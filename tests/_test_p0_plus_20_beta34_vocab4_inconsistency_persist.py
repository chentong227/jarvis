# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab4 / 2026-05-18] inconsistency_vocab.json 持久化 testcase

Session 0 第 4 项: jarvis_inconsistency_watcher class attrs _SIR_SLEEP_VERBS /
_SIR_BREAK_VERBS / _JARVIS_WRAPPER_MARKERS 迁 memory_pool/inconsistency_vocab.json
+ scripts/inconsistency_vocab_dump.py.

验证:
  - 3 个 category 各自加载 + mtime cache reload
  - 3 个 getter (get_sir_sleep_verbs / get_sir_break_verbs / get_jarvis_wrapper_markers)
  - InconsistencyWatcher class 已没有旧 class attrs (准则 6.5 红线)
  - _is_sir_sleep/break_commitment 仍按主体判定工作 (功能等价)
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
    import jarvis_inconsistency_watcher as iw
    iw._INCONSISTENCY_CACHE = None
    iw._INCONSISTENCY_MTIME = 0.0


class TestVocabFileLoading(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        import jarvis_inconsistency_watcher as iw
        self.iw = iw

    def test_seed_fallback_when_no_json(self):
        with unittest.mock.patch.object(
                self.iw, '_INCONSISTENCY_VOCAB_PATH', '/nonexistent_inc.json'):
            _reset_cache()
            self.assertGreater(len(self.iw.get_sir_sleep_verbs()), 0)
            self.assertGreater(len(self.iw.get_sir_break_verbs()), 0)
            self.assertGreater(len(self.iw.get_jarvis_wrapper_markers()), 0)
            # seed 含核心标志词
            self.assertIn('i shall sleep', self.iw.get_sir_sleep_verbs())
            self.assertIn('i need a break', self.iw.get_sir_break_verbs())
            self.assertIn('监督您', self.iw.get_jarvis_wrapper_markers())

    def test_loads_active_three_categories(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 's1', 'category': 'sleep_commitment',
                 'keywords': ['test_sleep_kw'], 'state': 'active'},
                {'id': 'b1', 'category': 'break_commitment',
                 'keywords': ['test_break_kw'], 'state': 'active'},
                {'id': 'w1', 'category': 'wrapper_exclusion',
                 'keywords': ['test_wrap_kw'], 'state': 'active'},
                {'id': 'r1', 'category': 'sleep_commitment',
                 'keywords': ['shouldnot_review'], 'state': 'review'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.iw, '_INCONSISTENCY_VOCAB_PATH', tmpname):
                _reset_cache()
                self.assertIn('test_sleep_kw', self.iw.get_sir_sleep_verbs())
                self.assertIn('test_break_kw', self.iw.get_sir_break_verbs())
                self.assertIn('test_wrap_kw', self.iw.get_jarvis_wrapper_markers())
                self.assertNotIn('shouldnot_review',
                                  self.iw.get_sir_sleep_verbs())
        finally:
            os.remove(tmpname)

    def test_incomplete_json_falls_back_to_seed(self):
        """如果 json 缺某类 (任一类空) → fallback seed (避免坏状态)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                # 只有 sleep, 没 break/wrapper → 不全 → fallback
                {'id': 's1', 'category': 'sleep_commitment',
                 'keywords': ['test_kw'], 'state': 'active'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.iw, '_INCONSISTENCY_VOCAB_PATH', tmpname):
                _reset_cache()
                # 应 fallback to seed (含 'i shall sleep')
                self.assertIn('i shall sleep', self.iw.get_sir_sleep_verbs())
                self.assertIn('监督您', self.iw.get_jarvis_wrapper_markers())
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 's', 'category': 'sleep_commitment',
                 'keywords': ['oldsleep'], 'state': 'active'},
                {'id': 'b', 'category': 'break_commitment',
                 'keywords': ['oldbreak'], 'state': 'active'},
                {'id': 'w', 'category': 'wrapper_exclusion',
                 'keywords': ['oldwrap'], 'state': 'active'},
            ]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.iw, '_INCONSISTENCY_VOCAB_PATH', tmpname):
                _reset_cache()
                self.assertIn('oldsleep', self.iw.get_sir_sleep_verbs())
                time.sleep(1.1)
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [
                        {'id': 's', 'category': 'sleep_commitment',
                         'keywords': ['newsleep'], 'state': 'active'},
                        {'id': 'b', 'category': 'break_commitment',
                         'keywords': ['newbreak'], 'state': 'active'},
                        {'id': 'w', 'category': 'wrapper_exclusion',
                         'keywords': ['newwrap'], 'state': 'active'},
                    ]}, f)
                self.assertIn('newsleep', self.iw.get_sir_sleep_verbs())
                self.assertNotIn('oldsleep', self.iw.get_sir_sleep_verbs())
        finally:
            os.remove(tmpname)


class TestCommitmentSubjectJudgement(unittest.TestCase):
    """_is_sir_sleep_commitment / _is_sir_break_commitment 主体判定功能等价"""

    def setUp(self):
        _reset_cache()
        import jarvis_inconsistency_watcher as iw
        self.iw = iw

    def _mock_promise(self, description: str):
        class P:
            def __init__(self, d):
                self.description = d
        return P(description)

    def _mock_watcher(self):
        # 不真启动线程, 只造 instance 调 method
        class FakeW:
            pass
        w = FakeW()
        w._is_sir_sleep_commitment = self.iw.InconsistencyWatcher._is_sir_sleep_commitment.__get__(w)
        w._is_sir_break_commitment = self.iw.InconsistencyWatcher._is_sir_break_commitment.__get__(w)
        return w

    def test_sir_self_sleep_promise_hits(self):
        w = self._mock_watcher()
        p = self._mock_promise("I'm going to bed now")
        self.assertTrue(w._is_sir_sleep_commitment(p))

    def test_jarvis_wrapper_excluded(self):
        """'我会监督您...' 是 Jarvis 包装句, 应被 wrapper_markers 排除."""
        w = self._mock_watcher()
        p = self._mock_promise("我会监督您在 13:05 准时休息")
        # 含 '监督您' (wrapper) + '休息' (无 sleep_verb 命中) → 应排除
        self.assertFalse(w._is_sir_sleep_commitment(p))

    def test_sir_break_promise_hits(self):
        w = self._mock_watcher()
        p = self._mock_promise("我先歇会, 等下回来")
        self.assertTrue(w._is_sir_break_commitment(p))


class TestCLIScript(unittest.TestCase):
    def test_cli_exists_and_has_actions(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'inconsistency_vocab_dump.py')
        self.assertTrue(os.path.exists(cli_path))
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only', '--archived',
                          '--category', '--keywords',
                          'sleep_commitment', 'break_commitment',
                          'wrapper_exclusion']:
            self.assertIn(required, src,
                          f'CLI 必须支持/提及 {required}')


class TestNoHardcodedClassAttrs(unittest.TestCase):
    """准则 6.5 红线: InconsistencyWatcher class 不能有 _SIR_*_VERBS / _JARVIS_WRAPPER_MARKERS"""

    def test_class_attrs_removed(self):
        import jarvis_inconsistency_watcher as iw
        for attr in ('_SIR_SLEEP_VERBS', '_SIR_BREAK_VERBS',
                      '_JARVIS_WRAPPER_MARKERS'):
            self.assertFalse(hasattr(iw.InconsistencyWatcher, attr),
                              f'{attr} 必须从 class attribute 删除 (迁 module-level vocab json)')

    def test_module_helpers_exist(self):
        import jarvis_inconsistency_watcher as iw
        self.assertTrue(callable(getattr(iw, 'get_sir_sleep_verbs', None)))
        self.assertTrue(callable(getattr(iw, 'get_sir_break_verbs', None)))
        self.assertTrue(callable(getattr(iw, 'get_jarvis_wrapper_markers', None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
