# -*- coding: utf-8 -*-
"""[口识体-B / 2026-05-31] 言出必行用体作 evidence 源: 闭验证环 testcase.

体(stance/节点)是 Jarvis 接地的关系结构。说的关系类 claim 若被体 active stance 或体
节点支持 → **不该判 unverified** (验证环穿体)。仿 recall_provider 加 body_evidence_provider。
详 docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md §4 closure B.

覆盖 (无 LLM, 隔离 provider + 隔离 body 单例):
  B1  _try_body_match: 词重叠命中(trace_to='body') / 不命中 / 无 provider / 异常安全
  B2  trace_to_evidence: body fallback verify; 不传→老行为 unverified; 正常 evidence 仍优先
  B3  trace_reply: 被体 stance 支持的关系 claim 不再 unverified (★做完标准)
  B4  向后兼容: 不传 body_evidence_provider 老 caller 零影响
  B5  默认 provider body_claim_evidence: 返回 active stance + 体节点证据 (接地)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_claim_tracer import (  # noqa: E402
    Claim, trace_to_evidence, trace_reply, _try_body_match,
)
from jarvis_relational_manifold import (  # noqa: E402
    RelationalManifold, make_node_id, KIND_CONCERN,
)
from jarvis_relational_lens import (  # noqa: E402
    RelationalLens, reset_lens_for_test, body_claim_evidence,
)
from jarvis_stance import (  # noqa: E402
    StanceStore, reset_stance_store_for_test, STATE_ACTIVE,
)


class TestB1BodyMatch(unittest.TestCase):
    def test_overlap_hit(self):
        c = Claim('quote', 'you tend to skip rest near deadlines')
        prov = lambda q: [{'source': 'stance:s1',
                           'content': "Sir tends to skip rest near deadlines"}]
        self.assertTrue(_try_body_match(c, prov))
        self.assertEqual(c.trace_to, 'body')
        self.assertIn('rest', c.trace_what)

    def test_no_overlap(self):
        c = Claim('quote', 'you tend to skip rest near deadlines')
        prov = lambda q: [{'source': 'stance:s1', 'content': "unrelated grocery list"}]
        self.assertFalse(_try_body_match(c, prov))

    def test_no_provider(self):
        self.assertFalse(_try_body_match(Claim('quote', 'whatever'), None))

    def test_provider_raises_safe(self):
        def boom(q):
            raise RuntimeError('x')
        self.assertFalse(_try_body_match(Claim('quote', 'the deadline rest thing'), boom))


class TestB2TraceToEvidence(unittest.TestCase):
    def test_body_fallback_verifies(self):
        c = Claim('quote', 'you noted the database migration plan')
        prov = lambda q: [{'source': 'stance:s1',
                           'content': "the database migration plan is on hold"}]
        ok = trace_to_evidence(c, [], [], use_vocab=False, body_evidence_provider=prov)
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'body')

    def test_no_provider_unverified(self):
        c = Claim('quote', 'you noted the database migration plan')
        self.assertFalse(trace_to_evidence(c, [], [], use_vocab=False))

    def test_normal_evidence_wins_without_body(self):
        c = Claim('past_action', 'opened dashboard')
        self.assertTrue(trace_to_evidence(c, ['✅ opened dashboard'], [], use_vocab=False))


class TestB3TraceReplyBodyStance(unittest.TestCase):
    """★做完标准: 被体 stance 支持的关系 claim 不被判 unverified."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        st = StanceStore(os.path.join(self._tmp.name, "stance.json"))
        st.add_stance("the database migration plan is on hold this week",
                      "sir_work", evidence_kind="thought", evidence_ref="t1",
                      confidence=0.8, state=STATE_ACTIVE)
        reset_stance_store_for_test(st)
        man = RelationalManifold(os.path.join(self._tmp.name, "m.json"))
        reset_lens_for_test(RelationalLens(manifold=man, stance_store=st,
                                           text_provider=lambda: {}))

    def tearDown(self):
        reset_stance_store_for_test(None)
        reset_lens_for_test(None)
        self._tmp.cleanup()

    def test_body_stance_removes_false_positive(self):
        reply = 'you noted "the database migration plan", Sir.'
        r0 = trace_reply(reply, tool_results=[], stm_recent=[],
                         include_swm_tool_called=False)
        self.assertGreaterEqual(r0['n_unverified'], 1)  # 无体 → 假阳性
        prov = lambda q: body_claim_evidence(q)
        r1 = trace_reply(reply, tool_results=[], stm_recent=[],
                         include_swm_tool_called=False, body_evidence_provider=prov)
        self.assertEqual(r1['n_unverified'], 0,
                         "被体 stance 支持的关系 claim 应 verified, 不再假阳性")


class TestB4BackwardCompat(unittest.TestCase):
    def test_old_caller_unaffected(self):
        r = trace_reply("The CPU is at 87% right now.", tool_results=['✅ cpu 87%'],
                        stm_recent=[], include_swm_tool_called=False)
        self.assertIn('n_claims', r)


class TestB5DefaultBodyProvider(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        st = StanceStore(os.path.join(self._tmp.name, "stance.json"))
        st.add_stance("Sir tends to skip rest near deadlines", "sir_wellbeing",
                      evidence_kind="thought", evidence_ref="t1",
                      confidence=0.8, state=STATE_ACTIVE)
        # 低置信 active 不该进 (< stance_min_conf 0.4)
        st.add_stance("a low confidence noisy view about something else", "x",
                      evidence_kind="thought", evidence_ref="t2",
                      confidence=0.2, state=STATE_ACTIVE)
        reset_stance_store_for_test(st)
        man = RelationalManifold(os.path.join(self._tmp.name, "m.json"))
        node = make_node_id(KIND_CONCERN, "sir_sleep")
        reset_lens_for_test(RelationalLens(
            manifold=man, stance_store=st,
            text_provider=lambda: {node: "Sir 连续熬夜风险 sleep deadline"}))

    def tearDown(self):
        reset_stance_store_for_test(None)
        reset_lens_for_test(None)
        self._tmp.cleanup()

    def test_returns_stance_evidence(self):
        ev = body_claim_evidence("you skip rest near deadlines")
        contents = [e["content"] for e in ev]
        self.assertTrue(any("skip rest" in c for c in contents),
                        "active 高置信 stance 应作体证据")
        self.assertFalse(any("low confidence noisy" in c for c in contents),
                         "低置信 stance 不该进体证据")

    def test_returns_node_text_evidence_on_overlap(self):
        ev = body_claim_evidence("sleep deadline risk")
        contents = [e["content"] for e in ev]
        self.assertTrue(any("连续熬夜" in c for c in contents),
                        "词重叠的体节点文本应作证据")


if __name__ == "__main__":
    unittest.main(verbosity=2)
