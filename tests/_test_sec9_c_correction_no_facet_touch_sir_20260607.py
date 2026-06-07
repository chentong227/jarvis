# -*- coding: utf-8 -*-
"""[§9-C 终态防回归 / 2026-06-07] 纠正路径不触 facet store.

C 终态(设计 JARVIS_SEC9_C_CORRECTION_BRIDGE_DESIGN.md 拍板小节):
  纯 profile 纠正不碰 facet(零误撤); on_sir_correction 无 turn-path 调用者。
本测防将来误把纠正路径接上 facet:
  1. on_sir_correction 当前无生产调用者(grep 静态守护)。
  2. 一次 profile 纠正(tool_memory_correction_apply)后, facets store 逐字节不变。
"""
from __future__ import annotations

import os
import re
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_identity_facets as F


class TestSec9CCorrectionNoFacetTouch(unittest.TestCase):

    def test_on_sir_correction_has_no_production_caller(self):
        """C 终态: on_sir_correction 不被任何**生产码**调用(纠正路径不接 facet)。

        扫所有 jarvis_*.py(生产码,排除 tests/),不得出现 on_sir_correction( 调用。
        (定义本身在 jarvis_identity_facets.py:def on_sir_correction 不算调用。)
        """
        callers = []
        for fn in os.listdir(ROOT):
            if not fn.startswith("jarvis_") or not fn.endswith(".py"):
                continue
            src = open(os.path.join(ROOT, fn), encoding="utf-8").read()
            for m in re.finditer(r"on_sir_correction\s*\(", src):
                # 排除定义行 (def on_sir_correction()
                start = src.rfind("\n", 0, m.start()) + 1
                line = src[start:m.end()]
                if line.lstrip().startswith("def "):
                    continue
                callers.append(f"{fn}: {line.strip()}")
        self.assertEqual(callers, [],
                         f"C 终态: on_sir_correction 不应有生产调用者, 实测 {callers}")

    def test_correction_does_not_mutate_facets_store(self):
        """一次 profile 纠正后, facets store 逐字节不变(纠正不碰 facet)。"""
        # 种一个 facets store
        spath = tempfile.mktemp(suffix="_facets_c.json")
        F._STORE_PATH = spath
        store = {"_meta": {"schema": "identity_facets"}, "facets": {"facet_x": {
            "facet_id": "facet_x", "identity_key": "node:x", "content": "c",
            "provenance": [{"source": F.SRC_MANIFOLD_SAID, "ref": "r",
                            "recurrence_count": 3}],
            "recurrence_count": 3, "crystallized_ts": 1.0, "status": F.STATUS_ACTIVE}}}
        with open(spath, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        before = open(spath, "rb").read()

        # 跑一次 profile 纠正 (tool_memory_correction_apply) — 不应碰 facets store
        try:
            from jarvis_tool_registry import tool_memory_correction_apply
            tool_memory_correction_apply(
                old_value="9 cups", new_value="8 cups",
                field_hint="hydration_count", nerve=None)  # nerve=None → profile 路径 fail-soft
        except Exception:
            pass  # 纠正本身成败无关; 关键是它不碰 facets store

        after = open(spath, "rb").read()
        self.assertEqual(before, after,
                         "C 终态: 一次纠正后 facets store 必须逐字节不变")
        try:
            os.unlink(spath)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
