"""轴 2.1 单元测试：[OPEN THREADS] prompt 块 —— 老友感 callback 基础

起因：STM 是机械列表，主脑下一轮看不见"上一轮 Jarvis 自己承诺了什么"。
Sir 说"我刚那个怎么样了" → 主脑想不起 5 分钟前说过的"I'll check that"。

修法：扫 STM 抓 Jarvis 发言里的承诺动词（"I'll check" / "我看一下" 等），
渲染成 `=== OPEN THREADS (still owed to Sir) ===` 块。

跑法：
    cd d:\\Jarvis
    python tests/_test_axis2_1_open_threads.py
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import extract_open_threads, render_open_threads_block


class TestExtractOpenThreads(unittest.TestCase):
    def test_empty_stm_returns_empty(self):
        self.assertEqual(extract_open_threads([]), [])

    def test_english_ill_check_detected(self):
        stm = [
            {'time': '14:30', 'user': 'whats up with the build', 'jarvis': "I'll check that for you, Sir."},
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]['lang'], 'en')
        self.assertIn('check', threads[0]['topic_hint'].lower())

    def test_english_let_me_see_detected(self):
        stm = [
            {'time': '14:30', 'user': 'how is X', 'jarvis': "Let me see what we have here, Sir."},
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]['lang'], 'en')

    def test_english_i_shall_detected(self):
        stm = [
            {'time': '14:30', 'user': 'remind me at 6', 'jarvis': "I shall note that down, Sir."},
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(len(threads), 1)

    def test_chinese_wo_kan_yixia_detected(self):
        stm = [
            {'time': '14:30', 'user': '\u8fd9\u4e2a bug \u600e\u4e48\u56de\u4e8b',  # 这个 bug 怎么回事
             'jarvis': '\u8ba9\u6211\u770b\u4e00\u4e0b, \u5148\u751f'},  # 让我看一下,先生
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]['lang'], 'zh')

    def test_chinese_wo_cha_yixia_detected(self):
        stm = [
            {'time': '14:30', 'user': 'X', 'jarvis': '\u6211\u67e5\u4e00\u4e0b\u5c31\u56de\u590d\u60a8'},  # 我查一下就回复您
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]['lang'], 'zh')

    def test_chinese_shao_deng_detected(self):
        stm = [
            {'time': '14:30', 'user': 'X', 'jarvis': '\u7a0d\u7b49, \u5148\u751f\u3002'},  # 稍等, 先生。
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(len(threads), 1)

    def test_no_promise_no_detection(self):
        stm = [
            {'time': '14:30', 'user': 'hi', 'jarvis': 'Good afternoon, Sir.'},
            {'time': '14:31', 'user': 'thanks', 'jarvis': 'My pleasure.'},
        ]
        threads = extract_open_threads(stm)
        self.assertEqual(threads, [], "无承诺词的对话不应被识别")

    def test_max_threads_cap(self):
        stm = [
            {'time': f'14:{i:02d}', 'user': 'X', 'jarvis': f"I'll check item {i}."}
            for i in range(10)
        ]
        threads = extract_open_threads(stm, max_threads=3)
        self.assertEqual(len(threads), 3)

    def test_newest_first(self):
        stm = [
            {'time': '14:00', 'user': 'a', 'jarvis': "I'll check A."},
            {'time': '14:05', 'user': 'b', 'jarvis': "I'll check B."},
            {'time': '14:10', 'user': 'c', 'jarvis': "I'll check C."},
        ]
        threads = extract_open_threads(stm)
        # reversed → 最近的在第一位
        self.assertIn('C', threads[0]['jarvis_said'])
        self.assertIn('A', threads[-1]['jarvis_said'])

    def test_nudge_entries_skipped(self):
        stm = [
            {'time': '14:00', 'user': '__NUDGE__:{"type":"late_night"}',
             'jarvis': "I'll get you to bed soon, Sir."},
            {'time': '14:05', 'user': 'real question', 'jarvis': "I'll check that, Sir."},
        ]
        threads = extract_open_threads(stm)
        # NUDGE 那条应被跳过
        self.assertEqual(len(threads), 1)
        self.assertIn('that', threads[0]['jarvis_said'])

    def test_timestamp_age_filter(self):
        """带 timestamp 字段的 STM 项超过 max_age_seconds 应跳过。"""
        now = time.time()
        stm = [
            {'time': '14:00', 'user': 'old', 'jarvis': "I'll check that.",
             'timestamp': now - 3600},  # 1 小时前
            {'time': '14:05', 'user': 'new', 'jarvis': "Let me see.",
             'timestamp': now - 60},     # 1 分钟前
        ]
        # reversed → 先看 new（≤30min 通过）→ 然后 old（>30min 终止）
        threads = extract_open_threads(stm, now=now, max_age_seconds=1800)
        self.assertEqual(len(threads), 1)
        self.assertIn('Let me see', threads[0]['jarvis_said'])


class TestRenderOpenThreadsBlock(unittest.TestCase):
    def test_empty_threads_returns_empty_string(self):
        self.assertEqual(render_open_threads_block([]), "")

    def test_renders_header_and_callback_rule(self):
        threads = [
            {'jarvis_said': "I'll check that for you, Sir.",
             'topic_hint': "I'll check that for you, Sir.",
             'time_str': '14:30', 'age_seconds': 60, 'lang': 'en'},
        ]
        block = render_open_threads_block(threads)
        self.assertIn('OPEN THREADS', block)
        self.assertIn('still owed to Sir', block)
        self.assertIn('CALLBACK RULE', block)
        self.assertIn('14:30', block)
        self.assertIn('check that', block)

    def test_max_chars_respected(self):
        threads = [
            {'jarvis_said': "I'll check item %d." % i,
             'topic_hint': "I'll check item %d." % i,
             'time_str': '14:%02d' % i, 'age_seconds': i*60, 'lang': 'en'}
            for i in range(20)
        ]
        block = render_open_threads_block(threads, max_chars=200)
        self.assertLessEqual(len(block), 350,
                             "max_chars 限制大致生效（含 header+rule 一些额外字符）")


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_assemble_prompt_computes_open_threads(self):
        # _assemble_prompt 必须计算 open_threads_block
        self.assertIn('extract_open_threads(', self.src)
        self.assertIn('render_open_threads_block(', self.src)
        self.assertIn('open_threads_block = ', self.src)

    def test_full_prompt_injects_open_threads(self):
        # full mode prompt 模板必须含 {open_threads_block}
        m = re.search(
            r'=== WHAT JUST HAPPENED ===\s*\{stm_context\}.*?\{open_threads_block\}',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "full mode prompt 必须在 stm_context 之后注入 open_threads_block")

    def test_short_chat_injects_open_threads(self):
        # SHORT_CHAT 档（return f"""...{stm_context}...{open_threads_block}...""") 也注入
        count = self.src.count('{open_threads_block}')
        # full + SHORT_CHAT + FACTUAL_RECALL 至少 3 处
        self.assertGreaterEqual(count, 3,
            f"open_threads_block 至少在 full/SHORT_CHAT/FACTUAL_RECALL 三处注入，实际：{count}")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestExtractOpenThreads),
        loader.loadTestsFromTestCase(TestRenderOpenThreadsBlock),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] 轴 2.1 Open Threads tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
