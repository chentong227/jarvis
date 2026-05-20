# -*- coding: utf-8 -*-
"""[β.5.39 / 2026-05-20] Sir Sleep Pattern CLI.

管理 memory_pool/sir_sleep_pattern_vocab.json — Sir 个人入睡时间习惯, 准则 6.

用法:
  python scripts/sleep_pattern_dump.py --show
  python scripts/sleep_pattern_dump.py --history
  python scripts/sleep_pattern_dump.py --set-weekday 24.0
  python scripts/sleep_pattern_dump.py --set-weekend 25.5
  python scripts/sleep_pattern_dump.py --history-add 2026-05-20 23.5 weekday
  python scripts/sleep_pattern_dump.py --recompute  # 用 history 中位数重算
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from statistics import median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, 'memory_pool', 'sir_sleep_pattern_vocab.json')


def _load(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def cmd_show(data):
    typ = data.get('typical_sleep_hour', {})
    print(f"weekday typical sleep hour: {typ.get('weekday')}")
    print(f"weekend typical sleep hour: {typ.get('weekend')}")
    print(f"tolerance: ±{typ.get('tolerance_hours', 1.0)}h")
    print(f"data_points_used: {typ.get('data_points_used', 0)} (min={data['_meta'].get('min_data_points', 5)})")
    last_ts = typ.get('last_computed_ts', 0)
    if last_ts:
        print(f"last_computed: {time.strftime('%Y-%m-%d %H:%M', time.localtime(last_ts))}")
    print(f"history entries: {len(data.get('history', []))}")


def cmd_history(data, limit=20):
    history = data.get('history', [])
    print(f"Total {len(history)} entries (last {limit}):")
    for h in history[-limit:]:
        wd = 'weekday' if h.get('weekday') else 'weekend'
        print(f"  {h.get('date')} @ {h.get('sleep_hour')}h ({wd}) src={h.get('source', '?')}")


def cmd_set(data, kind, value):
    if kind not in ('weekday', 'weekend'):
        print(f"ERR: kind must be weekday/weekend, got {kind}")
        return False
    try:
        v = float(value)
    except ValueError:
        print(f"ERR: value must be float, got {value}")
        return False
    if not (18.0 <= v <= 30.0):
        print(f"ERR: sleep_hour 应在 18.0-30.0 (跨午夜算 24+) 之间, 实际 {v}")
        return False
    typ = data.setdefault('typical_sleep_hour', {})
    typ[kind] = v
    typ['last_computed_ts'] = time.time()
    typ['source'] = 'manual (Sir CLI)'
    print(f"OK: typical_sleep_hour.{kind} = {v}")
    return True


def cmd_history_add(data, date_str, sleep_hour_str, weekday_str):
    try:
        sleep_hour = float(sleep_hour_str)
    except ValueError:
        print(f"ERR: sleep_hour must be float")
        return False
    weekday = 1 if weekday_str.lower() in ('weekday', '1', 'true') else 0
    entry = {
        'date': date_str,
        'sleep_ts': time.time(),
        'sleep_hour': sleep_hour,
        'weekday': weekday,
        'source': 'manual_cli',
    }
    data.setdefault('history', []).append(entry)
    print(f"OK: added entry {entry}")
    return True


def cmd_recompute(data):
    history = data.get('history', [])
    min_pts = data['_meta'].get('min_data_points', 5)
    weekday_hours = [h['sleep_hour'] for h in history if h.get('weekday') == 1]
    weekend_hours = [h['sleep_hour'] for h in history if h.get('weekday') == 0]
    typ = data.setdefault('typical_sleep_hour', {})
    updated = False
    if len(weekday_hours) >= min_pts:
        typ['weekday'] = round(median(weekday_hours), 2)
        updated = True
        print(f"weekday: {len(weekday_hours)} samples → median {typ['weekday']}h")
    else:
        print(f"weekday: 仅 {len(weekday_hours)} 数据点 (need {min_pts})")
    if len(weekend_hours) >= min_pts:
        typ['weekend'] = round(median(weekend_hours), 2)
        updated = True
        print(f"weekend: {len(weekend_hours)} samples → median {typ['weekend']}h")
    else:
        print(f"weekend: 仅 {len(weekend_hours)} 数据点 (need {min_pts})")
    if updated:
        typ['last_computed_ts'] = time.time()
        typ['data_points_used'] = len(weekday_hours) + len(weekend_hours)
        typ['source'] = 'recompute_cli'
    return updated


def main():
    ap = argparse.ArgumentParser(description='Sir Sleep Pattern vocab CLI (β.5.39)')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--history', action='store_true')
    ap.add_argument('--set-weekday', metavar='HOUR', help='set weekday typical_sleep_hour')
    ap.add_argument('--set-weekend', metavar='HOUR', help='set weekend typical_sleep_hour')
    ap.add_argument('--history-add', nargs=3, metavar=('DATE', 'HOUR', 'WEEKDAY'),
                    help='add history entry: DATE (YYYY-MM-DD) HOUR (float) WEEKDAY (weekday/weekend)')
    ap.add_argument('--recompute', action='store_true',
                    help='recompute typical_sleep_hour from history median')
    ap.add_argument('--path', default=DEFAULT_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"ERR: {args.path} not exist")
        sys.exit(1)
    data = _load(args.path)

    changed = False
    if args.set_weekday:
        changed = cmd_set(data, 'weekday', args.set_weekday) or changed
    if args.set_weekend:
        changed = cmd_set(data, 'weekend', args.set_weekend) or changed
    if args.history_add:
        changed = cmd_history_add(data, *args.history_add) or changed
    if args.recompute:
        changed = cmd_recompute(data) or changed
    if changed:
        _save(args.path, data)
        print(f"\n→ saved to {args.path}")

    if args.show or not (args.set_weekday or args.set_weekend or args.history_add or args.recompute or args.history):
        cmd_show(data)
    if args.history:
        cmd_history(data)


if __name__ == '__main__':
    main()
