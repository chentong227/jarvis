#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[SOUL Phase 5 P1 / Sir 2026-05-29] 动态架构地图 CLI.

动态地图 = Jarvis 认知自己架构的活组件 (非独立文档).
本 CLI 让 Sir/agent inspect + 手动 refresh.

Subcommands:
  refresh     重扫所有 jarvis_*.py → module_map.json + AUTO.md (一键刷新)
  list        列所有模块 (按 layer 分组)
  show <mod>  单模块详情 (职责/vocab/依赖/被依赖)
  orphans     架构治理: orphan / no_docstring / circular / parse_errors
  stats       总览统计
  retrieve <kw>  按 keyword retrieve 相关模块 (P2 self-debug 预览)
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    import _cli_utils  # noqa: F401  # utf-8 stdout
except Exception:
    pass
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def cmd_refresh(_args) -> int:
    from jarvis_module_scanner import refresh, _MODULE_MAP_PATH, _AUTO_MD_PATH
    data = refresh()
    st = data.get('stats', {})
    print(f"✅ refreshed: {st.get('total_modules', 0)} modules")
    print(f"   docstring: {st.get('with_docstring', 0)} | "
          f"orphans: {len(st.get('orphans', []))} | "
          f"no_doc: {len(st.get('no_docstring', []))} | "
          f"circular: {len(st.get('circular_deps', []))}")
    print(f"   → {_MODULE_MAP_PATH}")
    print(f"   → {_AUTO_MD_PATH}")
    return 0


def _load_or_hint():
    from jarvis_module_scanner import load_module_map
    data = load_module_map()
    if data is None:
        print("⚠️  module_map.json 不存在, 先跑: python scripts/module_map_dump.py refresh",
              file=sys.stderr)
        return None
    return data


def cmd_list(_args) -> int:
    data = _load_or_hint()
    if data is None:
        return 1
    layers = {}
    for n, i in data.get('modules', {}).items():
        layers.setdefault(i.get('layer', 'misc'), []).append((n, i))
    for layer in sorted(layers.keys()):
        mods = sorted(layers[layer], key=lambda x: -x[1].get('lines', 0))
        print(f"\n=== {layer} ({len(mods)}) ===")
        for n, i in mods:
            print(f"  {i.get('lines', 0):>5}  {n}  — "
                  f"{(i.get('purpose', '') or '(no doc)')[:55]}")
    return 0


def cmd_show(args) -> int:
    data = _load_or_hint()
    if data is None:
        return 1
    name = args.module
    if not name.startswith('jarvis_'):
        name = 'jarvis_' + name
    info = data.get('modules', {}).get(name)
    if info is None:
        print(f"⚠️  module '{name}' 不在 map", file=sys.stderr)
        return 1
    print(f"📦 {name} ({info.get('lines', 0)} 行) [layer={info.get('layer')}]")
    print(f"   职责: {info.get('purpose', '(无)')}")
    print(f"   classes: {info.get('classes', [])}")
    print(f"   关键 vocab: {info.get('vocab_files', [])}")
    print(f"   关联 doc: {info.get('doc_refs', [])}")
    print(f"   依赖 (含 lazy): {info.get('depends_on', [])}")
    print(f"   依赖 (top-level): {info.get('depends_on_toplevel', [])}")
    print(f"   被依赖: {info.get('depended_by', [])}")
    if 'error' in info:
        print(f"   ⚠️ error: {info['error']}")
    return 0


def cmd_orphans(_args) -> int:
    data = _load_or_hint()
    if data is None:
        return 1
    st = data.get('stats', {})
    print("=== 架构治理 ===")
    if st.get('parse_errors'):
        print(f"⚠️ parse 错误 ({len(st['parse_errors'])}): "
              f"{st['parse_errors']}")
    print(f"\n待补 docstring ({len(st.get('no_docstring', []))}):")
    for m in st.get('no_docstring', []):
        print(f"  - {m}")
    print(f"\norphan 无人 import ({len(st.get('orphans', []))}):")
    for m in st.get('orphans', []):
        print(f"  - {m}")
    print(f"\n循环依赖 top-level ({len(st.get('circular_deps', []))}):")
    for pair in st.get('circular_deps', []):
        print(f"  - {pair[0]} ↔ {pair[1]}")
    return 0


def cmd_stats(_args) -> int:
    data = _load_or_hint()
    if data is None:
        return 1
    meta = data.get('_meta', {})
    st = data.get('stats', {})
    print(f"[module_map] generated {meta.get('generated_at', '?')} "
          f"git {meta.get('git_head', '?')}")
    print(f"  总模块: {st.get('total_modules', 0)}")
    print(f"  有 docstring: {st.get('with_docstring', 0)} "
          f"({st.get('with_docstring', 0) * 100 // max(1, st.get('total_modules', 1))}%)")
    print(f"  orphans: {len(st.get('orphans', []))}")
    print(f"  no_docstring: {len(st.get('no_docstring', []))}")
    print(f"  circular (top-level): {len(st.get('circular_deps', []))}")
    print(f"  parse_errors: {len(st.get('parse_errors', []))}")
    return 0


def cmd_retrieve(args) -> int:
    from jarvis_module_scanner import get_modules_for_keyword
    hits = get_modules_for_keyword(args.keyword)
    if not hits:
        print(f"(no module matched '{args.keyword}')")
        return 0
    print(f"=== retrieve '{args.keyword}' ({len(hits)} hits) ===")
    for h in hits:
        print(f"  {h['name']} ({h.get('lines', 0)} 行) — "
              f"{(h.get('purpose', '') or '')[:50]}")
        print(f"      vocab: {h.get('vocab_files', [])[:3]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='module_map_dump',
        description="动态架构地图 CLI (SOUL Phase 5 P1)",
    )
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('refresh', help='重扫 → module_map.json + AUTO.md')
    sub.add_parser('list', help='列所有模块 (按 layer)')
    p_show = sub.add_parser('show', help='单模块详情')
    p_show.add_argument('module', help='模块名 (jarvis_ 前缀可省)')
    sub.add_parser('orphans', help='架构治理 (orphan/no_doc/circular)')
    sub.add_parser('stats', help='总览统计')
    p_ret = sub.add_parser('retrieve', help='按 keyword retrieve (P2 预览)')
    p_ret.add_argument('keyword')

    args = parser.parse_args()
    return {
        'refresh': cmd_refresh, 'list': cmd_list, 'show': cmd_show,
        'orphans': cmd_orphans, 'stats': cmd_stats, 'retrieve': cmd_retrieve,
    }[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
