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
import _cli_utils  # noqa: F401  # 🆕 [Sir Track 2] force utf-8 stdout
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
    STATE_REVIEW,
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
          f"ub_archived={stats['ub_archived']} "
          f"threads_archived={stats['threads_archived']}")
    print(f"[DECAY] persist: {'写盘' if persisted else '无变更'}")


def _print_review(s: RelationalStateStore, interactive: bool = True) -> None:
    """[β.2.4.4] 列出 SoulArchivistSentinel 自动 propose 的待审条目。

    🩹 [β.2.8.12 / 2026-05-18] Sir 反馈 "和处理关心的事一样, 每个选项跳出来 yes/no":
    interactive=True (默认) 走交互式, 一条一条问 1=activate / 2=reject / 3=skip / q=quit.
    interactive=False 仅列清单 (旧行为, 给 --review-list 用)
    """
    joke_q = s.list_inside_jokes_review()
    thread_q = s.list_threads_review()
    if not joke_q and not thread_q:
        print("[REVIEW QUEUE] 空 (没有待审 proposed_inside_jokes / proposed_shared_history_threads)")
        print("  Tip: SoulArchivistSentinel 每小时 LLM 反思一次后会写入这里")
        return

    if not interactive:
        # 非交互模式 — 仅列清单
        print("=" * 80)
        print(f"[REVIEW QUEUE] {len(joke_q)} jokes + {len(thread_q)} threads 等 Sir 拍板")
        print("=" * 80)
        if joke_q:
            print()
            print("[JOKES — 待审]")
            for j in joke_q:
                print(f"  id           : {j.id}")
                print(f"  phrase       : {j.phrase!r}")
                print(f"  tone         : {j.tone or '-'}")
                print(f"  birth_context: {j.birth_context or '-'}")
                print(f"  source       : {j.source} ({j.source_marker})")
                print()
        if thread_q:
            print("[THREADS — 待审]")
            for t in thread_q:
                print(f"  id        : {t.id}")
                print(f"  title     : {t.title!r}")
                if t.highlights:
                    print(f"  latest    : {t.highlights[-1].get('what', '')[:100]}")
                print(f"  source    : {t.source} ({t.source_marker})")
                print()
        print("Sir 命令:")
        print("  python scripts/relational_dump.py --activate <id>")
        print("  python scripts/relational_dump.py --reject   <id>")
        return

    # 交互模式 — align concerns_dump.py 风格
    total = len(joke_q) + len(thread_q)
    print("=" * 80)
    print(f"[REVIEW QUEUE] {total} 条 (含 {len(joke_q)} jokes + {len(thread_q)} threads) 等你拍板")
    print("=" * 80)
    print("每条问 4 个选项: 1=通过(activate) / 2=拒绝(archive) / 3=跳过 / q=退出")
    print()

    decisions = {'activate': [], 'reject': [], 'skip': []}
    items = []
    for j in joke_q:
        items.append(('joke', j))
    for t in thread_q:
        items.append(('thread', t))

    for idx, (kind, item) in enumerate(items, 1):
        print("-" * 80)
        if kind == 'joke':
            print(f"[{idx}/{total}]  JOKE  {item.id}")
            print(f"  phrase       : {item.phrase!r}")
            print(f"  tone         : {item.tone or '-'}")
            print(f"  birth_context: {item.birth_context or '-'}")
            print(f"  source       : {item.source} ({item.source_marker})")
        else:
            print(f"[{idx}/{total}]  THREAD  {item.id}")
            print(f"  title    : {item.title!r}")
            if item.highlights:
                print(f"  latest   : {item.highlights[-1].get('what', '')[:120]}")
            print(f"  source   : {item.source} ({item.source_marker})")
        print()
        while True:
            try:
                ans = input("  你的决定 [1=通过 / 2=拒绝 / 3=跳过 / q=退出]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n[退出]")
                _persist_interactive_review(s, decisions)
                return
            if ans in ('q', 'quit', 'exit'):
                _persist_interactive_review(s, decisions)
                print("[退出]")
                return
            if ans == '1' or ans in ('y', 'yes', '通过'):
                decisions['activate'].append(item.id)
                try:
                    s.activate_from_review(item.id)
                except Exception:
                    pass
                print(f"  ✅ 通过 → '{item.id}' 转入 active\n")
                break
            elif ans == '2' or ans in ('n', 'no', '拒绝'):
                decisions['reject'].append(item.id)
                try:
                    s.reject_from_review(item.id)
                except Exception:
                    pass
                print(f"  ❌ 拒绝 → '{item.id}' 归档\n")
                break
            elif ans == '3' or ans == '' or ans in ('skip', '跳过'):
                decisions['skip'].append(item.id)
                print(f"  ⏭️  跳过 → '{item.id}' 保持 review, 下次再问\n")
                break
            else:
                print(f"  无效输入 '{ans}', 请输 1/2/3/q")
    _persist_interactive_review(s, decisions)


def _persist_interactive_review(s: RelationalStateStore, decisions: dict) -> None:
    s.persist()
    try:
        s.write_review_queue()
    except Exception:
        pass
    print("=" * 80)
    print("[本次总结]")
    print(f"  ✅ 通过 {len(decisions['activate'])}: {decisions['activate']}")
    print(f"  ❌ 拒绝 {len(decisions['reject'])}: {decisions['reject']}")
    print(f"  ⏭️  跳过 {len(decisions['skip'])}: {decisions['skip']}")
    print("=" * 80)
    print("Sir 操作：")
    print("  python scripts/relational_dump.py --activate <id>   # 通过")
    print("  python scripts/relational_dump.py --reject   <id>   # 拒绝")


def _activate_review(s: RelationalStateStore, item_id: str) -> int:
    kind = s.activate_from_review(item_id)
    if not kind:
        print(f"[ERROR] '{item_id}' 不在 review 队列 / 不存在")
        return 2
    s.persist()
    s.write_review_queue()
    print(f"[OK] {kind} '{item_id}' → ACTIVE")
    return 0


def _reject_review(s: RelationalStateStore, item_id: str) -> int:
    kind = s.reject_from_review(item_id)
    if not kind:
        print(f"[ERROR] '{item_id}' 不在 review 队列 / 不存在")
        return 2
    s.persist()
    s.write_review_queue()
    print(f"[OK] {kind} '{item_id}' → ARCHIVED (rejected)")
    return 0


# ============================================================
# 🆕 [Sir 2026-05-28 17:05 方案 A 配套 / C2] stale review reaper CLI
# ============================================================
# Sir 真痛 dashboard 7-8 页堆积: AutoArbiter 已有 _do_stale_review_reap (15min
# tick 跑), 这里给 Sir 一个**手动 trigger 一次性扫**的 CLI flag —
# 不用等 daemon 15min, dry-run 安全看一眼 + --apply 真 archive.
def _archive_stale_reviews(s: RelationalStateStore, days: float,
                              apply: bool = False) -> int:
    """扫 3 类 review (joke/protocol/thread), 老的 (≥ N 天) archive.

    days: 多少天前 created_at → 视为 stale (默认 3 天, 同 AutoArbiter)
    apply: False = dry-run (默, 只列); True = 真 reject_from_review
    """
    if days <= 0:
        print(f"[ERROR] days must be > 0, got {days}")
        return 2
    cutoff = time.time() - days * 86400
    stale: list = []  # [(kind, item)]
    for j in s.list_inside_jokes_review():
        if j.created_at <= cutoff:
            stale.append(('joke', j))
    for p in s.list_protocols_review():
        if p.created_at <= cutoff:
            stale.append(('protocol', p))
    for t in s.list_threads_review():
        if t.created_at <= cutoff:
            stale.append(('thread', t))
    if not stale:
        print(f"[REVIEW] 没有 ≥ {days} 天的 review 待办 (cutoff="
              f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(cutoff))})")
        return 0
    print("=" * 80)
    mode = "🔴 APPLY (真 archive)" if apply else "🟡 DRY-RUN (仅列, 不改)"
    print(f"[STALE REVIEW] {len(stale)} 条 ≥ {days} 天的待办  [{mode}]")
    print(f"  cutoff: {time.strftime('%Y-%m-%d %H:%M', time.localtime(cutoff))}")
    print("=" * 80)
    by_kind: dict = {}
    for kind, item in stale:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        age_d = (time.time() - item.created_at) / 86400
        if kind == 'joke':
            label = f"phrase={item.phrase!r}"
        elif kind == 'protocol':
            label = f"rule={item.rule[:60]!r}"
        else:
            label = f"title={item.title!r}"
        print(f"  [{kind:8}] {item.id}  age={age_d:.1f}d  {label[:80]}")
    print()
    print(f"  by_kind: {by_kind}")
    if not apply:
        print()
        print("  ⚠️  DRY-RUN — 加 --apply 真 archive (走 reject_from_review):")
        print(f"     python scripts/relational_dump.py "
              f"--archive-stale-review {days} --apply")
        return 0
    # apply mode
    archived = 0
    failed = 0
    for kind, item in stale:
        try:
            res = s.reject_from_review(item.id)
            if res:
                archived += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ⚠️  failed to archive {item.id}: {e}")
            failed += 1
    s.persist()
    try:
        s.write_review_queue()
    except Exception:
        pass
    print()
    print(f"  ✅ archived: {archived}")
    if failed:
        print(f"  ❌ failed: {failed}")
    print(f"  ℹ️  Sir 元否决: dashboard 可 restore (state ARCHIVED ↔ ACTIVE)")
    return 0


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

    # Review queue (β.2.4.4): SoulArchivistSentinel 自动 propose 的条目等 Sir 拍板
    parser.add_argument('--review', action='store_true',
                        help='[β.2.8.12] 默认走交互式 — 一条一条问 1=activate / 2=reject / 3=skip / q=quit (align concerns_dump 风格)')
    parser.add_argument('--review-list', action='store_true',
                        help='仅列清单不交互 (旧 --review 行为, 给批量脚本用)')
    parser.add_argument('--activate', metavar='ID',
                        help='把 review 状态的条目转 active（Sir 通过）')
    parser.add_argument('--reject', metavar='ID',
                        help='把 review 状态的条目转 archived（Sir 拒绝）')

    # 🆕 [Sir 2026-05-28 17:05 方案 A C2] stale review reaper 手动 trigger
    parser.add_argument('--archive-stale-review', metavar='DAYS', type=float,
                        help='手动扫 ≥ N 天 review 待办自动 archive '
                             '(默 dry-run, 加 --apply 真改; 同 AutoArbiter 后台 reaper)')
    parser.add_argument('--apply', action='store_true',
                        help='配合 --archive-stale-review: 真 archive (默 dry-run)')

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

    if args.activate:
        return _activate_review(s, args.activate)
    if args.reject:
        return _reject_review(s, args.reject)
    if args.archive_stale_review is not None:
        return _archive_stale_reviews(
            s, args.archive_stale_review, apply=args.apply,
        )
    if args.review:
        _print_review(s, interactive=True)
        return 0
    if args.review_list:
        _print_review(s, interactive=False)
        return 0
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
