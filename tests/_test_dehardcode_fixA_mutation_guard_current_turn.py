# -*- coding: utf-8 -*-
"""[thinking-dehardcode fix#A / Sir 2026-05-31] MutationEvidenceGuard 纳入当前轮 utterance.

镜像复验挖出 (P1 emergent 第2轮): Sir 说 "你别老提醒我设提醒" → 主脑想写
profile.interaction_preferences="No proactive reminder offers" (合法! Sir 明确请求),
但 MutationEvidenceGuard substring/jaccard=0.00 → BLOCKED → 工具熔断
(consecutive_failures) → 本地合成"故障感"回复. 根因: _append_stm 在 turn 结束才把
user+jarvis 一起写 STM, guard 跑在 turn 中途时**当前轮 Sir 话不在 STM** → guard 拿
上一轮 STM (编码/午饭) 比对 → 误拦.

Fix#A (准则 5/6 接地, 不削弱反幻觉): caller (chat_bypass) 传当前轮 utterance,
check_mutation_evidence 把它并入证据 (检"Sir 真说过吗"的正确来源就是当前话).
编造的值 (BUG-H "Stay safe" vs Sir 说 "d home") 仍不匹配 → 仍 block.

覆盖 (纯函数, 无 LLM):
  T1 stale STM (无当前轮) → BLOCK (复现 bug)
  T2 同 case + 传 current_text (Sir 真说过) → PASS (本 fix)
  T3 编造值 + 传 current_text (无关) → 仍 BLOCK (反幻觉不破)
  T4 current_text 空 → 老行为 (向后兼容)
  T5 update_sir_field 透传 current_utterance (源码 anchor)
  T6 chat_bypass 在 stream 入口存 _current_turn_user_text + mutation 时传 (源码 anchor)
"""
from __future__ import annotations

import inspect
import os
import sys
import time
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_mutation_evidence_guard as guard


def _set_default_vocab():
    """注入 default vocab (隔离真 vocab 文件, 测试确定性)."""
    guard._VOCAB_CACHE['data'] = dict(guard._DEFAULT_VOCAB)
    guard._VOCAB_CACHE['checked_at'] = time.time()


def _reset_vocab():
    guard._VOCAB_CACHE['data'] = None
    guard._VOCAB_CACHE['mtime'] = 0.0
    guard._VOCAB_CACHE['checked_at'] = 0.0


def _nerve(*user_texts):
    return SimpleNamespace(
        short_term_memory=[{'user': t, 'jarvis': ''} for t in user_texts]
    )


# 真实镜像 case
_NEW_VALUE = 'No proactive reminder offers; wait for Sir to ask'
_PREV_STM = 'I have been coding six hours straight and skipped lunch.'
_CURRENT = ("You don't need to keep offering to set reminders for me. "
            "I'll ask if I actually want one.")


class TestFixAMutationGuardCurrentTurn(unittest.TestCase):
    def setUp(self):
        _set_default_vocab()

    def tearDown(self):
        _reset_vocab()

    def test_t1_stale_stm_blocks(self):
        """复现 bug: 当前轮话不在 STM → guard 拿上一轮 → 误拦合法写入."""
        ok, reason = guard.check_mutation_evidence(
            _NEW_VALUE, 'profile.interaction_preferences',
            'fast_call_mutation:update', _nerve(_PREV_STM), 'ProfileCard',
        )
        self.assertFalse(ok, f'无当前轮 → 应 block (复现 bug). got {reason}')

    def test_t2_current_text_passes(self):
        """本 fix: 传当前轮 utterance → Sir 真说过 → PASS."""
        ok, reason = guard.check_mutation_evidence(
            _NEW_VALUE, 'profile.interaction_preferences',
            'fast_call_mutation:update', _nerve(_PREV_STM), 'ProfileCard',
            current_text=_CURRENT,
        )
        self.assertTrue(ok, f'Sir 明确请求应 PASS, got: {reason}')

    def test_t3_fabrication_still_blocked(self):
        """反幻觉不破: 编造值 (Stay safe) vs Sir 真说 (d home) → 仍 block."""
        ok, reason = guard.check_mutation_evidence(
            'Sir frequently references the Stay safe quote from Avengers',
            'profile.idiosyncrasies', 'worker.memory_correction',
            _nerve('earlier chatter'), 'ProfileCard',
            current_text='d home',
        )
        self.assertFalse(ok, f'编造值应仍 block (反幻觉), got: {reason}')

    def test_t4_empty_current_text_backward_compat(self):
        """current_text 空 → 老行为 (stale STM block 不变)."""
        ok, _ = guard.check_mutation_evidence(
            _NEW_VALUE, 'profile.x', 'worker.x',
            _nerve(_PREV_STM), 'ProfileCard', current_text='',
        )
        self.assertFalse(ok)

    def test_t5_update_sir_field_threads_current_utterance(self):
        import jarvis_memory_hub
        sig = inspect.signature(
            jarvis_memory_hub.MemoryMutationGateway.update_sir_field)
        self.assertIn('current_utterance', sig.parameters,
                      'update_sir_field 应有 current_utterance 参数 (透传 guard)')

    def test_t6_chat_bypass_stores_and_passes(self):
        import jarvis_chat_bypass
        src = inspect.getsource(jarvis_chat_bypass)
        self.assertIn('_current_turn_user_text', src,
                      'chat_bypass 应存当前轮 utterance')
        self.assertIn('current_utterance=', src,
                      'chat_bypass mutation 调用应传 current_utterance')


if __name__ == '__main__':
    unittest.main()
