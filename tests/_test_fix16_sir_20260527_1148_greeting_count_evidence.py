# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 11:48 真痛 anchor] Good morning 重复 5+ 次治本.

Sir 真痛: 早上 8 点起后 jarvis 连说 5 次 "Good morning, Sir"
  (jarvis_20260527_073636.log L743/817/925/1179/1827/2343)

根因: `is_first_today` consume 后 prompt 没注入"今天已 greet N 次, 上次 X min 前"
evidence, 主脑看 STM/SOUL 编 "I see you're reviewing X" 仍以 "Good morning" 起头.

修法 (准则 6 数据强耦合):
  P1. ReturnSentinel track today greet count (跨午夜 reset)
  P2. nudge_ctx 无条件注入 greetings_today_count + last_greeting_min_ago
  P3. return_greeting directive 无条件 render evidence block (不只 morning case)
  P4. directive 加 semantic: count >= 1 → 不再 generic opener; count >= 3 → 考虑 [SILENCE]

测试 (4 testcase):
  - G1: ReturnSentinel __init__ 含 _greetings_today_count = 0
  - G2: ReturnSentinel __init__ 含 _last_greeting_day = ""
  - G3: return_greeting directive 无条件含 greetings_today_count evidence (任 ctx 都注)
  - G4: return_greeting directive 含 SILENCE/evidence-only semantic 准则 (count>=1 不 greet)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestG1G2ReturnSentinelGreetingState(unittest.TestCase):
    """ReturnSentinel 必有 _greetings_today_count + _last_greeting_day."""

    def test_g1_greetings_today_count_init_zero(self):
        """ReturnSentinel.__init__ 应初始化 _greetings_today_count = 0."""
        from jarvis_return_sentinel import ReturnSentinel
        worker = MagicMock()
        rs = ReturnSentinel(worker)
        self.assertTrue(hasattr(rs, '_greetings_today_count'),
            'ReturnSentinel 必有 _greetings_today_count 字段')
        self.assertEqual(rs._greetings_today_count, 0,
            '初始化时今日 greet count 应 = 0')

    def test_g2_last_greeting_day_init_empty(self):
        """ReturnSentinel.__init__ 应初始化 _last_greeting_day = ''."""
        from jarvis_return_sentinel import ReturnSentinel
        worker = MagicMock()
        rs = ReturnSentinel(worker)
        self.assertTrue(hasattr(rs, '_last_greeting_day'),
            'ReturnSentinel 必有 _last_greeting_day 字段 (跨午夜 reset 判断)')
        self.assertEqual(rs._last_greeting_day, '',
            '初始化时 last_greeting_day 应 = "" (跨午夜 reset 锚)')


class TestG3DirectiveAlwaysRendersGreetingEvidence(unittest.TestCase):
    """return_greeting directive 必须无条件含 greetings_today_count evidence."""

    def test_g3_directive_includes_greetings_today_count(self):
        """检 jarvis_chat_bypass.py return_greeting directive 含
        greetings_today_count + last_greeting_min_ago evidence 注入语法.
        无条件 render (不仅 is_first_today=True 时).
        """
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # directive source 必含这两 evidence 字段名
        self.assertIn("greetings_today_count", src,
            'return_greeting directive 必无条件含 greetings_today_count evidence')
        self.assertIn("last_greeting_min_ago", src,
            'return_greeting directive 必含 last_greeting_min_ago evidence')
        # 必含 [GREETING EVIDENCE] block label
        self.assertIn("[GREETING EVIDENCE", src,
            'directive 必有 [GREETING EVIDENCE] block 标签')


class TestG4DirectiveHasSemanticGuidance(unittest.TestCase):
    """directive 必含 semantic 指引: count>=1 不 greet; count>=3 考虑 SILENCE."""

    def test_g4_directive_has_semantic_no_greet_when_count_geq_1(self):
        """directive 必告主脑: count>=1 不再 generic opener (Good morning 等)."""
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 必含 'greetings_today_count >= 1' semantic 段
        self.assertIn("greetings_today_count >= 1", src,
            'directive 必含 count>=1 semantic 段 (告主脑不再 greet)')
        # 必告主脑别再 "Good morning"
        self.assertIn("'Good morning'", src,
            'directive 必显式列 Good morning 作 forbidden generic opener')
        # 必含 SILENCE 考虑路径
        self.assertIn("greetings_today_count >= 3", src,
            'directive 必含 count>=3 [SILENCE] semantic 段 (准则 1 高效)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
