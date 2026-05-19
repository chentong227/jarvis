# -*- coding: utf-8 -*-
"""
[P0+20-β.5.13 / 2026-05-19] β.5 决策集中主脑收尾 — silent_text/visual_pulse 纳入

Sir 21:48 反馈: "把 5 层后面这些所有的都接入 LLM 会怎么样? 直接做完吧, 全部的."

设计意图 (准则 6 第 3 维 决策集中主脑):
  旧版 ProactiveCare push channel=silent_text → worker:2746 直 emit 字幕 (跳过主脑)
  新版 (env JARVIS_NUDGE_LLM_ALL_CHANNELS=1 默认): choose_channel 永远返 'voice',
       所有 channel 走 stream_nudge → 主脑看 SWM + CHANNEL HINT + REACTION SPACE
       自决 silent / voice. silent 通过 reaction_space [SILENCE] 实现.

兼容性 (Sir 准则 7 元否决):
  env=0 → 走老 choose_channel 逻辑 (urgency / silent_recent 判 silent_text). 实机
  出问题秒切 (set env, 重启). 不需 git revert.

测试覆盖:
  A. choose_channel env=1 (default) → 永远 'voice'
  B. choose_channel env=0 → 老逻辑 (高 urgency / silent_recent → voice; 否则 silent_text)
  C. push 注入 original_channel_hint 到 nudge_ctx
  D. stream_nudge prompt 注入 channel_hint_str (字面 marker)
  E. _legacy_channel_for_hint 算老规则 channel (env=1 时仍能算)
  F. 老 silent_text 分支 worker 路径未删 (env=0 兼容)
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# A: choose_channel env=1 默认 'voice'
# ==========================================================================

class TestBeta513ChooseChannelEnvDefault(unittest.TestCase):
    """env JARVIS_NUDGE_LLM_ALL_CHANNELS=1 (默认) → 永远 voice."""

    @classmethod
    def setUpClass(cls):
        from jarvis_proactive_care import CareSpeechSynth
        cls.synth = CareSpeechSynth()

    def _make_evi(self, urgency=0.7):
        from jarvis_proactive_care import CareEvidence
        return CareEvidence(
            concern_id='sir_hydration_habit',
            urgency_score=urgency,
            what_i_watch='water intake',
            why_i_care='health',
            severity=0.5,
            breakdown={},
        )

    def test_env_default_returns_voice_low_urgency(self):
        """env 不设 → 默认 '1' → 低 urgency 也走 voice."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('JARVIS_NUDGE_LLM_ALL_CHANNELS', None)
            ch = self.synth.choose_channel(self._make_evi(0.6), False)
            self.assertEqual(ch, 'voice',
                'env 默认 (=1) 时低 urgency 也应走 voice (主脑接管)')

    def test_env_explicit_1_returns_voice(self):
        """env=1 显式 → voice."""
        with patch.dict(os.environ, {'JARVIS_NUDGE_LLM_ALL_CHANNELS': '1'}):
            ch = self.synth.choose_channel(self._make_evi(0.6), False)
            self.assertEqual(ch, 'voice')

    def test_env_silent_text_blocked_when_llm_all(self):
        """env=1 时即便老规则会选 silent_text, 实际 channel 仍 voice."""
        with patch.dict(os.environ, {'JARVIS_NUDGE_LLM_ALL_CHANNELS': '1'}):
            evi = self._make_evi(0.6)  # 中等 urgency, 老规则会选 silent_text
            ch = self.synth.choose_channel(evi, silent_done_recently=False)
            self.assertEqual(ch, 'voice', 'env=1 时禁止 silent_text 短路')


# ==========================================================================
# B: choose_channel env=0 老逻辑兼容
# ==========================================================================

class TestBeta513ChooseChannelEnvLegacy(unittest.TestCase):
    """env=0 → 老 channel 决策."""

    @classmethod
    def setUpClass(cls):
        from jarvis_proactive_care import CareSpeechSynth
        cls.synth = CareSpeechSynth()

    def _make_evi(self, urgency):
        from jarvis_proactive_care import CareEvidence
        return CareEvidence(
            concern_id='sir_hydration_habit',
            urgency_score=urgency,
            what_i_watch='water',
            why_i_care='health',
            severity=0.5,
            breakdown={},
        )

    def test_env_0_high_urgency_voice(self):
        """env=0 + urgency >= 0.85 → voice."""
        with patch.dict(os.environ, {'JARVIS_NUDGE_LLM_ALL_CHANNELS': '0'}):
            ch = self.synth.choose_channel(self._make_evi(0.9), False)
            self.assertEqual(ch, 'voice', 'env=0 高 urgency 仍 voice')

    def test_env_0_silent_recent_voice(self):
        """env=0 + silent 过 → 升级 voice."""
        with patch.dict(os.environ, {'JARVIS_NUDGE_LLM_ALL_CHANNELS': '0'}):
            ch = self.synth.choose_channel(self._make_evi(0.7), True)
            self.assertEqual(ch, 'voice', 'silent 过应升级 voice')

    def test_env_0_mid_urgency_silent_text(self):
        """env=0 + 中等 urgency + 未 silent → silent_text."""
        with patch.dict(os.environ, {'JARVIS_NUDGE_LLM_ALL_CHANNELS': '0'}):
            ch = self.synth.choose_channel(self._make_evi(0.6), False)
            self.assertEqual(ch, 'silent_text',
                'env=0 中等 urgency 未 silent → silent_text (老逻辑)')


# ==========================================================================
# C: _legacy_channel_for_hint helper
# ==========================================================================

class TestBeta513LegacyHintHelper(unittest.TestCase):
    """_legacy_channel_for_hint 算"原规则会选什么 channel" 给主脑参考."""

    @classmethod
    def setUpClass(cls):
        from jarvis_proactive_care import CareSpeechSynth
        cls.synth = CareSpeechSynth()

    def _make_evi(self, urgency):
        from jarvis_proactive_care import CareEvidence
        return CareEvidence(
            concern_id='c', urgency_score=urgency,
            what_i_watch='', why_i_care='', severity=0.5, breakdown={},
        )

    def test_legacy_hint_high_urgency_voice(self):
        h = self.synth._legacy_channel_for_hint(self._make_evi(0.9), False)
        self.assertEqual(h, 'voice')

    def test_legacy_hint_silent_recent_voice(self):
        h = self.synth._legacy_channel_for_hint(self._make_evi(0.7), True)
        self.assertEqual(h, 'voice')

    def test_legacy_hint_mid_urgency_silent_text(self):
        h = self.synth._legacy_channel_for_hint(self._make_evi(0.6), False)
        self.assertEqual(h, 'silent_text',
            'legacy hint 应保留老 silent_text 选择给主脑参考')

    def test_legacy_hint_ignores_env(self):
        """legacy_hint 即便 env=1 时也应算老结果 (主脑参考用)."""
        with patch.dict(os.environ, {'JARVIS_NUDGE_LLM_ALL_CHANNELS': '1'}):
            h = self.synth._legacy_channel_for_hint(self._make_evi(0.6), False)
            self.assertEqual(h, 'silent_text',
                'legacy_hint 不受 env 影响, 始终算老规则')


# ==========================================================================
# D: push 注入 original_channel_hint
# ==========================================================================

class TestBeta513PushInjectsHint(unittest.TestCase):
    """push 时把 original_channel_hint 写入 nudge_ctx."""

    def test_push_signature_has_hint_param(self):
        from jarvis_proactive_care import CareSpeechSynth
        import inspect
        sig = inspect.signature(CareSpeechSynth.push)
        self.assertIn('original_channel_hint', sig.parameters,
            'push 签名必须有 original_channel_hint 参数 (β.5.13)')

    def test_push_writes_hint_to_ctx(self):
        """dry_run=True 时 push 仍构 nudge_ctx, 拦 worker 看 ctx 字段."""
        from jarvis_proactive_care import CareSpeechSynth, CareEvidence
        import json
        evi = CareEvidence(
            concern_id='sir_hydration_habit', urgency_score=0.6,
            what_i_watch='w', why_i_care='', severity=0.5, breakdown={},
        )
        synth = CareSpeechSynth()

        captured_payload = []

        class _FakeWorker:
            def push_command(self, payload):
                captured_payload.append(payload)

        # 不 dry_run, push 会真调 worker.push_command(__NUDGE__:json)
        # 但 channel=voice 时 nudge_ctx 仍含 original_channel_hint
        synth.push(_FakeWorker(), evi, dry_run=False,
                    channel='voice', original_channel_hint='silent_text')
        self.assertEqual(len(captured_payload), 1, '应 push 1 次')
        payload = captured_payload[0]
        self.assertTrue(payload.startswith('__NUDGE__:'))
        ctx = json.loads(payload[len('__NUDGE__:'):])
        self.assertEqual(ctx.get('original_channel_hint'), 'silent_text',
            'nudge_ctx 必须含 original_channel_hint="silent_text"')


# ==========================================================================
# E: stream_nudge prompt 注入 channel_hint_str
# ==========================================================================

class TestBeta513StreamNudgePromptHint(unittest.TestCase):
    """stream_nudge 看到 original_channel_hint 时, prompt 含 CHANNEL HINT block."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_channel_hint_str_init(self):
        """stream_nudge 内必须有 channel_hint_str 变量初始化."""
        self.assertIn('channel_hint_str = ""', self.src,
            'stream_nudge 必须 init channel_hint_str')

    def test_reads_original_channel_hint(self):
        """nudge_context.get('original_channel_hint', ...) 必须存在."""
        self.assertIn("nudge_context.get('original_channel_hint'", self.src,
            'stream_nudge 必须读 nudge_context.original_channel_hint')

    def test_prompt_contains_channel_hint_marker(self):
        """prompt 模板必须含 [CHANNEL HINT — ...] marker."""
        self.assertIn('[CHANNEL HINT', self.src,
            'prompt 必须含 [CHANNEL HINT 块标题')
        self.assertIn('β.5.13', self.src, 'β.5.13 marker 必须存在')

    def test_prompt_explains_silent_upgrade(self):
        """CHANNEL HINT 必须解释 silent_text + 高 urgency 可升级 voice 的语义."""
        self.assertIn('upgrade to voice', self.src,
            'CHANNEL HINT 应说明高 urgency 可升级 voice')
        self.assertIn('consider [SILENCE]', self.src,
            'CHANNEL HINT 应说明可考虑 [SILENCE]')


# ==========================================================================
# F: 老 silent_text worker 路径未删 (env=0 兼容)
# ==========================================================================

class TestBeta513LegacyWorkerPathPreserved(unittest.TestCase):
    """β.5.13 是 env opt-in (默认开). 老 silent_text worker 分支必须保留作 env=0 路径."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_worker_silent_text_branch_exists(self):
        self.assertIn("nudge_channel == 'silent_text'", self.src,
            'worker silent_text 分支必须保留 (env=0 走老路径)')

    def test_worker_visual_pulse_branch_exists(self):
        self.assertIn("nudge_channel == 'visual_pulse'", self.src,
            'worker visual_pulse 分支必须保留')


# ==========================================================================
# G: marker comment 持久化
# ==========================================================================

class TestBeta513PersistMarker(unittest.TestCase):
    """β.5.13 marker 持久化."""

    def test_proactive_care_marker(self):
        src = _read(os.path.join(ROOT, 'jarvis_proactive_care.py'))
        self.assertIn('β.5.13', src,
            'β.5.13 marker 必须在 jarvis_proactive_care.py')
        self.assertIn('JARVIS_NUDGE_LLM_ALL_CHANNELS', src,
            'env 名 JARVIS_NUDGE_LLM_ALL_CHANNELS 必须存在')

    def test_chat_bypass_marker(self):
        src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))
        self.assertIn('β.5.13', src,
            'β.5.13 marker 必须在 jarvis_chat_bypass.py')


if __name__ == '__main__':
    unittest.main()
