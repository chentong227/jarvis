"""R7-α/B1+B2 单元测试：JarvisState 中央状态机

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_alpha_state.py

覆盖：
- 三个布尔字段（awake / active_task / active_conversation）的 setter / getter
- reason 字段被记录 + history 环
- snapshot 接口
- 事件总线注入 → set_xxx 时自动 publish
- jarvis_nerve 源码不再含散落的"self.is_awake = True"裸赋值
"""
import os
import re
import sys
import time
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import JarvisState, ConversationEventBus


class TestJarvisStateBasic(unittest.TestCase):
    def setUp(self):
        self.state = JarvisState()

    def test_initial_state(self):
        self.assertFalse(self.state.awake)
        self.assertFalse(self.state.active_task)
        self.assertFalse(self.state.active_conversation)
        # 初始 reason 应当是 'init'
        self.assertEqual(self.state.last_awake_reason(), 'init')

    def test_set_awake_records_reason(self):
        changed = self.state.set_awake(True, reason='wake_word', source='unittest')
        self.assertTrue(changed)
        self.assertTrue(self.state.awake)
        self.assertEqual(self.state.last_awake_reason(), 'wake_word')

    def test_set_same_value_returns_false(self):
        # 同值写入不算翻转，不产生 history 条目
        self.state.set_awake(True, reason='wake_word')
        before = len(self.state.history(50))
        changed = self.state.set_awake(True, reason='reflex_wake')
        self.assertFalse(changed)
        after = len(self.state.history(50))
        self.assertEqual(before, after, "同值写入不应往 history 添加")

    def test_set_active_task(self):
        self.state.set_active_task(True, reason='task_started')
        self.assertTrue(self.state.active_task)
        self.state.set_active_task(False, reason='task_done')
        self.assertFalse(self.state.active_task)
        self.assertEqual(self.state.last_task_reason(), 'task_done')

    def test_set_active_conversation(self):
        self.state.set_active_conversation(True, reason='wake')
        self.assertTrue(self.state.active_conversation)
        self.state.set_active_conversation(False, reason='dismiss')
        self.assertFalse(self.state.active_conversation)
        self.assertEqual(self.state.last_conv_reason(), 'dismiss')

    def test_snapshot_returns_all_fields(self):
        self.state.set_awake(True, reason='wake_word')
        self.state.set_active_task(True, reason='task_started')
        self.state.set_active_conversation(True, reason='wake')
        snap = self.state.snapshot()
        self.assertTrue(snap['awake'])
        self.assertTrue(snap['active_task'])
        self.assertTrue(snap['active_conversation'])
        self.assertEqual(snap['last_awake_reason'], 'wake_word')
        self.assertEqual(snap['last_task_reason'], 'task_started')
        self.assertEqual(snap['last_conv_reason'], 'wake')

    def test_history_orders_by_time(self):
        self.state.set_awake(True, reason='wake_word')
        self.state.set_active_task(True, reason='task_started')
        self.state.set_active_conversation(True, reason='wake')
        hist = self.state.history(10)
        self.assertEqual(len(hist), 3)
        self.assertEqual(hist[0]['field'], 'awake')
        self.assertEqual(hist[1]['field'], 'active_task')
        self.assertEqual(hist[2]['field'], 'active_conv')
        # 时间戳单调递增
        for i in range(1, len(hist)):
            self.assertGreaterEqual(hist[i]['ts'], hist[i - 1]['ts'])


class TestJarvisStateEventBusIntegration(unittest.TestCase):
    def setUp(self):
        self.bus = ConversationEventBus(max_events=20)
        self.state = JarvisState(event_bus=self.bus)

    def test_set_awake_publishes_to_bus(self):
        self.state.set_awake(True, reason='wake_word', source='ut')
        events = self.bus.recent_events(types={'state_awake_changed'})
        self.assertEqual(len(events), 1)
        self.assertIn('awake', events[0]['description'])
        self.assertIn('wake_word', events[0]['description'])

    def test_set_event_bus_after_construction(self):
        # 模拟生产路径：CentralNerve 先建 state 再建 bus，最后回填
        state2 = JarvisState()
        state2.set_awake(True, reason='wake_word')  # 无 bus 时不该挂
        bus2 = ConversationEventBus()
        state2.set_event_bus(bus2)
        state2.set_awake(False, reason='sleep_cmd')  # 现在有 bus 应该 publish
        events = bus2.recent_events(types={'state_awake_changed'})
        self.assertEqual(len(events), 1)
        self.assertIn('False', events[0]['description'])

    def test_three_setters_publish_independently(self):
        self.state.set_awake(True, reason='wake_word')
        self.state.set_active_task(True, reason='task_started')
        self.state.set_active_conversation(True, reason='wake')
        all_state_events = self.bus.recent_events(
            types={'state_awake_changed', 'state_active_task_changed', 'state_active_conv_changed'}
        )
        self.assertEqual(len(all_state_events), 3)


class TestJarvisStateThreadSafety(unittest.TestCase):
    def test_concurrent_writers(self):
        state = JarvisState()
        N = 50

        def flip_awake():
            for i in range(N):
                state.set_awake(i % 2 == 0, reason='wake_word')

        def flip_task():
            for i in range(N):
                state.set_active_task(i % 2 == 0, reason='task_started')

        def flip_conv():
            for i in range(N):
                state.set_active_conversation(i % 2 == 0, reason='wake')

        threads = [
            threading.Thread(target=flip_awake),
            threading.Thread(target=flip_task),
            threading.Thread(target=flip_conv),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不挂 + 状态值有效
        snap = state.snapshot()
        self.assertIsInstance(snap['awake'], bool)
        self.assertIsInstance(snap['active_task'], bool)
        self.assertIsInstance(snap['active_conversation'], bool)


class TestJarvisNerveScatteredWritesEliminated(unittest.TestCase):
    """源码契约：jarvis_nerve.py 里 JarvisWorkerThread.run / CentralNerve / VoiceListenThread
    的核心路径里不应再有"裸 self.is_awake = X"（应当走 state.set_awake 或 property setter）。
    例外：BreathingLightUI 等 UI 类有自己的 is_awake 字段，不计入。
    """

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()
        cls.lines = cls.src.splitlines()

    def _line_belongs_to_breathing_or_subtitle(self, idx: int) -> bool:
        # 往上找最近的 class 声明，看是不是 BreathingLightUI / SubtitleOverlay
        for j in range(idx, -1, -1):
            m = re.match(r'^class\s+(\w+)', self.lines[j])
            if m:
                return m.group(1) in ('BreathingLightUI', 'SubtitleOverlay')
        return False

    def test_no_scattered_is_awake_writes_in_jarvis_worker(self):
        # 在 JarvisWorkerThread 和 CentralNerve 类范围内，self.is_awake = True/False 应当被
        # state.set_awake 替代（property setter 兜底仍存在）。我们只检查"显式 True/False 字面"。
        offenders = []
        for i, ln in enumerate(self.lines):
            m = re.search(r'self\.is_awake\s*=\s*(True|False)\b', ln)
            if not m:
                continue
            if self._line_belongs_to_breathing_or_subtitle(i):
                continue  # UI 类，跳过
            offenders.append((i + 1, ln.strip()))
        self.assertEqual(
            offenders, [],
            f"仍有裸 self.is_awake = True/False 写入未走 state：{offenders}"
        )

    def test_no_scattered_is_active_task_writes(self):
        offenders = []
        for i, ln in enumerate(self.lines):
            m = re.search(r'self\.(jarvis\.)?is_active_task\s*=\s*(True|False)\b', ln)
            if not m:
                continue
            offenders.append((i + 1, ln.strip()))
        self.assertEqual(
            offenders, [],
            f"仍有裸 self.is_active_task = True/False 写入未走 state：{offenders}"
        )

    def test_voice_thread_state_attribute_wired_in_main(self):
        # main 里必须把 jarvis_worker.state 注入到 voice_worker.state
        self.assertRegex(
            self.src,
            r'voice_worker\.state\s*=\s*jarvis_worker\.state',
            "main 段必须把 jarvis_worker.state 注入到 voice_worker.state"
        )

    def test_central_nerve_has_state_attribute(self):
        # CentralNerve.__init__ 必须创建 self.state
        m = re.search(
            r'class\s+CentralNerve.*?def\s+__init__.*?from\s+jarvis_utils\s+import\s+JarvisState',
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "CentralNerve.__init__ 必须 import + 初始化 JarvisState")

    def test_jarvis_worker_inherits_state_from_central_nerve(self):
        # JarvisWorkerThread.__init__ 共享 self.jarvis.state
        self.assertRegex(
            self.src,
            r'self\.state\s*=\s*self\.jarvis\.state',
            "JarvisWorkerThread.__init__ 必须 self.state = self.jarvis.state"
        )


class TestVoiceListenThreadInActiveConversationProperty(unittest.TestCase):
    """直接 import VoiceListenThread 太重（依赖 PyQt5），只做源码契约校验。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_in_active_conversation_is_property(self):
        # 必须有 @property 装饰的 in_active_conversation
        self.assertRegex(
            self.src,
            r'@property\s+def\s+in_active_conversation',
            "in_active_conversation 必须是 property，能通过 state 中转"
        )

    def test_in_active_conversation_has_setter(self):
        self.assertRegex(
            self.src,
            r'@in_active_conversation\.setter\s+def\s+in_active_conversation',
            "in_active_conversation 必须有 setter，兼容老代码"
        )


class TestFalseAlarmDismissalReason(unittest.TestCase):
    """B3 修复：soft_focus 误判退出时必须标 'false_alarm'，不是空着让 wake_weight 当 natural。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_soft_focus_fail_path_sets_false_alarm(self):
        # 在 validate_soft_focus 返回 False 的分支里必须给 last_dismissal_reason 赋值
        # 找到 "检测到背景音/非对话" 这条字面附近，必须有 last_dismissal_reason = 'false_alarm'
        m = re.search(
            r"检测到背景音/非对话.*?last_dismissal_reason\s*=\s*['\"]false_alarm['\"]",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "soft_focus 误判退出分支必须设 last_dismissal_reason = 'false_alarm'")

    def test_wake_weight_recognizes_false_alarm(self):
        # _compute_wake_weight 必须显式处理 'false_alarm'，否则会被默认 natural 路径吃掉
        self.assertIn(
            "'false_alarm'",
            self.src,
            "_compute_wake_weight 必须显式处理 'false_alarm' 这个 dismissal reason"
        )


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestJarvisStateBasic),
        loader.loadTestsFromTestCase(TestJarvisStateEventBusIntegration),
        loader.loadTestsFromTestCase(TestJarvisStateThreadSafety),
        loader.loadTestsFromTestCase(TestJarvisNerveScatteredWritesEliminated),
        loader.loadTestsFromTestCase(TestVoiceListenThreadInActiveConversationProperty),
        loader.loadTestsFromTestCase(TestFalseAlarmDismissalReason),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-α/B1+B2+B3 JarvisState tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
