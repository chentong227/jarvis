import ctypes
import time
import os
import io
import base64
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "screenshot_hands",
    "description": "截图工具。全屏/窗口/区域截图，保存或返回base64。纯本地，毫秒级。",
    "requires_eyes": "desktop_eyes"
}

user32 = ctypes.windll.user32

try:
    from PIL import ImageGrab, Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【截图工具 指令字典】：
        1. "fullscreen": {"save_path": "可选路径"} — 全屏截图
        2. "window": {"title": "窗口标题", "save_path": "可选"} — 指定窗口截图
        3. "foreground": {"save_path": "可选"} — 前台窗口截图
        4. "region": {"x1": 0, "y1": 0, "x2": 500, "y2": 500, "save_path": "可选"} — 区域截图
        5. "to_clipboard": {"capture": "fullscreen/window/foreground/region", ...} — 截图到剪贴板
        6. "save_and_return": {"capture": "fullscreen", "save_path": "路径", ...} — 截图保存并返回信息
        """

    def _capture_fullscreen(self):
        if not HAS_PIL:
            return None
        return ImageGrab.grab()

    def _capture_window(self, title=None, hwnd=None):
        if not HAS_PIL:
            return None
        if hwnd is None and title:
            hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return None

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right <= r.left or r.bottom <= r.top:
            return None
        return ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))

    def _capture_foreground(self):
        hwnd = user32.GetForegroundWindow()
        return self._capture_window(hwnd=hwnd)

    def _capture_region(self, x1, y1, x2, y2):
        if not HAS_PIL:
            return None
        return ImageGrab.grab(bbox=(x1, y1, x2, y2))

    def _save_or_encode(self, img, save_path=None):
        if save_path:
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            img.save(save_path)
            return {"saved": True, "path": save_path, "size": f"{img.width}x{img.height}"}
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"saved": False, "base64": b64, "size": f"{img.width}x{img.height}"}

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        if not HAS_PIL:
            return ExecutionResult(success=False, msg="PIL/Pillow not installed. Run: pip install Pillow")

        try:
            if cmd == "fullscreen":
                img = self._capture_fullscreen()
                if img is None:
                    return ExecutionResult(success=False, msg="全屏截图失败")
                info = self._save_or_encode(img, params.get("save_path"))
                return ExecutionResult(success=True, msg=f"全屏截图 {info['size']}", data=info)

            elif cmd == "window":
                img = self._capture_window(title=params.get("title"), hwnd=params.get("hwnd"))
                if img is None:
                    return ExecutionResult(success=False, msg=f"窗口截图失败: {params.get('title', 'unknown')}")
                info = self._save_or_encode(img, params.get("save_path"))
                return ExecutionResult(success=True, msg=f"窗口截图 {info['size']}", data=info)

            elif cmd == "foreground":
                img = self._capture_foreground()
                if img is None:
                    return ExecutionResult(success=False, msg="前台窗口截图失败")
                info = self._save_or_encode(img, params.get("save_path"))
                return ExecutionResult(success=True, msg=f"前台截图 {info['size']}", data=info)

            elif cmd == "region":
                x1 = params.get("x1", 0)
                y1 = params.get("y1", 0)
                x2 = params.get("x2", 1920)
                y2 = params.get("y2", 1080)
                img = self._capture_region(x1, y1, x2, y2)
                if img is None:
                    return ExecutionResult(success=False, msg="区域截图失败")
                info = self._save_or_encode(img, params.get("save_path"))
                return ExecutionResult(success=True, msg=f"区域截图 ({x1},{y1})-({x2},{y2}) {info['size']}", data=info)

            elif cmd == "to_clipboard":
                capture = params.get("capture", "fullscreen")
                if capture == "fullscreen":
                    img = self._capture_fullscreen()
                elif capture == "foreground":
                    img = self._capture_foreground()
                elif capture == "window":
                    img = self._capture_window(title=params.get("title"))
                else:
                    img = self._capture_fullscreen()
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                import io as _io
                output = _io.BytesIO()
                img.convert("RGB").save(output, format="BMP")
                data = output.getvalue()[14:]
                output.close()
                ctypes.windll.user32.OpenClipboard(0)
                ctypes.windll.user32.EmptyClipboard()
                ctypes.windll.kernel32.GlobalAlloc.restype = ctypes.c_int
                h = ctypes.windll.kernel32.GlobalAlloc(0x2000, len(data))
                ctypes.windll.kernel32.GlobalLock.restype = ctypes.c_int
                ctypes.windll.kernel32.GlobalLock(h)
                ctypes.windll.user32.SetClipboardData(2, h)
                ctypes.windll.user32.CloseClipboard()
                return ExecutionResult(success=True, msg=f"截图已复制到剪贴板 {img.width}x{img.height}")

            elif cmd == "save_and_return":
                capture = params.get("capture", "fullscreen")
                save_path = params.get("save_path", "")
                if capture == "fullscreen":
                    img = self._capture_fullscreen()
                elif capture == "foreground":
                    img = self._capture_foreground()
                elif capture == "window":
                    img = self._capture_window(title=params.get("title"))
                elif capture == "region":
                    img = self._capture_region(params.get("x1", 0), params.get("y1", 0),
                                               params.get("x2", 1920), params.get("y2", 1080))
                else:
                    img = self._capture_fullscreen()
                if img is None:
                    return ExecutionResult(success=False, msg="截图失败")
                info = self._save_or_encode(img, save_path)
                return ExecutionResult(success=True, msg=f"截图完成 {info['size']}", data=info)

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"截图异常: {str(e)}")