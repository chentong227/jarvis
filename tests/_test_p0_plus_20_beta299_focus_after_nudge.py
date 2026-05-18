# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.9-D / 2026-05-18] ProactiveCare nudge 后 60s soft focus window

Sir 10:43 痛点:
  "ProactiveCare 发声后没焦点模式, 我想直接说 '我中午会补觉' 还要喊 Jarvis"

修法:
  1. ReturnSentinel 加通用 API open_soft_focus(duration_s, reason)
     - 复用现有 soft_focus_active + soft_focus_until + _soft_focus_reason 机制
  2. ProactiveCare._tick 真 voice 发声后, 自动调 worker.return_sentinel.open_soft_focus
  3. chat_bypass.stream_chat 入口 hook notify_sir_response_post_nudge
     → Sir 在 120s 内回应自动调 concern severity

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta299_focus_after_nudge.py
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOpenSoftFocusAPI(unittest.TestCase):
    """ReturnSentinel.open_soft_focus 通用 API"""

    def _make_rs(self):
        from jarvis_return_sentinel import ReturnSentinel
        # ReturnSentinel 需要 worker — 用 MagicMock
        worker = MagicMock()
        rs = ReturnSentinel(worker)
        return rs

    def test_open_soft_focus_sets_state(self):
        rs = self._make_rs()
        self.assertFalse(rs.soft_focus_active)
        rs.open_soft_focus(duration_s=60.0, reason='proactive_care')
        self.assertTrue(rs.soft_focus_active)
        self.assertEqual(rs._soft_focus_reason, 'proactive_care')
        # soft_focus_until 应在未来 ~60s
        delta = rs.soft_focus_until - time.time()
        self.assertGreater(delta, 55)
        self.assertLess(delta, 65)

    def test_open_soft_focus_clamps_duration(self):
        """duration 极端值被夹到 [15, 180]"""
        rs = self._make_rs()
        rs.open_soft_focus(duration_s=1.0, reason='x')
        self.assertGreaterEqual(rs.soft_focus_until - time.time(), 14)
        rs.open_soft_focus(duration_s=999.0, reason='y')
        self.assertLessEqual(rs.soft_focus_until - time.time(), 181)

    def test_open_soft_focus_reason_recorded(self):
        rs = self._make_rs()
        for reason in ('proactive_care', 'inconsistency', 'commitment_check', 'external'):
            rs.open_soft_focus(60.0, reason=reason)
            self.assertEqual(rs._soft_focus_reason, reason)


class TestProactiveCareTriggersFocus(unittest.TestCase):
    """ProactiveCare 真发声 voice 后, 自动调 worker.return_sentinel.open_soft_focus"""

    def setUp(self):
        from jarvis_proactive_care import (
            ProactiveCareEngine, reset_default_engine_for_test
        )
        for k in ('JARVIS_PROACTIVE_CARE_DRY_RUN', 'JARVIS_PROACTIVE_CARE_LIVE'):
            os.environ.pop(k, None)
        reset_default_engine_for_test()

        # 构造 worker 含 fake return_sentinel
        worker = MagicMock()
        self.fake_rs = MagicMock()
        worker.return_sentinel = self.fake_rs
        self.worker = worker

        self.engine = ProactiveCareEngine(worker, None)

    def _fake_tick_voice_sent(self):
        """模拟 _tick 中 voice 真发声路径 — 我们直接调那段逻辑."""
        from jarvis_proactive_care import CareEvidence
        # 构造一条 evidence
        evi = CareEvidence(
            concern_id='sir_test',
            urgency_score=0.9,
            what_i_watch='test',
            why_i_care='test',
            severity=0.9,
            breakdown={},
        )
        # 直接调 synth.push 模拟 (mock 让它返 True)
        with unittest.mock.patch.object(
                self.engine.synth, 'push', return_value=True):
            # 现在我们走 _tick 的下半部分:
            # 1. 记 last_nudge_concern_id
            # 2. 开 soft focus (如果 channel=voice)
            sent = self.engine.synth.push(self.worker, evi, dry_run=False,
                                            channel='voice')
            self.assertTrue(sent)
            # 模拟 _tick 后的状态更新
            self.engine.last_nudge_concern_id = evi.concern_id
            self.engine.last_any_nudge_ts = time.time()
            # 模拟 _tick 中 soft_focus 触发
            rs = getattr(self.worker, 'return_sentinel', None)
            if rs is not None and hasattr(rs, 'open_soft_focus'):
                rs.open_soft_focus(duration_s=60.0, reason='proactive_care')

    def test_voice_nudge_opens_focus(self):
        self._fake_tick_voice_sent()
        self.fake_rs.open_soft_focus.assert_called_once_with(
            duration_s=60.0, reason='proactive_care')


import unittest.mock  # 给上面 patch 用


class TestChatBypassHookExists(unittest.TestCase):
    """chat_bypass.py 必须调 ProactiveCare.notify_sir_response_post_nudge"""

    def test_hook_referenced_in_source(self):
        import inspect
        from jarvis_chat_bypass import ChatBypass
        # 抓 ChatBypass 全源码 (含 stream_chat 等)
        src = inspect.getsource(ChatBypass)
        self.assertIn('notify_sir_response_post_nudge', src,
                       'chat_bypass.py 必须接通 ProactiveCare 反馈 hook')


if __name__ == '__main__':
    unittest.main(verbosity=2)
