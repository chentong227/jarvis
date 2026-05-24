# -*- coding: utf-8 -*-
"""[Reshape M4.3 / 2026-05-24] Hub.write_commitment 4 kind 路由 → PromiseLog 单源.

覆盖:
  - 4 kind (commitment/cyclic/watch/self_promise) 都写 PromiseLog
  - receipt.layer_targeted = 'PromiseLog'
  - receipt.field_path = 'promise.{kind}'
  - PromiseLog 真有新 Promise (验 write 真生效)
  - trigger_pattern + bound_to_concern_id 新 field 真写
  - who_promised 真设
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_memory_hub import MemoryHub
from jarvis_promise_log import (
    PromiseExecutionLog, reset_default_log_for_test, get_default_log,
)


class TestWriteCommitmentToPromiseLog(unittest.TestCase):
    """M4.3 — hub.write_commitment 真接 PromiseLog."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_3_')
        # 隔离 PromiseLog 单例到 tmp
        self.plog_path = os.path.join(self.tmpdir, 'plog.json')
        reset_default_log_for_test(persist_path=self.plog_path)
        # 隔离 hub receipt
        self.receipt_path = os.path.join(self.tmpdir, 'receipts.jsonl')
        self.hub = MemoryHub(receipt_path=self.receipt_path)

    def tearDown(self):
        reset_default_log_for_test()  # 重置回默认
        try:
            for f in os.listdir(self.tmpdir):
                os.remove(os.path.join(self.tmpdir, f))
            os.rmdir(self.tmpdir)
        except Exception:
            pass

    def test_kind_commitment_writes_promise_log(self):
        receipt = self.hub.write_commitment(
            'Sir will sleep at 11pm', kind='commitment',
            who_promised='sir', deadline='23:00',
            jarvis_reply='Noted Sir.', source='gatekeeper',
        )
        self.assertTrue(receipt.ok, f'write 应成功, err={receipt.error}')
        self.assertEqual(receipt.layer_targeted, 'PromiseLog')
        self.assertEqual(receipt.field_path, 'promise.commitment')
        # PromiseLog 真有这条
        plog = get_default_log()
        self.assertEqual(len(plog.promises), 1)
        p = list(plog.promises.values())[0]
        self.assertEqual(p.kind, 'commitment')
        self.assertEqual(p.who_promised, 'sir')
        self.assertEqual(p.author, 'sir')
        self.assertEqual(p.deadline_str, '23:00')
        self.assertIn('sleep at 11pm', p.description)

    def test_kind_cyclic_writes_with_trigger_pattern(self):
        receipt = self.hub.write_commitment(
            'Check Sir focus every 30min', kind='cyclic',
            who_promised='jarvis',
            trigger_pattern={'kind': 'cycle_minutes', 'value': 30},
            bound_to_concern_id='sir_focus_streak',
            source='reflector',
        )
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.field_path, 'promise.cyclic')
        plog = get_default_log()
        p = list(plog.promises.values())[0]
        self.assertEqual(p.kind, 'cyclic')
        self.assertEqual(p.trigger_pattern,
                          {'kind': 'cycle_minutes', 'value': 30})
        self.assertEqual(p.bound_to_concern_id, 'sir_focus_streak')

    def test_kind_watch_writes_screen_vision_trigger(self):
        receipt = self.hub.write_commitment(
            'Wait for export progress 100%', kind='watch',
            who_promised='jarvis',
            trigger_pattern={'kind': 'screen_vision',
                              'evidence': 'export progress reaches 100%'},
            source='sir_request',
        )
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.field_path, 'promise.watch')
        plog = get_default_log()
        p = list(plog.promises.values())[0]
        self.assertEqual(p.kind, 'watch')
        self.assertEqual(p.trigger_pattern['kind'], 'screen_vision')

    def test_kind_self_promise_no_deadline(self):
        receipt = self.hub.write_commitment(
            'I shall remind Sir gently', kind='self_promise',
            who_promised='jarvis',
            jarvis_reply='Yes Sir, gently noted.',
            source='self_promise_detector',
        )
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.field_path, 'promise.self_promise')
        plog = get_default_log()
        p = list(plog.promises.values())[0]
        self.assertEqual(p.kind, 'self_promise')
        self.assertEqual(p.who_promised, 'jarvis')
        self.assertEqual(p.deadline_str, '')

    def test_receipt_persisted(self):
        """receipt jsonl 真写."""
        self.hub.write_commitment('x', kind='commitment', source='test')
        self.assertTrue(os.path.exists(self.receipt_path))
        with open(self.receipt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('PromiseLog', content)
        self.assertIn('promise.commitment', content)

    def test_who_promised_system_normalized(self):
        """who_promised='system' 时 author 仍 fallback 'jarvis' (PromiseLog 老 schema 限 jarvis/sir)."""
        receipt = self.hub.write_commitment(
            'reflector triggered cyclic', kind='cyclic',
            who_promised='system',  # 新值, 不在 jarvis/sir 之列
            source='reflector',
        )
        self.assertTrue(receipt.ok)
        plog = get_default_log()
        p = list(plog.promises.values())[0]
        # who_promised 真值保留
        self.assertEqual(p.who_promised, 'system')
        # 但 author backward compat fallback jarvis
        self.assertEqual(p.author, 'jarvis')


if __name__ == '__main__':
    unittest.main()
