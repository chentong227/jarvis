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


def cmd_propose(args) -> None:
    st = _store(args.path)
    ok, msg = st.propose_dimension(
        args.dimension,
        args.value,
        reason=args.reason or '',
        evidence_turn_id=args.turn_id or '',
        source='sir_cli_propose',
    )
    if not ok:
        raise SystemExit(f'❌ {msg}')
    print(f'📝 proposed {msg}')


def cmd_review(args) -> None:
    st = _store(args.path)
    items = st.list_review(include_decided=args.all)
    print(f'📋 RelationshipState Review ({len(items)})')
    for p in items:
        print(
            f'- {p.id} [{p.state}] {p.dimension}: '
            f'{p.current_value:.2f}->{p.proposed_value:.2f} '
            f'source={p.source} reason={p.reason[:100]}'
        )


def cmd_approve(args) -> None:
    st = _store(args.path)
    ok, msg = st.approve_proposal(args.proposal_id, reason=args.reason or '')
    if not ok:
        raise SystemExit(f'❌ {msg}')
    print(f'✅ {msg}')
    print(st.to_prompt_line(max_chars=240))


def cmd_reject(args) -> None:
    st = _store(args.path)
    ok, msg = st.reject_proposal(args.proposal_id, reason=args.reason or '')
    if not ok:
        raise SystemExit(f'❌ {msg}')
    print(f'✅ {msg}')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='RelationshipState CLI')
    p.add_argument('--path', default='', help='override relationship_state.json path')
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('list')
    p_set = sub.add_parser('set')
    p_set.add_argument('dimension')
    p_set.add_argument('value', type=float)
    p_set.add_argument('--note', default='')

    p_prop = sub.add_parser('propose')
    p_prop.add_argument('dimension')
    p_prop.add_argument('value', type=float)
    p_prop.add_argument('--reason', default='')
    p_prop.add_argument('--turn-id', default='')

    p_review = sub.add_parser('review')
    p_review.add_argument('--all', action='store_true')

    p_approve = sub.add_parser('approve')
    p_approve.add_argument('proposal_id')
    p_approve.add_argument('--reason', default='')

    p_reject = sub.add_parser('reject')
    p_reject.add_argument('proposal_id')
    p_reject.add_argument('--reason', default='')

    args = p.parse_args(argv)
    if args.cmd in (None, 'list'):
        cmd_list(args)
        return 0
    if args.cmd == 'set':
        cmd_set(args)
        return 0
    if args.cmd == 'propose':
        cmd_propose(args)
        return 0
    if args.cmd == 'review':
        cmd_review(args)
        return 0
    if args.cmd == 'approve':
        cmd_approve(args)
        return 0
    if args.cmd == 'reject':
        cmd_reject(args)
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
