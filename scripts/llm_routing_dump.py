# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 fix45] LLM 路由 vocab CLI (准则 6 持久化 + 准则 7 元否决一键关).

Sir 准则 6 vocab CLI 范式 (类比 scripts/gate_mode_dump.py / scripts/concerns_dump.py):
  - Sir 不改源码 + git commit 就能 toggling gate / 改 replace_models / 看 17 USD 进度
  - 即时生效 (jarvis_utils 每次 call 读 vocab + 5s mtime cache, 写后立即 invalidate)

用法:
  python scripts/llm_routing_dump.py                          # list 当前状态 + 用量概要
  python scripts/llm_routing_dump.py --gate on                # 启用 DeepSeek 路由
  python scripts/llm_routing_dump.py --gate off               # 全部 fallback 回原 google/gemini-*
  python scripts/llm_routing_dump.py --add-model google/gemini-3.1-pro-preview
  python scripts/llm_routing_dump.py --remove-model google/gemini-3.1-pro-preview
  python scripts/llm_routing_dump.py --add-exclude stm_summarizer
  python scripts/llm_routing_dump.py --remove-exclude stm_summarizer
  python scripts/llm_routing_dump.py --usage                  # per_caller breakdown + budget 剩余
  python scripts/llm_routing_dump.py --reset-usage            # 清零 usage stats (充值新一轮)
  python scripts/llm_routing_dump.py --history 20             # 最近 20 条 mutation history
  python scripts/llm_routing_dump.py --json                   # 机读 JSON
  python scripts/llm_routing_dump.py --rationale "Sir 17 USD 充值耗尽" --gate off

文件依赖:
- memory_pool/llm_routing_vocab.json  (准则 6 持久化, vocab + usage_stats + history)
- env OPENROUTER_DS_ONLY               (DeepSeek 专用 key, .env 配)

规范: 详 AGENTS.md §准则 6 + docs/JARVIS_PYTHON_STYLE.md vocab CLI 范式
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# CLI 独立进程不继承主进程 proxy env, OpenRouter / Google 调用通常需走 127.0.0.1:7890
os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7890')


def _load_helpers():
    """Lazy import jarvis_utils helpers (避免顶部 import 触发大依赖)."""
    from jarvis_utils import (
        _load_llm_routing_vocab,
        _llm_routing_vocab_path,
        _get_deepseek_key,
        get_deepseek_routing_stats,
        set_deepseek_routing_gate,
        add_deepseek_replace_model,
        remove_deepseek_replace_model,
        reset_deepseek_usage_stats,
        invalidate_llm_routing_cache,
    )
    return {
        'load': _load_llm_routing_vocab,
        'path': _llm_routing_vocab_path,
        'ds_key': _get_deepseek_key,
        'stats': get_deepseek_routing_stats,
        'set_gate': set_deepseek_routing_gate,
        'add_model': add_deepseek_replace_model,
        'remove_model': remove_deepseek_replace_model,
        'reset_usage': reset_deepseek_usage_stats,
        'invalidate': invalidate_llm_routing_cache,
    }


def _atomic_write(path: str, data: dict) -> None:
    """atomic JSON write, 与 jarvis_utils 写法一致."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_raw(path: str) -> dict:
    if not os.path.exists(path):
        print(f'❌ vocab not found: {path}')
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _budget_bar(pct: float, width: int = 30) -> str:
    """ASCII 进度条 (0-100%)."""
    pct = max(0.0, min(100.0, pct))
    filled = int(pct / 100.0 * width)
    return '[' + '#' * filled + '-' * (width - filled) + f'] {pct:5.1f}%'


def cmd_list(helpers: dict) -> None:
    """默认: 当前状态 + 17 USD 进度 + 简要 caller 排名."""
    vocab = helpers['load'](force=True)
    stats = helpers['stats']()
    path = helpers['path']()

    print(f'\n=== DeepSeek Routing Vocab ({path}) ===\n')
    enabled = int(vocab.get('enabled', 0))
    gate = '[ON ]' if enabled else '[OFF]'
    ds_ok = bool(helpers['ds_key']())
    key_marker = '[OK]' if ds_ok else '[MISSING]'

    print(f'  Gate          : {gate}  (enabled={enabled})')
    print(f'  DS_ONLY key   : {key_marker}  (env OPENROUTER_DS_ONLY)')
    if not ds_ok and enabled:
        print('  ⚠️  WARN: gate ON 但 OPENROUTER_DS_ONLY 缺失 → routing 自动 disabled (故障开放)')

    route = vocab.get('deepseek_route', {}) or {}
    print(f'  Route model   : {route.get("model", "(none)")}')
    print(f'  Replace models: {len(route.get("replace_models", []))}')
    for m in route.get('replace_models', []) or []:
        print(f'      - {m}')
    excl = route.get('exclude_callers', []) or []
    if excl:
        print(f'  Exclude callers: {len(excl)}')
        for c in excl:
            print(f'      - {c}')

    print(f'  Fallback on fail: {int(route.get("fallback_on_fail", 1))}')
    print(f'  Timeout / temp / max_tok: {route.get("timeout_s", 60)}s / '
          f'{route.get("temperature_default", 0.2)} / '
          f'{route.get("max_tokens_default", 600)}')

    # budget
    budget = float(stats.get('budget_total_usd', 17.0))
    est = float(stats.get('est_cost_usd', 0.0))
    pct = float(stats.get('budget_pct_used', 0.0))
    print(f'\n  Budget (USD)  : {est:.4f} / {budget:.2f}  '
          f'(remaining ${stats.get("budget_remaining_usd", 0.0):.4f})')
    print(f'  {_budget_bar(pct)}')
    if pct >= 80.0:
        print(f'  ⚠️  WARN: 已用 {pct:.1f}% — Sir 准备 --reset-usage 或 --gate off')
    elif pct >= 95.0:
        print(f'  🚨 CRITICAL: 已用 {pct:.1f}% — 立即 --gate off 防超支')

    # usage
    print(f'\n  Calls         : {int(stats.get("call_count", 0))} '
          f'(success={int(stats.get("success_count", 0))}, '
          f'fallback={int(stats.get("fallback_count", 0))})')
    print(f'  Tokens        : in={int(stats.get("input_tokens_total", 0))}, '
          f'out={int(stats.get("output_tokens_total", 0))}')
    if stats.get('last_call_iso'):
        print(f'  Last call     : {stats["last_call_iso"]}')
    if stats.get('last_error'):
        print(f'  Last error    : {stats["last_error"][:120]}')

    print()
    print('Sir 操作 menu:')
    print('  --gate on|off            # toggling routing 全局')
    print('  --add-model / --remove-model MODEL  # 改 replace_models')
    print('  --add-exclude / --remove-exclude CALLER  # 改 exclude_callers')
    print('  --usage                  # per_caller breakdown')
    print('  --reset-usage            # 清零计数 (Sir 充值新一轮后)')
    print('  --history [N]            # 最近 N 条 mutation 记录')
    print('  --json                   # 机读输出')
    print()


def cmd_usage(helpers: dict) -> None:
    """详细 per_caller breakdown + budget."""
    vocab = helpers['load'](force=True)
    stats = helpers['stats']()
    per = (vocab.get('usage_stats', {}) or {}).get('per_caller', {}) or {}

    print(f'\n=== DeepSeek Usage Breakdown ===\n')
    budget = float(stats.get('budget_total_usd', 17.0))
    est = float(stats.get('est_cost_usd', 0.0))
    pct = float(stats.get('budget_pct_used', 0.0))
    print(f'  Budget : ${est:.4f} / ${budget:.2f}  ({pct:.2f}% used)')
    print(f'  {_budget_bar(pct)}\n')

    if not per:
        print('  (无 per_caller 数据 — 还没 routing 命中过)')
        return

    print(f'  {"caller":<30} {"calls":>7} {"succ":>6} {"fb":>5} '
          f'{"in_tok":>10} {"out_tok":>10} {"est_$":>10}')
    print(f'  {"-"*30} {"-"*7} {"-"*6} {"-"*5} {"-"*10} {"-"*10} {"-"*10}')
    # sort by est_cost desc
    rows = sorted(per.items(),
                  key=lambda kv: float(kv[1].get('est_cost_usd', 0.0)),
                  reverse=True)
    total_calls = total_succ = total_fb = 0
    total_in = total_out = 0
    total_cost = 0.0
    for caller, slot in rows:
        calls = int(slot.get('call_count', 0))
        succ = int(slot.get('success_count', 0))
        fb = int(slot.get('fallback_count', 0))
        in_tok = int(slot.get('input_tokens', 0))
        out_tok = int(slot.get('output_tokens', 0))
        cost = float(slot.get('est_cost_usd', 0.0))
        total_calls += calls
        total_succ += succ
        total_fb += fb
        total_in += in_tok
        total_out += out_tok
        total_cost += cost
        print(f'  {caller[:30]:<30} {calls:>7} {succ:>6} {fb:>5} '
              f'{in_tok:>10} {out_tok:>10} ${cost:>9.4f}')
    print(f'  {"-"*30} {"-"*7} {"-"*6} {"-"*5} {"-"*10} {"-"*10} {"-"*10}')
    print(f'  {"TOTAL":<30} {total_calls:>7} {total_succ:>6} {total_fb:>5} '
          f'{total_in:>10} {total_out:>10} ${total_cost:>9.4f}')
    print()


def cmd_history(helpers: dict, n: int) -> None:
    """最近 N 条 mutation history."""
    path = helpers['path']()
    data = _read_raw(path)
    hist = data.get('history', []) or []
    if not hist:
        print('\n[HISTORY] 空 (从未 mutate)\n')
        return
    recent = hist[-max(1, n):]
    print(f'\n=== History (last {len(recent)} of {len(hist)}) ===\n')
    for h in recent:
        ts = h.get('applied_iso', '?')
        action = h.get('action', '?')
        src = h.get('source', '?')
        rat = h.get('rationale', '') or ''
        extra = ''
        if action == 'gate_toggle':
            extra = f' {h.get("old_value", "?")} -> {h.get("new_value", "?")}'
        elif action in ('add_replace_model', 'remove_replace_model'):
            extra = f' model={h.get("model", "?")}'
        elif action == 'reset_usage_stats':
            extra = f' old_est=${h.get("old_est_cost_usd", 0.0):.4f}'
        elif action in ('add_exclude_caller', 'remove_exclude_caller'):
            extra = f' caller={h.get("caller", "?")}'
        print(f'  [{ts}] {action}{extra}  (by={src})')
        if rat:
            print(f'      reason: {rat}')
    print()


def cmd_gate(helpers: dict, on: bool, rationale: str) -> int:
    ok, msg = helpers['set_gate'](enabled=on, source='sir_cli', rationale=rationale)
    if ok:
        state = 'ON' if on else 'OFF'
        print(f'✅ Gate -> {state}  ({msg})')
        if on and not helpers['ds_key']():
            print('  ⚠️  WARN: OPENROUTER_DS_ONLY 缺失 → routing 自动 disabled '
                  '(故障开放, 不阻塞主流). Sir fill key 后再试.')
        return 0
    print(f'❌ set_gate failed: {msg}')
    return 2


def cmd_add_model(helpers: dict, model: str, rationale: str) -> int:
    ok, msg = helpers['add_model'](model=model, source='sir_cli', rationale=rationale)
    if ok:
        print(f'✅ {msg}')
        return 0
    print(f'❌ add_model failed: {msg}')
    return 2


def cmd_remove_model(helpers: dict, model: str, rationale: str) -> int:
    ok, msg = helpers['remove_model'](model=model, source='sir_cli', rationale=rationale)
    if ok:
        print(f'✅ {msg}')
        return 0
    print(f'❌ remove_model failed: {msg}')
    return 2


def _mutate_exclude(helpers: dict, caller: str, add: bool,
                     rationale: str) -> int:
    """add/remove exclude_callers, atomic + history (jarvis_utils 没暴露公开 API,
    在 CLI 里直接 mutate vocab JSON. 与 set_gate 范式一致)."""
    caller = (caller or '').strip()
    if not caller:
        print('❌ caller 不能为空')
        return 2
    path = helpers['path']()
    data = _read_raw(path)
    route = data.setdefault('deepseek_route', {})
    excl = route.setdefault('exclude_callers', [])
    if add:
        if caller in excl:
            print(f'❌ already in exclude: {caller}')
            return 2
        excl.append(caller)
        action = 'add_exclude_caller'
        msg = f'added exclude: {caller} (now {len(excl)} excluded)'
    else:
        if caller not in excl:
            print(f'❌ not in exclude: {caller}')
            return 2
        excl.remove(caller)
        action = 'remove_exclude_caller'
        msg = f'removed exclude: {caller} (now {len(excl)} excluded)'

    now = time.time()
    iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now))
    hist = data.setdefault('history', [])
    hist.append({
        'action': action,
        'caller': caller,
        'source': 'sir_cli',
        'rationale': rationale[:200],
        'applied_at': now,
        'applied_iso': iso,
    })
    data['last_modified_at'] = now
    data['last_modified_iso'] = iso

    _atomic_write(path, data)
    helpers['invalidate']()
    print(f'✅ {msg}')
    return 0


def cmd_reset_usage(helpers: dict, rationale: str) -> int:
    ok, msg = helpers['reset_usage'](source='sir_cli', rationale=rationale)
    if ok:
        print(f'✅ usage reset ({msg})')
        return 0
    print(f'❌ reset_usage failed: {msg}')
    return 2


def cmd_json(helpers: dict) -> None:
    """机读 JSON 输出 (vocab + computed stats)."""
    vocab = helpers['load'](force=True)
    stats = helpers['stats']()
    payload = {
        'vocab': vocab,
        'computed_stats': stats,
        'ds_key_configured': bool(helpers['ds_key']()),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='LLM 路由 vocab CLI (Sir 2026-05-28 fix45, 准则 6 持久化)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--gate', choices=['on', 'off'],
                        help='启用/关闭 DeepSeek 路由 (Sir 元否决一键关)')
    parser.add_argument('--add-model', metavar='MODEL',
                        help='加 model 到 replace_models (e.g. google/gemini-3.1-pro-preview)')
    parser.add_argument('--remove-model', metavar='MODEL',
                        help='从 replace_models 移除 model')
    parser.add_argument('--add-exclude', metavar='CALLER',
                        help='加 caller 到 exclude_callers (即使 model 命中也不路由)')
    parser.add_argument('--remove-exclude', metavar='CALLER',
                        help='从 exclude_callers 移除 caller')
    parser.add_argument('--usage', action='store_true',
                        help='详细 per_caller breakdown + budget')
    parser.add_argument('--reset-usage', action='store_true',
                        help='清零 usage stats (Sir 充值新一轮后)')
    parser.add_argument('--history', nargs='?', type=int, const=10,
                        metavar='N', help='最近 N 条 mutation history (default 10)')
    parser.add_argument('--rationale', default='', metavar='TEXT',
                        help='给本次 mutation 加注释 (写进 history)')
    parser.add_argument('--json', action='store_true',
                        help='机读 JSON 输出')
    args = parser.parse_args()

    helpers = _load_helpers()
    rationale = (args.rationale or '').strip()

    # mutation 命令优先
    if args.gate is not None:
        return cmd_gate(helpers, on=(args.gate == 'on'), rationale=rationale)
    if args.add_model:
        return cmd_add_model(helpers, args.add_model, rationale)
    if args.remove_model:
        return cmd_remove_model(helpers, args.remove_model, rationale)
    if args.add_exclude:
        return _mutate_exclude(helpers, args.add_exclude, add=True, rationale=rationale)
    if args.remove_exclude:
        return _mutate_exclude(helpers, args.remove_exclude, add=False, rationale=rationale)
    if args.reset_usage:
        return cmd_reset_usage(helpers, rationale)

    # 查询命令
    if args.json:
        cmd_json(helpers)
        return 0
    if args.history is not None:
        cmd_history(helpers, args.history)
        return 0
    if args.usage:
        cmd_usage(helpers)
        return 0

    # 默认 list
    cmd_list(helpers)
    return 0


if __name__ == '__main__':
    sys.exit(main())
