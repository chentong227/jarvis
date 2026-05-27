# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:09 / 18:10 / 18:14 真测 3 anchor 合并]

A. (18:09) Sir '你下午什么时候关的不?' → Jarvis 编 '1:05 PM' 幻觉.
   治本: SelfAnchor 启动时扫 docs/runtime_logs/ 次新 log mtime, 入 SELF block.

B. (18:10) Sir '已选择 screen_tease 但为何不提醒?'.
   治本: SmartNudge._dispatch_nudge 3 处 silent return 加 bg_log + publish_skip
   (humor_memory.can_joke_now / should_skip_topic / gate.can_speak).

C. (18:14 INTEGRITY) Jarvis 嘴上承诺 reminder 但 add_reminder fail (time fmt).
   治本: l4_memory_hands._parse_trigger_time fallback parse 自然语言.
"""
from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ============================================================
# A. SelfAnchor PREVIOUS SESSION evidence (Sir 18:09)
# ============================================================
class TestSelfAnchorPreviousSession(unittest.TestCase):

    def test_t1_has_previous_session_methods(self):
        """SelfAnchor 必有 _previous_session_last_seen_at 属性 + getter."""
        from jarvis_self_anchor import SelfAnchor
        sa = SelfAnchor()
        self.assertTrue(hasattr(sa, '_previous_session_last_seen_at'),
            "SelfAnchor 必有 _previous_session_last_seen_at 属性")
        self.assertTrue(hasattr(sa, '_get_previous_session_info'),
            "SelfAnchor 必有 _get_previous_session_info() 方法")

    def test_t2_previous_session_info_returns_proper_format(self):
        """有 prev_ts 时 _get_previous_session_info 返 'HH:MM (Xh Ymin gap)'."""
        from jarvis_self_anchor import SelfAnchor
        sa = SelfAnchor()
        # 手动注入: 上 session 比本 session 早 4h 51min
        sa._session_started_at = time.mktime(
            time.strptime('2026-05-27 18:05:00', '%Y-%m-%d %H:%M:%S')
        )
        sa._previous_session_last_seen_at = time.mktime(
            time.strptime('2026-05-27 13:14:00', '%Y-%m-%d %H:%M:%S')
        )
        info = sa._get_previous_session_info()
        self.assertIsNotNone(info)
        self.assertIn('13:14', info, f"必含 HH:MM '13:14', got: {info}")
        # gap = 4h 51min
        self.assertTrue('4h' in info and '51min' in info,
            f"必含 '4h 51min' gap, got: {info}")

    def test_t3_build_block_includes_previous_session_when_available(self):
        """build_block 必把 previous session info 加进 [MY CURRENT CONTINUITY]."""
        from jarvis_self_anchor import SelfAnchor
        sa = SelfAnchor()
        sa._session_started_at = time.mktime(
            time.strptime('2026-05-27 18:05:00', '%Y-%m-%d %H:%M:%S')
        )
        sa._previous_session_last_seen_at = time.mktime(
            time.strptime('2026-05-27 13:14:00', '%Y-%m-%d %H:%M:%S')
        )
        block = sa.build_block(max_chars=4000)
        self.assertIn('previous session last activity', block,
            "build_block 必显 'previous session last activity'")
        self.assertIn('13:14', block,
            "block 必含上 session HH:MM")
        # 必含 'prior process died' 解释让主脑明白这是何时 die 的
        self.assertIn('prior process died', block,
            "block 必含解释 'prior process died' 让主脑懂 evidence 含义")

    def test_t4_build_block_session_uptime_shows_boot_hhmm(self):
        """session uptime 行必显 'boot at HH:MM' (老版只显 min)."""
        from jarvis_self_anchor import SelfAnchor
        sa = SelfAnchor()
        sa._session_started_at = time.mktime(
            time.strptime('2026-05-27 18:05:00', '%Y-%m-%d %H:%M:%S')
        )
        block = sa.build_block(max_chars=4000)
        self.assertIn('boot at 18:05', block,
            "block 必含 'boot at 18:05'")


# ============================================================
# B. SmartNudge silent return → bg_log (Sir 18:10)
# ============================================================
class TestSmartNudgeSilentSkipLogged(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_smart_nudge.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_t5_humor_cooldown_skip_has_bg_log(self):
        """humor_memory.can_joke_now=False 必加 bg_log + publish_skip."""
        self.assertIn('humor_memory_cooldown_', self.src,
            "publish_skip reason 'humor_memory_cooldown_' 必存在")
        self.assertIn("blocked by humor_memory", self.src,
            "bg_log msg 必含 'blocked by humor_memory'")
        self.assertIn("can_joke_now=False", self.src,
            "bg_log 必显具体原因 'can_joke_now=False'")

    def test_t6_humor_topic_skip_has_bg_log(self):
        """should_skip_topic=True 必加 bg_log + publish_skip."""
        self.assertIn('humor_memory_topic_skip_', self.src,
            "publish_skip reason 'humor_memory_topic_skip_' 必存在")
        self.assertIn("should_skip_topic=True", self.src,
            "bg_log 必显 'should_skip_topic=True'")

    def test_t7_nudge_gate_skip_has_bg_log(self):
        """gate.can_speak('companion')=False 必加 bg_log + publish_skip."""
        self.assertIn('nudge_gate_blocked_', self.src,
            "publish_skip reason 'nudge_gate_blocked_' 必存在")
        self.assertIn("blocked by NudgeGate", self.src,
            "bg_log msg 必含 'blocked by NudgeGate'")
        self.assertIn("can_speak('companion')=False", self.src,
            "bg_log 必显 'can_speak('companion')=False'")

    def test_t8_anchor_marker_in_src(self):
        """Sir 2026-05-27 18:10 anchor marker 必存."""
        self.assertIn('Sir 2026-05-27 18:10', self.src,
            "Sir 18:10 anchor marker 必存于 src")


# ============================================================
# C. add_reminder 自然语言 trigger_time parser (Sir 18:14)
# ============================================================
class TestAddReminderParser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 固定 'now' 让 test 稳定
        cls.now = time.mktime(
            time.strptime('2026-05-27 18:14:00', '%Y-%m-%d %H:%M:%S')
        )

    def _parse(self, raw):
        from l4_hands_pool.l4_memory_hands import _parse_trigger_time
        return _parse_trigger_time(raw, now_ts=self.now)

    def test_t9_strict_format_still_works(self):
        """老严格格式 'YYYY-MM-DD HH:MM:SS' 仍工作 (不破)."""
        ts, _ = self._parse('2026-05-28 08:00:00')
        self.assertIsNotNone(ts)
        got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
        self.assertEqual(got, '2026-05-28 08:00')

    def test_t10_tomorrow_with_time(self):
        """'tomorrow 08:00' / 'tomorrow 8am' 都返同结果."""
        for raw in ('tomorrow 08:00', 'tomorrow 8am', 'tomorrow at 8'):
            ts, _ = self._parse(raw)
            self.assertIsNotNone(ts, f"'{raw}' 必 parse 成")
            got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
            self.assertEqual(got, '2026-05-28 08:00',
                f"'{raw}' 应解 2026-05-28 08:00, got {got}")

    def test_t11_tomorrow_only_default_8am(self):
        """光 'tomorrow' 默认 08:00 (Sir 真测 case 复现)."""
        ts, _ = self._parse('tomorrow')
        got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
        self.assertEqual(got, '2026-05-28 08:00')

    def test_t12_chinese_natural(self):
        """中文自然语言: '明天' / '明天早上' / '明天 8 点 30 分'."""
        cases = [
            ('明天', '2026-05-28 08:00'),
            ('明天早上', '2026-05-28 08:00'),
            ('明天 8 点 30 分', '2026-05-28 08:30'),
            ('明天晚上 9 点', '2026-05-28 21:00'),
        ]
        for raw, expected in cases:
            ts, _ = self._parse(raw)
            self.assertIsNotNone(ts, f"'{raw}' 必 parse 成")
            got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
            self.assertEqual(got, expected, f"'{raw}' should be {expected}, got {got}")

    def test_t13_night_context_pm_inference(self):
        """'今晚 9 点' / 'tonight 9' 必推断 PM (21:00)."""
        cases = [
            ('今晚 9 点', '2026-05-27 21:00'),
            ('今晚', '2026-05-27 21:00'),
            ('明晚 8 点', '2026-05-28 20:00'),
            ('tonight 9pm', '2026-05-27 21:00'),
        ]
        for raw, expected in cases:
            ts, _ = self._parse(raw)
            self.assertIsNotNone(ts, f"'{raw}' 必 parse 成")
            got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
            self.assertEqual(got, expected, f"'{raw}' should be {expected}, got {got}")

    def test_t14_relative_time(self):
        """'in N hours/min' / 'N 小时后' / 'N 分钟后'."""
        cases = [
            ('in 2 hours', '2026-05-27 20:14'),
            ('in 30 min', '2026-05-27 18:44'),
            ('3 小时后', '2026-05-27 21:14'),
            ('5 分钟后', '2026-05-27 18:19'),
        ]
        for raw, expected in cases:
            ts, _ = self._parse(raw)
            self.assertIsNotNone(ts, f"'{raw}' 必 parse 成")
            got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
            self.assertEqual(got, expected)

    def test_t15_garbage_returns_none(self):
        """无效输入返 (None, '')."""
        for raw in ('asdf', '', 'qwerty', '   '):
            ts, _ = self._parse(raw)
            self.assertIsNone(ts, f"'{raw}' 应 parse 失败 (返 None)")

    def test_t16_today_past_hour_rolls_to_tomorrow(self):
        """'today 9am' 已过 → 推 tomorrow (避免反向 reminder)."""
        ts, _ = self._parse('today 9am')
        got = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
        # now=18:14, 9am 已过 → 推 2026-05-28 09:00
        self.assertEqual(got, '2026-05-28 09:00',
            f"today 已过点应推 tomorrow, got {got}")

    def test_t17_instruction_dict_mentions_natural_language(self):
        """get_instruction_dict 教主脑 trigger_time 接自然语言."""
        from l4_hands_pool.l4_memory_hands import Hands
        h = Hands.__new__(Hands)  # 不 init hippocampus
        instr = Hands.get_instruction_dict(h)
        self.assertIn('tomorrow 08:00', instr,
            "instruction 必含 'tomorrow 08:00' 示例")
        self.assertIn('明天早上', instr,
            "instruction 必含中文 '明天早上' 示例")
        self.assertIn('in 2 hours', instr,
            "instruction 必含 'in 2 hours' relative 示例")


if __name__ == '__main__':
    unittest.main(verbosity=2)
