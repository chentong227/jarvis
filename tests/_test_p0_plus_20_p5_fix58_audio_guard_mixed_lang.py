# -*- coding: utf-8 -*-
"""[P5-fix58 / 2026-05-23 16:11] Audio Guard 中英混排 reply 不再误判中文 lean.

Sir 16:08 真测痛点:
  主脑 reply 'It appears to be a text snippet on your clipboard, Sir.
  It reads: "现在优先找外女".' (英文 67 char + 中文 7 char, 占比 9.3%)
  被老 `_sentence_is_chinese_lean` 判定为中文为主 (因 cjk >= 3) → 整句进 subtitle
  mode → TTS 不发声.
  Sir: '复制的内容那句话不发声 = bug, 要发声'.

测试覆盖:
A. 英文主体含 7 字中文 quote → 不算中文 lean (TTS 应正常发声)
B. 纯中文 → 算中文 lean
C. 中英 50/50 → 算中文 lean (占比 > 30%)
D. 空 sentence → False
E. 单个中文字 → False (人名场景)
F. 英文含 2 字中文 quote → False (短引用)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestAudioGuardMixedLang(unittest.TestCase):

    def test_a_english_main_with_chinese_quote(self):
        """英文 67 char + 中文 7 char quote → 占比 ~9% → 不算 lean (TTS 发声)."""
        from jarvis_safety import _sentence_is_chinese_lean
        s = 'It appears to be a text snippet on your clipboard, Sir. It reads: "现在优先找外女".'
        self.assertFalse(_sentence_is_chinese_lean(s),
                          f'英文主体含中文 quote 应正常发声 (占比 ~9%), got True')

    def test_b_pure_chinese(self):
        """纯中文应判 lean (subtitle mode)."""
        from jarvis_safety import _sentence_is_chinese_lean
        self.assertTrue(_sentence_is_chinese_lean('这是一句完全中文的回复'))

    def test_c_half_chinese(self):
        """中文占比 > 30% 判 lean."""
        from jarvis_safety import _sentence_is_chinese_lean
        # "Hello 你好" 5 ascii + 1 space + 2 cjk = 8 total, 占比 25% → False
        # "Hi 你好世界" 2 ascii + 1 space + 4 cjk = 7 total, 占比 57% → True
        self.assertTrue(_sentence_is_chinese_lean('Hi 你好世界吧'),
                          'Hi 你好世界吧 应判 lean (占比 > 30%)')

    def test_d_empty(self):
        from jarvis_safety import _sentence_is_chinese_lean
        self.assertFalse(_sentence_is_chinese_lean(''))
        self.assertFalse(_sentence_is_chinese_lean(None))

    def test_e_single_chinese_char(self):
        """单个中文字 (人名场景) 不算 lean."""
        from jarvis_safety import _sentence_is_chinese_lean
        self.assertFalse(_sentence_is_chinese_lean('Hello 张, how are you today, my friend?'))

    def test_f_short_chinese_quote(self):
        """英文 reply 含 2 字短引 → 不 lean."""
        from jarvis_safety import _sentence_is_chinese_lean
        s = 'The user said: "好的", and then continued working on the task.'
        self.assertFalse(_sentence_is_chinese_lean(s))


if __name__ == '__main__':
    unittest.main()
