# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 20:55 真痛追根 方案 D 治本] InnerThought Outcome Loop.

Sir 真痛 (Phase 2B 铺垫但没合环):
  outcome 字段就位但没人写没人读, thought 不知道 Sir 关心不关心 →
  长期看 "想了一堆没体现". 解决: 后置检测 (post-reply hook) — 看主脑
  上轮 reply 是否 reference 某 thought + 看 Sir 本轮反应 (engage/silence/reject).

数据流 (准则 6 数据强耦合):
  Sir reply 进 chat_bypass
    → ThoughtOutcomeWatch worker (async, 不阻主流)
    → detect_outcome(sir_reply, jarvis_reply, recent_thoughts):
        (a) 主脑 reply 含 thought_reference_pattern (vocab) → 找 best match thought
        (b) Sir reply 含 sir_engaged/silenced/rejected (vocab) → outcome
        (c) 综合: 主脑 ref + Sir engage = 'sir_engaged' (最高价值)
                  Sir silence = 'sir_silenced' (该 archive 类似 topic)
                  Sir reject = 'sir_rejected' (强烈否)
                  no signal = 'no_signal' (默认)
    → InnerThoughtDaemon.record_outcome(thought_id, outcome) — 持久化 thought.outcome
    → publish SWM 'thought_outcome_observed' — 让 inner_thought 反思 evidence 看到

后期 (D+):
  WeeklyReflector 周期性看 outcome 比例 → 自适应调 surface_to_sir vocab
  阈值 (e.g. sir_engaged 多 → 降 surface threshold; sir_silenced 多 → 升).

准则:
  6 (vocab 持久化 + 数据强耦合): memory_pool/inner_thought_outcome_vocab.json
  8 (优雅高效可持续): 不在 .py 写死 keyword, async fire-and-forget, 不阻 main
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ==========================================================================
# Vocab IO
# ==========================================================================
_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_outcome_vocab.json',
)
_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_VOCAB_CHECK_INTERVAL_S = 30.0

_DEFAULT_VOCAB = {
    'thought_reference_patterns_zh': (
        '我刚才在想', '我刚在想', '刚才想到', '我注意到', '我留意到',
        '我意识到', '我察觉', '我反思', '想了想', '心里在想',
    ),
    'thought_reference_patterns_en': (
        'i was thinking', 'i noticed', 'i was reflecting', 'i was pondering',
        'it crossed my mind', 'i was considering', 'on reflection',
        'i caught myself', 'i realised', 'i realized',
    ),
    'sir_engaged_keywords_zh': (
        '不错', '好想法', '有意思', '对的', '没错', '确实', '说得对',
        '继续说', '展开说',
    ),
    'sir_engaged_keywords_en': (
        'good point', 'nice catch', 'interesting', 'exactly', "you're right",
        'true', 'indeed', 'tell me more', 'go on', 'fair point', 'agreed',
    ),
    'sir_silenced_keywords_zh': (
        '别提了', '别说了', '不用提', '不重要', '跳过', '下次别说',
    ),
    'sir_silenced_keywords_en': (
        'drop it', 'let it go', 'skip that', "don't bring that up",
        'not important', 'stop bringing',
    ),
    'sir_rejected_keywords_zh': (
        '不对', '错了', '不是这样', '误解了', '想错了', '不准确',
    ),
    'sir_rejected_keywords_en': (
        "that's wrong", 'incorrect', 'you got it wrong', "no it's not",
        'you misread', 'not really', 'not quite',
    ),
}


def _load_vocab() -> dict:
    """Lazy load vocab + mtime 30s throttle. 失败 fallback default."""
    now = time.time()
    if (_VOCAB_CACHE['data'] is not None and
            now - _VOCAB_CACHE['checked_at'] < _VOCAB_CHECK_INTERVAL_S):
        return _VOCAB_CACHE['data']
    _VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_VOCAB_PATH):
            _VOCAB_CACHE['data'] = _DEFAULT_VOCAB
            return _DEFAULT_VOCAB
        mtime = os.path.getmtime(_VOCAB_PATH)
        if (mtime == _VOCAB_CACHE['mtime'] and _VOCAB_CACHE['data']):
            return _VOCAB_CACHE['data']
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        config = dict(_DEFAULT_VOCAB)
        for k in _DEFAULT_VOCAB.keys():
            v = data.get(k)
            if v:
                config[k] = tuple(v)
        _VOCAB_CACHE['data'] = config
        _VOCAB_CACHE['mtime'] = mtime
        return config
    except Exception:
        return _DEFAULT_VOCAB


# ==========================================================================
# Data structure
# ==========================================================================
@dataclass
class OutcomeResult:
    """Outcome detection result."""
    thought_id: str         # 被 reference 的 thought id (or '' if none)
    outcome: str            # 'sir_engaged' | 'sir_silenced' | 'sir_rejected'
                              # | 'no_signal' | 'jarvis_referenced_no_reaction'
    matched_pattern: str    # 命中的 vocab keyword (debug)
    confidence: float       # 0.0-1.0
    reason: str             # 简短解释


# ==========================================================================
# Detection
# ==========================================================================
def _contains_any(text: str, keywords) -> Tuple[bool, str]:
    """text 含任何 keyword (case-insensitive) → (True, matched_kw)."""
    if not text or not keywords:
        return False, ''
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True, kw
    return False, ''


def _find_referenced_thought(jarvis_reply: str,
                                recent_thoughts: List) -> Optional[Tuple[str, float, str]]:
    """主脑 reply 中是否 reference 某 thought.

    判别 (2 层):
      1. jarvis_reply 含 thought_reference_pattern (e.g. "I noticed" / "我刚在想")
      2. jarvis_reply 与 thought.thought 有显著 token overlap (jaccard >= 0.15)
    满足 2 个 → 返 (thought_id, confidence, matched_pattern).
    """
    if not jarvis_reply or not recent_thoughts:
        return None
    vocab = _load_vocab()
    patterns = (vocab.get('thought_reference_patterns_zh', ())
                  + vocab.get('thought_reference_patterns_en', ()))
    has_pat, matched_pat = _contains_any(jarvis_reply, patterns)
    if not has_pat:
        return None

    # token overlap 判断 best match
    reply_tokens = set(re.findall(r'\w+', jarvis_reply.lower()))
    if not reply_tokens:
        return None
    best_match = None
    best_jaccard = 0.0
    for t in recent_thoughts:
        thought_text = getattr(t, 'thought', '')
        if not thought_text:
            continue
        # 只看最近 30min 的 thought (老 thought 不太可能被 reference)
        ts = getattr(t, 'ts', 0)
        if time.time() - ts > 1800:
            continue
        t_tokens = set(re.findall(r'\w+', thought_text.lower()))
        if not t_tokens:
            continue
        inter = len(reply_tokens & t_tokens)
        union = len(reply_tokens | t_tokens)
        jaccard = inter / union if union > 0 else 0
        if jaccard > best_jaccard:
            best_jaccard = jaccard
            best_match = t
    if best_match is None or best_jaccard < 0.15:
        return None
    confidence = min(1.0, best_jaccard * 3 + 0.3)  # boost (jaccard 是稀疏)
    return (best_match.id, confidence, matched_pat)


def detect_outcome(sir_reply: str, jarvis_reply: str,
                     recent_thoughts: List) -> Optional[OutcomeResult]:
    """检测 outcome.

    Returns:
      OutcomeResult if any signal detected, else None.
    """
    if not sir_reply:
        return None
    vocab = _load_vocab()

    # 1. 主脑 reply 是否 reference 某 thought?
    ref = _find_referenced_thought(jarvis_reply, recent_thoughts)

    # 2. Sir reply 含 engage/silence/reject keyword?
    has_engage, matched_eng = _contains_any(
        sir_reply,
        vocab.get('sir_engaged_keywords_zh', ())
        + vocab.get('sir_engaged_keywords_en', ()),
    )
    has_silence, matched_sil = _contains_any(
        sir_reply,
        vocab.get('sir_silenced_keywords_zh', ())
        + vocab.get('sir_silenced_keywords_en', ()),
    )
    has_reject, matched_rej = _contains_any(
        sir_reply,
        vocab.get('sir_rejected_keywords_zh', ())
        + vocab.get('sir_rejected_keywords_en', ()),
    )

    # 综合判: 优先级 reject > silence > engaged > ref_no_reaction
    if ref is None:
        # 主脑没 ref thought → 无法归因到具体 thought
        # 但 Sir 整体反应仍有价值 — 暂不返回 outcome (无 anchor)
        return None
    thought_id, ref_conf, matched_pat = ref

    if has_reject:
        return OutcomeResult(
            thought_id=thought_id,
            outcome='sir_rejected',
            matched_pattern=matched_rej,
            confidence=ref_conf * 0.9,
            reason=(f'jarvis ref thought via "{matched_pat}" '
                      f'+ Sir rejected via "{matched_rej}"'),
        )
    if has_silence:
        return OutcomeResult(
            thought_id=thought_id,
            outcome='sir_silenced',
            matched_pattern=matched_sil,
            confidence=ref_conf * 0.9,
            reason=(f'jarvis ref thought via "{matched_pat}" '
                      f'+ Sir silenced via "{matched_sil}"'),
        )
    if has_engage:
        return OutcomeResult(
            thought_id=thought_id,
            outcome='sir_engaged',
            matched_pattern=matched_eng,
            confidence=ref_conf,
            reason=(f'jarvis ref thought via "{matched_pat}" '
                      f'+ Sir engaged via "{matched_eng}"'),
        )
    # 主脑 ref 但 Sir 无明确反应 — 中性, 仍记
    return OutcomeResult(
        thought_id=thought_id,
        outcome='jarvis_referenced_no_reaction',
        matched_pattern=matched_pat,
        confidence=ref_conf * 0.5,
        reason=f'jarvis ref thought via "{matched_pat}" but Sir no clear signal',
    )


# ==========================================================================
# Process — 主入口 (chat_bypass post-reply hook 调)
# ==========================================================================
def process_sir_reply(sir_reply: str,
                        jarvis_reply: Optional[str] = None) -> Optional[OutcomeResult]:
    """完整流程: detect outcome → 写 thought.outcome → publish SWM.

    Args:
      sir_reply: 本轮 Sir 的话
      jarvis_reply: 上轮 Jarvis 的回复 (None → 从 STM 拿)

    Returns: OutcomeResult if detected else None.
    """
    if not sir_reply:
        return None

    # lazy import 防 circular
    try:
        from jarvis_inner_thought_daemon import get_default_daemon
    except Exception:
        return None
    daemon = get_default_daemon()
    if daemon is None:
        return None

    # 拿 jarvis_reply (默认从 STM 拿)
    if jarvis_reply is None:
        try:
            nerve = getattr(daemon, 'nerve', None) or getattr(daemon, 'central_nerve', None)
            if nerve and getattr(nerve, 'short_term_memory', None):
                stm = nerve.short_term_memory
                if stm and isinstance(stm[-1], dict):
                    jarvis_reply = stm[-1].get('jarvis', '') or ''
        except Exception:
            pass
    if not jarvis_reply:
        return None

    # 拿 recent thoughts (30min 内, 最多 20 条)
    try:
        recent = list(daemon._thoughts)[-20:] if hasattr(daemon, '_thoughts') else []
    except Exception:
        recent = []
    if not recent:
        return None

    result = detect_outcome(sir_reply, jarvis_reply, recent)
    if result is None:
        return None

    # 写 thought.outcome (持久化)
    try:
        if hasattr(daemon, 'record_outcome'):
            daemon.record_outcome(result.thought_id, result.outcome)
    except Exception:
        pass

    # publish SWM
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is not None:
            bus.publish(
                etype='thought_outcome_observed',
                description=(
                    f"thought {result.thought_id[:30]} → {result.outcome} "
                    f"(matched: \"{result.matched_pattern}\")"
                ),
                source='ThoughtOutcomeWatch',
                salience=0.7 if result.outcome in ('sir_engaged', 'sir_silenced',
                                                       'sir_rejected') else 0.4,
                metadata={
                    'thought_id': result.thought_id,
                    'outcome': result.outcome,
                    'matched_pattern': result.matched_pattern,
                    'confidence': result.confidence,
                    'reason': result.reason[:200],
                },
                ttl=86400.0,
            )
    except Exception:
        pass

    return result
