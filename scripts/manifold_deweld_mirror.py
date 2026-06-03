#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0c / Sir 2026-06-03] de-weld 镜像 — 按 about 謁证去假焊, 决定性测"簇=artifact?".

⚠️ 只读诊断工具 / 非生产路径: 用独立 RelationalManifold 实例读真文件 + 仅内存 prune, 绝不 .save
写回真体; de-weld 仅诊断不落市 (Sir 判: 全剥=89孤儿=欠整合, 且薄是假薄)。

Sir 人读 ground truth 翻转: "robust 单簇"是 artifact, 不是真整合。concern 本独立, 被泛化
monitoring thought 的 cooccur 假焊成团。机械判据 (替代"薄cooccur by rc", rc≥2≠真关联):
  **about 謁证** —
  1. thread↔concern 阈上边: 仅当 thought 的 about/concern_id 真指向该 concern 才保留;
     否则 = 偶发共提假焊 → 降到阈下 (本镜像: 移除)。
  2. concern↔concern 边: 默认偶发 → 降 (concern 不因同轮被提而相关)。
  3. 纯 cosine 跨类 (about 不含) → 降 (① 扩跨类, 顺手, 已被 #1 覆盖)。
全程机械/接地, 绝不 cosine 判断, **不删节点** (泛化 monitoring thought 节点保留, 只去假焊边;
⑤/红线C 不删传记; 它们可自成"待命/监控"小区或留孤儿, 诚实)。

预期非 no-op (假焊阈上承重)。量: concern 分开?largest_frac 降?长出接地小面? 防过碎 (报面 size)。
只读, 无写回。用法: python scripts/manifold_deweld_mirror.py
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


def _harvest(m):
    try:
        from jarvis_relational_weaver import RelationalWeaver
        return RelationalWeaver(manifold=m).harvest_nodes()
    except Exception:
        return {}


def _measure(m, label, text):
    now = time.time()
    surfaces = m.compute_surfaces(now=now)
    m.set_surfaces(surfaces)
    rep = m.complexity_report(now=now)
    bridges = m.bridge_nodes(surfaces)
    print(f"\n=== {label} ===")
    print(f"  health={rep['health']} largest_frac={rep['largest_surface_frac']} "
          f"surfaces={rep['surface_count']} bridges={rep['bridge_count']} "
          f"nodes={rep['node_count']} edges={rep['edge_count']}")
    sizes = sorted((s["size"] for s in surfaces), reverse=True)
    print(f"  面 size 分布: {sizes[:12]}{' ...' if len(sizes) > 12 else ''} "
          f"(防过碎: 是否一堆 size=3 尘?)")
    # 每面的 concern 成员 (看是否长出接地小面)
    for s in surfaces[:8]:
        concerns = [split_node_id(n)[1][:18] for n in s.get("members", [])
                    if split_node_id(n)[0] == "concern"]
        kinds = s.get("kinds", {})
        print(f"    ● size={s['size']} kinds={kinds} concerns={concerns}")
    return rep


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无 {SRC})")
        return 0
    about = _about_map()
    m = RelationalManifold(SRC)
    text = _harvest(m)
    print(f"[de-weld 镜像] about-map: {len(about)} thread 有 concern_id 謁证")
    _measure(m, "BEFORE — 真 manifold (含假焊)", text)

    # 按 about 謁证去假焊 (机械, 不删节点)
    removed_tc = removed_cc = 0
    with m._lock:
        for key in list(m._edges.keys()):
            e = m._edges[key]
            ka = split_node_id(e["a"])[0]
            kb = split_node_id(e["b"])[0]
            kinds = {p.get("kind") for p in e.get("provenance", [])}
            # #2 concern↔concern → 默认偶发, 移除 (除非将来有 said 显式连, 现无)
            if ka == "concern" and kb == "concern":
                if kinds <= {"cooccur", "embed", "inferred"}:  # 无 said 显式
                    m._adj[e["a"]].discard(key)
                    m._adj[e["b"]].discard(key)
                    del m._edges[key]
                    removed_cc += 1
                continue
            # #1 thread↔concern: 仅 about 謁证才留, 否则移除
            if {ka, kb} == {"thread", "concern"}:
                tnode = e["a"] if ka == "thread" else e["b"]
                cnode = e["b"] if ka == "thread" else e["a"]
                tid = split_node_id(tnode)[1]
                cid = split_node_id(cnode)[1]
                if cid not in about.get(tid, set()):
                    m._adj[e["a"]].discard(key)
                    m._adj[e["b"]].discard(key)
                    del m._edges[key]
                    removed_tc += 1
    print(f"\n[去假焊] 移除 thread↔concern 非謁证边 {removed_tc} 条 + "
          f"concern↔concern 偶发边 {removed_cc} 条 (节点全保留)")
    _measure(m, "AFTER L1 — 去 thread↔concern 非謁证 + concern↔concern (Sir 判据)", text)
    print("  → L1 若仍 1 大面: Sir 判据不够, cluster 经 thread↔thread mesh 残连")

    # === Level 2 决定性测: 纯 about 接地骨架 (只留 about-謁证 thread↔concern) ===
    # 移除 thread↔thread + 一切非 about-謁证边, 看接地骨架是否长出 per-concern 面 (节点保留)。
    m2 = RelationalManifold(SRC)
    kept = 0
    with m2._lock:
        for key in list(m2._edges.keys()):
            e = m2._edges[key]
            ka, kb = split_node_id(e["a"])[0], split_node_id(e["b"])[0]
            keep = False
            if {ka, kb} == {"thread", "concern"}:
                tnode = e["a"] if ka == "thread" else e["b"]
                cnode = e["b"] if ka == "thread" else e["a"]
                tid = split_node_id(tnode)[1]
                cid = split_node_id(cnode)[1]
                if cid in about.get(tid, set()):
                    keep = True
            if not keep:
                m2._adj[e["a"]].discard(key)
                m2._adj[e["b"]].discard(key)
                del m2._edges[key]
            else:
                kept += 1
    print(f"\n[Level 2] 只留 about-謁证 thread↔concern 边 {kept} 条 (移除 thread↔thread + 一切非接地)")
    _measure(m2, "L2 — 纯 about 接地骨架 (only about-謁证 thread↔concern)", text)
    print("\n  → L2 长出多个 per-concern 面 + 跨 concern 的 about-both thread 当桥 = 簇是 artifact, "
          "接地骨架本可分化 (Sir 拓扑设想成立); L2 仍 1 簇/全碎 = 接地太薄/真整合。防过碎: 看 size 分布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
