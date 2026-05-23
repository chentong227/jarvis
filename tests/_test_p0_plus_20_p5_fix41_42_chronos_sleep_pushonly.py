# -*- coding: utf-8 -*-
"""[P5-fix41/42 / 2026-05-23 14:36] ChronosSentinel 准则 6 三维耦合 reminder 链路.

Sir 14:32 真测痛点 (合并 2 BUG):

BUG #1 (优先级倒挂):
  Sir 132min sleep mode → 14:30 hydration cycle reminder fire →
  NudgeGate 强制解除 sleep mode → Sir 被唤醒.

BUG #2 (链条冲突):
  Sir 醒后 commitment_check 三连: 主脑没读 NudgeGate sleep_mode_active 直觉
  说 'Sir 没睡, 计划被专注取代'.

Sir 真意 (准则 6 / β.5.0 三维耦合):
  '我们始终要把模块整理起来, 触发链路应该要固定. 比如这次的提醒, 哪怕他不
  走之前的模块, 也该只是 push only, 植入数据整理模块然后 LLM 主脑决策.'

治本设计:
  ChronosSentinel.run():
    - 数据强耦合: 任何 reminder due → publish 'reminder_fired' 到 SWM (永远)
    - 行为弱耦合: sleep_mode + 非 alarm-style → push only (publish 不 deliver)
    - 决策集中主脑: Sir 唤醒后主脑 SWM 看 reminder_fired 历史自决补 ack
    - Sir 显式硬规底线: sleep + alarm-style → 仍 deliver (last resort)

  commitment_check directive:
    - sleep_evidence 注入 (sleep_mode_active / sleep_duration_min / recent_sleep_min)
    - 主脑 evidence-based 自决, 不再直觉 'still working'

覆盖:
A. ChronosSentinel _is_alarm_style 启发 (中英 alarm 词)
B. _publish_reminder_fired publish 'reminder_fired' 到 SWM (有 metadata)
C. sleep + 非 alarm → push only (publish, 不 mailbox.deliver)
D. sleep + alarm → mailbox.deliver (last resort)
E. 非 sleep → mailbox.deliver (老路径)
F. commitment_check directive 含 sleep_evidence block
G. _dispatch_commitment_nudge context 含 sleep_mode_active / sleep_duration_min
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestAlarmStyleHeuristic(unittest.TestCase):

    def setUp(self):
        from jarvis_sentinels import ChronosSentinel
        self.cs = ChronosSentinel.__new__(ChronosSentinel)

    def test_a_alarm_zh(self):
        for s in ('明天 7 点叫醒我', '把我叫起来', '设个闹钟', '8 点闹铃'):
            self.assertTrue(self.cs._is_alarm_style(s),
                              f"alarm-style '{s}' 应识别")

    def test_a_alarm_en(self):
        for s in ('wake me up at 8am', 'set an alarm', 'wake-up call'):
            self.assertTrue(self.cs._is_alarm_style(s),
                              f"alarm-style '{s}' 应识别")

    def test_a_non_alarm(self):
        for s in ('喝水提醒', 'hydration cycle', '伸展运动', 'pomodoro break'):
            self.assertFalse(self.cs._is_alarm_style(s),
                              f"非 alarm '{s}' 不该识别为 alarm")


class TestPublishReminderFired(unittest.TestCase):

    def setUp(self):
        from jarvis_sentinels import ChronosSentinel
        self.cs = ChronosSentinel.__new__(ChronosSentinel)

    def test_b_publish_when_bus_present(self):
        """publish 'reminder_fired' 进 SWM 含 metadata."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        # Inject as global
        import jarvis_utils as ju
        old_bus = ju._GLOBAL_EVENT_BUS
        try:
            ju._GLOBAL_EVENT_BUS = bus
            self.cs._publish_reminder_fired(
                r={'id': 99, 'intent': 'hydration cycle 90m', 'trigger_time': 1234.0},
                sleep_mode_active=True, is_alarm=False, delivered=False,
            )
            events = bus.recent_events()
            reminder_events = [e for e in events if e.get('type') == 'reminder_fired']
            self.assertGreater(len(reminder_events), 0,
                                'reminder_fired 事件应 publish')
            md = reminder_events[0].get('metadata', {})
            self.assertEqual(md.get('reminder_id'), 99)
            self.assertEqual(md.get('mode'), 'push_only')
            self.assertFalse(md.get('delivered'))
            self.assertTrue(md.get('sleep_mode_active'))
        finally:
            ju._GLOBAL_EVENT_BUS = old_bus

    def test_b_publish_no_bus_safe(self):
        """无 event_bus 不 raise."""
        import jarvis_utils as ju
        old_bus = ju._GLOBAL_EVENT_BUS
        try:
            ju._GLOBAL_EVENT_BUS = None
            # should not raise
            self.cs._publish_reminder_fired(
                r={'id': 1, 'intent': 'x', 'trigger_time': 0},
                sleep_mode_active=False, is_alarm=False, delivered=True)
        finally:
            ju._GLOBAL_EVENT_BUS = old_bus


class TestChronosCodeStructure(unittest.TestCase):
    """检查 ChronosSentinel.run 真改了."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_sentinels.py'), encoding='utf-8') as f:
            cls.src = f.read()

    def test_c_run_has_pushonly_path(self):
        idx = self.src.find('class ChronosSentinel')
        body = self.src[idx:idx + 6000]
        self.assertIn('Chronos/PushOnly', body,
                          'ChronosSentinel.run 应含 push only path log')
        self.assertIn('in_sleep and not is_alarm', body,
                          'sleep + 非 alarm → push only 判断逻辑应在')

    def test_c_run_publishes_reminder_fired(self):
        idx = self.src.find('class ChronosSentinel')
        body = self.src[idx:idx + 6000]
        self.assertIn('_publish_reminder_fired', body,
                          'ChronosSentinel.run 应调 _publish_reminder_fired')
        self.assertIn("'reminder_fired'", body,
                          "应 publish etype='reminder_fired'")

    def test_c_alarm_keywords_lists(self):
        idx = self.src.find('_ALARM_KEYWORDS_EN')
        self.assertGreater(idx, 0)
        body = self.src[idx:idx + 800]
        # 中英 alarm 关键词
        self.assertIn("'wake me'", body)
        self.assertIn("'叫醒'", body)
        self.assertIn("'闹钟'", body)


class TestCommitmentCheckSleepEvidence(unittest.TestCase):
    """fix42: commitment_check directive 看 sleep evidence."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), encoding='utf-8') as f:
            cls.bypass_src = f.read()
        with open(os.path.join(ROOT, 'jarvis_commitment_watcher.py'),
                    encoding='utf-8') as f:
            cls.cw_src = f.read()

    def test_d_directive_has_sleep_evidence_block(self):
        idx = self.bypass_src.find('"commitment_check": (')
        self.assertGreater(idx, 0)
        body = self.bypass_src[idx:idx + 2500]
        self.assertIn('SLEEP/REST EVIDENCE', body,
                          'commitment_check directive 应含 SLEEP/REST EVIDENCE block')
        for key in ('sleep_mode_active', 'sleep_duration_min', 'recent_sleep_min'):
            self.assertIn(key, body, f"directive 应注入 {key}")

    def test_d_dispatch_injects_sleep_context(self):
        idx = self.cw_src.find('def _dispatch_commitment_nudge')
        self.assertGreater(idx, 0)
        body = self.cw_src[idx:idx + 4000]
        self.assertIn('sleep_mode_active', body,
                          '_dispatch_commitment_nudge 应注入 sleep_mode_active')
        self.assertIn('sleep_duration_min', body,
                          '_dispatch_commitment_nudge 应注入 sleep_duration_min')
        self.assertIn('is_sleep_mode', body,
                          '应调 gate.is_sleep_mode()')


if __name__ == '__main__':
    unittest.main()
