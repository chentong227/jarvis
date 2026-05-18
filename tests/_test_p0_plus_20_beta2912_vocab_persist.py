# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.12 / 2026-05-18] behavior_inference_vocab.json 持久化 testcase

Sir 12:53 反馈: "infer_expected_behavior 硬编码 vocab 太蠢, 7 层架构应该自动加/改/删"

准则 6 治本:
  - vocab 持久化 memory_pool/behavior_inference_vocab.json
  - scripts/behavior_vocab_dump.py CLI 看/加/激活/拒绝/真删
  - infer_expected_behavior 动态加载 (mtime cache, 文件变自动 reload)
  - py 里 _SEED_BEHAVIOR_PATTERNS 仅 fallback (json 损坏/首次启动)

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta2912_vocab_persist.py
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestVocabFileLoading(unittest.TestCase):
    """vocab json 加载 + mtime cache"""

    def setUp(self):
        # 隔离: 跑前清 cache
        import jarvis_commitment_watcher as cw
        cw._BEHAVIOR_PATTERNS_CACHE = None
        cw._BEHAVIOR_PATTERNS_MTIME = 0.0
        self.cw = cw

    def test_seed_patterns_fallback_when_no_json(self):
        """json 不存在 → fallback _SEED_BEHAVIOR_PATTERNS"""
        bogus_path = '/nonexistent/x.json'
        with unittest.mock.patch.object(
                self.cw, '_BEHAVIOR_VOCAB_PATH', bogus_path):
            self.cw._BEHAVIOR_PATTERNS_CACHE = None
            patterns = self.cw.get_behavior_patterns()
        # fallback to seed
        self.assertGreater(len(patterns), 0)
        # seed 第 1 个是 sleep 类 idle_min
        first_eb = patterns[0][1]
        self.assertEqual(first_eb['kind'], 'idle_min')

    def test_loads_active_patterns_from_json(self):
        """json 存在 + 含 active pattern → 加载"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({
                '_meta': {'schema_version': 1},
                'patterns': [
                    {'id': 'test_a', 'keywords': ['testkw1'],
                     'expected_behavior': {'kind': 'idle_min', 'threshold': 99},
                     'state': 'active'},
                    {'id': 'test_b', 'keywords': ['testkw2'],
                     'expected_behavior': {'kind': 'idle_min', 'threshold': 22},
                     'state': 'review'},  # review 不应被加载
                ]
            }, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.cw, '_BEHAVIOR_VOCAB_PATH', tmpname):
                self.cw._BEHAVIOR_PATTERNS_CACHE = None
                self.cw._BEHAVIOR_PATTERNS_MTIME = 0.0
                patterns = self.cw.get_behavior_patterns()
            # 只 active 加载, review 不算
            self.assertEqual(len(patterns), 1)
            kws, eb = patterns[0]
            self.assertIn('testkw1', kws)
            self.assertEqual(eb['threshold'], 99)
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads_on_change(self):
        """文件变 mtime → cache 自动 reload"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [{'id': 'v1', 'keywords': ['x'],
                                       'expected_behavior': {'kind': 'idle_min', 'threshold': 1},
                                       'state': 'active'}]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.cw, '_BEHAVIOR_VOCAB_PATH', tmpname):
                self.cw._BEHAVIOR_PATTERNS_CACHE = None
                self.cw._BEHAVIOR_PATTERNS_MTIME = 0.0
                v1 = self.cw.get_behavior_patterns()
                self.assertEqual(v1[0][1]['threshold'], 1)
                # 改文件
                time.sleep(1.1)  # 确保 mtime 不同
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [{'id': 'v2', 'keywords': ['y'],
                                              'expected_behavior': {'kind': 'idle_min', 'threshold': 99},
                                              'state': 'active'}]}, f)
                v2 = self.cw.get_behavior_patterns()
                self.assertEqual(v2[0][1]['threshold'], 99,
                                  'mtime 变了 cache 必须 reload')
        finally:
            os.remove(tmpname)


class TestInferUsesDynamicVocab(unittest.TestCase):
    """infer_expected_behavior 用持久化 vocab"""

    def setUp(self):
        import jarvis_commitment_watcher as cw
        cw._BEHAVIOR_PATTERNS_CACHE = None
        cw._BEHAVIOR_PATTERNS_MTIME = 0.0
        self.cw = cw

    def test_sir_added_pattern_takes_effect(self):
        """Sir 通过 CLI 加新 pattern → infer 立即生效"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [{
                'id': 'sir_added_chrome',
                'keywords': ['看完youtube', 'finished youtube'],
                'expected_behavior': {'kind': 'idle_min', 'threshold': 7},
                'state': 'active',
            }]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.cw, '_BEHAVIOR_VOCAB_PATH', tmpname):
                self.cw._BEHAVIOR_PATTERNS_CACHE = None
                self.cw._BEHAVIOR_PATTERNS_MTIME = 0.0
                eb = self.cw.infer_expected_behavior('我看完YouTube就睡')
            self.assertIsNotNone(eb)
            self.assertEqual(eb['kind'], 'idle_min')
            self.assertEqual(eb['threshold'], 7)
        finally:
            os.remove(tmpname)


class TestCLIScript(unittest.TestCase):
    """scripts/behavior_vocab_dump.py CLI 烟测"""

    def test_cli_script_exists(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'behavior_vocab_dump.py')
        self.assertTrue(os.path.exists(cli_path),
                          'scripts/behavior_vocab_dump.py 必须存在')

    def test_cli_supports_add_activate_reject(self):
        """CLI 必须支持 4 个基本动作"""
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'behavior_vocab_dump.py')
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only']:
            self.assertIn(required, src,
                          f'CLI 必须支持 {required}')


import unittest.mock  # 给上面 patch 用


if __name__ == '__main__':
    unittest.main(verbosity=2)
