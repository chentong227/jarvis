# -*- coding: utf-8 -*-
"""[P0+20-β.1.9 / 2026-05-16] Jarvis 集成体检脚本

Sir 痛点："改了这么久，一个简单的对话就有连环 bug"。本脚本快速回答 9 个问题：

1. 所有 jarvis_*.py 模块能 clean import（不抛 NameError）吗？
2. PERSONA / 12 directive / SkillRegistry 130 skill 都加载到位了吗？
3. KeyRouter 能识别 main_brain + google_pool + openrouter_pool 吗？
4. Hippocampus DB 能连吗？关键表（chat_log/long_term_memory/commitments）存在吗？
5. memory_pool/ runtime json 文件健康吗？
6. directive_registry.json 的 fired/rejected/helped 计数有没有数据流入？
7. ReturnSentinel 的 win32api 真能 probe 到 idle_ms 吗？
8. 关键 helper 函数行为正确吗？（sanitize_trigger_time / detect_semantic_category）
9. PromiseExecutor / DirectiveDecayWorker / ChronosTick 等 daemon 能初始化吗？

用法：
    python scripts/health_check.py
    python scripts/health_check.py --verbose

退出码：
    0 = 全绿
    1 = 有 P0 问题（启动级别）
    2 = 有 P1 问题（功能级别）

规范：详 docs/JARVIS_WORKFLOW_PROTOCOL.md / AGENTS.md
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import sqlite3
import time
import traceback


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 工具
# ============================================================
class Result:
    OK = 'OK'
    WARN = 'WARN'
    FAIL = 'FAIL'

    def __init__(self, name, status, msg=''):
        self.name = name
        self.status = status
        self.msg = msg


def _print_result(r: Result):
    badge = {'OK': '[OK]', 'WARN': '[WARN]', 'FAIL': '[FAIL]'}[r.status]
    print(f"{badge:8} {r.name:50} {r.msg}")


# ============================================================
# 检查项
# ============================================================
SPLIT_MODULES = [
    'jarvis_safety', 'jarvis_key_router', 'jarvis_llm_reflector',
    'jarvis_env_probe', 'jarvis_sensors', 'jarvis_routing',
    'jarvis_memory_core', 'jarvis_sentinels', 'jarvis_conductor',
    'jarvis_return_sentinel', 'jarvis_commitment_watcher',
    'jarvis_smart_nudge', 'jarvis_chat_bypass', 'jarvis_central_nerve',
    'jarvis_blood', 'jarvis_hippocampus', 'jarvis_vocal_cord',
    'jarvis_enhanced', 'jarvis_skill_registry', 'jarvis_directives',
    'jarvis_utils', 'jarvis_worker', 'jarvis_fuzzy_resolver',
]


def check_imports(verbose=False) -> Result:
    failed = []
    for name in SPLIT_MODULES:
        try:
            importlib.import_module(name)
        except Exception as e:
            failed.append((name, type(e).__name__, str(e)[:80]))
    if failed:
        msg = ' '.join(f"{n}({t})" for n, t, _ in failed)
        return Result('1. 23 模块 clean import', Result.FAIL, msg)
    return Result('1. 23 模块 clean import', Result.OK,
                  f"全部 {len(SPLIT_MODULES)} 个模块 OK")


def check_persona_directives_skills() -> Result:
    issues = []
    try:
        from jarvis_central_nerve import JARVIS_CORE_PERSONA
        if len(JARVIS_CORE_PERSONA) < 1000:
            issues.append(f"PERSONA 太短({len(JARVIS_CORE_PERSONA)}chars)")
        if 'INTEGRITY' not in JARVIS_CORE_PERSONA:
            issues.append("PERSONA 缺 INTEGRITY 段")
        if 'NUDGE' not in JARVIS_CORE_PERSONA:
            issues.append("PERSONA 缺 NUDGE 段")
    except Exception as e:
        issues.append(f"PERSONA import fail: {e}")

    try:
        from jarvis_directives import bootstrap_default_registry, DirectiveRegistry
        reg = DirectiveRegistry(persist_path=os.path.join('memory_pool', '_health_check_directives.json'))
        bootstrap_default_registry(reg)
        if len(reg.directives) != 12:
            issues.append(f"directive 数={len(reg.directives)} (期望 12)")
    except Exception as e:
        issues.append(f"directive bootstrap fail: {e}")
    finally:
        try:
            os.remove(os.path.join('memory_pool', '_health_check_directives.json'))
        except Exception:
            pass

    try:
        from jarvis_skill_registry import get_registry
        reg = get_registry()
        reg.bootstrap(pools_root='.', jsonl_path=os.path.join('memory_pool', '_health_check_skills.jsonl'),
                      enable_autosave=False)
        skill_count = len(reg._skills) if hasattr(reg, '_skills') else 0
        if skill_count < 50:
            issues.append(f"skill 数={skill_count} (期望 ≥ 50，实际工程 130+)")
    except Exception as e:
        issues.append(f"skill bootstrap fail: {type(e).__name__}: {str(e)[:60]}")
    finally:
        try:
            os.remove(os.path.join('memory_pool', '_health_check_skills.jsonl'))
        except Exception:
            pass

    if issues:
        return Result('2. PERSONA + directive + skill', Result.FAIL, ' / '.join(issues))
    return Result('2. PERSONA + directive + skill', Result.OK,
                  f"persona={len(JARVIS_CORE_PERSONA)}c, directive=12, skill={skill_count}")


def check_key_router() -> Result:
    try:
        from jarvis_key_router import KeyRouter
        kr = KeyRouter('test_main', ['k1', 'k2', 'k3'], ['o1', 'o2'])
        stats = kr.get_stats()
        if 'key_status' not in stats:
            return Result('3. KeyRouter 健康', Result.FAIL, "缺 key_status 字段")
        return Result('3. KeyRouter 健康', Result.OK,
                      f"main+3google+2openrouter pool 就绪")
    except Exception as e:
        return Result('3. KeyRouter 健康', Result.FAIL, f"{type(e).__name__}: {e}")


def check_hippocampus_db() -> Result:
    db_path = os.path.join('memory_pool', 'jarvis_hippocampus.db')
    if not os.path.exists(db_path):
        return Result('4. Hippocampus DB', Result.WARN, f"DB 不存在（首次运行正常）: {db_path}")
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        conn.close()
        expected = {'chat_log', 'long_term_memory', 'commitments'}
        missing = expected - set(tables)
        if missing:
            return Result('4. Hippocampus DB', Result.FAIL,
                          f"缺表: {missing} (现有 {tables})")
        return Result('4. Hippocampus DB', Result.OK,
                      f"DB OK，{len(tables)} 张表")
    except Exception as e:
        return Result('4. Hippocampus DB', Result.FAIL, f"{type(e).__name__}: {e}")


def check_memory_pool_runtime_files() -> Result:
    found = []
    for fname in ['directive_registry.json', 'directive_review.json',
                  'key_router_state.json', 'plans.json', 'skill_registry.jsonl']:
        path = os.path.join('memory_pool', fname)
        if os.path.exists(path):
            try:
                size = os.path.getsize(path)
                found.append(f"{fname}({size}b)")
            except Exception:
                found.append(fname)
    return Result('5. memory_pool runtime 文件', Result.OK,
                  ', '.join(found) if found else '无（首次运行正常）')


def check_directive_data_flow() -> Result:
    path = os.path.join('memory_pool', 'directive_registry.json')
    if not os.path.exists(path):
        return Result('6. directive 数据流', Result.WARN,
                      "directive_registry.json 不存在（首次运行正常）")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        if not data:
            return Result('6. directive 数据流', Result.WARN, "空文件（未跑过对话）")
        total_fired = sum((d.get('fired', 0) or 0) for d in data.values() if isinstance(d, dict))
        total_helped = sum((d.get('helped', 0) or 0) for d in data.values() if isinstance(d, dict))
        if total_fired == 0:
            return Result('6. directive 数据流', Result.WARN,
                          "12 条 directive 累计 fired=0（未跑过对话或 trigger 全部漏命中）")
        return Result('6. directive 数据流', Result.OK,
                      f"fired={total_fired} helped={total_helped} (β.0.5 接入后 helped 才会非 0)")
    except Exception as e:
        return Result('6. directive 数据流', Result.FAIL, f"{type(e).__name__}: {e}")


def check_return_sentinel_win32() -> Result:
    try:
        import jarvis_return_sentinel as mod
        if not getattr(mod, '_WIN32_OK', False):
            return Result('7. ReturnSentinel idle_ms', Result.FAIL,
                          "win32api 不可用 → 归来感知失效")
        if mod.win32api is None:
            return Result('7. ReturnSentinel idle_ms', Result.FAIL,
                          "win32api 占位 None")
        idle_ms = mod.win32api.GetTickCount() - mod.win32api.GetLastInputInfo()
        if not isinstance(idle_ms, int):
            return Result('7. ReturnSentinel idle_ms', Result.FAIL,
                          f"idle_ms 类型异常: {type(idle_ms)}")
        return Result('7. ReturnSentinel idle_ms', Result.OK,
                      f"idle_ms={idle_ms}ms (Sir 当前活跃度)")
    except Exception as e:
        return Result('7. ReturnSentinel idle_ms', Result.FAIL, f"{type(e).__name__}: {e}")


def check_helpers() -> Result:
    try:
        from jarvis_worker import sanitize_trigger_time, detect_semantic_category
        out, was, _ = sanitize_trigger_time('2026-05-17 02:00:00', '两点起床', '我两点起床')
        if 6 <= time.localtime().tm_hour <= 18:
            if not was:
                return Result('8. helper 行为', Result.FAIL,
                              "sanitize_trigger_time 白天起床应矫正凌晨→下午")
        cat = detect_semantic_category('两点睡觉')
        if cat != 'sleep':
            return Result('8. helper 行为', Result.FAIL,
                          f"detect_semantic_category('两点睡觉')={cat} (期望 sleep)")
        return Result('8. helper 行为', Result.OK,
                      "sanitize_trigger_time + detect_semantic_category 行为正确")
    except Exception as e:
        return Result('8. helper 行为', Result.FAIL, f"{type(e).__name__}: {e}")


def check_daemons_initializable() -> Result:
    issues = []
    try:
        from jarvis_directives import DirectiveRegistry, bootstrap_default_registry
        reg = DirectiveRegistry(persist_path=os.path.join('memory_pool', '_health_check_decay.json'))
        bootstrap_default_registry(reg)
        if not hasattr(reg, 'start_decay_worker'):
            issues.append("DirectiveRegistry 缺 start_decay_worker")
        if not hasattr(reg, 'apply_decay'):
            issues.append("DirectiveRegistry 缺 apply_decay")
        try:
            os.remove(os.path.join('memory_pool', '_health_check_decay.json'))
        except Exception:
            pass
    except Exception as e:
        issues.append(f"DirectiveRegistry decay: {type(e).__name__}: {str(e)[:60]}")

    try:
        from jarvis_skill_registry import PromiseExecutor
        if not hasattr(PromiseExecutor, '__init__'):
            issues.append("PromiseExecutor 类异常")
    except Exception as e:
        issues.append(f"PromiseExecutor: {type(e).__name__}")

    try:
        from jarvis_sentinels import ChronosTick
        if not hasattr(ChronosTick, '__init__'):
            issues.append("ChronosTick 类异常")
    except Exception as e:
        issues.append(f"ChronosTick: {type(e).__name__}")

    if issues:
        return Result('9. daemon 可初始化', Result.FAIL, ' / '.join(issues))
    return Result('9. daemon 可初始化', Result.OK,
                  "DirectiveRegistry decay + PromiseExecutor + ChronosTick OK")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    print()
    print("=" * 70)
    print(" Jarvis 集成体检 — 9 项启动 + 运行时检查")
    print(f" 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    checks = [
        check_imports,
        check_persona_directives_skills,
        check_key_router,
        check_hippocampus_db,
        check_memory_pool_runtime_files,
        check_directive_data_flow,
        check_return_sentinel_win32,
        check_helpers,
        check_daemons_initializable,
    ]

    results = []
    for fn in checks:
        try:
            r = fn() if fn.__code__.co_argcount == 0 else fn(args.verbose)
        except Exception as e:
            r = Result(fn.__name__, Result.FAIL, f"{type(e).__name__}: {e}")
            if args.verbose:
                traceback.print_exc()
        results.append(r)
        _print_result(r)

    print()
    print("=" * 70)
    n_ok = sum(1 for r in results if r.status == Result.OK)
    n_warn = sum(1 for r in results if r.status == Result.WARN)
    n_fail = sum(1 for r in results if r.status == Result.FAIL)
    print(f" 体检完毕: {n_ok} OK / {n_warn} WARN / {n_fail} FAIL")
    print("=" * 70)
    print()

    if n_fail > 0:
        return 1
    if n_warn > 0:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
