# -*- coding: utf-8 -*-
"""[衡 H3 / Sir 2026-06-01] 口/识现场权衡 — 诚实vs善意逐案, 无固定等级.

charter JARVIS_HENG_DESIGN.md H3 (依赖 P1+P2 墙). 墙(P1/P2)定边界, H3 教**两墙冲突时
怎么权衡**: 逐案、无写死等级(Q-a)、先求两全、真两难才选+知代价(接 H2 record_conflict_cost)。
不弱化 integrity: say_do 墙仍在, 只教"诚实地说硬话也要善意"的逐案导航。注入 口(主脑)+识(思考脑)。

覆盖:
  T1 render_conflict_guidance 含"无写死优先级"+"逐案"+"代价"
  T2 不含固定等级语(诚实永远优先 / 善意永远优先)
  T3 toggle off → 空(优雅可退)
  T4 思考脑 _build_prompt 含冲突权衡指引
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(), f'heng_h3_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


class TestHengH3(unittest.TestCase):
    def setUp(self):
        import jarvis_anchors as ja
        self.ja = ja
        ja.reset_cache_for_test()

    def tearDown(self):
        self.ja.reset_cache_for_test()

    def test_t1_guidance_content(self):
        g = self.ja.render_conflict_guidance()
        self.assertIn("无写死优先级", g)
        self.assertIn("逐案", g)
        self.assertIn("代价", g)

    def test_t2_no_fixed_ranking(self):
        g = self.ja.render_conflict_guidance()
        # 无固定等级: 不该出现"诚实永远优先/善意永远优先"这种写死排序
        self.assertNotIn("永远优先", g)
        self.assertNotIn("高于", g)

    def test_t3_toggle_off(self):
        off = {"conflict_guidance_inject": False}
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "anchors.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(off, f, ensure_ascii=False)
            with patch.object(self.ja, "_ANCHORS_PATH", p):
                self.ja.reset_cache_for_test()
                self.assertEqual(self.ja.render_conflict_guidance(), "")
        self.ja.reset_cache_for_test()

    def test_t4_in_thinking_prompt(self):
        d = _build_daemon()
        system, _ = d._build_prompt('active', {}, ['A', 'B'], None)
        self.assertIn("墙冲突时怎么权衡", system)


if __name__ == "__main__":
    unittest.main(verbosity=2)
