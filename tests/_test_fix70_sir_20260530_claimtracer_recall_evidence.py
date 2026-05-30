# -*- coding: utf-8 -*-
"""[言出必行 I1 / Sir 2026-05-30] ClaimTracer 接 Self-Memory 召回底座作 evidence 源.

Sir 真意: "做完把言出必行也解决掉." 我核 ClaimTracer 真因: ④Recall/③State claim
("你昨天提过 X / 我们讨论过") evidence 源只 tool_results / STM 末 10 / system_clock /
promise tag — **没有真索引可命中** → 假阳性 (真说过却报 unverified). 治本 (本设计核心):
把 P0-P4 的 Self-Memory 召回底座 (MemoryHub + self-threads + self-notes, 带 provenance)
作为 evidence 源 — recall_provider fallback. 准则 5 接地 + 准则 1 (仅 unverified 才触发).

测试覆盖:
  I1A _try_recall_match: 词重叠命中/不命中/无 provider
  I1B trace_to_evidence: recall fallback verify (有/无 provider 对比, 老行为不变)
  I1C trace_reply: 召回可 verify 否则 unverified 的 claim (假阳性消除)
  I1D 向后兼容: 不传 recall_provider 老 caller 零影响
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_claim_tracer import (  # noqa: E402
    Claim, trace_to_evidence, trace_reply, _try_recall_match,
)


class TestI1ARecallMatch(unittest.TestCase):
    def test_overlap_hit(self):
        c = Claim('quote', 'you mentioned the vet appointment')
        prov = lambda q: [{'source': 'NOTE',
                           'content': "Sir's cat vet appointment is Friday"}]
        self.assertTrue(_try_recall_match(c, prov))
        self.assertEqual(c.trace_to, 'recall')
        self.assertIn('vet', c.trace_what)

    def test_no_overlap(self):
        c = Claim('quote', 'you mentioned the vet appointment')
        prov = lambda q: [{'source': 'LTM', 'content': "unrelated grocery list"}]
        self.assertFalse(_try_recall_match(c, prov))

    def test_no_provider(self):
        c = Claim('quote', 'whatever')
        self.assertFalse(_try_recall_match(c, None))

    def test_provider_raises_safe(self):
        c = Claim('quote', 'the vet appointment thing')
        def boom(q):
            raise RuntimeError('x')
        self.assertFalse(_try_recall_match(c, boom))


class TestI1BTraceToEvidence(unittest.TestCase):
    def test_recall_fallback_verifies(self):
        """正常路径 (legacy, 空 tool/stm) 未命中 → recall fallback verify."""
        c = Claim('quote', 'you noted the database migration plan')
        prov = lambda q: [{'source': 'THREAD',
                           'content': "the database migration plan is on hold"}]
        ok = trace_to_evidence(c, [], [], use_vocab=False,
                               recall_provider=prov)
        self.assertTrue(ok)
        self.assertEqual(c.trace_to, 'recall')

    def test_no_provider_unverified(self):
        """不传 provider → 老行为: 无 evidence → unverified (False)."""
        c = Claim('quote', 'you noted the database migration plan')
        ok = trace_to_evidence(c, [], [], use_vocab=False)
        self.assertFalse(ok)

    def test_normal_evidence_still_wins_without_recall(self):
        """tool_results 有命中 → 正常 verify, 不依赖 recall."""
        c = Claim('past_action', 'opened dashboard')
        ok = trace_to_evidence(c, ['✅ opened dashboard'], [],
                               use_vocab=False)
        self.assertTrue(ok)


class TestI1CTraceReply(unittest.TestCase):
    def test_recall_removes_false_positive(self):
        reply = 'you mentioned "the vet appointment on Friday", Sir.'
        prov = lambda q: [{'source': 'NOTE',
                           'content': "Sir's cat vet appointment is Friday 3pm"}]
        # 无 recall → unverified (假阳性)
        r0 = trace_reply(reply, tool_results=[], stm_recent=[],
                         include_swm_tool_called=False)
        self.assertGreaterEqual(r0['n_unverified'], 1)
        # 有 recall → verified (假阳性消除)
        r1 = trace_reply(reply, tool_results=[], stm_recent=[],
                         include_swm_tool_called=False, recall_provider=prov)
        self.assertEqual(r1['n_unverified'], 0,
            "召回命中真记忆 → ④Recall claim 该 verified, 不再假阳性")


class TestI1DBackwardCompat(unittest.TestCase):
    def test_old_caller_unaffected(self):
        """老 caller (不传 recall_provider) 正常工作."""
        reply = "The CPU is at 87% right now."
        r = trace_reply(reply, tool_results=['✅ cpu 87%'], stm_recent=[],
                        include_swm_tool_called=False)
        self.assertIn('n_claims', r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
