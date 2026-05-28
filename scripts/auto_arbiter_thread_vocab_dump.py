#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_arbiter_thread_vocab_dump — Sir CLI 管 thread 两层耦合 vocab.

[H.2 / Sir 2026-05-28 15:37 真痛 image 1 anchor]

thread = 'Sir 提及重要 milestone / achievement', e.g.
  'Built and deployed J.A.R.V.I.S.' / 'P0+19-5 architecture split done'

强 ACT (bypass LLM 直 activate): Sir 复述 title / Sir milestone vocab in STM
强 REJ (bypass LLM 直 reject): title trivial / detail 太短

vocab 持久化 memory_pool/auto_arbiter_thread_vocab.json (准则 6),
Sir CLI 改 → 30s 内 daemon 热重载.

用法:
  python scripts/auto_arbiter_thread_vocab_dump.py                  # list 全 vocab
  python scripts/auto_arbiter_thread_vocab_dump.py --stats          # 近 24h hit 数
  python scripts/auto_arbiter_thread_vocab_dump.py --add-milestone "毕业"
  python scripts/auto_arbiter_thread_vocab_dump.py --remove-milestone "毕业"
  python scripts/auto_arbiter_thread_vocab_dump.py --enable
  python scripts/auto_arbiter_thread_vocab_dump.py --disable
  python scripts/auto_arbiter_thread_vocab_dump.py --set-overlap 0.6
  python scripts/auto_arbiter_thread_vocab_dump.py --set-min-words 3
  python scripts/auto_arbiter_thread_vocab_dump.py --set-min-detail 20
  python scripts/auto_arbiter_thread_vocab_dump.py --set-max-title 100
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
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'auto_arbiter_thread_vocab.json')
LOG_PATH = os.path.join(ROOT, 'memory_pool', 'auto_arbiter_log.jsonl')


def load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'enabled': False}
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f) or {}


def save_vocab(data: dict) -> None:
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def print_list_section(title: str, items: List[str]) -> None:
    print(f"  {title} ({len(items)}):")
    if not items:
        print("    (empty)")
        return
    for it in items:
        print(f"    - {it}")


def cmd_list(vocab: dict) -> None:
    print(f"📄 [auto_arbiter_thread_vocab] {VOCAB_PATH}")
    print(f"  enabled: {vocab.get('enabled', False)}")
    print(f"  schema_version: {vocab.get('schema_version', '?')}")
    print()
    print_list_section('milestone_keywords (Sir milestone 词)',
                          vocab.get('milestone_keywords', []) or [])
    print()
    print("  thresholds:")
    print(f"    min_title_token_overlap: "
              f"{vocab.get('min_title_token_overlap', 0.5)}")
    print(f"    min_title_words:         "
              f"{vocab.get('min_title_words', 2)}")
    print(f"    max_title_chars:         "
              f"{vocab.get('max_title_chars', 80)}")
    print(f"    min_detail_chars:        "
              f"{vocab.get('min_detail_chars', 10)}")
    print(f"    stm_lookback_turns:      "
              f"{vocab.get('stm_lookback_turns', 10)}")


def cmd_stats(hours: float = 24.0) -> None:
    if not os.path.exists(LOG_PATH):
        print(f"📊 [stats] log not found: {LOG_PATH}")
        return
    cutoff = time.time() - hours * 3600.0
    act_count = 0
    rej_count = 0
    by_reason: dict = {}
    other = 0
    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if d.get('ts', 0) < cutoff:
                continue
            if d.get('kind') != 'thread':
                continue
            reason = d.get('reason', '')
            if not reason.startswith('pre_decide_strong'):
                other += 1
                continue
            if d.get('decision') == 'activate':
                act_count += 1
            elif d.get('decision') == 'reject':
                rej_count += 1
            tail = reason.split(': ', 1)[-1]
            key = tail.split(' in_stm=')[0][:40]
            by_reason[key] = by_reason.get(key, 0) + 1
    print(f"📊 [auto_arbiter thread strong-gate 近 {hours:.0f}h hits]")
    print(f"  ACTIVATE (强 ACT bypass LLM): {act_count}")
    print(f"  REJECT   (强 REJ bypass LLM): {rej_count}")
    print(f"  LLM eval (无强信号 fallback): {other}")
    if by_reason:
        print()
        print("  by reason 分布:")
        for k, n in sorted(by_reason.items(), key=lambda x: -x[1]):
            print(f"    {n:>3}× {k}")


def cmd_modify_list(vocab: dict, list_name: str, action: str,
                       value: str) -> bool:
    cur = vocab.get(list_name, []) or []
    if action == 'add':
        if value in cur:
            print(f"⚠️  '{value}' already in {list_name}")
            return False
        cur.append(value)
        vocab[list_name] = cur
        print(f"✅ added '{value}' to {list_name} (now {len(cur)} items)")
        return True
    elif action == 'remove':
        if value not in cur:
            print(f"⚠️  '{value}' not in {list_name}")
            return False
        cur.remove(value)
        vocab[list_name] = cur
        print(f"✅ removed '{value}' from {list_name} (now {len(cur)} items)")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description='AutoArbiter thread vocab Sir CLI'
    )
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--stats-hours', type=float, default=24.0)
    parser.add_argument('--add-milestone', type=str, metavar='KW')
    parser.add_argument('--remove-milestone', type=str, metavar='KW')
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--disable', action='store_true')
    parser.add_argument('--set-overlap', type=float, metavar='RATIO')
    parser.add_argument('--set-min-words', type=int, metavar='N')
    parser.add_argument('--set-max-title', type=int, metavar='N')
    parser.add_argument('--set-min-detail', type=int, metavar='N')
    parser.add_argument('--set-stm-lookback', type=int, metavar='N')

    args = parser.parse_args()

    if args.stats:
        cmd_stats(args.stats_hours)
        return 0

    vocab = load_vocab()
    dirty = False

    if args.enable:
        vocab['enabled'] = True
        print("✅ enabled=True")
        dirty = True
    if args.disable:
        vocab['enabled'] = False
        print("✅ enabled=False")
        dirty = True

    list_actions = [
        (args.add_milestone, 'milestone_keywords', 'add'),
        (args.remove_milestone, 'milestone_keywords', 'remove'),
    ]
    for value, list_name, action in list_actions:
        if value is not None:
            if cmd_modify_list(vocab, list_name, action, value):
                dirty = True

    threshold_changes = [
        ('min_title_token_overlap', args.set_overlap),
        ('min_title_words', args.set_min_words),
        ('max_title_chars', args.set_max_title),
        ('min_detail_chars', args.set_min_detail),
        ('stm_lookback_turns', args.set_stm_lookback),
    ]
    for key, value in threshold_changes:
        if value is not None:
            vocab[key] = value
            print(f"✅ {key}={value}")
            dirty = True

    if dirty:
        save_vocab(vocab)
        print(f"💾 saved → {VOCAB_PATH}")
        print("(daemon 下次 tick 30s 内 mtime cache 自动重载)")
        return 0

    cmd_list(vocab)
    return 0


if __name__ == '__main__':
    sys.exit(main())
