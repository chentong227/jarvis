# -*- coding: utf-8 -*-
"""[body-diff-P0c-Tier1 / Sir 2026-06-03] thread→concern "about" 边 (生成期连, grounded by concern_id).

真理源: docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md §14 (P0c about 边设计)。

== 修的真根因 (P0c 诊断, Sir 确认) ==
思考脑生 C 类 thought 时 actionable=adjust_concern_notes:<concern_id> **生成期就明确带 concern_id**,
但老码只 append concern.notes_for_self, **从不写成 manifold 边** → thread 进体只剩 summary →
靠 embed(cosine)/偶发 cooccur → 49 thread 孤儿。Tier1 = 当场把这根接地线记成 grounded 边。

== Sir 红线 ==
- ② 判据 = concern_id 机械 ref, **绝非 cosine, 绝非 LLM** (准则1 边生成纯几何/机械)。
- 14.1 铁律: 只在真有 referent 时连, **缺 referent → 不造边 (绝不凑接地降孤儿数)**。

覆盖 (纯机械, tmp 隔离):
  T1  observe_thought_concern_link 造 thread~concern 边 (PROV_SHARED + ref=concern_id)
  T2  机械 ref 非 cosine — provenance 无 PROV_EMBED (② 红线)
  T3  缺 referent (空 thread_id/concern_id) → 不造边 (14.1 铁律: 不凑接地)
  T4  idempotent — 重复调同一边 reinforce, 不重复造
  T5  daemon _do_adjust_concern_notes 已 wire Tier1 连边 (生成期 hook)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, KIND_THREAD, KIND_CONCERN,
    PROV_SHARED, PROV_EMBED,
)
from jarvis_relational_weaver import observe_thought_concern_link


def _mk(d):
    return RelationalManifold(os.path.join(d, "m.json"))


class TestTier1AboutEdge(unittest.TestCase):
    def test_t1_creates_grounded_shared_edge(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            key = observe_thought_concern_link(
                "thought_20260531_x", "sir_hydration_habit", manifold=m, save=False)
            self.assertIsNotNone(key, "应返 edge_key")
            tnode = make_node_id(KIND_THREAD, "thought_20260531_x")
            cnode = make_node_id(KIND_CONCERN, "sir_hydration_habit")
            e = m.get_edge(tnode, cnode)
            self.assertIsNotNone(e, "thread~concern about 边应被造")
            kinds = {p["kind"] for p in e["provenance"]}
            self.assertIn(PROV_SHARED, kinds, "应是 shared 边 (接地)")
            self.assertTrue(
                any(p.get("ref") == "sir_hydration_habit" for p in e["provenance"]),
                "ref=concern_id (机械接地, 可 trace)")

    def test_t2_not_cosine_not_embed(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            observe_thought_concern_link("th_a", "sir_x", manifold=m, save=False)
            e = m.get_edge(make_node_id(KIND_THREAD, "th_a"),
                           make_node_id(KIND_CONCERN, "sir_x"))
            kinds = {p["kind"] for p in e["provenance"]}
            self.assertNotIn(PROV_EMBED, kinds,
                             "Tier1 绝不 cosine/embed (Sir ② 焊死红线)")

    def test_t3_no_fabrication_on_missing_referent(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            self.assertIsNone(observe_thought_concern_link("", "sir_x", manifold=m, save=False))
            self.assertIsNone(observe_thought_concern_link("th_a", "", manifold=m, save=False))
            self.assertIsNone(observe_thought_concern_link("  ", "  ", manifold=m, save=False))
            self.assertEqual(m.stats()["edge_count"], 0,
                             "缺 referent → 不造边 (14.1 铁律: 绝不凑接地降孤儿数)")

    def test_t4_idempotent_reinforce(self):
        with tempfile.TemporaryDirectory() as d:
            m = _mk(d)
            observe_thought_concern_link("th_a", "sir_x", manifold=m, save=False)
            observe_thought_concern_link("th_a", "sir_x", manifold=m, save=False)
            self.assertEqual(m.stats()["edge_count"], 1,
                             "重复调 → 同一边 reinforce, 不重复造")

    def test_t5_daemon_wired_at_generation(self):
        import jarvis_inner_thought_daemon as itd
        with open(itd.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("observe_thought_concern_link", src,
                      "daemon _do_adjust_concern_notes 必须 wire Tier1 生成期连边")


if __name__ == "__main__":
    unittest.main(verbosity=2)
