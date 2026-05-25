# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 20:31 真测追根 准则 6.5] Priority Correction Vocab CLI Dump.

让 Sir 一行命令查看 / 加 / 拍板 ConcernFeedback 看的 priority correction phrase
(让主脑识别 "面试才是最重要" 类纠正信号 → 强 severity 推升 / 推降).

Sir 真理 (jarvis_20260525_200517.log Turn 4): "我说一次, 你应该学会, 权重应该
被我回应动态变化". 此 vocab 是关键学习机制 — Sir 加 phrase 不需改源码即生效.

用法:
    python scripts/priority_correction_dump.py                       # 列 active
    python scripts/priority_correction_dump.py --all                 # 列全部
    python scripts/priority_correction_dump.py --add "X 才算 priority" --category priority_correction
    python scripts/priority_correction_dump.py --activate <id>
    python scripts/priority_correction_dump.py --reject   <id>
    python scripts/priority_correction_dump.py --delete   <id>
    python scripts/priority_correction_dump.py --test "其实是面试"   # 测某句是否命中

文件依赖:
  memory_pool/priority_correction_vocab.json
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
    'priority_correction_vocab.json',
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
    print(f"[Priority Correction Vocab] {len(patterns)} pattern(s)")
    print(f"  path: {VOCAB_PATH}")
    print("=" * 70)
    for p in patterns:
        state = p.get('state', '?')
        if not show_all and state != 'active':
            continue
        pid = p.get('id', '?')
        cat = p.get('category', '?')
        phs = p.get('phrases', [])
        note = p.get('note', '')
        print(f"  [{state:>8}] {pid}  cat={cat}")
        print(f"             phrases ({len(phs)}): {', '.join(phs[:6])}"
              f"{' ...' if len(phs) > 6 else ''}")
        if note:
            print(f"             note: {note[:80]}")
        print()


def cmd_add(text: str, category: str) -> None:
    data = _load()
    patterns = data.setdefault('patterns', [])
    new_id = f"sir_added_{int(time.time())}"
    patterns.append({
        'id': new_id,
        'category': category,
        'phrases': [text],
        'state': 'review',
        'source': 'sir_cli',
        'created_at': time.time(),
        'note': f'Sir CLI added {time.strftime("%Y-%m-%d %H:%M")}',
    })
    _save(data)
    print(f"[OK] added '{text}' (id={new_id}, state=review)")
    print("Sir 拍板:")
    print(f"  python scripts/priority_correction_dump.py --activate {new_id}")


def _change_state(pid: str, new_state: str) -> None:
    data = _load()
    for p in data.get('patterns', []):
        if p.get('id') == pid:
            old = p.get('state', '?')
            p['state'] = new_state
            _save(data)
            print(f"[OK] {pid}: {old} -> {new_state}")
            return
    print(f"[ERR] id '{pid}' not found")


def cmd_delete(pid: str) -> None:
    data = _load()
    patterns = data.get('patterns', [])
    new_patterns = [p for p in patterns if p.get('id') != pid]
    if len(new_patterns) == len(patterns):
        print(f"[ERR] id '{pid}' not found")
        return
    data['patterns'] = new_patterns
    _save(data)
    print(f"[OK] {pid} deleted")


def cmd_test(text: str) -> None:
    """简易匹配测试: text 是否含 active phrase."""
    data = _load()
    text_lower = text.lower()
    hits = []
    for p in data.get('patterns', []):
        if p.get('state') != 'active':
            continue
        for ph in p.get('phrases', []):
            if ph.lower() in text_lower:
                hits.append((p.get('id'), p.get('category'), ph))
    print(f"input: '{text}'")
    if hits:
        print(f"matched ({len(hits)}):")
        for pid, cat, ph in hits:
            print(f"  - [{cat}] '{ph}' (from {pid})")
    else:
        print("no match — Sir 这句不算 priority correction signal")


def main() -> int:
    ap = argparse.ArgumentParser(description='Priority Correction Vocab CLI')
    ap.add_argument('--all', action='store_true', help='show all (incl review/rejected)')
    ap.add_argument('--add', help='add new phrase (text)')
    ap.add_argument('--category', default='priority_correction',
                     help='category for --add (default: priority_correction)')
    ap.add_argument('--activate', help='activate by id')
    ap.add_argument('--reject', help='reject by id')
    ap.add_argument('--delete', help='delete by id')
    ap.add_argument('--test', help='test text against vocab (是否命中 priority correction)')
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
