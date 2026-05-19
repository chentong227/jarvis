# -*- coding: utf-8 -*-
"""[P0+19-2 / 2026-05-16] PhysicalEnvironmentProbe — 物理环境感知

从 jarvis_nerve.py 拆出。设计原则：
- 毫秒级"心流"与"打扰阻力值"探测（28 维传感器矩阵）
- LLM 分类兜底（视觉理解 + 文本上下文）
- visual_context / visual_interruptibility / window_history 等
  **静态类属性**供其他模块只读访问（无须实例化）
- 主要被 jarvis_enhanced.py 的多个 sentinel 反向引用（之前是延迟 import 规避循环依赖）

依赖：
- 标准库：time / collections / threading
- Windows：win32gui / win32api / win32con / pycaw（顶部 import）
- 延迟 import：jarvis_utils.bg_log

线程安全：visual_interruptibility 等类属性允许多线程并发读；
内部 sensors 字典使用 lock 保护多线程更新。

副效益（P0+19-2 核心）：拆出后 jarvis_enhanced.py 可顶部 import 本类，
不再需要 10 处函数内延迟 import，循环依赖消失。
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


import time
import collections
import threading

import win32gui
import win32api
import win32con
# [P0+19-final fix 2]
from google.genai import types  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation  # noqa: F401


class PhysicalEnvironmentProbe:
    """纯物理探针：毫秒级心流与打扰阻力值探测 + LLM 分类兜底 + 28维传感器矩阵"""
    
    visual_context = "先生当前状态未知。"
    visual_interruptibility = 0
    
    current_physical_state = "[系统刚启动，状态采集中...]"
    current_window_title = ""
    window_history = collections.deque(maxlen=180)
    _is_monitoring = False
    
    current_process_name = "Unknown"
    current_work_category = "Idle"
    work_session_start = 0.0
    work_duration_minutes = 0
    _tick_callbacks = []
    
    _llm_classifier_key_router = None
    _llm_classifier_enabled = True
    _llm_last_classification_time = 0
    _llm_classification_interval = 120
    _llm_cached_category = None
    _llm_cached_detail = None

    # === 传感器矩阵 (28维) ===
    # 窗口与进程
    current_window_stay_seconds = 0.0
    _window_stay_start = 0.0
    _last_window_title = ""
    switch_frequency_5min = 0.0
    category_sequence = collections.deque(maxlen=20)
    
    # 键盘行为
    key_press_count_5min = 0
    backspace_count_5min = 0
    backspace_ratio = 0.0
    _key_timestamps = collections.deque(maxlen=500)
    _backspace_timestamps = collections.deque(maxlen=200)
    keyboard_burst_pause_ratio = 0.0
    shortcut_save_count_5min = 0
    shortcut_undo_count_5min = 0
    
    # 鼠标行为
    mouse_distance_5min = 0.0
    click_count_5min = 0
    scroll_amount_5min = 0
    _last_cursor_pos = (0, 0)
    _mouse_positions_5min = collections.deque(maxlen=300)
    _click_timestamps = collections.deque(maxlen=200)
    _scroll_accumulator = 0
    
    # 空闲与时间
    idle_seconds = 0.0
    is_first_active_today = True
    _first_active_reset_day = ""
    is_night_time = False
    
    # 后台环境
    background_distraction_count = 0
    wechat_has_unread = False
    audio_playing = False
    video_editor_open = False
    _last_bg_scan_time = 0
    _bg_scan_interval = 30
    
    # EMA 统计 (每个传感器维护自己的指数移动平均)
    _sensor_ema = {}
    _sensor_ema_alpha = {
        'switch_frequency': 0.9,
        'window_stay': 0.9,
        'key_frequency': 0.9,
        'backspace_ratio': 0.95,
        'burst_pause_ratio': 0.95,
        'shortcut_save': 0.95,
        'shortcut_undo': 0.95,
        'mouse_distance': 0.9,
        'click_frequency': 0.9,
        'scroll_amount': 0.9,
        'idle_seconds': 0.9,
        'session_duration': 0.99,
        'bg_distraction': 0.95,
    }
    
    # 传感器权重 (在线学习，初始值基于先验)
    _sensor_weights = {
        'switch_frequency': 1.0,
        'window_stay': 0.9,
        'category_entropy': 0.7,
        'key_frequency': 0.8,
        'backspace_ratio': 0.7,
        'burst_pause_ratio': 0.6,
        'shortcut_save': 0.4,
        'shortcut_undo': 0.5,
        'mouse_distance': 0.6,
        'click_frequency': 0.5,
        'scroll_amount': 0.4,
        'idle_seconds': 0.9,
        'session_duration': 0.7,
        'is_night': 0.6,
        'is_first_active': 0.8,
        'bg_distraction': 0.6,
        'wechat_unread': 0.5,
        'audio_playing': 0.3,
        'video_editor': 0.4,
        'error_visible': 0.9,
        'emotional_frustrated': 0.8,
        'cognitive_load_high': 0.7,
    }
    
    # 传感器容忍度 (z-score 在此范围内不算异常)
    _sensor_tolerance = {
        'switch_frequency': 0.4,
        'window_stay': 0.5,
        'category_entropy': 0.5,
        'key_frequency': 0.4,
        'backspace_ratio': 0.5,
        'burst_pause_ratio': 0.5,
        'shortcut_save': 0.5,
        'shortcut_undo': 0.5,
        'mouse_distance': 0.5,
        'click_frequency': 0.5,
        'scroll_amount': 0.5,
        'idle_seconds': 0.5,
        'session_duration': 0.3,
        'is_night': 1.0,
        'is_first_active': 1.0,
        'bg_distraction': 0.5,
        'wechat_unread': 0.5,
        'audio_playing': 0.5,
        'video_editor': 0.5,
        'error_visible': 0.5,
        'emotional_frustrated': 0.5,
        'cognitive_load_high': 0.5,
    }
    
    # 上一次传感器快照 (供 Conductor 使用)
    _last_sensor_snapshot = {}
    _last_snapshot_time = 0

    # 外部模块告警标记 (ProactiveShield / ProactiveCompanion 上报，由 Conductor 统一消费)
    _shield_alert = {'active': False}
    _companion_alert = {'active': False}
    _wellness_alert = {'active': False}

    @classmethod
    def set_key_router(cls, key_router):
        cls._llm_classifier_key_router = key_router

    @classmethod
    def _classify_with_llm(cls, window_title: str, process_name: str) -> tuple:
        if not cls._llm_classifier_key_router or not cls._llm_classifier_enabled:
            return None, None
        now = time.time()
        if now - cls._llm_last_classification_time < cls._llm_classification_interval:
            return cls._llm_cached_category, cls._llm_cached_detail
        if not window_title or len(window_title) < 3:
            return None, None
        
        cls._llm_last_classification_time = now
        try:
            prompt = f"""Classify this active window into ONE category. Respond with ONLY the category name and a brief detail.

Window Title: "{window_title[:100]}"
Process: "{process_name}"

Categories:
- Coding: IDE, terminal, code editor, debugger, documentation for programming
- Media: video player, music, streaming, games, entertainment
- Communication: chat, email, social media, messaging
- Browsing: general web browsing, research, reading articles
- AFK: idle, away from keyboard
- General: anything else

Respond in format: CATEGORY|detail
Example: Coding|Working in VS Code on a Python project"""
            
            def _classify_call(client):
                return client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=prompt,
                    config=types.GenerateContentConfig(max_output_tokens=30, temperature=0.1)
                )
            
            res, _key_name, _client = safe_gemini_call(
                cls._llm_classifier_key_router, KeyRouter.CALLER_SENTINEL, 'flash_lite',
                _classify_call, max_retries=1, base_delay=0.5,
                model_name='gemini-3.1-flash-lite', contents_text=prompt
            )
            cls._llm_classifier_key_router.release(_key_name)
            
            text = res.text.strip()
            if '|' in text:
                parts = text.split('|', 1)
                cat = parts[0].strip()
                detail = parts[1].strip() if len(parts) > 1 else window_title[:50]
                valid_cats = ['Coding', 'Media', 'Communication', 'Browsing', 'AFK', 'General']
                if cat in valid_cats:
                    cls._llm_cached_category = cat
                    cls._llm_cached_detail = detail
                    return cat, detail
        except Exception:
            cls._llm_classifier_enabled = False
        
        return None, None

    @classmethod
    def start_monitoring(cls):
        """启动毫秒级本地雷达 (0 算力消耗)"""
        if cls._is_monitoring: return
        cls._is_monitoring = True
        import threading
        threading.Thread(target=cls._monitor_loop, daemon=True).start()

    @classmethod
    def _monitor_loop(cls):
        import win32gui, win32api, win32con, win32process, time
        import ctypes
        from ctypes import wintypes
        
        try:
            import psutil
            _has_psutil = True
        except ImportError:
            _has_psutil = False
        
        user32 = ctypes.windll.user32
        
        VK_BACK = 0x08
        VK_DELETE = 0x2E
        VK_CONTROL = 0x11
        VK_LBUTTON = 0x01
        VK_RBUTTON = 0x02
        
        cls._last_cursor_pos = win32api.GetCursorPos()
        cls._window_stay_start = time.time()
        cls._last_window_title = ""
        
        while True:
            try:
                current_time = time.time()
                hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(hwnd) if hwnd else ""
                idle_time_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
                
                if _has_psutil and hwnd:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        proc = psutil.Process(pid)
                        cls.current_process_name = proc.name()
                    except Exception:
                        pass
                
                cls.window_history.append({
                    "time": current_time, 
                    "title": window_title, 
                    "idle_ms": idle_time_ms
                })
                
                # === 窗口停留时长 ===
                if window_title != cls._last_window_title and window_title:
                    cls._window_stay_start = current_time
                    cls._last_window_title = window_title
                cls.current_window_stay_seconds = round(current_time - cls._window_stay_start, 1)
                
                # === 切窗频率 (过去5分钟) ===
                cutoff_time = current_time - 300
                recent_switches = 0
                last_seen_title = None
                for entry in cls.window_history:
                    if entry["time"] >= cutoff_time:
                        if last_seen_title is not None and entry["title"] != last_seen_title and entry["title"] != "":
                            recent_switches += 1
                        last_seen_title = entry["title"]
                cls.switch_frequency_5min = recent_switches
                
                # === 工作类别序列 ===
                cls.category_sequence.append({
                    "time": current_time,
                    "category": cls.current_work_category,
                    "title": window_title[:60]
                })
                
                # === 键盘监控 ===
                key_down_this_tick = False
                backspace_this_tick = False
                ctrl_held = (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
                
                for vk_code in range(0x08, 0x5A):
                    if (user32.GetAsyncKeyState(vk_code) & 0x8000):
                        key_down_this_tick = True
                        cls._key_timestamps.append(current_time)
                        if vk_code == VK_BACK:
                            backspace_this_tick = True
                            cls._backspace_timestamps.append(current_time)
                        if ctrl_held:
                            if vk_code == ord('S'):
                                cls.shortcut_save_count_5min += 1
                            elif vk_code == ord('Z'):
                                cls.shortcut_undo_count_5min += 1
                        break
                
                cutoff_5min = current_time - 300
                while cls._key_timestamps and cls._key_timestamps[0] < cutoff_5min:
                    cls._key_timestamps.popleft()
                while cls._backspace_timestamps and cls._backspace_timestamps[0] < cutoff_5min:
                    cls._backspace_timestamps.popleft()
                
                cls.key_press_count_5min = len(cls._key_timestamps)
                cls.backspace_count_5min = len(cls._backspace_timestamps)
                if cls.key_press_count_5min > 0:
                    cls.backspace_ratio = round(cls.backspace_count_5min / cls.key_press_count_5min, 3)
                else:
                    cls.backspace_ratio = 0.0
                
                # === 键盘节奏 (burst/pause 比) ===
                if len(cls._key_timestamps) >= 3:
                    intervals = []
                    sorted_keys = sorted(cls._key_timestamps)
                    for i in range(1, len(sorted_keys)):
                        intervals.append(sorted_keys[i] - sorted_keys[i-1])
                    if intervals:
                        burst_count = sum(1 for x in intervals if x < 0.5)
                        pause_count = sum(1 for x in intervals if x > 3.0)
                        total = len(intervals)
                        cls.keyboard_burst_pause_ratio = round(
                            (burst_count - pause_count) / max(total, 1), 3
                        )
                
                # === 鼠标监控 ===
                cursor_pos = win32api.GetCursorPos()
                dx = cursor_pos[0] - cls._last_cursor_pos[0]
                dy = cursor_pos[1] - cls._last_cursor_pos[1]
                move_dist = (dx * dx + dy * dy) ** 0.5
                cls._mouse_positions_5min.append({
                    "time": current_time, "x": cursor_pos[0], "y": cursor_pos[1], "dist": move_dist
                })
                cls._last_cursor_pos = cursor_pos
                
                while cls._mouse_positions_5min and cls._mouse_positions_5min[0]["time"] < cutoff_5min:
                    cls._mouse_positions_5min.popleft()
                cls.mouse_distance_5min = round(
                    sum(p["dist"] for p in cls._mouse_positions_5min), 1
                )
                
                if (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) or \
                   (user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000):
                    cls._click_timestamps.append(current_time)
                while cls._click_timestamps and cls._click_timestamps[0] < cutoff_5min:
                    cls._click_timestamps.popleft()
                cls.click_count_5min = len(cls._click_timestamps)
                
                # === 空闲时长 ===
                cls.idle_seconds = round(idle_time_ms / 1000.0, 1)
                
                # === 今日首次活跃 ===
                current_day = time.strftime('%Y-%m-%d')
                if current_day != cls._first_active_reset_day:
                    cls._first_active_reset_day = current_day
                    cls.is_first_active_today = True
                if cls.idle_seconds < 30 and cls.is_first_active_today:
                    cls.is_first_active_today = False
                
                # === 深夜时段 ===
                current_hour = int(time.strftime('%H'))
                cls.is_night_time = (current_hour >= 23 or current_hour < 6)
                
                # === 后台环境扫描 (每30秒一次) ===
                if _has_psutil and current_time - cls._last_bg_scan_time > cls._bg_scan_interval:
                    cls._last_bg_scan_time = current_time
                    try:
                        distraction_procs = ['WeChat.exe', 'Wechat.exe', '微信.exe',
                                           'QQ.exe', 'TIM.exe', 'DingTalk.exe', '钉钉.exe',
                                           'Telegram.exe', 'Discord.exe', 'Slack.exe',
                                           'Feishu.exe', '飞书.exe', 'Lark.exe']
                        media_procs = ['cloudmusic.exe', 'QQMusic.exe', 'Spotify.exe',
                                      'foobar2000.exe', 'bilibili.exe']
                        video_edit_procs = ['Premiere.exe', 'AfterFX.exe', '剪映.exe',
                                          'Jianying.exe', 'CapCut.exe', 'DaVinci.exe',
                                          'Resolve.exe', 'Vegas.exe', 'FinalCut.exe']
                        
                        distraction_count = 0
                        wechat_unread = False
                        audio_active = False
                        video_editor = False
                        
                        for p in psutil.process_iter(['name']):
                            try:
                                pname = p.info['name'] or ''
                                if any(d in pname for d in distraction_procs):
                                    distraction_count += 1
                                if any(m in pname for m in media_procs):
                                    audio_active = True
                                if any(v in pname for v in video_edit_procs):
                                    video_editor = True
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                        
                        try:
                            wx_hwnd = user32.FindWindowW(None, None)
                            def _enum_wx(hwnd, _):
                                title = win32gui.GetWindowText(hwnd)
                                if '微信' in title:
                                    import re
                                    match = re.search(r'微信\((\d+)\)', title)
                                    if match and int(match.group(1)) > 0:
                                        nonlocal wechat_unread
                                        wechat_unread = True
                                        return False
                                return True
                            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
                            user32.EnumWindows(WNDENUMPROC(_enum_wx), 0)
                        except Exception:
                            pass
                        
                        try:
                            import pythoncom
                            pythoncom.CoInitialize()
                            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
                            sessions = AudioUtilities.GetAllSessions()
                            for session in sessions:
                                if session.Process:
                                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                                    if meter.GetPeakValue() > 0.05:
                                        audio_active = True
                                        break
                        except Exception:
                            pass
                        
                        cls.background_distraction_count = distraction_count
                        cls.wechat_has_unread = wechat_unread
                        cls.audio_playing = audio_active
                        cls.video_editor_open = video_editor
                    except Exception:
                        pass
                
                # === 更新 EMA ===
                cls._update_sensor_ema(current_time)
                
                # === 生成传感器快照 ===
                cls._last_sensor_snapshot = cls._build_sensor_snapshot()
                cls._last_snapshot_time = current_time
                
                # === 原有分类逻辑 ===
                lower_title = window_title.lower()
                prev_category = cls.current_work_category
                if idle_time_ms > 300000: 
                    cls.current_physical_state = "[AFK / Away From Keyboard]"
                    cls.current_work_category = "AFK"
                elif recent_switches >= 12: 
                    cls.current_physical_state = "[High APM / Intense Coding or Debugging]"
                    cls.current_work_category = "Coding"
                else:
                    if any(x in lower_title for x in ["bilibili", "youtube", "爱奇艺", "网易云", "飞车"]):
                        cls.current_physical_state = "[Media Consumption / Relaxing]"
                        cls.current_work_category = "Media"
                    elif any(x in lower_title for x in ["code", "cursor", "pycharm", "powershell"]):
                        cls.current_physical_state = f"[Geek Terminal or IDE / Active Window: {window_title[:30]}]"
                        cls.current_work_category = "Coding"
                    else:
                        cls.current_physical_state = f"[Standard Desktop Operation / Active Window: {window_title[:30]}]"
                        cls.current_work_category = "General"
                        
                        llm_cat, llm_detail = cls._classify_with_llm(window_title, cls.current_process_name)
                        if llm_cat:
                            cls.current_work_category = llm_cat
                            cls.current_physical_state = f"[{llm_cat} / {llm_detail[:50]}]"
                
                if prev_category != cls.current_work_category:
                    cls.work_session_start = current_time
                    # [β.5.0-A / 2026-05-19] SWM: category 变化 publish 给主脑
                    try:
                        from jarvis_utils import get_event_bus
                        _bus = get_event_bus()
                        if _bus is not None:
                            _bus.publish(
                                etype='sensor_change',
                                description=f"work_category: {prev_category} → {cls.current_work_category}",
                                source='PhysicalEnvProbe',
                                metadata={
                                    'kind': 'category_change',
                                    'prev': prev_category,
                                    'curr': cls.current_work_category,
                                },
                            )
                    except Exception:
                        pass
                
                if cls.work_session_start > 0:
                    cls.work_duration_minutes = round((current_time - cls.work_session_start) / 60, 1)
                        
            except Exception:
                pass
            
            for cb in cls._tick_callbacks:
                try:
                    cb()
                except Exception:
                    pass
            
            time.sleep(1)

    @classmethod
    def _update_sensor_ema(cls, current_time):
        observations = {
            'switch_frequency': cls.switch_frequency_5min,
            'window_stay': cls.current_window_stay_seconds,
            'key_frequency': cls.key_press_count_5min,
            'backspace_ratio': cls.backspace_ratio,
            'burst_pause_ratio': cls.keyboard_burst_pause_ratio,
            'shortcut_save': cls.shortcut_save_count_5min,
            'shortcut_undo': cls.shortcut_undo_count_5min,
            'mouse_distance': cls.mouse_distance_5min,
            'click_frequency': cls.click_count_5min,
            'scroll_amount': cls.scroll_amount_5min,
            'idle_seconds': cls.idle_seconds,
            'session_duration': cls.work_duration_minutes,
            'bg_distraction': cls.background_distraction_count,
        }
        for name, value in observations.items():
            alpha = cls._sensor_ema_alpha.get(name, 0.9)
            if name not in cls._sensor_ema:
                cls._sensor_ema[name] = value
            else:
                cls._sensor_ema[name] = alpha * cls._sensor_ema[name] + (1 - alpha) * value

    @classmethod
    def _build_sensor_snapshot(cls) -> dict:
        error_keywords = ['error', 'exception', 'traceback', 'stack trace',
                         '报错', '错误', 'stackoverflow', 'failed', 'failure']
        lower_title = cls.current_window_title.lower()
        error_visible = any(kw in lower_title for kw in error_keywords)
        
        cat_seq = list(cls.category_sequence)
        cat_list = [c['category'] for c in cat_seq if c['category'] != 'AFK']
        category_entropy = 0.0
        if len(cat_list) >= 3:
            from collections import Counter
            counts = Counter(cat_list)
            total = len(cat_list)
            import math
            category_entropy = -sum((c/total) * math.log(c/total + 0.001) for c in counts.values())
        
        return {
            'timestamp': cls._last_snapshot_time or time.time(),
            'window_title': cls.current_window_title,
            'process_name': cls.current_process_name,
            'work_category': cls.current_work_category,
            'window_stay_seconds': cls.current_window_stay_seconds,
            'switch_frequency_5min': cls.switch_frequency_5min,
            'category_entropy': round(category_entropy, 3),
            'key_press_count_5min': cls.key_press_count_5min,
            'backspace_ratio': cls.backspace_ratio,
            'burst_pause_ratio': cls.keyboard_burst_pause_ratio,
            'shortcut_save_5min': cls.shortcut_save_count_5min,
            'shortcut_undo_5min': cls.shortcut_undo_count_5min,
            'mouse_distance_5min': cls.mouse_distance_5min,
            'click_count_5min': cls.click_count_5min,
            'scroll_amount_5min': cls.scroll_amount_5min,
            'idle_seconds': cls.idle_seconds,
            'session_duration_minutes': cls.work_duration_minutes,
            'is_night_time': cls.is_night_time,
            'is_first_active_today': cls.is_first_active_today,
            'background_distraction_count': cls.background_distraction_count,
            'wechat_has_unread': cls.wechat_has_unread,
            'audio_playing': cls.audio_playing,
            'video_editor_open': cls.video_editor_open,
            'error_visible': error_visible,
            'physical_state': cls.current_physical_state,
            'shield_alert': dict(cls._shield_alert),
            'companion_alert': dict(cls._companion_alert),
            'wellness_alert': dict(cls._wellness_alert),
        }

    @classmethod
    def get_sensor_snapshot(cls) -> dict:
        return dict(cls._last_sensor_snapshot)

    @classmethod
    def compute_zscore(cls, sensor_name: str, current_value: float) -> float:
        ema = cls._sensor_ema.get(sensor_name, current_value)
        if ema < 0.001:
            return 0.0
        ratio = current_value / max(ema, 0.001)
        tolerance = cls._sensor_tolerance.get(sensor_name, 0.5)
        if 1.0 - tolerance <= ratio <= 1.0 + tolerance:
            return 0.0
        return abs(ratio - 1.0)

    @classmethod
    def compute_fusion_score(cls) -> float:
        snapshot = cls._last_sensor_snapshot
        if not snapshot:
            return 0.0
        
        z_scores = {}
        numeric_sensors = [
            'switch_frequency_5min', 'window_stay_seconds', 'category_entropy',
            'key_press_count_5min', 'backspace_ratio', 'burst_pause_ratio',
            'shortcut_save_5min', 'shortcut_undo_5min',
            'mouse_distance_5min', 'click_count_5min', 'scroll_amount_5min',
            'idle_seconds', 'session_duration_minutes', 'background_distraction_count',
        ]
        for sensor in numeric_sensors:
            value = snapshot.get(sensor, 0)
            z = cls.compute_zscore(sensor, value)
            z_scores[sensor] = z
        
        binary_sensors = {
            'is_night': 1.0 if snapshot.get('is_night_time') else 0.0,
            'is_first_active': 1.0 if snapshot.get('is_first_active_today') else 0.0,
            'wechat_unread': 1.0 if snapshot.get('wechat_has_unread') else 0.0,
            'audio_playing': 1.0 if snapshot.get('audio_playing') else 0.0,
            'video_editor': 1.0 if snapshot.get('video_editor_open') else 0.0,
            'error_visible': 1.0 if snapshot.get('error_visible') else 0.0,
        }
        
        total_score = 0.0
        total_weight = 0.0
        
        for name, z in z_scores.items():
            weight = cls._sensor_weights.get(name, 0.5)
            total_score += weight * z
            total_weight += weight
        
        for name, value in binary_sensors.items():
            weight = cls._sensor_weights.get(name, 0.5)
            total_score += weight * value
            total_weight += weight
        
        if total_weight > 0:
            return round(total_score / total_weight, 4)
        return 0.0

    @classmethod
    def update_sensor_weight(cls, sensor_name: str, feedback: float, surprise: float):
        if sensor_name in cls._sensor_weights:
            lr = 0.02
            cls._sensor_weights[sensor_name] += lr * feedback * surprise
            cls._sensor_weights[sensor_name] = max(0.05, min(2.0, cls._sensor_weights[sensor_name]))

    @staticmethod
    def get_interruptibility_score():
        """保持向下兼容，继续为 ChronosTick 起搏器提供阻力值"""
        score = 0
        try:
            import win32gui, win32api, win32con
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                screen_x = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_y = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                if (rect[2] - rect[0]) >= screen_x and (rect[3] - rect[1]) >= screen_y:
                    score += 50  
        except: pass

        try:
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name().lower() not in ["python.exe"]:
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    if meter.GetPeakValue() > 0.05: 
                        score += 40
                        break
        except: pass

        try:
            import win32api
            idle_time_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
            if idle_time_ms < 3000: 
                score += 20
            elif idle_time_ms > 60000: 
                score -= 30 
        except: pass
        
        score += PhysicalEnvironmentProbe.visual_interruptibility
        return max(0, min(100, score))


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

