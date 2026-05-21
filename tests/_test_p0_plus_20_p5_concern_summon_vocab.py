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

    def test_keywords_are_phrases_not_single_words(self):
        """[Sir 21:56 教训] keyword 应是完整短语, 不是单词.

        '状态' 单词误命中 '状态还不错' 导致 unsolicited callback.
        修法: 改成完整短语 '我状态如何' / '状态如何' 等.
        """
        from jarvis_concern_summon import load_active_keywords
        kws = load_active_keywords(force_reload=True)
        # 检查不应包含的宽词
        forbidden_singles = (
            '状态', '进度', '怎么样', '关心', '检查',
            'status', 'progress', 'concern', 'worry',
        )
        for kw in kws:
            self.assertNotIn(kw, forbidden_singles,
                              f'keyword "{kw}" 太宽泛, 易误触, 应改成完整短语')


class TestC_IsSummoned(unittest.TestCase):
    """is_summoned 命中检测."""

    def setUp(self):
        from jarvis_concern_summon import reset_cache_for_test
        reset_cache_for_test()

    def test_summon_english(self):
        from jarvis_concern_summon import is_summoned
        self.assertTrue(is_summoned("what's my progress today"))
        self.assertTrue(is_summoned("any concerns I should know"))
        self.assertTrue(is_summoned("how am I doing today"))

    def test_summon_chinese(self):
        from jarvis_concern_summon import is_summoned
        self.assertTrue(is_summoned("我担心啥呢"))
        self.assertTrue(is_summoned("什么进度要看"))
        self.assertTrue(is_summoned("提醒我啥事"))
        self.assertTrue(is_summoned("我状态如何"))

    def test_no_summon_normal_chat(self):
        from jarvis_concern_summon import is_summoned
        self.assertFalse(is_summoned("Good evening, Sir"))
        self.assertFalse(is_summoned("Thank you"))
        self.assertFalse(is_summoned("我刚才睡了 3 小时"))
        self.assertFalse(is_summoned(""))

    def test_no_summon_descriptive_state(self):
        """[Sir 21:56 真测痛点] '状态还不错' 不应触发 summon.

        Sir 是描述自己状态, 不是问 Jarvis "我状态如何".
        '状态' 单词被误命中是当晚翻 4% backspace 老账的根因.
        """
        from jarvis_concern_summon import is_summoned
        self.assertFalse(
            is_summoned("今天晚上因为休息了一下，所以状态还不错"),
            "描述性 '状态还不错' 不应触发 summon (Sir 21:56 真测教训)"
        )
        self.assertFalse(
            is_summoned("我现在状态很好"),
            "描述性 '状态很好' 不应触发 summon"
        )
        self.assertFalse(
            is_summoned("项目进度不错"),
            "描述性 '进度不错' 不应触发 summon"
        )
        self.assertFalse(
            is_summoned("怎么样, 累不累"),
            "Sir 关心 Jarvis 的 '怎么样' 不应触发"
        )


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
            # 完整短语应在 (Sir 21:56 教训后改成短语)
            self.assertTrue(any('concern' in kw for kw in kws),
                             '应有含 concern 的短语')
            self.assertTrue(any('担心' in kw for kw in kws),
                             '应有含 担心 的短语')
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
            # 完整短语应在
            self.assertTrue(any('concern' in kw for kw in kws),
                             '应有含 concern 的短语')
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
