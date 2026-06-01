#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[P5-fix27-B/C/D / 2026-05-22] 通用 simple-list vocab CLI

跟 concerns_dump.py / behavior_vocab_dump.py 风格对齐 (准则 6.5: CLI 可改).

适用于 schema = {'<group>': [phrase1, phrase2, ...], '<group2>': [...]} 的
简单 list-of-strings vocab. 集中管理 3 个 vocab (后续可加):

    promise_completion   — memory_pool/promise_completion_vocab.json
                            groups: fulfilled / cancelled
    stand_down_trigger   — memory_pool/stand_down_trigger_vocab.json
                            groups: enter / exit
    concern_dismiss      — memory_pool/concern_dismiss_vocab.json
                            groups: dismiss

Usage:
    # 列出 3 个 vocab 总览
    python scripts/simple_vocab_dump.py

    # 看一个 vocab 全部 phrase
    python scripts/simple_vocab_dump.py --vocab promise_completion

    # 加 phrase (group=fulfilled)
    python scripts/simple_vocab_dump.py --vocab promise_completion \\
        --add fulfilled "酒席结束了"

    # 删 phrase
    python scripts/simple_vocab_dump.py --vocab promise_completion \\
        --remove fulfilled "酒席结束了"

    # 看 seed (内置默认, json 不存在时返这个)
    python scripts/simple_vocab_dump.py --vocab stand_down_trigger --seed
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ============================================================
# Vocab registry — 加新 vocab 在这里登记一次, CLI 自动支持
# ============================================================
def _setup_path():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)


_setup_path()


def _get_promise_completion_seed():
    from jarvis_directives import _SEED_PROMISE_COMPLETION_PATTERNS
    return _SEED_PROMISE_COMPLETION_PATTERNS


def _get_stand_down_seed():
    from jarvis_directives import _SEED_STAND_DOWN_PATTERNS
    return _SEED_STAND_DOWN_PATTERNS


def _get_concern_dismiss_seed():
    from jarvis_directives import _SEED_CONCERN_DISMISS_PATTERNS
    # concern_dismiss is flat list (not dict-of-groups). 包成 {'dismiss': [...]}
    # 保持 CLI 一致接口.
    if isinstance(_SEED_CONCERN_DISMISS_PATTERNS, dict):
        return _SEED_CONCERN_DISMISS_PATTERNS
    return {'dismiss': list(_SEED_CONCERN_DISMISS_PATTERNS)}


VOCABS = {
    'promise_completion': {
        'path': os.path.join(ROOT, 'memory_pool', 'promise_completion_vocab.json'),
        'directive': 'promise_completion_judge',
        'desc': "Sir 说'X 做完了/不用了' → 主脑 emit promises.fulfill/cancel",
        'seed_fn': _get_promise_completion_seed,
        'groups': ('fulfilled', 'cancelled'),
        # disk schema: {group: [phrases]} (直)
        'schema': 'group_list',
    },
    'stand_down_trigger': {
        'path': os.path.join(ROOT, 'memory_pool', 'stand_down_trigger_vocab.json'),
        'directive': 'stand_down_judge',
        'desc': "Sir 说'我接电话/Jarvis回来' → 主脑 emit stand_down.set/clear",
        'seed_fn': _get_stand_down_seed,
        'groups': ('enter', 'exit'),
        'schema': 'group_list',
    },
    'concern_dismiss': {
        'path': os.path.join(ROOT, 'memory_pool', 'concern_dismiss_vocab.json'),
        'directive': 'concern_dismissal_judge',
        'desc': "Sir 说'X 别管了' → 主脑 emit concerns.dismiss",
        'seed_fn': _get_concern_dismiss_seed,
        'groups': ('dismiss',),
        # disk schema: {'patterns': [phrases]} (flat — 老格式)
        'schema': 'flat_patterns',
    },
}


# ============================================================
# IO
# ============================================================
def _load(path: str, schema: str = 'group_list') -> dict:
    """Load vocab → internal {group: [phrases]} schema.

    Args:
      path:   json file
      schema: 'group_list' = native {group: [phrases]}
              'flat_patterns' = {'patterns': [phrases]} → wrap as {'dismiss': [...]}
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            if isinstance(data, list):
                return {'dismiss': data}
            return {}
        if schema == 'flat_patterns':
            # disk: {'patterns': [...], '_meta': ...}
            patterns = data.get('patterns', [])
            if isinstance(patterns, list):
                return {'dismiss': patterns}
            return {}
        # group_list — 直接返 (剔除 _meta)
        return {k: v for k, v in data.items()
                  if not k.startswith('_') and isinstance(v, list)}
    except Exception as e:
        print(f"❌ 读 {path} 失败: {e}")
        sys.exit(1)


def _save(path: str, groups: dict, schema: str = 'group_list') -> None:
    """Save internal {group: [phrases]} → disk format per schema."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if schema == 'flat_patterns':
        # disk: {'patterns': [...], '_meta': ...}
        out = {
            '_meta': {
                'schema_version': 1,
                'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            },
            'patterns': list(groups.get('dismiss', [])),
        }
    else:
        out = {k: list(v) for k, v in groups.items() if not k.startswith('_')}
        out['_meta'] = {
            'schema_version': 1,
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)


def _resolve_vocab(name: str) -> dict:
    if name not in VOCABS:
        print(f"❌ 未知 vocab {name!r}. 可用: {list(VOCABS.keys())}")
        sys.exit(1)
    return VOCABS[name]


def _merge_groups(seed: dict, disk: dict) -> dict:
    """合并 seed + disk. disk 优先 (Sir 编辑过的留下), seed 兜底."""
    merged = {}
    for grp in seed:
        merged[grp] = list(disk.get(grp, seed.get(grp, [])))
    # disk 可能有 seed 没的 group (Sir 加的 custom)
    for grp in disk:
        if grp.startswith('_'):
            continue
        if grp not in merged:
            merged[grp] = list(disk[grp])
    return merged


# ============================================================
# Commands
# ============================================================
def cmd_overview() -> int:
    print("📚 Simple-list vocab 总览 (准则 6.5: 持久化 + CLI 可改)")
    print("=" * 78)
    for name, cfg in VOCABS.items():
        disk = _load(cfg['path'])
        seed = cfg['seed_fn']()
        merged = _merge_groups(seed, disk)
        total = sum(len(v) for v in merged.values())
        json_exists = '📂' if os.path.exists(cfg['path']) else '⚪(seed)'
        print(f"\n{json_exists} {name} ({total} phrases) → directive={cfg['directive']!r}")
        print(f"   {cfg['desc']}")
        print(f"   path  = {os.path.relpath(cfg['path'], ROOT)}")
        for grp, phrases in merged.items():
            sample = ', '.join(phrases[:5])
            print(f"   [{grp:<10}] {len(phrases):3} phrases | {sample}"
                    + (' ...' if len(phrases) > 5 else ''))
    print()
    print("详情: python scripts/simple_vocab_dump.py --vocab <name>")
    print("加词: python scripts/simple_vocab_dump.py --vocab <name> "
            "--add <group> <phrase>")
    return 0


def cmd_show(cfg: dict, name: str, show_seed: bool = False) -> int:
    disk = _load(cfg['path'])
    seed = cfg['seed_fn']()
    if show_seed:
        print(f"🌱 {name} SEED (内置默认, .py 里 hardcoded):")
        for grp in cfg['groups']:
            phrases = seed.get(grp, [])
            print(f"\n  [{grp}] ({len(phrases)} phrases)")
            for ph in phrases:
                print(f"    • {ph}")
        return 0
    merged = _merge_groups(seed, disk)
    print(f"📚 {name} → directive={cfg['directive']!r}")
    print(f"   path = {os.path.relpath(cfg['path'], ROOT)} "
            f"({'exists' if os.path.exists(cfg['path']) else 'NOT exists, using seed'})")
    print(f"   desc = {cfg['desc']}")
    print("=" * 78)
    for grp, phrases in merged.items():
        if grp.startswith('_'):
            continue
        print(f"\n  [{grp}] ({len(phrases)} phrases)")
        for ph in phrases:
            from_seed = ph in seed.get(grp, [])
            mark = '🌱' if from_seed else '🆕'
            print(f"    {mark} {ph}")
    return 0


def cmd_add(cfg: dict, name: str, group: str, phrase: str) -> int:
    phrase = (phrase or '').strip()
    if not phrase:
        print("❌ phrase 不能为空")
        return 1
    if group not in cfg['groups']:
        # warn 但允许 — Sir 可能想加新 group
        print(f"⚠️ '{group}' 不在标准 groups {cfg['groups']}, 仍 OK 但 directive "
                f"可能不识别. 标准 group 才被 _trigger_* 读.")
    disk = _load(cfg['path'])
    seed = cfg['seed_fn']()
    merged = _merge_groups(seed, disk)
    current = list(merged.get(group, []))
    if phrase.lower() in [p.lower() for p in current]:
        print(f"ℹ️ '{phrase}' 已在 [{group}], 无需加.")
        return 0
    current.append(phrase)
    merged[group] = current
    # 写 disk: 只持久化非 seed (合并 ok 也可全写, 简单点全写)
    disk_save = {k: v for k, v in merged.items() if not k.startswith('_')}
    _save(cfg['path'], disk_save)
    print(f"✅ 加入 [{group}]: '{phrase}'  (now {len(current)} phrases)")
    return 0


def cmd_remove(cfg: dict, name: str, group: str, phrase: str) -> int:
    phrase = (phrase or '').strip()
    if not phrase:
        print("❌ phrase 不能为空")
        return 1
    disk = _load(cfg['path'])
    seed = cfg['seed_fn']()
    merged = _merge_groups(seed, disk)
    current = list(merged.get(group, []))
    new_list = [p for p in current if p.lower() != phrase.lower()]
    if len(new_list) == len(current):
        print(f"ℹ️ '{phrase}' 不在 [{group}], 无需删")
        return 0
    merged[group] = new_list
    disk_save = {k: v for k, v in merged.items() if not k.startswith('_')}
    _save(cfg['path'], disk_save)
    note = ''
    if phrase.lower() in [p.lower() for p in seed.get(group, [])]:
        note = ' (来自 seed; 删了但下次 vocab 重 init 仍会有 seed — 该删 seed 在 .py)'
    print(f"🗑️ 删除 [{group}]: '{phrase}'  (now {len(new_list)} phrases){note}")
    return 0


# ============================================================
# main
# ============================================================
def main():
    ap = argparse.ArgumentParser(
        description='[P5-fix27 B/C/D] 通用 simple-list vocab CLI '
                       '(promise_completion / stand_down_trigger / concern_dismiss)')
    ap.add_argument('--vocab', '-v', choices=list(VOCABS.keys()),
                       help='target vocab name (空 → 显示所有 vocab 总览)')
    ap.add_argument('--seed', action='store_true',
                       help='show seed (.py 内置默认), 而非 disk merged')
    ap.add_argument('--add', nargs=2, metavar=('GROUP', 'PHRASE'),
                       help='加 phrase 到指定 group')
    ap.add_argument('--remove', nargs=2, metavar=('GROUP', 'PHRASE'),
                       help='删 phrase 从指定 group')
    args = ap.parse_args()

    if not args.vocab:
        return cmd_overview()

    cfg = _resolve_vocab(args.vocab)

    if args.add:
        return cmd_add(cfg, args.vocab, args.add[0], args.add[1])
    if args.remove:
        return cmd_remove(cfg, args.vocab, args.remove[0], args.remove[1])

    return cmd_show(cfg, args.vocab, show_seed=args.seed)


if __name__ == '__main__':
    sys.exit(main() or 0)
