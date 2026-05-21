# -*- coding: utf-8 -*-
"""[Gap-Z3 / β.5.46-fix11] Reflector Budget CLI dump.

Usage:
    python scripts/reflector_budget_dump.py --list      # 看用量
    python scripts/reflector_budget_dump.py --reset     # 强制 reset 窗口
    python scripts/reflector_budget_dump.py --set-cap concerns_reflector 80
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
sys.path.insert(0, _ROOT)

CONFIG_PATH = os.path.join(_ROOT, 'memory_pool', 'reflector_budget_config.json')


def cmd_list():
    from jarvis_reflector_budget import get_default_budget
    b = get_default_budget()
    s = b.stats()
    print(f'[Reflector Budget Stats]')
    print(f'  window_start: {s.get("window_start_iso", "?")}')
    print(f'  weekly_cap:   {s["weekly_cap_total"]}')
    print(f'  used:         {s["total_used"]}')
    print(f'  remaining:    {s["remaining"]}')
    print()
    print('Usage by reflector:')
    usage = s.get('usage_by_name', {})
    caps = s.get('per_reflector_cap', {})
    for name in sorted(set(list(usage.keys()) + list(caps.keys()))):
        used = usage.get(name, 0)
        cap = caps.get(name, '-')
        print(f'  {name:35s} {used:>5d} / {cap}')


def cmd_reset():
    from jarvis_reflector_budget import get_default_budget
    b = get_default_budget()
    b.reset_window()
    print('[OK] Window reset.')


def cmd_set_cap(name: str, cap: int):
    if not os.path.exists(CONFIG_PATH):
        print(f'[ERR] config not found: {CONFIG_PATH}')
        return
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    if 'per_reflector_cap' not in cfg or not isinstance(cfg['per_reflector_cap'], dict):
        cfg['per_reflector_cap'] = {}
    cfg['per_reflector_cap'][name] = max(1, int(cap))
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f'[OK] {name} cap set to {cap} (reload Jarvis for effect)')


def main():
    parser = argparse.ArgumentParser(description='Reflector Budget CLI')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--set-cap', nargs=2, metavar=('NAME', 'CAP'),
                         help='set per-reflector cap')
    args = parser.parse_args()
    if args.list:
        cmd_list()
    elif args.reset:
        cmd_reset()
    elif args.set_cap:
        cmd_set_cap(args.set_cap[0], int(args.set_cap[1]))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
