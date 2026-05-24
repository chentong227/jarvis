import time
from jarvis_blood import Action, ExecutionResult
from jarvis_hippocampus import Hippocampus

MANIFEST = {
    "name": "memory_hands",
    "description": "长期记忆与日程管理器。专用于检索过去的记忆、查看未来的日程，以及修改/取消已有记录。",
}

class Hands:
    def __init__(self, api_key="sk-or-v1-xxxxxxxxxxxx"):
        self.requires_memory_seal = False  
        self.api_key = api_key
        self.hippocampus = Hippocampus()

    def get_instruction_dict(self) -> str:
        return """
        【memory_hands】长期记忆与日程管理 (读/写/改/删):
        🚫 排斥禁区：本工具只操作【数据库中的记忆/日程记录】！【绝对禁止】用于搜索物理硬盘上的文件！找文件请用 system_hands.search_file 或 everything_search_hands.search_path！
        可用指令：
        1. "search_memory": {"query": "关键词", "time_range_hours": 72} <- 模糊检索【数据库中的】过去的聊天/任务。NOT for physical files!
        2. "list_reminders": {} <- 查看当前所有已记录的【未来待办/日程】。
        3. "delete_record": {"id": 12} <- 删除/取消指定的【数据库】记忆或日程。NOT for deleting physical files!
        4. "modify_record": {"id": 12, "new_intent": "新的内容(可选)", "new_time": "YYYY-MM-DD HH:MM:00 (可选)"} <- 修改已有日程的时间或内容。
        5. "add_reminder": {"intent": "提醒内容", "trigger_time": "YYYY-MM-DD HH:MM:00"} <- 创建新的未来提醒/待办事项。仅在用户明确要求设置提醒时使用！
        6. "list_commitments": {"max_age_hours": 48} <- 查 CommitmentWatcher 注册的承诺. 含真实 created_at 时间 (诚实接口, 避免编造时间幻觉). 用于回答 "你什么时候记下的承诺" / "我承诺过什么".
        """

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        
        try:
            if cmd == "search_memory":
                query = params.get("query", "")
                time_range = params.get("time_range_hours")
                time_limit = 0.0
                if time_range:
                    try: time_limit = time.time() - float(time_range) * 3600
                    except: pass
                
                results = self.hippocampus.search_memory(self.api_key, query, time_limit=time_limit)
                if not results:
                    return ExecutionResult(success=True, msg="记忆库中未找到相关记录。")
                
                mem_str = "\n".join([f"- [ID: {r['id']}] 意图: {r['intent']} | 结果: {r['summary']}" for r in results])
                return ExecutionResult(success=True, msg=f"找到以下记录：\n{mem_str}")
                
            elif cmd == "list_reminders":
                # 绕过向量搜索，直接进行精准的 SQL 日程提取
                conn = self.hippocampus._get_conn()
                cursor = conn.cursor()
                cursor.execute("SELECT id, user_intent, trigger_time FROM TaskMemories WHERE is_future_task = 1 AND is_deleted = 0")
                rows = cursor.fetchall()
                conn.close()
                
                if not rows:
                    return ExecutionResult(success=True, msg="当前没有任何待触发的未来提醒或日程。")
                    
                reminders_str = "\n".join([f"-[任务ID: {r[0]}] 触发时间: {time.strftime('%Y-%m-%d %H:%M', time.localtime(r[2])) if r[2]>0 else '未知'} | 内容: {r[1]}" for r in rows])
                return ExecutionResult(success=True, msg=f"当前待办日程如下：\n{reminders_str}")
                
            elif cmd == "list_commitments":
                # 🩹 [β.2.8.7 / 2026-05-17] 治 Sir 23:19 实测 LLM 时间幻觉
                # Sir 问 "你什么时候记下的承诺" 主脑没真接口 → 编时间.
                # 此接口直接查 Commitments 表 真 created_at + deadline_ts.
                max_age_h = float(params.get("max_age_hours", 48))
                cutoff = time.time() - max_age_h * 3600
                conn = self.hippocampus._get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, description, deadline_ts, created_at, source_text, "
                    "       nudged, is_deleted "
                    "FROM Commitments WHERE created_at >= ? "
                    "ORDER BY created_at DESC LIMIT 30",
                    (cutoff,)
                )
                rows = cursor.fetchall()
                conn.close()
                if not rows:
                    return ExecutionResult(success=True,
                        msg=f"过去 {max_age_h:.0f}h 内无 Commitment 记录")
                lines = []
                for r in rows:
                    cid, desc, dl, ca, src, ng, isd = r
                    ca_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ca)) if ca else '?'
                    dl_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(dl)) if dl else '?'
                    st = 'NUDGED' if ng else ('DELETED' if isd else 'PENDING')
                    lines.append(
                        f"- [DB#{cid}] {st} 注册于 {ca_str} | deadline={dl_str} | "
                        f"desc='{desc[:60]}' | source='{(src or '')[:60]}'"
                    )
                return ExecutionResult(success=True,
                    msg=f"Commitments (最近 {max_age_h:.0f}h, {len(rows)} 条):\n" + "\n".join(lines))

            elif cmd == "delete_record":
                record_id = params.get("id")
                if not record_id: return ExecutionResult(success=False, msg="缺少 id 参数。")
                self.hippocampus.delete_memory(record_id)
                return ExecutionResult(success=True, msg=f"记录[ID: {record_id}] 已被成功取消/移入回收站。")
                
            elif cmd == "modify_record":
                record_id = params.get("id")
                new_intent = params.get("new_intent")
                new_time = params.get("new_time")
                
                if not record_id: 
                    return ExecutionResult(success=False, msg="缺少 id 参数。")
                if not new_intent and not new_time:
                    return ExecutionResult(success=False, msg="缺少需要修改的内容或时间。")

                conn = self.hippocampus._get_conn()
                cursor = conn.cursor()
                
                updates = []
                vals =[]
                if new_intent:
                    updates.append("user_intent = ?")
                    vals.append(new_intent)
                if new_time:
                    try:
                        time_struct = time.strptime(new_time, "%Y-%m-%d %H:%M:%S")
                        trigger_ts = time.mktime(time_struct)
                        updates.append("trigger_time = ?")
                        vals.append(trigger_ts)
                        # 既然修改了时间，确保它被激活为未来任务
                        updates.append("is_future_task = 1") 
                    except Exception as e:
                        conn.close()
                        return ExecutionResult(success=False, msg=f"时间格式错误，必须为 YYYY-MM-DD HH:MM:00。错误信息: {e}")
                        
                vals.append(record_id)
                sql = f"UPDATE TaskMemories SET {', '.join(updates)} WHERE id = ?"
                cursor.execute(sql, tuple(vals))
                conn.commit()
                conn.close()
                return ExecutionResult(success=True, msg=f"记录 [ID: {record_id}] 已成功修改。")
                
            elif cmd == "add_reminder":
                intent = params.get("intent", "")
                trigger_time_str = params.get("trigger_time", "")
                # 🆕 [BUG #2 fix / 2026-05-24 19:45] 缺参数 fail-soft msg actionable.
                # 老 msg "缺少 intent 参数" 主脑看了一脸懵, 不知道怎么 self-correct.
                # 新 msg 教主脑下轮: 先问 Sir intent, Sir 答了再 emit FAST_CALL, 不抢发.
                if not intent:
                    return ExecutionResult(
                        success=False,
                        msg=(
                            "❌ add_reminder 缺 intent 参数 (提醒内容). "
                            "你不该在没问 Sir 提醒内容时就发 FAST_CALL. "
                            "下一轮: 先用自然语言问 Sir '需要提醒什么', "
                            "Sir 答了再 emit FAST_CALL[memory_hands/add_reminder] "
                            "并填 intent='Sir 答的内容'."
                        ),
                    )
                if not trigger_time_str:
                    return ExecutionResult(
                        success=False,
                        msg=(
                            "❌ add_reminder 缺 trigger_time 参数 (提醒时间). "
                            "下一轮: 先问 Sir 'X 几点提醒', "
                            "Sir 答了再 emit, 用 trigger_time='YYYY-MM-DD HH:MM:00' 格式."
                        ),
                    )
                try:
                    time_struct = time.strptime(trigger_time_str, "%Y-%m-%d %H:%M:%S")
                    trigger_ts = time.mktime(time_struct)
                except Exception as e:
                    return ExecutionResult(success=False, msg=f"时间格式错误，必须为 YYYY-MM-DD HH:MM:00。错误: {e}")
                # 🩹 [P5-fix-add_reminder / 2026-05-21 10:10] Sir 10:06 真测真报:
                # "NOT NULL constraint failed: TaskMemories.timestamp"
                # TaskMemories schema 要求 timestamp/environment/macro_goal NOT NULL,
                # 老 INSERT 只传 user_intent/trigger_time/is_future_task/is_deleted →
                # 3 列 NOT NULL 没传 → SQLite reject. 提醒功能从某次 schema 升级起就挂了.
                # 修: 创建时刻 = timestamp (now), environment = 'reminder' 标识, macro_goal = intent.
                conn = self.hippocampus._get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO TaskMemories "
                    "(timestamp, environment, user_intent, macro_goal, "
                    " trigger_time, is_future_task, is_deleted) "
                    "VALUES (?, ?, ?, ?, ?, 1, 0)",
                    (
                        time.time(),                  # 创建时刻
                        'reminder',                   # environment 标识 (区分 chat memory)
                        intent,                       # user_intent (提醒内容)
                        f'reminder: {intent[:80]}',   # macro_goal
                        trigger_ts,                   # 触发时刻
                    )
                )
                conn.commit()
                new_id = cursor.lastrowid
                conn.close()
                return ExecutionResult(success=True, msg=f"已创建提醒 [ID: {new_id}]：{intent}，触发时间：{trigger_time_str}")
                
            else:
                return ExecutionResult(success=False, msg=f"记忆肌肉不支持指令: {cmd}")
                
        except Exception as e:
            return ExecutionResult(success=False, msg=f"操作报错: {str(e)}")