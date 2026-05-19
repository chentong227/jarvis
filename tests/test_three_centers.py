# -*- coding: utf-8 -*-
import sys
import os
import json
import time
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 🩹 [β.5.18 / 2026-05-19] 老 NudgeGate/Conductor 测试预设 hard cooldown 行为, β.5.x
# 默认 publish_only (cooldown 不拦, 主脑自决). 全模块 mock read_gate_mode 返 hard
# 让老 testcase 测内部 hard 评估不破坏. β.5.18 已专测 freeze/sleep 即使 publish_only
# 也 hard 拦 (Sir 显式状态守). β.5.x publish_only 新行为另由 β.5.13/14/15/16 专测覆盖.
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

from PyQt5.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)

from jarvis_nerve import (
    NudgeGate, Conductor, PromptCenter, GuardianCenter, CompanionCenter,
    ReturnSentinel, CommitmentWatcher, SmartNudgeSentinel,
    PhysicalEnvironmentProbe, HabitClock
)
from jarvis_utils import QuickClassifier, get_quick_classifier, LocalLLMFallback, get_local_fallback


class MockWorker:
    def __init__(self):
        self.commands = []
        self.jarvis = self

    def push_command(self, cmd):
        self.commands.append(cmd)


class TestNudgeGate(unittest.TestCase):
    def setUp(self):
        self.gate = NudgeGate(cooldown_seconds=2)

    def test_basic_gate(self):
        self.assertTrue(self.gate.can_speak('guardian'))
        self.gate.mark_spoke('guardian')
        self.assertTrue(self.gate.can_speak('guardian'))
        self.assertFalse(self.gate.can_speak('companion'))

    def test_cooldown_expires(self):
        self.gate.mark_spoke('guardian')
        time.sleep(2.1)
        self.assertTrue(self.gate.can_speak('companion'))

    def test_urgent_override(self):
        self.gate.mark_spoke('companion')
        self.assertTrue(self.gate.can_speak('guardian', is_urgent=True))

    def test_sleep_mode_blocks_most(self):
        self.gate.activate_sleep_mode()
        self.assertFalse(self.gate.can_speak('guardian', nudge_type='offer_help'))
        self.assertFalse(self.gate.can_speak('companion', nudge_type='hydration'))
        self.assertFalse(self.gate.can_speak('guardian', is_urgent=True, nudge_type='commitment_check'))

    def test_sleep_mode_allows_return_greeting(self):
        self.gate.activate_sleep_mode()
        self.assertTrue(self.gate.can_speak('guardian', nudge_type='return_greeting'))

    def test_sleep_mode_deactivate(self):
        self.gate.activate_sleep_mode()
        self.gate.deactivate_sleep_mode()
        self.assertTrue(self.gate.can_speak('guardian', nudge_type='hydration'))

    def test_freeze_for_blocks_other_centers(self):
        # 用户手动急停 → freeze_for(180) 后 3 分钟内任何中心都不能抢话
        # （注意：同名 center 调 can_speak 时本来就会放行，所以测的是跨中心抢话）
        self.gate.freeze_for(180.0, source='manual_standby')
        # 不同中心：必须被冻结挡住
        self.assertFalse(self.gate.can_speak('guardian'))
        self.assertFalse(self.gate.can_speak('companion'))

    def test_freeze_for_zero_seconds_is_safe(self):
        # 边界：freeze_for(0) 不应该让 can_speak 永远 True 或抛错
        self.gate.freeze_for(0.0)
        # 当前 _last_nudge_time 大致等于 time.time() - _cooldown，所以另一中心应当能立刻发言
        self.assertTrue(self.gate.can_speak('guardian'))


class TestConductor(unittest.TestCase):
    def setUp(self):
        self.worker = MockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)
        self.conductor = Conductor(self.worker, nudge_gate=self.gate)
        # [轴3-L1 / 2026-05-15] 适配 OfferGuard：测试场景注册一个 dummy safe skill
        # 让 offer_help 能过 capability 闸；同时 reset OfferGuard 节奏 last_ts
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

    def test_nudge_type_map(self):
        # [P0-8 同步 / 2026-05-15] Check-in 不再被错映射到 return_greeting
        # （那是 ReturnSentinel 专属类型，让 Check-in 假冒会让 8 处豁免条件被绕过）
        self.assertEqual(self.conductor._nudge_type_map['Check-in'], 'check_in')
        self.assertEqual(self.conductor._nudge_type_map['Offer Help'], 'offer_help')
        self.assertEqual(self.conductor._nudge_type_map['Suggest Break'], 'suggest_break')
        self.assertEqual(self.conductor._nudge_type_map['Context Switch Alert'], 'context_switch_alert')
        self.assertEqual(self.conductor._nudge_type_map['Motivate'], 'flow_end')
        self.assertEqual(self.conductor._nudge_type_map['Warn Late Night'], 'late_night')
        self.assertEqual(self.conductor._nudge_type_map['Knowledge Archive'], 'atmosphere')

    def test_rule_based_decision(self):
        snapshot = {
            'afk_minutes': 0,
            'current_hour': 14,
            'active_window': 'code',
            'error_visible': True,
            'wellness_alert': {},
            'shield_alert': {},
            'companion_alert': {},
            'audio_playing': False,
            'video_editor': False,
        }
        decision = self.conductor._rule_decision(snapshot, 0.5)
        self.assertIn(decision['action'], ['Offer Help', 'None'])

    def test_dispatch_with_gate(self):
        decision = {'action': 'Suggest Break', 'reason': 'test', 'confidence': 0.8, 'message_tone': 'gentle'}
        snapshot = {'afk_minutes': 0, 'current_hour': 14}
        self.conductor._dispatch_to_jarvis(decision, snapshot)
        self.assertEqual(len(self.worker.commands), 1)
        self.assertIn('__NUDGE__', self.worker.commands[0])

    def test_dispatch_blocked_by_gate(self):
        self.gate.mark_spoke('companion')
        decision = {'action': 'Motivate', 'reason': 'test', 'confidence': 0.8, 'message_tone': 'gentle'}
        snapshot = {'afk_minutes': 0, 'current_hour': 14}
        self.conductor._dispatch_to_jarvis(decision, snapshot)
        self.assertEqual(len(self.worker.commands), 0)

    def test_dispatch_urgent_bypasses_gate(self):
        self.gate.mark_spoke('companion')
        decision = {'action': 'Offer Help', 'reason': 'test', 'confidence': 0.9, 'message_tone': 'gentle'}
        snapshot = {'afk_minutes': 0, 'current_hour': 14}
        self.conductor._dispatch_to_jarvis(decision, snapshot)
        self.assertEqual(len(self.worker.commands), 1)


class TestPromptCenter(unittest.TestCase):
    def test_creation(self):
        center = PromptCenter(key_router=None, central_nerve=None)
        # [C1-4 同步 / 2026-05-15] PromptCenter.habit_clock 死代码已删
        # （全工程零外部读取，业务统一走 CentralNerve.habit_clock）
        self.assertFalse(hasattr(center, 'habit_clock'),
                         "PromptCenter 不应再有孤立的 habit_clock 实例（C1-4）")
        self.assertIsNone(center.soul_archivist)
        self.assertIsNone(center.anticipator)
        self.assertIsNone(center.reflection_scheduler)


class TestGuardianCenter(unittest.TestCase):
    def setUp(self):
        self.worker = MockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_creation(self):
        center = GuardianCenter(self.worker, nudge_gate=self.gate)
        self.assertIsNone(center.conductor)
        self.assertIsNone(center.return_sentinel)
        self.assertIsNone(center.commitment_watcher)
        self.assertIsNone(center.wellness_guardian)


class TestCompanionCenter(unittest.TestCase):
    def setUp(self):
        self.worker = MockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_creation(self):
        center = CompanionCenter(self.worker, nudge_gate=self.gate)
        self.assertIsNone(center.smart_nudge)


class TestReturnSentinelGate(unittest.TestCase):
    def setUp(self):
        self.worker = MockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_gate_accepts(self):
        rs = ReturnSentinel(self.worker, nudge_gate=self.gate)
        self.assertEqual(rs.gate, self.gate)

    def test_no_gate_still_works(self):
        rs = ReturnSentinel(self.worker)
        self.assertIsNone(rs.gate)


class TestCommitmentWatcherGate(unittest.TestCase):
    def setUp(self):
        self.worker = MockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_gate_accepts(self):
        cw = CommitmentWatcher(self.worker, nudge_gate=self.gate)
        self.assertEqual(cw.gate, self.gate)

    def test_no_gate_still_works(self):
        cw = CommitmentWatcher(self.worker)
        self.assertIsNone(cw.gate)


class TestSmartNudgeSentinelGate(unittest.TestCase):
    def setUp(self):
        self.worker = MockWorker()
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_gate_accepts(self):
        sn = SmartNudgeSentinel(self.worker, nudge_gate=self.gate)
        self.assertEqual(sn.gate, self.gate)

    def test_no_gate_still_works(self):
        sn = SmartNudgeSentinel(self.worker)
        self.assertIsNone(sn.gate)


class TestSleepDetection(unittest.TestCase):
    def test_sleep_patterns(self):
        sleep_inputs = [
            '我去睡觉了',
            '睡了',
            '晚安',
            'good night',
            '困了',
            '我去睡了',
            '睡觉',
            '休息了',
            '去休息',
            '上床',
            '躺下',
            '关灯',
            '明天见',
            'night night',
            'im going to sleep',
            'i am tired',
            'I need to go to sleep right now',
            'i need to sleep',
            'I want to go to bed',
            'i have to sleep now',
            'I should go to rest',
            'i gotta sleep',
            'I must go to bed',
            'i will go to sleep',
            'I am gonna go to sleep',
            '我要去睡了',
            '我需要睡觉',
            '我想睡了',
            '我准备休息',
            '我该睡了',
            '我得去睡',
        ]
        for text in sleep_inputs:
            with self.subTest(text=text):
                import re
                patterns = [
                    r'(我去?睡(觉|了|啦|咯|吧|呀|哦|哈|喽))',
                    r'(睡了|睡觉|晚安|good\s*night|night\s*night)',
                    r'(困了|累了|休息了|去休息|要休息)',
                    r'(上床|躺下|关灯|熄灯)',
                    r'(明天见|明早|morning)',
                    r'(i\'?m?\s*(going\s+to\s+)?(sleep|bed))',
                    r'(i(\s+am|\'?m?)\s+tired)',
                    r'(i(\s+am)?\s+(need|want|have|got|gotta|should|must|will|gonna)(\s+to)?\s+(go\s+to\s+)?(sleep|bed|rest))',
                    r'(我(需要|要|想|准备|打算|该|得|必须)(去)?(睡|休息|躺))',
                ]
                matched = False
                for pattern in patterns:
                    if re.search(pattern, text.lower().strip()):
                        matched = True
                        break
                self.assertTrue(matched, f"'{text}' should match sleep pattern")


class TestNudgeDirectives(unittest.TestCase):
    def test_new_directives_exist(self):
        from jarvis_nerve import CentralNerve
        cn = CentralNerve.__new__(CentralNerve)
        if hasattr(cn, 'stream_nudge'):
            import inspect
            source = inspect.getsource(cn.stream_nudge)
            self.assertIn('offer_help', source)
            self.assertIn('suggest_break', source)
            self.assertIn('context_switch_alert', source)


class TestPhysicalEnvironmentProbe(unittest.TestCase):
    def test_sensor_weights(self):
        probe = PhysicalEnvironmentProbe()
        self.assertIsNotNone(probe._sensor_weights)
        self.assertIn('error_visible', probe._sensor_weights)

    def test_update_weight(self):
        PhysicalEnvironmentProbe.update_sensor_weight('error_visible', 1.0, 0.5)
        weight = PhysicalEnvironmentProbe._sensor_weights.get('error_visible', 0.5)
        self.assertGreater(weight, 0.5)


class TestHabitClock(unittest.TestCase):
    def test_creation(self):
        hc = HabitClock()
        self.assertIsNotNone(hc)


class TestQuickClassifier(unittest.TestCase):
    def test_singleton(self):
        c1 = get_quick_classifier()
        c2 = get_quick_classifier()
        self.assertIs(c1, c2)

    def test_timeout_map(self):
        c = get_quick_classifier()
        self.assertEqual(c.TIMEOUT_MAP["simple"], 3.0)
        self.assertEqual(c.TIMEOUT_MAP["code"], 8.0)
        self.assertEqual(c.TIMEOUT_MAP["reasoning"], 12.0)
        self.assertEqual(c.TIMEOUT_MAP["search"], 30.0)

    def test_calc_timeout_basic(self):
        c = get_quick_classifier()
        t = c.calc_timeout("simple", "hello", "")
        self.assertEqual(t, 3.0)

    def test_calc_timeout_with_turns(self):
        c = get_quick_classifier()
        deep_context = "[User]\n" * 10
        t = c.calc_timeout("reasoning", "explain this", deep_context)
        self.assertGreater(t, 12.0)

    def test_calc_timeout_with_length(self):
        c = get_quick_classifier()
        long_msg = "x" * 400
        t = c.calc_timeout("code", long_msg, "")
        self.assertGreater(t, 8.0)

    def test_calc_timeout_capped(self):
        c = get_quick_classifier()
        t = c.calc_timeout("search", "x" * 2000, "[User]\n" * 20)
        self.assertLessEqual(t, 30.0)

    def test_classify_fallback_on_error(self):
        c = get_quick_classifier()
        cat, timeout = c.classify("hello world", "")
        self.assertIn(cat, ["simple", "code", "reasoning", "search"])
        self.assertGreater(timeout, 0)

    def test_detect_sleep_intent(self):
        c = get_quick_classifier()
        result = c.detect_sleep_intent("hello")
        self.assertIn(result, ["sleep", "wake", "other"])

    def test_detect_emotion(self):
        c = get_quick_classifier()
        result = c.detect_emotion("I am so frustrated with this bug")
        self.assertIn(result, ["frustrated", "stressed", "tired", "playful", "excited", "curious", "impatient", "neutral"])

    def test_detect_emotion_empty(self):
        c = get_quick_classifier()
        result = c.detect_emotion("")
        self.assertEqual(result, "neutral")

    def test_extract_commitment(self):
        c = get_quick_classifier()
        result = c.extract_commitment("hello how are you")
        self.assertIsInstance(result, dict)
        self.assertIn("has_commitment", result)

    def test_commitment_watcher_add(self):
        from jarvis_nerve import CommitmentWatcher
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.commitments = []
        cw._lock = threading.Lock()
        cw._to_24h = lambda h, m, ap: time.time() + 3600
        cw.add_commitment("I will go to sleep at 11", "tonight")
        self.assertEqual(len(cw.commitments), 1)
        self.assertEqual(cw.commitments[0]["description"], "I will go to sleep at 11")

    def test_commitment_watcher_rejects_jarvis_instructions(self):
        """Bug A 回归测试：用户对 Jarvis 下指令不应被识别为用户承诺"""
        from jarvis_nerve import CommitmentWatcher
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.commitments = []
        cw._lock = threading.Lock()
        cw._to_24h = lambda h, m, ap: time.time() + 3600
        rejected_samples = [
            "帮我把媒体音量调到 30%",
            "把屏幕亮度调整到50%",
            "Jarvis, 你扮演一下你已经做完的样子",
            "turn off the notifications",
            "调高音量",
            "请你打开浏览器",
            "pretend you finished",
        ]
        for sample in rejected_samples:
            with self.subTest(sample=sample):
                before = len(cw.commitments)
                cw.add_commitment(sample, "")
                self.assertEqual(len(cw.commitments), before,
                                 f"应被拒绝，但被注册为承诺: '{sample}'")

    def test_commitment_watcher_accepts_genuine_self_commitment(self):
        from jarvis_nerve import CommitmentWatcher
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.commitments = []
        cw._lock = threading.Lock()
        cw._to_24h = lambda h, m, ap: time.time() + 3600
        # 🩹 [β.2.9.9] 时间确定性闸门: add_commitment 第 2 参数必须传可解析 deadline
        # 或 predicate. 旧 test 传 "" 现在会被闸门拒 (转 PromiseLog soft). 改传时间锚.
        accepted_samples = [
            ("I will sleep at 11", "23:00"),
            ("我11点睡觉", "23:00"),
            ("I'll go to bed by midnight", "midnight"),
        ]
        for sample, deadline in accepted_samples:
            with self.subTest(sample=sample):
                cw.commitments = []
                cw.add_commitment(sample, deadline)
                self.assertEqual(len(cw.commitments), 1,
                                 f"应被注册为承诺，但被拒绝: '{sample}'")


class TestDualTrackArchitecture(unittest.TestCase):
    def test_local_fallback_singleton(self):
        fb1 = get_local_fallback()
        fb2 = get_local_fallback()
        self.assertIs(fb1, fb2)

    def test_local_fallback_build_prompt(self):
        fb = get_local_fallback()
        messages = fb.build_fallback_prompt("hello", "previous context")
        self.assertIsInstance(messages, list)
        self.assertGreater(len(messages), 0)
        self.assertIn("content", messages[0])

    def test_quick_classifier_imports(self):
        from jarvis_utils import QuickClassifier, get_quick_classifier
        self.assertIsNotNone(QuickClassifier)
        self.assertIsNotNone(get_quick_classifier)


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestNudgeGate))
    suite.addTests(loader.loadTestsFromTestCase(TestConductor))
    suite.addTests(loader.loadTestsFromTestCase(TestPromptCenter))
    suite.addTests(loader.loadTestsFromTestCase(TestGuardianCenter))
    suite.addTests(loader.loadTestsFromTestCase(TestCompanionCenter))
    suite.addTests(loader.loadTestsFromTestCase(TestReturnSentinelGate))
    suite.addTests(loader.loadTestsFromTestCase(TestCommitmentWatcherGate))
    suite.addTests(loader.loadTestsFromTestCase(TestSmartNudgeSentinelGate))
    suite.addTests(loader.loadTestsFromTestCase(TestSleepDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestNudgeDirectives))
    suite.addTests(loader.loadTestsFromTestCase(TestPhysicalEnvironmentProbe))
    suite.addTests(loader.loadTestsFromTestCase(TestHabitClock))
    suite.addTests(loader.loadTestsFromTestCase(TestQuickClassifier))
    suite.addTests(loader.loadTestsFromTestCase(TestDualTrackArchitecture))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print("TEST REPORT")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split(chr(10))[-2]}")

    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split(chr(10))[-2]}")

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)