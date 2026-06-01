# -*- coding: utf-8 -*-
"""[Reshape 准则 8 / 2026-05-24] Habit progress vocab CLI.

管 memory_pool/habit_progress_vocab.json — habit_progress_routing directive 触发 vocab.

用法:
  python scripts/habit_progress_vocab_dump.py                       # 列全 vocab
  python scripts/habit_progress_vocab_dump.py --test '喝了三杯水'   # 测命中
  python scripts/habit_progress_vocab_dump.py --add-zh '骑车了'     # 加 ZH
  python scripts/habit_progress_vocab_dump.py --add-en 'biked'      # 加 EN
  python scripts/habit_progress_vocab_dump.py --remove-zh '骑车了'  # 删 ZH
  python scripts/habit_progress_vocab_dump.py --json                # 机读
"""
from __future__ import annotations

import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'habit_progress_vocab.json')


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save(data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
        tmp = VOCAB_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, VOCAB_PATH)
        return True
    except Exception as e:
        print(f'❌ save fail: {e}')
        return False


def _append_history(data: dict, action: str, value: str):
    hist = data.get('_history') or []
    hist.append({
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'marker': 'CLI',
        'reason': f'{action}: {value}',
    })
    data['_history'] = hist[-20:]


def main() -> int:
    p = argparse.ArgumentParser(description='Habit progress vocab CLI')
    p.add_argument('--test', help='测试某句是否命中')
    p.add_argument('--add-zh', help='加 ZH keyword')
    p.add_argument('--add-en', help='加 EN keyword')
    p.add_argument('--remove-zh', help='删 ZH keyword')
    p.add_argument('--remove-en', help='删 EN keyword')
    p.add_argument('--json', action='store_true', help='机读')
    args = p.parse_args()

    data = _load()

    # mutation ops
    mutated = False
    if args.add_zh:
        kws = list(data.get('zh_keywords') or [])
        if args.add_zh not in kws:
            kws.append(args.add_zh)
            data['zh_keywords'] = kws
            _append_history(data, 'add_zh', args.add_zh)
            mutated = True
            print(f"✅ added zh keyword: {args.add_zh!r}")
        else:
            print(f"ℹ️ already exists: {args.add_zh!r}")
    if args.add_en:
        kws = list(data.get('en_keywords') or [])
        if args.add_en not in kws:
            kws.append(args.add_en)
            data['en_keywords'] = kws
            _append_history(data, 'add_en', args.add_en)
            mutated = True
            print(f"✅ added en keyword: {args.add_en!r}")
        else:
            print(f"ℹ️ already exists: {args.add_en!r}")
    if args.remove_zh:
        kws = list(data.get('zh_keywords') or [])
        if args.remove_zh in kws:
            kws.remove(args.remove_zh)
            data['zh_keywords'] = kws
            _append_history(data, 'remove_zh', args.remove_zh)
            mutated = True
            print(f"❌ removed zh keyword: {args.remove_zh!r}")
        else:
            print(f"ℹ️ not found: {args.remove_zh!r}")
    if args.remove_en:
        kws = list(data.get('en_keywords') or [])
        if args.remove_en in kws:
            kws.remove(args.remove_en)
            data['en_keywords'] = kws
            _append_history(data, 'remove_en', args.remove_en)
            mutated = True
            print(f"❌ removed en keyword: {args.remove_en!r}")
        else:
            print(f"ℹ️ not found: {args.remove_en!r}")

    if mutated:
        _save(data)
        return 0

    # test mode
    if args.test:
        text = args.test.lower()
        zh_kw = data.get('zh_keywords') or []
        en_kw = data.get('en_keywords') or []
        hits = []
        for k in zh_kw:
            if k in text:
                hits.append(('zh', k))
        for k in en_kw:
            if k in text:
                hits.append(('en', k))
        print(f"\n测试: {args.test!r}")
        if hits:
            print(f"✅ 命中 ({len(hits)}):")
            for lang, k in hits:
                print(f"  - [{lang}] {k!r}")
            print(f"\n→ habit_progress_routing directive WILL fire.")
        else:
            print(f"❌ 不命中. directive NOT fire.")
            print(f"  若该 fire, 用 --add-zh / --add-en 加进 vocab.")
        return 0

    # default: dump
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print('=' * 78)
    print('  Habit Progress Vocab')
    print('=' * 78)
    zh = data.get('zh_keywords') or []
    en = data.get('en_keywords') or []
    print(f"\n  ZH keywords ({len(zh)}):")
    for k in zh:
        print(f"    - {k!r}")
    print(f"\n  EN keywords ({len(en)}):")
    for k in en:
        print(f"    - {k!r}")
    hints = data.get('concern_id_hints') or {}
    if hints:
        print(f"\n  Concern ID hints:")
        for k, v in hints.items():
            print(f"    {k:<30} → {v}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
