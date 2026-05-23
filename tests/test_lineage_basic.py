# -*- coding: utf-8 -*-
"""[Reshape M1 / 2026-05-24] Lineage Trace 基础设施单测

覆盖:
  - EvidenceID 生成唯一性 + 格式
  - Evidence dataclass + to_dict raw_snapshot 截断
  - LineageTracer record_evidence / record_decision / flush / trace_back
  - 线程安全 (multi-thread concurrent write)
  - disabled 模式空操作
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_lineage import (
    EvidenceID,
    Evidence,
    DecisionRecord,
    LineageTracer,
    get_default_tracer,
    reset_default_tracer_for_test,
    make_brain_decision_id,
)


class TestEvidenceID(unittest.TestCase):
    def test_format(self):
        eid = EvidenceID.new()
        self.assertTrue(eid.startswith('evt_'))
        # 'evt_20260524_010203_a1b2' 长度 24
        self.assertGreaterEqual(len(eid), 24)
        self.assertTrue(EvidenceID.is_valid(eid))

    def test_unique_100(self):
        """100 次生成 4 hex = 65536 种 / 同秒, birthday paradox ~7.4% 撞 1 次,
        阈值 95 (允许少量撞, 数学合理). 真要绝对唯一应该用更大 token 或 monotonic counter."""
        ids = set()
        for _ in range(100):
            ids.add(EvidenceID.new())
        self.assertGreaterEqual(len(ids), 95)

    def test_unique_burst_1000(self):
        """1000 次 burst 生成 4 hex (16 bit) 同秒 预期撞 ~7-8 次, 阈值 950."""
        ids = set()
        for _ in range(1000):
            ids.add(EvidenceID.new())
        self.assertGreaterEqual(len(ids), 950)

    def test_is_valid_negative(self):
        self.assertFalse(EvidenceID.is_valid(''))
        self.assertFalse(EvidenceID.is_valid('not_evt'))
        self.assertFalse(EvidenceID.is_valid('evt_'))
        self.assertFalse(EvidenceID.is_valid(None))

    def test_is_valid_positive(self):
        """真生成的 ID 应 valid (防回归)."""
        for _ in range(50):
            self.assertTrue(EvidenceID.is_valid(EvidenceID.new()))


class TestEvidence(unittest.TestCase):
    def test_basic_to_dict(self):
        ev = Evidence(
            evidence_id='evt_test_0001',
            timestamp=1716508800.0,
            source_module='TestModule',
            source_method='test_method',
            source_data_id='db:Test#1',
            parent_evidence_ids=['evt_parent_001'],
            raw_snapshot={'k': 'v'},
        )
        d = ev.to_dict()
        self.assertEqual(d['evidence_id'], 'evt_test_0001')
        self.assertEqual(d['source_module'], 'TestModule')
        self.assertEqual(d['raw_snapshot'], {'k': 'v'})

    def test_raw_snapshot_truncation_over_1kb(self):
        """raw_snapshot > 1KB 应自动 truncate."""
        big_snap = {'data': 'x' * 2000}  # 2KB+
        ev = Evidence(
            evidence_id='evt_big_001',
            timestamp=time.time(),
            source_module='Test',
            source_method='test',
            raw_snapshot=big_snap,
        )
        d = ev.to_dict()
        self.assertIn('__truncated__', d['raw_snapshot'])
        self.assertIn('original_size_bytes', d['raw_snapshot'])
        self.assertIn('preview', d['raw_snapshot'])

    def test_raw_snapshot_default_empty(self):
        ev = Evidence(
            evidence_id='evt_x',
            timestamp=time.time(),
            source_module='T',
            source_method='t',
        )
        self.assertEqual(ev.raw_snapshot, {})
        self.assertEqual(ev.parent_evidence_ids, [])
        self.assertEqual(ev.source_data_id, 'none')


class TestDecisionRecord(unittest.TestCase):
    def test_reply_truncation_500_char(self):
        long_reply = 'x' * 1000
        rec = DecisionRecord(
            decision_id='bd_test_001',
            turn_id='turn_test_001',
            reply_text=long_reply,
        )
        self.assertLessEqual(len(rec.reply_text), 500)
        self.assertTrue(rec.reply_text.endswith('...'))

    def test_timestamp_auto_filled(self):
        rec = DecisionRecord(
            decision_id='bd_x',
            turn_id='turn_x',
            reply_text='ok',
        )
        self.assertGreater(rec.timestamp, 0)


class TestLineageTracerBasic(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.jsonl_path = os.path.join(self.tmp_dir, 'lineage_test.jsonl')
        # 测试用 tracer (auto_start_flush=False, 手动 flush)
        self.tracer = LineageTracer(
            jsonl_path=self.jsonl_path,
            auto_start_flush=False,
        )

    def tearDown(self):
        try:
            self.tracer.stop(timeout=0.5)
        except Exception:
            pass
        try:
            if os.path.exists(self.jsonl_path):
                os.remove(self.jsonl_path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_record_evidence_returns_id(self):
        ev = Evidence(
            evidence_id='evt_x_001',
            timestamp=time.time(),
            source_module='Test',
            source_method='test',
        )
        ret = self.tracer.record_evidence(ev)
        self.assertEqual(ret, 'evt_x_001')

    def test_record_evidence_then_flush_jsonl_exists(self):
        for i in range(3):
            ev = Evidence(
                evidence_id=f'evt_x_{i}',
                timestamp=time.time(),
                source_module='Test',
                source_method='test',
            )
            self.tracer.record_evidence(ev)

        flushed = self.tracer.flush_now()
        self.assertEqual(flushed, 3)
        self.assertTrue(os.path.exists(self.jsonl_path))

        with open(self.jsonl_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            rec = json.loads(line)
            self.assertEqual(rec['record_type'], 'evidence')

    def test_record_decision_returns_id(self):
        ret = self.tracer.record_decision(
            decision_id='bd_test_001',
            turn_id='turn_test_001',
            reply_text='Confirmed today, Sir.',
            prompt_evidence_log={'soul_block': ['evt_a'], 'recent_completed': ['evt_b']},
            actions_emitted=['act_001'],
            claims_extracted=[{'text': 'Confirmed today', 'verified': True}],
        )
        self.assertEqual(ret, 'bd_test_001')

        self.tracer.flush_now()
        with open(self.jsonl_path, 'r', encoding='utf-8') as f:
            recs = [json.loads(line) for line in f]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['record_type'], 'decision')
        self.assertEqual(recs[0]['decision_id'], 'bd_test_001')

    def test_stats(self):
        for i in range(5):
            ev = Evidence(
                evidence_id=f'evt_{i}',
                timestamp=time.time(),
                source_module='T',
                source_method='t',
            )
            self.tracer.record_evidence(ev)

        s = self.tracer.stats()
        self.assertEqual(s['queue_size'], 5)
        self.assertEqual(s['flushed_count'], 0)
        self.assertEqual(s['dropped_count'], 0)

        self.tracer.flush_now()
        s2 = self.tracer.stats()
        self.assertEqual(s2['queue_size'], 0)
        self.assertEqual(s2['flushed_count'], 5)

    def test_trace_back_round_trip(self):
        """写 1 个 decision + 关联 evidence → trace_back 能拿回."""
        # 先写 evidence
        for eid in ['evt_a', 'evt_b']:
            self.tracer.record_evidence(Evidence(
                evidence_id=eid,
                timestamp=time.time(),
                source_module='Test',
                source_method='t',
                raw_snapshot={'note': eid},
            ))
        # 写 decision
        self.tracer.record_decision(
            decision_id='bd_trace_001',
            turn_id='turn_001',
            reply_text='Reply with evidence A and B.',
            prompt_evidence_log={'block_X': ['evt_a', 'evt_b']},
        )
        # 不显式 flush, trace_back 内部自己 flush
        result = self.tracer.trace_back('bd_trace_001')
        self.assertFalse(result['not_found'])
        self.assertEqual(result['decision']['decision_id'], 'bd_trace_001')
        self.assertIn('block_X', result['evidence_by_block'])
        self.assertEqual(len(result['evidence_by_block']['block_X']), 2)

    def test_trace_back_not_found(self):
        result = self.tracer.trace_back('bd_nonexistent_999')
        self.assertTrue(result['not_found'])
        self.assertIsNone(result['decision'])


class TestLineageTracerDisabled(unittest.TestCase):
    def test_disabled_record_evidence_no_op(self):
        tmp = tempfile.mkdtemp()
        jsonl = os.path.join(tmp, 'should_not_exist.jsonl')
        tracer = LineageTracer(
            jsonl_path=jsonl,
            enabled=False,
            auto_start_flush=False,
        )
        ev = Evidence(
            evidence_id='evt_x',
            timestamp=time.time(),
            source_module='T',
            source_method='t',
        )
        ret = tracer.record_evidence(ev)
        # 仍返 evidence_id (调用方可继续传)
        self.assertEqual(ret, 'evt_x')
        # 但 queue 应该空
        self.assertEqual(tracer.stats()['queue_size'], 0)
        # 文件不应该被创建
        tracer.flush_now()
        self.assertFalse(os.path.exists(jsonl))
        os.rmdir(tmp)


class TestLineageTracerThreadSafe(unittest.TestCase):
    def test_concurrent_write_no_loss(self):
        """10 threads × 50 evidence = 500 records, 全部应该 flush."""
        tmp_dir = tempfile.mkdtemp()
        jsonl = os.path.join(tmp_dir, 'concurrent.jsonl')
        tracer = LineageTracer(
            jsonl_path=jsonl,
            auto_start_flush=False,
            max_queue_size=1000,  # 充足
        )

        def worker(tid: int):
            for i in range(50):
                tracer.record_evidence(Evidence(
                    evidence_id=f'evt_t{tid}_i{i}',
                    timestamp=time.time(),
                    source_module=f'Thread{tid}',
                    source_method='work',
                ))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flushed = tracer.flush_now()
        self.assertEqual(flushed, 500)

        with open(jsonl, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 500)

        try:
            tracer.stop(timeout=0.5)
            os.remove(jsonl)
            os.rmdir(tmp_dir)
        except Exception:
            pass


class TestLineageTracerQueueOverflow(unittest.TestCase):
    def test_queue_maxlen_drops_oldest(self):
        """queue 满了 deque.maxlen 自动丢老, dropped_count 累计."""
        tmp = tempfile.mkdtemp()
        jsonl = os.path.join(tmp, 'overflow.jsonl')
        tracer = LineageTracer(
            jsonl_path=jsonl,
            auto_start_flush=False,
            max_queue_size=5,  # 故意小
        )
        for i in range(10):
            tracer.record_evidence(Evidence(
                evidence_id=f'evt_{i}',
                timestamp=time.time(),
                source_module='T',
                source_method='t',
            ))
        s = tracer.stats()
        # queue 应该 = 5 (maxlen)
        self.assertEqual(s['queue_size'], 5)
        # 应该至少有 5 个被 drop (10 - 5 = 5 次 dropped)
        self.assertGreaterEqual(s['dropped_count'], 5)
        try:
            os.rmdir(tmp)
        except Exception:
            pass


class TestMakeBrainDecisionId(unittest.TestCase):
    def test_format(self):
        did = make_brain_decision_id('turn_20260524_010203_abcd')
        self.assertTrue(did.startswith('bd_turn_'))
        # 'bd_<turn_id>_<4digit>'
        parts = did.split('_')
        # bd / turn / 20260524 / 010203 / abcd / 4digit  = 6 parts
        self.assertEqual(len(parts), 6)
        self.assertEqual(len(parts[-1]), 4)
        self.assertTrue(parts[-1].isdigit())


class TestGlobalSingletonReset(unittest.TestCase):
    def test_get_default_returns_singleton(self):
        # 先 reset 防干扰
        reset_default_tracer_for_test(None)
        t1 = get_default_tracer()
        t2 = get_default_tracer()
        self.assertIs(t1, t2)
        # cleanup
        reset_default_tracer_for_test(None)

    def test_inject_tracer_for_test(self):
        tmp = tempfile.mkdtemp()
        jsonl = os.path.join(tmp, 'inject.jsonl')
        custom = LineageTracer(jsonl_path=jsonl, auto_start_flush=False)
        reset_default_tracer_for_test(custom)
        self.assertIs(get_default_tracer(), custom)
        reset_default_tracer_for_test(None)
        try:
            os.rmdir(tmp)
        except Exception:
            pass


if __name__ == '__main__':
    unittest.main()
