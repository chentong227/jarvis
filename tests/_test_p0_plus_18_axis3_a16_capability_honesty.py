# -*- coding: utf-8 -*-
"""[P0+18-a.16 / 2026-05-15] 承诺必行 a.16 — 能力诚信约束（capability honesty） — 测试套件

背景
----
2026-05-15 15:50 实测：Sir 在 chat 中提到 Cursor 软件出现"对话框全白"的渲染层 bug。
Jarvis 通过 Conductor offer_help 提议：
  "I can run process_hands.get_process_info for Cursor to check for any
   unusual resource spikes or logged errors that might explain the visual hang."

`process_hands.get_process_info` 只返 OS 层（PID/CPU/MEM/exe），**不能读应用日志**。
Jarvis 用 `or` 把"能做的事 (resource spikes)"和"不能做的事 (logged errors)"缝在一起，
违反 Sir 的"承诺必行"设计理念 — 这是典型的 capability laundering through framing。

本套覆盖
-------
1. SkillManifest 新字段 `provides` / `cannot_provide` 默认值 + 序列化兼容
2. SkillScanner 读模块 MANIFEST 的 `command_provides` / `command_cannot_provide`
3. SkillScanner 支持 `_shared_` 同模块共享黑名单合并
4. process_hands.get_process_info 的 cannot_provide 实际包含 logged_errors 等关键词
5. CapabilityClaimValidator 抓 Jarvis 实际原话
6. CapabilityClaimValidator 不误报正常话术（精确率）
7. CapabilityClaimValidator 中文话术也能抓
8. format_violation_note 给出可读的 STM 提示
9. prompt 装配（nerve.py）注入了 TOOL_HONESTY_DIRECTIVE
10. SHORT_CHAT tier 注入了 TOOL_HONESTY_DIRECTIVE_MINI
11. Integrity Check 处接通了 _capability_note 到 3 处 STM append

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_18_axis3_a16_capability_honesty.py
"""

import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')
PROCESS_HANDS_PATH = os.path.join(ROOT, 'l4_hands_pool', 'l4_process_hands.py')


def _read(path):
    # [P0+19 / 2026-05-16] 拆分后 nerve.py 内容分散到多文件
    if 'jarvis_nerve.py' in str(path):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        return read_nerve_corpus()
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================================
# 1. SkillManifest 新字段
# ============================================================================
class TestA16_SkillManifestNewFields(unittest.TestCase):
    """provides / cannot_provide 字段必须存在且默认空 list。"""

    def test_fields_exist_with_defaults(self):
        from jarvis_skill_registry import SkillManifest
        sk = SkillManifest(
            command='foo.bar',
            module='foo',
            callable_name='bar',
            description='test',
        )
        self.assertTrue(hasattr(sk, 'provides'),
                        "SkillManifest 必须有 provides 字段")
        self.assertTrue(hasattr(sk, 'cannot_provide'),
                        "SkillManifest 必须有 cannot_provide 字段")
        self.assertEqual(sk.provides, [], "provides 默认空 list")
        self.assertEqual(sk.cannot_provide, [], "cannot_provide 默认空 list")

    def test_fields_serialize_roundtrip(self):
        """to_dict + from_dict 必须保留新字段。"""
        from jarvis_skill_registry import SkillManifest
        sk = SkillManifest(
            command='foo.bar',
            module='foo',
            callable_name='bar',
            description='test',
            provides=['pid', 'cpu'],
            cannot_provide=['logged_errors'],
        )
        d = sk.to_dict()
        self.assertIn('provides', d)
        self.assertIn('cannot_provide', d)
        sk2 = SkillManifest.from_dict(d)
        self.assertEqual(sk2.provides, ['pid', 'cpu'])
        self.assertEqual(sk2.cannot_provide, ['logged_errors'])

    def test_legacy_jsonl_without_new_fields_still_loads(self):
        """老 jsonl 缺新字段 → from_dict 必须 fallback 到空 list（向后兼容）。"""
        from jarvis_skill_registry import SkillManifest
        legacy = {
            'command': 'foo.bar',
            'module': 'foo',
            'callable_name': 'bar',
            'description': 'legacy entry',
        }
        sk = SkillManifest.from_dict(legacy)
        self.assertEqual(sk.provides, [])
        self.assertEqual(sk.cannot_provide, [])


# ============================================================================
# 2. SkillScanner 读 MANIFEST.command_provides / command_cannot_provide
# ============================================================================
class TestA16_SkillScannerReadsCapabilityFields(unittest.TestCase):
    """SkillScanner.scan_module_file 必须把 MANIFEST 里的字段灌进 SkillManifest。"""

    def test_scan_process_hands_picks_up_cannot_provide(self):
        from jarvis_skill_registry import SkillScanner
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        self.assertTrue(skills, "process_hands 必须扫出 skill")
        # 找 get_process_info
        gpi = next((s for s in skills if s.command.endswith('.get_process_info')), None)
        self.assertIsNotNone(gpi, "必须扫到 process_hands.get_process_info")
        self.assertIn('logged_errors', gpi.cannot_provide,
                      "get_process_info.cannot_provide 必须含 logged_errors")
        self.assertIn('js_exceptions', gpi.cannot_provide,
                      "get_process_info.cannot_provide 必须含 js_exceptions")

    def test_scan_picks_up_provides(self):
        from jarvis_skill_registry import SkillScanner
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        gpi = next((s for s in skills if s.command.endswith('.get_process_info')), None)
        self.assertIsNotNone(gpi)
        self.assertIn('pid', gpi.provides, "get_process_info.provides 必须含 pid")
        self.assertIn('cpu', gpi.provides, "get_process_info.provides 必须含 cpu")
        self.assertIn('memory', gpi.provides, "get_process_info.provides 必须含 memory")


# ============================================================================
# 3. _shared_ 合并机制
# ============================================================================
class TestA16_SharedCannotProvideMerging(unittest.TestCase):
    """MANIFEST 的 _shared_ 黑名单必须合并到每个 command 的 cannot_provide。"""

    def test_shared_keywords_propagate_to_all_commands(self):
        from jarvis_skill_registry import SkillScanner
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        # process_hands 的 _shared_ 含 'csp_violations'，每个 command 都该有
        for sk in skills:
            self.assertIn('csp_violations', sk.cannot_provide,
                          f"{sk.command}.cannot_provide 必须继承 _shared_ 黑名单 (csp_violations)")

    def test_per_command_specific_keywords_also_present(self):
        """get_process_info 特定的 'visual_hang' 也要在最终 cannot_provide 里"""
        from jarvis_skill_registry import SkillScanner
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        gpi = next((s for s in skills if s.command.endswith('.get_process_info')), None)
        self.assertIsNotNone(gpi)
        self.assertIn('visual_hang', gpi.cannot_provide,
                      "get_process_info 特定黑名单 (visual_hang) 必须存在")

    def test_shared_key_not_registered_as_command(self):
        """`_shared_` 本身不能被当成 command 注册到 SkillRegistry。"""
        from jarvis_skill_registry import SkillScanner
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        for sk in skills:
            self.assertNotIn('_shared_', sk.command,
                             f"_shared_ 不能出现在 command 名里，但看到了 {sk.command}")


# ============================================================================
# 4. CapabilityClaimValidator 抓 Jarvis 实际原话
# ============================================================================
class TestA16_ValidatorCatchesRealBug(unittest.TestCase):
    """Validator 必须抓出 2026-05-15 15:50 实测 bug 的原话。"""

    @classmethod
    def setUpClass(cls):
        # 用 fresh registry 注册 process_hands skill，避免依赖 jsonl 加载状态
        from jarvis_skill_registry import SkillRegistry, SkillScanner
        SkillRegistry.reset_instance_for_test()
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        reg = SkillRegistry.get_instance()
        for sk in skills:
            reg.register(sk, overwrite=True)
        cls.registry = reg

    @classmethod
    def tearDownClass(cls):
        from jarvis_skill_registry import SkillRegistry
        SkillRegistry.reset_instance_for_test()

    def test_detect_actual_15_50_violation(self):
        """Jarvis 这次实际说的原话必须被抓出来。"""
        from jarvis_skill_registry import CapabilityClaimValidator
        # 实测原话（略简）
        text = (
            "I can run `process_hands.get_process_info` for Cursor "
            "to check for any unusual resource spikes or logged errors "
            "that might explain the visual hang."
        )
        violations = CapabilityClaimValidator.detect_violations(text)
        self.assertTrue(violations,
                        "必须抓出至少 1 个 violation")
        v = violations[0]
        self.assertEqual(v['skill'], 'process_hands.get_process_info',
                         "skill 名必须正确抽出")
        self.assertIn('logged_errors', v['forbidden_keywords'],
                      "logged_errors 必须命中 cannot_provide")

    def test_detect_alternate_phrasing(self):
        """换种说法（'investigate' 而非 'check'）也要抓到。"""
        from jarvis_skill_registry import CapabilityClaimValidator
        text = (
            "I could use process_hands.get_process_info to investigate "
            "any JS exceptions or render errors in Cursor."
        )
        violations = CapabilityClaimValidator.detect_violations(text)
        self.assertTrue(violations)
        self.assertIn(violations[0]['skill'], ('process_hands.get_process_info',))

    def test_detect_chinese_phrasing(self):
        """中文话术也能抓。"""
        from jarvis_skill_registry import CapabilityClaimValidator
        text = (
            "我可以运行 process_hands.get_process_info 来查 Cursor "
            "的 logged errors 和 ui errors。"
        )
        violations = CapabilityClaimValidator.detect_violations(text)
        self.assertTrue(violations, "中文话术 + 英文关键词必须抓出")


# ============================================================================
# 5. Validator 不误报正常话术
# ============================================================================
class TestA16_ValidatorPrecision(unittest.TestCase):
    """Validator 在合法话术上不能报 false positive。"""

    @classmethod
    def setUpClass(cls):
        from jarvis_skill_registry import SkillRegistry, SkillScanner
        SkillRegistry.reset_instance_for_test()
        skills = SkillScanner.scan_module_file(PROCESS_HANDS_PATH)
        reg = SkillRegistry.get_instance()
        for sk in skills:
            reg.register(sk, overwrite=True)

    @classmethod
    def tearDownClass(cls):
        from jarvis_skill_registry import SkillRegistry
        SkillRegistry.reset_instance_for_test()

    def test_legitimate_usage_no_violation(self):
        """合法话术（只承诺工具真能做的事）不能误报。"""
        from jarvis_skill_registry import CapabilityClaimValidator
        text = (
            "I can run process_hands.get_process_info to check the CPU "
            "and memory usage of Cursor, Sir."
        )
        violations = CapabilityClaimValidator.detect_violations(text)
        self.assertFalse(violations,
                         "查 CPU/内存 是 get_process_info 真能做的事，不能误报")

    def test_honest_admission_no_violation(self):
        """RIGHT 范例（明确否认能查应用日志）不能误报。"""
        from jarvis_skill_registry import CapabilityClaimValidator
        text = (
            "I can confirm via process_hands.get_process_info that Cursor.exe "
            "is alive, but I cannot read its internal logged errors from there."
        )
        violations = CapabilityClaimValidator.detect_violations(text)
        # 这个句式里没有"我能用 X 来查 logged errors"的承诺，所以不应该被抓
        # （即使含"logged errors"关键字，那是在否认）
        self.assertFalse(violations,
                         "诚实承认局限不能误报")

    def test_unknown_skill_no_violation(self):
        """提到一个未注册的 skill → Validator 跳过（unknown_skill 由其他模块管）。"""
        from jarvis_skill_registry import CapabilityClaimValidator
        text = "I can run nonexistent_hand.fake_command to check the logged errors."
        violations = CapabilityClaimValidator.detect_violations(text)
        self.assertFalse(violations,
                         "未注册 skill 由 PromiseParser.unknown_skills 处理，Validator 不要重复抓")

    def test_empty_text_no_violation(self):
        from jarvis_skill_registry import CapabilityClaimValidator
        self.assertEqual(CapabilityClaimValidator.detect_violations(''), [])
        self.assertEqual(CapabilityClaimValidator.detect_violations(None), [])


# ============================================================================
# 6. format_violation_note
# ============================================================================
class TestA16_FormatViolationNote(unittest.TestCase):
    """format_violation_note 必须返回适合塞进 STM 的可读字符串。"""

    def test_empty_returns_empty(self):
        from jarvis_skill_registry import CapabilityClaimValidator
        self.assertEqual(CapabilityClaimValidator.format_violation_note([]), '')

    def test_non_empty_contains_skill_and_keyword(self):
        from jarvis_skill_registry import CapabilityClaimValidator
        violations = [{
            'skill': 'process_hands.get_process_info',
            'claim_text': 'logged errors that might explain the visual hang',
            'forbidden_keywords': ['logged_errors', 'visual_hang'],
            'matched_phrases': ['logged errors', 'visual hang'],
        }]
        note = CapabilityClaimValidator.format_violation_note(violations)
        self.assertIn('CAPABILITY OVERREACH NOTE', note)
        self.assertIn('process_hands.get_process_info', note)
        self.assertIn('承诺必行', note)


# ============================================================================
# 7. TOOL_HONESTY_DIRECTIVE & MINI 存在性
# ============================================================================
class TestA16_DirectivesExist(unittest.TestCase):
    """两个 directive 常量必须存在且包含关键词。"""

    def test_full_directive_has_key_warnings(self):
        from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE
        self.assertIn('TOOL HONESTY', TOOL_HONESTY_DIRECTIVE)
        self.assertIn('process_hands', TOOL_HONESTY_DIRECTIVE)
        self.assertIn('logged errors', TOOL_HONESTY_DIRECTIVE)
        self.assertIn('or', TOOL_HONESTY_DIRECTIVE,
                      "必须明确警告 'or' 缝合模式")
        self.assertIn('file_operator_hands.read', TOOL_HONESTY_DIRECTIVE,
                      "必须给出正确替代工具")
        # 中文核心约束也要在
        self.assertIn('承诺必行', TOOL_HONESTY_DIRECTIVE)

    def test_mini_directive_short_and_present(self):
        from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE_MINI
        # mini 版要控制在 700 字符内（SHORT_CHAT 体积敏感）
        self.assertLess(len(TOOL_HONESTY_DIRECTIVE_MINI), 700,
                        "MINI 版必须控制体积 < 700 字符")
        self.assertIn('process_hands', TOOL_HONESTY_DIRECTIVE_MINI)
        self.assertIn('file_operator_hands.read', TOOL_HONESTY_DIRECTIVE_MINI)


# ============================================================================
# 8. nerve.py 注入 TOOL_HONESTY (全档 + SHORT_CHAT 都有)
# ============================================================================
class TestA16_PromptAssemblyInjection(unittest.TestCase):
    """jarvis_nerve.py 必须注入 TOOL_HONESTY_DIRECTIVE 块。"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_marker_present(self):
        self.assertIn('P0+18-a.16', self.src,
                      "必须留下 [P0+18-a.16] marker")

    def test_full_directive_imported(self):
        """全档 prompt 必须 import + 注入 TOOL_HONESTY_DIRECTIVE。"""
        self.assertIn('from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE',
                      self.src)
        self.assertIn('{tool_honesty_directive}', self.src,
                      "result f-string 必须有 {tool_honesty_directive} 占位")

    def test_mini_directive_imported(self):
        """SHORT_CHAT 必须 import + 注入 TOOL_HONESTY_DIRECTIVE_MINI。"""
        self.assertIn('from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE_MINI',
                      self.src)
        self.assertIn('{_short_tool_honesty}', self.src,
                      "SHORT_CHAT f-string 必须有 {_short_tool_honesty} 占位")


# ============================================================================
# 9. Integrity Check 处接通 CapabilityClaimValidator
# ============================================================================
class TestA16_IntegrityCheckHook(unittest.TestCase):
    """Integrity Check 段必须调 CapabilityClaimValidator 且接到 3 处 STM append。"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_validator_imported_at_check_point(self):
        """必须 import CapabilityClaimValidator（在 Integrity Check 段附近）"""
        self.assertIn('CapabilityClaimValidator', self.src)
        # 必须用 detect_violations
        self.assertIn('detect_violations', self.src)

    def test_capability_note_var_exists(self):
        self.assertIn('_capability_note', self.src,
                      "必须有 _capability_note 变量收集 violation note")

    def test_stm_appends_use_capability_note(self):
        """STM append 的 jarvis 字段必须串上 _capability_note（3 处都接通）。"""
        # 现在应该有 3 处 "filtered_reply + _integrity_note + _capability_note"
        pattern = r'filtered_reply\s*\+\s*_integrity_note\s*\+\s*_capability_note'
        matches = re.findall(pattern, self.src)
        self.assertGreaterEqual(len(matches), 3,
                                f"3 处 STM append 必须串 _capability_note，实际找到 {len(matches)} 处")

    def test_event_bus_publishes_overreach(self):
        """命中违例时必须 publish 'capability_overreach_detected' 到 event_bus。"""
        self.assertIn("capability_overreach_detected", self.src,
                      "必须 publish capability_overreach_detected 事件")
        self.assertIn("source='capability_claim_validator'", self.src,
                      "event source 必须标 capability_claim_validator")


# ============================================================================
# 10. process_hands MANIFEST 实际数据
# ============================================================================
class TestA16_ProcessHandsManifestData(unittest.TestCase):
    """process_hands.py 的 MANIFEST 数据必须正确包含所有关键字段。"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(PROCESS_HANDS_PATH)

    def test_marker_present(self):
        self.assertIn('P0+18-a.16', self.src,
                      "process_hands.py 必须留 [P0+18-a.16] marker")

    def test_command_provides_dict_present(self):
        self.assertIn('"command_provides"', self.src)
        self.assertIn('"command_cannot_provide"', self.src)

    def test_get_process_info_explicit_keywords(self):
        """get_process_info 显式黑名单必须列出 visual_hang 等关键词"""
        # 简单字串包含检查（避免严格依赖 ast 解析）
        self.assertIn('"visual_hang"', self.src)
        self.assertIn('"logged_errors"', self.src)
        self.assertIn('"why_app_fails"', self.src)

    def test_shared_block_for_propagation(self):
        """_shared_ 块必须存在，包含跨 command 通用的关键词"""
        self.assertIn('"_shared_"', self.src)
        self.assertIn('"csp_violations"', self.src)


# ============================================================================
# Main
# ============================================================================
if __name__ == '__main__':
    unittest.main(verbosity=2)
