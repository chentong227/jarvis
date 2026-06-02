# -*- coding: utf-8 -*-
"""[body-diff-PG / Sir 2026-06-02] 接地谓词门 (固着↔健忘旋钮) 回归.

真理源: .kiro/specs/body-differentiation/ (R1/R11/R16, design §5.1,
Correctness Properties P1/P2/P3)。

不变量①: 倾斜默认衰减 UNLESS 机器可核谓词证明此事仍开着。两护栏焊死:
  (a) 默认衰减 (无谓词/not-open/不可判 → 衰); (b) 机器可核优先 (绝不 LLM)。

覆盖:
  Property 1 默认衰减:
    T1  无谓词 concern → still_open=False (默认衰减)
    T2  门关 (enabled=false) → 一律 still_open=False
  Property 2 still-open 顶住:
    T3  deadline 在未来 → still_open=True + evidence
    T4  deadline 过去 → still_open=False (事了结, 松开)
    T5  external_state=open → still_open=True
  Property 3 无 LLM:
    T6  grounded_predicate 模块源码无 LLM import / 调用
  R11.5 门接入 apply_decay:
    T7  still-open concern (deadline 未来) → apply_decay 不衰 severity
    T8  not-open concern → apply_decay 照常衰 (健忘侧)
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_grounded_predicate as gp
from jarvis_concerns import ConcernsLedger, Concern
import jarvis_soul_reflector as sr

DAY = 86400.0
T0 = time.time()


def _seed_cfg(enabled=True, preds=None):
    """默认谓词注册表 (date_compare + external_state, 不含 commitment 避免 nerve 依赖)。"""
    return {
        "enabled": enabled,
        "predicates": preds if preds is not None else [
            {"id": "deadline_future", "applies_to_kind": "concern",
             "match": {"has_field": "deadline_ts"}, "backstop": "date_compare",
             "enabled": True},
            {"id": "external_state_open", "applies_to_kind": "concern",
             "match": {"has_field": "external_state"}, "backstop": "external_state",
             "enabled": True},
        ],
    }


def _concern(cid="x", **kw):
    c = Concern(id=cid, what_i_watch="w", why_i_care="y", severity=kw.pop("severity", 1.0))
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ============================================================
# Property 1 — 默认衰减
# ============================================================
class TestProperty1DefaultDecay(unittest.TestCase):
    def test_t1_no_predicate_not_open(self):
        c = _concern("plain")  # 无 deadline_ts / external_state
        with patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
            open_, ev = gp.is_still_open(c, now=T0)
        self.assertFalse(open_, "无适用谓词 → 默认衰减 (not-open)")
        self.assertEqual(ev, "")

    def test_t2_gate_off_not_open(self):
        c = _concern("x", deadline_ts=T0 + 10 * DAY)  # 本该 still-open
        with patch.object(gp, "_load_predicates", return_value=_seed_cfg(enabled=False)):
            open_, ev = gp.is_still_open(c, now=T0)
        self.assertFalse(open_, "门关 → 一律 not-open")


# ============================================================
# Property 2 — still-open 顶住
# ============================================================
class TestProperty2StillOpen(unittest.TestCase):
    def test_t3_deadline_future_open(self):
        c = _concern("exam", deadline_ts=T0 + 5 * DAY)
        with patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
            open_, ev = gp.is_still_open(c, now=T0)
        self.assertTrue(open_, "deadline 在未来 → 仍开着")
        self.assertIn("deadline_future", ev)

    def test_t4_deadline_past_not_open(self):
        c = _concern("exam", deadline_ts=T0 - 5 * DAY)
        with patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
            open_, ev = gp.is_still_open(c, now=T0)
        self.assertFalse(open_, "deadline 过去 → 事了结, 松开 (默认衰减)")

    def test_t5_external_state_open(self):
        c = _concern("bill", external_state="open")
        with patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
            open_, ev = gp.is_still_open(c, now=T0)
        self.assertTrue(open_, "external_state=open → 仍开着")
        self.assertIn("external_state", ev)

    def test_t5b_external_state_closed(self):
        c = _concern("bill", external_state="closed")
        with patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
            open_, ev = gp.is_still_open(c, now=T0)
        self.assertFalse(open_, "external_state=closed → not-open")


# ============================================================
# Property 3 — 无 LLM
# ============================================================
class TestProperty3NoLLM(unittest.TestCase):
    def test_t6_no_llm_in_source(self):
        with open(gp.__file__, "r", encoding="utf-8") as f:
            src = f.read().lower()
        # 不得有 LLM 调用路径 (safe_openrouter_call / safe_gemini / reflect / llm call)
        for bad in ("safe_openrouter_call", "safe_gemini_call", "llmreflector",
                    "key_router.get_key", ".reflect("):
            self.assertNotIn(bad, src,
                             f"接地谓词门绝不靠 LLM, 源码不应含 '{bad}'")


# ============================================================
# R11.5 — 门接入 apply_decay
# ============================================================
class TestGateInDecay(unittest.TestCase):
    def _decay_cfg(self):
        return {"severity_decay_enabled": True, "severity_half_life_days": 7.0,
                "severity_decay_grace_days": 2.0, "severity_decay_floor": 0.0}

    def test_t7_still_open_holds_severity(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = _concern("exam", severity=1.0, deadline_ts=T0 + 5 * DAY)
            c.last_user_signal_ts = T0 - 30 * DAY  # 久无 Sir signal (本该衰)
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._decay_cfg()), \
                 patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
                stats = led.apply_decay()
            self.assertAlmostEqual(led.get("exam").severity, 1.0, places=3,
                                   msg="still-open (deadline 未来) → 抗衰减保持, 不被遗忘")
            self.assertGreaterEqual(stats.get("gate_held", 0), 1)

    def test_t8_not_open_decays(self):
        with tempfile.TemporaryDirectory() as d:
            led = ConcernsLedger(persist_path=os.path.join(d, "c.json"))
            c = _concern("stale", severity=1.0, deadline_ts=T0 - 5 * DAY)  # deadline 过去
            c.last_user_signal_ts = T0 - 30 * DAY
            led.register(c)
            with patch.object(sr, "_load_concern_decay_config", return_value=self._decay_cfg()), \
                 patch.object(gp, "_load_predicates", return_value=_seed_cfg()):
                led.apply_decay()
            self.assertLess(led.get("stale").severity, 0.3,
                            "not-open (deadline 过去 + 久无 Sir signal) → 照常衰 (健忘侧)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
