# -*- coding: utf-8 -*-
"""[P3 / 2026-05-20 23:42] P3 boundary BUG fixes verify

Cover (5 BUG, from JARVIS_DEEP_AUDIT_2026_05_20.md §3):
  #1 stream_chat 主对话 record nudge memory (RecentNudgeMemory 真完整)
  #2 worker.py memory_correction 迁 MemoryGateway (统一 mutation)
  #5 tool_concern_progress_update alias 扩 (value/count/amount/done)
  #6 ClaimTracer SWM lookback 60s→180s
  #7 jsonl rotation utility

NOT covered (Sir 拍板才做):
  #3 ProfileReflector 真 LLM-propose + apply sir_profile.json
  #4 真 retire 4 sentinel publish-only
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# BUG #5: tool_concern_progress_update alias 扩
# ============================================================

class TestBug5_ConcernProgressAliases(unittest.TestCase):

    def setUp(self):
        from jarvis_tool_registry import tool_concern_progress_update
        self.tool = tool_concern_progress_update

        class _MockLedger:
            def __init__(self):
                self.records = []

            def record_user_feedback(self, cid, raw, j):
                self.records.append({'cid': cid, 'raw': raw, 'judgement': j})
                return True

        class _MockNerve:
            def __init__(self):
                self.concerns_ledger = _MockLedger()

        self.nerve = _MockNerve()

    def test_alias_progress(self):
        r = self.tool(concern_id='c1', progress=5, nerve=self.nerve)
        self.assertTrue(r['ok'], r)
        self.assertEqual(self.nerve.concerns_ledger.records[0]['judgement']['progress']['current'], 5)

    def test_alias_value(self):
        r = self.tool(concern_id='c1', value=7, nerve=self.nerve)
        self.assertTrue(r['ok'])

    def test_alias_count(self):
        r = self.tool(concern_id='c1', count=8, nerve=self.nerve)
        self.assertTrue(r['ok'])

    def test_alias_amount(self):
        r = self.tool(concern_id='c1', amount=9, nerve=self.nerve)
        self.assertTrue(r['ok'])

    def test_alias_done(self):
        r = self.tool(concern_id='c1', done=10, nerve=self.nerve)
        self.assertTrue(r['ok'])

    def test_current_takes_precedence(self):
        r = self.tool(concern_id='c1', current=1, progress=2, value=3,
                       nerve=self.nerve)
        self.assertTrue(r['ok'])
        # current=1 wins, aliases ignored
        self.assertEqual(self.nerve.concerns_ledger.records[0]['judgement']['progress']['current'], 1)


# ============================================================
# BUG #6: ClaimTracer SWM lookback 60s→180s default
# ============================================================

class TestBug6_ClaimTracerLookback(unittest.TestCase):

    def test_default_lookback_180s(self):
        import inspect
        from jarvis_claim_tracer import trace_reply
        sig = inspect.signature(trace_reply)
        param = sig.parameters.get('swm_lookback_s')
        self.assertIsNotNone(param)
        self.assertEqual(param.default, 180.0,
                         f'P3 BUG#6: default lookback should be 180s, got {param.default}')


# ============================================================
# BUG #7: jsonl rotation utility
# ============================================================

class TestBug7_JsonlRotation(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='jsonl_rot_test_')
        self.path = os.path.join(self.tmpdir, 'test.jsonl')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_rotation_when_small(self):
        from jarvis_jsonl_rotator import maybe_rotate
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{"x": 1}\n' * 10)  # tiny
        rotated = maybe_rotate(self.path, size_mb_cap=10.0, force=True)
        self.assertFalse(rotated)
        self.assertTrue(os.path.exists(self.path))

    def test_rotation_when_oversized(self):
        from jarvis_jsonl_rotator import maybe_rotate, list_bak_files
        # write > 1MB content
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('x' * (2 * 1024 * 1024))  # 2MB
        rotated = maybe_rotate(self.path, size_mb_cap=1.0, force=True)
        self.assertTrue(rotated)
        # original now empty
        self.assertEqual(os.path.getsize(self.path), 0)
        # bak exists
        baks = list_bak_files(self.path)
        self.assertEqual(len(baks), 1)
        self.assertGreater(os.path.getsize(baks[0]), 1024 * 1024)

    def test_check_every_n_writes(self):
        """non-force calls only stat every N writes (cheap)."""
        from jarvis_jsonl_rotator import maybe_rotate
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('x' * (5 * 1024 * 1024))  # 5MB
        # without force, first call(s) may skip
        called_rotate = False
        for _ in range(25):  # enough to trigger 20-write interval
            if maybe_rotate(self.path, size_mb_cap=1.0, force=False):
                called_rotate = True
                break
        # should have rotated by now
        self.assertTrue(called_rotate)

    def test_stats(self):
        from jarvis_jsonl_rotator import stats
        s = stats()
        # known files dict
        self.assertIsInstance(s, dict)


# ============================================================
# BUG #2: MemoryGateway routes worker.memory_correction
# ============================================================

class TestBug2_GatewayWorkerMemoryCorrection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gateway_worker_test_')
        self.receipt_path = os.path.join(self.tmpdir, 'mutation_receipts.jsonl')
        from jarvis_memory_gateway import MemoryMutationGateway
        self.gw = MemoryMutationGateway(receipt_path=self.receipt_path)

        # mock nerve with ProfileCard
        class _MockProfileCard:
            def __init__(self):
                self.calls = []
                self._correction_weights = {
                    'intent_resolver': 0.9,
                    'worker.memory_correction': 0.7,  # P3 BUG#2
                }

            def apply_correction(self, source_module, field, old_value, new_value, confidence):
                self.calls.append({
                    'source_module': source_module, 'field': field,
                    'old_value': old_value, 'new_value': new_value,
                    'confidence': confidence,
                })

        class _MockNerve:
            def __init__(self):
                self.profile_card = _MockProfileCard()

        self.nerve = _MockNerve()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_worker_memory_correction_routes_to_profilecard(self):
        receipt = self.gw.update_sir_field(
            field_path='preferences.user_correction',
            new_value='今晚11点半睡',
            old_value='今晚早点睡',
            source='worker.memory_correction',
            confidence=0.5,
            nerve=self.nerve,
        )
        self.assertTrue(receipt.ok, f'receipt failed: {receipt.error}')
        self.assertEqual(receipt.layer_targeted, 'ProfileCard')
        # ProfileCard 真受到 apply_correction call with right source
        self.assertEqual(len(self.nerve.profile_card.calls), 1)
        call = self.nerve.profile_card.calls[0]
        self.assertEqual(call['source_module'], 'worker.memory_correction')

    def test_weight_value_in_profilecard(self):
        """Verify P3 BUG#2 weight 'worker.memory_correction': 0.7 in routing."""
        import jarvis_routing
        with open(jarvis_routing.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'worker.memory_correction': 0.7", src,
                       'P3 BUG#2: ProfileCard._correction_weights must have worker.memory_correction')


# ============================================================
# BUG #1: stream_chat record_nudge wired
# ============================================================

class TestBug1_StreamChatRecordWired(unittest.TestCase):
    """Static check: chat_bypass.py 含 stream_chat 末尾 record_nudge call."""

    def test_chat_bypass_has_main_chat_record(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 验 'main_chat' channel name 在 source 里
        self.assertIn("channel='main_chat'", src,
                       'P3 BUG#1: stream_chat must record nudge with channel=main_chat')
        # 验 import recent_nudge_memory
        self.assertIn('from jarvis_recent_nudge_memory import record_nudge', src)


if __name__ == '__main__':
    unittest.main()
