# -*- coding: utf-8 -*-
"""[P2 势能驱动 / Sir 2026-05-31] 体势能进 evidence 指纹 — 势能自转的"醒不醒"门.

Sir 真痛: 思考脑还是 tick=45s 时钟驱动空转 (C/D/E 反复想喝水), 不是势能驱动.
Sir 真意: "看到贾维斯在思考会很惊喜, 想看她在解决什么问题".

设计 (无 governor, 准则8 溶解元驱动): 体有 fresh delta (Weaver 算的真张力/新颖,
够幅度) → evidence 指纹含 node+幅度桶 → 指纹变 → daemon 醒去想那个势能区. 体 settled
(无 fresh delta) → 指纹稳 → idle (复用 evidence-gate skip, 杀 45s 空转).

覆盖 (monkeypatch body_focus, 无 LLM):
  T1 settled 体 (无 fresh delta) → 指纹不含 body 项 (两次同 → 可 skip)
  T2 体有 fresh delta (够幅度) → 指纹含 b:node:bucket (与 settled 不同 → 醒)
  T3 同区持续同幅度 → 同 bucket → 指纹稳 (不每 tick 重醒, 防 churn)
  T4 幅度低于 min → 不进指纹 (噪声门)
  T5 standing 高势能 (非 fresh) → 不进指纹 (只新 delta 算醒)
  T6 开关 off → 退回纯外部输入 (body 不进指纹)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_inner_thought_daemon import InnerThoughtDaemon


def _daemon():
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._bg_log = lambda *a, **k: None
    return d


class _FakeFocus:
    def __init__(self, focus):
        self._focus = focus

    def current_focus(self, limit=4):
        return self._focus[:limit]


_EVIDENCE = {'idle_seconds': 10, 'swm_events': [], 'stm': []}


def _fp(d, focus):
    with patch('jarvis_body_focus.get_body_focus', return_value=_FakeFocus(focus)):
        return d._compute_evidence_fingerprint('active', _EVIDENCE)


class TestP2PotentialDrivenTick(unittest.TestCase):
    def test_t1_settled_no_body_in_fp(self):
        d = _daemon()
        fp = _fp(d, [])   # settled: 无 focus
        self.assertNotIn('b:', fp)

    def test_t2_fresh_delta_changes_fp(self):
        d = _daemon()
        settled = _fp(d, [])
        # fresh delta: focus score = magnitude + 1.0 偏置 → 0.8 mag
        woke = _fp(d, [{'node': 'concern:sir_sleep', 'fresh': True, 'score': 1.8}])
        self.assertIn('b:concern:sir_sleep', woke)
        self.assertNotEqual(settled, woke)   # 指纹变 → 醒

    def test_t3_same_region_same_bucket_stable(self):
        d = _daemon()
        a = _fp(d, [{'node': 'concern:sir_sleep', 'fresh': True, 'score': 1.8}])
        b = _fp(d, [{'node': 'concern:sir_sleep', 'fresh': True, 'score': 1.85}])
        self.assertEqual(a, b)   # 同区同幅度桶 → 稳 (不每 tick 重醒)

    def test_t4_low_magnitude_gated(self):
        d = _daemon()
        # mag = 1.2 - 1.0 = 0.2 < 0.30 min → 不进指纹 (噪声门)
        fp = _fp(d, [{'node': 'concern:x', 'fresh': True, 'score': 1.2}])
        self.assertNotIn('b:', fp)

    def test_t5_standing_not_fresh_excluded(self):
        d = _daemon()
        # standing 高势能 (fresh=False) → 不算"新势能", 不进指纹
        fp = _fp(d, [{'node': 'concern:sir_sleep', 'fresh': False, 'score': 2.0}])
        self.assertNotIn('b:', fp)

    def test_t6_switch_off_excludes_body(self):
        d = _daemon()
        cfg_off = {
            'evidence_gate': {
                'enabled': True, 'idle_buckets_s': [300, 1800],
                'fingerprint_exclude_sources': [],
                'fingerprint_exclude_etype_suffixes': [],
                'body_potential_in_fingerprint': False,
            }
        }
        with patch('jarvis_inner_thought_daemon._load_cost_config',
                   return_value=cfg_off):
            fp = _fp(d, [{'node': 'concern:sir_sleep', 'fresh': True, 'score': 1.8}])
        self.assertNotIn('b:', fp)   # 开关 off → body 不进指纹


if __name__ == '__main__':
    unittest.main(verbosity=2)
