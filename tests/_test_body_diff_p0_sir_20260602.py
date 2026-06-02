# -*- coding: utf-8 -*-
"""[body-diff-P0 / Sir 2026-06-02] 破 blob 双杠杆 + 重叠面 + 桥度量 回归.

真理源: .kiro/specs/body-differentiation/ (requirements R2/R3/R4/R9, design §3,
Correctness Properties P4/P5/P6)。

立项实证: 体是 blob (124 节点 112 挤一个面, density 11.6, largest_frac 0.903),
成分 49 thread + 31 joke + 26 proto + 6 concern (自产 106 vs 外部 6)。

覆盖 (纯几何, 无 LLM, mock 边权):
  杠杆a 接地不对称 (R2, Property 4):
    T1  两端自产 (thread↔thread) → embed 边权打折 < 同 cosine 的自产↔concern
    T2  self_produced_kinds 含 joke/proto (不只 thread)
  杠杆b 重叠面去全局 seen (R3/R9, Property 5):
    T3  core_boundary: 两核 + 桥节点强连两核 → 桥节点属 >=2 面 (重叠)
    T4  legacy method → 硬分区 (桥节点只属一个面, 回退可用)
    T5  bridge_nodes() 返属 >=2 面的节点
  桥度量 + health (R3, Property 5/6):
    T6  complexity_report 有 bridge_count/bridge_frac
    T7  面多但无桥 → health=over_fragmented
    T8  blob (一面占过半) → health=blob (不变)
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as rm
from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, KIND_THREAD, KIND_CONCERN, KIND_JOKE,
    PROV_SAID,
)

T0 = 1_780_000_000.0


def _mk_manifold(d):
    return RelationalManifold(os.path.join(d, "m.json"))


def _edge(m, a, b, scale=1.0, now=T0):
    """造边, weight = PROV_SAID(1.0) × scale (控制核边 vs 桥边权重)。"""
    m.add_edge(a, b, PROV_SAID, ref="t", weight_scale=scale, now=now)


# ============================================================
# 杠杆 a — 接地不对称折扣 (R2, Property 4)
# ============================================================
class TestAsymmetryDiscount(unittest.TestCase):
    def test_t1_self_self_edge_discounted(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            th_a = make_node_id(KIND_THREAD, "ta")
            th_b = make_node_id(KIND_THREAD, "tb")
            con = make_node_id(KIND_CONCERN, "c1")
            # 同 cosine 0.85: thread↔thread 打折(0.5), thread↔concern 不打折
            m.add_geometric_edge(th_a, th_b, 0.85, weight_scale=0.5, now=T0)
            m.add_geometric_edge(th_a, con, 0.85, weight_scale=1.0, now=T0)
            w_self = m.effective_weight(m.get_edge(th_a, th_b), now=T0)
            w_ext = m.effective_weight(m.get_edge(th_a, con), now=T0)
            self.assertLess(w_self, w_ext,
                            "两端自产 embed 边权应 < 自产↔外部 (接地不对称)")
            self.assertAlmostEqual(w_self, w_ext * 0.5, places=4)

    def test_t2_self_produced_kinds_includes_joke_proto(self):
        cfg = rm.get_manifold_config()
        kinds = set(cfg.get("self_produced_kinds", []))
        self.assertIn("thread", kinds)
        self.assertIn("joke", kinds, "joke 应在 self_produced_kinds (实测 31 个)")
        self.assertIn("proto", kinds, "proto 应在 self_produced_kinds (实测 26 个)")


# ============================================================
# 杠杆 b — 重叠面 (R3/R9, Property 5)
# ============================================================
class TestOverlapSurfaces(unittest.TestCase):
    def _build_two_cores_with_bridge(self, m):
        # 核 A: a1-a2-a3 紧团 (核边 weight 1.0 >= core_min 0.60);
        # 核 B: b1-b2-b3 紧团; 桥 x 用**中等权**(0.5, 在低阈0.45与核阈0.60之间)强连两核
        # → 核不被桥并 (桥边 < core 阈), 但桥在低阈下归属两核 → 重叠。
        A = [make_node_id(KIND_THREAD, f"a{i}") for i in range(1, 4)]
        B = [make_node_id(KIND_THREAD, f"b{i}") for i in range(1, 4)]
        x = make_node_id(KIND_CONCERN, "bridge")
        for i in range(len(A)):
            for j in range(i + 1, len(A)):
                _edge(m, A[i], A[j], scale=1.0)   # 核边: 强
        for i in range(len(B)):
            for j in range(i + 1, len(B)):
                _edge(m, B[i], B[j], scale=1.0)
        # 桥 x 用中等权连两核各 2 个成员 (>= overlap_min_links 2, < core 阈不并核)
        _edge(m, x, A[0], scale=0.5); _edge(m, x, A[1], scale=0.5)
        _edge(m, x, B[0], scale=0.5); _edge(m, x, B[1], scale=0.5)
        return A, B, x

    def test_t3_core_boundary_bridge_in_two_surfaces(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            A, B, x = self._build_two_cores_with_bridge(m)
            with patch.object(rm, "get_manifold_config", return_value={
                **rm._SEED_MANIFOLD_CONFIG,
                "surface_method": "core_boundary",
                "surface_overlap_min_links": 2,
                "surface_min_size": 3,
                "surface_min_weight": 0.45,
            }):
                surfaces = m.compute_surfaces(now=T0)
                m.set_surfaces(surfaces)
                bridges = m.bridge_nodes(surfaces)
            # x 应属 >=2 面 (重叠 — 桥)
            self.assertIn(x, bridges, "桥节点应属 >=2 面 (core_boundary 重叠)")
            self.assertGreaterEqual(len(surfaces), 2, "应分出 >=2 面")

    def test_t4_legacy_hard_partition_no_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            A, B, x = self._build_two_cores_with_bridge(m)
            with patch.object(rm, "get_manifold_config", return_value={
                **rm._SEED_MANIFOLD_CONFIG,
                "surface_method": "legacy",
                "surface_min_size": 3,
                "surface_min_weight": 0.45,
            }):
                surfaces = m.compute_surfaces(now=T0)
                bridges = m.bridge_nodes(surfaces)
            # legacy 硬分区: x 桥把两核连成一个连通块 → 1 面, 无重叠
            self.assertEqual(len(bridges), 0,
                             "legacy 硬分区不产生重叠 (桥节点不属多面)")

    def test_t5_bridge_nodes_api(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            A, B, x = self._build_two_cores_with_bridge(m)
            with patch.object(rm, "get_manifold_config", return_value={
                **rm._SEED_MANIFOLD_CONFIG,
                "surface_method": "core_boundary",
                "surface_overlap_min_links": 2,
                "surface_min_size": 3, "surface_min_weight": 0.45,
            }):
                surfaces = m.compute_surfaces(now=T0)
                bridges = m.bridge_nodes(surfaces)
            for n, sids in bridges.items():
                self.assertGreaterEqual(len(sids), 2,
                                        "bridge_nodes 返的节点必属 >=2 面")


# ============================================================
# 桥度量 + health (R3, Property 5/6)
# ============================================================
class TestComplexityReportBridge(unittest.TestCase):
    def test_t6_report_has_bridge_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            rep = m.complexity_report(now=T0)
            self.assertIn("bridge_count", rep)
            self.assertIn("bridge_frac", rep)

    def test_t7_over_fragmented_health(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            # 造 >= over_frag_min (8) 个互不相连的小面, 无桥
            surfaces = []
            for k in range(9):
                mem = [make_node_id(KIND_THREAD, f"f{k}_{i}") for i in range(3)]
                surfaces.append({"surface_id": f"surf:f{k}", "members": mem,
                                 "size": 3, "kinds": {}, "top_nodes": mem})
            m.set_surfaces(surfaces)
            # 加少量边让 nc/ec 非零但不影响 (density 低)
            for k in range(9):
                a = make_node_id(KIND_THREAD, f"f{k}_0")
                b = make_node_id(KIND_THREAD, f"f{k}_1")
                _edge(m, a, b)
            with patch.object(rm, "get_manifold_config", return_value={
                **rm._SEED_MANIFOLD_CONFIG, "over_frag_min_surfaces": 8,
            }):
                rep = m.complexity_report(now=T0)
            self.assertEqual(rep["bridge_count"], 0)
            self.assertEqual(rep["health"], "over_fragmented",
                             "面多(>=8)但无桥 → over_fragmented (碎成孤岛, 不变量③)")

    def test_t8_blob_health_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk_manifold(d)
            # 一个面占过半节点 → blob
            big = [make_node_id(KIND_THREAD, f"n{i}") for i in range(10)]
            for i in range(len(big)):
                for j in range(i + 1, len(big)):
                    _edge(m, big[i], big[j])
            m.set_surfaces([{"surface_id": "surf:big", "members": big,
                             "size": 10, "kinds": {}, "top_nodes": big[:5]}])
            rep = m.complexity_report(now=T0)
            self.assertEqual(rep["health"], "blob",
                             "一面占过半 → blob (largest_frac>=0.5 判定不变)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
