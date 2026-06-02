# -*- coding: utf-8 -*-
"""[习惯化 / Sir 2026-06-02 反刍治本] 放电反馈缺口补全 testcase.

深挖结论 (非热补丁): 设计 §3 承诺 "识放电→该区 E 降→不再醒", 但唯一 wired 放电通道是
stance-coverage。低 agency concern (hydration) 识反复 attend 却只 adjust_notes (不改
severity 不立 stance) → 永不放电 → tension=severity 每 weave 重算 → 反复被召唤
("认识到自己反刍却停不下" = 结构缺口, 早于衡/锚)。

习惯化 (纯物理, 无 LLM, 接地 body_attention_outcome event):
  T1  反复非放电 attend 超 free_attends → tension 渐衰 (×factor)
  T2  真放电 (discharged=True) → 习惯化重置 (full tension 恢复)
  T3  免费窗内 (<= free_attends) → 不衰 (允许正常想清)
  T4  spontaneous recovery: 久不 attend (> recovery_s) → 恢复
  T5  novelty/drift 不受习惯化 (真新进展突破)
  T6  habituation_enabled=0 → 关闭 (回旧行为)
  T7  floor: 衰减不归 0 (仍可被真新事唤醒)
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

from jarvis_relational_manifold import (
    RelationalManifold, make_node_id, KIND_CONCERN, KIND_THREAD,
)
from jarvis_relational_weaver import RelationalWeaver

T0 = 1_780_000_000.0

_VEC = {
    "alpha one": [1.0, 0.0, 0.0],
    "alpha two": [0.99, 0.141, 0.0],
}


class _Embed:
    def __call__(self, texts):
        return [_VEC.get(t) for t in texts]


class _FakeBus:
    """最小 SWM bus: recent_events(types) 过滤 + timestamp/metadata 透传。"""

    def __init__(self, events=None):
        self.events = list(events or [])

    def recent_events(self, within_seconds=None, types=None):
        out = []
        for e in self.events:
            if types is not None and e.get("type") not in types:
                continue
            out.append(dict(e))
        return out

    def publish(self, *a, **k):
        return None


def _outcome(node, discharged, ts=T0):
    return {"type": "body_attention_outcome", "timestamp": ts,
            "metadata": {"node": node, "discharged": discharged}}


def _mk(d, *, concerns=None, threads=None, stances=None, bus=None):
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
        energy_path=os.path.join(d, "energy.json"), event_bus=bus)


def _hydration_concern(sev=0.9):
    return {"sir_water": {"id": "sir_water", "what_i_watch": "Sir 喝水",
                          "severity": sev, "state": "active"}}


class TestHabituation(unittest.TestCase):
    def test_t1_repeated_non_discharge_decays_tension(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            # 5 次非放电 attend, free=2 → excess=3 → factor=0.6^3=0.216
            evs = [_outcome(nid, False, ts=T0 + i) for i in range(5)]
            w = _mk(d, concerns=_hydration_concern(), bus=_FakeBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 10)
            tens = energy[nid]["tension"]
            # baseline 无习惯化应是 0.9; 习惯化后应明显 < 0.9
            self.assertLess(tens, 0.9 * 0.5,
                            f"反复非放电 attend 应衰 tension, got {tens}")
            self.assertAlmostEqual(tens, 0.9 * (0.6 ** 3), places=3)

    def test_t2_discharge_resets(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            # 4 非放电 然后 1 放电 → 放电后 non_discharge 归 0 → 不衰
            evs = [_outcome(nid, False, ts=T0 + i) for i in range(4)]
            evs.append(_outcome(nid, True, ts=T0 + 5))
            w = _mk(d, concerns=_hydration_concern(), bus=_FakeBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 10)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9, places=6,
                                   msg="真放电应重置习惯化 (full tension)")

    def test_t3_within_free_window_no_decay(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            # 2 次非放电 == free_attends → excess=0 → 不衰
            evs = [_outcome(nid, False, ts=T0 + i) for i in range(2)]
            w = _mk(d, concerns=_hydration_concern(), bus=_FakeBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 5)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9, places=6,
                                   msg="免费窗内不衰 (允许正常想清)")

    def test_t4_spontaneous_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            # 5 次非放电但都在很久前 (> recovery_s=3600) → 恢复
            evs = [_outcome(nid, False, ts=T0 + i) for i in range(5)]
            w = _mk(d, concerns=_hydration_concern(), bus=_FakeBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 5000)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9, places=6,
                                   msg="久不 attend 应 spontaneous recovery")

    def test_t5_novelty_not_habituated(self):
        with tempfile.TemporaryDirectory() as d:
            # novelty 来自新几何边 (th1/th2 cosine 高), 习惯化只乘 tension
            th_nid = make_node_id(KIND_THREAD, "th1")
            evs = [_outcome(th_nid, False, ts=T0 + i) for i in range(8)]
            w = _mk(d, threads=[
                {"thread_id": "th1", "summary": "alpha one", "status": "open"},
                {"thread_id": "th2", "summary": "alpha two", "status": "open"}],
                bus=_FakeBus(evs))
            stats = w.weave_once(now=T0)
            deltas = w.recent_deltas()
            nov = [x for x in deltas if x["kind"] == "novelty"]
            self.assertTrue(nov, "novelty 不受习惯化 → 真新进展应突破")

    def test_t6_disabled_no_habituation(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            evs = [_outcome(nid, False, ts=T0 + i) for i in range(8)]
            w = _mk(d, concerns=_hydration_concern(), bus=_FakeBus(evs))
            # monkeypatch config off via _ecfg override
            _orig = w._ecfg
            w._ecfg = lambda: {**_orig(), "habituation_enabled": 0}
            energy = w.compute_energy(set(), {}, {}, now=T0 + 10)
            self.assertAlmostEqual(energy[nid]["tension"], 0.9, places=6,
                                   msg="habituation_enabled=0 → 回旧行为不衰")

    def test_t7_floor_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            # 大量非放电 attend → factor 应触底 floor (0.15), 不归 0
            evs = [_outcome(nid, False, ts=T0 + i) for i in range(30)]
            w = _mk(d, concerns=_hydration_concern(), bus=_FakeBus(evs))
            energy = w.compute_energy(set(), {}, {}, now=T0 + 40)
            tens = energy[nid]["tension"]
            self.assertGreaterEqual(tens, 0.9 * 0.15 - 1e-6,
                                    f"不应衰到 0 (floor 保底), got {tens}")
            self.assertAlmostEqual(tens, 0.9 * 0.15, places=4)

    def test_t8_no_bus_graceful(self):
        with tempfile.TemporaryDirectory() as d:
            nid = make_node_id(KIND_CONCERN, "sir_water")
            w = _mk(d, concerns=_hydration_concern(), bus=None)
            # bus=None → _default_event_bus → 生产无注册时 None → 不衰 (graceful)
            energy = w.compute_energy(set(), {}, {}, now=T0)
            self.assertIn(nid, energy)
            self.assertGreater(energy[nid]["tension"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
