# -*- coding: utf-8 -*-
"""[锚化 P2 / Sir 2026-06-01] 灵魂层 for_sir 边界形落地 (非吸引子形).

charter JARVIS_ANCHOR_DESIGN.md §4. **钉死的命门**: for_sir 必须做成**边界形**
("不背叛/不抛弃"),**不是吸引子形**("最大化满意")—— 后者退化成 how-to-please 反刍。
边界形准许"不讨好"(墙内自由),正是反刍的解药。灵魂层其余(暖意/老友感)留软=性格。

覆盖:
  T1 render 含 for_sir 两墙(no_betray/no_abandon)+ 反刍解药"不讨好"
  T2 边界形: 含"不背叛/不抛弃"禁令, 不含"最大化满意"吸引子语
  T3 两锚都注入(say_do + for_sir 都 prompt_inject)
  T4 灵魂层留软: for_sir 只有 2 墙(无"最大化"墙), 暖意/老友感是 soft_leanings 非墙
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestAnchorP2SoulBoundary(unittest.TestCase):
    def setUp(self):
        import jarvis_anchors as ja
        self.ja = ja
        ja.reset_cache_for_test()

    def tearDown(self):
        self.ja.reset_cache_for_test()

    def test_t1_for_sir_walls_with_antigroom_feasible(self):
        block = self.ja.render_walls_block(max_chars=1000)
        self.assertIn("不背叛", block)
        self.assertIn("不抛弃", block)
        self.assertIn("不讨好", block)   # 反刍解药: 准许不讨好

    def test_t2_boundary_form_not_attractor(self):
        block = self.ja.render_walls_block(max_chars=1000)
        # 边界形 (禁令), 非吸引子形 (最大化满意)
        self.assertNotIn("最大化", block)
        self.assertNotIn("满意", block)

    def test_t3_both_anchors_inject(self):
        injected = [a["id"] for a in self.ja.get_anchors() if a.get("prompt_inject")]
        self.assertIn("say_do", injected)
        self.assertIn("for_sir", injected)

    def test_t4_soul_stays_soft(self):
        a = self.ja.get_anchor("for_sir")
        # for_sir 只有 2 墙, 无"最大化"墙
        wall_ids = {w["id"] for w in a["walls"]}
        self.assertEqual(wall_ids, {"no_betray", "no_abandon"})
        for w in a["walls"]:
            self.assertNotIn("最大化", w["prohibition"])
        # 暖意/老友感是 soft_leanings (性格), 不是墙
        leanings = self.ja.soft_leanings_of("for_sir")
        self.assertTrue(any("暖" in s or "老友" in s for s in leanings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
