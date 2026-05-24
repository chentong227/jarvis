# -*- coding: utf-8 -*-
"""[Reshape M1.3-min / 2026-05-24] collect_evidence_ids 单测

覆盖:
  - ConversationEventBus.collect_evidence_ids 返回近期 events 的 evidence_id list
  - within_seconds / types filter 正确
  - 没 evidence_id 的 event (legacy 兼容) 跳过
  - prompt_evidence_log → trace_back 完整 round trip
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_utils import ConversationEventBus
from jarvis_lineage import (
    LineageTracer,
    EvidenceID,
    make_brain_decision_id,
    reset_default_tracer_for_test,
)


class TestCollectEvidenceIds(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.jsonl_path = os.path.join(self.tmp_dir, 'lineage_collect.jsonl')
        self.tracer = LineageTracer(
            jsonl_path=self.jsonl_path,
            auto_start_flush=False,
        )
        reset_default_tracer_for_test(self.tracer)
        self.bus = ConversationEventBus(restore=False)

    def tearDown(self):
        try:
            self.tracer.stop(timeout=0.3)
        except Exception:
            pass
        reset_default_tracer_for_test(None)
        try:
            if os.path.exists(self.jsonl_path):
                os.remove(self.jsonl_path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_collect_basic(self):
        eid1 = self.bus.publish('event_a', 'desc a', source='ModA')
        eid2 = self.bus.publish('event_b', 'desc b', source='ModB')
        self.assertIsNotNone(eid1)
        self.assertIsNotNone(eid2)

        ids = self.bus.collect_evidence_ids(within_seconds=60.0)
        self.assertIn(eid1, ids)
        self.assertIn(eid2, ids)

    def test_collect_filter_by_types(self):
        eid_a = self.bus.publish('proactive_nudge', 'nudge x', source='M')
        eid_b = self.bus.publish('tool_executed', 'tool y', source='M')
        ids = self.bus.collect_evidence_ids(within_seconds=60.0, types={'proactive_nudge'})
        self.assertIn(eid_a, ids)
        self.assertNotIn(eid_b, ids)

    def test_collect_empty_bus(self):
        ids = self.bus.collect_evidence_ids(within_seconds=60.0)
        self.assertEqual(ids, [])

    def test_collect_skips_event_without_evidence_id(self):
        """Legacy event (无 evidence_id) 应跳过, 不抛."""
        # 模拟一个 legacy event (手动加, 没 evidence_id 字段)
        # 实际新 publish 都有, 这里强 test 兼容性
        with self.bus._lock:
            self.bus._events.append({
                'type': 'legacy_event',
                'description': 'no evidence id',
                'timestamp': time.time(),
                'ttl': 60.0,
                'source': 'legacy',
                'metadata': {},
                'salience': 0.5,
                # 故意没 evidence_id
            })
        # 再加正常 event
        eid_new = self.bus.publish('new_event', 'has eid', source='M')

        ids = self.bus.collect_evidence_ids(within_seconds=60.0)
        # 只返新 eid, legacy 跳过
        self.assertEqual(ids, [eid_new])


class TestPromptEvidenceLogRoundTrip(unittest.TestCase):
    """M1.3-min 完整 round trip: publish → collect → record_decision → trace_back."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.jsonl_path = os.path.join(self.tmp_dir, 'lineage_rt.jsonl')
        self.tracer = LineageTracer(
            jsonl_path=self.jsonl_path,
            auto_start_flush=False,
        )
        reset_default_tracer_for_test(self.tracer)
        self.bus = ConversationEventBus(restore=False)

    def tearDown(self):
        try:
            self.tracer.stop(timeout=0.3)
        except Exception:
            pass
        reset_default_tracer_for_test(None)
        try:
            if os.path.exists(self.jsonl_path):
                os.remove(self.jsonl_path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_full_round_trip_swm_blocks(self):
        """模拟 _assemble_prompt + chat_bypass.stream_chat 末尾 record_decision."""
        # 1. 几个模块 publish 到 SWM
        eid_a = self.bus.publish('emotion_shift', 'Stressed -> Calm', source='SirStatus')
        eid_b = self.bus.publish('tool_executed', 'memory.list done', source='memory_hands')
        eid_c = self.bus.publish('commitment_detected', 'will commit', source='gatekeeper')

        # 2. 模拟 _assemble_prompt 装 evidence_log
        evidence_log = {
            'swm_conversation_360s': self.bus.collect_evidence_ids(within_seconds=360.0),
        }

        # 3. 模拟 chat_bypass.stream_chat 末尾 record_decision
        turn_id = 'turn_20260524_073200_xxxx'
        decision_id = make_brain_decision_id(turn_id)
        self.tracer.record_decision(
            decision_id=decision_id,
            turn_id=turn_id,
            reply_text='Acknowledged, Sir. Memory cleared.',
            prompt_evidence_log=evidence_log,
            claims_extracted=[
                {'text': '<ClaimTracer ran: 1 claims, 1 verified, 0 unverified>',
                 'verified': True, 'is_aggregate': True}
            ],
        )

        # 4. trace_back 反向追溯
        result = self.tracer.trace_back(decision_id)
        self.assertFalse(result['not_found'])
        d = result['decision']
        self.assertEqual(d['turn_id'], turn_id)

        # 5. 验证 evidence_by_block 拿到完整 3 个 evidence
        ebb = result['evidence_by_block']
        self.assertIn('swm_conversation_360s', ebb)
        self.assertEqual(len(ebb['swm_conversation_360s']), 3)

        # 6. 验证每个 evidence 都有正确 source_module
        modules = sorted([ev['source_module'] for ev in ebb['swm_conversation_360s']])
        self.assertEqual(modules, ['SirStatus', 'gatekeeper', 'memory_hands'])


if __name__ == '__main__':
    unittest.main()
