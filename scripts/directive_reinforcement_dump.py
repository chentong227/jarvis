# -*- coding: utf-8 -*-
"""Directive Reinforcement Config CLI.

Sir 可不改源码调 #3 正向复利规则。

Usage:
    python scripts/directive_reinforcement_dump.py --list
    python scripts/directive_reinforcement_dump.py --set min_helped 4
    python scripts/directive_reinforcement_dump.py --disable
    python scripts/directive_reinforcement_dump.py --enable
    python scripts/directive_reinforcement_dump.py --runtime
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
sys.path.insert(0, _ROOT)

CONFIG_PATH = os.path.join(
    _ROOT, 'memory_pool', 'directive_reinforcement_config.json')

_ALLOWED = {
    'enabled': bool,
    'min_fired': int,
    'min_helped': int,
    'min_helped_ratio': float,
    'max_rejected_rate': float,
    'cooldown_hours': float,
    'priority_step': int,
    'max_priority': int,
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {
            'enabled': True,
            'min_fired': 5,
            'min_helped': 3,
            'min_helped_ratio': 0.7,
            'max_rejected_rate': 0.1,
            'cooldown_hours': 24,
            'priority_step': 1,
            'max_priority': 9,
            '_field_doc': {},
        }
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f) or {}


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f'✅ saved {CONFIG_PATH}')


def _coerce(key: str, value: str):
    typ = _ALLOWED[key]
    if typ is bool:
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on', 'enable')
    if typ is int:
        return int(value)
    if typ is float:
        return float(value)
    return value


def cmd_list() -> None:
    cfg = load_config()
    print(f'📋 Directive Reinforcement Config ({CONFIG_PATH})')
    print('=' * 72)
    for k in _ALLOWED:
        print(f'  {k:24s} = {cfg.get(k)}')
    print('=' * 72)
    docs = cfg.get('_field_doc') or {}
    if docs:
        print('Field doc:')
        for k, v in docs.items():
            print(f'  {k}: {v}')


def cmd_set(key: str, value: str) -> None:
    if key not in _ALLOWED:
        print(f'❌ unknown key: {key}')
        print('allowed:', ', '.join(_ALLOWED.keys()))
        sys.exit(2)
    cfg = load_config()
    cfg[key] = _coerce(key, value)
    save_config(cfg)
    print(f'✅ {key} = {cfg[key]}')


def cmd_runtime() -> None:
    from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
    reg = DirectiveRegistry()
    _bootstrap_seed_only(reg)
    reg.load()
    print('📊 Directive reinforcement runtime stats')
    print('-' * 112)
    print(f'{"id":<34} {"prio":>4} {"fired":>6} {"helped":>6} '
          f'{"not":>5} {"rej":>4} {"last_reinf":>12} {"state":<10}')
    print('-' * 112)
    for d in sorted(reg.directives.values(), key=lambda x: -x.priority):
        print(f'{d.id[:34]:<34} {d.priority:>4} {d.fired:>6} '
              f'{d.helped:>6} {d.not_helped:>5} {d.rejected:>4} '
              f'{int(d.last_reinforced or 0):>12} {d.state:<10}')
    print('-' * 112)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Directive positive reinforcement config CLI')
    parser.add_argument('--list', action='store_true', help='List config')
    parser.add_argument('--set', nargs=2, metavar=('KEY', 'VALUE'),
                        help='Set one config value')
    parser.add_argument('--enable', action='store_true', help='Enable')
    parser.add_argument('--disable', action='store_true', help='Disable')
    parser.add_argument('--runtime', action='store_true',
                        help='Show directive helped/not_helped stats')
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.set:
        cmd_set(args.set[0], args.set[1])
    elif args.enable:
        cmd_set('enabled', 'true')
    elif args.disable:
        cmd_set('enabled', 'false')
    elif args.runtime:
        cmd_runtime()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
