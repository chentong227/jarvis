#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/receptivity_gate_dump.py — Sir CLI 看/改输出闸 (口识体-D) vocab.

输出闸 = Sir 接收度单一门: 口主动 voice nudge 出声前过此, 不接收 → 降 silent_text /
suppress (防"突然说话吓一跳"). 准则 6 持久化 memory_pool/receptivity_gate_vocab.json.

用法:
  python scripts/receptivity_gate_dump.py                      # 看当前 vocab + 决策表
  python scripts/receptivity_gate_dump.py --set enabled 0      # 关门 (退回老行为, 永远出声)
  python scripts/receptivity_gate_dump.py --set just_interacted_window_s 12
  python scripts/receptivity_gate_dump.py --state afk_deep active  # 改某 sir_state 决策
  python scripts/receptivity_gate_dump.py --test active 3       # 模拟: state + 距上次互动秒
"""
from __future__ import annotations

import argparse
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PATH = os.path.join(ROOT, "memory_pool", "receptivity_gate_vocab.json")


def _load() -> dict:
    if not os.path.exists(PATH):
        return {}
    with open(PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)


def cmd_show() -> None:
    from jarvis_receptivity_gate import load_vocab
    v = load_vocab()
    print("=== 输出闸 (口识体-D) — Sir 接收度单一门 ===")
    print(f"enabled: {v.get('enabled')}  (false = 永远出声, 退回老行为)")
    print(f"just_interacted_window_s: {v.get('just_interacted_window_s')}  "
          f"(刚互动完此秒内 voice → 降 silent_text, 防吓一跳)")
    print(f"always_allow_types: {v.get('always_allow_types')}  (绕门永远出声)")
    print("sir_state 决策表:")
    for st, dec in (v.get("state_decision") or {}).items():
        print(f"  {st:12} → {dec}")
    print("\n决策: allow=正常出声 / downgrade=降 silent_text 留痕不出声 / suppress=仅留痕")


def cmd_test(state: str, secs: float) -> None:
    from jarvis_receptivity_gate import assess_receptivity
    d, reason = assess_receptivity(
        sir_state=state, seconds_since_last_interaction=secs)
    print(f"sir_state={state} since_last={secs}s → 决策={d} (reason={reason})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jarvis 输出闸 (口识体-D) CLI")
    ap.add_argument("--set", nargs=2, metavar=("KEY", "VAL"),
                    help="改顶层字段 (enabled/just_interacted_window_s)")
    ap.add_argument("--state", nargs=2, metavar=("SIR_STATE", "DECISION"),
                    help="改某 sir_state 决策 (allow/downgrade/suppress)")
    ap.add_argument("--test", nargs=2, metavar=("STATE", "SECS"),
                    help="模拟决策 (state + 距上次互动秒)")
    args = ap.parse_args(argv)

    if args.test:
        cmd_test(args.test[0], float(args.test[1]))
        return 0
    if args.set:
        data = _load()
        k, val = args.set
        if k in ("enabled",):
            data[k] = bool(int(val))
        elif k in ("just_interacted_window_s",):
            data[k] = float(val)
        else:
            print(f"❌ 未知/不支持直改字段: {k}")
            return 2
        _save(data)
        print(f"✅ set {k} = {data[k]}")
        return 0
    if args.state:
        data = _load()
        st, dec = args.state
        if dec not in ("allow", "downgrade", "suppress"):
            print("❌ DECISION 必须 allow/downgrade/suppress")
            return 2
        data.setdefault("state_decision", {})[st] = dec
        _save(data)
        print(f"✅ state_decision[{st}] = {dec}")
        return 0
    cmd_show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
