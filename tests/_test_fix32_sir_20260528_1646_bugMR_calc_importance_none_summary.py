# -*- coding: utf-8 -*-
"""[BUG MR / Sir 2026-05-28 16:46 真痛 MemoryRestore None summary] 单行 None-guard

Sir 真痛 (terminal log):
  > "[MemoryRestore] 恢复异常: object of type 'NoneType' has no len()"

Root cause (jarvis_central_nerve.py:_calc_importance):
  - SQL row `SELECT timestamp, user_intent, execution_summary, ...` 取出的
    execution_summary 字段允许 NULL → Python `None`.
  - line 702-703 已用 `(intent or "").lower()` / `(summary or "").lower()` 防 None,
    但 line 714 `if len(summary) > 100:` 漏 None-guard → 1 条 NULL 行就让
    整个 `_restore_short_term_memory` 异常退出, STM 全部丢.

Fix (1 行):
  `if len(summary) > 100:` → `if len(summary_lower) > 100:`
  (`summary_lower` 已经是 None-safe `(summary or "").lower()`)

Cover:
  A. summary=None 不炸 (Sir 实测 case)
  B. intent=None 不炸
  C. summary 短 (≤100) 不加分
  D. summary 长 (>100) 加 0.05 分 (老 logic 保留)
  E. marker 在源码
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bound_calc_importance(intent, summary, env):
    """Call CentralNerve._calc_importance 不实例化整个 nerve (init 太重).

    Trick: 借 unbound 方法 + dummy self. `_calc_importance` 只读参数 + 算分,
    不访问 self 字段, 所以 dummy self 即可.
    """
    from jarvis_central_nerve import CentralNerve

    class _Dummy:
        pass
    return CentralNerve._calc_importance(_Dummy(), intent, summary, env)


class TestA_NoneSummaryNotCrash(unittest.TestCase):
    """A: summary=None 不抛 TypeError (Sir 16:46 实测 case)."""

    def test_summary_none_returns_float(self):
        """SQL NULL execution_summary → summary=None, 应返 float 不炸."""
        try:
            score = _bound_calc_importance("test intent", None, "CHAT")
        except TypeError as e:
            self.fail(f"BUG MR regress: summary=None still raises TypeError: {e}")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestB_NoneIntentNotCrash(unittest.TestCase):
    """B: intent=None 不抛 (老 (intent or '') 已防, 守 regression)."""

    def test_intent_none_returns_float(self):
        try:
            score = _bound_calc_importance(None, "some summary text", "CHAT")
        except TypeError as e:
            self.fail(f"intent=None raises TypeError: {e}")
        self.assertIsInstance(score, float)


class TestC_BothNoneNotCrash(unittest.TestCase):
    """C: intent + summary 全 None 不炸 (极端 case)."""

    def test_both_none_returns_base_score(self):
        try:
            score = _bound_calc_importance(None, None, "DEV")
        except TypeError as e:
            self.fail(f"both None raises TypeError: {e}")
        # 全 None 应返 base 0.5 (no env bonus / no len bonus / no kw bonus)
        self.assertAlmostEqual(score, 0.5, places=2)


class TestD_LengthLogicPreserved(unittest.TestCase):
    """D: summary 长度判 logic 老 path 不破."""

    def test_short_summary_no_length_bonus(self):
        score = _bound_calc_importance("hi", "short text", "DEV")
        # base 0.5, summary ≤100 不加 0.05
        self.assertAlmostEqual(score, 0.5, places=2)

    def test_long_summary_adds_length_bonus(self):
        long_summary = "x" * 150  # > 100 chars
        score = _bound_calc_importance("hi", long_summary, "DEV")
        # base 0.5 + 0.05 (len > 100), env=DEV 不加 chat bonus
        self.assertAlmostEqual(score, 0.55, places=2)

    def test_chat_env_adds_chat_bonus(self):
        score = _bound_calc_importance("hi", "short", "CHAT")
        # base 0.5 + 0.1 (CHAT)
        self.assertAlmostEqual(score, 0.6, places=2)


class TestE_MarkerInSource(unittest.TestCase):
    """E: source 含 fix marker, 防回滚 silently."""

    def test_marker_present(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo_root, "jarvis_central_nerve.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        # Sir 16:46 fix marker
        self.assertIn("Sir 2026-05-28 16:46", src,
                      "BUG MR fix marker 丢失, fix 可能被 revert")
        # Fix 实际代码: summary_lower (None-safe), 不再裸 summary
        self.assertIn("if len(summary_lower) > 100:", src,
                      "BUG MR fix 代码丢失, len(summary) 还在裸调")


if __name__ == "__main__":
    unittest.main()
