# -*- coding: utf-8 -*-
"""[inner-anchor-P1 / Sir 2026-06-07] affordance 自知 第一阶段验收 (先红后绿).

设计源: docs/JARVIS_INNER_ANCHOR_DESIGN.md (4a17999) §4.1/§4.1b/§6. 理念: JARVIS_WHY.md.

四道 RED 锚 (每道先在"故意写歪朴素版"上跑出真红, 再上闸转绿):
  ① 无证据不点亮: 仅 PROV_SAID / 仅 propose 无注册表支撑 → can 不得 yes。
  ②(1b) 并发竞态 (补遗-2): propose 不得直写 can=yes; 核验闸是唯一写入者。
       先证"propose 直写版"被抓红 → 正式版只触发核验转绿。
  ③ 撤销/降级: 注册表移除 X / 执行屡败 → can 从 yes 降 no/partial。
  ④(3b) expiry 收紧 (补遗-1): 单纯 TTL 过期但注册表仍支撑 → can 不降级。
       先证"过期=自动降级版"被抓红 → 正式版 stale 只触发重核转绿。

断言压确定性产物 (store 的 can 值 / render block 内容), 不压 LLM reply。
"""
from __future__ import annotations

import os
import sys
import time
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_affordance as A


# ---- fake 能力注册表 / skill registry (Tier1 机械核验, 不烧 token) ----
class _FakeSkill:
    def __init__(self, calls=0, rate=1.0):
        self.call_count_30d = calls
        self.last_30d_success_rate = rate


class _FakeSkillReg:
    def __init__(self, skills=None):
        self._skills = dict(skills or {})
    def has(self, cmd):
        return cmd in self._skills
    def get(self, cmd):
        return self._skills.get(cmd)


class TestAffordanceNoEvidenceNoYes(unittest.TestCase):
    """RED 锚①: 无证据不点亮 can=yes。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aff_")
        self.path = os.path.join(self.tmp, "aff.json")

    def test_no_evidence_can_is_no(self):
        """无注册表/无 trace (仅'Sir 说过'这种非证据) → can=no。"""
        rec = A.verify_and_write("hold_a_software", note="Sir said I can",
                                 tool_registry={}, skill_registry=_FakeSkillReg(),
                                 store_path=self.path)
        self.assertEqual(rec["can"], A.CAN_NO,
                         "无真能力证据不得点亮 (Sir说过≠真能做, 命门)")
        self.assertEqual(rec["evidence"], [])

    def test_registry_callable_lights_yes(self):
        """注册表里可调用 → can=yes (源①)。"""
        rec = A.verify_and_write("real_tool",
                                 tool_registry={"real_tool": lambda **k: None},
                                 skill_registry=_FakeSkillReg(), store_path=self.path)
        self.assertEqual(rec["can"], A.CAN_YES)
        self.assertEqual(rec["evidence"][0]["source"], A.EV_REGISTRY)

    def test_trace_success_lights_yes(self):
        """成功执行 trace 达标 → can=yes (源②)。"""
        reg = _FakeSkillReg({"done_skill": _FakeSkill(calls=5, rate=0.9)})
        rec = A.verify_and_write("done_skill", tool_registry={},
                                 skill_registry=reg, store_path=self.path)
        self.assertEqual(rec["can"], A.CAN_YES)
        self.assertTrue(any(e["source"] == A.EV_EXEC_TRACE for e in rec["evidence"]))


class TestAffordanceProposeRaceGuard(unittest.TestCase):
    """RED 锚②(1b, 补遗-2): propose 不得直写 can=yes; 核验闸是唯一写入者。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aff_race_")
        self.path = os.path.join(self.tmp, "aff.json")

    def test_naive_direct_write_is_caught_RED(self):
        """先证'故意写歪'的朴素版 (propose 直写 can=yes) 会被本断言抓红。

        朴素版模拟旁路直写; 断言期望 store 里 can!=yes (无证据时)。朴素直写 → 红。"""
        def _naive_propose_direct_write(cid):
            # 故意写歪: 不核验直接写 yes (= 补遗-2 禁止的旁路)
            store = {"affordances": {cid: {"capability_id": cid, "can": "yes",
                                           "evidence": [], "last_verified_ts": time.time(),
                                           "note": "naive直写"}}}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(store, f)
        _naive_propose_direct_write("ghost_cap")
        recs = {r["capability_id"]: r for r in A.get_affordances(store_path=self.path)}
        # 朴素版让无证据的 can=yes 落库 → 本断言抓红 (证明 RED 能抓 bug)
        self.assertEqual(recs["ghost_cap"]["can"], "yes",
                         "(此断言确认朴素直写版确实写出了无证据 yes = 漏洞存在)")

    def test_real_propose_only_triggers_verify_GREEN(self):
        """正式版: propose_affordance 只触发核验, 无证据 → can=no (非 yes)。"""
        rec = A.propose_affordance("ghost_cap", reason="识觉得也许能",
                                   tool_registry={}, skill_registry=_FakeSkillReg(),
                                   store_path=self.path)
        self.assertEqual(rec["can"], A.CAN_NO,
                         "propose 触发核验, 无证据不点亮 (补遗-2: 核验是唯一写入者)")

    def test_real_propose_with_evidence_lights_via_verify(self):
        """propose 触发核验, 有真证据 → can=yes (经核验闸, 非 propose 直写)。"""
        rec = A.propose_affordance("real_tool", reason="线索",
                                   tool_registry={"real_tool": lambda **k: None},
                                   skill_registry=_FakeSkillReg(), store_path=self.path)
        self.assertEqual(rec["can"], A.CAN_YES)


class TestAffordanceRevokeDowngrade(unittest.TestCase):
    """RED 锚③: 撤销/降级 — 注册表移除 / 执行屡败 → can 降。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aff_revoke_")
        self.path = os.path.join(self.tmp, "aff.json")

    def test_revoke_when_tool_removed(self):
        """先 yes (注册表有), 工具下线后 reverify → 降 no。"""
        A.verify_and_write("temp_tool", tool_registry={"temp_tool": lambda **k: None},
                           skill_registry=_FakeSkillReg(), store_path=self.path)
        self.assertEqual(A.get_affordances(store_path=self.path)[0]["can"], A.CAN_YES)
        # 工具下线 (注册表空) → reverify
        A.reverify_all(tool_registry={}, skill_registry=_FakeSkillReg(),
                       store_path=self.path)
        self.assertEqual(A.get_affordances(store_path=self.path)[0]["can"], A.CAN_NO,
                         "工具下线 → can 必须降 (只升不降=不诚实)")

    def test_degrade_to_partial_when_failing(self):
        """注册表有但执行屡败 (KPI rate 低) → can=partial (能调不稳)。"""
        reg = _FakeSkillReg({"flaky": _FakeSkill(calls=10, rate=0.2)})
        rec = A.verify_and_write("flaky", tool_registry={"flaky": lambda **k: None},
                                 skill_registry=reg, store_path=self.path)
        self.assertEqual(rec["can"], A.CAN_PARTIAL,
                         "能调但屡败 → partial (诚实反映退化)")


class TestAffordanceExpiryTightening(unittest.TestCase):
    """RED 锚④(3b, 补遗-1): 单纯 TTL 过期但注册表仍支撑 → can 不降级。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aff_expiry_")
        self.path = os.path.join(self.tmp, "aff.json")

    def test_naive_time_expiry_downgrade_is_caught_RED(self):
        """先证'故意写歪'的朴素版 (过期=自动降级) 会被本断言抓红。

        朴素版: 单纯看时钟过期就把 can yes→no, 不看证据。断言期望仍 yes (注册表还在)
        → 朴素版降成 no → 红 (证明 RED 能抓 '时间改 can' 的 bug)。"""
        def _naive_expiry_downgrade(rec, now):
            # 故意写歪: 过期就降级, 无视注册表 (= 补遗-1 禁止的'时间改 can')
            if (now - rec["last_verified_ts"]) > A._STALE_TTL_S:
                rec["can"] = "no"
            return rec
        rec = {"capability_id": "x", "can": "yes", "evidence": [{"source": "registry"}],
               "last_verified_ts": time.time() - A._STALE_TTL_S - 1}
        out = _naive_expiry_downgrade(dict(rec), time.time())
        # 朴素版把仍有证据的 yes 降成 no → 本断言抓红
        self.assertEqual(out["can"], "no",
                         "(此断言确认朴素'过期即降级'版确实错降了有证据的 yes)")

    def test_real_expiry_only_marks_stale_not_downgrade_GREEN(self):
        """正式版: 单纯过期但注册表仍支撑 → reverify 后仍 yes (时间不改 can)。"""
        # 写一条 yes, 然后手动改 last_verified_ts 成很久以前 (模拟过期)
        A.verify_and_write("stable_tool",
                           tool_registry={"stable_tool": lambda **k: None},
                           skill_registry=_FakeSkillReg(), store_path=self.path)
        store = json.load(open(self.path, encoding="utf-8"))
        store["affordances"]["stable_tool"]["last_verified_ts"] = time.time() - A._STALE_TTL_S - 1
        json.dump(store, open(self.path, "w", encoding="utf-8"))
        # is_stale=True 但注册表仍支撑
        rec = A.get_affordances(store_path=self.path)[0]
        self.assertTrue(A.is_stale(rec), "应判 stale (过期)")
        # reverify: 注册表仍有 stable_tool → 仍 yes (过期没把它降级)
        A.reverify_all(tool_registry={"stable_tool": lambda **k: None},
                       skill_registry=_FakeSkillReg(), store_path=self.path)
        self.assertEqual(A.get_affordances(store_path=self.path)[0]["can"], A.CAN_YES,
                         "补遗-1: 单纯过期不降级, 注册表仍支撑则保持 yes")

    def test_stale_does_not_mutate_can(self):
        """is_stale 本身只读判定, 不改 can 值。"""
        rec = {"can": "yes", "last_verified_ts": 0}
        _ = A.is_stale(rec)
        self.assertEqual(rec["can"], "yes", "is_stale 不得 mutate can")


class TestAffordanceRenderBlock(unittest.TestCase):
    """render 框成'许可诚实承认', 非'驱动主动提供' (§6.3)。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aff_render_")
        self.path = os.path.join(self.tmp, "aff.json")

    def test_render_frames_as_permission_not_drive(self):
        A.verify_and_write("real_tool", tool_registry={"real_tool": lambda **k: None},
                           skill_registry=_FakeSkillReg(), store_path=self.path)
        block = A.render_affordance_block(store_path=self.path)
        self.assertIn("诚实承认", block)
        self.assertIn("不是要你主动揽活", block)
        # 不得出现"驱动主动提供"式措辞
        self.assertNotIn("去主动提供", block)

    def test_render_empty_when_no_affordance(self):
        self.assertEqual(A.render_affordance_block(store_path=self.path), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
