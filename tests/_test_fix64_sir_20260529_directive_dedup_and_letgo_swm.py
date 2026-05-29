# -*- coding: utf-8 -*-
"""[Sir 2026-05-29] Fix2 + Fix3: directive jaccard dedup + let_go swm_events.

Fix2: compose_main_brain_directive jaccard dedup against active directive.
Fix3: let_go 扩展覆盖 swm_events (LLM <LET_GO>swm:etype</LET_GO>).

测试覆盖 (8 testcase):
  Fix2:
    - D1: _check_directive_jaccard_dedup 无 active directive → 放行
    - D2: _check_directive_jaccard_dedup 相似 text → hit
    - D3: _check_directive_jaccard_dedup 不同 text → 放行
    - D4: _do_compose_main_brain_directive jaccard dedup reject
  Fix3:
    - L1: _collect_evidence prune swm_events per swm: let_go
    - L2: _parse_thought <LET_GO>swm:etype 验证 + persist
    - L3: _parse_thought <LET_GO>swm: 编造 etype → skip
    - L4: _build_prompt 含 swm: LET_GO 教学
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    with patch.object(
        InnerThoughtDaemon, '_append_cold_start_record',
        return_value=None,
    ):
        d = InnerThoughtDaemon(key_router=MagicMock())
    d._thoughts = []
    d._lock = __import__('threading').Lock()
    d._PROPOSE_QUALITY_VOCAB_CACHE = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    return d


def _make_thought(**kw):
    from jarvis_inner_thought_daemon import InnerThought
    _ts = kw.get('ts', time.time())
    t = InnerThought(
        id=kw.get('id', 'tht_test_001'),
        ts=_ts,
        ts_iso=kw.get('ts_iso', time.strftime('%Y-%m-%dT%H:%M:%S',
                                                time.localtime(_ts))),
        category=kw.get('category', 'B'),
        thought=kw.get('thought_text', 'test thought'),
        salience=kw.get('salience', 0.8),
        actionable=kw.get('actionable', 'none'),
        evidence_link=kw.get('evidence_link', 'none'),
    )
    return t


# ============================================================
# Fix2: directive jaccard dedup
# ============================================================

class TestDirectiveJaccardDedup(unittest.TestCase):
    """D1-D4: _check_directive_jaccard_dedup + compose gate."""

    def test_D1_no_active_directive_passes(self):
        """D1: 无 active directive → 放行."""
        daemon = _make_daemon()
        with patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ), patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
        ) as mock_track:
            mock_track.return_value.get_active_directive.return_value = None
            hit, hit_text, jacc = daemon._check_directive_jaccard_dedup(
                'be brief',
            )
        self.assertFalse(hit, "D1 无 active directive 应放行")

    def test_D2_similar_text_hits(self):
        """D2: 相似 text → hit."""
        daemon = _make_daemon()
        with patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ), patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
        ) as mock_track:
            mock_track.return_value.get_active_directive.return_value = {
                'text': 'be brief and skip health advice',
            }
            hit, hit_text, jacc = daemon._check_directive_jaccard_dedup(
                'be brief skip health',
            )
        self.assertTrue(hit, "D2 相似 directive 应 hit")
        self.assertGreater(jacc, 0.4, "D2 jaccard 应 > 0.4")

    def test_D3_different_text_passes(self):
        """D3: 完全不同 text → 放行."""
        daemon = _make_daemon()
        with patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ), patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
        ) as mock_track:
            mock_track.return_value.get_active_directive.return_value = {
                'text': 'be brief and skip health advice',
            }
            hit, hit_text, jacc = daemon._check_directive_jaccard_dedup(
                'use formal tone today',
            )
        self.assertFalse(hit, "D3 不同 directive 应放行")

    def test_D4_compose_rejects_jaccard_dup(self):
        """D4: _do_compose_main_brain_directive jaccard dedup reject."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        with patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ), patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
        ) as mock_track:
            mock_track.return_value.get_active_directive.return_value = {
                'text': 'be brief and skip health advice',
            }
            ok, result = daemon._do_compose_main_brain_directive(
                thought,
                'compose_main_brain_directive:be brief skip health',
            )
        self.assertFalse(ok, "D4 jaccard dedup 应 reject")
        self.assertIn('jaccard_dedup', result)


# ============================================================
# Fix3: let_go swm_events
# ============================================================

def _isolated_let_go_path():
    fd, path = tempfile.mkstemp(suffix='_let_go.json')
    os.close(fd)
    if os.path.exists(path):
        os.unlink(path)
    return path


class TestLetGoSwmEvents(unittest.TestCase):
    """L1-L4: let_go swm_events prune + parse + prompt."""

    def setUp(self):
        self.tmp_path = _isolated_let_go_path()
        import jarvis_inner_thought_daemon as m
        self._patcher = patch.object(m, '_LET_GO_TOPICS_PATH', self.tmp_path)
        self._patcher.start()
        # clear pacing cache
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self.tmp_path):
                os.unlink(self.tmp_path)
        except Exception:
            pass

    def test_L1_prune_swm_events_by_let_go(self):
        """L1: swm: let_go topic → prune matching etype from swm_events."""
        daemon = _make_daemon()
        from jarvis_inner_thought_daemon import _add_let_go_topic
        _add_let_go_topic('swm:auto_arbiter_anomaly', ttl_min=30)
        # mock SWM bus with anomaly event
        mock_bus = MagicMock()
        mock_bus.top_n.return_value = [
            {
                'type': 'auto_arbiter_anomaly',
                'description': 'bloat detected',
                '_age_s': 30,
                'source': 'AutoArbiterMonitor',
            },
            {
                'type': 'sir_awake',
                'description': 'Sir is back',
                '_age_s': 20,
                'source': 'PhysicalEnvProbe',
            },
        ]
        with patch(
            'jarvis_utils.get_event_bus',
            return_value=mock_bus,
        ):
            ev = daemon._collect_evidence(sir_state='active', within_seconds=90)
        swm_types = [e['type'] for e in ev.get('swm_events', [])]
        self.assertNotIn('auto_arbiter_anomaly', swm_types,
                          "L1 anomaly etype 应被 swm: let_go prune")
        self.assertIn('sir_awake', swm_types,
                       "L1 非 let_go etype 应保留")

    def test_L2_parse_swm_let_go_tag(self):
        """L2: <LET_GO>swm:auto_arbiter_anomaly</LET_GO> 验证 + persist."""
        daemon = _make_daemon()
        mock_bus = MagicMock()
        mock_bus.top_n.return_value = [
            {
                'type': 'auto_arbiter_anomaly',
                'description': 'bloat',
                '_age_s': 30,
                'source': 'AutoArbiterMonitor',
            },
        ]
        with patch(
            'jarvis_utils.get_event_bus',
            return_value=mock_bus,
        ):
            thought = daemon._parse_thought(
                raw=(
                    '<CATEGORY>D</CATEGORY>\n'
                    '<THOUGHT>I keep seeing the same anomaly, '
                    'should let it go for now</THOUGHT>\n'
                    '<SALIENCE>0.6</SALIENCE>\n'
                    '<ACTIONABLE>none</ACTIONABLE>\n'
                    '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
                    '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
                    '<CONTINUITY>new_topic</CONTINUITY>\n'
                    '<LET_GO>swm:auto_arbiter_anomaly</LET_GO>\n'
                ),
                sir_state='active',
                tick_interval=45,
            )
        self.assertIsNotNone(thought, "L2 parse 应成功")
        # verify let_go persisted
        from jarvis_inner_thought_daemon import _load_let_go_topics
        active = _load_let_go_topics()
        swm_entries = [
            e for e in active
            if e.get('thread_id', '').startswith('swm:')
        ]
        self.assertGreaterEqual(len(swm_entries), 1,
                                 "L2 swm: let_go 应持久化")

    def test_L3_parse_swm_fake_etype_skipped(self):
        """L3: <LET_GO>swm:fake_event</LET_GO> 编造 etype → skip."""
        daemon = _make_daemon()
        mock_bus = MagicMock()
        mock_bus.top_n.return_value = [
            {'type': 'real_event', 'description': 'x', '_age_s': 10,
             'source': 'test'},
        ]
        with patch(
            'jarvis_utils.get_event_bus',
            return_value=mock_bus,
        ):
            thought = daemon._parse_thought(
                raw=(
                    '<CATEGORY>D</CATEGORY>\n'
                    '<THOUGHT>test</THOUGHT>\n'
                    '<SALIENCE>0.5</SALIENCE>\n'
                    '<ACTIONABLE>none</ACTIONABLE>\n'
                    '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
                    '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
                    '<CONTINUITY>new_topic</CONTINUITY>\n'
                    '<LET_GO>swm:fake_event</LET_GO>\n'
                ),
                sir_state='active',
                tick_interval=45,
            )
        self.assertIsNotNone(thought, "L3 parse 应成功 (LET_GO skip 不阻塞)")
        from jarvis_inner_thought_daemon import _load_let_go_topics
        active = _load_let_go_topics()
        swm_entries = [
            e for e in active
            if e.get('thread_id', '').startswith('swm:')
        ]
        self.assertEqual(len(swm_entries), 0,
                          "L3 编造 swm etype 不应持久化")

    def test_L4_prompt_mentions_swm_let_go(self):
        """L4: _build_prompt 含 swm: LET_GO 教学."""
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active',
            'idle_seconds': 10,
            'hour': 10,
            'swm_events': [],
            'stm': [],
            'concerns': [],
            'recent_thoughts': [],
        }
        system, user = daemon._build_prompt(
            sir_state='active',
            evidence=evidence,
            free_categories=['A', 'B', 'C', 'D', 'E'],
        )
        self.assertIn('swm:', system,
                       "L4 prompt 应含 swm: LET_GO 教学")


if __name__ == '__main__':
    unittest.main()
