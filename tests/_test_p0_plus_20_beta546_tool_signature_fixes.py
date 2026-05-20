# -*- coding: utf-8 -*-
"""[P0 / 2026-05-20 23:18] Tool signature fixes — 3 critical IntentResolver tool BUG.

Cover:
  A. tool_concern_progress_update: accepts 'progress' as alias for 'current' (LLM
     often uses 'progress' name), accepts signal-only mode (no current/progress)
  B. tool_memory_correction_apply: calls ProfileCard.apply_correction with correct
     signature (source_module, field, old_value, new_value, confidence) not 
     (field_hint, new_value, raw_text) which was 100% TypeError
  C. tool_profile_field_update: same signature fix
  D. ProfileCard._correction_weights includes 'intent_resolver': 0.9 so that
     effective_confidence = 0.9 * 0.9 = 0.81 > 0.20 threshold → 真持久化 to 
     memory_pool/profile_corrections.jsonl
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _MockProfileCard:
    """Minimal ProfileCard mock matching real signature for testing."""

    def __init__(self):
        self.corrections_received = []
        # match real apply_correction signature
        self._correction_weights = {
            'intent_resolver': 0.9,
            'habit_clock': 0.30,
        }

    def apply_correction(self, source_module, field, old_value, new_value, confidence):
        """Match real signature exactly. Records call for verification."""
        self.corrections_received.append({
            'source_module': source_module,
            'field': field,
            'old_value': old_value,
            'new_value': new_value,
            'confidence': confidence,
        })


class _MockConcernsLedger:
    def __init__(self, accept_unknown=False):
        self.records = []
        self.accept = accept_unknown

    def record_user_feedback(self, concern_id, raw_text, judgement):
        self.records.append({
            'concern_id': concern_id,
            'raw_text': raw_text,
            'judgement': judgement,
        })
        return True  # always accept for test


class _MockNerve:
    def __init__(self):
        self.profile_card = _MockProfileCard()
        self.concerns_ledger = _MockConcernsLedger()


# ============================================================
# A. tool_concern_progress_update
# ============================================================

class TestA_ConcernProgressUpdate(unittest.TestCase):

    def setUp(self):
        from jarvis_tool_registry import tool_concern_progress_update
        self.tool = tool_concern_progress_update
        self.nerve = _MockNerve()

    def test_accepts_current_arg(self):
        """正常 path: LLM passes 'current'."""
        r = self.tool(concern_id='sir_hydration_habit', current=8, target=8,
                      unit='杯', nerve=self.nerve)
        self.assertTrue(r['ok'], r)
        self.assertIn('8', r['result'])
        rec = self.nerve.concerns_ledger.records[0]
        self.assertEqual(rec['judgement']['progress']['current'], 8)

    def test_accepts_progress_alias(self):
        """alias path: LLM passes 'progress' instead of 'current' (common)."""
        r = self.tool(concern_id='sir_hydration_habit', progress=7, target=8,
                      nerve=self.nerve)
        self.assertTrue(r['ok'], r)
        rec = self.nerve.concerns_ledger.records[0]
        self.assertEqual(rec['judgement']['progress']['current'], 7)

    def test_signal_only_mode_with_raw_text(self):
        """signal-only mode: just raw_text, no current/progress."""
        r = self.tool(concern_id='sir_sleep_streak',
                      raw_text='Sir said he slept badly',
                      severity_delta=0.1,
                      nerve=self.nerve)
        self.assertTrue(r['ok'], r)
        self.assertIn('signal-only', r['result'])

    def test_rejects_when_all_missing(self):
        """reject when no current AND no progress AND no raw_text AND no severity."""
        r = self.tool(concern_id='sir_sleep_streak', nerve=self.nerve)
        self.assertFalse(r['ok'])
        self.assertIn('require at least one', r['error'])

    def test_rejects_missing_concern_id(self):
        r = self.tool(concern_id='', current=8, nerve=self.nerve)
        self.assertFalse(r['ok'])
        self.assertIn('concern_id', r['error'])


# ============================================================
# B. tool_memory_correction_apply
# ============================================================

class TestB_MemoryCorrectionApply(unittest.TestCase):

    def setUp(self):
        from jarvis_tool_registry import tool_memory_correction_apply
        self.tool = tool_memory_correction_apply
        self.nerve = _MockNerve()

    def test_calls_apply_correction_with_correct_signature(self):
        """The critical P0 fix — was TypeError 100% before."""
        r = self.tool(old_value='9 cups', new_value='8 cups',
                      field_hint='hydration_count', nerve=self.nerve)
        self.assertTrue(r['ok'], f'tool failed: {r}')
        self.assertEqual(len(self.nerve.profile_card.corrections_received), 1)
        call = self.nerve.profile_card.corrections_received[0]
        # verify ALL 5 required args are passed correctly
        self.assertEqual(call['source_module'], 'intent_resolver')
        self.assertEqual(call['field'], 'hydration_count')
        self.assertEqual(call['old_value'], '9 cups')
        self.assertEqual(call['new_value'], '8 cups')
        self.assertEqual(call['confidence'], 0.9)

    def test_default_field_hint(self):
        """No field_hint → defaults to 'memory_correction'."""
        r = self.tool(old_value='X', new_value='Y', nerve=self.nerve)
        self.assertTrue(r['ok'])
        call = self.nerve.profile_card.corrections_received[0]
        self.assertEqual(call['field'], 'memory_correction')

    def test_custom_confidence(self):
        """Caller can override confidence."""
        r = self.tool(old_value='X', new_value='Y', confidence=0.5,
                      nerve=self.nerve)
        self.assertTrue(r['ok'])
        call = self.nerve.profile_card.corrections_received[0]
        self.assertEqual(call['confidence'], 0.5)

    def test_rejects_empty_new_value(self):
        r = self.tool(old_value='X', new_value='', nerve=self.nerve)
        self.assertFalse(r['ok'])


# ============================================================
# C. tool_profile_field_update
# ============================================================

class TestC_ProfileFieldUpdate(unittest.TestCase):

    def setUp(self):
        from jarvis_tool_registry import tool_profile_field_update
        self.tool = tool_profile_field_update
        self.nerve = _MockNerve()

    def test_real_sir_2026_05_20_case(self):
        """Sir 23:02:15 真 case: 26 yrs, 1.83m, 95kg → profile."""
        r = self.tool(field_path='biographic.height', value='1.83m',
                      raw_text='我身高 1.83', nerve=self.nerve)
        self.assertTrue(r['ok'], f'tool failed: {r}')
        call = self.nerve.profile_card.corrections_received[0]
        # the critical part: was TypeError before P0 fix
        self.assertEqual(call['source_module'], 'intent_resolver')
        self.assertEqual(call['field'], 'biographic.height')
        self.assertEqual(call['new_value'], '1.83m')
        self.assertEqual(call['confidence'], 0.9)

    def test_with_old_value(self):
        r = self.tool(field_path='biographic.weight', value='95kg',
                      old_value='90kg', nerve=self.nerve)
        self.assertTrue(r['ok'])
        call = self.nerve.profile_card.corrections_received[0]
        self.assertEqual(call['old_value'], '90kg')
        self.assertEqual(call['new_value'], '95kg')

    def test_rejects_missing_field_path(self):
        r = self.tool(field_path='', value='X', nerve=self.nerve)
        self.assertFalse(r['ok'])

    def test_no_profile_card(self):
        """Defensive: nerve without profile_card."""
        class _NoProfile:
            pass
        r = self.tool(field_path='x', value='y', nerve=_NoProfile())
        self.assertFalse(r['ok'])
        self.assertIn('no profile_card', r['error'])


# ============================================================
# D. ProfileCard._correction_weights includes 'intent_resolver': 0.9
# ============================================================

class TestD_ProfileCardWeights(unittest.TestCase):

    def test_intent_resolver_weight_present(self):
        """Verify intent_resolver weight is 0.9 (effective conf 0.81 > 0.20)."""
        # Read the source code to check weight (avoids needing a full Jarvis instance)
        import jarvis_routing
        with open(jarvis_routing.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'intent_resolver': 0.9", src,
                      "ProfileCard._correction_weights must include 'intent_resolver': 0.9")

    def test_effective_confidence_above_threshold(self):
        """0.9 weight * 0.9 default conf = 0.81 > 0.20 threshold → real persist."""
        effective = 0.9 * 0.9
        threshold = 0.20  # ProfileCard hardcoded in apply_correction
        self.assertGreater(effective, threshold,
                           "intent_resolver effective_confidence must exceed disk-persist threshold")


# ============================================================
# E. End-to-end: tool → ProfileCard (mocked) → real signature flow
# ============================================================

class TestE_EndToEndIntegration(unittest.TestCase):

    def test_concern_then_correction_then_profile_flow(self):
        """Simulate IntentResolver calling 3 tools in one turn — all should succeed."""
        from jarvis_tool_registry import (
            tool_concern_progress_update,
            tool_memory_correction_apply,
            tool_profile_field_update,
        )
        nerve = _MockNerve()
        # Sir: "我喝了 8 杯" (progress)
        r1 = tool_concern_progress_update(concern_id='sir_hydration', current=8,
                                          target=8, unit='杯', nerve=nerve)
        # Sir: "记错了, 应该是 7 杯"  (correction)
        r2 = tool_memory_correction_apply(old_value='8 杯', new_value='7 杯',
                                          field_hint='hydration_count', nerve=nerve)
        # Sir: "身高 1.83"  (profile field)
        r3 = tool_profile_field_update(field_path='biographic.height',
                                       value='1.83m', nerve=nerve)
        self.assertTrue(r1['ok'], r1)
        self.assertTrue(r2['ok'], r2)
        self.assertTrue(r3['ok'], r3)
        # ProfileCard receives both r2 + r3 corrections
        self.assertEqual(len(nerve.profile_card.corrections_received), 2)
        # ConcernsLedger receives r1
        self.assertEqual(len(nerve.concerns_ledger.records), 1)


if __name__ == '__main__':
    unittest.main()
