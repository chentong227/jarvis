import os
import webbrowser
import subprocess
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "url_launcher_hands",
    "description": "极简 URL/应用启动器。用系统默认浏览器打开网址，或用关联程序打开本地文件。零依赖，纯本地，毫秒级响应。",
}

class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【url_launcher_hands】极简启动器:
        1. "open_url": {"url": "https://..."} <- 用默认浏览器打开网址
        2. "open_file": {"path": "绝对路径"} <- 用关联程序打开本地文件/文件夹
        3. "open_app": {"app_name": "chrome"} <- 按名称启动应用 (chrome/firefox/edge/vscode/notepad/calculator/explorer/cmd)
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params

        try:
            if cmd == "open_url":
                url = params.get("url", "")
                if not url:
                    return ExecutionResult(success=False, msg="缺少 url 参数")
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                webbrowser.open(url)
                return ExecutionResult(success=True, msg=f"已在默认浏览器中打开 {url}")

            elif cmd == "open_file":
                path = params.get("path", "")
                if not path:
                    return ExecutionResult(success=False, msg="缺少 path 参数")
                path = os.path.expandvars(os.path.expanduser(path))
                if not os.path.exists(path):
                    return ExecutionResult(success=False, msg=f"路径不存在: {path}")
                os.startfile(path)
                return ExecutionResult(success=True, msg=f"已打开 {path}")

            elif cmd == "open_app":
                app_name = params.get("app_name", "").lower()
                app_map = {
                    "chrome": "chrome.exe",
                    "firefox": "firefox.exe",
                    "edge": "msedge.exe",
                    "vscode": "code",
                    "code": "code",
                    "notepad": "notepad.exe",
                    "calculator": "calc.exe",
                    "calc": "calc.exe",
                    "explorer": "explorer.exe",
                    "cmd": "cmd.exe",
                    "terminal": "cmd.exe",
                    "powershell": "powershell.exe",
                    "taskmgr": "taskmgr.exe",
                    "control": "control.exe",
                    "settings": "ms-settings:",
                }
                target = app_map.get(app_name, app_name)
                if target.startswith("ms-"):
                    os.startfile(target)
                else:
                    subprocess.Popen(target, shell=True)
                return ExecutionResult(success=True, msg=f"已启动 {app_name}")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"启动失败: {str(e)}")