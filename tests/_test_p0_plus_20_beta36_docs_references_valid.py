# -*- coding: utf-8 -*-
"""[P0+20-β.3.6 / 2026-05-18] Docs References Drift Detect — 章程漂移自动 detect

Sir 元治理路线 β.3.5 → β.3.6: 章程升级水位 3+. 防止重构后 doc 里 file:line 引用过时
误导后续 agent. 任何核心 .md 里出现 `<file>.py:<line>` 引用 → 必须 (1) 文件真实存在
(2) 引用行号 ≤ 文件实际行数 (3) 如同行有 backquoted NAME → ±tolerance 行内含该 NAME.

CORE_DOCS 范围 = AGENTS.md §2 必读表 + 按需 Grep 区 (跨 IDE 可携带的章程核心).
非 CORE_DOCS (TODO_ARCHIVE / 老 design doc) 不扫, 容许漂移 (历史快照).

跑法:
    python tests/_test_p0_plus_20_beta36_docs_references_valid.py
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDocsReferencesValid(unittest.TestCase):
    """章程核心 .md 里所有 `<file>.py:<line>` 引用必须真实可定位.

    DOC 分两类:
      - CORE_CHARTER_DOCS: 跨轨道章程, 引用必须精确 (testcase 严格 detect)
      - SPEC_DESIGN_DOCS: 当前轨道 design doc, 允许提到"未来待建"文件名 (跳过 backquoted 检查;
                          但 file:line 引用仍严格检查, 因为那是具体位置不是 spec)
    """

    CORE_CHARTER_DOCS = [
        'AGENTS.md',
        'docs/JARVIS_PYTHON_STYLE.md',
        'docs/AGENT_HANDOFF_PROTOCOL.md',
        'docs/AGENT_KICKOFF_TEMPLATE.md',
        'docs/JARVIS_WORKFLOW_PROTOCOL.md',
    ]

    # design doc 允许提"未来文件" (Session 2 待建 jarvis_claim_classifier.py 等), 跳过 backquoted 文件检查
    SPEC_DESIGN_DOCS = [
        'docs/JARVIS_INTEGRITY_STACK.md',
    ]

    @property
    def CORE_DOCS(self):
        """合并: CHARTER + DESIGN. file:line 引用对两类都严格."""
        return self.CORE_CHARTER_DOCS + self.SPEC_DESIGN_DOCS

    # 匹配 `<file>.py:<line>` 或 <file>.py:<line> (无 backtick), file 名含 jarvis_ 前缀或 scripts/ 路径
    REF_PATTERN = re.compile(
        r'`?([a-z][a-z_0-9/]*\.py):(\d+)(?:-\d+)?`?')

    # backquoted file 引用 (without :line)
    FILE_PATTERN = re.compile(r'`([a-z][a-z_0-9/]*\.py)`')

    # 容差 ±50 行 (重构后小漂可接受, 大漂提示更新)
    LINE_TOLERANCE = 50

    def _try_extract_referenced_name(self, line, match_start):
        """看 match 前 60 字符内是否有 `NAME` (大写开头的标识符)."""
        prefix = line[max(0, match_start - 60):match_start]
        # 倒序找最后一个 backquoted NAME (most relevant)
        all_names = re.findall(r'`([A-Z][A-Za-z_0-9]*)`', prefix)
        return all_names[-1] if all_names else None

    def _resolve_file(self, ref_path):
        """ref_path 可能是 'jarvis_X.py' (项目根) 或 'scripts/X.py' 等."""
        candidates = [
            os.path.join(ROOT, ref_path),
            os.path.join(ROOT, 'scripts', ref_path),
            os.path.join(ROOT, 'tests', ref_path),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    def _file_line_count(self, fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)

    def _file_lines(self, fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            return f.readlines()

    def test_all_file_line_refs_resolve(self):
        """核心 doc 里所有 <file>.py:<line> 引用 (a) 文件存在 (b) 行号合法 (c) 若同行有 `NAME` → ±tolerance 行内含."""
        errors = []
        for doc in self.CORE_DOCS:
            doc_path = os.path.join(ROOT, doc)
            if not os.path.exists(doc_path):
                continue
            with open(doc_path, 'r', encoding='utf-8') as f:
                doc_lines = f.readlines()

            for lineno, line in enumerate(doc_lines, 1):
                for m in self.REF_PATTERN.finditer(line):
                    ref_file = m.group(1)
                    ref_line = int(m.group(2))

                    fpath = self._resolve_file(ref_file)
                    if fpath is None:
                        errors.append(
                            f"{doc}:{lineno}: 引用文件 '{ref_file}' 不存在 "
                            f"(根/scripts/tests 都没找到). 可能漏 jarvis_ 前缀或文件被重命名.")
                        continue

                    total = self._file_line_count(fpath)
                    if ref_line > total + 5:
                        errors.append(
                            f"{doc}:{lineno}: 引用 '{ref_file}:{ref_line}' 超出文件实际行数 "
                            f"{total} 已漂.")
                        continue

                    name = self._try_extract_referenced_name(line, m.start())
                    if name and ref_line <= total:
                        py_lines = self._file_lines(fpath)
                        start = max(0, ref_line - 1 - self.LINE_TOLERANCE)
                        end = min(len(py_lines), ref_line + self.LINE_TOLERANCE)
                        ctx = ''.join(py_lines[start:end])
                        if name not in ctx:
                            errors.append(
                                f"{doc}:{lineno}: 引用 '{ref_file}:{ref_line}' "
                                f"±{self.LINE_TOLERANCE} 行内不含 '{name}', 可能 NAME 已移动或重命名.")

        self.assertEqual(
            errors, [],
            msg="章程文档引用漂移 (β.3.6 detect):\n" + "\n".join(f"  - {e}" for e in errors))

    def test_all_backquoted_file_refs_exist(self):
        """CORE_CHARTER_DOCS 里所有 `<file>.py` (无 :line) 引用文件必须真实存在.

        SPEC_DESIGN_DOCS 跳过 (允许提'未来待建'文件名, e.g. INTEGRITY_STACK §4 Session 2
        提到 jarvis_claim_classifier.py — 那是 spec, 不是漂移).
        """
        # 白名单: 范例 / 模板里允许的 placeholder 文件名 (`jarvis_<file>.py` 类)
        WHITELIST_PLACEHOLDERS = {
            'jarvis_<file>.py',
            'jarvis_x.py',
            '<x>.py',
            '_test_p0_plus_20_beta3x_<x>_persist.py',
        }

        errors = []
        # 仅扫 CORE_CHARTER_DOCS, design doc 跳过
        for doc in self.CORE_CHARTER_DOCS:
            doc_path = os.path.join(ROOT, doc)
            if not os.path.exists(doc_path):
                continue
            with open(doc_path, 'r', encoding='utf-8') as f:
                doc_lines = f.readlines()

            for lineno, line in enumerate(doc_lines, 1):
                for m in self.FILE_PATTERN.finditer(line):
                    ref_file = m.group(1)
                    if ref_file in WHITELIST_PLACEHOLDERS:
                        continue
                    if '<' in ref_file or '>' in ref_file:
                        continue
                    fpath = self._resolve_file(ref_file)
                    if fpath is None:
                        errors.append(
                            f"{doc}:{lineno}: 引用文件 `{ref_file}` 不存在. "
                            f"漏 jarvis_/scripts/ 前缀? 重命名? 删了?")

        self.assertEqual(
            errors, [],
            msg="章程文档 backquoted 文件引用漂移:\n" + "\n".join(f"  - {e}" for e in errors))


if __name__ == '__main__':
    unittest.main(verbosity=2)
