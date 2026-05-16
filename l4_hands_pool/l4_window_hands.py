import ctypes
import time
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "window_hands",
    "description": "窗口管理器。最小化/最大化/关闭/置顶/聚焦/排列/分屏/隐藏/列举所有窗口。纯本地，毫秒级。",
    "requires_eyes": "desktop_eyes"
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_SHOWNA = 8
SW_RESTORE = 9
SW_SHOWDEFAULT = 10
SW_FORCEMINIMIZE = 11

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040

WM_CLOSE = 0x0010
WM_SYSCOMMAND = 0x0112
SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_RESTORE = 0xF120

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【窗口管理器 指令字典】：
        1. "minimize": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 最小化
        2. "maximize": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 最大化
        3. "restore": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 还原
        4. "close": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 关闭
        5. "focus": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 聚焦到前台
        6. "hide": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 隐藏
        7. "show": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 显示
        8. "topmost": {"title": "窗口标题(可选)", "hwnd": 句柄(可选), "enable": true/false} — 置顶/取消置顶
        9. "minimize_all": {} — 最小化所有窗口(显示桌面)
        10. "restore_all": {} — 还原所有窗口
        11. "tile_left": {"title": "窗口标题(可选)"} — 贴靠左半屏
        12. "tile_right": {"title": "窗口标题(可选)"} — 贴靠右半屏
        13. "tile_top": {"title": "窗口标题(可选)"} — 贴靠上半屏
        14. "tile_bottom": {"title": "窗口标题(可选)"} — 贴靠下半屏
        15. "tile_quadrant": {"title": "窗口标题(可选)", "quadrant": "tl/tr/bl/br"} — 贴靠四分之一屏
        16. "move": {"title": "窗口标题(可选)", "x": 0, "y": 0, "width": 800, "height": 600} — 移动+调整大小
        17. "list_windows": {} — 列举所有可见窗口标题和句柄
        18. "find_window": {"title": "部分标题"} — 模糊搜索窗口
        19. "get_foreground": {} — 获取当前前台窗口标题
        20. "get_window_rect": {"title": "窗口标题(可选)", "hwnd": 句柄(可选)} — 获取窗口位置大小
        21. "set_opacity": {"title": "窗口标题(可选)", "opacity": 0-255} — 设置透明度
        22. "flash": {"title": "窗口标题(可选)"} — 闪烁窗口任务栏
        23. "cascade": {} — 层叠排列所有窗口
        24. "stack_horizontal": {} — 水平堆叠排列
        25. "stack_vertical": {} — 垂直堆叠排列
        """

    def _find_hwnd(self, title=None, hwnd=None):
        if hwnd:
            return hwnd
        if title:
            hwnd = user32.FindWindowW(None, title)
            if not hwnd:
                enum_result = []

                @WNDENUMPROC
                def enum_callback(h, lparam):
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(h, buf, 256)
                    if title.lower() in buf.value.lower():
                        enum_result.append(h)
                    return True

                user32.EnumWindows(enum_callback, 0)
                if enum_result:
                    return enum_result[0]
            return hwnd
        return user32.GetForegroundWindow()

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "minimize":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.ShowWindow(h, SW_MINIMIZE)
                    return ExecutionResult(success=True, msg="窗口已最小化")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "maximize":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.ShowWindow(h, SW_SHOWMAXIMIZED)
                    return ExecutionResult(success=True, msg="窗口已最大化")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "restore":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.ShowWindow(h, SW_RESTORE)
                    return ExecutionResult(success=True, msg="窗口已还原")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "close":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.PostMessageW(h, WM_CLOSE, 0, 0)
                    return ExecutionResult(success=True, msg="已发送关闭信号")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "focus":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.ShowWindow(h, SW_RESTORE)
                    user32.SetForegroundWindow(h)
                    return ExecutionResult(success=True, msg="窗口已聚焦")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "hide":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.ShowWindow(h, SW_HIDE)
                    return ExecutionResult(success=True, msg="窗口已隐藏")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "show":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    user32.ShowWindow(h, SW_SHOW)
                    return ExecutionResult(success=True, msg="窗口已显示")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "topmost":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if h:
                    enable = params.get("enable", True)
                    flag = HWND_TOPMOST if enable else HWND_NOTOPMOST
                    user32.SetWindowPos(h, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                    return ExecutionResult(success=True, msg=f"置顶={'开' if enable else '关'}")
                return ExecutionResult(success=False, msg="未找到目标窗口")

            elif cmd == "minimize_all":
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x4D, 0, 0, 0)
                user32.keybd_event(0x4D, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
                return ExecutionResult(success=True, msg="所有窗口已最小化")

            elif cmd == "restore_all":
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x44, 0, 0, 0)
                user32.keybd_event(0x44, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
                return ExecutionResult(success=True, msg="所有窗口已还原")

            elif cmd in ("tile_left", "tile_right", "tile_top", "tile_bottom"):
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if not h:
                    return ExecutionResult(success=False, msg="未找到目标窗口")
                screen_w = user32.GetSystemMetrics(0)
                screen_h = user32.GetSystemMetrics(1)
                if cmd == "tile_left":
                    user32.MoveWindow(h, 0, 0, screen_w // 2, screen_h, True)
                elif cmd == "tile_right":
                    user32.MoveWindow(h, screen_w // 2, 0, screen_w // 2, screen_h, True)
                elif cmd == "tile_top":
                    user32.MoveWindow(h, 0, 0, screen_w, screen_h // 2, True)
                elif cmd == "tile_bottom":
                    user32.MoveWindow(h, 0, screen_h // 2, screen_w, screen_h // 2, True)
                return ExecutionResult(success=True, msg=f"窗口已贴靠: {cmd}")

            elif cmd == "tile_quadrant":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if not h:
                    return ExecutionResult(success=False, msg="未找到目标窗口")
                screen_w = user32.GetSystemMetrics(0)
                screen_h = user32.GetSystemMetrics(1)
                hw, hh = screen_w // 2, screen_h // 2
                q = params.get("quadrant", "tl")
                pos = {"tl": (0, 0), "tr": (hw, 0), "bl": (0, hh), "br": (hw, hh)}
                x, y = pos.get(q, (0, 0))
                user32.MoveWindow(h, x, y, hw, hh, True)
                return ExecutionResult(success=True, msg=f"窗口已贴靠: {q}")

            elif cmd == "move":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if not h:
                    return ExecutionResult(success=False, msg="未找到目标窗口")
                x = params.get("x", 0)
                y = params.get("y", 0)
                w = params.get("width", 800)
                hh = params.get("height", 600)
                user32.MoveWindow(h, x, y, w, hh, True)
                return ExecutionResult(success=True, msg=f"窗口已移至 ({x},{y}) {w}x{hh}")

            elif cmd == "list_windows":
                results = []

                @WNDENUMPROC
                def enum_cb(h, lparam):
                    if user32.IsWindowVisible(h):
                        buf = ctypes.create_unicode_buffer(256)
                        user32.GetWindowTextW(h, buf, 256)
                        title = buf.value.strip()
                        if title and len(title) > 1:
                            results.append(f"0x{h:08X}: {title}")
                    return True

                user32.EnumWindows(enum_cb, 0)
                return ExecutionResult(success=True, msg=f"共 {len(results)} 个可见窗口:\n" + "\n".join(results[:50]),
                                       data={"windows": results})

            elif cmd == "find_window":
                title = params.get("title", "")
                results = []

                @WNDENUMPROC
                def enum_cb2(h, lparam):
                    if user32.IsWindowVisible(h):
                        buf = ctypes.create_unicode_buffer(256)
                        user32.GetWindowTextW(h, buf, 256)
                        if title.lower() in buf.value.lower():
                            results.append(f"0x{h:08X}: {buf.value}")
                    return True

                user32.EnumWindows(enum_cb2, 0)
                if results:
                    return ExecutionResult(success=True, msg="找到:\n" + "\n".join(results),
                                           data={"hwnds": results})
                return ExecutionResult(success=False, msg=f"未找到包含 '{title}' 的窗口")

            elif cmd == "get_foreground":
                h = user32.GetForegroundWindow()
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                return ExecutionResult(success=True, msg=f"前台窗口: {buf.value}", data={"hwnd": h, "title": buf.value})

            elif cmd == "get_window_rect":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if not h:
                    return ExecutionResult(success=False, msg="未找到目标窗口")

                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

                rect = RECT()
                user32.GetWindowRect(h, ctypes.byref(rect))
                w, hh = rect.right - rect.left, rect.bottom - rect.top
                return ExecutionResult(success=True,
                                       msg=f"位置:({rect.left},{rect.top}) 大小:{w}x{hh}",
                                       data={"x": rect.left, "y": rect.top, "width": w, "height": hh})

            elif cmd == "set_opacity":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if not h:
                    return ExecutionResult(success=False, msg="未找到目标窗口")
                opacity = params.get("opacity", 255)
                opacity = max(30, min(255, opacity))
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x80000
                LWA_ALPHA = 0x2
                style = user32.GetWindowLongW(h, GWL_EXSTYLE)
                user32.SetWindowLongW(h, GWL_EXSTYLE, style | WS_EX_LAYERED)
                user32.SetLayeredWindowAttributes(h, 0, opacity, LWA_ALPHA)
                return ExecutionResult(success=True, msg=f"透明度已设为 {opacity}/255")

            elif cmd == "flash":
                h = self._find_hwnd(params.get("title"), params.get("hwnd"))
                if not h:
                    return ExecutionResult(success=False, msg="未找到目标窗口")
                FLASHW_ALL = 0x3
                FLASHW_TIMERNOFG = 0xC

                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_int),
                                ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                                ("dwTimeout", ctypes.c_uint)]

                fwi = FLASHWINFO()
                fwi.cbSize = ctypes.sizeof(FLASHWINFO)
                fwi.hwnd = h
                fwi.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG
                fwi.uCount = 5
                fwi.dwTimeout = 0
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(fwi))
                return ExecutionResult(success=True, msg="窗口任务栏闪烁中")

            elif cmd == "cascade":
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x52, 0, 0, 0)
                user32.keybd_event(0x52, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
                time.sleep(0.3)
                user32.keybd_event(0x48, 0, 0, 0)
                user32.keybd_event(0x48, 0, 2, 0)
                return ExecutionResult(success=True, msg="窗口已层叠排列")

            elif cmd == "stack_horizontal":
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x5A, 0, 0, 0)
                user32.keybd_event(0x5A, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
                return ExecutionResult(success=True, msg="窗口已水平堆叠")

            elif cmd == "stack_vertical":
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x5A, 0, 0, 0)
                user32.keybd_event(0x5A, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
                time.sleep(0.3)
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x5A, 0, 0, 0)
                user32.keybd_event(0x5A, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
                return ExecutionResult(success=True, msg="窗口已垂直堆叠")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"窗口操作异常: {str(e)}")