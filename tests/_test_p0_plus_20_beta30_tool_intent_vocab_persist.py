# -*- coding: utf-8 -*-
"""[P0+20-β.3.0-vocab1 / 2026-05-18] tool_intent_vocab.json 持久化 testcase

INTEGRITY_STACK Session 0 第 1 项: tool_intent vocab 迁 py → json + CLI.

Sir 准则 6.5: vocab 不能硬编码 in py, 必须可加/改/删 + L7 LLM-propose 接口预留.

本 testcase 验证:
  - vocab 持久化 memory_pool/tool_intent_vocab.json
  - scripts/tool_intent_dump.py CLI 看/加/激活/拒绝/真删
  - jarvis_directives.get_tool_intent_patterns() 动态加载 (mtime cache, 文件变自动 reload)
  - py 里 _SEED_TOOL_INTENT_PATTERNS 仅 fallback (json 损坏/首次启动)
  - _trigger_tool_overture 用 get_tool_intent_patterns() 不再读硬编码 tuple

跑法:
    cd d:\\Jarvis
    python -m pytest tests/_test_p0_plus_20_beta30_tool_intent_vocab_persist.py -v
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
    """vocab json 加载 + mtime cache"""

    def setUp(self):
        # 隔离: 跑前清 cache
        import jarvis_directives as jd
        jd._TOOL_INTENT_PATTERNS_CACHE = None
        jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
        self.jd = jd

    def test_seed_patterns_fallback_when_no_json(self):
        """json 不存在 → fallback _SEED_TOOL_INTENT_PATTERNS"""
        bogus_path = '/nonexistent/tool_intent_x.json'
        with unittest.mock.patch.object(
                self.jd, '_TOOL_INTENT_VOCAB_PATH', bogus_path):
            self.jd._TOOL_INTENT_PATTERNS_CACHE = None
            patterns = self.jd.get_tool_intent_patterns()
        # fallback to seed
        self.assertGreater(len(patterns), 0)
        # seed 含中文设备控制 + ASCII 动词
        self.assertIn('打开', patterns)
        self.assertIn('open', patterns)

    def test_loads_active_patterns_from_json(self):
        """json 存在 + 含 active pattern → 加载; review/archived 不加载"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({
                '_meta': {'schema_version': 1},
                'patterns': [
                    {'id': 'test_active', 'category': 'misc',
                     'keywords': ['testkw_a', 'testkw_b'],
                     'state': 'active'},
                    {'id': 'test_review', 'category': 'misc',
                     'keywords': ['shouldnotload_review'],
                     'state': 'review'},
                    {'id': 'test_archived', 'category': 'misc',
                     'keywords': ['shouldnotload_arch'],
                     'state': 'archived'},
                ]
            }, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_TOOL_INTENT_VOCAB_PATH', tmpname):
                self.jd._TOOL_INTENT_PATTERNS_CACHE = None
                self.jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
                patterns = self.jd.get_tool_intent_patterns()
            # 只 active 加载, review/archived 不算
            self.assertIn('testkw_a', patterns)
            self.assertIn('testkw_b', patterns)
            self.assertNotIn('shouldnotload_review', patterns)
            self.assertNotIn('shouldnotload_arch', patterns)
        finally:
            os.remove(tmpname)

    def test_mtime_cache_reloads_on_change(self):
        """文件 mtime 变 → cache 自动 reload"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [{'id': 'v1', 'category': 'misc',
                                       'keywords': ['oldkw'],
                                       'state': 'active'}]}, f)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_TOOL_INTENT_VOCAB_PATH', tmpname):
                self.jd._TOOL_INTENT_PATTERNS_CACHE = None
                self.jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
                v1 = self.jd.get_tool_intent_patterns()
                self.assertIn('oldkw', v1)
                self.assertNotIn('newkw', v1)
                # 改文件
                time.sleep(1.1)  # 确保 mtime 不同
                with open(tmpname, 'w', encoding='utf-8') as f:
                    json.dump({'patterns': [{'id': 'v2', 'category': 'misc',
                                              'keywords': ['newkw'],
                                              'state': 'active'}]}, f)
                v2 = self.jd.get_tool_intent_patterns()
                self.assertIn('newkw', v2,
                              'mtime 变了 cache 必须 reload')
                self.assertNotIn('oldkw', v2)
        finally:
            os.remove(tmpname)

    def test_corrupt_json_falls_back_to_seed(self):
        """json 损坏 → fallback _SEED_TOOL_INTENT_PATTERNS, 不 crash"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            f.write('{ this is not valid json [[[')
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_TOOL_INTENT_VOCAB_PATH', tmpname):
                self.jd._TOOL_INTENT_PATTERNS_CACHE = None
                self.jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
                patterns = self.jd.get_tool_intent_patterns()
            # 应 fallback to seed (含 '打开')
            self.assertIn('打开', patterns)
        finally:
            os.remove(tmpname)


class TestTriggerUsesDynamicVocab(unittest.TestCase):
    """_trigger_tool_overture 用持久化 vocab"""

    def setUp(self):
        import jarvis_directives as jd
        jd._TOOL_INTENT_PATTERNS_CACHE = None
        jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
        self.jd = jd

    def test_sir_added_keyword_takes_effect(self):
        """Sir 通过 CLI 加新 keyword → trigger 立即生效"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False, encoding='utf-8') as f:
            json.dump({'patterns': [{
                'id': 'sir_custom',
                'category': 'misc',
                'keywords': ['一个绝对不会自然出现的关键词xyz'],
                'state': 'active',
            }]}, f, ensure_ascii=False)
            tmpname = f.name
        try:
            with unittest.mock.patch.object(
                    self.jd, '_TOOL_INTENT_VOCAB_PATH', tmpname):
                self.jd._TOOL_INTENT_PATTERNS_CACHE = None
                self.jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
                ctx_hit = self.jd.DirectiveContext(
                    user_input='我想要一个绝对不会自然出现的关键词xyz')
                ctx_miss = self.jd.DirectiveContext(
                    user_input='今天天气如何')
                self.assertTrue(self.jd._trigger_tool_overture(ctx_hit))
                self.assertFalse(self.jd._trigger_tool_overture(ctx_miss))
        finally:
            os.remove(tmpname)

    def test_real_json_drives_trigger(self):
        """真 memory_pool/tool_intent_vocab.json (本 repo 默认) 能驱动 trigger"""
        # 用默认 json (不 patch path), 应该命中 seed 同义词
        self.jd._TOOL_INTENT_PATTERNS_CACHE = None
        self.jd._TOOL_INTENT_PATTERNS_MTIME = 0.0
        ctx_hit_zh = self.jd.DirectiveContext(user_input='帮我打开 chrome')
        ctx_hit_en = self.jd.DirectiveContext(user_input='please open chrome')
        ctx_miss = self.jd.DirectiveContext(user_input='今天天气不错')
        self.assertTrue(self.jd._trigger_tool_overture(ctx_hit_zh))
        self.assertTrue(self.jd._trigger_tool_overture(ctx_hit_en))
        self.assertFalse(self.jd._trigger_tool_overture(ctx_miss))


class TestCLIScript(unittest.TestCase):
    """scripts/tool_intent_dump.py CLI 烟测"""

    def test_cli_script_exists(self):
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'tool_intent_dump.py')
        self.assertTrue(os.path.exists(cli_path),
                          'scripts/tool_intent_dump.py 必须存在')

    def test_cli_supports_required_actions(self):
        """CLI 必须支持 list / add / activate / reject / delete + state filter"""
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'tool_intent_dump.py')
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        for required in ['--add', '--activate', '--reject', '--delete',
                          '--review-list', '--active-only', '--archived',
                          '--category', '--keywords', '--state']:
            self.assertIn(required, src,
                          f'CLI 必须支持 {required}')


class TestNoHardcodedTupleInPy(unittest.TestCase):
    """准则 6.5 红线: py 里不能有 _TOOL_INTENT_PATTERNS = (...) 硬编码"""

    def test_old_hardcoded_name_renamed(self):
        """旧 _TOOL_INTENT_PATTERNS 必须改名为 _SEED_TOOL_INTENT_PATTERNS"""
        import jarvis_directives as jd
        # 旧名不应存在 (避免被误用)
        self.assertFalse(hasattr(jd, '_TOOL_INTENT_PATTERNS'),
                         '旧硬编码 _TOOL_INTENT_PATTERNS 必须改名为 _SEED_TOOL_INTENT_PATTERNS')
        # 新名 (seed fallback) 应存在
        self.assertTrue(hasattr(jd, '_SEED_TOOL_INTENT_PATTERNS'))
        # runtime helper 应存在
        self.assertTrue(callable(getattr(jd, 'get_tool_intent_patterns', None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
