# -*- coding: utf-8 -*-
"""[P5-Gap4-followup-vocab / 2026-05-21 21:42] Concern Summon Vocab CLI Dump

让 Sir 一行命令查看 / 拍板 SOUL concern 召唤 keyword (准则 6.5).

用法:
    python scripts/concern_summon_dump.py                       # 列出 active
    python scripts/concern_summon_dump.py --all                 # 列全部 (含 rejected)
    python scripts/concern_summon_dump.py --add "在意" --category progress_zh
    python scripts/concern_summon_dump.py --activate <id>
    python scripts/concern_summon_dump.py --reject   <id>
    python scripts/concern_summon_dump.py --delete   <id>
    python scripts/concern_summon_dump.py --test "我担心啥"     # 测试某句是否触发

文件依赖:
  memory_pool/concern_summon_vocab.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'memory_pool',
    'concern_summon_vocab.json',
)


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {}, 'patterns': []}
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(VOCAB_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_list(show_all: bool = False) -> None:
    data = _load()
    patterns = data.get('patterns', [])
    print("=" * 70)
    print(f"[Concern Summon Vocab] {len(patterns)} pattern(s) in {VOCAB_PATH}")
    print("=" * 70)
    for p in patterns:
        state = p.get('state', '?')
        if not show_all and state != 'active':
            continue
        pid = p.get('id', '?')
        cat = p.get('category', '?')
        kws = p.get('keywords', [])
        note = p.get('note', '')
        print(f"  [{state:>8}] {pid}  cat={cat}")
        print(f"             keywords ({len(kws)}): {', '.join(kws[:8])}"
              f"{' ...' if len(kws) > 8 else ''}")
        if note:
            print(f"             note: {note}")
        print()


def cmd_add(text: str, category: str) -> None:
    data = _load()
    patterns = data.setdefault('patterns', [])
    new_id = f"sir_added_{int(time.time())}"
    patterns.append({
        'id': new_id,
        'category': category,
        'keywords': [text],
        'state': 'review',
        'source': 'sir_cli',
        'created_at': time.time(),
        'note': f'Sir CLI added {time.strftime("%Y-%m-%d %H:%M")}',
    })
    _save(data)
    print(f"[OK] added '{text}' (id={new_id}, state=review)")
    print("Sir 拍板:")
    print(f"  python scripts/concern_summon_dump.py --activate {new_id}")


def _change_state(pid: str, new_state: str) -> None:
    data = _load()
    for p in data.get('patterns', []):
        if p.get('id') == pid:
            old = p.get('state', '?')
            p['state'] = new_state
            _save(data)
            print(f"[OK] {pid}: {old} -> {new_state}")
            return
    print(f"[ERR] id '{pid}' 找不到")


def cmd_delete(pid: str) -> None:
    data = _load()
    patterns = data.get('patterns', [])
    new_patterns = [p for p in patterns if p.get('id') != pid]
    if len(new_patterns) == len(patterns):
        print(f"[ERR] id '{pid}' 找不到")
        return
    data['patterns'] = new_patterns
    _save(data)
    print(f"[OK] {pid} 已删除")


def cmd_test(text: str) -> None:
    try:
        from jarvis_concern_summon import is_summoned, load_active_keywords
    except ImportError as e:
        print(f"[ERR] import 失败: {e}")
        return
    result = is_summoned(text)
    print(f"input: '{text}'")
    print(f"is_summoned: {result}")
    if result:
        kws = load_active_keywords()
        hits = [kw for kw in kws if kw in text.lower()]
        print(f"matched keywords: {hits}")


def main() -> int:
    ap = argparse.ArgumentParser(description='Concern Summon Vocab CLI')
    ap.add_argument('--all', action='store_true', help='show all (incl rejected)')
    ap.add_argument('--add', help='add new keyword (text)')
    ap.add_argument('--category', default='custom', help='category for --add')
    ap.add_argument('--activate', help='activate by id')
    ap.add_argument('--reject', help='reject by id')
    ap.add_argument('--delete', help='delete by id')
    ap.add_argument('--test', help='test text against vocab')
    args = ap.parse_args()

    if args.add:
        cmd_add(args.add, args.category)
    elif args.activate:
        _change_state(args.activate, 'active')
    elif args.reject:
        _change_state(args.reject, 'rejected')
    elif args.delete:
        cmd_delete(args.delete)
    elif args.test:
        cmd_test(args.test)
    else:
        cmd_list(show_all=args.all)
    return 0


if __name__ == '__main__':
    sys.exit(main())
