#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_arbiter_concern_vocab_dump — Sir CLI 管 concern 两层耦合 vocab.

[H.4 / Sir 2026-05-28 16:00]

concern = Jarvis 视角 'I'm watching', Sir 真意 image 1 严格把关:
  强 ACT: source trusted (sir_added/sir_confirmed) / Sir 抱怨 vocab + watch overlap
  强 REJ: watch trivial / why 缺

vocab 持久化 memory_pool/auto_arbiter_concern_vocab.json (准则 6),
Sir CLI 改 → 30s 内 daemon 热重载.

用法:
  python scripts/auto_arbiter_concern_vocab_dump.py                  # list
  python scripts/auto_arbiter_concern_vocab_dump.py --stats          # 近 24h hit
  python scripts/auto_arbiter_concern_vocab_dump.py --add-complaint "burnt out"
  python scripts/auto_arbiter_concern_vocab_dump.py --remove-complaint "burnt out"
  python scripts/auto_arbiter_concern_vocab_dump.py --add-source "sir_voice"
  python scripts/auto_arbiter_concern_vocab_dump.py --remove-source "sir_voice"
  python scripts/auto_arbiter_concern_vocab_dump.py --enable
  python scripts/auto_arbiter_concern_vocab_dump.py --disable
  python scripts/auto_arbiter_concern_vocab_dump.py --set-overlap 0.4
  python scripts/auto_arbiter_concern_vocab_dump.py --set-min-watch 4
  python scripts/auto_arbiter_concern_vocab_dump.py --set-min-why 4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VOCAB_PATH = os.path.join(ROOT, 'memory_pool',
                              'auto_arbiter_concern_vocab.json')
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
    print(f"📄 [auto_arbiter_concern_vocab] {VOCAB_PATH}")
    print(f"  enabled: {vocab.get('enabled', False)}")
    print(f"  schema_version: {vocab.get('schema_version', '?')}")
    print()
    print_list_section('sir_complaint_keywords (Sir 抱怨触发 ACT)',
                          vocab.get('sir_complaint_keywords', []) or [])
    print()
    print_list_section('trusted_sources (source 命中直 ACT)',
                          vocab.get('trusted_sources', []) or [])
    print()
    print("  thresholds:")
    print(f"    min_watch_token_overlap: "
              f"{vocab.get('min_watch_token_overlap', 0.3)}")
    print(f"    min_watch_words:         "
              f"{vocab.get('min_watch_words', 3)}")
    print(f"    min_why_words:           "
              f"{vocab.get('min_why_words', 3)}")
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
            if d.get('kind') != 'concern':
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
    print(f"📊 [auto_arbiter concern strong-gate 近 {hours:.0f}h hits]")
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
        description='AutoArbiter concern vocab Sir CLI'
    )
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--stats-hours', type=float, default=24.0)
    parser.add_argument('--add-complaint', type=str, metavar='KW')
    parser.add_argument('--remove-complaint', type=str, metavar='KW')
    parser.add_argument('--add-source', type=str, metavar='SRC')
    parser.add_argument('--remove-source', type=str, metavar='SRC')
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--disable', action='store_true')
    parser.add_argument('--set-overlap', type=float, metavar='RATIO')
    parser.add_argument('--set-min-watch', type=int, metavar='N')
    parser.add_argument('--set-min-why', type=int, metavar='N')
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
        (args.add_complaint, 'sir_complaint_keywords', 'add'),
        (args.remove_complaint, 'sir_complaint_keywords', 'remove'),
        (args.add_source, 'trusted_sources', 'add'),
        (args.remove_source, 'trusted_sources', 'remove'),
    ]
    for value, list_name, action in list_actions:
        if value is not None:
            if cmd_modify_list(vocab, list_name, action, value):
                dirty = True

    threshold_changes = [
        ('min_watch_token_overlap', args.set_overlap),
        ('min_watch_words', args.set_min_watch),
        ('min_why_words', args.set_min_why),
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
