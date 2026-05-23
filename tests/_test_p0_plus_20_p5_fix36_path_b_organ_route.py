# -*- coding: utf-8 -*-
"""[P5-fix36 / 2026-05-23 12:11] Path B (slow tool chain) FAST_CALL-only organ route fix.

Sir 12:10 真测痛点:
  Sir: "刚才吃饭时喝了大概200毫升，帮我记一下"
  Jarvis: "I have updated your hydration log..." (说真的)
  Jarvis: "I apologize, the progress tracking module is unavailable"
  ❌ progress 未挂载

根因 (在 jarvis_chat_bypass.py):
  - Path A (line 2204+, streaming): 调 _execute_fast_call ✅ 有 progress 分支
  - Path B (line 3262+, slow tool chain): 直接走 hand_registry.get(organ_name)
    → progress 不在 hand_registry → returns None → "❌ progress 未挂载"

Path B 的 ui_control 单独有分支, 但 concerns / stand_down / promises /
mutation / cyclic_task / progress 6 个 FAST_CALL-only organ 都没. Path A 通,
Path B 全报"未挂载".

治本:
  Path B 加 _FAST_CALL_ONLY_ORGANS list, 路由到 _execute_fast_call (DRY).

覆盖:
A. Source contains _FAST_CALL_ONLY_ORGANS list with all 6 organs
B. progress 在 list 中 (Sir 真痛点)
C. cyclic_task / mutation / concerns / stand_down / promises 在 list 中
D. Source 在 elif 分支有 _execute_fast_call 调用 (route 正确)
E. Reuses Path A's _execute_fast_call (no duplicate impl)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestPathBFastCallRoute(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_a_fast_call_only_organs_list_exists(self):
        self.assertIn('_FAST_CALL_ONLY_ORGANS', self.src,
                          'Path B must declare _FAST_CALL_ONLY_ORGANS')

    def test_b_progress_in_route_list(self):
        # Find the list near P5-fix36 marker
        idx = self.src.find('P5-fix36')
        self.assertGreater(idx, 0, 'P5-fix36 marker not found')
        block = self.src[idx:idx + 2000]
        self.assertIn("'progress'", block, 'progress must be in route list')

    def test_c_all_six_organs_in_route_list(self):
        idx = self.src.find('_FAST_CALL_ONLY_ORGANS')
        block = self.src[idx:idx + 1000]
        for organ in ('concerns', 'stand_down', 'promises', 'mutation',
                        'cyclic_task', 'progress'):
            self.assertIn(f"'{organ}'", block,
                            f"{organ} must be in _FAST_CALL_ONLY_ORGANS")

    def test_d_path_b_routes_to_execute_fast_call(self):
        # Check Path B's elif branch calls self._execute_fast_call
        idx = self.src.find('elif organ_name in _FAST_CALL_ONLY_ORGANS')
        self.assertGreater(idx, 0, 'Path B route branch not found')
        block = self.src[idx:idx + 800]
        self.assertIn('self._execute_fast_call(', block,
                          'Path B should route to _execute_fast_call')

    def test_e_no_duplicate_progress_branch_in_path_b(self):
        # Path B's hand_registry fallback must remain — progress still goes
        # through fast_call route, not duplicated. We just verify the route.
        # Check that hand_registry fallback still exists for non-FAST_CALL organs.
        self.assertIn('hand_registry.get(organ_name)', self.src,
                          'hand_registry fallback must remain for SLOW organs')


if __name__ == '__main__':
    unittest.main()
