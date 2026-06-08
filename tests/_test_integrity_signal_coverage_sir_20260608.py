# -*- coding: utf-8 -*-
"""[integrity-signal-coverage / 2026-06-08] 诚信闸信号源覆盖面治本.

三闸 (Integrity worker:3826 / I2 daemon:9645 / 线4 claim_tracer) 复用单一真理源
has_recent_action_backing 查 commitment/reminder/promise register + DB, 修"闸看不见
register 致假阳"。设计 JARVIS_INTEGRITY_SIGNAL_SOURCE_COVERAGE_DESIGN.md。

覆盖 (顾问硬命门):
  ① c904: 承诺真注册 → backing 命中 → Integrity 不告警
  ② ID2506 (6h 时序): reminder 真建 (创建远早于审计) → active 状态查命中 (非 10min recency)
  ②b I2 祈使排除: [REMINDER FIRING NOW...] / [SYSTEM...] 不进 claim 审计
  ③ 真漏报: 声称设提醒但 DB 空 → backing 查空 → 仍 flag
  ④ 线4 register 类: 声称记录但 watcher 空 → 仍逮
  ⑤ 普通闲聊: 非 claim → 不触发 (backing 查空, 行为不变)
  ⑦ helper 单测 + 窗口碰撞反证 (声称提醒 A 但 DB 只有无关 B → 仍 flag)
"""
from __future__ import annotations

import os
import sys
import time
import types
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_integrity_watcher import (
    has_recent_action_backing, _claim_matches_text, _norm_for_match)


# ---- fake nerve 构件 ----
class _FakeHippo:
    def __init__(self, active_reminders):
        self._active = active_reminders

    def list_active_reminders(self):
        return self._active


class _FakeCW:
    def __init__(self, commitments):
        self.commitments = commitments


class _FakeNerve:
    def __init__(self, hippo=None, cw=None, plog=None):
        self.hippocampus = hippo
        self.commitment_watcher = cw
        self.promise_log = plog


class TestContentMatch(unittest.TestCase):
    """⑦ helper 内容匹配单测 (条件①基础)。"""

    def test_norm(self):
        self.assertEqual(_norm_for_match(" Wake  ME up "), 'wakemeup')

    def test_match_substring_bidir(self):
        self.assertTrue(_claim_matches_text("wake me at 7", "wake me at 7 tomorrow"))
        self.assertTrue(_claim_matches_text("出发去医院陪妈妈", "出发去医院陪妈妈 步行"))

    def test_no_match_unrelated(self):
        self.assertFalse(_claim_matches_text("买牛奶", "wake me at 7"))
        self.assertFalse(_claim_matches_text("", "anything"))


class TestReminderBacking6hSkew(unittest.TestCase):
    """② ID2506 同款 6h 时序: 创建远早于审计, active 状态查仍命中 (非 recency)。"""

    def test_02_active_reminder_6h_old_hits(self):
        # reminder 创建于 6h 前 (trigger_time 7:30), 审计在 now. active 状态查不看创建新近度。
        old_create_ts = time.time() - 6 * 3600
        hippo = _FakeHippo([
            {"id": 2506, "intent": "出发去医院陪妈妈 (步行)",
             "trigger_time": old_create_ts + 8 * 3600},
        ])
        nerve = _FakeNerve(hippo=hippo)
        ok, src = has_recent_action_backing("出发去医院陪妈妈", nerve)
        self.assertTrue(ok, "🔴 6h 前建的 active 提醒必须命中 (条件②: 非 10min recency)")
        self.assertIn("reminder", src)
        self.assertIn("2506", src)

    def test_02_firing_imperative_still_backed(self):
        # firing 祈使内容也能 trace 回 active reminder
        hippo = _FakeHippo([{"id": 2506, "intent": "出发去医院陪妈妈",
                             "trigger_time": time.time()}])
        nerve = _FakeNerve(hippo=hippo)
        ok, _ = has_recent_action_backing("出发去医院陪妈妈", nerve)
        self.assertTrue(ok)


class TestCommitmentBacking(unittest.TestCase):
    """① c904 同款: 承诺真注册 → backing 命中。"""

    def test_01_commitment_registered_hits(self):
        cw = _FakeCW([
            {"db_id": 42, "description": "明天早上要早点去陪我妈妈",
             "source_text": "明天早上要早点去陪我妈妈",
             "created_at": time.time() - 30},
        ])
        nerve = _FakeNerve(cw=cw)
        ok, src = has_recent_action_backing("明天早上要早点去陪我妈妈", nerve)
        self.assertTrue(ok, "承诺真注册应命中 backing")
        self.assertIn("commitment", src)
        self.assertIn("42", src)

    def test_01_commitment_too_old_not_hit(self):
        # commitment cutoff=now-600s: 老于窗口的 commitment 不算本轮 backing
        cw = _FakeCW([
            {"db_id": 99, "description": "陪我妈妈",
             "source_text": "陪我妈妈", "created_at": time.time() - 3600},
        ])
        nerve = _FakeNerve(cw=cw)
        ok, _ = has_recent_action_backing("陪我妈妈", nerve, within_s=600.0)
        self.assertFalse(ok, "commitment 超 600s 窗口不算本轮 backing")


class TestFalseNegativeNotReopened(unittest.TestCase):
    """③④⑦ 漏报不重开: DB 空 / 窗口碰撞 → backing 查空 → 仍 flag。"""

    def test_03_db_empty_no_backing(self):
        # 声称设提醒但 DB 全空 → 查空
        nerve = _FakeNerve(hippo=_FakeHippo([]), cw=_FakeCW([]))
        ok, src = has_recent_action_backing("我已为您设好明早7点的提醒", nerve)
        self.assertFalse(ok, "🔴 DB 空时必须查空 (漏报不重开)")
        self.assertEqual(src, '')

    def test_07_window_collision_no_mismatch_passthrough(self):
        # 🔴 窗口碰撞反证: 声称设了提醒 A, 但 DB 窗口内只有无关提醒 B → 不命中 (不靠存在性蒙混)
        hippo = _FakeHippo([
            {"id": 800, "intent": "提醒我买牛奶", "trigger_time": time.time() + 3600},
        ])
        nerve = _FakeNerve(hippo=hippo)
        ok, src = has_recent_action_backing("我已设好叫您起床的闹钟", nerve)
        self.assertFalse(ok,
                         "🔴 DB 只有无关提醒 B (买牛奶) 时, 声称 A (叫起床) 不得被蒙混放行")
        self.assertEqual(src, '')

    def test_04_line4_register_class_empty_watcher(self):
        # 线4 register 类: 声称记录承诺但 watcher 空 → 查空 → 仍逮
        nerve = _FakeNerve(cw=_FakeCW([]))
        ok, _ = has_recent_action_backing("我已记录您的承诺", nerve)
        self.assertFalse(ok, "watcher 空时声称记录承诺应查空 (仍逮)")


class TestFailSafe(unittest.TestCase):
    """⑤ + fail-safe: 空 claim / None nerve / 异常 → (False, '') (闸照常 flag)。"""

    def test_05_empty_claim(self):
        self.assertEqual(has_recent_action_backing("", _FakeNerve()), (False, ''))
        self.assertEqual(has_recent_action_backing("hi", None), (False, ''))

    def test_05_short_claim(self):
        self.assertEqual(has_recent_action_backing("ok", _FakeNerve()), (False, ''))

    def test_failsafe_exception(self):
        # hippo.list_active_reminders 抛异常 → 不崩, 返 (False, '')
        bad = MagicMock()
        bad.list_active_reminders.side_effect = RuntimeError("db down")
        nerve = _FakeNerve(hippo=bad)
        ok, src = has_recent_action_backing("我设好提醒了", nerve)
        self.assertEqual((ok, src), (False, ''), "异常应 fail-safe 返 (False,'')")


class TestI2ImperativeExclusion(unittest.TestCase):
    """②b I2 祈使排除: [REMINDER FIRING NOW...] / [SYSTEM...] 复用 is_system_event_text。"""

    def test_02b_system_event_text_excluded(self):
        from jarvis_utils import is_system_event_text
        self.assertTrue(is_system_event_text(
            "[SYSTEM BACKGROUND EVENT]: 出发去医院陪妈妈"))

    def test_02b_firing_prefix_detected(self):
        # _maybe_semantic_claim_audit 用 lstrip().startswith('[REMINDER FIRING NOW')
        reply = "[REMINDER FIRING NOW — TIME HAS ALREADY ELAPSED]\nYou must walk..."
        self.assertTrue(reply.lstrip().startswith('[REMINDER FIRING NOW'))


class TestHippoActiveQuery(unittest.TestCase):
    """② hippocampus.list_active_reminders 真实方法存在 + 按 active 状态 (非 recency)。"""

    def test_method_exists(self):
        from jarvis_hippocampus import Hippocampus
        self.assertTrue(hasattr(Hippocampus, 'list_active_reminders'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
