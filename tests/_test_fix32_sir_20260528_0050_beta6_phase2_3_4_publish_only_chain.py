# -*- coding: utf-8 -*-
"""[fix32 / Sir 2026-05-28 00:50 真意 β.6 Phase 2/3/4 publish-only chain 完整接通]

Sir 真意 β.6: 5 reflector daemon (ProactiveCare / Conductor / Wellness / SmartNudge
/ SoulEvaluator) 退化 publish-only, 单一思考脑 (InnerThoughtDaemon) 统一决发声.
3 个 phase 验证 publish-only 端到端通:

Phase 2 (ProactiveCare):
  L51 vocab gate_mode_vocab.json 含 'ProactiveCare': 'publish_only'
  L52 ProactiveCareSpeechSynth.push() publish_only mode → publish 'proactive_care_advice'
      SWM event + 不真 push __NUDGE__ + 返 False
  L53 publish_only event metadata 含 nudge_directive + sir_recent_quote 等 evi 字段

Phase 3 (action_event_prefixes vocab):
  L54 memory_pool/runtime_log_marker_vocab.json action_event_prefixes 含
      'gate_advice' / 'proactive_care_advice' / 'soul_alignment_advice' 等
      publish_only 时代 advice etype
  L55 思考脑 _ACTION_EVENT_PREFIXES property fallback (vocab 损坏时) 也含新 etype

Phase 4 (SoulEvaluator):
  L56 vocab gate_mode_vocab.json 含 'SoulEvaluator': 'publish_only'
  L57 SoulAlignmentEvaluator._apply_to_ledger 一律 publish 'soul_alignment_advice' SWM
  L58 publish_only mode → skip notify ProactiveCare (不双重 mutation fatigue)
  L59 hard mode (向后兼容) → 仍 notify ProactiveCare

验证准则 6 三维耦合:
  - 数据强耦合: 5 daemon 全部 publish SWM evidence (advice/skip/active)
  - 行为弱耦合: gate_mode_vocab.json 默认 publish_only 不直 push __NUDGE__
  - 决策集中思考脑: 思考脑 nudge_history channel 通过 vocab driven prefix 看到全部 advice
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================
# Phase 2 — ProactiveCare publish-only
# ==========================================================

class TestL51VocabHasProactiveCare(unittest.TestCase):
    """gate_mode_vocab.json 含 'ProactiveCare': 'publish_only'."""

    def test_proactive_care_in_vocab(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        current = data.get('current', {})
        self.assertIn('ProactiveCare', current,
                       'β.6 Phase 2: ProactiveCare 必须在 gate_mode_vocab')
        self.assertEqual(current['ProactiveCare'], 'publish_only',
                          'β.6 Phase 2: ProactiveCare default = publish_only')


class TestL52ProactiveCarePushPublishOnly(unittest.TestCase):
    """ProactiveCareSpeechSynth.push() publish_only → publish 'proactive_care_advice'
    SWM event + 不真 push __NUDGE__ + 返 False."""

    def test_push_publish_only_publishes_advice(self):
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence

        synth = CareSpeechSynth()
        evi = CareEvidence(
            concern_id='test_concern_x',
            urgency_score=0.85,
            what_i_watch='Sir typing late',
            why_i_care='health',
            severity=0.7,
            breakdown={'base_severity': 0.7},
            sir_recent_quote='I am exhausted',
            inside_joke_ref='midnight oil',
            last_signal_what='30min coding',
        )
        captured = []

        class _FakeBus:
            def publish(self_, etype, description, source, salience=0.5,
                        metadata=None, ttl=0.0):
                captured.append({
                    'etype': etype, 'description': description,
                    'source': source, 'salience': salience,
                    'metadata': metadata or {}, 'ttl': ttl,
                })

        class _FakeWorker:
            push_called = False

            def push_command(self_, payload):
                self_.push_called = True  # 应不被调

        worker = _FakeWorker()

        # patch gate_mode='publish_only' + event_bus
        with patch('jarvis_utils.read_gate_mode', return_value='publish_only'):
            with patch('jarvis_utils.get_event_bus', return_value=_FakeBus()):
                result = synth.push(worker, evi, dry_run=False, channel='voice')

        self.assertFalse(result, 'publish_only mode 应返 False')
        self.assertFalse(worker.push_called,
                          'publish_only mode 不应真 push __NUDGE__')
        # 应 publish 'proactive_care_advice'
        advice_events = [e for e in captured if e['etype'] == 'proactive_care_advice']
        self.assertEqual(len(advice_events), 1,
                          f'expected 1 proactive_care_advice, got {len(advice_events)}')


class TestL53PublishOnlyEventMetadata(unittest.TestCase):
    """publish_only 'proactive_care_advice' event metadata 含完整 evi 字段."""

    def test_metadata_contains_evidence(self):
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence

        synth = CareSpeechSynth()
        evi = CareEvidence(
            concern_id='hydration',
            urgency_score=0.72,
            what_i_watch='no water 3h',
            why_i_care='health',
            severity=0.6,
            breakdown={'recency': 0.9, 'silence_pressure': 0.5},
            sir_recent_quote='喝了 5 杯',
            inside_joke_ref='glass count',
            last_signal_what='水杯计数',
        )
        captured = []

        class _FakeBus:
            def publish(self_, **kw):
                captured.append(kw)

        with patch('jarvis_utils.read_gate_mode', return_value='publish_only'):
            with patch('jarvis_utils.get_event_bus', return_value=_FakeBus()):
                synth.push(MagicMock(), evi, dry_run=False, channel='silent_text')

        self.assertEqual(len(captured), 1)
        md = captured[0].get('metadata') or {}
        self.assertEqual(md.get('concern_id'), 'hydration')
        self.assertEqual(md.get('channel_hint'), 'silent_text')
        self.assertEqual(md.get('urgency_score'), 0.72)
        self.assertIn('nudge_directive', md)
        self.assertIn('sir_recent_quote', md)
        self.assertEqual(md['sir_recent_quote'], '喝了 5 杯')
        self.assertIn('inside_joke_ref', md)
        self.assertIn('what_i_watch', md)
        self.assertIn('urgency_breakdown', md)
        self.assertEqual(md.get('gate_mode'), 'publish_only')


# ==========================================================
# Phase 3 — action_event_prefixes vocab
# ==========================================================

class TestL54VocabContainsPublishOnlyAdviceEtype(unittest.TestCase):
    """runtime_log_marker_vocab.json action_event_prefixes 含 publish-only advice etype."""

    def test_vocab_contains_advice_etype(self):
        path = os.path.join(ROOT, 'memory_pool', 'runtime_log_marker_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        prefixes = data.get('action_event_prefixes') or []
        required = (
            'gate_advice', 'proactive_care_advice', 'soul_alignment_advice',
            'concern_active', 'concern_timing_evidence',
        )
        for p in required:
            self.assertIn(p, prefixes,
                          f"β.6 Phase 3: action_event_prefixes 必含 '{p}' 让"
                          f"思考脑 nudge_history channel 看到 publish_only evi")


class TestL55DaemonFallbackAlsoHasAdviceEtype(unittest.TestCase):
    """_ACTION_EVENT_PREFIXES property fallback (vocab 损坏时) 也含新 advice etype."""

    def test_daemon_fallback_includes_advice(self):
        # 临 patch loader fail → 走 daemon fallback
        from jarvis_inner_thought_daemon import InnerThoughtDaemon

        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        with patch('jarvis_runtime_log_markers.load_action_event_prefixes',
                   side_effect=RuntimeError('mock vocab corrupted')):
            prefixes = d._ACTION_EVENT_PREFIXES

        self.assertIsInstance(prefixes, tuple)
        for p in ('gate_advice', 'proactive_care_advice',
                  'soul_alignment_advice'):
            self.assertIn(p, prefixes,
                          f"daemon fallback (vocab 损坏) 也必含 '{p}'")


# ==========================================================
# Phase 4 — SoulEvaluator publish-only
# ==========================================================

class TestL56VocabHasSoulEvaluator(unittest.TestCase):
    """gate_mode_vocab.json 含 'SoulEvaluator': 'publish_only'."""

    def test_soul_eval_in_vocab(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        current = data.get('current', {})
        self.assertIn('SoulEvaluator', current,
                       'β.6 Phase 4: SoulEvaluator 必须在 gate_mode_vocab')
        self.assertEqual(current['SoulEvaluator'], 'publish_only',
                          'β.6 Phase 4: SoulEvaluator default = publish_only')


class TestL57SoulEvalPublishesAdvice(unittest.TestCase):
    """SoulAlignmentEvaluator._apply_to_ledger 一律 publish 'soul_alignment_advice'
    SWM event (不分 mode)."""

    def test_apply_to_ledger_publishes_advice(self):
        from jarvis_soul_evaluator import (
            SoulAlignmentEvaluator, SoulEvalResult,
        )

        # mock ledger
        ledger = MagicMock()
        ledger.record_alignment.return_value = True
        ledger.persist.return_value = True

        ev = SoulAlignmentEvaluator(
            key_router=MagicMock(),
            concerns_ledger=ledger,
            relational_state=None,
            pool_size=1,
        )

        captured = []

        class _FakeBus:
            def publish(self_, **kw):
                captured.append(kw)

        result = SoulEvalResult(
            alignment='yes',
            aligned_concern_ids=['sir_sleep_streak'],
            missed_concern_ids=[],
            what_aligned='reply mentioned bedtime',
            what_missed='',
            elapsed_ms=120,
            turn_id='turn_test_57',
            picked_model='google/gemini-3-flash-preview',
            complexity_score=2,
        )
        # Patch read_gate_mode publish_only (skip notify ProactiveCare)
        with patch('jarvis_utils.read_gate_mode', return_value='publish_only'):
            with patch('jarvis_utils.get_event_bus', return_value=_FakeBus()):
                ev._apply_to_ledger(result)
        try:
            ev.shutdown(wait=False)
        except Exception:
            pass

        advice_events = [e for e in captured
                          if e.get('etype') == 'soul_alignment_advice']
        self.assertEqual(len(advice_events), 1,
                          f'expected 1 soul_alignment_advice, got {len(advice_events)}')
        md = advice_events[0].get('metadata') or {}
        self.assertEqual(md.get('alignment'), 'yes')
        self.assertEqual(md.get('aligned_concern_ids'), ['sir_sleep_streak'])
        self.assertEqual(md.get('turn_id'), 'turn_test_57')


class TestL58PublishOnlySkipsNotifyProactiveCare(unittest.TestCase):
    """publish_only mode → skip 调 ProactiveCare.notify_concern_aligned/rejected."""

    def test_publish_only_skips_pce_notify(self):
        from jarvis_soul_evaluator import (
            SoulAlignmentEvaluator, SoulEvalResult,
        )

        ledger = MagicMock()
        ledger.record_alignment.return_value = True
        ledger.persist.return_value = True

        ev = SoulAlignmentEvaluator(
            key_router=MagicMock(),
            concerns_ledger=ledger,
            relational_state=None,
            pool_size=1,
        )
        fake_pce = MagicMock()

        result = SoulEvalResult(
            alignment='no',
            aligned_concern_ids=[],
            missed_concern_ids=['sir_sleep_streak'],
            turn_id='turn_test_58',
        )
        with patch('jarvis_utils.read_gate_mode', return_value='publish_only'):
            with patch('jarvis_proactive_care.get_default_engine',
                       return_value=fake_pce):
                with patch('jarvis_utils.get_event_bus', return_value=MagicMock()):
                    ev._apply_to_ledger(result)
        try:
            ev.shutdown(wait=False)
        except Exception:
            pass

        # publish_only → 不应 notify
        fake_pce.notify_concern_aligned.assert_not_called()
        fake_pce.notify_concern_rejected.assert_not_called()


class TestL59HardModeStillNotifiesProactiveCare(unittest.TestCase):
    """hard mode (向后兼容) → 仍 notify ProactiveCare 走老学习反馈循环."""

    def test_hard_mode_notifies_pce(self):
        from jarvis_soul_evaluator import (
            SoulAlignmentEvaluator, SoulEvalResult,
        )

        ledger = MagicMock()
        ledger.record_alignment.return_value = True
        ledger.persist.return_value = True

        ev = SoulAlignmentEvaluator(
            key_router=MagicMock(),
            concerns_ledger=ledger,
            relational_state=None,
            pool_size=1,
        )
        fake_pce = MagicMock()

        result = SoulEvalResult(
            alignment='yes',
            aligned_concern_ids=['sir_sleep_streak'],
            missed_concern_ids=['sir_cursor_payment'],
            turn_id='turn_test_59',
        )
        with patch('jarvis_utils.read_gate_mode', return_value='hard'):
            with patch('jarvis_proactive_care.get_default_engine',
                       return_value=fake_pce):
                with patch('jarvis_utils.get_event_bus', return_value=MagicMock()):
                    ev._apply_to_ledger(result)
        try:
            ev.shutdown(wait=False)
        except Exception:
            pass

        # hard mode → 应 notify aligned + rejected
        fake_pce.notify_concern_aligned.assert_called_with('sir_sleep_streak')
        fake_pce.notify_concern_rejected.assert_called_with('sir_cursor_payment')


if __name__ == '__main__':
    unittest.main(verbosity=2)
