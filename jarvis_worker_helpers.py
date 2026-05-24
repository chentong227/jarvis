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
