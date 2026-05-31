# -*- coding: utf-8 -*-
"""[Sir 2026-05-31 21:04 真意 — 唤醒需理由 / emergent 去 45s 盲钟]

Sir 真痛: thinking-dehardcode emergent 已开 (退类冷却 + 区放电), 但思考"还在 45s tick
重复想 filler" — 因 45s 仍是**默认醒钟**, 醒不需要理由就空转产 filler。

真意 (势能自转): 思考是势能放电 (solve / reflect / propose / want-capability), 醒该有
**理由**:
  - 体真升起 fresh delta (Weaver 算的张力/新颖, grounded) → attend (45s 此刻是"有理由的快")
  - Sir 紧急 → emergency interrupt 即跟上 (随时注入)
  - 都没有 → 歇到 ambient floor (存在心跳), 不 45s 盲钟

本 commit (emergent reason-gate, legacy 0 变):
  - _emergent_rest_floor(proposed): 体无 fresh delta → 至少歇 floor; 有 → 不动 (attend)
  - evidence-gate skip (settled, emergent) → 歇 floor + _resting (体动静/Sir 提前醒)
  - real-tick resolve (emergent, 无 delta) → 钳到 floor, origin=rest_floor (log 显真 next)
  - log: tick={45}s → woke=<reason> (timeout / body_stir / emergency), 醒有可见理由

测试覆盖:
  T1 _emergent_rest_floor: 无 delta + proposed<floor → floor (歇, 不 45s 盲钟)
  T2 _emergent_rest_floor: 无 delta + proposed>floor → proposed (尊重更长 self-pace)
  T3 _emergent_rest_floor: 有 fresh delta → proposed 不动 (attend, 即便 < floor)
  T4 _emergent_rest_floor: wake_on_body_delta=False → proposed 不动 (vocab 开关)
  T5 skip 路径 emergent + settled → _next=floor + _resting=True (歇, 非 45s 回来再 skip)
  T6 skip 路径 legacy → _next 不变 (0) + 不强制 _resting (老行为 0 变)
  T7 _last_wake_reason 默认 'startup' + 可写 (loop 写真因, log 显 woke=)
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
    tmp = os.path.join(tempfile.gettempdir(),
                       f'emergent_wake_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


class _FakeFocus:
    """has_fresh_delta 桩 — 控制体"有没有理由醒"。"""

    def __init__(self, fresh: bool):
        self._fresh = fresh

    def has_fresh_delta(self, *, min_magnitude: float = 0.0) -> bool:
        return self._fresh


_REST_CFG = {'rest': {'ambient_floor_s': 600,
                      'body_stir_min_magnitude': 0.3,
                      'wake_on_body_delta': True}}


class TestEmergentRestFloor(unittest.TestCase):
    """T1-T4: _emergent_rest_floor 理由门 decision core。"""

    def setUp(self):
        self.d = _build_daemon()
        import jarvis_inner_thought_daemon as itd
        self.itd = itd

    def _call(self, proposed, *, fresh, cfg=None):
        cfg = cfg or _REST_CFG
        with patch.object(self.itd, '_load_saturation_config',
                          return_value=cfg), \
             patch('jarvis_body_focus.get_body_focus',
                   return_value=_FakeFocus(fresh)):
            return self.d._emergent_rest_floor(proposed)

    def test_t1_no_delta_floors_up(self):
        # 体 settled (无理由) + proposed 45s (盲钟) → 至少歇 floor 600
        self.assertEqual(self._call(45, fresh=False), 600)

    def test_t2_no_delta_respects_longer(self):
        # 体 settled + proposed 1800 (已更长, 如 afk) → 不缩短, 尊重 self-pace
        self.assertEqual(self._call(1800, fresh=False), 1800)

    def test_t3_fresh_delta_keeps_attend(self):
        # 体有 fresh delta (有理由 attend) → 45s 节奏不动 (即便 < floor)
        self.assertEqual(self._call(45, fresh=True), 45)

    def test_t4_switch_off_keeps_proposed(self):
        cfg = {'rest': {'ambient_floor_s': 600, 'body_stir_min_magnitude': 0.3,
                        'wake_on_body_delta': False}}
        # vocab 关 wake_on_body_delta → helper 不干预 (回退老行为)
        self.assertEqual(self._call(45, fresh=False, cfg=cfg), 45)


class TestSkipPathRestFloor(unittest.TestCase):
    """T5-T6: evidence-gate skip 路径在 emergent 歇 floor, legacy 0 变。"""

    def setUp(self):
        self.d = _build_daemon()
        import jarvis_inner_thought_daemon as itd
        self.itd = itd

    def _run_skip_tick(self, mode):
        d = self.d
        with patch.object(self.itd, '_thinking_kind_mode', return_value=mode), \
             patch.object(self.itd, '_load_saturation_config',
                          return_value=_REST_CFG), \
             patch('jarvis_body_focus.get_body_focus',
                   return_value=_FakeFocus(False)), \
             patch.object(d, '_classify_sir_state', return_value='active'), \
             patch.object(d, '_compute_free_categories', return_value=['A', 'B']), \
             patch.object(d, '_collect_evidence', return_value={}), \
             patch.object(d, '_maybe_evidence_gate_skip', return_value=True), \
             patch.object(d, '_sweep_ignored_main_replies'), \
             patch.object(d, '_check_active_watch_task_and_publish_vision_refresh'):
            d._tick()

    def test_t5_emergent_skip_rests_to_floor(self):
        self.d._next_tick_interval_s = 0
        self.d._resting = False
        self._run_skip_tick('emergent')
        # settled + emergent → 歇 floor, 标 resting (wait 期间体动静/Sir 提前醒)
        self.assertEqual(self.d._next_tick_interval_s, 600)
        self.assertTrue(self.d._resting)

    def test_t6_legacy_skip_unchanged(self):
        self.d._next_tick_interval_s = 0
        self.d._resting = False
        self._run_skip_tick('legacy')
        # legacy: skip 路径不碰 interval (老行为), 不强制 resting
        self.assertEqual(self.d._next_tick_interval_s, 0)
        self.assertFalse(self.d._resting)


class TestWakeReason(unittest.TestCase):
    """T7: _last_wake_reason 默认 + 可写 (log 显 woke=<理由>)。"""

    def test_t7_wake_reason_field(self):
        d = _build_daemon()
        self.assertEqual(d._last_wake_reason, 'startup')
        d._last_wake_reason = 'body_stir'
        self.assertEqual(d._last_wake_reason, 'body_stir')


if __name__ == '__main__':
    unittest.main(verbosity=2)
