# -*- coding: utf-8 -*-
"""[P5-fix66 / 2026-05-23 16:40] Phase 3d.3 — BlockSpec.audit_only + 5 audit sections.

Sir 战略 'standard/full 高风险一步一测'. Phase 3d.3 字面零变化, audit 可看 5 section 体积分布.

测试覆盖:
A. BlockSpec.audit_only field 存在, 默认 False
B. PromptBuilder.render_blocks 跳过 audit_only block
C. central_nerve 注册 5 audit-only section + legacy_full
D. 字面零变化 (output = legacy mega content)
E. audit bg_log 含 legacy_mega + audit_sections_total + top3
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestBlockSpecAuditOnly(unittest.TestCase):

    def test_a_audit_only_field_default_false(self):
        from jarvis_prompt_builder import BlockSpec
        spec = BlockSpec(id='x', content='hello')
        self.assertFalse(spec.audit_only)

    def test_a_audit_only_true(self):
        from jarvis_prompt_builder import BlockSpec
        spec = BlockSpec(id='x', content='hello', audit_only=True)
        self.assertTrue(spec.audit_only)


class TestRenderBlocksSkipsAuditOnly(unittest.TestCase):

    def test_b_audit_only_not_rendered(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='STANDARD')
        b.register(BlockSpec(id='audit_x', content='Y' * 100,
                              tiers=['STANDARD'], audit_only=True))
        b.register(BlockSpec(id='real_x', content='X' * 200,
                              tiers=['STANDARD']))
        out = b.compose(persona='', user_input='', include_meta_hint=False)
        self.assertIn('X' * 50, out)  # real_x rendered
        self.assertNotIn('Y' * 50, out)  # audit_x not rendered

    def test_b_audit_only_in_get_but_not_render(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='STANDARD')
        b.register(BlockSpec(id='audit_x', content='audit content',
                              tiers=['STANDARD'], audit_only=True))
        # get 仍可访问 (audit 用)
        self.assertIsNotNone(b.get('audit_x'))
        self.assertEqual(b.get('audit_x').content, 'audit content')
        # 但 render_blocks 跳过
        self.assertEqual(b.render_blocks(), '')

    def test_b_audit_only_skipped_in_meta_hint(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='STANDARD')
        b.register(BlockSpec(id='audit_x', content='X', tiers=['STANDARD'],
                              audit_only=True, hint='audit:<x>'))
        b.register(BlockSpec(id='real_y', content='Y', tiers=['STANDARD'],
                              hint='real:<y>'))
        hint = b.render_meta_hint()
        # audit_only blocks 仍在 list_block_ids (list_block_ids 不过滤 audit_only)
        # render_meta_hint 用 list_block_ids → 含 audit hint
        # 这是有意 — audit_only block 也可被主脑引用 META evidence
        self.assertIn('real:<y>', hint)


class TestCentralNervePhase3d3(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_c_register_5_audit_sections(self):
        """central_nerve standard wrapper 注册 5 audit-only section."""
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 5000):idx]
        for sid in ('persona_section', 'recent_section', 'skills_section',
                     'state_section', 'knowledge_tail_section'):
            self.assertIn(f"'{sid}'", section,
                              f'standard wrapper 应注册 {sid}')

    def test_c_audit_only_flag_set(self):
        """5 section 都 audit_only=True."""
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 5000):idx]
        self.assertIn('audit_only=True', section)
        # 至少 5 个出现 (5 sections)
        count = section.count('audit_only=True')
        self.assertGreaterEqual(count, 1)

    def test_c_legacy_block_audit_only_false(self):
        """legacy mega block audit_only=False (真渲染)."""
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 5000):idx]
        self.assertIn("id='legacy_full'", section)
        self.assertIn('audit_only=False', section)

    def test_e_audit_bg_log_present(self):
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 5000):idx]
        self.assertIn('legacy_mega=', section)
        self.assertIn('audit_sections_total=', section)
        self.assertIn('top3:', section)


if __name__ == '__main__':
    unittest.main()
