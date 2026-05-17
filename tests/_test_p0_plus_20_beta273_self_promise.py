# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.3 / 2026-05-17] SelfPromiseDetector 单测

详 docs/JARVIS_SOUL_UNIVERSALIZATION.md / β.2.7.3 修法。

目标：让 Jarvis 自己说"我会监督您 13:05"也能被注册成 commitment + 定时 nudge，
与 Sir 的承诺平等。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. detect() 中英双语
# ============================================================
class TestDetectEnglish(unittest.TestCase):

    def setUp(self):
        from jarvis_self_promise import SelfPromiseDetector
        self.det = SelfPromiseDetector()

    def test_hold_you_to_time(self):
        """治 Sir 13:09 实测：'I shall hold you to that 13:05 deadline'"""
        reply = "Noted, Sir. I shall hold you to that 13:05 deadline."
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)
        self.assertIn('13:05', promises[0]['deadline_str'])

    def test_will_remind_at(self):
        reply = "I will remind you at 11pm to wind down."
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)
        self.assertIn('11', promises[0]['deadline_str'].lower())

    def test_ill_check_in_30_minutes(self):
        reply = "I'll check on you in 30 minutes to see how things are going."
        promises = self.det.detect(reply)
        # action 含 "check on you"
        self.assertTrue(any('check' in p['description'].lower() for p in promises))

    def test_question_not_promise(self):
        """反问句不算承诺"""
        reply = "Would you like me to remind you at 11pm?"
        promises = self.det.detect(reply)
        self.assertEqual(len(promises), 0)

    def test_past_tense_not_promise(self):
        """已经做了的过去时不算承诺"""
        reply = "I have already reminded you at 11pm earlier today."
        # 过去式 'I have reminded' 不应触发未来承诺
        # 当前实现可能仍 match 因为 "I will/shall/'ll" 才触发 — past 不会被识为 promise
        promises = self.det.detect(reply)
        self.assertEqual(len(promises), 0)


class TestDetectChinese(unittest.TestCase):

    def setUp(self):
        from jarvis_self_promise import SelfPromiseDetector
        self.det = SelfPromiseDetector()

    def test_supervise_at_time(self):
        """治 Sir 13:09 实测：'我会监督您在 13:05 准时休息'"""
        reply = "好的，先生。我会监督您在 13:05 准时休息。"
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)
        # 应该 match 到"监督"+ "13:05"
        self.assertTrue(any('监督' in p['description'] for p in promises))
        self.assertTrue(any('13:05' in p['deadline_str'] or '13:05' in p['raw_match'] for p in promises))

    def test_remind_at_clock_time(self):
        reply = "我会在 23:30 提醒你休息。"
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)

    def test_will_at_hour(self):
        reply = "我会在 11 点催你睡觉。"
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)
        self.assertTrue(any('11' in p['deadline_str'] or '11' in p['raw_match'] for p in promises))

    def test_no_time_no_promise(self):
        """无时间锚不算承诺"""
        reply = "好的，先生。我会留意您的睡眠。"  # 没具体时间
        promises = self.det.detect(reply)
        self.assertEqual(len(promises), 0)

    def test_past_tense_zh(self):
        reply = "我刚才提醒过您了。"
        promises = self.det.detect(reply)
        self.assertEqual(len(promises), 0)


# ============================================================
# B. detect_and_register + commitment_watcher mock
# ============================================================
class TestDetectAndRegister(unittest.TestCase):

    def setUp(self):
        from jarvis_self_promise import SelfPromiseDetector
        self.det = SelfPromiseDetector()
        self.cw = MagicMock()

    def test_register_calls_add_commitment_with_self_promise_source(self):
        reply = "Noted, Sir. I shall hold you to that 13:05 deadline."
        result = self.det.detect_and_register(reply, commitment_watcher=self.cw, turn_id='t1')
        self.assertGreater(result['registered'], 0)
        self.assertEqual(result['detected'], result['registered'])
        # 验证 add_commitment 被调，source='self_promise'
        self.cw.add_commitment.assert_called()
        call_kwargs = self.cw.add_commitment.call_args.kwargs
        self.assertEqual(call_kwargs.get('source'), 'self_promise')

    def test_no_watcher_returns_no_watcher_skip(self):
        reply = "我会监督您在 13:05 准时休息。"
        result = self.det.detect_and_register(reply, commitment_watcher=None)
        self.assertEqual(result['registered'], 0)
        self.assertEqual(result['skipped_reason'], 'no_watcher')

    def test_empty_reply(self):
        result = self.det.detect_and_register('', commitment_watcher=self.cw)
        self.assertEqual(result['skipped_reason'], 'empty_reply')

    def test_dedup_same_reply_30s(self):
        reply = "我会监督您在 13:05 准时休息。"
        r1 = self.det.detect_and_register(reply, commitment_watcher=self.cw, turn_id='t1')
        r2 = self.det.detect_and_register(reply, commitment_watcher=self.cw, turn_id='t2')
        self.assertGreater(r1['registered'], 0)
        self.assertEqual(r2['skipped_reason'], 'dedup')

    def test_add_commitment_failure_does_not_crash(self):
        self.cw.add_commitment.side_effect = RuntimeError('mock fail')
        reply = "I shall remind you at 23:00."
        result = self.det.detect_and_register(reply, commitment_watcher=self.cw)
        # 检测到了但注册失败，不应该 raise
        self.assertEqual(result['registered'], 0)


class TestDetectAndRegisterAsync(unittest.TestCase):

    def setUp(self):
        from jarvis_self_promise import SelfPromiseDetector
        self.det = SelfPromiseDetector()
        self.cw = MagicMock()

    def test_async_fires_and_returns_thread(self):
        import time
        reply = "我会监督您在 14:00 准时吃饭。"
        thread = self.det.detect_and_register_async(reply, commitment_watcher=self.cw)
        self.assertIsNotNone(thread)
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        # 验证 commitment_watcher 被异步调用
        self.cw.add_commitment.assert_called()


# ============================================================
# C. stats
# ============================================================
class TestStats(unittest.TestCase):

    def test_stats_counters_increment(self):
        from jarvis_self_promise import SelfPromiseDetector
        det = SelfPromiseDetector()
        cw = MagicMock()
        det.detect_and_register("我会在 13:05 提醒你。", commitment_watcher=cw)
        det.detect_and_register("Another reply without promise.", commitment_watcher=cw)
        stats = det.get_stats()
        self.assertGreaterEqual(stats['detected'], 1)
        self.assertGreaterEqual(stats['registered'], 1)


# ============================================================
# D. singleton
# ============================================================
class TestSingleton(unittest.TestCase):

    def test_get_default_returns_same_instance(self):
        from jarvis_self_promise import get_default_detector, reset_default_detector_for_test
        reset_default_detector_for_test()
        a = get_default_detector()
        b = get_default_detector()
        self.assertIs(a, b)


if __name__ == '__main__':
    unittest.main(verbosity=2)
