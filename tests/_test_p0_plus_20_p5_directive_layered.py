# -*- coding: utf-8 -*-
"""[Gap-Y / β.5.46-fix5 / 2026-05-21 23:30] Directive 分层注入 + not_helped 测试.

Sir 22:14 真测痛点: directive cluster fired count=7 / chars=7724 → 主脑 attention 淹.
治法: top N priority 全文 + 余 brief (purpose_short).
+ not_helped 双向计数 + decay 规则 4/5 退役低效 directive.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    Directive,
    DirectiveRegistry,
    DirectiveContext,
    NOT_HELPED_PRIORITY_DROP,
    NOT_HELPED_REVIEW_THRESHOLD,
    HELPED_RATIO_THRESHOLD,
    STATE_ACTIVE,
    STATE_REVIEW,
    _PERSISTABLE_FIELDS,
)


class TestA_NotHelpedField(unittest.TestCase):
    """Directive dataclass 应有 not_helped + last_not_helped 字段."""

    def test_not_helped_initialized(self):
        d = Directive(id='test1', text='test', source_marker='test',
                       priority=5, ttl_days=30, trigger=lambda ctx: True)
        self.assertEqual(d.not_helped, 0)
        self.assertEqual(d.last_not_helped, 0.0)

    def test_persistable_fields_includes_not_helped(self):
        self.assertIn('not_helped', _PERSISTABLE_FIELDS,
                       'not_helped 应在持久化字段列表')
        self.assertIn('last_not_helped', _PERSISTABLE_FIELDS,
                       'last_not_helped 应在持久化字段列表')


class TestB_RecordHelpedBidirectional(unittest.TestCase):
    """record_helped 应双向记 (yes++ helped, no++ not_helped)."""

    def setUp(self):
        self.reg = DirectiveRegistry()
        d = Directive(id='dy_test', text='hi', source_marker='test',
                       priority=5, ttl_days=30, trigger=lambda ctx: True)
        self.reg.directives['dy_test'] = d

    def test_helped_true_increments_helped(self):
        self.reg.record_helped('dy_test', helped=True)
        self.assertEqual(self.reg.directives['dy_test'].helped, 1)
        self.assertEqual(self.reg.directives['dy_test'].not_helped, 0)

    def test_helped_false_increments_not_helped(self):
        self.reg.record_helped('dy_test', helped=False)
        self.assertEqual(self.reg.directives['dy_test'].helped, 0)
        self.assertEqual(self.reg.directives['dy_test'].not_helped, 1)

    def test_multiple_no_accumulates(self):
        for _ in range(5):
            self.reg.record_helped('dy_test', helped=False)
        self.assertEqual(self.reg.directives['dy_test'].not_helped, 5)


class TestC_DecayRule4_NotHelpedReview(unittest.TestCase):
    """decay 规则 4: not_helped >= 10 AND helped == 0 → state=review."""

    def test_high_not_helped_zero_helped_goes_to_review(self):
        reg = DirectiveRegistry()
        d = Directive(id='dy_low', text='hi', source_marker='test',
                       priority=5, ttl_days=30, trigger=lambda ctx: True)
        d.not_helped = NOT_HELPED_REVIEW_THRESHOLD
        d.helped = 0
        d.fired = 15
        reg.directives['dy_low'] = d
        # 设 review_path 临时
        import tempfile
        reg.review_path = os.path.join(tempfile.gettempdir(), 'test_dy_review.json')
        try:
            stats = reg.apply_decay()
            self.assertEqual(reg.directives['dy_low'].state, STATE_REVIEW,
                              'not_helped >= 10 + helped=0 应进 review')
            self.assertGreaterEqual(stats['review'], 1)
        finally:
            if os.path.exists(reg.review_path):
                os.unlink(reg.review_path)


class TestD_DecayRule5_NotHelpedPriorityDrop(unittest.TestCase):
    """decay 规则 5: not_helped >= 5 AND helped/(h+nh) < 0.3 → priority drop."""

    def test_low_helped_ratio_drops_priority(self):
        reg = DirectiveRegistry()
        d = Directive(id='dy_mid', text='hi', source_marker='test',
                       priority=8, ttl_days=30, trigger=lambda ctx: True)
        d.not_helped = NOT_HELPED_PRIORITY_DROP
        d.helped = 1  # ratio = 1 / 6 ≈ 0.17 < 0.3
        d.fired = 10
        reg.directives['dy_mid'] = d
        import tempfile
        reg.review_path = os.path.join(tempfile.gettempdir(), 'test_dy_review2.json')
        try:
            initial_priority = d.priority
            reg.apply_decay()
            self.assertLess(reg.directives['dy_mid'].priority, initial_priority,
                            'priority 应下降')
        finally:
            if os.path.exists(reg.review_path):
                os.unlink(reg.review_path)

    def test_high_helped_ratio_does_not_drop(self):
        reg = DirectiveRegistry()
        d = Directive(id='dy_high', text='hi', source_marker='test',
                       priority=8, ttl_days=30, trigger=lambda ctx: True)
        d.not_helped = 5
        d.helped = 20  # ratio = 20 / 25 = 0.8 > 0.3
        d.fired = 30
        reg.directives['dy_high'] = d
        import tempfile
        reg.review_path = os.path.join(tempfile.gettempdir(), 'test_dy_review3.json')
        try:
            initial_priority = d.priority
            reg.apply_decay()
            # 高 helped 比率不应 drop
            self.assertEqual(reg.directives['dy_high'].priority, initial_priority,
                              'helped ratio 高时不应 drop priority')
        finally:
            if os.path.exists(reg.review_path):
                os.unlink(reg.review_path)


class TestE_LayeredInjectStaticCheck(unittest.TestCase):
    """central_nerve _assemble_prompt 含分层注入逻辑."""

    def test_central_nerve_has_layered_logic(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('directive_inject_config.json', src,
                       'central_nerve 应读 inject config')
        self.assertIn('_full_directives', src,
                       '应有 full directive list')
        self.assertIn('_brief_directives', src,
                       '应有 brief directive list')
        self.assertIn('max_full_directives', src,
                       '应配置 max_full')
        self.assertIn('always_full_priority_threshold', src,
                       '应配置 priority threshold')
        self.assertIn('ADDITIONAL DIRECTIVES', src,
                       '应有 brief block 标题')

    def test_inject_config_exists_with_correct_schema(self):
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'directive_inject_config.json',
        )
        self.assertTrue(os.path.exists(cfg_path),
                         'config 文件应存在')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        self.assertIn('max_full_directives', cfg)
        self.assertIn('always_full_priority_threshold', cfg)
        self.assertIn('brief_max_chars_per_directive', cfg)


class TestF_EvaluatorRecordsBoth(unittest.TestCase):
    """directive_evaluator helped/no 都回写 registry."""

    def test_evaluator_calls_record_helped_with_no(self):
        import jarvis_directive_evaluator
        with open(jarvis_directive_evaluator.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 应有 helped=False 路径
        self.assertIn('record_helped', src)
        self.assertIn('helped=False', src,
                       'evaluator 应在 is_followed=no 时调 record_helped(False)')


if __name__ == '__main__':
    unittest.main()
