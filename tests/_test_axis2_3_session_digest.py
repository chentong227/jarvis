"""轴 2.3 单元测试：SessionDigest —— 读 DailyChronicle 已生成的昨日叙事

[Sir-2026-05-15] 之前架构：StatusLedgerSentinel._run_daily_summary 已经在
写 daily_{date}.json（含 narrative / notable_moment / productivity_assessment 等），
但 prompt 从来没用上 → Sir 早上开机贾维斯接不上"昨晚我们在干嘛"。

修法：SessionDigest 读 daily_{yesterday}.json → 合成短摘要 → prompt 顶部
`=== YESTERDAY ===` 块注入三档。零额外 LLM 调用。

跑法：
    cd d:\\Jarvis
    python tests/_test_axis2_3_session_digest.py
"""
import os
import re
import sys
import json
import time
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import SessionDigest, render_yesterday_block


class TestSessionDigestRead(unittest.TestCase):
    """读取 daily_{date}.json 的核心逻辑。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.daily_dir = os.path.join(self.tmpdir, 'daily')
        os.makedirs(self.daily_dir)
        self.profile_path = os.path.join(self.tmpdir, 'sir_profile.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_daily(self, date_str: str, data: dict):
        with open(os.path.join(self.daily_dir, f'daily_{date_str}.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

    def test_empty_dir_returns_empty(self):
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        self.assertEqual(sd.get_yesterday_digest(), '')

    def test_yesterday_with_narrative(self):
        yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
        self._write_daily(yesterday, {
            'date': yesterday,
            'narrative': 'Sir spent the day deep in JARVIS development, debugging the wake-word pipeline.',
            'dominant_activity': 'coding',
            'notable_moment': 'Fixed the GBK emoji encoding bug.',
            'tags': ['coding', 'debugging'],
            'productivity_assessment': 'highly productive',
        })
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        result = sd.get_yesterday_digest()
        self.assertIn('JARVIS', result)
        self.assertIn('GBK emoji', result)
        self.assertIn('highly productive', result)

    def test_yesterday_only_narrative(self):
        yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
        self._write_daily(yesterday, {
            'narrative': 'Just a quiet day, Sir watched racing streams.',
        })
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        result = sd.get_yesterday_digest()
        self.assertIn('racing streams', result)

    def test_no_yesterday_file_returns_empty(self):
        """有今天但没昨天 → 空。"""
        today = time.strftime('%Y-%m-%d')
        self._write_daily(today, {'narrative': 'Today.'})
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        # get_yesterday_digest 找的是 yesterday，今天的不算
        result = sd.get_yesterday_digest()
        self.assertEqual(result, '')

    def test_max_chars_truncation(self):
        yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
        self._write_daily(yesterday, {
            'narrative': 'A' * 500,
        })
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        result = sd.get_yesterday_digest(max_chars=100)
        self.assertLessEqual(len(result), 100)
        self.assertTrue(result.endswith('...'))

    def test_get_digest_for_specific_date(self):
        """读指定日期，便于 Sir 问"前天"那种场景。"""
        date = '2025-12-25'
        self._write_daily(date, {
            'narrative': 'Christmas Day Sir worked on holiday coding.',
            'notable_moment': 'Implemented a Christmas easter egg.',
        })
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        result = sd.get_digest_for_date(date)
        self.assertIn('Christmas Day', result)
        self.assertIn('easter egg', result)

    def test_dedup_notable_in_narrative(self):
        """notable_moment 如果已经在 narrative 里，不重复拼接。"""
        yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
        self._write_daily(yesterday, {
            'narrative': 'Sir fixed the GBK emoji encoding bug after hours of digging.',
            'notable_moment': 'fixed the GBK emoji encoding bug',  # 是 narrative 子串
        })
        sd = SessionDigest(daily_dir=self.daily_dir, sir_profile_path=self.profile_path)
        result = sd.get_yesterday_digest()
        # narrative 应该在
        self.assertIn('hours of digging', result)
        # 不应该有两次 "GBK emoji"
        self.assertEqual(result.lower().count('gbk emoji'), 1)


class TestRenderYesterdayBlock(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(render_yesterday_block(''), '')

    def test_renders_header_and_rule(self):
        digest = "Sir worked on JARVIS yesterday, fixing the bug pipeline."
        block = render_yesterday_block(digest)
        self.assertIn('=== YESTERDAY ===', block)
        self.assertIn(digest, block)
        self.assertIn('YESTERDAY RULE', block)
        self.assertIn('Do not bring it up unprompted', block)

    def test_max_chars_respected(self):
        digest = 'A' * 600
        block = render_yesterday_block(digest, max_chars=200)
        # body 被截到 200，header + rule 是额外字符
        self.assertLessEqual(len(block), 400)


class TestPromptInjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19-8 / 2026-05-16] CentralNerve 已搬到 jarvis_central_nerve.py
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_session_digest_initialized(self):
        self.assertIn('SessionDigest(', self.src,
                      "CentralNerve 必须实例化 SessionDigest")
        self.assertIn('self.session_digest', self.src)

    def test_yesterday_block_computed(self):
        self.assertIn('render_yesterday_block(', self.src)
        self.assertIn('yesterday_block = ', self.src)

    def test_yesterday_block_in_three_tiers(self):
        count = self.src.count('{yesterday_block}')
        self.assertGreaterEqual(count, 3,
            f"yesterday_block 至少要在 full / SHORT_CHAT / FACTUAL_RECALL 三处注入，实际：{count}")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestSessionDigestRead),
        loader.loadTestsFromTestCase(TestRenderYesterdayBlock),
        loader.loadTestsFromTestCase(TestPromptInjection),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] 轴 2.3 SessionDigest tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
