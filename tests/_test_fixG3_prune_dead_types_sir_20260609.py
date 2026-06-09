# -*- coding: utf-8 -*-
"""[fixG3-prune-dead-event-types / Sir 2026-06-09] 清掉消费端 4 死名.

死名 (memory_corrected/memory_update/profile_field_updated/concern_modified) 零 producer
(全仓 grep 实证), 功能被活 5 名覆盖 (sir_field_updated/sir_profile_overwritten/
concern_field_updated/tool_called/promise_fulfilled). 移除逐字节 behavior-preserving.

T1 活 5 名无回归: 各 publish 活名 event → 对应 past_action 声称 verified.
T2 死名移除逐字节同: publish 死名 event → 不被识别为 evidence (清理前后同, 因死名本不该产出).
T3 域映射清理后活名域不变: fixD 域配对对活名仍对.
T4 空窗口: 无 event → unverified.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_bus():
    from jarvis_utils import ConversationEventBus
    bus = ConversationEventBus(restore=False)
    ConversationEventBus.register_global(bus)
    return bus


class TestFixG3PruneDeadTypes(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()

    # ---------- T1: 活 5 名无回归 ----------
    def test_t1a_tool_called(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(etype='tool_called', description='✓ dashboard_open',
                         source='IntentResolver', salience=0.85,
                         metadata={'name': 'dashboard_open', 'args': {}, 'ok': True,
                                   'result_summary': 'opened'})
        r = trace_reply(jarvis_reply="I've opened the dashboard, Sir.",
                        tool_results=[], stm_recent=[], include_swm_tool_called=True)
        self.assertEqual(r['n_unverified'], 0)

    def test_t1b_sir_field_updated(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(etype='sir_field_updated',
                         description="ProfileCard: biographic.height = '1.83m'",
                         source='MemoryGateway', salience=0.8,
                         metadata={'field_path': 'biographic.height', 'ok': True})
        r = trace_reply(jarvis_reply="I've noted that, Sir.",
                        tool_results=[], stm_recent=[], include_swm_tool_called=True)
        self.assertEqual(r['n_unverified'], 0)

    def test_t1c_sir_profile_overwritten(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(etype='sir_profile_overwritten',
                         description="profile.preferred_tools = 'Kiro'",
                         source='ProfileCard', salience=0.85, metadata={'field': 'preferred_tools'})
        r = trace_reply(jarvis_reply="I've updated your profile, Sir.",
                        tool_results=[], stm_recent=[], include_swm_tool_called=True)
        self.assertEqual(r['n_unverified'], 0)

    def test_t1d_concern_field_updated(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(etype='concern_field_updated',
                         description="concern sir_sleep.severity = '0.8'",
                         source='concerns_ledger', salience=0.75,
                         metadata={'concern_id': 'sir_sleep', 'field': 'severity'})
        r = trace_reply(jarvis_reply="I've updated the concern, Sir.",
                        tool_results=[], stm_recent=[], include_swm_tool_called=True)
        self.assertEqual(r['n_unverified'], 0)

    def test_t1e_promise_fulfilled(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(etype='promise_fulfilled', description="Sir 完成体检 promise",
                         source='promise_log', salience=0.8, metadata={})
        # promise 声称需 past_action 动词; 用 "I've completed" 不在表, 用 noted/logged
        r = trace_reply(jarvis_reply="I've logged your promise completion, Sir.",
                        tool_results=[], stm_recent=[], include_swm_tool_called=True)
        # 至少不崩, 有 ✅ event (promise_fulfilled 活名) → 粗粒度 verified
        self.assertEqual(r['n_unverified'], 0)

    # ---------- T2: 死名移除逐字节同 ----------
    def test_t2_dead_name_not_recognized(self):
        """publish 死名 event → 不被识别为 evidence (消费 set 已不含死名)."""
        from jarvis_claim_tracer import trace_reply
        for dead in ('memory_corrected', 'memory_update',
                     'profile_field_updated', 'concern_modified'):
            b = _fresh_bus()
            b.publish(etype=dead, description=f"{dead} fired",
                      source='test', salience=0.85, metadata={})
            r = trace_reply(jarvis_reply="I've updated your profile, Sir.",
                            tool_results=[], stm_recent=[], include_swm_tool_called=True)
            # 死名不在消费 set → recent_events 不返它 → 无 ✅ evidence → unverified
            self.assertGreaterEqual(r['n_unverified'], 1,
                                    f"死名 {dead} 不该被识别为 evidence")

    # ---------- T3: 域映射清理后活名域不变 ----------
    def test_t3_domain_map_live_names(self):
        import jarvis_claim_tracer as ct
        ct._DOMAIN_VOCAB_CACHE['path'] = ''
        ct._DOMAIN_VOCAB_CACHE['mtime'] = 0.0
        ct._DOMAIN_VOCAB_CACHE['data'] = None
        self.assertEqual(ct._etype_to_domain('sir_profile_overwritten'), 'profile')
        self.assertEqual(ct._etype_to_domain('concern_field_updated'), 'concern')
        self.assertEqual(ct._etype_to_domain('sir_field_updated'), 'memory')
        self.assertEqual(ct._etype_to_domain('tool_called'), 'device_action')
        self.assertEqual(ct._etype_to_domain('promise_fulfilled'), 'promise')
        # 死名 → unknown (map 已无)
        self.assertEqual(ct._etype_to_domain('memory_corrected'), 'unknown')
        self.assertEqual(ct._etype_to_domain('profile_field_updated'), 'unknown')

    # ---------- T4: 空窗口 ----------
    def test_t4_empty_window_unverified(self):
        from jarvis_claim_tracer import trace_reply
        r = trace_reply(jarvis_reply="I've opened the dashboard, Sir.",
                        tool_results=[], stm_recent=[], include_swm_tool_called=True)
        self.assertGreaterEqual(r['n_unverified'], 1)


if __name__ == '__main__':
    unittest.main()
