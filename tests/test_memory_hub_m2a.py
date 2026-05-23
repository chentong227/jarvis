# -*- coding: utf-8 -*-
"""[Reshape M2.A / 2026-05-24] MemoryHub 新 API 单测

覆盖:
  - MemoryHub alias = MemoryMutationGateway (双名)
  - get_default_hub = get_default_gateway (单例 alias)
  - 6 write_* 方法存在 + 签名正确 + 写 receipt
  - query / to_prompt_block 跟 UnifiedMemoryGateway 行为对齐
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_memory_gateway import (
    MemoryMutationGateway,
    MemoryHub,
    get_default_gateway,
    get_default_hub,
    reset_default_gateway_for_test,
    reset_default_hub_for_test,
)


class TestHubAlias(unittest.TestCase):
    """新旧名 alias 必须严格一致."""

    def test_class_alias(self):
        self.assertIs(MemoryHub, MemoryMutationGateway)

    def test_getter_alias(self):
        self.assertIs(get_default_hub, get_default_gateway)
        self.assertIs(reset_default_hub_for_test, reset_default_gateway_for_test)

    def test_instance_works_both_names(self):
        a = MemoryMutationGateway()
        b = MemoryHub()
        self.assertIsInstance(b, MemoryMutationGateway)
        # 同一类, 行为应该完全一样
        self.assertEqual(type(a), type(b))


class TestWriteMethods(unittest.TestCase):
    """6 write_* 方法都应 attach 到 class + bound 到 instance."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='hub_m2a_')
        self.receipt_path = os.path.join(self.tmpdir, 'receipts.jsonl')
        self.hub = MemoryHub(receipt_path=self.receipt_path)

    def tearDown(self):
        try:
            for f in os.listdir(self.tmpdir):
                os.remove(os.path.join(self.tmpdir, f))
            os.rmdir(self.tmpdir)
        except Exception:
            pass

    def test_all_six_methods_exist(self):
        for name in ('write_identity', 'write_event', 'write_commitment',
                     'write_concern', 'write_state', 'write_relation'):
            self.assertTrue(hasattr(self.hub, name),
                            f'Hub 缺 {name}')
            self.assertTrue(callable(getattr(self.hub, name)))

    def test_write_identity_normalizes_path(self):
        """write_identity 自动加 'profile.' 前缀 (如果没有 profile/biographic/sir/preferences/traits 任一)."""
        nerve = MagicMock()
        nerve.profile_card = None  # 触发 'not available' 路径
        receipt = self.hub.write_identity('hobbies', ['reading'],
                                           source='test_sir',
                                           confidence=0.9, nerve=nerve)
        # field_path 应被 normalize 成 'profile.hobbies'
        self.assertEqual(receipt.field_path, 'profile.hobbies')
        self.assertEqual(receipt.layer_targeted, 'ProfileCard')

    def test_write_identity_preserves_existing_prefix(self):
        """已有 biographic./profile. 前缀不重复加."""
        nerve = MagicMock()
        nerve.profile_card = None
        r1 = self.hub.write_identity('biographic.height', '175cm',
                                       source='test', nerve=nerve)
        self.assertEqual(r1.field_path, 'biographic.height')
        r2 = self.hub.write_identity('profile.work_rhythms', {'mon': '9-6'},
                                       source='test', nerve=nerve)
        self.assertEqual(r2.field_path, 'profile.work_rhythms')

    def test_write_concern_path_format(self):
        nerve = MagicMock()
        nerve.concerns_ledger = None  # 触发 unavailable
        receipt = self.hub.write_concern('sir_sleep_streak', 'severity', 0.9,
                                          source='test', nerve=nerve)
        self.assertEqual(receipt.field_path,
                          'concerns.sir_sleep_streak.severity')
        self.assertEqual(receipt.layer_targeted, 'ConcernsLedger')

    def test_write_state_normalizes_path(self):
        nerve = MagicMock()
        receipt = self.hub.write_state('focus_window', 'pomodoro_25',
                                        source='test', nerve=nerve)
        self.assertEqual(receipt.field_path, 'state.focus_window')

    def test_write_relation_path_format(self):
        nerve = MagicMock()
        nerve.relational_state = None
        receipt = self.hub.write_relation('inside_joke', 'j1', 'phrase',
                                           'new joke',
                                           source='test', nerve=nerve)
        self.assertEqual(receipt.field_path, 'inside_joke.update.j1.phrase')
        self.assertEqual(receipt.layer_targeted, 'RelationalStateStore')

    def test_write_event_writes_receipt(self):
        """write_event 应写 receipt 不管 hippocampus 是否可用."""
        nerve = MagicMock()
        nerve.hippocampus = None
        receipt = self.hub.write_event('Sir went for a run', kind='daily',
                                        source='test_sir', nerve=nerve)
        self.assertEqual(receipt.layer_targeted, 'Hippocampus')
        self.assertEqual(receipt.field_path, 'hippocampus.daily')
        # receipt 应已写入 jsonl
        self.assertTrue(os.path.exists(self.receipt_path))

    def test_write_commitment_writes_receipt(self):
        nerve = MagicMock()
        nerve.commitment_watcher = None
        receipt = self.hub.write_commitment('remind in 1h', kind='commitment',
                                             source='test_sir', nerve=nerve)
        self.assertEqual(receipt.layer_targeted, 'CommitmentWatcher')
        self.assertEqual(receipt.field_path, 'commitment.commitment')


class TestQueryAndPromptBlock(unittest.TestCase):
    """query + to_prompt_block 从 UnifiedMemoryGateway 搬运, 行为对齐."""

    def setUp(self):
        self.hub = MemoryHub()

    def test_query_no_nerve_returns_empty(self):
        """nerve=None + 全局没设 → 空 list."""
        result = self.hub.query('hello', top_k=5, nerve=None)
        self.assertEqual(result, [])

    def test_query_explicit_nerve_empty(self):
        """nerve 给但全空 → 空."""
        nerve = MagicMock()
        nerve.short_term_memory = []
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        result = self.hub.query('hello', top_k=5, nerve=nerve)
        self.assertEqual(result, [])

    def test_query_with_stm(self):
        """STM 有内容 → fragment 包含 stm source."""
        nerve = MagicMock()
        nerve.short_term_memory = [
            {'time': '12:00', 'user': 'hello', 'jarvis': 'hi sir'},
        ]
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        result = self.hub.query('hello', top_k=5, nerve=nerve)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, 'stm')

    def test_to_prompt_block_empty(self):
        """空 query → 空 str."""
        block = self.hub.to_prompt_block('x', top_k=5, nerve=None)
        self.assertEqual(block, '')

    def test_to_prompt_block_with_stm(self):
        """STM 有内容 → 含 [UNIFIED MEMORY] 标题 + [STM] tag."""
        nerve = MagicMock()
        nerve.short_term_memory = [
            {'time': '12:00', 'user': 'go for run', 'jarvis': 'good sir'},
        ]
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        block = self.hub.to_prompt_block('run', top_k=5, nerve=nerve)
        self.assertIn('[UNIFIED MEMORY', block)
        self.assertIn('[STM]', block)


class TestBackwardCompat(unittest.TestCase):
    """老 update_sir_field API 必须仍 work, 不被新方法 shadow."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='hub_compat_')
        self.receipt_path = os.path.join(self.tmpdir, 'receipts.jsonl')
        self.hub = MemoryHub(receipt_path=self.receipt_path)

    def tearDown(self):
        try:
            for f in os.listdir(self.tmpdir):
                os.remove(os.path.join(self.tmpdir, f))
            os.rmdir(self.tmpdir)
        except Exception:
            pass

    def test_update_sir_field_still_works(self):
        nerve = MagicMock()
        nerve.profile_card = None  # 触发 'not available'
        receipt = self.hub.update_sir_field(
            field_path='biographic.height',
            new_value='180cm',
            source='legacy_caller',
            confidence=0.9,
            nerve=nerve,
        )
        self.assertEqual(receipt.field_path, 'biographic.height')
        # 老 caller 路径走 routing, layer 应识别为 ProfileCard
        self.assertEqual(receipt.layer_targeted, 'ProfileCard')


if __name__ == '__main__':
    unittest.main()
