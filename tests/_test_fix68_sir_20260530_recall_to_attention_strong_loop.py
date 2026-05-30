# -*- coding: utf-8 -*-
"""[Self-Memory P3 / Sir 2026-05-30] 强闭环 — 召回 mutate 门控态 回归.

emergence doc §3: 弱闭环 = 注入文字指望 LLM 注意; 强闭环 = 后果 mutate 那个会 gate
下一步的结构化态. P3: 主动召回 (<RECALL>) 命中的 OPEN 线程 → salience 结构性 bump
+ 刷 last_touched + re-tier hot → 在 open-threads 视图里浮到顶 → 思考脑下 tick
注意力被结构性导向 resurfaced 线程 (因果闭合, 非装饰性 append).

测试覆盖:
  P3A bump: open 线程命中召回 → salience +bump + hot; closed/let_go 不动; 无命中不动
  P3B open-threads view: 按 decayed salience 排, 排除 closed/let_go, 空 → ''
  P3C 门控显形: 召回 bump 让 stale 线程浮到 open-threads 顶 (resurface)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon(
        key_router=MagicMock(), concerns_ledger=None,
        relational_state=None, central_nerve=None,
    )
    d.key_router = None
    return d


def _isolate(daemon, tmpdir):
    daemon._SELF_THREADS_PATH = os.path.join(tmpdir, 'self_threads.json')


class TestP3ABump(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)
        now = time.time()
        self.daemon._save_self_threads({'threads': [
            {'thread_id': 't_open', 'summary': "the deploy bug keeps failing",
             'status': 'open', 'salience': 0.5, 'tier': 'warm',
             'last_touched_ts': now - 3 * 86400, 'occurrences': 3},
            {'thread_id': 't_closed', 'summary': "deploy pipeline migration",
             'status': 'closed', 'salience': 0.5, 'tier': 'cold',
             'last_touched_ts': now - 3 * 86400, 'occurrences': 2},
            {'thread_id': 't_other', 'summary': "unrelated grocery topic",
             'status': 'open', 'salience': 0.5, 'tier': 'warm',
             'last_touched_ts': now - 3 * 86400, 'occurrences': 2},
        ]})

    def test_open_match_bumped(self):
        n = self.daemon._bump_recalled_open_threads('deploy bug')
        self.assertEqual(n, 1, "只 open 且命中的 t_open 该 bump")
        data = self.daemon._load_self_threads()
        byid = {t['thread_id']: t for t in data['threads']}
        self.assertAlmostEqual(byid['t_open']['salience'], 0.58, delta=0.001)
        self.assertEqual(byid['t_open']['tier'], 'hot')
        # closed 不动 (尊重遗忘)
        self.assertEqual(byid['t_closed']['salience'], 0.5)
        self.assertEqual(byid['t_closed']['tier'], 'cold')
        # 无关 open 不动
        self.assertEqual(byid['t_other']['salience'], 0.5)

    def test_no_match_no_bump(self):
        n = self.daemon._bump_recalled_open_threads('quantum chromodynamics')
        self.assertEqual(n, 0)


class TestP3BOpenThreadsView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_empty_returns_empty(self):
        self.daemon._save_self_threads({'threads': []})
        self.assertEqual(self.daemon._build_open_threads_block(3), '')

    def test_sorted_and_excludes_non_open(self):
        self.daemon._save_self_threads({'threads': [
            {'thread_id': 't_low', 'summary': "LOWSAL marker thread",
             'status': 'open', 'salience_decayed': 0.2, 'tier': 'warm',
             'occurrences': 1},
            {'thread_id': 't_high', 'summary': "HIGHSAL marker thread",
             'status': 'open', 'salience_decayed': 0.9, 'tier': 'hot',
             'occurrences': 4},
            {'thread_id': 't_letgo', 'summary': "LETGO marker thread",
             'status': 'let_go', 'salience_decayed': 0.99, 'tier': 'cold',
             'occurrences': 9},
        ]})
        block = self.daemon._build_open_threads_block(5)
        self.assertIn('HIGHSAL', block)
        self.assertIn('LOWSAL', block)
        self.assertNotIn('LETGO', block, "let_go 不该出现在 OPEN THREADS 视图")
        # 高 salience 排在低之前
        self.assertLess(block.index('HIGHSAL'), block.index('LOWSAL'))


class TestP3CGatingManifest(unittest.TestCase):
    """召回 bump 让 stale 线程 resurface 到 open-threads 顶 (强闭环门控显形)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)
        now = time.time()
        self.daemon._save_self_threads({'threads': [
            # stale: 高 raw salience 但久未碰 → decayed 很低 → 初始排底
            {'thread_id': 't_stale', 'summary': "STALE the database migration plan",
             'status': 'open', 'salience': 0.7, 'salience_decayed': 0.05,
             'tier': 'cold', 'last_touched_ts': now - 20 * 86400,
             'occurrences': 4},
            # recent: 中 salience 刚碰 → decayed 中 → 初始排顶
            {'thread_id': 't_recent', 'summary': "RECENT some current chatter",
             'status': 'open', 'salience': 0.4, 'salience_decayed': 0.4,
             'tier': 'hot', 'last_touched_ts': now - 60, 'occurrences': 2},
        ]})

    def test_recall_resurfaces_stale_thread(self):
        block_before = self.daemon._build_open_threads_block(5)
        self.assertLess(block_before.index('RECENT'),
                        block_before.index('STALE'),
                        "初始: recent 在 stale 之前")
        # 主动召回命中 stale 线程 → bump (last_touched=now → decayed 跳回 ~full)
        bumped = self.daemon._bump_recalled_open_threads('database migration')
        self.assertEqual(bumped, 1)
        block_after = self.daemon._build_open_threads_block(5)
        self.assertLess(block_after.index('STALE'),
                        block_after.index('RECENT'),
                        "召回后: stale resurface 到顶 (强闭环 gate 下 tick 注意力)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
