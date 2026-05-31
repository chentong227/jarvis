# -*- coding: utf-8 -*-
"""[口识体-E / 2026-05-31] SOUL Layer2/3 → 体/lens 收敛 (内敛, flag-gated 渐进退平行).

relational_state(Layer2) 是体的胚胎, attention(Layer3) 已被识/体势能驱动 — 与透镜并存
= 平行表示 (准则 6 #4 反例)。closure E 加 flag-gated 替换: 透镜活 + flag 开 → 体/lens 供,
退旧块。**默认关 → 零生产影响; Sir 真机 A/B 验投影质量满意后才开 → 逐块退, 不一次全换。**
详 docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md §4 closure E.

覆盖 (无 LLM):
  E1  flag 默认关 (lens_replaces_layer2/3 → False) — 零生产影响
  E2  flag 开 (config override) → True
  E3  l2/l3 独立可控
  E4  central_nerve 接线: 透镜活 + flag 开 → 退 Layer2/3 平行 (静态守护)
  E5  安全: 透镜空时不读 replace flag (substitution 仅透镜活才考虑)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_lens as L
from jarvis_relational_lens import lens_replaces_layer2, lens_replaces_layer3


class TestLayerConverge(unittest.TestCase):
    def test_e1_default_off(self):
        # seed 默认 0 → 零生产影响 (代码级安全默认; 测 seed fallback, 不读 prod 实配,
        # 因 prod vocab 可被 Sir/真机验后调开 — 那是数据不是代码默认).
        _orig = L.get_manifold_config
        try:
            L.get_manifold_config = lambda: {}   # 空配 → 走 seed fallback 默认
            self.assertFalse(lens_replaces_layer2())
            self.assertFalse(lens_replaces_layer3())
        finally:
            L.get_manifold_config = _orig

    def test_e2_flag_on(self):
        _orig = L.get_manifold_config
        try:
            L.get_manifold_config = lambda: {"lens_replaces_layer2": 1,
                                             "lens_replaces_layer3": 1}
            self.assertTrue(lens_replaces_layer2())
            self.assertTrue(lens_replaces_layer3())
        finally:
            L.get_manifold_config = _orig

    def test_e3_independent(self):
        _orig = L.get_manifold_config
        try:
            L.get_manifold_config = lambda: {"lens_replaces_layer2": 1,
                                             "lens_replaces_layer3": 0}
            self.assertTrue(lens_replaces_layer2())
            self.assertFalse(lens_replaces_layer3())
        finally:
            L.get_manifold_config = _orig

    def test_e4_central_nerve_wired(self):
        with open(os.path.join(ROOT, "jarvis_central_nerve.py"), encoding="utf-8") as f:
            src = f.read()
        # 替换决策变量 + 条件接线
        self.assertIn("_lens_replaces_l2", src)
        self.assertIn("_lens_replaces_l3", src)
        self.assertIn("not _lens_replaces_l2", src)  # Layer2 退平行条件
        self.assertIn("not _lens_replaces_l3", src)  # Layer3 退平行条件
        self.assertIn("lens_replaces_layer2", src)   # import flag helper

    def test_e6_default_seeds_robust_to_stale_focus(self):
        # 真机发现根因: body_energy 被 stale/test 数据污染 (th1/th2 不存在) → focus_seeds
        # 指向不存在节点 → 透镜投影空. 修: default_seeds 过滤不存在 seed → fallback concern。
        import tempfile
        import jarvis_body_focus as BF
        from jarvis_relational_manifold import (
            RelationalManifold, make_node_id, KIND_CONCERN)
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            c1 = make_node_id(KIND_CONCERN, "c1")
            lens = L.RelationalLens(manifold=m, stance_store=False, text_provider=None)
            lens._node_text_map = lambda: {c1: "Sir concern one watch"}

            class _FakeFocus:
                def focus_seeds(self, *, limit=6):
                    return ["thread:th1", "thread:th2"]  # stale, 体里不存在

            _orig = BF.get_body_focus
            try:
                BF.get_body_focus = lambda: _FakeFocus()
                seeds = lens.default_seeds(limit=6)
            finally:
                BF.get_body_focus = _orig
            self.assertNotIn("thread:th1", seeds)  # stale seed 被过滤
            self.assertIn(c1, seeds)               # fallback 到真实 concern (透镜不空)

    def test_e5_replace_only_when_lens_active(self):
        # 安全: 必须在 'if lens_block:' guard 内才读 replace flag — 透镜空不替旧块
        with open(os.path.join(ROOT, "jarvis_central_nerve.py"), encoding="utf-8") as f:
            src = f.read()
        idx_guard = src.find("if lens_block:\n                _lens_replaces_l2")
        self.assertGreater(idx_guard, -1,
                           "replace flag 必须在透镜活 guard 内读 (透镜空→不替, 零影响)")

    def test_e7_seeds_from_text_topic(self):
        # prereq1: 透镜从当前对话文本词法匹配体节点 (替 Layer3 current-focus 角色)
        import tempfile
        from jarvis_relational_manifold import (
            RelationalManifold, make_node_id, KIND_CONCERN, KIND_THREAD)
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            hyd = make_node_id(KIND_CONCERN, "hydration")
            sleep = make_node_id(KIND_THREAD, "sleep")
            tmap = {hyd: "Sir hydration water intake reminders",
                    sleep: "totally different gardening topic here"}
            lens = L.RelationalLens(manifold=m, stance_store=False,
                                    text_provider=lambda: tmap)
            seeds = lens.seeds_from_text("how is my hydration and water today", limit=3)
            self.assertIn(hyd, seeds)        # 命中当前话题节点
            self.assertNotIn(sleep, seeds)   # 不相关不命中

    def test_e8_replace_keeps_strict_protocols(self):
        # prereq2: 替 Layer2 时仍注入 protocols-only block (STRICT RULES 常驻, 不丢人设硬规)
        with open(os.path.join(ROOT, "jarvis_central_nerve.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("_proto_only", src)
        self.assertIn("top_jokes=0", src)            # 砍 jokes, 仅留 protocol
        self.assertIn("elif _lens_replaces_l2", src)  # 替 L2 分支
        # prereq1 接线: 透镜吃 user_input
        self.assertIn("build_lens_block(user_input=", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
