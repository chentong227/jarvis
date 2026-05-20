# -*- coding: utf-8 -*-
"""[P2-Gap11 / 2026-05-21 00:10] ProfileReflector — sir_profile.json 真演化

Sir 真痛点: sir_profile.json 是**静态**手工维护, 全工程无任何 write path 改它.
Sir 跟 Jarvis 说 30 次 "我搬家了 / 改身高" 全部漂移. ProfileCard.apply_correction
只 append profile_corrections.jsonl, 主档案永远不动.

修法 (本模块):
  - daemon (默认不启, env JARVIS_PROFILE_REFLECTOR=1 启)
  - 周期 (default 24h tick) 扫 profile_corrections.jsonl 累积条目
  - LLM 看累积 corrections + STM + Concerns, propose sir_profile.json 改动
  - 写 review queue memory_pool/profile_review.json
  - Sir CLI scripts/profile_reflector_dump.py 看 + activate / reject

⚠️ MINIMAL VIABLE 版本范围:
  - daemon 框架 + LLM propose stub (返 placeholder)
  - review queue persist
  - CLI list / activate / reject
  - 真实施完整 LLM propose 留 P3 sprint (要慎重, sir_profile 是 Sir IP)

Sir 准则 6 binding:
  ✅ 数据 publish — review queue 持久化, CLI 可看
  ✅ 决策让 LLM (propose), Sir 仲裁 (activate/reject)
  ✅ 持久化 + CLI 可改
  ✅ 跟现有 layer 正交
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


_DEFAULT_REVIEW_PATH = os.path.join('memory_pool', 'profile_review.json')
_DEFAULT_CORRECTIONS_PATH = os.path.join('memory_pool', 'profile_corrections.jsonl')
_DEFAULT_PROFILE_PATH = os.path.join('jarvis_config', 'sir_profile.json')
_DEFAULT_TICK_INTERVAL_S = 86400.0  # 24h
_DEFAULT_MIN_CORRECTIONS = 5  # 累积 5 条 corrections 才 propose


@dataclass
class ProfileProposal:
    """LLM 建议的 sir_profile.json 改动."""
    proposal_id: str
    field_path: str             # 'active_projects' / 'skill_domains' / 'biographic.height'
    action: str                 # 'add' / 'modify' / 'archive' / 'remove'
    new_value: Any
    old_value: Any = ''
    rationale: str = ''         # LLM 解释为何 propose 这改动
    evidence_corrections: List[str] = field(default_factory=list)  # mutation_id list
    proposed_at: float = 0.0
    state: str = 'review'       # 'review' / 'active' / 'rejected'
    decided_at: float = 0.0
    decided_by: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


class ProfileReflector:
    """LLM-driven proposal for sir_profile.json evolution. Daemon mode."""

    def __init__(self,
                 review_path: Optional[str] = None,
                 corrections_path: Optional[str] = None,
                 profile_path: Optional[str] = None,
                 tick_interval_s: float = _DEFAULT_TICK_INTERVAL_S,
                 min_corrections: int = _DEFAULT_MIN_CORRECTIONS,
                 nerve=None):
        self.review_path = review_path or _DEFAULT_REVIEW_PATH
        self.corrections_path = corrections_path or _DEFAULT_CORRECTIONS_PATH
        self.profile_path = profile_path or _DEFAULT_PROFILE_PATH
        self.tick_interval_s = tick_interval_s
        self.min_corrections = min_corrections
        self.nerve = nerve
        self._lock = threading.Lock()
        self._proposals: List[ProfileProposal] = []
        self._daemon_running = False
        self._stop_flag = threading.Event()
        self._load_review_queue()

    def _load_review_queue(self) -> None:
        if not os.path.exists(self.review_path):
            return
        try:
            with open(self.review_path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            for d in (data.get('proposals') or []):
                try:
                    p = ProfileProposal(**d)
                    self._proposals.append(p)
                except Exception:
                    continue
        except Exception:
            pass

    def _persist_review_queue(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.review_path), exist_ok=True)
            tmp = self.review_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({
                    'proposals': [p.to_dict() for p in self._proposals],
                    '_meta': {
                        'persisted_at': time.time(),
                        'persisted_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                       time.localtime()),
                    },
                }, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.review_path)
        except Exception:
            pass

    def _scan_corrections(self) -> List[dict]:
        """读 profile_corrections.jsonl tail."""
        if not os.path.exists(self.corrections_path):
            return []
        try:
            with open(self.corrections_path, 'r', encoding='utf-8') as f:
                lines = [ln.strip() for ln in f if ln.strip()]
        except Exception:
            return []
        out = []
        for ln in lines[-200:]:  # last 200 corrections
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out

    def propose_from_corrections(self) -> List[ProfileProposal]:
        """LLM propose changes. MINIMAL: only stub LLM call, real impl 留 P3.

        Real impl will:
          - aggregate corrections by field_path
          - count repetition (Sir said X 5 times → high confidence propose modify)
          - LLM judge: should sir_profile.json field X change to Y? rationale?
        """
        corrections = self._scan_corrections()
        if len(corrections) < self.min_corrections:
            return []

        # MINIMAL: aggregate by field, group >= 3 occurrences propose
        by_field: Dict[str, List[dict]] = {}
        for c in corrections:
            fld = c.get('field', '')
            if not fld:
                continue
            by_field.setdefault(fld, []).append(c)

        new_proposals = []
        for fld, group in by_field.items():
            if len(group) < 3:
                continue
            # check if this field already has open proposal
            if any(p.field_path == fld and p.state == 'review' for p in self._proposals):
                continue
            # most-frequent new_value
            value_counts: Dict[str, int] = {}
            for c in group:
                v = str(c.get('new', ''))
                value_counts[v] = value_counts.get(v, 0) + 1
            top_value = max(value_counts.items(), key=lambda kv: kv[1])
            prop = ProfileProposal(
                proposal_id=f'prop_{uuid.uuid4().hex[:8]}',
                field_path=fld,
                action='modify',
                new_value=top_value[0],
                old_value='',  # could read sir_profile to get
                rationale=(
                    f'Sir mentioned this {len(group)} times in corrections '
                    f'(top value "{top_value[0][:40]}" {top_value[1]}x). '
                    f'Consider updating sir_profile.json {fld}.'
                ),
                evidence_corrections=[c.get('ts', '?') for c in group[-5:]],
                proposed_at=time.time(),
                state='review',
            )
            new_proposals.append(prop)

        with self._lock:
            self._proposals.extend(new_proposals)
            self._persist_review_queue()
        return new_proposals

    def list_review(self) -> List[ProfileProposal]:
        with self._lock:
            return [p for p in self._proposals if p.state == 'review']

    def activate(self, proposal_id: str, decided_by: str = 'sir_cli') -> bool:
        with self._lock:
            for p in self._proposals:
                if p.proposal_id == proposal_id and p.state == 'review':
                    p.state = 'active'
                    p.decided_at = time.time()
                    p.decided_by = decided_by
                    self._persist_review_queue()
                    # NOTE: real sir_profile.json mutation NOT done in MINIMAL.
                    # Caller (Sir CLI) writes profile manually after seeing approved.
                    return True
        return False

    def reject(self, proposal_id: str, decided_by: str = 'sir_cli') -> bool:
        with self._lock:
            for p in self._proposals:
                if p.proposal_id == proposal_id and p.state == 'review':
                    p.state = 'rejected'
                    p.decided_at = time.time()
                    p.decided_by = decided_by
                    self._persist_review_queue()
                    return True
        return False

    def stats(self) -> dict:
        with self._lock:
            return {
                'total': len(self._proposals),
                'review': sum(1 for p in self._proposals if p.state == 'review'),
                'active': sum(1 for p in self._proposals if p.state == 'active'),
                'rejected': sum(1 for p in self._proposals if p.state == 'rejected'),
            }

    # ===== Daemon =====

    def start_daemon(self) -> None:
        """Start background tick. Default off (env JARVIS_PROFILE_REFLECTOR=1)."""
        if os.environ.get('JARVIS_PROFILE_REFLECTOR') != '1':
            return
        if self._daemon_running:
            return
        self._daemon_running = True

        def _loop():
            try:
                from jarvis_utils import bg_log
                bg_log(f"🪞 [ProfileReflector] daemon started (tick={self.tick_interval_s}s)")
            except Exception:
                pass
            while not self._stop_flag.is_set():
                try:
                    new_props = self.propose_from_corrections()
                    if new_props:
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"🪞 [ProfileReflector] proposed {len(new_props)} changes")
                        except Exception:
                            pass
                except Exception:
                    pass
                self._stop_flag.wait(self.tick_interval_s)

        t = threading.Thread(target=_loop, daemon=True, name='ProfileReflector')
        t.start()

    def stop_daemon(self) -> None:
        self._stop_flag.set()
        self._daemon_running = False


_DEFAULT_REFLECTOR: Optional[ProfileReflector] = None
_LOCK = threading.Lock()


def get_default_reflector() -> ProfileReflector:
    global _DEFAULT_REFLECTOR
    with _LOCK:
        if _DEFAULT_REFLECTOR is None:
            _DEFAULT_REFLECTOR = ProfileReflector()
        return _DEFAULT_REFLECTOR


def reset_default_reflector_for_test() -> None:
    global _DEFAULT_REFLECTOR
    with _LOCK:
        _DEFAULT_REFLECTOR = None
