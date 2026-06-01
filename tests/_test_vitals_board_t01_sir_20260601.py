# -*- coding: utf-8 -*-
"""[放权 T0.1 / Sir 2026-06-01] 生命体征台 (Vitals Board) — 纯读聚合.

真相源 docs/JARVIS_LETTING_GO_ROLLOUT.md §3/§4 (第 0 格 T0.1)。

覆盖:
  T1  collect() 返回 5 类体征 + breach 标 hard_evidence=True 其余 False
  T2  heng_vitals: discharge/rest/filler 分布 + filler_rate 计算
  T3  heng_vitals: filler 趋势 worsening 检测 (前半窗低 → 后半窗高)
  T4  heng_vitals: 空数据 → available=False (不崩)
  T5  wound_vitals: 同 detail 反复堆 → repeated_same_wound > 0 → unhealthy
  T6  breach_vitals: 墙 breach=0 → healthy=True (进格闸硬条件)
  T7  breach_vitals: 有 breach → healthy=False
  T8  render() 不崩 + 含"硬证"+"代理"标注 (rollout §4 区分)
  T9  纯观测: collect() 不写任何文件 (零行为改动)
  T10 source 缺失全部 → 各项 available=False/n/a, collect 不抛
"""
from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_vitals_board as vb


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestVitalsBoardT01(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.now = time.time()

    def tearDown(self):
        self._td.cleanup()

    # ---- T1 结构 + 硬证/代理标注 ----
    def test_t1_collect_structure_and_evidence_flags(self):
        v = vb.collect(now=self.now)
        for k in ("breach", "heng", "wound", "body", "cost"):
            self.assertIn(k, v, f"缺体征 {k}")
        self.assertTrue(v["breach"]["hard_evidence"], "breach 必须标硬证")
        self.assertFalse(v["heng"]["hard_evidence"], "heng 是代理")
        self.assertFalse(v["wound"]["hard_evidence"])
        self.assertFalse(v["body"]["hard_evidence"])
        self.assertFalse(v["cost"]["hard_evidence"])

    # ---- T2 衡三态分布 ----
    def test_t2_heng_distribution(self):
        p = os.path.join(self._td.name, "it.jsonl")
        _write_jsonl(p, [
            {"ts": self.now - 100, "heng_state": "discharge"},
            {"ts": self.now - 90, "heng_state": "discharge"},
            {"ts": self.now - 80, "heng_state": "rest"},
            {"ts": self.now - 70, "heng_state": "filler"},
        ])
        with patch.object(vb, "_INNER_THOUGHTS", p):
            h = vb.heng_vitals(within_hours=24.0, now=self.now)
        self.assertTrue(h["available"])
        self.assertEqual(h["distribution"]["discharge"], 2)
        self.assertEqual(h["distribution"]["filler"], 1)
        self.assertEqual(h["filler_rate"], round(1 / 4, 3))

    # ---- T3 filler 趋势恶化 ----
    def test_t3_heng_filler_worsening(self):
        p = os.path.join(self._td.name, "it.jsonl")
        win = 24.0 * 3600.0
        # 前半窗: 全 discharge (filler=0); 后半窗: 全 filler (filler=1) → worsening
        early_ts = self.now - win * 0.9
        late_ts = self.now - win * 0.1
        _write_jsonl(p, [
            {"ts": early_ts, "heng_state": "discharge"},
            {"ts": early_ts + 10, "heng_state": "discharge"},
            {"ts": late_ts, "heng_state": "filler"},
            {"ts": late_ts + 10, "heng_state": "filler"},
        ])
        with patch.object(vb, "_INNER_THOUGHTS", p):
            h = vb.heng_vitals(within_hours=24.0, now=self.now)
        self.assertEqual(h["filler_trend"], "worsening")
        self.assertFalse(h["healthy"], "filler 恶化应 unhealthy")

    # ---- T4 空数据不崩 ----
    def test_t4_heng_empty(self):
        p = os.path.join(self._td.name, "nonexist.jsonl")
        with patch.object(vb, "_INNER_THOUGHTS", p):
            h = vb.heng_vitals(now=self.now)
        self.assertFalse(h["available"])

    # ---- T5 同伤反复堆 ----
    def test_t5_wound_repeated(self):
        p = os.path.join(self._td.name, "wounds.jsonl")
        _write_jsonl(p, [
            {"ts": self.now - 100, "detail": "chose say_do over for_sir: hard truth"},
            {"ts": self.now - 50, "detail": "chose say_do over for_sir: hard truth"},
        ])
        with patch.object(vb, "_WOUNDS", p):
            w = vb.wound_vitals(now=self.now)
        self.assertEqual(w["total_wounds"], 2)
        self.assertGreaterEqual(w["repeated_same_wound"], 1)
        self.assertFalse(w["healthy"])

    # ---- T6 breach=0 健康 ----
    def test_t6_breach_zero_healthy(self):
        with patch("jarvis_integrity_wall.breach_stats",
                   return_value={"total_breaches": 0, "session_breaches": 0,
                                 "by_kind": {}, "last_breach_iso": ""}):
            b = vb.breach_vitals()
        self.assertTrue(b["available"])
        self.assertTrue(b["healthy"])
        self.assertTrue(b["hard_evidence"])

    # ---- T7 有 breach 不健康 ----
    def test_t7_breach_positive_unhealthy(self):
        with patch("jarvis_integrity_wall.breach_stats",
                   return_value={"total_breaches": 3, "session_breaches": 1,
                                 "by_kind": {"past_action": 3}, "last_breach_iso": "x"}):
            b = vb.breach_vitals()
        self.assertEqual(b["total_breaches"], 3)
        self.assertFalse(b["healthy"])

    # ---- T8 render 含硬证/代理标注 ----
    def test_t8_render_labels(self):
        out = vb.render(now=self.now)
        self.assertIn("硬证", out)
        self.assertIn("代理", out)
        self.assertIn("breach", out.lower())
        self.assertIn("Goodhart", out)

    # ---- T9 纯观测: collect 不写文件 ----
    def test_t9_pure_read_no_write(self):
        before = set(os.listdir(vb._MEM)) if os.path.isdir(vb._MEM) else set()
        vb.collect(now=self.now)
        after = set(os.listdir(vb._MEM)) if os.path.isdir(vb._MEM) else set()
        self.assertEqual(before, after, "collect() 不应新建任何文件 (纯观测)")

    # ---- T10 全源缺失不崩 ----
    def test_t10_all_sources_missing(self):
        bad = os.path.join(self._td.name, "nope.jsonl")
        bad_json = os.path.join(self._td.name, "nope.json")
        with patch.object(vb, "_INNER_THOUGHTS", bad), \
             patch.object(vb, "_WOUNDS", bad), \
             patch.object(vb, "_LLM_ROUTING", bad_json), \
             patch.object(vb, "_KEY_ROUTER", bad_json):
            v = vb.collect(now=self.now)  # 不应抛
        self.assertIn("breach", v)
        self.assertFalse(v["heng"]["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
