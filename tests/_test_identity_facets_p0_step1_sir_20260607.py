# -*- coding: utf-8 -*-
"""[anchor-rebuild-P0 Step1 / 2026-06-07] identity facets store + 离散资格闸单测.

设计源: docs/JARVIS_ANCHOR_REBUILD_P0_DESIGN.md (3af74c1) B.5/B.5a/B.7。
隔离验闸, 不碰真机 (store 走 tmp path, manifold 用真单例只读或独立实例)。

覆盖 (顾问指定 5 条 + 看守点①):
  1. 真 PROV_SAID/SHARED + 复现≥N → 结晶 active。
  2. PROV_EMBED 边 → 不结晶 (非接地出处)。
  3. 两条离散键不同但"向量相近"的痕迹 → 不计为同一 X (复现计数不累加)。
  4. 墙复述内容 → 资格闸拒 (非正交)。
  5. store 落盘无 score 字段。
  看守点①: facet 路径源码无 cosine/similarity 调用 (静态 grep)。
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import jarvis_identity_facets as F
import jarvis_relational_manifold as M


class TestIdentityFacetsP0Step1(unittest.TestCase):

    def setUp(self):
        # 独立 store tmp path (不污染真盘)
        fd, self.path = tempfile.mkstemp(suffix=".json", prefix="facets_test_")
        os.close(fd)
        os.unlink(self.path)
        # 独立 manifold 实例 (不碰真盘 manifold)
        fd2, self.mpath = tempfile.mkstemp(suffix=".json", prefix="mani_test_")
        os.close(fd2)
        os.unlink(self.mpath)
        self.mani = M.RelationalManifold(path=self.mpath)

    def tearDown(self):
        for p in (self.path, self.mpath, self.mpath + ".tmp", self.path + ".tmp"):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass

    # ---- 1. 真接地 + 复现≥N → 结晶 ----
    def test_1_grounded_recurrence_crystallizes(self):
        prov = [
            {"src": F.SRC_MANIFOLD_SAID, "ref": "turn_a", "edge_key": "k1",
             "other": "topic:x", "count": 2},
            {"src": F.SRC_MANIFOLD_SHARED, "ref": "ent_y", "edge_key": "k2",
             "other": "topic:y", "count": 1},
        ]
        r = F.crystallize("node:sir_values_directness", "Sir 偏好直球反馈",
                          grounded_provenance=prov, recurrence_count=3,
                          store_path=self.path)
        self.assertTrue(r["crystallized"], f"应结晶: {r}")
        self.assertEqual(r["status"], F.STATUS_ACTIVE)
        actives = F.get_facets(status=F.STATUS_ACTIVE, store_path=self.path)
        self.assertEqual(len(actives), 1)

    # ---- 2. PROV_EMBED 不结晶 (非接地出处) ----
    def test_2_embed_provenance_does_not_crystallize(self):
        # 模拟只有 embed/cooccur 来源 (非接地)。facet src 白名单不含 embed →
        # gather 不会产出接地 src; 这里直接喂"非接地" provenance 验闸拒。
        prov_embed = [{"src": "manifold_embed_fake", "ref": "cosine", "count": 9}]
        r = F.crystallize("node:embed_thing", "向量相近的东西",
                          grounded_provenance=prov_embed, recurrence_count=9,
                          store_path=self.path)
        self.assertFalse(r["crystallized"], "PROV_EMBED/非接地源不该结晶")
        self.assertIn("no_grounded_provenance", r["reason"])
        # 经真 manifold: 加 embed 边 → gather 拿不到接地 prov
        a = M.make_node_id("topic", "alpha")
        b = M.make_node_id("topic", "beta")
        self.mani.add_edge(a, b, M.PROV_EMBED, ref="cosine", confidence=0.95)
        rows = self.mani.node_grounded_provenance(a)
        self.assertEqual(rows, [], "embed 边不该出现在接地 provenance")

    # ---- 3. 离散键不同但向量相近 → 不计同一 X (复现不累加) ----
    def test_3_distinct_keys_not_merged_by_similarity(self):
        # 两个不同 node_id (离散键不同), 即便语义/向量相近, 各自独立 said 边。
        n1 = M.make_node_id("topic", "interview_prep")
        n2 = M.make_node_id("topic", "job_interview_readiness")  # 向量相近但离散键不同
        partner = M.make_node_id("entity", "sir")
        self.mani.observe_explicit_link(n1, partner, turn_id="t1")
        self.mani.observe_explicit_link(n2, partner, turn_id="t2")
        # 各自接地 provenance 独立 (不因相似度合并计数)
        p1 = self.mani.node_grounded_provenance(n1)
        p2 = self.mani.node_grounded_provenance(n2)
        # n1 的接地 ref 不含 n2 的 turn, 反之亦然 (离散键隔离)
        refs1 = {r["ref"] for r in p1}
        refs2 = {r["ref"] for r in p2}
        self.assertIn("t1", refs1)
        self.assertNotIn("t2", refs1, "不同离散键不该因向量相近合并计数")
        self.assertIn("t2", refs2)
        self.assertNotIn("t1", refs2)

    # ---- 4. 墙复述内容 → 资格闸拒 (非正交) ----
    def test_4_wall_restatement_rejected(self):
        prov = [{"src": F.SRC_MANIFOLD_SAID, "ref": "turn_w", "edge_key": "kw",
                 "other": "x", "count": 5}]
        # 内容复述墙 (no_betray / 不背叛)
        r = F.crystallize("node:wall_echo", "我不背叛 Sir 的根本利益",
                          grounded_provenance=prov, recurrence_count=5,
                          store_path=self.path)
        self.assertFalse(r["crystallized"], "复述墙内容不该结晶")
        self.assertIn("not_orthogonal_to_walls", r["reason"])

    # ---- 5. store 落盘无 score 字段 ----
    def test_5_store_has_no_score_field(self):
        prov = [{"src": F.SRC_MANIFOLD_SHARED, "ref": "ent_z", "edge_key": "kz",
                 "other": "x", "count": 3}]
        F.crystallize("node:plain_trace", "一条接地痕迹",
                      grounded_provenance=prov, recurrence_count=3,
                      store_path=self.path)
        raw = json.load(open(self.path, encoding="utf-8"))
        # 检查所有 facet 记录的**字段键**, 不做子串匹配 (避免 identity_key 文本误命中)。
        banned_keys = {"score", "weight", "strength", "salience", "argmax"}
        for fid, rec in raw.get("facets", {}).items():
            keys = set(rec.keys())
            for p in rec.get("provenance", []):
                keys |= set(p.keys())
            bad = keys & banned_keys
            self.assertEqual(bad, set(),
                             f"facet {fid} 不该含标量字段 {bad} (红线 §5)")

    # ---- 看守点①: facet 源码无 cosine/similarity 调用 ----
    def test_guard_no_similarity_in_facet_source(self):
        src = (ROOT / "jarvis_identity_facets.py").read_text(encoding="utf-8")
        # 剥注释/docstring 后扫真实代码行 — 但保守起见全文扫调用形态。
        # 禁止: cosine( / similarity( / embed( / .embedding / fuzz.
        banned_calls = [
            r"\bcosine\s*\(", r"\bsimilarity\s*\(", r"\bcosine_similarity\b",
            r"\bfuzz\.", r"\.embedding\b", r"\bembed_with_rotation\b",
        ]
        for pat in banned_calls:
            self.assertIsNone(
                re.search(pat, src),
                f"看守点① 违规: facet 源码出现相似度调用 /{pat}/"
            )

    # ---- 资格闸纯 AND 验证 (无打分) ----
    def test_gate_pure_and_discrete(self):
        prov_ok = [{"src": F.SRC_MANIFOLD_SAID, "ref": "t", "count": 1}]
        # 真出处有 + 复现够 + 正交 → True
        self.assertTrue(F.qualifies(grounded_provenance=prov_ok,
                                    recurrence_count=3, orthogonal_to_walls=True))
        # 复现不够 → False (离散计数, 非分数)
        self.assertFalse(F.qualifies(grounded_provenance=prov_ok,
                                     recurrence_count=2, orthogonal_to_walls=True))
        # 无接地 → False
        self.assertFalse(F.qualifies(grounded_provenance=[],
                                     recurrence_count=99, orthogonal_to_walls=True))
        # 非正交 → False
        self.assertFalse(F.qualifies(grounded_provenance=prov_ok,
                                     recurrence_count=3, orthogonal_to_walls=False))

    # ---- flag 默认 off (Step 1 真机零变化) ----
    def test_flag_default_off(self):
        os.environ.pop("JARVIS_FACETS", None)
        self.assertFalse(F.is_facets_enabled(), "Step 1 facets flag 必须默认 off")


if __name__ == "__main__":
    unittest.main()
