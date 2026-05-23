#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35 / 2026-05-23 BUG#10] PreFlight edit diff dump.

Sir 真痛点: PreFlight 编辑了主脑回复, Sir 看到 edit 后 — 但 trace "为什么改"
看不到原文 vs edited 的 diff. 之前 preflight_stats.jsonl 只记 length.

修后 (P5-fix35) 加了 draft_excerpt + edited_excerpt. 本工具读 jsonl 展示.

用法:
  python scripts/preflight_diff_dump.py                # 最近 10 条 edit/scrap
  python scripts/preflight_diff_dump.py --all          # 全展示包括 pass
  python scripts/preflight_diff_dump.py --within 3600  # 最近 1h
  python scripts/preflight_diff_dump.py -n 20          # 取 20 条
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS_PATH = os.path.join(ROOT, 'memory_pool', 'preflight_stats.jsonl')


def _load(path: str) -> list:
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
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        print(f"[preflight_diff_dump] read error: {e}", file=sys.stderr)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-n', '--count', type=int, default=10,
                     help='show last N records (default 10)')
    p.add_argument('--all', action='store_true',
                     help='show pass verdicts too (default: only edit/scrap)')
    p.add_argument('--within', type=float, default=None,
                     help='only within N seconds')
    p.add_argument('--verdict', choices=['pass', 'edit', 'scrap'],
                     help='filter to a specific verdict')
    args = p.parse_args()

    rows = _load(STATS_PATH)
    if not rows:
        print(f"[preflight_diff_dump] no records at {STATS_PATH}")
        return 0

    # filter
    now = time.time()
    out = []
    for r in rows:
        if args.within is not None and r.get('ts', 0) < now - args.within:
            continue
        v = r.get('verdict', '')
        if args.verdict and v != args.verdict:
            continue
        if not args.all and v not in ('edit', 'scrap'):
            continue
        out.append(r)

    out = out[-args.count:]

    if not out:
        print(f"(no matching records — try --all or --within larger)")
        return 0

    print(f"{'='*78}")
    print(f"  PreFlight Diff Audit ({len(out)} records)")
    print(f"{'='*78}")
    for r in out:
        verdict = r.get('verdict', '?')
        emoji = {'pass': '✅', 'edit': '✏️', 'scrap': '🗑️'}.get(verdict, '?')
        iso = r.get('iso', '')[-8:] if r.get('iso') else '?'
        latency = r.get('latency_ms', 0)
        issues = r.get('issues', [])
        sir_utt = r.get('sir_utterance_excerpt', '')
        draft = r.get('draft_excerpt', '')
        edited = r.get('edited_excerpt', '')
        scrap_reason = r.get('scrap_reason', '')
        print(f"\n{emoji} [{iso}] verdict={verdict}  latency={latency}ms")
        print(f"  Sir said: {sir_utt[:120]}")
        if issues:
            print(f"  Issues:")
            for iss in issues:
                print(f"    - {iss[:200]}")
        if draft:
            print(f"  📝 Main brain draft (first 300 char):")
            print(f"     {draft[:300].replace(chr(10), ' ')}")
        if verdict == 'edit' and edited:
            print(f"  ✏️ PreFlight edited (first 300 char):")
            print(f"     {edited[:300].replace(chr(10), ' ')}")
        if verdict == 'scrap' and scrap_reason:
            print(f"  🗑️ Scrap reason: {scrap_reason}")
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
