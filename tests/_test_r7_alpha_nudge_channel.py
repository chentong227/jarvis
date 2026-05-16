"""R7-α/NudgeChannel 单元测试。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_alpha_nudge_channel.py

覆盖：
- NUDGE_CHANNEL_* 三档常量
- resolve_nudge_channel：默认映射 + override
- render_silent_nudge_text：优先级 silent_text > conductor_message > 模板
- DEFAULT_NUDGE_CHANNEL_MAP 关键类型的分流（offer_help=voice / screen_tease=silent_text）
- 源码契约：SmartNudge._dispatch_nudge 设 channel；JarvisWorker.run 分支处理 channel
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    NUDGE_CHANNEL_VOICE, NUDGE_CHANNEL_SILENT_TEXT, NUDGE_CHANNEL_VISUAL_PULSE,
    NUDGE_CHANNELS, DEFAULT_NUDGE_CHANNEL_MAP,
    resolve_nudge_channel, render_silent_nudge_text,
    SILENT_NUDGE_TEMPLATES,
)


class TestChannelConstants(unittest.TestCase):
    def test_three_channels_defined(self):
        self.assertEqual(NUDGE_CHANNEL_VOICE, 'voice')
        self.assertEqual(NUDGE_CHANNEL_SILENT_TEXT, 'silent_text')
        self.assertEqual(NUDGE_CHANNEL_VISUAL_PULSE, 'visual_pulse')
        self.assertEqual(set(NUDGE_CHANNELS),
                         {'voice', 'silent_text', 'visual_pulse'})


class TestResolveChannel(unittest.TestCase):
    def test_critical_types_route_to_voice(self):
        for t in ('offer_help', 'commitment_check', 'late_night',
                  'suggest_break', 'return_greeting'):
            self.assertEqual(resolve_nudge_channel(t), NUDGE_CHANNEL_VOICE,
                             f"{t} 应当走 VOICE")

    def test_trivia_types_route_to_silent_text(self):
        for t in ('screen_tease', 'atmosphere', 'afternoon',
                  'hydration', 'stretch', 'flow_end'):
            self.assertEqual(resolve_nudge_channel(t), NUDGE_CHANNEL_SILENT_TEXT,
                             f"{t} 应当走 SILENT_TEXT")

    def test_brief_types_route_to_visual_pulse(self):
        for t in ('background_brief', 'task_handoff_ready'):
            self.assertEqual(resolve_nudge_channel(t), NUDGE_CHANNEL_VISUAL_PULSE,
                             f"{t} 应当走 VISUAL_PULSE")

    def test_unknown_type_defaults_to_voice(self):
        self.assertEqual(resolve_nudge_channel('unknown_xxx'), NUDGE_CHANNEL_VOICE)

    def test_override_wins(self):
        # override 优先于默认映射
        self.assertEqual(
            resolve_nudge_channel('offer_help', override='silent_text'),
            NUDGE_CHANNEL_SILENT_TEXT,
        )
        # invalid override 退回默认
        self.assertEqual(
            resolve_nudge_channel('offer_help', override='garbage'),
            NUDGE_CHANNEL_VOICE,
        )


class TestRenderSilentText(unittest.TestCase):
    def test_explicit_silent_text_wins(self):
        ctx = {'silent_text': "Custom whisper, Sir.", 'conductor_message': "Should be ignored."}
        self.assertEqual(render_silent_nudge_text('screen_tease', ctx),
                         "Custom whisper, Sir.")

    def test_conductor_message_used_when_no_explicit(self):
        ctx = {'conductor_message': "Sir 已经工作 90 分钟。"}
        text = render_silent_nudge_text('atmosphere', ctx)
        self.assertIn("Sir", text)
        self.assertLessEqual(len(text), 100)

    def test_template_used_when_no_context(self):
        text = render_silent_nudge_text('screen_tease')
        self.assertEqual(text, SILENT_NUDGE_TEMPLATES['screen_tease'])

    def test_fallback_for_unknown_type(self):
        text = render_silent_nudge_text('unknown_xyz')
        self.assertIn('unknown_xyz', text)

    def test_length_cap(self):
        ctx = {'silent_text': 'x' * 500}
        text = render_silent_nudge_text('foo', ctx)
        self.assertLessEqual(len(text), 100)

    def test_long_conductor_message_skipped(self):
        # conductor_message 超过 200 字时不该被当字幕用（太长不适合飘）
        ctx = {'conductor_message': 'x' * 300}
        text = render_silent_nudge_text('unknown_yyy', ctx)
        # 应当走兜底模板 / 通用兜底，而不是塞 300 字字幕
        self.assertLessEqual(len(text), 100)


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_smart_nudge_sets_channel(self):
        # SmartNudge._dispatch_nudge 必须调 resolve_nudge_channel 并把结果塞回 context
        m = re.search(
            r"def _dispatch_nudge.+?resolve_nudge_channel.+?context\[['\"]channel['\"]\]",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "SmartNudge._dispatch_nudge 必须设 context['channel']")

    def test_worker_handles_silent_text_channel(self):
        self.assertIn("nudge_channel == 'silent_text'", self.src,
                      "JarvisWorker 必须有 silent_text 分支")

    def test_worker_handles_visual_pulse_channel(self):
        self.assertIn("nudge_channel == 'visual_pulse'", self.src,
                      "JarvisWorker 必须有 visual_pulse 分支")

    def test_silent_text_branch_does_not_call_stream_nudge(self):
        # silent_text 分支必须立即 continue，不能走 stream_nudge
        m = re.search(
            r"if nudge_channel == 'silent_text':(.+?)continue",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "silent_text 分支必须以 continue 收尾")
        block = m.group(1)
        self.assertNotIn('stream_nudge', block,
                         "silent_text 分支不该调 stream_nudge（不出声）")

    def test_silent_text_uses_render_silent_nudge_text(self):
        # silent_text 分支应当调 render_silent_nudge_text 生成字幕
        self.assertIn('render_silent_nudge_text', self.src)

    def test_silent_text_writes_to_subtitle_queue(self):
        # silent_text 必须把字幕推到 subtitle_queue
        m = re.search(
            r"if nudge_channel == 'silent_text':(.+?)continue",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m)
        self.assertIn('subtitle_queue.put', m.group(1))
        self.assertIn('silent_nudge', m.group(1))

    def test_silent_text_publishes_to_event_bus(self):
        m = re.search(
            r"if nudge_channel == 'silent_text':(.+?)continue",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m)
        self.assertIn("'proactive_nudge'", m.group(1))


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestChannelConstants),
        loader.loadTestsFromTestCase(TestResolveChannel),
        loader.loadTestsFromTestCase(TestRenderSilentText),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-α/NudgeChannel tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
