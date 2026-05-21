# -*- coding: utf-8 -*-
"""[β.5.46-fix13 Fix-1 / 2026-05-22] sleep_routine fire evidence gating.

Sir 00:25-00:32 真测连环 (B5/B6/B9):
  B5. 00:30:23: "Sir, you were only in sleep mode for 4 minute(s). Did you not
      fall asleep?" — Sir 根本没真睡, dismissal_soft 触发 activate_sleep_mode
      后 4min 被 _check_short_sleep 误质疑.
  B6. 00:25 + 00:30: 同夜 2 次 'Sir 表态约 30 分钟后睡' log 完整重复 — noisy.
  B9. 00:32: "you said you were going to sleep 2 minutes ago, but I detect you
      are still active" — _post_sleep_monitor 假质疑.

真凶: _sleep_activated_at / _sleep_confirmed_at 起算点 = dismissal/detect 时,
不是 Sir 真睡时. routine 还没真 fire 就被算"睡眠中".

治本 (Fix-1.1 / Fix-1.2 / Fix-1.3):
  1. NudgeGate 新加 _sleep_routine_fired_at + mark_sleep_routine_fired() +
     is_sleep_routine_fired() + sleep_routine_age_seconds()
  2. worker._do_routine 完成时调 mark_sleep_routine_fired()
  3. nerve._check_short_sleep 看 is_sleep_routine_fired(), 没 fire = skip
  4. SleepDetector._post_sleep_monitor_loop 看 is_sleep_routine_fired(), 没 fire = skip
  5. worker._detect_sleep_intent 同夜重复表态 (差距 < 5min) → 简短 renew log

Cover:
  A. NudgeGate API 新方法 (mark / is / age)
  B. activate_sleep_mode 重置 fired_at 为 0 (新一轮 sleep, 等 routine fire)
  C. mark_sleep_routine_fired 仅 sleep_mode active 时生效
  D. _check_short_sleep 看 is_sleep_routine_fired (静态 check)
  E. _post_sleep_monitor_loop 看 is_sleep_routine_fired (静态 check)
  F. _do_routine 调 mark_sleep_routine_fired (静态 check)
  G. _detect_sleep_intent 加 _is_renewal dedup log (静态 check)
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_NudgeGateApiAdded(unittest.TestCase):
    """NudgeGate 新 API: mark_sleep_routine_fired / is_sleep_routine_fired."""

    def setUp(self):
        from jarvis_sentinels import NudgeGate
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_initial_fired_state(self):
        """initial: 没 activate sleep_mode → is_sleep_routine_fired() False."""
        self.assertFalse(self.gate.is_sleep_routine_fired(),
                          '没 activate sleep_mode 时 fired 应 False')
        self.assertEqual(self.gate.sleep_routine_age_seconds(), 0.0,
                          '没 sleep 时 age 应 0')

    def test_activate_resets_fired_at(self):
        """activate_sleep_mode 应重置 _sleep_routine_fired_at = 0."""
        self.gate.activate_sleep_mode()
        self.assertFalse(self.gate.is_sleep_routine_fired(),
                          'activate 后 routine 还没 fire, 应 False')
        # internal attr
        self.assertEqual(self.gate._sleep_routine_fired_at, 0.0,
                          '新 sleep cycle 应重置 fired_at')

    def test_mark_routine_fired(self):
        """mark_sleep_routine_fired 后 is_sleep_routine_fired() = True."""
        self.gate.activate_sleep_mode()
        self.gate.mark_sleep_routine_fired()
        self.assertTrue(self.gate.is_sleep_routine_fired(),
                         'mark 后 fired 应 True')
        self.assertGreater(self.gate.sleep_routine_age_seconds(), -0.5,
                            'age 应可计算 (>= 0)')

    def test_mark_no_op_when_not_sleeping(self):
        """sleep_mode False 时 mark_sleep_routine_fired no-op."""
        # 没 activate
        self.gate.mark_sleep_routine_fired()
        self.assertFalse(self.gate.is_sleep_routine_fired(),
                          'sleep_mode False 时 mark 应 no-op')

    def test_age_increments(self):
        """fired 后 sleep_routine_age_seconds 单增."""
        self.gate.activate_sleep_mode()
        self.gate.mark_sleep_routine_fired()
        _age1 = self.gate.sleep_routine_age_seconds()
        time.sleep(0.05)
        _age2 = self.gate.sleep_routine_age_seconds()
        self.assertGreater(_age2, _age1,
                            'age 应单增 (时间流逝)')

    def test_deactivate_keeps_fired_at_until_next_activate(self):
        """deactivate 后 fired_at 仍存 (debug 用), 下次 activate 重置."""
        self.gate.activate_sleep_mode()
        self.gate.mark_sleep_routine_fired()
        self.assertTrue(self.gate.is_sleep_routine_fired())
        self.gate.deactivate_sleep_mode(force=True)
        # is_sleep_routine_fired = False 因为 _sleep_mode = False (不论 fired_at)
        self.assertFalse(self.gate.is_sleep_routine_fired(),
                          'deactivate 后 is_fired 应 False (因 sleep_mode False)')
        # 下次 activate 重置
        self.gate.activate_sleep_mode()
        self.assertEqual(self.gate._sleep_routine_fired_at, 0.0,
                          'activate 重置 fired_at')


class TestB_CheckShortSleepGuardsByEvidence(unittest.TestCase):
    """静态 check nerve._check_short_sleep 看 is_sleep_routine_fired."""

    def setUp(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_check_calls_is_sleep_routine_fired(self):
        """_check_short_sleep 应调 is_sleep_routine_fired."""
        idx = self.src.find('def _check_short_sleep')
        self.assertGreater(idx, 0)
        body = self.src[idx:idx + 3000]
        self.assertIn('is_sleep_routine_fired', body,
                      '_check_short_sleep 应调 is_sleep_routine_fired check evidence')
        self.assertIn('SleepDetector/Skip', body,
                      '应有 [SleepDetector/Skip] skip log marker')
        self.assertIn('Sir 只表态没真睡', body,
                      'skip 路径应 log "Sir 只表态没真睡"')


class TestC_PostSleepMonitorGuardsByEvidence(unittest.TestCase):
    """静态 check SleepDetector._post_sleep_monitor_loop 看 is_sleep_routine_fired."""

    def setUp(self):
        import jarvis_memory_core
        with open(jarvis_memory_core.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_loop_calls_is_sleep_routine_fired(self):
        """_post_sleep_monitor_loop 应调 is_sleep_routine_fired."""
        idx = self.src.find('def _post_sleep_monitor_loop')
        self.assertGreater(idx, 0)
        body = self.src[idx:idx + 3000]
        self.assertIn('is_sleep_routine_fired', body,
                      '_post_sleep_monitor_loop 应 check is_sleep_routine_fired')

    def test_loop_uses_fired_at_for_elapsed(self):
        """elapsed 起算改用 sleep_routine_age_seconds, 不是 _sleep_confirmed_at."""
        idx = self.src.find('def _post_sleep_monitor_loop')
        body = self.src[idx:idx + 3000]
        self.assertIn('sleep_routine_age_seconds', body,
                      '应用 sleep_routine_age_seconds 起算 elapsed (B9 治本)')

    def test_skip_log_marker_present(self):
        """没 routine fire 时应 skip log."""
        idx = self.src.find('def _post_sleep_monitor_loop')
        body = self.src[idx:idx + 3000]
        self.assertIn('PostSleepMonitor/Skip', body,
                      'skip 路径应 log marker [PostSleepMonitor/Skip]')


class TestD_WorkerRoutineCallsMark(unittest.TestCase):
    """静态 check worker._do_routine 完成时调 mark_sleep_routine_fired."""

    def setUp(self):
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_do_routine_calls_mark_fired(self):
        """_do_routine 应调 NudgeGate.mark_sleep_routine_fired."""
        self.assertIn('mark_sleep_routine_fired', self.src,
                      '_do_routine 应调 mark_sleep_routine_fired')
        # Fix-1.1 marker
        self.assertIn('Fix-1.1', self.src,
                      'Fix-1.1 marker 应在源码')


class TestE_DetectSleepIntentRenewalDedup(unittest.TestCase):
    """静态 check worker._detect_sleep_intent 同夜 renew dedup log."""

    def setUp(self):
        import jarvis_worker
        with open(jarvis_worker.__file__, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_renewal_flag_present(self):
        """_detect_sleep_intent 应有 _is_renewal flag."""
        self.assertIn('_is_renewal', self.src,
                      '_detect_sleep_intent 应有 _is_renewal flag (B6 治本)')

    def test_renewal_log_simplified(self):
        """renew 时 log 简短: [Sleep Intent/Renew]."""
        self.assertIn('[Sleep Intent/Renew]', self.src,
                      'renew log marker [Sleep Intent/Renew] 应 present')
        self.assertIn('Sir 二次表态', self.src,
                      'renew log 应说 Sir 二次表态')

    def test_renewal_threshold_5min(self):
        """renewal 判定阈值 5min 差异 (300s)."""
        idx = self.src.find('_is_renewal = True')
        self.assertGreater(idx, 0)
        # 看上下文有 300s threshold
        ctx = self.src[max(0, idx - 500):idx + 100]
        self.assertIn('< 300', ctx,
                      '应有 < 300s (5min) 阈值判 renewal')


if __name__ == '__main__':
    unittest.main()
