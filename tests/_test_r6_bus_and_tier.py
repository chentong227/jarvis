"""R6 单元测试：ConversationEventBus + STOP/DISMISS 上下文 + wake_weight 反转 + prompt tier 分类。

跑法：
    cd d:\\Jarvis
    python tests/_test_r6_bus_and_tier.py
"""
import sys
import os
import re
import time
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import ConversationEventBus, get_default_event_bus


# ============================================================
# 1. ConversationEventBus
# ============================================================
class TestConversationEventBus(unittest.TestCase):
    def setUp(self):
        self.bus = ConversationEventBus(max_events=20)

    def test_publish_and_read(self):
        self.assertTrue(self.bus.publish('conversation_event', 'Sir made a breakthrough on the bug'))
        events = self.bus.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['type'], 'conversation_event')
        self.assertIn('breakthrough', events[0]['description'])

    def test_publish_dedupe(self):
        # 8 秒内同类型同短描述会被去重
        self.assertTrue(self.bus.publish('proactive_nudge', 'offer_help dispatched'))
        self.assertFalse(self.bus.publish('proactive_nudge', 'offer_help dispatched'))
        # 不同 description 不去重
        self.assertTrue(self.bus.publish('proactive_nudge', 'stretch dispatched'))

    def test_ttl_expiry(self):
        # 用 ttl=0.1 模拟极短过期
        self.bus.publish('emotion_shift', 'Stressed -> Frustrated', ttl=0.1)
        time.sleep(0.15)
        events = self.bus.recent_events()
        self.assertEqual(len(events), 0)

    def test_to_prompt_block_renders(self):
        self.bus.publish('conversation_event', 'callback: Sir is referencing earlier file conversation')
        self.bus.publish('commitment_detected', 'Sir committed: "going to bed at 1 AM"')
        block = self.bus.to_prompt_block()
        self.assertIn('CONVERSATION STATE', block)
        self.assertIn('conversation_event', block)
        self.assertIn('commitment_detected', block)
        # 优先级排序：commitment_detected 优先级高于 conversation_event
        commitment_idx = block.index('commitment_detected')
        ce_idx = block.index('conversation_event')
        self.assertLess(commitment_idx, ce_idx,
                        "commitment_detected 优先级应高于 conversation_event，应当排在前面")

    def test_to_prompt_block_empty(self):
        self.assertEqual(self.bus.to_prompt_block(), "")

    def test_filter_by_type(self):
        self.bus.publish('conversation_event', 'callback event happens here')
        self.bus.publish('proactive_nudge', 'stretch nudge fired here')
        evts = self.bus.recent_events(types={'conversation_event'})
        self.assertEqual(len(evts), 1)
        self.assertEqual(evts[0]['type'], 'conversation_event')

    def test_max_chars_cap(self):
        for i in range(15):
            self.bus.publish('conversation_event', f'long event description number {i} ' * 5)
        block = self.bus.to_prompt_block(max_chars=300)
        self.assertLessEqual(len(block), 305)  # 留 …5字符余量

    def test_thread_safety(self):
        # 8 个线程并发写
        def worker(idx):
            for i in range(50):
                self.bus.publish(f'persona_note', f'thread-{idx}-msg-{i}-uniquesuffix')
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 因为 max_events=20，最后应只剩 20 条
        self.assertLessEqual(len(self.bus.snapshot()), 20)

    def test_default_singleton(self):
        b1 = get_default_event_bus()
        b2 = get_default_event_bus()
        self.assertIs(b1, b2)


# ============================================================
# 2. STOP_WORDS / DISMISS_WORDS 上下文感知
# ============================================================
class TestStopDismissContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 用 PyQt 准备 QApplication（VoiceListenThread 是 QThread）
        from PyQt5.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)
        from jarvis_nerve import VoiceListenThread
        cls.thread = VoiceListenThread()

    def test_strict_stop_exact_match(self):
        self.assertTrue(self.thread.detect_stop_command("闭嘴"))
        self.assertTrue(self.thread.detect_stop_command("退下"))
        self.assertTrue(self.thread.detect_stop_command("停止"))
        self.assertTrue(self.thread.detect_stop_command("shut up"))
        self.assertTrue(self.thread.detect_stop_command("stand down"))

    def test_strict_stop_at_head(self):
        self.assertTrue(self.thread.detect_stop_command("停止吧 Jarvis"))
        self.assertTrue(self.thread.detect_stop_command("Stand down, Jarvis"))
        self.assertTrue(self.thread.detect_stop_command("退下，谢谢"))

    def test_soft_stop_anjing_short(self):
        # "安静" 单独说才触发
        self.assertTrue(self.thread.detect_stop_command("安静"))

    def test_soft_stop_anjing_long_skips(self):
        # "外面很安静" / "现在很安静" 不应触发
        self.assertFalse(self.thread.detect_stop_command("外面很安静"),
                         "'外面很安静' 不应被判为强制停止")
        self.assertFalse(self.thread.detect_stop_command("现在很安静"),
                         "'现在很安静' 不应被判为强制停止")
        self.assertFalse(self.thread.detect_stop_command("环境真的好安静"),
                         "'环境真的好安静' 不应被判为强制停止")

    def test_dismiss_exact_match(self):
        self.assertTrue(self.thread.detect_dismiss_command("thanks"))
        self.assertTrue(self.thread.detect_dismiss_command("再见"))
        self.assertTrue(self.thread.detect_dismiss_command("晚安"))
        self.assertTrue(self.thread.detect_dismiss_command("bye"))

    def test_dismiss_short_sentence(self):
        self.assertTrue(self.thread.detect_dismiss_command("ok thanks"))
        self.assertTrue(self.thread.detect_dismiss_command("好的 再见"))
        self.assertTrue(self.thread.detect_dismiss_command("Good night, Jarvis"))

    def test_dismiss_long_sentence_skips(self):
        # "Thanks for that, can you also help with X" 不应触发告别
        self.assertFalse(
            self.thread.detect_dismiss_command(
                "Thanks for that, can you also help me with the file"),
            "'Thanks for that, can you also...' 不应误判告别"
        )
        self.assertFalse(
            self.thread.detect_dismiss_command("谢谢你刚才的解释 我还有别的问题"),
            "'谢谢你刚才的解释 我还有别的问题' 不应误判告别"
        )


# ============================================================
# 3. wake_weight 反转：last_dismissal_reason
# ============================================================
class TestWakeWeightReason(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)
        from jarvis_nerve import VoiceListenThread, JarvisWorkerThread
        cls.voice = VoiceListenThread()

        # 同 tier 测试一样，用 __new__ 跳过 JarvisWorkerThread 的真实 init
        proxy = JarvisWorkerThread.__new__(JarvisWorkerThread)
        proxy.voice_thread = cls.voice
        proxy.jarvis = type('J', (), {'short_term_memory': []})()
        cls.worker = proxy
        cls._compute = proxy._compute_wake_weight

    def test_manual_stop_recent_decreases(self):
        # 模拟：30s 前用户喊"闭嘴"
        self.voice.last_conversation_end_time = time.time() - 5
        self.voice.last_dismissal_reason = 'manual_stop'
        self.voice.in_active_conversation = False
        w_after_stop = self._compute("jarvis", ["jarvis"])
        # 同样的 jarvis 单词，没有 stop 历史
        self.voice.last_dismissal_reason = None
        self.voice.last_conversation_end_time = 0
        w_clean = self._compute("jarvis", ["jarvis"])
        self.assertLess(w_after_stop, w_clean,
                        "manual_stop 后 30s 内 wake_weight 应该比无历史更低")

    def test_timeout_recent_increases(self):
        # 模拟：30s 前自然超时，用户复唤醒
        self.voice.last_conversation_end_time = time.time() - 30
        self.voice.last_dismissal_reason = 'timeout'
        self.voice.in_active_conversation = False
        w_after_timeout = self._compute("jarvis", ["jarvis"])
        # 无历史
        self.voice.last_dismissal_reason = None
        self.voice.last_conversation_end_time = 0
        w_clean = self._compute("jarvis", ["jarvis"])
        self.assertGreaterEqual(w_after_timeout, w_clean,
                                "timeout 后短时复唤醒 wake_weight 应该 ≥ 无历史")

    def test_in_active_decreases(self):
        self.voice.last_dismissal_reason = None
        self.voice.last_conversation_end_time = 0
        self.voice.in_active_conversation = True
        w_active = self._compute("jarvis", ["jarvis"])
        self.voice.in_active_conversation = False
        w_inactive = self._compute("jarvis", ["jarvis"])
        self.assertLess(w_active, w_inactive,
                        "in_active_conversation=True 时不需要再唤醒，应减权")


# ============================================================
# 4. Prompt Tier 五档分类
# ============================================================
class TestPromptTierClassifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)
        from jarvis_nerve import VoiceListenThread, JarvisWorkerThread
        cls.voice = VoiceListenThread()

        class _MockJarvis:
            short_term_memory = []

        # 用 __new__ 跳过 JarvisWorkerThread 的真实 init（避免拉 CentralNerve）；
        # 保留所有类属性（_TIER_*、PROMPT_TIER_*、_compute_wake_weight 等）
        proxy = JarvisWorkerThread.__new__(JarvisWorkerThread)
        proxy.voice_thread = cls.voice
        proxy.jarvis = _MockJarvis()
        cls.worker = proxy
        cls._tiers = JarvisWorkerThread

    def _classify_cmd(self, cmd):
        cmd_words = cmd.lower().strip().split()
        cmd_clean = re.sub(r'[^\w\s]', '', cmd.lower()).strip()
        return self.worker._classify_prompt_tier(cmd, cmd_clean, cmd_words)

    def test_wake_only_simple_name(self):
        # 必须有 wake_weight ≥ 0.65。"jarvis" 单词：exact(0.55) + short(0.15) + word_count=1(0.10) = 0.80
        self.assertEqual(self._classify_cmd("jarvis"), self._tiers.PROMPT_TIER_WAKE_ONLY)
        self.assertEqual(self._classify_cmd("贾维斯"), self._tiers.PROMPT_TIER_WAKE_ONLY)

    def test_critical_reminder(self):
        self.assertEqual(self._classify_cmd("remind me to drink water in 30 minutes"),
                         self._tiers.PROMPT_TIER_CRITICAL)
        self.assertEqual(self._classify_cmd("帮我设个闹钟 5 点"),
                         self._tiers.PROMPT_TIER_CRITICAL)
        self.assertEqual(self._classify_cmd("提醒我下午开会"),
                         self._tiers.PROMPT_TIER_CRITICAL)

    def test_tool_request_open(self):
        self.assertEqual(self._classify_cmd("open the D drive"),
                         self._tiers.PROMPT_TIER_TOOL_REQUEST)
        self.assertEqual(self._classify_cmd("打开桌面文件夹"),
                         self._tiers.PROMPT_TIER_TOOL_REQUEST)
        self.assertEqual(self._classify_cmd("把音量调到 30"),
                         self._tiers.PROMPT_TIER_TOOL_REQUEST)

    def test_deep_query_historical(self):
        self.assertEqual(self._classify_cmd("remember when we talked about the bug"),
                         self._tiers.PROMPT_TIER_DEEP_QUERY)
        self.assertEqual(self._classify_cmd("上次咱们聊过的那个项目"),
                         self._tiers.PROMPT_TIER_DEEP_QUERY)

    def test_short_chat_default(self):
        # 短中性闲聊，不命中任何关键词
        self.assertEqual(self._classify_cmd("how are you doing today"),
                         self._tiers.PROMPT_TIER_SHORT_CHAT)
        self.assertEqual(self._classify_cmd("nice weather"),
                         self._tiers.PROMPT_TIER_SHORT_CHAT)

    def test_long_unknown_falls_to_deep(self):
        long_cmd = "I was reading this paper on transformer architectures and " \
                   "was wondering about the relationship between attention head count and " \
                   "model perplexity, especially in low-resource regimes."
        self.assertEqual(self._classify_cmd(long_cmd),
                         self._tiers.PROMPT_TIER_DEEP_QUERY)

    def test_critical_overrides_tool(self):
        # 同时有 "open" 和 "remind"，CRITICAL 优先
        self.assertEqual(
            self._classify_cmd("open the file and remind me to close it at 5pm"),
            self._tiers.PROMPT_TIER_CRITICAL
        )


def main():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    try:
        print("\n[OK] All R6 bus / context / wake / tier tests passed.")
    except UnicodeEncodeError:
        sys.stdout.write("\n[OK] All R6 bus / context / wake / tier tests passed.\n")


if __name__ == "__main__":
    main()
