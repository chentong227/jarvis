"""R7-β2/v5 单元测试：Backchannel timer 残留接口

[v5 / Sir-2026-05-14] backchannel chime 已删除（与 play_acknowledgment_chime 重复），
本套件转为"chime 真的被移除"+"timer 残留接口仍兼容老调用"的验证。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta2_backchannel.py

覆盖：
- _generate_backchannel_pcm 已从源码中移除
- ChatBypass.__init__ 不再含 _backchannel_pcm 字段
- _start_backchannel_timer / _mark_first_token 方法仍存在（接口兼容）
- timer 真启动但永不播 chime（play_count 恒为 0）
- 源码契约：stream_chat 仍调 _start_backchannel_timer；3 个 emit 分支 + interrupt_all 仍 _mark_first_token
"""
import os
import re
import sys
import time
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class _MockVocal:
    """模拟 vocal.play_only / vocal.say：记录调用次数 + 阻塞时长。"""
    def __init__(self):
        self.play_count = 0
        self.say_count = 0
        self.last_pcm = None
        self.last_text = None
        self.lock = threading.Lock()

    def play_only(self, audio_bytes: bytes):
        with self.lock:
            self.play_count += 1
            self.last_pcm = audio_bytes
        time.sleep(0.05)

    def say(self, text: str):
        with self.lock:
            self.say_count += 1
            self.last_text = text
        time.sleep(0.05)


class _MockSubtitleQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _MockBypass:
    """轻量 ChatBypass mock：v5 移除 _backchannel_pcm，timer 接口保留。"""

    def __init__(self):
        self.vocal = _MockVocal()
        self._first_token_received = False
        self._backchannel_timer = None
        self.is_interrupted = False
        self.jarvis = None
        self._local_utterance_timer = None
        self._local_utterance_in_progress = False
        self.subtitle_queue = _MockSubtitleQueue()
        from jarvis_nerve import ChatBypass
        self._LOCAL_UTTERANCE_POOL = ChatBypass._LOCAL_UTTERANCE_POOL
        self._LOCAL_UTTERANCE_ENABLED = ChatBypass._LOCAL_UTTERANCE_ENABLED
        self._pick_local_utterance = (
            lambda *a, **kw: ChatBypass._pick_local_utterance(self, *a, **kw)
        )
        self._start_backchannel_timer = (
            lambda *a, **kw: ChatBypass._start_backchannel_timer(self, *a, **kw)
        )
        self._mark_first_token = lambda: ChatBypass._mark_first_token(self)


class TestBackchannelChimeRemoved(unittest.TestCase):
    """v5：chime 通道整体移除验证。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_generate_backchannel_pcm_method_gone(self):
        self.assertNotIn('def _generate_backchannel_pcm', self.src,
                         "_generate_backchannel_pcm 已被 v5 移除，应不再出现在源码")

    def test_init_no_backchannel_pcm_assignment(self):
        # __init__ 不再有 self._backchannel_pcm = ... 的赋值
        m = re.search(r"self\._backchannel_pcm\s*=\s*self\._generate_backchannel_pcm", self.src)
        self.assertIsNone(m, "ChatBypass.__init__ 不应再合成 _backchannel_pcm")

    def test_no_play_chime_closure(self):
        # _maybe_play_chime 闭包应被移除
        self.assertNotIn('def _maybe_play_chime', self.src,
                         "_maybe_play_chime 闭包应已移除")

    def test_chime_threshold_const_still_present(self):
        # _CHIME_THRESHOLD_DEFAULT 常量保留（call site 还在用），不破坏 p3 测试
        self.assertIn('_CHIME_THRESHOLD_DEFAULT = 1.5', self.src)


class TestBackchannelTimerNoChime(unittest.TestCase):
    """v5：timer 启动后无声（保证 chime 真的不响）。"""

    def setUp(self):
        self.bypass = _MockBypass()

    def test_timer_fires_but_no_chime_played(self):
        """timer 触发也不该有 vocal.play_only 调用（chime 已删除）。"""
        self.bypass._start_backchannel_timer(threshold_sec=0.1)
        time.sleep(0.4)
        self.assertEqual(self.bypass.vocal.play_count, 0,
                         "v5: chime 已删，timer 触发不该播任何 PCM")

    def test_local_utterance_timer_fires_but_disabled(self):
        """local_utterance Timer 触发但 _LOCAL_UTTERANCE_ENABLED=False 短路。"""
        self.bypass._start_backchannel_timer(threshold_sec=0.1,
                                             local_utterance_threshold=0.2)
        time.sleep(0.5)
        self.assertEqual(self.bypass.vocal.say_count, 0,
                         "_LOCAL_UTTERANCE_ENABLED=False 时不该 vocal.say")
        self.assertEqual(self.bypass.vocal.play_count, 0,
                         "v5: chime 已删，play_count 恒 0")

    def test_first_token_marks_received(self):
        """_mark_first_token 必须设置 _first_token_received=True。"""
        self.bypass._start_backchannel_timer(threshold_sec=0.3)
        time.sleep(0.05)
        self.bypass._mark_first_token()
        self.assertTrue(self.bypass._first_token_received)
        # 即便 timer 后续触发也不该出声
        time.sleep(0.5)
        self.assertEqual(self.bypass.vocal.play_count, 0)
        self.assertEqual(self.bypass.vocal.say_count, 0)

    def test_restart_timer_safe(self):
        """重启 timer 不抛 + 旧 timer 被释放。"""
        self.bypass._start_backchannel_timer(threshold_sec=0.3)
        time.sleep(0.05)
        self.bypass._start_backchannel_timer(threshold_sec=0.1)
        time.sleep(0.3)
        self.assertEqual(self.bypass.vocal.play_count, 0)

    def test_interrupted_no_side_effect(self):
        self.bypass.is_interrupted = True
        self.bypass._start_backchannel_timer(threshold_sec=0.1)
        time.sleep(0.3)
        self.assertEqual(self.bypass.vocal.play_count, 0)
        self.assertEqual(self.bypass.vocal.say_count, 0)


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_chatbypass_init_has_residual_fields(self):
        # v5 保留 _first_token_received + _backchannel_timer，不再有 _backchannel_pcm
        self.assertIn('self._first_token_received', self.src)
        self.assertIn('self._backchannel_timer', self.src)

    def test_residual_methods_defined(self):
        # _start_backchannel_timer / _mark_first_token 仍要在（接口兼容）
        self.assertIn('def _start_backchannel_timer', self.src)
        self.assertIn('def _mark_first_token', self.src)

    def test_stream_chat_starts_timer(self):
        # stream_chat 入口仍需 _start_backchannel_timer（哪怕只是为了 future local utterance）
        self.assertRegex(
            self.src,
            r'self\._start_backchannel_timer\(threshold_sec=(?:0\.6|self\._CHIME_THRESHOLD_DEFAULT)',
        )

    def test_first_token_marks_in_branches(self):
        # 正常 streaming / gatekeeper / fast_call 三个分支 + interrupt_all + wrap-up 都应 _mark_first_token
        cnt = self.src.count('self._mark_first_token()') + self.src.count('chat_bypass._mark_first_token()')
        self.assertGreaterEqual(cnt, 4,
                                f"_mark_first_token 至少应被调 4 次，实际：{cnt}")

    def test_interrupt_all_cancels_residual_timer(self):
        m = re.search(
            r"def interrupt_all\(self\):.+?_mark_first_token\(\)",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "interrupt_all 必须 _mark_first_token()")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestBackchannelChimeRemoved),
        loader.loadTestsFromTestCase(TestBackchannelTimerNoChime),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] R7-β2/v5 backchannel removal tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
