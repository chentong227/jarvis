# -*- coding: utf-8 -*-
"""[Self-Memory P2 / Sir 2026-05-30] 河床/巩固 (consolidation) + 遗忘 回归.

Sir 真意: "连续存在差什么? 河在流但没结河床." 流水账 (心流 jsonl) 越长但"自我"
不变深. P2 治本: 把同 thread_id 的 thought 卷成持久线程 (running summary +
last_touched + salience + status + 回链 evidence), 遗忘 = salience 衰减 +
hot/warm/cold 分层 (不删除).

测试覆盖:
  P2A store: load/save roundtrip (隔离 temp path)
  P2B consolidate: thought 按 thread 卷成线程 (>= min_thoughts), 取最高 sal 摘要
  P2C 遗忘: tier (hot/warm/cold) + salience 半衰期衰减
  P2D recall_threads: 关键词重叠召回, 带 tier 标
  P2E cooldown: _maybe_consolidate_threads 周期 throttle
  P2F CLI: scripts/self_threads_dump.py importable + 基本命令
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=None,
    )
    # key_router=None → 巩固走 extractive 摘要 (不调 LLM, 测试确定性)
    d.key_router = None
    return d


def _isolate(daemon, tmpdir):
    daemon._SELF_THREADS_PATH = os.path.join(tmpdir, 'self_threads.json')


def _mk_thought(tid, idx, sal, text, ts):
    return types.SimpleNamespace(
        id=f"{tid}_{idx}", thread_id=tid, salience=sal,
        thought=text, ts=ts, category='B',
    )


class TestP2AStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_load_missing_empty(self):
        self.assertEqual(self.daemon._load_self_threads().get('threads'), [])

    def test_save_load_roundtrip(self):
        data = {'threads': [{'thread_id': 't1', 'summary': 'hello'}]}
        self.assertTrue(self.daemon._save_self_threads(data))
        got = self.daemon._load_self_threads()
        self.assertEqual(len(got['threads']), 1)
        self.assertEqual(got['threads'][0]['thread_id'], 't1')


class TestP2BConsolidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_thoughts_roll_into_threads(self):
        now = time.time()
        self.daemon._thoughts = [
            _mk_thought('thr_A', 1, 0.4, "Sir keeps toggling windows", now - 300),
            _mk_thought('thr_A', 2, 0.8, "Sir's window toggling looks like fatigue", now - 100),
            _mk_thought('thr_B', 1, 0.5, "the deploy bug is still open", now - 200),
            # thr_C 只 1 条 → < min_thoughts(2) → 不巩固
            _mk_thought('thr_C', 1, 0.9, "one-off thought", now - 50),
        ]
        n = self.daemon._consolidate_threads_once()
        # thr_A 有 2 条 (>= min 2) → 巩固; thr_B / thr_C 各 1 条 (< min) → 跳过.
        self.assertEqual(n, 1, "只 thr_A 有 >= 2 thought, 应只 1 个线程")
        data = self.daemon._load_self_threads()
        ids = [t['thread_id'] for t in data['threads']]
        self.assertIn('thr_A', ids)
        self.assertNotIn('thr_C', ids)
        thr_a = [t for t in data['threads'] if t['thread_id'] == 'thr_A'][0]
        self.assertEqual(thr_a['occurrences'], 2)
        self.assertEqual(thr_a['salience'], 0.8)
        # extractive 摘要 = 最高 sal thought text
        self.assertIn('fatigue', thr_a['summary'])
        self.assertEqual(thr_a['status'], 'open')
        self.assertTrue(thr_a['evidence_thought_ids'])

    def test_existing_thread_updated_not_duplicated(self):
        now = time.time()
        self.daemon._thoughts = [
            _mk_thought('thr_X', 1, 0.5, "first", now - 400),
            _mk_thought('thr_X', 2, 0.6, "second", now - 300),
        ]
        self.daemon._consolidate_threads_once()
        # 再加一条 → 重新巩固, 应 update 同 thread 不新增
        self.daemon._thoughts.append(
            _mk_thought('thr_X', 3, 0.7, "third newer", now - 50))
        self.daemon._consolidate_threads_once()
        data = self.daemon._load_self_threads()
        xs = [t for t in data['threads'] if t['thread_id'] == 'thr_X']
        self.assertEqual(len(xs), 1, "同 thread 不该重复")
        self.assertEqual(xs[0]['occurrences'], 3)


class TestP2CForgetting(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_tier_by_age(self):
        now = time.time()
        vocab = {'thread_tier_hot_max_age_s': 86400,
                 'thread_tier_warm_max_age_s': 604800}
        hot = {'last_touched_ts': now - 100}
        warm = {'last_touched_ts': now - 2 * 86400}
        cold = {'last_touched_ts': now - 10 * 86400}
        self.assertEqual(self.daemon._compute_thread_tier(hot, now, vocab), 'hot')
        self.assertEqual(self.daemon._compute_thread_tier(warm, now, vocab), 'warm')
        self.assertEqual(self.daemon._compute_thread_tier(cold, now, vocab), 'cold')

    def test_let_go_is_cold(self):
        now = time.time()
        vocab = {'thread_tier_hot_max_age_s': 86400,
                 'thread_tier_warm_max_age_s': 604800}
        th = {'last_touched_ts': now, 'status': 'let_go'}
        self.assertEqual(self.daemon._compute_thread_tier(th, now, vocab), 'cold')

    def test_salience_decay(self):
        now = time.time()
        # 1 个半衰期 (7d) 后 ≈ 0.5
        d = self.daemon._decayed_salience(1.0, now - 7 * 86400, now, 7.0)
        self.assertAlmostEqual(d, 0.5, delta=0.05)
        # 刚碰过 → 几乎不衰减
        d2 = self.daemon._decayed_salience(0.8, now - 60, now, 7.0)
        self.assertAlmostEqual(d2, 0.8, delta=0.01)


class TestP2DRecallThreads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)
        self.daemon._save_self_threads({'threads': [
            {'thread_id': 't_cat', 'summary': "Sir's cat Mochi has a vet appointment Friday",
             'tier': 'warm', 'occurrences': 3, 'salience': 0.7, 'salience_decayed': 0.5},
            {'thread_id': 't_deploy', 'summary': "the staging deploy bug keeps recurring",
             'tier': 'hot', 'occurrences': 5, 'salience': 0.8, 'salience_decayed': 0.8},
        ]})

    def test_keyword_overlap_recall(self):
        hits = self.daemon.recall_threads('what about the cat vet thing', top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['source'], 'THREAD')
        self.assertIn('Mochi', hits[0]['content'])
        self.assertIn('warm', hits[0]['content'])

    def test_no_overlap_empty(self):
        hits = self.daemon.recall_threads('quantum chromodynamics', top_k=3)
        self.assertEqual(hits, [])

    def test_recall_includes_threads(self):
        """recall() (no nerve) 也应纳入 threads 河床召回."""
        self.daemon.nerve = None
        out = self.daemon.recall('deploy bug', top_k=4)
        self.assertTrue(any(h['source'] == 'THREAD' for h in out))


class TestP2ECooldown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_cooldown_blocks_repeat(self):
        now = time.time()
        self.daemon._thoughts = [
            _mk_thought('thr_Q', 1, 0.5, "a", now - 100),
            _mk_thought('thr_Q', 2, 0.6, "b", now - 50),
        ]
        # 第一次跑
        self.daemon._last_consolidate_ts = 0.0
        self.daemon._maybe_consolidate_threads()
        self.assertTrue(os.path.exists(self.daemon._SELF_THREADS_PATH))
        # 删文件 + 立即再调 → cooldown 内, 不该重新生成
        os.remove(self.daemon._SELF_THREADS_PATH)
        self.daemon._maybe_consolidate_threads()
        self.assertFalse(os.path.exists(self.daemon._SELF_THREADS_PATH),
            "cooldown 内不该重跑巩固")


class TestP2FCLI(unittest.TestCase):
    def test_cli_importable_and_runs(self):
        import importlib
        mod = importlib.import_module('scripts.self_threads_dump')
        self.assertTrue(hasattr(mod, 'main'))
        # --tiers 在空河床上不崩
        rc = mod.main(['--tiers'])
        self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
