# -*- coding: utf-8 -*-
"""[衡 H0 / Sir 2026-06-01] 衡收敛三态显式化 (charter JARVIS_HENG_DESIGN.md §2).

"想发散 / 衡收敛"的收敛侧: 每轮 tick 收敛到三态之一(单一真理源 _classify_heng_state):
  discharge 放电: 真 effect (kind≠empty) 或 should_speak → 解了张力
  rest 休息: 空(无 effect)且已歇下(_resting) → settled(头等公民)
  filler: 空但还没歇(亢奋却空中项) → Layer 1 退避中,要杀的

覆盖:
  T1 真放电(actionable=propose_stance done)→ discharge
  T2 should_speak=True(即便 actionable=none)→ discharge(放电进语音)
  T3 空 + _resting=True → rest
  T4 空 + _resting=False → filler
  T5 heng_state 在 InnerThought 上可设(字段存在)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(), f'heng_h0_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _thought(actionable='none', should_speak=False, done=False, sal=0.7):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id='t', ts=time.time(), ts_iso='2026-06-01T00:00:00',
        category='B', thought='x', salience=sal,
        actionable=actionable, actionable_done=done, should_speak=should_speak,
    )


class TestHengH0(unittest.TestCase):
    def setUp(self):
        self.d = _build_daemon()

    def test_t1_discharge_effect(self):
        self.d._resting = False
        self.assertEqual(
            self.d._classify_heng_state(_thought('propose_stance', done=True)),
            'discharge')

    def test_t2_discharge_should_speak(self):
        self.d._resting = True  # 即便 resting, should_speak 仍算放电
        self.assertEqual(
            self.d._classify_heng_state(_thought('none', should_speak=True)),
            'discharge')

    def test_t3_rest_when_resting(self):
        self.d._resting = True
        self.assertEqual(self.d._classify_heng_state(_thought('none')), 'rest')

    def test_t4_filler_empty_not_resting(self):
        self.d._resting = False
        self.assertEqual(self.d._classify_heng_state(_thought('none')), 'filler')

    def test_t5_field_exists(self):
        t = _thought('none')
        t.heng_state = 'rest'
        self.assertEqual(t.heng_state, 'rest')
        # _heng_stats 初始化
        self.assertIn('filler', self.d._heng_stats)


if __name__ == '__main__':
    unittest.main(verbosity=2)
