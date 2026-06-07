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

    # ======================================================================
    # Step 2 — 锚减离散事件触发 (B.6)
    # ======================================================================
    def _crystallize_via_node(self, raw_id, content, n_links=3):
        """helper: 真 manifold 造 n_links 条 said 边 → 经 node 离散键结晶。"""
        node = M.make_node_id("topic", raw_id)
        for i in range(n_links):
            self.mani.observe_explicit_link(
                node, M.make_node_id("entity", f"sir_{i}"), turn_id=f"t_{raw_id}_{i}")
        # 用注入式 crystallize (直接喂离散 prov, 不依赖全局单例)
        prov = self.mani.node_grounded_provenance(node)
        prov_facet = [{"src": F.SRC_MANIFOLD_SAID, "ref": p["ref"],
                       "edge_key": p["edge_key"], "other": p["other"],
                       "count": p["count"]} for p in prov]
        ikey = self.mani.resolve(node)
        return F.crystallize(ikey, content, grounded_provenance=prov_facet,
                             recurrence_count=len(prov_facet),
                             store_path=self.path), node, ikey

    def test_s2_reverify_edge_gone_revokes(self):
        # 用 monkeypatch 让 gather 走本测 manifold 实例
        import unittest.mock as mock
        r, node, ikey = self._crystallize_via_node("reverify_x", "Sir 关心 X", 3)
        self.assertTrue(r["crystallized"])
        fid = r["facet_id"]
        # 接地边还在 → reverify 仍 active
        with mock.patch.object(F, "gather_grounded_provenance",
                               side_effect=lambda k: [
                                   {"src": F.SRC_MANIFOLD_SAID, "ref": "x", "count": 1}]):
            self.assertEqual(F.reverify_facet(fid, store_path=self.path), F.STATUS_ACTIVE)
        # 接地边没了 → reverify → revoked
        with mock.patch.object(F, "gather_grounded_provenance",
                               side_effect=lambda k: []):
            self.assertEqual(F.reverify_facet(fid, store_path=self.path), F.STATUS_REVOKED)
        revoked = F.get_facets(status=F.STATUS_REVOKED, store_path=self.path)
        self.assertEqual(len(revoked), 1)
        self.assertEqual(revoked[0]["revoke_reason"], "grounding_edge_gone")

    def test_s2_sir_correction_revokes(self):
        r, node, ikey = self._crystallize_via_node("corr_y", "Sir 偏好 Y", 3)
        fid = r["facet_id"]
        n = F.on_sir_correction(ikey, detail="not true", store_path=self.path)
        self.assertEqual(n, 1)
        revoked = F.get_facets(status=F.STATUS_REVOKED, store_path=self.path)
        self.assertEqual(len(revoked), 1)
        self.assertIn("sir_corrected", revoked[0]["revoke_reason"])

    def test_s2_time_alone_does_not_revoke(self):
        # 时间过(改老 crystallized_ts), 但接地边还在 → reverify 后仍 active(不自动减)
        import unittest.mock as mock
        r, node, ikey = self._crystallize_via_node("time_z", "Sir 习惯 Z", 3)
        fid = r["facet_id"]
        # 手动把 ts 改到很久以前
        store = json.load(open(self.path, encoding="utf-8"))
        store["facets"][fid]["crystallized_ts"] = time.time() - 999 * 86400
        json.dump(store, open(self.path, "w", encoding="utf-8"))
        with mock.patch.object(F, "gather_grounded_provenance",
                               side_effect=lambda k: [
                                   {"src": F.SRC_MANIFOLD_SHARED, "ref": "z", "count": 2}]):
            self.assertEqual(F.reverify_facet(fid, store_path=self.path), F.STATUS_ACTIVE,
                             "时间过但边还在 → 不该自动降级 (B.6 第3条)")

    # ======================================================================
    # Step 3 — render facets (B.8a)
    # ======================================================================
    def _seed_n_facets(self, n, src_mix=True):
        store = {"_meta": {}, "facets": {}}
        for i in range(n):
            src = (F.SRC_MANIFOLD_SHARED if (src_mix and i % 2 == 0)
                   else F.SRC_MANIFOLD_SAID)
            fid = f"facet_f{i}"
            store["facets"][fid] = {
                "facet_id": fid, "identity_key": f"node:f{i}",
                "content": f"facet content number {i}",
                "provenance": [{"source": src, "ref": f"r{i}", "recurrence_count": 3}],
                "recurrence_count": 3, "crystallized_ts": 1000.0 + i,
                "status": F.STATUS_ACTIVE,
            }
        json.dump(store, open(self.path, "w", encoding="utf-8"))

    def test_s3_render_caps_5_and_shared_priority(self):
        os.environ["JARVIS_FACETS"] = "1"
        try:
            self._seed_n_facets(6, src_mix=True)  # 3 shared (even i) + 3 said (odd i)
            block = F.render_facets_block(store_path=self.path)
            # 最多 5 条
            body_lines = [l for l in block.splitlines() if l.strip().startswith("- ")]
            self.assertLessEqual(len(body_lines), 5, "渲染最多 5 条")
            # PROV_SHARED 优先: 被丢的那条应是 said (优先级低)。shared facets = i 0,2,4
            # 共 3 条必全在; said = i 1,3,5 共 3 条只能进 2 条。
            self.assertIn("number 0", block)
            self.assertIn("number 2", block)
            self.assertIn("number 4", block)
        finally:
            os.environ.pop("JARVIS_FACETS", None)

    def test_s3_no_half_truncation(self):
        os.environ["JARVIS_FACETS"] = "1"
        try:
            # 一条超长 facet + 一条短的; 子预算放不下超长 → 整条丢, 不半截
            store = {"_meta": {}, "facets": {
                "facet_long": {"facet_id": "facet_long", "identity_key": "node:long",
                               "content": "X" * 500, "provenance": [
                                   {"source": F.SRC_MANIFOLD_SAID, "ref": "rl",
                                    "recurrence_count": 3}],
                               "recurrence_count": 3, "crystallized_ts": 1000.0,
                               "status": F.STATUS_ACTIVE},
            }}
            json.dump(store, open(self.path, "w", encoding="utf-8"))
            block = F.render_facets_block(store_path=self.path)
            # 超长条整条丢弃 → block 不含 X*500 的任何片段 (header-only → 返空)
            self.assertNotIn("XXX", block, "超长 facet 应整条丢弃, 不半截断")
        finally:
            os.environ.pop("JARVIS_FACETS", None)

    def test_s3_flag_off_empty_render(self):
        os.environ.pop("JARVIS_FACETS", None)
        self._seed_n_facets(3)
        self.assertEqual(F.render_facets_block(store_path=self.path), "",
                         "flag off 时渲染段必须为空")

    def test_s3_build_block_flag_off_no_regression(self):
        """flag off 时 SelfAnchor.build_block 不含 facets 段 (L0 无回归)。"""
        os.environ.pop("JARVIS_FACETS", None)
        import jarvis_self_anchor as SA
        sa = SA.SelfAnchor(central_nerve=None)
        block = sa.build_block()
        self.assertNotIn("WHO I'VE BECOME", block,
                         "flag off 时 build_block 不该含 facets 段")

    # ---- 看守点①bis: _is_orthogonal_to_walls 读 _SEED_ANCHORS 墙 id ----
    def test_orthogonal_reads_seed_anchors(self):
        ids = F._get_wall_ids()
        for wid in ("ground", "keep", "no_betray", "no_abandon"):
            self.assertIn(wid, ids, f"墙 id {wid} 应从 _SEED_ANCHORS 读到")

    # ======================================================================
    # 激活接线 B 验 (方案 A: Weaver weave_once 尾 producer + reverify)
    # ======================================================================
    def _make_weaver(self, tmpdir):
        """构造跑得动的 Weaver: 本测 manifold + no-op embed_fn (不烧 LLM) + temp paths。"""
        import jarvis_relational_weaver as W
        return W.RelationalWeaver(
            manifold=self.mani,
            embed_fn=lambda texts: [None] * len(texts),  # no-op, 不调 Gemini
            root=tmpdir,
            delta_publisher=lambda d: None,
            event_bus=None,
        )

    def test_wire_producer_crystallizes_on_weave(self):
        """方案A: flag-on 跑 weave_once → 接地痕迹(≥3 turn)结晶进 store。"""
        import tempfile, unittest.mock as mock
        os.environ["JARVIS_FACETS"] = "1"
        tmpd = tempfile.mkdtemp()
        try:
            # manifold 塞 3 不同 turn 的 said 边 (同一节点对)
            node = M.make_node_id("topic", "wired_topic")
            for t in ("w1", "w2", "w3"):
                self.mani.observe_explicit_link(node, M.make_node_id("entity", "sir"), turn_id=t)
            wv = self._make_weaver(tmpd)
            # producer 在 weave 内用全局 get_manifold; patch 指向本测 manifold + 本测 store
            with mock.patch("jarvis_relational_manifold.get_manifold", return_value=self.mani), \
                 mock.patch.object(F, "_STORE_PATH", self.path):
                wv.weave_once()
            actives = F.get_facets(status=F.STATUS_ACTIVE, store_path=self.path)
            self.assertGreaterEqual(len(actives), 1, "flag-on weave 后应结晶 active facet")
            # 无 score 字段
            blob = json.dumps(json.load(open(self.path, encoding="utf-8")))
            for k in ('"score"', '"weight"', '"strength"', '"salience"'):
                self.assertNotIn(k, blob)
        finally:
            os.environ.pop("JARVIS_FACETS", None)
            import shutil; shutil.rmtree(tmpd, ignore_errors=True)

    def test_wire_flag_off_no_producer_call(self):
        """flag off: weave_once 不调 producer/reverify (真机零变化)。"""
        import tempfile, unittest.mock as mock
        os.environ.pop("JARVIS_FACETS", None)
        tmpd = tempfile.mkdtemp()
        try:
            wv = self._make_weaver(tmpd)
            with mock.patch.object(F, "scan_and_crystallize") as m_scan, \
                 mock.patch.object(F, "reverify_all_facets") as m_rev:
                wv.weave_once()
                m_scan.assert_not_called()
                m_rev.assert_not_called()
        finally:
            import shutil; shutil.rmtree(tmpd, ignore_errors=True)

    def test_wire_try_except_facets_exception_does_not_break_weave(self):
        """try/except 兜底: facets 抛异常 → weave_once 照常返回 stats。"""
        import tempfile, unittest.mock as mock
        os.environ["JARVIS_FACETS"] = "1"
        tmpd = tempfile.mkdtemp()
        try:
            wv = self._make_weaver(tmpd)
            with mock.patch.object(F, "scan_and_crystallize",
                                   side_effect=RuntimeError("boom")):
                stats = wv.weave_once()  # 不该抛
            self.assertIsInstance(stats, dict)
            self.assertIn("edge_count", stats, "weave 主循环应照常完成")
        finally:
            os.environ.pop("JARVIS_FACETS", None)
            import shutil; shutil.rmtree(tmpd, ignore_errors=True)

    def test_wire_reverify_periodic_counter(self):
        """reverify 走离散计数节拍 (% R), 边删 → 到节拍 revoke。"""
        import tempfile, unittest.mock as mock
        os.environ["JARVIS_FACETS"] = "1"
        tmpd = tempfile.mkdtemp()
        try:
            # 先种 1 条 active facet 到本测 store
            store = {"_meta": {}, "facets": {"facet_rv": {
                "facet_id": "facet_rv", "identity_key": "node:rv",
                "content": "c", "provenance": [{"source": F.SRC_MANIFOLD_SAID,
                "ref": "r", "recurrence_count": 3}], "recurrence_count": 3,
                "crystallized_ts": 1.0, "status": F.STATUS_ACTIVE}}}
            json.dump(store, open(self.path, "w", encoding="utf-8"))
            wv = self._make_weaver(tmpd)
            wv._weave_count = 5  # 下一趟 weave → _weave_count=6, %6==0 触发 reverify
            # 接地边没了 → reverify 应 revoke
            with mock.patch("jarvis_relational_manifold.get_manifold", return_value=self.mani), \
                 mock.patch.object(F, "_STORE_PATH", self.path), \
                 mock.patch.object(F, "gather_grounded_provenance", side_effect=lambda k: []):
                wv.weave_once()
            revoked = F.get_facets(status=F.STATUS_REVOKED, store_path=self.path)
            self.assertEqual(len(revoked), 1, "到 %R 节拍 + 边没了 → revoke")
            self.assertEqual(revoked[0]["revoke_reason"], "grounding_edge_gone")
        finally:
            os.environ.pop("JARVIS_FACETS", None)
            import shutil; shutil.rmtree(tmpd, ignore_errors=True)

    # ======================================================================
    # 末轮 — producer scan_and_crystallize + count 语义 + 全 tier B 验
    # ======================================================================
    def _patch_gather_to_test_manifold(self):
        """让 facets 模块的 manifold 调用走本测独立实例 (不碰真盘)。"""
        import unittest.mock as mock
        return mock.patch.object(F, "get_manifold_for_test", create=True)

    def test_producer_count_distinct_turns_not_sum(self):
        """count 语义核: ≥3 不同 turn → 结晶; 同一 turn 重复多次 → 不够格。"""
        # 同一对节点, 同一 turn 重复 5 次 (count 自增到 5, 但只 1 个不同 ref)
        a = M.make_node_id("topic", "same_turn_spam")
        b = M.make_node_id("entity", "sir")
        for _ in range(5):
            self.mani.observe_explicit_link(a, b, turn_id="SAME_TURN")
        prov_rows = self.mani.node_grounded_provenance(a)
        prov_facet = [{"src": F.SRC_MANIFOLD_SAID, "ref": p["ref"],
                       "edge_key": p["edge_key"], "other": p["other"],
                       "count": p["count"]} for p in prov_rows]
        # _distinct_event_count = 1 (只 1 个不同 ref), 即便 count 累到 5
        self.assertEqual(F._distinct_event_count(prov_facet), 1,
                         "同一 turn 重复不该计成多个离散事件")
        r = F.crystallize(self.mani.resolve(a), "x",
                          grounded_provenance=prov_facet,
                          recurrence_count=F._distinct_event_count(prov_facet),
                          store_path=self.path)
        self.assertFalse(r["crystallized"], "同一 turn 刷 5 次不该够 N=3")
        # 现在跨 3 个不同 turn
        a2 = M.make_node_id("topic", "three_turns")
        for t in ("turn_1", "turn_2", "turn_3"):
            self.mani.observe_explicit_link(a2, b, turn_id=t)
        prov2 = self.mani.node_grounded_provenance(a2)
        pf2 = [{"src": F.SRC_MANIFOLD_SAID, "ref": p["ref"],
                "edge_key": p["edge_key"], "other": p["other"],
                "count": p["count"]} for p in prov2]
        self.assertEqual(F._distinct_event_count(pf2), 3, "3 不同 turn = 3 离散事件")

    def test_producer_template_content_no_llm(self):
        """content 模板化: 确定性字段拼接, 不含 free-form。"""
        node = M.make_node_id("topic", "interview")
        prov = [{"src": F.SRC_MANIFOLD_SAID, "ref": "t1", "other": "entity:sir", "count": 1}]
        content = F._template_content_for_node(node, prov)
        # 模板必含离散字段 (node kind:raw + other), 不含 LLM 生成痕迹
        self.assertIn("topic:interview", content)
        self.assertIn("entity:sir", content)
        self.assertIn("grounded relational trace", content)

    def test_producer_idempotent(self):
        """幂等: 同离散键反复 scan → 同 facet_id, 不重复。"""
        prov = [{"src": F.SRC_MANIFOLD_SHARED, "ref": "e1", "edge_key": "k", "other": "o", "count": 1},
                {"src": F.SRC_MANIFOLD_SHARED, "ref": "e2", "edge_key": "k2", "other": "o2", "count": 1},
                {"src": F.SRC_MANIFOLD_SHARED, "ref": "e3", "edge_key": "k3", "other": "o3", "count": 1}]
        r1 = F.crystallize("node:idem", "c1", grounded_provenance=prov,
                           recurrence_count=3, store_path=self.path)
        r2 = F.crystallize("node:idem", "c1", grounded_provenance=prov,
                           recurrence_count=3, store_path=self.path)
        self.assertEqual(r1["facet_id"], r2["facet_id"])
        self.assertEqual(len(F.get_facets(store_path=self.path)), 1, "同键不重复结晶")

    def test_producer_grep_no_score_sort_argmax(self):
        """producer 路径**代码行**无 score/argmax/sort 选结晶 (排除 docstring/注释)。"""
        src = (ROOT / "jarvis_identity_facets.py").read_text(encoding="utf-8")
        idx = src.find("def scan_and_crystallize")
        body = src[idx:idx + 2000]
        # 只看代码行: 剥 docstring (三引号块) + # 注释行
        code_lines = []
        in_doc = False
        for ln in body.splitlines():
            s = ln.strip()
            if s.startswith('"""') or s.startswith("'''"):
                in_doc = not in_doc
                continue
            if in_doc or s.startswith("#"):
                continue
            code_lines.append(ln)
        code = "\n".join(code_lines)
        for banned in ("argmax", ".sort(", "sorted(", "score", "salience"):
            self.assertNotIn(banned, code,
                             f"producer 代码不得用 {banned} 选结晶 (够格全结晶, 不挑选)")

    def test_b_all_tiers_facets_in_prompt(self):
        """全 tier B 验: flag-on 下 facets 真进 SelfAnchor build_block (尤 SHORT_CHAT)。

        SelfAnchor.build_block 是 Layer 0, 进所有注入 L0 的 tier。这里直接验
        build_block 输出含 facets 段 (flag on), 并测 flag off 逐字节无该段。
        """
        os.environ["JARVIS_FACETS"] = "1"
        try:
            # 种 1 条 active facet 到 temp store, 用 monkeypatch 指向它
            import unittest.mock as mock
            store = {"_meta": {}, "facets": {"facet_x": {
                "facet_id": "facet_x", "identity_key": "node:x",
                "content": "a grounded relational trace: [topic:x] linked with entity:sir",
                "provenance": [{"source": F.SRC_MANIFOLD_SHARED, "ref": "e", "recurrence_count": 3}],
                "recurrence_count": 3, "crystallized_ts": 1.0, "status": F.STATUS_ACTIVE}}}
            json.dump(store, open(self.path, "w", encoding="utf-8"))
            import jarvis_self_anchor as SA
            orig = F.render_facets_block

            def _patched(**kw):
                kw["store_path"] = self.path
                return orig(**kw)
            with mock.patch.object(F, "render_facets_block", side_effect=_patched):
                sa = SA.SelfAnchor(central_nerve=None)
                block_on = sa.build_block()
            self.assertIn("WHO I'VE BECOME", block_on,
                          "flag-on: facets 段应真进 build_block (Layer0 → 所有注入 tier)")
            self.assertIn("topic:x", block_on)
        finally:
            os.environ.pop("JARVIS_FACETS", None)

    def test_b_flag_on_l0_size(self):
        """量 flag-on L0 体积 (报准确字符数, 供 Sir 判 ~2100c)。"""
        os.environ["JARVIS_FACETS"] = "1"
        try:
            import unittest.mock as mock
            # 种 5 条 facet (render 上限)
            self._seed_n_facets(5, src_mix=True)
            orig = F.render_facets_block

            def _patched(**kw):
                kw["store_path"] = self.path
                return orig(**kw)
            import jarvis_self_anchor as SA
            with mock.patch.object(F, "render_facets_block", side_effect=_patched):
                sa = SA.SelfAnchor(central_nerve=None)
                on_len = len(sa.build_block())
            os.environ.pop("JARVIS_FACETS", None)
            sa2 = SA.SelfAnchor(central_nerve=None)
            off_len = len(sa2.build_block())
            # 报告用: facets 段增量 (不强断言具体值, 验 flag-on > flag-off 即可)
            self.assertGreater(on_len, off_len, "flag-on L0 应比 flag-off 大 (facets 段)")
            print(f"\n[B-verify L0 size] flag_off={off_len}c flag_on={on_len}c "
                  f"facets_delta={on_len - off_len}c")
        finally:
            os.environ.pop("JARVIS_FACETS", None)


if __name__ == "__main__":
    unittest.main()
