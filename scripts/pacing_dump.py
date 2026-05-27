# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 22:11 P10 治本] InnerThought self-pacing vocab CLI.

Sir 真问 (准则 6 vocab 持久化 + 准则 7 元否决):
  "贾维斯会动态变频吗? 发现自己不用太担心吗? 一直在想, 经常想重复事情"
  Sir 自查: "都像硬编码, 你觉得呢?"

治本: 不在 .py 写 if rule, 喂 raw self-signal 给思考脑, LLM 自决 NEXT_INTERVAL.
       lookback / signals_enabled / signal_fields / prompt 措辞 / SWM publish
       全 vocab JSON, Sir CLI 改不动 .py.

用法:
  python scripts/pacing_dump.py list
  python scripts/pacing_dump.py disable-signal self_thread_diversity
  python scripts/pacing_dump.py enable-signal self_thread_diversity
  python scripts/pacing_dump.py set-lookback 7
  python scripts/pacing_dump.py disable-prompt-block
  python scripts/pacing_dump.py enable-prompt-block
  python scripts/pacing_dump.py disable-swm
  python scripts/pacing_dump.py enable-swm
  python scripts/pacing_dump.py history
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Windows GBK 默认 console encoding 无法打 emoji. 强制 stdout utf-8.
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(
    ROOT, 'memory_pool', 'inner_thought_pacing_vocab.json'
)

VALID_SIGNALS = (
    'self_recent_quality',
    'self_thread_diversity',
    'overall_concern_pressure',
)


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(f"⚠️  {path} not found")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _add_history(data: dict, op: str, detail: str) -> None:
    hist = data.get('history') or []
    hist.append({
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'op': op,
        'detail': detail,
        'source': 'sir_cli',
    })
    data['history'] = hist[-100:]  # cap


def cmd_list(args):
    data = _load(args.path)
    meta = data.get('_meta') or {}
    print(f"📋 InnerThought self-pacing vocab @ {args.path}")
    print(f"   schema_version: {meta.get('schema_version', '?')}")
    print(f"   purpose: {meta.get('purpose', '?')[:120]}")
    print(f"\n[lookback_n] {data.get('lookback_n', '?')}")
    print(f"\n[signals_enabled]")
    for sig, on in (data.get('signals_enabled') or {}).items():
        mark = "✅" if on else "❌"
        print(f"   {mark} {sig}")
    pb = data.get('prompt_signal_block') or {}
    print(f"\n[prompt_signal_block]")
    print(f"   enabled: {'✅' if pb.get('enabled', True) else '❌'}")
    print(f"   max_chars: {pb.get('max_chars', '?')}")
    print(f"   tone: {pb.get('tone', '?')}")
    swp = data.get('swm_publish') or {}
    print(f"\n[swm_publish]")
    print(f"   enabled: {'✅' if swp.get('enabled', True) else '❌'}")
    print(f"   etype: {swp.get('etype', '?')}")
    print(f"   ttl_s: {swp.get('ttl_s', '?')}")
    print(f"   salience: {swp.get('salience', '?')}")
    hist = data.get('history') or []
    print(f"\n[History] {len(hist)} ops (use 'history' cmd to see 30 latest)")


def cmd_enable_signal(args):
    if args.signal not in VALID_SIGNALS:
        print(f"❌ unknown signal '{args.signal}', valid: {VALID_SIGNALS}")
        sys.exit(1)
    data = _load(args.path)
    sigs = data.get('signals_enabled') or {}
    sigs[args.signal] = True
    data['signals_enabled'] = sigs
    _add_history(data, 'enable_signal', args.signal)
    _save(args.path, data)
    print(f"✅ enabled signal '{args.signal}'")


def cmd_disable_signal(args):
    if args.signal not in VALID_SIGNALS:
        print(f"❌ unknown signal '{args.signal}', valid: {VALID_SIGNALS}")
        sys.exit(1)
    data = _load(args.path)
    sigs = data.get('signals_enabled') or {}
    sigs[args.signal] = False
    data['signals_enabled'] = sigs
    _add_history(data, 'disable_signal', args.signal)
    _save(args.path, data)
    print(f"❌ disabled signal '{args.signal}'")


def cmd_set_lookback(args):
    n = int(args.n)
    if n < 1 or n > 30:
        print(f"❌ lookback_n must be 1-30, got {n}")
        sys.exit(1)
    data = _load(args.path)
    old = data.get('lookback_n', '?')
    data['lookback_n'] = n
    _add_history(data, 'set_lookback', f"{old} → {n}")
    _save(args.path, data)
    print(f"✅ lookback_n: {old} → {n}")


def cmd_enable_prompt_block(args):
    data = _load(args.path)
    pb = data.get('prompt_signal_block') or {}
    pb['enabled'] = True
    data['prompt_signal_block'] = pb
    _add_history(data, 'enable_prompt_block', 'on')
    _save(args.path, data)
    print(f"✅ prompt_signal_block enabled")


def cmd_disable_prompt_block(args):
    data = _load(args.path)
    pb = data.get('prompt_signal_block') or {}
    pb['enabled'] = False
    data['prompt_signal_block'] = pb
    _add_history(data, 'disable_prompt_block', 'off')
    _save(args.path, data)
    print(f"❌ prompt_signal_block disabled (LLM won't see signal block)")


def cmd_enable_swm(args):
    data = _load(args.path)
    sw = data.get('swm_publish') or {}
    sw['enabled'] = True
    data['swm_publish'] = sw
    _add_history(data, 'enable_swm', 'on')
    _save(args.path, data)
    print(f"✅ swm_publish enabled")


def cmd_disable_swm(args):
    data = _load(args.path)
    sw = data.get('swm_publish') or {}
    sw['enabled'] = False
    data['swm_publish'] = sw
    _add_history(data, 'disable_swm', 'off')
    _save(args.path, data)
    print(f"❌ swm_publish disabled (no 'inner_thought_self_signal' event)")


def cmd_history(args):
    data = _load(args.path)
    hist = data.get('history') or []
    if not hist:
        print("(no history entries)")
        return
    print(f"📋 History ({len(hist)} ops, latest 30):")
    for e in hist[-30:]:
        print(
            f"   [{e.get('when', '?')}] {e.get('op', '?'):24} "
            f"{e.get('detail', '?')} ({e.get('source', '?')})"
        )


def main():
    parser = argparse.ArgumentParser(
        description='InnerThought self-pacing vocab CLI (Sir 22:11 P10)'
    )
    parser.add_argument('--path', default=DEFAULT_PATH)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列 vocab 全状态')
    p_list.set_defaults(func=cmd_list)

    p_en = sub.add_parser('enable-signal',
                            help=f"开启 signal ({'/'.join(VALID_SIGNALS)})")
    p_en.add_argument('signal')
    p_en.set_defaults(func=cmd_enable_signal)

    p_di = sub.add_parser('disable-signal',
                            help=f"关闭 signal ({'/'.join(VALID_SIGNALS)})")
    p_di.add_argument('signal')
    p_di.set_defaults(func=cmd_disable_signal)

    p_lb = sub.add_parser('set-lookback', help='改 lookback_n (1-30)')
    p_lb.add_argument('n', type=int)
    p_lb.set_defaults(func=cmd_set_lookback)

    p_pen = sub.add_parser('enable-prompt-block',
                              help='开启 [YOUR RECENT PACING SIGNAL] prompt 段')
    p_pen.set_defaults(func=cmd_enable_prompt_block)

    p_pdi = sub.add_parser('disable-prompt-block',
                              help='关闭 [YOUR RECENT PACING SIGNAL] prompt 段')
    p_pdi.set_defaults(func=cmd_disable_prompt_block)

    p_sen = sub.add_parser('enable-swm',
                              help="开启 SWM 'inner_thought_self_signal' publish")
    p_sen.set_defaults(func=cmd_enable_swm)

    p_sdi = sub.add_parser('disable-swm',
                              help="关闭 SWM 'inner_thought_self_signal' publish")
    p_sdi.set_defaults(func=cmd_disable_swm)

    p_hist = sub.add_parser('history', help='历史 ops (最近 30)')
    p_hist.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
