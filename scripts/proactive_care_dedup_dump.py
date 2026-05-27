# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 23:00 P12 治本] ProactiveCare publish dedup vocab CLI.

Sir 真痛 (inner_voice 截图刷屏):
  ProactiveCare 60s tick publish `concern_active` / `concern_timing_evidence`
  零 dedup, urgency=1.00 / severity=0.85 数字完全不变, 5min 内 5 次新 event,
  inner_voice dashboard 全 record 看起来像 "daemon 一直在重复想同一件事".

治本 (准则 6 vocab 持久化 + Sir CLI 可改不需 .py):
  publish 前 check key=(etype, concern_id, urgency_bucket, severity_bucket),
  在 window_s 内同 key 跳过 (in-memory). Sir 调 windows / buckets 立刻生效.

用法:
  python scripts/proactive_care_dedup_dump.py list
  python scripts/proactive_care_dedup_dump.py enable concern_active
  python scripts/proactive_care_dedup_dump.py disable concern_active
  python scripts/proactive_care_dedup_dump.py set-window concern_active 600
  python scripts/proactive_care_dedup_dump.py set-window concern_timing_evidence 900
  python scripts/proactive_care_dedup_dump.py set-bucket urgency 1
  python scripts/proactive_care_dedup_dump.py history
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Windows GBK 默认 console encoding 无法打 emoji. 强制 stdout utf-8.
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(
    ROOT, 'memory_pool', 'proactive_care_publish_dedup_vocab.json'
)

VALID_ETYPES = ('concern_active', 'concern_timing_evidence')
VALID_BUCKETS = ('urgency', 'severity', 'hours_until')


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(f"WARN  {path} not found")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _add_history(data: dict, op: str, detail: str) -> None:
    hist = data.get('history') or []
    hist.append({
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'op': op,
        'detail': detail,
        'source': 'sir_cli',
    })
    data['history'] = hist[-100:]


def cmd_list(args):
    data = _load(args.path)
    print("=== ProactiveCare publish dedup vocab ===")
    print(f"path: {args.path}")
    print()
    print("blocks_enabled:")
    for k, v in (data.get('blocks_enabled') or {}).items():
        flag = "ON " if v else "OFF"
        print(f"  [{flag}] {k}")
    print()
    print("windows (sec):")
    for k, v in (data.get('windows') or {}).items():
        mins = float(v) / 60.0
        print(f"  {k}: {v}s ({mins:.1f} min)")
    print()
    print("buckets (decimals for round):")
    for k, v in (data.get('buckets') or {}).items():
        print(f"  {k}: {v}")
    print()
    print("log_throttle:")
    for k, v in (data.get('log_throttle') or {}).items():
        print(f"  {k}: {v}")
    hist = data.get('history') or []
    if hist:
        print()
        print(f"history (last {min(5, len(hist))} of {len(hist)}):")
        for h in hist[-5:]:
            print(f"  {h.get('when', '?')} [{h.get('source', '?')}] "
                  f"{h.get('op', '?')}: {h.get('detail', '')}")


def cmd_enable(args):
    etype = args.etype
    if etype not in VALID_ETYPES:
        print(f"ERR invalid etype '{etype}'. Valid: {VALID_ETYPES}")
        sys.exit(1)
    data = _load(args.path)
    key = f"{etype}_dedup"
    be = data.setdefault('blocks_enabled', {})
    old = be.get(key, False)
    be[key] = True
    _add_history(data, 'enable', f"{key} (was {old})")
    _save(args.path, data)
    print(f"OK enabled {key}")


def cmd_disable(args):
    etype = args.etype
    if etype not in VALID_ETYPES:
        print(f"ERR invalid etype '{etype}'. Valid: {VALID_ETYPES}")
        sys.exit(1)
    data = _load(args.path)
    key = f"{etype}_dedup"
    be = data.setdefault('blocks_enabled', {})
    old = be.get(key, True)
    be[key] = False
    _add_history(data, 'disable', f"{key} (was {old})")
    _save(args.path, data)
    print(f"OK disabled {key} — 注意 publish 将恢复每 tick (不建议长期 disable)")


def cmd_set_window(args):
    etype = args.etype
    if etype not in VALID_ETYPES:
        print(f"ERR invalid etype '{etype}'. Valid: {VALID_ETYPES}")
        sys.exit(1)
    try:
        seconds = float(args.seconds)
    except ValueError:
        print(f"ERR invalid seconds '{args.seconds}' (must be float)")
        sys.exit(1)
    if seconds < 0:
        print(f"ERR seconds must be >= 0")
        sys.exit(1)
    data = _load(args.path)
    key = f"{etype}_window_s"
    wins = data.setdefault('windows', {})
    old = wins.get(key, 0)
    wins[key] = seconds
    _add_history(data, 'set_window', f"{key}: {old} -> {seconds}")
    _save(args.path, data)
    print(f"OK {key} = {seconds}s ({seconds / 60:.1f} min)")


def cmd_set_bucket(args):
    field = args.field
    if field not in VALID_BUCKETS:
        print(f"ERR invalid field '{field}'. Valid: {VALID_BUCKETS}")
        sys.exit(1)
    try:
        decimals = int(args.decimals)
    except ValueError:
        print(f"ERR invalid decimals '{args.decimals}' (must be int)")
        sys.exit(1)
    if decimals < 0 or decimals > 6:
        print(f"ERR decimals must be 0-6")
        sys.exit(1)
    data = _load(args.path)
    key = f"{field}_decimals"
    bks = data.setdefault('buckets', {})
    old = bks.get(key, 0)
    bks[key] = decimals
    _add_history(data, 'set_bucket', f"{key}: {old} -> {decimals}")
    _save(args.path, data)
    print(f"OK {key} = {decimals}")


def cmd_history(args):
    data = _load(args.path)
    hist = data.get('history') or []
    if not hist:
        print("(no history yet)")
        return
    print(f"=== history ({len(hist)} entries) ===")
    for h in hist:
        print(f"  {h.get('when', '?')} [{h.get('source', '?')}] "
              f"{h.get('op', '?')}: {h.get('detail', '')}")


def main():
    parser = argparse.ArgumentParser(
        prog='proactive_care_dedup_dump',
        description='ProactiveCare publish dedup vocab CLI [P12 治本]',
    )
    parser.add_argument('--path', default=DEFAULT_PATH,
                         help=f'vocab file (default: {DEFAULT_PATH})')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='show current vocab')
    p_list.set_defaults(func=cmd_list)

    p_en = sub.add_parser('enable', help='enable dedup for etype')
    p_en.add_argument('etype', choices=VALID_ETYPES)
    p_en.set_defaults(func=cmd_enable)

    p_dis = sub.add_parser('disable', help='disable dedup for etype')
    p_dis.add_argument('etype', choices=VALID_ETYPES)
    p_dis.set_defaults(func=cmd_disable)

    p_sw = sub.add_parser('set-window',
                          help='set dedup window seconds for etype')
    p_sw.add_argument('etype', choices=VALID_ETYPES)
    p_sw.add_argument('seconds', help='window seconds (float)')
    p_sw.set_defaults(func=cmd_set_window)

    p_sb = sub.add_parser('set-bucket',
                          help='set decimals for bucket field')
    p_sb.add_argument('field', choices=VALID_BUCKETS)
    p_sb.add_argument('decimals', help='decimals 0-6 (int)')
    p_sb.set_defaults(func=cmd_set_bucket)

    p_his = sub.add_parser('history', help='show change history')
    p_his.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
