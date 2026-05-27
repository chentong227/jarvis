# -*- coding: utf-8 -*-
"""[β.5.44-D / 2026-05-20 19:02] TOOL_REGISTRY — IntentResolver 调度的 mutation tool

Sir 18:55 真理: 每个 input module 散落 mutate state → 主脑不知道谁真改了 → 撒谎.

修法: 所有 mutation 集中在 TOOL_REGISTRY, IntentResolver LLM 调度. 每个 tool fn:
  - 接 **kwargs
  - 返 dict {'ok': bool, 'result': any, 'error': str}
  - 真 mutate state (写 ConcernsLedger / MemoryStore / CommitWatcher / ProfileCard)

主脑看 tool_called SWM 知道哪个 tool 真成功, 不再撒谎"已 corrected".

doc: docs/JARVIS_INTENT_RESOLVER_REFACTOR.md
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional  # noqa: F401


# ============================================================
# Tool implementations
# Each: returns {'ok': bool, 'result': str, 'error': str}
# ============================================================

def _ok(result: str = '') -> Dict[str, Any]:
    return {'ok': True, 'result': str(result)[:200], 'error': ''}


def _fail(error: str) -> Dict[str, Any]:
    return {'ok': False, 'result': '', 'error': str(error)[:200]}


# ---------------- Concern Progress Tool ----------------

def tool_concern_progress_update(
    concern_id: str,
    current: Optional[float] = None,
    progress: Optional[float] = None,   # 🩹 [P0] alias 1
    value: Optional[float] = None,      # 🩹 [P3 BUG#5] alias 2
    count: Optional[float] = None,      # 🩹 [P3 BUG#5] alias 3
    amount: Optional[float] = None,     # 🩹 [P3 BUG#5] alias 4
    done: Optional[float] = None,       # 🩹 [P3 BUG#5] alias 5
    target: float = 0,
    unit: str = '',
    raw_text: str = '',
    severity_delta: float = 0.0,
    optimal_timing: str = '',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """update Sir's progress on a concern. Pass 'current' (preferred) or aliases 'progress/value/count/amount/done'.

    Args: concern_id (req), current/progress/value/count/amount/done (opt — pick one), target (opt), unit (opt).
    Example (preferred): {concern_id: 'sir_hydration_habit', current: 8, target: 8, unit: '杯'}
    Aliases (LLM may use any): progress/value/count/amount/done — all map to current internally.

    Sir reports progress → real mutation in ConcernsLedger.daily_progress + severity.
    """
    if not concern_id:
        return _fail('concern_id required')
    # 🩹 [P0+P3 BUG#5] current alias resolution — LLM often picks any of these names
    if current is None:
        for _alias in (progress, value, count, amount, done):
            if _alias is not None:
                current = _alias
                break
    if current is None and not raw_text and severity_delta == 0.0:
        return _fail('require at least one of: current/progress/value/count/amount/done, raw_text, severity_delta')
    try:
        if nerve is None:
            try:
                import jarvis_central_nerve as _cn
                nerve = getattr(_cn, '_GLOBAL_NERVE', None)
            except Exception:
                nerve = None
        ledger = getattr(nerve, 'concerns_ledger', None) if nerve else None
        if ledger is None:
            return _fail('no concerns_ledger')
        # 🆕 [Sir 2026-05-27 21:34 真测 P4] target fallback + linear severity_delta
        # 主脑常 omit target / severity_delta=0 (default), 没 fallback → severity
        # 不动. 治本: lookup ledger daily_progress.target + 用 helper.
        _tgt_f = float(target) if target else None
        if _tgt_f is None or _tgt_f <= 0:
            try:
                _c = ledger.get(concern_id)
                _dp = (_c.daily_progress if _c else None) or {}
                _stored = _dp.get('target')
                if _stored is not None and float(_stored) > 0:
                    _tgt_f = float(_stored)
            except Exception:
                pass
        # 主脑没传 severity_delta (=default 0.0) → 用 helper 算 linear
        _sev_d = float(severity_delta)
        if abs(_sev_d) < 1e-6 and current is not None:
            try:
                from jarvis_concerns import (
                    compute_severity_delta_from_progress as _csev,
                )
                _sev_d = _csev(float(current), _tgt_f)
            except Exception:
                pass
        judgement = {
            'has_relevance': True,
            'severity_delta': _sev_d,
            'optimal_timing': optimal_timing,
        }
        if current is not None:
            judgement['progress'] = {
                'current': current,
                'target': _tgt_f if _tgt_f else target,
                'unit': unit,
            }
        ok = ledger.record_user_feedback(concern_id, raw_text or '', judgement)
        if ok:
            _desc = f'{current}/{target} {unit}'.strip() if current is not None else 'signal-only'
            return _ok(f'concern {concern_id} updated: {_desc}')
        return _fail(f'ledger.record_user_feedback rejected (concern {concern_id} not found?)')
    except Exception as e:
        return _fail(f'exception: {e}')


# ---------------- Memory Correction Tool ----------------

def tool_memory_correction_apply(
    old_value: str,
    new_value: str,
    field_hint: str = '',
    raw_text: str = '',
    confidence: float = 0.9,  # 🩹 [P0 / 2026-05-20 23:15] IntentResolver LLM judged → default high
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Sir corrected a previously recorded memory (e.g. '9 cups' → '8 cups').

    Args: old_value (prior), new_value (corrected), field_hint (which field, e.g. 'hydration_count').
    Real mutation: write to memory_pool/profile_corrections.jsonl via ProfileCard.apply_correction.
    """
    if not new_value:
        return _fail('new_value required')
    try:
        if nerve is None:
            import jarvis_central_nerve as _cn
            nerve = getattr(_cn, '_GLOBAL_NERVE', None)
        profile = getattr(nerve, 'profile_card', None) if nerve else None
        if profile is None:
            return _fail('no profile_card')
        if hasattr(profile, 'apply_correction'):
            try:
                # 🩹 [P0 / 2026-05-20 23:15] FIX: signature was wrong — ProfileCard.apply_correction
                # signature is (source_module, field, old_value, new_value, confidence), NOT
                # (field_hint, new_value, raw_text). Caused 100% TypeError silent fail.
                profile.apply_correction(
                    source_module='intent_resolver',
                    field=field_hint or 'memory_correction',
                    old_value=str(old_value or '')[:100],
                    new_value=str(new_value)[:100],
                    confidence=float(confidence),
                )
                return _ok(f'corrected: {old_value} → {new_value} (field={field_hint or "memory_correction"})')
            except Exception as e:
                return _fail(f'profile.apply_correction failed: {e}')
        return _fail('profile_card has no apply_correction')
    except Exception as e:
        return _fail(f'exception: {e}')


# ---------------- Commitment Register Tool ----------------

def tool_commitment_register(
    description: str,
    deadline_str: str = '',
    raw_text: str = '',
    author: str = 'sir',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Sir made an explicit commitment with a deadline (e.g. '我 11 点睡').
    
    Real mutation: register in CommitmentWatcher DB with deadline.
    """
    if not description:
        return _fail('description required')
    try:
        if nerve is None:
            import jarvis_central_nerve as _cn
            nerve = getattr(_cn, '_GLOBAL_NERVE', None)
        cw = getattr(nerve, 'commitment_watcher', None) if nerve else None
        if cw is None:
            return _fail('no commitment_watcher')
        if hasattr(cw, 'register_commitment'):
            try:
                cw.register_commitment(
                    description=description,
                    deadline_str=deadline_str,
                    raw_text=raw_text,
                    author=author,
                )
                return _ok(f'commitment registered: {description} @ {deadline_str}')
            except Exception as e:
                return _fail(f'cw.register failed: {e}')
        return _fail('commitment_watcher has no register_commitment')
    except Exception as e:
        return _fail(f'exception: {e}')


# ---------------- Self Promise Register Tool ----------------

def tool_self_promise_register(
    description: str,
    deadline_str: str = '',
    kind: str = 'soft',
    jarvis_reply: str = '',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Jarvis made a promise (e.g. 'I'll remind you at 11pm'). Register in PromiseLog."""
    if not description:
        return _fail('description required')
    try:
        if nerve is None:
            import jarvis_central_nerve as _cn
            nerve = getattr(_cn, '_GLOBAL_NERVE', None)
        plog = getattr(nerve, 'promise_log', None) if nerve else None
        if plog is None:
            # fallback get default
            try:
                from jarvis_promise_log import get_default_promise_log
                plog = get_default_promise_log()
            except Exception:
                return _fail('no promise_log')
        if hasattr(plog, 'register'):
            pid = plog.register(
                description=description,
                kind=kind,
                deadline_str=deadline_str,
                jarvis_reply=jarvis_reply,
                author='jarvis',
            )
            return _ok(f'promise {pid} registered (kind={kind})')
        return _fail('promise_log has no register')
    except Exception as e:
        return _fail(f'exception: {e}')


# ---------------- Profile Field Update Tool ----------------

def tool_profile_field_update(
    field_path: str,
    value: Any,
    old_value: str = '',
    raw_text: str = '',
    confidence: float = 0.9,  # 🩹 [P0 / 2026-05-20 23:15] IntentResolver judged → high default
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Sir gave a profile field update (e.g. field_path='preferences.height', value='1.83m').

    Args: field_path (which profile field, dot-notation), value (new value), old_value (optional prior).
    Real mutation: append to memory_pool/profile_corrections.jsonl via ProfileCard.apply_correction.
    NOTE: Does NOT in-place mutate sir_profile.json (that's Sir's IP file, append-only audit log).
    Sir can review via dashboard or scripts/profile_corrections_dump.py.
    """
    if not field_path:
        return _fail('field_path required')
    try:
        if nerve is None:
            import jarvis_central_nerve as _cn
            nerve = getattr(_cn, '_GLOBAL_NERVE', None)
        profile = getattr(nerve, 'profile_card', None) if nerve else None
        if profile is None:
            return _fail('no profile_card')
        if hasattr(profile, 'apply_correction'):
            try:
                # 🩹 [P0 / 2026-05-20 23:15] FIX: signature was wrong — same as tool_memory_correction_apply
                profile.apply_correction(
                    source_module='intent_resolver',
                    field=field_path,
                    old_value=str(old_value or '')[:100],
                    new_value=str(value)[:100],
                    confidence=float(confidence),
                )
                return _ok(f'profile field {field_path} = {str(value)[:60]} (logged to corrections.jsonl)')
            except Exception as e:
                return _fail(f'profile.apply_correction failed: {e}')
        return _fail('profile_card has no apply_correction')
    except Exception as e:
        return _fail(f'exception: {e}')


# ---------------- Milestone Register Tool (β.5.45) ----------------

def tool_milestone_register(
    text: str,
    title: str = '',
    context: str = '',
    tags: Any = None,
    pin: bool = False,
    instruction_for_jarvis: str = '',
    mtype: str = 'declaration',
    speaker: str = 'sir',
    language: str = 'zh',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Sir lifetime anchor request. Triggers: 'remember/store/keep forever/记住/铭记/记到海马体'. NOT commitment, NOT task.

    LLM-judge trigger semantics (IntentResolver decides):
      Sir says: 'remember this moment / 记住此刻 / lifetime anchor / 铭记 /
                 keep this forever / 记到海马体 / never forget this / 一辈子记着 ...'
    AND content is a personal declaration / insight / wish (not a task/reminder/promise).

    Real mutation: append to memory_pool/sir_milestones.json via
    jarvis_milestones.add_milestone (atomic write, dedupe by id).

    Default behavior (准则 6 #1):
      - do_not_use_against_sir = True (never weaponize in Sir's low moments)
      - replay_only_when_sir_asks = True (gentle replay only on Sir's ask)
      - pin = False (caller can override; pinned -> always in prompt block)
    """
    if not text or not text.strip():
        return _fail('text required (non-empty)')
    try:
        from jarvis_milestones import add_milestone as _add_milestone
    except Exception as e:
        return _fail(f'import jarvis_milestones failed: {e}')
    entry = {
        'text': text.strip(),
        'title': (title or '').strip(),
        'context': (context or '').strip(),
        'tags': list(tags) if isinstance(tags, (list, tuple)) else [],
        'pin': bool(pin),
        'instruction_for_jarvis': (instruction_for_jarvis or '').strip(),
        'type': mtype or 'declaration',
        'speaker': speaker or 'sir',
        'language': language or 'zh',
        'created_by': 'intent_resolver',
    }
    try:
        new_id = _add_milestone(entry)
        return _ok(f'milestone {new_id} registered (pin={pin}, type={entry["type"]})')
    except Exception as e:
        return _fail(f'add_milestone failed: {e}')


# ============================================================
# TOOL_REGISTRY — IntentResolver 调度入口
# ============================================================

# ---------------- Project Hold Tool ----------------

def tool_project_hold(
    project_keyword: str,
    hours: float = 72.0,
    raw_text: str = '',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """🆕 [β.5.46-fix18 / 2026-05-22] Sir 显式 hold project N 小时.

    Sir 11:39 真测痛点: 反复说"驾照放一放/hold off" 但 SmartNudge 仍 fire
    dormant_project. 治本 (3 数据源 refactor E 层): IntentResolver 检测 Sir
    cmd 含 hold phrase + project keyword → 调此 tool → ProjectTimeline.
    held_until_ts = now + hours*3600.

    Args:
      project_keyword: Sir 说的项目词 (e.g. "驾照"/"driver's license"). 模糊查 ProjectTimeline.
      hours: hold 时长, default 72h. vocab 里 default_hours 主导.
      raw_text: Sir 原话 (审计用).
    Returns:
      {'ok': True, 'result': '...'} 真 hold 成功
      {'ok': False, 'error': '...'} 没找到项目 / hippo 失败
    """
    if not project_keyword or not str(project_keyword).strip():
        return _fail('project_keyword required')
    if hours <= 0 or hours > 24 * 365:
        return _fail(f'invalid hours: {hours} (range 0-8760)')
    try:
        if nerve is None:
            try:
                import jarvis_central_nerve as _cn
                nerve = getattr(_cn, '_GLOBAL_NERVE', None)
            except Exception:
                nerve = None
        hippo = getattr(nerve, 'hippocampus', None) if nerve else None
        if hippo is None:
            return _fail('no hippocampus')
        # 模糊查 project_name
        project_name = None
        if hasattr(hippo, 'find_project_by_keyword'):
            project_name = hippo.find_project_by_keyword(project_keyword)
        if not project_name:
            return _fail(f'project not found by keyword: {project_keyword}')
        # 调 hippo.hold_project
        if not hasattr(hippo, 'hold_project'):
            return _fail('hippocampus.hold_project not available (needs β.5.46-fix18)')
        ok = hippo.hold_project(project_name, hours=float(hours),
                                  source='intent_resolver')
        if ok:
            return _ok(f"project '{project_name}' held for {hours:.0f}h")
        return _fail(f"project '{project_name}' hold failed")
    except Exception as e:
        return _fail(f'tool_project_hold exception: {e}')


# 🆕 [Sir 2026-05-26 19:14 准则 6 极致版 FIX C] confirm_pending_review tool
# =========================================================================
# Sir 真痛: AutoArbiter LLM 评 confidence 多 < threshold → defer_to_sir →
# review queue 累积 (7 jokes + 8 protocols 待 Sir 拍板). [PENDING REVIEW]
# block 注入主脑 prompt 后, 主脑能在自然对话中问 Sir "上次提议 X 算 inside
# joke 吗?", Sir yes/no 后主脑用本 tool 标 activate/reject — 不必去 dashboard.
# 准则 6 数据强耦合 (relational_state) + 准则 8 优雅 (主脑自决何时问).
# =========================================================================
def tool_confirm_pending_review(
    item_id: str,
    decision: str,
    reason: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """主脑工具 — Sir 自然对话 yes/no 后, 标 review queue 中条目 activate/reject.

    Args:
      item_id: pending review 条目 id (e.g. 'joke_20260526_135210_025c' /
               'proto_20260526_123350_01b3'). 必须是 prompt [PENDING REVIEW]
               中真实列出的 id (主脑 hallucinate id → 失败).
      decision: 'activate' (Sir 说 yes) | 'reject' (Sir 说 no).
      reason: optional, Sir 原话 / 主脑判断依据 (≤200 char, 持久化 history).

    Returns: {'ok': bool, 'message': str, 'kind': str (joke/protocol/'')}
    """
    try:
        from jarvis_relational import get_default_store
        store = get_default_store()
    except Exception as e:
        return _fail(f'tool_confirm_pending_review init exception: {e}')
    if not item_id:
        return _fail('item_id required')
    decision = (decision or '').strip().lower()
    if decision not in ('activate', 'reject'):
        return _fail(f"decision must be 'activate' or 'reject', got '{decision}'")
    try:
        if decision == 'activate':
            kind = store.activate_from_review(item_id)
        else:
            kind = store.reject_from_review(item_id)
        if not kind:
            return _fail(
                f"item '{item_id}' not in review queue (already "
                f"activated/rejected/not exist)"
            )
        return _ok(
            f"{kind} {item_id} → {decision}d (reason: {(reason or '')[:80]})"
        )
    except Exception as e:
        return _fail(f'tool_confirm_pending_review exception: {e}')


# ============================================================================
# 🆕 [Sir 2026-05-26 20:08 真意"全自治"] L1 主脑+L2 思考 共用 7 mutation tool
# ============================================================================
# Sir 真痛: "我说我不喜欢的, 他能直接改. 不要我去看面板甚至是 CLI."
# Sir 升级: "目前这些全让思考或者别的什么拍板, 不要我拍板."
# Sir 落地: "让主脑能通过我说话改这些事. 或反思的时候注意到我不喜欢, 改也行."
#
# 7 tool 覆盖现 dashboard/CLI 全功能, L1 主脑 / L2 思考共用.
# ============================================================================

# --------------------- Tool 1: revert AutoArbiter decision ----------------
def tool_revert_auto_arbiter_decision(
    decision_id: str = '',
    item_phrase: str = '',
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1/L2 撤销 AutoArbiter 自决.

    Sir 说"撤了那个 coffee threshold" → 主脑直调.
    Thought 反思看 SWM 'auto_arbiter_decision' Sir reacted negatively → 直调.

    Args:
      decision_id: 'aa_xxxxx' 精确, 留空则 item_phrase fuzzy
      item_phrase: 关键词 fuzzy 找最近 24h decision
      reason: 撤销理由 (持久化 + 反馈 daemon)
    """
    try:
        from jarvis_auto_arbiter import get_default_daemon
        daemon = get_default_daemon()
        if daemon is None:
            return _fail('AutoArbiter daemon 未启动')
        if decision_id:
            ok, msg = daemon.sir_revert(decision_id, reason=reason)
            return _ok(msg) if ok else _fail(msg)
        if not item_phrase:
            return _fail('需 decision_id OR item_phrase 之一')
        phrase_lower = item_phrase.strip().lower()
        cutoff = time.time() - 24 * 3600
        with daemon._lock:
            candidates = [
                d for d in daemon._decisions
                if d.ts > cutoff and not d.sir_reverted
                and phrase_lower in (d.item_preview or '').lower()
            ]
        if not candidates:
            return _fail(
                f"24h 内没找到含 '{item_phrase}' 的 decision"
            )
        if len(candidates) > 1:
            ids = ', '.join(c.id for c in candidates[:3])
            return _fail(
                f"多个 match ({len(candidates)}): {ids}... — 用 decision_id 精确"
            )
        target = candidates[0]
        ok, msg = daemon.sir_revert(target.id, reason=reason)
        return _ok(
            f"reverted {target.kind} '{target.item_preview[:40]}': {msg}"
        ) if ok else _fail(msg)
    except Exception as e:
        return _fail(f'tool_revert_auto_arbiter exception: {e}')


# --------------------- Tool 2: tune AutoArbiter threshold -----------------
def tool_tune_auto_arbiter_threshold(
    kind: str,
    new_threshold: Optional[float] = None,
    delta: Optional[float] = None,
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1/L2 调 AutoArbiter calibration threshold.

    Sir 说 "AutoArbiter 太松了, 调严点" → 主脑直调.
    DaemonHealthMonitor 看 threshold < 0.55 → 自调 (L3).

    Args:
      kind: 'inside_joke' / 'thread' / 'protocol' / 'concern' / 'directive'
      new_threshold: 绝对 (0.50-0.95)
      delta: 相对 (-0.20 to +0.20)
      reason: 调因 (持久化)
    """
    try:
        from jarvis_auto_arbiter import get_default_daemon
        daemon = get_default_daemon()
        # daemon 没跑也可改 file (持久化), 下次启动自然加载
        if daemon is None:
            cal_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'memory_pool', 'auto_arbiter_calibration.json'
            )
            try:
                with open(cal_path, 'r', encoding='utf-8') as f:
                    cal = json.load(f)
            except Exception:
                cal = {'thresholds': {}}
            thr = (cal.get('thresholds') or {}).get(kind, 0.75)
            if new_threshold is not None:
                final = max(0.50, min(0.95, float(new_threshold)))
            elif delta is not None:
                final = max(0.50, min(0.95, thr + float(delta)))
            else:
                return _fail('需 new_threshold OR delta')
            cal.setdefault('thresholds', {})[kind] = round(final, 3)
            cal['last_manual_tune_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            cal['last_manual_tune_reason'] = (reason or '')[:200]
            with open(cal_path, 'w', encoding='utf-8') as f:
                json.dump(cal, f, ensure_ascii=False, indent=2)
            return _ok(
                f"{kind} {thr:.2f}→{final:.2f} (daemon 未跑, 文件已生效)"
            )
        # daemon 跑 — 改 in-memory + persist
        old_thr = daemon._effective_thresholds().get(kind, 0.75)
        if new_threshold is not None:
            final = max(daemon.THRESHOLD_FLOOR,
                          min(daemon.THRESHOLD_CEILING, float(new_threshold)))
        elif delta is not None:
            final = max(daemon.THRESHOLD_FLOOR,
                          min(daemon.THRESHOLD_CEILING, old_thr + float(delta)))
        else:
            return _fail('需 new_threshold OR delta')
        daemon._calibration.setdefault('thresholds', {})[kind] = round(final, 3)
        daemon._calibration['last_manual_tune_iso'] = time.strftime(
            '%Y-%m-%dT%H:%M:%S'
        )
        daemon._calibration['last_manual_tune_reason'] = (reason or '')[:200]
        daemon._save_calibration()
        return _ok(
            f"{kind} {old_thr:.2f}→{final:.2f} (reason: {reason[:60]})"
        )
    except Exception as e:
        return _fail(f'tool_tune_auto_arbiter_threshold exception: {e}')


# --------------------- Tool 3: dismiss concern ----------------------------
def tool_dismiss_concern(
    concern_id: str = '',
    keyword: str = '',
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1/L2 软关闭 concern (Sir 不再被打扰).

    Sir 说 "不要再提那个 X 了" → 主脑直调.
    Thought 反思看 SWM 'concern_dismissed_evidence' 反复出现仍 active → 自调 (L2).

    Args:
      concern_id: 'sir_sleep_health' 精确
      keyword: 关键词 fuzzy (id/what/notes 任一)
      reason: dismiss 因 (持久化)
    """
    try:
        from jarvis_concerns import get_default_ledger
        ledger = get_default_ledger()
        if ledger is None:
            return _fail('ConcernsLedger 未启动')
        if concern_id:
            ok = ledger.dismiss(
                concern_id,
                reason=reason or 'Sir/thought 显式 dismiss',
                source='sir_voice' if reason else 'inner_thought',
            )
            return _ok(f"dismissed {concern_id}") if ok else _fail(
                f"concern '{concern_id}' 不存在")
        if not keyword:
            return _fail('需 concern_id OR keyword')
        kw_lower = keyword.strip().lower()
        try:
            actives = ledger.list_active() or []
        except Exception:
            actives = []
        matches = [
            c for c in actives
            if kw_lower in (getattr(c, 'id', '') or '').lower()
            or kw_lower in (getattr(c, 'what', '') or '').lower()
            or kw_lower in (getattr(c, 'notes_for_self', '') or '').lower()
        ]
        if not matches:
            return _fail(f"active concerns 没找到含 '{keyword}'")
        if len(matches) > 1:
            ids = ', '.join(c.id for c in matches[:3])
            return _fail(
                f"多个 match ({len(matches)}): {ids}... — 用 concern_id 精确"
            )
        target = matches[0]
        ok = ledger.dismiss(
            target.id,
            reason=reason or 'Sir/thought 显式 dismiss',
            source='sir_voice' if reason else 'inner_thought',
        )
        return _ok(
            f"dismissed {target.id} ({(target.what or '')[:40]})"
        ) if ok else _fail('dismiss 失败')
    except Exception as e:
        return _fail(f'tool_dismiss_concern exception: {e}')


# --------------------- Tool 4: archive relational item -------------------
def tool_archive_relational_item(
    item_id: str = '',
    keyword: str = '',
    kind: str = '',
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1/L2 归档 inside_joke / protocol / thread (active → archived).

    Sir 说 "把那个 '地基' 梗忘了" → 主脑直调.
    Thought 反思看 inside_joke use_count=0 + 30d 没用 → 自调 archive (L2).

    Args:
      item_id: 'joke_xxxxx' / 'proto_xxxxx' / 'thread_xxxxx' 精确
      keyword: 关键词 (phrase/rule/title fuzzy)
      kind: 'inside_joke' / 'protocol' / 'thread' 限定 (可选)
      reason: archive 因 (持久化, 写 entity)
    """
    try:
        from jarvis_relational import get_default_store
        store = get_default_store()
        if store is None:
            return _fail('RelationalStateStore 未启动')
        if item_id:
            return _archive_relational_by_id(store, item_id, reason)
        if not keyword:
            return _fail('需 item_id OR keyword')
        kw_lower = keyword.strip().lower()
        kinds_to_search = [kind] if kind else [
            'inside_joke', 'protocol', 'thread'
        ]
        matches = []
        for k in kinds_to_search:
            if k == 'inside_joke':
                for j in store.inside_jokes.values():
                    if getattr(j, 'state', '') != 'active':
                        continue
                    if kw_lower in (j.phrase or '').lower():
                        matches.append(('inside_joke', j.id, j.phrase[:60]))
            elif k == 'protocol':
                for p in store.unspoken_protocols.values():
                    if getattr(p, 'state', '') != 'active':
                        continue
                    if kw_lower in (p.rule or '').lower():
                        matches.append(('protocol', p.id, p.rule[:60]))
            elif k == 'thread':
                for t in store.shared_history_threads.values():
                    if getattr(t, 'state', '') != 'active':
                        continue
                    if kw_lower in (t.title or '').lower():
                        matches.append(('thread', t.id, t.title[:60]))
        if not matches:
            return _fail(
                f"active 没找到含 '{keyword}' 的 {kind or '任何 kind'}"
            )
        if len(matches) > 1:
            previews = '; '.join(
                f"{m[0]}/{m[1]} '{m[2]}'" for m in matches[:3]
            )
            return _fail(
                f"多个 match ({len(matches)}): {previews}... — 用 item_id"
            )
        kind_found, found_id, preview = matches[0]
        return _archive_relational_by_id(
            store, found_id, reason,
            found_kind=kind_found, preview=preview
        )
    except Exception as e:
        return _fail(f'tool_archive_relational_item exception: {e}')


def _archive_relational_by_id(
    store, item_id: str, reason: str,
    found_kind: str = '', preview: str = ''
) -> Dict[str, Any]:
    """内 helper — 直接 setattr state='archived'."""
    try:
        for kind_name, container in [
            ('inside_joke', store.inside_jokes),
            ('protocol', store.unspoken_protocols),
            ('thread', store.shared_history_threads),
        ]:
            if item_id in container:
                entity = container[item_id]
                old_state = getattr(entity, 'state', '?')
                entity.state = 'archived'
                store._dirty = True
                try:
                    store.persist()
                except Exception:
                    pass
                preview_str = preview or item_id
                return _ok(
                    f"archived {kind_name} '{preview_str}' "
                    f"(was {old_state}, reason: {reason[:60]})"
                )
        return _fail(
            f"item_id '{item_id}' 不在 inside_jokes/protocols/threads"
        )
    except Exception as e:
        return _fail(f'archive exception: {e}')


# --------------------- Tool 5: cancel promise -----------------------------
def tool_cancel_promise(
    promise_id: str = '',
    keyword: str = '',
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1/L2 撤销 pending promise.

    Sir 说 "那个 standby 承诺撤了" → 主脑直调.
    Thought 看 SWM 'commitment_yield_evidence' 反复 → 自调 (L2).

    Args:
      promise_id: 'p_xxxxx' 精确
      keyword: description fuzzy
      reason: cancel 因 (持久化 evidence)
    """
    try:
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        target_id = promise_id
        if not target_id:
            if not keyword:
                return _fail('需 promise_id OR keyword')
            kw_lower = keyword.strip().lower()
            pending = plog.list_pending()
            matches = [
                p for p in pending
                if kw_lower in (p.description or '').lower()
            ]
            if not matches:
                return _fail(f"pending 没找到含 '{keyword}'")
            if len(matches) > 1:
                ids = ', '.join(p.id for p in matches[:3])
                return _fail(
                    f"多个 match ({len(matches)}): {ids}... — 用 promise_id"
                )
            target_id = matches[0].id
        with plog._lock:
            p = plog.promises.get(target_id)
            if p is None:
                return _fail(f"promise '{target_id}' 不存在")
            if p.state != 'pending':
                return _fail(
                    f"promise '{target_id}' state={p.state} (不是 pending)"
                )
            p.state = 'cancelled'
            p.add_evidence(
                'sir_cancel',
                (reason or 'Sir/thought 显式 cancel')[:200],
            )
        try:
            plog._persist()
        except Exception:
            pass
        return _ok(
            f"cancelled promise {target_id} '{p.description[:40]}'"
        )
    except Exception as e:
        return _fail(f'tool_cancel_promise exception: {e}')


# --------------------- Tool 6: tune inner_thought allowlist ----------------
def tool_tune_inner_thought_allowlist(
    tool: str,
    action: str = 'add',
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1 调 thought call_tool allowlist (Sir 说 "thought 别调 X 了").

    Args:
      tool: tool name (e.g. 'milestone_register')
      action: 'add' / 'remove'
      reason: 调因 (持久化)
    """
    try:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'inner_thought_tool_allowlist.json'
        )
        if not os.path.exists(path):
            data = {'allowlist': [], 'history': []}
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        allow = list(data.get('allowlist') or [])
        action_lower = (action or '').strip().lower()
        if action_lower == 'add':
            if tool in allow:
                return _fail(f"'{tool}' 已在 allowlist")
            allow.append(tool)
            msg = f"added '{tool}' to allowlist"
        elif action_lower == 'remove':
            if tool not in allow:
                return _fail(f"'{tool}' 不在 allowlist")
            allow.remove(tool)
            msg = f"removed '{tool}' from allowlist"
        else:
            return _fail(f"action 须 'add' / 'remove', got '{action}'")
        data['allowlist'] = allow
        hist = list(data.get('history') or [])
        hist.append({
            'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'op': action_lower,
            'tool': tool,
            'source': 'sir_voice',
            'reason': (reason or '')[:200],
        })
        data['history'] = hist
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return _ok(f"{msg} (reason: {reason[:60]})")
    except Exception as e:
        return _fail(f'tool_tune_inner_thought_allowlist exception: {e}')


# --------------------- Tool 7: tune runtime_log_marker --------------------
def tool_tune_runtime_log_marker(
    marker: str,
    action: str = 'add',
    kind: str = 'log_line',
    reason: str = '',
    **kwargs,
) -> Dict[str, Any]:
    """L1 调 runtime log marker vocab (Sir 说 "反思也看 [Hippocampus]").

    Args:
      marker: marker string (e.g. '[Hippocampus]')
      action: 'add' / 'remove'
      kind: 'log_line' (default, 普通 log 行) / 'action_event_prefix' (SWM event 前缀)
      reason: 调因
    """
    try:
        from jarvis_runtime_log_markers import (
            add_marker, remove_marker, DEFAULT_VOCAB_PATH,
        )
        if not marker or not marker.strip():
            return _fail('marker 不能为空')
        action_lower = (action or '').strip().lower()
        kind_lower = (kind or 'log_line').strip().lower()
        if action_lower == 'add':
            ok = add_marker(
                marker.strip(), kind=kind_lower,
                path=DEFAULT_VOCAB_PATH, source='sir_voice',
            )
            if ok:
                return _ok(f"added [{kind_lower}] '{marker}' (reason: {reason[:60]})")
            return _fail(f"add fail or already exists: '{marker}'")
        elif action_lower == 'remove':
            ok = remove_marker(
                marker.strip(), kind=kind_lower,
                path=DEFAULT_VOCAB_PATH, source='sir_voice',
            )
            if ok:
                return _ok(f"removed [{kind_lower}] '{marker}' (reason: {reason[:60]})")
            return _fail(f"remove fail or not exists: '{marker}'")
        else:
            return _fail(f"action 须 'add' / 'remove', got '{action}'")
    except Exception as e:
        return _fail(f'tool_tune_runtime_log_marker exception: {e}')


TOOL_REGISTRY: Dict[str, Any] = {
    'concern_progress_update': tool_concern_progress_update,
    'memory_correction_apply': tool_memory_correction_apply,
    'commitment_register': tool_commitment_register,
    'self_promise_register': tool_self_promise_register,
    'profile_field_update': tool_profile_field_update,
    'milestone_register': tool_milestone_register,
    # 🆕 [β.5.46-fix18] Sir hold project tool
    'project_hold': tool_project_hold,
    # 🆕 [Sir 2026-05-26 19:14 准则 6 极致版 FIX C] PENDING REVIEW confirm tool
    'confirm_pending_review': tool_confirm_pending_review,
    # 🚫 [Sir 2026-05-26 20:14 真意 anchor 3] 7 mutation tool fn 保留但**不注册**:
    # =====================================================================
    # Sir 不想 main brain/thought 直接调 mutation tool (有 LLM hallucinate 风险).
    # 真意路径: Sir 自然质疑 → SirSkepticismDetector → Loop 内部 import fn 调.
    # 看 jarvis_sir_skepticism.py + docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §3.
    # =====================================================================
    # 'revert_auto_arbiter_decision': tool_revert_auto_arbiter_decision,
    # 'tune_auto_arbiter_threshold': tool_tune_auto_arbiter_threshold,
    # 'dismiss_concern': tool_dismiss_concern,
    # 'archive_relational_item': tool_archive_relational_item,
    # 'cancel_promise': tool_cancel_promise,
    # 'tune_inner_thought_allowlist': tool_tune_inner_thought_allowlist,
    # 'tune_runtime_log_marker': tool_tune_runtime_log_marker,
}


def get_tool_registry() -> Dict[str, Any]:
    """返回 TOOL_REGISTRY copy. central_nerve 启动时调."""
    return dict(TOOL_REGISTRY)


def register_tool(name: str, fn: Any) -> None:
    """运行时加 tool (e.g. plugin)."""
    TOOL_REGISTRY[name] = fn
