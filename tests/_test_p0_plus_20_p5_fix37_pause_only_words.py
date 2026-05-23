# -*- coding: utf-8 -*-
"""[P5-fix37 / 2026-05-23 12:15] PAUSE_ONLY_WORDS 暂停语气词不误触发 dismiss.

Sir 12:13 真测痛点:
  Sir: '嗯, 那稍等一下, 我去把这部分能力修复一下, 待会再帮我寄.'
  Jarvis 触发 dismiss → ASR mute 30s → standby.
  Sir: '欸欸欸? 错了! 错了!'

根因:
  STRICT_STOP_WORDS 含 '稍等一下' / '等一下' / 'wait a moment' / 'hold on'
  → detect_stop_command step 2 head_chars=8 命中 → 触发.

治本: 这 4 词 + 兄弟词 ('稍等' / '等等') 搬到 PAUSE_ONLY_WORDS, 仅整句完全等于触发.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestPauseOnlyWords(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, 'jarvis_worker.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_pause_only_words_declared(self):
        self.assertIn('PAUSE_ONLY_WORDS', self.src,
                          'PAUSE_ONLY_WORDS class attr must exist')

    def test_b_pause_words_in_pause_only_list(self):
        # Find the list block
        idx = self.src.find('PAUSE_ONLY_WORDS = [')
        self.assertGreater(idx, 0)
        # Find next ']'
        end = self.src.find(']', idx)
        block = self.src[idx:end + 1]
        for w in ('稍等一下', '等一下', '稍等', '等等',
                    'wait a moment', 'hold on'):
            self.assertIn(w, block, f"{w} must be in PAUSE_ONLY_WORDS")

    def test_c_strict_no_longer_has_pause_words(self):
        # Find STRICT_STOP_WORDS block
        idx = self.src.find('STRICT_STOP_WORDS = [')
        self.assertGreater(idx, 0)
        end = self.src.find(']', idx)
        strict_block = self.src[idx:end + 1]
        # 不允许这 4 个字面值在 STRICT_STOP_WORDS 块内
        for w in ('"稍等一下"', '"等一下"', '"wait a moment"', '"hold on"'):
            self.assertNotIn(w, strict_block,
                              f"STRICT_STOP_WORDS 不应再含 {w} (Sir 12:13 真痛点)")

    def test_d_detect_includes_pause_in_step1(self):
        # detect_stop_command must check PAUSE_ONLY_WORDS in step 1 (exact match)
        idx = self.src.find('def detect_stop_command')
        self.assertGreater(idx, 0)
        end = self.src.find('def ', idx + 1)
        body = self.src[idx:end]
        self.assertIn('PAUSE_ONLY_WORDS', body,
                          'detect_stop_command must reference PAUSE_ONLY_WORDS')

    def test_e_smoke_pause_word_logic(self):
        """运行时 smoke: 整句 == '稍等一下' 触发, 但 '嗯那稍等一下我...' 不触发."""
        try:
            from jarvis_worker import VoiceListenThread
        except Exception as e:
            self.skipTest(f'cannot import VoiceListenThread: {e}')

        # 整句 '稍等一下' → 触发
        self.assertTrue(
            VoiceListenThread.detect_stop_command(
                VoiceListenThread, '稍等一下'),
            '整句 "稍等一下" 应触发 dismiss')

        # Sir 12:13 真痛点 — 承前对话不触发
        sir_text = '嗯,那稍等一下,我去把这部分能力修复一下,待会再帮我寄.'
        self.assertFalse(
            VoiceListenThread.detect_stop_command(
                VoiceListenThread, sir_text),
            f'Sir 真痛点 "{sir_text[:30]}..." 不应触发')

        # 'wait a moment' 整句 → 触发
        self.assertTrue(
            VoiceListenThread.detect_stop_command(
                VoiceListenThread, 'wait a moment'),
            '"wait a moment" 整句应触发')

        # 'wait a moment please can you also...' 不触发
        self.assertFalse(
            VoiceListenThread.detect_stop_command(
                VoiceListenThread, 'wait a moment please can you also help'),
            'wait a moment 后接 continuation 不应触发')

        # STRICT 词仍工作
        self.assertTrue(
            VoiceListenThread.detect_stop_command(
                VoiceListenThread, '停止'),
            '"停止" 仍应触发')
        self.assertTrue(
            VoiceListenThread.detect_stop_command(
                VoiceListenThread, 'stand down'),
            '"stand down" 仍应触发')


if __name__ == '__main__':
    unittest.main()
