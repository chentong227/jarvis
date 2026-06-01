# -*- coding: utf-8 -*-
"""[β.5.18 / 2026-05-19] commitment_conditional_vocab.json CLI 工具.

Sir 准则 6 三硬规第 2 条 "CLI 可改" 落地. β.4.11 立 vocab 但 dump 工具一直没建,
docs_references_valid testcase 抓到 (AGENTS.md:66 backquoted ref 不存在).

vocab 用途 (β.4.11 立):
  conditional / status-description markers. Sir 说 "先不睡 / 等做完再睡 / 今晚熬"
  类 conditional status → LLM 抓成 commitment + 幻觉 deadline=8:00 让 Sir 烦.
  marker 命中后转 PromiseLog soft (避免 hard 注册).

接口 (兼容 scripts/concerns_dump.py 风格):
  python scripts/cmt_vocab_dump.py             # 默认 list (按 group)
  python scripts/cmt_vocab_dump.py --show GROUP # 看某 group 全部 markers
  python scripts/cmt_vocab_dump.py --add GROUP=PATTERN  # 加 (待 L7 reflector)
  python scripts/cmt_vocab_dump.py --counts    # 各 group marker 计数

Reflector L7 LLM-propose 仍待做 (β.5+ 后续轨道).
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


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'commitment_conditional_vocab.json')

VALID_GROUPS = (
    'markers_conditional',
    'markers_intent_vague',
    'markers_negation_status',
)


def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        print(f'❌ vocab 文件不存在: {VOCAB_PATH}')
        sys.exit(1)
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_vocab(vocab: dict) -> None:
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def cmd_list(vocab: dict) -> None:
    print(f'\n=== Commitment Conditional Vocab ({VOCAB_PATH}) ===\n')
    print(f'  version : {vocab.get("version", "?")}')
    print(f'  created : {vocab.get("created_at", "?")}\n')
    for g in VALID_GROUPS:
        items = vocab.get(g, [])
        print(f'  {g:<28} ({len(items):>2} markers)')
    print()


def cmd_show(vocab: dict, group: str) -> None:
    if group not in VALID_GROUPS:
        print(f'❌ unknown group: {group}')
        print(f'   valid: {", ".join(VALID_GROUPS)}')
        sys.exit(1)
    items = vocab.get(group, [])
    print(f'\n{group} ({len(items)} markers):')
    for i, m in enumerate(items, 1):
        print(f'  {i:>2}. {m}')
    print()


def cmd_counts(vocab: dict) -> None:
    print('\n=== marker counts ===')
    for g in VALID_GROUPS:
        print(f'  {g:<28} {len(vocab.get(g, []))}')
    print()


def cmd_add(vocab: dict, key_val: str) -> None:
    if '=' not in key_val:
        print('❌ --add 需 GROUP=PATTERN 格式')
        sys.exit(1)
    group, pattern = key_val.split('=', 1)
    group = group.strip()
    pattern = pattern.strip()
    if group not in VALID_GROUPS:
        print(f'❌ unknown group: {group}')
        sys.exit(1)
    items = vocab.setdefault(group, [])
    if pattern in items:
        print(f'⚠️ pattern 已存在于 {group}')
        return
    items.append(pattern)
    _save_vocab(vocab)
    print(f'✅ {group}: 新增 marker {pattern!r} (now {len(items)} markers)')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Commitment Conditional Vocab CLI (β.5.18)')
    parser.add_argument('--show', metavar='GROUP', help='看某 group 全部 markers')
    parser.add_argument('--add', metavar='GROUP=PATTERN', help='加 marker')
    parser.add_argument('--counts', action='store_true', help='各 group 计数')
    args = parser.parse_args()

    vocab = _load_vocab()
    if args.show:
        cmd_show(vocab, args.show)
    elif args.add:
        cmd_add(vocab, args.add)
    elif args.counts:
        cmd_counts(vocab)
    else:
        cmd_list(vocab)


if __name__ == '__main__':
    main()
