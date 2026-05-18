# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab3 / 2026-05-18] memory_correction_vocab.json 持久化 testcase

Session 0 第 3 项: jarvis_directives._MEMORY_CORRECTION_PATTERNS_ZH/EN 迁
memory_pool/memory_correction_vocab.json + scripts/memory_correction_dump.py.

验证:
  - vocab 持久化 + mtime cache reload
  - get_memory_correction_patterns() 动态加载
  - _trigger_memory_update_honesty 用 get_*() 不再读硬编码 tuple
  - 旧硬编码 _MEMORY_CORRECTION_PATTERNS_ZH/EN 名字必须删 (准则 6.5 红线)
"""
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVocabFileLoading(unittest.TestCase):
    def setUp(self):
        import jarvis_directives as jd
        jd._MEMORY_CORRECTION_CACHE = None
        jd._MEMORY_CORRECTION_MTIME = 0.0
        self.jd = jd

    def test_seed_fallback_when_no_json(self):
        with unittest.mock.patch.object(
                self.jd, '_MEMORY_CORRECTION_VOCAB_PATH', '/nonexistent.json'):
            self.jd._MEMORY_CORRECTION_CACHE = None
            patterns = self.jd.get_memory_correction_patterns()
        self.assertGreater(len(patterns), 0)
        self.assertIn('其实', patterns)
        self.assertIn('actually', patterns)

    def test_loads_active_patterns_from_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'test_a', 'category': 'correction',
                 'keywords': ['xtest_active_kw'], 'state': 'active'},
                {'id': 'test_r', 'category': 'correction',
                 'keywords': ['shouldnot_review'], 'state': 'review'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_MEMORY_CORRECTION_VOCAB_PATH', tmpname):
                self.jd._MEMORY_CORRECTION_CACHE = None
                self.jd._MEMORY_CORRECTION_MTIME = 0.0
                patterns = self.jd.get_memory_correction_patterns()
            self.assertIn('xtest_active_kw', patterns)
            self.assertNotIn('shouldnot_review', patterns)
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [{'id': 'v1', 'category': 'c',
                                       'keywords': ['oldkw_x'],
                                       'state': 'active'}]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_MEMORY_CORRECTION_VOCAB_PATH', tmpname):
                self.jd._MEMORY_CORRECTION_CACHE = None
                self.jd._MEMORY_CORRECTION_MTIME = 0.0
                v1 = self.jd.get_memory_correction_patterns()
                self.assertIn('oldkw_x', v1)
                time.sleep(1.1)
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [{'id': 'v2', 'category': 'c',
                                              'keywords': ['newkw_y'],
                                              'state': 'active'}]}, f)
                v2 = self.jd.get_memory_correction_patterns()
                self.assertIn('newkw_y', v2)
                self.assertNotIn('oldkw_x', v2)
        finally:
            os.remove(tmpname)


class TestTriggerUsesDynamicVocab(unittest.TestCase):
    def setUp(self):
        import jarvis_directives as jd
        jd._MEMORY_CORRECTION_CACHE = None
        jd._MEMORY_CORRECTION_MTIME = 0.0
        self.jd = jd

    def test_real_vocab_drives_trigger(self):
        self.jd._MEMORY_CORRECTION_CACHE = None
        self.jd._MEMORY_CORRECTION_MTIME = 0.0
        ctx_zh = self.jd.DirectiveContext(user_input='你搞错了, 不是那个意思')
        ctx_en = self.jd.DirectiveContext(user_input='actually let me clarify something')
        ctx_miss = self.jd.DirectiveContext(user_input='今天我打算去跑步')
        self.assertTrue(self.jd._trigger_memory_update_honesty(ctx_zh))
        self.assertTrue(self.jd._trigger_memory_update_honesty(ctx_en))
        self.assertFalse(self.jd._trigger_memory_update_honesty(ctx_miss))

    def test_sir_added_keyword_takes_effect(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [{
                'id': 'sir_custom',
                'category': 'correction',
                'keywords': ['一个绝不会自然出现关键词zzz'],
                'state': 'active',
            }]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_MEMORY_CORRECTION_VOCAB_PATH', tmpname):
                self.jd._MEMORY_CORRECTION_CACHE = None
                self.jd._MEMORY_CORRECTION_MTIME = 0.0
                ctx_hit = self.jd.DirectiveContext(
                    user_input='不对, 一个绝不会自然出现关键词zzz')
                self.assertTrue(self.jd._trigger_memory_update_honesty(ctx_hit))
        finally:
            os.remove(tmpname)


class TestCLIScript(unittest.TestCase):
    def test_cli_exists_and_has_actions(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'memory_correction_dump.py')
        self.assertTrue(os.path.exists(cli_path))
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only',
                          '--category', '--keywords']:
            self.assertIn(required, src)


class TestNoHardcodedTupleInPy(unittest.TestCase):
    def test_old_hardcoded_names_renamed(self):
        import jarvis_directives as jd
        self.assertFalse(hasattr(jd, '_MEMORY_CORRECTION_PATTERNS_ZH'),
                         '旧硬编码 _MEMORY_CORRECTION_PATTERNS_ZH 必须删')
        self.assertFalse(hasattr(jd, '_MEMORY_CORRECTION_PATTERNS_EN'),
                         '旧硬编码 _MEMORY_CORRECTION_PATTERNS_EN 必须删')
        self.assertTrue(hasattr(jd, '_SEED_MEMORY_CORRECTION_PATTERNS'))
        self.assertTrue(callable(getattr(jd, 'get_memory_correction_patterns', None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
