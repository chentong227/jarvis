# -*- coding: utf-8 -*-
"""[P0+20-β.2.8 / 2026-05-17] ProactiveCareEngine 单测

测点:
- CareSignalCollector urgency 公式 (base/recency/density/pressure/fatigue/L0)
- CareWindowGuard 7 条拒绝路径 (cooldown / night / sleep / active_conv / ...)
- CareSubjectSelector keyword 抽取 + STM/L2 素材查找
- CareSpeechSynth directive 构造 + dry_run 不真 push
- ProactiveCareEngine warm-up + threshold + tick log
- 单例 get_default_engine
- nudge_directive 覆盖路径 (chat_bypass.stream_nudge 行为)
"""
import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.pop('JARVIS_PROACTIVE_CARE_LIVE', None)


def _mock_concern(cid='sir_hydration', sev=0.7, last_triggered=0.0,
                   recent_signals=None, what='Sir water intake during long sessions'):
    """构造一个有 Concern 接口的 mock object."""
    c = MagicMock()
    c.id = cid
    c.severity = sev
    c.last_triggered = last_triggered
    c.recent_signals = recent_signals or []
    c.what_i_watch = what
    c.why_i_care = 'kidney + cognition'
    c.triggers_proactive = True
    return c


def _now():
    return time.time()


class TestCareSignalCollector(unittest.TestCase):
    def setUp(self):
        from jarvis_proactive_care import CareSignalCollector
        self.col = CareSignalCollector(ledger=None, anchor=None, nerve=None)

    def test_base_severity_affects_urgency(self):
        c_low = _mock_concern(sev=0.1)
        c_high = _mock_concern(sev=0.9)
        u_low, _ = self.col.compute_urgency(c_low, _now())
        u_high, _ = self.col.compute_urgency(c_high, _now())
        self.assertGreater(u_high, u_low)

    def test_recent_signal_increases_urgency(self):
        now = _now()
        c_old = _mock_concern(sev=0.5, recent_signals=[
            {'when': now - 72 * 3600, 'what': 'old signal'}
        ])
        c_fresh = _mock_concern(sev=0.5, recent_signals=[
            {'when': now - 600, 'what': 'fresh signal'}
        ])
        u_old, _ = self.col.compute_urgency(c_old, now)
        u_fresh, _ = self.col.compute_urgency(c_fresh, now)
        self.assertGreater(u_fresh, u_old)

    def test_signal_density(self):
        now = _now()
        many = [{'when': now - i * 1200, 'what': f's{i}'} for i in range(10)]
        c = _mock_concern(sev=0.5, recent_signals=many)
        _, bd = self.col.compute_urgency(c, now)
        self.assertEqual(bd['signal_density'], 1.0)

    def test_silence_pressure_builds(self):
        now = _now()
        c_recent = _mock_concern(sev=0.5, last_triggered=now - 60)
        c_quiet = _mock_concern(sev=0.5, last_triggered=now - 20 * 3600)
        u_r, _ = self.col.compute_urgency(c_recent, now)
        u_q, _ = self.col.compute_urgency(c_quiet, now)
        self.assertGreater(u_q, u_r)

    def test_fatigue_penalty(self):
        c = _mock_concern(sev=0.8)
        u_no, _ = self.col.compute_urgency(c, _now(), fatigue_count=0)
        u_some, _ = self.col.compute_urgency(c, _now(), fatigue_count=3)
        self.assertLess(u_some, u_no)
        self.assertGreater(u_some, 0.0)  # 有底

    def test_triggers_proactive_filter(self):
        from jarvis_proactive_care import CareSignalCollector
        ledger = MagicMock()
        c1 = _mock_concern(cid='c1', sev=0.7)
        c2 = _mock_concern(cid='c2', sev=0.7)
        c2.triggers_proactive = False
        ledger.list_active.return_value = [c1, c2]
        col = CareSignalCollector(ledger, None, None)
        out = col.collect(_now(), {})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0].id, 'c1')


class TestCareWindowGuard(unittest.TestCase):
    def setUp(self):
        from jarvis_proactive_care import CareWindowGuard
        self.worker = MagicMock()
        self.worker.voice_thread.in_active_conversation = False
        self.worker.voice_thread.is_jarvis_speaking = False
        self.worker.voice_thread._bypass_speech_count = 0
        self.nerve = MagicMock()
        self.nerve.nudge_gate.is_sleep_mode.return_value = False
        self.guard = CareWindowGuard(self.worker, self.nerve)

    def test_active_conversation_blocks(self):
        self.worker.voice_thread.in_active_conversation = True
        ok, reason = self.guard.can_speak(_mock_concern(), 0.9, _now(), 0, 0)
        self.assertFalse(ok)
        self.assertEqual(reason, 'active_conversation')

    def test_bypass_speech_blocks(self):
        self.worker.voice_thread._bypass_speech_count = 2
        ok, reason = self.guard.can_speak(_mock_concern(), 0.9, _now(), 0, 0)
        self.assertFalse(ok)
        self.assertEqual(reason, 'bypass_speech')

    def test_jarvis_speaking_blocks(self):
        self.worker.voice_thread.is_jarvis_speaking = True
        ok, _ = self.guard.can_speak(_mock_concern(), 0.9, _now(), 0, 0)
        self.assertFalse(ok)

    def test_explicit_reject_cooldown(self):
        now = _now()
        ok, reason = self.guard.can_speak(_mock_concern(), 0.9, now, 0, now + 600)
        self.assertFalse(ok)
        self.assertIn('explicit_reject', reason)

    def test_global_nudge_cooldown(self):
        now = _now()
        ok, reason = self.guard.can_speak(_mock_concern(), 0.9, now, now - 60, 0)
        self.assertFalse(ok)
        self.assertIn('global_nudge_cooldown', reason)

    def test_per_concern_cooldown(self):
        now = _now()
        c = _mock_concern(last_triggered=now - 600)
        ok, reason = self.guard.can_speak(c, 0.9, now, 0, 0)
        self.assertFalse(ok)
        self.assertIn('per_concern_cooldown', reason)

    def test_sleep_mode_blocks(self):
        self.nerve.nudge_gate.is_sleep_mode.return_value = True
        ok, reason = self.guard.can_speak(_mock_concern(), 0.9, _now() - 86400, 0, 0)
        # 注意 sleep_mode 在最后一条, 前面冷却放行
        self.assertFalse(ok)

    def test_ok_path(self):
        # 🩹 [β.2.9.6 hotfix] now 用确定的工作时段中午 12:00 避开 night_quiet (2-5h) 时段冲突.
        # 原 _now() - 3*3600 在某些时段 (e.g. 当前 08:30 - 3h = 05:30) 会落入 night_quiet.
        import time
        lt = time.localtime()
        now = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
        ok, reason = self.guard.can_speak(_mock_concern(), 0.7, now, 0, 0)
        self.assertTrue(ok, f"expected ok, got reason={reason}")


class TestCareSubjectSelector(unittest.TestCase):
    def setUp(self):
        from jarvis_proactive_care import CareSubjectSelector
        self.nerve = MagicMock()
        self.nerve.short_term_memory = [
            {'when': time.time() - 600, 'user': 'I drank some water just now',
             'jarvis': 'noted'},
            {'when': time.time() - 1200, 'user': 'totally unrelated topic',
             'jarvis': 'ok'},
        ]
        self.l2 = MagicMock()
        self.l2.list_inside_jokes.return_value = []
        self.sel = CareSubjectSelector(MagicMock(), self.l2, self.nerve)

    def test_keyword_extract(self):
        c = _mock_concern(cid='sir_hydration_habit',
                          what='watch Sir water intake during long sessions')
        kws = self.sel._concern_keywords(c)
        kw_l = [k.lower() for k in kws]
        self.assertIn('hydration', kw_l)
        self.assertIn('water', kw_l)
        # short stop words filtered
        self.assertNotIn('the', kw_l)
        self.assertNotIn('sir', kw_l)

    def test_find_recent_sir_quote(self):
        c = _mock_concern(cid='sir_hydration_habit',
                          what='watch water intake during sessions')
        q = self.sel._find_recent_sir_quote(c)
        self.assertIn('water', q.lower())

    def test_quote_not_found_returns_empty(self):
        c = _mock_concern(cid='sir_iron_man_quotes',
                          what='watch comicbook references')
        q = self.sel._find_recent_sir_quote(c)
        self.assertEqual(q, '')

    def test_inside_joke_match(self):
        from jarvis_proactive_care import CareSubjectSelector
        joke = MagicMock()
        joke.phrase = '远征'
        joke.birth_context = 'late night water bottle joke'
        self.l2.list_inside_jokes.return_value = [joke]
        sel = CareSubjectSelector(MagicMock(), self.l2, self.nerve)
        c = _mock_concern(cid='sir_hydration_habit',
                          what='water intake during long stretches')
        out = sel._find_inside_joke(c)
        self.assertEqual(out, '远征')

    def test_build_evidence_no_crash_on_missing_l2(self):
        from jarvis_proactive_care import CareSubjectSelector
        sel = CareSubjectSelector(MagicMock(), None, None)
        c = _mock_concern()
        evi = sel.build_evidence(c, 0.7, {'urgency': 0.7})
        self.assertEqual(evi.concern_id, c.id)
        self.assertEqual(evi.urgency_score, 0.7)


class TestCareSpeechSynth(unittest.TestCase):
    def setUp(self):
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence
        self.synth = CareSpeechSynth()
        self.evi = CareEvidence(
            concern_id='sir_hydration_habit',
            urgency_score=0.7,
            what_i_watch='water intake',
            why_i_care='kidney',
            severity=0.6,
            breakdown={'urgency': 0.7},
            sir_recent_quote='I forgot to drink',
            last_signal_what='2h no water break',
            inside_joke_ref='远征',
        )

    def test_directive_contains_evidence(self):
        d = self.synth.build_directive(self.evi)
        self.assertIn('sir_hydration_habit', d)
        self.assertIn('I forgot to drink', d)
        self.assertIn('远征', d)
        self.assertIn('ANTI-HALLUCINATION', d)
        self.assertIn('ZH', d)

    def test_dry_run_does_not_push(self):
        worker = MagicMock()
        sent = self.synth.push(worker, self.evi, dry_run=True)
        self.assertFalse(sent)
        worker.push_command.assert_not_called()

    def test_live_run_pushes_nudge(self):
        worker = MagicMock()
        sent = self.synth.push(worker, self.evi, dry_run=False)
        self.assertTrue(sent)
        worker.push_command.assert_called_once()
        payload = worker.push_command.call_args[0][0]
        self.assertTrue(payload.startswith('__NUDGE__:'))
        ctx = json.loads(payload[len('__NUDGE__:'):])
        self.assertEqual(ctx['type'], 'proactive_care')
        self.assertEqual(ctx['concern_id'], 'sir_hydration_habit')
        self.assertIn('nudge_directive', ctx)


class TestProactiveCareEngineFlow(unittest.TestCase):
    def setUp(self):
        from jarvis_proactive_care import (
            ProactiveCareEngine, reset_default_engine_for_test,
        )
        reset_default_engine_for_test()
        self.worker = MagicMock()
        self.worker.voice_thread.in_active_conversation = False
        self.worker.voice_thread.is_jarvis_speaking = False
        self.worker.voice_thread._bypass_speech_count = 0
        self.nerve = MagicMock()
        self.nerve.nudge_gate.is_sleep_mode.return_value = False
        self.nerve.short_term_memory = []
        self.engine = ProactiveCareEngine(self.worker, self.nerve,
                                            tick_interval_s=0.1)
        # 不调 start(), 直接 _tick

    def test_warmup_silences_first_5min(self):
        self.engine.start_ts = time.time()  # 刚启动
        ledger = MagicMock()
        c = _mock_concern(sev=0.95, last_triggered=time.time() - 20 * 3600)
        ledger.list_active.return_value = [c]
        self.engine.ledger = ledger
        self.engine.l2_store = None
        self.engine.anchor = None
        from jarvis_proactive_care import (
            CareSignalCollector, CareWindowGuard, CareSubjectSelector,
        )
        self.engine.collector = CareSignalCollector(ledger, None, None)
        self.engine.guard = CareWindowGuard(self.worker, self.nerve)
        self.engine.selector = CareSubjectSelector(ledger, None, None)
        self.engine._tick()
        self.worker.push_command.assert_not_called()

    def test_below_threshold_no_push(self):
        self.engine.start_ts = time.time() - 1000  # 过 warm-up
        self.engine.threshold = 0.9
        ledger = MagicMock()
        c = _mock_concern(sev=0.2)  # 算出来很低
        ledger.list_active.return_value = [c]
        self.engine.ledger = ledger
        from jarvis_proactive_care import (
            CareSignalCollector, CareWindowGuard, CareSubjectSelector,
        )
        self.engine.collector = CareSignalCollector(ledger, None, None)
        self.engine.guard = CareWindowGuard(self.worker, self.nerve)
        self.engine.selector = CareSubjectSelector(ledger, None, None)
        self.engine._tick()
        self.worker.push_command.assert_not_called()

    def test_above_threshold_pushes_when_live(self):
        self.engine.start_ts = time.time() - 1000
        self.engine.threshold = 0.3
        self.engine.dry_run = False
        ledger = MagicMock()
        c = _mock_concern(sev=0.9, last_triggered=time.time() - 20 * 3600)
        ledger.list_active.return_value = [c]
        self.engine.ledger = ledger
        from jarvis_proactive_care import (
            CareSignalCollector, CareWindowGuard, CareSubjectSelector,
        )
        self.engine.collector = CareSignalCollector(ledger, None, None)
        self.engine.guard = CareWindowGuard(self.worker, self.nerve)
        self.engine.selector = CareSubjectSelector(ledger, None, None)
        self.engine._tick()
        self.worker.push_command.assert_called_once()
        payload = self.worker.push_command.call_args[0][0]
        self.assertTrue(payload.startswith('__NUDGE__:'))

    def test_explicit_reject_silences(self):
        self.engine.start_ts = time.time() - 1000
        self.engine.threshold = 0.3
        self.engine.dry_run = False
        self.engine.notify_sir_explicit_reject()
        ledger = MagicMock()
        c = _mock_concern(sev=0.9, last_triggered=time.time() - 20 * 3600)
        ledger.list_active.return_value = [c]
        self.engine.ledger = ledger
        from jarvis_proactive_care import (
            CareSignalCollector, CareWindowGuard, CareSubjectSelector,
        )
        self.engine.collector = CareSignalCollector(ledger, None, None)
        self.engine.guard = CareWindowGuard(self.worker, self.nerve)
        self.engine.selector = CareSubjectSelector(ledger, None, None)
        self.engine._tick()
        self.worker.push_command.assert_not_called()

    def test_fatigue_dampens_urgency(self):
        from jarvis_proactive_care import CareSignalCollector
        col = CareSignalCollector(None, None, None)
        c = _mock_concern(sev=0.8)
        u_zero, _ = col.compute_urgency(c, _now(), fatigue_count=0)
        u_after_reject, _ = col.compute_urgency(c, _now(), fatigue_count=2)
        self.assertLess(u_after_reject, u_zero)


class TestSingletonAndNotifications(unittest.TestCase):
    def setUp(self):
        from jarvis_proactive_care import reset_default_engine_for_test
        reset_default_engine_for_test()

    def test_singleton(self):
        from jarvis_proactive_care import get_default_engine
        w = MagicMock()
        e1 = get_default_engine(w, None)
        e2 = get_default_engine()
        self.assertIs(e1, e2)

    def test_notify_any_nudge_sent_updates_ts(self):
        from jarvis_proactive_care import get_default_engine
        w = MagicMock()
        e = get_default_engine(w, None)
        e.last_any_nudge_ts = 0
        e.notify_any_nudge_sent()
        self.assertGreater(e.last_any_nudge_ts, 0)

    def test_concern_reject_increments_fatigue(self):
        from jarvis_proactive_care import get_default_engine
        w = MagicMock()
        e = get_default_engine(w, None)
        e.notify_concern_rejected('sir_hydration_habit')
        e.notify_concern_rejected('sir_hydration_habit')
        self.assertEqual(e.fatigue_map['sir_hydration_habit'], 2)

    def test_concern_aligned_decays_fatigue(self):
        from jarvis_proactive_care import get_default_engine
        w = MagicMock()
        e = get_default_engine(w, None)
        e.fatigue_map['x'] = 3
        e.notify_concern_aligned('x')
        self.assertEqual(e.fatigue_map['x'], 2)


class TestBeta2DeepWorkAndL2(unittest.TestCase):
    """β-2 强化: deep_work 检测 + L2 protocols + unfinished_business 注入"""

    def setUp(self):
        from jarvis_proactive_care import CareWindowGuard, CareSubjectSelector
        self.worker = MagicMock()
        self.worker.voice_thread.in_active_conversation = False
        self.worker.voice_thread.is_jarvis_speaking = False
        self.worker.voice_thread._bypass_speech_count = 0
        self.nerve = MagicMock()
        self.nerve.nudge_gate.is_sleep_mode.return_value = False
        self.nerve.short_term_memory = []
        self.guard = CareWindowGuard(self.worker, self.nerve)

    def test_deep_work_blocks_low_urgency(self):
        from unittest.mock import patch
        fake_snap = {
            'switch_frequency_5min': 1,
            'window_stay_seconds': 900,
            'key_press_count_5min': 150,
            'work_category': 'Coding',
            'session_duration_minutes': 60,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            now = time.time() - 86400
            ok, reason = self.guard.can_speak(_mock_concern(), 0.6, now, 0, 0)
            self.assertFalse(ok)
            self.assertIn('deep_work_focus', reason)

    def test_deep_work_allows_high_urgency(self):
        from unittest.mock import patch
        fake_snap = {
            'switch_frequency_5min': 1,
            'window_stay_seconds': 900,
            'work_category': 'Coding',
            'session_duration_minutes': 60,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            now = time.time() - 86400
            ok, _ = self.guard.can_speak(_mock_concern(), 0.8, now, 0, 0)
            self.assertTrue(ok)

    def test_not_deep_work_allows_normal(self):
        from unittest.mock import patch
        fake_snap = {
            'switch_frequency_5min': 8,
            'window_stay_seconds': 30,
            'key_press_count_5min': 50,
            'work_category': 'General',
            'session_duration_minutes': 5,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            now = time.time() - 86400
            ok, _ = self.guard.can_speak(_mock_concern(), 0.6, now, 0, 0)
            self.assertTrue(ok)

    def test_protocol_hints_relevant(self):
        from jarvis_proactive_care import CareSubjectSelector
        proto = MagicMock()
        proto.rule = "I should not pester Sir about hydration more than once per hour"
        proto.violations = []
        l2 = MagicMock()
        l2.list_protocols.return_value = [proto]
        l2.list_inside_jokes.return_value = []
        l2.list_unfinished.return_value = []
        sel = CareSubjectSelector(MagicMock(), l2, None)
        c = _mock_concern(cid='sir_hydration_habit',
                          what='watch water intake during long sessions')
        hints = sel._find_relevant_protocols(c)
        self.assertEqual(len(hints), 1)
        self.assertIn('hydration', hints[0].lower())

    def test_protocol_hints_violated_always_included(self):
        from jarvis_proactive_care import CareSubjectSelector
        proto = MagicMock()
        proto.rule = "I should let Sir finish his thought"
        proto.violations = [{'when': time.time(), 'what': 'cut in'}]
        l2 = MagicMock()
        l2.list_protocols.return_value = [proto]
        sel = CareSubjectSelector(MagicMock(), l2, None)
        c = _mock_concern(cid='sir_hydration_habit')
        hints = sel._find_relevant_protocols(c)
        self.assertEqual(len(hints), 1)

    def test_unfinished_business_match(self):
        from jarvis_proactive_care import CareSubjectSelector
        ub = MagicMock()
        ub.topic = 'finish water bottle refill setup'
        l2 = MagicMock()
        l2.list_unfinished.return_value = [ub]
        l2.list_inside_jokes.return_value = []
        l2.list_protocols.return_value = []
        sel = CareSubjectSelector(MagicMock(), l2, None)
        c = _mock_concern(cid='sir_hydration_habit',
                          what='watch water intake')
        out = sel._find_related_unfinished(c)
        self.assertIn('water', out)

    def test_current_activity_snapshot(self):
        from unittest.mock import patch
        from jarvis_proactive_care import CareSubjectSelector
        sel = CareSubjectSelector(MagicMock(), None, None)
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.current_work_category', 'Coding'), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe.work_duration_minutes', 45.0), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe.current_window_title', 'cursor.exe — main.py'):
            s = sel._snapshot_current_activity()
        self.assertIn('Coding', s)
        self.assertIn('45', s)

    def test_evidence_includes_protocols_and_unfinished(self):
        from jarvis_proactive_care import CareSubjectSelector
        proto = MagicMock()
        proto.rule = "I should not pester Sir about hydration more than once per hour"
        proto.violations = []
        ub = MagicMock()
        ub.topic = 'water bottle refill'
        l2 = MagicMock()
        l2.list_protocols.return_value = [proto]
        l2.list_unfinished.return_value = [ub]
        l2.list_inside_jokes.return_value = []
        sel = CareSubjectSelector(MagicMock(), l2, None)
        c = _mock_concern(cid='sir_hydration_habit',
                          what='watch water intake')
        evi = sel.build_evidence(c, 0.7, {})
        self.assertTrue(len(evi.protocol_hints) >= 1)
        self.assertIn('water', evi.related_unfinished.lower())

    def test_directive_includes_protocols_when_present(self):
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence
        synth = CareSpeechSynth()
        evi = CareEvidence(
            concern_id='c1', urgency_score=0.7,
            what_i_watch='x', why_i_care='y', severity=0.5,
            breakdown={},
            protocol_hints=['I should not pester Sir more than once per hour'],
        )
        d = synth.build_directive(evi)
        self.assertIn('OUR PROTOCOLS', d)
        self.assertIn('pester Sir', d)

    def test_directive_skips_protocols_section_when_empty(self):
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence
        synth = CareSpeechSynth()
        evi = CareEvidence(
            concern_id='c1', urgency_score=0.7,
            what_i_watch='x', why_i_care='y', severity=0.5,
            breakdown={},
            protocol_hints=[],
        )
        d = synth.build_directive(evi)
        self.assertNotIn('OUR PROTOCOLS', d)


class TestCareConcernSensor(unittest.TestCase):
    """β-2.5: CareConcernSensor — sensor 自动喂 concern signal"""

    def setUp(self):
        from jarvis_proactive_care import CareConcernSensor
        self.ledger = MagicMock()
        self.ledger.record_signal.return_value = True
        self.sensor = CareConcernSensor(self.ledger, None)

    def test_long_session_feeds_hydration_and_pomodoro(self):
        from unittest.mock import patch
        fake_snap = {
            'session_duration_minutes': 75,
            'work_category': 'Coding',
            'idle_seconds': 30,
            'backspace_ratio': 0.05,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            n = self.sensor.tick()
        self.assertGreaterEqual(n, 2)
        cids_called = [c.args[0] for c in self.ledger.record_signal.call_args_list]
        self.assertIn('sir_hydration_habit', cids_called)
        self.assertIn('sir_pomodoro_compliance', cids_called)

    def test_very_long_session_extra_hydration_boost(self):
        from unittest.mock import patch
        fake_snap = {
            'session_duration_minutes': 100,
            'work_category': 'Coding',
            'idle_seconds': 30,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            n = self.sensor.tick()
        # ≥3: hydration long_session + pomodoro long_session + hydration very_long_session
        self.assertGreaterEqual(n, 3)

    def test_late_night_feeds_sleep_streak(self):
        from unittest.mock import patch
        fake_snap = {
            'session_duration_minutes': 20,
            'work_category': 'Coding',
            'idle_seconds': 10,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap), \
             patch('time.localtime') as mock_lt:
            mock_lt.return_value = time.struct_time((2026, 5, 17, 3, 0, 0, 0, 0, 0))
            self.sensor.tick()
        cids = [c.args[0] for c in self.ledger.record_signal.call_args_list]
        self.assertIn('sir_sleep_streak', cids)

    def test_cooldown_prevents_double_signal(self):
        from unittest.mock import patch
        fake_snap = {
            'session_duration_minutes': 75,
            'work_category': 'Coding',
            'idle_seconds': 30,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            n1 = self.sensor.tick()
            n2 = self.sensor.tick()  # 立刻又 tick 一次
        self.assertGreaterEqual(n1, 2)
        self.assertEqual(n2, 0)  # 全在 cooldown

    def test_idle_no_session_no_signal(self):
        from unittest.mock import patch
        fake_snap = {
            'session_duration_minutes': 5,
            'work_category': 'Idle',
            'idle_seconds': 999,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            n = self.sensor.tick()
        self.assertEqual(n, 0)


class TestBeta31ChannelEscalation(unittest.TestCase):
    """β-3.1: channel 动态升级 (silent_text → voice)"""

    def setUp(self):
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence
        self.synth = CareSpeechSynth()
        self.evi_mid = CareEvidence(
            concern_id='sir_hydration_habit', urgency_score=0.65,
            what_i_watch='x', why_i_care='y', severity=0.5, breakdown={})
        self.evi_high = CareEvidence(
            concern_id='sir_sleep_streak', urgency_score=0.9,
            what_i_watch='x', why_i_care='y', severity=0.8, breakdown={})

    def test_high_urgency_always_voice(self):
        ch = self.synth.choose_channel(self.evi_high, silent_done_recently=False)
        self.assertEqual(ch, 'voice')
        ch2 = self.synth.choose_channel(self.evi_high, silent_done_recently=True)
        self.assertEqual(ch2, 'voice')

    def test_mid_urgency_first_time_silent(self):
        ch = self.synth.choose_channel(self.evi_mid, silent_done_recently=False)
        self.assertEqual(ch, 'silent_text')

    def test_mid_urgency_after_silent_escalates_voice(self):
        ch = self.synth.choose_channel(self.evi_mid, silent_done_recently=True)
        self.assertEqual(ch, 'voice')

    def test_render_silent_text(self):
        out = self.synth.render_silent_text(self.evi_mid)
        self.assertIn('Sir hydration habit', out)
        self.assertIn('watching', out.lower())

    def test_push_silent_channel(self):
        worker = MagicMock()
        sent = self.synth.push(worker, self.evi_mid, dry_run=False, channel='silent_text')
        self.assertTrue(sent)
        payload = worker.push_command.call_args[0][0]
        ctx = json.loads(payload[len('__NUDGE__:'):])
        self.assertEqual(ctx['channel'], 'silent_text')
        self.assertIn('silent_text', ctx)
        self.assertIn('Sir hydration habit', ctx['silent_text'])


class TestBeta32ExtraSensorRules(unittest.TestCase):
    """β-3.2: 额外 sensor 规则 (error_visible / context_switch / first_active / unfinished)"""

    def setUp(self):
        from jarvis_proactive_care import CareConcernSensor
        self.ledger = MagicMock()
        self.ledger.record_signal.return_value = True
        self.ledger.list_active.return_value = []
        self.sensor = CareConcernSensor(self.ledger, None)

    def test_error_visible_feeds_pomodoro(self):
        from unittest.mock import patch
        fake_snap = {
            'session_duration_minutes': 30,
            'work_category': 'Coding',
            'idle_seconds': 30,
            'error_visible': True,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            self.sensor.tick()
        cids = [c.args[0] for c in self.ledger.record_signal.call_args_list]
        self.assertIn('sir_pomodoro_compliance', cids)

    def test_high_switch_feeds_hydration(self):
        from unittest.mock import patch
        fake_snap = {
            'switch_frequency_5min': 15,
            'session_duration_minutes': 20,
            'idle_seconds': 30,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            self.sensor.tick()
        cids = [c.args[0] for c in self.ledger.record_signal.call_args_list]
        self.assertIn('sir_hydration_habit', cids)

    def test_first_active_today_feeds_hydration(self):
        from unittest.mock import patch
        fake_snap = {
            'is_first_active_today': True,
            'session_duration_minutes': 5,
            'idle_seconds': 5,
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.get_sensor_snapshot',
                    return_value=fake_snap):
            self.sensor.tick()
        cids = [c.args[0] for c in self.ledger.record_signal.call_args_list]
        self.assertIn('sir_hydration_habit', cids)


class TestDryRunDefault(unittest.TestCase):
    def test_dry_run_default_when_env_unset(self):
        from jarvis_proactive_care import reset_default_engine_for_test, get_default_engine
        os.environ.pop('JARVIS_PROACTIVE_CARE_LIVE', None)
        reset_default_engine_for_test()
        w = MagicMock()
        e = get_default_engine(w, None)
        self.assertTrue(e.dry_run, "默认必须 dry-run, 不污染生产")

    def test_live_mode_when_env_set(self):
        from jarvis_proactive_care import reset_default_engine_for_test, get_default_engine
        os.environ['JARVIS_PROACTIVE_CARE_LIVE'] = '1'
        try:
            reset_default_engine_for_test()
            w = MagicMock()
            e = get_default_engine(w, None)
            self.assertFalse(e.dry_run)
        finally:
            os.environ.pop('JARVIS_PROACTIVE_CARE_LIVE', None)
            reset_default_engine_for_test()


if __name__ == '__main__':
    unittest.main(verbosity=2)
