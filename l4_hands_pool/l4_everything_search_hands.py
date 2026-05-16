
import subprocess
import shutil
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "everything_search_hands",
    "description": "极其快速的全盘文件/文件夹绝对路径搜寻器。底层基于 Everything CLI (es.exe)。",
}

class Hands:
    def __init__(self):
        self.requires_memory_seal = False 
        self.es_path = shutil.which("es")

    def get_instruction_dict(self) -> str:
        return """
        【everything_search_hands】全盘路径嗅探器。用于当你不知道某个文件或文件夹的具体物理盘符和绝对路径时，先用它进行盲搜！
        1. "search_path" - 参数 {"keyword": "关键词(如 '微信' 或 '导出视频')", "limit": 10}。将返回最匹配的绝对路径列表。
        """

    def execute(self, action: Action) -> ExecutionResult:
        if not self.es_path:
            return ExecutionResult(success=False, msg="致命错误：系统环境中未安装或未配置 Everything CLI (es.exe)。请先生排查环境变量。")
            
        cmd = action.command
        params = action.params

        if cmd == "search_path":
            keyword = params.get("keyword", "")
            limit = params.get("limit", 10)
            
            try:
                # 调用 es.exe，限制返回数量防止上下文爆炸
                es_cmd = [self.es_path, keyword, "-n", str(limit)]
                res = subprocess.run(es_cmd, capture_output=True, text=True, encoding='gbk', errors='ignore')
                
                if res.returncode == 0 and res.stdout.strip():
                    lines = res.stdout.strip().split('\n')
                    return ExecutionResult(success=True, msg=f"Everything 找到以下 {len(lines)} 个高频匹配绝对路径:\n" + "\n".join(lines))
                else:
                    return ExecutionResult(success=False, msg=f"全盘扫描结束，未找到包含 '{keyword}' 的任何路径。")
            except Exception as e:
                return ExecutionResult(success=False, msg=f"Everything 引擎调用失败: {e}")
        else:
            return ExecutionResult(success=False, msg=f"未知指令: {cmd}")