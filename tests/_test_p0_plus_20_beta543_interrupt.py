# -*- coding: utf-8 -*-
"""β.5.43-C — 被打断察觉 (interrupted_aware) tests."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta543CInterruptedTrigger(unittest.TestCase):
    def test_trigger_callable(self):
        from jarvis_directives import (
            _trigger_interrupted_aware_judge, DirectiveContext,
        )
        ctx = DirectiveContext(current_hour=15, user_input='对了')
        r = _trigger_interrupted_aware_judge(ctx)
        self.assertIsInstance(r, bool)

    def test_trigger_fires_on_reply_interrupted(self):
        import jarvis_utils
        from jarvis_utils import ConversationEventBus
        from jarvis_directives import (
            _trigger_interrupted_aware_judge, DirectiveContext,
        )
        bus = ConversationEventBus()
        jarvis_utils._GLOBAL_EVENT_BUS = bus
        bus.publish(
            etype='reply_interrupted',
            description='Sir cut off Jarvis reply',
            source='interrupt_all',
            metadata={'last_reply_excerpt': 'I was about to...'},
        )
        ctx = DirectiveContext(current_hour=15, user_input='')
        self.assertTrue(_trigger_interrupted_aware_judge(ctx))


class TestBeta543CSWMEtype(unittest.TestCase):
    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        self.assertIn('reply_interrupted', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('reply_interrupted', ConversationEventBus.DEFAULT_SALIENCE)


class TestBeta543CDirectiveSeed(unittest.TestCase):
    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='interrupted_aware_judge'", src)
        self.assertIn('_trigger_interrupted_aware_judge', src)

    def test_vocab_json_has_entry(self):
        import json
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  encoding='utf-8') as f:
            v = json.load(f)
        ids = [d.get('id') for d in v.get('directives', [])]
        self.assertIn('interrupted_aware_judge', ids)


class TestBeta543CInterruptAllPublishesSWM(unittest.TestCase):
    """jarvis_worker.interrupt_all 必须 publish reply_interrupted SWM."""

    def test_worker_interrupt_all_has_publish_block(self):
        with open(os.path.join(ROOT, 'jarvis_worker.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.43-C', src, 'worker 必须含 β.5.43-C marker')
        self.assertIn('reply_interrupted', src,
                      'interrupt_all 必须 publish reply_interrupted SWM')


if __name__ == '__main__':
    unittest.main()
