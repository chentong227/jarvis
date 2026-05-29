# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'memory_pool', 'relationship_reflector_config.json')

DEFAULT_CONFIG = {
    'enabled': False,
    'min_interval_s': 21600,
    'min_stm_turns': 2,
    'use_llm': False,
    '_field_doc': {
        'enabled': 'Master switch. Default false: no background token cost.',
        'min_interval_s': 'Minimum seconds between relationship reflector attempts.',
        'min_stm_turns': 'Minimum recent STM turns required before proposing.',
        'use_llm': 'If false, hook remains inert even when enabled.',
    },
}


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key in ('enabled', 'min_interval_s', 'min_stm_turns', 'use_llm', '_field_doc'):
        if key in data:
            merged[key] = data[key]
    return merged


def _save(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    print(f'✅ saved → {path}')


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        return raw


def cmd_set(cfg: dict, items: list) -> None:
    valid = {'enabled', 'min_interval_s', 'min_stm_turns', 'use_llm'}
    for item in items:
        if '=' not in item:
            raise SystemExit(f'❌ --set requires KEY=VALUE, got {item}')
        key, raw = item.split('=', 1)
        key = key.strip()
        if key not in valid:
            raise SystemExit(f'❌ unknown key: {key}; valid: {", ".join(sorted(valid))}')
        cfg[key] = _parse_value(raw.strip())
        print(f'  {key} = {cfg[key]}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Relationship reflector config CLI')
    parser.add_argument('--path', default=CONFIG_PATH,
                        help='config path override for tests/mirror smoke')
    parser.add_argument('--set', action='append', default=[],
                        help='set KEY=VALUE')
    parser.add_argument('--enable', action='store_true',
                        help='enable relationship reflector hook')
    parser.add_argument('--disable', action='store_true',
                        help='disable relationship reflector hook')
    parser.add_argument('--llm-on', action='store_true',
                        help='allow hook to call LLM when enabled')
    parser.add_argument('--llm-off', action='store_true',
                        help='prevent hook from calling LLM')
    parser.add_argument('--reset', action='store_true',
                        help='reset to default config')
    args = parser.parse_args(argv)

    if args.reset:
        _save(args.path, json.loads(json.dumps(DEFAULT_CONFIG)))
        return

    cfg = _load(args.path)
    changed = False
    if args.enable:
        cfg['enabled'] = True
        changed = True
    if args.disable:
        cfg['enabled'] = False
        changed = True
    if args.llm_on:
        cfg['use_llm'] = True
        changed = True
    if args.llm_off:
        cfg['use_llm'] = False
        changed = True
    if args.set:
        cmd_set(cfg, args.set)
        changed = True

    if changed:
        _save(args.path, cfg)
        return

    print(json.dumps(cfg, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
