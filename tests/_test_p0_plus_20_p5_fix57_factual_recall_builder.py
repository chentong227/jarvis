# -*- coding: utf-8 -*-
"""[P5-fix57 / 2026-05-23 16:05] Phase 3b — FACTUAL_RECALL template 迁 PromptBuilder.

Sir 战略 '一步一步来' — Phase 3a (mail/light) 后, 推 Phase 3b FACTUAL_RECALL.

FACTUAL_RECALL 是 Sir 真实问 'X 多久' 的 tier — sensor_state_block 高优 (salience=0.90).
Sir 15:27 痛点 '我在 QQ 多久' 主脑 hallucinate 19 min 就走这个 tier.

测试覆盖:
A. FACTUAL_RECALL tier 真走 builder
B. 含 sensor / working_feed / event_bus / attention / stm / clock 13 blocks
C. sensor salience=0.90 高优 (Sir 痛点根因 evidence)
D. fallback 老路径仍在
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestFactualRecallBuilder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_factual_recall_uses_builder(self):
        """FACTUAL_RECALL tier 引用 PromptBuilder."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:")
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 6000]
        self.assertIn('PromptBuilder', section)
        self.assertIn("tier='FACTUAL_RECALL'", section)

    def test_b_includes_13_blocks(self):
        """FACTUAL_RECALL builder 注册 13 个 block."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:")
        section = self.src[idx:idx + 10000]
        # 必含的 block id
        for block_id in ('tone', 'how_to_respond', 'yesterday', 'stm',
                          'open_threads', 'project', 'skills', 'event_bus',
                          'attention', 'working_feed', 'clock', 'sensor', 'l2'):
            self.assertIn(f"id='{block_id}'", section,
                              f'FACTUAL_RECALL 应注册 block "{block_id}"')

    def test_c_sensor_block_high_salience(self):
        """sensor block salience=0.90 (FACTUAL_RECALL Sir 问 'X 多久' 真痛点)."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:")
        section = self.src[idx:idx + 10000]
        # 找 sensor block 段
        si = section.find("id='sensor'")
        self.assertGreater(si, 0)
        sensor_part = section[si:si + 500]
        self.assertIn('salience=0.90', sensor_part,
                          'FACTUAL_RECALL sensor 应 salience=0.90 (高优)')

    def test_d_fallback_present(self):
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:")
        section = self.src[idx:idx + 12000]
        self.assertIn('except Exception:', section)
        self.assertIn('fallback 老 f-string', section)

    def test_e_meta_hint_enabled(self):
        """FACTUAL_RECALL 允许 META 自检 (Sir 可 debug evidence trace)."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:")
        section = self.src[idx:idx + 10000]
        self.assertIn('include_meta_hint=True', section)


class TestBuilderRendersFactualRecall(unittest.TestCase):
    """直接调 builder 模拟 FACTUAL_RECALL 渲染."""

    def test_complete_factual_recall_prompt(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        fb = PromptBuilder(tier='FACTUAL_RECALL')
        fb.register(BlockSpec(
            id='how_to_respond',
            content='=== HOW TO RESPOND (FACTUAL_RECALL) ===\nDO NOT call tools',
            tiers=['FACTUAL_RECALL']))
        fb.register(BlockSpec(
            id='working_feed',
            content='[WORKING FEED]: clipboard=hello\\nlast cmd: ls',
            tiers=['FACTUAL_RECALL']))
        fb.register(BlockSpec(
            id='sensor',
            content='[SENSOR STATE]: current_window_stay_s: 45',
            tiers=['FACTUAL_RECALL'], hint='sensor:<field>'))
        out = fb.compose(
            persona='You are Jarvis.',
            user_input='我刚复制的是什么?',
            include_meta_hint=True,
        )
        self.assertIn('HOW TO RESPOND', out)
        self.assertIn('WORKING FEED', out)
        self.assertIn('SENSOR STATE', out)
        self.assertIn('User: 我刚复制的是什么?', out)
        self.assertIn('META EVIDENCE CHEAT SHEET', out)


if __name__ == '__main__':
    unittest.main()
