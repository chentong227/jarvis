# -*- coding: utf-8 -*-
"""[Reshape M1.2 / 2026-05-24] swm_history CLI dump.

看 memory_pool/swm_history.jsonl — high-salience event 持久化 (salience >= 0.85).

用法:
  python scripts/swm_history_dump.py                # 列最近 30 条
  python scripts/swm_history_dump.py --tail 100     # 最近 100 条
  python scripts/swm_history_dump.py --type intent_resolved   # 过滤 type
  python scripts/swm_history_dump.py --since 1h     # 1h 内
  python scripts/swm_history_dump.py --json         # 机读
  python scripts/swm_history_dump.py --stats        # type 分布
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'swm_history.jsonl')


def _parse_since(s: str) -> float:
    """parse '1h' / '30m' / '2d' → seconds ago, return cutoff timestamp."""
    if not s:
        return 0.0
    m = re.match(r'^(\d+)([smhd])$', s.strip().lower())
    if not m:
        return 0.0
    n, unit = int(m.group(1)), m.group(2)
    mul = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]
    return time.time() - n * mul


def _read_records(path: str, type_filter: str = '',
                   since_cutoff: float = 0.0, tail: int = 0) -> list:
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if type_filter and rec.get('type', '') != type_filter:
                    continue
                if since_cutoff > 0 and float(rec.get('timestamp', 0)) < since_cutoff:
                    continue
                out.append(rec)
    except Exception:
        pass
    if tail > 0:
        out = out[-tail:]
    return out


def _print_records(records: list):
    if not records:
        print('📭 (空)')
        return
    print('=' * 78)
    print(f'  SWM History (高 salience event, {len(records)} 条)')
    print('=' * 78)
    for rec in records:
        ts = rec.get('timestamp', 0)
        iso = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else '?'
        etype = rec.get('type', '?')
        sal = rec.get('salience', 0)
        src = rec.get('source', '?')
        desc = (rec.get('description') or '')[:100]
        evid = (rec.get('evidence_id') or '')[:16]
        print(f"\n  ⏰ {iso}  [{etype}]  salience={sal:.2f}  src={src}  evid={evid}")
        print(f"     {desc}")


def _print_stats(records: list):
    if not records:
        print('📭 (空)')
        return
    type_count = {}
    src_count = {}
    sal_sum = 0.0
    for rec in records:
        t = rec.get('type', '?')
        type_count[t] = type_count.get(t, 0) + 1
        s = rec.get('source', '?')
        src_count[s] = src_count.get(s, 0) + 1
        sal_sum += float(rec.get('salience', 0))
    print('=' * 78)
    print(f'  SWM History Stats ({len(records)} 条)')
    print('=' * 78)
    print(f'\n  Mean salience: {sal_sum / len(records):.3f}')
    print(f'\n  By type:')
    for t, c in sorted(type_count.items(), key=lambda x: x[1], reverse=True):
        print(f'    {t:<35} ×{c}')
    print(f'\n  By source:')
    for s, c in sorted(src_count.items(), key=lambda x: x[1], reverse=True):
        print(f'    {s:<35} ×{c}')


def main() -> int:
    p = argparse.ArgumentParser(description='SWM history CLI')
    p.add_argument('--path', default=DEFAULT_PATH)
    p.add_argument('--type', dest='type_filter', default='', help='过滤 event type')
    p.add_argument('--since', default='', help='时间窗 (1h / 30m / 2d)')
    p.add_argument('--tail', type=int, default=30, help='最近 N 条 (default 30)')
    p.add_argument('--json', action='store_true', help='机读')
    p.add_argument('--stats', action='store_true', help='type/source 分布')
    args = p.parse_args()

    since_cutoff = _parse_since(args.since)
    records = _read_records(args.path, args.type_filter, since_cutoff, args.tail)

    if args.stats:
        _print_stats(records)
        return 0
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    _print_records(records)
    return 0


if __name__ == '__main__':
    sys.exit(main())
