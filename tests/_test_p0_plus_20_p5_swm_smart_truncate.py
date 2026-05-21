# -*- coding: utf-8 -*-
"""[Gap-Z2 / β.5.46-fix6 / 2026-05-21 23:40] SWM smart truncate 测试.

不再简单尾部截断, 优先扔低 salience, 保 critical (>=0.85) 红线信号.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSmartTruncate(unittest.TestCase):

    def setUp(self):
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus()

    def _publish_n(self, n: int, etype: str, sal: float, prefix: str = ''):
        for i in range(n):
            self.bus.publish(
                etype=etype,
                description=f'{prefix}event_{i}_with_long_description_text',
                salience=sal,
                source='test',
            )

    def test_under_budget_returns_all(self):
        """字数没超 → 返全部 lines."""
        self._publish_n(3, 'test_etype_A', 0.5)
        block = self.bus.to_swm_block(n=12, max_chars=2000, salience_floor=0.0)
        self.assertIn('test_etype_A', block)
        self.assertEqual(block.count('event_'), 3)

    def test_over_budget_drops_low_salience(self):
        """字数超 → 优先扔低 salience."""
        # 5 个 high (0.9), 5 个 low (0.4)
        for i in range(5):
            self.bus.publish(
                etype='hi_evt',
                description=f'high_priority_event_{i}_with_long_text',
                salience=0.9,
                source='test',
            )
            self.bus.publish(
                etype='lo_evt',
                description=f'low_priority_event_{i}_with_long_text',
                salience=0.4,
                source='test',
            )
        # max_chars 故意小, 强制截断
        block = self.bus.to_swm_block(n=20, max_chars=600, salience_floor=0.0)
        # 所有 high 应保留
        for i in range(5):
            self.assertIn(f'high_priority_event_{i}', block,
                          f'high_priority_event_{i} 必保 (sal=0.9)')

    def test_critical_salience_always_kept(self):
        """critical >= 0.85 即使总超 budget 也不扔."""
        # 单个 critical event 超 budget
        long_desc = 'commitment_overdue ' * 30  # ~600c
        self.bus.publish(
            etype='commitment_overdue',
            description=long_desc,
            salience=0.95,
            source='test',
        )
        # 5 个 0.4 占位
        self._publish_n(5, 'lo_evt', 0.4, prefix='lo_')
        block = self.bus.to_swm_block(n=20, max_chars=400, salience_floor=0.0)
        # critical 必保
        self.assertIn('commitment_overdue', block)

    def test_drop_marker_shown(self):
        """有 non_critical 被截 → 加 dropped 标记."""
        self._publish_n(20, 'lo_evt', 0.4, prefix='lo_')
        block = self.bus.to_swm_block(n=20, max_chars=400, salience_floor=0.0)
        # 应有截断标记
        self.assertIn('dropped', block.lower())


if __name__ == '__main__':
    unittest.main()
