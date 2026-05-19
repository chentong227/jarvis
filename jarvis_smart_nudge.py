# -*- coding: utf-8 -*-
"""[P0+19-6.e / 2026-05-16] SmartNudge 哨兵 — 11 种 nudge 类型 + type-mute (P0+18-f.3) + humor_memory

从 jarvis_nerve.py 拆出 1 个大类（>500 行）。
向后兼容：jarvis_nerve.py 用 `from jarvis_smart_nudge import SmartNudgeSentinel` 转发，
旧 `from jarvis_nerve import SmartNudgeSentinel` 0 改动。
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
import threading
import queue
import random
import collections
import sqlite3  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional  # noqa: F401

# 🩹 [P0+20-β.1.7 / 2026-05-16] P0+19-6.e 拆分留尾：win32api 没 import →
# line 195/208 NameError → 主 while-True 循环 idle_ms 永 0 → 睡眠/凌晨深度休眠
# /idle_ms > 30000 等分支全失真。修法：try-import 容错（开发机无 pywin32 仍可跑测）。
try:
    import win32api  # noqa: F401
    import win32gui  # noqa: F401
    import win32con  # noqa: F401
except Exception:
    win32api = None  # type: ignore
    win32gui = None  # type: ignore
    win32con = None  # type: ignore

# 跨文件依赖（上游已拆完）
from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
# [P0+19-final fix 2]
from google.genai import types  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401  # noqa: F401
from jarvis_sensors import (  # noqa: F401
    SubconsciousMailbox, CausalChain, HabitClock,
    FunnelLogger, SensorFilter, ProjectTimeline,
)
from jarvis_sentinels import NudgeGate  # noqa: F401

# [P0+19-final fix / 2026-05-16] 补全跨模块依赖（拆分后实例化时才暴露的缺失）
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_blood import JarvisBlood, ExecutionResult, FeedbackSignal  # noqa: F401
except ImportError:
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
except ImportError:
    pass



from jarvis_memory_core import HumorMemory  # noqa: F401

class SmartNudgeSentinel(threading.Thread):
    """LLM人格路径：纯物理规则触发 + 投递 __NUDGE__ 到主脑"""
    def __init__(self, jarvis_worker, nudge_gate=None, humor_memory=None):
        super().__init__(daemon=True)
        self.worker = jarvis_worker
        self.gate = nudge_gate
        self.last_nudge_time = {}
        self.daily_nudge_count = 0
        self.last_reset_day = ""
        self.recent_nudge_topics = []
        # [P0+14 / 2026-05-15] HumorMemory 共享单例 —— 之前 SmartNudge 自创一个，
        # main 段 jarvis_worker.humor_memory 又创一个，"新笑话注册" vs "可以开玩笑检查"
        # 对的不是同一个实例，状态不同步。现在允许外部注入；不传则向后兼容自建。
        # main 段会优先把 jarvis_worker.humor_memory 注入这里。
        self.humor_memory = humor_memory if humor_memory is not None else HumorMemory()
        self._refused_help_until = 0.0
        self._help_refusal_history = []
        self._last_help_fingerprint = ""
        self._last_help_fingerprint_time = 0.0
        # [P0+18-f.3 / 2026-05-15] Long-term mute by nudge_type
        # Sir 22:13:58 实测：dormant_project 触发后说"不用再提"，旧版只 HardFreeze 300s
        # → 5min 后又冒同款 nudge。新机制：记最后一个 nudge_type + 时间,
        # 用户拒绝则把该 nudge_type mute 12-24h（强拒绝 24h / 普通 12h），同 fingerprint
        # 全天/半天不再触发。
        self._muted_nudge_types = {}  # {nudge_type: mute_until_ts}
        self._last_nudge_type = ""
        self._last_nudge_time = 0.0
        self._sleep_nudge_history = []
        self._unanswered_sleep_nudges = 0
        self._last_sleep_nudge_time = 0.0
        self._sleep_nudge_escalation_level = 0
        self._nudge_cooldowns = {
            "hydration": 5400,
            "stretch": 7200,
            "late_night": 3600,
            "atmosphere": 14400,
            "screen_tease": 14400,
            "afternoon": 7200,
            "flow_end": 10800,
            "dormant_project": 21600,
        }
        self._daily_limits = {
            "hydration": 3,
            "stretch": 2,
            "late_night": 3,
            "atmosphere": 1,
            "screen_tease": 1,
            "afternoon": 1,
            "flow_end": 2,
            "dormant_project": 2,
        }
        self._type_counts = {}

    def run(self):
        time.sleep(25)
        print("[SmartNudgeSentinel] 智能提醒引擎就绪...")
        # [β.5.6 / 2026-05-19] skip publish helper + dedupe
        # 防 while True 循环 publish 风暴: 同 reason 60s 内只 publish 1 次
        self._skip_publish_last_t = {}
        def _publish_skip(skip_reason: str, extra_meta: dict = None):
            try:
                _now = time.time()
                _last = self._skip_publish_last_t.get(skip_reason, 0)
                if _now - _last < 60.0:
                    return  # dedupe
                self._skip_publish_last_t[skip_reason] = _now
                # GC 5min 以前
                self._skip_publish_last_t = {
                    k: v for k, v in self._skip_publish_last_t.items()
                    if _now - v < 300
                }
                from jarvis_utils import get_event_bus
                _bus = get_event_bus()
                if _bus is None:
                    return
                meta = {
                    'decision': 'block',
                    'block_reason': skip_reason,
                }
                if extra_meta:
                    meta.update(extra_meta)
                _bus.publish(
                    etype='gate_advice',
                    description=f"SmartNudge skipped tick: {skip_reason}",
                    source='SmartNudge',
                    metadata=meta,
                    salience=0.4,  # tick skip 是背景信号
                )
            except Exception:
                pass
        # 暴露给 instance 让 sub-method 能用 (虽然现在只 inline)
        self._publish_skip = _publish_skip
        while True:
            try:
                current_day = time.strftime("%Y-%m-%d")
                if current_day != self.last_reset_day:
                    self.daily_nudge_count = 0
                    self._type_counts = {}
                    self.last_reset_day = current_day

                if self.daily_nudge_count >= 8:
                    _publish_skip('daily_quota_exhausted',
                                  {'daily_nudge_count': self.daily_nudge_count})
                    time.sleep(60)
                    continue

                if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread.in_active_conversation:
                    _publish_skip('in_active_conversation')
                    time.sleep(10)
                    continue

                # 🩹 [β.2.7.10 / 2026-05-17] Sir 旁路对话期间 (打电话/和家人说话) 静默
                # Jarvis 察觉 Sir 在和外人说 → 当前不打扰. 旁路计数 ≥ 2 即静默 90s
                try:
                    _vt = getattr(self.worker, 'voice_thread', None)
                    if _vt is not None:
                        _bp = getattr(_vt, '_bypass_speech_count', 0)
                        if _bp >= 2:
                            _publish_skip(f'bypass_speech_count_{_bp}',
                                          {'bypass_count': _bp})
                            time.sleep(90)
                            continue
                except Exception:
                    pass

                # [P0+20-α.4 / 2026-05-16] standby 静默窗口（60s）：
                # 解决 jarvis_20260516_092307.log 中 standby 9s 后就触发 dormant_project 的问题。
                # 原因：对话结束后 active_conversation→False，但 SmartNudge 主循环立即继续 tick，
                #       下一轮就把 dormant_project 排进候选。Sir 刚说完话还没反应过来就被骚扰。
                # 修法：从 JarvisState 拿 seconds_since_conv_off()，< 60s 整体跳过本 tick。
                try:
                    state = getattr(self.worker.jarvis, 'state', None) if hasattr(self.worker, 'jarvis') else None
                    if state is not None:
                        secs_off = state.seconds_since_conv_off()
                        if 0 <= secs_off < 60.0:
                            _publish_skip(f'standby_silence_{int(secs_off)}s_since_conv_off',
                                          {'secs_since_conv_off': int(secs_off)})
                            time.sleep(5)
                            continue
                except Exception:
                    pass

                if self.gate and self.gate.is_sleep_mode():
                    idle_ms = 0
                    try:
                        idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                    except:
                        pass
                    # 🩹 [β.2.9.1.1 / 2026-05-18] Sir 01:14 反馈 "判断太广": 5s idle 阈值
                    # 让 Sir 瞬时键鼠扰动 (碰一下鼠标) 就解 sleep mode. 准则 6 反例.
                    # 改 30s 阈值 — Sir 真坐回电脑前 30s 持续活跃才算"真醒".
                    if idle_ms < 30000:
                        self.gate.deactivate_sleep_mode()
                        # [P0+20-β.2.4 hotfix / 2026-05-16] P0+19 split 后 worker
                        # 直持 _on_activity_wake，原 worker.jarvis 守卫永不通 → 失效。
                        try:
                            from jarvis_utils import resolve_worker_attr
                            _wake = resolve_worker_attr(self.worker, '_on_activity_wake')
                            if _wake is not None:
                                _wake()
                        except Exception:
                            pass
                        continue
                    time.sleep(30)
                    continue

                idle_ms = 0
                try:
                    idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                except:
                    pass

                current_hour = int(time.strftime("%H"))
                if 1 <= current_hour < 6 and idle_ms > 1200000:
                    if self.gate and not self.gate.is_sleep_mode():
                        self.gate.activate_sleep_mode()
                        print(f"\n[SmartNudgeSentinel] 深度休眠检测: 凌晨{current_hour}点闲置{idle_ms // 60000}分钟，自动进入睡眠模式")
                    time.sleep(30)
                    continue

                if idle_ms > 30000:
                    time.sleep(10)
                    continue

                work_duration = PhysicalEnvironmentProbe.work_duration_minutes
                work_category = PhysicalEnvironmentProbe.current_work_category
                current_hour = int(time.strftime("%H"))
                window_title = ""
                process_name = PhysicalEnvironmentProbe.current_process_name
                try:
                    import win32gui
                    hwnd = win32gui.GetForegroundWindow()
                    window_title = win32gui.GetWindowText(hwnd) if hwnd else ""
                except:
                    pass

                recent_switches = 0
                try:
                    cutoff = time.time() - 180
                    last_title = None
                    for entry in PhysicalEnvironmentProbe.window_history:
                        if entry["time"] >= cutoff:
                            if last_title is not None and entry["title"] != last_title and entry["title"] != "":
                                recent_switches += 1
                            last_title = entry["title"]
                except:
                    pass

                nudge_type = None
                nudge_context = {}
                candidates = []

                if work_duration > 75 and work_category != "AFK" and not (23 <= current_hour or current_hour < 6):
                    candidates.append(("hydration", {"work_duration": int(work_duration), "work_category": work_category}))

                if work_duration > 100 and work_category == "Coding":
                    candidates.append(("stretch", {"work_duration": int(work_duration)}))

                if work_category == "Coding" and 1 <= current_hour < 6 and work_duration > 150:
                    candidates.append(("late_night", {"work_duration": int(work_duration), "current_hour": current_hour}))

                if work_category == "Media" and 18 <= current_hour < 23:
                    try:
                        from pycaw.pycaw import AudioUtilities
                        sessions = AudioUtilities.GetAllSessions()
                        has_audio = False
                        for s in sessions:
                            if s.Process and s.Process.name() != "System Sounds":
                                try:
                                    vol = s.SimpleAudioVolume.GetMasterVolume()
                                    if vol > 0.01:
                                        has_audio = True
                                        break
                                except:
                                    pass
                        if has_audio:
                            candidates.append(("atmosphere", {"window_title": window_title}))
                    except:
                        pass

                if window_title:
                    lower_title = window_title.lower()
                    error_kw = ["error", "exception", "failed", "traceback", "崩溃", "报错", "404", "500", "stack trace", "undefined", "null pointer"]
                    fun_kw = ["bilibili", "youtube", "直播", "游戏", "steam", "netflix", "视频", "番剧", "twitch"]
                    slack_kw = ["reddit", "twitter", "微博", "知乎", "douyin", "抖音", "xiaohongshu", "小红书"]

                    if any(kw in lower_title for kw in error_kw):
                        candidates.append(("screen_tease", {"window_title": window_title, "category": "error"}))
                    elif any(kw in lower_title for kw in fun_kw):
                        candidates.append(("screen_tease", {"window_title": window_title, "category": "entertainment"}))
                    elif any(kw in lower_title for kw in slack_kw):
                        candidates.append(("screen_tease", {"window_title": window_title, "category": "slacking"}))

                if 14 <= current_hour < 17 and work_duration > 90 and work_category == "Coding":
                    candidates.append(("afternoon", {"work_duration": int(work_duration)}))

                prev_category = getattr(self, '_prev_work_category', None)
                if prev_category == "Coding" and work_category != "Coding" and work_category != "AFK":
                    prev_duration = getattr(self, '_prev_coding_duration', 0)
                    if prev_duration > 60:
                        candidates.append(("flow_end", {"prev_duration": int(prev_duration), "new_category": work_category}))

                if work_category == "Coding":
                    self._prev_coding_duration = work_duration
                elif work_category != "Coding":
                    self._prev_coding_duration = 0
                self._prev_work_category = work_category

                if work_category == "Coding" and 9 <= current_hour < 23:
                    try:
                        if hasattr(self.worker, 'hippocampus'):
                            dormant = self.worker.hippocampus.get_dormant_projects(dormant_days=3)
                            if dormant:
                                candidates.append(("dormant_project", {"dormant_projects": dormant}))
                    except:
                        pass

                if candidates:
                    nudge_type, nudge_context = self._select_best_nudge(candidates, work_duration, work_category, current_hour)

                if nudge_type:
                    now = time.time()
                    cooldown = self._nudge_cooldowns.get(nudge_type, 3600)

                    if nudge_type in ("late_night", "suggest_break"):
                        cooldown = self._calc_sleep_nudge_cooldown(nudge_type, cooldown)

                    # 🩹 [P0+20-β.1.17 / 2026-05-16] 拦截可见性日志
                    # 🩹 [P0+20-β.1.19 / 2026-05-16] throttle：每 nudge_type 每道闸 5min 最多一行
                    # 治 Sir 18:43 截图刷屏：主循环 5s tick → 每秒一行拦截日志 → 终端被刷屏
                    if not hasattr(self, '_skip_log_last'):
                        self._skip_log_last = {}
                    _SKIP_LOG_INTERVAL = 300.0  # 5min

                    def _maybe_log_skip(_reason_key: str, _msg: str):
                        _last = self._skip_log_last.get(_reason_key, 0.0)
                        if now - _last >= _SKIP_LOG_INTERVAL:
                            self._skip_log_last[_reason_key] = now
                            try:
                                from jarvis_utils import bg_log as _smb_log
                                _smb_log(_msg)
                            except Exception:
                                pass

                    _last_t = self.last_nudge_time.get(nudge_type, 0)
                    _cd_remaining = cooldown - (now - _last_t)
                    if _cd_remaining > 0:
                        _maybe_log_skip(
                            f'cd:{nudge_type}',
                            f"⏸️ [SmartNudge/Skip] {nudge_type} cooldown 未过 "
                            f"(剩 {int(_cd_remaining)}s / cooldown={int(cooldown)}s) "
                            f"[5min throttle]"
                        )
                    else:
                        daily_limit = self._daily_limits.get(nudge_type, 3)
                        type_count = self._type_counts.get(nudge_type, 0)
                        if type_count >= daily_limit:
                            _maybe_log_skip(
                                f'limit:{nudge_type}',
                                f"⏸️ [SmartNudge/Skip] {nudge_type} 今日已达上限 "
                                f"({type_count}/{daily_limit}) [5min throttle]"
                            )
                        else:
                            # 检查 type-mute（Sir 之前说过"别再提 X 类"）
                            _muted_until = self._muted_nudge_types.get(nudge_type, 0.0)
                            if now < _muted_until:
                                _maybe_log_skip(
                                    f'mute:{nudge_type}',
                                    f"🔇 [SmartNudge/Muted] {nudge_type} type-muted "
                                    f"(剩 {int((_muted_until - now) / 60)}min, Sir 之前拒过) [5min throttle]"
                                )
                            else:
                                if nudge_type in ("late_night", "suggest_break"):
                                    self._track_sleep_nudge_dispatch(nudge_type)
                                self._dispatch_nudge(nudge_type, nudge_context)
                                self.last_nudge_time[nudge_type] = now
                                self._type_counts[nudge_type] = type_count + 1
                                self.daily_nudge_count += 1

            except Exception:
                pass
            time.sleep(5)

    def _select_best_nudge(self, candidates, work_duration, work_category, current_hour):
        if len(candidates) == 1:
            return candidates[0]

        try:
            from jarvis_utils import get_quick_classifier
            classifier = get_quick_classifier()
            if classifier.is_available:
                types_list = [c[0] for c in candidates]
                types_str = ", ".join(types_list)
                prompt = f"""User is working. Select the BEST nudge type from: {types_str}

Context: work_duration={int(work_duration)}min, category={work_category}, hour={current_hour}

Nudge types explained:
- hydration: remind to drink water
- stretch: remind to stretch/stand up
- late_night: warn about working too late
- atmosphere: comment on media/audio playing
- screen_tease: tease about what's on screen
- afternoon: afternoon energy check
- flow_end: acknowledge finishing a coding session
- dormant_project: remind about forgotten projects

Answer ONLY the nudge type name, nothing else."""

                import urllib.request
                import json as _json
                payload = _json.dumps({
                    "model": classifier._active_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 10},
                }).encode("utf-8")

                req = urllib.request.Request(
                    f"{classifier.BASE_URL}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    result = _json.loads(resp.read().decode())
                    raw = result.get("message", {}).get("content", "").strip().lower()

                for c_type, c_ctx in candidates:
                    if c_type in raw:
                        print(f"[SmartNudgeSentinel] 已选择提醒: {c_type} (候选: {types_str})")
                        return (c_type, c_ctx)
        except Exception:
            pass

        return candidates[0]

    def _calc_sleep_nudge_cooldown(self, nudge_type: str, base_cooldown: float) -> float:
        now = time.time()
        self._sleep_nudge_history = [h for h in self._sleep_nudge_history if now - h['time'] < 14400]

        if not self._sleep_nudge_history:
            self._sleep_nudge_escalation_level = 0
            return base_cooldown

        unanswered = [h for h in self._sleep_nudge_history if not h.get('answered', False)]
        escalation = len(unanswered)

        if escalation == 0:
            self._sleep_nudge_escalation_level = 0
            return base_cooldown

        self._sleep_nudge_escalation_level = min(escalation, 4)

        escalation_multipliers = {
            1: 1.5,
            2: 2.5,
            3: 4.0,
            4: 6.0,
        }
        multiplier = escalation_multipliers.get(escalation, 6.0)
        return base_cooldown * multiplier

    def _track_sleep_nudge_dispatch(self, nudge_type: str):
        now = time.time()
        was_answered = self._check_sleep_nudge_answered()
        self._sleep_nudge_history.append({
            'time': now,
            'type': nudge_type,
            'answered': was_answered,
        })
        self._last_sleep_nudge_time = now
        if len(self._sleep_nudge_history) > 20:
            self._sleep_nudge_history = self._sleep_nudge_history[-20:]

        unanswered = [h for h in self._sleep_nudge_history if not h.get('answered', False)]
        self._unanswered_sleep_nudges = len(unanswered)

    def _check_sleep_nudge_answered(self) -> bool:
        if not self._sleep_nudge_history:
            return True
        last = self._sleep_nudge_history[-1]
        if last.get('answered', False):
            return True
        try:
            if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread:
                vt = self.worker.voice_thread
                if vt.last_interaction_time > last['time']:
                    for h in self._sleep_nudge_history:
                        if not h.get('answered', False) and vt.last_interaction_time > h['time']:
                            h['answered'] = True
                    return True
        except:
            pass
        return False

    def _dispatch_nudge(self, nudge_type, context):
        # [v5.1 / Sir-2026-05-15] Sleep Intent 抑制：Sir 已表态 X 分钟后睡 → 静默 sleep 类 nudge
        # 与 Conductor._execute_path_b 同源逻辑，覆盖 SmartNudge 路径
        _SLEEP_RELATED_NUDGES = {'late_night', 'suggest_break', 'bedtime'}
        if nudge_type in _SLEEP_RELATED_NUDGES:
            spi = getattr(self.worker, '_sleep_intent_until', 0.0)
            if time.time() < spi:
                try:
                    from jarvis_utils import bg_log
                    remaining = int(spi - time.time())
                    bg_log(f"💤 [SmartNudge/SleepIntent] Sir 已表态睡眠意图，静默 {nudge_type}（剩 {remaining}s）")
                except Exception:
                    pass
                return

        if nudge_type in ("atmosphere", "screen_tease"):
            window_title = context.get("window_title", "")
            topic_key = self.humor_memory.extract_topic_key(window_title, nudge_type)
            if not self.humor_memory.can_joke_now(topic_key):
                return
            if self.humor_memory.should_skip_topic(topic_key):
                return
            context["humor_freshness"] = self.humor_memory.get_topic_freshness(topic_key)
            context["topic_key"] = topic_key
            context["topic_weight"] = self.humor_memory.get_topic_weight(topic_key)
        context["type"] = nudge_type
        context["recent_topics"] = list(self.recent_nudge_topics[-5:])

        if nudge_type in ("late_night", "suggest_break"):
            context["sleep_escalation"] = self._sleep_nudge_escalation_level
            context["unanswered_count"] = self._unanswered_sleep_nudges

        # [P0+10 / 2026-05-15] 拒绝期通用化：之前只挡 offer_help —— 实际 Sir 说"不需要"
        # 之后，late_night / suggest_break / check_in / atmosphere 等任何 nudge 都不该再蹦出来；
        # 只豁免 return_greeting（AFK 真归来一句问候算独立信号）。这样 SmartNudge 与
        # Conductor._dispatch_path_a / _execute_path_b 行为一致（同源拒绝期判定）。
        if nudge_type != 'return_greeting' and time.time() < self._refused_help_until:
            try:
                from jarvis_utils import bg_log as _ref_bg_log
                _remaining = int(self._refused_help_until - time.time())
                _ref_bg_log(f"🚫 [SmartNudge/RefusalRespect] 用户拒绝期内，跳过 {nudge_type}（剩 {_remaining}s）")
            except Exception:
                pass
            return

        # [P0+18-f.3 / 2026-05-15] 按 nudge_type 长期 mute（响应 Sir "不用再提"）
        # _refused_help_until 是全局 5-30min 冷却,_muted_nudge_types 是 type-specific
        # 12-24h mute,两者叠加形成"短期全静音 + 长期特定静音"。
        # return_greeting 永远豁免（AFK 归来问候是独立信号）。
        if nudge_type != 'return_greeting':
            _mute_until = self._muted_nudge_types.get(nudge_type, 0.0)
            if _mute_until > time.time():
                try:
                    from jarvis_utils import bg_log as _mute_bg_log
                    _hours_left = (_mute_until - time.time()) / 3600.0
                    _mute_bg_log(f"🔇 [SmartNudge/TypeMuted] {nudge_type} long-term mute "
                                 f"(剩 {_hours_left:.1f}h, Sir 之前说过不用再提)")
                except Exception:
                    pass
                return

        if nudge_type == "offer_help":
            fingerprint = self._gen_help_fingerprint(context)
            dynamic_cooldown = self._calc_help_cooldown(fingerprint)
            if dynamic_cooldown > 0:
                remaining = dynamic_cooldown - (time.time() - self._last_help_fingerprint_time)
                if remaining > 0:
                    print(f"⏳ [Help Cooldown] 动态冷却中 ({remaining:.0f}s剩余), fingerprint={fingerprint[:40]}...")
                    return
            self._last_help_fingerprint = fingerprint
            self._last_help_fingerprint_time = time.time()

        if self.gate and not self.gate.can_speak('companion', nudge_type=nudge_type):
            return

        # [R7-α/NudgeChannel] 决定走哪条通道：voice / silent_text / visual_pulse
        # SmartNudge 调用方可以显式 context['channel_override']，否则按默认映射
        try:
            from jarvis_utils import resolve_nudge_channel
            context['channel'] = resolve_nudge_channel(
                nudge_type, override=context.get('channel_override')
            )
        except Exception:
            context['channel'] = 'voice'

        cmd = f"__NUDGE__:{json.dumps(context, ensure_ascii=False)}"
        self.worker.push_command(cmd)
        if self.gate:
            self.gate.mark_spoke('companion')
        self.recent_nudge_topics.append(nudge_type)
        if len(self.recent_nudge_topics) > 10:
            self.recent_nudge_topics.pop(0)
        # [P0+18-f.3 / 2026-05-15] 记最新 nudge_type, 拒绝时用来 mute
        self._last_nudge_type = nudge_type
        self._last_nudge_time = time.time()

        # [R6/Bus] 投递到对话事件总线 —— 让 Conductor / 主脑 / 其他中心都能"看见"
        # SmartNudge 刚发了什么，避免主脑下一轮 prompt 不知道刚刚有过 offer_help。
        # [P0+20-β.2.4 hotfix / 2026-05-16] 同款 worker.jarvis.X 伪失效守卫修复
        try:
            from jarvis_utils import resolve_worker_attr
            bus = resolve_worker_attr(self.worker, 'event_bus')
            if bus is not None:
                _summary = f"{nudge_type}"
                # 让 LLM 看得见 nudge 类型 + 简短的窗口/类别上下文
                _meta_parts = []
                for k in ('window_title', 'category', 'work_duration'):
                    if context.get(k):
                        _meta_parts.append(f"{k}={str(context[k])[:40]}")
                if _meta_parts:
                    _summary += " | " + " ".join(_meta_parts)
                bus.publish(
                    etype='proactive_nudge',
                    description=_summary,
                    source='smart_nudge',
                    metadata={'nudge_type': nudge_type},
                )
        except Exception:
            pass

        try:
            if hasattr(self.worker, 'causal_chain'):
                cc = self.worker.causal_chain
                if nudge_type == "late_night":
                    cc.record("late_night", f"Late night coding at {int(time.strftime('%H'))}:00")
                elif nudge_type == "flow_end" and context.get('prev_duration', 0) > 120:
                    cc.record("long_coding_session", f"Extended coding: {context.get('prev_duration', 0)}min")
                elif nudge_type == "screen_tease" and context.get('category') == 'entertainment':
                    cc.record("media_binge", f"Media consumption: {context.get('window_title', '')[:50]}")
        except:
            pass

    def _gen_help_fingerprint(self, context: dict) -> str:
        parts = []
        window_title = context.get('window_title', '')
        if window_title:
            import re
            cleaned = re.sub(r'[^a-zA-Z0-9]', '', window_title.lower())[:30]
            if cleaned:
                parts.append(cleaned)
        category = context.get('category', '')
        if category:
            parts.append(category)
        try:
            snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
            if snapshot:
                if snapshot.get('error_visible'):
                    parts.append('err_visible')
                br = snapshot.get('backspace_ratio', 0)
                if br > 0.15:
                    parts.append('hi_bs')
                elif br > 0.08:
                    parts.append('mid_bs')
        except:
            pass
        work_cat = PhysicalEnvironmentProbe.current_work_category
        if work_cat:
            parts.append(work_cat.lower())
        return '|'.join(parts) if parts else 'generic'

    def _calc_help_cooldown(self, fingerprint: str) -> float:
        now = time.time()
        self._help_refusal_history = [h for h in self._help_refusal_history if now - h['time'] < 7200]
        matches = [h for h in self._help_refusal_history if h['fingerprint'] == fingerprint]
        if not matches:
            if fingerprint == self._last_help_fingerprint:
                return 300.0
            return 0.0
        latest = max(matches, key=lambda h: h['time'])
        refusal_count = latest.get('count', 1)
        base_cooldowns = [300, 900, 1800, 3600, 7200]
        idx = min(refusal_count, len(base_cooldowns) - 1)
        cooldown = base_cooldowns[idx]
        try:
            snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
            if snapshot:
                br = snapshot.get('backspace_ratio', 0)
                if br > 0.15:
                    cooldown = max(60, cooldown * 0.6)
                switches = snapshot.get('switch_frequency_5min', 0)
                if switches > 10:
                    cooldown = max(60, cooldown * 0.7)
        except:
            pass
        current_hour = int(time.strftime('%H'))
        if 22 <= current_hour or current_hour < 6:
            cooldown = max(120, cooldown * 1.3)
        elapsed = now - latest['time']
        remaining = cooldown - elapsed
        return max(0.0, remaining)

# ==========================================
# 🎨 [P0+19-1 / 2026-05-16] _box_newline / 结构化标签 / 中文检测已拆到 jarvis_safety.py
# ==========================================
# 原内容（_box_newline / _STRUCTURAL_TAGS / _STRUCTURAL_TAG_BLOCK_RE / _STRUCTURAL_TAG_ANY_RE /
# _strip_structural_tag_blocks / _strip_structural_tags_only / _is_forming_structural_tag /
# _CHINESE_CHAR_RE / _sentence_is_chinese_lean）+ 完整历史 marker (P0+18-c.1 / P0+18-e.2 / P0+18-e.4)
# 已搬到 `jarvis_safety.py`。本处转发垫层保证：
# - `from jarvis_nerve import _is_forming_structural_tag` 等旧 import 0 改动
# - 后续 nerve 内部直接调用 0 改动
from jarvis_safety import (
    _box_newline,
    _STRUCTURAL_TAGS,
    _STRUCTURAL_TAG_BLOCK_RE,
    _STRUCTURAL_TAG_ANY_RE,
    _strip_structural_tag_blocks,
    _strip_structural_tags_only,
    _is_forming_structural_tag,
    _CHINESE_CHAR_RE,
    _sentence_is_chinese_lean,
)


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

