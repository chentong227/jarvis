# -*- coding: utf-8 -*-
"""
[P0+20-β.5.11 / 2026-05-19] BUG: "hey jarvis" 应走快唤醒 (reflex 短路径)

Sir 真机痛点: "hey jarvis" 被 parse_wake_word 识为 cmd='hey' 送 LLM 跑全主脑,
应该走 β.4.8 设计的快唤醒 (reflex chime + 短 awake reaction).

设计意图 (Sir 明确): 任意词+jarvis 中
  - "任意词" 是实词 (如 "帮我开 cursor") → cmd='帮我开 cursor' 送 LLM (LLM 唤醒)
  - "任意词" 是纯 filler/呼语 (hey/hi/yo/嘿/喂/...) → cmd 视作空 → 走 reflex 快唤醒

Root cause: parse_wake_word 在剥 wake_aliases 和 wake_phrases 后, 仅以 `len(cmd) <= 1`
判空唤醒, 没把语气词识别为空意图.

修法: 在 wake_phrases 后增 filler_addressing_words list (英中双语呼语), 剥掉.

测试覆盖:
  A. "hey jarvis" → cmd='jarvis' (快唤醒)
  B. "嘿 jarvis" → cmd='jarvis' (中文同款)
  C. "yo jarvis" / "hi jarvis" / "oi jarvis" / "hello jarvis" 等 → cmd='jarvis'
  D. "jarvis 帮我开 cursor" → cmd 含 '帮我开 cursor' (LLM 唤醒不破坏)
  E. "jarvis" 单词 → cmd='jarvis' (原行为)
  F. "are you there jarvis" → cmd='jarvis' (旧 wake_phrases 仍工作)
  G. 持久化 marker 验证
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class _ParseWakeProxy:
    """轻量 proxy: 把 VoiceListenThread.parse_wake_word 作为 unbound 函数调用.

    parse_wake_word 实现仅用 `text` 参数, 不引用 self 任何状态 — 因此可以
    跳过 QThread 真实初始化, 避免 PyQt5 super().__init__() 校验报错.
    """

    def __init__(self):
        from jarvis_worker import VoiceListenThread
        self._fn = VoiceListenThread.parse_wake_word

    def parse_wake_word(self, text):
        return self._fn(None, text)


class TestBeta511HeyJarvisFastWake(unittest.TestCase):
    """β.5.11: 纯语气词+jarvis 应走快唤醒, 不送 LLM."""

    @classmethod
    def setUpClass(cls):
        cls.worker = _ParseWakeProxy()

    # === 应走快唤醒 (cmd='jarvis') ===

    def test_hey_jarvis_fast_wake(self):
        """'hey jarvis' → cmd='jarvis' (核心痛点)."""
        is_wake, cmd = self.worker.parse_wake_word("hey jarvis")
        self.assertTrue(is_wake, "'hey jarvis' 必须触发 wake")
        self.assertEqual(cmd, 'jarvis',
            f"'hey jarvis' 必须降级为空唤醒 cmd='jarvis' (走 reflex), 实际 cmd='{cmd}'")

    def test_hi_jarvis_fast_wake(self):
        """'hi jarvis' → cmd='jarvis'."""
        is_wake, cmd = self.worker.parse_wake_word("hi jarvis")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_yo_jarvis_fast_wake(self):
        """'yo jarvis' → cmd='jarvis'."""
        is_wake, cmd = self.worker.parse_wake_word("yo jarvis")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_hello_jarvis_fast_wake(self):
        """'hello jarvis' → cmd='jarvis'."""
        is_wake, cmd = self.worker.parse_wake_word("hello jarvis")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_zh_hey_jarvis_fast_wake(self):
        """'嘿 贾维斯' → cmd='jarvis' (中文呼语)."""
        is_wake, cmd = self.worker.parse_wake_word("嘿 贾维斯")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_zh_wei_jarvis_fast_wake(self):
        """'喂 贾维斯' → cmd='jarvis'."""
        is_wake, cmd = self.worker.parse_wake_word("喂 贾维斯")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_okay_jarvis_fast_wake(self):
        """'ok jarvis' → cmd='jarvis'."""
        is_wake, cmd = self.worker.parse_wake_word("ok jarvis")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    # === 实词 cmd 应保留 (走 LLM 唤醒) ===

    def test_real_cmd_preserved_zh(self):
        """'jarvis 帮我开 cursor' → cmd 必须含 '帮我开 cursor' (LLM 唤醒)."""
        is_wake, cmd = self.worker.parse_wake_word("jarvis 帮我开 cursor")
        self.assertTrue(is_wake)
        self.assertNotEqual(cmd, 'jarvis',
            "实词 cmd 不能被降级为空唤醒")
        self.assertIn('帮我开', cmd,
            f"实词 cmd 必须保留, 实际 cmd='{cmd}'")
        self.assertIn('cursor', cmd)

    def test_real_cmd_preserved_en(self):
        """'jarvis open chrome' → cmd 含 'open chrome'."""
        is_wake, cmd = self.worker.parse_wake_word("jarvis open chrome")
        self.assertTrue(is_wake)
        self.assertNotEqual(cmd, 'jarvis')
        self.assertIn('open', cmd)
        self.assertIn('chrome', cmd)

    def test_real_cmd_with_filler_preserved(self):
        """'hey jarvis open chrome' → 含 'open chrome' (filler 剥掉但实词保留)."""
        is_wake, cmd = self.worker.parse_wake_word("hey jarvis open chrome")
        self.assertTrue(is_wake)
        self.assertIn('open', cmd)
        self.assertIn('chrome', cmd)

    # === 原行为不破 ===

    def test_jarvis_alone_fast_wake(self):
        """单 'jarvis' → cmd='jarvis' (原行为)."""
        is_wake, cmd = self.worker.parse_wake_word("jarvis")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_are_you_there_jarvis_fast_wake(self):
        """'are you there jarvis' → cmd='jarvis' (旧 wake_phrases 仍工作)."""
        is_wake, cmd = self.worker.parse_wake_word("are you there jarvis")
        self.assertTrue(is_wake)
        self.assertEqual(cmd, 'jarvis')

    def test_non_jarvis_no_wake(self):
        """无 jarvis 的语句不该触发 wake."""
        is_wake, cmd = self.worker.parse_wake_word("hey there how are you")
        self.assertFalse(is_wake, "无 jarvis 不该触发 wake")


class TestBeta511PersistMarker(unittest.TestCase):
    """β.5.11 持久化 marker 验证."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_marker_comment_present(self):
        """β.5.11 marker 注释必须存在."""
        self.assertIn('β.5.11', self.src,
            'β.5.11 marker 必须出现在 jarvis_worker.py (便于 git blame 追溯)')

    def test_filler_list_present(self):
        """filler_addressing_words list 必须存在."""
        self.assertIn('filler_addressing_words', self.src,
            'parse_wake_word 必须有 filler_addressing_words list')

    def test_hey_in_filler_list(self):
        """\\bhey\\b 必须在 list 里."""
        self.assertIn(r'\bhey\b', self.src,
            'hey 必须在 filler_addressing_words list 内')

    def test_zh_filler_present(self):
        """中文呼语 '嘿' '喂' 必须在 list 里."""
        self.assertIn(r"r'嘿'", self.src, "'嘿' 必须在 list 内")
        self.assertIn(r"r'喂'", self.src, "'喂' 必须在 list 内")


if __name__ == '__main__':
    unittest.main()
