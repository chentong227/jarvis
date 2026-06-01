#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P0+20-β.4.3.2 / 2026-05-18] evidence_req_dump.py — L2 Evidence Requirements CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.

schema:
  patterns[] = {id, claim_type, accepted_evidence_kinds[], state, source, note}
  claim_type ∈ {Past, Future, State, Recall, Social, Tool, Unknown}
  accepted_evidence_kinds[] ⊂ EVIDENCE_KINDS_CANONICAL (见 jarvis_evidence_requirements.py)
  state ∈ {active, review, archived}

用法:
  python scripts/evidence_req_dump.py
  python scripts/evidence_req_dump.py --active-only
  python scripts/evidence_req_dump.py --type Past
  python scripts/evidence_req_dump.py --add --id custom_X \\
        --claim-type Tool --evidence-kinds "tool_results_any,uncertainty_marker_nearby" \\
        --state review --note "Sir 加的"
  python scripts/evidence_req_dump.py --activate <id>
  python scripts/evidence_req_dump.py --reject <id>
  python scripts/evidence_req_dump.py --delete <id>
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
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'evidence_requirements.json')

CLAIM_TYPES_CANONICAL = ('Past', 'Future', 'State', 'Recall', 'Social',
                          'Tool', 'Unknown')
EVIDENCE_KINDS_CANONICAL = (
    'tool_results_success', 'tool_results_any', 'stm_match', 'ltm_match',
    'system_clock_within_2min', 'promise_log_recorded',
    'uncertainty_marker_nearby', 'none',
)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {'schema_version': 1,
                          'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
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


def _split_csv(s: str) -> list:
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def cmd_list(filter_state: str = '', filter_type: str = '') -> int:
    data = _load()
    patterns = data.get('patterns', [])
    if filter_state:
        patterns = [p for p in patterns if p.get('state') == filter_state]
    if filter_type:
        patterns = [p for p in patterns if p.get('claim_type') == filter_type]
    if not patterns:
        print(f"(无 {filter_state or '任何'} pattern" +
              (f", type={filter_type}" if filter_type else '') + ")")
        return 0
    print(f"📚 evidence_requirements.json — {len(patterns)} 条 "
          f"{filter_state or '(all)'}"
          + (f" / type={filter_type}" if filter_type else ''))
    print("=" * 78)
    by_type: dict = {}
    for p in patterns:
        by_type.setdefault(p.get('claim_type', '?'), []).append(p)
    for ct in sorted(by_type.keys()):
        print(f"\n🏷️  claim_type = {ct}")
        for p in by_type[ct]:
            state_emoji = {'active': '✅', 'review': '⏳',
                            'archived': '🗄️'}.get(p.get('state', '?'), '?')
            kinds = p.get('accepted_evidence_kinds', []) or []
            print(f"  {state_emoji} [{p.get('state', '?'):8s}] {p.get('id', '?')}"
                  f"   ({len(kinds)} evidence kind)")
            print(f"      kinds: {kinds}")
            if p.get('note'):
                print(f"      note: {p['note']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.id or not args.claim_type:
        print("❌ --add 必须传 --id + --claim-type")
        return 1
    if args.claim_type not in CLAIM_TYPES_CANONICAL:
        print(f"❌ --claim-type 必须是 {CLAIM_TYPES_CANONICAL}")
        return 1
    kinds = _split_csv(args.evidence_kinds or '')
    bad = [k for k in kinds if k not in EVIDENCE_KINDS_CANONICAL]
    if bad:
        print(f"❌ --evidence-kinds 含非法值: {bad}")
        print(f"   合法值: {EVIDENCE_KINDS_CANONICAL}")
        return 1
    data = _load()
    patterns = data.setdefault('patterns', [])
    if any(p.get('id') == args.id for p in patterns):
        print(f"❌ id '{args.id}' 已存在")
        return 1
    new_p = {
        'id': args.id,
        'claim_type': args.claim_type,
        'accepted_evidence_kinds': kinds,
        'state': args.state or 'review',
        'source': 'sir_added',
        'created_at': time.time(),
        'note': args.note or '',
    }
    patterns.append(new_p)
    _save(data)
    print(f"✅ 加入 pattern '{args.id}' type={args.claim_type} state={new_p['state']}")
    print(f"   evidence_kinds ({len(kinds)}): {kinds}")
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
    ap.add_argument('--active-only', action='store_true')
    ap.add_argument('--review-list', action='store_true')
    ap.add_argument('--archived', action='store_true')
    ap.add_argument('--type', dest='claim_type_filter',
                    help='仅看某 claim_type')
    ap.add_argument('--add', action='store_true')
    ap.add_argument('--id', help='pattern entry id (唯一)')
    ap.add_argument('--claim-type', dest='claim_type',
                    help=f'claim_type ∈ {CLAIM_TYPES_CANONICAL}')
    ap.add_argument('--evidence-kinds', dest='evidence_kinds',
                    help=f'evidence_kind 列表, 逗号分隔. 合法值: {EVIDENCE_KINDS_CANONICAL}')
    ap.add_argument('--state', choices=['active', 'review', 'archived'])
    ap.add_argument('--note')
    ap.add_argument('--activate', metavar='ID')
    ap.add_argument('--reject', metavar='ID')
    ap.add_argument('--delete', metavar='ID')
    args = ap.parse_args()
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
    return cmd_list(filter_state, args.claim_type_filter or '')


if __name__ == '__main__':
    sys.exit(main())
