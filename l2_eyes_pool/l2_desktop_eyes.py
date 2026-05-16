import uiautomation as auto
from typing import List, Dict, Tuple
from jarvis_blood import PerceptionData
MANIFEST = {
    "name": "desktop_eyes",
    "description": "桌面级战术目镜，用于扫描本地 GUI 句柄树。"
}
class Eyes:
    def __init__(self):
        print("👁️  [眼睛]: 桌面级战术目镜 (UI句柄+OCR融合架构) 初始化...")

    def _calculate_iou(self, boxA: Tuple[int, int, int, int], boxB: Tuple[int, int, int, int]) -> float:
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        if interArea == 0:
            return 0.0

        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        iou = interArea / float(boxAArea + boxBArea - interArea)
        return iou

    def _track_a_uiautomation(self) -> List[Dict]:
        elements = []
        active_window = auto.GetForegroundControl()
        if not active_window:
            return elements

        for control, depth in auto.WalkControl(active_window, maxDepth=4):
            rect = control.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                name = control.Name.strip()
                if name:
                    elements.append({
                        "source": "uiautomation",
                        "tag": control.ControlTypeName,
                        "text": name[:50], 
                        "bbox": (rect.left, rect.top, rect.right, rect.bottom)
                    })
        return elements

    def _track_b_ocr(self) -> List[Dict]:
        return []

    # 👇 核心改动：统一改名为 scan
    def scan(self, hands=None) -> PerceptionData:
        print("👁️  [眼睛]: 正在执行双轨空间扫描...")
        
        track_a_data = self._track_a_uiautomation()
        track_b_data = self._track_b_ocr()
        
        merged_elements = []
        merged_elements.extend(track_a_data)
        
        for ocr_item in track_b_data:
            is_duplicate = False
            for ui_item in merged_elements:
                if self._calculate_iou(ocr_item["bbox"], ui_item["bbox"]) > 0.6:
                    is_duplicate = True
                    break
            if not is_duplicate:
                merged_elements.append(ocr_item)

        final_elements = []
        for index, el in enumerate(merged_elements, start=1):
            j_id = f"j-{index}"
            final_elements.append({
                "j_id": j_id,
                "type": el["tag"],
                "text": el["text"],
                "bbox": el["bbox"]
            })

        active_window_name = auto.GetForegroundControl().Name if auto.GetForegroundControl() else "Unknown Workspace"
        
        return PerceptionData(
            url="desktop://", 
            page_title=active_window_name,
            interactable_elements=final_elements
        )