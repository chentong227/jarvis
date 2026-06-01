#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
[P0+20-β.2.9.7-γ.2 / 2026-05-18] proactive_care_tail.py — 实时观察 ProactiveCare 决策

类似 tail -f, 实时跟踪 latest.log 输出 ProactiveCare daemon 的:
  - 📡 Sensor 派生 signal (主动发现 concern 该 nudge)
  - 📊 Health tick (每 30 tick = 30min 一次 top3 active concerns)
  - 🛑 Skip (urgency 未过阈 / cooldown / deep_work / sleep_mode 等)
  - 🤝 DRY/LIVE Nudge (要 / 实际 push)
  - 🚫 Sir 显式拒绝
  - ⚖️ InconsistencyWatcher fire
  - 💡 daemon 启动 / 状态

Sir β.2.9.7 LIVE 切换后用此脚本看新 ProactiveCare 是否正常发声 + 没 spam.

用法:
    python scripts/proactive_care_tail.py                    # 默认实时跟踪
    python scripts/proactive_care_tail.py --no-follow        # 一次性 dump 当前 log
    python scripts/proactive_care_tail.py --last 100         # 看最后 100 条
    python scripts/proactive_care_tail.py --log <path>       # 指定 log 文件
    python scripts/proactive_care_tail.py --filter skip      # 只看 skip 事件
                                          (skip/sensor/health/nudge/reject/incon)

按 Ctrl+C 退出 follow 模式.
"""

import argparse
import io
import os
import re
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ============================================================
# 事件 pattern + 友好渲染 (准则 6: 不硬编码具体 concern, 通用 pattern)
# ============================================================

_EVENT_PATTERNS = [
    # (key, color, regex, label)
    ('sensor', '\033[36m',
     re.compile(r'📡\s*\[ProactiveCare/Sensor\]\s*(.+)$'), 'SENSOR'),
    ('health', '\033[37m',
     re.compile(r'📊\s*\[ProactiveCare/Health\]\s*(.+)$'), 'HEALTH'),
    ('skip', '\033[33m',
     re.compile(r'🛑\s*\[ProactiveCare\]\s*skip\s*(.+)$'), 'SKIP  '),
    ('nudge_dry', '\033[35m',
     re.compile(r'🤝\s*\[ProactiveCare/DRY\]\s*(.+)$'), 'DRY   '),
    ('nudge_live', '\033[92m',
     re.compile(r'🤝\s*\[ProactiveCare/LIVE\]\s*(.+)$'), 'LIVE  '),
    ('reject', '\033[91m',
     re.compile(r'🚫\s*\[ProactiveCare\]\s*Sir.*?(显式拒绝.*)$'), 'REJECT'),
    ('incon', '\033[95m',
     re.compile(r'⚖️\s*\[InconsistencyWatcher\]\s*(.+)$'), 'INCON '),
    ('start', '\033[94m',
     re.compile(r'💡\s*\[ProactiveCareEngine\]\s*(.+)$'), 'START '),
]
_RESET = '\033[0m'


def find_latest_log() -> str:
    pointer = os.path.join(ROOT, 'docs', 'runtime_logs', 'latest.txt')
    if os.path.exists(pointer):
        try:
            with open(pointer, 'r', encoding='utf-8', errors='ignore') as f:
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
            try:
                candidates.append((os.path.getmtime(full), full))
            except OSError:
                pass
    if not candidates:
        return ''
    candidates.sort(reverse=True)
    return candidates[0][1]


def _classify_line(line: str) -> Optional[tuple]:
    """返回 (key, color, label, body) 或 None."""
    for key, color, pat, label in _EVENT_PATTERNS:
        m = pat.search(line)
        if m:
            return (key, color, label, m.group(1).strip())
    return None


def _format_event(ts_str: str, key: str, color: str,
                    label: str, body: str, use_color: bool) -> str:
    if use_color:
        return f"{color}{ts_str}  {label}{_RESET}  {body}"
    return f"{ts_str}  {label}  {body}"


def _extract_ts(line: str) -> str:
    """从行首抓 [sess_xxx] [turn_xxx] 后的时间, 或用 wall clock 兜底."""
    m = re.search(r'\[sess_\d{8}_(\d{6})_', line)
    if m:
        hh, mm, ss = m.group(1)[:2], m.group(1)[2:4], m.group(1)[4:6]
        return f"{hh}:{mm}:{ss}"
    return time.strftime('%H:%M:%S')


def render_history(path: str, last_n: int, filter_key: Optional[str],
                    use_color: bool) -> int:
    """一次性 dump 历史. 返回输出条数."""
    if not path or not os.path.exists(path):
        print(f"⚠️ log 不存在: {path}")
        return 0
    events = []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                cls = _classify_line(line)
                if cls is None:
                    continue
                key, color, label, body = cls
                if filter_key and filter_key not in key:
                    continue
                ts = _extract_ts(line)
                events.append(_format_event(ts, key, color, label, body, use_color))
    except Exception as e:
        print(f"⚠️ 读 log 失败: {e}")
        return 0
    tail = events[-last_n:] if last_n > 0 else events
    print('\n'.join(tail))
    print(f"\n--- {len(tail)} / {len(events)} ProactiveCare 事件 (filter={filter_key or 'all'}) ---")
    return len(tail)


def follow(path: str, filter_key: Optional[str], use_color: bool,
            poll_interval: float = 1.0) -> None:
    """实时 tail -f. Ctrl+C 退出."""
    if not path or not os.path.exists(path):
        print(f"⚠️ log 不存在: {path}")
        return
    print(f"📡 follow {path}")
    print(f"   filter={filter_key or 'all'}  color={'on' if use_color else 'off'}")
    print("   按 Ctrl+C 退出\n" + '-' * 70)
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)  # EOF
            while True:
                line = f.readline()
                if not line:
                    time.sleep(poll_interval)
                    continue
                cls = _classify_line(line)
                if cls is None:
                    continue
                key, color, label, body = cls
                if filter_key and filter_key not in key:
                    continue
                ts = _extract_ts(line)
                print(_format_event(ts, key, color, label, body, use_color),
                       flush=True)
    except KeyboardInterrupt:
        print("\n--- 退出 follow ---")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-follow', action='store_true',
                    help='不实时跟踪, 一次性 dump 当前 log 退出')
    ap.add_argument('--last', type=int, default=50,
                    help='dump 模式最后 N 条事件 (默认 50, 0=全部)')
    ap.add_argument('--filter', default='',
                    help='只看某类事件: sensor/health/skip/nudge/reject/incon/start')
    ap.add_argument('--log', default='',
                    help='指定 log 文件 (默认 latest.txt 指向)')
    ap.add_argument('--no-color', action='store_true',
                    help='禁用 ANSI 颜色 (适合管道 / Windows 老终端)')
    args = ap.parse_args()

    log_path = args.log or find_latest_log()
    if not log_path:
        print("❌ 找不到 runtime log. 给 --log 或确认 docs/runtime_logs/ 有内容")
        return 1

    filter_key = args.filter.strip().lower() or None
    use_color = not args.no_color and sys.stdout.isatty()

    if args.no_follow:
        render_history(log_path, args.last, filter_key, use_color)
    else:
        # 先 dump 最后 20 条作上下文, 再 follow
        if args.last > 0:
            render_history(log_path, min(args.last, 20), filter_key, use_color)
            print('-' * 70)
        follow(log_path, filter_key, use_color)
    return 0


if __name__ == '__main__':
    sys.exit(main())
