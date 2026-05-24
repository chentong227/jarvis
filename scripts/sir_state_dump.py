# -*- coding: utf-8 -*-
"""[Reshape M8.B / 2026-05-24] sir_state CLI dump.

看 unified sir_state (sir_status.json + stand_down_state.json + sir_acked_state.json
合并 read facade).

用法:
  python scripts/sir_state_dump.py                # 完整 state
  python scripts/sir_state_dump.py --section sleep    # 只看 sleep
  python scripts/sir_state_dump.py --section stand_down
  python scripts/sir_state_dump.py --json         # 机读
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _print_section(title: str, data: dict, indent: int = 2):
    sp = ' ' * indent
    print(f"\n{sp}━━ {title} ━━")
    if not isinstance(data, dict):
        print(f"{sp}  {data}")
        return
    if not data:
        print(f"{sp}  (空)")
        return
    for k, v in data.items():
        if isinstance(v, (dict, list)) and v:
            try:
                vs = json.dumps(v, ensure_ascii=False)[:120]
            except Exception:
                vs = str(v)[:120]
        else:
            vs = str(v)[:120]
        print(f"{sp}  {k:<25} : {vs}")


def main() -> int:
    p = argparse.ArgumentParser(description='sir_state unified CLI')
    p.add_argument('--section', default='',
                     help='只看某 section (sleep / online / focus / mood / stand_down / acked)')
    p.add_argument('--json', action='store_true', help='机读')
    args = p.parse_args()

    try:
        from jarvis_sir_state import read_unified
    except ImportError as e:
        print(f'❌ cannot import jarvis_sir_state: {e}')
        return 1

    state = read_unified()
    if not state:
        print('📭 (空)')
        return 0

    if args.json:
        if args.section and args.section in state:
            print(json.dumps(state[args.section], ensure_ascii=False, indent=2,
                              default=str))
        else:
            print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.section:
        if args.section not in state:
            print(f'❌ section {args.section!r} 不存在. 可选: {list(state.keys())}')
            return 1
        _print_section(args.section, state[args.section], indent=0)
        return 0

    print('=' * 78)
    print('  Sir State (unified, M8.B facade)')
    print('=' * 78)
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f'  read at: {now}')
    # 按典型 section 顺序展示
    section_order = [
        'sleep', 'online', 'focus', 'mood',
        'stand_down', 'acked',
        'meta',                  # rest dump
    ]
    shown = set()
    for sec in section_order:
        if sec in state:
            _print_section(sec, state[sec])
            shown.add(sec)
    # 余下 section
    for k, v in state.items():
        if k in shown or k.startswith('_'):
            continue
        _print_section(k, v if isinstance(v, dict) else {k: v})
    return 0


if __name__ == '__main__':
    sys.exit(main())
