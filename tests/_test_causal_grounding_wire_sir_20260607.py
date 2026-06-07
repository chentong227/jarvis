# -*- coding: utf-8 -*-
"""[causal-grounding-wire / 2026-06-07] 因果接地接生产 caller (热路径接线) 验证.

接线点: jarvis_chat_bypass.py _run_body_writeback 闭包内, observe_turn_cooccurrence 后.
只喂 Sir 原话 (clean_user_input), 绝不喂 final_reply (防 Jarvis 自产话当 Sir 接地).

本测复刻接线契约 (闭包逻辑 = 只取 _su=clean_user_input, 空跳过, 与 COOCCUR 并存),
+ 静态守护接线源码 (证默认参绑定 / 只喂 clean_user_input / fail-safe).

覆盖:
  T1 真走 turn 母亲句: Sir "母亲要做手术" → entity:母亲~entity:手术 SAID(ref=turn_id)
  T2 非关系句不写: Sir "现在很累" → 不写
  T3 Jarvis 自产话不触发: final_reply 含"X要做Y" + clean_user_input 无关系 → 不写
     (证明只喂 clean_user_input 没喂 final_reply)
  T4 空 user 跳过: clean_user_input 空 → 跳过不报错
  T5 COOCCUR 并存: 同 turn COOCCUR 边仍写 (因果 SAID 不抢路)
  T6 fail-safe: 因果函数抛异常 → 闭包逻辑不崩
  T7 接线源码静态守护: chat_bypass 接线处 _su=clean_user_input 默认参绑定 + 不喂 final_reply
"""
from __future__ import annotations

import os
import sys
import re
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_weaver as W
import jarvis_relational_manifold as M


def _mk_manifold():
    d = tempfile.mkdtemp()
    return M.RelationalManifold(os.path.join(d, "m.json"))


def _run_wire_closure(clean_user_input, final_reply, turn_id, manifold):
    """复刻 chat_bypass _run_body_writeback 闭包的接线契约 (用注入 manifold)。

    = COOCCUR(喂拼接) + 因果 SAID(只喂 clean_user_input, 空跳过), 各自 try/except。
    """
    _wb_txt = ((clean_user_input or '') + ' \n ' + (final_reply or '')).strip()
    _su = (clean_user_input or '')
    # COOCCUR (喂 _wb_txt — 不动)
    try:
        if _wb_txt:
            W.observe_turn_cooccurrence(_wb_txt, turn_id, manifold=manifold,
                                        save=False)
    except Exception:
        pass
    # 因果 SAID (只喂 _su = clean_user_input)
    try:
        if _su.strip():
            W.observe_sir_relational_link(_su, turn_id, manifold=manifold,
                                          save=False)
    except Exception:
        pass


def _nodes(m):
    s = set()
    for e in m._edges.values():
        s.add(e["a"]); s.add(e["b"])
    return s


class TestWireContract(unittest.TestCase):
    def test_t1_mother_turn_writes_said(self):
        m = _mk_manifold()
        _run_wire_closure("母亲要做手术", "明白先生, 我会留意", "turn_m1", m)
        ns = _nodes(m)
        self.assertIn("entity:母亲", ns)
        self.assertIn("entity:手术", ns)
        # SAID 边 ref = turn_id
        said = [e for e in m._edges.values()
                if any(p.get("kind") == M.PROV_SAID for p in e.get("provenance", []))]
        self.assertTrue(said, "应有 SAID 边")
        self.assertTrue(any(
            any(p.get("ref") == "turn_m1" for p in e.get("provenance", []))
            for e in said))

    def test_t2_non_relational_no_write(self):
        m = _mk_manifold()
        _run_wire_closure("现在很累", "先生注意休息", "turn_x", m)
        self.assertNotIn("entity:现", _nodes(m))
        self.assertNotIn("entity:很累", _nodes(m))
        # 无 SAID 边
        said = [e for e in m._edges.values()
                if any(p.get("kind") == M.PROV_SAID for p in e.get("provenance", []))]
        self.assertEqual(said, [])

    def test_t3_jarvis_reply_does_not_trigger(self):
        """★关键: final_reply 含关系词, clean_user_input 无 → 不写 SAID (只喂 Sir 原话)."""
        m = _mk_manifold()
        # Jarvis 回话含"母亲要做手术"关系词, 但 Sir 原话只是"好的"
        _run_wire_closure("好的", "我记得您母亲要做手术, 已安排提醒", "turn_j1", m)
        # 不应出现 entity:母亲/手术 的 SAID 边 (final_reply 没喂给因果函数)
        said = [e for e in m._edges.values()
                if any(p.get("kind") == M.PROV_SAID for p in e.get("provenance", []))]
        self.assertEqual(said, [],
                         "Jarvis 自产话不该触发因果 SAID (证明没喂 final_reply)")
        self.assertNotIn("entity:母亲", _nodes(m))

    def test_t4_empty_user_skips(self):
        m = _mk_manifold()
        # clean_user_input 空 (nudge/系统触发), final_reply 有内容
        _run_wire_closure("", "系统提醒: 母亲要做手术", "turn_sys", m)
        said = [e for e in m._edges.values()
                if any(p.get("kind") == M.PROV_SAID for p in e.get("provenance", []))]
        self.assertEqual(said, [], "空 user 应跳过因果写入")

    def test_t5_cooccur_coexists(self):
        # COOCCUR 仍写 (喂 _wb_txt). 用真实节点文本让 cooccur 命中 ≥2.
        m = _mk_manifold()
        tmap = {
            M.make_node_id(M.KIND_CONCERN, "sir_sleep"): "Sir 连续熬夜风险",
            M.make_node_id(M.KIND_CONCERN, "sir_pomo"): "Sir 番茄钟工作节奏",
        }
        # 直接验 observe_turn_cooccurrence 仍写 COOCCUR (接线不动它)
        n = W.observe_turn_cooccurrence("熬夜 又 番茄钟", "turn_c1",
                                        text_map=tmap, manifold=m, save=False)
        self.assertGreaterEqual(n, 1)
        cooccur = [e for e in m._edges.values()
                   if any(p.get("kind") == M.PROV_COOCCUR
                          for p in e.get("provenance", []))]
        self.assertTrue(cooccur, "COOCCUR 边应照常写")

    def test_t6_failsafe_on_exception(self):
        m = _mk_manifold()
        with mock.patch.object(W, "observe_sir_relational_link",
                               side_effect=RuntimeError("boom")):
            # 闭包逻辑应被 try/except 兜住, 不抛
            try:
                _run_wire_closure("母亲要做手术", "ok", "turn_e", m)
            except Exception:
                self.fail("接线闭包应 fail-safe, 不该抛")


class TestWireSourceStaticGuard(unittest.TestCase):
    def test_t7_wiring_source_only_feeds_clean_user_input(self):
        src = open(os.path.join(ROOT, "jarvis_chat_bypass.py"),
                   encoding="utf-8").read()
        idx = src.find("def _run_body_writeback")
        self.assertGreater(idx, 0)
        body = src[idx:idx + 1200]
        # 默认参绑定 _su=clean_user_input (防闭包延迟绑定)
        self.assertIn("_su=", body)
        self.assertIn("clean_user_input", body)
        # 调因果函数只喂 _su, 不喂 _wb_txt/final_reply
        self.assertIn("observe_sir_relational_link(_su", body)
        self.assertNotIn("observe_sir_relational_link(_wb_txt", body)
        self.assertNotIn("observe_sir_relational_link(final_reply", body)


if __name__ == "__main__":
    unittest.main()
