"""scripts/jarvis_mirror_tail.py — tail _mirror_output.jsonl (Cascade audit)

[Sir 2026-05-28 22:00 fix49 mirror P3 CLI-tail]

用法:
  python scripts/jarvis_mirror_tail.py --mirror D:/jarvis_mirror_20260528_223000
  python scripts/jarvis_mirror_tail.py                                          # 自动找最新
  python scripts/jarvis_mirror_tail.py --follow                                 # 持续 tail (Ctrl-C 退)
  python scripts/jarvis_mirror_tail.py --event turn_complete                    # 只看主脑 turn 结果
  python scripts/jarvis_mirror_tail.py --event mock_tts --limit 20              # 最近 20 条 TTS

事件类型 (jarvis_mirror_mode.py + jarvis_chat_bypass.py + jarvis_nerve.py 写):
  - sir_input_received      — Sir 说话被 worker 收到
  - turn_complete           — 主脑 stream_chat_local 完, channel='main_chat'
  - fast_call_attempt       — 工具调发起 (organ.command + params)
  - mock_tts                — TTS speak 路径 (text + len_chars)
  - mock_tts_render         — TTS render_only 路径
  - mock_audio_play         — play_only 路径
  - mock_tts_stop           — stop_immediately 路径
  - mirror_fast_call_skipped — ui_control.dashboard_* 短路
  - mirror_subtitle         — UI 字幕事件 (channel + text)
  - mirror_ui_state / mirror_ui_visual_pulse / mirror_ui_awake / ...
  - mirror_voice_worker_started / mirror_subtitle_overlay_started / ...
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
    candidates = sorted(glob.glob('D:/jarvis_mirror_*'), reverse=True)
    candidates = [c for c in candidates if os.path.isdir(c)]
    if not candidates:
        raise SystemExit("❌ 没找到 D:/jarvis_mirror_* 目录")
    return candidates[0]


def fmt_event(entry: dict) -> str:
    """单条 JSON 行 → 单行人读 string."""
    ev = entry.get('event', '?')
    ts_iso = entry.get('ts_iso', '?')

    if ev == 'sir_input_received':
        return f"[{ts_iso}] 🎤 Sir: {entry.get('text', '')!r}"
    if ev == 'turn_complete':
        sir = entry.get('sir_utterance', '')[:80]
        reply = entry.get('final_reply', '')[:200]
        dur = entry.get('duration_sec')
        tools = entry.get('tool_results', []) or []
        circuit = entry.get('circuit_broken_reason')
        dur_str = f"{dur:.1f}s" if dur else 'n/a'
        tag = f" (tools={len(tools)})" if tools else ''
        cb_str = f" ⚠️ circuit={circuit}" if circuit else ''
        return f"[{ts_iso}] 🧠 turn_complete dur={dur_str}{tag}{cb_str}\n   ↳ Sir : {sir!r}\n   ↳ Jrvs: {reply!r}"
    if ev == 'fast_call_attempt':
        return f"[{ts_iso}] 🔧 FAST_CALL {entry.get('organ')}.{entry.get('command')} params={entry.get('params_excerpt')}"
    if ev == 'mock_tts':
        return f"[{ts_iso}] 🗣️ TTS({entry.get('len_chars')}c): {entry.get('text', '')[:120]!r}"
    if ev == 'mock_tts_render':
        return f"[{ts_iso}] 🎙️ render_only({entry.get('len_chars')}c, retry={entry.get('retry')}): {entry.get('text', '')[:80]!r}"
    if ev == 'mock_audio_play':
        return f"[{ts_iso}] 🔊 play_only bytes={entry.get('byte_len')} text={entry.get('text', '')[:60]!r}"
    if ev == 'mock_tts_stop':
        return f"[{ts_iso}] 🛑 TTS stop"
    if ev == 'mirror_fast_call_skipped':
        return f"[{ts_iso}] 🚧 mirror_skip {entry.get('organ')}.{entry.get('command')} reason={entry.get('reason')}"
    if ev == 'mirror_subtitle':
        return f"[{ts_iso}] 📺 subtitle[{entry.get('channel')}]: {entry.get('text', '')[:160]!r}"
    if ev.startswith('mirror_ui_'):
        return f"[{ts_iso}] 🪟 UI {ev[10:]}: {json.dumps({k: v for k, v in entry.items() if k not in ('event','ts','ts_iso')}, ensure_ascii=False)}"
    if ev.startswith('mirror_voice_worker_') or ev.startswith('mirror_subtitle_overlay_'):
        return f"[{ts_iso}] 🪞 {ev}"

    # fallback: dump payload
    other = {k: v for k, v in entry.items() if k not in ('event', 'ts', 'ts_iso')}
    return f"[{ts_iso}] {ev}: {json.dumps(other, ensure_ascii=False)[:200]}"


def read_all_lines(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return f.readlines()


def filter_lines(lines: list, *, event_filter: str = '', limit: int = 0) -> list:
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            entry = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if event_filter and entry.get('event') != event_filter:
            continue
        out.append(entry)
    if limit and len(out) > limit:
        out = out[-limit:]
    return out


def main() -> int:
    p = argparse.ArgumentParser(description='tail _mirror_output.jsonl (人读格式)')
    p.add_argument('--mirror', type=str, default='', help='镜像根目录 (默: 自动找最新)')
    p.add_argument('--event', type=str, default='', help='只看某类 event (e.g. turn_complete / mock_tts)')
    p.add_argument('--limit', type=int, default=50, help='最近 N 条 (默 50, --follow 时无视)')
    p.add_argument('--follow', '-f', action='store_true', help='持续 tail (Ctrl-C 退)')
    p.add_argument('--raw', action='store_true', help='直接 print JSON line, 不做 human format')
    args = p.parse_args()

    mirror_root = args.mirror or find_latest_mirror()
    output_path = os.path.join(mirror_root, '_mirror_output.jsonl')
    print(f"🪞 [mirror_tail] {output_path}")
    print(f"🪞 [mirror_tail] event_filter={args.event or '(all)'}, limit={args.limit}, follow={args.follow}")
    print('-' * 70)

    if not args.follow:
        lines = read_all_lines(output_path)
        entries = filter_lines(lines, event_filter=args.event, limit=args.limit)
        for e in entries:
            if args.raw:
                print(json.dumps(e, ensure_ascii=False))
            else:
                print(fmt_event(e))
        return 0

    # follow 模式: 持续 poll, 1s tick
    seen_line_count = 0
    try:
        while True:
            lines = read_all_lines(output_path)
            new_lines = lines[seen_line_count:]
            seen_line_count = len(lines)
            entries = filter_lines(new_lines, event_filter=args.event)
            for e in entries:
                if args.raw:
                    print(json.dumps(e, ensure_ascii=False))
                else:
                    print(fmt_event(e))
            time.sleep(1.0)
    except KeyboardInterrupt:
        print('\n🪞 [mirror_tail] Ctrl-C, 退出')
        return 0


if __name__ == '__main__':
    sys.exit(main())
