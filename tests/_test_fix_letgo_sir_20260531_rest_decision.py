# -*- coding: utf-8 -*-
"""[放下能力 / Sir 2026-05-31 17:37] 识主动"放下" — settled 不强凑 thought, 歇会.

Sir 真意: "可以空转, 但空转本身就是意义'放下, 这会 Sir 没事我也没事, 休息会', 而不是
强行凑一个 thought 的空转". 识每次唤醒先判有无真势能; 没有 → <REST> → 不产 filler,
拉长下次唤醒 (越歇越久); 被 Sir 唤醒/紧急 → emergency 中断即跟上。

覆盖 (无 LLM, duck-typed):
  L1 raw 含 <REST> 且无实质 THOUGHT → 识别为 rest (不 parse filler)
  L2 rest → 拉长 next_tick_interval (越歇越久, 按 streak 走 backoff_steps)
  L3 rest 连续 → interval 递增到封顶
  L4 raw 含 <REST> 但也有实质 THOUGHT → 不当 rest (走正常 parse, 防误吞)
  L5 enabled=0 → 不启用 (退回老行为)
  L6 prompt 含 REST-first 指令 (静态: LLM 被告知可放下)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_inner_thought_daemon import InnerThoughtDaemon


def _daemon():
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._bg_log = lambda *a, **k: None
    d._low_value_streak = 0
    d._next_tick_interval_s = 0
    d._tick_origin_stats = {}
    return d


class TestRestDecision(unittest.TestCase):
    def test_l1_rest_detected(self):
        d = _daemon()
        raw = "<REST>all settled — nothing pressing, resting</REST>"
        self.assertTrue(d._handle_rest_decision(raw, 'active'))

    def test_l2_rest_relaxes_interval(self):
        d = _daemon()
        d._handle_rest_decision("<REST>settled</REST>", 'active')
        # streak=1 → steps[0]=180
        self.assertEqual(d._next_tick_interval_s, 180)
        self.assertEqual(d._low_value_streak, 1)

    def test_l3_consecutive_rest_grows_to_cap(self):
        d = _daemon()
        intervals = []
        for _ in range(7):
            d._handle_rest_decision("<REST>still settled</REST>", 'active')
            intervals.append(d._next_tick_interval_s)
        # 越歇越久, 封顶 1800
        self.assertEqual(intervals[0], 180)
        self.assertEqual(intervals[-1], 1800)   # capped
        self.assertTrue(intervals[1] >= intervals[0])  # 单调不降

    def test_l4_substantive_thought_not_rest(self):
        d = _daemon()
        # 既有 REST 又有实质 THOUGHT → 不当 rest (走正常 parse)
        raw = ("<REST>x</REST><CATEGORY>B</CATEGORY><THOUGHT>My last reply was too "
               "verbose on system alerts; next time I should be terser with Sir.</THOUGHT>")
        self.assertFalse(d._handle_rest_decision(raw, 'active'))

    def test_l5_disabled(self):
        d = _daemon()
        cfg = {'rest': {'enabled': False}}
        with patch('jarvis_inner_thought_daemon._load_saturation_config',
                   return_value=cfg):
            self.assertFalse(d._handle_rest_decision("<REST>settled</REST>", 'active'))

    def test_l6_prompt_has_rest_instruction(self):
        with open(os.path.join(ROOT, 'jarvis_inner_thought_daemon.py'),
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn('<REST>', src)
        self.assertIn('Resting is a VALID', src)
        self.assertIn('DO NOT manufacture a filler', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
