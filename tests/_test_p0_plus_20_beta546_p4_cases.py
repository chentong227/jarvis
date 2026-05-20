# -*- coding: utf-8 -*-
"""[P4 Cases / 2026-05-21 00:00] Sir 23:32-23:38 真机 case fixes

Cover 4 cases reported by Sir:
  Case #1: 23:30 commitment 不响 — grace_minutes default 10→2
  Case #2: 23:32 "trial quota reached" hallucination — covered by Case #4 (indirect)
  Case #3: 焦点模式不显 — Conductor SoftFocus wire
  Case #4: 23:38 "11:59 PM" hallucination — [PENDING COMMITMENTS] block injected
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCase1_GraceMinutesDefault(unittest.TestCase):
    """Case #1: grace_minutes default changed 10→2"""

    def test_load_default_grace_2(self):
        """Source check: load_active_commitments default should be 2."""
        import jarvis_commitment_watcher
        with open(jarvis_commitment_watcher.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # All 5 grace_minutes locations should be 2 (not 10)
        # Count occurrences of "grace_minutes': 10," — should be 0
        self.assertNotIn("'grace_minutes': 10,", src,
                         "P4 Case #1: All grace_minutes defaults should be 2, not 10")
        self.assertNotIn("'grace_minutes', 10)", src,
                         "P4 Case #1: load default should be 2, not 10")
        # Total "grace_minutes ... 2" patterns (dict + kwarg + load) — should be >= 4
        import re as _re
        _n_2_total = len(_re.findall(r"grace_minutes['\s=,:]+2[\),]", src))
        self.assertGreaterEqual(_n_2_total, 4,
                                 f"P4 Case #1: should have >= 4 grace_minutes=2 patterns, got {_n_2_total}")


class TestCase3_ConductorSoftFocus(unittest.TestCase):
    """Case #3: Conductor _execute_path_a/_b wire SoftFocus"""

    def test_conductor_has_open_soft_focus(self):
        import jarvis_conductor
        with open(jarvis_conductor.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # Should contain open_soft_focus call(s)
        self.assertIn("open_soft_focus", src,
                       "P4 Case #3: Conductor must call return_sentinel.open_soft_focus")
        self.assertIn("reason='conductor_nudge'", src,
                       "P4 Case #3: Conductor SoftFocus reason should be conductor_nudge")


class TestCase4_PendingCommitmentsBlock(unittest.TestCase):
    """Case #4: _assemble_prompt injects [PENDING COMMITMENTS] block"""

    def test_central_nerve_has_pending_commitments_block(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("PENDING COMMITMENTS / NEAR DEADLINE", src,
                       "P4 Case #4: _assemble_prompt must inject [PENDING COMMITMENTS] block")
        self.assertIn("Never invent timestamps", src,
                       "P4 Case #4: prompt block should warn against timestamp hallucination")


if __name__ == '__main__':
    unittest.main()
