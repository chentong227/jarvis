# -*- coding: utf-8 -*-
"""
[P0+20-β.5.17 / 2026-05-19] proactive_care 也加入 focus mode 触发列表

Sir 22:21 实测 - ProactiveCare 主动关心 voice 通道发声后, Sir 没机会回应:
原 focus_lock 触发列表只含 ('offer_help', 'commitment_check'), 不含 proactive_care.
β.5.13 把 ProactiveCare 也走 stream_nudge 主脑 reaction_space 决策 — 主脑选 voice
发声的 proactive_care 应当跟 offer_help 等同待遇 (用户期望回应).

修法 (jarvis_worker.py:2964): 触发列表加 'proactive_care'.

测试覆盖:
  A. trigger 列表字面含 'proactive_care'
  B. focus_lock log 用 nudge_type 字面 (不写死 offer_help)
  C. β.5.17 marker comment 持久化
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBeta517ProactiveCareFocusMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_worker.py'))

    def test_marker_present(self):
        self.assertIn('β.5.17', self.src,
            'β.5.17 marker 必须在 jarvis_worker.py')

    def test_proactive_care_in_focus_trigger_list(self):
        """触发列表含 'proactive_care'."""
        self.assertIn(
            '("offer_help", "commitment_check", "proactive_care")',
            self.src,
            '触发列表必须含 proactive_care (β.5.17)')

    def test_focus_lock_log_uses_dynamic_nudge_type(self):
        """log 用 {nudge_type} 字面而不是写死 'offer_help'."""
        self.assertIn('[Focus Lock] {nudge_type}', self.src,
            'Focus Lock log 应用动态 nudge_type 不写死 offer_help')

    def test_legacy_check_in_path_preserved(self):
        """check_in 单独路径 (45s soft focus) 保留, 不动."""
        self.assertIn('if nudge_type == "check_in"', self.src,
            'check_in 单独 45s 路径保留 (β.5.17 不动)')


if __name__ == '__main__':
    unittest.main()
