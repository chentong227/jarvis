# -*- coding: utf-8 -*-
"""[β.5.46-fix14 / 2026-05-22] IntentResolver A/B telemetry CLI

Sir 拍板副链 A/B: IntentResolver primary 升级 google/gemini-3.5-flash, 跑 1-2 周
看真实 fact tool call 准确率 + latency 决定是否升级主脑.

本 CLI 看 telemetry stats:
- primary (3.5-flash) vs fallback (2.5-flash-lite) 各自 success rate
- 平均 latency
- parse fail count (3.5-flash verbose 会不会 break JSON schema)

Usage:
    cd d:/Jarvis
    python scripts/intent_resolver_telemetry_dump.py
    python scripts/intent_resolver_telemetry_dump.py --reset    # 清零 (升级前对照)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TELEMETRY_PATH = os.path.join('memory_pool', 'intent_resolver_telemetry.json')


def _fmt_pct(num: int, denom: int) -> str:
    if denom <= 0:
        return '-'
    return f"{num / denom * 100:.1f}%"


def _fmt_avg_ms(sum_ms: float, n: int) -> str:
    if n <= 0:
        return '-'
    return f"{sum_ms / n:.0f}ms"


def cmd_show() -> int:
    if not os.path.exists(TELEMETRY_PATH):
        print(f'(no telemetry yet — IntentResolver 还没跑 turn)\n'
              f'expected at {TELEMETRY_PATH}')
        return 0
    try:
        with open(TELEMETRY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'failed to load telemetry: {e}', file=sys.stderr)
        return 2

    stats = data.get('stats', {}) or {}
    print('=' * 70)
    print(f'IntentResolver A/B Telemetry')
    print('=' * 70)
    print(f"primary_model    : {data.get('primary_model', '?')}")
    print(f"fallback_model   : {data.get('fallback_model', '?')}")
    _ts = data.get('updated_at', 0)
    if _ts > 0:
        _age = time.time() - _ts
        if _age < 60:
            print(f"last updated     : {int(_age)}s ago")
        elif _age < 3600:
            print(f"last updated     : {int(_age/60)}min ago")
        else:
            print(f"last updated     : {_age/3600:.1f}h ago")

    print()
    turns = stats.get('turns_resolved', 0)
    tools_ok = stats.get('tools_called_total', 0)
    tools_fail = stats.get('tools_failed_total', 0)
    print(f"turns_resolved   : {turns}")
    print(f"tools_called_ok  : {tools_ok}")
    print(f"tools_failed     : {tools_fail}")

    print()
    print('LLM Calls — A/B')
    print('-' * 70)
    p_calls = stats.get('llm_primary_calls', 0)
    p_ok = stats.get('llm_primary_ok', 0)
    p_fail = stats.get('llm_primary_fail', 0)
    p_lat = stats.get('llm_primary_latency_sum_ms', 0.0)

    f_calls = stats.get('llm_fallback_calls', 0)
    f_ok = stats.get('llm_fallback_ok', 0)
    f_fail = stats.get('llm_fallback_fail', 0)
    f_lat = stats.get('llm_fallback_latency_sum_ms', 0.0)

    parse_fail = stats.get('llm_parse_fail', 0)

    print(f"{'metric':<20}{'primary (3.5)':<18}{'fallback (lite)':<18}")
    print('-' * 70)
    print(f"{'calls':<20}{p_calls:<18}{f_calls:<18}")
    print(f"{'ok':<20}{p_ok:<18}{f_ok:<18}")
    print(f"{'fail':<20}{p_fail:<18}{f_fail:<18}")
    print(f"{'success_rate':<20}{_fmt_pct(p_ok, p_calls):<18}{_fmt_pct(f_ok, f_calls):<18}")
    print(f"{'avg_latency':<20}{_fmt_avg_ms(p_lat, p_calls):<18}"
          f"{_fmt_avg_ms(f_lat, f_calls):<18}")
    print()
    print(f"json_parse_fail  : {parse_fail}")
    if p_calls > 0:
        print(f"parse_fail_rate  : {_fmt_pct(parse_fail, p_calls + f_calls)}")

    if stats.get('last_error'):
        print()
        print(f"last_error       : {stats['last_error'][:120]}")
    return 0


def cmd_reset() -> int:
    """清零 telemetry. Sir 升级前对照用 (Sir 真测前清, 测完看新数据)."""
    try:
        if os.path.exists(TELEMETRY_PATH):
            os.remove(TELEMETRY_PATH)
            print(f'reset: removed {TELEMETRY_PATH}')
        else:
            print('(no telemetry to reset)')
        return 0
    except Exception as e:
        print(f'reset failed: {e}', file=sys.stderr)
        return 2


def main() -> int:
    p = argparse.ArgumentParser(description='IntentResolver A/B telemetry')
    p.add_argument('--reset', action='store_true',
                    help='clear telemetry counters')
    args = p.parse_args()
    if args.reset:
        return cmd_reset()
    return cmd_show()


if __name__ == '__main__':
    sys.exit(main())
