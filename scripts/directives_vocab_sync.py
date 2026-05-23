# -*- coding: utf-8 -*-
"""[P5-fix47 / 2026-05-23 15:15] directives_vocab.json ← jarvis_directives.py seed sync.

Sir 准则 6 硬规 #1: 持久化到 memory_pool/*.json. Log 抓到:
  ⚠️ [DirectiveBootstrap] 11 directive 仅在 .py seed, 应 sync 到 directives_vocab.json

这 11 个 directive 工作正常 (seed fallback merge 注册了), 但 Sir CLI 不能查/改 →
违反准则 6 (持久化 + CLI 可改).

本工具: 从 jarvis_directives.py seed 提取每个 missing directive 的 metadata (id /
priority / ttl_days / source_marker / tier_whitelist / purpose_short) → 写入
directives_vocab.json (state='active').

注意: text 字段不 sync (太长, 仍在 .py source). seed merge 路径继续从 .py
拿 text. JSON 只存 metadata + state, 让 Sir CLI 可看/激活/拒/调 priority.

用法:
  python scripts/directives_vocab_sync.py --dry-run    # 看 diff
  python scripts/directives_vocab_sync.py --apply      # 真写入 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


VOCAB_PATH = ROOT / 'memory_pool' / 'directives_vocab.json'
SEED_PATH = ROOT / 'jarvis_directives.py'


def extract_seed_directives() -> list:
    """从 jarvis_directives.py 抽所有 Directive(...) 块的 metadata."""
    src = SEED_PATH.read_text(encoding='utf-8')
    # 匹配 Directive( ... ) 块 — DOTALL, non-greedy
    # 简化匹配: 找每个 'Directive(' 然后看到匹配的 ')'
    out = []
    i = 0
    while True:
        start = src.find('Directive(', i)
        if start < 0:
            break
        # 找匹配的右括号 (考虑嵌套)
        depth = 0
        j = start + len('Directive(')
        while j < len(src):
            c = src[j]
            if c == '(':
                depth += 1
            elif c == ')':
                if depth == 0:
                    break
                depth -= 1
            j += 1
        block = src[start:j+1] if j < len(src) else src[start:]
        i = j + 1

        # 抽字段
        def _grab(pat, default=''):
            m = re.search(pat, block, re.DOTALL)
            return m.group(1) if m else default

        did = _grab(r"id\s*=\s*['\"]([^'\"]+)['\"]")
        if not did:
            continue
        priority = int(_grab(r"priority\s*=\s*(\d+)", '5') or 5)
        ttl_days = int(_grab(r"ttl_days\s*=\s*(\d+)", '90') or 90)
        marker = _grab(r"source_marker\s*=\s*['\"]([^'\"]+)['\"]")
        purpose = _grab(r"purpose_short\s*=\s*['\"]([^'\"]+)['\"]")
        # tier_whitelist: 简化, 默认空 list
        tw_match = re.search(r"tier_whitelist\s*=\s*\[(.*?)\]", block, re.DOTALL)
        tiers = []
        if tw_match:
            for m in re.finditer(r"['\"](\w+)['\"]", tw_match.group(1)):
                tiers.append(m.group(1))
        # trigger fn name
        trig = _grab(r"trigger\s*=\s*(\w+)", 'None')

        out.append({
            'id': did,
            'priority': priority,
            'ttl_days': ttl_days,
            'source_marker': marker,
            'purpose_short': purpose,
            'tier_whitelist': tiers,
            'trigger_fn': trig,
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true', help='真写入 JSON (默认 dry-run)')
    p.add_argument('--dry-run', action='store_true', default=False)
    args = p.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True

    if not VOCAB_PATH.exists():
        print(f'❌ vocab not found: {VOCAB_PATH}')
        return 1

    vocab = json.loads(VOCAB_PATH.read_text(encoding='utf-8'))
    json_ids = {d.get('id') for d in vocab.get('directives', [])}

    seed = extract_seed_directives()
    seed_ids = {d['id'] for d in seed}

    missing = sorted(seed_ids - json_ids)
    extra_in_json = sorted(json_ids - seed_ids)

    print(f'JSON vocab: {len(json_ids)} directives')
    print(f'.py seed:   {len(seed_ids)} directives')
    print(f'')
    print(f'=== Missing from JSON (seed-only, 违准则 6 #1): {len(missing)} ===')
    for did in missing:
        sd = next((d for d in seed if d['id'] == did), None)
        if sd:
            print(f'  + {did} (priority={sd["priority"]}, marker={sd["source_marker"][:30]})')

    print(f'\n=== In JSON only (deprecated/.py 已删): {len(extra_in_json)} ===')
    for did in extra_in_json:
        print(f'  - {did}')

    if not missing:
        print('\n✅ JSON 与 seed 同步, 无需更新.')
        return 0

    if args.dry_run:
        print(f'\n💡 dry-run mode. 加 --apply 真写入 JSON.')
        return 0

    # 真写入: append missing to vocab
    print(f'\n📝 写入 {len(missing)} 条 missing directive metadata 到 JSON ...')
    for did in missing:
        sd = next((d for d in seed if d['id'] == did), None)
        if not sd:
            continue
        entry = {
            'id': did,
            'state': 'active',
            'priority': sd['priority'],
            'ttl_days': sd['ttl_days'],
            'source_marker': sd['source_marker'],
            'purpose_short': sd['purpose_short'],
            'tier_whitelist': sd['tier_whitelist'],
            'trigger_fn_name': sd['trigger_fn'],
            'text_source': '.py seed (long text 不 sync, 留 source-of-truth)',
        }
        vocab.setdefault('directives', []).append(entry)
        print(f'  ✅ {did}')

    # backup + write
    backup = str(VOCAB_PATH) + '.bak'
    import shutil
    shutil.copy2(VOCAB_PATH, backup)
    VOCAB_PATH.write_text(
        json.dumps(vocab, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n✅ done. backup: {backup}')
    print(f'   下次重启 Jarvis, DirectiveBootstrap 不再报 "seed-filled (JSON 缺)".')
    return 0


if __name__ == '__main__':
    sys.exit(main())
