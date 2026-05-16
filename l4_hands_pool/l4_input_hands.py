import ctypes
import time
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "input_hands",
    "description": "键鼠模拟器。点击/双击/右键/拖拽/滚轮/键盘输入/组合键/获取鼠标坐标/移动鼠标。纯本地，毫秒级。",
    "requires_eyes": "desktop_eyes"
}

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000

VK_MAP = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "ins": 0x2D, "printscreen": 0x2C, "prtsc": 0x2C,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
    "win": 0x5B, "windows": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "lctrl": 0xA2, "rctrl": 0xA3, "lalt": 0xA4, "ralt": 0xA5,
    "lshift": 0xA0, "rshift": 0xA1,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
    "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2, "media_play_pause": 0xB3,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                ("time", ctypes.c_uint), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint), ("union", INPUT_UNION)]


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【键鼠模拟器 指令字典】：
        1. "click": {"x": 500, "y": 300, "button": "left/right/middle"} — 单击
        2. "double_click": {"x": 500, "y": 300} — 双击
        3. "right_click": {"x": 500, "y": 300} — 右键
        4. "drag": {"x1": 100, "y1": 100, "x2": 500, "y2": 500} — 拖拽
        5. "scroll": {"delta": 120, "x": 500, "y": 300} — 滚轮(正=上,负=下)
        6. "move_to": {"x": 500, "y": 300} — 移动鼠标
        7. "get_pos": {} — 获取当前鼠标坐标
        8. "type_text": {"text": "要输入的文字"} — 逐字输入(支持中文)
        9. "paste_text": {"text": "要粘贴的文字"} — 通过剪贴板粘贴
        10. "key_press": {"key": "enter"} — 按下并释放单键
        11. "key_down": {"key": "ctrl"} — 按下不放
        12. "key_up": {"key": "ctrl"} — 释放
        13. "hotkey": {"keys": ["ctrl", "c"]} — 组合键
        14. "type_line": {"text": "一行文字"} — 输入一行+回车
        15. "scroll_up": {"clicks": 3} — 向上滚N格
        16. "scroll_down": {"clicks": 3} — 向下滚N格
        17. "middle_click": {"x": 500, "y": 300} — 中键点击
        18. "move_relative": {"dx": 100, "dy": -50} — 相对移动
        19. "click_at_current": {"button": "left"} — 在当前位置点击
        20. "send_keys": {"keys": ["ctrl", "shift", "t"]} — 发送组合键(别名)
        """

    def _send_input(self, inp):
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def _mouse_event(self, flags, x=0, y=0, data=0):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = x
        inp.union.mi.dy = y
        inp.union.mi.mouseData = data
        inp.union.mi.dwFlags = flags
        self._send_input(inp)

    def _key_event(self, vk, up=False):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
        self._send_input(inp)

    def _vk(self, key):
        key = key.lower()
        if key in VK_MAP:
            return VK_MAP[key]
        if len(key) == 1:
            return ord(key.upper())
        return 0

    def _set_cursor(self, x, y):
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        abs_x = int(x * 65535 / screen_w)
        abs_y = int(y * 65535 / screen_h)
        self._mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y)

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "click":
                x, y = params.get("x", 0), params.get("y", 0)
                btn = params.get("button", "left")
                self._set_cursor(x, y)
                time.sleep(0.02)
                if btn == "right":
                    self._mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0)
                elif btn == "middle":
                    self._mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0)
                else:
                    self._mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_LEFTUP, 0, 0)
                return ExecutionResult(success=True, msg=f"已{btn}键点击 ({x},{y})")

            elif cmd == "double_click":
                x, y = params.get("x", 0), params.get("y", 0)
                self._set_cursor(x, y)
                time.sleep(0.02)
                for _ in range(2):
                    self._mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_LEFTUP, 0, 0)
                    time.sleep(0.05)
                return ExecutionResult(success=True, msg=f"已双击 ({x},{y})")

            elif cmd == "right_click":
                x, y = params.get("x", 0), params.get("y", 0)
                self._set_cursor(x, y)
                time.sleep(0.02)
                self._mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0)
                self._mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0)
                return ExecutionResult(success=True, msg=f"已右键 ({x},{y})")

            elif cmd == "middle_click":
                x, y = params.get("x", 0), params.get("y", 0)
                self._set_cursor(x, y)
                time.sleep(0.02)
                self._mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0)
                self._mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0)
                return ExecutionResult(success=True, msg=f"已中键点击 ({x},{y})")

            elif cmd == "drag":
                x1, y1 = params.get("x1", 0), params.get("y1", 0)
                x2, y2 = params.get("x2", 0), params.get("y2", 0)
                self._set_cursor(x1, y1)
                time.sleep(0.02)
                self._mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0)
                time.sleep(0.02)
                self._set_cursor(x2, y2)
                time.sleep(0.02)
                self._mouse_event(MOUSEEVENTF_LEFTUP, 0, 0)
                return ExecutionResult(success=True, msg=f"已从 ({x1},{y1}) 拖拽至 ({x2},{y2})")

            elif cmd == "scroll":
                delta = params.get("delta", 120)
                x, y = params.get("x"), params.get("y")
                if x is not None and y is not None:
                    self._set_cursor(x, y)
                    time.sleep(0.02)
                self._mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta)
                return ExecutionResult(success=True, msg=f"已滚轮 {delta}")

            elif cmd == "scroll_up":
                clicks = params.get("clicks", 3)
                for _ in range(clicks):
                    self._mouse_event(MOUSEEVENTF_WHEEL, 0, 0, 120)
                    time.sleep(0.01)
                return ExecutionResult(success=True, msg=f"已向上滚 {clicks} 格")

            elif cmd == "scroll_down":
                clicks = params.get("clicks", 3)
                for _ in range(clicks):
                    self._mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -120)
                    time.sleep(0.01)
                return ExecutionResult(success=True, msg=f"已向下滚 {clicks} 格")

            elif cmd == "move_to":
                x, y = params.get("x", 0), params.get("y", 0)
                self._set_cursor(x, y)
                return ExecutionResult(success=True, msg=f"鼠标已移至 ({x},{y})")

            elif cmd == "move_relative":
                dx, dy = params.get("dx", 0), params.get("dy", 0)
                self._mouse_event(MOUSEEVENTF_MOVE, dx, dy)
                return ExecutionResult(success=True, msg=f"鼠标相对移动 ({dx},{dy})")

            elif cmd == "get_pos":
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                return ExecutionResult(success=True, msg=f"鼠标坐标: ({pt.x},{pt.y})",
                                       data={"x": pt.x, "y": pt.y})

            elif cmd == "click_at_current":
                btn = params.get("button", "left")
                if btn == "right":
                    self._mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0)
                elif btn == "middle":
                    self._mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0)
                else:
                    self._mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0)
                    self._mouse_event(MOUSEEVENTF_LEFTUP, 0, 0)
                return ExecutionResult(success=True, msg=f"已在当前位置{btn}键点击")

            elif cmd == "type_text":
                text = params.get("text", "")
                for ch in text:
                    vk = ord(ch.upper()) if ch.isascii() and ch.isalpha() else 0
                    if vk:
                        if ch.isupper():
                            self._key_event(self._vk("shift"))
                        self._key_event(vk)
                        self._key_event(vk, up=True)
                        if ch.isupper():
                            self._key_event(self._vk("shift"), up=True)
                    else:
                        import subprocess
                        subprocess.run(["powershell", "-Command",
                                        f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('{ch}')"],
                                       capture_output=True, timeout=2)
                    time.sleep(0.005)
                return ExecutionResult(success=True, msg=f"已输入: {text[:50]}")

            elif cmd == "paste_text":
                text = params.get("text", "")
                import subprocess
                ps = f"Set-Clipboard -Value '{text}'"
                subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=3)
                time.sleep(0.1)
                self._key_event(self._vk("ctrl"))
                self._key_event(self._vk("v"))
                self._key_event(self._vk("v"), up=True)
                self._key_event(self._vk("ctrl"), up=True)
                return ExecutionResult(success=True, msg=f"已粘贴: {text[:50]}")

            elif cmd == "key_press":
                key = params.get("key", "")
                vk = self._vk(key)
                if vk:
                    self._key_event(vk)
                    self._key_event(vk, up=True)
                    return ExecutionResult(success=True, msg=f"已按下: {key}")
                return ExecutionResult(success=False, msg=f"未知按键: {key}")

            elif cmd == "key_down":
                key = params.get("key", "")
                vk = self._vk(key)
                if vk:
                    self._key_event(vk)
                    return ExecutionResult(success=True, msg=f"已按下(保持): {key}")
                return ExecutionResult(success=False, msg=f"未知按键: {key}")

            elif cmd == "key_up":
                key = params.get("key", "")
                vk = self._vk(key)
                if vk:
                    self._key_event(vk, up=True)
                    return ExecutionResult(success=True, msg=f"已释放: {key}")
                return ExecutionResult(success=False, msg=f"未知按键: {key}")

            elif cmd in ("hotkey", "send_keys"):
                keys = params.get("keys", [])
                for k in keys:
                    vk = self._vk(k)
                    if vk:
                        self._key_event(vk)
                time.sleep(0.02)
                for k in reversed(keys):
                    vk = self._vk(k)
                    if vk:
                        self._key_event(vk, up=True)
                return ExecutionResult(success=True, msg=f"已发送组合键: {'+'.join(keys)}")

            elif cmd == "type_line":
                text = params.get("text", "")
                self.execute(Action(command="paste_text", params={"text": text}))
                time.sleep(0.05)
                self._key_event(self._vk("enter"))
                self._key_event(self._vk("enter"), up=True)
                return ExecutionResult(success=True, msg=f"已输入一行: {text[:50]}")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"输入模拟异常: {str(e)}")