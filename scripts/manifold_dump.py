#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/manifold_dump.py — Sir CLI 看/管 体(Body)的关系流形边层.

[体-P1 / 2026-05-31] 准则 6: 数据持久化 memory_pool/relational_manifold.json
+ CLI 可看/改 (Sir 不需改源码). 边由织网者 Weaver (体-P5) / 识 / sensor 自动织.
详 docs/JARVIS_TRINITY_ARCHITECTURE.md.

用法:
  python scripts/manifold_dump.py                    # stats + top 边 (默认)
  python scripts/manifold_dump.py --top 40           # 看权重最高 N 条边
  python scripts/manifold_dump.py --node <node_id>   # 看某节点的 neighbors (前缀匹配)
  python scripts/manifold_dump.py --kind cooccur     # 只看某 provenance 类型的边
  python scripts/manifold_dump.py --review           # 看 LLM 推断待审边 (体-P4)
  python scripts/manifold_dump.py --spread <node_id> # spreading-activation 预览 (透镜原型)
  python scripts/manifold_dump.py --surfaces         # 看语义曲面 (体-P3 面/社区)
  python scripts/manifold_dump.py --lens [seed]      # 预览透镜投影 block (体-P6, 不需开 gate)
  python scripts/manifold_dump.py --config           # 看当前 config
  python scripts/manifold_dump.py --decay            # 衰减全部边到 now (写回)
  python scripts/manifold_dump.py --prune            # 删低于 floor 的边
  python scripts/manifold_dump.py --weave            # 织网者跑一轮 (harvest+几何边, 真调 embedding)
  python scripts/manifold_dump.py --json             # raw dump
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Windows PowerShell stdout 默 GBK, 本 CLI 用 emoji (✅⚠️) 会 UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_relational_manifold import (  # noqa: E402
    RelationalManifold, get_manifold_config, split_node_id,
)

PATH = os.path.join(ROOT, "memory_pool", "relational_manifold.json")


def _fmt_age(ts) -> str:
    a = max(0, int(time.time() - float(ts or 0)))
    if a < 3600:
        return f"{a // 60}m"
    if a < 86400:
        return f"{a // 3600}h"
    return f"{a // 86400}d"


def _short(node_id: str, width: int = 30) -> str:
    return node_id if len(node_id) <= width else node_id[: width - 1] + "\u2026"


def _kinds_of(e: dict) -> str:
    seen = []
    for p in e.get("provenance", []):
        k = p.get("kind")
        if k and k not in seen:
            seen.append(k)
    return "+".join(seen)


def cmd_stats(m: RelationalManifold) -> None:
    s = m.stats()
    print("=== 体 / Relational Manifold (边层) ===")
    print(f"边数: {s['edge_count']}   节点数: {s['node_count']}   "
          f"待审(inferred): {s['review_count']}")
    print(f"总有效权重: {s['total_effective_weight']}")
    print(f"边按类型: {s['edges_by_kind']}")


def cmd_top(m: RelationalManifold, n: int, kind: str = "") -> None:
    now = time.time()
    edges = m.all_edges()
    rows = []
    for e in edges:
        if kind and kind not in _kinds_of(e):
            continue
        rows.append((m.effective_weight(e, now), e))
    rows.sort(key=lambda x: x[0], reverse=True)
    if not rows:
        print("(无匹配边 — 织网者还没织, 或 kind 过滤太严)")
        return
    print(f"{'WEIGHT':>7} {'CNT':>4} {'AGE':>4} {'KINDS':14} A  ~  B")
    print("-" * 80)
    for w, e in rows[:n]:
        print(f"{w:>7.3f} {int(e.get('reinforce_count', 0)):>4} "
              f"{_fmt_age(e.get('last_reinforced_ts')):>4} "
              f"{_kinds_of(e):14} {_short(e['a'])}  ~  {_short(e['b'])}")
    print(f"\n共 {len(rows)} 边" + (f" (kind={kind})" if kind else ""))


def cmd_node(m: RelationalManifold, prefix: str) -> None:
    # 前缀匹配找节点 (Sir 不用打全 id)
    matches = set()
    for e in m.all_edges():
        for nid in (e["a"], e["b"]):
            if nid == prefix or nid.startswith(prefix) or prefix in nid:
                matches.add(nid)
    if not matches:
        print(f"(无节点匹配 {prefix!r})")
        return
    for nid in sorted(matches):
        kind, raw = split_node_id(nid)
        nbrs = m.neighbors(nid, limit=20)
        print(f"\n● {nid}  (kind={kind}, degree={m.degree(nid)})")
        for other, w in nbrs:
            e = m.get_edge(nid, other)
            print(f"    {w:>6.3f}  [{_kinds_of(e) if e else '?'}]  {_short(other, 44)}")


def cmd_review(m: RelationalManifold) -> None:
    rows = [e for e in m.all_edges() if e.get("review")]
    if not rows:
        print("(无待审 inferred 边 — 体-P4 LLM propose 后才有)")
        return
    print(f"待审 LLM 推断边 {len(rows)} 条:")
    for e in rows:
        prov = [p for p in e.get("provenance", []) if p.get("inferred")]
        conf = prov[0].get("confidence") if prov else "?"
        rat = prov[0].get("detail", "") if prov else ""
        print(f"  conf={conf} {_short(e['a'], 28)} ~ {_short(e['b'], 28)}  {rat[:50]}")


def cmd_spread(m: RelationalManifold, prefix: str) -> None:
    seed = None
    for e in m.all_edges():
        for nid in (e["a"], e["b"]):
            if nid == prefix or nid.startswith(prefix) or prefix in nid:
                seed = nid
                break
        if seed:
            break
    if not seed:
        print(f"(无节点匹配 {prefix!r})")
        return
    act = m.spread([seed], hops=2)
    rows = sorted(act.items(), key=lambda x: x[1], reverse=True)
    print(f"spreading-activation from {seed} (hops=2):")
    for nid, a in rows[:30]:
        tag = "  <seed>" if nid == seed else ""
        print(f"    {a:>6.3f}  {_short(nid, 50)}{tag}")
    print(f"\n点亮 {len(rows)} 节点 (透镜 Lens 体-P6 用这个选投影子图)")


def cmd_surfaces(m: RelationalManifold) -> None:
    surfaces = m.get_surfaces()
    if not surfaces:
        print("(无语义曲面 — 织网者还没织, 或没有 >= surface_min_weight 的紧连块)")
        print("提示: 先 python scripts/manifold_dump.py --weave")
        return
    print(f"语义曲面 (体-P3 面) {len(surfaces)} 个:")
    for s in surfaces:
        print(f"\n● {s['surface_id']}  size={s['size']}  kinds={s.get('kinds', {})}")
        for nid in s.get("top_nodes", [])[:5]:
            print(f"    · {_short(nid, 56)}")


def cmd_lens(m: RelationalManifold, seed_prefix: str) -> None:
    from jarvis_relational_lens import RelationalLens, lens_inject_enabled
    lens = RelationalLens(manifold=m)
    seeds = None
    if seed_prefix:
        text_map = lens._node_text_map()
        seeds = [n for n in text_map if seed_prefix in n]
        if not seeds:
            print(f"(无节点匹配 {seed_prefix!r}; 用默认 seeds)")
            seeds = None
    block = lens.project(seeds)
    print(f"[lens gate: {'ON' if lens_inject_enabled() else 'OFF (预览不受影响)'}]\n")
    print(block if block else "(投影为空 — 体还没织边 / 无相关节点 / 无高置信立场)")


def cmd_complexity(m: RelationalManifold) -> None:
    r = m.complexity_report()
    print("=== 体复杂度 vs 体积 (closure D1) ===")
    print(f"health: {r['health']}   complexity_score: {r['complexity_score']}")
    print(f"nodes={r['node_count']} edges={r['edge_count']} surfaces={r['surface_count']}")
    print(f"density(边/节点)={r['density']}  largest_surface_frac(blob 检测)={r['largest_surface_frac']}")
    print(f"grounded_frac={r['grounded_frac']}  compression(节点/面)={r['compression']}")
    if r["health"] == "blob":
        print("⚠️ blob: 一个大簇吃掉过半节点 = 冗余体积, 低复杂度 → 该 merge (closure D2)")
    elif r["health"] == "over_dense":
        print("⚠️ over_dense: 过连接, 信息稀释 → 提阈值 / prune")


def cmd_config() -> None:
    print(json.dumps(get_manifold_config(), ensure_ascii=False, indent=2))


def cmd_merge_dups(m: RelationalManifold, threshold: float) -> None:
    """口识体 数据卫生: 一次性合并近重复节点 (alias, 不删源, 可逆). 准则 6 CLI.

    用缓存向量算两两 cosine, >= threshold → add_alias(dup→rep, rep=度数高). 收 blob/去重
    识自生成的近重复 self-talk (如 8 个 'Sir 装睡' joke 变体). 不删 relational_state 源。
    """
    import numpy as np
    vpath = os.path.join(ROOT, "memory_pool", "manifold_vectors.json")
    try:
        vec = (json.load(open(vpath, encoding="utf-8")) or {}).get("vectors") or {}
    except Exception:
        print("(无 manifold_vectors.json — 先 python scripts/manifold_dump.py --weave)")
        return
    ids = [k for k in vec if vec[k].get("vec")]
    if len(ids) < 2:
        print("(缓存向量 < 2, 无法算近重复)")
        return
    M = np.array([vec[i]["vec"] for i in ids], dtype=np.float32)
    nrm = np.linalg.norm(M, axis=1, keepdims=True)
    nrm[nrm == 0] = 1.0
    Mn = M / nrm
    sim = Mn @ Mn.T
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            c = float(sim[i, j])
            if c >= threshold:
                pairs.append((c, ids[i], ids[j]))
    pairs.sort(reverse=True)
    print(f"近重复对 (cosine>={threshold}): {len(pairs)}")
    merged = 0
    for c, a, b in pairs:
        ra, rb = m.resolve(a), m.resolve(b)
        if ra == rb:
            continue
        rep, dup = (ra, rb) if m.degree(ra) >= m.degree(rb) else (rb, ra)
        if m.add_alias(dup, rep):
            merged += 1
            print(f"  merge cos={c:.3f}  keep {_short(rep, 42)}  ←alias {_short(dup, 42)}")
    if merged:
        m.save()
    cx = m.complexity_report()
    print(f"\n✅ 合并 {merged} 对 (source 不删, 可逆). "
          f"complexity: {cx['health']}/{cx['complexity_score']} "
          f"largest_surface_frac={cx['largest_surface_frac']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis 体(Body) 关系流形 CLI")
    ap.add_argument("--top", type=int, metavar="N", help="看权重最高 N 条边")
    ap.add_argument("--node", metavar="ID", help="看某节点 neighbors (前缀匹配)")
    ap.add_argument("--kind", metavar="K", default="",
                    help="过滤 provenance 类型 (cooccur/said/shared/embed/inferred)")
    ap.add_argument("--review", action="store_true", help="看 LLM 推断待审边")
    ap.add_argument("--spread", metavar="ID", help="spreading-activation 预览 (透镜原型)")
    ap.add_argument("--surfaces", action="store_true", help="看语义曲面 (体-P3 面)")
    ap.add_argument("--complexity", action="store_true", help="复杂度 vs 体积度量 (closure D1)")
    ap.add_argument("--lens", nargs="?", const="", metavar="SEED",
                    help="预览透镜投影 block (体-P6; 可选 seed 节点前缀)")
    ap.add_argument("--config", action="store_true", help="看 config")
    ap.add_argument("--decay", action="store_true", help="衰减全部边到 now (写回)")
    ap.add_argument("--prune", action="store_true", help="删低于 floor 的边")
    ap.add_argument("--weave", action="store_true",
                    help="织网者跑一轮 (harvest + 几何 embed 边, 真调 embedding API)")
    ap.add_argument("--merge-dups", action="store_true",
                    help="一次性合并近重复节点 (alias 去重 blob, 不删源, 可逆)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="--merge-dups 的 cosine 阈值 (默认取 config merge_threshold)")
    ap.add_argument("--json", action="store_true", help="raw dump")
    args = ap.parse_args(argv)

    if args.config:
        cmd_config()
        return 0

    m = RelationalManifold(PATH)

    if args.weave:
        from jarvis_relational_weaver import RelationalWeaver
        w = RelationalWeaver(manifold=m)
        print("织网中 (harvest + embed + 几何边)... 真调 embedding API, 稍候")
        stats = w.weave_once()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    if args.merge_dups:
        thr = (args.threshold if args.threshold is not None
               else float(get_manifold_config().get("merge_threshold", 0.90)))
        cmd_merge_dups(m, thr)
        return 0

    if args.json:
        print(json.dumps({"stats": m.stats(), "edges": m.all_edges()},
                         ensure_ascii=False, indent=2))
    elif args.node:
        cmd_node(m, args.node)
    elif args.review:
        cmd_review(m)
    elif args.spread:
        cmd_spread(m, args.spread)
    elif args.surfaces:
        cmd_surfaces(m)
    elif args.complexity:
        cmd_complexity(m)
    elif args.lens is not None:
        cmd_lens(m, args.lens)
    elif args.decay:
        m.apply_decay()
        m.save()
        print("✅ 已衰减全部边到 now 并写回")
        cmd_stats(m)
    elif args.prune:
        n = m.prune()
        m.save()
        print(f"✅ 已 prune {n} 条低权重边")
        cmd_stats(m)
    elif args.top:
        cmd_top(m, args.top, kind=args.kind)
    else:
        cmd_stats(m)
        print()
        cmd_top(m, 20, kind=args.kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
