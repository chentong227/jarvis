# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 18:44 Phase 2] SWM event → voice mirror vocab CLI

让 Sir 一行命令 list / activate / reject / add SWM→voice mirror mapping.
准则 6: vocab 持久化 memory_pool/swm_to_voice_vocab.json, CLI 可改, 不写死.

用法:
  python scripts/swm_to_voice_dump.py                 # list 所有 mapping
  python scripts/swm_to_voice_dump.py --active        # 只列 active=true
  python scripts/swm_to_voice_dump.py --inactive      # 只列 active=false
  python scripts/swm_to_voice_dump.py --activate <etype>
  python scripts/swm_to_voice_dump.py --reject <etype>
  python scripts/swm_to_voice_dump.py --add <etype> --source sensor \
      --intent observation --min-salience 0.4 \
      --wants-voice-min 0.7 --template "{desc}"
  python scripts/swm_to_voice_dump.py --tail [--limit 30]
      # 显示最近 voice entry (含 SWM mirror 来的)
  python scripts/swm_to_voice_dump.py --stats         # 全 mapping + voice stats

文件:
  memory_pool/swm_to_voice_vocab.json  ← 持久化 vocab
  memory_pool/inner_voice_24h.jsonl    ← voice append-only log

规范: AGENTS.md §1 准则 6 三维耦合
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'memory_pool', 'swm_to_voice_vocab.json'
)


def _load_vocab() -> dict:
    if not os.path.exists(_VOCAB_PATH):
        return {'mappings': []}
    try:
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {'mappings': []}
    except Exception as e:
        print(f'❌ load vocab fail: {e}', file=sys.stderr)
        sys.exit(1)


def _save_vocab(vocab: dict) -> None:
    # 写时间戳到 _meta
    if '_meta' not in vocab:
        vocab['_meta'] = {}
    vocab['_meta']['last_modified'] = time.strftime(
        '%Y-%m-%dT%H:%M:%S%z', time.localtime()
    )
    try:
        with open(_VOCAB_PATH, 'w', encoding='utf-8') as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)
        print(f'✅ vocab saved: {_VOCAB_PATH}')
    except Exception as e:
        print(f'❌ save vocab fail: {e}', file=sys.stderr)
        sys.exit(1)


def _find_mapping(vocab: dict, etype: str):
    for i, m in enumerate(vocab.get('mappings') or []):
        if m.get('etype') == etype:
            return i, m
    return -1, None


def cmd_list(active_only: bool = False, inactive_only: bool = False):
    vocab = _load_vocab()
    mappings = vocab.get('mappings') or []
    rows = []
    for m in mappings:
        a = m.get('active', True)
        if active_only and not a:
            continue
        if inactive_only and a:
            continue
        rows.append(m)
    print(f'\n📚 SWM → voice mirror vocab ({len(rows)}/{len(mappings)} '
          f'shown)\n')
    print(f'{"etype":<32} {"act":<4} {"source":<16} {"intent":<13} '
            f'{"min_sal":<8} {"wv_min":<7} template')
    print('-' * 110)
    for m in rows:
        act = '✓' if m.get('active', True) else '✗'
        etype = m.get('etype', '?')[:30]
        src = (m.get('source') or '?')[:14]
        intent = (m.get('intent') or '?')[:11]
        ms = m.get('min_salience', 0.3)
        wv = m.get('wants_voice_min_salience', '-')
        tmpl = (m.get('content_template') or '{desc}')[:40]
        print(f'{etype:<32} {act:<4} {src:<16} {intent:<13} '
                f'{ms:<8.2f} {str(wv):<7} {tmpl}')
    print()


def cmd_activate(etype: str):
    vocab = _load_vocab()
    i, m = _find_mapping(vocab, etype)
    if i < 0:
        print(f'❌ etype {etype!r} not found in vocab')
        sys.exit(1)
    vocab['mappings'][i]['active'] = True
    _save_vocab(vocab)
    print(f'✅ activated etype={etype}')


def cmd_reject(etype: str):
    vocab = _load_vocab()
    i, m = _find_mapping(vocab, etype)
    if i < 0:
        print(f'❌ etype {etype!r} not found in vocab')
        sys.exit(1)
    vocab['mappings'][i]['active'] = False
    _save_vocab(vocab)
    print(f'✅ rejected (active=false) etype={etype}')


def cmd_add(args):
    vocab = _load_vocab()
    i, _ = _find_mapping(vocab, args.add)
    if i >= 0:
        print(f'⚠️ etype {args.add!r} exists. Use --activate / --reject '
              f'or edit JSON manually for full mod.')
        sys.exit(1)
    new = {
        'etype': args.add,
        'active': True,
        'source': args.source or 'noting',
        'intent': args.intent or 'noting',
        'min_salience': float(args.min_salience) if args.min_salience else 0.3,
        'wants_voice_min_salience': float(args.wants_voice_min)
            if args.wants_voice_min else 0.8,
        'content_template': args.template or '{desc}',
    }
    vocab.setdefault('mappings', []).append(new)
    _save_vocab(vocab)
    print(f'✅ added new mapping: {json.dumps(new, ensure_ascii=False, indent=2)}')


def cmd_tail(limit: int = 30):
    from jarvis_inner_voice_track import get_inner_voice_track
    track = get_inner_voice_track()
    entries = track.all_recent(hours=24.0)
    # 倒序
    entries = sorted(entries, key=lambda e: -e.ts)[:limit]
    print(f'\n🌊 inner_voice 最近 {len(entries)} entries (倒序):\n')
    for e in entries:
        hhmm = time.strftime('%H:%M:%S', time.localtime(e.ts))
        star = '★' if e.wants_voice else ' '
        swm_etype = ''
        if e.meta and 'swm_etype' in e.meta:
            swm_etype = f' (swm:{e.meta["swm_etype"]})'
        print(f'  {hhmm} [{e.source:14s} / {e.intent:11s} u={e.urgency:.2f}] {star} '
              f'{e.content[:90]}{swm_etype}')
    print()


def cmd_stats():
    vocab = _load_vocab()
    mappings = vocab.get('mappings') or []
    active = sum(1 for m in mappings if m.get('active', True))
    print(f'\n📊 vocab stats: total={len(mappings)} active={active} '
          f'inactive={len(mappings) - active}')
    # source / intent 分布
    from collections import Counter
    src_c = Counter()
    intent_c = Counter()
    for m in mappings:
        if not m.get('active', True):
            continue
        src_c[m.get('source') or '?'] += 1
        intent_c[m.get('intent') or '?'] += 1
    print(f'  active source 分布: {dict(src_c)}')
    print(f'  active intent 分布: {dict(intent_c)}')

    # voice stats
    try:
        from jarvis_inner_voice_track import get_inner_voice_track
        s = get_inner_voice_track().stats()
        print(f'\n📊 voice track stats: {s}')
    except Exception as e:
        print(f'⚠️ voice track unavailable: {e}')
    print()


def main():
    parser = argparse.ArgumentParser(
        description='SWM → voice mirror vocab CLI (Sir 真愿景 Phase 2)'
    )
    parser.add_argument('--active', action='store_true',
                          help='only list active mappings')
    parser.add_argument('--inactive', action='store_true',
                          help='only list inactive mappings')
    parser.add_argument('--activate', metavar='ETYPE',
                          help='activate mapping by etype')
    parser.add_argument('--reject', metavar='ETYPE',
                          help='reject (deactivate) mapping by etype')
    parser.add_argument('--add', metavar='ETYPE',
                          help='add new mapping for etype')
    parser.add_argument('--source', help='for --add: voice source')
    parser.add_argument('--intent', help='for --add: voice intent')
    parser.add_argument('--min-salience', help='for --add: min salience to mirror')
    parser.add_argument('--wants-voice-min',
                          help='for --add: salience threshold for wants_voice=True')
    parser.add_argument('--template', help='for --add: content template (default {desc})')
    parser.add_argument('--tail', action='store_true',
                          help='show recent voice entries')
    parser.add_argument('--limit', type=int, default=30,
                          help='for --tail: max entries (default 30)')
    parser.add_argument('--stats', action='store_true',
                          help='show vocab + voice stats')

    args = parser.parse_args()

    if args.activate:
        cmd_activate(args.activate)
    elif args.reject:
        cmd_reject(args.reject)
    elif args.add:
        cmd_add(args)
    elif args.tail:
        cmd_tail(limit=args.limit)
    elif args.stats:
        cmd_stats()
    else:
        cmd_list(active_only=args.active, inactive_only=args.inactive)


if __name__ == '__main__':
    main()
