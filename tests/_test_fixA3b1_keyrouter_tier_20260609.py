# -*- coding: utf-8 -*-
"""[fixA3b1-keyrouter-tier / Sir 2026-06-09] key_router google pool 全 free + paid fallback.

弃付费 key 后只留两个免费 key (GEMINI_KEY + GOOGLE_KEY_2), 都标 tier='free'.
tier_filter='paid' 无 paid key 时 fallback 全池 (不 raise). 与 keyleak 并发槽
(_acquire_times/reaper) 语义正交, 无回归.

T1 google pool 全标 free.
T2 tier_filter='paid' 无 paid → fallback 全池 (能取到 key, 不 raise).
T3 tier_filter='free' / 'any' 正常取 key.
T4 keyleak 槽逻辑无回归: acquire/release 正常, _acquire_times 仍工作, _reap_stale_slots 在.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_router():
    from jarvis_key_router import KeyRouter
    return KeyRouter(
        main_brain_key='or-main',
        google_keys=['g-free-1', 'g-free-2'],
        openrouter_keys=['or-1', 'or-2'],
    )


class TestFixA3b1KeyrouterTier(unittest.TestCase):

    def test_t1_all_google_tier_free(self):
        kr = _make_router()
        tiers = [e.get('tier') for e in kr._google_pool]
        self.assertEqual(tiers, ['free', 'free'], "两个 google key 都应标 free")

    def test_t2_paid_filter_fallback_whole_pool(self):
        kr = _make_router()
        # tier_filter='paid' 无 paid key → fallback 全池, 能取到 key 不 raise
        key, name = kr.get_google_key(caller='test_paid', tier_filter='paid')
        self.assertIsNotNone(key, "无 paid key 应 fallback 全池取到")
        self.assertIn(name, ('google_1', 'google_2'))

    def test_t3_free_and_any_filter(self):
        kr = _make_router()
        k1, n1 = kr.get_google_key(caller='t', tier_filter='free')
        self.assertIsNotNone(k1)
        k2, n2 = kr.get_google_key(caller='t', tier_filter='any')
        self.assertIsNotNone(k2)

    def test_t4_keyleak_slots_intact(self):
        kr = _make_router()
        # keyleak 槽逻辑: acquire/release + _acquire_times + reaper 仍在 (无回归)
        self.assertTrue(hasattr(kr, '_acquire_times'))
        self.assertTrue(hasattr(kr, '_reap_stale_slots'))
        # openrouter acquire/release 正常
        okey, label = kr.get_openrouter_key(caller='test')
        self.assertIsNotNone(okey)
        rk = kr._resolve_key(label)
        self.assertGreaterEqual(kr._active_calls.get(rk, 0), 1)
        kr.release(label)
        self.assertEqual(kr._active_calls.get(rk, 0), 0)
        # reaper 可调 (无 stale → 回收 0)
        reaped = kr._reap_stale_slots(stale_after_s=120.0)
        self.assertEqual(reaped, 0)


if __name__ == '__main__':
    unittest.main()
