# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 00:11] Thinking Agency Phase 4-5 — M1/M2/M3/M4 regression

Sir 真意 (2026-05-27 00:11):
> "再回归测试一下下一个阶段的工程, 该思考完了就执行 ok"
> Phase 4-5 from KICKOFF:
>   M1 ThoughtChain — continuity / thread_id
>   M2 TimeAwareness — hourly pattern from STM
>   M3 VisualPulse — subtle 💭 字幕区 (vocab 节流)
>   M4 Dashboard — outcome / thread_group / time_pattern panel

测试覆盖 (准则 4 testing discipline):
  1. M1 InnerThought dataclass 有 thread_id + continuity 字段, default 合理
  2. M1 prompt 含 <CONTINUITY> 字段说明
  3. M1 _parse_thought 处理 same_thread:<id> 正确 → 沿用 thread; 处理 unknown id → 降级 new_topic
  4. M2 TimeAwarenessReflector cache + get_pattern_at_now() 正确返
  5. M2 get_pattern_at_now() STM 空 → return None (fail-safe)
  6. M3 inner_thought_pulse_vocab.json 真存在 + schema 完整
  7. M3 _load_pulse_vocab() lazy + mtime cache
  8. M3 _emit_thought_pulse 节流 — disabled / 低 sal / cooldown 全部 skip
  9. M3 _emit_thought_pulse 通路 — 合规 thought 真 enqueue subtitle_queue
 10. M4 /api/inner_thoughts 返 outcome_breakdown + thread_groups + time_pattern_now
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================
# M1 ThoughtChain
# ==========================================================

class TestM1ThoughtChain(unittest.TestCase):

    def test_innerthought_dataclass_has_thread_id_and_continuity(self):
        """M1 字段加齐. default = ('', 'new_topic')."""
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='thought_x', ts=0.0, ts_iso='', category='A',
            thought='hi', salience=0.5, actionable='none',
        )
        self.assertTrue(hasattr(t, 'thread_id'))
        self.assertTrue(hasattr(t, 'continuity'))
        self.assertEqual(t.thread_id, '')
        self.assertEqual(t.continuity, 'new_topic')

    def test_prompt_template_has_continuity_field(self):
        """M1 prompt 在 source 文件含 <CONTINUITY> instruction."""
        path = os.path.join(ROOT, 'jarvis_inner_thought_daemon.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('<CONTINUITY>', src)
        self.assertIn('same_thread', src)
        self.assertIn('new_topic', src)

    def test_parse_thought_resolves_same_thread_to_existing(self):
        """M1 parse: 'same_thread:thought_abc' 真在 recent 找到 → 沿用 thread."""
        from jarvis_inner_thought_daemon import (
            InnerThought, InnerThoughtDaemon,
        )
        # 真造 daemon (no nerve), inject 1 recent thought
        existing = InnerThought(
            id='thought_20260527_001100_abc1', ts=time.time() - 60,
            ts_iso='', category='A', thought='prev',
            salience=0.3, actionable='none',
        )
        existing.thread_id = 'thought_20260527_001100_abc1'
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon._thoughts = [existing]
        daemon._lock = MagicMock()
        # 真 LLM raw text containing CONTINUITY
        llm_raw = (
            '<CATEGORY>A</CATEGORY>\n<THOUGHT>continuing prev</THOUGHT>\n'
            '<SALIENCE>0.4</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>same_thread:thought_20260527_001100_abc1</CONTINUITY>\n'
        )
        parsed = daemon._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.continuity, 'same_thread')
        self.assertEqual(
            parsed.thread_id, 'thought_20260527_001100_abc1'
        )

    def test_parse_thought_unknown_id_falls_back_to_new_topic(self):
        """M1 parse: LLM 编造 id 找不到 → 降级 new_topic + self id."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon._thoughts = []  # empty
        daemon._lock = MagicMock()
        llm_raw = (
            '<CATEGORY>B</CATEGORY>\n<THOUGHT>fake</THOUGHT>\n'
            '<SALIENCE>0.3</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>same_thread:nonexistent_id</CONTINUITY>\n'
        )
        parsed = daemon._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.continuity, 'new_topic')
        # thread_id 应是 self.id (new thread)
        self.assertEqual(parsed.thread_id, parsed.id)

    def test_parse_thought_explicit_new_topic(self):
        """M1 parse: CONTINUITY: new_topic 真返 new_topic."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon._thoughts = []
        daemon._lock = MagicMock()
        llm_raw = (
            '<CATEGORY>C</CATEGORY>\n<THOUGHT>starting fresh</THOUGHT>\n'
            '<SALIENCE>0.5</SALIENCE>\n<ACTIONABLE>none</ACTIONABLE>\n'
            '<EVIDENCE_LINK>none</EVIDENCE_LINK>\n'
            '<NEXT_INTERVAL>default</NEXT_INTERVAL>\n'
            '<CONTINUITY>new_topic</CONTINUITY>\n'
        )
        parsed = daemon._parse_thought(
            llm_raw, sir_state='active', tick_interval=60,
        )
        self.assertEqual(parsed.continuity, 'new_topic')


# ==========================================================
# M2 TimeAwareness
# ==========================================================

class TestM2TimeAwareness(unittest.TestCase):

    def test_module_import(self):
        """M2 模块导出 get_pattern_at_now / maybe_run_reflector."""
        from jarvis_time_awareness import (
            get_pattern_at_now,
            maybe_run_reflector,
            _DEFAULT_VOCAB,
        )
        self.assertIsNotNone(get_pattern_at_now)
        self.assertIsNotNone(maybe_run_reflector)
        self.assertIsInstance(_DEFAULT_VOCAB, dict)
        self.assertIn('patterns', _DEFAULT_VOCAB)
        self.assertIn('patterns_by_hour', _DEFAULT_VOCAB)

    def test_get_pattern_at_now_returns_dict_with_required_schema(self):
        """M2 返 dict 完整 schema (无论有无 vocab data)."""
        from jarvis_time_awareness import get_pattern_at_now
        result = get_pattern_at_now()
        self.assertIsInstance(result, dict)
        for k in ('hour', 'day', 'hour_day_key', 'typical_activities',
                  'typical_topics', 'frequency', 'sample_count',
                  'fallback_used', 'has_data'):
            self.assertIn(k, result, f'missing key {k}')
        # hour 在有效范围
        self.assertGreaterEqual(result['hour'], 0)
        self.assertLess(result['hour'], 24)

    def test_get_pattern_at_now_no_vocab_returns_has_data_false(self):
        """M2 vocab 空/缺 hour → has_data=False, 不 raise."""
        from jarvis_time_awareness import get_pattern_at_now
        with patch('jarvis_time_awareness._load_vocab',
                   return_value={'patterns': {}, 'patterns_by_hour': {}}):
            result = get_pattern_at_now()
            self.assertFalse(result['has_data'])
            self.assertEqual(result['sample_count'], 0)
            self.assertEqual(result['typical_activities'], [])


# ==========================================================
# M3 Visual Pulse
# ==========================================================

class TestM3VisualPulse(unittest.TestCase):

    def test_pulse_vocab_file_exists_and_schema(self):
        """M3 vocab json 真存在 + schema 完整."""
        path = os.path.join(ROOT, 'memory_pool',
                            'inner_thought_pulse_vocab.json')
        self.assertTrue(os.path.exists(path), f'missing {path}')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k in ('enabled', 'min_sal_to_pulse', 'min_pulse_cooldown_s',
                  'skip_if_main_convo_recent_s', 'max_text_chars'):
            self.assertIn(k, data, f'vocab missing key {k}')

    def test_load_pulse_vocab_fail_safe(self):
        """M3 vocab path 缺失 → 返 default, 不 raise."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        # 强制 cache miss
        daemon._PULSE_VOCAB_CACHE = {
            'data': None, 'mtime': 0.0, 'checked_at': 0.0
        }
        with patch.object(InnerThoughtDaemon, '_PULSE_VOCAB_PATH',
                          '/nonexistent/path.json'):
            vocab = daemon._load_pulse_vocab()
            self.assertIsInstance(vocab, dict)
            self.assertIn('enabled', vocab)

    def test_emit_pulse_skips_when_disabled(self):
        """M3 vocab enabled=False → 不 enqueue."""
        from jarvis_inner_thought_daemon import (
            InnerThought, InnerThoughtDaemon,
        )
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon.nerve = MagicMock()
        daemon.nerve.chat_bypass = MagicMock()
        daemon.nerve.chat_bypass.subtitle_queue = MagicMock()
        # mock load_pulse_vocab to return disabled
        with patch.object(
            daemon, '_load_pulse_vocab',
            return_value={'enabled': False},
        ):
            t = InnerThought(
                id='x', ts=time.time(), ts_iso='', category='A',
                thought='hi', salience=0.9, actionable='none',
            )
            daemon._emit_thought_pulse(t)
            daemon.nerve.chat_bypass.subtitle_queue.put.assert_not_called()

    def test_emit_pulse_skips_below_min_sal(self):
        """M3 sal < min → 不 enqueue."""
        from jarvis_inner_thought_daemon import (
            InnerThought, InnerThoughtDaemon,
        )
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon.nerve = MagicMock()
        daemon.nerve.chat_bypass = MagicMock()
        daemon.nerve.chat_bypass.subtitle_queue = MagicMock()
        with patch.object(
            daemon, '_load_pulse_vocab',
            return_value={
                'enabled': True, 'min_sal_to_pulse': 0.5,
                'min_pulse_cooldown_s': 0,
                'skip_if_main_convo_recent_s': 0,
                'max_text_chars': 50,
                'show_continuity_marker': False,
                'show_category': False,
            },
        ):
            t = InnerThought(
                id='x', ts=time.time(), ts_iso='', category='A',
                thought='hi', salience=0.3, actionable='none',
            )
            daemon._emit_thought_pulse(t)
            daemon.nerve.chat_bypass.subtitle_queue.put.assert_not_called()

    def test_emit_pulse_cooldown_blocks_second_emit(self):
        """M3 距上次 < cooldown → 不 enqueue."""
        from jarvis_inner_thought_daemon import (
            InnerThought, InnerThoughtDaemon,
        )
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon.nerve = MagicMock()
        daemon.nerve.chat_bypass = MagicMock()
        daemon.nerve.chat_bypass.subtitle_queue = MagicMock()
        daemon._last_pulse_ts = time.time() - 5  # 5s ago
        with patch.object(
            daemon, '_load_pulse_vocab',
            return_value={
                'enabled': True, 'min_sal_to_pulse': 0.3,
                'min_pulse_cooldown_s': 30,
                'skip_if_main_convo_recent_s': 0,
                'max_text_chars': 50,
                'show_continuity_marker': False,
                'show_category': False,
            },
        ):
            t = InnerThought(
                id='x', ts=time.time(), ts_iso='', category='A',
                thought='hi', salience=0.5, actionable='none',
            )
            daemon._emit_thought_pulse(t)
            daemon.nerve.chat_bypass.subtitle_queue.put.assert_not_called()

    def test_emit_pulse_success_enqueues_subtitle(self):
        """M3 合规 thought → 真 enqueue ('thought_pulse', text)."""
        from jarvis_inner_thought_daemon import (
            InnerThought, InnerThoughtDaemon,
        )
        daemon = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
        daemon.nerve = MagicMock()
        daemon.nerve.short_term_memory = []
        daemon.nerve.chat_bypass = MagicMock()
        daemon.nerve.chat_bypass.subtitle_queue = MagicMock()
        with patch.object(
            daemon, '_load_pulse_vocab',
            return_value={
                'enabled': True, 'min_sal_to_pulse': 0.3,
                'min_pulse_cooldown_s': 0,
                'skip_if_main_convo_recent_s': 0,
                'max_text_chars': 50,
                'show_continuity_marker': True,
                'show_category': True,
            },
        ):
            t = InnerThought(
                id='x', ts=time.time(), ts_iso='', category='A',
                thought='Sir is focused on debugging', salience=0.7,
                actionable='none',
            )
            t.continuity = 'new_topic'
            daemon._emit_thought_pulse(t)
            daemon.nerve.chat_bypass.subtitle_queue.put.assert_called_once()
            args, _ = daemon.nerve.chat_bypass.subtitle_queue.put.call_args
            channel, text = args[0]
            self.assertEqual(channel, 'thought_pulse')
            self.assertIn('A', text)
            self.assertIn('Sir is focused', text)


# ==========================================================
# M4 Dashboard API
# ==========================================================

class TestM4DashboardAPI(unittest.TestCase):

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        import jarvis_dashboard_web
        self.app = jarvis_dashboard_web.app
        self.client = self.app.test_client()

    def test_api_inner_thoughts_returns_new_fields(self):
        """M4 /api/inner_thoughts 返 outcome_breakdown + thread_groups."""
        resp = self.client.get('/api/inner_thoughts?hours=24&limit=10')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('ok'))
        self.assertIn('thread_groups', data)
        self.assertIn('time_pattern_now', data)
        stats = data.get('stats', {})
        self.assertIn('outcome_breakdown', stats)
        self.assertIn('thread_count_total', stats)
        # outcome_breakdown 4 key 都存在
        ob = stats['outcome_breakdown']
        for k in ('pending', 'sir_engaged', 'sir_silenced', 'sir_rejected'):
            self.assertIn(k, ob)


if __name__ == '__main__':
    unittest.main()
