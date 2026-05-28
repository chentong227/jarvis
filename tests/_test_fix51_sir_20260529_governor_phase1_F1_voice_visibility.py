# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 00:30 拍板 governor Phase 1 F1] 心声不过滤自家 thought.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F1 (Phase 1)
SOUL lineage: docs/JARVIS_SOUL_DRIVE.md → SOUL_UNIVERSALIZATION → SOUL_THOUGHT_LOOP_PLAN
              → 本 Phase 4 governor

修缮目标:
  缺口 ②: 旧版 `_non_thought = [e for e in _voice_recent if e.source != 'inner_thought']`
  让思考脑看心声时看不到自己已 think 的内容, 元意识闭环断, 重复 think 22 次同事却不自觉.

F1 真改 (jarvis_inner_thought_daemon.py:2780-2791):
  - 删 inner_thought filter, 直接用 _voice_recent
  - 文案: "cross-source signals" → "all-source signals (incl. own thoughts)"
  - 注释更新

测试覆盖 (3 testcase):
  - F1_1: 心声 inject 含 source='inner_thought' entry content (核心 — 不再被过滤)
  - F1_2: 新文案 "all-source signals (incl. own thoughts)" 出现
  - F1_3: 旧文案 "cross-source signals" 不再出现
  - F1_4: source='sensor' 类 entry 仍含 (backward compat — 不破坏旧行为)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_voice_entry(source, content, intent='noting', urgency=0.5,
                      wants_voice=False, age_s=60):
    """Helper: 构 VoiceEntry fake."""
    from jarvis_inner_voice_track import VoiceEntry
    return VoiceEntry(
        ts=time.time() - age_s,
        source=source,
        content=content,
        intent=intent,
        urgency=urgency,
        wants_voice=wants_voice,
    )


class TestF1VoiceVisibility(unittest.TestCase):
    """F1 — 心声给思考脑应是 '全意识流'(含自家 thought)."""

    def _make_daemon(self):
        """构最小 daemon (mock key_router)."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        return InnerThoughtDaemon(key_router=MagicMock())

    def _build_prompt_with_fake_voice(self, fake_entries):
        """patch get_inner_voice_track + is_enabled, 调 _build_prompt 拿 user_prompt."""
        fake_track = MagicMock()
        fake_track.recent.return_value = fake_entries

        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled',
            return_value=True,
        ):
            daemon = self._make_daemon()
            minimal_ev = {
                'sir_state': 'active',
                'idle_seconds': 60,
                'hour': 0,
                'recent_thoughts': [],
                'swm_events': [],
            }
            _system, user_prompt = daemon._build_prompt(
                sir_state='active',
                evidence=minimal_ev,
            )
        return user_prompt

    # ---------------- F1_1: 核心 — inner_thought entry 不再被过滤 ----------------

    def test_F1_1_own_thought_visible_in_voice_block(self):
        """F1 核心: source='inner_thought' entry 真现在 user_prompt 里."""
        own_thought_content = "I noticed Sir went to bed at 23:30"
        fake_entries = [
            _make_voice_entry(
                source='inner_thought',
                content=own_thought_content,
                intent='reflection',
                age_s=120,
            ),
        ]
        user_prompt = self._build_prompt_with_fake_voice(fake_entries)
        self.assertIn(
            own_thought_content, user_prompt,
            "F1 核心断言失败: source='inner_thought' entry 未现在 user_prompt — "
            "F1 改未生效 (filter 仍存在?)",
        )

    # ---------------- F1_2: 新文案 ----------------

    def test_F1_2_new_label_all_source_signals(self):
        """F1 新文案: 'all-source signals (incl. own thoughts)' 出现."""
        fake_entries = [
            _make_voice_entry(
                source='inner_thought',
                content="A reflection on Sir's behavior",
            ),
        ]
        user_prompt = self._build_prompt_with_fake_voice(fake_entries)
        self.assertIn(
            'all-source signals', user_prompt,
            "F1 新文案 'all-source signals' 未现 — F1 label 改未生效",
        )
        self.assertIn(
            '(incl. own thoughts)', user_prompt,
            "F1 新文案 '(incl. own thoughts)' 未现 — F1 label 改未生效",
        )

    # ---------------- F1_3: 旧文案不再出现 ----------------

    def test_F1_3_old_label_cross_source_signals_removed(self):
        """F1 旧文案 'cross-source signals' 不再出现 (避免旧版残留)."""
        fake_entries = [
            _make_voice_entry(source='sensor', content="Sir typed something"),
        ]
        user_prompt = self._build_prompt_with_fake_voice(fake_entries)
        self.assertNotIn(
            'cross-source signals', user_prompt,
            "F1 旧文案 'cross-source signals' 仍出现 — 旧 label 未清除",
        )

    # ---------------- F1_4: 不破坏旧行为 ----------------

    def test_F1_4_sensor_entry_still_visible(self):
        """F1 backward compat: source='sensor' 类 entry 仍现在 user_prompt."""
        sensor_content = "Sir typed nothing for 5min (idle 300s)"
        fake_entries = [
            _make_voice_entry(
                source='sensor',
                content=sensor_content,
                intent='observation',
                urgency=0.7,
            ),
        ]
        user_prompt = self._build_prompt_with_fake_voice(fake_entries)
        self.assertIn(
            sensor_content, user_prompt,
            "F1 backward compat 失败: source='sensor' entry 不应被破坏",
        )

    # ---------------- F1_5: 混合 source 全可见 (综合) ----------------

    def test_F1_5_mixed_sources_all_visible(self):
        """F1 综合: inner_thought + sensor + care_trigger 三类混合, 全可见."""
        entries = [
            _make_voice_entry(
                source='inner_thought',
                content="OWN_THOUGHT_MARKER_xyz123",
                age_s=300,
            ),
            _make_voice_entry(
                source='sensor',
                content="SENSOR_MARKER_xyz123",
                age_s=180,
            ),
            _make_voice_entry(
                source='care_trigger',
                content="CARE_MARKER_xyz123",
                age_s=60,
            ),
        ]
        user_prompt = self._build_prompt_with_fake_voice(entries)
        for marker in ('OWN_THOUGHT_MARKER_xyz123',
                        'SENSOR_MARKER_xyz123',
                        'CARE_MARKER_xyz123'):
            self.assertIn(
                marker, user_prompt,
                f"F1 综合失败: marker '{marker}' 未现, 心声 inject 不全",
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
