#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0c-B / Sir 2026-06-03] 阈上跨 concern 焊接路径 — 读图刀, 供 Sir 逐条人读真假.

⚠️ 只读诊断工具 / 非生产路径: 用独立 RelationalManifold 实例读真文件, 绝不 .save 写回真体。

Sir B: 读图刀列出**阈上 (>= 成面阈) 把不同 concern 焊一起**的边/路径, Sir 逐条人读
"真共变 vs 假 (cosine≠about)"。已知: hand_pain↔interview(rc=10 coding→手痛) 像真; concern↔
thread 的 cosine embed = 假。只读, 无写回, 无 LLM。

输出三段:
  A. 阈上 concern↔concern 直连边 (最清晰的跨主题焊)
  B. 阈上经 thread 桥接 >=2 个 concern 的 thread (间接跨主题焊)
  C. 阈上 concern↔thread EMBED (cosine) 边 — 标注 thread 历史 about 哪个 concern
     (about==该concern=cosine 重复接地; about!=或无=纯 cosine 跨焊=假)

用法: python scripts/manifold_cross_concern_audit.py
"""
from __future__ import annotations

import json
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_relational_manifold import (  # noqa: E402
    RelationalManifold, split_node_id, get_manifold_config,
)

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
THOUGHTS = os.path.join(ROOT, "memory_pool", "inner_thoughts.jsonl")


def _about_map():
    """thread_id -> set(concern_id) from inner_thoughts.jsonl adjust_concern_notes."""
    m = {}
    if not os.path.exists(THOUGHTS):
        return m
    for line in open(THOUGHTS, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
        except Exception:
            continue
        a = (t.get("actionable") or "")
        if a.startswith("adjust_concern_notes:"):
            p = a.split(":", 2)
            if len(p) >= 3:
                cid = p[1].strip()
                tid = (t.get("thread_id") or t.get("id") or "").strip()
                if cid and tid:
                    m.setdefault(tid, set()).add(cid)
    return m


def _kinds(e):
    return "+".join(sorted({p.get("kind") for p in e.get("provenance", []) if p.get("kind")}))


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无 {SRC})")
        return 0
    m = RelationalManifold(SRC)
    cfg = get_manifold_config()
    thr = float(cfg.get("surface_min_weight", 0.45))
    core_w = float(cfg.get("surface_core_min_weight", 0.60))
    now = time.time()
    about = _about_map()
    try:
        from jarvis_relational_weaver import RelationalWeaver
        text = RelationalWeaver(manifold=m).harvest_nodes()
    except Exception:
        text = {}

    def _t(nid):
        return (text.get(nid) or "").replace("\n", " ")[:58]

    edges = m.all_edges()
    above = [(e, m.effective_weight(e, now)) for e in edges]
    above = [(e, w) for e, w in above if w >= thr]
    print(f"[阈上跨 concern 焊接路径] 成面阈={thr} 核阈={core_w} | 阈上边 {len(above)}/{len(edges)}")

    # A. concern↔concern 阈上直连
    print(f"\n=== A. 阈上 concern↔concern 直连边 (最清晰跨主题焊) ===")
    aa = []
    for e, w in above:
        ka, kb = split_node_id(e["a"])[0], split_node_id(e["b"])[0]
        if ka == "concern" and kb == "concern":
            aa.append((w, e))
    if not aa:
        print("  (无 — concern 间无阈上直连边)")
    for w, e in sorted(aa, key=lambda x: -x[0]):
        rc = int(e.get("reinforce_count", 0))
        print(f"  w={w:.2f} rc={rc} [{_kinds(e)}]  "
              f"{split_node_id(e['a'])[1][:24]} ↔ {split_node_id(e['b'])[1][:24]}")

    # B. thread 桥接 >=2 concern (阈上)
    print(f"\n=== B. 阈上经 thread 桥接 >=2 concern 的 thread (间接跨主题焊) ===")
    thread_concerns = {}  # thread_node -> {concern_node: (w, kinds)}
    for e, w in above:
        ka, kb = split_node_id(e["a"])[0], split_node_id(e["b"])[0]
        if {ka, kb} == {"thread", "concern"}:
            tnode = e["a"] if ka == "thread" else e["b"]
            cnode = e["b"] if ka == "thread" else e["a"]
            thread_concerns.setdefault(tnode, {})[cnode] = (w, _kinds(e))
    bridges = {t: cs for t, cs in thread_concerns.items() if len(cs) >= 2}
    if not bridges:
        print("  (无 thread 阈上连到 >=2 concern)")
    for tnode, cs in sorted(bridges.items(), key=lambda x: -len(x[1])):
        tid = split_node_id(tnode)[1]
        ab = about.get(tid, set())
        print(f"\n  🧵 thread {tid[:26]}  (历史 about: {sorted(ab) or '—'})")
        print(f"      文本: {_t(tnode)}")
        for cnode, (w, k) in sorted(cs.items(), key=lambda x: -x[1][0]):
            cid = split_node_id(cnode)[1]
            flag = "✓grounded(about匹配)" if cid in ab else "⚠cosine?(about不含此concern)"
            print(f"      → {cid[:22]:22} w={w:.2f} [{k}] {flag}")

    # C. concern↔thread 阈上 EMBED (cosine) 边 — 纯 cosine 跨焊候选
    print(f"\n=== C. 阈上 concern↔thread 含 EMBED 边 (cosine 焊 thread 到 concern) ===")
    cc = []
    for e, w in above:
        ka, kb = split_node_id(e["a"])[0], split_node_id(e["b"])[0]
        if {ka, kb} == {"thread", "concern"} and "embed" in _kinds(e):
            cc.append((w, e))
    print(f"  共 {len(cc)} 条 concern↔thread 含 embed 阈上边:")
    grounded_n = cosine_n = 0
    for w, e in sorted(cc, key=lambda x: -x[0]):
        ka = split_node_id(e["a"])[0]
        tnode = e["a"] if ka == "thread" else e["b"]
        cnode = e["b"] if ka == "thread" else e["a"]
        tid = split_node_id(tnode)[1]
        cid = split_node_id(cnode)[1]
        ab = about.get(tid, set())
        is_g = cid in ab
        grounded_n += is_g
        cosine_n += (not is_g)
    print(f"  其中 about 匹配(cosine 重复接地): {grounded_n} | "
          f"about 不含此 concern(纯 cosine 跨焊=假): {cosine_n}")
    for w, e in sorted(cc, key=lambda x: -x[0])[:15]:
        ka = split_node_id(e["a"])[0]
        tnode = e["a"] if ka == "thread" else e["b"]
        cnode = e["b"] if ka == "thread" else e["a"]
        tid = split_node_id(tnode)[1]
        cid = split_node_id(cnode)[1]
        ab = about.get(tid, set())
        flag = "✓about匹配" if cid in ab else "⚠纯cosine"
        print(f"  w={w:.2f} [{_kinds(e)}] {flag}  {cid[:20]} ~ {tid[:18]}  {_t(tnode)[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
