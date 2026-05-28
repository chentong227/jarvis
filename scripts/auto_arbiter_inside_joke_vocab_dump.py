#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_arbiter_inside_joke_vocab_dump — Sir CLI 管 inside_joke 两层耦合 vocab.

[H.1 / Sir 2026-05-28 15:30 真痛 image 1 anchor]

Sir 真痛: '真笑点得我大致复述 / 笑了 / 确认对才算 inside_joke'.
反 LLM 自嗨, Python deterministic strong-gate 用 vocab 判强信号:
  - 强 ACT: Sir 复述 phrase / AmbientSensor laughter / Sir 文字确认
  - 强 REJ: Sir dismiss 词 / stock butler 套话 / trivial 长度

vocab 持久化 memory_pool/auto_arbiter_inside_joke_vocab.json (准则 6),
Sir CLI 改 → 30s 内 daemon 热重载.

用法:
  python scripts/auto_arbiter_inside_joke_vocab_dump.py                 # list 全 vocab
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --stats         # 看近 24h pre-decide hit 数
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --add-confirm "笑死"
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --add-dismiss "无聊"
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --add-stock "right away sir"
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --remove-confirm "笑死"
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --remove-dismiss "无聊"
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --remove-stock "right away sir"
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --enable
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --disable
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --set-overlap 0.7
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --set-min-words 4
  python scripts/auto_arbiter_inside_joke_vocab_dump.py --set-laughter-window 600
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

VOCAB_PATH = os.path.join(
    ROOT, 'memory_pool', 'auto_arbiter_inside_joke_vocab.json'
)
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
    print(f"📄 [auto_arbiter_inside_joke_vocab] {VOCAB_PATH}")
    print(f"  enabled: {vocab.get('enabled', False)}")
    print(f"  schema_version: {vocab.get('schema_version', '?')}")
    print()
    print_list_section('confirm_keywords (Sir 文字确认)',
                          vocab.get('confirm_keywords', []) or [])
    print_list_section('dismiss_keywords (Sir 明拒)',
                          vocab.get('dismiss_keywords', []) or [])
    print_list_section('stock_butler_keywords (套话 reject)',
                          vocab.get('stock_butler_keywords', []) or [])
    print()
    print("  thresholds:")
    print(f"    sir_quote_token_overlap: "
              f"{vocab.get('sir_quote_token_overlap', 0.6)}")
    print(f"    laughter_window_s:       "
              f"{vocab.get('laughter_window_s', 300)}")
    print(f"    confirm_turns_after:     "
              f"{vocab.get('confirm_turns_after', 2)}")
    print(f"    min_phrase_words:        "
              f"{vocab.get('min_phrase_words', 3)}")
    print(f"    max_phrase_chars:        "
              f"{vocab.get('max_phrase_chars', 80)}")
    print(f"    stm_lookback_turns:      "
              f"{vocab.get('stm_lookback_turns', 10)}")


def cmd_stats(hours: float = 24.0) -> None:
    """看 inside_joke strong-gate 近 N h hit 数 + by reason."""
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
            if d.get('kind') != 'inside_joke':
                continue
            reason = d.get('reason', '')
            if not reason.startswith('pre_decide_strong'):
                other += 1
                continue
            if d.get('decision') == 'activate':
                act_count += 1
            elif d.get('decision') == 'reject':
                rej_count += 1
            # reason key (去 in_stm 噪音)
            tail = reason.split(': ', 1)[-1]
            key = tail.split(' in_stm=')[0][:40]
            by_reason[key] = by_reason.get(key, 0) + 1
    print(f"📊 [auto_arbiter inside_joke strong-gate 近 {hours:.0f}h hits]")
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
        description='AutoArbiter inside_joke vocab Sir CLI'
    )
    parser.add_argument('--stats', action='store_true',
                          help='show near 24h pre-decide hit count')
    parser.add_argument('--stats-hours', type=float, default=24.0,
                          help='stats look-back hours (default 24)')
    parser.add_argument('--add-confirm', type=str, metavar='KW')
    parser.add_argument('--add-dismiss', type=str, metavar='KW')
    parser.add_argument('--add-stock', type=str, metavar='KW')
    parser.add_argument('--remove-confirm', type=str, metavar='KW')
    parser.add_argument('--remove-dismiss', type=str, metavar='KW')
    parser.add_argument('--remove-stock', type=str, metavar='KW')
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--disable', action='store_true')
    parser.add_argument('--set-overlap', type=float, metavar='RATIO')
    parser.add_argument('--set-min-words', type=int, metavar='N')
    parser.add_argument('--set-max-chars', type=int, metavar='N')
    parser.add_argument('--set-laughter-window', type=int, metavar='S')
    parser.add_argument('--set-confirm-turns', type=int, metavar='N')
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
        (args.add_confirm, 'confirm_keywords', 'add'),
        (args.add_dismiss, 'dismiss_keywords', 'add'),
        (args.add_stock, 'stock_butler_keywords', 'add'),
        (args.remove_confirm, 'confirm_keywords', 'remove'),
        (args.remove_dismiss, 'dismiss_keywords', 'remove'),
        (args.remove_stock, 'stock_butler_keywords', 'remove'),
    ]
    for value, list_name, action in list_actions:
        if value is not None:
            if cmd_modify_list(vocab, list_name, action, value):
                dirty = True

    threshold_changes = [
        ('set_overlap', 'sir_quote_token_overlap', args.set_overlap),
        ('set_min_words', 'min_phrase_words', args.set_min_words),
        ('set_max_chars', 'max_phrase_chars', args.set_max_chars),
        ('set_laughter_window', 'laughter_window_s', args.set_laughter_window),
        ('set_confirm_turns', 'confirm_turns_after', args.set_confirm_turns),
        ('set_stm_lookback', 'stm_lookback_turns', args.set_stm_lookback),
    ]
    for arg_name, key, value in threshold_changes:
        if value is not None:
            vocab[key] = value
            print(f"✅ {key}={value}")
            dirty = True

    if dirty:
        save_vocab(vocab)
        print(f"💾 saved → {VOCAB_PATH}")
        print("(daemon 下次 tick 内 30s mtime cache 自动重载)")
        return 0

    # 无 modify args → 默认 list
    cmd_list(vocab)
    return 0


if __name__ == '__main__':
    sys.exit(main())
