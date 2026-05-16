"""R7-β4 单元测试：AntiCommonPhraseTracker + VerbosityPreferenceTracker

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta4_anti_phrase_verbosity.py
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    AntiCommonPhraseTracker, VerbosityPreferenceTracker,
    get_default_phrase_tracker, get_default_verbosity_tracker,
)


class TestPhraseExtraction(unittest.TestCase):
    def setUp(self):
        self.t = AntiCommonPhraseTracker()

    def test_extracts_en_bigrams(self):
        phrases = self.t._extract_phrases("As you wish, Sir, I shall.")
        # 2-gram，全 stop-word 的不算
        # 'as you'（you 不在 stop）/ 'you wish' / 'shall i' (无 'i shall' 因为 i 在 stop)
        # 实际：'as you' (as in stop / you in stop → 都在则跳)；这条已被过滤
        # 'you wish' （you in stop, wish 不在）保留
        self.assertIn('you wish', phrases)

    def test_extracts_zh_bigrams(self):
        phrases = self.t._extract_phrases("作为您的管家，我会的。")
        # '作为'/'为您'/'您的'/'的管'/'管家'... 等
        self.assertIn('管家', phrases)
        self.assertIn('作为', phrases)

    def test_does_not_cross_punctuation_zh(self):
        phrases = self.t._extract_phrases("先生。好的。")
        # 不该出现 "生好" 这种跨标点 bigram
        self.assertNotIn('生好', phrases)


class TestPhraseTrackerDensity(unittest.TestCase):
    def setUp(self):
        self.t = AntiCommonPhraseTracker(window_days=7)

    def test_low_density_not_returned(self):
        # 单日 1 次，不到 min_days=4，不该出现
        self.t.record_reply("hello world", day_key='2026-05-01')
        self.assertEqual(self.t.get_high_density_phrases(min_days=4), [])

    def test_high_density_returned(self):
        # 5 天都说同一句 → 该 2-gram 出现 5 天 → high density
        for day in ('2026-05-01', '2026-05-02', '2026-05-03',
                    '2026-05-04', '2026-05-05'):
            self.t.record_reply("As you wish wish Sir", day_key=day)
        phrases = self.t.get_high_density_phrases(min_days=4)
        # "wish wish" 应该出现（每天 1 次 × 5 天）
        self.assertTrue(any('wish' in p for p in phrases))

    def test_eviction_after_window(self):
        # 创建超过 window_days 的旧桶
        old_day = '2026-04-01'
        self.t.record_reply("ancient phrase example", day_key=old_day)
        # 用今天的 day_key 触发 evict
        self.t.record_reply("fresh phrase", day_key='2026-05-10')
        # 7 天窗：2026-04-01 应被 evict
        snap = self.t.snapshot()
        self.assertNotIn(old_day, snap)

    def test_to_prompt_block_empty_when_low(self):
        self.t.record_reply("hello world")
        self.assertEqual(self.t.to_prompt_block(), "")

    def test_to_prompt_block_renders_when_high(self):
        for day in ('2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04'):
            self.t.record_reply("As you wish wish wish Sir", day_key=day)
        block = self.t.to_prompt_block(min_days=4, top_k=3)
        self.assertIn('AVOID PHRASES', block)


class TestVerbosityTracker(unittest.TestCase):
    def setUp(self):
        self.t = VerbosityPreferenceTracker()

    def test_default_cap(self):
        self.assertEqual(self.t.cap_sentences, 1)
        self.assertEqual(self.t.to_prompt_block(), "")

    def test_one_more_request_does_not_change(self):
        self.t.observe("can you explain more?")
        self.assertEqual(self.t.cap_sentences, 1)

    def test_two_more_requests_raises(self):
        self.t.observe("can you explain more?")
        self.t.observe("说详细一点")
        self.assertEqual(self.t.cap_sentences, 2)

    def test_two_less_requests_lowers_back(self):
        # 先提到 2
        self.t.observe("explain more")
        self.t.observe("more detail")
        self.assertEqual(self.t.cap_sentences, 2)
        # 再连续两次"短一点"
        self.t.observe("shorter")
        self.t.observe("简短")
        self.assertEqual(self.t.cap_sentences, 1)

    def test_cap_clamped_to_max(self):
        for _ in range(20):
            self.t.observe("说详细一点")
        self.assertLessEqual(self.t.cap_sentences, self.t.MAX_CAP_SENTENCES)

    def test_cap_clamped_to_min(self):
        for _ in range(20):
            self.t.observe("短一点")
        self.assertGreaterEqual(self.t.cap_sentences, self.t.MIN_CAP_SENTENCES)

    def test_neutral_input_does_not_change_cap(self):
        cap_before = self.t.cap_sentences
        for _ in range(10):
            self.t.observe("打开 D 盘")  # 中性请求
        self.assertEqual(self.t.cap_sentences, cap_before)

    def test_to_prompt_block_when_higher(self):
        self.t.observe("详细一点")
        self.t.observe("再详细一些")
        block = self.t.to_prompt_block()
        self.assertIn('VERBOSITY DIRECTIVE', block)
        self.assertIn('2 sentences', block)

    def test_reset(self):
        self.t.observe("详细一点")
        self.t.observe("再详细一些")
        self.t.reset()
        self.assertEqual(self.t.cap_sentences, 1)


class TestSingletons(unittest.TestCase):
    def test_phrase_tracker_singleton(self):
        a = get_default_phrase_tracker()
        b = get_default_phrase_tracker()
        self.assertIs(a, b)

    def test_verbosity_tracker_singleton(self):
        a = get_default_verbosity_tracker()
        b = get_default_verbosity_tracker()
        self.assertIs(a, b)


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_central_nerve_instantiates_trackers(self):
        self.assertIn('AntiCommonPhraseTracker(window_days=7)', self.src)
        self.assertIn('VerbosityPreferenceTracker()', self.src)

    def test_prompt_has_avoid_phrases_block(self):
        self.assertIn('{avoid_phrases_block}', self.src)

    def test_prompt_has_verbosity_block(self):
        self.assertIn('{verbosity_block}', self.src)

    def test_verbosity_tracker_observes_cmd(self):
        # 应当在 _classify_prompt_tier 旁边调 verbosity_tracker.observe(cmd)
        self.assertRegex(
            self.src,
            r'vt\.observe\(cmd\)',
            "JarvisWorker.run 必须 verbosity_tracker.observe(cmd)"
        )

    def test_phrase_tracker_records_reply(self):
        # phrase_tracker.record_reply(final_clean_reply) 应当被调
        self.assertRegex(
            self.src,
            r'pt\.record_reply\(final_clean_reply\)',
            "JarvisWorker 必须在 STM append 后 phrase_tracker.record_reply"
        )
        # 至少 3 处（三个 STM append 路径都要 record）
        cnt = self.src.count('pt.record_reply(final_clean_reply)')
        self.assertGreaterEqual(cnt, 3,
                                f"应至少 3 处 record_reply（三条 STM append 路径），实际：{cnt}")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestPhraseExtraction),
        loader.loadTestsFromTestCase(TestPhraseTrackerDensity),
        loader.loadTestsFromTestCase(TestVerbosityTracker),
        loader.loadTestsFromTestCase(TestSingletons),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-β4/AntiPhrase + Verbosity tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
