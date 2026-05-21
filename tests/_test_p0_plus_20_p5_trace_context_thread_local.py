# -*- coding: utf-8 -*-
"""[Gap-Z6 / β.5.46-fix7 / 2026-05-21 23:50] TraceContext 跨线程修复测试.

daemon thread 应能 capture turn_id, log 始终归属正确 turn — 不被主 thread 影响.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_utils import TraceContext


class TestThreadLocalTurn(unittest.TestCase):

    def setUp(self):
        TraceContext.init_session()

    def test_global_get_returns_main_turn(self):
        TraceContext.new_turn()
        tid = TraceContext.get_turn_id()
        self.assertTrue(tid.startswith('turn_'))

    def test_push_pop_returns_to_global(self):
        global_tid = TraceContext.new_turn()
        token = TraceContext.push_turn_id_for_thread('turn_thread_X')
        try:
            self.assertEqual(TraceContext.get_turn_id(), 'turn_thread_X')
        finally:
            TraceContext.pop_turn_id_for_thread(token)
        # 还原后应回到 global
        self.assertEqual(TraceContext.get_turn_id(), global_tid)

    def test_main_new_turn_does_not_affect_daemon(self):
        """daemon push 后, 主 thread 切 turn — daemon 仍看 captured."""
        main_tid_before = TraceContext.new_turn()
        captured_in_daemon = []

        def _daemon_work():
            with TraceContext.captured_turn('turn_daemon_X'):
                # 启动期间主 thread 切了 turn
                time.sleep(0.05)
                captured_in_daemon.append(TraceContext.get_turn_id())

        t = threading.Thread(target=_daemon_work, daemon=True)
        t.start()
        # 主 thread 切到新 turn
        time.sleep(0.01)
        main_tid_after = TraceContext.new_turn()
        self.assertNotEqual(main_tid_before, main_tid_after)
        t.join()
        # daemon 看到的应是它自己 captured 的, 不是主 thread 新 turn
        self.assertEqual(captured_in_daemon[0], 'turn_daemon_X',
                         'daemon thread 应看 captured turn, 不被主 thread 切影响')

    def test_two_daemons_isolated(self):
        """两个 daemon 各自 capture, 互不干扰."""
        TraceContext.new_turn()
        results = {}

        def _daemon_a():
            with TraceContext.captured_turn('turn_A'):
                time.sleep(0.05)
                results['a'] = TraceContext.get_turn_id()

        def _daemon_b():
            with TraceContext.captured_turn('turn_B'):
                time.sleep(0.05)
                results['b'] = TraceContext.get_turn_id()

        ta = threading.Thread(target=_daemon_a, daemon=True)
        tb = threading.Thread(target=_daemon_b, daemon=True)
        ta.start()
        tb.start()
        ta.join()
        tb.join()
        self.assertEqual(results.get('a'), 'turn_A')
        self.assertEqual(results.get('b'), 'turn_B')

    def test_log_prefix_uses_captured_turn(self):
        """get_log_prefix 在 daemon 中应反映 captured turn_id."""
        TraceContext.new_turn()
        results = []

        def _daemon():
            with TraceContext.captured_turn('turn_log_test'):
                time.sleep(0.02)
                results.append(TraceContext.get_log_prefix())

        t = threading.Thread(target=_daemon, daemon=True)
        t.start()
        t.join()
        self.assertTrue(results, 'daemon should run')
        self.assertIn('turn_log_test', results[0],
                       'log prefix 应含 captured turn_id')

    def test_get_global_turn_id_ignores_contextvar(self):
        """get_global_turn_id 总返主 thread, 忽略 ContextVar."""
        global_tid = TraceContext.new_turn()
        with TraceContext.captured_turn('turn_xyz'):
            # 当前 ContextVar 是 turn_xyz, 但 global_get 应返 global_tid
            self.assertEqual(TraceContext.get_global_turn_id(), global_tid)


if __name__ == '__main__':
    unittest.main()
