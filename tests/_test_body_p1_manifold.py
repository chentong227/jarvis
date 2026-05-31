# -*- coding: utf-8 -*-
"""[体-P1 / 2026-05-31] Relational Manifold 边层 testcase.

体 (Body) 三位一体第三器官的最底层地基: 交叉引用图 (边层)。
详 docs/JARVIS_TRINITY_ARCHITECTURE.md §3/§9.

覆盖 (接地红线 = 言出必行):
  T1  make/split node_id 往返 + 非法拒绝
  T2  **接地红线**: 无 ref 的边被拒 (幻觉防线)
  T3  add_edge 造边 + weight=increment + provenance 带 kind/ref
  T4  observe_cooccurrence 两两造边 (C(n,2)); <2 节点 = 0
  T5  Hebbian: 重复 observe 累加 weight + reinforce_count; 同(kind,ref) provenance dedup
  T6  weight cap 封顶
  T7  said 边 (Sir 显式连接) 强于 cooccur
  T8  shared 实体两两造边
  T9  时间衰减: effective_weight 半衰期减半; apply_decay 写回
  T10 prune 删低于 floor 的边
  T11 neighbors 按权降序 + min_weight 过滤 + degree
  T12 spread (spreading-activation) 逐跳衰减 + 未连通节点不点亮
  T13 持久化往返: save → reload 保边 + 邻接 + neighbors
  T14 inferred 边 (LLM propose-not-trust): 标 review + confidence 缩放 + 无 turn_id 拒
  T15 stats edges_by_kind 计数
"""
from __future__ import annotations

import os
import sys
import math
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, split_node_id,
    get_manifold_config,
    KIND_THREAD, KIND_CONCERN, KIND_JOKE,
    PROV_COOCCUR, PROV_SAID, PROV_SHARED, PROV_INFERRED,
)

T0 = 1_780_000_000.0  # 固定基准时间 → weight 断言确定 (无隐式衰减)


def _mk(tmpdir: str) -> RelationalManifold:
    return RelationalManifold(os.path.join(tmpdir, "manifold.json"))


def _node(kind: str, raw: str) -> str:
    return make_node_id(kind, raw)


class TestNodeId(unittest.TestCase):
    def test_t1_node_id_roundtrip_and_reject(self):
        nid = make_node_id(KIND_THREAD, "thought_20260530_1")
        self.assertEqual(nid, "thread:thought_20260530_1")
        self.assertEqual(split_node_id(nid), (KIND_THREAD, "thought_20260530_1"))
        with self.assertRaises(ValueError):
            make_node_id("", "x")
        with self.assertRaises(ValueError):
            make_node_id(KIND_THREAD, "")


class TestGrounding(unittest.TestCase):
    def test_t2_reject_ungrounded_edge(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_CONCERN, "c1"), _node(KIND_THREAD, "t1")
            # 无 ref = 幻觉 → 拒
            self.assertIsNone(m.add_edge(a, b, PROV_COOCCUR, "", now=T0))
            self.assertEqual(m.stats()["edge_count"], 0)
            # 自环拒
            self.assertIsNone(m.add_edge(a, a, PROV_COOCCUR, "turn_x", now=T0))

    def test_t3_add_edge_basic(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_CONCERN, "c1"), _node(KIND_THREAD, "t1")
            key = m.add_edge(a, b, PROV_COOCCUR, "turn_1", now=T0)
            self.assertIsNotNone(key)
            e = m.get_edge(a, b)
            self.assertAlmostEqual(e["weight"], 0.30, places=4)
            self.assertEqual(e["reinforce_count"], 1)
            self.assertEqual(len(e["provenance"]), 1)
            self.assertEqual(e["provenance"][0]["kind"], PROV_COOCCUR)
            self.assertEqual(e["provenance"][0]["ref"], "turn_1")
            # 无向: 反向查同一条边
            self.assertIs(m.get_edge(b, a), e)


class TestObservers(unittest.TestCase):
    def test_t4_cooccurrence_pairwise(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            nodes = [_node(KIND_THREAD, f"t{i}") for i in range(3)]
            n = m.observe_cooccurrence(nodes, "turn_2", now=T0)
            self.assertEqual(n, 3)  # C(3,2)
            self.assertEqual(m.stats()["edge_count"], 3)
            # <2 节点 → 0
            self.assertEqual(m.observe_cooccurrence([nodes[0]], "turn_3", now=T0), 0)
            # 无 turn_id → 0
            self.assertEqual(m.observe_cooccurrence(nodes, "", now=T0), 0)

    def test_t5_hebbian_reinforce_and_provenance_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_THREAD, "t2")
            m.add_edge(a, b, PROV_COOCCUR, "turn_1", now=T0)
            m.add_edge(a, b, PROV_COOCCUR, "turn_1", now=T0)  # 同 ref
            e = m.get_edge(a, b)
            # weight 累加 (无衰减 now 固定): 0.3 + 0.3
            self.assertAlmostEqual(e["weight"], 0.60, places=4)
            self.assertEqual(e["reinforce_count"], 2)
            # 同 (kind, ref) → provenance 不重复堆, count 累加
            self.assertEqual(len(e["provenance"]), 1)
            self.assertEqual(e["provenance"][0]["count"], 2)
            # 不同 ref → 新 provenance
            m.add_edge(a, b, PROV_COOCCUR, "turn_2", now=T0)
            self.assertEqual(len(m.get_edge(a, b)["provenance"]), 2)

    def test_t6_weight_cap(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_THREAD, "t2")
            cap = float(get_manifold_config()["weight_cap"])
            for i in range(100):
                m.add_edge(a, b, PROV_SAID, f"turn_{i}", now=T0)
            self.assertLessEqual(m.get_edge(a, b)["weight"], cap + 1e-6)
            self.assertAlmostEqual(m.get_edge(a, b)["weight"], cap, places=4)

    def test_t7_said_stronger_than_cooccur(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_THREAD, "t2")
            c = _node(KIND_THREAD, "t3")
            m.observe_explicit_link(a, b, "turn_1", now=T0)
            m.observe_cooccurrence([a, c], "turn_1", now=T0)
            self.assertGreater(m.get_edge(a, b)["weight"], m.get_edge(a, c)["weight"])
            self.assertAlmostEqual(m.get_edge(a, b)["weight"], 1.00, places=4)

    def test_t8_shared_entity(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            nodes = [_node(KIND_JOKE, f"j{i}") for i in range(3)]
            n = m.observe_shared_entity(nodes, "concern:sir_sleep", now=T0)
            self.assertEqual(n, 3)
            e = m.get_edge(nodes[0], nodes[1])
            self.assertAlmostEqual(e["weight"], 0.50, places=4)
            self.assertEqual(e["provenance"][0]["kind"], PROV_SHARED)
            self.assertEqual(e["provenance"][0]["ref"], "concern:sir_sleep")


class TestDecayPrune(unittest.TestCase):
    def test_t9_decay_halflife(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_THREAD, "t2")
            m.add_edge(a, b, PROV_SAID, "turn_1", now=T0)  # weight 1.0
            e = m.get_edge(a, b)
            hl = float(get_manifold_config()["half_life_days"]) * 86400.0
            # 半衰期后 effective ≈ 0.5
            self.assertAlmostEqual(m.effective_weight(e, T0 + hl), 0.5, places=3)
            # apply_decay 写回
            m.apply_decay(now=T0 + hl)
            self.assertAlmostEqual(m.get_edge(a, b)["weight"], 0.5, places=3)

    def test_t10_prune_below_floor(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_THREAD, "t2")
            m.add_edge(a, b, PROV_COOCCUR, "turn_1", now=T0)  # 0.30
            hl = float(get_manifold_config()["half_life_days"]) * 86400.0
            # 3 个半衰期: 0.30 * 0.125 = 0.0375 < floor 0.05
            removed = m.prune(now=T0 + 3 * hl)
            self.assertEqual(removed, 1)
            self.assertEqual(m.stats()["edge_count"], 0)
            self.assertEqual(m.degree(a), 0)


class TestQueries(unittest.TestCase):
    def test_t11_neighbors_and_degree(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            hub = _node(KIND_CONCERN, "hub")
            strong = _node(KIND_THREAD, "strong")
            weak = _node(KIND_THREAD, "weak")
            m.observe_explicit_link(hub, strong, "turn_1", now=T0)   # 1.0
            m.observe_cooccurrence([hub, weak], "turn_1", now=T0)    # 0.3
            self.assertEqual(m.degree(hub), 2)
            nbrs = m.neighbors(hub, now=T0)
            self.assertEqual([n for n, _ in nbrs], [strong, weak])  # 降序
            # min_weight 过滤掉 weak
            filtered = m.neighbors(hub, min_weight=0.5, now=T0)
            self.assertEqual([n for n, _ in filtered], [strong])

    def test_t12_spread_activation(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            seed = _node(KIND_CONCERN, "seed")
            a = _node(KIND_THREAD, "a")
            b = _node(KIND_THREAD, "b")
            far = _node(KIND_THREAD, "far")  # 不连通
            m.observe_explicit_link(seed, a, "turn_1", now=T0)
            m.observe_explicit_link(a, b, "turn_1", now=T0)
            act = m.spread([seed], hops=2, now=T0)
            self.assertEqual(act[seed], 1.0)
            self.assertIn(a, act)
            self.assertIn(b, act)
            self.assertGreater(act[a], act[b])   # 越远越弱
            self.assertNotIn(far, act)            # 未连通不点亮


class TestSurfaces(unittest.TestCase):
    def _cluster(self, m, nodes, now):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                m.observe_explicit_link(nodes[i], nodes[j], "turn_1", now=now)  # said=1.0

    def test_surfaces_two_clusters(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            ca = [_node(KIND_JOKE, f"a{i}") for i in range(3)]
            cb = [_node(KIND_CONCERN, f"b{i}") for i in range(3)]
            self._cluster(m, ca, T0)
            self._cluster(m, cb, T0)
            # 弱桥 (cooccur 0.30 < surface_min_weight 0.45) → 不合并两簇
            m.observe_cooccurrence([ca[0], cb[0]], "turn_2", now=T0)
            surfaces = m.compute_surfaces(now=T0)
            self.assertEqual(len(surfaces), 2)
            self.assertTrue(all(s["size"] == 3 for s in surfaces))

    def test_surface_min_size_and_membership(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            ca = [_node(KIND_JOKE, f"a{i}") for i in range(3)]
            self._cluster(m, ca, T0)
            # 一对孤立强边 (size 2 < min_size 3) → 不成面
            x, y = _node(KIND_THREAD, "x"), _node(KIND_THREAD, "y")
            m.observe_explicit_link(x, y, "turn_1", now=T0)
            surfaces = m.compute_surfaces(now=T0, min_size=3)
            self.assertEqual(len(surfaces), 1)
            self.assertEqual(surfaces[0]["size"], 3)
            # set/get + surface_of
            m.set_surfaces(surfaces)
            self.assertEqual(len(m.get_surfaces()), 1)
            self.assertIsNotNone(m.surface_of(ca[0]))
            self.assertIsNone(m.surface_of(x))


class TestComplexity(unittest.TestCase):
    def _cluster(self, m, nodes, now):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                m.observe_explicit_link(nodes[i], nodes[j], "t1", now=now)

    def test_blob_detected(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            big = [_node(KIND_JOKE, f"b{i}") for i in range(6)]
            small = [_node(KIND_CONCERN, f"s{i}") for i in range(3)]
            self._cluster(m, big, T0)
            self._cluster(m, small, T0)
            m.set_surfaces(m.compute_surfaces(now=T0))
            r = m.complexity_report(now=T0)
            self.assertEqual(r["health"], "blob")          # 大簇吃过半 = 低复杂度
            self.assertGreater(r["largest_surface_frac"], 0.5)

    def test_healthy_balanced(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            for c in range(3):
                self._cluster(m, [_node(KIND_THREAD, f"c{c}_{i}") for i in range(3)], T0)
            m.set_surfaces(m.compute_surfaces(now=T0))
            r = m.complexity_report(now=T0)
            self.assertEqual(r["health"], "healthy")
            self.assertLess(r["largest_surface_frac"], 0.5)

    def test_grounded_frac_drops_with_inferred(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b, c = (_node(KIND_THREAD, "a"), _node(KIND_THREAD, "b"),
                       _node(KIND_THREAD, "c"))
            self._cluster(m, [a, b, c], T0)
            m.add_inferred_edge(a, _node(KIND_THREAD, "x"), "t1", 0.5, "guess", now=T0)
            r = m.complexity_report(now=T0)
            self.assertLess(r["grounded_frac"], 1.0)


class TestPersistence(unittest.TestCase):
    def test_t13_save_reload_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "manifold.json")
            m1 = RelationalManifold(path)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_CONCERN, "c1")
            m1.observe_explicit_link(a, b, "turn_1", now=T0)
            m1.save()
            self.assertTrue(os.path.exists(path))
            m2 = RelationalManifold(path)
            self.assertEqual(m2.stats()["edge_count"], 1)
            self.assertEqual(m2.degree(a), 1)
            nbrs = m2.neighbors(a, now=T0)
            self.assertEqual(nbrs[0][0], b)
            self.assertAlmostEqual(m2.get_edge(a, b)["weight"], 1.0, places=4)


class TestInferred(unittest.TestCase):
    def test_t14_inferred_edge_review_and_confidence(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b = _node(KIND_THREAD, "t1"), _node(KIND_CONCERN, "c1")
            key = m.add_inferred_edge(a, b, "turn_1", confidence=0.5,
                                      rationale="LLM 觉得这俩因果相关", now=T0)
            self.assertIsNotNone(key)
            e = m.get_edge(a, b)
            self.assertTrue(e["review"])
            # weight = inferred increment(0.40) * confidence(0.5) = 0.20
            self.assertAlmostEqual(e["weight"], 0.20, places=4)
            p = e["provenance"][0]
            self.assertEqual(p["kind"], PROV_INFERRED)
            self.assertTrue(p["inferred"])
            self.assertAlmostEqual(p["confidence"], 0.5, places=3)
            self.assertEqual(m.stats()["review_count"], 1)
            # 无 turn_id → 拒 (LLM 推断也必须接地)
            self.assertIsNone(
                m.add_inferred_edge(a, b, "", confidence=0.9, rationale="x", now=T0))

    def test_t15_stats_by_kind(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            a, b, c = (_node(KIND_THREAD, "a"), _node(KIND_THREAD, "b"),
                       _node(KIND_CONCERN, "c"))
            m.observe_cooccurrence([a, b], "turn_1", now=T0)
            m.observe_explicit_link(a, c, "turn_2", now=T0)
            s = m.stats(now=T0)
            self.assertEqual(s["edge_count"], 2)
            self.assertEqual(s["edges_by_kind"].get(PROV_COOCCUR), 1)
            self.assertEqual(s["edges_by_kind"].get(PROV_SAID), 1)
            self.assertEqual(s["node_count"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
