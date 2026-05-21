# -*- coding: utf-8 -*-
"""[Gap-Z4 / β.5.46-fix9 / 2026-05-22 00:05] Vocab Dedup Lint 工具.

扫 memory_pool/*.json vocab 文件, 找重复 keyword. 只 report 不自动修, Sir 拍板.

== 痛点 ==

35 个 vocab JSON, 关键词难免重复. e.g.:
  - concern_summon_vocab.json    含 "what concerns"
  - forbidden_callback_vocab.json 含 "Regarding my previous"
  - severity_decay_vocab.json    含 ...

改一处其他不同步, 维护负担. 没 cross-link 工具.

== 治法 ==

CLI 工具扫 memory_pool/*.json:
  1. 提取每个 vocab 的 keywords (heuristic 找 list-of-string fields)
  2. 找重复 — 同 keyword 在 2+ vocab 文件中出现
  3. 输出 (keyword, [vocab_a, vocab_b, ...]) 报告
  4. Sir 看报告决定是否合并 / 重命名 / 留双份

不自动修 — 准则 7 (Sir 元否决) + 这种合并需要语义判断.

Usage:
    python scripts/vocab_dedup_lint.py             # 全扫报告
    python scripts/vocab_dedup_lint.py --keyword "Regarding my previous"  # 单 keyword 反查
    python scripts/vocab_dedup_lint.py --vocab concern_summon_vocab.json  # 单 vocab 详情
    python scripts/vocab_dedup_lint.py --threshold 3  # 仅看重复 >= 3 文件的
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Set

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
_VOCAB_DIR = os.path.join(_ROOT, 'memory_pool')


def _is_string(v) -> bool:
    return isinstance(v, str) and len(v.strip()) > 0


def _extract_keywords_from_obj(obj, keywords: Set[str], depth: int = 0) -> None:
    """递归提取 obj 中所有 string. 启发式 — 任何 list/dict-value 中的 string 都视为 keyword.

    跳过 _doc / _purpose / _history 等 meta 字段.
    """
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.startswith('_'):
                continue
            if _is_string(v):
                # 单 string field (e.g. {"id": "x"}) 不算 keyword 除非是 list 元素
                # 这里跳过 dict 单 string value, 仅 list/复合提取
                continue
            _extract_keywords_from_obj(v, keywords, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            if _is_string(item):
                # list of strings → keyword
                kw = item.strip()
                if 1 < len(kw) < 200:  # 过滤太长/太短
                    keywords.add(kw.lower())
            elif isinstance(item, (dict, list)):
                _extract_keywords_from_obj(item, keywords, depth + 1)


def scan_vocab_files() -> Dict[str, Set[str]]:
    """扫 memory_pool/*.json, 返 {filename: set(keywords)}."""
    result: Dict[str, Set[str]] = {}
    if not os.path.isdir(_VOCAB_DIR):
        print(f'[ERR] vocab dir not found: {_VOCAB_DIR}')
        sys.exit(1)
    for fname in sorted(os.listdir(_VOCAB_DIR)):
        if not fname.endswith('.json'):
            continue
        # 跳过 review queue / state / db
        if 'review' in fname or 'state' in fname:
            continue
        path = os.path.join(_VOCAB_DIR, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            kws: Set[str] = set()
            _extract_keywords_from_obj(data, kws)
            if kws:
                result[fname] = kws
        except Exception as e:
            print(f'[skip] {fname}: {e}')
    return result


def find_duplicates(vocab_data: Dict[str, Set[str]],
                    threshold: int = 2) -> Dict[str, List[str]]:
    """返 {keyword: [vocab_files]}, 仅含 >= threshold 个 vocab 中的 keyword."""
    kw_to_vocabs: Dict[str, List[str]] = defaultdict(list)
    for fname, kws in vocab_data.items():
        for kw in kws:
            kw_to_vocabs[kw].append(fname)
    return {
        kw: sorted(vfs)
        for kw, vfs in kw_to_vocabs.items()
        if len(vfs) >= threshold
    }


def cmd_report(threshold: int = 2):
    print(f'[Scanning] {_VOCAB_DIR}/*.json...')
    vocab_data = scan_vocab_files()
    print(f'   {len(vocab_data)} vocab files indexed')
    print(f'   {sum(len(kws) for kws in vocab_data.values())} total keyword occurrences')
    print()

    dups = find_duplicates(vocab_data, threshold=threshold)
    if not dups:
        print(f'[OK] No duplicates found (threshold={threshold})')
        return

    print(f'[!] Found {len(dups)} keyword(s) shared across >= {threshold} vocab files:')
    print('=' * 80)
    # sort by num shared (most shared first)
    sorted_dups = sorted(dups.items(), key=lambda x: -len(x[1]))
    for kw, vfs in sorted_dups[:50]:  # cap 50 to avoid screen flood
        print(f'  "{kw[:60]}" -> {len(vfs)} files: {", ".join(v[:30] for v in vfs)}')
    if len(sorted_dups) > 50:
        print(f'  ... ({len(sorted_dups) - 50} more, use --threshold higher to filter)')
    print('=' * 80)
    print('Sir decides: merge / rename / keep both. Re-run after edits.')


def cmd_keyword_lookup(keyword: str):
    """反查单 keyword 在哪些 vocab."""
    vocab_data = scan_vocab_files()
    kw_lower = keyword.lower().strip()
    found = []
    for fname, kws in vocab_data.items():
        for kw in kws:
            if kw_lower in kw or kw in kw_lower:
                found.append((fname, kw))
    if not found:
        print(f'No vocab contains "{keyword}"')
        return
    print(f'Found "{keyword}" in {len(found)} vocab entries:')
    for fname, kw in found:
        print(f'  {fname:<45s} | "{kw[:60]}"')


def cmd_vocab_detail(vocab_name: str):
    """看单 vocab 的所有 keyword."""
    path = os.path.join(_VOCAB_DIR, vocab_name)
    if not os.path.exists(path):
        print(f'[ERR] {path} not found')
        return
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    kws: Set[str] = set()
    _extract_keywords_from_obj(data, kws)
    print(f'[{vocab_name}] {len(kws)} keyword(s):')
    for kw in sorted(kws):
        print(f'  - "{kw[:80]}"')


def main():
    parser = argparse.ArgumentParser(description='Vocab Dedup Lint')
    parser.add_argument('--threshold', type=int, default=2,
                         help='min vocab files for keyword to be flagged (default 2)')
    parser.add_argument('--keyword', type=str, help='lookup single keyword')
    parser.add_argument('--vocab', type=str, help='show single vocab detail')
    args = parser.parse_args()

    if args.keyword:
        cmd_keyword_lookup(args.keyword)
    elif args.vocab:
        cmd_vocab_detail(args.vocab)
    else:
        cmd_report(threshold=args.threshold)


if __name__ == '__main__':
    main()
