# -*- coding: utf-8 -*-
"""[wakeup-line3-alarm-bypass / 2026-06-08] alarm-style commitment bypass 闸2(yield)+
闸3(publish_only) → 到点真 push __NUDGE__. 修叫醒失败 bug (线3).

真因: β.6 把 CommitmentWatcher 退 publish_only, 闹钟到点交思考脑自决 → Sir afk_deep
没人发声 → 漏叫. 方案 P: alarm-style 同时 bypass 闸2(:2247 should_yield) + 闸3(:2287
publish_only), 各加 and not _is_alarm_style_commitment. 复用现有判定, 不收紧不新写.

覆盖 (顾问三命门 + 反证):
  改前红/改后绿: 由 git 对照 (本测试验改后绿 = push 被调)
  T_green     : alarm 承诺 + publish_only → push_command 被调 (__NUDGE__:)
  T_gate2     : alarm + 近 600s proactive nudge (should_yield=True) → bypass 闸2 → push 被调
  T_afk       : alarm + Sir AFK 600s + publish_only → 双 bypass → push 被调
  T_negA      : 提醒我喝水 (非 alarm) + publish_only → 不 push (仍 publish_only)
  T_negB1     : 我11点睡觉 → 不命中 alarm → 不 push
  T_negB2     : 导出完成提醒我 → 不命中 alarm → 不 push
  T_negC      : 番茄钟 author=jarvis → 不命中 alarm → 不 push
  T_vocab     : 8 alarm vocab 全 True; 喝水/睡觉/番茄钟 全 False
  T_gate1     : 施工首验 — can_speak(is_urgent=True) 对 commitment_check 放行 (非 sleep_mode)
  线1         : 见 _test ... intent_router unknown_intent → tool_intent_unresolved sal=0.9
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


def _install_fake_win32api(idle_seconds: float):
    """注入 fake win32api 控制 idle (GetTickCount - GetLastInputInfo = idle_ms)."""
    fake = types.ModuleType("win32api")
    fake.GetTickCount = lambda: int(idle_seconds * 1000)
    fake.GetLastInputInfo = lambda: 0
    sys.modules["win32api"] = fake


def _mk_cw(idle_seconds: float = 5.0, gate_can_speak: bool = True):
    """构造 CommitmentWatcher + fake worker + fake gate. idle 控 AFK 分支。"""
    _install_fake_win32api(idle_seconds)
    from jarvis_commitment_watcher import CommitmentWatcher

    worker = MagicMock()
    worker.push_command = MagicMock()

    gate = MagicMock()
    gate.can_speak = MagicMock(return_value=gate_can_speak)
    gate.mark_spoke = MagicMock()

    cw = CommitmentWatcher(worker, nudge_gate=gate)
    cw.jarvis = None
    return cw, worker, gate


def _commitment(desc, src="", overdue_min=5):
    return {
        "db_id": 44,
        "deadline_ts": time.time() - overdue_min * 60,
        "description": desc,
        "source_text": src,
        "grace_minutes": 2,
        "nudged": False,
        "author": "jarvis",
    }


class _Patches:
    """统一 monkeypatch read_gate_mode + should_yield + event_bus。"""

    def __init__(self, gate_mode="publish_only", should_yield=False):
        self.gate_mode = gate_mode
        self.should_yield = should_yield
        self._orig = {}

    def __enter__(self):
        import jarvis_utils
        self._orig["read_gate_mode"] = jarvis_utils.read_gate_mode
        jarvis_utils.read_gate_mode = lambda name: (
            self.gate_mode if name == "CommitmentWatcher" else "publish_only")
        # event_bus → MagicMock (publish 不报错)
        self._orig["get_event_bus"] = jarvis_utils.get_event_bus
        self._bus = MagicMock()
        jarvis_utils.get_event_bus = lambda: self._bus
        # nudge_coordination yield
        import jarvis_nudge_coordination as nc
        self._orig["_yield"] = nc.should_yield_to_recent_proactive_nudge
        self._orig["_skip"] = nc.publish_proactive_nudge_skipped
        nc.should_yield_to_recent_proactive_nudge = (
            lambda **kw: (self.should_yield, "test_yield_reason"))
        nc.publish_proactive_nudge_skipped = lambda **kw: None
        return self

    def __exit__(self, *a):
        import jarvis_utils
        jarvis_utils.read_gate_mode = self._orig["read_gate_mode"]
        jarvis_utils.get_event_bus = self._orig["get_event_bus"]
        import jarvis_nudge_coordination as nc
        nc.should_yield_to_recent_proactive_nudge = self._orig["_yield"]
        nc.publish_proactive_nudge_skipped = self._orig["_skip"]
        return False


class TestAlarmBypass(unittest.TestCase):
    def test_green_alarm_publish_only_pushes(self):
        """改后绿: alarm 承诺 + publish_only → push_command 被调 __NUDGE__:。"""
        cw, worker, gate = _mk_cw()
        c = _commitment("I shall wake you @ 07:00", src="明天早上7点叫我起床")
        with _Patches(gate_mode="publish_only", should_yield=False):
            cw._dispatch_commitment_nudge(c)
        worker.push_command.assert_called_once()
        payload = worker.push_command.call_args[0][0]
        self.assertTrue(payload.startswith("__NUDGE__:"),
                        "alarm 应 push __NUDGE__")

    def test_gate2_yield_bypassed_by_alarm(self):
        """P 命门: alarm + 近 600s proactive nudge (should_yield=True) → bypass 闸2 → push。"""
        cw, worker, gate = _mk_cw()
        c = _commitment("I shall wake you @ 07:00", src="叫我起床")
        with _Patches(gate_mode="publish_only", should_yield=True):
            cw._dispatch_commitment_nudge(c)
        worker.push_command.assert_called_once()
        self.assertTrue(worker.push_command.call_args[0][0].startswith("__NUDGE__:"))

    def test_afk_coexist_alarm_pushes(self):
        """AFK 共存: alarm + Sir AFK 600s + publish_only → 双 bypass → push。"""
        cw, worker, gate = _mk_cw(idle_seconds=600.0)
        c = _commitment("wake me at 7", src="起床")
        with _Patches(gate_mode="publish_only", should_yield=False):
            cw._dispatch_commitment_nudge(c)
        worker.push_command.assert_called_once()

    def test_negA_normal_commitment_still_publish_only(self):
        """反证A: 提醒我喝水 (非 alarm) + publish_only → 不 push。"""
        cw, worker, gate = _mk_cw()
        c = _commitment("提醒我喝水", src="记得喝水")
        with _Patches(gate_mode="publish_only", should_yield=False):
            cw._dispatch_commitment_nudge(c)
        worker.push_command.assert_not_called()

    def test_negB_boundary_words_not_alarm(self):
        """反证B: 我11点睡觉 / 导出完成提醒我 → 不命中 alarm → 不 push。"""
        for desc in ("我11点睡觉", "导出完成提醒我"):
            cw, worker, gate = _mk_cw()
            c = _commitment(desc, src=desc)
            with _Patches(gate_mode="publish_only", should_yield=False):
                cw._dispatch_commitment_nudge(c)
            worker.push_command.assert_not_called()

    def test_negC_pomodoro_author_jarvis_not_alarm(self):
        """反证C: 番茄钟 author=jarvis → 不命中 alarm → 仍 publish_only 不 push (β.6 本意保住)。"""
        cw, worker, gate = _mk_cw()
        c = _commitment("番茄钟 02:43", src="番茄钟")
        with _Patches(gate_mode="publish_only", should_yield=False):
            cw._dispatch_commitment_nudge(c)
        worker.push_command.assert_not_called()

    def test_negA_yield_normal_still_yields(self):
        """反证: 非 alarm + should_yield=True → 仍 yield (不 push)。闸2 对普通承诺逐字不变。"""
        cw, worker, gate = _mk_cw()
        c = _commitment("提醒我喝水", src="喝水")
        with _Patches(gate_mode="publish_only", should_yield=True):
            cw._dispatch_commitment_nudge(c)
        worker.push_command.assert_not_called()


class TestAlarmVocabReuse(unittest.TestCase):
    def test_vocab_all_true(self):
        cw, _, _ = _mk_cw()
        for kw in ("wake", "alarm", "起床", "叫醒", "叫我", "闹钟", "睡醒", "清醒"):
            self.assertTrue(cw._is_alarm_style_commitment({"description": f"x{kw}y"}),
                            f"{kw} 应命中 alarm")

    def test_vocab_negatives_false(self):
        cw, _, _ = _mk_cw()
        for desc in ("提醒我喝水", "我11点睡觉", "番茄钟 02:43", "导出完成提醒我"):
            self.assertFalse(cw._is_alarm_style_commitment({"description": desc}),
                             f"{desc} 不应命中 alarm")


class TestGate1CanSpeakFirstVerify(unittest.TestCase):
    """施工首验: 闸1 can_speak(is_urgent=True, commitment_check) 在非 sleep_mode 放行。

    用真实 NudgeGate (publish_only 默认 vocab), 验 commitment_check 在无 freeze/sleep
    时 can_speak 返 True (= 不拦 alarm)。这是方案 P 成立的前提。
    """

    def test_can_speak_passes_commitment_check_non_sleep(self):
        from jarvis_sentinels import NudgeGate
        gate = NudgeGate()
        # 非 freeze / 非 sleep_mode 默认态
        ok = gate.can_speak("guardian", is_urgent=True, nudge_type="commitment_check")
        self.assertTrue(ok, "闸1: 非 sleep_mode 时 commitment_check 应放行 (方案 P 前提)")


class TestLine1IntentRouterReport(unittest.TestCase):
    """线1: unknown_intent → event_bus publish tool_intent_unresolved sal=0.9。"""

    def test_unknown_intent_publishes_high_salience(self):
        from jarvis_intent_router import IntentRouter, IntentCall
        bus = MagicMock()
        bus.publish = MagicMock()
        router = IntentRouter(fast_call_executor=None, event_bus=bus)
        # 'Wake up Sir' 不在 intent_map, 且无 '/' → unknown_intent
        call = IntentCall(intent_id="Wake up Sir", args={}, raw_json='{"intent":"Wake up Sir"}')
        result = router.route_and_invoke(call)
        self.assertEqual(result["reason"], "unknown_intent")
        # 应有一条 tool_intent_unresolved publish (sal 0.9)
        found = None
        for c in bus.publish.call_args_list:
            if c.kwargs.get("etype") == "tool_intent_unresolved":
                found = c
                break
        self.assertIsNotNone(found, "unknown_intent 应 publish tool_intent_unresolved")
        self.assertEqual(found.kwargs.get("salience"), 0.9)
        self.assertEqual(found.kwargs["metadata"]["intent_id"], "Wake up Sir")


if __name__ == "__main__":
    unittest.main(verbosity=2)
