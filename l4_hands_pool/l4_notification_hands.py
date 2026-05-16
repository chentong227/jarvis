import ctypes
import subprocess
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "notification_hands",
    "description": "Windows通知发射器。弹窗/气泡/消息框/系统通知。纯本地。",
}

user32 = ctypes.windll.user32


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【通知发射器 指令字典】：
        1. "toast": {"title": "标题", "message": "内容", "duration": 5} — Windows Toast通知
        2. "msgbox": {"title": "标题", "message": "内容"} — 消息弹窗(阻塞)
        3. "balloon": {"title": "标题", "message": "内容"} — 托盘气泡
        4. "flash_taskbar": {} — 闪烁任务栏
        5. "beep": {"freq": 1000, "duration": 500} — 系统蜂鸣
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "toast":
                title = params.get("title", "Jarvis")
                message = params.get("message", "")
                duration = params.get("duration", 5)
                ps = (
                    f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                    f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                    f"$texts = $template.GetElementsByTagName('text'); "
                    f"$texts[0].AppendChild($template.CreateTextNode('{title}')) | Out-Null; "
                    f"$texts[1].AppendChild($template.CreateTextNode('{message}')) | Out-Null; "
                    f"$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Jarvis'); "
                    f"$toast = New-Object Windows.UI.Notifications.ToastNotification($template); "
                    f"$notifier.Show($toast)"
                )
                subprocess.Popen(["powershell", "-Command", ps], shell=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ExecutionResult(success=True, msg=f"Toast已发送: {title}")

            elif cmd == "msgbox":
                title = params.get("title", "Jarvis")
                message = params.get("message", "")
                user32.MessageBoxW(0, message, title, 0x40)
                return ExecutionResult(success=True, msg="消息框已关闭")

            elif cmd == "balloon":
                title = params.get("title", "Jarvis")
                message = params.get("message", "")
                ps = (
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"$notify = New-Object System.Windows.Forms.NotifyIcon; "
                    f"$notify.Icon = [System.Drawing.SystemIcons]::Information; "
                    f"$notify.Visible = $true; "
                    f"$notify.ShowBalloonTip(5000, '{title}', '{message}', [System.Windows.Forms.ToolTipIcon]::Info)"
                )
                subprocess.Popen(["powershell", "-Command", ps], shell=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ExecutionResult(success=True, msg=f"气泡已发送: {title}")

            elif cmd == "flash_taskbar":
                FLASHW_ALL = 0x3
                FLASHW_TIMERNOFG = 0xC

                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_int),
                                ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                                ("dwTimeout", ctypes.c_uint)]

                fw = FLASHWINFO()
                fw.cbSize = ctypes.sizeof(FLASHWINFO)
                fw.hwnd = user32.GetForegroundWindow()
                fw.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG
                fw.uCount = 3
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(fw))
                return ExecutionResult(success=True, msg="任务栏闪烁")

            elif cmd == "beep":
                freq = params.get("freq", 1000)
                dur = params.get("duration", 500)
                ctypes.windll.kernel32.Beep(freq, dur)
                return ExecutionResult(success=True, msg=f"蜂鸣 {freq}Hz {dur}ms")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"通知异常: {str(e)}")