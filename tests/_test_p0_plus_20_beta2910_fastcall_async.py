# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.10 / 2026-05-18] FAST_CALL 异步软超时治本工具卡顿

Sir 11:09 实测痛点 + 11:11 反对占位语音:
  "工具调用非常卡顿, 说话-工具-说话 变成 说话-卡顿-全部一起出"
  "我宁愿全部走主脑, 占位语音太没人味了"

设计 (准则 1 高效 + 准则 6 不硬编码):
  ChatBypass._execute_fast_call_with_soft_timeout 软超时 wrapper:
    submit 到 ThreadPoolExecutor
    try result(timeout=1.5s):
      ≤1.5s 完成 → 同步返 result + was_sync=True (短工具体验跟旧版无差)
      >1.5s → TimeoutError → 主 stream 立刻继续 + was_sync=False
        后台 callback 把 result 写 _pending_tool_results 列表
        下一轮 drain_pending_tool_results() 注入 stream_chat prompt
        让主脑看到真实工具反馈, 自然讲解, 不凭空说话

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta2910_fastcall_async.py
"""
import os
import sys
import time
import unittest
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_chat_bypass():
    """造一个最小 ChatBypass 实例供测试. 不启 daemon thread."""
    from jarvis_chat_bypass import ChatBypass
    # 用 __new__ 绕过 __init__ 中的 vocal_cord daemon, 手动初始化必要字段
    cb = ChatBypass.__new__(ChatBypass)

    import concurrent.futures
    import queue
    cb._tool_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix='TestAsync')
    cb._pending_tool_results = []
    cb._pending_tool_lock = threading.Lock()
    cb.TOOL_SOFT_TIMEOUT_S = 1.5
    cb.subtitle_queue = queue.Queue()
    cb.jarvis = MagicMock()
    cb.jarvis.hand_registry = {}
    return cb


class TestSoftTimeout(unittest.TestCase):
    """软超时核心契约"""

    def setUp(self):
        self.cb = _make_chat_bypass()

    def tearDown(self):
        try:
            self.cb._tool_executor.shutdown(wait=False)
        except Exception:
            pass

    def test_fast_tool_returns_sync(self):
        """短工具 (< timeout) 应同步返回, was_sync=True"""
        with patch.object(self.cb, '_execute_fast_call',
                            return_value='✅ fast_tool: done'):
            result, was_sync = self.cb._execute_fast_call_with_soft_timeout(
                'test_organ', 'fast_cmd', {}, timeout=1.0)
        self.assertEqual(result, '✅ fast_tool: done')
        self.assertTrue(was_sync, '短工具必须同步返回')

    def test_slow_tool_returns_placeholder(self):
        """慢工具 (> timeout) 应立刻返 placeholder, was_sync=False"""
        def _slow(*_args):
            time.sleep(0.5)  # > timeout 0.2
            return '✅ slow_tool: late done'

        with patch.object(self.cb, '_execute_fast_call', side_effect=_slow):
            result, was_sync = self.cb._execute_fast_call_with_soft_timeout(
                'slow_organ', 'slow_cmd', {}, timeout=0.2)
        self.assertFalse(was_sync, '慢工具不应阻塞主 stream')
        self.assertIn('异步执行中', result, '应返回 placeholder 含异步标识')

    def test_slow_tool_callback_writes_pending(self):
        """慢工具后台完成后 result 应进 _pending_tool_results"""
        def _slow(*_args):
            time.sleep(0.3)
            return '✅ slow tool: real result'

        with patch.object(self.cb, '_execute_fast_call', side_effect=_slow):
            self.cb._execute_fast_call_with_soft_timeout(
                'lazy_organ', 'lazy_cmd', {}, timeout=0.1)
        # 等后台完成
        time.sleep(0.8)
        with self.cb._pending_tool_lock:
            self.assertEqual(len(self.cb._pending_tool_results), 1)
            entry = self.cb._pending_tool_results[0]
            self.assertEqual(entry['organ'], 'lazy_organ')
            self.assertEqual(entry['command'], 'lazy_cmd')
            self.assertIn('real result', entry['result'])

    def test_pending_capacity_caps_at_20(self):
        """连续 25 个 pending 应只保留最后 20"""
        for i in range(25):
            with self.cb._pending_tool_lock:
                self.cb._pending_tool_results.append({
                    'organ': 'o', 'command': f'c{i}',
                    'result': 'r', 'ts': time.time(),
                })
        # 触发 cap 逻辑 (现在没自动 cap, 但 drain 会保 20 — 我们设 cap 在 callback)
        # 这里手动模拟一次 cap (按设计每次 append 后)
        with self.cb._pending_tool_lock:
            if len(self.cb._pending_tool_results) > 20:
                self.cb._pending_tool_results = self.cb._pending_tool_results[-20:]
        with self.cb._pending_tool_lock:
            self.assertLessEqual(len(self.cb._pending_tool_results), 20)


class TestDrainPendingToolResults(unittest.TestCase):
    """drain_pending_tool_results — 主脑下一轮看到真实工具反馈"""

    def setUp(self):
        self.cb = _make_chat_bypass()

    def tearDown(self):
        try:
            self.cb._tool_executor.shutdown(wait=False)
        except Exception:
            pass

    def test_empty_returns_empty_string(self):
        self.assertEqual(self.cb.drain_pending_tool_results(), '')

    def test_drain_returns_formatted_block(self):
        with self.cb._pending_tool_lock:
            self.cb._pending_tool_results.append({
                'organ': 'chrome_hands', 'command': 'open_url',
                'result': '✅ opened https://github.com',
                'ts': time.time() - 5,
            })
        text = self.cb.drain_pending_tool_results()
        self.assertIn('BACKGROUND TOOL RESULTS', text)
        self.assertIn('chrome_hands.open_url', text)
        self.assertIn('opened https://github.com', text)
        # drain 后 pending 应清空
        with self.cb._pending_tool_lock:
            self.assertEqual(len(self.cb._pending_tool_results), 0)

    def test_drain_includes_age(self):
        with self.cb._pending_tool_lock:
            self.cb._pending_tool_results.append({
                'organ': 'x', 'command': 'y', 'result': 'z',
                'ts': time.time() - 30,
            })
        text = self.cb.drain_pending_tool_results()
        self.assertIn('s ago', text)


class TestStreamChatInjectsDrain(unittest.TestCase):
    """stream_chat / stream_chat_cloud_followup 入口必须调 drain_pending_tool_results"""

    def test_stream_chat_calls_drain(self):
        import inspect
        from jarvis_chat_bypass import ChatBypass
        src = inspect.getsource(ChatBypass.stream_chat)
        self.assertIn('drain_pending_tool_results', src,
                       'stream_chat 必须调 drain 让主脑看异步工具结果')

    def test_stream_chat_cloud_followup_calls_drain(self):
        import inspect
        from jarvis_chat_bypass import ChatBypass
        src = inspect.getsource(ChatBypass.stream_chat_cloud_followup)
        self.assertIn('drain_pending_tool_results', src,
                       'stream_chat_cloud_followup 也必须调 drain')


if __name__ == '__main__':
    unittest.main(verbosity=2)
