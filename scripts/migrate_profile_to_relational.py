# -*- coding: utf-8 -*-
"""[P0+20-β.2.4.2 / 2026-05-16] 把 sir_profile 的"关系类"字段迁到 relational_state。

详 docs/JARVIS_SOUL_DRIVE.md。

背景：Sir 22:54 实测 Layer 2 后审计发现 sir_profile 也记录了 our_inside_jokes
和 significant_milestones，会和 Layer 2 RelationalState 双注入 prompt。方案 A
（老路径退役）的第 2 步：一次性把现有数据从 sir_profile 迁入 relational_state。

迁移规则：
- sir_profile.our_inside_jokes (list[str]) → InsideJoke[]
    * phrase: 整条 string（最多 80 字）
    * birth_context: 'migrated from sir_profile.our_inside_jokes'
    * tone: '' (旧数据没调性信息)
    * source: 'migrated_from_profile'
- sir_profile.significant_milestones (list[str]) → SharedHistoryThread[]
    * title: 整条 string
    * highlights: 单条 [{when, what: <title>}]
    * source: 'migrated_from_profile'

默认 dry-run，只报告会做什么。Sir 确认后用 --apply 真写。
--delete-from-profile 在 --apply 之后从 sir_profile 删掉迁过的字段（破坏性，
谨慎；自动备份 sir_profile.json.bak.<ts>）。

用法：
    python scripts/migrate_profile_to_relational.py                       # dry-run
    python scripts/migrate_profile_to_relational.py --apply               # 真写 relational
    python scripts/migrate_profile_to_relational.py --apply --delete-from-profile
                                                                          # 写完从 profile 删字段
    python scripts/migrate_profile_to_relational.py --profile-path X.json # 测试覆盖
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_relational import (
    RelationalStateStore,
    InsideJoke,
    SharedHistoryThread,
    make_joke_id,
    make_thread_id,
)


DEFAULT_PROFILE_PATH = os.path.join('jarvis_config', 'sir_profile.json')
DEFAULT_RELATIONAL_PATH = os.path.join('memory_pool', 'relational_state.json')
MARKER = 'P0+20-β.2.4.2'


def _load_profile(path: str) -> dict:
    if not os.path.exists(path):
        print(f"[ERROR] sir_profile not found: {path}")
        sys.exit(2)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f) or {}


def _save_profile(path: str, data: dict) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _backup_profile(path: str) -> str:
    ts = time.strftime('%Y%m%d_%H%M%S')
    bak = f"{path}.bak.{ts}"
    shutil.copy2(path, bak)
    return bak


def _plan_migration(profile: dict, store: RelationalStateStore) -> dict:
    """看会产生哪些新条目 + 哪些条目已存在不重复注入。"""
    plan = {
        'jokes_to_add': [],
        'jokes_skipped_duplicate': [],
        'threads_to_add': [],
        'threads_skipped_duplicate': [],
    }
    for j_str in (profile.get('our_inside_jokes') or []):
        s = str(j_str).strip()
        if not s:
            continue
        jid = make_joke_id(s)
        if store.get_inside_joke(jid) is not None:
            plan['jokes_skipped_duplicate'].append(jid)
        else:
            plan['jokes_to_add'].append((jid, s))

    for m_str in (profile.get('significant_milestones') or []):
        s = str(m_str).strip()
        if not s:
            continue
        tid = make_thread_id(s)
        if store.get_thread(tid) is not None:
            plan['threads_skipped_duplicate'].append(tid)
        else:
            plan['threads_to_add'].append((tid, s))
    return plan


def _print_plan(plan: dict, dry_run: bool) -> None:
    mode = "DRY-RUN (no writes)" if dry_run else "APPLY (writes will happen)"
    print("=" * 80)
    print(f"[migrate] mode={mode}")
    print(f"  jokes to add        : {len(plan['jokes_to_add'])}")
    for jid, phrase in plan['jokes_to_add'][:10]:
        print(f"    + {jid}: \"{phrase[:80]}\"")
    if len(plan['jokes_to_add']) > 10:
        print(f"    ... and {len(plan['jokes_to_add']) - 10} more")
    print(f"  jokes skipped (dup) : {len(plan['jokes_skipped_duplicate'])}")
    for jid in plan['jokes_skipped_duplicate'][:5]:
        print(f"    = {jid}")
    print(f"  threads to add      : {len(plan['threads_to_add'])}")
    for tid, title in plan['threads_to_add'][:10]:
        print(f"    + {tid}: \"{title[:80]}\"")
    if len(plan['threads_to_add']) > 10:
        print(f"    ... and {len(plan['threads_to_add']) - 10} more")
    print(f"  threads skipped (dup): {len(plan['threads_skipped_duplicate'])}")
    for tid in plan['threads_skipped_duplicate'][:5]:
        print(f"    = {tid}")
    print("=" * 80)


def _apply_migration(plan: dict, store: RelationalStateStore) -> dict:
    """真写。返回统计。"""
    now = time.time()
    stats = {'jokes_added': 0, 'threads_added': 0}

    for jid, phrase in plan['jokes_to_add']:
        joke = InsideJoke(
            id=jid,
            phrase=phrase[:120],
            birth_context='migrated from sir_profile.our_inside_jokes',
            tone='',
            source='migrated_from_profile',
            source_marker=MARKER,
        )
        if store.add_inside_joke(joke):
            stats['jokes_added'] += 1

    for tid, title in plan['threads_to_add']:
        thread = SharedHistoryThread(
            id=tid,
            title=title[:120],
            detail='migrated from sir_profile.significant_milestones',
            source='migrated_from_profile',
            source_marker=MARKER,
        )
        thread.add_highlight(title)
        if store.add_thread(thread):
            stats['threads_added'] += 1

    store._dirty = True
    store.persist()
    return stats


def _delete_from_profile(path: str, profile: dict) -> str:
    """从 sir_profile 删 our_inside_jokes 和 significant_milestones 字段。
    返回备份路径。"""
    bak = _backup_profile(path)
    profile.pop('our_inside_jokes', None)
    profile.pop('significant_milestones', None)
    _save_profile(path, profile)
    return bak


def main():
    parser = argparse.ArgumentParser(
        description='Migrate sir_profile.our_inside_jokes + significant_milestones → relational_state.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--profile-path', default=DEFAULT_PROFILE_PATH,
                        help='sir_profile.json 路径 (default jarvis_config/sir_profile.json)')
    parser.add_argument('--relational-path', default=DEFAULT_RELATIONAL_PATH,
                        help='relational_state.json 路径')
    parser.add_argument('--apply', action='store_true',
                        help='真写 relational_state（默认 dry-run）')
    parser.add_argument('--delete-from-profile', action='store_true',
                        help='--apply 后从 sir_profile 删 our_inside_jokes/significant_milestones '
                             '字段。会先备份 sir_profile.json.bak.<ts>')
    args = parser.parse_args()

    profile = _load_profile(args.profile_path)
    store = RelationalStateStore(persist_path=args.relational_path)
    store.load()

    plan = _plan_migration(profile, store)
    _print_plan(plan, dry_run=not args.apply)

    if not args.apply:
        n_total = len(plan['jokes_to_add']) + len(plan['threads_to_add'])
        if n_total == 0:
            print("[migrate] nothing to migrate (profile 无 our_inside_jokes / significant_milestones)")
        else:
            print(f"[migrate] DRY-RUN done. Re-run with --apply to actually write {n_total} items.")
        return 0

    stats = _apply_migration(plan, store)
    print()
    print("=" * 80)
    print(f"[migrate] APPLIED to {args.relational_path}")
    print(f"  jokes_added         = {stats['jokes_added']}")
    print(f"  threads_added       = {stats['threads_added']}")
    print("=" * 80)

    if args.delete_from_profile:
        if (plan['jokes_to_add'] or plan['threads_to_add']
                or 'our_inside_jokes' in profile
                or 'significant_milestones' in profile):
            bak = _delete_from_profile(args.profile_path, profile)
            print(f"[migrate] sir_profile 删字段完成，备份: {bak}")
        else:
            print("[migrate] sir_profile 已无需删字段（无相关 key）")

    return 0


if __name__ == '__main__':
    sys.exit(main())
