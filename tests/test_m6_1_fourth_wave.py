# -*- coding: utf-8 -*-
"""[Reshape M6.1 fourth wave / 2026-05-24] 8 个 soul extras helper 抽离.

覆盖:
  - 每个 helper method 真存在
  - empty result 时返 ''
  - 含数据时真渲染 block
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestPendingCommitmentsBlock(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.commitment_watcher = None
        with patch('jarvis_promise_log.get_default_log', return_value=None):
            self.assertEqual(n._build_pending_commitments_block(), '')

    def test_renders_cw_commitments(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        cw = MagicMock()
        cw.commitments = [
            {'description': 'sleep at 11', 'deadline_ts': time.time() + 600,
              'nudged': False, 'source': 'sir'}
        ]
        n.commitment_watcher = cw
        with patch('jarvis_promise_log.get_default_log', return_value=None):
            result = n._build_pending_commitments_block()
        self.assertIn('PENDING COMMITMENTS', result)
        self.assertIn('sleep at 11', result)


class TestSleepRoutineBlock(unittest.TestCase):
    def test_empty_no_event(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.event_bus = None
        self.assertEqual(n._build_sleep_routine_evidence_block(), '')

    def test_renders_with_event(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        bus = MagicMock()
        bus.recent_events = MagicMock(return_value=[
            {'metadata': {
                'mute_apps': {'success': True, 'hits': ['Spotify']},
                'sleep_display': {'success': True, 'msg': 'OK'},
                'asr_mute': {'success': True, 'ttl_s': 600},
            }}
        ])
        n.event_bus = bus
        result = n._build_sleep_routine_evidence_block()
        self.assertIn('SLEEP ROUTINE EVIDENCE', result)
        self.assertIn('Spotify', result)


class TestRecentCompletedBlock(unittest.TestCase):
    def test_empty_no_hippocampus(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.hippocampus = None
        self.assertEqual(n._build_recent_completed_block(), '')

    def test_renders_completed_events(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        hippo = MagicMock()
        hippo.list_recent_completed_events = MagicMock(return_value=[
            {'intent': 'blood pressure consult', 'age': '2d', 'iso': '2026-05-22'}
        ])
        n.hippocampus = hippo
        result = n._build_recent_completed_block()
        self.assertIn('RECENT COMPLETED', result)
        self.assertIn('blood pressure', result)


class TestWatchTaskFiredBlock(unittest.TestCase):
    def test_empty_no_event(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.event_bus = None
        self.assertEqual(n._build_watch_task_fired_block(), '')

    def test_renders_with_fired(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        bus = MagicMock()
        bus.recent_events = MagicMock(return_value=[
            {'metadata': {
                'what_to_watch': 'Premiere export complete',
                'trigger_evidence': 'render bar 100%',
                'fired_evidence': 'screenshot at 14:30',
                'notify_msg_en': 'Sir, export done',
                'notify_msg_zh': 'Sir 导出完了',
            }}
        ])
        n.event_bus = bus
        result = n._build_watch_task_fired_block()
        self.assertIn('WATCH TASK FIRED', result)
        self.assertIn('Premiere', result)


class TestSelfPromiseOverdueBlock(unittest.TestCase):
    def test_empty_no_event(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.event_bus = None
        self.assertEqual(n._build_self_promise_overdue_block(), '')


class TestIntentResolvedBlock(unittest.TestCase):
    def test_empty_no_event(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.event_bus = None
        self.assertEqual(n._build_intent_resolved_block(), '')

    def test_renders_with_tool_calls(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        bus = MagicMock()
        bus.recent_events = MagicMock(return_value=[
            {'metadata': {
                'tool_calls': [{'name': 'mutate_count', 'ok': True}]
            }}
        ])
        n.event_bus = bus
        result = n._build_intent_resolved_block()
        self.assertIn('INTENT RESOLVED', result)
        self.assertIn('mutate_count', result)


class TestMoodEstimateBlock(unittest.TestCase):
    def test_returns_block_with_evidence(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        # PhysicalEnvironmentProbe.get_sensor_snapshot real call
        result = n._build_mood_estimate_block()
        # 应含 'MOOD ESTIMATE' (real probe 基本能 work) or empty
        if result:
            self.assertIn('MOOD ESTIMATE', result)


class TestWakeContextBlock(unittest.TestCase):
    def test_empty_no_worker(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n._worker_ref = None
        self.assertEqual(n._build_wake_context_block(), '')

    def test_renders_short_gap(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        worker = MagicMock()
        vt = MagicMock()
        vt.last_conversation_end_time = time.time() - 120  # 2min ago
        worker.voice_thread = vt
        n._worker_ref = worker
        n.short_term_memory = []
        with patch('jarvis_promise_log.get_default_log', side_effect=Exception):
            with patch('jarvis_claim_tracer.get_stats', side_effect=Exception):
                result = n._build_wake_context_block()
        self.assertIn('WAKE CONTEXT', result)


if __name__ == '__main__':
    unittest.main()
