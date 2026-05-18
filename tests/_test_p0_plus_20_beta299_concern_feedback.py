# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.9 / 2026-05-18] ProactiveCare concern 动态权重反馈骨架 testcase

Sir 10:43 反馈:
  "贾维斯能不能通过后续承诺的执行来显式提高或降低这件事的关心度?
   不仅睡眠, 后面贾维斯关心别的事情也会这样动态影响权重?"

设计 (准则 6 通用机制, 不针对特定 concern 硬编码):
  ProactiveCare 发 nudge 时记 last_nudge_concern_id + last_any_nudge_ts.
  Sir 在 120s 内回应 → notify_sir_response_post_nudge(text):
    通用 vocab 判正面 → severity -= 0.1 + 衰减 fatigue
    通用 vocab 判负面 → fatigue +1 (severity 不动)
    中性 → 仅记 signal (让 L4 reflector 看)

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta299_concern_feedback.py
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestResponseClassification(unittest.TestCase):
    """_classify_response 通用 vocab 判正/负/中性"""

    def setUp(self):
        from jarvis_proactive_care import ProactiveCareEngine
        self.cls = ProactiveCareEngine

    # === 正面 ===
    def test_zh_ok_positive(self):
        self.assertEqual(self.cls._classify_response('好的'), 'positive')

    def test_zh_will_do_positive(self):
        self.assertEqual(self.cls._classify_response('我会去做'), 'positive')

    def test_zh_now_go_positive(self):
        self.assertEqual(self.cls._classify_response('马上现在去'), 'positive')

    def test_en_sure_positive(self):
        self.assertEqual(self.cls._classify_response('sure thing'), 'positive')

    def test_en_will_do_positive(self):
        self.assertEqual(self.cls._classify_response("I'll get on it"), 'positive')

    # === 负面 ===
    def test_zh_dont_pester_negative(self):
        self.assertEqual(self.cls._classify_response('别催了'), 'negative')

    def test_zh_forget_it_negative(self):
        self.assertEqual(self.cls._classify_response('算了不要了'), 'negative')

    def test_en_no_negative(self):
        self.assertEqual(self.cls._classify_response('no thanks'), 'negative')

    def test_en_knock_it_off(self):
        self.assertEqual(self.cls._classify_response('knock it off'), 'negative')

    # === 边界: '不会做' 含 '会做' 正面词, 但应判负 ===
    def test_negation_overrides_positive(self):
        # '我不去' 含 '我' 但 '不' 应判负
        self.assertEqual(self.cls._classify_response('我不去'), 'negative')

    # === 中性 ===
    def test_neutral_unrelated(self):
        self.assertEqual(self.cls._classify_response('你看到我的眼镜了吗'), 'neutral')

    def test_empty_is_neutral(self):
        self.assertEqual(self.cls._classify_response(''), 'neutral')


class TestNotifySirResponsePostNudge(unittest.TestCase):
    """notify_sir_response_post_nudge — 完整反馈流程"""

    def setUp(self):
        from jarvis_proactive_care import (
            ProactiveCareEngine, reset_default_engine_for_test
        )
        # 清环境 + reset 单例
        for k in ('JARVIS_PROACTIVE_CARE_DRY_RUN',
                  'JARVIS_PROACTIVE_CARE_LIVE'):
            os.environ.pop(k, None)
        reset_default_engine_for_test()

        worker = MagicMock()
        self.engine = ProactiveCareEngine(worker, None)
        # Mock ledger
        self.mock_ledger = MagicMock()
        self.engine.ledger = self.mock_ledger

    def test_no_recent_nudge_returns_none(self):
        """没发过 nudge → 返 None"""
        self.engine.last_nudge_concern_id = ''
        self.engine.last_any_nudge_ts = 0
        result = self.engine.notify_sir_response_post_nudge('好的')
        self.assertIsNone(result)
        self.mock_ledger.record_signal.assert_not_called()

    def test_too_late_returns_none(self):
        """nudge 5min 前发的, 超 120s 窗口 → 返 None"""
        self.engine.last_nudge_concern_id = 'sir_sleep_streak'
        self.engine.last_any_nudge_ts = time.time() - 300
        result = self.engine.notify_sir_response_post_nudge('好的')
        self.assertIsNone(result)

    def test_positive_response_lowers_severity(self):
        """Sir nudge 后 60s 说 '好的会去' → severity -= 0.1"""
        self.engine.last_nudge_concern_id = 'sir_sleep_streak'
        self.engine.last_any_nudge_ts = time.time() - 60
        result = self.engine.notify_sir_response_post_nudge('好的我会去睡')
        self.assertEqual(result, 'positive')
        # 验证 record_signal 被调 + severity_delta=-0.1
        self.mock_ledger.record_signal.assert_called_once()
        args, kwargs = self.mock_ledger.record_signal.call_args
        # 调用形式 record_signal(cid, what, severity_delta=...)
        self.assertEqual(args[0], 'sir_sleep_streak')
        self.assertEqual(kwargs.get('severity_delta'), -0.1)

    def test_negative_response_increases_fatigue(self):
        """Sir 说 '别催了' → fatigue +1"""
        self.engine.last_nudge_concern_id = 'sir_hydration_habit'
        self.engine.last_any_nudge_ts = time.time() - 30
        before_fatigue = self.engine.fatigue_map.get('sir_hydration_habit', 0)
        result = self.engine.notify_sir_response_post_nudge('别催了')
        self.assertEqual(result, 'negative')
        after = self.engine.fatigue_map.get('sir_hydration_habit', 0)
        self.assertEqual(after - before_fatigue, 1)
        # severity_delta 应该是 0 (不主动降)
        args, kwargs = self.mock_ledger.record_signal.call_args
        self.assertEqual(kwargs.get('severity_delta'), 0)

    def test_neutral_response_records_signal_no_severity_change(self):
        """Sir 说无关话 → 记 signal 但不动 severity"""
        self.engine.last_nudge_concern_id = 'sir_cursor_payment'
        self.engine.last_any_nudge_ts = time.time() - 10
        result = self.engine.notify_sir_response_post_nudge('我的眼镜在哪?')
        self.assertEqual(result, 'neutral')
        self.mock_ledger.record_signal.assert_called_once()
        args, kwargs = self.mock_ledger.record_signal.call_args
        self.assertEqual(kwargs.get('severity_delta'), 0)


class TestPostNudgeGeneric(unittest.TestCase):
    """通用性: 不针对 sleep 硬编码, 任何 concern 都生效 (Sir 准则 6)"""

    def setUp(self):
        from jarvis_proactive_care import (
            ProactiveCareEngine, reset_default_engine_for_test
        )
        for k in ('JARVIS_PROACTIVE_CARE_DRY_RUN',
                  'JARVIS_PROACTIVE_CARE_LIVE'):
            os.environ.pop(k, None)
        reset_default_engine_for_test()
        self.engine = ProactiveCareEngine(MagicMock(), None)
        self.engine.ledger = MagicMock()

    def test_works_for_arbitrary_concern_id(self):
        """新加的 concern (任意 id) 都应能通过这套机制"""
        for cid in ('sir_new_hobby', 'jarvis_self_learning', 'sir_xyz_random'):
            self.engine.last_nudge_concern_id = cid
            self.engine.last_any_nudge_ts = time.time() - 30
            r = self.engine.notify_sir_response_post_nudge('好的我会做')
            self.assertEqual(r, 'positive',
                              f'concern {cid} 应通用响应正面判')


if __name__ == '__main__':
    unittest.main(verbosity=2)
