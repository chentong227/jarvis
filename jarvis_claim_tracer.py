# -*- coding: utf-8 -*-
"""
[P0+20-β.2.8.7 / 2026-05-17] ClaimTracer — 通用反幻觉框架

Sir 23:32 反馈尖锐:
> "不写硬编码吧? 硬编码只是时间不能编造幻觉吗? 这为什么在之前的言出必行
>  中没实现?"

设计原则:
  言出必行 = 任何 Jarvis 输出的 specific factual claim 必须 trace 到 evidence.
  PromiseLog 只 cover 未来承诺, 没 cover 过去事实陈述 — Sir 抓住的真 gap.

ClaimTracer 抽 Jarvis reply 里的 specific factual claim:
  - 时间戳 (23:14:06, 9:30am, 下午三点)
  - 具体数字 (87%, 3次, 6小时)
  - 显式 quote ("Sir said X" / "Sir 说了 X")
然后 scan 当轮 evidence 来源:
  - fast_call results (tool 真返回的字串)
  - STM (Sir 原话 / 过往对话)
  - uncertainty markers ("大约/我估计/about/roughly")
没 trace 到 → log "⚠️ [ClaimTracer/Unverified] {claim} in reply"
β.2.9: 接入 SoulAlignmentEvaluator 把 unverified claim 算 missed.

设计为 fire-and-forget 异步, evaluate ≤ 5ms 不阻塞主对话.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# Claim 类型 + 提取 regex
# ============================================================

# 时间戳: HH:MM(:SS)? 或 H:MMam/pm 或 下午三点 / 早上九点半
_PAT_TIME_HHMMSS = re.compile(r'\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b')
_PAT_TIME_AMPM = re.compile(r'\b(\d{1,2})(?::(\d{2}))?\s*(?:am|pm|AM|PM)\b')
_PAT_TIME_ZH = re.compile(r'(早上|上午|中午|下午|晚上|凌晨)?\s*'
                            r'(零|一|二|三|四|五|六|七|八|九|十|十一|十二|\d{1,2})\s*点\s*'
                            r'(半|一刻|三刻|\d{1,2}\s*分?)?')

# 具体百分数 / 倍数
_PAT_PERCENT = re.compile(r'\b\d{1,3}(?:\.\d+)?\s*[%％]')
_PAT_MULTIPLIER = re.compile(r'\b\d+(?:\.\d+)?\s*[倍]')

# 具体计数 ("3 次" / "5 个" / "twice" / "three times")
_PAT_ZH_COUNT = re.compile(r'(\d+)\s*(次|个|条|遍|回|篇|份|张|项)')
_PAT_EN_COUNT = re.compile(r'\b(\d+)\s+(times|days|weeks|months|hours|minutes)\b',
                             re.IGNORECASE)

# 显式 quote attribution ("you said X" / "Sir 说 X" / 直引)
_PAT_QUOTE_ATTR_EN = re.compile(r'\byou (?:said|told me|mentioned|noted)\s+[\'"](.{5,80})[\'"]',
                                  re.IGNORECASE)
_PAT_QUOTE_ATTR_ZH = re.compile(r'您?(?:说过?|告诉我|提到|表示)[\'"](.{3,60})[\'"]')

# Uncertainty marker — 这些短语让 claim 不算严格 fact
_UNCERTAINTY_MARKERS = (
    'about', 'approximately', 'roughly', 'estimate', 'guess', 'maybe',
    "i'm not sure", "i think", "i recall", "i believe", "around",
    '大约', '大概', '差不多', '我估计', '我印象中', '可能', '应该', '好像',
    '我记得', '我猜', '左右',
)


# ============================================================
# Claim datatypes
# ============================================================

class Claim:
    """一个 specific factual claim."""

    def __init__(self, kind: str, text: str, span: Tuple[int, int] = (0, 0)):
        self.kind = kind          # 'time' / 'percent' / 'count' / 'quote'
        self.text = text          # 命中的字串 (e.g. "23:14:06" / "87%" / "Sir said X")
        self.span = span
        self.has_uncertainty = False
        self.trace_to = None      # 'tool:xxx' | 'stm:turn_n' | 'uncertainty' | None
        self.trace_what = ''

    def __repr__(self):
        return f"Claim({self.kind} '{self.text}' trace={self.trace_to})"


# ============================================================
# Extraction
# ============================================================

def extract_claims(text: str) -> List[Claim]:
    """从 Jarvis reply 里抽所有 specific factual claim. ≤ 5ms."""
    if not text or len(text) < 5:
        return []
    claims: List[Claim] = []

    # 时间戳
    for m in _PAT_TIME_HHMMSS.finditer(text):
        s = m.group(0)
        # 过滤过短/无意义 (e.g. "1:1" 应该不算)
        if int(m.group(1)) > 24 or int(m.group(2)) > 59:
            continue
        claims.append(Claim('time', s, m.span()))
    for m in _PAT_TIME_AMPM.finditer(text):
        claims.append(Claim('time', m.group(0), m.span()))
    # 中文时间 e.g. "下午三点半" — 简化只 mark
    for m in _PAT_TIME_ZH.finditer(text):
        if m.group(2):  # 必须有具体数字才算
            claims.append(Claim('time', m.group(0), m.span()))

    # 百分数 / 倍数
    for m in _PAT_PERCENT.finditer(text):
        claims.append(Claim('percent', m.group(0), m.span()))
    for m in _PAT_MULTIPLIER.finditer(text):
        claims.append(Claim('multiplier', m.group(0), m.span()))

    # 计数
    for m in _PAT_ZH_COUNT.finditer(text):
        claims.append(Claim('count', m.group(0), m.span()))
    for m in _PAT_EN_COUNT.finditer(text):
        claims.append(Claim('count', m.group(0), m.span()))

    # Quote attribution (Sir 说...)
    for pat in (_PAT_QUOTE_ATTR_EN, _PAT_QUOTE_ATTR_ZH):
        for m in pat.finditer(text):
            claims.append(Claim('quote', m.group(0)[:80], m.span()))

    # 标 uncertainty: 每个 claim 看附近 ±40 字符是否含 uncertainty marker
    text_l = text.lower()
    for c in claims:
        start = max(0, c.span[0] - 40)
        end = min(len(text), c.span[1] + 40)
        window = text_l[start:end]
        if any(m in window for m in _UNCERTAINTY_MARKERS):
            c.has_uncertainty = True
    return claims


# ============================================================
# Trace evidence
# ============================================================

def trace_to_evidence(claim: Claim, tool_results: List[str],
                       stm_recent: List[Dict]) -> bool:
    """看 claim 是否能 trace 到 evidence. 返回 True = 找到 trace.

    优先级:
      1. uncertainty marker — 已标
      2. tool_results 含该字串
      3. STM 含该字串 (Sir 原话或 jarvis 之前 reply)
    """
    if claim.has_uncertainty:
        claim.trace_to = 'uncertainty'
        return True

    needle = claim.text.lower()
    needle_compact = re.sub(r'\s+', '', needle)

    # tool result
    for tr in tool_results or []:
        tr_l = str(tr).lower()
        if needle in tr_l or needle_compact in re.sub(r'\s+', '', tr_l):
            claim.trace_to = 'tool'
            claim.trace_what = str(tr)[:100]
            return True

    # STM (含 user + jarvis 历史 reply)
    for entry in (stm_recent or [])[-10:]:
        blob = (str(entry.get('user', '')) + ' ' +
                str(entry.get('jarvis', ''))).lower()
        if needle in blob or needle_compact in re.sub(r'\s+', '', blob):
            claim.trace_to = 'stm'
            claim.trace_what = blob[:100]
            return True

    return False


# ============================================================
# 主 API: trace 一段 reply + log unverified claims
# ============================================================

def trace_reply(jarvis_reply: str,
                  tool_results: Optional[List[str]] = None,
                  stm_recent: Optional[List[Dict]] = None,
                  turn_id: str = '') -> dict:
    """对 Jarvis reply 跑 claim trace. fire-and-forget, 返 stats.

    Args:
      jarvis_reply: 主脑当轮输出 (含中英文混合)
      tool_results: 当轮所有 fast_call 返回的 result strings (空 list 也 ok)
      stm_recent: 当前 STM (last ~10 entries) 含 user + jarvis 历史
      turn_id: trace id 给 log

    Returns:
      {n_claims, n_verified, n_unverified, unverified_examples}
    """
    if not jarvis_reply:
        return {'n_claims': 0, 'n_verified': 0, 'n_unverified': 0,
                'unverified_examples': []}
    claims = extract_claims(jarvis_reply)
    if not claims:
        return {'n_claims': 0, 'n_verified': 0, 'n_unverified': 0,
                'unverified_examples': []}

    tool_results = tool_results or []
    stm_recent = stm_recent or []

    n_verified = 0
    n_unverified = 0
    unverified_examples: List[str] = []
    for c in claims:
        ok = trace_to_evidence(c, tool_results, stm_recent)
        if ok:
            n_verified += 1
        else:
            n_unverified += 1
            unverified_examples.append(f"[{c.kind}] '{c.text}'")

    if n_unverified > 0:
        try:
            ex = ' / '.join(unverified_examples[:3])
            bg_log(
                f"⚠️ [ClaimTracer/Unverified] turn={turn_id or '?'} "
                f"reply has {n_unverified}/{len(claims)} unverified claims: {ex[:200]}"
            )
        except Exception:
            pass

    return {
        'n_claims': len(claims),
        'n_verified': n_verified,
        'n_unverified': n_unverified,
        'unverified_examples': unverified_examples,
    }


# ============================================================
# 防回归: SoulAlignmentEvaluator 接入预留 (β.2.9)
# ============================================================

_CLAIM_STATS = {
    'total_replies_traced': 0,
    'total_claims': 0,
    'total_unverified': 0,
}


def get_stats() -> dict:
    return dict(_CLAIM_STATS)


def update_stats(result: dict) -> None:
    _CLAIM_STATS['total_replies_traced'] += 1
    _CLAIM_STATS['total_claims'] += result.get('n_claims', 0)
    _CLAIM_STATS['total_unverified'] += result.get('n_unverified', 0)
