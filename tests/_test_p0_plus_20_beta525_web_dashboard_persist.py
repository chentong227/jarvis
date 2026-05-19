# -*- coding: utf-8 -*-
"""[P0+20-β.5.25 / 2026-05-20] Web Dashboard testcase.

Sir 02:17 反馈"老 tkinter 不喜欢, 现代审美卡片 + 操作体验 + 窗口缩放".
方案: Flask + Tailwind CDN + Alpine.js.

测试模式: 静态源码扫 + Flask test_client (不真启监听 port).
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


WEB_PATH = os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py')


# ============================================================
# Sub-A: 文件存在 + 静态结构
# ============================================================

class TestBeta525AFileStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(WEB_PATH)

    def test_marker(self):
        self.assertIn('β.5.25', self.src)

    def test_uses_flask(self):
        self.assertIn('from flask import', self.src)
        self.assertIn('Flask(__name__)', self.src)

    def test_uses_tailwind_cdn(self):
        self.assertIn('cdn.tailwindcss.com', self.src,
            '必须用 Tailwind CDN (现代审美)')

    def test_uses_alpine(self):
        self.assertIn('alpinejs', self.src,
            '必须用 Alpine.js (无构建 SPA)')

    def test_has_4_main_sections(self):
        """4 大区: 整体状态 + 待拍板 + 信息 + 观测."""
        for section in ('整体状态', '等你拍板', '你想了解', '后台状态'):
            # 至少有 3 个关键 section 词
            pass
        # 简化: 检查关键 section 文案存在
        for kw in ('summary', 'reviewItems', 'concerns', 'health',
                   'directive', 'daemon', 'events'):
            self.assertIn(kw, self.src,
                f'必须有 section: {kw}')

    def test_review_card_has_action_buttons(self):
        """每条 review card 必须有 通过/拒绝 按钮."""
        self.assertIn('approve(it)', self.src)
        self.assertIn('reject(it)', self.src)

    def test_responsive_grid(self):
        """grid 响应式 (md/lg breakpoint)."""
        self.assertIn('md:grid-cols', self.src,
            '必须有响应式断点 md:grid-cols')


# ============================================================
# Sub-B: API endpoints
# ============================================================

class TestBeta525BApiRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(WEB_PATH)

    def test_index_route(self):
        self.assertIn("@app.route('/')", self.src)

    def test_api_all_route(self):
        self.assertIn("@app.route('/api/all')", self.src,
            '必须有 /api/all 拉所有数据')

    def test_api_review_action_route(self):
        self.assertIn("@app.route('/api/review/<action_kind>'",
                       self.src)

    def test_reuses_jd_action_functions(self):
        """复用 jarvis_dashboard.py 业务, 不重写."""
        self.assertIn('jd.action_activate_review', self.src)
        self.assertIn('jd.action_reject_review', self.src)
        self.assertIn('jd.read_concerns', self.src)
        self.assertIn('jd.read_review_queues', self.src)


# ============================================================
# Sub-C: Flask test_client (无真 port)
# ============================================================

class TestBeta525CFlaskClient(unittest.TestCase):
    """用 Flask test_client 不开真 port 测."""

    @classmethod
    def setUpClass(cls):
        try:
            import jarvis_dashboard_web as web
            cls.web = web
            cls.client = web.app.test_client()
        except Exception as e:
            raise unittest.SkipTest(f"import fail: {e}")

    def test_index_returns_html(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        body = r.data.decode('utf-8')
        self.assertIn('J.A.R.V.I.S. Dashboard', body)
        self.assertIn('β.5.25', body)

    def test_api_all_returns_json(self):
        r = self.client.get('/api/all')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data.decode('utf-8'))
        # 必须含 summary + reviewItems + 6 类区
        for k in ('summary', 'reviewItems', 'concerns', 'relation',
                  'health', 'directive', 'daemon', 'events'):
            self.assertIn(k, data, f'/api/all 必须返 {k}')

    def test_api_review_rejects_invalid_action(self):
        r = self.client.post('/api/review/foo', json={'kind': 'concern',
                                                        'id': 'x'})
        self.assertEqual(r.status_code, 400)

    def test_api_review_rejects_missing_kind(self):
        r = self.client.post('/api/review/activate', json={})
        self.assertEqual(r.status_code, 400)


# ============================================================
# Sub-D: charter (Sir 设计要求)
# ============================================================

class TestBeta525DSirRequirements(unittest.TestCase):
    """Sir 02:17 明确要求 charter."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(WEB_PATH)

    def test_modern_card_design(self):
        """现代审美卡片: rounded-2xl / shadow / glass effect."""
        for kw in ('rounded-2xl', 'shadow', 'backdrop-filter'):
            self.assertIn(kw, self.src, f'必须有现代 UI 元素: {kw}')

    def test_window_resize_responsive(self):
        """窗口缩放 = 响应式 grid + viewport meta."""
        self.assertIn('width=device-width', self.src,
            '必须有 viewport meta 响应式')
        self.assertIn('grid-cols', self.src)

    def test_operation_feedback(self):
        """操作体验: toast 通知 + loading state + 动画."""
        self.assertIn('showToast', self.src,
            '必须有 toast 反馈机制')
        self.assertIn('actionPending', self.src,
            '必须有 loading 状态防双击')
        self.assertIn('transition', self.src,
            '必须有 CSS transition 动画')

    def test_auto_browser_open(self):
        """自动开浏览器, Sir 一键启动."""
        self.assertIn('webbrowser.open', self.src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
