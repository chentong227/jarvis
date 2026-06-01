# -*- coding: utf-8 -*-
"""[P5-Gap4 / 2026-05-21 18:18] Directive Meta CLI — purpose_short + cluster 分析

Gap 4 治根 directive cluster 元层. 此 CLI 专注:
  - 看每条 directive 的 purpose_short (1 句话描述)
  - 看哪些 directive 缺 purpose_short (lazy 填提醒)
  - 看最近 N turn 的 fired cluster (谁经常一起 fire)
  - 看潜在冲突 (P10 vs P10 经常一起 fire 的组合)

跟 registry_dump.py 的关系:
  - registry_dump.py 看 runtime 计数 (fired/rejected/helped/state) 维度
  - 本 CLI 看元层视角 (purpose_short / cluster / 冲突)

用法:
    python scripts/directive_meta_dump.py --purpose-shorts        # 列所有 directive purpose_short
    python scripts/directive_meta_dump.py --missing                # 列缺 purpose_short 的
    python scripts/directive_meta_dump.py --priority-gte 10        # 只列 P10+
    python scripts/directive_meta_dump.py --recent-fires 20        # 看最近 N turn fired cluster
    python scripts/directive_meta_dump.py --conflicts              # 找经常冲突的 directive 组合 (LLM 辅助, 留 TODO)

详 docs/JARVIS_DIRECTIVE_SELF_AWARENESS.md
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import _cli_utils  # noqa: F401  # 🆕 [Sir Track 2] force utf-8 stdout


# Windows console UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    DirectiveRegistry,
    bootstrap_default_registry,
    STATE_ACTIVE,
)


def _icon(priority: int) -> str:
    if priority >= 12:
        return '🔴'
    if priority >= 11:
        return '🟠'
    if priority >= 10:
        return '🟡'
    if priority >= 8:
        return '⚪'
    return '·'


def list_purpose_shorts(reg: DirectiveRegistry, *, priority_gte: int = 0,
                          missing_only: bool = False) -> None:
    """列所有 directive 的 purpose_short."""
    items = sorted(reg.directives.values(),
                    key=lambda d: (-d.priority, d.id))
    if priority_gte > 0:
        items = [d for d in items if d.priority >= priority_gte]
    if missing_only:
        items = [d for d in items if not (d.purpose_short or '').strip()]

    if not items:
        print(f"(no directives matching filter)")
        return

    title = "Directive Meta — purpose_short overview"
    if priority_gte > 0:
        title += f" (priority >= {priority_gte})"
    if missing_only:
        title += " (missing purpose_short only)"

    print(f"\n{'=' * 60}")
    print(f" {title}")
    print(f" Total: {len(items)} directives")
    print(f"{'=' * 60}\n")

    for d in items:
        ps = (d.purpose_short or '').strip()
        if ps:
            ps_disp = ps[:80]
        else:
            ps_disp = '(missing)'
        state_icon = '✓' if d.state == STATE_ACTIVE else '✗'
        print(f"  {_icon(d.priority)} P{d.priority:>2} {state_icon} {d.id:<45s}")
        print(f"      → {ps_disp}")
        if not ps:
            print(f"      ⚠ Lazy fill needed (see directive text in jarvis_directives.py)")
        print()


def list_recent_fires(turn_limit: int = 20) -> None:
    """看最近 N turn 的 fired directive cluster.

    数据源: log 中 '🧭 [L2 inject] fired=[...]'. 暂未结构化持久化, 仅展示需求.
    TODO: 结构化 publish SWM 'directive_fired_cluster' (P5-Gap4 后续).
    """
    print(f"\n{'=' * 60}")
    print(f" Recent fired clusters (last {turn_limit} turns)")
    print(f"{'=' * 60}\n")
    print(f"  ⚠ TODO: cluster 数据需要结构化持久化 (currently 仅 log)")
    print(f"  暂用法: 看 docs/runtime_logs/latest.log Grep '🧭 [L2 inject]'")
    print(f"  例: rg '🧭 \\[L2 inject\\]' docs/runtime_logs/latest.log | tail -20")


def find_conflicts() -> None:
    """找经常一起 fire 且可能冲突的 directive 组合.

    TODO: 接入 SWM cluster history + LLM judge.
    """
    print(f"\n{'=' * 60}")
    print(f" Directive conflicts (LLM judge based)")
    print(f"{'=' * 60}\n")
    print(f"  ⚠ TODO: 需要 SWM cluster history 持久化 + LLM judge propose 冲突")
    print(f"  设计: 累 100 turn fired cluster → LLM 看 priority + purpose_short →")
    print(f"        propose 冲突组合 + 建议调整 priority / 合并 / archive")


def main() -> int:
    p = argparse.ArgumentParser(
        description='Directive Meta CLI — purpose_short + cluster (Gap 4)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--purpose-shorts', action='store_true',
                    help='列所有 directive purpose_short')
    p.add_argument('--missing', action='store_true',
                    help='只列缺 purpose_short 的')
    p.add_argument('--priority-gte', type=int, default=0,
                    help='只列 priority >= N (默认 0 = 全列)')
    p.add_argument('--recent-fires', type=int, metavar='N',
                    help='看最近 N turn fired cluster')
    p.add_argument('--conflicts', action='store_true',
                    help='找经常一起 fire 的 directive 冲突 (LLM judge based)')

    args = p.parse_args()

    # bootstrap registry
    reg = DirectiveRegistry()
    bootstrap_default_registry(reg)

    if args.recent_fires:
        list_recent_fires(args.recent_fires)
        return 0

    if args.conflicts:
        find_conflicts()
        return 0

    if args.missing or args.purpose_shorts or args.priority_gte > 0:
        list_purpose_shorts(reg,
                              priority_gte=args.priority_gte,
                              missing_only=args.missing)
        return 0

    # default: 列所有 + 标记 missing
    list_purpose_shorts(reg)
    return 0


if __name__ == '__main__':
    sys.exit(main())
