# -*- coding: utf-8 -*-
"""β.5.43-D — Sir 评 reply 反馈通道 tests."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta543DReplyFeedbackModule(unittest.TestCase):
    def test_imports(self):
        import jarvis_reply_feedback as rfb
        for sym in ('log_reply_feedback', 'get_recent_reply_feedback',
                    'format_for_prompt', 'VALID_VERDICTS'):
            self.assertTrue(hasattr(rfb, sym))

    def test_log_invalid_verdict_rejected(self):
        from jarvis_reply_feedback import log_reply_feedback
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'f.jsonl')
            ok = log_reply_feedback('test reply', 'unknown_verdict', path=p)
            self.assertFalse(ok)

    def test_log_and_read(self):
        from jarvis_reply_feedback import (
            log_reply_feedback, get_recent_reply_feedback,
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'f.jsonl')
            self.assertTrue(log_reply_feedback('hello sir', 'good', '', path=p))
            self.assertTrue(log_reply_feedback('verbose reply', 'bad', '太啰嗦', path=p))
            self.assertTrue(log_reply_feedback('off topic', 'silent_wanted', '', path=p))
            entries = get_recent_reply_feedback(hours=24, path=p)
            self.assertEqual(len(entries), 3)
            self.assertEqual(entries[-1]['verdict'], 'silent_wanted')
            self.assertEqual(entries[1]['sir_note'], '太啰嗦')

    def test_format_for_prompt(self):
        from jarvis_reply_feedback import format_for_prompt
        entries = [
            {'verdict': 'good', 'reply_excerpt': 'Hi Sir', 'sir_note': ''},
            {'verdict': 'bad', 'reply_excerpt': 'Long reply', 'sir_note': '太啰嗦'},
        ]
        out = format_for_prompt(entries)
        self.assertIn('SIR LAST REPLY FEEDBACK', out)
        self.assertIn('good', out)
        self.assertIn('bad', out)
        self.assertIn('太啰嗦', out)


class TestBeta543DDashboardAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        try:
            from jarvis_dashboard_web import app
        except Exception as e:
            raise unittest.SkipTest(f'Flask unavailable: {e}')
        cls.client = app.test_client()

    def test_api_recent_replies_returns_list(self):
        rv = self.client.get('/api/recent_replies')
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertTrue(data['ok'])
        self.assertIn('replies', data)
        self.assertIsInstance(data['replies'], list)

    def test_api_reply_feedback_invalid_verdict_400(self):
        rv = self.client.post(
            '/api/reply_feedback',
            data=json.dumps({'reply_excerpt': 'x', 'verdict': 'invalid_v'}),
            content_type='application/json',
        )
        # 400 因为 invalid verdict, 但 endpoint 返 ok=False 200 (jarvis_reply_feedback 处理)
        # 实际从 endpoint 代码看, 返 400 (jsonify(error=...))
        self.assertEqual(rv.status_code, 400)


class TestBeta543DCentralNervePromptInject(unittest.TestCase):
    def test_assemble_prompt_imports_feedback(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.43-D', src)
        self.assertIn('jarvis_reply_feedback', src)
        self.assertIn('get_recent_reply_feedback', src)
        self.assertIn('SIR LAST REPLY FEEDBACK', src + open(
            os.path.join(ROOT, 'jarvis_reply_feedback.py'), encoding='utf-8'
        ).read())


if __name__ == '__main__':
    unittest.main()
