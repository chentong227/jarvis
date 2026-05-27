import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
from jarvis_blood import Action, ExecutionResult
from jarvis_hippocampus import Hippocampus

MANIFEST = {
    "name": "memory_hands",
    "description": "长期记忆与日程管理器。专用于检索过去的记忆、查看未来的日程，以及修改/取消已有记录。",
}


# 🆕 [Sir 2026-05-27 18:14 真测 anchor BUG-C] 自然语言时间 parser
# ============================================================
# Sir 真测: 主脑 emit trigger_time='tomorrow' / 'tomorrow 08:00' / '明天' →
# add_reminder 旧版只接 'YYYY-MM-DD HH:MM:SS' 严格格式 → fail → Jarvis 嘴
# 上承诺 reminder 但没真存 → 准则 5 INTEGRITY 失败. 治本: tool 入口 fallback
# parse 自然语言. 准则 6 信任 LLM emit 自然词, python 兜底.
# ============================================================
_DEFAULT_HOUR_BY_DAYTIME = {
    'morning': 8, 'noon': 12, 'afternoon': 14, 'evening': 19, 'night': 21,
    '早上': 8, '早晨': 8, '上午': 9, '中午': 12, '下午': 14,
    '傍晚': 18, '晚上': 21, '深夜': 23,
}


def _parse_trigger_time(
    raw: str, now_ts: Optional[float] = None
) -> Tuple[Optional[float], str]:
    """parse 多种自然语言时间到 timestamp.

    Returns:
        (trigger_ts, normalized_str). 失败返 (None, '').
    """
    if not raw or not isinstance(raw, str):
        return (None, '')
    s = raw.strip()
    if not s:
        return (None, '')
    now = now_ts if now_ts is not None else time.time()
    now_dt = datetime.fromtimestamp(now)

    # 1. 严格格式 YYYY-MM-DD HH:MM:SS
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M:%S',
                '%Y/%m/%d %H:%M'):
        try:
            ts = time.mktime(time.strptime(s, fmt))
            return (ts, time.strftime('%Y-%m-%d %H:%M:00', time.localtime(ts)))
        except Exception:
            pass

    s_low = s.lower().strip()

    # 2. relative: 'in N hours/minutes/days'
    m = re.match(r'^in\s+(\d+)\s*(hour|hr|h|minute|min|m|day|d)s?\b', s_low)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta_sec = {'hour': 3600, 'hr': 3600, 'h': 3600,
                     'minute': 60, 'min': 60, 'm': 60,
                     'day': 86400, 'd': 86400}.get(unit, 0)
        if delta_sec > 0:
            ts = now + n * delta_sec
            return (ts, time.strftime('%Y-%m-%d %H:%M:00', time.localtime(ts)))

    # 3. 中文 'N 小时后' / 'N 分钟后' / 'N 天后'
    m = re.match(r'^(\d+)\s*(小时|分钟|天)后', s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta_sec = {'小时': 3600, '分钟': 60, '天': 86400}.get(unit, 0)
        if delta_sec > 0:
            ts = now + n * delta_sec
            return (ts, time.strftime('%Y-%m-%d %H:%M:00', time.localtime(ts)))

    # 4. 'tomorrow' / 'today' / '明天' / '今天' + optional time
    date_word = None
    rest = s_low
    night_context = False  # 'tonight' / '今晚' / '明晚' → hh < 12 推 PM
    if s_low.startswith('tomorrow'):
        date_word = 'tomorrow'
        rest = s_low[len('tomorrow'):].strip(' ,')
    elif s_low.startswith('today'):
        date_word = 'today'
        rest = s_low[len('today'):].strip(' ,')
    elif s_low.startswith('tonight'):
        date_word = 'today'
        rest = (s_low[len('tonight'):].strip(' ,') or 'night')
        night_context = True
    elif s.startswith('明天'):
        date_word = 'tomorrow'
        rest = s[len('明天'):].strip(' ,，')
    elif s.startswith('今天'):
        date_word = 'today'
        rest = s[len('今天'):].strip(' ,，')
    elif s.startswith('今晚'):
        date_word = 'today'
        rest = (s[len('今晚'):].strip(' ,，') or '晚上')
        night_context = True
    elif s.startswith('明晚'):
        date_word = 'tomorrow'
        rest = (s[len('明晚'):].strip(' ,，') or '晚上')
        night_context = True

    if date_word:
        # 目标 date
        if date_word == 'today':
            target_date = now_dt.date()
        else:  # tomorrow
            target_date = (now_dt + timedelta(days=1)).date()
        # parse rest into HH, MM
        hh, mm = _parse_clock(rest)
        if hh is None:
            # 默认: tomorrow → 08:00, today → next quarter hour
            if date_word == 'tomorrow':
                # night_context = '明晚' 无具体时间 → 21:00
                hh, mm = (21, 0) if night_context else (8, 0)
            else:
                # today 没说几点 → 当前 +1h 整点 (night_context → 21:00)
                if night_context:
                    hh, mm = 21, 0
                else:
                    target_dt = now_dt + timedelta(hours=1)
                    hh, mm = target_dt.hour, 0
        elif night_context and 1 <= hh < 12:
            # '今晚 9 点' → 21 (PM 推断)
            hh += 12
        try:
            target_dt = datetime(target_date.year, target_date.month,
                                  target_date.day, hh, mm, 0)
            ts = target_dt.timestamp()
            # 防御: today 但已过点 → 推 tomorrow
            if date_word == 'today' and ts <= now:
                target_dt = target_dt + timedelta(days=1)
                ts = target_dt.timestamp()
            return (ts, time.strftime('%Y-%m-%d %H:%M:00', time.localtime(ts)))
        except Exception:
            return (None, '')

    return (None, '')


def _parse_clock(s: str) -> Tuple[Optional[int], Optional[int]]:
    """parse 'HH:MM' / '8am' / '8:30' / '8 点 30 分' / 'morning' / '早上' 等.

    Returns (hh, mm). 失败 returns (None, None).
    """
    if not s:
        return (None, None)
    s_low = s.lower().strip()
    # daytime word: morning/晚上 → default hour
    for word, hh in _DEFAULT_HOUR_BY_DAYTIME.items():
        if word in s_low or word in s:
            # word + optional 几点
            rest = s_low.replace(word, '').strip() or s.replace(word, '').strip()
            m = re.search(r'(\d{1,2})', rest)
            if m:
                h_try = int(m.group(1))
                # 中文常 12h: 早上8 / 晚上 9 → 21
                if 1 <= h_try <= 12 and word in ('evening', 'night', '晚上', '深夜', '傍晚'):
                    h_try = h_try + 12 if h_try < 12 else h_try
                return (h_try, 0)
            return (hh, 0)
    # HH:MM
    m = re.match(r'^(\d{1,2}):(\d{2})(?:am|pm)?$', s_low)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 'pm' in s_low and hh < 12:
            hh += 12
        if 'am' in s_low and hh == 12:
            hh = 0
        return (hh, mm)
    # 8am / 8pm / at 8 / 8 点 / 8 点 30 分
    m = re.match(r'^(?:at\s+)?(\d{1,2})\s*(am|pm)?$', s_low)
    if m:
        hh = int(m.group(1))
        if m.group(2) == 'pm' and hh < 12:
            hh += 12
        if m.group(2) == 'am' and hh == 12:
            hh = 0
        return (hh, 0)
    m = re.match(r'^(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?', s)
    if m:
        return (int(m.group(1)), int(m.group(2) or 0))
    return (None, None)

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
        4. "modify_record": {"id": 12, "new_intent": "新的内容(可选)", "new_time": "时间(可选)"} <- 修改已有日程的时间或内容。
        5. "add_reminder": {"intent": "提醒内容", "trigger_time": "时间"} <- 创建新的未来提醒/待办事项。仅在用户明确要求设置提醒时使用！
           ↳ trigger_time 接受多种格式 (Sir 2026-05-27 BUG-C 治本): "YYYY-MM-DD HH:MM:00" 严格 / "tomorrow 08:00" / "tomorrow morning" / "明天早上" / "明天 8 点" / "今晚 9 点" / "in 2 hours" / "3 小时后" 都自动 parse.
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
                    # 🆕 [Sir 2026-05-27 18:14 真测 anchor BUG-C 治本] 同 add_reminder 用 _parse_trigger_time
                    trigger_ts, _normalized = _parse_trigger_time(new_time)
                    if trigger_ts is None:
                        conn.close()
                        return ExecutionResult(
                            success=False,
                            msg=(
                                f"❌ new_time 无法解析: '{new_time}'. "
                                f"接受 'YYYY-MM-DD HH:MM:00' / 'tomorrow 08:00' / "
                                f"'明天早上' / 'in 2 hours' / '3 小时后' 等."
                            ),
                        )
                    updates.append("trigger_time = ?")
                    vals.append(trigger_ts)
                    # 既然修改了时间，确保它被激活为未来任务
                    updates.append("is_future_task = 1")
                        
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
                            "Sir 答了再 emit, 用 trigger_time='YYYY-MM-DD HH:MM:00' 格式 "
                            "或自然语言 'tomorrow 08:00' / '明天早上' / 'in 2 hours' 都接受."
                        ),
                    )
                # 🆕 [Sir 2026-05-27 18:14 真测 anchor BUG-C 治本] 自然语言 fallback
                # 老版只接 'YYYY-MM-DD HH:MM:SS' 严格格式. Sir 真测主脑 emit 'tomorrow'
                # 类自然词 → fail → Jarvis 嘴上说"shall set"但 reminder 没存 →
                # 准则 5 INTEGRITY 失败. 治本 _parse_trigger_time fallback.
                trigger_ts, normalized = _parse_trigger_time(trigger_time_str)
                if trigger_ts is None:
                    return ExecutionResult(
                        success=False,
                        msg=(
                            f"❌ trigger_time 无法解析: '{trigger_time_str}'. "
                            f"接受格式: 'YYYY-MM-DD HH:MM:00' / 'tomorrow 08:00' / "
                            f"'明天早上' / 'in 2 hours' / '3 小时后' / '今晚 9 点' 等. "
                            f"下一轮请 emit 标准格式或常见自然语言."
                        ),
                    )
                trigger_time_str = normalized  # 给下方 msg 显标准化后的时间
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