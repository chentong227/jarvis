# -*- coding: utf-8 -*-
"""[P0+20-β.2.7.2 / 2026-05-17] 一次性修：Windows 应用音量混合器锁死 python.exe 1% 问题

Sir 反馈："滑块动不了，灰色锁死的 1%"

原因：
- Windows 应用音量混合器记每个应用的历史音量
- 某次音量被手动 / 第三方驱动 / NahimicService 设到 1% 后，Python 进程退出但 mixer 记住
- Jarvis 启动新 Python 进程时继承这个值，滑块灰色显示 "1%"

修法：
- 调 pycaw 直接 SetMasterVolume(1.0) 给所有当前活的 python.exe / pythonw.exe 进程
- 一次跑就好，Jarvis 不用重启也能听到声音
- 长期防御：β.2.7.2 已在 jarvis_central_nerve.py.__init__ 加自动恢复（重启 Jarvis 后自动生效）

用法：
    python scripts\\unlock_python_volume.py
"""
import os
import sys


def main():
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    except ImportError as e:
        print(f"ERROR: 缺少依赖 {e}. 请: pip install pycaw comtypes")
        sys.exit(1)

    print(f"=" * 60)
    print(f"  Python 进程音量恢复工具")
    print(f"  当前 PID: {os.getpid()}")
    print(f"=" * 60)
    print()

    comtypes.CoInitialize()
    sessions = AudioUtilities.GetAllSessions()
    print(f"找到 {len(sessions)} 个音频会话\n")

    found = []
    fixed = 0
    for session in sessions:
        try:
            if not session.Process:
                continue
            pname = (session.Process.name() or '').lower()
            pid = session.ProcessId
            if pname in ('python.exe', 'pythonw.exe'):
                v = session._ctl.QueryInterface(ISimpleAudioVolume)
                cur = v.GetMasterVolume()
                muted = v.GetMute()
                found.append((pid, pname, cur, muted))
                if cur < 0.95 or muted:
                    v.SetMasterVolume(1.0, None)
                    v.SetMute(0, None)
                    new_cur = v.GetMasterVolume()
                    print(f"  ✅ {pname} (pid={pid}): {cur:.0%} (muted={muted}) → {new_cur:.0%}")
                    fixed += 1
                else:
                    print(f"  ⏭️ {pname} (pid={pid}): 已是 {cur:.0%}，跳过")
        except Exception as e:
            print(f"  ⚠️ 会话处理失败: {e}")
            continue
    comtypes.CoUninitialize()

    print()
    if not found:
        print("没找到任何 Python 进程的音频会话。")
        print("可能 Jarvis 还没产生过音频输出，或者 Windows 没记录会话。")
        print("→ 重启 Jarvis 让 cosyvoice 产生一次 audio 输出再跑此脚本。")
    elif fixed == 0:
        print(f"全部 {len(found)} 个 Python 进程音量已经是 100%，无需修复。")
    else:
        print(f"✅ 恢复了 {fixed} / {len(found)} 个 Python 进程的音量")
        print("现在 Windows 音量混合器里 python.exe 滑块应该回到 100% 不再灰色。")
        print("如果还没声音，检查：")
        print("  1. Windows 主音量是否非零")
        print("  2. 默认输出设备是否正确 (扬声器 vs 蓝牙耳机)")
        print("  3. Jarvis cosyvoice 是否正常加载（log 找 '✅ [声带器官]'）")


if __name__ == '__main__':
    main()
