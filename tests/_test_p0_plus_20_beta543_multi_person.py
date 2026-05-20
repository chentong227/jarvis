# -*- coding: utf-8 -*-
"""β.5.43-B — Multi-person aware directive tests."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta543BMultiPersonAwareTrigger(unittest.TestCase):
    def test_trigger_callable(self):
        from jarvis_directives import (
            _trigger_multi_person_aware_judge, DirectiveContext,
        )
        ctx = DirectiveContext(current_hour=14, user_input='帮我看看')
        r = _trigger_multi_person_aware_judge(ctx)
        self.assertIsInstance(r, bool)

    def test_trigger_fires_on_ambient_conversation(self):
        import jarvis_utils
        from jarvis_utils import ConversationEventBus
        from jarvis_directives import (
            _trigger_multi_person_aware_judge, DirectiveContext,
        )
        bus = ConversationEventBus()
        jarvis_utils._GLOBAL_EVENT_BUS = bus
        bus.publish(
            etype='ambient_state',
            description='Ambient: conversation (conf=0.72, n=4)',
            source='ambient_sensor',
            metadata={'ambient_type': 'conversation', 'confidence': 0.72},
        )
        ctx = DirectiveContext(current_hour=14, user_input='帮我看看')
        self.assertTrue(
            _trigger_multi_person_aware_judge(ctx),
            'ambient_state=conversation 应该触发 multi_person_aware_judge',
        )

    def test_trigger_does_not_fire_on_other_ambient(self):
        import jarvis_utils
        from jarvis_utils import ConversationEventBus
        from jarvis_directives import (
            _trigger_multi_person_aware_judge, DirectiveContext,
        )
        bus = ConversationEventBus()
        jarvis_utils._GLOBAL_EVENT_BUS = bus
        bus.publish(
            etype='ambient_state',
            description='Ambient: humming (conf=0.7, n=3)',
            source='ambient_sensor',
            metadata={'ambient_type': 'humming', 'confidence': 0.7},
        )
        ctx = DirectiveContext(current_hour=14, user_input='')
        self.assertFalse(
            _trigger_multi_person_aware_judge(ctx),
            'humming ambient 不该触发 multi_person',
        )


class TestBeta543BDirectiveSeed(unittest.TestCase):
    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='multi_person_aware_judge'", src)
        self.assertIn('_trigger_multi_person_aware_judge', src)
        # priority 9 (高 — 否决其他)
        idx = src.find("id='multi_person_aware_judge'")
        block = src[idx:idx + 600]
        self.assertIn('priority=9', block,
            'multi_person_aware_judge 必须 priority=9 (最高之一, 否决 reply 倾向)')

    def test_vocab_json_has_entry(self):
        import json
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  encoding='utf-8') as f:
            v = json.load(f)
        ids = [d.get('id') for d in v.get('directives', [])]
        self.assertIn('multi_person_aware_judge', ids)


if __name__ == '__main__':
    unittest.main()
