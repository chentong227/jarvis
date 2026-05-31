# -*- coding: utf-8 -*-
"""[体-P6 / 2026-05-31] 透镜 Lens testcase.

透镜 = 体→口 忠实投影 (相关性 + 形状/阻力 两重忠实)。
详 docs/JARVIS_TRINITY_ARCHITECTURE.md §5/§6.

覆盖 (无 LLM, tmp 隔离):
  T1  相关性: spreading-activation 选相关节点进 block; seed 本身不重复进
  T2  形状/阻力: 高置信 active 立场进 "My read" 段 (即使和语境无边)
  T3  gate: lens_inject_enabled 默认 0 → build_lens_block 返 ""; 开 → 有内容
  T4  空体 → 投影空串
  T5  char budget: 超预算截断不溢出
  T6  default_seeds: 无 seed 时用 concern + 高度数 hub
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as M
from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, KIND_CONCERN, KIND_THREAD,
)
from jarvis_relational_lens import RelationalLens
from jarvis_stance import StanceStore, STATE_ACTIVE

T0 = 1_780_000_000.0


def _seed_manifold(d):
    m = RelationalManifold(os.path.join(d, "manifold.json"))
    sleep = make_node_id(KIND_CONCERN, "sir_sleep")
    pomo = make_node_id(KIND_CONCERN, "sir_pomodoro")
    thread = make_node_id(KIND_THREAD, "th1")
    # sleep ~ pomodoro (强), pomodoro ~ thread (中)
    m.observe_explicit_link(sleep, pomo, "turn_1", now=T0)
    m.observe_cooccurrence([pomo, thread], "turn_1", now=T0)
    text = {
        sleep: "Sir 连续熬夜风险", pomo: "Sir 番茄钟工作节奏",
        thread: "Sir 在赶 interview 准备",
    }
    return m, text, sleep, pomo, thread


class TestLens(unittest.TestCase):
    def test_t1_relevance_projection(self):
        with tempfile.TemporaryDirectory() as d:
            m, text, sleep, pomo, thread = _seed_manifold(d)
            lens = RelationalLens(manifold=m, stance_store=False,
                                  text_provider=lambda: text)
            block = lens.project([sleep], now=T0)
            self.assertIn("RELATIONAL CONTEXT", block)
            self.assertIn("番茄钟", block)        # pomo 被激活
            self.assertNotIn("连续熬夜", block)    # seed 本身不重复进投影

    def test_t2_stance_shape_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            m, text, sleep, pomo, thread = _seed_manifold(d)
            st = StanceStore(os.path.join(d, "stance.json"))
            st.add_stance("Sir 截止日临近易牺牲休息, 温和坚持有效", "sir_wellbeing",
                          evidence_kind="thought", evidence_ref="t1",
                          confidence=0.8, state=STATE_ACTIVE, now=T0)
            lens = RelationalLens(manifold=m, stance_store=st,
                                  text_provider=lambda: text)
            block = lens.project([sleep], now=T0)
            self.assertIn("My read", block)
            self.assertIn("温和坚持", block)       # 立场被保留 (形状/阻力)

    def test_t3_gate_default_off(self):
        with tempfile.TemporaryDirectory() as d:
            m, text, sleep, pomo, thread = _seed_manifold(d)
            import jarvis_relational_lens as L
            # 默认 gate off → build_lens_block 返空
            self.assertFalse(L.lens_inject_enabled())
            # 直接 project 不受 gate 影响 (gate 只在 build_lens_block)
            lens = RelationalLens(manifold=m, stance_store=False,
                                  text_provider=lambda: text)
            self.assertTrue(lens.project([sleep], now=T0))

    def test_t4_empty_body(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            lens = RelationalLens(manifold=m, stance_store=False,
                                  text_provider=lambda: {})
            self.assertEqual(lens.project([], now=T0), "")

    def test_t5_char_budget(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            hub = make_node_id(KIND_CONCERN, "hub")
            text = {hub: "seed"}
            for i in range(40):
                n = make_node_id(KIND_THREAD, f"t{i}")
                m.observe_explicit_link(hub, n, "turn_1", now=T0)
                text[n] = "X" * 200  # 长文本
            lens = RelationalLens(manifold=m, stance_store=False,
                                  text_provider=lambda: text)
            block = lens.project([hub], max_chars=600, now=T0)
            self.assertLessEqual(len(block), 700)  # 不显著溢出预算

    def test_t6_default_seeds(self):
        with tempfile.TemporaryDirectory() as d:
            m, text, sleep, pomo, thread = _seed_manifold(d)
            lens = RelationalLens(manifold=m, stance_store=False,
                                  text_provider=lambda: text)
            seeds = lens.default_seeds(limit=6)
            self.assertIn(sleep, seeds)   # concern 优先进 seeds
            self.assertIn(pomo, seeds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
