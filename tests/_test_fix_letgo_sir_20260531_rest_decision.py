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

    def test_l2_rest_uses_ambient_floor_not_ladder(self):
        # 优雅: 休息=单一存在心跳 floor (非升级阶梯). 多次 rest 间隔不变 (不 escalate).
        d = _daemon()
        d._handle_rest_decision("<REST>settled</REST>", 'active')
        first = d._next_tick_interval_s
        self.assertEqual(first, 600)        # ambient_floor, 单常数
        self.assertTrue(d._resting)         # 标记休息中 (体动静可唤醒)
        # 再 rest → 还是同一 floor (不像 ladder 越来越久)
        d._resting = False
        d._handle_rest_decision("<REST>still settled</REST>", 'active')
        self.assertEqual(d._next_tick_interval_s, first)   # 不 escalate

    def test_l3_body_stir_wakes_from_rest(self):
        # 势能扰动唤醒: 休息中体有 fresh delta → 提前结束休息 (非定时到点)
        d = _daemon()
        d._resting = True

        class _FakeFocus:
            def has_fresh_delta(self, min_magnitude=0.0):
                return True
        with patch('jarvis_body_focus.get_body_focus', return_value=_FakeFocus()):
            self.assertTrue(d._check_body_stir())
        self.assertFalse(d._resting)   # 唤醒后清休息标

    def test_l3b_no_stir_no_wake(self):
        d = _daemon()
        d._resting = True

        class _FakeFocus:
            def has_fresh_delta(self, min_magnitude=0.0):
                return False
        with patch('jarvis_body_focus.get_body_focus', return_value=_FakeFocus()):
            self.assertFalse(d._check_body_stir())
        self.assertTrue(d._resting)    # 没动静 → 继续休息

    def test_l3c_not_resting_no_check(self):
        d = _daemon()
        d._resting = False  # 没在休息 → 不检 (正常 tick 不需)
        self.assertFalse(d._check_body_stir())

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
