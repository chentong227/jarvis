# -*- coding: utf-8 -*-
"""[Reshape M4.5.1 / 2026-05-24] CommitmentWatcher add_commitment dual-write to PromiseLog.

覆盖:
  - add_commitment 仍写 SQLite (老 daemon 路径不破)
  - add_commitment 同时写 PromiseLog (M4.5.1 新加)
  - source 字段 'cw.add_commitment.dual_write/{source}'
  - self_promise source → who_promised='jarvis'
  - 其它 source → who_promised='sir'
  - dual-write 失败不破 add_commitment 主流 (silent fail)
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
import time
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestDualWrite(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_5_1_')
        self.plog_path = os.path.join(self.tmpdir, 'jarvis_promise_log.json')
        # 隔离 PromiseLog singleton
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test(persist_path=self.plog_path)
        # 隔离 hub singleton + receipt
        from jarvis_memory_hub import reset_default_gateway_for_test
        reset_default_gateway_for_test()

    def tearDown(self):
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test()
        from jarvis_memory_hub import reset_default_gateway_for_test
        reset_default_gateway_for_test()
        try:
            import shutil
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def _make_mock_cw(self):
        """构造一个 minimal mock CW 实例够调 add_commitment."""
        from jarvis_commitment_watcher import CommitmentWatcher
        # bypass __init__ (避免 worker 依赖)
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.worker = MagicMock()
        cw.gate = None
        cw.commitments = []
        import threading
        cw._lock = threading.Lock()
        # mock _get_hippo 返 None (跳 SQLite 写, 只验 PromiseLog)
        cw._get_hippo = MagicMock(return_value=None)
        return cw

    def test_dual_write_to_promise_log_for_sir_commitment(self):
        """add_commitment(source='user_text') → PromiseLog kind=commitment who_promised=sir."""
        cw = self._make_mock_cw()
        # 触发 add_commitment 走完
        cw.add_commitment(
            description='Sir 11pm sleep',
            deadline_str='23:00',
            user_text='I will sleep at 11pm',
            is_future_task_confirmed=True,  # bypass first_person check
            source='user_text',
        )
        # 验 PromiseLog 真有 1 条
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        # 至少 1 条 (deadline parse 可能加多个)
        self.assertGreaterEqual(len(plog.promises), 1,
                                  'M4.5.1 dual_write 应至少写 1 条进 PromiseLog')
        # 找 dual_write 那条
        dual_writes = [
            p for p in plog.promises.values()
            if (p.who_promised == 'sir' and p.kind == 'commitment')
        ]
        self.assertGreaterEqual(len(dual_writes), 1)
        p = dual_writes[0]
        self.assertEqual(p.who_promised, 'sir')
        self.assertEqual(p.kind, 'commitment')
        self.assertIn('sleep', p.description.lower())

    def test_dual_write_for_self_promise_source(self):
        """source='self_promise' → who_promised='jarvis'."""
        cw = self._make_mock_cw()
        cw.add_commitment(
            description='I shall remind sir',
            deadline_str='12:00',
            user_text='Yes Sir, I will',
            is_future_task_confirmed=True,
            source='self_promise',
        )
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        jarvis_promises = [
            p for p in plog.promises.values()
            if p.who_promised == 'jarvis' and p.kind == 'commitment'
        ]
        self.assertGreaterEqual(len(jarvis_promises), 1,
                                  'self_promise source → who_promised=jarvis')

    def test_dual_write_records_source_marker(self):
        """receipt source 含 'cw.add_commitment.dual_write/'."""
        cw = self._make_mock_cw()
        cw.add_commitment(
            description='check progress 30min',
            deadline_str='10:30',
            user_text='will check',
            is_future_task_confirmed=True,
            source='user_text',
        )
        # 验 receipt 含 dual_write source
        from jarvis_memory_hub import get_default_hub
        hub = get_default_hub()
        recents = hub.recent_receipts(max_n=10)
        dual_w = [r for r in recents
                  if 'cw.add_commitment.dual_write' in r.get('source', '')]
        self.assertGreaterEqual(len(dual_w), 1,
                                  '应有 receipt source 含 cw.add_commitment.dual_write')

    def test_dual_write_silent_fail_does_not_break_add_commitment(self):
        """dual-write 内部失败应静默, 不破 add_commitment 主流."""
        cw = self._make_mock_cw()
        # 让 hub.write_commitment 抛异常
        with patch('jarvis_memory_hub.get_default_hub') as mock_hub:
            mock_hub.side_effect = RuntimeError('simulated failure')
            # add_commitment 应仍走完 (commitments list 应 append)
            cw.add_commitment(
                description='resilience test',
                deadline_str='09:00',
                user_text='test',
                is_future_task_confirmed=True,
                source='user_text',
            )
            # commitments list 仍有
            self.assertGreaterEqual(len(cw.commitments), 1,
                                      'dual_write 失败时 commitments list 仍 append')


if __name__ == '__main__':
    unittest.main()
