# -*- coding: utf-8 -*-
"""[口识体-G0 / 2026-05-31] 海马体永不动 guard.

Sir 红线: hippocampus(SQLite 永久记忆) 是五十年记忆基石, **永不动**。体/识/口 只**引用**
(读 / embed), 绝不改写。这是让"自己审自己"的自指环不漂移的不动锚。
详 docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md §6。

本 guard: 静态扫体的 5 个模块源码, 断言不含 hippocampus 写操作 (INSERT/DELETE/store_memory
/add_memory/archive_memory)。体只 _embed_with_rotation (只读 embed)。任何未来改动若让体写
hippo → 本 test 红 → 挡住。
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 体的 5 个模块 (说/识也不该直接写 hippo, 但体是引用层, 先锁体)
BODY_MODULES = [
    "jarvis_relational_manifold.py",
    "jarvis_relational_weaver.py",
    "jarvis_relational_lens.py",
    "jarvis_body_focus.py",
    "jarvis_stance.py",
]

# hippocampus 写操作模式 (出现 = 违永不动红线)
FORBIDDEN = [
    r"INSERT\s+INTO",
    r"DELETE\s+FROM",
    r"\bstore_memory\b",
    r"\badd_memory\b",
    r"\barchive_memory\b",
    r"\b_store_memory\b",
    r"hippocampus\.(save|store|add|insert|update|delete|commit)\b",
]


class TestHippoImmutable(unittest.TestCase):
    def test_body_modules_never_mutate_hippocampus(self):
        violations = []
        for mod in BODY_MODULES:
            path = os.path.join(ROOT, mod)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            for pat in FORBIDDEN:
                for m in re.finditer(pat, src, re.IGNORECASE):
                    line = src[:m.start()].count("\n") + 1
                    violations.append(f"{mod}:{line} 命中禁写模式 {pat!r}: {m.group(0)!r}")
        self.assertEqual(
            violations, [],
            "海马体永不动红线: 体模块不得写 hippocampus, 只能引用/embed。违规:\n  "
            + "\n  ".join(violations))

    def test_weaver_only_reads_hippo_for_embed(self):
        # 体唯一碰 Hippocampus 的地方 (weaver default_embed_fn) 只能调 _embed_with_rotation
        path = os.path.join(ROOT, "jarvis_relational_weaver.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        if "Hippocampus(" in src:
            # 用到 Hippocampus → 必须只读 (_embed_with_rotation)
            self.assertIn("_embed_with_rotation", src,
                          "weaver 用 Hippocampus 必须只为只读 embed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
