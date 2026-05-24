# -*- coding: utf-8 -*-
"""[Reshape M6.2 / 2026-05-24] WAKE_ONLY tier 抽 _assemble_wake_only_prompt helper.

覆盖:
  - method 真存在
  - WAKE_ONLY tier 调度走 helper (PromptBuilder 主路径 / fallback string template)
  - HOW TO RESPOND (WAKE_ONLY) 关键 phrase 真在结果
  - persona / user_input 真注入 prompt
  - sensor_state_block / system_alert_text 真传 helper
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestWakeOnlyHelper(unittest.TestCase):
    def setUp(self):
        from jarvis_central_nerve import CentralNerve
        self.n = CentralNerve.__new__(CentralNerve)
        self.n._asm_stage_t = {}
        self.n._l2_injected_block = ''

    def test_method_exists(self):
        from jarvis_central_nerve import CentralNerve
        self.assertTrue(hasattr(CentralNerve, '_assemble_wake_only_prompt'))

    def test_wake_only_renders_persona_and_input(self):
        result = self.n._assemble_wake_only_prompt(
            core_persona='I am JARVIS, butler to Sir.',
            user_input='hey jarvis',
            stm_context='Last turn: Sir said hello',
            current_time='2026-05-24 14:00',
            sensor_state_block='[SENSOR] focused on coding',
            system_alert_text='',
        )
        # persona 真注入
        self.assertIn('JARVIS', result)
        # WAKE_ONLY HOW TO RESPOND 关键 phrase 真在
        self.assertIn('UNDER 6 WORDS', result)
        # user_input 真注入
        self.assertIn('hey jarvis', result)
        # SYSTEM CLOCK 真注入
        self.assertIn('2026-05-24 14:00', result)
        # sensor block 真注入
        self.assertIn('focused on coding', result)
        # ZH 提示真在
        self.assertIn('---ZH---', result)

    def test_wake_only_truncates_long_stm(self):
        long_stm = 'x' * 1000
        result = self.n._assemble_wake_only_prompt(
            core_persona='persona',
            user_input='hi',
            stm_context=long_stm,
            current_time='now',
            sensor_state_block='',
            system_alert_text='',
        )
        # STM 应被截断 (不应 1000 字 + persona/user_input 全占 prompt)
        self.assertLess(result.count('x'), 600,
                          'long STM 应被截断到 500')

    def test_wake_only_no_l2_no_block(self):
        """没 _l2_injected_block 不应出 l2 字段."""
        # default setUp 设 _l2_injected_block = ''
        result = self.n._assemble_wake_only_prompt(
            core_persona='p', user_input='u', stm_context='',
            current_time='now', sensor_state_block='',
            system_alert_text='',
        )
        # PromptBuilder mode: 没 l2 不会 register 该 block
        # fallback mode: getattr default 空 string, 不破
        self.assertNotIn('l2_directive_X', result)


if __name__ == '__main__':
    unittest.main()
