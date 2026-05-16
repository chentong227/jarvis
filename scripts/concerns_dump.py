# -*- coding: utf-8 -*-
"""[P0+20-β.2.5 / 2026-05-17] Concerns Ledger CLI Dump

让 Sir 一行命令查看 / 拍板 Jarvis 的内部牵挂（灵魂工程 Layer 1 + Layer 4
WeeklyReflector propose 队列）。

用法：
    python scripts/concerns_dump.py                          # 默认 ASCII 表
    python scripts/concerns_dump.py --review                 # 列 WeeklyReflector 提名待审
    python scripts/concerns_dump.py --activate <id>          # Sir 通过
    python scripts/concerns_dump.py --reject   <id>          # Sir 拒绝（→ archived）
    python scripts/concerns_dump.py --snooze   <id> --hours 24  # 暂停 24h
    python scripts/concerns_dump.py --json                   # 机读 JSON
    python scripts/concerns_dump.py --decay                  # 强制 apply_decay
    python scripts/concerns_dump.py --reflect-now            # 立刻让 WeeklyReflector 跑一次

文件依赖：
- memory_pool/concerns.json         ← runtime ledger
- memory_pool/concerns_review.json  ← review 队列（含 WeeklyReflector propose 内容）

规范：详 docs/JARVIS_SOUL_DRIVE.md §5 + §6
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

from jarvis_concerns import (
    ConcernsLedger,
    bootstrap_default_concerns,
    STATE_ACTIVE, STATE_REVIEW, STATE_ARCHIVED, STATE_SNOOZED,
)


def _load_ledger() -> ConcernsLedger:
    """构造 ledger，恢复 disk 状态，但不启动 decay daemon。"""
    ledger = ConcernsLedger()
    bootstrap_default_concerns(ledger)
    ledger.load()
    return ledger


def _print_table(ledger: ConcernsLedger) -> None:
    print(ledger.dump_human())


def _print_review(ledger: ConcernsLedger) -> None:
    review = ledger.list_review()
    if not review:
        print("[REVIEW QUEUE] 空（WeeklyReflector 尚未 propose 新 concerns / Sir 已全部拍板）")
        print("  Tip: WeeklyReflector 默认 7 天 LLM 反思一次。强制立刻跑：")
        print("    python scripts/concerns_dump.py --reflect-now")
        return
    print("=" * 80)
    print(f"[REVIEW QUEUE] {len(review)} concerns 等 Sir 拍板")
    print("=" * 80)
    for c in review:
        print(f"  id          : {c.id}")
        print(f"  what_i_watch: {c.what_i_watch}")
        print(f"  why_i_care  : {c.why_i_care}")
        print(f"  severity    : {c.severity:.2f}")
        print(f"  source      : {c.source} ({c.source_marker})")
        print(f"  created_at  : {time.strftime('%Y-%m-%d %H:%M', time.localtime(c.created_at))}")
        print()
    print("Sir 操作：")
    print("  python scripts/concerns_dump.py --activate <id>   # 通过")
    print("  python scripts/concerns_dump.py --reject   <id>   # 拒绝")


def _activate(ledger: ConcernsLedger, cid: str) -> int:
    c = ledger.get(cid)
    if c is None:
        print(f"[ERROR] concern '{cid}' 不存在")
        return 2
    old = c.state
    ok = ledger.activate(cid)
    ledger.persist()
    ledger.write_review_queue()
    print(f"[OK] '{cid}' {old} → ACTIVE (returned={ok})")
    return 0


def _reject(ledger: ConcernsLedger, cid: str) -> int:
    c = ledger.get(cid)
    if c is None:
        print(f"[ERROR] concern '{cid}' 不存在")
        return 2
    old = c.state
    ok = ledger.reject(cid)
    ledger.persist()
    ledger.write_review_queue()
    print(f"[OK] '{cid}' {old} → ARCHIVED (rejected) (returned={ok})")
    return 0


def _snooze(ledger: ConcernsLedger, cid: str, hours: float) -> int:
    c = ledger.get(cid)
    if c is None:
        print(f"[ERROR] concern '{cid}' 不存在")
        return 2
    old = c.state
    ok = ledger.snooze(cid, hours=hours)
    ledger.persist()
    print(f"[OK] '{cid}' {old} → SNOOZED for {hours}h (returned={ok})")
    return 0


def _force_decay(ledger: ConcernsLedger) -> None:
    stats = ledger.apply_decay()
    ledger.persist()
    print(f"[DECAY] archived={stats['archived']} unsnoozed={stats['unsnoozed']}")


def _print_json(ledger: ConcernsLedger) -> None:
    snapshot = {}
    for cid, c in ledger.concerns.items():
        snapshot[cid] = c.to_dict()
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


def _reflect_now(ledger: ConcernsLedger) -> int:
    """[β.2.5] 强制 WeeklyReflector 跑一次（不用等 7 天）。
    场景：Sir 刚加了 50+ 条 STM 想立刻看 reflector 能不能 propose 出来。

    注意：本 CLI 是独立 process，没法直接调主 daemon 的 force_run_now。
    我们直接实例化 WeeklyReflector，传 stm_provider 读 jarvis_memory.db 的
    ConversationHistory 表（hippocampus STM），跑一次。
    """
    print("[reflect-now] 立刻让 WeeklyReflector 反思一次...")
    try:
        from jarvis_key_router import KeyRouter, _ALL_KEYS as _allkeys  # noqa: F401
    except Exception as e:
        print(f"[ERROR] key_router 不可用: {e}")
        print("        (CLI 反射需要 KeyRouter 提供 openrouter_key)")
        return 2

    try:
        from jarvis_config.keys import load_keys
        from jarvis_key_router import KeyRouter
        _keys = load_keys()
        kr = KeyRouter(_keys.google_keys, _keys.openrouter_keys)
    except Exception as e:
        print(f"[ERROR] KeyRouter 初始化失败: {e}")
        return 2

    # STM provider：读 ConversationHistory 表最近 50 条
    def _stm_from_sqlite():
        import sqlite3
        db = os.path.join('memory_pool', 'jarvis_memory.db')
        if not os.path.exists(db):
            return []
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            cur.execute(
                'SELECT user_input, jarvis_reply, timestamp '
                'FROM ConversationHistory ORDER BY id DESC LIMIT 50'
            )
            rows = cur.fetchall()
            conn.close()
            stm = []
            for u, j, t in reversed(rows):
                stm.append({'user': u or '', 'jarvis': j or '',
                            'time': time.strftime('%H:%M', time.localtime(t)) if t else ''})
            return stm
        except Exception:
            return []

    def _profile_loader():
        try:
            p = os.path.join('jarvis_config', 'sir_profile.json')
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    from jarvis_soul_reflector import WeeklyReflector
    reflector = WeeklyReflector(
        concerns_ledger=ledger,
        key_router=kr,
        stm_provider=_stm_from_sqlite,
        profile_provider=_profile_loader,
    )
    result = reflector.force_run_now()
    print(f"[reflect-now] result: {result}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Concerns Ledger CLI Dump (灵魂工程 Layer 1 + Layer 4)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--review', action='store_true',
                        help='列 WeeklyReflector 提名待审 (state=review)')
    parser.add_argument('--activate', metavar='CONCERN_ID',
                        help='把指定 concern 转 active（Sir 通过）')
    parser.add_argument('--reject', metavar='CONCERN_ID',
                        help='把指定 concern 转 archived（Sir 拒绝）')
    parser.add_argument('--snooze', metavar='CONCERN_ID',
                        help='把指定 concern 暂停 N 小时')
    parser.add_argument('--hours', type=float, default=24.0,
                        help='snooze 小时数（默认 24）')
    parser.add_argument('--json', action='store_true',
                        help='机读 JSON 输出（覆盖 ASCII 表）')
    parser.add_argument('--decay', action='store_true',
                        help='强制触发 apply_decay 一次')
    parser.add_argument('--reflect-now', action='store_true',
                        help='强制 WeeklyReflector 立刻跑一次反思（不用等 7d）')
    args = parser.parse_args()

    ledger = _load_ledger()

    if args.activate:
        return _activate(ledger, args.activate)
    if args.reject:
        return _reject(ledger, args.reject)
    if args.snooze:
        return _snooze(ledger, args.snooze, args.hours)
    if args.review:
        _print_review(ledger)
        return 0
    if args.decay:
        _force_decay(ledger)
        return 0
    if args.reflect_now:
        return _reflect_now(ledger)
    if args.json:
        _print_json(ledger)
        return 0

    _print_table(ledger)
    return 0


if __name__ == '__main__':
    sys.exit(main())
