# -*- coding: utf-8 -*-
"""β.5.40-A2 — PhysioProxy tests (Sir 方向 A.2)"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta540A2Module(unittest.TestCase):
    def test_imports(self):
        import jarvis_physio_proxy as pp
        for sym in ('PhysioProxy', 'PhysioState', 'compute_physio_state',
                    'get_physio_proxy', 'DEFAULT_BASELINE', '_norm_clip'):
            self.assertTrue(hasattr(pp, sym))


class TestBeta540A2ComputeState(unittest.TestCase):
    def test_session_too_short_returns_zero_confidence(self):
        from jarvis_physio_proxy import compute_physio_state
        s = compute_physio_state(key_5min=100, session_age_s=10)
        self.assertEqual(s.confidence, 0.0)
        self.assertEqual(s.energy, 0.0)

    def test_normal_data_computes(self):
        from jarvis_physio_proxy import compute_physio_state
        s = compute_physio_state(
            key_5min=200,
            mouse_dist_5min=5000,
            backspace_ratio=0.05,
            burst_pause_ratio=0.5,
            switch_freq_5min=3,
            shortcut_undo_5min=0,
            session_age_s=600,
        )
        self.assertGreater(s.confidence, 0.5, 'normal session 有数据应高 conf')
        # 5min normal: energy~0.5, focus~0.85+, stress<0.1
        self.assertAlmostEqual(s.energy, 0.5, delta=0.1)
        self.assertGreater(s.focus, 0.7, '低 bsr + 少 switch → 高 focus')
        self.assertLess(s.stress, 0.2, '低 bsr → 低 stress')

    def test_high_stress_detected(self):
        from jarvis_physio_proxy import compute_physio_state
        s = compute_physio_state(
            key_5min=300,
            mouse_dist_5min=8000,
            backspace_ratio=0.25,  # 高
            burst_pause_ratio=0.1,  # erratic
            switch_freq_5min=10,
            shortcut_undo_5min=6,   # 高
            session_age_s=1200,
        )
        self.assertGreater(s.stress, 0.5, '高 bsr+undo+erratic → stress > 0.5')

    def test_high_focus_detected(self):
        from jarvis_physio_proxy import compute_physio_state
        s = compute_physio_state(
            key_5min=400,
            backspace_ratio=0.03,  # 极低
            switch_freq_5min=1,
            shortcut_undo_5min=0,
            session_age_s=900,
        )
        self.assertGreater(s.focus, 0.8, '低 bsr+少 switch → focus > 0.8')

    def test_clamp_range(self):
        from jarvis_physio_proxy import compute_physio_state
        s = compute_physio_state(
            key_5min=99999, mouse_dist_5min=99999,
            backspace_ratio=2.0, switch_freq_5min=999, shortcut_undo_5min=999,
            session_age_s=99999,
        )
        for v in (s.energy, s.focus, s.stress, s.confidence):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


class TestBeta540A2NormClip(unittest.TestCase):
    def test_zero(self):
        from jarvis_physio_proxy import _norm_clip
        self.assertEqual(_norm_clip(0, 100, 500), 0.0)

    def test_p50_maps_to_0_5(self):
        from jarvis_physio_proxy import _norm_clip
        self.assertAlmostEqual(_norm_clip(100, 100, 500), 0.5, places=2)

    def test_p90_maps_to_0_9(self):
        from jarvis_physio_proxy import _norm_clip
        self.assertAlmostEqual(_norm_clip(500, 100, 500), 0.9, places=2)

    def test_clip_at_1(self):
        from jarvis_physio_proxy import _norm_clip
        self.assertLessEqual(_norm_clip(9999, 100, 500), 1.0)


class TestBeta540A2Publish(unittest.TestCase):
    def setUp(self):
        import jarvis_physio_proxy as pp
        pp._GLOBAL_PROXY = None

    def test_no_bus_no_publish(self):
        from jarvis_physio_proxy import PhysioProxy
        p = PhysioProxy(event_bus=None, enabled=True)
        snap = {'key_press_count_5min': 200, 'session_duration_minutes': 10}
        r = p.compute_and_publish(snap)
        self.assertIsNone(r)

    def test_with_bus_publishes(self):
        from jarvis_physio_proxy import PhysioProxy
        calls = []

        class Fb:
            def publish(self, **kw):
                calls.append(kw)
                return True

        p = PhysioProxy(event_bus=Fb(), enabled=True)
        snap = {
            'key_press_count_5min': 200,
            'mouse_distance_5min': 5000,
            'backspace_ratio': 0.05,
            'switch_frequency_5min': 3,
            'session_duration_minutes': 10,
        }
        s = p.compute_and_publish(snap)
        self.assertIsNotNone(s)
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(calls[0]['etype'], 'physio_state')

    def test_cooldown_prevents_repeat(self):
        from jarvis_physio_proxy import PhysioProxy
        calls = []

        class Fb:
            def publish(self, **kw):
                calls.append(kw)
                return True

        p = PhysioProxy(event_bus=Fb(), enabled=True)
        snap = {
            'key_press_count_5min': 200,
            'session_duration_minutes': 10,
        }
        p.compute_and_publish(snap)
        p.compute_and_publish(snap)  # cooldown 内
        self.assertEqual(len(calls), 1, '60s cooldown 期内只 1 次')


class TestBeta540A2SWMEtype(unittest.TestCase):
    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        import jarvis_physio_proxy  # noqa
        self.assertIn('physio_state', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('physio_state', ConversationEventBus.DEFAULT_SALIENCE)


class TestBeta540A2Directive(unittest.TestCase):
    def test_trigger(self):
        from jarvis_directives import _trigger_physio_state_judge, DirectiveContext
        ctx = DirectiveContext(current_hour=10, user_input='')
        r = _trigger_physio_state_judge(ctx)
        self.assertIsInstance(r, bool)

    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='physio_state_judge'", src)
        self.assertIn('_trigger_physio_state_judge', src)

    def test_vocab_json_entry(self):
        import json
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  'r', encoding='utf-8') as f:
            v = json.load(f)
        ids = [d.get('id') for d in v.get('directives', [])]
        self.assertIn('physio_state_judge', ids)


class TestBeta540A2ProactiveCarePublish(unittest.TestCase):
    def test_proactive_care_has_publish_block(self):
        with open(os.path.join(ROOT, 'jarvis_proactive_care.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.40-A2', src)
        self.assertIn('get_physio_proxy', src)


if __name__ == '__main__':
    unittest.main()
