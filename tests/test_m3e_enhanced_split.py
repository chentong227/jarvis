# -*- coding: utf-8 -*-
"""[Reshape M3.E / 2026-05-24] jarvis_enhanced.py 拆 3 file — facade re-export.

覆盖:
  - 3 个新 module 真存在 (jarvis_proactive_shield / _companion / _skill_tree_tracker)
  - 直接 import 工作 (新风格)
  - 老 facade `from jarvis_enhanced import X` 仍工作 (backward compat)
  - 拆出来的 class 是同一对象 (id check, no double class)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestSplitFiles(unittest.TestCase):
    def test_three_new_files_exist(self):
        for name in ['jarvis_proactive_shield.py',
                      'jarvis_proactive_companion.py',
                      'jarvis_skill_tree_tracker.py']:
            self.assertTrue(os.path.exists(os.path.join(ROOT, name)),
                              f'{name} 应存在')

    def test_direct_imports_work(self):
        from jarvis_proactive_shield import ProactiveShield
        from jarvis_proactive_companion import ProactiveCompanion, get_user_idle_seconds
        from jarvis_skill_tree_tracker import SkillTreeTracker
        self.assertTrue(ProactiveShield is not None)
        self.assertTrue(ProactiveCompanion is not None)
        self.assertTrue(SkillTreeTracker is not None)
        self.assertTrue(callable(get_user_idle_seconds))

    def test_facade_reexport_works(self):
        """老 caller `from jarvis_enhanced import X` 仍 work."""
        from jarvis_enhanced import ProactiveShield, ProactiveCompanion, SkillTreeTracker
        self.assertTrue(ProactiveShield is not None)
        self.assertTrue(ProactiveCompanion is not None)
        self.assertTrue(SkillTreeTracker is not None)

    def test_no_double_class(self):
        """直接 import vs facade re-export 应是同一 class object."""
        from jarvis_proactive_shield import ProactiveShield as Direct
        from jarvis_enhanced import ProactiveShield as ViaFacade
        self.assertIs(Direct, ViaFacade,
                       'facade re-export 应是同一 class, 否则 isinstance 会破')

    def test_enhanced_facade_size(self):
        """jarvis_enhanced.py 应是 facade 短文件 (< 60 行), 不再 739 行."""
        with open(os.path.join(ROOT, 'jarvis_enhanced.py'),
                   encoding='utf-8') as f:
            lines = f.readlines()
        self.assertLess(len(lines), 60,
                          f'facade 应短 (<60), 实际 {len(lines)}')


if __name__ == '__main__':
    unittest.main()
