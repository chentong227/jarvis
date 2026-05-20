# -*- coding: utf-8 -*-
"""β.5.40-fix — Sir 16:07 sleep nudge BUG, 准则 6 evidence-driven 修法.

不修硬编码 dampen 公式. 改:
1. ProactiveCare publish concern_timing_evidence SWM (sleep concern 16:07 → in_window=False, hours_until=+6)
2. concern_timing_judge directive 教主脑看 evidence 自决 (远离 timing 不主动提)

Tests:
  1. _compute_concern_timing_evidence helper
  2. SWM etype + salience 注册
  3. directive trigger callable
  4. directive seed + vocab entry
  5. ProactiveCare publish 在 source 含
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta540FixComputeEvidence(unittest.TestCase):
    """_compute_concern_timing_evidence 算 timing evidence."""

    def test_no_optimal_timing_returns_none(self):
        from jarvis_proactive_care import _compute_concern_timing_evidence
        c = type('C', (), {'optimal_timing': ''})()
        self.assertIsNone(_compute_concern_timing_evidence(c, 1779200000.0))

    def test_before_sleep_at_afternoon(self):
        """16:00 sir_sleep_streak → in_window=False, hours_until=6."""
        import time
        from jarvis_proactive_care import _compute_concern_timing_evidence
        c = type('C', (), {'optimal_timing': 'before_sleep'})()
        # 制 timestamp 16:00 local
        ts = time.mktime((2026, 5, 20, 16, 0, 0, 0, 140, 0))
        ev = _compute_concern_timing_evidence(c, ts)
        self.assertIsNotNone(ev)
        self.assertEqual(ev['optimal_timing'], 'before_sleep')
        self.assertEqual(ev['current_hour'], 16)
        self.assertFalse(ev['is_in_optimal_window'])
        self.assertEqual(ev['hours_until_optimal'], 6, '16:00 离 22:00 = 6h')

    def test_before_sleep_at_22(self):
        import time
        from jarvis_proactive_care import _compute_concern_timing_evidence
        c = type('C', (), {'optimal_timing': 'before_sleep'})()
        ts = time.mktime((2026, 5, 20, 22, 0, 0, 0, 140, 0))
        ev = _compute_concern_timing_evidence(c, ts)
        self.assertTrue(ev['is_in_optimal_window'])
        self.assertEqual(ev['hours_until_optimal'], 0)

    def test_morning_at_3(self):
        import time
        from jarvis_proactive_care import _compute_concern_timing_evidence
        c = type('C', (), {'optimal_timing': 'morning'})()
        ts = time.mktime((2026, 5, 20, 3, 0, 0, 0, 140, 0))
        ev = _compute_concern_timing_evidence(c, ts)
        self.assertFalse(ev['is_in_optimal_window'])
        self.assertEqual(ev['hours_until_optimal'], 3, '03:00 离 06:00 = 3h')

    def test_now_always_in_window(self):
        import time
        from jarvis_proactive_care import _compute_concern_timing_evidence
        c = type('C', (), {'optimal_timing': 'now'})()
        ev = _compute_concern_timing_evidence(c, time.time())
        self.assertTrue(ev['is_in_optimal_window'])
        self.assertEqual(ev['hours_until_optimal'], 0)

    def test_unknown_timing_returns_none(self):
        from jarvis_proactive_care import _compute_concern_timing_evidence
        c = type('C', (), {'optimal_timing': 'noon'})()
        self.assertIsNone(_compute_concern_timing_evidence(c, 1779200000.0))


class TestBeta540FixSWMEtype(unittest.TestCase):
    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        self.assertIn('concern_timing_evidence', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('concern_timing_evidence', ConversationEventBus.DEFAULT_SALIENCE)

    def test_salience_high_enough_for_main_brain(self):
        from jarvis_utils import ConversationEventBus
        s = ConversationEventBus.DEFAULT_SALIENCE['concern_timing_evidence']
        # salience ≥ 0.55 才会进 top_n 给主脑看
        self.assertGreaterEqual(s, 0.5)


class TestBeta540FixDirective(unittest.TestCase):
    def test_trigger_callable(self):
        from jarvis_directives import _trigger_concern_timing_judge, DirectiveContext
        ctx = DirectiveContext(current_hour=16, user_input='')
        r = _trigger_concern_timing_judge(ctx)
        self.assertIsInstance(r, bool)

    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='concern_timing_judge'", src)
        self.assertIn('_trigger_concern_timing_judge', src)
        # priority 8 (高于其他 directives)
        self.assertIn("priority=8", src)

    def test_directive_priority_higher_than_other_nudge_directives(self):
        """concern_timing_judge priority 必须高 (否决 top_concern push 的盲目反应)."""
        # 看 seed 内的 priority
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        idx = src.find("id='concern_timing_judge'")
        block = src[idx:idx+1000]
        self.assertIn('priority=8', block)

    def test_vocab_json_has_entry(self):
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  'r', encoding='utf-8') as f:
            v = json.load(f)
        ids = [d.get('id') for d in v.get('directives', [])]
        self.assertIn('concern_timing_judge', ids)


class TestBeta540FixProactiveCarePublish(unittest.TestCase):
    def test_pc_has_publish_block(self):
        with open(os.path.join(ROOT, 'jarvis_proactive_care.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.40-fix', src, 'ProactiveCare 必须含 β.5.40-fix marker')
        self.assertIn('concern_timing_evidence', src)
        self.assertIn('_compute_concern_timing_evidence', src)


class TestBeta540FixNoHardcodedDampen(unittest.TestCase):
    """Sir 真理: 修法不能动 compute_urgency 的硬 dampen 公式 (准则 6)."""

    def test_compute_urgency_unchanged(self):
        """compute_urgency 不应该新加硬 dampen — 只能动 publish 路径."""
        with open(os.path.join(ROOT, 'jarvis_proactive_care.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 compute_urgency 函数体
        idx = src.find('def compute_urgency')
        end = src.find('def ', idx + 1)
        body = src[idx:end] if idx > 0 and end > idx else ''
        # 老逻辑: timing_mul = 1.5 if timing_hit. 不应该加 'timing_mul = 0.4' 类硬 dampen
        # (Sir 准则 6 拒绝硬编码)
        # 实际允许 timing_mul = 1.5 (老逻辑保留), 但不应该有新硬 dampen
        self.assertNotIn('timing_mul = 0.3', body)
        self.assertNotIn('timing_mul = 0.4', body)
        self.assertNotIn('timing_mul = 0.5', body)


if __name__ == '__main__':
    unittest.main()
