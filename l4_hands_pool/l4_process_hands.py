import ctypes
import subprocess
import os
from jarvis_blood import Action, ExecutionResult

# [P0+18-b.8 / 2026-05-15] fuzzy fallback —— NotFound 时返候选给主脑反向问 Sir
try:
    from jarvis_fuzzy_resolver import (
        fuzzy_resolve_entity,
        get_running_process_names,
        format_fuzzy_candidates_for_msg,
    )
    _HAS_FUZZY = True
except Exception:
    _HAS_FUZZY = False


def _fuzzy_fallback_result(query: str, base_msg: str) -> 'ExecutionResult':
    """统一封装：NotFound 时拉所有进程做 fuzzy → 命中候选则附带返回。
    无候选 / 模块未加载 → 退化为原始 base_msg。"""
    if not _HAS_FUZZY or not query:
        return ExecutionResult(success=False, msg=base_msg)
    try:
        cands = fuzzy_resolve_entity(query, get_running_process_names(),
                                     top_k=5, min_similarity=0.55)
    except Exception:
        cands = []
    if not cands:
        return ExecutionResult(success=False, msg=base_msg)
    fuzzy_text = format_fuzzy_candidates_for_msg(cands, query=query)
    return ExecutionResult(
        success=False,
        msg=f"{base_msg}\n{fuzzy_text}",
        data={"fuzzy_candidates": [
            {"name": c, "score": float(s)} for c, s in cands
        ]},
    )

MANIFEST = {
    "name": "process_hands",
    "description": "进程管理器。列举/查找/终止/启动/聚焦进程，获取CPU/内存占用。纯本地。",
    # [P0+18-a.16 / 2026-05-15] capability honesty —— Sir 的"承诺必行"硬约束
    # 防止主脑说"我能用 process_hands.get_process_info 来查日志/异常/UI 失败原因"
    # 这种越界许诺（详见 jarvis_skill_registry.CapabilityClaimValidator 注释）。
    #
    # provides:        这个 command 真实能输出的信息域（小写关键词）
    # cannot_provide:  显式禁止承诺的信息域（小写关键词；可含下划线，Validator 会容错空格/横杠）
    "command_provides": {
        "list_processes":    ["pid", "process_name", "memory", "cpu", "process_list"],
        "find_process":      ["pid", "process_name", "executable_path", "memory"],
        "kill_process":      ["termination_result"],
        "kill_by_name":      ["termination_count"],
        "focus_process":     ["window_focused"],
        "get_process_info":  ["pid", "process_name", "cpu", "memory", "executable_path",
                              "create_time", "is_running"],
        "start_process":     ["pid", "process_started"],
        "is_running":        ["is_running", "pid"],
        "wait_for_process":  ["pid", "wait_elapsed"],
        "get_top_cpu":       ["pid", "process_name", "cpu"],
    },
    "command_cannot_provide": {
        # 通用：所有进程类工具都不能读应用内部状态
        "_shared_": [
            "logged_errors", "application_logs", "internal_logs", "log_file",
            "js_exceptions", "javascript_errors", "render_errors", "renderer_state",
            "ui_errors", "ui_state", "dialog_state", "window_content",
            "csp_violations", "trusted_types_violation", "stack_trace",
            "why_app_fails", "why_application_fails", "blank_screen_cause",
            "visual_hang", "rendering_failure", "unhandled_exception",
            "internal_application_state", "application_state",
            "devtools_console", "console_errors", "browser_console",
            "configuration_errors", "extension_errors", "plugin_errors",
        ],
        # get_process_info 是本次 bug 实际触发点 — 显式重申
        "get_process_info": [
            "logged_errors", "application_logs", "js_exceptions", "render_errors",
            "csp_violations", "ui_errors", "why_app_fails", "blank_screen_cause",
            "visual_hang", "internal_application_state", "devtools_console",
        ],
    },
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

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
        【进程管理器 指令字典】：
        1. "list_processes": {"filter": "可选名称过滤", "top": 20} — 列举进程(按内存排序)
        2. "find_process": {"name": "chrome"} — 查找进程
        3. "kill_process": {"name": "notepad", "pid": 可选} — 终止进程
        4. "kill_by_name": {"name": "notepad"} — 按名称终止所有匹配进程
        5. "focus_process": {"name": "chrome"} — 聚焦进程主窗口
        6. "get_process_info": {"name": "chrome", "pid": 可选} — 获取进程详情(CPU/内存/路径)
        7. "start_process": {"path": "C:\\path\\app.exe", "args": "可选参数"} — 启动进程
        8. "is_running": {"name": "chrome"} — 检查进程是否在运行
        9. "wait_for_process": {"name": "chrome", "timeout": 30} — 等待进程启动
        10. "get_top_cpu": {"top": 5} — 获取CPU占用最高的进程
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        if not HAS_PSUTIL:
            return ExecutionResult(success=False, msg="psutil not installed. Run: pip install psutil")

        try:
            if cmd == "list_processes":
                name_filter = (params.get("filter") or "").lower()
                top = params.get("top", 20)
                procs = []
                for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
                    try:
                        info = p.info
                        if name_filter and name_filter not in (info['name'] or '').lower():
                            continue
                        mem_mb = (info['memory_info'] or psutil._common.smem(0, 0, 0, 0, 0, 0)).rss / 1024 / 1024
                        procs.append((info['pid'], info['name'], mem_mb, info['cpu_percent'] or 0))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                procs.sort(key=lambda x: x[2], reverse=True)
                procs = procs[:top]
                lines = [f"  PID {p[0]:6d} | {p[3]:5.1f}% CPU | {p[2]:7.1f} MB | {p[1]}" for p in procs]
                return ExecutionResult(success=True, msg=f"进程列表 (Top {len(procs)}):\n" + "\n".join(lines),
                                       data={"processes": [{"pid": p[0], "name": p[1], "mem_mb": round(p[2], 1),
                                                            "cpu": round(p[3], 1)} for p in procs]})

            elif cmd == "find_process":
                name = (params.get("name") or "").lower()
                results = []
                for p in psutil.process_iter(['pid', 'name', 'exe', 'memory_info']):
                    try:
                        if name in (p.info['name'] or '').lower():
                            mem = (p.info['memory_info'] or psutil._common.smem(0, 0, 0, 0, 0, 0)).rss / 1024 / 1024
                            results.append({"pid": p.info['pid'], "name": p.info['name'],
                                            "exe": p.info['exe'] or '', "mem_mb": round(mem, 1)})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if results:
                    lines = [f"  PID {r['pid']} | {r['mem_mb']:.1f}MB | {r['exe']}" for r in results]
                    return ExecutionResult(success=True, msg=f"找到 {len(results)} 个进程:\n" + "\n".join(lines),
                                           data={"processes": results})
                # [P0+18-b.8] NotFound → fuzzy fallback
                return _fuzzy_fallback_result(name, base_msg=f"未找到进程: {name}")

            elif cmd == "kill_process":
                pid = params.get("pid")
                name = params.get("name")
                killed = False
                if pid:
                    try:
                        p = psutil.Process(pid)
                        p.terminate()
                        killed = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                elif name:
                    name_lower = name.lower()
                    for p in psutil.process_iter(['pid', 'name']):
                        try:
                            if name_lower in (p.info['name'] or '').lower():
                                p.terminate()
                                killed = True
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                if killed:
                    return ExecutionResult(success=True, msg=f"进程已终止: {name or pid}")
                # [P0+18-b.8] 按名字 kill 但没找到 → fuzzy fallback（按 pid 不做 fuzzy）
                if name:
                    return _fuzzy_fallback_result(name, base_msg=f"进程未找到: {name}")
                return ExecutionResult(success=False, msg=f"进程未找到: {pid}")

            elif cmd == "kill_by_name":
                name = (params.get("name") or "").lower()
                count = 0
                for p in psutil.process_iter(['pid', 'name']):
                    try:
                        if name in (p.info['name'] or '').lower():
                            p.terminate()
                            count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if count > 0:
                    return ExecutionResult(success=True, msg=f"已终止 {count} 个 {name} 进程")
                # [P0+18-b.8] 没匹配任何进程 → fuzzy fallback
                return _fuzzy_fallback_result(params.get("name") or name,
                                              base_msg=f"已终止 0 个 {name} 进程")

            elif cmd == "focus_process":
                name = (params.get("name") or "").lower()
                found_hwnd = None

                def enum_cb(h, lparam):
                    nonlocal found_hwnd
                    try:
                        pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                        p = psutil.Process(pid.value)
                        if name in (p.name() or '').lower():
                            found_hwnd = h
                            return False
                    except Exception:
                        pass
                    return True

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
                user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
                if found_hwnd:
                    user32.ShowWindow(found_hwnd, 9)
                    user32.SetForegroundWindow(found_hwnd)
                    return ExecutionResult(success=True, msg=f"已聚焦: {name}")
                # [P0+18-b.8] 找不到对应窗口 → fuzzy fallback
                return _fuzzy_fallback_result(name, base_msg=f"未找到窗口: {name}")

            elif cmd == "get_process_info":
                pid = params.get("pid")
                name = params.get("name")
                target = None
                if pid:
                    try:
                        target = psutil.Process(pid)
                    except psutil.NoSuchProcess:
                        return ExecutionResult(success=False, msg=f"进程不存在: PID {pid}")
                elif name:
                    name_lower = name.lower()
                    for p in psutil.process_iter(['pid', 'name']):
                        try:
                            if name_lower in (p.info['name'] or '').lower():
                                target = p
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                if target is None:
                    # [P0+18-b.8] NotFound → fuzzy fallback（仅在按 name 查时）
                    if name:
                        return _fuzzy_fallback_result(name, base_msg=f"未找到进程: {name}")
                    return ExecutionResult(success=False, msg=f"未找到进程: {pid}")
                try:
                    cpu = target.cpu_percent(interval=0.1)
                    mem = target.memory_info().rss / 1024 / 1024
                    exe = target.exe() or ''
                    ctime = target.create_time()
                    import time as _t
                    created = _t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(ctime))
                    return ExecutionResult(success=True,
                                           msg=f"{target.name()} | PID {target.pid} | CPU {cpu:.1f}% | MEM {mem:.1f}MB | 路径 {exe} | 启动 {created}",
                                           data={"pid": target.pid, "name": target.name(), "cpu": cpu,
                                                 "mem_mb": round(mem, 1), "exe": exe, "created": created})
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    return ExecutionResult(success=False, msg=f"获取进程信息失败: {e}")

            elif cmd == "start_process":
                path = params.get("path", "")
                args = params.get("args", "")
                if not path:
                    return ExecutionResult(success=False, msg="缺少 path 参数")
                cmd_line = f'"{path}" {args}'.strip()
                proc = subprocess.Popen(cmd_line, shell=True)
                return ExecutionResult(success=True, msg=f"进程已启动 PID {proc.pid}", data={"pid": proc.pid})

            elif cmd == "is_running":
                name = (params.get("name") or "").lower()
                for p in psutil.process_iter(['name']):
                    try:
                        if name in (p.info['name'] or '').lower():
                            return ExecutionResult(success=True, msg=f"{name} 正在运行",
                                                   data={"running": True, "pid": p.pid})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                return ExecutionResult(success=True, msg=f"{name} 未运行", data={"running": False})

            elif cmd == "wait_for_process":
                name = (params.get("name") or "").lower()
                timeout = params.get("timeout", 30)
                import time as _t
                start = _t.time()
                while _t.time() - start < timeout:
                    for p in psutil.process_iter(['name']):
                        try:
                            if name in (p.info['name'] or '').lower():
                                return ExecutionResult(success=True,
                                                       msg=f"{name} 已启动 PID {p.pid}",
                                                       data={"pid": p.pid, "waited": round(_t.time() - start, 1)})
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    _t.sleep(0.5)
                return ExecutionResult(success=False, msg=f"超时 {timeout}s，{name} 未启动")

            elif cmd == "get_top_cpu":
                top = params.get("top", 5)
                procs = []
                for p in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                    try:
                        cpu = p.info['cpu_percent'] or 0
                        procs.append((p.info['pid'], p.info['name'], cpu))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                procs.sort(key=lambda x: x[2], reverse=True)
                procs = procs[:top]
                lines = [f"  PID {p[0]:6d} | {p[2]:5.1f}% | {p[1]}" for p in procs]
                return ExecutionResult(success=True, msg=f"CPU Top {top}:\n" + "\n".join(lines),
                                       data={"top": [{"pid": p[0], "name": p[1], "cpu": round(p[2], 1)} for p in procs]})

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"进程管理异常: {str(e)}")