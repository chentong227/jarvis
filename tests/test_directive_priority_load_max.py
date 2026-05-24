# -*- coding: utf-8 -*-
"""[Sir 2026-05-24 22:30 真测 hydration BUG 治本] priority load max(persisted, defined).

源 BUG:
  Sir 真测 "我喝了 8 杯水" → 主脑 emit `progress.set` 而不是 `concerns.progress_update`
  → fail → 熔断收尾 → Sir 看到 "didn't manage logging".

根因:
  habit_progress_routing directive .py/JSON 定义 priority=13, 但 persisted=10
  (老 BUG-4 fix 前 priority=11, evaluator not_helped=6 → decay → 10).
  load() 无脑 setattr(d, 'priority', persisted=10) → 重启后 priority=10.
  progress_tracker_dispatcher priority=11 > 10 → 主脑听后者 → emit progress.set
  → track_id 'sir_hydration_habit' 不存在 → fail.

修法:
  load() 时 priority 取 max(persisted, defined) — Sir 准则 7 元否决 +
  .py/JSON 显式升级永远优先, persisted decay 不覆盖. 历史计数 (fired/helped/
  not_helped/last_*) 仍正常 restore (audit 可见).
"""
import os
import json
import tempfile
import unittest
from unittest.mock import patch


class TestDirectivePriorityLoadMax(unittest.TestCase):
    """load() 时 priority 取 max(persisted, defined)."""

    def setUp(self):
        from jarvis_directives import DirectiveRegistry, Directive
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', suffix='.json', delete=False
        )
        self.tmp.close()
        self.reg = DirectiveRegistry(persist_path=self.tmp.name)
        # 注册一个 priority=13 的 directive
        self.reg.register(Directive(
            id='test_directive', priority=13, ttl_days=90,
            text='test', trigger=lambda ctx: True,
        ))

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_persisted_lower_priority_does_not_override(self):
        """persisted priority=10 (老 decay 痕迹), defined=13 → load 后取 13."""
        # 模拟 persisted state: priority 已被 decay 到 10
        persisted = {
            'test_directive': {
                'priority': 10,
                'fired': 6,
                'not_helped': 6,
                'helped': 0,
                'state': 'active',
            }
        }
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump(persisted, f)
        n = self.reg.load()
        self.assertEqual(n, 1)
        d = self.reg.get('test_directive')
        self.assertEqual(d.priority, 13,
                         'persisted 10 不应覆盖 defined 13 — 取 max')
        # 但 fired/not_helped 仍 restore (history audit)
        self.assertEqual(d.fired, 6, 'fired 计数应正常 restore')
        self.assertEqual(d.not_helped, 6, 'not_helped 应正常 restore')

    def test_persisted_higher_priority_used(self):
        """persisted priority=15 > defined=13 → 取 max = 15 (尊重 persisted)."""
        persisted = {
            'test_directive': {
                'priority': 15,  # 反过来情况
                'fired': 0,
                'not_helped': 0,
                'state': 'active',
            }
        }
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump(persisted, f)
        self.reg.load()
        d = self.reg.get('test_directive')
        self.assertEqual(d.priority, 15, '取 max — persisted 高时尊重持久化')

    def test_persisted_equal_priority(self):
        """persisted == defined → 无变化."""
        persisted = {
            'test_directive': {'priority': 13, 'fired': 3, 'state': 'active'},
        }
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump(persisted, f)
        self.reg.load()
        d = self.reg.get('test_directive')
        self.assertEqual(d.priority, 13)
        self.assertEqual(d.fired, 3)

    def test_no_priority_in_persisted(self):
        """persisted 没 priority 字段 → defined 不变."""
        persisted = {
            'test_directive': {'fired': 5, 'state': 'active'},
        }
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump(persisted, f)
        self.reg.load()
        d = self.reg.get('test_directive')
        self.assertEqual(d.priority, 13)
        self.assertEqual(d.fired, 5)


class TestHabitProgressRoutingTopPriority(unittest.TestCase):
    """end-to-end: habit_progress_routing 在 default registry 必须 priority >= 13.
    
    这是 Sir 22:30 真测 BUG 的最终验证 — directive 必须 outrank
    progress_tracker_dispatcher (11) 和 correction_dispatcher (12).
    """

    def test_habit_routing_outrank_progress_dispatcher(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        habit = reg.get('habit_progress_routing')
        prog = reg.get('progress_tracker_dispatcher')
        self.assertIsNotNone(habit, 'habit_progress_routing 必须注册')
        self.assertIsNotNone(prog, 'progress_tracker_dispatcher 必须注册')
        self.assertGreater(habit.priority, prog.priority,
                           f'habit_routing (P{habit.priority}) 必须高于 '
                           f'progress_tracker_dispatcher (P{prog.priority})')

    def test_habit_routing_priority_at_least_13(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        habit = reg.get('habit_progress_routing')
        self.assertGreaterEqual(habit.priority, 13,
                                f'priority 必须 >= 13 (实际 {habit.priority})')

    def test_habit_routing_outrank_correction_dispatcher(self):
        from jarvis_directives import get_default_registry
        reg = get_default_registry()
        habit = reg.get('habit_progress_routing')
        corr = reg.get('correction_dispatcher')
        if corr:  # 可能此 directive 不在
            self.assertGreaterEqual(habit.priority, corr.priority,
                                    'habit_routing 必须 ≥ correction_dispatcher')


if __name__ == '__main__':
    unittest.main()
