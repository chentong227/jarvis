# -*- coding: utf-8 -*-
"""
[P0+20-β.2.9.1 / 2026-05-18] Display Hands — Sir 想要的 dim/sleep 显示器接口

Sir 准则 5 (言出必行): Jarvis 之前说 "I shall dim displays" 但没真接口能做.
现在加: dim_display / sleep_display / wake_display / get_brightness.

注: Windows 桌面显示器 (HDMI 接口) 通常 NOT support 软件改 brightness, 只能用
SetMonitorBrightness (WMI). Laptop 内屏可改. 软改不到的话, 用 monitor_off
(WM_SYSCOMMAND, SC_MONITORPOWER=2) 兜底 — 直接休眠显示器, 效果更好.
"""

import subprocess
from jarvis_blood import Action, ExecutionResult


MANIFEST = {
    "name": "display_hands",
    "description": "显示器亮度/电源控制. dim / sleep / wake / get_brightness."
                   " Sir 经典: '睡觉时把屏幕变暗'. 桌面外接屏不支持 brightness 软改,"
                   " 此情况自动 fallback 到 monitor_off (直接休眠显示器)."
}


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【显示器控制 指令字典】 [β.2.9.1]:
        1. "get_brightness": {} — 读当前亮度 (0-100). 失败 = 不支持软改 (外接屏).
        2. "set_brightness": {"level": 0-100} — 设置亮度. 失败时自动建议 sleep_display.
        3. "dim_display": {} — 等价 set_brightness(level=20). Sir 睡觉常用.
        4. "sleep_display": {} — 直接关显示器电源 (Windows SC_MONITORPOWER=2).
                                  最可靠的 'dim'. Sir 动鼠标键盘自动唤醒.
        5. "wake_display": {} — 主动唤醒显示器 (移动鼠标 1px).
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params

        try:
            if cmd == "get_brightness":
                return self._get_brightness()
            elif cmd == "set_brightness":
                level = params.get("level")
                if level is None:
                    return ExecutionResult(success=False, msg="缺 level (0-100) 参数")
                return self._set_brightness(int(level))
            elif cmd == "dim_display":
                # 先试 set_brightness(20), 失败 fallback sleep_display
                r = self._set_brightness(20)
                if not r.success:
                    return self._sleep_display()
                return r
            elif cmd == "sleep_display":
                return self._sleep_display()
            elif cmd == "wake_display":
                return self._wake_display()
            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")
        except Exception as e:
            return ExecutionResult(success=False, msg=f"display 异常: {str(e)}")

    def _get_brightness(self) -> ExecutionResult:
        try:
            ps = ("(Get-WmiObject -Namespace root/wmi "
                  "-Class WmiMonitorBrightness).CurrentBrightness")
            result = subprocess.run(["powershell", "-Command", ps],
                                      capture_output=True, text=True, timeout=10)
            out = result.stdout.strip()
            if out and out.isdigit():
                return ExecutionResult(success=True, msg=f"当前亮度: {out}%")
            return ExecutionResult(
                success=False,
                msg="无法读取亮度 (外接屏 / 不支持). 试 sleep_display 兜底."
            )
        except Exception as e:
            return ExecutionResult(success=False, msg=f"读亮度失败: {str(e)}")

    def _set_brightness(self, level: int) -> ExecutionResult:
        level = max(0, min(100, level))
        try:
            ps = (f"(Get-WmiObject -Namespace root/wmi "
                  f"-Class WmiMonitorBrightnessMethods)"
                  f".WmiSetBrightness(1,{level})")
            result = subprocess.run(["powershell", "-Command", ps],
                                      capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and 'ReturnValue' in (result.stdout or '') + (result.stderr or ''):
                # WMI 返回成功 (ReturnValue=0)
                return ExecutionResult(success=True, msg=f"亮度已设 {level}%")
            # WMI 通常在桌面外接屏失败
            return ExecutionResult(
                success=False,
                msg=f"WMI SetBrightness 失败 (大概率外接屏不支持). 建议改用 sleep_display."
            )
        except Exception as e:
            return ExecutionResult(success=False, msg=f"设亮度失败: {str(e)}")

    def _sleep_display(self) -> ExecutionResult:
        """SendMessage WM_SYSCOMMAND SC_MONITORPOWER=2 (off).
        Sir 鼠标键盘动就自动唤醒, 比 set_brightness 更兼容."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            HWND_BROADCAST = 0xFFFF
            WM_SYSCOMMAND = 0x0112
            SC_MONITORPOWER = 0xF170
            POWER_OFF = 2
            user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND,
                                  SC_MONITORPOWER, POWER_OFF)
            return ExecutionResult(success=True, msg="显示器已休眠 (动鼠标键盘自动唤醒)")
        except Exception as e:
            return ExecutionResult(success=False, msg=f"sleep_display 失败: {str(e)}")

    def _wake_display(self) -> ExecutionResult:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.mouse_event(0x0001, 1, 0, 0, 0)  # move 1px
            user32.mouse_event(0x0001, -1, 0, 0, 0)
            return ExecutionResult(success=True, msg="已唤醒显示器")
        except Exception as e:
            return ExecutionResult(success=False, msg=f"wake 失败: {str(e)}")
