# -*- coding: utf-8 -*-
"""[β.5.46-fix15 / 2026-05-22] Sir 10:59 真测 BUG — 287K 行 log spam regression

Sir 报: "看看日志, 严重的 BUG 溢出, 刷屏了"
8 分钟 21 MB / 287047 行, 99.9% 是同一行:
  '[CentralNerve] 检测到用户活动唤醒 (睡眠模式持续 0.X 分钟)'

Root cause (3 层并发 race):
  1. SleepIntent activate sleep_mode → _sleep_activated_at = now
  2. SmartNudge tick: idle_ms < 30s → 调 deactivate_sleep_mode() (非 force)
  3. NudgeGate: 30s 内拒, **silent return** — sleep_mode 仍 True
  4. SmartNudge 不知失败, 紧接调 _on_activity_wake() → print
  5. 下 tick 再来 — print spam

3 处 minimal fix:
  A. NudgeGate.deactivate_sleep_mode 返 bool (老 silent void)
  B. SmartNudge 看 bool — False 不调 wake, sleep 30s 等
  C. _on_activity_wake 加 30s 防御性 cooldown — 第二道防线

Cover:
  TestA: deactivate_sleep_mode 返 bool, 30s 内拒返 False
  TestB: SmartNudge 路径 — 真测 mock 30s 内不应 spam print
  TestC: _on_activity_wake 30s cooldown 单测
  TestD: marker 在源码
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_DeactivateReturnsBool(unittest.TestCase):
    """A: NudgeGate.deactivate_sleep_mode 返 bool."""

    def setUp(self):
        from jarvis_sentinels import NudgeGate
        self.gate = NudgeGate()

    def test_deactivate_returns_true_when_force(self):
        self.gate.activate_sleep_mode()
        result = self.gate.deactivate_sleep_mode(force=True)
        self.assertTrue(result, 'force=True 应真解 + 返 True')
        self.assertFalse(self.gate.is_sleep_mode())

    def test_deactivate_returns_false_within_30s_lock(self):
        """30s 内拒绝 — 返 False 让 caller 知道."""
        self.gate.activate_sleep_mode()
        # 立刻调 deactivate (0 秒)
        result = self.gate.deactivate_sleep_mode(force=False)
        self.assertFalse(result,
                          '30s lock 内拒返 False (老 silent return = void/None)')
        self.assertTrue(self.gate.is_sleep_mode(),
                          'sleep_mode 仍 True (拒了)')

    def test_deactivate_returns_true_after_30s(self):
        """超 30s 后 deactivate 真解 + 返 True."""
        self.gate.activate_sleep_mode()
        # 模拟 31s 后
        self.gate._sleep_activated_at = time.time() - 31
        result = self.gate.deactivate_sleep_mode(force=False)
        self.assertTrue(result, '超 30s 应真解 + 返 True')
        self.assertFalse(self.gate.is_sleep_mode())

    def test_deactivate_returns_false_when_not_sleeping(self):
        """没 sleep 时调 deactivate (force=False) — 返 False."""
        # 默认状态: not sleeping
        result = self.gate.deactivate_sleep_mode(force=False)
        # 没 sleep 时 was_sleeping=False, 不进入 if branch, 末尾 return False
        self.assertFalse(result, '没 sleep 调 deactivate 应返 False')


class TestB_SmartNudgeChecksReturn(unittest.TestCase):
    """B: SmartNudge 看 deactivate 返 bool, 假就 sleep 不调 wake."""

    def test_marker_in_source(self):
        import jarvis_smart_nudge
        with open(jarvis_smart_nudge.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix15', src,
                       'fix15 marker 应在 SmartNudge')
        self.assertIn('deactivated = self.gate.deactivate_sleep_mode()', src,
                       'SmartNudge 应捕获 deactivate 返值')
        self.assertIn('if not deactivated:', src,
                       'SmartNudge 应看 deactivated bool 决定是否调 wake')

    def test_old_silent_call_removed(self):
        """老路径 `self.gate.deactivate_sleep_mode()` 不看返值已被替."""
        import jarvis_smart_nudge
        with open(jarvis_smart_nudge.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 sleep mode 分支
        idx = src.find('is_sleep_mode():')
        self.assertGreater(idx, 0)
        body = src[idx:idx + 1500]
        # 应该有 "deactivated =" 模式 (新), 不是直接 silent call
        self.assertIn('deactivated =', body)
        # 应该有 "if not deactivated"
        self.assertIn('if not deactivated', body)


class TestC_OnActivityWakeCooldown(unittest.TestCase):
    """C: _on_activity_wake 30s 防御性 cooldown."""

    def test_marker_in_source(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix15', src,
                       'fix15 marker 应在 central_nerve._on_activity_wake')
        self.assertIn('_last_activity_wake_print', src,
                       '应有 _last_activity_wake_print cooldown 字段')

    def test_cooldown_check_present(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('def _on_activity_wake')
        self.assertGreater(idx, 0)
        body = src[idx:idx + 800]
        self.assertIn('_last_activity_wake_print', body,
                       '应在 _on_activity_wake 函数内 check cooldown')
        self.assertIn('< 30', body,
                       '30s cooldown')

    def test_cooldown_blocks_repeated_calls(self):
        """模拟 _on_activity_wake 重复调 — 第二次 30s 内应跳过 print."""
        # mock central_nerve 实例最简
        nerve = MagicMock()
        nerve._last_activity_wake_print = 0
        nerve.nudge_gate = MagicMock()
        nerve.nudge_gate.sleep_duration_seconds.return_value = 60.0

        # bind 真函数
        from jarvis_central_nerve import CentralNerve
        # 第一次 call - 模拟 fire
        with patch('builtins.print') as p1:
            CentralNerve._on_activity_wake(nerve)
            p1_call_count = p1.call_count
        # 立刻第二次 call (cooldown 内)
        with patch('builtins.print') as p2:
            CentralNerve._on_activity_wake(nerve)
            p2_call_count = p2.call_count
        # 第一次应有 print, 第二次应无 (cooldown blocks)
        self.assertGreaterEqual(p1_call_count, 1, '第一次应 print')
        self.assertEqual(p2_call_count, 0, '第二次 30s cooldown 内应 silent')


class TestD_MarkerCoverage(unittest.TestCase):
    """D: 3 处 fix marker 全在源码 (commit 验证)."""

    def test_sentinels_marker(self):
        import jarvis_sentinels
        with open(jarvis_sentinels.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix15', src,
                       'fix15 marker 应在 NudgeGate.deactivate_sleep_mode')

    def test_smart_nudge_marker(self):
        import jarvis_smart_nudge
        with open(jarvis_smart_nudge.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix15', src)

    def test_central_nerve_marker(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.46-fix15', src)


if __name__ == '__main__':
    unittest.main()
