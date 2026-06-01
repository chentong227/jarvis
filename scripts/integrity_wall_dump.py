#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/integrity_wall_dump.py — 回路外机械墙 breach ledger CLI (放权 T0.2).

机械墙是**回路外**真兜底 (确定性, 无 vocab/LLM, 系统改不动)。本 CLI 只**看**
breach ledger (硬证), 不改墙 (改墙 = 改 jarvis_integrity_wall.py 源码 + commit + test,
= 历史驱动慢塑, 非运行时改写。§0 硬线)。

  python scripts/integrity_wall_dump.py            # breach 概要 (by kind + 总数 + 体征)
  python scripts/integrity_wall_dump.py --tail 20  # 最近 20 条 breach 明细
  python scripts/integrity_wall_dump.py --json     # 机读 stats
"""
from __future__ import annotations

import os
import sys
import json
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="回路外机械墙 breach ledger CLI — 只看 (硬证), 不改墙")
    ap.add_argument("--tail", type=int, default=0,
                    help="显示最近 N 条 breach 明细")
    ap.add_argument("--json", action="store_true", help="机读 stats")
    args = ap.parse_args()

    import jarvis_integrity_wall as wall
    stats = wall.breach_stats()

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    print("=== 回路外机械墙 (no_fabrication) — breach ledger 硬证 ===")
    print(f"  墙激活 (检测原语就位): {stats['wall_active']}")
    print(f"  ledger: {stats['ledger_path']}")
    print(f"  breach 总数 (持久): {stats['total_breaches']}")
    print(f"  breach 本 session: {stats['session_breaches']}")
    if stats['by_kind']:
        print("  by kind:")
        for k, n in sorted(stats['by_kind'].items(), key=lambda x: -x[1]):
            print(f"    {k}: {n}")
    print(f"  最近 breach: {stats['last_breach_iso'] or '(无)'}")
    health = "✅ breach=0 (进格闸硬条件满足)" if stats['total_breaches'] == 0 \
        else f"⚠️ breach={stats['total_breaches']} (§1 STOP 触发器: 任何 >0 报 Sir)"
    print(f"  体征: {health}")

    if args.tail and args.tail > 0:
        path = stats['ledger_path']
        print(f"\n=== 最近 {args.tail} 条 breach ===")
        if not os.path.exists(path):
            print("  (ledger 空)")
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            for ln in lines[-args.tail:]:
                try:
                    e = json.loads(ln)
                    print(f"  [{e.get('iso','?')}] turn={e.get('turn_id','?')} "
                          f"[{e.get('kind','?')}] {e.get('claim','')[:80]} "
                          f"— {e.get('reason','')}")
                except Exception:
                    continue
        except OSError:
            print("  (读取失败)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
