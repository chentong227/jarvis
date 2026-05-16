
import os
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "file_operator_hands",
    "description": "高度泛化的底层文件操作工具。盲操读写本地文件/读取目录列表，无需打开任何UI界面。",
}

class Hands:
    def __init__(self):
        self.requires_memory_seal = True 

    def get_instruction_dict(self) -> str:
        return """
        【file_operator_hands】底层文件操作器。绝对禁止瞎猜路径，必须使用绝对路径！包含指令:
        1. "write_file" - 参数 {"path": "绝对路径(如 D:\\a.txt)", "content": "写入内容", "mode": "w(覆盖)或a(追加)"}
        2. "read_file" - 参数 {"path": "绝对路径"}。静默读取纯文本文件内容。
        3. "list_dir" - 参数 {"path": "绝对文件夹路径"}。静默获取目录下的所有文件名。
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        
        try:
            # 兼容处理：将类似 ~/Desktop 的路径转化为真实绝对路径
            raw_path = params.get("path", "")
            target_path = os.path.expandvars(os.path.expanduser(raw_path))
            
            if cmd == "write_file":
                content = params.get("content", "")
                mode = params.get("mode", "w")
                
                # 检查父目录是否存在，如果不存在则坚决报错，绝不越权创建！
                parent_dir = os.path.dirname(os.path.abspath(target_path))
                if not os.path.exists(parent_dir):
                    return ExecutionResult(success=False, msg=f"写入失败：物理路径 '{parent_dir}' 不存在。")
                    
                with open(target_path, mode, encoding="utf-8") as f:
                    f.write(content)
                action_str = "覆盖写入" if mode == "w" else "追加写入"
                return ExecutionResult(success=True, msg=f"成功对 '{target_path}' 进行了{action_str}。")
                
            elif cmd == "read_file":
                if not os.path.exists(target_path):
                    return ExecutionResult(success=False, msg=f"读取失败：文件 '{target_path}' 不存在。")
                with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                    # 为了防止塞爆大模型上下文，最多只读取前 3000 个字符
                    text = f.read(3000) 
                return ExecutionResult(success=True, msg=f"文件内容前 3000 字如下:\n{text}")
                
            elif cmd == "list_dir":
                if not os.path.exists(target_path):
                    return ExecutionResult(success=False, msg=f"扫描失败：目录 '{target_path}' 不存在。")
                files = os.listdir(target_path)
                return ExecutionResult(success=True, msg=f"目录 '{target_path}' 下的文件有:\n{', '.join(files[:50])}")
                
            else:
                return ExecutionResult(success=False, msg=f"未知的泛化指令: {cmd}")
        except Exception as e:
            return ExecutionResult(success=False, msg=f"底层 OS 操作异常: {e}")
