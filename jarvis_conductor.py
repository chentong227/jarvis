# -*- coding: utf-8 -*-
"""[P0+19-6.b / 2026-05-16] 指挥官 Conductor — 传感器融合 + 规则/LLM 决策 + 三档轻推

从 jarvis_nerve.py 拆出 1 个大类（>500 行）。
向后兼容：jarvis_nerve.py 用 `from jarvis_conductor import Conductor` 转发，
旧 `from jarvis_nerve import Conductor` 0 改动。
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




class Conductor(threading.Thread):
    """指挥中枢：事件驱动决策入口
    
    路径A（外部警报）：Shield/Companion/Wellness 触发 → 收集上下文 → 发给主脑自然发声
    路径B（操作异常）：SensorFilter 漏斗触发 → 截图 → 决策LLM → 发给主脑
    """
    
    def __init__(self, jarvis_worker, nudge_gate=None):
        super().__init__(daemon=True)
        self.worker = jarvis_worker
        self.gate = nudge_gate
        self._running = False
        self._last_action_time = 0
        self._action_cooldown = 120
        self._daily_action_count = 0
        self._last_reset_day = ""
        self._action_history = collections.deque(maxlen=50)
        self._state_archive = collections.deque(maxlen=1440)
        
        self.sensor_filter = SensorFilter()
        self._screenshot_sentinel = None
        
        # [P0-8 / 2026-05-15] 修复严重语义错配 bug：
        # 旧版 把 Conductor 的"打个招呼"决策（action=Check-in）错误地映射到 ReturnSentinel
        # 的 AFK 归来问候类型 → 终端日志显示误导，且 8 处豁免条件让 Check-in 绕过
        # 拒绝期/sleep_mode/hard_freeze。
        # 实测 Sir 凌晨 1:44-1:45 47s 内被骚扰两次正是这个 bug：
        # 第一次 ReturnSentinel 真的归来问候 → soft_focus 60s → timeout → Conductor 路径B
        # 触发 Check-in → 假装成归来问候又出声一次。
        # 修法：Check-in 走独立的 check_in 类型；豁免点单独处理。
        self._nudge_type_map = {
            'Check-in': 'check_in',
            'Offer Help': 'offer_help',
            'Suggest Break': 'suggest_break',
            'Motivate': 'flow_end',
            'Warn Late Night': 'late_night',
            'Knowledge Archive': 'atmosphere',
            'Context Switch Alert': 'context_switch_alert',
        }
        
        # 拦截原因诊断（限频 30s 防刷屏）
        self._last_block_log_time = 0
        self._block_log_interval = 30
    
    def set_screenshot_sentinel(self, sentinel):
        self._screenshot_sentinel = sentinel
    
    def run(self):
        time.sleep(30)
        print("[Conductor] 指挥中枢就绪 — 事件驱动决策引擎已激活...")
        self._running = True
        while self._running:
            try:
                self._event_loop()
            except Exception as e:
                print(f"[Conductor] 中枢异常: {e}")
            time.sleep(5)
    
    def _event_loop(self):
        current_time = time.time()
        current_day = time.strftime('%Y-%m-%d')
        
        if current_day != self._last_reset_day:
            self._last_reset_day = current_day
            self._daily_action_count = 0
        
        # 检查是否有待消费的高优 alert，如果有但被拦截，限频打一行提示
        def _has_pending_alert():
            return (PhysicalEnvironmentProbe._shield_alert.get('active') or
                    PhysicalEnvironmentProbe._wellness_alert.get('active'))
        
        def _log_block(reason: str):
            if current_time - self._last_block_log_time > self._block_log_interval:
                if _has_pending_alert():
                    pending = []
                    if PhysicalEnvironmentProbe._shield_alert.get('active'):
                        s = PhysicalEnvironmentProbe._shield_alert
                        pending.append(f"shield({s.get('type','')}/{s.get('switch_count','?')}sw)")
                    if PhysicalEnvironmentProbe._wellness_alert.get('active'):
                        pending.append("wellness")
                    self._last_block_log_time = current_time
                    print(f"⏸️ [Conductor] alert pending ({', '.join(pending)}) but blocked: {reason}")
        
        if self.gate and self.gate.is_sleep_mode():
            _log_block("sleep_mode")
            return
        
        if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread.in_active_conversation:
            _log_block("in_active_conversation")
            return
        
        if getattr(self.worker, 'is_active_task', False):
            _log_block("is_active_task")
            return
        
        if current_time - self._last_action_time < self._action_cooldown:
            _log_block(f"action_cooldown ({int(self._action_cooldown - (current_time - self._last_action_time))}s left)")
            return
        
        if self._daily_action_count >= 12:
            _log_block("daily_limit_reached")
            return
        
        snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
        if not snapshot:
            return
        
        fusion_score = PhysicalEnvironmentProbe.compute_fusion_score()
        self._state_archive.append({
            'time': current_time,
            'snapshot': snapshot,
            'fusion_score': fusion_score
        })
        
        path_a_result = self._check_path_a(snapshot)
        if path_a_result:
            self._dispatch_path_a(path_a_result, snapshot)
            return
        
        path_b_result = self.sensor_filter.should_trigger()
        if path_b_result.get("triggered"):
            self._execute_path_b(path_b_result)
    
    def _check_path_a(self, snapshot: dict) -> dict:
        # 注：companion_alert 通道已弃用 —— ProactiveCompanion 未启用
        # 重叠功能由其他模块承担：
        #   morning_greeting → ReturnSentinel.first_active_today
        #   work_switch      → SmartNudgeSentinel.flow_end
        #   breath_check     → 与 JARVIS 管家人设不符（管家不做周期性情感关怀）
        shield_alert = snapshot.get('shield_alert', {})
        wellness_alert = snapshot.get('wellness_alert', {})
        
        if shield_alert.get('active') and self._daily_action_count < 12:
            PhysicalEnvironmentProbe._shield_alert = {'active': False}
            return {
                'source': 'ProactiveShield',
                'alert_type': shield_alert.get('type', 'unknown'),
                'action': 'Offer Help',
                'reason': f"效率断崖检测: {shield_alert.get('type', 'unknown')}",
                'tone': 'gentle',
                'nudge_type': 'offer_help',
            }
        
        if wellness_alert.get('active') and self._daily_action_count < 12:
            PhysicalEnvironmentProbe._wellness_alert = {'active': False}
            return {
                'source': 'WellnessGuardian',
                'alert_type': 'wellness',
                'action': 'Suggest Break',
                'reason': f"健康守护: {wellness_alert.get('reason', 'health check')}",
                'tone': 'gentle',
                'nudge_type': 'suggest_break',
            }
        
        return None
    
    def _dispatch_path_a(self, alert_info: dict, snapshot: dict):
        nudge_type = alert_info['nudge_type']
        if self.gate and not self.gate.can_speak('guardian', is_urgent=False, nudge_type=nudge_type):
            return

        # [R7-β post-test v3] 拒绝期内任何 nudge_type 都跳过（return_greeting 除外）
        # [P0+20-β.2.4 hotfix / 2026-05-16] worker.jarvis.X 伪失效守卫修复
        from jarvis_utils import resolve_worker_attr as _rwa
        cc = _rwa(self.worker, 'companion_center')
        if cc is not None:
            if hasattr(cc, 'smart_nudge') and cc.smart_nudge:
                sn = cc.smart_nudge
                if time.time() < sn._refused_help_until and nudge_type != 'return_greeting':
                    try:
                        from jarvis_utils import bg_log
                        remaining = int(sn._refused_help_until - time.time())
                        bg_log(f"🚫 [Conductor-A/RefusalRespect] 用户拒绝期内，跳过 {nudge_type}（剩 {remaining}s）")
                    except Exception:
                        pass
                    return

        if nudge_type == 'offer_help':
            cc = _rwa(self.worker, 'companion_center')
            if cc is not None:
                if hasattr(cc, 'smart_nudge') and cc.smart_nudge:
                    sn = cc.smart_nudge
                    _win_title = ""
                    try:
                        import win32gui
                        _hwnd = win32gui.GetForegroundWindow()
                        _win_title = win32gui.GetWindowText(_hwnd) if _hwnd else ""
                    except:
                        pass
                    fingerprint = sn._gen_help_fingerprint({
                        'window_title': _win_title,
                        'category': 'error'
                    })
                    dynamic_cooldown = sn._calc_help_cooldown(fingerprint)
                    if dynamic_cooldown > 0:
                        remaining = dynamic_cooldown - (time.time() - sn._last_help_fingerprint_time)
                        if remaining > 0:
                            return
                    sn._last_help_fingerprint = fingerprint
                    sn._last_help_fingerprint_time = time.time()
        
        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')
        work_category = PhysicalEnvironmentProbe.current_work_category
        work_duration = PhysicalEnvironmentProbe.work_duration_minutes
        window_title = ""
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            window_title = win32gui.GetWindowText(hwnd) if hwnd else ""
        except:
            pass
        
        sensor_summary = (
            f"窗口: {window_title[:80]} | "
            f"类别: {work_category} | "
            f"会话时长: {int(work_duration)}分钟 | "
            f"按键/5min: {snapshot.get('key_press_count_5min', 0)} | "
            f"退格率: {snapshot.get('backspace_ratio', 0):.2%} | "
            f"切换/5min: {snapshot.get('switch_frequency_5min', 0)} | "
            f"空闲: {snapshot.get('idle_seconds', 0)}s | "
            f"深夜: {snapshot.get('is_night_time', False)} | "
            f"报错: {snapshot.get('error_visible', False)}"
        )
        
        conductor_message = (
            f"调度中心内部通知：{alert_info['source']} 检测到事件。"
            f"触发原因：{alert_info['reason']}。"
            f"当前时间：{current_time}。"
            f"传感器摘要：[{sensor_summary}]。"
            f"请根据以上上下文，以自然的语气主动对先生说一句话。"
            f"语气要求：{alert_info['tone']}。"
            f"不要说我通知你的，就像你自己注意到的一样自然地说出来。"
        )
        
        nudge_context = {
            "type": nudge_type,
            "recent_topics": [],
            "conductor_message": conductor_message,
            "conductor_action": alert_info['action'],
            "conductor_reason": alert_info['reason'],
            "session_duration": snapshot.get('session_duration_minutes', 0),
            "error_visible": snapshot.get('error_visible', False),
            "switch_frequency": snapshot.get('switch_frequency_5min', 0),
            "category_entropy": snapshot.get('category_entropy', 0),
        }
        
        cmd = f"__NUDGE__:{json.dumps(nudge_context, ensure_ascii=False)}"
        self.worker.push_command(cmd)
        if self.gate:
            self.gate.mark_spoke('guardian')
        
        self._last_action_time = time.time()
        self._daily_action_count += 1
        self._action_history.append({
            'time': time.strftime('%H:%M:%S'),
            'action': alert_info['action'],
            'reason': alert_info['reason'],
            'confidence': 0.85
        })
        # [P0+18-b.3 / 2026-05-15] 改 bg_log，主对话框不再被诊断行干扰
        try:
            from jarvis_utils import bg_log
            bg_log(f"[Conductor] 路径A触发: {alert_info['source']} → {alert_info['action']} → 已发送 __NUDGE__")
        except Exception:
            print(f"[Conductor] 路径A触发: {alert_info['source']} → {alert_info['action']} → 已发送 __NUDGE__")
    
    def _execute_path_b(self, filter_result: dict):
        decision = self._decision_llm(filter_result)
        if not decision or not decision.get('should_speak'):
            return
        
        nudge_type = decision.get('nudge_type', 'offer_help')

        # [P0+18-b.7 / 2026-05-15] 最近主动对话冷却：用户刚跟 Jarvis 说完话的
        # 120s 内不再插话主动 offer —— 修"用户问'你能做什么'立刻被推 offer_help"
        # 的 UX 问题（用户感觉 Jarvis 抢答 / 不给思考空间）。
        try:
            if hasattr(self.worker, 'voice_thread') and self.worker.voice_thread:
                last_user_speech = getattr(self.worker.voice_thread, 'last_user_speech_time', 0.0)
                if last_user_speech > 0:
                    elapsed_since_user = time.time() - last_user_speech
                    if elapsed_since_user < 120.0:
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"⏸️ [Conductor/PostChatCooldown] Sir 刚对话过 ({int(elapsed_since_user)}s 前)，path_b 暂缓主动 {nudge_type}（剩 {int(120 - elapsed_since_user)}s）")
                        except Exception:
                            pass
                        return
        except Exception:
            pass

        if self.gate and not self.gate.can_speak('guardian', is_urgent=True, nudge_type=nudge_type):
            return

        # [v5.1 / Sir-2026-05-15] Sleep Intent 抑制：Sir 已表态 X 分钟后睡 → 静默 sleep 类 nudge
        # 修"重复催睡"——Sir 说一遍后 Conductor 不该 6/10/14 分钟接连再催
        _SLEEP_RELATED_NUDGES = {'late_night', 'suggest_break', 'bedtime'}
        if nudge_type in _SLEEP_RELATED_NUDGES:
            spi = getattr(self.worker, '_sleep_intent_until', 0.0)
            if time.time() < spi:
                try:
                    from jarvis_utils import bg_log
                    remaining = int(spi - time.time())
                    bg_log(f"💤 [Conductor/SleepIntent] Sir 已表态睡眠意图，静默 {nudge_type}（剩 {remaining}s）")
                except Exception:
                    pass
                return

        # [R7-β post-test v3] _refused_help_until 现在对所有 nudge_type 生效
        # —— Sir 说"不需要你的帮助"之后，Check-in / Suggest Break / Late Night 等
        # 也都不该再蹦出来；只有 return_greeting（AFK 归来）由 NudgeGate.SLEEP_ALLOWED_TYPES 兜底
        # [P0+20-β.2.4 hotfix / 2026-05-16] worker.jarvis.X 伪失效守卫修复
        from jarvis_utils import resolve_worker_attr as _rwa
        cc = _rwa(self.worker, 'companion_center')
        if cc is not None:
            if hasattr(cc, 'smart_nudge') and cc.smart_nudge:
                sn = cc.smart_nudge
                if time.time() < sn._refused_help_until and nudge_type != 'return_greeting':
                    try:
                        from jarvis_utils import bg_log
                        remaining = int(sn._refused_help_until - time.time())
                        bg_log(f"🚫 [Conductor/RefusalRespect] 用户拒绝期内，跳过 {nudge_type}（剩 {remaining}s）")
                    except Exception:
                        pass
                    return

        if nudge_type == 'offer_help':
            cc = _rwa(self.worker, 'companion_center')
            if cc is not None:
                if hasattr(cc, 'smart_nudge') and cc.smart_nudge:
                    sn = cc.smart_nudge
                    _win_title = ""
                    try:
                        import win32gui
                        _hwnd = win32gui.GetForegroundWindow()
                        _win_title = win32gui.GetWindowText(_hwnd) if _hwnd else ""
                    except:
                        pass
                    fingerprint = sn._gen_help_fingerprint({
                        'window_title': _win_title,
                        'category': 'error'
                    })
                    dynamic_cooldown = sn._calc_help_cooldown(fingerprint)
                    if dynamic_cooldown > 0:
                        remaining = dynamic_cooldown - (time.time() - sn._last_help_fingerprint_time)
                        if remaining > 0:
                            return
                    sn._last_help_fingerprint = fingerprint
                    sn._last_help_fingerprint_time = time.time()
        
        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')
        snapshot = filter_result.get('snapshot', {})
        work_category = PhysicalEnvironmentProbe.current_work_category
        work_duration = PhysicalEnvironmentProbe.work_duration_minutes
        window_title = ""
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            window_title = win32gui.GetWindowText(hwnd) if hwnd else ""
        except:
            pass
        
        sensor_summary = (
            f"窗口: {window_title[:80]} | "
            f"类别: {work_category} | "
            f"会话时长: {int(work_duration)}分钟 | "
            f"按键/5min: {snapshot.get('key_press_count_5min', 0)} | "
            f"退格率: {snapshot.get('backspace_ratio', 0):.2%} | "
            f"切换/5min: {snapshot.get('switch_frequency_5min', 0)} | "
            f"空闲: {snapshot.get('idle_seconds', 0)}s | "
            f"深夜: {snapshot.get('is_night_time', False)} | "
            f"报错: {snapshot.get('error_visible', False)}"
        )
        
        conductor_message = (
            f"调度中心内部通知：传感器漏斗检测到异常。"
            f"触发原因：{filter_result.get('reason', '')}。"
            f"决策LLM判断：{decision.get('decision_reason', '')}。"
            f"当前时间：{current_time}。"
            f"传感器摘要：[{sensor_summary}]。"
            f"融合分趋势：{filter_result.get('fusion_trend', '')}。"
            f"请根据以上上下文，以自然的语气主动对先生说一句话。"
            f"语气要求：{decision.get('tone', 'gentle')}。"
            f"不要说我通知你的，就像你自己注意到的一样自然地说出来。"
        )
        
        nudge_context = {
            "type": nudge_type,
            "recent_topics": [],
            "conductor_message": conductor_message,
            "conductor_action": decision.get('action', 'Check-in'),
            "conductor_reason": filter_result.get('reason', ''),
            "session_duration": snapshot.get('session_duration_minutes', 0),
            "error_visible": snapshot.get('error_visible', False),
            "switch_frequency": snapshot.get('switch_frequency_5min', 0),
            "category_entropy": snapshot.get('category_entropy', 0),
        }
        
        cmd = f"__NUDGE__:{json.dumps(nudge_context, ensure_ascii=False)}"
        self.worker.push_command(cmd)
        if self.gate:
            self.gate.mark_spoke('guardian')
        
        self._last_action_time = time.time()
        self._daily_action_count += 1
        self._action_history.append({
            'time': time.strftime('%H:%M:%S'),
            'action': decision.get('action', 'Check-in'),
            'reason': filter_result.get('reason', ''),
            'confidence': decision.get('confidence', 0.7)
        })
        # [P0+18-b.3 / 2026-05-15] 改 bg_log：主对话框不再被这条诊断行干扰
        try:
            from jarvis_utils import bg_log
            bg_log(f"[Conductor] 路径B触发: 漏斗检测 → {decision.get('action', 'Check-in')} → 已发送 __NUDGE__")
        except Exception:
            print(f"[Conductor] 路径B触发: 漏斗检测 → {decision.get('action', 'Check-in')} → 已发送 __NUDGE__")
    
    def _rule_decision(self, snapshot: dict, fusion_score: float) -> dict:
        """[P1] 旧 API 兼容封装：从 snapshot + fusion_score 给出基于规则的决策。
        现路径 A/B 已经把这套规则拆到 `_check_path_a` 和决策 LLM；此处只为旧测试和外部脚本
        提供"先看一眼有没有要 Offer Help"的快速判断。
        """
        try:
            error_visible = bool(snapshot.get('error_visible', False))
            audio_playing = bool(snapshot.get('audio_playing', False))
            video_editor = bool(snapshot.get('video_editor', False))
            shield_alert = snapshot.get('shield_alert') or {}
            wellness_alert = snapshot.get('wellness_alert') or {}
            current_hour = snapshot.get('current_hour', 12)
            afk_minutes = snapshot.get('afk_minutes', 0)
            # [C1-5 / 2026-05-15] companion_alert 分支死代码清扫：
            # PhysicalEnvironmentProbe._companion_alert 永远是 {'active': False}
            # （ProactiveCompanion 全工程零实例化，没人会写这个字段），
            # 这条分支永远走不到。删除避免 confusion；后续若真要复活伴侣告警
            # 需要先重新接通 ProactiveCompanion 的 setter。

            if shield_alert.get('active'):
                return {
                    'action': 'Offer Help',
                    'reason': f"shield_alert:{shield_alert.get('type','unknown')}",
                    'confidence': 0.9,
                    'message_tone': 'gentle',
                }
            if wellness_alert.get('active'):
                return {
                    'action': 'Suggest Break',
                    'reason': f"wellness_alert:{wellness_alert.get('reason','health')}",
                    'confidence': 0.85,
                    'message_tone': 'gentle',
                }
            if error_visible and not audio_playing and not video_editor:
                return {
                    'action': 'Offer Help',
                    'reason': 'error_visible_on_screen',
                    'confidence': 0.75,
                    'message_tone': 'gentle',
                }
            if current_hour >= 23 or current_hour < 2:
                if afk_minutes < 5:
                    return {
                        'action': 'Warn Late Night',
                        'reason': 'late_night_still_active',
                        'confidence': 0.7,
                        'message_tone': 'gentle',
                    }
            return {
                'action': 'None',
                'reason': 'no_rule_matched',
                'confidence': 0.0,
                'message_tone': 'casual',
            }
        except Exception as e:
            return {
                'action': 'None',
                'reason': f'rule_decision_error:{e}',
                'confidence': 0.0,
                'message_tone': 'casual',
            }

    def _dispatch_to_jarvis(self, decision: dict, snapshot: dict) -> bool:
        """[P1] 旧 API 兼容封装：把 decision 翻译成 __NUDGE__ 命令推给 worker，过 gate 决定是否真发。

        urgent 规则：action == 'Offer Help' 或 confidence ≥ 0.9 视为紧急（绕过 gate 跨中心冷却）。
        其它情况按 'guardian' 中心的 can_speak 走。返回是否真的派发。
        """
        if not decision or decision.get('action', 'None') == 'None':
            return False
        action = decision.get('action', 'None')
        nudge_type = self._nudge_type_map.get(action, 'offer_help')
        confidence = float(decision.get('confidence', 0.5) or 0.5)
        is_urgent = (action == 'Offer Help') or (confidence >= 0.9)

        if self.gate is not None:
            try:
                if not self.gate.can_speak('guardian',
                                           is_urgent=is_urgent,
                                           nudge_type=nudge_type):
                    return False
            except Exception:
                pass

        conductor_message = (
            f"调度中心内部通知：{action}。"
            f"触发原因：{decision.get('reason', '')}。"
            f"语气要求：{decision.get('message_tone', 'gentle')}。"
            f"请根据以上上下文，以自然的语气主动对先生说一句话。"
            f"不要说我通知你的，就像你自己注意到的一样自然地说出来。"
        )
        nudge_context = {
            "type": nudge_type,
            "recent_topics": [],
            "conductor_message": conductor_message,
            "conductor_action": action,
            "conductor_reason": decision.get('reason', ''),
            "session_duration": (snapshot or {}).get('session_duration_minutes', 0),
            "error_visible": (snapshot or {}).get('error_visible', False),
            "switch_frequency": (snapshot or {}).get('switch_frequency_5min', 0),
            "category_entropy": (snapshot or {}).get('category_entropy', 0),
        }
        try:
            cmd = f"__NUDGE__:{json.dumps(nudge_context, ensure_ascii=False)}"
        except Exception:
            cmd = "__NUDGE__:{}"
        try:
            self.worker.push_command(cmd)
        except Exception:
            return False
        if self.gate is not None:
            try:
                self.gate.mark_spoke('guardian')
            except Exception:
                pass
        self._last_action_time = time.time()
        self._daily_action_count += 1
        self._action_history.append({
            'time': time.strftime('%H:%M:%S'),
            'action': action,
            'reason': decision.get('reason', ''),
            'confidence': confidence,
        })
        return True

    def _decision_llm(self, filter_result: dict) -> dict:
        import json as _json, re, base64
        try:
            deviation_report = filter_result.get('deviation_report', {})
            deviations = deviation_report.get('deviations', [])
            
            deviation_lines = []
            for d in deviations:
                if d.get('direction') == '状态翻转':
                    deviation_lines.append(f"· {d['label']}: {d['baseline_state']} → 当前为{d['current']}")
                else:
                    deviation_lines.append(
                        f"· {d['label']}: {d['baseline_mean']} → {d['current']} "
                        f"(z={d['z_score']}, {d['direction']})"
                    )
            deviation_text = "\n".join(deviation_lines) if deviation_lines else "无详细偏离数据"
            
            semantic_info = ""
            if not filter_result.get('bypass_semantic'):
                sj = filter_result.get('semantic_judgment', {})
                semantic_info = f"\n语义门判断: {sj.get('reason', '')}"
            
            ledger_text = "暂无"
            if hasattr(self.worker, 'status_ledger'):
                try:
                    ledger = self.worker.status_ledger.get_instant_ledger()
                    ledger_text = _json.dumps(ledger, ensure_ascii=False)
                except:
                    pass
            
            screenshot_b64 = None
            if self._screenshot_sentinel:
                screenshot_b64 = self._screenshot_sentinel.capture_on_demand()
            
            bypass_semantic = filter_result.get('bypass_semantic', False)
            funnel_context = ""
            if bypass_semantic:
                funnel_context = (
                    "第一层统计门检测到极端偏离(z>3.0)，已跳过第二层语义门，直接送达你这里。"
                    "这意味着传感器数据出现了罕见的剧烈波动，但未必等于用户真的需要帮助——"
                    "可能是用户切换了任务、短暂离开、或系统自身波动。你需要用截图来验证。"
                )
            else:
                funnel_context = (
                    "第一层统计门检测到显著偏离，第二层语义门已确认这些偏离'值得关注'。"
                    "两轮筛选后送达你这里，说明传感器+语义双重确认有异常。"
                    "但最终判断权在你——结合截图确认是否真的需要干预。"
                )

            prompt = f"""你是贾维斯的三层漏斗的最终决策层。

=== 漏斗架构 ===
第一层(统计门/z-score)：滚动基线检测传感器偏离，过滤掉正常波动。
第二层(语义门)：判断偏离组合是否'值得关注'，过滤掉无意义的数值变化。
第三层(你/决策LLM)：结合截图+用户状态，做最终的是否发声判决。

=== 本轮漏斗路径 ===
{funnel_context}

=== 传感器偏离报告 ===
{deviation_text}
{semantic_info}

=== 融合分趋势 ===
当前融合分: {filter_result.get('fusion_score', 0)}
历史趋势: {filter_result.get('fusion_trend', '')}

=== 用户状态档案 ===
{ledger_text}

=== 决策指南 ===
1. 截图是最高优先级的真相来源。如果截图显示用户正常工作中(写代码/聊天/浏览)，偏离可能只是任务切换——判 NO。
2. 如果截图显示报错、卡住、反复修改同一内容、或异常行为——判 YES。
3. 用户状态档案中的 emotional_tone 和 detected_stress_signals 作为辅助参考。
4. 置信度<0.7 一律判 NO。不确定时判 NO。宁可漏报不要误报。

可用动作: 'None', 'Check-in', 'Offer Help', 'Suggest Break', 'Warn Late Night', 'Context Switch Alert'
语气: casual/formal/gentle/urgent/playful

输出严格JSON:
{{"should_speak": true/false, "action": "动作名", "decision_reason": "简短原因", "confidence": 0.0-1.0, "tone": "语气", "nudge_type": "offer_help/suggest_break/late_night/context_switch_alert/check_in/atmosphere"}}"""
# [P0-8 / 2026-05-15] nudge_type 列表里去掉 return_greeting（那是 ReturnSentinel 的专属类型，
# Conductor 决策 LLM 不应自己挑这个）；加上 check_in 对应 Check-in 动作。
            
            key_router = getattr(self.worker, 'key_router', None)
            if not key_router and hasattr(self.worker, 'jarvis'):
                key_router = getattr(self.worker.jarvis, 'key_router', None)
            
            def _call_decision(client):
                contents = [types.Part(text=prompt)]
                if screenshot_b64:
                    img_bytes = base64.b64decode(screenshot_b64)
                    contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
                return client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=contents
                )
            
            res, _key_name, _client = safe_gemini_call(
                key_router, KeyRouter.CALLER_SENTINEL, 'flash_lite', _call_decision,
                max_retries=2, base_delay=1.0,
                model_name='gemini-3.1-flash-lite', contents_text=prompt
            )
            key_router.release(_key_name)
            
            raw_text = res.text.strip()
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                decision = _json.loads(match.group(0))
                FunnelLogger().log_layer3_decision(filter_result, decision, prompt)
                if decision.get('confidence', 0) < 0.7:
                    decision['should_speak'] = False
                return decision
        except Exception as e:
            print(f"[Conductor] 决策LLM异常: {e}")
        
        return {"should_speak": False, "reason": "决策LLM失败"}
    
    def get_state_archive(self, minutes: int = 10) -> list:
        cutoff = time.time() - minutes * 60
        return [s for s in self._state_archive if s['time'] >= cutoff]
    
    def get_latest_summary(self) -> str:
        archive = self.get_state_archive(10)
        if not archive:
            return "[状态数据采集中...]"
        
        latest = archive[-1]['snapshot']
        fusion = archive[-1]['fusion_score']
        
        lines = []
        lines.append(f"窗口: {latest.get('window_title', '')[:60]}")
        lines.append(f"类别: {latest.get('work_category', '')} | 停留: {latest.get('window_stay_seconds', 0)}s")
        lines.append(f"键盘: {latest.get('key_press_count_5min', 0)}次/5min | 退格率: {latest.get('backspace_ratio', 0):.2%}")
        lines.append(f"鼠标: {latest.get('mouse_distance_5min', 0)}px | 点击: {latest.get('click_count_5min', 0)}次/5min")
        lines.append(f"会话: {latest.get('session_duration_minutes', 0)}min | 空闲: {latest.get('idle_seconds', 0)}s")
        lines.append(f"后台: 干扰进程{latest.get('background_distraction_count', 0)}个 | 微信未读: {latest.get('wechat_has_unread', False)}")
        lines.append(f"融合异常分: {fusion:.4f} | 深夜: {latest.get('is_night_time', False)}")
        return "\n".join(lines)
    
    def record_implicit_feedback(self, user_response_type: str):
        if not self._action_history:
            return
        
        feedback_map = {
            'positive_reply': 1.0,
            'neutral_reply': 0.3,
            'negative_reply': -0.5,
            'ignored': -0.3,
            'dismissed': -0.8,
        }
        feedback = feedback_map.get(user_response_type, 0.0)
        
        snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
        if not snapshot:
            return
        
        numeric_sensors = [
            'switch_frequency_5min', 'window_stay_seconds', 'category_entropy',
            'key_press_count_5min', 'backspace_ratio', 'burst_pause_ratio',
            'mouse_distance_5min', 'click_count_5min', 'idle_seconds',
            'session_duration_minutes', 'background_distraction_count',
        ]
        
        for sensor in numeric_sensors:
            value = snapshot.get(sensor, 0)
            z = PhysicalEnvironmentProbe.compute_zscore(sensor, value)
            PhysicalEnvironmentProbe.update_sensor_weight(sensor, feedback, z)
        
        binary_sensors_map = {
            'is_night': snapshot.get('is_night_time', False),
            'is_first_active': snapshot.get('is_first_active_today', False),
            'wechat_unread': snapshot.get('wechat_has_unread', False),
            'audio_playing': snapshot.get('audio_playing', False),
            'video_editor': snapshot.get('video_editor_open', False),
            'error_visible': snapshot.get('error_visible', False),
        }
        for name, value in binary_sensors_map.items():
            surprise = 1.0 if value else 0.0
            PhysicalEnvironmentProbe.update_sensor_weight(name, feedback, surprise)
        
        print(f"[Conductor] 隐式反馈学习: {user_response_type} → 权重已更新 (feedback: {feedback})")


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

