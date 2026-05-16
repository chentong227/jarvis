import os
import shutil
import subprocess
import time
import json
import threading
import uuid
from send2trash import send2trash  
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "system_hands",
    "description": "专治【Everything文件搜索】【获取绝对路径】【文件移动/复制/目录探测】【向人类提问】。触发条件：寻找文件坐标或管理物理硬盘。⚠️排斥禁区：本器官【没有】向文件内写入文本的能力！写字请挂载 txt_writer_hands！",
    "requires_eyes": "system_eyes"
}

class Hands:
    _global_jobs = {} # 改为类变量，所有实例共享
    _job_lock = threading.Lock()
    
    def __init__(self):
        self.jobs = Hands._global_jobs # 引用全局
        self.requires_memory_seal = True  
        self.config_dir = "jarvis_config"
        os.makedirs(self.config_dir, exist_ok=True)
        self.audit_log_path = os.path.join(self.config_dir, "jarvis_os_audit.log")
        self.landmark_file = os.path.join(self.config_dir, "os_landmarks.json")
        


    def _audit(self, message: str):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
        print(f"[系统审计]: 已记录物理变更 -> {message}")

    def _get_media_duration(self, filepath: str) -> str:
        try:
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in['.mp4', '.mov', '.avi', '.mkv', '.mp3', '.wav']:
                return "非媒体文件"
            cmd =['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
            if result.returncode == 0:
                duration_sec = float(result.stdout.strip())
                m, s = divmod(duration_sec, 60)
                h, m = divmod(m, 60)
                return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
            else:
                return "未检测到 FFmpeg 环境，暂无法读取时长"
        except Exception:
            return "未检测到 FFmpeg 环境，暂无法读取时长"
    
    def _purge_dead_landmark(self, dead_path: str):
        """🧹 自净神经：一旦发现死胡同，立刻从 JSON 中抹除该信标并审计"""
        if not os.path.exists(self.landmark_file): return
        try:
            with open(self.landmark_file, "r", encoding="utf-8") as f:
                landmarks = json.load(f)
            
            # 找出所有指向这个失效路径的别名
            keys_to_del = [k for k, v in landmarks.items() if v == dead_path]
            
            if keys_to_del:
                for k in keys_to_del:
                    del landmarks[k]
                    self._audit(f" 🧹 自动清理失效信标: [{k}] -> 路径已不存在")
                    
                with open(self.landmark_file, "w", encoding="utf-8") as f:
                    json.dump(landmarks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ [信标清理异常]: {e}")

    def get_instruction_dict(self) -> str:
        return """
        【当前挂载：OS 操作系统底层管理 (L4) 指令字典】：
        🚫 排斥禁区：本工具只操作【物理硬盘上的文件和目录】！【绝对禁止】用于搜索/修改数据库中的记忆记录！查记忆请用 memory_hands！
        1. "open_item": {"path": "绝对路径"} 
        2. "close_process": {"process_name": "软件名.exe"} 
        3. "search_file": {"keyword": "关键词", "search_dir": "搜索范围"} <- 搜索【物理硬盘】文件。NOT for database records!
        4. "mark_landmark": {"alias": "别名", "path": "绝对路径"} <- 【信标更新协议】：必须用来覆盖已失效的旧信标！
        5. "list_dir": {"path": "绝对路径"} <- 【目录透视协议】：返回后缀统计以及【具体的文件名称列表】，供你精准确认。
        6. "batch_manage": {"action": "move_batch", "source_dir": "源目录", "destination": "目标目录", "keywords":[".jpg", ".txt"]} 
        7. "manage_file": {"action": "move/copy/mkdir", "source": "源路径", "destination": "目标路径"}
        8. "wait": {"seconds": 2}
        9. "finish": {"message": "给用户的操作汇报", "seal_memory": true}
        10. "delete_file": {"path": "绝对路径"} <- 【高危动作】：移入回收站，接受 L5 审查。NOT for database records!
        11. "get_file_info": {"path": "绝对路径"} 
        12. "submit_batch_job": {"source_dir": "源目录", "destination": "目标目录", "keywords":[".mp4"]} 
        13. "check_job_status": {"job_id": "任务ID"} 
        14. "ask_user": {"question": "你想问的具体问题"} <- 【人类求助协议】：当你发现用户提到的文件名不存在（可能是用户记错了）、或者你遇到了无法通过逻辑自行解决的盲区时，【绝对不要盲猜或死循环】！立即调用此指令向人类发起提问，系统会挂起等待人类解答，拿到回答后再继续推理！
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        
        try:

            if cmd == "wait":
                sec = params.get("seconds", 2)
                time.sleep(sec)
                return ExecutionResult(success=True, msg=f"已原地等待 {sec} 秒", data={"suggested_model": "flash"})
            
            elif cmd == "get_file_info":
                target_path = params.get("path")
                if not target_path or not os.path.exists(target_path):
                    self._purge_dead_landmark(target_path) # 👇 触发自净
                    return ExecutionResult(success=False, msg=f"路径不存在，无法透视: {target_path}。(如果是旧信标，已自动剔除)")
                try:
                    stat = os.stat(target_path)
                    size_mb = stat.st_size / (1024 * 1024)
                    c_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_ctime))
                    m_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                    
                    info_str = f"文件名称: {os.path.basename(target_path)}\n"
                    info_str += f"物理大小: {size_mb:.2f} MB\n"
                    info_str += f"创建时间: {c_time}\n"
                    info_str += f"最后修改: {m_time}\n"
                    
                    duration = self._get_media_duration(target_path)
                    if duration != "非媒体文件":
                        info_str += f"媒体时长: {duration}\n"
                        
                    return ExecutionResult(success=True, msg=f"文件元数据读取成功:\n{info_str}", data={"suggested_model": "flash"})
                except Exception as e:
                    return ExecutionResult(success=False, msg=f"读取元数据失败: {str(e)}")

            elif cmd == "submit_batch_job":
                src_dir = params.get("source_dir")
                dst = params.get("destination")
                keywords = params.get("keywords",[])
                if isinstance(keywords, str): keywords =[keywords]
                
                if not os.path.exists(src_dir): 
                    return ExecutionResult(success=False, msg=f"源目录失效: {src_dir}。请寻找真实路径！")
                    
                job_id = str(uuid.uuid4())[:8]
                
                def background_task(j_id, s_dir, d_dir, kws):
                    with self._job_lock:
                        self.jobs[j_id] = {"status": "Running", "moved": 0, "msg": "正在扫描与搬运中..."}
                    try:
                        os.makedirs(d_dir, exist_ok=True)
                        moved_count = 0
                        for root, dirs, files in os.walk(s_dir):
                            for file in files:
                                if any(kw.lower() in file.lower() for kw in kws):
                                    shutil.move(os.path.join(root, file), os.path.join(d_dir, file))
                                    moved_count += 1
                                    with self._job_lock:
                                        self.jobs[j_id]["moved"] = moved_count
                        
                        with self._job_lock:
                            self.jobs[j_id]["status"] = "Completed"
                            self.jobs[j_id]["msg"] = f"搬运完成，共转移了 {moved_count} 个文件。"
                        self._audit(f" [异步任务 {j_id} 完结]: 成功将 {moved_count} 个文件搬运至 {d_dir}")
                    except Exception as e:
                        with self._job_lock:
                            self.jobs[j_id]["status"] = "Failed"
                            self.jobs[j_id]["msg"] = f"搬运遭遇异常物理阻断: {str(e)}"
                            
                t = threading.Thread(target=background_task, args=(job_id, src_dir, dst, keywords), daemon=True)
                t.start()
                return ExecutionResult(success=True, msg=f"✅ 成功挂载异步搬运任务！Job ID: {job_id}。", data={"suggested_model": "flash"})

            elif cmd == "check_job_status":
                job_id = params.get("job_id")
                with self._job_lock:
                    job_info = self.jobs.get(job_id)
                if not job_info:
                    return ExecutionResult(success=False, msg=f"任务池中未找到指定的 Job ID: {job_id}")
                
                status = job_info["status"]
                moved = job_info["moved"]
                msg = job_info["msg"]
                return ExecutionResult(success=True, msg=f"任务句柄[{job_id}] 状态: {status} | 已搬运: {moved} 个 | 详情: {msg}", data={"suggested_model": "flash"})

            elif cmd == "list_dir":
                target_path = params.get("path")
                if not os.path.exists(target_path):
                    self._purge_dead_landmark(target_path) # 👇 触发自净
                    return ExecutionResult(success=False, msg=f"路径不存在: {target_path}。旧信标已自动剔除，请 search_file 并 mark_landmark。")
                
                files = os.listdir(target_path)
                file_stats = {}
                file_names =[]  # 👇 修复散光眼：新增收集文件名的列表
                
                for f in files:
                    full_path = os.path.join(target_path, f)
                    if os.path.isfile(full_path):
                        ext = os.path.splitext(f)[1].lower() or "无后缀"
                        file_stats[ext] = file_stats.get(ext, 0) + 1
                        file_names.append(f)
                
                stat_str = ", ".join([f"{ext}: {count}个" for ext, count in file_stats.items()])
                
                # 为了防止文件夹里有成千上万个文件撑爆大模型的上下文，做个切片保护
                name_str = ", ".join(file_names[:40]) 
                if len(file_names) > 40:
                    name_str += f" ... (等共 {len(file_names)} 个文件，已折叠)"
                    
                # 既返回统计，也返回具体名字
                return ExecutionResult(
                    success=True, 
                    msg=f"目录扫描完毕。\n【文件格式统计】: {stat_str}\n【具体文件名单】: {name_str}", 
                    data={"suggested_model": "flash"}
                )
            
            elif cmd == "mark_landmark":
                alias = params.get("alias")
                path = params.get("path")
                if not os.path.exists(path): return ExecutionResult(success=False, msg=f"路径不存在: {path}")
                landmarks = {}
                if os.path.exists(self.landmark_file):
                    with open(self.landmark_file, "r", encoding="utf-8") as f: landmarks = json.load(f)
                landmarks[alias] = path
                with open(self.landmark_file, "w", encoding="utf-8") as f: json.dump(landmarks, f, ensure_ascii=False, indent=2)
                self._audit(f" 设立空间信标: [{alias}] -> {path}")
                return ExecutionResult(success=True, msg=f"信标 '{alias}' 设立成功。", data={"suggested_model": "flash"})

            elif cmd == "open_item":
                path = params.get("path")
                if not os.path.exists(path): 
                    self._purge_dead_landmark(path) # 👇 触发自净
                    return ExecutionResult(success=False, msg=f"路径不存在: {path}。(已自动剔除失效信标)")
                os.startfile(path) 
                self._audit(f" 唤醒目标: {path}")
                return ExecutionResult(success=True, msg=f"已成功唤醒并打开: {path}", data={"suggested_model": "flash"})
                
            elif cmd == "close_process":
                proc = params.get("process_name")
                if not proc.endswith(".exe"): proc += ".exe"
                res = subprocess.run(f"taskkill /F /IM {proc}", shell=True, capture_output=True, text=True)
                if res.returncode == 0:
                    self._audit(f" 强制击杀: {proc}")
                    return ExecutionResult(success=True, msg=f"进程已物理抹杀。", data={"suggested_model": "flash"})
                return ExecutionResult(success=False, msg=f"关闭失败: {res.stderr}")

            elif cmd == "search_file":
                keyword = params.get("keyword", "")
                search_dir = params.get("search_dir", "")
                if ";" in search_dir: search_dir = ""
                
                es_path = shutil.which("es")
                if es_path:
                    es_cmd = ["es", keyword]
                    if search_dir: es_cmd.extend(["-path", search_dir])
                    res = subprocess.run(es_cmd, capture_output=True, text=True, encoding='gbk', errors='ignore')
                    if res.returncode == 0 and res.stdout.strip():
                        lines = res.stdout.strip().split('\n')[:15]
                        return ExecutionResult(success=True, msg=f"⚡ Everything 命中:\n{chr(10).join(lines)}", data={"suggested_model": "flash"})
                    return ExecutionResult(success=False, msg=f"Everything 未找到 '{keyword}'。")
                else:
                    if not os.path.exists(search_dir): return ExecutionResult(success=False, msg=f"搜索根目录不存在: {search_dir}")
                    results =[]
                    for root, dirs, files in os.walk(search_dir):
                        if len(results) > 15: break
                        for name in files + dirs:
                            if keyword == "*" or keyword == "" or keyword.lower() in name.lower():
                                results.append(os.path.join(root, name))
                    if results: return ExecutionResult(success=True, msg=f"慢速扫描命中:\n{chr(10).join(results)}", data={"suggested_model": "flash"})
                    return ExecutionResult(success=False, msg=f"未找到匹配项。")

            elif cmd == "batch_manage":
                src_dir = params.get("source_dir")
                dst = params.get("destination")
                keywords = params.get("keywords",[])
                if isinstance(keywords, str): keywords = [keywords] 
                
                if not os.path.exists(src_dir): 
                    return ExecutionResult(success=False, msg=f"源目录失效: {src_dir}。请寻找真实路径！")
                
                os.makedirs(dst, exist_ok=True)
                moved_count = 0
                for root, dirs, files in os.walk(src_dir):
                    for file in files:
                        if any(kw.lower() in file.lower() for kw in keywords):
                            shutil.move(os.path.join(root, file), os.path.join(dst, file))
                            moved_count += 1
                            
                return ExecutionResult(success=True, msg=f"执行完毕：批量移动了 {moved_count} 个文件。", data={"suggested_model": "flash"})
            
            elif cmd == "delete_file":
                target_path = params.get("path")
                if not target_path or not os.path.exists(target_path):
                    return ExecutionResult(success=False, msg=f"路径不存在，无法删除: {target_path}")
                try:
                    send2trash(target_path)
                    self._audit(f" 🗑️ 软删除拦截入库: 已将[{target_path}] 移入回收站")
                    return ExecutionResult(success=True, msg=f"已成功将 {target_path} 移入回收站。")
                except Exception as e:
                    return ExecutionResult(success=False, msg=f"移入回收站失败: {str(e)}")

            elif cmd == "manage_file":
                action_type = params.get("action")
                src = params.get("source", "")
                dst = params.get("destination", "")
                
                if action_type == "delete": return ExecutionResult(success=False, msg="🚨[L5 权限驳回]: manage_file 的删除被封印！请使用专属的 delete_file 指令接受 L5 审查。")
                if action_type in ["move", "copy"] and not os.path.exists(src): return ExecutionResult(success=False, msg=f"源文件不存在: {src}")

                if action_type == "move":
                    shutil.move(src, dst)
                    self._audit(f" 物理移动: [{src}] -> [{dst}]")
                    return ExecutionResult(success=True, msg=f"已移动: {src} -> {dst}")
                elif action_type == "copy":
                    if os.path.isdir(src): shutil.copytree(src, dst)
                    else: shutil.copy2(src, dst)
                    self._audit(f" 物理克隆: [{src}] ->[{dst}]")
                    return ExecutionResult(success=True, msg=f"已复制: {src} -> {dst}")
                elif action_type == "mkdir":
                    target_dir = src if src else dst
                    if not target_dir: return ExecutionResult(success=False, msg="mkdir 失败：未提供有效路径。")
                    
                    parent_dir = os.path.dirname(target_dir)
                    if parent_dir and not os.path.exists(parent_dir):
                        return ExecutionResult(success=False, msg=f" 拒绝执行！父目录不存在:[{parent_dir}]。请先 search_file 找到真实路径！")
                        
                    os.makedirs(target_dir, exist_ok=True)
                    self._audit(f" 建立目录: {target_dir}")
                    return ExecutionResult(success=True, msg=f"成功建立目录: {target_dir}")
                else:
                    return ExecutionResult(success=False, msg=f"不支持的操作: {action_type}")
            else:
                return ExecutionResult(success=False, msg=f"不支持指令: {cmd}")
                
        except Exception as e:
            return ExecutionResult(success=False, msg=f"底层 OS 异常: {str(e)}")