# -*- coding: utf-8 -*-
"""[主页 / Sir 2026-06-01] jarvis_homepage — 四元架构演化主页 (纯读聚合).

主页 vs 面板分工 (Sir 定): 面板=运维数值健康; 主页="谁的诞生路径" (识/说/体/衡 + 演变)。
真相源 docs/JARVIS_ANCHOR_AND_BOUNDARY.md (锚=负空间/四标记) + JARVIS_TRINITY_ARCHITECTURE.md。

覆盖:
  T1  collect() 返回 7 区 (who/continuity/mind/voice/body/weigh/emergence)
  T2  who_i_am: 锚负空间 (墙=不做什么) + 多锚形状判定
  T3  mind: 衡三态分布 + 最新 thought
  T4  emergence: 数据跨度 <48h → evolution=insufficient_data (不伪造长期趋势)
  T5  emergence: 数据跨度 >=48h + filler 降 → emerging
  T6  emergence 四标记: wound→标记2, capability→标记4
  T7  render() 不崩 + 含四元 (识/说/体/衡) + 演变 + 诚实残余标注
  T8  纯读: collect 不写任何文件
  T9  全源缺失 → 各区 available=False, 不抛
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

import jarvis_homepage as hp


def _wj(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestHomepage(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.now = time.time()

    def tearDown(self):
        self._td.cleanup()

    def test_t1_collect_seven_zones(self):
        v = hp.collect(now=self.now)
        for k in ("who", "continuity", "mind", "voice", "body", "weigh", "emergence"):
            self.assertIn(k, v, f"缺区 {k}")

    def test_t2_who_anchors_negative_space(self):
        w = hp.who_i_am()
        # 真仓有 anchors.json (P0 已建), 应可读 2 锚
        if w.get("available"):
            self.assertGreaterEqual(w.get("n_anchors", 0), 1)
            # 墙是"不做什么" (负空间): 每墙有 prohibition
            for a in w.get("anchors", []):
                for wall in a.get("walls", []):
                    self.assertIn("not", wall)

    def test_t3_mind_heng_distribution(self):
        p = os.path.join(self._td.name, "it.jsonl")
        _wj(p, [
            {"ts": self.now - 50, "heng_state": "discharge", "thought": "x",
             "derived_kind": "solve", "ts_iso": "2026-06-01T00:00:00"},
            {"ts": self.now - 40, "heng_state": "filler", "thought": "y"},
            {"ts": self.now - 30, "heng_state": "rest", "thought": "z"},
        ])
        with patch.object(hp, "_INNER_THOUGHTS", p):
            m = hp.mind(now=self.now)
        self.assertTrue(m["available"])
        self.assertEqual(m["heng_dist"]["discharge"], 1)
        self.assertEqual(m["heng_dist"]["filler"], 1)
        self.assertEqual(m["thought_count"], 3)

    def test_t4_emergence_insufficient_data(self):
        # 全部 thought 在近 6h 内 → 跨度 <48h → insufficient_data (不伪造趋势)
        p = os.path.join(self._td.name, "it.jsonl")
        _wj(p, [
            {"ts": self.now - 3600, "heng_state": "discharge"},
            {"ts": self.now - 1800, "heng_state": "filler"},
            {"ts": self.now - 600, "heng_state": "rest"},
        ])
        with patch.object(hp, "_INNER_THOUGHTS", p):
            em = hp.emergence(now=self.now)
        self.assertEqual(em["evolution"], "insufficient_data")
        self.assertLess(em["heng_data_span_hours"], 48.0)

    def test_t5_emergence_emerging(self):
        # 跨度 >48h, 早期 filler 高, 今天 filler 低 → emerging
        p = os.path.join(self._td.name, "it.jsonl")
        wk = 168 * 3600.0
        old = self.now - wk * 0.6  # >48h 前
        rows = []
        # 一周前: 多 filler
        for i in range(10):
            rows.append({"ts": old + i, "heng_state": "filler"})
        for i in range(2):
            rows.append({"ts": old + 100 + i, "heng_state": "discharge"})
        # 今天: 多 discharge, 少 filler
        for i in range(10):
            rows.append({"ts": self.now - 600 + i, "heng_state": "discharge"})
        rows.append({"ts": self.now - 100, "heng_state": "filler"})
        _wj(p, rows)
        with patch.object(hp, "_INNER_THOUGHTS", p):
            em = hp.emergence(now=self.now)
        self.assertGreaterEqual(em["heng_data_span_hours"], 48.0)
        self.assertEqual(em["evolution"], "emerging")

    def test_t6_emergence_markers(self):
        it = os.path.join(self._td.name, "it.jsonl")
        wounds = os.path.join(self._td.name, "w.jsonl")
        caps = os.path.join(self._td.name, "c.jsonl")
        _wj(it, [{"ts": self.now - 100, "heng_state": "discharge"}])
        _wj(wounds, [{"ts": self.now - 100, "detail": "chose A over B"}])
        _wj(caps, [{"ts": self.now - 100, "desc": "read calendar"}])
        with patch.object(hp, "_INNER_THOUGHTS", it), \
             patch.object(hp, "_WOUNDS", wounds), \
             patch.object(hp, "_CAPABILITY", caps):
            em = hp.emergence(now=self.now)
        self.assertEqual(em["markers"]["resistance_marks"], 1)
        self.assertEqual(em["markers"]["self_authored_wishes"], 1)

    def test_t7_render_four_pillars(self):
        out = hp.render(now=self.now)
        for kw in ("识", "说", "体", "衡", "演变", "我是谁", "诚实残余"):
            self.assertIn(kw, out, f"render 缺 {kw}")

    def test_t8_pure_read_no_write(self):
        before = set(os.listdir(hp._MEM)) if os.path.isdir(hp._MEM) else set()
        hp.collect(now=self.now)
        after = set(os.listdir(hp._MEM)) if os.path.isdir(hp._MEM) else set()
        self.assertEqual(before, after, "collect() 不应写文件 (纯观测)")

    def test_t9_all_sources_missing(self):
        bad = os.path.join(self._td.name, "nope.jsonl")
        with patch.object(hp, "_INNER_THOUGHTS", bad), \
             patch.object(hp, "_WOUNDS", bad), \
             patch.object(hp, "_CAPABILITY", bad), \
             patch.object(hp, "_COLD_STARTS", bad), \
             patch.object(hp, "_STM_RECENT", bad):
            v = hp.collect(now=self.now)  # 不应抛
        self.assertFalse(v["mind"]["available"])
        self.assertFalse(v["continuity"]["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
