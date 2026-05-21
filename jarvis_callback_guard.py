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
    """检测到 unsolicited callback → publish 'unsolicited_callback_detected' SWM.

    salience 高 (0.85 = high severity 红线), 让主脑下轮 prompt 一定看到.
    """
    if not hits:
        return False
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return False
        # 取 highest severity
        sev_rank = {'high': 3, 'medium': 2, 'low': 1, '': 0}
        top_hit = max(hits, key=lambda h: sev_rank.get(h.get('severity', ''), 0))
        bus.publish(
            etype='unsolicited_callback_detected',
            description=(
                f"reply 命中 forbidden callback phrase: '{top_hit['match_text']}' "
                f"(id={top_hit['phrase_id']}, sev={top_hit['severity']})"
            ),
            source='CallbackGuard',
            salience=0.85,
            metadata={
                'hits_n': len(hits),
                'top_phrase_id': top_hit['phrase_id'],
                'top_match_text': top_hit['match_text'],
                'top_severity': top_hit['severity'],
                'all_hits': [h['phrase_id'] for h in hits[:5]],
                'reply_excerpt': reply_excerpt[:200],
                'sir_utterance_excerpt': sir_utterance[:120],
                'turn_id': turn_id,
                'detected_at': time.time(),
            },
        )
        return True
    except Exception:
        return False


def render_forbidden_block_for_prompt(
    within_seconds: float = 900.0,
    max_hits: int = 3,
) -> str:
    """供 _assemble_prompt 调: 看 SWM 近期 'unsolicited_callback_detected' event,
    渲染成 prompt block 让主脑下轮自纠.

    Returns: 空字符串 (无最近 event) 或 prompt block 文本.
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return ''
        events = []
        for e in bus.top_n(n=20):
            if e.get('type') != 'unsolicited_callback_detected':
                continue
            if e.get('_age_s', 9999) > within_seconds:
                continue
            events.append(e)
        if not events:
            return ''

        lines = [
            '[SIR FLAGGED UNSOLICITED CALLBACK — DO NOT REPEAT]',
            '  Recent reply(s) violated unsolicited_callback_guard rule.',
            '  Sir did NOT ask about these old topics — you brought them up unprompted.',
            '  THIS IS A TOP-PRIORITY RED LINE (priority 12, equal to no_hallucinated_tool_use).',
            '',
            '  Recent flagged phrases (do NOT use these forms again unless Sir asks):',
        ]
        seen_phrases = set()
        for e in events[:max_hits]:
            meta = e.get('metadata') or {}
            phrase = (meta.get('top_phrase_id', '') or '')
            match_text = (meta.get('top_match_text', '') or '')[:60]
            if phrase in seen_phrases:
                continue
            seen_phrases.add(phrase)
            age = int(e.get('_age_s', 0))
            lines.append(
                f"    - {phrase} (matched: '{match_text}', {age}s ago)"
            )
        lines.append('')
        lines.append('  Rewrite rule: drop the callback. Reply only to Sir current turn.')
        lines.append('  If you must reference past, wait for Sir to ask explicitly.')
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
