# -*- coding: utf-8 -*-
"""[Gap 2 / P5-PreFlight / 2026-05-21 00:45 + P5-fixD / 10:00 默认开] Reply PreFlight verify

Cover:
  A. ReplyPreFlight class basic (default ON, env=0 disabled, fallback safe)
  B. Cache layer
  C. Stats persist
  D. Singleton register
  E. Static check stream_chat / central_nerve / _assemble_prompt wired
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_ReplyPreFlightBasics(unittest.TestCase):

    def setUp(self):
        from jarvis_reply_preflight import reset_default_preflight_for_test
        reset_default_preflight_for_test()

    def test_default_enabled(self):
        """[P5-fixD] default ON — no env var → enabled."""
        from jarvis_reply_preflight import is_enabled
        os.environ.pop('JARVIS_PREFLIGHT', None)
        self.assertTrue(is_enabled())

    def test_env_disabled(self):
        """[P5-fixD] JARVIS_PREFLIGHT=0 → disabled."""
        from jarvis_reply_preflight import is_enabled
        os.environ['JARVIS_PREFLIGHT'] = '0'
        try:
            self.assertFalse(is_enabled())
        finally:
            os.environ.pop('JARVIS_PREFLIGHT', None)

    def test_env_explicit_enabled(self):
        from jarvis_reply_preflight import is_enabled
        os.environ['JARVIS_PREFLIGHT'] = '1'
        try:
            self.assertTrue(is_enabled())
        finally:
            os.environ.pop('JARVIS_PREFLIGHT', None)

    def test_no_key_router_fallback_pass(self):
        """No key_router → check returns pass with _fallback=True."""
        from jarvis_reply_preflight import ReplyPreFlight
        pf = ReplyPreFlight(key_router=None)
        result = pf.check(
            sir_utterance="好的好的",
            draft_reply="I must apologize for my previous claim...",
            state_summary="Sir is casual",
        )
        self.assertEqual(result['verdict'], 'pass')
        self.assertTrue(result['_fallback'])

    def test_empty_draft_passes(self):
        """Empty draft → silence → pass."""
        from jarvis_reply_preflight import ReplyPreFlight
        pf = ReplyPreFlight(key_router=None)
        result = pf.check(sir_utterance="hello", draft_reply="")
        self.assertEqual(result['verdict'], 'pass')
        self.assertEqual(result['latency_ms'], 0)

    def test_stats_initialized(self):
        from jarvis_reply_preflight import ReplyPreFlight
        pf = ReplyPreFlight(key_router=None)
        s = pf.stats()
        self.assertEqual(s['total_checks'], 0)
        self.assertEqual(s['pass_count'], 0)


class TestB_Cache(unittest.TestCase):

    def setUp(self):
        from jarvis_reply_preflight import reset_default_preflight_for_test
        reset_default_preflight_for_test()

    def test_cache_hit_no_recall(self):
        """Same (sir+draft) hash within TTL returns cached verdict."""
        from jarvis_reply_preflight import _cache_put, _cache_get, _cache_key
        key = _cache_key("hello", "draft")
        verdict = {'verdict': 'pass', 'issues': [], 'edited_reply': '',
                   'scrap_reason': '', 'latency_ms': 0, '_cached': False,
                   '_fallback': False}
        _cache_put(key, verdict)
        cached = _cache_get(key, ttl_s=60.0)
        self.assertIsNotNone(cached)
        self.assertEqual(cached['verdict'], 'pass')

    def test_cache_expired(self):
        """Beyond TTL returns None."""
        from jarvis_reply_preflight import _cache_put, _cache_get, _cache_key
        key = _cache_key("hello", "draft")
        verdict = {'verdict': 'pass'}
        _cache_put(key, verdict)
        cached = _cache_get(key, ttl_s=0.001)  # already expired
        import time as _t
        _t.sleep(0.01)
        cached = _cache_get(key, ttl_s=0.001)
        self.assertIsNone(cached)


class TestC_Singleton(unittest.TestCase):

    def setUp(self):
        from jarvis_reply_preflight import reset_default_preflight_for_test
        reset_default_preflight_for_test()

    def test_register_get(self):
        from jarvis_reply_preflight import (
            ReplyPreFlight, register_preflight, get_default_preflight
        )
        self.assertIsNone(get_default_preflight())
        pf = ReplyPreFlight(key_router=None)
        register_preflight(pf)
        self.assertIs(get_default_preflight(), pf)


class TestD_StaticIntegration(unittest.TestCase):
    """Static src checks: stream_chat + central_nerve + _assemble_prompt wired."""

    def test_stream_chat_calls_preflight(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("from jarvis_reply_preflight import is_enabled", src)
        self.assertIn("get_default_preflight", src)
        self.assertIn("ReplyPreFlightAsync", src)

    def test_central_nerve_initializes_preflight(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("from jarvis_reply_preflight import ReplyPreFlight", src)
        self.assertIn("self.reply_preflight", src)
        self.assertIn("register_preflight", src)

    def test_preflight_publishes_swm_via_chat_bypass(self):
        """[β.5.46+ / 2026-05-21 18:17] [PREFLIGHT FEEDBACK] block 删除 (Sir 真意).

        新通路: chat_bypass async_preflight 后 publish SWM 'preflight_verdict' event.
        主脑下轮通过 SWM evidence 看到 PreFlight 历史结果, 不通过专用 block.
        """
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("preflight_verdict", src,
                       "chat_bypass 应 publish SWM event 'preflight_verdict'")
        self.assertIn("ReplyPreFlight", src,
                       "chat_bypass 应调 ReplyPreFlight async")


class TestE_StatsPersist(unittest.TestCase):

    def setUp(self):
        from jarvis_reply_preflight import reset_default_preflight_for_test
        reset_default_preflight_for_test()
        self.tmpdir = tempfile.mkdtemp(prefix='preflight_stats_test_')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_record_stats_appends(self):
        from jarvis_reply_preflight import _DEFAULT_CONFIG, _record_stats
        path = os.path.join(self.tmpdir, 'preflight_stats.jsonl')
        _orig = _DEFAULT_CONFIG['stats_path']
        _DEFAULT_CONFIG['stats_path'] = path
        try:
            _record_stats(
                {'verdict': 'scrap', 'issues': ['unsolicited callback'],
                 'edited_reply': ''},
                latency_ms=420.0,
                sir_utt='好的',
                draft_len=180,
            )
            self.assertTrue(os.path.exists(path))
            with open(path, 'r', encoding='utf-8') as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            self.assertEqual(len(lines), 1)
            d = json.loads(lines[0])
            self.assertEqual(d['verdict'], 'scrap')
            self.assertEqual(d['issues'], ['unsolicited callback'])
            self.assertEqual(d['draft_len'], 180)
        finally:
            _DEFAULT_CONFIG['stats_path'] = _orig


if __name__ == '__main__':
    unittest.main()
