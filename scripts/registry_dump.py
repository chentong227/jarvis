# -*- coding: utf-8 -*-
"""[P0+20-β.0.4 / 2026-05-16] Directive Registry CLI Dump

让 Sir 一行命令看 13 条 L2 directive 的健康度（fired / rejected / helped / state）。

用法：
    python scripts/registry_dump.py                    # 默认 ASCII 表
    python scripts/registry_dump.py --review           # 只列 review 队列（rejected >= 3）
    python scripts/registry_dump.py --activate <id>    # Sir 手动激活某条 dormant/review
    python scripts/registry_dump.py --json             # 机读 JSON 输出（管道可用）
    python scripts/registry_dump.py --decay            # 触发一次 apply_decay 看会发生什么

文件依赖：
- memory_pool/directive_registry.json   ← runtime 计数
- memory_pool/directive_review.json     ← review 队列

规范：详 docs/PROMPT_REFACTOR_PLAN.md §6 + §8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    DirectiveRegistry,
    bootstrap_default_registry,
    STATE_ACTIVE,
    STATE_DORMANT,
    STATE_REVIEW,
)


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


def main():
    parser = argparse.ArgumentParser(description='Directive Registry CLI Dump')
    parser.add_argument('--review', action='store_true', help='只列 review 队列')
    parser.add_argument('--activate', metavar='DIRECTIVE_ID',
                        help='把指定 directive 从 dormant/review 激活回 active')
    parser.add_argument('--json', action='store_true', help='输出机读 JSON（覆盖 ASCII 表）')
    parser.add_argument('--decay', action='store_true', help='强制触发一次 apply_decay')
    parser.add_argument('--days', type=int, default=7, help='ASCII 表 last_X_days 窗口（默认 7）')
    args = parser.parse_args()

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
