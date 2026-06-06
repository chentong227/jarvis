# -*- coding: utf-8 -*-
"""[body-diff-P2 / Sir 2026-06-06] 势能层接地化 验收门 (势能零假焊, 先红后绿).

真理源: docs/JARVIS_ENERGY_GROUNDING_DESIGN_P2.md §8 (先红后绿纪律) + §1 (compute_energy
novelty/drift 全量数边 = 唯一未设防 body->brain 通道, 实测洗白 8:0) + docs/
JARVIS_BODY_ARCHITECTURE_MAP.md §6.1 (改哪行: edge_snapshot provs + compute_energy 白名单)。

历史 (先红后绿, §8 主力门): 拍1 本断言在**未加门的 naive compute_energy** 上跑 → RED
(flag=1 时假焊边仍贡献 novelty/drift, 因为门不存在); 拍2 实做 C1-C8 (edge_snapshot 带
provs + is_grounded 统一谓词 + compute_energy 白名单过滤); 拍3 转绿 = 假焊势能归零、接地
势能不损。

设计取舍 (§4, 显式不藏): energy_grounded_only=1 时 cooccur/embed 边对 novelty/drift 贡献
→ 0 (接受丢失弱共现先验, 真关系会以接地边 shared/said 重现)。tension 不数边、不受影响。

断言压**确定性势能值** (compute_energy 输出), 不压 LLM reply。flag 经 mock get_manifold_config
pin (不依赖真盘默认值, 免 disk 漂移)。红线 A: is_grounded = 机械 provenance 集合交, 无打分。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_weaver as W
import jarvis_relational_manifold as rm
from jarvis_relational_manifold import (
    RelationalManifold, PROV_SHARED, PROV_SAID, PROV_EMBED, PROV_COOCCUR,
)
from jarvis_relational_weaver import RelationalWeaver

T0 = 1_780_000_000.0
A_NODE = "concern:pomodoro"
B_NODE = "concern:sleep"      # pomodoro<->sleep = §4.3 实测双高频假焊对


def _cfg(*, energy_grounded_only: int) -> dict:
    """seed config + pin energy_grounded_only flag (top-level 白名单用 seed 默认 {shared,said})。"""
    cfg = json.loads(json.dumps(rm._SEED_MANIFOLD_CONFIG))
    cfg["energy"]["energy_grounded_only"] = energy_grounded_only
    return cfg


def _mk_weaver(d) -> RelationalWeaver:
    """最小 weaver (空 store, 直接喂 snapshot 给 compute_energy, 不跑 weave_geometric)。"""
    cp = os.path.join(d, "concerns.json")
    rp = os.path.join(d, "relational_state.json")
    sp = os.path.join(d, "stance.json")
    tp = os.path.join(d, "self_threads.json")
    for p, obj in ((cp, {}), (rp, {"inside_jokes": {}, "unspoken_protocols": {}}),
                   (sp, {"stances": {}}), (tp, {"threads": []})):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    man = RelationalManifold(os.path.join(d, "manifold.json"))
    return RelationalWeaver(
        manifold=man, threads_path=tp, concerns_path=cp, relational_path=rp,
        vectors_path=os.path.join(d, "vec.json"), stance_path=sp,
        energy_path=os.path.join(d, "energy.json"), event_bus=None)


def _snap(key, a, b, w, provs):
    """构造 edge_snapshot 风格的边 (C1 后带 provs 字段)。"""
    return {key: {"a": a, "b": b, "w": w, "provs": set(provs)}}


class TestEnergyGroundedNovelty(unittest.TestCase):
    """novelty: 新边只有假焊 provenance (embed/cooccur) → flag=1 时不贡献势能。"""

    def _novelty(self, provs, *, flag):
        """返 A_NODE 的 novelty 贡献; 节点被接地化过滤掉 (不进 energy dict) → 视作 0.0。"""
        with tempfile.TemporaryDirectory() as d:
            w = _mk_weaver(d)
            post = _snap("ek", A_NODE, B_NODE, 0.6, provs)
            with mock.patch.object(W, "get_manifold_config",
                                   return_value=_cfg(energy_grounded_only=flag)):
                energy = w.compute_energy({"ek"}, {}, post, now=T0)
            # 过滤掉的假焊边 → 节点不产势能条目 (= 零势能, 比 0.0 更强的证据)
            return energy.get(A_NODE, {}).get("novelty", 0.0)

    def test_falseweld_novelty_control_flag_off(self):
        """控制组: flag=0 时假焊边 (embed) 仍贡献 novelty (= 当前洗白行为)。"""
        self.assertAlmostEqual(self._novelty({PROV_EMBED}, flag=0), 0.6, places=6,
                               msg="flag=0 应保持老行为 (假焊边贡献 novelty)")

    def test_falseweld_novelty_zero_flag_on(self):
        """★ 主力门: flag=1 时纯假焊边 (embed) novelty 贡献 = 0 (势能不吃假焊)。

        拍1 RED: 未加门的 compute_energy 不认 flag → novelty=0.6 != 0 → 本断言红。
        拍3 GREEN: 加门后 embed 边被 is_grounded 过滤 → novelty=0。"""
        self.assertAlmostEqual(self._novelty({PROV_EMBED}, flag=1), 0.0, places=6,
                               msg="flag=1 纯 embed 假焊边不该贡献 novelty (势能零假焊)")

    def test_cooccur_novelty_zero_flag_on(self):
        """flag=1 时 cooccur 边 (偶发假焊, §4 取舍) novelty 贡献 = 0。"""
        self.assertAlmostEqual(self._novelty({PROV_COOCCUR}, flag=1), 0.0, places=6,
                               msg="flag=1 cooccur 边不该贡献 novelty (设计 §4 取舍)")

    def test_grounded_novelty_preserved_flag_on(self):
        """接地区不损: flag=1 时 shared (about 接地) 边 novelty 贡献不变。"""
        self.assertAlmostEqual(self._novelty({PROV_SHARED}, flag=1), 0.6, places=6,
                               msg="flag=1 接地边 (shared) novelty 不该被削 (接地区不损)")

    def test_mixed_provenance_grounded_passes_flag_on(self):
        """混合 provenance: 边含任一接地 prov (shared) → flag=1 仍贡献 (有接地证据即放行)。"""
        self.assertAlmostEqual(self._novelty({PROV_EMBED, PROV_SHARED}, flag=1), 0.6,
                               places=6, msg="含 shared 的混合边应放行 (任一接地即接地)")


class TestEnergyGroundedDrift(unittest.TestCase):
    """drift: 边权变动只有假焊 provenance → flag=1 时不贡献 drift。"""

    def _drift(self, provs, *, flag):
        """返 A_NODE 的 drift 贡献; 节点被接地化过滤掉 → 视作 0.0。"""
        with tempfile.TemporaryDirectory() as d:
            w = _mk_weaver(d)
            pre = _snap("ek", A_NODE, B_NODE, 0.2, provs)
            post = _snap("ek", A_NODE, B_NODE, 0.5, provs)  # drift = 0.3
            with mock.patch.object(W, "get_manifold_config",
                                   return_value=_cfg(energy_grounded_only=flag)):
                energy = w.compute_energy(set(), pre, post, now=T0)
            return energy.get(A_NODE, {}).get("drift", 0.0)

    def test_falseweld_drift_control_flag_off(self):
        self.assertAlmostEqual(self._drift({PROV_EMBED}, flag=0), 0.3, places=6,
                               msg="flag=0 应保持老行为 (假焊边贡献 drift)")

    def test_falseweld_drift_zero_flag_on(self):
        """★ 主力门: flag=1 时纯假焊边 drift 贡献 = 0。"""
        self.assertAlmostEqual(self._drift({PROV_EMBED}, flag=1), 0.0, places=6,
                               msg="flag=1 纯 embed 假焊边不该贡献 drift (势能零假焊)")

    def test_grounded_drift_preserved_flag_on(self):
        self.assertAlmostEqual(self._drift({PROV_SAID}, flag=1), 0.3, places=6,
                               msg="flag=1 接地边 (said) drift 不该被削 (接地区不损)")


class TestIsGroundedPredicate(unittest.TestCase):
    """统一谓词 is_grounded (红线 A: 机械集合交, 无打分)。"""

    def test_is_grounded_basic(self):
        gp = {PROV_SHARED, PROV_SAID}
        self.assertTrue(rm.is_grounded({PROV_SHARED}, gp))
        self.assertTrue(rm.is_grounded({PROV_SAID}, gp))
        self.assertTrue(rm.is_grounded({PROV_EMBED, PROV_SHARED}, gp))  # 任一接地即接地
        self.assertFalse(rm.is_grounded({PROV_EMBED}, gp))
        self.assertFalse(rm.is_grounded({PROV_COOCCUR}, gp))
        self.assertFalse(rm.is_grounded(set(), gp))


class TestEnergyCouplingGuard(unittest.TestCase):
    """耦合护栏 (对称 lens): flag=1 但白名单非法 (空/含非接地 prov) → fail-loud。"""

    def test_guard_ok_when_valid(self):
        cfg = _cfg(energy_grounded_only=1)
        with mock.patch.object(W, "get_manifold_config", return_value=cfg):
            self.assertIsNone(W.validate_energy_coupling())

    def test_guard_relapse_warns_when_flag_off(self):
        """★ [真机激活后 / Sir 2026-06-07] flag=0 = relapse 洗白态 → loud 告警 (非 None)。

        真机已激活接地化 (默认翻 1), effective=0 = 有人翻回洗白态 → 护栏必须 loud 喊
        (盲点① relapse 防线)。0 仍允许 (显式 override 调试), 但每次都告警。"""
        cfg = _cfg(energy_grounded_only=0)
        with mock.patch.object(W, "get_manifold_config", return_value=cfg):
            v = W.validate_energy_coupling()
        self.assertIsNotNone(v, "flag=0 relapse 应 loud 告警 (真机激活后)")
        self.assertIn("relapse", v)

    def test_guard_warns_empty_whitelist(self):
        """★ RED 锚: flag=1 但白名单空 → 势能无边可数 (退化) → 返回 violation。"""
        cfg = _cfg(energy_grounded_only=1)
        cfg["spread_grounded_provenance"] = []
        with mock.patch.object(W, "get_manifold_config", return_value=cfg):
            self.assertIsNotNone(W.validate_energy_coupling())

    def test_guard_warns_non_grounded_in_whitelist(self):
        """flag=1 但白名单含 embed (非接地 prov 混入) → 违背接地语义 → violation。"""
        cfg = _cfg(energy_grounded_only=1)
        cfg["spread_grounded_provenance"] = [PROV_EMBED]
        with mock.patch.object(W, "get_manifold_config", return_value=cfg):
            self.assertIsNotNone(W.validate_energy_coupling())


if __name__ == "__main__":
    unittest.main(verbosity=2)
