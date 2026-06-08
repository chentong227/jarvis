# -*- coding: utf-8 -*-
"""[keyleak-fix / Sir 2026-06-08] OpenRouter 并发槽泄漏修 + KeyRouter stale-slot reaper.

真机 BUG: openrouter_1/2 active_calls 顶到 10/10 (key 全 healthy) → 副池满 →
Gatekeeper/IntentResolver/ScreenVision 全 "无可用Key"。根因: caller get_openrouter_key
(active_calls += 1) 但 return 路径漏 release。

修两层:
  1. 每轮 caller (intent_resolver / reply_preflight) 加 try/finally release (单测在各自模块测)
  2. KeyRouter._reap_stale_slots — 系统级 backstop, 回收持有 > 120s 的 stale 槽

本测覆盖 reaper:
  T1 正常 acquire+release → active_calls 归 0, 无 stale 回收
  T2 漏 release (模拟 leak) → 槽位累积; reaper (stale_after 极小) 回收 → active_calls 归 0
  T3 fresh acquire 不被误回收 (持有 < stale_after)
  T4 reaper 返回回收数准确
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_router():
    from jarvis_key_router import KeyRouter
    with patch.object(KeyRouter, '_load_permanent_death_state', lambda self: None):
        return KeyRouter('main_k', ['gk1', 'gk2'], ['ok1', 'ok2'])


class TestKeyleakReaper(unittest.TestCase):
    def test_t1_normal_acquire_release_no_stale(self):
        kr = _make_router()
        key, name = kr.get_openrouter_key('test')
        self.assertIsNotNone(key)
        kr.release(name)
        # 全部 release → active_calls 0
        k = kr._resolve_key(name)
        self.assertEqual(kr._active_calls[k], 0)
        reaped = kr._reap_stale_slots(stale_after_s=0.0)
        self.assertEqual(reaped, 0, "无未释放槽 → reaper 不回收")

    def test_t2_leaked_slots_reaped(self):
        kr = _make_router()
        # 模拟 leak: acquire 不 release, 顶满一个 key 的 10 槽
        ok_key = kr._openrouter_pool[0]['key']
        for _ in range(10):
            kr._try_acquire(ok_key)
        self.assertEqual(kr._active_calls[ok_key], 10, "10 次 acquire 不 release → 顶满")
        # 此时 get 该 key 应失败 (满) — 但池里还有 ok2
        # reaper stale_after=0 → 全部判 stale 回收
        reaped = kr._reap_stale_slots(stale_after_s=0.0)
        self.assertEqual(reaped, 10)
        self.assertEqual(kr._active_calls[ok_key], 0, "reaper 回收后槽位归 0")

    def test_t3_fresh_not_reaped(self):
        kr = _make_router()
        ok_key = kr._openrouter_pool[0]['key']
        kr._try_acquire(ok_key)
        # 大 stale_after → fresh 槽不回收
        reaped = kr._reap_stale_slots(stale_after_s=120.0)
        self.assertEqual(reaped, 0, "fresh 槽 (持有 < 120s) 不被误回收")
        self.assertEqual(kr._active_calls[ok_key], 1)

    def test_t4_partial_reap(self):
        kr = _make_router()
        ok_key = kr._openrouter_pool[0]['key']
        # 2 个老 acquire
        kr._try_acquire(ok_key)
        kr._try_acquire(ok_key)
        time.sleep(0.05)
        # 注入 1 个 fresh (改最后一个时间戳为现在)
        kr._try_acquire(ok_key)
        # stale_after 卡在中间: 前 2 个老的回收, 第 3 个 fresh 留
        reaped = kr._reap_stale_slots(stale_after_s=0.03)
        self.assertEqual(reaped, 2, f"应回收 2 个老槽, got {reaped}")
        self.assertEqual(kr._active_calls[ok_key], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
