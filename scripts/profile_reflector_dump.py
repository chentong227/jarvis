# -*- coding: utf-8 -*-
"""[P2-Gap11 / 2026-05-21 00:15] Profile Reflector CLI — Sir 仲裁 sir_profile.json propose

Usage:
    python scripts/profile_reflector_dump.py                       # list review
    python scripts/profile_reflector_dump.py --review              # list review only
    python scripts/profile_reflector_dump.py --all                 # list all (review/active/rejected)
    python scripts/profile_reflector_dump.py --propose             # trigger 1 propose run
    python scripts/profile_reflector_dump.py --activate <id>       # Sir 通过
    python scripts/profile_reflector_dump.py --reject <id>         # Sir 拒
    python scripts/profile_reflector_dump.py --stats               # 统计
"""
from __future__ import annotations

import argparse
import os
import sys


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--review', action='store_true')
    p.add_argument('--all', action='store_true')
    p.add_argument('--propose', action='store_true')
    p.add_argument('--activate', metavar='ID')
    p.add_argument('--reject', metavar='ID')
    p.add_argument('--stats', action='store_true')
    args = p.parse_args()

    from jarvis_profile_reflector import get_default_reflector
    reflector = get_default_reflector()

    if args.stats:
        for k, v in reflector.stats().items():
            print(f'  {k:12s} = {v}')
        return

    if args.propose:
        new_props = reflector.propose_from_corrections()
        print(f'[ProfileReflector] proposed {len(new_props)} new changes (now in review queue)')
        return

    if args.activate:
        ok = reflector.activate(args.activate)
        print(f'[ProfileReflector] activate {args.activate}: {"OK" if ok else "NOT FOUND"}')
        return

    if args.reject:
        ok = reflector.reject(args.reject)
        print(f'[ProfileReflector] reject {args.reject}: {"OK" if ok else "NOT FOUND"}')
        return

    # default: list review
    reviews = reflector.list_review()
    if not reviews and not args.all:
        print('[ProfileReflector] (no proposals in review)')
        print('  Tip: --propose to trigger one run, or --all to see active+rejected')
        return

    if args.all:
        all_props = reflector._proposals
        print(f'[ProfileReflector] {len(all_props)} total proposals:')
        for p in all_props:
            print(f"  [{p.state.upper():8s}] {p.proposal_id}: {p.field_path} = '{str(p.new_value)[:40]}' ({p.action})")
            if p.rationale:
                print(f'      rationale: {p.rationale[:120]}')
    else:
        print(f'[ProfileReflector] {len(reviews)} proposals awaiting Sir review:')
        for p in reviews:
            print(f"  {p.proposal_id}: {p.field_path} ({p.action})")
            print(f"      new: '{str(p.new_value)[:60]}'")
            if p.rationale:
                print(f'      why: {p.rationale[:150]}')
            print()


if __name__ == '__main__':
    main()
