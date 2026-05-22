# -*- coding: utf-8 -*-
"""[β.5.46-fix18 / 2026-05-22] project_hold_phrases vocab CLI 工具

Sir 11:39 真测痛点: 反复说"驾照放一放" 但 SmartNudge 仍 fire dormant_project.
治本: 持久化 vocab + IntentResolver 检测 → ProjectTimeline.hold_project().

准则 6 vocab CLI 范式 (类 scripts/concerns_dump.py):
  - list / list-active / list-review / list-rejected
  - add / activate / reject / delete

Usage:
  python scripts/project_hold_phrases_dump.py
  python scripts/project_hold_phrases_dump.py --add "搁置 (zh) 168h"
  python scripts/project_hold_phrases_dump.py --activate <id>
  python scripts/project_hold_phrases_dump.py --reject <id>
  python scripts/project_hold_phrases_dump.py --delete <id>

severity_delta 范围: 24-168h (1-7天).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List

VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'memory_pool', 'project_hold_phrases_vocab.json'
)


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'version': 'β.5.46-fix18', 'phrases': [],
                'review_queue': [], 'rejected_history': []}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'load failed: {e}', file=sys.stderr)
        return {}


def _save(data: dict) -> bool:
    try:
        with open(VOCAB_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f'save failed: {e}', file=sys.stderr)
        return False


def _list(filter_state: str = '') -> int:
    data = _load()
    phrases = data.get('phrases', []) or []
    if filter_state:
        phrases = [p for p in phrases if p.get('state') == filter_state]
    if not phrases:
        print('(无)')
        return 0
    print(f"共 {len(phrases)} 条")
    print('-' * 70)
    for p in phrases:
        st = p.get('state', '?')
        emoji = {'active': '✅', 'review': '🔥', 'archived': '📦', 'rejected': '❌'}.get(st, '?')
        lang = p.get('lang', '?')
        hrs = p.get('default_hours', '?')
        print(f"  {emoji} [{lang}] {p.get('phrase'):<30} {hrs}h  id={p.get('id')}")
    return 0


def _add(phrase: str, lang: str = 'zh', hours: int = 72,
          target_review: bool = True) -> int:
    data = _load()
    phrases = data.setdefault('phrases', [])
    new_id = phrase.lower().replace(' ', '_').replace("'", '')[:32] + '_' + str(int(time.time()) % 1000)
    item = {
        'id': new_id,
        'phrase': phrase,
        'lang': lang,
        'default_hours': hours,
        'state': 'review' if target_review else 'active',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'proposed_by': 'sir' if not target_review else 'sir_request_reflector',
    }
    phrases.append(item)
    if _save(data):
        print(f"✅ 已加 (id={new_id}, state={item['state']})")
        return 0
    return 2


def _set_state(target_id: str, new_state: str) -> int:
    data = _load()
    phrases = data.get('phrases', []) or []
    for p in phrases:
        if p.get('id') == target_id:
            old = p.get('state')
            p['state'] = new_state
            p[f'{new_state}_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            if _save(data):
                print(f"✅ {target_id}: {old} → {new_state}")
                return 0
            return 2
    print(f"❌ id 不存在: {target_id}", file=sys.stderr)
    return 1


def _delete(target_id: str) -> int:
    data = _load()
    phrases = data.get('phrases', []) or []
    new_phrases = [p for p in phrases if p.get('id') != target_id]
    if len(new_phrases) == len(phrases):
        print(f"❌ id 不存在: {target_id}", file=sys.stderr)
        return 1
    data['phrases'] = new_phrases
    if _save(data):
        print(f"🗑 已删 {target_id}")
        return 0
    return 2


def main() -> int:
    p = argparse.ArgumentParser(description='project_hold_phrases vocab CLI')
    p.add_argument('--list-active', action='store_true', help='list active only')
    p.add_argument('--list-review', action='store_true', help='list review only')
    p.add_argument('--list-rejected', action='store_true', help='list rejected only')
    p.add_argument('--add', type=str, default='', help='add new phrase')
    p.add_argument('--lang', type=str, default='zh', help='lang (zh/en) for --add')
    p.add_argument('--hours', type=int, default=72, help='default_hours for --add')
    p.add_argument('--activate', type=str, default='', help='activate by id')
    p.add_argument('--reject', type=str, default='', help='reject by id')
    p.add_argument('--archive', type=str, default='', help='archive by id')
    p.add_argument('--delete', type=str, default='', help='delete by id')
    args = p.parse_args()

    if args.list_active:
        return _list('active')
    if args.list_review:
        return _list('review')
    if args.list_rejected:
        return _list('rejected')
    if args.add:
        return _add(args.add, lang=args.lang, hours=args.hours,
                     target_review=False)
    if args.activate:
        return _set_state(args.activate, 'active')
    if args.reject:
        return _set_state(args.reject, 'rejected')
    if args.archive:
        return _set_state(args.archive, 'archived')
    if args.delete:
        return _delete(args.delete)
    return _list()


if __name__ == '__main__':
    sys.exit(main())
