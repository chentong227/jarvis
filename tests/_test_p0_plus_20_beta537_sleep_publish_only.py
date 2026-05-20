# -*- coding: utf-8 -*-
"""[β.5.37-B / 2026-05-20] SleepDetector publish-only 改造.

Sir 14:39 校正: 中置信 'confirm' 路径不再 set pending state + handle_confirmation_response
硬 keyword match. SleepDetector.detect publish 'sleep_intent_signal' 到 SWM, 主脑看 evidence
自决问 Sir 或等待.

详 docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md §4.1.
"""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta537BSleepDetectorPublishesSignal(unittest.TestCase):
    """SleepDetector.detect 必须 publish 'sleep_intent_signal' 到 SWM."""

    def test_detect_publishes_signal_to_event_bus(self):
        from jarvis_memory_core import SleepIntentDetector
        from jarvis_utils import ConversationEventBus

        bus = ConversationEventBus()
        # register_global 让 SleepDetector.detect 能拿到 bus
        ConversationEventBus.register_global(bus)

        nerve = MagicMock()
        detector = SleepIntentDetector(nerve)
        detector._last_detect_time = 0  # bypass cooldown

        # 喂含 sleep keyword 的话 (触发 score > 0.3)
        with patch('jarvis_memory_core.get_quick_classifier') as mock_qc:
            mock_qc.return_value.is_available = True
            mock_qc.return_value.detect_sleep_intent = MagicMock(return_value='sleep')
            detector.detect("我准备去睡觉了")

        top = bus.top_n(n=10)
        sleep_signals = [e for e in top if e['type'] == 'sleep_intent_signal']
        self.assertGreater(len(sleep_signals), 0,
            "SleepDetector.detect 必须 publish 'sleep_intent_signal'")
        sig = sleep_signals[0]
        self.assertEqual(sig['source'], 'SleepDetector')
        self.assertIn('score', sig.get('metadata', {}))


class TestBeta537BNervePathNoLongerCallsConfirmation(unittest.TestCase):
    """central_nerve._detect_sleep_intent 不再调 handle_confirmation_response / request_confirmation."""

    def test_source_does_not_call_handle_confirmation(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # _detect_sleep_intent 函数体内不应有 handle_confirmation_response 调用
        idx = src.find('def _detect_sleep_intent(self')
        end = src.find('# [P0+12 / 2026-05-15] 语义清晰别名', idx)
        body = src[idx:end] if idx > 0 and end > idx else ''
        self.assertNotIn('detector.handle_confirmation_response(', body,
            '_detect_sleep_intent 函数体不应再调 handle_confirmation_response (β.5.37-B publish-only)')
        self.assertNotIn('detector.request_confirmation()', body,
            '_detect_sleep_intent 函数体不应再调 request_confirmation (β.5.37-B publish-only)')
        # 必须有 β.5.37-B marker
        self.assertIn('β.5.37-B', body,
            'β.5.37-B marker 必须在 _detect_sleep_intent 函数体')

    def test_handle_confirmation_response_marked_deprecated(self):
        """函数仍存在但 docstring 标 DEPRECATED β.5.37-B."""
        with open(os.path.join(ROOT, 'jarvis_memory_core.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('def handle_confirmation_response(self')
        end = src.find('def request_confirmation(self', idx)
        func = src[idx:end] if idx > 0 else ''
        self.assertIn('DEPRECATED', func,
            'handle_confirmation_response 必须标 DEPRECATED')
        self.assertIn('β.5.37-B', func,
            'handle_confirmation_response docstring 必须含 β.5.37-B marker')


if __name__ == '__main__':
    unittest.main()
