# -*- coding: utf-8 -*-
"""[第五阶段支柱 A / Sir 2026-05-29 02:29 真痛 "开着挂机心疼 token"] 回归.

Sir 真痛: 思考脑 active 45s tick 每 tick 必调 LLM (flash 主脑同款),
挂机 (Sir 不在/没动/无新事件) 时仍重复烧 = 最大浪费.

支柱 A: tick 前算 evidence 指纹 (外部输入: sir_state + idle bucket +
SWM event type/desc + STM 最新 turn), 跟上次一样 → skip LLM (不烧 token),
daemon alive. 连续 skip 满 max_skip_streak → 强制 think 1 次 (心跳).

设计: docs/JARVIS_THINKING_COST_AWARE_SELF_DEBUG_DESIGN.md 支柱 A
vocab: memory_pool/inner_thought_cost_config.json

测试覆盖 (14 testcase):
指纹算法 (8):
  FP1 相同 evidence → 相同指纹
  FP2 sir_state 变 → 指纹变
  FP3 新 SWM event → 指纹变
  FP4 Sir 说新话 (STM 新 turn) → 指纹变
  FP5 idle 跨桶 (300 边界) → 指纹变
  FP6 idle 同桶 (10s vs 20s) → 指纹同 (防抖动)
  FP7 age_s 变但内容同 → 指纹同 (关键: 每 tick age 变仍 skip)
  FP8 recent_thoughts 变 → 指纹不变 (关键: 思考脑自产不污染)
skip 逻辑 (6):
  SK1 首 tick → 不 skip (think)
  SK2 第二 tick 指纹同 → skip
  SK3 指纹变 → 不 skip + reset streak
  SK4 连续 skip 到 max → 强制 think + reset (心跳)
  SK5 enabled=false → 不 skip (退回老行为)
  SK6 skip count 累计 (audit)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CFG_PATCH = 'jarvis_inner_thought_daemon._load_cost_config'


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    d = InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=None,
    )
    d._bg_log = MagicMock()  # 不写真 runtime log
    return d


def _ev(sir_state='active', idle=10, swm_events=None, stm=None,
        recent_thoughts=None):
    ev = {
        'sir_state': sir_state,
        'idle_seconds': idle,
        'swm_events': swm_events if swm_events is not None else [],
        'stm': stm if stm is not None else [],
    }
    if recent_thoughts is not None:
        ev['recent_thoughts'] = recent_thoughts
    return ev


def _cfg(enabled=True, max_skip=20, buckets=(300, 1800)):
    return {'evidence_gate': {
        'enabled': enabled,
        'max_skip_streak': max_skip,
        'idle_buckets_s': list(buckets),
    }}


class TestEvidenceFingerprint(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()

    def test_FP1_same_evidence_same_fp(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            ev = _ev(swm_events=[{'type': 'x', 'desc': 'hello'}])
            fp1 = self.d._compute_evidence_fingerprint('active', ev)
            fp2 = self.d._compute_evidence_fingerprint('active', ev)
            self.assertEqual(fp1, fp2)

    def test_FP2_state_change_fp_change(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            fp_a = self.d._compute_evidence_fingerprint('active', _ev())
            fp_b = self.d._compute_evidence_fingerprint('sleep', _ev())
            self.assertNotEqual(fp_a, fp_b)

    def test_FP3_new_swm_event_fp_change(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            fp1 = self.d._compute_evidence_fingerprint(
                'active', _ev(swm_events=[]))
            fp2 = self.d._compute_evidence_fingerprint(
                'active', _ev(swm_events=[
                    {'type': 'reminder_fired', 'desc': 'new'}]))
            self.assertNotEqual(fp1, fp2)

    def test_FP4_sir_new_turn_fp_change(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            fp1 = self.d._compute_evidence_fingerprint('active', _ev(
                stm=[{'when': '2026-05-29T02:00:00', 'user': 'hi'}]))
            fp2 = self.d._compute_evidence_fingerprint('active', _ev(
                stm=[{'when': '2026-05-29T02:05:00', 'user': 'hello again'}]))
            self.assertNotEqual(fp1, fp2)

    def test_FP5_idle_cross_bucket_fp_change(self):
        with patch(CFG_PATCH, return_value=_cfg(buckets=(300, 1800))):
            fp_lo = self.d._compute_evidence_fingerprint(
                'active', _ev(idle=100))
            fp_hi = self.d._compute_evidence_fingerprint(
                'active', _ev(idle=600))
            self.assertNotEqual(fp_lo, fp_hi)

    def test_FP6_idle_same_bucket_fp_same(self):
        with patch(CFG_PATCH, return_value=_cfg(buckets=(300, 1800))):
            fp1 = self.d._compute_evidence_fingerprint('active', _ev(idle=10))
            fp2 = self.d._compute_evidence_fingerprint('active', _ev(idle=20))
            self.assertEqual(fp1, fp2)

    def test_FP7_age_s_change_fp_same(self):
        # 关键: SWM event age_s 每 tick 变, 但 type+desc 同 → 指纹必须同
        # (否则永不 skip — 挂机时每 tick age 增长会破坏省 token)
        with patch(CFG_PATCH, return_value=_cfg()):
            fp1 = self.d._compute_evidence_fingerprint('active', _ev(
                swm_events=[{'type': 'x', 'desc': 'same', 'age_s': 5}]))
            fp2 = self.d._compute_evidence_fingerprint('active', _ev(
                swm_events=[{'type': 'x', 'desc': 'same', 'age_s': 50}]))
            self.assertEqual(fp1, fp2)

    def test_FP8_recent_thoughts_no_pollute(self):
        # 关键: 思考脑自己产 thought 不能改指纹 (否则它一 think 就永不 skip)
        with patch(CFG_PATCH, return_value=_cfg()):
            fp1 = self.d._compute_evidence_fingerprint('active', _ev(
                recent_thoughts=[]))
            fp2 = self.d._compute_evidence_fingerprint('active', _ev(
                recent_thoughts=[{'id': 't1', 'thought': 'I am thinking'}]))
            self.assertEqual(fp1, fp2)


class TestEvidenceGateSkip(unittest.TestCase):
    def setUp(self):
        self.d = _make_daemon()

    def test_SK1_first_tick_no_skip(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            # 首 tick: _last_tick_fingerprint='' != 新指纹 → 不 skip (think)
            skip = self.d._maybe_evidence_gate_skip('active', _ev())
            self.assertFalse(skip)

    def test_SK2_same_fp_skip(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            ev = _ev(swm_events=[{'type': 'x', 'desc': 'a'}])
            self.d._maybe_evidence_gate_skip('active', ev)   # 首 tick set fp
            skip = self.d._maybe_evidence_gate_skip('active', ev)  # 第二 tick 同
            self.assertTrue(skip)

    def test_SK3_fp_change_no_skip_reset(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            ev1 = _ev(swm_events=[{'type': 'x', 'desc': 'a'}])
            self.d._maybe_evidence_gate_skip('active', ev1)  # set fp
            self.d._maybe_evidence_gate_skip('active', ev1)  # skip, streak=1
            self.assertEqual(self.d._evidence_skip_streak, 1)
            ev2 = _ev(swm_events=[{'type': 'y', 'desc': 'new event'}])
            skip = self.d._maybe_evidence_gate_skip('active', ev2)  # 指纹变
            self.assertFalse(skip)
            self.assertEqual(self.d._evidence_skip_streak, 0)  # reset

    def test_SK4_max_skip_heartbeat(self):
        with patch(CFG_PATCH, return_value=_cfg(max_skip=3)):
            ev = _ev(swm_events=[{'type': 'x', 'desc': 'a'}])
            self.d._maybe_evidence_gate_skip('active', ev)   # set fp, streak=0
            # skip 3 次 (streak 1,2,3)
            self.assertTrue(self.d._maybe_evidence_gate_skip('active', ev))
            self.assertTrue(self.d._maybe_evidence_gate_skip('active', ev))
            self.assertTrue(self.d._maybe_evidence_gate_skip('active', ev))
            self.assertEqual(self.d._evidence_skip_streak, 3)
            # 第 4 次: streak==max(3) → 强制 think (不 skip) + reset
            skip = self.d._maybe_evidence_gate_skip('active', ev)
            self.assertFalse(skip)
            self.assertEqual(self.d._evidence_skip_streak, 0)

    def test_SK5_disabled_no_skip(self):
        with patch(CFG_PATCH, return_value=_cfg(enabled=False)):
            ev = _ev()
            self.d._maybe_evidence_gate_skip('active', ev)
            skip = self.d._maybe_evidence_gate_skip('active', ev)
            self.assertFalse(skip)  # disabled → 永不 skip (退回老每 tick 调 LLM)

    def test_SK6_skip_count_audit(self):
        with patch(CFG_PATCH, return_value=_cfg()):
            ev = _ev(swm_events=[{'type': 'x', 'desc': 'a'}])
            self.d._maybe_evidence_gate_skip('active', ev)   # set fp (count 不增)
            self.d._maybe_evidence_gate_skip('active', ev)   # skip count=1
            self.d._maybe_evidence_gate_skip('active', ev)   # skip count=2
            self.assertEqual(self.d._evidence_gated_skip_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
