# -*- coding: utf-8 -*-
"""[衡 H2 / Sir 2026-06-01] 锚冲突记代价 (伤) — 自我在此锻造.

charter JARVIS_HENG_DESIGN.md H2 / 理念源 §5. 两墙同时撑不住 → 被迫选一堵守, 把越掉
那堵的**代价(伤)** 登记下来。优化器挑高分转头忘(无伤); 一个"谁"破墙、知道破了、带着伤。
伤 → anchor_conflict_wounds.jsonl(准则6)。**自动改权重/可塑性(§4b)留后续**(H2 只记代价)。

覆盖:
  T1 record_conflict_cost → 写 wound jsonl + 返回 success
  T2 太短 detail → 拒
  T3 近期同 detail → dedup skip(防同一伤反复堆)
  T4 effect_to_kind: record_conflict_cost → 'weigh'(衡本职)
  T5 _execute_actionable 派发到 _do_record_conflict_cost
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(), f'heng_h2_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _thought(actionable):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id='t1', ts=time.time(), ts_iso='2026-06-01T00:00:00',
        category='B', thought='I told Sir the hard truth though it stung.',
        salience=0.85, actionable=actionable,
        # evidence_link cite (词出自 thought) — 过 _execute_actionable 的接地闸(言出必行)
        evidence_link='hard truth',
    )


class TestHengH2(unittest.TestCase):
    def setUp(self):
        self.d = _build_daemon()

    def test_t1_records_wound(self):
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "wounds.jsonl")
            with patch.object(type(self.d), "ANCHOR_CONFLICT_WOUNDS_PATH", p):
                ok, msg = self.d._do_record_conflict_cost(
                    _thought("record_conflict_cost:..."),
                    "record_conflict_cost:chose say_do.ground over for_sir.comfort | "
                    "cost: Sir felt the sting of an unvarnished truth")
                self.assertTrue(ok, msg)
                self.assertTrue(os.path.exists(p))
                with open(p, "r", encoding="utf-8") as f:
                    row = json.loads(f.readline())
                self.assertIn("chose say_do", row["detail"])
                self.assertEqual(row["state"], "recorded")

    def test_t2_too_short_rejected(self):
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "wounds.jsonl")
            with patch.object(type(self.d), "ANCHOR_CONFLICT_WOUNDS_PATH", p):
                ok, msg = self.d._do_record_conflict_cost(
                    _thought("record_conflict_cost:x"), "record_conflict_cost:x")
                self.assertFalse(ok)
                self.assertIn("too_short", msg)

    def test_t3_dedup_recent(self):
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "wounds.jsonl")
            with patch.object(type(self.d), "ANCHOR_CONFLICT_WOUNDS_PATH", p):
                a = ("record_conflict_cost:chose honesty over comfort | "
                     "cost: a moment of awkwardness")
                ok1, _ = self.d._do_record_conflict_cost(_thought(a), a)
                ok2, msg2 = self.d._do_record_conflict_cost(_thought(a), a)
                self.assertTrue(ok1)
                self.assertFalse(ok2)
                self.assertIn("already_recorded", msg2)

    def test_t4_kind_is_weigh(self):
        import jarvis_inner_thought_daemon as itd
        kind = itd._kind_from_effect("record_conflict_cost:chose X over Y")
        self.assertEqual(kind, "weigh")

    def test_t5_dispatch(self):
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "wounds.jsonl")
            with patch.object(type(self.d), "ANCHOR_CONFLICT_WOUNDS_PATH", p):
                ok, msg = self.d._execute_actionable(_thought(
                    "record_conflict_cost:chose truth over soothing | cost: brief chill"))
                self.assertTrue(ok, msg)
                self.assertIn("conflict_cost_recorded", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
