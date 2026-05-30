#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/self_threads_dump.py — Sir CLI 看/管 河床 (self-threads / 巩固的持久思维线程).

[Self-Memory P2 / Sir 2026-05-30] 准则 6: 数据持久化 memory_pool/self_threads.json
+ CLI 可看/改 (Sir 不需改源码). 线程由思考脑 _consolidate_threads_once 自动巩固生成.

用法:
  python scripts/self_threads_dump.py                  # list (默认, 按 last_touched 排序)
  python scripts/self_threads_dump.py --tier hot       # 只看某 tier (hot/warm/cold)
  python scripts/self_threads_dump.py --show <tid>     # 看一条完整 (含 evidence 回链)
  python scripts/self_threads_dump.py --tiers          # tier 分布统计
  python scripts/self_threads_dump.py --let-go <tid>   # Sir 显式放下 (status=let_go → cold)
  python scripts/self_threads_dump.py --reopen <tid>   # 重开 (status=open)
  python scripts/self_threads_dump.py --json           # raw dump
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'memory_pool', 'self_threads.json')
NOTES_PATH = os.path.join(ROOT, 'memory_pool', 'self_notes.jsonl')


def _load() -> dict:
    if not os.path.exists(PATH):
        return {'_meta': {'schema': 'self_threads'}, 'threads': []}
    try:
        with open(PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {'threads': []}
        data.setdefault('threads', [])
        return data
    except Exception as e:
        print(f"[err] 读 {PATH} 失败: {e}")
        return {'threads': []}


def _save(data: dict) -> None:
    data.setdefault('_meta', {'schema': 'self_threads'})
    data['_meta']['updated_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)


def _fmt_age(ts) -> str:
    a = max(0, int(time.time() - float(ts or 0)))
    if a < 3600:
        return f"{a // 60}m"
    if a < 86400:
        return f"{a // 3600}h"
    return f"{a // 86400}d"


def cmd_list(data: dict, tier_filter: str = '') -> None:
    threads = [t for t in data.get('threads', [])
               if not tier_filter or t.get('tier') == tier_filter]
    threads.sort(key=lambda t: -float(t.get('last_touched_ts', 0) or 0))
    if not threads:
        print("(河床为空或无匹配 — 思考脑周期巩固后才有线程)")
        return
    print(f"{'TIER':6} {'SEEN':>4} {'SAL':>5} {'AGE':>4} {'STATUS':8} SUMMARY")
    print("-" * 78)
    for t in threads:
        sal = float(t.get('salience_decayed', t.get('salience', 0)) or 0)
        print(f"{str(t.get('tier', '?')):6} "
              f"{str(t.get('occurrences', '?')):>4} "
              f"{sal:>5.2f} "
              f"{_fmt_age(t.get('last_touched_ts')):>4} "
              f"{str(t.get('status', 'open')):8} "
              f"{str(t.get('summary', ''))[:74]}")
        print(f"       id={t.get('thread_id', '')}")
    print(f"\n共 {len(threads)} 线程"
          + (f" (tier={tier_filter})" if tier_filter else ""))


def cmd_show(data: dict, tid: str) -> None:
    for t in data.get('threads', []):
        if t.get('thread_id') == tid or t.get('thread_id', '').startswith(tid):
            print(json.dumps(t, ensure_ascii=False, indent=2))
            return
    print(f"(未找到线程: {tid})")


def cmd_tiers(data: dict) -> None:
    from collections import Counter
    c = Counter(t.get('tier', '?') for t in data.get('threads', []))
    s = Counter(t.get('status', 'open') for t in data.get('threads', []))
    print("tier 分布:", dict(c))
    print("status 分布:", dict(s))
    print("总线程数:", len(data.get('threads', [])))


def cmd_notes(limit: int = 30) -> None:
    """看 self-notes (P4 schema-free 自写记忆) 末 N 条."""
    if not os.path.exists(NOTES_PATH):
        print("(无 self-notes — 思考脑 <NOTE> 后才有)")
        return
    rows = []
    try:
        with open(NOTES_PATH, 'r', encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    rows.append(json.loads(ln))
    except Exception as e:
        print(f"[err] 读 notes 失败: {e}")
        return
    for r in rows[-limit:]:
        print(f"  [{r.get('ts_iso', '?')}] {str(r.get('text', ''))[:110]}")
    print(f"\n共 {len(rows)} notes (显末 {min(limit, len(rows))})")


def cmd_set_status(data: dict, tid: str, status: str) -> None:
    for t in data.get('threads', []):
        if t.get('thread_id') == tid or t.get('thread_id', '').startswith(tid):
            old = t.get('status', 'open')
            t['status'] = status
            _save(data)
            print(f"✅ {t.get('thread_id')}: status {old} → {status}")
            return
    print(f"(未找到线程: {tid})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis 河床 (self-threads) CLI")
    ap.add_argument('--show', metavar='TID', help="看一条完整 (含 evidence)")
    ap.add_argument('--tier', metavar='TIER', default='',
                    help="list 时只看某 tier (hot/warm/cold)")
    ap.add_argument('--tiers', action='store_true', help="tier/status 分布统计")
    ap.add_argument('--notes', action='store_true',
                    help="看 self-notes (P4 schema-free 自写记忆)")
    ap.add_argument('--let-go', metavar='TID', help="Sir 显式放下 (status=let_go)")
    ap.add_argument('--reopen', metavar='TID', help="重开线程 (status=open)")
    ap.add_argument('--json', action='store_true', help="raw dump")
    args = ap.parse_args(argv)

    data = _load()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.show:
        cmd_show(data, args.show)
    elif args.tiers:
        cmd_tiers(data)
    elif args.notes:
        cmd_notes()
    elif args.let_go:
        cmd_set_status(data, args.let_go, 'let_go')
    elif args.reopen:
        cmd_set_status(data, args.reopen, 'open')
    else:
        cmd_list(data, tier_filter=args.tier)
    return 0


if __name__ == '__main__':
    sys.exit(main())
