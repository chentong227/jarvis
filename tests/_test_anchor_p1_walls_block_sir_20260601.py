# -*- coding: utf-8 -*-
"""[锚化 P1 / Sir 2026-06-01] 言出必行边界块注入 (judge→boundary 建设性侧).

charter JARVIS_ANCHOR_DESIGN.md §3. persona 已有禁令(不可改红线 AGENTS §4.8);
P1 补 persona 缺的**建设性侧** —— 撞墙时的可行 move(问/hedge/沉默),data-driven from
anchors.json,减"我必须精确"式优化焦虑(H0 镜像那条 衡=filler 反刍的根)。

覆盖:
  T1 render_walls_block 含 say_do 墙(ground/keep prohibition + feasible 可行选项)
  T2 for_sir prompt_inject=false → 不出现在块里(P2 才开)
  T3 say_do prompt_inject=false(CLI/json 可关)→ 块空
  T4 块有界(<= max_chars)
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestAnchorP1WallsBlock(unittest.TestCase):
    def setUp(self):
        import jarvis_anchors as ja
        self.ja = ja
        ja.reset_cache_for_test()

    def tearDown(self):
        self.ja.reset_cache_for_test()

    def test_t1_say_do_walls_present(self):
        block = self.ja.render_walls_block()
        self.assertIn("言出必行", block)
        self.assertIn("不把无法 trace", block)        # ground prohibition
        self.assertIn("hedge", block)                  # ground feasible
        self.assertIn("搁置", block)                   # keep feasible

    def test_t2_for_sir_not_injected(self):
        block = self.ja.render_walls_block()
        # for_sir prompt_inject=false → 不注入 (P2 才开)
        self.assertNotIn("不背叛", block)

    def test_t3_toggle_off_empties(self):
        off = {"anchors": [{"id": "say_do", "prompt_inject": False}]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "anchors.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(off, f, ensure_ascii=False)
            with patch.object(self.ja, "_ANCHORS_PATH", p):
                self.ja.reset_cache_for_test()
                block = self.ja.render_walls_block()
                self.assertNotIn("言出必行", block)  # 关了 → 不注入
        self.ja.reset_cache_for_test()

    def test_t4_bounded(self):
        block = self.ja.render_walls_block(max_chars=520)
        self.assertLessEqual(len(block), 520)


if __name__ == "__main__":
    unittest.main(verbosity=2)
