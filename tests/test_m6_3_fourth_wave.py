# -*- coding: utf-8 -*-
"""[Reshape M6.3 fourth wave / 2026-05-24] 8 init section helper extract.

覆盖:
  - 8 个 init helper 真存在
  - 4 个 setter 真设 attr (struggle_reflector, intent_resolver, screen_vision_engine, stm_summarizer)
  - 不抛异常
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestInit8FourthWave(unittest.TestCase):
    def test_all_methods_exist(self):
        from jarvis_central_nerve import CentralNerve
        methods = [
            '_init_struggle_reflector',
            '_init_intent_resolver',
            '_init_tom_reflector',
            '_init_integrity_watcher',
            '_init_screen_vision_engine',
            '_init_reject_learner',
            '_init_stm_summarizer',
            '_init_reply_preflight',
        ]
        for m in methods:
            self.assertTrue(hasattr(CentralNerve, m), f'missing {m}')

    def test_init_struggle_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n.short_term_memory = []
        n._init_struggle_reflector()
        self.assertTrue(hasattr(n, 'struggle_reflector'))

    def test_init_intent_resolver_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_intent_resolver()
        self.assertTrue(hasattr(n, 'intent_resolver'))

    def test_init_tom_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_tom_reflector()
        self.assertTrue(hasattr(n, 'tom_reflector'))

    def test_init_integrity_watcher_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_integrity_watcher()
        self.assertTrue(hasattr(n, 'integrity_watcher'))

    def test_init_screen_vision_engine_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_screen_vision_engine()
        self.assertTrue(hasattr(n, 'screen_vision_engine'))

    def test_init_reject_learner_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_reject_learner()
        self.assertTrue(hasattr(n, 'reject_learner'))

    def test_init_stm_summarizer_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_stm_summarizer()
        self.assertTrue(hasattr(n, 'stm_summarizer'))

    def test_init_reply_preflight_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_reply_preflight()
        self.assertTrue(hasattr(n, 'reply_preflight'))


if __name__ == '__main__':
    unittest.main()
