#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[β.5.36-E / 2026-05-20] intent_map_dump.py — Intent-to-tool mapping CLI

Sir 2026-05-20 10:46 实测 BUG 3: 工具名泄漏 ("I can run process_hands.get_top_cpu...").
根因: skill_registry.to_prompt_block 直接把工具名给 LLM + 让 LLM "MUST reference by name".

β.5.36-E 修法: intent-tool 解耦 — LLM 输出 <TOOL_CALL>{"intent": "check_top_cpu"},
intent_router 后端翻成工具名执行. LLM prompt 只看 intent (semantic), 不见工具名.

准则 6: vocab 持久化到 memory_pool/intent_to_tool_map.json, 此 CLI 管理.
doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md

用法:
  python scripts/intent_map_dump.py                  # list 全部 (含 review)
  python scripts/intent_map_dump.py --active-only    # 仅 active
  python scripts/intent_map_dump.py --review-list    # 仅待 Sir 审

  python scripts/intent_map_dump.py --add <id> --tool <full_tool_name> \\
         --hint "X" [--phrases-en "a,b"] [--phrases-zh "c,d"] [--danger safe/risky/dangerous]
  python scripts/intent_map_dump.py --activate <id>
  python scripts/intent_map_dump.py --reject <id>
  python scripts/intent_map_dump.py --deactivate <id>
  python scripts/intent_map_dump.py --delete <id>
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'intent_to_tool_map.json')

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {
            '_meta': {
                'schema_version': 1,
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            },
            'intents': [],
            'review_queue': [],
            'rejected_history': [],
        }
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERR] read vocab failed: {e}")
        sys.exit(1)


def _save(data: dict) -> None:
    data.setdefault('_meta', {})['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, VOCAB_PATH)


def _find(data: dict, intent_id: str) -> tuple:
    for i, c in enumerate(data.get('intents', [])):
        if c.get('id') == intent_id:
            return 'intent', i, c
    for i, c in enumerate(data.get('review_queue', [])):
        if c.get('id') == intent_id:
            return 'review', i, c
    return None, -1, None


def cmd_list(filter_state: str = '') -> int:
    data = _load()
    intents = data.get('intents', [])
    review_queue = data.get('review_queue', [])

    if filter_state == 'review':
        items = [(c, 'review') for c in review_queue]
    elif filter_state == 'active':
        items = [(c, 'intent') for c in intents if c.get('state', 'active') == 'active']
    else:
        items = [(c, 'intent') for c in intents] + [(c, 'review') for c in review_queue]

    if not items:
        print(f"(no {filter_state or 'any'} intents)")
        return 0

    print(f"intent_to_tool_map.json - {len(items)} intents {filter_state or '(all)'}")
    print("=" * 78)
    for c, src in items:
        state = c.get('state', 'active')
        emoji = {'active': '[OK]', 'review': '[REV]',
                 'archived': '[ARC]'}.get(state, '[?]')
        danger = c.get('dangerous_flag', '?')
        print(f"\n{emoji} [{state:8s}] [{danger:9s}] {c.get('id', '?')}  (src={src})")
        print(f"    tool: {c.get('tool', '?')}")
        if c.get('semantic_hint'):
            print(f"    hint: {c['semantic_hint']}")
        pe = c.get('human_phrases_en', [])
        if pe:
            print(f"    en  : {', '.join(pe[:5])}" + (f" ... +{len(pe)-5}" if len(pe) > 5 else ''))
        pz = c.get('human_phrases_zh', [])
        if pz:
            print(f"    zh  : {', '.join(pz[:5])}" + (f" ... +{len(pz)-5}" if len(pz) > 5 else ''))
        if c.get('source'):
            print(f"    src : {c['source']}")
    print()
    return 0


def cmd_add(args) -> int:
    if not args.add or not args.tool:
        print("[ERR] --add <id> + --tool <full_tool_name> required")
        return 1
    data = _load()
    iid = args.add
    kind, _, existing = _find(data, iid)
    if existing is not None:
        print(f"[ERR] id '{iid}' already exists in {kind}")
        return 1
    danger = (args.danger or 'safe').lower()
    if danger not in ('safe', 'risky', 'dangerous'):
        print(f"[ERR] --danger must be safe/risky/dangerous, got {danger}")
        return 1
    pen = [s.strip() for s in (args.phrases_en or '').split(',') if s.strip()]
    pzh = [s.strip() for s in (args.phrases_zh or '').split(',') if s.strip()]
    item = {
        'id': iid,
        'state': 'active',
        'tool': args.tool,
        'semantic_hint': args.hint or f"Sir intent: {iid}",
        'human_phrases_en': pen,
        'human_phrases_zh': pzh,
        'dangerous_flag': danger,
        'source': args.source or f'manual add @ {time.strftime("%Y-%m-%dT%H:%M:%S")}',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    data.setdefault('intents', []).append(item)
    _save(data)
    print(f"[OK] added intent '{iid}' → tool '{args.tool}' (danger={danger}, active)")
    return 0


def cmd_activate(intent_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, intent_id)
    if item is None:
        print(f"[ERR] '{intent_id}' not found")
        return 1
    if kind == 'review':
        item['state'] = 'active'
        item['activated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        data['review_queue'].pop(idx)
        data.setdefault('intents', []).append(item)
        _save(data)
        print(f"[OK] '{intent_id}' moved from review_queue to active intents")
    else:
        item['state'] = 'active'
        _save(data)
        print(f"[OK] '{intent_id}' state -> active")
    return 0


def cmd_reject(intent_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, intent_id)
    if item is None:
        print(f"[ERR] '{intent_id}' not found")
        return 1
    if kind != 'review':
        print(f"[ERR] '{intent_id}' not in review_queue")
        return 1
    item['state'] = 'rejected'
    item['rejected_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    data['review_queue'].pop(idx)
    data.setdefault('rejected_history', []).append(item)
    _save(data)
    print(f"[OK] '{intent_id}' moved from review_queue to rejected_history")
    return 0


def cmd_deactivate(intent_id: str) -> int:
    data = _load()
    kind, _, item = _find(data, intent_id)
    if item is None:
        print(f"[ERR] '{intent_id}' not found")
        return 1
    if kind != 'intent':
        print(f"[ERR] '{intent_id}' not active")
        return 1
    item['state'] = 'archived'
    item['archived_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _save(data)
    print(f"[OK] '{intent_id}' state -> archived")
    return 0


def cmd_delete(intent_id: str) -> int:
    data = _load()
    kind, idx, item = _find(data, intent_id)
    if item is None:
        print(f"[ERR] '{intent_id}' not found")
        return 1
    if kind == 'intent':
        data['intents'].pop(idx)
    elif kind == 'review':
        data['review_queue'].pop(idx)
    _save(data)
    print(f"[OK] '{intent_id}' DELETED from {kind}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog='intent_map_dump',
        description='Intent-to-tool mapping CLI (β.5.36-E)',
    )
    p.add_argument('--active-only', action='store_true')
    p.add_argument('--review-list', action='store_true')

    p.add_argument('--add', metavar='ID', help='add new intent id')
    p.add_argument('--tool', metavar='FULL_TOOL_NAME',
                   help='full tool name (e.g. process_hands.get_top_cpu)')
    p.add_argument('--hint', metavar='STR', help='semantic_hint for LLM')
    p.add_argument('--phrases-en', metavar='CSV', help='comma-separated english phrases')
    p.add_argument('--phrases-zh', metavar='CSV', help='comma-separated chinese phrases')
    p.add_argument('--danger', metavar='LEVEL', help='safe|risky|dangerous (default safe)')
    p.add_argument('--source', metavar='STR')

    p.add_argument('--activate', metavar='ID')
    p.add_argument('--reject', metavar='ID')
    p.add_argument('--deactivate', metavar='ID')
    p.add_argument('--delete', metavar='ID')

    args = p.parse_args(argv)

    if args.add:
        return cmd_add(args)
    if args.activate:
        return cmd_activate(args.activate)
    if args.reject:
        return cmd_reject(args.reject)
    if args.deactivate:
        return cmd_deactivate(args.deactivate)
    if args.delete:
        return cmd_delete(args.delete)

    if args.active_only:
        return cmd_list('active')
    if args.review_list:
        return cmd_list('review')
    return cmd_list()


if __name__ == '__main__':
    sys.exit(main())
