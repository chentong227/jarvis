#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[fixD-claim-domain-scoped-verify / 2026-06-09] claim_domain_dump.py — L2.5 Claim Action-Domain vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.

schema:
  _meta.enforce: bool   — false=影子期 (live 走粗粒度, 域配对只 record); true=收紧
  _meta.etype_domain_map: {etype: domain}  — 右手 event→域 映射
  patterns[] = {id, domain, keywords[], state}  — 左手 claim→域 关键词
  domain ∈ {profile, concern, memory, device_action, promise}
  state ∈ {active, review, archived}

用法:
  python scripts/claim_domain_dump.py
  python scripts/claim_domain_dump.py --active-only
  python scripts/claim_domain_dump.py --domain profile
  python scripts/claim_domain_dump.py --add --id custom_X \\
        --domain device_action --keywords "toggled,切换" --state review
  python scripts/claim_domain_dump.py --activate <id>
  python scripts/claim_domain_dump.py --reject <id>
  python scripts/claim_domain_dump.py --delete <id>
  python scripts/claim_domain_dump.py --enforce on   # flip 收紧 (复核影子假阳率后)
  python scripts/claim_domain_dump.py --enforce off  # 回到影子期
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'claim_domain_vocab.json')

DOMAINS_CANONICAL = ('profile', 'concern', 'memory', 'device_action', 'promise')

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {'schema_version': 1, 'enforce': False,
                          'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
                'patterns': []}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"读 vocab 失败: {e}")
        sys.exit(1)


def _save(data: dict) -> None:
    data.setdefault('_meta', {})['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, VOCAB_PATH)


def _split_csv(s: str) -> list:
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def cmd_list(filter_state: str = '', filter_domain: str = '') -> int:
    data = _load()
    patterns = data.get('patterns', [])
    enforce = bool(data.get('_meta', {}).get('enforce', False))
    if filter_state:
        patterns = [p for p in patterns if p.get('state') == filter_state]
    if filter_domain:
        patterns = [p for p in patterns if p.get('domain') == filter_domain]
    print(f"claim_domain_vocab.json — enforce={enforce} "
          f"({'收紧' if enforce else '影子期'}) — {len(patterns)} 条 "
          f"{filter_state or '(all)'}"
          + (f" / domain={filter_domain}" if filter_domain else ''))
    print("=" * 78)
    emap = data.get('_meta', {}).get('etype_domain_map', {})
    print(f"etype→域 映射 ({len(emap)}): {emap}")
    print("-" * 78)
    by_dom: dict = {}
    for p in patterns:
        by_dom.setdefault(p.get('domain', '?'), []).append(p)
    for dom in sorted(by_dom.keys()):
        print(f"\n域 = {dom}")
        for p in by_dom[dom]:
            se = {'active': '[active]', 'review': '[review]',
                  'archived': '[archived]'}.get(p.get('state', '?'), '[?]')
            kws = p.get('keywords', []) or []
            print(f"  {se} {p.get('id', '?')}  ({len(kws)} keyword)")
            head = kws[:8]
            if head:
                print(f"      kw: {head}" + (f" ... +{len(kws)-8}" if len(kws) > 8 else ''))
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.domain:
        print("--add 必须传 --id + --domain")
        return 1
    if args.domain not in DOMAINS_CANONICAL:
        print(f"--domain 必须是 {DOMAINS_CANONICAL}, 你传 '{args.domain}'")
        return 1
    kws = _split_csv(args.keywords or '')
    if not kws:
        print("--keywords 至少给一个")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"id '{args.id}' 已存在")
        return 1
    new_p = {
        'id': args.id,
        'domain': args.domain,
        'keywords': kws,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"加入 pattern '{args.id}' state={new_p['state']} domain={args.domain}")
    print(f"   kw: {kws[:5]}  ({len(kws)} total)")
    return 0


def cmd_state_change(pid: str, new_state: str) -> int:
    data = _load()
    for p in data.get('patterns', []):
        if p.get('id') == pid:
            old = p.get('state', '?')
            p['state'] = new_state
            _save(data)
            print(f"pattern '{pid}': {old} → {new_state}")
            return 0
    print(f"pattern id '{pid}' 不存在")
    return 1


def cmd_delete(pid: str) -> int:
    data = _load()
    before = len(data.get('patterns', []))
    data['patterns'] = [p for p in data.get('patterns', []) if p.get('id') != pid]
    if len(data['patterns']) == before:
        print(f"pattern id '{pid}' 不存在")
        return 1
    _save(data)
    print(f"真删 pattern '{pid}'")
    return 0


def cmd_enforce(val: str) -> int:
    data = _load()
    new_val = (val.lower() == 'on')
    old = bool(data.get('_meta', {}).get('enforce', False))
    data.setdefault('_meta', {})['enforce'] = new_val
    _save(data)
    print(f"enforce: {old} → {new_val} "
          f"({'收紧 (域不匹配→unverified)' if new_val else '影子期 (live 走粗粒度)'})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--active-only', action='store_true')
    ap.add_argument('--review-list', action='store_true')
    ap.add_argument('--archived', action='store_true')
    ap.add_argument('--domain', dest='domain_filter_or_add',
                    help='list: 仅看某域 / add: 指定域')
    ap.add_argument('--add', action='store_true')
    ap.add_argument('--id', help='pattern entry id (唯一)')
    ap.add_argument('--keywords', help='keyword 列表, 逗号分隔')
    ap.add_argument('--state', choices=['active', 'review', 'archived'])
    ap.add_argument('--note')
    ap.add_argument('--activate', metavar='ID')
    ap.add_argument('--reject', metavar='ID')
    ap.add_argument('--delete', metavar='ID')
    ap.add_argument('--enforce', choices=['on', 'off'],
                    help='flip 影子期/收紧 (改 _meta.enforce, 零代码改)')
    args = ap.parse_args()
    # add 用 --domain 作目标域; list 也用 --domain 作过滤
    args.domain = args.domain_filter_or_add
    if args.enforce:
        return cmd_enforce(args.enforce)
    if args.activate:
        return cmd_state_change(args.activate, 'active')
    if args.reject:
        return cmd_state_change(args.reject, 'archived')
    if args.delete:
        return cmd_delete(args.delete)
    if args.add:
        return cmd_add(args)
    filter_state = ''
    if args.review_list:
        filter_state = 'review'
    elif args.active_only:
        filter_state = 'active'
    elif args.archived:
        filter_state = 'archived'
    return cmd_list(filter_state, args.domain if not args.add else '')


if __name__ == '__main__':
    sys.exit(main())
