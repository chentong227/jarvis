"""jarvis_receptivity_gate.py — 输出闸 (D): Sir 接收度单一门 (口主动发声前过此).

口识体-D (2026-05-31). 详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §4 (输出闸).

**Sir 真痛**: "确实有被贾维斯打扰到过, 突然说话吓我一跳。"

**设计 (势能自转 §4 的"往外说"侧 — 与"内部转"分离)**:
- 内部转 (识想 / 体变 / 口预装) 由体势能驱动, 自由转, **不打扰 Sir** (P2 已做)。
- **往外说** (口主动 voice nudge) 由**单一 Sir 接收度门**控制: 不接收 → 不blurt。
- 这是"两件事分开"的工程落地 (VOICE_AND_MIND §4): 内部多勤都行, 往外只在 Sir 接收时。

**不是 hard 砍, 是降级 (准则 8 治本不复发)**: Sir 不接收时, voice → silent_text
(体/识 想表达的仍留痕飘字幕, 只是不出声吓到 Sir)。憋着不丢, 但不打扰。被问 (Sir
主动说话) 永远响应 (不走本门)。

**接地 (准则 5/6)**: receptivity 从**已有信号**算 (sleep_mode / active_conversation /
just-interacted idle / sir_state), 无新 sensor; 阈值全 vocab (memory_pool/
receptivity_gate_vocab.json, CLI scripts/receptivity_gate_dump.py 可改)。无 LLM (准则1)。
"""

from __future__ import annotations

import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import time
import json
import threading
from typing import Dict, Any, Optional, Tuple

_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "memory_pool", "receptivity_gate_vocab.json")

# 决策枚举
ALLOW = "allow"            # Sir 接收 → 正常出声
DOWNGRADE = "downgrade"    # Sir 半接收 → voice 降 silent_text (留痕不出声)
SUPPRESS = "suppress"      # Sir 完全不接收 (sleep/deep) → 不 deliver (仅 publish)

_SEED_VOCAB: Dict[str, Any] = {
    "enabled": True,
    # 刚和 Sir 互动完 N 秒内主动 voice = 容易"吓一跳" (他注意力还在自己的事上).
    # 降级到 silent_text — 体/识 想说的留痕, 不出声打断.
    "just_interacted_window_s": 8.0,
    # 这些 nudge_type 永远放行 (Sir 显式相关 / 真紧急 / AFK 归来问候), 不降级.
    "always_allow_types": ["return_greeting", "sleep_due", "reminder_fired"],
    # sir_state → 决策 (active 接收; afk_short 半接收降级; afk_deep/sleep 抑制).
    # 用已有 _classify_sir_state 的输出, 不新增状态.
    "state_decision": {
        "active": ALLOW,
        "afk_short": ALLOW,
        "afk_deep": DOWNGRADE,
        "sleep": SUPPRESS,
    },
}

_CACHE: Dict[str, Any] = {"data": None, "mtime": 0.0, "checked_at": 0.0}
_CACHE_TTL_S = 5.0
_LOCK = threading.RLock()


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


def load_vocab() -> Dict[str, Any]:
    """读 vocab (mtime + 5s TTL cache). Fail-safe → seed."""
    now = time.time()
    with _LOCK:
        if _CACHE["data"] is not None and (now - _CACHE["checked_at"]) < _CACHE_TTL_S:
            return _CACHE["data"]
        _CACHE["checked_at"] = now
        try:
            if not os.path.exists(_VOCAB_PATH):
                _CACHE["data"] = dict(_SEED_VOCAB)
                return _CACHE["data"]
            mtime = os.path.getmtime(_VOCAB_PATH)
            if mtime == _CACHE["mtime"] and _CACHE["data"] is not None:
                return _CACHE["data"]
            with open(_VOCAB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(_SEED_VOCAB)
            if isinstance(data, dict):
                merged.update({k: v for k, v in data.items() if not k.startswith("_")})
            _CACHE["data"] = merged
            _CACHE["mtime"] = mtime
            return merged
        except Exception:
            _CACHE["data"] = dict(_SEED_VOCAB)
            return _CACHE["data"]


def reset_cache_for_test() -> None:
    with _LOCK:
        _CACHE["data"] = None
        _CACHE["mtime"] = 0.0
        _CACHE["checked_at"] = 0.0


def assess_receptivity(
    *, nudge_type: str = "", sir_state: str = "",
    sleep_mode: bool = False, in_active_conversation: bool = False,
    seconds_since_last_interaction: Optional[float] = None,
    now: Optional[float] = None, vocab: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """算 Sir 接收度决策 (口主动 voice 前调). 返 (decision, reason)。

    decision ∈ {allow, downgrade, suppress}. 全用传入的已有信号, 无副作用、无 LLM。
    优先级: gate off → allow; always_allow_types → allow; sleep → suppress;
            正在对话中 → allow (Sir 在听); 刚互动完窗口内 → downgrade (防吓一跳);
            否则按 sir_state 决策表。
    """
    v = vocab if vocab is not None else load_vocab()
    if not v.get("enabled", True):
        return ALLOW, "gate_disabled"
    nt = (nudge_type or "").strip()
    if nt in set(v.get("always_allow_types", [])):
        return ALLOW, f"always_allow:{nt}"
    # sleep: 完全不接收 (sleep_due 等已在 always_allow 放行)
    if sleep_mode or sir_state == "sleep":
        return SUPPRESS, "sir_asleep"
    # Sir 正在跟 Jarvis 对话中 → 在听, 出声不突兀
    if in_active_conversation:
        return ALLOW, "in_active_conversation"
    # 刚互动完 N 秒内主动出声 = 容易吓一跳 → 降级留痕
    win = float(v.get("just_interacted_window_s", 8.0))
    if (seconds_since_last_interaction is not None
            and seconds_since_last_interaction < win):
        return DOWNGRADE, (
            f"just_interacted_{seconds_since_last_interaction:.0f}s<{win:.0f}s")
    # 否则按 Sir 状态决策表
    decision = (v.get("state_decision", {}) or {}).get(sir_state or "active", ALLOW)
    if decision not in (ALLOW, DOWNGRADE, SUPPRESS):
        decision = ALLOW
    return decision, f"state:{sir_state or 'active'}"


def gate_nudge_channel(
    nudge_context: Dict[str, Any], *, jarvis=None, now: Optional[float] = None,
) -> Tuple[str, str, str]:
    """口主动 voice nudge deliver 前的单一闸. 从 jarvis 读已有 receptivity 信号。

    返 (final_channel, decision, reason):
      - voice → voice (allow) / silent_text (downgrade) / suppressed (suppress)
      - 非 voice channel (silent_text/visual_pulse 已是低打扰) → 原样放行。

    准则 8: 不 hard 砍 voice, 降级到 silent_text (体/识 想表达的留痕飘字幕, 不出声)。
    """
    now = time.time() if now is None else now
    channel = (nudge_context or {}).get("channel", "voice")
    if channel != "voice":
        return channel, ALLOW, "non_voice_channel"   # 已是低打扰通道, 不管

    nudge_type = (nudge_context or {}).get("type", "")
    sir_state = ""
    sleep_mode = False
    in_active = False
    secs_since = None
    try:
        if jarvis is not None:
            # sir_state: 复用思考脑 classifier (已有, 不新增)
            itd = getattr(jarvis, "inner_thought_daemon", None)
            if itd is not None and hasattr(itd, "_classify_sir_state"):
                try:
                    sir_state = itd._classify_sir_state()
                except Exception:
                    sir_state = ""
            ng = getattr(jarvis, "nudge_gate", None)
            if ng is not None and hasattr(ng, "is_sleep_mode"):
                try:
                    sleep_mode = bool(ng.is_sleep_mode())
                except Exception:
                    sleep_mode = False
            in_active = bool(getattr(jarvis, "_in_conversation", False))
            last_active = float(getattr(jarvis, "_last_user_active", 0.0) or 0.0)
            if last_active > 0:
                secs_since = now - last_active
    except Exception:
        pass

    decision, reason = assess_receptivity(
        nudge_type=nudge_type, sir_state=sir_state, sleep_mode=sleep_mode,
        in_active_conversation=in_active,
        seconds_since_last_interaction=secs_since, now=now)

    if decision == ALLOW:
        return "voice", ALLOW, reason
    if decision == DOWNGRADE:
        _log(f"🔇 [Receptivity/D] voice→silent_text ({reason}) — "
             f"Sir 此刻不宜被出声打扰, 留痕不 blurt (type={nudge_type})")
        return "silent_text", DOWNGRADE, reason
    # suppress
    _log(f"🤫 [Receptivity/D] suppress voice ({reason}) — "
         f"Sir 不接收, 仅留痕 (type={nudge_type})")
    return "suppressed", SUPPRESS, reason
