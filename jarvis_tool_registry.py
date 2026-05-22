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
        judgement = {
            'has_relevance': True,
            'severity_delta': float(severity_delta),
            'optimal_timing': optimal_timing,
        }
        if current is not None:
            judgement['progress'] = {'current': current, 'target': target, 'unit': unit}
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


TOOL_REGISTRY: Dict[str, Any] = {
    'concern_progress_update': tool_concern_progress_update,
    'memory_correction_apply': tool_memory_correction_apply,
    'commitment_register': tool_commitment_register,
    'self_promise_register': tool_self_promise_register,
    'profile_field_update': tool_profile_field_update,
    'milestone_register': tool_milestone_register,
    # 🆕 [β.5.46-fix18] Sir hold project tool
    'project_hold': tool_project_hold,
}


def get_tool_registry() -> Dict[str, Any]:
    """返回 TOOL_REGISTRY copy. central_nerve 启动时调."""
    return dict(TOOL_REGISTRY)


def register_tool(name: str, fn: Any) -> None:
    """运行时加 tool (e.g. plugin)."""
    TOOL_REGISTRY[name] = fn
