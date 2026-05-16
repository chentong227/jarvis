import os
import platform
import json
from jarvis_blood import PerceptionData

MANIFEST = {
    "name": "system_eyes",
    "description": "系统底层雷达，用于扫描操作系统环境、读取已知空间信标（高频文件夹的绝对路径）。"
}

class Eyes:
    def __init__(self):
        print("👁️  [L2-系统雷达]: 操作系统底层扫描矩阵已开启...")
        self.os_type = platform.system()
        self.current_user_dir = os.path.expanduser("~")
        
        self.config_dir = "jarvis_config"
        os.makedirs(self.config_dir, exist_ok=True)
        self.landmark_file = os.path.join(self.config_dir, "os_landmarks.json")

    def _load_landmarks(self) -> dict:
        """加载并【自动清洗】空间信标库"""
        if not os.path.exists(self.landmark_file):
            default_landmarks = {"桌面": os.path.join(self.current_user_dir, "Desktop")}
            with open(self.landmark_file, "w", encoding="utf-8") as f:
                json.dump(default_landmarks, f, ensure_ascii=False, indent=2)
            return default_landmarks
        
        try:
            with open(self.landmark_file, "r", encoding="utf-8") as f:
                raw_landmarks = json.load(f)
            
            # 👇 潜意识自愈机制：过滤掉物理世界已经不存在的死信标
            valid_landmarks = {}
            changed = False
            for alias, path in raw_landmarks.items():
                if os.path.exists(path):
                    valid_landmarks[alias] = path
                else:
                    changed = True
                    print(f"\n   🧹[潜意识清理]: 发现失效信标 [{alias} -> {path}]，已从视觉皮层及记录中彻底物理剥离。")
            
            # 如果有脏数据被清理了，顺手更新一下本地 JSON，根治认死理
            if changed:
                with open(self.landmark_file, "w", encoding="utf-8") as f:
                    json.dump(valid_landmarks, f, ensure_ascii=False, indent=2)
                    
            return valid_landmarks
        except Exception:
            return {}

    def scan(self, hands=None) -> PerceptionData:
        drives =[]
        if self.os_type == "Windows":
            import string
            drives =[f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]

        landmarks = self._load_landmarks()
        landmark_str = "\n".join([f"  - {k}: {v}" for k, v in landmarks.items()])

        elements =[
            {"type": "os_info", "text": f"当前操作系统: {self.os_type}"},
            {"type": "user_dir", "text": f"用户主目录: {self.current_user_dir}"},
            {"type": "available_drives", "text": f"本地可用盘符: {', '.join(drives)}"},
            {"type": "spatial_landmarks", "text": f"【系统已知空间信标(绝对坐标)】:\n{landmark_str if landmark_str else '暂无有效记录'}"}
        ]

        return PerceptionData(
            url=f"os://{platform.node()}",
            page_title="系统底层控制台",
            interactable_elements=elements
        )