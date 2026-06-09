# -*- coding: utf-8 -*-
"""[fixA-claim-evidence-coverage / Sir 2026-06-09] ClaimTracer 消费端加认实名 mutation event.

根因: ClaimTracer `_fetch_swm_tool_results` 消费 set 列了 'profile_field_updated' /
'concern_modified' 两个无任何生产者的死名, 而真实 mutation 用别名发:
  - profile 写 → 'sir_profile_overwritten' (jarvis_routing.py:928)
  - concern 改 → 'concern_field_updated'  (jarvis_concerns.py:711)
→ 真 "I've updated your profile" 声称在 180s 窗口找不到 ✅ → 冤判 unverified (false-positive)
→ 主脑下轮被误导多余自纠/道歉.

修法: 把两个实名加进消费 set. record-only, 零 TTFT, 纯加名.

T1 (G1 · bugB 闭环铁证): profile 声称 + sir_profile_overwritten event → verified;
                          反例 空窗口 → unverified (证明该 event 是转判关键).
T2 (G2): concern 声称 + concern_field_updated event → verified; 无则 unverified.
T3 (无回归): 现有 3 名 (tool_called/sir_field_updated/promise_fulfilled) 各自仍 verified;
            空窗口仍 unverified.
T4 (红线 record-only): trace_reply 不改 reply 文本 / 不抛 / 返 dict 无副作用.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_bus():
    """新建并注册全局 EventBus (restore=False 防老 swm_history 污染)."""
    from jarvis_utils import ConversationEventBus
    bus = ConversationEventBus(restore=False)
    ConversationEventBus.register_global(bus)
    return bus


class TestFixAClaimEvidenceCoverage(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()

    # ---------- T1: G1 profile 写 (bugB 闭环铁证) ----------
    def test_t1_g1_profile_overwritten_verifies_claim(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten',
            description="profile.preferred_tools = 'Kiro' (was: 'Cursor', source=reflector)",
            source='ProfileCard',
            salience=0.85,
            metadata={'field': 'preferred_tools', 'new_value': 'Kiro'},
        )
        result = trace_reply(
            jarvis_reply="I've updated your profile, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1,
                                "应抽到 past_action 'I've updated'")
        self.assertEqual(result['n_unverified'], 0,
                         "sir_profile_overwritten 在窗口 → 声称应 verified")

    def test_t1_g1_reverse_no_event_unverified(self):
        """反例: 同句、窗口内无任何 ✅ → unverified (证明 event 是转判关键)."""
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply="I've updated your profile, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertGreaterEqual(result['n_unverified'], 1,
                                "空窗口 → past_action 应 unverified")

    # ---------- T2: G2 concern 改 ----------
    def test_t2_g2_concern_field_updated_verifies_claim(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='concern_field_updated',
            description="concern sir_sleep.severity = '0.8' (was '0.5')",
            source='concerns_ledger',
            salience=0.8,
            metadata={'concern_id': 'sir_sleep', 'field': 'severity'},
        )
        result = trace_reply(
            jarvis_reply="I've updated the concern, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0,
                         "concern_field_updated 在窗口 → 声称应 verified")

    def test_t2_g2_reverse_no_event_unverified(self):
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply="I've updated the concern, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_unverified'], 1)

    # ---------- T3: 无回归 (现有 3 名仍 verified) ----------
    def test_t3_existing_names_still_verify(self):
        from jarvis_claim_tracer import trace_reply
        # sir_field_updated (memory correction 真路径)
        self.bus.publish(
            etype='sir_field_updated',
            description="ProfileCard: biographic.height = '1.83m'",
            source='MemoryGateway',
            salience=0.8,
            metadata={'field_path': 'biographic.height', 'ok': True},
        )
        result = trace_reply(
            jarvis_reply="I've saved that, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0,
                         "sir_field_updated 仍应被认 (无回归)")

    def test_t3_tool_called_still_verify(self):
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='tool_called',
            description='✓ ui_control.dashboard_open',
            source='IntentResolver',
            salience=0.85,
            metadata={'name': 'dashboard_open', 'args': {}, 'ok': True,
                      'result_summary': 'opened'},
        )
        result = trace_reply(
            jarvis_reply="I've opened the dashboard, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0)

    def test_t3_empty_window_still_unverified(self):
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply="I've opened the dashboard, Sir.",
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_unverified'], 1,
                                "空窗口任何 past_action 仍 unverified")

    # ---------- T4: 红线 record-only ----------
    def test_t4_record_only_no_side_effect(self):
        from jarvis_claim_tracer import trace_reply
        reply = "I've updated your profile, Sir."
        self.bus.publish(
            etype='sir_profile_overwritten',
            description="profile.x = 'y'",
            source='ProfileCard',
            salience=0.85,
            metadata={},
        )
        result = trace_reply(
            jarvis_reply=reply,
            tool_results=[],
            stm_recent=[],
            include_swm_tool_called=True,
        )
        # 返回纯 stats dict, 不含改写后的 reply (record-only, 不 gate/不改文本)
        self.assertIsInstance(result, dict)
        self.assertIn('n_claims', result)
        self.assertNotIn('edited_reply', result)
        self.assertNotIn('reply', result)
        # 原 reply 变量未被 mutate
        self.assertEqual(reply, "I've updated your profile, Sir.")


if __name__ == '__main__':
    unittest.main()
