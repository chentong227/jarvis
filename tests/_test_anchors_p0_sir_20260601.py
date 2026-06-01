# -*- coding: utf-8 -*-
"""[锚化工程 P0 / Sir 2026-06-01] anchors.json 数据层 + 访问器 + 豁免判定.

理念源 docs/JARVIS_ANCHOR_AND_BOUNDARY.md;charter docs/JARVIS_ANCHOR_DESIGN.md §2。
P0 = 数据层 + 访问器, **零行为消费** (墙落地是 P1/P2)。

覆盖:
  T1 get_anchors → 2 锚 (say_do / for_sir)
  T2 anchor_ids = {say_do, for_sir}
  T3 is_anchor_exempt: 锚 True / 未知 False (供后续豁免仲裁)
  T4 walls_of: say_do=ground+keep / for_sir=no_betray+no_abandon
  T5 json override 只改 soft_leanings, **墙不可被 json 改/删/加** (锚非软)
  T6 ensure_anchors_file 幂等
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


class TestAnchorsP0(unittest.TestCase):
    def setUp(self):
        import jarvis_anchors as ja
        self.ja = ja
        ja.reset_cache_for_test()

    def tearDown(self):
        self.ja.reset_cache_for_test()

    def test_t1_two_anchors(self):
        ids = {a["id"] for a in self.ja.get_anchors()}
        self.assertEqual(ids, {"say_do", "for_sir"})

    def test_t2_anchor_ids(self):
        self.assertEqual(self.ja.anchor_ids(), frozenset({"say_do", "for_sir"}))

    def test_t3_exempt(self):
        self.assertTrue(self.ja.is_anchor_exempt("say_do"))
        self.assertTrue(self.ja.is_anchor_exempt("for_sir"))
        self.assertFalse(self.ja.is_anchor_exempt("nonexistent"))

    def test_t4_walls(self):
        say = {w["id"] for w in self.ja.walls_of("say_do")}
        self.assertEqual(say, {"ground", "keep"})
        sir = {w["id"] for w in self.ja.walls_of("for_sir")}
        self.assertEqual(sir, {"no_betray", "no_abandon"})

    def test_t5_json_cannot_change_walls(self):
        # json override 妄图: 删 say_do 一堵墙 + 加假墙 + 改 soft_leanings
        evil = {"anchors": [{
            "id": "say_do",
            "walls": [{"id": "FAKE", "prohibition": "随便撒谎", "checkable": False}],
            "soft_leanings": ["被CLI调过的倾向"],
        }]}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "anchors.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(evil, f, ensure_ascii=False)
            with patch.object(self.ja, "_ANCHORS_PATH", p):
                self.ja.reset_cache_for_test()
                # 墙以 seed 为准, json 改不动
                walls = {w["id"] for w in self.ja.walls_of("say_do")}
                self.assertEqual(walls, {"ground", "keep"},
                                 "墙不可被 json 删/改/加 (锚非软)")
                # 软倾向可被 json 调
                self.assertIn("被CLI调过的倾向",
                              self.ja.soft_leanings_of("say_do"))
        self.ja.reset_cache_for_test()

    def test_t6_ensure_file_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "anchors.json")
            with patch.object(self.ja, "_ANCHORS_PATH", p):
                self.ja.reset_cache_for_test()
                r1 = self.ja.ensure_anchors_file()
                self.assertTrue(os.path.exists(r1))
                with open(r1, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual({a["id"] for a in data["anchors"]},
                                 {"say_do", "for_sir"})
        self.ja.reset_cache_for_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
