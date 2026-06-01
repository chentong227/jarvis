# -*- coding: utf-8 -*-
"""[Gap-Y / β.5.46-fix5] Directive Inject Config CLI Dump.

准则 6.5: Sir 不改源码就能调 directive 分层注入策略.

Usage:
    python scripts/directive_inject_dump.py --list
    python scripts/directive_inject_dump.py --max-full 7
    python scripts/directive_inject_dump.py --threshold 10
    python scripts/directive_inject_dump.py --brief-max 150
"""
from __future__ import annotations

import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout


_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
sys.path.insert(0, _ROOT)

CONFIG_PATH = os.path.join(_ROOT, 'memory_pool', 'directive_inject_config.json')


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(f'❌ config not found: {CONFIG_PATH}')
        sys.exit(1)
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f'✅ saved {CONFIG_PATH}')


def cmd_list():
    cfg = load_config()
    print(f'📋 Directive Inject Config ({CONFIG_PATH})')
    print('=' * 60)
    for k, v in cfg.items():
        if k.startswith('_'):
            continue
        print(f'  {k:35s} = {v}')
    print('=' * 60)
    print('Field doc:')
    field_doc = cfg.get('_field_doc', {})
    for k, v in field_doc.items():
        print(f'  {k}: {v}')


def cmd_max_full(n: int):
    cfg = load_config()
    cfg['max_full_directives'] = max(1, n)
    save_config(cfg)
    print(f'✅ max_full_directives = {cfg["max_full_directives"]}')


def cmd_threshold(n: int):
    cfg = load_config()
    cfg['always_full_priority_threshold'] = max(1, n)
    save_config(cfg)
    print(f'✅ always_full_priority_threshold = {cfg["always_full_priority_threshold"]}')


def cmd_brief_max(n: int):
    cfg = load_config()
    cfg['brief_max_chars_per_directive'] = max(50, n)
    save_config(cfg)
    print(f'✅ brief_max_chars_per_directive = {cfg["brief_max_chars_per_directive"]}')


def cmd_show_runtime():
    """看运行时 directive 状态 (含 not_helped 计数)."""
    try:
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        reg.load()
        print('📊 Directive Runtime Stats:')
        print('-' * 100)
        print(f'{"id":<32} {"prio":>4} {"fired":>6} {"helped":>6} {"not_helped":>10} {"state":<10}')
        print('-' * 100)
        for d in sorted(reg.directives.values(), key=lambda x: -x.priority):
            print(f'{d.id[:32]:<32} {d.priority:>4} {d.fired:>6} {d.helped:>6} {d.not_helped:>10} {d.state:<10}')
        print('-' * 100)
    except Exception as e:
        print(f'❌ runtime stats unavailable: {e}')


def main():
    parser = argparse.ArgumentParser(description='Directive Inject Config CLI')
    parser.add_argument('--list', action='store_true', help='List config')
    parser.add_argument('--max-full', type=int, help='Set max_full_directives (top N 全文)')
    parser.add_argument('--threshold', type=int, help='Set always_full_priority_threshold (P>=N 永远全文)')
    parser.add_argument('--brief-max', type=int, help='Set brief_max_chars_per_directive')
    parser.add_argument('--show-runtime', action='store_true', help='Show runtime directive stats')
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.max_full is not None:
        cmd_max_full(args.max_full)
    elif args.threshold is not None:
        cmd_threshold(args.threshold)
    elif args.brief_max is not None:
        cmd_brief_max(args.brief_max)
    elif args.show_runtime:
        cmd_show_runtime()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
