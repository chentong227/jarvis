# -*- coding: utf-8 -*-
"""[口识体-B2 / 2026-05-31] 口写体: 对话 turn → 显著共现边 testcase.

闭环的写侧: 一轮对话提到的体节点 (lexical 匹配) → 两两共现边, turn_id 接地。
**选择性 (准则 8 防 bloat)**: 平凡闲聊 (匹配 <2 节点) → 不写。
详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §4.1 / §1.1 铁律1。

覆盖 (tmp 隔离):
  T1  turn 激活 ≥2 体节点 (熬夜+overbearing) → 共现边
  T2  平凡闲聊 (匹配 <2) → 不写 (selective)
  T3  CJK 滑窗 gram 匹配长 run (连续熬夜风险 → 熬夜)
  T4  turn_id 接地 (provenance ref=turn_id)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, KIND_CONCERN, KIND_JOKE, PROV_COOCCUR,
)
from jarvis_relational_weaver import observe_turn_cooccurrence, _distinctive_terms

SLEEP = make_node_id(KIND_CONCERN, "sleep")
JOKE = make_node_id(KIND_JOKE, "j1")
HYDR = make_node_id(KIND_CONCERN, "hydration")
TMAP = {
    SLEEP: "Sir 连续熬夜风险 deep night",
    JOKE: "becoming overbearing",
    HYDR: "Sir 饮水 hydration 不足",
}


class TestWriteback(unittest.TestCase):
    def test_t1_turn_creates_cooccur(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            n = observe_turn_cooccurrence(
                "Sir 你最近又熬夜了, 有点 overbearing 啊", "turn_1",
                text_map=TMAP, manifold=m, save=False)
            self.assertGreaterEqual(n, 1)
            e = m.get_edge(SLEEP, JOKE)
            self.assertIsNotNone(e, "熬夜+overbearing 两节点应连共现边")

    def test_t2_smalltalk_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            n = observe_turn_cooccurrence(
                "hello how are you today", "turn_2",
                text_map=TMAP, manifold=m, save=False)
            self.assertEqual(n, 0, "平凡闲聊匹配<2 → 不写 (selective)")
            self.assertEqual(m.stats()["edge_count"], 0)

    def test_t3_cjk_gram_match(self):
        terms = _distinctive_terms("Sir 连续熬夜风险 deep night")
        self.assertIn("熬夜", terms)        # 滑窗 gram 从长 run 抽出
        self.assertIn("deep", terms)

    def test_t4_turn_id_grounded(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            observe_turn_cooccurrence(
                "熬夜 又 overbearing", "turn_xyz",
                text_map=TMAP, manifold=m, save=False)
            e = m.get_edge(SLEEP, JOKE)
            self.assertIsNotNone(e)
            refs = {p["ref"] for p in e["provenance"]}
            self.assertIn("turn_xyz", refs)             # 接地到 turn
            self.assertEqual(e["provenance"][0]["kind"], PROV_COOCCUR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
