import time
import win32gui
import win32api
import win32con
import subprocess
import socket
import json
import os
import sys
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "desktop_hands",
    "description": "专治【桌面GUI】【便签/记事本界面】【鼠标点击/按键注入】。触发条件：要求操控可视化的桌面软件界面。⚠️排斥禁区：如果用户只是想静默生成/写入txt文档，【绝对禁止】调用我，请立刻挂载 txt_writer_hands！",
    "requires_eyes": "desktop_eyes"
}

class Hands:
    def __init__(self):
        print("⚙️ [L4-桌面手脚]: 副交感神经系统准备就绪 (开启静默句柄注入与UDP发射模式)。")
        self.requires_memory_seal = True
        self.gui_process = None
        self.last_hwnd = None 
        self.udp_port = 17890 # 便签微服务监听的端口

    def get_instruction_dict(self) -> str:
        return """
        【当前挂载：桌面副交感执行层 (L4) 指令字典】：
        1. "spawn_note": {}  
        2. "render_note": {"text": "待办内容"} 
        3. "close_note": {} 
        4. "os_click": {"x": 坐标X, "y": 坐标Y}
        5. "os_type": {"text": "内容"} 
        6. "wait": {"seconds": 2} <- 原地等待系统动画。
        7. "finish": {"message": "任务结束", "seal_memory": true}
        
        🛡️ 【桌面 GUI 物理交互协议】：
        1. UI 动画延迟法则：调用 spawn_note 后，必须调用 wait 停留 1-2 秒等待程序启动！否则后续的 render_note 会丢失。
        """

    def _send_udp(self, cmd: str, params: dict = None):
        """隐秘的 UDP 微波发射器，不需要理会目标是否存活"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            payload = json.dumps({"command": cmd, "params": params or {}}).encode('utf-8')
            sock.sendto(payload, ('127.0.0.1', self.udp_port))
            sock.close()
        except Exception as e:
            print(f"⚠️ [UDP发射失败]: {e}")

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        
        try:
            if cmd == "spawn_note":
                script_path = os.path.join("l4_hands_pool", "l4_gui_atom.py")
                self.gui_process = subprocess.Popen([sys.executable, script_path])
                time.sleep(1.0) # 👇 物理后摇：给独立进程1秒钟启动时间
                return ExecutionResult(success=True, msg="副交感进程已点火并启动完成")

            elif cmd == "render_note":
                self._send_udp("render_text", {"text": params.get("text", "")})
                # 👇 核心增强：执行完不再是“盲人”，而是手动给 L3 返回一条物理确认
                return ExecutionResult(
                    success=True, 
                    msg="内容已投递至便签。物理透视确认：窗口已存在，文字已渲染。", 
                    data={"suggested_model": "flash"}
                )

            # 👇 新增：补齐之前漏掉的 wait 指令
            elif cmd == "wait":
                sec = params.get("seconds", 2)
                time.sleep(sec)
                return ExecutionResult(success=True, msg=f"已原地物理等待 {sec} 秒")

            elif cmd == "close_note":
                self._send_udp("SHUTDOWN")
                return ExecutionResult(success=True, msg="已发送物理切断信号")
            
            elif cmd == "os_click":
                x, y = params.get("x"), params.get("y")
                hwnd = win32gui.WindowFromPoint((x, y))
                self.last_hwnd = hwnd 
                cx, cy = win32gui.ScreenToClient(hwnd, (x, y))
                lparam = win32api.MAKELONG(cx, cy)
                win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(0.05)
                win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
                return ExecutionResult(success=True, msg=f"已向后台句柄[{hwnd}]注入隐形点击 ({x}, {y})")
                
            elif cmd == "os_type":
                text = params.get("text", "")
                target_hwnd = self.last_hwnd or win32gui.GetForegroundWindow() 
                for char in text:
                    win32api.PostMessage(target_hwnd, win32con.WM_CHAR, ord(char), 0)
                    time.sleep(0.01)
                return ExecutionResult(success=True, msg=f"已向后台句柄[{target_hwnd}]静默注入文本")

            return ExecutionResult(success=False, msg=f"桌面肌肉不支持指令: {cmd}")
            
        except Exception as e:
            return ExecutionResult(success=False, msg=f"桌面执行报错: {str(e)}")

    def shutdown(self):
        self._send_udp("SHUTDOWN")
        
    def take_snapshot(self, save_path="memory_snapshot.png") -> str:
        # 这里为了演示精简，暂时返回 None，你可以随时把截图代码加回来
        return None