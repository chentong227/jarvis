# -*- coding: utf-8 -*-
"""[body-diff-P0b-③ / Sir 2026-06-03] alias-fold 接进 compute_surfaces/stats/complexity_report.

真理源: .kiro/specs/body-differentiation/design.md §3.2 (P0b route 改判) + kickoff §11。

== 修的真 bug (发现 A) ==
add_alias(dup, rep) 只写 self._aliases, 但 compute_surfaces / stats / complexity_report
旧码全程用原始 e["a"]/e["b"] **从不 resolve()** → 已有合并 (merge_threshold=0.93) 是纯记账
(merged_dups 计数), dup 节点 + 它的边照常成面 → largest_frac 不动 = "光降合并阈零效果"根因。

== Sir ③ 约束 ==
alias-fold 是独立正确性修复, **merge_threshold 不动, 不复活"降自产合并阈"** (T5 红线守).
无 alias 时折叠必须与旧行为完全等价 (T3 回归守卫)。

覆盖 (纯几何, 无 LLM, tmp 隔离):
  T1  stats alias-fold: dup→rep 后 node_count/edge_count 折叠去重 + 自环丢弃
  T2  compute_surfaces alias-fold: dup 折进 rep, 面 members 含 rep 不含 dup, size 缩
  T3  无 alias 等价 (回归守卫): stats 折叠 == 原始 len(edges)/distinct nodes
  T4  complexity_report 跟随折叠: merge 后 node_count 真降 (修前=零效果)
  T5  Sir ③ 红线: seed merge_threshold/auto_merge_dups.threshold 不动 (不复活降阈)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as rm
from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, KIND_THREAD, KIND_CONCERN, PROV_SAID,
)

T0 = 1_780_000_000.0


def _mk(d):
    return RelationalManifold(os.path.join(d, "m.json"))


def _edge(m, a, b, scale=1.0, now=T0):
    m.add_edge(a, b, PROV_SAID, ref="t", weight_scale=scale, now=now)


_CORE_CFG = {
    "surface_method": "core_boundary",
    "surface_overlap_min_links": 2,
    "surface_min_size": 3,
    "surface_min_weight": 0.45,
    "surface_core_min_weight": 0.60,
}


class TestStatsAliasFold(unittest.TestCase):
    def test_t1_stats_node_count_folds_dup_into_rep(self):
        """node_count 按 resolve 折叠 (largest_frac 分母真降); edge_count 保持物理计数."""
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            rep = make_node_id(KIND_THREAD, "rep")
            dup = make_node_id(KIND_THREAD, "dup")
            other = make_node_id(KIND_CONCERN, "other")
            _edge(m, rep, other)     # rep~other
            _edge(m, dup, other)     # dup~other
            _edge(m, dup, rep)       # dup~rep
            s0 = m.stats(now=T0)
            self.assertEqual(s0["node_count"], 3, "合并前 distinct 3 节点")
            self.assertEqual(s0["edge_count"], 3, "合并前 3 物理边")
            # 合并 dup → rep
            self.assertTrue(m.add_alias(dup, rep))
            s1 = m.stats(now=T0)
            # node_count 折叠: {resolve(rep)=rep, resolve(dup)=rep, resolve(other)} = {rep, other} = 2
            self.assertEqual(s1["node_count"], 2, "折叠后 dup 并入 rep → distinct 2 节点")
            # edge_count 保持物理 (alias 可逆不删源, 物理边仍在; introspection/持久化语义不变)
            self.assertEqual(s1["edge_count"], 3, "edge_count 保持物理计数 (不随 alias 折叠)")


class TestSurfaceAliasFold(unittest.TestCase):
    def test_t2_compute_surfaces_folds_dup(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            rep = make_node_id(KIND_THREAD, "rep")
            n2 = make_node_id(KIND_THREAD, "n2")
            n3 = make_node_id(KIND_THREAD, "n3")
            dup = make_node_id(KIND_THREAD, "dup")
            # 单核紧团: rep-n2-n3-dup 两两核边 (weight 1.0 >= core 0.60)
            for a, b in [(rep, n2), (rep, n3), (n2, n3), (dup, n2), (dup, n3)]:
                _edge(m, a, b)
            with patch.object(rm, "get_manifold_config",
                              return_value={**rm._SEED_MANIFOLD_CONFIG, **_CORE_CFG}):
                s0 = m.compute_surfaces(now=T0)
                self.assertEqual(s0[0]["size"], 4, "合并前面含 4 节点 (含 dup)")
                self.assertIn(dup, s0[0]["members"])
                # 合并 dup → rep
                self.assertTrue(m.add_alias(dup, rep))
                s1 = m.compute_surfaces(now=T0)
            self.assertEqual(s1[0]["size"], 3, "折叠后 dup 并入 rep → 面 3 节点")
            self.assertNotIn(dup, s1[0]["members"], "dup 不再单独成面成员")
            self.assertIn(rep, s1[0]["members"])


class TestNoAliasEquivalence(unittest.TestCase):
    def test_t3_fold_is_identity_without_alias(self):
        """回归守卫: 无 alias 时折叠后的 stats 必须等于原始计数 (不破老行为)。"""
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            nodes = [make_node_id(KIND_THREAD, f"n{i}") for i in range(5)]
            con = make_node_id(KIND_CONCERN, "c")
            _edge(m, nodes[0], nodes[1])
            _edge(m, nodes[1], nodes[2])
            _edge(m, nodes[2], con)
            _edge(m, nodes[3], nodes[4])
            s = m.stats(now=T0)
            raw_edges = m.all_edges()
            raw_nodes = {n for e in raw_edges for n in (e["a"], e["b"])}
            self.assertEqual(s["edge_count"], len(raw_edges),
                             "无 alias → edge_count == 原始边数")
            self.assertEqual(s["node_count"], len(raw_nodes),
                             "无 alias → node_count == 原始 distinct 节点数")


class TestComplexityFollowsFold(unittest.TestCase):
    def test_t4_complexity_node_count_drops_after_merge(self):
        """修前: add_alias 对 complexity_report 零效果 (bug)。修后: node_count 真降。"""
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            rep = make_node_id(KIND_THREAD, "rep")
            n2 = make_node_id(KIND_THREAD, "n2")
            n3 = make_node_id(KIND_THREAD, "n3")
            dup = make_node_id(KIND_THREAD, "dup")
            for a, b in [(rep, n2), (rep, n3), (n2, n3), (dup, n2), (dup, n3)]:
                _edge(m, a, b)
            with patch.object(rm, "get_manifold_config",
                              return_value={**rm._SEED_MANIFOLD_CONFIG, **_CORE_CFG}):
                m.set_surfaces(m.compute_surfaces(now=T0))
                rep0 = m.complexity_report(now=T0)
                self.assertTrue(m.add_alias(dup, rep))
                m.set_surfaces(m.compute_surfaces(now=T0))
                rep1 = m.complexity_report(now=T0)
            self.assertEqual(rep1["node_count"], rep0["node_count"] - 1,
                             "merge 后 node_count 真降 1 (修前为零效果)")
            self.assertEqual(rep1["merged_dups"], 1)
            self.assertLessEqual(rep1["largest_surface_frac"],
                                 rep0["largest_surface_frac"])


class TestMergeThresholdRedLine(unittest.TestCase):
    def test_t5_merge_threshold_not_lowered(self):
        """Sir ③ 红线: alias-fold ≠ 复活降阈合并。seed 合并阈不动。"""
        cfg = rm._SEED_MANIFOLD_CONFIG
        self.assertEqual(cfg["merge_threshold"], 0.90,
                         "P0b alias-fold 不动 merge_threshold (不复活降阈)")
        self.assertEqual(cfg["auto_merge_dups"]["threshold"], 0.93,
                         "auto_merge_dups 阈不动 (Sir ③: 两件事别粘一起)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
