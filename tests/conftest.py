# -*- coding: utf-8 -*-
"""[P0+20-W.3 / 2026-05-16] pytest 全局 fixture / hook

只对 pytest 模式生效（`pytest tests/` 或 `pytest tests/some_test.py`）。
现有 46 个 unittest 风格脚本（`python tests/_test_X.py`）不走 pytest，
它们的统计由 `tests/_runall.ps1` 直接收集 + 写 last_run.json。

本文件提供：
1. `trace_id` fixture — 每个 test 一个独立的 trace_id（用于结构化日志断言）
2. `pytest_sessionstart` — 生成 test_run_id + 抓 git head/branch
3. `pytest_sessionfinish` — 把本次 pytest 结果写到 tests/last_run.json
   （只在直接跑 pytest 时生效；走 _runall.ps1 时 PS1 末尾自己写）

规范：详 docs/JARVIS_WORKFLOW_PROTOCOL.md §2
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_LAST_RUN_JSON = _REPO_ROOT / "tests" / "last_run.json"


def _git_head_short() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _git_branch() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S") + f".{int((time.time() % 1) * 1000):03d}Z"


# ============================================================
# Session-level state (in-memory) — pytest_sessionfinish 写盘
# ============================================================
_SESSION_STATE: dict = {
    "test_run_id": "",
    "git_head": "",
    "git_branch": "",
    "started_at": "",
    "started_ts": 0.0,
    "marker_context": os.environ.get("JARVIS_TEST_MARKER", ""),
    "runner": "pytest",
}


def pytest_sessionstart(session):
    """pytest 会话开始：分配 test_run_id + 抓 git 元信息。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    rid = secrets.token_hex(2)
    _SESSION_STATE["test_run_id"] = f"test_{ts}_{rid}"
    _SESSION_STATE["git_head"] = _git_head_short()
    _SESSION_STATE["git_branch"] = _git_branch()
    _SESSION_STATE["started_at"] = _now_iso()
    _SESSION_STATE["started_ts"] = time.time()
    sys.stderr.write(
        f"\n[conftest] test_run_id={_SESSION_STATE['test_run_id']} "
        f"git_head={_SESSION_STATE['git_head']} "
        f"branch={_SESSION_STATE['git_branch']}\n"
    )


def pytest_sessionfinish(session, exitstatus):
    """pytest 会话结束：写 tests/last_run.json。"""
    try:
        tr = getattr(session, "testsfailed", 0)
        # session 直接没暴露 passed/skipped 计数，从 stats（terminalreporter）拿
        passed = failed = skipped = errors = 0
        try:
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                stats = getattr(reporter, "stats", {}) or {}
                passed = len(stats.get("passed", []))
                failed = len(stats.get("failed", []))
                skipped = len(stats.get("skipped", []))
                errors = len(stats.get("error", []))
        except Exception:
            failed = tr or 0

        failed_names = []
        try:
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                for rep in (reporter.stats.get("failed", []) or []):
                    nodeid = getattr(rep, "nodeid", "") or ""
                    if nodeid:
                        failed_names.append(nodeid)
        except Exception:
            pass

        ended_ts = time.time()
        report = {
            "test_run_id": _SESSION_STATE["test_run_id"],
            "git_head": _SESSION_STATE["git_head"],
            "git_branch": _SESSION_STATE["git_branch"],
            "started_at": _SESSION_STATE["started_at"],
            "ended_at": _now_iso(),
            "duration_s": round(ended_ts - _SESSION_STATE["started_ts"], 2),
            "exitstatus": int(exitstatus),
            "runner": "pytest",
            "marker_context": _SESSION_STATE["marker_context"],
            "summary": {
                "total": passed + failed + skipped + errors,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
            },
            "failed_tests": failed_names,
        }
        _LAST_RUN_JSON.parent.mkdir(parents=True, exist_ok=True)
        _LAST_RUN_JSON.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sys.stderr.write(
            f"[conftest] last_run.json written: {_LAST_RUN_JSON} "
            f"(passed={passed} failed={failed} skipped={skipped} errors={errors})\n"
        )
    except Exception as e:
        sys.stderr.write(f"[conftest] failed to write last_run.json: {e}\n")


# ============================================================
# Per-test fixture: trace_id
# ============================================================
@pytest.fixture
def trace_id(request) -> str:
    """每个 test 一个独立 trace_id，供结构化日志断言用。
    
    用法：
        def test_xxx(trace_id, capsys):
            bg_log(f"hello {trace_id}")
            assert trace_id in capsys.readouterr().err
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    rid = secrets.token_hex(2)
    tid = f"test_{ts}_{rid}_{request.node.name[:20]}"
    return tid
