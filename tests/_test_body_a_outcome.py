# -*- coding: utf-8 -*-
"""[口识体-A / 2026-05-31] outcome→stance: 闭学习环后半 testcase.

Sir 对回复的反应(engaged/rejected) → reinforce/weaken 当轮透镜投影过的 stance:
  (1) lens.project(turn_id=...) 记录本轮真正投影进 prompt 的 stance_id;
  (2) apply_reaction_outcome(turn_id, reaction): engaged 强化 / rejected 削弱。
详 docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md §4 closure A.

覆盖 (无 LLM, tmp 隔离):
  T1  project(turn_id) 记录投影过的 stance_id; projected_stances_for 取回
  T2  engaged → reinforce(+0.1, evidence=outcome/turn_id) → confidence↑ + 加 evidence
  T3  rejected → weaken(0.15) → confidence↓; 跌破 0.15 且 active → 转 review
  T4  ignored / 未知 reaction → no-op (不动 stance)
  T5  无投影记录的 turn → apply no-op (透镜没投 stance / turn 不匹配)
  T6  apply 后 consume → 重复 apply 不二次改 (幂等)
  T7  chat_bypass 接线 (静态 grep: 调 apply_reaction_outcome)
"""
from __future__ import annotations

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
from jarvis_relational_lens import RelationalLens
from jarvis_stance import StanceStore, STATE_ACTIVE, STATE_REVIEW

T0 = 1_780_000_000.0


def _seed(d):
    """小流形 + 文本 (让 default_seeds/relevance 有料)。"""
    m = RelationalManifold(os.path.join(d, "manifold.json"))
    sleep = make_node_id(KIND_CONCERN, "sir_sleep")
    pomo = make_node_id(KIND_CONCERN, "sir_pomodoro")
    thread = make_node_id(KIND_THREAD, "th1")
    m.observe_explicit_link(sleep, pomo, "turn_1", now=T0)
    m.observe_cooccurrence([pomo, thread], "turn_1", now=T0)
    text = {sleep: "Sir 连续熬夜风险", pomo: "Sir 番茄钟工作节奏",
            thread: "Sir 在赶 interview 准备"}
    return m, text, sleep, pomo, thread


def _lens_with_stance(d, *, claim, conf, state):
    m, text, sleep, pomo, thread = _seed(d)
    st = StanceStore(os.path.join(d, "stance.json"))
    sid = st.add_stance(claim, "sir_wellbeing", evidence_kind="thought",
                        evidence_ref="t1", confidence=conf, state=state, now=T0)
    lens = RelationalLens(manifold=m, stance_store=st, text_provider=lambda: text)
    return lens, st, sid, sleep


class TestOutcomeToStance(unittest.TestCase):
    def test_t1_project_records_projected_stance(self):
        with tempfile.TemporaryDirectory() as d:
            lens, st, sid, sleep = _lens_with_stance(
                d, claim="Sir 截止日临近易牺牲休息, 温和坚持有效",
                conf=0.8, state=STATE_ACTIVE)
            block = lens.project([sleep], turn_id="turn_A", now=T0)
            self.assertIn("My read", block)
            self.assertEqual(lens.projected_stances_for("turn_A", now=T0), [sid])
            # 没投影的 turn → 空
            self.assertEqual(lens.projected_stances_for("turn_other", now=T0), [])

    def test_t2_engaged_reinforces(self):
        with tempfile.TemporaryDirectory() as d:
            lens, st, sid, sleep = _lens_with_stance(
                d, claim="温和坚持比一次性提醒更有效果一些", conf=0.8,
                state=STATE_ACTIVE)
            lens.project([sleep], turn_id="turn_A", now=T0)
            ev_before = len(st.get(sid)["evidence"])
            n = lens.apply_reaction_outcome("turn_A", "engaged", now=T0)
            self.assertEqual(n, 1)
            s = st.get(sid)
            self.assertAlmostEqual(s["confidence"], 0.9, places=6)   # 0.8 + 0.1
            self.assertEqual(s["evidence"][-1]["kind"], "outcome")    # 接地
            self.assertEqual(s["evidence"][-1]["ref"], "turn_A")
            self.assertEqual(len(s["evidence"]), ev_before + 1)

    def test_t3_rejected_weakens_below_floor_to_review(self):
        with tempfile.TemporaryDirectory() as d:
            # 低置信 active 立场, 投影需放宽 stance_min_conf 才进 block
            lens, st, sid, sleep = _lens_with_stance(
                d, claim="Sir 此刻最好别被打扰这件事我比较确定", conf=0.2,
                state=STATE_ACTIVE)
            lens.project([sleep], turn_id="turn_R", stance_min_conf=0.1, now=T0)
            self.assertEqual(lens.projected_stances_for("turn_R", now=T0), [sid])
            n = lens.apply_reaction_outcome("turn_R", "rejected", now=T0)
            self.assertEqual(n, 1)
            s = st.get(sid)
            self.assertAlmostEqual(s["confidence"], 0.05, places=6)   # 0.2 - 0.15
            self.assertEqual(s["state"], STATE_REVIEW)                # 跌破 0.15 转 review
            self.assertIn("sir rejected", s.get("last_weaken_reason", ""))

    def test_t4_ignored_or_unknown_noop(self):
        with tempfile.TemporaryDirectory() as d:
            lens, st, sid, sleep = _lens_with_stance(
                d, claim="某条够分量的接地立场放这里测一下", conf=0.7,
                state=STATE_ACTIVE)
            lens.project([sleep], turn_id="turn_A", now=T0)
            self.assertEqual(lens.apply_reaction_outcome("turn_A", "ignored", now=T0), 0)
            self.assertEqual(lens.apply_reaction_outcome("turn_A", "", now=T0), 0)
            self.assertAlmostEqual(st.get(sid)["confidence"], 0.7, places=6)  # 没动

    def test_t5_no_projection_record_noop(self):
        with tempfile.TemporaryDirectory() as d:
            # 透镜不带 stance (stance_store=False) → 投影无 stance → 无记录
            m, text, sleep, pomo, thread = _seed(d)
            lens = RelationalLens(manifold=m, stance_store=False,
                                  text_provider=lambda: text)
            block = lens.project([sleep], turn_id="turn_X", now=T0)
            self.assertTrue(block)  # 有 relevance 内容
            self.assertEqual(lens.projected_stances_for("turn_X", now=T0), [])
            self.assertEqual(lens.apply_reaction_outcome("turn_X", "engaged", now=T0), 0)

    def test_t6_idempotent_consume(self):
        with tempfile.TemporaryDirectory() as d:
            lens, st, sid, sleep = _lens_with_stance(
                d, claim="温和坚持比一次性提醒更有效果一些", conf=0.6,
                state=STATE_ACTIVE)
            lens.project([sleep], turn_id="turn_A", now=T0)
            self.assertEqual(lens.apply_reaction_outcome("turn_A", "engaged", now=T0), 1)
            # 第二次 apply: 记录已 consume → 0, 置信不再二次升
            self.assertEqual(lens.apply_reaction_outcome("turn_A", "engaged", now=T0), 0)
            self.assertAlmostEqual(st.get(sid)["confidence"], 0.7, places=6)  # 仅 +0.1 一次

    def test_t7_chat_bypass_wired(self):
        # 静态守护: chat_bypass meta_feedback 处接了 outcome→stance
        with open(os.path.join(ROOT, "jarvis_chat_bypass.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("apply_reaction_outcome", src)
        self.assertIn("_pending_turn_ids", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
