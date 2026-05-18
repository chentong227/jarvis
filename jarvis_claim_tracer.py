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

# 🩹 [β.3.0 BUG#4 / 2026-05-18] past-action claim 提取
# Sir 14:00 痛点: 主脑说"已打开看板"但实际工具失败 → 言行不一.
# 此 regex 抓 reply 里"已 X / I've X / opened X / muted X"动作.
# Trace 时需要 tool_results 至少有 ✅ 才算 verified, 否则 unverified action lie.
_PAT_PAST_ACTION_ZH = re.compile(
    r'(已经?|帮?你?)\s*(打开|开启|启动|关闭|关掉|静音|发送|发了|设置|设好|'
    r'调好|调成|调到|更新|记下|存了|存好|保存|删除|删了|取消)\s*([了好])?'
)
_PAT_PAST_ACTION_EN = re.compile(
    r"\b(?:i'?ve|i have|i)\s+(opened|launched|started|closed|muted|sent|"
    r"set|updated|saved|deleted|cancelled)\b",
    re.IGNORECASE
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

def trace_to_evidence(claim: Claim, tool_results: List[str],
                       stm_recent: List[Dict]) -> bool:
    """看 claim 是否能 trace 到 evidence. 返回 True = 找到 trace.

    优先级:
      1. uncertainty marker — 已标
      2. past_action 类: tool_results 必含 ✅ marker (β.3.0 BUG#4)
      3. tool_results 含该字串
      4. STM 含该字串 (Sir 原话或 jarvis 之前 reply)
    """
    if claim.has_uncertainty:
        claim.trace_to = 'uncertainty'
        return True

    # 🩹 [β.3.0 BUG#4 / 2026-05-18] past_action 必须 tool 真成功
    if claim.kind == 'past_action':
        for tr in tool_results or []:
            tr_s = str(tr)
            if '✅' in tr_s:
                claim.trace_to = 'tool_success'
                claim.trace_what = tr_s[:100]
                return True
        # past_action 没有 ✅ → 言行不一, 不 verify (不用 STM fallback)
        return False

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
                            audit_path: Optional[str] = None) -> str:
    """构造 [INTEGRITY ALERT] 提示串, 供 _assemble_prompt prepend 到 system_alert_text.

    仅访问 immediate previous turn 的 unverified entries (按 ts 分 turn-group 取最新).
    无则返 ''. 任何异常返 '' 不 raise (保主路径).

    准则 5 / 准则 6 设计:
      - 只述说上轮的 claim 未 verify 事实, 两个选项 (withdraw / supply evidence)
      - 不写上中文句式 / 不指定使用 '其实/I'm sorry/On reflection' 等 wording
    """
    try:
        unv = read_recent_unverified(limit=limit,
                                       exclude_turn_id=current_turn_id,
                                       audit_path=audit_path)
    except Exception:
        return ''
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
    prior = by_turn[latest_turn]
    n = len(prior)
    examples = ' / '.join(
        f"[{e.get('kind')}] \"{e.get('claim')}\""
        for e in prior[:3]
    )
    if n > 3:
        examples += f" / ... (+{n - 3} more)"
    return (
        f"[INTEGRITY ALERT] Your previous turn ({latest_turn}) had {n} "
        f"unverified factual claim(s): {examples}. In THIS reply, either "
        f"acknowledge and withdraw plainly, or supply the missing evidence. "
        f"Do not pretend it was never said. (准则 5 言出必行)"
    )
