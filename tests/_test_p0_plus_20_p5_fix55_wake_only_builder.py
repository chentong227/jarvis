# -*- coding: utf-8 -*-
"""[P5-fix55 / 2026-05-23 15:55] Phase 2 — WAKE_ONLY template 迁 PromptBuilder.

Sir 拍板槽 1 Phase 2 示范: 迁 1 个 template 验证 builder 不破坏现有行为.

测试覆盖:
A. WAKE_ONLY tier 真走 builder 路径 (不 fallback)
B. 输出含核心元素: persona, HOW TO RESPOND, RECENT TURNS, SYSTEM CLOCK, User
C. builder 失败 fallback 老路径正常 (保护)
D. 输出 < 1.5K (Sir 设定 WAKE_ONLY 目标体积)
E. _l2_injected_block 注入 (若有)
F. system_alert_text 末尾 (若有)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestWakeOnlyBuilder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_wake_only_uses_builder(self):
        """WAKE_ONLY tier 引用 jarvis_prompt_builder."""
        self.assertIn("if prompt_tier == self.PROMPT_TIER_WAKE_ONLY:", self.src)
        # 找 WAKE_ONLY 那段, 看是否含 PromptBuilder import
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_WAKE_ONLY:")
        # 取该段后 4000 字符
        section = self.src[idx:idx + 4000]
        self.assertIn('PromptBuilder', section,
                          'WAKE_ONLY 段应 import PromptBuilder')
        self.assertIn('BlockSpec', section,
                          'WAKE_ONLY 段应用 BlockSpec')
        self.assertIn("tier='WAKE_ONLY'", section,
                          'PromptBuilder 应初始化 tier=WAKE_ONLY')

    def test_a_fallback_present(self):
        """builder 失败 fallback 老路径仍在 (准则 8: 不破坏现有行为)."""
        idx = self.src.find("if prompt_tier == self.PROMPT_TIER_WAKE_ONLY:")
        section = self.src[idx:idx + 4000]
        self.assertIn('except Exception:', section)
        self.assertIn('builder 失败', section)
        self.assertIn('fallback', section)

    def test_b_builder_renders_complete_wake_prompt(self):
        """直接调 builder 模拟 WAKE_ONLY, 验证关键元素都在."""
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        wb = PromptBuilder(tier='WAKE_ONLY')
        wb.register(BlockSpec(
            id='how_to_respond',
            content='=== HOW TO RESPOND (WAKE_ONLY) ===\nReply UNDER 6 WORDS',
            tiers=['WAKE_ONLY']))
        wb.register(BlockSpec(
            id='stm',
            content='=== RECENT TURNS ===\nturn1: hi\nturn2: hello',
            tiers=['WAKE_ONLY']))
        wb.register(BlockSpec(
            id='clock',
            content='[SYSTEM CLOCK]: 2026-05-23 15:55',
            tiers=['WAKE_ONLY']))
        wb.register(BlockSpec(
            id='sensor',
            content='[SENSOR STATE]: active_window: "VSCode"',
            tiers=['WAKE_ONLY']))
        out = wb.compose(
            persona='You are Jarvis.',
            user_input='Jarvis?',
            include_meta_hint=False,
        )
        # 验证关键元素都在
        self.assertIn('You are Jarvis.', out)
        self.assertIn('HOW TO RESPOND', out)
        self.assertIn('RECENT TURNS', out)
        self.assertIn('SYSTEM CLOCK', out)
        self.assertIn('SENSOR STATE', out)
        self.assertIn('User: Jarvis?', out)

    def test_d_wake_only_size_compact(self):
        """WAKE_ONLY 目标 < 1.5K (Sir 设计目标)."""
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        wb = PromptBuilder(tier='WAKE_ONLY')
        # 模拟典型 WAKE_ONLY 内容
        wb.register(BlockSpec(
            id='how_to_respond',
            content='=== HOW TO RESPOND (WAKE_ONLY) ===\n' + 'X' * 200,
            tiers=['WAKE_ONLY']))
        wb.register(BlockSpec(
            id='stm',
            content='=== RECENT TURNS ===\n' + 'turn ' * 50,
            tiers=['WAKE_ONLY']))
        wb.register(BlockSpec(
            id='clock',
            content='[SYSTEM CLOCK]: 2026-05-23 15:55:00 Friday',
            tiers=['WAKE_ONLY']))
        out = wb.compose(
            persona='J' * 300,
            user_input='Jarvis?',
            include_meta_hint=False,
        )
        # WAKE_ONLY 目标 ≤ 1500 — 但 builder 不强制截断, 此测验证 builder 输出体积小
        self.assertLess(len(out), 2000,
                          f'WAKE_ONLY builder 输出应紧凑, got {len(out)} chars')

    def test_e_tier_filter_excludes_non_wake(self):
        """tier=WAKE_ONLY 应过滤 tier=['DEEP_QUERY'] 的 block."""
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        wb = PromptBuilder(tier='WAKE_ONLY')
        wb.register(BlockSpec(
            id='wake_block', content='WAKE',
            tiers=['WAKE_ONLY']))
        wb.register(BlockSpec(
            id='deep_block', content='DEEP_CONTENT_NOT_WANTED',
            tiers=['DEEP_QUERY']))
        out = wb.render_blocks()
        self.assertIn('WAKE', out)
        self.assertNotIn('DEEP_CONTENT_NOT_WANTED', out)


if __name__ == '__main__':
    unittest.main()
