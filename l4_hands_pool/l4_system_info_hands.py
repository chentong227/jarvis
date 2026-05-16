import ctypes
import os
import time
import subprocess
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "system_info_hands",
    "description": "系统信息探测器。CPU/内存/磁盘/GPU/电池/运行时间/分辨率/外设。纯本地。",
}

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【系统信息探测器 指令字典】：
        1. "cpu": {} — CPU型号/核心数/使用率
        2. "memory": {} — 内存总量/已用/可用
        3. "disk": {"drive": "C:"} — 磁盘空间
        4. "all_disks": {} — 所有磁盘空间
        5. "uptime": {} — 系统运行时间
        6. "resolution": {} — 屏幕分辨率/缩放
        7. "os_info": {} — 操作系统版本
        8. "full_report": {} — 完整系统报告
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "cpu":
                if HAS_PSUTIL:
                    cpu_percent = psutil.cpu_percent(interval=0.5)
                    cpu_count = psutil.cpu_count()
                    freq = psutil.cpu_freq()
                    freq_str = f"{freq.current:.0f}MHz" if freq else "N/A"
                    return ExecutionResult(success=True,
                                           msg=f"CPU: {cpu_count}核 @ {freq_str} | 使用率 {cpu_percent}%",
                                           data={"cores": cpu_count, "usage": cpu_percent, "freq": freq_str})
                return ExecutionResult(success=False, msg="psutil not installed")

            elif cmd == "memory":
                if HAS_PSUTIL:
                    mem = psutil.virtual_memory()
                    total_gb = mem.total / (1024 ** 3)
                    used_gb = mem.used / (1024 ** 3)
                    avail_gb = mem.available / (1024 ** 3)
                    return ExecutionResult(success=True,
                                           msg=f"内存: {used_gb:.1f}/{total_gb:.1f}GB ({mem.percent}%) | 可用 {avail_gb:.1f}GB",
                                           data={"total_gb": round(total_gb, 1), "used_gb": round(used_gb, 1),
                                                 "avail_gb": round(avail_gb, 1), "percent": mem.percent})
                return ExecutionResult(success=False, msg="psutil not installed")

            elif cmd == "disk":
                drive = params.get("drive", "C:")
                if not drive.endswith("\\"):
                    drive += "\\"
                if HAS_PSUTIL:
                    try:
                        usage = psutil.disk_usage(drive)
                        free_gb = usage.free / (1024 ** 3)
                        total_gb = usage.total / (1024 ** 3)
                        return ExecutionResult(success=True,
                                               msg=f"{drive} 磁盘: {usage.percent}% 已用 | {free_gb:.1f}/{total_gb:.1f}GB 可用",
                                               data={"drive": drive, "percent": usage.percent,
                                                     "free_gb": round(free_gb, 1), "total_gb": round(total_gb, 1)})
                    except Exception:
                        return ExecutionResult(success=False, msg=f"无法读取 {drive}")
                return ExecutionResult(success=False, msg="psutil not installed")

            elif cmd == "all_disks":
                if HAS_PSUTIL:
                    parts = psutil.disk_partitions()
                    lines = []
                    data = []
                    for p in parts:
                        try:
                            usage = psutil.disk_usage(p.mountpoint)
                            free_gb = usage.free / (1024 ** 3)
                            total_gb = usage.total / (1024 ** 3)
                            lines.append(f"  {p.device} {p.mountpoint}: {usage.percent}% | {free_gb:.1f}/{total_gb:.1f}GB")
                            data.append({"device": p.device, "mount": p.mountpoint,
                                         "percent": usage.percent, "free_gb": round(free_gb, 1),
                                         "total_gb": round(total_gb, 1)})
                        except Exception:
                            pass
                    return ExecutionResult(success=True, msg="磁盘:\n" + "\n".join(lines), data={"disks": data})
                return ExecutionResult(success=False, msg="psutil not installed")

            elif cmd == "uptime":
                if HAS_PSUTIL:
                    boot = psutil.boot_time()
                    now = time.time()
                    uptime_sec = now - boot
                    d = int(uptime_sec // 86400)
                    h = int((uptime_sec % 86400) // 3600)
                    m = int((uptime_sec % 3600) // 60)
                    boot_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(boot))
                    return ExecutionResult(success=True,
                                           msg=f"运行时间: {d}天{h}小时{m}分钟 | 启动于 {boot_str}",
                                           data={"days": d, "hours": h, "minutes": m, "boot_time": boot_str})
                return ExecutionResult(success=False, msg="psutil not installed")

            elif cmd == "resolution":
                w = user32.GetSystemMetrics(0)
                h = user32.GetSystemMetrics(1)
                try:
                    import ctypes
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
                    scale = ctypes.windll.shcore.GetScaleFactorForDevice(0)
                except Exception:
                    scale = 100
                return ExecutionResult(success=True, msg=f"分辨率: {w}x{h} | 缩放: {scale}%",
                                       data={"width": w, "height": h, "scale": scale})

            elif cmd == "os_info":
                try:
                    import platform
                    os_ver = platform.platform()
                    py_ver = platform.python_version()
                    host = platform.node()
                    return ExecutionResult(success=True,
                                           msg=f"OS: {os_ver}\nPython: {py_ver}\nHost: {host}",
                                           data={"os": os_ver, "python": py_ver, "host": host})
                except Exception as e:
                    return ExecutionResult(success=False, msg=str(e))

            elif cmd == "full_report":
                parts = []
                if HAS_PSUTIL:
                    cpu = psutil.cpu_percent(interval=0.3)
                    mem = psutil.virtual_memory()
                    parts.append(f"CPU: {psutil.cpu_count()}核 @ {cpu}%")
                    parts.append(f"RAM: {mem.used/(1024**3):.1f}/{mem.total/(1024**3):.1f}GB ({mem.percent}%)")
                    for p in psutil.disk_partitions():
                        try:
                            u = psutil.disk_usage(p.mountpoint)
                            parts.append(f"Disk {p.device}: {u.percent}% ({u.free/(1024**3):.1f}GB free)")
                        except Exception:
                            pass
                    boot = psutil.boot_time()
                    uptime = time.time() - boot
                    d = int(uptime // 86400)
                    h = int((uptime % 86400) // 3600)
                    parts.append(f"Uptime: {d}d {h}h")
                w = user32.GetSystemMetrics(0)
                h_s = user32.GetSystemMetrics(1)
                parts.append(f"Screen: {w}x{h_s}")
                return ExecutionResult(success=True, msg="系统报告:\n  " + "\n  ".join(parts),
                                       data={"report": parts})

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"系统信息异常: {str(e)}")