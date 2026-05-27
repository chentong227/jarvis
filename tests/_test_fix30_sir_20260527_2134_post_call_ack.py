# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 21:34 真测 P5] tool_call 后主脑只回 "Done, Sir." 太敷衍.

Sir 真测看到:
  🛠️ ✅ concerns.progress_update: sir_hydration_habit → 1 杯 (...)
  Done, Sir.
  📺 [Subtitle] 已完成。

Sir 反应: "这个回应好像太简单了, 而且好像没添加成功？"

根因: directive `habit_progress_routing` 教 emit FAST_CALL, 但**漏教
       STEP 3 怎么用 tool_result confirm 进度**. 对比 commitment_watcher
       directive 有 STEP 1/2/3 教 ack 模式, hydration directive 缺.

治本: directive 加 STEP 1-4 POST-CALL ACK section, 教主脑用 tool_result
       内的 `N/M 单位` 数据 ack — 含具体数字, 不许 "Done, Sir."

测试: 静态扫描 directive text 含必要 anchor (STEP 3, 数字, 反例).
"""
from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


class TestHabitProgressDirectiveHasPostCallAck(unittest.TestCase):
    """`habit_progress_routing` directive 必须含 STEP 1-4 POST-CALL ACK."""

    @classmethod
    def setUpClass(cls):
        with open(
            os.path.join(_REPO, 'jarvis_directives.py'),
            'r', encoding='utf-8'
        ) as f:
            cls.body = f.read()
        # 提取 habit_progress_routing directive 的 text (粗筛 by id anchor)
        import re
        m = re.search(
            r"id='habit_progress_routing'.*?trigger=",
            cls.body, re.DOTALL,
        )
        cls.directive_text = m.group(0) if m else ''

    def test_directive_found(self):
        """directive 存在."""
        self.assertTrue(self.directive_text,
            'habit_progress_routing directive 必须存在')

    def test_has_post_call_ack_section(self):
        """必须有 POST-CALL ACK 段."""
        self.assertIn('POST-CALL ACK', self.directive_text,
            'directive 必须含 POST-CALL ACK section (教 ack 模式)')

    def test_has_step_3_with_progress_number_examples(self):
        """STEP 3 必须有 N/M 进度数字示例."""
        # 至少 2 个具体进度数字示例 (e.g. 1/10, 3/, 10/10)
        import re
        matches = re.findall(r'\d+/\d+\s*杯', self.directive_text)
        self.assertGreaterEqual(len(matches), 2,
            f'STEP 3 必须含 ≥2 个 N/M 杯 进度示例, 得 {matches}')

    def test_explicitly_forbids_done_sir(self):
        """必须显式反例 'Done, Sir.' / '已完成'."""
        self.assertIn('Done, Sir', self.directive_text,
            'directive 必须显式反例 "Done, Sir."')
        # 至少一个反例 anchor
        bad_anchors = ['Done, Sir', '已完成', '好的']
        found = [a for a in bad_anchors if a in self.directive_text]
        self.assertGreaterEqual(len(found), 2,
            f'必须显式反例 ≥2 种敷衍话术 ({bad_anchors}), 得 {found}')

    def test_step_2_explains_tool_result_format(self):
        """STEP 2 必须解释 tool result 格式 (让主脑知 N/M 数据从哪来)."""
        self.assertIn('severity_delta', self.directive_text,
            'STEP 2 必须解释 tool result 含 severity_delta')

    def test_step_4_failure_case_no_lying(self):
        """STEP 4 必须教 tool fail 时真话, 不撒谎."""
        self.assertTrue(
            ('不撒谎' in self.directive_text or
             'fail' in self.directive_text.lower()),
            'STEP 4 必须 cover fail case'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
