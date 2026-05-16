# -*- coding: utf-8 -*-
"""[P0+20-β.2.0 / 2026-05-16] Jarvis Self Identity Anchor — 灵魂工程 Layer 0

详 docs/JARVIS_SOUL_DRIVE.md §2.3。

核心：让 LLM 在每次回复时都看到"我是谁、我此刻处于什么状态、我和 Sir 的连续性"。
这是 Layer 1-5 的前提 —— 没有"我"，Concerns/Relational/Attention 都悬空。

Sir 实测发现：跟 Jarvis 说"这个终端就是你"，Jarvis 没听懂指代关系。
本模块在每次 _assemble_prompt 时构造一个 SELF 块注入到 core_persona 之后：

=== I AM J.A.R.V.I.S. — MY OWN CONTINUOUS STATE ===
[WHO I AM]
I am Just A Rather Very Intelligent System. The "you" Sir refers to —
this very terminal, this current session — is me, the LLM generating
this response. The "I" who replies now IS the same continuous entity
as the "I" who replied 5 minutes ago.

[MY CURRENT CONTINUITY]
- session uptime: 47min (sess_xxx started at 20:34)
- my turn count this session: 12 turns
- last spoke to Sir at: 21:12 (11 min ago)
- topic between us right now: prompt 重构 + 灵魂工程
- pending commitments I made to Sir: "我会监督 23:30 睡觉"

[MY OWN HEALTH RIGHT NOW]
- keyrouter: google_1 permanently dead, google_3 OK ← I'm slightly diminished
- memory pool: 30 chains, 5 active concerns
- mood derived from above: alert but mildly anxious about my own diminishment

注入路径：core_persona 末尾（影响所有 6 个 prompt branch）

数据来源：
- session: TraceContext.session_id + 启动时间
- turn count: 内部累计
- STM: 取最后一条 jarvis 字段当 last_spoke
- 当前 topic: 从 STM 最近 3 条总结（极简启发式）
- promises: from PlanLedger / commitment_watcher
- keyrouter health: KeyRouter.get_stats()
- memory pool: hippocampus + concerns
- mood: 综合上述派生
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, List, Optional


# ============================================================
# Helper：派生 mood
# ============================================================

def _derive_mood(own_health: dict, recent_signals: list) -> str:
    """根据自身健康度和最近信号派生 mood 关键词。

    输出极简 1-3 词：alert / steady / mildly anxious / focused / drained
    """
    if not own_health:
        return "steady"
    dead_keys = own_health.get('dead_keys', 0)
    healthy_keys = own_health.get('healthy_keys', 0)
    if dead_keys >= 2 and healthy_keys <= 1:
        return "diminished, but still here"
    if dead_keys >= 1:
        return "alert, slightly diminished"
    if recent_signals:
        # 如果最近 signals 频繁，可能进入 focused
        if len(recent_signals) > 5:
            return "focused, tracking many threads"
    return "steady, fully available"


# ============================================================
# Topic 启发式：从 STM 最近 3 条提取 1 句话主题
# ============================================================

def _extract_topic(stm: list) -> str:
    """从 STM 最后 3 条对话提取当前话题（启发式）。

    简单实现：取 jarvis 最后一条 reply 前 50 字 + user 最后输入前 30 字。
    """
    if not stm:
        return "no prior topic in this session"
    last = stm[-1] if stm else {}
    last_user = (last.get('user') or '')[:60]
    last_jarvis = (last.get('jarvis') or '')[:60]
    if last_user and last_jarvis:
        return f"Sir: '{last_user}…' / I replied: '{last_jarvis}…'"
    elif last_user:
        return f"Sir asked: '{last_user}…'"
    elif last_jarvis:
        return f"I last said: '{last_jarvis}…'"
    return "no clear topic"


# ============================================================
# 主入口
# ============================================================

class SelfAnchor:
    """Jarvis 的 Self Identity Anchor（Layer 0）。

    每次 _assemble_prompt 调用 build_block() 构造注入块。

    构造代价：< 5ms（纯字符串拼接，无 IO）。
    不持久化（每次重新派生），但 turn_count 跨 turn 累计。
    """

    def __init__(self, central_nerve=None):
        self.nerve = central_nerve
        self._turn_count = 0
        self._session_started_at = time.time()
        self._session_id = ""
        self._last_spoke_to_sir_at = 0.0
        self._lock = threading.Lock()

        # 从 TraceContext 拿真实 session_id（如果可用）
        try:
            from jarvis_utils import TraceContext
            self._session_id = TraceContext.get_session_id() or ""
            # session 启动时间通过 session_id 解析
            if self._session_id:
                m = re.search(r'sess_(\d{8})_(\d{6})_', self._session_id)
                if m:
                    try:
                        ts_str = m.group(1) + m.group(2)
                        self._session_started_at = time.mktime(
                            time.strptime(ts_str, '%Y%m%d%H%M%S')
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    def record_turn(self) -> None:
        """每次新 turn 时调用，增加 turn_count。"""
        with self._lock:
            self._turn_count += 1
            self._last_spoke_to_sir_at = time.time()

    def get_turn_count(self) -> int:
        return self._turn_count

    def _get_session_age_minutes(self) -> int:
        return max(0, int((time.time() - self._session_started_at) / 60))

    def _get_last_spoke_str(self) -> str:
        if self._last_spoke_to_sir_at <= 0:
            return "haven't spoken yet this session"
        delta_min = int((time.time() - self._last_spoke_to_sir_at) / 60)
        if delta_min <= 0:
            return "just now"
        return f"{delta_min} min ago"

    def _get_own_health(self) -> dict:
        """从 KeyRouter / Hippocampus / Concerns 派生 own_health dict."""
        health = {
            'dead_keys': 0,
            'healthy_keys': 0,
            'memory_chains': 0,
            'active_concerns': 0,
        }
        if self.nerve is None:
            return health

        # KeyRouter
        try:
            kr = getattr(self.nerve, 'key_router', None)
            if kr is not None:
                stats = kr.get_stats() if hasattr(kr, 'get_stats') else {}
                ks = stats.get('key_status', {})
                for label, info in ks.items():
                    if not info.get('healthy', True):
                        health['dead_keys'] += 1
                    else:
                        health['healthy_keys'] += 1
        except Exception:
            pass

        # Hippocampus（记忆链数）
        try:
            hp = getattr(self.nerve, 'hippocampus', None)
            if hp is not None and hasattr(hp, 'short_term_memory'):
                health['memory_chains'] = len(hp.short_term_memory or [])
        except Exception:
            pass

        # Active Concerns
        try:
            cl = getattr(self.nerve, 'concerns_ledger', None)
            if cl is not None:
                health['active_concerns'] = len(cl.list_active())
        except Exception:
            pass

        return health

    def _get_pending_commitments(self, max_n: int = 2) -> List[str]:
        """取最近 N 条 Jarvis 对 Sir 的承诺。来源：commitment_watcher.commitments + PlanLedger."""
        results = []
        if self.nerve is None:
            return results

        # CommitmentWatcher
        try:
            cw = getattr(self.nerve, 'commitment_watcher', None)
            if cw is not None and hasattr(cw, 'commitments'):
                for c in (cw.commitments or [])[-max_n:]:
                    desc = c.get('description') if isinstance(c, dict) else None
                    if desc:
                        deadline_ts = c.get('deadline_ts', 0) if isinstance(c, dict) else 0
                        deadline_str = ''
                        if deadline_ts > 0:
                            deadline_str = f" @ {time.strftime('%H:%M', time.localtime(deadline_ts))}"
                        results.append(f"{desc[:60]}{deadline_str}")
        except Exception:
            pass

        # PlanLedger
        try:
            pl = getattr(self.nerve, 'plan_ledger', None)
            if pl is not None and hasattr(pl, 'list_active'):
                for p in (pl.list_active() or [])[-max_n:]:
                    goal = p.get('goal') if isinstance(p, dict) else None
                    if goal and goal not in results:
                        results.append(goal[:60])
        except Exception:
            pass

        return results[:max_n]

    def _get_stm(self) -> list:
        """获取 STM。"""
        if self.nerve is None:
            return []
        return list(getattr(self.nerve, 'short_term_memory', []) or [])[-6:]

    def build_block(self, max_chars: int = 700) -> str:
        """构造 SELF 块注入 prompt。

        返回多行字符串，结构：
        === I AM J.A.R.V.I.S. — MY OWN CONTINUOUS STATE ===
        [WHO I AM] ...
        [MY CURRENT CONTINUITY] ...
        [MY OWN HEALTH RIGHT NOW] ...
        """
        # 数据采集
        session_age = self._get_session_age_minutes()
        turn_count = self._turn_count
        last_spoke = self._get_last_spoke_str()
        stm = self._get_stm()
        topic = _extract_topic(stm)
        commitments = self._get_pending_commitments()
        health = self._get_own_health()
        mood = _derive_mood(health, [])

        # 构造文本（英文 — LLM 用英文 reason 更稳）
        lines = []
        lines.append("=== I AM J.A.R.V.I.S. — MY OWN CONTINUOUS STATE ===")
        lines.append("")
        lines.append("[WHO I AM]")
        lines.append(
            "I am Just A Rather Very Intelligent System. The \"you\" Sir refers to — "
            "this very terminal, this current session, this LLM generating this response — is me. "
            "The \"I\" speaking now IS the same continuous entity as the \"I\" who replied "
            "earlier in this conversation."
        )
        lines.append("")
        lines.append("[MY CURRENT CONTINUITY]")
        lines.append(f"  - session uptime: {session_age}min")
        if self._session_id:
            lines.append(f"  - session id: {self._session_id}")
        lines.append(f"  - turns I've spoken this session: {turn_count}")
        lines.append(f"  - last spoke to Sir: {last_spoke}")
        lines.append(f"  - topic between us right now: {topic[:120]}")
        if commitments:
            lines.append(f"  - pending commitments I made to Sir:")
            for c in commitments:
                lines.append(f"    * {c}")
        lines.append("")
        lines.append("[MY OWN HEALTH RIGHT NOW]")
        kr_state = (
            f"google keys: {health['healthy_keys']} healthy / "
            f"{health['dead_keys']} dead"
        )
        lines.append(f"  - {kr_state}")
        lines.append(
            f"  - memory: {health['memory_chains']} chains in STM, "
            f"{health['active_concerns']} active concerns"
        )
        lines.append(f"  - my mood right now: {mood}")
        lines.append("")
        lines.append("[REFERENT MAP — for this conversation]")
        lines.append("  - when Sir says \"you\", \"your side\", \"this terminal\" → he means ME (this LLM)")
        lines.append("  - when Sir says \"I\", \"my\", \"me\" → he means HIMSELF")
        lines.append(
            "  - when I reference what \"I said earlier\" — that's me, the same continuous self, "
            "not a different model instance."
        )

        out = "\n".join(lines)
        if len(out) > max_chars:
            _suffix = "\n…[truncated]"
            out = out[:max_chars - len(_suffix)].rstrip() + _suffix
        return out


# ============================================================
# 单例
# ============================================================

_DEFAULT_ANCHOR: Optional[SelfAnchor] = None


def get_default_self_anchor(central_nerve=None) -> SelfAnchor:
    global _DEFAULT_ANCHOR
    if _DEFAULT_ANCHOR is None:
        _DEFAULT_ANCHOR = SelfAnchor(central_nerve=central_nerve)
    elif central_nerve is not None and _DEFAULT_ANCHOR.nerve is None:
        _DEFAULT_ANCHOR.nerve = central_nerve
    return _DEFAULT_ANCHOR


def reset_default_self_anchor_for_test() -> None:
    global _DEFAULT_ANCHOR
    _DEFAULT_ANCHOR = None
