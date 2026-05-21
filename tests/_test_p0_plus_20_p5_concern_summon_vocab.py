# -*- coding: utf-8 -*-
"""[P5-Gap4-followup-vocab / 2026-05-21 21:42] concern_summon_vocab + loader 测试

准则 6.5 完整范式验证:
1. vocab json 持久化 (memory_pool/concern_summon_vocab.json)
2. CLI 可改 (scripts/concern_summon_dump.py)
3. loader 加载 + fallback (jarvis_concern_summon.py)
4. central_nerve 主流路径用 loader (commit dec4870 + 本 commit)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_VocabFileShape(unittest.TestCase):
    """vocab json 文件结构正确."""

    def test_vocab_file_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'concern_summon_vocab.json'
        )
        self.assertTrue(os.path.exists(path), f'vocab 文件应存在: {path}')

    def test_vocab_schema(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'concern_summon_vocab.json'
        )
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('_meta', data)
        self.assertIn('patterns', data)
        self.assertIsInstance(data['patterns'], list)
        for p in data['patterns']:
            self.assertIn('id', p)
            self.assertIn('keywords', p)
            self.assertIn('state', p)


class TestB_LoaderActiveKeywords(unittest.TestCase):
    """loader 加载 active keyword."""

    def setUp(self):
        from jarvis_concern_summon import reset_cache_for_test
        reset_cache_for_test()

    def test_load_returns_keywords(self):
        from jarvis_concern_summon import load_active_keywords
        kws = load_active_keywords(force_reload=True)
        self.assertGreater(len(kws), 5, '至少 5 个 keyword 才合理')
        # 中英都有
        self.assertTrue(any('concern' in kw for kw in kws))
        self.assertTrue(any('担心' in kw for kw in kws))


class TestC_IsSummoned(unittest.TestCase):
    """is_summoned 命中检测."""

    def setUp(self):
        from jarvis_concern_summon import reset_cache_for_test
        reset_cache_for_test()

    def test_summon_english(self):
        from jarvis_concern_summon import is_summoned
        self.assertTrue(is_summoned("what's my progress today"))
        self.assertTrue(is_summoned("any concerns I should know"))

    def test_summon_chinese(self):
        from jarvis_concern_summon import is_summoned
        self.assertTrue(is_summoned("我担心啥呢"))
        self.assertTrue(is_summoned("我有什么进度要看"))
        self.assertTrue(is_summoned("提醒我啥事"))

    def test_no_summon_normal_chat(self):
        from jarvis_concern_summon import is_summoned
        self.assertFalse(is_summoned("Good evening, Sir"))
        self.assertFalse(is_summoned("Thank you"))
        self.assertFalse(is_summoned("我刚才睡了 3 小时"))
        self.assertFalse(is_summoned(""))


class TestD_FallbackOnVocabMissing(unittest.TestCase):
    """vocab 缺失/损坏 → fall back hardcoded list."""

    def test_fallback_when_path_missing(self):
        # monkeypatch _VOCAB_PATH 指向不存在的位置 → fall back
        import jarvis_concern_summon as jcs
        original = jcs._VOCAB_PATH
        try:
            jcs._VOCAB_PATH = '/tmp/nonexistent_vocab_xxx.json'
            jcs.reset_cache_for_test()
            kws = jcs.load_active_keywords(force_reload=True)
            self.assertGreater(len(kws), 5,
                                'fall back hardcoded list 应至少 5 个 keyword')
            # 经典 fallback 词应在
            self.assertIn('concern', kws)
            self.assertIn('担心', kws)
        finally:
            jcs._VOCAB_PATH = original
            jcs.reset_cache_for_test()


class TestE_FallbackOnCorruptVocab(unittest.TestCase):
    """vocab json 损坏 → fall back."""

    def test_fallback_when_json_corrupt(self):
        import jarvis_concern_summon as jcs
        original = jcs._VOCAB_PATH
        with tempfile.NamedTemporaryFile(
                'w', delete=False, suffix='.json', encoding='utf-8') as f:
            f.write('{this is not valid json')
            corrupt_path = f.name
        try:
            jcs._VOCAB_PATH = corrupt_path
            jcs.reset_cache_for_test()
            kws = jcs.load_active_keywords(force_reload=True)
            self.assertGreater(len(kws), 5, 'JSON 损坏应 fall back')
            self.assertIn('concern', kws)
        finally:
            jcs._VOCAB_PATH = original
            jcs.reset_cache_for_test()
            try:
                os.remove(corrupt_path)
            except Exception:
                pass


class TestF_CentralNerveUsesLoader(unittest.TestCase):
    """central_nerve _assemble_prompt 主流路径调 loader."""

    def test_central_nerve_imports_loader(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 主流路径用 loader
        self.assertIn('from jarvis_concern_summon import is_summoned', src,
                       'central_nerve 应 import loader 主流路径')
        # fallback 仍存在
        self.assertIn('_summon_kw', src,
                       'fallback hardcoded list 仍 present (resilience)')


class TestG_CLIDumpAvailable(unittest.TestCase):
    """CLI 工具可执行."""

    def test_cli_script_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'concern_summon_dump.py'
        )
        self.assertTrue(os.path.exists(path),
                         f'CLI 工具应存在: {path}')

    def test_cli_supports_test_command(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'concern_summon_dump.py'
        )
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('--test', src)
        self.assertIn('--add', src)
        self.assertIn('--activate', src)
        self.assertIn('--reject', src)
        self.assertIn('--delete', src)


if __name__ == '__main__':
    unittest.main()
