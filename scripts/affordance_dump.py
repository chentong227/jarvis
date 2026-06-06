#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/affordance_dump.py — affordance 自知 CLI (内在锚第一阶段).

Sir 抽查能力自知 (轻闸纯机械, 不做常驻抽查; 此 CLI 让 Sir 随时 list/inspect):
  python scripts/affordance_dump.py                  # list 全部 affordance
  python scripts/affordance_dump.py --id <cap>       # 看单条详情 (含 evidence)
  python scripts/affordance_dump.py --reverify       # 触发全量重核 (对照注册表/trace)
  python scripts/affordance_dump.py --stale          # 只列 stale (超 TTL 未重核)

设计源: docs/JARVIS_INNER_ANCHOR_DESIGN.md §6.4. can 只由真能力证据点亮 (命门)。
"""
from __future__ import annotations

import os
import sys
import time
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_affordance as A


def _print_rec(r: dict, detail: bool = False) -> None:
    can = r.get("can", "?")
    tag = {"yes": "[能]", "no": "[做不到]", "partial": "[部分能]"}.get(can, "[?]")
    stale = " (stale-待重核)" if A.is_stale(r) else ""
    print(f"  {tag:8} {r.get('capability_id','')}{stale}")
    if detail:
        for e in r.get("evidence", []):
            print(f"        evidence: source={e.get('source')} ref={e.get('ref')}")
        lv = r.get("last_verified_ts", 0)
        print(f"        last_verified: {time.strftime('%Y-%m-%d %H:%M', time.localtime(lv)) if lv else '-'}")
        if r.get("note"):
            print(f"        note: {r.get('note')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis affordance 自知 CLI")
    ap.add_argument("--id", metavar="CAP", help="看单条详情")
    ap.add_argument("--reverify", action="store_true", help="触发全量重核 (对照注册表/trace)")
    ap.add_argument("--stale", action="store_true", help="只列 stale")
    args = ap.parse_args(argv)

    if args.reverify:
        rep = A.reverify_all()
        print(f"♻️ reverify: {rep['reverified']} 条核验, {rep['changed']} 条 can 变化")
        return 0

    recs = A.get_affordances()
    if args.id:
        recs = [r for r in recs if r.get("capability_id") == args.id]
        if not recs:
            print(f"(无 affordance 匹配 {args.id!r})")
            return 0
        for r in recs:
            _print_rec(r, detail=True)
        return 0

    if args.stale:
        recs = [r for r in recs if A.is_stale(r)]

    if not recs:
        print("(affordance store 为空 — 识 propose + 核验后才有)")
        return 0
    yes = sum(1 for r in recs if r.get("can") == "yes")
    no = sum(1 for r in recs if r.get("can") == "no")
    partial = sum(1 for r in recs if r.get("can") == "partial")
    print(f"📋 affordance 自知 ({len(recs)} 条: 能={yes} 部分={partial} 做不到={no}):")
    for r in sorted(recs, key=lambda x: x.get("capability_id", "")):
        _print_rec(r)
    print("\n(can 只由真能力证据点亮: 注册表可调用 / 执行trace达标; Sir说过不算)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
