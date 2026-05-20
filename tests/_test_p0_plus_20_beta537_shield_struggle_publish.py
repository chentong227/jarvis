# -*- coding: utf-8 -*-
"""[β.5.37-C / 2026-05-20] ProactiveShield ghost dampen + struggle publish 改造.

层 2 publish-only:
- ProactiveShield._compute_frustration_score 加 ghost_activity_dampen 维度
  (idle_seconds_real + cascade_active → score *= 0.10, sensor evidence based)
- ProactiveShield._scan 触 alert 时 publish 'shield_observation' 到 SWM
- Conductor SirStruggleVocab path publish 'sir_struggle_observed' 到 SWM

Sir 14:39 校正核心: 不再 sentinel hard skip / hard match,
全部 sensor evidence + 主脑看 SWM evidence 自决.
"""
from __future__ import annotations

import os
import unittest
from collections import deque
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta537CShieldGhostDampen(unittest.TestCase):
    """_compute_frustration_score 看 sensor (idle_real + cascade_active) 评分自然衰减."""

    def _make_shield(self):
        from jarvis_enhanced import ProactiveShield
        shield = ProactiveShield.__new__(ProactiveShield)
        shield.jarvis = None
        return shield

    def test_no_ghost_high_score(self):
        """Sir 真在场 (idle 0 / cascade 否) → 评分不衰减."""
        shield = self._make_shield()
        snap = {
            'idle_seconds_real': 5,
            'cascade_active': False,
            'backspace_ratio': 0.20,
            'shortcut_undo_5min': 5,
        }
        score, breakdown = shield._compute_frustration_score(
            switches=18, error_duration_min=8, snapshot=snap
        )
        self.assertNotIn('ghost_activity_dampen', breakdown,
            'Sir 在场 (cascade=False) 不该有 ghost_activity_dampen')
        self.assertGreater(score, 0.5,
            'multi-signal 应得高分 (无 ghost 衰减)')

    def test_ghost_dampens_score(self):
        """Sir 离场 + cascade active → ghost dampen score *= 0.10."""
        shield = self._make_shield()
        snap = {
            'idle_seconds_real': 120,
            'cascade_active': True,
            'cascade_process_name': 'cursor.exe',
            'backspace_ratio': 0.20,
            'shortcut_undo_5min': 5,
        }
        score, breakdown = shield._compute_frustration_score(
            switches=18, error_duration_min=8, snapshot=snap
        )
        self.assertIn('ghost_activity_dampen', breakdown,
            'cascade ghost 必须触发 dampen 维度')
        self.assertIn('_ghost_evidence', breakdown,
            'breakdown 必须含 _ghost_evidence (sensor evidence transparent)')
        self.assertEqual(breakdown['ghost_activity_dampen'], 0.10)
        self.assertLess(score, 0.15,
            'ghost dampen 后 score 应大幅衰减 (* 0.1)')

    def test_no_cascade_just_idle_no_dampen(self):
        """Sir 离场但无 cascade ghost source → 不衰减 (可能 Sir 真发呆)."""
        shield = self._make_shield()
        snap = {
            'idle_seconds_real': 120,
            'cascade_active': False,
            'backspace_ratio': 0.20,
        }
        score, breakdown = shield._compute_frustration_score(
            switches=18, error_duration_min=8, snapshot=snap
        )
        self.assertNotIn('ghost_activity_dampen', breakdown,
            'cascade=False 时不该 dampen, 即使 idle 高 (Sir 可能真在思考)')


class TestBeta537CSWMPublish(unittest.TestCase):
    """ProactiveShield / SirStruggleVocab publish 到 SWM."""

    def test_shield_observation_publish_in_source(self):
        with open(os.path.join(ROOT, 'jarvis_enhanced.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'shield_observation'", src,
            'shield_observation publish 必须存在 jarvis_enhanced.py')
        self.assertIn('β.5.37-C', src,
            'β.5.37-C marker 必须在 jarvis_enhanced.py')

    def test_sir_struggle_observed_publish_in_source(self):
        with open(os.path.join(ROOT, 'jarvis_conductor.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'sir_struggle_observed'", src,
            'sir_struggle_observed publish 必须存在 jarvis_conductor.py')
        self.assertIn('β.5.37-C', src,
            'β.5.37-C marker 必须在 jarvis_conductor.py')

    def test_swm_signals_publish_to_bus(self):
        """SWM publish + top_n 真渲染."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish('shield_observation', 'frustration high', source='ProactiveShield',
                    salience=0.8, metadata={'score': 0.75})
        bus.publish('sir_struggle_observed', 'phrase=stuck_zh', source='SirStruggleVocab',
                    salience=0.85, metadata={'phrase_id': 'stuck_zh'})
        top = bus.top_n(n=5)
        types = [e['type'] for e in top]
        self.assertIn('shield_observation', types)
        self.assertIn('sir_struggle_observed', types)
        block = bus.to_swm_block(n=5)
        self.assertIn('shield_observation', block)
        self.assertIn('sir_struggle_observed', block)


if __name__ == '__main__':
    unittest.main()
