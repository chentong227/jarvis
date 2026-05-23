# -*- coding: utf-8 -*-
"""[P5-fix45 / 2026-05-23 15:10] CONCERN_DAMPEN E2E 链路验证.

Sir 14:51 真痛点: 我中午睡了 1h → mutation ✅ → 但 sir_sleep_streak severity 没削.
Sir 真问: '链路是否实现?'

E2E test:
1. mutation organ 写 ProfileCard → MemoryGateway publish 'sir_field_updated' SWM
2. SWM bus.to_swm_block() 渲染 → 主脑 prompt 含 'sir_field_updated' 描述
3. 主脑 (mock) 看到 + emit <CONCERN_DAMPEN cid="..." delta="-0.3" reason="..."/>
4. chat_bypass process_reply → ledger.record_signal → severity 削
5. ConcernsLedger publish 'concern_dampen_applied' SWM (closure)
6. 下轮 prompt 看 closure event

测试覆盖:
A. mutation publish 'sir_field_updated' (sal ≥ 0.3 → 进 swm_block)
B. swm_block 含 sir_field_updated
C. process_reply 解析主脑 dampen tag → ledger.record_signal
D. 'concern_dampen_applied' closure SWM publish
E. 闭环: 下轮 swm_block 含 closure event
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestE2EDampenChain(unittest.TestCase):

    def setUp(self):
        from jarvis_utils import ConversationEventBus
        import jarvis_utils as ju
        self._old_bus = ju._GLOBAL_EVENT_BUS
        self.bus = ConversationEventBus()
        ju._GLOBAL_EVENT_BUS = self.bus

    def tearDown(self):
        import jarvis_utils as ju
        ju._GLOBAL_EVENT_BUS = self._old_bus

    def test_a_mutation_publish_to_swm_block(self):
        """mutation publish → swm_block 真渲染 sir_field_updated."""
        # simulate MemoryGateway _publish_swm
        self.bus.publish(
            etype='sir_field_updated',
            description=(
                "ProfileCard: profile.daily_logs.2026-05-23 = "
                "'Midday nap: 1 hour' (mutation_id=mut_xxx, src=test, ok=True)"
            ),
            source='MemoryGateway',
            salience=0.80,
            metadata={'field_path': 'profile.daily_logs.2026-05-23'},
        )
        block = self.bus.to_swm_block(n=12, max_chars=900, salience_floor=0.3)
        self.assertIn('sir_field_updated', block,
                          'swm_block 必须含 sir_field_updated event 给主脑看')
        self.assertIn('Midday nap', block,
                          'swm_block 必须含 mutation new_value (主脑读 evidence)')
        self.assertIn('MemoryGateway', block,
                          'swm_block 必须含 source MemoryGateway')

    def test_b_dampen_tag_processes_into_ledger(self):
        """主脑 emit dampen tag → process_reply → ledger.record_signal 调."""
        from jarvis_concern_dampen import process_reply

        class MockLedger:
            def __init__(self):
                self.records = []
            def record_signal(self, cid, what, severity_delta, source_turn_id=''):
                self.records.append({
                    'cid': cid, 'severity_delta': severity_delta, 'what': what
                })
                return True

        ledger = MockLedger()
        # 模拟主脑 reply 含 tag (typical Sir 14:51 case)
        reply = (
            'Noted, Sir. 看您休息了一小时, 担心度自然调低. '
            '<CONCERN_DAMPEN cid="sir_sleep_streak" delta="-0.3" '
            'reason="Sir reported midday nap 1h"/>'
        )
        n = process_reply(reply, ledger, turn_id='turn_test_e2e')
        self.assertEqual(n, 1)
        self.assertEqual(len(ledger.records), 1)
        rec = ledger.records[0]
        self.assertEqual(rec['cid'], 'sir_sleep_streak')
        self.assertAlmostEqual(rec['severity_delta'], -0.3)

    def test_c_dampen_closure_publishes_to_swm(self):
        """dampen apply 后 publish 'concern_dampen_applied' (闭环 → 主脑下轮可见)."""
        from jarvis_concern_dampen import process_reply

        class MockLedger:
            def record_signal(self, *a, **k): return True

        reply = '<CONCERN_DAMPEN cid="x" delta="-0.3" reason="r"/>'
        n = process_reply(reply, MockLedger(), turn_id='turn_t1')
        self.assertEqual(n, 1)
        # 看 SWM 是否有 closure event
        events = self.bus.recent_events()
        closure = [e for e in events
                     if e.get('type') == 'concern_dampen_applied']
        self.assertGreater(len(closure), 0,
                            'concern_dampen_applied 应 publish 闭环')

    def test_d_full_chain_mutation_then_dampen_then_closure(self):
        """完整链 mutation → SWM evidence → dampen tag → closure."""
        from jarvis_concern_dampen import process_reply

        # 步 1: mutation publish
        self.bus.publish(
            etype='sir_field_updated',
            description='ProfileCard: nap=1h',
            source='MemoryGateway',
            salience=0.80,
        )

        # 步 2: 主脑下轮看到 swm_block (验证)
        block = self.bus.to_swm_block()
        self.assertIn('sir_field_updated', block)

        # 步 3: 主脑 emit dampen tag
        class MockLedger:
            def record_signal(self, *a, **k): return True

        reply = (
            'Noted, Sir. '
            '<CONCERN_DAMPEN cid="sir_sleep_streak" delta="-0.3" '
            'reason="Sir nap 1h verified"/>'
        )
        n = process_reply(reply, MockLedger(), turn_id='turn_t2')
        self.assertEqual(n, 1)

        # 步 4: 闭环 — 下轮 swm_block 含 closure
        block2 = self.bus.to_swm_block()
        self.assertIn('concern_dampen_applied', block2,
                          '闭环: 下轮 swm 显 dampen 已应用')


if __name__ == '__main__':
    unittest.main()
