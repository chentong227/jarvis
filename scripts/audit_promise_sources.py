# -*- coding: utf-8 -*-
"""[Reshape M4.2 / 2026-05-24] PromiseLog 5 source audit script (dry-run, 只读不写).

显示当前 5 个 promise source 的数据量 + sample, 帮 Sir 决定:
  1. 哪些 source 真有数据需要 migrate
  2. 数据 schema 真长什么样
  3. 估算 migration 后的 PromiseLog 大小

不写任何文件, 安全可重复跑.

用法:
    python scripts/audit_promise_sources.py
"""
import os
import sys
import json
import sqlite3
from typing import Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ANSI 颜色简化
GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'


def _section(name: str) -> None:
    print(f"\n{BOLD}{CYAN}═══ {name} ═══{RESET}")


def _kv(k: str, v) -> None:
    print(f"  {YELLOW}{k}{RESET}: {v}")


def audit_promise_log() -> Dict:
    """Source 1 (目标): jarvis_promise_log.json"""
    _section('Source 1: PromiseLog (目标, 已存在)')
    path = os.path.join(ROOT, 'memory_pool', 'jarvis_promise_log.json')
    _kv('path', path)
    if not os.path.exists(path):
        _kv('status', f'{YELLOW}NOT EXISTS{RESET}')
        return {'count': 0, 'states': {}, 'kinds': {}}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        _kv('error', f'{YELLOW}load failed: {e}{RESET}')
        return {'count': 0, 'states': {}, 'kinds': {}}
    states, kinds = {}, {}
    for pid, p in data.items():
        s = p.get('state', '?')
        k = p.get('kind', '?')
        states[s] = states.get(s, 0) + 1
        kinds[k] = kinds.get(k, 0) + 1
    _kv('total', len(data))
    _kv('states', states)
    _kv('kinds', kinds)
    return {'count': len(data), 'states': states, 'kinds': kinds}


def audit_commitments_sqlite() -> Dict:
    """Source 2: SQLite Commitments table"""
    _section('Source 2: CommitmentWatcher SQLite (Commitments table)')
    db_path = os.path.join(ROOT, 'memory_pool', 'jarvis_memory.db')
    _kv('db_path', db_path)
    if not os.path.exists(db_path):
        _kv('status', f'{YELLOW}NOT EXISTS{RESET}')
        return {'count': 0, 'active': 0, 'nudged': 0}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # 检表是否存在
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Commitments'")
        if not cur.fetchone():
            _kv('status', f'{YELLOW}Commitments table NOT EXISTS{RESET}')
            conn.close()
            return {'count': 0, 'active': 0, 'nudged': 0}
        cur.execute("SELECT COUNT(*) FROM Commitments")
        total = cur.fetchone()[0]
        # 🩹 [M4.4-fix / 2026-05-24] active = nudged=0 AND is_deleted=0 (跟 migration script 对齐).
        # 老版本只用 nudged=0 漏过滤 is_deleted, 导致 migrate 后 audit 仍显示 active>0 不符现实.
        cur.execute("SELECT COUNT(*) FROM Commitments WHERE nudged=0 AND is_deleted=0")
        active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM Commitments WHERE nudged=1")
        nudged = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM Commitments WHERE is_deleted=1")
        deleted = cur.fetchone()[0]
        _kv('total', total)
        _kv('active (nudged=0 AND is_deleted=0)', active)
        _kv('nudged (nudged=1)', nudged)
        _kv('deleted (is_deleted=1)', deleted)
        # sample of 真 active only
        cur.execute("SELECT description, deadline_ts, created_at FROM Commitments WHERE nudged=0 AND is_deleted=0 ORDER BY created_at DESC LIMIT 3")
        rows = cur.fetchall()
        if rows:
            _kv('latest 3 sample', '')
            for r in rows:
                print(f"    - {r[0][:50]} (deadline_ts={r[1]:.0f}, created_at={r[2]:.0f})")
        conn.close()
        return {'count': total, 'active': active, 'nudged': nudged}
    except Exception as e:
        _kv('error', f'{YELLOW}query failed: {e}{RESET}')
        return {'count': 0, 'active': 0, 'nudged': 0}


def audit_cyclic_task() -> Dict:
    """Source 3: cyclic_task_protocol.json"""
    _section('Source 3: CyclicTask (cyclic_task_protocol.json)')
    path = os.path.join(ROOT, 'memory_pool', 'cyclic_task_protocol.json')
    _kv('path', path)
    if not os.path.exists(path):
        _kv('status', f'{YELLOW}NOT EXISTS{RESET}')
        return {'count': 0, 'active': 0}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        _kv('error', f'{YELLOW}load failed: {e}{RESET}')
        return {'count': 0, 'active': 0}
    tasks = raw.get('tasks', []) if isinstance(raw, dict) else []
    active = sum(1 for t in tasks if t.get('state') == 'active')
    _kv('total', len(tasks))
    _kv('active', active)
    if tasks:
        _kv('sample (first 2)', '')
        for t in tasks[:2]:
            print(f"    - id={t.get('task_id', '?')[:30]} "
                  f"kind={t.get('kind', '?')} "
                  f"cycle={t.get('cycle_minutes', 0)}min "
                  f"desc='{(t.get('description', '') or '')[:40]}'")
    return {'count': len(tasks), 'active': active}


def audit_watch_task() -> Dict:
    """Source 4: watch_tasks.json"""
    _section('Source 4: WatchTask (watch_tasks.json)')
    path = os.path.join(ROOT, 'memory_pool', 'watch_tasks.json')
    _kv('path', path)
    if not os.path.exists(path):
        _kv('status', f'{YELLOW}NOT EXISTS{RESET}')
        return {'count': 0, 'active': 0}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        _kv('error', f'{YELLOW}load failed: {e}{RESET}')
        return {'count': 0, 'active': 0}
    tasks = data.get('tasks', []) if isinstance(data, dict) else []
    active = sum(1 for t in tasks if t.get('state') == 'active')
    _kv('total', len(tasks))
    _kv('active', active)
    if tasks:
        _kv('sample (first 2)', '')
        for t in tasks[:2]:
            print(f"    - id={t.get('id', '?')[:30]} "
                  f"state={t.get('state', '?')} "
                  f"watch='{(t.get('what_to_watch', '') or '')[:40]}'")
    return {'count': len(tasks), 'active': active}


def audit_concerns_notes() -> Dict:
    """Source 5: concerns.json notes_for_self field (across all concerns)."""
    _section('Source 5: concerns.json notes_for_self (in each concern)')
    path = os.path.join(ROOT, 'memory_pool', 'concerns.json')
    _kv('path', path)
    if not os.path.exists(path):
        _kv('status', f'{YELLOW}NOT EXISTS{RESET}')
        return {'concerns': 0, 'with_notes': 0, 'pending_ack': 0}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        _kv('error', f'{YELLOW}load failed: {e}{RESET}')
        return {'concerns': 0, 'with_notes': 0, 'pending_ack': 0}
    concerns = data.get('concerns', {}) if isinstance(data, dict) else {}
    total = len(concerns)
    with_notes = 0
    pending_ack = 0
    samples = []
    for cid, c in concerns.items():
        notes = (c.get('notes_for_self') or '').strip()
        if notes:
            with_notes += 1
            if '[pending_ack' in notes:
                pending_ack += 1
            if len(samples) < 3:
                samples.append(f"{cid}: '{notes[:80]}'")
    _kv('total_concerns', total)
    _kv('with_notes_for_self', with_notes)
    _kv('含 [pending_ack]', pending_ack)
    if samples:
        _kv('sample (first 3)', '')
        for s in samples:
            print(f"    - {s}")
    return {'concerns': total, 'with_notes': with_notes, 'pending_ack': pending_ack}


def main() -> None:
    print(f"{BOLD}{GREEN}╔══════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{GREEN}║  [Reshape M4.2] PromiseLog 5 source migration audit (DRY)  ║{RESET}")
    print(f"{BOLD}{GREEN}╚══════════════════════════════════════════════════════════════╝{RESET}")

    s1 = audit_promise_log()
    s2 = audit_commitments_sqlite()
    s3 = audit_cyclic_task()
    s4 = audit_watch_task()
    s5 = audit_concerns_notes()

    _section('Migration Plan (估算)')
    new_promises_estimated = (
        s2.get('active', 0) + s3.get('active', 0) +
        s4.get('active', 0) + s5.get('pending_ack', 0)
    )
    _kv('PromiseLog 现有', s1.get('count', 0))
    _kv('Commitments active → kind=commitment', s2.get('active', 0))
    _kv('CyclicTask active → kind=cyclic', s3.get('active', 0))
    _kv('WatchTask active → kind=watch', s4.get('active', 0))
    _kv('Concerns pending_ack → bound_to_concern_id', s5.get('pending_ack', 0))
    _kv(f'{BOLD}迁后 PromiseLog 总数 (estimated){RESET}',
        f"{s1.get('count', 0)} + {new_promises_estimated} = {s1.get('count', 0) + new_promises_estimated}")

    _section('Sir Decision')
    if new_promises_estimated == 0:
        print(f"  {GREEN}[OK] 4 source (Commitments/Cyclic/Watch/Concerns) 0 active data{RESET}")
        print(f"  {GREEN}[OK] Safe to skip M4.4 apply migration{RESET}")
        print(f"  {GREEN}-> Next: M4.5+ CommitmentWatcher degrade + caller replace{RESET}")
    elif new_promises_estimated < 20:
        print(f"  {YELLOW}[WARN] {new_promises_estimated} rows pending migration{RESET}")
        print(f"  -> M4.4 dry-run + manual review")
    else:
        print(f"  {YELLOW}[WARN] {new_promises_estimated} rows pending migration (large){RESET}")
        print(f"  -> M4.4 must backup + batch migrate")


if __name__ == '__main__':
    main()
