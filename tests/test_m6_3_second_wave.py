# -*- coding: utf-8 -*-
"""[Reshape M6.3 second wave / 2026-05-24] 6 init section helper 抽离.

覆盖:
  - 6 个 init helper 真存在
  - _init_3_brain_legacy(api_key) 设置 right_brain/left_brain/l5_brain (None or instance)
  - _init_stm_persist 设置 _stm_persist_path / _stm_persist_max
  - _init_event_bus_swm 设置 self.event_bus
  - _init_working_feed 设置 self.working_feed
  - _init_plan_ledger 设置 self.plan_ledger
  - _init_skill_registry_bootstrap 不抛异常
"""
import os
import sys
import threading
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestInit6Helpers(unittest.TestCase):
    def test_all_methods_exist(self):
        from jarvis_central_nerve import CentralNerve
        methods = [
            # 🆕 [Reshape M3.G 真删 / 2026-05-24 17:00] _init_3_brain_legacy 已删除.
            # 不再 require '_init_3_brain_legacy' (主对话 100% 走 chat_bypass 单脑).
            '_init_stm_persist',
            '_init_event_bus_swm',
            '_init_working_feed',
            '_init_plan_ledger',
            '_init_skill_registry_bootstrap',
        ]
        for m in methods:
            self.assertTrue(hasattr(CentralNerve, m), f'missing {m}')

    def test_3_brain_method_and_attrs_removed(self):
        """🆕 [Reshape M3.G 真删 / 2026-05-24 17:00] verify M3.G 真删完成.

        老 _init_3_brain_legacy method + right_brain/left_brain/l5_brain attr 已删除.
        Sir 真测 SWM deprecated_3_brain_invoked event = 0 → 安全删除.
        老 test_init_3_brain_legacy_sets_attrs 用例迁到本 test 反向验证 (M3.G 真删).
        """
        from jarvis_central_nerve import CentralNerve
        # method 不应再存在
        self.assertFalse(
            hasattr(CentralNerve, '_init_3_brain_legacy'),
            'M3.G 真删未完成: _init_3_brain_legacy method 仍存在'
        )
        # 实例化后, 3 个 brain attr 不应存在 (CentralNerve.__new__ 不会 set 它们)
        n = CentralNerve.__new__(CentralNerve)
        self.assertFalse(hasattr(n, 'right_brain'),
                            'M3.G 真删未完成: right_brain attr 仍存在')
        self.assertFalse(hasattr(n, 'left_brain'),
                            'M3.G 真删未完成: left_brain attr 仍存在')
        self.assertFalse(hasattr(n, 'l5_brain'),
                            'M3.G 真删未完成: l5_brain attr 仍存在')

    def test_init_stm_persist_sets_basic_attrs(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.short_term_memory = []
        n._stm_max_size = 30
        n._stm_compress_threshold = 20
        n._stm_importance_scores = {}
        # restore + start_daemon 内部异常都被吞,helper 不该抛
        try:
            n._init_stm_persist()
        except Exception as e:
            self.fail(f'should not raise: {e}')
        self.assertEqual(n._stm_persist_path,
                          os.path.join('memory_pool', 'stm_recent.jsonl'))
        self.assertEqual(n._stm_persist_max, 50)
        self.assertEqual(n._stm_persist_interval_s, 30.0)
        self.assertFalse(n._stm_dirty)
        self.assertIsNotNone(n._stm_persist_lock)

    def test_init_event_bus_swm_sets_event_bus(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.state = None  # state 没初始化, 跳过 set_event_bus
        n._init_event_bus_swm()
        # event_bus 应被设 (None 或 ConversationEventBus instance)
        self.assertTrue(hasattr(n, 'event_bus'))

    def test_init_working_feed_sets_attrs(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n._init_working_feed()
        self.assertTrue(hasattr(n, 'working_feed'))
        self.assertTrue(hasattr(n, '_clipboard_watcher'))
        self.assertTrue(hasattr(n, '_ps_history_watcher'))

    def test_init_plan_ledger_sets_attr(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        n.event_bus = None
        n._init_plan_ledger()
        self.assertTrue(hasattr(n, 'plan_ledger'))

    def test_init_skill_registry_bootstrap_no_raise(self):
        from jarvis_central_nerve import CentralNerve
        n = CentralNerve.__new__(CentralNerve)
        try:
            n._init_skill_registry_bootstrap()
        except Exception as e:
            self.fail(f'should not raise: {e}')


if __name__ == '__main__':
    unittest.main()
