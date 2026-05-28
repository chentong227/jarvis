"""scripts/jarvis_mirror.py — Jarvis Agent Mirror launcher

[Sir 2026-05-28 22:00 fix49 mirror P3 launcher]

用法 (Cascade 在主 d:/Jarvis cwd 跑):
  python scripts/jarvis_mirror.py --task "测试 Sir 说 'remind me in 2 hours' 的 reminder 链"

行为:
  1. 选目标根目录: D:\\jarvis_mirror_<YYYYMMDD_HHMMSS>\\ (--root 可指定)
  2. shutil.copytree d:/Jarvis → 目标根 (ignore_patterns 跳大文件 / cache / git / legacy / nested mirror)
  3. 重置 _mirror_input.jsonl / _mirror_output.jsonl 空文件, 写 _mirror_meta.json (task / pid / cwd)
  4. subprocess.Popen `python jarvis_nerve.py` 在镜像 cwd, env JARVIS_MIRROR=1 + JARVIS_MIRROR_TASK=<task>
  5. 打印 mirror_root + log path + 注入命令 (`scripts/jarvis_mirror_say.py`) 给 Sir/Cascade

设计准则 (准则 6 数据强耦合 + 准则 8 优雅):
  - 单进程隔离 (subprocess cwd → mirror), 跟主 Jarvis 0 共享 sqlite / sentinel / nerve / state
  - 镜像启动失败不影响主 Jarvis, 镜像 crash 不污染主 d:/Jarvis (cwd 隔离)
  - --dry-run 只复制不启动 (给 Cascade pre-check)
  - --keep-runtime-logs 默认 False (镜像不继承主 Jarvis 历史 runtime log)
  - --include-models 默认 False (CosyVoice/ + ffmpeg.exe/ffprobe.exe 跳, MockVocalCord 不需)

风险记 (后人调试看这里):
  - 复制耗时: 主 d:/Jarvis 不含 CosyVoice/ffmpeg ~150MB → shutil.copytree ~10-30s on SSD
  - 端口冲突: dashboard 默 8765, mirror 启动 chat_bypass 触 dashboard_open 会撞主 port → 已在
    jarvis_chat_bypass.py:1641-1651 加 mirror_fast_call_skipped 短路
  - 主脑可能拿 mirror 自己的 .env / OPENROUTER_KEY 真烧 LLM 调用 (env 共享, 没办法). Cascade
    自觉用便宜 model 测试, 或 set JARVIS_MIRROR_DRY=1 (TODO 后续做)

依赖: 标准库 only (os/sys/shutil/argparse/json/time/subprocess)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

# [BUG #1 fix Sir 2026-05-28 22:42 mirror live test]
# Windows PowerShell stdout 默 GBK, launcher 用 emoji (🪞 🚀 📝 …) 会 UnicodeEncodeError 崩.
# Python 3.7+ TextIOWrapper.reconfigure 可重设 encoding, 这里 force utf-8 + errors='replace' 兜底.
# 影响范围: 只改 launcher 自己进程 stdout/stderr, 不影响 mirror subprocess (它走 DEVNULL).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# Ignore patterns — 跳什么不复制
# ============================================================

DEFAULT_IGNORE_NAMES = {
    # cache / build
    '__pycache__', '.pytest_cache', '.vscode', '.cursor',
    # vcs / legacy
    '.git', '_legacy',
    # large model weights (mirror 用 MockVocalCord 不需要)
    'CosyVoice',
    # nested mirror leftovers (防递归)
    '_mirror_input.jsonl', '_mirror_output.jsonl', '_mirror_meta.json',
}

LARGE_FILES_TO_SKIP = {
    'ffmpeg.exe',   # 95 MB, 镜像只测 chat / sentinel, 不会真切视频
    'ffprobe.exe',  # 95 MB, 同上
}

RUNTIME_DIRS_OPTIONAL = {
    # 默 不复制 runtime_logs (镜像从空 log 起), --keep-runtime-logs 才复制.
    # [BUG #4 Sir 2026-05-28 22:50 fix49] l2_eyes_pool 是 organ source (.py 文件, 不是
    # 截图缓存), 跳了会让 CentralNerve._hot_reload_organs 找不到 dir 而崩. 移出 OPTIONAL
    # → 总是复制. 真截图缓存在主进程 runtime / SQLite / 其他位置.
    'runtime_logs',
}


def _make_ignore(keep_runtime: bool, include_models: bool):
    """返一个 shutil.copytree ignore callable."""

    def ignore(src_dir: str, names: list) -> list:
        skip = set()
        for n in names:
            # 始终跳: cache / git / legacy
            if n in DEFAULT_IGNORE_NAMES:
                skip.add(n)
                continue
            # 跳大模型 binary, 除非 --include-models
            if not include_models and n in LARGE_FILES_TO_SKIP:
                skip.add(n)
                continue
            # runtime_logs 默 keep, --no-runtime-logs 才跳
            if not keep_runtime and n in RUNTIME_DIRS_OPTIONAL:
                skip.add(n)
                continue
        return list(skip)

    return ignore


# ============================================================
# 复制 + 初始化
# ============================================================

def copy_source_to_mirror(src: str, dst: str, *, keep_runtime: bool, include_models: bool) -> tuple:
    """复制 src → dst, 跳大文件 + cache. 返 (file_count, total_bytes, elapsed_s)."""
    if os.path.exists(dst):
        raise FileExistsError(f"mirror root already exists: {dst} (rm 它或换 --root)")

    t0 = time.time()
    print(f"📁 [mirror] copying {src} → {dst} ...")
    shutil.copytree(
        src, dst,
        ignore=_make_ignore(keep_runtime=keep_runtime, include_models=include_models),
        # symlinks=False (默) — 真复制, 避免 mirror 反读主目录
        # ignore_dangling_symlinks=True 不需要 (windows 不太用 symlink)
    )
    elapsed = time.time() - t0

    # 统计大小 + 文件数
    total_bytes = 0
    file_count = 0
    for root, _dirs, files in os.walk(dst):
        for f in files:
            try:
                total_bytes += os.path.getsize(os.path.join(root, f))
                file_count += 1
            except OSError:
                pass

    print(f"📁 [mirror] copied: {file_count} files / {total_bytes / 1048576:.1f} MB / {elapsed:.1f}s")
    return file_count, total_bytes, elapsed


def init_mirror_io(mirror_root: str, *, task: str) -> dict:
    """空 _mirror_input.jsonl / _mirror_output.jsonl + 写 _mirror_meta.json."""
    input_path = os.path.join(mirror_root, '_mirror_input.jsonl')
    output_path = os.path.join(mirror_root, '_mirror_output.jsonl')
    meta_path = os.path.join(mirror_root, '_mirror_meta.json')

    # 强制重置 (如果用户 reuse --root, 旧 JSONL 必须清掉, 否则 worker 看到陈年输入会乱跑)
    for p in (input_path, output_path):
        with open(p, 'w', encoding='utf-8') as f:
            f.write('')

    meta = {
        'task': task,
        'mirror_root': mirror_root,
        'source_root': SOURCE_ROOT,
        'created_ts': time.time(),
        'created_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'pid_launcher': os.getpid(),
        'input_path': input_path,
        'output_path': output_path,
    }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        'input_path': input_path,
        'output_path': output_path,
        'meta_path': meta_path,
    }


# ============================================================
# 启动 subprocess
# ============================================================

def launch_mirror_subprocess(mirror_root: str, *, task: str, detach: bool) -> tuple:
    """subprocess.Popen `python jarvis_nerve.py`, JARVIS_MIRROR=1 env.

    返 (rc, pid). detach=True 时 rc 恒为 0 (launch 成功), pid = subprocess pid.
    detach=False 时 rc = subprocess returncode, pid = subprocess pid.
    """
    env = os.environ.copy()
    env['JARVIS_MIRROR'] = '1'
    env['JARVIS_MIRROR_TASK'] = task or '<no task description>'
    # 防 Sir 在 mirror 看 dashboard 跟主进程撞 port: 留 TODO 后续把 port 也变成 env-tunable
    # 当前 chat_bypass.py:1641-1651 已加 dashboard mirror skip, 暂够用

    python_exe = sys.executable
    nerve_script = os.path.join(mirror_root, 'jarvis_nerve.py')

    cmd = [python_exe, nerve_script]
    print(f"🚀 [mirror] launch: {' '.join(cmd)}")
    print(f"🚀 [mirror] cwd: {mirror_root}")
    print(f"🚀 [mirror] env JARVIS_MIRROR=1, JARVIS_MIRROR_TASK={env['JARVIS_MIRROR_TASK'][:60]}")

    # [Sir 2026-05-28 23:10 fix49 smoke debug] subprocess 的 stdout/stderr 转发到
    # mirror_root/_mirror_stdout.log + _mirror_stderr.log, 方便 Cascade tail 看
    # nerve 启动是否成功 / chat_bypass 调用是否真打到我 monkey-patch wrapper.
    # 主进程 0 影响 (这是 subprocess 的 stdout, 不是 launcher 的).
    stdout_log = os.path.join(mirror_root, '_mirror_stdout.log')
    stderr_log = os.path.join(mirror_root, '_mirror_stderr.log')
    stdout_fp = open(stdout_log, 'wb')  # bytes mode, 不强转 encoding 避免 windows GBK
    stderr_fp = open(stderr_log, 'wb')
    print(f"📝 [mirror] subprocess stdout → {stdout_log}")
    print(f"📝 [mirror] subprocess stderr → {stderr_log}")

    if detach:
        # Windows DETACHED_PROCESS (= 0x00000008) 让镜像 subprocess 独立, 关 launcher 不杀镜像
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        proc = subprocess.Popen(
            cmd, cwd=mirror_root, env=env,
            creationflags=creationflags,
            stdout=stdout_fp, stderr=stderr_fp,
        )
        print(f"🚀 [mirror] subprocess started, pid={proc.pid}")
        # 返 (0, pid) 表示 launch 成功 (detach 下 pid 不当 returncode 用, 避免大数 pid 当 exit code)
        return (0, proc.pid)
    else:
        # 前台跑, Cascade 看实时 stdout (但 stdout 量很大, 建议加 --detach + tail _mirror_output.jsonl)
        proc = subprocess.Popen(cmd, cwd=mirror_root, env=env, stdout=stdout_fp, stderr=stderr_fp)
        proc.wait()
        return (proc.returncode, proc.pid)


# ============================================================
# CLI 入口
# ============================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='Jarvis Agent Mirror — 复制目录, MockVocalCord/MirrorVoiceWorker 启镜像 subprocess'
    )
    p.add_argument('--task', type=str, default='',
                   help='本次镜像测试目的, 写入 _mirror_meta.json + env JARVIS_MIRROR_TASK')
    p.add_argument('--root', type=str, default='',
                   help='镜像目标根目录 (默: D:/jarvis_mirror_<ts>/)')
    p.add_argument('--keep-runtime-logs', action='store_true',
                   help='复制 runtime_logs/ + l2_eyes_pool/ (默: 不复制, 镜像从空 runtime log 起)')
    p.add_argument('--include-models', action='store_true',
                   help='复制 ffmpeg.exe + ffprobe.exe (默: 不复制, mirror MockVocalCord 不需)')
    p.add_argument('--dry-run', action='store_true',
                   help='只复制 + init meta, 不启 subprocess (给 Cascade pre-check)')
    p.add_argument('--no-detach', action='store_true',
                   help='前台跑 subprocess (默 detach, launcher 退出 mirror 继续跑)')
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # 决定镜像根目录
    if args.root:
        mirror_root = os.path.abspath(args.root)
    else:
        ts = time.strftime('%Y%m%d_%H%M%S')
        mirror_root = f'D:/jarvis_mirror_{ts}'

    print(f"🪞 [Jarvis Agent Mirror] task='{args.task}'")
    print(f"🪞 [Jarvis Agent Mirror] source: {SOURCE_ROOT}")
    print(f"🪞 [Jarvis Agent Mirror] mirror: {mirror_root}")

    # 1. 复制
    try:
        copy_source_to_mirror(
            SOURCE_ROOT, mirror_root,
            keep_runtime=args.keep_runtime_logs,
            include_models=args.include_models,
        )
    except FileExistsError as e:
        print(f"❌ [mirror] {e}")
        return 2

    # 2. init JSONL + meta
    paths = init_mirror_io(mirror_root, task=args.task)
    print(f"📝 [mirror] input  : {paths['input_path']}")
    print(f"📝 [mirror] output : {paths['output_path']}")
    print(f"📝 [mirror] meta   : {paths['meta_path']}")

    # 3. dry-run check
    if args.dry_run:
        print("🛑 [mirror] --dry-run, 不启 subprocess. 检查上面 path 后再正式跑.")
        print(f"💡 [mirror] 下一步: python scripts/jarvis_mirror.py --root \"{mirror_root}\" --task \"...\"")
        return 0

    # 4. 启 subprocess
    rc, pid = launch_mirror_subprocess(mirror_root, task=args.task, detach=not args.no_detach)

    # 5. 打印 Cascade 用法 cheat sheet
    print()
    print("=" * 70)
    print("🪞 镜像已启动 — Cascade 用以下命令操作:")
    print("=" * 70)
    print(f"  注入 Sir 说话:  python scripts/jarvis_mirror_say.py --mirror \"{mirror_root}\" \"hi jarvis\"")
    print(f"  实时看输出:     python scripts/jarvis_mirror_tail.py --mirror \"{mirror_root}\"")
    print(f"  看 subprocess stdout/stderr: tail \"{mirror_root}\\_mirror_stdout.log\" / _mirror_stderr.log")
    print(f"  停镜像 (windows): taskkill /F /PID {pid}  (或关 cmd 窗口)")
    print(f"  清镜像 (windows): rmdir /S /Q \"{mirror_root}\"")
    print("=" * 70)

    return 0 if rc == 0 else rc


if __name__ == '__main__':
    sys.exit(main())
