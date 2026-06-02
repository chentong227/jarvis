# -*- coding: utf-8 -*-
"""[体-P2/P5 / 2026-05-31] 织网者 Weaver + 几何边 testcase.

体 (Body) 的维护器官: harvest 节点 → embed(缓存) → 几何 cosine 边 → decay/prune。
详 docs/JARVIS_TRINITY_ARCHITECTURE.md §4.

覆盖 (mock embedder, 确定 cosine, tmp 隔离):
  T1  harvest: 从 threads/concerns/relational 取节点 + 文本; 过滤 archived/let_go/过短
  T2  几何织网: 相似(cos>阈值)连 embed 边, 不相似不连; provenance kind=embed + confidence≈cos
  T3  **属性边幂等**: 重复 weave 不膨胀 (set-to-floor, 区别于事件边 Hebbian 累加)
  T4  向量缓存: 文本不变 → 不重复 embed (省 API); 文本变 → 重 embed
  T5  weave_once: 返回 stats + 持久化 manifold + vectors 文件
  T6  maintain: decay + prune 枯边
  T7  事件边 + 几何边混合: weight = max(事件累加, 几何floor)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as _rm
import jarvis_relational_weaver as _rw
from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, get_manifold_config,
    KIND_THREAD, KIND_CONCERN, KIND_JOKE, KIND_PROTOCOL,
    PROV_EMBED, PROV_COOCCUR,
)
from jarvis_relational_weaver import RelationalWeaver

T0 = 1_780_000_000.0


def _no_discount_cfg():
    """[body-diff-P0a] 关接地不对称折扣 (本组测几何边权公式, 与折扣正交)。"""
    cfg = dict(_rm._SEED_MANIFOLD_CONFIG)
    cfg["self_produced_edge_discount"] = 1.0
    return cfg

# 确定向量 → 已知 cosine: alpha 系两条近平行 (cos≈0.99), beta 正交 (cos=0)
_VEC = {
    "alpha one":  [1.0, 0.0, 0.0],
    "alpha two":  [0.99, 0.141, 0.0],   # 与 alpha one cos≈0.99
    "beta thing": [0.0, 1.0, 0.0],      # 正交
}


class _CountingEmbed:
    """mock embedder: 按文本查表, 记调用次数 (验缓存)."""

    def __init__(self):
        self.calls = 0
        self.embedded = 0

    def __call__(self, texts):
        self.calls += 1
        self.embedded += len(texts)
        return [_VEC.get(t) for t in texts]


def _write_stores(d: str, *, threads=None, concerns=None, jokes=None, protos=None):
    tp = os.path.join(d, "self_threads.json")
    cp = os.path.join(d, "concerns.json")
    rp = os.path.join(d, "relational_state.json")
    with open(tp, "w", encoding="utf-8") as f:
        json.dump({"threads": threads or []}, f)
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(concerns or {}, f)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"inside_jokes": jokes or {}, "unspoken_protocols": protos or {}}, f)
    return tp, cp, rp


def _mk_weaver(d, embed_fn, **store_kwargs):
    tp, cp, rp = _write_stores(d, **store_kwargs)
    man = RelationalManifold(os.path.join(d, "manifold.json"))
    return RelationalWeaver(
        manifold=man, embed_fn=embed_fn,
        threads_path=tp, concerns_path=cp, relational_path=rp,
        vectors_path=os.path.join(d, "vectors.json"),
        # 测试隔离: 必须 tmp energy_path/stance_path, 否则 weave_once._save_energy 写真
        # memory_pool/body_energy.json (真机发现: th1/th2 残留污染 prod 透镜 default_seeds)。
        stance_path=os.path.join(d, "stance.json"),
        energy_path=os.path.join(d, "energy.json"),
    )


class TestHarvest(unittest.TestCase):
    def test_t1_harvest_filters(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk_weaver(
                d, _CountingEmbed(),
                threads=[
                    {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                    {"thread_id": "th2", "summary": "x", "status": "open"},       # 过短
                    {"thread_id": "th3", "summary": "gone now", "status": "let_go"},  # 放下
                ],
                concerns={
                    "c1": {"id": "c1", "what_i_watch": "beta thing",
                           "why_i_care": "", "state": "active"},
                    "c2": {"id": "c2", "what_i_watch": "archived one",
                           "state": "archived"},          # 归档跳过
                    "_meta": {"x": 1},                      # _ 前缀跳过
                },
                jokes={"j1": {"id": "j1", "phrase": "alpha two",
                              "birth_context": "", "state": "active"}},
                protos={"p1": {"id": "p1", "rule": "always be concise", "state": "active"}},
            )
            nodes = w.harvest_nodes()
            self.assertIn(make_node_id(KIND_THREAD, "th1"), nodes)
            self.assertNotIn(make_node_id(KIND_THREAD, "th2"), nodes)  # 过短
            self.assertNotIn(make_node_id(KIND_THREAD, "th3"), nodes)  # let_go
            self.assertIn(make_node_id(KIND_CONCERN, "c1"), nodes)
            self.assertNotIn(make_node_id(KIND_CONCERN, "c2"), nodes)  # archived
            self.assertIn(make_node_id(KIND_JOKE, "j1"), nodes)
            self.assertIn(make_node_id(KIND_PROTOCOL, "p1"), nodes)
            self.assertEqual(nodes[make_node_id(KIND_THREAD, "th1")], "alpha one")


class TestGeometric(unittest.TestCase):
    def _three_node_weaver(self, d, embed):
        return _mk_weaver(
            d, embed,
            threads=[
                {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                {"thread_id": "th2", "summary": "alpha two", "status": "open"},
            ],
            concerns={"c1": {"id": "c1", "what_i_watch": "beta thing",
                             "state": "active"}},
        )

    def test_t2_geometric_edges(self):
        with tempfile.TemporaryDirectory() as d:
            w = self._three_node_weaver(d, _CountingEmbed())
            with patch.object(_rw, "get_manifold_config", return_value=_no_discount_cfg()):
                added = w.weave_geometric(now=T0)
            self.assertEqual(added, 1)  # 仅 alpha one ~ alpha two
            a = make_node_id(KIND_THREAD, "th1")
            b = make_node_id(KIND_THREAD, "th2")
            beta = make_node_id(KIND_CONCERN, "c1")
            e = w.manifold.get_edge(a, b)
            self.assertIsNotNone(e)
            self.assertEqual(e["provenance"][0]["kind"], PROV_EMBED)
            self.assertEqual(e["provenance"][0]["ref"], "cosine")
            self.assertGreater(e["provenance"][0]["confidence"], 0.95)
            # weight ≈ embed_increment(0.60) * cos(≈0.99)
            self.assertAlmostEqual(e["weight"], 0.60 * e["provenance"][0]["confidence"],
                                   places=2)
            # 不相似 → 无边
            self.assertIsNone(w.manifold.get_edge(a, beta))

    def test_t3_idempotent_no_inflation(self):
        with tempfile.TemporaryDirectory() as d:
            w = self._three_node_weaver(d, _CountingEmbed())
            w.weave_geometric(now=T0)
            a = make_node_id(KIND_THREAD, "th1")
            b = make_node_id(KIND_THREAD, "th2")
            w1 = w.manifold.get_edge(a, b)["weight"]
            # 同一时刻重复 weave 3 次 → 属性边不累加 (set-to-floor)
            for _ in range(3):
                w.weave_geometric(now=T0)
            w2 = w.manifold.get_edge(a, b)["weight"]
            self.assertAlmostEqual(w1, w2, places=6)

    def test_t4_vector_cache(self):
        with tempfile.TemporaryDirectory() as d:
            embed = _CountingEmbed()
            w = self._three_node_weaver(d, embed)
            w.weave_geometric(now=T0)
            self.assertEqual(embed.calls, 1)       # 一批
            self.assertEqual(embed.embedded, 3)    # 3 节点
            # 文本不变再 weave → 不重 embed
            w.weave_geometric(now=T0)
            self.assertEqual(embed.calls, 1)
            self.assertEqual(embed.embedded, 3)


class TestWeaveOnceAndMaintain(unittest.TestCase):
    def test_t5_weave_once_persists(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk_weaver(
                d, _CountingEmbed(),
                threads=[
                    {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                    {"thread_id": "th2", "summary": "alpha two", "status": "open"},
                ],
            )
            stats = w.weave_once(now=T0)
            self.assertEqual(stats["weave_count"], 1)
            self.assertEqual(stats["nodes"], 2)
            self.assertEqual(stats["embed_edges_added"], 1)
            self.assertEqual(stats["edge_count"], 1)
            self.assertTrue(os.path.exists(os.path.join(d, "manifold.json")))
            self.assertTrue(os.path.exists(os.path.join(d, "vectors.json")))
            # reload manifold → 边在
            m2 = RelationalManifold(os.path.join(d, "manifold.json"))
            self.assertEqual(m2.stats()["edge_count"], 1)

    def test_t6_maintain_prunes_stale(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk_weaver(d, _CountingEmbed())
            a, b = make_node_id(KIND_THREAD, "x"), make_node_id(KIND_THREAD, "y")
            w.manifold.add_edge(a, b, PROV_COOCCUR, "turn_1", now=T0)  # 0.30
            hl = float(get_manifold_config()["half_life_days"]) * 86400.0
            pruned = w.maintain(now=T0 + 3 * hl)  # 0.30*0.125 < 0.05 floor
            self.assertEqual(pruned, 1)
            self.assertEqual(w.manifold.stats()["edge_count"], 0)

    def test_t7_event_plus_geometric_max(self):
        with tempfile.TemporaryDirectory() as d:
            w = self._mk(d)
            a = make_node_id(KIND_THREAD, "th1")
            b = make_node_id(KIND_THREAD, "th2")
            # 先事件边 (cooccur 0.30 累加 2 次 = 0.60)
            w.manifold.add_edge(a, b, PROV_COOCCUR, "t1", now=T0)
            w.manifold.add_edge(a, b, PROV_COOCCUR, "t2", now=T0)
            ev = w.manifold.get_edge(a, b)["weight"]
            # 几何 floor (0.60*0.99≈0.594) < 事件 0.60 → max 保留事件值
            w.weave_geometric(now=T0)
            after = w.manifold.get_edge(a, b)["weight"]
            self.assertGreaterEqual(after, ev - 1e-6)
            # 两种 provenance 都在
            kinds = {p["kind"] for p in w.manifold.get_edge(a, b)["provenance"]}
            self.assertIn(PROV_COOCCUR, kinds)
            self.assertIn(PROV_EMBED, kinds)

    def _mk(self, d):
        return _mk_weaver(
            d, _CountingEmbed(),
            threads=[
                {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                {"thread_id": "th2", "summary": "alpha two", "status": "open"},
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
