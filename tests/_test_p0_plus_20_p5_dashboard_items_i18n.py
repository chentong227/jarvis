# -*- coding: utf-8 -*-
"""[P5-fix-items-i18n / 2026-05-22] Dashboard /items 页面 i18n 翻译完善 verify

Sir 让"我们的事翻译" — 补 frontend i18n maps 覆盖:
  - state fallback (archived/rejected/pending/done/overdue/expired/fired/...)
  - category fallback (commitment/promise/watch_task/milestone/...)
  - field key (priority/severity/threshold/tags/...)
  - proposed_by (sir_request_reflector/l7_reflector/...)
  - sidebar 状态过滤补 archived

Cover:
  A. 5 个 helper 函数都加在 _ITEMS_HTML alpine app
  B. catIcon 补 new categories
  C. categoryZh 覆盖 22 个常用 category
  D. stateZh 覆盖 14 个常用 state
  E. fieldKeyZh 覆盖 40+ 常用 field key
  F. proposerZh 覆盖 15+ reflector / extractor
  G. sidebar 加 'archived' filter (老只有 review/active)
  H. card state badge 用 stateZh + stateClass
  I. detail panel field label 用 fieldKeyZh + 原 key 进 title
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dashboard_src() -> str:
    """读 dashboard_web.py 全文."""
    p = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scripts', 'jarvis_dashboard_web.py'
    )
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


class TestA_HelpersDefined(unittest.TestCase):
    """5 helper 函数都加在 _ITEMS_HTML alpine app."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_categoryZh_defined(self):
        self.assertIn('categoryZh(c)', self.src)

    def test_stateZh_defined(self):
        self.assertIn('stateZh(st)', self.src)

    def test_stateClass_defined(self):
        self.assertIn('stateClass(st)', self.src)

    def test_fieldKeyZh_defined(self):
        self.assertIn('fieldKeyZh(k)', self.src)

    def test_proposerZh_defined(self):
        self.assertIn('proposerZh(p)', self.src)


class TestB_CategoryZhCoverage(unittest.TestCase):
    """categoryZh 覆盖常用 category."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_core_categories(self):
        for cat in ['concern', 'inside_joke', 'thread', 'protocol',
                     'unfinished', 'screen_tease', 'struggle', 'directive',
                     'sleep_pattern', 'callback', 'cooldown', 'profile']:
            self.assertIn(f"{cat}:", self.src,
                            f"categoryZh 应有 {cat}")

    def test_new_categories_added(self):
        """fix14: 加 commitment/promise/watch_task/milestone/memory_correction."""
        for cat in ['commitment', 'promise', 'watch_task', 'milestone',
                     'memory_correction']:
            self.assertIn(f"{cat}:", self.src,
                            f"categoryZh 应有 {cat} (P5-fix-items-i18n)")


class TestC_StateZhCoverage(unittest.TestCase):
    """stateZh 覆盖 14 个常用 state."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_active_states(self):
        for st in ['review', 'active', 'archived', 'rejected']:
            self.assertIn(f"{st}:", self.src,
                            f"stateZh 应有 {st}")

    def test_workflow_states(self):
        """commitment / promise 等用的 state."""
        for st in ['pending', 'done', 'overdue', 'expired', 'fired',
                    'cancelled', 'fulfilled', 'untracked']:
            self.assertIn(f"{st}:", self.src,
                            f"stateZh 应有 {st}")


class TestD_FieldKeyZh(unittest.TestCase):
    """fieldKeyZh 翻译常用 field key."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_basic_keys(self):
        for k in ['priority', 'severity', 'urgency', 'threshold',
                   'cooldown', 'tags', 'keywords', 'state', 'category']:
            self.assertIn(f"{k}:'", self.src,
                            f"fieldKeyZh 应有 {k}")

    def test_watch_task_keys(self):
        for k in ['what_to_watch', 'trigger_evidence',
                   'notify_msg_en', 'notify_msg_zh',
                   'sir_request', 'jarvis_ack']:
            self.assertIn(f"{k}:'", self.src,
                            f"fieldKeyZh 应有 {k} (WatchTask)")


class TestE_ProposerZh(unittest.TestCase):
    """proposerZh 覆盖 reflector / extractor."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_sir_default(self):
        self.assertIn("Sir 拍板", self.src,
                       'proposerZh 应返 "Sir 拍板" 默认')

    def test_reflectors(self):
        for p in ['sir_request_reflector', 'l7_reflector',
                   'concerns_reflector', 'weekly_reflector',
                   'intent_resolver', 'watch_task_registrar']:
            self.assertIn(f"{p}:'", self.src,
                            f"proposerZh 应有 {p}")


class TestF_SidebarStateFilter(unittest.TestCase):
    """sidebar 状态过滤补 archived (老只有 review/active)."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_archived_in_filter(self):
        # 新路径应该有 archived
        self.assertIn("'', 'review', 'active', 'archived'", self.src,
                       'sidebar 状态过滤应含 archived (新)')

    def test_uses_stateZh_helper(self):
        """sidebar 渲染状态用 stateZh helper 不再硬编码."""
        # 老硬编码版本
        old_hardcoded = "st==='review' ? '🔥 待拍板' : '✅ 已生效'"
        self.assertNotIn(old_hardcoded, self.src,
                          '老硬编码状态文字应被 stateZh helper 替')


class TestG_CardStateBadgeUsesHelper(unittest.TestCase):
    """card state badge 用 stateZh + stateClass."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_card_uses_stateClass(self):
        self.assertIn(':class="stateClass(item.state)"', self.src,
                       'card state badge :class 应用 stateClass helper')

    def test_card_uses_stateZh(self):
        self.assertIn('x-text="stateZh(item.state)"', self.src,
                       'card state badge x-text 应用 stateZh helper')


class TestH_DetailPanelI18n(unittest.TestCase):
    """detail panel field label 用 fieldKeyZh + 原 key 进 title."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_label_uses_fieldKeyZh(self):
        self.assertIn('x-text="fieldKeyZh(key)"', self.src,
                       'detail panel <label> 应用 fieldKeyZh')

    def test_label_has_title_with_raw_key(self):
        # 原英文 key 进 title (hover 看)
        self.assertIn(':title="key"', self.src,
                       'detail panel <label> 应有 :title="key" 让 Sir hover 看原 key')

    def test_detail_header_uses_categoryZh(self):
        self.assertIn('categoryZh(detail.category)', self.src,
                       'detail panel 头部分类应用 categoryZh')

    def test_detail_header_uses_stateZh(self):
        self.assertIn('stateZh(detail.state)', self.src,
                       'detail panel 头部状态应用 stateZh')


class TestI_CardProposerUsesHelper(unittest.TestCase):
    """card 提议者文字用 proposerZh."""

    def setUp(self):
        self.src = _load_dashboard_src()

    def test_proposer_label_uses_helper(self):
        self.assertIn("提议者: ' + proposerZh(item.proposed_by)", self.src,
                       'card 提议者文字应用 proposerZh helper')


if __name__ == '__main__':
    unittest.main()
