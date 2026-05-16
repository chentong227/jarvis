import io
import base64
from jarvis_blood import PerceptionData

MANIFEST = {
    "name": "vlm_eyes",
    "description": "全视之眼 (像素级物理感知)。用于当用户问“屏幕上是什么”、“这件衣服好看吗”、“报错截图是什么意思”时，直接看物理屏幕。"
}

class Eyes:
    def __init__(self):
        print("👁️ [L2-全视之眼]: 多模态仿生视觉皮层已接入...")

    def scan(self, hands=None) -> PerceptionData:
        try:
            from PIL import ImageGrab
            
            # 物理级屏幕捕获
            img = ImageGrab.grab()
            
            # 压缩尺寸，防止 Base64 撑爆大模型上下文，720p 足够分辨网页和代码了
            img.thumbnail((1280, 720))
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=80)
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return PerceptionData(
                url="screen://physical_monitor",
                page_title="当前屏幕物理快照",
                interactable_elements=[{"type": "info", "text": "全模态图像已捕获。请直接根据你看到的图像内容回答先生的问题。"}],
                image_base64=img_b64
            )
            
        except Exception as e:
            return PerceptionData(
                url="screen://error",
                page_title="视觉捕获失败",
                interactable_elements=[{"type": "error", "text": f"缺少 Pillow 库或无法截屏: {e}"}]
            )