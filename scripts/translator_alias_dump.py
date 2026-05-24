# -*- coding: utf-8 -*-
"""CLI: Translator alias vocab 管理.

用法 (类 concerns_dump.py 风格):
    python scripts/translator_alias_dump.py list
    python scripts/translator_alias_dump.py list --status review
    python scripts/translator_alias_dump.py list --kind organ
    python scripts/translator_alias_dump.py add --kind organ --from X --to Y
                                                --evidence "Sir 真测..."
    python scripts/translator_alias_dump.py activate alias_004
    python scripts/translator_alias_dump.py reject alias_004
    python scripts/translator_alias_dump.py archive alias_004
    python scripts/translator_alias_dump.py stats
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'translator_alias_vocab.json')


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'schema_version': 1, 'aliases': []}
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict) -> None:
    data['last_modified'] = datetime.utcnow().isoformat() + 'Z'
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    with open(VOCAB_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _next_id(data: dict) -> str:
    aliases = data.get('aliases', []) or []
    max_n = 0
    for a in aliases:
        aid = a.get('id', '')
        if aid.startswith('alias_'):
            try:
                n = int(aid.split('_', 1)[1])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f'alias_{max_n + 1:03d}'


def cmd_list(args) -> None:
    data = _load()
    aliases = data.get('aliases', []) or []
    if args.status:
        aliases = [a for a in aliases if a.get('status') == args.status]
    if args.kind:
        aliases = [a for a in aliases if a.get('kind') == args.kind]

    if not aliases:
        print('(no aliases)')
        return

    print(f'{"ID":12} {"KIND":8} {"FROM":24} {"TO":24} {"STATUS":10} {"HITS":>5}')
    print('-' * 95)
    for a in aliases:
        print(
            f'{a.get("id", "")[:12]:12} '
            f'{a.get("kind", "")[:8]:8} '
            f'{a.get("from", "")[:24]:24} '
            f'{a.get("to", "")[:24]:24} '
            f'{a.get("status", "")[:10]:10} '
            f'{a.get("hit_count", 0):>5}'
        )


def cmd_add(args) -> None:
    data = _load()
    new_id = _next_id(data)
    entry = {
        'id': new_id,
        'kind': args.kind,
        'from': getattr(args, 'from'),
        'to': args.to,
        'status': 'review',
        'evidence': args.evidence or '(CLI manual add)',
        'added_by': 'Sir-CLI',
        'added_at': datetime.utcnow().isoformat() + 'Z',
        'activated_by': None,
        'activated_at': None,
        'hit_count': 0,
        'last_hit_at': None,
        'version': 1,
        'superseded_by': None,
    }
    if args.kind == 'command' and args.scope_organ:
        entry['scope_organ'] = args.scope_organ
    data.setdefault('aliases', []).append(entry)
    _save(data)
    print(f'added {new_id} (status=review). activate by:')
    print(f'  python scripts/translator_alias_dump.py activate {new_id}')


def cmd_activate(args) -> None:
    data = _load()
    for a in data.get('aliases', []) or []:
        if a.get('id') == args.alias_id:
            a['status'] = 'active'
            a['activated_by'] = 'Sir'
            a['activated_at'] = datetime.utcnow().isoformat() + 'Z'
            _save(data)
            print(f'activated {args.alias_id}')
            return
    print(f'no alias {args.alias_id}')
    sys.exit(1)


def cmd_reject(args) -> None:
    data = _load()
    for a in data.get('aliases', []) or []:
        if a.get('id') == args.alias_id:
            a['status'] = 'rejected'
            a['activated_by'] = None
            _save(data)
            print(f'rejected {args.alias_id}')
            return
    print(f'no alias {args.alias_id}')
    sys.exit(1)


def cmd_archive(args) -> None:
    data = _load()
    for a in data.get('aliases', []) or []:
        if a.get('id') == args.alias_id:
            a['status'] = 'archived'
            _save(data)
            print(f'archived {args.alias_id}')
            return
    print(f'no alias {args.alias_id}')
    sys.exit(1)


def cmd_stats(args) -> None:
    data = _load()
    aliases = data.get('aliases', []) or []
    by_status = {}
    by_kind = {}
    total_hits = 0
    for a in aliases:
        by_status[a.get('status', '')] = by_status.get(a.get('status', ''), 0) + 1
        by_kind[a.get('kind', '')] = by_kind.get(a.get('kind', ''), 0) + 1
        total_hits += a.get('hit_count', 0) or 0
    print(f'TOTAL aliases: {len(aliases)}')
    print(f'TOTAL hits:    {total_hits}')
    print('BY STATUS:')
    for k, v in sorted(by_status.items()):
        print(f'  {k:10} {v}')
    print('BY KIND:')
    for k, v in sorted(by_kind.items()):
        print(f'  {k:10} {v}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Translator alias vocab manager')
    subs = parser.add_subparsers(dest='cmd', required=True)

    p_list = subs.add_parser('list', help='list all aliases')
    p_list.add_argument('--status', choices=['active', 'review', 'rejected', 'archived'])
    p_list.add_argument('--kind', choices=['organ', 'command'])
    p_list.set_defaults(func=cmd_list)

    p_add = subs.add_parser('add', help='add new alias (status=review)')
    p_add.add_argument('--kind', choices=['organ', 'command'], required=True)
    p_add.add_argument('--from', required=True, dest='from')
    p_add.add_argument('--to', required=True)
    p_add.add_argument('--scope-organ', dest='scope_organ', default=None)
    p_add.add_argument('--evidence', default='')
    p_add.set_defaults(func=cmd_add)

    p_act = subs.add_parser('activate', help='set status=active')
    p_act.add_argument('alias_id')
    p_act.set_defaults(func=cmd_activate)

    p_rej = subs.add_parser('reject', help='set status=rejected')
    p_rej.add_argument('alias_id')
    p_rej.set_defaults(func=cmd_reject)

    p_arc = subs.add_parser('archive', help='set status=archived (soft delete)')
    p_arc.add_argument('alias_id')
    p_arc.set_defaults(func=cmd_archive)

    p_stat = subs.add_parser('stats', help='show stats')
    p_stat.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
