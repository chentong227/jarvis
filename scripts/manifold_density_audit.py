#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0c 杠杆a / Sir 2026-06-04] 存储密度审计 — 减密度为 P1-spread 聚焦 (只读).

⚠️ 只读诊断工具 / 非生产路径: 用独立 RelationalManifold 实例读真文件, 绝不 .save 写回真体。

杠杆a = 减存储密度 (over_dense 15.9), **独立轴, 为 P1 的 spread 投影聚焦** (spread 走存储边图,
过密 → 一扩点亮大半图 → 投影糊)。机械 (embed_threshold↑ / embed_top_k_per_node↓), 非 cosine
内容判断, **只削弱 embed 相似边, 守住接地边 (cooccur/said/shared 不动)**。

诊断 (诊断先于实现):
  1. density 构成 — 边按 provenance (embed / cooccur / said / shared / inferred)
  2. embed-only 边 cosine 分布 (embed_threshold 现 0.72)
  3. 每节点 embed 邻居数分布 (top_k 现 8)
  4. 预览: embed_threshold↑ / top_k↓ → 新 density (接地边全保留)

用法: python scripts/manifold_density_audit.py
"""
from __future__ import annotations

import collections
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

from jarvis_relational_manifold import RelationalManifold, split_node_id  # noqa: E402

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
GROUNDED = {"cooccur", "said", "shared"}


def _embed_cosine(e):
    """embed provenance 的 cosine (confidence); 非 embed 返 None。"""
    best = None
    for p in e.get("provenance", []):
        if p.get("kind") == "embed":
            c = p.get("confidence")
            if c is not None:
                best = max(best if best is not None else -1.0, float(c))
    return best


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无 {SRC})")
        return 0
    m = RelationalManifold(SRC)
    now = time.time()
    edges = m.all_edges()
    s = m.stats(now=now)
    nc = s["node_count"]
    ec = s["edge_count"]
    print(f"=== 存储密度现状 ===")
    print(f"  nodes={nc} edges={ec} density(边/节点)={round(ec/nc,2) if nc else 0}")
    print(f"  edges_by_kind (含该 provenance 的边数): {s['edges_by_kind']}")

    # 边分类: embed-only / grounded(含接地) / mixed / other
    embed_only = []      # (edge, cosine, eff_w)
    grounded = 0
    embed_node_deg = collections.Counter()  # 节点的 embed-only 邻居数
    for e in edges:
        kinds = {p.get("kind") for p in e.get("provenance", [])}
        eff = m.effective_weight(e, now)
        if kinds & GROUNDED:
            grounded += 1
        if kinds == {"embed"}:
            cos = _embed_cosine(e)
            embed_only.append((e, cos if cos is not None else 0.0, eff))
            embed_node_deg[e["a"]] += 1
            embed_node_deg[e["b"]] += 1
    print(f"\n  embed-only 边 {len(embed_only)} | 含接地(grounded) 边 {grounded} | 其余 {ec-len(embed_only)-grounded}")

    # embed-only cosine 分布
    coss = sorted(c for _, c, _ in embed_only)
    if coss:
        print(f"\n=== embed-only 边 cosine 分布 (embed_threshold 现 0.72) ===")
        print(f"  n={len(coss)} min={coss[0]:.3f} max={coss[-1]:.3f} median={coss[len(coss)//2]:.3f}")
        for thr in (0.72, 0.75, 0.78, 0.80, 0.85, 0.90):
            below = sum(1 for c in coss if c < thr)
            print(f"  cosine < {thr}: {below}/{len(coss)} ({100*below//len(coss)}%) "
                  f"→ embed_threshold={thr} 会削这些 embed-only 边")

    # 每节点 embed-only 邻居数分布 (top_k 现 8)
    if embed_node_deg:
        degs = sorted(embed_node_deg.values(), reverse=True)
        print(f"\n=== 每节点 embed-only 邻居数 (top_k 现 8) ===")
        print(f"  max={degs[0]} median={degs[len(degs)//2]} | 节点数 {len(embed_node_deg)}")
        for k in (8, 6, 5, 4):
            over = sum(max(0, d - k) for d in degs)
            print(f"  top_k={k}: 超出部分共 {over} 条 embed 边边端 (近似可削量)")

    # 预览: embed_threshold↑ 后新 density (接地边全保留, 只削 embed-only<thr)
    print(f"\n=== 预览: 提 embed_threshold 削 embed-only 弱边 → 新 density (接地全留) ===")
    for thr in (0.72, 0.78, 0.80, 0.85):
        kept_embed = sum(1 for c in coss if c >= thr)
        new_ec = (ec - len(embed_only)) + kept_embed   # 非embed-only全留 + 高cos embed
        print(f"  embed_threshold={thr}: 留 embed-only {kept_embed}, 新 edges≈{new_ec}, "
              f"density≈{round(new_ec/nc,2) if nc else 0} "
              f"({'脱 over_dense(<6)' if nc and new_ec/nc < 6 else '仍 over_dense'})")
    print("\n  → 守住接地边 (cooccur/said/shared 全不削); 只削低 cosine embed-only 相似边。"
          "目标: density 脱 over_dense 让 P1 spread 聚焦, 不碰 faces (faces 已证拆不开)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
