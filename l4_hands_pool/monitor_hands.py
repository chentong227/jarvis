import psutil
import os
import glob
from jarvis_blood import ExecutionResult

MANIFEST = {
    "name": "monitor_hands",
    "description": "系统状态监控与视觉感知器官。可用于查看磁盘剩余空间、检查特定文件夹内的文件导出/下载状态。"
}

class Hands:
    def __init__(self):
        self.requires_memory_seal = False 

    def get_instruction_dict(self):
        return """
        【monitor_hands】系统状态监控器官，包含以下 command:
        1. "check_disk_space" - 参数 {"drive": "C:"}，检查特定磁盘的可用空间。
        2. "check_ame_export" - 参数 {"folder_path": "D:\\Export"}，检查导出文件夹中是否还有 .tmp 临时文件，评估是否导出完成。
        """

    def execute(self, action) -> ExecutionResult:
        cmd = action.command
        params = action.params

        if cmd == "check_disk_space":
            drive = params.get("drive", "C:")
            try:
                # 为了兼容不同写法，确保带上斜杠
                if not drive.endswith("\\") and not drive.endswith("/"):
                    drive += "\\"
                usage = psutil.disk_usage(drive)
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                percent = usage.percent
                msg = f"{drive} 盘空间: 已用 {percent}%, 剩余 {free_gb:.2f} GB / 总计 {total_gb:.2f} GB"
                return ExecutionResult(success=True, msg=msg, data={"percent": percent, "free_gb": free_gb})
            except Exception as e:
                return ExecutionResult(success=False, msg=f"无法读取磁盘状态: {e}")

        elif cmd == "check_ame_export":
            folder_path = params.get("folder_path", "")
            if not os.path.exists(folder_path):
                return ExecutionResult(success=False, msg=f"目录不存在: {folder_path}")
            try:
                # 寻找未完成的 .tmp 文件 (Adobe Media Encoder 导出时通常会产生)
                tmp_files = glob.glob(os.path.join(folder_path, "*.tmp"))
                mp4_files = glob.glob(os.path.join(folder_path, "*.mp4"))
                
                if tmp_files:
                    return ExecutionResult(success=True, msg=f"导出正在进行中，发现 {len(tmp_files)} 个 .tmp 临时文件。", data={"is_exporting": True})
                else:
                    return ExecutionResult(success=True, msg=f"未发现临时文件，导出大概率已完成。当前目录下有 {len(mp4_files)} 个 .mp4 文件。", data={"is_exporting": False, "mp4_count": len(mp4_files)})
            except Exception as e:
                return ExecutionResult(success=False, msg=f"检查导出文件夹失败: {e}")

        else:
            return ExecutionResult(success=False, msg=f"未知的指令: {cmd}")