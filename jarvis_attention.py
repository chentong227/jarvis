# -*- coding: utf-8 -*-
"""[P0+20-β.2.3 / 2026-05-16] Jarvis Attention — 灵魂工程 Layer 3

详 docs/JARVIS_SOUL_DRIVE.md §2.2（Layer 3 — Attention Allocation）+ §3.4。

核心：每次 _assemble_prompt 调用时**动态构造**一个 [ATTENTION RIGHT NOW] 块，
告诉主脑此刻的注意力分配：
- current_focus: 当前 user_input 的类型 + 前缀（让主脑明确"Sir 现在问的是什么"）
- long_term_watch: top 3 active concerns（提醒主脑"哪怕在闲聊也得考虑这些"）
- pending_followups: overdue 或最久没碰的 unfinished business（让主脑能自然 callback）

与 Layer 1/2 的区别：
- Layer 1 (Concerns): 是"我关心什么"的完整列表 + why_i_care
- Layer 2 (Relational): 是"我们之间"的笑点/默契/未竟之事**完整内容**
- Layer 3 (Attention): 是上述的**当前焦点摘要** —— 一行一条，让主脑视野
  里同时有"短期问题(Sir 输入)"+"长期挂念(concerns)"+"未竟之事(unfinished)"

注入位置：core_persona 之后（在 Layer 0/1/2 之后），由 _assemble_prompt
基于当前 user_input 动态构造，不缓存。

构造代价：< 5ms（纯字符串拼接 + 简单分类）。

容错：任何 ledger / store 缺失或抛错都返回 ''，不影响主路径。
"""
from __future__ import annotations

import re
import time
from typing import Any, List, Optional


# ============================================================
# 输入分类（current_focus）
# ============================================================

# 简单启发式：question / request / chat / continuation / commitment
_QUESTION_HINTS_EN = (
    'what', 'why', 'how', 'when', 'where', 'who', 'which',
    "what's", "where's", "how's",
    'can you', 'could you', 'do you', 'does ', 'is ', 'are ', 'will ',
)
_QUESTION_HINTS_ZH = ('吗', '?', '？', '什么', '怎么', '为什么', '为啥', '何时', '哪里', '哪个', '谁')

_REQUEST_HINTS_EN = (
    'please', 'help me', 'help with', 'open', 'launch', 'show me', 'find',
    'search', 'look up', 'remind', 'set ', 'create', 'make', 'write', 'send',
    'list ', 'play ',
)
_REQUEST_HINTS_ZH = ('帮我', '请', '帮忙', '打开', '启动', '搜', '找', '提醒', '记', '设', '播放', '关掉', '列')

_COMMITMENT_HINTS_EN = (
    "i'll", 'i will', "i'm going to", 'i plan', 'i promise', 'gonna ',
)
_COMMITMENT_HINTS_ZH = ('我会', '我要', '我打算', '答应', '保证', '一定')

_CONTINUATION_HINTS = (
    'actually', 'wait', 'also', 'and ', 'so ', 'about that', 'as i said',
    '对了', '另外', '还有', '刚才', '上次', '继续', '接着', '然后')


def classify_input(text: str) -> str:
    """启发式分类 user_input → focus type。返回 question / request / commitment /
    continuation / chat（默认）。"""
    if not text:
        return 'silence'
    t = text.strip().lower()
    if not t:
        return 'silence'

    if any(t.startswith(h) or h in t.split(None, 1)[0:1] for h in _QUESTION_HINTS_EN) \
            or any(h in t for h in _QUESTION_HINTS_ZH):
        return 'question'
    if any(h in t for h in _REQUEST_HINTS_EN) or any(h in text for h in _REQUEST_HINTS_ZH):
        return 'request'
    if any(h in t for h in _COMMITMENT_HINTS_EN) or any(h in text for h in _COMMITMENT_HINTS_ZH):
        return 'commitment'
    if any(t.startswith(h) for h in _CONTINUATION_HINTS) \
            or any(h in text for h in _CONTINUATION_HINTS):
        return 'continuation'

    return 'chat'


def is_short_input(text: str) -> bool:
    """< 6 words / < 12 chars 视为短输入。短输入下不注入大 attention 块。"""
    if not text:
        return True
    t = text.strip()
    if len(t) < 4:
        return True
    return len(t.split()) < 6


# ============================================================
# Top picks
# ============================================================

def _top_concerns(concerns_ledger, top_n: int = 3) -> List[dict]:
    """Top N active concerns by severity。返回 [{'id', 'severity', 'what_i_watch'}]。"""
    if concerns_ledger is None:
        return []
    try:
        active = concerns_ledger.list_active()
    except Exception:
        return []
    active = sorted(active, key=lambda c: -getattr(c, 'severity', 0.0))
    out = []
    for c in active[:top_n]:
        out.append({
            'id': getattr(c, 'id', '?'),
            'severity': float(getattr(c, 'severity', 0.0)),
            'what_i_watch': (getattr(c, 'what_i_watch', '') or '')[:60],
        })
    return out


def _top_unfinished(relational_state, top_n: int = 2) -> List[dict]:
    """Top N unfinished business：overdue 优先 + 最久没碰排前。"""
    if relational_state is None:
        return []
    try:
        ranked = relational_state._rank_unfinished(top_n)
    except Exception:
        return []
    out = []
    now = time.time()
    for u in ranked:
        age_h = (now - getattr(u, 'last_touched', now)) / 3600.0
        age_str = f"{age_h:.0f}h ago" if age_h < 48 else f"{age_h / 24:.1f}d ago"
        is_over = False
        try:
            is_over = u.is_overdue()
        except Exception:
            pass
        out.append({
            'id': getattr(u, 'id', '?'),
            'topic': (getattr(u, 'topic', '') or '')[:60],
            'last_touched_str': age_str,
            'overdue': is_over,
        })
    return out


# ============================================================
# 主入口
# ============================================================

def build_attention_block(concerns_ledger=None,
                          relational_state=None,
                          user_input: str = '',
                          stm: Optional[list] = None,
                          top_concerns: int = 3,
                          top_unfinished: int = 2,
                          max_chars: int = 500) -> str:
    """构造 [ATTENTION RIGHT NOW] 注入块。

    Returns 多行字符串。空 attention（没有 ledger、没有 input）返回 ''。

    结构示例：
        === ATTENTION RIGHT NOW ===
        [CURRENT FOCUS]
          - kind: question
          - preview: "Why did the cursor build fail again..."
        [LONG-TERM WATCH — top 3 by severity]
          - jarvis_keyrouter_health (0.50)
          - sir_cursor_payment (0.40)
          - sir_sleep_streak (0.30)

    [P0+20-β.2.3 / 2026-05-16] PENDING FOLLOWUPS 段已删（subagent 审计建议）：
    Layer 2 RelationalState.to_prompt_block 的 [UNFINISHED BUSINESS] 段已覆盖此能力，
    Layer 3 再列一遍是 100% 重复。Layer 3 仅做"动态当下"维度（focus + concerns），
    长期未竟之事归 Layer 2 单源管理。`top_unfinished` 参数保留作 API 兼容（已无效果）。

    详 docs/JARVIS_SOUL_DRIVE.md §2.2（Layer 3）+ subagent 审计 §5。
    """
    focus_kind = classify_input(user_input or '')
    is_short = is_short_input(user_input or '')

    # 短输入：只注入 LONG-TERM 摘要（不夹 current focus 一行废话）
    # 完全没有内容时返回 ''
    concerns_top = _top_concerns(concerns_ledger, top_concerns)

    if not concerns_top and not (user_input or '').strip():
        return ''

    lines: List[str] = ["=== ATTENTION RIGHT NOW ==="]

    if user_input and not is_short:
        preview = user_input.strip()[:90]
        lines.append("[CURRENT FOCUS]")
        lines.append(f"  - kind: {focus_kind}")
        lines.append(f"  - preview: \"{preview}\"")

    if concerns_top:
        lines.append("[LONG-TERM WATCH — top concerns I keep an eye on]")
        for c in concerns_top:
            lines.append(f"  - {c['id']} (sev={c['severity']:.2f}): {c['what_i_watch']}"[:160])

    # 若只剩 header，没内容 → 退化为空
    if len(lines) == 1:
        return ''

    out = "\n".join(lines)
    if len(out) > max_chars:
        _suffix = "\n…[truncated]"
        out = out[:max_chars - len(_suffix)].rstrip() + _suffix
    return out
