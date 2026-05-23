# -*- coding: utf-8 -*-
"""[P5-fix59 / 2026-05-23 16:13] Phase 3c — SHORT_CHAT template 迁 PromptBuilder.

Sir 战略 '一步一步来'. WAKE_ONLY/REMINDER_FIRING/light/FACTUAL_RECALL 4 个 template
都迁好 + Sir 真测 FACTUAL_RECALL 完美治 15:27 hallucinate 痛点后, 推 Phase 3c SHORT_CHAT.

SHORT_CHAT 是 Sir **一般对话** 默认 tier (短句不属 WAKE_ONLY/FACTUAL_RECALL).

测试覆盖:
A. SHORT_CHAT tier 真走 builder
B. 含 stm/skills/tool_honesty/promise_mini/active_plan/event_bus/attention/working_feed/correction/sensor/clock/l2 等 20+ blocks
C. sensor salience=0.85, promise_mini salience=0.85, how_to_respond salience=0.85 (高优)
D. fallback 老路径仍在
E. include_meta_hint=True
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestShortChatBuilder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_short_chat_uses_builder(self):
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:")
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 12000]
        self.assertIn('PromptBuilder', section)
        self.assertIn("tier='SHORT_CHAT'", section)

    def test_b_includes_core_blocks(self):
        """SHORT_CHAT 注册核心 blocks."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:")
        section = self.src[idx:idx + 12000]
        for block_id in ('stm', 'skills', 'tool_honesty', 'promise_mini',
                          'active_plan', 'event_bus', 'attention',
                          'working_feed', 'tone', 'how_to_respond',
                          'time_persona', 'correction', 'sensor', 'clock', 'l2'):
            self.assertIn(f"id='{block_id}'", section,
                              f'SHORT_CHAT 应注册 block "{block_id}"')

    def test_c_high_salience_blocks(self):
        """关键 block salience 0.85+."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:")
        section = self.src[idx:idx + 12000]
        # promise_mini
        pi = section.find("id='promise_mini'")
        self.assertGreater(pi, 0)
        self.assertIn('salience=0.85', section[pi:pi + 200])
        # how_to_respond
        hi = section.find("id='how_to_respond'")
        self.assertGreater(hi, 0)
        self.assertIn('salience=0.85', section[hi:hi + 200])
        # sensor
        si = section.find("id='sensor'")
        self.assertGreater(si, 0)
        self.assertIn('salience=0.85', section[si:si + 200])

    def test_d_fallback_present(self):
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:")
        section = self.src[idx:idx + 15000]
        self.assertIn('except Exception:', section)
        self.assertIn('fallback 老 f-string', section)

    def test_e_meta_hint_enabled(self):
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:")
        section = self.src[idx:idx + 12000]
        self.assertIn('include_meta_hint=True', section)


if __name__ == '__main__':
    unittest.main()
