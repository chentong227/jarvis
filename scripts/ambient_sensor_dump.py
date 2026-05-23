#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[P5-fix35-E / 2026-05-23 11:36] AmbientSensor CLI — Sir 看 / 改 config.

Sir 真痛点: AmbientSensor 启用了但没体感. 21MB log 0 publish.
治本: config 持久化 (memory_pool/ambient_sensor_config.json) + CLI 调.

用法:
  python scripts/ambient_sensor_dump.py                        # 看 config + stats
  python scripts/ambient_sensor_dump.py --json                 # 机读
  python scripts/ambient_sensor_dump.py --set <key>=<value>    # 改 config (Sir CLI)
  python scripts/ambient_sensor_dump.py --reset                # 恢复默认
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'memory_pool', 'ambient_sensor_config.json')


def _load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _show(as_json: bool) -> int:
    data = _load()
    cfg = data.get('config', {}) if isinstance(data, dict) else {}
    docs = data.get('_field_docs', {}) if isinstance(data, dict) else {}

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("=" * 78)
    print(f"  AmbientSensor config — {CONFIG_PATH}")
    print("=" * 78)
    if not cfg:
        print("  (empty config — 用 defaults)")
        return 0
    for k, v in cfg.items():
        print(f"  {k:35s} = {v}")
        doc = docs.get(k, '')
        if doc:
            print(f"  {'':35s}   ↳ {doc[:100]}")
    print()

    # Try to load live stats
    try:
        sys.path.insert(0, ROOT)
        from jarvis_ambient_sensor import get_ambient_sensor
        sensor = get_ambient_sensor()
        stats = sensor.get_stats()
        print("=" * 78)
        print("  Runtime stats (current process — only meaningful if Jarvis running):")
        print("=" * 78)
        print(f"  effective_enabled:       {stats.get('effective_enabled')}")
        print(f"  n_windows_analyzed:      {stats.get('n_windows_analyzed', 0)}")
        print(f"  n_signals_published:    {stats.get('n_signals_published', 0)}")
        print(f"  n_skipped_state_gate:   {stats.get('n_skipped_state_gate', 0)}  (Sir 说话/Jarvis TTS 期 / active 期)")
        print(f"  n_skipped_volume:       {stats.get('n_skipped_volume', 0)}  (太静 < min_vol or 太响 > max_vol)")
        print(f"  n_classified_no_match:  {stats.get('n_classified_no_match', 0)}  (window 分析了但分类不出)")
        print(f"  n_below_consensus:      {stats.get('n_below_consensus', 0)}  (单个有结果但 < consecutive_agree)")
        print(f"  n_below_cooldown:       {stats.get('n_below_cooldown', 0)}  (consensus 够了但 cooldown 内)")
        if stats.get('stats_per_type'):
            print(f"  ✅ Published per type:")
            for k, v in stats['stats_per_type'].items():
                print(f"     {k}: {v}")
    except Exception as e:
        print(f"  (live stats 不可用: {e})")
    print()
    return 0


def _set(kv: str) -> int:
    if '=' not in kv:
        print(f"[error] format: --set key=value", file=sys.stderr)
        return 1
    k, v = kv.split('=', 1)
    k = k.strip()
    v = v.strip()
    # type coerce
    if v.lower() in ('true', 'false'):
        val = v.lower() == 'true'
    else:
        try:
            val = float(v) if '.' in v else int(v)
        except Exception:
            val = v
    data = _load()
    if 'config' not in data or not isinstance(data.get('config'), dict):
        data['config'] = {}
    old_v = data['config'].get(k, '<unset>')
    data['config'][k] = val
    _save(data)
    print(f"✅ config['{k}']: {old_v} → {val}")
    print(f"  (Sir 跑中 Jarvis 的 AmbientSensor mtime cache 会自动 reload, 无需重启)")
    return 0


def _reset() -> int:
    """Reset config to defaults (preserves _comment / _field_docs)."""
    defaults = {
        'min_confidence': 0.50,
        'consecutive_agree_threshold': 2,
        'per_type_cooldown_s': 60.0,
        'min_volume_for_analysis': 30,
        'max_volume_for_analysis': 3000,
        'analysis_window_samples': 8000,
        'sample_rate': 16000,
        'analyze_in_active_chat': False,
        'stats_log_interval_s': 300.0,
    }
    data = _load()
    if not isinstance(data, dict):
        data = {}
    data['config'] = defaults
    _save(data)
    print(f"✅ Reset config to defaults.")
    return 0


def main():
    p = argparse.ArgumentParser(description='AmbientSensor CLI')
    p.add_argument('--json', action='store_true', help='JSON output')
    p.add_argument('--set', metavar='KEY=VALUE',
                     help='Set a config field (e.g. --set min_confidence=0.45)')
    p.add_argument('--reset', action='store_true',
                     help='Reset config to defaults')
    args = p.parse_args()

    if args.set:
        return _set(args.set)
    if args.reset:
        return _reset()
    return _show(args.json)


if __name__ == '__main__':
    sys.exit(main())
