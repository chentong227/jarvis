# -*- coding: utf-8 -*-
"""
proactive_care_dump.py — ProactiveCareEngine 数据观察工具

用途: dry-run 期间 (env JARVIS_PROACTIVE_CARE_LIVE 未设) Jarvis 不真发声但所有
"本想 nudge" 决定 / sensor signal / cooldown 拒绝原因都 bg_log 留痕. 此脚本扫
docs/runtime_logs/latest.log 把这些事件整理成可读报告.

用法:
    python scripts/proactive_care_dump.py            # 最近 24h
    python scripts/proactive_care_dump.py --days 3   # 最近 3 天
    python scripts/proactive_care_dump.py --tail 20  # 仅最后 20 条
"""

import argparse
import collections
import io
import os
import re
import sys
import time
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def find_latest_log() -> str:
    latest_pointer = os.path.join(ROOT, 'docs', 'runtime_logs', 'latest.txt')
    if os.path.exists(latest_pointer):
        try:
            with open(latest_pointer, 'r', encoding='utf-8', errors='ignore') as f:
                path = f.read().strip()
                if os.path.isabs(path) and os.path.exists(path):
                    return path
                cand = os.path.join(ROOT, path)
                if os.path.exists(cand):
                    return cand
        except Exception:
            pass
    log_dir = os.path.join(ROOT, 'docs', 'runtime_logs')
    if not os.path.isdir(log_dir):
        return ''
    candidates = []
    for f in os.listdir(log_dir):
        if f.startswith('jarvis_') and f.endswith('.log'):
            full = os.path.join(log_dir, f)
            candidates.append((os.path.getmtime(full), full))
    if not candidates:
        return ''
    candidates.sort(reverse=True)
    return candidates[0][1]


PAT_WOULD = re.compile(r'\[ProactiveCare/DRY\].*concern=(\S+).*urgency=([0-9.]+)')
PAT_LIVE = re.compile(r'\[ProactiveCare/LIVE\].*concern=(\S+).*urgency=([0-9.]+)')
PAT_SKIP = re.compile(r'\[ProactiveCare\] skip concern=(\S+).*urgency=([0-9.]+).*reason=(.+)$')
PAT_SENSOR = re.compile(r'\[ProactiveCare/Sensor\].*fed (\d+) signal')
PAT_HEALTH = re.compile(r'\[ProactiveCare/Health\].*tick=(\d+).*actives=(\d+).*top3=\[(.*)\] dry_run=(\w+)')
PAT_REJECT = re.compile(r'\[ProactiveCare\].*Sir.*?显式拒绝')
PAT_FATIGUE = re.compile(r'\[ProactiveCare\].*concern=(\S+).*fatigue=(\d+)')


def parse_log(path: str, since_ts: float) -> dict:
    counts = {
        'would_nudge': collections.Counter(),
        'live_nudge': collections.Counter(),
        'skip_reason': collections.Counter(),
        'sensor_signals': 0,
        'health_ticks': 0,
        'last_top3': '',
        'last_dry_run': '',
        'fatigue_events': collections.Counter(),
        'explicit_reject_count': 0,
        'would_examples': [],
        'skip_examples': [],
        'live_examples': [],
    }
    if not path or not os.path.exists(path):
        return counts
    try:
        mtime = os.path.getmtime(path)
        if mtime < since_ts:
            return counts
    except Exception:
        pass

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = PAT_WOULD.search(line)
            if m:
                cid = m.group(1)
                counts['would_nudge'][cid] += 1
                if len(counts['would_examples']) < 8:
                    counts['would_examples'].append(line.strip())
                continue
            m = PAT_LIVE.search(line)
            if m:
                cid = m.group(1)
                counts['live_nudge'][cid] += 1
                if len(counts['live_examples']) < 8:
                    counts['live_examples'].append(line.strip())
                continue
            m = PAT_SKIP.search(line)
            if m:
                reason = m.group(3).split('(')[0].strip()
                counts['skip_reason'][reason] += 1
                if len(counts['skip_examples']) < 8:
                    counts['skip_examples'].append(line.strip())
                continue
            m = PAT_SENSOR.search(line)
            if m:
                counts['sensor_signals'] += int(m.group(1))
                continue
            m = PAT_HEALTH.search(line)
            if m:
                counts['health_ticks'] += 1
                counts['last_top3'] = m.group(3)
                counts['last_dry_run'] = m.group(4)
                continue
            if PAT_REJECT.search(line):
                counts['explicit_reject_count'] += 1
                continue
            m = PAT_FATIGUE.search(line)
            if m:
                counts['fatigue_events'][m.group(1)] += 1
                continue
    return counts


def render(counts: dict) -> str:
    lines: List[str] = []
    lines.append("=" * 64)
    lines.append("ProactiveCareEngine — 观察报告")
    lines.append("=" * 64)
    lines.append(f"扫描时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"模式 (last_seen): dry_run={counts['last_dry_run'] or '?'}")
    lines.append(f"Health tick 总数: {counts['health_ticks']}")
    lines.append(f"最近 top3 concerns (urgency): {counts['last_top3'] or '(none)'}")
    lines.append(f"Sensor 总 signal 注入次数: {counts['sensor_signals']}")
    lines.append(f"Sir 显式拒绝事件: {counts['explicit_reject_count']}")
    lines.append("")
    lines.append("--- Would-Nudge (dry-run) per concern ---")
    if counts['would_nudge']:
        for cid, n in counts['would_nudge'].most_common():
            lines.append(f"  {cid:32s}  {n} 次")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("--- Live-Nudge per concern (实际出声) ---")
    if counts['live_nudge']:
        for cid, n in counts['live_nudge'].most_common():
            lines.append(f"  {cid:32s}  {n} 次")
    else:
        lines.append("  (none — 仍在 dry-run 或无触发)")
    lines.append("")
    lines.append("--- Skip reasons ---")
    if counts['skip_reason']:
        for r, n in counts['skip_reason'].most_common():
            lines.append(f"  {r:32s}  {n} 次")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("--- Fatigue (Sir miss/reject 累计) ---")
    if counts['fatigue_events']:
        for cid, n in counts['fatigue_events'].most_common():
            lines.append(f"  {cid:32s}  {n} 次 fatigue 事件")
    else:
        lines.append("  (none)")
    if counts['would_examples']:
        lines.append("")
        lines.append("--- 最近 would-nudge 示例 ---")
        for ex in counts['would_examples'][-5:]:
            lines.append(f"  {ex[-180:]}")
    if counts['live_examples']:
        lines.append("")
        lines.append("--- 最近 live-nudge 示例 ---")
        for ex in counts['live_examples'][-5:]:
            lines.append(f"  {ex[-180:]}")
    lines.append("=" * 64)
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=1, help='扫最近多少天 (默认 1)')
    ap.add_argument('--log', type=str, default='', help='指定 log 路径')
    args = ap.parse_args()

    path = args.log or find_latest_log()
    if not path:
        print("找不到 log 文件. 试指定 --log <path>")
        sys.exit(1)
    print(f"扫 log: {path}")
    since = time.time() - args.days * 86400
    counts = parse_log(path, since)
    print(render(counts))


if __name__ == '__main__':
    main()
