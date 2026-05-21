# -*- coding: utf-8 -*-
"""[Gap 5 / β.5.46-fix10 / 2026-05-22 00:10] L8 Reject Learner — 闭环演化层.

Sir 在 dashboard /items 评 reply 👎 / silent_wanted / edit, 这反馈进
memory_pool/reply_feedback.jsonl 但**没自动 propose directive 修订**. 这是
Sir 反馈→系统改进的最后一公里没接.

== 治法 ==

L8 RejectLearner daemon 周期性 (每 4h):
  1. 读最近 24h reply_feedback.jsonl
  2. 过滤 verdict in (bad, silent_wanted, edit) 反馈
  3. 如 < min_reject_count → skip
  4. LLM judge 看 reply 内容 + sir_note → propose:
       a. directive_amend: 改老 directive 文本
       b. new_directive: 加新 directive
       c. directive_retire: 退役老 directive
       d. sentinel_tune: 改 sentinel gate_mode
  5. 写 memory_pool/reject_review.json
  6. Sir CLI scripts/reject_learner_dump.py --list/--accept/--reject 拍板

== 准则合规 ==

- 准则 1 (TTFT): daemon 周期跑, 不阻 stream
- 准则 6 (拒绝硬编码): LLM propose, 不写死规则
- 准则 6.5: config + propose review 持久化
- 准则 7 (Sir 元否决): 只 propose 不自动 apply, Sir 拍板

== 文件 ==

- 读: memory_pool/reply_feedback.jsonl
- 写: memory_pool/reject_review.json (propose queue)
- config: memory_pool/reject_learner_config.json
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional


_THIS = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_THIS, 'memory_pool', 'reject_learner_config.json')
_FEEDBACK_PATH = os.path.join(_THIS, 'memory_pool', 'reply_feedback.jsonl')
_REVIEW_PATH = os.path.join(_THIS, 'memory_pool', 'reject_review.json')


_FALLBACK_CONFIG = {
    'enabled': True,
    'cycle_interval_hours': 4.0,
    'lookback_hours': 24.0,
    'min_reject_count': 3,
    'model': 'flash_lite',
    'cooldown_after_propose_hours': 12.0,
}


def _load_config() -> Dict[str, Any]:
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                merged = dict(_FALLBACK_CONFIG)
                for k, v in cfg.items():
                    if not k.startswith('_'):
                        merged[k] = v
                return merged
    except Exception:
        pass
    return dict(_FALLBACK_CONFIG)


def is_enabled() -> bool:
    val = os.environ.get('JARVIS_REJECT_LEARNER', '').strip()
    if val == '0':
        return False
    if val == '1':
        return True
    return bool(_load_config().get('enabled', True))


# ============================================================
# Read feedback + filter rejects
# ============================================================

def _read_recent_rejects(hours: float = 24.0) -> List[Dict[str, Any]]:
    """读最近 hours 内 verdict in (bad, silent_wanted, edit) 的 entry."""
    if not os.path.exists(_FEEDBACK_PATH):
        return []
    cutoff = time.time() - hours * 3600
    rejects = []
    try:
        with open(_FEEDBACK_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                ts = float(entry.get('ts', 0))
                if ts < cutoff:
                    continue
                verdict = entry.get('verdict', '')
                if verdict in ('bad', 'silent_wanted', 'edit'):
                    rejects.append(entry)
    except Exception:
        pass
    return rejects


# ============================================================
# Review queue
# ============================================================

def _load_review_queue() -> List[Dict[str, Any]]:
    if not os.path.exists(_REVIEW_PATH):
        return []
    try:
        with open(_REVIEW_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_review_queue(queue: List[Dict[str, Any]]) -> bool:
    try:
        os.makedirs(os.path.dirname(_REVIEW_PATH), exist_ok=True)
        tmp = _REVIEW_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _REVIEW_PATH)
        return True
    except Exception:
        return False


def _propose_id(rejects: List[Dict[str, Any]]) -> str:
    """生成 propose id 基于 rejects (去重)."""
    sig = '|'.join(
        f"{e.get('ts', 0):.0f}_{e.get('verdict', '')}_{(e.get('reply_excerpt', '') or '')[:30]}"
        for e in rejects
    )
    return 'rl_' + hashlib.md5(sig.encode('utf-8', 'ignore')).hexdigest()[:12]


# ============================================================
# LLM propose prompt
# ============================================================

_PROPOSE_PROMPT = """You are Jarvis's L8 Reject Learner. Sir gave negative feedback on these recent replies:

[REJECTED REPLIES (last {hours}h)]
{rejects_block}

[YOUR TASK]
Analyze pattern across these rejects. Propose ONE concrete improvement (not a list).
Output strict JSON, no preamble:

{{
  "propose_type": "directive_amend" | "new_directive" | "directive_retire" | "sentinel_tune" | "no_action",
  "rationale": "one short English sentence why",
  "target": "directive id or sentinel name (empty for new_directive / no_action)",
  "delta": "what to change (e.g. 'remove ritual phrase X' / 'add trigger condition Y' / 'change gate from hard to soft')",
  "confidence": 0.0-1.0
}}

If pattern unclear or only 1-2 reject, use propose_type="no_action".
Be conservative — Sir has final say (this just enters review queue)."""


# ============================================================
# RejectLearner main class
# ============================================================

class RejectLearner:
    """L8 闭环演化 — 周期性扫 reject feedback, LLM propose, Sir 拍板."""

    def __init__(self, key_router: Optional[Any] = None):
        self.key_router = key_router
        self.cfg = _load_config()
        self._lock = threading.Lock()
        self._daemon_running = False
        self._daemon_thread: Optional[threading.Thread] = None
        self._last_cycle_ts = 0.0
        self._stats = {
            'cycles_run': 0,
            'proposes_generated': 0,
            'no_action': 0,
            'llm_failures': 0,
            'last_cycle_iso': '',
        }

    def run_cycle(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """跑一次 cycle. Returns propose dict (写 review queue) or None."""
        with self._lock:
            if self._daemon_running and not force:
                return None
            self._stats['cycles_run'] += 1
            self._stats['last_cycle_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')

        rejects = _read_recent_rejects(hours=self.cfg.get('lookback_hours', 24.0))
        min_count = int(self.cfg.get('min_reject_count', 3))
        if len(rejects) < min_count:
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"📊 [RejectLearner] cycle: only {len(rejects)} rejects "
                    f"(< {min_count}), skip"
                )
            except Exception:
                pass
            return None

        # cooldown check — 12h 内 propose 过相同 sig 跳过
        prop_id = _propose_id(rejects)
        existing = _load_review_queue()
        cooldown_s = self.cfg.get('cooldown_after_propose_hours', 12.0) * 3600
        for ex in existing:
            if ex.get('id') == prop_id:
                age = time.time() - float(ex.get('ts', 0))
                if age < cooldown_s:
                    return None

        # LLM propose
        proposal = self._llm_propose(rejects)
        if not proposal:
            with self._lock:
                self._stats['llm_failures'] += 1
            return None

        ptype = proposal.get('propose_type', 'no_action')
        if ptype == 'no_action':
            with self._lock:
                self._stats['no_action'] += 1
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"📊 [RejectLearner] propose=no_action ({len(rejects)} rejects)"
                )
            except Exception:
                pass
            return None

        # write to review queue
        entry = {
            'id': prop_id,
            'ts': time.time(),
            'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'reject_count': len(rejects),
            'reject_excerpts': [
                {
                    'verdict': r.get('verdict', ''),
                    'excerpt': (r.get('reply_excerpt', '') or '')[:120],
                    'sir_note': (r.get('sir_note', '') or '')[:120],
                }
                for r in rejects[:5]
            ],
            'propose': proposal,
            'status': 'pending',
        }
        existing.append(entry)
        _save_review_queue(existing)
        with self._lock:
            self._stats['proposes_generated'] += 1
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"📝 [RejectLearner] propose written: {prop_id} "
                f"type={ptype} target='{proposal.get('target', '')[:30]}' "
                f"conf={proposal.get('confidence', 0):.2f}"
            )
        except Exception:
            pass
        return entry

    def _llm_propose(self, rejects: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """LLM 看 rejects propose 改进."""
        if self.key_router is None:
            return None
        rejects_block = ''
        for i, r in enumerate(rejects[:10]):
            v = r.get('verdict', '')
            excerpt = (r.get('reply_excerpt', '') or '')[:120]
            note = (r.get('sir_note', '') or '')[:120]
            rejects_block += f"[{i+1}] verdict={v} | reply: {excerpt}"
            if note:
                rejects_block += f" | Sir note: {note}"
            rejects_block += '\n'
        prompt = _PROPOSE_PROMPT.format(
            hours=self.cfg.get('lookback_hours', 24.0),
            rejects_block=rejects_block,
        )
        try:
            from jarvis_utils import safe_openrouter_call
            okey, _label = self.key_router.get_openrouter_key(
                caller='reject_learner')
            _model_map = {
                'flash_lite': 'google/gemini-2.5-flash-lite-preview-09-2025',
                'flash': 'google/gemini-2.5-flash-preview-09-2025',
            }
            _model = _model_map.get(
                self.cfg.get('model', 'flash_lite'),
                _model_map['flash_lite'])
            response_text = safe_openrouter_call(
                openrouter_key=okey,
                model=_model,
                prompt=prompt,
                max_tokens=400,
                temperature=0.2,
            )
            txt = (response_text or '').strip()
            if txt.startswith('```'):
                lines = txt.split('\n')
                if len(lines) >= 3:
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            if not isinstance(parsed, dict):
                return None
            # validate propose_type
            ptype = parsed.get('propose_type', 'no_action')
            if ptype not in ('directive_amend', 'new_directive',
                             'directive_retire', 'sentinel_tune', 'no_action'):
                ptype = 'no_action'
            parsed['propose_type'] = ptype
            return parsed
        except Exception:
            return None

    def start_daemon(self) -> None:
        """启动 daemon thread (每 cycle_interval_hours 跑一次)."""
        if self._daemon_thread is not None and self._daemon_thread.is_alive():
            return
        if not is_enabled():
            return

        def _loop():
            interval_s = float(self.cfg.get('cycle_interval_hours', 4.0)) * 3600.0
            # 启动等 60s 让其他模块就绪
            time.sleep(60.0)
            while True:
                try:
                    self.run_cycle()
                except Exception:
                    pass
                # check enabled 每 cycle (Sir 可热关)
                if not is_enabled():
                    break
                time.sleep(max(60.0, interval_s))

        self._daemon_thread = threading.Thread(
            target=_loop, daemon=True, name='RejectLearnerDaemon')
        self._daemon_thread.start()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ============================================================
# Global registry
# ============================================================

_DEFAULT_LEARNER: Optional[RejectLearner] = None
_INIT_LOCK = threading.Lock()


def get_default_learner() -> Optional[RejectLearner]:
    return _DEFAULT_LEARNER


def register_learner(learner: RejectLearner) -> None:
    global _DEFAULT_LEARNER
    with _INIT_LOCK:
        _DEFAULT_LEARNER = learner


def reset_default_learner_for_test() -> None:
    global _DEFAULT_LEARNER
    with _INIT_LOCK:
        _DEFAULT_LEARNER = None


# ============================================================
# Sir CLI helpers
# ============================================================

def list_review_queue() -> List[Dict[str, Any]]:
    """Sir CLI 用. 列待 review 的 propose."""
    return [e for e in _load_review_queue() if e.get('status') == 'pending']


def update_review_status(propose_id: str, new_status: str,
                          sir_note: str = '') -> bool:
    """Sir CLI 用. 标 propose accepted/rejected."""
    if new_status not in ('accepted', 'rejected', 'pending'):
        return False
    queue = _load_review_queue()
    found = False
    for entry in queue:
        if entry.get('id') == propose_id:
            entry['status'] = new_status
            entry['sir_decision_ts'] = time.time()
            entry['sir_decision_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            if sir_note:
                entry['sir_note'] = sir_note[:300]
            found = True
    if found:
        _save_review_queue(queue)
    return found
