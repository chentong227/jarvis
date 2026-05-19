# -*- coding: utf-8 -*-
"""
[P0+20-β.5.0-A / 2026-05-19] Shared World Model 数据强耦合 (准则 6 升级)

Sir 拍板: "数据强耦合 / 行为弱耦合 / 决策集中主脑" 三维, 这是新准则 6 落地.

β.5.0-A 改造 (本 commit):
  1. ConversationEventBus = SharedWorldModel:
     - 加 publish(salience) 参数 + DEFAULT_SALIENCE map
     - 加 top_n(n=12, salience_floor) API (按 salience × recency 排)
     - 加 to_swm_block() prompt 渲染
     - 加 register_global / get_event_bus 让远端模块 publish 不需 self.jarvis
  2. 5 个新 publish point (准则 6 数据强耦合):
     - PhysicalEnvProbe: category 变化 publish 'sensor_change'
     - NudgeGate.can_speak: block 时 publish 'gate_advice'
     - ProactiveCare._tick: top concern publish 'concern_active'
     - ReturnSentinel._on_return: AFK 回归 publish 'afk_return'
     - CentralNerve._append_stm: 末尾对话 publish 'utterance_appended'
  3. _assemble_prompt 注入 [SHARED WORLD MODEL] block (主脑 prompt 看 top_n(12))

测试覆盖:
  - SWM API: publish(salience) / top_n / to_swm_block 单元测
  - register_global / get_event_bus 单例验
  - 5 处 source publish 信号源源码存在性验
  - _assemble_prompt 注入 swm_block 验
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# A1: SWM core API (publish salience / top_n / to_swm_block / register_global)
# ==========================================================================

class TestP0Plus20Beta50SWMCoreAPI(unittest.TestCase):
    """ConversationEventBus → SharedWorldModel API 扩展."""

    def setUp(self):
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus()

    def test_publish_accepts_salience_param(self):
        ok = self.bus.publish('sensor_change', 'window changed', salience=0.7)
        self.assertTrue(ok)
        snap = self.bus.snapshot()
        self.assertEqual(len(snap), 1)
        self.assertAlmostEqual(snap[0]['salience'], 0.7)

    def test_publish_default_salience_from_map(self):
        """publish 不传 salience → 从 DEFAULT_SALIENCE[etype] 取."""
        self.bus.publish('concern_active', 'top=sleep urgency=0.8')
        snap = self.bus.snapshot()
        # DEFAULT_SALIENCE['concern_active'] = 0.65
        self.assertAlmostEqual(snap[0]['salience'], 0.65)

    def test_publish_unknown_etype_default_05(self):
        self.bus.publish('nonexistent_etype', 'foo')
        snap = self.bus.snapshot()
        self.assertAlmostEqual(snap[0]['salience'], 0.5)

    def test_salience_clamped_0_1(self):
        self.bus.publish('test', 'a', salience=2.5)
        self.bus.publish('test2', 'b', salience=-1.0)
        # 等 8s dedupe pass + 强制不同 etype
        snap = self.bus.snapshot()
        clamped = [e['salience'] for e in snap]
        self.assertIn(1.0, clamped)
        self.assertIn(0.0, clamped)

    def test_top_n_sorts_by_salience_recency(self):
        """top_n 按 (salience × 0.7 + recency × 0.3) 排."""
        self.bus.publish('low_test', 'low_sal', salience=0.2)
        self.bus.publish('high_test', 'high_sal', salience=0.9)
        self.bus.publish('mid_test', 'mid_sal', salience=0.5)
        top = self.bus.top_n(n=3)
        self.assertEqual(len(top), 3)
        # 时近度都接近 1, 主导是 salience
        self.assertEqual(top[0]['type'], 'high_test')
        self.assertEqual(top[2]['type'], 'low_test')

    def test_top_n_filters_by_salience_floor(self):
        self.bus.publish('a', 'low', salience=0.1)
        self.bus.publish('b', 'mid', salience=0.5)
        self.bus.publish('c', 'high', salience=0.9)
        top = self.bus.top_n(n=10, salience_floor=0.4)
        types = [e['type'] for e in top]
        self.assertNotIn('a', types)
        self.assertIn('b', types)
        self.assertIn('c', types)

    def test_top_n_includes_score_and_age(self):
        self.bus.publish('test', 'x', salience=0.7)
        top = self.bus.top_n(n=1)
        self.assertEqual(len(top), 1)
        self.assertIn('score', top[0])
        self.assertIn('_age_s', top[0])

    def test_to_swm_block_renders_with_metadata(self):
        self.bus.publish('concern_active', 'top=sleep urgency=0.8',
                         source='ProactiveCare', salience=0.85)
        block = self.bus.to_swm_block(n=5)
        self.assertIn('SHARED WORLD MODEL', block)
        self.assertIn('concern_active', block)
        self.assertIn('ProactiveCare', block)
        self.assertIn('sal=0.85', block)
        self.assertIn('top=sleep', block)

    def test_to_swm_block_empty_returns_empty(self):
        block = self.bus.to_swm_block()
        self.assertEqual(block, '')

    def test_to_swm_block_respects_max_chars(self):
        for i in range(20):
            self.bus.publish(f'event_{i}', f'event {i} ' * 30, salience=0.5)
        block = self.bus.to_swm_block(n=20, max_chars=300)
        self.assertLessEqual(len(block), 305)


class TestP0Plus20Beta50RegisterGlobal(unittest.TestCase):
    """register_global / get_event_bus 单例机制."""

    def test_register_global_exposes_via_get_event_bus(self):
        from jarvis_utils import ConversationEventBus, get_event_bus
        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)
        retrieved = get_event_bus()
        self.assertIs(retrieved, bus)

    def test_get_event_bus_returns_none_if_not_registered(self):
        from jarvis_utils import ConversationEventBus, get_event_bus
        # 重置全局 (其他测可能已注册)
        ConversationEventBus.register_global(None)
        self.assertIsNone(get_event_bus())


# ==========================================================================
# A2: 5 处 publish point 源码验
# ==========================================================================

class TestP0Plus20Beta50PublishPoints(unittest.TestCase):
    """5 个 source 已加 publish."""

    def test_physical_env_probe_publishes_sensor_change(self):
        path = os.path.join(ROOT, 'jarvis_env_probe.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("etype='sensor_change'", src,
            'PhysicalEnvProbe 必须 publish sensor_change (β.5.0-A)')
        self.assertIn("source='PhysicalEnvProbe'", src,
            'PhysicalEnvProbe publish 必须标 source')

    def test_nudge_gate_publishes_block_decision(self):
        path = os.path.join(ROOT, 'jarvis_sentinels.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 NudgeGate.can_speak
        idx = src.find('def can_speak(self, center_name')
        self.assertGreater(idx, 0)
        # 后 1500 字内必须 publish gate_advice
        block = src[idx:idx+1500]
        self.assertIn("etype='gate_advice'", block,
            "NudgeGate.can_speak 必须 publish gate_advice (β.5.0-A)")

    def test_proactive_care_publishes_top_concern(self):
        path = os.path.join(ROOT, 'jarvis_proactive_care.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("etype='concern_active'", src,
            'ProactiveCare 必须 publish concern_active (β.5.0-A)')

    def test_return_sentinel_publishes_afk_return(self):
        path = os.path.join(ROOT, 'jarvis_return_sentinel.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("etype='afk_return'", src,
            'ReturnSentinel _on_return 必须 publish afk_return (β.5.0-A)')

    def test_central_nerve_stm_publishes_utterance(self):
        path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("etype='utterance_appended'", src,
            'CentralNerve._append_stm 必须 publish utterance_appended (β.5.0-A)')


# ==========================================================================
# A3: _assemble_prompt 注入 SWM block
# ==========================================================================

class TestP0Plus20Beta50PromptInjection(unittest.TestCase):
    """_assemble_prompt 装配 [SHARED WORLD MODEL] block."""

    def test_assemble_prompt_constructs_swm_block(self):
        path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('to_swm_block(n=12', src,
            '_assemble_prompt 必须调 bus.to_swm_block(n=12, ...)')
        self.assertIn('swm_block = ""', src,
            '_assemble_prompt 必须初始化 swm_block')

    def test_swm_block_injected_into_prompt_template(self):
        path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('{swm_block}', src,
            'prompt 模板必须含 {swm_block} 插值')

    def test_swm_block_appears_before_event_bus_block(self):
        path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        swm_idx = src.rfind('{swm_block}')
        ebus_idx = src.rfind('{event_bus_block}')
        self.assertGreater(swm_idx, 0)
        self.assertGreater(ebus_idx, 0)
        self.assertLess(swm_idx, ebus_idx,
            'swm_block 应在 event_bus_block 之前 (高 salience signal 优先看)')


# ==========================================================================
# A4: DEFAULT_SALIENCE 完整性
# ==========================================================================

class TestP0Plus20Beta50DefaultSalience(unittest.TestCase):
    """DEFAULT_SALIENCE 字典含所有新 etype."""

    def test_all_new_etypes_have_salience(self):
        from jarvis_utils import ConversationEventBus
        new_etypes = [
            'sensor_change', 'gate_advice', 'concern_active',
            'afk_return', 'self_critique', 'utterance_appended',
        ]
        for et in new_etypes:
            self.assertIn(et, ConversationEventBus.DEFAULT_SALIENCE,
                f'DEFAULT_SALIENCE 必须有 {et} (β.5.0-A)')
            sal = ConversationEventBus.DEFAULT_SALIENCE[et]
            self.assertGreaterEqual(sal, 0.0)
            self.assertLessEqual(sal, 1.0)

    def test_critical_etypes_have_high_salience(self):
        """commitment_overdue / hallucination 必须 ≥ 0.9 salience."""
        from jarvis_utils import ConversationEventBus
        self.assertGreaterEqual(
            ConversationEventBus.DEFAULT_SALIENCE['commitment_overdue'], 0.9)
        self.assertGreaterEqual(
            ConversationEventBus.DEFAULT_SALIENCE['hallucination_detected'], 0.9)


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.5.0-A SWM tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
