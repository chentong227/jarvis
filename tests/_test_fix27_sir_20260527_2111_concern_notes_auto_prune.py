# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 21:11 真测 P3] ConcernsLedger.prune_concern_notes + auto-prune.

Sir 真痛 (真测 log):
  💭 [InnerThought] [C/sal=0.72/state=active/tick=45s] ...
    actionable=adjust_concern_notes:sir_hydration_habit
    → notes_near_cap:485/500 (>=80% — wait for archival or prune before adding)

InnerThought 反复 propose adjust_concern_notes, 但 notes 已满 80%+, 反复被 reject.
治本 (准则 6 三维耦合):
  - ConcernsLedger.prune_concern_notes — archive 老 segments 到 jsonl, 留新 50%
  - _do_adjust_concern_notes — 检测 >=80% → 自动 prune → 继续 append
  - 不丢历史 (老段在 memory_pool/concern_notes_archive.jsonl)

测试:
  1. prune_concern_notes 多 segment → archive 老段 + 留新
  2. prune_concern_notes 单 segment → no-op (smallest > target)
  3. _do_adjust_concern_notes 多 segment 满 80% → auto-prune → append 成功
  4. _do_adjust_concern_notes 单 segment 满 80% → 退回 reject (兼容)
  5. archive jsonl 含完整 segments + ts + cid
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ==========================================================================
# Part A — ConcernsLedger.prune_concern_notes 单元
# ==========================================================================
class TestPruneConcernNotes(unittest.TestCase):

    def _build_ledger_with_notes(self, notes: str):
        from jarvis_concerns import ConcernsLedger, Concern
        tmp_concerns = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp_concerns)
        ledger.register(Concern(
            id='c1',
            what_i_watch='watch x',
            why_i_care='care y',
            severity=0.5,
            notes_for_self=notes,
        ))
        return ledger

    def test_multi_segment_archive_and_keep_new(self):
        """多 segment notes → archive 老段, 留新段."""
        # 模拟 5 个 inner_thought segment, 每个 ~100 char, 总 500 (满 cap)
        segments = [
            f'[inner_thought/A/sal=0.{i}] note number {i} ' + 'x' * 60
            for i in range(5)
        ]
        notes = ' | '.join(segments)
        # 实际 notes 长度可能 > 500, 算下
        self.assertGreater(len(notes), 400, 'setup: notes 必须 > 80% cap')

        ledger = self._build_ledger_with_notes(notes)
        tmp_archive = tempfile.mktemp(suffix='.jsonl')
        try:
            ok, msg, archived_n = ledger.prune_concern_notes(
                'c1', target_chars=250,
                source='test', archive_path=tmp_archive,
            )
            self.assertTrue(ok, f'prune should succeed: {msg}')
            self.assertGreater(archived_n, 0,
                f'should archive at least 1 segment, got {archived_n}, msg={msg}')

            # ledger 现在 ≤ target_chars
            new_notes = ledger.get('c1').notes_for_self
            self.assertLessEqual(len(new_notes), 250,
                f'after prune, notes should be <= 250, got {len(new_notes)}')

            # archive jsonl 含老段
            self.assertTrue(os.path.exists(tmp_archive),
                'archive jsonl should exist after prune')
            with open(tmp_archive, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f if l.strip()]
            self.assertEqual(len(lines), archived_n,
                f'archive lines={len(lines)} != archived_n={archived_n}')
            # 每行是合法 jsonl + 含必要字段
            for line in lines:
                entry = json.loads(line)
                self.assertIn('ts', entry)
                self.assertIn('cid', entry)
                self.assertIn('segment', entry)
                self.assertEqual(entry['cid'], 'c1')
                self.assertEqual(entry['archived_by'], 'test')
                self.assertTrue(entry['segment'].startswith('[inner_thought/'))

            # 保留的是最新 segments (segments[-X:])
            # 检 ledger 含最后一个 segment (segments[-1])
            self.assertIn(segments[-1], new_notes,
                'newest segment must be kept')
        finally:
            if os.path.exists(tmp_archive):
                os.remove(tmp_archive)

    def test_single_segment_noop(self):
        """单 segment 比 target 大 → no-op."""
        ledger = self._build_ledger_with_notes('X' * 450)
        tmp_archive = tempfile.mktemp(suffix='.jsonl')
        try:
            ok, msg, archived_n = ledger.prune_concern_notes(
                'c1', target_chars=250,
                source='test', archive_path=tmp_archive,
            )
            self.assertTrue(ok, f'noop should still return ok: {msg}')
            self.assertEqual(archived_n, 0, 'no archive for single segment')
            # ledger notes 不变
            self.assertEqual(len(ledger.get('c1').notes_for_self), 450)
            # archive jsonl 不该被创建 (or 空)
            if os.path.exists(tmp_archive):
                with open(tmp_archive, 'r', encoding='utf-8') as f:
                    self.assertEqual(f.read().strip(), '')
        finally:
            if os.path.exists(tmp_archive):
                os.remove(tmp_archive)

    def test_already_under_target(self):
        """notes 已 < target → no-op."""
        ledger = self._build_ledger_with_notes('short note')
        ok, msg, archived_n = ledger.prune_concern_notes(
            'c1', target_chars=250, source='test',
        )
        self.assertTrue(ok)
        self.assertEqual(archived_n, 0)
        self.assertIn('no-op', msg)

    def test_concern_not_found(self):
        ledger = self._build_ledger_with_notes('hi')
        ok, msg, archived_n = ledger.prune_concern_notes(
            'nonexistent', target_chars=250,
        )
        self.assertFalse(ok)
        self.assertIn('not found', msg)
        self.assertEqual(archived_n, 0)


# ==========================================================================
# Part B — _do_adjust_concern_notes 自动 prune 端到端
# ==========================================================================
class TestAutoPruneOnAdjust(unittest.TestCase):

    def _build_daemon(self, notes: str):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        from jarvis_concerns import ConcernsLedger, Concern
        tmp = tempfile.mktemp(suffix='.json')
        ledger = ConcernsLedger(persist_path=tmp)
        ledger.register(Concern(
            id='c1',
            what_i_watch='watch x',
            why_i_care='care y',
            severity=0.5,
            notes_for_self=notes,
        ))
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=ledger,
            relational_state=None,
            central_nerve=None,
        )
        return daemon, ledger

    def test_multi_segment_auto_prune_then_append(self):
        """多 segment 满 80% → auto-prune → append 成功."""
        from jarvis_inner_thought_daemon import InnerThought
        # 模拟 6 个 ~80 char segment, 总 ~480 (>80% cap)
        segments = [
            f'[inner_thought/A/sal=0.{i}] watch x reaction noted '
            f'and tracked observation #{i}'
            for i in range(6)
        ]
        notes = ' | '.join(segments)[:495]  # 接近 cap
        self.assertGreater(len(notes), 400, 'setup: notes must be >= 80% cap')

        daemon, ledger = self._build_daemon(notes)
        # patch archive 路径到 tmp
        tmp_archive = tempfile.mktemp(suffix='.jsonl')
        try:
            with patch.object(
                ledger, 'DEFAULT_NOTES_ARCHIVE_PATH', tmp_archive
            ):
                thought = InnerThought(
                    id='th1', ts=time.time(), ts_iso='2026-05-27T21:11',
                    category='C',
                    thought='Sir reaction pattern noticed when watch x',
                    salience=0.8,
                    actionable='adjust_concern_notes:c1:new observation',
                    evidence_link='watch x',
                )
                ok, msg = daemon._do_adjust_concern_notes(
                    thought,
                    'adjust_concern_notes:c1:new observation about watch x',
                )

            self.assertTrue(
                ok,
                f'multi-segment 满 80% 应自动 prune → append 成功, got msg={msg}'
            )
            # ledger 现在含新 segment
            cur = ledger.get('c1').notes_for_self
            self.assertIn('new observation', cur,
                'new segment 应在 ledger 中')
            # ledger 总长 ≤ 500 (cap)
            self.assertLessEqual(len(cur), 500)
            # archive 应有内容
            self.assertTrue(os.path.exists(tmp_archive))
        finally:
            if os.path.exists(tmp_archive):
                os.remove(tmp_archive)

    def test_single_segment_falls_back_to_reject(self):
        """单 segment 满 80% → prune no-op → 退回 reject (兼容老行为).

        note >= 10 char (daemon min_note=10).
        """
        from jarvis_inner_thought_daemon import InnerThought
        daemon, ledger = self._build_daemon('X' * 450)
        thought = InnerThought(
            id='th1', ts=time.time(), ts_iso='2026-05-27T21:11',
            category='C',
            thought='Sir reaction pattern noticed when watch x',
            salience=0.8,
            actionable='adjust_concern_notes:c1:remember to dampen response',
            evidence_link='watch x',
        )
        ok, msg = daemon._do_adjust_concern_notes(
            thought,
            'adjust_concern_notes:c1:remember to dampen response',
        )
        self.assertFalse(ok, 'single-segment prune no-op → 退回 reject')
        self.assertIn('notes_near_cap', msg)


# ==========================================================================
# Part C — 设计文档/字段断言 (准则 6 持久化路径完整)
# ==========================================================================
class TestPathAndApiSurface(unittest.TestCase):

    def test_ledger_has_prune_api(self):
        from jarvis_concerns import ConcernsLedger
        self.assertTrue(hasattr(ledger_cls := ConcernsLedger,
                                'prune_concern_notes'),
                        'ConcernsLedger must expose prune_concern_notes')
        self.assertTrue(hasattr(ledger_cls, 'DEFAULT_NOTES_ARCHIVE_PATH'),
                        'must expose DEFAULT_NOTES_ARCHIVE_PATH constant')

    def test_archive_path_in_memory_pool(self):
        from jarvis_concerns import ConcernsLedger
        path = ConcernsLedger.DEFAULT_NOTES_ARCHIVE_PATH
        # 必须在 memory_pool/ 下 (准则 6 持久化)
        self.assertIn('memory_pool', path.replace('\\', '/'))
        self.assertTrue(path.endswith('.jsonl'),
                        'archive should be jsonl format')


if __name__ == '__main__':
    unittest.main(verbosity=2)
