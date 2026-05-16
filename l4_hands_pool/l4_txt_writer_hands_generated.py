from jarvis_blood import Action, ExecutionResult
import os

MANIFEST = {
    "name": "txt_writer_hands",
    "description": "专治【后台静默生成txt】【往文件写入/追加纯文本】。触发条件：已知绝对路径且需要落盘记录文字。⚠️排斥禁区：本器官没有GUI界面！如果用户说“打开便签”、“屏幕上留个言”，【绝对禁止】调用我，请立刻挂载 desktop_hands！",
    "requires_eyes": "txt_writer_eyes"
}

class Hands:
    def __init__(self):
        self.requires_memory_seal = True

    def get_instruction_dict(self) -> str:
        return '【指令字典】\n1. "write_text": {"filepath": "绝对或相对路径", "content": "要写入的文本内容", "mode": "w或a(覆盖或追加)"} <- 写入文本文件。'

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        if cmd == "write_text":
            filepath = params.get("filepath")
            content = params.get("content", "")
            mode = params.get("mode", "w")
            if not filepath:
                return ExecutionResult(success=False, msg="缺少filepath参数")
            if mode not in ["w", "a"]:
                return ExecutionResult(success=False, msg="mode必须是w或a")
            
            parent_dir = os.path.dirname(os.path.abspath(filepath))
            if not os.path.exists(parent_dir):
                return ExecutionResult(success=False, msg=f"FileNotFoundError: 父目录不存在 {parent_dir}")
            
            try:
                with open(filepath, mode, encoding="utf-8") as f:
                    f.write(content)
                return ExecutionResult(success=True, msg=f"成功写入文件: {filepath}")
            except Exception as e:
                return ExecutionResult(success=False, msg=f"写入失败: {str(e)}")
        return ExecutionResult(success=False, msg="不支持的指令")
