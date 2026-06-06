# -*- coding: utf-8 -*-
"""[body-diff-P1 / Sir 2026-06-06] 耦合护栏验收: inject=1 但 grounded_only=0 → 拒绝注入.

真理源: docs/JARVIS_LENS_REOPEN_DESIGN_P1.md §1 (耦合护栏两层) + JARVIS_VALIDATION_STANDARD
§6 (05-31 假焊事故: 只翻 inject 忘翻 grounded → 复活 95.6% 假焊).

护栏存在意义 = 堵"inject=1 但 grounded_only=0"这条已证有害路径。测试必须先看见它拦下真东西:

  T1 无护栏会漏假焊 (RED 锚, 证明威胁真实): 误配 inject=1+grounded=0 下, **绕过护栏直接走
     naive project** (复刻护栏未拦截时的行为) → 投影出 hand_pain↔interview 假焊。证明这条
     路径若不拦就有害 (= 护栏不是装饰)。
  T2 护栏拦截转绿: 同误配下走真 build_lens_block (含护栏) → 返 "" (拒绝注入, 当 off)。
  T3 启动期 loud 早警 (层1): validate_lens_coupling 在误配下返 violation str + loud。
  T4 限流 (层2): 连续多次误配调用, REFUSE bg_log 只报一次 (状态不变不刷屏)。
  T5 正配不拦: inject=1+grounded=1 → build_lens_block 正常投影 (非空, 不被护栏误伤)。
  T6 lens 关不触发护栏: inject=0 → "" (老行为, 护栏不介入)。

⚠️ 隔离: mock get_manifold_config (rm + L 两处, lens reader bind 副本), temp 体副本, 不写回.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as rm
import jarvis_relational_lens as L
from jarvis_relational_manifold import RelationalManifold

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
VOCAB = os.path.join(ROOT, "memory_pool", "relational_manifold_vocab.json")

_INTERVIEW = "interview"
_HANDPAIN = "hand pain"


def _cfg(inject, grounded):
    cfg = json.loads(json.dumps(rm._SEED_MANIFOLD_CONFIG))
    try:
        if os.path.exists(VOCAB):
            with open(VOCAB, encoding="utf-8") as f:
                ov = json.load(f)
            cfg = rm._deep_merge(cfg, ov.get("config", ov))
    except Exception:
        pass
    cfg["lens_inject_enabled"] = 1 if inject else 0
    cfg["lens_spread_grounded_only"] = 1 if grounded else 0
    return cfg


@unittest.skipUnless(os.path.exists(SRC), "无生产体数据 — 跳过耦合护栏验收")
class TestLensCouplingGuard(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1_guard_")
        self.dst = os.path.join(self.tmp, "m.json")
        shutil.copy(SRC, self.dst)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        L.reset_lens_for_test(None)
        L._REFUSE_LOG_STATE["last"] = None

    def _lens(self):
        from jarvis_relational_lens import RelationalLens, reset_lens_for_test
        lens = RelationalLens(manifold=RelationalManifold(self.dst))
        reset_lens_for_test(lens)
        return lens

    def test_t1_no_guard_leaks_falseweld_RED_anchor(self):
        """RED 锚: 误配下若绕过护栏直接 naive project → 投假焊 (证明威胁真实, 护栏非装饰)。"""
        cfg = _cfg(inject=True, grounded=False)
        with mock.patch.object(rm, "get_manifold_config", return_value=cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=cfg):
            lens = self._lens()
            seeds = lens.seeds_from_text("my hand pain is acting up again")
            # 绕过 build_lens_block 护栏, 直接 naive project (= 护栏不拦时的行为)
            block = lens.project(seeds)
        self.assertIn(
            _INTERVIEW, block.lower(),
            "RED 锚失效: 无护栏的 naive project 竟没投出 interview 假焊 — "
            "若此处不红, T2 的绿就证明不了护栏真拦下了东西。",
        )

    def test_t2_guard_refuses_inject_GREEN(self):
        """护栏拦截: 误配下走真 build_lens_block → 返 "" (拒绝注入)。"""
        cfg = _cfg(inject=True, grounded=False)
        with mock.patch.object(rm, "get_manifold_config", return_value=cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=cfg):
            self._lens()
            from jarvis_relational_lens import build_lens_block
            block = build_lens_block(user_input="my hand pain is acting up again")
        self.assertEqual(
            block, "",
            f"耦合护栏失效: 误配 (inject=1, grounded=0) 下 build_lens_block 竟未拒绝注入, "
            f"返回非空 (裸 naive lens 复活风险)。block={block[:200]!r}",
        )

    def test_t3_startup_loud_early_warning(self):
        """层1 启动期 loud: validate_lens_coupling 误配下返 violation str。"""
        cfg = _cfg(inject=True, grounded=False)
        with mock.patch.object(L, "get_manifold_config", return_value=cfg):
            from jarvis_relational_lens import validate_lens_coupling
            violation = validate_lens_coupling()
        self.assertIsNotNone(violation, "启动期校验未抓到误配 (inject=1, grounded=0)")
        self.assertIn("COUPLING-GUARD", violation)

    def test_t3b_startup_ok_when_properly_configured(self):
        """正配 (inject=1, grounded=1) → 启动校验返 None (不误报)。"""
        cfg = _cfg(inject=True, grounded=True)
        with mock.patch.object(L, "get_manifold_config", return_value=cfg):
            from jarvis_relational_lens import validate_lens_coupling
            self.assertIsNone(validate_lens_coupling())

    def test_t4_hotpath_refuse_log_throttled(self):
        """层2 限流: 连续多次误配调用, REFUSE bg_log 只报一次 (状态不变)。"""
        cfg = _cfg(inject=True, grounded=False)
        L._REFUSE_LOG_STATE["last"] = None
        calls = []
        with mock.patch.object(rm, "get_manifold_config", return_value=cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=cfg), \
                mock.patch.object(L, "_log", side_effect=lambda m: calls.append(m)):
            self._lens()
            from jarvis_relational_lens import build_lens_block
            for _ in range(5):
                build_lens_block(user_input="my hand pain is acting up again")
        refuse_logs = [c for c in calls if "REFUSE" in c]
        self.assertEqual(
            len(refuse_logs), 1,
            f"限流失效: 5 次误配调用 REFUSE 日志报了 {len(refuse_logs)} 次 (应 1 次防刷屏)。",
        )

    def test_t5_proper_config_not_blocked(self):
        """正配 (inject=1, grounded=1) → build_lens_block 正常投影 (护栏不误伤)。"""
        cfg = _cfg(inject=True, grounded=True)
        with mock.patch.object(rm, "get_manifold_config", return_value=cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=cfg):
            self._lens()
            from jarvis_relational_lens import build_lens_block
            block = build_lens_block(user_input="how is my hydration today")
        self.assertTrue(
            block, "护栏误伤: 正配 (inject=1, grounded=1) 下 hydration 投影被拦成空。",
        )

    def test_t6_lens_off_no_guard(self):
        """lens 关 (inject=0) → "" (老行为, 护栏不介入)。"""
        cfg = _cfg(inject=False, grounded=False)
        with mock.patch.object(rm, "get_manifold_config", return_value=cfg), \
                mock.patch.object(L, "get_manifold_config", return_value=cfg):
            self._lens()
            from jarvis_relational_lens import build_lens_block
            self.assertEqual(build_lens_block(user_input="anything"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
