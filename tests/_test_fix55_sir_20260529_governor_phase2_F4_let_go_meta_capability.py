# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 governor Phase 2 F4] '放下' 元能力 — let_go topics.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F4
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → governor

修缮目标 (V5 + Sir 真痛 anchor):
  Sir 真痛: "重复思考严重, 放下元能力一直没立"
  治本: LLM 自决 <LET_GO>thread_id</LET_GO> tag → daemon 持久化 + TTL prune

F4 真改:
  1. memory_pool/inner_voice_aging_config.json 加 `topic_repeat` 段
  2. jarvis_inner_thought_daemon.py:
     - module-level: _LET_GO_TOPICS_PATH + _LET_GO_LOCK
     - 新 helper _get_topic_repeat_config / _load_let_go_topics /
       _save_let_go_topics / _add_let_go_topic / _remove_let_go_topic
     - _collect_evidence: topic_distribution 加 aged_flag + ev['active_let_go_topics']
       + prune recent_thoughts + topic_distribution per active let_go
     - _build_prompt:
       * TOPIC DISTRIBUTION block 加 🍂 AGED mark + LET_GO 教学
       * 新 [ACTIVELY LETTING GO] block 渲染 active let_go
       * FORMAT 段加 <LET_GO> tag 教学
     - _parse_thought: 加 <LET_GO> tag 解析 + prefix-match + _add_let_go_topic
  3. scripts/let_go_dump.py CLI (list/add/extend/revoke/clear/config)

测试覆盖 (12 testcase):
  - F4_1: _get_topic_repeat_config 默认 (10, 60, 30) + sanity cap
  - F4_2: _add_let_go_topic 新增 + persist
  - F4_3: _add_let_go_topic 同 thread_id → extend ttl
  - F4_4: _load_let_go_topics prune expired
  - F4_5: _remove_let_go_topic 工作 + not_found 返 False
  - F4_6: _collect_evidence topic_distribution 加 aged_flag (count >= max_occ)
  - F4_7: _collect_evidence prune recent_thoughts per active let_go
  - F4_8: _collect_evidence ev['active_let_go_topics'] 含 entries
  - F4_9: _build_prompt [TOPIC DISTRIBUTION] 含 🍂 AGED + LET_GO 教学
  - F4_10: _build_prompt [ACTIVELY LETTING GO] block 渲染
  - F4_11: _parse_thought <LET_GO> prefix-match thread → 调 _add_let_go_topic
  - F4_12: _parse_thought <LET_GO> hallucinated id → skip (不 add)
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


def _isolated_let_go_path():
    """生成隔离的 tmp let_go_topics.json path (避免污染 prod)."""
    fd, path = tempfile.mkstemp(suffix='_let_go.json')
    os.close(fd)
    os.unlink(path)  # 确保不存在 (load 返 [])
    return path


def _make_thought(thread_id='thr_test', age_s=60, content='Test thought',
                  thought_id=None):
    """构 InnerThought, 指定 thread_id."""
    from jarvis_inner_thought_daemon import InnerThought
    ts = time.time() - age_s
    return InnerThought(
        id=thought_id or f'th_{int(ts * 1000)}_{age_s}',
        ts=ts,
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts)),
        category='B',
        thought=content,
        salience=0.7,
        actionable='none',
        evidence_link='none',
        thread_id=thread_id,
    )


class TestF4VocabHelper(unittest.TestCase):
    """F4_1: _get_topic_repeat_config."""

    def test_F4_1_default_and_sanity_cap(self):
        """F4_1: seed 默认 (vocab 缺失 fallback) → (10, 60, 30) + sanity cap.

        🆕 [Sir 2026-06-02] 指向不存在的 aging config path 测 seed fallback,
        不读 live vocab — live max_occurrences 是 Sir 可调值 (准则 6/7)。
        topic_repeat 经 jarvis_inner_voice_track._load_aging_config 读, 故 patch 那里。
        """
        import jarvis_inner_voice_track as ivt
        from jarvis_inner_thought_daemon import _get_topic_repeat_config
        _orig_path = ivt._AGING_CONFIG_PATH
        _orig_cache = ivt._AGING_CFG_CACHE
        _orig_mtime = ivt._AGING_CFG_CACHE_MTIME
        try:
            ivt._AGING_CONFIG_PATH = '/nonexistent/_seed_fallback_only.json'
            ivt._AGING_CFG_CACHE = None
            ivt._AGING_CFG_CACHE_MTIME = 0.0
            max_occ, win_min, default_ttl = _get_topic_repeat_config()
        finally:
            ivt._AGING_CONFIG_PATH = _orig_path
            ivt._AGING_CFG_CACHE = _orig_cache
            ivt._AGING_CFG_CACHE_MTIME = _orig_mtime
        # seed 默认值 (_AGING_CFG_DEFAULT.topic_repeat 缺失 → helper fallback 10/60/30)
        self.assertEqual(max_occ, 10)
        self.assertEqual(win_min, 60)
        self.assertEqual(default_ttl, 30)


class TestF4Storage(unittest.TestCase):
    """F4_2/3/4/5: storage helpers."""

    def setUp(self):
        self.tmp_path = _isolated_let_go_path()
        import jarvis_inner_thought_daemon as m
        self._patcher = patch.object(m, '_LET_GO_TOPICS_PATH', self.tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self.tmp_path):
                os.unlink(self.tmp_path)
        except Exception:
            pass

    def test_F4_2_add_and_persist(self):
        """F4_2: _add_let_go_topic 持久化 + 可读回."""
        from jarvis_inner_thought_daemon import (
            _add_let_go_topic, _load_let_go_topics,
        )
        ok = _add_let_go_topic(
            thread_id='thr_test_xyz',
            ttl_min=5,
            source='llm',
            thought_id='th_origin',
            reason='Sir requested let go',
        )
        self.assertTrue(ok)
        active = _load_let_go_topics()
        self.assertEqual(len(active), 1)
        e = active[0]
        self.assertEqual(e['thread_id'], 'thr_test_xyz')
        self.assertEqual(e['source'], 'llm')
        self.assertEqual(e['reason'], 'Sir requested let go')
        self.assertGreater(e['ttl_ts'], time.time())

    def test_F4_3_dedup_extend_existing(self):
        """F4_3: 同 thread_id 二次 add → extend ttl, 不重复 entry."""
        from jarvis_inner_thought_daemon import (
            _add_let_go_topic, _load_let_go_topics,
        )
        _add_let_go_topic('thr_xyz', ttl_min=5, source='llm')
        active1 = _load_let_go_topics()
        self.assertEqual(len(active1), 1)
        ttl1 = active1[0]['ttl_ts']
        # 加同 thread_id with longer ttl
        time.sleep(0.01)
        _add_let_go_topic('thr_xyz', ttl_min=30,
                          source='sir_manual', reason='extend')
        active2 = _load_let_go_topics()
        self.assertEqual(len(active2), 1, "F4_3 同 thread_id 不重复 entry")
        ttl2 = active2[0]['ttl_ts']
        self.assertGreater(ttl2, ttl1, "F4_3 二次 add 应 extend ttl")
        # extend_history 应有记录
        self.assertGreater(len(active2[0].get('extend_history', [])), 0)

    def test_F4_4_load_prunes_expired(self):
        """F4_4: _load_let_go_topics 自动 prune expired entries."""
        from jarvis_inner_thought_daemon import (
            _save_let_go_topics, _load_let_go_topics,
        )
        # 直接 save 含 expired entry
        _save_let_go_topics([
            {
                'thread_id': 'thr_old',
                'ttl_ts': time.time() - 100,  # expired
                'source': 'test',
                'reason': 'old',
                'created_at_iso': '2026-05-29T00:00:00',
            },
            {
                'thread_id': 'thr_new',
                'ttl_ts': time.time() + 3600,  # valid
                'source': 'test',
                'reason': 'new',
                'created_at_iso': '2026-05-29T00:30:00',
            },
        ])
        active = _load_let_go_topics()
        self.assertEqual(len(active), 1, "F4_4 应 prune expired")
        self.assertEqual(active[0]['thread_id'], 'thr_new')

    def test_F4_5_remove_works(self):
        """F4_5: _remove_let_go_topic 工作 + not_found 返 False."""
        from jarvis_inner_thought_daemon import (
            _add_let_go_topic, _remove_let_go_topic, _load_let_go_topics,
        )
        _add_let_go_topic('thr_a', ttl_min=5)
        _add_let_go_topic('thr_b', ttl_min=5)
        # remove existing
        ok = _remove_let_go_topic('thr_a')
        self.assertTrue(ok)
        active = _load_let_go_topics()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['thread_id'], 'thr_b')
        # remove non-existing
        ok2 = _remove_let_go_topic('thr_nonexist')
        self.assertFalse(ok2, "F4_5 not_found 应返 False")


class TestF4CollectEvidence(unittest.TestCase):
    """F4_6/7/8: _collect_evidence aged_flag + prune + active_let_go_topics."""

    def setUp(self):
        # 清 vocab cache
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0
        # 隔离 let_go path
        self.tmp_path = _isolated_let_go_path()
        import jarvis_inner_thought_daemon as m
        self._patcher = patch.object(m, '_LET_GO_TOPICS_PATH', self.tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self.tmp_path):
                os.unlink(self.tmp_path)
        except Exception:
            pass

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            return InnerThoughtDaemon(key_router=MagicMock())

    def test_F4_6_aged_flag_when_count_ge_max(self):
        """F4_6: topic_distribution 加 aged_flag (count >= max_occ).

        🆕 [Sir 2026-06-02] patch aging config 到固定 threshold=10 测契约,
        不依赖 live vocab (Sir 可调 max_occurrences, 准则 6/7)。
        """
        import jarvis_inner_voice_track as ivt
        daemon = self._make_daemon()
        # 12 thoughts thr_aged (≥ 10) + 5 thr_young (< 10)
        thoughts = (
            [_make_thought('thr_aged', age_s=60 + i) for i in range(12)]
            + [_make_thought('thr_young', age_s=60 + i)
                for i in range(5)]
        )
        with daemon._lock:
            daemon._thoughts = thoughts
        _fixed_cfg = {
            'topic_repeat': {
                'max_occurrences_in_window': 10,
                'window_min': 60,
                'default_let_go_ttl_min': 30,
            }
        }
        with patch.object(ivt, '_load_aging_config', return_value=_fixed_cfg):
            ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        td = ev.get('topic_distribution', {})
        topics = td.get('topics', [])
        # 找 thr_aged + thr_young
        aged = next(t for t in topics if t['thread_id_short'] == 'thr_aged')
        young = next(t for t in topics if t['thread_id_short'] == 'thr_young')
        self.assertTrue(aged['aged_flag'], "F4_6 count=12 应 aged_flag=True")
        self.assertFalse(young['aged_flag'], "F4_6 count=5 应 aged_flag=False")
        # ev 含 aged_threshold + default_let_go_ttl_min
        self.assertEqual(td['aged_threshold'], 10)
        self.assertEqual(td['default_let_go_ttl_min'], 30)

    def test_F4_7_prune_recent_thoughts_per_active_let_go(self):
        """F4_7: active let_go thread_id 从 recent_thoughts prune."""
        daemon = self._make_daemon()
        # 加 active let_go for thr_silenced
        from jarvis_inner_thought_daemon import _add_let_go_topic
        _add_let_go_topic('thr_silenced', ttl_min=30)
        # 注入 mock thoughts: thr_silenced + thr_visible
        with daemon._lock:
            daemon._thoughts = [
                _make_thought('thr_silenced', age_s=60, content='silenced 1'),
                _make_thought('thr_silenced', age_s=120, content='silenced 2'),
                _make_thought('thr_visible', age_s=180, content='visible 1'),
            ]
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        # recent_thoughts 应只含 thr_visible
        rt = ev.get('recent_thoughts', [])
        thread_ids = [t['thread_id'] for t in rt]
        self.assertNotIn('thr_silenced', thread_ids,
                          "F4_7 thr_silenced 应被 prune")
        self.assertIn('thr_visible', thread_ids)
        # topic_distribution 应不含 thr_silenced
        td_topics = ev.get('topic_distribution', {}).get('topics', [])
        td_ids = [t['thread_id_short'] for t in td_topics]
        self.assertNotIn('thr_silenced', td_ids,
                          "F4_7 thr_silenced 应从 topic_distribution prune")

    def test_F4_8_ev_contains_active_let_go_topics(self):
        """F4_8: ev['active_let_go_topics'] 含 entries + ttl_remaining_s."""
        daemon = self._make_daemon()
        from jarvis_inner_thought_daemon import _add_let_go_topic
        _add_let_go_topic('thr_alpha', ttl_min=30, source='llm',
                          reason='cycle too much')
        _add_let_go_topic('thr_beta', ttl_min=15, source='sir_manual',
                          reason='manual silence')
        with daemon._lock:
            daemon._thoughts = []
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        lg = ev.get('active_let_go_topics', [])
        self.assertEqual(len(lg), 2)
        # 找 thr_alpha + thr_beta
        ids = [e['thread_id_short'] for e in lg]
        self.assertIn('thr_alpha', ids)
        self.assertIn('thr_beta', ids)
        # ttl_remaining_s 应 > 0
        for e in lg:
            self.assertGreater(e['ttl_remaining_s'], 0)


class TestF4PromptRender(unittest.TestCase):
    """F4_9/10: _build_prompt 渲染."""

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

    def test_F4_9_topic_distribution_renders_aged_mark_and_let_go_teaching(self):
        """F4_9: [TOPIC DISTRIBUTION] 含 🍂 AGED + <LET_GO> 教学."""
        daemon = self._make_daemon()
        mock_ev = {
            'sir_state': 'active', 'idle_seconds': 60, 'hour': 0,
            'recent_thoughts': [],
            'swm_events': [],
            'topic_distribution': {
                'lookback_min': 60,
                'warning_threshold': 10,
                'aged_threshold': 10,
                'default_let_go_ttl_min': 30,
                'topics': [
                    {'thread_id_short': 'thr_aged_xx', 'count': 22,
                     'last_age_s': 60, 'aged_flag': True},
                    {'thread_id_short': 'thr_young', 'count': 3,
                     'last_age_s': 180, 'aged_flag': False},
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
        # 🍂 AGED mark 应在 thr_aged 行
        for line in user_prompt.splitlines():
            if 'thr_aged_xx' in line:
                self.assertIn('🍂 AGED', line,
                              "F4_9 aged_flag=True 行应含 🍂 AGED")
                break
        # <LET_GO> 教学应在 (TOPIC DISTRIBUTION 后)
        self.assertIn('<LET_GO>', user_prompt)
        self.assertIn('AGED topics', user_prompt)

    def test_F4_10_actively_letting_go_block_renders(self):
        """F4_10: [ACTIVELY LETTING GO] block 含 active let_go entries."""
        daemon = self._make_daemon()
        mock_ev = {
            'sir_state': 'active', 'idle_seconds': 60, 'hour': 0,
            'recent_thoughts': [],
            'swm_events': [],
            'active_let_go_topics': [
                {'thread_id_short': 'thr_xyz', 'reason': 'cycle 22 times',
                 'source': 'llm', 'ttl_remaining_s': 1700},
                {'thread_id_short': 'thr_abc', 'reason': 'sir requested',
                 'source': 'sir_manual', 'ttl_remaining_s': 600},
            ],
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
        self.assertIn('[ACTIVELY LETTING GO', user_prompt)
        self.assertIn('thr_xyz', user_prompt)
        self.assertIn('cycle 22 times', user_prompt)
        self.assertIn('thr_abc', user_prompt)
        self.assertIn('sir_manual', user_prompt)


class TestF4ParseLetGo(unittest.TestCase):
    """F4_11/12: _parse_thought <LET_GO> tag."""

    def setUp(self):
        self.tmp_path = _isolated_let_go_path()
        import jarvis_inner_thought_daemon as m
        self._patcher = patch.object(m, '_LET_GO_TOPICS_PATH', self.tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self.tmp_path):
                os.unlink(self.tmp_path)
        except Exception:
            pass

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            return InnerThoughtDaemon(key_router=MagicMock())

    def test_F4_11_let_go_prefix_match_adds_topic(self):
        """F4_11: <LET_GO> prefix-match thread → 调 _add_let_go_topic."""
        daemon = self._make_daemon()
        # 注入 prior thought with thread_id (LLM 看 thread_id_short 12 char)
        full_tid = 'thread_20260529_001234_5678'  # full thread_id
        prior = _make_thought(thread_id=full_tid, age_s=60)
        with daemon._lock:
            daemon._thoughts = [prior]
        # 模拟 LLM raw output: prefix 12 char (LLM 看到的 short)
        raw = f"""
<CATEGORY>B</CATEGORY>
<THOUGHT>I've been cycling on this 22 times, letting go.</THOUGHT>
<SALIENCE>0.85</SALIENCE>
<ACTIONABLE>none</ACTIONABLE>
<EVIDENCE_LINK>none</EVIDENCE_LINK>
<LET_GO>{full_tid[:16]}</LET_GO>
"""
        thought = daemon._parse_thought(raw, sir_state='active',
                                          tick_interval=60)
        self.assertIsNotNone(thought)
        # 验 let_go 真持久化
        from jarvis_inner_thought_daemon import _load_let_go_topics
        active = _load_let_go_topics()
        self.assertEqual(len(active), 1,
                          "F4_11 <LET_GO> 真 prefix-match 应 _add")
        self.assertTrue(
            active[0]['thread_id'].startswith(full_tid[:16]),
            "F4_11 stored thread_id 应是 full"
        )
        self.assertEqual(active[0]['source'], 'llm')

    def test_F4_12_let_go_hallucinated_id_skipped(self):
        """F4_12: <LET_GO> hallucinated id (不在 recent_thoughts) → 跳."""
        daemon = self._make_daemon()
        # 注入 prior with different thread_id
        prior = _make_thought(thread_id='real_thread_xyz', age_s=60)
        with daemon._lock:
            daemon._thoughts = [prior]
        # LLM hallucinate 编造 id
        raw = """
<CATEGORY>B</CATEGORY>
<THOUGHT>letting go of nonexistent thread.</THOUGHT>
<SALIENCE>0.8</SALIENCE>
<ACTIONABLE>none</ACTIONABLE>
<EVIDENCE_LINK>none</EVIDENCE_LINK>
<LET_GO>fake_hallucinated_thr_id</LET_GO>
"""
        thought = daemon._parse_thought(raw, sir_state='active',
                                          tick_interval=60)
        self.assertIsNotNone(thought)
        # 验 let_go 没持久化 (hallucinated id 跳)
        from jarvis_inner_thought_daemon import _load_let_go_topics
        active = _load_let_go_topics()
        self.assertEqual(len(active), 0,
                          "F4_12 hallucinated id 应跳, 不 add")


if __name__ == '__main__':
    unittest.main(verbosity=2)
