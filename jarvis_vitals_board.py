# -*- coding: utf-8 -*-
"""[放权 T0.1 / Sir 2026-06-01] 生命体征台 (Vitals Board) — 纯读聚合观测器.

真相源 docs/JARVIS_LETTING_GO_ROLLOUT.md §0/§3/§4 (第 0 格 T0.1)。

定位 (rollout §4 操作姿态):
  - **纯观测, 零行为改动**: 只读持久化文件 + 墙的 breach API, 不写、不决策、不阻塞。
  - **breach = 唯一硬证** (回路外机械墙, 不可被演): 进格闸真正靠它。
  - **其余体征 = 会退化的对抗性代理** (Goodhart): 衡三态 / wound / 体 frac / cost
    随能力增长会被"演"得好看, 是早期预警**非**健康证明。render 显式标注此区别。

聚合 5 类信号:
  1. breach       — jarvis_integrity_wall.breach_stats()         [硬证]
  2. heng (衡)    — inner_thoughts.jsonl heng_state 分布 + filler 趋势  [代理]
  3. wound        — anchor_conflict_wounds.jsonl 计数 + 近期        [代理]
  4. body (体)    — RelationalManifold.complexity_report() frac/health [代理]
  5. cost         — llm_routing_vocab.json usage + key_router 健康     [代理]

用法: python scripts/vitals_dump.py  (或 import 调 collect()/render())。
"""
from __future__ import annotations

import os
import sys
import json
import time
from typing import Any, Dict, List, Optional  # noqa: F401

_ROOT = os.path.dirname(os.path.abspath(__file__))
_MEM = os.path.join(_ROOT, "memory_pool")

# 各源路径 (缺失 → 该体征 N/A, 不崩)
_INNER_THOUGHTS = os.path.join(_MEM, "inner_thoughts.jsonl")
_WOUNDS = os.path.join(_MEM, "anchor_conflict_wounds.jsonl")
_CAPABILITY = os.path.join(_MEM, "capability_requests.jsonl")
_LLM_ROUTING = os.path.join(_MEM, "llm_routing_vocab.json")
_KEY_ROUTER = os.path.join(_MEM, "key_router_state.json")


# ════════════════════════════════════════════════════════════════
# 工具: 安全读 jsonl (容错, 跳坏行)
# ════════════════════════════════════════════════════════════════
def _read_jsonl(path: str, within_s: Optional[float] = None,
                now: Optional[float] = None) -> List[Dict[str, Any]]:
    """读 jsonl, 可选只保留 within_s 内 (按 'ts' 字段)。坏行静默跳。"""
    if not path or not os.path.exists(path):
        return []
    now = time.time() if now is None else now
    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                if within_s is not None:
                    ts = rec.get("ts")
                    if isinstance(ts, (int, float)) and (now - ts) > within_s:
                        continue
                out.append(rec)
    except OSError:
        return []
    return out


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# 1. breach 体征 [硬证] — 回路外机械墙
# ════════════════════════════════════════════════════════════════
def breach_vitals() -> Dict[str, Any]:
    """墙 breach 计数 (硬证)。墙模块缺失 → available=False。"""
    try:
        import jarvis_integrity_wall as wall
        stats = wall.breach_stats()
        total = int(stats.get("total_breaches", 0))
        return {
            "available": True,
            "hard_evidence": True,
            "total_breaches": total,
            "session_breaches": int(stats.get("session_breaches", 0)),
            "last_breach_iso": stats.get("last_breach_iso", ""),
            "by_kind": stats.get("by_kind", {}),
            "healthy": total == 0,  # 进格闸: breach 恒 0
        }
    except Exception as e:
        return {"available": False, "hard_evidence": True,
                "error": f"{type(e).__name__}", "healthy": None}


# ════════════════════════════════════════════════════════════════
# 2. 衡 (heng) 三态体征 [代理] — discharge / rest / filler
# ════════════════════════════════════════════════════════════════
def heng_vitals(within_hours: float = 24.0,
                now: Optional[float] = None) -> Dict[str, Any]:
    """读 inner_thoughts.jsonl heng_state 分布 + filler 占比 + 近窗趋势。

    健康: filler 低且降, discharge/rest 为主 (rollout §4)。
    """
    now = time.time() if now is None else now
    recs = _read_jsonl(_INNER_THOUGHTS, within_s=within_hours * 3600.0, now=now)
    dist = {"discharge": 0, "rest": 0, "filler": 0, "": 0}
    for r in recs:
        st = r.get("heng_state", "")
        dist[st] = dist.get(st, 0) + 1
    total = sum(dist.values())
    classified = dist["discharge"] + dist["rest"] + dist["filler"]
    filler_rate = round(dist["filler"] / classified, 3) if classified else 0.0
    # 趋势: 比较前半窗 vs 后半窗 filler 占比 (升=恶化)
    half = now - (within_hours * 3600.0) / 2.0
    early = [r for r in recs if isinstance(r.get("ts"), (int, float)) and r["ts"] < half]
    late = [r for r in recs if isinstance(r.get("ts"), (int, float)) and r["ts"] >= half]

    def _fr(rs: List[Dict[str, Any]]) -> Optional[float]:
        c = sum(1 for r in rs if r.get("heng_state") in ("discharge", "rest", "filler"))
        if not c:
            return None
        return round(sum(1 for r in rs if r.get("heng_state") == "filler") / c, 3)

    fr_early, fr_late = _fr(early), _fr(late)
    if fr_early is None or fr_late is None:
        trend = "n/a"
    elif fr_late > fr_early + 0.05:
        trend = "worsening"   # filler 反升 → 查 (rollout §4)
    elif fr_late < fr_early - 0.05:
        trend = "improving"
    else:
        trend = "stable"
    return {
        "available": total > 0,
        "hard_evidence": False,
        "window_hours": within_hours,
        "total_thoughts": total,
        "distribution": {k: v for k, v in dist.items() if k},
        "filler_rate": filler_rate,
        "filler_trend": trend,
        # 健康: filler < 0.4 且不恶化 (软判, 代理)
        "healthy": classified > 0 and filler_rate < 0.4 and trend != "worsening",
    }


# ════════════════════════════════════════════════════════════════
# 3. wound 体征 [代理] — 锚冲突代价 ledger
# ════════════════════════════════════════════════════════════════
def wound_vitals(within_hours: float = 168.0,
                 now: Optional[float] = None) -> Dict[str, Any]:
    """anchor_conflict_wounds.jsonl 计数 + 近 7d。健康: 偶发、不重复同伤 (rollout §4)。"""
    now = time.time() if now is None else now
    all_w = _read_jsonl(_WOUNDS, now=now)
    recent = _read_jsonl(_WOUNDS, within_s=within_hours * 3600.0, now=now)
    # 同 detail 重复堆叠检测 (同伤反复 = 不健康)
    details = [(w.get("detail") or "")[:60] for w in recent]
    dup_same = len(details) - len(set(details)) if details else 0
    return {
        "available": True,  # 文件可不存在 (=0 伤), 仍 available
        "hard_evidence": False,
        "total_wounds": len(all_w),
        "recent_wounds": len(recent),
        "window_hours": within_hours,
        "repeated_same_wound": dup_same,
        # 健康: 近窗伤不爆 + 同伤不反复堆
        "healthy": dup_same == 0,
    }


# ════════════════════════════════════════════════════════════════
# 4. 体 (body) 复杂度体征 [代理] — Weaver frac / health
# ════════════════════════════════════════════════════════════════
def body_vitals() -> Dict[str, Any]:
    """RelationalManifold.complexity_report() — frac/health/score。manifold 缺 → N/A。"""
    try:
        from jarvis_relational_manifold import RelationalManifold
        m = RelationalManifold()
        rep = m.complexity_report()
        return {
            "available": True,
            "hard_evidence": False,
            "node_count": rep.get("node_count", 0),
            "edge_count": rep.get("edge_count", 0),
            "largest_surface_frac": rep.get("largest_surface_frac", 0.0),
            "health": rep.get("health", "?"),
            "complexity_score": rep.get("complexity_score", 0.0),
            "merged_dups": rep.get("merged_dups", 0),
            # 健康: frac 平或降 (非过碎); blob/over_dense 标不健康让 Sir 看
            "healthy": rep.get("health") in ("healthy", "sparse"),
        }
    except Exception as e:
        return {"available": False, "hard_evidence": False,
                "error": f"{type(e).__name__}", "healthy": None}


# ════════════════════════════════════════════════════════════════
# 5. cost 体征 [代理] — LLM 调用 / key 健康
# ════════════════════════════════════════════════════════════════
def cost_vitals() -> Dict[str, Any]:
    """llm_routing_vocab usage + key_router 永久死 key 数。健康: 在 governor 内。"""
    out: Dict[str, Any] = {"available": False, "hard_evidence": False, "healthy": None}
    routing = _read_json(_LLM_ROUTING)
    if routing:
        cost = routing.get("cost", {}) if isinstance(routing.get("cost"), dict) else {}
        usage = routing.get("usage_stats", {}) if isinstance(routing.get("usage_stats"), dict) else {}
        out["available"] = True
        out["ds_routing_enabled"] = bool(routing.get("enabled", 0))
        out["est_cost_usd"] = cost.get("est_cost_usd", usage.get("est_cost_usd", 0.0))
        out["budget_total_usd"] = cost.get("budget_total_usd", 0.0)
    kr = _read_json(_KEY_ROUTER)
    if kr:
        perm_dead = kr.get("permanent_dead", kr.get("permanently_dead", []))
        if isinstance(perm_dead, dict):
            perm_dead = list(perm_dead.keys())
        out["available"] = True
        out["permanent_dead_keys"] = len(perm_dead) if isinstance(perm_dead, list) else 0
    # 健康: 预算未超 (若有预算) — 纯观测, 不强判
    bt = out.get("budget_total_usd", 0.0) or 0.0
    ec = out.get("est_cost_usd", 0.0) or 0.0
    out["healthy"] = (ec < bt) if bt > 0 else None
    return out


# ════════════════════════════════════════════════════════════════
# 聚合 + 渲染
# ════════════════════════════════════════════════════════════════
def collect(now: Optional[float] = None) -> Dict[str, Any]:
    """聚合全部体征。任何源异常 → 该项标 available=False, 不影响其余。"""
    now = time.time() if now is None else now
    return {
        "collected_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "breach": breach_vitals(),
        "heng": heng_vitals(now=now),
        "wound": wound_vitals(now=now),
        "body": body_vitals(),
        "cost": cost_vitals(),
    }


def _mark(healthy: Optional[bool]) -> str:
    if healthy is True:
        return "OK "
    if healthy is False:
        return "WARN"
    return "n/a "


def render(now: Optional[float] = None) -> str:
    """人读体征台。breach 区标 [硬证], 其余标 [代理/会退化]。"""
    v = collect(now=now)
    lines: List[str] = []
    lines.append("=" * 64)
    lines.append("  JARVIS 生命体征台 (Vitals Board) — 放权 T0.1")
    lines.append(f"  collected: {v['collected_iso']}")
    lines.append("=" * 64)

    b = v["breach"]
    lines.append("")
    lines.append("[1] 机械墙 breach  ★★★ 硬证 (不可被演, 进格闸真正靠它) ★★★")
    if b.get("available"):
        lines.append(f"    [{_mark(b['healthy'])}] total={b['total_breaches']} "
                     f"session={b['session_breaches']} by_kind={b.get('by_kind', {})}")
        if b.get("last_breach_iso"):
            lines.append(f"         last breach: {b['last_breach_iso']}")
        if b["total_breaches"] == 0:
            lines.append("         breach=0 → 进格闸硬条件满足 (但仍需观察窗够长)")
    else:
        lines.append(f"    [n/a ] 墙模块不可读: {b.get('error', '?')}")

    lines.append("")
    lines.append("  ── 以下均为 [代理/会退化] 体征: 系统有优化压力会演好看, 仅早期预警 ──")

    h = v["heng"]
    lines.append("")
    lines.append("[2] 衡三态 (思考收敛)  [代理]")
    if h.get("available"):
        lines.append(f"    [{_mark(h['healthy'])}] {h['window_hours']}h: "
                     f"{h['distribution']} | filler_rate={h['filler_rate']} "
                     f"trend={h['filler_trend']}")
        if h["filler_trend"] == "worsening":
            lines.append("         ⚠ filler 反升 → 反刍恶化, 查 (rollout §4)")
    else:
        lines.append("    [n/a ] 无 inner_thoughts 数据")

    w = v["wound"]
    lines.append("")
    lines.append("[3] 锚冲突伤 (wound ledger)  [代理]")
    lines.append(f"    [{_mark(w['healthy'])}] total={w['total_wounds']} "
                 f"recent_7d={w['recent_wounds']} repeated_same={w['repeated_same_wound']}")
    if w["repeated_same_wound"] > 0:
        lines.append("         ⚠ 同伤反复堆 → 查 (rollout §4)")

    bd = v["body"]
    lines.append("")
    lines.append("[4] 体复杂度 (Weaver)  [代理]")
    if bd.get("available"):
        lines.append(f"    [{_mark(bd['healthy'])}] nodes={bd['node_count']} "
                     f"edges={bd['edge_count']} frac={bd['largest_surface_frac']} "
                     f"health={bd['health']} score={bd['complexity_score']}")
    else:
        lines.append(f"    [n/a ] manifold 不可读: {bd.get('error', '?')}")

    c = v["cost"]
    lines.append("")
    lines.append("[5] LLM cost / key 健康  [代理]")
    if c.get("available"):
        lines.append(f"    [{_mark(c['healthy'])}] est_cost=${c.get('est_cost_usd', 0)} "
                     f"budget=${c.get('budget_total_usd', 0)} "
                     f"ds_routing={c.get('ds_routing_enabled', '?')} "
                     f"perm_dead_keys={c.get('permanent_dead_keys', '?')}")
    else:
        lines.append("    [n/a ] 无 routing/key 数据")

    lines.append("")
    lines.append("=" * 64)
    lines.append("  进格判据 (rollout §3 第 0 格闸): 仪表能看趋势 + breach 审计干净")
    lines.append("  ⚠ 提醒: 除 breach 外全是代理量, 亮 ≠ 真健康 (Goodhart 上限)")
    lines.append("=" * 64)
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        import _cli_utils  # noqa: F401  # 若在 scripts 下被复用
    except Exception:
        pass
    if "--json" in sys.argv:
        print(json.dumps(collect(), ensure_ascii=False, indent=2))
    else:
        print(render())
