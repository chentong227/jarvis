#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 Phase 4] InnerVoice ageing/spotlight CLI 工具.

准则 6 三维耦合: 配置持久化 memory_pool/inner_voice_aging_config.json,
本 CLI 让 Sir 不改源码 + 不 git commit 就能 inspect / 调阈值.

Subcommands:
  config      显示当前 ageing/spotlight/surface_detection 配置 (含 default merge 后)
  pending     列出当前 ★ pending 未 surface 的 entry (近 1h)
  aged        列出近 24h 内 surface_attempts >= max_attempts OR 老于 max_age_sec 的
              entry (无论现在 wants_voice 真假, 反映"曾经 ★ 后被消化")
  stats       voice track 总览统计
  apply       手动触发一次 apply_ageing (Dry-run 时 --dry-run 不动 buffer)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _fmt_age(sec: float) -> str:
    if sec < 60:
        return f"{int(sec)}s"
    if sec < 3600:
        return f"{int(sec / 60)}m"
    if sec < 86400:
        return f"{sec / 3600:.1f}h"
    return f"{sec / 86400:.1f}d"


def cmd_config(_args) -> int:
    from jarvis_inner_voice_track import _load_aging_config, _AGING_CONFIG_PATH
    cfg = _load_aging_config()
    print(f"[config path] {_AGING_CONFIG_PATH}")
    print(f"[file exists] {os.path.exists(_AGING_CONFIG_PATH)}")
    print()
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


def cmd_pending(_args) -> int:
    from jarvis_inner_voice_track import get_inner_voice_track
    track = get_inner_voice_track()
    pending = track.get_pending_wants_voice()
    if not pending:
        print("(no pending ★ wants_voice entries)")
        return 0
    now = time.time()
    print(f"[*] {len(pending)} pending entries (not surfaced yet):")
    print()
    for e in pending:
        age = now - e.ts
        hhmm = time.strftime("%H:%M", time.localtime(e.ts))
        print(
            f"  - {hhmm} age={_fmt_age(age)} attempts={e.surface_attempts} "
            f"id={e.entry_id} u={e.urgency:.2f}"
        )
        print(f"      [{e.source}/{e.intent}] {e.content[:100]}")
    return 0


def cmd_aged(_args) -> int:
    """近 24h 内 attempts >= max_attempts OR age > max_age 的 entry."""
    from jarvis_inner_voice_track import (
        get_inner_voice_track, _load_aging_config,
    )
    track = get_inner_voice_track()
    cfg = _load_aging_config()
    ag = cfg.get('ageing', {})
    max_age = float(ag.get('ageing_max_age_sec', 7200.0))
    max_att = int(ag.get('ageing_max_attempts', 6))
    now = time.time()
    aged = []
    for e in track.all_recent(hours=24.0):
        age = now - e.ts
        is_aged = (age > max_age) or (e.surface_attempts >= max_att)
        if is_aged and (
            # 曾经 ★ — 现在被降级 OR 仍 ★ (但即将 ageing)
            e.surface_attempts > 0 or not e.surfaced_to_sir
        ):
            aged.append(e)
    if not aged:
        print("(no aged entries in past 24h)")
        return 0
    print(f"aged {len(aged)} entries (≥ {max_att} attempts or > {_fmt_age(max_age)}):")
    print()
    for e in aged[-20:]:
        age = now - e.ts
        hhmm = time.strftime("%H:%M", time.localtime(e.ts))
        flags = []
        if age > max_age:
            flags.append(f"age>{_fmt_age(max_age)}")
        if e.surface_attempts >= max_att:
            flags.append(f"attempts>={max_att}")
        if e.surfaced_to_sir:
            flags.append("surfaced_to_sir")
        if e.wants_voice:
            flags.append("still_★")
        else:
            flags.append("aged_demoted")
        print(
            f"  - {hhmm} age={_fmt_age(age)} attempts={e.surface_attempts} "
            f"[{'/'.join(flags)}]"
        )
        print(f"      [{e.source}/{e.intent}] {e.content[:100]}")
    return 0


def cmd_stats(_args) -> int:
    from jarvis_inner_voice_track import get_inner_voice_track
    track = get_inner_voice_track()
    stats = track.stats()
    print("[stats] InnerVoiceTrack:")
    for k, v in stats.items():
        print(f"  {k:30s} {v}")
    return 0


def cmd_apply(args) -> int:
    from jarvis_inner_voice_track import get_inner_voice_track
    track = get_inner_voice_track()
    if args.dry_run:
        # 不动 buffer, 只 dry-run
        from jarvis_inner_voice_track import _load_aging_config
        cfg = _load_aging_config()
        ag = cfg.get('ageing', {})
        max_age = float(ag.get('ageing_max_age_sec', 7200.0))
        max_att = int(ag.get('ageing_max_attempts', 6))
        now = time.time()
        would_age = 0
        for e in track.all_recent(hours=24.0):
            if not e.wants_voice or e.surfaced_to_sir:
                continue
            if (now - e.ts) > max_age or e.surface_attempts >= max_att:
                would_age += 1
        print(f"[dry-run] would age {would_age} entries")
    else:
        n = track.apply_ageing()
        print(f"aged {n} entries (★ → wants_voice=False, jsonl 不动)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="InnerVoice ageing/spotlight CLI"
    )
    sub = parser.add_subparsers(dest='cmd')
    sub.required = True

    sub.add_parser('config', help='show current ageing config (default merged)')
    sub.add_parser('pending', help='list ★ pending wants_voice entries')
    sub.add_parser('aged', help='list aged entries (24h)')
    sub.add_parser('stats', help='voice track stats')
    p_apply = sub.add_parser('apply', help='apply ageing now (in-memory mutate)')
    p_apply.add_argument('--dry-run', action='store_true',
                              help='只算不动 buffer')

    args = parser.parse_args(argv)
    return {
        'config': cmd_config,
        'pending': cmd_pending,
        'aged': cmd_aged,
        'stats': cmd_stats,
        'apply': cmd_apply,
    }[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
