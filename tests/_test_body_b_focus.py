# -*- coding: utf-8 -*-
"""[口识体-B / 2026-05-31] current_focus 桥 (BodyFocus) testcase.

体此刻"哪里有势能" — 口/识 共读的单一焦点源。
详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §1/§5.

覆盖 (tmp 隔离):
  T1  current_focus: 合并 recent_deltas(fresh 优先) + top_energy; fresh 排前
  T2  focus_seeds 返 node id
  T3  has_fresh_delta
  T4  render_attention_block grounded (含节点文本 + why)
  T5  空势能 → 空焦点/空块
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_relational_manifold import RelationalManifold, make_node_id, KIND_CONCERN, KIND_THREAD
from jarvis_body_focus import BodyFocus

C1 = make_node_id(KIND_CONCERN, "sir_sleep")
TH1 = make_node_id(KIND_THREAD, "th1")
TEXT = {C1: "Sir 连续熬夜风险", TH1: "Sir 在赶 interview"}


def _mk(d, energy):
    ep = os.path.join(d, "body_energy.json")
    with open(ep, "w", encoding="utf-8") as f:
        json.dump(energy, f)
    man = RelationalManifold(os.path.join(d, "m.json"))
    return BodyFocus(manifold=man, energy_path=ep, text_provider=lambda: TEXT)


class TestBodyFocus(unittest.TestCase):
    def test_t1_merge_fresh_priority(self):
        with tempfile.TemporaryDirectory() as d:
            bf = _mk(d, {
                "recent_deltas": [{"node": C1, "kind": "tension", "magnitude": 0.7}],
                "top_energy": [{"node": TH1, "novelty": 0.5, "tension": 0.0,
                                "drift": 0.0, "total": 0.5}],
            })
            focus = bf.current_focus(limit=6)
            self.assertEqual(focus[0]["node"], C1)      # fresh delta 排前
            self.assertTrue(focus[0]["fresh"])
            nodes = {f["node"] for f in focus}
            self.assertIn(TH1, nodes)                   # standing 也在

    def test_t2_seeds(self):
        with tempfile.TemporaryDirectory() as d:
            bf = _mk(d, {"recent_deltas": [{"node": C1, "kind": "tension",
                                            "magnitude": 0.7}], "top_energy": []})
            self.assertEqual(bf.focus_seeds(), [C1])

    def test_t3_has_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            bf = _mk(d, {"recent_deltas": [{"node": C1, "kind": "tension",
                                            "magnitude": 0.7}], "top_energy": []})
            self.assertTrue(bf.has_fresh_delta())
            self.assertTrue(bf.has_fresh_delta(min_magnitude=0.5))
            self.assertFalse(bf.has_fresh_delta(min_magnitude=0.9))

    def test_t4_attention_block(self):
        with tempfile.TemporaryDirectory() as d:
            bf = _mk(d, {"recent_deltas": [{"node": C1, "kind": "tension",
                                            "magnitude": 0.7}], "top_energy": []})
            block = bf.render_attention_block()
            self.assertIn("BODY SIGNALS", block)
            self.assertIn("熬夜", block)            # 节点文本 grounded
            self.assertIn("tension", block)         # why

    def test_t5_empty(self):
        with tempfile.TemporaryDirectory() as d:
            bf = _mk(d, {"recent_deltas": [], "top_energy": []})
            self.assertEqual(bf.current_focus(), [])
            self.assertEqual(bf.render_attention_block(), "")
            self.assertFalse(bf.has_fresh_delta())


if __name__ == "__main__":
    unittest.main(verbosity=2)
