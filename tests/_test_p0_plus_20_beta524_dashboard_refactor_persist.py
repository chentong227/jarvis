# -*- coding: utf-8 -*-
"""[P0+20-β.5.24 / 2026-05-19] Dashboard 全面重构 testcase.

Sir 01:58 反馈 (2 张截图):
- 'X' 拒绝说不存在 → 修 relational thread title fallback + 过滤短 preview
- 框太小看不到新建议 → main grid row weight 5
- 排版老旧 → 大 card-in-card + source + rationale + 时间
- 信息不够 → 4 类型整合 + 详情面板
- 全面重构

测试模式: 静态源码扫 + read_review_queues 行为模拟.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


DASHBOARD_PATH = os.path.join(ROOT, 'scripts', 'jarvis_dashboard.py')


# ============================================================
# Sub-A: layout 放大待处理 (main grid weight)
# ============================================================

class TestBeta524ALayoutWeights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(DASHBOARD_PATH)

    def test_marker(self):
        self.assertIn('β.5.24', self.src)

    def test_rowconfigure_weights(self):
        """main grid: row 1 (待处理) weight 必须 >= 5."""
        # 找 main.rowconfigure(1, weight=5)
        self.assertRegex(self.src,
            r"main\.rowconfigure\(1,\s*weight=5",
            'main rowconfigure(1) 必须 weight=5')

    def test_info_row_smaller(self):
        """row 0 (信息) weight 应小 (≤1) 让待处理放大."""
        self.assertRegex(self.src,
            r"main\.rowconfigure\(0,\s*weight=1",
            'row 0 信息 weight 必须 ≤1')


# ============================================================
# Sub-B: read_review_queues 4 类型整合 + thread title 修
# ============================================================

class TestBeta524BReviewQueues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(DASHBOARD_PATH)

    def test_thread_title_fallback(self):
        """relational thread 必须读 title (老 dashboard 漏)."""
        # 找 def read_review_queues 后面有 title 关键字
        idx = self.src.find('def read_review_queues')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 5000]
        self.assertIn('title', snippet,
            'read_review_queues 必须考虑 title 字段 (thread)')

    def test_highlights_what_fallback(self):
        """relational thread rationale 必须 fallback 到 highlights[0].what."""
        idx = self.src.find('def read_review_queues')
        snippet = self.src[idx:idx + 5000]
        self.assertIn('highlights', snippet)
        self.assertIn("hl[0].get('what'", snippet,
            '必须从 highlights[0].what 取 rationale')

    def test_cooldown_source_integrated(self):
        """cooldown_vocab.review_queue 必须接入 (β.5.23-B L7)."""
        self.assertIn('proactive_care_cooldown_vocab.json', self.src,
            '必须读 cooldown vocab')
        self.assertIn("'kind': 'cooldown'", self.src,
            'review item 必须有 cooldown kind')

    def test_short_preview_filtered(self):
        """preview len < 5 → 过滤 (防 'X' 类垃圾)."""
        self.assertIn('len(preview.strip()) < 5', self.src,
            '必须过滤短 preview')

    def test_no_5_cap(self):
        """不再 items[:5] / items_cr[:5] 截断 — 让 Sir 看全.
        不检 [:300] (rationale truncate 是 OK的)."""
        import re
        idx = self.src.find('def read_review_queues')
        snippet = self.src[idx:idx + 6000]
        # 检 list slicing [:5] / [:3] 但不检 truncate [:300]
        matches = re.findall(r'\b(?:items_cr|items_dr|rr|lst|rq|items)\[:5\]', snippet)
        self.assertEqual(len(matches), 0,
            f'不该再 items[:5] 截断, found: {matches}')

    def test_rich_fields(self):
        """每条 item 必须有 source + rationale + created_iso."""
        idx = self.src.find('def read_review_queues')
        snippet = self.src[idx:idx + 6000]
        for field in ('rationale', 'source', 'created_iso'):
            self.assertIn(f"'{field}'", snippet,
                f"item 必须有 {field} 字段")


# ============================================================
# Sub-C: render_review_buttons 大卡片 + 详情
# ============================================================

class TestBeta524CRenderRichCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(DASHBOARD_PATH)

    def test_render_uses_h3_font_for_preview(self):
        """preview 必须用 h3_font (大字号)."""
        idx = self.src.find('def _render_review_buttons')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 5000]
        # 找 ✦ preview 那行用 h3_font
        self.assertIn('h3_font', snippet,
            'preview 应使用 h3_font 大字号')

    def test_render_shows_source(self):
        idx = self.src.find('def _render_review_buttons')
        snippet = self.src[idx:idx + 5000]
        self.assertIn('来源:', snippet,
            'card 必须显 source 标签')

    def test_render_shows_rationale(self):
        idx = self.src.find('def _render_review_buttons')
        snippet = self.src[idx:idx + 5000]
        self.assertIn('rationale', snippet,
            'card 必须显 rationale 详情')

    def test_render_4_kind_labels(self):
        """4 类型都有中文 label."""
        idx = self.src.find('def _render_review_buttons')
        snippet = self.src[idx:idx + 5000]
        for zh in ('长期关心', '你们之间', '临时规则', 'Cooldown'):
            self.assertIn(zh, snippet,
                f"4 类型 label 必须有 {zh}")


# ============================================================
# Sub-D: action_activate/reject 加 cooldown 支持
# ============================================================

class TestBeta524DActionCooldownSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(DASHBOARD_PATH)

    def test_activate_supports_cooldown(self):
        idx = self.src.find('def action_activate_review')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 2000]
        self.assertIn("kind == 'cooldown'", snippet,
            'activate 必须支持 cooldown kind')
        self.assertIn('_apply_cooldown_proposal', snippet,
            '必须调 _apply_cooldown_proposal')

    def test_reject_supports_cooldown(self):
        idx = self.src.find('def action_reject_review')
        self.assertGreater(idx, 0)
        snippet = self.src[idx:idx + 2000]
        self.assertIn("kind == 'cooldown'", snippet,
            'reject 必须支持 cooldown kind')

    def test_drop_cooldown_helper(self):
        self.assertIn('def _drop_cooldown_review_entry', self.src,
            '必须有 _drop_cooldown_review_entry helper')

    def test_extra_param_supported(self):
        """action_activate/reject 必须接受 extra=None 参数."""
        self.assertIn('extra=None', self.src,
            '必须有 extra 参数')


# ============================================================
# Sub-E: runtime - read_review_queues 真读 Sir 实际数据
# ============================================================

class TestBeta524ERuntime(unittest.TestCase):
    """runtime 测真实数据."""

    def test_real_data_no_x_preview(self):
        """读真实 review json, 确认没有 preview='X' 这种垃圾."""
        import jarvis_dashboard as jd
        data = jd.read_review_queues()
        self.assertIn('items', data)
        for it in data['items']:
            preview = it.get('preview', '')
            self.assertGreaterEqual(len(preview.strip()), 5,
                f"preview '{preview}' 太短, 应被过滤")

    def test_relational_threads_now_visible(self):
        """实际 relational_review.json 有 9 个 thread, 应都被读出 (现已 title fallback).
        前提: 该文件实际存在 + 有 shared_history_threads."""
        rel_path = os.path.join(ROOT, 'memory_pool', 'relational_review.json')
        if not os.path.exists(rel_path):
            self.skipTest('relational_review.json 不存在')
        with open(rel_path, 'r', encoding='utf-8') as f:
            rel = json.load(f)
        n_threads = len(rel.get('shared_history_threads', []) or [])
        if n_threads == 0:
            self.skipTest('实际 thread 数 0')
        import jarvis_dashboard as jd
        data = jd.read_review_queues()
        n_relational = sum(1 for i in data['items']
                            if i['kind'].startswith('relational'))
        self.assertGreaterEqual(n_relational, n_threads,
            f"应至少读出 {n_threads} 条 relational, 实际只 {n_relational}")

    def test_all_items_have_required_fields(self):
        """每条 review item 必须有 kind/id/preview/source/rationale."""
        import jarvis_dashboard as jd
        data = jd.read_review_queues()
        for it in data['items']:
            for k in ('kind', 'id', 'preview', 'source', 'rationale'):
                self.assertIn(k, it, f"item 必须有 {k}: {it}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
