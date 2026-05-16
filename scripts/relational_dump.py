# -*- coding: utf-8 -*-
"""[P0+20-β.2.2 / 2026-05-16] Relational State CLI Dump

让 Sir 一行命令录入 / 查看 / 管理 Layer 2 RelationalState：
- inside_jokes（我们的笑点）
- unspoken_protocols（我们的默契）
- unfinished_business（未竟之事）

经典用法（来自 Sir 2026-05-16 21:57 实测）：

    python scripts/relational_dump.py --add-inside-joke \
      --phrase "becoming... overbearing" \
      --birth-context "Sir 21:57:23 反讽 'overly meddlesome' → Jarvis 用省略号自嘲" \
      --tone "wry, self-deprecating"

更多用法：

    python scripts/relational_dump.py                          # 默认 ASCII 表
    python scripts/relational_dump.py --list                   # 同 ASCII 表
    python scripts/relational_dump.py --list-jokes             # 只列 inside jokes
    python scripts/relational_dump.py --list-protocols         # 只列 protocols
    python scripts/relational_dump.py --list-unfinished        # 只列 unfinished business
    python scripts/relational_dump.py --json                   # 机读 JSON

    # 录入：
    python scripts/relational_dump.py --add-inside-joke \
        --phrase "<短语>" --birth-context "<情境>" --tone "<调性>"

    python scripts/relational_dump.py --add-protocol \
        --rule "<我应当 X / 我不应当 Y>"

    python scripts/relational_dump.py --add-unfinished \
        --topic "<主题>" --detail "<详情>" --next-touch-due "2026-05-20 10:00"

    # 管理：
    python scripts/relational_dump.py --archive <id>           # 归档（任意一类）
    python scripts/relational_dump.py --done <ub_id>           # UB 标完成
    python scripts/relational_dump.py --pause <ub_id>          # UB 暂停
    python scripts/relational_dump.py --resume <ub_id>         # UB 恢复
    python scripts/relational_dump.py --decay                  # 触发一次 decay
    python scripts/relational_dump.py --show-prompt            # 打印将注入 prompt 的块

文件依赖：
- memory_pool/relational_state.json   ← runtime 状态

规范：详 docs/JARVIS_SOUL_DRIVE.md §2.2 + §3.3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


# [P0+20-β.2.2 fix / 2026-05-16] PowerShell 控制台中文乱码修复：
# - Python stdout/stderr reconfigure 到 UTF-8（让 Python 输出 UTF-8 bytes）
# - chcp 65001 切控制台 code page（让 PowerShell 按 UTF-8 解读 bytes）
# 二者缺一不可。jarvis_utils.py 启动时已做第 1 步，但 CLI 单独跑不走那条路径。
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

from jarvis_relational import (
    RelationalStateStore,
    InsideJoke,
    UnspokenProtocol,
    UnfinishedBusiness,
    SharedHistoryThread,
    make_joke_id,
    make_protocol_id,
    make_ub_id,
    make_thread_id,
    STATE_ACTIVE,
    STATE_ARCHIVED,
    UB_OPEN,
    UB_PAUSED,
    UB_DONE,
)


# ============================================================
# 工具：解析时间字符串 "2026-05-20 10:00" / "2026-05-20T10:00" / 空 = 0
# ============================================================

def _parse_due(s: str) -> float:
    if not s or not s.strip():
        return 0.0
    s = s.strip().replace('T', ' ')
    try:
        return time.mktime(time.strptime(s, '%Y-%m-%d %H:%M'))
    except Exception:
        pass
    try:
        return time.mktime(time.strptime(s, '%Y-%m-%d %H:%M:%S'))
    except Exception:
        pass
    try:
        return time.mktime(time.strptime(s, '%Y-%m-%d'))
    except Exception:
        pass
    print(f"[ERROR] 无法解析时间 '{s}'，支持格式：'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DD'")
    sys.exit(2)


# ============================================================
# 操作函数
# ============================================================

def _load_store(custom_path: str = None) -> RelationalStateStore:
    """加载 store（不启动 daemon）。"""
    s = RelationalStateStore(persist_path=custom_path)
    s.load()
    return s


def _add_inside_joke(args) -> int:
    if not args.phrase:
        print("[ERROR] --phrase 必填")
        return 2
    s = _load_store(args.persist_path)
    joke = InsideJoke(
        id=args.id or make_joke_id(args.phrase),
        phrase=args.phrase[:120],
        birth_context=(args.birth_context or '')[:400],
        tone=(args.tone or '')[:60],
        source='sir_added',
        source_marker=args.marker or f"sir_cli_{time.strftime('%Y%m%d_%H%M%S')}",
        birth_turn_id=args.turn_id or '',
    )
    ok = s.add_inside_joke(joke)
    if not ok:
        print(f"[SKIP] inside_joke '{joke.id}' 已存在，未覆盖")
        return 1
    s._dirty = True
    persisted = s.persist()
    print(f"[OK] 已录入 inside_joke")
    print(f"  id       : {joke.id}")
    print(f"  phrase   : {joke.phrase!r}")
    print(f"  tone     : {joke.tone or '-'}")
    print(f"  birth_ctx: {joke.birth_context or '-'}")
    print(f"  persisted: {persisted} (path={s.persist_path})")
    return 0


def _add_protocol(args) -> int:
    if not args.rule:
        print("[ERROR] --rule 必填")
        return 2
    s = _load_store(args.persist_path)
    proto = UnspokenProtocol(
        id=args.id or make_protocol_id(args.rule),
        rule=args.rule[:300],
        source='sir_added',
        source_marker=args.marker or f"sir_cli_{time.strftime('%Y%m%d_%H%M%S')}",
        learned_from_turn_id=args.turn_id or '',
    )
    ok = s.add_protocol(proto)
    if not ok:
        print(f"[SKIP] protocol '{proto.id}' 已存在，未覆盖")
        return 1
    s._dirty = True
    persisted = s.persist()
    print(f"[OK] 已录入 protocol")
    print(f"  id       : {proto.id}")
    print(f"  rule     : {proto.rule!r}")
    print(f"  persisted: {persisted} (path={s.persist_path})")
    return 0


def _add_unfinished(args) -> int:
    if not args.topic:
        print("[ERROR] --topic 必填")
        return 2
    s = _load_store(args.persist_path)
    ub = UnfinishedBusiness(
        id=args.id or make_ub_id(args.topic),
        topic=args.topic[:120],
        detail=(args.detail or '')[:300],
        next_touch_due=_parse_due(args.next_touch_due) if args.next_touch_due else 0.0,
        source='sir_added',
        source_marker=args.marker or f"sir_cli_{time.strftime('%Y%m%d_%H%M%S')}",
        origin_turn_id=args.turn_id or '',
    )
    ok = s.add_unfinished(ub)
    if not ok:
        print(f"[SKIP] unfinished '{ub.id}' 已存在，未覆盖")
        return 1
    s._dirty = True
    persisted = s.persist()
    print(f"[OK] 已录入 unfinished_business")
    print(f"  id        : {ub.id}")
    print(f"  topic     : {ub.topic!r}")
    print(f"  detail    : {ub.detail or '-'}")
    due_str = '-' if ub.next_touch_due <= 0 else time.strftime(
        '%Y-%m-%d %H:%M', time.localtime(ub.next_touch_due)
    )
    print(f"  next_due  : {due_str}")
    print(f"  persisted : {persisted} (path={s.persist_path})")
    return 0


def _add_thread(args) -> int:
    if not args.title:
        print("[ERROR] --title 必填")
        return 2
    s = _load_store(args.persist_path)
    thread = SharedHistoryThread(
        id=args.id or make_thread_id(args.title),
        title=args.title[:120],
        detail=(args.detail or '')[:300],
        source='sir_added',
        source_marker=args.marker or f"sir_cli_{time.strftime('%Y%m%d_%H%M%S')}",
    )
    ok = s.add_thread(thread)
    if not ok:
        print(f"[SKIP] thread '{thread.id}' 已存在，未覆盖")
        return 1
    s._dirty = True
    persisted = s.persist()
    print(f"[OK] 已录入 shared_history_thread")
    print(f"  id        : {thread.id}")
    print(f"  title     : {thread.title!r}")
    print(f"  detail    : {thread.detail or '-'}")
    print(f"  persisted : {persisted} (path={s.persist_path})")
    return 0


def _add_highlight(args) -> int:
    if not args.thread_id:
        print("[ERROR] --thread-id 必填")
        return 2
    if not args.what:
        print("[ERROR] --what 必填")
        return 2
    s = _load_store(args.persist_path)
    if s.get_thread(args.thread_id) is None:
        print(f"[ERROR] thread '{args.thread_id}' 不存在")
        return 2
    ok = s.record_thread_highlight(args.thread_id, args.what[:200])
    persisted = s.persist()
    print(f"[OK] thread '{args.thread_id}' 加入 highlight (ok={ok})")
    print(f"  what      : {args.what[:80]!r}")
    print(f"  persisted : {persisted}")
    return 0


def _archive_any(args) -> int:
    """归档：自动判断是 joke / protocol / ub / thread。"""
    s = _load_store(args.persist_path)
    target = args.archive
    did = False
    kind = ''
    if s.get_inside_joke(target) is not None:
        did = s.archive_inside_joke(target)
        kind = 'inside_joke'
    elif s.get_protocol(target) is not None:
        did = s.archive_protocol(target)
        kind = 'protocol'
    elif s.get_unfinished(target) is not None:
        did = s.mark_unfinished_done(target)
        kind = 'unfinished_business → done'
    elif s.get_thread(target) is not None:
        did = s.archive_thread(target)
        kind = 'shared_history_thread'
    else:
        print(f"[ERROR] id '{target}' 不存在于任何一类")
        return 2
    s.persist()
    print(f"[OK] {kind} '{target}' 已归档 (returned={did})")
    return 0


def _ub_op(args, op: str) -> int:
    s = _load_store(args.persist_path)
    target = getattr(args, op)
    fn = {'done': s.mark_unfinished_done,
          'pause': s.pause_unfinished,
          'resume': s.resume_unfinished}[op]
    if s.get_unfinished(target) is None:
        print(f"[ERROR] unfinished_business '{target}' 不存在")
        return 2
    ok = fn(target)
    s.persist()
    print(f"[OK] unfinished '{target}' --{op} (ok={ok})")
    return 0


def _print_table(s: RelationalStateStore) -> None:
    print(s.dump_human())


def _print_jokes(s: RelationalStateStore) -> None:
    jokes = s.list_inside_jokes()
    if not jokes:
        print("[INSIDE JOKES] (empty)")
        return
    print(f"[INSIDE JOKES] {len(jokes)} active")
    print("-" * 80)
    for j in sorted(jokes, key=lambda x: -x.created_at):
        print(f"  id     : {j.id}")
        print(f"  phrase : {j.phrase!r}")
        print(f"  tone   : {j.tone or '-'}")
        print(f"  born   : {j.birth_context or '-'}")
        if j.last_used > 0:
            print(f"  used   : {j.use_count} times, last "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(j.last_used))}")
        else:
            print(f"  used   : 0 times")
        print()


def _print_protocols(s: RelationalStateStore) -> None:
    protos = s.list_protocols()
    if not protos:
        print("[UNSPOKEN PROTOCOLS] (empty)")
        return
    print(f"[UNSPOKEN PROTOCOLS] {len(protos)} active")
    print("-" * 80)
    for p in protos:
        print(f"  id        : {p.id}")
        print(f"  rule      : {p.rule!r}")
        print(f"  violations: {len(p.violations)}")
        if p.violations:
            for v in p.violations[-3:]:
                print(f"    - {v.get('when_iso', '')}: {v.get('what', '')[:100]}")
        print()


def _print_unfinished(s: RelationalStateStore) -> None:
    ubs = s.list_unfinished()
    if not ubs:
        print("[UNFINISHED BUSINESS] (empty)")
        return
    print(f"[UNFINISHED BUSINESS] {len(ubs)} active")
    print("-" * 80)
    now = time.time()
    for u in sorted(ubs, key=lambda x: x.last_touched):
        age_h = (now - u.last_touched) / 3600
        age_str = f"{age_h:.1f}h ago" if age_h < 48 else f"{age_h / 24:.1f}d ago"
        overdue = " [OVERDUE]" if u.is_overdue() else ""
        due_str = time.strftime(
            '%Y-%m-%d %H:%M', time.localtime(u.next_touch_due)
        ) if u.next_touch_due > 0 else '-'
        print(f"  id      : {u.id} [{u.state}]{overdue}")
        print(f"  topic   : {u.topic!r}")
        if u.detail:
            print(f"  detail  : {u.detail}")
        print(f"  touched : {age_str}")
        print(f"  due     : {due_str}")
        print()


def _print_threads(s: RelationalStateStore) -> None:
    threads = s.list_threads()
    if not threads:
        print("[SHARED HISTORY THREADS] (empty)")
        return
    print(f"[SHARED HISTORY THREADS] {len(threads)} active")
    print("-" * 80)
    now = time.time()
    for t in sorted(threads, key=lambda x: -x.last_milestone_at):
        age_days = (now - t.last_milestone_at) / 86400
        print(f"  id        : {t.id}")
        print(f"  title     : {t.title!r}")
        if t.detail:
            print(f"  detail    : {t.detail}")
        print(f"  highlights: {len(t.highlights)}")
        for h in t.highlights[-3:]:
            print(f"    - {h.get('when_iso', '')}: {h.get('what', '')[:100]}")
        print(f"  last touched: {age_days:.1f}d ago")
        print()


def _print_json(s: RelationalStateStore) -> None:
    snapshot = {
        'inside_jokes': {jid: j.to_dict() for jid, j in s.inside_jokes.items()},
        'unspoken_protocols': {pid: p.to_dict() for pid, p in s.unspoken_protocols.items()},
        'unfinished_business': {uid: u.to_dict() for uid, u in s.unfinished_business.items()},
        'shared_history_threads': {
            tid: t.to_dict() for tid, t in s.shared_history_threads.items()
        },
    }
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


def _show_prompt(s: RelationalStateStore) -> None:
    block = s.to_prompt_block()
    if not block:
        print("[PROMPT BLOCK] (empty — 没有 active 数据，不会注入 prompt)")
        return
    print("=" * 80)
    print("[PROMPT BLOCK] 这是注入到 prompt 的实际内容:")
    print("=" * 80)
    print(block)
    print("=" * 80)
    print(f"  length: {len(block)} chars")


def _force_decay(s: RelationalStateStore) -> None:
    stats = s.apply_decay()
    persisted = s.persist()
    print(f"[DECAY] jokes_archived={stats['jokes_archived']} "
          f"protocols_archived={stats['protocols_archived']} "
          f"ub_archived={stats['ub_archived']}")
    print(f"[DECAY] persist: {'写盘' if persisted else '无变更'}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Relational State CLI Dump (灵魂工程 Layer 2)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--persist-path', default=None,
                        help='自定义 JSON 路径（默认 memory_pool/relational_state.json）')

    # 读
    parser.add_argument('--list', action='store_true', help='默认 ASCII 表（同无参）')
    parser.add_argument('--list-jokes', action='store_true', help='只列 inside jokes')
    parser.add_argument('--list-protocols', action='store_true', help='只列 protocols')
    parser.add_argument('--list-unfinished', action='store_true', help='只列 unfinished business')
    parser.add_argument('--list-threads', action='store_true',
                        help='只列 shared history threads')
    parser.add_argument('--json', action='store_true', help='机读 JSON')
    parser.add_argument('--show-prompt', action='store_true',
                        help='打印将注入 prompt 的 [BETWEEN US] 块')

    # 写
    parser.add_argument('--add-inside-joke', action='store_true', help='录入新 inside_joke')
    parser.add_argument('--phrase', help='inside_joke 短语')
    parser.add_argument('--birth-context', help='inside_joke 诞生情境')
    parser.add_argument('--tone', help='inside_joke 调性（如 wry, self-deprecating）')

    parser.add_argument('--add-protocol', action='store_true', help='录入新 protocol')
    parser.add_argument('--rule', help='protocol 规则（第一人称命令）')

    parser.add_argument('--add-unfinished', action='store_true', help='录入新 unfinished_business')
    parser.add_argument('--topic', help='unfinished_business 主题')
    parser.add_argument('--detail', help='unfinished_business 详情（也用于 thread.detail）')
    parser.add_argument('--next-touch-due', help='下次提及截止（"YYYY-MM-DD HH:MM"）')

    parser.add_argument('--add-thread', action='store_true',
                        help='录入新 shared_history_thread（接管原 sir_profile.significant_milestones）')
    parser.add_argument('--title', help='thread 标题')

    parser.add_argument('--add-highlight', action='store_true',
                        help='给某 thread 加一条 highlight')
    parser.add_argument('--thread-id', help='目标 thread id（配合 --add-highlight）')
    parser.add_argument('--what', help='highlight 内容（配合 --add-highlight）')

    parser.add_argument('--id', help='可选：手工指定 id（不指定则从 phrase/rule/topic 自动派生）')
    parser.add_argument('--marker', help='可选：source_marker（默认 sir_cli_YYYYMMDD_HHMMSS）')
    parser.add_argument('--turn-id', help='可选：诞生时的 turn_id')

    # 管理
    parser.add_argument('--archive', metavar='ID', help='归档（自动判类）')
    parser.add_argument('--done', metavar='UB_ID', help='UB 标完成')
    parser.add_argument('--pause', metavar='UB_ID', help='UB 暂停')
    parser.add_argument('--resume', metavar='UB_ID', help='UB 恢复')
    parser.add_argument('--decay', action='store_true', help='强制触发一次 apply_decay')

    args = parser.parse_args()

    if args.add_inside_joke:
        return _add_inside_joke(args)
    if args.add_protocol:
        return _add_protocol(args)
    if args.add_unfinished:
        return _add_unfinished(args)
    if args.add_thread:
        return _add_thread(args)
    if args.add_highlight:
        return _add_highlight(args)
    if args.archive:
        return _archive_any(args)
    if args.done:
        return _ub_op(args, 'done')
    if args.pause:
        return _ub_op(args, 'pause')
    if args.resume:
        return _ub_op(args, 'resume')

    s = _load_store(args.persist_path)

    if args.decay:
        _force_decay(s)
        return 0
    if args.json:
        _print_json(s)
        return 0
    if args.show_prompt:
        _show_prompt(s)
        return 0
    if args.list_jokes:
        _print_jokes(s)
        return 0
    if args.list_protocols:
        _print_protocols(s)
        return 0
    if args.list_unfinished:
        _print_unfinished(s)
        return 0
    if args.list_threads:
        _print_threads(s)
        return 0

    _print_table(s)
    return 0


if __name__ == '__main__':
    sys.exit(main())
