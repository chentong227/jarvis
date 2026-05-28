# -*- coding: utf-8 -*-
"""[fix29 / Sir 2026-05-28 15:46 real-screen] reminder ack 期间 Sir 已回 BUG.

真实场景 (2026-05-28 15:40 Sir 复习面试):
  - 15:40:28 ChronosTick _speak_mail() 启 (blocking stream_chat 10s+)
  - 15:40:31 Sir 已回 "好的好的, 谢谢你" (last_user_speech_time=15:40:31)
  - 15:40:38 _speak_mail return → _pending_reminders[id]['last_spoke']=15:40:38
  - 下次 tick: _user_responded_since(15:40:38) → 15:40:31>15:40:38=FALSE
  - 错过 ack → 3 min 后 escalate tier 2 (SECOND attempt)
  - Sir 不耐 "不要再催了" 才 consume

修法 (jarvis_sentinels.py:429-441):
  speak_start_ts = time.time() BEFORE _speak_mail()
  last_spoke = speak_start_ts (not after _speak_mail done)

测试 (3 个):
  L1 BUG 复现 (老逻辑 last_spoke=_speak_mail 后, Sir 在期间回 → 应 consume 却 escalate)
  L2 修后行为: last_spoke=speak 前, Sir 期间回 → consume ✓
  L3 修后行为: Sir 真 silent (last_user_speech_time < speak_start_ts) → 老 tier=1 → 3 min 后 escalate (不破坏 escalation 逻辑)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_chronos():
    """构造 ChronosTick 但 stub掉 daemon thread + Jarvis dep."""
    from jarvis_sentinels import ChronosTick

    jarvis = MagicMock()
    jarvis._pending_reminders = {}
    jarvis.voice_thread = MagicMock()
    jarvis.voice_thread.last_user_speech_time = 0.0
    jarvis.hippocampus = MagicMock()
    jarvis.hippocampus.consume_reminder = MagicMock()
    jarvis.short_term_memory = []

    # 旁路 Thread.__init__ + super.__init__
    ct = ChronosTick.__new__(ChronosTick)
    ct.jarvis = jarvis
    ct.mailbox = MagicMock()
    ct.chat_bypass = MagicMock()
    ct.ui_callback = MagicMock()
    return ct, jarvis


# ==========================================================================
# L1: BUG 复现 — 老逻辑 last_spoke=_speak_mail 后 → 漏 ack
# ==========================================================================
class TestL1BugRepro(unittest.TestCase):
    def test_old_last_spoke_after_speak_misses_ack(self):
        """复现 老 bug: last_spoke = _speak_mail 后 ts (Sir 在期间回 → 漏)."""
        ct, jarvis = _make_chronos()
        speak_start = 1000.0
        sir_reply_during = speak_start + 2.0  # Sir 在 speak 期间回 (1002)
        speak_done = speak_start + 10.0  # _speak_mail 完成 (1010)

        # 老 buggy 逻辑: last_spoke 用 _speak_mail 完成后 ts
        jarvis._pending_reminders[2289] = {
            'tier': 1,
            'last_spoke': speak_done,  # ← 老 BUG: 用 _speak_mail 后 ts
            'intent': 'Resume interview preparation',
            'trigger_time': speak_start,
        }
        jarvis.voice_thread.last_user_speech_time = sir_reply_during  # 1002

        # patch time.time() 到 _speak_mail 后 5s
        now_after = speak_done + 5.0
        import jarvis_sentinels as _sent
        old_time = _sent.time.time
        _sent.time.time = lambda: now_after
        try:
            ct._check_escalations()
        finally:
            _sent.time.time = old_time

        # BUG 表现: consume_reminder 未调, reminder 仍 pending
        jarvis.hippocampus.consume_reminder.assert_not_called()
        self.assertIn(2289, jarvis._pending_reminders)


# ==========================================================================
# L2: 修后行为 — last_spoke=speak 前 → Sir 期间回 consume ✓
# ==========================================================================
class TestL2FixedBehavior(unittest.TestCase):
    def test_fix_uses_speak_start_ts_so_consume(self):
        """修后: last_spoke = _speak_mail 开始 ts, Sir 期间回 → consume."""
        ct, jarvis = _make_chronos()
        speak_start = 1000.0
        sir_reply_during = speak_start + 2.0  # 1002

        # 修后: last_spoke = speak_start_ts (BEFORE _speak_mail)
        jarvis._pending_reminders[2289] = {
            'tier': 1,
            'last_spoke': speak_start,  # ← 修法: 用 speak 前 ts
            'intent': 'Resume interview preparation',
            'trigger_time': speak_start,
        }
        jarvis.voice_thread.last_user_speech_time = sir_reply_during

        now_after = speak_start + 15.0
        import jarvis_sentinels as _sent
        old_time = _sent.time.time
        _sent.time.time = lambda: now_after
        try:
            ct._check_escalations()
        finally:
            _sent.time.time = old_time

        # 修后: consume_reminder 调一次, reminder 出 pending
        jarvis.hippocampus.consume_reminder.assert_called_once_with(2289)
        self.assertNotIn(2289, jarvis._pending_reminders)


# ==========================================================================
# L3: escalation 逻辑不破 — Sir 真 silent → 仍 escalate
# ==========================================================================
class TestL3EscalationStillWorks(unittest.TestCase):
    def test_silent_sir_still_escalates_after_180s(self):
        """Sir 真没回 (last_user_speech_time < last_spoke) → 180s 后 escalate."""
        ct, jarvis = _make_chronos()
        speak_start = 1000.0

        jarvis._pending_reminders[2289] = {
            'tier': 1,
            'last_spoke': speak_start,
            'intent': 'Resume interview preparation',
            'trigger_time': speak_start,
        }
        # Sir 在 reminder 之前说过话 (但之后没)
        jarvis.voice_thread.last_user_speech_time = speak_start - 100.0  # 900

        now_after = speak_start + 181.0  # > 180s
        import jarvis_sentinels as _sent
        old_time = _sent.time.time
        _sent.time.time = lambda: now_after
        # mock _escalate_reminder 看是否调
        ct._escalate_reminder = MagicMock()
        try:
            ct._check_escalations()
        finally:
            _sent.time.time = old_time

        # 不 consume, escalate 到 tier 2
        jarvis.hippocampus.consume_reminder.assert_not_called()
        ct._escalate_reminder.assert_called_once()
        args, _ = ct._escalate_reminder.call_args
        self.assertEqual(args[0], 2289)
        self.assertEqual(args[2], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
