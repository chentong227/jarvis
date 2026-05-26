# -*- coding: utf-8 -*-
"""Sir CLI: 看 / 改 sir_behavior_temporal_vocab.json.

用法:
  python scripts/time_awareness_dump.py list
  python scripts/time_awareness_dump.py show <hour_day_key>  # e.g. 23_mon
  python scripts/time_awareness_dump.py now                  # 当前 hour pattern
  python scripts/time_awareness_dump.py add <hour_day_key> --activity X --topic Y
  python scripts/time_awareness_dump.py rm <hour_day_key>
  python scripts/time_awareness_dump.py routine_add --name evening_wind_down \
        --hours 22,23,0 --sig showered,睡前
  python scripts/time_awareness_dump.py reflect                # 强 reflect now
  python scripts/time_awareness_dump.py prompt                 # show 主脑 lite block
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# add parent to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def cmd_list(args):
    from jarvis_time_awareness import _load_vocab
    vocab = _load_vocab()
    patterns = vocab.get('patterns', {})
    by_hour = vocab.get('patterns_by_hour', {})
    print(f"\n== patterns (hour × day, {len(patterns)} entries) ==")
    if not patterns:
        print("  (empty)")
    for k in sorted(patterns.keys()):
        p = patterns[k]
        acts = ','.join(p.get('typical_activities', [])[:3])
        print(f"  {k:10s}  freq={p.get('frequency', 0):.2f} "
              f"n={p.get('sample_count', 0)}  acts=[{acts}]")
    print(f"\n== patterns_by_hour aggregate ({len(by_hour)} hours) ==")
    for hour in sorted(by_hour.keys(), key=int):
        p = by_hour[hour]
        acts = ','.join(p.get('typical_activities', [])[:3])
        print(f"  hour={hour:2s}    freq={p.get('frequency', 0):.2f} "
              f"n={p.get('sample_count', 0)}  acts=[{acts}]")
    routines = vocab.get('learned_routines', [])
    print(f"\n== learned_routines ({len(routines)}) ==")
    for r in routines:
        print(f"  - {r.get('name', '?')}  hours={r.get('hours', [])}  "
              f"sig={r.get('signature', [])}  conf={r.get('confidence', 0):.2f}")
    print(f"\nlast_reflector_run: {vocab.get('last_reflector_run', '(never)')}")


def cmd_show(args):
    from jarvis_time_awareness import _load_vocab
    vocab = _load_vocab()
    key = args.key
    p = vocab.get('patterns', {}).get(key)
    if not p:
        print(f"key '{key}' not found in patterns")
        return
    print(json.dumps(p, ensure_ascii=False, indent=2))


def cmd_now(args):
    from jarvis_time_awareness import get_pattern_at_now, get_routines_active_now
    p = get_pattern_at_now()
    print(json.dumps(p, ensure_ascii=False, indent=2))
    r = get_routines_active_now()
    if r:
        print("\n== active routines ==")
        for x in r:
            print(json.dumps(x, ensure_ascii=False, indent=2))


def cmd_add(args):
    from jarvis_time_awareness import _load_vocab, _save_vocab
    vocab = _load_vocab()
    key = args.key
    patterns = dict(vocab.get('patterns', {}))
    p = dict(patterns.get(key, {
        'typical_activities': [], 'typical_topics': [],
        'frequency': 0.0, 'sample_count': 0,
    }))
    if args.activity:
        acts = list(p.get('typical_activities', []))
        for a in args.activity.split(','):
            a = a.strip()
            if a and a not in acts:
                acts.append(a)
        p['typical_activities'] = acts
    if args.topic:
        tops = list(p.get('typical_topics', []))
        for t in args.topic.split(','):
            t = t.strip()
            if t and t not in tops:
                tops.append(t)
        p['typical_topics'] = tops
    p['last_observed'] = time.strftime('%Y-%m-%d')
    p['sample_count'] = max(int(p.get('sample_count', 0)), 1)
    patterns[key] = p
    vocab['patterns'] = patterns
    if _save_vocab(vocab):
        print(f"updated {key}")
    else:
        print("save failed")


def cmd_rm(args):
    from jarvis_time_awareness import _load_vocab, _save_vocab
    vocab = _load_vocab()
    patterns = dict(vocab.get('patterns', {}))
    if args.key in patterns:
        del patterns[args.key]
        vocab['patterns'] = patterns
        if _save_vocab(vocab):
            print(f"removed {args.key}")
    else:
        print(f"{args.key} not in patterns")


def cmd_routine_add(args):
    from jarvis_time_awareness import _load_vocab, _save_vocab
    vocab = _load_vocab()
    routines = list(vocab.get('learned_routines', []))
    hours = [int(h.strip()) for h in args.hours.split(',') if h.strip()]
    sig = [s.strip() for s in args.sig.split(',') if s.strip()]
    routines.append({
        'name': args.name,
        'hours': hours,
        'signature': sig,
        'confidence': float(args.confidence or 0.7),
        'added': time.strftime('%Y-%m-%d'),
    })
    vocab['learned_routines'] = routines
    if _save_vocab(vocab):
        print(f"added routine '{args.name}'")


def cmd_reflect(args):
    from jarvis_time_awareness import maybe_run_reflector
    # Sir 强 reflect — 用空 stm (后续 daemon real-run 时会真 mine)
    # 实际 daemon 跑时自带 STM, 这里只 force=True 触发 timestamp
    ok = maybe_run_reflector([], force=True)
    print(f"reflector run: {ok}")


def cmd_prompt(args):
    from jarvis_time_awareness import format_for_thought_prompt, format_for_main_brain_lite
    print("== InnerThought prompt block ==")
    print(format_for_thought_prompt() or '(no data)')
    print("\n== Main brain lite ==")
    print(format_for_main_brain_lite() or '(no data)')


def main():
    p = argparse.ArgumentParser(description='TimeAwareness vocab CLI')
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('list')

    sp = sub.add_parser('show'); sp.add_argument('key')
    sub.add_parser('now')
    sp = sub.add_parser('add')
    sp.add_argument('key')
    sp.add_argument('--activity', default='')
    sp.add_argument('--topic', default='')
    sp = sub.add_parser('rm'); sp.add_argument('key')
    sp = sub.add_parser('routine_add')
    sp.add_argument('--name', required=True)
    sp.add_argument('--hours', required=True)
    sp.add_argument('--sig', required=True)
    sp.add_argument('--confidence', default='0.7')
    sub.add_parser('reflect')
    sub.add_parser('prompt')

    args = p.parse_args()
    if args.cmd == 'list':
        cmd_list(args)
    elif args.cmd == 'show':
        cmd_show(args)
    elif args.cmd == 'now':
        cmd_now(args)
    elif args.cmd == 'add':
        cmd_add(args)
    elif args.cmd == 'rm':
        cmd_rm(args)
    elif args.cmd == 'routine_add':
        cmd_routine_add(args)
    elif args.cmd == 'reflect':
        cmd_reflect(args)
    elif args.cmd == 'prompt':
        cmd_prompt(args)
    else:
        p.print_help()


if __name__ == '__main__':
    main()
