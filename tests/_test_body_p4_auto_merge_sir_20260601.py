# -*- coding: utf-8 -*-
"""[体 P4 / Sir 2026-06-01] 内容中性算法健康: blob 时自动合并近重复 (全局 cosine sweep).

charter JARVIS_ANCHOR_DESIGN.md §6 + 理念源 §6/0601 决议: 体复杂度走**内容中性算法健康**
(去重/模块度), **非锚**。auto_merge_near_dups = 复用 D2 几何去重的**全局 sweep**(weave_geometric
是边形成时的 local merge; 本法 blob 时全局补一刀), 纯 cosine, 可逆 alias, 不删源、不做内容判断。

诚实边界: blob 的更深根是**过连接(distinct 节点挤一个 surface)**, 非重复 → 真正解需**模块度
压力**(surface 形成改, 风险高), 本 P4 不鲁莽动体, 只交付安全的去重 sweep, 模块度压力作 follow-up。

覆盖:
  T1 auto_merge_near_dups: 近重复(cos>=阈)→ merge(alias); 不同节点不动
  T2 max_merges 上限 respected
  T3 阈值高于相似度 → 0 merge(保守不误合)
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

from jarvis_relational_manifold import RelationalManifold
from jarvis_relational_weaver import RelationalWeaver


def _mk(d, vectors):
    for n in ("c.json", "s.json"):
        open(os.path.join(d, n), "w").write("{}")
    open(os.path.join(d, "r.json"), "w").write(
        '{"inside_jokes":{},"unspoken_protocols":{}}')
    open(os.path.join(d, "t.json"), "w").write('{"threads":[]}')
    vp = os.path.join(d, "v.json")
    with open(vp, "w", encoding="utf-8") as f:
        json.dump({"vectors": vectors}, f)
    m = RelationalManifold(os.path.join(d, "m.json"))
    w = RelationalWeaver(
        manifold=m, embed_fn=lambda ts: [None] * len(ts),
        threads_path=os.path.join(d, "t.json"),
        concerns_path=os.path.join(d, "c.json"),
        relational_path=os.path.join(d, "r.json"),
        vectors_path=vp, stance_path=os.path.join(d, "s.json"))
    return m, w


# n1,n2 near-dup (cos≈1.0); n3 orthogonal
_VEC = {
    "x:n1": {"vec": [1.0, 0.0, 0.0]},
    "x:n2": {"vec": [0.998, 0.06, 0.0]},
    "x:n3": {"vec": [0.0, 1.0, 0.0]},
}


class TestP4AutoMerge(unittest.TestCase):
    def test_t1_merges_near_dup(self):
        with tempfile.TemporaryDirectory() as d:
            m, w = _mk(d, _VEC)
            n = w.auto_merge_near_dups(threshold=0.95, max_merges=10)
            self.assertEqual(n, 1, "n1≈n2 应合并 1 对")
            self.assertEqual(m.resolve("x:n1"), m.resolve("x:n2"))
            self.assertNotEqual(m.resolve("x:n3"), m.resolve("x:n1"))  # n3 不动

    def test_t2_max_merges_cap(self):
        # 4 个全近重复, cap=1 → 只合 1 对
        vec = {f"x:m{i}": {"vec": [1.0, 0.001 * i, 0.0]} for i in range(4)}
        with tempfile.TemporaryDirectory() as d:
            m, w = _mk(d, vec)
            n = w.auto_merge_near_dups(threshold=0.95, max_merges=1)
            self.assertEqual(n, 1)

    def test_t3_high_threshold_no_false_merge(self):
        with tempfile.TemporaryDirectory() as d:
            m, w = _mk(d, _VEC)
            # 阈 0.999: n1/n2 cos≈0.998 < 0.999 → 不合 (保守)
            n = w.auto_merge_near_dups(threshold=0.9995, max_merges=10)
            self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
