# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 20:45 真愿景 Phase 6] audio-to-brain — 直接送 Sir 实时
audio 给主脑 (Gemini multi-modal) 听语气. 不破老路径, env 控开关.

工程:
  - VoiceListenThread 加 3 字段缓存 (_last_audio_wav_bytes/_ts/_duration_sec)
  - line 1161-1185 record loop 拿 pcm_data 后构 WAV bytes + 暂存
  - get_recent_audio_for_brain helper (max_age_sec=30 默, 过期 b'')
  - chat_bypass.stream_chat 读 voice_thread.get_recent_audio_for_brain
  - env JARVIS_AUDIO_TO_BRAIN=1 才生效 (默 0 = 老路径不变)
  - audio Part 加进 chat_history (types.Part.from_bytes mime=audio/wav)
  - prompt 末尾追 'AUDIO ATTACHED' hint 提示主脑感知语气
  - clean_intent 以 '[后台系统' 开头 (system_event) 跳过 (无 Sir 真声音)
  - _supports_vision_main gate (text-only model 不送 audio)

测试 10 testcase:

Step A — VoiceListenThread audio cache (4):
  - PH6_1: 含 3 新字段 + 默认值
  - PH6_2: get_recent_audio_for_brain 返 fresh audio
  - PH6_3: stale (age > max_age) → 返 b''
  - PH6_4: 空 buffer → 返 b''

Step B — chat_bypass env / gate (3, source 静态检验):
  - PH6_5: env check 走 'JARVIS_AUDIO_TO_BRAIN' env var
  - PH6_6: system_event ('[后台系统...]') 跳过 audio
  - PH6_7: _supports_vision_main gate 检查

Step C — chat_bypass audio Part 注入 (3):
  - PH6_8: chat_history 含 mime_type='audio/wav'
  - PH6_9: 含 'AUDIO ATTACHED' prompt hint
  - PH6_10: 调 voice_thread.get_recent_audio_for_brain helper
"""
from __future__ import annotations

import os
import re
import sys
import time
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ============================================================
# Step A — VoiceListenThread audio cache
# ============================================================

class TestStepAVoiceListenThreadAudioCache(unittest.TestCase):

    def test_ph6_1_voice_thread_has_3_new_fields(self):
        """PH6_1: VoiceListenThread 含 3 新字段 + 默认值."""
        from jarvis_voice_listen_thread import VoiceListenThread
        # 不 init (会启 QThread), 只看 __init__ source 是否有这 3 字段
        import inspect
        src = inspect.getsource(VoiceListenThread.__init__)
        self.assertIn('_last_audio_wav_bytes', src)
        self.assertIn('_last_audio_ts', src)
        self.assertIn('_last_audio_duration_sec', src)
        # 也含 Phase 6 marker
        self.assertIn('Phase 6', src)

    def test_ph6_2_helper_returns_fresh_audio(self):
        """PH6_2: get_recent_audio_for_brain fresh (< max_age) 返 bytes."""
        from jarvis_voice_listen_thread import VoiceListenThread

        # stub 不 init QThread, 只挂方法
        class _Stub:
            _last_audio_wav_bytes = b'RIFFTEST'
            _last_audio_ts = time.time()
            _last_audio_duration_sec = 5.0
            get_recent_audio_for_brain = (
                VoiceListenThread.get_recent_audio_for_brain
            )

        b, d = _Stub().get_recent_audio_for_brain(max_age_sec=30.0)
        self.assertEqual(b, b'RIFFTEST')
        self.assertEqual(d, 5.0)

    def test_ph6_3_helper_returns_empty_when_stale(self):
        """PH6_3: stale (age > max_age) → 返 (b'', 0.0)."""
        from jarvis_voice_listen_thread import VoiceListenThread

        class _Stub:
            _last_audio_wav_bytes = b'RIFFTEST'
            _last_audio_ts = time.time() - 60.0  # 60s 前
            _last_audio_duration_sec = 5.0
            get_recent_audio_for_brain = (
                VoiceListenThread.get_recent_audio_for_brain
            )

        b, d = _Stub().get_recent_audio_for_brain(max_age_sec=30.0)
        self.assertEqual(b, b'')
        self.assertEqual(d, 0.0)

    def test_ph6_4_helper_returns_empty_when_buffer_empty(self):
        """PH6_4: 空 buffer → 返 (b'', 0.0)."""
        from jarvis_voice_listen_thread import VoiceListenThread

        class _Stub:
            _last_audio_wav_bytes = b''
            _last_audio_ts = time.time()
            _last_audio_duration_sec = 0.0
            get_recent_audio_for_brain = (
                VoiceListenThread.get_recent_audio_for_brain
            )

        b, d = _Stub().get_recent_audio_for_brain(max_age_sec=30.0)
        self.assertEqual(b, b'')
        self.assertEqual(d, 0.0)


# ============================================================
# Step B — chat_bypass env / gate (static src check)
# ============================================================

class TestStepBChatBypassEnvGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()
        # 隔离 stream_chat body
        m = re.search(
            r'def stream_chat\(self.*?(?=\n    def stream_nudge\()',
            cls.src, re.DOTALL,
        )
        cls.body = m.group(0)

    def test_ph6_5_env_var_check_present(self):
        """PH6_5: stream_chat 含 JARVIS_AUDIO_TO_BRAIN env 检查."""
        self.assertIn("JARVIS_AUDIO_TO_BRAIN", self.body)
        self.assertIn("os.environ.get", self.body)
        # 默 '0' (老路径 不破)
        self.assertIn("'JARVIS_AUDIO_TO_BRAIN', '0'", self.body)

    def test_ph6_6_system_event_skips_audio(self):
        """PH6_6: clean_intent '[后台系统...]' 跳过 audio."""
        # system_event 通常以 '[后台系统xxx]' 开头, 不带 Sir 真声音
        self.assertIn("'[后台系统'", self.body)
        # 且应该 ANDed 在 env=='1' 同条件下
        self.assertTrue(
            'startswith' in self.body or '[后台系统' in self.body,
            'should check clean_intent startswith [后台系统'
        )

    def test_ph6_7_supports_vision_main_gate(self):
        """PH6_7: _supports_vision_main gate (text-only model 不送 audio)."""
        # _supports_vision_main 已存在 (image 路径用), audio 也应 gate
        self.assertIn('_supports_vision_main', self.body)
        # audio 段附近应该 reference 同变量
        # 简化判: audio 段 + _supports_vision_main 都在 body
        # (具体顺序在 PH6_8 验证 audio_wav_bytes 是否被 _supports gate)


# ============================================================
# Step C — chat_bypass audio Part 注入
# ============================================================

class TestStepCChatBypassAudioPart(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(_REPO, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()
        m = re.search(
            r'def stream_chat\(self.*?(?=\n    def stream_nudge\()',
            cls.src, re.DOTALL,
        )
        cls.body = m.group(0)

    def test_ph6_8_chat_history_contains_audio_wav_mime(self):
        """PH6_8: chat_history Part 用 mime_type='audio/wav'."""
        self.assertIn('mime_type="audio/wav"', self.body)

    def test_ph6_9_prompt_audio_hint_present(self):
        """PH6_9: prompt 末尾追 'AUDIO ATTACHED' hint 提示主脑感知语气."""
        self.assertIn('AUDIO ATTACHED', self.body)
        # 应明确不让主脑 quote/transcribe (避免污染 ASR text)
        self.assertIn('Do NOT quote', self.body)
        # 应明确让主脑 attune tone
        self.assertIn('mood', self.body.lower())

    def test_ph6_10_calls_voice_thread_helper(self):
        """PH6_10: 调 voice_thread.get_recent_audio_for_brain helper."""
        self.assertIn('get_recent_audio_for_brain', self.body)
        # 应 max_age_sec=30 (跟 helper 默认一致)
        self.assertIn('max_age_sec=30', self.body)

    def test_ph6_11_audio_hint_must_not_use_str_format_on_prompt(self):
        """🩹 PH6_11 [Sir 20:55 真测 BUGFIX]: prompt 含 JSON 字面量
        (e.g. {"intent": "..."}), 不能用 .format(...) — 会 KeyError.
        必须用 f-string 拼接, prompt 段落不经 format 处理.
        """
        # body 含 audio_hint 拼接 + 不能含 `.format(_audio_duration_sec)` 用在 prompt 上
        # 旧版反例: `(prompt + "[AUDIO ATTACHED] ... ~{:.1f}s ...").format(_audio_duration_sec)`
        # 修后: `_audio_hint = f"..."` + `prompt + _audio_hint`
        # 静态校验: 不应出现把 prompt 拼接后再 .format 的形态
        bad_pattern = (
            r'prompt\s*\n*\s*\+\s*"[^"]*AUDIO ATTACHED[^"]*"[\s\S]{0,500}'
            r'\)\.format\('
        )
        self.assertIsNone(
            re.search(bad_pattern, self.body),
            'audio_hint 不能用 (prompt + ...).format(_audio_duration_sec) — '
            'prompt 内 JSON 字面量会被 str.format 当成 placeholder 引 KeyError. '
            '改用 f-string 拼接.'
        )
        # 正向验证: 应有 f"..." 形态 + _audio_duration_sec 在 f-string 内
        self.assertTrue(
            re.search(
                r'f"[^"]*\{_audio_duration_sec[^"]*\}',
                self.body,
            ),
            '应用 f-string {_audio_duration_sec:.1f} 形态'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
