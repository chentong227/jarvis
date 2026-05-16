import ctypes
import subprocess
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "clipboard_hands",
    "description": "剪贴板管理器。读取/写入/清空/追加剪贴板内容。纯本地。",
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
CF_TEXT = 1


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【剪贴板管理器 指令字典】：
        1. "get": {} — 读取剪贴板文本
        2. "set": {"text": "内容"} — 写入剪贴板
        3. "clear": {} — 清空剪贴板
        4. "append": {"text": "追加内容"} — 追加到现有内容末尾
        5. "get_clipboard": {} — 读取剪贴板(别名)
        6. "copy_from_file": {"path": "文件路径"} — 读取文件内容到剪贴板
        """

    def _get_clipboard_text(self):
        user32.OpenClipboard(0)
        try:
            if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                h = user32.GetClipboardData(CF_UNICODETEXT)
                if h:
                    kernel32.GlobalLock.restype = ctypes.c_wchar_p
                    ptr = kernel32.GlobalLock(h)
                    text = ptr.value if ptr else ""
                    kernel32.GlobalUnlock(h)
                    return text
            elif user32.IsClipboardFormatAvailable(CF_TEXT):
                h = user32.GetClipboardData(CF_TEXT)
                if h:
                    kernel32.GlobalLock.restype = ctypes.c_char_p
                    ptr = kernel32.GlobalLock(h)
                    text = (ptr.value or b"").decode("gbk", errors="replace") if ptr else ""
                    kernel32.GlobalUnlock(h)
                    return text
            return ""
        finally:
            user32.CloseClipboard()

    def _set_clipboard_text(self, text):
        user32.OpenClipboard(0)
        user32.EmptyClipboard()
        if text:
            size = len(text) + 1
            h = kernel32.GlobalAlloc(0x2000, size * 2)
            kernel32.GlobalLock.restype = ctypes.c_wchar_p
            ptr = kernel32.GlobalLock(h)
            ptr.value = text
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(CF_UNICODETEXT, h)
        user32.CloseClipboard()

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd in ("get", "get_clipboard"):
                text = self._get_clipboard_text()
                preview = text[:200] + ("..." if len(text) > 200 else "")
                return ExecutionResult(success=True, msg=f"剪贴板 ({len(text)} 字符): {preview}",
                                       data={"text": text, "length": len(text)})

            elif cmd == "set":
                text = params.get("text", "")
                self._set_clipboard_text(text)
                return ExecutionResult(success=True, msg=f"已写入剪贴板 ({len(text)} 字符)")

            elif cmd == "clear":
                self._set_clipboard_text("")
                return ExecutionResult(success=True, msg="剪贴板已清空")

            elif cmd == "append":
                current = self._get_clipboard_text()
                append_text = params.get("text", "")
                new_text = current + append_text
                self._set_clipboard_text(new_text)
                return ExecutionResult(success=True, msg=f"已追加 ({len(append_text)} 字符)，总计 {len(new_text)} 字符")

            elif cmd == "copy_from_file":
                path = params.get("path", "")
                if not path:
                    return ExecutionResult(success=False, msg="缺少 path 参数")
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    self._set_clipboard_text(content)
                    return ExecutionResult(success=True, msg=f"已从文件复制 ({len(content)} 字符)")
                except FileNotFoundError:
                    return ExecutionResult(success=False, msg=f"文件不存在: {path}")
                except Exception as e:
                    return ExecutionResult(success=False, msg=f"读取文件失败: {e}")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"剪贴板异常: {str(e)}")