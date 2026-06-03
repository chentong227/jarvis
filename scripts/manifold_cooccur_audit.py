#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0c / Sir 2026-06-03] cooccur 边审计 — 诊断+校准薄化判据 (只读, 无 LLM, 无写回).

⚠️ 只读诊断工具 / 非生产路径: 用独立 RelationalManifold 实例读真文件, 绝不 .save 写回真体。

Sir ground truth: hydration ⊥ interview 在真实生活互不相干 → cooccur 把它们连一起 = 假边
(同轮 check-in 一起提 ≠ 关联)。本审计读真 manifold 的 cooccur 边, 统计 concern↔concern 跨主题
边是"单轮偶发共提"还是"反复真共变" (reinforce_count = 共现轮数 / provenance 轮数 / 时间跨度),
用 ground truth 校准 Step A 的薄化判据 (机械计数/窗口/特异性, 绝不 cosine; 别凭魔数)。

用法: python scripts/manifold_cooccur_audit.py
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
    RelationalManifold, split_node_id,
)

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
PROV_COOCCUR = "cooccur"


def _cooccur_prov(e):
    """返该边的 cooccur provenance entries (kind=cooccur)。"""
    return [p for p in e.get("provenance", []) if p.get("kind") == PROV_COOCCUR]


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无 {SRC})")
        return 0
    m = RelationalManifold(SRC)   # 只读: 不调 save()
    now = time.time()
    edges = m.all_edges()

    # 分类: 按端点 kind 对 + 收集每条 cooccur 边的 reinforce_count (校准薄化)
    by_pair_kind = {}
    pair_rc = {}        # pair -> list of reinforce_count
    all_rc = []
    cc_concern_concern = []
    for e in edges:
        cprov = _cooccur_prov(e)
        if not cprov:
            continue  # 只看含 cooccur 的边
        ka = split_node_id(e["a"])[0]
        kb = split_node_id(e["b"])[0]
        pair = tuple(sorted([ka, kb]))
        by_pair_kind[pair] = by_pair_kind.get(pair, 0) + 1
        rc_e = int(e.get("reinforce_count", 0))
        pair_rc.setdefault(pair, []).append(rc_e)
        all_rc.append(rc_e)
        if ka == "concern" and kb == "concern":
            # 共现轮数: reinforce_count (真总数) + provenance 里 distinct turn (capped 12)
            rc = int(e.get("reinforce_count", 0))
            tss = [float(p.get("ts", 0)) for p in cprov if p.get("ts")]
            span_d = round((max(tss) - min(tss)) / 86400.0, 1) if len(tss) >= 2 else 0.0
            cc_concern_concern.append({
                "a": split_node_id(e["a"])[1],
                "b": split_node_id(e["b"])[1],
                "w": round(m.effective_weight(e, now), 3),
                "reinforce_count": rc,
                "n_prov_turns": len(cprov),
                "ts_span_days": span_d,
            })

    print("=== cooccur 边按端点 kind 对 (含 cooccur provenance 的边) — 看焊料在哪 ===")
    print(f"  {'pair':22} {'n':>4} {'rc=1(偶发)':>10} {'rc>=3(反复)':>11} {'median_rc':>9}")
    for pair, n in sorted(by_pair_kind.items(), key=lambda x: -x[1]):
        rcs = sorted(pair_rc.get(pair, []))
        n_rc1 = sum(1 for x in rcs if x <= 1)
        n_rc3 = sum(1 for x in rcs if x >= 3)
        med = rcs[len(rcs) // 2] if rcs else 0
        print(f"  {pair[0]:8} ↔ {pair[1]:8} {n:>4} {n_rc1:>10} {n_rc3:>11} {med:>9}")
    # 全 cooccur rc 分布 (校准薄化阈 K — 单轮偶发 rc=1 占比)
    if all_rc:
        a = sorted(all_rc)
        print(f"\n=== 全 cooccur 边 rc 分布 (校准薄化: rc=1=单轮偶发=假边候选) ===")
        print(f"  total={len(a)} rc=1: {sum(1 for x in a if x<=1)} "
              f"({100*sum(1 for x in a if x<=1)//len(a)}%) | "
              f"rc=2: {sum(1 for x in a if x==2)} | rc>=3: {sum(1 for x in a if x>=3)} | "
              f"max={max(a)} median={a[len(a)//2]}")
        for k in (2, 3):
            cut = sum(1 for x in a if x < k)
            print(f"  若薄到 rc>={k}: 切 {cut}/{len(a)} 条 cooccur ({100*cut//len(a)}%), 留 {len(a)-cut} 条反复共现")

    print(f"\n=== concern ↔ concern cooccur 边 ({len(cc_concern_concern)} 条) — 跨主题假边候选 ===")
    print(f"  {'reinf':>5} {'turns':>5} {'span_d':>6} {'w':>6}  A ↔ B")
    cc_concern_concern.sort(key=lambda r: -r["reinforce_count"])
    for r in cc_concern_concern:
        print(f"  {r['reinforce_count']:>5} {r['n_prov_turns']:>5} "
              f"{r['ts_span_days']:>6} {r['w']:>6}  {r['a'][:22]} ↔ {r['b'][:22]}")

    # reinforce_count 分布 (校准薄化阈 K)
    rcs = [r["reinforce_count"] for r in cc_concern_concern]
    if rcs:
        rcs_sorted = sorted(rcs)
        print(f"\n=== reinforce_count 分布 (校准 Step A 薄化阈 K, 别凭魔数) ===")
        print(f"  n={len(rcs)} min={min(rcs)} max={max(rcs)} "
              f"median={rcs_sorted[len(rcs)//2]}")
        for k in (1, 2, 3, 5):
            n_le = sum(1 for x in rcs if x <= k)
            print(f"  reinforce_count <= {k}: {n_le}/{len(rcs)} 条 "
                  f"({'若 K=%d 则切掉这些' % (k+1)})")

    # ground truth 校准: hydration ↔ interview
    print(f"\n=== ground truth 校准: hydration ↔ interview (Sir 说应独立, 该被切) ===")
    found = False
    for r in cc_concern_concern:
        ab = (r["a"] + r["b"]).lower()
        if "hydration" in ab and "interview" in ab:
            print(f"  找到: {r['a']} ↔ {r['b']}  reinforce_count={r['reinforce_count']} "
                  f"turns={r['n_prov_turns']} span={r['ts_span_days']}d w={r['w']}")
            print(f"  → 若 reinforce_count 低 = 单轮偶发共提 = 假边 (符合 Sir ground truth, 该薄掉)")
            found = True
    if not found:
        print("  (未找到直接 hydration↔interview cooccur 边 — 可能经 thread 间接连, 或已不共现)")

    # === Step A 预览: 薄 cooccur rc<2 → 锚分开没? (core_w 0.60, ① on, 真 config) ===
    # 关键验证: rc=1 cooccur 边权≈0.30 < 成面阈 0.45 → 可能根本不在 surface → 薄掉零效果?
    def _surf(label):
        surfaces = m.compute_surfaces()
        m.set_surfaces(surfaces)
        rep = m.complexity_report()
        print(f"  [{label}] largest_frac={rep['largest_surface_frac']} "
              f"surfaces={rep['surface_count']} bridges={rep['bridge_count']} "
              f"health={rep['health']} nodes={rep['node_count']} edges={rep['edge_count']}")
    print(f"\n=== Step A 预览: 薄 cooccur-only rc<2 → 锚分开没? (真 config core_w0.60 ①on) ===")
    _surf("BEFORE (全边)")
    pruned = 0
    with m._lock:
        for key in list(m._edges.keys()):
            e = m._edges[key]
            provs = e.get("provenance", [])
            cc = [p for p in provs if p.get("kind") == PROV_COOCCUR]
            other = [p for p in provs if p.get("kind") != PROV_COOCCUR]
            if cc and not other and int(e.get("reinforce_count", 0)) < 2:
                m._adj[e["a"]].discard(key)
                m._adj[e["b"]].discard(key)
                del m._edges[key]
                pruned += 1
    print(f"  (薄掉 {pruned} 条 cooccur-only rc<2 边)")
    _surf("AFTER 薄 rc<2")
    print("  → 若 largest_frac/surfaces 几乎不变 = rc=1 边本就 < 成面阈, 薄它无效, "
          "焊料在别处 (rc>=2 cooccur + concern↔thread embed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
