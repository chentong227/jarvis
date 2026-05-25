# -*- coding: utf-8 -*-
"""[P2 / Sir 2026-05-25 21:47 真测追根] KeyRouter Priority + OpenRouter Fallback + 限速.

Sir 真痛点 (jarvis_20260525_*.log + Sir 21:42 哲学讨论 inner_thought roadmap):
  - google_1 SSL EOF (Sir 代理流量超), 切 key 但 stream 已终止
  - OpenRouter pool 4 key 闲置 (老 get_key allow_openrouter_fallback 参数没真用)
  - 后台 daemon 失控 → 主对话 TTFT 上升

P2 治本 6 layer (准则 6 三维耦合 + 准则 8 优雅高效):
  1. PRIORITY_HIGH / MEDIUM / LOW 三档 + caller 默认映射
  2. get_key() 加 priority 参数 (main_brain auto HIGH 锁死, 不破老 caller)
  3. get_key() 真启用 OpenRouter fallback (google 全挂 → 走 OpenRouter pool)
  4. _TokenBucket 30/min LOW 限速 (防 inner_thought / L7 reflector 失控)
  5. report_error 网络层 OpenRouter 也 spawn auto_recover (老仅 google)
  6. get_openrouter_key 也加 priority 限速 (后台 reflector 主路径)

未来 P1 inner_thought daemon 真上路时, 这是 Sir 数字生命可行性的工程保护层.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_router():
    """无环境依赖创建 KeyRouter 实例 (不真调 API)."""
    from jarvis_key_router import KeyRouter
    return KeyRouter(
        main_brain_key='fake_main_brain_sk-or-v1-AAA',
        google_keys=['fake_g_AIzaSy1', 'fake_g_AIzaSy2', 'fake_g_AIzaSy3'],
        openrouter_keys=['fake_or_sk-or-v1-2', 'fake_or_sk-or-v1-3',
                          'fake_or_sk-or-v1-4', 'fake_or_sk-or-v1-5'],
    )


# ==========================================================================
# Layer 1: PRIORITY 常量 + caller 映射
# ==========================================================================
class TestL1PriorityConstants(unittest.TestCase):

    def test_priority_constants_exist(self):
        from jarvis_key_router import KeyRouter
        self.assertEqual(KeyRouter.PRIORITY_HIGH, 'high')
        self.assertEqual(KeyRouter.PRIORITY_MEDIUM, 'medium')
        self.assertEqual(KeyRouter.PRIORITY_LOW, 'low')

    def test_high_priority_callers_complete(self):
        from jarvis_key_router import KeyRouter
        for c in ['main_brain', 'gatekeeper', 'reply_preflight']:
            self.assertIn(c, KeyRouter._PRIORITY_HIGH_CALLERS,
                f"'{c}' 应在 HIGH (turn-time critical)")

    def test_medium_priority_callers_complete(self):
        from jarvis_key_router import KeyRouter
        for c in ['sentinel', 'hippocampus', 'predicate_parser', 'soul_evaluator']:
            self.assertIn(c, KeyRouter._PRIORITY_MEDIUM_CALLERS,
                f"'{c}' 应在 MEDIUM (turn-time tolerable)")

    def test_default_priority_inference(self):
        router = _make_router()
        # HIGH
        self.assertEqual(router._default_priority('main_brain'), 'high')
        self.assertEqual(router._default_priority('gatekeeper'), 'high')
        self.assertEqual(router._default_priority('reply_preflight'), 'high')
        # MEDIUM
        self.assertEqual(router._default_priority('sentinel'), 'medium')
        self.assertEqual(router._default_priority('hippocampus'), 'medium')
        self.assertEqual(router._default_priority('soul_evaluator'), 'medium')
        # LOW (默认所有后台)
        self.assertEqual(router._default_priority('reflector'), 'low')
        self.assertEqual(router._default_priority('inner_thought'), 'low')
        self.assertEqual(router._default_priority('struggle_reflector'), 'low')
        self.assertEqual(router._default_priority('soul_reflector'), 'low')
        self.assertEqual(router._default_priority(''), 'low')


# ==========================================================================
# Layer 2: get_key() priority 参数 + main_brain auto HIGH
# ==========================================================================
class TestL2GetKeyPriorityParam(unittest.TestCase):

    def test_main_brain_locked_to_main_brain_key(self):
        router = _make_router()
        key, name, provider = router.get_key('main_brain')
        self.assertEqual(name, 'main_brain')
        self.assertEqual(provider, 'openrouter')
        self.assertTrue(key.startswith('fake_main_brain_'))
        router.release('main_brain')

    def test_get_key_default_priority_inferred(self):
        """老 caller 不传 priority → 自动按 caller 推断 (向后兼容)."""
        router = _make_router()
        # gatekeeper → 自动 HIGH → 不限速
        key, name, provider = router.get_key('gatekeeper')
        self.assertIsNotNone(key)
        router.release(name)

    def test_explicit_priority_overrides_default(self):
        """显式传 priority=HIGH 跳过限速 (即使 caller='inner_thought' 默认 LOW)."""
        from jarvis_key_router import KeyRouter
        router = _make_router()
        # inner_thought 默认 LOW, 显式 HIGH → 不进 bucket
        before = router._fallback_stats['low_priority_acquired']
        key, name, _ = router.get_key('inner_thought',
                                         priority=KeyRouter.PRIORITY_HIGH)
        self.assertIsNotNone(key)
        after = router._fallback_stats['low_priority_acquired']
        self.assertEqual(after, before, '显式 HIGH 不应消耗 LOW bucket')
        router.release(name)


# ==========================================================================
# Layer 3: 真 OpenRouter fallback (google 全挂 → OpenRouter)
# ==========================================================================
class TestL3GoogleToOpenRouterFallback(unittest.TestCase):

    def test_google_all_unhealthy_falls_back_to_openrouter(self):
        router = _make_router()
        # 标 google 全 unhealthy
        for entry in router._google_pool:
            router._key_status[entry['key']]['healthy'] = False
        before = router._fallback_stats['google_to_openrouter']
        key, name, provider = router.get_key('sentinel')
        self.assertEqual(provider, 'openrouter',
            f'google 全挂应 fallback OpenRouter, 实际 provider={provider}')
        self.assertTrue(name.startswith('openrouter_'))
        after = router._fallback_stats['google_to_openrouter']
        self.assertEqual(after, before + 1,
            'fallback 计数应 +1')
        router.release(name)

    def test_allow_openrouter_fallback_false_raises(self):
        """显式 allow_openrouter_fallback=False → google 全挂直接 raise."""
        router = _make_router()
        for entry in router._google_pool:
            router._key_status[entry['key']]['healthy'] = False
        with self.assertRaises(RuntimeError):
            router.get_key('sentinel', allow_openrouter_fallback=False)


# ==========================================================================
# Layer 4: LOW priority token bucket 限速
# ==========================================================================
class TestL4LowPriorityRateLimit(unittest.TestCase):

    def test_low_priority_acquires_token(self):
        from jarvis_key_router import KeyRouter
        router = _make_router()
        before = router._fallback_stats['low_priority_acquired']
        key, name, _ = router.get_key('inner_thought',
                                         priority=KeyRouter.PRIORITY_LOW)
        after = router._fallback_stats['low_priority_acquired']
        self.assertEqual(after, before + 1, 'LOW 调用应消耗 1 token')
        router.release(name)

    def test_low_priority_bucket_exhaustion_raises(self):
        """耗尽 token bucket → LOW 调用应 raise (短超时)."""
        from jarvis_key_router import KeyRouter
        router = _make_router()
        # 把 bucket 抽干 (capacity=30)
        router._low_priority_bucket.tokens = 0.0
        router._low_priority_bucket.last_refill = time.time()
        # 让 timeout 短一点 (test 加速)
        original_timeout = router._LOW_PRIORITY_WAIT_TIMEOUT_S
        try:
            # monkey patch 让等 0.3s 即返
            router._low_priority_bucket.refill_per_sec = 0.0  # 不补
            with self.assertRaises(RuntimeError) as ctx:
                # 强制 bypass wait timeout 用 patch
                old_acquire = router._low_priority_bucket.acquire
                router._low_priority_bucket.acquire = lambda **kw: False
                try:
                    router.get_key('inner_thought',
                                    priority=KeyRouter.PRIORITY_LOW)
                finally:
                    router._low_priority_bucket.acquire = old_acquire
            self.assertIn('LOW priority 限速命中', str(ctx.exception))
            self.assertGreaterEqual(
                router._fallback_stats['low_priority_rate_limited'], 1)
        finally:
            pass

    def test_high_priority_does_not_consume_bucket(self):
        from jarvis_key_router import KeyRouter
        router = _make_router()
        before = router._fallback_stats['low_priority_acquired']
        key, name, _ = router.get_key('gatekeeper',
                                         priority=KeyRouter.PRIORITY_HIGH)
        after = router._fallback_stats['low_priority_acquired']
        self.assertEqual(after, before, 'HIGH 不应消耗 LOW bucket')
        router.release(name)


# ==========================================================================
# Layer 5: report_error 网络层 OpenRouter 也 spawn auto_recover
# ==========================================================================
class TestL5OpenRouterAutoRecover(unittest.TestCase):

    def test_source_spawns_recover_for_both_pools(self):
        """源码必须 unconditional spawn _auto_recover (不再 google-only)."""
        with open(os.path.join(ROOT, 'jarvis_key_router.py'),
                   'r', encoding='utf-8') as f:
            src = f.read()
        # 网络层错误 — 已删 `if status['provider'] == self.PROVIDER_GOOGLE` 守门
        idx = src.find('is_network_error and not is_billing_error')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 1500]
        # auto_recover spawn 必须不带 provider filter
        self.assertIn('OpenRouter pool 也走 auto_recover', src,
                       'P2 必须 anchor: OpenRouter pool 也走 auto_recover')

    def test_unhealthy_mark_spawns_recover_for_both_pools(self):
        """标 unhealthy 路径也不再 google-only."""
        with open(os.path.join(ROOT, 'jarvis_key_router.py'),
                   'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find('永久死亡的 key 不 spawn _auto_recover')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 800]
        # 不再有 provider == PROVIDER_GOOGLE 守门
        self.assertNotIn("status['provider'] == self.PROVIDER_GOOGLE", block,
                          'unhealthy spawn 不再 google-only')


# ==========================================================================
# Layer 6: get_openrouter_key 也加 priority 限速
# ==========================================================================
class TestL6GetOpenRouterKeyPriority(unittest.TestCase):

    def test_low_priority_consumes_bucket(self):
        from jarvis_key_router import KeyRouter
        router = _make_router()
        before = router._fallback_stats['low_priority_acquired']
        key, name = router.get_openrouter_key('inner_thought',
                                                 priority=KeyRouter.PRIORITY_LOW)
        after = router._fallback_stats['low_priority_acquired']
        self.assertEqual(after, before + 1)
        router.release(name)

    def test_high_priority_skips_bucket(self):
        from jarvis_key_router import KeyRouter
        router = _make_router()
        before = router._fallback_stats['low_priority_acquired']
        key, name = router.get_openrouter_key('reply_preflight',
                                                 priority=KeyRouter.PRIORITY_HIGH)
        after = router._fallback_stats['low_priority_acquired']
        self.assertEqual(after, before)
        router.release(name)


# ==========================================================================
# get_stats 报告 P2 stats
# ==========================================================================
class TestStatsExposesP2Metrics(unittest.TestCase):

    def test_stats_contains_priority_stats(self):
        router = _make_router()
        stats = router.get_stats()
        self.assertIn('priority_stats', stats)
        self.assertIn('google_to_openrouter', stats['priority_stats'])
        self.assertIn('low_priority_rate_limited', stats['priority_stats'])
        self.assertIn('low_priority_acquired', stats['priority_stats'])

    def test_stats_contains_low_priority_bucket(self):
        router = _make_router()
        stats = router.get_stats()
        self.assertIn('low_priority_bucket', stats)
        bk = stats['low_priority_bucket']
        self.assertIn('tokens', bk)
        self.assertIn('capacity', bk)
        self.assertEqual(bk['capacity'], 30.0)


# ==========================================================================
# 向后兼容: 老 caller 不传 priority 仍工作
# ==========================================================================
class TestBackwardCompat(unittest.TestCase):

    def test_old_caller_no_priority_param_still_works(self):
        """老调用 get_key('sentinel', 'flash') 不带 priority 仍能拿到 key."""
        router = _make_router()
        key, name, provider = router.get_key('sentinel', 'flash')
        self.assertIsNotNone(key)
        self.assertEqual(provider, 'google')
        router.release(name)

    def test_old_get_openrouter_key_no_priority(self):
        router = _make_router()
        key, name = router.get_openrouter_key('soul_reflector')
        self.assertIsNotNone(key)
        router.release(name)


if __name__ == '__main__':
    unittest.main()
