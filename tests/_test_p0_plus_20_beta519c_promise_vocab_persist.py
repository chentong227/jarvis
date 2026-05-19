# -*- coding: utf-8 -*-
"""[β.5.19-C / 2026-05-20] jarvis_self_promise.py soft vocab 迁移 persist test.

老 jarvis_self_promise.py 把 SOFT_PROMISE_VERBS 写死在 source list (β.2.7.8 立),
违反准则 6 三硬规第 1 条 (持久化). β.5.19-C 迁 memory_pool/promise_soft_vocab.json
+ CLI scripts/promise_vocab_dump.py + py 仅留 _SEED_*_SOFT_PROMISE_VERBS fallback.

注: 复杂 hard PROMISE_PATTERNS regex 留源码 (准则 6 递归边界, 系统级 regex).

测点:
  1. vocab json 存在 + 2 groups (en_soft_verbs / zh_soft_verbs)
  2. _SEED_*_SOFT_PROMISE_VERBS fallback 仍在
  3. _load_promise_vocab() 返 (en, zh) tuple
  4. _get_compiled_soft_patterns() 返编译 regex (mtime cache 生效)
  5. SelfPromiseDetector.detect() 用 mtime-cached compiled patterns
  6. CLI scripts/promise_vocab_dump.py 存在 + list/show/counts 可调
  7. marker [β.5.19-C] 在源码 + json + CLI
  8. EN/ZH soft promise 真匹配测试
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'promise_soft_vocab.json')
CLI_PATH = os.path.join(ROOT, 'scripts', 'promise_vocab_dump.py')


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBeta519CVocabFile(unittest.TestCase):
    """vocab json 文件存在性 + schema 合规"""

    @classmethod
    def setUpClass(cls):
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            cls.data = json.load(f)

    def test_vocab_exists(self):
        self.assertTrue(os.path.exists(VOCAB_PATH))

    def test_vocab_has_meta(self):
        self.assertIn('version', self.data)
        self.assertIn('created_at', self.data)
        self.assertIn('purpose', self.data)

    def test_vocab_has_two_groups(self):
        groups = self.data.get('groups', {})
        for g in ('en_soft_verbs', 'zh_soft_verbs'):
            self.assertIn(g, groups, f'缺 group {g}')
            self.assertIn('description', groups[g])
            self.assertIn('verbs', groups[g])
            self.assertGreater(len(groups[g]['verbs']), 0)

    def test_vocab_history_init_marker(self):
        history = self.data.get('history', [])
        markers = [h.get('marker', '') for h in history]
        self.assertIn('β.5.19-C', markers)


class TestBeta519CLoader(unittest.TestCase):
    """loader + mtime cache + 兼容 fallback"""

    def setUp(self):
        # 重置 cache
        import jarvis_self_promise as sp
        sp._sp_vocab_cache = {}
        sp._sp_vocab_mtime = 0.0
        sp._sp_compiled_en = None
        sp._sp_compiled_zh = None
        if hasattr(sp._get_compiled_soft_patterns, '_compiled_mtime'):
            delattr(sp._get_compiled_soft_patterns, '_compiled_mtime')

    def test_load_returns_two_tuples(self):
        import jarvis_self_promise as sp
        en, zh = sp._load_promise_vocab()
        self.assertIsInstance(en, tuple)
        self.assertIsInstance(zh, tuple)
        self.assertGreater(len(en), 0)
        self.assertGreater(len(zh), 0)

    def test_seed_fallback_exists(self):
        import jarvis_self_promise as sp
        self.assertTrue(hasattr(sp, '_SEED_EN_SOFT_PROMISE_VERBS'))
        self.assertTrue(hasattr(sp, '_SEED_ZH_SOFT_PROMISE_VERBS'))

    def test_load_contains_key_verbs(self):
        import jarvis_self_promise as sp
        en, zh = sp._load_promise_vocab()
        self.assertIn('monitor', en)
        self.assertIn('integrate reminders', en)
        self.assertIn('持续监督', zh)
        self.assertIn('留意', zh)


class TestBeta519CCompiledPatterns(unittest.TestCase):
    """_get_compiled_soft_patterns() 返编译 regex 且能 match"""

    def setUp(self):
        import jarvis_self_promise as sp
        sp._sp_compiled_en = None
        sp._sp_compiled_zh = None
        if hasattr(sp._get_compiled_soft_patterns, '_compiled_mtime'):
            delattr(sp._get_compiled_soft_patterns, '_compiled_mtime')

    def test_compiled_patterns_are_re_pattern(self):
        import jarvis_self_promise as sp
        import re
        en_p, zh_p = sp._get_compiled_soft_patterns()
        self.assertIsInstance(en_p, re.Pattern)
        self.assertIsInstance(zh_p, re.Pattern)

    def test_en_pattern_matches_classic_case(self):
        """β.2.7.8 立时的 Sir 实测 case: 'I will integrate reminders'"""
        import jarvis_self_promise as sp
        en_p, _ = sp._get_compiled_soft_patterns()
        m = en_p.search("I will integrate reminders into our dialogue")
        self.assertIsNotNone(m, 'integrate reminders 必须 match')

    def test_zh_pattern_matches_classic_case(self):
        """中文 '我会持续监督你' 必须 match"""
        import jarvis_self_promise as sp
        _, zh_p = sp._get_compiled_soft_patterns()
        m = zh_p.search("我会持续监督你今晚的状态")
        self.assertIsNotNone(m)


class TestBeta519CDetectorUsesCachedPatterns(unittest.TestCase):
    """SelfPromiseDetector.detect_in_jarvis_reply 用 mtime-cached patterns"""

    def test_detect_finds_soft_en(self):
        from jarvis_self_promise import SelfPromiseDetector
        d = SelfPromiseDetector()
        results = d.detect("I will monitor your late-night coding closely.")
        self.assertGreater(len(results), 0,
            'soft EN promise 必须被 detect')
        # 至少有一条 kind='soft'
        kinds = [r.get('kind') for r in results]
        self.assertIn('soft', kinds)

    def test_detect_finds_soft_zh(self):
        from jarvis_self_promise import SelfPromiseDetector
        d = SelfPromiseDetector()
        # 必须无时间锚 (今晚/明早/数字时间) 才走 soft 路径
        # 如有时间锚会走 hard ZH pattern
        results = d.detect("我会留意你的健康状态保护好你的身体")
        self.assertGreater(len(results), 0)
        kinds = [r.get('kind') for r in results]
        self.assertIn('soft', kinds)


class TestBeta519CCLIDump(unittest.TestCase):
    """scripts/promise_vocab_dump.py CLI 可调"""

    def _run(self, *args):
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        return subprocess.run(
            [sys.executable, CLI_PATH] + list(args),
            cwd=ROOT, env=env, capture_output=True,
            encoding='utf-8', timeout=10)

    def test_cli_exists(self):
        self.assertTrue(os.path.exists(CLI_PATH))

    def test_cli_default_list(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, f'stderr={r.stderr}')
        self.assertIn('Promise Soft Vocab', r.stdout)
        self.assertIn('en_soft_verbs', r.stdout)
        self.assertIn('zh_soft_verbs', r.stdout)

    def test_cli_counts(self):
        r = self._run('--counts')
        self.assertEqual(r.returncode, 0)
        self.assertIn('verb counts', r.stdout)

    def test_cli_show_en(self):
        r = self._run('--show', 'en_soft_verbs')
        self.assertEqual(r.returncode, 0)
        self.assertIn('monitor', r.stdout)

    def test_cli_show_unknown_group_fails(self):
        r = self._run('--show', 'badgroup')
        self.assertNotEqual(r.returncode, 0)


class TestBeta519CMarkers(unittest.TestCase):
    """marker 同步检查"""

    def test_pyfile_marker(self):
        src = _read(os.path.join(ROOT, 'jarvis_self_promise.py'))
        self.assertIn('β.5.19-C', src)

    def test_pyfile_load_function(self):
        src = _read(os.path.join(ROOT, 'jarvis_self_promise.py'))
        self.assertIn('_load_promise_vocab', src)
        self.assertIn('_get_compiled_soft_patterns', src)

    def test_pyfile_detect_uses_cached_helper(self):
        src = _read(os.path.join(ROOT, 'jarvis_self_promise.py'))
        # detect path 必须调 _get_compiled_soft_patterns(), 不再裸引 _EN_SOFT_PATTERN
        self.assertIn('_get_compiled_soft_patterns()', src)

    def test_cli_marker(self):
        src = _read(CLI_PATH)
        self.assertIn('β.5.19-C', src)

    def test_json_marker(self):
        src = _read(VOCAB_PATH)
        self.assertIn('β.5.19-C', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
