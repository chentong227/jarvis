# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 19:14 真痛 anchor] 让思考真生效 — 4 修治本回归测试.

Sir 真痛链 (3 question):
  Q1: "为什么 3 分钟才思考一次? 是冷却吗?"
       → BUG 1 fix 副作用: _has_active_rest_commitment 误判 sleep → tick 1800s
  Q2: "他说我工作一下午是不是幻觉?"
       → ClaimTracer 看到 unverified=5/5 但 SmartNudge 路径没 block
  Q3: "还在提醒? 这个 BUG 没修吗?"
       → PromiseLog 重复 register: p_543b5902 hard + p_56cbff2b commitment 同 desc,
          fulfill 一个没 mark dup → reload 又 fire
  Q4 (元否决): "怎么我看你的思考链里一堆硬编码? 30+ sensor 矩阵都没用?"
       → BUG 1 fix 用 hardcode vocab 是反例, 必须删
  Q5 (dashboard): "修复完刚才的问题, 这些都没自动拍板?"
       → AutoArbiter prompt "必须<0.7" 硬规 + threshold 0.75/0.80 → 大量 defer_to_sir

4 修治本 (准则 6 + 8):
  FIX 1 (Q1+Q4): jarvis_inner_thought_daemon — 删 hardcode vocab + 用 SirStatusTracker + idle 短路
  FIX 2 (Q3): jarvis_promise_log mark_fulfilled — dedup 同 desc pending 全 mark
  FIX 3 (Q5-A): jarvis_auto_arbiter — 删 prompt "必须<0.7" 硬规
  FIX 4 (Q5-B): memory_pool/auto_arbiter_calibration.json — threshold 0.75→0.65 (joke/thread), 0.80→0.70 (protocol)
  FIX 5 (Q5-C): jarvis_relational.to_prompt_block — 加 [PENDING REVIEW] block + confirm_pending_review tool

测试覆盖 (16 testcase):
  P1-P3 PromiseLog dedup (单条 / 多 dup / 不同 desc 不 affect)
  R1-R4 [PENDING REVIEW] block (含 jokes / 含 protocols / 空 / id 显示)
  T1-T3 confirm_pending_review tool (activate / reject / 不存在 id)
  A1-A2 AutoArbiter prompt (删硬规 / fallback 描述存在)
  A3-A4 calibration (新 baseline 0.65 / 0.70)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# P1-P3: PromiseLog.mark_fulfilled dedup (Q3 治本)
# ==========================================================================
class TestPromiseLogMarkFulfilledDedup(unittest.TestCase):
    def setUp(self):
        from jarvis_promise_log import PromiseExecutionLog
        self.tmp = tempfile.mkdtemp(prefix='plog_dedup_')
        self.plog = PromiseExecutionLog(
            persist_path=os.path.join(self.tmp, 'p.jsonl')
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_p1_dedup_same_desc_marks_all(self):
        """同 desc 注册 2 个 promise, fulfill 一个 → 另一个 dup 也 fulfilled.

        注: register 已 dedup desc+deadline_str+age<1h. Sir 真实 BUG (p_543b5902/
        p_56cbff2b 同 desc) 可能因不同 deadline_str (different parse path) 没
        register dedup. 这里用不同 deadline_str 模拟真 BUG 场景.
        """
        desc = "I shall remain on standby and wake you"
        p1 = self.plog.register(
            description=desc, kind='hard', deadline_str='13:30'
        )
        p2 = self.plog.register(
            description=desc, kind='commitment',
            deadline_str='2026-05-26 13:30:00'  # 不同 deadline_str
        )
        # 2 个都 pending (deadline_str 不同 → register 没 dedup)
        self.assertEqual(len(self.plog.list_pending()), 2,
            'register dedup 仅看 deadline_str 相同, 不同 str 算 2 条')
        # fulfill p1 → p2 应自动 dup mark (我加的 mark_fulfilled dedup, 看 desc only)
        ok = self.plog.mark_fulfilled(p1, 'sir_voice', 'Sir 说做完了')
        self.assertTrue(ok)
        pending = self.plog.list_pending()
        self.assertEqual(len(pending), 0,
            'fulfill p1 后 dup p2 应自动 mark fulfilled (Q3 治本)')
        # 两个 promise state 都 fulfilled
        self.assertEqual(self.plog.promises[p1].state, 'fulfilled')
        self.assertEqual(self.plog.promises[p2].state, 'fulfilled')

    def test_p2_different_desc_not_affected(self):
        """不同 desc promise → fulfill 一个不影响别的."""
        p1 = self.plog.register(
            description='wake me at 13:30', kind='hard',
            deadline_str='13:30'
        )
        p2 = self.plog.register(
            description='remind about meeting', kind='commitment',
            deadline_str='14:00'
        )
        ok = self.plog.mark_fulfilled(p1, 'sir_voice', 'done')
        self.assertTrue(ok)
        self.assertEqual(self.plog.promises[p1].state, 'fulfilled')
        self.assertEqual(self.plog.promises[p2].state, 'pending',
            '不同 desc promise 不该被影响')

    def test_p3_case_insensitive_strip_dedup(self):
        """desc lowercase + strip 后相同 → 同 dup."""
        p1 = self.plog.register(
            description='Wake Up Sir',
            kind='hard', deadline_str='13:30'
        )
        p2 = self.plog.register(
            description='  WAKE UP SIR  ',  # whitespace + case 不同
            kind='commitment', deadline_str='13:30'
        )
        self.plog.mark_fulfilled(p1, 'test', 'done')
        self.assertEqual(self.plog.promises[p2].state, 'fulfilled',
            'desc case+strip insensitive dedup 应工作')


# ==========================================================================
# R1-R4: [PENDING REVIEW] block in relational.to_prompt_block
# ==========================================================================
class TestPendingReviewBlock(unittest.TestCase):
    def setUp(self):
        from jarvis_relational import RelationalStateStore
        self.tmp = tempfile.mkdtemp(prefix='rel_review_')
        self.store = RelationalStateStore(
            persist_path=os.path.join(self.tmp, 'rel.json')
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_r1_pending_review_jokes_in_block(self):
        """propose joke → review state → to_prompt_block 含 [PENDING REVIEW]."""
        from jarvis_relational import InsideJoke
        joke = InsideJoke(
            id='joke_test_001',
            phrase='地基要打牢',
            birth_context='Sir mentioned this earlier',
            tone='callback',
            source='inner_thought',
            source_marker='test',
            birth_turn_id='',
        )
        self.store.propose_inside_joke(joke)
        block = self.store.to_prompt_block()
        self.assertIn('PENDING REVIEW', block,
            'block 应含 PENDING REVIEW section')
        self.assertIn('地基要打牢', block,
            'pending joke phrase 必须显示')

    def test_r2_pending_review_protocols_in_block(self):
        """propose protocol → review → block 含 protocol id + rule."""
        from jarvis_relational import UnspokenProtocol
        proto = UnspokenProtocol(
            id='proto_test_001',
            rule='Do not open with formal apologies',
            source='inner_thought',
        )
        self.store.propose_protocol(proto)
        block = self.store.to_prompt_block()
        self.assertIn('PENDING REVIEW', block)
        self.assertIn('formal apologies', block,
            'pending protocol rule 必须显示')

    def test_r3_block_shows_item_id(self):
        """block 显示 id (主脑 confirm_pending_review tool 需要 id)."""
        from jarvis_relational import InsideJoke
        joke = InsideJoke(
            id='joke_test_specific_id_123',
            phrase='test phrase',
            birth_context='test',
            tone='callback',
            source='inner_thought',
            source_marker='test',
            birth_turn_id='',
        )
        self.store.propose_inside_joke(joke)
        block = self.store.to_prompt_block()
        self.assertIn('joke_test_specific_id_123', block,
            'item id 必须在 block 中 (主脑 confirm tool 需要)')

    def test_r4_empty_review_no_block(self):
        """无 pending review → 不显示 PENDING REVIEW section."""
        block = self.store.to_prompt_block()
        self.assertNotIn('PENDING REVIEW', block,
            '无 pending → 不该有 PENDING REVIEW section')


# ==========================================================================
# T1-T3: confirm_pending_review tool (Q5-C 治本)
# ==========================================================================
class TestConfirmPendingReviewTool(unittest.TestCase):
    def setUp(self):
        # patch global _DEFAULT_STORE singleton 用 tmp 路径 store
        import jarvis_relational as _rel
        from jarvis_relational import RelationalStateStore
        self.tmp = tempfile.mkdtemp(prefix='conf_tool_')
        self.store = RelationalStateStore(
            persist_path=os.path.join(self.tmp, 'rel.json')
        )
        self._saved_default = _rel._DEFAULT_STORE
        _rel._DEFAULT_STORE = self.store

    def tearDown(self):
        import jarvis_relational as _rel
        _rel._DEFAULT_STORE = self._saved_default
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_t1_activate_pending_joke(self):
        """tool activate → joke state 'review' → 'active'."""
        from jarvis_relational import InsideJoke
        from jarvis_tool_registry import tool_confirm_pending_review
        joke = InsideJoke(
            id='joke_t1_001', phrase='test joke',
            birth_context='ctx', tone='callback',
            source='inner_thought', source_marker='', birth_turn_id='',
        )
        self.store.propose_inside_joke(joke)
        result = tool_confirm_pending_review(
            item_id='joke_t1_001', decision='activate',
            reason='Sir said yes naturally'
        )
        self.assertTrue(result['ok'])
        self.assertEqual(self.store.inside_jokes['joke_t1_001'].state, 'active')

    def test_t2_reject_pending_protocol(self):
        """tool reject → protocol state 'review' → 'archived'."""
        from jarvis_relational import UnspokenProtocol
        from jarvis_tool_registry import tool_confirm_pending_review
        proto = UnspokenProtocol(
            id='proto_t2_001',
            rule='Do not use jargon',
            source='inner_thought',
        )
        self.store.propose_protocol(proto)
        result = tool_confirm_pending_review(
            item_id='proto_t2_001', decision='reject',
            reason='Sir said no'
        )
        self.assertTrue(result['ok'])
        self.assertEqual(
            self.store.unspoken_protocols['proto_t2_001'].state, 'archived'
        )

    def test_t3_unknown_id_fails(self):
        """tool 调不存在 id → ok=False."""
        from jarvis_tool_registry import tool_confirm_pending_review
        result = tool_confirm_pending_review(
            item_id='joke_does_not_exist', decision='activate'
        )
        self.assertFalse(result['ok'])
        self.assertIn('not in review queue', result['error'])


# ==========================================================================
# A1-A4: AutoArbiter prompt + calibration (Q5-A + Q5-B 治本)
# ==========================================================================
class TestAutoArbiterRelaxed(unittest.TestCase):
    def test_a1_inside_joke_prompt_no_hard_floor(self):
        """inside_joke prompt 不再含 '必须<0.7' 硬规."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon(key_router=None)
        fake_joke = MagicMock(phrase='test', birth_context='ctx',
                                tone='callback', source='inner')
        evidence = {'entity': {'phrase': 'test', 'birth_context': 'ctx',
                                  'tone': 'callback', 'source': 'inner'},
                       'existing_active_jokes': []}
        sys_prompt, _ = daemon._build_prompt('inside_joke', fake_joke, evidence)
        # 老硬规: "Otherwise <0.7" → 已删
        self.assertNotIn('Otherwise <0.7', sys_prompt,
            "prompt 不该再含 'Otherwise <0.7' 硬规 (Q5-A 治本)")
        # 新让 LLM 自评
        self.assertIn('自评', sys_prompt,
            'prompt 应让 LLM 自评 confidence')

    def test_a2_protocol_prompt_no_hard_floor(self):
        """protocol prompt 同 — 不再含 '必须<0.7'."""
        from jarvis_auto_arbiter import AutoArbiterDaemon
        daemon = AutoArbiterDaemon(key_router=None)
        fake_proto = MagicMock(rule='Do not X', source='inner',
                                  source_marker='')
        evidence = {'entity': {'rule': 'Do not X', 'source': 'inner',
                                  'source_marker': ''},
                       'existing_active_protocols': []}
        sys_prompt, _ = daemon._build_prompt('protocol', fake_proto, evidence)
        self.assertNotIn('Otherwise <0.7', sys_prompt,
            "protocol prompt 不该再含 'Otherwise <0.7' 硬规")

    def test_a3_calibration_baseline_lowered(self):
        """memory_pool/auto_arbiter_calibration.json baseline 0.75→0.65 (joke/thread), 0.80→0.70 (protocol).

        🆕 [Sir 2026-06-02] 改 assertLessEqual: AutoArbiter 运行时自校准门槛 (往下调,
        让更多通过 = 自治正常行为)。本测验 "baseline 已下调" 契约 (<= Q5-B 上限),
        容忍 runtime 向下漂移 (live 是 gitignored 运行时数据, 硬断言固定值会脆)。
        """
        cal_path = os.path.join(ROOT, 'memory_pool',
                                  'auto_arbiter_calibration.json')
        with open(cal_path, 'r', encoding='utf-8') as f:
            cal = json.load(f)
        thr = cal.get('thresholds', {})
        self.assertLessEqual(thr.get('inside_joke'), 0.65,
            'inside_joke threshold 应 <= 0.65 (Q5-B 下调 + 容忍 runtime 校准)')
        self.assertLessEqual(thr.get('thread'), 0.65,
            'thread threshold 应 <= 0.65')
        self.assertLessEqual(thr.get('protocol'), 0.70,
            'protocol threshold 应 <= 0.70')

    def test_a4_tool_registered(self):
        """confirm_pending_review tool 已注册."""
        from jarvis_tool_registry import get_tool_registry
        registry = get_tool_registry()
        self.assertIn('confirm_pending_review', registry,
            'confirm_pending_review tool 必须在 TOOL_REGISTRY')


if __name__ == '__main__':
    unittest.main()
