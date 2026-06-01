# -*- coding: utf-8 -*-
"""
[P0+20-β.4.8 / 2026-05-19] Mic + Acoustic Wake 诊断 CLI

为 Sir P2 真机调试 acoustic wakeword (openWakeWord) 提供的工具.
覆盖准则 6.5 "CLI 可改 vocab" 要求 — Sir 不需改 .py + git commit.

用法
----
# 1. 查看现 vocab thresholds
python scripts/mic_diag.py --vocab-show

# 2. 实时显示麦克风 RMS (帮 Sir 判断环境噪音 / 是否需调 fallback_volume_entry)
python scripts/mic_diag.py --rms 10

# 3. 实时声学检测 (说话看 detect 分数, Sir 调 threshold 用)
python scripts/mic_diag.py --test-wake 20

# 4. 改 vocab 不用编辑 JSON (e.g. 改 threshold)
python scripts/mic_diag.py --set openwakeword_threshold=0.4
python scripts/mic_diag.py --set acoustic_wake_enabled=true

# 5. 启用 Sir 自训 jarvis_v1.onnx (P2 Sir 拿 Colab 训练完后)
python scripts/mic_diag.py --use-model memory_pool/wakeword_models/jarvis_v1.onnx

# 6. 切回内置 hey_jarvis_v0.1
python scripts/mic_diag.py --use-builtin hey_jarvis_v0.1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time

# 让 import jarvis_acoustic_wake 找到项目根
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _vocab_path() -> str:
    return os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')


def _load_vocab() -> dict:
    p = _vocab_path()
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_vocab_atomic(data: dict) -> None:
    p = _vocab_path()
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')  # POSIX 风格 trailing newline (与 seed 一致)
    os.replace(tmp, p)


def _parse_value(raw: str):
    """智能解析 CLI 值: 'true'→True / 'false'→False / 数字→数 / 其他→str."""
    s = raw.strip()
    low = s.lower()
    if low in ('true', 'yes', 'on'):
        return True
    if low in ('false', 'no', 'off'):
        return False
    if low in ('null', 'none', ''):
        return ''
    # 数字
    try:
        if '.' in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def cmd_vocab_show() -> int:
    from jarvis_acoustic_wake import load_mic_safety_thresholds, is_acoustic_wake_enabled
    thr = load_mic_safety_thresholds()
    print('=' * 60)
    print('mic_safety_vocab.json _meta.thresholds (β.4.8):')
    print('=' * 60)
    for k, v in thr.items():
        print(f"  {k:<40} = {v!r}")
    print('=' * 60)
    print(f"  vocab path: {_vocab_path()}")
    print(f"  acoustic_wake_enabled: {is_acoustic_wake_enabled()}")
    enabled = is_acoustic_wake_enabled()
    if enabled:
        print('  状态: 真机生效 ✓ AuditoryCortex 主循环走 acoustic wake')
    else:
        print('  状态: 灰度关闭 (默认). Sir 真机调通后')
        print('        python scripts/mic_diag.py --set acoustic_wake_enabled=true')
    print('=' * 60)
    return 0


def cmd_set(kv: str) -> int:
    """改 vocab 单个 key (e.g. acoustic_wake_enabled=true / threshold=0.4)."""
    if '=' not in kv:
        print(f"[ERR] --set 需 key=value, 你给的: {kv!r}")
        return 1
    k, v = kv.split('=', 1)
    k = k.strip()
    new_v = _parse_value(v)
    data = _load_vocab()
    meta = data.setdefault('_meta', {})
    thr = meta.setdefault('thresholds', {})
    if k not in thr:
        print(f"[WARN] key {k!r} 不在 vocab _meta.thresholds 里 (现有 keys: {list(thr.keys())})")
        print(f"       继续写入 (准则 6.5 vocab 可扩展)")
    old_v = thr.get(k, '<new>')
    thr[k] = new_v
    _save_vocab_atomic(data)
    print(f"[OK] {k}: {old_v!r} → {new_v!r}")
    print(f"     vocab: {_vocab_path()}")
    print(f"     (重启 Jarvis 主程序生效)")
    return 0


def cmd_use_model(model_path: str) -> int:
    """启用 Sir 自训 ONNX. 改 openwakeword_custom_model_path + 启 acoustic_wake."""
    full = os.path.abspath(model_path)
    if not os.path.exists(full):
        print(f"[ERR] model 文件不存在: {full}")
        return 1
    # 相对项目根的路径 (vocab 里存相对路径更好)
    try:
        rel = os.path.relpath(full, ROOT).replace('\\', '/')
    except ValueError:
        rel = full
    data = _load_vocab()
    thr = data.setdefault('_meta', {}).setdefault('thresholds', {})
    old = thr.get('openwakeword_custom_model_path', '')
    thr['openwakeword_custom_model_path'] = rel
    thr['acoustic_wake_enabled'] = True
    _save_vocab_atomic(data)
    size_kb = os.path.getsize(full) / 1024
    print(f"[OK] 启用 Sir 自训 ONNX:")
    print(f"     openwakeword_custom_model_path: {old!r} → {rel!r}")
    print(f"     acoustic_wake_enabled: → True")
    print(f"     model size: {size_kb:.1f} KB")
    print(f"     vocab: {_vocab_path()}")
    print(f"     (重启 Jarvis 主程序生效)")
    return 0


def cmd_use_builtin(model_name: str) -> int:
    """切回 openWakeWord 内置模型 (清 custom_path)."""
    data = _load_vocab()
    thr = data.setdefault('_meta', {}).setdefault('thresholds', {})
    thr['openwakeword_custom_model_path'] = ''
    thr['openwakeword_model'] = model_name
    _save_vocab_atomic(data)
    print(f"[OK] 切回内置 model:")
    print(f"     openwakeword_model: → {model_name!r}")
    print(f"     openwakeword_custom_model_path: → '' (清)")
    print(f"     (重启 Jarvis 主程序生效)")
    return 0


def cmd_rms(duration_s: float) -> int:
    """实时打 RMS — 帮 Sir 判断环境噪音范围, 调 fallback_volume_entry 时参考."""
    try:
        import pyaudio
        import numpy as np
    except ImportError as e:
        print(f"[ERR] 依赖未装: {e}")
        return 1
    print('=' * 60)
    print(f"麦克风 RMS 实时显示 — {duration_s:.0f}s")
    print('=' * 60)
    print('  默认 VAD: ENTRY=180 (说话进入) / EXIT=100 (退出说话)')
    print('  Sir 环境噪音 RMS 应 < 100 (安静 / 退出 VAD)')
    print('  Sir 正常说话 RMS 应 > 180 (进入 VAD)')
    print('  按 Ctrl+C 提前退出')
    print()
    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                         input=True, frames_per_buffer=1024)
    except Exception as e:
        print(f'[ERR] 麦克风打开失败: {e}')
        return 1
    started = time.time()
    rms_min, rms_max, rms_sum, count = 999999, 0, 0, 0
    last_print = 0.0
    try:
        while time.time() - started < duration_s:
            buf = stream.read(1024, exception_on_overflow=False)
            arr = np.frombuffer(buf, dtype=np.int16)
            rms = float(np.abs(arr).mean())
            count += 1
            rms_sum += rms
            if rms < rms_min:
                rms_min = rms
            if rms > rms_max:
                rms_max = rms
            now = time.time()
            if now - last_print >= 0.1:
                bar_len = min(int(rms / 20), 50)
                bar = '█' * bar_len + '░' * (50 - bar_len)
                marker = ''
                if rms > 180:
                    marker = '<— SPEAK (>180)'
                elif rms > 100:
                    marker = '<— middle (100-180)'
                sys.stdout.write(f"\r  RMS={rms:6.1f} [{bar}] {marker}".ljust(95))
                sys.stdout.flush()
                last_print = now
    except KeyboardInterrupt:
        print("\n  [Ctrl+C 退出]")
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass
    avg = rms_sum / max(1, count)
    print()
    print('=' * 60)
    print(f"  统计: min={rms_min:.1f}  avg={avg:.1f}  max={rms_max:.1f}  ({count} frames in {time.time()-started:.1f}s)")
    print('=' * 60)
    # 智能建议
    if rms_max < 80:
        print('  [建议] max RMS < 80 → 麦克风太远 / 增益太低 / Sir 没说话?')
    elif rms_min > 150:
        print('  [建议] min RMS > 150 → 环境太吵 (空调/风扇/视频). 现 ENTRY=180 可能误触发')
        print('         考虑: python scripts/mic_diag.py --set fallback_volume_entry=300')
    elif rms_max < 200 and avg > 50:
        print('  [建议] Sir 说话 RMS 不太高, 可能麦克风灵敏度低 / 说话太轻')
    return 0


def cmd_test_wake(duration_s: float) -> int:
    """实时声学检测 — 复用 jarvis_acoustic_wake CLI test-mic."""
    # 直接 import 调原 CLI 实现
    from jarvis_acoustic_wake import _cmd_test_mic
    return _cmd_test_mic(duration_s=duration_s, model_override=None)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        description='Jarvis Mic + Acoustic Wake 诊断 CLI (β.4.8)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('--vocab-show', action='store_true',
                      help='打印当前 mic_safety_vocab.json _meta.thresholds')
    grp.add_argument('--set', metavar='KEY=VALUE', dest='set_kv',
                      help='改单个 threshold (e.g. acoustic_wake_enabled=true)')
    grp.add_argument('--use-model', metavar='PATH',
                      help='启用 Sir 自训 ONNX (P2 jarvis_v1.onnx)')
    grp.add_argument('--use-builtin', metavar='NAME',
                      help='切回 openWakeWord 内置 (e.g. hey_jarvis_v0.1 / alexa)')
    grp.add_argument('--rms', type=float, nargs='?', const=10.0, metavar='SECONDS',
                      help='实时 RMS 显示 N 秒 (默认 10s)')
    grp.add_argument('--test-wake', type=float, nargs='?', const=20.0, metavar='SECONDS',
                      help='实时声学检测 N 秒 (默认 20s)')
    args = parser.parse_args()

    if args.vocab_show:
        return cmd_vocab_show()
    if args.set_kv:
        return cmd_set(args.set_kv)
    if args.use_model:
        return cmd_use_model(args.use_model)
    if args.use_builtin:
        return cmd_use_builtin(args.use_builtin)
    if args.rms is not None:
        return cmd_rms(args.rms)
    if args.test_wake is not None:
        return cmd_test_wake(args.test_wake)
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
