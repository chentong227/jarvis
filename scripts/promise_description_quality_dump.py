"""[Sir 2026-05-28 07:18] CLI for promise_description_quality_vocab.json.

准则 6.5 vocab 持久化 + CLI 可改. 治 SmartNudge '02:43 番茄钟' 幻觉:
PromiseLog.add() 前校验 description, blacklist 拒 fake commitment.

Usage:
    python scripts/promise_description_quality_dump.py             # list
    python scripts/promise_description_quality_dump.py --add x     # 加 'x' 入 blacklist
    python scripts/promise_description_quality_dump.py --remove x  # 移
    python scripts/promise_description_quality_dump.py --mode accept_warn  # 切模式
    python scripts/promise_description_quality_dump.py --test "x"  # 测某 desc 会被拒
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'promise_description_quality_vocab.json')


def _load():
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(d):
    d.setdefault('history', []).append({
        'date': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'change': f'CLI {sys.argv[1:]}',
    })
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def is_rejected(desc: str, vocab: dict) -> tuple:
    """Return (rejected: bool, reason: str). 公开 — PromiseLog.add() 调."""
    if not isinstance(desc, str):
        return True, f'not_string ({type(desc).__name__})'
    desc_stripped = desc.strip()
    bl = vocab.get('blacklist_descriptions', {})
    if desc_stripped in bl.get('exact_match', []):
        return True, f'exact_match:{desc_stripped!r}'
    for p in bl.get('prefix_match', []):
        if desc_stripped.startswith(p):
            return True, f'prefix_match:{p!r}'
    for pat in bl.get('regex_patterns', []):
        try:
            if re.match(pat, desc_stripped):
                return True, f'regex:{pat!r}'
        except re.error:
            pass
    min_len = int(vocab.get('min_length', 3))
    if len(desc_stripped) < min_len:
        return True, f'too_short ({len(desc_stripped)} < {min_len})'
    max_len = int(vocab.get('max_length', 500))
    if len(desc_stripped) > max_len:
        return True, f'too_long ({len(desc_stripped)} > {max_len})'
    return False, ''


def cmd_list(v):
    print(f"PromiseDescriptionQuality vocab @ {VOCAB_PATH}")
    print(f"  version: {v.get('version')}")
    print(f"  behavior_on_violation: {v.get('behavior_on_violation')}")
    print(f"  min_length: {v.get('min_length')} / max_length: {v.get('max_length')}")
    bl = v.get('blacklist_descriptions', {})
    print(f"  exact_match  ({len(bl.get('exact_match', []))}): {bl.get('exact_match', [])[:15]}{'...' if len(bl.get('exact_match', [])) > 15 else ''}")
    print(f"  prefix_match ({len(bl.get('prefix_match', []))}): {bl.get('prefix_match', [])}")
    print(f"  regex_patts  ({len(bl.get('regex_patterns', []))}): {bl.get('regex_patterns', [])}")


def cmd_add(v, item, where='exact_match'):
    bl = v.setdefault('blacklist_descriptions', {}).setdefault(where, [])
    if item in bl:
        print(f"already in {where}: {item!r}")
        return
    bl.append(item)
    _save(v)
    print(f"added to {where}: {item!r} (now {len(bl)} items)")


def cmd_remove(v, item, where='exact_match'):
    bl = v.get('blacklist_descriptions', {}).get(where, [])
    if item not in bl:
        print(f"not in {where}: {item!r}")
        return
    bl.remove(item)
    _save(v)
    print(f"removed from {where}: {item!r}")


def cmd_mode(v, mode):
    valid = list(v.get('behavior_modes', {}).keys()) or ['reject_silent', 'reject_raise', 'accept_warn']
    if mode not in valid:
        print(f"invalid mode {mode!r}. valid: {valid}")
        return
    v['behavior_on_violation'] = mode
    _save(v)
    print(f"behavior_on_violation = {mode}")


def cmd_test(v, desc):
    rejected, reason = is_rejected(desc, v)
    if rejected:
        print(f"❌ REJECT {desc!r} — {reason}")
    else:
        print(f"✅ ACCEPT {desc!r}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--add', help='add to exact_match blacklist')
    p.add_argument('--add-prefix', help='add to prefix_match blacklist')
    p.add_argument('--remove', help='remove from exact_match blacklist')
    p.add_argument('--remove-prefix', help='remove from prefix_match blacklist')
    p.add_argument('--mode', help='set behavior_on_violation (reject_silent|reject_raise|accept_warn)')
    p.add_argument('--test', help='test if a description would be rejected')
    args = p.parse_args()

    v = _load()

    if args.add:
        cmd_add(v, args.add, 'exact_match')
    elif args.add_prefix:
        cmd_add(v, args.add_prefix, 'prefix_match')
    elif args.remove:
        cmd_remove(v, args.remove, 'exact_match')
    elif args.remove_prefix:
        cmd_remove(v, args.remove_prefix, 'prefix_match')
    elif args.mode:
        cmd_mode(v, args.mode)
    elif args.test is not None:
        cmd_test(v, args.test)
    else:
        cmd_list(v)


if __name__ == '__main__':
    main()
