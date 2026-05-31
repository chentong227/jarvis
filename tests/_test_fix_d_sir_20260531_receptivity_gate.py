# -*- coding: utf-8 -*-
"""[口识体-D / Sir 2026-05-31] 输出闸 — Sir 接收度单一门 (防 voice 突然吓一跳).

Sir 真痛: "确实有被贾维斯打扰到过, 突然说话吓我一跳。"

设计 (VOICE_AND_MIND §4 两件事分开): '内部转'不受门 (P2 势能驱动); '往外说 voice'
过单一接收度门. 不接收 → voice 降 silent_text (留痕不出声) 或 suppress. 被问永远响应.

覆盖 (无 LLM, 纯函数):
  T1 active → allow
  T2 sleep → suppress
  T3 just-interacted 窗口内 → downgrade (核心: 防吓一跳)
  T4 afk_deep → downgrade
  T5 always_allow_types (return_greeting/sleep_due) → allow (绕门)
  T6 in_active_conversation → allow (Sir 在听)
  T7 gate disabled → allow (退回老行为)
  T8 gate_nudge_channel: 非 voice channel 原样放行
  T9 worker 接线 (静态 grep)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_receptivity_gate import (
    assess_receptivity, gate_nudge_channel, load_vocab,
    ALLOW, DOWNGRADE, SUPPRESS,
)


class TestReceptivityGate(unittest.TestCase):
    def test_t1_active_allows(self):
        d, _ = assess_receptivity(sir_state='active')
        self.assertEqual(d, ALLOW)

    def test_t2_sleep_suppress(self):
        d, _ = assess_receptivity(sir_state='sleep')
        self.assertEqual(d, SUPPRESS)
        d2, _ = assess_receptivity(sir_state='active', sleep_mode=True)
        self.assertEqual(d2, SUPPRESS)

    def test_t3_just_interacted_downgrade(self):
        # 核心治本: 刚互动完 3s 主动 voice → 降级 (防吓一跳)
        d, reason = assess_receptivity(
            sir_state='active', seconds_since_last_interaction=3.0)
        self.assertEqual(d, DOWNGRADE)
        self.assertIn('just_interacted', reason)

    def test_t3b_past_window_allows(self):
        # 超窗口 (20s) → 不降级
        d, _ = assess_receptivity(
            sir_state='active', seconds_since_last_interaction=20.0)
        self.assertEqual(d, ALLOW)

    def test_t4_afk_deep_downgrade(self):
        d, _ = assess_receptivity(sir_state='afk_deep')
        self.assertEqual(d, DOWNGRADE)

    def test_t5_always_allow_types(self):
        # return_greeting / sleep_due 绕门 (即使 sleep)
        for nt in ('return_greeting', 'sleep_due'):
            d, _ = assess_receptivity(nudge_type=nt, sir_state='sleep',
                                      sleep_mode=True)
            self.assertEqual(d, ALLOW, f"{nt} 应绕门")

    def test_t6_in_conversation_allows(self):
        # Sir 正跟 Jarvis 对话 → 在听, 即使刚互动完也 allow
        d, reason = assess_receptivity(
            sir_state='active', in_active_conversation=True,
            seconds_since_last_interaction=2.0)
        self.assertEqual(d, ALLOW)
        self.assertIn('active_conversation', reason)

    def test_t7_disabled_allows(self):
        vocab = dict(load_vocab())
        vocab['enabled'] = False
        d, _ = assess_receptivity(sir_state='sleep', sleep_mode=True, vocab=vocab)
        self.assertEqual(d, ALLOW)

    def test_t8_non_voice_passthrough(self):
        ch, dec, _ = gate_nudge_channel({'channel': 'silent_text', 'type': 'x'})
        self.assertEqual(ch, 'silent_text')
        self.assertEqual(dec, ALLOW)

    def test_t8b_voice_downgrade_routes_silent(self):
        # voice + 不接收 → final channel = silent_text (jarvis=None 走默认信号)
        # 构 fake jarvis: sleep_mode True → suppress
        class _FakeNG:
            def is_sleep_mode(self):
                return True

        class _FakeJ:
            nudge_gate = _FakeNG()
            _in_conversation = False
            _last_user_active = 0.0
            inner_thought_daemon = None
        ch, dec, _ = gate_nudge_channel({'channel': 'voice', 'type': 'offer_help'},
                                        jarvis=_FakeJ())
        self.assertEqual(ch, 'suppressed')
        self.assertEqual(dec, SUPPRESS)

    def test_t9_worker_wired(self):
        with open(os.path.join(ROOT, 'jarvis_worker.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('gate_nudge_channel', src)
        self.assertIn('接收度门', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
