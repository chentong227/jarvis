# -*- coding: utf-8 -*-
"""[Reshape M8.A / 2026-05-24] mem_audit CLI dump.

看 memory_pool/mem_audit.jsonl — 5 audit log 合并源 (mutation_receipts /
profile_corrections / claim_revisions / claim_stats / integrity_audit).

用法:
  python scripts/mem_audit_dump.py                       # 列最近 30 条
  python scripts/mem_audit_dump.py --tail 100            # 最近 100
  python scripts/mem_audit_dump.py --kind mutation       # 过滤 kind
  python scripts/mem_audit_dump.py --source ProfileCard  # 过滤 source
  python scripts/mem_audit_dump.py --since 1h            # 1h 内
  python scripts/mem_audit_dump.py --stats               # 分布
  python scripts/mem_audit_dump.py --json                # 机读
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


def _parse_since(s: str) -> float:
    if not s:
        return 0.0
    m = re.match(r'^(\d+)([smhd])$', s.strip().lower())
    if not m:
        return 0.0
    n, unit = int(m.group(1)), m.group(2)
    mul = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]
    return time.time() - n * mul


def _print_record(rec: dict):
    ts = rec.get('ts', 0)
    iso = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else '?'
    kind = rec.get('kind', '?')
    src = rec.get('source', '?')
    content = rec.get('content', {}) or {}
    summary = (content.get('summary') or
                content.get('field') or
                content.get('description') or '')
    print(f"\n  ⏰ {iso}  [{kind}]  src={src}")
    if summary:
        print(f"     {str(summary)[:100]}")
    # show 1-2 more content fields
    for k in ('old_value', 'new_value', 'field_path', 'confidence',
              'verdict', 'mutation_id'):
        if k in content and content[k]:
            print(f"     {k}: {str(content[k])[:80]}")


def main() -> int:
    p = argparse.ArgumentParser(description='mem_audit CLI')
    p.add_argument('--kind', default='', help='filter kind (mutation/correction/claim/integrity)')
    p.add_argument('--source', default='', help='filter source')
    p.add_argument('--since', default='', help='时间窗 (1h/30m/2d)')
    p.add_argument('--tail', type=int, default=30, help='最近 N 条')
    p.add_argument('--stats', action='store_true', help='分布统计')
    p.add_argument('--json', action='store_true', help='机读')
    args = p.parse_args()

    try:
        from jarvis_mem_audit import read_unified
    except ImportError as e:
        print(f'❌ cannot import jarvis_mem_audit: {e}')
        return 1

    since_cutoff = _parse_since(args.since)
    # read with filters
    kinds_set = {args.kind} if args.kind else None
    records = read_unified(limit=10000, kinds=kinds_set, include_legacy=True)
    if args.source:
        records = [r for r in records if r.get('source', '').startswith(args.source)]
    if since_cutoff > 0:
        records = [r for r in records if float(r.get('ts', 0)) >= since_cutoff]
    records = records[-args.tail:] if args.tail > 0 else records

    if args.stats:
        kind_count = {}
        src_count = {}
        for rec in records:
            k = rec.get('kind', '?')
            kind_count[k] = kind_count.get(k, 0) + 1
            s = rec.get('source', '?')
            src_count[s] = src_count.get(s, 0) + 1
        print('=' * 78)
        print(f'  mem_audit Stats ({len(records)} 条)')
        print('=' * 78)
        print('\n  By kind:')
        for k, c in sorted(kind_count.items(), key=lambda x: x[1], reverse=True):
            print(f'    {k:<25} ×{c}')
        print('\n  By source:')
        for s, c in sorted(src_count.items(), key=lambda x: x[1], reverse=True):
            print(f'    {s:<35} ×{c}')
        return 0

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    if not records:
        print('📭 (空)')
        return 0
    print('=' * 78)
    print(f'  mem_audit (统一 audit log, {len(records)} 条)')
    print('=' * 78)
    for rec in records:
        _print_record(rec)
    return 0


if __name__ == '__main__':
    sys.exit(main())
