from jarvis_blood import PerceptionData
MANIFEST = {
    "name": "memory_eyes",
    "description": "潜意识内视镜，用于在记忆检索时提供静态背景板。"
}
class Eyes:
    def __init__(self):
        print("👁️  [眼睛]: 潜意识内视镜已开启...")

    # 👇 核心改动：统一改名为 scan
    def scan(self, hands=None) -> PerceptionData:
        return PerceptionData(
            url="memory://hippocampus", 
            page_title="长期记忆库", 
            interactable_elements=[{"j_id": "db-1", "type": "database", "text": "高维向量记忆矩阵"}]
        )