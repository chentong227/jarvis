# -*- coding: utf-8 -*-
"""[SOUL Phase C.2 / Sir 2026-05-26] UnspokenProtocol trigger_tier + trigger_sir_state.

Sir 拍板 C.2 anchor:
  "复用 UnspokenProtocol 加 2 个 trigger 字段 — to_prompt_block 按
  current_tier + current_sir_state filter. 不加 directive_registry 新概念.
  解 Sir 真意场景: 'Sir 在 coding 时不要 nudge' 这种**场景化**规则不该全 tier always-on."

设计 (准则 6 数据驱动 + 4 问全 Yes):
  - UnspokenProtocol 加 trigger_tier: List[str] + trigger_sir_state: List[str]
    空 list = 全场景 always inject (向后兼容老 protocol)
    非空 list = AND filter (两个 trigger 都 match 才 inject)
  - matches_context(current_tier, current_sir_state) -> bool helper
  - to_prompt_block 加 current_tier + current_sir_state 参数, 调 matches_context filter
  - load_persist 兼容: 老 JSON 缺 trigger 字段 → 默认空 list (全场景)
  - _build_layer_2_relational_block(prompt_tier) 加参 + 拿 sir_state from
    inner_thought_daemon._classify_sir_state

测试覆盖 (12 个):
  L1 UnspokenProtocol 加 trigger_tier + trigger_sir_state 默认空
  L2 matches_context: trigger 空 = match all
  L3 matches_context: tier in trigger_tier = match
  L4 matches_context: tier 不在 trigger_tier = no match
  L5 matches_context: sir_state in trigger_sir_state = match
  L6 matches_context: 两 trigger AND 关系 (一个不 match = no match)
  L7 to_prompt_block 空 trigger 全场景 inject (向后兼容)
  L8 to_prompt_block 非空 trigger + context match = inject
  L9 to_prompt_block 非空 trigger + context no match = filter 掉
  L10 load_persist 兼容老 JSON 无 trigger 字段
  L11 _build_layer_2_relational_block 调 to_prompt_block 传 prompt_tier
  L12 端到端: protocol 限 'CHAT' tier, central_nerve prompt_tier='STANDARD' → filter 掉
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# L1: UnspokenProtocol 加字段默认空
# ==========================================================================
class TestL1ProtocolHasTriggerFields(unittest.TestCase):
    def test_protocol_default_trigger_tier_empty(self):
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(id='p1', rule='Do not X')
        self.assertEqual(p.trigger_tier, [],
            'default trigger_tier 空 = 全场景 always inject (向后兼容)')
        self.assertEqual(p.trigger_sir_state, [],
            'default trigger_sir_state 空 = 全场景')


# ==========================================================================
# L2-L6: matches_context 逻辑
# ==========================================================================
class TestL2EmptyTriggerMatchesAll(unittest.TestCase):
    def test_empty_trigger_matches_any_context(self):
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(id='p1', rule='Do not X')
        self.assertTrue(p.matches_context('CHAT', 'active'))
        self.assertTrue(p.matches_context('STANDARD', 'sleep'))
        self.assertTrue(p.matches_context('', ''))
        self.assertTrue(p.matches_context('any_tier', 'any_state'))


class TestL3TierMatch(unittest.TestCase):
    def test_tier_in_trigger_matches(self):
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(
            id='p1', rule='Do not X',
            trigger_tier=['CHAT', 'STANDARD'],
        )
        self.assertTrue(p.matches_context('CHAT', ''))
        self.assertTrue(p.matches_context('STANDARD', ''))


class TestL4TierNoMatch(unittest.TestCase):
    def test_tier_not_in_trigger_no_match(self):
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(
            id='p1', rule='Do not X',
            trigger_tier=['CHAT'],
        )
        self.assertFalse(p.matches_context('STANDARD', ''),
            'tier=STANDARD 不在 trigger_tier=[CHAT] → 不 match')
        self.assertFalse(p.matches_context('', ''),
            '空 tier 不能 match 非空 trigger_tier')


class TestL5SirStateMatch(unittest.TestCase):
    def test_sir_state_in_trigger_matches(self):
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(
            id='p1', rule='Do not X',
            trigger_sir_state=['active', 'afk_short'],
        )
        self.assertTrue(p.matches_context('', 'active'))
        self.assertTrue(p.matches_context('', 'afk_short'))


class TestL6BothTriggerAndRelation(unittest.TestCase):
    def test_both_trigger_must_match(self):
        """AND 关系: 两个 trigger 都 match 才 inject (防意外触发)."""
        from jarvis_relational import UnspokenProtocol
        p = UnspokenProtocol(
            id='p1', rule='Do not X',
            trigger_tier=['CHAT'],
            trigger_sir_state=['active'],
        )
        # 两个都 match → True
        self.assertTrue(p.matches_context('CHAT', 'active'))
        # tier match 但 state 不 match → False
        self.assertFalse(p.matches_context('CHAT', 'sleep'))
        # state match 但 tier 不 match → False
        self.assertFalse(p.matches_context('STANDARD', 'active'))
        # 两个都不 match → False
        self.assertFalse(p.matches_context('STANDARD', 'sleep'))


# ==========================================================================
# L7-L9: to_prompt_block 用 filter
# ==========================================================================
class TestL7EmptyTriggerAlwaysInject(unittest.TestCase):
    def test_old_protocol_no_trigger_always_injects(self):
        """向后兼容: 老 protocol (空 trigger) 任意 context 都 inject."""
        from jarvis_relational import RelationalStateStore, UnspokenProtocol
        tmp = tempfile.mktemp(suffix='.json')
        rs = RelationalStateStore(persist_path=tmp)
        rs.add_protocol(UnspokenProtocol(id='p_old',
                                              rule='Do not interrupt'))
        # 全场景都 inject
        block = rs.to_prompt_block(current_tier='CHAT', current_sir_state='active')
        self.assertIn('Do not interrupt', block)
        block = rs.to_prompt_block(current_tier='STANDARD', current_sir_state='sleep')
        self.assertIn('Do not interrupt', block,
            '老 protocol (空 trigger) 在 sleep tier=STANDARD 也应 inject')
        # 不传 context (老 caller 行为) 也应 inject
        block = rs.to_prompt_block()
        self.assertIn('Do not interrupt', block)


class TestL8FilteredInjectWhenMatch(unittest.TestCase):
    def test_protocol_with_trigger_injects_on_match(self):
        from jarvis_relational import RelationalStateStore, UnspokenProtocol
        tmp = tempfile.mktemp(suffix='.json')
        rs = RelationalStateStore(persist_path=tmp)
        rs.add_protocol(UnspokenProtocol(
            id='p_chat_only',
            rule='Do not lecture when chatting',
            trigger_tier=['CHAT'],
        ))
        block = rs.to_prompt_block(current_tier='CHAT', current_sir_state='active')
        self.assertIn('Do not lecture', block)


class TestL9FilteredOutWhenNoMatch(unittest.TestCase):
    def test_protocol_with_trigger_filtered_when_no_match(self):
        from jarvis_relational import RelationalStateStore, UnspokenProtocol
        tmp = tempfile.mktemp(suffix='.json')
        rs = RelationalStateStore(persist_path=tmp)
        rs.add_protocol(UnspokenProtocol(
            id='p_chat_only',
            rule='Do not lecture when chatting',
            trigger_tier=['CHAT'],
        ))
        block = rs.to_prompt_block(current_tier='STANDARD',
                                       current_sir_state='active')
        self.assertNotIn('Do not lecture', block,
            'STANDARD tier 不在 trigger_tier=[CHAT] → protocol 不 inject')


# ==========================================================================
# L10: load_persist 兼容老 JSON
# ==========================================================================
class TestL10LoadPersistCompat(unittest.TestCase):
    def test_old_json_without_trigger_fields_loads_with_empty(self):
        """老 relational_state.json 没 trigger 字段 → 默认空 list."""
        from jarvis_relational import RelationalStateStore
        tmp = tempfile.mktemp(suffix='.json')
        # 模拟老 JSON (没 trigger_tier / trigger_sir_state 字段)
        old_json = {
            'inside_jokes': {},
            'unspoken_protocols': {
                'p_legacy': {
                    'id': 'p_legacy',
                    'rule': 'Old protocol from before C.2',
                    'state': 'active',
                    # 没 trigger_tier / trigger_sir_state
                }
            },
            'unfinished_business': {},
            'shared_history_threads': {},
        }
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(old_json, f)
        rs = RelationalStateStore(persist_path=tmp)
        result = rs.load()
        self.assertEqual(result['protocols'], 1)
        p = rs.get_protocol('p_legacy')
        self.assertIsNotNone(p)
        self.assertEqual(p.trigger_tier, [],
            '老 JSON 缺 trigger_tier → 默认空 list')
        self.assertEqual(p.trigger_sir_state, [],
            '老 JSON 缺 trigger_sir_state → 默认空 list')


# ==========================================================================
# L11: _build_layer_2_relational_block 接 prompt_tier + 拿 sir_state
# ==========================================================================
class TestL11CentralNerveBuildBlock(unittest.TestCase):
    def test_build_layer_2_passes_prompt_tier_and_sir_state(self):
        """_build_layer_2_relational_block(prompt_tier='CHAT') 调 to_prompt_block
        传 current_tier='CHAT' + current_sir_state from inner_thought_daemon."""
        # 用 mock central_nerve (不启动真 nerve)
        from jarvis_central_nerve import CentralNerve
        nerve = MagicMock(spec=CentralNerve)
        nerve._soul_concern_inject_reason = 'silent'

        # mock relational_state.to_prompt_block — record kwargs
        nerve.relational_state = MagicMock()
        nerve.relational_state.to_prompt_block = MagicMock(return_value='[block]')

        # mock inner_thought_daemon._classify_sir_state -> 'afk_short'
        nerve.inner_thought_daemon = MagicMock()
        nerve.inner_thought_daemon._classify_sir_state = MagicMock(
            return_value='afk_short'
        )

        # 调真 method (unbound) 传 mock self
        result = CentralNerve._build_layer_2_relational_block(
            nerve, prompt_tier='CHAT'
        )
        self.assertEqual(result, '[block]')
        # 验证 to_prompt_block 真被传了正确参数
        call_kwargs = nerve.relational_state.to_prompt_block.call_args.kwargs
        self.assertEqual(call_kwargs.get('current_tier'), 'CHAT',
            'to_prompt_block 必须收 current_tier=CHAT')
        self.assertEqual(call_kwargs.get('current_sir_state'), 'afk_short',
            'to_prompt_block 必须收 current_sir_state from daemon')


# ==========================================================================
# L12: 端到端 — protocol 限 CHAT, central_nerve STANDARD → filter
# ==========================================================================
class TestL12EndToEndFilter(unittest.TestCase):
    def test_end_to_end_protocol_chat_only_not_in_standard(self):
        """完整路径: propose protocol with trigger_tier=['CHAT'],
        central_nerve assemble prompt_tier='STANDARD' → block 不含 protocol."""
        from jarvis_relational import RelationalStateStore, UnspokenProtocol
        from jarvis_central_nerve import CentralNerve
        tmp = tempfile.mktemp(suffix='.json')
        rs = RelationalStateStore(persist_path=tmp)
        rs.add_protocol(UnspokenProtocol(
            id='p_chat',
            rule='Be casual when chatting',
            trigger_tier=['CHAT'],
        ))

        # 完整 path: _build_layer_2 → to_prompt_block(current_tier='STANDARD')
        nerve = MagicMock(spec=CentralNerve)
        nerve._soul_concern_inject_reason = 'silent'
        nerve.relational_state = rs
        nerve.inner_thought_daemon = MagicMock()
        nerve.inner_thought_daemon._classify_sir_state = MagicMock(
            return_value='active'
        )

        block_chat = CentralNerve._build_layer_2_relational_block(
            nerve, prompt_tier='CHAT'
        )
        self.assertIn('Be casual', block_chat,
            'CHAT tier 应 inject protocol')

        block_standard = CentralNerve._build_layer_2_relational_block(
            nerve, prompt_tier='STANDARD'
        )
        self.assertNotIn('Be casual', block_standard,
            'STANDARD tier 不在 trigger_tier=[CHAT] → 不应 inject protocol')


if __name__ == '__main__':
    unittest.main()
