# -*- coding: utf-8 -*-
"""[β.6 Phase 1d 收口 / 2026-05-28] 思考脑发声 vocab CLI 工具.

Sir 准则 6 vocab CLI 范式 (类比 scripts/gate_mode_dump.py):
  - Sir 不改源码 + git commit 就能调思考脑发声策略
  - 即时生效 (daemon 每 30s mtime check, 改完 30s 内热重载)

用法:
  python scripts/thinking_brain_speak_dump.py                      # 全 dump
  python scripts/thinking_brain_speak_dump.py --show-styles        # 看 styles 表
  python scripts/thinking_brain_speak_dump.py --show-rate-cap      # 看 rate cap

  # 加 style (准则 6: 加 style 改 JSON 即可, .py 不动, prompt 也自动同步)
  python scripts/thinking_brain_speak_dump.py --add-style \
      whisper="quiet 1-line subtitle, no pulse" --default-if-invalid=false

  # 删 style
  python scripts/thinking_brain_speak_dump.py --remove-style whisper

  # 改 default fallback style (should_speak=yes 但 LLM 没指定 / 非法时)
  python scripts/thinking_brain_speak_dump.py --set-default silent_text

  # 调 rate cap (smoothing 物理保底, 防 LLM 短时连发 yes 噪音 Sir)
  python scripts/thinking_brain_speak_dump.py --set-rate-cap 300:3
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB_PATH = os.path.join(
    ROOT, 'memory_pool', 'thinking_brain_speak_config.json'
)


def _load_vocab() -> dict:
    if not os.path.exists(VOCAB_PATH):
        print(f'X vocab not found: {VOCAB_PATH}')
        sys.exit(1)
    with open(VOCAB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_vocab(vocab: dict, action: str, change: str) -> None:
    meta = vocab.setdefault('_meta', {})
    meta['updated_at'] = _dt.datetime.now().isoformat(timespec='seconds')
    history = vocab.setdefault('history', [])
    history.append({
        'ts': meta['updated_at'],
        'by': 'scripts/thinking_brain_speak_dump.py',
        'action': action,
        'change': change,
    })
    tmp = VOCAB_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VOCAB_PATH)


def _styles_v2(vocab: dict) -> list:
    """返 styles array (v2). 若 vocab 是 v1 自动转 v2 (内存里, 不写盘)."""
    if isinstance(vocab.get('styles'), list):
        return vocab['styles']
    # v1 → v2 内存适配
    out = []
    vs = (vocab.get('valid_styles') or {}).get('values') or []
    default_name = ((vocab.get('default_style_if_invalid') or {})
                    .get('value') or '').lower()
    for v in vs:
        n = str(v).lower()
        out.append({'name': n, 'description': '',
                    'default_if_invalid': (n == default_name)})
    return out


def cmd_list(vocab: dict) -> None:
    print(f'\n=== Thinking-Brain Speak Vocab ({VOCAB_PATH}) ===\n')
    meta = vocab.get('_meta', {})
    print(f'  schema_version: {meta.get("schema_version", "?")}')
    print(f'  updated_at:     {meta.get("updated_at", "?")}\n')

    print('--- Styles (SPEAK_STYLE enum + prompt-injected description) ---')
    for s in _styles_v2(vocab):
        name = s.get('name', '?')
        desc = s.get('description', '') or '(no description)'
        is_def = s.get('default_if_invalid')
        marker = '[D]' if is_def else '   '
        print(f'  {marker} {name:<14} {desc}')
    print()

    rc = vocab.get('rate_cap') or {}
    print('--- Rate Cap (Python smoothing 物理保底) ---')
    print(f'  window_s:          {rc.get("window_s", "?")}')
    print(f'  max_yes_in_window: {rc.get("max_yes_in_window", "?")}')
    print()


def cmd_show_styles(vocab: dict) -> None:
    print('\n--- Styles ---')
    for s in _styles_v2(vocab):
        name = s.get('name', '?')
        desc = s.get('description', '')
        is_def = s.get('default_if_invalid')
        marker = '*default*' if is_def else ''
        print(f'  {name:<14} {marker:<10} {desc}')
    print()


def cmd_show_rate_cap(vocab: dict) -> None:
    rc = vocab.get('rate_cap') or {}
    print(f'\nwindow_s = {rc.get("window_s")}')
    print(f'max_yes_in_window = {rc.get("max_yes_in_window")}')
    print('(每 window_s 秒内 LLM should_speak=yes 已 >= max_yes_in_window 个 '
          '→ 后续强 force silent 该 tick, 防抖)\n')


def cmd_add_style(vocab: dict, key_val: str, default_if_invalid: bool) -> None:
    if '=' not in key_val:
        print('X --add-style 需 NAME=DESCRIPTION, 比如 whisper="quiet 1-line"')
        sys.exit(1)
    name, desc = key_val.split('=', 1)
    name = name.strip().lower()
    desc = desc.strip().strip('"').strip("'")
    if not name:
        print('X style name 不可空')
        sys.exit(1)

    # 升级 v1 → v2 持久化 (写盘)
    if 'styles' not in vocab:
        vocab['styles'] = _styles_v2(vocab)
        vocab.pop('valid_styles', None)
        vocab.pop('default_style_if_invalid', None)

    existing = [s for s in vocab['styles'] if s.get('name') == name]
    if existing:
        existing[0]['description'] = desc
        if default_if_invalid:
            for s in vocab['styles']:
                s['default_if_invalid'] = (s.get('name') == name)
        change = f'update style {name} desc -> {desc!r}'
        print(f'OK style {name} updated.')
    else:
        # 若新 style 标 default → 其他 default 都关
        if default_if_invalid:
            for s in vocab['styles']:
                s['default_if_invalid'] = False
        vocab['styles'].append({
            'name': name, 'description': desc,
            'default_if_invalid': default_if_invalid,
        })
        change = f'add style {name} desc={desc!r} default_if_invalid={default_if_invalid}'
        print(f'OK style {name} added.')

    _save_vocab(vocab, 'add-style', change)
    print('   (daemon 30s 内 mtime 重载, prompt SPEAK_STYLE 行自动同步)')


def cmd_remove_style(vocab: dict, name: str) -> None:
    name = name.strip().lower()
    styles = _styles_v2(vocab)
    new_styles = [s for s in styles if s.get('name') != name]
    if len(new_styles) == len(styles):
        print(f'X style {name} not found.')
        sys.exit(1)
    # 升级 v2 持久化
    vocab['styles'] = new_styles
    vocab.pop('valid_styles', None)
    vocab.pop('default_style_if_invalid', None)
    # 若删的是 default → 留 1 个标 default (第 1 个)
    if not any(s.get('default_if_invalid') for s in new_styles) and new_styles:
        new_styles[0]['default_if_invalid'] = True
        print(f'   (default 已自动转给 {new_styles[0]["name"]})')
    _save_vocab(vocab, 'remove-style', f'remove {name}')
    print(f'OK style {name} removed.')


def cmd_set_default(vocab: dict, name: str) -> None:
    name = name.strip().lower()
    styles = _styles_v2(vocab)
    if not any(s.get('name') == name for s in styles):
        print(f'X style {name} not found in styles list.')
        print('   先 --add-style 添加再设为 default.')
        sys.exit(1)
    for s in styles:
        s['default_if_invalid'] = (s.get('name') == name)
    vocab['styles'] = styles
    vocab.pop('valid_styles', None)
    vocab.pop('default_style_if_invalid', None)
    _save_vocab(vocab, 'set-default', f'default -> {name}')
    print(f'OK default style -> {name}')


def cmd_set_rate_cap(vocab: dict, spec: str) -> None:
    if ':' not in spec:
        print('X --set-rate-cap 格式 WINDOW_S:MAX_YES, 比如 300:3')
        sys.exit(1)
    try:
        window_s, max_yes = spec.split(':', 1)
        window_s = int(window_s.strip())
        max_yes = int(max_yes.strip())
    except ValueError:
        print('X WINDOW_S / MAX_YES 必须是整数')
        sys.exit(1)
    rc = vocab.setdefault('rate_cap', {})
    old_w = rc.get('window_s')
    old_m = rc.get('max_yes_in_window')
    rc['window_s'] = window_s
    rc['max_yes_in_window'] = max_yes
    _save_vocab(
        vocab, 'set-rate-cap',
        f'window_s {old_w}->{window_s} max_yes {old_m}->{max_yes}',
    )
    print(f'OK rate cap: window_s={window_s} max_yes_in_window={max_yes}')


def main() -> None:
    p = argparse.ArgumentParser(
        description='Thinking-brain speak vocab CLI (β.6 Phase 1d)'
    )
    p.add_argument('--show-styles', action='store_true', help='show styles 表')
    p.add_argument('--show-rate-cap', action='store_true', help='show rate cap')
    p.add_argument('--add-style', metavar='NAME=DESC',
                   help='add or update a style')
    p.add_argument('--default-if-invalid', metavar='BOOL', default='false',
                   help='for --add-style: 标新 style 为 default fallback (true/false)')
    p.add_argument('--remove-style', metavar='NAME', help='remove a style')
    p.add_argument('--set-default', metavar='NAME', help='切 default fallback style')
    p.add_argument('--set-rate-cap', metavar='WIN:MAX',
                   help='set rate cap, 比如 300:3')

    args = p.parse_args()
    vocab = _load_vocab()

    if args.show_styles:
        cmd_show_styles(vocab)
    elif args.show_rate_cap:
        cmd_show_rate_cap(vocab)
    elif args.add_style:
        flag = str(args.default_if_invalid).strip().lower() in (
            '1', 'true', 'yes', 'y',
        )
        cmd_add_style(vocab, args.add_style, flag)
    elif args.remove_style:
        cmd_remove_style(vocab, args.remove_style)
    elif args.set_default:
        cmd_set_default(vocab, args.set_default)
    elif args.set_rate_cap:
        cmd_set_rate_cap(vocab, args.set_rate_cap)
    else:
        cmd_list(vocab)


if __name__ == '__main__':
    main()
