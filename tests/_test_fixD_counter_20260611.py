# -*- coding: utf-8 -*-
"""[fixD-counter / Sir 2026-06-11 裁决E] 影子期分母计数器 — 只记数不改判定.

缘起: 影子期仪表只记不一致 (DomainShadow 行) 缺总评估分母 → 一致率无法计算,
切 enforce 证据不足 (工单#4.1 读数). 本刀: 每次域配对评估 evaluated+1, 不一致
mismatch+1, 节流 + 退出各 dump 一行 [ClaimTracer/DomainShadowStats] evaluated=N
mismatch=M. 零判定路径接触.

T1 一致评估: evaluated+1, mismatch+0
T2 不一致评估: evaluated+1, mismatch+1
T3 域分不出 (回落粗粒度): 不计数
T4 影子期判定不变: 不一致计数的同时 live verdict 仍走粗粒度 (verified)
T5 节流 dump: 间隔归零 → bg_log 出 DomainShadowStats 行
T6 退出 dump: evaluated>0 出 final 行; 全零不出 (不刷空行)
红线: 纯 mock/SWM 隔离 bus, 不写真档案; enforce monkeypatch 测后还原.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_claim_tracer as ct  # noqa: E402


def _fresh_bus():
    from jarvis_utils import ConversationEventBus
    bus = ConversationEventBus(restore=False)
    ConversationEventBus.register_global(bus)
    return bus


class TestFixDCounter(unittest.TestCase):

    def setUp(self):
        self.bus = _fresh_bus()
        if not hasattr(ct, '_ORIG_DOMAIN_ENFORCE'):
            ct._ORIG_DOMAIN_ENFORCE = ct._domain_enforce
        ct._domain_enforce = lambda: False  # 影子期
        # 计数器隔离
        self._stats0 = dict(ct._DOMAIN_SHADOW_STATS)
        ct._DOMAIN_SHADOW_STATS['evaluated'] = 0
        ct._DOMAIN_SHADOW_STATS['mismatch'] = 0
        ct._DOMAIN_SHADOW_STATS['last_log_ts'] = 0.0
        self._interval0 = ct._DOMAIN_STATS_LOG_INTERVAL_S

    def tearDown(self):
        ct._domain_enforce = ct._ORIG_DOMAIN_ENFORCE
        ct._DOMAIN_STATS_LOG_INTERVAL_S = self._interval0
        for k, v in self._stats0.items():
            ct._DOMAIN_SHADOW_STATS[k] = v

    def _stats(self):
        return (int(ct._DOMAIN_SHADOW_STATS['evaluated']),
                int(ct._DOMAIN_SHADOW_STATS['mismatch']))

    # ---- T1 一致评估 ----
    def test_t1_agreeing_evaluation_counts(self):
        self.bus.publish(etype='tool_called',
                         description="✅ l4_audio_hands.mute_app ok",
                         source='worker', salience=0.85,
                         metadata={'organ': 'l4_audio_hands'})
        r = ct.trace_reply(jarvis_reply="I've muted the notifications, Sir.",
                           tool_results=[], stm_recent=[],
                           include_swm_tool_called=True)
        ev, mm = self._stats()
        self.assertEqual(ev, 1, "域配对评估应 +1")
        self.assertEqual(mm, 0, "同域一致不应计 mismatch")
        self.assertGreaterEqual(r['n_claims'], 1)

    # ---- T2 不一致评估 ----
    def test_t2_mismatch_counts(self):
        self.bus.publish(etype='sir_profile_overwritten',
                         description="profile.preferred_tools = 'Kiro'",
                         source='ProfileCard', salience=0.85,
                         metadata={'field': 'preferred_tools'})
        ct.trace_reply(jarvis_reply="I've muted the notifications, Sir.",
                       tool_results=[], stm_recent=[],
                       include_swm_tool_called=True)
        ev, mm = self._stats()
        self.assertEqual(ev, 1)
        self.assertEqual(mm, 1, "device 声称 vs 仅 profile 证据 → mismatch+1")

    # ---- T3 域分不出不计数 ----
    def test_t3_unclassifiable_not_counted(self):
        self.bus.publish(etype='tool_called',
                         description="✅ something ok",
                         source='worker', salience=0.85, metadata={})
        ct.trace_reply(jarvis_reply="I've finished that, Sir.",  # 无域关键词
                       tool_results=[], stm_recent=[],
                       include_swm_tool_called=True)
        ev, mm = self._stats()
        self.assertEqual((ev, mm), (0, 0), "unknown 回落路径不进分母")

    # ---- T4 影子期判定不变 ----
    def test_t4_shadow_verdict_unchanged_while_counting(self):
        self.bus.publish(etype='sir_profile_overwritten',
                         description="profile.x = 'y'",
                         source='ProfileCard', salience=0.85,
                         metadata={'field': 'x'})
        r = ct.trace_reply(jarvis_reply="I've muted the speaker, Sir.",
                           tool_results=[], stm_recent=[],
                           include_swm_tool_called=True)
        self.assertEqual(r['n_unverified'], 0,
                         "影子期 live 仍走粗粒度 verified (计数零判定影响)")
        self.assertEqual(self._stats(), (1, 1))

    # ---- T5 节流 dump ----
    def test_t5_periodic_log_line(self):
        ct._DOMAIN_STATS_LOG_INTERVAL_S = 0.0
        captured = []
        orig = ct.bg_log
        try:
            ct.bg_log = lambda msg, *a, **k: captured.append(str(msg))
            ct._bump_domain_shadow_stats(mismatch=False)
        finally:
            ct.bg_log = orig
        hits = [m for m in captured if 'DomainShadowStats' in m]
        self.assertTrue(hits, "间隔到期应 dump 读数行")
        self.assertIn('evaluated=1 mismatch=0', hits[0])

    # ---- T6 退出 dump ----
    def test_t6_final_dump(self):
        captured = []
        orig = ct.bg_log
        try:
            ct.bg_log = lambda msg, *a, **k: captured.append(str(msg))
            ct._DOMAIN_SHADOW_STATS['evaluated'] = 7
            ct._DOMAIN_SHADOW_STATS['mismatch'] = 2
            ct._dump_domain_shadow_stats_final()
            ct._DOMAIN_SHADOW_STATS['evaluated'] = 0
            ct._DOMAIN_SHADOW_STATS['mismatch'] = 0
            ct._dump_domain_shadow_stats_final()
        finally:
            ct.bg_log = orig
        finals = [m for m in captured if 'DomainShadowStats/final' in m]
        self.assertEqual(len(finals), 1, "evaluated>0 出 1 行, 全零不出")
        self.assertIn('evaluated=7 mismatch=2', finals[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
