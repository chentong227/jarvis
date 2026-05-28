# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 00:30 拍板 governor Phase 1 F6 改 2] B 类反思 append 心声 + dedup.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F6 改 2 (Phase 1)
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → Phase 4 governor

修缮目标 (缺口 ③):
  旧路: 思考脑 B 类反思 → publish SWM 'self_reflection_noted'.
  问题: 该 etype 0 consumer (Sir 12:30 audit), 主脑实际看不到 B 类反思.
  治本: B 类反思 → append 心声 source='self_reflection' intent='reflection',
       主脑下轮 SOUL inject 心声 (`_build_layer_1c_inner_voice_block`)
       → 自然看到 B 类反思.
  防淹没: 30min 内同 topic (jaccard >= 0.6) 已 append → 跳过, 防 1h 22 次重复.

F6 改 2 真改:
  1. memory_pool/inner_thought_pacing_vocab.json 加 `self_reflection_dedup` block
  2. jarvis_inner_thought_daemon.py:
     - _PACING_DEFAULT_CONFIG 加 'self_reflection_dedup' fallback
     - 新 helper `_get_self_reflection_dedup_config() -> (enabled, win_min, jacc_thr)`
     - 新 helper `_self_reflection_jaccard(a, b) -> float` (inline)
     - `_maybe_publish_self_correction` 末尾加 append 心声 + dedup

测试覆盖 (8 testcase):
  - F6c2_1: helper 默认返 (True, 30, 0.6)
  - F6c2_2: vocab disable → (False, ...)
  - F6c2_3: vocab sanity cap (window>180 → 180, jaccard>1.0 → 1.0)
  - F6c2_4: jaccard helper 计算正确 (相同/部分/无 overlap)
  - F6c2_5: B 类 + high sal → append 心声 source='self_reflection'
  - F6c2_6: A 类 → skip (非 B 类不 append)
  - F6c2_7: 30min 内同 topic (jaccard >= 0.6) → skip dedup
  - F6c2_8: 不同 topic (jaccard < 0.6) → append 两次
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


def _make_thought(thought_text, category='B', salience=0.8):
    """构 B 类反思 thought."""
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f'th_{int(time.time() * 1000)}_{abs(hash(thought_text)) % 1000}',
        ts=time.time(),
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
        category=category,
        thought=thought_text,
        salience=salience,
        actionable='none',
        evidence_link='none',
    )


class TestF6c2Helper(unittest.TestCase):
    """F6 改 2 helper."""

    def setUp(self):
        from jarvis_inner_thought_daemon import _PACING_VOCAB_CACHE
        _PACING_VOCAB_CACHE['data'] = None
        _PACING_VOCAB_CACHE['mtime'] = 0.0
        _PACING_VOCAB_CACHE['checked_at'] = 0.0

    def test_F6c2_1_default(self):
        """F6c2_1: 默认 vocab → (True, 30, 0.6)."""
        from jarvis_inner_thought_daemon import (
            _get_self_reflection_dedup_config,
        )
        enabled, win, jacc = _get_self_reflection_dedup_config()
        self.assertTrue(enabled)
        self.assertEqual(win, 30)
        self.assertAlmostEqual(jacc, 0.6, places=4)

    def test_F6c2_2_vocab_disable(self):
        """F6c2_2: vocab enabled=False → (False, ...)."""
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'self_reflection_dedup': {
                    'enabled': False,
                    'window_min': 30,
                    'jaccard_threshold': 0.6,
                }
            }, f)
            tmp_path = f.name
        try:
            with patch.object(m, '_PACING_VOCAB_PATH', tmp_path):
                m._PACING_VOCAB_CACHE['data'] = None
                m._PACING_VOCAB_CACHE['mtime'] = 0.0
                m._PACING_VOCAB_CACHE['checked_at'] = 0.0
                enabled, _w, _j = m._get_self_reflection_dedup_config()
            self.assertFalse(enabled, "F6c2_2 vocab enabled=False 应生效")
        finally:
            os.unlink(tmp_path)

    def test_F6c2_3_sanity_cap(self):
        """F6c2_3: sanity cap (window>180, jaccard>1.0)."""
        import jarvis_inner_thought_daemon as m
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump({
                'self_reflection_dedup': {
                    'enabled': True,
                    'window_min': 9999,
                    'jaccard_threshold': 99.0,
                }
            }, f)
            tmp_path = f.name
        try:
            with patch.object(m, '_PACING_VOCAB_PATH', tmp_path):
                m._PACING_VOCAB_CACHE['data'] = None
                m._PACING_VOCAB_CACHE['mtime'] = 0.0
                m._PACING_VOCAB_CACHE['checked_at'] = 0.0
                _e, win, jacc = m._get_self_reflection_dedup_config()
            self.assertEqual(win, 180)
            self.assertAlmostEqual(jacc, 1.0, places=4)
        finally:
            os.unlink(tmp_path)

    def test_F6c2_4_jaccard_helper(self):
        """F6c2_4: jaccard 计算 (相同/部分/无 overlap)."""
        from jarvis_inner_thought_daemon import _self_reflection_jaccard
        # 100% overlap
        self.assertAlmostEqual(
            _self_reflection_jaccard('Sir is sleeping now',
                                     'Sir is sleeping now'),
            1.0, places=4
        )
        # 0% overlap
        self.assertAlmostEqual(
            _self_reflection_jaccard('alpha beta gamma',
                                     'xyz pqr klm'),
            0.0, places=4
        )
        # 部分 overlap (jaccard 高)
        jacc = _self_reflection_jaccard(
            'Sir is stale sleep observation',
            'Sir is stale sleep notice',
        )
        # 4 共 / 6 union = 0.666...
        self.assertGreater(jacc, 0.5)
        self.assertLess(jacc, 0.7)
        # 空字符串
        self.assertEqual(_self_reflection_jaccard('', 'abc'), 0.0)


class TestF6c2AppendVoice(unittest.TestCase):
    """F6 改 2 _maybe_publish_self_correction 末尾 append 心声."""

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

    def test_F6c2_5_b_thought_appends_voice(self):
        """F6c2_5: B 类 + high sal → append 心声 source='self_reflection'."""
        daemon = self._make_daemon()
        fake_track = MagicMock()
        fake_track.recent.return_value = []  # 窗内无 prior
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            thought = _make_thought(
                'I noticed Sir went to bed late', category='B',
                salience=0.85,
            )
            daemon._maybe_publish_self_correction(thought)
        # 应调 _track.append 1 次
        self.assertEqual(fake_track.append.call_count, 1,
                          "F6c2_5 B 类 + high sal 应 append 1 次心声")
        kw = fake_track.append.call_args.kwargs
        self.assertEqual(kw['source'], 'self_reflection')
        self.assertEqual(kw['intent'], 'reflection')
        self.assertIn('I noticed Sir went to bed late', kw['content'])
        # sal=0.85 → wants_voice=True (★ spotlight)
        self.assertTrue(kw['wants_voice'],
                        "F6c2_5 sal=0.85 应标 wants_voice=True spotlight")

    def test_F6c2_6_a_thought_skips_voice(self):
        """F6c2_6: A 类 → skip (非 B 类不 append)."""
        daemon = self._make_daemon()
        fake_track = MagicMock()
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            thought = _make_thought('observation', category='A',
                                       salience=0.9)
            daemon._maybe_publish_self_correction(thought)
        self.assertEqual(fake_track.append.call_count, 0,
                          "F6c2_6 A 类 thought 不应 append 心声")

    def test_F6c2_7_dedup_same_topic(self):
        """F6c2_7: 30min 内同 topic (jaccard >= 0.6) → skip dedup."""
        daemon = self._make_daemon()
        # Fake recent: 已有同 topic self_reflection entry
        from jarvis_inner_voice_track import VoiceEntry
        existing_entry = VoiceEntry(
            ts=time.time() - 300,  # 5min ago (within 30min window)
            source='self_reflection',
            content='(self-reflected) Sir stale sleep observation',
            intent='reflection',
            urgency=0.5,
            wants_voice=False,
        )
        fake_track = MagicMock()
        fake_track.recent.return_value = [existing_entry]
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            # 新 thought 跟 existing 高 jaccard
            thought = _make_thought(
                'Sir stale sleep observation continuing',
                category='B', salience=0.8,
            )
            daemon._maybe_publish_self_correction(thought)
        self.assertEqual(
            fake_track.append.call_count, 0,
            "F6c2_7 同 topic (jaccard >= 0.6) 应 skip dedup, 不 append"
        )

    def test_F6c2_8_no_dedup_different_topic(self):
        """F6c2_8: 不同 topic (jaccard < 0.6) → append."""
        daemon = self._make_daemon()
        from jarvis_inner_voice_track import VoiceEntry
        existing_entry = VoiceEntry(
            ts=time.time() - 300,
            source='self_reflection',
            content='(self-reflected) Sir hydration check',
            intent='reflection',
            urgency=0.5,
            wants_voice=False,
        )
        fake_track = MagicMock()
        fake_track.recent.return_value = [existing_entry]
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True
        ):
            # 新 thought 跟 existing 低 jaccard (不同主题)
            thought = _make_thought(
                'Premiere render took too long today',
                category='B', salience=0.8,
            )
            daemon._maybe_publish_self_correction(thought)
        self.assertEqual(
            fake_track.append.call_count, 1,
            "F6c2_8 不同 topic 应 append (新主题)"
        )

    def test_F6c2_9_disabled_dedup_always_appends(self):
        """F6c2_9: enabled=False → 不 dedup (但本身也跳 append, 实际 enabled=False = 整体关 append)."""
        daemon = self._make_daemon()
        import jarvis_inner_thought_daemon as m
        # Patch helper return enabled=False
        with patch.object(m, '_get_self_reflection_dedup_config',
                          return_value=(False, 30, 0.6)):
            fake_track = MagicMock()
            with patch(
                'jarvis_inner_voice_track.get_inner_voice_track',
                return_value=fake_track,
            ), patch(
                'jarvis_inner_voice_track.is_enabled', return_value=True
            ):
                thought = _make_thought('test', category='B', salience=0.8)
                daemon._maybe_publish_self_correction(thought)
        # enabled=False → 不 append (整体关 dedup pipeline)
        self.assertEqual(
            fake_track.append.call_count, 0,
            "F6c2_9 enabled=False 应整体跳 (含 append)"
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
