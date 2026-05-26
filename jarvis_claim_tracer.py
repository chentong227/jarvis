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

import json
import os
import re
import threading
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
# 🆕 [Sir 2026-05-25 20:01 真测 log 追根 BUG 治本] 英文单词数字也算 specific claim
# =====================================================================
# 源 BUG: ReturnSentinel 真传 afk_minutes=96 (1.6h) 给主脑, 主脑撒 "eight-hour
# rest" — Sir 真理"我大概离开了一个多小时". ClaimTracer 老 _PAT_EN_COUNT 只抓
# 阿拉伯 \d+, "eight" 单词绕过 regex 没 trace. 准则 5 言出必行底线漏.
# 治本: 加 _PAT_EN_WORD_COUNT 抓英文单词数字 one~twenty + ten 倍数 +
# hyphenated "eight-hour / two-day / three-week" 形式.
# =====================================================================
# 单词数字 + 时间/计数单位 (含 hyphen 形式)
_PAT_EN_WORD_COUNT = re.compile(
    r'\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
    r'twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|'
    r'a|an|several|few|couple)'
    r'[-\s]+'
    r'(hour|hours|minute|minutes|day|days|week|weeks|month|months|year|years|'
    r'time|times|second|seconds|night|nights|morning|mornings|'
    r'session|sessions)s?\b',
    re.IGNORECASE,
)

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

# 🩹 [β.3.0 BUG#4 / 2026-05-18] past-action claim 提取
# Sir 14:00 痛点: 主脑说"已打开看板"但实际工具失败 → 言行不一.
# 此 regex 抓 reply 里"已 X / I've X / opened X / muted X"动作.
# Trace 时需要 tool_results 至少有 ✅ 才算 verified, 否则 unverified action lie.
_PAT_PAST_ACTION_ZH = re.compile(
    r'(已经?|帮?你?)\s*(打开|开启|启动|关闭|关掉|静音|发送|发了|设置|设好|'
    r'调好|调成|调到|更新|记下|存了|存好|保存|删除|删了|取消|'
    # 🆕 [P5-fix40 / 2026-05-23 12:21] Sir 12:17 真痛点: 主脑说"已安排了 90 分钟
    # 饮水提醒" 但**没真发 cyclic_task FAST_CALL**. ClaimTracer 漏抓因为词表
    # 不含"安排". 补: 安排/计划/预定/创建/记录/记在/写入/排好/调度/订/订上/
    # 添加/加入/写好/挂上 (主脑常用 commit-style verb).
    r'安排|安排好|计划|计划好|预定|创建|记录|记在|写入|排好|调度|订上|订好|'
    r'添加|加入|写好|挂上|挂好|登记|登记好|放好|放上)\s*([了好])?'
)
_PAT_PAST_ACTION_EN = re.compile(
    r"\b(?:i'?ve|i have|i)\s+(opened|launched|started|closed|muted|sent|"
    r"set|updated|saved|deleted|cancelled|"
    # 🆕 [P5-fix40] commit-style verbs — Sir 12:17 真痛点同因.
    r"scheduled|arranged|planned|created|registered|added|"
    r"configured|noted|logged|recorded|booked|stored|"
    r"installed|enabled|disabled|attached|configured)\b",
    re.IGNORECASE
)


# ============================================================
# Claim datatypes
# ============================================================

class Claim:
    """一个 specific factual claim.

    🆕 [Reshape M3.B.Claim / 2026-05-24] 推荐新代码用 `FactClaim` 别名 (更准确,
    跟 `jarvis_integrity_watcher.IntegrityClaim` 区分). 老 `Claim` 名保留 0 改动.
    """

    def __init__(self, kind: str, text: str, span: Tuple[int, int] = (0, 0)):
        self.kind = kind          # 'time' / 'percent' / 'count' / 'quote'
        self.text = text          # 命中的字串 (e.g. "23:14:06" / "87%" / "Sir said X")
        self.span = span
        self.has_uncertainty = False
        self.trace_to = None      # 'tool:xxx' | 'stm:turn_n' | 'uncertainty' | None
        self.trace_what = ''

    def __repr__(self):
        return f"Claim({self.kind} '{self.text}' trace={self.trace_to})"


# [Reshape M3.B.Claim / 2026-05-24] 新名 alias — 推荐新代码用 FactClaim 更准确
# (vs jarvis_integrity_watcher.IntegrityClaim). 老 Claim 名保留兼容 0 caller 改.
FactClaim = Claim


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
    # 🆕 [Sir 2026-05-25 20:01] 英文单词数字 + duration unit (eight-hour rest 等)
    for m in _PAT_EN_WORD_COUNT.finditer(text):
        claims.append(Claim('count', m.group(0), m.span()))

    # Quote attribution (Sir 说...)
    for pat in (_PAT_QUOTE_ATTR_EN, _PAT_QUOTE_ATTR_ZH):
        for m in pat.finditer(text):
            claims.append(Claim('quote', m.group(0)[:80], m.span()))

    # 🩹 [β.3.0 BUG#4] past-action claim — Sir 14:00 治本
    for m in _PAT_PAST_ACTION_ZH.finditer(text):
        claims.append(Claim('past_action', m.group(0), m.span()))
    for m in _PAT_PAST_ACTION_EN.finditer(text):
        claims.append(Claim('past_action', m.group(0), m.span()))

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

# 🩹 [β.4.3.3 / 2026-05-18] PromiseLog 标签抽取 (Future tense claim evidence)
# 主脑 emit <PROMISE>...</PROMISE> → PromiseLog 写入 → 当作 Future evidence.
# 逻辑上完整 promise tag schema 在 jarvis_promise_log.py / jarvis_directives.py;
# 这里只抽 inner text 供 L2 evidence_kind 'promise_log_recorded' 查表.
_PAT_PROMISE_TAG = re.compile(r'<PROMISE[^>]*>(.*?)</PROMISE>',
                                re.IGNORECASE | re.DOTALL)

# 🩹 [β.4.3.3] time claim 解析 — 'HH:MM(:SS)?' / 'H:MM am/pm' 两种格式
_PAT_TIME_PARSE_HHMM = re.compile(r'\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b')
_PAT_TIME_PARSE_AMPM = re.compile(
    r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)\b')


def _extract_promise_tags(reply: str) -> List[str]:
    """从 reply 里抽 <PROMISE>...</PROMISE> inner text list. 空/无返 []."""
    if not reply:
        return []
    try:
        return [m.group(1).strip() for m in _PAT_PROMISE_TAG.finditer(reply)
                if m.group(1) and m.group(1).strip()]
    except Exception:
        return []


def _parse_time_to_hm(text: str) -> Optional[tuple]:
    """从 text 里抽第一个时间字段 → (hour, minute) 24h. 失败返 None.

    支持:
      - 'HH:MM' / 'HH:MM:SS' (24h)
      - 'H[:MM] am/pm' (美式)
      - 不合法范围 返 None (如 '99:99')
    """
    if not text:
        return None
    m = _PAT_TIME_PARSE_HHMM.search(text)
    if m:
        try:
            h = int(m.group(1))
            mn = int(m.group(2))
        except (TypeError, ValueError):
            return None
        if 0 <= h < 24 and 0 <= mn < 60:
            return (h, mn)
        return None
    m = _PAT_TIME_PARSE_AMPM.search(text)
    if m:
        try:
            h = int(m.group(1))
            mn = int(m.group(2) or '0')
        except (TypeError, ValueError):
            return None
        if not (1 <= h <= 12 and 0 <= mn < 60):
            return None
        ampm = m.group(3).lower()
        if ampm == 'pm' and h < 12:
            h += 12
        elif ampm == 'am' and h == 12:
            h = 0
        return (h, mn)
    return None


def _check_time_within_2min(claim: 'Claim',
                              system_clock: Optional[float]) -> bool:
    """time claim 与 system_clock (epoch float) 的 diff <= 2 min. midnight wrap 兼."""
    if system_clock is None:
        return False
    hm = _parse_time_to_hm(claim.text or '')
    if hm is None:
        return False
    try:
        lt = time.localtime(float(system_clock))
    except (TypeError, ValueError, OSError):
        return False
    cur_mins = lt.tm_hour * 60 + lt.tm_min
    claim_mins = hm[0] * 60 + hm[1]
    diff = abs(cur_mins - claim_mins)
    diff = min(diff, 1440 - diff)  # midnight wrap
    return diff <= 2


# 🩹 [β.4.3.3 / 2026-05-18] 老 trace_to label alias 保 β.2.8.7 testcase 不破
# β.2.8.7 testcase 直接 assert claim.trace_to == 'tool' / 'stm' / 'tool_success'.
# 新 vocab 路径用 evidence_kind canonical 名 (tool_results_any / stm_match / ...).
# 通过 alias 让 trace_to 继续返回老短名, evidence_kind 全名记到 trace_what 后缀.
_LEGACY_TRACE_LABEL = {
    'tool_results_success': 'tool_success',
    'tool_results_any': 'tool',
    'stm_match': 'stm',
    'ltm_match': 'ltm',
    'system_clock_within_2min': 'system_clock',
    'promise_log_recorded': 'promise_log',
    'uncertainty_marker_nearby': 'uncertainty',
    'none': 'none',
}


def _check_evidence_kind(kind: str, claim: 'Claim',
                           tool_results: List, stm_recent: List,
                           system_clock: Optional[float],
                           ltm_context: str,
                           promise_log_tags: Optional[List[str]]) -> bool:
    """单个 evidence_kind 查表 dispatcher. 未识别的 kind 返 False (fail-safe)."""
    if kind == 'none':
        return True
    if kind == 'uncertainty_marker_nearby':
        return bool(getattr(claim, 'has_uncertainty', False))
    needle = (getattr(claim, 'text', '') or '').lower()
    nc = re.sub(r'\s+', '', needle) if needle else ''
    if kind == 'tool_results_success':
        for tr in tool_results or []:
            if '✅' in str(tr):
                return True
        return False
    if kind == 'tool_results_any':
        if not needle:
            return False
        for tr in tool_results or []:
            tr_l = str(tr).lower()
            if needle in tr_l or (nc and nc in re.sub(r'\s+', '', tr_l)):
                return True
        return False
    if kind == 'stm_match':
        if not needle:
            return False
        for entry in (stm_recent or [])[-10:]:
            try:
                blob = (str(entry.get('user', '')) + ' '
                        + str(entry.get('jarvis', ''))).lower()
            except AttributeError:
                continue
            if needle in blob or (nc and nc in re.sub(r'\s+', '', blob)):
                return True
        return False
    if kind == 'ltm_match':
        if not needle or not ltm_context:
            return False
        return needle in str(ltm_context).lower()
    if kind == 'system_clock_within_2min':
        return _check_time_within_2min(claim, system_clock)
    if kind == 'promise_log_recorded':
        if not promise_log_tags or not needle:
            return False
        for tag in promise_log_tags:
            if needle in str(tag).lower():
                return True
        return False
    return False  # 未识别 kind: fail-safe 返 False


def _trace_via_legacy(claim: 'Claim', tool_results: List,
                       stm_recent: List) -> bool:
    """老硬编码路径 (β.2.8.7 + β.3.0 BUG#4 原逻辑). 仅 use_vocab=False 走.

    保留预防回归: testcase 可显式调 use_vocab=False 验证老行为.
    """
    # past_action 必须 tool 真成功 (β.3.0 BUG#4)
    if claim.kind == 'past_action':
        for tr in tool_results or []:
            tr_s = str(tr)
            if '✅' in tr_s:
                claim.trace_to = 'tool_success'
                claim.trace_what = tr_s[:100]
                return True
        return False
    needle = (claim.text or '').lower()
    needle_compact = re.sub(r'\s+', '', needle)
    for tr in tool_results or []:
        tr_l = str(tr).lower()
        if needle in tr_l or needle_compact in re.sub(r'\s+', '', tr_l):
            claim.trace_to = 'tool'
            claim.trace_what = str(tr)[:100]
            return True
    for entry in (stm_recent or [])[-10:]:
        try:
            blob = (str(entry.get('user', '')) + ' '
                    + str(entry.get('jarvis', ''))).lower()
        except AttributeError:
            continue
        if needle in blob or needle_compact in re.sub(r'\s+', '', blob):
            claim.trace_to = 'stm'
            claim.trace_what = blob[:100]
            return True
    return False


def _trace_via_vocab(claim: 'Claim', tool_results: List, stm_recent: List,
                       system_clock: Optional[float], ltm_context: str,
                       promise_log_tags: Optional[List[str]],
                       classify_vocab_path: Optional[str] = None,
                       evidence_vocab_path: Optional[str] = None) -> bool:
    """新 L1+L2 表驱 evidence 路径 (β.4.3.3 默认).

    1. L1 classify 出 claim_type
    2. L2 get_requirements -> evidence_kinds list
    3. 空 list (Unknown / 补不到) → fail-safe 返 True 不 audit
    4. 逐 evidence_kind 调 _check_evidence_kind, 任一命中 → True
    5. 全未命中 → False
    """
    try:
        from jarvis_claim_classifier import classify as _classify
        from jarvis_evidence_requirements import get_requirements as _get_req
    except Exception:
        # L1/L2 import 失败 → 退走老路径 (defense in depth)
        return _trace_via_legacy(claim, tool_results, stm_recent)

    try:
        claim_type = _classify(claim.text or '', claim.kind,
                                  vocab_path=classify_vocab_path)
        required = _get_req(claim_type, vocab_path=evidence_vocab_path)
    except Exception:
        return _trace_via_legacy(claim, tool_results, stm_recent)

    # fail-safe: Unknown / 空 requirements → 视为 verified (不 audit, 防死循环)
    if not required:
        claim.trace_to = 'no_requirement_failsafe'
        claim.trace_what = f'claim_type={claim_type}'
        return True

    for ek in required:
        try:
            ok = _check_evidence_kind(ek, claim, tool_results, stm_recent,
                                         system_clock, ltm_context,
                                         promise_log_tags)
        except Exception:
            ok = False
        if ok:
            # β.4.3.3: 用 legacy alias 保 β.2.8.7 testcase 老断言不破
            # canonical evidence_kind name 记到 trace_what 后缀 (诊断用)
            claim.trace_to = _LEGACY_TRACE_LABEL.get(ek, ek)
            claim.trace_what = f'claim_type={claim_type} evidence_kind={ek}'
            return True
    return False


def trace_to_evidence(claim: 'Claim', tool_results: List,
                       stm_recent: List,
                       system_clock: Optional[float] = None,
                       ltm_context: str = '',
                       promise_log_tags: Optional[List[str]] = None,
                       use_vocab: bool = True,
                       classify_vocab_path: Optional[str] = None,
                       evidence_vocab_path: Optional[str] = None) -> bool:
    """看 claim 是否能 trace 到 evidence. 返 True = 找到 trace.

    [β.4.3.3 / 2026-05-18] L1 + L2 表驱 默认 (use_vocab=True). Legacy 保留.

    优先级:
      1. uncertainty marker (已标) — 两路径都看
      2. use_vocab=True → _trace_via_vocab (表驱)
      3. use_vocab=False → _trace_via_legacy (老硬编码路径, 回归验证)

    防恶性耦合 BUG (β.4.2-hotfix 教训):
      - 新参默认值 → 老调用方 (传 3 positional) 零修改
      - L1/L2 import 失败 → 退走 legacy
      - L1/L2 vocab 损坏 → seed fallback (在 L1/L2 内部处理)
      - Unknown 类 / 空 requirements → fail-safe verified (不 audit 不死循环)
    """
    if claim.has_uncertainty:
        claim.trace_to = 'uncertainty'
        return True
    if use_vocab:
        return _trace_via_vocab(
            claim, tool_results, stm_recent,
            system_clock=system_clock, ltm_context=ltm_context,
            promise_log_tags=promise_log_tags,
            classify_vocab_path=classify_vocab_path,
            evidence_vocab_path=evidence_vocab_path,
        )
    return _trace_via_legacy(claim, tool_results, stm_recent)


# ============================================================
# 主 API: trace 一段 reply + log unverified claims
# ============================================================

def _fetch_swm_tool_results(within_seconds: float = 60.0) -> List[str]:
    """🩹 [P1-Gap9 / 2026-05-20 23:25] 从全局 event_bus 拿最近 N 秒的 'tool_called' events,
    转 string 给 ClaimTracer 作 evidence.

    🆕 [P5-fix77-R / 2026-05-23 19:11] BUG-R: 跨 module mutation evidence gap.
    Sir 19:09 真测痛点: 主脑说 "I've updated your profile" → ClaimTracer 报 unverified.
    但实际 Memory Correction 真做了 mutation (走 MemoryGateway, 不进 tool_results).
    修法: 扩展 _fetch_swm_tool_results 也拿 mutation events (memory_corrected /
    sir_field_updated / memory_update / profile_field_updated) 作 ✅ evidence,
    让 ClaimTracer 不再 false-positive "I've updated profile" 类幻觉警告.

    覆盖 IntentResolver 异步调 tool 的 trace gap — 主脑下轮看 [INTENT RESOLVED] 知道
    tool 真生效, ClaimTracer 也应该看到 SWM tool_called events 作 evidence, 不再
    false-positive unverified 警告.

    格式 (跟 _PAT_PAST_ACTION 兼容):
      "✅ tool_name(args_snippet)" — 成功 tool, 算 verify 证据
      "❌ tool_name(args_snippet) — error_snippet" — 失败 tool, 不算证据

    Returns:
      List[str] — 可空 (没 event_bus / 没 events 都返 [])
    """
    try:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus is None:
            return []
        # 🆕 [P5-fix77-R] 加 mutation events 类型, 覆盖 MemoryGateway 等跨模块路径
        events = bus.recent_events(
            within_seconds=within_seconds,
            types={'tool_called', 'memory_corrected', 'sir_field_updated',
                   'memory_update', 'profile_field_updated',
                   'concern_modified', 'promise_fulfilled'},
        ) or []
        results = []
        for ev in events:
            meta = ev.get('metadata') or {}
            # 🆕 [Sir 2026-05-26 22:35 fix] publish 内部 store 用 'type' key (line 1600).
            # 老 BUG: 用 'etype' 永远空 → 全走 else fallback → '✅ (...)' 不分 ok/fail.
            etype = ev.get('type', '') or ev.get('etype', '')  # bw-compat 兜底
            # tool_called 类: 老格式 (name + args + ok)
            if etype == 'tool_called':
                name = meta.get('name', '?')
                args = meta.get('args') or {}
                ok = bool(meta.get('ok', False))
                err = str(meta.get('error', ''))[:80]
                result_summary = str(meta.get('result_summary', ''))[:120]
                try:
                    import json as _json
                    args_snip = _json.dumps(args, ensure_ascii=False)[:80]
                except Exception:
                    args_snip = str(args)[:80]
                if ok:
                    results.append(f"✅ {name}({args_snip}) — {result_summary}")
                else:
                    results.append(f"❌ {name}({args_snip}) — {err}")
            else:
                # 🆕 [P5-fix77-R] mutation 类 events: SWM 已 publish = mutation 成功
                # 用 etype + description 作 ✅ evidence (主脑能 trace "updated profile"
                # 类 claim 到 'sir_field_updated' event).
                desc = str(ev.get('description', '') or '')[:120]
                results.append(f"✅ {etype}({desc})")
        return results
    except Exception:
        return []


# ============================================================
# 🆕 [P5-fix22 / 2026-05-22] retract context detection
# Sir 17:05 真测痛点: 主脑被 INTEGRITY ALERT prepend 强制撤回 "95%" → reply 含
# "withdraw 95%" → ClaimTracer 抽 "95%" 当 unverified → 入 audit → 下轮 ALERT
# 又 inject → 主脑又撤回 → 死循环 7-8 轮.
# 修法: claim 在 retract context (主脑明确撤回的话术) 中 → skip audit.
# 准则 5: 主脑在退缩 = 不 commit, 不应当 factual claim.
# 准则 6 next-iter: 把 phrases 持久化到 memory_pool/claim_retract_vocab.json + CLI.
# ============================================================

_RETRACT_PHRASES_HARDCODED = (
    # 英文 retract patterns
    'withdraw', 'retract', 'unfounded', 'baseless',
    'unverified estimate', 'unverified figure', 'no data to support',
    'no live sensor', 'no live telemetry', 'cannot verify',
    "can't verify", 'lack the data', 'lack empirical',
    'i must correct', 'i must withdraw', 'i must retract',
    'must formally withdraw', 'must formally retract',
    'on reflection', 'in hindsight', 'must withdraw',
    # 中文 retract patterns
    '撤回', '收回', '没有依据', '没有数据', '无凭据',
    '不应该提', '不该提到', '我必须撤回', '必须收回',
    '没有实时数据', '没有实时传感', '没有依据的估算',
    '没有事实依据', '不实', '没有支持', '我没有数据',
    '没有可证实', '一个未经核实', '未经核实',
)


def _is_claim_in_retract_context(reply: str, claim_text: str,
                                     window_chars: int = 150) -> bool:
    """检测 claim 是否在 retract 话术上下文中 (P5-fix22).

    主脑 reply 含 "withdraw 95%" / "我必须撤回 95%" 等 → 周围 ±150 chars
    含 retract phrase → return True. trace_reply 看到 True → skip audit.
    """
    if not reply or not claim_text:
        return False
    try:
        idx = reply.find(claim_text)
        if idx < 0:
            return False
        start = max(0, idx - window_chars)
        end = min(len(reply), idx + len(claim_text) + window_chars)
        snippet = reply[start:end].lower()
        return any(p in snippet for p in _RETRACT_PHRASES_HARDCODED)
    except Exception:
        return False


def trace_reply(jarvis_reply: str,
                  tool_results: Optional[List[str]] = None,
                  stm_recent: Optional[List[Dict]] = None,
                  turn_id: str = '',
                  system_clock: Optional[float] = None,
                  ltm_context: str = '',
                  use_vocab: bool = True,
                  classify_vocab_path: Optional[str] = None,
                  evidence_vocab_path: Optional[str] = None,
                  include_swm_tool_called: bool = True,
                  swm_lookback_s: float = 180.0) -> dict:
    """对 Jarvis reply 跑 claim trace. fire-and-forget, 返 stats.

    Args:
      jarvis_reply: 主脑当轮输出 (含中英文混合)
      tool_results: 当轮所有 fast_call 返回的 result strings (空 list 也 ok)
      stm_recent: 当前 STM (last ~10 entries) 含 user + jarvis 历史
      turn_id: trace id 给 log
      system_clock: [β.4.3.3] 当前 epoch float, 供 time claim verify (None → time claim 走不了 SYSTEM CLOCK 路径)
      ltm_context: [β.4.3.3] 本轮 prompt 注入的 LTM 串, 供 ltm_match
      use_vocab: [β.4.3.3] True 默认 → L1+L2 表驱; False → legacy 老硬编码
      classify_vocab_path / evidence_vocab_path: testcase 注入用, 默认走全局
      include_swm_tool_called: [P1-Gap9 / 2026-05-20] True 默认 → 从 event_bus 拿
                              最近 60s 'tool_called' events 作 evidence. False 关闭
                              (testcase 隔离用).
      swm_lookback_s: [P1-Gap9] SWM lookback 窗口, default 60s.

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

    tool_results = list(tool_results or [])
    stm_recent = stm_recent or []

    # 🩹 [P1-Gap9 / 2026-05-20 23:25] 拼接 SWM tool_called events 进 tool_results.
    # 治 false-positive: IntentResolver async 调 tool 成功后, 主脑下轮 reply 说
    # "已为您 X", ClaimTracer 现在能看到 SWM 有 ✅ tool_called → verify.
    if include_swm_tool_called:
        swm_results = _fetch_swm_tool_results(within_seconds=swm_lookback_s)
        if swm_results:
            tool_results.extend(swm_results)
    # β.4.3.3: 抽 PromiseLog tags 一次 (per-reply, 不该每 claim 抽 1 次)
    promise_log_tags = _extract_promise_tags(jarvis_reply) if use_vocab else None

    n_verified = 0
    n_unverified = 0
    n_skipped_retract = 0
    unverified_examples: List[str] = []
    for c in claims:
        # 🆕 [P5-fix22 / 2026-05-22] retract context skip — 治死循环
        # 主脑明确 withdraw/retract 当前 claim → 不当 factual, 不入 audit
        # 否则下轮 build_integrity_alert 又 inject → 主脑又撤 → 死循环.
        if _is_claim_in_retract_context(jarvis_reply, c.text):
            n_skipped_retract += 1
            continue

        ok = trace_to_evidence(
            c, tool_results, stm_recent,
            system_clock=system_clock, ltm_context=ltm_context,
            promise_log_tags=promise_log_tags, use_vocab=use_vocab,
            classify_vocab_path=classify_vocab_path,
            evidence_vocab_path=evidence_vocab_path,
        )
        if ok:
            n_verified += 1
        else:
            n_unverified += 1
            unverified_examples.append(f"[{c.kind}] '{c.text}'")
            # 🩹 [β.3.5 INTEGRITY_STACK L4 enforce / 2026-05-18]
            # 仅 unverified 入 audit jsonl (防文件膨胀; verified 由 _CLAIM_STATS 计总量)
            try:
                _audit_reason = (
                    'no ✅ marker in tool_results' if c.kind == 'past_action'
                    else 'no match in tool_results or STM'
                )
                write_audit_entry(turn_id, c, found=False,
                                    reason=_audit_reason)
            except Exception:
                pass

    if n_skipped_retract > 0:
        try:
            bg_log(
                f"🛡️ [ClaimTracer/RetractSkip P5-fix22] turn={turn_id or '?'} "
                f"skipped {n_skipped_retract} claim(s) in retract context "
                f"(主脑明确撤回, 不入 audit, 防死循环)"
            )
        except Exception:
            pass

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


# ============================================================
# 🩹 [β.3.5 / 2026-05-18] INTEGRITY_STACK L4 enforce —
#   integrity_audit.jsonl 持久化 + [INTEGRITY ALERT] 注入下一轮 prompt
#
# 设计准则:
#   - 准则 5 (言出必行): unverified factual claim 必须 trace 到 evidence;
#     上轮未在 evidence 里的 claim 要在下轮 “主动撤回 或 补 evidence”.
#   - 准则 6 (不硬编码): ALERT 只 trace 事实 (turn_id / kind / claim text),
#     不教主脑具体中文句式 — 主脑自己决定怎么措辞.
#   - 准则 6.5 (动态 schema): audit file 路径可注入 (testcase 隔离),
#     entries jsonl 追写, 仅 unverified 入表 (verified 由 _CLAIM_STATS 计趋势).
# ============================================================

_INTEGRITY_AUDIT_PATH = os.path.join('memory_pool', 'integrity_audit.jsonl')


def _ensure_audit_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


def write_audit_entry(turn_id: str, claim: 'Claim', found: bool,
                       reason: str = '', evidence_kind: str = '',
                       audit_path: Optional[str] = None) -> bool:
    """Append 1 行 audit jsonl. 仅 unverified (found=False) 入表; 失败返 False 不 raise.

    schema (per line): ts / iso / turn_id / claim / kind / evidence_kind / found / reason
    """
    if found:
        return False  # 仅 incident 入表, 防文件膨胀
    # 🩹 [β.4.2-hotfix / 2026-05-18] Sir 18:46 实测死循环治本:
    # `time` kind claim verify 路径不看 prompt SYSTEM CLOCK 注入 → 永远 found=False →
    # 每次主脑报时间都进 audit → ALERT 注入下轮 → 主脑道歉但又报时间 → 死循环.
    # 临时止血: time kind 跳过 audit (诊断 bg_log 仍发, 不影响 trace).
    # 真治本 (β.4.3+ TODO): 加 SYSTEM CLOCK ±2 min 比较 verify, 命中则 found=True.
    if getattr(claim, 'kind', '') == 'time':
        return False
    path = audit_path or _INTEGRITY_AUDIT_PATH
    try:
        _ensure_audit_dir(path)
        entry = {
            'ts': time.time(),
            'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'turn_id': turn_id or '',
            'claim': (getattr(claim, 'text', '') or '')[:200],
            'kind': getattr(claim, 'kind', ''),
            'evidence_kind': evidence_kind or (getattr(claim, 'trace_to', '') or ''),
            'found': bool(found),
            'reason': (reason or '')[:200],
        }
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True
    except OSError:
        return False


def read_recent_unverified(limit: int = 50,
                            exclude_turn_id: str = '',
                            audit_path: Optional[str] = None) -> List[dict]:
    """读 audit jsonl 尾 limit 行, 返回 found=False 且 turn_id != exclude_turn_id 的条目.

    失败 / 文件不存在 / 损坏 都返 [] 不 raise. limit 防读海量 jsonl.
    """
    path = audit_path or _INTEGRITY_AUDIT_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return []
    entries: List[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except (ValueError, TypeError):
            continue
        if e.get('found'):
            continue
        if exclude_turn_id and e.get('turn_id') == exclude_turn_id:
            continue
        entries.append(e)
    return entries


def build_integrity_alert(current_turn_id: str = '',
                            limit: int = 20,
                            audit_path: Optional[str] = None,
                            max_age_s: float = 600.0) -> str:
    """构造 [INTEGRITY ALERT] 提示串, 供 _assemble_prompt prepend 到 system_alert_text.

    仅访问 immediate previous turn 的 unverified entries (按 ts 分 turn-group 取最新).
    无则返 ''. 任何异常返 '' 不 raise (保主路径).

    准则 5 / 准则 6 设计:
      - 只述说上轮的 claim 未 verify 事实, 两个选项 (withdraw / supply evidence)
      - 不写上中文句式 / 不指定使用 '其实/I'm sorry/On reflection' 等 wording

    🩹 [β.5.46-fix17 / 2026-05-22] Sir 11:39 真测 BUG: Jarvis 主动 "withdraw 95% figure"
    Root cause: 11:26 audit 写了 {"turn_id": "", "claim": "95%"} (空 turn_id —
    daemon/跨 session 路径, 不对应任何 main turn). build_integrity_alert 按 ts 排
    选 "上轮" 时把这条空 turn_id entry 算成上轮 → inject 95% 给 11:39 turn → 主脑
    被 prompt 强迫道歉一个 Sir 没要求道歉的事 ("他不算骗人, 为啥道歉?").
    修: 过滤 turn_id="" entry, 仅算真有 turn_id 的 audit (= 真主 turn 的 unverified).

    🆕 [P5-fix39 / 2026-05-23 12:18] Sir audit 真发现: integrity_audit.jsonl 是
    append-only 不清, 每 turn 都把**N 小时前**的 stale unverified turn 反复
    inject. Sir 12:08 后每 turn 看到 'unverified=279c' 同长度 — 都是 11:05 的
    stale claim 被反复 inject. 治本: max_age_s 默认 600s (10min), latest_turn
    最旧 ts < now - max_age_s → 不 inject (太老 = stale, 主脑别被强迫 ack).
    """
    try:
        unv = read_recent_unverified(limit=limit,
                                       exclude_turn_id=current_turn_id,
                                       audit_path=audit_path)
    except Exception:
        return ''
    if not unv:
        return ''
    # 🩹 [β.5.46-fix17] 过滤 turn_id="" — 不对应 main turn 的 claim 不该 inject ALERT
    unv = [e for e in unv if (e.get('turn_id') or '').strip()]
    if not unv:
        return ''
    # 🆕 [P5-fix39] staleness filter — 过滤 max_age_s 之前的 stale entries
    try:
        import time as _time_pf39
        now_ts = _time_pf39.time()
        unv = [e for e in unv
                 if (now_ts - float(e.get('ts', 0))) < float(max_age_s)]
    except Exception:
        pass
    if not unv:
        return ''
    # 按 turn_id group, 取 ts 最大的 turn (immediate prior turn)
    by_turn: Dict[str, List[dict]] = {}
    for e in unv:
        by_turn.setdefault(e.get('turn_id') or '?', []).append(e)
    if not by_turn:
        return ''
    latest_turn = max(by_turn.keys(),
                       key=lambda k: max(float(e.get('ts', 0)) for e in by_turn[k]))
    # 🆕 [P5-Layer1-fix19 / 2026-05-22] Sir 13:13 立 — 主脑 META skip_alert 检查.
    # 主脑上轮 SELF_CHECK 已经 emit [META] skip_alert=yes (e.g. fix17 case 主脑
    # 自己看出 IntegrityAlert 引用的是 daemon 空 turn_id, 拒绝道歉) → 本轮就别再
    # inject ALERT 强迫道歉. 主脑自决优先 (准则 6 决策集中主脑).
    try:
        from jarvis_meta_self_check import find_meta_for_turn
        latest_meta = find_meta_for_turn(latest_turn)
        if latest_meta and latest_meta.get('skip_alert'):
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🧠 [SelfCheck/SkipAlert] turn={latest_turn} 主脑已 skip_alert=yes, "
                    f"本轮不再 inject INTEGRITY ALERT (主脑自决, 准则 6)"
                )
            except Exception:
                pass
            return ''
    except Exception:
        pass
    prior = by_turn[latest_turn]
    n = len(prior)
    examples = ' / '.join(
        f"[{e.get('kind')}] \"{e.get('claim')}\""
        for e in prior[:3]
    )
    if n > 3:
        examples += f" / ... (+{n - 3} more)"
    # 🆕 [Sir 2026-05-24 23:41 真测追根 BUG 治本] mark turn as INTEGRITY-injected
    # 给 PreFlight 看 — INTEGRITY 教主脑承认上轮错, 道歉是合规不是 unsolicited.
    try:
        _mark_alert_injected(current_turn_id)
    except Exception:
        pass
    return (
        f"[INTEGRITY ALERT] Your previous turn ({latest_turn}) had {n} "
        f"unverified factual claim(s): {examples}. In THIS reply, either "
        f"acknowledge and withdraw plainly, or supply the missing evidence. "
        f"Do not pretend it was never said. (准则 5 言出必行)"
    )


# ============================================================
# 🆕 [Sir 2026-05-24 23:41 真测追根 BUG 治本] alert_injected tracker
# ============================================================
# 防 INTEGRITY (教主脑承认上轮错) vs PreFlight (Q1 unsolicited callback) 两防线打架.
# build_integrity_alert 返非空时 mark turn → PreFlight check 时豁免 Q1.
# 60s TTL rolling, 防内存泄漏.
# ============================================================
_ALERT_INJECTED_TURNS: Dict[str, float] = {}
_ALERT_INJECTED_LOCK = threading.Lock()


def _mark_alert_injected(turn_id: str) -> None:
    """build_integrity_alert 返非空时调."""
    if not turn_id:
        return
    with _ALERT_INJECTED_LOCK:
        _ALERT_INJECTED_TURNS[turn_id] = time.time()
        # GC: 60s 前的清掉
        _now = time.time()
        _stale = [k for k, v in _ALERT_INJECTED_TURNS.items() if _now - v > 60]
        for k in _stale:
            _ALERT_INJECTED_TURNS.pop(k, None)


def was_alert_injected_this_turn(turn_id: str) -> bool:
    """PreFlight 查 — 本轮 INTEGRITY/Alert 已 inject → 豁免 Q1 unsolicited callback."""
    if not turn_id:
        return False
    with _ALERT_INJECTED_LOCK:
        return turn_id in _ALERT_INJECTED_TURNS
