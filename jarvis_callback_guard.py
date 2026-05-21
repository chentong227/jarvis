# -*- coding: utf-8 -*-
"""[P5-fixCB / 2026-05-21 10:30] Unsolicited Callback Guard — Sir 5+ 次真测痛点真治本.

Sir 10:06/10:08 (重启后) + 22:04/22:19/23:02/23:43/23:49 反复 5+ 次:
主脑 unsolicited callback 老账道歉 (Sir 当前 turn 完全没问).
PreFlight async (P5-fixD default ON) 修不了当前轮 (post-stream).

真治本两层:
  C. directive unsolicited_callback_guard (priority 12, prompt 顶级强约束教主脑)
  B. 本模块 post-stream scan reply → publish SWM + 写 STM forbidden block 下轮
     主脑看到 → 自纠

跟 PreFlight (LLM-based async) 互补: 本模块用 vocab regex (零延迟), 命中即 evidence
publish, 不阻 reply 输出. 主脑下轮 prompt 看 [SIR ASKED YOU TO STOP CALLBACK] block
强约束.

不硬编码: vocab 持久化到 `memory_pool/forbidden_callback_vocab.json`, CLI 改 + L7
reflector propose 新 phrase. Sir 准则 6 合规.

测试: tests/_test_p0_plus_20_p5_callback_guard.py
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'forbidden_callback_vocab.json')


# ============================================================
# Vocab cache (mtime-based, 跟其他 vocab 同 pattern)
# ============================================================

_VOCAB_LOCK = threading.Lock()
_VOCAB_CACHE: Dict[str, object] = {
    'mtime': 0.0,
    'phrases': [],  # list of (compiled_pattern, phrase_id, severity, lang)
}


def _load_vocab(vocab_path: Optional[str] = None) -> List[Tuple[re.Pattern, str, str, str]]:
    """读 vocab JSON, 返回 list of (compiled regex, id, severity, lang).

    mtime cache, fail-safe (文件不存在 / corrupt → 返 [], 不抛).
    """
    path = vocab_path or DEFAULT_VOCAB_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []

    with _VOCAB_LOCK:
        if mtime == _VOCAB_CACHE['mtime'] and _VOCAB_CACHE['phrases']:
            return _VOCAB_CACHE['phrases']
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return _VOCAB_CACHE['phrases'] or []

        compiled = []
        for phrase in data.get('phrases', []):
            if phrase.get('state', 'active') != 'active':
                continue
            patterns = phrase.get('patterns', [])
            if not patterns:
                continue
            phrase_id = phrase.get('id', '?')
            severity = phrase.get('severity', 'medium')
            lang = phrase.get('lang', 'en')
            for pat in patterns:
                if not pat:
                    continue
                try:
                    # 不分大小写, 不要 word boundary (中文 pattern 不适合)
                    compiled.append((
                        re.compile(re.escape(pat), re.IGNORECASE),
                        phrase_id, severity, lang,
                    ))
                except Exception:
                    continue
        _VOCAB_CACHE['mtime'] = mtime
        _VOCAB_CACHE['phrases'] = compiled
        return compiled


def reset_vocab_cache() -> None:
    """testcase 用."""
    with _VOCAB_LOCK:
        _VOCAB_CACHE['mtime'] = 0.0
        _VOCAB_CACHE['phrases'] = []


# ============================================================
# Public API
# ============================================================

def scan_for_unsolicited_callback(
    reply_text: str,
    sir_utterance: str = '',
    vocab_path: Optional[str] = None,
) -> List[Dict]:
    """扫 reply_text 命中 forbidden_callback phrase, 返 list of hits.

    Args:
        reply_text: Jarvis 准备输出/已输出的 reply
        sir_utterance: Sir 当前 turn 说的话 (可选). 若 Sir 主动 callback 上轮
                       (含 'you said' / '你刚才' / '之前你说' 等), 则 callback 是
                       solicited, 不算命中.
        vocab_path: 测试用, 通常 None.

    Returns:
        list of hits, 每条 {'pattern', 'phrase_id', 'severity', 'lang', 'match_text', 'pos'}
    """
    if not reply_text or not reply_text.strip():
        return []

    # 若 Sir 主动召唤老账 → callback solicited, skip scan
    if _sir_invited_callback(sir_utterance):
        return []

    hits = []
    compiled = _load_vocab(vocab_path)
    for pattern, phrase_id, severity, lang in compiled:
        m = pattern.search(reply_text)
        if m:
            hits.append({
                'pattern': pattern.pattern,
                'phrase_id': phrase_id,
                'severity': severity,
                'lang': lang,
                'match_text': m.group(0),
                'pos': m.start(),
            })
    return hits


_SIR_INVITE_PATTERNS = [
    # 英文 — Sir 主动 callback 老账
    re.compile(r'\byou\s+(said|told|claimed|promised|mentioned)\b', re.IGNORECASE),
    re.compile(r'\b(earlier|before|previously|just\s+now),?\s+you\b', re.IGNORECASE),
    re.compile(r'\bdid\s+you\s+(set|update|save|store|do)\b', re.IGNORECASE),
    re.compile(r'\byou\s+(lied|were\s+wrong|messed\s+up)\b', re.IGNORECASE),
    # 中文
    re.compile(r'你刚才(说|提到|讲)'),
    re.compile(r'你之前(说|提到|讲|答应)'),
    re.compile(r'你(撒谎|说错|搞错|乱说)'),
    re.compile(r'之前你'),
    re.compile(r'刚才你'),
]


def _sir_invited_callback(sir_utterance: str) -> bool:
    """Sir 当前 turn 是否主动 callback 老账 (== solicited, 不算 callback 违规)."""
    if not sir_utterance:
        return False
    text = sir_utterance.strip()
    for pat in _SIR_INVITE_PATTERNS:
        if pat.search(text):
            return True
    return False


# ============================================================
# SWM publish + STM forbidden block
# ============================================================

def publish_callback_violation(
    hits: List[Dict],
    reply_excerpt: str,
    sir_utterance: str,
    turn_id: str = '',
) -> bool:
    """[P5-fixCB-revise / 2026-05-21 11:35 Sir 真意]: redirect 不 ban.

    Sir 11:30 真理: 道歉是 functional revision 不是 ritual.
    主脑命中 callback 句式 → 不再 publish 'violation', 而是:
      1. 提取 capability_keyword (regex 解析 'previous claim of X' / 'previous X')
      2. 调 jarvis_claim_revision_log.capture_revision_from_reply 写 store + publish
         'claim_revision_captured' (info, salience 0.55)
      3. 主脑下轮看 [PENDING CLAIM REVISIONS] block (合法 surface 触发: Sir 召唤 / 自决)
      4. **不**在当前 reply 阻塞 (post-stream, Sir 已听到)
      5. **不**在主脑下轮硬约束 ban (那是上版 P5-fixCB 的过度治本)

    Returns: True = 真 redirect 写 store + publish; False = hits 空 / 失败.
    """
    if not hits:
        return False
    try:
        # 取 highest severity hit
        sev_rank = {'high': 3, 'medium': 2, 'low': 1, '': 0}
        top_hit = max(hits, key=lambda h: sev_rank.get(h.get('severity', ''), 0))

        # 提取 capability_keyword (从 reply 解析 'previous claim of X' / etc.)
        capability_kw, reason_text = _extract_capability_from_reply(
            reply_text=reply_excerpt or '',
            top_hit=top_hit,
        )

        # redirect 到 ClaimRevisionLog (写 store + publish 'claim_revision_captured')
        try:
            from jarvis_claim_revision_log import capture_revision_from_reply
            rid = capture_revision_from_reply(
                reply_excerpt=reply_excerpt or '',
                capability_keyword=capability_kw or top_hit.get('match_text', '?')[:60],
                admitted_lacking_reason=reason_text or '',
                turn_id=turn_id or '',
                related_keywords=[h.get('phrase_id', '') for h in hits[:5] if h.get('phrase_id')],
                source='callback_guard',
            )
            return bool(rid)
        except Exception:
            # ClaimRevisionLog import 失败兜底: fallback 旧 publish (info, 不是 violation)
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return False
            bus.publish(
                etype='claim_revision_captured',
                description=(
                    f"reply 含 callback intent capability='{top_hit['match_text'][:40]}' "
                    f"(ClaimRevisionLog import 失败, fallback publish)"
                ),
                source='CallbackGuard',
                salience=0.55,
                metadata={
                    'hits_n': len(hits),
                    'top_phrase_id': top_hit['phrase_id'],
                    'top_match_text': top_hit['match_text'],
                    'reply_excerpt': (reply_excerpt or '')[:200],
                    'sir_utterance_excerpt': (sir_utterance or '')[:120],
                    'turn_id': turn_id,
                    'detected_at': time.time(),
                    'fallback_no_store': True,
                },
            )
            return True
    except Exception:
        return False


# ============================================================
# Capability extraction from reply text (regex MVP)
# ============================================================

_CAPABILITY_EXTRACT_PATTERNS = [
    # English
    re.compile(
        r'(?:previous\s+claim|earlier\s+claim|previous\s+statement|previous\s+assertion)\s+'
        r'(?:of|about|regarding)\s+([^.,;:!?\n—–-]{5,80})',
        re.IGNORECASE,
    ),
    re.compile(
        r'(?:i\s+(?:must\s+admit|should\s+clarify|misspoke))[^a-z]*?'
        r'(?:about|regarding|on)\s+([^.,;:!?\n—–-]{5,80})',
        re.IGNORECASE,
    ),
    # 中文
    re.compile(r'关于(?:我)?之前(?:声称|说过|提到)?(?:的|了)?([^,，。.!?！？\n—–-]{4,40})'),
    re.compile(r'(?:我)?之前(?:声称|说|讲)?了?([^,，。.!?！？\n—–-]{4,40})'),
]

# Reason 句式: 'I do not have / 我没有...'
_REASON_EXTRACT_PATTERNS = [
    re.compile(r'(I\s+(?:do\s+not|don\'?t)\s+(?:have|possess)[^.!?\n]{5,150})', re.IGNORECASE),
    re.compile(r'(no\s+such\s+(?:update|action|set|change)[^.!?\n]{0,80}\s+was\s+performed)', re.IGNORECASE),
    re.compile(r'(that\s+was\s+inaccurate[^.!?\n]{0,80})', re.IGNORECASE),
    re.compile(r'(我没(?:有)?(?:那个|这个)?能力[^,，。.!?！？\n]{0,40})'),
    re.compile(r'(我并(?:没|不)有(?:直接)?(?:的)?[^,，。.!?！？\n]{2,40}的?(?:接口|权限|能力))'),
]


def _extract_capability_from_reply(reply_text: str, top_hit: Dict) -> tuple:
    """从 reply 提 (capability_keyword, reason_text). 失败返 ('', '').

    MVP regex. 长期可用 LLM judge.
    """
    if not reply_text:
        return ('', '')
    text = reply_text.strip()

    cap = ''
    for pat in _CAPABILITY_EXTRACT_PATTERNS:
        m = pat.search(text)
        if m:
            cap = m.group(1).strip().strip(',.:;—–-').strip()
            if cap:
                cap = cap[:80]
                break

    reason = ''
    for pat in _REASON_EXTRACT_PATTERNS:
        m = pat.search(text)
        if m:
            reason = m.group(1).strip().strip(',.:;—–-').strip()
            if reason:
                reason = reason[:200]
                break

    # fallback: 用 match_text 周围 60 char 作 reason
    if not reason:
        match_text = (top_hit.get('match_text', '') or '')[:60]
        if match_text:
            try:
                idx = text.lower().find(match_text.lower())
                if idx >= 0:
                    start = max(0, idx - 10)
                    end = min(len(text), idx + len(match_text) + 80)
                    reason = text[start:end].strip()
            except Exception:
                pass

    return (cap, reason)


def render_forbidden_block_for_prompt(
    within_seconds: float = 900.0,
    max_hits: int = 3,
) -> str:
    """[P5-fixCB-revise / 2026-05-21 11:35 Sir 真意 redirect 不 ban]:

    ## 跟之前 P5-fixCB 的差别
    上版 (BAN 风格): 'DO NOT repeat this phrase' / 'priority 12 red line'.
    新版 (REDIRECT 风格): "你已 capture 一个 claim revision intent.
    **不在当前 reply 主动 callback** (Sir 没召唤). 等 Sir 召唤相关话题时
    [PENDING CLAIM REVISIONS] block 会显示 — 你可主动 surface."

    Block 不再针对 'unsolicited_callback_detected' (那 etype 已退役),
    改读 'claim_revision_captured' 最近 events. 主脑看到 = 知道有 pending,
    不主动翻; Sir 召唤 → render_pending_revisions_block 显主动 surface.

    Returns: 空字符串 (无最近 event) 或 prompt block 文本.
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return ''
        events = []
        for e in bus.top_n(n=20):
            if e.get('type') not in ('claim_revision_captured', 'unsolicited_callback_detected'):
                continue
            if e.get('_age_s', 9999) > within_seconds:
                continue
            events.append(e)
        if not events:
            return ''

        lines = [
            '[CLAIM REVISION CAPTURED — 你之前想 backtrack 的已 redirect 到 ClaimRevisionLog]',
            '  Recent reply(s) 含 callback intent (e.g. "Regarding my previous claim..."),',
            '  系统已自动 capture capability + reason 写 ClaimRevisionLog (不在当前 reply 主动说).',
            '',
            '  **当前轮指引** (Sir 11:30 真理 "道歉要有意义的道歉"):',
            '    ❌ 不要主动 callback unsolicited (Sir 没召唤老话题就别翻)',
            '    ❌ 不要 stack ritual self-flagellation ("I must apologize for..." 类空道歉)',
            '    ✅ 只回 Sir current turn 真问的事',
            '    ✅ 等 Sir 主动召唤 (质疑 / 询问 capability) → [PENDING CLAIM REVISIONS] 会显 → 那时 surface',
            '    ✅ 或自检 promise overdue → SelfPromiseDetector 会 publish overdue → 主动 admit',
            '',
            '  Recent captures (informational, 不要主动提):',
        ]
        seen = set()
        for e in events[:max_hits]:
            meta = e.get('metadata') or {}
            cap = (meta.get('capability_keyword', '') or meta.get('top_match_text', '') or '?')[:60]
            if cap in seen:
                continue
            seen.add(cap)
            age = int(e.get('_age_s', 0))
            lines.append(f"    - capability='{cap}' captured {age}s ago (id={meta.get('revision_id', '?')[:8]})")
        return '\n'.join(lines)
    except Exception:
        return ''


# ============================================================
# Stats (Sir CLI 看历史命中)
# ============================================================

def get_recent_hits(hours: float = 24.0, limit: int = 50) -> List[Dict]:
    """供 Sir CLI / dashboard 看历史 unsolicited_callback 命中."""
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return []
        cutoff = hours * 3600.0
        out = []
        for e in bus.top_n(n=100):
            if e.get('type') != 'unsolicited_callback_detected':
                continue
            if e.get('_age_s', 9999) > cutoff:
                continue
            meta = e.get('metadata') or {}
            out.append({
                'turn_id': meta.get('turn_id', ''),
                'top_phrase_id': meta.get('top_phrase_id', ''),
                'match_text': meta.get('top_match_text', ''),
                'reply_excerpt': meta.get('reply_excerpt', '')[:100],
                'sir_utterance': meta.get('sir_utterance_excerpt', '')[:80],
                'detected_at': meta.get('detected_at', 0),
                'age_s': e.get('_age_s', 0),
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
