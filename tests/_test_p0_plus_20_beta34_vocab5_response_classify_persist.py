# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab5 / 2026-05-18] response_classify_vocab.json 持久化 testcase

Session 0 第 5 项: ProactiveCareEngine class attrs _RESPONSE_POSITIVE/NEGATIVE
迁 memory_pool/response_classify_vocab.json + scripts/response_classify_dump.py.
"""
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reset_cache():
    import jarvis_proactive_care as pc
    pc._RESPONSE_CLASSIFY_CACHE = None
    pc._RESPONSE_CLASSIFY_MTIME = 0.0


class TestVocabLoading(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        import jarvis_proactive_care as pc
        self.pc = pc

    def test_seed_fallback_when_no_json(self):
        with unittest.mock.patch.object(
                self.pc, '_RESPONSE_CLASSIFY_VOCAB_PATH', '/nonexistent.json'):
            _reset_cache()
            self.assertIn('好的', self.pc.get_response_positive_vocab())
            self.assertIn('ok', self.pc.get_response_positive_vocab())
            self.assertIn('别催', self.pc.get_response_negative_vocab())
            self.assertIn('stop', self.pc.get_response_negative_vocab())

    def test_loads_two_categories(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'pos1', 'category': 'positive',
                 'keywords': ['test_pos_kw'], 'state': 'active'},
                {'id': 'neg1', 'category': 'negative',
                 'keywords': ['test_neg_kw'], 'state': 'active'},
                {'id': 'r1', 'category': 'positive',
                 'keywords': ['shouldnot_review'], 'state': 'review'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.pc, '_RESPONSE_CLASSIFY_VOCAB_PATH', tmpname):
                _reset_cache()
                pos = self.pc.get_response_positive_vocab()
                neg = self.pc.get_response_negative_vocab()
                self.assertIn('test_pos_kw', pos)
                self.assertIn('test_neg_kw', neg)
                self.assertNotIn('shouldnot_review', pos)
        finally:
            os.remove(tmpname)

    def test_incomplete_falls_back(self):
        """任一类空 → fallback (避免坏状态)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                # 只有 positive, 缺 negative → fallback
                {'id': 'p', 'category': 'positive',
                 'keywords': ['x'], 'state': 'active'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.pc, '_RESPONSE_CLASSIFY_VOCAB_PATH', tmpname):
                _reset_cache()
                self.assertIn('好的', self.pc.get_response_positive_vocab())
                self.assertIn('别催', self.pc.get_response_negative_vocab())
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'p', 'category': 'positive',
                 'keywords': ['oldp'], 'state': 'active'},
                {'id': 'n', 'category': 'negative',
                 'keywords': ['oldn'], 'state': 'active'},
            ]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.pc, '_RESPONSE_CLASSIFY_VOCAB_PATH', tmpname):
                _reset_cache()
                self.assertIn('oldp', self.pc.get_response_positive_vocab())
                time.sleep(1.1)
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [
                        {'id': 'p', 'category': 'positive',
                         'keywords': ['newp'], 'state': 'active'},
                        {'id': 'n', 'category': 'negative',
                         'keywords': ['newn'], 'state': 'active'},
                    ]}, f)
                self.assertIn('newp', self.pc.get_response_positive_vocab())
                self.assertNotIn('oldp', self.pc.get_response_positive_vocab())
        finally:
            os.remove(tmpname)


class TestClassifyResponse(unittest.TestCase):
    """_classify_response 功能等价"""

    def setUp(self):
        _reset_cache()
        import jarvis_proactive_care as pc
        self.pc = pc
        self.engine_cls = pc.ProactiveCareEngine

    def test_positive_chinese(self):
        self.assertEqual(self.engine_cls._classify_response('好的, 我去做'), 'positive')

    def test_positive_english(self):
        self.assertEqual(self.engine_cls._classify_response("ok will do"), 'positive')

    def test_negative_chinese(self):
        self.assertEqual(self.engine_cls._classify_response('别催了, 烦死了'), 'negative')

    def test_negative_english(self):
        self.assertEqual(self.engine_cls._classify_response('no leave it alone'), 'negative')

    def test_neutral(self):
        self.assertEqual(self.engine_cls._classify_response('今天天气不错'), 'neutral')

    def test_negative_priority_over_positive(self):
        """'不会做' 含 '会做' 应判 negative (negative 优先)."""
        # '我不会做' 含 '我不' (neg) + '会做' (pos), 应优先 neg
        self.assertEqual(self.engine_cls._classify_response('我不会做'), 'negative')


class TestCLIScript(unittest.TestCase):
    def test_cli_exists_and_has_actions(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'response_classify_dump.py')
        self.assertTrue(os.path.exists(cli_path))
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only', '--archived',
                          '--category', '--keywords',
                          'positive', 'negative']:
            self.assertIn(required, src)


class TestNoClassAttrs(unittest.TestCase):
    """ProactiveCareEngine 不能有 _RESPONSE_POSITIVE / _RESPONSE_NEGATIVE 类属性"""

    def test_class_attrs_removed(self):
        import jarvis_proactive_care as pc
        for attr in ('_RESPONSE_POSITIVE', '_RESPONSE_NEGATIVE'):
            self.assertFalse(hasattr(pc.ProactiveCareEngine, attr),
                              f'{attr} 必须从 class 删 (迁 module-level)')

    def test_module_helpers_exist(self):
        import jarvis_proactive_care as pc
        self.assertTrue(callable(getattr(pc, 'get_response_positive_vocab', None)))
        self.assertTrue(callable(getattr(pc, 'get_response_negative_vocab', None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
