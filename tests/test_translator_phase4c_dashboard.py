# -*- coding: utf-8 -*-
"""[Translator Phase 4.C / 2026-05-24 23:00] /translator dashboard page test.

详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.8

覆盖 (静态 grep — 完整 e2e flask test 太重, 这里仅验 endpoints + nav link 都已加):
  A. /api/translator endpoint 定义
  B. /api/translator/<alias_id>/<action> 定义
  C. /translator page 定义 + 含 stats/aliases 渲染逻辑
  D. 主 dashboard nav 含 📚 Translator 入口
  E. API 调用 scripts/translator_alias_dump.py 做 activate/reject
  F. /api/translator 返 reflector + translator_runtime stats (闭环 4.A)
"""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestPhase4CDashboard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_api_translator_endpoint(self):
        self.assertIn("@app.route('/api/translator')", self.src)
        self.assertIn('def api_translator():', self.src)

    def test_api_translator_action_endpoint(self):
        self.assertIn("@app.route('/api/translator/<alias_id>/<action>'", self.src)
        self.assertIn('def api_translator_action(', self.src)

    def test_api_action_calls_cli_script(self):
        """action API 必须 subprocess invoke scripts/translator_alias_dump.py."""
        self.assertIn('translator_alias_dump.py', self.src)
        self.assertIn('subprocess', self.src.lower())

    def test_api_validates_action(self):
        """action 必须 in ('activate', 'reject')."""
        self.assertIn("if action not in ('activate', 'reject')", self.src)

    def test_translator_page_endpoint(self):
        self.assertIn("@app.route('/translator')", self.src)
        self.assertIn('def page_translator():', self.src)

    def test_main_nav_has_translator_link(self):
        """主 dashboard 必须有 /translator nav link."""
        self.assertIn('href="/translator"', self.src,
                      '主 dashboard nav 必须含 /translator 入口')
        self.assertIn('📚 Translator', self.src)

    def test_api_returns_reflector_stats(self):
        """/api/translator 应含 reflector + translator_runtime stats (闭环 Phase 4.A)."""
        self.assertIn("from jarvis_translator_reflector import get_default_reflector",
                      self.src)
        self.assertIn("from jarvis_translator import get_default_translator",
                      self.src)
        self.assertIn("'translator_runtime'", self.src)

    def test_api_sorts_review_first(self):
        """API 应按 status rank 排序 (review > active > rejected) + hit_count desc."""
        self.assertIn("'review': 0", self.src)
        self.assertIn("'active': 1", self.src)
        self.assertIn("'rejected': 2", self.src)
        # hit_count desc (用 -int)
        self.assertIn("-int(a.get('hit_count', 0) or 0)", self.src)

    def test_page_html_has_status_badges(self):
        """page html 含 status-review/active/rejected badge style."""
        self.assertIn('.status-review', self.src)
        self.assertIn('.status-active', self.src)
        self.assertIn('.status-rejected', self.src)

    def test_page_html_has_alpine(self):
        """page 用 Alpine.js (轻量 reactive)."""
        self.assertIn('alpinejs', self.src.lower())
        self.assertIn('x-data="trVocab()"', self.src)


if __name__ == '__main__':
    unittest.main()
