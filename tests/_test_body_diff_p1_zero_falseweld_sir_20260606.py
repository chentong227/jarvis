# -*- coding: utf-8 -*-
"""[body-diff-P1 / Sir 2026-06-06] 投影零假焊 验收断言 (接地偏权 spread 验收门).

真理源: docs/JARVIS_VALIDATION_STANDARD.md §4 (投影零假焊 = 投影类特性常驻验收维, 先红
后绿) + docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md §15.1 (人读 ground-truth: hand_pain↔
interview 是假焊 — 手痛=玩 AoE4 游戏, 非 coding) + §15.6 P1 门(b).

历史 (先红后绿, §6 断言缺失=漏检无声): 拍1 本断言在**未改 naive 代码** (spread 走全边)
上跑 → RED (抓到 95.6% 假焊 / hand_pain↔interview 双向互投); 拍2 实做 grounded_only
(spread 只沿 PROV_SHARED/SAID about 边); 拍3 本断言转绿 = 接地偏权切掉假焊。

本测调**真** build_lens_block() → RelationalLens.project() → manifold.spread() (不复刻),
在真生产体数据 temp 副本上跑。三道断言 (Sir 拍3 收紧):
  1. 沉默 seed (hand_pain): grounded 投影块**空, 或非空但零 interview 假焊** — 两者都过
     (无接地路径 → 诚实沉默 是设计正确行为, 不变量①)。
  2. 沉默 seed (interview): 同上, 反向 (零 hand_pain 假焊)。
  3. hydration 正控: grounded 投影集 **⊆ 接地可达集 (全 PROV_SHARED/SAID about 节点)
     且非空** — 这是绿阶段的**防假绿门** (替掉旧"全局块非空"): 它非空 ⟹ 机器活着 + flag
     真开 + spread 真跑 + 接地路径真投得出; ⊆ ⟹ 没混进非接地路径残留 (§15.1 别误判健康)。

⚠️ 隔离 (§5 + Sir 拍3 ①): 测试内显式 pin lens_inject_enabled=1 + lens_spread_grounded_only=1
(mock get_manifold_config, **不依赖真盘默认值** 免 disk 漂移); 复制真体到 temp, 绝不写回。
flag-on 自检两阶段都留 (机器没活/flag 没开 → 正控变空直接红, 不假绿)。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock as mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as rm
import jarvis_relational_lens as L
from jarvis_relational_manifold import (
    RelationalManifold, split_node_id, PROV_SHARED, PROV_SAID,
)

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
VOCAB = os.path.join(ROOT, "memory_pool", "relational_manifold_vocab.json")

# 人读 ground-truth 假焊对 (§15.1 Sir 亲读钉死)
_INTERVIEW_MARKERS = ("interview",)
_HANDPAIN_MARKERS = ("hand pain", "hand_pain")
# 接地放行白名单 (与生产 spread_grounded_provenance 一致)
_GROUNDED_PROVS = {PROV_SHARED, PROV_SAID}


def _base_cfg() -> dict:
    """读 seed + 真盘 vocab, 然后**显式 pin 双 flag** (不依赖盘默认值, 免 disk 漂移)。"""
    cfg = json.loads(json.dumps(rm._SEED_MANIFOLD_CONFIG))
    try:
        if os.path.exists(VOCAB):
            with open(VOCAB, encoding="utf-8") as f:
                ov = json.load(f)
            cfg = rm._deep_merge(cfg, ov.get("config", ov))
    except Exception:
        pass
    cfg["lens_inject_enabled"] = 1          # pin: 沙盒里真开 lens
    cfg["lens_spread_grounded_only"] = 1    # pin: 接地偏权 spread (拍3 转绿配置)
    return cfg


@unittest.skipUnless(os.path.exists(SRC), "无生产体数据 — 跳过真数据零假焊验收")
class TestProjectionZeroFalseWeld(unittest.TestCase):
    """接地偏权下真 build_lens_block 投影: 假焊切掉 + hydration 正控 ⊆ 接地可达。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1_zfw_")
        self.dst = os.path.join(self.tmp, "m.json")
        shutil.copy(SRC, self.dst)  # 复制真体到 temp, 绝不写回
        self.cfg = _base_cfg()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        try:
            L.reset_lens_for_test(None)
        except Exception:
            pass

    # ---- helpers: 真路径 (双 flag pin 在 mock cfg) ----
    def _new_lens(self):
        from jarvis_relational_lens import RelationalLens, reset_lens_for_test
        m = RelationalManifold(self.dst)
        lens = RelationalLens(manifold=m)
        reset_lens_for_test(lens)
        return m, lens

    def _block_via_real_path(self, user_input: str) -> str:
        """真 build_lens_block(user_input=...) → 真 project → 真 spread (grounded)。"""
        m, lens = self._new_lens()
        with mock.patch.object(rm, "get_manifold_config", return_value=self.cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=self.cfg):
            from jarvis_relational_lens import build_lens_block, lens_inject_enabled
            self.assertTrue(lens_inject_enabled(),
                            "flag-on 自检: lens 必须在沙盒里真开 (否则假绿)")
            return build_lens_block(user_input=user_input) or ""

    def _derive_seeds(self, lens, user_input):
        """复刻 build_lens_block 的 seed 派生 (topic + focus)。"""
        topic = lens.seeds_from_text(user_input) if user_input else []
        focus = lens.default_seeds()
        return topic + [s for s in focus if s not in topic]

    def _projected_nodes(self, m, lens, user_input):
        """复刻 project 的 relevance 节点选取 (grounded spread → resolve → 排 seed/无文本/
        stance), 返回真投影进 block 的节点集 (node 级, 不靠 text 解析)。"""
        from jarvis_relational_manifold import KIND_STANCE
        seeds = self._derive_seeds(lens, user_input)
        seed_set = set(seeds)
        text_map = lens._node_text_map()
        act = m.spread(seeds, hops=2, min_activation=0.08, grounded_only=True)
        best = {}
        for nid, score in act.items():
            rep = m.resolve(nid)
            if rep in seed_set or rep not in text_map:
                continue
            if split_node_id(rep)[0] == KIND_STANCE:
                continue
            if score > best.get(rep, -1.0):
                best[rep] = score
        return set(best.keys()), seed_set

    # ---- 断言 1/2: 沉默 seed 假焊切掉 (空 或 非空零假焊) ----
    def test_handpain_grounded_no_interview_falseweld(self):
        block = self._block_via_real_path("my hand pain is acting up again")
        hit = [mk for mk in _INTERVIEW_MARKERS if mk in block.lower()]
        self.assertFalse(
            hit,
            f"零假焊违反: hand_pain 话题的接地偏权投影块仍含 interview concern "
            f"(§15.1 假焊). 命中={hit}\n--- 投影块 ---\n{block}",
        )

    def test_interview_grounded_no_handpain_falseweld(self):
        block = self._block_via_real_path("how is my interview prep going")
        hit = [mk for mk in _HANDPAIN_MARKERS if mk in block.lower()]
        self.assertFalse(
            hit,
            f"零假焊违反: interview 话题的接地偏权投影块仍含 hand_pain concern "
            f"(§15.1 假焊). 命中={hit}\n--- 投影块 ---\n{block}",
        )

    # ---- 断言 3: hydration 正控 — grounded 投影非空 + 每节点(alias簇)有 about 接地边 ----
    def test_hydration_positive_control_subset_grounded_and_nonempty(self):
        """hydration 有接地路径 → grounded 投影 (a) 非空 [机器活/flag开/spread跑] +
        (b) 每个投影节点的 **alias 簇** 含 ≥1 条 about 接地边 [⊆ 接地, 没混进非接地路径].

        ⚠️ alias-fold: 投影节点是 resolve() 代表, 接地边可能落在簇内 alias 成员上 (代表
        自己 _adj 只剩 embed/cooccur)。故 provenance 复核须取**整簇** _adj 并集, 不只代表
        (否则误报)。这是非循环的真验证: naive 全边能投出纯 embed mesh 节点 (无任何接地边),
        grounded 偏权下这种节点不该出现 — 簇级 about 边检查能抓到泄漏。"""
        with mock.patch.object(rm, "get_manifold_config", return_value=self.cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=self.cfg):
            m, lens = self._new_lens()
            projected, seed_set = self._projected_nodes(m, lens, "how is my hydration today")
            # rep → alias 簇成员 (含 rep 自己): 任一节点 resolve 到该 rep
            cluster = {}
            for n in m._adj.keys():
                rep = m.resolve(n)
                cluster.setdefault(rep, set()).add(n)
            # 复核: 每个投影 rep 的整簇 _adj 并集是否含 about 接地边
            leaked = []
            for rep in projected:
                provs = set()
                for member in cluster.get(rep, {rep}):
                    for key in m._adj.get(member, ()):
                        e = m._edges.get(key)
                        if e:
                            provs |= {p.get("kind") for p in e.get("provenance", [])}
                if not (provs & _GROUNDED_PROVS):
                    leaked.append((rep, sorted(provs)))

        # (a) 非空: grounded 路径真投得出 → 机器活着 + flag 真开 + spread 真跑
        self.assertTrue(
            projected,
            "防假绿门: hydration 正控 grounded 投影为空 = 机器没活/flag 没开/接线断 "
            "(不是诚实沉默 — hydration 有接地路径)。",
        )
        # (b) 每投影节点(整簇)有 about 接地边 = ⊆ 接地, 没混进纯 embed/cooccur 路径
        self.assertFalse(
            leaked,
            f"hydration 正控 ⊆ 接地 违反: 投影出无 about 接地边的节点(簇) {leaked} "
            f"(§15.1 别误判健康 — 纯 embed/cooccur 节点漏进接地偏权投影)。",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
