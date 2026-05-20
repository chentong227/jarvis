# -*- coding: utf-8 -*-
"""[β.5.35-A / 2026-05-20] screen_tease vocab 持久化 regression test.

Sir 2026-05-20 10:46 实测 BUG 2: SmartNudge screen_tease 一周静音.
根因: error_kw / fun_kw / slack_kw 硬编码在 jarvis_smart_nudge.py:361-372
跟不上 Sir 真实屏幕场景 (Cascade / Cursor / IDE 项目名 / 文档 / 教程都不在 vocab).

修法 (准则 6 持久化 + CLI):
  1. memory_pool/screen_tease_vocab.json  — 5 seed category (active)
  2. scripts/screen_tease_vocab_dump.py    — CLI 增删查改
  3. jarvis_smart_nudge.py 改读 vocab (mtime cache 秒级生效)

docs: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'screen_tease_vocab.json')
CLI_PATH = os.path.join(ROOT, 'scripts', 'screen_tease_vocab_dump.py')


class TestBeta535AVocabFileSchema(unittest.TestCase):
    """vocab JSON 文件存在 + schema 正确."""

    def test_vocab_json_exists(self):
        self.assertTrue(os.path.exists(VOCAB_PATH),
            f'screen_tease_vocab.json 必须存在 (β.5.35-A): {VOCAB_PATH}')

    def test_vocab_json_schema(self):
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 三个 top-level key 必须存在
        self.assertIn('_meta', data)
        self.assertIn('categories', data)
        self.assertIn('review_queue', data)
        self.assertIn('rejected_history', data)
        self.assertEqual(data['_meta'].get('schema_version'), 1)
        self.assertIsInstance(data['categories'], list)
        self.assertIsInstance(data['review_queue'], list)
        self.assertIsInstance(data['rejected_history'], list)

    def test_seed_categories_present(self):
        """β.5.35-A: 5 个 seed category 必须 active."""
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        active_ids = {c.get('id') for c in data['categories']
                      if c.get('state', 'active') == 'active'}
        # 5 个 seed (Sir 拍板的): β.4.X 3 个 + β.5.35 扩的 2 个
        for seed_id in ('error_debugging', 'entertainment', 'slacking',
                        'reading_docs', 'ide_focus'):
            self.assertIn(seed_id, active_ids,
                f'seed category "{seed_id}" 必须在 vocab 里 active')

    def test_seed_category_fields_present(self):
        """每个 active category 必须含 id / keywords / directive_hint / state."""
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for c in data['categories']:
            for required in ('id', 'state', 'keywords', 'directive_hint'):
                self.assertIn(required, c,
                    f'category {c.get("id", "?")} 缺字段 {required}')
            self.assertIsInstance(c['keywords'], list)
            self.assertTrue(len(c['keywords']) > 0,
                f'category {c["id"]} keywords 不能为空')


class TestBeta535ASmartNudgeReadsVocab(unittest.TestCase):
    """SmartNudge 改读 vocab, 不再硬编码 error_kw / fun_kw / slack_kw."""

    def _get_src(self):
        with open(os.path.join(ROOT, 'jarvis_smart_nudge.py'), 'r', encoding='utf-8') as f:
            return f.read()

    def test_marker_present(self):
        src = self._get_src()
        self.assertIn('β.5.35-A', src, 'β.5.35-A marker 必须在 jarvis_smart_nudge.py')

    def test_load_vocab_helper_exists(self):
        src = self._get_src()
        self.assertIn('def _load_screen_tease_vocab', src,
            '_load_screen_tease_vocab helper 必须存在 (mtime cache)')

    def test_old_hardcoded_lists_removed(self):
        """硬编码 error_kw / fun_kw / slack_kw 列表必须删除 (准则 6)."""
        src = self._get_src()
        # 老 list 都已转 vocab — 不再在 .py 源码出现 inline list
        # (注释里提名字 OK, 但不能再有 `error_kw = [...]` 这样的赋值)
        for forbidden_assign in (
            'error_kw = [',
            'fun_kw = [',
            'slack_kw = [',
        ):
            self.assertNotIn(forbidden_assign, src,
                f'硬编码 list `{forbidden_assign}...]` 必须删除 (β.5.35-A 持久化到 vocab)')

    def test_reads_vocab_at_screen_tease_branch(self):
        """screen_tease 触发分支必须调 _load_screen_tease_vocab."""
        src = self._get_src()
        # 找 screen_tease 触发块
        # 简化匹配: helper 名 + screen_tease 串紧邻在 1.5kb 内
        helper_idx = src.find('_load_screen_tease_vocab()')
        st_branch_idx = src.find('"screen_tease",', helper_idx if helper_idx > 0 else 0)
        self.assertGreater(helper_idx, 0,
            'helper _load_screen_tease_vocab() 必须被调用 (vocab 路径)')
        self.assertGreater(st_branch_idx, helper_idx,
            'screen_tease tuple 必须在 helper 调用之后 (vocab 命中后 append)')
        # 间距 < 2kb (确保是同一逻辑块, 不是两处无关代码)
        self.assertLess(st_branch_idx - helper_idx, 2000,
            'screen_tease append 必须紧邻 helper 调用 (同一 branch)')


class TestBeta535ACLI(unittest.TestCase):
    """CLI scripts/screen_tease_vocab_dump.py 工作."""

    def test_cli_script_exists(self):
        self.assertTrue(os.path.exists(CLI_PATH),
            f'screen_tease_vocab_dump.py 必须存在: {CLI_PATH}')

    def test_cli_list_runs_clean(self):
        """CLI --active-only 不能崩."""
        # encoding='utf-8' + errors='replace' 兼容 Win GBK locale (β.5.35-A test patch)
        r = subprocess.run(
            [sys.executable, CLI_PATH, '--active-only'],
            capture_output=True, text=True, cwd=ROOT, timeout=30,
            encoding='utf-8', errors='replace',
        )
        self.assertEqual(r.returncode, 0,
            f'CLI 不能 exit != 0: stderr={r.stderr}')
        out = (r.stdout or '').lower()
        self.assertIn('active', out,
            'CLI list 输出必须含 "active"')

    def test_cli_add_remove_keyword_roundtrip(self):
        """add-keyword → vocab 里多出来 → remove-keyword → vocab 回原状.

        注意: 直接操作真实 vocab. 用 fixture keyword (不影响 seed).
        如 test 中途失败, 用 scripts/screen_tease_vocab_dump.py --remove-keyword 手动清.
        """
        fixture_kw = 'β.5.35A_test_fixture_kw_xyz123'
        cat_id = 'reading_docs'  # 使用 reading_docs 做 fixture (β.5.35-A 引入的)

        # add
        r1 = subprocess.run(
            [sys.executable, CLI_PATH, '--add-keyword', cat_id, fixture_kw],
            capture_output=True, text=True, cwd=ROOT, timeout=30,
            encoding='utf-8', errors='replace',
        )
        try:
            self.assertEqual(r1.returncode, 0, f'add-keyword fail: {r1.stderr}')

            # verify
            with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cat = next((c for c in data['categories'] if c.get('id') == cat_id), None)
            self.assertIsNotNone(cat, f'category {cat_id} 应存在')
            self.assertIn(fixture_kw, cat['keywords'])
        finally:
            # remove (always — 即使 add 失败也清)
            subprocess.run(
                [sys.executable, CLI_PATH, '--remove-keyword', cat_id, fixture_kw],
                capture_output=True, text=True, cwd=ROOT, timeout=30,
                encoding='utf-8', errors='replace',
            )
            # 确认确实 removed
            with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
                data2 = json.load(f)
            cat2 = next((c for c in data2['categories'] if c.get('id') == cat_id), None)
            if cat2 is not None:
                self.assertNotIn(fixture_kw, cat2['keywords'],
                    f'remove-keyword 后 fixture {fixture_kw} 必须不在 vocab')


class TestBeta535AMtimeCacheBehavior(unittest.TestCase):
    """_load_screen_tease_vocab mtime cache: 文件改 → 缓存 invalidate."""

    def test_returns_active_categories(self):
        """直接调 helper 应该返回 active categories list."""
        # SmartNudgeSentinel 需要构造 — 但 helper 只依赖 self._screen_tease_vocab_path
        # 因此可 monkey-patch 构造一个 minimal 实例
        from jarvis_smart_nudge import SmartNudgeSentinel
        # SmartNudge __init__ 需要 jarvis_worker arg, 直接用 None (helper 不依赖)
        # 但 __init__ super().__init__ 是 threading.Thread, 可用 Mock
        from unittest.mock import MagicMock
        nudge = SmartNudgeSentinel(MagicMock())
        cats = nudge._load_screen_tease_vocab()
        self.assertIsInstance(cats, list)
        self.assertGreater(len(cats), 0, '至少应该有 1 个 active category (seed)')
        # 每个 cat 含必备字段
        for c in cats:
            self.assertIn('id', c)
            self.assertIn('keywords', c)


if __name__ == '__main__':
    unittest.main()
