# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 21:11 真测 P2_b] InnerThought log 不许截到字中间.

Sir 真测 log 21:04 看到:
  💭 [InnerThought] [B/sal=0.75/state=active/tick=45s] ... I should aim
     for a more aligned ton | actionable=propose_protocol:Always match
     Sir's conf → proposed:Always match Sir's confirmatio (id=...)
     | cite="informal confirmation" | next=60s(llm_chosen)

3 处截到 word 中间:
  - thought.thought[:300] → "more aligned ton" (应 "tone")
  - thought.actionable[:40] → "Always match Sir's conf" (应 "confirmation")
  - result[:?] → "Always match Sir's confirmatio" (应 "confirmation")

治本: 新 helper `_truncate_at_word_boundary(s, max_chars)` —
  - 切 max_chars 后倒查 word boundary (space/punct)
  - 回退不超过 max*0.2, 找到 → 截到 boundary + '…'
  - 没找到 → 仍按 max_chars + '…' (避免无穷回退)

测试:
  - len <= max → 不切
  - 长 + 有 space → 切到 space 前 + '…'
  - 长 + 全无 space → max + '…' (CJK 友好)
  - 回退太远 (>20%) → 仍切 max + '…'
  - 边界标点 (',' '.' '!' '?' '，' '。' 等) 也算 boundary
  - 集成: 3 处 log 调 helper (静态扫描)
"""
from __future__ import annotations

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ==========================================================================
# Part A — helper 单元
# ==========================================================================
class TestTruncateAtWordBoundary(unittest.TestCase):

    def setUp(self):
        from jarvis_inner_thought_daemon import _truncate_at_word_boundary
        self.fn = _truncate_at_word_boundary

    def test_short_no_truncate(self):
        """len <= max → 原样返."""
        self.assertEqual(self.fn('hello', 10), 'hello')
        self.assertEqual(self.fn('exactly10c', 10), 'exactly10c')

    def test_empty_string(self):
        self.assertEqual(self.fn('', 10), '')
        self.assertEqual(self.fn(None, 10), None)

    def test_truncate_at_space(self):
        """长字符串 + 有 space → 切到 space 前 + suffix."""
        s = "Always match Sir's confirmation tone"
        out = self.fn(s, 24)
        # max=24 char, "Always match Sir's confi" 切到 'confi' 字中, 回退到
        # 最近 space → "Always match Sir's…"
        self.assertTrue(out.endswith('…'))
        # 关键断言: 不截在 word 中间 (即 'confi' 不该出现末尾)
        self.assertFalse(out.replace('…', '').endswith('confi'),
            f'should not end mid-word: {out!r}')
        # 应保留完整 word "Sir's"
        self.assertIn("Sir's", out)

    def test_truncate_at_punctuation(self):
        """标点也算 boundary."""
        s = "Hello, world! This is a long sentence."
        out = self.fn(s, 14)
        self.assertTrue(out.endswith('…'))
        # max=14 "Hello, world! " — 切到 '!' 前 (boundary)
        # 不该末尾是 'Th' / 'T' 等 next word 起始
        self.assertFalse('Th' in out.split('…')[0][-3:],
            f'should not include next word start: {out!r}')

    def test_truncate_cjk_falls_back(self):
        """全中文无 space → 按 max + suffix (CJK 字符天然可切)."""
        s = "这是一段很长的中文文本没有任何空格符号"
        out = self.fn(s, 8)
        # 全无 boundary → 按 max + …
        self.assertTrue(out.endswith('…'))
        self.assertEqual(len(out), 8 + 1)  # 8 char + …

    def test_truncate_chinese_punct_boundary(self):
        """中文标点也算 boundary."""
        s = "你好，世界！这是一段长文本。还有更多。"
        out = self.fn(s, 8)
        self.assertTrue(out.endswith('…'))
        # max=8 "你好，世界！这是" — 应回退到 ！ 或 ，
        # 不该把 "这是" 包进
        cleaned = out.replace('…', '')
        self.assertFalse(cleaned.endswith('这是'),
            f'should fall back to CJK punct: {out!r}')

    def test_truncate_no_fallback_too_far(self):
        """回退超 20% → 不回退, 按 max 切 + suffix."""
        # max=20, 但 space 在 position 3 → 回退 17 char (>20%*20=4)
        s = "AB " + "X" * 100
        out = self.fn(s, 20)
        self.assertTrue(out.endswith('…'))
        # 不该回退到 position 3 (太亏) — 应直接切 20 + …
        cleaned = out.replace('…', '').rstrip()
        self.assertGreater(len(cleaned), 4,
            f'should not fall back too far, got {out!r}')

    def test_custom_suffix(self):
        """suffix 可定制."""
        out = self.fn('hello world this is long', 10, suffix='...')
        self.assertTrue(out.endswith('...'))


# ==========================================================================
# Part B — 静态扫描 3 处 log 真用 helper
# ==========================================================================
class TestLogSitesUseHelper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(
            os.path.join(_REPO, 'jarvis_inner_thought_daemon.py'),
            'r', encoding='utf-8'
        ) as f:
            cls.body = f.read()

    def test_actionable_uses_helper_in_console_log(self):
        """Sir 真看的 console log (action_str) 必须用 helper, 不用 [:40] 硬切.

        SWM metadata 内部 [:60]/[:120]/[:100] 维持 (Sir 不直看, 内部 trace).
        """
        # 正向: console log 必须调 helper
        self.assertIn(
            '_truncate_at_word_boundary(thought.actionable',
            self.body,
            'console log 必须用 helper truncate thought.actionable'
        )

    def test_evidence_link_uses_helper_in_console_log(self):
        """cite=\"...\" console log evidence_link 应用 helper."""
        self.assertIn(
            '_truncate_at_word_boundary(thought.evidence_link',
            self.body,
            'console log 必须用 helper truncate thought.evidence_link'
        )

    def test_thought_text_uses_helper_in_normal_log(self):
        """normal log thought.thought[:300] 应改 helper (mediocre [:60] 仍可)."""
        # 找 normal log line (不是 mediocre)
        # 正向: 应有 _truncate_at_word_boundary(thought.thought, 300)
        self.assertIn(
            '_truncate_at_word_boundary(thought.thought, 300)',
            self.body,
            'normal log 必须调 helper truncate thought.thought 到 300 word-boundary'
        )

    def test_helper_defined(self):
        """helper 必须存在."""
        self.assertIn(
            'def _truncate_at_word_boundary(',
            self.body,
            'helper _truncate_at_word_boundary 必须定义'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
