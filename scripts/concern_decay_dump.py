#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[反刍治本 / Sir 2026-06-02] concern_decay_dump.py — concern severity 反刍治本 vocab CLI

准则 6: vocab 持久化 memory_pool/concern_decay_vocab.json + CLI 可改 (Sir 不改源码)。

三修配置 (详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §3.2):
  Fix1 scan_jarvis_reply: reflect 是否扫贾维斯自己回复 (false=斩自我强化环)
  Fix2 severity_decay_*: severity 时间半衰期 (久无真 Sir signal → 自然遗忘)
  Fix3 (无 vocab, 硬规): snooze/dismiss concern 不喂体张力

用法:
  python scripts/concern_decay_dump.py                 # 看当前 config
  python scripts/concern_decay_dump.py --set severity_half_life_days 5
  python scripts/concern_decay_dump.py --set scan_jarvis_reply true
  python scripts/concern_decay_dump.py --decay-now      # 立刻跑一轮 severity 衰减 (治存量污染)
  python scripts/concern_decay_dump.py --preview        # 看每个 active concern 当前/衰后 severity
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'concern_decay_vocab.json')

_DEFAULT = {
    'scan_jarvis_reply': False,
    'severity_decay_enabled': True,
    'severity_half_life_days': 7.0,
    'severity_decay_grace_days': 2.0,
    'severity_decay_floor': 0.0,
}

_BOOL_KEYS = {'scan_jarvis_reply', 'severity_decay_enabled'}
_FLOAT_KEYS = {'severity_half_life_days', 'severity_decay_grace_days', 'severity_decay_floor'}


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return dict(_DEFAULT)
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        out = dict(_DEFAULT)
        out.update({k: v for k, v in data.items() if not k.startswith('_')})
        return out
    except Exception as e:
        print(f"[warn] load fail ({e}); using defaults")
        return dict(_DEFAULT)


def _save(cfg: dict) -> None:
    payload = {
        '_meta': {
            'schema': 'concern_decay_vocab',
            'updated_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'cli': 'scripts/concern_decay_dump.py',
        },
    }
    payload.update(cfg)
    tmp = VOCAB_PATH + '.tmp'
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def _coerce(key: str, val: str):
    if key in _BOOL_KEYS:
        return str(val).strip().lower() in ('1', 'true', 'yes', 'on')
    if key in _FLOAT_KEYS:
        return float(val)
    return val


def cmd_show(cfg: dict) -> None:
    print("=== concern_decay_vocab (反刍治本配置) ===")
    for k in _DEFAULT:
        print(f"  {k:28} = {cfg.get(k)}")


def cmd_preview() -> None:
    """看每个 active concern 当前 severity + apply_decay 后会变成多少 (dry-run)。"""
    from jarvis_concerns import ConcernsLedger
    cp = os.path.join(ROOT, 'memory_pool', 'concerns.json')
    led = ConcernsLedger(persist_path=cp)
    led.load()
    enabled, hl_s, grace_s, floor = led._severity_decay_params()
    now = time.time()
    print(f"=== severity 衰减预览 (half_life={hl_s/86400:.1f}d grace={grace_s/86400:.1f}d) ===")
    print(f"{'concern_id':32}{'state':10}{'sev':>6}{'→衰后':>8}{'锚龄(d)':>8}")
    print("-" * 70)
    rows = sorted(led.concerns.values(), key=lambda c: -c.severity)
    for c in rows:
        if c.state != 'active':
            new = c.severity
            age_d = 0.0
        else:
            anchor = c.last_user_signal_ts or led._infer_user_anchor(c)
            age = now - anchor
            age_d = age / 86400.0
            if enabled and c.severity > floor and age > grace_s and hl_s > 0:
                new = max(floor, c.severity * (0.5 ** ((age - grace_s) / hl_s)))
            else:
                new = c.severity
        flag = " ←衰" if new < c.severity - 1e-4 else ""
        print(f"{c.id:32}{c.state:10}{c.severity:>6.2f}{new:>8.2f}{age_d:>8.1f}{flag}")


def cmd_decay_now() -> None:
    """立刻跑一轮 apply_decay (Sir 治存量污染: 让陈年高 severity 立即降温)。"""
    from jarvis_concerns import ConcernsLedger
    cp = os.path.join(ROOT, 'memory_pool', 'concerns.json')
    led = ConcernsLedger(persist_path=cp)
    led.load()
    stats = led.apply_decay()
    led.persist()
    print(f"[DECAY] severity_decayed={stats.get('severity_decayed', 0)} "
          f"archived={stats.get('archived', 0)} unsnoozed={stats.get('unsnoozed', 0)}")
    cmd_preview()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="concern 反刍治本 vocab CLI")
    ap.add_argument('--set', nargs=2, metavar=('KEY', 'VAL'), help="设一个配置字段")
    ap.add_argument('--preview', action='store_true', help="dry-run 看 severity 衰减预览")
    ap.add_argument('--decay-now', action='store_true', help="立刻跑一轮 severity 衰减 (写回)")
    args = ap.parse_args(argv)

    if args.preview:
        cmd_preview()
        return 0
    if args.decay_now:
        cmd_decay_now()
        return 0
    cfg = _load()
    if args.set:
        key, val = args.set
        if key not in _DEFAULT:
            print(f"[err] unknown key {key!r}. valid: {list(_DEFAULT)}")
            return 1
        cfg[key] = _coerce(key, val)
        _save(cfg)
        print(f"[set] {key} = {cfg[key]}")
    cmd_show(cfg)
    return 0


if __name__ == '__main__':
    sys.exit(main())
