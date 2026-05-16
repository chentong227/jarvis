# -*- coding: utf-8 -*-
"""[P0+19-6.a / 2026-05-16] Jarvis Sentinels — 9 个普通守护线程

从 jarvis_nerve.py 拆出（不含 Conductor / ReturnSentinel / CommitmentWatcher /
SmartNudgeSentinel，这 4 个独立文件 P0+19-6.b-e）：

| Class                        | 用途                                           |
|------------------------------|------------------------------------------------|
| ChronosTick                  | 心脏起搏器（融合 mailbox + 三级递进提醒）       |
| ChronosSentinel              | Chronos 监督守护                                |
| SystemSentinel               | 系统层监控（CPU/内存/IO 异常 → bg_log warning） |
| SoulArchivistSentinel        | 灵魂画像提纯（flash-lite 长时记忆）              |
| NudgeGate                    | Nudge 门（冷却 / 频次 / type-mute / hard-freeze）|
| UserStatusLedgerSentinel     | 用户状态台账 (gemini-flash-lite 标注)            |
| ScreenshotSentinel           | 屏幕截图定时（视觉上下文输入）                    |
| WellnessGuardian             | 生理节律监控（连续工作时长 → 建议休息）            |
| ReflectionScheduler          | LLM 反思调度（flash-lite/flash）                  |

依赖：
- 标准库：time / threading / queue / collections / re / json / random
- jarvis_env_probe.PhysicalEnvironmentProbe (传感器读取)
- jarvis_sensors (HabitClock / SensorFilter 等)
- jarvis_utils.bg_log (延迟 import)
- jarvis_llm_reflector.LlmReflector (延迟 import)
- jarvis_safety._is_xxx (延迟 import, 部分 sentinel 用)
- jarvis_hippocampus.Hippocampus (延迟 import, SoulArchivist 用)

向后兼容：转发垫层保持 `from jarvis_nerve import NudgeGate / ChronosTick / ...` 0 改动。
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

# 跨文件类引用（顶部 import — 这些都已拆完）
from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
# [P0+19-final fix 2]
from google.genai import types  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401  # noqa: F401

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


from jarvis_sensors import SubconsciousMailbox, CausalChain, HabitClock, FunnelLogger, SensorFilter  # noqa: F401

__all__ = [
    'ChronosTick',
    'ChronosSentinel',
    'SystemSentinel',
    'SoulArchivistSentinel',
    'NudgeGate',
    'UserStatusLedgerSentinel',
    'ScreenshotSentinel',
    'WellnessGuardian',
    'ReflectionScheduler',
]


# ============================================================================
# A. 心跳 / 守护 / 灵魂画像 / 门 (ChronosTick + ChronosSentinel + SystemSentinel
#    + SoulArchivistSentinel + NudgeGate)
# ============================================================================

class ChronosTick(threading.Thread):
    """心脏起搏器：融合信箱、三级递进提醒与探针的裁决者"""
    def __init__(self, mailbox: SubconsciousMailbox, chat_bypass: 'ChatBypass', ui_callback, jarvis):
        super().__init__(daemon=True)
        self.mailbox = mailbox
        self.chat_bypass = chat_bypass
        self.ui_callback = ui_callback
        self.jarvis = jarvis
        self.jarvis._pending_reminders = {}

    def _user_responded_since(self, since_time: float) -> bool:
        if hasattr(self.jarvis, 'voice_thread'):
            return self.jarvis.voice_thread.last_user_speech_time > since_time
        return False

    def _speak_mail(self, mail: dict):
        """统一的语音播报入口"""
        self.ui_callback("THINKING")
        set_browser_ducking(True)
        
        current_hour = int(time.strftime("%H"))
        is_late_night = current_hour >= 23 or current_hour < 6
        
        tone_override = mail.get("tone_override", "")
        if tone_override:
            tone_prompt = tone_override
        elif mail["priority"] == "URGENT":
            tone_prompt = "This is an URGENT system alert. Speak directly, confidently, but keep it professional."
        elif is_late_night:
            tone_prompt = "It is late at night. You MUST use an EXTREMELY gentle, soft, whispering, and caring tone. Be brief so as not to startle Sir."
        else:
            tone_prompt = "Speak proactively and elegantly as my butler to inform me of this update."

        pseudo_input = f"[SYSTEM BACKGROUND EVENT]: {mail['content']}\n[DIRECTIVE]: Act autonomously and inform Sir about this event. {tone_prompt} Do NOT wait for my prompt. Do NOT use <START_ROUTING>."
        
        stm_context = "\n".join([f"[{m.get('time', '')}] {m['user']} -> {m['jarvis']}" for m in self.jarvis.short_term_memory[-6:]])
        if len(stm_context) > 2000:
            stm_context = "..." + stm_context[-2000:]
        ltm_context = getattr(self.chat_bypass, 'last_ltm_context', 'None')
        chat_organs = ", ".join(self.jarvis.hand_manifests.keys())
        
        print(f"\n[Reminder] Detected pending reminders, reporting...")
        
        prompt = self.jarvis._assemble_prompt(
            user_input=pseudo_input,
            stm_context=stm_context,
            ltm_context=ltm_context,
            chat_organs=chat_organs,
            mode="mail"
        )
        
        if hasattr(self, 'voice_thread') and self.voice_thread:
            self.voice_thread._suppress_wave = True
        _, jarvis_reply = self.chat_bypass.stream_chat(
            prompt=prompt,
            user_input=pseudo_input,
            clean_intent="[后台系统异步唤醒]",
            stm_context=stm_context,
            ltm_context=ltm_context
        )
        if hasattr(self, 'voice_thread') and self.voice_thread:
            self.voice_thread._suppress_wave = False
        
        if jarvis_reply:
            clean_reply = jarvis_reply.split("---ZH---")[0].strip()
            self.jarvis.short_term_memory.append({
                "time": time.strftime("%H:%M:%S"),
                "user": f"[系统事件] {mail['content']}",
                "jarvis": clean_reply
            })
            if len(self.jarvis.short_term_memory) > 10: 
                self.jarvis.short_term_memory.pop(0)
            
            print(f" └─ [System] 主动提醒已同步至海马体。")
            self.jarvis.hippocampus.seal_chat_async(
                self.jarvis.gemini_key, 
                f"[系统主动提醒]: {mail['content']}", 
                clean_reply, 
                memory_protocol={"memory_type": "REMINDER"}
            )
        
        if hasattr(self.jarvis, 'focus_callback'):
            self.jarvis.focus_callback()
            
        self.ui_callback("IDLE")
        import threading as _thr
        _thr.Thread(target=lambda: (time.sleep(3), set_browser_ducking(False)), daemon=True).start()
        return jarvis_reply

    def _check_escalations(self):
        """检查待处理提醒是否需要递进升级"""
        now = time.time()
        consumed_ids = []
        
        for mem_id, state in list(self.jarvis._pending_reminders.items()):
            elapsed = now - state['last_spoke']
            
            if self._user_responded_since(state['last_spoke']):
                self.jarvis.hippocampus.consume_reminder(mem_id)
                consumed_ids.append(mem_id)
                print(f"\n[Reminder] 用户已确认，消费提醒 ID:{mem_id} '{state['intent']}'")
                continue
            
            if state['tier'] == 1 and elapsed > 180:
                self._escalate_reminder(mem_id, state, 2)
            elif state['tier'] == 2 and elapsed > 180:
                self._escalate_reminder(mem_id, state, 3)
            elif state['tier'] == 3 and elapsed > 180:
                self._finalize_reminder(mem_id, state)
                consumed_ids.append(mem_id)
        
        for mid in consumed_ids:
            del self.jarvis._pending_reminders[mid]

    def _escalate_reminder(self, mem_id: int, state: dict, new_tier: int):
        """递进提醒等级，重新投递到信箱"""
        tier_tones = {
            2: "This is your SECOND reminder attempt. Sir may not have heard you. Use a slightly more concerned and insistent tone. Briefly mention WHY this reminder matters if context is available. Keep it under 15 words.",
            3: "This is your FINAL reminder attempt. Sir has not responded to two previous calls. Use a firm but still respectful and caring tone. Make it clear that time is of the essence. Keep it under 15 words."
        }
        tier_labels = {2: "Second", 3: "Final"}
        
        state['tier'] = new_tier
        state['last_spoke'] = time.time()
        
        # [P0+18-c.2 / 2026-05-15] 修 Sir 主诉：触发文案让 LLM 把"执行提醒"误读为"询问要不要安排"
        # 旧文案 "it is time to trigger the following reminder" 配合用户原话 "提醒我两分钟后喝水"
        # 让 LLM 回 "您曾要求...需要为您设置倒计时吗?" — 时间语义被完全 invert。
        # 新文案强调"倒计时已耗尽 / 立刻执行 / 不要再问 / extract 动作直接说"。
        content = (
            f"[REMINDER FIRING NOW — TIME HAS ALREADY ELAPSED]\n"
            f"Sir's original request was: '{state['intent']}'.\n"
            f"The countdown is OVER. The wait period has finished. "
            f"You must DELIVER this reminder to Sir IN THIS MOMENT, as if a kitchen timer just rang. "
            f"Extract the actual action from the request (the part after the time anchor) "
            f"and tell Sir directly in short, present-tense imperative."
        )
        self.mailbox.deliver(
            "URGENT" if new_tier >= 3 else "NORMAL",
            content,
            tone_override=tier_tones[new_tier]
        )
        print(f"\n[Reminder] ID:{mem_id} escalated to Tier {new_tier}/3 ({tier_labels[new_tier]} attempt) '{state['intent']}'")

    def _finalize_reminder(self, mem_id: int, state: dict):
        """最终兜底：消费提醒 + STM留痕供后续对话引用"""
        self.jarvis.hippocampus.consume_reminder(mem_id)
        
        trigger_time_str = time.strftime("%H:%M", time.localtime(state['trigger_time']))
        self.jarvis.short_term_memory.append({
            "time": time.strftime("%H:%M:%S"),
            "user": f"[未确认提醒] {trigger_time_str} - {state['intent']}",
            "jarvis": "[系统] 提醒已过期，用户未响应。"
        })
        if len(self.jarvis.short_term_memory) > 10:
            self.jarvis.short_term_memory.pop(0)
        
        print(f"\n[Reminder] ID:{mem_id} '{state['intent']}' 3次未确认已归档，记录至STM。")


    def _smart_interrupt_decision(self, score: int, highest_priority: str) -> tuple:
        """P3 智能打断决策引擎：融合情绪 + 工时 + 阻力值 + 时段，输出 (should_speak, reason)"""
        if highest_priority == "URGENT":
            return True, "URGENT_PRIORITY"
        
        work_duration = PhysicalEnvironmentProbe.work_duration_minutes
        work_category = PhysicalEnvironmentProbe.current_work_category
        current_hour = int(time.strftime("%H"))
        
        ledger = {}
        if hasattr(self.jarvis, 'status_ledger'):
            ledger = self.jarvis.status_ledger.get_instant_ledger()
        
        emotional_tone = ledger.get("emotional_tone", "Neutral")
        stress_signals = ledger.get("detected_stress_signals", [])
        
        threshold = 30
        
        if emotional_tone in ("Frustrated", "Stressed"):
            threshold += 25
        if stress_signals and len(stress_signals) >= 2:
            threshold += 15
        if work_category == "Coding" and work_duration > 60:
            threshold += 20
        if work_duration > 180:
            threshold += 15
        if current_hour >= 23 or current_hour < 7:
            threshold += 10
        
        if score < threshold:
            return True, f"SCORE_OK({score}<{threshold})"
        else:
            return False, f"SCORE_HIGH({score}>={threshold})"

    def run(self):
        _last_openrouter_check = 0
        while True:
            time.sleep(8) 
            
            self._check_escalations()
            
            if time.time() - _last_openrouter_check > 300:
                _last_openrouter_check = time.time()
                if hasattr(self.jarvis, 'key_router') and self.jarvis.key_router:
                    alert = self.jarvis.key_router.get_openrouter_alert()
                    if alert:
                        print(f"\n{'='*65}")
                        print(f"💳 {alert}")
                        print(f"{'='*65}\n")
                        self.jarvis.short_term_memory.append({
                            "time": time.strftime("%H:%M:%S"),
                            "user": "[SYSTEM ALERT] OpenRouter fallback active",
                            "jarvis": alert
                        })
                        if len(self.jarvis.short_term_memory) > 10:
                            self.jarvis.short_term_memory.pop(0)
            
            if self.mailbox.has_mail():
                score = PhysicalEnvironmentProbe.get_interruptibility_score()
                highest_priority = self.mailbox.peek_highest_priority()
                
                should_speak, reason = self._smart_interrupt_decision(score, highest_priority)
                
                if should_speak:
                    mail = self.mailbox.pop_mail()
                    if mail:
                        reminder_id = mail.get("reminder_id")
                        self._speak_mail(mail)
                        
                        if reminder_id:
                            self.jarvis._pending_reminders[reminder_id] = {
                                "tier": 1,
                                "last_spoke": time.time(),
                                "intent": mail.get("reminder_intent", ""),
                                "trigger_time": mail.get("reminder_trigger_time", 0)
                            }
                            print(f"\n[Reminder] ID:{reminder_id} 已注册三级升级监控 '{mail.get('reminder_intent', '')}'")
                else:
                    self.ui_callback("MAIL_PENDING")

class ChronosSentinel(threading.Thread):
    """时间唤醒哨兵：盯着海马体里的'未来记忆'"""
    def __init__(self, mailbox, hippocampus, jarvis=None):
        super().__init__(daemon=True)
        self.mailbox = mailbox
        self.hippocampus = hippocampus
        self.jarvis = jarvis

    def run(self):
        time.sleep(10) # 延迟启动，避开开机高峰
        while True:
            try:
                current_ts = time.time()
                # 呼叫海马体获取并消费到点的提醒
                reminders = self.hippocampus.fetch_due_reminders(current_ts)
                
                for r in reminders:
                    intent = r['intent']
                    if self.jarvis and r['id'] in getattr(self.jarvis, '_pending_reminders', {}):
                        continue
                    # [P0+18-c.2 / 2026-05-15] 同 _escalate_reminder：触发文案改成"FIRING NOW"
                    # 不再用"it is time to trigger the following reminder" 让 LLM 误读
                    content = (
                        f"[REMINDER FIRING NOW — TIME HAS ALREADY ELAPSED]\n"
                        f"Sir's original request was: '{intent}'.\n"
                        f"The countdown is OVER. The wait period has finished. "
                        f"You must DELIVER this reminder to Sir IN THIS MOMENT, as if a kitchen timer just rang. "
                        f"Extract the actual action from the request (the part after the time anchor) "
                        f"and tell Sir directly in short, present-tense imperative."
                    )
                    self.mailbox.deliver(
                        "NORMAL",
                        content,
                        reminder_id=r['id'],
                        reminder_intent=intent,
                        reminder_trigger_time=r['trigger_time']
                    )
                    
            except Exception as e:
                pass 
                
            time.sleep(30) # 哨兵每 30 秒核对一次生物钟
                                
class SystemSentinel(threading.Thread):
    """物理系统监控哨兵：盯着电量、硬盘和导出任务"""
    def __init__(self, mailbox):
        super().__init__(daemon=True)
        self.mailbox = mailbox
        self.last_disk_warning = 0
        self.last_export_warning = 0
        
        # 💡 哨兵拿起了刚刚造好的器官
        from l4_hands_pool.monitor_hands import Hands as MonitorHands
        self.monitor = MonitorHands()

    def run(self):
        # 延迟启动，避免系统刚开机时资源抢占
        time.sleep(15) 
        while True:
            try:
                # 1. S级警报：监控 C 盘硬盘爆满 (调用器官)
                # 构造一个假 Action 让器官执行
                from jarvis_blood import Action 
                disk_res = self.monitor.execute(Action(command="check_disk_space", params={"drive": "D:"}))
                if disk_res.success and disk_res.data:
                    if disk_res.data["percent"] > 95 and (time.time() - self.last_disk_warning > 3600):
                        # 👇 替换为英文通知
                        self.mailbox.deliver("URGENT", f"The video drive (D:) is critically full. {disk_res.msg}. Please clean it up immediately to prevent export/recording crashes.")
                        self.last_disk_warning = time.time()

                # 2. A级提醒：监控 Adobe Media Encoder 导出状态 (假定导出目录在 D:\Export)
                # 注意：您需要把这里的 D:\\Export 换成您实际常用的视频导出路径
                export_res = self.monitor.execute(Action(command="check_ame_export", params={"folder_path": "D:\桌面\录屏\2024.11.01"}))
                if export_res.success and export_res.data:
                    if not export_res.data["is_exporting"] and self.last_export_warning != 0:
                        # 👇 替换为英文通知
                        self.mailbox.deliver("NORMAL", f"Sir, the background video rendering appears to be complete. There are currently {export_res.data['mp4_count']} finished files in the export folder.")
                        self.last_export_warning = 0 
                    elif export_res.data["is_exporting"]:
                        self.last_export_warning = 1

            except Exception as e:
                pass # 哨兵的原则：绝不因为自身报错导致主程序崩溃
            
            # 哨兵每 60 秒巡逻一圈
            time.sleep(60)

# ==========================================
# 📍 修改目标位置: jarvis_nerve.py (替换整个 VisualSentinel 类)
# ==========================================
# ==========================================
# 📍 修改目标位置: jarvis_nerve.py (完全替换原有的 VisualSentinel 类)
# ==========================================
# ==========================================
# 📍 插入位置: jarvis_nerve.py (放在 UserStatusLedgerSentinel 类的下方)
# ==========================================
# ==========================================
# 📍 替换目标: jarvis_nerve.py (完全替换 SoulArchivistSentinel 类)
# ==========================================
class SoulArchivistSentinel(threading.Thread):
    """L2 潜意识守护者：在挂机时提纯短期记忆，沉淀为灵魂画像"""
    def __init__(self, key_router, central_nerve):
        super().__init__(daemon=True)
        self.key_router = key_router
        self.model_name = 'gemini-3.1-flash-lite'
        self.jarvis = central_nerve
        
        self.profile_dir = "jarvis_config"
        self.profile_file = os.path.join(self.profile_dir, "sir_profile.json")
        if not os.path.exists(self.profile_dir):
            os.makedirs(self.profile_dir)
            
        self.last_update_time = time.time()
        # 👇 核心新增：记录初始启动时的小时数
        self.last_update_hour = time.localtime(self.last_update_time).tm_hour
        self.is_updating = False
        self.last_processed_chats = ""

    def _load_profile(self):
        import os, json
        if os.path.exists(self.profile_file):
            try:
                with open(self.profile_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {
          "core_philosophy": "A practical software developer who values clean, efficient code. Dislikes over-engineered solutions and pretentious technical jargon.",
          "idiosyncrasies": "Pays attention to UI details. Occasionally mixes Chinese and English when speaking. Uses voice input extensively.",
          "significant_milestones": ["Built and deployed the J.A.R.V.I.S. personal assistant system."],
          "our_inside_jokes": [],
          "conversational_boundaries": "Dislikes forced humor and sycophantic behavior. Prefers direct, professional responses. Accepts occasional dry wit when natural.",
          "active_projects": [],
          "skill_domains": [],
          "work_rhythms": "Insufficient data to determine patterns yet.",
          "skill_progression": []
        }
    def _save_profile(self, profile_data):
        import json
        with open(self.profile_file, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=2)

    def run(self):
        import time, json, re
        time.sleep(20) 
        print("[SoulArchivist] 潜意识归档引擎就绪 (每小时触发模式)...")
        
        while True:
            time.sleep(60)
            
            current_hour = time.localtime(time.time()).tm_hour
            if current_hour == self.last_update_hour:
                continue
            if self.is_updating:
                continue
                
            self.is_updating = True
            try:
                current_profile = self._load_profile()
                
                recent_chats = "\n".join([f"[{m.get('time', '')}] {m['user']} -> {m['jarvis']}" for m in self.jarvis.short_term_memory[-20:]])
                if not recent_chats or recent_chats == self.last_processed_chats:
                    self.last_update_hour = current_hour
                    self.is_updating = False
                    continue
                
                current_hour_str = time.strftime('%H:%M')
                current_weekday = time.strftime('%A')
                
                ledger_snapshot = "No ledger data available."
                if hasattr(self.jarvis, 'status_ledger'):
                    ledger_snapshot = json.dumps(self.jarvis.status_ledger.get_instant_ledger(), ensure_ascii=False)
                
                physical_state = PhysicalEnvironmentProbe.current_physical_state
                work_category = PhysicalEnvironmentProbe.current_work_category
                work_duration = PhysicalEnvironmentProbe.work_duration_minutes
                
                # [P0+20-β.2.4.4 / 2026-05-16] 老路径退役第 4 步：
                # 不再写 our_inside_jokes / significant_milestones 到 sir_profile。
                # 改成输出 proposed_inside_jokes / proposed_shared_history_threads，
                # 由本类提取后调 relational_state.propose_* 走 Sir review queue。
                # 详 docs/JARVIS_SOUL_DRIVE.md
                prompt = f"""[ROLE]
You are the Subconscious Archivist of J.A.R.V.I.S. Your purpose is to understand Sir by analyzing recent conversation logs and updating his profile with factual, natural-language observations.

[CRITICAL RULES]
1. PRESERVATION OVER COMPRESSION: Do NOT delete existing traits unless they are factually contradicted. Your job is to APPEND and REFINE.
2. USE NATURAL, HUMAN LANGUAGE: Describe Sir as a normal person. NEVER use pretentious jargon like "geek", "nerve system", "architectural surge", "zero-delay", "biological efficiency", "codifying", "surge", or any similar technical metaphors to describe a human being.
3. BE FACTUAL, NOT DRAMATIC: Sir is a software developer who codes, watches racing, edits videos, and is learning to drive. Describe these activities plainly. Do not romanticize them.
4. DO NOT INVENT TRAITS: Only record what is actually observed in the logs. Do not extrapolate a "persona" from limited data.
5. DO NOT CREATE SELF-FULFILLING PROPHECIES: Never write entries that predict how Sir will react to the system. Do not write "Sir questions the system's naming" or similar meta-commentary.
6. SEPARATE Sir's identity (long-lasting traits) from OUR RELATIONAL state (jokes / shared history). Inside jokes and milestones are now PROPOSED for Sir's review — they will NOT auto-activate.

[TEMPORAL CONTEXT]
Current Time: {current_hour_str} on {current_weekday}
Physical State: {physical_state}
Work Category: {work_category} (Session: {work_duration} min)
Real-time Ledger: {ledger_snapshot}

[OBSERVATION DIRECTIVES — Sir's identity (auto-saved)]
1. Boundaries & Philosophy: Did Sir express new preferences or dislikes? APPEND to `conversational_boundaries` / `core_philosophy` in plain language.
2. Idiosyncrasies: Any new observable habits? Describe them neutrally in `idiosyncrasies`.
3. Active Projects & Skills: What is Sir working on or learning? Update `active_projects` and `skill_domains`.
4. Work Rhythms: Based on temporal patterns, update `work_rhythms` with observed schedules (e.g., "Night owl: most active between 10 PM and 3 AM").
5. Skill Progression: If Sir has been consistently working on something across sessions, APPEND to `skill_progression` as: {{"skill": "skill name", "first_observed": "approximate date", "confidence": "low/medium/high"}}.

[PROPOSAL DIRECTIVES — Our relational state (REVIEW queue, NOT auto-active)]
6. Proposed Inside Jokes: Did a genuinely amusing interaction occur? Output entries in `proposed_inside_jokes` (at most 3 per cycle). Each entry: {{"phrase": "<short callback phrase, <80 chars>", "birth_context": "<one-sentence why funny>", "tone": "<wry/dry/playful/etc>"}}.
7. Proposed Shared History Threads: Did Sir mention a significant life event or achievement? Output in `proposed_shared_history_threads`. Each entry: {{"title": "<short title>", "highlight": "<one-sentence latest detail>"}}.

[INPUT]
Old Soul Ledger: {json.dumps(current_profile, ensure_ascii=False)}
Recent Raw Logs: {recent_chats}

[OUTPUT]
Output ONLY the updated JSON. The JSON MUST include Sir's identity fields plus the two PROPOSAL arrays (empty arrays if nothing to propose). Do NOT include `our_inside_jokes` or `significant_milestones` keys — those are deprecated. ALL values MUST be in English. NO markdown, NO explanations."""
                
                _key, _key_name, _provider = self.key_router.get_key(KeyRouter.CALLER_SENTINEL, 'flash_lite',
                                                       allow_openrouter_fallback=False)
                _client = create_genai_client(api_key=_key)
                try:
                    res = _client.models.generate_content(
                        model=self.model_name,
                        contents=prompt
                    )
                except Exception as _api_e:
                    self.key_router.report_error(_key_name, str(_api_e))
                    raise
                finally:
                    self.key_router.release(_key_name)
                match = re.search(r'\{.*\}', res.text.strip(), re.DOTALL)
                if match:
                    new_profile = json.loads(match.group(0))

                    # [P0+20-β.2.4.4 / 2026-05-16] 老路径退役：
                    # ① 提取 LLM 输出的 proposed_inside_jokes / proposed_shared_history_threads
                    #    走 relational_state.propose_*（不直接 active，等 Sir review）
                    # ② 强制从 new_profile 删 our_inside_jokes / significant_milestones
                    #    （兼容 LLM 旧习惯还输出这两字段的情况）
                    proposed_jokes = new_profile.pop('proposed_inside_jokes', []) or []
                    proposed_threads = new_profile.pop('proposed_shared_history_threads', []) or []
                    new_profile.pop('our_inside_jokes', None)
                    new_profile.pop('significant_milestones', None)
                    n_joke_proposed = 0
                    n_thread_proposed = 0
                    try:
                        from jarvis_relational import (
                            get_default_store, InsideJoke, SharedHistoryThread,
                            make_joke_id, make_thread_id,
                        )
                        store = get_default_store()
                        for entry in proposed_jokes[:5]:
                            if not isinstance(entry, dict):
                                continue
                            phrase = str(entry.get('phrase') or '').strip()
                            if not phrase:
                                continue
                            jid = make_joke_id(phrase)
                            joke = InsideJoke(
                                id=jid,
                                phrase=phrase[:120],
                                birth_context=str(entry.get('birth_context') or '')[:300],
                                tone=str(entry.get('tone') or '')[:60],
                                source='auto_proposed',
                                source_marker='P0+20-β.2.4.4',
                            )
                            if store.propose_inside_joke(joke):
                                n_joke_proposed += 1
                        for entry in proposed_threads[:5]:
                            if not isinstance(entry, dict):
                                continue
                            title = str(entry.get('title') or '').strip()
                            if not title:
                                continue
                            tid = make_thread_id(title)
                            thread = SharedHistoryThread(
                                id=tid,
                                title=title[:120],
                                source='auto_proposed',
                                source_marker='P0+20-β.2.4.4',
                            )
                            highlight = str(entry.get('highlight') or '').strip()
                            if highlight:
                                thread.add_highlight(highlight)
                            if store.propose_thread(thread):
                                n_thread_proposed += 1
                        if n_joke_proposed or n_thread_proposed:
                            store._dirty = True
                            store.persist()
                            store.write_review_queue()
                    except Exception:
                        pass

                    # Sir 画像字段写入 sir_profile（identity 单向）
                    self._save_profile(new_profile)

                    self.last_update_time = time.time()
                    self.last_update_hour = time.localtime(self.last_update_time).tm_hour
                    self.last_processed_chats = recent_chats

                    try:
                        self.jarvis.profile_card._cache_time = 0
                        self.jarvis.profile_card.apply_correction(
                            'soul_archivist',
                            'identity',
                            'profile_updated',
                            f"v{time.strftime('%H%M')}",
                            0.5
                        )
                    except Exception:
                        pass

                    # [P0+18-c.7 / 2026-05-15] 系统状态打印改 bg_log，不漏到对话框
                    # [P0+20-β.2.4.4] 报 proposed 数量让 Sir 知道 review 队列状态
                    try:
                        from jarvis_utils import bg_log as _sa_bg_log
                        if n_joke_proposed or n_thread_proposed:
                            _sa_bg_log(
                                f"📚 [SoulArchivist] Sir的资料已更新；提名 "
                                f"{n_joke_proposed} jokes + {n_thread_proposed} threads "
                                f"进 review 队列（用 scripts/relational_dump.py --review 看）"
                            )
                        else:
                            _sa_bg_log("📚 [SoulArchivist] Sir的资料已更新，沉淀了新的洞察。")
                    except Exception:
                        pass
            except Exception as e:
                pass
            finally:
                self.is_updating = False
                    
class NudgeGate:
    """共享门控：确保 GuardianCenter 和 CompanionCenter 不会同时发声
    
    规则：
    - 同一中心内部自行管理频率
    - 不同中心之间：一个中心发声后，另一个中心需等待 cooldown 秒
    - 异常介入优先级高于日常关怀（紧急事件可打断日常）
    - 睡眠模式：用户表示睡觉后，仅放行 return_greeting（AFK归来），其余全部抑制
      由聊天管线检测用户醒来后自动解除
    """
    SLEEP_ALLOWED_TYPES = {'return_greeting'}

    def __init__(self, cooldown_seconds: int = 90):
        self._lock = threading.Lock()
        self._last_nudge_time = 0.0
        self._last_nudge_center = ''
        self._cooldown = cooldown_seconds
        self._guardian_override = False
        self._sleep_mode = False
        self._sleep_activated_at = 0.0
        # [R7-β post-test v3] 硬冻结：用户明确拒绝/急停时，连 is_urgent 都不能绕过
        # 这是设计修复——之前 freeze_for 只改 _last_nudge_time，is_urgent 在 can_speak
        # 入口就 return True，导致 Conductor 路径 B 还能在拒绝后 1m47s 抢话
        self._hard_freeze_until = 0.0
        self._hard_freeze_source = ''

    def can_speak(self, center_name: str, is_urgent: bool = False, nudge_type: str = '') -> bool:
        """[轴3-L1 / 2026-05-15] OfferGuard 中央闸接入：
        - 节奏闸（按 nudge_type 各自的 min_interval_s 限频，修 Cs1 path_b 绕过 wellness cooldown）
        - capability 闸（offer_help 必须有 healthy safe skill 可 reference，修 Cs2 宽泛承诺）
        - 通过 → 立刻 OfferGuard.mark_spoken 更新节奏 last_ts（守望者一旦 can_speak 通过就
          push_command，不会再次 check_offer，所以这里立即 mark 是安全的）。"""
        with self._lock:
            now = time.time()
            # [v3] 硬冻结优先于一切（包括 is_urgent）—— 用户拒绝/急停明确不想听见
            if now < self._hard_freeze_until:
                return False
            if self._sleep_mode:
                if nudge_type not in self.SLEEP_ALLOWED_TYPES:
                    return False
            if is_urgent:
                # [轴3-L1] is_urgent 也过 OfferGuard 闸（path_b is_urgent=True 也得遵守节奏）
                if nudge_type and not self._offer_guard_pass(nudge_type):
                    return False
                self._guardian_override = True
                return True
            if self._last_nudge_center and self._last_nudge_center != center_name:
                if now - self._last_nudge_time < self._cooldown:
                    return False
            # OfferGuard 兜底：节奏 + capability
            if nudge_type and not self._offer_guard_pass(nudge_type):
                return False
            return True

    def _offer_guard_pass(self, nudge_type: str) -> bool:
        """[轴3-L1] 中央闸调用 + 通过时记节奏。任何异常默认放行（兜底安全）。"""
        try:
            from jarvis_skill_registry import OfferGuard
            ok, _reason = OfferGuard.check_offer(nudge_type)
            if ok:
                OfferGuard.mark_spoken(nudge_type)
            return ok
        except Exception:
            return True  # OfferGuard 不可用 → 放行（不卡死现有逻辑）

    def mark_spoke(self, center_name: str, nudge_type: str = None):
        """[轴3-L1 / 2026-05-15] nudge_type 参数可选 — 向后兼容老 6 处调用。
        OfferGuard 节奏 last_ts 已在 can_speak 通过时立即更新（不再依赖 mark_spoke）。
        nudge_type 参数保留以备守望者主动声明（如希望仅在 publish 真发出后才记节奏）。"""
        with self._lock:
            self._last_nudge_time = time.time()
            self._last_nudge_center = center_name
            self._guardian_override = False

    def freeze_for(self, seconds: float, source: str = 'manual_standby'):
        """[R7-β post-test v3] 硬冻结 Nudge 通道：N 秒内任何中心（Conductor / SmartNudge /
        Companion / Guardian）都不能说话，is_urgent 也不能绕过。

        用于"用户手动急停"（180s）/"用户明确拒绝"（300s）/"用户告别"（600s）等场景。
        旧实现只改 _last_nudge_time，被 is_urgent 在 can_speak 入口短路 → 失效。
        v3 起改为独立 _hard_freeze_until 字段，can_speak 入口优先检查。
        """
        with self._lock:
            new_until = time.time() + max(0.0, seconds)
            if new_until > self._hard_freeze_until:
                self._hard_freeze_until = new_until
                self._hard_freeze_source = source
            # 同步更新旧字段，保持 seconds_since_last 等接口的一致性
            self._last_nudge_time = self._hard_freeze_until - self._cooldown
            self._last_nudge_center = source
            self._guardian_override = False

    def is_hard_frozen(self) -> bool:
        """[v3] 外部探测当前是否处于硬冻结状态，方便日志/调试。"""
        with self._lock:
            return time.time() < self._hard_freeze_until

    def seconds_since_last(self) -> float:
        with self._lock:
            if self._last_nudge_time == 0:
                return float('inf')
            return time.time() - self._last_nudge_time

    def activate_sleep_mode(self):
        with self._lock:
            self._sleep_mode = True
            self._sleep_activated_at = time.time()
            print(f"[NudgeGate] 休眠模式已激活，抑制所有主动发言直到用户自然唤醒")

    def deactivate_sleep_mode(self):
        with self._lock:
            was_sleeping = self._sleep_mode
            self._sleep_mode = False
            if was_sleeping:
                duration = time.time() - self._sleep_activated_at
                print(f"[NudgeGate] 休眠模式自动解除 (持续 {duration/60:.1f}分钟)，恢复主动发言")

    def is_sleep_mode(self) -> bool:
        with self._lock:
            return self._sleep_mode

    def sleep_duration_seconds(self) -> float:
        with self._lock:
            if not self._sleep_mode or self._sleep_activated_at == 0:
                return 0.0
            return time.time() - self._sleep_activated_at




# ============================================================================
# B. 状态/截图/健康/反思 (UserStatusLedger + Screenshot + Wellness + ReflectionScheduler)
# ============================================================================

class UserStatusLedgerSentinel(threading.Thread):
    def __init__(self, key_router, central_nerve, screenshot_sentinel=None):
        super().__init__(daemon=True)
        self.key_router = key_router
        self.model_name = 'gemini-3.1-flash-lite'
        self.jarvis = central_nerve
        self._screenshot_sentinel = screenshot_sentinel

        self.ledger_dir = r"D:\Jarvis\jarvis_config"
        self.ledger_file = os.path.join(self.ledger_dir, "user_status_ledger.json")
        if not os.path.exists(self.ledger_dir):
            os.makedirs(self.ledger_dir)

        self.history_dir = os.path.join(self.ledger_dir, "user_status_history")
        self.snapshot_dir = os.path.join(self.history_dir, "snapshots")
        self.daily_dir = os.path.join(self.history_dir, "daily")
        for d in [self.history_dir, self.snapshot_dir, self.daily_dir]:
            os.makedirs(d, exist_ok=True)

        self.current_ledger = self._load_ledger()
        self.last_update_time = 0
        self.is_updating = False
        self._last_daily_summary_date = None

        self.is_focus_mode = False

    def set_screenshot_sentinel(self, sentinel):
        self._screenshot_sentinel = sentinel

    def _load_ledger(self):
        import os, json
        if os.path.exists(self.ledger_file):
            try:
                with open(self.ledger_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {
            "physical_focus": "System just started, no data yet",
            "semantic_inertia": "No recent deep conversation",
            "activity_state": "Just connected",
            "emotional_tone": "Neutral",
            "conversation_sentiment": "N/A",
            "detected_stress_signals": []
        }

    def _save_ledger(self, ledger_data):
        import json
        with open(self.ledger_file, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, ensure_ascii=False, indent=2)
        self.current_ledger = ledger_data

    def _save_snapshot(self, ledger_data):
        import json, os, time
        try:
            timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
            snapshot_path = os.path.join(self.snapshot_dir, f"{timestamp}.json")
            snapshot = {
                "timestamp": time.time(),
                "time_str": timestamp,
                "data": ledger_data
            }
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)

            cutoff = time.time() - 7 * 86400
            for fname in os.listdir(self.snapshot_dir):
                fpath = os.path.join(self.snapshot_dir, fname)
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                except:
                    pass
        except Exception:
            pass

    def get_instant_ledger(self):
        return self.current_ledger

    def get_recent_daily_summaries(self, days: int = 3) -> str:
        import os, json, time
        summaries = []
        try:
            files = sorted([f for f in os.listdir(self.daily_dir) if f.startswith('daily_') and f.endswith('.json')],
                           reverse=True)
            for fname in files[:days]:
                fpath = os.path.join(self.daily_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    date_str = fname.replace('daily_', '').replace('.json', '')
                    narrative = data.get('narrative', '') or data.get('summary', '')
                    tags = data.get('tags', [])
                    tag_str = ', '.join(tags) if tags else ''
                    if narrative:
                        summaries.append(f"[{date_str}] {narrative}")
                        if tag_str:
                            summaries[-1] += f" (Tags: {tag_str})"
                except:
                    pass
        except Exception:
            pass
        return '\n'.join(summaries) if summaries else ""

    def force_update_async(self):
        if self.is_updating:
            return
        import threading
        threading.Thread(target=self._update_ledger_logic, daemon=True).start()

    def _update_ledger_logic(self):
        import time, json, re
        self.is_updating = True
        try:
            physical_state = PhysicalEnvironmentProbe.current_physical_state
            process_name = PhysicalEnvironmentProbe.current_process_name
            work_category = PhysicalEnvironmentProbe.current_work_category
            work_duration = PhysicalEnvironmentProbe.work_duration_minutes
            
            snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
            fusion_score = PhysicalEnvironmentProbe.compute_fusion_score()

            recent_chats = "\n".join([f"[{m.get('time', '')}] {m['user']} -> {m['jarvis']}" for m in self.jarvis.short_term_memory[-10:]])
            if not recent_chats: recent_chats = "近期无对话。"

            prompt = f"""You are an ultra-fast behavioral profiler documenting Sir's real-time state.

CRITICAL RULES:
1. NO HALLUCINATIONS! You MUST rely entirely on the provided [Local Physical Radar State] for the focused window/software. Do NOT invent software names that are not listed.
2. Be extremely concise. Use minimal words.
3. Sir is the human user.
4. YOU MUST OUTPUT THE JSON VALUES ENTIRELY IN ENGLISH.
5. Sir uses a DESKTOP PC. There is NO battery. NEVER mention battery percentage, power level, or device charge.

[Previous Ledger]:
{json.dumps(self.current_ledger, ensure_ascii=False)}

[Recent Dialogue Context]:
{recent_chats}

[Local Physical Radar State (Absolute Truth for Window Title)]:
{physical_state}
[Active Process]: {process_name}
[Work Category]: {work_category} (Session duration: {work_duration} minutes)

[Physical Sensor Matrix]:
- Window stay: {snapshot.get('window_stay_seconds', 0)}s
- Switches in 5min: {snapshot.get('switch_frequency_5min', 0)}
- Category entropy: {snapshot.get('category_entropy', 0)}
- Key presses in 5min: {snapshot.get('key_press_count_5min', 0)}
- Backspace ratio: {snapshot.get('backspace_ratio', 0)}
- Burst/pause ratio: {snapshot.get('burst_pause_ratio', 0)}
- Ctrl+S in 5min: {snapshot.get('shortcut_save_5min', 0)}
- Ctrl+Z in 5min: {snapshot.get('shortcut_undo_5min', 0)}
- Mouse distance 5min: {snapshot.get('mouse_distance_5min', 0)}px
- Clicks in 5min: {snapshot.get('click_count_5min', 0)}
- Idle seconds: {snapshot.get('idle_seconds', 0)}
- Night time: {snapshot.get('is_night_time', False)}
- First active today: {snapshot.get('is_first_active_today', False)}
- Background distractions: {snapshot.get('background_distraction_count', 0)}
- WeChat unread: {snapshot.get('wechat_has_unread', False)}
- Audio playing: {snapshot.get('audio_playing', False)}
- Video editor open: {snapshot.get('video_editor_open', False)}
- Error visible on screen: {snapshot.get('error_visible', False)}
- Fusion anomaly score: {fusion_score}

Output STRICT JSON format:
{{
    "software_and_content": "Objective description of the active software and content based ON THE RADAR STATE. (e.g., 'Using PowerShell for command line operations', 'Using Chrome to view AI docs').",
    "screen_activity_type": "Classify the screen activity: 'Coding', 'Debugging', 'Reading', 'Writing', 'Media Editing', 'Watching', 'Chatting', 'Browsing', 'Gaming', 'Idle', 'AFK'.",
    "error_on_screen": "If error/exception/traceback is visible on screen, describe it briefly. Otherwise 'None'.",
    "attention_focus": "Where is Sir's attention? 'Deep Work', 'Shallow Work', 'Casual Browsing', 'Entertainment', 'Communication', 'Distracted', 'AFK'.",
    "recent_dialogue_topic": "Summary of the current conversation topic (or 'None' / 'Silent focus').",
    "human_cognitive_load": "Describe Sir's mental/physical state based on ALL sensor data (key rhythm, mouse activity, window switching, backspace ratio, etc). (e.g., 'High cognitive load, debugging code with frequent undo', 'Relaxed, watching media', 'Idle').",
    "emotional_tone": "Detected emotional state from dialogue tone and word choice. Pick ONE: 'Neutral', 'Focused', 'Frustrated', 'Excited', 'Tired', 'Playful', 'Stressed', 'Satisfied', 'Curious', 'Impatient'.",
    "conversation_sentiment": "Overall sentiment: 'Positive', 'Negative', 'Neutral', or 'Mixed'.",
    "detected_stress_signals": "List any stress indicators observed (urgency keywords, repeated corrections, sigh-like language, short/terse replies, high backspace ratio, frequent undo, rapid window switching). Empty list if none.",
    "intervention_suggestion": "Based on all sensor data, suggest if Jarvis should intervene: 'None', 'Check-in', 'Offer Help', 'Suggest Break', 'Motivate', 'Warn Late Night'. Be conservative - only suggest when sensor anomaly score is high."
}}"""
            from jarvis_utils import safe_gemini_call
            import base64

            screenshot_b64 = None
            if self._screenshot_sentinel:
                screenshot_b64 = self._screenshot_sentinel.get_latest_screenshot_b64()

            def _call_ledger(client):
                contents = [types.Part(text=prompt)]
                if screenshot_b64:
                    img_bytes = base64.b64decode(screenshot_b64)
                    contents.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
                return client.models.generate_content(
                    model=self.model_name,
                    contents=contents
                )

            res, _key_name, _client = safe_gemini_call(
                self.key_router,
                KeyRouter.CALLER_SENTINEL,
                'flash_lite',
                _call_ledger,
                max_retries=3,
                base_delay=2.0,
                model_name=self.model_name, contents_text=prompt
            )
            self.key_router.release(_key_name)

            match = re.search(r'\{.*\}', res.text.strip(), re.DOTALL)
            if match:
                new_ledger = json.loads(match.group(0))
                old_tone = self.current_ledger.get('emotional_tone', '')
                new_tone = new_ledger.get('emotional_tone', '')
                self._save_ledger(new_ledger)
                self._save_snapshot(new_ledger)
                self.last_update_time = time.time()
                
                if old_tone and new_tone and old_tone != new_tone:
                    try:
                        self.jarvis.profile_card.apply_correction(
                            'status_ledger',
                            'current_state.emotional_tone',
                            old_tone,
                            new_tone,
                            0.7
                        )
                    except Exception:
                        pass
        except Exception as e:
            print(f"[StatusLedger] 后台更新异常: {e}")
        finally:
            self.is_updating = False

    def _run_daily_summary(self):
        import time, json, os
        today_str = time.strftime('%Y-%m-%d')
        daily_path = os.path.join(self.daily_dir, f"daily_{today_str}.json")
        if os.path.exists(daily_path):
            self._last_daily_summary_date = today_str
            return

        print(f"\n[DailyChronicle] 正在为 {today_str} 生成每日叙事摘要...")
        try:
            today_start = time.mktime(time.strptime(today_str, '%Y-%m-%d'))

            snapshots_today = []
            for fname in os.listdir(self.snapshot_dir):
                fpath = os.path.join(self.snapshot_dir, fname)
                try:
                    if os.path.getmtime(fpath) >= today_start:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            snapshots_today.append(json.load(f))
                except:
                    pass

            if not snapshots_today and self.current_ledger:
                snapshots_today = [{"timestamp": time.time(), "time_str": today_str, "data": self.current_ledger}]

            chat_history = ""
            try:
                stm = self.jarvis.short_term_memory
                if stm:
                    chat_history = "\n".join([f"[{m.get('time', '?')}] Sir: {m.get('user', '')} → Jarvis: {m.get('jarvis', '')}" for m in stm])
            except:
                pass

            habit_summary = ""
            try:
                if hasattr(self.jarvis, 'habit_clock'):
                    habit_summary = self.jarvis.habit_clock.get_llm_enhanced_summary()
            except:
                pass

            project_summary = ""
            try:
                if hasattr(self.jarvis, 'hippocampus'):
                    project_summary = self.jarvis.hippocampus.get_active_projects_summary()
            except:
                pass

            causal_summary = ""
            try:
                if hasattr(self.jarvis, 'causal_chain'):
                    causal_summary = self.jarvis.causal_chain.get_llm_enhanced_summary()
            except:
                pass

            _key, _key_name, _provider = self.key_router.get_key(KeyRouter.CALLER_SENTINEL, 'flash_lite',
                                                       allow_openrouter_fallback=False)
            _client = create_genai_client(api_key=_key)

            system_prompt = """You are Sir's personal life chronicler. Your task is to synthesize a day's worth of activity data into a concise, insightful daily narrative summary.

RULES:
1. Output ONLY valid JSON. No markdown, no explanation outside JSON.
2. The narrative should be 3-5 sentences in English, written as if Jarvis is privately noting Sir's day.
3. Be factual but warm — like a butler's private journal entry about his employer.
4. Focus on WHAT Sir did, HOW he seemed (emotional trajectory), and any notable patterns.
5. Extract 3-5 concise tags that categorize the day's activities (e.g., 'coding', 'debugging', 'media', 'late-night', 'productive', 'tired', 'focused').
6. The summary should help Jarvis recall context days later when Sir asks "what did I do last week?"."""

            user_prompt = f"""Synthesize Sir's daily log for {today_str}:

=== STATUS SNAPSHOTS (activity state changes throughout the day) ===
{json.dumps([{"time": s.get('time_str', ''), "state": s.get('data', {})} for s in snapshots_today], ensure_ascii=False, indent=2)}

=== CHAT HISTORY (conversations with Jarvis today) ===
{chat_history if chat_history else '(No conversations today)'}

=== WORK HABITS ===
{habit_summary if habit_summary else '(No habit data)'}

=== ACTIVE PROJECTS ===
{project_summary if project_summary else '(No project data)'}

=== CAUSAL PATTERNS ===
{causal_summary if causal_summary else '(No causal data)'}

Output this JSON:
{{
    "date": "{today_str}",
    "narrative": "A 3-5 sentence summary of Sir's day, written elegantly in English from Jarvis's perspective.",
    "emotional_arc": "How Sir's emotional state evolved through the day (e.g., 'Focused → Frustrated → Satisfied').",
    "dominant_activity": "The single activity that dominated Sir's day.",
    "tags": ["tag1", "tag2", "tag3"],
    "notable_moment": "The most significant or interesting event of the day.",
    "productivity_assessment": "Brief assessment: 'highly productive', 'moderately productive', 'rest day', or 'mixed'."
}}"""

            try:
                res = _client.models.generate_content(
                    model='gemini-3.1-flash-lite',
                    contents=system_prompt + '\n\n' + user_prompt
                )
            except Exception as _api_e:
                self.key_router.report_error(_key_name, str(_api_e))
                raise
            finally:
                self.key_router.release(_key_name)

            match = re.search(r'\{.*\}', res.text.strip(), re.DOTALL)
            if match:
                daily_data = json.loads(match.group(0))
                with open(daily_path, 'w', encoding='utf-8') as f:
                    json.dump(daily_data, f, ensure_ascii=False, indent=2)
                self._last_daily_summary_date = today_str
                print(f"[DailyChronicle] {today_str} 叙事已归档: {daily_data.get('dominant_activity', 'N/A')}")
            else:
                print(f"[DailyChronicle] LLM 返回格式无效，跳过 {today_str}")

        except Exception as e:
            print(f"[DailyChronicle] {today_str} 异常: {e}")

    def run(self):
        import time
        time.sleep(10)
        print("[StatusLedger] 异步增量更新引擎就绪...")
        print("[DailyChronicle] 每日叙事摘要引擎挂载完毕...")

        while True:
            time.sleep(5)
            time_since_last = time.time() - self.last_update_time

            if self.is_focus_mode:
                if time_since_last >= 30 and not self.is_updating:
                    self._update_ledger_logic()
            else:
                is_idle = "挂机" in PhysicalEnvironmentProbe.current_physical_state
                interval = 3600 if is_idle else 600
                if time_since_last >= interval and not self.is_updating:
                    self._update_ledger_logic()

            today_str = time.strftime('%Y-%m-%d')
            if self._last_daily_summary_date != today_str and not self.is_updating:
                current_hour = int(time.strftime('%H'))
                if current_hour >= 23 or current_hour < 2:
                    self._run_daily_summary()
                elif current_hour >= 10 and not self._last_daily_summary_date:
                    self._run_daily_summary()

class ScreenshotSentinel(threading.Thread):
    """截图哨兵：每10分钟截取物理屏幕，供 UserStatusLedger 和 Conductor 决策使用"""
    def __init__(self):
        super().__init__(daemon=True)
        self._lock = threading.Lock()
        self._latest_screenshot_b64 = None
        self._latest_screenshot_time = 0
        self._screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_config", "screenshots")
        os.makedirs(self._screenshot_dir, exist_ok=True)

    def run(self):
        time.sleep(15)
        print("[ScreenshotSentinel] 截图哨兵就绪 — 每10分钟捕获物理屏幕...")
        while True:
            try:
                self._capture_and_store()
            except Exception as e:
                # [P0+18-c.14 / 2026-05-15] 改 bg_log，不裸 print 漏到对话框
                try:
                    from jarvis_utils import bg_log as _ss_bg_log
                    _ss_bg_log(f"⚠️ [ScreenshotSentinel] 截图异常: {e}")
                except Exception:
                    pass
            time.sleep(600)

    def _capture_and_store(self):
        try:
            from PIL import ImageGrab
            import base64
            img = ImageGrab.grab()
            img.thumbnail((1280, 720))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            with self._lock:
                self._latest_screenshot_b64 = img_b64
                self._latest_screenshot_time = time.time()
        except Exception as e:
            # [P0+18-c.14 / 2026-05-15] 屏保锁屏 / 显示设备状态切换时常见 "screen grab failed"
            # 不裸 print，统一 bg_log 进背景框（Sir 实测 log:328 抓到）
            try:
                from jarvis_utils import bg_log as _ss_bg_log
                _ss_bg_log(f"⚠️ [ScreenshotSentinel] 截图失败 (可能屏保锁屏): {e}")
            except Exception:
                pass

    def get_latest_screenshot_b64(self) -> str:
        with self._lock:
            return self._latest_screenshot_b64

    def get_latest_screenshot_time(self) -> float:
        with self._lock:
            return self._latest_screenshot_time

    def capture_on_demand(self) -> str:
        self._capture_and_store()
        return self.get_latest_screenshot_b64()

class WellnessGuardian(threading.Thread):
    """P5 健康守护者：基于工时模式主动建议休息，防止过度疲劳"""
    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.jarvis = central_nerve
        self.last_break_suggestion_time = 0.0
        self.suggestion_cooldown = 7200
        self.daily_suggestion_count = 0
        self.last_reset_day = time.strftime("%Y-%m-%d")

    def run(self):
        import time
        time.sleep(30)
        print("[WellnessGuardian] 昼夜节律监测器就绪...")
        
        while True:
            time.sleep(300)
            
            try:
                current_day = time.strftime("%Y-%m-%d")
                if current_day != self.last_reset_day:
                    self.daily_suggestion_count = 0
                    self.last_reset_day = current_day
                
                work_duration = PhysicalEnvironmentProbe.work_duration_minutes
                work_category = PhysicalEnvironmentProbe.current_work_category
                current_hour = int(time.strftime("%H"))
                
                now = time.time()
                if now - self.last_break_suggestion_time < self.suggestion_cooldown:
                    continue
                if self.daily_suggestion_count >= 3:
                    continue
                
                should_suggest = False
                suggestion_reason = ""
                
                if work_category == "Coding" and work_duration > 120:
                    should_suggest = True
                    suggestion_reason = f"continuous coding for {int(work_duration)} minutes"
                elif work_duration > 180:
                    should_suggest = True
                    suggestion_reason = f"extended screen time of {int(work_duration)} minutes"
                
                if current_hour >= 1 and current_hour < 6 and work_category == "Coding":
                    should_suggest = True
                    suggestion_reason = f"late-night coding at {current_hour}:00"
                
                if should_suggest:
                    self._send_wellness_nudge(suggestion_reason)
                    self.last_break_suggestion_time = now
                    self.daily_suggestion_count += 1
                    
            except Exception:
                pass

    def _send_wellness_nudge(self, reason: str):
        try:
            PhysicalEnvironmentProbe._wellness_alert = {
                'active': True,
                'reason': reason,
                'hour': int(time.strftime('%H')),
                'timestamp': time.time(),
            }
            print(f"\n[WellnessGuardian] 健康事件已上报 Conductor ({reason})")
        except Exception:
            pass

class ReflectionScheduler(threading.Thread):
    """LLM 反思调度器：协调 HabitClock / ProjectTimeline / CausalChain 的 LLM 反思频率
    
    设计原则：
    - 规则引擎实时运行（免费、毫秒级）
    - LLM 反思按需触发（便宜、秒级）
    - 成本可控：每天约 50-80 次 flash-lite + 8-10 次 flash
    
    调度策略：
    - HabitClock._llm_reflect(): 每 30min 一次 (flash-lite)
    - ProjectTimeline._llm_reflect(): 检测到新进程时 (flash-lite)
    - CausalChain._llm_reflect(): 检测到新模式时，最少间隔 3h (flash)
    """
    
    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.jarvis = central_nerve
        self.reflector = LlmReflector()
        
        self._last_habit_reflect = 0
        self._last_causal_reflect = 0
        self._last_project_reflect = 0
        self._last_process_check = ""
        
        self.habit_interval = 1800
        self.causal_min_interval = 10800
        self.project_min_interval = 900
        
        self._last_causal_event_count = 0
        self._last_causal_pattern_hash = ""
        
        self._daily_cost_limit = 0.01
        self._paused = False
    
    def run(self):
        import time
        time.sleep(15)
        print("[ReflectionScheduler] LLM混合反思调度器就绪...")
        print(f"   ├─ HabitClock 反思: 每 {self.habit_interval // 60} 分钟 (flash-lite)")
        print(f"   ├─ ProjectTimeline 反思: 新进程检测触发 (flash-lite)")
        print(f"   └─ CausalChain 反思: 模式触发, 最小间隔 {self.causal_min_interval // 3600} 小时 (flash)")
        
        while True:
            time.sleep(30)
            
            try:
                stats = self.reflector.get_daily_stats()
                if stats['estimated_cost_usd'] > self._daily_cost_limit:
                    if not self._paused:
                        print(f"[ReflectionScheduler] 今日费用已达 ${stats['estimated_cost_usd']:.4f}，暂停 LLM 反思")
                        self._paused = True
                    continue
                else:
                    if self._paused:
                        print(f"[ReflectionScheduler] 费用降至 ${stats['estimated_cost_usd']:.4f}，恢复 LLM 反思")
                        self._paused = False
                
                if self._paused:
                    continue
                
                self._tick_habit_reflect()
                self._tick_project_reflect()
                self._tick_causal_reflect()
                
            except Exception as e:
                print(f"[ReflectionScheduler] 调度异常: {e}")
    
    def _tick_habit_reflect(self):
        now = time.time()
        if now - self._last_habit_reflect < self.habit_interval:
            return
        
        if not hasattr(self.jarvis, 'habit_clock'):
            return
        
        self._last_habit_reflect = now
        import threading
        threading.Thread(target=self._do_habit_reflect, daemon=True).start()
    
    def _do_habit_reflect(self):
        try:
            from jarvis_utils import bg_log
        except Exception:
            bg_log = print
        try:
            result = self.jarvis.habit_clock._llm_reflect(self.reflector)
            if result.get('success') and not result.get('cached'):
                stats = self.reflector.get_daily_stats()
                bg_log(f"[HabitClock LLM] 窗口分类反思完成 (今日费用: ${stats['estimated_cost_usd']:.5f})")
        except Exception as e:
            bg_log(f"[HabitClock] 反思异常: {e}")
    
    def _tick_project_reflect(self):
        now = time.time()
        if now - self._last_project_reflect < self.project_min_interval:
            return
        
        if not hasattr(self.jarvis, 'project_timeline'):
            return
        
        current_process = PhysicalEnvironmentProbe.current_process_name
        if current_process == self._last_process_check:
            return
        
        prev_process = self._last_process_check
        self._last_process_check = current_process
        self._last_project_reflect = now
        
        if prev_process and prev_process != "Unknown" and hasattr(self.jarvis, 'project_timeline'):
            self.jarvis.project_timeline.end_session()
        
        if current_process and current_process != "Unknown":
            current_title = ""
            if PhysicalEnvironmentProbe.window_history:
                current_title = PhysicalEnvironmentProbe.window_history[-1].get('title', '')
            self.jarvis.project_timeline.start_session(current_process, current_title)
            import threading
            threading.Thread(target=self._do_project_reflect, daemon=True).start()
    
    def _do_project_reflect(self):
        try:
            if PhysicalEnvironmentProbe.window_history:
                current_title = PhysicalEnvironmentProbe.window_history[-1].get('title', '')
                self.jarvis.project_timeline.update_title(current_title)
            result = self.jarvis.project_timeline._llm_reflect(self.reflector)
            if result.get('success') and not result.get('cached'):
                proj = result.get('result', {}).get('project_name', 'unknown')
                conf = result.get('result', {}).get('confidence', 0)
                if proj != 'unknown' and conf >= 0.5:
                    print(f"[ProjectTimeline LLM] 项目已识别: {proj} (置信度: {conf:.0%})")
        except Exception as e:
            print(f"[ProjectTimeline] 反思异常: {e}")
    
    def _tick_causal_reflect(self):
        now = time.time()
        if now - self._last_causal_reflect < self.causal_min_interval:
            return
        
        if not hasattr(self.jarvis, 'causal_chain'):
            return
        
        cc = self.jarvis.causal_chain
        current_count = len(cc.events)
        
        if current_count < 3:
            return
        
        patterns = cc.detect_patterns()
        pattern_hash = hashlib.md5(str(patterns).encode()).hexdigest()
        
        new_events = current_count - self._last_causal_event_count
        pattern_changed = pattern_hash != self._last_causal_pattern_hash
        
        if new_events >= 2 or pattern_changed:
            self._last_causal_reflect = now
            self._last_causal_event_count = current_count
            self._last_causal_pattern_hash = pattern_hash
            
            import threading
            threading.Thread(target=self._do_causal_reflect, daemon=True).start()
    
    def _do_causal_reflect(self):
        try:
            result = self.jarvis.causal_chain._llm_reflect(self.reflector)
            if result.get('success') and not result.get('cached'):
                conf = result.get('result', {}).get('overall_confidence', 0)
                stats = self.reflector.get_daily_stats()
                if conf >= 0.7:
                    print(f"[CausalChain LLM] 高置信度因果推理完成 (置信度: {conf:.0%}, 今日费用: ${stats['estimated_cost_usd']:.5f})")
                else:
                    print(f"[CausalChain LLM] 因果推理完成 (置信度: {conf:.0%}, 今日费用: ${stats['estimated_cost_usd']:.5f})")
        except Exception as e:
            print(f"[CausalChain] 反思异常: {e}")
    
    def force_reflect(self):
        """Single reflection trigger (used by sleep archive)"""
        import threading
        threading.Thread(target=self._do_habit_reflect, daemon=True).start()

    def force_reflect_all(self):
        """手动触发全部反思（用于调试或关键节点）"""
        import threading
        threading.Thread(target=self._do_habit_reflect, daemon=True).start()
        threading.Thread(target=self._do_project_reflect, daemon=True).start()
        threading.Thread(target=self._do_causal_reflect, daemon=True).start()
        print("[ReflectionScheduler] 手动全量反思已触发...")
    
    def get_status(self) -> dict:
        stats = self.reflector.get_daily_stats()
        return {
            'paused': self._paused,
            'daily_cost': stats['estimated_cost_usd'],
            'daily_calls': stats['calls'],
            'cache_size': stats['cache_hits'],
            'last_habit_reflect': time.strftime('%H:%M:%S', time.localtime(self._last_habit_reflect)) if self._last_habit_reflect else 'never',
            'last_causal_reflect': time.strftime('%H:%M:%S', time.localtime(self._last_causal_reflect)) if self._last_causal_reflect else 'never',
            'last_project_reflect': time.strftime('%H:%M:%S', time.localtime(self._last_project_reflect)) if self._last_project_reflect else 'never',
        }


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

