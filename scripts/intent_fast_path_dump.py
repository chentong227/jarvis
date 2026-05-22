#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🆕 [P5-fix20-B1 / 2026-05-22] IntentResolver vocab fast-path CLI.

Sir 14:32 真测痛点: OpenRouter 全挂 + Google 池 429 → IntentResolver LLM
全 fail → 0 mutation → 嘴上说没真做. fast-path 在 LLM 之前 keyword 匹配,
高确定性场景 (e.g. "暂停 X 项目") 直达 tool 不走 LLM.

准则 6 vocab 持久化范式 — 持久化到 memory_pool/intent_fast_path_vocab.json,
CLI 让 Sir list / add / activate / reject / delete, 不动源码.

Usage:
  python scripts/intent_fast_path_dump.py --list
  python scripts/intent_fast_path_dump.py --list --inactive
  python scripts/intent_fast_path_dump.py --add "暂停" --tool tool_project_hold --lang zh
  python scripts/intent_fast_path_dump.py --activate "搁置"
  python scripts/intent_fast_path_dump.py --reject "shelve it"
  python scripts/intent_fast_path_dump.py --delete "暂停"
  python scripts/intent_fast_path_dump.py --review            # 看 L7 待 Sir 拍板
  python scripts/intent_fast_path_dump.py --test "我想先暂停那个 dashboard"  # dry-run 看命中
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'intent_fast_path_vocab.json')


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_doc': '', 'vocab': [], 'review_queue': []}
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def cmd_list(args) -> int:
    data = _load()
    vocab = data.get('vocab', [])
    if args.inactive:
        vocab = [v for v in vocab if not v.get('active')]
    elif not args.all:
        vocab = [v for v in vocab if v.get('active')]
    print(f"=== IntentResolver Fast-Path Vocab ({len(vocab)} items) ===")
    if not vocab:
        print(f"  (空)")
        return 0
    for v in vocab:
        active = '🟢' if v.get('active') else '⚫'
        phrase = v.get('phrase', '?')
        tool = v.get('tool_name', '?')
        lang = v.get('lang', '?')
        conf = v.get('confidence', '?')
        print(f"  {active} [{lang}] '{phrase}' → {tool}  (conf={conf})")
        if args.verbose:
            note = v.get('note', '')
            src = v.get('source', '?')
            added = v.get('added_at', '?')
            print(f"      src={src} added={added}{'  note: ' + note if note else ''}")
    return 0


def cmd_add(args) -> int:
    data = _load()
    vocab = data.setdefault('vocab', [])
    phrase = args.add.strip().lower()
    if not phrase:
        print(f"❌ phrase 不能空")
        return 1
    # 已存在?
    for v in vocab:
        if v.get('phrase', '').strip().lower() == phrase:
            print(f"⚠️ 已存在: {phrase} (使用 --activate 激活 / --delete 删后再加)")
            return 1
    new_entry = {
        'phrase': phrase,
        'tool_name': args.tool,
        'tool_args_template': {'sir_utterance': '{sir_utterance}'},
        'min_utterance_len': args.min_len or 4,
        'max_utterance_len': args.max_len or 60,
        'confidence': args.confidence or 0.85,
        'lang': args.lang or 'any',
        'active': True,
        'source': args.source or 'sir',
        'added_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'added_by': 'sir' if args.source != 'l7_reflector' else 'l7_reflector',
    }
    if args.note:
        new_entry['note'] = args.note
    vocab.append(new_entry)
    _save(data)
    print(f"✅ 已加: '{phrase}' → {args.tool} (lang={args.lang or 'any'})")
    return 0


def cmd_activate(args) -> int:
    data = _load()
    phrase = args.activate.strip().lower()
    for v in data.get('vocab', []):
        if v.get('phrase', '').strip().lower() == phrase:
            v['active'] = True
            v['activated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            _save(data)
            print(f"✅ 已激活: '{phrase}'")
            return 0
    print(f"❌ 未找到: '{phrase}'")
    return 1


def cmd_reject(args) -> int:
    data = _load()
    phrase = args.reject.strip().lower()
    for v in data.get('vocab', []):
        if v.get('phrase', '').strip().lower() == phrase:
            v['active'] = False
            v['rejected_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            _save(data)
            print(f"⚫ 已拒绝 (转 inactive): '{phrase}' (--activate 可恢复)")
            return 0
    print(f"❌ 未找到: '{phrase}'")
    return 1


def cmd_delete(args) -> int:
    data = _load()
    phrase = args.delete.strip().lower()
    vocab = data.get('vocab', [])
    new_vocab = [v for v in vocab if v.get('phrase', '').strip().lower() != phrase]
    if len(new_vocab) == len(vocab):
        print(f"❌ 未找到: '{phrase}'")
        return 1
    data['vocab'] = new_vocab
    _save(data)
    print(f"🗑️ 已删除: '{phrase}'")
    return 0


def cmd_review(args) -> int:
    """看 L7 reflector 待 Sir 拍板的 vocab proposal."""
    data = _load()
    queue = data.get('review_queue', [])
    print(f"=== Review Queue ({len(queue)} items) ===")
    if not queue:
        print(f"  (空 — L7 reflector 未 propose 任何新 vocab)")
        return 0
    for i, q in enumerate(queue):
        print(f"  [{i}] '{q.get('phrase')}' → {q.get('tool_name')} ({q.get('lang')})")
        print(f"      proposed_at={q.get('proposed_at', '?')}")
        print(f"      reason: {q.get('reason', '')}")
        print(f"      examples: {q.get('examples', [])[:3]}")
    print()
    print("Sir 拍板: --add 复制条进 vocab, 或忽略 (review 不影响线上).")
    return 0


def cmd_test(args) -> int:
    """dry-run 看一句话命中哪些 vocab."""
    data = _load()
    vocab = [v for v in data.get('vocab', []) if v.get('active')]
    utt = args.test.strip().lower()
    print(f"输入: '{args.test}' (lower='{utt}', len={len(utt)})")
    print(f"=== Active vocab matching ===")
    matched = []
    for v in vocab:
        phrase = v.get('phrase', '').lower()
        if not phrase:
            continue
        min_len = v.get('min_utterance_len', 0)
        max_len = v.get('max_utterance_len', 0)
        if len(utt) < min_len:
            continue
        if max_len > 0 and len(utt) > max_len:
            continue
        if phrase in utt:
            matched.append(v)
            print(f"  🟢 命中: '{phrase}' → {v.get('tool_name')}  conf={v.get('confidence')}")
    if not matched:
        print(f"  (无命中 — fast-path 不会触发, 走 LLM)")
        return 1
    print()
    print(f"→ fast-path 会调 {len(matched)} 个 tool: "
          f"{[m.get('tool_name') for m in matched]}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description='IntentResolver fast-path vocab CLI (P5-fix20-B1)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument('--list', action='store_true', help='列 active vocab')
    g.add_argument('--add', metavar='PHRASE', help='加新 vocab (要 --tool)')
    g.add_argument('--activate', metavar='PHRASE', help='激活 vocab')
    g.add_argument('--reject', metavar='PHRASE', help='转 inactive')
    g.add_argument('--delete', metavar='PHRASE', help='永久删除')
    g.add_argument('--review', action='store_true', help='看 L7 待审 queue')
    g.add_argument('--test', metavar='UTTERANCE', help='测一句话命中哪些 vocab')

    p.add_argument('--tool', help='--add 时 tool_name')
    p.add_argument('--lang', default=None, help='--add 时 lang (zh/en/any)')
    p.add_argument('--source', default='sir', help='--add 时 source')
    p.add_argument('--note', default='', help='--add 时备注')
    p.add_argument('--confidence', type=float, default=None, help='--add 时 confidence (0-1)')
    p.add_argument('--min-len', type=int, default=None, help='--add 时句长下限')
    p.add_argument('--max-len', type=int, default=None, help='--add 时句长上限')
    p.add_argument('--inactive', action='store_true', help='--list 时仅看 inactive')
    p.add_argument('--all', action='store_true', help='--list 时 active+inactive 全显示')
    p.add_argument('--verbose', '-v', action='store_true', help='--list 时详细')
    args = p.parse_args()

    # 默认 --list
    if not any([args.list, args.add, args.activate, args.reject, args.delete,
                args.review, args.test]):
        args.list = True

    if args.list:
        return cmd_list(args)
    if args.add:
        if not args.tool:
            print(f"❌ --add 需要 --tool <tool_name>")
            return 1
        return cmd_add(args)
    if args.activate:
        return cmd_activate(args)
    if args.reject:
        return cmd_reject(args)
    if args.delete:
        return cmd_delete(args)
    if args.review:
        return cmd_review(args)
    if args.test:
        return cmd_test(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
