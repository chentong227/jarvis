# -*- coding: utf-8 -*-
"""[body-diff-P0b-① / Sir 2026-06-03] 接地加权成面 (weighted 非 only, 不变量② 彻底形态).

真理源: .kiro/specs/body-differentiation/design.md §3.2/§3.5 (P0b ①) + kickoff §11。

== 解决什么 (发现 C) ==
镜像: 全部边成面 largest_frac 0.702, 1439 边里 1092 (76%) 是自产↔自产 embed (思考相似糊团);
"只认 grounded 边" → 0.355 但 49 thread 变孤儿 (接近删思考, 违 R2.2)。正解 = **weighted**:
成面阶段接地边 (cooccur/said/shared) 全权; 两端都自产 (thread/joke/proto) 的非接地边
(embed/inferred-only) ×乘子 (<1) → 面围真实共现长, 不围思考相似长。

== Sir ① 约束 (weighted 非 only) ==
自产边仍在图里 (不删, spread/势能不受影响), 仅成面权降; 自产节点仍能经接地纽带成面归属,
不被抹成孤儿。**绝不"只认 grounded"把自产 thread 整个抹掉。**

覆盖 (纯几何, 无 LLM, tmp 隔离):
  T1  两端自产 embed-only 团 → 成面权打折压下阈值 → 不成面 (mult 1.0 时成); 且边仍在图 (未删)
  T2  自产节点有接地纽带 → 仍有面归属 (weighted 非 only, R2.2 不删思考)
  T3  接地边 (said) 两端自产也免折扣 (grounded > 自产 embed)
  T4  cross 边 (thread↔concern) embed 免折扣 (只折两端都自产, 保思考↔现实)
  T5  vocab 键存在 + 默认值 (准则 6)
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


def _said(m, a, b, scale=1.0):
    m.add_edge(a, b, PROV_SAID, ref="t", weight_scale=scale, now=T0)


def _embed(m, a, b, cos=0.95):
    m.add_geometric_edge(a, b, cos, now=T0)   # weight = 0.60 × cos (PROV_EMBED)


# core_min 0.45 让 embed 边 (≈0.57) 能成核; min_size 3
_CFG = {
    "surface_method": "core_boundary",
    "surface_overlap_min_links": 2,
    "surface_min_size": 3,
    "surface_min_weight": 0.45,
    "surface_core_min_weight": 0.45,
}


def _cfg(**over):
    return {**rm._SEED_MANIFOLD_CONFIG, **_CFG, **over}


class TestSelfProducedEmbedDiscounted(unittest.TestCase):
    def test_t1_self_produced_embed_cluster_suppressed(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            t = [make_node_id(KIND_THREAD, f"t{i}") for i in range(3)]
            _embed(m, t[0], t[1]); _embed(m, t[1], t[2]); _embed(m, t[0], t[2])
            # 乘子 0.5: 0.57 × 0.5 = 0.285 < 0.45 → 自产 embed 团成不了面
            with patch.object(rm, "get_manifold_config",
                              return_value=_cfg(surface_self_produced_embed_weight=0.5)):
                s_disc = m.compute_surfaces(now=T0)
            # 乘子 1.0 (不折): 0.57 >= 0.45 → 成 1 面
            with patch.object(rm, "get_manifold_config",
                              return_value=_cfg(surface_self_produced_embed_weight=1.0)):
                s_full = m.compute_surfaces(now=T0)
            self.assertEqual(len(s_disc), 0, "两端自产 embed 团应被成面权打折压下 → 不成面")
            self.assertEqual(len(s_full), 1, "不折时同样的团成 1 面 (证明是加权差异)")
            # weighted 非 only: 边仍在图 (compute_surfaces 只读, 不删边)
            self.assertIsNotNone(m.get_edge(t[0], t[1]),
                                 "自产 embed 边仍在图 (weighted 非 only, 未删)")


class TestSelfProducedKeepsMembership(unittest.TestCase):
    def test_t2_self_produced_node_with_grounded_tie_in_surface(self):
        """weighted 非 only: 自产节点经接地纽带仍有面归属 (R2.2 不删思考, ②.3)。"""
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            c = [make_node_id(KIND_CONCERN, f"c{i}") for i in range(3)]
            t1 = make_node_id(KIND_THREAD, "t1")
            _said(m, c[0], c[1]); _said(m, c[1], c[2]); _said(m, c[0], c[2])
            _said(m, t1, c[0]); _said(m, t1, c[1])   # 自产 t1 有接地 (said) 纽带到核
            with patch.object(rm, "get_manifold_config",
                              return_value=_cfg(surface_self_produced_embed_weight=0.5)):
                surfaces = m.compute_surfaces(now=T0)
            members = set()
            for s in surfaces:
                members.update(s["members"])
            self.assertIn(t1, members,
                          "自产节点有接地纽带 → 仍有面归属 (没被抹成孤儿)")


class TestGroundedEdgeImmune(unittest.TestCase):
    def test_t3_grounded_edge_not_discounted_even_self_produced(self):
        """接地边 (said) 即便两端自产也全权 (grounded > 自产 embed)。"""
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            t = [make_node_id(KIND_THREAD, f"t{i}") for i in range(3)]
            _said(m, t[0], t[1]); _said(m, t[1], t[2]); _said(m, t[0], t[2])
            with patch.object(rm, "get_manifold_config",
                              return_value=_cfg(surface_self_produced_embed_weight=0.5)):
                surfaces = m.compute_surfaces(now=T0)
            self.assertEqual(len(surfaces), 1, "接地边 (said) 免折扣 → 仍成 1 面")
            self.assertEqual(surfaces[0]["size"], 3)


class TestCrossEdgeImmune(unittest.TestCase):
    def test_t4_cross_embed_not_discounted(self):
        """cross 边 (thread↔concern) embed 免折扣 (只折两端都自产, 保思考↔现实)。"""
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            c = [make_node_id(KIND_CONCERN, f"c{i}") for i in range(3)]
            t1 = make_node_id(KIND_THREAD, "t1")
            _said(m, c[0], c[1]); _said(m, c[1], c[2]); _said(m, c[0], c[2])
            _embed(m, t1, c[0]); _embed(m, t1, c[1])   # cross embed (≈0.57), 不折
            with patch.object(rm, "get_manifold_config",
                              return_value=_cfg(surface_self_produced_embed_weight=0.5)):
                surfaces = m.compute_surfaces(now=T0)
            members = set()
            for s in surfaces:
                members.update(s["members"])
            self.assertIn(t1, members,
                          "cross embed 边免折扣 (0.57>=0.45) → t1 入面 (思考↔现实保留)")


class TestVocab(unittest.TestCase):
    def test_t5_vocab_defaults(self):
        cfg = rm._SEED_MANIFOLD_CONFIG
        self.assertEqual(cfg["surface_self_produced_embed_weight"], 0.5)
        self.assertIn("cooccur", cfg["surface_grounded_provenance"])
        self.assertIn("said", cfg["surface_grounded_provenance"])
        self.assertIn("shared", cfg["surface_grounded_provenance"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
