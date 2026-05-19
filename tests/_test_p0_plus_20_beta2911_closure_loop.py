# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.11 / 2026-05-18] 灵魂闭环 A — 关心-承诺-履约-反馈

Sir 10:43 + 12:35 灵魂级要求:
  "贾维斯关心 → 我承诺 → 履约/违约 → 动态影响关心值"
  "扩展到其他能力 (不止睡眠) 和其他模块 (不止 concern)"

通用化 (准则 6 vocab 驱动, 不针对 sleep 硬编码):
  1. infer_concern_link — 复用 ConcernsReflector CONCERN_KEYWORDS 反查
     任何新 concern 加 keyword → 此函数自动支持, 0 改动
  2. infer_expected_behavior — vocab 表驱动 4 类:
     idle_min (sleep/rest) / stm_contains (任务) / process_exit (剪完视频) / 未来扩展
  3. CommitmentWatcher tick 加 _backfill_concern_link + _check_fulfillment + _on_fulfillment
  4. PromiseLog 配对 evidence (Sir 兑现 → Jarvis 言出必行的证据)

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta2911_closure_loop.py
"""
import os
import sys
import time
import unittest
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 🩹 [β.5.18 / 2026-05-19] β.4.9 把 severity_delta 改成 vocab-driven (jarvis_safety
# _load_severity_delta + memory_pool/severity_vocab.json per_concern 覆盖). 老
# β.2.9.11 testcase 期硬编码 -0.2/+0.1 默认值, vocab 现在覆盖到 -0.25/+0.05.
# 用 setUpModule mock _load_severity_delta 返默认让单元测试独立于 vocab 配置.
_severity_delta_patch = None


def setUpModule():
    global _severity_delta_patch
    def _default_delta(cid, verdict):
        return -0.20 if verdict == 'fulfilled' else 0.10
    _severity_delta_patch = patch(
        'jarvis_safety._load_severity_delta', side_effect=_default_delta)
    _severity_delta_patch.start()


def tearDownModule():
    global _severity_delta_patch
    if _severity_delta_patch is not None:
        _severity_delta_patch.stop()
        _severity_delta_patch = None


class TestInferConcernLink(unittest.TestCase):
    """infer_concern_link 通用 — 复用 reflector vocab 反查"""

    def setUp(self):
        from jarvis_commitment_watcher import infer_concern_link
        self.infer = infer_concern_link

    def test_sleep_links_to_sleep_streak(self):
        self.assertEqual(self.infer('我11点睡觉'), 'sir_sleep_streak')
        self.assertEqual(self.infer('I will go to bed at 23'), 'sir_sleep_streak')

    def test_hydration_links(self):
        cid = self.infer('我去喝水')
        self.assertEqual(cid, 'sir_hydration_habit')

    def test_unknown_returns_none(self):
        # 完全无关词
        self.assertIsNone(self.infer('天气真好'))
        self.assertIsNone(self.infer(''))

    def test_works_for_any_concern_added_to_reflector(self):
        """通用性: 任意新 concern 在 reflector CONCERN_KEYWORDS 加 keyword
        都应该自动被 infer 反查 (准则 6 vocab 驱动)."""
        from jarvis_soul_reflector import CONCERN_KEYWORDS
        # 抽 reflector 第一个 concern 的第一个 keyword 测
        for cid, kw_list in CONCERN_KEYWORDS.items():
            if kw_list:
                kw = kw_list[0][0]
                found = self.infer(f'我 {kw} 了')
                self.assertEqual(
                    found, cid,
                    f"infer 必须能反查任意 reflector concern '{cid}' "
                    f"的 keyword '{kw}'"
                )
                break


class TestInferExpectedBehavior(unittest.TestCase):
    """infer_expected_behavior vocab 表驱动"""

    def setUp(self):
        from jarvis_commitment_watcher import infer_expected_behavior
        self.infer = infer_expected_behavior

    def test_sleep_infers_idle_30min(self):
        eb = self.infer('我11点睡觉')
        self.assertEqual(eb['kind'], 'idle_min')
        self.assertEqual(eb['threshold'], 30)

    def test_break_infers_idle_5min(self):
        eb = self.infer('我去歇会儿')
        self.assertEqual(eb['kind'], 'idle_min')
        self.assertEqual(eb['threshold'], 5)

    def test_task_infers_stm_contains(self):
        eb = self.infer('我去刷题')
        self.assertEqual(eb['kind'], 'stm_contains')
        self.assertIn('完成', eb['kws'])

    def test_irrelevant_returns_none(self):
        self.assertIsNone(self.infer('随便聊聊'))


class TestFulfillmentDetection(unittest.TestCase):
    """_check_fulfillment 通用 4 类验证"""

    def setUp(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        self.cw = CommitmentWatcher.__new__(CommitmentWatcher)
        self.cw.worker = MagicMock()
        self.cw.worker.short_term_memory = []

    def test_idle_min_fulfilled(self):
        c = {'expected_behavior': {'kind': 'idle_min', 'threshold': 5},
             'description': 'sleep'}
        # mock win32api 返 idle 10min
        import jarvis_commitment_watcher as cwmod
        if cwmod.win32api is None:
            self.skipTest('win32api unavailable')
        with patch.object(cwmod.win32api, 'GetTickCount', return_value=10*60*1000), \
             patch.object(cwmod.win32api, 'GetLastInputInfo', return_value=0):
            verdict = self.cw._check_fulfillment(c, time.time())
        self.assertEqual(verdict, 'fulfilled')

    def test_idle_min_broken(self):
        c = {'expected_behavior': {'kind': 'idle_min', 'threshold': 30},
             'description': 'sleep'}
        import jarvis_commitment_watcher as cwmod
        if cwmod.win32api is None:
            self.skipTest('win32api unavailable')
        with patch.object(cwmod.win32api, 'GetTickCount', return_value=60*1000), \
             patch.object(cwmod.win32api, 'GetLastInputInfo', return_value=0):
            verdict = self.cw._check_fulfillment(c, time.time())
        self.assertEqual(verdict, 'broken')

    def test_stm_contains_fulfilled(self):
        c = {'expected_behavior': {'kind': 'stm_contains', 'kws': ['完成']},
             'description': '刷题'}
        self.cw.worker.short_term_memory = [
            {'user': '我把题做完成了', 'jarvis': '好的'},
        ]
        verdict = self.cw._check_fulfillment(c, time.time())
        self.assertEqual(verdict, 'fulfilled')

    def test_stm_contains_broken(self):
        c = {'expected_behavior': {'kind': 'stm_contains', 'kws': ['完成']},
             'description': '刷题'}
        self.cw.worker.short_term_memory = [
            {'user': '在打游戏', 'jarvis': '好的'},
        ]
        verdict = self.cw._check_fulfillment(c, time.time())
        self.assertEqual(verdict, 'broken')

    def test_no_expected_behavior_returns_unknown(self):
        c = {'description': 'something', 'expected_behavior': None}
        self.assertEqual(self.cw._check_fulfillment(c, time.time()), 'unknown')


class TestOnFulfillmentCallsFeedback(unittest.TestCase):
    """_on_fulfillment 调 ledger.record_signal + ProactiveCare.notify"""

    def setUp(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        self.cw = CommitmentWatcher.__new__(CommitmentWatcher)
        self.cw.worker = MagicMock()

    def test_fulfilled_lowers_severity(self):
        c = {'concern_link': 'sir_sleep_streak',
             'description': '我11点睡', 'expected_behavior': {'kind': 'idle_min'}}
        mock_ledger = MagicMock()
        mock_pce = MagicMock()
        with patch('jarvis_concerns.get_default_ledger', return_value=mock_ledger), \
             patch('jarvis_proactive_care.get_default_engine', return_value=mock_pce):
            self.cw._on_fulfillment(c, 'fulfilled')
        # ledger.record_signal 调了 severity_delta=-0.2
        mock_ledger.record_signal.assert_called_once()
        args, kwargs = mock_ledger.record_signal.call_args
        self.assertEqual(args[0], 'sir_sleep_streak')
        self.assertEqual(kwargs.get('severity_delta'), -0.2)
        self.assertIn('兑现', args[1])
        mock_pce.notify_concern_aligned.assert_called_once_with('sir_sleep_streak')

    def test_broken_raises_severity(self):
        c = {'concern_link': 'sir_hydration_habit',
             'description': '我去喝水', 'expected_behavior': {'kind': 'idle_min'}}
        mock_ledger = MagicMock()
        mock_pce = MagicMock()
        with patch('jarvis_concerns.get_default_ledger', return_value=mock_ledger), \
             patch('jarvis_proactive_care.get_default_engine', return_value=mock_pce):
            self.cw._on_fulfillment(c, 'broken')
        args, kwargs = mock_ledger.record_signal.call_args
        self.assertEqual(kwargs.get('severity_delta'), 0.1)
        self.assertIn('违约', args[1])
        mock_pce.notify_concern_rejected.assert_called_once_with('sir_hydration_habit')

    def test_unknown_no_call(self):
        c = {'concern_link': 'sir_x', 'description': 'x'}
        mock_ledger = MagicMock()
        with patch('jarvis_concerns.get_default_ledger', return_value=mock_ledger):
            self.cw._on_fulfillment(c, 'unknown')
        mock_ledger.record_signal.assert_not_called()

    def test_no_concern_link_no_call(self):
        c = {'concern_link': '', 'description': 'x'}
        mock_ledger = MagicMock()
        with patch('jarvis_concerns.get_default_ledger', return_value=mock_ledger):
            self.cw._on_fulfillment(c, 'fulfilled')
        mock_ledger.record_signal.assert_not_called()


class TestAddCommitmentAutoInfer(unittest.TestCase):
    """add_commitment 顶部自动 infer concern_link + expected_behavior"""

    def setUp(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        self.cw = CommitmentWatcher(MagicMock())
        # mock _get_hippo 返回有 add_commitment_row 的 fake
        fake_hippo = MagicMock()
        fake_hippo.add_commitment_row.return_value = 999
        self.cw._get_hippo = lambda: fake_hippo

    def test_sleep_commitment_auto_infers(self):
        self.cw.add_commitment(
            description='我11点睡觉',
            deadline_str='23:00',
            user_text='我11点睡觉',
        )
        self.assertEqual(len(self.cw.commitments), 1)
        c = self.cw.commitments[0]
        self.assertEqual(c['concern_link'], 'sir_sleep_streak')
        self.assertEqual(c['expected_behavior']['kind'], 'idle_min')
        self.assertEqual(c['expected_behavior']['threshold'], 30)

    def test_explicit_caller_value_wins(self):
        """caller 显式传 concern_link / expected_behavior > 自动 infer"""
        self.cw.add_commitment(
            description='我11点睡觉',
            deadline_str='23:00',
            user_text='我11点睡觉',
            concern_link='sir_custom_concern',
            expected_behavior={'kind': 'custom'},
        )
        c = self.cw.commitments[0]
        self.assertEqual(c['concern_link'], 'sir_custom_concern')
        self.assertEqual(c['expected_behavior']['kind'], 'custom')


if __name__ == '__main__':
    unittest.main(verbosity=2)
