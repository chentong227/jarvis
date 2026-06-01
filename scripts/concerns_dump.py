# -*- coding: utf-8 -*-
"""[P0+20-β.2.5 / 2026-05-17] Concerns Ledger CLI Dump

让 Sir 一行命令查看 / 拍板 Jarvis 的内部牵挂（灵魂工程 Layer 1 + Layer 4
WeeklyReflector propose 队列）。

用法：
    python scripts/concerns_dump.py                          # 默认 ASCII 表
    python scripts/concerns_dump.py --review                 # 交互式审核（推荐，输 1/2/3/4）
    python scripts/concerns_dump.py --review --no-interactive # 只打印列表
    python scripts/concerns_dump.py --activate <id>          # 直接通过（脚本用）
    python scripts/concerns_dump.py --reject   <id>          # 直接拒绝
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
import _cli_utils  # noqa: F401  # 🆕 [Sir Track 2] force utf-8 stdout
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

# 🩹 [β.2.7.5 / 2026-05-17] CLI 独立进程不继承 Jarvis 主进程的 proxy env
# google/* / openai/* 在 Sir region 走 OpenRouter 时 403, 必须经 127.0.0.1:7890 出
os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7890')


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


def _print_review(ledger: ConcernsLedger, interactive: bool = True) -> None:
    """🩹 [β.2.7.4 / 2026-05-17] Sir 反馈"CLI 太复杂"→默认进交互模式，按数字操作。

    interactive=True 时：列出每条 → Sir 输入 1/2/3/4 拍板
    interactive=False 时：只打印列表，给 --no-interactive 使用
    """
    review = ledger.list_review()
    if not review:
        print("[REVIEW QUEUE] 空（WeeklyReflector 尚未 propose 新 concerns / Sir 已全部拍板）")
        print("  Tip: WeeklyReflector 默认 7 天 LLM 反思一次。强制立刻跑：")
        print("    python scripts/concerns_dump.py --reflect-now")
        return

    if not interactive:
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
        return

    # 交互模式
    print("=" * 80)
    print(f"[REVIEW QUEUE] {len(review)} 条 Jarvis 提议等你拍板")
    print("=" * 80)
    print("每条问 4 个选项: 1=通过(activate) / 2=拒绝(archive) / 3=暂缓24h(snooze) / 4=跳过")
    print("回车 = 跳过 / 输 q 立即退出")
    print()

    decisions = {'activate': [], 'reject': [], 'snooze': [], 'skip': []}
    for idx, c in enumerate(review, 1):
        print("-" * 80)
        print(f"[{idx}/{len(review)}]  {c.id}  (severity {c.severity:.2f})")
        print(f"  关心啥：  {c.what_i_watch}")
        print(f"  为啥关心：{c.why_i_care}")
        print(f"  来源：    {c.source} ({c.source_marker})")
        print(f"  创建时间：{time.strftime('%Y-%m-%d %H:%M', time.localtime(c.created_at))}")
        print()
        while True:
            try:
                ans = input("  你的决定 [1=通过 / 2=拒绝 / 3=暂缓 / 4=跳过 / q=退出]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n[退出]")
                _persist_interactive_result(ledger, decisions)
                return
            if ans in ('q', 'quit', 'exit'):
                _persist_interactive_result(ledger, decisions)
                print("[退出]")
                return
            if ans == '1' or ans in ('y', 'yes', '通过'):
                decisions['activate'].append(c.id)
                ledger.activate(c.id)
                print(f"  ✅ 通过 → '{c.id}' 转入 active\n")
                break
            elif ans == '2' or ans in ('n', 'no', '拒绝'):
                decisions['reject'].append(c.id)
                ledger.reject(c.id)
                print(f"  ❌ 拒绝 → '{c.id}' 归档\n")
                break
            elif ans == '3' or ans in ('s', 'snooze', '暂缓'):
                decisions['snooze'].append(c.id)
                ledger.snooze(c.id, hours=24.0)
                print(f"  ⏸️ 暂缓 24h → '{c.id}'\n")
                break
            elif ans == '4' or ans == '' or ans in ('skip', '跳过'):
                decisions['skip'].append(c.id)
                print(f"  ⏭️ 跳过 → '{c.id}' 保持 review，下次再问\n")
                break
            else:
                print(f"  无效输入 '{ans}'，请输 1/2/3/4 或 q")

    _persist_interactive_result(ledger, decisions)


def _persist_interactive_result(ledger: ConcernsLedger, decisions: dict) -> None:
    """交互结束后持久化 + 打总结。"""
    ledger.persist()
    ledger.write_review_queue()
    print("=" * 80)
    print("[本次总结]")
    print(f"  ✅ 通过 {len(decisions['activate'])}: {decisions['activate']}")
    print(f"  ❌ 拒绝 {len(decisions['reject'])}: {decisions['reject']}")
    print(f"  ⏸️ 暂缓 {len(decisions['snooze'])}: {decisions['snooze']}")
    print(f"  ⏭️ 跳过 {len(decisions['skip'])}: {decisions['skip']}")
    print("=" * 80)


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


# 🆕 [P5-fix24-concern-dismiss / 2026-05-22] Sir 18:42 痛点 — 语言控制 concern
def _dismiss(ledger: ConcernsLedger, cid: str, reason: str) -> int:
    """软关闭 concern: triggers_proactive=False + severity 上限 0.3.
    Sir 后续问起仍可被动答, 只是不再主动 nudge.
    """
    c = ledger.get(cid)
    if c is None:
        print(f"[ERROR] concern '{cid}' 不存在")
        return 2
    old_trig = c.triggers_proactive
    old_sev = c.severity
    ok = ledger.dismiss(cid, reason=reason or 'CLI dismiss', source='cli')
    ledger.persist()
    print(f"[OK] '{cid}' triggers_proactive {old_trig}→{c.triggers_proactive}, "
          f"severity {old_sev:.2f}→{c.severity:.2f} (returned={ok})")
    print(f"  reason: {reason or '(none)'}")
    print(f"  Sir 后续提及仍可答, 但 ProactiveCare 不再主动 nudge.")
    return 0


def _reactivate(ledger: ConcernsLedger, cid: str, reason: str) -> int:
    """重激活: triggers_proactive=True, severity 不动."""
    c = ledger.get(cid)
    if c is None:
        print(f"[ERROR] concern '{cid}' 不存在")
        return 2
    old_trig = c.triggers_proactive
    ok = ledger.reactivate(cid, reason=reason or 'CLI reactivate', source='cli')
    ledger.persist()
    print(f"[OK] '{cid}' triggers_proactive {old_trig}→{c.triggers_proactive} "
          f"(returned={ok})")
    print(f"  reason: {reason or '(none)'}")
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
        from jarvis_config.keys import load_keys
        from jarvis_key_router import KeyRouter
        _keys = load_keys()
        kr = KeyRouter(
            main_brain_key=_keys.OPENROUTER_MAIN,
            google_keys=_keys.GOOGLE_LIST,
            openrouter_keys=_keys.OPENROUTER_LIST,
        )
    except Exception as e:
        print(f"[ERROR] KeyRouter 初始化失败: {e}")
        print("        (CLI 反射需要 KeyRouter 提供 openrouter_key)")
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
                        help='列 WeeklyReflector 提名待审 (state=review) — 默认进交互模式')
    parser.add_argument('--no-interactive', action='store_true',
                        help='--review 时不进交互，只打印列表')
    parser.add_argument('--activate', metavar='CONCERN_ID',
                        help='把指定 concern 转 active（Sir 通过）')
    parser.add_argument('--reject', metavar='CONCERN_ID',
                        help='把指定 concern 转 archived（Sir 拒绝）')
    parser.add_argument('--snooze', metavar='CONCERN_ID',
                        help='把指定 concern 暂停 N 小时')
    parser.add_argument('--hours', type=float, default=24.0,
                        help='snooze 小时数（默认 24）')
    # 🆕 [P5-fix24-concern-dismiss / 2026-05-22]
    parser.add_argument('--dismiss', metavar='CONCERN_ID',
                        help='软关闭 concern (Sir 不在意了): triggers_proactive=False, '
                             'severity 上限 0.3, Sir 后续仍可被动问起')
    parser.add_argument('--reactivate', metavar='CONCERN_ID',
                        help='重激活 dismissed concern: triggers_proactive=True')
    parser.add_argument('--reason', default='',
                        help='dismiss/reactivate 原因 (写进 signal + notes_for_self)')
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
    if args.dismiss:
        return _dismiss(ledger, args.dismiss, args.reason)
    if args.reactivate:
        return _reactivate(ledger, args.reactivate, args.reason)
    if args.review:
        _print_review(ledger, interactive=(not args.no_interactive))
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
