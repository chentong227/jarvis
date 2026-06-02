# -*- coding: utf-8 -*-
"""[反刍治本 / Sir 2026-06-02] concern severity 三结构根因回归.

真机数据实证 (body_energy.json + concerns.json): 水/cursor/keyrouter 反刍, 但
Sir 早不提了, 贾维斯也"久没提" — top_energy 6 节点全 novelty=0/drift=0 (纯陈年
standing tension)。根因三条:
  Fix1 自我强化环: ConcernsReflector 扫 jarvis_reply → 贾维斯自己说 "hydration"
        也 +severity → 自己把火点着。治: 只扫 user_input。
  Fix2 不遗忘: severity>0.5 永不过期 + 无半衰期。治: 按"最后真 Sir signal"半衰。
  Fix3 snooze/dismiss 漏电: snoozed/triggers_proactive=False concern 仍喂体张力。
        治: _concern_severity_map 只计 active + triggers_proactive。

覆盖:
  Fix1: T1 只扫 user / T2 jarvis_reply 不再 +severity / T3 vocab 可开回旧
  Fix2: T4 久无 Sir signal → severity 衰 / T5 宽限期内不衰 / T6 Sir signal 刷新锚
        / T7 user_sourced=True 更新锚, False 不更新 / T8 disabled 不衰
  Fix3: T9 snoozed 不喂体张力 / T10 dismiss(triggers_proactive=False) 不喂 / T11 active 喂
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_concerns import ConcernsLedger, Concern, STATE_ACTIVE, STATE_SNOOZED
import jarvis_soul_reflector as sr
from jarvis_relational_manifold import RelationalManifold, make_node_id, KIND_CONCERN
from jarvis_relational_weaver import RelationalWeaver

DAY = 86400.0


# ============================================================
# Fix1 — 自我强化环
# ============================================================
class TestFix1SelfReinforce(unittest.TestCase):
    def _mk_ledger(self, d):
        led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
        led.register(Concern(id="sir_hydration_habit", what_i_watch="water",
                             why_i_care="y", severity=0.5))
        return led

    def test_t1_user_input_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            led = self._mk_ledger(d)
            refl = sr.ConcernsReflector(led)
            with patch.object(sr, "_reflect_scans_jarvis_reply", return_value=False):
                rec = refl.reflect_turn(user_input="记得多喝水", jarvis_reply="", turn_id="t1")
            self.assertIn("sir_hydration_habit", rec, "Sir 说喝水 → 应记 signal")

    def test_t2_jarvis_reply_not_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            led = self._mk_ledger(d)
            refl = sr.ConcernsReflector(led)
            sev_before = led.get("sir_hydration_habit").severity
            # Sir 没提水, 只贾维斯自己回复里有 hydration
            with patch.object(sr, "_reflect_scans_jarvis_reply", return_value=False):
                rec = refl.reflect_turn(
                    user_input="帮我看下代码",
                    jarvis_reply="Of course Sir. Also your hydration target...",
                    turn_id="t2")
            self.assertNotIn("sir_hydration_habit", rec,
                             "贾维斯自己说 hydration 不该 +severity (斩自我强化环)")
            self.assertAlmostEqual(led.get("sir_hydration_habit").severity,
                                   sev_before, places=5)

    def test_t3_vocab_can_reenable(self):
        with tempfile.TemporaryDirectory() as d:
            led = self._mk_ledger(d)
            refl = sr.ConcernsReflector(led)
            with patch.object(sr, "_reflect_scans_jarvis_reply", return_value=True):
                rec = refl.reflect_turn(
                    user_input="帮我看下代码",
                    jarvis_reply="your hydration target",
                    turn_id="t3")
            self.assertIn("sir_hydration_habit", rec,
                          "scan_jarvis_reply=true → 回旧行为 (Sir 可开)")


# ============================================================
# Fix2 — severity 时间半衰期
# ============================================================
class TestFix2SeverityDecay(unittest.TestCase):
    def _cfg(self, **kw):
        base = {'severity_decay_enabled': True, 'severity_half_life_days': 7.0,
                'severity_decay_grace_days': 2.0, 'severity_decay_floor': 0.0}
        base.update(kw)
        return base

    def test_t4_stale_concern_decays(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=1.0)
            c.last_user_signal_ts = time.time() - 9 * DAY  # 9 天前 Sir 提过
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._cfg()):
                led.apply_decay()
            # age=9d, grace=2d → 衰 7d = 1 个半衰期 → ~0.5
            self.assertLess(led.get("x").severity, 0.6,
                            "9天没真 Sir signal → severity 应半衰")
            self.assertGreater(led.get("x").severity, 0.4)

    def test_t5_within_grace_no_decay(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=1.0)
            c.last_user_signal_ts = time.time() - 1 * DAY  # 1 天前 (< grace 2d)
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._cfg()):
                led.apply_decay()
            self.assertAlmostEqual(led.get("x").severity, 1.0, places=3,
                                   msg="宽限期内不衰")

    def test_t6_user_signal_refreshes_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=1.0)
            c.last_user_signal_ts = time.time() - 30 * DAY
            led.register(c)
            # Sir 刚真提 → 刷新锚
            led.record_signal("x", "Sir 真说的", severity_delta=0.0, user_sourced=True)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._cfg()):
                led.apply_decay()
            self.assertAlmostEqual(led.get("x").severity, 1.0, places=3,
                                   msg="Sir 刚提 → 锚刷新 → 不衰")

    def test_t7_user_sourced_flag(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            led.register(Concern(id="x", what_i_watch="w", why_i_care="y", severity=0.5))
            led.record_signal("x", "jarvis 自己", severity_delta=0.0, user_sourced=False)
            self.assertEqual(led.get("x").last_user_signal_ts, 0.0,
                             "贾维斯自己 signal 不更新衰减锚")
            led.record_signal("x", "Sir 真说", severity_delta=0.0, user_sourced=True)
            self.assertGreater(led.get("x").last_user_signal_ts, 0.0,
                               "Sir signal 更新衰减锚")

    def test_t8_disabled_no_decay(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=1.0)
            c.last_user_signal_ts = time.time() - 30 * DAY
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config",
                              return_value=self._cfg(severity_decay_enabled=False)):
                led.apply_decay()
            self.assertAlmostEqual(led.get("x").severity, 1.0, places=3,
                                   msg="disabled → 不衰 (回旧行为)")

    def test_t9_persist_roundtrip_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            led = ConcernsLedger(persist_path=p)
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=0.5)
            led.register(c)
            led.record_signal("x", "Sir", user_sourced=True)
            led._dirty = True
            led.persist()
            led2 = ConcernsLedger(persist_path=p)
            led2.load()
            self.assertGreater(led2.get("x").last_user_signal_ts, 0.0,
                               "last_user_signal_ts 应持久化 roundtrip")

    def test_t9b_legacy_anchor_inference(self):
        # legacy concern (last_user_signal_ts=0) — 锚从 recent_signals 推断:
        # 全是贾维斯内部 signal ([reflect/...]) → fallback created_at → 能衰 (治存量污染)
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=1.0,
                        created_at=time.time() - 30 * DAY)
            c.last_updated = time.time()  # 贾维斯自己刚 reflect 过 (不该当锚)
            c.recent_signals = [
                {"what": "[reflect/turn_x] 检测到话题: hydration", "when": time.time()},
                {"what": "[update/notes_for_self/inner_thought] ...", "when": time.time()},
            ]
            c.last_user_signal_ts = 0.0  # legacy
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._cfg()):
                led.apply_decay()
            self.assertLess(led.get("x").severity, 0.3,
                            "legacy concern 全贾维斯内部 signal → 锚=created_at → 应衰")

    def test_t9c_real_sir_signal_in_recent_anchors(self):
        # recent_signals 含真 Sir signal (非 [reflect/ 前缀) → 锚=那条 when → 新鲜不衰
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = Concern(id="x", what_i_watch="w", why_i_care="y", severity=1.0,
                        created_at=time.time() - 30 * DAY)
            c.recent_signals = [
                {"what": "[reflect/turn_x] 检测到话题", "when": time.time() - 20 * DAY},
                {"what": "Sir 听到 nudge 后正面回应: '好的谢谢'", "when": time.time()},
            ]
            c.last_user_signal_ts = 0.0
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._cfg()):
                led.apply_decay()
            self.assertAlmostEqual(led.get("x").severity, 1.0, places=2,
                                   msg="recent_signals 有真 Sir 回应 → 锚新鲜 → 不衰")


# ============================================================
# Fix3 — snooze/dismiss 切断体张力
# ============================================================
class TestFix3SnoozeDismissTension(unittest.TestCase):
    def _mk_weaver(self, d, concerns):
        cp = os.path.join(d, "concerns.json")
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(concerns, f)
        for name in ("self_threads.json", "relational_state.json", "stance.json"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                json.dump({}, f)
        man = RelationalManifold(os.path.join(d, "m.json"))
        return RelationalWeaver(
            manifold=man, embed_fn=lambda ts: [None] * len(ts),
            threads_path=os.path.join(d, "self_threads.json"),
            concerns_path=cp,
            relational_path=os.path.join(d, "relational_state.json"),
            vectors_path=os.path.join(d, "v.json"),
            stance_path=os.path.join(d, "stance.json"),
            energy_path=os.path.join(d, "e.json"))

    def test_t10_snoozed_no_tension(self):
        with tempfile.TemporaryDirectory() as d:
            w = self._mk_weaver(d, {
                "ksnooze": {"id": "ksnooze", "what_i_watch": "x", "severity": 1.0,
                            "state": "snoozed", "triggers_proactive": False}})
            sev = w._concern_severity_map()
            self.assertNotIn(make_node_id(KIND_CONCERN, "ksnooze"), sev,
                             "snoozed concern 不该喂体张力")

    def test_t11_dismissed_no_tension(self):
        with tempfile.TemporaryDirectory() as d:
            w = self._mk_weaver(d, {
                "cdismiss": {"id": "cdismiss", "what_i_watch": "x", "severity": 0.9,
                             "state": "active", "triggers_proactive": False}})
            sev = w._concern_severity_map()
            self.assertNotIn(make_node_id(KIND_CONCERN, "cdismiss"), sev,
                             "dismiss 软关闭 (triggers_proactive=False) 不该喂体张力")

    def test_t12_active_still_tension(self):
        with tempfile.TemporaryDirectory() as d:
            w = self._mk_weaver(d, {
                "areal": {"id": "areal", "what_i_watch": "x", "severity": 0.8,
                          "state": "active", "triggers_proactive": True}})
            sev = w._concern_severity_map()
            self.assertIn(make_node_id(KIND_CONCERN, "areal"), sev,
                          "真 active + proactive concern 仍喂体张力")
            self.assertAlmostEqual(sev[make_node_id(KIND_CONCERN, "areal")], 0.8, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
