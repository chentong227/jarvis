# -*- coding: utf-8 -*-
"""
health_tail.py — Jarvis 自身健康趋势查询

Sir 22:42 反馈: 2G 内存正不正常? 有无泄漏?

用法:
  python scripts/health_tail.py            # 最近 24 个 sample (2h)
  python scripts/health_tail.py -n 100     # 最近 100 个 (8h)
  python scripts/health_tail.py --now      # 立即采一份新 sample
"""
import argparse
import io
import json
import os
import sys
import time

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
HISTORY = os.path.join(ROOT, 'memory_pool', 'jarvis_health_history.jsonl')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-n', '--limit', type=int, default=24)
    ap.add_argument('--now', action='store_true', help='当前一次性采样 (Jarvis 进程内)')
    args = ap.parse_args()

    if args.now:
        try:
            import psutil
            p = psutil.Process(os.getpid())
            print("此命令在当前 (脚本) 进程中采样, 仅供参考:")
            print(f"  ws={p.memory_info().rss/1024/1024:.1f} MB")
            print(f"  threads={p.num_threads()}")
            print("如需 Jarvis 进程数据, 用任务管理器或下面历史日志.")
        except ImportError:
            print("缺 psutil: pip install psutil")
        return

    if not os.path.exists(HISTORY):
        print(f"无历史数据 ({HISTORY} 不存在). Jarvis 启动后 5min 才有第一份 sample.")
        return

    samples = []
    with open(HISTORY, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                samples.append(json.loads(line.strip()))
            except Exception:
                continue

    samples = samples[-args.limit:]
    if not samples:
        print("(no samples)")
        return

    print(f"=" * 70)
    print(f"Jarvis HealthProbe — 最近 {len(samples)} 个 sample")
    print(f"=" * 70)
    print(f"{'time':<10s}  {'WS (MB)':>10s}  {'Priv (MB)':>10s}  {'Thr':>5s}  {'Hdl':>5s}  CPU%")
    print("-" * 70)
    for s in samples:
        t = s.get('iso', '?')[-8:]
        print(f"{t:<10s}  {s.get('ws_mb', 0):>10.1f}  "
              f"{s.get('private_mb', 0):>10.1f}  "
              f"{s.get('threads', 0):>5d}  "
              f"{s.get('handles', 0):>5d}  "
              f"{s.get('cpu_pct', 0):.1f}")

    print()
    first, last = samples[0], samples[-1]
    span_h = (last.get('ts', 0) - first.get('ts', 0)) / 3600 if len(samples) > 1 else 0
    print(f"-- 趋势 (span={span_h:.1f}h) --")
    print(f"WS:      {first.get('ws_mb', 0):>8.1f}MB → {last.get('ws_mb', 0):>8.1f}MB "
          f"(Δ={last.get('ws_mb', 0) - first.get('ws_mb', 0):+.1f} MB)")
    print(f"Threads: {first.get('threads', 0):>8d}   → {last.get('threads', 0):>8d}   "
          f"(Δ={last.get('threads', 0) - first.get('threads', 0):+d})")
    print(f"Handles: {first.get('handles', 0):>8d}   → {last.get('handles', 0):>8d}   "
          f"(Δ={last.get('handles', 0) - first.get('handles', 0):+d})")


if __name__ == '__main__':
    main()
