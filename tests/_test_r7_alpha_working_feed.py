"""R7-α/WorkingMemoryFeed 单元测试。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_alpha_working_feed.py

覆盖：
- WorkingMemoryFeed push / recent / TTL 过期
- to_prompt_block 渲染（clipboard / terminal / file_saved / window_focus）
- 默认单例 get_default_working_feed
- PSHistoryWatcher 文件 mtime + 行差分逻辑（用临时文件模拟）
- ClipboardWatcher 的过滤函数被调用
- 源码契约：CentralNerve 启动两个 watcher，prompt 注入 working_feed 块
"""
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    WorkingMemoryFeed, ClipboardWatcher, PSHistoryWatcher,
    get_default_working_feed,
)


class TestWorkingMemoryFeedBasic(unittest.TestCase):
    def setUp(self):
        self.feed = WorkingMemoryFeed(max_events=20, ttl_seconds=10.0)

    def test_push_and_recent(self):
        self.assertTrue(self.feed.push('clipboard_copy', {'preview': 'hello', 'length': 5}))
        events = self.feed.recent()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['type'], 'clipboard_copy')
        self.assertEqual(events[0]['payload']['preview'], 'hello')

    def test_push_rejects_empty_type(self):
        self.assertFalse(self.feed.push('', {'k': 'v'}))
        self.assertFalse(self.feed.push(None, {'k': 'v'}))

    def test_filter_by_types(self):
        self.feed.push('clipboard_copy', {'preview': 'a'})
        self.feed.push('terminal_cmd', {'cmd': 'ls'})
        self.feed.push('clipboard_copy', {'preview': 'b'})
        events = self.feed.recent(types={'clipboard_copy'})
        self.assertEqual(len(events), 2)
        for e in events:
            self.assertEqual(e['type'], 'clipboard_copy')

    def test_ttl_expiry(self):
        feed = WorkingMemoryFeed(max_events=10, ttl_seconds=2.0)
        feed.push('clipboard_copy', {'preview': 'a'}, ts=time.time() - 5.0)
        feed.push('clipboard_copy', {'preview': 'b'}, ts=time.time() - 0.5)
        events = feed.recent()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['payload']['preview'], 'b')

    def test_within_seconds_filter(self):
        self.feed.push('clipboard_copy', {'preview': 'old'}, ts=time.time() - 8.0)
        self.feed.push('clipboard_copy', {'preview': 'new'}, ts=time.time() - 1.0)
        events = self.feed.recent(within_seconds=3.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['payload']['preview'], 'new')

    def test_max_events_evicts(self):
        feed = WorkingMemoryFeed(max_events=3, ttl_seconds=100.0)
        for i in range(5):
            feed.push('terminal_cmd', {'cmd': f'cmd{i}'})
        events = feed.recent()
        self.assertEqual(len(events), 3)
        cmds = [e['payload']['cmd'] for e in events]
        # 最早两条被挤掉
        self.assertEqual(cmds, ['cmd2', 'cmd3', 'cmd4'])

    def test_clear(self):
        self.feed.push('clipboard_copy', {'preview': 'a'})
        self.assertEqual(len(self.feed.recent()), 1)
        self.feed.clear()
        self.assertEqual(self.feed.recent(), [])

    def test_default_singleton(self):
        a = get_default_working_feed()
        b = get_default_working_feed()
        self.assertIs(a, b)


class TestWorkingMemoryFeedRender(unittest.TestCase):
    def test_empty_block(self):
        feed = WorkingMemoryFeed()
        self.assertEqual(feed.to_prompt_block(), "")

    def test_clipboard_rendering(self):
        feed = WorkingMemoryFeed()
        feed.push('clipboard_copy', {'preview': 'def foo():\n    return 1', 'length': 24})
        block = feed.to_prompt_block()
        self.assertIn("WORKING MEMORY", block)
        self.assertIn("clipboard_copy", block)
        self.assertIn("def foo()", block)
        # 换行应被替换成空格
        self.assertNotIn('\n    return', block)

    def test_terminal_rendering(self):
        feed = WorkingMemoryFeed()
        feed.push('terminal_cmd', {'cmd': 'pytest tests/'})
        block = feed.to_prompt_block()
        self.assertIn("terminal_cmd", block)
        self.assertIn("pytest tests/", block)

    def test_file_saved_rendering(self):
        feed = WorkingMemoryFeed()
        feed.push('file_saved', {'path': 'd:\\Jarvis\\foo.py', 'ext': 'py'})
        block = feed.to_prompt_block()
        self.assertIn("file_saved", block)
        self.assertIn("foo.py", block)

    def test_window_focus_rendering(self):
        feed = WorkingMemoryFeed()
        feed.push('window_focus', {'title': 'Code – jarvis_nerve.py'})
        block = feed.to_prompt_block()
        self.assertIn("window_focus", block)

    def test_max_chars_cap(self):
        feed = WorkingMemoryFeed()
        for i in range(20):
            feed.push('terminal_cmd', {'cmd': 'x' * 100})
        block = feed.to_prompt_block(max_chars=200)
        self.assertLessEqual(len(block), 200 + 10)  # 略微宽容
        self.assertTrue(block.endswith('…') or '\n' in block)

    def test_top_8_events_only(self):
        feed = WorkingMemoryFeed()
        for i in range(15):
            feed.push('terminal_cmd', {'cmd': f'cmd{i}'})
        block = feed.to_prompt_block(max_chars=2000)
        # 不应该展示所有 15 条
        cmd_count = block.count('terminal_cmd')
        self.assertLessEqual(cmd_count, 8)


class TestPSHistoryWatcher(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.history_path = os.path.join(self.tmpdir, 'history.txt')
        # 初始化带几行历史
        with open(self.history_path, 'w', encoding='utf-8') as f:
            f.write("ls\ncd ..\npytest tests/\n")
        self.feed = WorkingMemoryFeed()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_first_pass_does_not_push(self):
        """首次扫描应只建索引不投递（避免一启动把历史全推一遍）。"""
        watcher = PSHistoryWatcher(self.feed, history_path=self.history_path)
        watcher.POLL_INTERVAL = 0.05
        watcher.start()
        time.sleep(0.2)
        watcher.stop()
        watcher.join(timeout=1.0)
        events = self.feed.recent(types={'terminal_cmd'})
        self.assertEqual(events, [], "首次扫描不应推任何 terminal_cmd 事件")

    def test_new_lines_appended_pushes(self):
        watcher = PSHistoryWatcher(self.feed, history_path=self.history_path)
        watcher.POLL_INTERVAL = 0.05
        watcher.start()
        time.sleep(0.2)  # 让首次扫描跑完

        # 追加新行
        with open(self.history_path, 'a', encoding='utf-8') as f:
            f.write("git status\n")
        # 改 mtime 强制刷新
        os.utime(self.history_path, None)
        time.sleep(0.3)

        watcher.stop()
        watcher.join(timeout=1.0)
        events = self.feed.recent(types={'terminal_cmd'})
        cmds = [e['payload']['cmd'] for e in events]
        self.assertIn('git status', cmds, f"新增行应被推送；实际：{cmds}")
        # 不应该把首次扫描的旧行也推
        for old in ('ls', 'cd ..', 'pytest tests/'):
            self.assertNotIn(old, cmds)

    def test_missing_file_does_not_crash(self):
        watcher = PSHistoryWatcher(self.feed, history_path='/nonexistent/path/history.txt')
        watcher.POLL_INTERVAL = 0.05
        watcher.start()
        time.sleep(0.2)
        watcher.stop()
        watcher.join(timeout=1.0)
        # 没崩 + 没推任何事件
        self.assertEqual(self.feed.recent(), [])


class TestClipboardWatcherSkipFilter(unittest.TestCase):
    """ClipboardWatcher 在 Linux/无 win32clipboard 环境下 run() 会立刻返回（ctypes 调用失败）。
    我们只测 skip_if_match_fn 接口契约。"""

    def test_skip_filter_callable(self):
        feed = WorkingMemoryFeed()
        watcher = ClipboardWatcher(feed, skip_if_match_fn=lambda txt: 'jarvis' in (txt or '').lower())
        self.assertTrue(callable(watcher._skip_if_match_fn))
        # 调用过滤函数本身不该挂
        self.assertTrue(watcher._skip_if_match_fn("Jarvis says hi"))
        self.assertFalse(watcher._skip_if_match_fn("hello world"))

    def test_min_preview_len_constant(self):
        feed = WorkingMemoryFeed()
        watcher = ClipboardWatcher(feed)
        self.assertGreaterEqual(watcher.MIN_PREVIEW_LEN, 1)
        self.assertGreaterEqual(watcher.MAX_PREVIEW_LEN, 100)


class TestSourceContract(unittest.TestCase):
    """jarvis_nerve.py 源码契约：CentralNerve 启动两个 watcher；prompt 注入 working_feed 块。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_central_nerve_creates_working_feed(self):
        self.assertIn('WorkingMemoryFeed(', self.src,
                      "CentralNerve 必须实例化 WorkingMemoryFeed")

    def test_central_nerve_starts_clipboard_watcher(self):
        self.assertRegex(
            self.src,
            r'self\._clipboard_watcher\s*=\s*ClipboardWatcher\(',
            "CentralNerve 必须创建 ClipboardWatcher"
        )
        self.assertRegex(
            self.src,
            r'self\._clipboard_watcher\.start\(\)',
            "ClipboardWatcher 必须 start()"
        )

    def test_central_nerve_starts_ps_history_watcher(self):
        self.assertRegex(
            self.src,
            r'self\._ps_history_watcher\s*=\s*PSHistoryWatcher\(',
            "CentralNerve 必须创建 PSHistoryWatcher"
        )

    def test_clipboard_watcher_filters_jarvis_echo(self):
        # ClipboardWatcher 的 skip_if_match_fn 应当用 is_recent_jarvis_echo 过滤
        # 避免 Jarvis 自己塞剪贴板的内容触发自循环
        m = re.search(
            r"ClipboardWatcher\([^)]*skip_if_match_fn\s*=.*?is_recent_jarvis_echo",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "ClipboardWatcher 应用 is_recent_jarvis_echo 过滤自家回声")

    def test_prompt_full_tier_has_working_feed_block(self):
        self.assertIn('{working_feed_block}', self.src,
                      "full 档 prompt 必须包含 {working_feed_block} 占位")

    def test_prompt_short_chat_tier_has_short_feed(self):
        m = re.search(
            r"if prompt_tier == self\.PROMPT_TIER_SHORT_CHAT.+?_short_feed",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "SHORT_CHAT 档必须注入 _short_feed")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestWorkingMemoryFeedBasic),
        loader.loadTestsFromTestCase(TestWorkingMemoryFeedRender),
        loader.loadTestsFromTestCase(TestPSHistoryWatcher),
        loader.loadTestsFromTestCase(TestClipboardWatcherSkipFilter),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-α/WorkingMemoryFeed tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
