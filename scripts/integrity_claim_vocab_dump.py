#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P5-IntegrityWatcher / 2026-05-21 14:35] IntegrityWatcher vocab CLI

Sir 准则 6 — vocab 持久化 + CLI manage.
Sir 14:30 设计: 3 层 waterfall vocab + LLM, vocab 主路径.

用法:
  # vocab
  python scripts/integrity_claim_vocab_dump.py --list
  python scripts/integrity_claim_vocab_dump.py --list-type reminder
  python scripts/integrity_claim_vocab_dump.py --add reminder --pattern '(?:set|added).*timer' --lang en
  python scripts/integrity_claim_vocab_dump.py --deactivate reminder

  # suspicious keyword
  python scripts/integrity_claim_vocab_dump.py --kw-list
  python scripts/integrity_claim_vocab_dump.py --kw-add saved --lang en
  python scripts/integrity_claim_vocab_dump.py --kw-remove 已 --lang zh

  # stats
  python scripts/integrity_claim_vocab_dump.py --stats
  python scripts/integrity_claim_vocab_dump.py --watch-list

  # llm judge stats (Layer 3)
  python scripts/integrity_claim_vocab_dump.py --llm-stats
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'integrity_claim_vocab.json')
KW_PATH = os.path.join(ROOT, 'memory_pool', 'integrity_suspicious_kw.json')


def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        print(f'(no vocab file: {VOCAB_PATH})')
        return {}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'load fail: {e}')
        return {}


def _save_vocab(data: dict) -> None:
    data.setdefault('_meta', {})
    data['_meta']['updated_at'] = time.time()
    data['_meta']['updated_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def _load_kw() -> dict:
    if not os.path.exists(KW_PATH):
        return {}
    try:
        with open(KW_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_kw(data: dict) -> None:
    data.setdefault('_meta', {})
    data['_meta']['updated_at'] = time.time()
    data['_meta']['updated_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
    tmp = KW_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, KW_PATH)


def cmd_list(args) -> None:
    data = _load_vocab()
    patterns = (data.get('patterns') or {})
    if not patterns:
        print('(no patterns)')
        return
    filter_type = (args.list_type or '').strip().lower()
    print(f"\n=== IntegrityWatcher Claim Vocab ({len(patterns)} types) ===\n")
    for ctype, entry in patterns.items():
        if filter_type and ctype != filter_type:
            continue
        state = entry.get('state', '?')
        target = entry.get('default_target', '?')
        en_n = len(entry.get('en_patterns') or [])
        zh_n = len(entry.get('zh_patterns') or [])
        print(f"  [{state:8s}] {ctype:12s} default_target={target} (en={en_n}, zh={zh_n})")
        if args.verbose:
            for i, p in enumerate(entry.get('en_patterns') or []):
                print(f"    en[{i}]: {p[:100]}")
            for i, p in enumerate(entry.get('zh_patterns') or []):
                print(f"    zh[{i}]: {p[:80]}")


def cmd_add(args) -> None:
    if not args.add or not args.pattern:
        print('--add <claim_type> --pattern <regex> [--lang en|zh] required')
        return
    ctype = args.add.strip().lower()
    pat = args.pattern.strip()
    lang = (args.lang or 'en').strip().lower()
    if lang not in ('en', 'zh'):
        print('--lang must be en or zh')
        return
    # Try compile
    try:
        re.compile(pat)
    except re.error as e:
        print(f'❌ bad regex: {e}')
        return
    data = _load_vocab()
    patterns = data.setdefault('patterns', {})
    entry = patterns.setdefault(ctype, {
        'claim_label': ctype,
        'default_target': ctype,
        'en_patterns': [],
        'zh_patterns': [],
        'state': 'active',
        'added_at': time.time(),
        'added_by': 'sir_cli',
    })
    key = 'en_patterns' if lang == 'en' else 'zh_patterns'
    if pat in entry[key]:
        print(f'⏭ pattern already exists in {ctype}.{key}')
        return
    entry[key].append(pat)
    _save_vocab(data)
    print(f"✅ added {lang} pattern to {ctype}: {pat[:80]}")


def cmd_deactivate(args) -> None:
    ctype = (args.deactivate or '').strip().lower()
    data = _load_vocab()
    patterns = data.get('patterns') or {}
    if ctype not in patterns:
        print(f'❌ no claim_type {ctype}')
        return
    patterns[ctype]['state'] = 'inactive'
    _save_vocab(data)
    print(f'✅ {ctype} deactivated')


def cmd_kw_list(args) -> None:
    data = _load_kw()
    en = data.get('keywords_en') or []
    zh = data.get('keywords_zh') or []
    print(f"\n=== Suspicious Keywords ({len(en)} en + {len(zh)} zh) ===\n")
    print(f"  EN: {', '.join(en)}")
    print(f"  ZH: {', '.join(zh)}")


def cmd_kw_add(args) -> None:
    kw = (args.kw_add or '').strip()
    lang = (args.lang or 'en').strip().lower()
    if not kw or lang not in ('en', 'zh'):
        print('--kw-add <word> [--lang en|zh] required')
        return
    data = _load_kw()
    key = 'keywords_en' if lang == 'en' else 'keywords_zh'
    arr = data.setdefault(key, [])
    if kw in arr:
        print(f'⏭ already in {key}: {kw}')
        return
    arr.append(kw)
    _save_kw(data)
    print(f'✅ added {lang} keyword: {kw}')


def cmd_kw_remove(args) -> None:
    kw = (args.kw_remove or '').strip()
    lang = (args.lang or 'en').strip().lower()
    data = _load_kw()
    key = 'keywords_en' if lang == 'en' else 'keywords_zh'
    arr = data.get(key) or []
    if kw not in arr:
        print(f'❌ not in {key}: {kw}')
        return
    arr.remove(kw)
    _save_kw(data)
    print(f'✅ removed {lang} keyword: {kw}')


def cmd_stats(args) -> None:
    try:
        from jarvis_integrity_watcher import get_stats
        s = get_stats()
        if not s:
            print('(stats unavailable, watcher not yet initialized)')
            return
        print('\n=== IntegrityWatcher Stats ===')
        for k, v in s.items():
            print(f'  {k}: {v}')
    except Exception as e:
        print(f'load stats fail: {e}')


def cmd_watch_list(args) -> None:
    try:
        from jarvis_integrity_watcher import get_default_store
        store = get_default_store()
        items = store.all_items()
        if not items:
            print('(no claims in watch list)')
            return
        print(f'\n=== Watch List ({len(items)} claims) ===\n')
        for c in items[:50]:
            age_s = c.age_s()
            age_str = f'{int(age_s/60)}m' if age_s > 60 else f'{int(age_s)}s'
            print(
                f"  [{c.status:13s}] {c.claim_type:10s} {c.id[:8]} "
                f"target='{c.extracted_target[:30]}' age={age_str} retries={c.retries}"
            )
    except Exception as e:
        print(f'load watch list fail: {e}')


def cmd_llm_stats(args) -> None:
    try:
        from jarvis_integrity_watcher import get_default_llm_judge
        j = get_default_llm_judge()
        print('\n=== Layer 3 LLM Judge Stats ===')
        print(f"  available: {j.is_available()}")
        for k, v in j.stats().items():
            print(f'  {k}: {v}')
    except Exception as e:
        print(f'load llm stats fail: {e}')


def main() -> int:
    p = argparse.ArgumentParser(description='Jarvis IntegrityWatcher vocab CLI')
    p.add_argument('--list', action='store_true', help='list all claim type vocab')
    p.add_argument('--list-type', type=str, default='', help='filter list by claim_type')
    p.add_argument('--verbose', '-v', action='store_true', help='show pattern details')
    p.add_argument('--add', type=str, default='', metavar='CLAIM_TYPE',
                    help='add pattern to claim_type (use --pattern + --lang)')
    p.add_argument('--pattern', type=str, default='', help='regex pattern')
    p.add_argument('--lang', type=str, default='en', help='en|zh')
    p.add_argument('--deactivate', type=str, default='', metavar='CLAIM_TYPE',
                    help='deactivate claim_type (vocab keeps but not compiled)')
    p.add_argument('--kw-list', action='store_true', help='list suspicious keywords')
    p.add_argument('--kw-add', type=str, default='', help='add suspicious keyword')
    p.add_argument('--kw-remove', type=str, default='', help='remove suspicious keyword')
    p.add_argument('--stats', action='store_true', help='watcher stats')
    p.add_argument('--watch-list', action='store_true', help='current watch list')
    p.add_argument('--llm-stats', action='store_true', help='Layer 3 LLM judge stats')
    args = p.parse_args()

    if args.list or args.list_type:
        cmd_list(args)
    elif args.add:
        cmd_add(args)
    elif args.deactivate:
        cmd_deactivate(args)
    elif args.kw_list:
        cmd_kw_list(args)
    elif args.kw_add:
        cmd_kw_add(args)
    elif args.kw_remove:
        cmd_kw_remove(args)
    elif args.stats:
        cmd_stats(args)
    elif args.watch_list:
        cmd_watch_list(args)
    elif args.llm_stats:
        cmd_llm_stats(args)
    else:
        p.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
