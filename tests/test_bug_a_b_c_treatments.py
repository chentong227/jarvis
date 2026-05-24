# -*- coding: utf-8 -*-
"""[2026-05-24 19:50] BUG-A/B/C wave 修测试.

BUG-A (TTS 卡顿): emergency cleanup + duration log + SWM publish (jarvis_vocal_cord.py)
BUG-B (Tool Chain 熔断截断): universal safety net wrap-up trigger (jarvis_chat_bypass.py)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestBugATTSEmergencyCleanup(unittest.TestCase):
    """BUG-A: TTS render 慢自动 emergency GPU cleanup + SWM publish."""

    def test_emergency_threshold_present(self):
        """jarvis_vocal_cord.py 含 12s 阈值 + emergency cleanup."""
        with open(os.path.join(ROOT, 'jarvis_vocal_cord.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('BUG-A 治本', src, 'BUG-A 治本标识缺失')
        self.assertIn('_render_dur > 12.0', src, 'emergency 阈值 12s 缺失')
        self.assertIn('emergency GPU cleanup', src, 'emergency cleanup log msg 缺失')

    def test_swm_publish_on_slow_render(self):
        """卡 render → publish tts_render_slow event 进 SWM."""
        with open(os.path.join(ROOT, 'jarvis_vocal_cord.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("etype='tts_render_slow'", src, 'tts_render_slow event 缺失')
        self.assertIn("'duration_sec'", src, 'metadata duration_sec 缺失')
        self.assertIn("'text_excerpt'", src, 'metadata text_excerpt 缺失')

    def test_emergency_cleanup_uses_ipc_collect(self):
        """emergency 用 ipc_collect 比正常清更彻底."""
        with open(os.path.join(ROOT, 'jarvis_vocal_cord.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("torch.cuda.ipc_collect", src,
                      'emergency cleanup 应用 ipc_collect 比 empty_cache 更彻底')


class TestBugBUniversalWrapUpSafetyNet(unittest.TestCase):
    """BUG-B: Tool Chain 熔断后 universal wrap-up safety net."""

    def test_universal_safety_net_present(self):
        """chat_bypass.py 含 universal safety net comment + condition."""
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('Universal Safety Net', src, 'BUG-B universal safety net 标识缺失')
        # 检条件: 任何 _circuit_broken_reason + reply < 20 char 但非 duplicate_call
        self.assertIn(
            "not _circuit_broken_reason.startswith('duplicate_call:')",
            src,
            '应排除 duplicate_call (P5-fix63 已 cover)',
        )
        self.assertIn("len(_stripped_full or '') < 20", src, '20 char 阈值缺失')

    def test_p5_fix63_still_present(self):
        """老 P5-fix63 (duplicate_call + 30 char) 仍在不被覆盖."""
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix63', src, 'P5-fix63 标识应保留')
        self.assertIn("len(_stripped_full or '') < 30", src, 'P5-fix63 30 char 阈值应保留')


if __name__ == '__main__':
    unittest.main()
