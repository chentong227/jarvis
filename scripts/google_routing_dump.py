# -*- coding: utf-8 -*-
"""[Sir 2026-06-08] Google 模型档路由 CLI 工具 (准则6 vocab 三件套).

弃付费 key 后: 两个免费 Google key 轮流跑 flash-lite + embedding; 3-flash 转
OpenRouter。本工具让 Sir 不改源码就能调每个 Google 模型档走哪条通道。
即时生效 (safe_gemini_call 每次调用 mtime-cache 读 vocab)。

用法:
  python scripts/google_routing_dump.py                          # list 当前路由
  python scripts/google_routing_dump.py --force-openrouter MODEL # MODEL 强制走 OpenRouter
  python scripts/google_routing_dump.py --google-only MODEL      # MODEL 只走 Google 不 fallback
  python scripts/google_routing_dump.py --clear MODEL            # MODEL 移出两表 (回老 50/50 双通道)
  python scripts/google_routing_dump.py --reset                  # 恢复 seed 默认

路由语义:
  force_openrouter        — 强制只走 OpenRouter (不试 Google), 省免费 key 额度。
                            走 _OR_MODEL_MAP 映射到 OpenRouter 模型。
  google_only_no_fallback — 只走 Google 两免费 key 轮流, 失败**不** fallback
                            OpenRouter (Sir 明确不烧 OpenRouter 余额)。
  (未列出)                — 老 50/50 双通道行为 (向后兼容)。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
try:
    import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout
except Exception:
    pass


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'google_model_routing.json')

_SEED = {
    "_meta": {
        "schema": "google_model_routing",
        "schema_version": 1,
        "purpose": "[Sir 2026-06-08] Google 模型档路由表 (准则6). 两免费 key 轮流跑 "
                   "flash-lite + embedding; 3-flash 转 OpenRouter.",
        "edit_via": "scripts/google_routing_dump.py",
    },
    "force_openrouter": ["gemini-3-flash-preview"],
    "google_only_no_fallback": ["gemini-3.1-flash-lite"],
}


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return json.loads(json.dumps(_SEED))
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data.setdefault('force_openrouter', [])
    data.setdefault('google_only_no_fallback', [])
    return data


def _save(vocab: dict) -> None:
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def cmd_list(vocab: dict) -> None:
    print(f'\n=== Google Model Routing ({VOCAB_PATH}) ===\n')
    print('force_openrouter (强制 OpenRouter, 不试 Google):')
    for m in vocab.get('force_openrouter', []):
        print(f'  - {m}')
    if not vocab.get('force_openrouter'):
        print('  (none)')
    print('\ngoogle_only_no_fallback (只走 Google 两免费 key, 不 fallback):')
    for m in vocab.get('google_only_no_fallback', []):
        print(f'  - {m}')
    if not vocab.get('google_only_no_fallback'):
        print('  (none)')
    print('\n其余 model_name → 老 50/50 双通道 (向后兼容)。\n')


def _clear_from_both(vocab: dict, model: str) -> None:
    vocab['force_openrouter'] = [m for m in vocab.get('force_openrouter', []) if m != model]
    vocab['google_only_no_fallback'] = [
        m for m in vocab.get('google_only_no_fallback', []) if m != model]


def main() -> int:
    ap = argparse.ArgumentParser(description='Google 模型档路由 CLI (准则6)')
    ap.add_argument('--force-openrouter', metavar='MODEL',
                    help='MODEL 强制走 OpenRouter')
    ap.add_argument('--google-only', metavar='MODEL',
                    help='MODEL 只走 Google 两免费 key 不 fallback')
    ap.add_argument('--clear', metavar='MODEL',
                    help='MODEL 移出两表 (回老 50/50 双通道)')
    ap.add_argument('--reset', action='store_true', help='恢复 seed 默认')
    args = ap.parse_args()

    if args.reset:
        _save(json.loads(json.dumps(_SEED)))
        print('✅ 已恢复 seed 默认路由。')
        cmd_list(_load())
        return 0

    vocab = _load()
    changed = False

    if args.force_openrouter:
        m = args.force_openrouter
        _clear_from_both(vocab, m)
        vocab['force_openrouter'].append(m)
        changed = True
        print(f'✅ {m} → force_openrouter')

    if args.google_only:
        m = args.google_only
        _clear_from_both(vocab, m)
        vocab['google_only_no_fallback'].append(m)
        changed = True
        print(f'✅ {m} → google_only_no_fallback')

    if args.clear:
        _clear_from_both(vocab, args.clear)
        changed = True
        print(f'✅ {args.clear} 已移出两表 (回老双通道)')

    if changed:
        _save(vocab)

    cmd_list(_load())
    return 0


if __name__ == '__main__':
    sys.exit(main())
