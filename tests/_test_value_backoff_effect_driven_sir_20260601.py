# -*- coding: utf-8 -*-
"""[Sir 2026-06-01 真意 — 价值=放电效果, 非自评 salience / 杀 filler 中项]

Sir 三元框架: 思考要么真**放电** (discharge: solve/shape_next/adjust_self/want/
relate, kind != empty), 要么真**休息** (rest, 头等公民); 要杀的只有中间那坨
**filler = 亢奋却空** (kind=empty 不放电 + 不休息 + 自评高分)。

真机痛: B 类自省 "我刚回复太啰嗦, 该简洁" sal=0.85 kind=empty, 每 60s 一条不止。
根因: value_backoff 旧逻辑 `sal >= reset_on_high_salience(0.75) → reset streak` +
`is_low_value = sal<floor AND no_effect` — 反刍自评 0.85 高分 → 既不算低值、又触发
reset → streak 永不累积 → 永不退避。而 body_delta_wake 又因 active 对话 Weaver 反复
织同一话题 → 永远 has_fresh_delta → 撤退避回快 → 60s 反刍不止。

修 (两段协调):
1. value_backoff 改 effect-driven: 真放电 (kind!=empty) 或 should_speak → reset;
   不放电 = 低值 streak++ (**无视自评 salience**)。
2. body_delta_wake 加闸: 连续空想达 empty_streak_to_rest → 啃不动的 delta 不再撤退避
   (本测覆盖 #1 决策核心; #2 集成在 _tick, 由 streak 阈值驱动)。

覆盖:
  T1 effect-driven: 连续 kind=empty 高 sal(0.85) → streak 累积 + 退避 (旧逻辑会被 0.85 reset)
  T2 真放电 (actionable=propose_stance done) → reset streak 回 0
  T3 should_speak=True (即便 kind=empty) → reset (放电进语音)
  T4 legacy 回退 (value_by_effect_not_salience=False) → 高 sal 仍 reset (旧行为保留)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(), f'vb_effect_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _thought(actionable='none', sal=0.85, should_speak=False, done=False):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id='t', ts=time.time(), ts_iso='2026-06-01T00:00:00',
        category='B', thought='I was too verbose; I should be concise.',
        salience=sal, actionable=actionable,
        actionable_done=done, should_speak=should_speak,
    )


_VB_CFG = {'value_backoff': {
    'enabled': True,
    'value_by_effect_not_salience': True,
    'empty_streak_to_rest': 3,
    'min_streak_to_backoff': 2,
    'backoff_steps_s': [90, 180, 300, 600],
    'low_value_salience_floor': 0.55,
    'reset_on_high_salience': 0.75,
}}


class TestValueBackoffEffectDriven(unittest.TestCase):
    def setUp(self):
        self.d = _build_daemon()
        import jarvis_inner_thought_daemon as itd
        self.itd = itd

    def test_t1_empty_high_salience_accumulates(self):
        # 反刍: kind=empty(actionable=none) + 自评 sal=0.85 高分. 旧逻辑会被 0.85 reset;
        # effect-driven 下应累积 streak → 退避 (无视自评分)。
        with patch.object(self.itd, '_load_saturation_config', return_value=_VB_CFG):
            self.d._low_value_streak = 0
            r1 = self.d._update_value_backoff(_thought('none', 0.85))
            self.assertEqual(self.d._low_value_streak, 1)
            self.assertEqual(r1, 0)  # < min_streak(2) → 还不退避
            r2 = self.d._update_value_backoff(_thought('none', 0.85))
            self.assertEqual(self.d._low_value_streak, 2)
            self.assertEqual(r2, 90)  # steps[0]
            r3 = self.d._update_value_backoff(_thought('none', 0.85))
            self.assertEqual(self.d._low_value_streak, 3)
            self.assertEqual(r3, 180)  # steps[1] — 反刍被真正退避 (旧逻辑做不到)

    def test_t2_discharge_resets(self):
        # 真放电 (actionable 非 none + done) → kind != empty → reset 回快思考。
        with patch.object(self.itd, '_load_saturation_config', return_value=_VB_CFG):
            self.d._low_value_streak = 3
            r = self.d._update_value_backoff(
                _thought('propose_stance', 0.6, done=True))
            self.assertEqual(self.d._low_value_streak, 0)
            self.assertEqual(r, 0)

    def test_t3_should_speak_resets(self):
        # should_speak=True (放电进语音) → reset, 即便 actionable=none。
        with patch.object(self.itd, '_load_saturation_config', return_value=_VB_CFG):
            self.d._low_value_streak = 3
            r = self.d._update_value_backoff(
                _thought('none', 0.85, should_speak=True))
            self.assertEqual(self.d._low_value_streak, 0)
            self.assertEqual(r, 0)

    def test_t4_legacy_high_salience_resets(self):
        # 回退档: value_by_effect_not_salience=False → 高 sal 仍 reset (旧行为不破)。
        legacy = {'value_backoff': dict(_VB_CFG['value_backoff'],
                                        value_by_effect_not_salience=False)}
        with patch.object(self.itd, '_load_saturation_config', return_value=legacy):
            self.d._low_value_streak = 2
            r = self.d._update_value_backoff(_thought('none', 0.85))
            self.assertEqual(self.d._low_value_streak, 0)  # 0.85 >= 0.75 → 旧 reset
            self.assertEqual(r, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
