# -*- coding: utf-8 -*-
"""[口识体-B3 / 2026-05-31] 体势能 E + body_delta testcase.

势能自转的"坡度": E = w_nov·新颖(新边) + w_drift·漂移(边权变) + w_tension·张力(高severity
concern 无 stance 覆盖)。weave 后 diff → 能量上升超阈的节点派 body_delta 唤醒识。
详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §2/§3.

覆盖 (mock embed, tmp 隔离):
  T1  新颖: 新几何边 → 两端 novelty 能量 → delta (kind=novelty)
  T2  张力: 高severity concern 无 stance → tension 能量 → delta; 有 stance 覆盖 → 不计
  T3  **settled 不再 delta**: 第二轮无新边 + prev_energy 已记 → rise=0 → 0 delta (杜绝重复)
  T4  delta_publisher 被调 + 能量持久化文件
  T5  max_deltas_per_weave 上限
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
    RelationalManifold, make_node_id, KIND_THREAD, KIND_CONCERN,
)
from jarvis_relational_weaver import RelationalWeaver

T0 = 1_780_000_000.0


def _no_discount_cfg():
    """[body-diff-P0a] 关掉接地不对称折扣 (本组测能量/几何机制, 与折扣正交)。"""
    cfg = dict(_rm._SEED_MANIFOLD_CONFIG)
    cfg["self_produced_edge_discount"] = 1.0
    return cfg


def _patch_no_discount():
    """patch weaver + manifold 命名空间的 get_manifold_config (weave_once 两处都用)。"""
    import contextlib
    cm = contextlib.ExitStack()

    class _Both:
        def __enter__(self_):
            cm.enter_context(patch.object(_rw, "get_manifold_config",
                                          return_value=_no_discount_cfg()))
            cm.enter_context(patch.object(_rm, "get_manifold_config",
                                          return_value=_no_discount_cfg()))
            return self_

        def __exit__(self_, *a):
            cm.close()
            return False
    return _Both()

_VEC = {
    "alpha one": [1.0, 0.0, 0.0],
    "alpha two": [0.99, 0.141, 0.0],
    "beta thing": [0.0, 1.0, 0.0],
}


class _Embed:
    def __call__(self, texts):
        return [_VEC.get(t) for t in texts]


def _mk(d, *, threads=None, concerns=None, stances=None, publisher=None):
    tp = os.path.join(d, "self_threads.json")
    cp = os.path.join(d, "concerns.json")
    rp = os.path.join(d, "relational_state.json")
    sp = os.path.join(d, "stance.json")
    with open(tp, "w", encoding="utf-8") as f:
        json.dump({"threads": threads or []}, f)
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(concerns or {}, f)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"inside_jokes": {}, "unspoken_protocols": {}}, f)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"stances": stances or {}}, f)
    man = RelationalManifold(os.path.join(d, "manifold.json"))
    return RelationalWeaver(
        manifold=man, embed_fn=_Embed(),
        threads_path=tp, concerns_path=cp, relational_path=rp,
        vectors_path=os.path.join(d, "vec.json"), stance_path=sp,
        energy_path=os.path.join(d, "energy.json"), delta_publisher=publisher)


class TestBodyEnergy(unittest.TestCase):
    def test_t1_novelty_delta(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk(d, threads=[
                {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                {"thread_id": "th2", "summary": "alpha two", "status": "open"}])
            with _patch_no_discount():
                stats = w.weave_once(now=T0)
            deltas = w.recent_deltas()
            nov = [x for x in deltas if x["kind"] == "novelty"]
            self.assertTrue(nov, "新几何边应产生 novelty delta")
            nodes = {x["node"] for x in nov}
            self.assertIn(make_node_id(KIND_THREAD, "th1"), nodes)

    def test_t2_tension_uncovered_only(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk(d,
                    concerns={
                        "c1": {"id": "c1", "what_i_watch": "Sir 熬夜",
                               "severity": 0.6, "state": "active"},
                        "c2": {"id": "c2", "what_i_watch": "Sir 久坐",
                               "severity": 0.6, "state": "active"}},
                    stances={"s1": {"stance_id": "s1", "claim": "x", "about": "c2",
                                    "state": "active", "confidence": 0.7}})
            w.weave_once(now=T0)
            deltas = w.recent_deltas()
            tens = {x["node"] for x in deltas if x["kind"] == "tension"}
            self.assertIn(make_node_id(KIND_CONCERN, "c1"), tens)   # 无 stance → 张力
            self.assertNotIn(make_node_id(KIND_CONCERN, "c2"), tens)  # 有 stance → 不计

    def test_t3_settled_no_repeat_delta(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk(d, threads=[
                {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                {"thread_id": "th2", "summary": "alpha two", "status": "open"}],
                concerns={"c1": {"id": "c1", "what_i_watch": "x",
                                 "severity": 0.6, "state": "active"}})
            with _patch_no_discount():
                w.weave_once(now=T0)
                self.assertTrue(w.recent_deltas(), "首轮应有 delta")
                # 第二轮: 无新边 + prev_energy 已记 → rise=0 → settled, 不再 delta (杜绝重复)
                w.weave_once(now=T0)
            self.assertEqual(len(w.recent_deltas()), 0,
                             "settled 后不应再 delta (resolved=discharged 不复发)")

    def test_t4_publisher_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            got = []
            w = _mk(d, threads=[
                {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                {"thread_id": "th2", "summary": "alpha two", "status": "open"}],
                publisher=lambda dlt: got.append(dlt))
            with _patch_no_discount():
                w.weave_once(now=T0)
            self.assertTrue(got, "delta_publisher 应被调")
            self.assertTrue(os.path.exists(os.path.join(d, "energy.json")))
            data = json.load(open(os.path.join(d, "energy.json"), encoding="utf-8"))
            self.assertIn("recent_deltas", data)
            self.assertIn("top_energy", data)

    def test_t5_max_deltas_cap(self):
        with tempfile.TemporaryDirectory() as d:
            # 造一堆高 severity uncovered concern → 一堆 tension delta, 测上限
            concerns = {f"c{i}": {"id": f"c{i}", "what_i_watch": f"x{i}",
                                  "severity": 0.9, "state": "active"} for i in range(30)}
            w = _mk(d, concerns=concerns)
            w.weave_once(now=T0)
            cap = int(__import__("jarvis_relational_manifold").get_manifold_config()
                      ["energy"]["max_deltas_per_weave"])
            self.assertLessEqual(len(w.recent_deltas()), cap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
