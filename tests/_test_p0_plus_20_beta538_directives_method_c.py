# -*- coding: utf-8 -*-
"""[β.5.38 / 2026-05-20] 方向 C — 5 个新 SWM evidence directive.

Sir 选择: 杠杆最高方向 — 利用 β.5.37 架构, 主脑看 SWM evidence 自决场景 A/B/C.

5 个新 directive:
  - morning_mood_judge (6-10am + first_active_today)
  - late_night_care_judge (>= 23:00 / < 02:00)
  - silent_company_judge (Sir 不说话久 + cascade_active)
  - callback_recall_judge (Sir 输入含模糊 reference)
  - mood_shift_judge (SWM 含 ≥ 3 类 state signal 在 30min 内)
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta538TriggerFunctions(unittest.TestCase):
    """5 个新 trigger 函数 callable + basic ctx case."""

    def test_morning_mood_outside_window(self):
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext
        # 中午 12 时 → False (不在 6-10am 窗口)
        self.assertFalse(_trigger_morning_mood_judge(DirectiveContext(current_hour=12)))

    def test_morning_mood_in_window_first_active(self):
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        with patch.object(P, 'is_first_active_today', new=True):
            self.assertTrue(_trigger_morning_mood_judge(DirectiveContext(current_hour=8)))

    def test_morning_mood_in_window_not_first(self):
        from jarvis_directives import _trigger_morning_mood_judge, DirectiveContext
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        with patch.object(P, 'is_first_active_today', new=False):
            self.assertFalse(_trigger_morning_mood_judge(DirectiveContext(current_hour=8)))

    def test_late_night_care_23h(self):
        from jarvis_directives import _trigger_late_night_care_judge, DirectiveContext
        self.assertTrue(_trigger_late_night_care_judge(DirectiveContext(current_hour=23)))

    def test_late_night_care_1am(self):
        from jarvis_directives import _trigger_late_night_care_judge, DirectiveContext
        self.assertTrue(_trigger_late_night_care_judge(DirectiveContext(current_hour=1)))

    def test_late_night_care_daytime(self):
        from jarvis_directives import _trigger_late_night_care_judge, DirectiveContext
        self.assertFalse(_trigger_late_night_care_judge(DirectiveContext(current_hour=14)))

    def test_silent_company_with_user_input_skipped(self):
        from jarvis_directives import _trigger_silent_company_judge, DirectiveContext
        # Sir 主动说了话 → 不算 silent
        self.assertFalse(_trigger_silent_company_judge(
            DirectiveContext(user_input="hello")))

    def test_callback_recall_with_nage(self):
        from jarvis_directives import _trigger_callback_recall_judge, DirectiveContext
        self.assertTrue(_trigger_callback_recall_judge(
            DirectiveContext(user_input="把那个文档打开一下")))

    def test_callback_recall_with_earlier(self):
        from jarvis_directives import _trigger_callback_recall_judge, DirectiveContext
        self.assertTrue(_trigger_callback_recall_judge(
            DirectiveContext(user_input="like I said earlier, please proceed")))

    def test_callback_recall_normal_no_ref(self):
        from jarvis_directives import _trigger_callback_recall_judge, DirectiveContext
        self.assertFalse(_trigger_callback_recall_judge(
            DirectiveContext(user_input="open chrome")))


class TestBeta538MoodShiftWithSWM(unittest.TestCase):
    """mood_shift_judge 在 SWM 含 ≥ 3 类 state signal 时 fire."""

    def setUp(self):
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)

    def test_mood_shift_fires_on_3_signal_types(self):
        from jarvis_directives import _trigger_mood_shift_judge, DirectiveContext
        # 灌 3 类 state signal
        self.bus.publish('sleep_intent_signal', 'score=0.5', source='SleepDetector', salience=0.6)
        self.bus.publish('sir_struggle_observed', 'stuck', source='SirStruggleVocab', salience=0.7)
        self.bus.publish('sir_afk_detected', 'idle 100s', source='PhysicalEnvProbe', salience=0.65)
        self.assertTrue(_trigger_mood_shift_judge(DirectiveContext()),
            '≥ 3 类 state signal 必须 fire mood_shift_judge')

    def test_silent_company_fires_on_ghost(self):
        from jarvis_directives import _trigger_silent_company_judge, DirectiveContext
        self.bus.publish('ghost_activity_observed', 'cursor.exe', source='PhysicalEnvProbe', salience=0.6)
        # 无 user_input + SWM 含 ghost → fire
        self.assertTrue(_trigger_silent_company_judge(DirectiveContext(user_input="")))


class TestBeta538DirectiveRegistered(unittest.TestCase):
    """5 directive 在 seed_defs + vocab JSON."""

    def test_seed_defs_contain_five_new(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        for did in ('morning_mood_judge', 'late_night_care_judge', 'silent_company_judge',
                    'callback_recall_judge', 'mood_shift_judge'):
            self.assertIn(f"id='{did}'", src, f'{did} 必须存在 seed_defs')
        self.assertIn('β.5.38', src, 'β.5.38 marker 必须存在')

    def test_vocab_json_contains_five_entries(self):
        import json
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ids = {d['id'] for d in data['directives']}
        for did in ('morning_mood_judge', 'late_night_care_judge', 'silent_company_judge',
                    'callback_recall_judge', 'mood_shift_judge'):
            self.assertIn(did, ids, f'{did} 必须存在 vocab JSON')


if __name__ == '__main__':
    unittest.main()
