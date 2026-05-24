# -*- coding: utf-8 -*-
"""[Reshape M3.B / 2026-05-24] 同名 class 冲突消除验证.

覆盖:
  - jarvis_blood.CorrectionEntry / MemoryFragment / PromptLayer 已删 (避免 import 冲突)
  - jarvis_memory_core 这 3 个仍然在 (单源)
  - 任何 caller 都从 memory_core 拿到正确 class
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBloodDuplicatesRemoved(unittest.TestCase):
    """blood 的 3 个 placeholder dataclass 已删."""

    def test_blood_correction_entry_gone(self):
        import jarvis_blood
        self.assertFalse(hasattr(jarvis_blood, 'CorrectionEntry'),
                          'M3.B: jarvis_blood.CorrectionEntry 应已删 (唯一定义在 memory_core)')

    def test_blood_memory_fragment_gone(self):
        import jarvis_blood
        self.assertFalse(hasattr(jarvis_blood, 'MemoryFragment'),
                          'M3.B: jarvis_blood.MemoryFragment 应已删 (唯一定义在 memory_core)')

    def test_blood_prompt_layer_gone(self):
        import jarvis_blood
        self.assertFalse(hasattr(jarvis_blood, 'PromptLayer'),
                          'M3.B: jarvis_blood.PromptLayer 应已删 (唯一定义在 memory_core)')


class TestMemoryCoreStillHasClasses(unittest.TestCase):
    """memory_core 的 3 个 class 仍是唯一 source of truth."""

    def test_memory_core_correction_entry(self):
        from jarvis_memory_core import CorrectionEntry
        self.assertIsNotNone(CorrectionEntry)

    def test_memory_core_memory_fragment(self):
        from jarvis_memory_core import MemoryFragment
        self.assertIsNotNone(MemoryFragment)
        # 验证 field
        mf = MemoryFragment(source='test', content='x')
        self.assertEqual(mf.source, 'test')

    def test_memory_core_prompt_layer(self):
        from jarvis_memory_core import PromptLayer
        self.assertIsNotNone(PromptLayer)


class TestSoulRouterUnique(unittest.TestCase):
    """SoulRouter 唯一 source of truth = jarvis_routing.SoulRouter (M3.B)."""

    def test_enhanced_soul_router_gone(self):
        import jarvis_enhanced
        self.assertFalse(hasattr(jarvis_enhanced, 'SoulRouter'),
                          'M3.B: jarvis_enhanced.SoulRouter 应已删 (唯一在 routing)')

    def test_routing_soul_router_intact(self):
        from jarvis_routing import SoulRouter
        self.assertIsNotNone(SoulRouter)
        # 验证 advanced version (含 BILINGUAL_BRIDGE)
        self.assertTrue(hasattr(SoulRouter, 'BILINGUAL_BRIDGE'),
                         'M3.B: routing.SoulRouter 应是 advanced version 含 BILINGUAL_BRIDGE')


class TestBloodCoreClassesIntact(unittest.TestCase):
    """blood.py 的核心 dataclass (Action / ExecutionResult / JarvisBlood / FeedbackSignal / TaskSnapshot) 不受影响."""

    def test_blood_action(self):
        from jarvis_blood import Action
        self.assertIsNotNone(Action)

    def test_blood_execution_result(self):
        from jarvis_blood import ExecutionResult
        self.assertIsNotNone(ExecutionResult)

    def test_blood_jarvis_blood(self):
        from jarvis_blood import JarvisBlood
        self.assertIsNotNone(JarvisBlood)

    def test_blood_feedback_signal(self):
        from jarvis_blood import FeedbackSignal
        self.assertIsNotNone(FeedbackSignal)

    def test_blood_task_snapshot(self):
        from jarvis_blood import TaskSnapshot
        self.assertIsNotNone(TaskSnapshot)


if __name__ == '__main__':
    unittest.main()
