# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 08:53] InnerThought cost config CLI (支柱A evidence-gated tick).

准则 6 vocab + CLI 范式: Sir 可看/改省 token 节流参数, 不需改源码 + git commit.
(json 原标 "CLI TODO 明天补" — 本次修支柱A 指纹 bug 顺手补齐.)

  python scripts/inner_thought_cost_dump.py                      # show current
  python scripts/inner_thought_cost_dump.py --set max_skip_streak=30
  python scripts/inner_thought_cost_dump.py --set "idle_buckets_s=[300,1800,7200]"
  python scripts/inner_thought_cost_dump.py --enable            # evidence_gate on
  python scripts/inner_thought_cost_dump.py --disable           # 退回每 tick 必调 LLM
  python scripts/inner_thought_cost_dump.py --exclude-source-add SomeSensor
  python scripts/inner_thought_cost_dump.py --exclude-source-remove PhysicalEnvProbe
  python scripts/inner_thought_cost_dump.py --exclude-suffix-add _hint
  python scripts/inner_thought_cost_dump.py --exclude-suffix-remove _advice
  python scripts/inner_thought_cost_dump.py --reset             # 回 default
"""
from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'memory_pool', 'inner_thought_cost_config.json')

# 与 jarvis_inner_thought_daemon._COST_DEFAULT_CONFIG 保持一致
DEFAULT_CONFIG = {
    "_doc": "第五阶段支柱 A — evidence-gated tick 省 token. 详 jarvis_inner_thought_daemon.py _COST_DEFAULT_CONFIG + docs/JARVIS_THINKING_COST_AWARE_SELF_DEBUG_DESIGN.md.",
    "evidence_gate": {
        "enabled": True,
        "max_skip_streak": 20,
        "idle_buckets_s": [300, 1800],
        "fingerprint_exclude_sources": ["inner_thought", "PhysicalEnvProbe"],
        "fingerprint_exclude_etype_suffixes": ["_advice"],
    },
}

_GATE = 'evidence_gate'


def _load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ config 读失败 {e}, 用默认")
        return json.loads(json.dumps(DEFAULT_CONFIG))


def _save(cfg: dict) -> None:
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"✅ saved → {CONFIG_PATH}")


def _gate(cfg: dict) -> dict:
    g = cfg.setdefault(_GATE, {})
    if not isinstance(g, dict):
        g = {}
        cfg[_GATE] = g
    return g


def cmd_show(cfg: dict) -> None:
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


def cmd_set(cfg: dict, items: list) -> None:
    g = _gate(cfg)
    for item in items:
        if '=' not in item:
            print(f"⚠️ --set arg must be KEY=VALUE, got {item}")
            continue
        k, v = item.split('=', 1)
        k = k.strip()
        try:
            val = json.loads(v.strip())
        except Exception:
            val = v.strip()
        g[k] = val
        print(f"  {_GATE}.{k} = {val}")
    _save(cfg)


def cmd_toggle(cfg: dict, enable: bool) -> None:
    _gate(cfg)['enabled'] = enable
    print(f"  {_GATE}.enabled = {enable}")
    _save(cfg)


def cmd_list_edit(cfg: dict, field: str, add, remove) -> None:
    g = _gate(cfg)
    lst = g.setdefault(field, [])
    if not isinstance(lst, list):
        lst = []
        g[field] = lst
    if add:
        if add not in lst:
            lst.append(add)
            print(f"  + {field}: {add}")
        else:
            print(f"  (already present) {field}: {add}")
    if remove:
        if remove in lst:
            lst.remove(remove)
            print(f"  - {field}: {remove}")
        else:
            print(f"  (not found) {field}: {remove}")
    _save(cfg)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="InnerThought cost config CLI (支柱A evidence-gated tick)")
    p.add_argument('--set', action='append', default=[],
                    help='set KEY=VALUE (max_skip_streak / idle_buckets_s / enabled)')
    p.add_argument('--enable', action='store_true', help='evidence_gate on')
    p.add_argument('--disable', action='store_true',
                    help='evidence_gate off (退回每 tick 必调 LLM)')
    p.add_argument('--exclude-source-add', type=str, default=None,
                    help='加一个 source 进 fingerprint_exclude_sources')
    p.add_argument('--exclude-source-remove', type=str, default=None,
                    help='从 fingerprint_exclude_sources 移除')
    p.add_argument('--exclude-suffix-add', type=str, default=None,
                    help='加一个 etype 后缀进 fingerprint_exclude_etype_suffixes')
    p.add_argument('--exclude-suffix-remove', type=str, default=None,
                    help='从 fingerprint_exclude_etype_suffixes 移除')
    p.add_argument('--reset', action='store_true', help='reset to defaults')
    args = p.parse_args(argv)

    cfg = _load()

    if args.reset:
        _save(json.loads(json.dumps(DEFAULT_CONFIG)))
        return
    if args.set:
        cmd_set(cfg, args.set)
        return
    if args.enable:
        cmd_toggle(cfg, True)
        return
    if args.disable:
        cmd_toggle(cfg, False)
        return
    if args.exclude_source_add or args.exclude_source_remove:
        cmd_list_edit(cfg, 'fingerprint_exclude_sources',
                       args.exclude_source_add, args.exclude_source_remove)
        return
    if args.exclude_suffix_add or args.exclude_suffix_remove:
        cmd_list_edit(cfg, 'fingerprint_exclude_etype_suffixes',
                       args.exclude_suffix_add, args.exclude_suffix_remove)
        return
    cmd_show(cfg)


if __name__ == '__main__':
    main()
