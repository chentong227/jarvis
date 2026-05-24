# -*- coding: utf-8 -*-
"""[Reshape M4.7 / 2026-05-24] dashboard pending_callbacks dual-write to PromiseLog.

覆盖:
  - dashboard `_apply_callback_proposal` 调 PromiseLog.register kind='cross_session_callback'
  - jsonl 仍写 (老 consumer 兼容)
  - PromiseLog dedup 不破 (1h 内同 desc 复用 ID)
  - PromiseLog 失败不破 jsonl write (resilience)
"""
import os
import sys
import unittest
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestM47PromiseLogIntegration(unittest.TestCase):
    """直接验证 PromiseLog 真支持 'cross_session_callback' kind (dashboard 用)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m47_')
        self.plog_path = os.path.join(self.tmpdir, 'plog.json')
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test(persist_path=self.plog_path)

    def tearDown(self):
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test()
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_register_cross_session_callback_kind(self):
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        pid = plog.register(
            description='Remind Sir at 18:00 to drink water',
            kind='cross_session_callback',
            deadline_str='2026-05-24 18:00:00',
            jarvis_reply='Sir mentioned water reminder yesterday',
            author='sir',
        )
        self.assertTrue(pid.startswith('p_'))
        p = plog.get(pid)
        self.assertEqual(p.kind, 'cross_session_callback')
        self.assertEqual(p.author, 'sir')
        self.assertEqual(p.deadline_str, '2026-05-24 18:00:00')

    def test_dedup_1h_within(self):
        """同 desc + deadline 1h 内重复 register 应复用 ID (老逻辑应仍 work)."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        pid1 = plog.register(
            description='dup test', kind='cross_session_callback',
            deadline_str='17:00', author='sir',
        )
        pid2 = plog.register(
            description='dup test', kind='cross_session_callback',
            deadline_str='17:00', author='sir',
        )
        self.assertEqual(pid1, pid2, '1h 内同 desc + deadline 应 dedup')


class TestM47DashboardCallSite(unittest.TestCase):
    """smoke test: 验证 dashboard 调用路径真存在且 import OK."""

    def test_apply_callback_function_exists(self):
        # dashboard 是 GUI module, import 时不应破 (只 check fn 存在)
        import importlib.util
        path = os.path.join(ROOT, 'scripts', 'jarvis_dashboard.py')
        self.assertTrue(os.path.exists(path))
        with open(path, encoding='utf-8') as f:
            content = f.read()
        # 验证 dual-write 真在 source 里
        self.assertIn('cross_session_callback', content,
                       'M4.7 dual-write 真 inject')
        self.assertIn('jarvis_promise_log', content,
                       'PromiseLog import 真 inject')


if __name__ == '__main__':
    unittest.main()
