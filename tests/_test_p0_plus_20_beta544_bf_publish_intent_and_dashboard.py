"""[β.5.44-B+F / 2026-05-20 19:09] publish_intent + dashboard page

B: 4 module 加 publish_intent_candidate (旁路不动旧 mutate, 向后兼容):
   - jarvis_worker.py MemoryCorrection gate → sir_intent_correction_candidate
   - jarvis_concern_feedback.py record → sir_intent_progress_candidate
   - jarvis_worker.py Gatekeeper Commitment → sir_intent_commit_candidate
   - jarvis_self_promise.py detect_and_register → sir_intent_promise_candidate
   - jarvis_commitment_watcher.py add_commitment → sir_intent_deadline_candidate

F: Dashboard 加 /intent_resolved page + /api/intent_resolved endpoint, Sir 看每轮
   IntentResolver 真做了什么 mutation.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestSubB_PublishIntentInModules(unittest.TestCase):
    """B: 5 module 加 publish sir_intent_*_candidate (旁路)."""

    def test_memory_correction_publishes_candidate(self):
        src = open(
            os.path.join(ROOT, 'jarvis_worker.py'), encoding='utf-8'
        ).read()
        # marker
        self.assertIn('β.5.44-B', src,
                      'jarvis_worker.py 必有 β.5.44-B marker')
        # publish sir_intent_correction_candidate
        self.assertIn('sir_intent_correction_candidate', src,
                      'Memory Correction 必 publish sir_intent_correction_candidate')

    def test_concern_feedback_publishes_progress(self):
        src = open(
            os.path.join(ROOT, 'jarvis_concern_feedback.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.44-B', src)
        self.assertIn('sir_intent_progress_candidate', src,
                      'ConcernFeedback 必 publish sir_intent_progress_candidate')

    def test_gatekeeper_publishes_commit(self):
        src = open(
            os.path.join(ROOT, 'jarvis_worker.py'), encoding='utf-8'
        ).read()
        self.assertIn('sir_intent_commit_candidate', src,
                      'Gatekeeper 必 publish sir_intent_commit_candidate')

    def test_self_promise_publishes_promise(self):
        src = open(
            os.path.join(ROOT, 'jarvis_self_promise.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.44-B', src)
        self.assertIn('sir_intent_promise_candidate', src,
                      'SelfPromise 必 publish sir_intent_promise_candidate')

    def test_commitment_watcher_publishes_deadline(self):
        src = open(
            os.path.join(ROOT, 'jarvis_commitment_watcher.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.44-B', src)
        self.assertIn('sir_intent_deadline_candidate', src,
                      'CommitmentWatcher 必 publish sir_intent_deadline_candidate')

    def test_publish_uses_get_event_bus(self):
        """所有 publish 都要走 get_event_bus, 不要 hardcode bus instance."""
        for fn in [
            'jarvis_worker.py',
            'jarvis_concern_feedback.py',
            'jarvis_self_promise.py',
            'jarvis_commitment_watcher.py',
        ]:
            src = open(os.path.join(ROOT, fn), encoding='utf-8').read()
            # 找 β.5.44-B 段落, 确保用 get_event_bus
            idx = src.find('β.5.44-B')
            if idx > 0:
                snippet = src[idx:idx + 1500]
                self.assertIn('get_event_bus', snippet,
                              f'{fn} β.5.44-B 段必用 get_event_bus')

    def test_runtime_publish_concern_feedback(self):
        """实跑 ConcernFeedback record_user_feedback → SWM 必有 sir_intent_progress_candidate."""
        from jarvis_concerns import Concern, ConcernsLedger
        from jarvis_concern_feedback import ConcernFeedbackJudge
        from jarvis_utils import ConversationEventBus

        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)

        # ledger setup
        ledger = ConcernsLedger.__new__(ConcernsLedger)
        ledger.concerns = {}
        ledger.persist_path = '/tmp/test_b544_concerns.json'
        ledger.review_path = '/tmp/test_b544_review.json'
        c = Concern(
            id='test_hyd', what_i_watch='Sir hydration',
            why_i_care='health', severity=0.6, state='active',
        )
        ledger.concerns['test_hyd'] = c
        import threading as _th
        ledger._lock = _th.Lock()
        ledger._dirty = False

        # judge instance
        judge = ConcernFeedbackJudge.__new__(ConcernFeedbackJudge)
        judge.ledger = ledger
        judge.key_router = None
        judge._lock = _th.Lock()
        judge._judge_thread_count = 0
        # mock _call_llm_judge 让它返 cooked judgement
        def _mock_llm(*a, **kw):
            return {'concerns': [{
                'cid': 'test_hyd',
                'has_relevance': True,
                'progress': {'current': 8, 'target': 8, 'unit': '杯'},
                'severity_delta': -0.3,
                'optimal_timing': 'now',
            }]}
        judge._call_llm_judge = _mock_llm

        # 调 _judge_worker (sync 路径, 不 spawn thread)
        judge._judge_worker('应该是 8 杯', 'turn_test_b544')

        evs = bus.recent_events(types={'sir_intent_progress_candidate'})
        self.assertGreaterEqual(len(evs), 1,
                                'ConcernFeedback 必 publish sir_intent_progress_candidate')
        ev = evs[-1]
        self.assertEqual(ev['source'], 'ConcernFeedback')
        meta = ev.get('metadata') or {}
        self.assertEqual(meta.get('judgement', {}).get('concern_id'), 'test_hyd')


class TestSubF_DashboardIntentResolvedPage(unittest.TestCase):
    """F: Dashboard /intent_resolved page + API endpoint."""

    def test_api_endpoint_registered(self):
        src = open(
            os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
            encoding='utf-8'
        ).read()
        self.assertIn("@app.route('/api/intent_resolved')", src,
                      'dashboard 必 register /api/intent_resolved endpoint')
        self.assertIn("def api_intent_resolved", src)

    def test_page_endpoint_registered(self):
        src = open(
            os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
            encoding='utf-8'
        ).read()
        self.assertIn("@app.route('/intent_resolved')", src,
                      'dashboard 必 register /intent_resolved page')
        self.assertIn("def page_intent_resolved", src)
        self.assertIn("β.5.44-F", src)

    def test_html_template_has_critical_ui_elements(self):
        src = open(
            os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
            encoding='utf-8'
        ).read()
        self.assertIn('_INTENT_RESOLVED_HTML', src)
        # UI 关键元素
        for kw in ['Intent Resolved Log', '/api/intent_resolved', 'tool 成功', 'tool 失败',
                   'hours-sel', 'event-tool-calls']:
            self.assertIn(kw, src, f'HTML template 必含 "{kw}"')

    def test_api_returns_structured_data_when_bus_empty(self):
        """调 API 应返 ok=True even bus empty."""
        # flask test client
        try:
            from scripts.jarvis_dashboard_web import app
        except Exception:
            self.skipTest('dashboard web import fail (likely flask not installed)')
            return
        client = app.test_client()
        resp = client.get('/api/intent_resolved?hours=1&limit=10')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNotNone(data)
        self.assertIn('ok', data)
        # 即使 bus 空, 也返 events=[] (不 throw)
        self.assertTrue(data['ok'])
        self.assertIn('events', data)


class TestSubB_BackwardCompat(unittest.TestCase):
    """B 必保持向后兼容: 旧 mutation 路径不变, 仅旁路 publish."""

    def test_b544_block_uses_try_except(self):
        """publish 路径必 try/except 包裹, 失败不阻塞主路径."""
        for fn in [
            'jarvis_worker.py',
            'jarvis_concern_feedback.py',
            'jarvis_self_promise.py',
            'jarvis_commitment_watcher.py',
        ]:
            src = open(os.path.join(ROOT, fn), encoding='utf-8').read()
            idx = src.find('β.5.44-B')
            if idx > 0:
                snippet = src[idx:idx + 2000]
                self.assertIn('try:', snippet,
                              f'{fn} β.5.44-B 段必 try/except 包裹')
                self.assertIn('except Exception', snippet,
                              f'{fn} β.5.44-B 段必 except Exception')

    def test_b544_block_does_not_remove_old_mutation_paths(self):
        """旧 ConcernsLedger.record_user_feedback 还在 (call site 未删)."""
        src = open(
            os.path.join(ROOT, 'jarvis_concern_feedback.py'), encoding='utf-8'
        ).read()
        self.assertIn('self.ledger.record_user_feedback', src,
                      'concern_feedback 旧 mutation 路径不能删')
        # commitment_watcher.add_commitment 旧路径不能删
        src2 = open(
            os.path.join(ROOT, 'jarvis_commitment_watcher.py'), encoding='utf-8'
        ).read()
        self.assertIn('self.commitments.append', src2,
                      'commitment_watcher 旧 mutation (append) 不能删')


if __name__ == '__main__':
    unittest.main(verbosity=2)
