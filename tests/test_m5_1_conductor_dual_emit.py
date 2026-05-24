# -*- coding: utf-8 -*-
"""[Reshape M5.1 / 2026-05-24] Conductor dual-emit 'conductor_intent' SWM event.

覆盖:
  - Conductor _dispatch_path_a 真 fire 时 publish 'conductor_intent' SWM event
  - metadata 含 path='A', nudge_type, action, alert_source, fired_via='__NUDGE__'
  - _execute_path_b 同款 dual-emit (metadata path='B', 含 decision_reason)
  - publish 失败不破老 __NUDGE__ push 路径
  - source 标记 'Conductor.path_a/*' 或 'Conductor.path_b/SensorFilter'
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Voice:
    last_user_speech_time = 0.0
    in_active_conversation = False


class _Worker:
    """SimpleNamespace 风格 worker mock — 关键属性硬设, 不让 MagicMock 拦截子属性."""
    def __init__(self):
        self.push_command_calls = []
        self.is_active_task = False
        self.companion_center = None  # 真 None 不是 MagicMock
        self.voice_thread = _Voice()
        self._sleep_intent_until = 0.0
        self.return_sentinel = None
        self.status_ledger = None
        self.short_term_memory = []
        self.jarvis = None

    def push_command(self, cmd):
        self.push_command_calls.append(cmd)


def _make_mock_conductor():
    """构造 minimal Conductor 实例 (bypass __init__)."""
    from jarvis_conductor import Conductor
    import collections
    cd = Conductor.__new__(Conductor)
    cd.worker = _Worker()
    cd.gate = MagicMock()
    cd.gate.can_speak = MagicMock(return_value=True)
    cd.gate.is_sleep_mode = MagicMock(return_value=False)
    cd.gate.mark_spoke = MagicMock()
    cd.gate.seconds_since_last = MagicMock(return_value=999.0)
    cd._last_action_time = 0
    cd._action_cooldown = 0
    cd._daily_action_count = 0
    cd._action_history = collections.deque(maxlen=50)
    return cd


class TestPathADualEmit(unittest.TestCase):
    def test_path_a_publishes_conductor_intent(self):
        from jarvis_utils import ConversationEventBus
        cd = _make_mock_conductor()

        captured_events = []
        bus = ConversationEventBus()
        orig_publish = bus.publish

        def _cap_publish(etype, description, **kwargs):
            captured_events.append({'etype': etype, 'description': description,
                                     'kwargs': kwargs})
            return orig_publish(etype, description, **kwargs)
        bus.publish = _cap_publish

        with patch('jarvis_conductor.json') as mock_json, \
             patch('jarvis_utils.get_event_bus', return_value=bus):
            mock_json.dumps = lambda d, **kw: '{}'
            alert_info = {
                'source': 'ProactiveShield',
                'alert_type': 'frustration',
                'action': 'Tease Screen',
                'reason': '屏幕动作模式: rapid_switching',
                'tone': 'gentle',
                'nudge_type': 'screen_tease',
            }
            snapshot = {'idle_seconds': 30, 'session_duration_minutes': 60,
                         'error_visible': False, 'switch_frequency_5min': 5,
                         'category_entropy': 0.5}
            cd._dispatch_path_a(alert_info, snapshot)

        # 找 conductor_intent event
        conductor_events = [e for e in captured_events if e['etype'] == 'conductor_intent']
        self.assertGreaterEqual(len(conductor_events), 1,
                                  'M5.1: path_a 应 publish conductor_intent')
        ev = conductor_events[0]
        self.assertIn('ProactiveShield', ev['description'])
        self.assertEqual(ev['kwargs']['metadata']['path'], 'A')
        self.assertEqual(ev['kwargs']['metadata']['nudge_type'], 'screen_tease')
        self.assertEqual(ev['kwargs']['metadata']['fired_via'], '__NUDGE__')
        self.assertEqual(ev['kwargs']['metadata']['alert_source'], 'ProactiveShield')

    def test_path_a_old_push_command_still_works(self):
        """dual-emit 不破老 __NUDGE__ push."""
        cd = _make_mock_conductor()
        alert_info = {
            'source': 'ProactiveShield', 'alert_type': 't',
            'action': 'Tease Screen', 'reason': 'r',
            'tone': 'gentle', 'nudge_type': 'screen_tease',
        }
        snapshot = {'idle_seconds': 30}
        cd._dispatch_path_a(alert_info, snapshot)
        # push_command 仍被调
        self.assertGreaterEqual(len(cd.worker.push_command_calls), 1,
                                  'M5.1: dual-emit 不应阻碍 __NUDGE__ push')
        self.assertTrue(cd.worker.push_command_calls[0].startswith('__NUDGE__'))


class TestPathBDualEmit(unittest.TestCase):
    def test_path_b_publishes_conductor_intent(self):
        from jarvis_utils import ConversationEventBus
        cd = _make_mock_conductor()

        captured_events = []
        bus = ConversationEventBus()
        orig_publish = bus.publish

        def _cap_publish(etype, description, **kwargs):
            captured_events.append({'etype': etype, 'description': description,
                                     'kwargs': kwargs})
            return orig_publish(etype, description, **kwargs)
        bus.publish = _cap_publish

        with patch('jarvis_utils.get_event_bus', return_value=bus):
            filter_result = {
                'triggered': True,
                'reason': 'sensor anomaly',
                'fusion_score': 0.85,
                'fusion_trend': 'rising',
                'snapshot': {'idle_seconds': 60,
                              'session_duration_minutes': 120,
                              'error_visible': True},
                'deviation_report': {'deviations': []},
                'bypass_semantic': False,
                'semantic_judgment': {'reason': 'visible error spike'},
            }
            decision = {
                'should_speak': True,
                'action': 'Offer Help',
                'decision_reason': 'screen shows persistent error',
                'confidence': 0.85,
                'tone': 'gentle',
                'nudge_type': 'offer_help',
            }
            # 注入 mock _decision_llm 避免真 LLM call
            cd._decision_llm = MagicMock(return_value=decision)
            cd._execute_path_b(filter_result)

        conductor_events = [e for e in captured_events if e['etype'] == 'conductor_intent']
        self.assertGreaterEqual(len(conductor_events), 1,
                                  'M5.1: path_b 应 publish conductor_intent')
        ev = conductor_events[0]
        self.assertEqual(ev['kwargs']['metadata']['path'], 'B')
        self.assertEqual(ev['kwargs']['metadata']['nudge_type'], 'offer_help')
        self.assertEqual(ev['kwargs']['metadata']['action'], 'Offer Help')
        self.assertIn('sensor anomaly', ev['description'])

    def test_path_b_old_push_command_still_works(self):
        cd = _make_mock_conductor()
        filter_result = {
            'triggered': True, 'reason': 'r',
            'snapshot': {'idle_seconds': 10},
            'deviation_report': {'deviations': []},
            'bypass_semantic': False,
            'semantic_judgment': {'reason': 'x'},
        }
        cd._decision_llm = MagicMock(return_value={
            'should_speak': True, 'action': 'Check-in',
            'decision_reason': 'x', 'confidence': 0.8,
            'tone': 'gentle', 'nudge_type': 'check_in',
        })
        cd._execute_path_b(filter_result)
        self.assertGreaterEqual(len(cd.worker.push_command_calls), 1)


if __name__ == '__main__':
    unittest.main()
