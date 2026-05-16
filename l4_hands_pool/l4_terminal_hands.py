import os
import re
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "terminal_hands",
    "description": "专治【系统能力进化】【编写Python代码生成新器官】。触发条件：当且仅当现有所有器官均无法满足用户需求，必须通过写代码临时造轮子时，方可挂载！",
    "requires_eyes": "terminal_eyes"
}

FORBIDDEN_TOKENS =[
    "os.system", "subprocess", "eval(", "exec(", 
    "shutil.rmtree", "os.remove", "os.removedirs", "os.unlink",
    "format ", "diskpart", "del /", "rm -rf"
]

class Hands:
    def __init__(self):
        print("⚙️[L4-终端手脚]: 自我繁衍与代码锻造炉已点火...")
        self.requires_memory_seal = True  
        self.eyes_pool_dir = "l2_eyes_pool"
        self.hands_pool_dir = "l4_hands_pool"
        os.makedirs(self.eyes_pool_dir, exist_ok=True)
        os.makedirs(self.hands_pool_dir, exist_ok=True)

    def get_instruction_dict(self) -> str:
        return """
        【当前挂载：终端繁衍中心 (L4) 指令字典】：
        1. "forge_organ": {"organ_prefix": "器官英文前缀", "eyes_code": "L2模块代码", "hands_code": "L4模块代码"} 
           <- 【创世指令】：为你自己编写并挂载一个新的器官！
           
        🛠️ 【软件工程与物理痛觉约束】(极其重要生死红线)：
        1. 极度泛化：你编写的器官必须是通用的底层驱动！绝对不允许在代码里硬编码具体的业务路径（如 Desktop）或特定的文件后缀。
        2. 职责单一：一个器官只干一类事。
        3. 严禁捏造虚假路径 (物理痛觉)：在编写文件写入相关的能力时，【绝对不要】使用 os.makedirs(..., exist_ok=True) 强行去创建不存在的父目录！如果目标文件夹不存在，必须原原本本地抛出 Exception 或 FileNotFoundError！这样才能将痛觉反馈给系统，让系统意识到路径错了！
           
        🧬 【必须严格遵循的器官 DNA 泛式 (代码模板)】：
        [L2 Eyes 代码规范]:
        ```python
        from jarvis_blood import PerceptionData
        MANIFEST = {"name": "你的prefix_eyes", "description": "描述它能看到什么"}
        class Eyes:
            def __init__(self): pass
            def scan(self, hands=None) -> PerceptionData:
                return PerceptionData(url="app://xxx", page_title="xxx", interactable_elements=[])
        ```[L4 Hands 代码规范]:
        ```python
        from jarvis_blood import Action, ExecutionResult
        MANIFEST = {"name": "你的prefix_hands", "description": "描述能执行什么", "requires_eyes": "你的prefix_eyes"}
        class Hands:
            def __init__(self):
                self.requires_memory_seal = True
            def get_instruction_dict(self) -> str:
                return '【指令字典】\\n1. "do_something": {"param": "xxx"} <- 说明...'
            def execute(self, action: Action) -> ExecutionResult:
                # 你的物理执行逻辑
                return ExecutionResult(success=False, msg="不支持指令")
        ```
        """

    def _security_scan(self, code_str: str) -> str:
        for token in FORBIDDEN_TOKENS:
            if token in code_str:
                return token
        return ""

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        
        if cmd == "forge_organ":
            prefix = params.get("organ_prefix", "").strip().lower()
            eyes_code = params.get("eyes_code", "")
            hands_code = params.get("hands_code", "")
            
            if not prefix or not eyes_code or not hands_code:
                return ExecutionResult(success=False, msg="繁衍失败：前缀或代码块为空。")

            toxic_token_eyes = self._security_scan(eyes_code)
            toxic_token_hands = self._security_scan(hands_code)
            
            if toxic_token_eyes or toxic_token_hands:
                toxic = toxic_token_eyes or toxic_token_hands
                return ExecutionResult(
                    success=False, 
                    msg=f"🚨[底层物理熔断] 你的代码包含了绝对禁用的高危词汇[{toxic}]！系统已切断供电。"
                )

            eyes_path = os.path.join(self.eyes_pool_dir, f"l2_{prefix}_eyes_generated.py")
            hands_path = os.path.join(self.hands_pool_dir, f"l4_{prefix}_hands_generated.py")
            
            try:
                with open(eyes_path, "w", encoding="utf-8") as f:
                    f.write(eyes_code)
                with open(hands_path, "w", encoding="utf-8") as f:
                    f.write(hands_code)
                    
                msg = f"✨ [繁衍成功] 已成功铸造新器官！L2 视觉皮层: {eyes_path} | L4 运动神经: {hands_path}。\n💡 提示：物理文件已落盘！中枢神经将在下一个阶段开始时自动热重载。请立刻调用 finish 指令结束当前阶段！"
                return ExecutionResult(success=True, msg=msg, data={"suggested_model": "flash"})
            
            except Exception as e:
                return ExecutionResult(success=False, msg=f"写入异常: {str(e)}")
        else:
            return ExecutionResult(success=False, msg=f"不支持的指令: {cmd}")