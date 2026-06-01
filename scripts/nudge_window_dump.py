# -*- coding: utf-8 -*-
"""CLI for nudge_window_vocab.json (β.5.40-E1).

Sir 用法:
  python scripts/nudge_window_dump.py --show
  python scripts/nudge_window_dump.py --set-weekday 14 0.2     # 周一-五 14 点 score=0.2 (低)
  python scripts/nudge_window_dump.py --set-weekend 10 0.9     # 周末 10 点 score=0.9 (高)
  python scripts/nudge_window_dump.py --reset                  # 全清 → 等 L7 重算
  python scripts/nudge_window_dump.py --recompute              # 立刻让 reflector 跑 (需 nerve runtime)
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
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'nudge_window_vocab.json')


def _load():
    if not os.path.exists(VOCAB_PATH):
        return None
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ load vocab err: {e}")
        return None


def _save(vocab):
    try:
        tmp = VOCAB_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, VOCAB_PATH)
        print(f"✅ saved {VOCAB_PATH}")
        return True
    except Exception as e:
        print(f"❌ save err: {e}")
        return False


def _show(vocab):
    print(f"\n=== nudge_window_vocab.json ===")
    print(f"path: {VOCAB_PATH}")
    print(f"last_computed_ts: {vocab.get('last_computed_ts', 0)}")
    print(f"source: {vocab.get('source', '?')}")
    print()
    
    wd = vocab.get('weekday_hourly_receptive', {})
    we = vocab.get('weekend_hourly_receptive', {})
    sc = vocab.get('samples_count', {'weekday': {}, 'weekend': {}})
    
    print(f"{'Hour':<6}{'Weekday':<12}{'Wd Samp':<10}{'Weekend':<12}{'We Samp':<10}")
    print('-' * 50)
    for h in range(24):
        hs = str(h)
        wd_s = wd.get(hs)
        we_s = we.get(hs)
        wd_n = sc.get('weekday', {}).get(hs, 0)
        we_n = sc.get('weekend', {}).get(hs, 0)
        wd_str = f"{wd_s:.2f}" if wd_s is not None else '   -'
        we_str = f"{we_s:.2f}" if we_s is not None else '   -'
        bar_wd = '█' * int((wd_s or 0) * 10) if wd_s is not None else ''
        bar_we = '█' * int((we_s or 0) * 10) if we_s is not None else ''
        print(f"{h:<6}{wd_str + ' ' + bar_wd:<12}{wd_n:<10}{we_str + ' ' + bar_we:<12}{we_n:<10}")
    print()
    
    history = vocab.get('history', [])
    print(f"history: {len(history)} samples (last 3):")
    for s in history[-3:]:
        print(f"  - {s.get('iso', '?')} h={s.get('hour')} wd={s.get('is_weekday')} → {s.get('outcome')}")


def _set_hour(vocab, key, hour, score):
    table = vocab.setdefault(key, {})
    if hour < 0 or hour >= 24:
        print(f"❌ hour out of range 0-23: {hour}")
        return False
    if score < 0 or score > 1:
        print(f"❌ score out of range 0-1: {score}")
        return False
    table[str(hour)] = round(float(score), 3)
    print(f"✅ {key}[{hour}] = {score}")
    return True


def _reset(vocab):
    null_table = {str(h): None for h in range(24)}
    vocab['weekday_hourly_receptive'] = dict(null_table)
    vocab['weekend_hourly_receptive'] = dict(null_table)
    vocab['samples_count'] = {'weekday': {}, 'weekend': {}}
    vocab['history'] = []
    vocab['last_computed_ts'] = 0
    vocab['source'] = '手动 --reset (Sir 清空 + 等 L7 重算)'
    print("✅ reset all 24 hours weekday/weekend + history cleared")


def main():
    ap = argparse.ArgumentParser(description='nudge_window_vocab.json CLI (β.5.40-E1)')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--set-weekday', nargs=2, metavar=('HOUR', 'SCORE'),
                    help='Set weekday[H]=S, 0-23, 0-1')
    ap.add_argument('--set-weekend', nargs=2, metavar=('HOUR', 'SCORE'),
                    help='Set weekend[H]=S')
    ap.add_argument('--reset', action='store_true')
    args = ap.parse_args()
    
    vocab = _load()
    if vocab is None:
        print(f"❌ {VOCAB_PATH} 不存在")
        sys.exit(1)
    
    if args.show:
        _show(vocab)
        return
    
    changed = False
    if args.set_weekday:
        h = int(args.set_weekday[0]); s = float(args.set_weekday[1])
        if _set_hour(vocab, 'weekday_hourly_receptive', h, s):
            changed = True
    if args.set_weekend:
        h = int(args.set_weekend[0]); s = float(args.set_weekend[1])
        if _set_hour(vocab, 'weekend_hourly_receptive', h, s):
            changed = True
    if args.reset:
        _reset(vocab)
        changed = True
    
    if changed:
        _save(vocab)
    elif not args.show:
        _show(vocab)


if __name__ == '__main__':
    main()
