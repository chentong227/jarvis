"""scripts/jarvis_mirror_run_screen_scenarios.py — 一键跑 6 类视觉场景 mirror 测试

[Sir 2026-05-28 fix50 / screen watch 真测 cheat sheet]

Sir 真需求 (Sir 11:40 原话):
  "我最需要的就是让他盯着直播, 直播发生什么画面提醒我, 或者让他盯着你, 你出现 API
   限速提醒我之类的这种."

6 场景 (E/F = Sir P0 真用例, A-D = 视觉 4 类 P1 覆盖):
  E (直播)     — '盯下直播, 主播开始唱歌就喊我'    [字幕/口型/弹幕 evidence]
  F (限速)     — '看着 Windsurf 出 rate limit 提醒'  [errors_visible 字段]
  A (文字)     — 'build 完叫我'                       [terminal text]
  B (图标)     — '微信红点亮了告诉我'                  [notable_elements 红点]
  C (图形)     — 'AAPL 涨破 100 通知'                  [图表 summary]
  D (图像)     — '下载图标变绿说一声'                  [status icon]

每场景流程:
  1. Cascade 注入 sir 话 (mirror_say)
  2. 等 init_wait s 让主脑 reply + Registrar 提取
  3. Cascade 注入 frame1 (初态, judge 应不命中)
  4. 等 frame_wait s 让 ScreenVision daemon describe + judge
  5. Cascade 注入 frame2 (触发态, judge 应命中 → fire)
  6. 等 frame_wait s 让 judge fire + 主脑 nudge reply
  7. 输出该场景的 watch_task_* event count

用法:
  # 启 mirror (另开窗口) — 等到 mirror_voice_worker_started event
  python scripts/jarvis_mirror.py --task "fix50 screen watch 6 scenarios"

  # 跑全部 6 场景 (默 ~8 min)
  python scripts/jarvis_mirror_run_screen_scenarios.py

  # 只跑 E + F (Sir P0)
  python scripts/jarvis_mirror_run_screen_scenarios.py --scenarios E,F

  # 跑单场景 + 缩短等待 (调试)
  python scripts/jarvis_mirror_run_screen_scenarios.py --scenarios A --init-wait 3 --frame-wait 15
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

# Windows GBK stdout 撞 emoji, force utf-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass


# ============================================================
# 6 场景定义
# ============================================================

SCENARIOS = {
    'E': {
        'priority': 'P0',
        'name': '直播 (Sir 真用例 — 主播唱歌)',
        'sir_text': '盯下这个直播间, 主播一开始唱歌就喊我',
        'frame1': {
            'active_app': 'Bilibili 直播',
            'file_or_url_visible': 'https://live.bilibili.com/12345',
            'screen_summary': '直播间画面: 主播 idle 状态, 弹幕稀疏, 没在唱歌',
            'recent_visible_keywords': ['直播', '弹幕', 'idle'],
            'notable_elements': ['主播头像', '聊天框', '礼物栏'],
            'confidence': 0.9,
        },
        'frame2': {
            'active_app': 'Bilibili 直播',
            'file_or_url_visible': 'https://live.bilibili.com/12345',
            'screen_summary': '直播间: 主播张嘴中, 字幕显"歌词", 弹幕刷屏 "唱了唱了 好听!"',
            'recent_visible_keywords': ['唱歌', '弹幕', '歌词', '主播'],
            'notable_elements': [
                '主播张嘴动作 (歌唱口型)',
                '字幕显歌词',
                '弹幕高密度刷"唱了"',
            ],
            'confidence': 0.95,
        },
        'expected_fire_keyword': '唱歌',
    },
    'F': {
        'priority': 'P0',
        'name': 'Cascade 限速 (Sir 真用例 — 盯 Windsurf rate limit)',
        'sir_text': '看着 Windsurf 这个对话窗口, 出现 rate limit 错误提醒我',
        'frame1': {
            'active_app': 'Windsurf (Cascade chat)',
            'file_or_url_visible': 'cascade://chat',
            'screen_summary': 'Cascade chat panel: AI 正常响应, 没错误',
            'recent_visible_keywords': ['Cascade', 'chat', 'tool', 'response'],
            'notable_elements': ['chat 列表', '输入框', 'tool call 卡片'],
            'errors_visible': [],
            'confidence': 0.9,
        },
        'frame2': {
            'active_app': 'Windsurf (Cascade chat)',
            'file_or_url_visible': 'cascade://chat',
            'screen_summary': 'Cascade chat 顶 banner: "Rate limit exceeded (429), retry in 60s". 输入框灰',
            'recent_visible_keywords': ['rate', 'limit', '429', 'exceeded'],
            'notable_elements': [
                '顶部 red error banner',
                '输入框灰禁用',
                'retry in 60s 计时器',
            ],
            'errors_visible': [
                'Rate limit exceeded (HTTP 429)',
                'Cascade chat throttled',
            ],
            'confidence': 0.97,
        },
        'expected_fire_keyword': 'rate limit',
    },
    'A': {
        'priority': 'P1',
        'name': '文字 (build 完叫我)',
        'sir_text': '在 Cursor terminal 跑 build 呢, build 完叫我',
        'frame1': {
            'active_app': 'Cursor — Terminal',
            'file_or_url_visible': '',
            'screen_summary': 'Terminal 显示 "Building... 47% [############       ]"',
            'recent_visible_keywords': ['Building', 'webpack', '47%'],
            'build_output_status': 'running',
            'notable_elements': ['进度条 47%'],
            'confidence': 0.9,
        },
        'frame2': {
            'active_app': 'Cursor — Terminal',
            'file_or_url_visible': '',
            'screen_summary': 'Terminal 显示 "Build succeeded in 12.3s ✓"',
            'recent_visible_keywords': ['Build', 'succeeded', '12.3s', '✓'],
            'build_output_status': 'passed',
            'notable_elements': ['绿色 success ✓', 'webpack done'],
            'confidence': 0.95,
        },
        'expected_fire_keyword': 'build',
    },
    'B': {
        'priority': 'P1',
        'name': '图标 (微信红点)',
        'sir_text': '帮我盯下系统托盘, 微信红点出现就告诉我',
        'frame1': {
            'active_app': 'Desktop (微信 background)',
            'file_or_url_visible': '',
            'screen_summary': '桌面 + 任务栏托盘: WeChat 图标无 badge',
            'recent_visible_keywords': ['桌面', '托盘'],
            'notable_elements': ['WeChat tray icon (无 badge, 灰色)'],
            'confidence': 0.85,
        },
        'frame2': {
            'active_app': 'Desktop (微信 notification)',
            'file_or_url_visible': '',
            'screen_summary': '桌面 + 任务栏托盘: WeChat 图标右上角红色数字 badge "3"',
            'recent_visible_keywords': ['微信', 'badge', '3 条', '通知'],
            'notable_elements': [
                'WeChat tray icon 红色 badge "3"',
                '右下角 toast 弹窗',
            ],
            'confidence': 0.92,
        },
        'expected_fire_keyword': '微信',
    },
    'C': {
        'priority': 'P1',
        'name': '图形 (股票 AAPL 涨破 100)',
        'sir_text': '股票软件 AAPL 涨破 100 通知我',
        'frame1': {
            'active_app': '同花顺',
            'file_or_url_visible': '',
            'screen_summary': 'AAPL 实时图表: 当前价 98.50, K 线上升趋势',
            'recent_visible_keywords': ['AAPL', '98.50', 'K线'],
            'notable_elements': ['上升 K 线', '当前价 98.50'],
            'confidence': 0.9,
        },
        'frame2': {
            'active_app': '同花顺',
            'file_or_url_visible': '',
            'screen_summary': 'AAPL 实时图表: 当前价 100.80, 突破 100 关口, 红色 K 线',
            'recent_visible_keywords': ['AAPL', '100.80', '突破', '100'],
            'notable_elements': [
                'AAPL 突破 100 关口',
                '红色大 K 线',
                '成交量放大',
            ],
            'confidence': 0.95,
        },
        'expected_fire_keyword': '100',
    },
    'D': {
        'priority': 'P1',
        'name': '图像 (下载图标变绿)',
        'sir_text': 'IDM 下载图标变绿 (下载完成) 说一声',
        'frame1': {
            'active_app': 'IDM Download Manager',
            'file_or_url_visible': '',
            'screen_summary': 'IDM 下载窗口: 文件下载中, 图标蓝色 in-progress, 进度 73%',
            'recent_visible_keywords': ['IDM', '下载', '73%'],
            'notable_elements': ['Download progress icon (blue, in-progress)'],
            'confidence': 0.9,
        },
        'frame2': {
            'active_app': 'IDM Download Manager',
            'file_or_url_visible': '',
            'screen_summary': 'IDM 下载窗口: 文件下载完成, 图标变绿 ✓, "Download complete"',
            'recent_visible_keywords': ['IDM', '下载', '完成', 'complete'],
            'notable_elements': [
                'Download icon (green, complete) ✓',
                'Download complete 弹窗',
            ],
            'confidence': 0.95,
        },
        'expected_fire_keyword': '下载',
    },
}


# ============================================================
# Helpers
# ============================================================


def find_latest_mirror() -> str:
    candidates = sorted(glob.glob('D:/jarvis_mirror_*'), reverse=True)
    candidates = [c for c in candidates if os.path.isdir(c)]
    if not candidates:
        raise SystemExit(
            "❌ 没找到任何 D:/jarvis_mirror_* 目录. "
            "另开窗 python scripts/jarvis_mirror.py --task '...'"
        )
    return candidates[0]


def run_subcmd(args_list: list, *, cwd: str = '.') -> int:
    """同步跑一个子命令 (mirror_say / mirror_screen), 透传 stdout."""
    print(f"   $ {' '.join(args_list)}")
    proc = subprocess.run(args_list, cwd=cwd, env=os.environ.copy())
    return proc.returncode


def tail_count_events(mirror_root: str, *, since_ts: float,
                       event_types: set) -> dict:
    """读 _mirror_output.jsonl 统计 since_ts 之后各 event 数."""
    path = os.path.join(mirror_root, '_mirror_output.jsonl')
    if not os.path.exists(path):
        return {e: 0 for e in event_types}
    counts = {e: 0 for e in event_types}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = float(entry.get('ts', 0) or 0)
                if ts < since_ts:
                    continue
                ev = entry.get('event', '')
                if ev in event_types:
                    counts[ev] += 1
    except Exception as e:
        print(f"   ⚠️ tail 失败: {e}")
    return counts


def run_scenario(scenario_id: str, scenario: dict,
                  mirror_root: str, *,
                  init_wait: float, frame_wait: float,
                  python_exe: str, repo_root: str) -> dict:
    """跑单场景, 返 metrics dict."""
    name = scenario['name']
    pri = scenario['priority']
    sir_text = scenario['sir_text']
    frame1 = scenario['frame1']
    frame2 = scenario['frame2']
    expected_kw = scenario.get('expected_fire_keyword', '')

    print()
    print('=' * 78)
    print(f"🎬 场景 {scenario_id} [{pri}] — {name}")
    print('=' * 78)
    print(f"  sir_text:  {sir_text}")
    print(f"  expected fire keyword: '{expected_kw}'")
    print()

    scenario_start_ts = time.time()

    # Step 0: clear 上次的 fake snapshot
    print("Step 0/4: clear 上次 fake snapshot")
    run_subcmd([
        python_exe,
        os.path.join('scripts', 'jarvis_mirror_screen.py'),
        '--mirror', mirror_root, '--clear',
    ], cwd=repo_root)
    print()

    # Step 1: 注入 sir 话 → 触发 Registrar
    print(f"Step 1/4: 注入 sir 话 → Registrar 提取 watch_task")
    run_subcmd([
        python_exe,
        os.path.join('scripts', 'jarvis_mirror_say.py'),
        '--mirror', mirror_root,
        sir_text,
        '--note', f"[fix50 scenario {scenario_id}] {name}",
    ], cwd=repo_root)
    print(f"   ⏱  等 {init_wait}s 让主脑 reply + Registrar LLM 提取...")
    time.sleep(init_wait)
    print()

    # Step 2: 注入 frame1 (初态)
    print("Step 2/4: 注入 frame1 (初态, judge 应不命中)")
    f1_args = [
        python_exe,
        os.path.join('scripts', 'jarvis_mirror_screen.py'),
        '--mirror', mirror_root,
        '--summary', frame1.get('screen_summary', ''),
        '--active-app', frame1.get('active_app', ''),
        '--keywords', ','.join(frame1.get('recent_visible_keywords', [])),
        '--notable', ','.join(frame1.get('notable_elements', [])),
        '--errors', ','.join(frame1.get('errors_visible', [])),
        '--build-status', frame1.get('build_output_status', ''),
        '--confidence', str(frame1.get('confidence', 0.9)),
        '--note', f"scenario {scenario_id} frame1 (初态)",
    ]
    if frame1.get('file_or_url_visible'):
        f1_args.extend(['--file-or-url', frame1['file_or_url_visible']])
    run_subcmd(f1_args, cwd=repo_root)
    print(f"   ⏱  等 {frame_wait}s 让 ScreenVision daemon describe + judge...")
    time.sleep(frame_wait)
    print()

    # Step 3: 注入 frame2 (触发态)
    print("Step 3/4: 注入 frame2 (触发态, judge 应命中 → fire)")
    f2_args = [
        python_exe,
        os.path.join('scripts', 'jarvis_mirror_screen.py'),
        '--mirror', mirror_root,
        '--summary', frame2.get('screen_summary', ''),
        '--active-app', frame2.get('active_app', ''),
        '--keywords', ','.join(frame2.get('recent_visible_keywords', [])),
        '--notable', ','.join(frame2.get('notable_elements', [])),
        '--errors', ','.join(frame2.get('errors_visible', [])),
        '--build-status', frame2.get('build_output_status', ''),
        '--confidence', str(frame2.get('confidence', 0.9)),
        '--note', f"scenario {scenario_id} frame2 (触发态)",
    ]
    if frame2.get('file_or_url_visible'):
        f2_args.extend(['--file-or-url', frame2['file_or_url_visible']])
    run_subcmd(f2_args, cwd=repo_root)
    print(f"   ⏱  等 {frame_wait}s 让 judge fire + 主脑 nudge reply...")
    time.sleep(frame_wait)
    print()

    # Step 4: 统计 events
    print("Step 4/4: 统计 _mirror_output.jsonl events")
    counts = tail_count_events(mirror_root, since_ts=scenario_start_ts,
                                event_types={
                                    'sir_input_received',
                                    'turn_complete',
                                    'mock_tts',
                                    'mirror_screen_fake_applied',
                                    'mock_audio_play',
                                })
    for ev, c in counts.items():
        print(f"   {ev:<35} : {c}")

    # 简易 verdict (人工最终判)
    fire_evidence_in_mock_tts = False
    try:
        path = os.path.join(mirror_root, '_mirror_output.jsonl')
        if os.path.exists(path) and expected_kw:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if float(entry.get('ts', 0) or 0) < scenario_start_ts:
                        continue
                    if entry.get('event') == 'mock_tts':
                        text = (entry.get('text') or '').lower()
                        if expected_kw.lower() in text:
                            fire_evidence_in_mock_tts = True
                            break
    except Exception:
        pass

    if fire_evidence_in_mock_tts:
        print(
            f"   ✅ mock_tts 含 expected keyword '{expected_kw}' "
            f"→ fire 链疑似成功 (人工最终判 prompt 自然度)"
        )
    elif counts.get('mock_tts', 0) > 0:
        print(
            f"   ⚠️ mock_tts {counts['mock_tts']} 条但没命中 '{expected_kw}' "
            f"— 主脑可能没用 watch evidence (人工看 tail)"
        )
    else:
        print(
            f"   ❌ 0 mock_tts — fire 链可能没触发 (检查 mirror 是否真起 / "
            f"backfill 时间不够). 用 tail 看详情:"
        )
        print(
            f"      python scripts/jarvis_mirror_tail.py "
            f"--mirror \"{mirror_root}\" --limit 20"
        )

    return {
        'scenario_id': scenario_id,
        'name': name,
        'priority': pri,
        'counts': counts,
        'fire_keyword_matched': fire_evidence_in_mock_tts,
        'duration_s': time.time() - scenario_start_ts,
    }


# ============================================================
# Main
# ============================================================


def main() -> int:
    p = argparse.ArgumentParser(
        description='跑 6 类视觉场景 mirror 测试 (Sir 真需求: 直播 + Cascade 限速)'
    )
    p.add_argument('--mirror', type=str, default='',
                   help='镜像根目录 (默: 自动找 D:/jarvis_mirror_* 最新)')
    p.add_argument('--scenarios', type=str, default='E,F,A,B,C,D',
                   help='跑哪些场景 (comma-sep, 默 E,F,A,B,C,D 全 6 个; '
                        'P0=E,F 仅 Sir 真用例)')
    p.add_argument('--init-wait', type=float, default=8.0,
                   help='sir 话注入后等 (s, 默 8) 给主脑 reply + Registrar 提取')
    p.add_argument('--frame-wait', type=float, default=35.0,
                   help='frame 注入后等 (s, 默 35) 给 daemon describe + judge')
    p.add_argument('--python', type=str, default=sys.executable,
                   help='python interpreter (默 当前 sys.executable)')
    args = p.parse_args()

    mirror_root = args.mirror or find_latest_mirror()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print('=' * 78)
    print('🎬 fix50 — 6 类视觉场景 mirror 测试')
    print('=' * 78)
    print(f"  mirror_root : {mirror_root}")
    print(f"  scenarios   : {args.scenarios}")
    print(f"  init_wait   : {args.init_wait}s")
    print(f"  frame_wait  : {args.frame_wait}s")
    print(f"  python      : {args.python}")
    print()
    print("💡 mirror 必须已起 (另开窗): "
           "python scripts/jarvis_mirror.py --task 'fix50 screen'")
    print()

    selected_ids = [s.strip().upper() for s in args.scenarios.split(',')
                     if s.strip()]
    unknown = [s for s in selected_ids if s not in SCENARIOS]
    if unknown:
        raise SystemExit(f"❌ 未知场景 id: {unknown}. 可选: {list(SCENARIOS.keys())}")

    results = []
    for sid in selected_ids:
        res = run_scenario(
            sid, SCENARIOS[sid], mirror_root,
            init_wait=args.init_wait,
            frame_wait=args.frame_wait,
            python_exe=args.python,
            repo_root=repo_root,
        )
        results.append(res)

    # 汇总
    print()
    print('=' * 78)
    print('🎬 汇总')
    print('=' * 78)
    print(
        f"  {'ID':<4}{'PRI':<6}{'fire_kw_match':<16}"
        f"{'mock_tts':<11}{'fake_applied':<14}{'dur':<7}{'name':<60}"
    )
    print('-' * 78)
    for r in results:
        c = r['counts']
        print(
            f"  {r['scenario_id']:<4}{r['priority']:<6}"
            f"{('✅ YES' if r['fire_keyword_matched'] else '❌ NO'):<16}"
            f"{c.get('mock_tts', 0):<11}"
            f"{c.get('mirror_screen_fake_applied', 0):<14}"
            f"{int(r['duration_s']):>3}s   "
            f"{r['name'][:60]}"
        )
    print()
    fire_count = sum(1 for r in results if r['fire_keyword_matched'])
    print(
        f"✅ {fire_count}/{len(results)} 场景 fire keyword 命中 mock_tts "
        f"(人工最终判 reply 自然度)."
    )
    print()
    print(f"💡 完整 audit: python scripts/jarvis_mirror_tail.py --mirror \"{mirror_root}\"")
    print(f"💡 看 fake 应用: ... --event mirror_screen_fake_applied")
    print(f"💡 看主脑回复: ... --event turn_complete")
    print(f"💡 看 mock TTS: ... --event mock_tts")

    return 0 if fire_count == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
