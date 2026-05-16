import os
import platform
from jarvis_blood import PerceptionData

MANIFEST = {
    "name": "terminal_eyes",
    "description": "代码繁衍视野。用于在编写新器官时，提供底层代码规范与系统状态。"
}

class Eyes:
    def __init__(self):
        print("👁️ [L2-终端之眼]: 繁衍视觉皮层已接入...")

    def scan(self, hands=None) -> PerceptionData:
        sys_info = f"系统架构: {platform.system()} {platform.release()}"
        
        elements =[
            {"type": "status", "text": sys_info},
            {"type": "warning", "text": "【造物主模式】当前环境允许你编写并永久写入新的器官 Python 文件。"},
            {"type": "rule", "text": "注意：生成的器官将带有 _generated.py 尾缀。你的代码必须极其稳定，严禁包含任何破坏性系统命令。"}
        ]
        
        return PerceptionData(
            url="system://organ_forge",
            page_title="Jarvis Organ Forge (自我繁衍中心)",
            interactable_elements=elements
        )