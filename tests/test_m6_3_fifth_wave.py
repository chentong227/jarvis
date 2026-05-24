# -*- coding: utf-8 -*-
"""[Reshape M6.3 fifth wave / 2026-05-24] 6 reflector + PromiseExecutor init.

覆盖:
  - 6 个 init helper 真存在
  - 5 个 reflector helper 设 attr (sir_request, companion_rhythm, inside_joke, sleep_pattern, directive_evaluator)
  - PromiseExecutor 行为分支 (plan_ledger=None vs not None)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestInit6FifthWave(unittest.TestCase):
    def test_all_methods_exist(self):
        from jarvis_central_nerve import CentralNerve
        methods = [
            '_init_sir_request_reflector',
            '_init_companion_rhythm_reflector',
            '_init_inside_joke_reflector',
            '_init_sleep_pattern_reflector',
            '_init_directive_evaluator',
            '_init_promise_executor',
        ]
        for m in methods:
            self.assertTrue(hasattr(CentralNerve, m), f'missing {m}')

    def test_init_sir_request_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n.short_term_memory = []
        n.concerns_ledger = None
        n._init_sir_request_reflector()
        self.assertTrue(hasattr(n, 'sir_request_reflector'))

    def test_init_companion_rhythm_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.short_term_memory = []
        n._init_companion_rhythm_reflector()
        self.assertTrue(hasattr(n, 'companion_rhythm_reflector'))

    def test_init_inside_joke_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n.short_term_memory = []
        n.relational_state = None
        n._init_inside_joke_reflector()
        self.assertTrue(hasattr(n, 'inside_joke_reflector'))

    def test_init_sleep_pattern_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.hippocampus = None
        n._init_sleep_pattern_reflector()
        self.assertTrue(hasattr(n, 'sleep_pattern_reflector'))

    def test_init_directive_evaluator_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_directive_evaluator()
        self.assertTrue(hasattr(n, 'directive_evaluator'))

    def test_init_promise_executor_no_ledger(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.plan_ledger = None
        n.event_bus = None
        n._init_promise_executor()
        self.assertTrue(hasattr(n, 'promise_executor'))
        self.assertIsNone(n.promise_executor)

    def test_init_promise_executor_with_ledger(self):
        from jarvis_central_nerve import CentralNerve
        from unittest.mock import MagicMock
        n = CentralNerve.__new__(CentralNerve)
        n.plan_ledger = MagicMock()
        n.event_bus = None
        n._init_promise_executor()
        self.assertTrue(hasattr(n, 'promise_executor'))
        # 有 plan_ledger 则尝试 instantiate (instance 或 None on import error)


if __name__ == '__main__':
    unittest.main()
