#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.3.0-vocab3 / 2026-05-18] audio_ducking_dump.py — sleep 静音目标 vocab CLI

Sir 14:00 实测痛点: WeChat 没真静音 + 进程名硬编码 'WeChat' 违准则 6.5.
治本: vocab → memory_pool/audio_ducking_targets.json + 此 CLI 管理.

用法:
  python scripts/audio_ducking_dump.py                 # list 所有
  python scripts/audio_ducking_dump.py --active-only   # 只看 sleep 时会静音的
  python scripts/audio_ducking_dump.py --review-list   # 待 Sir 决定

  python scripts/audio_ducking_dump.py --add --id zoom \\
        --process-name "Zoom"        # 加 Zoom 到 review
  python scripts/audio_ducking_dump.py --activate <id>
  python scripts/audio_ducking_dump.py --reject <id>
  python scripts/audio_ducking_dump.py --delete <id>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'audio_ducking_targets.json')

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {'schema_version': 1,
                            'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
                'targets': []}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 读 vocab 失败: {e}")
        sys.exit(1)


def _save(data: dict) -> None:
    data.setdefault('_meta', {})['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, VOCAB_PATH)


def cmd_list(filter_state: str = '') -> int:
    data = _load()
    targets = data.get('targets', [])
    if filter_state:
        targets = [t for t in targets if t.get('state') == filter_state]
    if not targets:
        print(f"(无 {filter_state or '任何'} target)")
        return 0
    print(f"🔇 audio_ducking_targets.json — {len(targets)} 条 {filter_state or '(all)'}")
    print("=" * 78)
    for t in targets:
        state_emoji = {'active': '✅', 'review': '⏳',
                        'archived': '🗄️'}.get(t.get('state', '?'), '?')
        print(f"\n{state_emoji} [{t.get('state', '?'):8s}] {t.get('id', '?')}")
        print(f"    process_name: {t.get('process_name', '?')}")
        if t.get('note'):
            print(f"    note: {t['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.process_name:
        print("❌ --add 必须传 --id + --process-name")
        return 1
    data = _load()
    targets = data.setdefault('targets', [])
    if any(t.get('id') == args.id for t in targets):
        print(f"❌ id '{args.id}' 已存在")
        return 1
    new_t = {
        'id': args.id,
        'process_name': args.process_name,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    targets.append(new_t)
    _save(data)
    print(f"✅ 加入 target '{args.id}' state={new_t['state']} "
          f"process={args.process_name}")
    return 0


def cmd_state_change(tid: str, new_state: str) -> int:
    data = _load()
    for t in data.get('targets', []):
        if t.get('id') == tid:
            old = t.get('state', '?')
            t['state'] = new_state
            _save(data)
            print(f"✅ target '{tid}': {old} → {new_state}")
            return 0
    print(f"❌ target id '{tid}' 不存在")
    return 1


def cmd_delete(tid: str) -> int:
    data = _load()
    before = len(data.get('targets', []))
    data['targets'] = [t for t in data.get('targets', []) if t.get('id') != tid]
    if len(data['targets']) == before:
        print(f"❌ target id '{tid}' 不存在")
        return 1
    _save(data)
    print(f"🗑️  真删 target '{tid}'")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--active-only', action='store_true', help='仅看 active')
    ap.add_argument('--review-list', action='store_true', help='仅看 review')
    ap.add_argument('--archived', action='store_true', help='仅看 archived')

    ap.add_argument('--add', action='store_true', help='加新 target')
    ap.add_argument('--id', help='target id (唯一)')
    ap.add_argument('--process-name', help='进程名 (fuzzy match)')
    ap.add_argument('--state', choices=['active', 'review', 'archived'],
                    help='初始 state (默认 review)')
    ap.add_argument('--note', help='备注')

    ap.add_argument('--activate', metavar='ID', help='review → active')
    ap.add_argument('--reject', metavar='ID', help='→ archived')
    ap.add_argument('--delete', metavar='ID', help='真删')

    args = ap.parse_args()

    if args.activate:
        return cmd_state_change(args.activate, 'active')
    if args.reject:
        return cmd_state_change(args.reject, 'archived')
    if args.delete:
        return cmd_delete(args.delete)
    if args.add:
        return cmd_add(args)

    if args.review_list:
        return cmd_list('review')
    if args.active_only:
        return cmd_list('active')
    if args.archived:
        return cmd_list('archived')
    return cmd_list('')


if __name__ == '__main__':
    sys.exit(main())
