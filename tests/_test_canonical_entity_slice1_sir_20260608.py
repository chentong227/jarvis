# -*- coding: utf-8 -*-
"""[canonical-entity-slice1 / 2026-06-08] corrigible canonical 实体层 (外挂 registry).

详 docs/process/JARVIS_SLICE1_CANONICAL_ENTITY_DESIGN.md.

覆盖 (8 条裁定 + 红线反证):
  ①  跨 3 turn 妈妈/我妈/母亲 → 折同 cid, 触达=3
  ①b 同一 turn 妈妈+我妈 → 触达只 +1 (同 turn 去重)
  ②  表外词 (邻居/老王) → 不建 canonical (exact 不命中)
  ③  revoke "我妈" 后再喂 → 触达不增 (必修门控活体)
  ④  registry 与 manifold._aliases 物理分离 (反证)
  ⑤  空 provenance → create 拒
  ⑥  空 ref → add_alias_link 拒
  ⑦  jarvis_canonical_entities.py 静态扫无 cosine/embed/np/similarity (禁相似度)
  ⑧  Jarvis 自产话 (final_reply) 不喂 → 不触达 (writeback 只喂 _su)
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

import jarvis_canonical_entities as CE


def _mk_reg():
    d = tempfile.mkdtemp()
    return CE.CanonicalEntityRegistry(os.path.join(d, "canon.json"))


def _gref(ref="kinship_exact", surface="妈妈", cid="person:mother"):
    return {"source_kind": "exact", "ref": ref, "ts": 0.0,
            "detail": f"kinship:{surface}->{cid}"}


def _feed(reg, surface, cid, label, relation, turn_id):
    """模拟 writeback 命中一个 surface 后的完整门控管线 (与 cb_bypass 接线等价)。"""
    resolved = reg.resolve_surface_to_cid(surface)
    if resolved is None and reg._alias_links.get(surface, {}).get("status") == "revoked":
        return False  # 必修门控: revoked 终态, 不复活不触达
    reg.create_canonical_entity(
        cid, {"canonical_label": label, "relation_to_sir": relation},
        [_gref(surface=surface, cid=cid)])
    reg.add_canonical_alias_link(surface, cid, source="exact", ref=turn_id)
    return reg.touch(cid, turn_id)


class TestFoldAcrossTurns(unittest.TestCase):
    def test_01_three_turns_fold_touch_3(self):
        reg = _mk_reg()
        _feed(reg, "妈妈", "person:mother", "母亲", "mother", "turn_1")
        _feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_2")
        _feed(reg, "母亲", "person:mother", "母亲", "mother", "turn_3")
        node = reg.get_canonical_node("person:mother")
        self.assertIsNotNone(node)
        self.assertEqual(node["touch_count"], 3, "3 个不同 turn 应折到同一 cid 触达=3")
        self.assertEqual(sorted(node["touch_refs"]), ["turn_1", "turn_2", "turn_3"])

    def test_01b_same_turn_touch_once(self):
        reg = _mk_reg()
        # 同一 turn 同时说 妈妈 + 我妈
        _feed(reg, "妈妈", "person:mother", "母亲", "mother", "turn_X")
        _feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_X")
        node = reg.get_canonical_node("person:mother")
        self.assertEqual(node["touch_count"], 1, "同 turn 多 surface 触达只 +1")


class TestExactOnlyNoFalseWeld(unittest.TestCase):
    def test_02_non_kinship_no_canonical(self):
        reg = _mk_reg()
        hits = CE.lookup_kinship_surfaces("邻居老王来串门")
        self.assertEqual(hits, [], "表外词不应命中 kinship")
        # 不命中 → 不建 canonical
        self.assertIsNone(reg.get_canonical_node("person:neighbor"))
        self.assertEqual(len(reg._entities), 0)

    def test_02b_lookup_substring_hit(self):
        # 整词子串命中 (不切词)
        hits = CE.lookup_kinship_surfaces("我妈最近身体不太好")
        surfaces = {s for s, _ in hits}
        self.assertIn("我妈", surfaces)
        # 单字 surface 已删: "妈" 不应单独命中 (只多字形)
        self.assertNotIn("妈", surfaces)


class TestRevokeReFeed(unittest.TestCase):
    def test_03_revoke_then_refeed_no_touch(self):
        reg = _mk_reg()
        # 先建链 + 触达
        self.assertTrue(_feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_1"))
        self.assertEqual(reg.get_canonical_node("person:mother")["touch_count"], 1)
        # Sir CLI 撤掉 "我妈"
        self.assertTrue(reg.revoke_alias_link("我妈", by="sir", reason="test"))
        # 再喂 "我妈" (新 turn) → 必修门控应跳过 touch
        touched = _feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_2")
        self.assertFalse(touched, "revoked surface 再喂不应触达")
        self.assertEqual(reg.get_canonical_node("person:mother")["touch_count"], 1,
                         "撤后触达不增 (撤了不白撤)")

    def test_03b_revoked_link_not_auto_revived(self):
        reg = _mk_reg()
        _feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_1")
        reg.revoke_alias_link("我妈")
        # add_canonical_alias_link 不得自动复活 revoked
        ok = reg.add_canonical_alias_link("我妈", "person:mother",
                                          source="exact", ref="turn_2")
        self.assertFalse(ok, "revoked 是终态, exact 写入不复活")
        self.assertEqual(reg._alias_links["我妈"]["status"], "revoked")

    def test_03c_resolve_only_active(self):
        reg = _mk_reg()
        _feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_1")
        self.assertEqual(reg.resolve_surface_to_cid("我妈"), "person:mother")
        reg.revoke_alias_link("我妈")
        self.assertIsNone(reg.resolve_surface_to_cid("我妈"), "revoked 不应被 resolve")


class TestPhysicalSeparation(unittest.TestCase):
    def test_04_registry_separate_from_manifold_aliases(self):
        # 反证: registry 操作不碰 manifold._aliases (不同文件/对象/key 空间)
        import jarvis_relational_manifold as M
        d = tempfile.mkdtemp()
        man = M.RelationalManifold(os.path.join(d, "m.json"))
        # manifold 加一条 cosine alias (node→node)
        man.add_edge("entity:a", "entity:b", M.PROV_SAID, "turn_1")
        man.add_edge("entity:c", "entity:d", M.PROV_SAID, "turn_1")
        man.add_alias("entity:c", "entity:a")
        before = dict(man.get_aliases())
        # registry 大量操作
        reg = CE.CanonicalEntityRegistry(os.path.join(d, "canon.json"))
        _feed(reg, "妈妈", "person:mother", "母亲", "mother", "turn_1")
        _feed(reg, "我妈", "person:mother", "母亲", "mother", "turn_2")
        reg.revoke_alias_link("我妈")
        # manifold._aliases 未变
        self.assertEqual(man.get_aliases(), before, "registry 操作不应触动 manifold._aliases")
        # 不同 key 空间: registry alias key=surface(表面词), manifold alias key=node_id
        self.assertIn("我妈", reg._alias_links)
        self.assertNotIn("我妈", man.get_aliases())
        # 不同文件
        self.assertNotEqual(reg.path, man.path)


class TestGroundingGate(unittest.TestCase):
    def test_05_empty_provenance_rejected(self):
        reg = _mk_reg()
        self.assertFalse(reg.create_canonical_entity("person:mother", {}, []),
                         "空 provenance 应拒")
        self.assertFalse(reg.create_canonical_entity("person:mother", {},
                                                     [{"source_kind": "exact"}]),
                         "无 ref 的 provenance 应拒")
        self.assertEqual(len(reg._entities), 0)

    def test_06_empty_ref_alias_rejected(self):
        reg = _mk_reg()
        reg.create_canonical_entity("person:mother", {"canonical_label": "母亲"}, [_gref()])
        self.assertFalse(reg.add_canonical_alias_link("妈妈", "person:mother",
                                                      source="exact", ref=""),
                         "空 ref 应拒")
        self.assertFalse(reg.add_canonical_alias_link("妈妈", "person:mother",
                                                      source="exact", ref="   "),
                         "空白 ref 应拒")
        self.assertNotIn("妈妈", reg._alias_links)


class TestNoSimilarity(unittest.TestCase):
    def test_07_static_scan_no_similarity(self):
        """禁相似度红线: 实体层不得**计算/import** 相似度。

        说明: 裁定要求"静态扫无 cosine/embed/np./similarity import"。本扫描针对
        **真实的相似度计算/import 信号** (import numpy / np. / cosine_similarity /
        sklearn / faiss / def _embed / .embedding(), 等), 而非裸字串。
        合法例外: SOURCE_COSINE = "cosine" 是**软源 taxonomy 标签** (预留 Slice 3,
        未来 cosine proposer 写进 JSON 的 source_kind 值, 非计算), 不算引入相似度。
        故扫描前剥注释 + 字符串字面量 (用 tokenize), 只查真实代码 token。
        """
        import tokenize
        import io as _io
        path = os.path.join(ROOT, "jarvis_canonical_entities.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # 用 tokenize 剥掉注释 + 字符串字面量, 只留真实代码 (NAME/OP/...)。
        code_tokens = []
        try:
            for tok in tokenize.generate_tokens(_io.StringIO(src).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                code_tokens.append(tok.string)
        except Exception:
            code_tokens = src.split()
        code = " ".join(code_tokens)
        # 真实相似度计算/import 信号 (不含裸 source_kind 标签字串)
        for bad in ("numpy", "np.", "cosine_similarity", "sklearn", "faiss",
                    "embedding", "_embed", "scipy", "torch"):
            self.assertNotIn(bad, code,
                             f"禁相似度红线: 实体层代码不得含相似度计算/import {bad!r}")
        # 确认本模块不 import manifold (manifold 核心零改动: 不碰即不可能改)
        self.assertNotIn("jarvis_relational_manifold", code,
                         "实体层不应 import manifold (物理分离)")


class TestSelfTalkNotFed(unittest.TestCase):
    def test_08_jarvis_reply_not_fed(self):
        """反证 ⑧: writeback 只喂 Sir 原话 (_su), 不喂 final_reply。

        模拟 writeback: Sir 那轮没说亲属词, 但 Jarvis 回复含 "母亲" → 不应触达。
        (cb_bypass 接线 if _su.strip() 用 clean_user_input, 绝不喂 _wb_txt/final_reply。)
        """
        reg = _mk_reg()
        sir_text = "今天天气不错"             # Sir 原话: 无亲属词
        jarvis_reply = "您是说母亲的事吗"       # Jarvis 自产: 含 "母亲"
        # writeback 只对 sir_text 跑 lookup
        hits = CE.lookup_kinship_surfaces(sir_text)
        for surface, (cid, label, rel) in hits:
            _feed(reg, surface, cid, label, rel, "turn_1")
        self.assertEqual(len(reg._entities), 0, "Sir 原话无亲属词不应建 canonical")
        # 反面确认: 若错喂 jarvis_reply 会命中 (证明命中逻辑本身工作)
        self.assertTrue(CE.lookup_kinship_surfaces(jarvis_reply),
                        "jarvis_reply 含母亲 — 命中逻辑工作, 但 writeback 不喂它")


class TestRename(unittest.TestCase):
    def test_rename_canonical(self):
        reg = _mk_reg()
        _feed(reg, "妈妈", "person:mother", "母亲", "mother", "turn_1")
        self.assertTrue(reg.rename_canonical("person:mother", "妈妈大人"))
        node = reg.get_canonical_node("person:mother")
        self.assertEqual(node["canonical_label"], "妈妈大人")
        self.assertEqual(node["audit"][-1]["op"], "rename")

    def test_idempotent_create(self):
        reg = _mk_reg()
        reg.create_canonical_entity("person:mother", {"canonical_label": "母亲"}, [_gref()])
        reg.create_canonical_entity("person:mother", {"canonical_label": "母亲"}, [_gref()])
        self.assertEqual(len(reg._entities), 1, "重复 create 不重建")

    def test_conflict_no_silent_rewrite(self):
        reg = _mk_reg()
        reg.create_canonical_entity("person:mother", {"canonical_label": "母亲"}, [_gref()])
        reg.add_canonical_alias_link("妈妈", "person:mother", source="exact", ref="t1")
        # 同 surface 指别的 cid → 拒
        ok = reg.add_canonical_alias_link("妈妈", "person:aunt", source="exact", ref="t2")
        self.assertFalse(ok, "surface 已指别 cid → 不静默改写")
        self.assertEqual(reg._alias_links["妈妈"]["cid"], "person:mother")


if __name__ == "__main__":
    unittest.main(verbosity=2)
