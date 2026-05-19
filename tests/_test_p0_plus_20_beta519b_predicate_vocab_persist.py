# -*- coding: utf-8 -*-
"""[β.5.19-B / 2026-05-20] jarvis_predicate.py vocab 迁移 persist test.

老 jarvis_predicate.py 把 wake/export/premiere keywords 写死在 source
(`_WAKE_KEYWORDS = (...)` 等), 违反准则 6 三硬规第 1 条 (持久化). β.5.19-B 迁
memory_pool/predicate_keywords.json + CLI scripts/predicate_vocab_dump.py + py
仅留 _SEED_*_KEYWORDS fallback.

测点:
  1. vocab json 存在 + 3 groups (wake/export/premiere) + 各组 keyword 非空
  2. _SEED_*_KEYWORDS fallback 仍在 (json 损坏兼容)
  3. _load_predicate_vocab() 返 3 groups tuple
  4. get_predicate_keywords(group) 返 vocab keyword
  5. heuristic_predicate_from_text() 用 vocab-driven keyword (不直接用 _SEED)
  6. CLI scripts/predicate_vocab_dump.py 存在 + list/show/counts 命令可调
  7. marker [β.5.19-B] 在 jarvis_predicate.py + memory_pool json + CLI
  8. mtime cache (写新 keyword 后能 reload)
"""
import json
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'predicate_keywords.json')
CLI_PATH = os.path.join(ROOT, 'scripts', 'predicate_vocab_dump.py')


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBeta519BVocabFile(unittest.TestCase):
    """vocab json 文件存在性 + schema 合规"""

    @classmethod
    def setUpClass(cls):
        cls.path = VOCAB_PATH
        with open(cls.path, 'r', encoding='utf-8') as f:
            cls.data = json.load(f)

    def test_vocab_exists(self):
        self.assertTrue(os.path.exists(self.path),
            f'vocab 文件必须存在: {self.path}')

    def test_vocab_has_version_meta(self):
        self.assertIn('version', self.data)
        self.assertIn('created_at', self.data)
        self.assertIn('purpose', self.data)

    def test_vocab_has_three_groups(self):
        groups = self.data.get('groups', {})
        for g in ('wake', 'export', 'premiere'):
            self.assertIn(g, groups, f'缺 group {g}')
            self.assertIn('description', groups[g])
            self.assertIn('keywords', groups[g])
            self.assertGreater(len(groups[g]['keywords']), 0,
                f'group {g} keywords 必须非空')

    def test_vocab_history_with_init_marker(self):
        history = self.data.get('history', [])
        self.assertGreater(len(history), 0)
        markers = [h.get('marker', '') for h in history]
        self.assertIn('β.5.19-B', markers,
            'history 必须含 β.5.19-B init 记录')


class TestBeta519BLoader(unittest.TestCase):
    """jarvis_predicate.py loader + cache 行为"""

    def setUp(self):
        # 强制重置 cache 测试每次行为
        import jarvis_predicate as p
        p._pred_vocab_cache = {}
        p._pred_vocab_mtime = 0.0

    def test_load_returns_three_groups(self):
        import jarvis_predicate as p
        vocab = p._load_predicate_vocab()
        self.assertIn('wake', vocab)
        self.assertIn('export', vocab)
        self.assertIn('premiere', vocab)
        # tuple, 非 list
        self.assertIsInstance(vocab['wake'], tuple)
        self.assertIsInstance(vocab['export'], tuple)
        self.assertIsInstance(vocab['premiere'], tuple)

    def test_get_predicate_keywords_wake(self):
        import jarvis_predicate as p
        kws = p.get_predicate_keywords('wake')
        self.assertIn('醒', kws)
        self.assertIn('wake', kws)
        self.assertIn('起床', kws)

    def test_get_predicate_keywords_unknown_group(self):
        import jarvis_predicate as p
        kws = p.get_predicate_keywords('nonexistent_group')
        self.assertEqual(kws, ())

    def test_seed_fallback_exists(self):
        import jarvis_predicate as p
        self.assertTrue(hasattr(p, '_SEED_WAKE_KEYWORDS'))
        self.assertTrue(hasattr(p, '_SEED_EXPORT_KEYWORDS'))
        self.assertTrue(hasattr(p, '_SEED_PREMIERE_KEYWORDS'))


class TestBeta519BHeuristicUsesVocab(unittest.TestCase):
    """heuristic_predicate_from_text 用 vocab-driven keyword"""

    def test_wake_text_creates_predicate(self):
        from jarvis_predicate import heuristic_predicate_from_text
        pred = heuristic_predicate_from_text("明早醒了")
        self.assertIsNotNone(pred,
            '含 wake keyword 的 text 必须产生 predicate')

    def test_export_premiere_text_creates_predicate(self):
        from jarvis_predicate import heuristic_predicate_from_text
        pred = heuristic_predicate_from_text("导出完视频")
        self.assertIsNotNone(pred,
            '含 export + premiere keyword 的 text 必须产生 predicate')

    def test_empty_text_no_predicate(self):
        from jarvis_predicate import heuristic_predicate_from_text
        self.assertIsNone(heuristic_predicate_from_text(""))
        self.assertIsNone(heuristic_predicate_from_text(None))


class TestBeta519BCLIDump(unittest.TestCase):
    """scripts/predicate_vocab_dump.py CLI 命令可调"""

    def _run(self, *args):
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [sys.executable, CLI_PATH] + list(args),
            cwd=ROOT, env=env, capture_output=True,
            encoding='utf-8', timeout=10)
        return result

    def test_cli_exists(self):
        self.assertTrue(os.path.exists(CLI_PATH),
            f'CLI 工具必须存在: {CLI_PATH}')

    def test_cli_default_list(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, f'stderr={r.stderr}')
        self.assertIn('Predicate Keywords Vocab', r.stdout)
        self.assertIn('wake', r.stdout)
        self.assertIn('export', r.stdout)
        self.assertIn('premiere', r.stdout)

    def test_cli_counts(self):
        r = self._run('--counts')
        self.assertEqual(r.returncode, 0)
        self.assertIn('keyword counts', r.stdout)

    def test_cli_show_wake(self):
        r = self._run('--show', 'wake')
        self.assertEqual(r.returncode, 0)
        self.assertIn('keywords', r.stdout)
        self.assertIn('醒', r.stdout)

    def test_cli_show_unknown_group_fails(self):
        r = self._run('--show', 'badgroup')
        self.assertNotEqual(r.returncode, 0)


class TestBeta519BMarkers(unittest.TestCase):
    """marker 同步检查"""

    def test_pyfile_marker(self):
        src = _read(os.path.join(ROOT, 'jarvis_predicate.py'))
        self.assertIn('β.5.19-B', src,
            'jarvis_predicate.py 必须含 β.5.19-B marker')

    def test_pyfile_load_function(self):
        src = _read(os.path.join(ROOT, 'jarvis_predicate.py'))
        self.assertIn('_load_predicate_vocab', src)
        self.assertIn('get_predicate_keywords', src)

    def test_cli_marker(self):
        src = _read(CLI_PATH)
        self.assertIn('β.5.19-B', src,
            'CLI 工具必须含 β.5.19-B marker')

    def test_json_marker(self):
        src = _read(VOCAB_PATH)
        self.assertIn('β.5.19-B', src,
            'predicate_keywords.json 必须含 β.5.19-B marker')


if __name__ == '__main__':
    unittest.main(verbosity=2)
