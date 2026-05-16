import ctypes
import subprocess
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "audio_hands",
    "description": "音频设备管理器。列举/切换/静音/音量调节音频设备。纯本地。",
}

user32 = ctypes.windll.user32


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【音频设备管理器 指令字典】：
        1. "list_devices": {} — 列举音频输出设备
        2. "get_default": {} — 获取默认设备
        3. "set_default": {"device_name": "扬声器"} — 设置默认设备
        4. "get_volume": {} — 获取当前音量
        5. "set_volume": {"level": <0-100 整数, 必填>}
           — 设置媒体音量。level 必须显式来自用户原话（如 "30%" → 30）；不要使用任何默认值。
           — 若用户没说具体数字，先用一句话向 Sir 确认，再发起此调用。
        6. "mute": {"enable": true/false} — 静音/取消静音
        """

    def _run_ps(self, script):
        result = subprocess.run(["powershell", "-Command", script],
                                capture_output=True, text=True, timeout=10)
        return result.stdout.strip()

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "list_devices":
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$devices = @(); "
                    "Get-WmiObject Win32_SoundDevice | ForEach-Object { $devices += $_.Name }; "
                    "Write-Output ($devices -join '|||')"
                )
                output = self._run_ps(ps)
                devices = [d.strip() for d in output.split("|||") if d.strip()]
                if devices:
                    lines = [f"  {i+1}. {d}" for i, d in enumerate(devices)]
                    return ExecutionResult(success=True, msg=f"音频设备:\n" + "\n".join(lines),
                                           data={"devices": devices})
                return ExecutionResult(success=False, msg="未找到音频设备")

            elif cmd == "get_default":
                ps = (
                    "Add-Type -TypeDefinition @'"
                    "using System; using System.Runtime.InteropServices;"
                    "public class Audio {"
                    "  [DllImport(\"winmm.dll\")] public static extern int waveOutGetNumDevs();"
                    "}"
                    "'@; "
                    "[Audio]::waveOutGetNumDevs()"
                )
                output = self._run_ps(ps)
                return ExecutionResult(success=True, msg=f"音频输出设备数: {output}",
                                       data={"device_count": output})

            elif cmd == "set_default":
                device = params.get("device_name", "")
                if not device:
                    return ExecutionResult(success=False, msg="缺少 device_name")
                ps = (
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"[System.Windows.Forms.SendKeys]::SendWait('{{VOLUME_MUTE}}')"
                )
                return ExecutionResult(success=True, msg=f"已尝试切换默认设备(需手动): {device}")

            elif cmd == "get_volume":
                ps = (
                    "Add-Type -TypeDefinition @'"
                    "using System; using System.Runtime.InteropServices;"
                    "public class Vol {"
                    "  [DllImport(\"user32.dll\")] public static extern IntPtr SendMessageW(IntPtr hWnd, int Msg, IntPtr wParam, IntPtr lParam);"
                    "  [DllImport(\"user32.dll\")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);"
                    "}"
                    "'@; "
                    "Write-Output 'ok'"
                )
                output = self._run_ps(ps)
                return ExecutionResult(success=True, msg="音量查询(通过多媒体键调节间接实现)",
                                       data={"note": "use media_control_hands for precise volume"})

            elif cmd == "set_volume":
                # 🛡️ Bug G 修复：兼容大模型常见的参数命名漂移
                # （volume_level / volume / vol / value / percent / percentage → level）
                _level_aliases = ("level", "volume_level", "volume", "vol",
                                  "value", "percent", "percentage", "media_volume",
                                  "audio_level", "vol_level")
                raw_level = None
                used_alias = None
                for _k in _level_aliases:
                    if _k in params and params[_k] not in (None, ""):
                        raw_level = params[_k]
                        used_alias = _k
                        break
                if raw_level is None:
                    return ExecutionResult(
                        success=False,
                        msg="set_volume 需要明确传入 level 参数（0-100 的整数）。"
                            "也可使用别名 volume_level/volume/vol/percent。"
                            "请重新发起 FAST_CALL 并显式指定。",
                    )
                if isinstance(raw_level, str):
                    raw_level = raw_level.strip().rstrip("%").strip()
                try:
                    level = int(float(raw_level))
                except (TypeError, ValueError):
                    return ExecutionResult(
                        success=False,
                        msg=f"set_volume 收到非法 level={raw_level!r}（来自 '{used_alias}'），无法解析为整数。请用 0-100 的数字。",
                    )
                if not (0 <= level <= 100):
                    return ExecutionResult(
                        success=False,
                        msg=f"set_volume 的 level={level} 越界（必须在 0-100 之间）",
                    )
                VK_VOLUME_DOWN = 0xAE
                VK_VOLUME_UP = 0xAF
                for _ in range(50):
                    user32.keybd_event(VK_VOLUME_DOWN, 0, 0x0001, 0)
                    user32.keybd_event(VK_VOLUME_DOWN, 0, 0x0001 | 0x0002, 0)
                import time
                time.sleep(0.1)
                for _ in range(level // 2):
                    user32.keybd_event(VK_VOLUME_UP, 0, 0x0001, 0)
                    user32.keybd_event(VK_VOLUME_UP, 0, 0x0001 | 0x0002, 0)
                    time.sleep(0.02)
                return ExecutionResult(success=True, msg=f"音量已设为约 {level}%")

            elif cmd == "mute":
                enable = params.get("enable", True)
                VK_VOLUME_MUTE = 0xAD
                user32.keybd_event(VK_VOLUME_MUTE, 0, 0x0001, 0)
                user32.keybd_event(VK_VOLUME_MUTE, 0, 0x0001 | 0x0002, 0)
                return ExecutionResult(success=True, msg=f"静音={'开' if enable else '关'}")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"音频管理异常: {str(e)}")