#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/anchors_dump.py — 锚 (Anchor/Boundary) CLI (锚化工程 P0).

只**看 + 调软**, 不删墙 (锚非软, 理念源 §3-公理2 / §3-4b):
  python scripts/anchors_dump.py                 # list 所有锚 (墙 + 软倾向 + 冲突)
  python scripts/anchors_dump.py --id say_do     # 看单个锚详情
  python scripts/anchors_dump.py --walls         # 只列所有墙 (禁令)

(调 soft_leanings/conflict_notes 直接编辑 memory_pool/anchors.json — 那是软可调区;
 walls 改不动: 即便 json 里改了, loader 也以 .py seed 的墙为准。)
"""
from __future__ import annotations

import os
import sys
import argparse

# UTF-8 输出 (PowerShell GBK 会崩 emoji/中文)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _print_anchor(a: dict, detail: bool = False) -> None:
    print(f"\n=== 锚 [{a.get('id')}] {a.get('name','')} "
          f"{'(豁免仲裁)' if a.get('exempt_from_arbitration') else ''} ===")
    print("  墙 (boundary / 不做什么):")
    for w in a.get("walls", []):
        ck = "可检验" if w.get("checkable") else "框架志向"
        print(f"    - [{w.get('id')}] {w.get('prohibition')}  "
              f"({ck}, 兜底={w.get('backstop','-')})")
    print(f"  软倾向 (墙外辐射, 可调=性格): {', '.join(a.get('soft_leanings', [])) or '-'}")
    if detail:
        om = a.get("organ_manifest", {})
        print("  跨器官落点:")
        for organ in ("体", "识", "口"):
            if organ in om:
                print(f"    {organ}: {om[organ]}")
        print(f"  冲突笔记: {a.get('conflict_notes','-')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="锚 (Anchor/Boundary) CLI — 只看+调软, 不删墙")
    ap.add_argument("--id", help="看单个锚详情")
    ap.add_argument("--walls", action="store_true", help="只列所有墙 (禁令)")
    args = ap.parse_args()

    import jarvis_anchors as ja
    ja.ensure_anchors_file()

    if args.walls:
        print("=== 所有墙 (boundary 禁令) ===")
        for a in ja.get_anchors():
            for w in a.get("walls", []):
                print(f"  [{a['id']}/{w['id']}] {w['prohibition']}")
        return 0

    if args.id:
        a = ja.get_anchor(args.id)
        if not a:
            print(f"无此锚: {args.id}  (现有: {sorted(ja.anchor_ids())})")
            return 1
        _print_anchor(a, detail=True)
        return 0

    anchors = ja.get_anchors()
    print(f"=== 锚清单 ({len(anchors)} 个;锚=边界,豁免仲裁,详 docs/JARVIS_ANCHOR_AND_BOUNDARY.md) ===")
    for a in anchors:
        _print_anchor(a, detail=False)
    print("\n(--id <id> 看详情 / --walls 只列墙;调 soft_leanings 编辑 memory_pool/anchors.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
