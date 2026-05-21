# -*- coding: utf-8 -*-
"""[P5-Gap4 / 2026-05-21 18:30] Directive Self-Awareness — purpose_short + meta block

Sir 22:19 真痛点: 主脑被 8 条 directive cluster 淹, 看不到全貌, over-correct.
治根: 加 purpose_short + [DIRECTIVES FIRED THIS TURN] 元层 block. 主脑能"鸟瞰"
+ reason 哪些适用此刻 / 哪些 false positive. 详 docs/JARVIS_DIRECTIVE_SELF_AWARENESS.md
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_DirectiveDataclassExtension(unittest.TestCase):
    """Directive dataclass 加 purpose_short field."""

    def test_directive_has_purpose_short_field(self):
        from jarvis_directives import Directive
        # 默认空字符串
        from dataclasses import fields
        f_names = {f.name for f in fields(Directive)}
        self.assertIn('purpose_short', f_names,
                       'Directive dataclass 必须有 purpose_short field')

    def test_directive_purpose_short_default_empty(self):
        """purpose_short 默认空字符串 (backward compat)."""
        from jarvis_directives import Directive
        d = Directive(id='_test_', text='', trigger=lambda c: False)
        self.assertEqual(d.purpose_short, '')


class TestB_BootstrapMergesSeedAndJSON(unittest.TestCase):
    """[P5-Gap4-bootstrap-merge] JSON + seed merge — JSON 缺的 seed 仍 register."""

    def test_p5_key_directives_registered(self):
        """P5 关键 directive (.py seed 但 JSON 缺) 应该被 register."""
        from jarvis_directives import DirectiveRegistry, bootstrap_default_registry
        reg = DirectiveRegistry()
        bootstrap_default_registry(reg)
        # 这 3 条只在 .py seed, JSON 缺 → 老 bootstrap 不 register, 新 bootstrap merge 后 register
        critical = [
            'unsolicited_callback_guard',         # P12
            'integrity_watcher_report_use',        # P11
            'morning_warmth_priority',              # P11
        ]
        for did in critical:
            d = reg.directives.get(did)
            self.assertIsNotNone(
                d,
                f"{did} 必须 register (P5-Gap4 修 bootstrap merge bug)")
            self.assertEqual(d.state, 'active', f"{did} state 必须 active")


class TestC_PurposeShortFilledForP10Plus(unittest.TestCase):
    """P10+ 重点 directive 必须有 purpose_short (鸟瞰用)."""

    def test_p10_plus_directives_have_purpose_short(self):
        from jarvis_directives import DirectiveRegistry, bootstrap_default_registry
        reg = DirectiveRegistry()
        bootstrap_default_registry(reg)

        critical_with_ps = {
            'no_hallucinated_tool_use_judge',
            'unsolicited_callback_guard',
            'morning_warmth_priority',
            'over_offer_called_out_judge',
            'integrity_watcher_report_use',
            'capability_boundary_judge',
            'memory_update_honesty',
            'past_action_honesty',
            'bilingual_directive',
        }
        for did in critical_with_ps:
            d = reg.directives.get(did)
            self.assertIsNotNone(d, f"{did} 必须 register")
            self.assertTrue(
                bool((d.purpose_short or '').strip()),
                f"{did} (P{d.priority}) 必须有 purpose_short — Gap 4 鸟瞰用"
            )
            self.assertLess(
                len(d.purpose_short), 90,
                f"{did} purpose_short 必须 < 90 chars (鸟瞰简洁)"
            )


class TestD_AssemblePromptIncludesMetaBlock(unittest.TestCase):
    """_assemble_prompt 应当注入 [DIRECTIVES FIRED THIS TURN] meta block."""

    def test_central_nerve_renders_meta_block(self):
        """central_nerve.py 含 meta block 的代码 (静态检)."""
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 关键 marker
        self.assertIn('[DIRECTIVES FIRED THIS TURN', src,
                       'central_nerve 应渲染 [DIRECTIVES FIRED THIS TURN] meta block')
        self.assertIn('HOW TO USE THIS META-VIEW', src,
                       '应含 HOW TO USE THIS META-VIEW 子段教主脑用法')
        self.assertIn('purpose_short', src,
                       '应使用 directive.purpose_short 字段')


class TestE_CLIDumpAvailable(unittest.TestCase):
    """scripts/directive_meta_dump.py 可用."""

    def test_cli_script_exists(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'directive_meta_dump.py'
        )
        self.assertTrue(os.path.exists(path),
                         'scripts/directive_meta_dump.py 必须存在')


if __name__ == '__main__':
    unittest.main()
