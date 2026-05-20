# -*- coding: utf-8 -*-
"""β.5.43-A — Jarvis State Tracker (HUD 状态条) tests."""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta543AStateTracker(unittest.TestCase):
    def setUp(self):
        import jarvis_state_tracker as jst
        jst._TRACKER = None  # reset singleton

    def test_imports(self):
        import jarvis_state_tracker as jst
        for sym in ('JarvisStateTracker', 'get_state_tracker',
                     'set_state', 'get_state',
                     'STATE_READY', 'STATE_THINKING', 'STATE_SPEAKING',
                     'STATE_LISTENING', 'STATE_FOCUSED', 'STATE_ERROR',
                     'ALL_STATES', 'STATE_DISPLAY'):
            self.assertTrue(hasattr(jst, sym), f'必须有 {sym}')

    def test_initial_state_is_ready(self):
        from jarvis_state_tracker import get_state_tracker, STATE_READY
        t = get_state_tracker()
        self.assertEqual(t.get_state(), STATE_READY)

    def test_transition_to_thinking(self):
        from jarvis_state_tracker import (
            get_state_tracker, STATE_READY, STATE_THINKING
        )
        t = get_state_tracker()
        ok = t.set_state(STATE_THINKING, reason='llm_started')
        self.assertTrue(ok)
        self.assertEqual(t.get_state(), STATE_THINKING)
        # 二次 set 同 state 不算 transition
        ok2 = t.set_state(STATE_THINKING, reason='still_thinking')
        self.assertFalse(ok2)

    def test_invalid_state_rejected(self):
        from jarvis_state_tracker import get_state_tracker
        t = get_state_tracker()
        ok = t.set_state('UNKNOWN', reason='test')
        self.assertFalse(ok)

    def test_swm_publish_on_transition(self):
        from jarvis_state_tracker import get_state_tracker, STATE_THINKING
        publish_calls = []

        class FakeBus:
            def publish(self, **kw):
                publish_calls.append(kw)
                return True

        t = get_state_tracker(event_bus=FakeBus())
        t.set_state(STATE_THINKING, reason='test')
        self.assertGreaterEqual(len(publish_calls), 1)
        self.assertEqual(publish_calls[0]['etype'], 'jarvis_state')
        meta = publish_calls[0]['metadata']
        self.assertEqual(meta['new_state'], 'thinking')
        self.assertEqual(meta['reason'], 'test')

    def test_subtitle_emit_on_transition(self):
        from jarvis_state_tracker import (
            get_state_tracker, STATE_SPEAKING, STATE_DISPLAY
        )
        queue_items = []

        class FakeQ:
            def put(self, item):
                queue_items.append(item)

        t = get_state_tracker(subtitle_queue=FakeQ())
        t.set_state(STATE_SPEAKING, reason='tts_started')
        self.assertGreaterEqual(len(queue_items), 1)
        kind, payload = queue_items[0]
        self.assertEqual(kind, 'jarvis_state')
        self.assertEqual(payload['state'], 'speaking')
        self.assertEqual(payload['emoji'], STATE_DISPLAY['speaking']['emoji'])

    def test_history_tracking(self):
        from jarvis_state_tracker import (
            get_state_tracker, STATE_THINKING, STATE_SPEAKING, STATE_READY
        )
        t = get_state_tracker()
        t.set_state(STATE_THINKING, reason='a')
        t.set_state(STATE_SPEAKING, reason='b')
        t.set_state(STATE_READY, reason='c')
        hist = t.get_recent_history(5)
        self.assertEqual(len(hist), 3)
        self.assertEqual(hist[-1]['to'], 'ready')

    def test_snapshot_has_display(self):
        from jarvis_state_tracker import get_state_tracker, STATE_FOCUSED
        t = get_state_tracker()
        t.set_state(STATE_FOCUSED, reason='nudge_focus_lock')
        snap = t.get_snapshot()
        self.assertEqual(snap['state'], 'focused')
        self.assertIn('emoji', snap['display'])
        self.assertIn('label_en', snap['display'])
        self.assertIn('label_zh', snap['display'])
        self.assertGreater(snap['age_seconds'], -0.1)

    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        import jarvis_state_tracker  # noqa: register
        self.assertIn('jarvis_state', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('jarvis_state', ConversationEventBus.DEFAULT_SALIENCE)


class TestBeta543AWorkerHook(unittest.TestCase):
    """jarvis_worker.py 必须 hook tracker 到 set_speaking_state + ASR listening."""

    def test_set_speaking_state_hooks_tracker(self):
        with open(os.path.join(ROOT, 'jarvis_worker.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.43-A', src, 'worker 必须含 β.5.43-A marker')
        self.assertIn('from jarvis_state_tracker import', src)
        self.assertIn('STATE_SPEAKING', src)
        self.assertIn('STATE_LISTENING', src,
                      'ASR voice detected 必须 set LISTENING')


class TestBeta543ADashboardAPI(unittest.TestCase):
    """dashboard /api/state endpoint + HUD UI."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        try:
            from jarvis_dashboard_web import app
        except Exception as e:
            raise unittest.SkipTest(f'Flask app unavailable: {e}')
        cls.client = app.test_client()

    def test_api_state_returns_json(self):
        rv = self.client.get('/api/state')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertTrue(data.get('ok'))
        self.assertIn('state', data)
        self.assertIn('display', data)

    def test_dashboard_html_has_hud_badge(self):
        rv = self.client.get('/')
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        self.assertIn('β.5.43-A', body, '老 dashboard 必须含 β.5.43-A HUD 标记')
        self.assertIn('jarvisState', body, 'Alpine state 必须含 jarvisState')
        self.assertIn('fetchJarvisState', body, '必须含 fetch 函数')


if __name__ == '__main__':
    unittest.main()
