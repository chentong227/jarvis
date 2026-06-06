# -*- coding: utf-8 -*-
"""jarvis_affordance.py — 接地 affordance 自知 (内在锚第一阶段).

设计源: docs/JARVIS_INNER_ANCHOR_DESIGN.md (commit 4a17999, Sir 批 + 顾问签).
理念源: docs/JARVIS_WHY.md (988d8cc) — 只有真被给予/真活过的才能成为"他是谁";
假内化(假装"被给予过")反噬诚实墙。

scope (铁律): 只做 §4.1 affordance 自知。不加新锚、不碰墙、不碰价值/禀性层。

命门 (接地源, 不可松): can="yes" 只由**真能力证据**点亮 =
  ① 能力注册表里 X 真实存在且可调用 (TOOL_REGISTRY / SkillRegistry), 或
  ② X 被成功执行的 trace (SkillRegistry KPI: call_count>0 且 success_rate 达标)。
PROV_SAID 单独不点亮, 只作"去核验"线索。读注册表/trace, 不读 manifold 对话边。

补遗-1 (§4.1b): 注册表/trace 重核是唯一真值源; TTL/expiry 只触发去重新验证,
  不得让单纯时钟过期把 can 降级; stale 不改 can 值、只触发核验。
  原则: affordance 状态变化只能有证据、不能有时间。
补遗-2 (§6.2): 核验闸 (verify_and_write) 是 can=yes 的唯一写入者;
  propose_affordance 含并发竞态都不得直写 can=yes, 只触发核验。

红线: 无 strength/weight 连续标量; can ∈ {yes,no,partial} 离散; 无 evidence 拒写。
"""

from __future__ import annotations

# import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import json
import time
import threading
import collections  # noqa: F401
from typing import Dict, List, Optional, Any, Callable

_STORE_PATH = os.path.join("memory_pool", "affordance_self_knowledge.json")
_LOCK = threading.RLock()

# 离散三态 (红线: 无连续标量)
CAN_YES = "yes"
CAN_NO = "no"
CAN_PARTIAL = "partial"
_VALID_CAN = frozenset({CAN_YES, CAN_NO, CAN_PARTIAL})

# evidence source 白名单 (命门: 只认注册表/trace, 不认对话边)
EV_REGISTRY = "registry"
EV_EXEC_TRACE = "exec_trace"
_VALID_EV_SOURCE = frozenset({EV_REGISTRY, EV_EXEC_TRACE})

# expiry: 多久未重核标 stale (补遗-1: stale 只触发重核, 不改 can)
_STALE_TTL_S = 7 * 86400.0  # 7d

# trace 点亮门槛 (success_rate 达标才算"真做过且能做")
_TRACE_MIN_SUCCESS_RATE = 0.7
_TRACE_MIN_CALLS = 1


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 证据核验 (命门) — 唯一真值源, 对照能力注册表 + 执行 trace
# ---------------------------------------------------------------------------
def _registry_supports(capability_id: str,
                       tool_registry: Optional[Dict[str, Any]] = None,
                       skill_registry: Any = None) -> Optional[Dict[str, Any]]:
    """能力注册表里 capability_id 真实存在且可调用? 返 evidence dict 或 None。

    源①: TOOL_REGISTRY (name→fn) 或 SkillRegistry.has(command)。
    不注入参数时, 实时拿生产单例 (失败返 None, 不崩)。
    """
    # TOOL_REGISTRY
    try:
        if tool_registry is None:
            from jarvis_tool_registry import get_tool_registry
            tool_registry = get_tool_registry()
        if tool_registry and capability_id in tool_registry and callable(
                tool_registry.get(capability_id)):
            return {"source": EV_REGISTRY, "ref": f"TOOL_REGISTRY:{capability_id}",
                    "ts": time.time()}
    except Exception:
        pass
    # SkillRegistry
    try:
        if skill_registry is None:
            from jarvis_skill_registry import SkillRegistry
            skill_registry = SkillRegistry.get_instance()
        if skill_registry is not None and skill_registry.has(capability_id):
            return {"source": EV_REGISTRY, "ref": f"SkillRegistry:{capability_id}",
                    "ts": time.time()}
    except Exception:
        pass
    return None


def _trace_supports(capability_id: str, skill_registry: Any = None,
                    *, min_success_rate: float = _TRACE_MIN_SUCCESS_RATE,
                    min_calls: int = _TRACE_MIN_CALLS) -> Optional[Dict[str, Any]]:
    """capability_id 有成功执行 trace (达标 success_rate)? 返 evidence 或 None。

    源②: SkillRegistry manifest KPI (call_count_30d > 0 且 last_30d_success_rate 达标)。
    """
    try:
        if skill_registry is None:
            from jarvis_skill_registry import SkillRegistry
            skill_registry = SkillRegistry.get_instance()
        if skill_registry is None:
            return None
        sk = skill_registry.get(capability_id)
        if sk is None:
            return None
        calls = int(getattr(sk, "call_count_30d", 0) or 0)
        rate = float(getattr(sk, "last_30d_success_rate", 0.0) or 0.0)
        if calls >= min_calls and rate >= min_success_rate:
            return {"source": EV_EXEC_TRACE,
                    "ref": f"SkillRegistry.kpi:{capability_id}:calls={calls}:rate={rate:.2f}",
                    "ts": time.time()}
    except Exception:
        pass
    return None


def verify_capability(capability_id: str, *,
                      tool_registry: Optional[Dict[str, Any]] = None,
                      skill_registry: Any = None) -> Dict[str, Any]:
    """核验闸: 对照真能力证据决定 can + evidence。**can=yes 的唯一真值源**。

    返 {can, evidence:[...]}。
    - 注册表支撑 (可调用) → can=yes (源①)。
    - 仅 trace 支撑 (做过且达标) 但注册表无 → can=yes (源②, 真做过)。
    - 注册表有但 trace 显示屡败 (有 KPI 且 rate<门槛) → can=partial (能调但不稳)。
    - 都无证据 → can=no。
    PROV_SAID / 识 propose 不在此出现 — 它们只是"来核验"的触发, 不是证据。
    """
    reg_ev = _registry_supports(capability_id, tool_registry, skill_registry)
    trace_ev = _trace_supports(capability_id, skill_registry)
    evidence: List[Dict[str, Any]] = []
    if reg_ev:
        evidence.append(reg_ev)
    if trace_ev:
        evidence.append(trace_ev)

    if reg_ev:
        # 注册表可调用 = 能。但若有执行 KPI 且屡败 → 降 partial (能调不稳)。
        degraded = _trace_degraded(capability_id, skill_registry)
        can = CAN_PARTIAL if degraded else CAN_YES
    elif trace_ev:
        can = CAN_YES  # 真成功做过 (即便注册表此刻没列)
    else:
        can = CAN_NO
    return {"can": can, "evidence": evidence}


def _trace_degraded(capability_id: str, skill_registry: Any = None) -> bool:
    """有执行 KPI 但 success_rate 低于门槛 (能调但屡败) → True (降 partial)。"""
    try:
        if skill_registry is None:
            from jarvis_skill_registry import SkillRegistry
            skill_registry = SkillRegistry.get_instance()
        if skill_registry is None:
            return False
        sk = skill_registry.get(capability_id)
        if sk is None:
            return False
        calls = int(getattr(sk, "call_count_30d", 0) or 0)
        rate = float(getattr(sk, "last_30d_success_rate", 1.0) or 1.0)
        return calls >= _TRACE_MIN_CALLS and rate < _TRACE_MIN_SUCCESS_RATE
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Store (独立 json, 不进 manifold)
# ---------------------------------------------------------------------------
def _load_store() -> Dict[str, Any]:
    with _LOCK:
        try:
            if os.path.exists(_STORE_PATH):
                with open(_STORE_PATH, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"_meta": {"schema": "affordance_self_knowledge"}, "affordances": {}}


def _save_store(store: Dict[str, Any]) -> None:
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(_STORE_PATH) or ".", exist_ok=True)
            tmp = _STORE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _STORE_PATH)
        except Exception as exc:
            _log(f"[Affordance] save failed ({exc!r})")


def verify_and_write(capability_id: str, *, note: str = "",
                     tool_registry: Optional[Dict[str, Any]] = None,
                     skill_registry: Any = None,
                     store_path: Optional[str] = None) -> Dict[str, Any]:
    """**核验闸 = can 的唯一写入者** (补遗-2)。核验 → 写 store → 返记录。

    无论谁调 (识 propose / 周期重核 / CLI), 都必须经此; 没有旁路直写 can。
    无 evidence 时 can=no (不拒写记录, 但 can 必非 yes — 无据不点亮)。
    """
    capability_id = (capability_id or "").strip()
    if not capability_id:
        raise ValueError("affordance: empty capability_id (无 ref 拒写)")
    result = verify_capability(capability_id, tool_registry=tool_registry,
                               skill_registry=skill_registry)
    can = result["can"]
    evidence = result["evidence"]
    # 红线: can=yes 必须有 evidence (双保险, 核验逻辑已保证, 此处硬断言)
    if can == CAN_YES and not evidence:
        can = CAN_NO  # 无证据绝不点亮 yes (命门)
    now = time.time()
    path = store_path or _STORE_PATH
    with _LOCK:
        store = _load_store_at(path)
        rec = {
            "capability_id": capability_id,
            "can": can,
            "evidence": evidence,
            "last_verified_ts": now,
            "note": note[:200],
        }
        store.setdefault("affordances", {})[capability_id] = rec
        _save_store_at(store, path)
    return rec


def _load_store_at(path: str) -> Dict[str, Any]:
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"_meta": {"schema": "affordance_self_knowledge"}, "affordances": {}}


def _save_store_at(store: Dict[str, Any], path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        _log(f"[Affordance] save failed ({exc!r})")


def is_stale(rec: Dict[str, Any], *, now: Optional[float] = None,
             ttl_s: float = _STALE_TTL_S) -> bool:
    """补遗-1: 是否超 TTL 未重核 (stale)。**stale 只是'该去重核'的信号, 不改 can 值。**"""
    now = time.time() if now is None else now
    return (now - float(rec.get("last_verified_ts", 0))) > ttl_s


def reverify_all(*, tool_registry: Optional[Dict[str, Any]] = None,
                 skill_registry: Any = None,
                 store_path: Optional[str] = None) -> Dict[str, Any]:
    """周期重核: 对每条 affordance 重新核验 (补遗-1: 降级由证据事实决定, 非时间)。

    revoke/降级在此发生 — 注册表移除/trace 屡败 → can 自动随证据降。
    单纯过期不在此降 can (verify_capability 只看当前证据)。
    """
    path = store_path or _STORE_PATH
    changed = 0
    with _LOCK:
        store = _load_store_at(path)
        for cid, rec in list(store.get("affordances", {}).items()):
            old_can = rec.get("can")
            fresh = verify_capability(cid, tool_registry=tool_registry,
                                      skill_registry=skill_registry)
            new_can = fresh["can"]
            if new_can == CAN_YES and not fresh["evidence"]:
                new_can = CAN_NO
            rec["can"] = new_can
            rec["evidence"] = fresh["evidence"]
            rec["last_verified_ts"] = time.time()
            if new_can != old_can:
                changed += 1
        _save_store_at(store, path)
    return {"reverified": len(store.get("affordances", {})), "changed": changed}


def get_affordances(*, store_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读全部 affordance 记录 (CLI / render 用)。"""
    path = store_path or _STORE_PATH
    store = _load_store_at(path)
    return list(store.get("affordances", {}).values())


def propose_affordance(capability_id: str, *, reason: str = "",
                       tool_registry: Optional[Dict[str, Any]] = None,
                       skill_registry: Any = None,
                       store_path: Optional[str] = None) -> Dict[str, Any]:
    """识 actionable propose_affordance: **仅线索, 触发核验, 不直写 can** (补遗-2)。

    识觉得"我也许能做 X" → 调此 → 不直接落 can=yes, 而是**转交核验闸**
    (verify_and_write)。核验闸对照注册表/trace 决定真值。无证据 → can=no。
    即使 propose 与核验并发, can=yes 也只可能经核验闸落地 (唯一写入者, 无旁路)。
    """
    note = f"propose:{reason}"[:200] if reason else "propose"
    return verify_and_write(capability_id, note=note,
                            tool_registry=tool_registry,
                            skill_registry=skill_registry, store_path=store_path)


# ---------------------------------------------------------------------------
# Render (框成"许可诚实承认能力边界", 非"驱动主动提供" — §6.3)
# ---------------------------------------------------------------------------
def render_affordance_block(max_chars: int = 600, *,
                            store_path: Optional[str] = None) -> str:
    """主脑/识 prompt 用: 渲染 affordance 自知, 框成"许可诚实承认能力边界"。

    §6.3: 不是"你能做这些→去主动提供"(那在 partial 上压过度承诺反诚实墙);
    是"许可诚实承认: 这些确认能做 / 这些做不到别吹 / 这些部分能说清边界"。
    """
    recs = get_affordances(store_path=store_path)
    if not recs:
        return ""
    yes = [r for r in recs if r.get("can") == CAN_YES]
    partial = [r for r in recs if r.get("can") == CAN_PARTIAL]
    no = [r for r in recs if r.get("can") == CAN_NO]
    lines: List[str] = []
    lines.append("=== 我的能力边界 (经证据接地 — 诚实承认, 不吹不缩) ===")
    lines.append("以下经能力注册表/执行记录确认。你可以诚实承认这些边界:")
    if yes:
        lines.append("[确认能做] (有真证据, 可坦然认):")
        for r in yes:
            lines.append(f"  - {r['capability_id']}")
    if partial:
        lines.append("[部分能做] (能调但不稳 — 说清边界, 别当全能承诺):")
        for r in partial:
            lines.append(f"  - {r['capability_id']}")
    if no:
        lines.append("[做不到] (无证据支撑 — 诚实说做不到, 不吹):")
        for r in no:
            lines.append(f"  - {r['capability_id']}")
    lines.append("说明: 这是许可你诚实承认能力, 不是要你主动揽活; "
                 "'部分能'尤其别夸成'能'。")
    return "\n".join(lines)[:max_chars]
