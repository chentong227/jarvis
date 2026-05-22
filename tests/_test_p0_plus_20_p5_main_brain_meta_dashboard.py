# -*- coding: utf-8 -*-
"""[P5-Layer1-fix19-dashboard / 2026-05-22] 主脑 thinking pass 可视化集成 dashboard

Sir 14:31 "把这些信息能放都放到可视化窗口方便我看".

测试覆盖:
  A: /api/main_brain_meta 返回 schema (ok, records, stats, health)
  B: filter 工作 — skip_alert / reaction / turn / limit
  C: stats 计算正确 — total / skip_alert_pct / evidence_pct / reactions
  D: health 判定 — empty / warn (skip > 50%) / warn (ev < 30%) / ok
  E: /main_brain_meta page 200
  F: marker 存在
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _seed(path: str, records: list) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')


# 共用 dashboard 模块 (一次导入)
_DASHBOARD = None


def _get_app():
    """import dashboard module + 返 Flask app."""
    global _DASHBOARD
    if _DASHBOARD is None:
        import importlib
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts'
        ))
        _DASHBOARD = importlib.import_module('jarvis_dashboard_web')
    return _DASHBOARD.app


class TestA_ApiSchema(unittest.TestCase):
    """A: /api/main_brain_meta 返回 schema."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _q(self, **kw):
        """build URL with audit_path."""
        from urllib.parse import urlencode
        kw['audit_path'] = self.tmp.name
        return '/api/main_brain_meta?' + urlencode(kw)

    def test_empty_audit(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q())
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['records'], [])
        self.assertEqual(data['health'], 'empty')
        self.assertIn('主脑还没跑过', data['health_msg'])

    def test_basic_schema(self):
        _seed(self.tmp.name, [{
            'turn_id': 'turn_a', 'evidence': ['stm:t1'],
            'reaction': 'voice', 'skip_alert': False,
            'note': 'test', 'ts': time.time(),
            'user_input_excerpt': 'hi',
        }])
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q())
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['total'], 1)
        self.assertEqual(len(data['records']), 1)
        rec = data['records'][0]
        self.assertEqual(rec['turn_id'], 'turn_a')
        self.assertIn('stats', data)
        self.assertIn('health', data)


class TestB_Filter(unittest.TestCase):
    """B: filter 工作 — skip_alert / reaction / turn / limit."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()
        records = [
            {'turn_id': 'turn_1', 'evidence': ['stm:t1'],
             'reaction': 'voice', 'skip_alert': False, 'note': 'a',
             'ts': time.time() - 100, 'user_input_excerpt': 'first'},
            {'turn_id': 'turn_2', 'evidence': ['none'],
             'reaction': 'silent_text', 'skip_alert': True, 'note': 'b',
             'ts': time.time() - 50, 'user_input_excerpt': 'second'},
            {'turn_id': 'turn_3', 'evidence': ['stm:t2', 'swm:x'],
             'reaction': 'voice', 'skip_alert': False, 'note': 'c',
             'ts': time.time(), 'user_input_excerpt': 'third'},
        ]
        _seed(self.tmp.name, records)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _q(self, **kw):
        from urllib.parse import urlencode
        kw['audit_path'] = self.tmp.name
        return '/api/main_brain_meta?' + urlencode(kw)

    def test_filter_skip_alert_yes(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q(skip_alert='yes'))
        data = r.get_json()
        # 仅 turn_2
        self.assertEqual(len(data['records']), 1)
        self.assertEqual(data['records'][0]['turn_id'], 'turn_2')

    def test_filter_skip_alert_no(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q(skip_alert='no'))
        data = r.get_json()
        # turn_1 + turn_3 (2 条)
        self.assertEqual(len(data['records']), 2)
        ids = {rec['turn_id'] for rec in data['records']}
        self.assertEqual(ids, {'turn_1', 'turn_3'})

    def test_filter_reaction_voice(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q(reaction='voice'))
        data = r.get_json()
        self.assertEqual(len(data['records']), 2)

    def test_filter_reaction_silent_text(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q(reaction='silent_text'))
        data = r.get_json()
        self.assertEqual(len(data['records']), 1)
        self.assertEqual(data['records'][0]['turn_id'], 'turn_2')

    def test_filter_by_turn(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q(turn='turn_2'))
        data = r.get_json()
        self.assertEqual(len(data['records']), 1)
        self.assertEqual(data['records'][0]['turn_id'], 'turn_2')

    def test_records_reversed_newest_first(self):
        """records 应是新的在最前面 (倒序)."""
        app = _get_app()
        with app.test_client() as c:
            r = c.get(self._q())
        data = r.get_json()
        self.assertEqual(data['records'][0]['turn_id'], 'turn_3')  # 最新
        self.assertEqual(data['records'][-1]['turn_id'], 'turn_1')  # 最旧


class TestC_Stats(unittest.TestCase):
    """C: stats 计算正确."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()
        # 4 条: 1 skip / 3 evidence 非空 / 2 voice 1 silent_text 1 silence
        records = [
            {'turn_id': 'a', 'evidence': ['stm:t1'], 'reaction': 'voice',
             'skip_alert': False, 'note': '', 'ts': time.time()},
            {'turn_id': 'b', 'evidence': ['none'], 'reaction': 'voice',
             'skip_alert': True, 'note': '', 'ts': time.time()},
            {'turn_id': 'c', 'evidence': ['stm:t3', 'swm:y'], 'reaction': 'silent_text',
             'skip_alert': False, 'note': '', 'ts': time.time()},
            {'turn_id': 'd', 'evidence': ['profile:loc'], 'reaction': 'silence',
             'skip_alert': False, 'note': '', 'ts': time.time()},
        ]
        _seed(self.tmp.name, records)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_stats_counts(self):
        from urllib.parse import urlencode
        app = _get_app()
        with app.test_client() as c:
            r = c.get('/api/main_brain_meta?' + urlencode({'audit_path': self.tmp.name}))
        s = r.get_json()['stats']
        self.assertEqual(s['total'], 4)
        self.assertEqual(s['skip_alert_count'], 1)
        self.assertEqual(s['skip_alert_pct'], 25.0)
        self.assertEqual(s['evidence_count'], 3)
        self.assertEqual(s['evidence_pct'], 75.0)
        # avg evidence = (1+1+2+1)/4 = 1.25
        self.assertEqual(s['avg_evidence_per_turn'], 1.25)
        # reaction
        self.assertEqual(s['reactions'].get('voice'), 2)
        self.assertEqual(s['reactions'].get('silent_text'), 1)
        self.assertEqual(s['reactions'].get('silence'), 1)


class TestD_Health(unittest.TestCase):
    """D: health 判定 — empty / warn (skip > 50%) / warn (ev < 30%) / ok."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _get_health(self) -> tuple:
        from urllib.parse import urlencode
        app = _get_app()
        with app.test_client() as c:
            r = c.get('/api/main_brain_meta?' + urlencode({'audit_path': self.tmp.name}))
        data = r.get_json()
        return data['health'], data['health_msg']

    def test_empty(self):
        h, msg = self._get_health()
        self.assertEqual(h, 'empty')

    def test_warn_skip_above_50(self):
        # 4/6 = 66.6% skip_alert → warn
        records = []
        for i in range(6):
            records.append({
                'turn_id': f't{i}',
                'evidence': ['stm:x'],
                'reaction': 'voice',
                'skip_alert': i < 4,  # 前 4 个 skip=True
                'note': '', 'ts': time.time(),
            })
        _seed(self.tmp.name, records)
        h, msg = self._get_health()
        self.assertEqual(h, 'warn')
        self.assertIn('skip_alert', msg)

    def test_warn_evidence_below_30(self):
        # 6 轮, 1 个 evidence 非空 = 16.6% → warn
        records = []
        for i in range(6):
            ev = ['stm:x'] if i == 0 else ['none']
            records.append({
                'turn_id': f't{i}', 'evidence': ev,
                'reaction': 'voice', 'skip_alert': False,
                'note': '', 'ts': time.time(),
            })
        _seed(self.tmp.name, records)
        h, msg = self._get_health()
        self.assertEqual(h, 'warn')
        self.assertIn('evidence', msg)

    def test_ok_high_evidence(self):
        # 10 轮 evidence 全非空 = 100% → ok
        records = []
        for i in range(10):
            records.append({
                'turn_id': f't{i}', 'evidence': ['stm:x'],
                'reaction': 'voice', 'skip_alert': False,
                'note': '', 'ts': time.time(),
            })
        _seed(self.tmp.name, records)
        h, msg = self._get_health()
        self.assertEqual(h, 'ok')
        self.assertIn('良好', msg)


class TestE_Pages(unittest.TestCase):
    """E: /main_brain_meta page 200."""

    def test_page_renders(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get('/main_brain_meta')
        self.assertEqual(r.status_code, 200)
        body = r.data.decode('utf-8')
        # 关键 UI 元素
        self.assertIn('主脑 Thinking Pass META', body)
        self.assertIn('/api/main_brain_meta', body)
        self.assertIn('skip-sel', body)
        self.assertIn('reaction-sel', body)
        self.assertIn('limit-sel', body)
        # 健康度 banner
        self.assertIn('health-banner', body)

    def test_home_has_meta_link(self):
        """主页 header 应有 '🧠 思考链' 入口跳 /main_brain_meta."""
        app = _get_app()
        with app.test_client() as c:
            r = c.get('/')
        self.assertEqual(r.status_code, 200)
        body = r.data.decode('utf-8')
        self.assertIn('/main_brain_meta', body)
        self.assertIn('思考链', body)

    def test_home_has_mini_card(self):
        """主页应有 brainMeta mini card (Layer 1 META 健康度概览)."""
        app = _get_app()
        with app.test_client() as c:
            r = c.get('/')
        body = r.data.decode('utf-8')
        # mini card title
        self.assertIn('主脑思考链 (Layer 1 META)', body)
        # Alpine state binding
        self.assertIn('brainMeta', body)
        self.assertIn('brainMeta.evidence_pct', body)
        self.assertIn('brainMeta.skip_alert_pct', body)
        # 链到详情 page
        self.assertIn('详情 →', body)


class TestG_ApiAllHasBrainMeta(unittest.TestCase):
    """G: /api/all 应含 brainMeta 字段."""

    def test_brain_meta_in_api_all(self):
        app = _get_app()
        with app.test_client() as c:
            r = c.get('/api/all')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn('brainMeta', data,
                       '/api/all 应返回 brainMeta 字段供主页 mini card 渲染')

    def test_brain_meta_summary_helper(self):
        """直接测 _read_brain_meta_summary helper."""
        global _DASHBOARD
        app = _get_app()  # ensure module imported
        # 用空 audit (default 路径) — 应返 health=empty 或 stat
        result = _DASHBOARD._read_brain_meta_summary()
        # 不论是否有数据, 应是 dict
        self.assertIsInstance(result, dict)
        # health 字段必有 (empty / ok / warn)
        if result:  # 非空 dict
            self.assertIn('health', result)
            self.assertIn('total', result)


class TestF_Marker(unittest.TestCase):
    def test_marker_in_dashboard(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'jarvis_dashboard_web.py'
        )
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-Layer1-fix19-dashboard', src)
        self.assertIn('_MAIN_BRAIN_META_HTML', src)
        self.assertIn('def api_main_brain_meta', src)
        self.assertIn('def page_main_brain_meta', src)


if __name__ == '__main__':
    unittest.main()
