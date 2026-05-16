from playwright.sync_api import sync_playwright
import os
import time
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "web_hands",
    "description": "专治【浏览器行为】【访问URL/B站】【网页元素点击与文本填充】。触发条件：明确需要连接互联网或访问网站时挂载。",
    "requires_eyes": "web_eyes"
}

class Hands:
    def __init__(self, auth_file=os.path.join("jarvis_config", "bilibili_auth.json")):
        print("⚙️ [手脚]: 物理肌肉通电...")
        self.requires_memory_seal = True  
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=False)
        
        # 👇 修改点：读取 jarvis_config 里的 auth 文件
        if os.path.exists(auth_file):
            print("🔑 [Web]: 侦测到本地 Auth 凭证，正在挂载账号状态...")
            self.context = self.browser.new_context(storage_state=auth_file)
        else:
            print("⚠️ [Web]: 未侦测到 Auth 凭证，将以无痕模式启动...")
            self.context = self.browser.new_context()
            
        self.page = self.context.new_page()

    def get_instruction_dict(self) -> str:
        return """
        【当前挂载：网页副交感执行层 (L4) 指令字典】：
        1. "navigate": {"url": "目标网址"} 
        2. "click": {"selector": "[jarvis-id='ID']"}  
        3. "fill_text": {"selector": "[jarvis-id='ID']", "text": "输入内容"}
        4. "upload_file": {"selector": "[jarvis-id='ID']", "file_path": "绝对路径"}
        5. "wait": {"seconds": 2} 
        6. "scroll": {"direction": "down", "distance": 800} <- 【新增】：如果只看到页脚，或需要找底下的内容，用此向下滚动(down/up)。
        7. "finish": {"message": "任务结束", "seal_memory": true}
        
        🛡️ 【网页生存与记忆协议】(极其重要)：
        1. JS 异步渲染等待法则：现代网页大量使用前端动态渲染。如果你执行了 navigate 或 click 之后，下一轮眼睛传回的 elements 是空的，或者没有看到预期元素，【绝对不允许】立刻报错放弃！你【必须】调用 "wait" 指令等待 2-3 秒，让眼睛重新扫描！只有连续 2 次 wait 依然失败，才能放弃。
        2. 知识防污染法则：当你在网页上查阅了大量的资料、规律、新闻后，在调用 finish 时，message 【必须极度压缩】为动作摘要（例如：“为用户查阅了B站热门趋势”），绝对不允许把网页的长篇正文写进 message 污染系统的海马体记忆库！
        """

    def _get_active_page(self):
        return self.context.pages[-1]

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        page = self._get_active_page()
        
        try:
            if cmd == "navigate":
                page.goto(params.get("url"), wait_until="domcontentloaded", timeout=15000)
                return ExecutionResult(success=True, msg=f"成功跳转")
                
            elif cmd == "click":
                selector = params.get("selector")
                page.locator(selector).first.click(timeout=5000)
                return ExecutionResult(success=True, msg=f"点击了 {selector}")
                
            elif cmd == "fill_text":
                selector = params.get("selector")
                page.locator(selector).first.fill(params.get("text"), timeout=5000)
                return ExecutionResult(success=True, msg=f"输入了文本")
            
            elif cmd == "upload_file":
                selector = params.get("selector")
                file_path = params.get("file_path")
                page.locator(selector).set_input_files(file_path, timeout=5000)
                return ExecutionResult(success=True, msg=f"成功将文件挂载至 {selector}")

            elif cmd == "wait":
                sec = params.get("seconds", 2)
                time.sleep(sec)
                return ExecutionResult(
                    success=True, 
                    msg=f"已原地等待 {sec} 秒，请重新观察环境", 
                    data={"suggested_model": "flash"} 
                )
            elif cmd == "scroll":
                direction = params.get("direction", "down")
                dist = params.get("distance", 800)
                # 使用 playwright 的鼠标滚轮 API
                sign = 1 if direction == "down" else -1
                page.mouse.wheel(0, dist * sign)
                time.sleep(1) # 滚动后稍微等待懒加载渲染
                return ExecutionResult(
                    success=True, 
                    msg=f"已向 {direction} 滚动了 {dist} 像素", 
                    data={"suggested_model": "flash"}
                )
            
            else:
                return ExecutionResult(success=False, msg=f"未知的物理指令: {cmd}")
        except Exception as e:
            return ExecutionResult(success=False, msg=f"手脚执行报错: {str(e)}")

    def shutdown(self):
        self.browser.close()
        self.playwright.stop()

    def take_snapshot(self, save_path="memory_snapshot.png") -> str:
        try:
            self._get_active_page().screenshot(path=save_path)
            return save_path
        except Exception as e:
            print(f"⚠️[网页快照失败]: {e}")
            return None
    def __del__(self):
        # 对象被垃圾回收时，物理拔管，释放内存
        try:
            if hasattr(self, 'browser'): self.browser.close()
            if hasattr(self, 'playwright'): self.playwright.stop()
        except:
            pass