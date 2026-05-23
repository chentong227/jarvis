# -*- coding: utf-8 -*-
"""[P5-fix69 / 2026-05-23 16:55] Phase 4 prompt size audit 离线工具.

Sir 16:52 战略: '需要我提供数据请告诉我, 给我测试的方案, 我现在给你跑数据'.

工具读取最近 log file, 提取 PromptBuilder/STANDARD audit lines, 统计:
- 平均 / 最大 / 最小 mega block size
- 平均 audit_sections_total
- top3 section 出现频率 (哪个 section 经常上榜)
- Phase 4 砍建议 (基于经验阈值: STANDARD < 10K = OK, > 15K = 需瘦身)

用法:
    python scripts/prompt_size_audit.py                 # 默认最近 1 log file
    python scripts/prompt_size_audit.py --last 5        # 最近 5 个 log file
    python scripts/prompt_size_audit.py --file <path>   # 指定 log
    python scripts/prompt_size_audit.py --all-tiers     # 含 SHORT_CHAT/FACTUAL_RECALL/...
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

# Force UTF-8 stdout (避免 Windows GBK encoding error with emoji)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).parent.parent.resolve()
LOG_DIR = ROOT / 'docs' / 'runtime_logs'

# Pattern matches:
# 📐 [PromptBuilder/STANDARD] legacy_mega=15234 chars | audit_sections_total=14502 | top3: state_section=8910, ...
PATTERN = re.compile(
    r'\[PromptBuilder/(\w+)\]\s+'
    r'legacy_mega=(\d+)\s+chars\s+\|\s+'
    r'audit_sections_total=(\d+)\s+\|\s+'
    r'top3:\s+(.+?)(?:\n|$)'
)


def parse_log(path: Path) -> list:
    """Parse 1 log file, return list of dict: tier/mega/sections_total/top3."""
    records = []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                m = PATTERN.search(line)
                if m:
                    tier = m.group(1)
                    mega = int(m.group(2))
                    sections_total = int(m.group(3))
                    top3_str = m.group(4).strip()
                    # top3 format: 'state_section=8910, recent_section=2103, ...'
                    top3 = []
                    for part in top3_str.split(','):
                        part = part.strip()
                        if '=' in part:
                            name, _, val = part.partition('=')
                            try:
                                top3.append((name.strip(), int(val.strip())))
                            except ValueError:
                                pass
                    records.append({
                        'tier': tier,
                        'mega_chars': mega,
                        'sections_total': sections_total,
                        'top3': top3,
                    })
    except Exception as e:
        print(f"  ⚠️ failed to parse {path}: {e}", file=sys.stderr)
    return records


def find_recent_logs(n: int) -> list:
    """Return n most recent log files (by mtime)."""
    if not LOG_DIR.exists():
        return []
    logs = sorted(LOG_DIR.glob('jarvis_*.log'),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[:n]


def format_recommendation(stats: dict) -> str:
    """Generate Phase 4 砍建议."""
    lines = []
    lines.append('\n# 📋 Phase 4 砍建议')
    lines.append('─' * 60)
    avg_mega = stats.get('avg_mega', 0)
    max_mega = stats.get('max_mega', 0)

    # 基于经验阈值判断
    if avg_mega == 0:
        lines.append('  ⚠️ 无数据 — 请 Sir 先跑测试 (5 turn 方案)')
        return '\n'.join(lines)

    if avg_mega < 8000:
        lines.append(f'  ✅ 平均 {avg_mega} chars — 体积合理, Phase 4 优先级低')
    elif avg_mega < 12000:
        lines.append(f'  🟡 平均 {avg_mega} chars — 中等, 可选优化')
    else:
        lines.append(f'  🔴 平均 {avg_mega} chars — 偏大, **必须 Phase 4 瘦身**')

    if max_mega > 18000:
        lines.append(f'  🚨 最大 {max_mega} chars — 极端 case 超大, 检查异常 turn')

    lines.append('')
    lines.append('  Top 经常上榜 section (出现频率 + 平均 size):')
    top_freq = stats.get('top_section_freq', {})
    top_avg = stats.get('top_section_avg', {})
    sorted_freq = sorted(top_freq.items(), key=lambda x: -x[1])
    for name, freq in sorted_freq[:5]:
        avg = top_avg.get(name, 0)
        rec = ''
        if avg > 3000:
            rec = '  → 候选砍 (avg > 3K)'
        elif avg > 1500:
            rec = '  → 候选 max_chars (1500)'
        lines.append(f'    {name:30s}  freq={freq:3d}  avg={avg:5d} chars {rec}')

    lines.append('')
    lines.append('  建议优先级 (准则 8 优雅 + 准则 6 主脑端):')
    lines.append('    1. 对 top section 设 BlockSpec.max_chars 限 (≤ 1500/2000)')
    lines.append('    2. 按 tier 砍冷门 block (e.g. STANDARD 保留, SHORT_CHAT 删)')
    lines.append('    3. 极端大 section (> 3K avg) 抽取必要 sub-block')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Phase 4 prompt size audit')
    parser.add_argument('--last', type=int, default=1,
                          help='analyze last N log files (default 1)')
    parser.add_argument('--file', type=str, default='',
                          help='analyze specific log file path')
    parser.add_argument('--all-tiers', action='store_true',
                          help='show all tiers (not just STANDARD)')
    args = parser.parse_args()

    # collect log files
    if args.file:
        log_files = [Path(args.file)]
    else:
        log_files = find_recent_logs(args.last)

    if not log_files:
        print('❌ No log files found.', file=sys.stderr)
        sys.exit(1)

    print(f'📁 Analyzing {len(log_files)} log file(s):')
    for lf in log_files:
        print(f'   - {lf.name}')

    # parse
    all_records = []
    for lf in log_files:
        recs = parse_log(lf)
        all_records.extend(recs)

    if not all_records:
        print('\n⚠️ No PromptBuilder audit lines found in logs.')
        print('   Sir 需要重启 Jarvis + 跑触发 STANDARD tier 的对话 (复杂多维问题).')
        print('   测试方案: 5 turn 覆盖各 tier (见 scripts/prompt_size_audit.py docstring).')
        sys.exit(0)

    print(f'\n📊 Total audit records: {len(all_records)}')

    # group by tier
    by_tier = defaultdict(list)
    for r in all_records:
        by_tier[r['tier']].append(r)

    target_tiers = list(by_tier.keys()) if args.all_tiers else ['STANDARD']

    for tier in target_tiers:
        if tier not in by_tier:
            continue
        recs = by_tier[tier]
        if not recs:
            continue
        mega_list = [r['mega_chars'] for r in recs]
        section_total_list = [r['sections_total'] for r in recs]

        print(f'\n# Tier = {tier}')
        print('─' * 60)
        print(f'  Records:        {len(recs)}')
        print(f'  mega_chars:     avg={int(mean(mega_list)):5d}  '
              f'median={int(median(mega_list)):5d}  '
              f'min={min(mega_list):5d}  max={max(mega_list):5d}')
        print(f'  sections_total: avg={int(mean(section_total_list)):5d}  '
              f'median={int(median(section_total_list)):5d}')

        # top sections analysis
        section_freq = Counter()
        section_sizes = defaultdict(list)
        for r in recs:
            for name, size in r.get('top3', []):
                section_freq[name] += 1
                section_sizes[name].append(size)
        section_avg = {name: int(mean(sizes))
                       for name, sizes in section_sizes.items()}

        if tier == 'STANDARD':
            stats = {
                'avg_mega': int(mean(mega_list)),
                'max_mega': max(mega_list),
                'top_section_freq': dict(section_freq),
                'top_section_avg': section_avg,
            }
            print(format_recommendation(stats))

    print('\n' + '═' * 60)
    print('  用法回顾:')
    print('    python scripts/prompt_size_audit.py --last 5')
    print('    python scripts/prompt_size_audit.py --file <path>')
    print('    python scripts/prompt_size_audit.py --all-tiers')


if __name__ == '__main__':
    main()
