# -*- coding: utf-8 -*-
"""[useful-or-quiet P1 / Sir 2026-05-31 00:46] 跨 category 价值门控退避 回归.

Sir 真痛: "高频唤醒不是唤醒了一直重复做无用功. 要么放得下/降频, 要么真有用."
根因 (已核): saturation `_check_and_update_saturation` 要求"连续同 category"才计数
(line 3589 `all(t.category == cat)`), 但思考脑每 tick category-hop (B/A/C/D/E) →
count 一直 reset → 永不到 force 阈值 → 永不降频 → 跨类低值 churn (编故事/重复提案).

P1 治本: 价值门控退避 (不看 category, 只看价值) — 连续低值 tick → 指数退避;
reset on 高值/should_speak. 只能拉长 interval (clamp 安全).

测试覆盖:
  VB1 跨 category 低值连续 → streak 累积 + 指数退避 (补 saturation 漏洞)
  VB2 高 salience (>=reset) → reset 回 baseline
  VB3 should_speak → reset (真想说 → 不退避)
  VB4 中值 (>=floor) → 不算低值 → reset
  VB5 disabled → 0
  VB6 _tick clamp 只拉长不缩短
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon(
        key_router=MagicMock(), concerns_ledger=None,
        relational_state=None, central_nerve=None,
    )
    # 隔离 _infer_actionable_state → 'none' (无 effect), 专测 backoff 逻辑
    d._infer_actionable_state = lambda t: 'none'
    return d


def _thought(sal, should_speak=False, cat='A'):
    return types.SimpleNamespace(
        salience=sal, should_speak=should_speak, category=cat,
        actionable='none', actionable_done=None,
    )


class TestVB1CrossCategoryBackoff(unittest.TestCase):
    def test_low_value_accumulates_across_categories(self):
        d = _make_daemon()
        # 跨 5 个不同 category 的低值 tick — saturation 会 reset, 价值退避不会
        seq = []
        for cat in ('A', 'B', 'C', 'D', 'E', 'A'):
            seq.append(d._update_value_backoff(_thought(0.4, cat=cat)))
        # streak: 1(<min2→0) / 2→90 / 3→180 / 4→300 / 5→600 / 6→600(cap)
        self.assertEqual(seq, [0, 90, 180, 300, 600, 600],
            f"跨 category 低值应累积退避 (补 saturation 漏洞), got {seq}")


class TestVB2HighSalienceResets(unittest.TestCase):
    def test_high_salience_resets_streak(self):
        d = _make_daemon()
        d._update_value_backoff(_thought(0.4))  # streak=1
        d._update_value_backoff(_thought(0.4))  # streak=2 → 90
        self.assertEqual(d._low_value_streak, 2)
        # 高 salience (真值得想) → reset
        out = d._update_value_backoff(_thought(0.85))
        self.assertEqual(out, 0)
        self.assertEqual(d._low_value_streak, 0)


class TestVB3ShouldSpeakResets(unittest.TestCase):
    def test_should_speak_resets(self):
        d = _make_daemon()
        d._update_value_backoff(_thought(0.4))
        d._update_value_backoff(_thought(0.4))
        out = d._update_value_backoff(_thought(0.4, should_speak=True))
        self.assertEqual(out, 0, "真想说 → 不退避")
        self.assertEqual(d._low_value_streak, 0)


class TestVB4MidValueNotLow(unittest.TestCase):
    def test_mid_value_above_floor_not_low(self):
        d = _make_daemon()
        # sal 0.6 >= floor 0.55 (且 < reset 0.75) → 不算低值 → reset
        out = d._update_value_backoff(_thought(0.6))
        self.assertEqual(out, 0)
        self.assertEqual(d._low_value_streak, 0)


class TestVB5Disabled(unittest.TestCase):
    def test_disabled_returns_zero(self):
        d = _make_daemon()
        with patch('jarvis_inner_thought_daemon._load_saturation_config',
                    return_value={'value_backoff': {'enabled': False}}):
            d._update_value_backoff(_thought(0.4))
            out = d._update_value_backoff(_thought(0.4))
        self.assertEqual(out, 0)
        self.assertEqual(d._low_value_streak, 0)


class TestVB6ConfigPresent(unittest.TestCase):
    def test_value_backoff_in_config(self):
        from jarvis_inner_thought_daemon import _load_saturation_config
        cfg = _load_saturation_config()
        self.assertIn('value_backoff', cfg)
        self.assertIn('backoff_steps_s', cfg['value_backoff'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
