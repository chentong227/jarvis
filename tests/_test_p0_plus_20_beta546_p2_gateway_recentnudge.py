# -*- coding: utf-8 -*-
"""[P2 / 2026-05-20 23:55] P2 fixes verify — MemoryMutationGateway + RecentNudgeMemory

Cover:
  A. MemoryMutationGateway routes ProfileCard fields correctly (Gap 7)
  B. MemoryMutationGateway routes Milestones (Gap 7)
  C. MemoryMutationGateway publishes SWM + writes receipt jsonl (Gap 7)
  D. RecentNudgeMemory persists + recalls + prompt block (Gap 12)
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. MemoryGateway routes ProfileCard
# ============================================================

class _MockProfileCard:
    def __init__(self):
        self.corrections_received = []
        self._correction_weights = {'intent_resolver': 0.9, 'test_src': 0.5}

    def apply_correction(self, source_module, field, old_value, new_value, confidence):
        self.corrections_received.append({
            'source_module': source_module, 'field': field,
            'old_value': old_value, 'new_value': new_value,
            'confidence': confidence,
        })


class _MockNerve:
    def __init__(self):
        self.profile_card = _MockProfileCard()
        self.concerns_ledger = None


class TestA_GatewayProfileCardRouting(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gateway_test_')
        self.receipt_path = os.path.join(self.tmpdir, 'mutation_receipts.jsonl')
        from jarvis_memory_gateway import MemoryMutationGateway
        self.gw = MemoryMutationGateway(receipt_path=self.receipt_path)
        self.nerve = _MockNerve()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_route_biographic_to_profilecard(self):
        receipt = self.gw.update_sir_field(
            field_path='biographic.height',
            new_value='1.83m',
            source='intent_resolver',
            confidence=0.9,
            nerve=self.nerve,
        )
        self.assertTrue(receipt.ok, f'receipt failed: {receipt.error}')
        self.assertEqual(receipt.layer_targeted, 'ProfileCard')
        self.assertTrue(receipt.mutation_id.startswith('mut_'))
        # ProfileCard真受到 apply_correction call
        self.assertEqual(len(self.nerve.profile_card.corrections_received), 1)
        call = self.nerve.profile_card.corrections_received[0]
        self.assertEqual(call['field'], 'biographic.height')
        self.assertEqual(call['new_value'], '1.83m')

    def test_route_preferences_to_profilecard(self):
        receipt = self.gw.update_sir_field(
            field_path='preferences.language',
            new_value='english',
            source='test_src',
            nerve=self.nerve,
        )
        self.assertEqual(receipt.layer_targeted, 'ProfileCard')
        self.assertTrue(receipt.ok)

    def test_unknown_layer_returns_error_receipt(self):
        receipt = self.gw.update_sir_field(
            field_path='random_unknown_field',
            new_value='X',
            source='test',
            nerve=self.nerve,
        )
        self.assertFalse(receipt.ok)
        self.assertEqual(receipt.layer_targeted, 'unknown')
        self.assertIn('no router', receipt.error)


# ============================================================
# B. MemoryGateway Milestones routing
# ============================================================

class TestB_GatewayMilestones(unittest.TestCase):

    def setUp(self):
        # tmp milestone store
        self.tmpdir = tempfile.mkdtemp(prefix='gateway_ms_test_')
        self.receipt_path = os.path.join(self.tmpdir, 'mutation_receipts.jsonl')
        self.ms_path = os.path.join(self.tmpdir, 'sir_milestones.json')
        # monkey-patch milestones storage
        import jarvis_milestones as _ms
        self._orig_store_path = _ms._store_path
        _ms._store_path = lambda: self.ms_path
        from jarvis_memory_gateway import MemoryMutationGateway
        self.gw = MemoryMutationGateway(receipt_path=self.receipt_path)

    def tearDown(self):
        import jarvis_milestones as _ms
        _ms._store_path = self._orig_store_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_route_lifetime_anchor(self):
        receipt = self.gw.update_sir_field(
            field_path='lifetime_anchor.declaration',
            new_value='I am free.',
            source='sir_cli',
        )
        self.assertTrue(receipt.ok, f'milestone route failed: {receipt.error}')
        self.assertEqual(receipt.layer_targeted, 'Milestones')


# ============================================================
# C. MemoryGateway SWM + receipt persistence
# ============================================================

class TestC_GatewaySWMandReceipt(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='gateway_swm_test_')
        self.receipt_path = os.path.join(self.tmpdir, 'mutation_receipts.jsonl')
        from jarvis_memory_gateway import MemoryMutationGateway
        self.gw = MemoryMutationGateway(receipt_path=self.receipt_path)
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)
        self.nerve = _MockNerve()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_receipt_persisted_to_jsonl(self):
        self.gw.update_sir_field(
            field_path='biographic.height',
            new_value='1.83m',
            source='intent_resolver',
            nerve=self.nerve,
        )
        self.assertTrue(os.path.exists(self.receipt_path))
        with open(self.receipt_path, 'r', encoding='utf-8') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        self.assertEqual(len(lines), 1)
        d = json.loads(lines[0])
        self.assertEqual(d['field_path'], 'biographic.height')
        self.assertTrue(d['ok'])

    def test_swm_publish_on_mutation(self):
        self.gw.update_sir_field(
            field_path='biographic.weight',
            new_value='95kg',
            source='intent_resolver',
            nerve=self.nerve,
        )
        events = self.bus.recent_events(
            within_seconds=10,
            types={'sir_field_updated'},
        )
        self.assertEqual(len(events), 1)
        meta = events[0].get('metadata', {})
        self.assertEqual(meta['field_path'], 'biographic.weight')
        self.assertTrue(meta['ok'])

    def test_recent_receipts(self):
        for i in range(3):
            self.gw.update_sir_field(
                field_path=f'biographic.field_{i}',
                new_value=f'v_{i}',
                source='test', nerve=self.nerve,
            )
        recents = self.gw.recent_receipts(max_n=10)
        self.assertEqual(len(recents), 3)


# ============================================================
# D. RecentNudgeMemory
# ============================================================

class TestD_RecentNudgeMemory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='rnm_test_')
        self.path = os.path.join(self.tmpdir, 'recent_nudges.jsonl')
        from jarvis_recent_nudge_memory import RecentNudgeMemoryStore
        self.store = RecentNudgeMemoryStore(path=self.path, max_keep=10)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_record_and_recall(self):
        topic = self.store.record_nudge(
            channel='ProactiveCare',
            content='The shower was a wise choice, Sir. Time for sleep at 23:30.',
            trigger='concern=sir_sleep_streak',
        )
        self.assertIn('shower', topic.lower())
        recents = self.store.recent_nudges(within_seconds=1800)
        self.assertEqual(len(recents), 1)
        self.assertEqual(recents[0].channel, 'ProactiveCare')

    def test_persist_and_reload(self):
        self.store.record_nudge(
            channel='ReturnSentinel',
            content='I trust the shower was refreshing.',
        )
        # 重新 load
        from jarvis_recent_nudge_memory import RecentNudgeMemoryStore
        store2 = RecentNudgeMemoryStore(path=self.path, max_keep=10)
        recents = store2.recent_nudges(within_seconds=1800)
        self.assertEqual(len(recents), 1)
        self.assertEqual(recents[0].channel, 'ReturnSentinel')

    def test_prompt_block_format(self):
        self.store.record_nudge(
            channel='ProactiveCare',
            content='Sir, shower was wise choice, 23:30 sleep',
            trigger='concern=sir_sleep_streak',
        )
        self.store.record_nudge(
            channel='ReturnSentinel',
            content='Welcome back, shower must have been refreshing',
        )
        block = self.store.to_prompt_block()
        self.assertIn('[RECENT JARVIS NUDGES', block)
        self.assertIn('ProactiveCare', block)
        self.assertIn('ReturnSentinel', block)
        self.assertIn('shower', block.lower())
        self.assertIn('guidance', block.lower())

    def test_rolling_max_keep(self):
        for i in range(15):
            self.store.record_nudge(channel=f'ch{i}',
                                     content=f'nudge content {i}')
        # max_keep=10 → drop earlier 5
        self.assertEqual(len(self.store._records), 10)

    def test_old_records_filtered_by_lookback(self):
        import time as _t
        # 直接 inject old record
        from jarvis_recent_nudge_memory import NudgeRecord
        old = NudgeRecord(
            ts=_t.time() - 3700,  # 1h+ ago
            iso='', channel='Old',
            content='very old nudge',
        )
        self.store._records.append(old)
        # 5min lookback → 不包含 old
        recents = self.store.recent_nudges(within_seconds=300)
        self.assertEqual(len(recents), 0)
        # 2h lookback → 包含
        recents = self.store.recent_nudges(within_seconds=7200)
        self.assertEqual(len(recents), 1)

    def test_stats(self):
        self.store.record_nudge(channel='ProactiveCare', content='X')
        self.store.record_nudge(channel='ProactiveCare', content='Y')
        self.store.record_nudge(channel='ReturnSentinel', content='Z')
        s = self.store.stats()
        self.assertEqual(s['total'], 3)
        self.assertEqual(s['by_channel']['ProactiveCare'], 2)
        self.assertEqual(s['by_channel']['ReturnSentinel'], 1)


if __name__ == '__main__':
    unittest.main()
