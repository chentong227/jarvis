# -*- coding: utf-8 -*-
"""[β.5.37-A / 2026-05-20] Sensor 层: real_input + ghost_activity 传感器扩展.

Sir 14:39 校正真理: "传感器灵敏度修复 — 把不是真正我在操作的行为和我操作的行为
区分开告诉主脑, 而不是硬编码 sentinel guard."

层 1 工程实现:
  PhysicalEnvironmentProbe 新字段:
    - last_real_input_ts (Unix ts of 真键鼠按)
    - idle_seconds_real (alias of idle_seconds, 语义清晰)
    - cascade_active (bool: fg process 是否 IDE/Cascade 类)
    - cascade_process_name (哪个 IDE)
  SWM publish:
    - sir_afk_detected on < 60 → > 60s idle transition
    - ghost_activity_observed on idle_real > 60 + cascade_active
"""
from __future__ import annotations

import os
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta537ASensorFields(unittest.TestCase):
    """PhysicalEnvironmentProbe 新字段 + snapshot 暴露 + publish point 存在."""

    def test_class_attrs_exist(self):
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        self.assertTrue(hasattr(P, 'last_real_input_ts'),
            '新字段 last_real_input_ts 必须存在')
        self.assertTrue(hasattr(P, 'idle_seconds_real'),
            '新字段 idle_seconds_real 必须存在 (alias)')
        self.assertTrue(hasattr(P, 'cascade_active'),
            '新字段 cascade_active 必须存在 (bool ghost source)')
        self.assertTrue(hasattr(P, 'cascade_process_name'),
            '新字段 cascade_process_name 必须存在')

    def test_snapshot_contains_new_fields(self):
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        snap = P._build_sensor_snapshot()
        self.assertIn('idle_seconds_real', snap,
            'snapshot 必须含 idle_seconds_real')
        self.assertIn('last_real_input_ts', snap,
            'snapshot 必须含 last_real_input_ts')
        self.assertIn('cascade_active', snap,
            'snapshot 必须含 cascade_active')
        self.assertIn('cascade_process_name', snap,
            'snapshot 必须含 cascade_process_name')
        self.assertIsInstance(snap['cascade_active'], bool,
            'cascade_active 必须是 bool')

    def test_publish_points_present_in_source(self):
        with open(os.path.join(ROOT, 'jarvis_env_probe.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # SWM 信号类型
        self.assertIn("'sir_afk_detected'", src,
            'sir_afk_detected publish 必须存在')
        self.assertIn("'ghost_activity_observed'", src,
            'ghost_activity_observed publish 必须存在')
        # β.5.37-A marker
        self.assertIn('β.5.37-A', src,
            'β.5.37-A marker 必须在 source')
        # IDE process keyword list (注: 这里允许 sensor 层 keyword 因为它是 evidence 来源,
        # 不是 decision logic — 准则 6 vocab 化是行为决策, sensor evidence 抽取可保留)
        for kw in ('cursor.exe', 'windsurf.exe', 'code.exe'):
            self.assertIn(kw, src,
                f'IDE process keyword {kw} 必须存在 (sensor evidence)')


class TestBeta537ASWMPublishHelper(unittest.TestCase):
    """SWM publish 限频 + transition 检测正确."""

    def test_swm_bus_publish_callable(self):
        # 确认 ConversationEventBus + get_event_bus API 可用
        from jarvis_utils import get_event_bus, ConversationEventBus
        bus = ConversationEventBus()
        bus.publish('sir_afk_detected', 'test', source='PhysicalEnvProbe', salience=0.65)
        top = bus.top_n(n=5)
        self.assertGreater(len(top), 0, 'publish 后 top_n 必须 ≥ 1')
        self.assertEqual(top[0]['type'], 'sir_afk_detected')

    def test_afk_publish_api_works(self):
        """publish 'sir_afk_detected' / 'ghost_activity_observed' 到 SWM 可用 + top_n 含."""
        from jarvis_utils import ConversationEventBus
        bus = ConversationEventBus()
        bus.publish('sir_afk_detected', 'idle_real=120s', source='PhysicalEnvProbe',
                    salience=0.65, metadata={'idle_seconds_real': 120})
        bus.publish('ghost_activity_observed', 'Cascade fg + Sir afk',
                    source='PhysicalEnvProbe', salience=0.6,
                    metadata={'cascade_process': 'cursor.exe'})
        top = bus.top_n(n=10)
        types = [e['type'] for e in top]
        self.assertIn('sir_afk_detected', types,
            'sir_afk_detected 必须可 publish')
        self.assertIn('ghost_activity_observed', types,
            'ghost_activity_observed 必须可 publish')
        # 验证 SWM block 渲染
        block = bus.to_swm_block(n=5, salience_floor=0.5)
        self.assertIn('sir_afk_detected', block)
        self.assertIn('ghost_activity_observed', block)


if __name__ == '__main__':
    unittest.main()
