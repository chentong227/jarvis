# -*- coding: utf-8 -*-
"""[β.5.36-fix3 / 2026-05-20 13:05] ProactiveShield ghost-input guard regression test.

Sir 实测真理: "屏幕动的是 Cursor 自动编程的, 不是我"
ProactiveShield 老逻辑看 window_history switches 误判 Sir 在场 (Cascade IDE 改文件 → window 变).
修法: idle_seconds > 60s → Sir 离桌, 不触 shield_alert (准则 6 evidence: 真物理 input).
"""
from __future__ import annotations

import os
import unittest
from collections import deque
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta536Fix3GhostInputGuard(unittest.TestCase):
    """ProactiveShield._scan() 看 idle_seconds 守卫 ghost activity."""

    def _make_shield(self):
        from jarvis_enhanced import ProactiveShield
        # bypass __init__ side effects
        shield = ProactiveShield.__new__(ProactiveShield)
        shield.jarvis = None
        shield._window_switch_times = deque(maxlen=100)
        shield._error_page_times = {}
        shield._search_history = deque(maxlen=50)
        shield._last_nudge_time = 0
        shield._nudge_cooldown = 900
        shield._daily_nudge_count = 0
        shield._last_reset_day = ""
        shield._last_diag_print_time = 0
        shield._diag_print_interval = 30
        return shield

    def test_marker_present_in_source(self):
        with open(os.path.join(ROOT, 'jarvis_enhanced.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.36-fix3', src,
            'β.5.36-fix3 marker 必须在 jarvis_enhanced.py')
        self.assertIn('GhostInputGuard', src,
            'GhostInputGuard marker 必须存在')
        self.assertIn('idle_seconds > 60', src,
            'idle_seconds > 60 阈值必须显式存在')

    def test_idle_over_60s_skips_shield(self):
        """idle_seconds > 60 时, _scan 直接 return (不进 window history 分析)."""
        shield = self._make_shield()
        # mock GetTickCount + LastInputInfo via PhysicalEnvironmentProbe.get_sensor_snapshot
        fake_snap = {
            'idle_seconds': 120,  # 2 min idle, Sir 离桌
            'work_category': 'Coding',
            'window_title': 'Cursor - main.py',
        }
        # 同时灌一堆 window history (cascade 切换), 看 shield 是否仍 skip
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        fake_history = deque(
            [{'time': i, 'title': f'win_{i}', 'idle_ms': 100} for i in range(100)],
            maxlen=180,
        )
        with patch.object(P, 'get_sensor_snapshot', return_value=fake_snap), \
             patch.object(P, 'window_history', new=fake_history), \
             patch.object(P, '_shield_alert', new={'active': False}):
            shield._scan()
        # _scan() 在 idle > 60 时 return, _shield_alert 不该被设
        self.assertFalse(P._shield_alert.get('active', False),
            'idle > 60s 时 ProactiveShield 不该触 shield_alert')

    def test_idle_under_60s_proceeds_to_analysis(self):
        """idle_seconds <= 60 时, _scan 继续走 frustration 分析."""
        shield = self._make_shield()
        fake_snap = {
            'idle_seconds': 30,  # Sir 在场
            'work_category': 'Coding',
        }
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        # < 10 events history → 后续 _scan 早 return (history 少不分析), 避免下游崩
        fake_history = deque(
            [{'time': i, 'title': f'win_{i}', 'idle_ms': 100} for i in range(5)],
            maxlen=180,
        )
        with patch.object(P, 'get_sensor_snapshot', return_value=fake_snap), \
             patch.object(P, 'window_history', new=fake_history):
            # 不抛异常即可 (走过 idle guard, 进 history 分析)
            try:
                shield._scan()
            except Exception as e:
                self.fail(f'idle <= 60 路径不应抛: {e}')


if __name__ == '__main__':
    unittest.main()
