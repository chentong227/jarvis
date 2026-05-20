# -*- coding: utf-8 -*-
"""β.5.41-C — Dashboard Web (Flask) /items page + API endpoints tests."""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


class TestBeta541CFlaskApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from jarvis_dashboard_web import app
        except Exception as e:
            raise unittest.SkipTest(f'Flask app unavailable: {e}')
        cls.app = app
        cls.client = app.test_client()

    def test_items_page_route_exists(self):
        rv = self.client.get('/items')
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        # 关键 UI 元素
        self.assertIn('我们的事', body)
        self.assertIn('itemsApp', body)
        self.assertIn('✏️ 修正', body)
        self.assertIn('🗑 删', body)

    def test_api_items_returns_json(self):
        rv = self.client.get('/api/items')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertTrue(data['ok'])
        self.assertIn('items', data)
        self.assertIn('counts', data)
        self.assertIsInstance(data['items'], list)

    def test_api_items_filter_by_category(self):
        rv = self.client.get('/api/items?category=inside_joke')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        for it in data['items']:
            self.assertEqual(it['category'], 'inside_joke')

    def test_api_items_filter_by_state(self):
        rv = self.client.get('/api/items?state=active')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        for it in data['items']:
            self.assertEqual(it['state'], 'active')

    def test_api_mutate_unknown_id_returns_error(self):
        rv = self.client.post(
            '/api/items/nonexistent_xyz/modify',
            data=json.dumps({'new_fields': {}}),
            content_type='application/json',
        )
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertFalse(data['ok'])
        self.assertIn('error', data)

    def test_api_mutate_invalid_action_400(self):
        rv = self.client.post(
            '/api/items/x/invalid_action',
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(rv.status_code, 400)

    def test_api_ack_endpoint(self):
        rv = self.client.post('/api/items/test_ack_xxx/ack')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        # ack 总返 True (即使 item 不存在, ack 只追踪 id)
        self.assertTrue(data['ok'])


class TestBeta541COldDashboardLinksToItems(unittest.TestCase):
    """老 dashboard 主页加了链接到新 /items 页."""

    @classmethod
    def setUpClass(cls):
        try:
            from jarvis_dashboard_web import app
        except Exception as e:
            raise unittest.SkipTest(f'Flask app unavailable: {e}')
        cls.client = app.test_client()

    def test_root_page_has_items_link(self):
        rv = self.client.get('/')
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        self.assertIn('href="/items"', body, '老 dashboard 必须含 /items 链接')
        self.assertIn('我们的事', body)


if __name__ == '__main__':
    unittest.main()
