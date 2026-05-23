# -*- coding: utf-8 -*-
"""[Reshape M2.C / 2026-05-24] UnifiedMemoryGateway deprecated stub 验证

覆盖:
  - UnifiedMemoryGateway 仍可 instantiate (noqa F401 兼容)
  - query / to_prompt_block 实际 delegate 到 MemoryHub
  - 首次 instantiate 发 DeprecationWarning
  - 行为跟 hub 一致
"""
import os
import sys
import unittest
import warnings
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_memory_core import UnifiedMemoryGateway
from jarvis_memory_gateway import get_default_hub


class TestDeprecatedStub(unittest.TestCase):
    def setUp(self):
        # 重置 warned 标志, 让每个 test 都能触发 warn
        UnifiedMemoryGateway._warned = False

    def test_can_instantiate(self):
        nerve = MagicMock()
        gw = UnifiedMemoryGateway(nerve)
        self.assertIsNotNone(gw)
        self.assertIs(gw.nerve, nerve)

    def test_emits_deprecation_warning_first_time(self):
        nerve = MagicMock()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            UnifiedMemoryGateway(nerve)
            self.assertTrue(any(issubclass(x.category, DeprecationWarning)
                                 for x in w))
            self.assertTrue(any('MemoryHub' in str(x.message) for x in w))

    def test_warns_only_once(self):
        nerve = MagicMock()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            UnifiedMemoryGateway(nerve)
            UnifiedMemoryGateway(nerve)
            UnifiedMemoryGateway(nerve)
            depr = [x for x in w if issubclass(x.category, DeprecationWarning)]
            # 只第一次发, 后续不重发
            self.assertEqual(len(depr), 1)


class TestDelegation(unittest.TestCase):
    """deprecated stub 行为应跟 hub 一致 (delegate)."""

    def setUp(self):
        UnifiedMemoryGateway._warned = True  # 不再发 warn 干扰

    def test_query_empty_no_nerve_data(self):
        nerve = MagicMock()
        nerve.short_term_memory = []
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        gw = UnifiedMemoryGateway(nerve)
        result = gw.query('hello', top_k=5)
        self.assertEqual(result, [])

    def test_query_with_stm_delegates_correctly(self):
        nerve = MagicMock()
        nerve.short_term_memory = [
            {'time': '12:00', 'user': 'go run', 'jarvis': 'good sir'},
        ]
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        gw = UnifiedMemoryGateway(nerve)
        result = gw.query('run', top_k=5)
        # delegate 到 hub.query (M2.A), 行为对齐
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, 'stm')

    def test_to_prompt_block_empty(self):
        nerve = MagicMock()
        nerve.short_term_memory = []
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        gw = UnifiedMemoryGateway(nerve)
        block = gw.to_prompt_block('x', top_k=5)
        self.assertEqual(block, '')

    def test_to_prompt_block_with_stm(self):
        nerve = MagicMock()
        nerve.short_term_memory = [
            {'time': '12:00', 'user': 'hello', 'jarvis': 'hi sir'},
        ]
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None
        gw = UnifiedMemoryGateway(nerve)
        block = gw.to_prompt_block('hello', top_k=5)
        self.assertIn('[UNIFIED MEMORY', block)
        self.assertIn('[STM]', block)

    def test_behavior_matches_hub_directly(self):
        """gw 行为应跟直接调 hub.query/to_prompt_block 一致."""
        nerve = MagicMock()
        nerve.short_term_memory = [
            {'time': '12:00', 'user': 'foo', 'jarvis': 'bar'},
        ]
        nerve.hippocampus = None
        nerve.profile_card = None
        nerve.status_ledger = None
        nerve.causal_chain = None

        gw_block = UnifiedMemoryGateway(nerve).to_prompt_block('foo', top_k=5)
        hub_block = get_default_hub().to_prompt_block('foo', top_k=5, nerve=nerve)
        self.assertEqual(gw_block, hub_block)


if __name__ == '__main__':
    unittest.main()
