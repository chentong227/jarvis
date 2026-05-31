# -*- coding: utf-8 -*-
"""[体-P4 / 2026-05-31] 立场 Stance store testcase.

立场 = Jarvis 自己对 Sir/关系的接地 view (阻力/老师感载体)。
详 docs/JARVIS_TRINITY_ARCHITECTURE.md §3.

覆盖 (接地红线 + Sir 元否决):
  T1  add_stance: review 默认 + evidence 接地
  T2  **接地红线**: 无 evidence_ref → 拒
  T3  reinforce: outcome 闭环上调置信 + 加 evidence + 去顶
  T4  weaken: 反例削弱; 跌破 0.15 自动转 review
  T5  Sir confirm (准则 7): → active + 高置信 + source=sir_confirmed
  T6  Sir retire (准则 7): → retired + sir_reverted + reason
  T7  list_for_lens: 只返高置信 active (透镜保形用)
  T8  持久化往返
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_stance import StanceStore, STATE_ACTIVE, STATE_REVIEW, STATE_RETIRED

T0 = 1_780_000_000.0


def _mk(d):
    return StanceStore(os.path.join(d, "stance.json"))


class TestStance(unittest.TestCase):
    def test_t1_add_review_grounded(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            sid = st.add_stance(
                "Sir 截止日临近时易牺牲休息, 温和坚持比一次性提醒有效",
                "sir_wellbeing", evidence_kind="thought",
                evidence_ref="thought_20260531_1", detail="连续 3 晚熬夜后感谢轻推",
                confidence=0.6, now=T0)
            self.assertIsNotNone(sid)
            s = st.get(sid)
            self.assertEqual(s["state"], STATE_REVIEW)  # propose-not-trust
            self.assertEqual(len(s["evidence"]), 1)
            self.assertEqual(s["evidence"][0]["ref"], "thought_20260531_1")

    def test_t2_reject_ungrounded(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            self.assertIsNone(st.add_stance(
                "无证据的立场", "x", evidence_kind="thought",
                evidence_ref="", now=T0))
            self.assertEqual(st.stats()["total"], 0)

    def test_t3_reinforce(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            sid = st.add_stance("c", "a", evidence_kind="thought",
                                evidence_ref="t1", confidence=0.5, now=T0)
            ok = st.reinforce(sid, evidence_kind="outcome", evidence_ref="turn_9",
                              detail="Sir 采纳", delta=0.2, now=T0)
            self.assertTrue(ok)
            s = st.get(sid)
            self.assertAlmostEqual(s["confidence"], 0.7, places=4)
            self.assertEqual(len(s["evidence"]), 2)
            self.assertEqual(s["reinforce_count"], 2)
            # reinforce 无 ref → 拒
            self.assertFalse(st.reinforce(sid, evidence_kind="x", evidence_ref=""))

    def test_t4_weaken_demotes(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            sid = st.add_stance("c", "a", evidence_kind="thought",
                                evidence_ref="t1", confidence=0.25,
                                state=STATE_ACTIVE, now=T0)
            st.weaken(sid, delta=0.15, reason="Sir 反例", now=T0)
            s = st.get(sid)
            self.assertAlmostEqual(s["confidence"], 0.10, places=4)
            self.assertEqual(s["state"], STATE_REVIEW)  # 跌破 0.15 自动降级

    def test_t5_sir_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            sid = st.add_stance("c", "a", evidence_kind="thought",
                                evidence_ref="t1", confidence=0.5, now=T0)
            self.assertTrue(st.confirm(sid))
            s = st.get(sid)
            self.assertEqual(s["state"], STATE_ACTIVE)
            self.assertEqual(s["source"], "sir_confirmed")
            self.assertGreaterEqual(s["confidence"], 0.85)

    def test_t6_sir_retire(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            sid = st.add_stance("c", "a", evidence_kind="thought",
                                evidence_ref="t1", state=STATE_ACTIVE, now=T0)
            self.assertTrue(st.retire(sid, reason="过时了"))
            s = st.get(sid)
            self.assertEqual(s["state"], STATE_RETIRED)
            self.assertTrue(s["sir_reverted"])
            self.assertEqual(s["retire_reason"], "过时了")

    def test_t7_list_for_lens(self):
        with tempfile.TemporaryDirectory() as d:
            st = _mk(d)
            hi = st.add_stance("high", "a", evidence_kind="t", evidence_ref="t1",
                               confidence=0.8, state=STATE_ACTIVE, now=T0)
            st.add_stance("low", "a", evidence_kind="t", evidence_ref="t2",
                          confidence=0.3, state=STATE_ACTIVE, now=T0)
            st.add_stance("rev", "a", evidence_kind="t", evidence_ref="t3",
                          confidence=0.9, state=STATE_REVIEW, now=T0)  # review 不算
            lens = st.list_for_lens(min_confidence=0.5)
            ids = [s["stance_id"] for s in lens]
            self.assertIn(hi, ids)
            self.assertEqual(len(lens), 1)  # 只高置信 active

    def test_t8_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stance.json")
            st1 = StanceStore(path)
            sid = st1.add_stance("persist me", "a", evidence_kind="t",
                                 evidence_ref="t1", now=T0)
            st2 = StanceStore(path)
            self.assertIsNotNone(st2.get(sid))
            self.assertEqual(st2.stats()["total"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
