# -*- coding: utf-8 -*-
"""[P0+20-β.3.4-vocab7 / 2026-05-18] concern_keywords_vocab.json 持久化 testcase

Session 0 第 7 项 (末项): jarvis_soul_reflector.CONCERN_KEYWORDS Dict[str, List[Tuple]]
迁 memory_pool/concern_keywords_vocab.json + scripts/concern_keywords_dump.py.

特殊:
  - entry 含 concern_id + List[{kw, severity_delta}] (加权 vocab)
  - 同 concern_id 多 entry 合并 keywords_weighted
  - 兼容垫层: CONCERN_KEYWORDS module-level snapshot 仍保留 (commitment_watcher
    + 2 testcase 用 `from jarvis_soul_reflector import CONCERN_KEYWORDS`)
  - production hot path (_scan_text + infer_concern_link) 改用 get_concern_keywords()
    享 mtime cache reload
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
    import jarvis_soul_reflector as sr
    sr._CONCERN_KEYWORDS_CACHE = None
    sr._CONCERN_KEYWORDS_MTIME = 0.0


class TestVocabLoading(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        import jarvis_soul_reflector as sr
        self.sr = sr

    def test_seed_fallback_when_no_json(self):
        with unittest.mock.patch.object(
                self.sr, '_CONCERN_KEYWORDS_VOCAB_PATH', '/nonexistent.json'):
            _reset_cache()
            kws = self.sr.get_concern_keywords()
        # fallback 应含全部 6 个 concern
        for cid in ('sir_sleep_streak', 'sir_pomodoro_compliance',
                    'sir_cursor_payment', 'sir_hydration_habit',
                    'unfinished_jiazhao_ke1', 'jarvis_keyrouter_health'):
            self.assertIn(cid, kws, f'fallback 缺 {cid}')
            self.assertGreater(len(kws[cid]), 0)

    def test_loads_active_from_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'a1', 'concern_id': 'test_concern_a',
                 'category': 'test',
                 'keywords_weighted': [
                     {'kw': 'alpha', 'severity_delta': 0.05},
                     {'kw': 'beta', 'severity_delta': 0.07},
                 ],
                 'state': 'active'},
                {'id': 'r1', 'concern_id': 'test_concern_r',
                 'category': 'test',
                 'keywords_weighted': [{'kw': 'shouldnot', 'severity_delta': 0.05}],
                 'state': 'review'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.sr, '_CONCERN_KEYWORDS_VOCAB_PATH', tmpname):
                _reset_cache()
                kws = self.sr.get_concern_keywords()
            self.assertIn('test_concern_a', kws)
            self.assertNotIn('test_concern_r', kws)
            # tuple shape (kw, delta) 保留
            self.assertEqual(kws['test_concern_a'][0], ('alpha', 0.05))
            self.assertEqual(kws['test_concern_a'][1], ('beta', 0.07))
        finally:
            os.remove(tmpname)

    def test_same_concern_id_merges_multi_entries(self):
        """同 concern_id 多 active entry 应合并 keywords_weighted."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'a1', 'concern_id': 'merged_test',
                 'category': 'x',
                 'keywords_weighted': [{'kw': 'kw_a', 'severity_delta': 0.05}],
                 'state': 'active'},
                {'id': 'a2', 'concern_id': 'merged_test',
                 'category': 'x',
                 'keywords_weighted': [{'kw': 'kw_b', 'severity_delta': 0.10}],
                 'state': 'active'},
            ]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.sr, '_CONCERN_KEYWORDS_VOCAB_PATH', tmpname):
                _reset_cache()
                kws = self.sr.get_concern_keywords()
            # 2 entry 合并
            self.assertEqual(len(kws['merged_test']), 2)
            kw_names = {kw for kw, _ in kws['merged_test']}
            self.assertEqual(kw_names, {'kw_a', 'kw_b'})
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [
                {'id': 'v1', 'concern_id': 'mt_test', 'category': 'x',
                 'keywords_weighted': [{'kw': 'oldkw', 'severity_delta': 0.05}],
                 'state': 'active'},
            ]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.sr, '_CONCERN_KEYWORDS_VOCAB_PATH', tmpname):
                _reset_cache()
                v1 = self.sr.get_concern_keywords()
                self.assertEqual(v1['mt_test'][0][0], 'oldkw')
                time.sleep(1.1)
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [
                        {'id': 'v2', 'concern_id': 'mt_test', 'category': 'x',
                         'keywords_weighted': [{'kw': 'newkw', 'severity_delta': 0.10}],
                         'state': 'active'},
                    ]}, f)
                v2 = self.sr.get_concern_keywords()
                self.assertEqual(v2['mt_test'][0][0], 'newkw')
                self.assertEqual(v2['mt_test'][0][1], 0.10)
        finally:
            os.remove(tmpname)

    def test_corrupt_json_falls_back_to_seed(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            f.write('not valid json {{{')
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.sr, '_CONCERN_KEYWORDS_VOCAB_PATH', tmpname):
                _reset_cache()
                kws = self.sr.get_concern_keywords()
            # fallback to seed
            self.assertIn('sir_sleep_streak', kws)
        finally:
            os.remove(tmpname)


class TestScanTextEquivalence(unittest.TestCase):
    """ConcernsReflector._scan_text 功能等价 — 用 production vocab (default json)"""

    def setUp(self):
        _reset_cache()
        import jarvis_soul_reflector as sr
        self.sr = sr

    def test_cursor_payment_hit(self):
        refl = self.sr.ConcernsReflector(None)
        hits = refl._scan_text('cursor 订阅 续费')
        self.assertIn('sir_cursor_payment', hits)

    def test_sleep_hit(self):
        refl = self.sr.ConcernsReflector(None)
        hits = refl._scan_text('我去睡了, 累了')
        self.assertIn('sir_sleep_streak', hits)

    def test_multi_concern_hits(self):
        """'熬夜赶 cursor' 同时命中 sleep + cursor (兼容 β.3.3 老 test)."""
        refl = self.sr.ConcernsReflector(None)
        hits = refl._scan_text('熬夜赶 cursor')
        self.assertIn('sir_sleep_streak', hits)
        self.assertIn('sir_cursor_payment', hits)

    def test_severity_cap_per_turn(self):
        """单 concern 单轮 severity_delta cap 0.15."""
        refl = self.sr.ConcernsReflector(None)
        # 喝水 vocab 多个 kw, 应 cap
        hits = refl._scan_text('喝水 喝点水 多喝水 补水 hydration drink water')
        self.assertLessEqual(hits.get('sir_hydration_habit', 0), 0.15 + 1e-9)


class TestInferConcernLink(unittest.TestCase):
    """commitment_watcher.infer_concern_link 用 get_concern_keywords()"""

    def setUp(self):
        _reset_cache()

    def test_sleep_promise_links_to_sleep_streak(self):
        from jarvis_commitment_watcher import infer_concern_link
        self.assertEqual(infer_concern_link('我去睡了'), 'sir_sleep_streak')

    def test_cursor_promise_links_to_payment(self):
        from jarvis_commitment_watcher import infer_concern_link
        self.assertEqual(infer_concern_link('cursor 订阅 续费'),
                          'sir_cursor_payment')

    def test_unrelated_returns_none(self):
        from jarvis_commitment_watcher import infer_concern_link
        self.assertIsNone(infer_concern_link('今天天气真好'))


class TestBackwardCompat(unittest.TestCase):
    """CONCERN_KEYWORDS 兼容垫层 — 老代码不破"""

    def test_concern_keywords_snapshot_exists(self):
        """CONCERN_KEYWORDS module-level dict 仍可 import (兼容老代码)."""
        from jarvis_soul_reflector import CONCERN_KEYWORDS
        self.assertIsInstance(CONCERN_KEYWORDS, dict)
        for cid in ('sir_sleep_streak', 'sir_cursor_payment'):
            self.assertIn(cid, CONCERN_KEYWORDS)

    def test_snapshot_entries_have_tuple_shape(self):
        """老代码迭代 (kw, delta) tuple 应仍 work."""
        from jarvis_soul_reflector import CONCERN_KEYWORDS
        for cid, kw_list in CONCERN_KEYWORDS.items():
            for entry in kw_list:
                self.assertEqual(len(entry), 2)
                kw, delta = entry
                self.assertIsInstance(kw, str)
                self.assertIsInstance(delta, (int, float))


class TestCLIScript(unittest.TestCase):
    def test_cli_exists_and_has_actions(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'concern_keywords_dump.py')
        self.assertTrue(os.path.exists(cli_path))
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only', '--archived',
                          '--concern-id', '--kws-weighted',
                          'keywords_weighted', 'severity_delta']:
            self.assertIn(required, src,
                          f'CLI 必须支持/提及 {required}')


class TestNoStaticDictHardcoded(unittest.TestCase):
    """准则 6.5 红线: _SEED_CONCERN_KEYWORDS 仅 fallback, 真 vocab 在 json"""

    def test_seed_and_helper_exist(self):
        import jarvis_soul_reflector as sr
        self.assertTrue(hasattr(sr, '_SEED_CONCERN_KEYWORDS'))
        self.assertTrue(callable(getattr(sr, 'get_concern_keywords', None)))
        # CONCERN_KEYWORDS 兼容垫层仍在 (老代码用)
        self.assertTrue(hasattr(sr, 'CONCERN_KEYWORDS'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
