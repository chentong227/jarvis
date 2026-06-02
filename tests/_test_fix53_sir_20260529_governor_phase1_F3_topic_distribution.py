# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 00:30 拍板 governor Phase 1 F3] topic distribution hint in evidence.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F3 (Phase 1)
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → Phase 4 governor

修缮目标 (E4 evidence 维度化):
  思考脑没看到主题分布 → 不知自己重复 think 22 次同事 → 元意识断.
  治本: 加 [TOPIC DISTRIBUTION] block, count by thread_id in window,
  ⚠️ mark threshold≥occurrences. LLM 视觉自然激活 let_go (Phase 2 实现标签).

F3 真改:
  1. memory_pool/inner_thought_pacing_vocab.json 加 `topic_distribution` block
  2. jarvis_inner_thought_daemon.py:
     - _PACING_DEFAULT_CONFIG 加 'topic_distribution' fallback
     - _load_pacing_config deep-merge whitelist 加入
     - 新 helper `_get_topic_distribution_config() -> (lookback_min, threshold, max_topics)`
     - _collect_evidence 加 ev['topic_distribution'] 字段 (count by thread_id)
     - _build_prompt 加 [TOPIC DISTRIBUTION] block 渲染

测试覆盖 (7 testcase):
  - F3_1: helper 默认返 (60, 10, 10)
  - F3_2: vocab 改值 → hot reload
  - F3_3: vocab missing → fallback
  - F3_4: sanity cap
  - F3_5: _collect_evidence 加 ev['topic_distribution'] 含 count by thread_id
  - F3_6: cutoff 外 thought 不算 (window 隔离)
  - F3_7: _build_prompt 渲染 [TOPIC DISTRIBUTION] + ⚠️ mark threshold≥
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


def _make_thought(thread_id='thr_main', age_s=60, content='Test thought'):
    """构 InnerThought, 指定 thread_id."""
    from jarvis_inner_thought_daemon import InnerThought
    ts = time.time() - age_s
    return InnerThought(
        id=f'th_{int(ts * 1000)}_{age_s}',
        ts=ts,
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts)),
        category='B',
        thought=content,
        salience=0.7,
        actionable='none',
        evidence_link='none',
        thread_id=thread_id,
    )


class TestF3Helper(unittest.TestCase):
    """F3 helper `_get_topic_distribution_config()`."""

    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def test_F3_1_default(self):
        """F3_1: seed 默认 (vocab 文件缺失时 fallback) → (60, 10, 10).

        🆕 [Sir 2026-06-02] 指向不存在的 vocab path 测 seed fallback 契约,
        不读 live vocab — live warning_threshold 是 Sir 可调值 (准则 6/7),
        硬断言 live 值会随 Sir 调参而脆断。seed 常量才是契约。
        """
        import jarvis_inner_thought_daemon as m
        with patch.object(m, '_PACING_VOCAB_PATH',
                          '/nonexistent/_seed_fallback_only.json'):
            m._PACING_VOCAB_CACHE['data'] = None
            m._PACING_VOCAB_CACHE['mtime'] = 0.0
            m._PACING_VOCAB_CACHE['checked_at'] = 0.0
            lookback, warn, max_topics = m._get_topic_distribution_config()
        self.assertEqual(lookback, 60)
        self.assertEqual(warn, 10)
        self.assertEqual(max_topics, 10)

    def test_F3_2_vocab_hot_reload(self):
        """F3_2: vocab 改值 → hot reload."""
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'topic_distribution': {
                    'lookback_min': 30,
                    'warning_threshold': 5,
                    'max_topics_shown': 15,
                }
            }, f)
            tmp_path = f.name
        try:
            with patch.object(m, '_PACING_VOCAB_PATH', tmp_path):
                m._PACING_VOCAB_CACHE['data'] = None
                m._PACING_VOCAB_CACHE['mtime'] = 0.0
                m._PACING_VOCAB_CACHE['checked_at'] = 0.0
                lookback, warn, max_topics = (
                    m._get_topic_distribution_config()
                )
            self.assertEqual(lookback, 30)
            self.assertEqual(warn, 5)
            self.assertEqual(max_topics, 15)
        finally:
            os.unlink(tmp_path)

    def test_F3_3_vocab_missing_fallback(self):
        """F3_3: vocab missing → fallback (60, 10, 10)."""
        import jarvis_inner_thought_daemon as m
        with patch.object(
            m, '_PACING_VOCAB_PATH',
            os.path.join(tempfile.gettempdir(), 'nonexist_xyz.json')
        ):
            m._PACING_VOCAB_CACHE['data'] = None
            m._PACING_VOCAB_CACHE['mtime'] = 0.0
            m._PACING_VOCAB_CACHE['checked_at'] = 0.0
            lookback, warn, max_topics = m._get_topic_distribution_config()
        self.assertEqual(lookback, 60)
        self.assertEqual(warn, 10)
        self.assertEqual(max_topics, 10)

    def test_F3_4_sanity_cap(self):
        """F3_4: 越界 sanity cap (lookback>360, warn>100, max>30)."""
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'topic_distribution': {
                    'lookback_min': 9999,
                    'warning_threshold': 9999,
                    'max_topics_shown': 9999,
                }
            }, f)
            tmp_path = f.name
        try:
            with patch.object(m, '_PACING_VOCAB_PATH', tmp_path):
                m._PACING_VOCAB_CACHE['data'] = None
                m._PACING_VOCAB_CACHE['mtime'] = 0.0
                m._PACING_VOCAB_CACHE['checked_at'] = 0.0
                lookback, warn, max_topics = (
                    m._get_topic_distribution_config()
                )
            self.assertEqual(lookback, 360, "F3_4 lookback sanity cap 360")
            self.assertEqual(warn, 100, "F3_4 warn sanity cap 100")
            self.assertEqual(max_topics, 30, "F3_4 max_topics sanity cap 30")
        finally:
            os.unlink(tmp_path)


class TestF3CollectEvidence(unittest.TestCase):
    """F3 `_collect_evidence` 加 ev['topic_distribution']."""

    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            return InnerThoughtDaemon(key_router=MagicMock())

    def test_F3_5_count_by_thread_id(self):
        """F3_5: evidence 'topic_distribution' 含 count by thread_id."""
        daemon = self._make_daemon()
        # 注入 mock thoughts: 22 thr_sleep + 18 thr_proactive + 3 thr_hydration
        thoughts = (
            [_make_thought('thr_sleep', age_s=60 * (i + 1))
             for i in range(22)]
            + [_make_thought('thr_proactive', age_s=60 * (i + 1) + 30)
                for i in range(18)]
            + [_make_thought('thr_hydration', age_s=60 * (i + 1) + 60)
                for i in range(3)]
        )
        with daemon._lock:
            daemon._thoughts = thoughts
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        td = ev.get('topic_distribution', {})
        topics = td.get('topics', [])
        # 应至少 3 topics (按 count desc 排)
        self.assertGreaterEqual(len(topics), 3, "F3_5 应至少 3 topics")
        # top topic 应是 thr_sleep (22 count)
        self.assertEqual(topics[0]['thread_id_short'], 'thr_sleep')
        self.assertEqual(topics[0]['count'], 22)
        # 2nd topic thr_proactive 18 count
        self.assertEqual(topics[1]['thread_id_short'], 'thr_proactive')
        self.assertEqual(topics[1]['count'], 18)

    def test_F3_6_cutoff_window_isolation(self):
        """F3_6: cutoff 外 thought 不算 (window 隔离)."""
        daemon = self._make_daemon()
        # 5 in window + 5 outside (60min default cutoff)
        thoughts = (
            [_make_thought('thr_recent', age_s=60 * (i + 1))
             for i in range(5)]  # 1, 2, 3, 4, 5min ago
            + [_make_thought('thr_old', age_s=60 * 90 + 60 * i)
                for i in range(5)]  # 90, 91, 92, 93, 94min ago (outside 60)
        )
        with daemon._lock:
            daemon._thoughts = thoughts
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        td = ev.get('topic_distribution', {})
        topics = td.get('topics', [])
        thread_ids = [t['thread_id_short'] for t in topics]
        self.assertIn('thr_recent', thread_ids,
                      "F3_6 thr_recent 应在 (within 60min)")
        self.assertNotIn('thr_old', thread_ids,
                          "F3_6 thr_old 不应在 (outside 60min cutoff)")


class TestF3PromptRender(unittest.TestCase):
    """F3 `_build_prompt` 渲染 [TOPIC DISTRIBUTION]."""

    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def test_F3_7_prompt_contains_topic_distribution_block(self):
        """F3_7: prompt 含 [TOPIC DISTRIBUTION] block + ⚠️ mark."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            daemon = InnerThoughtDaemon(key_router=MagicMock())
        mock_ev = {
            'sir_state': 'active',
            'idle_seconds': 60,
            'hour': 0,
            'recent_thoughts': [],
            'swm_events': [],
            'topic_distribution': {
                'lookback_min': 60,
                'warning_threshold': 10,
                'topics': [
                    {'thread_id_short': 'thr_sleep', 'count': 22,
                     'last_age_s': 180},
                    {'thread_id_short': 'thr_hydration', 'count': 3,
                     'last_age_s': 720},
                ],
            },
        }
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=MagicMock(recent=MagicMock(return_value=[]))
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            _system, user_prompt = daemon._build_prompt(
                sir_state='active', evidence=mock_ev,
            )
        # 必含 block label
        self.assertIn('[TOPIC DISTRIBUTION', user_prompt,
                      "F3_7 应含 '[TOPIC DISTRIBUTION' block label")
        self.assertIn('thr_sleep', user_prompt,
                      "F3_7 应含 thr_sleep topic")
        self.assertIn('22 occurrences', user_prompt,
                      "F3_7 应含 '22 occurrences'")
        # ⚠️ mark threshold>= (22 >= 10 → mark)
        # 找 thr_sleep 行后是否含 ⚠️
        for line in user_prompt.splitlines():
            if 'thr_sleep' in line:
                self.assertIn('⚠️', line,
                              "F3_7 thr_sleep (22 >= 10) 行应含 ⚠️ mark")
                break
        # thr_hydration (3 < 10) 行不该含 ⚠️
        for line in user_prompt.splitlines():
            if 'thr_hydration' in line:
                self.assertNotIn('⚠️', line,
                                  "F3_7 thr_hydration (3 < 10) 行不该含 ⚠️")
                break

    def test_F3_8_no_topic_distribution_block_when_empty(self):
        """F3_8: ev 无 topic_distribution → prompt 不含 block (优雅 fallback)."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            daemon = InnerThoughtDaemon(key_router=MagicMock())
        mock_ev = {
            'sir_state': 'active',
            'idle_seconds': 60,
            'hour': 0,
            'recent_thoughts': [],
            'swm_events': [],
            # 无 topic_distribution 字段
        }
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=MagicMock(recent=MagicMock(return_value=[]))
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            _system, user_prompt = daemon._build_prompt(
                sir_state='active', evidence=mock_ev,
            )
        self.assertNotIn('[TOPIC DISTRIBUTION', user_prompt,
                          "F3_8 evidence 无 topic_distribution → "
                          "prompt 不应含 block")


if __name__ == '__main__':
    unittest.main(verbosity=2)
