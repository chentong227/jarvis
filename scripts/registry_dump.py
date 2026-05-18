# -*- coding: utf-8 -*-
"""[P0+20-β.0.4 / 2026-05-16, β.4.6 / 2026-05-18] Directive Registry CLI Dump

让 Sir 一行命令看 18 条 L2 directive 的健康度（fired / rejected / helped / state）.
β.4.6 加 vocab 编辑命令: --show / --edit-text / --archive (Sir 改 directive text 不需改 .py).

用法（runtime 计数维度）:
    python scripts/registry_dump.py                    # 默认 ASCII 表
    python scripts/registry_dump.py --review           # 只列 review 队列（rejected >= 3）
    python scripts/registry_dump.py --activate <id>    # Sir 手动激活某条 dormant/review
    python scripts/registry_dump.py --json             # 机读 JSON 输出（管道可用）
    python scripts/registry_dump.py --decay            # 触发一次 apply_decay 看会发生什么

用法（β.4.6 vocab 编辑维度 / Sir 改 directive 措辞）:
    python scripts/registry_dump.py --show <id>            # 看某 directive 的 text 全文 + metadata
    python scripts/registry_dump.py --edit-text <id> --new-text-file <path>
                                                            # 用文件内容替换 directive text (state 不变)
    python scripts/registry_dump.py --archive <id>         # 永久关闭 (state → archived)
    python scripts/registry_dump.py --vocab-list           # 列 vocab JSON 全部 directive (id/state/priority)

文件依赖:
- memory_pool/directive_registry.json   ← runtime 计数 (gitignored)
- memory_pool/directive_review.json     ← legacy review 队列 (rejected≥3 触发)
- memory_pool/directives_vocab.json     ← β.4.6 主 vocab (text+metadata, in repo)

规范: 详 docs/PROMPT_REFACTOR_PLAN.md §6 + §8 + AGENTS.md 准则 6.5
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time


# Windows console GBK 不能 emoji / 中文非 GBK, 强制 stdout utf-8 (类 claim_classify_dump.py β.4.3.1 模式)
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    DirectiveRegistry,
    bootstrap_default_registry,
    STATE_ACTIVE,
    STATE_DORMANT,
    STATE_REVIEW,
    STATE_ARCHIVED,
)


VOCAB_PATH = os.path.join('memory_pool', 'directives_vocab.json')


def _load_runtime_registry() -> DirectiveRegistry:
    """构造一个 registry，从 disk 恢复 runtime 计数，但不启动 decay daemon。"""
    reg = DirectiveRegistry()
    bootstrap_default_registry(reg)
    n = reg.load()
    return reg


def _print_table(reg: DirectiveRegistry, days_window: int = 7) -> None:
    print(reg.dump_human(days_window=days_window))


def _print_review_queue() -> None:
    review_path = os.path.join('memory_pool', 'directive_review.json')
    if not os.path.exists(review_path):
        print(f"[REVIEW] {review_path} 不存在（无 review 队列 / decay 还没跑出 review state）")
        return
    try:
        with open(review_path, 'r', encoding='utf-8') as f:
            data = json.load(f) or []
    except Exception as e:
        print(f"[REVIEW] 读取失败: {e}")
        return
    if not data:
        print(f"[REVIEW] 空队列")
        return
    print(f"[REVIEW] {len(data)} 条 directive 等 Sir 审阅:")
    print()
    for i, e in enumerate(data, 1):
        print(f"  #{i} {e.get('id', 'unknown')}")
        print(f"     marker={e.get('source_marker', '')} fired={e.get('fired')} "
              f"rejected={e.get('rejected')} (rate={e.get('rej_rate'):.0%})")
        print(f"     last_rejected={e.get('last_rejected_iso', '')}")
        print(f"     enqueued_at={e.get('enqueued_at', '')}")
        print(f"     text_preview: {e.get('text_preview', '')[:120]!r}")
        print()


def _activate(reg: DirectiveRegistry, did: str) -> None:
    d = reg.get(did)
    if d is None:
        print(f"[ACTIVATE] directive '{did}' 不存在")
        return
    old_state = d.state
    if old_state == STATE_ACTIVE:
        print(f"[ACTIVATE] '{did}' 已是 active，无操作")
        return
    with reg._lock:
        d.state = STATE_ACTIVE
        d.rejected = 0  # 复位 rejected 计数避免立刻又被 decay 推回 review
        reg._dirty = True
    reg.persist()
    print(f"[ACTIVATE] '{did}' state {old_state} → {STATE_ACTIVE} (rejected reset to 0)")


def _print_json(reg: DirectiveRegistry) -> None:
    snapshot = {}
    with reg._lock:
        for did, d in reg.directives.items():
            snapshot[did] = {
                'priority': d.priority,
                'state': d.state,
                'fired': d.fired,
                'rejected': d.rejected,
                'helped': d.helped,
                'last_triggered': d.last_triggered,
                'last_rejected': d.last_rejected,
                'last_helped': d.last_helped,
                'tier_whitelist': list(d.tier_whitelist),
                'ttl_days': d.ttl_days,
                'source_marker': d.source_marker,
            }
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


def _force_decay(reg: DirectiveRegistry) -> None:
    print("[DECAY] 调用 apply_decay()...")
    stats = reg.apply_decay()
    print(f"[DECAY] result: dormant={stats['dormant']} review={stats['review']} "
          f"priority_drop={stats['priority_drop']}")
    persisted = reg.persist()
    print(f"[DECAY] persist: {'写盘' if persisted else '无变更'}")


# ============================================================
# β.4.6 vocab 编辑命令 (Sir 改 directive text/state 不需改 .py)
# ============================================================

def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        print(f"❌ {VOCAB_PATH} 不存在 (运行一次 Jarvis 让 bootstrap 写默认 seed, 或手动创建)")
        sys.exit(1)
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"❌ 读 {VOCAB_PATH} 失败: {e}")
        sys.exit(1)


def _save_vocab(vocab: dict) -> None:
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def _cmd_show_directive(did: str) -> int:
    """看某 directive 的 text 全文 + metadata."""
    vocab = _load_vocab()
    for entry in vocab.get('directives', []):
        if entry.get('id') == did:
            print(f"\n{'='*70}")
            print(f"id           = {entry.get('id')}")
            print(f"state        = {entry.get('state', 'active')}")
            print(f"priority     = {entry.get('priority', 5)}")
            print(f"tier_whitelist = {entry.get('tier_whitelist') or '(全 tier)'}")
            print(f"ttl_days     = {entry.get('ttl_days', 30)}")
            print(f"source_marker= {entry.get('source_marker', '-')}")
            print(f"source       = {entry.get('source', 'seed')}")
            note = entry.get('note', '')
            if note:
                print(f"note         = {note}")
            print(f"{'='*70}")
            print(f"--- text ---")
            print(entry.get('text', ''))
            print(f"{'='*70}\n")
            return 0
    print(f"❌ directive '{did}' 不在 {VOCAB_PATH}")
    return 1


def _cmd_vocab_list() -> int:
    """列 vocab JSON 全部 directive (id/state/priority/marker)."""
    vocab = _load_vocab()
    directives = vocab.get('directives', [])
    print(f"\n[VOCAB] {VOCAB_PATH} — {len(directives)} directives\n")
    state_emoji = {
        'active': '✅', 'dormant': '💤', 'review': '⏳', 'archived': '🗄️',
    }
    by_state: dict = {}
    for d in directives:
        s = d.get('state', 'active')
        by_state.setdefault(s, []).append(d)
    for s in ('active', 'review', 'dormant', 'archived'):
        items = by_state.get(s, [])
        if not items:
            continue
        print(f"  {state_emoji.get(s, '?')} {s} ({len(items)})")
        for d in sorted(items, key=lambda x: -int(x.get('priority', 5))):
            text_preview = (d.get('text') or '').replace('\n', ' ')[:70]
            ellipsis = '...' if len(d.get('text', '')) > 70 else ''
            print(f"    {d.get('id', '?'):<32} prio={d.get('priority', 5)} "
                   f"src={(d.get('source_marker') or '-')[:14]:<14} "
                   f"text='{text_preview}{ellipsis}'")
        print()
    return 0


def _cmd_edit_text(did: str, new_text_file: str) -> int:
    """用文件内容替换 directive text. state 不变."""
    if not os.path.exists(new_text_file):
        print(f"❌ new-text-file '{new_text_file}' 不存在")
        return 1
    try:
        with open(new_text_file, 'r', encoding='utf-8') as f:
            new_text = f.read().rstrip()
    except OSError as e:
        print(f"❌ 读 {new_text_file} 失败: {e}")
        return 1
    if not new_text:
        print(f"❌ {new_text_file} 内容为空, 拒绝写入")
        return 1
    vocab = _load_vocab()
    for entry in vocab.get('directives', []):
        if entry.get('id') == did:
            old_len = len(entry.get('text', ''))
            entry['text'] = new_text
            entry['note'] = (
                f"[β.4.6 Sir CLI edit @ {time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"text 改自 {old_len}b → {len(new_text)}b"
            )
            _save_vocab(vocab)
            print(f"✅ '{did}' text 已更新 ({old_len}b → {len(new_text)}b). "
                   f"重启 Jarvis 生效 (mtime cache 自动 reload)")
            return 0
    print(f"❌ directive '{did}' 不在 {VOCAB_PATH}")
    return 1


def _cmd_archive_directive(did: str) -> int:
    """state → archived (永久关闭, 主链不再注册此 directive)."""
    vocab = _load_vocab()
    for entry in vocab.get('directives', []):
        if entry.get('id') == did:
            old_state = entry.get('state', 'active')
            entry['state'] = STATE_ARCHIVED
            entry['note'] = (
                f"[β.4.6 Sir CLI archive @ {time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"state {old_state} → archived"
            )
            _save_vocab(vocab)
            print(f"✅ '{did}' state {old_state} → archived (主链下次 bootstrap 不再注册)")
            return 0
    print(f"❌ directive '{did}' 不在 {VOCAB_PATH}")
    return 1


def main():
    parser = argparse.ArgumentParser(description='Directive Registry CLI Dump')
    # runtime 计数维度
    parser.add_argument('--review', action='store_true', help='只列 review 队列')
    parser.add_argument('--activate', metavar='DIRECTIVE_ID',
                        help='把指定 directive 从 dormant/review 激活回 active')
    parser.add_argument('--json', action='store_true', help='输出机读 JSON（覆盖 ASCII 表）')
    parser.add_argument('--decay', action='store_true', help='强制触发一次 apply_decay')
    parser.add_argument('--days', type=int, default=7, help='ASCII 表 last_X_days 窗口（默认 7）')
    # β.4.6 vocab 编辑维度
    parser.add_argument('--show', metavar='DIRECTIVE_ID',
                        help='看某 directive 的 text 全文 + metadata')
    parser.add_argument('--vocab-list', action='store_true',
                        help='列 vocab JSON 全部 directive (按 state 分组)')
    parser.add_argument('--edit-text', metavar='DIRECTIVE_ID',
                        help='用 --new-text-file 内容替换 directive text')
    parser.add_argument('--new-text-file', metavar='PATH',
                        help='--edit-text 的新 text 文件路径')
    parser.add_argument('--archive', metavar='DIRECTIVE_ID',
                        help='永久关闭某 directive (state → archived)')
    args = parser.parse_args()

    # β.4.6 vocab 命令 (不需要 runtime registry)
    if args.show:
        return _cmd_show_directive(args.show)
    if args.vocab_list:
        return _cmd_vocab_list()
    if args.edit_text:
        if not args.new_text_file:
            print("❌ --edit-text 必须配 --new-text-file <path>")
            return 1
        return _cmd_edit_text(args.edit_text, args.new_text_file)
    if args.archive:
        return _cmd_archive_directive(args.archive)

    # runtime 计数命令 (需要 registry)
    reg = _load_runtime_registry()

    if args.review:
        _print_review_queue()
        return 0

    if args.activate:
        _activate(reg, args.activate)
        return 0

    if args.decay:
        _force_decay(reg)
        return 0

    if args.json:
        _print_json(reg)
        return 0

    _print_table(reg, days_window=args.days)
    return 0


if __name__ == '__main__':
    sys.exit(main())
