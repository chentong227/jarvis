# -*- coding: utf-8 -*-
"""[轴3-L2 / 2026-05-15] Capability-Aware Phrasing — 测试套件

覆盖：
  TestSkillRegistryPromptBlockDirective    — to_prompt_block 必须含 OFFER 强约束 directive
  TestNervePromptInjectionContract         — _assemble_prompt 在 SHORT_CHAT/FACTUAL_RECALL/full
                                             3 个 tier 注入 available_skills_block 的源码契约
  TestNudgePromptInjectionContract         — stream_nudge 在 offer_help / commitment_check /
                                             context_switch_alert 注入 nudge_skills_block
  TestEndToEndPhrasingDirective            — 端到端：渲染 prompt 块含具体 skill 名 + FORBIDDEN

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l2_capability_phrasing.py
"""
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry,
    SkillManifest,
    DANGER_SAFE,
    DANGER_RISKY,
    DANGER_DANGEROUS,
    get_registry,
)


def _make(command='audio.list', danger=DANGER_SAFE, **k):
    base = dict(command=command, module='m', callable_name='c',
                description='d', dangerous_flag=danger)
    base.update(k)
    return SkillManifest(**base)


# ==========================================================================
# to_prompt_block directive 完整性
# ==========================================================================

class TestSkillRegistryPromptBlockDirective(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_block_contains_header_and_directive(self):
        self.reg.register(_make('audio.list', danger=DANGER_SAFE,
                                description='列举音频设备'))
        block = self.reg.to_prompt_block()
        self.assertIn('=== AVAILABLE SKILLS ===', block)
        self.assertIn('FORBIDDEN', block, '块必须含 FORBIDDEN generic offer 强约束')
        self.assertIn('reference one of these', block.lower(),
            '块必须教 LLM 必须 reference 具体 skill')

    def test_block_lists_each_skill_with_metadata(self):
        self.reg.register(_make(
            'audio.list', danger=DANGER_SAFE,
            description='列举音频输出设备',
        ))
        self.reg.register(_make(
            'audio.set_volume', danger=DANGER_RISKY,
            description='设置媒体音量',
            args_schema={'level': {'type': 'int', 'range': [0, 100]}},
        ))
        block = self.reg.to_prompt_block()
        self.assertIn('audio.list', block)
        self.assertIn('audio.set_volume', block)
        self.assertIn('safe', block, '应标 dangerous_flag')
        self.assertIn('risky', block)

    def test_filter_safe_only_excludes_risky_and_dangerous(self):
        self.reg.register(_make('audio.list', danger=DANGER_SAFE))
        self.reg.register(_make('audio.set', danger=DANGER_RISKY))
        self.reg.register(_make('file.delete', danger=DANGER_DANGEROUS))
        block = self.reg.to_prompt_block(filter_safe_only=True)
        self.assertIn('audio.list', block)
        self.assertNotIn('audio.set', block)
        self.assertNotIn('file.delete', block)

    def test_empty_registry_block_has_fallback(self):
        block = self.reg.to_prompt_block()
        self.assertIn('no healthy skills registered', block)


# ==========================================================================
# _assemble_prompt 注入 available_skills_block 源码契约
# ==========================================================================

class TestNervePromptInjectionContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_marker_present(self):
        self.assertIn('[轴3-L2 / 2026-05-15]', self.src,
            'jarvis_nerve.py 必须有 [轴3-L2] marker')

    def test_available_skills_block_computed_once(self):
        """available_skills_block 必须在 _assemble_prompt 顶部计算一次（动态、不 cache）"""
        m = re.search(
            r'def _assemble_prompt.*?available_skills_block\s*=\s*""\s*\n.*?'
            r'from jarvis_skill_registry import get_registry.*?'
            r'available_skills_block\s*=\s*get_registry\(\)\.to_prompt_block',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            '_assemble_prompt 必须计算 available_skills_block（动态不 cache）')

    def test_short_chat_tier_injects_skills_block(self):
        """SHORT_CHAT prompt 必须含 {available_skills_block}"""
        m = re.search(
            r'PROMPT_TIER_SHORT_CHAT.*?return f""".*?\{available_skills_block\}',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'SHORT_CHAT tier 必须注入 available_skills_block')

    def test_factual_recall_tier_injects_skills_block(self):
        m = re.search(
            r'PROMPT_TIER_FACTUAL_RECALL.*?return f""".*?\{available_skills_block\}',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'FACTUAL_RECALL tier 必须注入 available_skills_block')

    def test_full_mode_injects_skills_block(self):
        """full mode (默认 / DEEP_QUERY / TOOL_REQUEST / CRITICAL) 必须注入"""
        # full mode 的 result = f"""...""" 或后续大 prompt 必须含 available_skills_block
        # 全文搜：available_skills_block 占位至少出现 3 次（3 个 tier）
        count = self.src.count('{available_skills_block}')
        self.assertGreaterEqual(count, 3,
            f'available_skills_block 占位至少出现 3 次（FACTUAL_RECALL/SHORT_CHAT/full），实际 {count}')

    def test_imports_get_registry(self):
        self.assertIn('from jarvis_skill_registry import get_registry', self.src,
            'jarvis_nerve.py 必须 from jarvis_skill_registry import get_registry')


# ==========================================================================
# stream_nudge 注入 nudge_skills_block 源码契约
# ==========================================================================

class TestNudgePromptInjectionContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_stream_nudge_computes_skills_block_for_offer_types(self):
        """stream_nudge 必须为 offer_help / commitment_check / context_switch_alert
        几类 nudge 计算 nudge_skills_block"""
        m = re.search(
            r'nudge_skills_block\s*=\s*""\s*\n\s*if nudge_type in \([^\)]*offer_help',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'stream_nudge 必须为 offer_help 类 nudge 计算 nudge_skills_block')

    def test_stream_nudge_uses_safe_filter(self):
        """nudge prompt 注入只限 safe（不暴露 dangerous skill 给 LLM 主动 offer）"""
        m = re.search(
            r'nudge_skills_block\s*=.*?to_prompt_block\([^)]*filter_safe_only\s*=\s*True',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'stream_nudge 的 to_prompt_block 调用必须 filter_safe_only=True')

    def test_stream_nudge_prompt_contains_offer_integrity_directive(self):
        """nudge prompt 必须含 [轴3-L2 OFFER INTEGRITY] directive"""
        self.assertIn('OFFER INTEGRITY', self.src,
            'stream_nudge prompt 必须含 OFFER INTEGRITY directive')
        self.assertIn('FORBIDDEN', self.src,
            'OFFER INTEGRITY directive 必须明确 FORBIDDEN generic offer')
        self.assertIn("That's outside my reach", self.src,
            'OFFER INTEGRITY 必须教 LLM "That\'s outside my reach" 的兜底措辞')


# ==========================================================================
# 端到端：渲染含真 skill 名 + 验收 Cs2
# ==========================================================================

class TestEndToEndPhrasingDirective(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_cs2_key_health_inspector_appears_in_block(self):
        """Cs2 验收续：注册 KeyHealthInspector 后，prompt 块必须含具体 skill 名"""
        self.reg.register(_make(
            'key_health_inspector.report_403_status',
            danger=DANGER_SAFE,
            description='排查 API key 403 健康状态：列出失败 key + 推荐恢复时机',
        ))
        block = self.reg.to_prompt_block(filter_safe_only=True)
        self.assertIn('key_health_inspector.report_403_status', block,
            'KeyHealthInspector skill 必须出现在 prompt 块中（让 LLM 知道能 offer 它）')
        self.assertIn('排查 API key 403', block,
            'description 必须出现，让 LLM 能用人话 reference')

    def test_dangerous_skill_excluded_in_safe_block(self):
        """安全过滤：dangerous skill 不该出现在 nudge offer 候选中"""
        self.reg.register(_make('file.delete', danger=DANGER_DANGEROUS,
                                description='删除文件'))
        block = self.reg.to_prompt_block(filter_safe_only=True)
        self.assertNotIn('file.delete', block,
            'dangerous skill 不能出现在 safe-only block（防止 LLM 主动 offer 危险动作）')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L2 Capability-Aware Phrasing tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
