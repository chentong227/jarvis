"""scripts/jarvis_mirror_say.py — 注入 Sir 模拟话进 mirror

[Sir 2026-05-28 22:00 fix49 mirror P3 CLI-say]

用法:
  python scripts/jarvis_mirror_say.py --mirror D:/jarvis_mirror_20260528_223000 "嗨 Jarvis 现在几点"
  python scripts/jarvis_mirror_say.py "提醒我 2 小时后吃药"            # 自动找最新 D:/jarvis_mirror_*

行为:
  - append 一行 JSON 到 <mirror>/_mirror_input.jsonl
  - MirrorVoiceWorker 1s poll 读到 → emit text_ready → jarvis_worker.push_command (跟 Sir 真说一致)
  - 立即写也立即返回, 不等镜像处理 (镜像处理由 Cascade tail _mirror_output.jsonl 看)

JSON schema (每行):
  {
    "text": "Sir 说的话",
    "ts": <unix float>,
    "ts_iso": "2026-05-28T22:30:00",
    "source": "cascade_inject",
    "note": "可选 — Cascade 备注本句测什么"
  }
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

# [BUG #1 fix Sir 2026-05-28 22:42] Windows GBK stdout 撞 emoji, force utf-8
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
            "❌ 没找到任何 D:/jarvis_mirror_* 目录. 先跑 python scripts/jarvis_mirror.py 启镜像."
        )
    return candidates[0]


def inject_text(mirror_root: str, text: str, *, note: str = '') -> str:
    """append 1 行 JSON 到 _mirror_input.jsonl. 返 path."""
    input_path = os.path.join(mirror_root, '_mirror_input.jsonl')
    if not os.path.exists(mirror_root):
        raise SystemExit(f"❌ mirror_root 不存在: {mirror_root}")

    entry = {
        'text': str(text),
        'ts': time.time(),
        'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'source': 'cascade_inject',
    }
    if note:
        entry['note'] = note

    with open(input_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    return input_path


def main() -> int:
    p = argparse.ArgumentParser(description='注入 Sir 说话到 mirror (_mirror_input.jsonl)')
    p.add_argument('text', type=str, help='Sir 模拟说的话')
    p.add_argument('--mirror', type=str, default='',
                   help='镜像根目录 (默: 自动找 D:/jarvis_mirror_* 最新)')
    p.add_argument('--note', type=str, default='',
                   help='Cascade 备注本句目的 (e.g. "测 reminder 链是否触发")')
    args = p.parse_args()

    mirror_root = args.mirror or find_latest_mirror()
    path = inject_text(mirror_root, args.text, note=args.note)

    print(f"🪞 [mirror_say] mirror={mirror_root}")
    print(f"🪞 [mirror_say] wrote → {path}")
    print(f"🪞 [mirror_say] text  = {args.text!r}")
    if args.note:
        print(f"🪞 [mirror_say] note  = {args.note}")
    print(f"💡 看响应: python scripts/jarvis_mirror_tail.py --mirror \"{mirror_root}\"")
    return 0


if __name__ == '__main__':
    sys.exit(main())
