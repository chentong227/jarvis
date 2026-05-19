# -*- coding: utf-8 -*-
"""
[P0+20-β.5.5-β.5.7 / 2026-05-19] β.5 完整重构收尾

接 β.5.4 Conductor publish-only, β.5.5+ 让 SmartNudge / ReturnSentinel skip
也 publish 'gate_advice' 到 SWM, 主脑能看到完整 picture.

β.5.5 ReturnSentinel _on_return skip publish (5 个 skip 点):
  - greeting_cooldown
  - afk_too_short_<X>s
  - startup_guard_<X>s_remaining
  - in_active_conversation
  - last_conv_end_<X>s_ago
  - media_window_foreground

β.5.6 SmartNudge.run skip publish (4 个 skip 点 + helper dedupe):
  - daily_quota_exhausted
  - in_active_conversation
  - bypass_speech_count_<N>
  - standby_silence_<X>s_since_conv_off
  - helper: 60s 内同 reason 1 次 + 5min GC

β.5.7 vocab 全切 publish_only:
  - 6 sentinel 都标 publish_only (NudgeGate/OfferGuard 真 publish_only,
    其他 4 个是 SWM 信号语义 — skip 时 publish gate_advice)
  - 加 note_publish_only_partial 说明区分
  - history 加 β.5.5-β.5.7 节点

测试覆盖:
  A. ReturnSentinel 6 skip 点都有 _publish_skip 调用
  B. SmartNudge run() 含 _publish_skip helper + 4 skip 点
  C. vocab 6 sentinel 全 publish_only + note_publish_only_partial 存在
"""

from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# A: ReturnSentinel skip publish (β.5.5)
# ==========================================================================

class TestBeta55ReturnSentinelSkipPublish(unittest.TestCase):
    def _src(self):
        path = os.path.join(ROOT, 'jarvis_return_sentinel.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_publish_skip_helper_defined(self):
        src = self._src()
        self.assertIn('def _publish_skip(skip_reason: str', src,
            'ReturnSentinel _on_return 必须含 _publish_skip helper (β.5.5)')

    def test_publish_skip_uses_gate_advice_source_returnsentinel(self):
        src = self._src()
        idx = src.find('def _publish_skip(skip_reason')
        block = src[idx:idx+2500]
        self.assertIn("etype='gate_advice'", block)
        self.assertIn("source='ReturnSentinel'", block)

    def test_skip_reasons_publish(self):
        """6 个 skip 点都有 _publish_skip 调用."""
        src = self._src()
        expected_reasons = (
            'greeting_cooldown_',
            'afk_too_short_',
            'startup_guard_',
            'in_active_conversation',
            'last_conv_end_',
            'media_window_foreground',
        )
        for r in expected_reasons:
            self.assertIn(r, src,
                f"ReturnSentinel _publish_skip 应含 skip_reason='{r}'")


# ==========================================================================
# B: SmartNudge skip publish (β.5.6)
# ==========================================================================

class TestBeta56SmartNudgeSkipPublish(unittest.TestCase):
    def _src(self):
        path = os.path.join(ROOT, 'jarvis_smart_nudge.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_publish_skip_helper_with_dedupe(self):
        src = self._src()
        self.assertIn('_skip_publish_last_t', src,
            'SmartNudge run() 必须含 _skip_publish_last_t dedupe state (β.5.6)')
        self.assertIn('def _publish_skip(skip_reason: str', src,
            'SmartNudge run() 必须含 _publish_skip helper')

    def test_skip_publish_uses_gate_advice_source_smartnudge(self):
        src = self._src()
        idx = src.find('def _publish_skip(skip_reason')
        block = src[idx:idx+2000]
        self.assertIn("etype='gate_advice'", block)
        self.assertIn("source='SmartNudge'", block)

    def test_smartnudge_skip_reasons_publish(self):
        src = self._src()
        expected = (
            'daily_quota_exhausted',
            'in_active_conversation',
            'bypass_speech_count_',
            'standby_silence_',
        )
        for r in expected:
            self.assertIn(r, src,
                f"SmartNudge _publish_skip 应含 skip_reason='{r}'")

    def test_skip_dedupe_60s_window(self):
        """SmartNudge skip publish helper 必须 60s dedupe (防风暴)."""
        src = self._src()
        idx = src.find('def _publish_skip(skip_reason')
        block = src[idx:idx+1500]
        self.assertIn('< 60.0', block,
            'SmartNudge _publish_skip 必须 60s dedupe window')


# ==========================================================================
# C: vocab 全 publish_only (β.5.7)
# ==========================================================================

class TestBeta57VocabFullPublishOnly(unittest.TestCase):
    def _load(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_all_6_sentinels_publish_only(self):
        data = self._load()
        current = data.get('current', {})
        for s in ('NudgeGate', 'OfferGuard', 'SmartNudgeSentinel',
                  'Conductor', 'WellnessGuardian', 'ReturnSentinel'):
            self.assertEqual(current.get(s), 'publish_only',
                f'{s} 必须 publish_only (β.5.7)')

    def test_note_publish_only_partial_exists(self):
        """vocab 必须含 note_publish_only_partial 区分真 publish_only 与 SWM 信号 publish."""
        data = self._load()
        self.assertIn('note_publish_only_partial', data,
            'vocab 必须含 note_publish_only_partial 说明区分')

    def test_history_records_beta55_through_57(self):
        data = self._load()
        history = data.get('history', [])
        self.assertGreaterEqual(len(history), 3,
            'vocab history 应记录 init / β.5.3 / β.5.5-β.5.7 三个变更')
        last = history[-1]
        self.assertIn('β.5.5', last['change'])


# ==========================================================================
# D: Conductor publish-only signal (β.5.4 收编)
# ==========================================================================

class TestBeta54ConductorPublishSignal(unittest.TestCase):
    def test_conductor_check_path_a_publishes_intent(self):
        path = os.path.join(ROOT, 'jarvis_conductor.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('def _check_path_a')
        block = src[idx:idx+3500]
        self.assertIn("source='Conductor'", block,
            'Conductor _check_path_a 必须 publish source=Conductor (β.5.4)')
        self.assertIn('has_shield_alert', block)
        self.assertIn('has_wellness_alert', block)


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.5-β.5.7 收尾 tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
