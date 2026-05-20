# -*- coding: utf-8 -*-
"""[β.5.37-D / 2026-05-20] 主脑 directive 层: 3 个 SWM evidence directive.

- sleep_confirmation_judge: 看 SWM sleep_intent_signal 自决 confirm sleep / 等待
- ghost_activity_judge: 看 SWM ghost_activity_observed / sir_afk_detected 不把屏幕动当 Sir 操作
- sir_intent_judge: 看 SWM sir_struggle_observed 判 struggle vs dismiss

Sir 14:39 校正: 准则 6 三维耦合 — 主脑看 SWM evidence 自决, 不再 sentinel hard decide.
"""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta537DTriggerFunctions(unittest.TestCase):
    """3 个新 trigger 函数定义存在 + import 正常 (不验 bus state — 跨 test 污染)."""

    def test_swm_has_recent_helper_importable(self):
        from jarvis_directives import _swm_has_recent
        self.assertTrue(callable(_swm_has_recent))

    def test_sleep_confirmation_trigger_callable(self):
        from jarvis_directives import _trigger_sleep_confirmation_judge, DirectiveContext
        self.assertTrue(callable(_trigger_sleep_confirmation_judge))
        # 调用不抛异常即可 (bus state 跨 test 污染, 不验 True/False)
        result = _trigger_sleep_confirmation_judge(DirectiveContext())
        self.assertIsInstance(result, bool)

    def test_ghost_activity_trigger_callable(self):
        from jarvis_directives import _trigger_ghost_activity_judge, DirectiveContext
        self.assertTrue(callable(_trigger_ghost_activity_judge))
        result = _trigger_ghost_activity_judge(DirectiveContext())
        self.assertIsInstance(result, bool)

    def test_sir_intent_trigger_callable(self):
        from jarvis_directives import _trigger_sir_intent_judge, DirectiveContext
        self.assertTrue(callable(_trigger_sir_intent_judge))
        result = _trigger_sir_intent_judge(DirectiveContext())
        self.assertIsInstance(result, bool)


class TestBeta537DTriggersFireOnSWMEvidence(unittest.TestCase):
    """3 个 trigger 在 SWM 含相关 signal 时 fire True."""

    def setUp(self):
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus()
        ConversationEventBus.register_global(self.bus)

    def test_sleep_confirmation_fires_on_sleep_intent_signal(self):
        from jarvis_directives import _trigger_sleep_confirmation_judge, DirectiveContext
        self.bus.publish('sleep_intent_signal', 'score=0.63', source='SleepDetector', salience=0.7)
        self.assertTrue(_trigger_sleep_confirmation_judge(DirectiveContext()),
            'sleep_intent_signal 在 SWM → 必须 fire')

    def test_ghost_activity_fires_on_ghost_observed(self):
        from jarvis_directives import _trigger_ghost_activity_judge, DirectiveContext
        self.bus.publish('ghost_activity_observed', 'cursor.exe in fg', source='PhysicalEnvProbe', salience=0.6)
        self.assertTrue(_trigger_ghost_activity_judge(DirectiveContext()))

    def test_ghost_activity_fires_on_afk_detected(self):
        from jarvis_directives import _trigger_ghost_activity_judge, DirectiveContext
        self.bus.publish('sir_afk_detected', 'idle 120s', source='PhysicalEnvProbe', salience=0.65)
        self.assertTrue(_trigger_ghost_activity_judge(DirectiveContext()))

    def test_sir_intent_fires_on_struggle_observed(self):
        from jarvis_directives import _trigger_sir_intent_judge, DirectiveContext
        self.bus.publish('sir_struggle_observed', 'stuck_zh', source='SirStruggleVocab', salience=0.85)
        self.assertTrue(_trigger_sir_intent_judge(DirectiveContext()))


class TestBeta537DDirectiveRegistered(unittest.TestCase):
    """3 directive 注册到 registry + vocab JSON entry 存在."""

    def test_seed_defs_contain_three_new_directives(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        for did in ('sleep_confirmation_judge', 'ghost_activity_judge', 'sir_intent_judge'):
            self.assertIn(f"id='{did}'", src,
                f'{did} 必须存在 seed_defs')
            self.assertIn(f'β.5.37-D', src,
                'β.5.37-D marker 必须存在')

    def test_vocab_json_contains_three_entries(self):
        import json
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ids = {d['id'] for d in data['directives']}
        for did in ('sleep_confirmation_judge', 'ghost_activity_judge', 'sir_intent_judge'):
            self.assertIn(did, ids, f'{did} 必须存在 vocab JSON')


if __name__ == '__main__':
    unittest.main()
