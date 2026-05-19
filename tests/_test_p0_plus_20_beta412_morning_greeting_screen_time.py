# -*- coding: utf-8 -*-
"""
[P0+20-β.4.12 / 2026-05-19] 早起 + 7h 误算 双 BUG 修

Sir 09:59 实测痛点 (跨夜睡眠 + 起床场景):
  1. 早起 Jarvis 没问好: 直接说 "10 点了, Integrity Stack 等您" — 像 Sir 没睡
     根因: ReturnSentinel _on_return 算出 is_first_today=True 但没传 nudge_ctx,
           LLM 看 STM 昨晚工作 → 自然引述工作 topic
  2. 错说 "您坐屏前 7 小时": Conductor path_a → WellnessGuardian
     根因: Sir 02:30 睡 → 09:30 起, work_category="AFK" 期间 work_session_start
           留在 02:30, work_duration_minutes=420. WellnessGuardian 看 work_duration > 180
           触发 wellness_alert. 但 Sir 在睡觉.
  3. 09:59:44 ReturnSentinel nudge + 09:59:49 Conductor 同源连推
     根因: stale wellness_alert flag (Sir 起床前 09:55 设的) 没 TTL, Conductor 立刻消费

修复 (准则 6 evidence-only / 通用):
  1. ReturnSentinel _on_return 注入 is_first_today + crosses_sleep_period + is_morning_window
  2. stream_nudge return_greeting directive 加 morning context evidence 分支
     (不教句式, 给主脑 evidence 让它自己涌现 morning tone)
  3. WellnessGuardian: work_category == "AFK" 时不算 work_duration > 180
  4. Conductor: wellness_alert / shield_alert 加 TTL 30min, 过期主动清
  5. Conductor: inter-source cooldown 60s (任何 source nudge 后 60s 不发新 path_a)
"""

from __future__ import annotations

import io
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# BUG 1: ReturnSentinel 注入早起 evidence
# ==========================================================================

class TestP0Plus20Beta412ReturnSentinelEvidence(unittest.TestCase):
    """ReturnSentinel _on_return 必须给 nudge_ctx 注入 is_first_today / crosses_sleep_period."""

    def test_source_contains_is_first_today_field(self):
        src_path = os.path.join(ROOT, 'jarvis_return_sentinel.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('"is_first_today"', src,
            'nudge_ctx 必须含 is_first_today 字段 (β.4.12 evidence injection)')
        self.assertIn('"crosses_sleep_period"', src,
            'nudge_ctx 必须含 crosses_sleep_period 字段')
        self.assertIn('"is_morning_window"', src,
            'nudge_ctx 必须含 is_morning_window 字段')

    def test_crosses_sleep_threshold_at_4h(self):
        """AFK > 4h (14400s) 才算跨夜睡眠."""
        src_path = os.path.join(ROOT, 'jarvis_return_sentinel.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('afk_duration > 14400', src,
            '跨夜睡眠阈值 4h (14400s) 必须用于 crosses_sleep_period 计算')

    def test_morning_window_5_to_12(self):
        """is_morning_window = 5 <= hour < 12."""
        src_path = os.path.join(ROOT, 'jarvis_return_sentinel.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('5 <= current_hour_for_ctx < 12', src,
            'is_morning_window 必须用 [5, 12) 计算')


# ==========================================================================
# BUG 1.b: stream_nudge directive 加 morning context evidence 分支
# ==========================================================================

class TestP0Plus20Beta412DirectiveMorningEvidence(unittest.TestCase):
    """stream_nudge return_greeting directive 必须含 morning context evidence."""

    def _get_chat_bypass_src(self):
        src_path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_directive_contains_morning_context_block(self):
        src = self._get_chat_bypass_src()
        self.assertIn('MORNING CONTEXT', src,
            'return_greeting directive 必须含 [MORNING CONTEXT] evidence 块')
        self.assertIn('is_first_today', src,
            'directive 必须引用 is_first_today 字段')

    def test_directive_does_not_teach_phrases(self):
        """evidence-only 准则 6: 不教 '早安'/'good morning' 等具体句式."""
        src = self._get_chat_bypass_src()
        # 提取 return_greeting directive 块
        start = src.find('"return_greeting":')
        self.assertGreater(start, 0)
        end = src.find('"commitment_check":', start)
        directive = src[start:end]
        # 不能命令主脑用某句具体话 (硬编码反例)
        forbidden_phrases = [
            'Say "早安"',
            'Say "Good morning"',
            "Say '早安'",
            'You must say "',
            'Always begin with "Good morning',
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, directive,
                f'directive 不应硬编码句式: {phrase}')

    def test_directive_lightweight_check_in_guidance(self):
        """morning evidence 应该建议 lightweight status check, 不重提工作."""
        src = self._get_chat_bypass_src()
        self.assertIn('lightweight', src,
            'morning directive 必须建议 lightweight check-in')
        self.assertIn("hasn't had coffee yet", src,
            'morning directive 必须 anchor "Sir hasnt had coffee yet" 防止重提工作')


# ==========================================================================
# BUG 2: WellnessGuardian work_category=AFK 时不该触发
# ==========================================================================

class TestP0Plus20Beta412WellnessAFKGuard(unittest.TestCase):
    """WellnessGuardian 在 AFK 时不应触发 break suggest."""

    def test_source_has_afk_continue_guard(self):
        src_path = os.path.join(ROOT, 'jarvis_sentinels.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 WellnessGuardian.run 块
        idx = src.find('class WellnessGuardian')
        self.assertGreater(idx, 0)
        wg_block = src[idx:idx+5000]
        self.assertIn('if work_category == "AFK"', wg_block,
            'WellnessGuardian.run 必须有 work_category == "AFK" guard (β.4.12)')
        # guard 必须在 should_suggest 计算之前 (early continue)
        afk_idx = wg_block.find('if work_category == "AFK":\n')
        elif_extended_idx = wg_block.find('elif work_duration > 180:')
        self.assertGreater(afk_idx, 0, 'AFK early-continue guard 必须存在')
        self.assertGreater(elif_extended_idx, 0)
        self.assertLess(afk_idx, elif_extended_idx,
            'AFK guard 必须在 "elif work_duration > 180" 触发分支之前')


# ==========================================================================
# BUG 3: Conductor wellness_alert TTL + inter-source cooldown
# ==========================================================================

class TestP0Plus20Beta412ConductorTTLAndCooldown(unittest.TestCase):
    """Conductor 必须看 alert timestamp TTL + NudgeGate cross-source cooldown."""

    def test_source_has_alert_ttl(self):
        src_path = os.path.join(ROOT, 'jarvis_conductor.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('ALERT_TTL_S', src,
            'Conductor 必须定义 ALERT_TTL_S 常量')
        self.assertIn('_is_alert_fresh', src,
            'Conductor 必须有 _is_alert_fresh helper')
        self.assertIn('1800', src,
            'TTL 应 30min = 1800s')

    def test_source_has_inter_source_cooldown(self):
        src_path = os.path.join(ROOT, 'jarvis_conductor.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('INTER_SOURCE_COOLDOWN_S', src,
            'Conductor 必须定义 INTER_SOURCE_COOLDOWN_S')
        self.assertIn('seconds_since_last', src,
            'Conductor 必须用 NudgeGate.seconds_since_last 做 cross-source cooldown')

    def test_stale_flag_cleanup(self):
        """陈旧 flag 必须主动清, 不让下次 tick 误报."""
        src_path = os.path.join(ROOT, 'jarvis_conductor.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找过期清理段
        self.assertIn('过期 (age >', src,
            'Conductor 必须主动清陈旧 alert flag')


# ==========================================================================
# 端到端验: 模拟 Sir 早起场景
# ==========================================================================

class TestP0Plus20Beta412EndToEndScenario(unittest.TestCase):
    """模拟 Sir 02:30 睡, 10:00 起 — 验所有 4 个 BUG 都治."""

    def test_check_path_a_skips_when_recent_nudge(self):
        """Conductor _check_path_a 在 NudgeGate 最近 nudge 后 60s 内不发新."""
        from jarvis_conductor import Conductor
        # 构造 minimal Conductor instance
        cond = Conductor.__new__(Conductor)
        cond._daily_action_count = 0
        cond._last_block_log_time = 0
        cond._block_log_interval = 300
        # Mock NudgeGate: 最近 5s 前 nudge
        mock_gate = MagicMock()
        mock_gate.seconds_since_last = MagicMock(return_value=5.0)
        cond.gate = mock_gate

        # 构造 wellness_alert active snapshot
        snapshot = {
            'shield_alert': {'active': False},
            'wellness_alert': {
                'active': True,
                'reason': 'extended screen time of 420 minutes',
                'timestamp': time.time(),
            }
        }
        result = cond._check_path_a(snapshot)
        self.assertIsNone(result,
            '5s 前刚 nudge → Conductor 必须 return None, 不抢话')

    def test_check_path_a_drops_stale_alert(self):
        """30min+ 前的 alert flag 必须被 TTL 拦截 + 清."""
        from jarvis_conductor import Conductor
        from jarvis_env_probe import PhysicalEnvironmentProbe
        cond = Conductor.__new__(Conductor)
        cond._daily_action_count = 0
        cond._last_block_log_time = 0
        cond._block_log_interval = 300
        mock_gate = MagicMock()
        mock_gate.seconds_since_last = MagicMock(return_value=999999.0)  # 老到不阻
        cond.gate = mock_gate

        stale_alert = {
            'active': True,
            'reason': 'extended screen time of 420 minutes',
            'timestamp': time.time() - 2000,  # 33min 前
        }
        PhysicalEnvironmentProbe._wellness_alert = dict(stale_alert)
        PhysicalEnvironmentProbe._shield_alert = {'active': False}
        snapshot = {
            'shield_alert': {'active': False},
            'wellness_alert': stale_alert
        }
        result = cond._check_path_a(snapshot)
        self.assertIsNone(result,
            'stale wellness_alert (33min 前) 必须被 TTL 拦截')
        # 清理后 _wellness_alert 应 active=False
        self.assertFalse(PhysicalEnvironmentProbe._wellness_alert.get('active'),
            '陈旧 wellness_alert 必须被主动清')

    def test_check_path_a_passes_fresh_alert(self):
        """新鲜 alert + 长时间无 nudge → 正常发."""
        from jarvis_conductor import Conductor
        from jarvis_env_probe import PhysicalEnvironmentProbe
        cond = Conductor.__new__(Conductor)
        cond._daily_action_count = 0
        cond._last_block_log_time = 0
        cond._block_log_interval = 300
        mock_gate = MagicMock()
        mock_gate.seconds_since_last = MagicMock(return_value=999999.0)
        cond.gate = mock_gate

        fresh_alert = {
            'active': True,
            'reason': 'real coding 120 min',
            'timestamp': time.time() - 60,  # 1min 前
        }
        PhysicalEnvironmentProbe._wellness_alert = dict(fresh_alert)
        PhysicalEnvironmentProbe._shield_alert = {'active': False}
        snapshot = {
            'shield_alert': {'active': False},
            'wellness_alert': fresh_alert
        }
        result = cond._check_path_a(snapshot)
        self.assertIsNotNone(result, '新鲜 alert + 无 cooldown → 应该发')
        self.assertEqual(result['source'], 'WellnessGuardian')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.4.12 morning greeting + 7h screen time tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
