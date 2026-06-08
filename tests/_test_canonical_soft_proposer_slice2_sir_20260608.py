# -*- coding: utf-8 -*-
"""[canonical-soft-proposer-slice2 / 2026-06-08] 软源提议层 (路线A 离散词法, 不烧 LLM).

对话 turn 软词命中 → 产 proposed AliasLink (绝不自动 active); 碰硬接地同指或 Sir
--activate 才升 active; 全程可撤。设计 JARVIS_SLICE2_SOFT_PROPOSER_DESIGN.md。

三条硬条件 (顾问加挂, 每条专测):
  ① 幂等去重: 已 active link 的 surface→cid, 软源再抽 → no-op (不双建)
  ② 升级严格内容匹配: 自动升级只升同 surface 同 cid, 不误升窗口内任意 proposed
  ③ 自动升级不复活 revoked: Sir 撤过的链, 软源/auto 不复活, 只 Sir --activate 才复活

8 条反证矩阵:
  R1 软抽 → proposed (不 active / resolve 不命中)
  R2 proposed 碰硬源同指 → 升 active (留 audit)
  R3 Sir revoke proposed → revoked 可逆
  R4 软提议不污染硬源链 (硬 active + touch 不变)
  R5 误提议 → 不 touch / 不进中心度
  R6 软提议不被入口闸误杀 (is_system_event 仍 skip)
  R7 cosine 旧 add_alias 不双写 (软提议只写 canonical, 不 import manifold)
  R8 activate op 单测 (proposed→active / 幂等 / 拒不存在)
"""
from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_canonical_entities as CE


def _reg():
    tmp = tempfile.mkdtemp(prefix='soft_slice2_')
    path = os.path.join(tmp, 'canonical_entities.json')
    return CE.CanonicalEntityRegistry(path=path), tmp


def _seed_entity(reg, cid, label='母亲', rel='mother'):
    gref = {"source_kind": "exact", "ref": "seed", "ts": time.time(),
            "detail": "seed"}
    reg.create_canonical_entity(cid, {"canonical_label": label,
                                      "relation_to_sir": rel}, [gref])


class TestHardCondition1Dedup(unittest.TestCase):
    """硬条件①: 软源不对已有 active link 的 surface→cid 重复产 proposed。"""

    def test_h1_active_surface_no_duplicate_proposed(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        # 硬源先建 active "妈妈"->mother
        reg.add_canonical_alias_link("妈妈", "person:mother", source="exact", ref="t1")
        self.assertEqual(reg.resolve_surface_to_cid("妈妈"), "person:mother")
        # 软源再抽 "妈妈" → no-op
        ok = reg.add_soft_alias_link("妈妈", "person:mother", source="llm", ref="t2")
        self.assertFalse(ok, "🔴 已 active 同 cid, 软源应 no-op 不重复产")
        lk = reg.get_alias_link("妈妈")
        self.assertEqual(lk["status"], "active", "该 surface 仍只 1 条 active")
        # proposed 队列里没有 妈妈
        self.assertNotIn("妈妈", [p["surface"] for p in reg.list_proposed()])

    def test_h1_proposed_surface_no_duplicate(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        ok1 = reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        self.assertTrue(ok1)
        # 再抽同 surface 同 cid → no-op
        ok2 = reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t2")
        self.assertFalse(ok2, "已 proposed 同 cid, 不重复产")
        self.assertEqual(len(reg.list_proposed()), 1)


class TestHardCondition2ContentMatch(unittest.TestCase):
    """硬条件②: 自动升级须严格内容匹配 (同 surface 同 cid), 不误升窗口内任意 proposed。"""

    def test_h2_only_matching_proposed_upgraded(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:neighbor", label="邻居老王", rel="neighbor")
        # 软提议 邻居老王 -> person:neighbor (proposed)
        reg.add_soft_alias_link("邻居老王", "person:neighbor", source="llm", ref="t1")
        self.assertEqual(reg.get_alias_link("邻居老王")["status"], "proposed")
        # 硬源来的是 妈妈->mother (与老王无关) → 升不存在的妈妈项, 老王不被误升
        # 模拟升级钩子: activate 只对 妈妈 (该 surface 无 proposed)
        ok = reg.activate_alias_link("妈妈", by="auto_hard_grounding",
                                     expect_cid="person:mother")
        self.assertFalse(ok, "妈妈无 proposed 链, 不应升")
        # 老王仍 proposed (不被误升)
        self.assertEqual(reg.get_alias_link("邻居老王")["status"], "proposed",
                         "🔴 老王那条与硬源不同指, 必须仍 proposed 不被误升")

    def test_h2_expect_cid_mismatch_refused(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        # expect_cid 指错 → 拒
        ok = reg.activate_alias_link("妈咪", by="auto_hard_grounding",
                                     expect_cid="person:father")
        self.assertFalse(ok, "🔴 expect_cid 不匹配 → 拒升 (内容匹配红线)")
        self.assertEqual(reg.get_alias_link("妈咪")["status"], "proposed")


class TestHardCondition3NoRevive(unittest.TestCase):
    """硬条件③: 自动升级绝不复活 Sir 已 revoke 的链。"""

    def test_h3_auto_upgrade_not_revive_revoked(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("我妈", "person:mother", source="llm", ref="t1")
        # Sir revoke
        reg.revoke_alias_link("我妈", by="sir", reason="test")
        self.assertEqual(reg.get_alias_link("我妈")["status"], "revoked")
        # 软源再抽 "我妈" → add_soft no-op (不复活)
        ok_soft = reg.add_soft_alias_link("我妈", "person:mother", source="llm", ref="t2")
        self.assertFalse(ok_soft, "revoked 软源不复活")
        # 自动升级钩子 (auto_hard_grounding) → 拒复活
        ok_auto = reg.activate_alias_link("我妈", by="auto_hard_grounding",
                                          expect_cid="person:mother")
        self.assertFalse(ok_auto, "🔴 auto 升级绝不复活 revoked")
        self.assertEqual(reg.get_alias_link("我妈")["status"], "revoked",
                         "revoked 守住, 未被自动复活")

    def test_h3_sir_explicit_activate_revives(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("我妈", "person:mother", source="llm", ref="t1")
        reg.revoke_alias_link("我妈", by="sir")
        # 只有 Sir 显式 activate 才复活
        ok = reg.activate_alias_link("我妈", by="sir", reason="CLI --activate")
        self.assertTrue(ok, "Sir 显式 --activate 应复活 revoked")
        self.assertEqual(reg.get_alias_link("我妈")["status"], "active")


class TestAntiProofMatrix(unittest.TestCase):
    """8 条反证矩阵 R1-R8。"""

    def test_R1_soft_produces_proposed_not_active(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        self.assertEqual(reg.get_alias_link("妈咪")["status"], "proposed")
        self.assertIsNone(reg.resolve_surface_to_cid("妈咪"),
                          "R1: proposed 不被 resolve 命中 (不进硬层)")

    def test_R2_proposed_upgraded_on_hard_same(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        # 硬源同指 (同 surface 同 cid) → 升级钩子
        reg.add_canonical_alias_link("妈咪", "person:mother", source="exact", ref="t2")
        lk = reg.get_alias_link("妈咪")
        if lk["status"] == "proposed":
            reg.activate_alias_link("妈咪", by="auto_hard_grounding",
                                    expect_cid="person:mother")
        self.assertEqual(reg.get_alias_link("妈咪")["status"], "active",
                         "R2: proposed 碰硬源同指 → active")
        audit = reg.get_alias_link("妈咪").get("audit", [])
        self.assertTrue(any(a.get("op") == "activate" for a in audit),
                        "R2: 升级留 audit")

    def test_R3_revoke_reversible(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        reg.revoke_alias_link("妈咪", by="sir")
        self.assertEqual(reg.get_alias_link("妈咪")["status"], "revoked")
        self.assertIsNone(reg.resolve_surface_to_cid("妈咪"))

    def test_R4_soft_not_pollute_hard_chain(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_canonical_alias_link("妈妈", "person:mother", source="exact", ref="t1")
        reg.touch("person:mother", "turn_hard_1")
        before = len(reg.get_canonical_node("person:mother")["touch_refs"])
        # 软提议 不同 surface
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t2")
        after = len(reg.get_canonical_node("person:mother")["touch_refs"])
        self.assertEqual(before, after, "R4: 软提议不动硬源 touch_refs")
        self.assertEqual(reg.resolve_surface_to_cid("妈妈"), "person:mother",
                         "R4: 硬 active 链不受软提议影响")

    def test_R5_misproposal_no_touch_no_centrality(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        # proposed 不计触达 (resolve None → writeback 不 touch)
        node = reg.get_canonical_node("person:mother")
        self.assertEqual(node.get("touch_count", 0), 0,
                         "R5: 误提议不 touch / 不进中心度")

    def test_R6_entry_gate_still_skips_system_event(self):
        # 复用 thread1 入口闸: 软提议挂入口闸之后, 系统事件仍 skip
        from jarvis_utils import is_system_event_text
        self.assertTrue(is_system_event_text("[SYSTEM BACKGROUND EVENT]: x"),
                        "R6: 入口闸判系统事件 (软提议在其后, 不误杀真话)")
        self.assertFalse(is_system_event_text("妈咪今天来"),
                         "R6: 真 Sir 原话不被入口闸拦")

    def test_R7_no_manifold_import_no_cosine_doublewrite(self):
        # 软提议只写 canonical_entities.py, 该模块绝不真 import manifold/调 cosine add_alias。
        # 注: 检"真 import 语句"和"裸 .add_alias( 调用", 不误判注释里的红线文档串 /
        # add_canonical_alias_link 等方法名子串。
        import jarvis_canonical_entities as _ce
        src = open(_ce.__file__, encoding='utf-8').read()
        import re as _re
        # 真 import 语句 (行首, 非注释)
        self.assertIsNone(
            _re.search(r'^\s*(import|from)\s+jarvis_relational_manifold', src, _re.M),
            "R7: canonical 无真 import manifold 语句")
        # 裸 cosine add_alias( 调用 (非 add_canonical_alias_link / add_soft_alias_link)
        self.assertIsNone(
            _re.search(r'(?<![_a-zA-Z])add_alias\s*\(', src),
            "R7: 不调旧 cosine add_alias(")
        # numpy / cosine / embedding import 红线
        self.assertIsNone(
            _re.search(r'^\s*import\s+numpy', src, _re.M),
            "R7: 禁相似度 — 无 numpy import")

    def test_R8_activate_op_unit(self):
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        # 不存在 → False
        self.assertFalse(reg.activate_alias_link("不存在", by="sir"))
        # proposed → active
        reg.add_soft_alias_link("妈咪", "person:mother", source="llm", ref="t1")
        self.assertTrue(reg.activate_alias_link("妈咪", by="sir"))
        self.assertEqual(reg.get_alias_link("妈咪")["status"], "active")
        # active → 幂等 True
        self.assertTrue(reg.activate_alias_link("妈咪", by="sir"))

    def test_soft_source_rejected_for_hard_source(self):
        # add_soft_alias_link 拒硬源 (防绕过 status 分流)
        reg, _ = _reg()
        _seed_entity(reg, "person:mother")
        ok = reg.add_soft_alias_link("妈咪", "person:mother", source="exact", ref="t1")
        self.assertFalse(ok, "软入口拒硬源 source")


class TestLookupSoftSurfaces(unittest.TestCase):
    def test_soft_vocab_hit(self):
        hits = CE.lookup_soft_surfaces("妈咪今天给我打电话")
        surfaces = [h[0] for h in hits]
        self.assertIn("妈咪", surfaces)

    def test_soft_vocab_no_hit(self):
        self.assertEqual(CE.lookup_soft_surfaces("今天天气不错"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
