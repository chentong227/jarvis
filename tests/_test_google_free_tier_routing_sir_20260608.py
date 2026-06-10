# -*- coding: utf-8 -*-
"""[Sir 2026-06-08] 弃付费 key + 两免费 key 轮流 + 3-flash 转 OpenRouter 单测.

覆盖:
  ① keys.py: GOOGLE_KEY_3 可选, GOOGLE_LIST 过滤空/占位符 (2 个免费 key)
  ② KeyRouter: 两 key 都 free tier, get_google_key('paid') fallback 全池轮流
  ③ google_model_routing: seed + force_openrouter/google_only 语义
  ④ safe_gemini_call 路由: 3-flash → force_openrouter; flash-lite → google_only
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestKeysLoaderTwoFreeKeys(unittest.TestCase):
    def test_google_key_3_optional_filtered(self):
        # GOOGLE_KEY_3 缺失 → GOOGLE_LIST 只有 2 个
        import jarvis_config.keys as K
        env = {
            'OPENROUTER_MAIN': 'sk-or-main', 'OPENROUTER_2': 'sk-or-2',
            'OPENROUTER_3': 'sk-or-3', 'GEMINI_KEY': 'g_free_1',
            'GOOGLE_KEY_2': 'g_free_2',
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(K, '_load_dotenv_if_present', lambda: None):
                keys = K.load_keys()
        self.assertEqual(len(keys.GOOGLE_LIST), 2)
        self.assertEqual(keys.GOOGLE_LIST, ['g_free_1', 'g_free_2'])

    def test_google_key_3_placeholder_filtered(self):
        import jarvis_config.keys as K
        env = {
            'OPENROUTER_MAIN': 'sk-or-main', 'OPENROUTER_2': 'sk-or-2',
            'OPENROUTER_3': 'sk-or-3', 'GEMINI_KEY': 'g_free_1',
            'GOOGLE_KEY_2': 'g_free_2', 'GOOGLE_KEY_3': 'REPLACE_ME_OPTIONAL',
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(K, '_load_dotenv_if_present', lambda: None):
                keys = K.load_keys()
        self.assertEqual(len(keys.GOOGLE_LIST), 2)


class TestKeyRouterBothFree(unittest.TestCase):
    def _make_router(self):
        from jarvis_key_router import KeyRouter
        # 避免载入 disk permanent-death state 干扰
        with patch.object(KeyRouter, '_load_permanent_death_state', lambda self: None):
            kr = KeyRouter('main_k', ['gk1', 'gk2'], ['ok1', 'ok2'])
        return kr

    def test_both_keys_free_tier(self):
        kr = self._make_router()
        tiers = [e['tier'] for e in kr._google_pool]
        self.assertEqual(tiers, ['free', 'free'])

    def test_paid_filter_fallback_to_full_pool(self):
        # tier_filter='paid' 无 paid key → fallback 全池, 不 raise
        kr = self._make_router()
        seen = set()
        for _ in range(30):
            key, name = kr.get_google_key('test', tier_filter='paid')
            seen.add(name)
            kr.release(name)
        self.assertEqual(seen, {'google_1', 'google_2'})


class TestGoogleModelRouting(unittest.TestCase):
    def setUp(self):
        import jarvis_utils as JU
        self.JU = JU
        JU._google_routing_cache['data'] = None
        JU._google_routing_cache['mtime'] = 0.0

    def test_seed_fallback_when_missing(self):
        # 指向不存在路径 → seed
        with patch('os.path.getmtime', side_effect=OSError):
            r = self.JU._load_google_model_routing()
        self.assertIn('gemini-3-flash-preview', r['force_openrouter'])
        self.assertIn('gemini-3.1-flash-lite', r['google_only_no_fallback'])

    def test_loads_real_config(self):
        r = self.JU._load_google_model_routing()
        self.assertIn('force_openrouter', r)
        self.assertIn('google_only_no_fallback', r)


class TestSafeGeminiCallRouting(unittest.TestCase):
    """路由决策: force_openrouter 只走 OR; google_only 只走 Google 不 fallback。"""

    def setUp(self):
        import jarvis_utils as JU
        self.JU = JU
        JU._google_routing_cache['data'] = None
        JU._google_routing_cache['mtime'] = 0.0

    def _fake_router(self):
        kr = MagicMock()
        kr.CALLER_MAIN_BRAIN = 'main_brain'
        return kr

    def test_force_openrouter_model_skips_google(self):
        # gemini-3-flash-preview → 只走 OpenRouter, get_google_key 不被调
        routing = {'force_openrouter': ['gemini-3-flash-preview'],
                   'google_only_no_fallback': []}
        with patch.object(self.JU, '_load_google_model_routing', lambda: routing):
            kr = self._fake_router()
            or_client = MagicMock()
            with patch('jarvis_utils.get_rate_limiter', return_value=MagicMock()):
                kr.get_openrouter_key.return_value = ('ok1', 'openrouter_1')
                with patch('openai.OpenAI') as MockOAI:
                    inst = MockOAI.return_value
                    inst.chat.completions.create.return_value = MagicMock(
                        choices=[MagicMock(message=MagicMock(content='hi'))])
                    res, name, _ = self.JU.safe_gemini_call(
                        kr, 'gatekeeper', 'flash', lambda c: None,
                        model_name='gemini-3-flash-preview',
                        contents_text='x', max_retries=1)
        self.assertEqual(res.text, 'hi')
        kr.get_google_key.assert_not_called()

    def test_google_only_model_skips_openrouter(self):
        # gemini-3.1-flash-lite → 只走 Google, get_openrouter_key 不被调
        routing = {'force_openrouter': [],
                   'google_only_no_fallback': ['gemini-3.1-flash-lite']}
        with patch.object(self.JU, '_load_google_model_routing', lambda: routing):
            kr = self._fake_router()
            kr.get_google_key.return_value = ('gk1', 'google_1')
            with patch('jarvis_utils.get_rate_limiter', return_value=MagicMock()):
                with patch('jarvis_utils.create_genai_client') as mock_client:
                    mock_client.return_value = MagicMock()
                    res, name, _ = self.JU.safe_gemini_call(
                        kr, 'sentinel', 'flash_lite',
                        lambda c: MagicMock(text='lite-ok'),
                        model_name='gemini-3.1-flash-lite',
                        contents_text='x', max_retries=1,
                        google_tier_filter='paid')
        self.assertEqual(res.text, 'lite-ok')
        kr.get_openrouter_key.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
