# -*- coding: utf-8 -*-
"""[P0+20-β.2.8.5 / 2026-05-17] PromiseExecutionLog — Jarvis 承诺生命周期账本

Sir 22:25 痛点: "贾维斯说话能不能和行为一致这个事情让我很困扰". 任何 Jarvis
表态都要有 evidence 配对, 否则就是说而不做.
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPromiseExecutionLog(unittest.TestCase):
    def setUp(self):
        from jarvis_promise_log import PromiseExecutionLog, reset_default_log_for_test
        reset_default_log_for_test()
        self._tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self._tmp.close()
        os.remove(self._tmp.name)
        self.log = PromiseExecutionLog(persist_path=self._tmp.name)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except Exception:
            pass

    def test_register_returns_id_and_persists(self):
        pid = self.log.register(
            description='I shall update my keyrouter status',
            kind='soft',
            jarvis_reply='I shall update my status accordingly.',
        )
        self.assertTrue(pid.startswith('p_'))
        self.assertEqual(len(self.log.list_pending()), 1)
        self.assertTrue(os.path.exists(self._tmp.name))

    def test_mark_fulfilled_changes_state(self):
        pid = self.log.register('update status', kind='soft')
        ok = self.log.mark_fulfilled(pid, 'tool:key_router.check',
                                       'key_router check returned 3 green')
        self.assertTrue(ok)
        p = self.log.get(pid)
        self.assertEqual(p.state, 'fulfilled')
        self.assertEqual(len(p.evidence), 1)
        self.assertGreater(p.fulfilled_at, 0)

    def test_mark_overdue(self):
        pid = self.log.register('rest at 22:00', kind='hard',
                                  deadline_str='22:00')
        ok = self.log.mark_overdue(pid)
        self.assertTrue(ok)
        self.assertEqual(self.log.get(pid).state, 'overdue')

    def test_mark_cancelled(self):
        pid = self.log.register('x', kind='soft')
        ok = self.log.mark_cancelled(pid, reason='Sir said skip it')
        self.assertTrue(ok)
        self.assertEqual(self.log.get(pid).state, 'cancelled')

    def test_double_fulfill_rejected(self):
        pid = self.log.register('x', kind='soft')
        self.assertTrue(self.log.mark_fulfilled(pid, 'k1', 'w1'))
        self.assertFalse(self.log.mark_fulfilled(pid, 'k2', 'w2'))

    def test_sweep_untracked_old_no_evidence(self):
        from jarvis_promise_log import UNTRACKED_AFTER_HOURS
        pid_old = self.log.register('old promise', kind='soft')
        p = self.log.get(pid_old)
        p.registered_at = time.time() - (UNTRACKED_AFTER_HOURS + 1) * 3600
        pid_recent = self.log.register('recent', kind='soft')
        pid_with_ev = self.log.register('old with ev', kind='soft')
        p_we = self.log.get(pid_with_ev)
        p_we.registered_at = time.time() - (UNTRACKED_AFTER_HOURS + 1) * 3600
        p_we.add_evidence('manual', 'sir touched')
        n = self.log.sweep_untracked()
        self.assertEqual(n, 1)
        self.assertEqual(self.log.get(pid_old).state, 'untracked')
        self.assertEqual(self.log.get(pid_recent).state, 'pending')
        self.assertEqual(self.log.get(pid_with_ev).state, 'pending')

    def test_find_pending_matching_by_keyword(self):
        pid = self.log.register('check keyrouter health and update status',
                                  kind='soft')
        p = self.log.find_pending_matching(['keyrouter', 'status'])
        self.assertIsNotNone(p)
        self.assertEqual(p.id, pid)
        p2 = self.log.find_pending_matching(['banana', 'unicorn'])
        self.assertIsNone(p2)

    def test_find_pending_skips_fulfilled(self):
        pid = self.log.register('check keyrouter', kind='soft')
        self.log.mark_fulfilled(pid, 'tool', 'done')
        p = self.log.find_pending_matching(['keyrouter'])
        self.assertIsNone(p)

    def test_stats_breakdown(self):
        self.log.register('p1', kind='soft')
        pid2 = self.log.register('p2', kind='hard', deadline_str='22:00')
        self.log.mark_fulfilled(pid2, 't', 'w')
        stats = self.log.stats()
        self.assertEqual(stats['total'], 2)
        self.assertEqual(stats['states']['pending'], 1)
        self.assertEqual(stats['states']['fulfilled'], 1)
        self.assertEqual(stats['kinds']['soft'], 1)
        self.assertEqual(stats['kinds']['hard'], 1)


class TestTryPairEvidence(unittest.TestCase):
    def setUp(self):
        from jarvis_promise_log import reset_default_log_for_test
        self._tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self._tmp.close()
        os.remove(self._tmp.name)
        reset_default_log_for_test(persist_path=self._tmp.name)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except Exception:
            pass

    def test_pair_matches_pending_with_keyword(self):
        from jarvis_promise_log import get_default_log, try_pair_evidence
        log = get_default_log()
        pid = log.register('I will check keyrouter health', kind='soft')
        matched = try_pair_evidence(
            evidence_kind='tool:key_router.check',
            evidence_what='key_router status: 3 keys healthy',
        )
        self.assertEqual(matched, pid)
        self.assertEqual(log.get(pid).state, 'fulfilled')

    def test_pair_no_match_returns_none(self):
        from jarvis_promise_log import get_default_log, try_pair_evidence
        log = get_default_log()
        log.register('I will check hydration', kind='soft')
        matched = try_pair_evidence('tool:other.unrelated', 'banana smoothie')
        self.assertIsNone(matched)

    def test_pair_skips_too_old(self):
        from jarvis_promise_log import get_default_log, try_pair_evidence
        log = get_default_log()
        pid = log.register('I will check keyrouter', kind='soft')
        log.get(pid).registered_at = time.time() - 1200  # 20min ago
        matched = try_pair_evidence(
            'tool:k.c', 'keyrouter ok', max_match_age_s=600.0)
        self.assertIsNone(matched)


class TestSelfPromiseIntegration(unittest.TestCase):
    """SelfPromiseDetector → PromiseExecutionLog 端到端集成"""

    def setUp(self):
        from jarvis_promise_log import reset_default_log_for_test
        self._tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self._tmp.close()
        os.remove(self._tmp.name)
        reset_default_log_for_test(persist_path=self._tmp.name)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except Exception:
            pass

    def test_self_promise_registers_to_log(self):
        from jarvis_self_promise import SelfPromiseDetector
        from jarvis_promise_log import get_default_log
        from unittest.mock import MagicMock
        det = SelfPromiseDetector()
        cw = MagicMock()
        cw.add_commitment.return_value = True
        det.detect_and_register(
            "I will remind you at 22:00 to take a break.",
            commitment_watcher=cw,
            turn_id='turn_test_001',
        )
        log = get_default_log()
        self.assertGreaterEqual(len(log.promises), 1)


class TestSir2239RegressionContextMatch(unittest.TestCase):
    """[β.2.8.5 hotfix] Sir 22:39 实测: promise.description 字面没 sleep 关键词
    但 jarvis_reply 整段含 sleep / curfew → 应能匹配上 sleep_streak nudge evidence."""

    def setUp(self):
        from jarvis_promise_log import reset_default_log_for_test
        self._tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self._tmp.close()
        os.remove(self._tmp.name)
        reset_default_log_for_test(persist_path=self._tmp.name)

    def tearDown(self):
        try:
            os.remove(self._tmp.name)
        except Exception:
            pass

    def test_context_keyword_in_reply_matches_evidence(self):
        from jarvis_promise_log import get_default_log, try_pair_evidence
        log = get_default_log()
        pid = log.register(
            description='I shall adjust my monitoring accordingly',
            jarvis_reply=(
                'My apologies, Sir. I referenced 23:00 because of our conversation '
                'last night, where you corrected your earlier 21:00 target to a '
                '"midnight deadline," specifically aiming for 23:30. Given your '
                'current statement about wanting to sleep early tonight, I extrapolated '
                'that to the nearest hour mark on your schedule. If you intend to retire '
                'even earlier than that, I shall adjust my monitoring accordingly.'
            ),
        )
        matched = try_pair_evidence(
            evidence_kind='proactive_care_nudge',
            evidence_what='actively raised concern sir_sleep_streak: Sir late nights / cervical health',
        )
        self.assertEqual(matched, pid)
        self.assertEqual(log.get(pid).state, 'fulfilled')

    def test_pure_description_only_match_still_works(self):
        """回归: 当 description 自身就含 keyword 时, 仍正确匹配 (老路径不破坏)."""
        from jarvis_promise_log import get_default_log, try_pair_evidence
        log = get_default_log()
        pid = log.register(
            description='I will check the keyrouter health and report back',
            jarvis_reply='(short reply)',
        )
        matched = try_pair_evidence(
            evidence_kind='tool:key_router.report',
            evidence_what='keyrouter probe returned 3 green',
        )
        self.assertEqual(matched, pid)


class TestSweepDaemon(unittest.TestCase):
    def test_singleton_start(self):
        from jarvis_promise_log import ensure_sweep_daemon_started, _SWEEP_DAEMON
        ensure_sweep_daemon_started()
        # 再次调用不应崩
        ensure_sweep_daemon_started()


if __name__ == '__main__':
    unittest.main(verbosity=2)
