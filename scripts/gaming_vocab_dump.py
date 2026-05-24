# -*- coding: utf-8 -*-
"""[Sir 真测 BUG-2 治本 / 2026-05-24] gaming_vocab CLI

准则 6.5 三件套 #2: CLI 可改 — Sir 不用改源码 + git commit, 直接调本 CLI:
  - 看现在哪些游戏 vocab 在生效
  - 加新游戏 (L7 reflector 没看到的)
  - activate / reject _review_queue 里 L7 propose 的
  - 设 require_fullscreen / VAD multiplier

usage:
  python scripts/gaming_vocab_dump.py                      # default --list
  python scripts/gaming_vocab_dump.py --list
  python scripts/gaming_vocab_dump.py --add "Hearthstone" --note "炉石"
  python scripts/gaming_vocab_dump.py --reject "drm"
  python scripts/gaming_vocab_dump.py --activate "pubg"
  python scripts/gaming_vocab_dump.py --review                 # 看 L7 propose queue
  python scripts/gaming_vocab_dump.py --approve-review 0      # 把 review queue idx=0 移到 active
  python scripts/gaming_vocab_dump.py --set-fullscreen false
  python scripts/gaming_vocab_dump.py --set-multiplier 2.0 1.5
"""
from __future__ import annotations
import os
import sys
import json
import time
import argparse


def _path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, 'memory_pool', 'gaming_vocab.json')


def _load() -> dict:
    p = _path()
    if not os.path.exists(p):
        print(f'❌ vocab 不存在: {p}', file=sys.stderr)
        sys.exit(1)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict) -> None:
    p = _path()
    data.setdefault('_meta', {})['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cmd_list(data: dict) -> int:
    print('\n=== gaming_vocab.json ===\n')
    meta = data.get('_meta', {})
    print(f"version: {meta.get('version','?')}, updated: {meta.get('updated','?')}")
    print(f"require_fullscreen: {data.get('require_fullscreen', True)}")
    vad = data.get('vad_adaptation', {})
    print(f"VAD multipliers: volume={vad.get('volume_threshold_multiplier', 1.8)}, "
            f"silence={vad.get('silence_limit_multiplier', 1.3)}")
    titles = data.get('title_keywords', [])
    active = [t for t in titles if isinstance(t, dict) and t.get('state') == 'active']
    rejected = [t for t in titles if isinstance(t, dict) and t.get('state') == 'rejected']
    print(f"\nactive title_keywords ({len(active)}):")
    for t in active:
        n = t.get('note', '')
        n_tag = f' — {n}' if n else ''
        print(f"  ✓ {t.get('pattern','?'):30s}{n_tag}")
    if rejected:
        print(f"\nrejected ({len(rejected)}):")
        for t in rejected:
            print(f"  ✗ {t.get('pattern','?'):30s}")
    review = data.get('_review_queue', [])
    if review:
        print(f"\n_review_queue ({len(review)}): (用 --review 看详情, --approve-review N)")
    return 0


def cmd_review(data: dict) -> int:
    review = data.get('_review_queue', [])
    print(f'\n=== L7 reflector review queue ({len(review)}) ===\n')
    for i, r in enumerate(review):
        if isinstance(r, dict):
            print(f"  [{i}] pattern={r.get('pattern','?')!r}")
            for k, v in r.items():
                if k != 'pattern':
                    print(f"       {k}: {v}")
        else:
            print(f"  [{i}] {r}")
    if not review:
        print('(empty)')
    return 0


def cmd_add(data: dict, pattern: str, note: str = '') -> int:
    titles = data.setdefault('title_keywords', [])
    p_low = pattern.lower().strip()
    if not p_low:
        print('❌ pattern 不能为空', file=sys.stderr)
        return 1
    for t in titles:
        if isinstance(t, dict) and t.get('pattern', '').lower() == p_low:
            t['state'] = 'active'
            t['note'] = note or t.get('note', '')
            t['added'] = time.strftime('%Y-%m-%d')
            _save(data)
            print(f'✓ activated existing: {p_low!r}')
            return 0
    titles.append({
        'pattern': p_low,
        'state': 'active',
        'added': time.strftime('%Y-%m-%d'),
        'note': note or 'Sir CLI add',
    })
    _save(data)
    print(f'✓ added active: {p_low!r}')
    return 0


def cmd_reject(data: dict, pattern: str) -> int:
    titles = data.get('title_keywords', [])
    p_low = pattern.lower().strip()
    for t in titles:
        if isinstance(t, dict) and t.get('pattern', '').lower() == p_low:
            t['state'] = 'rejected'
            t['rejected_at'] = time.strftime('%Y-%m-%d')
            _save(data)
            print(f'✓ rejected: {p_low!r}')
            return 0
    print(f'❌ pattern 不存在: {pattern!r}', file=sys.stderr)
    return 1


def cmd_activate(data: dict, pattern: str) -> int:
    titles = data.get('title_keywords', [])
    p_low = pattern.lower().strip()
    for t in titles:
        if isinstance(t, dict) and t.get('pattern', '').lower() == p_low:
            t['state'] = 'active'
            _save(data)
            print(f'✓ activated: {p_low!r}')
            return 0
    print(f'❌ pattern 不存在: {pattern!r}', file=sys.stderr)
    return 1


def cmd_approve_review(data: dict, idx: int) -> int:
    review = data.get('_review_queue', [])
    if idx < 0 or idx >= len(review):
        print(f'❌ idx {idx} 超界 (queue size={len(review)})', file=sys.stderr)
        return 1
    entry = review.pop(idx)
    titles = data.setdefault('title_keywords', [])
    if isinstance(entry, dict):
        pattern = entry.get('pattern', '')
        note = entry.get('note', 'L7 propose approved')
    else:
        pattern = str(entry)
        note = 'L7 propose approved'
    titles.append({
        'pattern': pattern.lower().strip(),
        'state': 'active',
        'added': time.strftime('%Y-%m-%d'),
        'note': note,
    })
    _save(data)
    print(f'✓ approved & activated: {pattern!r}')
    return 0


def cmd_set_fullscreen(data: dict, val: str) -> int:
    val_low = val.lower().strip()
    if val_low in ('true', '1', 'yes', 'on'):
        data['require_fullscreen'] = True
    elif val_low in ('false', '0', 'no', 'off'):
        data['require_fullscreen'] = False
    else:
        print(f'❌ 非法布尔值: {val!r} (用 true / false)', file=sys.stderr)
        return 1
    _save(data)
    print(f'✓ require_fullscreen = {data["require_fullscreen"]}')
    return 0


def cmd_set_multiplier(data: dict, vol: float, sil: float) -> int:
    vad = data.setdefault('vad_adaptation', {})
    vad['volume_threshold_multiplier'] = float(vol)
    vad['silence_limit_multiplier'] = float(sil)
    _save(data)
    print(f'✓ VAD multipliers: volume={vol}, silence={sil}')
    return 0


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--list', action='store_true', default=True,
                     help='list all (default)')
    g.add_argument('--review', action='store_true',
                     help='show L7 review queue')
    g.add_argument('--add', metavar='PATTERN', help='add new active pattern')
    g.add_argument('--reject', metavar='PATTERN', help='reject pattern (state=rejected)')
    g.add_argument('--activate', metavar='PATTERN', help='activate existing pattern')
    g.add_argument('--approve-review', type=int, metavar='IDX',
                     help='approve L7 queue entry at IDX (move to active)')
    g.add_argument('--set-fullscreen', metavar='BOOL',
                     help='set require_fullscreen (true/false)')
    ap.add_argument('--note', default='', help='note for --add')
    ap.add_argument('--set-multiplier', nargs=2, type=float, metavar=('VOL', 'SIL'),
                      help='set VAD multipliers (e.g. 2.0 1.5)')
    args = ap.parse_args()

    data = _load()

    if args.add:
        return cmd_add(data, args.add, args.note)
    if args.reject:
        return cmd_reject(data, args.reject)
    if args.activate:
        return cmd_activate(data, args.activate)
    if args.approve_review is not None:
        return cmd_approve_review(data, args.approve_review)
    if args.set_fullscreen:
        return cmd_set_fullscreen(data, args.set_fullscreen)
    if args.set_multiplier:
        return cmd_set_multiplier(data, args.set_multiplier[0], args.set_multiplier[1])
    if args.review:
        return cmd_review(data)
    return cmd_list(data)


if __name__ == '__main__':
    sys.exit(main())
