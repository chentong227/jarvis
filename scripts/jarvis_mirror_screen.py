"""scripts/jarvis_mirror_screen.py — 注入 fake screen snapshot 进 mirror

[Sir 2026-05-28 fix50 / screen watch test]

Cascade 用本工具向 mirror 的 _mirror_screen.jsonl 注入 fake ScreenSnapshot, 让
ScreenVisionEngine _do_describe 跳过真截图 + 真 vision LLM, 直接走持久化+publish+
WatchTask judge 全链. Cascade 完整测 6 类视觉场景 (文字/图标/图形/图像 + 直播/限速)
不烧真 vision LLM token.

用法 (3 种):

  # 1) CLI 参数直接构造 (最常用, 适合 6 场景脚本)
  python scripts/jarvis_mirror_screen.py \\
      --summary "Bilibili 直播间, 主播张嘴中, 弹幕刷'唱了唱了'" \\
      --active-app "Bilibili 直播" \\
      --keywords "唱歌,弹幕,直播" \\
      --notable "主播张嘴动作,弹幕高密度" \\
      --confidence 0.9

  # 2) 从 JSON file 注入 (复杂 schema)
  python scripts/jarvis_mirror_screen.py --json scenarios/live_singing.json

  # 3) --clear: 清掉 _mirror_screen.jsonl 重新开始
  python scripts/jarvis_mirror_screen.py --clear

  # 自动找最新 D:/jarvis_mirror_* — 或 --mirror 指定

JSON schema (Cascade write 一行 = 1 帧):
  {
    "active_app": "Bilibili 直播",
    "file_or_url_visible": "https://live.bilibili.com/...",
    "screen_summary": "主播张嘴中, 弹幕高密度",
    "recent_visible_keywords": ["唱歌", "弹幕"],
    "errors_visible": [],
    "build_output_status": "",
    "notable_elements": ["主播张嘴动作", "弹幕高密度"],
    "confidence": 0.9,
    "privacy_redacted": false
  }
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

# Windows GBK stdout 撞 emoji, force utf-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass


def find_latest_mirror() -> str:
    """没指定 --mirror 时自动找 D:/jarvis_mirror_* 最新一个."""
    candidates = sorted(glob.glob('D:/jarvis_mirror_*'), reverse=True)
    candidates = [c for c in candidates if os.path.isdir(c)]
    if not candidates:
        raise SystemExit(
            "❌ 没找到任何 D:/jarvis_mirror_* 目录. "
            "先跑 python scripts/jarvis_mirror.py 启镜像."
        )
    return candidates[0]


def _split_csv(s: str) -> list:
    """'a,b,c' → ['a', 'b', 'c']. 空字符串 → []."""
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]


def build_payload_from_args(args) -> dict:
    """从 CLI args 构造 fake snapshot dict."""
    payload = {
        'active_app': args.active_app or '',
        'file_or_url_visible': args.file_or_url or '',
        'screen_summary': args.summary or '',
        'recent_visible_keywords': _split_csv(args.keywords),
        'errors_visible': _split_csv(args.errors),
        'build_output_status': args.build_status or '',
        'notable_elements': _split_csv(args.notable),
        'confidence': float(args.confidence),
        'privacy_redacted': bool(args.privacy_redacted),
    }
    if args.cursor_line is not None:
        try:
            payload['cursor_line_approx'] = int(args.cursor_line)
        except ValueError:
            pass
    if args.note:
        payload['_cascade_note'] = args.note
    return payload


def inject_snapshot(mirror_root: str, payload: dict) -> str:
    """append 1 行 fake snapshot 到 _mirror_screen.jsonl. 返 path."""
    screen_path = os.path.join(mirror_root, '_mirror_screen.jsonl')
    if not os.path.isdir(mirror_root):
        raise SystemExit(f"❌ mirror_root 不存在或不是目录: {mirror_root}")

    payload = dict(payload)
    payload.setdefault('_injected_at', time.time())
    payload.setdefault('_injected_iso', time.strftime('%Y-%m-%dT%H:%M:%S'))

    with open(screen_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')

    return screen_path


def clear_snapshots(mirror_root: str) -> str:
    """truncate _mirror_screen.jsonl. 返 path."""
    screen_path = os.path.join(mirror_root, '_mirror_screen.jsonl')
    if not os.path.isdir(mirror_root):
        raise SystemExit(f"❌ mirror_root 不存在: {mirror_root}")
    with open(screen_path, 'w', encoding='utf-8') as f:
        f.write('')
    return screen_path


def main() -> int:
    p = argparse.ArgumentParser(
        description='注入 fake screen snapshot 进 mirror (_mirror_screen.jsonl)'
    )
    p.add_argument('--mirror', type=str, default='',
                   help='镜像根目录 (默: 自动找 D:/jarvis_mirror_* 最新)')

    # Mode 1: --clear
    p.add_argument('--clear', action='store_true',
                   help='truncate _mirror_screen.jsonl 重新开始 (跟 inject 互斥)')

    # Mode 2: --json file
    p.add_argument('--json', type=str, default='',
                   help='从 JSON file 读 snapshot dict')

    # Mode 3: CLI 参数直接构造
    p.add_argument('--summary', type=str, default='',
                   help='screen_summary (主体描述, 1-2 句)')
    p.add_argument('--active-app', type=str, default='',
                   help='active_app (e.g. "Cursor", "Bilibili 直播")')
    p.add_argument('--file-or-url', type=str, default='',
                   help='file_or_url_visible')
    p.add_argument('--cursor-line', type=str, default=None,
                   help='cursor_line_approx (int)')
    p.add_argument('--keywords', type=str, default='',
                   help='recent_visible_keywords, comma-separated')
    p.add_argument('--errors', type=str, default='',
                   help='errors_visible, comma-separated')
    p.add_argument('--build-status', type=str, default='',
                   help='build_output_status (idle/running/failed/passed)')
    p.add_argument('--notable', type=str, default='',
                   help='notable_elements, comma-separated')
    p.add_argument('--confidence', type=float, default=0.9,
                   help='confidence 0-1 (default 0.9, > 0.3 才显 prompt)')
    p.add_argument('--privacy-redacted', action='store_true',
                   help='标 privacy-sensitive — judge 会 skip')
    p.add_argument('--note', type=str, default='',
                   help='Cascade 备注本帧目的 (e.g. "场景 A frame 2 build done")')

    args = p.parse_args()
    mirror_root = args.mirror or find_latest_mirror()

    if args.clear:
        path = clear_snapshots(mirror_root)
        print(f"🪞 [mirror_screen] mirror={mirror_root}")
        print(f"🪞 [mirror_screen] cleared → {path}")
        return 0

    if args.json:
        if not os.path.isfile(args.json):
            raise SystemExit(f"❌ JSON file 不存在: {args.json}")
        with open(args.json, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        if args.note:
            payload['_cascade_note'] = args.note
    else:
        if not args.summary and not args.active_app:
            raise SystemExit(
                "❌ 必须给 --summary 或 --active-app 或 --json (--clear 除外)"
            )
        payload = build_payload_from_args(args)

    path = inject_snapshot(mirror_root, payload)

    print(f"🪞 [mirror_screen] mirror={mirror_root}")
    print(f"🪞 [mirror_screen] wrote → {path}")
    print(f"🪞 [mirror_screen] summary  = {payload.get('screen_summary', '')[:120]}")
    if payload.get('errors_visible'):
        print(f"🪞 [mirror_screen] errors   = {payload['errors_visible']}")
    if payload.get('notable_elements'):
        print(f"🪞 [mirror_screen] notable  = {payload['notable_elements']}")
    print(
        f"💡 ScreenVision daemon 下次 _do_describe (默 5min, "
        f"active WatchTask 30s) 自动用本 fake. 立即触发: 主脑下轮自然走 SWM."
    )
    print(
        f"💡 看 fire: python scripts/jarvis_mirror_tail.py "
        f"--mirror \"{mirror_root}\" --event watch_task_fired"
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
