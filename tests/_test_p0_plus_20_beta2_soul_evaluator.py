# -*- coding: utf-8 -*-
"""[P0+20-β.2.6 / 2026-05-17] 灵魂工程 Layer 5 - SoulAlignmentEvaluator 测试

评 "Jarvis 本轮回复是否对齐 self_model + relational_state"。
与 DirectiveEvaluator (β.0.5) 区别：
- DirectiveEvaluator: compliance（评 fired directive 是否被遵守）
- SoulAlignmentEvaluator: alignment（评 reply 是否引用/honored 相关 concerns）

详 docs/JARVIS_SOUL_DRIVE.md §5.3
"""
import os
import sys
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_concerns import (
    Concern, ConcernsLedger,
    bootstrap_default_concerns,
    STATE_ACTIVE,
)
from jarvis_relational import (
    RelationalStateStore, InsideJoke, UnspokenProtocol, UnfinishedBusiness,
)
from jarvis_soul_evaluator import (
    SoulAlignmentEvaluator, SoulEvalResult,
    _parse_soul_response, SOUL_EVALUATOR_CONFIG,
    get_default_soul_evaluator, reset_default_soul_evaluator_for_test,
)


# ============================================================
# A. _parse_soul_response
# ============================================================
class TestParseSoulResponse(unittest.TestCase):

    def test_valid_yes(self):
        r = _parse_soul_response(
            '{"alignment":"yes","aligned_concern_ids":["c1"],'
            '"missed_concern_ids":[],"what_aligned":"x","what_missed":""}'
        )
        self.assertEqual(r['alignment'], 'yes')
        self.assertEqual(r['aligned_concern_ids'], ['c1'])

    def test_valid_partial(self):
        r = _parse_soul_response('{"alignment":"partial"}')
        self.assertEqual(r['alignment'], 'partial')

    def test_valid_no_with_missed(self):
        r = _parse_soul_response(
            '{"alignment":"no","missed_concern_ids":["sir_sleep_streak"]}'
        )
        self.assertEqual(r['alignment'], 'no')
        self.assertEqual(r['missed_concern_ids'], ['sir_sleep_streak'])

    def test_embedded_in_text(self):
        r = _parse_soul_response(
            'My analysis:\n{"alignment":"yes","aligned_concern_ids":["x"]}\nDone.'
        )
        self.assertEqual(r['alignment'], 'yes')

    def test_invalid_json(self):
        r = _parse_soul_response('this is not json')
        self.assertEqual(r['alignment'], 'unknown')

    def test_empty_input(self):
        r = _parse_soul_response('')
        self.assertEqual(r['alignment'], 'unknown')

    def test_unknown_alignment_value(self):
        r = _parse_soul_response('{"alignment":"definitely_yes"}')
        self.assertEqual(r['alignment'], 'unknown')

    def test_concern_ids_capped(self):
        """超过 10 个 concern_ids 应被 cap"""
        ids = '["' + '","'.join(f'c{i}' for i in range(20)) + '"]'
        r = _parse_soul_response(
            f'{{"alignment":"yes","aligned_concern_ids":{ids}}}'
        )
        self.assertLessEqual(len(r['aligned_concern_ids']), 10)


# ============================================================
# B. Concern.record_alignment / aligned_count / missed_count
# ============================================================
class TestConcernAlignmentFields(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.ledger = ConcernsLedger(persist_path=self.tmp.name)
        bootstrap_default_concerns(self.ledger)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_record_alignment_increments_aligned(self):
        ok = self.ledger.record_alignment('sir_sleep_streak', aligned=True)
        self.assertTrue(ok)
        c = self.ledger.get('sir_sleep_streak')
        self.assertEqual(c.aligned_count, 1)
        self.assertGreater(c.last_aligned_at, 0)

    def test_record_alignment_increments_missed(self):
        self.ledger.record_alignment('sir_sleep_streak', aligned=False)
        c = self.ledger.get('sir_sleep_streak')
        self.assertEqual(c.missed_count, 1)
        self.assertGreater(c.last_missed_at, 0)

    def test_record_alignment_unknown_concern(self):
        ok = self.ledger.record_alignment('nonexistent_concern', aligned=True)
        self.assertFalse(ok)

    def test_persist_load_alignment_fields(self):
        self.ledger.record_alignment('sir_sleep_streak', aligned=True)
        self.ledger.record_alignment('sir_sleep_streak', aligned=True)
        self.ledger.record_alignment('sir_sleep_streak', aligned=False)
        self.assertTrue(self.ledger.persist())
        # 新 ledger 从盘上 load
        l2 = ConcernsLedger(persist_path=self.tmp.name)
        l2.load()
        c = l2.get('sir_sleep_streak')
        self.assertEqual(c.aligned_count, 2)
        self.assertEqual(c.missed_count, 1)
        self.assertGreater(c.last_aligned_at, 0)
        self.assertGreater(c.last_missed_at, 0)

    def test_legacy_json_no_alignment_fields(self):
        """老 JSON 没 aligned_count/missed_count 字段，load 时应兼容默认 0"""
        import json
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump({
                'c1': {
                    'id': 'c1', 'what_i_watch': 'x', 'why_i_care': 'y',
                    'severity': 0.5,
                    # 没有 aligned_count / missed_count
                }
            }, f)
        l = ConcernsLedger(persist_path=self.tmp.name)
        l.load()
        c = l.get('c1')
        self.assertIsNotNone(c)
        self.assertEqual(c.aligned_count, 0)
        self.assertEqual(c.missed_count, 0)


# ============================================================
# C. SoulAlignmentEvaluator mock 端到端
# ============================================================
class TestSoulEvaluatorMockedLLM(unittest.TestCase):
    """mock safe_openrouter_call + key_router 测完整流程"""

    def setUp(self):
        reset_default_soul_evaluator_for_test()
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.ledger = ConcernsLedger(persist_path=self.tmp.name)
        bootstrap_default_concerns(self.ledger)

        self.tmp_rel = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp_rel.close()
        os.unlink(self.tmp_rel.name)
        self.rel = RelationalStateStore(persist_path=self.tmp_rel.name)
        self.rel.add_inside_joke(InsideJoke(id='j1', phrase='test joke', tone='dry'))

        self.key_router = MagicMock()
        self.key_router.get_openrouter_key.return_value = ('fake_key', 'or_1')

        self.eval = SoulAlignmentEvaluator(
            key_router=self.key_router,
            concerns_ledger=self.ledger,
            relational_state=self.rel,
            pool_size=1,
        )

    def tearDown(self):
        try:
            self.eval.shutdown(wait=True)
        except Exception:
            pass
        reset_default_soul_evaluator_for_test()
        for p in (self.tmp.name, self.tmp_rel.name):
            if os.path.exists(p):
                os.unlink(p)

    def test_evaluate_async_records_alignment_yes(self):
        mock_resp = (
            '{"alignment":"yes","aligned_concern_ids":["sir_sleep_streak"],'
            '"missed_concern_ids":[],"what_aligned":"reply mentioned bedtime",'
            '"what_missed":""}'
        )
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value=mock_resp):
            self.eval.evaluate_async(
                user_input='I am exhausted, going to bed',
                jarvis_reply='Sleep well, Sir. I shall guard the night.',
                turn_id='t1',
            )
            self.eval.shutdown(wait=True)
        # 同步等 future
        c = self.ledger.get('sir_sleep_streak')
        self.assertEqual(c.aligned_count, 1)
        self.assertEqual(c.missed_count, 0)
        stats = self.eval.get_stats()
        self.assertEqual(stats['aligned_count'], 1)
        self.assertEqual(stats['concern_alignments_recorded'], 1)

    def test_evaluate_async_records_alignment_no(self):
        mock_resp = (
            '{"alignment":"no","aligned_concern_ids":[],'
            '"missed_concern_ids":["sir_sleep_streak","sir_cursor_payment"],'
            '"what_missed":"reply ignored fatigue context"}'
        )
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value=mock_resp):
            self.eval.evaluate_async(
                user_input='熬夜赶 cursor 项目',
                jarvis_reply='OK Sir, proceeding.',
                turn_id='t2',
            )
            self.eval.shutdown(wait=True)
        self.assertEqual(self.ledger.get('sir_sleep_streak').missed_count, 1)
        self.assertEqual(self.ledger.get('sir_cursor_payment').missed_count, 1)
        stats = self.eval.get_stats()
        self.assertEqual(stats['not_aligned_count'], 1)
        self.assertEqual(stats['concern_alignments_recorded'], 2)

    def test_evaluate_skipped_when_no_active_concerns(self):
        """0 active concerns → 直接 return，不调 LLM"""
        # archive 所有 concerns
        for c in list(self.ledger.list_active()):
            self.ledger.reject(c.id)
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value='') as mock_call:
            self.eval.evaluate_async(
                user_input='hi', jarvis_reply='Hello, Sir.',
                turn_id='t3',
            )
            self.eval.shutdown(wait=True)
        self.assertEqual(mock_call.call_count, 0)
        self.assertEqual(self.eval.get_stats()['submitted'], 0)

    def test_evaluate_skipped_when_reply_too_short(self):
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value='') as mock_call:
            self.eval.evaluate_async(
                user_input='hi', jarvis_reply='OK',  # < min_reply_chars=10
                turn_id='t4',
            )
            self.eval.shutdown(wait=True)
        self.assertEqual(mock_call.call_count, 0)

    def test_evaluate_skipped_when_no_key_router(self):
        e2 = SoulAlignmentEvaluator(
            key_router=None,
            concerns_ledger=self.ledger,
            relational_state=self.rel,
            pool_size=1,
        )
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value='') as mock_call:
            e2.evaluate_async(
                user_input='something long enough to evaluate',
                jarvis_reply='reply long enough to evaluate too',
                turn_id='t5',
            )
            e2.shutdown(wait=True)
        self.assertEqual(mock_call.call_count, 0)

    def test_llm_failure_no_crash(self):
        def _raise(*a, **kw):
            raise RuntimeError('mock LLM down')
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   side_effect=_raise):
            self.eval.evaluate_async(
                user_input='test',
                jarvis_reply='reply long enough to evaluate',
                turn_id='t6',
            )
            self.eval.shutdown(wait=True)
        stats = self.eval.get_stats()
        self.assertEqual(stats['failed'], 1)

    def test_invalid_json_response_no_record(self):
        """LLM 输出垃圾 → alignment=unknown → 不写 ledger"""
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value='this is not json'):
            self.eval.evaluate_async(
                user_input='I am tired',
                jarvis_reply='reply long enough to be evaluated',
                turn_id='t7',
            )
            self.eval.shutdown(wait=True)
        # ledger 不应有任何 alignment 累计
        for c in self.ledger.list_active():
            self.assertEqual(c.aligned_count, 0,
                             f"{c.id} aligned_count 不应为 {c.aligned_count}")

    def test_rate_limit_kicks_in(self):
        """超过 rate_limit_per_minute → 后续 submit 跳过"""
        rate = SOUL_EVALUATOR_CONFIG['rate_limit_per_minute']
        self.eval._call_times = [time.time()] * rate
        with patch('jarvis_soul_evaluator.safe_openrouter_call',
                   return_value='{"alignment":"yes"}') as mock_call:
            self.eval.evaluate_async(
                user_input='test',
                jarvis_reply='reply long enough to be evaluated',
                turn_id='rate_test',
            )
            self.eval.shutdown(wait=True)
        self.assertEqual(mock_call.call_count, 0)
        self.assertEqual(self.eval.get_stats()['rate_limited'], 1)

    def test_concerns_and_relational_summary_format(self):
        """采集的 summary 应含 concern id 和 relational phrase"""
        c_sum = self.eval._get_concerns_summary()
        r_sum = self.eval._get_relational_summary()
        # 5 个 seed concerns 至少有一个出现
        self.assertTrue(
            any(cid in c_sum for cid in
                ('sir_sleep_streak', 'jarvis_keyrouter_health',
                 'sir_cursor_payment'))
        )
        self.assertIn('test joke', r_sum)


# ============================================================
# D. Singleton
# ============================================================
class TestSoulEvaluatorSingleton(unittest.TestCase):

    def setUp(self):
        reset_default_soul_evaluator_for_test()

    def tearDown(self):
        reset_default_soul_evaluator_for_test()

    def test_get_default_returns_same(self):
        kr = MagicMock()
        ledger = ConcernsLedger()
        e1 = get_default_soul_evaluator(
            key_router=kr, concerns_ledger=ledger, relational_state=None
        )
        e2 = get_default_soul_evaluator()
        self.assertIs(e1, e2)
        e1.shutdown(wait=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
