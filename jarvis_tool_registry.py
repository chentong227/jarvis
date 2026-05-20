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
from typing import Any, Dict, Optional


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
    current: float,
    target: float = 0,
    unit: str = '',
    raw_text: str = '',
    severity_delta: float = 0.0,
    optimal_timing: str = '',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """update Sir's daily progress on a concern (e.g. 'sir_hydration_habit' current=8/8).
    
    Sir reports progress → real mutation in ConcernsLedger.daily_progress + severity.
    """
    if not concern_id:
        return _fail('concern_id required')
    try:
        if nerve is None:
            from jarvis_utils import get_default_event_bus  # fallback
            nerve = None
        if nerve is None:
            try:
                import jarvis_central_nerve as _cn
                # try get global nerve
                nerve = getattr(_cn, '_GLOBAL_NERVE', None)
            except Exception:
                nerve = None
        ledger = getattr(nerve, 'concerns_ledger', None) if nerve else None
        if ledger is None:
            return _fail('no concerns_ledger')
        judgement = {
            'has_relevance': True,
            'progress': {'current': current, 'target': target, 'unit': unit},
            'severity_delta': float(severity_delta),
            'optimal_timing': optimal_timing,
        }
        ok = ledger.record_user_feedback(concern_id, raw_text, judgement)
        if ok:
            return _ok(
                f'concern {concern_id} progress updated: {current}/{target} {unit}'
            )
        return _fail(f'ledger.record_user_feedback rejected (concern not found?)')
    except Exception as e:
        return _fail(f'exception: {e}')


# ---------------- Memory Correction Tool ----------------

def tool_memory_correction_apply(
    old_value: str,
    new_value: str,
    field_hint: str = '',
    raw_text: str = '',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Sir corrected a previously recorded memory (e.g. '9 cups' → '8 cups').
    
    Real mutation: find matching ProfileCard/memory cell, update to new_value.
    """
    if not new_value:
        return _fail('new_value required')
    try:
        # ProfileCard apply_correction (existing API)
        if nerve is None:
            import jarvis_central_nerve as _cn
            nerve = getattr(_cn, '_GLOBAL_NERVE', None)
        profile = getattr(nerve, 'profile_card', None) if nerve else None
        if profile is None:
            return _fail('no profile_card')
        # try canonical apply_correction
        if hasattr(profile, 'apply_correction'):
            try:
                profile.apply_correction(
                    old_value=old_value,
                    new_value=new_value,
                    field_hint=field_hint,
                    raw_text=raw_text,
                )
                return _ok(f"corrected: {old_value} → {new_value}")
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
    raw_text: str = '',
    nerve=None,
    **kw,
) -> Dict[str, Any]:
    """Sir gave a profile preference update (e.g. 'I prefer english').
    
    Real mutation: update ProfileCard field directly via apply_correction.
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
                profile.apply_correction(
                    field_hint=field_path,
                    new_value=str(value),
                    raw_text=raw_text,
                )
                return _ok(f'profile field {field_path} = {str(value)[:60]}')
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

TOOL_REGISTRY: Dict[str, Any] = {
    'concern_progress_update': tool_concern_progress_update,
    'memory_correction_apply': tool_memory_correction_apply,
    'commitment_register': tool_commitment_register,
    'self_promise_register': tool_self_promise_register,
    'profile_field_update': tool_profile_field_update,
    'milestone_register': tool_milestone_register,
}


def get_tool_registry() -> Dict[str, Any]:
    """返回 TOOL_REGISTRY copy. central_nerve 启动时调."""
    return dict(TOOL_REGISTRY)


def register_tool(name: str, fn: Any) -> None:
    """运行时加 tool (e.g. plugin)."""
    TOOL_REGISTRY[name] = fn
