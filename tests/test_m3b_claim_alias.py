# -*- coding: utf-8 -*-
"""[Reshape M3.B.Claim / 2026-05-24] FactClaim / IntegrityClaim alias 验证.

策略: 不 rename 251 处 (太大 risk vs 0 收益), 加新名 alias 让新代码可用更准确名.
老 Claim 名保留 0 改动 - backward compat.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestFactClaimAlias(unittest.TestCase):
    """jarvis_claim_tracer.FactClaim is jarvis_claim_tracer.Claim alias."""

    def test_factclaim_is_claim(self):
        from jarvis_claim_tracer import Claim, FactClaim
        self.assertIs(FactClaim, Claim,
                       'M3.B.Claim: FactClaim 应是 Claim 严格 alias')

    def test_factclaim_instantiate_same(self):
        from jarvis_claim_tracer import FactClaim
        c = FactClaim('time', '12:00')
        self.assertEqual(c.kind, 'time')
        self.assertEqual(c.text, '12:00')
        self.assertIsNone(c.trace_to)

    def test_old_claim_name_still_works(self):
        from jarvis_claim_tracer import Claim
        c = Claim('percent', '87%')
        self.assertEqual(c.kind, 'percent')


class TestIntegrityClaimAlias(unittest.TestCase):
    """jarvis_integrity_watcher.IntegrityClaim is jarvis_integrity_watcher.Claim alias."""

    def test_integrityclaim_is_claim(self):
        from jarvis_integrity_watcher import Claim, IntegrityClaim
        self.assertIs(IntegrityClaim, Claim,
                       'M3.B.Claim: IntegrityClaim 应是 Claim 严格 alias')

    def test_integrityclaim_dataclass_fields(self):
        from jarvis_integrity_watcher import IntegrityClaim
        c = IntegrityClaim(id='c1', claim_type='reminder',
                            extracted_action='I set reminder',
                            extracted_target='12:00')
        self.assertEqual(c.id, 'c1')
        self.assertEqual(c.claim_type, 'reminder')

    def test_old_claim_name_still_works(self):
        from jarvis_integrity_watcher import Claim
        c = Claim(id='c2', claim_type='profile',
                    extracted_action='updated', extracted_target='hobbies')
        self.assertEqual(c.claim_type, 'profile')


class TestNoCrossConflict(unittest.TestCase):
    """两个 Claim 不再冲突: 同时 import 不互相覆盖."""

    def test_can_import_both_factclaim_and_integrityclaim(self):
        from jarvis_claim_tracer import FactClaim
        from jarvis_integrity_watcher import IntegrityClaim
        # 这俩是独立 class
        self.assertIsNot(FactClaim, IntegrityClaim)

    def test_old_claim_collision_still_exists(self):
        """老 `from X import Claim` 同时用仍冲突 (已知, 0 真 caller). 用新名 alias 解."""
        from jarvis_claim_tracer import Claim as FC
        from jarvis_integrity_watcher import Claim as IC
        # 用 'as' 解决, 不用 'as' 仍会覆盖
        self.assertIsNot(FC, IC)


if __name__ == '__main__':
    unittest.main()
