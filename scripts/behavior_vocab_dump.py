#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.12 / 2026-05-18] behavior_vocab_dump.py — 履约验证 vocab 管理 CLI

Sir 12:53 反馈: "infer_expected_behavior 硬编码 in py 太蠢, 应该可加/改/删"
准则 6 治本: vocab 持久化到 memory_pool/behavior_inference_vocab.json, 此 CLI 管理.

用法:
  python scripts/behavior_vocab_dump.py                # list 所有 (含 review)
  python scripts/behavior_vocab_dump.py --active-only  # 只看 active
  python scripts/behavior_vocab_dump.py --review-list  # 只看待 Sir 审

  python scripts/behavior_vocab_dump.py --add ...      # 加新 pattern (见 --add 参数组)
  python scripts/behavior_vocab_dump.py --activate <id> # review → active
  python scripts/behavior_vocab_dump.py --reject <id>   # review → archived (软删)
  python scripts/behavior_vocab_dump.py --delete <id>   # 真删 (慎用)

  # --add 参数组示例:
  #   --add --id chrome_exit --keywords "看完视频,看完,watched movie" \\
  #         --kind process_exit --process-name "chrome.exe"
  #   --add --id new_idle --keywords "去洗澡,take a shower" \\
  #         --kind idle_min --threshold 20
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'behavior_inference_vocab.json')

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {'schema_version': 1, 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
                'patterns': []}
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
    patterns = data.get('patterns', [])
    if filter_state:
        patterns = [p for p in patterns if p.get('state') == filter_state]
    if not patterns:
        print(f"(无 {filter_state or '任何'} pattern)")
        return 0
    print(f"📚 behavior_inference_vocab.json — {len(patterns)} 条 {filter_state or '(all)'}")
    print("=" * 78)
    for p in patterns:
        state_emoji = {'active': '✅', 'review': '⏳',
                        'archived': '🗄️'}.get(p.get('state', '?'), '?')
        print(f"\n{state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}")
        kws = p.get('keywords', [])
        print(f"    keywords: {', '.join(kws[:8])}" +
              (f" ... +{len(kws)-8}" if len(kws) > 8 else ''))
        eb = p.get('expected_behavior', {})
        kind = eb.get('kind', '?')
        if kind == 'idle_min':
            print(f"    expected: idle >= {eb.get('threshold', '?')} min")
        elif kind == 'stm_contains':
            print(f"    expected: STM 含 {eb.get('kws', [])[:5]}")
        elif kind == 'process_exit':
            print(f"    expected: 进程 '{eb.get('name', '?')}' 退")
        else:
            print(f"    expected: {eb}")
        if p.get('note'):
            print(f"    note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.keywords or not args.kind:
        print("❌ --add 必须传 --id + --keywords + --kind")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"❌ id '{args.id}' 已存在 (用 --delete <id> 先删)")
        return 1
    eb: dict = {'kind': args.kind}
    if args.kind == 'idle_min':
        if args.threshold is None:
            print("❌ kind=idle_min 必须 --threshold <分钟>")
            return 1
        eb['threshold'] = float(args.threshold)
    elif args.kind == 'stm_contains':
        if not args.stm_kws:
            print("❌ kind=stm_contains 必须 --stm-kws 'X,Y,Z'")
            return 1
        eb['kws'] = [k.strip() for k in args.stm_kws.split(',') if k.strip()]
    elif args.kind == 'process_exit':
        if not args.process_name:
            print("❌ kind=process_exit 必须 --process-name 'chrome.exe'")
            return 1
        eb['name'] = args.process_name
    else:
        print(f"❌ 不支持的 kind: {args.kind} (支持: idle_min/stm_contains/process_exit)")
        return 1
    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    new_p = {
        'id': args.id,
        'keywords': keywords,
        'expected_behavior': eb,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' state={new_p['state']}")
    print(f"   keywords: {keywords}")
    print(f"   expected: {eb}")
    return 0


def cmd_state_change(pid: str, new_state: str) -> int:
    data = _load()
    for p in data.get('patterns', []):
        if p.get('id') == pid:
            old = p.get('state', '?')
            p['state'] = new_state
            _save(data)
            print(f"✅ pattern '{pid}': {old} → {new_state}")
            return 0
    print(f"❌ pattern id '{pid}' 不存在")
    return 1


def cmd_delete(pid: str) -> int:
    data = _load()
    before = len(data.get('patterns', []))
    data['patterns'] = [p for p in data.get('patterns', []) if p.get('id') != pid]
    if len(data['patterns']) == before:
        print(f"❌ pattern id '{pid}' 不存在")
        return 1
    _save(data)
    print(f"🗑️  真删 pattern '{pid}'")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--active-only', action='store_true', help='仅看 active')
    ap.add_argument('--review-list', action='store_true', help='仅看 review')
    ap.add_argument('--archived', action='store_true', help='仅看 archived')

    ap.add_argument('--add', action='store_true', help='加新 pattern')
    ap.add_argument('--id', help='pattern id (唯一)')
    ap.add_argument('--keywords', help='触发关键词 (逗号分隔)')
    ap.add_argument('--kind', choices=['idle_min', 'stm_contains', 'process_exit'],
                    help='验证方式')
    ap.add_argument('--threshold', type=float, help='idle_min 阈值 (分钟)')
    ap.add_argument('--stm-kws', help='stm_contains keyword list (逗号分隔)')
    ap.add_argument('--process-name', help='process_exit 进程名 (如 chrome.exe)')
    ap.add_argument('--state', choices=['active', 'review', 'archived'],
                    help='初始 state (默认 review, Sir 审后 --activate)')
    ap.add_argument('--note', help='备注')

    ap.add_argument('--activate', metavar='ID', help='review → active')
    ap.add_argument('--reject', metavar='ID', help='review/active → archived')
    ap.add_argument('--delete', metavar='ID', help='真删 (慎用)')

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
