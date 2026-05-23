# -*- coding: utf-8 -*-
"""[P5-fix64 / 2026-05-23 16:28] Phase 3d.2 — BlockSpec.metadata + PromptBuilder audit helpers.

Sir 战略 'standard/full 风险高地方一步一测'. Phase 3d 拆 3 子 commit:
  3d.1 (commit 72149c3): zero textual change, builder wrapper
  3d.2 (本 commit): BlockSpec.metadata 内省字段 + audit helpers (total_chars/size_breakdown/audit_summary) + central_nerve bg_log
  3d.3 (后续): 真拆 mega block 成 ~30 细 block (字面仍一致)

3d.2 = audit infrastructure 准备, Phase 4 瘦身用. 字面仍零变化.

测试覆盖:
A. BlockSpec.metadata field 存在
B. BlockSpec.char_len() 工作
C. PromptBuilder.total_chars() / size_breakdown / audit_summary
D. central_nerve standard/full mega block 含 metadata (logical_sections / phase / split_pending)
E. central_nerve 含 audit bg_log
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestBlockSpecMetadata(unittest.TestCase):

    def test_a_metadata_field_exists(self):
        from jarvis_prompt_builder import BlockSpec
        spec = BlockSpec(id='x', content='hello', tiers=['CHAT'],
                          metadata={'sections': ['a', 'b']})
        self.assertEqual(spec.metadata, {'sections': ['a', 'b']})

    def test_a_metadata_default_empty(self):
        from jarvis_prompt_builder import BlockSpec
        spec = BlockSpec(id='x', content='hello', tiers=['CHAT'])
        self.assertEqual(spec.metadata, {})

    def test_b_char_len(self):
        from jarvis_prompt_builder import BlockSpec
        self.assertEqual(BlockSpec(id='x', content='hello').char_len(), 5)
        self.assertEqual(BlockSpec(id='x', content='').char_len(), 0)


class TestPromptBuilderAudit(unittest.TestCase):

    def test_c_total_chars(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='a', content='hello', tiers=['CHAT']))
        b.register(BlockSpec(id='b', content='world!', tiers=['CHAT']))
        self.assertEqual(b.total_chars(), 11)

    def test_c_total_chars_filters_inactive(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='a', content='hello', tiers=['CHAT']))
        b.register(BlockSpec(id='b', content='ignored', tiers=['DEEP']))
        self.assertEqual(b.total_chars(), 5)

    def test_c_size_breakdown_desc(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='CHAT')
        b.register(BlockSpec(id='small', content='hi', tiers=['CHAT']))
        b.register(BlockSpec(id='big', content='X' * 100, tiers=['CHAT']))
        b.register(BlockSpec(id='mid', content='Y' * 50, tiers=['CHAT']))
        top = b.size_breakdown(top_k=3)
        self.assertEqual(top[0], ('big', 100))
        self.assertEqual(top[1], ('mid', 50))
        self.assertEqual(top[2], ('small', 2))

    def test_c_audit_summary(self):
        from jarvis_prompt_builder import PromptBuilder, BlockSpec
        b = PromptBuilder(tier='STANDARD')
        b.register(BlockSpec(id='a', content='X' * 100, tiers=['STANDARD']))
        b.register(BlockSpec(id='b', content='Y' * 200, tiers=['STANDARD']))
        s = b.audit_summary()
        self.assertEqual(s['tier'], 'STANDARD')
        self.assertEqual(s['n_blocks'], 2)
        self.assertEqual(s['total_chars'], 300)
        self.assertEqual(s['block_ids'], ['a', 'b'])
        self.assertEqual(s['top5'][0], ('b', 200))


class TestCentralNerveAuditWired(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_d_standard_has_metadata(self):
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 6000):idx]
        self.assertIn('metadata=', section)
        # Phase 3d.3 替换 'logical_sections' / 'phase': '3d.2' 为 5 sections
        # 但仍含 metadata + phase 信息 (新的 3d.3)
        self.assertIn("'phase':", section)

    def test_e_audit_bg_log_present(self):
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 6000):idx]
        self.assertIn('[PromptBuilder/STANDARD]', section)
        # Phase 3d.3 改 audit log: legacy_mega + audit_sections_total + top3
        self.assertIn('legacy_mega=', section)
        self.assertIn('audit_sections_total=', section)


if __name__ == '__main__':
    unittest.main()
