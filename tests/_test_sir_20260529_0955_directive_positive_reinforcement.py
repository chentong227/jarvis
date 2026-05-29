# -*- coding: utf-8 -*-
"""[#3 / Sir 2026-05-29] Directive positive reinforcement tests.

覆盖：
- helped 高且 rejected/not_helped 低 → priority +1
- cooldown 防重复 boost
- max_priority cap 不越界
- priority>=10 红线不 boost/不 mutate
- disabled config no-op
- last_reinforced persist/load round-trip
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (  # noqa: E402
    Directive,
    DirectiveRegistry,
    STATE_ACTIVE,
)


def _cfg(**overrides):
    base = {
        'enabled': True,
        'min_fired': 5,
        'min_helped': 3,
        'min_helped_ratio': 0.7,
        'max_rejected_rate': 0.1,
        'cooldown_hours': 24,
        'priority_step': 1,
        'max_priority': 9,
    }
    base.update(overrides)
    return base


def _directive(did='d', priority=5, fired=5, helped=4, not_helped=1,
               rejected=0):
    d = Directive(
        id=did,
        text='test directive',
        trigger=lambda _ctx: True,
        priority=priority,
        source_marker='test',
    )
    d.state = STATE_ACTIVE
    d.fired = fired
    d.helped = helped
    d.not_helped = not_helped
    d.rejected = rejected
    d.last_triggered = time.time()
    return d


class TestDirectivePositiveReinforcement(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False,
                                               suffix='.json')
        self.tmp.close()
        self.review_path = self.tmp.name + '.review.json'
        self.r = DirectiveRegistry(persist_path=self.tmp.name,
                                   review_path=self.review_path)

    def tearDown(self):
        self.r.stop_decay_worker()
        for p in (self.tmp.name, self.review_path):
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_helped_high_boosts_priority_once(self):
        d = _directive(priority=5, fired=5, helped=4, not_helped=1)
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg()):
            stats = self.r.apply_decay()
        self.assertEqual(stats['priority_boost'], 1)
        self.assertEqual(self.r.get('d').priority, 6)
        self.assertGreater(self.r.get('d').last_reinforced, 0)

    def test_cooldown_prevents_repeat_boost(self):
        d = _directive(priority=5, fired=10, helped=9, not_helped=1)
        d.last_reinforced = time.time()
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg(cooldown_hours=24)):
            stats = self.r.apply_decay()
        self.assertEqual(stats['priority_boost'], 0)
        self.assertEqual(self.r.get('d').priority, 5)

    def test_max_priority_cap(self):
        d = _directive(priority=8, fired=10, helped=10, not_helped=0)
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg(priority_step=3, max_priority=9)):
            stats = self.r.apply_decay()
        self.assertEqual(stats['priority_boost'], 1)
        self.assertEqual(self.r.get('d').priority, 9)

    def test_priority_10_redline_protected(self):
        d = _directive(priority=10, fired=10, helped=10, not_helped=0)
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg(max_priority=9)):
            stats = self.r.apply_decay()
        self.assertEqual(stats['critical_protected'], 1)
        self.assertEqual(stats['priority_boost'], 0)
        self.assertEqual(self.r.get('d').priority, 10)
        self.assertEqual(self.r.get('d').last_reinforced, 0)

    def test_disabled_config_noop(self):
        d = _directive(priority=5, fired=10, helped=10, not_helped=0)
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg(enabled=False)):
            stats = self.r.apply_decay()
        self.assertEqual(stats['priority_boost'], 0)
        self.assertEqual(self.r.get('d').priority, 5)

    def test_mixed_signal_not_helped_threshold_blocks_boost(self):
        d = _directive(priority=5, fired=20, helped=20, not_helped=5)
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg()):
            stats = self.r.apply_decay()
        self.assertEqual(stats['priority_boost'], 0)
        self.assertEqual(self.r.get('d').priority, 5)

    def test_persist_load_last_reinforced(self):
        d = _directive(priority=5, fired=10, helped=10, not_helped=0)
        self.r.register(d)
        with patch('jarvis_directives._load_reinforcement_config',
                   return_value=_cfg(cooldown_hours=0)):
            self.r.apply_decay()
        ts = self.r.get('d').last_reinforced
        self.assertTrue(self.r.persist())

        r2 = DirectiveRegistry(persist_path=self.tmp.name,
                               review_path=self.review_path)
        r2.register(_directive(priority=5, fired=0, helped=0, not_helped=0))
        n = r2.load()
        self.assertEqual(n, 1)
        self.assertEqual(r2.get('d').last_reinforced, ts)
        self.assertEqual(r2.get('d').priority, 6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
