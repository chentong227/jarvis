#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix34 / 2026-05-23] Model A/B audit — agent-run weekly report.

设计思路 (Sir 真要求):
  - Sir 只判体感, 不做数据对比
  - Cascade (我) 跑这个脚本, 给 Sir 周报
  - 数据源: memory_pool/mutation_receipts.jsonl (含 model 标签)
  - 按 model 分组对比: receipt 数 / 成功率 / 失败原因 / source 分布

用法:
  python scripts/model_compare_audit.py                    # 默认 7 天 + 全 model
  python scripts/model_compare_audit.py --days 14
  python scripts/model_compare_audit.py --since 2026-05-23
  python scripts/model_compare_audit.py --model deepseek/deepseek-v4-pro
  python scripts/model_compare_audit.py --report report.md  # 写 markdown 周报

输出:
  - 终端表格 (model x metric)
  - 可选 markdown 周报文件 (Sir 看)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIPT_PATH = os.path.join(ROOT, 'memory_pool', 'mutation_receipts.jsonl')


def _load_receipts(path: str) -> list:
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
        print(f"[model_compare_audit] read error: {e}", file=sys.stderr)
    return out


def _filter(rows: list, since_ts: Optional[float] = None,
              model_filter: Optional[str] = None) -> list:
    out = []
    for r in rows:
        if since_ts is not None and r.get('ts', 0) < since_ts:
            continue
        if model_filter and r.get('model', '') != model_filter:
            continue
        out.append(r)
    return out


def _summarize_by_model(rows: list) -> dict:
    """按 model 分组. 返回 {model: stats}."""
    groups = defaultdict(list)
    for r in rows:
        # normalize: missing key, None, '' 都归一到 <unknown>
        m = r.get('model') or '<unknown>'
        groups[m].append(r)

    summaries = {}
    for model, items in groups.items():
        n = len(items)
        n_ok = sum(1 for r in items if r.get('ok'))
        n_fail = n - n_ok
        success_rate = (n_ok / n) if n > 0 else 0.0
        layers = Counter(r.get('layer_targeted', '?') for r in items)
        sources = Counter(r.get('source', '?').split(':')[0] for r in items)
        # source 头 (e.g. fast_call_mutation:refine → fast_call_mutation)
        commands = Counter()
        for r in items:
            src = r.get('source', '')
            parts = src.split(':')
            if len(parts) >= 2:
                commands[parts[1]] += 1
        # fail reasons (前 3)
        fail_reasons = Counter()
        for r in items:
            if not r.get('ok'):
                err = (r.get('error', '') or '<no error>')[:80]
                fail_reasons[err] += 1
        # 时间跨度
        ts_values = [r.get('ts', 0) for r in items if r.get('ts')]
        if ts_values:
            time_span_h = (max(ts_values) - min(ts_values)) / 3600.0
            first_iso = time.strftime('%Y-%m-%d %H:%M', time.localtime(min(ts_values)))
            last_iso = time.strftime('%Y-%m-%d %H:%M', time.localtime(max(ts_values)))
        else:
            time_span_h = 0.0
            first_iso = ''
            last_iso = ''
        summaries[model] = {
            'n': n,
            'n_ok': n_ok,
            'n_fail': n_fail,
            'success_rate': success_rate,
            'time_span_h': time_span_h,
            'first_iso': first_iso,
            'last_iso': last_iso,
            'layers': dict(layers.most_common()),
            'sources': dict(sources.most_common()),
            'commands': dict(commands.most_common()),
            'fail_reasons': dict(fail_reasons.most_common(3)),
            'rate_per_hour': (n / time_span_h) if time_span_h > 0 else 0.0,
        }
    return summaries


def _print_terminal(summaries: dict, since_iso: str):
    print("=" * 78)
    print(f"📊 [model_compare_audit] mutation receipts since {since_iso}")
    print("=" * 78)
    if not summaries:
        print("  (no receipts in window)")
        return

    # 排序: receipt 数最多的在前
    ordered = sorted(summaries.items(), key=lambda kv: -kv[1]['n'])

    print(f"\n{'Model':<45} {'Total':>6} {'OK':>5} {'Fail':>5} {'Rate':>7} {'Span':>7}")
    print("-" * 78)
    for model, s in ordered:
        m_disp = (model or '<unknown>')[:44]
        print(f"{m_disp:<45} "
              f"{s['n']:>6} {s['n_ok']:>5} {s['n_fail']:>5} "
              f"{s['success_rate']*100:>6.1f}% "
              f"{s['time_span_h']:>6.1f}h")
    print()

    # 详细每个 model
    for model, s in ordered:
        m_disp = model or '<unknown>'
        print(f"\n--- {m_disp} ---")
        print(f"  Time:    {s['first_iso']} → {s['last_iso']} ({s['time_span_h']:.1f}h)")
        print(f"  Rate:    {s['rate_per_hour']:.2f} receipts/hour")
        if s['layers']:
            top_layers = ', '.join(f"{k}={v}" for k, v in list(s['layers'].items())[:4])
            print(f"  Layers:  {top_layers}")
        if s['sources']:
            top_srcs = ', '.join(f"{k}={v}" for k, v in list(s['sources'].items())[:3])
            print(f"  Sources: {top_srcs}")
        if s['commands']:
            top_cmds = ', '.join(f"{k}={v}" for k, v in list(s['commands'].items())[:5])
            print(f"  Cmds:    {top_cmds}")
        if s['fail_reasons']:
            print(f"  Fail reasons (top 3):")
            for err, cnt in s['fail_reasons'].items():
                print(f"    [{cnt}x] {err}")


def _write_markdown_report(summaries: dict, since_iso: str,
                              out_path: str) -> None:
    lines = []
    lines.append(f"# Model A/B Audit Report")
    lines.append(f"")
    lines.append(f"**Window**: since {since_iso}")
    lines.append(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"")
    lines.append(f"## Summary")
    lines.append(f"")
    if not summaries:
        lines.append(f"_No receipts in window._")
    else:
        lines.append(f"| Model | Receipts | OK | Fail | Success% | Span (h) | Rate (/h) |")
        lines.append(f"|---|---|---|---|---|---|---|")
        ordered = sorted(summaries.items(), key=lambda kv: -kv[1]['n'])
        for model, s in ordered:
            m_disp = model or '<unknown>'
            lines.append(
                f"| `{m_disp}` | {s['n']} | {s['n_ok']} | {s['n_fail']} | "
                f"{s['success_rate']*100:.1f}% | {s['time_span_h']:.1f} | "
                f"{s['rate_per_hour']:.2f} |"
            )

        lines.append(f"")
        lines.append(f"## Detail per model")
        for model, s in ordered:
            m_disp = model or '<unknown>'
            lines.append(f"")
            lines.append(f"### `{m_disp}`")
            lines.append(f"")
            lines.append(f"- **Time window**: {s['first_iso']} → {s['last_iso']}")
            lines.append(f"- **Total mutations**: {s['n']} ({s['n_ok']} ok / {s['n_fail']} fail)")
            lines.append(f"- **Success rate**: {s['success_rate']*100:.1f}%")
            lines.append(f"- **Rate**: {s['rate_per_hour']:.2f} receipts/hour")
            if s['layers']:
                lines.append(f"- **Layer distribution**:")
                for k, v in s['layers'].items():
                    lines.append(f"  - `{k}`: {v}")
            if s['commands']:
                lines.append(f"- **Mutation commands**:")
                for k, v in s['commands'].items():
                    lines.append(f"  - `{k}`: {v}")
            if s['fail_reasons']:
                lines.append(f"- **Fail reasons** (top 3):")
                for err, cnt in s['fail_reasons'].items():
                    lines.append(f"  - `[{cnt}x]` {err}")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"_Generated by `scripts/model_compare_audit.py` "
                  f"(reads `memory_pool/mutation_receipts.jsonl`)._")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"\n📄 Markdown report written to: {out_path}")


def main():
    p = argparse.ArgumentParser(description='Model A/B audit (Cascade weekly tool)')
    p.add_argument('--days', type=float, default=7.0,
                     help='look back N days (default 7, use 0.04 for 1 hour)')
    p.add_argument('--since', type=str, default=None,
                     help='ISO date YYYY-MM-DD (overrides --days)')
    p.add_argument('--model', type=str, default=None,
                     help='filter to specific model only')
    p.add_argument('--report', type=str, default=None,
                     help='write markdown report to this path')
    p.add_argument('--receipt', type=str, default=RECEIPT_PATH,
                     help=f'mutation receipts path (default {RECEIPT_PATH})')
    args = p.parse_args()

    # determine since_ts
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, '%Y-%m-%d')
        except ValueError:
            try:
                since_dt = datetime.strptime(args.since, '%Y-%m-%dT%H:%M')
            except ValueError:
                print(f"[error] invalid --since format: {args.since}", file=sys.stderr)
                return 1
        since_ts = since_dt.timestamp()
        since_iso = since_dt.strftime('%Y-%m-%d %H:%M')
    else:
        since_ts = time.time() - args.days * 86400
        since_iso = time.strftime('%Y-%m-%d %H:%M', time.localtime(since_ts))

    rows = _load_receipts(args.receipt)
    if not rows:
        print(f"[model_compare_audit] no receipts found at {args.receipt}")
        return 0

    rows = _filter(rows, since_ts=since_ts, model_filter=args.model)
    summaries = _summarize_by_model(rows)
    _print_terminal(summaries, since_iso)

    if args.report:
        _write_markdown_report(summaries, since_iso, args.report)

    return 0


if __name__ == '__main__':
    sys.exit(main())
