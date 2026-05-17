# -*- coding: utf-8 -*-
"""[P0+19-9 / 2026-05-16] Jarvis Worker — PyQt5 主线程 + 语音监听线程

从 jarvis_nerve.py 拆出 2 个超大 QThread 类：
  - VoiceListenThread (658 行) — 麦克风/funasr/唤醒/字幕分发
  - JarvisWorkerThread (2807 行) — 主对话编排 QThread，桥接 UI + ChatBypass + CentralNerve

依赖：
- PyQt5: QThread / pyqtSignal
- speech_recognition / funasr (jarvis_nerve 顶部已 import)
- 所有上游拆完文件 (CentralNerve / ChatBypass / KeyRouter / sentinel / etc)

向后兼容：jarvis_nerve.py 用 `from jarvis_worker import ...` 转发。
"""

from __future__ import annotations

# [P0+19-final fix 4 / 2026-05-16] 一次性补全标准库 + 第三方常用 import（防 NameError 暴露）
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import random  # noqa: F401
import queue  # noqa: F401
import sqlite3  # noqa: F401
import hashlib  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
import importlib  # noqa: F401
import concurrent.futures  # noqa: F401
import multiprocessing  # noqa: F401
from collections import defaultdict, deque  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
try:
    from google.genai import types  # noqa: F401
except ImportError:
    pass


import os
import re
import json
import time
import math
import threading
import queue
import random
import collections
import sqlite3  # noqa: F401
import importlib  # noqa: F401
import io  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional  # noqa: F401

# PyQt5
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt  # noqa: F401
from PyQt5.QtWidgets import QApplication  # noqa: F401

# Windows / Audio / 第三方
import numpy as np  # noqa: F401
import soundfile as sf  # noqa: F401
import win32gui  # noqa: F401
import win32api  # noqa: F401
import win32con  # noqa: F401
import speech_recognition as sr  # noqa: F401
from PIL import ImageGrab, Image  # noqa: F401
from funasr import AutoModel  # noqa: F401
from fuzzywuzzy import fuzz  # noqa: F401
import comtypes  # noqa: F401
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation  # noqa: F401
from google import genai  # noqa: F401
from google.genai import types  # noqa: F401

# Cross-module
from jarvis_safety import *  # noqa: F401, F403
from jarvis_key_router import KeyRouter  # noqa: F401
from jarvis_llm_reflector import LlmReflector  # noqa: F401
from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
from jarvis_sensors import (  # noqa: F401
    SensorFilter, HabitClock, CausalChain, ProjectTimeline,
    SubconsciousMailbox, FunnelLogger,
)
from jarvis_routing import SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard  # noqa: F401
from jarvis_memory_core import (  # noqa: F401
    PromptLayer, PromptCache, CorrectionEntry, CorrectionMemory,
    MemoryFragment, UnifiedMemoryGateway, FeedbackTracker,
    TaskWorkerPool, Anticipator, CorrectionLoop, SleepIntentDetector,
    HumorMemory,
)
from jarvis_sentinels import (  # noqa: F401
    ChronosTick, ChronosSentinel, SystemSentinel, SoulArchivistSentinel,
    NudgeGate, UserStatusLedgerSentinel, ScreenshotSentinel,
    WellnessGuardian, ReflectionScheduler,
)
from jarvis_conductor import Conductor  # noqa: F401
from jarvis_return_sentinel import ReturnSentinel  # noqa: F401
from jarvis_commitment_watcher import CommitmentWatcher  # noqa: F401
from jarvis_smart_nudge import SmartNudgeSentinel  # noqa: F401
from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS  # noqa: F401
from jarvis_central_nerve import CentralNerve, JARVIS_CORE_PERSONA, set_browser_ducking  # [P0+19-final fix 2]
import concurrent.futures  # [P0+19-final fix 3] worker.run 用 ThreadPoolExecutor 跑 Gatekeeper  # noqa: F401

from jarvis_vocal_cord import VocalCord  # noqa: F401
from jarvis_blood import JarvisBlood, ExecutionResult, FeedbackSignal  # noqa: F401
from jarvis_hippocampus import Hippocampus  # noqa: F401
from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401
from l1_right_brain import RightBrain  # noqa: F401
from l3_left_brain import LeftBrain  # noqa: F401
from l5_reflection_brain import ReflectionBrain  # noqa: F401

from jarvis_utils import (  # noqa: F401
    safe_gemini_call, get_local_fallback, safe_openrouter_call,
    QuickClassifier, get_quick_classifier, create_genai_client,
    bg_log, set_conversation_active, is_conversation_active,
    register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
)


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
    import time as _t
    import re as _re
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

    has_wake = bool(_re.search(r'(起床|醒|wake\s*up|get\s*up|醒来|起来|wake)', combined))
    has_sleep = bool(_re.search(r'(睡觉|睡|sleep|bed|rest|休息|躺下|上床)', combined))
    has_pm_marker = bool(_re.search(r'(下午|afternoon|p\.?m\.?|傍晚|晚上(?!好)|tonight|evening)', combined))
    has_am_marker = bool(_re.search(r'(凌晨|early\s*morning|midnight|a\.?m\.?|早上|清晨|大早)', combined))
    has_tomorrow = bool(_re.search(r'(明天|tomorrow|next\s*day|next\s*morning|tmrw)', combined))
    has_today_pm = bool(_re.search(r'(今天下午|今下午|this\s*afternoon|today\s*pm)', combined))

    target_hour = ts.tm_hour
    target_min = ts.tm_min
    new_hour = target_hour
    correction_reason = ""
    add_day = False  # 是否换到下一天

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
    import re as _re
    if not text:
        return 'misc'
    t = text.lower()
    matched = []
    for cat, patterns in _SEMANTIC_CATEGORIES.items():
        for p in patterns:
            if _re.search(p, t):
                matched.append(cat)
                break
    if not matched:
        return 'misc'
    # 如果同时匹配 wake 和 sleep（极少），优先 sleep（场景：睡前定起床闹钟）
    if 'wake' in matched and 'sleep' in matched:
        return 'wake'  # 这种 case 默认走 wake，因为"起床闹钟"语义更强
    return matched[0]


class VoiceListenThread(QThread):
    text_ready = pyqtSignal(str)
    interrupt_signal = pyqtSignal()
    awake_signal = pyqtSignal(bool) 
    
    # [R6/B5] 拆成"硬指令"+"次硬指令"两档：
    # - STRICT_STOP_WORDS: 即便句子稍长（如"你给我闭嘴"）也立刻触发
    # - SOFT_STOP_WORDS:  容易和正常陈述歧义（如"安静"），必须在首位且短句才触发
    # 注意"安静"从硬档移除 —— "外面很安静" 不应误炸为强制停止。
    STRICT_STOP_WORDS = ["停止", "终止", "别弄了", "退下", "闭嘴", "shut up", "stand down"]
    SOFT_STOP_WORDS = ["安静", "shut"]
    # 兼容字段：保持外部访问 STOP_WORDS 的旧调用不挂（合并所有词）
    STOP_WORDS = STRICT_STOP_WORDS + SOFT_STOP_WORDS

    # DISMISS_WORDS 拆成两档：
    # - EXCLUSIVE: 专属告别词，整句出现一次基本就是再见（晚安/再见/goodbye/bye 等）
    # - POLITE:    礼貌词，本身高频出现在非告别语境中（谢谢/thanks）→ 必须整句很短才算告别
    # "stand down" 之前同时挂在 STOP_WORDS 和 DISMISS_WORDS，逻辑上属于强制中断 → 仅留 STOP_WORDS
    DISMISS_EXCLUSIVE = [
        "goodbye", "good night", "bye", "see you", "see you next time",
        "晚安", "再见", "拜拜",
    ]
    DISMISS_POLITE = [
        "thanks", "thank you",
        "谢谢",
    ]
    DISMISS_WORDS = DISMISS_EXCLUSIVE + DISMISS_POLITE  # 兼容旧调用

    DEBUG_ASR = False

    def __init__(self):
        super().__init__()
        self._state_lock = threading.Lock()
        self.is_jarvis_speaking = False
        # [R7-α/B1] in_active_conversation 走 self.state 中央状态机；
        # 但本类在 __init__ 时还没注入 state（state 在 main 里事后绑过来），
        # 所以保留一个 _local_in_active_conv 兜底字段，property 在没 state 时读它。
        self._local_in_active_conv = False
        self.state = None
        self.last_interaction_time = 0
        self.last_user_speech_time = 0
        self.mute_until = 0.0
        self.last_conversation_end_time = 0
        # [R6/B6] 记录上次"对话结束"是什么原因导致的，供 wake_weight 区分误唤醒严重度
        # 取值：'manual_stop'（用户喊停）/ 'manual_dismiss'（告别）/ 'timeout'（超时）/ 'natural'（正常结束）
        self.last_dismissal_reason = None
        self._suppress_wave = False
        # [R7-β5] 共享 subtitle_queue 引用，main 段事后注入（push 'listening_start' / 'listening_done'）
        self._subtitle_queue = None

    def _publish_listening_done(self):
        """[R7-β5] ASR 结果被丢弃（hallucination/too_short/echo）时清掉 Listening… 指示。"""
        try:
            if self._subtitle_queue is not None:
                self._subtitle_queue.put(("listening_done", ""))
        except Exception:
            pass

    # [R7-α/B1] in_active_conversation 通过 property 走 state.active_conversation；
    # state 未注入时退到本地 _local_in_active_conv，保证早期访问（如单元测试）不挂。
    @property
    def in_active_conversation(self) -> bool:
        state = self.state
        if state is None:
            return self._local_in_active_conv
        return state.active_conversation

    @in_active_conversation.setter
    def in_active_conversation(self, value):
        value = bool(value)
        self._local_in_active_conv = value
        state = self.state
        if state is not None:
            state.set_active_conversation(value, reason='legacy_setter', source='VoiceListenThread')

    # [R6/B5] 上下文感知的停止/告别词检测
    # 规则：
    # 1. 整句完全等于关键词 → 一定触发（"闭嘴"、"再见"）
    # 2. 关键词在首 6 个字符内出现 → 触发（短的强制指令）
    # 3. 否则不触发（"现在外面好安静" / "Thanks for that, can you also..."）
    # 这样避免一个无心词把整个会话击碎。
    @staticmethod
    def _phrase_at_head(needle: str, haystack_lower: str, head_chars: int = 6) -> bool:
        """关键词是否出现在 haystack 前 head_chars 字符内，且对英文使用词边界。

        [P0+20-β.2.5 hotfix / 2026-05-17] \\b 在 Python re 默认含汉字 word char，
        所以 '是stand' 之间不算 boundary → 用显式 ASCII lookbehind/lookahead 替代。
        """
        if not needle or not haystack_lower:
            return False
        prefix = haystack_lower[:head_chars]
        if any('\u4e00' <= c <= '\u9fa5' for c in needle):
            return needle in prefix
        # 英文：ASCII 词边界 + 起始位置在 head_chars 内
        m = re.search(r'(?<![a-zA-Z])' + re.escape(needle) + r'(?![a-zA-Z])',
                      haystack_lower)
        if not m:
            return False
        return m.start() <= head_chars

    @staticmethod
    def _phrase_at_tail(needle: str, haystack_lower: str, tail_chars: int = 14) -> bool:
        """[P0+20-β.2.5 hotfix / 2026-05-17] 关键词是否在 haystack **末尾** tail_chars
        字符内。Sir 23:58 实测 BUG：'不是不是我说错了，是 stand down' 这种纠正/补救式
        输入 sw 在尾部不在首部，原 _phrase_at_head 路径不触发 → stand down 没退出焦点。
        英文用显式 ASCII boundary（\\b 默认含汉字 → '是stand' 之间不算 boundary）。"""
        if not needle or not haystack_lower:
            return False
        suffix = haystack_lower[-max(tail_chars, len(needle) + 4):]
        if any('\u4e00' <= c <= '\u9fa5' for c in needle):
            return needle in suffix
        m = re.search(r'(?<![a-zA-Z])' + re.escape(needle) + r'(?![a-zA-Z])', suffix)
        return m is not None

    def detect_stop_command(self, clean_text: str) -> bool:
        """是否是强制停止指令。被 ASR 主循环调用。"""
        if not clean_text:
            return False
        s = clean_text.lower().strip()
        s_clean = re.sub(r'[，。,.!?？！\s]+', '', s)
        if not s_clean:
            return False
        # 1. 整句完全等于硬/软停止词
        for sw in self.STRICT_STOP_WORDS + self.SOFT_STOP_WORDS:
            if s_clean == sw.lower().replace(' ', ''):
                return True
        # 2. 硬停止词出现在首部（6 字符内）→ 触发
        for sw in self.STRICT_STOP_WORDS:
            if self._phrase_at_head(sw.lower(), s, head_chars=8):
                return True
        # 3. 软停止词仅在 "整句 ≤ 4 字符 且 首部命中" 触发（保留"安静"作为短促停止的兜底）
        for sw in self.SOFT_STOP_WORDS:
            if len(s_clean) <= 4 and self._phrase_at_head(sw.lower(), s, head_chars=4):
                return True
        # 4. [P0+20-β.2.5 hotfix / 2026-05-17] 硬停止词出现在句末（最后 max(len(sw)+6, 14)
        # 字符内）→ 也触发。修 Sir 23:58 实测 BUG："不是不是我说错了，是 stand down" 这种
        # 纠正模式：句首是否定词「不是」，真正意图在句末。短句 (≤ 26 字符) 强制句末检测；
        # 长句仍跳过避免误炸"I want to talk about stand down protocols"这类话题讨论。
        if len(s_clean) <= 26:
            for sw in self.STRICT_STOP_WORDS:
                if self._phrase_at_tail(sw.lower(), s, tail_chars=max(len(sw) + 6, 14)):
                    return True
        return False

    def detect_dismiss_command(self, clean_text: str) -> bool:
        """是否是告别/告退（用户准备结束这一段对话）。"""
        if not clean_text:
            return False
        s = clean_text.lower().strip()
        s_clean = re.sub(r'[，。,.!?？！\s]+', '', s)
        if not s_clean:
            return False

        # 1. 整句等于任何告别词（精确匹配）
        for dw in self.DISMISS_WORDS:
            if s_clean == dw.lower().replace(' ', ''):
                return True

        word_count = len(s.split())
        zh_count = sum(1 for c in s if '\u4e00' <= c <= '\u9fa5')

        # 2. 礼貌词（thanks / 谢谢）—— 必须整句极短才算告别
        # 中文：≤ 4 个汉字总量；英文：≤ 3 个词
        for dw in self.DISMISS_POLITE:
            dw_lower = dw.lower()
            if any('\u4e00' <= c <= '\u9fa5' for c in dw_lower):
                if zh_count <= 4 and dw_lower in s_clean:
                    return True
            else:
                if word_count <= 3:
                    if self._phrase_at_head(dw_lower, s, head_chars=6):
                        return True
                    if re.search(r'\b' + re.escape(dw_lower) + r'\b\s*[!.?]*\s*$', s):
                        return True

        # 3. 强告别词（再见 / bye / goodbye）—— 短句 ≤ 8 词 / ≤ 16 字符 + 首尾命中
        if word_count <= 8 and len(s_clean) <= 16:
            for dw in self.DISMISS_EXCLUSIVE:
                dw_lower = dw.lower()
                if any('\u4e00' <= c <= '\u9fa5' for c in dw_lower):
                    dw_compact = dw_lower.replace(' ', '')
                    if s_clean.startswith(dw_compact) or s_clean.endswith(dw_compact):
                        return True
                else:
                    if self._phrase_at_head(dw_lower, s, head_chars=8):
                        return True
                    if re.search(r'\b' + re.escape(dw_lower) + r'\b\s*[!.?]*\s*$', s):
                        return True

        return False

    def set_speaking_state(self, state_str):
        if state_str == "EXECUTING":
            self.is_jarvis_speaking = True
            set_browser_ducking(True)
            # [P0+18-a.7 / 2026-05-15] 修 BUG #5: Jarvis 自己说话期间不续命焦点 →
            # 30s standby 倒计时跨 vocal 回答阶段 → Sir 听完 Jarvis 回答时焦点已经掉了。
            # 边界续命：进 EXECUTING（开始说话）+ 出 IDLE（说完）各续一次，
            # 与 Bug E 修复不冲突 — Bug E 是说不要在 THINKING 状态持续续命（思考阶段无限续）；
            # 这里只在状态切换瞬间续，单次操作。
            try:
                if getattr(self, 'in_active_conversation', False):
                    self.last_interaction_time = time.time()
            except Exception:
                pass
        elif state_str == "THINKING":
            if getattr(self, 'is_jarvis_speaking', False):
                self.mute_until = time.time() + 1.5
            self.is_jarvis_speaking = False
            # 👇 Bug E 修复：不在这里把 last_interaction_time 顶到现在，
            # 否则任何 Jarvis 自己思考/说话都会续命焦点锁，30 秒永远到不了。
            # last_interaction_time 现在只在"用户成功讲了有效话"时才更新。
            # （P0+18-a.7 备注：续命只在 EXECUTING/IDLE 切换瞬间做，THINKING 仍不续 —
            # 思考态可能持续很久，避免拖死 standby）
        elif state_str == "IDLE":
            was_speaking = getattr(self, 'is_jarvis_speaking', False)
            self.is_jarvis_speaking = False
            # 👇 Bug A 修复：Jarvis 刚说完话 → 保留一个短窗口（0.6s）防止
            # 喇叭余音/房间混响被自家麦克风又拾回去当成"用户输入"。
            # 之前在 in_active_conversation=True 时把 mute_until 强制清零，
            # 直接导致 "As you wish, muting audio" 被自己听进去的死循环。
            if was_speaking:
                # 焦点对话里给 0.6s（够让 TTS 余音衰减但不影响用户秒回）；
                # 非对话状态给 1.5s（更保守，因为我们没在等用户讲话）。
                grace = 0.6 if self.in_active_conversation else 1.5
                self.mute_until = max(self.mute_until, time.time() + grace)
                # [P0+18-a.7 / 2026-05-15] 出 EXECUTING → IDLE（说完一段话）也续命一次，
                # 让 Sir 听完 Jarvis 答语后还有完整 30s 思考时间。
                try:
                    if getattr(self, 'in_active_conversation', False):
                        self.last_interaction_time = time.time()
                except Exception:
                    pass
            if not self.in_active_conversation:
                set_browser_ducking(False)

    def parse_wake_word(self, text):
        text_lower = text.lower().strip()
        if not text_lower:
            return False, text_lower

        wake_aliases = [
            "jarvis", "贾维斯", "javis", "jervis", "jarvi", "jarvice",
            "charles", "travis", "jovis", "gervais",
            "chavis", "jarvid", "jarvs",
            "rovis", "noice", "jarbis", "jarvas", "charvis", "jarviz",
            "jarbis", "jarbus", "jarbiz", "jerviz", "jervas",
            "jarbys", "jarbice", "jervice", "jervis",
        ]

        found_alias = None
        for w in wake_aliases:
            w_lower = w.lower()
            if re.match(r'^[a-z]+$', w_lower):
                if re.search(r'\b' + w_lower + r'\b', text_lower):
                    found_alias = w_lower
                    break
            else:
                if w_lower in text_lower:
                    found_alias = w_lower
                    break

        if found_alias is None:
            english_words = re.findall(r'[a-z]+', text_lower)
            for word in english_words:
                if 4 <= len(word) <= 8:
                    if fuzz.ratio(word, "jarvis") >= 78:
                        found_alias = word
                        break
                    if fuzz.partial_ratio(word, "jarvis") >= 82:
                        found_alias = word
                        break

            if found_alias is None:
                zh_chars = re.sub(r'[^\u4e00-\u9fa5]', '', text_lower)
                if len(zh_chars) >= 2:
                    for size in [2, 3]:
                        for i in range(len(zh_chars) - size + 1):
                            window = zh_chars[i:i+size]
                            if fuzz.ratio(window, "贾维斯") >= 66:
                                found_alias = window
                                break
                        if found_alias:
                            break

        if found_alias is None:
            wake_phrases_fuzzy = [
                "wake up", "wake", "woke up", "woke", "awake",
                "wca", "wka", "wakeup", "way cup", "weigh cup",
                "wake out", "wakeup", "wait up", "wake app",
            ]
            for wp in wake_phrases_fuzzy:
                wp_clean = wp.replace(" ", "")
                text_clean = text_lower.replace(" ", "")
                if wp_clean in text_clean:
                    found_alias = wp
                    break
                if len(text_lower.split()) <= 3:
                    if fuzz.ratio(text_clean, wp_clean) >= 75:
                        found_alias = wp
                        break

        if found_alias is None:
            return False, text_lower

        cmd = text_lower
        cmd = re.sub(r'\b' + re.escape(found_alias) + r'\b', '', cmd)

        wake_phrases = [
            r'\bare\s+you\s+there\b', r'\byou\s+there\b',
            r'\bare\s+you\s+up\b', r'\byou\s+up\b',
            r'\bare\s+you\s+online\b', r'\byou\s+online\b',
            r'\bare\s+you\b',
        ]
        for phrase in wake_phrases:
            cmd = re.sub(phrase, '', cmd)

        cmd = re.sub(r'[，。,.!?？！\s]+', ' ', cmd).strip()

        if not cmd or len(cmd) <= 1:
            cmd = "jarvis"

        return True, cmd

    def _emit_with_attention(self, cmd: str):
        """[R7-α/AttentionContext] emit text_ready 之前先抓拍一份 attention 快照。
        slot 未挂上时不挂；抓拍异常吞掉不影响 emit 主路径。
        capture_now 内部已做 try/except + ≤ 10ms 防御，不会阻塞 ASR 节奏。
        """
        try:
            slot = getattr(self, '_attention_slot', None)
            if slot is not None:
                slot.capture_now()
        except Exception:
            pass
        # 🧬 [P0+20-W.2 / 2026-05-16] 开新对话轮：本轮所有 bg_log 自动带 [turn_xxx] 前缀
        try:
            from jarvis_utils import TraceContext
            TraceContext.new_turn()
        except Exception:
            pass
        # 🪞 [P0+20-β.2.0 / 2026-05-16] 通知 SelfAnchor 新 turn 开始（用于 turn_count + last_spoke）
        try:
            from jarvis_self_anchor import get_default_self_anchor
            _anchor = get_default_self_anchor()
            if _anchor is not None:
                _anchor.record_turn()
        except Exception:
            pass
        self.text_ready.emit(cmd)

    def run(self):
        print("🧠[AuditoryCortex] 正在将 SenseVoiceSmall 神经网络加载到 GPU 显存...")
        try:
            from funasr import AutoModel
            model = AutoModel(model="iic/SenseVoiceSmall", trust_remote_code=True, device="cuda:0")
            print("✅[AuditoryCortex] 本地模型挂载完毕, 完全离线运行！")
        except Exception as e:
            print(f"❌ [模型挂载失败]: {e}")
            return

        import pyaudio, numpy as np, time, wave, soundfile as sf, re, sys
        p = pyaudio.PyAudio()
        try:
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        except Exception as e:
            print(f"❌[麦克风锁定失败]: {e}")
            return

        print("[AuditoryCortex] 24/7 物理环境音频监听已启动...")

        VOLUME_THRESHOLD = 180
        SILENCE_LIMIT = 1.8
        # 👇 Bug D 修复：用户实际诉求是"对话完保持 30 秒焦点模式后自动退出"，
        # 原来 60s 太长 + 又被环境噪音不断续命，实际从来不会自动退出。
        ACTIVE_TIMEOUT = 30.0

        pre_roll_buffer = collections.deque(maxlen=20) 
        audio_frames = []
        is_speaking = False
        silence_timer = time.time()
        start_record_time = 0.0 

        # 🩹 [P0+20-β.1.1 / 2026-05-16] 声波打印节流（治 B6 致命卡顿）
        # 原症状：每帧（64ms）都 sys.stdout.write 进度条 → PowerShell 看不懂 \r
        # → 把所有 ~50 字节进度条横向叠成 30K bytes 单行 → 终端阻塞 → 麦克风
        # 录入再叠加上一段说的话。
        # 修法：① 100ms 内最多刷一次；② 单段进度条结束（is_speaking 落到 False）
        # 再统一换行收尾；③ 异常完全吞掉，绝不影响 ASR 主路径。
        WAVE_PRINT_INTERVAL = 0.10  # 100ms
        last_wave_print_at = 0.0
        wave_in_progress = False  # 当前是否在打印一段声波（决定收尾换行）

        while True:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                volume = np.abs(audio_data).mean()

                # 🩹 [P0+20-β.1.22 / 2026-05-16] 焦点超时检查提到主循环顶部（治 Sir 20:36 反馈）
                # 之前 timeout 检查只在 line 922 的"安静声波"路径，环境有持续音量（视频音/音乐）
                # → volume > VOLUME_THRESHOLD → 走 line 618 分支 → 永远 reach 不到 timeout 检查。
                # 修法：每次 iter 顶部检查一次（不依赖 is_speaking / volume 分支）。
                if self.in_active_conversation and not is_speaking:
                    if time.time() - self.last_interaction_time > ACTIVE_TIMEOUT:
                        print("\n💤[System Standby] 专注锁超时，返回潜意识状态。")
                        if self.state is not None:
                            self.state.set_active_conversation(False, reason='timeout', source='active_timeout_toplevel')
                        else:
                            self.in_active_conversation = False
                        self.last_conversation_end_time = time.time()
                        self.last_dismissal_reason = 'timeout'
                        self.awake_signal.emit(False)
                        set_browser_ducking(False)
                        try:
                            if self._subtitle_queue is not None:
                                self._subtitle_queue.put(("focus", False))
                                self._subtitle_queue.put(("clear", ""))
                        except Exception:
                            pass

                if getattr(self, 'is_jarvis_speaking', False) or time.time() < getattr(self, 'mute_until', 0) or getattr(self, '_suppress_wave', False):
                    frames_left = stream.get_read_available()
                    if frames_left > 0:
                        stream.read(frames_left, exception_on_overflow=False) # 抽干脏水
                    continue
                    
                # 🩹 [P0+20-β.2.2 / 2026-05-16] 滞后双阈值 VAD（治 Sir 21:43 反馈 ASR 不触发）
                # 根因：Sir 后台 Premiere 视频导出让 volume 在 100-200 抖动 →
                # 单一阈值 180 让某些帧进 if-high 分支刷新 silence_timer →
                # silence_timer 永远不超时 → ASR 永远不触发。
                # 修：保持 ENTRY=180 不漏 Sir 真说话，加 EXIT=100 让背景音落到"中间区"，
                # 中间区帧不刷新 silence_timer，让累积正常超时触发 ASR。
                SILENCE_THRESHOLD_EXIT = 100  # 真安静阈值（< 100 视为安静）
                if volume > VOLUME_THRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        self.last_user_speech_time = time.time()
                        start_record_time = time.time() 
                        audio_frames = list(pre_roll_buffer) 
                        
                        if self.in_active_conversation:
                            try:
                                # 🩹 β.1.1：起始用 \r 而不是 \n，避免新行+\r 在 PowerShell
                                # 里堆积视错觉
                                sys.stdout.write("\r🎙️ [接收物理声波] ")
                                sys.stdout.flush()
                                wave_in_progress = True
                                last_wave_print_at = time.time()
                            except Exception:
                                pass
                            # [R7-β5] 第一帧拾到声波 → 屏幕显示 "Listening…"，让 Sir 立刻
                            # 知道 Jarvis 听到了。ASR 完成后由 'user' 频道替换为正式转录。
                            try:
                                if self._subtitle_queue is not None:
                                    self._subtitle_queue.put(("listening_start", ""))
                            except Exception:
                                pass

                    if self.in_active_conversation:
                        # 👇 Bug E 修复：不要在每个高于阈值的声波帧都顶起 last_interaction_time，
                        # 否则环境噪音（风扇/键盘/音乐）会让焦点模式永远续命，30 秒到不了。
                        # last_interaction_time 现在只在 ASR 真正成功转录出有意义内容时才更新（见下方）。
                        # 🩹 β.1.1：节流到 100ms 一次刷新（每帧 64ms → 平均 1-2 帧刷一次）
                        now_t = time.time()
                        if now_t - last_wave_print_at >= WAVE_PRINT_INTERVAL:
                            try:
                                bars = "█" * min(int(volume / 100), 30)
                                sys.stdout.write(f"\r🎙️ [接收物理声波] {bars} ".ljust(50))
                                sys.stdout.flush()
                                last_wave_print_at = now_t
                            except Exception:
                                pass

                    silence_timer = time.time() 
                    audio_frames.append(data)

                # 🩹 [P0+20-β.2.2 / 2026-05-16] 中间区：100 < volume <= 180
                # 视为背景噪音 / 说话尾音，audio 仍然录入但 silence_timer 不刷新
                # 让 silence_timeout 能正常累积到达
                elif is_speaking and volume > SILENCE_THRESHOLD_EXIT:
                    audio_frames.append(data)
                    # 注意：不刷新 silence_timer，不打格子（避免误以为 Sir 在说话）

                elif is_speaking:
                    audio_frames.append(data)
                    
                    current_speaking_duration = time.time() - start_record_time
                    
                    if self.in_active_conversation:
                        if current_speaking_duration < 3:
                            current_silence_limit = 1.5
                        else:
                            current_silence_limit = 2
                    else:
                        current_silence_limit = 1.5
                    
                    max_record_time = 60.0 if self.in_active_conversation else 4.0 
                    
                    is_silence_timeout = (time.time() - silence_timer > current_silence_limit)
                    is_max_time_reached = (time.time() - start_record_time > max_record_time)
                    
                    if is_silence_timeout or is_max_time_reached:
                        is_speaking = False
                        # 🩹 [P0+20-β.1.1 / 2026-05-16] 收尾换行：保证一段声波结束后
                        # 后续 [Pipeline]/[Tier]/[Human] 等输出不和进度条粘连。
                        if wave_in_progress:
                            try:
                                sys.stdout.write("\n")
                                sys.stdout.flush()
                            except Exception:
                                pass
                            wave_in_progress = False
                        
                        if self.in_active_conversation and self.DEBUG_ASR:
                            sys.stdout.write("\r🧠[声波截断] 正在进行神经网络转译...".ljust(50) + "\n")
                            sys.stdout.flush()

                        pcm_data = b''.join(audio_frames)
                        with io.BytesIO() as wav_io:
                            with wave.open(wav_io, 'wb') as wav_file:
                                wav_file.setnchannels(1)
                                wav_file.setsampwidth(2)
                                wav_file.setframerate(16000)
                                wav_file.writeframes(pcm_data)
                            wav_io.seek(0)
                            speech_array, _ = sf.read(wav_io)

                        res = model.generate(input=speech_array, cache={}, language="auto", use_itn=True, disable_pbar=True)

                        if res and len(res) > 0:
                            raw_text = res[0].get("text", "")
                            clean_text = re.sub(r'<\|.*?\|>', '', raw_text).strip()
                            clean_text_lower = clean_text.lower()
                            
                            if clean_text and len(clean_text) >= 2 and self.DEBUG_ASR:
                                print(f"\n🔊 [ASR Diag] Model heard: '{clean_text}' (raw: '{raw_text}')")
                            
                            is_woken_up, raw_cmd = self.parse_wake_word(clean_text)

                            # [R6/B5] 改走上下文感知检测 —— "外面很安静" 不再误炸
                            if self.detect_stop_command(clean_text):
                                if self.DEBUG_ASR:
                                    print(f"\n🛑 [Force Stop] 中断指令已接收，系统终止。")
                                # [R7-α/B1] 显式 reason='stop_cmd'
                                if self.state is not None:
                                    self.state.set_active_conversation(False, reason='stop_cmd', source='detect_stop_command')
                                else:
                                    self.in_active_conversation = False
                                self.last_conversation_end_time = time.time()
                                self.last_dismissal_reason = 'manual_stop'  # [R6/B6] 标记停止原因
                                self.awake_signal.emit(False)
                                self.interrupt_signal.emit()
                                set_browser_ducking(False)
                                # [R7-β1/post-test] 清字幕
                                try:
                                    if self._subtitle_queue is not None:
                                        self._subtitle_queue.put(("focus", False))
                                        self._subtitle_queue.put(("clear", ""))
                                except Exception:
                                    pass
                                frames_left = stream.get_read_available()
                                if frames_left > 0: stream.read(frames_left, exception_on_overflow=False)
                                continue

                            ghost_hallucinations = [
                                "the.", "the", "no.", "no", "yeah.", "yeah", ".", "i.", "i", "a.", "oh.",
                                "you.", "you", "and.", "and", "to.", "to", "is.", "is", "it.", "it",
                                "he.", "he", "she.", "she", "we.", "we", "they.", "they",
                                "als", "als you", "r as", "robin", "hello joyce", "hello",
                                "mhm.", "mhm", "uh.", "uh", "um.", "um", "hmm.", "hmm",
                                "rs.", "rs", "com.", "com", "jo.", "jo", "da", "da.",
                                "ok.", "ok", "okay.", "okay", "yes.", "yes", "so.", "so",
                                "me.", "me", "my.", "my", "in.", "in", "on.", "on",
                                "at.", "at", "of.", "of", "be.", "be", "do.", "do",
                                # [v4] Sir 23:02:33 实测发现 ASR 把背景杂音听成 "I am" 触发空轮 LLM。
                                # Whisper-class 模型对长尾噪声的典型幻觉就是 "I am" / "thank you" / "you" 等。
                                "i am.", "i am", "i'm", "im",
                                "thank you.", "thank you", "thanks.", "thanks",
                                "bye.", "bye", "goodbye.", "goodbye",
                                "all right.", "all right", "alright.", "alright",
                                "go.", "go", "hi.", "hi", "hey.", "hey", "ha.", "ha",
                                "novice.", "novice", "alice.", "alice", "joice.", "joice",
                                "zice.", "zice", "do all this.", "do all this",
                                "davis.", "davis", "travis.", "service.", "service",
                                "nervous.", "nervous", "harvest.", "harvest",
                                "this.", "this", "that.", "that", "what.", "what",
                                "or.", "or", "as.", "as", "if.", "if", "us.", "us",
                                "all.", "all", "not.", "not", "but.", "but", "are.", "are",
                                "am.", "am", "an.", "an", "has.", "has", "had.", "had",
                                "was.", "was", "were.", "were", "will.", "will", "would.", "would",
                                # [P0+18-a.8 / 2026-05-15] 修 BUG #6: ASR 把 Jarvis 末尾 "It's"/"if"/"or"
                                # 当用户输入。补全英文常见缩写 + 短助词，让 echo 余音被静默丢弃。
                                "it's.", "it's", "its.", "its",
                                "i'll.", "i'll", "i've.", "i've", "i'd.", "i'd",
                                "we'll.", "we'll", "we've.", "we've", "we're.", "we're",
                                "you'll.", "you'll", "you've.", "you've", "you're.", "you're", "your.", "your",
                                "they'll.", "they'll", "they've.", "they've", "they're.", "they're",
                                "that's.", "that's", "there's.", "there's", "here's.", "here's", "where's.", "where's",
                                "what's.", "what's", "who's.", "who's", "how's.", "how's",
                                "won't.", "won't", "don't.", "don't", "can't.", "can't",
                                "couldn't.", "couldn't", "shouldn't.", "shouldn't", "wouldn't.", "wouldn't",
                                "doesn't.", "doesn't", "didn't.", "didn't", "wasn't.", "wasn't", "weren't.", "weren't",
                                "isn't.", "isn't", "aren't.", "aren't", "hasn't.", "hasn't", "haven't.", "haven't",
                                "sir.", "sir", "ma'am.", "ma'am",
                                # Jarvis 常说的尾巴音节（"...Sir." 之后 ASR 偶尔切出来的孤词）
                                "with.", "with", "for.", "for", "from.", "from", "by.", "by", "into.", "into",
                                "very.", "very", "well.", "well", "just.", "just", "now.", "now", "then.", "then",
                                "some.", "some", "any.", "any", "much.", "much", "many.", "many",
                                "let.", "let", "see.", "see", "got.", "got", "get.", "get",
                                # 中文短助词常见 ASR 噪声（jarvis 中文翻译末尾）
                                "嗯", "呃", "啊", "哦", "嗯。", "呃。", "啊。", "哦。", "嗯，", "呃，",
                                "好的", "好的。", "是的", "是的。", "好", "对", "对。",
                            ]
                            # 👇 核心修复：将中文纳入有效信息判定！
                            meaningful_en_words = [w for w in re.findall(r'[a-z]+', clean_text_lower) if len(w) >= 2]
                            zh_chars = re.findall(r'[\u4e00-\u9fa5]', clean_text)
                            
                            # 如果既没有英文单词，也没有中文字符，才算真的没有意义 (纯符号或乱码)
                            has_no_meaning = len(meaningful_en_words) == 0 and len(zh_chars) == 0
                            
                            # 对于纯英文，长度 <=3 极大概率是底噪 ("oh", "ah")，所以拦截；
                            # 但对于中文，即使只有 2 个字符 ("好的", "查询", "谢谢") 也是完全有意义的指令，绝不能拦截！
                            is_too_short = len(clean_text) <= 3 and len(zh_chars) == 0
                            
                            # 终极拦截逻辑：如果太短且没中文、或是已知空耳幻觉、或彻底没内容，才丢弃
                            if is_too_short or clean_text_lower in ghost_hallucinations or has_no_meaning:
                                if not self.in_active_conversation:
                                    set_browser_ducking(False)
                                # [R7-β5] ASR 丢弃 → 清 Listening… 状态
                                self._publish_listening_done()
                                continue

                            # 👇 Bug B 修复：核心回声防御 ——
                            # ASR 转录的文本是否高度疑似 Jarvis 自己最近 12s 说过的话？
                            # 命中即作为麦克风拾到的喇叭余音丢弃，绝不送进 LLM 形成"Jarvis 跟自己对话"。
                            # 这是 16:22:22 那次 "As you wish, muting audio" 死循环的最后一道闸。
                            try:
                                from jarvis_utils import is_recent_jarvis_echo
                                if is_recent_jarvis_echo(clean_text):
                                    if self.DEBUG_ASR:
                                        print(f"\n🔇 [Echo Guard] 检测到 Jarvis 自己的回声，丢弃: '{clean_text[:80]}'")
                                    else:
                                        try:
                                            from jarvis_utils import bg_log
                                            bg_log(f"🔇 [Echo Guard] 丢弃 Jarvis 自己的回声: '{clean_text[:60]}'")
                                        except Exception:
                                            pass
                                    if not self.in_active_conversation:
                                        set_browser_ducking(False)
                                    # [R7-β5] echo 丢弃 → 清 Listening… 状态
                                    self._publish_listening_done()
                                    continue
                            except Exception:
                                pass

                            # 👇 往下继续保留您原来的代码
                            if hasattr(self, 'return_sentinel') and self.return_sentinel:
                                if self.return_sentinel.soft_focus_active:
                                    if self.return_sentinel.validate_soft_focus(clean_text):
                                        # [P0+18-c.13 / 2026-05-15] 改 bg_log 不漏到 acoustic wave 行尾
                                        try:
                                            from jarvis_utils import bg_log as _sf_bg_log
                                            _sf_bg_log("🔒 [Soft Focus] Verified, focus mode locked。")
                                        except Exception:
                                            pass
                                    else:
                                        try:
                                            from jarvis_utils import bg_log as _sf_bg_log
                                            _sf_bg_log("🔇 [Soft Focus] 检测到背景音/非对话，静默退出。")
                                        except Exception:
                                            pass
                                        # [R7-α/B1+B3] 显式 reason='soft_focus_fail'，并补上 B3 漏掉的 last_dismissal_reason
                                        if self.state is not None:
                                            self.state.set_active_conversation(False, reason='soft_focus_fail', source='validate_soft_focus')
                                        else:
                                            self.in_active_conversation = False
                                        self.last_conversation_end_time = time.time()
                                        # [B3 修复] 之前这里只 emit awake_signal 但没标 last_dismissal_reason，
                                        # 导致 wake_weight 把这次错误退出当成 natural（中性），相当于回声/底噪
                                        # 让 Jarvis 退场后又被自家底噪触发误唤醒；现在标成 false_alarm 让 wake_weight
                                        # 把短时间内紧跟的"复唤醒"按"误退出后的恢复"处理（不扣权重）。
                                        self.last_dismissal_reason = 'false_alarm'
                                        self.awake_signal.emit(False)
                                        set_browser_ducking(False)
                                        # [P0+11 / 2026-05-15] soft_focus_fail 退出时也清 Listening… 状态
                                        # 之前 too_short / hallucination / echo 三处补了，soft_focus_fail 漏了
                                        # 导致字幕区"Listening…"残留直到下一次 ASR 成功覆盖
                                        self._publish_listening_done()
                                        continue  

                            # [R6/B5] 改走上下文感知检测 —— "Thanks for that, can you also..." 不再被错判为告别
                            if self.in_active_conversation and self.detect_dismiss_command(clean_text):
                                print("\n💤 [System Standby] 告别指令已接收，进入潜意识状态。")
                                # [R7-α/B1] 显式 reason='dismiss'
                                if self.state is not None:
                                    self.state.set_active_conversation(False, reason='dismiss', source='detect_dismiss_command')
                                else:
                                    self.in_active_conversation = False
                                self.last_conversation_end_time = time.time()
                                self.last_dismissal_reason = 'manual_dismiss'  # [R6/B6] 标记告别原因
                                self.awake_signal.emit(False)
                                # [R7-β1/post-test] 告别 → 清字幕
                                try:
                                    if self._subtitle_queue is not None:
                                        self._subtitle_queue.put(("focus", False))
                                except Exception:
                                    pass
                                cmd = re.sub(r'[，。,.!?？！\s]+$', '', clean_text)
                                if cmd: self._emit_with_attention(cmd)
                                continue

                            # 👇 极简处理：不再打印“神经元捕获残影”等废话，直接发送指令
                            if is_woken_up:
                                if not self.in_active_conversation:
                                    self.awake_signal.emit(True)
                                # [R7-α/B1] 显式 reason='wake'
                                if self.state is not None:
                                    self.state.set_active_conversation(True, reason='wake', source='wake_word_match')
                                else:
                                    self.in_active_conversation = True
                                self.last_interaction_time = time.time()
                                set_browser_ducking(True) 
                                cmd = re.sub(r'[，。,.!?？！\s]+$', '', raw_cmd)
                                if cmd:
                                    self._emit_with_attention(cmd)
                                else:
                                    self._emit_with_attention("jarvis")
                                    set_browser_ducking(False) 
                                    
                            elif self.in_active_conversation:
                                cmd = re.sub(r'[，。,.!?？！\s]+$', '', clean_text)
                                if cmd:
                                    self.last_interaction_time = time.time() 
                                    set_browser_ducking(True) 
                                    self._emit_with_attention(cmd)

                        self.mute_until = time.time() + 1.0

                        frames_left = stream.get_read_available()
                        if frames_left > 0:
                            stream.read(frames_left, exception_on_overflow=False)   
                else:
                    if not is_speaking:
                        pre_roll_buffer.append(data)
                        if self.in_active_conversation and (time.time() - self.last_interaction_time > ACTIVE_TIMEOUT):
                            print("\n💤[System Standby] 专注锁超时，返回潜意识状态。")
                            # [R7-α/B1] 显式 reason='timeout'
                            if self.state is not None:
                                self.state.set_active_conversation(False, reason='timeout', source='active_timeout')
                            else:
                                self.in_active_conversation = False
                            self.last_conversation_end_time = time.time()
                            self.last_dismissal_reason = 'timeout'  # [R6/B6] 标记是"自然超时"，与"用户主动喊停"区分
                            self.awake_signal.emit(False)
                            set_browser_ducking(False)
                            # [R7-β1/post-test] 焦点超时 → 清字幕 + 通知 SubtitleOverlay 退焦点
                            try:
                                if self._subtitle_queue is not None:
                                    self._subtitle_queue.put(("focus", False))
                                    self._subtitle_queue.put(("clear", ""))
                            except Exception:
                                pass

            except Exception as e:
                print(f"⚠️[Audio Nerve 断连]: {e}")
                time.sleep(1)
                
class JarvisWorkerThread(QThread):
    state_changed = pyqtSignal(str)
    DEBUG_LTM = False
    
    def __init__(self, api_key, gemini_key, key_router=None):
        super().__init__()
        self.key_router = key_router
        PhysicalEnvironmentProbe.start_monitoring()
        self.cmd_queue = queue.Queue()
        self.jarvis = CentralNerve(api_key=api_key, gemini_key=gemini_key, key_router=key_router, state_callback=self.emit_state)
        self.jarvis._worker_ref = self
        # [R7-α/B1] 共用 CentralNerve 的中央状态机；本类的 is_awake property 直接读 state.awake
        self.state = self.jarvis.state
        self.return_sentinel = self.jarvis.guardian_center.return_sentinel if self.jarvis.guardian_center else None
        self.chat_bypass = ChatBypass(key_router, self.jarvis.vocal, self.state_changed.emit)
        
        self.jarvis.chat_bypass = self.chat_bypass
        # 👇 核心新增：把整个中枢神经系统暴露给主聊天脑，让它能瞬间抓取原子工具！
        self.chat_bypass.jarvis = self.jarvis

        # [轴3-L3.2 + L3.3 / 2026-05-15] 注入 PromiseExecutor 的两个回调 + 启动 daemon
        # 必须在 chat_bypass / vocal 都准备好之后注入。
        # - fast_call_executor 走 ChatBypass._execute_fast_call (复用 FAST_CALL 的成熟工具调用路径)
        # - say_to_sir 走 vocal.say (clarification 反向问 Sir / dangerous 二次确认 / 完工汇报)
        # [P0+18-a.2] 任何失败必须带 traceback 让 Sir 重启时看见根因，不静默吞
        if getattr(self.jarvis, 'promise_executor', None) is not None:
            try:
                _exec = self.jarvis.promise_executor
                _cb = self.chat_bypass
                _voc = self.jarvis.vocal
                _exec._fast_call = (
                    lambda organ, command, args, _cb_ref=_cb:
                        _cb_ref._execute_fast_call(organ, command, args)
                )
                _exec._say = (
                    lambda text, _v=_voc:
                        (_v.say(text) if _v else None)
                )
                _exec.start()
                print(f"[PromiseExecutor wire] ✅ fast_call+say 已注入 + daemon 已启动")
            except Exception as _e:
                import traceback as _tb
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"[PromiseExecutor wire] 失败：{_e}")
                except Exception:
                    pass
                _tb.print_exc()
        else:
            print(f"[PromiseExecutor wire] 跳过：self.jarvis.promise_executor 为 None")
        
        self.mailbox = SubconsciousMailbox()
        # ... 后面的保持不变
        self.jarvis.mailbox = self.mailbox 
        self.jarvis.focus_callback = self.enter_focus_mode
        # 👇 核心修复：把 self.jarvis 传给起搏器！
        self.heartbeat = ChronosTick(self.mailbox, self.chat_bypass, self.state_changed.emit, self.jarvis)
        self.heartbeat.start()
        self.jarvis.chronos_tick = self.heartbeat
        
        # 你的系统哨兵 (前提是你之前已经加了这个类)
        self.system_sentinel = SystemSentinel(self.mailbox)
        self.system_sentinel.start()
        
        self.chronos_sentinel = ChronosSentinel(self.mailbox, self.jarvis.hippocampus, self.jarvis)
        self.chronos_sentinel.start()

        self.pending_event = None

        # [v5.1 / Sir-2026-05-15] Sleep Intent 窗口
        # 当 Sir 明确表态"我 X 分钟后睡 / I'll go to sleep in X" 时，把窗口设到
        # now + X 分钟 + 15 分钟 grace。Conductor / SmartNudgeSentinel 在此窗口内
        # 静默 late_night / suggest_break / bedtime 类 nudge —— 修"重复催睡"。
        self._sleep_intent_until = 0.0
    
    def emit_state(self, state):
        self.state_changed.emit(state)

    # [R7-α/B1] is_awake 通过 property 走 self.state；
    # 老代码 self.is_awake = X 仍然能写（property setter 会接住 → state.set_awake(X, reason='legacy_setter')）。
    # 新代码应该显式：self.state.set_awake(X, reason='wake_word' / 'sleep_cmd' / ...)
    @property
    def is_awake(self) -> bool:
        state = getattr(self, 'state', None)
        if state is None:
            return False
        return state.awake

    @is_awake.setter
    def is_awake(self, value):
        state = getattr(self, 'state', None)
        if state is None:
            return
        state.set_awake(value, reason='legacy_setter', source='JarvisWorkerThread')

    def set_awake_status(self, status: bool):
        # 💡 终极修复：只接受听觉皮层传来的“睡眠”指令（同步 UI 待机）。
        # 绝对不接受外部传来的“刚被唤醒”信号！防止大脑过早认为自己醒了而吞掉唤醒词！
        # 大脑的清醒状态，必须由它在处理完第一句话后自己亲自点亮。
        if not status:
            # [R7-α/B1] 显式 reason，便于追溯
            state = getattr(self, 'state', None)
            if state is not None:
                state.set_awake(False, reason='standby', source='set_awake_status')

    # [R6/Tier] 五档 prompt 路由分类器（字面量在 CentralNerve；此处别名供本类方法与单测引用）
    PROMPT_TIER_WAKE_ONLY = CentralNerve.PROMPT_TIER_WAKE_ONLY
    PROMPT_TIER_SHORT_CHAT = CentralNerve.PROMPT_TIER_SHORT_CHAT
    PROMPT_TIER_FACTUAL_RECALL = CentralNerve.PROMPT_TIER_FACTUAL_RECALL
    PROMPT_TIER_TOOL_REQUEST = CentralNerve.PROMPT_TIER_TOOL_REQUEST
    PROMPT_TIER_DEEP_QUERY = CentralNerve.PROMPT_TIER_DEEP_QUERY
    PROMPT_TIER_CRITICAL = CentralNerve.PROMPT_TIER_CRITICAL

    _TIER_CRITICAL_KEYWORDS = [
        r'remind\s+me', r'set\s+(an?\s+)?alarm', r'schedule\b', r'wake\s+me\s+up',
        r'cancel.*remind', r'cancel.*alarm',
        r'提醒我', r'闹钟', r'叫醒我', r'定个', r'设个', r'排期', r'取消.*提醒',
        r'at\s+\d', r"\d+\s*o'?clock", r'\d+点',
        r'remember\s+(this|that)', r'记下', r'记住', r'note\s+this',
    ]
    # [R7-β1] FACTUAL_RECALL —— 近期事实查询，答案大概率已在 working_feed / event_bus / STM 里
    # 触发要求：必须带"刚 / 最近 / 上一句 / just"这类时间指代 + 一个可被 working_feed 命中的对象（剪贴板/命令/历史话题）
    # 优先级高于 TOOL_REQUEST，避免"刚复制的是什么"被误判为"copy 动作 → 调工具"。
    _TIER_FACTUAL_RECALL_KEYWORDS = [
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
    _TIER_TOOL_KEYWORDS = [
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
    _TIER_DEEP_KEYWORDS = [
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

    def _classify_prompt_tier(self, cmd: str, cmd_clean: str, cmd_words: list) -> str:
        """O(几十微秒) 的纯文本六档分类。返回 PROMPT_TIER_* 之一。
        排序优先级：CRITICAL > FACTUAL_RECALL > TOOL_REQUEST > DEEP_QUERY > WAKE_ONLY > SHORT_CHAT
        —— FACTUAL_RECALL 必须先于 TOOL_REQUEST 判定，否则"刚复制的内容"被
        TOOL_REQUEST 关键词"复制"吸走，去调不存在的剪贴板工具（19:21 实战 bug）。
        """
        if not cmd:
            return self.PROMPT_TIER_SHORT_CHAT
        cmd_lower = cmd.lower()

        # 1. CRITICAL —— 排期/提醒/记忆同步：永远走全量
        for pat in self._TIER_CRITICAL_KEYWORDS:
            if re.search(pat, cmd_lower):
                return self.PROMPT_TIER_CRITICAL

        # 2. [R7-β1] FACTUAL_RECALL —— 近期事实查询（"刚复制 / 刚说 / 刚跑的命令"）
        # 答案大概率已在 prompt 的 WORKING MEMORY / event_bus / STM 里，不该再调工具
        for pat in self._TIER_FACTUAL_RECALL_KEYWORDS:
            try:
                if re.search(pat, cmd_lower):
                    return self.PROMPT_TIER_FACTUAL_RECALL
            except re.error:
                if pat in cmd_lower:
                    return self.PROMPT_TIER_FACTUAL_RECALL

        # 3. TOOL_REQUEST —— 动作动词
        for pat in self._TIER_TOOL_KEYWORDS:
            try:
                if pat.startswith('\\b') or pat.startswith('(') or '\\' in pat:
                    if re.search(pat, cmd_lower):
                        return self.PROMPT_TIER_TOOL_REQUEST
                else:
                    if pat in cmd_lower:
                        return self.PROMPT_TIER_TOOL_REQUEST
            except re.error:
                if pat in cmd_lower:
                    return self.PROMPT_TIER_TOOL_REQUEST

        # 4. DEEP_QUERY —— 历史/指代/记忆引用
        for pat in self._TIER_DEEP_KEYWORDS:
            try:
                if pat.startswith('\\b') or pat.startswith('(') or '\\' in pat:
                    if re.search(pat, cmd_lower):
                        return self.PROMPT_TIER_DEEP_QUERY
                else:
                    if pat in cmd_lower:
                        return self.PROMPT_TIER_DEEP_QUERY
            except re.error:
                if pat in cmd_lower:
                    return self.PROMPT_TIER_DEEP_QUERY

        # 5. WAKE_ONLY —— 看 wake_weight
        wake_weight = self._compute_wake_weight(cmd_clean, cmd_words)
        if wake_weight >= 0.65:
            return self.PROMPT_TIER_WAKE_ONLY

        # 6. SHORT_CHAT —— ≤ 8 词且 ≤ 50 字符
        if len(cmd_words) <= 8 and len(cmd) <= 50:
            return self.PROMPT_TIER_SHORT_CHAT

        # 默认走 DEEP_QUERY（更长的输入大概率需要更丰富的上下文）
        return self.PROMPT_TIER_DEEP_QUERY

    def _compute_wake_weight(self, cmd_clean: str, cmd_words: list) -> float:
        weight = 0.0

        WAKE_ALIASES = [
            "jarvis", "javis", "jervis", "charles", "travis", "jovis",
            "wake up", "wake", "woke up", "awake", "贾维斯", "加维斯", "家维斯"
        ]

        is_exact_wake = cmd_clean in WAKE_ALIASES
        is_short = len(cmd_words) <= 2
        word_count = len(cmd_words)

        if is_exact_wake:
            weight += 0.55

        if is_short:
            weight += 0.15

        if word_count == 1:
            weight += 0.10

        # [R6/B6] 根据"上次对话结束的原因"决定权重，而不是粗暴对所有刚结束的对话减权：
        # - manual_stop / manual_dismiss: 用户主动结束 → 30s 内复唤醒大概率是无意识背景噪音，扣权重
        # - timeout: 自然超时 → 用户可能"哦对了 Jarvis" 想到补充，给个小加分（5min 内）
        # - natural / None: 没有明确结束信号 → 中性，不动权重
        time_since_last_conv = float('inf')
        last_reason = None
        if hasattr(self, 'voice_thread') and self.voice_thread:
            time_since_last_conv = time.time() - self.voice_thread.last_conversation_end_time
            last_reason = getattr(self.voice_thread, 'last_dismissal_reason', None)

        if last_reason in ('manual_stop', 'manual_dismiss'):
            # 用户主动喊停，刚刚的复唤醒 95% 是回声/底噪 → 严格扣
            if time_since_last_conv < 30:
                weight -= 0.25
            elif time_since_last_conv < 120:
                weight -= 0.12
        elif last_reason == 'timeout':
            # 自然超时，复唤醒大概率是"哦对了" → 给一点点加分（不冒进，0.08）
            if 5 < time_since_last_conv < 300:
                weight += 0.08
        elif last_reason == 'false_alarm':
            # [R7-α/B3] soft_focus 误判退出（不是 Sir 主动结束，是 validate_soft_focus 把
            # 背景音当成"非对话"）→ 紧跟着的复唤醒大概率是 Sir 在补救前一句被吞的话，不扣权重
            # 之前这种情况会被 wake_weight 当成 natural（中性）—— 也就是没加分，但同样不影响后续
            # 已经够保守了，这里不再加分（避免把误判的"复唤醒"放大成幻觉唤醒）
            pass

        # in_active 时根本不需要再唤醒 → 仍然减权
        in_active = False
        if hasattr(self, 'voice_thread') and self.voice_thread:
            in_active = self.voice_thread.in_active_conversation
        if in_active:
            weight -= 0.30

        looks_like_practice = False
        if is_short and not is_exact_wake:
            practice_patterns = [
                r'^(say|speak|read|pronounce|repeat|how.*say|how.*pronounce)\s',
                r'^(说|读|念|发音|怎么读|怎么说)',
                r'^(is|are|am|do|does|did|can|could|will|would|should|may|might)\s',
                r'^(what|who|where|when|why|how)\s',
                r'^(i\s|you\s|he\s|she\s|it\s|we\s|they\s)',
                r'^(string|integer|float|boolean|array|object|function|class|method|variable)',
            ]
            for pat in practice_patterns:
                if re.search(pat, cmd_clean):
                    looks_like_practice = True
                    break
        if looks_like_practice:
            weight -= 0.35

        stm_has_recent_practice = False
        if hasattr(self.jarvis, 'short_term_memory') and self.jarvis.short_term_memory:
            recent = self.jarvis.short_term_memory[-3:]
            for m in recent:
                user_msg = m.get('user', '')
                if any(kw in user_msg.lower() for kw in ['say', 'pronounce', '发音', '怎么说', 'string']):
                    stm_has_recent_practice = True
                    break
        if stm_has_recent_practice:
            weight -= 0.20

        return max(0.0, min(1.0, weight))

    def play_acknowledgment_chime(self):
        """生成并播放一个极度优雅、科幻的低频确认音 (无需外部音频文件)"""
        try:
            import numpy as np
            import threading
            
            def _play():
                sr = 22050
                duration = 0.15  # 极短的 150 毫秒
                t = np.linspace(0, duration, int(sr * duration), endpoint=False)
                
                # 🎶 物理声学合成：C5 与 E5 的大三度和谐双音色 (顶级智能音箱常用的听觉UI和弦)
                wave1 = np.sin(2 * np.pi * 523.25 * t)
                wave2 = np.sin(2 * np.pi * 659.25 * t)
                
                # 📉 指数衰减包络 (模拟高级玻璃或水晶的敲击感，声音迅速收敛)
                envelope = np.exp(-20 * t)
                
                # 🎚️ 混合音轨，并把音量压到 0.08 (极度克制、优雅、绝对不刺耳)
                chime = (wave1 + wave2) * 0.5 * envelope * 0.4
                
                chime_int16 = (chime * 32767).astype(np.int16)
                
                # 🚀 降维打击：直接倾泻进 VocalCord 的常驻零延迟声卡通道！
                if hasattr(self.jarvis, 'vocal') and hasattr(self.jarvis.vocal, 'play_only'):
                    self.jarvis.vocal.play_only(chime_int16.tobytes())
                    
            # 挂在后台幽灵线程，绝对不阻塞 AI 思考
            threading.Thread(target=_play, daemon=True).start()
        except Exception as e:
            pass

    # 找到 JarvisWorkerThread 类的 set_awake_status 下面增加：
    def enter_focus_mode(self, silent=False):
        if not silent:
            print("\n👀 [CentralNerve] 语音结束，自动维持 30 秒专注模式...")

        # [R7-α/B1] 走中央状态机；reason='focus_mode' 便于回看
        if self.state is not None:
            self.state.set_awake(True, reason='focus_mode', source='enter_focus_mode')
        vt = getattr(self, 'voice_thread', None)
        if vt is not None:
            vt.in_active_conversation = True
            vt.last_interaction_time = time.time()
            vt.awake_signal.emit(True)

    def push_command(self, cmd):
        self.cmd_queue.put(cmd)

    def interrupt_all(self):
        print("\n🚨 [CentralNerve] 全局停止信号已接收！强制拔线...")
        self.jarvis.is_interrupted = True
        self.chat_bypass.is_interrupted = True
        
        # 👇 核心修改 3：彻底解除状态锁和受污染的记忆/队列
        # [R7-α/B1] 走中央状态机：interrupt 是个清晰可追溯的原因
        if self.state is not None:
            self.state.set_active_task(False, reason='interrupt', source='interrupt_all')
            self.state.set_awake(False, reason='interrupt', source='interrupt_all')
        from jarvis_blood import JarvisBlood
        self.jarvis.blood = JarvisBlood()  # 换血：清空受污染的任务血液状态

        # 清空天启探针队列里残留的废话
        with self.jarvis.interruption_queue.mutex:
            self.jarvis.interruption_queue.queue.clear()

        # [R7-α/B6] 顺序修正：必须先 vocal.stop() 真正打断正在播放的那一帧音频，
        # 再清队列。原来"先 clear queue 再 vocal.stop()"会让 _play_worker 仍卡在
        # vocal.play_only() 阻塞调用里念完当前帧 → 偶发"急停后又自言半句"现象。
        if hasattr(self.jarvis.vocal, 'stop'):
            try:
                self.jarvis.vocal.stop()
            except Exception:
                pass

        with self.chat_bypass.audio_queue.mutex:
            self.chat_bypass.audio_queue.queue.clear()
        with self.chat_bypass.wave_queue.mutex:
            self.chat_bypass.wave_queue.queue.clear()

        # [R7-α/B6] 把可能正在 render 的标志位也归零，让 _play_worker 走 IDLE 路径
        try:
            self.chat_bypass._render_in_progress = False
        except Exception:
            pass

        # [R7-β2] 取消任何挂着的 backchannel timer，避免急停后 chime 还会蹦出来
        try:
            self.chat_bypass._mark_first_token()
        except Exception:
            pass

        # [R7-α/PlanLedger] 急停时把所有 active plan 也 cancel 掉
        try:
            pl = getattr(self.jarvis, 'plan_ledger', None)
            if pl is not None:
                cancelled = pl.cancel_all(reason='interrupt_all')
                if cancelled:
                    print(f"📋 [PlanLedger] interrupt_all 取消了 {len(cancelled)} 个 active plan")
        except Exception:
            pass

        # 👇 Bug G 修复：手动急停（用户说"闭嘴""退下"等）后，3 分钟内不允许
        # Conductor / SmartNudge 任何一种主动发声，避免刚静音又被 offer_help
        # 立刻吵醒 → 进焦点模式 → 听到自己之前的退场语 → 死循环这种灾难。
        try:
            gate = getattr(self.jarvis, 'nudge_gate', None)
            if gate and hasattr(gate, 'freeze_for'):
                gate.freeze_for(180.0, source='manual_standby')
                print("🛡️ [NudgeGate] 手动急停后冷却 3 分钟，抑制 Conductor / SmartNudge 抢话。")
        except Exception:
            pass

        # [R6/Bus] 投递 manual_standby 到事件总线，让主脑下次唤醒时知道"刚刚被叫停了"
        try:
            bus = getattr(self.jarvis, 'event_bus', None)
            if bus is not None:
                bus.publish(
                    etype='manual_standby',
                    description="Sir manually interrupted you and asked for silence.",
                    source='interrupt_all',
                )
        except Exception:
            pass

        # 👇 Bug B 修复：清空 TTS 回声指纹环 —— 急停场景下我们要主动断电，
        # 之前积累的 12s 指纹可能干扰用户重新唤醒后的第一句正常话。
        try:
            from jarvis_utils import clear_jarvis_tts_ring
            clear_jarvis_tts_ring()
        except Exception:
            pass

        self.emit_state("IDLE")
        self.chat_bypass.subtitle_queue.put(("focus", False))
        self.chat_bypass.subtitle_queue.put(("clear", ""))
        print("✅ [System Standby] Neural deadlock cleared, fully returned to standby。")
        import random
        import threading
        
        # 贾维斯的专属退场语录池 (英文语音 + 中文字幕)
        stand_down_phrases = [
            ("Standing down, Sir.", "已退下，先生。"),
            ("Entering standby mode.", "进入待机模式。"),
            ("Awaiting your next command, Sir.", "等待您的下一个指令，先生。"),
            ("Systems on standby.", "系统已挂起。"),
            ("As you wish. Muting audio.", "如您所愿，已静音。")
        ]
        
        en_phrase, zh_subtitle = random.choice(stand_down_phrases)
        
        # 极简 UI 打印，保持强迫症排版
        print(_box_newline(f"\n║ 🤖  [Jarvis] {en_phrase}"))
        print(_box_newline(f"║ 📺  [Subtitle] {zh_subtitle}"))
        print("╚" + "═"*63 + "\n")
        
        # 开一个极轻量的幽灵线程去念这句话，绝对不阻塞系统制动！
        # 👇 Bug C 修复：必须经过状态机把 is_jarvis_speaking 翻起来，
        # 否则 vocal.say 直接打 PyAudio 输出流时麦克风毫无防护，自己
        # 会把"As you wish, Muting audio."又听回去当成用户指令。
        # 同时把这句话注册到回声指纹环，30s 内 ASR 听到再确认一次拦截。
        try:
            from jarvis_utils import register_jarvis_tts
            register_jarvis_tts(en_phrase)
        except Exception:
            pass

        def _speak_exit():
            try:
                self.emit_state("EXECUTING")
                self.jarvis.vocal.say(en_phrase)
            except Exception:
                pass
            finally:
                try:
                    self.emit_state("IDLE")
                except Exception:
                    pass

        threading.Thread(target=_speak_exit, daemon=True).start()

        self.jarvis.short_term_memory.append({
            "time": time.strftime("%H:%M:%S"),
            "user": "[System Standby] 退场",
            "jarvis": en_phrase
        })
        if len(self.jarvis.short_term_memory) > 10:
            self.jarvis.short_term_memory.pop(0)
        try:
            self.jarvis.hippocampus.seal_chat_async(
                self.jarvis.gemini_key, "[System Standby] 退场", en_phrase,
                memory_protocol={"memory_type": "STANDBY"}
            )
        except:
            pass

    def _detect_joke_feedback(self, cmd: str):
        try:
            stm = self.jarvis.short_term_memory
            if not stm:
                return
            last_entry = stm[-1]
            last_user = last_entry.get("user", "")
            if "[智能轻推]" not in str(last_user):
                return
            if "atmosphere" not in str(last_user) and "screen_tease" not in str(last_user):
                return

            cmd_lower = cmd.lower()
            dismissive_patterns = [
                "not funny", "not that funny", "not a joke", "not joking",
                "this is normal", "it's normal", "that's normal", "its normal",
                "很正常", "不好笑", "没意思", "无聊", "这很正常",
                "没什么好笑", "不好笑啊", "这有什么好笑", "有什么好笑",
                "别开玩笑了", "不要开玩笑", "别闹", "行了",
                "stop joking", "stop it", "enough", "that's enough",
                "i'm serious", "im serious", "seriously",
                "not really", "not at all", "whatever",
                "so what", "big deal", "what's funny",
            ]
            is_dismissive = any(p in cmd_lower for p in dismissive_patterns)

            if not is_dismissive:
                return

            nudge_type_str = str(last_user)
            for entry in reversed(stm):
                user_str = str(entry.get("user", ""))
                if "screen_tease" in user_str or "atmosphere" in user_str:
                    nudge_type_str = user_str
                    break

            if hasattr(self, 'humor_memory'):
                hm = self.humor_memory
                recent = hm.get_recent_topics(max_age_seconds=600)
                if recent:
                    topic = recent[-1]
                    hm.lower_topic_weight(topic, 0.5)
                    print(f"🎭 [Humor Feedback] Negative response detected, lowering topic '{topic}' weight")
        except:
            pass

    # [R7-β1/post-test] 通用"拒绝词典"，与 _detect_help_refusal / NudgeGate freeze 共用
    _GENERIC_REFUSAL_PATTERNS = [
        # 英文（按"短而精确"排，避免误伤）
        "no thanks", "no thank you", "thanks but no",
        "i'm fine", "im fine", "i am fine", "it's fine", "its fine",
        "i'm ok", "im ok", "i am ok", "it's ok", "its ok",
        "i'm good", "im good", "i am good",
        "i got it", "i've got it", "ive got it",
        "i'll fix", "ill fix", "i will fix", "i can fix",
        "i'll handle", "ill handle", "i will handle",
        "not now", "leave it", "let it be", "forget it",
        "stop offering", "stop suggesting",
        # 中文
        "不需要", "不用", "不必", "没事", "算了", "不用了",
        "我自己", "自己来", "自己能", "我可以", "我能",
        "别再提", "别再说", "够了", "停下", "停止帮助",
        "不需要你的帮助", "不要你的帮助",
    ]

    # [R7-β post-test v3] 强拒绝词典 —— 命中即触发硬冻结 300s（NudgeGate.freeze_for），
    # 即使 stm[-5:] 没看见 offer_help、即使 Conductor 路径 B 用 is_urgent=True 也吵不到 Sir
    # 设计意图：用户说出这些话本身就是明确"暂时别再说话"的信号，不需要再去看上下文
    _STRONG_REFUSAL_PATTERNS = [
        "不需要你的帮助", "不要你的帮助", "不要再提", "别再提", "别再说", "别再来",
        "不要打扰", "别打扰", "闭嘴", "安静一下", "停止帮助", "你别说话",
        "stop offering", "stop suggesting", "stop talking", "stop interrupting",
        "leave me alone", "i don't need help", "i don't need your help",
        "i dont need help", "i dont need your help", "shut up", "be quiet",
    ]

    def _detect_help_refusal(self, cmd: str):
        """检测用户的"拒绝帮助"信号。R7-β1/post-test 改造：
        
        - 旧版只看 stm[-1]，但 offer_help 后用户可能先说别的（"你在干嘛"），导致下一句
          "不需要帮助"找不到 stm[-1] = offer_help → 拒绝信号被丢。新版扫描最近 15 条 STM
          + 30 分钟内 [智能轻推]/[Smart Nudge] 都算"有过 offer_help"。
        - v3：新增 _STRONG_REFUSAL_PATTERNS 强拒绝词典，命中即 5 分钟硬冻结，
          且硬冻结连 Conductor 的 is_urgent=True 也绕不过。
        - 通用否定（"不需要" / "no thanks"）即便没有近期 offer_help 也会触发 90s 短冷冻。
        - [P0+20-β.1.4 / 2026-05-16] 加自我打断白名单（治 B3）：
          Sir 12:43 实测 "跟我说说啊，不对不对不对，不用不用跟我说，我我要跟你说，
          我我两点起床" 被误识别成"拒绝帮助"→ NudgeGate 全通道硬冻结 300s。
          其实 Sir 在自我修正（"不对不对" + "我要跟你说"），不是拒绝 Jarvis。
        """
        try:
            cmd_lower = (cmd or "").lower().strip()
            if not cmd_lower:
                return
            is_strong_refusal = any(p in cmd_lower for p in self._STRONG_REFUSAL_PATTERNS)
            is_refusal = is_strong_refusal or any(p in cmd_lower for p in self._GENERIC_REFUSAL_PATTERNS)
            if not is_refusal:
                return

            # 🩹 [P0+20-β.1.4 / 2026-05-16] 自我打断 pre-filter：仅对非强拒绝生效。
            # 强拒绝（"shut up" / "leave me alone" / "不要再提"）即便有口吃修正也按拒绝处理。
            if not is_strong_refusal:
                self_interruption_patterns = [
                    r'不对不对',
                    r'不是不是',
                    r'不不不',
                    r'(?:no\s+){2,}',
                    r'我我[^\s,，。.]',
                    r'(我要|我想|我得|我会|我得).{0,12}(跟你|和你|给你|对你|跟我自己).{0,3}说',
                    r'(?:wait|hold|hang)\s+on',
                    r'let\s+me\s+(say|tell|explain|finish)',
                    r'(等[一下下]|等等|等我说)',
                    r'(?:um|uh|er|呃|嗯).{0,6}我',
                ]
                import re as _re_si
                for pat in self_interruption_patterns:
                    if _re_si.search(pat, cmd_lower):
                        try:
                            from jarvis_utils import bg_log as _si_bg
                            _si_bg(
                                f"🩹 [Help Refusal/SelfInterrupt] 自我打断白名单跳过："
                                f"'{cmd_lower[:60]}' (matched={pat})"
                            )
                        except Exception:
                            pass
                        return

            stm = self.jarvis.short_term_memory or []
            # [v3] 扩大扫描：最近 15 条 + 30 分钟内的 nudge 痕迹（智能轻推/Smart Nudge/Conductor）
            now = time.time()
            window_start = now - 1800.0  # 30 min
            had_offer_help = False
            for entry in stm[-15:]:
                user_field = str(entry.get("user", ""))
                if any(tag in user_field for tag in (
                    "offer_help", "[智能轻推]", "[Smart Nudge]", "Smart Nudge",
                    "[Conductor]", "[Proactive", "Offer Help", "调度中心",
                )):
                    had_offer_help = True
                    break
                # 时间戳兜底（如果 entry 带 time 字符串可与 now 对照，简化跳过）

            cc = getattr(self.jarvis, 'companion_center', None)
            if cc is not None and hasattr(cc, 'smart_nudge') and cc.smart_nudge:
                sn = cc.smart_nudge
                fingerprint = getattr(sn, '_last_help_fingerprint', '') or 'generic'
                existing = [h for h in sn._help_refusal_history if h['fingerprint'] == fingerprint]
                if existing:
                    existing[0]['count'] = existing[0].get('count', 1) + 1
                    existing[0]['time'] = now
                else:
                    sn._help_refusal_history.append({
                        'fingerprint': fingerprint,
                        'time': now,
                        'count': 1
                    })
                # 强拒绝直接给 1800s（30 min），普通拒绝按动态冷却（至少 300s）
                if is_strong_refusal:
                    cooldown = 1800.0
                else:
                    cooldown = max(sn._calc_help_cooldown(fingerprint), 300.0)
                sn._refused_help_until = max(sn._refused_help_until, now + cooldown)
                count = existing[0]['count'] if existing else 1

                # [P0+18-f.3 / 2026-05-15] type-specific long-term mute
                # 如果 15min 内有 nudge 投递过，把那个 nudge_type mute 12-24h
                # 强拒绝 24h / 普通 12h；这样 Sir 说"不用再提"后，同款 nudge 当日/半日不再来
                last_nudge_type = getattr(sn, '_last_nudge_type', '') or ''
                last_nudge_time = getattr(sn, '_last_nudge_time', 0.0) or 0.0
                if last_nudge_type and (now - last_nudge_time) < 900.0:
                    if is_strong_refusal:
                        mute_seconds = 86400.0  # 24h
                    else:
                        mute_seconds = 43200.0  # 12h
                    existing_until = sn._muted_nudge_types.get(last_nudge_type, 0.0)
                    sn._muted_nudge_types[last_nudge_type] = max(existing_until, now + mute_seconds)
                    try:
                        from jarvis_utils import bg_log as _mute_log
                        _hours = mute_seconds / 3600.0
                        _mute_log(f"🔇 [SmartNudge/TypeMuted] {last_nudge_type} muted for {_hours:.0f}h "
                                  f"(Sir said stop {('strongly' if is_strong_refusal else '')}).")
                    except Exception:
                        pass

                # [轴 1.6 / 2026-05-15] 改 bg_log：原 print 在 GBK 终端因 emoji 抛 UnicodeEncodeError，
                # 被 outer try/except 静默吞掉 → 整个方法挂掉、freeze_for 永远不调用
                # 这是 v3/v4 上"用户说'不需要帮助'后 Conductor 仍然催"的真根因
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🚫 [Help Refusal] 用户拒绝帮助 (#{count}, strong={is_strong_refusal}), "
                           f"fingerprint={fingerprint[:40]}, 动态冷却 {cooldown:.0f}s, had_nudge_in_15={had_offer_help}")
                except Exception:
                    pass

            # [v3] freeze NudgeGate（硬冻结，is_urgent 也绕不过）
            # - 强拒绝 → 300s 硬冻结
            # - 弱信号 + 近 nudge → 300s 硬冻结
            # - 弱信号 + 无近 nudge → 90s 硬冻结（保留兜底）
            nudge_gate = getattr(self.jarvis, 'nudge_gate', None)
            if nudge_gate is not None and hasattr(nudge_gate, 'freeze_for'):
                if is_strong_refusal:
                    freeze_seconds = 300.0
                elif had_offer_help:
                    freeze_seconds = 300.0
                else:
                    freeze_seconds = 90.0
                try:
                    nudge_gate.freeze_for(freeze_seconds, source='user_rejection')
                    # [轴 1.6] 同上：改 bg_log，避免 GBK 终端 emoji 抛 UnicodeEncodeError 丢消息
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"🧊 [NudgeGate HardFreeze] 用户拒绝信号 → 全通道硬冻结 {int(freeze_seconds)}s "
                               f"(strong={is_strong_refusal})")
                    except Exception:
                        pass
                except Exception:
                    pass

            # event_bus 投递（让主脑下一轮 prompt 能引用）
            try:
                bus = getattr(self.jarvis, 'event_bus', None)
                if bus is not None:
                    bus.publish(
                        etype='help_refused',
                        description=f"Sir rejected help: '{cmd[:60]}'"
                                    + (' (STRONG)' if is_strong_refusal else '')
                                    + (' (after nudge)' if had_offer_help else ''),
                        source='_detect_help_refusal',
                        metadata={'had_offer_help_in_5': had_offer_help,
                                  'is_strong': is_strong_refusal},
                    )
            except Exception:
                pass
        except Exception:
            pass

    # [v5.1 / Sir-2026-05-15] Sleep Intent 检测 —— 修"重复催睡"
    # 起因：Sir 说"I will go to sleep. 我马上回去睡觉，再过半小时左右吧"之后，
    # Conductor 仍然在 6 分钟 / 10 分钟 / 14 分钟时连催 late_night / suggest_break 三次。
    # 根因：Conductor / SmartNudge 都不读 STM，独立按"夜深 + 屏幕亮"信号决定催睡。
    # 修法：检测 Sir 的睡眠表态 → 设 worker._sleep_intent_until 窗口 → 两个发送端在窗口内
    # 静默 sleep 相关 nudge。
    _SLEEP_INTENT_PATTERNS = [
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
        r"我.{0,8}(?:会|要|得|该|打算|准备|应该|可能|大概|估计|差不多).{0,15}(?:点|时|分).{0,12}(?:睡|休息|去睡|睡觉|睡了|关机|下线|歇)",
        r"我.{0,8}(?:会|要|得|打算).{0,8}(?:在|于|到了).{0,15}(?:睡|休息|睡觉|睡了|关机|下线|歇)",
        r"(?:等下|等一下|等会|等会儿|晚点|迟点|稍后|过会|过一会|过会儿).{0,10}(?:睡|休息|睡觉|睡了)",
        r"(?:我)?\s*(?:差不多|大概|应该|估计|可能).{0,10}(?:点|时).{0,12}(?:睡|休息|睡觉|睡了)",
        # "今晚"/"今天晚上"/"待会儿" + 睡 / "今晚就/今晚要"
        r"(?:今晚|今天晚上|今夜|待会儿?).{0,10}(?:睡|休息|睡觉|关机|下线|休息)",
    ]

    # 时间提取：捕获"30 分钟" / "half hour" / "一小时" 等。命中越早越具体优先。
    _SLEEP_TIME_EXTRACTORS = [
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
    _CN_DIGIT_MAP = {
        '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '俩': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12,
    }
    _SLEEP_DEFAULT_DELAY_SEC = 1800  # 默认 30 分钟
    _SLEEP_GRACE_SEC = 900           # 目标时间到了还多给 15 分钟 grace

    def _detect_sleep_intent(self, cmd: str):
        """[v5.1 / P0-2 expanded 2026-05-15 / P0+12 注] 检测 Sir 表态'X 分钟后睡'或'X 点睡' → 设置静默催睡窗口。
        与 CentralNerve._detect_sleep_intent **同名异义**（后者触发"全床深度休眠"模式）。
        建议新代码改用别名 _detect_sleep_window_intent 让语义清晰；保留本名兼容现有测试与日志。

        命中即更新 self._sleep_intent_until = now + delay + grace。
        Conductor._execute_path_b / SmartNudgeSentinel._dispatch_nudge 在发 sleep 类
        nudge 前查这个窗口，命中即静默 + bg_log。

        支持三种时间锚定（优先级从高到低）：
        1. 绝对时间点："两点睡觉" / "在2点睡" / "凌晨3点" → 解析为距那个钟点的秒数
        2. 相对延迟："30 分钟后" / "半小时后" / "一会儿"
        3. 默认延迟：1800s（30 分钟）
        """
        try:
            if not cmd or cmd.startswith("__NUDGE__:"):
                return
            text = cmd.lower().strip()
            if not text:
                return
            if not any(re.search(p, text) for p in self._SLEEP_INTENT_PATTERNS):
                return

            delay_sec = None

            # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 优先级 0：immediate 关键词
            # 治 Sir 13:16 实测 BUG："我现在就去睡觉" 被默认 30min 兜底
            # → 静默窗口拖到 14:01，Sir 等不到夜间监督。
            # 命中即 delay_sec=0（仍加 _SLEEP_GRACE_SEC 给监督留 buffer）
            # 守门：text 含相对/绝对时间锚时跳过 immediate，让正常解析优先。
            _HAS_TIME_ANCHOR = bool(re.search(
                r'\d+\s*(?:分钟|分|min(?:ute)?s?|小时|hours?|hrs?)|'
                r'(?:半|半个|一个|两个|个把)\s*(?:小时|hour)|'
                r'(?:再过|过|等|大概|大约|差不多|约|左右)|'
                r'[一二两俩三四五六七八九十\d]{1,2}\s*点|'
                r'\d{1,2}:\d{2}|'
                r'(?:at|by|in|around|near|until|before|after)\s+\d|'
                r'half\s+(?:an?\s+)?hour',
                text, re.IGNORECASE
            ))
            _IMMEDIATE_PATTERNS = (
                # 中文：现在/马上/立刻/立即/这就 + 任意 0-4 字 + 睡|床|去睡
                r'现在\s*.{0,4}?(?:就)?(?:去|上)?\s*(?:睡|床)',
                r'马上\s*.{0,4}?(?:去|上)?\s*(?:睡|床)',
                r'立(?:刻|即|马)\s*.{0,4}?(?:去|上)?\s*(?:睡|床)',
                r'这就\s*.{0,4}?(?:去|上)?\s*(?:睡|床)',
                r'(?:我)?去睡(?:觉|了)',
                r'我现在就(?:去|要)',  # 兜底："我现在就去 X" 即便 X 不是睡 (sleep_intent_patterns 已守门)
                # 英文
                r"going\s+to\s+(?:sleep|bed)\s+now",
                r"i'?m\s+(?:off\s+to\s+)?bed",
                r"time\s+(?:for|to)\s+(?:sleep|bed)",
                r"heading\s+to\s+bed",
                r"\bright\s+now\b",
                r"\bimmediately\b",
                r"sleep\s+now",
            )
            if not _HAS_TIME_ANCHOR and any(re.search(p, text) for p in _IMMEDIATE_PATTERNS):
                delay_sec = 0

            # 优先级 1：绝对时间点 — 中文"X 点 / X 点 N 分"，X 可以是中文数字
            # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 加 if delay_sec is None: 守门，
            # 否则优先级 0 (immediate) 设的 delay_sec=0 会被本分支误覆盖
            cn_hour_pat = r"(?:凌晨|早上|早晨|上午|中午|下午|晚上|今晚)?\s*([一二两俩三四五六七八九十]|十一|十二|\d{1,2})\s*点(?:\s*(半|[一二三四五六七八九十]\d?|\d{1,2})\s*分?)?"
            m_cn = re.search(cn_hour_pat, text) if delay_sec is None else None
            if m_cn:
                try:
                    hour_str = m_cn.group(1)
                    if hour_str.isdigit():
                        hour = int(hour_str)
                    else:
                        hour = self._CN_DIGIT_MAP.get(hour_str, -1)
                    minute = 0
                    min_str = m_cn.group(2) or ''
                    if min_str == '半':
                        minute = 30
                    elif min_str.isdigit():
                        minute = min(59, int(min_str))
                    elif min_str in self._CN_DIGIT_MAP:
                        minute = self._CN_DIGIT_MAP[min_str]

                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        now_local = time.localtime()
                        # 凌晨上下文：当前 < 6 点时，小数字（hour < 12）保留为凌晨；其他时段补 12
                        if now_local.tm_hour < 6:
                            adj_hour = hour
                        elif 6 <= now_local.tm_hour < 12:
                            adj_hour = hour + 12 if hour < 12 else hour
                        else:
                            adj_hour = hour + 12 if hour < 12 else hour
                        # 显式带"凌晨/早上"则强制 AM；带"下午/晚上"则强制 PM
                        prefix = m_cn.group(0)[:m_cn.group(0).index(hour_str)] if hour_str in m_cn.group(0) else ''
                        if any(am_kw in prefix for am_kw in ('凌晨', '早上', '早晨', '上午')):
                            adj_hour = hour if hour != 12 else 0
                        elif any(pm_kw in prefix for pm_kw in ('下午', '晚上', '今晚')):
                            adj_hour = hour + 12 if hour < 12 else hour
                        if adj_hour >= 24:
                            adj_hour -= 24
                        target_ts = time.mktime((now_local.tm_year, now_local.tm_mon, now_local.tm_mday,
                                                  adj_hour, minute, 0,
                                                  now_local.tm_wday, now_local.tm_yday, now_local.tm_isdst))
                        if target_ts < time.time() - 600:
                            target_ts += 86400
                        gap = target_ts - time.time()
                        # 防极端：> 18 小时视为可疑（凌晨上下文兜底）
                        if 60 <= gap <= 64800:
                            delay_sec = int(gap)
                except Exception:
                    pass

            # 优先级 1b：英文"at X" / "by X" / "X o'clock"
            if delay_sec is None:
                en_hour_pat = r"(?:at|by|around|near)\s+(\d{1,2})(?:\s*:\s*(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
                m_en = re.search(en_hour_pat, text)
                if m_en:
                    try:
                        hour = int(m_en.group(1))
                        minute = int(m_en.group(2)) if m_en.group(2) else 0
                        ap = (m_en.group(3) or '').lower().replace('.', '')
                        now_local = time.localtime()
                        if ap == 'pm' and hour != 12:
                            hour += 12
                        elif ap == 'am' and hour == 12:
                            hour = 0
                        elif not ap:
                            if now_local.tm_hour < 6 and hour < 12:
                                pass
                            elif hour < 12:
                                hour += 12
                        if 0 <= hour <= 23:
                            target_ts = time.mktime((now_local.tm_year, now_local.tm_mon, now_local.tm_mday,
                                                      hour, minute, 0,
                                                      now_local.tm_wday, now_local.tm_yday, now_local.tm_isdst))
                            if target_ts < time.time() - 600:
                                target_ts += 86400
                            gap = target_ts - time.time()
                            if 60 <= gap <= 64800:
                                delay_sec = int(gap)
                    except Exception:
                        pass

            # 优先级 2：相对延迟（已有逻辑）
            if delay_sec is None:
                for pat, fn in self._SLEEP_TIME_EXTRACTORS:
                    m = re.search(pat, text)
                    if m:
                        try:
                            delay_sec = fn(m)
                        except Exception:
                            delay_sec = self._SLEEP_DEFAULT_DELAY_SEC
                        break

            # 优先级 3：默认
            if delay_sec is None:
                delay_sec = self._SLEEP_DEFAULT_DELAY_SEC

            new_until = time.time() + delay_sec + self._SLEEP_GRACE_SEC
            old_until = getattr(self, '_sleep_intent_until', 0.0)
            self._sleep_intent_until = max(old_until, new_until)

            try:
                from jarvis_utils import bg_log
                mins = int(delay_sec / 60)
                until_str = time.strftime('%H:%M', time.localtime(self._sleep_intent_until))
                bg_log(f"🌙 [Sleep Intent] Sir 表态约 {mins} 分钟后睡 → 静默 late_night/suggest_break 至 {until_str}")
            except Exception:
                pass

            try:
                bus = getattr(self.jarvis, 'event_bus', None)
                if bus is not None:
                    bus.publish(
                        etype='sleep_intent_declared',
                        description=f"Sir said he'll sleep in ~{int(delay_sec/60)} min",
                        source='_detect_sleep_intent',
                        metadata={
                            'delay_seconds': delay_sec,
                            'expires_at': self._sleep_intent_until,
                            'cmd_excerpt': cmd[:80],
                        },
                    )
            except Exception:
                pass
        except Exception:
            pass

    # [P0+12 / 2026-05-15] 语义清晰别名 — 与 CentralNerve._detect_deep_sleep_request 区分
    def _detect_sleep_window_intent(self, cmd: str):
        """语义别名：检测"Sir 表态 X 分钟后睡"软窗口（仅静默 sleep 类 nudge）。
        与 CentralNerve._detect_deep_sleep_request 不同（后者触发深度休眠 + 数据归档）。
        """
        return self._detect_sleep_intent(cmd)

    def run(self):
        # ⚡ 模糊脊髓反射词典 (巨量扩充版)
        reflex_dict = {
            # --- 存在性确认 (Are you there?) ---
            "are you there": "At your service, sir.",
            "you there": "At your service, sir.",
            "your there": "At your service, sir.",
            "you layer": "At your service, sir.",     # 空耳
            "you bear": "At your service, sir.",      # 空耳
            "you hair": "At your service, sir.",      # 空耳
            "all you there": "At your service, sir.", # 空耳
            "are you dare": "At your service, sir.",  # 空耳
            "you online": "I am online and ready, sir.",
            "are you online": "I am online and ready, sir.",
            "you listening": "Always listening, sir.",
            
            # --- 唤醒词 (Wake up / Are you up?) ---
            "wake up": "At your service, sir.",
            "are you up": "At your service, sir.",
            "you up": "At your service, sir.",
            "awake": "At your service, sir.",
            "me up": "At your service, sir.",         # 空耳
            "make up": "At your service, sir.",       # 空耳
            "wait up": "At your service, sir.",       # 空耳
            "way cup": "At your service, sir.",       # 空耳
            "weigh cup": "At your service, sir.",     # 空耳
            "wake out": "At your service, sir.",      # 空耳
            "woke up": "At your service, sir.",       # 空耳

            # --- 单呼名字 (Jarvis 英文发音极其容易崩坏) ---
            "jarvis": "I am here, sir.",
            "jervis": "I am here, sir.",              # 空耳
            "travis": "I am here, sir.",              # 空耳
            "charles": "I am here, sir.",             # 空耳
            "chavez": "I am here, sir.",              # 空耳
            "java": "I am here, sir.",                # 空耳
            "drivers": "I am here, sir.",             # 空耳
            "joce": "I am here, sir.",                # 空耳
            "jovis": "I am here, sir.",               # 空耳
            "just": "I am here, sir.",                # 空耳
            "garbage": "I am here, sir.",             # 极其常见的英文ASR悲剧空耳...
            
            # --- 单呼名字 (中文发音容错) ---
            "贾维斯": "Yes, sir.",
            "加维斯": "Yes, sir.",
            "家维斯": "Yes, sir.",
            "查维斯": "Yes, sir.",
            "甲苯斯": "Yes, sir.",                    # 空耳
            "假维斯": "Yes, sir.",                    # 空耳
            "假装是": "Yes, sir.",                    # 中文极度离谱空耳
            "夹尾巴": "Yes, sir.",                    # 甚至这个都有可能

            # --- 告退与物理静音 (Stand down / 退下) ---
            "stand down": "Entering silent mode, sir.",
            "stan down": "Entering silent mode, sir.",  # 空耳
            "sand down": "Entering silent mode, sir.",  # 空耳
            "send down": "Entering silent mode, sir.",  # 空耳
            "stamp down": "Entering silent mode, sir.", # 空耳
            "shut up": "Entering silent mode, sir.",
            "shut down": "Entering silent mode, sir.",
            "go to sleep": "Entering silent mode, sir.",
            "go sleep": "Entering silent mode, sir.",
            "dismiss": "Entering silent mode, sir.",
            "dismissed": "Entering silent mode, sir.",
            "this miss": "Entering silent mode, sir.",  # 空耳
            "退下": "Entering silent mode, sir.",
            "推下": "Entering silent mode, sir.",       # 空耳
            "腿下": "Entering silent mode, sir.",       # 空耳
            "跪下": "Entering silent mode, sir.",       # 空耳 (退下 容易听成 跪下)
            "退学": "Entering silent mode, sir.",       # 空耳
            "休息": "Entering silent mode, sir.",
            "闭嘴": "Entering silent mode, sir.",
            "安静": "Entering silent mode, sir."
        }
        
        if not hasattr(self, "_dream_compressed"):
            self.jarvis.hippocampus.compress_chat_history(self.jarvis.gemini_key, days=7)
            self._dream_compressed = True
        
        while True:
            if not self.cmd_queue.empty():
                cmd = self.cmd_queue.get()

                if hasattr(self.jarvis, 'key_router') and self.jarvis.key_router:
                    _cmd_lower = cmd.lower().strip()
                    if any(kw in _cmd_lower for kw in ['i know', '我知道了', '知道了', 'got it', 'okay', 'understood', '明白']):
                        if self.jarvis.key_router.is_openrouter_active():
                            self.jarvis.key_router.acknowledge_openrouter_alert()
                            print("✅ [KeyRouter] OpenRouter 提醒已确认，今日不再提醒。")

                if not cmd.startswith("__NUDGE__:") and hasattr(self.chat_bypass, 'subtitle_queue'):
                    # 绝对禁止后台线程直接调用 UI，改用安全队列投递！
                    self.chat_bypass.subtitle_queue.put(("user", cmd))

                if not cmd.startswith("__NUDGE__:") and hasattr(self, 'humor_memory'):
                    self._detect_joke_feedback(cmd)
                    self._detect_help_refusal(cmd)
                    # [v5.1 / Sir-2026-05-15] 检测"我 X 分钟后睡"——设静默窗口防 Conductor 重复催睡
                    self._detect_sleep_intent(cmd)

                matched_reflex = False
                cmd_lower = cmd.lower().strip()
                import re 
                cmd_clean = re.sub(r'[^\w\s]', '', cmd_lower)
                
                # 🛡️ 第一重锁：超长句子直接放行给大模型（比如设定闹钟的长句）
                if len(cmd_clean.split()) <= 6 and len(cmd_clean) <= 30:
                    for key, response in reflex_dict.items():
                        key_clean = re.sub(r'[^\w\s]', '', key.lower())
                        
                        # 🛡️ 第二重锁：原话和字典词的长度差绝不能超过 6 个字符！
                        if abs(len(cmd_clean) - len(key_clean)) <= 6:
                            if key_clean in cmd_clean or fuzz.ratio(key_clean, cmd_clean) >= 85:
                                matched_reflex = True
                                break
                            
                if matched_reflex:
                    is_sleep_cmd = (response == "Entering silent mode, sir.")
                    
                    if getattr(self, 'is_awake', False) and not is_sleep_cmd:
                        if hasattr(self, 'return_sentinel') and self.return_sentinel and self.return_sentinel.soft_focus_active:
                            pass
                        else:
                            print(f"👻 [Guard] Already in focus mode, ignoring redundant wake word: '{cmd}'")
                            continue 
                        
                    print(f"⚡ [Spinal Reflex] Command received: '{cmd}'")
                    
                    if is_sleep_cmd:
                        # [R7-α/B1] reason='sleep_cmd'：用户喊"退下"等
                        if self.state is not None:
                            self.state.set_awake(False, reason='sleep_cmd', source='reflex_match')
                        if hasattr(self.chat_bypass, 'audio_queue'):
                            self.state_changed.emit("EXECUTING")
                            self.chat_bypass.audio_queue.put((response, {}))
                        else:
                            self.state_changed.emit("EXECUTING")
                            self.jarvis.vocal.say(response)
                            self.state_changed.emit("IDLE")

                        self.jarvis.short_term_memory.append({
                            "time": time.strftime("%H:%M:%S"),
                            "user": cmd,
                            "jarvis": response
                        })
                        if len(self.jarvis.short_term_memory) > 10:
                            self.jarvis.short_term_memory.pop(0)
                        try:
                            self.jarvis.hippocampus.seal_chat_async(
                                self.jarvis.gemini_key, cmd, response,
                                memory_protocol={"memory_type": "SPINAL_REFLEX"}
                            )
                        except:
                            pass
                        continue

                    dynamic_en, dynamic_zh = None, None
                    if hasattr(self, 'return_sentinel') and self.return_sentinel:
                        dynamic_en, dynamic_zh = self.return_sentinel.get_dynamic_wake_response(cmd)

                    if dynamic_en:
                        print(f"🏠 [Dynamic Wake] Context-aware response...")
                        print(_box_newline(f"║ 🤖  [Jarvis] {dynamic_en}"))
                        if dynamic_zh:
                            print(_box_newline(f"║ 📺  [Subtitle] {dynamic_zh}"))
                        print("╚" + "═"*63 + "\n")

                        # [R7-α/B1] reason='dynamic_wake'：ReturnSentinel 给的上下文唤醒应答
                        if self.state is not None:
                            self.state.set_awake(True, reason='dynamic_wake', source='reflex_match')
                        if hasattr(self, 'status_ledger'):
                            self.status_ledger.force_update_async()

                        if hasattr(self.chat_bypass, 'audio_queue'):
                            self.state_changed.emit("EXECUTING")
                            self.chat_bypass.audio_queue.put((dynamic_en, {}))
                        else:
                            self.state_changed.emit("EXECUTING")
                            self.jarvis.vocal.say(dynamic_en)
                            self.state_changed.emit("IDLE")

                        if hasattr(self, 'voice_thread'):
                            self.voice_thread.in_active_conversation = True
                            self.voice_thread.last_interaction_time = time.time()
                            self.voice_thread.awake_signal.emit(True)

                        self.jarvis.short_term_memory.append({
                            "time": time.strftime("%H:%M:%S"),
                            "user": cmd,
                            "jarvis": dynamic_en
                        })
                        if len(self.jarvis.short_term_memory) > 10:
                            self.jarvis.short_term_memory.pop(0)
                        try:
                            self.jarvis.hippocampus.seal_chat_async(
                                self.jarvis.gemini_key, cmd, dynamic_en,
                                memory_protocol={"memory_type": "SPINAL_REFLEX"}
                            )
                        except:
                            pass
                    else:
                        # [R7-α/B1] reason='reflex_wake'：脊髓反射词典匹配（"Jarvis"/"贾维斯"等）
                        if self.state is not None:
                            self.state.set_awake(True, reason='reflex_wake', source='reflex_match')
                        if hasattr(self, 'status_ledger'):
                            self.status_ledger.force_update_async()

                        if hasattr(self.chat_bypass, 'audio_queue'):
                            self.state_changed.emit("EXECUTING")
                            self.chat_bypass.audio_queue.put(response)
                        else:
                            self.state_changed.emit("EXECUTING")
                            self.jarvis.vocal.say(response)
                            self.state_changed.emit("IDLE")

                        self.jarvis.short_term_memory.append({
                            "time": time.strftime("%H:%M:%S"),
                            "user": cmd,
                            "jarvis": response
                        })
                        if len(self.jarvis.short_term_memory) > 10:
                            self.jarvis.short_term_memory.pop(0)
                        try:
                            self.jarvis.hippocampus.seal_chat_async(
                                self.jarvis.gemini_key, cmd, response,
                                memory_protocol={"memory_type": "SPINAL_REFLEX"}
                            )
                        except:
                            pass
                    continue

                if cmd.startswith("__NUDGE__:"):
                    try:
                        nudge_json_str = cmd[len("__NUDGE__:"):]
                        nudge_context = json.loads(nudge_json_str)
                        nudge_type = nudge_context.get("type", "unknown")
                        # [R7-α/NudgeChannel] 三档分流：voice / silent_text / visual_pulse
                        nudge_channel = nudge_context.get('channel', 'voice')

                        if hasattr(self.jarvis, 'nudge_gate') and self.jarvis.nudge_gate.is_sleep_mode():
                            if nudge_type not in ('return_greeting',):
                                continue

                        # [R7-α/NudgeChannel] SILENT_TEXT 档：不调 LLM、不出声，
                        # 只字幕飘过 + STM 写一行 + event_bus 投递。
                        if nudge_channel == 'silent_text':
                            try:
                                from jarvis_utils import render_silent_nudge_text, bg_log
                                _silent_text = render_silent_nudge_text(nudge_type, nudge_context)
                                # 字幕：用 "user" 频道展示但带标记，让 SubtitleOverlay 知道这是静默 nudge
                                if hasattr(self.chat_bypass, 'subtitle_queue'):
                                    self.chat_bypass.subtitle_queue.put(("silent_nudge", _silent_text))
                                # STM 留痕
                                self.jarvis.short_term_memory.append({
                                    "time": time.strftime("%H:%M:%S"),
                                    "user": f"[静默轻推] {nudge_type}",
                                    "jarvis": _silent_text + " [SILENT_TEXT 通道：未出声]"
                                })
                                if len(self.jarvis.short_term_memory) > 10:
                                    self.jarvis.short_term_memory.pop(0)
                                # event_bus 投递
                                try:
                                    bus = getattr(self.jarvis, 'event_bus', None)
                                    if bus is not None:
                                        bus.publish(
                                            etype='proactive_nudge',
                                            description=f"silent_text:{nudge_type}: {_silent_text[:80]}",
                                            source='silent_nudge',
                                            metadata={'nudge_type': nudge_type, 'channel': 'silent_text'},
                                        )
                                except Exception:
                                    pass
                                bg_log(f"🤫 [SilentNudge/{nudge_type}] {_silent_text[:80]}")
                            except Exception as _e:
                                try:
                                    from jarvis_utils import bg_log as _bg
                                    _bg(f"⚠️ [Silent Nudge Error]: {_e}")
                                except Exception:
                                    pass
                            continue  # 不进入 voice 分支

                        # [R7-α/NudgeChannel] VISUAL_PULSE 档：完全不字幕不出声，
                        # 只 publish 一条 event_bus + STM 留痕。
                        # （R7-β 接 BreathingLight 加一次金光呼吸；当前先把数据流接通）
                        if nudge_channel == 'visual_pulse':
                            try:
                                from jarvis_utils import bg_log
                                _vp_text = nudge_context.get('silent_text') or f"{nudge_type}: brief ready"
                                self.jarvis.short_term_memory.append({
                                    "time": time.strftime("%H:%M:%S"),
                                    "user": f"[视觉脉冲] {nudge_type}",
                                    "jarvis": _vp_text + " [VISUAL_PULSE 通道：仅呼吸灯]"
                                })
                                if len(self.jarvis.short_term_memory) > 10:
                                    self.jarvis.short_term_memory.pop(0)
                                try:
                                    bus = getattr(self.jarvis, 'event_bus', None)
                                    if bus is not None:
                                        bus.publish(
                                            etype='proactive_nudge',
                                            description=f"visual_pulse:{nudge_type}",
                                            source='visual_pulse',
                                            metadata={'nudge_type': nudge_type, 'channel': 'visual_pulse'},
                                        )
                                except Exception:
                                    pass
                                # 投递给 BreathingLight（R7-β 接住）
                                if hasattr(self.chat_bypass, 'subtitle_queue'):
                                    self.chat_bypass.subtitle_queue.put(("visual_pulse", nudge_type))
                                bg_log(f"💡 [VisualPulse/{nudge_type}] (no voice / no subtitle)")
                            except Exception as _e:
                                try:
                                    from jarvis_utils import bg_log as _bg
                                    _bg(f"⚠️ [Visual Pulse Error]: {_e}")
                                except Exception:
                                    pass
                            continue

                        # [R7-α/NudgeChannel] VOICE 档：保持原行为
                        # [P0+18-c.6 / 2026-05-15] 修 Sir 17:53 实测 BUG：return_greeting LLM 路径
                        # 破坏对话框 — set_browser_ducking 是 daemon 异步 bg_log，会在
                        # stream_nudge 已打开"╔/║ 🤖 [Jarvis]" 之后才 fire。当时
                        # set_conversation_active(False)，bg_log 直接写 stderr → 漏到 box 内部。
                        # 修法：voice 分支最顶端激活 conversation，所有 bg_log（含 BrowserDucking
                        # 异步 daemon、KeyRouter、Hippocampus 等）都进缓冲；finally 里
                        # subtitle 打完、╚ 框关闭后再 flush 到 ──── [Background] ──── 框。
                        try:
                            from jarvis_utils import set_conversation_active as _set_conv_active_c6
                            _set_conv_active_c6(True)
                        except Exception:
                            _set_conv_active_c6 = None

                        stm_context = "\n".join([f"{m['user']} -> {m['jarvis']}" for m in self.jarvis.short_term_memory[-6:]])
                        if len(stm_context) > 2000:
                            stm_context = "..." + stm_context[-2000:]

                        ltm_context = "暂无相关历史记录。"
                        try:
                            search_query = f"最近工作 当前项目 {nudge_type}"
                            ltm_results = self.jarvis.hippocampus.search_memory(self.jarvis.gemini_key, search_query, top_k=2)
                            if ltm_results:
                                ltm_context = ""
                                for r in ltm_results:
                                    time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['timestamp']))
                                    ltm_context += f"[{time_str}] Intent: {r['intent']} | Result: {r['summary']}\n"
                        except:
                            pass

                        self.state_changed.emit("THINKING")
                        if hasattr(self, 'voice_thread') and self.voice_thread:
                            self.voice_thread._suppress_wave = True
                        # [R7-β1/post-test] 主动 nudge 出声前压低浏览器音量
                        # 之前只在用户主动唤醒路径（VoiceListenThread）有 ducking；
                        # 主动 offer_help 路径漏了，导致 edge / chrome 直播声盖住 Jarvis
                        try:
                            set_browser_ducking(True)
                        except Exception:
                            pass
                        # [P0+9 / 2026-05-15] 把 stream_nudge 失败/抛错单独 catch + bg_log，
                        # 让 Sir 实测时一眼看到"为什么 Smart Nudge 显示开始响应但没出声"。
                        # 之前 stream_nudge 内部如果 LLM 返回空/抛错，外层只看 nudge_reply 是否真，
                        # 静默丢弃；用户体验是"╔...开始响应╔...║ 🤖 [Jarvis]"后没下文。
                        nudge_reply = None
                        _nudge_exc_repr = None
                        try:
                            nudge_reply = self.chat_bypass.stream_nudge(nudge_context, stm_context, ltm_context)
                        except Exception as _ne:
                            _nudge_exc_repr = repr(_ne)[:200]
                        finally:
                            if hasattr(self, 'voice_thread') and self.voice_thread:
                                self.voice_thread._suppress_wave = False
                            # [R7-β1/post-test] nudge 说完后 3s 再恢复浏览器音量
                            # （避免接下来用户秒答时音量瞬间跳回）
                            try:
                                import threading as _thr2
                                _thr2.Thread(
                                    target=lambda: (time.sleep(3.0), set_browser_ducking(False)),
                                    daemon=True,
                                ).start()
                            except Exception:
                                pass
                            # [P0+18-c.6] 对话激活复位：subtitle 已打完、╚ 框已关，flush 背景框
                            try:
                                if _set_conv_active_c6 is not None:
                                    _set_conv_active_c6(False)
                            except Exception:
                                pass

                        # [P0+9 / 2026-05-15] 失败/为空都打日志 + 把"未出声"信号 publish 到 event_bus，
                        # 让主脑下一轮 prompt 能看到"刚刚有个 nudge 计划但没出来"
                        if not nudge_reply:
                            try:
                                from jarvis_utils import bg_log as _nudge_bg_log
                                _nudge_bg_log(
                                    f"⚠️ [Nudge/NoSound] type={nudge_type} 未出声 — "
                                    f"reason={'exception:' + _nudge_exc_repr if _nudge_exc_repr else 'empty_reply'}"
                                )
                            except Exception:
                                pass
                            try:
                                bus = getattr(self.jarvis, 'event_bus', None)
                                if bus is not None:
                                    bus.publish(
                                        etype='nudge_no_sound',
                                        description=f"{nudge_type}: {_nudge_exc_repr or 'empty_reply'}",
                                        source='nudge_dispatch',
                                        metadata={'nudge_type': nudge_type,
                                                  'exception': _nudge_exc_repr},
                                    )
                            except Exception:
                                pass

                        if nudge_reply:
                            self.jarvis.short_term_memory.append({
                                "time": time.strftime("%H:%M:%S"),
                                "user": f"[智能轻推] {nudge_type}",
                                "jarvis": nudge_reply
                            })
                            if len(self.jarvis.short_term_memory) > 10:
                                self.jarvis.short_term_memory.pop(0)

                            if nudge_type in ("screen_tease", "atmosphere") and hasattr(self, 'humor_memory'):
                                topic_key = nudge_context.get("topic_key", "")
                                if topic_key:
                                    self.humor_memory.register_joke(topic_key, nudge_reply)

                            self.jarvis.hippocampus.seal_chat_async(
                                self.jarvis.gemini_key,
                                f"[智能轻推]: {nudge_type}",
                                nudge_reply,
                                memory_protocol={"memory_type": "NUDGE"}
                            )

                        self.state_changed.emit("IDLE")
                    except Exception as e:
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"⚠️ [Nudge Error]: {e}")
                        except Exception:
                            pass
                        self.state_changed.emit("IDLE")
                    
                    if nudge_type == "return_greeting" and hasattr(self, 'return_sentinel') and self.return_sentinel:
                        self.return_sentinel.soft_focus_active = True
                        self.return_sentinel.soft_focus_until = time.time() + 60.0
                        if hasattr(self, 'voice_thread'):
                            self.voice_thread.in_active_conversation = True
                            self.voice_thread.last_interaction_time = time.time()

                    # [P0-8 / 2026-05-15] check_in 是 Conductor 的"打个招呼"，与 return_greeting
                    # 走类似的 soft_focus 但更短（45s，让 Sir 想接就接，不想接也不会被多次打扰）。
                    if nudge_type == "check_in" and hasattr(self, 'return_sentinel') and self.return_sentinel:
                        self.return_sentinel.soft_focus_active = True
                        self.return_sentinel.soft_focus_until = time.time() + 45.0
                        if hasattr(self, 'voice_thread'):
                            self.voice_thread.in_active_conversation = True
                            self.voice_thread.last_interaction_time = time.time()

                    if nudge_type in ("offer_help", "commitment_check") and hasattr(self, 'return_sentinel') and self.return_sentinel:
                        self.return_sentinel.soft_focus_active = True
                        self.return_sentinel.soft_focus_until = time.time() + 90.0
                        self.return_sentinel._soft_focus_reason = nudge_type
                        if hasattr(self, 'voice_thread'):
                            self.voice_thread.in_active_conversation = True
                            self.voice_thread.last_interaction_time = time.time()
                            # 👇 Bug A 修复：原来这里写 mute_until=0.0 是为了让用户能秒回，
                            # 但同时也把 TTS 余音的防御窗口拆了 → Jarvis 听到自己的
                            # "Pylance seems rather displeased..." 拖尾音被 ASR 转成
                            # 用户输入。现在保留 set_speaking_state(IDLE) 留下的 0.6s
                            # 回声防御窗口（足够余音衰减但不影响用户响应）。
                        # [R6/Bus] 把 focus_lock 状态投递到总线，主脑下一轮 prompt 可以引用
                        try:
                            bus = getattr(self.jarvis, 'event_bus', None)
                            if bus is not None:
                                bus.publish(
                                    etype='soft_focus_active',
                                    description=f"awaiting reply to {nudge_type} (90s window)",
                                    source='focus_lock',
                                    metadata={'reason': nudge_type, 'window_seconds': 90},
                                )
                        except Exception:
                            pass
                        print(f"🎯 [Focus Lock] offer_help 焦点模式已激活 (90s)，等待 Sir 回复...")
                    continue
                
                # 如果没命中脊髓反射（是正常的聊天指令），大脑进入清醒状态
                # [R7-α/B1] reason='continuing_conversation'：正常对话路径
                if self.state is not None:
                    self.state.set_awake(True, reason='continuing_conversation', source='regular_chat')
                _t_pipeline_start = time.time()
                
                # 💡 核心手术：任务防线。如果贾维斯正在干活，绝对不去打扰主聊天脑，而是移交天启探针！
                if getattr(self.jarvis, 'is_active_task', False):
                    print(f"⚡ [Route Transfer] Physical task in progress, voice '{cmd}' routed to oracle probe...")
                    self.jarvis.interruption_queue.put(cmd)
                    continue

                self.state_changed.emit("THINKING")
                
                # 👇 核心新增：在开始连接大模型思考的前一瞬间，播放优雅的确认音
                self.play_acknowledgment_chime()
                
                # ==========================================
                # 📍 修改目标位置: jarvis_nerve.py (在 JarvisWorkerThread.run 中)
                # ==========================================
                
                # ==========================================
# 📍 修改目标位置: jarvis_nerve.py (在 JarvisWorkerThread.run 中)
# ==========================================
                stm_context = "\n".join([f"{m['user']} -> {m['jarvis']}" for m in self.jarvis.short_term_memory[-6:]])
                if len(stm_context) > 2000:
                    stm_context = "..." + stm_context[-2000:]
                
                clean_cmd = cmd
                clean_intent = cmd # 👈 新增：专门用于 UI 打印的纯净意图
                system_alert_text = "" # 👈 新增：专门用于喂给大模型的隐形警告
                ltm_context = "暂时未回想起相关的历史记录。"
                # 👇 修复 1：提前声明默认值，防止报错后变量未定义
                gate_data_to_save = [{}]
                
                # 👇 双轨并行门神架构：快轨(LTM检索→LLM) + 慢轨(门神解析→记忆存储)
                _t_gate_start = time.time()
                gate_future = None
                gate_data_to_save = [{}]

                # [P0+18-b.6 / 2026-05-15] system event 短路：Reminder Mailbox 触发的伪
                # user_input 形如 `[SYSTEM BACKGROUND EVENT]: ...`，不应再走 Gatekeeper
                # 否则 LLM 会把"提醒我去拿快递"这种来自系统通告的句子再 schedule 成新的
                # is_future_task=true → 同一条 reminder 在数据库里被复制成 ID:705/707/710
                # 多次触发。短路掉这条路径既省 LLM 调用，也根治重复提醒。
                _is_system_event = (
                    cmd.startswith('[SYSTEM BACKGROUND EVENT]')
                    or cmd.startswith('[系统主动提醒]')
                    or cmd.startswith('[SYSTEM ALERT]')
                    or cmd.startswith('[后台系统异步唤醒]')
                )
                if _is_system_event:
                    try:
                        from jarvis_utils import bg_log
                        bg_log("⏭️ [Gatekeeper Skip] system event 路径，跳过 Gatekeeper LLM 解析（防止 reminder 重入）")
                    except Exception:
                        pass

                if not _is_system_event and (len(cmd.split()) > 2 or len(cmd) > 8):
                    def _do_gatekeeper():
                        _gate_key_name = None
                        result = {
                            'clean_intent': cmd,
                            'gate_data_to_save': [{}],
                            'system_alert_text': '',
                            'pending_commitment': None,
                            'conversation_event': None,
                        }
                        try:
                            current_time_str = time.strftime('%Y-%m-%d %H:%M:%S')
                            
                            gate_prompt = f"""Analyze the speech recognition (ASR) text and extract the Universal Memory Protocol.
Current System Time: {current_time_str}

Rules:
1. Correct phonetic misspellings. You MUST translate Chinglish or Pinyin (like 'zhuomian') back to standard Chinese in 'clean_intent' (e.g. '桌面').
2. 'memory_type': Categorize strictly as "CHAT", "TASK", or "REMINDER".
3. 'entities': Extract precise subjects, locations, and context. Use "none" if absent.
4. [CRITICAL] 'is_future_task': MUST be false by default! Only set to true if the user uses EXPLICIT imperative scheduling language such as: "remind me at...", "set an alarm for...", "schedule...", "at X o'clock remind me...", "wake me up at...". Statements about future plans (e.g. "I will go tomorrow", "I want to learn driving") are NOT future tasks. Questions about future events are NOT future tasks. When in doubt, set to false.
5. 'trigger_time_str': If is_future_task is true, calculate the EXACT target time in 'YYYY-MM-DD HH:MM:00' format based on Current System Time. Otherwise leave empty.
5a. [TIME-OF-DAY CONTEXT — CRITICAL] When the user says an ambiguous small number (e.g. "两点" / "two o'clock" / "三点" / "five"):
    [STEP 1 — Action verb takes precedence over hour-of-day default]:
    - "起床/醒/wake up/get up/醒来/起来" + small num → ALWAYS interpret as AM (e.g. "两点起床" = 02:00 if night, 14:00 ONLY if user explicitly said "下午两点"). Default: tomorrow morning small_num:00.
    - "睡觉/睡/sleep/bed/rest" + small num → ALWAYS interpret as the next sleep window. If now is daytime (6-21), "两点睡觉" usually means 02:00 of next morning (or 14:00 only if user explicitly said "下午"/"PM"). If now is late night (22-05), it means the imminent 02:00.
    - "吃饭/午餐/lunch" + small num → typically 12-13 (lunch) or 18-20 (dinner) — pick by current hour.
    - "下午/afternoon/PM" → FORCE PM range (12-23).
    - "凌晨/early morning/midnight/AM" → FORCE early-morning range (0-6).
    [STEP 2 — If no action verb, use current-hour fallback]:
    - If Current System Time hour < 6 (early morning), default to SAME early morning today.
    - If Current System Time hour 6-11 (morning), default to the afternoon of TODAY (small num + 12).
    - If Current System Time hour 12-23 (afternoon/evening), default to the evening of TODAY (small num + 12), unless explicitly stated as AM.
    [STEP 3]:
    - If the computed time is already in the past (< now - 1h), advance by 24h (next day).
    NEVER blindly map small numbers to 12-23 hour range — always cross-check with Current System Time AND action verb.
    EXAMPLE: at 12:43 PM, user says "我两点起床" → trigger_time_str = "<tomorrow_date> 02:00:00" (NOT today 14:00, NOT today 02:00 already-past). At 12:43 PM, user says "我两点睡觉" → trigger_time_str = "<tomorrow_date> 02:00:00" (NOT today 14:00, sleep verb forces next-night).
6. 'needs_ltm': True IF the user asks about past events, uses vague pronouns, or requests past info.
7. 'cancel_old_reminder': If the user explicitly asks to CANCEL a previous reminder, extract the OLD intent here. Otherwise leave empty.
8. [DATABASE ALIGNMENT (CRITICAL)]: The 'search_query' MUST ALWAYS be translated into highly descriptive CHINESE KEYWORDS.
9. [ANTI-HALLUCINATION]: NEVER invent tasks! When uncertain, default to is_future_task=false.
10. 'conversation_event': Analyze the STM context AND the current command. Detect if a significant conversational shift just occurred. Output null if none.

Event types and their triggers:
- "breakthrough": A recurring confusion, error, or frustration that appeared multiple times in STM has just been RESOLVED in the current command. Example: STM shows 5 rounds of "string vs stream" ASR confusion, current command finally gets it right.
- "callback": Sir is explicitly referencing or building on something from earlier in THIS conversation (visible in STM). This is NOT a new topic — it's continuity.
- "tension_release": STM shows mounting frustration or repeated failures, and the current command indicates the issue is resolved or Sir is letting it go with humor/resignation.
- "shared_discovery": Sir just discovered or realized something and is sharing it with you for the first time.

Output format: {{"type": "breakthrough", "description": "One sentence directive to Jarvis. Example: 'The long-running ASR confusion between string and stream has finally been resolved. Acknowledge this with dry satisfaction before addressing the command.'"}} or null.

11. 'commitment': Detect ONLY user-self-commitments (the user promising what THEY themselves will do). Set has_commitment=true ONLY when ALL three conditions hold:
    (a) The subject is "I/我" — the user is the one taking the action.
    (b) The user uses self-binding language. ACCEPT both DIRECT and HEDGED forms:
        - Direct:  "I will...", "I promise...", "I'm going to...", "remind me to...",
                   "我会...", "我要...", "我打算...", "我答应..."
        - Hedged but time-anchored (ALSO COUNT): "I'll probably...", "I might...", "I should...",
                   "I think I'll...", "大概会...", "可能会...", "估计会...", "也许...", "差不多...",
                   "我大概 X 点...", "我大概会 X". Hedging is OK as long as (c) holds.
    (c) There is a concrete future deadline or time anchor (a clock time, 'tonight', 'tomorrow X', etc.).
    HARD REJECT (has_commitment=false) for ALL of the following — even if a time appears:
      - Commands directed at Jarvis: "帮我...", "给我...", "把...调到...", "请你...", "Jarvis,...", "set...", "turn off...", "adjust...", "change...", "open...", "close...".
      - Imperatives without an explicit "I/我" subject ("调亮度到50%" / "turn down the volume").
      - Role-play / hypothetical prompts: "假装...", "扮演...", "pretend you...", "act as if...".
      - Questions, status checks, or descriptions of what Jarvis should do.
      - Aspirations without time anchor: "I want to be healthier" (no time) → false. "我想早点睡" (no specific time) → false.
    🩹 [β.2.7.3 / 2026-05-17]: hedged + time = STILL commitment（治 Sir "我大概1:05睡" 漏判 BUG）。
    False positives here corrupt Sir's commitment ledger — but missing real hedged commitments is just as bad.

12. [MEMORY CORRECTION] 'correction': Detect if the user is CORRECTING a previous statement or memory (changing wrong info to right info). Triggers: "that was wrong", "I meant X not Y", "I said it wrong", "actually it's X", "no, I meant X", "不是...是...", "说错了...应该是...", "纠正一下". CRITICAL: Do NOT trigger correction if the user is asking to DELETE/REMOVE a memory. If the user says "delete that memory" or "删掉那个记忆", use delete_memory_hint (rule 13) instead. When triggered:
   - 'has_correction': true
   - 'old_value': What the user previously said that was wrong (extract from STM context or the current command)
   - 'new_value': What the user is correcting it TO (the CORRECT information, NOT "delete" or "删掉")
   - 'search_hint': Keywords to find the matching memory in LTM (in Chinese)
   If no correction detected, set has_correction=false.

13. [MEMORY DELETION] 'delete_memory_hint': Detect if the user wants to DELETE/REMOVE a specific *memory or past record from STM/LTM*. Triggers: "delete that memory", "remove that record", "forget that", "删掉那个记忆", "把那个记录删了", "去掉那段", "清除那个". When triggered, extract keywords to find the target memory. Otherwise leave empty.

13a. [PHYSICAL FILE vs MEMORY ENTRY — CRITICAL / P0+18-a.6 / 2026-05-15] delete_memory_hint is ONLY for *erasing memory entries* (rows in STM list / hippocampus SQLite). It is NOT for deleting physical files, folders, file paths, or anything on disk.
    If the user wants to delete a physical FILE / FOLDER (anything with `.txt`/`.md`/`.py`/`.exe`/`.png`/`.pdf` suffix, or a drive letter `D:\\` / `D盘`, or words like `文件` / `桌面` / `desktop` / `documents` / `folder` / `directory`), leave delete_memory_hint EMPTY. The main brain will route it to file_operator_hands.delete via the PromiseLedger (dangerous skill, requires Sir's explicit 'go' confirm).
    Examples (FILE intent → leave empty):
      User: "删掉 D:\\Jarvis\\test_dummy.txt 这个文件"
        WRONG: delete_memory_hint = "D盘 test.txt 文件"        ← will be REFUSED by guard 5 (P0+18-a.5)
        RIGHT: delete_memory_hint = ""                          ← let main brain call file_operator_hands.delete
      User: "把桌面那个 readme 删了"
        WRONG: delete_memory_hint = "桌面 readme"               ← will be REFUSED (contains '桌面')
        RIGHT: delete_memory_hint = ""                          ← physical file
      User: "把 downloads 那个 zip 包清掉"
        WRONG: delete_memory_hint = "downloads zip"             ← contains 'downloads' + '.zip' implication
        RIGHT: delete_memory_hint = ""                          ← physical file/folder
    Examples (MEMORY intent → keep concrete hint):
      User: "删掉两点睡觉那条记忆"
        RIGHT: delete_memory_hint = "两点睡觉"                  ← genuine STM entry deletion
      User: "把那次音量调整的记录清掉"
        RIGHT: delete_memory_hint = "音量调整"                  ← genuine LTM entry deletion

14. [REFERENCE DISAMBIGUATION] CRITICAL for delete_memory_hint AND correction.search_hint:
    NEVER use bare pronouns/fillers as the hint value. The system will REFUSE to act on these:
      Forbidden hints: "那个东西" / "this thing" / "that" / "this" / "it" / "那个" / "这个" / "那段" / "这条" / "那记忆".
    When the user uses such pronouns, you MUST resolve them to the actual referent by reading STM Context.
    Algorithm:
      (a) Find the most recent CONCRETE topic in STM Context that matches what Sir is talking about.
      (b) Use that concrete topic (a noun phrase, a fact, a time + verb, a name) as the hint.
      (c) If you cannot find a clear referent in STM, leave the hint EMPTY rather than guessing.
    Examples:
      STM contains: "我会在大概两点的时候睡觉"
      User says:    "删掉那个东西不重要了"
      WRONG hint:   "那个东西"          ← will be refused
      RIGHT hint:   "两点睡觉"           ← concrete referent from STM
    Examples:
      STM contains: "把音量调到 30%"
      User says:    "去掉那条记录"
      WRONG hint:   "那条记录"          ← will be refused
      RIGHT hint:   "音量 30%"          ← concrete referent
    Examples:
      STM contains: (nothing relevant)
      User says:    "删掉那个东西"
      WRONG hint:   "那个东西"          ← will be refused
      RIGHT hint:   ""                   ← leave empty, let main brain ask Sir to clarify

15. [MULTI-OP / 2026-05-15 P0+18-d.4] If the user mentions MULTIPLE distinct memory/reminder
    operations in a single utterance (e.g. "cancel the package reminder AND add a Subject One reminder
    for tomorrow morning" / "取消快递提醒，再加一个明天早上学科目一的提醒"), output ONE record per
    distinct operation in the JSON array — do NOT cram multiple operations into one record's
    fields.
    Example user: "三点取快递的提醒已经过去了，记得明天早上要提醒我学科目一"
    CORRECT output (2 records):
      [
        {{"clean_intent": "确认明天早上学科目一", "memory_type": "REMINDER",
          "is_future_task": true, "trigger_time_str": "<tomorrow morning>",
          "correction": {{"has_correction": false}}, ...}},
        {{"clean_intent": "归档已过期的快递提醒", "memory_type": "CHAT",
          "is_future_task": false,
          "correction": {{"has_correction": true, "old_value": "明天下午三点取快递",
            "new_value": "已过期 — archive", "search_hint": "快递"}}, ...}}
      ]
    WRONG output (1 record, cramming both into one new_value):
      [{{..., "new_value": "今天下午取快递（已过期），明天早上学科目一", ...}}]   ← creates garbage memory
    If only one operation is present, output ONE record as usual.

Context: {stm_context}
Raw ASR: {cmd}

Output strict JSON ARRAY ONLY. NO EXPLANATIONS. NO THOUGHTS.[
  {{
    "clean_intent": "The actual meaning (MUST be in Chinese if user meant Chinese)",
    "memory_type": "CHAT",
    "entities": {{"time": "...", "location": "...", "subject": "..."}},
    "is_future_task": false,
    "trigger_time_str": "",
    "cancel_old_reminder": "",
    "needs_ltm": true,
    "search_query": "MUST BE IN CHINESE",
    "conversation_event": null,
    "commitment": {{"has_commitment": false, "description": "", "deadline": ""}},
    "correction": {{"has_correction": false, "old_value": "", "new_value": "", "search_hint": ""}},
    "delete_memory_hint": ""
  }}
]"""
                            
                            def _gate_call(client):
                                return client.models.generate_content(
                                    model='gemini-3.1-flash-lite',
                                    contents=gate_prompt
                                )
                            
                            gate_res, _gate_key_name, _gate_client = safe_gemini_call(
                                self.jarvis.key_router, KeyRouter.CALLER_GATEKEEPER, 'flash_lite',
                                _gate_call, max_retries=2, base_delay=1.0,
                                model_name='gemini-3.1-flash-lite', contents_text=gate_prompt
                            )
                            self.jarvis.key_router.release(_gate_key_name)
                                
                            match = re.search(r'\[.*\]', gate_res.text.strip(), re.DOTALL)
                            gate_data_list = []
                            if match:
                                gate_data_list = json.loads(match.group(0))
                                if isinstance(gate_data_list, dict):
                                    gate_data_list = [gate_data_list]
                                if not gate_data_list or len(gate_data_list) == 0:
                                    gate_data_list = [{}]
                                    
                                clean_intent = gate_data_list[0].get("clean_intent", cmd)
                                result['clean_intent'] = clean_intent
                                
                                for gate_data in gate_data_list:
                                    trigger_time_str = gate_data.get("trigger_time_str", "")
                                    trigger_timestamp = 0.0
                                    if gate_data.get("is_future_task") and trigger_time_str:
                                        try:
                                            corrected_str, was_corrected, correction_reason = sanitize_trigger_time(
                                                trigger_time_str,
                                                gate_data.get("clean_intent", ""),
                                                cmd,
                                            )
                                            if was_corrected:
                                                trigger_time_str = corrected_str
                                                gate_data["trigger_time_str"] = corrected_str
                                                try:
                                                    from jarvis_utils import bg_log as _stz_bg
                                                    _stz_bg(
                                                        f"🛠️ [TimeSanitize] '{gate_data.get('clean_intent','')[:40]}' "
                                                        f"trigger 修正 → {corrected_str} (reason={correction_reason})"
                                                    )
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                        try:
                                            time_struct = time.strptime(trigger_time_str, "%Y-%m-%d %H:%M:%S")
                                            trigger_timestamp = time.mktime(time_struct)
                                        except Exception:
                                            pass
                                    gate_data["trigger_timestamp"] = trigger_timestamp
                                    
                                    if gate_data.get("is_future_task"):
                                        # [P0+18-c.8 / 2026-05-15] 改 bg_log 不粘 🎙️[接收物理声波] 行尾
                                        try:
                                            from jarvis_utils import bg_log as _th_bg_log
                                            _th_bg_log(f"⏰ [Time Hook] Task scheduled: '{gate_data.get('clean_intent')}', trigger: {trigger_time_str}")
                                        except Exception:
                                            pass
                                        
                                    cancel_old = gate_data.get("cancel_old_reminder", "")
                                    if cancel_old:
                                        print(f"\n🎯 [System Override] Cancel intent captured, cleaning old task: '{cancel_old}'...")
                                        cancel_res = self.jarvis.hippocampus.cancel_future_reminder(self.jarvis.gemini_key, cancel_old)
                                        print(f" └─ 🗑️ {cancel_res}")
                                        
                                        removed_count = 0
                                        for mid, state in list(self.jarvis._pending_reminders.items()):
                                            if cancel_old.lower() in state.get('intent', '').lower():
                                                if hasattr(self.jarvis, 'chronos_tick') and self.jarvis.chronos_tick:
                                                    self.jarvis.chronos_tick.mailbox.cancel_by_reminder_id(mid)
                                                del self.jarvis._pending_reminders[mid]
                                                self.jarvis.hippocampus.consume_reminder(mid)
                                                removed_count += 1
                                                print(f" └─ 🚫 [Scheduler Sync] 已从升级队列移除 ID:{mid} '{state.get('intent', '')}'")
                                        if removed_count == 0:
                                            print(f" └─ ℹ️ [Scheduler Sync] 活跃升级队列中无匹配 (可能尚未触发)")
                                        
                                result['gate_data_to_save'] = gate_data_list
                                
                                # 🎯 conversation_event 抽取（突破/回调/释压/分享）
                                # 反幻觉三重闸：
                                #   1. 必须是 dict（LLM 输出 null 时跳过）
                                #   2. type 必须在白名单内
                                #   3. description 至少 20 字，防止"Sir said something."这类空话
                                ce = gate_data_list[0].get("conversation_event")
                                if isinstance(ce, dict):
                                    ce_type = (ce.get('type') or '').strip().lower()
                                    ce_desc = (ce.get('description') or '').strip()
                                    valid_types = {'breakthrough', 'callback', 'tension_release', 'shared_discovery'}
                                    if ce_type in valid_types and len(ce_desc) >= 20:
                                        result['conversation_event'] = {
                                            'type': ce_type,
                                            'description': ce_desc[:300],
                                        }
                                        _ce_preview = ce_desc if len(ce_desc) <= 80 else (ce_desc[:80] + "…")
                                        try:
                                            from jarvis_utils import bg_log
                                            bg_log(f"🎯 [Conversation Event] {ce_type}: {_ce_preview}")
                                        except Exception:
                                            print(f"║ 🎯 [Conversation Event] {ce_type}: {_ce_preview}")
                                        # [R6/B1] 直接 publish 到对话事件总线 —— 不再等下一轮 self.pending_event
                                        # gatekeeper 是后台线程，可能在 stream_chat 期间或之后才返回，
                                        # 不管哪种情况，prompt assembler 下次组装时都能直接读到。
                                        try:
                                            bus = getattr(self.jarvis, 'event_bus', None)
                                            if bus is not None:
                                                bus.publish(
                                                    etype='conversation_event',
                                                    description=f"[{ce_type}] {ce_desc}",
                                                    source='gatekeeper',
                                                    metadata={'subtype': ce_type},
                                                )
                                        except Exception:
                                            pass
                                
                                # [P0+18-d.4 / 2026-05-15] Multi-op 支持 —— commitment 循环处理 list
                                # 修 Sir 18:30 实测 BUG：一句话提"取消快递 + 加科目一"两件事，
                                # Gatekeeper 旧版只看 [0]，多余 record 丢失。
                                # 🩹 [β.2.7.3 / 2026-05-17] 加诊断 log：让 Sir 能 grep 'Gatekeeper Commitment' 排查漏判
                                for _commit_gd in gate_data_list:
                                    commitment = _commit_gd.get("commitment", {}) if isinstance(_commit_gd, dict) else {}
                                    _has_c = bool(isinstance(commitment, dict) and commitment.get("has_commitment"))
                                    _desc_dbg = (commitment.get("description", "") if isinstance(commitment, dict) else "")[:60]
                                    _ddl_dbg = (commitment.get("deadline", "") if isinstance(commitment, dict) else "")[:30]
                                    try:
                                        from jarvis_utils import bg_log as _gk_bg
                                        _gk_bg(
                                            f"📝 [Gatekeeper Commitment] has_commitment={_has_c} "
                                            f"desc='{_desc_dbg}' deadline='{_ddl_dbg}' cmd='{cmd[:60]}'"
                                        )
                                    except Exception:
                                        pass
                                    if isinstance(commitment, dict) and commitment.get("has_commitment"):
                                        desc = commitment.get("description", "")
                                        deadline = commitment.get("deadline", "")
                                        if desc and len(desc) >= 5:
                                            # [P0+18-c.8 / 2026-05-15] 改 bg_log,避免"║ 📝 [Commitment]" 在 box 外当孤儿 ║
                                            try:
                                                from jarvis_utils import bg_log as _cm_bg_log
                                                _cm_bg_log(f"📝 [Commitment] {desc} | 截止: {deadline}")
                                            except Exception:
                                                pass
                                            # 多 op 时 result['pending_commitment'] 只保留最后一个（UI 仅展示一条），
                                            # 但 commitment_watcher.add_commitment 每条都 add。
                                            result['pending_commitment'] = commitment
                                            # [P0+18-c.9/c.10 / 2026-05-15] 传 cmd（用户原话）+ Time Hook 已确认信号
                                            if hasattr(self.jarvis, 'commitment_watcher') and self.jarvis.commitment_watcher:
                                                _is_future_confirmed = bool(_commit_gd.get('is_future_task'))
                                                self.jarvis.commitment_watcher.add_commitment(
                                                    desc, deadline,
                                                    user_text=cmd,
                                                    is_future_task_confirmed=_is_future_confirmed,
                                                )
                                            # [R6/B1] 承诺也 publish 到事件总线
                                            try:
                                                bus = getattr(self.jarvis, 'event_bus', None)
                                                if bus is not None:
                                                    _deadline_str = f" (by {deadline})" if deadline else ""
                                                    bus.publish(
                                                        etype='commitment_detected',
                                                        description=f"Sir committed: \"{desc}\"{_deadline_str}",
                                                        source='gatekeeper',
                                                        metadata={'deadline': deadline},
                                                    )
                                            except Exception:
                                                pass

                                # [P0+18-d.4 / 2026-05-15] Multi-op 支持 —— correction / delete_hint 扫描
                                # 修 Sir 18:30 实测 BUG：LLM 输出 [0] 是"明天科目一 future_task=true"
                                # + [1] 是"快递 archive correction"，旧代码只看 [0].correction，[1] 的纠正丢失。
                                # 修法：扫描整个 list 找第一条有 has_correction 或 delete_memory_hint 的 record。
                                # 4 层防御逻辑沿用，不需要复制；多 op 时仅处理"主纠正"一条（次纠正
                                # 通过 commitment / is_future_task 字段已被 for 循环覆盖）。
                                correction = {}
                                delete_hint = ""
                                for _scan_gd in gate_data_list:
                                    if not isinstance(_scan_gd, dict):
                                        continue
                                    _c = _scan_gd.get("correction", {})
                                    if isinstance(_c, dict) and _c.get("has_correction") and not correction:
                                        correction = _c
                                    _d = _scan_gd.get("delete_memory_hint", "")
                                    if isinstance(_d, str) and _d.strip() and not delete_hint:
                                        delete_hint = _d
                                    if correction and delete_hint:
                                        break
                                # 没扫到 → 保留 fallback 走 [0]
                                if not correction:
                                    correction = gate_data_list[0].get("correction", {}) if isinstance(gate_data_list[0], dict) else {}
                                if not delete_hint:
                                    delete_hint = gate_data_list[0].get("delete_memory_hint", "") if isinstance(gate_data_list[0], dict) else ""

                                if delete_hint and len(delete_hint) >= 2:
                                    # [P0+16 / 2026-05-15] Memory Deletion 4 层防御（09:22 误删 5 条事件根因修）：
                                    # 防御 1: 纯指代词拦截 — 'delete that thing' / '删掉那个东西' 必须先让 Sir 澄清
                                    # 防御 2: search_memory min_similarity=0.45 — 不再返回 0.1 相似度噪声
                                    # 防御 3: 删除前 candidates preview + event_bus publish — 让 Sir + 主脑下一轮看见删了什么（PromiseLedger hook 接口）
                                    # 防御 4: Gatekeeper prompt 规则 14 [REFERENCE DISAMBIGUATION] — 上游 LLM 先把指代词消歧
                                    # [P0+18-a.5 / 2026-05-15] 防御 5: 物理文件删除意图直接拒触发 delete_memory，
                                    #                                  让主脑走 file_operator_hands.delete 正轨
                                    try:
                                        from jarvis_utils import bg_log
                                    except Exception:
                                        bg_log = lambda m: print(f"║ {m}")

                                    # 防御 5（最先拦，避免 hint 含 .txt/.md/D盘/桌面/文件 等触发 LTM 搜索）
                                    if _is_physical_file_delete_intent(delete_hint):
                                        bg_log(f"🛡️ [Memory Deletion Guard / Physical-File] hint='{delete_hint}' 含物理文件标识 (后缀/盘符/桌面/文件夹)，拒绝触发 delete_memory — 让主脑走 file_operator_hands.delete")
                                        try:
                                            bus = getattr(self.jarvis, 'event_bus', None)
                                            if bus is not None:
                                                bus.publish(
                                                    etype='memory_deletion_refused',
                                                    description=f"Refused: hint '{delete_hint}' targets physical file, not STM memory entry.",
                                                    source='memory_deletion_guard',
                                                    metadata={'delete_hint': delete_hint, 'reason': 'physical_file_intent'},
                                                )
                                        except Exception:
                                            pass
                                        result['gate_result_text'] = (
                                            f"Memory deletion REFUSED: '{delete_hint}' targets a physical file/folder, "
                                            f"not an STM memory entry. To delete files, use file_operator_hands.delete via the PromiseLedger "
                                            f"(dangerous skill, requires Sir's explicit 'go' confirm)."
                                        )
                                    # 防御 1
                                    elif _is_reference_only_hint(delete_hint):
                                        bg_log(f"🛡️ [Memory Deletion Guard] hint='{delete_hint}' 是纯指代词，拒绝删除 — 等 Sir 澄清具体所指")
                                        try:
                                            bus = getattr(self.jarvis, 'event_bus', None)
                                            if bus is not None:
                                                bus.publish(
                                                    etype='memory_deletion_refused',
                                                    description=f"Refused: hint '{delete_hint}' is reference-only pronoun.",
                                                    source='memory_deletion_guard',
                                                    metadata={'delete_hint': delete_hint, 'reason': 'reference_only'},
                                                )
                                        except Exception:
                                            pass
                                        result['gate_result_text'] = (
                                            f"Memory deletion REFUSED: '{delete_hint}' is a pronoun without clear referent. "
                                            f"Ask Sir to specify which memory (e.g., '删掉两点睡觉那条' / 'delete the 2am sleep entry')."
                                        )
                                    else:
                                        bg_log(f"🗑️ [Memory Deletion] 搜索: hint='{delete_hint}' (min_sim=0.45)")
                                        try:
                                            # 防御 2: 高阈值 search
                                            ltm_results = self.jarvis.hippocampus.search_memory(
                                                self.jarvis.gemini_key, delete_hint, top_k=5,
                                                min_similarity=0.45,
                                            )
                                            if not ltm_results:
                                                ltm_results = self.jarvis.hippocampus.search_memory(
                                                    self.jarvis.gemini_key, cmd, top_k=5,
                                                    min_similarity=0.45,
                                                )
                                            if not ltm_results:
                                                bg_log(f"⚠️ [Memory Deletion] 无候选 (相似度都 < 0.45 / hint='{delete_hint}')")
                                                result['gate_result_text'] = (
                                                    f"Memory deletion: No matching records found for '{delete_hint}' "
                                                    f"(similarity threshold 0.45). Nothing was deleted."
                                                )
                                            else:
                                                # 防御 3: candidates preview + event_bus
                                                preview_lines = [f"📋 [Memory Deletion Preview] 即将删除 {len(ltm_results)} 条候选 (hint='{delete_hint}'):"]
                                                preview_payload = []
                                                for mem in ltm_results:
                                                    sim = mem.get('similarity', 0.0)
                                                    intent = mem.get('intent', '')[:60]
                                                    preview_lines.append(f"  ID={mem.get('id')} sim={sim:.2f} intent={intent!r}")
                                                    preview_payload.append({'id': mem.get('id'), 'sim': sim, 'intent': intent})
                                                bg_log('\n'.join(preview_lines))
                                                try:
                                                    bus = getattr(self.jarvis, 'event_bus', None)
                                                    if bus is not None:
                                                        bus.publish(
                                                            etype='memory_deletion_preview',
                                                            description=f"About to delete {len(ltm_results)} memories matching '{delete_hint}'",
                                                            source='memory_deletion',
                                                            metadata={'delete_hint': delete_hint, 'candidates': preview_payload},
                                                        )
                                                except Exception:
                                                    pass

                                                deleted_count = 0
                                                for mem in ltm_results:
                                                    mem_id = mem.get('id', 0)
                                                    mem_intent = mem.get('intent', '')
                                                    if mem_id > 0:
                                                        self.jarvis.hippocampus.delete_memory(mem_id)
                                                        print(f" └─ 🗑️ 已删除记忆 ID:{mem_id} '{mem_intent[:60]}'")
                                                        deleted_count += 1
                                                if deleted_count > 0:
                                                    result['gate_result_text'] = f"Memory deletion SUCCESS: {deleted_count} record(s) removed matching '{delete_hint}'."
                                                else:
                                                    result['gate_result_text'] = f"Memory deletion: No matching records found for '{delete_hint}'. Nothing was deleted."
                                        except Exception as e:
                                            try:
                                                from jarvis_utils import bg_log as _bg
                                                _bg(f"└─ ❌ [Memory Deletion Failed]: {e}")
                                            except Exception:
                                                pass
                                            result['gate_result_text'] = f"Memory deletion FAILED: {str(e)[:80]}. The memory may still exist."

                                elif isinstance(correction, dict) and correction.get("has_correction"):
                                    old_val = correction.get("old_value", "")
                                    new_val = correction.get("new_value", "")
                                    search_hint = correction.get("search_hint", old_val)
                                    if new_val and len(new_val) >= 2:
                                        if any(kw in new_val for kw in ['删除', '删掉', '去掉', '清除', 'delete', 'remove']):
                                            print(f"║ ⚠️ [Correction Guard] new_value='{new_val}' 看起来是删除指令，跳过correction，转为delete_memory")
                                            # [P0+16 / 2026-05-15] correction→delete 同样套 4 层防御（防止"那个东西是错的，删了"误删）
                                            try:
                                                from jarvis_utils import bg_log as _del_bg
                                            except Exception:
                                                _del_bg = lambda m: print(f"║ {m}")
                                            _hint_for_guard = search_hint or old_val
                                            # [P0+18-a.5 / 2026-05-15] 防御 5: 物理文件意图先拦
                                            if _is_physical_file_delete_intent(_hint_for_guard):
                                                _del_bg(f"🛡️ [Memory Deletion Guard / via correction / Physical-File] hint='{_hint_for_guard}' 含物理文件标识，拒绝触发 delete_memory")
                                                try:
                                                    bus = getattr(self.jarvis, 'event_bus', None)
                                                    if bus is not None:
                                                        bus.publish(
                                                            etype='memory_deletion_refused',
                                                            description=f"Refused (via correction): hint '{_hint_for_guard}' targets physical file.",
                                                            source='memory_deletion_guard',
                                                            metadata={'delete_hint': _hint_for_guard, 'reason': 'physical_file_intent'},
                                                        )
                                                except Exception:
                                                    pass
                                                result['gate_result_text'] = (
                                                    f"Memory deletion REFUSED: '{_hint_for_guard}' targets a physical file/folder, "
                                                    f"not an STM memory entry. Use file_operator_hands.delete via PromiseLedger instead."
                                                )
                                            elif _is_reference_only_hint(_hint_for_guard):
                                                _del_bg(f"🛡️ [Memory Deletion Guard / via correction] hint='{_hint_for_guard}' 是纯指代词，拒绝删除")
                                                result['gate_result_text'] = (
                                                    f"Memory deletion REFUSED: '{_hint_for_guard}' is a pronoun without clear referent. "
                                                    f"Ask Sir to specify which memory."
                                                )
                                            else:
                                                try:
                                                    ltm_results = self.jarvis.hippocampus.search_memory(
                                                        self.jarvis.gemini_key, _hint_for_guard or cmd, top_k=5,
                                                        min_similarity=0.45,
                                                    )
                                                    if not ltm_results:
                                                        _del_bg(f"⚠️ [Memory Deletion / via correction] 无候选 (sim < 0.45 / hint='{_hint_for_guard}')")
                                                        result['gate_result_text'] = "Memory deletion: No matching records found. Nothing was deleted."
                                                    else:
                                                        # candidates preview + event_bus
                                                        preview_lines = [f"📋 [Memory Deletion Preview / via correction] 即将删除 {len(ltm_results)} 条 (hint='{_hint_for_guard}'):"]
                                                        preview_payload = []
                                                        for mem in ltm_results:
                                                            sim = mem.get('similarity', 0.0)
                                                            intent = mem.get('intent', '')[:60]
                                                            preview_lines.append(f"  ID={mem.get('id')} sim={sim:.2f} intent={intent!r}")
                                                            preview_payload.append({'id': mem.get('id'), 'sim': sim, 'intent': intent})
                                                        _del_bg('\n'.join(preview_lines))
                                                        try:
                                                            bus = getattr(self.jarvis, 'event_bus', None)
                                                            if bus is not None:
                                                                bus.publish(
                                                                    etype='memory_deletion_preview',
                                                                    description=f"About to delete {len(ltm_results)} memories (via correction) matching '{_hint_for_guard}'",
                                                                    source='memory_deletion_via_correction',
                                                                    metadata={'delete_hint': _hint_for_guard, 'candidates': preview_payload},
                                                                )
                                                        except Exception:
                                                            pass
                                                        deleted_count = 0
                                                        for mem in ltm_results:
                                                            mem_id = mem.get('id', 0)
                                                            if mem_id > 0:
                                                                self.jarvis.hippocampus.delete_memory(mem_id)
                                                                print(f" └─ 🗑️ 已删除记忆 ID:{mem_id}")
                                                                deleted_count += 1
                                                        if deleted_count > 0:
                                                            result['gate_result_text'] = f"Memory deletion SUCCESS: {deleted_count} record(s) removed."
                                                        else:
                                                            result['gate_result_text'] = "Memory deletion: No matching records found. Nothing was deleted."
                                                except Exception as e:
                                                    result['gate_result_text'] = f"Memory deletion FAILED: {str(e)[:80]}."
                                        else:
                                            # 🩹 [P0+20-β.1.3 / 2026-05-16] 性质替换守卫（治 B2）：
                                            # Sir 12:43 实测：原存"两点起床"，Sir 又说"我要睡觉"，LLM 把它
                                            # 当作"correction" old=两点起床 / new=两点睡觉 → 把起床闹钟覆盖
                                            # 成了睡觉计划。
                                            #
                                            # 🩹 [P0+20-β.1.23 / 2026-05-16] 守卫扩展（治 Sir 20:50 反驳→替换 BUG）：
                                            # Sir 反问"你真的认为我需要9点睡吗" → Gatekeeper 把它当 correction
                                            # old="21:00" new="不认同 9点睡觉" → 时间标签被换成否定语句。
                                            # 新规则：
                                            #   ① 任一类别非 misc 且 old_cat != new_cat → 拒绝替换（原 β.1.3）
                                            #   ② new_val 含明显"反驳/否定/反问"词 → 拒绝替换（这是 refusal 不是 correction）
                                            #   ③ old_val 是纯时间标签 (\d+[:.]?\d* / X 点) + new_val 含语义动词 → 拒绝
                                            old_cat = detect_semantic_category(old_val)
                                            new_cat = detect_semantic_category(new_val)
                                            import re as _re_guard

                                            _refusal_in_new = bool(_re_guard.search(
                                                r'(不认同|不同意|不要|不需要|不用|不想|不会|不可能|不行|'
                                                r'我不|真的吗|你确定|确定吗|凭什么|why\s+would|are\s+you\s+sure|'
                                                r'no\s+(way|need|i\s+won|i\s+don)|i\s+(don\'?t|won\'?t|cannot))',
                                                new_val, _re_guard.IGNORECASE
                                            ))
                                            _is_time_only = bool(_re_guard.match(
                                                r'^\s*\d{1,2}[:\.]\d{0,2}\s*$|^\s*\d{1,2}\s*(点|时|am|pm)\s*$',
                                                old_val, _re_guard.IGNORECASE
                                            ))
                                            category_conflict = (
                                                (old_cat != 'misc' and new_cat != 'misc' and old_cat != new_cat)
                                                or _refusal_in_new
                                                or (_is_time_only and new_cat != 'misc' and new_cat != 'wake' and new_cat != 'sleep')
                                            )
                                            if category_conflict:
                                                try:
                                                    from jarvis_utils import bg_log as _cat_bg
                                                    _cat_bg(
                                                        f"🛡️ [Memory Correction Guard] 性质冲突拒绝替换："
                                                        f"old='{old_val}' ({old_cat}) → new='{new_val}' ({new_cat})。"
                                                        f"转为新记忆独立保存。"
                                                    )
                                                except Exception:
                                                    pass
                                                result['gate_result_text'] = (
                                                    f"Memory correction REFUSED: '{old_val}' is a {old_cat} entry, "
                                                    f"but '{new_val}' is a {new_cat} entry — different category. "
                                                    f"Saved '{new_val}' as a NEW memory instead of overwriting."
                                                )
                                                # 直接进入"未匹配走新记忆"路径（updated=False）
                                                updated = False
                                                ltm_results = []
                                                # 跳到下方 if not updated 的兜底分支
                                                pass
                                            else:
                                                try:
                                                    from jarvis_utils import bg_log
                                                    bg_log(f"🔧 [Memory Correction] '{old_val}' → '{new_val}'")
                                                except Exception:
                                                    print(f"║ 🔧 [Memory Correction] '{old_val}' → '{new_val}'")
                                            try:
                                                if category_conflict:
                                                    queries = []
                                                    ltm_results = []
                                                else:
                                                    queries = [q for q in [search_hint, old_val, cmd] if q and len(q) >= 2]
                                                    ltm_results = []
                                                    for q in queries:
                                                        ltm_results = self.jarvis.hippocampus.search_memory(
                                                            self.jarvis.gemini_key, q, top_k=5
                                                        )
                                                        if ltm_results:
                                                            break
                                                updated = False
                                                for mem in (ltm_results or []):
                                                    mem_intent = mem.get('intent', '').lower()
                                                    mem_summary = mem.get('summary', '').lower()
                                                    if old_val.lower() in mem_intent or old_val.lower() in mem_summary or \
                                                       search_hint.lower() in mem_intent or search_hint.lower() in mem_summary:
                                                        mem_id = mem.get('id', 0)
                                                        if mem_id > 0:
                                                            self.jarvis.hippocampus.update_memory(
                                                                api_key=self.jarvis.gemini_key,
                                                                memory_id=mem_id,
                                                                env=mem.get('environment', 'CHAT'),
                                                                intent=new_val,
                                                                goal="",
                                                                new_summary=f"[用户纠正] 原: {old_val} → 新: {new_val}"
                                                            )
                                                            try:
                                                                from jarvis_utils import bg_log
                                                                bg_log(f" └─ ✅ 已修正记忆 ID:{mem_id}")
                                                            except Exception:
                                                                print(f" └─ ✅ 已修正记忆 ID:{mem_id}")
                                                            updated = True
                                                            break
                                                if not updated:
                                                    try:
                                                        from jarvis_utils import bg_log
                                                        bg_log(f" └─ ⚠️ 未找到匹配记忆，将作为新记忆存储")
                                                    except Exception:
                                                        print(f" └─ ⚠️ 未找到匹配记忆，将作为新记忆存储")
                                                    # [P0+18-e.1 / 2026-05-15] 关键修：兜底不再无脑降级为 CHAT。
                                                    # 修 Sir 20:28-20:32 实测 BUG（jarvis_20260515_202835.log:225-228）：
                                                    #   Sir: "改到9点" → Cancel 先抹掉 8 点 reminder
                                                    #                 → Memory Correction 找不到旧记录
                                                    #                 → 旧代码把 gate_data_to_save 强行改成单条 CHAT
                                                    #                 → DB id=747 is_future_task=0 + trigger_time=0
                                                    #                 → 1 分钟后 Sir 问 "代办事项" → "queue is clear"（错！）
                                                    #
                                                    # 因果链：Cancel + Correction 同帧触发时，Gatekeeper 原 gate_data_list
                                                    # 通常已含一条 is_future_task=True + trigger_timestamp>0 的"新 reminder"
                                                    # 记录（从 log line 186 的 [Time Hook] 可证），但兜底分支无脑覆盖丢失。
                                                    #
                                                    # 修法：检查原 gate_data_list 是否已有"含 trigger 的未来任务"记录：
                                                    #   - 有 → 保留原 list 不动（reminder 走正常落库通道）
                                                    #   - 无 → 检测 new_val 是否含时间锚词（点/时/早上/明天/AM/PM…）
                                                    #          含时间锚 → 拼 REMINDER 兜底（trigger 字段标 [需重新确认]，让主脑下轮看到）
                                                    #          不含 → 保留原 CHAT 兜底（无时间纠正属于"语义纠正"，正确）
                                                    _existing_list = result.get('gate_data_to_save') or []
                                                    _has_future_with_trigger = any(
                                                        isinstance(g, dict)
                                                        and g.get('is_future_task')
                                                        and float(g.get('trigger_timestamp') or 0.0) > 0
                                                        for g in _existing_list
                                                    )
                                                    if _has_future_with_trigger:
                                                        try:
                                                            from jarvis_utils import bg_log as _e1_bg
                                                            _e1_bg(
                                                                " └─ ✅ [P0+18-e.1] 上游已含未来任务+trigger，"
                                                                "保留原 gate_data_list（不降级为 CHAT），reminder 正常落库"
                                                            )
                                                        except Exception:
                                                            pass
                                                        # 不动 result['gate_data_to_save']
                                                        # [P0+18-e.1] 改善 gate_result_text 显示，告诉 Sir 新 reminder 已落
                                                        try:
                                                            _e1_trigger_str = ''
                                                            for _g in _existing_list:
                                                                if isinstance(_g, dict) and _g.get('is_future_task'):
                                                                    _e1_trigger_str = _g.get('trigger_time_str', '') or ''
                                                                    break
                                                            if _e1_trigger_str:
                                                                result['gate_result_text'] = (
                                                                    f"Memory correction: '{old_val}' was already gone, "
                                                                    f"but new reminder for '{new_val}' is scheduled at {_e1_trigger_str}."
                                                                )
                                                            else:
                                                                result['gate_result_text'] = (
                                                                    f"Memory correction: '{old_val}' was already gone, "
                                                                    f"new reminder for '{new_val}' has been saved."
                                                                )
                                                            # 此处直接 continue 下面的 _e1_check_done 流程,
                                                            # 不需要走最末尾的 "Saved as new memory" 通用 result。
                                                        except Exception:
                                                            pass
                                                    else:
                                                        _time_anchors = (
                                                            '点', '时', ':', 'am', 'pm', 'a.m', 'p.m',
                                                            '明天', '今天', '后天', '早上', '中午', '下午',
                                                            '晚上', '凌晨', '清晨',
                                                            'morning', 'afternoon', 'evening', 'night',
                                                            'tomorrow', 'today', 'tonight',
                                                        )
                                                        _new_val_lower = (new_val or '').lower()
                                                        _new_has_time = any(t in _new_val_lower for t in _time_anchors)
                                                        if _new_has_time:
                                                            try:
                                                                from jarvis_utils import bg_log as _e1_bg
                                                                _e1_bg(
                                                                    f" └─ ⚠️ [P0+18-e.1] new_val='{new_val}' 含时间锚词但上游未给 trigger，"
                                                                    "兜底为 REMINDER 占位（trigger=0 → render 显示 [time unknown]）"
                                                                )
                                                            except Exception:
                                                                pass
                                                            result['gate_data_to_save'] = [{
                                                                "clean_intent": f"[需重新确认时间] {new_val}（原 '{old_val}' 已取消）",
                                                                "memory_type": "REMINDER",
                                                                "entities": {},
                                                                "is_future_task": True,
                                                                "trigger_time_str": "",
                                                                "trigger_timestamp": 0.0,
                                                                "needs_ltm": False,
                                                                "search_query": new_val,
                                                            }]
                                                        else:
                                                            result['gate_data_to_save'] = [{
                                                                "clean_intent": f"[纠正] {new_val}",
                                                                "memory_type": "CHAT",
                                                                "entities": {},
                                                                "is_future_task": False,
                                                                "trigger_time_str": "",
                                                                "needs_ltm": False,
                                                                "search_query": new_val,
                                                            }]
                                                    # [P0+18-e.1] 仅在未进 _has_future_with_trigger 分支时,
                                                    # 才用通用 "Saved as a new memory" 文案。
                                                    if not _has_future_with_trigger:
                                                        result['gate_result_text'] = f"Memory correction: Original record not found. Saved '{new_val}' as a new memory."
                                                else:
                                                    result['gate_result_text'] = f"Memory correction SUCCESS: Updated '{old_val}' to '{new_val}'."

                                                # [P0-3 / 2026-05-15] Memory Correction → CommitmentWatcher 联动：
                                                # 若纠正涉及时间（含"点/时/AM/PM/:"），同步 update_by_keyword 让
                                                # in-memory commitment 也按新值修。这就是 Sir 提的"commit 没联动"根因修复。
                                                try:
                                                    cw = getattr(self.jarvis, 'commitment_watcher', None)
                                                    if cw is not None:
                                                        time_signal_chars = ('点', '时', ':', 'am', 'pm', 'a.m', 'p.m')
                                                        if any(ch in old_val.lower() for ch in time_signal_chars) or \
                                                           any(ch in new_val.lower() for ch in time_signal_chars):
                                                            # 用 search_hint 或 old_val 作关键词找老 commitment 并更新 deadline
                                                            kw = search_hint or old_val
                                                            n_upd = cw.update_by_keyword(
                                                                keyword=kw,
                                                                new_description=None,
                                                                new_deadline_str=new_val,
                                                                max_age_seconds=3600,
                                                            )
                                                            if n_upd == 0:
                                                                # 没找到匹配 → 试着按时间锚词取消旧的（避免遗留错误时间的 commitment）
                                                                # 例如 old_val="14:00" / "下午2点" → 取消所有近期含"睡"的 commitment
                                                                rest_words = ['睡', '休息', 'sleep', 'bed', 'rest']
                                                                # 仅在 new_val 也含睡眠语义时才取消（避免误伤其他类 commitment）
                                                                if any(rw in (cmd.lower()) for rw in rest_words):
                                                                    n_cancel = cw.cancel_by_keyword(
                                                                        keyword='睡' if '睡' in cmd else 'sleep',
                                                                        max_age_seconds=3600,
                                                                    )
                                                                    if n_cancel > 0:
                                                                        try:
                                                                            from jarvis_utils import bg_log
                                                                            bg_log(f"🔄 [Commitment Sync] correction 触发，撤销 {n_cancel} 条旧 sleep commitment")
                                                                        except Exception:
                                                                            pass
                                                except Exception as _e_cw:
                                                    print(f" └─ ⚠️ [Commitment Sync Failed]: {_e_cw}")
                                            except Exception as e:
                                                try:
                                                    from jarvis_utils import bg_log as _bg
                                                    _bg(f"└─ ❌ [Memory Correction Failed]: {e}")
                                                except Exception:
                                                    pass
                                                result['gate_result_text'] = f"Memory correction FAILED: {str(e)[:80]}. Please ask Sir to repeat."
                                
                                import re as re_gate
                                # [P0-6 / 2026-05-15] 中文小时锚词补全（基线版）：
                                # 实测 "我会在大概两点的时候睡觉" 没匹配 \d+点（"两"是中文数字），
                                # → AFP 把 is_future_task 清掉，但 Time Hook + CommitmentWatcher 都已注册。
                                # 三系统信号不一致。补全中文数字小时词 + 自然语义时间词。
                                #
                                # [P0+18-d.3 / 2026-05-15] 在 P0-6 基础上彻底修透 —— 信任上游 + 扩词典：
                                # 修 Sir 17:25 实测 BUG（172146.log:489-492）：
                                #   "不如明天早上起来刷怎么样" → Time Hook ✅ schedule 2026-05-16 08:00
                                #   → CommitmentWatcher ✅ 也 accept（P0+18-c.10 已修）
                                #   → 但 AFP 旧硬规则把 is_future_task 清掉 → 入库 ID 729 trigger=null
                                #   → 真机重启后 "明天早上 8 点提醒"完全没注册
                                #
                                # 根因：AFP 词典还缺一些"自然口语承诺"，比如：
                                #   - "明天早上起来 X"（"明早"匹配但"明天早上"两个词不匹配）
                                #   - "我打算/我准备/我计划 + 时间"
                                #   - "不如/要不要 + 明天 X"
                                #
                                # 修法（双管齐下）：
                                # 1. 扩词典 — 覆盖中文自然口语承诺（在 P0-6 基础上加 [P0+18-d.3 新增] 段）
                                # 2. 信任 Gatekeeper LLM — 上游 LLM 已经判定 is_future_task=True
                                #    且给了 trigger_time_str (>=10 字符) → AFP 不再硬清，改为
                                #    bg_log warn 提醒 Sir 这种结构，但**保留 is_future_task** 让数据落库。
                                #
                                # 设计取舍：宁可"未来误注册一条 reminder"（Sir 可 list_reminders 看到并删），
                                # 也不能"用户明明承诺了却没注册"（Sir 看不见、无从纠正、信任崩塌）。
                                schedule_keywords = [
                                    # 英文显式承诺
                                    r'remind\s+me', r'set\s+(an\s+)?alarm', r'schedule', r'wake\s+me\s+up',
                                    r'at\s+\d', r'\d+\s*o\'?clock', r'\d+:\d+',
                                    # 中文显式承诺 / 闹钟动词
                                    r'提醒我', r'闹钟', r'叫醒我', r'定个', r'设个', r'排期',
                                    # 阿拉伯/中文数字小时锚词
                                    r'\d+点', r'[零一二两三四五六七八九十]+\s*点(?:钟|半|多)?',
                                    r'(?:凌晨|早上|早晨|上午|中午|下午|晚上|傍晚|今晚|半夜|深夜)\s*[\d零一二两三四五六七八九十]+\s*点',
                                    # 中文时间段锚词（无小时数字）
                                    r'(?:今晚|今夜|明早|明晚|后天|大后天)\s*(?:再|就|要|的)?',
                                    # [P0+18-d.3 新增] "明天/后天/下周 + 早上/中午/下午/晚上"自然口语
                                    # 实测 "不如明天早上起来刷题" 旧规则匹配不到，必须加这条
                                    r'(?:明天|后天|大后天|下周|周末|周一|周二|周三|周四|周五|周六|周日)\s*(?:再)?\s*(?:凌晨|早上|早晨|上午|中午|下午|晚上|傍晚|半夜|深夜)',
                                    r'(?:凌晨|早上|早晨|上午|中午|下午|晚上|傍晚|半夜|深夜)\s*(?:再|就|要|的)?\s*(?:起来|开始|去|做|刷|学|练|跑|睡|起床|起身)',
                                    # [P0+18-d.3 新增] 含蓄承诺动词（"我打算/计划/准备"以及"不如/要不"）
                                    r'(?:我|咱们|咱)\s*(?:要|会|想|打算|准备|计划|得|需要|该)\s*(?:在|于)?\s*(?:明天|后天|今天|今晚|早上|下午|晚上|凌晨)',
                                    r'(?:不如|要不|要不要|不然)\s*(?:明天|后天|今天|今晚)',
                                    # 时长锚词
                                    r'半\s*(?:个)?\s*小时(?:后|内|之后)?',
                                    r'\d+\s*(?:分钟|小时|秒)\s*(?:后|内|之后)',
                                    # 英文自然语义时间词
                                    r'(?:by|before|after|until|till)\s+(?:tonight|tomorrow|midnight|noon|\d{1,2})',
                                    r'in\s+(?:half\s+an?\s+|a\s+|an?\s+)?(?:hour|minute|min|sec)s?',
                                    r'tomorrow\s+(?:morning|afternoon|evening|night)',
                                    r'(?:next|this)\s+(?:morning|afternoon|evening|night|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
                                ]
                                has_schedule_keyword = any(re_gate.search(kw, cmd_lower) for kw in schedule_keywords)

                                for gate_data in result['gate_data_to_save']:
                                    if not gate_data.get("is_future_task"):
                                        continue
                                    if has_schedule_keyword:
                                        # 词典命中 → AFP 完全放行
                                        continue
                                    # [P0+18-d.3] 词典没命中但 LLM 已经给了 trigger_time_str → 信任 LLM
                                    upstream_trigger = (gate_data.get("trigger_time_str") or "").strip()
                                    upstream_ts = float(gate_data.get("trigger_timestamp") or 0.0)
                                    if upstream_trigger and len(upstream_trigger) >= 10 and upstream_ts > 0:
                                        try:
                                            from jarvis_utils import bg_log as _afp_bg_log
                                            _afp_bg_log(
                                                f"⚠️ [Anti-False-Positive/TrustUpstream] 词典未命中但 Gatekeeper "
                                                f"已给 trigger='{upstream_trigger}' → 信任 LLM，保留 is_future_task=True"
                                            )
                                        except Exception:
                                            pass
                                        continue
                                    # 真假阳性：词典 + 上游都没给 → 才清除
                                    gate_data["is_future_task"] = False
                                    gate_data["trigger_time_str"] = ""
                                    gate_data["trigger_timestamp"] = 0.0
                                    try:
                                        from jarvis_utils import bg_log as _afp_bg_log
                                        _afp_bg_log(
                                            "🛡️ [Anti-False-Positive] 未检测到日程关键词且 Gatekeeper 未给出 trigger，"
                                            "未来任务标记已清除。"
                                        )
                                    except Exception:
                                        pass
                            else:
                                result['gate_data_to_save'] = [{}]
                                    
                        except concurrent.futures.TimeoutError:
                            print(f"⚠️ [Gatekeeper Timeout] 跳过记忆精炼，快速响应模式...")
                            if _gate_key_name is not None:
                                self.jarvis.key_router.report_error(_gate_key_name, 'timeout')
                                self.jarvis.key_router.release(_gate_key_name)
                            result['system_alert_text'] = "\n[SYSTEM ALERT]: The memory and scheduling module just timed out due to network turbulence. YOU DID NOT RECORD THE REMINDER OR MEMORY. IF Sir requested a reminder or task, you MUST elegantly apologize, mention a slight network fluctuation, and ask Sir to repeat. IF it's just casual chat, reply normally."
                        except Exception as e:
                            error_type = type(e).__name__
                            try:
                                from jarvis_utils import bg_log as _bg
                                _bg(f"⚠️ [Gatekeeper Error]: {error_type} {e}")
                            except Exception:
                                pass
                            if _gate_key_name is not None:
                                self.jarvis.key_router.report_error(_gate_key_name, str(e))
                                self.jarvis.key_router.release(_gate_key_name)
                            result['system_alert_text'] = f"\n[SYSTEM ALERT]: The memory module failed ({error_type}). YOU DID NOT RECORD ANYTHING. IF Sir requested a reminder, elegantly apologize, mention a brief cognitive glitch, and ask Sir to repeat."
                        return result
                    
                    gate_future = concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(_do_gatekeeper)
                
                # === 快轨：用原始 cmd 直接查 LTM，不等门神 ===
                ltm_context = "暂时未回想起相关的历史记录。"
                system_alert_text = ""
                clean_intent = cmd
                clean_cmd = cmd
                
                if len(cmd.split()) > 2 or len(cmd) > 8:
                    if self.DEBUG_LTM:
                        print(f"🧠 [Hippocampus Fast] 查询中: '{cmd[:60]}'")
                    try:
                        ltm_results = self.jarvis.hippocampus.search_memory(self.jarvis.gemini_key, cmd, top_k=2)
                        if ltm_results:
                            ltm_context = ""
                            for r in ltm_results:
                                time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['timestamp']))
                                env_tag = "Casual Chat" if r['environment'] in ['CHAT', 'CHAT_SUMMARY'] else f"Physical Task ({r['environment']})"
                                ltm_context += f"[{time_str}] {env_tag} -> Intent: {r['intent']} | Result: {r['summary']} \n"
                    except Exception as e:
                        if self.DEBUG_LTM:
                            try:
                                from jarvis_utils import bg_log as _bg
                                _bg(f"⚠️ [Fast LTM] Retrieval error: {e}")
                            except Exception:
                                pass
                
                self.jarvis._hot_reload_organs() 
                
                session_ctx = self.jarvis.preload_session_context()
                if session_ctx:
                    ltm_context += session_ctx
                
                _t_pre_llm = time.time()
                _t_gate_elapsed = _t_pre_llm - _t_gate_start
                
                # 👇 维护一个黑名单，把重型的 UI 器官排除在快思考之外。
                # 后续你加了小工具不用改这里，它会自动被主脑读取！只有需要控制鼠标/键盘的重型工具才加进这里。
                # ==========================================
# 📍 替换目标: jarvis_nerve.py (在 JarvisWorkerThread.run 中，组装 tool_instructions 的下方)
# ==========================================
                # 👇 维护一个黑名单，把重型的 UI 器官排除在快思考之外。
                FAST_CALL_BLACKLIST =["web_hands", "desktop_hands", "terminal_hands"]

                # [P0+18-d.6 / 2026-05-15] 主脑能看到的工具 hint：除了 manifest 顶层 description，
                # 额外明示高频"读"类子命令，让主脑知道"列代办 = memory_hands.list_reminders"
                # 这种语义→工具映射，避免它在 prompt block 空时只能猜。
                _KEY_SUBCOMMAND_HINTS = {
                    'memory_hands': (
                        '主要子命令: list_reminders={} (列未来日程) / search_memory={"query":...,"time_range_hours":N} '
                        '(检索过去聊天/任务) / add_reminder={"intent":..., "trigger_time":"YYYY-MM-DD HH:MM:00"} / '
                        'delete_record={"id":N} / modify_record={"id":N, "new_intent":..., "new_time":...}'
                    ),
                    'system_hands': '主要子命令: find_process / kill_process / shutdown / restart / lock_workstation',
                    'window_hands': '主要子命令: close_window / focus_window / minimize_window / maximize_window',
                    'audio_hands': '主要子命令: set_volume / mute / unmute',
                }

                _tool_lines = []
                for name, info in self.jarvis.hand_manifests.items():
                    if name in FAST_CALL_BLACKLIST:
                        continue
                    line = f"- {name}: {info['description']}"
                    hint = _KEY_SUBCOMMAND_HINTS.get(name)
                    if hint:
                        line += f"\n    {hint}"
                    _tool_lines.append(line)
                tool_instructions = "\n".join(_tool_lines)
                tool_instructions += "\n- ui_control: subtitle_on/off, orb_on/off"
                chat_organs = tool_instructions
                
                # 👇 核心新增：提取系统已知的物理信标（如真实的 D:\桌面），喂给聊天脑！
                landmark_file = os.path.join("jarvis_config", "os_landmarks.json")
                landmarks_str = ""
                if os.path.exists(landmark_file):
                    try:
                        with open(landmark_file, "r", encoding="utf-8") as f:
                            lms = json.load(f)
                            landmarks_str = "\n".join([f"- {k}: {v}" for k, v in lms.items()])
                    except: pass
                    
                def trigger_routing(task_cmd=clean_cmd, protocol_data=gate_data_to_save):
                    self.state_changed.emit("THINKING")
                    try:
                        import win32gui
                        hwnd = win32gui.GetForegroundWindow()
                        active_window_title = win32gui.GetWindowText(hwnd)
                        env_hint = f" [系统探针：用户当前正在看 '{active_window_title}' 窗口]"
                    except:
                        env_hint = ""
                        
                    self.jarvis.run(task_cmd + env_hint, memory_protocol=protocol_data)
                    self.state_changed.emit("IDLE")

                # 👇 核心修复 1：不要把 system_alert_text 拼进这里！保持纯净！
                enriched_cmd = f": {cmd}"

                # 👇 本地场景判定：协助LLM精准回应，减少prompt膨胀
                scene_tags = []
                cmd_words = cmd.lower().strip().split()
                cmd_clean = re.sub(r'[^\w\s]', '', cmd.lower()).strip()

                # [P0+18-b.9 / 2026-05-15] 把"对话激活"标志位前置到 prompt 装配开始之前。
                # 之前 set_conversation_active(True) 在 stream_chat 入口（line 7458），
                # 但 [Prompt Tier] / [Tone] / [Conversation Event] / [Memory Correction] 等
                # bg_log 发生在 stream_chat 调用**之前**的装配阶段 → _active=False 时直接打 stderr
                # → 漏到主对话框外（Sir 15:50 截图实测）。
                # 修法：提前 set_active(True)，所有装配阶段 bg_log 都进缓冲；stream_chat 收尾
                # 时统一在 ──── [Background] ──── 框里一次性 flush，主对话框只留 Human / Jarvis。
                # 闭环保证：stream_chat finally 已经会 set_active(False)；reflex_dict 短路路径
                # 不走到这里（更早就 return 了），不影响。
                try:
                    from jarvis_utils import set_conversation_active as _set_conv_active_b9
                    _set_conv_active_b9(True)
                except Exception:
                    pass

                # [R6/Tier] 一次性算出 5 档 prompt tier，下面 prompt 组装 + 截图分档都用它
                prompt_tier = self._classify_prompt_tier(cmd, cmd_clean, cmd_words)
                is_wake_only = (prompt_tier == self.PROMPT_TIER_WAKE_ONLY)

                # [R7-β4] 观察用户输入：连续要求"详细一点 / 短一点"会调整 sentence cap
                try:
                    vt = getattr(self.jarvis, 'verbosity_tracker', None)
                    if vt is not None:
                        _prev_cap = vt.cap_sentences
                        _new_cap = vt.observe(cmd)
                        if _new_cap != _prev_cap:
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"📏 [Verbosity] cap_sentences: {_prev_cap}→{_new_cap}")
                            except Exception:
                                pass
                except Exception:
                    pass

                work_category = PhysicalEnvironmentProbe.current_work_category
                if is_wake_only:
                    scene_tags.append("WAKE_ONLY")
                elif work_category == "Coding":
                    scene_tags.append("WORK_MODE")
                elif work_category == "Media":
                    scene_tags.append("RELAX_MODE")

                if scene_tags:
                    enriched_cmd = f"[{'|'.join(scene_tags)}] {cmd}"
                current_ledger = self.status_ledger.get_instant_ledger() if hasattr(self, 'status_ledger') else None

                # [R6/Tier] bg_log 一下分档结果方便回看（不阻塞、不进对话框）
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🎚️ [Prompt Tier] {prompt_tier}  (cmd_len={len(cmd)}, words={len(cmd_words)})")
                except Exception:
                    pass

                # 👇 核心改造 1：提前判断这句话是不是告退指令
                is_dismissal = any(w in cmd_lower for w in self.voice_thread.DISMISS_WORDS) if hasattr(self, 'voice_thread') else False

                self.state_changed.emit("THINKING")

                soul_tags = []
                if self.jarvis.soul_router:
                    soul_tags = self.jarvis.soul_router.route(enriched_cmd, stm_context)

                if self.pending_event:
                    event_text = f"[SYSTEM ALERT — CONVERSATION EVENT]: {self.pending_event}"
                    system_alert_text = event_text if not system_alert_text else system_alert_text + "\n" + event_text
                    self.pending_event = None

                _t_assemble_start = time.time()
                prompt = self.jarvis._assemble_prompt(
                    user_input=enriched_cmd,
                    stm_context=stm_context,
                    ltm_context=ltm_context,
                    chat_organs=chat_organs,
                    ledger_data=current_ledger,
                    landmarks_str=landmarks_str,
                    system_alert_text=system_alert_text,
                    mode="full",
                    soul_tags=soul_tags,
                    prompt_tier=prompt_tier,  # [R6/Tier] 走五档分流
                )
                _t_assemble_done = time.time()

                if hasattr(self, 'voice_thread') and self.voice_thread:
                    self.voice_thread._suppress_wave = True

                try:
                    # === 云端主脑，本地兜底 ===
                    _, jarvis_reply = self.chat_bypass.stream_chat(
                        prompt=prompt,
                        user_input=enriched_cmd,
                        clean_intent=clean_intent,
                        stm_context=stm_context,
                        ltm_context=ltm_context,
                        route_callback=trigger_routing,
                        gate_future=gate_future,
                        prompt_tier=prompt_tier,  # [R6/Tier+Screenshot] 把分档结果一路传到截图与流式逻辑
                    )
                finally:
                    if hasattr(self, 'voice_thread') and self.voice_thread:
                        self.voice_thread._suppress_wave = False
                
                _t_llm_done = time.time()
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⏱️ [Pipeline Timer] Full pipeline: {_t_llm_done - _t_pipeline_start:.1f}s")
                except Exception:
                    print(f"⏱️ [Pipeline Timer] Full pipeline: {_t_llm_done - _t_pipeline_start:.1f}s", file=sys.stderr)

                # 🧬 [P0+20-W.2 / 2026-05-16] 该轮收尾：清 turn_id（保留 session_id）
                # 之后的后台 daemon 日志不再带本轮 turn_id 前缀，避免误归因
                try:
                    from jarvis_utils import TraceContext
                    TraceContext.clear_turn()
                except Exception:
                    pass
                
                if not is_dismissal and jarvis_reply:
                    reply_lower = jarvis_reply.lower()
                    semantic_dismissal = (
                        reply_lower.startswith("standing down") or
                        reply_lower.startswith("goodbye") or
                        reply_lower.startswith("farewell") or
                        ("entering standby" in reply_lower and len(cmd_words) <= 5) or
                        ("going to sleep" in reply_lower and len(cmd_words) <= 5)
                    )
                    if semantic_dismissal:
                        is_dismissal = True
                        print("🧠 [Semantic Fallback] LLM reply contains farewell semantics, exiting focus mode。")
                
                # 👇 核心改造 2：如果是告退，说完就睡，绝对不再续命！
                if is_dismissal:
                    # [R7-α/B1] reason='dismissal'：用户告别
                    if self.state is not None:
                        self.state.set_awake(False, reason='dismissal', source='dismissal_path')
                    if hasattr(self, 'voice_thread'):
                        self.voice_thread.in_active_conversation = False
                        self.voice_thread.last_conversation_end_time = time.time()
                        self.voice_thread.last_dismissal_reason = 'manual_dismiss'  # [R6/B6]
                        self.voice_thread.awake_signal.emit(False)
                    if hasattr(self.chat_bypass, 'subtitle_queue'):
                        self.chat_bypass.subtitle_queue.put(("focus", False))
                    print("\n💤[System Standby] 告别完成，进入深度潜意识。")
                else:
                    # [R7-α/B1] reason='continuing_conversation'：对话还在进行
                    if self.state is not None:
                        self.state.set_awake(True, reason='continuing_conversation', source='post_chat')
                    if hasattr(self, 'voice_thread'):
                        self.voice_thread.in_active_conversation = True
                        self.voice_thread.last_interaction_time = time.time()
                        self.voice_thread.last_dismissal_reason = None  # [R6/B6] 对话继续中，清空 dismissal 痕迹
                        self.voice_thread.awake_signal.emit(True)
                    if hasattr(self.chat_bypass, 'subtitle_queue'):
                        self.chat_bypass.subtitle_queue.put(("focus", True))
                
                if not jarvis_reply or jarvis_reply.strip() == "":
                    print("⚠️ [System Fallback] LLM 回复真空，触发本地管家协议...")
                    local_reply = self.chat_bypass._try_local_fallback(enriched_cmd, stm_context)
                    if local_reply:
                        print(f"║ 🔄 [本地兜底] 切换到 {get_local_fallback()._model}")
                        print(f"║ 🤖  [Jarvis-Local] {local_reply[:200]}")
                        self.chat_bypass._speak_local_reply(local_reply)
                        jarvis_reply = local_reply
                    else:
                        self.chat_bypass.audio_queue.put(("As you wish, Sir.", {}))
                        jarvis_reply = "As you wish, Sir."
                
                # 无论是不是任务，大模型生成的这句完美的客套话/聊天，都要记入海马体
                final_clean_reply = jarvis_reply.replace("<START_ROUTING>", "").strip() if jarvis_reply else ""
                
                filtered_reply = final_clean_reply
                hallucination_patterns = [
                    r'\d{1,3}%\s*(battery|power|charge|remaining)',
                    r'(battery|power|charge)\s*(at|is at|level|remaining)\s*\d{1,3}%',
                    r'your\s+(remaining\s+)?\d{1,3}%',
                ]
                for pat in hallucination_patterns:
                    if re.search(pat, filtered_reply, re.IGNORECASE):
                        print(f"║ 🛡️  [Hallucination Filter] 电池幻觉已检测，已从 STM 清除")
                        filtered_reply = re.sub(pat, '[FILTERED]', filtered_reply, flags=re.IGNORECASE)
                
                # === 后置幻觉守门（B 守门人 / 轻档）：贾维斯声称完成动作但实际没成功 ===
                # 触发条件（两档）：reply 非空 + 长度足够 + 1.5B 判定为 claim，并且
                #   档 1：本轮根本没调任何工具（`not _has_tool_results`）
                #   档 2：[P1] 工具链熔断（`_circuit_broken_reason` 非空）——
                #         即使 _tool_results 有失败记录，熔断意味着 LLM 没按计划走完，
                #         若它仍然回复"已搞定"则同样是言行不一。
                # 处理方式：终端告警 + 在 STM 的 jarvis 字段加 [INTEGRITY] 后缀，下一轮 prompt 看见
                _has_tool_results = bool(getattr(self.chat_bypass, '_last_tool_results', []))
                _cb_reason = getattr(self.chat_bypass, '_last_circuit_broken_reason', None)
                _integrity_note = ""
                # [P0+18-a.16 / 2026-05-15] CapabilityClaimValidator —— post-hoc 抓"我能用 X 查 Y"
                # 型越界许诺（不在 _should_check_integrity 闸内：本检测**与是否调过工具无关**，
                # 即使主脑只是口头提议没真跑工具，也要拦）
                _capability_note = ""
                try:
                    from jarvis_skill_registry import CapabilityClaimValidator as _CCV
                    _cap_violations = _CCV.detect_violations(filtered_reply) if filtered_reply else []
                    if _cap_violations:
                        try:
                            from jarvis_utils import bg_log as _bg_log
                            for _v in _cap_violations:
                                _bg_log(
                                    f"🚨 [Capability Overreach] skill=`{_v.get('skill','?')}` "
                                    f"claimed=`{', '.join(_v.get('matched_phrases',[])[:3])}` "
                                    f"but cannot_provide blocks it (承诺必行)"
                                )
                        except Exception:
                            pass
                        _capability_note = _CCV.format_violation_note(_cap_violations)
                        # 同步推 event_bus（让其他模块 / 主脑下一轮能 cross-check 看到）
                        try:
                            _bus = getattr(self.jarvis, 'event_bus', None)
                            if _bus is not None:
                                _bus.publish(
                                    etype='capability_overreach_detected',
                                    description=(
                                        f"[capability_overreach] Jarvis offered skills "
                                        f"that cannot deliver the claimed info: "
                                        f"{[v.get('skill') for v in _cap_violations]}"
                                    )[:300],
                                    source='capability_claim_validator',
                                    metadata={
                                        'violations': _cap_violations[:5],
                                        'reply_excerpt': filtered_reply[:200],
                                        'detected_at': time.time(),
                                    },
                                )
                        except Exception:
                            pass
                except Exception:
                    pass
                _should_check_integrity = (
                    filtered_reply and len(filtered_reply.strip()) >= 15
                    and ((not _has_tool_results) or _cb_reason)
                )
                if _should_check_integrity:
                    try:
                        _qc = get_quick_classifier()
                        if _qc.is_available:
                            _t_intg_start = time.time()
                            _is_claim = _qc.detect_action_claim(filtered_reply)
                            _intg_ms = int((time.time() - _t_intg_start) * 1000)
                            if _is_claim:
                                _label = (
                                    "no_tool_called" if not _has_tool_results
                                    else f"circuit_broken:{_cb_reason}"
                                )
                                print(f"\n║ 🚨 [Integrity Check] 言行不一警告（{_intg_ms}ms / 1.5B 检测 / {_label}）")
                                print(f"║   贾维斯声称完成了某动作但本轮{'未调用任何工具' if not _has_tool_results else '工具链已熔断（' + str(_cb_reason) + '）'}。")
                                print(f"║   原话: {filtered_reply[:140]}")
                                print(f"║   STM 将加注 [claim_unverified]，下一轮主脑会被提醒。")
                                if not _has_tool_results:
                                    _integrity_note = " [INTEGRITY NOTE: I claimed to have performed an action above, but I did NOT actually execute any tool. If Sir asks, I must admit honestly that I cannot do that.]"
                                else:
                                    _integrity_note = f" [INTEGRITY NOTE: I claimed completion, but the tool chain was circuit-broken ({_cb_reason}) and did not finish as planned. If Sir asks, I must admit honestly what actually succeeded and what didn't.]"
                                # [P0-4 / 2026-05-15] 把 hallucination 信号同步推到 event_bus，
                                # 让下一轮 prompt assembler 立刻看到（比 STM [INTEGRITY NOTE] 早一拍 +
                                # 让其他模块如 CommitmentWatcher/SmartNudge 也能联动，不是只主脑可见）。
                                # 这样 Conductor 在拿到 hallucination 信号后 30 秒内不应再触发 follow-up
                                # 类 nudge（避免"嘴上说完了→Conductor 又催"的二段叠加迷惑）。
                                try:
                                    _bus = getattr(self.jarvis, 'event_bus', None)
                                    if _bus is not None:
                                        _bus.publish(
                                            etype='hallucination_detected',
                                            description=f"[{_label}] Jarvis claimed action but didn't execute: \"{filtered_reply[:120]}\"",
                                            source='integrity_check',
                                            metadata={
                                                'label': _label,
                                                'has_tool_results': _has_tool_results,
                                                'circuit_broken_reason': _cb_reason,
                                                'reply_excerpt': filtered_reply[:200],
                                                'detected_at': time.time(),
                                            },
                                        )
                                except Exception:
                                    pass
                    except Exception as _e:
                        pass
                
                # === 收集门神慢轨结果：分岔策略 ===
                # 关键路径（排期/提醒/记忆）：必须等门神确认存上了才能回复
                # 闲聊路径：异步存储，不阻塞对话
                import re as _re_schedule
                _critical_keywords = [
                    r'remind\s+me', r'set\s+(an?\s+)?alarm', r'schedule', r'wake\s+me\s+up',
                    r'提醒我', r'闹钟', r'叫醒我', r'定个', r'设个', r'排期',
                    r'at\s+\d', r'\d+\s*o\'?clock', r'\d+点', r'\d+:\d+',
                    r'remember', r'记下', r'记住', r'保存', r'note\s+this',
                    r'cancel.*remind', r'取消.*提醒', r'取消.*闹钟',
                ]
                _is_critical = any(_re_schedule.search(kw, cmd_lower) for kw in _critical_keywords)
                
                if gate_future:
                    if _is_critical:
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"🔒 [Gatekeeper Sync] 检测到日程/记忆关键词，等待守门人...")
                        except Exception:
                            print(f"🔒 [Gatekeeper Sync] 检测到日程/记忆关键词，等待守门人...", file=sys.stderr)
                        try:
                            gate_result = gate_future.result(timeout=25.0)
                            if gate_result.get('clean_intent') and gate_result['clean_intent'] != cmd:
                                clean_intent = gate_result['clean_intent']
                            if gate_result.get('gate_data_to_save'):
                                gate_data_to_save = gate_result['gate_data_to_save']
                            if gate_result.get('system_alert_text'):
                                system_alert_text = gate_result['system_alert_text']
                            if gate_result.get('conversation_event') and isinstance(gate_result['conversation_event'], dict):
                                event = gate_result['conversation_event']
                                self.pending_event = event.get('description', '')
                            _t_gate_done = time.time()
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"⏱️ [Gatekeeper Slow] 解析完成: {_t_gate_done - _t_gate_start:.1f}s (同步等待)")
                            except Exception:
                                print(f"⏱️ [Gatekeeper Slow] 解析完成: {_t_gate_done - _t_gate_start:.1f}s (同步等待)", file=sys.stderr)
                        except concurrent.futures.TimeoutError:
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"⚠️ [Gatekeeper Slow] 结果收集超时！关键路径存储未确认")
                            except Exception:
                                print(f"⚠️ [Gatekeeper Slow] 结果收集超时！关键路径存储未确认", file=sys.stderr)
                            jarvis_reply = "Sir, my memory system is currently overloaded. I heard you but couldn't confirm the save. Could you repeat that?"
                            final_clean_reply = jarvis_reply
                            filtered_reply = jarvis_reply
                            self.chat_bypass.audio_queue.put((jarvis_reply, {}))
                        except Exception as e:
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"⚠️ [Gatekeeper Slow] 结果收集异常: {e}")
                            except Exception:
                                print(f"⚠️ [Gatekeeper Slow] 结果收集异常: {e}", file=sys.stderr)
                            jarvis_reply = "I encountered an error processing that request, Sir. Please try again."
                            final_clean_reply = jarvis_reply
                            filtered_reply = jarvis_reply
                            self.chat_bypass.audio_queue.put((jarvis_reply, {}))
                        
                        self.jarvis.short_term_memory.append({
                            "time": time.strftime("%H:%M:%S"),
                            "user": clean_intent,
                            "jarvis": filtered_reply + _integrity_note + _capability_note
                        })
                        if hasattr(self, 'commitment_watcher') and self.commitment_watcher:
                            self.commitment_watcher.extract_from_input(clean_intent)
                        # [R7-β4] 记录 Jarvis 回复供"防套话密度版"统计
                        try:
                            pt = getattr(self.jarvis, 'phrase_tracker', None)
                            if pt is not None and final_clean_reply:
                                pt.record_reply(final_clean_reply)
                        except Exception:
                            pass
                        if final_clean_reply:
                            self.jarvis.hippocampus.seal_chat_async(
                                self.jarvis.gemini_key, clean_intent, final_clean_reply,
                                memory_protocol=gate_data_to_save
                            )
                    else:
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"🔓 [Gatekeeper Async] 聊天路径，后台存储非阻塞")
                        except Exception:
                            print(f"🔓 [Gatekeeper Async] 聊天路径，后台存储非阻塞", file=sys.stderr)
                        def _async_gate_collect():
                            nonlocal clean_intent, gate_data_to_save, system_alert_text
                            try:
                                gate_result = gate_future.result(timeout=30.0)
                                if gate_result.get('clean_intent') and gate_result['clean_intent'] != cmd:
                                    clean_intent = gate_result['clean_intent']
                                if gate_result.get('gate_data_to_save'):
                                    gate_data_to_save = gate_result['gate_data_to_save']
                                if gate_result.get('system_alert_text'):
                                    system_alert_text = gate_result['system_alert_text']
                                if gate_result.get('conversation_event') and isinstance(gate_result['conversation_event'], dict):
                                    event = gate_result['conversation_event']
                                    self.pending_event = event.get('description', '')
                                _t_gate_done = time.time()
                                try:
                                    from jarvis_utils import bg_log
                                    bg_log(f"⏱️ [Gatekeeper Slow] 解析完成: {_t_gate_done - _t_gate_start:.1f}s (后台异步)")
                                except Exception:
                                    print(f"⏱️ [Gatekeeper Slow] 解析完成: {_t_gate_done - _t_gate_start:.1f}s (后台异步)", file=sys.stderr)
                            except concurrent.futures.TimeoutError:
                                try:
                                    from jarvis_utils import bg_log
                                    bg_log(f"⚠️ [Gatekeeper Slow] 结果收集超时，使用默认协议")
                                except Exception:
                                    print(f"⚠️ [Gatekeeper Slow] 结果收集超时，使用默认协议", file=sys.stderr)
                            except Exception as e:
                                try:
                                    from jarvis_utils import bg_log
                                    bg_log(f"⚠️ [Gatekeeper Slow] 结果收集异常: {e}")
                                except Exception:
                                    print(f"⚠️ [Gatekeeper Slow] 结果收集异常: {e}", file=sys.stderr)
                            
                            self.jarvis.short_term_memory.append({
                                "time": time.strftime("%H:%M:%S"),
                                "user": clean_intent,
                                "jarvis": filtered_reply + _integrity_note + _capability_note
                            })
                            if hasattr(self, 'commitment_watcher') and self.commitment_watcher:
                                self.commitment_watcher.extract_from_input(clean_intent)
                            # [R7-β4] 记录 Jarvis 回复
                            try:
                                pt = getattr(self.jarvis, 'phrase_tracker', None)
                                if pt is not None and final_clean_reply:
                                    pt.record_reply(final_clean_reply)
                            except Exception:
                                pass
                            if final_clean_reply:
                                self.jarvis.hippocampus.seal_chat_async(
                                    self.jarvis.gemini_key, clean_intent, final_clean_reply,
                                    memory_protocol=gate_data_to_save
                                )
                        
                        threading.Thread(target=_async_gate_collect, daemon=True).start()
                else:
                    _gate_data = gate_data_to_save
                    _gate_intent = clean_intent
                    if hasattr(self.chat_bypass, '_gate_data_to_save') and self.chat_bypass._gate_data_to_save:
                        _gate_data = self.chat_bypass._gate_data_to_save
                    if hasattr(self.chat_bypass, '_gate_clean_intent') and self.chat_bypass._gate_clean_intent:
                        _gate_intent = self.chat_bypass._gate_clean_intent
                    self.jarvis.short_term_memory.append({
                        "time": time.strftime("%H:%M:%S"),
                        "user": _gate_intent,
                        "jarvis": filtered_reply + _integrity_note + _capability_note
                    })
                    if hasattr(self, 'commitment_watcher') and self.commitment_watcher:
                        self.commitment_watcher.extract_from_input(_gate_intent)
                    # [R7-β4] 记录 Jarvis 回复
                    try:
                        pt = getattr(self.jarvis, 'phrase_tracker', None)
                        if pt is not None and final_clean_reply:
                            pt.record_reply(final_clean_reply)
                    except Exception:
                        pass
                    if final_clean_reply:
                        self.jarvis.hippocampus.seal_chat_async(
                            self.jarvis.gemini_key, _gate_intent, final_clean_reply,
                            memory_protocol=_gate_data
                        )

                # [P0+18-b.3 / 2026-05-15] [Focus Mode] 框改 bg_log：原来打印在主对话
                # ╚═══ 之后会把 [Gatekeeper Slow] / [KeyRouter] 等 bg_log flush 内容夹在
                # 中间，视觉上像"两条横线分隔不清"。改 bg_log 后会跟 ──── [Background] ────
                # 框统一渲染，主对话框 ╚═══ 后是干净的换行 + 背景框。
                try:
                    from jarvis_utils import bg_log
                    if is_dismissal:
                        bg_log("💤 [System Standby] 告别完成，进入深度潜意识。Waiting for voice wake ('Jarvis...')...")
                    elif is_wake_only:
                        bg_log("👂 [Focus Mode] Jarvis ready, listening...")
                    else:
                        bg_log(f"⏰ [{time.strftime('%H:%M:%S')}] 👂 [Focus Mode] 对话完成，Jarvis 继续聆听...")
                except Exception:
                    print("\n" + "═"*65)
                    if is_dismissal:
                        print("💤 [System Standby] 告别完成，进入深度潜意识。")
                        print("Waiting for voice wake ('Jarvis...')...")
                    elif is_wake_only:
                        print("👂 [Focus Mode] Jarvis ready, listening...")
                    else:
                        print(f"⏰ [{time.strftime('%H:%M:%S')}] 👂 [Focus Mode] 对话完成，Jarvis 继续聆听...")
                    print("═"*65 + "\n")
                
            self.msleep(100)

from PyQt5.QtWidgets import QOpenGLWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QPainter, QColor, QLinearGradient, QPen
from PyQt5.QtCore import QRectF, QPointF
from OpenGL.GL import *
from OpenGL.GL import shaders
import time
import math


# [P0+19-final fix 5 / 2026-05-16] 全量跨模块类引用兜底（try/except 防循环依赖）
try:
    from jarvis_safety import *  # noqa: F401, F403
except Exception:
    pass
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except Exception:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except Exception:
    pass
try:
    from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
except Exception:
    pass
try:
    from jarvis_sensors import (  # noqa: F401
        FunnelLogger, SensorFilter, HabitClock, CausalChain,
        ProjectTimeline, SubconsciousMailbox,
    )
except Exception:
    pass
try:
    from jarvis_routing import (  # noqa: F401
        SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard,
        PromptCenter, GuardianCenter, CompanionCenter,
    )
except Exception:
    pass
try:
    from jarvis_memory_core import (  # noqa: F401
        PromptLayer, PromptCache, CorrectionEntry, CorrectionMemory,
        MemoryFragment, UnifiedMemoryGateway, FeedbackTracker,
        TaskWorkerPool, Anticipator, CorrectionLoop, SleepIntentDetector,
        HumorMemory,
    )
except Exception:
    pass
try:
    from jarvis_sentinels import (  # noqa: F401
        ChronosTick, ChronosSentinel, SystemSentinel, SoulArchivistSentinel,
        NudgeGate, UserStatusLedgerSentinel, ScreenshotSentinel,
        WellnessGuardian, ReflectionScheduler,
    )
except Exception:
    pass
try:
    from jarvis_conductor import Conductor  # noqa: F401
except Exception:
    pass
try:
    from jarvis_return_sentinel import ReturnSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_commitment_watcher import CommitmentWatcher  # noqa: F401
except Exception:
    pass
try:
    from jarvis_smart_nudge import SmartNudgeSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS  # noqa: F401
except Exception:
    pass
try:
    from jarvis_blood import (  # noqa: F401
        JarvisBlood, ExecutionResult, FeedbackSignal, Action, PerceptionData, TaskSnapshot,
    )
except Exception:
    pass
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except Exception:
    pass
try:
    from jarvis_vocal_cord import VocalCord  # noqa: F401
except Exception:
    pass
try:
    from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401
except Exception:
    pass
try:
    from jarvis_skill_registry import (  # noqa: F401
        SkillRegistry, SkillManifest, OfferGuard, PromiseExecutor, PromiseActivator,
        get_registry,
    )
except Exception:
    pass
try:
    from l1_right_brain import RightBrain  # noqa: F401
except Exception:
    pass
try:
    from l3_left_brain import LeftBrain  # noqa: F401
except Exception:
    pass
try:
    from l5_reflection_brain import ReflectionBrain  # noqa: F401
except Exception:
    pass
try:
    from jarvis_utils import (  # noqa: F401
        bg_log, set_conversation_active, is_conversation_active,
        register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
        safe_gemini_call, safe_openrouter_call, create_genai_client,
        get_local_fallback, QuickClassifier, get_quick_classifier,
        ConversationEventBus, JarvisState, PlanLedger, WorkingMemoryFeed,
        SessionDigest, ToneSelector, AntiCommonPhraseTracker,
        VerbosityPreferenceTracker, ProjectContextProbe,
        ClipboardWatcher, PSHistoryWatcher, AttentionSlot,
        render_yesterday_block, render_open_threads_block,
        render_active_reminders_block, render_attention_block,
        render_silent_nudge_text, render_project_block,
        extract_open_threads, capture_attention_snapshot,
        resolve_nudge_channel, network_retry, get_rate_limiter,
        get_default_attention_slot, get_default_event_bus,
        get_default_phrase_tracker, get_default_plan_ledger,
        get_default_tone_selector, get_default_verbosity_tracker,
        get_default_working_feed,
    )
except Exception:
    pass

