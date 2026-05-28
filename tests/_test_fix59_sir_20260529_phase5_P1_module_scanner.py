# -*- coding: utf-8 -*-
"""[SOUL Phase 5 P1 / Sir 2026-05-29] 动态架构地图 — jarvis_module_scanner.

设计文档: docs/JARVIS_DYNAMIC_MAP_AND_SELF_DEBUG_DESIGN.md
SOUL lineage: 自我认知元架构从"我是谁"(Layer 0) 延伸到"我的身体构造"(架构)

P1 目标: AST 零副作用扫 jarvis_*.py → module_map.json (活数据) + agent-readable md.
  缘起: JARVIS_ARCHITECTURE_MAP.md 手维护过时 (6 天漏 28 模块 + 思考脑核心缺失).
  Sir 洞察: "动态地图 = Jarvis 认知自己架构的活组件, 非独立文档".

测试覆盖 (~14 testcase):
  scan_module (5):
    - P1_1: 提取 lines/purpose/classes
    - P1_2: 提取 vocab_files / doc_refs (regex)
    - P1_3: 提取 depends_on (all, 含 lazy)
    - P1_4: 提取 depends_on_toplevel (仅 module-level)
    - P1_5: parse_fail 记 error 不崩
  infer_layer (2):
    - P1_6: thinking/soul/integrity 分类
    - P1_7: vocab override
  scan_all (4):
    - P1_8: 全扫 fixture dir + 反向依赖 depended_by
    - P1_9: circular 只算 top-level 双向 (lazy 不算)
    - P1_10: stats (orphans/no_docstring/with_docstring)
    - P1_11: 真扫 root (119 模块, circular=0 验证)
  render + retrieve (3):
    - P1_12: render_markdown 含 agent 快速导航 + layer 分组
    - P1_13: load_module_map 读回
    - P1_14: get_modules_for_keyword retrieve (P2 用)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _write_fixture(tmpdir, name, content):
    path = os.path.join(tmpdir, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


class TestScanModule(unittest.TestCase):
    """P1_1-5: scan_module AST 提取."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_P1_1_lines_purpose_classes(self):
        from jarvis_module_scanner import scan_module
        src = '''# -*- coding: utf-8 -*-
"""Fake module — test purpose line."""
import os


class FakeEngine:
    pass


class FakeHelper:
    pass
'''
        p = _write_fixture(self.tmp, 'jarvis_fake_a.py', src)
        info = scan_module(p)
        self.assertEqual(info['purpose'], 'Fake module — test purpose line.')
        self.assertIn('FakeEngine', info['classes'])
        self.assertIn('FakeHelper', info['classes'])
        self.assertGreater(info['lines'], 5)
        self.assertNotIn('error', info)

    def test_P1_2_vocab_doc_refs(self):
        from jarvis_module_scanner import scan_module
        src = '''"""Fake."""
PATH = "memory_pool/fake_config.json"
PATH2 = "memory_pool/another_vocab.json"
# see docs/JARVIS_FAKE_DESIGN.md
'''
        p = _write_fixture(self.tmp, 'jarvis_fake_b.py', src)
        info = scan_module(p)
        self.assertIn('fake_config.json', info['vocab_files'])
        self.assertIn('another_vocab.json', info['vocab_files'])
        self.assertIn('JARVIS_FAKE_DESIGN.md', info['doc_refs'])

    def test_P1_3_depends_on_all_incl_lazy(self):
        from jarvis_module_scanner import scan_module
        src = '''"""Fake."""
from jarvis_utils import bg_log


def helper():
    from jarvis_concerns import ConcernsLedger  # lazy import
    return ConcernsLedger
'''
        p = _write_fixture(self.tmp, 'jarvis_fake_c.py', src)
        info = scan_module(p)
        # all_deps 含 top-level + lazy
        self.assertIn('jarvis_utils', info['depends_on'])
        self.assertIn('jarvis_concerns', info['depends_on'])

    def test_P1_4_depends_on_toplevel_only(self):
        from jarvis_module_scanner import scan_module
        src = '''"""Fake."""
from jarvis_utils import bg_log


def helper():
    from jarvis_concerns import ConcernsLedger  # lazy — NOT toplevel
    return ConcernsLedger
'''
        p = _write_fixture(self.tmp, 'jarvis_fake_d.py', src)
        info = scan_module(p)
        # toplevel 只含 module-level import
        self.assertIn('jarvis_utils', info['depends_on_toplevel'])
        self.assertNotIn('jarvis_concerns', info['depends_on_toplevel'],
                          "P1_4 lazy import 不应在 toplevel")

    def test_P1_5_parse_fail_records_error(self):
        from jarvis_module_scanner import scan_module
        src = '"""Fake."""\ndef broken(:\n  pass\n'  # syntax error
        p = _write_fixture(self.tmp, 'jarvis_fake_broken.py', src)
        info = scan_module(p)
        self.assertIn('error', info)
        self.assertIn('parse_fail', info['error'])


class TestInferLayer(unittest.TestCase):
    """P1_6-7: layer 分类."""

    def test_P1_6_layer_classification(self):
        from jarvis_module_scanner import _infer_layer
        self.assertEqual(_infer_layer('jarvis_inner_thought_daemon'), 'thinking')
        self.assertEqual(_infer_layer('jarvis_concerns'), 'soul')
        self.assertEqual(_infer_layer('jarvis_claim_tracer'), 'integrity')
        self.assertEqual(_infer_layer('jarvis_hippocampus'), 'memory')
        self.assertEqual(_infer_layer('jarvis_proactive_care'), 'nudge')

    def test_P1_7_unknown_layer_misc(self):
        from jarvis_module_scanner import _infer_layer
        self.assertEqual(_infer_layer('jarvis_zzz_unknown_xyz'), 'misc')


class TestScanAll(unittest.TestCase):
    """P1_8-11: scan_all 全扫 + circular + stats."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _setup_circular_fixtures(self):
        # A ↔ B top-level 双向 (真 circular)
        _write_fixture(self.tmp, 'jarvis_a.py',
                       '"""A."""\nfrom jarvis_b import x\n')
        _write_fixture(self.tmp, 'jarvis_b.py',
                       '"""B."""\nfrom jarvis_a import y\n')
        # C lazy import A (不算 circular)
        _write_fixture(self.tmp, 'jarvis_c.py',
                       '"""C."""\ndef f():\n    from jarvis_a import z\n')

    def test_P1_8_scan_all_reverse_deps(self):
        from jarvis_module_scanner import scan_all
        self._setup_circular_fixtures()
        data = scan_all(self.tmp)
        mods = data['modules']
        self.assertEqual(len(mods), 3)
        # jarvis_a depended_by 含 b (top) + c (lazy)
        self.assertIn('jarvis_b', mods['jarvis_a']['depended_by'])
        self.assertIn('jarvis_c', mods['jarvis_a']['depended_by'])

    def test_P1_9_circular_toplevel_only(self):
        from jarvis_module_scanner import scan_all
        self._setup_circular_fixtures()
        data = scan_all(self.tmp)
        circular = data['stats']['circular_deps']
        # A↔B top-level 双向 → 算 1 对
        pairs = [tuple(sorted(p)) for p in circular]
        self.assertIn(('jarvis_a', 'jarvis_b'), pairs)
        # A-C lazy 单向 (C lazy import A, A 不 import C) → 不算
        self.assertNotIn(('jarvis_a', 'jarvis_c'), pairs)

    def test_P1_10_stats(self):
        from jarvis_module_scanner import scan_all
        _write_fixture(self.tmp, 'jarvis_withdoc.py',
                       '"""Has doc."""\nimport os\n')
        _write_fixture(self.tmp, 'jarvis_nodoc.py',
                       'import os\n')  # 无 docstring
        data = scan_all(self.tmp)
        stats = data['stats']
        self.assertEqual(stats['total_modules'], 2)
        self.assertEqual(stats['with_docstring'], 1)
        self.assertIn('jarvis_nodoc', stats['no_docstring'])

    def test_P1_11_real_scan_circular_zero(self):
        """P1_11: 真扫 root — 119 模块, circular=0 (Jarvis lazy import 设计好)."""
        from jarvis_module_scanner import scan_all
        data = scan_all(ROOT)
        st = data['stats']
        self.assertGreaterEqual(st['total_modules'], 110,
                                 "真扫应 >= 110 模块")
        # Jarvis 用 lazy import 避免 load-time 循环 → top-level circular = 0
        self.assertEqual(len(st['circular_deps']), 0,
                          f"真扫 circular 应 0, 实际 {st['circular_deps'][:3]}")
        # 思考脑核心应在 (验证不漏关键模块, 修手 map 痛点)
        self.assertIn('jarvis_inner_thought_daemon', data['modules'])


class TestRenderRetrieve(unittest.TestCase):
    """P1_12-14: render + load + retrieve."""

    def test_P1_12_render_agent_readable(self):
        from jarvis_module_scanner import scan_all, render_markdown
        data = scan_all(ROOT)
        md = render_markdown(data)
        # Sir 强调 agent-readable
        self.assertIn('Agent 快速导航', md)
        self.assertIn('AUTO-GENERATED', md)
        self.assertIn('按 Layer 分组', md)
        self.assertIn('架构治理', md)
        # 核心枢纽应出现
        self.assertIn('jarvis_chat_bypass', md)

    def test_P1_13_load_module_map(self):
        from jarvis_module_scanner import (
            scan_all, save_module_map, load_module_map,
        )
        import tempfile as _tf
        data = scan_all(ROOT)
        tmp_path = _tf.mktemp(suffix='_mm.json')
        try:
            save_module_map(data, tmp_path)
            loaded = load_module_map(tmp_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(
                loaded['_meta']['schema'], 'module_map'
            )
            self.assertIn('jarvis_inner_thought_daemon', loaded['modules'])
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_P1_14_get_modules_for_keyword(self):
        """P1_14: retrieve 按 keyword (P2 self-debug 用)."""
        from jarvis_module_scanner import (
            scan_all, save_module_map, get_modules_for_keyword,
        )
        import tempfile as _tf
        data = scan_all(ROOT)
        tmp_path = _tf.mktemp(suffix='_mm.json')
        try:
            save_module_map(data, tmp_path)
            # retrieve 'proactive' → 应命中 jarvis_proactive_care
            hits = get_modules_for_keyword('proactive', tmp_path)
            self.assertGreater(len(hits), 0)
            names = [h['name'] for h in hits]
            self.assertTrue(
                any('proactive' in n for n in names),
                f"P1_14 retrieve 'proactive' 应命中, 实际 {names}"
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
