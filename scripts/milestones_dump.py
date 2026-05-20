# -*- coding: utf-8 -*-
"""[β.5.45 / 2026-05-20] Sir Lifetime Milestones CLI Dump

让 Sir 一行命令查看 / 加 / pin / 删 自己的 lifetime milestone anchors.
NOT commitments. NOT to be weaponized.

用法:
    python scripts/milestones_dump.py                       # list 所有
    python scripts/milestones_dump.py --stats               # 统计
    python scripts/milestones_dump.py --show <id>           # 看单条
    python scripts/milestones_dump.py --add                 # 交互式添加
    python scripts/milestones_dump.py --pin <id>            # 标 pinned
    python scripts/milestones_dump.py --unpin <id>          # 取消 pinned
    python scripts/milestones_dump.py --delete <id>         # 删 (confirm)
    python scripts/milestones_dump.py --json                # 机读 JSON
    python scripts/milestones_dump.py --render-prompt       # 看 prompt block 渲染
"""
from __future__ import annotations

import argparse
import json
import os
import sys


if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_milestones import (
    load_milestones, get_milestone, add_milestone,
    pin_milestone, delete_milestone, render_prompt_block, stats,
)


def _short(s: str, n: int = 60) -> str:
    s = (s or '').replace('\n', ' ').strip()
    return s if len(s) <= n else s[:n] + '...'


def cmd_list() -> None:
    ms = load_milestones()
    if not ms:
        print('[milestones] (empty)')
        print('  Tip: add via `--add` or via voice to Jarvis (lifetime anchor instruction)')
        return
    ms_sorted = sorted(ms, key=lambda m: m.get('ts', ''), reverse=True)
    print(f'[milestones] total={len(ms)}')
    print('  ' + '-' * 78)
    for m in ms_sorted:
        mid = m.get('id', '?')
        ts = (m.get('ts') or '')[:16]
        pin_mark = '[PIN]' if m.get('pin') else '     '
        mtype = m.get('type', '?')
        title = m.get('title') or _short(m.get('text', ''), 50)
        print(f'  {pin_mark} {ts}  {mid}  [{mtype}]  {title}')
    print('  ' + '-' * 78)
    print('  Tip: `--show <id>` for full text + jarvis-note')


def cmd_show(milestone_id: str) -> None:
    m = get_milestone(milestone_id)
    if not m:
        print(f'[milestones] NOT FOUND: {milestone_id}')
        sys.exit(2)
    print('=' * 80)
    for k in ('id', 'ts', 'type', 'title', 'speaker', 'language', 'pin',
              'created_by', 'do_not_use_against_sir', 'replay_only_when_sir_asks'):
        print(f'  {k:30s}: {m.get(k)}')
    print(f'  {"tags":30s}: {", ".join(m.get("tags") or [])}')
    print('-' * 80)
    print('text:')
    print(f'  {m.get("text", "")}')
    if m.get('context'):
        print('-' * 80)
        print('context:')
        print(f'  {m.get("context")}')
    if m.get('instruction_for_jarvis'):
        print('-' * 80)
        print('instruction_for_jarvis:')
        print(f'  {m.get("instruction_for_jarvis")}')
    print('=' * 80)


def cmd_add() -> None:
    print('=== Add new milestone (Ctrl+C to abort) ===')
    try:
        text = input('text (required): ').strip()
        if not text:
            print('[abort] text cannot be empty'); sys.exit(2)
        title = input('title (optional): ').strip()
        mtype = input("type [declaration/insight/wish] (declaration): ").strip() or 'declaration'
        speaker = input("speaker [sir/jarvis] (sir): ").strip() or 'sir'
        language = input("language [zh/en/mixed] (zh): ").strip() or 'zh'
        context = input('context (optional): ').strip()
        tags_raw = input('tags (comma-separated, optional): ').strip()
        tags = [t.strip() for t in tags_raw.split(',') if t.strip()] if tags_raw else []
        pin = input('pin? [y/N]: ').strip().lower() in ('y', 'yes')
        instr = input('instruction_for_jarvis (optional): ').strip()
    except (KeyboardInterrupt, EOFError):
        print('\n[abort]'); sys.exit(130)
    entry = {
        'text': text, 'title': title, 'type': mtype, 'speaker': speaker,
        'language': language, 'context': context, 'tags': tags, 'pin': pin,
        'instruction_for_jarvis': instr, 'created_by': 'manual_cli',
    }
    new_id = add_milestone(entry)
    print(f'[ok] added id={new_id}')


def cmd_pin(milestone_id: str, pinned: bool) -> None:
    if not get_milestone(milestone_id):
        print(f'[milestones] NOT FOUND: {milestone_id}'); sys.exit(2)
    pin_milestone(milestone_id, pinned)
    state = 'PINNED' if pinned else 'UNPINNED'
    print(f'[ok] {state} {milestone_id}')


def cmd_delete(milestone_id: str) -> None:
    m = get_milestone(milestone_id)
    if not m:
        print(f'[milestones] NOT FOUND: {milestone_id}'); sys.exit(2)
    print(f'about to DELETE: {m.get("title") or _short(m.get("text", ""), 60)}')
    try:
        if input('type "yes" to confirm: ').strip().lower() != 'yes':
            print('[abort]'); sys.exit(2)
    except (KeyboardInterrupt, EOFError):
        print('\n[abort]'); sys.exit(130)
    delete_milestone(milestone_id)
    print('[ok] deleted')


def main() -> None:
    p = argparse.ArgumentParser(description='Sir lifetime milestones CLI')
    p.add_argument('--show', metavar='ID')
    p.add_argument('--add', action='store_true')
    p.add_argument('--pin', metavar='ID')
    p.add_argument('--unpin', metavar='ID')
    p.add_argument('--delete', metavar='ID')
    p.add_argument('--json', action='store_true')
    p.add_argument('--stats', action='store_true')
    p.add_argument('--render-prompt', action='store_true', dest='render_prompt')
    args = p.parse_args()

    if args.json:
        print(json.dumps(load_milestones(), ensure_ascii=False, indent=2))
    elif args.stats:
        for k, v in stats().items():
            print(f'  {k:15s} = {v}')
    elif args.render_prompt:
        block = render_prompt_block(max_recent=3)
        print(block if block else '[render-prompt] (empty)')
    elif args.show:
        cmd_show(args.show)
    elif args.add:
        cmd_add()
    elif args.pin:
        cmd_pin(args.pin, True)
    elif args.unpin:
        cmd_pin(args.unpin, False)
    elif args.delete:
        cmd_delete(args.delete)
    else:
        cmd_list()


if __name__ == '__main__':
    main()
