# -*- coding: utf-8 -*-
"""[口识体-D2 / 2026-05-31] 主动合并近重复 (alias) — 防体积膨胀, 保复杂度.

复杂度度量(D1)抓出 blob → D2 把近重复节点(cosine>=merge_threshold)合并成代表(alias),
**不删源 store**(hippo 永不动), 投影/复杂度据此当一个。详 FULL_CLOSURE_AND_CONVERGENCE §6。

覆盖 (tmp 隔离):
  T1  add_alias + resolve (链 + 防环)
  T2  Weaver 检测近重复 (cosine>=0.90) → 记 alias
  T3  complexity_report 反映 merged_dups
  T4  BodyFocus 按 alias 去重 (两近重复 → 焦点只剩代表)
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

from jarvis_relational_manifold import RelationalManifold, make_node_id, KIND_THREAD
from jarvis_relational_weaver import RelationalWeaver
from jarvis_body_focus import BodyFocus

T0 = 1_780_000_000.0
_VEC = {"alpha one": [1.0, 0.0, 0.0], "alpha two": [0.99, 0.141, 0.0]}  # cos≈0.99


class _Embed:
    def __call__(self, texts):
        return [_VEC.get(t) for t in texts]


class TestMerge(unittest.TestCase):
    def test_t1_alias_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            a, b, c = "x:a", "x:b", "x:c"
            self.assertTrue(m.add_alias(b, a))
            self.assertTrue(m.add_alias(c, b))     # 链: c→b→a
            self.assertEqual(m.resolve(c), a)
            self.assertFalse(m.add_alias(a, c))    # 防环 (a→c→b→a)

    def test_t2_weaver_detects_dup(self):
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "t.json"); cp = os.path.join(d, "c.json")
            rp = os.path.join(d, "r.json"); sp = os.path.join(d, "s.json")
            with open(tp, "w") as f:
                json.dump({"threads": [
                    {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                    {"thread_id": "th2", "summary": "alpha two", "status": "open"}]}, f)
            for p in (cp, sp):
                open(p, "w").write("{}")
            open(rp, "w").write('{"inside_jokes":{},"unspoken_protocols":{}}')
            m = RelationalManifold(os.path.join(d, "m.json"))
            w = RelationalWeaver(manifold=m, embed_fn=_Embed(), threads_path=tp,
                                 concerns_path=cp, relational_path=rp,
                                 vectors_path=os.path.join(d, "v.json"), stance_path=sp)
            w.weave_geometric(now=T0)
            self.assertGreaterEqual(len(m.get_aliases()), 1, "cos≈0.99 应合并 alias")

    def test_t3_complexity_merged_dups(self):
        with tempfile.TemporaryDirectory() as d:
            m = RelationalManifold(os.path.join(d, "m.json"))
            m.add_alias("x:b", "x:a")
            self.assertEqual(m.complexity_report(now=T0)["merged_dups"], 1)

    def test_t4_focus_dedup_by_alias(self):
        with tempfile.TemporaryDirectory() as d:
            rep = make_node_id(KIND_THREAD, "rep")
            dup = make_node_id(KIND_THREAD, "dup")
            m = RelationalManifold(os.path.join(d, "m.json"))
            m.add_alias(dup, rep)
            ep = os.path.join(d, "energy.json")
            with open(ep, "w", encoding="utf-8") as f:
                json.dump({"recent_deltas": [],
                           "top_energy": [
                               {"node": rep, "total": 0.9, "tension": 0.9,
                                "novelty": 0, "drift": 0},
                               {"node": dup, "total": 0.8, "tension": 0.8,
                                "novelty": 0, "drift": 0}]}, f)
            bf = BodyFocus(manifold=m, energy_path=ep,
                           text_provider=lambda: {rep: "rep text", dup: "dup text"})
            focus = bf.current_focus(limit=6)
            nodes = [it["node"] for it in focus]
            self.assertEqual(nodes.count(rep), 1)   # 合并: 只剩代表
            self.assertNotIn(dup, nodes)            # dup 不单独出现


if __name__ == "__main__":
    unittest.main(verbosity=2)
