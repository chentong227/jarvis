# -*- coding: utf-8 -*-
"""[口识体-E / 2026-05-31] 强闭环写侧: 识 propose_stance → stance store testcase.

识反思出"我对 Sir/关系的判断" → propose_stance actionable → 写 stance(review, 接地
thought.id) → Sir CLI confirm → active → 透镜投影给口(阻力)。这是强闭环的写入端。
详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §6/§7。

覆盖 (duck-typed thought + 隔离 stance store):
  T1  valid propose_stance (sal>=0.7) → 写 stance(review), about + claim + 接地 thought.id
  T2  低 salience → gated (立场要够分量)
  T3  claim 过短 → rejected
  T4  无 about → 默认 sir_relationship
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_stance
from jarvis_stance import StanceStore, reset_stance_store_for_test, STATE_REVIEW
from jarvis_inner_thought_daemon import InnerThoughtDaemon


def _bare_daemon():
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._bg_log = lambda *a, **k: None
    return d


def _thought(sal=0.8, text="Sir under-rests near deadlines", tid="thought_test_1"):
    return SimpleNamespace(salience=sal, text=text, id=tid)


class TestStanceLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        reset_stance_store_for_test(
            StanceStore(os.path.join(self._tmp.name, "stance.json")))

    def tearDown(self):
        reset_stance_store_for_test(None)
        self._tmp.cleanup()

    def test_t1_valid_propose_stance(self):
        d = _bare_daemon()
        ok, result = d._do_propose_stance(
            _thought(),
            "propose_stance:sir_wellbeing:gentle persistence near deadlines helps more than one-off reminders")
        self.assertTrue(ok, result)
        self.assertIn("stance_proposed", result)
        store = jarvis_stance.get_stance_store()
        rows = store.list(STATE_REVIEW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["about"], "sir_wellbeing")
        self.assertEqual(rows[0]["evidence"][0]["ref"], "thought_test_1")  # 接地

    def test_t2_low_salience_gated(self):
        d = _bare_daemon()
        ok, result = d._do_propose_stance(
            _thought(sal=0.5), "propose_stance:sir_wellbeing:some grounded view here ok")
        self.assertFalse(ok)
        self.assertIn("gated", result)

    def test_t3_short_claim_rejected(self):
        d = _bare_daemon()
        ok, result = d._do_propose_stance(_thought(), "propose_stance:x:short")
        self.assertFalse(ok)
        self.assertIn("too_short", result)

    def test_t4_no_about_defaults(self):
        d = _bare_daemon()
        ok, result = d._do_propose_stance(
            _thought(), "propose_stance:Sir values directness over deference here")
        self.assertTrue(ok, result)
        rows = jarvis_stance.get_stance_store().list(STATE_REVIEW)
        self.assertEqual(rows[0]["about"], "sir_relationship")


if __name__ == "__main__":
    unittest.main(verbosity=2)
