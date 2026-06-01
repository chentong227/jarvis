# -*- coding: utf-8 -*-
"""[Gap-Z1 / β.5.46-fix4] STM Reply Summarizer CLI Dump.

准则 6.5 持久化 + CLI 可改 + L7 Reflector LLM-propose. 本工具 Sir 不改源码就能:
  - --list: 看当前 config + stats
  - --enable / --disable: 切开关 (写 memory_pool/stm_summarize_config.json)
  - --threshold N: 改 min_chars_to_summarize
  - --max-chars N: 改 max_summary_chars
  - --test "<reply>": 离线测压缩输出 (调真 LLM)

Usage:
    python scripts/stm_summarize_dump.py --list
    python scripts/stm_summarize_dump.py --disable
    python scripts/stm_summarize_dump.py --threshold 250
    python scripts/stm_summarize_dump.py --test "I should mention earlier I said 4%..."
"""
from __future__ import annotations

import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout


# add parent dir to sys.path
_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
sys.path.insert(0, _ROOT)

CONFIG_PATH = os.path.join(_ROOT, 'memory_pool', 'stm_summarize_config.json')


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(f'❌ config not found: {CONFIG_PATH}')
        sys.exit(1)
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f'✅ saved {CONFIG_PATH}')


def cmd_list():
    cfg = load_config()
    print(f'📝 STM Summarizer Config ({CONFIG_PATH})')
    print('=' * 60)
    for k, v in cfg.items():
        if k.startswith('_'):
            continue
        print(f'  {k:30s} = {v}')
    print('=' * 60)
    # stats (if registered)
    try:
        from jarvis_stm_summarizer import get_default_summarizer
        s = get_default_summarizer()
        if s is not None:
            print('📊 Runtime Stats (current process — needs running Jarvis):')
            for k, v in s.stats().items():
                print(f'  {k:30s} = {v}')
        else:
            print('(no running summarizer)')
    except Exception as e:
        print(f'(stats unavailable: {e})')


def cmd_enable(enabled: bool):
    cfg = load_config()
    cfg['enabled'] = enabled
    save_config(cfg)
    print(f'✅ enabled = {enabled}')


def cmd_threshold(n: int):
    cfg = load_config()
    cfg['min_chars_to_summarize'] = max(50, n)
    save_config(cfg)
    print(f'✅ min_chars_to_summarize = {cfg["min_chars_to_summarize"]}')


def cmd_max_chars(n: int):
    cfg = load_config()
    cfg['max_summary_chars'] = max(50, n)
    save_config(cfg)
    print(f'✅ max_summary_chars = {cfg["max_summary_chars"]}')


def cmd_test(reply: str):
    print(f'📥 Input ({len(reply)}c):\n  {reply[:300]}{"..." if len(reply) > 300 else ""}')
    print('-' * 60)
    try:
        from jarvis_stm_summarizer import STMSummarizer
        from jarvis_key_router import get_default_router
        kr = get_default_router()
        s = STMSummarizer(key_router=kr)
        if not s.should_summarize(reply):
            print('⚠️  too short to summarize (< min_chars threshold)')
            return
        print('🔄 calling LLM...')
        result = s.summarize(sir_utterance='(test)', raw_reply=reply)
        if result:
            print(f'📤 Output ({len(result)}c):\n  {result}')
        else:
            print('❌ LLM call failed (check key router / network)')
    except Exception as e:
        print(f'❌ test failed: {e}')


def main():
    parser = argparse.ArgumentParser(description='STM Summarizer CLI Tool')
    parser.add_argument('--list', action='store_true', help='List current config + stats')
    parser.add_argument('--enable', action='store_true', help='Enable summarizer')
    parser.add_argument('--disable', action='store_true', help='Disable summarizer')
    parser.add_argument('--threshold', type=int, help='Set min_chars_to_summarize')
    parser.add_argument('--max-chars', type=int, help='Set max_summary_chars')
    parser.add_argument('--test', type=str, help='Test compress (real LLM call)')
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.enable:
        cmd_enable(True)
    elif args.disable:
        cmd_enable(False)
    elif args.threshold is not None:
        cmd_threshold(args.threshold)
    elif args.max_chars is not None:
        cmd_max_chars(args.max_chars)
    elif args.test is not None:
        cmd_test(args.test)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
