#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[fixE-llm-semantic-backstop / 2026-06-09] claim_semantic_dump.py — L2.6 LLM 语义兜底 vocab CLI

Sir 准则 6.5: vocab 必须 (1) 持久化 (2) CLI 可改 (3) L7 LLM-propose.

schema (_meta):
  enforce: bool       — false=影子期 (LLM verdict 只 record); true=LLM 翻案生效
  model: str          — 判定用 model (区域可用便宜判定型)
  max_tokens / temperature
  prompt_template: str — 含 {claim_text} / {events} 占位

用法:
  python scripts/claim_semantic_dump.py                 # show
  python scripts/claim_semantic_dump.py --set-model google/gemini-2.5-flash-lite-preview-09-2025
  python scripts/claim_semantic_dump.py --set-prompt-file path/to/prompt.txt
  python scripts/claim_semantic_dump.py --enforce on|off
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'claim_semantic_vocab.json')

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _load() -> dict:
    if not os.path.exists(VOCAB_PATH):
        return {'_meta': {'schema_version': 1, 'enforce': False}}
    try:
        with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"读 vocab 失败: {e}")
        sys.exit(1)


def _save(data: dict) -> None:
    data.setdefault('_meta', {})['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, VOCAB_PATH)


def cmd_show() -> int:
    data = _load()
    m = data.get('_meta', {})
    print("claim_semantic_vocab.json — L2.6 LLM 语义兜底")
    print("=" * 70)
    print(f"  enforce      = {m.get('enforce', False)} "
          f"({'LLM 翻案生效' if m.get('enforce') else '影子期 (只 record)'})")
    print(f"  model        = {m.get('model', '(none)')}")
    print(f"  max_tokens   = {m.get('max_tokens', '?')}")
    print(f"  temperature  = {m.get('temperature', '?')}")
    pt = m.get('prompt_template', '')
    print(f"  prompt_template ({len(pt)} chars):")
    print("  " + "-" * 66)
    for line in pt.split('\n')[:6]:
        print(f"    {line[:80]}")
    if pt.count('\n') > 6:
        print(f"    ... (+{pt.count(chr(10)) - 6} more lines)")
    # 占位符校验
    has_claim = '{claim_text}' in pt
    has_events = '{events}' in pt
    print("  " + "-" * 66)
    print(f"  占位符: {{claim_text}}={'✓' if has_claim else '✗ 缺!'}  "
          f"{{events}}={'✓' if has_events else '✗ 缺!'}")
    return 0


def cmd_set_model(model: str) -> int:
    data = _load()
    old = data.get('_meta', {}).get('model')
    data.setdefault('_meta', {})['model'] = model
    _save(data)
    print(f"model: {old} → {model}")
    return 0


def cmd_set_prompt_file(path: str) -> int:
    if not os.path.exists(path):
        print(f"prompt 文件不存在: {path}")
        return 1
    pt = io.open(path, encoding='utf-8').read()
    if '{claim_text}' not in pt or '{events}' not in pt:
        print("prompt 必须含 {claim_text} 和 {events} 占位符, 拒绝写入")
        return 1
    data = _load()
    data.setdefault('_meta', {})['prompt_template'] = pt
    _save(data)
    print(f"prompt_template 更新 ({len(pt)} chars)")
    return 0


def cmd_enforce(val: str) -> int:
    data = _load()
    new_val = (val.lower() == 'on')
    old = bool(data.get('_meta', {}).get('enforce', False))
    data.setdefault('_meta', {})['enforce'] = new_val
    _save(data)
    print(f"enforce: {old} → {new_val} "
          f"({'LLM 翻案生效 (YES→verified)' if new_val else '影子期 (只 record)'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--set-model', metavar='MODEL')
    ap.add_argument('--set-prompt-file', metavar='PATH')
    ap.add_argument('--enforce', choices=['on', 'off'])
    args = ap.parse_args()
    if args.set_model:
        return cmd_set_model(args.set_model)
    if args.set_prompt_file:
        return cmd_set_prompt_file(args.set_prompt_file)
    if args.enforce:
        return cmd_enforce(args.enforce)
    return cmd_show()


if __name__ == '__main__':
    sys.exit(main())
