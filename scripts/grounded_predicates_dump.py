#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-PG / Sir 2026-06-02] grounded_predicates_dump.py — 接地谓词门 CLI.

准则 6: vocab 持久化 memory_pool/grounded_predicates_vocab.json + CLI 可看/改 (Sir 不改源码)。
固着↔健忘旋钮 = 接地谓词门: 默认衰减 UNLESS 机器可核谓词证明此事仍开着。绝不靠 LLM。

用法:
  python scripts/grounded_predicates_dump.py                 # 看注册表 + backstops
  python scripts/grounded_predicates_dump.py --check <cid>   # 对某 concern 现场判 still-open (+evidence)
  python scripts/grounded_predicates_dump.py --enable <id>   # 启用某谓词
  python scripts/grounded_predicates_dump.py --disable <id>  # 停用某谓词
  python scripts/grounded_predicates_dump.py --gate-off      # 整门关 (回纯衰减)
  python scripts/grounded_predicates_dump.py --gate-on       # 整门开
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import jarvis_grounded_predicate as gp

VOCAB_PATH = os.path.join(ROOT, "memory_pool", "grounded_predicates_vocab.json")


def _load_raw() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return json.loads(json.dumps(gp._SEED_PREDICATES))
    try:
        with open(VOCAB_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        print(f"[warn] load fail ({e}); using seed")
        return json.loads(json.dumps(gp._SEED_PREDICATES))


def _save(doc: dict) -> None:
    doc.setdefault("_meta", {})["updated_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = VOCAB_PATH + ".tmp"
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)
    gp.reset_cache_for_test()


def cmd_show() -> None:
    st = gp.gate_stats()
    print("=== 接地谓词门 (固着↔健忘旋钮) ===")
    print(f"门总开关 enabled: {st['enabled']}")
    print(f"谓词数: {st['predicate_count']}   机器 backstops: {st['backstops_available']}")
    print("-" * 70)
    for p in st["predicates"]:
        flag = "✅" if p["enabled"] else "⏸️ "
        print(f"  {flag} [{p['id']:22}] backstop={p['backstop']:20} kind={p['applies_to_kind']}")
    print("\n护栏: (a) 默认衰减 UNLESS 可证仍开着  (b) 只认机器 backstop, 绝不 LLM")


def cmd_check(cid: str) -> None:
    """对某 concern 现场判 still-open + evidence (诊断)。"""
    from jarvis_concerns import get_default_ledger
    led = get_default_ledger()
    led.load()
    c = led.get(cid)
    if c is None:
        print(f"(concern '{cid}' 不存在; active: {[x.id for x in led.list_active()][:10]})")
        return
    open_, ev = gp.is_still_open(c, now=time.time())
    print(f"concern={cid} severity={getattr(c, 'severity', '?')}")
    print(f"  still_open = {open_}")
    print(f"  evidence   = {ev or '(无 — 默认衰减)'}")
    print(f"  → {'抗衰减保持 (固着侧: 真没完)' if open_ else '默认衰减 (健忘侧: 无活证据)'}")


def cmd_toggle(pid: str, enabled: bool) -> None:
    doc = _load_raw()
    found = False
    for p in doc.get("predicates", []):
        if isinstance(p, dict) and p.get("id") == pid:
            p["enabled"] = enabled
            found = True
    if not found:
        print(f"[err] 谓词 id '{pid}' 不存在")
        return
    _save(doc)
    print(f"✅ 谓词 '{pid}' enabled={enabled}")
    cmd_show()


def cmd_gate(enabled: bool) -> None:
    doc = _load_raw()
    doc["enabled"] = enabled
    _save(doc)
    print(f"✅ 门总开关 enabled={enabled}")
    cmd_show()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="接地谓词门 CLI")
    ap.add_argument("--check", metavar="CID", help="对某 concern 现场判 still-open")
    ap.add_argument("--enable", metavar="ID", help="启用某谓词")
    ap.add_argument("--disable", metavar="ID", help="停用某谓词")
    ap.add_argument("--gate-off", action="store_true", help="整门关 (回纯衰减)")
    ap.add_argument("--gate-on", action="store_true", help="整门开")
    args = ap.parse_args(argv)
    if args.check:
        cmd_check(args.check)
    elif args.enable:
        cmd_toggle(args.enable, True)
    elif args.disable:
        cmd_toggle(args.disable, False)
    elif args.gate_off:
        cmd_gate(False)
    elif args.gate_on:
        cmd_gate(True)
    else:
        cmd_show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
