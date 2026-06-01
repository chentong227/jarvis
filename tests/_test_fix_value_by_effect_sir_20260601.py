# -*- coding: utf-8 -*-
"""[Sir 2026-06-01 真意 — 价值=放电效果, 非自评 salience / 杀"亢奋却空"的 filler]

Sir 真机看到思考脑死循环反刍 (sal=0.85 / kind=empty / 每 60s / 内容全是"我该对 Sir
更简洁/更 nuanced"). 根因链:
  1. value_backoff 用 salience 判值: sal=0.85 ≥ reset_on_high_salience(0.75) →
     每条都 reset streak → 永不退避。反刍最爱给自己打高分, salience 不可信。
  2. body_delta_wake: active 对话时 Weaver 把同一话题反复织进体 → 永远 has_fresh_delta
     → 撤销 backoff 回快 → 60s 反刍不止。

Sir 三元框 (纠正"每个思考配行为=再胁迫"): 思考要么真**放电** (discharge:
solve/shape_next/adjust_self/want/relate, kind != empty), 要么真**休息** (rest,
头等公民); 要杀的只有中间那坨 **filler = 亢奋却空** (kind=empty + 不放电 + 不休息)。

本 commit (Layer 1):
  - value_backoff 改 **effect-driven** (value_by_effect_not_salience): 真放电或
    should_speak → reset; 不放电 → streak++ (无视自评 salience)。
  - 连续空想达 empty_streak_to_rest → 转真休息 (_resting, 被体动静/Sir 唤醒)。
  - body_delta_wake 加闸: 已连续失败放电 (streak≥阈) → **不**撤退避 (啃不动的 delta
    不再拉我回快)。

覆盖:
  T1 kind=empty + sal=0.85 连续 → streak 累积 (不被高自评 reset) + 退避递增 [回归核心]
  T2 真放电 (effect) → streak reset, 不退避
  T3 should_speak=True → streak reset (放电进语音)
  T4 达 min_streak → 返退避 > 0; 步进只增不减
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
    tmp = os.path.join(tempfile.gettempdir(), f'valeffect_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk(actionable='none', sal=0.85, should_speak=False):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id='t', ts=time.time(), ts_iso='2026-06-01T00:00:00',
        category='B', thought='I should be more concise with Sir.',
        salience=sal, actionable=actionable, should_speak=should_speak,
    )


class TestValueByEffect(unittest.TestCase):

    def test_t1_empty_high_salience_accumulates(self):
        # 回归核心: kind=empty (actionable=none) + sal=0.85 必须**不被** reset
        # (旧 bug: sal>=0.75 → reset → 永不退避 → 反刍不止)
        d = _build_daemon()
        d._low_value_streak = 0
        with patch.object(d, '_infer_actionable_state', return_value='none'):
            i1 = d._update_value_backoff(_mk('none', 0.85))   # streak1 <min → 0
            i2 = d._update_value_backoff(_mk('none', 0.85))   # streak2 → 退避
            i3 = d._update_value_backoff(_mk('none', 0.85))   # streak3 → 更长
        self.assertEqual(d._low_value_streak, 3,
                         '高自评 sal=0.85 的空想不该 reset streak (effect-driven)')
        self.assertGreater(i2, 0, '达 min_streak 应退避')
        self.assertGreaterEqual(i3, i2, '退避只增不减')

    def test_t2_discharge_resets(self):
        # 真放电 (kind != empty) → reset, 回快思考
        d = _build_daemon()
        d._low_value_streak = 5
        with patch.object(d, '_infer_actionable_state', return_value='done'):
            i = d._update_value_backoff(_mk('propose_stance', 0.5))
        self.assertEqual(i, 0)
        self.assertEqual(d._low_value_streak, 0, '真放电应 reset streak')

    def test_t3_should_speak_resets(self):
        # should_speak=True (放电进语音) → reset, 即便 kind=empty
        d = _build_daemon()
        d._low_value_streak = 5
        with patch.object(d, '_infer_actionable_state', return_value='none'):
            i = d._update_value_backoff(_mk('none', 0.5, should_speak=True))
        self.assertEqual(i, 0)
        self.assertEqual(d._low_value_streak, 0)

    def test_t4_backoff_monotonic(self):
        d = _build_daemon()
        d._low_value_streak = 0
        seq = []
        with patch.object(d, '_infer_actionable_state', return_value='none'):
            for _ in range(6):
                seq.append(d._update_value_backoff(_mk('none', 0.9)))
        # 只增不减 (clamp 安全), 末段到顶 step
        for a, b in zip(seq, seq[1:]):
            self.assertLessEqual(a, b, f'退避序列应单调不减: {seq}')
        self.assertGreater(seq[-1], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
