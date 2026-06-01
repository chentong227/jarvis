# -*- coding: utf-8 -*-
"""[衡 H1 / Sir 2026-06-01] 识 anchor-aware: 思考脑 prompt 含锚的墙+可行选项.

charter JARVIS_HENG_DESIGN.md H1 (依赖锚化 P0-P2 墙就位). 把锚的墙喂思考脑, 让它
知道自己的边界, 把"撞墙张力"(诚实vs善意)识别为真值得想的 discharge, 而非"我必须精确"反刍
(H0 镜像那条 衡=filler 的根)。复用 P1 render_walls_block (data-driven anchors.json)。

覆盖:
  T1 _build_prompt 含"你的边界"块 + say_do 墙(不把无法trace) + for_sir 墙(不背叛)
  T2 含可行选项框架(hedge/不讨好)→ 减"我必须精确"焦虑
  T3 关掉所有 prompt_inject → 思考 prompt 不含边界块(优雅可退)
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


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    import time
    tmp = os.path.join(tempfile.gettempdir(), f'heng_h1_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


class TestHengH1(unittest.TestCase):
    def setUp(self):
        self.d = _build_daemon()
        import jarvis_anchors as ja
        self.ja = ja
        ja.reset_cache_for_test()

    def tearDown(self):
        self.ja.reset_cache_for_test()

    def test_t1_walls_in_thinking_prompt(self):
        system, _ = self.d._build_prompt('active', {}, ['A', 'B'], None)
        self.assertIn("你的边界", system)
        self.assertIn("不把无法 trace", system)  # say_do 墙
        self.assertIn("不背叛", system)            # for_sir 墙

    def test_t2_feasible_framing_present(self):
        system, _ = self.d._build_prompt('active', {}, ['A'], None)
        self.assertIn("hedge", system)        # 可行选项 (减焦虑)
        self.assertIn("不讨好", system)        # for_sir 可行 (反刍解药)

    def test_t3_toggle_off_no_block(self):
        off = {"anchors": [
            {"id": "say_do", "prompt_inject": False},
            {"id": "for_sir", "prompt_inject": False},
        ]}
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "anchors.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(off, f, ensure_ascii=False)
            with patch.object(self.ja, "_ANCHORS_PATH", p):
                self.ja.reset_cache_for_test()
                system, _ = self.d._build_prompt('active', {}, ['A'], None)
                self.assertNotIn("你的边界", system)  # 全关 → 无边界块
        self.ja.reset_cache_for_test()


if __name__ == "__main__":
    unittest.main(verbosity=2)
