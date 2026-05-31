# -*- coding: utf-8 -*-
"""[口识体-C / 2026-05-31] nudge 群退化 publish→体能量: 闭感知环 testcase.

nudge/care 警报 (wellness/proactive) 不再直推 __NUDGE__, 退化为体的 tension 能量:
SWM 近期 nudge 类 signal → 映射到相关 concern node 的张力 → 识经 body_delta attend。
"一个 wellness 警报 = 体的张力"。详 docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md §4 closure C.

覆盖 (fake bus 注入, tmp 隔离):
  T1  注入 proactive_care_advice → 对应 concern 张力↑ → body_delta (kind=tension)  ★做完标准
  T2  unknown concern 警报 → 不计 (不造幻影能量, 准则 5 全接地)
  T3  soul_alignment_advice missed_concern_ids → missed concern 张力 (Jarvis 漏掉=张力)
  T4  storm: 同 concern 多警报 → 张力封顶 nudge_tension_cap (防膨胀)
  T5  nudge_tension_enabled=0 → 退化关闭, 不计 nudge 张力
  T6  salience 加权: 高 salience 警报 → 更高张力 (接地于 event 重要度)
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
    RelationalManifold, make_node_id, KIND_CONCERN,
)
from jarvis_relational_weaver import RelationalWeaver

T0 = 1_780_000_000.0


class _FakeBus:
    """SWM 替身: recent_events 按 type 过滤 (忽略时间, 测试确定性)。"""
    def __init__(self, events=None):
        self.events = list(events or [])

    def recent_events(self, within_seconds=None, types=None):
        return [e for e in self.events
                if types is None or e.get("type") in types]

    def publish(self, *a, **k):
        return None


def _evt(etype, *, salience=0.6, **meta):
    return {"type": etype, "metadata": dict(meta), "salience": salience,
            "timestamp": T0, "ttl": 600.0}


def _mk(d, *, concerns=None, stances=None, events=None):
    cp = os.path.join(d, "concerns.json")
    rp = os.path.join(d, "relational_state.json")
    sp = os.path.join(d, "stance.json")
    tp = os.path.join(d, "self_threads.json")
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(concerns or {}, f)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"inside_jokes": {}, "unspoken_protocols": {}}, f)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"stances": stances or {}}, f)
    with open(tp, "w", encoding="utf-8") as f:
        json.dump({"threads": []}, f)
    man = RelationalManifold(os.path.join(d, "manifold.json"))
    return RelationalWeaver(
        manifold=man, threads_path=tp, concerns_path=cp, relational_path=rp,
        vectors_path=os.path.join(d, "vec.json"), stance_path=sp,
        energy_path=os.path.join(d, "energy.json"),
        event_bus=_FakeBus(events or []))


# 低 severity (< tension_severity_min 0.40) → 无 severity 张力, 隔离出 nudge 张力
def _concern(cid, sev=0.1):
    return {cid: {"id": cid, "what_i_watch": f"watch {cid}",
                  "why_i_care": "care", "severity": sev, "state": "active"}}


class TestNudgeEnergy(unittest.TestCase):
    def test_t1_care_advice_to_tension_delta(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk(d, concerns=_concern("sir_sleep"),
                    events=[_evt("proactive_care_advice", salience=0.7,
                                 concern_id="sir_sleep")])
            energy = w.compute_energy(set(), {}, {}, now=T0)
            nid = make_node_id(KIND_CONCERN, "sir_sleep")
            self.assertAlmostEqual(energy[nid]["tension"], 0.35, places=6)  # 0.5*0.7
            self.assertGreater(energy[nid]["total"], 0.0)
            # 做完标准: 能量↑ → body_delta (kind=tension)
            deltas = w._diff_and_emit_deltas(energy, T0)
            tens = [x for x in deltas if x["node"] == nid and x["kind"] == "tension"]
            self.assertTrue(tens, "nudge 警报应让 concern 升张力 → body_delta")

    def test_t2_unknown_concern_no_phantom(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk(d, concerns=_concern("sir_sleep"),
                    events=[_evt("proactive_care_advice", concern_id="not_a_concern")])
            energy = w.compute_energy(set(), {}, {}, now=T0)
            # 体里没这个 concern node → 不造幻影能量
            self.assertNotIn(make_node_id(KIND_CONCERN, "not_a_concern"), energy)

    def test_t3_soul_alignment_missed_concerns(self):
        with tempfile.TemporaryDirectory() as d:
            concerns = {}
            concerns.update(_concern("sir_sleep"))
            concerns.update(_concern("sir_water"))
            w = _mk(d, concerns=concerns,
                    events=[_evt("soul_alignment_advice", salience=0.5,
                                 missed_concern_ids=["sir_sleep", "sir_water"])])
            energy = w.compute_energy(set(), {}, {}, now=T0)
            for cid in ("sir_sleep", "sir_water"):
                nid = make_node_id(KIND_CONCERN, cid)
                self.assertAlmostEqual(energy[nid]["tension"], 0.25, places=6)  # 0.5*0.5

    def test_t4_storm_capped(self):
        with tempfile.TemporaryDirectory() as d:
            events = [_evt("care_signal_derived", salience=1.0, concern_id="sir_sleep")
                      for _ in range(10)]  # 10*0.5 = 5.0 未封顶
            w = _mk(d, concerns=_concern("sir_sleep"), events=events)
            energy = w.compute_energy(set(), {}, {}, now=T0)
            nid = make_node_id(KIND_CONCERN, "sir_sleep")
            self.assertAlmostEqual(energy[nid]["tension"], 1.5, places=6)  # cap

    def test_t5_disabled_flag(self):
        with tempfile.TemporaryDirectory() as d:
            w = _mk(d, concerns=_concern("sir_sleep"),
                    events=[_evt("proactive_care_advice", concern_id="sir_sleep")])
            w._ecfg = lambda: {"nudge_tension_enabled": 0,
                               "nudge_tension_etypes": ["proactive_care_advice"]}
            self.assertEqual(w._nudge_tension_map({make_node_id(KIND_CONCERN, "sir_sleep")},
                                                  now=T0), {})

    def test_t6_salience_weighted(self):
        with tempfile.TemporaryDirectory() as d:
            w_hi = _mk(d, concerns=_concern("sir_sleep"),
                       events=[_evt("proactive_care_advice", salience=0.9,
                                    concern_id="sir_sleep")])
            nid = make_node_id(KIND_CONCERN, "sir_sleep")
            hi = w_hi._nudge_tension_map({nid}, now=T0)[nid]
        with tempfile.TemporaryDirectory() as d2:
            w_lo = _mk(d2, concerns=_concern("sir_sleep"),
                       events=[_evt("proactive_care_advice", salience=0.3,
                                    concern_id="sir_sleep")])
            lo = w_lo._nudge_tension_map({nid}, now=T0)[nid]
        self.assertGreater(hi, lo)  # 高 salience 警报 → 更高张力 (接地)


if __name__ == "__main__":
    unittest.main(verbosity=2)
