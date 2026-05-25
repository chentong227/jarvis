# -*- coding: utf-8 -*-
"""[P0+19-6.c / 2026-05-16] 回归哨兵 ReturnSentinel — 动态唤醒回应 + AFK 归来主动问候 + 软焦点验证

从 jarvis_nerve.py 拆出 1 个大类（>500 行）。
向后兼容：jarvis_nerve.py 用 `from jarvis_return_sentinel import ReturnSentinel` 转发，
旧 `from jarvis_nerve import ReturnSentinel` 0 改动。
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

# 🩹 [P0+20-β.1.7 / 2026-05-16] P0+19-6.c 拆分留尾：win32api 没 import →
# line 146 / 530 NameError → 外层 try/except 静默吞 → idle_ms 永 0 → was_afk 永 False
# → 永远不触发 _on_return → "归来感知" 完全失效。Sir 14:30 实测 1+ 小时回归未问候即此因。
# import 失败时显式赋 None，line 146 检测 None 直接走 "无 idle 信号" 兜底（防御纵深）
try:
    import win32api  # noqa: F401
    import win32gui  # noqa: F401
    import win32con  # noqa: F401
    _WIN32_OK = True
except Exception:
    win32api = None  # type: ignore
    win32gui = None  # type: ignore
    win32con = None  # type: ignore
    _WIN32_OK = False

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




class ReturnSentinel(threading.Thread):
    """本地快速路径：动态唤醒回应 + AFK归来主动问候 + 软焦点验证"""
    def __init__(self, jarvis_worker, nudge_gate=None):
        super().__init__(daemon=True)
        self.worker = jarvis_worker
        self.gate = nudge_gate
        self.last_active_time = time.time()
        # [P0+9 / 2026-05-15] 旧版初值 0.0 在某些边界条件下会让 afk_duration 变成 epoch 巨量秒，
        # 错误通过 300s 阈值；改为 time.time() 让首启边界状态合理。
        self.last_afk_start = time.time()
        self.was_afk = False
        self.first_active_today = True
        self.last_active_day = ""
        self.soft_focus_until = 0.0
        self.soft_focus_active = False
        self._last_greeting_time = 0.0
        self._greeting_cooldown = 120
        self._pending_greeting = None
        self._glow_start_time = 0.0
        self._greeting_phase = "idle"

        # [P0+9 / 2026-05-15] Sir 实测 8:03 巧合触发"早晨问候"但实际未出声 + 8:44 才真起床。
        # 根因链：
        #   1) Jarvis 启动时 first_active_today=True；
        #   2) 启动后第一次 idle_ms 跳到 < 30000 时（系统进程/屏保/Jarvis 自家进程产生输入事件），
        #      was_afk True→False 即触发 _on_return；
        #   3) 推 __NUDGE__ 进 cmd_queue 后，因 LLM 失败/网络/海马体阻塞被静默吞，没出声但 STM 留痕。
        # 三层修法：
        #   A. _startup_guard_until: 启动后 5min 内不允许 first_active_today 触发问候
        #   B. _active_streak_seconds: idle hysteresis —— 连续 5s 输入才算真回归（防抖）
        #   C. _on_return + __NUDGE__ 失败均加 bg_log，让 Sir 看到"为啥触发/为啥没出声"
        self._startup_guard_until = time.time() + 300.0
        self._active_streak_seconds = 0  # 距上次输入活动连续秒数
        self._last_idle_ms_seen = 0      # 上一轮的 idle_ms，用于差分

    def run(self):
        time.sleep(20)
        # 🩹 [P0+20-β.1.7 / 2026-05-16] 启动自检：让 Sir 一眼看到 idle detect 在工作
        try:
            from jarvis_utils import bg_log as _rs_bg
            if _WIN32_OK and win32api is not None:
                _probe_idle = win32api.GetTickCount() - win32api.GetLastInputInfo()
                _rs_bg(f"[ReturnSentinel/Health] win32api OK, idle_probe={_probe_idle}ms")
            else:
                _rs_bg("⚠️ [ReturnSentinel/Health] win32api 不可用，归来感知将走兜底（无 idle 信号）")
        except Exception:
            pass
        print("[ReturnSentinel] 回归检测 + 动态唤醒引擎就绪...")
        _diag_last_log = 0.0  # 5min 一次诊断日志
        while True:
            try:
                idle_ms = 0
                if win32api is not None:
                    try:
                        idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                    except Exception:
                        pass

                # 5min 一次诊断日志（让 Sir 能 grep 看 idle 真值变化曲线）
                _now_t = time.time()
                if _now_t - _diag_last_log > 300.0:
                    _diag_last_log = _now_t
                    try:
                        from jarvis_utils import bg_log as _diag_bg
                        _diag_bg(
                            f"[ReturnSentinel/Diag] idle_ms={idle_ms} was_afk={self.was_afk} "
                            f"streak={self._active_streak_seconds}s first_today={self.first_active_today}"
                        )
                    except Exception:
                        pass

                current_day = time.strftime("%Y-%m-%d")
                if current_day != self.last_active_day:
                    self.first_active_today = True
                    self.last_active_day = current_day

                # [P0+9 / 2026-05-15] hysteresis：进入 AFK 阈值 30s（保持原值）；
                # 退出 AFK 必须连续 5s 内 idle_ms < 5000（即至少 5s 内没出现 5s+ 的静默期）
                # 防止单次系统进程/屏保事件的瞬时输入误判为"用户回归"。
                is_afk_now_raw = (idle_ms > 30000)
                if idle_ms < 5000:
                    self._active_streak_seconds += 1
                else:
                    self._active_streak_seconds = 0

                # AFK 中：只有连续 ≥5s 真活动才算回归；其它情况视为仍 AFK
                if self.was_afk:
                    is_afk_now = not (self._active_streak_seconds >= 5)
                else:
                    is_afk_now = is_afk_now_raw

                if self.was_afk and not is_afk_now:
                    afk_duration = time.time() - self.last_afk_start
                    self.last_active_time = time.time()
                    self._on_return(afk_duration)

                if is_afk_now and not self.was_afk:
                    self.last_afk_start = time.time()

                self.was_afk = is_afk_now

                if self.soft_focus_active and time.time() > self.soft_focus_until:
                    self.soft_focus_active = False

                if self._greeting_phase == "glow":
                    if time.time() - self._glow_start_time >= 5.0:
                        self._greeting_phase = "speaking"
                        en_text, zh_text = self._pending_greeting
                        self._pending_greeting = None
                        self._speak_and_soft_focus(en_text, zh_text)
                        self._greeting_phase = "idle"

            except Exception:
                pass
            time.sleep(1)

    def _on_return(self, afk_duration):
        # 🩹 [β.2.9.6 / 2026-05-18] expose 给 AfterAfk predicate 用 (CommitmentWatcher
        # _build_predicate_ctx 读 self._last_afk_minutes).
        try:
            self._last_afk_minutes = float(afk_duration / 60)
        except Exception:
            self._last_afk_minutes = 0
        # [P0+9 / 2026-05-15] 全链路 bg_log：每个 return 分支都打日志，让 Sir 实测时
        # 一眼看出"为什么 ReturnSentinel 触发了 / 为什么被挡了"。
        try:
            from jarvis_utils import bg_log as _ret_bg_log
        except Exception:
            _ret_bg_log = None

        def _log(msg):
            if _ret_bg_log:
                try:
                    _ret_bg_log(msg)
                except Exception:
                    pass

        afk_min = int(afk_duration / 60)
        _log(f"📞 [ReturnSentinel] _on_return: afk={afk_min}min (raw={int(afk_duration)}s), first_today={self.first_active_today}")

        # [β.5.0-A / 2026-05-19] 准则 6 数据强耦合: AFK 回归原始信号 publish 到 SWM
        # 即使本次 _on_return 被各种 gate 拦 (cooldown / startup_guard / media_window / ...)
        # 不发 nudge, 主脑仍能在 next prompt 看到 "Sir 刚回来过, AFK X min, first_today=Y".
        try:
            from jarvis_utils import get_event_bus
            _swm = get_event_bus()
            if _swm is not None:
                _swm.publish(
                    etype='afk_return',
                    description=f"Sir returned: AFK {afk_min}min, first_today={self.first_active_today}",
                    source='ReturnSentinel',
                    metadata={
                        'afk_minutes': afk_min,
                        'afk_seconds': int(afk_duration),
                        'first_today': bool(self.first_active_today),
                        'crosses_sleep': bool(afk_duration > 14400),
                    },
                    # AFK > 4h (跨夜) salience 高, 短 AFK 较低
                    salience=0.75 if afk_duration > 14400 else 0.45,
                )
        except Exception:
            pass

        # [β.5.5 / 2026-05-19] skip 时统一 publish 'gate_advice' source='ReturnSentinel'
        # 让主脑下次能看到 "ReturnSentinel wanted greet but blocked: reason=X".
        # helper 内含 dedupe (避免循环 publish 风暴, 同 reason 60s 1 次).
        def _publish_skip(skip_reason: str, extra_meta: dict = None):
            try:
                from jarvis_utils import get_event_bus
                _bus = get_event_bus()
                if _bus is None:
                    return
                meta = {
                    'decision': 'block',
                    'block_reason': skip_reason,
                    'afk_minutes': afk_min,
                    'first_today': bool(self.first_active_today),
                }
                if extra_meta:
                    meta.update(extra_meta)
                _bus.publish(
                    etype='gate_advice',
                    description=f"ReturnSentinel wanted greet but blocked: {skip_reason}",
                    source='ReturnSentinel',
                    metadata=meta,
                    # [β.5.8-fix] 同 SmartNudge: skip 信号 sal=0.25 不进默认 SWM render.
                    # 真正 Sir 起床 (afk_return raw) sal=0.75+ 仍优先注入.
                    salience=0.25,
                )
            except Exception:
                pass

        if time.time() - self._last_greeting_time < self._greeting_cooldown:
            remaining = int(self._greeting_cooldown - (time.time() - self._last_greeting_time))
            _log(f"📞 [ReturnSentinel/Skip] greeting cooldown 未过（剩 {remaining}s）")
            _publish_skip(f'greeting_cooldown_{remaining}s_remaining',
                          {'cooldown_remaining_s': remaining})
            return
        if afk_duration < 300:
            _log(f"📞 [ReturnSentinel/Skip] afk_duration < 300s，太短不算真回归")
            _publish_skip(f'afk_too_short_{int(afk_duration)}s',
                          {'afk_seconds': int(afk_duration)})
            return

        # [P0+9 / 2026-05-15] 启动护栏：启动 5min 内的 first_active_today 触发被挡
        # 解决 Sir 实测 8:03 那次"巧合 was_afk 切换 + first_active_today 还是 True"误触发
        if self.first_active_today and time.time() < self._startup_guard_until:
            remaining = int(self._startup_guard_until - time.time())
            _log(f"🛡️ [ReturnSentinel/StartupGuard] 启动后 {300 - remaining}s（< 5min），跳过 first_active_today 首次问候")
            _publish_skip(f'startup_guard_{remaining}s_remaining',
                          {'startup_guard_remaining_s': remaining})
            # 不消耗 first_active_today —— 等真正稳定的 AFK 周期再触发
            return

        if self.gate and self.gate.is_sleep_mode():
            # 🩹 [β.2.9.1.3] ReturnSentinel = Sir AFK >5min 回来, 算真醒 force=True
            # 🩹 [β.5.22-E / 2026-05-19] Sir 01:24 实测痛点: "退出睡眠很久了, Jarvis 没主动问怎么没睡".
            # Root cause: 老路径 ReturnSentinel.deactivate_sleep_mode 直接解除, 没调 _check_short_sleep
            # → 短睡 (e.g. <300s) 询问逻辑只走 CentralNerve._detect_wake_up 路径 (语音唤醒).
            # 修法: ReturnSentinel 解除 sleep_mode 时也调 nerve._check_short_sleep, 让 AFK 回来
            # 也能触发短睡询问 (Sir 真睡过 + 真起 不会触发, 假睡 < 5min 才触发).
            _sleep_dur_for_check = 0.0
            try:
                _sleep_dur_for_check = float(self.gate.sleep_duration_seconds() or 0.0)
            except Exception:
                pass
            self.gate.deactivate_sleep_mode(force=True)
            print(f"[ReturnSentinel] 用户回归，自动解除休眠模式 (AFK {afk_duration/60:.0f}分钟)")
            # β.5.22-E: 短睡询问 hook
            try:
                _nerve = getattr(self.worker, 'jarvis', None)
                if _nerve is not None and hasattr(_nerve, '_check_short_sleep') \
                        and _sleep_dur_for_check > 0:
                    _nerve._check_short_sleep(_sleep_dur_for_check)
            except Exception:
                pass

        if hasattr(self.worker, 'voice_thread'):
            vt = self.worker.voice_thread
            if vt.in_active_conversation:
                _log(f"📞 [ReturnSentinel/Skip] 当前在 active_conversation 中，让对话自然继续")
                _publish_skip('in_active_conversation')
                return
            if vt.last_conversation_end_time > 0 and (time.time() - vt.last_conversation_end_time) < 120:
                gap = int(time.time() - vt.last_conversation_end_time)
                # 🆕 [Sir 2026-05-25 13:32 真测追根 BUG 治本] reminder fire 豁免
                # =====================================================================
                # 源 BUG: 闹钟 13:30 fire 走 chat_bypass.stream_chat → vt.last_conversation
                # _end_time 被设. ReturnSentinel _on_return (Sir 真敲键鼠) 看到
                # "距上轮对话 < 120s" → skip morning greeting. 但闹钟不是 Sir 主动对话!
                # 治本: 看 SWM 近 conv_end_age_s + 30s 内是否有 reminder_fired event
                # → 是 = 上轮 conv 被闹钟占, 豁免 skip 仍 greet.
                # =====================================================================
                _is_reminder_occupied = False
                try:
                    from jarvis_utils import get_event_bus as _geb_rs
                    _bus_rs = _geb_rs()
                    if _bus_rs is not None:
                        _recent_reminders = _bus_rs.recent_events(
                            within_seconds=float(gap + 30),
                            types={'reminder_fired'},
                        )
                        # 任何 reminder_fired 在 conv_end 前后 ±15s 窗口 → 是闹钟占用
                        _conv_end_ts = vt.last_conversation_end_time
                        for _ev in _recent_reminders:
                            _ev_ts = float(_ev.get('ts', 0) or 0)
                            if abs(_ev_ts - _conv_end_ts) < 15.0:
                                _is_reminder_occupied = True
                                break
                except Exception:
                    pass
                if _is_reminder_occupied:
                    _log(f"📞 [ReturnSentinel/Bypass] 上轮 conv 是闹钟 fire 占用 (非 Sir 主动对话), "
                         f"豁免 < 120s skip, 继续 morning greeting")
                else:
                    _log(f"📞 [ReturnSentinel/Skip] 距上轮对话结束 < 120s，避免立刻再问候")
                    _publish_skip(f'last_conv_end_{gap}s_ago',
                                  {'last_conv_end_age_s': gap})
                    return

        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            fg_title = win32gui.GetWindowText(hwnd).lower() if hwnd else ""
        except:
            fg_title = ""
        media_keywords = ["bilibili", "youtube", "iqiyi", "爱奇艺", "netflix", "prime", "hulu",
                          "twitch", "douyin", "抖音", "tiktok", "vimeo", "dailymotion",
                          "qqmusic", "网易云", "spotify", "player", "video", "播放",
                          "movie", "film", "tv", "anime", "动漫", "综艺", "剧",
                          "potplayer", "vlc", "mpv", "kmplayer", "暴风", "迅雷"]
        if any(kw in fg_title for kw in media_keywords):
            # 🆕 [Sir 2026-05-25 18:04 真测追根 BUG 治本] 残留窗口 ≠ Sir 在看
            # =====================================================================
            # 源 BUG: Sir 出门 262min AFK, 前台 bilibili 视频残留 (Sir 走前没关).
            # ReturnSentinel 看到媒体窗口 → skip greeting. 但 Sir 不在看视频!
            # 残留窗口仅在**短 AFK** (Sir 真在看) 才该 skip. 长 AFK 必是出门.
            # 治本: AFK >= 30min → 媒体窗口豁免 (残留). < 30min 才信任窗口.
            # 准则 6 evidence-driven: AFK 时长 = 真证据, 残留窗口不是.
            # =====================================================================
            if afk_duration >= 1800:  # 30min+ AFK = 出门, 残留窗口不可信
                _log(f"📞 [ReturnSentinel/Bypass] 前台是媒体窗口（{fg_title[:40]}）"
                     f"但 AFK {int(afk_duration/60)}min 太长 = 残留, 仍 greet")
            else:
                _log(f"📞 [ReturnSentinel/Skip] 前台是媒体窗口（{fg_title[:40]}），不打扰")
                _publish_skip('media_window_foreground',
                              {'fg_title_prefix': fg_title[:40],
                               'afk_minutes': int(afk_duration/60)})
                return

        current_hour = int(time.strftime("%H"))
        work_category = PhysicalEnvironmentProbe.current_work_category
        weekday = time.strftime("%A")

        snap = self._snap_context(afk_duration)
        self._trim_stale_stm()

        should_greet = False
        use_llm = False
        is_first_today = False

        if self.first_active_today:
            should_greet = True
            is_first_today = True
            # [v4] Sir 反馈："AFK 回归问候可以动态生成吗？根据上下文、离开前的工作"
            # → 即使是当天第一次活跃，也走 LLM 让它能引用上下文（昨晚工作内容/今早时段）
            use_llm = True
        elif afk_duration > 900:  # AFK > 15 min
            should_greet = True
            # [v4] 旧逻辑只有 > 4h AFK 才走 LLM，其余用罐头模板 → 内容千篇一律
            # 改为：任何 > 15 分钟 AFK 都用 LLM，让贾维斯能引用最近 STM 里的工作内容
            use_llm = True

        if not should_greet:
            _log(f"📞 [ReturnSentinel/Skip] should_greet=False（hour={current_hour}, afk_min={afk_min}）")
            return

        if use_llm:
            try:
                if hasattr(self.worker, 'voice_thread'):
                    self.worker.voice_thread.awake_signal.emit(True)
            except:
                pass
            # [β.4.12 / 2026-05-19] Sir 09:59 实测 BUG: 起床后 Jarvis 直接说 "10 点了, Integrity
            # Stack 等您" 像 Sir 没睡觉. 根因: nudge_ctx 没传 is_first_today / 跨夜信号给主脑,
            # LLM 看到 STM 昨晚 Integrity Stack → 自然引述工作话题. 修法 (准则 6 evidence-only):
            # 注入 3 个 evidence 字段, 主脑 prompt 看到能涌现 morning tone, 不教句式.
            crosses_sleep = afk_duration > 14400  # > 4h AFK 大概率跨夜睡觉
            current_hour_for_ctx = int(time.strftime("%H"))
            is_morning_window = 5 <= current_hour_for_ctx < 12
            # 🩹 [P5-SirStatusTracker / 2026-05-21 15:25] Sir 13:49 痛点 — context aware
            # Sir 12:06 说"睡觉了下午见" → tracker 已 capture status='sleep'.
            # 13:49 回 → 这里读 status, 主脑收到 declared_status 信号自然出 sleep return 话术.
            sir_declared_status = ''
            sir_status_keyword = ''
            sir_status_age_min = 0
            try:
                from jarvis_sir_status_tracker import current_status as _sst_cur
                _cur = _sst_cur()
                if _cur.get('status') not in ('unknown', 'active'):
                    sir_declared_status = _cur.get('status', '')
                    sir_status_keyword = _cur.get('last_keyword', '')
                    sir_status_age_min = int(_cur.get('age_s', 0) / 60)
            except Exception:
                pass
            nudge_ctx = {
                "type": "return_greeting",
                "afk_minutes": snap["afk_minutes"],
                "work_category": work_category,
                "weekday": weekday,
                "work_hint": snap["work_hint"],
                "pattern_hint": snap["pattern_hint"],
                "time_hint": snap["time_hint"],
                # [β.4.12] 早起 first greeting 信号 (主脑用来涌现 morning tone)
                "is_first_today": is_first_today,
                "crosses_sleep_period": crosses_sleep,
                "is_morning_window": is_morning_window,
                # 🩹 [P5-SirStatusTracker / 2026-05-21 15:25] Sir 声明状态 (sleep/nap/lunch/out/dnd)
                "sir_declared_status": sir_declared_status,  # '' 或 sleep/nap/lunch/out/...
                "sir_status_keyword": sir_status_keyword,    # Sir 原话片段
                "sir_status_age_min": sir_status_age_min,    # 声明状态距今分钟
                # [P0+9 / 2026-05-15] 新增 source 标记，让 _dispatch_nudge 终端 tag 显示 [ReturnSentinel]
                "via_return_sentinel": True,
                "source": "ReturnSentinel",
            }
            if self.gate and not self.gate.can_speak('guardian', nudge_type='return_greeting'):
                _log(f"📞 [ReturnSentinel/Blocked] NudgeGate.can_speak 拒绝 (hard_freeze 或冲突)，未发出问候")
                return

            # 🩹 [P3-BUG#4 / 2026-05-20 23:42] publish candidate (β.5.0 三维耦合)
            # vocab gate_mode='publish_only' 已 set, 但行为没真退化. 加 publish candidate
            # 让 ProactiveCare/主脑下轮看到. JARVIS_RETURN_SENTINEL_RETIRE=1 时**真**退化
            # (不 push __NUDGE__ 走主对话, 完全交 ProactiveCare 集中决策).
            try:
                from jarvis_utils import get_event_bus as _rs_geb
                _rs_bus = _rs_geb()
                if _rs_bus is not None:
                    _rs_bus.publish(
                        etype='sir_intent_return_greeting_candidate',
                        description=(
                            f"Sir AFK return: {afk_min}min, first_today={self.first_active_today}, "
                            f"hour={current_hour}. ReturnSentinel suggests greeting."
                        ),
                        source='ReturnSentinel',
                        salience=0.70,
                        metadata={
                            'confidence': 0.75,
                            'afk_minutes': afk_min,
                            'first_today': bool(self.first_active_today),
                            'work_category': work_category,
                            'weekday': weekday,
                            'is_first_today': is_first_today,
                            'current_hour': current_hour,
                            'nudge_ctx': nudge_ctx,
                        },
                    )
            except Exception:
                pass

            # 🩹 [P3-BUG#4] explicit env flag 真退化 (Sir 拍板才用)
            try:
                import os as _os_p3
                if _os_p3.environ.get('JARVIS_RETURN_SENTINEL_RETIRE') == '1':
                    _log(f"📞 [ReturnSentinel/RETIRED] env JARVIS_RETURN_SENTINEL_RETIRE=1, candidate published, NOT firing nudge")
                    self.first_active_today = False  # 仍 consume first_today
                    return
            except Exception:
                pass

            cmd = f"__NUDGE__:{json.dumps(nudge_ctx, ensure_ascii=False)}"
            self.worker.push_command(cmd)
            if self.gate:
                self.gate.mark_spoke('guardian')
            self._last_greeting_time = time.time()
            # [P0+9 / 2026-05-15] LLM 路径成功推送也要置 first_active_today=False
            # 之前只有罐头模板路径置 False（line 4313 之前），LLM 路径漏掉 →
            # 同一天可能反复触发 first_active_today（如果上次 push 因下游异常没出声）
            self.first_active_today = False

            # 🩹 [P5-fixC / 2026-05-21 09:45] β.5.0 行为弱耦合 — publish proactive_nudge_fired
            # 让 SmartNudge.commitment_check + Conductor.path_b offer_help 等其他 sentinel
            # 看到本 morning greeting 已 fire, 自决退化 publish-only (不连发抢话筒).
            # Sir 09:05/06/12 真测痛点: 3 个 sentinel 7 min 内连发 — 没人协调.
            # 此 publish 不是硬 cooldown 数字, 是 evidence: 别的 sentinel 看 evidence 自决.
            try:
                from jarvis_nudge_coordination import publish_proactive_nudge_fired as _pn_pub
                _pn_pub(
                    kind='return_greeting',
                    sentinel='ReturnSentinel',
                    extra_metadata={'afk_minutes': afk_min, 'hour': current_hour},
                )
            except Exception:
                pass

            _log(f"📞 [ReturnSentinel/Sent] return_greeting NUDGE 已推 (afk={afk_min}min, hour={current_hour}, first_today_in_ctx={is_first_today})")
            return

        # 🩹 [β.2.9.10 / 2026-05-18] Sir 11:54 反馈 "还是这个固定句式".
        # 模板兜底路径 (use_llm=False) 已死代码 — should_greet 时永远 use_llm=True.
        # 删兜底防回退. 模板池 _pick_return_greeting / _pick_smart_greeting 整套
        # (~280 行) 也跟着删, 仅 docs/TODO_ARCHIVE.md 提及历史. 净化 + 防回退诱惑.
        # 这里走到说明上面 use_llm 路径未 return → 异常路径, 直接 log + 退.
        _log(f"⚠️ [ReturnSentinel] should_greet=True 但 use_llm=False — 异常状态, 跳过")
        return

    def open_soft_focus(self, duration_s: float = 60.0,
                          reason: str = 'external') -> None:
        """🩹 [β.2.9.9 / 2026-05-18] 通用 API: 任何主动发声后开 soft focus window.

        Sir 10:43 痛点: ProactiveCare 主动 nudge 后没焦点模式, Sir 想口头回应
        "我中午会补觉" 还要先说 "Jarvis" 唤醒. 复用 soft_focus 机制 (原本只
        AFK 归来用), 让任何主动发声路径都能借这条 X 秒短焦点窗口.

        Args:
          duration_s: focus 持续时间秒, 默认 60s
          reason: 'proactive_care' / 'inconsistency' / 'commitment_check' 等
        """
        self.soft_focus_active = True
        self.soft_focus_until = time.time() + max(15.0, min(180.0, duration_s))
        self._soft_focus_reason = reason
        try:
            from jarvis_utils import bg_log as _bg
            _bg(
                f"🎯 [ReturnSentinel/SoftFocus] 开 {int(duration_s)}s focus "
                f"window (reason={reason}) — Sir 短回应不用喊 Jarvis"
            )
        except Exception:
            pass

    def _pick_return_greeting(self, afk_duration, current_hour, work_category, weekday, is_first_today=False):
        afk_min = int(afk_duration / 60)
        is_weekend = weekday in ("Saturday", "Sunday")

        greetings = []

        if is_first_today:
            if 5 <= current_hour < 12:
                if is_weekend:
                    greetings = [
                        ("Morning, Sir~ sleep well?", "早啊先生~睡得好吗？"),
                        ("Mmm... morning, Sir. Taking it slow today?", "嗯…早，先生。今天慢慢来？"),
                        ("Good morning, Sir~ ready when you are.", "早上好先生~随时待命。"),
                    ]
                else:
                    if weekday == "Monday":
                        greetings = [
                            ("Morning, Sir~ new week... fresh start, I suppose.", "早啊先生~新的一周…算是新的开始吧。"),
                            ("Monday, Sir... let's ease into it.", "周一了先生…慢慢进入状态吧。"),
                        ]
                    elif weekday == "Friday":
                        greetings = [
                            ("Morning, Sir~ Friday. Almost there.", "早啊先生~周五了，快了。"),
                        ]
                    else:
                        greetings = [
                            ("Morning, Sir~", "早啊先生~"),
                            ("Good morning, Sir~ ready when you are.", "早上好先生~随时待命。"),
                        ]
                if work_category == "Coding":
                    greetings.append(("Morning, Sir~ you were coding late last night... how are we feeling?", "早啊先生~昨晚写代码到很晚…感觉怎么样？"))
            elif 12 <= current_hour < 18:
                greetings = [
                    ("Afternoon, Sir~", "下午好先生~"),
                    ("Mmm... afternoon, Sir. Ready to continue?", "嗯…下午了，先生。继续吗？"),
                ]
            elif 18 <= current_hour < 23:
                greetings = [
                    ("Evening, Sir~", "晚上好先生~"),
                    ("Evening, Sir~ how was your day?", "晚上好先生~今天过得怎么样？"),
                ]
            else:
                time_str = time.strftime("%H:%M")
                greetings = [
                    (f"Sir... it's {time_str}... still working?", f"先生…都{time_str}了…还在忙？"),
                    ("Late night, Sir~ need anything?", "夜深了先生~需要什么吗？"),
                ]

        elif 5 <= current_hour < 12:
            if afk_duration > 14400:
                if is_weekend:
                    greetings = [
                        ("Morning, Sir~ sleep well?", "早啊先生~睡得好吗？"),
                        ("Mmm... morning, Sir. Taking it slow today?", "嗯…早，先生。今天慢慢来？"),
                        ("Good morning, Sir~ ready when you are.", "早上好先生~随时待命。"),
                    ]
                else:
                    if weekday == "Monday":
                        greetings = [
                            ("Morning, Sir~ new week... fresh start, I suppose.", "早啊先生~新的一周…算是新的开始吧。"),
                            ("Monday, Sir... let's ease into it.", "周一了先生…慢慢进入状态吧。"),
                        ]
                    elif weekday == "Friday":
                        greetings = [
                            ("Morning, Sir~ Friday. Almost there.", "早啊先生~周五了，快了。"),
                        ]
                    else:
                        greetings = [
                            ("Morning, Sir~", "早啊先生~"),
                            ("Good morning, Sir~ ready when you are.", "早上好先生~随时待命。"),
                        ]
                if work_category == "Coding":
                    greetings.append(("Morning, Sir~ you were coding late last night... how are we feeling?", "早啊先生~昨晚写代码到很晚…感觉怎么样？"))
            elif afk_min >= 30:
                if work_category == "Coding":
                    greetings = [
                        ("Welcome back, Sir~ shall we pick up where we left off?", "回来啦先生~继续刚才的？"),
                        ("Sir~ ready to continue?", "先生~继续吗？"),
                    ]
                elif work_category == "Media":
                    greetings = [
                        ("Welcome back, Sir~ good break?", "回来啦先生~休息得不错？"),
                    ]
                else:
                    greetings = [
                        ("Welcome back, Sir~", "回来啦先生~"),
                        ("Sir~ everything alright?", "先生~一切还好吗？"),
                    ]
            else:
                greetings = [
                    ("Yes, Sir~", "在呢先生~"),
                    ("Here, Sir~", "在~"),
                    ("Go ahead, Sir~", "请说先生~"),
                ]

        elif 12 <= current_hour < 18:
            if afk_min >= 120:
                if work_category == "Coding":
                    greetings = [
                        ("Sir~ you were deep in it earlier... resuming?", "先生~之前您很投入…继续吗？"),
                        ("Afternoon, Sir~ shall we get back to it?", "下午了先生~继续工作吗？"),
                    ]
                else:
                    greetings = [
                        ("Afternoon, Sir~", "下午好先生~"),
                        ("Sir~ how was your break?", "先生~休息得怎么样？"),
                    ]
            elif afk_min >= 30:
                if work_category == "Coding":
                    greetings = [
                        ("Welcome back, Sir~", "回来啦先生~"),
                        ("Sir~ picking up the thread?", "先生~接上思路了？"),
                    ]
                else:
                    greetings = [
                        ("Sir~", "先生~"),
                        ("Yes, Sir~ what can I do?", "在呢先生~有什么需要？"),
                    ]
            else:
                greetings = [
                    ("Yes, Sir~", "在呢先生~"),
                    ("Here~", "在~"),
                    ("Ready, Sir~", "就绪先生~"),
                ]

        elif 18 <= current_hour < 23:
            if afk_min >= 60:
                if work_category == "Coding":
                    greetings = [
                        ("Evening, Sir~ still at it?", "晚上了先生~还在忙？"),
                        ("Sir~ working late tonight?", "先生~今晚加班？"),
                    ]
                elif work_category == "Media":
                    greetings = [
                        ("Evening, Sir~ good dinner?", "晚上好先生~晚餐不错？"),
                        ("Welcome back, Sir~ relaxing tonight?", "回来啦先生~今晚放松一下？"),
                        ("Evening, Sir~ enjoying the stream?", "晚上好先生~直播好看吗？"),
                        ("Sir~ what are we watching tonight?", "先生~今晚在看什么？"),
                    ]
                else:
                    greetings = [
                        ("Evening, Sir~", "晚上好先生~"),
                        ("Sir~ everything in order?", "先生~一切正常吗？"),
                    ]
            elif afk_min >= 30:
                greetings = [
                    ("Sir~", "先生~"),
                    ("Yes, Sir~", "在呢先生~"),
                    ("Evening, Sir~", "晚上好先生~"),
                ]
            else:
                greetings = [
                    ("Yes, Sir~", "在呢先生~"),
                    ("Here, Sir~", "在~"),
                ]

        else:
            if afk_min >= 30:
                time_str = time.strftime("%H:%M")
                if work_category == "Coding":
                    greetings = [
                        (f"Sir... it's {time_str}... still working?", f"先生…都{time_str}了…还在忙？"),
                        (f"{time_str} already, Sir... you've been at this a while.", f"已经{time_str}了先生…您忙了很久了。"),
                        ("Late night, Sir~ need anything?", "夜深了先生~需要什么吗？"),
                        ("Quiet night, Sir~ just us.", "安静的夜晚先生~只有我们。"),
                        (f"Sir, it's {time_str}... even I'm impressed.", f"先生，都{time_str}了…连我都佩服。"),
                    ]
                else:
                    greetings = [
                        ("Sir... it's quite late.", "先生…很晚了。"),
                        ("Can't sleep, Sir~?", "睡不着吗先生~？"),
                        (f"{time_str}... you're still up, Sir.", f"{time_str}了…您还醒着，先生。"),
                    ]
            else:
                greetings = [
                    ("Still here, Sir~", "还在呢先生~"),
                    ("Sir~", "先生~"),
                    ("Yes~", "在~"),
                ]

        if not greetings:
            return None, None

        import random
        return random.choice(greetings)

    def get_dynamic_wake_response(self, cmd):
        current_hour = int(time.strftime("%H"))
        work_category = PhysicalEnvironmentProbe.current_work_category
        weekday = time.strftime("%A")
        idle_ms = 0
        try:
            idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
        except:
            pass
        afk_sec = idle_ms / 1000.0

        if afk_sec < 30:
            return None, None

        return self._pick_return_greeting(afk_sec, current_hour, work_category, weekday)

    def _snap_context(self, afk_duration: float) -> dict:
        snap = {
            "afk_minutes": int(afk_duration / 60),
            "time_hint": "",
            "work_hint": "",
            "pattern_hint": "",
        }

        hour = int(time.strftime("%H"))
        if 5 <= hour < 12:
            snap["time_hint"] = "morning"
        elif 12 <= hour < 18:
            snap["time_hint"] = "afternoon"
        elif 18 <= hour < 23:
            snap["time_hint"] = "evening"
        else:
            snap["time_hint"] = "late night"

        cat = PhysicalEnvironmentProbe.current_work_category
        dur = PhysicalEnvironmentProbe.work_duration_minutes
        proc = PhysicalEnvironmentProbe.current_process_name
        afk_min = snap["afk_minutes"]
        actual_work_min = max(0, dur - afk_min)
        if cat == "Coding" and actual_work_min > 15:
            snap["work_hint"] = f"was coding ({proc}) for {int(actual_work_min)}min before stepping away"
        elif cat == "Media" and actual_work_min > 10:
            snap["work_hint"] = f"was watching media for {int(actual_work_min)}min"
        elif cat != "AFK" and actual_work_min > 10:
            snap["work_hint"] = f"was active in {cat} for {int(actual_work_min)}min"

        if hasattr(self.worker, 'causal_chain'):
            try:
                patterns = self.worker.causal_chain.detect_patterns()
                if patterns:
                    snap["pattern_hint"] = patterns[0][:120]
            except:
                pass

        return snap

    def _trim_stale_stm(self, max_age_minutes=30):
        if not hasattr(self.worker, 'short_term_memory'):
            return
        stm = self.worker.short_term_memory
        if not stm:
            return
        cutoff = time.time() - max_age_minutes * 60
        fresh = []
        for entry in stm:
            entry_time = entry.get("time", "")
            try:
                h, m, s = entry_time.split(":")
                entry_ts = time.mktime(time.strptime(
                    f"{time.strftime('%Y-%m-%d')} {h}:{m}:{s}",
                    "%Y-%m-%d %H:%M:%S"
                ))
                if entry_ts >= cutoff:
                    fresh.append(entry)
            except:
                fresh.append(entry)
        if len(fresh) < 3:
            fresh = stm[-3:] if len(stm) >= 3 else stm
        self.worker.short_term_memory = fresh[-10:]

    def _pick_smart_greeting(self, snap, current_hour, work_category, weekday):
        afk_min = snap["afk_minutes"]
        work_hint = snap["work_hint"]
        pattern_hint = snap["pattern_hint"]

        greetings = []

        if afk_min < 30:
            if work_hint:
                greetings = [
                    (f"Back already, Sir. You {work_hint}.", f"这么快就回来了，先生。你之前{work_hint}。"),
                    ("That was quick, Sir~", "好快啊先生~"),
                ]
            else:
                greetings = [
                    ("Back already, Sir.", "回来了，先生。"),
                    ("That was quick, Sir~", "好快啊先生~"),
                ]
        elif afk_min < 120:
            if pattern_hint:
                greetings.append(
                    (f"Welcome back, Sir. {pattern_hint}.", f"欢迎回来，先生。{pattern_hint}。")
                )
            if work_hint:
                greetings.append(
                    (f"Welcome back, Sir. You {work_hint}. Shall we continue?", f"欢迎回来，先生。你之前{work_hint}。继续吗？")
                )
            greetings.append(("Welcome back, Sir~", "欢迎回来先生~"))
        else:
            if pattern_hint:
                greetings.append(
                    (f"Welcome back, Sir. {pattern_hint}.", f"欢迎回来，先生。{pattern_hint}。")
                )
            greetings.append(("Welcome back, Sir~", "欢迎回来先生~"))

        if not greetings:
            return None, None
        import random
        return random.choice(greetings)

    def _speak_and_soft_focus(self, en_text, zh_text):
        print(f"\n[ReturnSentinel] 主动问候已触发...")
        print(_box_newline(f"║ 🤖  [Jarvis] {en_text}"))
        print(_box_newline(f"║ 📺  [Subtitle] {zh_text}"))
        print("╚" + "═"*63 + "\n")

        if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread:
            self.worker.voice_thread._suppress_wave = True

        try:
            state_signal = getattr(self.worker, 'state_changed', None)
            if hasattr(self.worker, 'chat_bypass') and hasattr(self.worker.chat_bypass, 'audio_queue'):
                if state_signal:
                    state_signal.emit("EXECUTING")
                self.worker.chat_bypass.audio_queue.put((en_text, {}))
            elif hasattr(self.worker, 'vocal'):
                if state_signal:
                    state_signal.emit("EXECUTING")
                self.worker.vocal.say(en_text)
                if state_signal:
                    state_signal.emit("IDLE")
        except Exception as e:
            print(f"[ReturnSentinel] 音频调度异常: {e}")
            try:
                state_signal = getattr(self.worker, 'state_changed', None)
                if state_signal:
                    state_signal.emit("IDLE")
            except:
                pass
        finally:
            if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread:
                self.worker.voice_thread._suppress_wave = False
                self.worker.voice_thread.mute_until = time.time() + 1.5

        self.worker.is_awake = True
        self.soft_focus_active = True
        self.soft_focus_until = time.time() + self._calc_soft_focus_duration()

        if hasattr(self.worker, 'voice_thread'):
            self.worker.voice_thread.in_active_conversation = True
            self.worker.voice_thread.last_interaction_time = time.time()

        if hasattr(self.worker, 'short_term_memory'):
            self.worker._append_stm("[归来感知] 主动问候", en_text, importance=0.4)

        if hasattr(self.worker, 'hippocampus'):
            try:
                self.worker.hippocampus.seal_chat_async(
                    self.worker.gemini_key,
                    "[归来感知] 主动问候",
                    en_text,
                    memory_protocol={"memory_type": "RETURN_GREETING"}
                )
            except:
                pass

    def _calc_soft_focus_duration(self) -> float:
        base_duration = 60.0
        try:
            if hasattr(self.worker, 'short_term_memory'):
                stm = getattr(self.worker, 'short_term_memory', [])
                if stm:
                    recent = stm[-3:]
                    for m in recent:
                        content = f"{m.get('user', '')} {m.get('jarvis', '')}"
                        if any(kw in content.lower() for kw in ['task', '任务', 'continue', '继续', 'wait', '等']):
                            base_duration += 30.0

                work_cat = PhysicalEnvironmentProbe.current_work_category
                if work_cat == "Coding":
                    base_duration += 30.0
                elif work_cat == "Media":
                    base_duration -= 20.0

            current_hour = int(time.strftime('%H'))
            if 22 <= current_hour or current_hour < 6:
                base_duration -= 15.0
        except Exception:
            pass

        return max(30.0, min(180.0, base_duration))

    def validate_soft_focus(self, audio_text):
        if not self.soft_focus_active:
            return False
        if time.time() > self.soft_focus_until:
            self.soft_focus_active = False
            return False

        # 👇 Bug B 修复（防御纵深）：focus_lock 90s 期间 mute_until 可能瞬时
        # 被切到 0，给 Jarvis TTS 拖尾留了空隙。这里在最后一道闸再筛一遍：
        # 如果 ASR 转的就是 Jarvis 12s 内说过的话，直接判为非用户响应。
        try:
            from jarvis_utils import is_recent_jarvis_echo
            if is_recent_jarvis_echo(audio_text):
                # 不关闭 soft_focus_active —— 继续等真正的用户响应
                return False
        except Exception:
            pass

        text_lower = audio_text.lower()
        wake_aliases = ["jarvis", "贾维斯", "charles", "travis", "jervis", "jus", "jobs", "just", "java", "rovis", "noice", "jarbis", "jarvas", "charvis"]
        if any(w in text_lower for w in wake_aliases):
            self.soft_focus_active = False
            return True

        # [P0+20-β.4.9 / 2026-05-19] 主动关怀类 reason 宽松 validate
        # Sir 反馈: ProactiveCare nudge 后 Sir 说短句 (e.g. "好"/"喝水"/"我去") 被判
        # "背景音/非对话" 静默退出 → Sir 失去回应窗口被迫重 wake. 治本:
        # Jarvis 主动开口 (proactive_care/commitment_check/inconsistency) 时, Sir
        # 60s 内任何有意义 ASR (≥1 中文字 OR ≥2 字母英文词) 都接受为回应.
        # Echo guard 已在 line ~795 拦, 此处不会把 Jarvis 自己回声当 Sir 回应.
        _soft_reason = getattr(self, '_soft_focus_reason', '')
        if _soft_reason in ('proactive_care', 'commitment_check', 'inconsistency'):
            zh_chars_count = len(re.findall(r'[\u4e00-\u9fa5]', audio_text))
            meaningful_en = [w for w in re.findall(r'[a-z]+', text_lower) if len(w) >= 2]
            if zh_chars_count >= 1 or meaningful_en:
                self.soft_focus_active = False
                return True
            # 纯符号 / 短到几乎空 → 继续保留 soft_focus 等下一句
            return False

        is_offer_help = _soft_reason == 'offer_help'

        if is_offer_help:
            if len(audio_text.split()) > 8:
                self.soft_focus_active = False
                return True
            zh_chars = re.findall(r'[\u4e00-\u9fa5]', audio_text)
            if len(zh_chars) > 6:
                self.soft_focus_active = False
                return True
            help_responses = [
                "yes", "no", "ok", "okay", "sure", "fine", "good", "great", "nice",
                "thanks", "thank you", "alright", "maybe", "yeah", "yep", "nope",
                "it's good", "its good", "i'm good", "im good", "not bad",
                "i'm fine", "im fine", "all good", "pretty good", "very good",
                "doing well", "doing good", "was good", "is good", "been good",
                "不错", "还行", "还好", "可以", "好的", "嗯", "好", "是", "对",
                "no thanks", "no thank you", "thanks but no", "not now", "later",
                "maybe later", "leave it", "let it be", "forget it",
                "i'll fix", "ill fix", "i will fix", "i can fix",
                "i'll handle", "ill handle", "i will handle",
                "i got it", "i've got it", "ive got it",
                "不需要", "不用", "不必", "没事", "算了", "不用了",
                "我自己", "自己来", "自己能", "我可以", "我能",
                "help me", "please help", "yes please", "go ahead",
                "sure thing", "let's do it", "lets do it",
                "帮我", "帮忙", "需要", "来吧", "行吧",
            ]
            if text_lower in help_responses or any(text_lower.startswith(r) for r in ["it's ", "its ", "i'm ", "im ", "was ", "is ", "been ", "i'll ", "ill ", "i will ", "i can ", "i've ", "ive "]):
                self.soft_focus_active = False
                return True
            meaningful_words = [w for w in re.findall(r'[a-z]+', text_lower) if len(w) >= 2]
            if len(meaningful_words) >= 3:
                self.soft_focus_active = False
                return True
            return False

        if len(audio_text.split()) > 4:
            self.soft_focus_active = False
            return True

        zh_chars = re.findall(r'[\u4e00-\u9fa5]', audio_text)
        if len(zh_chars) > 3:
            self.soft_focus_active = False
            return True

        common_responses = [
            "yes", "no", "ok", "okay", "sure", "fine", "good", "great", "nice",
            "thanks", "thank you", "alright", "maybe", "yeah", "yep", "nope",
            "it's good", "its good", "i'm good", "im good", "not bad",
            "i'm fine", "im fine", "all good", "pretty good", "very good",
            "doing well", "doing good", "was good", "is good", "been good",
            "不错", "还行", "还好", "可以", "好的", "嗯", "好", "是", "对",
        ]
        if text_lower in common_responses or any(text_lower.startswith(r) for r in ["it's ", "its ", "i'm ", "im ", "was ", "is ", "been "]):
            self.soft_focus_active = False
            return True

        meaningful_words = [w for w in re.findall(r'[a-z]+', text_lower) if len(w) >= 2]
        if len(meaningful_words) >= 2:
            self.soft_focus_active = False
            return True

        return False


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

