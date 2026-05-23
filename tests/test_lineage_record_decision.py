# -*- coding: utf-8 -*-
"""[Reshape M1.4 / 2026-05-24] Lineage record_decision 单测

覆盖:
  - LineageTracer.record_decision 写 jsonl 正确
  - DecisionRecord 字段完整 (decision_id / turn_id / reply / prompt_evidence_log /
    actions_emitted / claims_extracted)
  - trace_back round trip 能拿回 decision + evidence
  - make_brain_decision_id 唯一性
  - chat_bypass 风格 mock 验证 (record_decision 调用约定)
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_lineage import (
    LineageTracer,
    EvidenceID,
    Evidence,
    DecisionRecord,
    make_brain_decision_id,
    get_default_tracer,
    reset_default_tracer_for_test,
)


class TestRecordDecisionBasic(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.jsonl_path = os.path.join(self.tmp_dir, 'lineage_dec.jsonl')
        self.tracer = LineageTracer(
            jsonl_path=self.jsonl_path,
            auto_start_flush=False,
        )

    def tearDown(self):
        try:
            self.tracer.stop(timeout=0.3)
        except Exception:
            pass
        try:
            if os.path.exists(self.jsonl_path):
                os.remove(self.jsonl_path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_record_decision_round_trip(self):
        # 先 record 几个 evidence (模拟 prompt block evidence)
        eid_soul = EvidenceID.new()
        eid_recent = EvidenceID.new()
        for eid, src in [(eid_soul, 'ConcernsLedger'), (eid_recent, 'Hippocampus')]:
            self.tracer.record_evidence(Evidence(
                evidence_id=eid,
                timestamp=time.time(),
                source_module=src,
                source_method='render_for_prompt',
                source_data_id=f'mem:{src}',
                raw_snapshot={'sample': True},
            ))

        # record decision 链接 evidence
        decision_id = make_brain_decision_id('turn_20260524_010203_abcd')
        self.tracer.record_decision(
            decision_id=decision_id,
            turn_id='turn_20260524_010203_abcd',
            reply_text='Confirmed today, Sir. Hydration looking good.',
            prompt_evidence_log={
                'soul_block': [eid_soul],
                'recent_completed': [eid_recent],
            },
            actions_emitted=['act_progress_status_001'],
            claims_extracted=[
                {'text': 'Confirmed today', 'verified': True},
                {'text': 'Hydration looking good', 'verified': False},
            ],
        )

        # trace_back 验证
        result = self.tracer.trace_back(decision_id)
        self.assertFalse(result['not_found'])
        d = result['decision']
        self.assertEqual(d['decision_id'], decision_id)
        self.assertEqual(d['turn_id'], 'turn_20260524_010203_abcd')
        self.assertEqual(len(d['claims_extracted']), 2)
        self.assertEqual(len(d['actions_emitted']), 1)

        # evidence_by_block 应该有 2 block, 每 block 1 evidence
        ebb = result['evidence_by_block']
        self.assertIn('soul_block', ebb)
        self.assertIn('recent_completed', ebb)
        self.assertEqual(len(ebb['soul_block']), 1)
        self.assertEqual(ebb['soul_block'][0]['source_module'], 'ConcernsLedger')
        self.assertEqual(ebb['recent_completed'][0]['source_module'], 'Hippocampus')

    def test_record_decision_empty_log_ok(self):
        """prompt_evidence_log / actions / claims 全空也应能记录."""
        self.tracer.record_decision(
            decision_id='bd_empty_001',
            turn_id='turn_empty',
            reply_text='Acknowledged.',
        )
        result = self.tracer.trace_back('bd_empty_001')
        self.assertFalse(result['not_found'])
        self.assertEqual(result['decision']['prompt_evidence_log'], {})
        self.assertEqual(result['decision']['actions_emitted'], [])
        self.assertEqual(result['decision']['claims_extracted'], [])

    def test_record_decision_broken_chain(self):
        """prompt_evidence_log 中 evidence_id 不存在时, evidence_by_block 该 entry 空."""
        eid_orphan = EvidenceID.new()
        # 注意: 没 record_evidence(eid_orphan), 模拟 broken chain
        self.tracer.record_decision(
            decision_id='bd_broken_001',
            turn_id='turn_x',
            reply_text='reply',
            prompt_evidence_log={'block_x': [eid_orphan]},
        )
        result = self.tracer.trace_back('bd_broken_001')
        self.assertFalse(result['not_found'])
        # block_x evidence list 应该空 (因为 orphan eid 找不到)
        self.assertEqual(result['evidence_by_block']['block_x'], [])


class TestMakeBrainDecisionIdUnique(unittest.TestCase):
    def test_make_brain_decision_id_basic(self):
        bid = make_brain_decision_id('turn_x')
        self.assertTrue(bid.startswith('bd_turn_x_'))
        # 4 digit suffix
        suffix = bid.rsplit('_', 1)[-1]
        self.assertEqual(len(suffix), 4)
        self.assertTrue(suffix.isdigit())

    def test_burst_30_decisions_likely_unique(self):
        """30 次 burst (4 digit = 10000 种), 应该全唯一."""
        ids = set()
        for _ in range(30):
            ids.add(make_brain_decision_id('turn_burst'))
            time.sleep(0.001)  # 故意小间隔, 防同 ms 撞
        # 不严格 100%, 但 30 个 ≥ 28 (允许 2 撞概率极小)
        self.assertGreaterEqual(len(ids), 28)


class TestChatBypassMockRecordDecision(unittest.TestCase):
    """模拟 chat_bypass.stream_chat 末尾调 record_decision 的调用约定."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.jsonl_path = os.path.join(self.tmp_dir, 'lineage_cb.jsonl')
        self.tracer = LineageTracer(
            jsonl_path=self.jsonl_path,
            auto_start_flush=False,
        )
        reset_default_tracer_for_test(self.tracer)

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

    def test_chat_bypass_pattern(self):
        """模拟 chat_bypass.stream_chat 末尾的 record_decision 调用."""
        # 模拟 chat_bypass 流末尾的 _turn_id_now / final_reply / _claim_result
        _turn_id_now = 'turn_20260524_071000_abcd'
        final_reply = 'Today, Sir. Total hydration 1100ml.'
        _claim_result = {
            'n_claims': 2,
            'n_verified': 1,
            'n_unverified': 1,
            'unverified_examples': ['Total hydration 1100ml.'],
        }

        # 这是 chat_bypass.py:4746-4775 的 inline pattern (copy-paste 测试)
        _ln_decision_id = make_brain_decision_id(_turn_id_now)
        _ln_claims = []
        for _ex in (_claim_result.get('unverified_examples', []) or [])[:5]:
            _ln_claims.append({'text': str(_ex)[:100], 'verified': False})
        _ln_n_ver = int(_claim_result.get('n_verified', 0))
        if _ln_n_ver > 0:
            _ln_claims.append({
                'text': f'<{_ln_n_ver} verified claims>',
                'verified': True,
                'is_aggregate': True,
            })
        get_default_tracer().record_decision(
            decision_id=_ln_decision_id,
            turn_id=_turn_id_now,
            reply_text=final_reply,
            prompt_evidence_log={},
            actions_emitted=[],
            claims_extracted=_ln_claims,
        )

        # 验证
        result = self.tracer.trace_back(_ln_decision_id)
        self.assertFalse(result['not_found'])
        d = result['decision']
        self.assertEqual(d['turn_id'], _turn_id_now)
        # 1 unverified + 1 verified aggregate
        self.assertEqual(len(d['claims_extracted']), 2)
        verified_count = sum(1 for c in d['claims_extracted'] if c.get('verified'))
        unverified_count = sum(1 for c in d['claims_extracted'] if not c.get('verified'))
        self.assertEqual(verified_count, 1)
        self.assertEqual(unverified_count, 1)


if __name__ == '__main__':
    unittest.main()
