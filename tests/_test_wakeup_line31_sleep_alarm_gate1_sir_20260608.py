# -*- coding: utf-8 -*-
"""[wakeup-line31-sleep-alarm-gate1 / 2026-06-08] 闸1 sleep_mode 闹钟豁免 (方案 a).

线3 让闹钟穿 AFK/yield/publish_only (闸2/闸3); 本片补闸1: can_speak 在 sleep_mode 下
拦 commitment_check → Sir 显式/自动 sleep_mode 时漏叫。方案 a: can_speak 加 is_alarm 参,
sleep 子句加 not is_alarm (alarm 穿 sleep); freeze 检查零改动 (闹钟仍被急停拦, 安全红线)。

覆盖 (顾问硬命门):
  ① sleep + alarm → True (穿 sleep)
  ② sleep + 非 alarm commitment → False (静音保住)
  ②b sleep + 其他 type (hydration/offer_help) 默认 → False (逐字不变)
  ③ freeze + alarm → False (安全必绿, 不准放宽)
  ③b freeze + sleep + alarm → False (freeze 优先)
  ④ idle 不回归 (无 explicit sleep) → True
  ⑤ dispatch 集成 (真 NudgeGate + activate_sleep_mode + 线3 闸2/3 bypass → push 被调)
  ⑥ 向后兼容 (老调用不传 is_alarm 行为不变)
  施工首验: hard + publish_only 两 gate_mode 都验 is_alarm 透传
"""
from __future__ import annotations

import os
import sys
import json
import time
import types
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_sentinels as S


def _gate():
    return S.NudgeGate(cooldown_seconds=90)


class _GateMode:
    """patch read_gate_mode 控 gate_mode (hard / publish_only)。

    用 unittest.mock.patch (而非裸赋值) 防跨测试模块状态泄漏: 裸赋值会把
    jarvis_utils.read_gate_mode 替成 lambda, 破坏其他模块 (如 test_three_centers
    setUpModule) 对同一 target 的 mock.patch save/restore (导致 return_greeting 误判)。
    mock.patch 进出栈式 save/restore, 干净隔离。
    """

    def __init__(self, mode):
        self.mode = mode
        self._p = None

    def __enter__(self):
        from unittest import mock
        self._p = mock.patch('jarvis_utils.read_gate_mode',
                             side_effect=lambda name='NudgeGate': self.mode)
        self._p.start()
        return self

    def __exit__(self, *a):
        if self._p is not None:
            self._p.stop()
            self._p = None
        return False


class TestSleepAlarmGate1(unittest.TestCase):
    def tearDown(self):
        # [整洁隔离 / 2026-06-08] can_speak 通过会写 OfferGuard 类级 _last_offer_ts
        # (跨测试模块共享单例)。重置防泄漏到 test_three_centers 等后续模块
        # (否则 return_greeting 会撞 offer_guard rhythm cooldown 误判)。
        try:
            from jarvis_skill_registry import OfferGuard
            OfferGuard.reset_for_test()
        except Exception:
            pass

    # ---- publish_only gate_mode (默认生产) ----
    def test_01_sleep_alarm_passes_publish_only(self):
        g = _gate()
        g.activate_sleep_mode()
        with _GateMode('publish_only'):
            self.assertTrue(g.can_speak('guardian', is_urgent=True,
                                        nudge_type='commitment_check', is_alarm=True),
                            "sleep + alarm 应穿 (publish_only)")

    def test_02_sleep_non_alarm_blocked_publish_only(self):
        g = _gate()
        g.activate_sleep_mode()
        with _GateMode('publish_only'):
            self.assertFalse(g.can_speak('guardian', is_urgent=True,
                                         nudge_type='commitment_check', is_alarm=False),
                             "sleep + 非 alarm commitment 应仍拦 (静音保住)")

    def test_02b_sleep_other_types_blocked(self):
        g = _gate()
        g.activate_sleep_mode()
        with _GateMode('publish_only'):
            for nt in ('hydration', 'offer_help'):
                self.assertFalse(g.can_speak('companion', nudge_type=nt),
                                 f"sleep + {nt} 默认应拦 (逐字不变)")

    # ---- ③ freeze 安全态 — 闹钟绝不穿 (必绿) ----
    def test_03_freeze_alarm_blocked_publish_only(self):
        g = _gate()
        g.freeze_for(180)
        with _GateMode('publish_only'):
            self.assertFalse(g.can_speak('guardian', is_urgent=True,
                                         nudge_type='commitment_check', is_alarm=True),
                             "🔴 freeze + alarm 必须仍拦 (安全红线)")

    def test_03b_freeze_plus_sleep_alarm_blocked(self):
        g = _gate()
        g.freeze_for(180)
        g.activate_sleep_mode()
        with _GateMode('publish_only'):
            self.assertFalse(g.can_speak('guardian', is_urgent=True,
                                         nudge_type='commitment_check', is_alarm=True),
                             "🔴 freeze 优先于 sleep, alarm 仍拦")

    def test_03_freeze_alarm_blocked_hard(self):
        """施工首验: hard gate_mode 下 freeze+alarm 也拦 (is_alarm 透传 internal)。"""
        g = _gate()
        g.freeze_for(180)
        with _GateMode('hard'):
            self.assertFalse(g.can_speak('guardian', is_urgent=True,
                                         nudge_type='commitment_check', is_alarm=True),
                             "🔴 hard gate_mode freeze+alarm 必须仍拦")

    # ---- 施工首验: hard gate_mode is_alarm 透传 ----
    def test_hard_gate_sleep_alarm_passes(self):
        """hard gate_mode: sleep + alarm → 穿 (确认 is_alarm 真透传到 internal)。"""
        g = _gate()
        g.activate_sleep_mode()
        with _GateMode('hard'):
            # hard 模式走 internal result; sleep + alarm → 不被 sleep 子句拦,
            # is_urgent=True → urgent_override → True
            self.assertTrue(g.can_speak('guardian', is_urgent=True,
                                        nudge_type='commitment_check', is_alarm=True),
                            "hard gate_mode sleep+alarm 应穿 (is_alarm 透传 internal)")

    def test_hard_gate_sleep_non_alarm_blocked(self):
        g = _gate()
        g.activate_sleep_mode()
        with _GateMode('hard'):
            self.assertFalse(g.can_speak('guardian', is_urgent=True,
                                         nudge_type='commitment_check', is_alarm=False),
                             "hard gate_mode sleep+非alarm 应拦")

    # ---- ④ idle 不回归 (无 explicit sleep) ----
    def test_04_idle_no_sleep_alarm_passes(self):
        g = _gate()  # 未 activate_sleep_mode → _sleep_mode=False
        with _GateMode('publish_only'):
            self.assertTrue(g.can_speak('guardian', is_urgent=True,
                                        nudge_type='commitment_check', is_alarm=True),
                            "无 explicit sleep (idle) → 放行 (不回归本 bug 场景)")

    # ---- ⑥ 向后兼容 ----
    def test_06_backward_compat_no_is_alarm(self):
        g = _gate()
        g.activate_sleep_mode()
        with _GateMode('publish_only'):
            # 老调用不传 is_alarm → 默认 False → offer_help 仍拦
            self.assertFalse(g.can_speak('guardian', nudge_type='offer_help'),
                             "老调用 (无 is_alarm) 行为不变")
            # return_greeting 白名单仍放行
            self.assertTrue(g.can_speak('guardian', nudge_type='return_greeting'),
                            "return_greeting 白名单不受影响")


class TestDispatchIntegration(unittest.TestCase):
    """⑤ dispatch 集成: 真 NudgeGate + activate_sleep_mode + 线3 闸2/3 bypass → push 被调。"""

    def tearDown(self):
        try:
            from jarvis_skill_registry import OfferGuard
            OfferGuard.reset_for_test()
        except Exception:
            pass

    def _install_fake_win32api(self, idle_seconds=5.0):
        fake = types.ModuleType("win32api")
        fake.GetTickCount = lambda: int(idle_seconds * 1000)
        fake.GetLastInputInfo = lambda: 0
        sys.modules["win32api"] = fake

    def test_05_sleep_alarm_dispatch_pushes(self):
        self._install_fake_win32api()
        from jarvis_commitment_watcher import CommitmentWatcher

        worker = MagicMock()
        worker.push_command = MagicMock()
        gate = S.NudgeGate(cooldown_seconds=90)
        gate.activate_sleep_mode()  # explicit sleep — 闸1 会拦非 alarm

        cw = CommitmentWatcher(worker, nudge_gate=gate)
        cw.jarvis = None
        c = {
            "db_id": 44, "deadline_ts": time.time() - 300,
            "description": "I shall wake you @ 07:00",
            "source_text": "明天早上7点叫我起床",
            "grace_minutes": 2, "nudged": False, "author": "jarvis",
        }

        # 线3 闸2/3 bypass + 本片闸1 bypass — 全链需 publish_only + yield 都让 alarm 过
        import jarvis_utils
        import jarvis_nudge_coordination as nc
        _orig_rgm = jarvis_utils.read_gate_mode
        _orig_geb = jarvis_utils.get_event_bus
        _orig_yield = nc.should_yield_to_recent_proactive_nudge
        jarvis_utils.read_gate_mode = lambda name: (
            'publish_only' if name == 'CommitmentWatcher' else 'publish_only')
        jarvis_utils.get_event_bus = lambda: MagicMock()
        nc.should_yield_to_recent_proactive_nudge = lambda **kw: (False, '')
        try:
            cw._dispatch_commitment_nudge(c)
        finally:
            jarvis_utils.read_gate_mode = _orig_rgm
            jarvis_utils.get_event_bus = _orig_geb
            nc.should_yield_to_recent_proactive_nudge = _orig_yield

        worker.push_command.assert_called_once()
        self.assertTrue(worker.push_command.call_args[0][0].startswith("__NUDGE__:"),
                        "explicit sleep + alarm → 闸1 穿 → push __NUDGE__")

    def test_05b_sleep_non_alarm_dispatch_no_push(self):
        """反证: explicit sleep + 非 alarm 承诺 → 闸1 拦 → 不 push。"""
        self._install_fake_win32api()
        from jarvis_commitment_watcher import CommitmentWatcher

        worker = MagicMock()
        worker.push_command = MagicMock()
        gate = S.NudgeGate(cooldown_seconds=90)
        gate.activate_sleep_mode()

        cw = CommitmentWatcher(worker, nudge_gate=gate)
        cw.jarvis = None
        c = {
            "db_id": 45, "deadline_ts": time.time() - 300,
            "description": "提醒我喝水", "source_text": "记得喝水",
            "grace_minutes": 2, "nudged": False, "author": "jarvis",
        }
        import jarvis_utils
        import jarvis_nudge_coordination as nc
        _orig_rgm = jarvis_utils.read_gate_mode
        _orig_geb = jarvis_utils.get_event_bus
        _orig_yield = nc.should_yield_to_recent_proactive_nudge
        jarvis_utils.read_gate_mode = lambda name: 'publish_only'
        jarvis_utils.get_event_bus = lambda: MagicMock()
        nc.should_yield_to_recent_proactive_nudge = lambda **kw: (False, '')
        try:
            cw._dispatch_commitment_nudge(c)
        finally:
            jarvis_utils.read_gate_mode = _orig_rgm
            jarvis_utils.get_event_bus = _orig_geb
            nc.should_yield_to_recent_proactive_nudge = _orig_yield

        worker.push_command.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
