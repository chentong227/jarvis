# -*- coding: utf-8 -*-
"""[Reshape M4.5.3 / 2026-05-24] CW _dual_mark_fired helper — daemon nudge 后
同步标 SQLite + PromiseLog evidence.

覆盖:
  - _dual_mark_fired 既调 SQLite mark_commitment_nudged 也加 PromiseLog evidence
  - 没 promise_id 时只走 SQLite (老 commitment 不破)
  - 没 db_id 时只走 PromiseLog (新 commitment 来源)
  - SQLite or PromiseLog 任一失败不破另一路 (准则 1 高效)
"""
import os
import sys
import tempfile
import unittest
import threading
import time
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Voice:
    last_user_speech_time = 0.0
    in_active_conversation = False


class _Worker:
    def __init__(self):
        self.is_active_task = False
        self.companion_center = None
        self.voice_thread = _Voice()
        self.jarvis = None
        self.hippocampus = None  # 子 test 内 set


def _make_cw():
    from jarvis_commitment_watcher import CommitmentWatcher
    cw = CommitmentWatcher.__new__(CommitmentWatcher)
    cw.worker = _Worker()
    cw.gate = None
    cw.commitments = []
    cw._lock = threading.Lock()
    return cw


class TestDualMarkFired(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_5_3_')
        self.plog_path = os.path.join(self.tmpdir, 'plog.json')
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test(persist_path=self.plog_path)

    def tearDown(self):
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test()
        try:
            import shutil
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_with_promise_id_adds_evidence(self):
        """有 promise_id → PromiseLog 加 evidence."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        future_iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                     time.localtime(time.time() + 3600))
        pid = plog.register(description='test commit',
                              kind='commitment',
                              deadline_str=future_iso, author='sir')
        cw = _make_cw()
        c = {'description': 'test commit', 'deadline_ts': time.time() + 3600,
             'promise_id': pid, 'db_id': 0}
        cw._dual_mark_fired(c)
        # PromiseLog 真有 cw_nudge_fired evidence
        p = plog.get(pid)
        self.assertIsNotNone(p)
        kinds = [e.get('kind') for e in p.evidence]
        self.assertIn('cw_nudge_fired', kinds)

    def test_without_promise_id_no_promise_log_write(self):
        """没 promise_id (老 SQLite-only commitment) → PromiseLog 不动."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        cw = _make_cw()
        c = {'description': 'old commit', 'db_id': 0,
             'deadline_ts': time.time() + 3600}
        size_before = len(plog.promises)
        cw._dual_mark_fired(c)
        size_after = len(plog.promises)
        self.assertEqual(size_before, size_after,
                          '没 promise_id 不应在 PromiseLog 创新条')

    def test_with_db_id_calls_sqlite_mark(self):
        """有 db_id 调 hippo.mark_commitment_nudged."""
        cw = _make_cw()
        mock_hippo = MagicMock()
        cw._get_hippo = MagicMock(return_value=mock_hippo)
        c = {'description': 'x', 'db_id': 42}
        cw._dual_mark_fired(c)
        mock_hippo.mark_commitment_nudged.assert_called_once_with(42)

    def test_promise_log_failure_does_not_break_sqlite(self):
        """PromiseLog 失败不破 SQLite mark."""
        cw = _make_cw()
        mock_hippo = MagicMock()
        cw._get_hippo = MagicMock(return_value=mock_hippo)
        c = {'description': 'x', 'db_id': 7, 'promise_id': 'p_invalid'}
        # promise_id 'p_invalid' 不存在, add_evidence_only 应静默返 False
        cw._dual_mark_fired(c)
        # SQLite mark 仍调
        mock_hippo.mark_commitment_nudged.assert_called_once_with(7)

    def test_sqlite_failure_does_not_break_promise_log(self):
        """SQLite 失败不破 PromiseLog evidence."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        future_iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                     time.localtime(time.time() + 3600))
        pid = plog.register(description='resilience',
                              kind='commitment', deadline_str=future_iso,
                              author='sir')
        cw = _make_cw()
        # _get_hippo 抛异常
        cw._get_hippo = MagicMock(side_effect=RuntimeError('sim'))
        c = {'description': 'resilience', 'db_id': 99, 'promise_id': pid}
        cw._dual_mark_fired(c)
        # PromiseLog 仍 add_evidence
        p = plog.get(pid)
        kinds = [e.get('kind') for e in p.evidence]
        self.assertIn('cw_nudge_fired', kinds)


if __name__ == '__main__':
    unittest.main()
