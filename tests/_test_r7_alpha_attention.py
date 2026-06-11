"""R7-α/AttentionContext 单元测试。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_alpha_attention.py

覆盖：
- capture_attention_snapshot 在 win32 不可用时降级到全 None
- AttentionSlot capture_now / latest / clear / TTL 过期
- render_attention_block 输出格式
- 源码契约：voice_thread 用 _emit_with_attention；prompt 注入 attention block
"""
import os
import re
import sys
import time
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    AttentionSlot, capture_attention_snapshot, render_attention_block,
    get_default_attention_slot,
)


class TestCaptureSnapshot(unittest.TestCase):
    def test_capture_returns_dict_with_required_keys(self):
        snap = capture_attention_snapshot()
        self.assertIsInstance(snap, dict)
        for k in ('ts', 'window_title', 'foreground_pid',
                  'cursor_pos', 'screen_size', 'recent_windows_5s'):
            self.assertIn(k, snap)

    def test_ts_is_recent(self):
        snap = capture_attention_snapshot()
        self.assertLess(abs(time.time() - snap['ts']), 1.0)

    def test_window_history_provider_filters_old(self):
        old = time.time() - 30.0
        recent = time.time() - 1.0
        provider = lambda: [
            {'time': old, 'title': 'Old Window'},
            {'time': recent, 'title': 'Recent Window'},
        ]
        snap = capture_attention_snapshot(window_history_provider=provider)
        # 30s 前的窗口不该出现
        titles = ' '.join(snap['recent_windows_5s'])
        self.assertNotIn('Old Window', titles)
        # 1s 前的窗口应该出现
        self.assertIn('Recent Window', titles)

    def test_provider_exception_doesnt_crash_capture(self):
        def bad():
            raise RuntimeError("blow up")
        snap = capture_attention_snapshot(window_history_provider=bad)
        # 抓拍应该照样返回（其他字段不受影响）
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap['recent_windows_5s'], [])

    def test_capture_under_10ms(self):
        # 不应该慢于 30ms（COM 调用偶尔抖动给一点空间），10ms 是软目标
        t0 = time.time()
        capture_attention_snapshot()
        elapsed_ms = (time.time() - t0) * 1000
        self.assertLess(elapsed_ms, 200.0, f"capture 太慢: {elapsed_ms:.0f}ms")


class TestAttentionSlot(unittest.TestCase):
    def setUp(self):
        self.slot = AttentionSlot(max_age_seconds=5.0)

    def test_initial_latest_is_empty(self):
        self.assertEqual(self.slot.latest(), {})

    def test_capture_then_latest(self):
        snap = self.slot.capture_now()
        self.assertIsInstance(snap, dict)
        got = self.slot.latest(max_age_seconds=10.0)
        self.assertIsInstance(got, dict)
        self.assertIn('ts', got)
        # latest 返回的是拷贝，不应该和 _snap 是同一对象
        self.assertIsNot(got, self.slot._snap)

    def test_latest_expires(self):
        self.slot.capture_now()
        # 假装时间已过 100s
        with mock.patch('jarvis_utils.time.time', return_value=time.time() + 100.0):
            self.assertEqual(self.slot.latest(max_age_seconds=5.0), {})

    def test_clear(self):
        self.slot.capture_now()
        self.assertNotEqual(self.slot.latest(max_age_seconds=10.0), {})
        self.slot.clear()
        self.assertEqual(self.slot.latest(), {})

    def test_thread_safety_capture_and_read(self):
        N = 30
        results = []

        def writer():
            for _ in range(N):
                self.slot.capture_now()

        def reader():
            for _ in range(N):
                results.append(self.slot.latest(max_age_seconds=10.0))

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不挂 + 所有读都是 dict（不是 None 不是异常）
        for r in results:
            self.assertIsInstance(r, dict)

    def test_set_window_history_provider(self):
        provider1 = lambda: [{'time': time.time(), 'title': 'A'}]
        self.slot.set_window_history_provider(provider1)
        snap = self.slot.capture_now()
        self.assertIn('A', ' '.join(snap['recent_windows_5s']))


class TestRenderBlock(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        self.assertEqual(render_attention_block({}), "")
        self.assertEqual(render_attention_block(None), "")

    def test_renders_window_only(self):
        snap = {'window_title': 'Visual Studio Code',
                'foreground_pid': None, 'cursor_pos': None,
                'screen_size': None, 'recent_windows_5s': []}
        block = render_attention_block(snap)
        self.assertIn("ATTENTION", block)
        self.assertIn("Visual Studio Code", block)

    def test_renders_cursor_with_grid(self):
        snap = {'window_title': None, 'foreground_pid': 1234,
                'cursor_pos': (960, 540),
                'screen_size': (1920, 1080),
                'recent_windows_5s': []}
        block = render_attention_block(snap)
        # 屏幕中央应当渲染成"中中"或类似
        self.assertIn("cursor=(960,540)", block)
        # 应该有方位标记
        self.assertTrue(any(tag in block for tag in ('中', '上', '下', '左', '右')))

    def test_renders_recent_switches(self):
        snap = {'window_title': 'Current', 'foreground_pid': None,
                'cursor_pos': None, 'screen_size': None,
                'recent_windows_5s': ['A', 'B', 'C']}
        block = render_attention_block(snap)
        self.assertIn("recent_switches", block)

    def test_max_chars_cap(self):
        snap = {'window_title': 'x' * 500, 'foreground_pid': 1,
                'cursor_pos': (0, 0), 'screen_size': (100, 100),
                'recent_windows_5s': ['y' * 100]}
        block = render_attention_block(snap, max_chars=120)
        # 标题部分（title 字段）+ body 限到 ≤ max_chars，整段含 title 不会爆
        self.assertLess(len(block), 600)


class TestSourceContract(unittest.TestCase):
    """jarvis_nerve.py 源码契约：voice_thread emit 走 _emit_with_attention；prompt 注入 attention block。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_voice_thread_has_emit_with_attention(self):
        self.assertRegex(
            self.src,
            r'def\s+_emit_with_attention\(self,\s*cmd',
            "VoiceListenThread 必须有 _emit_with_attention 方法"
        )

    def test_text_ready_emit_replaced(self):
        # VoiceListenThread.run 里 emit text_ready 的地方应该用 _emit_with_attention
        # 允许某些极端边角（停止/中断分支）保留裸 emit，但主要 4 处必须改写
        emit_call_count = len(re.findall(r'self\.text_ready\.emit\(', self.src))
        emit_via_attention_count = len(re.findall(r'self\._emit_with_attention\(', self.src))
        self.assertGreaterEqual(
            emit_via_attention_count, 3,
            f"至少 3 处 emit 应改走 _emit_with_attention，实际只有 {emit_via_attention_count}"
        )

    def test_prompt_has_attention_block(self):
        # _assemble_prompt 必须 import 并使用 render_attention_block
        self.assertIn('render_attention_block', self.src)
        # full 档 prompt 模板里必须包含 {attention_block} 占位
        self.assertIn('{attention_block}', self.src)

    def test_short_chat_tier_has_attention_too(self):
        # SHORT_CHAT 分支也要塞 attention（短聊也常用"这个/这里"）
        # 🆕 [fixT-r7 / Sir 2026-06-11 裁决I 修轨] M6.2 把 SHORT_CHAT tier 体抽进
        # _assemble_short_chat_prompt helper, 老 regex (dispatch 向后扫符号) 失锚.
        # 契约不变, 双锚现代化: dispatch 接线 + helper 体内含注入.
        m_dispatch = re.search(
            r"if prompt_tier == self\.PROMPT_TIER_SHORT_CHAT:.+?"
            r"_assemble_short_chat_prompt",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m_dispatch, "SHORT_CHAT dispatch 必须接 helper")
        m = re.search(
            r"def _assemble_short_chat_prompt.+?_short_attn",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "SHORT_CHAT 档必须也注入 _short_attn")

    def test_main_wires_attention_slot(self):
        self.assertRegex(
            self.src,
            r'voice_worker\._attention_slot\s*=\s*_attn_slot',
            "main 必须把 attention slot 注入到 voice_worker"
        )
        self.assertRegex(
            self.src,
            r'jarvis_worker\._attention_slot\s*=\s*_attn_slot',
            "main 必须把 attention slot 注入到 jarvis_worker"
        )


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestCaptureSnapshot),
        loader.loadTestsFromTestCase(TestAttentionSlot),
        loader.loadTestsFromTestCase(TestRenderBlock),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-α/AttentionContext tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
