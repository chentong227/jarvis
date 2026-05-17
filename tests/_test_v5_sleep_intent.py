"""v5.1 单元测试：Sleep Intent 检测 + 重复催睡抑制

起因（Sir 2026-05-14 23:50-00:14 实测日志）：
- 23:50 Sir 说"I will go to sleep. 我马上回去睡觉，再过半小时左右吧"
- 23:56 Conductor 触发 late_night → "Finalizing these AI assets now would..."
- 00:00 Conductor 又触发 late_night → "The vlog assets can wait until morning..."
- 00:00:53 Sir 又说"我过半小时就会睡的"
- 00:14 Conductor 又触发 suggest_break → "Perhaps it is time to leave the agents..."
3 次重复催睡！根因：Conductor/SmartNudge 不读 STM、不识别 Sir 的睡眠表态。

修法：
- JarvisWorkerThread._detect_sleep_intent 检测中英文表态 → 设 _sleep_intent_until 窗口
- Conductor._execute_path_b / SmartNudgeSentinel._dispatch_nudge 在窗口内静默 sleep 类 nudge

跑法：
    cd d:\\Jarvis
    python tests/_test_v5_sleep_intent.py
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestSleepIntentSourceContract(unittest.TestCase):
    """v5.1 源码契约：方法存在、字段存在、抑制路径就绪。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_detect_method_defined(self):
        self.assertIn('def _detect_sleep_intent', self.src,
                      "JarvisWorkerThread._detect_sleep_intent 必须存在")

    def test_intent_patterns_constant_defined(self):
        self.assertIn('_SLEEP_INTENT_PATTERNS', self.src)
        self.assertIn('_SLEEP_TIME_EXTRACTORS', self.src)
        self.assertIn('_SLEEP_DEFAULT_DELAY_SEC', self.src)
        self.assertIn('_SLEEP_GRACE_SEC', self.src)

    def test_field_init_in_worker_init(self):
        # JarvisWorkerThread.__init__ 必须初始化 _sleep_intent_until = 0.0
        m = re.search(
            r"class JarvisWorkerThread\(QThread\):.*?def __init__.*?self\._sleep_intent_until\s*=\s*0\.0",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "JarvisWorkerThread.__init__ 必须 self._sleep_intent_until = 0.0")

    def test_run_invokes_detect_sleep_intent(self):
        # run() 处理 user cmd 时必须调用 _detect_sleep_intent
        self.assertIn('self._detect_sleep_intent(cmd)', self.src,
                      "run() 必须在用户命令路径上调 _detect_sleep_intent")

    def test_conductor_suppression_in_path_b(self):
        # Conductor._execute_path_b 必须有 sleep_intent 抑制段
        m = re.search(
            r"def _execute_path_b.*?_SLEEP_RELATED_NUDGES.*?_sleep_intent_until.*?return",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "Conductor._execute_path_b 必须有 _sleep_intent_until 抑制 sleep 类 nudge")

    def test_smartnudge_suppression_in_dispatch(self):
        # SmartNudgeSentinel._dispatch_nudge 必须有 sleep_intent 抑制段
        m = re.search(
            r"def _dispatch_nudge.*?_SLEEP_RELATED_NUDGES.*?_sleep_intent_until.*?return",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "SmartNudgeSentinel._dispatch_nudge 必须有 _sleep_intent_until 抑制 sleep 类 nudge")

    def test_event_bus_publish_sleep_intent(self):
        # 检测到睡眠意图必须 publish 'sleep_intent_declared' 事件
        self.assertIn("'sleep_intent_declared'", self.src,
                      "必须 publish sleep_intent_declared 让主脑 prompt 看见")


class TestSleepIntentDetection(unittest.TestCase):
    """运行时：调用 _detect_sleep_intent 验证窗口正确设置。"""

    def _make_worker(self):
        """构造一个最小 worker，能调 _detect_sleep_intent。"""
        from jarvis_nerve import JarvisWorkerThread

        class _DummyJarvis:
            event_bus = None

        worker = JarvisWorkerThread.__new__(JarvisWorkerThread)
        worker.jarvis = _DummyJarvis()
        worker._sleep_intent_until = 0.0
        return worker

    def test_english_in_30_min(self):
        worker = self._make_worker()
        before = time.time()
        worker._detect_sleep_intent("I'll go to sleep in 30 minutes")
        delta = worker._sleep_intent_until - before
        # 30 min + 15 min grace = 2700s ± 10s 误差
        self.assertGreater(delta, 2680)
        self.assertLess(delta, 2720)

    def test_chinese_half_hour(self):
        worker = self._make_worker()
        before = time.time()
        worker._detect_sleep_intent("我马上回去睡觉，再过半小时左右吧")
        delta = worker._sleep_intent_until - before
        # 半小时 = 1800s + 900s grace = 2700s
        self.assertGreater(delta, 2680)
        self.assertLess(delta, 2720)

    def test_chinese_explicit_minutes(self):
        worker = self._make_worker()
        before = time.time()
        worker._detect_sleep_intent("我过半小时就会睡的")
        delta = worker._sleep_intent_until - before
        self.assertGreater(delta, 2680)
        self.assertLess(delta, 2720)

    def test_chinese_45_minutes(self):
        worker = self._make_worker()
        before = time.time()
        worker._detect_sleep_intent("我45分钟后就睡觉")
        delta = worker._sleep_intent_until - before
        # 45 min + 15 grace = 3600s
        self.assertGreater(delta, 3580)
        self.assertLess(delta, 3620)

    def test_chinese_马上去睡(self):
        # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 旧测试 "马上=5min" 是错的语义。
        # Sir 真意是 immediate (0s) — 旧版本兜底误判成 5min 给延迟监督，
        # 新版本走 immediate 分支 = 0s + 900s grace = 900s。
        worker = self._make_worker()
        before = time.time()
        worker._detect_sleep_intent("我马上去睡")
        delta = worker._sleep_intent_until - before
        # "马上" = immediate → 0s + 900s grace = 900s
        self.assertGreater(delta, 880)
        self.assertLess(delta, 920)

    def test_no_match_normal_speech(self):
        worker = self._make_worker()
        worker._detect_sleep_intent("帮我开一下浏览器")
        self.assertEqual(worker._sleep_intent_until, 0.0,
                         "正常指令不应触发 sleep intent")

    def test_no_match_nudge_command(self):
        worker = self._make_worker()
        worker._detect_sleep_intent("__NUDGE__:{\"type\":\"late_night\"}")
        self.assertEqual(worker._sleep_intent_until, 0.0,
                         "__NUDGE__ 命令本身不能触发 sleep intent")

    def test_default_delay_when_no_number(self):
        worker = self._make_worker()
        before = time.time()
        worker._detect_sleep_intent("I'm going to bed")
        delta = worker._sleep_intent_until - before
        # 没说时间 → 默认 30 min + 15 grace = 2700s
        self.assertGreater(delta, 2680)
        self.assertLess(delta, 2720)

    def test_repeated_intent_extends_window(self):
        """Sir 多次表态 → 取最远的窗口（max）。"""
        worker = self._make_worker()
        worker._detect_sleep_intent("我15分钟后睡")
        first = worker._sleep_intent_until
        worker._detect_sleep_intent("我45分钟后睡")
        second = worker._sleep_intent_until
        self.assertGreater(second, first,
                           "更远的表态应延长窗口，不应缩短")

    def test_repeated_short_does_not_shorten(self):
        """Sir 先说 45 min，再说 5 min —— 窗口不能缩短。"""
        worker = self._make_worker()
        worker._detect_sleep_intent("我45分钟后睡")
        first = worker._sleep_intent_until
        worker._detect_sleep_intent("我马上去睡")
        second = worker._sleep_intent_until
        self.assertGreaterEqual(second, first,
                                "重复表态时窗口只能延长不能缩短（max 语义）")


class TestSleepIntentSuppressesNudge(unittest.TestCase):
    """运行时：sleep_intent 窗口内 late_night / suggest_break 真的被静默。"""

    def test_conductor_path_b_skips_late_night(self):
        """模拟 Conductor._execute_path_b 在 sleep_intent 窗口内静默 late_night。"""
        from jarvis_nerve import Conductor, NudgeGate

        class _Worker:
            def __init__(self):
                self.commands = []
                self._sleep_intent_until = time.time() + 1800  # 30 min 窗口
                self.jarvis = self

            def push_command(self, cmd):
                self.commands.append(cmd)

        worker = _Worker()
        cond = Conductor(worker, nudge_gate=NudgeGate(cooldown_seconds=10))

        # 注入一个会触发 late_night 的 decision
        decision = {
            'should_speak': True,
            'nudge_type': 'late_night',
            'action': 'Warn Late Night',
            'decision_reason': 'mock',
            'tone': 'gentle',
            'confidence': 0.8,
        }

        # 用 monkey patch 替换 _decision_llm 让它返回我们的 decision
        cond._decision_llm = lambda fr: decision
        filter_result = {'reason': 'late_at_night', 'snapshot': {}}

        cond._execute_path_b(filter_result)

        # sleep_intent 窗口内 → push_command 不该被调
        self.assertEqual(len(worker.commands), 0,
            "sleep_intent 窗口内 Conductor 必须静默 late_night，不应推命令")

    def test_conductor_path_b_allows_offer_help(self):
        """sleep_intent 窗口内非 sleep 类 nudge（如 offer_help）仍可发。"""
        from jarvis_nerve import Conductor, NudgeGate
        # [轴3-L1 / 2026-05-15] 适配 OfferGuard：注册 dummy safe skill 让 offer_help 通过 capability 闸
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
                description='test fixture',
                dangerous_flag='safe',
            ))
        except Exception:
            pass

        class _Worker:
            def __init__(self):
                self.commands = []
                self._sleep_intent_until = time.time() + 1800
                self.jarvis = self

            def push_command(self, cmd):
                self.commands.append(cmd)

        worker = _Worker()
        cond = Conductor(worker, nudge_gate=NudgeGate(cooldown_seconds=10))

        decision = {
            'should_speak': True,
            'nudge_type': 'offer_help',
            'action': 'Offer Help',
            'decision_reason': 'mock',
            'tone': 'gentle',
            'confidence': 0.8,
        }
        cond._decision_llm = lambda fr: decision
        filter_result = {'reason': 'error_visible', 'snapshot': {}}

        cond._execute_path_b(filter_result)
        # offer_help 不在 sleep_intent 抑制列表 → 应被推送
        self.assertEqual(len(worker.commands), 1,
            "offer_help 不属于 sleep 类 → 应正常发出")

    def test_conductor_path_b_post_window_allows_late_night(self):
        """sleep_intent 窗口过期后 late_night 应正常放行。"""
        from jarvis_nerve import Conductor, NudgeGate

        class _Worker:
            def __init__(self):
                self.commands = []
                self._sleep_intent_until = time.time() - 10  # 已过期
                self.jarvis = self

            def push_command(self, cmd):
                self.commands.append(cmd)

        worker = _Worker()
        cond = Conductor(worker, nudge_gate=NudgeGate(cooldown_seconds=10))

        decision = {
            'should_speak': True,
            'nudge_type': 'late_night',
            'action': 'Warn Late Night',
            'decision_reason': 'mock',
            'tone': 'gentle',
            'confidence': 0.8,
        }
        cond._decision_llm = lambda fr: decision
        filter_result = {'reason': 'late_at_night', 'snapshot': {}}

        cond._execute_path_b(filter_result)
        self.assertEqual(len(worker.commands), 1,
            "窗口过期后 late_night 应能正常发")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestSleepIntentSourceContract),
        loader.loadTestsFromTestCase(TestSleepIntentDetection),
        loader.loadTestsFromTestCase(TestSleepIntentSuppressesNudge),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] v5.1 Sleep Intent tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
