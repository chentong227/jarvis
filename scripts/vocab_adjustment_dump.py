#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[SOUL Phase 5 P3 / Sir 2026-05-29] 思考脑 self-debug vocab 调整 review CLI.

思考脑 propose_vocab_adjustment → review queue → 本 CLI 让 Sir 拍板.
准则 7 Sir 元否决: 思考脑只 propose, Sir apply/reject 才真改 vocab.

Subcommands:
  list              列 pending propose (思考脑 self-debug 建议)
  apply <idx> --yes Sir 拍板 → 真改 vocab key_path + mark applied
  reject <idx>      Sir 否决 → mark rejected
  clear-done        清掉已 applied/rejected 的历史 entry
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    import _cli_utils  # noqa: F401
except Exception:
    pass
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_REVIEW_PATH = os.path.join(_ROOT, 'memory_pool', 'vocab_adjustment_review.jsonl')


def _load_entries():
    if not os.path.exists(_REVIEW_PATH):
        return []
    out = []
    with open(_REVIEW_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _save_entries(entries):
    with open(_REVIEW_PATH, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


def _coerce(value: str):
    """类型推断: '100'→int, '0.4'→float, 'true'→bool, else str."""
    v = value.strip()
    if v.lower() in ('true', 'false'):
        return v.lower() == 'true'
    try:
        if '.' in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _set_nested(d: dict, key_path: str, value):
    """key_path 'a.b.c' → d['a']['b']['c'] = value."""
    keys = key_path.split('.')
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def cmd_list(_args) -> int:
    entries = _load_entries()
    pending = [(i, e) for i, e in enumerate(entries)
               if e.get('status') == 'pending']
    print(f"[vocab_adjustment review] {_REVIEW_PATH}")
    print(f"  total={len(entries)} pending={len(pending)}")
    if not pending:
        print("  (no pending proposals)")
        return 0
    print()
    for i, e in pending:
        print(f"  [{i}] {e.get('vocab_file')}:{e.get('key_path')} "
              f"= {e.get('proposed_value')}")
        print(f"      sal={e.get('salience', 0):.2f} | "
              f"{e.get('ts_iso', '?')}")
        print(f"      rationale: {e.get('rationale', '')[:90]}")
        print()
    return 0


def cmd_apply(args) -> int:
    if not args.yes:
        print("⚠️  needs --yes (apply 会真改 vocab)", file=sys.stderr)
        return 1
    entries = _load_entries()
    if args.idx < 0 or args.idx >= len(entries):
        print(f"ERR: idx {args.idx} out of range (0-{len(entries)-1})",
              file=sys.stderr)
        return 1
    e = entries[args.idx]
    if e.get('status') != 'pending':
        print(f"⚠️  entry {args.idx} status={e.get('status')} (非 pending)",
              file=sys.stderr)
        return 1
    vocab_file = e['vocab_file']
    vocab_path = os.path.join(_ROOT, 'memory_pool', vocab_file)
    if not os.path.exists(vocab_path):
        print(f"ERR: vocab file 不存在: {vocab_path}", file=sys.stderr)
        return 1
    # 读 → nested set → 写
    try:
        with open(vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        old = json.dumps(data, ensure_ascii=False)
        _set_nested(data, e['key_path'], _coerce(e['proposed_value']))
        with open(vocab_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        e['status'] = 'applied'
        e['applied_at'] = __import__('time').strftime('%Y-%m-%dT%H:%M:%S')
        _save_entries(entries)
        print(f"✅ applied: {vocab_file}:{e['key_path']} = "
              f"{e['proposed_value']}")
        print(f"   (old len={len(old)}, Sir 可 git diff 看改动)")
        return 0
    except Exception as ex:
        print(f"ERR apply: {ex}", file=sys.stderr)
        return 1


def cmd_reject(args) -> int:
    entries = _load_entries()
    if args.idx < 0 or args.idx >= len(entries):
        print(f"ERR: idx out of range", file=sys.stderr)
        return 1
    entries[args.idx]['status'] = 'rejected'
    _save_entries(entries)
    print(f"✅ rejected entry {args.idx}")
    return 0


def cmd_clear_done(_args) -> int:
    entries = _load_entries()
    kept = [e for e in entries if e.get('status') == 'pending']
    _save_entries(kept)
    print(f"✅ cleared {len(entries) - len(kept)} done entries, "
          f"{len(kept)} pending kept")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='vocab_adjustment_dump',
        description="思考脑 self-debug vocab 调整 review (SOUL Phase 5 P3)",
    )
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='列 pending propose')
    p_a = sub.add_parser('apply', help='Sir 拍板真改 vocab')
    p_a.add_argument('idx', type=int)
    p_a.add_argument('--yes', action='store_true')
    p_r = sub.add_parser('reject', help='Sir 否决')
    p_r.add_argument('idx', type=int)
    sub.add_parser('clear-done', help='清 applied/rejected 历史')
    args = parser.parse_args()
    return {
        'list': cmd_list, 'apply': cmd_apply, 'reject': cmd_reject,
        'clear-done': cmd_clear_done,
    }[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
