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

# 🩹 [β.3.0 / 2026-05-18] Sir 16:18 实测 BUG 治本: 测试 fixture 不污染 latest.txt
# (dashboard 误把测试 log 当主进程 log → 0/12 daemon 恐吓). bg_log 看此 env.
os.environ.setdefault('JARVIS_TEST_MODE', '1')


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


# ============================================================
# 🩹 [β.2.9.7 / 2026-05-18] autouse: 隔离 prod 持久化路径, 防测试污染
# ============================================================
# Sir 09:06 实测痛点: tests/_test_p0_plus_20_beta273_self_promise.py 等不隔离
# 生产 promise_log.json → 跑 _runall.ps1 后 28 条 "我会监督您 13:05" 残留 → 真生产
# InconsistencyWatcher 反复 fire. 加 module-level autouse fixture 让任何 pytest
# 测试都自动改写 jarvis_promise_log._DEFAULT_LOG 到 tmp 路径, 测完恢复.
# unittest 风格脚本 (`python tests/_test_X.py`) 仍由 setUpModule 各自隔离.
@pytest.fixture(autouse=True)
def _autouse_isolate_prod_persistence(tmp_path, monkeypatch):
    """所有 pytest 测试默认隔离 prod persistence 路径. 单独 test 不需要时也无害."""
    tmp_promise_log = tmp_path / "jarvis_promise_log.json"
    tmp_promise_log.write_text("{}\n", encoding="utf-8")
    try:
        import jarvis_promise_log as _jpl
        # reset singleton + 切到 tmp path
        _jpl.reset_default_log_for_test(persist_path=str(tmp_promise_log))
    except Exception:
        pass

    # [Reshape M1 / 2026-05-24] 隔离 LineageTracer 生产 jsonl
    # Sir 真测发现 100+ testcase 跑 SWM publish 污染 memory_pool/lineage.jsonl
    # (1367 unknown / 1452 evidence). 每个 test 切自己 tmp path, 测完丢.
    try:
        import jarvis_lineage as _jln
        tmp_lineage_jsonl = tmp_path / "lineage_test.jsonl"
        _isolated_tracer = _jln.LineageTracer(
            jsonl_path=str(tmp_lineage_jsonl),
            auto_start_flush=False,   # 不启 daemon, 测试 deterministic
        )
        _jln.reset_default_tracer_for_test(_isolated_tracer)
    except Exception:
        pass

    yield

    # 测试完: 重置单例 (next test / cleanup 用 prod path 再 lazy init)
    try:
        import jarvis_promise_log as _jpl
        _jpl.reset_default_log_for_test()
    except Exception:
        pass

    # [Reshape M1 / 2026-05-24] 测试完重置 LineageTracer 单例
    try:
        import jarvis_lineage as _jln
        _jln.reset_default_tracer_for_test(None)
    except Exception:
        pass


# ============================================================
# 🆕 [Sir 2026-05-28 14:55 Track 1] Generic memory_pool diff detector
# ============================================================
# 历史 BUG (β.5.45 调查): tests/_test_p0_plus_20_p5_fix23_meta_protect.py
# 跑 `DirectiveRegistry()` 无 args → write prod `memory_pool/directive_review.json`
# 累计 16 条 'regular_directive' 测试残留, Sir 12:59 review queue 全是垃圾.
#
# Root cause: 单点隔离 (上面 promise_log + lineage 各 1 fixture) 不能 cover
# 所有 prod module 写盘行为. 加 generic checksum diff detector — test 跑前
# hash memory_pool 全部 .json + .jsonl, 跑后再 hash, diff = log warning.
#
# 默认 warning mode (不 fail test, 让 Sir 自决修哪个 module). Env
# `JARVIS_TEST_STRICT_ISOLATION=1` → 升级 fail mode (CI 用).
#
# 准则 6: 检测目标 (memory_pool/*.json + *.jsonl) 不 vocab 化 — 这是 system
# 内部测试基建常量 (准则 6 递归边界).
# ============================================================
import hashlib as _hashlib  # noqa: E402

_MEMORY_POOL = _REPO_ROOT / "memory_pool"
# 这些 file Sir 显式接受 test 改 (e.g. tmp test 文件, 或测试 fixture 文件).
# 用 prefix 而不是 vocab 是因为这是 system-internal 测试基建常量 (准则 6 递归边界).
_ALLOW_TEST_MUTATE_PREFIX = (
    "_test_",  # test fixture 文件 (test 显式写)
    "_tmp_",   # 临时调试 (Sir 知情)
)


def _scan_memory_pool_checksum() -> dict:
    """返 {filename: sha256_hex} for memory_pool/*.json + *.jsonl.

    跳过 _test_* / _tmp_* prefix (test 显式 mutate 文件).
    """
    out = {}
    if not _MEMORY_POOL.exists():
        return out
    for p in _MEMORY_POOL.glob("*.json"):
        if p.name.startswith(_ALLOW_TEST_MUTATE_PREFIX):
            continue
        try:
            data = p.read_bytes()
            out[p.name] = _hashlib.sha256(data).hexdigest()
        except OSError:
            pass
    for p in _MEMORY_POOL.glob("*.jsonl"):
        if p.name.startswith(_ALLOW_TEST_MUTATE_PREFIX):
            continue
        try:
            data = p.read_bytes()
            out[p.name] = _hashlib.sha256(data).hexdigest()
        except OSError:
            pass
    return out


@pytest.fixture(autouse=True)
def _autouse_detect_memory_pool_mutation(request):
    """Test 跑前/后 hash memory_pool/*.json[l]. Diff = warning (or fail in
    strict env). 防止 test 污染 prod queue / vocab.

    历史 case: tests/_test_p0_plus_20_p5_fix23_meta_protect.py::
               test_priority_9_still_decays_normally 跑 DirectiveRegistry()
               无 args → 写 prod `memory_pool/directive_review.json` 16 条
               `regular_directive` 污染.
    """
    before = _scan_memory_pool_checksum()
    yield
    after = _scan_memory_pool_checksum()
    mutated = []
    for fn, h_after in after.items():
        h_before = before.get(fn)
        if h_before is None:
            mutated.append((fn, 'created'))
        elif h_before != h_after:
            mutated.append((fn, 'modified'))
    for fn in before:
        if fn not in after:
            mutated.append((fn, 'deleted'))
    if not mutated:
        return
    test_id = getattr(request.node, 'nodeid', '?')
    msg = (
        f"\n⚠️ [conftest/MemoryPool-mutation] test={test_id} 改了 prod\n"
        f"   memory_pool 文件 (应隔离 tmp_path 或 inject path):\n"
    )
    for fn, kind in mutated:
        msg += f"     - {kind}: {fn}\n"
    sys.stderr.write(msg)
    if os.environ.get('JARVIS_TEST_STRICT_ISOLATION') == '1':
        pytest.fail(msg)
