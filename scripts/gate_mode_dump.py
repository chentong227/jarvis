# -*- coding: utf-8 -*-
"""[β.5.1 / 2026-05-19] Sentinel gate_mode CLI 工具.

Sir 准则 6.5 vocab CLI 范式 (类比 scripts/concerns_dump.py):
  - Sir 不改源码 + git commit 就能调 sentinel 行为
  - 即时生效 (NudgeGate 每次 can_speak 读 vocab)

用法:
  python scripts/gate_mode_dump.py                      # list 当前所有 sentinel mode
  python scripts/gate_mode_dump.py --show NudgeGate     # 看 NudgeGate 模式 + 解释
  python scripts/gate_mode_dump.py --set NudgeGate=soft # 切 NudgeGate 为 soft
  python scripts/gate_mode_dump.py --reset              # 全切回 hard (rollback)

模式说明 (vocab.json):
  hard         — 原行为: return True/False. 不 publish 到 SWM.
  soft         — 双轨: 仍 hard return, 同时 publish gate_advice 到 SWM.
                 用于 β.5 早期观察期 (主脑看 evidence 但行为受约束).
  publish_only — 永不 hard 拦: return True. 仅 publish gate_advice 到 SWM.
                 主脑看 advice 自决 (走 stream_nudge reaction_space [SILENCE]).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')

VALID_MODES = ('hard', 'soft', 'publish_only')
KNOWN_SENTINELS = (
    'NudgeGate', 'OfferGuard', 'SmartNudgeSentinel',
    'Conductor', 'WellnessGuardian', 'ReturnSentinel',
)


def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        print(f'❌ vocab not found: {VOCAB_PATH}')
        sys.exit(1)
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_vocab(vocab: dict) -> None:
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def cmd_list(vocab: dict) -> None:
    print(f'\n=== Sentinel Gate Modes ({VOCAB_PATH}) ===\n')
    current = vocab.get('current', {})
    for sentinel in KNOWN_SENTINELS:
        mode = current.get(sentinel, 'hard')
        marker = '[H]' if mode == 'hard' else ('[S]' if mode == 'soft' else '[P]')
        print(f'  {marker} {sentinel:<25} = {mode}')
    print()
    print('Modes:')
    modes_doc = vocab.get('modes', {})
    for m in VALID_MODES:
        doc = modes_doc.get(m, '(no doc)')
        print(f'  {m:<14} — {doc[:90]}')
    print()


def cmd_show(vocab: dict, sentinel: str) -> None:
    current = vocab.get('current', {})
    if sentinel not in current:
        print(f'❌ unknown sentinel: {sentinel}')
        print(f'   valid: {", ".join(KNOWN_SENTINELS)}')
        sys.exit(1)
    mode = current[sentinel]
    print(f'\n{sentinel}: {mode}')
    print(f'  {vocab.get("modes", {}).get(mode, "(no doc)")}')
    print()


def cmd_set(vocab: dict, key_val: str) -> None:
    if '=' not in key_val:
        print(f'❌ --set 需 key=val 格式, 比如 --set NudgeGate=soft')
        sys.exit(1)
    sentinel, mode = key_val.split('=', 1)
    sentinel = sentinel.strip()
    mode = mode.strip()
    if sentinel not in KNOWN_SENTINELS:
        print(f'❌ unknown sentinel: {sentinel}')
        print(f'   valid: {", ".join(KNOWN_SENTINELS)}')
        sys.exit(1)
    if mode not in VALID_MODES:
        print(f'❌ unknown mode: {mode}')
        print(f'   valid: {", ".join(VALID_MODES)}')
        sys.exit(1)
    current = vocab.setdefault('current', {})
    old = current.get(sentinel, 'hard')
    current[sentinel] = mode
    _save_vocab(vocab)
    print(f'✅ {sentinel}: {old} → {mode}')
    print(f'   即时生效 (NudgeGate 每次 can_speak 读 vocab, 无需重启)')


def cmd_reset(vocab: dict) -> None:
    current = vocab.setdefault('current', {})
    changed = 0
    for s in KNOWN_SENTINELS:
        old = current.get(s, 'hard')
        if old != 'hard':
            current[s] = 'hard'
            print(f'🔒 {s}: {old} → hard')
            changed += 1
    if changed == 0:
        print('💤 全部已是 hard, 无需 reset.')
    else:
        _save_vocab(vocab)
        print(f'\n✅ reset 完成 ({changed} 个 sentinel)')


def main() -> None:
    parser = argparse.ArgumentParser(description='Sentinel gate_mode vocab CLI (β.5.1)')
    parser.add_argument('--show', metavar='SENTINEL', help='看 sentinel mode + 解释')
    parser.add_argument('--set', metavar='K=V', help='设 sentinel mode, 比如 NudgeGate=soft')
    parser.add_argument('--reset', action='store_true', help='全切回 hard (rollback)')
    args = parser.parse_args()

    vocab = _load_vocab()
    if args.show:
        cmd_show(vocab, args.show)
    elif getattr(args, 'set'):
        cmd_set(vocab, getattr(args, 'set'))
    elif args.reset:
        cmd_reset(vocab)
    else:
        cmd_list(vocab)


if __name__ == '__main__':
    main()
