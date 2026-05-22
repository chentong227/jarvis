# -*- coding: utf-8 -*-
"""[P5-fix25-stand-down / 2026-05-22] Stand Down CLI

Sir 准则 6.5: 配置持久化 + CLI 可改 (不需要改源码 + git commit).

Usage:
    cd d:/Jarvis
    python scripts/stand_down_dump.py status                      # 当前状态
    python scripts/stand_down_dump.py set --reason game --duration 60   # 进入
    python scripts/stand_down_dump.py set --reason phone --duration 15
    python scripts/stand_down_dump.py clear                       # 立即 wake
    python scripts/stand_down_dump.py history --tail 20           # 看历史
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

from jarvis_stand_down import (
    DEFAULT_DURATION_MIN,
    MAX_DURATION_MIN,
    GRACE_PERIOD_S,
    REASON_PHONE,
    REASON_GAME,
    REASON_FAMILY,
    REASON_FOCUS,
    REASON_MANUAL,
    clear_stand_down,
    get_state,
    set_stand_down,
    is_active,
    is_in_grace,
    _HISTORY_PATH,
)


def cmd_status() -> int:
    s = get_state()
    if not s.is_active_now():
        print("☀️ [StandDown] NOT active")
        if s.cleared_at_ts > 0:
            ago = int((time.time() - s.cleared_at_ts) / 60)
            print(f"   last cleared: {ago}min ago by {s.cleared_by_source}")
        return 0
    print("🌙 [StandDown] ACTIVE")
    print(f"   reason     : {s.reason}")
    print(f"   since      : {time.strftime('%H:%M:%S', time.localtime(s.since_ts))}"
          f" ({int(s.elapsed_s() / 60)}min ago)")
    print(f"   until      : {time.strftime('%H:%M:%S', time.localtime(s.until_ts))}"
          f" (in {int(s.remaining_s() / 60)}min)")
    if s.exit_hint:
        print(f"   exit_hint  : {s.exit_hint}")
    if s.is_in_grace():
        grace_left = int(s.grace_until_ts - time.time())
        print(f"   grace      : 试探期 {grace_left}s 剩 (Sir 说话会自动 cancel)")
    print(f"   set_by     : {s.set_by_source} (turn={s.set_by_turn})")
    return 0


def cmd_set(reason: str, duration_min: float, exit_hint: str) -> int:
    s = set_stand_down(
        reason=reason or REASON_MANUAL,
        duration_min=duration_min,
        exit_hint=exit_hint or '',
        source='cli',
    )
    print(f"🌙 [StandDown] 进入沉默")
    print(f"   reason   : {s.reason}")
    print(f"   duration : {int((s.until_ts - s.since_ts) / 60)}min "
          f"(until {time.strftime('%H:%M', time.localtime(s.until_ts))})")
    print(f"   grace    : {int(GRACE_PERIOD_S)}s 试探期")
    if exit_hint:
        print(f"   exit_hint: {exit_hint}")
    return 0


def cmd_clear(reason: str) -> int:
    was_active = is_active()
    s = clear_stand_down(reason=reason or '', source='cli')
    if was_active:
        print(f"☀️ [StandDown] wake up (cli)")
        if reason:
            print(f"   reason: {reason}")
    else:
        print("ℹ️ [StandDown] 当前未在 stand_down, 无需 clear")
    return 0


def cmd_history(tail: int) -> int:
    if not os.path.exists(_HISTORY_PATH):
        print("(no history)")
        return 0
    try:
        with open(_HISTORY_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[ERROR] {e}")
        return 2
    if not lines:
        print("(no history)")
        return 0
    show = lines[-tail:] if tail > 0 else lines
    for L in show:
        try:
            d = json.loads(L.strip())
            ev = d.get('event', '?')
            iso = d.get('iso', '?')
            reason = d.get('reason', '') or d.get('prev_reason', '')
            src = d.get('source', '?')
            extra = ''
            if ev == 'set':
                dur = d.get('duration_min', 0)
                extra = f" duration={int(dur)}min"
            elif ev == 'clear':
                held = d.get('duration_held_s', 0)
                extra = f" held={int(held)}s"
            print(f"  [{iso}] {ev:<8} reason={reason:<15} src={src}{extra}")
        except Exception:
            print(f"  (skipped malformed line)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description='Stand Down CLI')
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('status', help='查看当前 stand_down 状态')

    pset = sub.add_parser('set', help='进入 stand_down 模式')
    pset.add_argument('--reason', default=REASON_MANUAL,
                       help=(f'phone_call / game / family_chat / deep_focus / '
                             f'manual (default: {REASON_MANUAL})'))
    pset.add_argument('--duration', type=float, default=DEFAULT_DURATION_MIN,
                       help=(f'分钟 (default {DEFAULT_DURATION_MIN}, '
                             f'max {MAX_DURATION_MIN})'))
    pset.add_argument('--exit-hint', default='',
                       help='退出条件提示 (LLM 自由文本, 主脑下轮看)')

    pclear = sub.add_parser('clear', help='立即 wake')
    pclear.add_argument('--reason', default='',
                          help='clear 原因 (写历史)')

    phist = sub.add_parser('history', help='查看历史')
    phist.add_argument('--tail', type=int, default=20,
                          help='最近 N 条 (default 20)')

    args = p.parse_args()
    if args.cmd == 'status':
        return cmd_status()
    if args.cmd == 'set':
        return cmd_set(args.reason, args.duration, args.exit_hint)
    if args.cmd == 'clear':
        return cmd_clear(args.reason)
    if args.cmd == 'history':
        return cmd_history(args.tail)
    p.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
