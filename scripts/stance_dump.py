#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/stance_dump.py — Sir CLI 看/管 Jarvis 立场 (体-P4 stance).

[体-P4 / 2026-05-31] 准则 6 持久化 (memory_pool/stance.json) + 准则 7 Sir 元否决权.
立场 = Jarvis 自己对 Sir/关系的接地 view (阻力/老师感载体). 识 propose 进 review,
Sir 在这里 confirm / retire / revert. 详 docs/JARVIS_TRINITY_ARCHITECTURE.md.

用法:
  python scripts/stance_dump.py                    # list active (默认)
  python scripts/stance_dump.py --all              # list 全部 (含 review/retired)
  python scripts/stance_dump.py --review           # 看 review 队列 (识 propose 待 Sir 拍板)
  python scripts/stance_dump.py --show <sid>       # 看一条完整 (含 evidence 接地链)
  python scripts/stance_dump.py --confirm <sid>    # Sir 确认 → active + 高置信
  python scripts/stance_dump.py --retire <sid>     # Sir 否决 → retired
  python scripts/stance_dump.py --reason TEXT      # 配合 --retire 写理由
  python scripts/stance_dump.py --json             # raw dump
"""
from __future__ import annotations

import argparse
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_stance import StanceStore, STATE_ACTIVE, STATE_REVIEW  # noqa: E402

PATH = os.path.join(ROOT, "memory_pool", "stance.json")


def _fmt(s: dict) -> str:
    return (f"[{s.get('state', '?'):7}] conf={float(s.get('confidence', 0)):.2f} "
            f"about={s.get('about', ''):16} {str(s.get('claim', ''))[:70]}")


def cmd_list(store: StanceStore, state) -> None:
    rows = store.list(state)
    if not rows:
        print("(无立场" + (f" state={state}" if state else "") +
              " — 识 propose 后才有)")
        return
    for s in rows:
        print(_fmt(s))
        print(f"          id={s.get('stance_id')}  src={s.get('source')} "
              f"evidence={len(s.get('evidence', []))}")
    print(f"\n共 {len(rows)} 立场" + (f" (state={state})" if state else ""))
    print(f"stats: {store.stats()}")


def cmd_show(store: StanceStore, sid: str) -> None:
    s = store.get(sid)
    if not s:
        print(f"(未找到立场: {sid})")
        return
    print(json.dumps(s, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis 立场 (stance) CLI")
    ap.add_argument("--all", action="store_true", help="list 全部状态")
    ap.add_argument("--review", action="store_true", help="只看 review 队列")
    ap.add_argument("--show", metavar="SID", help="看一条完整 (含 evidence)")
    ap.add_argument("--confirm", metavar="SID", help="Sir 确认 → active")
    ap.add_argument("--retire", metavar="SID", help="Sir 否决 → retired")
    ap.add_argument("--reason", metavar="TEXT", default="", help="配合 --retire 写理由")
    ap.add_argument("--json", action="store_true", help="raw dump")
    args = ap.parse_args(argv)

    store = StanceStore(PATH)

    if args.json:
        print(json.dumps(store.list(), ensure_ascii=False, indent=2))
    elif args.show:
        cmd_show(store, args.show)
    elif args.confirm:
        ok = store.confirm(args.confirm)
        print(f"{'✅ 已确认' if ok else '未找到'}: {args.confirm}")
    elif args.retire:
        ok = store.retire(args.retire, reason=args.reason)
        print(f"{'✅ 已否决(retired)' if ok else '未找到'}: {args.retire}")
    elif args.review:
        cmd_list(store, STATE_REVIEW)
    elif args.all:
        cmd_list(store, None)
    else:
        cmd_list(store, STATE_ACTIVE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
