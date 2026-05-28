# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 00:30 拍板 governor Phase 1 F2] recent_thoughts 窗口可调 + 默认扩大.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F2 (Phase 1)
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → Phase 4 governor

修缮目标:
  缺口 ①: 旧版 `recent_3 = sorted(self._thoughts, key=lambda t: -t.ts)[:3]`
  思考脑只看 last 3 thought, 看不到 1h 内重复 22 次同事 → 元意识失效.

F2 真改:
  1. memory_pool/inner_thought_pacing_vocab.json 加 `recent_thoughts_lookback`
     block (n=15, min=30)
  2. jarvis_inner_thought_daemon.py:
     - 加 `_PACING_DEFAULT_CONFIG['recent_thoughts_lookback']`
     - `_load_pacing_config` deep-merge 加入 `recent_thoughts_lookback`
     - 新 helper `_get_recent_thoughts_lookback() -> (n, lookback_min)`
     - `_collect_evidence` 用 helper + cutoff + n 上限 + fallback
     - `_build_prompt` 文案 "last N within M min" dynamic

测试覆盖 (7 testcase):
  - F2_1: helper 默认返 (15, 30)
  - F2_2: vocab 改 n=20 + min=60 → helper hot-reload 返 (20, 60)
  - F2_3: vocab fail (path 不在) → fallback (15, 30)
  - F2_4: sanity cap (n=100 → 50, min=300 → 180)
  - F2_5: _collect_evidence 用 helper, last N within cutoff
  - F2_6: cutoff 内空 (老 thought) → fallback 取 last n 不管时间
  - F2_7: _build_prompt 文案 dynamic 含 "last X within Ymin"
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


def _make_thought(thought_text='Test thought', age_s=60, category='B',
                  salience=0.7):
    """构 InnerThought fake."""
    from jarvis_inner_thought_daemon import InnerThought
    ts = time.time() - age_s
    return InnerThought(
        id=f'th_test_{int(ts * 1000)}',
        ts=ts,
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(ts)),
        category=category,
        thought=thought_text,
        salience=salience,
        actionable='none',
        evidence_link='none',
    )


class TestF2Helper(unittest.TestCase):
    """F2 helper `_get_recent_thoughts_lookback()`."""

    def setUp(self):
        # 清 cache 让每个 test 独立 (避免 mtime cache 干扰)
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def test_F2_1_default_returns_15_30(self):
        """F2_1: 默认 vocab → helper 返 (15, 30)."""
        from jarvis_inner_thought_daemon import _get_recent_thoughts_lookback
        n, lookback_min = _get_recent_thoughts_lookback()
        self.assertEqual(n, 15, "F2_1 默认 n 应为 15")
        self.assertEqual(lookback_min, 30, "F2_1 默认 min 应为 30")

    def test_F2_2_vocab_hot_reload_n_20_min_60(self):
        """F2_2: vocab 改 n=20 / min=60 → helper hot-reload 返 (20, 60)."""
        import jarvis_inner_thought_daemon as daemon_mod
        # 写 tmp vocab 覆盖
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'recent_thoughts_lookback': {'n': 20, 'min': 60}
            }, f)
            tmp_path = f.name
        try:
            with patch.object(daemon_mod, '_PACING_VOCAB_PATH', tmp_path):
                # 清 cache
                daemon_mod._PACING_VOCAB_CACHE['data'] = None
                daemon_mod._PACING_VOCAB_CACHE['mtime'] = 0.0
                daemon_mod._PACING_VOCAB_CACHE['checked_at'] = 0.0
                n, lookback_min = daemon_mod._get_recent_thoughts_lookback()
            self.assertEqual(n, 20, "F2_2 vocab n=20 应生效")
            self.assertEqual(lookback_min, 60, "F2_2 vocab min=60 应生效")
        finally:
            os.unlink(tmp_path)

    def test_F2_3_vocab_missing_fallback(self):
        """F2_3: vocab path 不在 → fallback (15, 30)."""
        import jarvis_inner_thought_daemon as daemon_mod
        bogus_path = os.path.join(
            tempfile.gettempdir(), 'nonexistent_vocab_xyz.json'
        )
        with patch.object(daemon_mod, '_PACING_VOCAB_PATH', bogus_path):
            daemon_mod._PACING_VOCAB_CACHE['data'] = None
            daemon_mod._PACING_VOCAB_CACHE['mtime'] = 0.0
            daemon_mod._PACING_VOCAB_CACHE['checked_at'] = 0.0
            n, lookback_min = daemon_mod._get_recent_thoughts_lookback()
        self.assertEqual(n, 15, "F2_3 vocab fail → fallback n=15")
        self.assertEqual(lookback_min, 30, "F2_3 vocab fail → fallback min=30")

    def test_F2_4_sanity_cap(self):
        """F2_4: 越界 vocab 值被 sanity cap (n>50 → 50, min>180 → 180)."""
        import jarvis_inner_thought_daemon as daemon_mod
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'recent_thoughts_lookback': {'n': 100, 'min': 300}
            }, f)
            tmp_path = f.name
        try:
            with patch.object(daemon_mod, '_PACING_VOCAB_PATH', tmp_path):
                daemon_mod._PACING_VOCAB_CACHE['data'] = None
                daemon_mod._PACING_VOCAB_CACHE['mtime'] = 0.0
                daemon_mod._PACING_VOCAB_CACHE['checked_at'] = 0.0
                n, lookback_min = daemon_mod._get_recent_thoughts_lookback()
            self.assertEqual(n, 50, "F2_4 sanity cap n=100 → 50")
            self.assertEqual(
                lookback_min, 180, "F2_4 sanity cap min=300 → 180"
            )
        finally:
            os.unlink(tmp_path)


class TestF2CollectEvidence(unittest.TestCase):
    """F2 `_collect_evidence` 用 helper, last N within cutoff."""

    def setUp(self):
        # 清 vocab cache (避免 TestF2Helper.test_F2_4 sanity cap 残留 min=180)
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def _make_daemon(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        # mock _append_cold_start_record 避免 prod memory_pool mutation
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            return InnerThoughtDaemon(key_router=MagicMock())

    def test_F2_5_last_n_within_cutoff(self):
        """F2_5: 思考脑 evidence 'recent_thoughts' last N within cutoff."""
        daemon = self._make_daemon()
        # 注入 mock thoughts: 5 within 30min + 3 outside (40, 45, 60 min ago)
        with daemon._lock:
            daemon._thoughts = [
                _make_thought(f'within_{i}', age_s=60 * (i + 1))
                for i in range(5)  # ages: 1, 2, 3, 4, 5 min ago
            ] + [
                _make_thought(f'outside_{i}', age_s=2400 + 60 * i)
                for i in range(3)  # ages: 40, 41, 42 min ago
            ]
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        names = [t['thought'] for t in ev['recent_thoughts']]
        # 应只含 within (5 条), 不含 outside
        self.assertEqual(
            len(ev['recent_thoughts']), 5,
            f"F2_5 cutoff 30min 应只含 5 条 within thought, 实际: {names}"
        )
        for name in names:
            self.assertTrue(
                name.startswith('within_'),
                f"F2_5 thought '{name}' 应在 cutoff 内"
            )

    def test_F2_6_fallback_when_cutoff_empty(self):
        """F2_6: cutoff 内空 (老 thought 历史) → fallback 取 last n 不管时间."""
        daemon = self._make_daemon()
        # 所有 thought 都在 cutoff 外 (1h+ ago)
        with daemon._lock:
            daemon._thoughts = [
                _make_thought(f'old_{i}', age_s=3600 * (i + 2))
                for i in range(5)  # ages: 2h, 3h, 4h, 5h, 6h ago
            ]
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        # Fallback: 应取 last 5 (default n=15 但只 5 条历史)
        self.assertEqual(
            len(ev['recent_thoughts']), 5,
            "F2_6 cutoff 内空 → fallback 取 last n (5 条全) 不管时间"
        )

    def test_F2_5b_evidence_contains_lookback_min(self):
        """F2: evidence 含 recent_thoughts_lookback_min 字段供 prompt 文案用."""
        daemon = self._make_daemon()
        with daemon._lock:
            daemon._thoughts = [_make_thought('test', age_s=60)]
        ev = daemon._collect_evidence(sir_state='active', within_seconds=600)
        self.assertIn('recent_thoughts_lookback_min', ev,
                      "F2 evidence 应含 recent_thoughts_lookback_min (供 prompt)")
        self.assertEqual(ev['recent_thoughts_lookback_min'], 30,
                          "F2 默认 lookback_min=30")


class TestF2PromptDynamic(unittest.TestCase):
    """F2 `_build_prompt` 文案 dynamic."""

    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def test_F2_7_prompt_label_dynamic(self):
        """F2_7: prompt 文案含 dynamic 'last X within Ymin'."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(key_router=MagicMock())
        # mock recent_thoughts (3 条)
        mock_ev = {
            'sir_state': 'active',
            'idle_seconds': 60,
            'hour': 0,
            'recent_thoughts': [
                {
                    'id': f'th_{i}', 'thread_id': f'thr_{i}',
                    'continuity': 'new_topic', 'category': 'B',
                    'thought': f'test thought {i}', 'salience': 0.7,
                    'actionable': 'none', 'actionable_done': None,
                    'actionable_result': '', 'outcome': 'pending',
                    'age_s': 60 * (i + 1),
                }
                for i in range(3)
            ],
            'swm_events': [],
            'recent_thoughts_lookback_min': 45,  # 自定义验文案
        }
        # patch inner_voice 空, 避免干扰
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=MagicMock(recent=MagicMock(return_value=[]))
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            _system, user_prompt = daemon._build_prompt(
                sir_state='active', evidence=mock_ev,
            )
        # F2_7 核心: 文案 dynamic
        self.assertIn('last 3 within 45min', user_prompt,
                      "F2_7 prompt 应含 dynamic 'last 3 within 45min'")
        # 旧文案 "last 3" 单独不应直接现 (应被新 dynamic 替代)
        self.assertNotIn('last 3, for continuity', user_prompt,
                          "F2_7 旧静态文案 'last 3, for continuity' 不应残留")


if __name__ == '__main__':
    unittest.main(verbosity=2)
