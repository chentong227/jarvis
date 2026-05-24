# -*- coding: utf-8 -*-
"""[Reshape M1.2 / 2026-05-24] SWM ConversationEventBus.publish 加 evidence 字段测试

覆盖:
  - publish 返回 evidence_id (str) 而非 bool
  - 老 caller `if bus.publish(...)` 仍 work (truthy)
  - dedupe 抑制返 None
  - evidence_chain 传递 + 存入 event dict
  - LineageTracer 被异步 record (mock 验证)
  - 不破老 metadata / salience / ttl 参数
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_utils import ConversationEventBus
from jarvis_lineage import (
    LineageTracer,
    EvidenceID,
    reset_default_tracer_for_test,
    get_default_tracer,
)


class _LineageTestMixin:
    """每个 test 注入隔离的 LineageTracer."""

    def _setup_isolated_tracer(self):
        self.tmp_dir = tempfile.mkdtemp()
        jsonl = os.path.join(self.tmp_dir, f'lineage_{int(time.time()*1000)}.jsonl')
        self.tracer = LineageTracer(jsonl_path=jsonl, auto_start_flush=False)
        reset_default_tracer_for_test(self.tracer)

    def _teardown_isolated_tracer(self):
        try:
            self.tracer.stop(timeout=0.3)
        except Exception:
            pass
        reset_default_tracer_for_test(None)
        try:
            for f in os.listdir(self.tmp_dir):
                os.remove(os.path.join(self.tmp_dir, f))
            os.rmdir(self.tmp_dir)
        except Exception:
            pass


class TestPublishReturnsEvidenceId(_LineageTestMixin, unittest.TestCase):
    def setUp(self):
        self._setup_isolated_tracer()
        self.bus = ConversationEventBus(restore=False)  # M1.2: 干净 deque

    def tearDown(self):
        self._teardown_isolated_tracer()

    def test_basic_publish_returns_evidence_id(self):
        eid = self.bus.publish('test_event', 'test desc', source='test')
        self.assertIsNotNone(eid)
        self.assertTrue(EvidenceID.is_valid(eid))

    def test_backward_compat_truthy(self):
        """老 caller 用 `if bus.publish(...)` 仍 work."""
        # truthy case
        ret = self.bus.publish('test_event_a', 'desc a', source='t')
        self.assertTrue(bool(ret))

        # falsy case: dedupe 抑制 (8s 内同 etype+desc[:60])
        ret2 = self.bus.publish('test_event_a', 'desc a', source='t')
        self.assertFalse(bool(ret2))
        self.assertIsNone(ret2)

    def test_empty_etype_returns_none(self):
        self.assertIsNone(self.bus.publish('', 'desc', source='t'))
        self.assertIsNone(self.bus.publish('etype', '', source='t'))


class TestPublishWithEvidenceChain(_LineageTestMixin, unittest.TestCase):
    def setUp(self):
        self._setup_isolated_tracer()
        self.bus = ConversationEventBus(restore=False)

    def tearDown(self):
        self._teardown_isolated_tracer()

    def test_evidence_chain_stored_in_event(self):
        parent_id = EvidenceID.new()
        eid = self.bus.publish(
            'cascade_event', 'caused by parent',
            source='cascade_test',
            evidence_chain=[parent_id],
        )
        self.assertIsNotNone(eid)

        # event dict 内应该有 evidence_chain
        events = self.bus.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['evidence_chain'], [parent_id])
        self.assertEqual(events[0]['evidence_id'], eid)

    def test_custom_evidence_id_honored(self):
        custom_id = 'evt_custom_test_001'
        eid = self.bus.publish(
            'test_e', 'custom desc',
            source='t',
            evidence_id=custom_id,
        )
        self.assertEqual(eid, custom_id)
        events = self.bus.recent_events()
        self.assertEqual(events[0]['evidence_id'], custom_id)


class TestPublishLineageRecord(_LineageTestMixin, unittest.TestCase):
    def setUp(self):
        self._setup_isolated_tracer()
        self.bus = ConversationEventBus(restore=False)

    def tearDown(self):
        self._teardown_isolated_tracer()

    def test_publish_triggers_lineage_record(self):
        """publish 应触发 LineageTracer.record_evidence."""
        self.assertEqual(self.tracer.stats()['queue_size'], 0)

        eid = self.bus.publish('test_e', 'lineage trace test', source='test_mod')

        self.assertEqual(self.tracer.stats()['queue_size'], 1)
        self.tracer.flush_now()

        # 读 jsonl 验证内容
        import json
        with open(self.tracer.jsonl_path, 'r', encoding='utf-8') as f:
            records = [json.loads(line) for line in f]
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec['record_type'], 'evidence')
        self.assertEqual(rec['evidence_id'], eid)
        self.assertEqual(rec['source_module'], 'test_mod')
        self.assertEqual(rec['source_method'], 'event_bus.publish')
        self.assertEqual(rec['source_data_id'], 'swm:test_e')

    def test_publish_dedupe_no_lineage_record(self):
        """dedupe 抑制时不应 record (因为没真写入 event_bus)."""
        self.bus.publish('test_e_d', 'dedupe test', source='t')
        # 第二次同 etype+desc 8s 内抑制
        eid2 = self.bus.publish('test_e_d', 'dedupe test', source='t')
        self.assertIsNone(eid2)
        # tracer 只 record 1 个 (第一次)
        self.assertEqual(self.tracer.stats()['queue_size'], 1)


class TestPublishBackwardCompat(_LineageTestMixin, unittest.TestCase):
    """确保所有老参数 / 行为不破."""

    def setUp(self):
        self._setup_isolated_tracer()
        self.bus = ConversationEventBus(restore=False)

    def tearDown(self):
        self._teardown_isolated_tracer()

    def test_metadata_preserved(self):
        eid = self.bus.publish(
            'test_e', 'desc',
            source='t',
            metadata={'k1': 'v1', 'k2': 42},
        )
        self.assertIsNotNone(eid)
        evs = self.bus.recent_events()
        self.assertEqual(evs[0]['metadata'], {'k1': 'v1', 'k2': 42})

    def test_salience_preserved(self):
        eid = self.bus.publish('test_e', 'desc', source='t', salience=0.95)
        evs = self.bus.recent_events()
        self.assertAlmostEqual(evs[0]['salience'], 0.95)

    def test_ttl_preserved(self):
        eid = self.bus.publish('test_e', 'desc', source='t', ttl=999.0)
        evs = self.bus.recent_events()
        self.assertEqual(evs[0]['ttl'], 999.0)

    def test_description_truncation(self):
        long_desc = 'x' * 1000
        eid = self.bus.publish('test_e', long_desc, source='t')
        evs = self.bus.recent_events()
        self.assertLessEqual(len(evs[0]['description']), 300)


class TestPublishLineageDegrade(unittest.TestCase):
    """lineage 模块不可用时 publish 仍 work (degrade gracefully)."""

    def test_publish_works_when_lineage_import_fails(self):
        bus = ConversationEventBus(restore=False)
        with mock.patch.dict('sys.modules', {'jarvis_lineage': None}):
            # import 失败应该 catch, publish 不 throw
            try:
                # 此时 evidence_id 自动 gen 会失败 → 内部 evidence_id = None
                # 但 publish 仍应正常返回 (可能 None 或 evt_id, 看 import 时机)
                ret = bus.publish('degrade_test', 'desc', source='t')
                # 不强求返 None 还是 evt_id, 只要 publish 不 throw
            except Exception as e:
                self.fail(f'publish 不应 throw 即使 lineage 不可用: {e}')


if __name__ == '__main__':
    unittest.main()
