# -*- coding: utf-8 -*-
"""[P0+20-β.3.3 / 2026-05-18] Agent Discipline Red Lines — 章程可执行化

Sir 2026-05-18 立 "黑箱化 + 可迭代" 目标. 章程从"靠 agent 自觉"升级为"靠 testcase 红线挡".
任何 agent 接手都不可绕过的硬规, 通过 grep + testcase 强制:

  - 准则 6.5 vocab 硬编码红线 (新 _XXX_PATTERNS / _XXX_KEYWORDS = [...] 必须配 _SEED_/get_/json + CLI)
  - jarvis_*.py forbidden anti-patterns (from jarvis_nerve import * / raw sqlite to memory_pool)
  - 跨 IDE 可携带性自检 (docs/JARVIS_PYTHON_STYLE.md 存在)
  - 交接协议自检 (docs/AGENT_HANDOFF_PROTOCOL.md + KICKOFF_TEMPLATE.md 存在)

ratcheting / allow-list 策略:
  当前已知遗留违规放 ALLOW_LIST_VOCAB_HARDCODED, 测试 pass 条件 = 命中数 ≤ allow-list 长度.
  Session 0 推进时, 每迁完一个 vocab → 从 allow-list 删除一项 → testcase 自动收紧.
  任何新增硬编码 → 命中数 > allow-list → FAIL.

跑法:
    python -m pytest tests/_test_p0_plus_20_beta33_agent_discipline_red_lines.py -v
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _iter_project_py_files(prefixes=('jarvis_',), include_scripts=True):
    """遍历项目内 .py 文件 (排除 venv / __pycache__ / 测试自身)."""
    out = []
    for fname in os.listdir(ROOT):
        if fname.endswith('.py') and any(fname.startswith(p) for p in prefixes):
            out.append(os.path.join(ROOT, fname))
    if include_scripts:
        scripts_dir = os.path.join(ROOT, 'scripts')
        if os.path.isdir(scripts_dir):
            for fname in os.listdir(scripts_dir):
                if fname.endswith('.py'):
                    out.append(os.path.join(scripts_dir, fname))
    return out


def _grep_in_files(pattern: str, files, line_filter=None, flags=0):
    """grep regex in files, return [(rel_file, lineno, line), ...]"""
    rx = re.compile(pattern, flags)
    out = []
    for fp in files:
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                for lineno, line in enumerate(f, 1):
                    if rx.search(line):
                        if line_filter is None or line_filter(line):
                            rel = os.path.relpath(fp, ROOT).replace('\\', '/')
                            out.append((rel, lineno, line.rstrip()))
        except Exception:
            continue
    return out


class TestForbiddenImports(unittest.TestCase):
    """docs/JARVIS_PYTHON_STYLE.md §4 — 禁止 import / call 路径."""

    def test_no_star_import_from_jarvis_nerve(self):
        """`from jarvis_nerve import *` — 破坏 P0+19 split 后的 forwarding shim. 0 容忍."""
        files = _iter_project_py_files()
        hits = _grep_in_files(r'^\s*from\s+jarvis_nerve\s+import\s+\*', files)
        self.assertEqual(
            hits, [],
            msg=f"准则: 禁止 `from jarvis_nerve import *` (破 forwarding shim). 命中:\n" +
                "\n".join(f"  {f}:{ln}: {ln_str}" for f, ln, ln_str in hits))

    def test_no_raw_sqlite_connect_to_memory_pool(self):
        """raw `sqlite3.connect("memory_pool/...")` 直连 → 跳过 Hippocampus 并发控制. 0 容忍."""
        files = _iter_project_py_files()
        # 例外: jarvis_memory_core.py 是 Hippocampus 实现自身, 内部当然要 connect
        files = [fp for fp in files if not fp.endswith('jarvis_memory_core.py')]
        hits = _grep_in_files(
            r'sqlite3\.connect\([^)]*memory_pool', files,
            line_filter=lambda l: not l.lstrip().startswith('#'))
        self.assertEqual(
            hits, [],
            msg=f"准则: 走 Hippocampus / CommitmentWatcher API, 不要 raw sqlite3.connect memory_pool. 命中:\n" +
                "\n".join(f"  {f}:{ln}: {ln_str}" for f, ln, ln_str in hits))


class TestRule65VocabHardcoded(unittest.TestCase):
    """AGENTS.md 准则 6.5 + docs/JARVIS_PYTHON_STYLE.md §6 红线.

    任何 `_<X>_PATTERNS = [...]` / `_<X>_KEYWORDS = (...)` in py 都违规,
    应迁到 memory_pool/<x>_vocab.json + scripts/<x>_dump.py + py 留 _SEED_/get_ 范式.

    ratcheting/allow-list 兜底: 当前已知遗留 (β.3.0 开始迁移) 放白名单. Session 0 推进时逐个移除.

    例外 (准则 6.4 系统级常量豁免, 不入 allow-list):
      - _ANSI ANSI 着色 / _COLOR_PATTERNS terminal ANSI regex
      - _NON_RETRYABLE_KEYWORDS API 错误码黑名单 (HTTP 类常量, 不是语义 vocab)
    """

    # 当前已知违规 (β.3.3 立 testcase 时盘点). Session 0 推进时, 每完成一个迁移 → 从此 list 删除.
    # 格式: (file_rel_path, var_name) — 任意一项被迁走 (改名 _SEED_X_PATTERNS) 后立刻从 list 删.
    ALLOW_LIST_VOCAB_HARDCODED = [
        # P0+20-β.3.0 Session 0 剩余待迁:
        ('jarvis_utils.py', '_OPEN_THREAD_PATTERNS'),       # 承诺动词正则 — 待迁 open_thread_vocab.json
        ('jarvis_self_promise.py', '_EN_PROMISE_PATTERNS'),  # 英文承诺 — 待迁 self_promise_vocab.json
        ('jarvis_self_promise.py', '_ZH_PROMISE_PATTERNS'),  # 中文承诺 — 同上
        ('jarvis_self_promise.py', '_REJECT_PATTERNS'),      # 拒绝模式 — 待迁 reject_vocab.json
        ('jarvis_skill_registry.py', '_CLAIM_PATTERNS'),     # claim 提取 — 待迁 claim_vocab.json
        ('jarvis_predicate.py', '_WAKE_KEYWORDS'),           # 唤醒词 — 待迁 predicate_wake_vocab.json
        ('jarvis_predicate.py', '_EXPORT_KEYWORDS'),         # 导出词 — 同上
        ('jarvis_predicate.py', '_PREMIERE_KEYWORDS'),       # premiere 词 — 同上
        ('scripts/jarvis_dashboard.py', '_EVENT_PATTERNS'),       # dashboard CLI 事件 regex (CLI 工具, 优先级低)
        ('scripts/proactive_care_tail.py', '_EVENT_PATTERNS'),    # proactive_care 后台事件 regex (CLI 工具, 优先级低)
    ]

    # 系统级常量豁免 — 不算违规, 不必进 allow-list, 但 grep 会命中, 测试要排除
    SYSTEM_CONSTANTS_EXEMPT = {
        ('jarvis_utils.py', '_COLOR_PATTERNS'),         # terminal ANSI 着色 regex
        ('jarvis_utils.py', '_NON_RETRYABLE_KEYWORDS'),  # API 错误码黑名单
    }

    def _scan_hardcoded(self, pattern_type='PATTERNS'):
        """扫描所有 _<X>_PATTERNS = [...] 或 _<X>_KEYWORDS = (...) 命中, 排除 _SEED_ 前缀."""
        files = _iter_project_py_files()
        # 行首允许有缩进 (class 内可能), 但通常硬编码是 module-level
        rx = re.compile(rf'^(_[A-Z][A-Z_0-9]*_{pattern_type})\s*=\s*[\[\(]')
        hits = []
        for fp in files:
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    for lineno, line in enumerate(f, 1):
                        m = rx.match(line)
                        if not m:
                            continue
                        var_name = m.group(1)
                        if var_name.startswith('_SEED_'):
                            continue
                        rel = os.path.relpath(fp, ROOT).replace('\\', '/')
                        if (rel, var_name) in self.SYSTEM_CONSTANTS_EXEMPT:
                            continue
                        hits.append((rel, var_name, lineno))
            except Exception:
                continue
        return hits

    def test_patterns_hardcoded_within_allowlist(self):
        """`_<X>_PATTERNS = [...]` 命中数 ≤ ALLOW_LIST 长度. 任何新增 → FAIL."""
        hits = self._scan_hardcoded('PATTERNS')
        allow_set = {(f, v) for f, v in self.ALLOW_LIST_VOCAB_HARDCODED}
        hits_set = {(f, v) for f, v, _ln in hits}
        new_violations = hits_set - allow_set
        self.assertEqual(
            new_violations, set(),
            msg=(
                f"准则 6.5 红线: 新加 `_<X>_PATTERNS = [...]` 硬编码 in py 违规.\n"
                f"应该迁到 memory_pool/<x>_vocab.json + scripts/<x>_dump.py CLI (照搬 β.3.0-vocab1 范式).\n"
                f"新违规:\n" +
                "\n".join(f"  {f}: {v}" for f, v in sorted(new_violations))))

    def test_allowlist_not_obsolete(self):
        """ALLOW_LIST 不能含已经被迁走的 stale 条目 (rat-chet 收紧机制).

        联合 scan PATTERNS + KEYWORDS, 因为 allow-list 是混合 (predicate.py 是 _KEYWORDS).
        """
        hits_p = self._scan_hardcoded('PATTERNS')
        hits_k = self._scan_hardcoded('KEYWORDS')
        hits_set = {(f, v) for f, v, _ln in (hits_p + hits_k)}
        allow_set = {(f, v) for f, v in self.ALLOW_LIST_VOCAB_HARDCODED}
        obsolete = allow_set - hits_set
        self.assertEqual(
            obsolete, set(),
            msg=(
                f"ratcheting: ALLOW_LIST_VOCAB_HARDCODED 含已经被迁走的 stale 条目, 请从 list 删除:\n" +
                "\n".join(f"  {f}: {v}" for f, v in sorted(obsolete))))

    def test_keywords_hardcoded_within_allowlist(self):
        """`_<X>_KEYWORDS = (...)` 命中数 ≤ ALLOW_LIST 长度. 任何新增 → FAIL."""
        hits = self._scan_hardcoded('KEYWORDS')
        allow_set = {(f, v) for f, v in self.ALLOW_LIST_VOCAB_HARDCODED}
        hits_set = {(f, v) for f, v, _ln in hits}
        new_violations = hits_set - allow_set
        self.assertEqual(
            new_violations, set(),
            msg=(
                f"准则 6.5 红线: 新加 `_<X>_KEYWORDS = (...)` 硬编码 in py 违规.\n"
                f"应该迁到 memory_pool/<x>_vocab.json + scripts/<x>_dump.py CLI.\n"
                f"新违规:\n" +
                "\n".join(f"  {f}: {v}" for f, v in sorted(new_violations))))


class TestHandoffArtifacts(unittest.TestCase):
    """docs/AGENT_HANDOFF_PROTOCOL.md 三阶段交接基础设施 — 必备文件存在."""

    def test_python_style_doc_exists(self):
        """docs/JARVIS_PYTHON_STYLE.md 跨 agent 硬规真理源, 必须存在."""
        path = os.path.join(ROOT, 'docs', 'JARVIS_PYTHON_STYLE.md')
        self.assertTrue(
            os.path.exists(path),
            f"docs/JARVIS_PYTHON_STYLE.md 必须存在 (跨 agent 硬规单点真相). 缺失 → 非 Cursor agent (Windsurf/Codex/Claude Code) 看不到 python style 硬规.")

    def test_handoff_protocol_doc_exists(self):
        """docs/AGENT_HANDOFF_PROTOCOL.md 三阶段交接协议必须存在."""
        path = os.path.join(ROOT, 'docs', 'AGENT_HANDOFF_PROTOCOL.md')
        self.assertTrue(
            os.path.exists(path),
            f"docs/AGENT_HANDOFF_PROTOCOL.md 必须存在 (agent 接力赛闭环协议).")

    def test_kickoff_template_doc_exists(self):
        """docs/AGENT_KICKOFF_TEMPLATE.md 完工交接填空模板必须存在."""
        path = os.path.join(ROOT, 'docs', 'AGENT_KICKOFF_TEMPLATE.md')
        self.assertTrue(
            os.path.exists(path),
            f"docs/AGENT_KICKOFF_TEMPLATE.md 必须存在 (HANDOFF 阶段 3 用).")

    def test_agents_md_section12_present(self):
        """AGENTS.md 必须含 §12 Agent Handoff Protocol 速览."""
        path = os.path.join(ROOT, 'AGENTS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn(
            '## 12. Agent Handoff Protocol', content,
            f"AGENTS.md §12 必须存在 (引用 docs/AGENT_HANDOFF_PROTOCOL.md). β.3.2 加.")
        self.assertIn(
            '## 13. 当前迭代状态', content,
            f"AGENTS.md §13 必须存在 (原 §12 改名). 重命名错误检测.")

    def test_python_style_mdc_is_mirror_pointer(self):
        """`.cursor/rules/jarvis_python_style.mdc` 应是 outline mirror pointer, 不应是 doc 副本."""
        path = os.path.join(ROOT, '.cursor', 'rules', 'jarvis_python_style.mdc')
        if not os.path.exists(path):
            self.skipTest(f".cursor/rules/jarvis_python_style.mdc 不存在 (可能 .gitignore 忽略, 非致命)")
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn(
            '真理源', content,
            f"mdc 必须含 '真理源' 字样指向 docs/JARVIS_PYTHON_STYLE.md (β.3.1 立).")
        self.assertIn(
            'docs/JARVIS_PYTHON_STYLE.md', content,
            f"mdc 必须明确引用 docs/JARVIS_PYTHON_STYLE.md.")


class TestRuleSixFiveCharter(unittest.TestCase):
    """AGENTS.md 准则 6.5 文档自检 — 章程不能被悄悄改没."""

    def test_charter_rule_six_five_present(self):
        """AGENTS.md 必须含准则 6.5 段落 — 立项至今不可移除."""
        path = os.path.join(ROOT, 'AGENTS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        for required in [
            '准则 6.5',
            '动态架构必须',
            '持久化',
            'CLI 可改',
            'L7 Reflector LLM-propose',
        ]:
            self.assertIn(
                required, content,
                f"AGENTS.md 必须含准则 6.5 关键字 '{required}' (Sir 2026-05-18 12:57 立).")

    def test_charter_double_layer_reporting_present(self):
        """AGENTS.md §9.2 双层表达硬规必须存在."""
        path = os.path.join(ROOT, 'AGENTS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        for required in [
            '9.2 双层表达',
            '一句话:',
            '40 字',
        ]:
            self.assertIn(
                required, content,
                f"AGENTS.md §9.2 双层表达硬规缺失 '{required}' (β.3.0 立).")


if __name__ == '__main__':
    unittest.main(verbosity=2)
