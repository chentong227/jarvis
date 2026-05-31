# -*- coding: utf-8 -*-
"""[thinking-dehardcode-P0 / Sir 2026-05-31] 思考脑 kind 去硬编码 vocab CLI.

识的最后一条硬编码 = A-E 5 类 category 槽. 本工程拔它: kind 由体势能涌现
(focus 区招来 thought → 放电产 effect = kind), diversity 靠"区放电"替"类冷却".
详 docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md + AGENT_KICKOFF_THINKING_DEHARDCODE.md.

准则 6 vocab + CLI 范式: Sir 可看/改 mode + effect→kind 派生表, 不需改源码 + commit.

  python scripts/thinking_kind_dump.py                          # show current
  python scripts/thinking_kind_dump.py --mode emergent          # 切 emergent (Phase 1+ 验后)
  python scripts/thinking_kind_dump.py --mode legacy            # 回退 (任一 phase 出问题)
  python scripts/thinking_kind_dump.py --set-kind call_tool=solve        # 改一条派生
  python scripts/thinking_kind_dump.py --set-special kind_for_none=empty # 改特例 label
  python scripts/thinking_kind_dump.py --reset                  # 回 default (legacy)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
try:
    import _cli_utils  # noqa: F401  # side-effect force utf8 stdout (Windows GBK safe)
except Exception:
    # _cli_utils 可选 (Windows GBK emoji 安全); 缺失不致命
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'memory_pool', 'thinking_kind_vocab.json')

_MODES = ('legacy', 'emergent')
_SPECIAL_KEYS = ('kind_for_rest', 'kind_for_none', 'kind_for_unknown')

# 与 jarvis_inner_thought_daemon._THINKING_KIND_DEFAULT 保持一致.
DEFAULT_CONFIG = {
    "_doc": "思考脑去硬编码 (A-E 类槽 → 势能驱动 kind). 详 jarvis_inner_thought_daemon.py _THINKING_KIND_DEFAULT + docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md.",
    "thinking_kind_mode": "legacy",
    "effect_to_kind": {
        "update_concern_severity": "solve",
        "adjust_concern_notes": "shape_next",
        "propose_stance": "reflect",
        "propose_protocol": "reflect",
        "suggest_inside_joke": "relate",
        "fire_nudge": "reach_out",
        "propose_watch_task": "commit",
        "compose_main_brain_directive": "shape_next",
        "propose_vocab_adjustment": "self_debug",
        "adjust_sensor_threshold": "self_debug",
        "call_tool": "solve",
        "request_capability": "want_capability"
    },
    "kind_for_rest": "rest",
    "kind_for_none": "empty",
    "kind_for_unknown": "act"
}


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


def cmd_show(cfg: dict) -> None:
    mode = cfg.get('thinking_kind_mode', 'legacy')
    print(f"thinking_kind_mode = {mode}"
          f"  ({'A-E 槽 + 类冷却 (老行为)' if mode == 'legacy' else '势能区 summon + kind=effect'})")
    print("\neffect_to_kind (actionable 前缀 → 涌现 kind label, 无冷却):")
    for k, v in (cfg.get('effect_to_kind') or {}).items():
        print(f"  {k:<32} → {v}")
    print("\nspecial:")
    for k in _SPECIAL_KEYS:
        print(f"  {k:<20} = {cfg.get(k, '')}")


def cmd_mode(cfg: dict, mode: str) -> None:
    if mode not in _MODES:
        print(f"⚠️ mode 必须是 {_MODES}, got {mode}")
        return
    old = cfg.get('thinking_kind_mode', 'legacy')
    cfg['thinking_kind_mode'] = mode
    print(f"  thinking_kind_mode: {old} → {mode}")
    if mode == 'emergent':
        print("  ⚠️ emergent 模式逐 phase 开 — 确认已镜像 + Sir 真机验过对应 phase.")
    _save(cfg)


def cmd_set_kind(cfg: dict, items: list) -> None:
    table = cfg.setdefault('effect_to_kind', {})
    if not isinstance(table, dict):
        table = {}
        cfg['effect_to_kind'] = table
    for item in items:
        if '=' not in item:
            print(f"⚠️ --set-kind arg 须 PREFIX=KIND, got {item}")
            continue
        prefix, kind = item.split('=', 1)
        prefix, kind = prefix.strip(), kind.strip()
        table[prefix] = kind
        print(f"  effect_to_kind.{prefix} = {kind}")
    _save(cfg)


def cmd_set_special(cfg: dict, items: list) -> None:
    for item in items:
        if '=' not in item:
            print(f"⚠️ --set-special arg 须 KEY=VALUE, got {item}")
            continue
        k, v = item.split('=', 1)
        k, v = k.strip(), v.strip()
        if k not in _SPECIAL_KEYS:
            print(f"⚠️ special key 须属 {_SPECIAL_KEYS}, got {k}")
            continue
        cfg[k] = v
        print(f"  {k} = {v}")
    _save(cfg)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="思考脑 kind 去硬编码 vocab CLI (thinking_kind_mode + effect→kind)")
    p.add_argument('--mode', type=str, default=None,
                   help='切 thinking_kind_mode: legacy | emergent')
    p.add_argument('--set-kind', action='append', default=[],
                   help='改派生表一条 PREFIX=KIND (e.g. call_tool=solve)')
    p.add_argument('--set-special', action='append', default=[],
                   help='改特例 label KEY=VALUE (kind_for_rest/kind_for_none/kind_for_unknown)')
    p.add_argument('--reset', action='store_true', help='reset to defaults (legacy)')
    args = p.parse_args(argv)

    if args.reset:
        _save(json.loads(json.dumps(DEFAULT_CONFIG)))
        return

    cfg = _load()
    if args.mode:
        cmd_mode(cfg, args.mode)
        return
    if args.set_kind:
        cmd_set_kind(cfg, args.set_kind)
        return
    if args.set_special:
        cmd_set_special(cfg, args.set_special)
        return
    cmd_show(cfg)


if __name__ == '__main__':
    main()
