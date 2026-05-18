# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab6 / 2026-05-18] feedback_vocab.json 持久化 testcase

Session 0 第 6 项: FeedbackTracker._correction_patterns (10 regex × signal_type)
迁 memory_pool/feedback_vocab.json + scripts/feedback_vocab_dump.py.
特殊: entry 是 (compiled regex, signal_type) 不是 keyword. 顺序敏感.
"""
import json
import os
import re
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reset_cache():
    import jarvis_memory_core as mc
    mc._FEEDBACK_PATTERNS_CACHE = None
    mc._FEEDBACK_PATTERNS_MTIME = 0.0


class TestVocabLoading(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        import jarvis_memory_core as mc
        self.mc = mc

    def test_seed_fallback_when_no_json(self):
        with unittest.mock.patch.object(
                self.mc, '_FEEDBACK_VOCAB_PATH', '/nonexistent.json'):
            _reset_cache()
            patterns = self.mc.get_feedback_patterns()
        self.assertEqual(len(patterns), len(self.mc._SEED_FEEDBACK_PATTERNS))
        # 验证第 1 条是 correction
        first_pat, first_sig = patterns[0]
        self.assertEqual(first_sig, 'correction')
        self.assertTrue(first_pat.search('不对你搞错了'))

    def test_loads_active_from_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'p1', 'category': 'positive', 'signal_type': 'positive',
                 'regex': r'\bawesome\b', 'state': 'active'},
                {'id': 'p2', 'category': 'correction', 'signal_type': 'correction',
                 'regex': '搞砸了', 'state': 'active'},
                {'id': 'pr', 'category': 'positive', 'signal_type': 'positive',
                 'regex': 'shouldnot_review', 'state': 'review'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.mc, '_FEEDBACK_VOCAB_PATH', tmpname):
                _reset_cache()
                patterns = self.mc.get_feedback_patterns()
            self.assertEqual(len(patterns), 2)
            sigs = [s for _, s in patterns]
            self.assertIn('positive', sigs)
            self.assertIn('correction', sigs)
            # 顺序保留 (json 内顺序 = 加载顺序)
            self.assertEqual(patterns[0][1], 'positive')
            self.assertEqual(patterns[1][1], 'correction')
        finally:
            os.remove(tmpname)

    def test_bad_regex_skipped(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'good', 'category': 'positive', 'signal_type': 'positive',
                 'regex': r'\bgood\b', 'state': 'active'},
                {'id': 'bad', 'category': 'correction', 'signal_type': 'correction',
                 'regex': '[invalid(regex', 'state': 'active'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.mc, '_FEEDBACK_VOCAB_PATH', tmpname):
                _reset_cache()
                patterns = self.mc.get_feedback_patterns()
            # 只 good 应被加载, bad regex 跳过
            self.assertEqual(len(patterns), 1)
            self.assertEqual(patterns[0][1], 'positive')
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'v1', 'category': 'positive', 'signal_type': 'positive',
                 'regex': r'\boldkw\b', 'state': 'active'},
            ]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.mc, '_FEEDBACK_VOCAB_PATH', tmpname):
                _reset_cache()
                v1 = self.mc.get_feedback_patterns()
                self.assertTrue(v1[0][0].search('saying oldkw'))
                self.assertFalse(v1[0][0].search('saying newkw'))
                time.sleep(1.1)
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [
                        {'id': 'v2', 'category': 'positive', 'signal_type': 'positive',
                         'regex': r'\bnewkw\b', 'state': 'active'},
                    ]}, f)
                v2 = self.mc.get_feedback_patterns()
                self.assertTrue(v2[0][0].search('saying newkw'))
                self.assertFalse(v2[0][0].search('saying oldkw'))
        finally:
            os.remove(tmpname)


class TestAnalyzeInteractionEquivalence(unittest.TestCase):
    """FeedbackTracker.analyze_interaction 用新 helper, 功能等价"""

    def setUp(self):
        _reset_cache()
        import jarvis_memory_core as mc
        self.mc = mc
        self.tracker = mc.FeedbackTracker()

    def test_zh_correction(self):
        sig = self.tracker.analyze_interaction('不对, 你搞错了', 'reply')
        self.assertEqual(sig.signal_type, 'correction')

    def test_en_correction(self):
        sig = self.tracker.analyze_interaction("actually that's wrong", 'reply')
        self.assertEqual(sig.signal_type, 'correction')

    def test_en_positive(self):
        sig = self.tracker.analyze_interaction('thanks, that was perfect', 'reply')
        self.assertEqual(sig.signal_type, 'positive')

    def test_zh_positive(self):
        sig = self.tracker.analyze_interaction('谢谢, 完美', 'reply')
        self.assertEqual(sig.signal_type, 'positive')

    def test_confusion_zh(self):
        sig = self.tracker.analyze_interaction('啥? 没明白', 'reply')
        self.assertEqual(sig.signal_type, 'confusion')

    def test_dismiss_zh(self):
        sig = self.tracker.analyze_interaction('算了, 别管了', 'reply')
        self.assertEqual(sig.signal_type, 'dismiss')

    def test_neutral(self):
        sig = self.tracker.analyze_interaction('今天去外面散步', 'reply')
        self.assertEqual(sig.signal_type, 'neutral')


class TestCLIScript(unittest.TestCase):
    def test_cli_exists_and_has_actions(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'feedback_vocab_dump.py')
        self.assertTrue(os.path.exists(cli_path))
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only', '--archived',
                          '--regex', '--signal-type',
                          'correction', 'confusion', 'positive',
                          'follow_up', 'dismiss']:
            self.assertIn(required, src,
                          f'CLI 必须支持/提及 {required}')


class TestNoInstanceAttrAfterInit(unittest.TestCase):
    """FeedbackTracker.__init__ 不能再创建 self._correction_patterns"""

    def test_no_instance_attr(self):
        import jarvis_memory_core as mc
        ft = mc.FeedbackTracker()
        self.assertFalse(hasattr(ft, '_correction_patterns'),
                          'self._correction_patterns 必须删 (迁 module-level)')

    def test_module_helper_exists(self):
        import jarvis_memory_core as mc
        self.assertTrue(callable(getattr(mc, 'get_feedback_patterns', None)))
        # seed 也要存在
        self.assertTrue(hasattr(mc, '_SEED_FEEDBACK_PATTERNS'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
