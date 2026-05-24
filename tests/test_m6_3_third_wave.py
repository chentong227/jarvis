# -*- coding: utf-8 -*-
"""[Reshape M6.3 third wave / 2026-05-24] 11 init section helper.

覆盖:
  - 11 个 init helper 真存在
  - 3 个有 attribute side-effect 的 helper 真设了 attr
  - 不抛异常 (init 容错全 try/except)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestInit11Helpers(unittest.TestCase):
    def test_all_methods_exist(self):
        from jarvis_central_nerve import CentralNerve
        methods = [
            '_init_directive_registry',
            '_init_self_anchor',
            '_init_concerns_ledger',
            '_init_stand_down',
            '_init_relational_state',
            '_init_attention_layer3',
            '_init_soul_evaluator',
            '_init_reflectors',
            '_init_claim_stats_dumper',
            '_init_integrity_reflector',
            '_init_screen_tease_reflector',
        ]
        for m in methods:
            self.assertTrue(hasattr(CentralNerve, m), f'missing {m}')

    def test_init_self_anchor_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n._init_self_anchor()
        self.assertTrue(hasattr(n, 'self_anchor'))

    def test_init_concerns_ledger_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n._init_concerns_ledger()
        self.assertTrue(hasattr(n, 'concerns_ledger'))

    def test_init_relational_state_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n._init_relational_state()
        self.assertTrue(hasattr(n, 'relational_state'))

    def test_init_soul_evaluator_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n.concerns_ledger = None
        n.relational_state = None
        n._init_soul_evaluator()
        self.assertTrue(hasattr(n, 'soul_evaluator'))

    def test_init_reflectors_sets_attrs(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n.concerns_ledger = None
        n.short_term_memory = []
        n._init_reflectors()
        self.assertTrue(hasattr(n, 'concerns_reflector'))
        self.assertTrue(hasattr(n, 'weekly_reflector'))

    def test_init_claim_stats_dumper_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n._init_claim_stats_dumper()
        self.assertTrue(hasattr(n, 'claim_stats_dumper'))

    def test_init_integrity_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_integrity_reflector()
        self.assertTrue(hasattr(n, 'integrity_reflector'))

    def test_init_screen_tease_reflector_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.key_router = None
        n._init_screen_tease_reflector()
        self.assertTrue(hasattr(n, 'screen_tease_reflector'))

    def test_init_no_raise(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        for fn in ['_init_directive_registry', '_init_stand_down',
                    '_init_attention_layer3']:
            try:
                getattr(n, fn)()
            except Exception as e:
                self.fail(f'{fn} should not raise: {e}')


if __name__ == '__main__':
    unittest.main()
