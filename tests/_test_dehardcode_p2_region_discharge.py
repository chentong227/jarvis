# -*- coding: utf-8 -*-
"""[thinking-dehardcode-P2 / Sir 2026-05-31 真机] 退类冷却 → 区放电.

Sir 真机真痛: 思考脑还在 tick=45s + A-E 槽 + cooldown skip (legacy 默认)。
工程 Phase 2 (设计 §3/§5.3, 最高风险, 镜像+真机验): emergent 模式拔掉 category
冷却 (SAME_CATEGORY_COOLDOWN 的两道 gate), diversity 改靠:
  (1) evidence-gate 体势能指纹 (同焦点区+同幅度桶 → 指纹稳 → idle skip)
  (2) value-backoff (连续低值降频)
  (3) REST (无真势能放下)
即"体不安定→识转, 体平息→识静"; 想清一个区 → Weaver E 降 → body_focus 不再列 →
自然不复发。legacy 保留老 cooldown (0 行为变)。

行为验证靠镜像 + Sir 真机 (设计红线: Phase 2 必镜像+真机逐块验)。本单测锚结构:
  T1 tick 两道 cooldown gate 都 emergent 条件化 (源码 anchor)
  T2 legacy SAME_CATEGORY_COOLDOWN_S 常量仍在 (legacy cooldown 不破)
  T3 _compute_free_categories 仍可用 (legacy 路径)
  T4 emergent free_categories 不被冷却 gate (源码: emergent → list('ABCDE'))
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_inner_thought_daemon import InnerThoughtDaemon


class TestP2RegionDischarge(unittest.TestCase):
    def _tick_src(self):
        """取含两道 cooldown gate 的 tick 方法源码 (整 class 源码兜底)."""
        return inspect.getsource(InnerThoughtDaemon)

    def test_t1_cooldown_gates_emergent_conditional(self):
        src = self._tick_src()
        # gate1 (全冷却→skip) emergent 分支
        self.assertIn("_tk_mode == 'emergent'", src,
                      'tick 应有 emergent 分支退类冷却 (Phase 2)')
        # gate2 (2nd-defense 同类 skip) emergent 退化
        self.assertIn("_tk_mode != 'emergent'", src,
                      '2nd-defense 同类 skip 应 emergent 退化')

    def test_t2_legacy_cooldown_constant_intact(self):
        # legacy cooldown 仍在 (0 行为变), 值不被 Phase 2 动
        self.assertTrue(hasattr(InnerThoughtDaemon, 'SAME_CATEGORY_COOLDOWN_S'))
        self.assertEqual(InnerThoughtDaemon.SAME_CATEGORY_COOLDOWN_S, 300)

    def test_t3_compute_free_categories_callable(self):
        d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        d._last_category_ts = {}
        free = d._compute_free_categories()
        # 全空 → 全 free (legacy 路径不破)
        self.assertEqual(set(free), set('ABCDE'))

    def test_t4_emergent_free_categories_not_gated(self):
        """emergent 分支把 free_categories 设为全集 (不按冷却挑)."""
        src = self._tick_src()
        # emergent 分支 free_categories = list('ABCDE')
        self.assertIn("list('ABCDE')", src,
                      "emergent 应 free_categories = list('ABCDE') (不按类冷却 gate)")


if __name__ == '__main__':
    unittest.main()
