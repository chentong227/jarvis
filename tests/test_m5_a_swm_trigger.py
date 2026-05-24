"""[Reshape M5.A] tests for jarvis_swm_trigger.SWMTrigger daemon."""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jarvis_swm_trigger as swm_trig
from jarvis_swm_trigger import (
    SWMTrigger, TriggerHandler, _extract_reminder_fired,
    _extract_cyclic_task_due, _extract_watch_task_fired,
    _extract_generic_proactive, get_default_trigger,
    reset_default_trigger_for_test, publish_to_swm_trigger,
)


class TestExtractFunctions(unittest.TestCase):
    def test_reminder_fired_extract(self):
        ev = {
            'event_id': 'evt_abc',
            'metadata': {
                'commitment_description': 'sit up',
                'overdue_minutes': 5,
                'sleep_mode_active': False,
                'commitment_time': '14:30',
                'promise_id': 'prom_xyz',
            },
        }
        nctx = _extract_reminder_fired(ev)
        self.assertEqual(nctx['type'], 'commitment_check')
        self.assertEqual(nctx['commitment_description'], 'sit up')
        self.assertEqual(nctx['overdue_minutes'], 5)
        self.assertEqual(nctx['_swm_trigger_origin'], 'evt_abc')

    def test_cyclic_task_due_extract(self):
        ev = {
            'event_id': 'evt_c1',
            'metadata': {
                'task_id': 'hydration_2026',
                'kind': 'reminder',
                'description': 'drink water',
                'intent_template': 'time to hydrate',
            },
        }
        nctx = _extract_cyclic_task_due(ev)
        self.assertEqual(nctx['type'], 'cyclic_task_fire')
        self.assertEqual(nctx['task_id'], 'hydration_2026')

    def test_watch_task_fired_extract(self):
        ev = {
            'event_id': 'evt_w1',
            'metadata': {
                'task_id': 'wt_xx',
                'what_to_watch': 'video posted',
                'trigger_evidence': 'video URL detected',
                'rationale': 'screen shows post button clicked',
            },
        }
        nctx = _extract_watch_task_fired(ev)
        self.assertEqual(nctx['type'], 'watch_task_alert')
        self.assertEqual(nctx['task_id'], 'wt_xx')

    def test_generic_proactive_with_nudge_context(self):
        ev = {
            'event_id': 'evt_g1',
            'metadata': {
                'nudge_context': {
                    'type': 'sir_focused_observation',
                    'extra': 'data',
                },
            },
        }
        nctx = _extract_generic_proactive(ev)
        self.assertEqual(nctx['type'], 'sir_focused_observation')
        self.assertEqual(nctx['_swm_trigger_origin'], 'evt_g1')

    def test_generic_proactive_fallback(self):
        ev = {
            'event_id': 'evt_g2',
            'description': 'something happened',
            'metadata': {'nudge_type': 'observation_x'},
        }
        nctx = _extract_generic_proactive(ev)
        self.assertEqual(nctx['type'], 'observation_x')


class TestSWMTriggerCore(unittest.TestCase):
    def setUp(self):
        reset_default_trigger_for_test()
        self.worker = MagicMock()
        self.worker.push_command = MagicMock()
        self.trigger = SWMTrigger(worker_ref=self.worker)

    def tearDown(self):
        self.trigger.stop()
        reset_default_trigger_for_test()

    def test_make_event_key_with_event_id(self):
        ev = {'event_id': 'evt_xyz', 'etype': 'reminder_fired'}
        key = self.trigger._make_event_key(ev)
        self.assertEqual(key, 'evt_xyz')

    def test_make_event_key_fallback(self):
        ev = {'etype': 'reminder_fired', 'ts': 1700000000.5}
        key = self.trigger._make_event_key(ev)
        self.assertIn('reminder_fired', key)

    def test_dedup_recent(self):
        self.trigger._mark_processed('evt_abc')
        self.assertTrue(self.trigger._is_dedup_recent('evt_abc'))
        self.assertFalse(self.trigger._is_dedup_recent('evt_xyz'))

    def test_should_process_event_low_salience_filter(self):
        ev = {
            'etype': 'reminder_fired',
            'salience': 0.3,
            'metadata': {'fired_via': 'swm_trigger'},
        }
        self.assertFalse(self.trigger._should_process_event(ev))

    def test_should_process_event_unknown_etype(self):
        ev = {
            'etype': 'random_etype',
            'salience': 0.9,
            'metadata': {'fired_via': 'swm_trigger'},
        }
        self.assertFalse(self.trigger._should_process_event(ev))

    def test_should_process_event_old_path_skip(self):
        # fired_via=__NUDGE__ → 老 sentinel push 路径, daemon 跳过
        ev = {
            'etype': 'reminder_fired',
            'salience': 0.85,
            'metadata': {'fired_via': '__NUDGE__'},
        }
        self.assertFalse(self.trigger._should_process_event(ev))

    def test_should_process_reminder_fired_default_accept(self):
        # 'reminder_fired' / 'cyclic_task_due' / 'watch_task_fired' 默认接受
        # (M4.4/M4.5 sentinel dual-emit 时, daemon 启用即单源 trigger)
        ev = {
            'etype': 'reminder_fired',
            'salience': 0.85,
            'metadata': {},  # no fired_via
        }
        self.assertTrue(self.trigger._should_process_event(ev))

    def test_should_process_proactive_nudge_required_strict(self):
        # 'proactive_nudge_required' 必须 fired_via=swm_trigger
        ev_no = {
            'etype': 'proactive_nudge_required',
            'salience': 0.85,
            'metadata': {},
        }
        self.assertFalse(self.trigger._should_process_event(ev_no))

        ev_yes = {
            'etype': 'proactive_nudge_required',
            'salience': 0.85,
            'metadata': {'fired_via': 'swm_trigger'},
        }
        self.assertTrue(self.trigger._should_process_event(ev_yes))

    def test_process_event_pushes_command(self):
        ev = {
            'event_id': 'evt_proc',
            'etype': 'reminder_fired',
            'salience': 0.85,
            'metadata': {
                'commitment_description': 'walk',
                'overdue_minutes': 3,
            },
        }
        ok = self.trigger._process_event(ev)
        self.assertTrue(ok)
        self.assertEqual(self.worker.push_command.call_count, 1)
        # check pushed cmd starts with __NUDGE__:
        cmd_arg = self.worker.push_command.call_args[0][0]
        self.assertTrue(cmd_arg.startswith('__NUDGE__:'))
        self.assertIn('walk', cmd_arg)
        self.assertEqual(self.trigger._fired_count, 1)


class TestSingletonAndPublish(unittest.TestCase):
    def setUp(self):
        reset_default_trigger_for_test()

    def tearDown(self):
        reset_default_trigger_for_test()

    def test_get_default_trigger_singleton(self):
        worker = MagicMock()
        t1 = get_default_trigger(worker_ref=worker)
        t2 = get_default_trigger()
        self.assertIs(t1, t2)
        self.assertIs(t1.worker_ref, worker)

    def test_status_dump(self):
        from jarvis_swm_trigger import get_status
        s = get_status()
        self.assertEqual(s['state'], 'not_started')
        get_default_trigger(worker_ref=MagicMock())
        s2 = get_status()
        self.assertIn('subscribed', s2)
        self.assertIn('reminder_fired', s2['subscribed'])


if __name__ == '__main__':
    unittest.main()
