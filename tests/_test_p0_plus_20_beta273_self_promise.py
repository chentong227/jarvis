# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.3 / 2026-05-17] SelfPromiseDetector 单测

详 docs/JARVIS_SOUL_UNIVERSALIZATION.md / β.2.7.3 修法。

目标：让 Jarvis 自己说"我会监督您 13:05"也能被注册成 commitment + 定时 nudge，
与 Sir 的承诺平等。
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 🩹 [β.2.9.7 / 2026-05-18] Sir 09:06 实测痛点: prod promise_log.json 被本测试
# 污染 (30+ "我会监督您 13:05" 残留) → InconsistencyWatcher 反复 fire.
# 修: module-level isolate — 把 default log 切到临时文件, 测试期间不写 prod.
_ISOLATED_LOG_PATH = None


def setUpModule():
    global _ISOLATED_LOG_PATH
    _tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False, encoding='utf-8')
    _tmp.write('{}\n')
    _tmp.close()
    _ISOLATED_LOG_PATH = _tmp.name
    from jarvis_promise_log import reset_default_log_for_test
    reset_default_log_for_test(persist_path=_ISOLATED_LOG_PATH)


def tearDownModule():
    from jarvis_promise_log import reset_default_log_for_test
    reset_default_log_for_test()  # 恢复无单例, prod 路径首次调用时 lazy 建
    try:
        if _ISOLATED_LOG_PATH and os.path.exists(_ISOLATED_LOG_PATH):
            os.remove(_ISOLATED_LOG_PATH)
    except Exception:
        pass


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

    def test_no_time_no_hard_promise_but_soft_caught(self):
        """🩹 [β.2.7.8] 无时间锚 → 不再算 0 promises, 而是算 soft promise"""
        reply = "好的，先生。我会留意您的睡眠。"  # 没具体时间
        promises = self.det.detect(reply)
        # soft promise 路径捕获
        self.assertGreater(len(promises), 0)
        self.assertEqual(promises[0]['kind'], 'soft')
        self.assertEqual(promises[0]['deadline_str'], '')

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
        # 用 .jarvis = None 避免 soft promise fallback 误匹配
        self.cw.jarvis = None
        self.cw.worker = None
        self.cw.central_nerve = None
        reply = "I shall remind you at 23:00."
        result = self.det.detect_and_register(reply, commitment_watcher=self.cw)
        # 检测到了 hard 但注册失败, 应不 raise + registered=0
        self.assertEqual(result['registered'], 0)
        self.assertGreater(result['detected'], 0)


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
# C2. [β.2.7.8] Soft Promise (无时间锚 ongoing intent)
# ============================================================
class TestSoftPromise(unittest.TestCase):

    def setUp(self):
        from jarvis_self_promise import SelfPromiseDetector
        self.det = SelfPromiseDetector()

    def test_en_soft_will_integrate_reminders(self):
        """治 Sir 18:46 实测: 'I will integrate reminders into our dialogue and issue
        proactive prompts' — 无时间锚 → soft"""
        reply = ("Understood, Sir. I will integrate reminders into our dialogue and "
                 "issue proactive prompts when necessary to ensure you don't neglect "
                 "your hydration intake.")
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)
        soft = [p for p in promises if p.get('kind') == 'soft']
        self.assertGreater(len(soft), 0, "应识别为 soft promise (无时间锚)")
        # description 含 integrate reminders 或 issue proactive
        joined = ' '.join(p['description'].lower() for p in soft)
        self.assertTrue(
            'integrate reminders' in joined or 'issue proactive' in joined,
            f"soft promise desc 应含 ongoing intent: {soft}"
        )

    def test_zh_soft_keep_watch(self):
        """中文 soft: '我会留意您的睡眠' (无具体时间)"""
        reply = "好的，先生。我会留意您的睡眠，主动提醒您休息。"
        promises = self.det.detect(reply)
        self.assertGreater(len(promises), 0)
        soft = [p for p in promises if p.get('kind') == 'soft']
        self.assertGreater(len(soft), 0)
        for p in soft:
            self.assertEqual(p['deadline_str'], '')

    def test_hard_promise_marks_kind_hard(self):
        """hard promise 应被标 kind='hard'"""
        promises = self.det.detect("I shall remind you at 23:00.")
        hards = [p for p in promises if p.get('kind') == 'hard']
        self.assertGreater(len(hards), 0)

    def test_soft_dedup_with_hard(self):
        """同 reply 既有 hard 又有 soft 时 dedup (避免双计)"""
        promises = self.det.detect("I shall remind you at 23:00.")
        # 不应同时含 hard 和 soft 同句 (hard remind you at 23:00 vs soft remind)
        kinds = [p.get('kind') for p in promises]
        # 至少 1 个，且不重复同 description
        self.assertEqual(len(promises), len(set(p['description'][:30] for p in promises)))

    def test_soft_writes_to_matching_concern_notes(self):
        """soft promise 找匹配 concern 写 notes_for_self + 升 severity"""
        from jarvis_self_promise import SelfPromiseDetector
        from jarvis_concerns import Concern, ConcernsLedger, STATE_ACTIVE
        import tempfile, os as _os
        tmpdir = tempfile.mkdtemp()
        ledger = ConcernsLedger(persist_path=_os.path.join(tmpdir, 'c.json'),
                                 review_path=_os.path.join(tmpdir, 'r.json'))
        # 注册 hydration concern
        hyd = Concern(
            id='sir_hydration_habit', what_i_watch='hydration target 3L',
            why_i_care='health', severity=0.5, state=STATE_ACTIVE,
        )
        ledger.register(hyd)

        cw = MagicMock()
        # 让 detector 通过 cw.jarvis.concerns_ledger 找到 ledger
        cw.jarvis = MagicMock()
        cw.jarvis.concerns_ledger = ledger

        det = SelfPromiseDetector()
        reply = "Understood, Sir. I will integrate reminders for your hydration intake."
        result = det.detect_and_register(reply, commitment_watcher=cw, turn_id='t1')

        # 验证 soft 被注册
        self.assertGreater(result['registered'], 0)
        # 验证 notes_for_self 被写入
        c = ledger.get('sir_hydration_habit')
        self.assertIsNotNone(c)
        self.assertIn('β.2.7.8', c.notes_for_self or '')
        # severity 升了 0.05
        self.assertAlmostEqual(c.severity, 0.55, places=2)


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
