# -*- coding: utf-8 -*-
"""[口识体-F / 2026-05-31] 张力 dyad — 立场↔Sir关心 边 (阻力/老师载体).

设计 (VOICE_AND_MIND §6): 立场 = Jarvis 对某 concern 的坚定 view. 高置信 active stance
about 某 concern → stance 节点与 concern 节点连 dyad 边 (grounded by stance_id) + stance
节点得"立场张力"势能 (Jarvis 持有坚定 view = 可能推开 Sir 的阻力源). 数据驱动: 立场越
多/越坚定 → dyad 越多 → 体在那些区有阻力势能。真冲突 valence 待 Sir-wish 信号成熟。

覆盖 (mock embed, tmp 隔离):
  T1 高置信 active stance about concern → 织 dyad 边 (stance↔concern, grounded stance_id)
  T2 低置信 stance (< min_confidence) → 不织 (不够坚定不算阻力)
  T3 review/retired stance → 不织 (只 active)
  T4 立场张力进 compute_energy (stance 节点 tension↑)
  T5 stance_dyad_enabled=0 → 关闭 (不织不计)
  T6 无 about 的 stance → 不织 (无 concern 锚)
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
    RelationalManifold, make_node_id, KIND_STANCE, KIND_CONCERN,
)
from jarvis_relational_weaver import RelationalWeaver

T0 = 1_780_000_000.0


def _mk(d, stances):
    sp = os.path.join(d, "stance.json")
    cp = os.path.join(d, "concerns.json")
    rp = os.path.join(d, "relational_state.json")
    tp = os.path.join(d, "self_threads.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"stances": stances}, f)
    with open(cp, "w", encoding="utf-8") as f:
        json.dump({"sir_sleep": {"id": "sir_sleep", "what_i_watch": "x",
                                 "severity": 0.1, "state": "active"}}, f)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"inside_jokes": {}, "unspoken_protocols": {}}, f)
    with open(tp, "w", encoding="utf-8") as f:
        json.dump({"threads": []}, f)
    man = RelationalManifold(os.path.join(d, "m.json"))
    w = RelationalWeaver(
        manifold=man, embed_fn=lambda ts: [None] * len(ts),
        threads_path=tp, concerns_path=cp, relational_path=rp,
        vectors_path=os.path.join(d, "v.json"), stance_path=sp,
        energy_path=os.path.join(d, "e.json"), event_bus=None)
    return w, man


def _stance(sid, about, conf, state="active"):
    return {sid: {"stance_id": sid, "claim": "Sir benefits from gentle persistence",
                  "about": about, "confidence": conf, "state": state}}


class TestStanceDyad(unittest.TestCase):
    def test_t1_high_conf_weaves_dyad(self):
        with tempfile.TemporaryDirectory() as d:
            w, man = _mk(d, _stance("st1", "sir_sleep", 0.8))
            n = w.weave_stance_dyads(now=T0)
            self.assertEqual(n, 1)
            sn = make_node_id(KIND_STANCE, "st1")
            cn = make_node_id(KIND_CONCERN, "sir_sleep")
            e = man.get_edge(sn, cn)
            self.assertIsNotNone(e)            # dyad 边存在
            # grounded by stance_id
            refs = [p.get("ref") for p in (e.get("provenance") or [])]
            self.assertIn("st1", refs)

    def test_t2_low_conf_no_dyad(self):
        with tempfile.TemporaryDirectory() as d:
            w, man = _mk(d, _stance("st1", "sir_sleep", 0.3))  # < 0.6
            self.assertEqual(w.weave_stance_dyads(now=T0), 0)

    def test_t3_non_active_no_dyad(self):
        with tempfile.TemporaryDirectory() as d:
            w, _ = _mk(d, _stance("st1", "sir_sleep", 0.9, state="review"))
            self.assertEqual(w.weave_stance_dyads(now=T0), 0)

    def test_t4_dyad_tension_in_energy(self):
        with tempfile.TemporaryDirectory() as d:
            w, _ = _mk(d, _stance("st1", "sir_sleep", 0.8))
            energy = w.compute_energy(set(), {}, {}, now=T0)
            sn = make_node_id(KIND_STANCE, "st1")
            self.assertIn(sn, energy)
            self.assertGreater(energy[sn]["tension"], 0.0)  # 立场张力计入
            self.assertAlmostEqual(energy[sn]["tension"], 0.4 * 0.8, places=6)

    def test_t5_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            w, _ = _mk(d, _stance("st1", "sir_sleep", 0.8))
            w._ecfg = lambda: {"stance_dyad_enabled": 0}
            self.assertEqual(w.weave_stance_dyads(now=T0), 0)
            self.assertEqual(w._stance_dyad_tension_map(), {})

    def test_t6_no_about_no_dyad(self):
        with tempfile.TemporaryDirectory() as d:
            w, _ = _mk(d, _stance("st1", "", 0.9))
            self.assertEqual(w.weave_stance_dyads(now=T0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
