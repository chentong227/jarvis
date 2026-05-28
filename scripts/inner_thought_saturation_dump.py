# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 19:20] InnerThought saturation config CLI.

准则 6 vocab + CLI 范式: Sir 可看/改阈值不需改源码.

  python scripts/inner_thought_saturation_dump.py              # show current
  python scripts/inner_thought_saturation_dump.py --set min_thoughts_same_thread=4
  python scripts/inner_thought_saturation_dump.py --set min_consecutive_saturated_for_force=7
  python scripts/inner_thought_saturation_dump.py --set fatigue_delta_per_saturation=0.08
  python scripts/inner_thought_saturation_dump.py --disable concern_fatigue_softening
  python scripts/inner_thought_saturation_dump.py --enable  concern_fatigue_softening
  python scripts/inner_thought_saturation_dump.py --reset                       # 回 default
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'memory_pool', 'inner_thought_saturation_config.json')

DEFAULT_CONFIG = {
    "_doc": "Sir 2026-05-28 19:20 — see source for full spec.",
    "saturation_trigger": {
        "min_thoughts_same_thread": 3,
        "require_all_should_speak_false": True,
        "actionable_done_states": ["none", "rejected", "gated", "failed"],
    },
    "concern_fatigue_softening": {
        "enabled": True,
        "fatigue_delta_per_saturation": 0.05,
        "decay_back_half_life_hours": 24.0,
        "fatigue_cap": 0.5,
    },
    "python_physical_force": {
        "enabled": True,
        "min_consecutive_saturated_for_force": 5,
        "force_next_interval_s": 600,
        "force_max_short_choice_s": 60,
    },
}


def _load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ config 读失败 {e}, 用默认")
        return dict(DEFAULT_CONFIG)


def _save(cfg: dict) -> None:
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"✅ saved → {CONFIG_PATH}")


def _set_path(cfg: dict, dotted: str, raw_val: str) -> bool:
    """Look up the field across all top-level sections (saturation_trigger /
    concern_fatigue_softening / python_physical_force). Returns True if set.
    """
    # try parse value
    try:
        val: object = json.loads(raw_val)
    except Exception:
        val = raw_val  # plain string fallback

    for section in ('saturation_trigger',
                     'concern_fatigue_softening',
                     'python_physical_force'):
        sect = cfg.get(section)
        if isinstance(sect, dict) and dotted in sect:
            sect[dotted] = val
            print(f"  {section}.{dotted} = {val}")
            return True
    print(f"⚠️ unknown key {dotted}")
    return False


def cmd_show(_args, cfg: dict) -> None:
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


def cmd_set(args, cfg: dict) -> None:
    for item in args.set:
        if '=' not in item:
            print(f"⚠️ --set arg must be KEY=VALUE, got {item}")
            continue
        k, v = item.split('=', 1)
        _set_path(cfg, k.strip(), v.strip())
    _save(cfg)


def cmd_toggle(args, cfg: dict, enable: bool) -> None:
    section = args.disable if not enable else args.enable
    if section not in cfg or not isinstance(cfg[section], dict):
        print(f"⚠️ unknown section {section}")
        return
    cfg[section]['enabled'] = enable
    print(f"  {section}.enabled = {enable}")
    _save(cfg)


def cmd_reset(_args, _cfg: dict) -> None:
    _save(dict(DEFAULT_CONFIG))


def main(argv=None):
    p = argparse.ArgumentParser(description="InnerThought saturation config CLI")
    p.add_argument('--set', action='append', default=[],
                    help='set KEY=VALUE (e.g. --set min_thoughts_same_thread=4)')
    p.add_argument('--disable', type=str, default=None,
                    help='disable a section (concern_fatigue_softening|python_physical_force)')
    p.add_argument('--enable', type=str, default=None,
                    help='enable a section')
    p.add_argument('--reset', action='store_true', help='reset to defaults')
    args = p.parse_args(argv)

    cfg = _load()

    if args.reset:
        cmd_reset(args, cfg)
        return
    if args.set:
        cmd_set(args, cfg)
        return
    if args.disable:
        cmd_toggle(args, cfg, enable=False)
        return
    if args.enable:
        cmd_toggle(args, cfg, enable=True)
        return
    cmd_show(args, cfg)


if __name__ == '__main__':
    main()
