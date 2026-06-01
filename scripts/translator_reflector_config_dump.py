# -*- coding: utf-8 -*-
"""CLI: Translator L7 reflector config 管理.

Phase 4.D / 2026-05-24 — Sir 改 config 不需重启 Jarvis, daemon 下次 cycle 自动 pick up.

用法 (类 concerns_dump.py 风格):
    python scripts/translator_reflector_config_dump.py show
    python scripts/translator_reflector_config_dump.py set --tick-interval-s 600
    python scripts/translator_reflector_config_dump.py set --propose-threshold 2
    python scripts/translator_reflector_config_dump.py set --scan-window-s 3600
    python scripts/translator_reflector_config_dump.py reset

可调字段:
  tick_interval_s:    daemon cycle 间隔 (默认 1800s = 30min)
  startup_delay_s:    daemon 启动延迟 (默认 600s = 10min)
  propose_threshold:  同 (from, to) by_command N 次才 propose (默认 3)
  scan_window_s:      扫 SWM events 回看窗口 (默认 7200s = 2h)
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

from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONFIG_PATH = os.path.join(ROOT, 'memory_pool', 'translator_reflector_config.json')

DEFAULTS = {
    'tick_interval_s': 1800.0,
    'startup_delay_s': 600.0,
    'propose_threshold': 3,
    'scan_window_s': 7200.0,
}


def _load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {'schema_version': 1, **DEFAULTS}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict, reason: str) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    history = data.setdefault('_history', [])
    history.append({
        'ts': datetime.utcnow().isoformat() + 'Z',
        'marker': 'Sir-CLI',
        'reason': reason,
    })
    # 保留最近 20 条
    data['_history'] = history[-20:]
    tmp = CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def cmd_show(_args) -> None:
    data = _load()
    print(f'=== Translator Reflector Config ===')
    print(f'(file: {CONFIG_PATH})')
    print()
    for k, default in DEFAULTS.items():
        cur = data.get(k, default)
        diff_mark = '(默认)' if cur == default else '(已改)'
        print(f'  {k:22} = {cur} {diff_mark}')
    print()
    hist = data.get('_history', [])
    if hist:
        print(f'最近 {min(5, len(hist))} 次改动:')
        for h in hist[-5:]:
            print(f'  - {h.get("ts", "?")[:19]}: {h.get("reason", "")}')


def cmd_set(args) -> None:
    data = _load()
    changes = []
    for k in DEFAULTS:
        v = getattr(args, k, None)
        if v is not None:
            old = data.get(k, DEFAULTS[k])
            if old != v:
                data[k] = v
                changes.append(f'{k}: {old} → {v}')
    if not changes:
        print('(no changes — 至少需要 --tick-interval-s / --startup-delay-s / --propose-threshold / --scan-window-s 之一)')
        sys.exit(1)
    reason = ' | '.join(changes)
    _save(data, reason)
    print(f'✅ updated: {reason}')
    print('(daemon 下次 cycle 自动 pick up, 无需重启)')


def cmd_reset(_args) -> None:
    data = _load()
    changes = []
    for k, default in DEFAULTS.items():
        if data.get(k) != default:
            changes.append(f'{k}: {data.get(k)} → {default}')
            data[k] = default
    if not changes:
        print('(config 已是默认值)')
        return
    _save(data, 'reset to defaults: ' + ' | '.join(changes))
    print(f'✅ reset to defaults: {" | ".join(changes)}')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Translator L7 reflector config manager (Phase 4.D)')
    subs = parser.add_subparsers(dest='cmd', required=True)

    p_show = subs.add_parser('show', help='display current config')
    p_show.set_defaults(func=cmd_show)

    p_set = subs.add_parser('set', help='change config value')
    p_set.add_argument('--tick-interval-s', dest='tick_interval_s', type=float,
                        help='daemon cycle interval seconds (default 1800)')
    p_set.add_argument('--startup-delay-s', dest='startup_delay_s', type=float,
                        help='daemon startup delay seconds (default 600)')
    p_set.add_argument('--propose-threshold', dest='propose_threshold', type=int,
                        help='alias propose threshold count (default 3)')
    p_set.add_argument('--scan-window-s', dest='scan_window_s', type=float,
                        help='SWM events scan window seconds (default 7200)')
    p_set.set_defaults(func=cmd_set)

    p_reset = subs.add_parser('reset', help='reset all fields to defaults')
    p_reset.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
