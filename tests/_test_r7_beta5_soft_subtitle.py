"""R7-β5 单元测试：listening_start/done 软字幕状态条 + α5 兼容修复

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta5_soft_subtitle.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestSubtitleOverlayHandlersSourceContract(unittest.TestCase):
    """SubtitleOverlay._poll_queue 必须处理 listening_start/done + user + 兼容 α5。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_listening_start_handled(self):
        self.assertIn('elif lang == "listening_start":', self.src,
                      "_poll_queue 必须处理 listening_start")
        # 必须调用 show_user_speech 显示 "Listening…"
        m = re.search(
            r'elif lang == "listening_start":(.+?)(?=elif lang ==|except queue\.Empty)',
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m)
        self.assertIn('show_user_speech', m.group(1))

    def test_listening_done_handled(self):
        self.assertIn('elif lang == "listening_done":', self.src)

    def test_user_lang_handled(self):
        """α5 之前的 latent bug：subtitle_queue.put(('user', cmd)) 被静默丢。"""
        self.assertIn('elif lang == "user":', self.src,
                      "α5 latent bug 修复：'user' 类型 ASR 完成文本必须被处理")

    def test_focus_lang_handled(self):
        self.assertIn('elif lang == "focus":', self.src,
                      "'focus' 类型必须被处理")

    def test_silent_nudge_handled(self):
        self.assertIn('elif lang == "silent_nudge":', self.src,
                      "α5 'silent_nudge' 必须被 SubtitleOverlay 处理")

    def test_visual_pulse_handled_as_noop(self):
        # 至少 _poll_queue 里要 acknowledge 它的存在（即使 pass）
        self.assertIn('elif lang == "visual_pulse":', self.src,
                      "α5 'visual_pulse' 至少要明确 acknowledge（pass 也行）")


class TestVoiceListenThreadIntegrationSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_voice_thread_init_has_subtitle_queue_field(self):
        self.assertIn('self._subtitle_queue = None', self.src)

    def test_voice_thread_has_publish_listening_done(self):
        self.assertIn('def _publish_listening_done', self.src)

    def test_listening_start_pushed_on_first_voice_frame(self):
        # 在 is_speaking 第一帧（"接收物理声波" 那一行附近）必须 push listening_start
        m = re.search(
            r"接收物理声波.+?listening_start",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m,
                             "第一帧拾到声波时必须 push listening_start")

    def test_listening_done_pushed_on_too_short_or_hallucination(self):
        # 丢弃路径必须调 _publish_listening_done
        cnt = self.src.count('self._publish_listening_done()')
        self.assertGreaterEqual(cnt, 2,
                                f"至少 2 处丢弃路径要调 _publish_listening_done，实际：{cnt}")

    def test_main_wires_voice_subtitle_queue(self):
        self.assertRegex(
            self.src,
            r'voice_worker\._subtitle_queue\s*=\s*jarvis_worker\.chat_bypass\.subtitle_queue',
            "main 必须注入 voice_worker._subtitle_queue"
        )


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestSubtitleOverlayHandlersSourceContract),
        loader.loadTestsFromTestCase(TestVoiceListenThreadIntegrationSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-β5/SoftSubtitle tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
