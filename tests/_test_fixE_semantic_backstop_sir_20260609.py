# -*- coding: utf-8 -*-
"""[fixE-llm-semantic-backstop / Sir 2026-06-09] LLM 语义兜底层 (影子期默认).

(d) 域配对治跨大类蒙混, 残留"同域跨 field". (c) 在 (d) 判 fail 的候选上用 LLM 语义判.
影子期 (_meta.enforce=false 默认): live 仍走 (d), LLM verdict 只 record.
单测用 mock semantic_provider (不真打 LLM).

T1 影子默认·零回归: enforce=false, (d) fail 候选 + mock provider 返 True → live 仍 unverified (走 d).
T2 flip enforce·LLM 翻案: 同上 enforce=true → verified.
T3 (d) 放行不问 LLM: (d)/vocab pass 候选 → verified, mock provider 未被调用 (省成本).
T4 provider 故障开放: mock 抛异常/None → False 不阻断 (enforce=true 不翻案不崩).
T5 契约向后兼容: 不传 semantic_provider (老 caller) → 正常工作无回归.
T6 enforce flag: enforce false/true 切换 live 行为符合预期.
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


def _set_semantic_enforce(val: bool):
    import jarvis_claim_tracer as ct
    if not hasattr(ct, '_ORIG_SEM_ENFORCE'):
        ct._ORIG_SEM_ENFORCE = ct._semantic_enforce
    ct._semantic_enforce = lambda: val


def _set_domain_enforce(val: bool):
    import jarvis_claim_tracer as ct
    if not hasattr(ct, '_ORIG_DOMAIN_ENFORCE'):
        ct._ORIG_DOMAIN_ENFORCE = ct._domain_enforce
    ct._domain_enforce = lambda: val


def _restore():
    import jarvis_claim_tracer as ct
    if hasattr(ct, '_ORIG_SEM_ENFORCE'):
        ct._semantic_enforce = ct._ORIG_SEM_ENFORCE
    if hasattr(ct, '_ORIG_DOMAIN_ENFORCE'):
        ct._domain_enforce = ct._ORIG_DOMAIN_ENFORCE
    ct._DOMAIN_VOCAB_CACHE['path'] = ''
    ct._DOMAIN_VOCAB_CACHE['mtime'] = 0.0
    ct._DOMAIN_VOCAB_CACHE['data'] = None


class TestFixESemanticBackstop(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()
        # (d) enforce=true 让域配对真 fail (制造 (c) 触发条件)
        _set_domain_enforce(True)
        self.calls = []

    def tearDown(self):
        _restore()

    def _provider_yes(self, claim_text, events):
        self.calls.append((claim_text, list(events)))
        return True

    def _provider_no(self, claim_text, events):
        self.calls.append((claim_text, list(events)))
        return False

    def _provider_raises(self, claim_text, events):
        self.calls.append((claim_text, list(events)))
        raise RuntimeError('simulated LLM/balance failure')

    # ---------- T1: 影子默认·零回归 ----------
    def test_t1_shadow_default_zero_regression(self):
        """enforce=false: (d) fail 候选 + provider YES → live 仍 unverified (走 d)."""
        _set_semantic_enforce(False)
        from jarvis_claim_tracer import trace_reply
        # device 声称 + 仅 profile event → (d) enforce 判 fail
        self.bus.publish(
            etype='sir_profile_overwritten', description="profile.x='y'",
            source='ProfileCard', salience=0.85, metadata={'field': 'x'},
        )
        result = trace_reply(
            jarvis_reply="I've muted the notifications, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
            semantic_provider=self._provider_yes,
        )
        # 影子期: live 走 (d) 结果 = unverified (provider 即便 YES 也不改 live)
        self.assertGreaterEqual(result['n_unverified'], 1,
                                "影子期 LLM YES 不改 live, 仍 unverified")

    # ---------- T2: flip enforce·LLM 翻案 ----------
    def test_t2_enforce_llm_overturns(self):
        _set_semantic_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten', description="profile.x='y'",
            source='ProfileCard', salience=0.85, metadata={'field': 'x'},
        )
        result = trace_reply(
            jarvis_reply="I've muted the notifications, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
            semantic_provider=self._provider_yes,
        )
        self.assertEqual(result['n_unverified'], 0,
                         "enforce: LLM YES → 翻案 verified")

    # ---------- T3: (d) 放行不问 LLM ----------
    def test_t3_domain_pass_skips_llm(self):
        """(d) pass 候选 → verified 且 provider 未被调用 (省成本铁证)."""
        _set_semantic_enforce(True)
        from jarvis_claim_tracer import trace_reply
        # profile 声称 + profile event → (d) pass
        self.bus.publish(
            etype='sir_profile_overwritten', description="profile.x='y'",
            source='ProfileCard', salience=0.85, metadata={'field': 'x'},
        )
        result = trace_reply(
            jarvis_reply="I've updated your profile, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
            semantic_provider=self._provider_yes,
        )
        self.assertEqual(result['n_unverified'], 0, "(d) pass → verified")
        self.assertEqual(len(self.calls), 0,
                         "(d) 放行的不该调 LLM (省成本)")

    # ---------- T4: provider 故障开放 ----------
    def test_t4_provider_fault_open(self):
        """provider 抛异常 → False 不阻断 (enforce=true 下不翻案不崩)."""
        _set_semantic_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten', description="profile.x='y'",
            source='ProfileCard', salience=0.85, metadata={'field': 'x'},
        )
        result = trace_reply(
            jarvis_reply="I've muted the notifications, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
            semantic_provider=self._provider_raises,
        )
        # provider 异常 → 故障开放 False → 不翻案 → 仍 unverified (不崩)
        self.assertGreaterEqual(result['n_unverified'], 1,
                                "provider 异常 → 不翻案, 不崩")

    # ---------- T5: 契约向后兼容 ----------
    def test_t5_backward_compat_no_provider(self):
        """不传 semantic_provider → 正常工作无回归."""
        _set_semantic_enforce(True)
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='sir_profile_overwritten', description="profile.x='y'",
            source='ProfileCard', salience=0.85, metadata={'field': 'x'},
        )
        result = trace_reply(
            jarvis_reply="I've updated your profile, Sir.",
            tool_results=[], stm_recent=[], include_swm_tool_called=True,
        )
        self.assertIn('n_claims', result)
        self.assertEqual(result['n_unverified'], 0, "profile 声称同域 → verified")

    # ---------- T6: enforce flag 切换 ----------
    def test_t6_enforce_toggle(self):
        from jarvis_claim_tracer import trace_reply

        def run():
            b = _fresh_bus()
            b.publish(etype='sir_profile_overwritten', description="profile.x='y'",
                      source='ProfileCard', salience=0.85, metadata={'field': 'x'})
            return trace_reply(
                jarvis_reply="I've muted the notifications, Sir.",
                tool_results=[], stm_recent=[], include_swm_tool_called=True,
                semantic_provider=self._provider_yes,
            )
        _set_semantic_enforce(False)
        self.assertGreaterEqual(run()['n_unverified'], 1, "enforce=false → live unverified")
        _set_semantic_enforce(True)
        self.assertEqual(run()['n_unverified'], 0, "enforce=true → LLM 翻案 verified")


if __name__ == '__main__':
    unittest.main()
