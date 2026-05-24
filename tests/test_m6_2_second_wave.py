# -*- coding: utf-8 -*-
"""[Reshape M6.2 second wave / 2026-05-24] FACTUAL_RECALL + SHORT_CHAT helper.

覆盖:
  - 2 个 method 真存在
  - FACTUAL_RECALL helper 渲染基本内容 (HOW TO RESPOND / FACTUAL_RECALL)
  - SHORT_CHAT helper 渲染基本内容 (PROMISE_PROTOCOL_DIRECTIVE_MINI 等)
  - persona / user_input 真注入
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestFactualRecallHelper(unittest.TestCase):
    def setUp(self):
        from jarvis_central_nerve import CentralNerve
        self.n = CentralNerve.__new__(CentralNerve)
        self.n._asm_stage_t = {}
        self.n._l2_injected_block = ''
        self.n.working_feed = None
        self.n.event_bus = None
        self.n.tone_selector = None

    def test_method_exists(self):
        from jarvis_central_nerve import CentralNerve
        self.assertTrue(hasattr(CentralNerve, '_assemble_factual_recall_prompt'))

    def test_renders_persona_and_input(self):
        result = self.n._assemble_factual_recall_prompt(
            core_persona='I am JARVIS',
            user_input='what did I just copy',
            stm_context='Sir copied X 30s ago',
            current_time='2026-05-24 14:00',
            current_hour=14,
            ledger_data={},
            sensor_state_block='[SENSOR] coding mode',
            system_alert_text='',
            yesterday_block='',
            open_threads_block='',
            project_block='',
            available_skills_block='',
        )
        self.assertIn('JARVIS', result)
        self.assertIn('what did I just copy', result)
        self.assertIn('FACTUAL_RECALL', result)
        # FACTUAL_RECALL 关键 phrase 真在
        self.assertIn('DO NOT call any tool', result.replace('—', '-'))


class TestShortChatHelper(unittest.TestCase):
    def setUp(self):
        from jarvis_central_nerve import CentralNerve
        self.n = CentralNerve.__new__(CentralNerve)
        self.n._asm_stage_t = {}
        self.n._l2_injected_block = ''
        self.n.event_bus = None
        self.n.tone_selector = None
        self.n.working_feed = None
        self.n.plan_ledger = None

    def test_method_exists(self):
        from jarvis_central_nerve import CentralNerve
        self.assertTrue(hasattr(CentralNerve, '_assemble_short_chat_prompt'))

    def test_renders_persona_and_input(self):
        result = self.n._assemble_short_chat_prompt(
            core_persona='I am JARVIS',
            user_input='hey what time',
            stm_context='Sir asked time',
            current_time='2026-05-24 14:00',
            current_hour=14,
            ledger_data={},
            sensor_state_block='',
            system_alert_text='',
            yesterday_block='',
            open_threads_block='',
            project_block='',
            available_skills_block='',
            how_to_respond='Reply briefly.',
            time_persona='afternoon coding',
            context_str='',
            pc_block_value='',
            correction_context='',
            style_adjustment='',
            ledger_str='No status data',
        )
        self.assertIn('JARVIS', result)
        self.assertIn('hey what time', result)


if __name__ == '__main__':
    unittest.main()
