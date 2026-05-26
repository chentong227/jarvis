# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 12:13 真痛] InnerThought cooldown 30min → 5min 修.

Sir 原话:
  "💭 [InnerThought] all 5 categories in cooldown (skip count 6), next free in 11min
  — daemon alive, awaiting free slot. 这个机制是不是有问题？我怎么记得我们是有一个
  只要我在活动就持续 1 分钟 1 次的思考呢？"

根因数学:
  - 现 30min cooldown × 5 cat → 前 5 tick (5 min) 每 60s 出 thought, 第 6 tick
    起 25 min silence, 直到 cat A 30 min cooldown 完毕.
  - 平均生成率 = 5 thought / 30 min = 1 thought / 6min ❌
  - 违 Sir 真意 "active = 1 thought / 60s 持续输出"

修:
  - SAME_CATEGORY_COOLDOWN_S = 1800 (30 min) → 300 (5 min)
  - 数学验证: tick 6 (t=300s) 时 cat A.last_ts=0, 300-0=300 ≥ 300 → cat A free,
    daemon 永不静默. 同 cat 仍隔 5min, 保 diversity 不连发完全重复.

测试覆盖 (4 个):
  L1 constant 真值 (SAME_CATEGORY_COOLDOWN_S == 300)
  L2 _compute_free_categories 数学验证: cat A.last_ts=0 + now=300 → A in free
  L3 6 tick 不全静默 (simulate 5 cat 跑一轮 + tick 6 必 free)
  L4 docstring 含 "5min" 不含 "30min" (注释一致)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    """临时 daemon (临时 PERSIST_PATH 隔离)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(),
                          f'cooldown_fix_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


# ==========================================================================
# L1: constant 真值
# ==========================================================================
class TestCooldownConstant(unittest.TestCase):
    def test_cooldown_is_300s_not_1800s(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        self.assertEqual(
            InnerThoughtDaemon.SAME_CATEGORY_COOLDOWN_S, 300,
            'Sir 真痛 fix: cooldown 必须是 5min (300s), 不是 30min (1800s). '
            '5 cat × 5min = 5min 一轮, 保 1 thought/min 持续输出.'
        )


# ==========================================================================
# L2: _compute_free_categories 数学 — t=300 时 cat A.last_ts=0 → free
# ==========================================================================
class TestFreeCategoriesMath(unittest.TestCase):
    def test_cat_free_after_300s(self):
        """cat A.last_ts=0 (启动时) + now=300 → 300-0=300 >= 300 → A free."""
        d = _build_daemon()
        d._last_category_ts = {'A': 0.0, 'B': 0.0, 'C': 0.0, 'D': 0.0, 'E': 0.0}
        with patch('jarvis_inner_thought_daemon.time.time', return_value=300.0):
            free = d._compute_free_categories()
        self.assertEqual(set(free), {'A', 'B', 'C', 'D', 'E'},
            'cat last_ts=0 + 300s 后, 全 cat 应 free (last_ts=0 = 永远不在 cooldown)')


# ==========================================================================
# L3: 6 tick 不全静默 (5 cat 一轮后 tick 6 必 free)
# ==========================================================================
class TestDoesNotSilenceAfter5Ticks(unittest.TestCase):
    def test_tick_6_has_free_category(self):
        """模拟启动后 5 tick 各用一个 cat (60s 间隔), tick 6 (300s) 必有 free.

        关键: SAME_CATEGORY_COOLDOWN_S == active_interval × 5
        → 第 5+1 tick 时第一个 cat 已 cooldown 完毕.
        """
        d = _build_daemon()
        # 模拟 5 tick 各用一个 cat (t=0, 60, 120, 180, 240)
        d._last_category_ts = {
            'A': 0.0, 'B': 60.0, 'C': 120.0, 'D': 180.0, 'E': 240.0,
        }
        # tick 6: t=300 (5 min)
        with patch('jarvis_inner_thought_daemon.time.time', return_value=300.0):
            free = d._compute_free_categories()
        self.assertIn('A', free,
            'tick 6 (t=300s) 时 cat A 必 free (300-0=300 ≥ 300)')
        self.assertGreater(len(free), 0,
            'tick 6 必有 free cat, daemon 永不静默 25min')

    def test_active_interval_x_cat_count_matches_cooldown(self):
        """工程不变式: SAME_CATEGORY_COOLDOWN_S == INTERVAL_ACTIVE_S × 5

        改 cooldown 或 active interval 时必须保证不变 (否则 daemon 又静默).
        """
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        self.assertEqual(
            InnerThoughtDaemon.SAME_CATEGORY_COOLDOWN_S,
            InnerThoughtDaemon.INTERVAL_ACTIVE_S * 5,
            'cooldown 必须 = active_interval × 5 (5 cat 一轮)'
        )


# ==========================================================================
# L4: docstring 注释一致 (含 "5min" 不含 "30min 同 category")
# ==========================================================================
class TestDocstringConsistency(unittest.TestCase):
    def test_module_docstring_mentions_5min_not_30min_cooldown(self):
        import jarvis_inner_thought_daemon as mod
        ds = mod.__doc__ or ''
        self.assertIn('5min', ds,
            'module docstring 应含 "5min" 注释 cooldown 新值')
        # 不该有 "30min 同 category" 这种老引用
        self.assertNotIn('同 category 30min', ds,
            'module docstring 不应保留 "同 category 30min" 老注释')


if __name__ == '__main__':
    unittest.main()
