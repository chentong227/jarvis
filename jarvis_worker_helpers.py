# -*- coding: utf-8 -*-
"""[Reshape M6.W2 / 2026-05-24 18:00] Worker pure helpers — sanitize_trigger_time + detect_semantic_category.

历史: 同住 jarvis_worker.py (~120 行 module-level pure fn). 抽出来:
  - sanitize_trigger_time — 上游 LLM trigger time 后处理矫正 (P0+20-β.1.2)
  - detect_semantic_category + _SEMANTIC_CATEGORIES — Memory Correction 守卫 (P0+20-β.1.3)

向后兼容: jarvis_worker.py 顶部 re-export 这 2 fn + dict, 老 caller 仍 work.

设计:
  - 纯 fn, 无 self / class state. 极低风险抽出.
  - import: 仅 stdlib (time / re).
  - 0 caller break: jarvis_worker JarvisWorkerThread + scripts/health_check.py + tests 都通过 re-export.
"""
from __future__ import annotations

import re
import time as _t


# 🩹 [P0+20-β.1.2 / 2026-05-16] Sanity check：上游 LLM 给的 trigger_time_str 容易把
# "两点起床" 当 02:00（凌晨）。规则：动词决定时段 + 当前小时兜底。
def sanitize_trigger_time(trigger_time_str: str, intent: str, user_text: str = ""):
    """对 Gatekeeper LLM 给的 trigger_time_str 做后处理矫正。

    返回：(corrected_str, was_corrected_bool, reason_str)
    - corrected_str: "YYYY-MM-DD HH:MM:SS" 或原值
    - was_corrected_bool: 是否做了矫正（用于 bg_log）
    - reason_str: 矫正原因（debug）

    规则：
    1. 起床/wake → 默认 AM (4-11)。若 LLM 给 14:00 + 没有"下午/PM" → 强制改 AM。
    2. 下午/afternoon/PM → 强制 12-23。若 LLM 给凌晨 → 强制 +12。
    3. 凌晨/early morning/AM → 强制 0-6。
    4. 睡觉/sleep + 当前白天 + LLM 给小时落在 4-21 → 推到下一个晚上窗口。
    """
    if not trigger_time_str or len(trigger_time_str) < 16:
        return trigger_time_str, False, ""
    try:
        ts = _t.strptime(trigger_time_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            ts = _t.strptime(trigger_time_str + ":00", "%Y-%m-%d %H:%M:%S")
        except Exception:
            return trigger_time_str, False, "parse_failed"

    intent_l = (intent or "").lower()
    user_l = (user_text or "").lower()
    combined = intent_l + " | " + user_l
    now = _t.localtime()

    has_wake = bool(re.search(r'(起床|醒|wake\s*up|get\s*up|醒来|起来|wake)', combined))
    has_sleep = bool(re.search(r'(睡觉|睡|sleep|bed|rest|休息|躺下|上床)', combined))
    has_pm_marker = bool(re.search(r'(下午|afternoon|p\.?m\.?|傍晚|晚上(?!好)|tonight|evening)', combined))
    has_am_marker = bool(re.search(r'(凌晨|early\s*morning|midnight|a\.?m\.?|早上|清晨|大早)', combined))
    has_tomorrow = bool(re.search(r'(明天|tomorrow|next\s*day|next\s*morning|tmrw)', combined))
    has_today_pm = bool(re.search(r'(今天下午|今下午|this\s*afternoon|today\s*pm)', combined))

    target_hour = ts.tm_hour
    target_min = ts.tm_min
    new_hour = target_hour
    correction_reason = ""

    if has_pm_marker and target_hour < 12:
        new_hour = target_hour + 12
        correction_reason = "pm_marker_force"
    elif has_am_marker and target_hour >= 12:
        new_hour = target_hour - 12
        if new_hour < 0:
            new_hour = 0
        correction_reason = "am_marker_force"
    elif has_wake and not has_pm_marker and target_hour >= 12 and target_hour <= 18:
        new_hour = target_hour - 12
        correction_reason = "wake_verb_force_am"
    elif (has_wake and not has_pm_marker and not has_am_marker and not has_tomorrow
          and target_hour <= 4 and 6 <= now.tm_hour <= 18):
        new_hour = target_hour + 12
        correction_reason = "daytime_wake_force_today_pm"
    elif (has_sleep and not has_am_marker and not has_today_pm
          and 6 <= now.tm_hour <= 21 and 3 <= target_hour <= 11):
        new_hour = target_hour + 12
        correction_reason = "sleep_verb_force_pm_or_night"
    elif (has_sleep and not has_today_pm and not has_am_marker
          and 6 <= now.tm_hour <= 21 and 12 <= target_hour <= 18):
        new_hour = target_hour - 12
        correction_reason = "sleep_verb_force_next_morning"

    if new_hour == target_hour:
        return trigger_time_str, False, ""

    try:
        corrected_struct = (now.tm_year, now.tm_mon, now.tm_mday,
                            new_hour, target_min, 0,
                            now.tm_wday, now.tm_yday, now.tm_isdst)
        corrected_ts = _t.mktime(corrected_struct)
        if has_wake and corrected_ts < _t.time() - 3600:
            corrected_ts += 86400
        elif has_sleep and corrected_ts < _t.time() - 1800:
            corrected_ts += 86400
        elif corrected_ts < _t.time() - 3600:
            corrected_ts += 86400
        corrected_str = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(corrected_ts))
        return corrected_str, True, correction_reason
    except Exception:
        return trigger_time_str, False, "mktime_failed"


# 🩹 [P0+20-β.1.3 / 2026-05-16] 语义类别探测：用于 Memory Correction 守卫。
# 同类（睡眠 ↔ 睡眠）允许替换；不同类（起床 vs 睡觉 / 工作 vs 吃饭）应拒绝替换 → 当
# 作"新记忆"独立保存而不是覆盖。
_SEMANTIC_CATEGORIES = {
    'wake':   [r'起床', r'醒', r'wake', r'get\s*up'],
    'sleep':  [r'睡觉', r'睡了?', r'休息', r'躺下', r'sleep', r'\bbed\b', r'\brest\b', r'nap'],
    'eat':    [r'吃[饭东午晚早]', r'吃午', r'吃晚', r'吃早', r'早餐', r'午餐', r'晚餐', r'宵夜',
               r'lunch', r'dinner', r'breakfast', r'吃药', r'喝水', r'\beat\b', r'\bmeal\b'],
    'work':   [r'工作', r'加班', r'开会', r'meeting', r'写代码', r'编程', r'\bwork\b', r'\bcode\b'],
    'study':  [r'学习', r'做题', r'刷题', r'复习', r'预习', r'study', r'review'],
    'sport':  [r'锻炼', r'健身', r'跑步', r'运动', r'拉伸', r'exercise', r'workout'],
    'video':  [r'剪辑', r'剪视频', r'录视频', r'做视频'],
}


def detect_semantic_category(text: str) -> str:
    """返回文本所属语义类别。无明显类别时返回 'misc'。"""
    if not text:
        return 'misc'
    t = text.lower()
    matched = []
    for cat, patterns in _SEMANTIC_CATEGORIES.items():
        for p in patterns:
            if re.search(p, t):
                matched.append(cat)
                break
    if not matched:
        return 'misc'
    # 如果同时匹配 wake 和 sleep（极少），优先 sleep（场景：睡前定起床闹钟）
    if 'wake' in matched and 'sleep' in matched:
        return 'wake'  # 这种 case 默认走 wake，因为"起床闹钟"语义更强
    return matched[0]


# 🆕 [Reshape M6.W3 / 2026-05-24 18:15] Prompt tier classifier keyword lists
# 抽自 JarvisWorkerThread class attr (~50 行 list 定义). worker class _TIER_*_KEYWORDS
# 改为指向这里的常量, backward compat (老 self._TIER_*_KEYWORDS access 仍 work).
#
# 设计 (准则 6 - 持久化, 但 keyword regex list 留 module const 是 "持久化硬规":
# 这些 regex 是系统级 prompt tier classifier 内核, 不是用户可改的 vocab.
# Sir CLI 改 vocab 用 directives_vocab.json / gaming_vocab.json 等, 不改 tier classifier).

# CRITICAL —— 排期/提醒/记忆同步：永远走全量 prompt
TIER_CRITICAL_KEYWORDS = [
    r'remind\s+me', r'set\s+(an?\s+)?alarm', r'schedule\b', r'wake\s+me\s+up',
    r'cancel.*remind', r'cancel.*alarm',
    r'提醒我', r'闹钟', r'叫醒我', r'定个', r'设个', r'排期', r'取消.*提醒',
    r'at\s+\d', r"\d+\s*o'?clock", r'\d+点',
    r'remember\s+(this|that)', r'记下', r'记住', r'note\s+this',
]

# [R7-β1] FACTUAL_RECALL —— 近期事实查询，答案大概率已在 working_feed / event_bus / STM 里
# 触发要求：必须带"刚 / 最近 / 上一句 / just"这类时间指代 + 一个可被 working_feed 命中的对象
# 优先级高于 TOOL_REQUEST，避免"刚复制的是什么"被误判为"copy 动作 → 调工具"
TIER_FACTUAL_RECALL_KEYWORDS = [
    # 中文：刚/才/最近 + 复制/粘贴/命令/说过/聊
    r'刚(复制|粘贴|说|讲|跑|敲|点|聊|提到)',
    r'(刚才|刚刚|刚)\s*(复制|粘贴|说|讲|跑|敲|点|聊|提到|那个|那段|的)',
    r'(我|你)\s*刚\s*(复制|粘贴|说|讲|跑|敲|点|聊|提到)',
    r'(刚刚|刚才|刚)[^。！？]{0,12}?(剪贴板|粘贴板|命令|对话|话|聊的|说的)',
    r'最近\s*(复制|粘贴|跑|敲|聊|说|提到)',
    r'剪贴板.*内容',
    r'(刚.{0,4}(复制|粘贴).{0,8}内容)',
    # English: just + verb / what did i just / what command did i just run
    r"\b(what|which)(\s+\w+){0,3}\s+(did|do)\s+i\s+(just\s+|recently\s+)?(copy|paste|run|say|type|hit)",
    r"\bdid\s+i\s+just\s+(copy|paste|run|say|type|hit)",
    # "what is on/in the clipboard" / "what's on the clipboard"
    r"\b(what'?s|what\s+is|what\s+are|whats)\s+(on|in)\s+(the\s+)?clipboard\b",
    r"\bclipboard\s+(content|right\s+now|currently)\b",
    r"\bjust\s+(copied|pasted|typed|ran|said|hit)\b",
    r"\bthe\s+thing\s+i\s+just\b",
    r"\brecent(ly)?\s+(copied|ran|typed|pasted|hit)\b",
]

TIER_TOOL_KEYWORDS = [
    # English action verbs
    r'\b(open|close|launch|start|stop|play|pause|resume|skip|next|previous)\b',
    r'\b(search|find|locate|copy|paste|cut|delete|create|make|generate)\b',
    r'\b(set|change|adjust|increase|decrease|raise|lower|mute|unmute)\b',
    r'\b(volume|brightness|wallpaper|theme|notification|wifi|bluetooth)\b',
    r'\b(screenshot|record|capture|save\s+as)\b',
    # 中文动作动词
    '打开', '关闭', '启动', '停止', '播放', '暂停', '继续播放', '下一首', '上一首',
    '搜索', '查找', '复制', '粘贴', '剪切', '删除', '新建', '创建',
    '调到', '调高', '调低', '调成', '调亮', '调暗', '增加', '减少',
    '音量', '亮度', '壁纸', '通知', '截图', '录屏',
]

TIER_DEEP_KEYWORDS = [
    r"\b(remember\s+when|last\s+time|the\s+other\s+day|we\s+talked|we\s+discussed)\b",
    r"\b(what\s+did\s+i|what\s+was\s+i|where\s+was\s+i|how\s+did\s+i)\b",
    r"\bthat\s+(file|bug|error|project|thing|topic|conversation)\b",
    '上次', '上回', '之前', '昨天', '前天', '之前咱们', '咱们聊过', '记得',
    '那个文件', '那个项目', '那个 bug', '那个东西', '那次',
    # [P0+18-a.4 / 2026-05-15] 修 BUG #1: "排查/诊断/分析/帮我看 X" 等动词请求被误归 SHORT_CHAT
    # 这些是典型多步动作（需要先调用查询工具 → 再分析 → 反推），必须升 DEEP_QUERY 让
    # 主脑看到完整 PROMISE_PROTOCOL_DIRECTIVE + AVAILABLE SKILLS，从而写 <PROMISE>
    r"\b(diagnose|analyze|investigate|review|inspect|audit|debug|troubleshoot|figure\s+out|look\s+into|check\s+out)\b",
    r"\bhelp\s+me\s+(see|look|check|find|fix|debug|solve|figure)",
    r"\bwhy\s+(is|does|did|do|are|am)\b.{0,40}(error|fail|bug|issue|problem|wrong|broken)",
    '排查', '诊断', '分析一下', '审一下', '审查', '检查一下', '体检',
    '帮我看', '帮我查', '帮我分析', '帮我排查', '帮我诊断', '帮我审',
    '看一下', '看看为什么', '看看哪里', '看看是不是',
    '为什么', '怎么回事', '是什么原因', '哪里出了',
]


# 🆕 [Reshape M6.W4 / 2026-05-24 18:30] Refusal pattern fallback lists
# (vocab json 不可用时的 fallback, source of truth = memory_pool/refusal_vocab.json,
# CLI: scripts/refusal_vocab_dump.py). worker class attr 用 alias 指向.
#
# 设计 (准则 6 - 持久化硬规): refusal fallback 仅在 vocab json 加载失败时使用,
# 真 source of truth 在 JSON. 此处保 list 是为了 import-safe default.

# 🩹 [β.5.22-F / 2026-05-19] generic refusal — "不需要 / not now / leave it alone"
GENERIC_REFUSAL_PATTERNS = [
    # fallback only — 真 source of truth 在 memory_pool/refusal_vocab.json
    "no thanks", "no thank you", "thanks but no",
    "i'm fine", "im fine", "i am fine", "it's fine", "its fine",
    "i'm ok", "im ok", "i am ok", "it's ok", "its ok",
    "i'm good", "im good", "i am good",
    "i got it", "i've got it", "ive got it",
    "i'll fix", "ill fix", "i will fix", "i can fix",
    "i'll handle", "ill handle", "i will handle",
    "not now", "leave it", "let it be", "forget it",
    "stop offering", "stop suggesting",
    "不需要", "不用", "不必", "没事", "算了", "不用了",
    "我自己", "自己来", "自己能", "我可以", "我能",
    "别再提", "别再说", "够了", "停下", "停止帮助",
    "不需要你的帮助", "不要你的帮助",
]

# 🩹 [β.5.22-F] strong refusal — 显式禁止 (闭嘴 / shut up / leave me alone)
STRONG_REFUSAL_PATTERNS = [
    # fallback only
    "不需要你的帮助", "不要你的帮助", "不要再提", "别再提", "别再说", "别再来",
    "不要打扰", "别打扰", "闭嘴", "安静一下", "停止帮助", "你别说话",
    "stop offering", "stop suggesting", "stop talking", "stop interrupting",
    "leave me alone", "i don't need help", "i don't need your help",
    "i dont need help", "i dont need your help", "shut up", "be quiet",
]


# 🆕 [Reshape M6.W4 / 2026-05-24 18:30] Sleep intent detection patterns
# 抽自 JarvisWorkerThread class attr.

# [v5.1 / Sir-2026-05-15] Sleep Intent 检测 —— 修"重复催睡"
# 起因：Sir 说"I will go to sleep. 我马上回去睡觉，再过半小时左右吧"之后，
# Conductor 仍然在 6 分钟 / 10 分钟 / 14 分钟时连催 late_night / suggest_break 三次。
# 修法：检测 Sir 的睡眠表态 → 设 worker._sleep_intent_until 窗口 → 两个发送端在窗口内
# 静默 sleep 相关 nudge。
SLEEP_INTENT_PATTERNS = [
    # 英文：i'll/i'm gonna/i'm about to/i will go to + sleep/bed; off to bed; turning in
    r"(?:i\s*['\u2019]?\s*ll|i\s+will|i\s*['\u2019]?\s*m\s+(?:gonna|going\s+to|about\s+to|heading))\s+(?:go\s+to\s+)?(?:sleep|bed|hit\s+the\s+sack)",
    r"(?:gonna|going\s+to|off\s+to|heading\s+to|hitting)\s+(?:sleep|bed|the\s+sack)",
    r"(?:going|turning)\s+in\s+(?:now|soon|in\s+a)?",
    r"(?:bedtime|nighty[\s-]?night|good\s*night)",
    # [P0-2 / 2026-05-15] 英文补：i'll sleep at X / i plan to sleep / i'll be in bed by X
    r"(?:i\s*['\u2019]?\s*ll|i\s+(?:plan\s+to|am\s+planning\s+to|intend\s+to))\s+(?:sleep|hit\s+(?:the\s+)?(?:sheets|bed)|be\s+in\s+bed|crash)",
    r"(?:by|at|around|near)\s+\d{1,2}\s*(?:o\'?clock|am|pm|:\d{2})?.{0,20}(?:sleep|bed)",
    # 中文：我...睡 / 我...休息 / 再过...睡 / 准备睡 / 马上去睡 / 我去睡
    r"我.{0,15}(?:就|快|马上|一会儿|过|过\s*会|分钟后|小时后).{0,15}(?:去\s*睡|睡觉|睡了|休息|睡)",
    r"我.{0,8}(?:马上|快|准备|要|打算).{0,8}(?:睡|休息|去睡|睡觉|睡了)",
    r"再过.{0,12}.{0,6}(?:就|).{0,4}(?:睡|休息|睡觉|睡了)",
    r"(?:我)?\s*(?:马上|立刻|准备|打算).{0,4}(?:去睡|睡觉|睡了|休息)",
    r"我\s*(?:要|想|打算)?\s*(?:去|回|回去).{0,4}(?:睡|休息)",
    # [P0-2 / 2026-05-15] 中文补：实测 Sir 说"我会在大概两点的时候睡觉" 未命中。
    # 补"会在/会/打算/差不多 + 点/时/分 + 睡/休息"自然表述；以及"等下/等一下/晚点/迟点 + 睡"
    # 🩹 [β.5.38-fix / 2026-05-20 15:18] Sir 实测 BUG: "今天我我晚上会尽量早点睡的"
    # 老 pattern "点" 误命中"早点睡"的"点". 修法: 排除"早点/晚点/迟点 + 睡" 副词在 (?:点|时|分) 前.
    r"我.{0,8}(?:会|要|得|该|打算|准备|应该|可能|大概|估计|差不多)(?!.{0,3}(?:早|晚|迟)点).{0,15}(?:点|时|分).{0,12}(?:睡|休息|去睡|睡觉|睡了|关机|下线|歇)",
    r"我.{0,8}(?:会|要|得|打算).{0,8}(?:在|于|到了).{0,15}(?:睡|休息|睡觉|睡了|关机|下线|歇)",
    r"(?:等下|等一下|等会|等会儿|晚点|迟点|稍后|过会|过一会|过会儿).{0,10}(?:睡|休息|睡觉|睡了)",
    r"(?:我)?\s*(?:差不多|大概|应该|估计|可能).{0,10}(?:点|时).{0,12}(?:睡|休息|睡觉|睡了)",
    # "今晚"/"今天晚上"/"待会儿" + 睡 / "今晚就/今晚要"
    r"(?:今晚|今天晚上|今夜|待会儿?).{0,10}(?:睡|休息|睡觉|关机|下线|休息)",
]

# 时间提取：捕获"30 分钟" / "half hour" / "一小时" 等。命中越早越具体优先。
SLEEP_TIME_EXTRACTORS = [
    (r"(\d+)\s*(?:分钟|分(?!\w)|min(?:ute)?s?)", lambda m: int(m.group(1)) * 60),
    (r"(\d+)\s*(?:小时|hour|hr)s?", lambda m: int(m.group(1)) * 3600),
    (r"半\s*(?:个)?\s*小时|half\s+(?:an?\s+)?hour", lambda m: 1800),
    (r"一\s*(?:个)?\s*小时|an?\s+hour", lambda m: 3600),
    (r"几\s*分钟|few\s+(?:more\s+)?minutes?", lambda m: 600),
    (r"一会儿|一下|in\s+a\s+bit|in\s+a\s+while|shortly", lambda m: 600),
    (r"马上|立刻|right\s+(?:now|away)|now", lambda m: 300),
    # [P0-2 / 2026-05-15] 补：明确时间点（"两点睡 / 在 2 点睡"）→ 距现在到那个钟点的秒数。
    # 优先处理中文数字"两/三/四/五"，再阿拉伯数字。lambda 接收 match 对象自带 self 隐含 - 这里改成
    # 闭包形式，需要 self 上下文才能调 _to_24h。下方在 _detect_sleep_intent 里单独处理。
]

# 中文数字到阿拉伯：仅覆盖 0-12（够用）
CN_DIGIT_MAP = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '俩': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12,
}
