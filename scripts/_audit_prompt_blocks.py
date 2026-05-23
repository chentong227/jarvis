# -*- coding: utf-8 -*-
"""[Audit / 2026-05-21 09:25] 扫 jarvis_central_nerve._assemble_prompt 注入的 block.

输出每个 [BLOCK NAME] 出现位置, 帮 audit 找重复或错位 block.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main():
    target = Path(__file__).parent.parent / 'jarvis_central_nerve.py'
    lines = target.read_text(encoding='utf-8').splitlines()

    block_pat = re.compile(r'\[\s*([A-Z][A-Z _/\-]{2,})\s*\]')
    blocks_by_name = defaultdict(list)
    for i, line in enumerate(lines, 1):
        # 只看 1393-2900 范围 (在 _assemble_prompt 内)
        if 1393 <= i <= 2900:
            stripped = line.strip()
            # 只记 string-literal 出现的 block name (不算 comment)
            if stripped.startswith('#') or stripped.startswith('//'):
                continue
            for m in block_pat.finditer(line):
                name = m.group(1)
                # 排除明显的非 block (e.g. ATTENTION RIGHT NOW 子句, code path)
                if len(name) >= 4 and name.replace(' ', '').replace('_', '').replace('-', '').replace('/', '').isalpha():
                    blocks_by_name[name].append(i)

    print(f"=== Prompt blocks in _assemble_prompt (line 1393-2900) ===\n")
    for name, lns in sorted(blocks_by_name.items(), key=lambda x: x[1][0]):
        marker = '  '
        if len(lns) > 1:
            marker = '⚠️ '  # 多次出现 — 可能多处 inject 或 string-fragment
        print(f"{marker}L{lns[0]:5d}  ({len(lns)}x)  [{name}]")

    print(f"\n--- 总 block 名: {len(blocks_by_name)} ---")
    dupes = {n: l for n, l in blocks_by_name.items() if len(l) > 1}
    if dupes:
        print(f"\n⚠️ 重复 block name (≥ 2 次):\n")
        for name, lns in sorted(dupes.items(), key=lambda x: -len(x[1])):
            print(f"  {len(lns):2d}x  [{name}]   at lines {lns}")


if __name__ == '__main__':
    main()
