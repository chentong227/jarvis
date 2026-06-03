#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0c-Tier1 / Sir 2026-06-03] P0c Tier1 about 边 镜像复验 — 只读, 死 API 真数据验.

⚠️ 只读诊断工具 / 非生产路径: 复制到 temp 跑, 绝不 .save 写回真体; 仅 scripts/ 诊断, 非生产链。

真理源: docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md §14 (P0c about 边设计)。

Sir ④: observe_shared_entity 是死了从没生产跑过的 API, 复活后要在真数据镜像上实跑验证
(测试绿 ≠ 生产接线无暗坑)。本脚本 (只读, 复制到 temp 无写回):
  1. 从 inner_thoughts.jsonl 提历史 (thread_id, concern_id) 对 (adjust_concern_notes actionable)
     = "若 Tier1 一直接着, 会建的 about 边" (回填模拟生成期连边)。
  2. 验 thread_id 与 self_threads.json 对应率 (死 API 暗坑: 连到非 harvest 节点?)。
  3. 只对**当前 body 真实存在的 thread 节点**应用 (re-home 现存孤儿, 不造幽灵节点)。
  4. 量平衡尺 (Sir 14.5): largest_frac<0.5 + 面往 4-10 + 桥种类多样 + 孤儿归位 + 反向塌方守卫。

用法: python scripts/manifold_p0c_mirror.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest.mock as mock

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as rm  # noqa: E402
from jarvis_relational_manifold import (  # noqa: E402
    RelationalManifold, make_node_id, split_node_id, KIND_THREAD, KIND_CONCERN,
)
from jarvis_relational_weaver import (  # noqa: E402
    observe_thought_concern_link, RelationalWeaver,
)

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
THOUGHTS = os.path.join(ROOT, "memory_pool", "inner_thoughts.jsonl")
ST = os.path.join(ROOT, "memory_pool", "self_threads.json")
VOCAB = os.path.join(ROOT, "memory_pool", "relational_manifold_vocab.json")


def _cfg():
    c = json.loads(json.dumps(rm._SEED_MANIFOLD_CONFIG))
    try:
        if os.path.exists(VOCAB):
            ov = json.load(open(VOCAB, encoding="utf-8"))
            c = rm._deep_merge(c, ov.get("config", ov))
    except Exception:
        pass
    return c


def _pairs():
    out = []
    if not os.path.exists(THOUGHTS):
        return out
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
                    out.append((tid, cid))
    return list(set(out))


def _measure(m, cfg, label):
    now = time.time()
    with mock.patch.object(rm, "get_manifold_config", return_value=cfg):
        surfaces = m.compute_surfaces(now=now)
        m.set_surfaces(surfaces)
        rep = m.complexity_report(now=now)
        bridges = m.bridge_nodes(surfaces)
        in_surf = set()
        for s in surfaces:
            in_surf.update(s.get("members", ()))
        all_nodes = {m.resolve(n) for n, ks in m._adj.items() if ks}
        sp_kinds = set(cfg.get("self_produced_kinds", ["thread", "joke", "proto"]))
        sp = [n for n in all_nodes if split_node_id(n)[0] in sp_kinds]
        sp_in = [n for n in sp if n in in_surf]
    bridge_concerns = sorted(split_node_id(n)[1][:22] for n in bridges
                             if split_node_id(n)[0] == "concern")
    print(f"\n=== {label} ===")
    print(f"  health={rep['health']}  largest_frac={rep['largest_surface_frac']}  "
          f"surfaces={rep['surface_count']}  bridges={rep['bridge_count']}  nodes={rep['node_count']}")
    print(f"  自产在面: {len(sp_in)}/{len(sp)}  (孤儿 {len(sp) - len(sp_in)})")
    print(f"  桥里 concern 节点 ({len(bridge_concerns)} 种, 看种类是否多样): {bridge_concerns[:10]}")
    return rep, len(sp), len(sp_in), len(bridge_concerns)


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无生产体数据 {SRC})")
        return 0
    pairs = _pairs()
    concerns = set(c for _, c in pairs)
    st = json.load(open(ST, encoding="utf-8")) if os.path.exists(ST) else {}
    stids = set(th.get("thread_id") for th in st.get("threads", []))
    tids = set(t for t, _ in pairs)
    print(f"[P0c Tier1 镜像复验] 只读真数据")
    print(f"  inner_thoughts.jsonl: {len(pairs)} unique (thread,concern) 对, "
          f"{len(concerns)} 个 concern (种类: {sorted(concerns)})")
    print(f"  ⚠️ thread_id ∩ self_threads.json: {len(tids & stids)}/{len(tids)} "
          f"(其余历史 thread 已 aged-out, 连边会造无 harvest-text 节点)")

    tmp = tempfile.mkdtemp(prefix="p0c_mirror_")
    dst = os.path.join(tmp, "m.json")
    shutil.copy(SRC, dst)
    try:
        m = RelationalManifold(dst)
        cfg = _cfg()
        # 当前 body 真实节点 (harvest)
        try:
            harvested = set(RelationalWeaver(manifold=m).harvest_nodes().keys())
        except Exception:
            harvested = set()
        rep0, sp0, spin0, bc0 = _measure(m, cfg, "BEFORE — 真 manifold (无 Tier1 about 边)")
        # 只对当前 body 真实存在的 thread 节点应用 (re-home 现存孤儿, 不造幽灵)
        applied = 0
        skipped_phantom = 0
        for tid, cid in pairs:
            tnode = make_node_id(KIND_THREAD, tid)
            cnode = make_node_id(KIND_CONCERN, cid)
            if tnode not in harvested or cnode not in harvested:
                skipped_phantom += 1
                continue
            if observe_thought_concern_link(tid, cid, manifold=m, save=False):
                applied += 1
        print(f"\n[应用 Tier1] {applied} 条 about 边 (re-home 现存 thread 节点); "
              f"跳过 {skipped_phantom} 条 (thread/concern 节点当前不在 body, 避免造幽灵)")
        rep1, sp1, spin1, bc1 = _measure(m, cfg, "AFTER — +Tier1 about 边 (当前 body)")
        print(f"\n=== 平衡尺 (Sir 14.5 验收) ===")
        print(f"  largest_frac: {rep0['largest_surface_frac']} → {rep1['largest_surface_frac']}  "
              f"(<0.5? 反向守卫: 别塌成 mega-face)")
        print(f"  surfaces: {rep0['surface_count']} → {rep1['surface_count']}  (目标往 4-10 走)")
        print(f"  bridges: {rep0['bridge_count']} → {rep1['bridge_count']}  "
              f"(concern 桥种类: {bc0} → {bc1}, 多样?)")
        print(f"  自产在面: {spin0}/{sp0} → {spin1}/{sp1}  "
              f"(孤儿 {sp0 - spin0} → {sp1 - spin1}, 大幅但非全部归位?)")
        print(f"  health: {rep0['health']} → {rep1['health']}")

        # === 诊断: Tier1 + core_w 0.80 (0.80 单独曾给 2 面 4 桥; about 边是否丰富分化?) ===
        cfg80 = dict(cfg)
        cfg80["surface_core_min_weight"] = 0.80
        _measure(m, cfg80, "诊断 — Tier1 about 边 + core_w 0.80 (vs 0.80 单独 2面4桥)")

        # === 杠杆a 预览诊断 (Sir ④: 分开测各自归因, 这只是诊断不是 commit) ===
        # 削掉 embed-only 边 (模拟杠杆a 减存储密度), 看 Tier1 接地 about scaffold 是否
        # 长出 concern-hub 面。证明 scaffold 是真的, 只是被 over_dense embed 掩盖。
        grounded_kinds = set(cfg.get("surface_grounded_provenance",
                                     ["cooccur", "said", "shared"]))
        with m._lock:
            for key in list(m._edges.keys()):
                e = m._edges[key]
                provs = {p.get("kind") for p in e.get("provenance", [])}
                if not (provs & grounded_kinds):  # embed/inferred-only → 削
                    m._adj[e["a"]].discard(key)
                    m._adj[e["b"]].discard(key)
                    del m._edges[key]
        rep2, sp2, spin2, bc2 = _measure(
            m, cfg, "杠杆a 预览 — Tier1 about 边 + 削 embed-only (诊断, 非 commit)")
        print(f"\n=== 杠杆a 预览归因 ===")
        print(f"  削 embed-only 后 (接地骨架显形): largest_frac={rep2['largest_surface_frac']} "
              f"surfaces={rep2['surface_count']} bridges={rep2['bridge_count']} "
              f"concern 桥种类={bc2} 自产在面={spin2}/{sp2}")
        print(f"  → 若 surfaces 多 + 桥多样 = about scaffold 真的, 只是被 over_dense 掩盖")
        print(f"     ⟹ 实证 Sir 两病分治: Tier1 治没接地, 杠杆a 治过密, 缺一不可")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
