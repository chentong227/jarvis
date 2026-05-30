# -*- coding: utf-8 -*-
"""[Self-Memory P1 / Sir 2026-05-30] 思考脑自我回忆 (recall as an action) 回归.

Sir 真意: "高频思考脑能不能自我迭代自我理解? 随口的记忆/昨天那件事/好久没见."

根因 (已核): 思考脑只 _maybe_archive_to_hippocampus **写**海马, tick 中无召回路径,
只看预塞的 24h 窗口 → 任何"随口的记忆"都得 hand-code 预 push.

P1 治本 (本测覆盖):
  - recall(): 复用 MemoryHub.query 跨 source 召回 (不造新存储); 无 nerve → [] (诚实)
  - build_recall_block(): F3 接地 — 带 [SOURCE] provenance + 允许"模糊记得"禁裸断言
  - <RECALL>query</RECALL> brain-initiated loop: 本 tick 解析 → 召回 → 下 tick 顶注入

决策锚: F1 混合 (后台 tick 自发深召回) / F3 允许模糊记得.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=None,
    )


def _frag(source, content):
    return types.SimpleNamespace(source=source, content=content)


def _mock_nerve_with_memory(fragments):
    nerve = MagicMock()
    nerve.memory_gateway.query = MagicMock(return_value=fragments)
    return nerve


# ============================================================
# P1A — recall() 召回
# ============================================================

class TestP1Recall(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_no_nerve_returns_empty(self):
        """无 nerve + 无河床 → [] (诚实, 不编造)."""
        self.daemon.nerve = None
        # 隔离 self-threads 河床到不存在的 temp, 避免读真 self_threads.json
        import tempfile as _tf
        self.daemon._SELF_THREADS_PATH = os.path.join(
            _tf.mkdtemp(), 'self_threads.json')
        self.assertEqual(self.daemon.recall('anything'), [])

    def test_empty_query_returns_empty(self):
        self.daemon.nerve = _mock_nerve_with_memory([_frag('LTM', 'x')])
        self.assertEqual(self.daemon.recall(''), [])

    def test_recall_returns_candidates_with_source(self):
        """有 nerve + hub → 召回候选带 source provenance."""
        frags = [
            _frag('LTM', "Sir mentioned his cat Mochi has a vet appt Friday"),
            _frag('STM', "earlier Sir asked about the deploy bug"),
        ]
        self.daemon.nerve = _mock_nerve_with_memory(frags)
        out = self.daemon.recall('cat vet', top_k=4)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['source'], 'LTM')
        self.assertIn('Mochi', out[0]['content'])
        # 真调了 hub.query (复用 MemoryHub, 不造新存储)
        self.daemon.nerve.memory_gateway.query.assert_called_once()

    def test_recall_survives_hub_exception(self):
        """hub.query 抛异常 → [] (fail-safe, 不崩 tick)."""
        nerve = MagicMock()
        nerve.memory_gateway.query = MagicMock(side_effect=RuntimeError('boom'))
        self.daemon.nerve = nerve
        self.assertEqual(self.daemon.recall('x'), [])


# ============================================================
# P1B — build_recall_block() F3 接地纪律
# ============================================================

class TestP1RecallBlock(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_empty_results_empty_block(self):
        self.assertEqual(self.daemon.build_recall_block([]), '')

    def test_block_has_source_tags_and_hedge_discipline(self):
        results = [{'source': 'ltm',
                    'content': 'Sir said he sleeps late on weekends'}]
        block = self.daemon.build_recall_block(results, query='sleep')
        self.assertIn('[LTM]', block, "应带 source provenance 标签")
        self.assertIn('Sir said he sleeps late', block)
        # F3 接地红线: 允许模糊记得 + 禁裸断言 + 引准则 5
        self.assertIn('模糊记得', block)
        self.assertIn('准则 5', block)


# ============================================================
# P1C — <RECALL> brain-initiated loop
# ============================================================

class TestP1RecallTag(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()
        self.daemon.nerve = _mock_nerve_with_memory(
            [_frag('LTM', "Sir's vet appt for Mochi is Friday 3pm")]
        )

    def test_recall_tag_sets_pending_block(self):
        raw = ("<CATEGORY>A</CATEGORY><THOUGHT>Something about a pet</THOUGHT>"
               "<SALIENCE>0.5</SALIENCE>"
               "<RECALL>Sir's cat vet appointment</RECALL>")
        self.daemon._handle_recall_tag(raw)
        self.assertTrue(self.daemon._pending_recall_block,
            "<RECALL> 应跑召回并 queue pending block")
        self.assertIn('Mochi', self.daemon._pending_recall_block)

    def test_empty_recall_tag_no_block(self):
        raw = "<THOUGHT>x</THOUGHT><RECALL></RECALL>"
        self.daemon._handle_recall_tag(raw)
        self.assertEqual(self.daemon._pending_recall_block, '')

    def test_no_recall_tag_no_block(self):
        raw = "<THOUGHT>just a normal thought, nothing familiar</THOUGHT>"
        self.daemon._handle_recall_tag(raw)
        self.assertEqual(self.daemon._pending_recall_block, '')

    def test_placeholder_recall_tag_no_block(self):
        raw = "<RECALL>none</RECALL>"
        self.daemon._handle_recall_tag(raw)
        self.assertEqual(self.daemon._pending_recall_block, '')


# ============================================================
# P1D — pending recall block 下 tick prompt 注入
# ============================================================

class TestP1PromptInject(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_pending_block_injected_and_cleared(self):
        self.daemon._pending_recall_block = (
            "=== RECALLED MEMORY __p1_inject_marker__ ===\n  [LTM] foo"
        )
        _system, user = self.daemon._build_prompt(
            sir_state='active',
            evidence={'sir_state': 'active', 'idle_seconds': 10, 'hour': 14},
        )
        self.assertIn('__p1_inject_marker__', user,
            "上 tick 召回结果应注入本 tick prompt")
        self.assertEqual(self.daemon._pending_recall_block, '',
            "注入后应清空 (consumed)")

    def test_no_pending_block_no_injection(self):
        self.daemon._pending_recall_block = ''
        _system, user = self.daemon._build_prompt(
            sir_state='active',
            evidence={'sir_state': 'active', 'idle_seconds': 10, 'hour': 14},
        )
        self.assertNotIn('RECALLED MEMORY', user)


# ============================================================
# P1E — prompt FORMAT 含 <RECALL> tag 说明
# ============================================================

class TestP1PromptFormatHasRecall(unittest.TestCase):
    def test_system_prompt_offers_recall_tag(self):
        daemon = _make_daemon()
        system, _user = daemon._build_prompt(
            sir_state='active',
            evidence={'sir_state': 'active', 'idle_seconds': 10, 'hour': 14},
        )
        self.assertIn('<RECALL>', system,
            "FORMAT 应给思考脑 <RECALL> 自查记忆能力")


if __name__ == '__main__':
    unittest.main(verbosity=2)
