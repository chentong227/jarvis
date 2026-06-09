# -*- coding: utf-8 -*-
"""[fixD-claim-domain-scoped-verify / Sir 2026-06-09] 域配对 verify (影子期默认).

粗粒度 verify (180s 窗口任一 ✅ 放行任意 past_action) → 假声称被无关真 mutation 蒙混.
修法: claim 分动作域 (profile/concern/memory/device_action/promise), 要求同域 ✅ event.
影子期 (_meta.enforce=false 默认): live 仍走粗粒度, 域 verdict 只 record. flip 才收紧.

T1 影子默认·零回归铁证: enforce=false, device 声称 + 仅 profile event → verified (不变).
T2 flip·跨大类被堵:    enforce=true, 同上 → unverified.
T3 同域正解:           enforce=true, profile 声称 + profile event → verified.
T4 unknown 回落:        enforce=true, 无域关键词声称 + 任一 ✅ → verified (行为不变).
T5 现 3 名同域无回归:   tool_called/sir_field_updated/promise_fulfilled 各配同域 → verified; 空窗口 → unverified.
T6 多域放宽:           enforce=true, 复合声称 + 任一同域 → verified.
T7 错分缓解:           模糊声称分不出域 → unknown 回落, 不误判.
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


def _set_enforce(val: bool):
    """monkeypatch _domain_enforce 返回值 (testcase 隔离, 不写真 vocab)."""
    import jarvis_claim_tracer as ct
    ct._domain_enforce = lambda: val


def _clear_domain_cache():
    import jarvis_claim_tracer as ct
    # 还原 _domain_enforce 为真实现 (重新 import 模块属性)
    import importlib
    # 直接恢复: 重新绑定原函数 (从模块源重新读不现实, 用保存的原引用)
    if hasattr(ct, '_ORIG_DOMAIN_ENFORCE'):
        ct._domain_enforce = ct._ORIG_DOMAIN_ENFORCE
    ct._DOMAIN_VOCAB_CACHE['path'] = ''
    ct._DOMAIN_VOCAB_CACHE['mtime'] = 0.0
    ct._DOMAIN_VOCAB_CACHE['data'] = None


class TestFixDDomainScoped(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()
        import jarvis_claim_tracer as ct
        if not hasattr(ct, '_ORIG_DOMAIN_ENFORCE'):
            ct._ORIG_DOMAIN_ENFORCE = ct._domain_enforce

    def tearDown(self):
        _clear_domain_cache()

    # ---------- T1: 影子默认·零回归铁证 ----------
    def test_t1_shadow_default_zero_regression(self):
        """enforce=false: device 声称 + 仅 profile event → verified (live 走粗粒度, 不变)."""
        _set_enforce(False)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten',
            description="profile.preferred_tools = 'Kiro'",
            source='ProfileCard', salience=0.85, metadata={'field': 'preferred_tools'},
        )
        result = trace_reply(
            jarvis_reply="I've muted the notifications, Sir.",  # device 声称
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        # 影子期: live 走粗粒度 (窗口有 ✅) → verified (与现行为逐字节同)
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0,
                         "影子期 device 声称 + profile event 仍 verified (零回归)")

    # ---------- T2: flip·跨大类被堵 ----------
    def test_t2_enforce_blocks_cross_category(self):
        """enforce=true: device 声称 + 仅 profile event → unverified (收紧生效)."""
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten',
            description="profile.preferred_tools = 'Kiro'",
            source='ProfileCard', salience=0.85, metadata={'field': 'preferred_tools'},
        )
        result = trace_reply(
            jarvis_reply="I've muted the notifications, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertGreaterEqual(result['n_unverified'], 1,
                                "enforce: device 声称无同域 event → unverified")

    # ---------- T3: 同域正解 ----------
    def test_t3_same_domain_verifies(self):
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten',
            description="profile.preferred_tools = 'Kiro'",
            source='ProfileCard', salience=0.85, metadata={'field': 'preferred_tools'},
        )
        result = trace_reply(
            jarvis_reply="I've updated your profile, Sir.",  # profile 声称
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0,
                         "enforce: profile 声称 + profile event → verified")

    # ---------- T4: unknown 回落 ----------
    def test_t4_unknown_domain_fallback(self):
        """enforce=true: 无域关键词声称 + 任一 ✅ → verified (回落粗粒度, 行为不变)."""
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='tool_called',
            description='✓ some_tool', source='IntentResolver', salience=0.85,
            metadata={'name': 'some_tool', 'args': {}, 'ok': True, 'result_summary': 'done'},
        )
        # "I've cancelled it" — cancelled 在 past_action regex 但不在任何域 keyword → unknown
        result = trace_reply(
            jarvis_reply="I've cancelled it, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0,
                         "无域声称 → unknown → 回落粗粒度 verified")

    # ---------- T5: 现 3 名同域无回归 ----------
    def test_t5a_tool_called_device_verifies(self):
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='tool_called', description='✓ dashboard_open',
            source='IntentResolver', salience=0.85,
            metadata={'name': 'dashboard_open', 'args': {}, 'ok': True, 'result_summary': 'opened'},
        )
        result = trace_reply(
            jarvis_reply="I've opened the dashboard, Sir.",  # device 声称
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertEqual(result['n_unverified'], 0)

    def test_t5b_sir_field_updated_memory_verifies(self):
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_field_updated',
            description="ProfileCard: biographic.height = '1.83m'",
            source='MemoryGateway', salience=0.8, metadata={'field_path': 'biographic.height', 'ok': True},
        )
        result = trace_reply(
            jarvis_reply="I've noted that, Sir.",  # memory 声称
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertEqual(result['n_unverified'], 0)

    def test_t5c_empty_window_unverified(self):
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply="I've opened the dashboard, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_unverified'], 1,
                                "空窗口 → device 声称 unverified")

    # ---------- T6: 多域放宽 ----------
    def test_t6_multi_domain_relaxed(self):
        """enforce=true: 复合声称 (profile+device) + 任一同域 event → verified."""
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten',
            description="profile.x = 'y'", source='ProfileCard', salience=0.85, metadata={},
        )
        result = trace_reply(
            jarvis_reply="I've updated your profile and sent the email, Sir.",  # profile + device
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertGreaterEqual(result['n_claims'], 1)
        self.assertEqual(result['n_unverified'], 0,
                         "多域: 任一同域 (profile) event 命中 → verified")

    # ---------- T7: 错分缓解 ----------
    def test_t7_ambiguous_claim_fallback(self):
        """模糊声称分不出域 → unknown 回落, 不误判 (有 ✅ → verified)."""
        _set_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='tool_called', description='✓ generic',
            source='IntentResolver', salience=0.85,
            metadata={'name': 'generic', 'args': {}, 'ok': True, 'result_summary': 'ok'},
        )
        result = trace_reply(
            jarvis_reply="I've cancelled it, Sir.",  # cancelled 不在任何域 keyword → unknown
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertEqual(result['n_unverified'], 0,
                         "模糊声称 unknown 回落 → 不误判")


if __name__ == '__main__':
    unittest.main()
