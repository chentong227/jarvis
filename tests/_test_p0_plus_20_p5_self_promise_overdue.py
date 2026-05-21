# -*- coding: utf-8 -*-
"""[P5-fixCB-revise / 2026-05-21 11:55] Self-Promise Overdue → 合法 surface (b).

Sir 11:30 真理 (b) 通道: Jarvis 自己发现承诺没履行 → 主动 admit.
PromiseLog.sweep_untracked 转 STATE_UNTRACKED 时 publish 'self_promise_overdue' SWM,
主脑下轮 [SELF-PROMISE OVERDUE] block 显 → 主动 surface.

Cover:
  A. PromiseLog.sweep_untracked 转 UNTRACKED 时 publish event (per-promise)
  B. central_nerve _assemble_prompt 含 [SELF-PROMISE OVERDUE] block 渲染逻辑
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_SweepPublishesOverdue(unittest.TestCase):
    """sweep_untracked 转 UNTRACKED 时 publish 'self_promise_overdue' per-promise."""

    def _build_log_with_old_pending(self):
        """构造一个 PromiseExecutionLog 含 25h 老 pending."""
        import jarvis_promise_log as _pl
        log = _pl.PromiseExecutionLog(persist_path='_test_promise_log_overdue.json')
        # register 一个 promise, registered_at 改成 25h 前
        pid = log.register(
            description='I will keep an eye on the hydration logs',
            kind='soft',
            deadline_str='',
            jarvis_reply='I will keep an eye on the hydration logs.',
            turn_id='turn_old',
            lang='en',
        )
        # mutate registered_at 直接 to 25h ago
        with log._lock:
            p = log.promises.get(pid)
            self.assertIsNotNone(p)
            p.registered_at = time.time() - 25 * 3600.0
            p.evidence = []  # 无 evidence
        return log, pid

    def tearDown(self):
        try:
            os.remove('_test_promise_log_overdue.json')
        except Exception:
            pass

    def test_sweep_publishes_per_promise_event(self):
        log, pid = self._build_log_with_old_pending()
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus') as _mock_geb:
            _mock_geb.return_value = mock_bus
            n = log.sweep_untracked()
        self.assertEqual(n, 1)
        # SWM publish was called for this promise
        self.assertTrue(mock_bus.publish.called)
        kwargs = mock_bus.publish.call_args.kwargs
        self.assertEqual(kwargs['etype'], 'self_promise_overdue')
        self.assertIn('PromiseLog', kwargs['source'])
        meta = kwargs.get('metadata') or {}
        self.assertEqual(meta.get('promise_id'), pid)
        self.assertIn('hydration', meta.get('description', ''))
        self.assertGreaterEqual(meta.get('age_hours', 0), 24)

    def test_sweep_no_event_when_no_old_pending(self):
        import jarvis_promise_log as _pl
        log = _pl.PromiseExecutionLog(persist_path='_test_promise_log_fresh.json')
        log.register(description='I will check soon', kind='soft', jarvis_reply='I will check soon')
        # promise 是新的, 不该 untracked
        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus') as _mock_geb:
            _mock_geb.return_value = mock_bus
            n = log.sweep_untracked()
        self.assertEqual(n, 0)
        self.assertFalse(mock_bus.publish.called)
        try:
            os.remove('_test_promise_log_fresh.json')
        except Exception:
            pass


class TestB_StaticBlockWired(unittest.TestCase):
    """central_nerve _assemble_prompt 真接入 [SELF-PROMISE OVERDUE] block."""

    def test_central_nerve_renders_self_promise_overdue_block(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # block header
        self.assertIn('SELF-PROMISE OVERDUE', src)
        # event type
        self.assertIn("'self_promise_overdue'", src)
        # 教如何 surface
        self.assertIn('自然 inline admit', src)
        # de-dup by promise_id
        self.assertIn('_seen_pids', src)


if __name__ == '__main__':
    unittest.main()
