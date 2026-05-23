# -*- coding: utf-8 -*-
"""[P5-fix61 / 2026-05-23 16:18] Phase 3d.1 — standard/full mode 加 PromptBuilder wrapper.

Sir 战略 (Sir 16:17): 'standard/full 风险最高 → 一步一 commit, 一步一测, 主脑别崩'.

Phase 3d 拆 N 个子 commit:
  - 3d.1 (本 commit): 字面零变化, 仅集成 builder 路径 (整 result 当 1 mega block)
  - 3d.2 (后续): 拆 result 成 5 大 section block
  - 3d.3 (后续): 拆 section 成 30+ 细 block (完成 builder 化)

3d.1 是最小风险 — 主脑 prompt 字面**完全一致**, 仅执行路径走 builder. 验证基础后再增量.

测试覆盖:
A. _assemble_prompt 末尾含 builder route (try jarvis_prompt_builder)
B. 安全闸 (user_input in _via_builder 才接受)
C. fallback 老 result 路径 (准则 8 不破现有)
D. PromptBuilder.compose(persona=X) = X (零变化验证)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestPhase3d1StandardBuilder(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(ROOT / 'jarvis_central_nerve.py', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_standard_route_uses_builder(self):
        """_assemble_prompt 末尾含 builder route."""
        # 找 'return result' 前的 builder route
        idx = self.src.rfind('return result')
        self.assertGreater(idx, 0)
        section = self.src[max(0, idx - 2000):idx]
        self.assertIn('PromptBuilder', section,
                          'standard/full 应集成 PromptBuilder')
        self.assertIn("tier='STANDARD'", section,
                          'PromptBuilder 应 tier=STANDARD')
        self.assertIn('Phase 3d.1', section)

    def test_b_safety_gate_user_input(self):
        """安全闸: user_input in _via_builder 才接受."""
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 2000):idx]
        self.assertIn('user_input in _via_builder', section,
                          '应有安全闸 user_input 在 builder 输出中')

    def test_c_fallback_present(self):
        """fallback 老 result 路径在."""
        idx = self.src.rfind('return result')
        section = self.src[max(0, idx - 2000):idx]
        self.assertIn('except Exception:', section)
        self.assertIn('fallback 老 result', section)


class TestBuilderPassthrough(unittest.TestCase):
    """验证 PromptBuilder.compose(persona=X) = X (字面零变化)."""

    def test_d_compose_persona_only_preserves_content(self):
        from jarvis_prompt_builder import PromptBuilder
        sb = PromptBuilder(tier='STANDARD')
        original = "Hello\n\n=== STM ===\nturn 1: hi\n\nUser: test\n[system_alert]"
        out = sb.compose(
            persona=original,
            user_input='',
            footer='',
            system_alert='',
            include_meta_hint=False,
        )
        # builder 输出应 = original (字面零变化)
        self.assertEqual(out.strip(), original.strip())

    def test_d_compose_with_user_input_appends(self):
        from jarvis_prompt_builder import PromptBuilder
        sb = PromptBuilder(tier='STANDARD')
        out = sb.compose(
            persona='prefix content',
            user_input='hello',
            include_meta_hint=False,
        )
        self.assertIn('prefix content', out)
        self.assertIn('User: hello', out)


if __name__ == '__main__':
    unittest.main()
