from playwright.sync_api import Page
from jarvis_blood import PerceptionData
MANIFEST = {
    "name": "web_eyes",
    "description": "网页战术目镜，用于扫描网页 DOM 树结构。"
}
class Eyes:
    def __init__(self):
        print("👁️  [眼睛]: 网页战术目镜初始化...")

    def scan(self, hands) -> PerceptionData:
        page = hands._get_active_page() # 自己向手脚索要网页环境
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass # 咽下超时报错，强行执行后续的 js_code 提取当前能看到的元素
        js_code = """
        () => {
            let items = [];
            let counter = 1;
            document.querySelectorAll('button, a, input, [role="button"]').forEach((el) => {
                const rect = el.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                if (isVisible) {
                    let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '';
                    text = text.trim();
                    if (text.length > 0) {
                        const j_id = `j-${counter}`;
                        el.setAttribute('jarvis-id', j_id);
                        items.push({"j_id": j_id, "tag": el.tagName.toLowerCase(), "text": text.substring(0, 50)});
                        counter++;
                    }
                }
            });
            return items;
        }
        """
        try:
            elements = page.evaluate(js_code)
            return PerceptionData(url=page.url, page_title=page.title(), interactable_elements=elements)
        except Exception as e:
            return PerceptionData(url=page.url, page_title="Error", interactable_elements=[])