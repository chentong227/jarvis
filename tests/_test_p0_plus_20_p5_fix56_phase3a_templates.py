# -*- coding: utf-8 -*-
"""[P5-fix56 / 2026-05-23 16:00] Phase 3a — REMINDER_FIRING + light mode 迁 builder.

Sir 战略: '一步一步来', WAKE_ONLY (Phase 2) 实测通过后, 推 Phase 3a 2 简单 template.

测试覆盖:
A. REMINDER_FIRING (mode=mail) 用 builder
B. mode=light 用 builder
C. 两者 fallback 老路径都存在 (准则 8 不破现有)
D. mode=mail builder 不写 META (极简)
E. mode=light builder 写 META hint
F. central_nerve import 不破
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestPhase3aTemplates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_reminder_firing_uses_builder(self):
        """REMINDER_FIRING (mode=mail) 段引用 PromptBuilder."""
        idx = self.src.find('if mode == "mail":')
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 3500]
        self.assertIn('PromptBuilder', section)
        self.assertIn("tier='REMINDER_FIRING'", section)
        self.assertIn("reminder_directive", section)

    def test_b_light_mode_uses_builder(self):
        """mode=light 段引用 PromptBuilder."""
        idx = self.src.find('if mode == "light":')
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 3500]
        self.assertIn('PromptBuilder', section)
        self.assertIn("tier='LIGHT'", section)

    def test_c_both_have_fallback(self):
        """两个 template builder 失败都 fallback 老 f-string."""
        for marker in ('if mode == "mail":', 'if mode == "light":'):
            idx = self.src.find(marker)
            self.assertGreater(idx, 0)
            section = self.src[idx:idx + 4000]
            self.assertIn('except Exception:', section)
            self.assertIn('fallback', section)

    def test_d_mail_no_meta_hint(self):
        """REMINDER_FIRING mode 极简, include_meta_hint=False."""
        idx = self.src.find('if mode == "mail":')
        section = self.src[idx:idx + 3500]
        self.assertIn('include_meta_hint=False', section,
                          'REMINDER_FIRING 极简, 不写 META cheat sheet')

    def test_e_light_with_meta_hint(self):
        """light mode 允许 META 自检, include_meta_hint=True."""
        idx = self.src.find('if mode == "light":')
        section = self.src[idx:idx + 3500]
        self.assertIn('include_meta_hint=True', section,
                          'light mode 允许 META 自检')

    def test_f_central_nerve_import(self):
        """central_nerve 模块 import 不破 (无 syntax / circular)."""
        import jarvis_central_nerve  # noqa: F401
        self.assertTrue(True)


class TestBuilderRendersTemplate(unittest.TestCase):
    """直接调 builder 模拟 REMINDER_FIRING + light 渲染."""

    def test_reminder_firing_complete(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        rb = PromptBuilder(tier='REMINDER_FIRING')
        rb.register(BlockSpec(
            id='reminder_directive',
            content='REMINDER DELIVERY MODE: Sir is waiting...',
            tiers=['REMINDER_FIRING']))
        rb.register(BlockSpec(
            id='clock',
            content='[SYSTEM CLOCK]: 2026-05-23 16:00',
            tiers=['REMINDER_FIRING']))
        rb.register(BlockSpec(
            id='sensor',
            content='[SENSOR STATE]: active_window: "VSCode"',
            tiers=['REMINDER_FIRING']))
        out = rb.compose(
            persona='You are Jarvis.',
            user_input='[REMINDER FIRING NOW] drink water',
            footer='[BILINGUAL]: speak English. ---ZH---',
            include_meta_hint=False,
        )
        self.assertIn('REMINDER DELIVERY MODE', out)
        self.assertIn('SYSTEM CLOCK', out)
        self.assertIn('SENSOR STATE', out)
        self.assertIn('[BILINGUAL]', out)
        self.assertIn('drink water', out)

    def test_light_mode_complete(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        lb = PromptBuilder(tier='LIGHT')
        lb.register(BlockSpec(
            id='context', content='[CONTEXT]: morning',
            tiers=['LIGHT']))
        lb.register(BlockSpec(
            id='correction', content='[CORRECTION]: previous mistake noted',
            tiers=['LIGHT']))
        lb.register(BlockSpec(
            id='clock', content='[SYSTEM CLOCK]: 2026-05-23 16:00',
            tiers=['LIGHT']))
        lb.register(BlockSpec(
            id='sensor', content='[SENSOR STATE]: ...',
            tiers=['LIGHT'], hint='sensor:<field>'))
        out = lb.compose(
            persona='You are Jarvis.',
            user_input='Hello',
            include_meta_hint=True,
        )
        self.assertIn('CONTEXT', out)
        self.assertIn('CORRECTION', out)
        self.assertIn('META EVIDENCE CHEAT SHEET', out)
        self.assertIn('sensor:<field>', out)
        self.assertIn('User: Hello', out)


if __name__ == '__main__':
    unittest.main()
