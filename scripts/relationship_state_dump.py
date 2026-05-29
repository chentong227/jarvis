# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys

import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from jarvis_relationship_state import RelationshipStateStore  # noqa: E402

DEFAULT_PATH = os.path.join(_ROOT, 'memory_pool', 'relationship_state.json')


def _store(path: str = '') -> RelationshipStateStore:
    st = RelationshipStateStore(path or DEFAULT_PATH)
    st.load()
    return st


def cmd_list(args) -> None:
    st = _store(args.path)
    s = st.state
    print(f'📋 RelationshipState ({st.path})')
    print(st.to_prompt_line(max_chars=240))
    print(f'source={s.source} turn_id={s.updated_turn_id or "-"}')
    print(f'note={s.note or "-"}')


def cmd_set(args) -> None:
    st = _store(args.path)
    ok, msg = st.set_dimension(
        args.dimension,
        args.value,
        source='sir_cli',
        note=args.note or '',
    )
    if not ok:
        raise SystemExit(f'❌ {msg}')
    print(f'✅ {msg}')
    print(st.to_prompt_line(max_chars=240))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='RelationshipState CLI')
    p.add_argument('--path', default='', help='override relationship_state.json path')
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('list')
    p_set = sub.add_parser('set')
    p_set.add_argument('dimension')
    p_set.add_argument('value', type=float)
    p_set.add_argument('--note', default='')

    args = p.parse_args(argv)
    if args.cmd in (None, 'list'):
        cmd_list(args)
        return 0
    if args.cmd == 'set':
        cmd_set(args)
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
