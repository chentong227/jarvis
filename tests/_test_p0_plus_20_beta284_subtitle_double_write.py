# -*- coding: utf-8 -*-
"""[P0+20-β.2.8.4 / 2026-05-17] 字幕英文双写 BUG 回归

Sir 22:08 实测: 字幕英文出现 "Your math is precise, Sir. Our last interaction
concluded at 19:07, Your math is precise, Sir. making it ..." — 同一内容乱序
重复. 终端正确单份.

根因: jarvis_chat_bypass.stream_chat 内 token-level subtitle_queue.put
(每个 LLM delta) + sentence-level subtitle_queue.put (句子切完) 双写,
SubtitleOverlay._en_words.extend(new_words) 不去重 → 内容混乱.

修法: 删 token-level put('en', delta) (3 处), 保留 sentence-level put.
终端仍 print(delta) 实时, 字幕只滞后到句末 (200-800ms) 但正确无重复.

回归测策略: scan jarvis_chat_bypass.py 源码确认没有
  subtitle_queue.put(("en", delta))
模式 (允许 put sentence / put _en).
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BYPASS_PATH = os.path.join(ROOT, 'jarvis_chat_bypass.py')


class TestSubtitleDoubleWriteRegression(unittest.TestCase):
    def setUp(self):
        with open(BYPASS_PATH, 'r', encoding='utf-8') as f:
            self.src = f.read()
            self.lines = self.src.split('\n')

    def test_no_token_level_subtitle_put_delta(self):
        """Stream-delta put('en', delta) — 禁止. delta 仅终端 print 不进字幕 queue."""
        pat = re.compile(r'subtitle_queue\.put\(\("en",\s*delta\b')
        matches = []
        for i, line in enumerate(self.lines, 1):
            if pat.search(line):
                matches.append(f"line {i}: {line.strip()}")
        self.assertEqual(matches, [],
            f"发现 token-level subtitle_queue.put('en', delta) 双写 BUG 回归:\n"
            + '\n'.join(matches))

    def test_sentence_level_put_still_present(self):
        """sentence-level put('en', sentence) 必须保留 (字幕仍要正常出)."""
        pat = re.compile(r'subtitle_queue\.put\(\("en",\s*sentence')
        count = sum(1 for line in self.lines if pat.search(line))
        # 至少 stream_chat 主路径 + gatekeeper + fast_call + stream_chat_local + 
        # stream_chat_cloud_followup + stream_nudge ≥ 6 处
        self.assertGreaterEqual(count, 6,
            f"sentence-level put('en', sentence) 只有 {count} 处, 字幕路径可能掉了")

    def test_stream_chat_token_delta_comment_explains_fix(self):
        """改动处必须留 marker '[β.2.8.4]' + 防双写注释, 便于追溯."""
        marker = "β.2.8.4"
        beta_count = self.src.count(marker)
        self.assertGreaterEqual(beta_count, 1,
            f"jarvis_chat_bypass.py 必须含 [β.2.8.4] marker (找到 {beta_count} 处)")

    def test_print_delta_still_terminal(self):
        """终端实时 print(_box_newline(delta)) 不能误删 — Sir 仍需终端实时反馈."""
        pat = re.compile(r'print\(_box_newline\(delta\)')
        count = sum(1 for line in self.lines if pat.search(line))
        self.assertGreaterEqual(count, 3,
            f"print(_box_newline(delta)) 只有 {count} 处, 终端实时打字效果可能丢")


if __name__ == '__main__':
    unittest.main(verbosity=2)
