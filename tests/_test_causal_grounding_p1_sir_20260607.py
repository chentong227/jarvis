# -*- coding: utf-8 -*-
"""[causal-grounding-P1 / 2026-06-07] 对话关系事实接地: Sir 显式关系标记 → entity 节点 + SAID 边.

§9 A 前置 / 修-因果接地首刀. 顾问/Sir 阶段0 对齐放行.
管线: 关系模式正则捕获两实体槽 → _clean_entity 离散清洗 → make_node_id('entity',raw)
→ resolve 查/建 (绕开 cosine) → observe_explicit_link(PROV_SAID, ref=turn_id).

红线: 全程正则+make_node_id+exact resolve, 零相似度/embedding/cosine; 保守触发
(无标记不写); 清洗噪音宁跳过 (漏接优于假接); 结晶门槛不动; 不碰 auto_merge.

覆盖:
  T1 母亲关系重放: 母亲要做手术/母亲住进医院 → entity:母亲/手术/医院 + SAID 边
  T2 改前/改后对照: 无 caller 时 manifold 无 entity 边; 调后有
  T3 无标记不写: 并列罗列 / 无关系标记 → 不写边
  T4 噪音捕获跳过: 我妈妈明天要做手术 → 清洗出"妈妈", 不建 entity:我妈妈明天/妈明
  T5 变体不归并: 妈妈 vs 母亲 → 两不同 entity 节点, 不 cosine 合并
  T6 SAID 边 ref=turn_id + provenance kind=said (接地真实)
  T7 结晶门槛未动: qualifies 仍 ≥3 不同 ref; 同 entity 攒 3 turn 后能结晶
  T8 不回归: observe_turn_cooccurrence (COOCCUR) / observe_thought_concern_link 路径不变
  T9 清洗护栏: _clean_entity 剥前缀/去噪音/过长跳过/多词跳过 (纯离散)
  T10 零相似度静态守护: 新增函数代码无 cosine/embed/auto_merge/similar
"""
from __future__ import annotations

import os
import sys
import re
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_weaver as W
import jarvis_relational_manifold as M
import jarvis_identity_facets as F


def _mk_manifold():
    d = tempfile.mkdtemp()
    return M.RelationalManifold(os.path.join(d, "m.json"))


class TestMotherReplay(unittest.TestCase):
    def test_t1_mother_relation_creates_entity_said_edges(self):
        m = _mk_manifold()
        eks1 = W.observe_sir_relational_link("母亲要做手术", "turn_1",
                                             manifold=m, save=False)
        eks2 = W.observe_sir_relational_link("母亲住进医院", "turn_2",
                                             manifold=m, save=False)
        self.assertTrue(eks1, "母亲要做手术 应写 SAID 边")
        self.assertTrue(eks2, "母亲住进医院 应写 SAID 边")
        # 节点应含 entity:母亲 / entity:手术 / entity:医院
        nodes = set()
        for e in m._edges.values():
            nodes.add(e["a"]); nodes.add(e["b"])
        self.assertIn("entity:母亲", nodes)
        self.assertIn("entity:手术", nodes)
        self.assertIn("entity:医院", nodes)

    def test_t2_before_after_contrast(self):
        m = _mk_manifold()
        # 改前: 没有 caller → manifold 无 entity 边
        self.assertEqual(len(m._edges), 0)
        # 改后: 调用 → 有边
        W.observe_sir_relational_link("母亲要做手术", "turn_1",
                                      manifold=m, save=False)
        self.assertGreater(len(m._edges), 0)


class TestConservativeTrigger(unittest.TestCase):
    def test_t3_no_marker_no_write(self):
        m = _mk_manifold()
        # 无关系标记的并列罗列
        eks = W.observe_sir_relational_link("买了牛奶面包鸡蛋", "turn_1",
                                            manifold=m, save=False)
        self.assertEqual(eks, [])
        self.assertEqual(len(m._edges), 0)

    def test_t3b_bare_status_no_two_entity(self):
        m = _mk_manifold()
        # "妈妈住院了" 无 "A住进B" 两实体标记 → 不写 (保守)
        eks = W.observe_sir_relational_link("妈妈住院了", "turn_1",
                                            manifold=m, save=False)
        self.assertEqual(eks, [])


class TestNoiseCaptureSkip(unittest.TestCase):
    def test_t4_noise_prefix_cleaned_no_garbage_node(self):
        m = _mk_manifold()
        W.observe_sir_relational_link("我妈妈明天要做手术", "turn_1",
                                      manifold=m, save=False)
        nodes = set()
        for e in m._edges.values():
            nodes.add(e["a"]); nodes.add(e["b"])
        # 清洗出 "妈妈" (剥"我"前缀 + 去"明天"噪音), 不建垃圾节点
        self.assertIn("entity:妈妈", nodes)
        self.assertNotIn("entity:我妈妈明天", nodes)
        self.assertNotIn("entity:妈明", nodes)
        self.assertNotIn("entity:我妈妈", nodes)


class TestVariantNoMerge(unittest.TestCase):
    def test_t5_variants_distinct_nodes_no_cosine_merge(self):
        m = _mk_manifold()
        W.observe_sir_relational_link("妈妈要做手术", "turn_1",
                                      manifold=m, save=False)
        W.observe_sir_relational_link("母亲要做手术", "turn_2",
                                      manifold=m, save=False)
        nodes = set()
        for e in m._edges.values():
            nodes.add(e["a"]); nodes.add(e["b"])
        # 妈妈 / 母亲 = 两个不同 entity 节点 (不归并)
        self.assertIn("entity:妈妈", nodes)
        self.assertIn("entity:母亲", nodes)
        # 无 alias 合并 (绕开 cosine)
        self.assertEqual(m.get_aliases(), {})


class TestSaidEdgeGrounding(unittest.TestCase):
    def test_t6_edge_is_said_with_turn_id_ref(self):
        m = _mk_manifold()
        W.observe_sir_relational_link("母亲要做手术", "turn_xyz",
                                      manifold=m, save=False)
        e = None
        for ed in m._edges.values():
            e = ed
            break
        self.assertIsNotNone(e)
        provs = e.get("provenance", [])
        self.assertTrue(any(p.get("kind") == M.PROV_SAID for p in provs),
                        "边 provenance 应含 PROV_SAID")
        self.assertTrue(any(p.get("ref") == "turn_xyz" for p in provs),
                        "SAID 边 ref 应是 turn_id")


class TestCrystallizationThresholdUntouched(unittest.TestCase):
    def test_t7_qualifies_unchanged_and_entity_can_crystallize(self):
        # 门槛逐字节: qualifies 仍 ≥3 + 接地 + 正交
        self.assertEqual(F.RECURRENCE_MIN_N, 3)
        m = _mk_manifold()
        # 同 entity 对攒 3 不同 turn 的 SAID 边
        for t in ("turn_1", "turn_2", "turn_3"):
            W.observe_sir_relational_link("母亲要做手术", t,
                                          manifold=m, save=False)
        prov = m.node_grounded_provenance("entity:母亲")
        # 不同 ref (turn) 数应 = 3 (entity:母亲~entity:手术 跨 3 turn)
        refs = {p["ref"] for p in prov}
        self.assertGreaterEqual(len(refs), 3,
                                "母亲节点应有 ≥3 不同 turn ref 的接地边")


class TestNoRegression(unittest.TestCase):
    def test_t8_cooccur_and_concern_paths_intact(self):
        m = _mk_manifold()
        # COOCCUR 路径 (observe_turn_cooccurrence 走 observe_cooccurrence) 仍在
        self.assertTrue(hasattr(m, "observe_cooccurrence"))
        self.assertTrue(hasattr(m, "observe_shared_entity"))
        # observe_thought_concern_link 仍可调
        self.assertTrue(hasattr(W, "observe_thought_concern_link"))
        # 直接验 cooccur 仍写 COOCCUR 边
        a = M.make_node_id(M.KIND_THREAD, "t1")
        b = M.make_node_id(M.KIND_CONCERN, "c1")
        m.observe_cooccurrence([a, b], "turn_1")
        e = m.get_edge(a, b)
        self.assertIsNotNone(e)
        self.assertTrue(any(p.get("kind") == M.PROV_COOCCUR
                            for p in e.get("provenance", [])))


class TestCleanEntityGuardrail(unittest.TestCase):
    def test_t9_clean_entity_discrete(self):
        # 剥人称前缀
        self.assertEqual(W._clean_entity("我妈妈"), "妈妈")
        self.assertEqual(W._clean_entity("他公司"), "公司")
        # 去时间噪音
        self.assertEqual(W._clean_entity("明天手术"), "手术")
        # 英文 lower + strip
        self.assertEqual(W._clean_entity("  Hospital "), "hospital")
        # 过长 → None
        self.assertIsNone(W._clean_entity("一二三四五六七八九十"))
        # 空 → None
        self.assertIsNone(W._clean_entity(""))
        # 剥光成空 → None (纯前缀/噪音)
        self.assertIsNone(W._clean_entity("明天"))


class TestZeroSimilarityStaticGuard(unittest.TestCase):
    def test_t10_no_similarity_in_new_code(self):
        src = open(os.path.join(ROOT, "jarvis_relational_weaver.py"),
                   encoding="utf-8").read()
        # 抽 observe_sir_relational_link + _clean_entity 函数体
        for fn in ("def observe_sir_relational_link", "def _clean_entity"):
            idx = src.find(fn)
            self.assertGreater(idx, 0, f"{fn} 应存在")
            body = src[idx:idx + 2500]
            # 剥注释行 (# 开头) + docstring 后再查
            code_lines = []
            in_doc = False
            for ln in body.splitlines():
                st = ln.strip()
                if st.startswith('"""'):
                    in_doc = not in_doc if st.count('"""') == 1 else in_doc
                    continue
                if in_doc or st.startswith("#"):
                    continue
                code_lines.append(ln)
            code = "\n".join(code_lines).lower()
            for bad in ("cosine", "embed", "auto_merge", "similar", "argmax",
                        "add_geometric"):
                self.assertNotIn(bad, code,
                                 f"{fn} 代码行不应含相似度 token '{bad}'")


if __name__ == "__main__":
    unittest.main()
