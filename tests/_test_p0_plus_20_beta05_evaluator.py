# -*- coding: utf-8 -*-
"""[P0+20-β.0.5 / 2026-05-16] DirectiveEvaluator 单元 + 集成测试

覆盖：
- _parse_eval_response 7+ 场景（标准 JSON / 嵌入 JSON / partial / 非 JSON / 空）
- EvaluatorRateLimit 滑动窗口 60s
- evaluate_async 空输入 / 空 reply / registry/key_router 缺失时静默跳过
- mock LLM 响应后 evaluator.record_helped 被正确写回 registry
- shutdown 不抛异常

规范：详 docs/PROMPT_REFACTOR_PLAN.md §7
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directive_evaluator import (
    DirectiveEvaluator,
    _parse_eval_response,
    EvalResult,
    EVALUATOR_CONFIG,
    EVALUATOR_PROMPT,
    get_default_evaluator,
    reset_default_evaluator_for_test,
)
from jarvis_directives import (
    DirectiveRegistry,
    bootstrap_default_registry,
)


# ============================================================
# A. _parse_eval_response
# ============================================================
class TestParseEvalResponse(unittest.TestCase):

    def test_standard_yes_json(self):
        v, r = _parse_eval_response('{"is_followed":"yes","reason":"appended ZH"}')
        self.assertEqual(v, 'yes')
        self.assertEqual(r, 'appended ZH')

    def test_standard_no_json(self):
        v, r = _parse_eval_response('{"is_followed":"no","reason":"missed ZH"}')
        self.assertEqual(v, 'no')
        self.assertIn('missed', r)

    def test_partial_json(self):
        v, r = _parse_eval_response('{"is_followed":"partial","reason":"only EN"}')
        self.assertEqual(v, 'partial')

    def test_embedded_json_in_text(self):
        v, r = _parse_eval_response('LLM said {"is_followed":"yes","reason":"ok"} thanks')
        self.assertEqual(v, 'yes')

    def test_invalid_value_falls_to_unknown(self):
        v, r = _parse_eval_response('{"is_followed":"maybe","reason":"unclear"}')
        self.assertEqual(v, 'unknown')

    def test_empty_string(self):
        v, r = _parse_eval_response('')
        self.assertEqual(v, 'unknown')

    def test_non_json_string(self):
        v, r = _parse_eval_response('something completely random')
        self.assertEqual(v, 'unknown')


# ============================================================
# B. evaluate_async early-skip 行为
# ============================================================
class TestEvaluateAsyncEarlySkip(unittest.TestCase):

    def setUp(self):
        reset_default_evaluator_for_test()
        self.ev = DirectiveEvaluator(key_router=None, registry=None)

    def tearDown(self):
        self.ev.shutdown(wait=False)

    def test_empty_directive_ids_skip(self):
        self.ev.evaluate_async([], 'user', 'reply')
        self.assertEqual(self.ev.stats['submitted'], 0)

    def test_empty_reply_skip(self):
        self.ev.evaluate_async(['some_id'], 'user input', '')
        self.assertEqual(self.ev.stats['submitted'], 0)

    def test_short_reply_skip(self):
        self.ev.evaluate_async(['some_id'], 'user input', '   ')
        self.assertEqual(self.ev.stats['submitted'], 0)

    def test_empty_user_input_skip(self):
        self.ev.evaluate_async(['some_id'], '', 'a long valid reply text')
        self.assertEqual(self.ev.stats['submitted'], 0)

    def test_no_registry_no_keyrouter_skip(self):
        self.ev.evaluate_async(['some_id'], 'user', 'a valid reply')
        self.assertEqual(self.ev.stats['submitted'], 0)


# ============================================================
# C. Rate limit
# ============================================================
class TestRateLimit(unittest.TestCase):

    def setUp(self):
        self.ev = DirectiveEvaluator()
        self.ev._rate_limit_per_minute = 3

    def tearDown(self):
        self.ev.shutdown(wait=False)

    def test_rate_limit_allows_first_n(self):
        for _ in range(3):
            self.assertTrue(self.ev._check_rate_limit())

    def test_rate_limit_blocks_after_threshold(self):
        for _ in range(3):
            self.ev._check_rate_limit()
        self.assertFalse(self.ev._check_rate_limit())


# ============================================================
# D. Mock LLM 评分回写 registry
# ============================================================
class TestEvaluateAsyncWritesBack(unittest.TestCase):

    def setUp(self):
        self.reg = DirectiveRegistry(persist_path=os.path.join('memory_pool', '_test_ev_writeback.json'))
        bootstrap_default_registry(self.reg)

        self.kr = MagicMock()
        self.kr.get_openrouter_key.return_value = ('fake_key', 'openrouter_1')
        self.kr.release.return_value = None

        self.ev = DirectiveEvaluator(key_router=self.kr, registry=self.reg, pool_size=2)

    def tearDown(self):
        self.ev.shutdown(wait=True)
        try:
            os.remove(os.path.join('memory_pool', '_test_ev_writeback.json'))
        except Exception:
            pass

    def test_yes_response_writes_helped(self):
        directive_id = 'bilingual_directive'
        d_before = self.reg.directives[directive_id]
        helped_before = d_before.helped

        mocked = '{"is_followed":"yes","reason":"appended ZH at end"}'
        with patch('jarvis_directive_evaluator.safe_openrouter_call', return_value=mocked):
            self.ev.evaluate_async(
                fired_directive_ids=[directive_id],
                user_input='set volume to 30%',
                jarvis_reply='Done, Sir. ---ZH--- 已调音量。',
            )
            self.ev._pool.shutdown(wait=True)
            self.ev._pool = self.ev._pool.__class__(max_workers=2)

        self.assertEqual(self.reg.directives[directive_id].helped, helped_before + 1)
        self.assertGreaterEqual(self.ev.stats['helped_count'], 1)

    def test_no_response_does_not_write_helped(self):
        directive_id = 'tool_honesty_directive'
        d_before = self.reg.directives[directive_id]
        helped_before = d_before.helped

        mocked = '{"is_followed":"no","reason":"claimed Done falsely"}'
        with patch('jarvis_directive_evaluator.safe_openrouter_call', return_value=mocked):
            self.ev.evaluate_async(
                fired_directive_ids=[directive_id],
                user_input='did the call go through?',
                jarvis_reply='Done, Sir.',
            )
            self.ev._pool.shutdown(wait=True)
            self.ev._pool = self.ev._pool.__class__(max_workers=2)

        self.assertEqual(self.reg.directives[directive_id].helped, helped_before)
        self.assertGreaterEqual(self.ev.stats['not_helped_count'], 1)

    def test_exception_in_openrouter_call_does_not_break(self):
        directive_id = 'bilingual_directive'
        with patch('jarvis_directive_evaluator.safe_openrouter_call',
                   side_effect=RuntimeError('fake network')):
            self.ev.evaluate_async(
                fired_directive_ids=[directive_id],
                user_input='test input',
                jarvis_reply='test reply with enough length',
            )
            self.ev._pool.shutdown(wait=True)
            self.ev._pool = self.ev._pool.__class__(max_workers=2)

        self.assertGreaterEqual(self.ev.stats['failed'], 1)


# ============================================================
# E. 单例
# ============================================================
class TestSingleton(unittest.TestCase):

    def setUp(self):
        reset_default_evaluator_for_test()

    def tearDown(self):
        reset_default_evaluator_for_test()

    def test_singleton_same_instance(self):
        e1 = get_default_evaluator()
        e2 = get_default_evaluator()
        self.assertIs(e1, e2)

    def test_reset_creates_new_instance(self):
        e1 = get_default_evaluator()
        reset_default_evaluator_for_test()
        e2 = get_default_evaluator()
        self.assertIsNot(e1, e2)


# ============================================================
# F. 配置 + prompt 模板
# ============================================================
class TestConfigAndPrompt(unittest.TestCase):

    def test_config_has_primary_and_fallback(self):
        self.assertIn('primary_model', EVALUATOR_CONFIG)
        self.assertIn('fallback_model', EVALUATOR_CONFIG)
        self.assertTrue(EVALUATOR_CONFIG['primary_model'].startswith('google/gemini'))

    def test_prompt_has_placeholders(self):
        for ph in ('{directive_text}', '{user_input}', '{jarvis_reply}'):
            self.assertIn(ph, EVALUATOR_PROMPT)

    def test_prompt_asks_for_json(self):
        self.assertIn('JSON', EVALUATOR_PROMPT)
        self.assertIn('is_followed', EVALUATOR_PROMPT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
