# -*- coding: utf-8 -*-
"""[P5-Gap3 / 2026-05-21 18:35] Screen Vision CLI

让 Sir 一行命令看 ScreenVisionEngine 状态 / latest snapshot / history / debug 触发.

用法:
    python scripts/screen_vision_dump.py --latest       # 看最新 snapshot
    python scripts/screen_vision_dump.py --history 10   # 看最近 10 帧
    python scripts/screen_vision_dump.py --stats         # engine 状态 (calls/success/fail/redacted)
    python scripts/screen_vision_dump.py --snap-now      # 立即触发 1 次 sample (要 JARVIS_SCREEN_VISION=1 + 启动主进程)
    python scripts/screen_vision_dump.py --status         # env flag check + last snapshot age

文件依赖:
    memory_pool/screen_snapshot.json   ← latest 1 帧 atomic 覆盖
    memory_pool/screen_history.jsonl    ← rolling N 帧

详 docs/JARVIS_VISION_INTEGRATION.md
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import _cli_utils  # noqa: F401  # 🆕 [Sir Track 2] force utf-8 stdout
import time
from datetime import datetime


# Windows console UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SNAPSHOT_PATH = os.path.join('memory_pool', 'screen_snapshot.json')
HISTORY_PATH = os.path.join('memory_pool', 'screen_history.jsonl')


def _format_age(captured_at: float) -> str:
    age_s = time.time() - captured_at
    if age_s < 60:
        return f"{int(age_s)}s ago"
    if age_s < 3600:
        return f"{int(age_s / 60)}min ago"
    if age_s < 86400:
        return f"{int(age_s / 3600)}h ago"
    return f"{int(age_s / 86400)}d ago"


def show_latest() -> None:
    if not os.path.exists(SNAPSHOT_PATH):
        print(f"(no snapshot yet — file {SNAPSHOT_PATH} not exists)")
        print(f"  启动 Jarvis + 设 env JARVIS_SCREEN_VISION=1 + 唤醒一次")
        return
    with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"\n{'=' * 60}")
    print(f" Latest Screen Snapshot")
    print(f"{'=' * 60}\n")
    print(f"  Captured: {data.get('captured_iso', '?')} ({_format_age(data.get('captured_at', 0))})")
    print(f"  Trigger:  {data.get('sampling_trigger', '?')}")
    print(f"  Model:    {data.get('vision_model_used', '?')}")
    print(f"  Active:   {data.get('active_app', '(unknown)')}")
    if data.get('file_or_url_visible'):
        print(f"  File/URL: {data.get('file_or_url_visible')}")
    if data.get('cursor_line_approx') is not None:
        print(f"  Cursor:   line ~{data.get('cursor_line_approx')}")
    print(f"  Summary:  {data.get('screen_summary', '')}")
    if data.get('recent_visible_keywords'):
        kws = ', '.join(data.get('recent_visible_keywords', [])[:5])
        print(f"  Keywords: {kws}")
    if data.get('errors_visible'):
        for e in data.get('errors_visible', [])[:3]:
            print(f"  Error:    {e}")
    if data.get('build_output_status'):
        print(f"  Build:    {data.get('build_output_status')}")
    if data.get('notable_elements'):
        for n in data.get('notable_elements', [])[:3]:
            print(f"  Notable:  {n}")
    print(f"  Confidence: {data.get('confidence', 0):.2f}")
    if data.get('privacy_redacted'):
        print(f"  ⚠️ PRIVACY-REDACTED frame")


def show_history(limit: int = 10) -> None:
    if not os.path.exists(HISTORY_PATH):
        print(f"(no history yet — file {HISTORY_PATH} not exists)")
        return
    with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    if not lines:
        print(f"(history empty)")
        return
    items = []
    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    print(f"\n{'=' * 60}")
    print(f" Screen Vision History (last {len(items)} frames)")
    print(f"{'=' * 60}\n")
    for it in items:
        age = _format_age(it.get('captured_at', 0))
        trigger = it.get('sampling_trigger', '?')
        app = it.get('active_app', '(unknown)')[:30]
        summary = it.get('screen_summary', '')[:80]
        conf = it.get('confidence', 0)
        priv = '⚠' if it.get('privacy_redacted') else ' '
        print(f"  {priv} [{age:>10s}] {trigger:>10s} | {app:<30s} | conf={conf:.2f}")
        print(f"               → {summary}")


def show_stats() -> None:
    print(f"\n{'=' * 60}")
    print(f" Screen Vision Engine Stats")
    print(f"{'=' * 60}\n")
    env_v = (os.environ.get('JARVIS_SCREEN_VISION') or '').strip().lower()
    enabled = env_v in ('1', 'true', 'yes', 'on')
    print(f"  env JARVIS_SCREEN_VISION = {os.environ.get('JARVIS_SCREEN_VISION') or '(unset)'}")
    print(f"  enabled = {enabled}")
    print(f"  snapshot path = {SNAPSHOT_PATH}")
    print(f"    exists = {os.path.exists(SNAPSHOT_PATH)}")
    print(f"  history path = {HISTORY_PATH}")
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                n = sum(1 for _ in f)
            print(f"    line count = {n}")
        except Exception:
            print(f"    (history read failed)")
    else:
        print(f"    exists = False")

    # latest age
    if os.path.exists(SNAPSHOT_PATH):
        with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"  latest captured = {data.get('captured_iso', '?')} ({_format_age(data.get('captured_at', 0))})")
        print(f"  latest trigger  = {data.get('sampling_trigger', '?')}")
        print(f"  latest conf     = {data.get('confidence', 0):.2f}")
        print(f"  latest privacy  = {data.get('privacy_redacted', False)}")
    if not enabled:
        print(f"\n  ⚠ ScreenVision module 默认关闭 (Sir gradual opt-in)")
        print(f"  启用: 设 JARVIS_SCREEN_VISION=1 + 重启 Jarvis")


def snap_now() -> None:
    """立即触发 1 次 sample. 需要 Jarvis 主进程已运行 + JARVIS_SCREEN_VISION=1.

    本 CLI 是 standalone, 不能直接调主进程的 engine. 改为触发后台模式:
    用 daemon 模式跑一次完整 capture + describe (需 key_router).
    """
    print(f"⚠ snap-now 需要 Jarvis 主进程已运行 (engine + key_router 在那).")
    print(f"  替代: 先确保 JARVIS_SCREEN_VISION=1 启动 Jarvis.")
    print(f"  唤醒一次 (chat_bypass 主流自动 trigger).")
    print(f"  或等 5min backfill daemon 自动 sample.")
    print(f"  本 CLI 当前不直接调 vision LLM (避免 standalone 重复初始化 KeyRouter).")


def main() -> int:
    p = argparse.ArgumentParser(
        description='Screen Vision CLI — Gap 3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--latest', action='store_true',
                    help='看最新 snapshot 详情')
    p.add_argument('--history', type=int, metavar='N',
                    help='看最近 N 帧 history')
    p.add_argument('--stats', action='store_true',
                    help='看 engine 状态 + env flag check')
    p.add_argument('--snap-now', action='store_true',
                    help='立即触发 sample (需主进程运行)')
    p.add_argument('--status', action='store_true',
                    help='等同 --stats')

    args = p.parse_args()

    if args.history:
        show_history(args.history)
        return 0
    if args.stats or args.status:
        show_stats()
        return 0
    if args.snap_now:
        snap_now()
        return 0
    # default: --latest
    show_latest()
    return 0


if __name__ == '__main__':
    sys.exit(main())
