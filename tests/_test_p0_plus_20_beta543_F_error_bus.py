"""[β.5.43-F / 2026-05-20 19:10] Error Self-Healing Bus

Sir 17:10 真理 (6 缺口 F): '系统出错时主动告诉 Sir, 不装作没事'.

测试覆盖:
- ErrorBus 核心 API (report / recent_errors / dedupe / 持久化)
- SWM publish 'system_error_visible'
- central_nerve _assemble_prompt 注入 [SYSTEM ERRORS] block
- IntentResolver 接入 (tool fail + LLM fail → report_error)
- Dashboard /api/system_errors endpoint
"""
from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestErrorBusCore(unittest.TestCase):
    """ErrorBus 核心 API."""

    def setUp(self):
        from jarvis_error_bus import ErrorBus
        self.tmpd = tempfile.mkdtemp()
        self.bus = ErrorBus(config={
            'persist_path': os.path.join(self.tmpd, 'errors.jsonl'),
            'in_memory_max': 50,
            'persist_max': 100,
            'dedupe_window_s': 60,
        })

    def test_report_basic(self):
        ok = self.bus.report(
            module='test_mod', kind='test_kind',
            detail='something failed', severity='moderate',
        )
        self.assertTrue(ok)
        errs = self.bus.recent_errors(within_seconds=300)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]['module'], 'test_mod')
        self.assertEqual(errs[0]['kind'], 'test_kind')

    def test_dedupe_within_window(self):
        self.bus.report('mod1', 'kind1', 'first')
        ok2 = self.bus.report('mod1', 'kind1', 'second')
        self.assertFalse(ok2, 'dedupe 应跳过 1min 内同 (module, kind)')
        errs = self.bus.recent_errors()
        self.assertEqual(len(errs), 1)

    def test_dedupe_different_kind_passes(self):
        self.bus.report('mod1', 'kind1', 'first')
        ok2 = self.bus.report('mod1', 'kind2', 'second')
        self.assertTrue(ok2)
        errs = self.bus.recent_errors()
        self.assertEqual(len(errs), 2)

    def test_severity_filter(self):
        self.bus.report('m', 'k1', severity='minor')
        self.bus.report('m', 'k2', severity='moderate')
        self.bus.report('m', 'k3', severity='severe')
        # moderate+
        errs = self.bus.recent_errors(min_severity='moderate')
        self.assertEqual(len(errs), 2)
        # severe only
        errs = self.bus.recent_errors(min_severity='severe')
        self.assertEqual(len(errs), 1)

    def test_persist_jsonl(self):
        self.bus.report('m', 'k', 'detail')
        # 文件应该有一行
        path = self.bus.config['persist_path']
        self.assertTrue(os.path.exists(path))
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry['module'], 'm')
        self.assertEqual(entry['kind'], 'k')

    def test_invalid_args_return_false(self):
        ok = self.bus.report('', 'k')
        self.assertFalse(ok)
        ok = self.bus.report('m', '')
        self.assertFalse(ok)


class TestErrorBusSWMPublish(unittest.TestCase):

    def test_publishes_system_error_visible_swm(self):
        from jarvis_error_bus import ErrorBus
        from jarvis_utils import ConversationEventBus

        ev_bus = ConversationEventBus()
        ConversationEventBus.register_global(ev_bus)

        tmpd = tempfile.mkdtemp()
        eb = ErrorBus(config={
            'persist_path': os.path.join(tmpd, 'errors.jsonl'),
            'dedupe_window_s': 60,
        })
        eb.report('test', 'kind1', detail='x', severity='moderate')

        evs = ev_bus.recent_events(types={'system_error_visible'})
        self.assertGreaterEqual(len(evs), 1,
                                'moderate error 应 publish SWM')
        ev = evs[-1]
        self.assertEqual(ev['source'], 'ErrorBus')
        meta = ev.get('metadata', {})
        self.assertEqual(meta.get('module'), 'test')


class TestErrorBusSingleton(unittest.TestCase):

    def test_get_error_bus_singleton(self):
        from jarvis_error_bus import get_error_bus
        b1 = get_error_bus()
        b2 = get_error_bus()
        self.assertIs(b1, b2)

    def test_report_error_helper(self):
        from jarvis_error_bus import report_error, get_error_bus
        get_error_bus().clear_dedupe()
        ok = report_error('helper_test', 'helper_kind', 'detail', 'moderate')
        self.assertTrue(ok)


class TestSWMEtypeRegistered(unittest.TestCase):

    def test_system_error_visible_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        self.assertIn('system_error_visible', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('system_error_visible', ConversationEventBus.DEFAULT_SALIENCE)


class TestCentralNerveInjection(unittest.TestCase):
    """central_nerve _assemble_prompt 注入 [SYSTEM ERRORS] block."""

    def test_marker_present(self):
        src = open(
            os.path.join(ROOT, 'jarvis_central_nerve.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.43-F', src)
        self.assertIn('SYSTEM ERRORS', src)
        self.assertIn('from jarvis_error_bus import get_error_bus', src)

    def test_intent_resolver_reports_tool_fail(self):
        src = open(
            os.path.join(ROOT, 'jarvis_intent_resolver.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.43-F', src)
        self.assertIn('tool_fail.', src)
        self.assertIn('llm_judge_fail', src)


class TestDashboardEndpoint(unittest.TestCase):

    def test_api_endpoint_registered(self):
        src = open(
            os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
            encoding='utf-8'
        ).read()
        self.assertIn("@app.route('/api/system_errors')", src)
        self.assertIn("def api_system_errors", src)
        self.assertIn('β.5.43-F', src)

    def test_api_returns_structured_data(self):
        try:
            from scripts.jarvis_dashboard_web import app
        except Exception:
            self.skipTest('flask not available')
            return
        client = app.test_client()
        resp = client.get('/api/system_errors?hours=1&min_severity=moderate')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertIn('errors', data)
        self.assertIn('stats', data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
