"""R7-α/B5+B6+B8 单元测试：stream_chat / interrupt_all / _play_worker 打磨。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_alpha_bugs.py

覆盖：
- B5: stream_chat 熔断时往 event_bus publish 'tool_chain_circuit_broken'
  - DEFAULT_TTL 包含该类型 + 优先级 = 7
- B6: interrupt_all 顺序修正（vocal.stop 先于 queue.clear；plan_ledger.cancel_all）
- B8: _render_in_progress 标志位（_render_worker 置位 + finally 复位；_play_worker 检查）
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import ConversationEventBus


class TestB5EventBusType(unittest.TestCase):
    def test_circuit_broken_in_default_ttl(self):
        self.assertIn('tool_chain_circuit_broken', ConversationEventBus.DEFAULT_TTL)
        self.assertGreaterEqual(
            ConversationEventBus.DEFAULT_TTL['tool_chain_circuit_broken'], 60,
            "circuit_broken TTL 应当足够长（至少 60s），让下一轮还能看见"
        )

    def test_circuit_broken_publishable(self):
        bus = ConversationEventBus()
        ok = bus.publish(
            'tool_chain_circuit_broken',
            'reason=duplicate_call:audio_hands.set_volume | ✅1 ❌0',
            source='stream_chat',
            metadata={'reason': 'duplicate_call', 'ok_count': 1, 'fail_count': 0},
        )
        self.assertTrue(ok)
        events = bus.recent_events(types={'tool_chain_circuit_broken'})
        self.assertEqual(len(events), 1)
        self.assertIn('duplicate_call', events[0]['description'])

    def test_circuit_broken_appears_in_prompt_block_with_high_priority(self):
        bus = ConversationEventBus()
        # 故意先发一些低优先级的事件
        bus.publish('persona_note', 'some low-priority note here')
        bus.publish('tool_executed', 'audio_hands.set_volume done')
        # 再发 circuit_broken
        bus.publish('tool_chain_circuit_broken',
                    'reason=duplicate_call:audio_hands.set_volume',
                    metadata={'reason': 'duplicate'})
        block = bus.to_prompt_block(max_chars=1000)
        # circuit_broken 应当在 persona_note 之前出现（优先级更高）
        idx_circuit = block.find('tool_chain_circuit_broken')
        idx_persona = block.find('persona_note')
        self.assertGreaterEqual(idx_circuit, 0)
        self.assertGreaterEqual(idx_persona, 0)
        self.assertLess(idx_circuit, idx_persona,
                        "circuit_broken 优先级应高于 persona_note，先出现在 prompt 块")


class TestB5SourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_stream_chat_publishes_circuit_broken(self):
        # 必须在 _circuit_broken_reason 且 _tool_results 都满足时 publish
        m = re.search(
            r"if _circuit_broken_reason and _tool_results:.+?bus\.publish\(\s*etype\s*=\s*['\"]tool_chain_circuit_broken['\"]",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "stream_chat 必须在熔断时 publish tool_chain_circuit_broken")


class TestB6SourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_interrupt_all_calls_vocal_stop_before_queue_clear(self):
        """B6: vocal.stop() 必须在 audio_queue.queue.clear() 之前。"""
        # 找到 interrupt_all 方法范围
        m = re.search(
            r"def interrupt_all\(self\):(.+?)(?=^\s{4}def\s+\w+|\Z)",
            self.src, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(m, "未定位到 interrupt_all 方法")
        body = m.group(1)
        idx_vocal_stop = body.find('vocal.stop()')
        idx_audio_clear = body.find('audio_queue.queue.clear()')
        self.assertGreaterEqual(idx_vocal_stop, 0, "interrupt_all 必须调 vocal.stop()")
        self.assertGreaterEqual(idx_audio_clear, 0, "interrupt_all 必须 clear audio_queue")
        self.assertLess(idx_vocal_stop, idx_audio_clear,
                        "B6: vocal.stop() 必须在 audio_queue.queue.clear() 之前调")

    def test_interrupt_all_resets_render_in_progress(self):
        # B6 顺手：把 _render_in_progress 归零，让 _play_worker 走 IDLE
        m = re.search(
            r"def interrupt_all\(self\):.+?_render_in_progress\s*=\s*False",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "interrupt_all 必须把 _render_in_progress 归零")

    def test_interrupt_all_cancels_active_plans(self):
        # 急停时也应取消所有 active plan
        m = re.search(
            r"def interrupt_all\(self\):.+?plan_ledger.+?cancel_all\(",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "interrupt_all 必须取消所有 active plan")


class TestB8SourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_render_in_progress_attribute_declared(self):
        # ChatBypass.__init__ 必须声明 self._render_in_progress = False
        self.assertRegex(
            self.src,
            r'self\._render_in_progress\s*=\s*False',
            "ChatBypass.__init__ 必须声明 self._render_in_progress = False"
        )

    def test_render_worker_sets_and_resets_flag(self):
        # _render_worker 必须置 True，并在 finally 块里复位
        m = re.search(
            r"def _render_worker\(self\):.+?self\._render_in_progress\s*=\s*True"
            r".+?finally:.+?self\._render_in_progress\s*=\s*False",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "_render_worker 必须 try/finally 置 True/复位 False")

    def test_play_worker_checks_render_in_progress_before_idle(self):
        # _play_worker 在 emit IDLE 前必须检查 _render_in_progress
        m = re.search(
            r"def _play_worker\(self\):(.+?)(?=^\s{4}def\s+\w+|\Z)",
            self.src, re.MULTILINE | re.DOTALL
        )
        self.assertIsNotNone(m, "未定位到 _play_worker")
        body = m.group(1)
        self.assertIn('not self._render_in_progress', body,
                      "_play_worker 必须用 not self._render_in_progress 守护 IDLE")
        # 两处 IDLE 都要守护：30s 超时分支 + 空队列分支
        guarded_count = body.count('not self._render_in_progress')
        self.assertGreaterEqual(guarded_count, 2,
                                "至少有 2 处 IDLE 分支被 _render_in_progress 守护")


class TestRenderInProgressFlagBehavior(unittest.TestCase):
    """跑出一个最小桩，用真的 ChatBypass 类太重；改用纯 mock 验证标志位生命周期。"""

    def test_flag_lifecycle_in_render_worker(self):
        # 模拟 _render_worker 内部行为：进 True，render 抛异常，finally 也必须复位
        class _Stub:
            _render_in_progress = False
            def _do(self):
                self._render_in_progress = True
                try:
                    raise RuntimeError("render exploded")
                finally:
                    self._render_in_progress = False

        s = _Stub()
        try:
            s._do()
        except RuntimeError:
            pass
        self.assertFalse(s._render_in_progress, "异常后必须复位为 False（finally）")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestB5EventBusType),
        loader.loadTestsFromTestCase(TestB5SourceContract),
        loader.loadTestsFromTestCase(TestB6SourceContract),
        loader.loadTestsFromTestCase(TestB8SourceContract),
        loader.loadTestsFromTestCase(TestRenderInProgressFlagBehavior),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-α/B5+B6+B8 tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
