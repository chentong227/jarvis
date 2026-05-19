# -*- coding: utf-8 -*-
"""[β.5.19-C / 2026-05-20] promise_soft_vocab.json CLI 工具.

Sir 准则 6 三硬规第 2 条 "CLI 可改" 落地. 老 jarvis_self_promise.py 把 soft
promise 动词词表写死在 source list (`_EN_SOFT_PROMISE_VERBS = (...)` /
`_ZH_SOFT_PROMISE_VERBS = (...)`), Sir 实测发现新动词 (β.2.7.8 立时的
'integrate reminders') 需改 .py + git commit. β.5.19-C 迁 json + 此 CLI 让 Sir
list/show/add/count 不动源码; vocab mtime 变后 detect regex 自动 recompile.

vocab 用途:
  SelfPromiseDetector 的 soft promise (无时间锚) 检测. 抓 "I will monitor X" /
  "我会留意 X" 类承诺. hard (有时间锚) 走另一套复杂 regex 留源码 (递归边界).

接口 (兼容 cmt_vocab_dump.py / predicate_vocab_dump.py 风格):
  python scripts/promise_vocab_dump.py             # 默认 list (按 group)
  python scripts/promise_vocab_dump.py --show GROUP # 看某 group 全部 verbs
  python scripts/promise_vocab_dump.py --add GROUP=VERB  # 加 (Sir 自决)
  python scripts/promise_vocab_dump.py --counts    # 各 group verb 计数

Reflector L7 LLM-propose 仍待做 (β.5+ 后续轨道).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(ROOT, 'memory_pool', 'promise_soft_vocab.json')

VALID_GROUPS = ('en_soft_verbs', 'zh_soft_verbs')


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
    print(f'\n=== Promise Soft Vocab ({VOCAB_PATH}) ===\n')
    print(f'  version : {vocab.get("version", "?")}')
    print(f'  created : {vocab.get("created_at", "?")}\n')
    groups = vocab.get('groups', {})
    for g in VALID_GROUPS:
        gd = groups.get(g, {})
        verbs = gd.get('verbs', [])
        desc = gd.get('description', '')
        print(f'  {g:<18} ({len(verbs):>2} verbs)  {desc}')
    print()


def cmd_show(vocab: dict, group: str) -> None:
    if group not in VALID_GROUPS:
        print(f'❌ unknown group: {group}')
        print(f'   valid: {", ".join(VALID_GROUPS)}')
        sys.exit(1)
    groups = vocab.get('groups', {})
    gd = groups.get(group, {})
    verbs = gd.get('verbs', [])
    desc = gd.get('description', '')
    print(f'\n{group} ({len(verbs)} verbs): {desc}')
    for i, v in enumerate(verbs, 1):
        print(f'  {i:>2}. {v}')
    print()


def cmd_counts(vocab: dict) -> None:
    print('\n=== verb counts ===')
    groups = vocab.get('groups', {})
    for g in VALID_GROUPS:
        verbs = groups.get(g, {}).get('verbs', [])
        print(f'  {g:<18} {len(verbs)}')
    print()


def cmd_add(vocab: dict, key_val: str) -> None:
    if '=' not in key_val:
        print('❌ --add 需 GROUP=VERB 格式')
        sys.exit(1)
    group, verb = key_val.split('=', 1)
    group = group.strip()
    verb = verb.strip()
    if group not in VALID_GROUPS:
        print(f'❌ unknown group: {group}')
        sys.exit(1)
    groups = vocab.setdefault('groups', {})
    gd = groups.setdefault(group, {'description': '', 'verbs': []})
    verbs = gd.setdefault('verbs', [])
    if verb in verbs:
        print(f'⚠️ verb 已存在于 {group}')
        return
    verbs.append(verb)
    # history 追加
    history = vocab.setdefault('history', [])
    import datetime as _dt
    history.append({
        'ts': _dt.datetime.now().isoformat(timespec='seconds'),
        'marker': 'CLI',
        'action': 'add',
        'group': group,
        'verb': verb,
    })
    _save_vocab(vocab)
    print(f'✅ {group}: 新增 verb {verb!r} (now {len(verbs)} verbs)')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Promise Soft Vocab CLI (β.5.19-C)')
    parser.add_argument('--show', metavar='GROUP', help='看某 group 全部 verbs')
    parser.add_argument('--add', metavar='GROUP=VERB', help='加 verb')
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
