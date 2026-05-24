# -*- coding: utf-8 -*-
"""[Reshape M4.4 / 2026-05-24] Migrate active Commitments → PromiseLog single source.

Sir 准则 8: 安全 + 可回滚.
  1. dry-run 模式 (默认): 只输出 plan diff, 不写
  2. apply 模式: 自动 backup + 真写 + verify + 标记原 SQLite row nudged=1

Backup 路径: _legacy/data_migration_backup/<timestamp>/
  - jarvis_memory.db (含原 Commitments)
  - jarvis_promise_log.json (原 PromiseLog snapshot)

Migration 规则:
  - 只迁 nudged=0 AND is_deleted=0 (真 active 老数据)
  - PromiseLog.register(kind='commitment', who_promised='sir', author='sir')
  - deadline_str format: 'YYYY-MM-DD HH:MM:SS' (跟 PromiseLog 老数据格式一致)
  - SQLite row 标 nudged=1 (避免 CommitmentWatcher daemon 再 fire)

回滚: restore backup 即可
  Copy-Item _legacy/data_migration_backup/<timestamp>/jarvis_memory.db memory_pool/
  Copy-Item _legacy/data_migration_backup/<timestamp>/jarvis_promise_log.json memory_pool/

用法:
    python scripts/migrate_commitments_to_promise_log.py             # dry-run (默认)
    python scripts/migrate_commitments_to_promise_log.py --apply    # 真执行
    python scripts/migrate_commitments_to_promise_log.py --rollback <timestamp>  # 回滚到 backup
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
CYAN = '\033[96m'
BOLD = '\033[1m'
RESET = '\033[0m'

DB_PATH = os.path.join(ROOT, 'memory_pool', 'jarvis_memory.db')
PLOG_PATH = os.path.join(ROOT, 'memory_pool', 'jarvis_promise_log.json')
BACKUP_BASE = os.path.join(ROOT, '_legacy', 'data_migration_backup')


def _info(msg: str) -> None:
    print(f"{CYAN}[migrate]{RESET} {msg}")


def _ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def _err(msg: str) -> None:
    print(f"{RED}[ERR]{RESET} {msg}")


def fetch_active_commitments() -> list:
    """读 active 老 Commitments (nudged=0 AND is_deleted=0)."""
    if not os.path.exists(DB_PATH):
        return []
    rows = []
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            'SELECT id, description, deadline_ts, grace_minutes, source_text, created_at '
            'FROM Commitments WHERE nudged=0 AND is_deleted=0 '
            'ORDER BY created_at ASC'
        )
        for r in cur.fetchall():
            rows.append({
                'db_id': r[0],
                'description': r[1] or '',
                'deadline_ts': r[2] or 0.0,
                'grace_minutes': r[3] or 10,
                'source_text': r[4] or '',
                'created_at': r[5] or 0.0,
            })
        conn.close()
    except Exception as e:
        _err(f'fetch_active_commitments: {e}')
    return rows


def is_already_migrated(plog_data: dict, c: dict) -> bool:
    """检 PromiseLog 是否已含这条 Commitment (防重复 migrate).

    匹配规则: same description (lowercase strip) + same author=sir
              AND registered_at within 60s of created_at.
    """
    desc_l = (c['description'] or '').strip().lower()
    if not desc_l:
        return False
    cat = c['created_at']
    for pid, p in plog_data.items():
        if (p.get('description') or '').strip().lower() != desc_l:
            continue
        if p.get('author') != 'sir':
            continue
        pra = p.get('registered_at', 0)
        if abs(pra - cat) < 60:  # within 1min = same event
            return True
    return False


def plan_migration() -> dict:
    """dry-run plan: 列要迁的 + 哪些已 migrated."""
    rows = fetch_active_commitments()
    # 读 PromiseLog
    if os.path.exists(PLOG_PATH):
        try:
            with open(PLOG_PATH, 'r', encoding='utf-8') as f:
                plog_data = json.load(f) or {}
        except Exception:
            plog_data = {}
    else:
        plog_data = {}

    to_migrate = []
    already = []
    for c in rows:
        if is_already_migrated(plog_data, c):
            already.append(c)
        else:
            to_migrate.append(c)
    return {
        'plog_size_before': len(plog_data),
        'commitments_active': len(rows),
        'to_migrate': to_migrate,
        'already_migrated': already,
    }


def print_plan(plan: dict) -> None:
    print(f"\n{BOLD}{CYAN}═══ Migration Plan (dry-run){RESET}")
    print(f"  PromiseLog 现有: {plan['plog_size_before']}")
    print(f"  Commitments active 总数: {plan['commitments_active']}")
    print(f"  {GREEN}待迁{RESET}: {len(plan['to_migrate'])}")
    print(f"  {YELLOW}已迁过 (跳过){RESET}: {len(plan['already_migrated'])}")
    if plan['to_migrate']:
        print(f"\n  待迁列表:")
        for c in plan['to_migrate']:
            iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                  time.localtime(c['deadline_ts']))
            print(f"    - db_id={c['db_id']} deadline={iso} "
                  f"desc='{c['description'][:50]}'")
    if plan['already_migrated']:
        print(f"\n  已迁过 (skip):")
        for c in plan['already_migrated']:
            print(f"    - db_id={c['db_id']} '{c['description'][:50]}'")
    print(f"  迁后 PromiseLog 总数: "
          f"{plan['plog_size_before'] + len(plan['to_migrate'])}")


def make_backup(timestamp: str) -> str:
    """backup db + json. 返 backup dir."""
    backup_dir = os.path.join(BACKUP_BASE, timestamp)
    os.makedirs(backup_dir, exist_ok=True)
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, os.path.join(backup_dir, 'jarvis_memory.db'))
        _ok(f'backup jarvis_memory.db → {backup_dir}')
    if os.path.exists(PLOG_PATH):
        shutil.copy2(PLOG_PATH,
                      os.path.join(backup_dir, 'jarvis_promise_log.json'))
        _ok(f'backup jarvis_promise_log.json → {backup_dir}')
    return backup_dir


def apply_migration(plan: dict) -> bool:
    """真执行: backup → write PromiseLog → mark SQLite nudged=1."""
    if not plan['to_migrate']:
        _info('0 rows to migrate, nothing to do.')
        return True

    # 1. backup
    timestamp = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    backup_dir = make_backup(timestamp)

    # 2. 写 PromiseLog. 直接 instantiate 用 PLOG_PATH 让 test 能 monkey-patch.
    # (prod 跑时 PLOG_PATH = default, 跟 singleton 一样;
    #  test 跑时 PLOG_PATH 被 patch 到 tmpdir, 直接 instantiate 不走 singleton.)
    from jarvis_promise_log import PromiseExecutionLog
    plog = PromiseExecutionLog(persist_path=PLOG_PATH)
    migrated_pids = []
    for c in plan['to_migrate']:
        iso_dl = time.strftime('%Y-%m-%d %H:%M:%S',
                                 time.localtime(c['deadline_ts']))
        pid = plog.register(
            description=c['description'][:300],
            kind='commitment',  # 新 4 kind 之一
            deadline_str=iso_dl,
            jarvis_reply='',  # Commitments 没存
            turn_id='',
            lang='',
            author='sir',
        )
        # 设新 field
        p = plog.promises.get(pid)
        if p is not None:
            p.who_promised = 'sir'
            # registered_at 用原 created_at 保历史时间
            p.registered_at = c['created_at']
            # 加 migration evidence
            p.evidence.append({
                'when': time.time(),
                'when_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                            time.localtime()),
                'kind': 'migration',
                'what': f'M4.4 migrated from Commitments db_id={c["db_id"]}',
            })
        migrated_pids.append((c['db_id'], pid))
        _ok(f"migrated db_id={c['db_id']} → pid={pid} '{c['description'][:40]}'")
    plog._persist()

    # 3. 标 SQLite nudged=1 (避免 CW daemon 重复 fire)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for db_id, pid in migrated_pids:
            cur.execute(
                'UPDATE Commitments SET nudged=1 WHERE id=?',
                (db_id,)
            )
        conn.commit()
        conn.close()
        _ok(f'marked {len(migrated_pids)} SQLite rows nudged=1')
    except Exception as e:
        _err(f'SQLite update failed (但 PromiseLog 已写): {e}')
        _warn(f'手动回滚: 删 PromiseLog 新加 {len(migrated_pids)} 条 + restore SQLite')
        return False

    # 4. verify
    new_plog = json.load(open(PLOG_PATH, 'r', encoding='utf-8'))
    expected = plan['plog_size_before'] + len(plan['to_migrate'])
    if len(new_plog) != expected:
        _warn(f'verify: expected {expected}, got {len(new_plog)}')
    else:
        _ok(f'verify: PromiseLog now has {len(new_plog)} entries (was '
            f'{plan["plog_size_before"]}, +{len(plan["to_migrate"])})')

    _info(f'\nbackup dir: {backup_dir}')
    _info(f'rollback: Copy-Item {backup_dir}\\jarvis_memory.db memory_pool\\; '
          f'Copy-Item {backup_dir}\\jarvis_promise_log.json memory_pool\\')
    return True


def rollback(timestamp: str) -> bool:
    """restore from backup."""
    backup_dir = os.path.join(BACKUP_BASE, timestamp)
    if not os.path.isdir(backup_dir):
        _err(f'backup dir 不存在: {backup_dir}')
        return False
    db_bak = os.path.join(backup_dir, 'jarvis_memory.db')
    plog_bak = os.path.join(backup_dir, 'jarvis_promise_log.json')
    if os.path.exists(db_bak):
        shutil.copy2(db_bak, DB_PATH)
        _ok(f'restored jarvis_memory.db from {db_bak}')
    if os.path.exists(plog_bak):
        shutil.copy2(plog_bak, PLOG_PATH)
        _ok(f'restored jarvis_promise_log.json from {plog_bak}')
    return True


def main():
    ap = argparse.ArgumentParser(description='M4.4 Commitments → PromiseLog migration')
    ap.add_argument('--apply', action='store_true',
                     help='真执行 migration (默认 dry-run)')
    ap.add_argument('--rollback', metavar='TIMESTAMP',
                     help='回滚到指定 backup (e.g. 20260524_082500)')
    args = ap.parse_args()

    if args.rollback:
        return 0 if rollback(args.rollback) else 1

    plan = plan_migration()
    print_plan(plan)

    if not args.apply:
        print(f"\n{YELLOW}[dry-run]{RESET} 跑 --apply 真执行")
        return 0

    print(f"\n{BOLD}{GREEN}═══ APPLY MODE ═══{RESET}")
    ok = apply_migration(plan)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
