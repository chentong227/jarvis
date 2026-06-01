# -*- coding: utf-8 -*-
"""[β.5.19-B / 2026-05-20] predicate_keywords.json CLI 工具.

Sir 准则 6 三硬规第 2 条 "CLI 可改" 落地. 老 jarvis_predicate.py 把 wake/export/
premiere keywords 写死在 source list (`_WAKE_KEYWORDS = (...)` 等), Sir 加新词需
改 .py + git commit. β.5.19-B 迁 json + 此 CLI 让 Sir 直接 list/show/add/count 不动源码.

vocab 用途:
  jarvis_predicate.heuristic_predicate_from_text() 的 LLM 不可用 fallback.
  抓 Sir 自然语言 ("明早醒了" / "导出完视频" / ...) 推 predicate
  (WakeFirstActive / ProcessExited(...) 等), 后续 commitment_watcher 用作触发条件.

接口 (兼容 scripts/concerns_dump.py + cmt_vocab_dump.py 风格):
  python scripts/predicate_vocab_dump.py             # 默认 list (按 group)
  python scripts/predicate_vocab_dump.py --show GROUP # 看某 group 全部 keywords
  python scripts/predicate_vocab_dump.py --add GROUP=KEYWORD  # 加 (Sir 自决)
  python scripts/predicate_vocab_dump.py --counts    # 各 group keyword 计数

Reflector L7 LLM-propose 仍待做 (β.5+ 后续轨道).
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


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'predicate_keywords.json')

VALID_GROUPS = ('wake', 'export', 'premiere')


def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        print(f'❌ vocab 文件不存在: {VOCAB_PATH}')
        sys.exit(1)
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_vocab(vocab: dict) -> None:
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def cmd_list(vocab: dict) -> None:
    print(f'\n=== Predicate Keywords Vocab ({VOCAB_PATH}) ===\n')
    print(f'  version : {vocab.get("version", "?")}')
    print(f'  created : {vocab.get("created_at", "?")}\n')
    groups = vocab.get('groups', {})
    for g in VALID_GROUPS:
        gd = groups.get(g, {})
        kws = gd.get('keywords', [])
        desc = gd.get('description', '')
        print(f'  {g:<10} ({len(kws):>2} keywords)  {desc}')
    print()


def cmd_show(vocab: dict, group: str) -> None:
    if group not in VALID_GROUPS:
        print(f'❌ unknown group: {group}')
        print(f'   valid: {", ".join(VALID_GROUPS)}')
        sys.exit(1)
    groups = vocab.get('groups', {})
    gd = groups.get(group, {})
    kws = gd.get('keywords', [])
    desc = gd.get('description', '')
    print(f'\n{group} ({len(kws)} keywords): {desc}')
    for i, k in enumerate(kws, 1):
        print(f'  {i:>2}. {k}')
    print()


def cmd_counts(vocab: dict) -> None:
    print('\n=== keyword counts ===')
    groups = vocab.get('groups', {})
    for g in VALID_GROUPS:
        kws = groups.get(g, {}).get('keywords', [])
        print(f'  {g:<10} {len(kws)}')
    print()


def cmd_add(vocab: dict, key_val: str) -> None:
    if '=' not in key_val:
        print('❌ --add 需 GROUP=KEYWORD 格式')
        sys.exit(1)
    group, keyword = key_val.split('=', 1)
    group = group.strip()
    keyword = keyword.strip()
    if group not in VALID_GROUPS:
        print(f'❌ unknown group: {group}')
        sys.exit(1)
    groups = vocab.setdefault('groups', {})
    gd = groups.setdefault(group, {'description': '', 'keywords': []})
    kws = gd.setdefault('keywords', [])
    if keyword in kws:
        print(f'⚠️ keyword 已存在于 {group}')
        return
    kws.append(keyword)
    # history 追加
    history = vocab.setdefault('history', [])
    import datetime as _dt
    history.append({
        'ts': _dt.datetime.now().isoformat(timespec='seconds'),
        'marker': 'CLI',
        'action': 'add',
        'group': group,
        'keyword': keyword,
    })
    _save_vocab(vocab)
    print(f'✅ {group}: 新增 keyword {keyword!r} (now {len(kws)} keywords)')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Predicate Keywords Vocab CLI (β.5.19-B)')
    parser.add_argument('--show', metavar='GROUP', help='看某 group 全部 keywords')
    parser.add_argument('--add', metavar='GROUP=KEYWORD', help='加 keyword')
    parser.add_argument('--counts', action='store_true', help='各 group 计数')
    args = parser.parse_args()

    vocab = _load_vocab()
    if args.show:
        cmd_show(vocab, args.show)
    elif args.add:
        cmd_add(vocab, args.add)
    elif args.counts:
        cmd_counts(vocab)
    else:
        cmd_list(vocab)


if __name__ == '__main__':
    main()
