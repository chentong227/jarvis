"""P1 修复单元测试（继 R7-β post-test v2 之后）。

跑法：
    cd d:\\Jarvis
    python tests/_test_p1_fixes.py

覆盖：
1. Conductor 旧 API 兼容封装：`_rule_decision` / `_dispatch_to_jarvis`
   —— 修掉 TODO P1 "TestConductor 4 个 pre-existing 失败" 老重构遗留
2. ChatBypass 把 `_last_circuit_broken_reason` 暴露给外层，供 B 守门人消费
3. B 守门人（Integrity Check）在工具链熔断时也触发，不再"只看有没有 tool_results"
"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# 🩹 [β.5.18 / 2026-05-19] 老 Conductor/NudgeGate 测试预设 hard 行为, β.5.x 默认
# publish_only. 全模块 mock read_gate_mode 返 hard 让老 testcase 测内部 hard 评估
# 不破坏. β.5.x publish_only 新行为另由 β.5.13/14/15 等专测覆盖.
_gate_mode_patch = None


def setUpModule():
    global _gate_mode_patch
    _gate_mode_patch = mock.patch(
        'jarvis_utils.read_gate_mode', return_value='hard')
    _gate_mode_patch.start()


def tearDownModule():
    global _gate_mode_patch
    if _gate_mode_patch is not None:
        _gate_mode_patch.stop()
        _gate_mode_patch = None


class _LocalMockWorker:
    """轻量 MockWorker：只暴露 push_command 接口，不引入 PyQt 重依赖。"""

    def __init__(self):
        self.commands = []
        self.jarvis = self

    def push_command(self, cmd):
        self.commands.append(cmd)


class TestConductorLegacyAPI(unittest.TestCase):
    """[P1-A] 旧测试套件期望的 _rule_decision / _dispatch_to_jarvis 必须存在并工作。"""

    def setUp(self):
        from jarvis_nerve import Conductor, NudgeGate
        self.worker = _LocalMockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)
        self.conductor = Conductor(self.worker, nudge_gate=self.gate)
        # [轴3-L1 / 2026-05-15] 适配 OfferGuard：注册 dummy safe skill
        try:
            from jarvis_skill_registry import (
                SkillRegistry, OfferGuard, SkillManifest,
            )
            SkillRegistry.reset_instance_for_test()
            OfferGuard.reset_for_test()
            SkillRegistry.get_instance().register(SkillManifest(
                command='_test_fixture.dummy_safe',
                module='_test_fixture',
                callable_name='dummy',
                description='test fixture for OfferGuard capability check',
                dangerous_flag='safe',
            ))
        except Exception:
            pass

    def tearDown(self):
        try:
            from jarvis_skill_registry import SkillRegistry, OfferGuard
            OfferGuard.reset_for_test()
            SkillRegistry.reset_instance_for_test()
        except Exception:
            pass

    def test_rule_decision_returns_offer_help_on_error(self):
        snapshot = {
            'afk_minutes': 0, 'current_hour': 14, 'active_window': 'code',
            'error_visible': True, 'wellness_alert': {}, 'shield_alert': {},
            'companion_alert': {}, 'audio_playing': False, 'video_editor': False,
        }
        decision = self.conductor._rule_decision(snapshot, 0.5)
        self.assertEqual(decision['action'], 'Offer Help')

    def test_rule_decision_returns_none_on_quiet(self):
        snapshot = {
            'afk_minutes': 0, 'current_hour': 14, 'active_window': 'browser',
            'error_visible': False, 'wellness_alert': {}, 'shield_alert': {},
            'companion_alert': {}, 'audio_playing': False, 'video_editor': False,
        }
        decision = self.conductor._rule_decision(snapshot, 0.2)
        self.assertEqual(decision['action'], 'None')

    def test_rule_decision_late_night_warns(self):
        snapshot = {
            'afk_minutes': 0, 'current_hour': 1, 'active_window': 'code',
            'error_visible': False, 'wellness_alert': {}, 'shield_alert': {},
            'companion_alert': {}, 'audio_playing': False, 'video_editor': False,
        }
        decision = self.conductor._rule_decision(snapshot, 0.3)
        self.assertEqual(decision['action'], 'Warn Late Night')

    def test_dispatch_to_jarvis_pushes_nudge_when_gate_open(self):
        decision = {'action': 'Suggest Break', 'reason': 'test',
                    'confidence': 0.8, 'message_tone': 'gentle'}
        snapshot = {'afk_minutes': 0, 'current_hour': 14}
        ok = self.conductor._dispatch_to_jarvis(decision, snapshot)
        self.assertTrue(ok)
        self.assertEqual(len(self.worker.commands), 1)
        self.assertIn('__NUDGE__', self.worker.commands[0])

    def test_dispatch_to_jarvis_blocked_by_gate(self):
        self.gate.mark_spoke('companion')  # 别中心刚发声，guardian 冷却中
        decision = {'action': 'Motivate', 'reason': 'test',
                    'confidence': 0.7, 'message_tone': 'gentle'}
        ok = self.conductor._dispatch_to_jarvis(decision, {})
        self.assertFalse(ok)
        self.assertEqual(len(self.worker.commands), 0)

    def test_dispatch_to_jarvis_urgent_bypasses_gate(self):
        self.gate.mark_spoke('companion')
        decision = {'action': 'Offer Help', 'reason': 'test',
                    'confidence': 0.9, 'message_tone': 'gentle'}
        ok = self.conductor._dispatch_to_jarvis(decision, {})
        self.assertTrue(ok)
        self.assertEqual(len(self.worker.commands), 1)

    def test_dispatch_to_jarvis_returns_false_on_none_action(self):
        decision = {'action': 'None', 'reason': '', 'confidence': 0.0}
        ok = self.conductor._dispatch_to_jarvis(decision, {})
        self.assertFalse(ok)


class TestCircuitBrokenReasonExposed(unittest.TestCase):
    """[P1-B] ChatBypass._last_circuit_broken_reason 必须存在为默认 None，
    且 stream_chat 收尾会把局部 _circuit_broken_reason 写到这。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19-3 / 2026-05-16] FunnelLogger 等已拆到 jarvis_sensors.py
        # 用 corpus helper 跨多文件扫描，避免源码扫描断裂
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_attribute_declared_in_init(self):
        self.assertRegex(
            self.src,
            r'self\._last_circuit_broken_reason\s*=\s*None',
            "ChatBypass.__init__ 必须声明 self._last_circuit_broken_reason = None"
        )

    def test_stream_chat_assigns_attribute(self):
        # 收尾处把局部 _circuit_broken_reason 写到 self._last_circuit_broken_reason
        m = re.search(
            r"self\._last_circuit_broken_reason\s*=\s*_circuit_broken_reason",
            self.src,
        )
        self.assertIsNotNone(m,
                             "stream_chat 收尾必须把 _circuit_broken_reason 暴露到 self._last_circuit_broken_reason")


class TestFunnelDismissiveContextSuppressesContradictionFlip(unittest.TestCase):
    """[P1-D] 漏斗第二层"矛盾修正"过于激进：LLM 明确说"没有显示出系统性异常"
    也会被反转。修复后：检测到 dismissive context（"正常/没有/no issue/expected"等）就不再翻转。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19-3 / 2026-05-16] FunnelLogger 等已拆到 jarvis_sensors.py
        # 用 corpus helper 跨多文件扫描，避免源码扫描断裂
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_dismissive_markers_list_present(self):
        # 源码必须引入 _dismissive_markers 列表
        self.assertIn('_dismissive_markers', self.src,
                      "Funnel 第二层必须有 _dismissive_markers 列表压制误翻转")
        # 必须至少包含核心标记
        self.assertIn("'正常'", self.src)
        self.assertIn("'没有问题'", self.src)
        # 英文也必须覆盖
        self.assertIn("'no issue'", self.src)

    def test_contradiction_flip_guarded_by_dismissive_check(self):
        # 翻转判断必须先看是否 _has_dismissive
        m = re.search(
            r"_has_dismissive\s*=\s*any\(.*_dismissive_markers.*?\).*?"
            r"if\s*\(not\s+_has_dismissive\)\s*and\s*any\(",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "矛盾修正必须先检查 _has_dismissive，否则会把 LLM 的'没有显示出异常'误翻转"
        )


class TestIntegrityCheckConsumesCircuitBroken(unittest.TestCase):
    """[P1-C] B 守门人（Integrity Check）必须在熔断场景也触发，不能只看 _has_tool_results。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19-3 / 2026-05-16] FunnelLogger 等已拆到 jarvis_sensors.py
        # 用 corpus helper 跨多文件扫描，避免源码扫描断裂
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_b_gatekeeper_reads_circuit_broken_reason(self):
        # B 守门人代码段必须读取 _last_circuit_broken_reason
        self.assertIn(
            '_last_circuit_broken_reason',
            self.src,
            "B 守门人必须读取 _last_circuit_broken_reason"
        )
        # 出现 ≥ 2 次：一次声明、一次消费
        self.assertGreaterEqual(
            self.src.count('_last_circuit_broken_reason'), 2,
            "_last_circuit_broken_reason 至少出现 2 次（声明 + 消费）"
        )

    def test_b_gatekeeper_branches_on_circuit_broken(self):
        # 检查 `_should_check_integrity` 守门判断
        m = re.search(
            r"_should_check_integrity\s*=.*?\(.*?not\s+_has_tool_results.*?or\s+_cb_reason\s*\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "B 守门人必须同时支持两档：(not _has_tool_results) or _cb_reason"
        )

    def test_integrity_note_carries_circuit_reason(self):
        # 熔断分支的 _integrity_note 必须包含 circuit-broken / 熔断 字样
        self.assertIn(
            'circuit-broken',
            self.src,
            "B 守门人熔断分支的 INTEGRITY NOTE 必须告诉下一轮主脑'工具链已熔断'"
        )


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestConductorLegacyAPI),
        loader.loadTestsFromTestCase(TestCircuitBrokenReasonExposed),
        loader.loadTestsFromTestCase(TestIntegrityCheckConsumesCircuitBroken),
        loader.loadTestsFromTestCase(TestFunnelDismissiveContextSuppressesContradictionFlip),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All P1 fix tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
