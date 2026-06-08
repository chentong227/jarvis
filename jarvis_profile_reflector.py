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
# 🆕 [P5-fix81 / 2026-05-23 22:05] BUG-X Plan B — ProfileReflector 实时化
# Sir 真意 "我教过的东西除非重新修正不然不用改" — 24h tick 太慢, 5 阈值
# 太高. Sir 当晚教 cup_ml 24h 后才 propose 已经丢窗口. 修法: 5min + 1 阈值,
# 高置信 (≥0.85, fast_call_mutation/sir_cli) 直接 overwrite_field 跳 review.
_DEFAULT_TICK_INTERVAL_S = 300.0  # 5min (was 24h)
_DEFAULT_MIN_CORRECTIONS = 1  # 累积 1 条就 propose (was 5)
_DEFAULT_AUTO_APPLY_CONF = 0.85  # 高置信跳 review 直接写


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

    def propose_from_corrections(self, use_llm: bool = True) -> List[ProfileProposal]:
        """Propose changes from accumulated ProfileCorrections.

        🩹 [P3-BUG#3 / 2026-05-20 23:45] 真 LLM-propose 升级:
          Phase 1 (aggregation): group corrections by field, count freq
          Phase 2 (LLM judge): 复用 LlmReflector. 看 grouped + sir_profile current
                              snapshot, LLM 决定 propose action (modify/add/remove)
                              + rationale.
          use_llm=False: 走老 aggregation stub (testcase 隔离用)

        Sir CLI --activate 后, 仍只改 review queue. 真 apply sir_profile.json 留
        P4 sprint (要含 .bak.YYYYMMDD_HHMM 备份 + Sir 二次确认).
        """
        corrections = self._scan_corrections()
        if len(corrections) < self.min_corrections:
            return []

        # Phase 1: aggregate by field
        by_field: Dict[str, List[dict]] = {}
        for c in corrections:
            fld = c.get('field', '')
            if not fld:
                continue
            by_field.setdefault(fld, []).append(c)

        # filter: only fields with >= 3 occurrences
        candidate_fields = {fld: g for fld, g in by_field.items() if len(g) >= 3}
        if not candidate_fields:
            return []

        # skip if any candidate already has open proposal
        candidate_fields = {
            fld: g for fld, g in candidate_fields.items()
            if not any(p.field_path == fld and p.state == 'review' for p in self._proposals)
        }
        if not candidate_fields:
            return []

        # Phase 2: LLM judge (or aggregation stub if use_llm=False)
        if use_llm:
            new_proposals = self._llm_propose(candidate_fields)
        else:
            new_proposals = self._aggregation_propose_stub(candidate_fields)

        with self._lock:
            self._proposals.extend(new_proposals)
            self._persist_review_queue()
        return new_proposals

    def _aggregation_propose_stub(self,
                                    candidate_fields: Dict[str, List[dict]]
                                    ) -> List[ProfileProposal]:
        """Stub aggregation (use_llm=False fallback)."""
        new_proposals = []
        for fld, group in candidate_fields.items():
            value_counts: Dict[str, int] = {}
            for c in group:
                v = str(c.get('new', ''))
                value_counts[v] = value_counts.get(v, 0) + 1
            top_value = max(value_counts.items(), key=lambda kv: kv[1])
            new_proposals.append(ProfileProposal(
                proposal_id=f'prop_{uuid.uuid4().hex[:8]}',
                field_path=fld,
                action='modify',
                new_value=top_value[0],
                rationale=(
                    f'[stub] Sir mentioned this {len(group)} times. '
                    f'Top value "{top_value[0][:40]}" {top_value[1]}x.'
                ),
                evidence_corrections=[str(c.get('ts', '?')) for c in group[-5:]],
                proposed_at=time.time(),
                state='review',
            ))
        return new_proposals

    def _llm_propose(self,
                      candidate_fields: Dict[str, List[dict]]) -> List[ProfileProposal]:
        """🩹 [P3-BUG#3 / 2026-05-20 23:45] 真 LLM-propose. 复用 LlmReflector cache."""
        try:
            from jarvis_llm_reflector import LlmReflector
        except Exception:
            return self._aggregation_propose_stub(candidate_fields)

        # 读 sir_profile 当前 snapshot (selected fields preview)
        current_profile_snippet = ''
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, 'r', encoding='utf-8') as f:
                    _profile_data = json.load(f) or {}
                # 仅取 candidate_fields 涉及的 keys preview
                _preview = {}
                for fld in list(candidate_fields.keys())[:8]:
                    _top = fld.split('.')[0]
                    if _top in _profile_data and _top not in _preview:
                        _preview[_top] = str(_profile_data[_top])[:300]
                current_profile_snippet = json.dumps(_preview, ensure_ascii=False, indent=2)[:1500]
            except Exception:
                current_profile_snippet = '(profile read failed)'

        # 构 LLM prompt
        evidence_summary = []
        for fld, group in list(candidate_fields.items())[:6]:
            recent_values = [str(c.get('new', ''))[:60] for c in group[-5:]]
            evidence_summary.append(
                f"  Field '{fld}' ({len(group)}x): recent values = {recent_values}"
            )
        evidence_text = '\n'.join(evidence_summary)

        prompt = f"""[ROLE] You are ProfileReflector. Sir has corrected himself N times in
recent days. You decide: should sir_profile.json be updated?

[CURRENT sir_profile.json snippet (relevant fields)]
{current_profile_snippet or '(empty)'}

[ACCUMULATED CORRECTIONS (>= 3 times each field)]
{evidence_text}

[YOUR JOB]
For each field, decide:
- action: 'modify' (change existing value) | 'add' (new field) | 'archive' (deprecated) | 'skip' (don't propose now)
- new_value: the final value (consolidate from recent values)
- confidence: 0.0-1.0
- rationale: 1-2 sentence why

[OUTPUT JSON ONLY, no markdown]
{{
  "proposals": [
    {{"field_path": "...", "action": "modify|add|archive|skip",
      "new_value": "...", "confidence": 0.8,
      "rationale": "..."}}
  ]
}}

If skip all: {{"proposals": []}}
"""

        reflector = LlmReflector()
        result = reflector.reflect(
            model='flash',
            system_prompt='You are ProfileReflector helping Sir evolve his personal profile.',
            user_prompt=prompt,
            cache_ttl=600,  # 10min cache same input
        )
        if not result or not result.get('success'):
            return self._aggregation_propose_stub(candidate_fields)

        # parse raw_text → JSON
        raw = (result.get('raw_text') or '').strip()
        if raw.startswith('```'):
            lines = raw.split('\n')
            if len(lines) >= 3:
                raw = '\n'.join(lines[1:-1])
        try:
            parsed = json.loads(raw)
            proposals_data = parsed.get('proposals', []) if isinstance(parsed, dict) else []
        except Exception:
            return self._aggregation_propose_stub(candidate_fields)

        new_proposals = []
        for pd in proposals_data[:6]:
            try:
                act = pd.get('action', 'modify')
                if act == 'skip':
                    continue
                fld = pd.get('field_path', '')
                if not fld or fld not in candidate_fields:
                    continue
                new_proposals.append(ProfileProposal(
                    proposal_id=f'prop_{uuid.uuid4().hex[:8]}',
                    field_path=fld,
                    action=act,
                    new_value=pd.get('new_value', ''),
                    rationale=f"[LLM conf={pd.get('confidence', 0.5)}] {pd.get('rationale', '')[:300]}",
                    evidence_corrections=[
                        str(c.get('ts', '?'))
                        for c in candidate_fields[fld][-5:]
                    ],
                    proposed_at=time.time(),
                    state='review',
                ))
            except Exception:
                continue
        return new_proposals

    def list_review(self) -> List[ProfileProposal]:
        with self._lock:
            return [p for p in self._proposals if p.state == 'review']

    # 🆕 [bugB(c) Part 2 / Sir 2026-06-08] activate 写回安全契约 helpers.
    # 保守白名单: 只放软纠正字段 (Sir 反复教正的事实/偏好/习惯 — 正是"读不回"痛点),
    # **显式排除核心身份/关系锚** (core_philosophy/idiosyncrasies/conversational_boundaries/
    # life_anchors/relationship_status/professional_role/work_rhythms — 误写代价高,
    # 首版 activate 不碰, 需更高门槛)。复用 overwrite_field 原子写, 不另造写路径。
    # ⚠️ 交叉验证不变式: 本 14 字段必须 ⊆ ProfileCard._OVERWRITE_ALLOWED_FIELDS (22),
    # 否则会"过本白名单 → overwrite_field 拒 → 谎称 applied"。已核 NOT_SUBSET=[] (全 ⊆),
    # 测 test_subset_of_overwrite_whitelist 守这条不变式; 未来给本表加字段必须同时
    # 在 overwrite 白名单, 否则该测红。
    _ACTIVATE_WRITEBACK_WHITELIST = frozenset({
        'preferred_tools', 'frequently_used_software', 'work_category',
        'current_priority', 'unit_preferences', 'health_goals',
        'health_concerns', 'sleep_target_hour', 'wake_target_hour',
        'nudge_frequency_default', 'communication_preferences',
        'location_general', 'languages', 'active_projects',
    })

    def _is_writeback_allowed(self, field_path: str) -> bool:
        """field_path 顶层段命中保守白名单才允许 activate 写回。
        嵌套 (unit_preferences.cup_ml) 取顶层 (unit_preferences) 判。"""
        if not field_path:
            return False
        top = field_path.split('.', 1)[0].strip()
        # preferences.X alias → unit_preferences (同 overwrite_field 范式)
        if top == 'preferences':
            top = 'unit_preferences'
        return top in self._ACTIVATE_WRITEBACK_WHITELIST

    def _backup_profile(self) -> str:
        """写前时间戳备份 sir_profile.json → .bak.<ts>。返备份路径 (失败返 '')。"""
        try:
            if not os.path.exists(self.profile_path):
                return ''
            import shutil
            ts = time.strftime('%Y%m%d_%H%M%S')
            backup_path = f"{self.profile_path}.bak.{ts}"
            shutil.copy2(self.profile_path, backup_path)
            return backup_path
        except Exception:
            return ''

    def _writeback_via_profile_card(self, field_path: str, new_value,
                                    proposal_id: str):
        """复用 ProfileCard.overwrite_field 原子写 (tmp+rename+白名单+缓存失效)。
        返 (ok, msg, old_value)。无 profile_card → 拒 (不另造写路径)。"""
        pc = getattr(self.nerve, 'profile_card', None) if self.nerve else None
        if pc is None or not hasattr(pc, 'overwrite_field'):
            return False, 'no profile_card.overwrite_field', None
        # 剥 'profile.'/'preferences.' 前缀交 overwrite_field (它自己识 alias+嵌套)
        _path = field_path
        for _pfx in ('profile.', 'biographic.', 'sir.'):
            if _path.startswith(_pfx):
                _path = _path[len(_pfx):]
                break
        return pc.overwrite_field(
            field=_path, new_value=new_value,
            source='profile_reflector_activate',
            reason=f'Sir activated proposal {proposal_id}')

    def _audit(self, msg: str) -> None:
        """审计 trail → bg_log (进 runtime log + trace)。"""
        try:
            from jarvis_utils import bg_log
            bg_log(f"🪞 [ProfileReflector/activate] {msg}")
        except Exception:
            pass

    def _cleanup_orphan_backup(self, backup_path: str, old_value=None) -> None:
        """写失败时清理刚建的孤儿 .bak (写没成功, 备份无意义留存)。
        失败静默 (清理失败不影响主流, 仅审计)。"""
        if not backup_path:
            return
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except Exception as _e:
            self._audit(f"orphan .bak cleanup fail: {backup_path} ({_e})")

    def activate(self, proposal_id: str, decided_by: str = 'sir_cli') -> bool:
        """🆕 [bugB(c) Part 2 / Sir 2026-06-08] activate → 真写回 sir_profile.json.

        从"只翻 state"升级为经安全契约真写回 (闭合 bugB 后半环: corrections 读不回 →
        Sir activate 后真生效)。安全契约逐条:
          b. 白名单 — field_path 命中 _ACTIVATE_WRITEBACK_WHITELIST (软纠正字段子集,
             显式排除核心身份/关系锚) 才写; 非白名单 → state=rejected_non_whitelist。
          c. .bak — 写前时间戳备份 sir_profile.json.bak.<ts>。
          d. 原子写 — 复用 ProfileCard.overwrite_field (tmp+rename + 白名单 + 缓存失效),
             不另造平行白名单/写路径。首版只 set/overwrite 标量 (action modify/add);
             archive/remove 先拒 + state=rejected_unsupported_action。
          e. 缓存失效 — overwrite_field 末尾已 self._cache_time=0 (写后 retrieve 立读新值)。
          f. 幂等 — 已 applied 再 activate → no-op (不二次写/不新增 .bak)。
          g. 审计 — bg_log (proposal_id, field, old→new, backup_path)。
        红线: daemon 绝不自动调 activate; 只 CLI --activate (Sir 显式) 触发。
        """
        with self._lock:
            target = None
            for p in self._proposals:
                if p.proposal_id == proposal_id:
                    target = p
                    break
            if target is None:
                return False
            # f. 幂等: 已终态 → no-op
            if target.state in ('applied', 'rejected', 'rejected_non_whitelist',
                                 'rejected_unsupported_action'):
                return target.state == 'applied'
            if target.state not in ('review', 'active'):
                return False

            # d-pre. action 限制: 首版只支持 modify/add 标量 set
            if target.action not in ('modify', 'add'):
                target.state = 'rejected_unsupported_action'
                target.decided_at = time.time()
                target.decided_by = decided_by
                self._persist_review_queue()
                self._audit(f"activate REJECT {proposal_id}: unsupported action "
                            f"'{target.action}' (仅 modify/add)")
                return False

            # b. 白名单校验
            if not self._is_writeback_allowed(target.field_path):
                target.state = 'rejected_non_whitelist'
                target.decided_at = time.time()
                target.decided_by = decided_by
                self._persist_review_queue()
                self._audit(f"activate REJECT {proposal_id}: field "
                            f"'{target.field_path}' 非 activate 写回白名单 (核心身份/关系锚不开)")
                return False

            # c. .bak 备份 (写前; 若写失败 → 清理孤儿 .bak)
            backup_path = self._backup_profile()

            # d. 原子写 (复用 ProfileCard.overwrite_field — 含原子写+白名单+缓存失效)
            ok, msg, old_value = self._writeback_via_profile_card(
                target.field_path, target.new_value, proposal_id)
            if not ok:
                # 🔴 红线: 写没成功**绝不**标 applied (那就是本链在治的"声称做了没做")。
                # overwrite_field 白名单拒 / 写盘失败 / 任何原因 ok=False →
                # state='writeback_failed' + 审计失败原因 + 清理刚建的孤儿 .bak。
                self._cleanup_orphan_backup(backup_path, old_value=None)
                target.state = 'writeback_failed'
                target.decided_at = time.time()
                target.decided_by = decided_by
                self._persist_review_queue()
                self._audit(f"activate WRITE-FAIL {proposal_id}: {msg} "
                            f"→ state=writeback_failed (孤儿 .bak 已清)")
                return False

            # f/g. 成功 → applied + 审计
            target.old_value = old_value
            target.state = 'applied'
            target.decided_at = time.time()
            target.decided_by = decided_by
            self._persist_review_queue()
            self._audit(
                f"activate APPLIED {proposal_id}: {target.field_path} "
                f"'{str(old_value)[:40]}' → '{str(target.new_value)[:40]}' "
                f"(backup={backup_path})")
            return True



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
