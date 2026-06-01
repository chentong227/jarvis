# -*- coding: utf-8 -*-
"""[BUG FIX / Sir 2026-05-29 07:07 真痛] directive 绑架 + 旁路语误触发 双修.

Sir 真测 runtime log 暴露双重 bug:
1. directive 绑架: 思考脑 compose 的 directive (cursor_payment) TTL 5min 内每轮
   重复注入主脑 prompt top → Sir 问 IPAP 主脑连答 cursor_payment 3 次跑题.
   根因: get_active_directive 只 TTL check 不消费. 修复: chat_bypass 注入后即 clear.
2. 旁路语误触发: Sir afk 回来 Jarvis greeting → 90s focus lock → Sir 转头跟妈妈
   说话 ("睡觉关灯吗") 落 directness 灰区 0.5 → "仍触发" → Jarvis 误响应跑题.
   根因: nudge focus 期间灰区 (0.3-0.6) 无条件触发. 修复 (方案A 精准追踪):
   nudge 主动开 focus 期间 Sir 未明确回应过 → 灰区静默; Sir 明确对 Jarvis
   (>=0.6) → 触发 + 清 pending_ack 转正常对话 (灰区恢复 = 不小心翼翼).

测试覆盖 (12 testcase):
directive 一次性消费 (2):
  D1 注入后 clear → 第二次 get None (防 5min 重复注入绑架)
  D2 clear 后思考脑可 re-compose 新 directive
方案A grayzone gate 决策 (_evaluate_focus_directness, 8):
  GZ1 <0.3 → 旁路语丢弃
  GZ2 灰区 0.5 + pending_ack=True → 静默 (nudge focus 未 ack)
  GZ3 灰区 0.5 + pending_ack=False → 触发 (Sir 已在对话)
  GZ4 >=0.6 + pending_ack=True → 触发 + just_acked
  GZ5 >=0.6 + pending_ack=False → 触发
  GZ6 ack side-effect: GZ4 后 _nudge_focus_pending_ack 变 False
  GZ7 边界 0.3 (灰区下界) + pending_ack → 静默
  GZ8 边界 0.6 (明确下界) + pending_ack → 触发 + ack
状态机集成 (2):
  SM1 nudge focus 全流程: pending → 灰区静默 → 明确ack → 灰区恢复触发
  SM2 wake 路径: pending_ack=False → 灰区直接触发 (不小心翼翼)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_fresh_track():
    """构 fresh InnerVoiceTrack (隔离 singleton + disable jsonl persist)."""
    from jarvis_inner_voice_track import InnerVoiceTrack
    track = InnerVoiceTrack()
    with track._lock:
        track._buffer.clear()
    if hasattr(track, '_persist_entry'):
        track._persist_entry = lambda _e: None
    track.clear_active_directive()
    return track


def _make_voice_thread(pending_ack=False):
    """构 VoiceListenThread (不调 __init__, 只设 gate 字段供纯逻辑测)."""
    from jarvis_voice_listen_thread import VoiceListenThread
    vt = VoiceListenThread.__new__(VoiceListenThread)
    vt._nudge_focus_pending_ack = pending_ack
    return vt


class TestDirectiveOneShot(unittest.TestCase):
    """directive 一次性消费 (防 5min 重复注入绑架主脑)."""

    def test_D1_consumed_after_inject(self):
        # 模拟 chat_bypass: 思考脑 set → 主脑 get (注入) → clear (消费)
        track = _make_fresh_track()
        track.set_thinking_brain_directive(
            text='inform Sir about cursor payment', ttl_min=5,
            composed_by_thought_id='th_2026',
        )
        # turn 1: 主脑读到 directive (注入 prompt)
        d1 = track.get_active_directive()
        self.assertIsNotNone(d1)
        # 🆕 注入后即消费 (chat_bypass 修复)
        track.clear_active_directive()
        # turn 2/3: 不再注入 (一次性, 防绑架跑题)
        self.assertIsNone(track.get_active_directive())
        self.assertIsNone(track.get_active_directive())

    def test_D2_recompose_after_consume(self):
        # 消费后思考脑下个 tick 仍可 re-compose (若真需要)
        track = _make_fresh_track()
        track.set_thinking_brain_directive(text='first directive')
        track.clear_active_directive()  # 消费
        self.assertIsNone(track.get_active_directive())
        # 思考脑 re-compose
        ok = track.set_thinking_brain_directive(text='second directive')
        self.assertTrue(ok)
        d = track.get_active_directive()
        self.assertIsNotNone(d)
        self.assertEqual(d['text'], 'second directive')


class TestGrayzoneGateDecision(unittest.TestCase):
    """方案A _evaluate_focus_directness 决策 (纯逻辑)."""

    def test_GZ1_bypass_below_03(self):
        vt = _make_voice_thread(pending_ack=True)
        trigger, is_gray, reason, acked = vt._evaluate_focus_directness(0.2)
        self.assertFalse(trigger)
        self.assertFalse(is_gray)
        self.assertEqual(reason, '旁路语')
        self.assertFalse(acked)

    def test_GZ2_grayzone_now_triggers_to_main_brain(self):
        # [Sir 2026-05-31 00:24 "过分严格了" 治本] 灰区不再 ASR 硬静默 → 触发交主脑自决
        vt = _make_voice_thread(pending_ack=True)
        trigger, is_gray, reason, acked = vt._evaluate_focus_directness(0.5)
        self.assertTrue(trigger)  # 灰区交主脑判 (不再 ASR 层静默 — Sir '洗了个澡'被吞)
        self.assertTrue(is_gray)
        self.assertEqual(reason, '')
        self.assertFalse(acked)  # 灰区不算明确 ack (>=0.6 才 clear pending)

    def test_GZ3_grayzone_triggers_when_not_pending(self):
        vt = _make_voice_thread(pending_ack=False)
        trigger, is_gray, reason, acked = vt._evaluate_focus_directness(0.5)
        self.assertTrue(trigger)  # Sir 已在对话, 灰区触发 (不小心翼翼)
        self.assertTrue(is_gray)
        self.assertEqual(reason, '')

    def test_GZ4_explicit_triggers_and_acks(self):
        vt = _make_voice_thread(pending_ack=True)
        trigger, is_gray, reason, acked = vt._evaluate_focus_directness(0.8)
        self.assertTrue(trigger)
        self.assertFalse(is_gray)
        self.assertTrue(acked)  # 首次明确回应

    def test_GZ5_explicit_triggers_no_pending(self):
        vt = _make_voice_thread(pending_ack=False)
        trigger, is_gray, reason, acked = vt._evaluate_focus_directness(0.8)
        self.assertTrue(trigger)
        self.assertFalse(acked)  # 本来就没 pending

    def test_GZ6_ack_side_effect_clears_pending(self):
        vt = _make_voice_thread(pending_ack=True)
        vt._evaluate_focus_directness(0.8)
        # side-effect: pending_ack 被清 (Sir 明确回应 → 转正常对话)
        self.assertFalse(vt._nudge_focus_pending_ack)

    def test_GZ7_boundary_03_now_triggers(self):
        # [Sir 2026-05-31 00:24] 0.3 灰区下界 → 触发 (交主脑判, 不再静默)
        vt = _make_voice_thread(pending_ack=True)
        trigger, is_gray, _, _ = vt._evaluate_focus_directness(0.3)
        self.assertTrue(trigger)
        self.assertTrue(is_gray)

    def test_GZ8_boundary_06_explicit_acks(self):
        vt = _make_voice_thread(pending_ack=True)
        trigger, is_gray, _, acked = vt._evaluate_focus_directness(0.6)
        self.assertTrue(trigger)  # 0.6 是明确下界 → 触发
        self.assertFalse(is_gray)
        self.assertTrue(acked)


class TestGrayzoneStateMachine(unittest.TestCase):
    """方案A 完整状态机流程 (Sir 真实场景)."""

    def test_SM1_grayzone_routes_to_main_brain_not_asr_silenced(self):
        # [Sir 2026-05-31 00:24 "过分严格了" 治本] return_greeting 后 Sir 灰区回应
        # ("洗了个澡，精神了一点" 真机 0.5) 不再被 ASR 静默 → 触发交主脑自决
        # (主脑看上下文 + multi_person/ambient directive 判 engage vs silent).
        vt = _make_voice_thread(pending_ack=True)  # nudge 开 focus
        t1, is_gray1, reason1, _ = vt._evaluate_focus_directness(0.5)
        self.assertTrue(t1, "Sir 对招呼的灰区回应不该被 ASR 静默")
        self.assertTrue(is_gray1)
        self.assertEqual(reason1, '')
        # Sir 明确对 Jarvis (>=0.6) → 触发 + ack (转正常对话)
        t2, _, _, acked2 = vt._evaluate_focus_directness(0.8)
        self.assertTrue(t2)
        self.assertTrue(acked2)
        # 后续灰区仍触发
        t3, is_gray3, _, _ = vt._evaluate_focus_directness(0.5)
        self.assertTrue(t3)
        self.assertTrue(is_gray3)

    def test_SM2_wake_path_grayzone_triggers(self):
        # 场景: Sir 主动喊 Jarvis 唤醒 (pending_ack=False) → 灰区直接触发
        vt = _make_voice_thread(pending_ack=False)  # wake 路径
        t1, is_gray, _, _ = vt._evaluate_focus_directness(0.5)
        self.assertTrue(t1)  # 灰区也触发 (Sir 旧诉求"不小心翼翼")
        self.assertTrue(is_gray)

    def test_SM3_sir_real_case_shower_reply_not_silenced(self):
        # [Sir 2026-05-31 00:24 真机] greeting 后 Sir '嗯，是的，洗了个澡，精神了一点'
        # 真机 score=0.5 空 breakdown 被灰区静默吞掉 (Sir 直接回应招呼却被无视).
        # 验证: classify → 灰区, evaluate → 触发 (交主脑, 不再 ASR 误杀).
        from jarvis_voice_listen_thread import VoiceListenThread
        vt = VoiceListenThread.__new__(VoiceListenThread)
        vt._nudge_focus_pending_ack = True
        score, breakdown = vt.classify_jarvis_directness(
            '嗯，是的，洗了个澡，精神了一点')
        self.assertTrue(0.3 <= score < 0.6,
            f"应落灰区 (真机 0.5, 无 directness 关键字), got {score}")
        trigger, is_gray, reason, _ = vt._evaluate_focus_directness(score)
        self.assertTrue(trigger, "Sir 对招呼的灰区回应不该被 ASR 静默 (真痛回归)")
        self.assertEqual(reason, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
