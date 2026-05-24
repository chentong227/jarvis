# -*- coding: utf-8 -*-
"""[Reshape M6.W2 / 2026-05-24 18:00] worker_helpers 抽出验证.

抽出的 fn:
  - sanitize_trigger_time
  - detect_semantic_category + _SEMANTIC_CATEGORIES

向后兼容验证:
  - jarvis_worker_helpers 直接 import OK
  - jarvis_worker re-export 仍 work (老 caller `from jarvis_worker import ...`)
  - 行为与抽出前一致 (regression)
"""
from __future__ import annotations
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestM6W2WorkerHelpersSplit(unittest.TestCase):
    """W2 抽出: sanitize_trigger_time + detect_semantic_category 走 jarvis_worker_helpers."""

    def test_helpers_module_importable(self):
        """jarvis_worker_helpers 直接 import."""
        import jarvis_worker_helpers as h
        self.assertTrue(hasattr(h, 'sanitize_trigger_time'))
        self.assertTrue(hasattr(h, 'detect_semantic_category'))
        self.assertTrue(hasattr(h, '_SEMANTIC_CATEGORIES'))

    def test_worker_reexport_backward_compat(self):
        """from jarvis_worker import ... 老 caller 仍 work."""
        from jarvis_worker import (
            sanitize_trigger_time, detect_semantic_category, _SEMANTIC_CATEGORIES,
        )
        from jarvis_worker_helpers import (
            sanitize_trigger_time as h_st,
            detect_semantic_category as h_dc,
            _SEMANTIC_CATEGORIES as h_cat,
        )
        # re-export 必须是同一对象
        self.assertIs(sanitize_trigger_time, h_st)
        self.assertIs(detect_semantic_category, h_dc)
        self.assertIs(_SEMANTIC_CATEGORIES, h_cat)

    def test_sanitize_trigger_time_wake_pm_force_am(self):
        """起床动词 + LLM 给 14:00 → 强制改 02:00 (am)."""
        from jarvis_worker_helpers import sanitize_trigger_time
        # 14:00 起床 + 没 PM marker → AM
        out, was, reason = sanitize_trigger_time(
            '2026-05-24 14:00:00', 'set wake alarm', '两点起床'
        )
        self.assertTrue(was)
        self.assertEqual(reason, 'wake_verb_force_am')
        self.assertIn('02:00:00', out)

    def test_sanitize_trigger_time_short_input(self):
        """太短的 trigger_time_str → 不矫正."""
        from jarvis_worker_helpers import sanitize_trigger_time
        out, was, _ = sanitize_trigger_time('', '', '')
        self.assertFalse(was)
        out, was, _ = sanitize_trigger_time('short', '', '')
        self.assertFalse(was)

    def test_detect_semantic_category_basic(self):
        """各类别基本命中."""
        from jarvis_worker_helpers import detect_semantic_category
        self.assertEqual(detect_semantic_category('明天早上起床'), 'wake')
        self.assertEqual(detect_semantic_category('我去睡觉了'), 'sleep')
        self.assertEqual(detect_semantic_category('吃晚饭'), 'eat')
        self.assertEqual(detect_semantic_category('开会'), 'work')
        self.assertEqual(detect_semantic_category('做题'), 'study')
        self.assertEqual(detect_semantic_category('健身'), 'sport')
        self.assertEqual(detect_semantic_category('剪视频'), 'video')

    def test_detect_semantic_category_misc_and_priority(self):
        """无类别 → misc; 同时含 wake+sleep → wake (默认起床闹钟)."""
        from jarvis_worker_helpers import detect_semantic_category
        self.assertEqual(detect_semantic_category(''), 'misc')
        self.assertEqual(detect_semantic_category('随便聊聊'), 'misc')
        # 含 'wake' 和 'sleep' 都能命中 — 起床+睡觉 边界 case
        out = detect_semantic_category('起床睡觉')
        self.assertEqual(out, 'wake')


class TestM6W3TierKeywordsAlias(unittest.TestCase):
    """W3 抽出: TIER_*_KEYWORDS 4 lists 走 jarvis_worker_helpers."""

    def test_tier_lists_in_helpers(self):
        """4 个 list 都 export from helpers."""
        from jarvis_worker_helpers import (
            TIER_CRITICAL_KEYWORDS,
            TIER_FACTUAL_RECALL_KEYWORDS,
            TIER_TOOL_KEYWORDS,
            TIER_DEEP_KEYWORDS,
        )
        # 非空且类型正确
        self.assertIsInstance(TIER_CRITICAL_KEYWORDS, list)
        self.assertGreater(len(TIER_CRITICAL_KEYWORDS), 5)
        self.assertGreater(len(TIER_FACTUAL_RECALL_KEYWORDS), 5)
        self.assertGreater(len(TIER_TOOL_KEYWORDS), 10)
        self.assertGreater(len(TIER_DEEP_KEYWORDS), 10)

    def test_worker_class_attr_alias_to_helpers(self):
        """JarvisWorkerThread._TIER_*_KEYWORDS 与 helpers 是同一对象 (alias)."""
        from jarvis_worker import JarvisWorkerThread
        from jarvis_worker_helpers import (
            TIER_CRITICAL_KEYWORDS,
            TIER_FACTUAL_RECALL_KEYWORDS,
            TIER_TOOL_KEYWORDS,
            TIER_DEEP_KEYWORDS,
        )
        self.assertIs(JarvisWorkerThread._TIER_CRITICAL_KEYWORDS, TIER_CRITICAL_KEYWORDS)
        self.assertIs(JarvisWorkerThread._TIER_FACTUAL_RECALL_KEYWORDS, TIER_FACTUAL_RECALL_KEYWORDS)
        self.assertIs(JarvisWorkerThread._TIER_TOOL_KEYWORDS, TIER_TOOL_KEYWORDS)
        self.assertIs(JarvisWorkerThread._TIER_DEEP_KEYWORDS, TIER_DEEP_KEYWORDS)

    def test_tier_critical_contains_known_patterns(self):
        """TIER_CRITICAL 含 reminder/alarm 关键 pattern."""
        import re
        from jarvis_worker_helpers import TIER_CRITICAL_KEYWORDS
        joined = ' '.join(TIER_CRITICAL_KEYWORDS)
        self.assertIn('提醒我', joined)
        # 测一个 regex pattern 真能 match
        for pat in TIER_CRITICAL_KEYWORDS:
            try:
                if re.search(pat, 'remind me to drink water'):
                    return  # 至少一个 pattern hit
            except re.error:
                pass
        self.fail('No TIER_CRITICAL pattern matches "remind me ..."')


if __name__ == '__main__':
    unittest.main()
