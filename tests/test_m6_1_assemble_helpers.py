# -*- coding: utf-8 -*-
"""[Reshape M6.1 / 2026-05-24] _assemble_prompt 子函数化第一波 — 3 helper.

覆盖:
  - _build_unified_memory_block: skip 条件 / 调用 hub.to_prompt_block / fallback to old signature
  - _build_skill_tree_block: skip 条件 / 调用 skill_tree.get_skill_summary_for_prompt
  - _build_anticipator_block: skip 条件 / 调用 anticipator.get_preloaded_context
  - 行为与 _assemble_prompt 原嵌入代码一致 (regression no-break)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _make_minimal_nerve():
    """构 minimal CentralNerve 让 helper 能 attach. bypass __init__."""
    from jarvis_central_nerve import CentralNerve
    n = CentralNerve.__new__(CentralNerve)
    n._asm_stage_t = {}
    return n


class TestUnifiedMemoryBlock(unittest.TestCase):
    def test_skip_no_memory_gateway(self):
        n = _make_minimal_nerve()
        # 没 memory_gateway 属性
        result = n._build_unified_memory_block('hello', _allow_full=True,
                                                  _skip_heavy=False)
        self.assertEqual(result, '')

    def test_skip_when_not_allow_full(self):
        n = _make_minimal_nerve()
        n.memory_gateway = MagicMock()
        result = n._build_unified_memory_block('hello', _allow_full=False,
                                                  _skip_heavy=False)
        self.assertEqual(result, '')
        # 不应调 to_prompt_block
        n.memory_gateway.to_prompt_block.assert_not_called()

    def test_skip_when_skip_heavy(self):
        n = _make_minimal_nerve()
        n.memory_gateway = MagicMock()
        result = n._build_unified_memory_block('hello', _allow_full=True,
                                                  _skip_heavy=True)
        self.assertEqual(result, '')

    def test_calls_hub_with_nerve(self):
        n = _make_minimal_nerve()
        gw = MagicMock()
        gw.to_prompt_block = MagicMock(return_value='[UNIFIED] sample')
        n.memory_gateway = gw
        result = n._build_unified_memory_block('hi sir', _allow_full=True,
                                                  _skip_heavy=False)
        self.assertEqual(result, '[UNIFIED] sample')
        gw.to_prompt_block.assert_called_once_with('hi sir', top_k=3, nerve=n)
        # stage timing 真记
        self.assertIn('memory_gateway', n._asm_stage_t)

    def test_fallback_when_typeerror(self):
        """老 UnifiedMemoryGateway 没 nerve 参数, fallback 到 2-arg signature."""
        n = _make_minimal_nerve()
        gw = MagicMock()
        # 第一次调 (with nerve) 抛 TypeError, 第二次调 (no nerve) 返
        gw.to_prompt_block = MagicMock(
            side_effect=[TypeError('unexpected nerve'), '[OLD UNIFIED]'])
        n.memory_gateway = gw
        result = n._build_unified_memory_block('q', _allow_full=True,
                                                  _skip_heavy=False)
        self.assertEqual(result, '[OLD UNIFIED]')
        self.assertEqual(gw.to_prompt_block.call_count, 2)


class TestSkillTreeBlock(unittest.TestCase):
    def test_skip_no_skill_tree(self):
        n = _make_minimal_nerve()
        result = n._build_skill_tree_block(_allow_full=True, _skip_heavy=False)
        self.assertEqual(result, '')

    def test_skip_not_allow_full(self):
        n = _make_minimal_nerve()
        n.skill_tree = MagicMock()
        result = n._build_skill_tree_block(_allow_full=False, _skip_heavy=False)
        self.assertEqual(result, '')

    def test_calls_skill_tree(self):
        n = _make_minimal_nerve()
        n.skill_tree = MagicMock()
        n.skill_tree.get_skill_summary_for_prompt = MagicMock(
            return_value='[SKILL] python expert')
        result = n._build_skill_tree_block(_allow_full=True, _skip_heavy=False)
        self.assertEqual(result, '[SKILL] python expert')
        self.assertIn('skill_tree', n._asm_stage_t)


class TestAnticipatorBlock(unittest.TestCase):
    def test_skip_no_prompt_center(self):
        n = _make_minimal_nerve()
        result = n._build_anticipator_block(_skip_heavy=False)
        self.assertEqual(result, '')

    def test_skip_anticipator_none(self):
        n = _make_minimal_nerve()
        n.prompt_center = MagicMock()
        n.prompt_center.anticipator = None
        result = n._build_anticipator_block(_skip_heavy=False)
        self.assertEqual(result, '')

    def test_skip_when_skip_heavy(self):
        n = _make_minimal_nerve()
        n.prompt_center = MagicMock()
        n.prompt_center.anticipator = MagicMock()
        result = n._build_anticipator_block(_skip_heavy=True)
        self.assertEqual(result, '')

    def test_calls_anticipator(self):
        n = _make_minimal_nerve()
        n.prompt_center = MagicMock()
        n.prompt_center.anticipator = MagicMock()
        n.prompt_center.anticipator.get_preloaded_context = MagicMock(
            return_value='[ANTI] preloaded')
        result = n._build_anticipator_block(_skip_heavy=False)
        self.assertEqual(result, '[ANTI] preloaded')
        self.assertIn('anticipator', n._asm_stage_t)


if __name__ == '__main__':
    unittest.main()
