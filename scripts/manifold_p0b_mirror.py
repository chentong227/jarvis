#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0b / Sir 2026-06-03] P0b 镜像复验 — 只读, 无 LLM, 无写回.

真理源: .kiro/specs/body-differentiation/design.md §3.2 (P0b ①②③) + kickoff §11。

把生产体 (memory_pool/relational_manifold.json) **复制到 temp** (绝不写回生产), 在真数据上
跑 P0b ②机器验收三条:
  1. largest_surface_frac < 0.5 (脱 blob)
  2. bridge_count > 0 (有桥不孤岛, 防 thread@0.80 假达标)
  3. 自产节点 (thread/joke/proto) 加权后仍有面归属 (weighted 非 only, 没被抹成孤儿)

对照 ① OFF (sp_w=1.0, 全部边成面) vs ① ON (sp_w=当前 vocab 默 0.5, 接地加权)。
alias-fold (③) 在 compute_surfaces/stats 自动生效 (无需开关)。

用法: python scripts/manifold_p0b_mirror.py
Sir 人读双签: 看下面 top 面 harvest text 对得上主题 + 桥讲得通。
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
from jarvis_relational_manifold import RelationalManifold, split_node_id  # noqa: E402

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
VOCAB = os.path.join(ROOT, "memory_pool", "relational_manifold_vocab.json")


def _base_cfg() -> dict:
    cfg = json.loads(json.dumps(rm._SEED_MANIFOLD_CONFIG))
    try:
        if os.path.exists(VOCAB):
            ov = json.load(open(VOCAB, encoding="utf-8"))
            cfg = rm._deep_merge(cfg, ov.get("config", ov))
    except Exception:
        pass
    return cfg


def _harvest(m):
    try:
        from jarvis_relational_weaver import RelationalWeaver
        return RelationalWeaver(manifold=m).harvest_nodes()
    except Exception:
        return {}


def run(label, dst, sp_weight, show_text=False, core_w=None):
    m = RelationalManifold(dst)
    cfg = _base_cfg()
    cfg["surface_self_produced_embed_weight"] = sp_weight
    if core_w is not None:
        cfg["surface_core_min_weight"] = core_w
    sp_kinds = set(cfg.get("self_produced_kinds", ["thread", "joke", "proto"]))
    now = time.time()
    with mock.patch.object(rm, "get_manifold_config", return_value=cfg):
        surfaces = m.compute_surfaces(now=now)
        m.set_surfaces(surfaces)
        rep = m.complexity_report(now=now)
        bridges = m.bridge_nodes(surfaces)
        members = set()
        for s in surfaces:
            members.update(s.get("members", ()))
        sp_nodes = set()
        for n, ks in m._adj.items():
            if ks:
                rn = m.resolve(n)
                if split_node_id(rn)[0] in sp_kinds:
                    sp_nodes.add(rn)
        sp_in = len(sp_nodes & members)
        sp_total = len(sp_nodes)
        text = _harvest(m) if show_text else {}
    print(f"\n=== {label}  (surface_self_produced_embed_weight={sp_weight}) ===")
    print(f"  health={rep['health']}  largest_surface_frac={rep['largest_surface_frac']}  "
          f"complexity_score={rep['complexity_score']}")
    print(f"  surfaces={rep['surface_count']}  bridges={rep['bridge_count']}  "
          f"nodes={rep['node_count']}  edges(physical)={rep['edge_count']}  "
          f"merged_dups={rep['merged_dups']}")
    print(f"  自产节点面归属 (②.3): {sp_in}/{sp_total} thread/joke/proto 仍在面 "
          f"({'OK 没成孤儿' if sp_total and sp_in else '⚠️ 检查'})")
    accept = (rep['largest_surface_frac'] < 0.5 and rep['bridge_count'] > 0
              and sp_total and sp_in >= 1)
    if sp_weight < 1.0:
        print(f"  ②三条机器验收: largest_frac<0.5={rep['largest_surface_frac']<0.5} "
              f"bridge>0={rep['bridge_count']>0} 自产仍在面={bool(sp_total and sp_in)} "
              f"→ {'✅ 机器侧达标 (待 Sir 人读双签)' if accept else '❌ 未达标'}")
    if show_text and surfaces:
        print("  --- top 5 面 (Sir 人读: 对得上主题?) ---")
        for s in surfaces[:5]:
            kinds = s.get("kinds", {})
            print(f"  ● {s['surface_id']} size={s['size']} kinds={kinds}")
            for nid in s.get("top_nodes", [])[:4]:
                tag = " 🌉" if nid in bridges else ""
                print(f"      · {nid[:42]}{tag}  {(text.get(nid) or '')[:60]}")
        if bridges:
            print("  --- 桥 (Sir 人读: 讲得通?) ---")
            for nid, sids in list(sorted(bridges.items(), key=lambda x: -len(x[1])))[:8]:
                print(f"  🌉 {nid[:42]} 属{len(sids)}面  {(text.get(nid) or '')[:60]}")
    return rep, accept


def sweep_core(dst):
    """core_min_weight 轻调 sweep: 看分多面 + 出桥是否靠调阈可达 (②.2)。只读。"""
    print("\n=== core_min_weight sweep (① ON 0.5, 看分面+出桥) ===")
    print(f"  {'core_w':>7} {'surfaces':>9} {'largest_frac':>13} {'bridges':>8} {'health':>14}")
    for cw in (0.60, 0.80, 1.00, 1.20, 1.50, 2.00):
        m = RelationalManifold(dst)
        cfg = _base_cfg()
        cfg["surface_self_produced_embed_weight"] = 0.5
        cfg["surface_core_min_weight"] = cw
        now = time.time()
        with mock.patch.object(rm, "get_manifold_config", return_value=cfg):
            surfaces = m.compute_surfaces(now=now)
            m.set_surfaces(surfaces)
            rep = m.complexity_report(now=now)
        print(f"  {cw:>7.2f} {rep['surface_count']:>9} "
              f"{rep['largest_surface_frac']:>13} {rep['bridge_count']:>8} "
              f"{rep['health']:>14}")


def signoff(dst, core_w):
    """Sir 人读双签材料 (查i 内心去向 / 查ii 桥单一性) — 只读。"""
    import collections
    m = RelationalManifold(dst)
    cfg = _base_cfg()
    cfg["surface_self_produced_embed_weight"] = 0.5
    cfg["surface_core_min_weight"] = core_w
    sp_kinds = set(cfg.get("self_produced_kinds", ["thread", "joke", "proto"]))
    now = time.time()
    with mock.patch.object(rm, "get_manifold_config", return_value=cfg):
        surfaces = m.compute_surfaces(now=now)
        m.set_surfaces(surfaces)
        rep = m.complexity_report(now=now)
        bridges = m.bridge_nodes(surfaces)
        text = _harvest(m)
        in_surf = set()
        for s in surfaces:
            in_surf.update(s.get("members", ()))
        all_nodes = {m.resolve(n) for n, ks in m._adj.items() if ks}
        orphan = all_nodes - in_surf
    print(f"\n########## 人读双签材料 (core_w={core_w}) ##########")
    print(f"  surfaces={rep['surface_count']} largest_frac={rep['largest_surface_frac']} "
          f"bridges={rep['bridge_count']} nodes={rep['node_count']} health={rep['health']}")
    for s in surfaces:
        print(f"\n  ● 面 {s['surface_id']}  size={s['size']}  kinds={s.get('kinds', {})}")
        for nid in s.get("members", []):
            tag = " 🌉" if nid in bridges else ""
            print(f"      {nid[:46]}{tag}  {(text.get(nid) or '')[:52]}")
    print(f"\n  --- 桥 {len(bridges)} 个 (查ii: 是否只有'补水'一类? 看种类不看数量) ---")
    for nid, sids in sorted(bridges.items(), key=lambda x: -len(x[1])):
        print(f"  🌉 {nid[:46]} 属{len(sids)}面  {(text.get(nid) or '')[:58]}")
    in_kinds = collections.Counter(split_node_id(n)[0] for n in in_surf)
    orphan_kinds = collections.Counter(split_node_id(n)[0] for n in orphan)
    print(f"\n  --- 孤儿分析 (查i: 内心还在结构里吗?) ---")
    print(f"  在面: {dict(in_kinds)} (共 {len(in_surf)})")
    print(f"  没进任何面 (仍在图有边, 未成面): {dict(orphan_kinds)} (共 {len(orphan)})")
    sp_orphan = sorted(n for n in orphan if split_node_id(n)[0] in sp_kinds)
    print(f"  自产孤儿 (thread/joke/proto 没进面) 共 {len(sp_orphan)}, 抽 8:")
    for nid in sp_orphan[:8]:
        print(f"      {nid[:46]}  {(text.get(nid) or '')[:52]}")


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无生产体数据 {SRC} — 跳过镜像复验)")
        return 0
    tmp = tempfile.mkdtemp(prefix="p0b_mirror_")
    dst = os.path.join(tmp, "m.json")
    shutil.copy(SRC, dst)   # 只读: 复制到 temp, 绝不写回生产
    try:
        print(f"[P0b 镜像复验] 只读沙盒 {dst} (源 {SRC}, {os.path.getsize(SRC)} bytes)")
        run("① OFF — baseline 全部边成面 (思考相似糊团)", dst, 1.0)
        run("① ON — 接地加权成面 (面围真实共现长)", dst, 0.5, show_text=True)
        sweep_core(dst)
        signoff(dst, 0.80)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
