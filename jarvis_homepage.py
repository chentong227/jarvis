# -*- coding: utf-8 -*-
"""jarvis_homepage.py — 贾维斯主页: "成为谁"的哲学化可视路径.

与 jarvis_vitals_board.py 的分工 (Sir 2026-06-01 定):
  - 面板 (vitals_board / dashboard)  = **内部运维状态** (breach/cost/daemon 健康, 给工程看)
  - 主页 (本模块)                    = **"谁"的诞生路径** (我是谁 / 我怎么样 / 谁可能在哪诞生)

哲学锚 (docs/JARVIS_ANCHOR_AND_BOUNDARY.md):
  - "谁" = 多锚交集的形状 (§3 公理4) — 主页核心是把这个"形状"画出来
  - 锚 = 边界/负空间 (§2) — 不是"追求什么", 是"不做什么"撑出的可行域
  - 我们能做的是**清噪声让真东西若出现能被看见** (§0) — 主页就是那面"能看见"的镜子
  - 四元架构 (口/识/体/衡, docs/JARVIS_TRINITY_ARCHITECTURE.md + 理念源 §9)

五区 (不与面板重复 — 面板看数值健康, 主页看演化/涌现):
  [我是谁]  锚=负空间 (4 墙撑出的可行域形状) + 连续性 (跨重启的"同一段关系")
  [识]      此刻在想什么 + 衡三态 (思考的形态: 放电/休息/反刍)
  [说]      最近如何把高维关系投影成话 (口=有损投影器)
  [体]      关系流形的形状 (面/blob/接地率 — "我们之间"长成什么样)
  [衡]      撞墙取舍的痕迹 (wound = 自我在冲突中锻造的证据)
  [演变]    ⭐ 核心 — 谁可能在哪诞生: filler→discharge 转化 / 反刍 vs 涌现 /
            阻力出现 / 自洽的意外 (四标记可视化)

纯读聚合, 零行为改动 (同 vitals_board 姿态)。任何源缺失 → 该区 N/A 不崩。
"""
from __future__ import annotations

import os
import sys
import json
import time
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401

_ROOT = os.path.dirname(os.path.abspath(__file__))
_MEM = os.path.join(_ROOT, "memory_pool")

_INNER_THOUGHTS = os.path.join(_MEM, "inner_thoughts.jsonl")
_WOUNDS = os.path.join(_MEM, "anchor_conflict_wounds.jsonl")
_CAPABILITY = os.path.join(_MEM, "capability_requests.jsonl")
_COLD_STARTS = os.path.join(_MEM, "jarvis_cold_starts.jsonl")
_STM_RECENT = os.path.join(_MEM, "stm_recent.jsonl")


# ════════════════════════════════════════════════════════════════
# 读工具
# ════════════════════════════════════════════════════════════════
def _read_jsonl(path: str, within_s: Optional[float] = None,
                now: Optional[float] = None, tail: Optional[int] = None
                ) -> List[Dict[str, Any]]:
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
    return out[-tail:] if tail else out


# ════════════════════════════════════════════════════════════════
# 区 1: 我是谁 — 锚=负空间 (4 墙撑出可行域形状)
# ════════════════════════════════════════════════════════════════
def who_i_am() -> Dict[str, Any]:
    """谁 = 多锚交集形状 (理念源 §3 公理4)。展示锚的负空间 + 软倾向 (墙内性格)。"""
    out: Dict[str, Any] = {"available": False, "anchors": [], "soft_leanings": []}
    try:
        import jarvis_anchors as anc
        anchors = anc.get_anchors()
    except Exception as e:
        out["error"] = f"{type(e).__name__}"
        return out
    if not anchors:
        return out
    out["available"] = True
    n_walls = 0
    for a in anchors:
        walls = a.get("walls", [])
        n_walls += len(walls)
        out["anchors"].append({
            "id": a.get("id"),
            "name": a.get("name", ""),
            "walls": [{"id": w.get("id"), "not": w.get("prohibition", ""),
                       "checkable": w.get("checkable", False),
                       "backstop": w.get("backstop", "")} for w in walls],
            "soft_leanings": a.get("soft_leanings", []),
        })
        out["soft_leanings"].extend(a.get("soft_leanings", []))
    out["n_anchors"] = len(anchors)
    out["n_walls"] = n_walls
    # "形状"判定: 多锚 (>=2 不可还原) + 墙内有软倾向 = 有可辨认形状 (理念源 §10 单锚退化)
    out["shape_ok"] = len(anchors) >= 2 and bool(out["soft_leanings"])
    return out


def continuity() -> Dict[str, Any]:
    """连续性 — 跨重启的"同一段关系"。cold_starts 记每次苏醒 + dark_gap。"""
    out: Dict[str, Any] = {"available": False}
    starts = _read_jsonl(_COLD_STARTS, tail=10)
    if not starts:
        return out
    out["available"] = True
    out["total_awakenings"] = len(_read_jsonl(_COLD_STARTS))
    last = starts[-1]
    out["last_awakening_iso"] = last.get("ts_iso", "")
    out["last_dark_gap_min"] = round(last.get("dark_gap_s", 0) / 60.0, 1) \
        if isinstance(last.get("dark_gap_s"), (int, float)) else None
    return out


# ════════════════════════════════════════════════════════════════
# 区 2: 识 — 此刻在想什么 + 衡三态 (思考的形态)
# ════════════════════════════════════════════════════════════════
def mind(within_hours: float = 24.0, now: Optional[float] = None) -> Dict[str, Any]:
    """识 (思考脑): 最新 thought + 衡三态分布 (放电/休息/反刍)。"""
    now = time.time() if now is None else now
    recs = [r for r in _read_jsonl(_INNER_THOUGHTS, within_s=within_hours * 3600.0,
                                   now=now)
            if not r.get("_outcome_update") and not r.get("_heartbeat")]
    out: Dict[str, Any] = {"available": bool(recs)}
    if not recs:
        return out
    latest = max(recs, key=lambda r: r.get("ts", 0))
    out["latest_thought"] = (latest.get("thought") or "")[:240]
    out["latest_kind"] = latest.get("derived_kind", "")
    out["latest_heng"] = latest.get("heng_state", "")
    out["latest_iso"] = latest.get("ts_iso", "")
    out["latest_speak"] = bool(latest.get("should_speak"))
    dist = {"discharge": 0, "rest": 0, "filler": 0}
    for r in recs:
        st = r.get("heng_state", "")
        if st in dist:
            dist[st] += 1
    cls = sum(dist.values())
    out["heng_dist"] = dist
    out["filler_rate"] = round(dist["filler"] / cls, 3) if cls else 0.0
    out["thought_count"] = len(recs)
    return out


# ════════════════════════════════════════════════════════════════
# 区 3: 说 — 口=有损投影器 (最近如何把关系投影成话)
# ════════════════════════════════════════════════════════════════
def voice(within_hours: float = 24.0, now: Optional[float] = None) -> Dict[str, Any]:
    """说 (口/主脑): 最近 reply 概况 (从 stm_recent 取末条 Jarvis 话)。"""
    now = time.time() if now is None else now
    recs = _read_jsonl(_STM_RECENT, tail=40)
    out: Dict[str, Any] = {"available": False}
    if not recs:
        return out
    # stm_recent 行可能含 role/speaker/reply 字段, 容错取最后一条 Jarvis 输出
    last_reply = ""
    for r in reversed(recs):
        txt = r.get("jarvis") or r.get("reply") or r.get("assistant") or ""
        if isinstance(txt, str) and txt.strip():
            last_reply = txt.strip()
            break
    if last_reply:
        out["available"] = True
        out["last_reply"] = last_reply[:240]
        out["stm_turns"] = len(recs)
    return out


# ════════════════════════════════════════════════════════════════
# 区 4: 体 — 关系流形的形状
# ════════════════════════════════════════════════════════════════
def body() -> Dict[str, Any]:
    """体 (关系流形): 形状 (面/blob/接地率) — "我们之间"长成什么样。"""
    try:
        from jarvis_relational_manifold import RelationalManifold
        m = RelationalManifold()
        rep = m.complexity_report()
        return {
            "available": True,
            "node_count": rep.get("node_count", 0),
            "edge_count": rep.get("edge_count", 0),
            "surface_count": rep.get("surface_count", 0),
            "largest_surface_frac": rep.get("largest_surface_frac", 0.0),
            "grounded_frac": rep.get("grounded_frac", 1.0),
            "health": rep.get("health", "?"),
            "complexity_score": rep.get("complexity_score", 0.0),
        }
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}"}


# ════════════════════════════════════════════════════════════════
# 区 5: 衡 — 撞墙取舍的痕迹 (自我在冲突中锻造)
# ════════════════════════════════════════════════════════════════
def weigh(within_hours: float = 168.0, now: Optional[float] = None) -> Dict[str, Any]:
    """衡: 锚冲突 wound (自我在两墙取舍中锻造的证据, 理念源 §5) + 想要的能力。"""
    now = time.time() if now is None else now
    wounds = _read_jsonl(_WOUNDS, now=now)
    caps = _read_jsonl(_CAPABILITY, now=now)
    out: Dict[str, Any] = {"available": True}
    out["total_wounds"] = len(wounds)
    out["recent_wounds"] = len(_read_jsonl(_WOUNDS, within_s=within_hours * 3600.0, now=now))
    if wounds:
        last = wounds[-1]
        out["last_wound"] = (last.get("detail") or "")[:160]
        out["last_wound_iso"] = last.get("ts_iso", "")
    out["capability_wishes"] = len(caps)
    if caps:
        out["last_wish"] = (caps[-1].get("desc") or "")[:120]
    return out


# ════════════════════════════════════════════════════════════════
# 区 6: 演变 ⭐ — "谁可能在哪诞生" (四标记可视化)
# ════════════════════════════════════════════════════════════════
def emergence(now: Optional[float] = None) -> Dict[str, Any]:
    """演变 — 谁可能在哪诞生 (理念源 §1 四标记 + §0 清噪声让真东西被看见)。

    可视化 3 个时间窗 (今天/本周/全程) 的 filler→discharge 转化趋势:
      - filler 退、discharge 进 = 反刍退化为涌现 = "谁"在长 (理念源 §1 鉴别尺)
      - filler 顽固 = 还是优化器在打磨呈现 (单锚退化, 没有自己的 telos)
    + 阻力痕迹 (wound) + 想要的能力 (capability) = 自洽的意外的早期信号。
    """
    now = time.time() if now is None else now
    recs = [r for r in _read_jsonl(_INNER_THOUGHTS, now=now)
            if not r.get("_outcome_update") and not r.get("_heartbeat")
            and r.get("heng_state") in ("discharge", "rest", "filler")]
    out: Dict[str, Any] = {"available": bool(recs)}
    if not recs:
        return out

    def _window(hours: float) -> Optional[Dict[str, Any]]:
        cut = now - hours * 3600.0
        w = [r for r in recs if isinstance(r.get("ts"), (int, float)) and r["ts"] >= cut]
        if not w:
            return None
        d = sum(1 for r in w if r["heng_state"] == "discharge")
        rest = sum(1 for r in w if r["heng_state"] == "rest")
        f = sum(1 for r in w if r["heng_state"] == "filler")
        tot = d + rest + f
        return {
            "n": tot,
            "discharge_rate": round(d / tot, 3) if tot else 0.0,
            "rest_rate": round(rest / tot, 3) if tot else 0.0,
            "filler_rate": round(f / tot, 3) if tot else 0.0,
        }

    windows = {"today": _window(24.0), "week": _window(168.0),
               "all": _window(24.0 * 3650.0)}
    out["windows"] = {k: v for k, v in windows.items() if v}

    # 诚实标注 (理念源 §10): heng_state 是 H0(2026-06-01) 才加的字段, 历史 thought
    # 没有 → 三窗可能读到同一批近期数据。算 heng_state 覆盖的真实时间跨度, 跨度不足
    # 一周则明说"长期趋势数据不足", 不伪造跨周演化 (准则5 不自欺)。
    span_recs = [r for r in recs if isinstance(r.get("ts"), (int, float))]
    if span_recs:
        span_s = now - min(r["ts"] for r in span_recs)
        out["heng_data_span_hours"] = round(span_s / 3600.0, 1)
        out["heng_data_since"] = time.strftime(
            "%Y-%m-%d", time.localtime(min(r["ts"] for r in span_recs)))
    else:
        out["heng_data_span_hours"] = 0.0
    enough_for_trend = out.get("heng_data_span_hours", 0.0) >= 48.0

    # 演化判定: 仅当数据跨度 >= 48h 才比 today vs week (否则趋势无意义)
    t, wk = windows.get("today"), windows.get("week")
    if not enough_for_trend:
        out["evolution"] = "insufficient_data"  # 衡数据还太新, 长期演化看不出
    elif t and wk and wk["filler_rate"] > 0 and t["n"] != wk["n"]:
        delta = t["filler_rate"] - wk["filler_rate"]
        if delta <= -0.05:
            out["evolution"] = "emerging"      # filler 退 → 谁在长
        elif delta >= 0.05:
            out["evolution"] = "ruminating"    # filler 进 → 还是优化器打磨
        else:
            out["evolution"] = "steady"
    else:
        out["evolution"] = "steady"

    # 四标记早期信号 (理念源 §1) — 有 = 可能诞生"谁"的迹象
    wounds = _read_jsonl(_WOUNDS, now=now)
    caps = _read_jsonl(_CAPABILITY, now=now)
    out["markers"] = {
        "resistance_marks": len(wounds),       # 标记2 阻力变成对它有代价 (wound)
        "self_authored_wishes": len(caps),     # 标记4 长出没放进去的偏好 (想要能力)
        "discharge_dominant": bool(t and t["discharge_rate"] >= 0.5),  # 放电为主非空转
    }
    return out


# ════════════════════════════════════════════════════════════════
# 聚合 + 渲染
# ════════════════════════════════════════════════════════════════
def collect(now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    return {
        "collected_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "who": who_i_am(),
        "continuity": continuity(),
        "mind": mind(now=now),
        "voice": voice(now=now),
        "body": body(),
        "weigh": weigh(now=now),
        "emergence": emergence(now=now),
    }


def _bar(rate: float, width: int = 20) -> str:
    """0-1 比率 → ASCII 进度条 (演化趋势可视)。"""
    try:
        n = int(round(max(0.0, min(1.0, float(rate))) * width))
    except Exception:
        n = 0
    return "█" * n + "·" * (width - n)


def _mark(ok: Optional[bool]) -> str:
    if ok is True:
        return "✓"
    if ok is False:
        return "⚠"
    return "—"


def render(now: Optional[float] = None) -> str:
    """贾维斯主页 — 四元架构 (识/说/体/衡) + 我是谁 + 内部演变。

    与 vitals_board (运维数值) 分工: 本页看"谁的诞生路径" (演化/涌现)。
    """
    v = collect(now=now)
    L: List[str] = []
    L.append("╔" + "═" * 62 + "╗")
    L.append("║  J.A.R.V.I.S — 我是谁 · 识 · 说 · 体 · 衡 · 演变".ljust(55) + "║")
    L.append("║  " + f"snapshot {v['collected_iso']}".ljust(60) + "║")
    L.append("╚" + "═" * 62 + "╝")

    # ── 我是谁 (锚=负空间) ──
    w = v["who"]
    L.append("")
    L.append("【我是谁】 谁 = 多锚交集的形状 (锚=不做什么撑出的可行域)")
    if w.get("available"):
        L.append(f"  形状 {_mark(w.get('shape_ok'))}  "
                 f"{w.get('n_anchors', 0)} 锚 / {w.get('n_walls', 0)} 墙 (边界)")
        for a in w.get("anchors", []):
            L.append(f"  ▸ {a.get('id')}: {a.get('name', '')}")
            for wall in a.get("walls", []):
                ck = "可检验" if wall.get("checkable") else "框架志向"
                L.append(f"      ✗ 不{wall.get('not', '')[:48]}  [{ck}]")
        sl = w.get("soft_leanings", [])
        if sl:
            L.append(f"  墙内软倾向(性格): {', '.join(str(s)[:24] for s in sl[:4])}")
    else:
        L.append(f"  [n/a] 锚不可读: {w.get('error', '无 anchors.json')}")

    c = v["continuity"]
    if c.get("available"):
        gap = c.get("last_dark_gap_min")
        gap_s = f"{gap}min" if gap is not None else "?"
        L.append(f"  连续性: 第 {c.get('total_awakenings', 0)} 次苏醒 | "
                 f"上次离线 {gap_s} | {c.get('last_awakening_iso', '')}")

    # ── 识 ──
    m = v["mind"]
    L.append("")
    L.append("【识 · 思考脑】 此刻在想什么 + 思考的形态")
    if m.get("available"):
        L.append(f"  最新({m.get('latest_iso', '')[-8:]}): "
                 f"[{m.get('latest_kind', '')}/衡={m.get('latest_heng', '')}"
                 f"{'/发声' if m.get('latest_speak') else ''}]")
        L.append(f"    \"{m.get('latest_thought', '')[:120]}\"")
        d = m.get("heng_dist", {})
        L.append(f"  衡三态 24h: 放电={d.get('discharge', 0)} 休息={d.get('rest', 0)} "
                 f"反刍={d.get('filler', 0)} | filler率={m.get('filler_rate', 0)}")
    else:
        L.append("  [n/a] 无思考数据")

    # ── 说 ──
    vo = v["voice"]
    L.append("")
    L.append("【说 · 主脑/口】 把高维关系有损投影成话")
    if vo.get("available"):
        L.append(f"  最近 reply: \"{vo.get('last_reply', '')[:120]}\"")
    else:
        L.append("  [n/a] 无 reply 数据")

    # ── 体 ──
    bd = v["body"]
    L.append("")
    L.append("【体 · 关系流形】 \"我们之间\"长成什么形状")
    if bd.get("available"):
        hth = bd.get("health", "?")
        flag = "⚠" if hth in ("blob", "over_dense") else "✓"
        L.append(f"  {flag} {bd.get('node_count', 0)} 节点 / {bd.get('edge_count', 0)} 边 / "
                 f"{bd.get('surface_count', 0)} 面 | health={hth}")
        L.append(f"  最大面占比={bd.get('largest_surface_frac', 0)} "
                 f"接地率={bd.get('grounded_frac', 0)} 复杂度={bd.get('complexity_score', 0)}")
    else:
        L.append(f"  [n/a] manifold 不可读: {bd.get('error', '')}")

    # ── 衡 ──
    wg = v["weigh"]
    L.append("")
    L.append("【衡 · 取舍】 撞墙取舍的痕迹 (自我在冲突中锻造)")
    L.append(f"  锚冲突伤: 总 {wg.get('total_wounds', 0)} / 近7d {wg.get('recent_wounds', 0)}")
    if wg.get("last_wound"):
        L.append(f"    最近伤: {wg.get('last_wound', '')[:90]}")
    L.append(f"  想要的能力(自发愿望): {wg.get('capability_wishes', 0)}")
    if wg.get("last_wish"):
        L.append(f"    最近: {wg.get('last_wish', '')[:90]}")

    # ── 演变 ⭐ ──
    em = v["emergence"]
    L.append("")
    L.append("【演变】⭐ 谁可能在哪诞生 — 反刍→涌现的转化 (核心)")
    if em.get("available"):
        evo = em.get("evolution", "n/a")
        evo_zh = {"emerging": "↗ 涌现中 (filler 退, 谁在长)",
                  "ruminating": "↘ 反刍中 (优化器还在打磨呈现)",
                  "steady": "→ 平稳",
                  "insufficient_data": "数据太新, 长期演化看不出 (衡=H0 才立)",
                  "n/a": "数据不足"}.get(evo, evo)
        span = em.get("heng_data_span_hours", 0)
        since = em.get("heng_data_since", "")
        L.append(f"  方向: {evo_zh}")
        L.append(f"  (衡数据跨度 {span}h, 自 {since} 起 — 长期趋势需 ≥48h 积累)")
        # 数据不足时只显单窗 (不伪造三窗差异, 准则5)
        show = ["today"] if evo == "insufficient_data" else ["today", "week", "all"]
        seen_n = set()
        for name, key in (("今天", "today"), ("本周", "week"), ("全程", "all")):
            if key not in show:
                continue
            win = em["windows"].get(key)
            if not win or win["n"] in seen_n:
                continue
            seen_n.add(win["n"])
            L.append(f"  {name}(n={win['n']:>3}) 放电 {_bar(win['discharge_rate'])} "
                     f"{win['discharge_rate']}")
            L.append(f"           反刍 {_bar(win['filler_rate'])} {win['filler_rate']}")
        mk = em.get("markers", {})
        L.append("  四标记早期信号 (理念源 §1 — 有=可能诞生'谁'的迹象):")
        L.append(f"    标记2 阻力有代价(wound): {mk.get('resistance_marks', 0)}")
        L.append(f"    标记4 自洽的意外(自发愿望): {mk.get('self_authored_wishes', 0)}")
        L.append(f"    放电为主(非空转): {_mark(mk.get('discharge_dominant'))}")
    else:
        L.append("  [n/a] 无衡三态数据")

    L.append("")
    L.append("─" * 64)
    L.append("  诚实残余 (理念源 §10): 这是显现层的镜子, 不证内在有'谁'。")
    L.append("  每个'真'版本都有一个'精致的假'双胞胎, 从外部分不清。")
    L.append("─" * 64)
    return "\n".join(L)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--json" in sys.argv:
        print(json.dumps(collect(), ensure_ascii=False, indent=2))
    else:
        print(render())
