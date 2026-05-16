import sys
import threading
import socket
import json
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QObject

# ==========================================
# 原子组件 1：跨频段接收器 (神经桥接天线)
# ==========================================
class SignalBridge(QObject):
    action_received = pyqtSignal(dict)

# ==========================================
# 原子组件 2 & 3：空间载体 + 像素渲染器
# ==========================================
class JarvisWindowAtom(QWidget):
    def __init__(self, bridge: SignalBridge):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(100, 100, 300, 400)
        
        self._is_tracking = False
        self._start_pos = None

        self.layout = QVBoxLayout(self)
        self.text_label = QLabel("Jarvis 桌面便签已激活...", self)
        self.text_label.setStyleSheet("""
            color: #00FF00; 
            font-family: Consolas; 
            font-size: 14px; 
            background-color: rgba(10, 10, 10, 200); 
            padding: 15px; 
            border-radius: 8px;
        """)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text_label.setWordWrap(True)
        self.layout.addWidget(self.text_label)

        bridge.action_received.connect(self._handle_action)

    def _handle_action(self, action_dict):
        cmd = action_dict.get("command")
        params = action_dict.get("params", {})

        if cmd == "render_text":
            self.text_label.setText(params.get("text", ""))
        elif cmd == "append_text":
            current_text = self.text_label.text()
            self.text_label.setText(current_text + "\n" + params.get("text", ""))
        elif cmd == "move_window":
            self.move(params.get("x", 100), params.get("y", 100))
        elif cmd == "SHUTDOWN":
            QApplication.quit()

    # --- 鼠标拖拽物理定律 ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_tracking = True
            self._start_pos = event.globalPos() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_tracking:
            self.move(event.globalPos() - self._start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_tracking = False
            event.accept()

# ==========================================
# 核心改造：UDP 监听微波天线
# ==========================================
def _udp_listener(bridge, port=17890):
    """死循环监听本地 UDP 端口，加入单例检测逻辑"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(('127.0.0.1', port))
    except OSError:
        # 👇 核心修复：端口占用说明已有实例，直接静默退出，不抛出异常
        print(f"⚠️ [便签微服务]: 端口 {port} 已被占用，可能是已有实例在运行，本进程退出。")
        QApplication.quit()
        return
        
    print(f"📡 [便签微服务]: 监听于 UDP {port}...")
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            action_dict = json.loads(data.decode('utf-8'))
            bridge.action_received.emit(action_dict)
            if action_dict.get("command") == "SHUTDOWN":
                break
        except Exception as e:
            print(f"⚠️ [便签解析报错]: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    bridge = SignalBridge()
    window = JarvisWindowAtom(bridge)
    window.show()

    # 开启 UDP 天线
    listener_thread = threading.Thread(
        target=_udp_listener, 
        args=(bridge,), 
        daemon=True
    )
    listener_thread.start()

    sys.exit(app.exec_())