#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
[β.2.9.7 / 2026-05-18] promise_log_reset.py — Jarvis 承诺账本一键清/裁

Sir 09:06 实测痛点: InconsistencyWatcher 一直提醒之前的事情. 根因之一是
prod memory_pool/jarvis_promise_log.json 累积老 promise (含测试残留 +
跨 session 老的 hard promise 13:05 类). 清掉就不再被反复 fire.

用法:
  python scripts/promise_log_reset.py                    # 默认: 干跑, 仅打印将清掉哪些
  python scripts/promise_log_reset.py --apply            # 真清 (全清 + 重写为空)
  python scripts/promise_log_reset.py --keep-fulfilled   # 只清 pending, 保留已 fulfilled 历史
  python scripts/promise_log_reset.py --older-than 7d    # 只清 7d 前的
  python scripts/promise_log_reset.py --backup           # apply 前先备份
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
import time

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                       errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'jarvis_promise_log.json')


def _parse_age(s: str) -> float:
    if not s:
        return 0.0
    m = re.match(r'^(\d+)\s*([smhd])$', s.strip().lower())
    if not m:
        raise ValueError(f"bad --older-than format: {s!r} (use e.g. 30m / 2h / 7d)")
    n, unit = int(m.group(1)), m.group(2)
    return n * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true',
                    help='真清; 默认仅 dry-run 打印将清掉哪些')
    ap.add_argument('--keep-fulfilled', action='store_true',
                    help='保留 fulfilled / cancelled / untracked 历史')
    ap.add_argument('--older-than', default='',
                    help='只清创建时间早于此 (e.g. 30m / 2h / 7d)')
    ap.add_argument('--backup', action='store_true',
                    help='apply 前备份当前 json 到 .bak.YYYYmmdd_HHMMSS')
    ap.add_argument('--path', default=DEFAULT_PATH,
                    help=f'jarvis_promise_log.json 路径 (默认 {DEFAULT_PATH})')
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"❌ 不存在: {args.path}")
        return 1

    with open(args.path, 'r', encoding='utf-8') as f:
        data = json.load(f) or {}

    if not data:
        print(f"✅ 已是空: {args.path}")
        return 0

    cutoff_age = _parse_age(args.older_than)
    now = time.time()

    def _should_drop(p: dict) -> bool:
        if cutoff_age > 0:
            age = now - float(p.get('registered_at', 0) or 0)
            if age < cutoff_age:
                return False
        if args.keep_fulfilled:
            return p.get('state', 'pending') == 'pending'
        return True

    keep = {pid: p for pid, p in data.items() if not _should_drop(p)}
    drop = {pid: p for pid, p in data.items() if _should_drop(p)}

    print(f"📋 {args.path}")
    print(f"   total:     {len(data)}")
    print(f"   will drop: {len(drop)}")
    print(f"   will keep: {len(keep)}")
    if drop:
        print(f"\n要清掉的前 10 条样本:")
        for i, (pid, p) in enumerate(list(drop.items())[:10]):
            age_h = (now - float(p.get('registered_at', 0) or 0)) / 3600.0
            print(f"   {i+1}. {pid} [{p.get('state', '?'):10s}] "
                  f"age={age_h:6.1f}h kind={p.get('kind', '?'):5s} "
                  f"'{(p.get('description', '') or '')[:60]}'")

    if not args.apply:
        print(f"\n(dry-run, 加 --apply 真清)")
        return 0

    if args.backup:
        ts = time.strftime('%Y%m%d_%H%M%S')
        bak = f"{args.path}.bak.{ts}"
        shutil.copy2(args.path, bak)
        print(f"📦 backup: {bak}")

    with open(args.path, 'w', encoding='utf-8') as f:
        json.dump(keep, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"✅ 已写回 {args.path} (剩 {len(keep)})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
