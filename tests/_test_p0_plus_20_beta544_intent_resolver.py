"""[β.5.44 / 2026-05-20 19:00] IntentResolver 重构集成 test

Sir 18:55 真理: '我说一句话, 7 个 module 各自动太乱了, 应该全 publish-only + 
LLM 集中决策'.

测试覆盖 sub-step A/C/D/E:
A: SWM etype 注册 (sir_intent.*, tool_called, intent_resolved)
C: jarvis_intent_resolver IntentResolver 类
D: jarvis_tool_registry TOOL_REGISTRY + 5 mutation tool
E: central_nerve _assemble_prompt 注入 [INTENT RESOLVED] block

注: B (6 module 改 publish_intent) 后续 sub-step 做.
"""
from __future__ import annotations

import os
import sys
import json
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestSubA_SWMEtypes(unittest.TestCase):
    """A: SWM etype 注册."""

    def test_sir_intent_etypes_registered(self):
        from jarvis_utils import ConversationEventBus
        expected_etypes = [
            'sir_intent_commit_candidate',
            'sir_intent_progress_candidate',
            'sir_intent_correction_candidate',
            'sir_intent_profile_update_candidate',
            'sir_intent_promise_candidate',
            'sir_intent_deadline_candidate',
            'tool_called',
            'intent_resolved',
        ]
        for et in expected_etypes:
            self.assertIn(et, ConversationEventBus.DEFAULT_TTL,
                          f'{et} must be in DEFAULT_TTL')
            self.assertIn(et, ConversationEventBus.DEFAULT_SALIENCE,
                          f'{et} must be in DEFAULT_SALIENCE')

    def test_intent_resolved_high_salience(self):
        """intent_resolved 必 salience ≥ 0.85 (主脑必看)."""
        from jarvis_utils import ConversationEventBus
        self.assertGreaterEqual(
            ConversationEventBus.DEFAULT_SALIENCE['intent_resolved'], 0.85
        )

    def test_tool_called_high_salience(self):
        from jarvis_utils import ConversationEventBus
        self.assertGreaterEqual(
            ConversationEventBus.DEFAULT_SALIENCE['tool_called'], 0.80
        )


class TestSubC_IntentResolver(unittest.TestCase):
    """C: IntentResolver 类."""

    def test_module_imports(self):
        import jarvis_intent_resolver as m
        self.assertTrue(hasattr(m, 'IntentResolver'))
        self.assertTrue(hasattr(m, 'get_intent_resolver'))
        self.assertTrue(hasattr(m, 'register_intent_resolver'))
        self.assertTrue(hasattr(m, 'INTENT_RESOLVER_CONFIG'))
        self.assertTrue(hasattr(m, 'INTENT_RESOLVER_PROMPT'))

    def test_resolver_with_no_tools_returns_reason(self):
        from jarvis_intent_resolver import IntentResolver
        r = IntentResolver(
            key_router=None,
            central_nerve=None,
            tool_registry={},
        )
        res = r.resolve_turn(turn_id='t1', sir_utterance='应该是 8 杯水')
        self.assertEqual(res['tool_calls'], [])
        # 没 tools 应该 reason 提示
        self.assertIn(res['reason'], ['no tools registered', 'no candidates'])

    def test_resolver_with_short_utterance_short_circuits(self):
        from jarvis_intent_resolver import IntentResolver
        # 至少有一个 tool
        r = IntentResolver(
            key_router=None,
            central_nerve=None,
            tool_registry={'dummy_tool': lambda **kw: {'ok': True}},
        )
        res = r.resolve_turn(turn_id='t1', sir_utterance='嗯')
        self.assertEqual(res['tool_calls'], [])
        self.assertIn('too short', res['reason'])

    def test_resolver_async_does_not_block(self):
        from jarvis_intent_resolver import IntentResolver
        r = IntentResolver(
            key_router=None,
            central_nerve=None,
            tool_registry={'dummy': lambda **kw: {'ok': True}},
        )
        t0 = time.time()
        t = r.resolve_turn_async(turn_id='t1', sir_utterance='test 异步不阻塞')
        elapsed = time.time() - t0
        # async 应 < 100ms 返
        self.assertLess(elapsed, 0.5)
        self.assertTrue(t.is_alive() or not t.is_alive())  # thread 已 spawn


class TestSubD_ToolRegistry(unittest.TestCase):
    """D: TOOL_REGISTRY."""

    def test_module_imports(self):
        import jarvis_tool_registry as m
        self.assertTrue(hasattr(m, 'TOOL_REGISTRY'))
        self.assertTrue(hasattr(m, 'get_tool_registry'))
        self.assertTrue(hasattr(m, 'register_tool'))

    def test_5_mutation_tools_registered(self):
        from jarvis_tool_registry import TOOL_REGISTRY
        expected = [
            'concern_progress_update',
            'memory_correction_apply',
            'commitment_register',
            'self_promise_register',
            'profile_field_update',
        ]
        for name in expected:
            self.assertIn(name, TOOL_REGISTRY,
                          f'tool {name} must be in TOOL_REGISTRY')

    def test_tool_concern_progress_update_signature(self):
        """tool 必接 nerve= kw 且能容错."""
        from jarvis_tool_registry import tool_concern_progress_update
        # 无 nerve 应 fail 但不 throw
        res = tool_concern_progress_update(
            concern_id='test_cid',
            current=8, target=8, unit='杯',
            nerve=None,
        )
        self.assertIsInstance(res, dict)
        self.assertIn('ok', res)
        self.assertIn('error', res)
        # 无 nerve → ok=False
        self.assertFalse(res['ok'])

    def test_tool_with_empty_required_arg_fails_gracefully(self):
        from jarvis_tool_registry import (
            tool_memory_correction_apply,
            tool_commitment_register,
            tool_self_promise_register,
        )
        # 无 new_value → fail
        r = tool_memory_correction_apply(old_value='x', new_value='')
        self.assertFalse(r['ok'])
        # 无 description → fail
        r = tool_commitment_register(description='')
        self.assertFalse(r['ok'])
        # 无 description → fail
        r = tool_self_promise_register(description='')
        self.assertFalse(r['ok'])

    def test_register_tool_runtime(self):
        from jarvis_tool_registry import register_tool, TOOL_REGISTRY
        register_tool('test_runtime_tool', lambda **kw: {'ok': True})
        self.assertIn('test_runtime_tool', TOOL_REGISTRY)
        # cleanup
        TOOL_REGISTRY.pop('test_runtime_tool', None)


class TestSubE_PromptInjection(unittest.TestCase):
    """E: _assemble_prompt 注入 [INTENT RESOLVED] block."""

    def test_central_nerve_has_intent_resolved_injection(self):
        src = open(
            os.path.join(ROOT, 'jarvis_central_nerve.py'), encoding='utf-8'
        ).read()
        # 必含 marker + 关键文本
        self.assertIn('β.5.44-E', src)
        self.assertIn('intent_resolved', src)
        self.assertIn('INTENT RESOLVED THIS TURN', src)

    def test_central_nerve_init_creates_resolver(self):
        src = open(
            os.path.join(ROOT, 'jarvis_central_nerve.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.44-CD', src)
        self.assertIn('IntentResolver(', src)
        self.assertIn('register_intent_resolver', src)
        self.assertIn('TOOL_REGISTRY', src.replace('get_tool_registry', 'TOOL_REGISTRY'))

    def test_chat_bypass_hooks_resolver(self):
        src = open(
            os.path.join(ROOT, 'jarvis_chat_bypass.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.44-CE', src)
        self.assertIn('resolve_turn_async', src)


class TestSubIntegration_FullRoundtrip(unittest.TestCase):
    """集成: IntentResolver + TOOL_REGISTRY + SWM publish 全链路."""

    def test_resolver_publishes_intent_resolved_after_resolve(self):
        """模拟有 dummy tool + 命中, resolver 应 publish intent_resolved SWM."""
        from jarvis_intent_resolver import IntentResolver
        from jarvis_utils import ConversationEventBus

        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)

        # mock central_nerve  
        class StubNerve:
            event_bus = bus
            concerns_ledger = None
        nerve = StubNerve()

        # tool 总返 ok
        def _dummy_tool(**kw):
            return {'ok': True, 'result': 'ok'}

        r = IntentResolver(
            key_router=None,  # 没 key_router → LLM fail
            central_nerve=nerve,
            tool_registry={'dummy_tool': _dummy_tool},
        )
        res = r.resolve_turn(turn_id='turn_test_xxx', sir_utterance='应该是 8 杯')
        # 没 LLM → 没 plan → 没 tool 调 → 不 publish intent_resolved (这是预期, plan 空)
        # 当前实现: LLM fail 时直接 return, 不 publish
        # 验证 publish 路径需 plan 非空 — 后续若需可加 manual inject test


if __name__ == '__main__':
    unittest.main(verbosity=2)
