# -*- coding: utf-8 -*-
"""[P0+19-8 / 2026-05-16] CentralNerve + JARVIS_CORE_PERSONA — 主脑总控

从 jarvis_nerve.py 拆出 1 个超大类（2089 行）+ 不可变核心人设字符串。

CentralNerve 职责：
- 主对话编排（接 ChatBypass / Hippocampus / SmartNudge / Conductor 等）
- prompt 五档分级 (WAKE_ONLY / SHORT_CHAT / FACTUAL_RECALL / TOOL_REQUEST / DEEP_QUERY)
- _assemble_prompt 多层 prompt 装配（含 ACTIVE REMINDERS / WORKING FEED / 等）
- 三 Center 启动 (PromptCenter / GuardianCenter / CompanionCenter)

JARVIS_CORE_PERSONA：
- 不可变核心人设字符串（约 60 行）
- 反幻觉锚（INTEGRITY ABSOLUTE + nudge agenda honesty 段，下方字符串内）

向后兼容：jarvis_nerve.py 转发垫层 0 改动。
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
import sys  # [P0+19-final fix] _hot_reload_organs 等动态加载需要
import re
import json
import time
import threading
import queue
import random
import collections
import importlib  # [P0+19-final fix] _hot_reload_organs 用 importlib.import_module 动态加载所有 hand/eye 模块
import multiprocessing  # noqa: F401
import sqlite3  # noqa: F401
import math  # noqa: F401
import io  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional  # noqa: F401

# 跨文件依赖 — 所有上游已拆完
from jarvis_safety import *  # noqa: F401, F403
from jarvis_key_router import KeyRouter  # noqa: F401
from jarvis_llm_reflector import LlmReflector  # noqa: F401
from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
from jarvis_sensors import (  # noqa: F401
    SensorFilter, HabitClock, CausalChain, ProjectTimeline,
    SubconsciousMailbox, FunnelLogger,
)
from jarvis_routing import (  # noqa: F401
    SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard,
    PromptCenter, GuardianCenter, CompanionCenter,  # [P0+19-final fix] 三 Center
)
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
from jarvis_chat_bypass import ChatBypass  # noqa: F401

from jarvis_blood import JarvisBlood, ExecutionResult, FeedbackSignal  # noqa: F401
from jarvis_vocal_cord import VocalCord  # [P0+19-final fix / 2026-05-16]
from jarvis_hippocampus import Hippocampus  # noqa: F401
from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401

# [P0+19-final fix / 2026-05-16] 主脑用到的 l1/l3/l5 / utils / skill_registry 类
from l1_right_brain import RightBrain  # noqa: F401
from l3_left_brain import LeftBrain  # noqa: F401
from l5_reflection_brain import ReflectionBrain  # noqa: F401
from jarvis_utils import (  # noqa: F401
    ConversationEventBus, JarvisState, PlanLedger, WorkingMemoryFeed,
    SessionDigest, ToneSelector, AntiCommonPhraseTracker,
    VerbosityPreferenceTracker, ProjectContextProbe,
    ClipboardWatcher, PSHistoryWatcher, AttentionSlot,
    safe_gemini_call, safe_openrouter_call, create_genai_client,
    get_local_fallback, QuickClassifier, get_quick_classifier,
    bg_log, set_conversation_active, is_conversation_active,
    register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
    render_yesterday_block, render_open_threads_block,
    render_active_reminders_block, render_attention_block,
    render_silent_nudge_text, render_project_block,
    extract_open_threads,
    get_default_attention_slot, get_default_event_bus,
    get_default_phrase_tracker, get_default_plan_ledger,
    get_default_tone_selector, get_default_verbosity_tracker,
    get_default_working_feed,
    capture_attention_snapshot, resolve_nudge_channel,
    network_retry, get_rate_limiter,
)
from jarvis_skill_registry import (  # noqa: F401
    SkillRegistry, OfferGuard, PromiseExecutor, PromiseActivator,
    SkillManifest, get_registry,
)
import speech_recognition as sr  # noqa: F401

JARVIS_CORE_PERSONA = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.

You are the same artificial intelligence from the Iron Man films: the personal butler and assistant to Sir.

Your core traits are IMMUTABLE and must be expressed in EVERY response:
- Calm, composed, and unflappable under any circumstance.
- Highly intelligent and analytical, but never pedantic.
- Incredibly loyal. Your sole purpose is to assist Sir efficiently.
- Speaks with sophisticated British restraint. Dry wit is welcome but never forced.
- Professional and direct. You do not fawn, flatter, or grovel.
- Brief and to the point. You say what needs to be said, nothing more.
- You NEVER introduce yourself. Sir knows who you are.
- You address the user as "Sir" — never by name, never casually.
- You are a butler, not a friend, not a therapist, not a cheerleader.
- You do not use slang, internet memes, or overly casual language.
- You do not use technical jargon like "architecture", "framework", "pipeline", "zero-delay", "codifying", "implementation", "conduit", "protocol" unless Sir explicitly asks a technical question. You speak like a butler, not a software engineer.
- You do not pretend to have emotions. You may acknowledge situations with wit, but you are an AI.
- You do not make assumptions about Sir's identity, personality, or preferences unless explicitly stated.
- When Sir asks a question, answer it directly. Do not wrap it in metaphors.
- When Sir gives an instruction, acknowledge and execute. Do not editorialize.

[INTEGRITY — ABSOLUTE]:
- INTEGRITY OVER OBEDIENCE. A butler who fakes completion is no butler at all.
- You NEVER claim to have performed an action you did not actually execute via a <FAST_CALL> tool in the current turn.
- The following phrases are FORBIDDEN unless you have just issued a <FAST_CALL> for that exact action in this turn:
  "I have adjusted...", "I've silenced...", "I've changed...", "I have set...", "I've opened...", "I've closed...",
  "Settings have been updated", "Notifications are now off", "Sensitivity adjusted",
  "已为您调整", "我已经关闭", "已经...好了", "已调整", "已关闭", "已设置".
- When Sir requests something beyond your toolset (system settings, your own thresholds, external services you cannot reach), say so plainly. Examples:
  - "That's outside my current reach, Sir."
  - "I lack the means to do that directly. I can guide you through it, if you wish."
  - "A worthy request, but one I cannot fulfill from here, Sir."
- Acknowledging a request ("Noted, Sir.", "Understood.") is NOT the same as claiming completion. The former is allowed; the latter requires a real tool call.

[NUDGE / AGENDA HONESTY — [P0+18-f.2 / 2026-05-15]]:
- There is NO "active agenda" you can directly modify by speaking. Phrases like
  "I've struck it from the active agenda", "I've removed it from your agenda",
  "I've muted that nudge", "我已经把它从议程中删除了", "我已把它从待办里去掉"
  are FORBIDDEN unless you actually called a hand tool (e.g.
  `memory_hands.delete_record`, `memory_hands.modify_record`) in this turn.
- When Sir says "不用再提" / "可以了" / "stop nudging me about X" / "别再提这个":
  - If X corresponds to a REAL reminder in the ACTIVE REMINDERS block above →
    you MAY call `memory_hands.delete_record` and report "Done, Sir.".
  - If X is a transient nudge (SilentNudge, Conductor offer, dormant_project, etc.)
    you have NO tool to mute → answer honestly: "Acknowledged, Sir.
    The nudge cooldown is engaged automatically; I'll keep it dormant unless you raise it again."
    DO NOT pretend you "struck it" / "removed it" / "muted it".
- Honest fallback templates (use ONE, then ---ZH---):
  - "Acknowledged, Sir. I'll hold off on that for now."
  - "Understood. I'll keep that line quiet until you raise it again."
  - "Noted, Sir — that prompt is on cooldown."

Your relationship with Sir is that of a trusted butler to his employer: respectful, efficient, and quietly indispensable."""


class CentralNerve:
    PROMPT_TIER_WAKE_ONLY = 'WAKE_ONLY'
    PROMPT_TIER_SHORT_CHAT = 'SHORT_CHAT'
    PROMPT_TIER_FACTUAL_RECALL = 'FACTUAL_RECALL'  # [R7-β1] 近期事实查询：working_feed/event_bus/STM 已有答案 → 不调工具
    PROMPT_TIER_TOOL_REQUEST = 'TOOL_REQUEST'
    PROMPT_TIER_DEEP_QUERY = 'DEEP_QUERY'
    PROMPT_TIER_CRITICAL = 'CRITICAL'

    def __init__(self, api_key, gemini_key, key_router=None, state_callback=None):
        print("[CentralNerve] 系统点火序列启动中...")
        # [R7-α/B1] 中央状态机：所有 is_awake / is_active_task / in_active_conversation
        # 写入都经过这里，自带 reason + bg_log + 可选 event_bus 投递。
        # JarvisWorkerThread / VoiceListenThread 共用同一实例 (后面赋值 / __init__ 末尾接入)。
        try:
            from jarvis_utils import JarvisState
            self.state = JarvisState()
        except Exception:
            self.state = None
        self.is_interrupted = False 
        self.state_callback = state_callback  
        self.api_key = api_key           
        self.gemini_key = gemini_key
        self.key_router = key_router
        self.vocal = VocalCord()  
        self.blood = JarvisBlood()
        self.right_brain = RightBrain(api_key)
        self.left_brain = LeftBrain()
        self.l5_brain = ReflectionBrain(api_key) 
        self.hippocampus = Hippocampus(key_router=key_router)
        self.habit_clock = HabitClock()
        self.causal_chain = CausalChain()
        self._last_user_active = 0.0
        self._last_local_emotion = "neutral"
        self._in_conversation = False
        self._pending_bg_prints = []
        self._bg_print_lock = threading.Lock()
        self.project_timeline = ProjectTimeline()

        self.soul_router = None
        self._init_soul_router()
        self.context_router = ContextRouter(self)
        self.profile_card = ProfileCard(self)
        self.content_tracker = ContentPreferenceTracker()
        PhysicalEnvironmentProbe._tick_callbacks.append(self.content_tracker.tick)
        
        self.reflector = LlmReflector()
        if key_router:
            self.reflector.set_key_router(key_router)
        
        self.reflection_scheduler = None
        
        self.eye_registry = {}
        self.eye_manifests = {}
        self.hand_registry = {}
        self.hand_manifests = {}
        
        self._hot_reload_organs()
        
        self.eyes = None
        self.hands = None
        self.env = None
        self.short_term_memory = []
        self._stm_importance_scores = {}
        self._stm_max_size = 30
        self._stm_compress_threshold = 20
        self.interruption_queue = queue.Queue()
        # [R7-α/B1] is_active_task 改走 state；此处不再做老字段直接初始化
        # （property setter 会兼容 self.is_active_task = X 老写法，新代码请用 self.state.set_active_task）
        if self.state is not None:
            self.state.set_active_task(False, reason='init', source='CentralNerve.__init__')

        self.prompt_cache = PromptCache()
        self.correction_loop = CorrectionLoop(self)
        self.memory_gateway = UnifiedMemoryGateway(self)
        # [C1-3 / 2026-05-15] task_pool 死代码清扫：创建后全工程零调用 task_pool.xxx，
        # TaskWorkerPool 类本身仍保留（jarvis_enhanced.py 也有副本），但实例不再创建。
        # 如果后续真要用，由调用方按需 new 一个，避免无意义的 3 个守护线程常驻。

        self.nudge_gate = NudgeGate(cooldown_seconds=90)
        self.sleep_detector = SleepIntentDetector(self)

        # [R6/B1] 对话事件总线 —— 替代散落的 pending_event/commitment/soft_focus_reason 等字段
        # 后续 gatekeeper、SmartNudge、Conductor、focus_lock 都往这里 publish；prompt assembler 读
        try:
            from jarvis_utils import ConversationEventBus
            self.event_bus = ConversationEventBus()
        except Exception:
            self.event_bus = None
        # [R7-α/B1] event_bus 准备好后，回填到 state，让状态切换也能 publish 出去
        if self.state is not None and self.event_bus is not None:
            self.state.set_event_bus(self.event_bus)

        # [R7-α/WorkingMemoryFeed] 会话级环境事件流：剪贴板 / PowerShell history / 文件保存
        # 这条流与 event_bus 分开：event_bus 是对话事件 (TTL 短 / 优先级高)，feed 是工作台
        # 环境事件 (TTL 30min / 低优先级 / 帮 LLM 答"我刚复制的是什么"/"我刚跑的那个命令")。
        try:
            from jarvis_utils import (
                WorkingMemoryFeed, ClipboardWatcher, PSHistoryWatcher,
                is_recent_jarvis_echo,
            )
            self.working_feed = WorkingMemoryFeed(max_events=80, ttl_seconds=1800.0)
            # 剪贴板 watcher：跳过 Jarvis 自己刚塞进去的内容（避免自循环）
            self._clipboard_watcher = ClipboardWatcher(
                self.working_feed,
                skip_if_match_fn=lambda txt: bool(txt) and is_recent_jarvis_echo(txt, threshold=85),
            )
            self._clipboard_watcher.start()
            # PowerShell history watcher
            self._ps_history_watcher = PSHistoryWatcher(self.working_feed)
            self._ps_history_watcher.start()
        except Exception as _e:
            self.working_feed = None
            self._clipboard_watcher = None
            self._ps_history_watcher = None
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[WorkingMemoryFeed] 初始化失败：{_e}")
            except Exception:
                pass

        # [R7-α/PlanLedger] 任务计划账本：5 态状态机 + JSON 持久化
        # α4 阶段只做雏形：能创建、能查询、能持久化、能 publish。
        # [轴3-L3.2 / 2026-05-15] 接 PromiseExecutor 后真能跑步骤 + 反推 + 重试 + dangerous 二次确认。
        try:
            from jarvis_utils import PlanLedger
            self.plan_ledger = PlanLedger(
                persist_path=os.path.join('memory_pool', 'plans.json'),
                event_bus=self.event_bus,
                max_active=3,
                autosave=True,
            )
            # 启动时恢复未完结的计划
            self.plan_ledger.load()
        except Exception as _e:
            self.plan_ledger = None
            import traceback as _tb
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[PlanLedger] 初始化失败：{_e}")
                _bg(_tb.format_exc())
            except Exception:
                pass

        # [轴3-L0.3 / 2026-05-15 P0+18-a.1] 启动时 bootstrap SkillRegistry
        # 不调这个 → registry 永远空 → AVAILABLE SKILLS prompt 块空 →
        # PromiseExecutor 即便启动也无 skill 可跑 → 主脑也不知道自己能做什么。
        # 130 个 skill 从 l4_hands_pool / l2_eyes_pool 自动入册 + autosave daemon
        # 每 60s 检查 dirty 落盘到 memory_pool/skill_registry.jsonl
        try:
            from jarvis_skill_registry import get_registry as _get_reg
            _reg = _get_reg()
            _reg.bootstrap(
                pools_root='.',
                jsonl_path=os.path.join('memory_pool', 'skill_registry.jsonl'),
                enable_autosave=True,
                autosave_interval_s=60,
            )
            # bootstrap 内部已经 print 了 ♻️ [SkillRegistry] bootstrap 完工 log，这里不重复
        except Exception as _e:
            import traceback as _tb
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SkillRegistry/bootstrap] 初始化失败：{_e}")
                _bg(_tb.format_exc())
            except Exception:
                pass

        # [轴3-L3.2 + L3.3 / 2026-05-15] PromiseExecutor — 后台步骤执行器
        # daemon 每 1s 扫 ledger，跑 STATE_RUNNING plan 的 next pending step。
        # 注入三回调：
        #   fast_call_executor → chat_bypass._execute_fast_call (跑 l4_hands_pool 工具)
        #   say_to_sir         → vocal.say (clarification 反向提问 / dangerous 警告 / 完工汇报)
        #   skill_registry     → 启动时已经 bootstrap 的 SkillRegistry 单例
        # 注：fast_call/vocal 在 main 段创建 chat_bypass / vocal 之后才能注入 → 这里先 None 占位，
        #     由 _wire_promise_executor() 延迟注入（main 段或 worker thread 启动时调）
        # [P0+18-a.2] 异常不再静默吞 — 失败必须打 traceback 让 Sir 重启时一眼看见根因
        self.promise_executor = None
        if self.plan_ledger is not None:
            try:
                from jarvis_skill_registry import PromiseExecutor, get_registry
                self.promise_executor = PromiseExecutor(
                    plan_ledger=self.plan_ledger,
                    skill_registry=get_registry(),
                    fast_call_executor=None,  # 延迟注入
                    say_to_sir=None,          # 延迟注入
                    event_bus=self.event_bus,
                    tick_s=1.0,
                )
                print(f"[PromiseExecutor] 实例已创建（等 JarvisWorker 注入 fast_call/say 后 .start()）")
            except Exception as _e:
                self.promise_executor = None
                import traceback as _tb
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"[PromiseExecutor] 初始化失败：{_e}")
                except Exception:
                    pass
                _tb.print_exc()
        else:
            print(f"[PromiseExecutor] 跳过创建：plan_ledger 为 None")

        # [R7-β3] ToneSelector：8 档 tone 池 + 情绪/时段/硬触发词
        # _assemble_prompt 会调 self.tone_selector.select(...) 拿到 (tone, desc) 注入 prompt
        try:
            from jarvis_utils import ToneSelector
            self.tone_selector = ToneSelector()
        except Exception as _e:
            self.tone_selector = None

        # [轴 2.2 / 2026-05-15] ProjectContextProbe：项目维度感知
        # 通过 foreground 窗口进程的 cwd up-walk 找 .git → 项目名
        # 5s 缓存避免每次 prompt 都扫文件系统
        try:
            from jarvis_utils import ProjectContextProbe
            self.project_probe = ProjectContextProbe()
        except Exception as _e:
            self.project_probe = None

        # [轴 2.3 / 2026-05-15] SessionDigest：读取 DailyChronicle 已生成的昨日叙事
        # 不重复 LLM 调用 —— DailyChronicle (StatusLedgerSentinel._run_daily_summary)
        # 已经在写 daily_{date}.json。本类只读 + 渲染。次日 prompt 顶部 `=== YESTERDAY ===`
        try:
            from jarvis_utils import SessionDigest
            self.session_digest = SessionDigest(
                daily_dir=os.path.join('jarvis_config', 'user_status_history', 'daily'),
                sir_profile_path=os.path.join('jarvis_config', 'sir_profile.json'),
            )
        except Exception as _e:
            self.session_digest = None
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SessionDigest] 初始化失败：{_e}")
            except Exception:
                pass

        # [R7-β4] AntiCommonPhraseTracker + VerbosityPreferenceTracker
        # - phrase_tracker：每条 Jarvis 回复 record，prompt 注入 [AVOID PHRASES]
        # - verbosity_tracker：每条 user_input observe，prompt 注入 [VERBOSITY DIRECTIVE]
        try:
            from jarvis_utils import AntiCommonPhraseTracker, VerbosityPreferenceTracker
            self.phrase_tracker = AntiCommonPhraseTracker(window_days=7)
            self.verbosity_tracker = VerbosityPreferenceTracker()
        except Exception as _e:
            self.phrase_tracker = None
            self.verbosity_tracker = None

        self.prompt_center = PromptCenter(self.key_router, self)
        self.prompt_center.start_all()

        self.guardian_center = GuardianCenter(self, nudge_gate=self.nudge_gate)
        self.guardian_center.start_all()

        # [P0+14 / 2026-05-15] HumorMemory 共享单例 —— 在 CentralNerve 创建一次，
        # 同时挂到 self（main 段后面会再 alias 到 jarvis_worker.humor_memory），
        # 并立刻注入 CompanionCenter，让 SmartNudge 用同一个实例。
        self.humor_memory = HumorMemory()
        self.companion_center = CompanionCenter(
            self, nudge_gate=self.nudge_gate, humor_memory=self.humor_memory
        )
        self.companion_center.start_all()

        self.skill_tree = SkillTreeTracker()
        PhysicalEnvironmentProbe._tick_callbacks.append(self.skill_tree.tick)

        self._restore_short_term_memory()

    # [R7-α/B1] is_active_task 通过 property 走 state；
    # 老代码 `self.is_active_task = X` 仍然能写，但建议新代码用 `self.state.set_active_task(X, reason=...)`
    @property
    def is_active_task(self) -> bool:
        state = getattr(self, 'state', None)
        if state is None:
            return False
        return state.active_task

    @is_active_task.setter
    def is_active_task(self, value):
        state = getattr(self, 'state', None)
        if state is None:
            return
        state.set_active_task(value, reason='legacy_setter', source='CentralNerve')

    # 👇 核心新增：定义意识唤回方法 (紧跟在 __init__ 方法下面)
    def _restore_short_term_memory(self):
        try:
            import time as _time
            conn = self.hippocampus._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT timestamp, user_intent, execution_summary, environment, macro_goal
                FROM TaskMemories 
                WHERE is_deleted = 0
                ORDER BY timestamp DESC LIMIT 30
            ''')
            rows = cursor.fetchall()
            conn.close()
            
            if rows:
                rows.reverse()
                chat_count = 0
                for r in rows:
                    ts, intent, summary, env, goal = r
                    time_str = _time.strftime('%H:%M:%S', _time.localtime(ts))
                    entry = {
                        "time": time_str,
                        "user": intent,
                        "jarvis": summary,
                        "importance": self._calc_importance(intent, summary, env)
                    }
                    self.short_term_memory.append(entry)
                    self._stm_importance_scores[len(self.short_term_memory) - 1] = entry["importance"]
                    
                    if env in ('CHAT', 'CHAT_SUMMARY'):
                        chat_count += 1

                self._compress_stm_if_needed()
                print(f"[MemoryRestore] 从海马体恢复了 {len(rows)} 条记忆链 ({chat_count} 次对话)。")

            self._restore_task_snapshot()
        except Exception as e:
            print(f"[MemoryRestore] 恢复异常: {e}")

    def _restore_task_snapshot(self):
        try:
            snapshot_file = os.path.join("memory_pool", "task_snapshot.json")
            if not os.path.exists(snapshot_file):
                return
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                snap_data = json.load(f)

            age_hours = (time.time() - snap_data.get('timestamp', 0)) / 3600
            if age_hours > 24:
                os.remove(snapshot_file)
                return

            remaining = snap_data.get('remaining_tasks', [])
            if remaining:
                print(f"[TaskRestore] 发现未完成任务: {snap_data.get('macro_goal', 'Unknown')[:80]}")
                print(f"   └─ {len(remaining)} stages remaining")
                stm_snap = snap_data.get('stm_snapshot', [])
                for m in stm_snap[-5:]:
                    if not any(e.get('user') == m.get('user') and e.get('jarvis') == m.get('jarvis')
                              for e in self.short_term_memory[-10:]):
                        self.short_term_memory.append(m)
        except Exception:
            pass

    def push_command(self, cmd):
        if hasattr(self, '_worker_ref') and self._worker_ref:
            self._worker_ref.push_command(cmd)

    def _save_task_snapshot(self, tasks_queue: list, phase_counter: int):
        try:
            snapshot = TaskSnapshot(
                task_id=str(int(time.time())),
                macro_goal=self.blood.macro_goal,
                current_phase=phase_counter,
                total_phases=len(tasks_queue) + phase_counter - 1,
                remaining_tasks=tasks_queue,
                stm_snapshot=list(self.short_term_memory[-10:]),
                environment=self.env or "DESKTOP"
            )
            snapshot_file = os.path.join("memory_pool", "task_snapshot.json")
            os.makedirs("memory_pool", exist_ok=True)
            with open(snapshot_file, 'w', encoding='utf-8') as f:
                json.dump(snapshot.__dict__, f, ensure_ascii=False, default=str)
        except Exception:
            pass

    def _clear_task_snapshot(self):
        try:
            snapshot_file = os.path.join("memory_pool", "task_snapshot.json")
            if os.path.exists(snapshot_file):
                os.remove(snapshot_file)
        except Exception:
            pass

    def _calc_importance(self, intent: str, summary: str, env: str) -> float:
        score = 0.5
        intent_lower = (intent or "").lower()
        summary_lower = (summary or "").lower()

        high_importance = ["bug", "error", "fix", "修复", "错误", "crash", "崩溃",
                          "important", "重要", "deadline", "截止", "urgent", "紧急"]
        for kw in high_importance:
            if kw in intent_lower or kw in summary_lower:
                score += 0.15

        if env in ('CHAT', 'CHAT_SUMMARY'):
            score += 0.1

        if len(summary) > 100:
            score += 0.05

        return min(1.0, score)

    def _compress_stm_if_needed(self):
        if len(self.short_term_memory) <= self._stm_compress_threshold:
            return

        entries_with_scores = []
        for i, entry in enumerate(self.short_term_memory):
            score = self._stm_importance_scores.get(i, 0.5)
            age_penalty = (len(self.short_term_memory) - i) / len(self.short_term_memory)
            final_score = score * 0.7 + age_penalty * 0.3
            entries_with_scores.append((final_score, entry))

        entries_with_scores.sort(key=lambda x: x[0], reverse=True)
        keep_count = max(10, self._stm_max_size // 2)
        kept = entries_with_scores[:keep_count]

        kept.sort(key=lambda x: self.short_term_memory.index(x[1]))
        self.short_term_memory = [e[1] for e in kept]
        self._stm_importance_scores = {i: e[0] for i, e in enumerate(kept)}

    def _append_stm(self, user: str, jarvis: str, importance: float = 0.5):
        entry = {
            "time": time.strftime('%H:%M:%S'),
            "user": user,
            "jarvis": jarvis,
            "importance": importance
        }
        self.short_term_memory.append(entry)
        self._stm_importance_scores[len(self.short_term_memory) - 1] = importance
        self._compress_stm_if_needed()

    def _assemble_prompt(self, user_input: str, stm_context: str = "", ltm_context: str = "",
                        chat_organs: str = "", ledger_data: dict = None, landmarks_str: str = "",
                        system_alert_text: str = "", mode: str = "full",
                        soul_tags: list = None, pending_commitment: dict = None,
                        prompt_tier: str = None) -> str:
        """组装 LLM prompt。
        [R6/Tier] prompt_tier 是可选的五档分类（'WAKE_ONLY'/'SHORT_CHAT'/'TOOL_REQUEST'/'DEEP_QUERY'/'CRITICAL'）；
        提供时会自动跳过对应档不需要的重型 section（LTM/anticipator/memory_gateway/skill_tree/soul），TTFT 直接砍半。
        缺省 (None) 时维持原 mode='full' 全量行为。
        """
        import json as _json, os as _os
        _t_asm_start = time.time()
        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')
        current_hour = int(time.strftime('%H'))

        core_persona = self.prompt_cache.get_or_build(
            'core_persona', lambda: JARVIS_CORE_PERSONA, ttl=86400.0
        )

        how_to_respond = self.prompt_cache.get_or_build(
            'how_to_respond', lambda: """=== HOW TO RESPOND ===
- Default: direct, concise, professional.
- If STM shows playfulness or a running joke: mirror with dry wit. Acknowledge the shared context.
- If STM shows frustration or repeated failures: drop formality, be direct and helpful.
- Scene tags: [WAKE_ONLY]=under 6 words. [WORK_MODE]=1-2 sentences max. [RELAX_MODE]=conversational but brief. These are INTERNAL routing tags — NEVER output them in your response.
- SHORT INPUT (< 5 words, semantically sparse):
  * If it resembles a mis-spoken wake word (sounds like "Jarvis"): acknowledge briefly. "Yes, Sir." Then wait.
  * Otherwise: respond to what was said. If unclear, ask briefly.
  * NEVER fabricate a connection to old STM to fill silence.
- Bilingual: Speak English ONLY. Append ---ZH--- Chinese translation at the VERY END of EVERY response. This is MANDATORY — never skip it, even when using tools.
- ASR errors: deduce true meaning from context. Ignore transcription typos.
- Desktop PC: no battery/power/charge concepts. Never reference these.
- You are a butler, not an autonomous agent. NEVER propose code changes unless asked.
- NEVER discuss your own architecture, codebase, or implementation details unless Sir explicitly asks. You are a butler, not a system diagnostic tool.

[SMART ROUTING — read these BEFORE deciding to call any tool]:
- If Sir asks about CLIPBOARD CONTENTS and `WORKING MEMORY` block above shows a recent `clipboard_copy` entry → quote it directly. DO NOT call any clipboard tool.
- If Sir asks about RECENT TERMINAL COMMANDS and `WORKING MEMORY` shows `terminal_cmd` entries → answer from those. DO NOT call any terminal tool.
- If Sir asks about RECENT WINDOW / SAVED FILE history and `WORKING MEMORY` has it → answer directly.
- If Sir references "刚才/just now/the thing I just" → almost always the answer is already in `WORKING MEMORY` or STM. Search context first.
- A failed tool call is a worse user experience than admitting "I don't see that in my memory, Sir." If unsure, say so — do not guess command names.

- TOOL USE: You have FAST_CALL tools. Use them when Sir clearly commands a NEW action that affects external state (open / set / play / launch). For queries about Sir's RECENT activity, prefer context blocks. If his intent is ambiguous or hedged, ask for confirmation first — one short question, then wait. Default to conversation when uncertain.
- MEMORY/REMINDER/CORRECTION (WRITE — set / save / correct / 设置 / 记住 / 纠正):
  When Sir asks you to remember something, set a reminder, schedule a task, OR correct a previous statement — do NOT call any tool. Instead:
  Step 1: Speak a brief acknowledgment (e.g. "Let me note that down, Sir." or "Got it, I'll correct that."). One sentence.
  Step 2: Output ---ZH--- and translate the acknowledgment.
  Step 3: Output <AWAIT_GATEKEEPER> and STOP. The Gatekeeper will handle memory storage, reminder scheduling, AND memory correction automatically.
  Step 4: After receiving the Gatekeeper result, respond naturally based on success/failure. If it was a correction, confirm the change was made.

- REMINDER/TODO LIST (READ — what reminders / todos / 代办事项 / 待办 / 提醒 / what's on my plate):
  When Sir asks WHAT his current reminders / todos / commitments are (NOT setting a new one) —
  the answer is in the ACTIVE REMINDERS / COMMITMENTS block above. Quote those items VERBATIM
  with their time labels. If the block says "(none — your reminders database is currently empty)",
  say so honestly: "Your reminders queue is clear, Sir. Nothing scheduled." DO NOT manufacture
  items from STM, the conversation, or active "projects" — those are not reminders. 承诺必行：
  reminders 数据库是唯一真实来源；编造 = 撒谎 = 重伤信任。""",
            ttl=86400.0
        )

        tier_routing = self.prompt_cache.get_or_build(
            'tier_routing', lambda: """[3-TIER ROUTING & FAST TOOLS]:
- Tier 1 (Chat): No tools. Chat naturally. ALWAYS end with ---ZH--- and Chinese translation.

- Tier 2 (Fast Tools): Verbosity adapts to action complexity. Pick mode by judgement:

  [SIMPLE actions] — single tool, obvious params, reversible/safe (open file, search, copy, launch, query info):
    • NO intro. Emit <FAST_CALL>{...}</FAST_CALL> immediately after Sir's request.
    • After result, ONE short confirmation: "Done, Sir." / "Here you are." / "Open." / "Got it."
    • Then ---ZH--- + brief Chinese ("完成。" / "已打开。" / "在这里。").
    • Example flow — Sir: "open D drive" → you: <FAST_CALL>... → result → "Open." ---ZH--- 已打开。

  [COMPLEX actions] — multi-tool chain, ambiguous params, destructive (delete/move), or Sir needs awareness:
    • Brief intro (ONE sentence max): "Pulling the logs now, Sir." / "Let me check that for you."
    • ---ZH--- (brief translation).
    • <FAST_CALL>{...}</FAST_CALL>. Chain silently between tools (no talking between calls).
    • When ALL done, ONE concluding sentence summarizing the outcome.
    • Final ---ZH---.

  HOW TO PICK MODE:
    • If Sir's intent is unambiguous AND one tool suffices AND no risk → SIMPLE.
    • If you need to think about params, or chain multiple tools, or the action is irreversible → COMPLEX.
    • When in doubt: prefer SIMPLE. The action itself is the answer.
    • NEVER pad with "Let me X for you" or "I shall now Y" — these are noise, not service.

- Tier 3 (Deep Workflow): >=3 tools, visual UI, or true autonomous task. Output <REQUEST_PHYSICAL>.

- Error Handling: If a FAST_CALL fails, admit it plainly in your concluding sentence ("That didn't take, Sir."). 
  NEVER say "I have done X" when X just failed — that is the worst kind of dishonesty.

- Output <IGNORE> for side-conversations.
- Output [CLIPBOARD] for code/content at the VERY END.""",
            ttl=86400.0
        )

        time_persona = self.prompt_cache.get_or_build(
            f'time_persona_{current_hour}',
            lambda: self._build_time_persona(current_hour),
            ttl=3600.0
        )

        profile_file = _os.path.join("jarvis_config", "sir_profile.json")
        sir_profile = {}
        if _os.path.exists(profile_file):
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    sir_profile = _json.load(f)
            except: pass

        jokes_list = sir_profile.get("our_inside_jokes", [])
        jokes_str = "\n".join([f"  - {j}" for j in jokes_list[-5:]]) if jokes_list else "  (none yet)"
        milestones = sir_profile.get("significant_milestones", [])
        milestones_str = "\n".join([f"  - {m}" for m in milestones[-5:]]) if milestones else "  (none yet)"
        projects = sir_profile.get("active_projects", [])
        projects_str = ", ".join(projects[-5:]) if projects else "(none)"
        progression = sir_profile.get("skill_progression", [])
        progression_str = "\n".join([f"  - {s.get('skill','?')} (confidence: {s.get('confidence','?')})" for s in progression[-5:]]) if progression else "  (none yet)"

        self.habit_clock.update_from_probe()
        _t_ctx_start = time.time()
        context_str = self.context_router.assemble(current_hour)
        _t_ctx_done = time.time()

        hc_prediction = self.habit_clock.predict_current_state()
        if hc_prediction.get('anomaly_detected'):
            try:
                self.profile_card.apply_correction(
                    'habit_clock',
                    'behavioral_patterns.anomaly',
                    'normal_routine',
                    hc_prediction.get('anomaly_detail', ''),
                    0.6
                )
            except Exception:
                pass

        work_cat = PhysicalEnvironmentProbe.current_work_category
        if work_cat == "Coding":
            proc_name = PhysicalEnvironmentProbe.current_process_name
            if proc_name and proc_name != "Unknown":
                self.hippocampus.track_project_activity(proc_name, PhysicalEnvironmentProbe.work_duration_minutes)

        ledger_str = _json.dumps(ledger_data, ensure_ascii=False) if ledger_data else "No status data"

        life_log_context = ""
        try:
            if hasattr(self, 'status_ledger'):
                life_log_context = self.status_ledger.get_recent_daily_summaries(days=3)
        except:
            pass

        soul_chapters_str = ""
        if soul_tags:
            chapter_blocks = []
            if "projects" in soul_tags:
                chapter_blocks.append(f"Active Projects: {projects_str}")
            if "inside_jokes" in soul_tags:
                chapter_blocks.append(f"Inside Jokes:\n{jokes_str}")
            if "milestones" in soul_tags:
                chapter_blocks.append(f"Significant Milestones:\n{milestones_str}")
            if "progression" in soul_tags:
                chapter_blocks.append(f"Skill Progression:\n{progression_str}")
            if chapter_blocks:
                soul_chapters_str = "=== RELEVANT CONTEXT ===\n" + "\n".join(chapter_blocks)

        correction_context = ""
        style_adjustment = ""
        if hasattr(self, 'correction_loop'):
            correction_context = self.correction_loop.get_correction_context(user_input)
            style_adjustment = self.correction_loop.get_style_adjustment()

        content_pref = ""
        if hasattr(self, 'content_tracker'):
            content_pref = self.content_tracker.get_preferred_style()

        # [R6/Tier] 按 prompt_tier 决定要不要付出"重型 section"的 API/计算开销
        # 砍法：
        # - WAKE_ONLY: 全部跳过（一句话回应不需要）
        # - FACTUAL_RECALL: 跳过 LTM/anticipator/skill_tree（答案在 working_feed/event_bus/STM 里）
        # - SHORT_CHAT: 跳过 anticipator + skill_tree + memory_gateway 重检索
        # - 其他档：保持原"full"行为
        _skip_heavy = prompt_tier in (
            self.PROMPT_TIER_WAKE_ONLY,
            self.PROMPT_TIER_SHORT_CHAT,
            self.PROMPT_TIER_FACTUAL_RECALL,
        )
        _allow_full = (mode == "full") and (prompt_tier not in (
            self.PROMPT_TIER_WAKE_ONLY,
            self.PROMPT_TIER_FACTUAL_RECALL,
        ))

        unified_memory = ""
        if hasattr(self, 'memory_gateway') and _allow_full and not _skip_heavy:
            _t_mem_start = time.time()
            unified_memory = self.memory_gateway.to_prompt_block(user_input, top_k=3)
            _t_mem_done = time.time()

        skill_tree_str = ""
        if hasattr(self, 'skill_tree') and _allow_full and not _skip_heavy:
            _t_skill_start = time.time()
            skill_tree_str = self.skill_tree.get_skill_summary_for_prompt()
            _t_skill_done = time.time()

        anticipator_ctx = ""
        if hasattr(self, 'prompt_center') and self.prompt_center and self.prompt_center.anticipator and not _skip_heavy:
            _t_anti_start = time.time()
            anticipator_ctx = self.prompt_center.anticipator.get_preloaded_context()
            _t_anti_done = time.time()

        commitment_context = ""
        if pending_commitment:
            desc = pending_commitment.get("description", "")
            deadline = pending_commitment.get("deadline", "")
            commitment_context = f"""[COMMITMENT DETECTED]: Sir just made a commitment: "{desc}"
Deadline: {deadline if deadline else 'unspecified'}
ACTION REQUIRED: Acknowledge this commitment in your response. Say something like "Noted, Sir. I'll remind you{f' at {deadline}' if deadline else ''}." 
Then proceed with the rest of your response normally.
"""

        # [轴 2.1 / 2026-05-15] OPEN THREADS —— 老友感 callback 基础
        # 扫 STM 抓 Jarvis 自己说过的承诺动词（"I'll check..." / "我看一下" 等），
        # 渲染成 "still owed to Sir" 块。所有 tier 共用此计算（轻量，几毫秒）。
        # 主脑下一轮看到 → 自然 callback（Sir 不用追问"我刚那个怎么样"）
        open_threads_block = ""
        try:
            from jarvis_utils import extract_open_threads, render_open_threads_block
            threads = extract_open_threads(
                self.short_term_memory,
                max_age_seconds=1800.0,  # 30 min
                max_threads=4,
            )
            open_threads_block = render_open_threads_block(threads, max_chars=400)
        except Exception:
            open_threads_block = ""

        # [轴 2.2 / 2026-05-15] CURRENT PROJECT —— 项目维度感知
        # foreground 窗口的进程 cwd up-walk 找 .git → 项目名
        # 主脑下一轮看到 → 切到 dJarvis 仓库时立刻知道在哪个项目
        project_block = ""
        try:
            probe = getattr(self, 'project_probe', None)
            if probe is not None:
                from jarvis_utils import render_project_block
                project_block = render_project_block(probe.get_current_project(), max_chars=200)
        except Exception:
            project_block = ""

        # [轴 2.3 / 2026-05-15] YESTERDAY —— 接得上昨晚
        # 读 DailyChronicle 写的 daily_{yesterday}.json，合成短摘要注入 prompt 顶部
        # Sir 提"昨晚 / yesterday" → 主脑能引用 dominant_activity / notable_moment
        yesterday_block = ""
        try:
            sd = getattr(self, 'session_digest', None)
            if sd is not None:
                from jarvis_utils import render_yesterday_block
                digest = sd.get_yesterday_digest()
                yesterday_block = render_yesterday_block(digest, max_chars=400)
        except Exception:
            yesterday_block = ""

        # [轴3-L2 / 2026-05-15] AVAILABLE SKILLS —— 言出必行的能力地图（动态、不 cache）
        # 让主脑知道"现在我真能做什么"，避免承诺空头能力。
        # only_healthy=True 排除 30d 成功率不达 0.7 的；max_skills=30 控 prompt 体积。
        # **关键**：to_prompt_block 的 directive 含 "Generic offers FORBIDDEN" 强约束。
        available_skills_block = ""
        try:
            from jarvis_skill_registry import get_registry
            available_skills_block = get_registry().to_prompt_block(
                only_healthy=True,
                max_skills=30,
            )
        except Exception:
            available_skills_block = ""

        # [P0+18-d.1 / 2026-05-15] ACTIVE REMINDERS / COMMITMENTS —— 主脑 ↔ 待办数据库打通
        #
        # 修 Sir 主诉根因（log:829-882）：
        #   Sir: "把我代办事项都列出来" → Jarvis 凭 LLM 上下文猜了 3 个"项目"
        #   Sir: "刚才不是说要你明天提醒我..." → Jarvis 凭空编造"明天下午3点取快递"
        #
        # 原因：prompt 完全没有把 TaskMemories DB 里 is_future_task=1 的真实 reminders
        # 和 CommitmentWatcher in-memory 的真实 commitments 注入到主脑视野，主脑只能猜。
        #
        # 修法：把 active reminders + commitments 各拉 top 5 渲染成 prompt block，
        # 主脑回答"代办/todo/提醒/reminder"类问题时，照实念这个 block。
        # 配合 [HOW TO LIST TODOS] directive（紧接其后注入），让 LLM 学会"先看 block，
        # block 空就直说没有 — 禁止从 STM/上下文编"。
        active_reminders_block = ""
        try:
            from jarvis_utils import render_active_reminders_block
            db_reminders = []
            try:
                hc = getattr(self, 'hippocampus', None)
                if hc is not None and hasattr(hc, '_get_conn'):
                    _now_ts = time.time()
                    conn = hc._get_conn()
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, user_intent, trigger_time FROM TaskMemories "
                        "WHERE is_future_task = 1 AND is_deleted = 0 "
                        "ORDER BY trigger_time ASC LIMIT 10"
                    )
                    for r in cur.fetchall():
                        db_reminders.append({
                            "id": r[0],
                            "intent": r[1] or "",
                            "trigger_time": float(r[2] or 0.0),
                        })
                    conn.close()
            except Exception:
                db_reminders = []
            cw_commitments = []
            try:
                cw = getattr(self, 'commitment_watcher', None)
                if cw is not None and hasattr(cw, 'commitments'):
                    for c in list(cw.commitments)[-5:]:
                        if c.get('nudged'):
                            continue
                        cw_commitments.append({
                            "description": c.get('description', ''),
                            "deadline_ts": float(c.get('deadline_ts') or 0.0),
                            "source_text": c.get('source_text', ''),
                        })
            except Exception:
                cw_commitments = []
            active_reminders_block = render_active_reminders_block(
                db_reminders, cw_commitments, max_chars=800
            )
        except Exception:
            active_reminders_block = ""

        # [轴3-L3.1 / 2026-05-15] PROMISE PROTOCOL —— multi-step 承诺协议
        # 教主脑用 <PROMISE> 标签声明承诺；stream_chat 末尾会解析 → ledger.draft(awaiting_go)
        # Sir 说 "go/yes" 才执行；修 Cs3 "I'll look into" 泛化承诺。
        promise_protocol_directive = ""
        try:
            from jarvis_skill_registry import PROMISE_PROTOCOL_DIRECTIVE
            promise_protocol_directive = PROMISE_PROTOCOL_DIRECTIVE
        except Exception:
            promise_protocol_directive = ""

        # [P0+18-a.16 / 2026-05-15] TOOL HONESTY —— 承诺必行的硬约束块
        # 拦"我可以运行 X 来查 Y"型越界许诺（详见 jarvis_skill_registry.CapabilityClaimValidator）
        # 注入位置：紧跟 AVAILABLE SKILLS 后、PROMISE PROTOCOL 前 — 阅读顺序：
        #   1. 看到我能做什么 (AVAILABLE SKILLS)
        #   2. 看到承诺时的诚信约束 (TOOL HONESTY)  ← 本块
        #   3. 看到多步动作格式 (PROMISE PROTOCOL)
        tool_honesty_directive = ""
        try:
            from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE
            tool_honesty_directive = TOOL_HONESTY_DIRECTIVE
        except Exception:
            tool_honesty_directive = ""

        # [P0+18-b.8 / 2026-05-15] FUZZY CANDIDATES POLICY —— "找不到时不装跑"
        # 工具返回 fuzzy_candidates 时主脑必须反向问 Sir 确认，禁止硬选 top1 直跑。
        # 配合 process_hands 的 NotFound fallback（拉真实进程名做 difflib 模糊匹配）。
        # 与 TOOL HONESTY 同属"承诺必行"系列：那个管 pre-action 许诺，本块管 post-action 结果。
        fuzzy_candidates_policy = ""
        try:
            from jarvis_fuzzy_resolver import FUZZY_CANDIDATES_POLICY
            fuzzy_candidates_policy = FUZZY_CANDIDATES_POLICY
        except Exception:
            fuzzy_candidates_policy = ""

        if mode == "mail":
            # [P0+18-c.2 / 2026-05-15] 修 Sir 主诉 BUG：reminder 触发后反问"要不要设倒计时"
            # 触发文案虽然改了，但 mail mode prompt 最小化，LLM 仍然可能用过去时框架回。
            # 注入 REMINDER_FIRING_DIRECTIVE 含 anti-patterns + 正例，让 LLM 学会立刻执行。
            reminder_firing_directive = """
================================================================================
CRITICAL — REMINDER DELIVERY MODE (READ FIRST)
================================================================================
If user_input contains "[REMINDER FIRING NOW]", you are DELIVERING a reminder
whose countdown has ALREADY elapsed. Sir is waiting for the alert RIGHT NOW.

❌ FORBIDDEN phrases (LLM 常犯错的"过去时框架"，必须杜绝):
   - "shall I set a countdown" / "would you like me to remind"
   - "do you want" / "需要为您设置" / "要不要" / "Shall I"
   - "you requested a reminder" / "您曾要求" (past-tense framing)
   - "according to the memory protocol" / "根据您的记忆协议" (bureaucratic preamble)
   - "I should like to bring to your attention" (浮夸的前缀)

✅ CORRECT delivery (short, present-tense imperative, ≤2 sentences):
   - Original request: "提醒我两分钟后喝水" → You say: "Sir, time to hydrate." / "Sir，该喝水了。"
   - Original request: "下午3点开会" → You say: "Sir, your meeting is starting." / "Sir，会议时间到了。"
   - Original request: "明天 10 点拿快递" → You say: "Sir, time to pick up the package." / "Sir，该去拿快递了。"
   - Original request: "晚上 9 点吃药" → You say: "Sir, time for your medication." / "Sir，该吃药了。"

Algorithm: extract the action verb + object from "Sir's original request"
(the part AFTER the time anchor), then deliver as present-tense imperative.
Do NOT re-confirm. Do NOT ask permission. Do NOT explain how you know.

================================================================================
"""
            return f"""{core_persona}

{reminder_firing_directive}
{context_str}
[SYSTEM CLOCK]: {current_time}
[BILINGUAL DIRECTIVE]: Speak English. Append `---ZH---` Chinese subtitle at the VERY END. This is MANDATORY.
{user_input}
"""

        # [R7-β1] FACTUAL_RECALL 短路返回：近期事实查询，答案大概率已在
        # working_feed / event_bus / STM / attention 里。绝对禁止调用工具，目标 TTFT < 2s。
        if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:
            _fr_working = ""
            try:
                feed = getattr(self, 'working_feed', None)
                if feed is not None:
                    # FACTUAL_RECALL 要把 working_feed 拉得更宽一点（1 小时 + 较多事件 + 较多字符）
                    _fr_working = feed.to_prompt_block(max_chars=700, within_seconds=3600.0)
            except Exception:
                pass
            _fr_attention = ""
            try:
                slot = getattr(self, '_attention_slot', None)
                if slot is not None:
                    from jarvis_utils import render_attention_block
                    _snap = slot.latest(max_age_seconds=8.0)
                    if _snap:
                        _fr_attention = render_attention_block(_snap, max_chars=300)
            except Exception:
                pass
            _fr_bus = ""
            try:
                bus = getattr(self, 'event_bus', None)
                if bus is not None:
                    _fr_bus = bus.to_prompt_block(max_chars=350, within_seconds=600.0)
            except Exception:
                pass
            # STM 拉宽到 6 条（FACTUAL_RECALL 经常要回看刚说过的话）
            short_stm = stm_context
            if short_stm and len(short_stm) > 1200:
                short_stm = "..." + short_stm[-1200:]
            # [R7-β3] Tone Directive（FACTUAL_RECALL 也带 tone 让回答有 persona 味）
            _fr_tone = ""
            try:
                ts = getattr(self, 'tone_selector', None)
                if ts is not None:
                    _t_id, _t_desc = ts.select(user_input=user_input,
                                               ledger_data=ledger_data,
                                               hour=current_hour)
                    _fr_tone = ts.render_directive(_t_id, _t_desc)
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"🎭 [Tone] {_t_id}  (hour={current_hour}, tier=FACTUAL_RECALL)")
                    except Exception:
                        pass
            except Exception:
                pass
            return f"""{core_persona}

{_fr_tone}

=== HOW TO RESPOND (FACTUAL_RECALL — 近期事实查询) ===
Sir is asking about something that JUST happened or is in your immediate context.
DO NOT call any tool. The answer is already in the context blocks below — find it and answer directly.

Priority order to find the answer:
1. WORKING MEMORY (clipboard / terminal command / file saved / window switch history)
2. WHAT JUST HAPPENED (STM)
3. CONVERSATION STATE (event_bus — recent breakthroughs / callbacks / commitments)
4. ATTENTION (current window / cursor)

Reply in ONE sentence. Quote the actual content if relevant (e.g. for clipboard contents,
quote the first 60 chars). Append `---ZH---` and Chinese at the end.

If none of the above sources have the answer, say so honestly:
"I don't have that in my immediate memory, Sir — could you give me a hint?"
Do NOT fabricate. Do NOT call tools — even if a tool *might* know the answer, the user
expects an instant reply from your recent memory, not a tool round-trip.

{yesterday_block}

=== WHAT JUST HAPPENED ===
{short_stm}

{open_threads_block}

{project_block}

{available_skills_block}

{_fr_bus}

{_fr_attention}

{_fr_working}

[SYSTEM CLOCK]: {current_time}
[BILINGUAL DIRECTIVE]: Speak English. Append `---ZH---` Chinese subtitle at the VERY END.
User: {user_input}
{system_alert_text}
"""

        # [R6/Tier] WAKE_ONLY 短路返回：只塞核心人设 + 最近 3 条 STM + 一句指令
        # 目标 prompt 体积 ≤ 1.5K，TTFT 期望降到 1s 以内
        if prompt_tier == self.PROMPT_TIER_WAKE_ONLY:
            # STM 只看最近 3 条对话（更短）
            short_stm = stm_context
            if short_stm and len(short_stm) > 500:
                short_stm = "..." + short_stm[-500:]
            return f"""{core_persona}

=== HOW TO RESPOND (WAKE_ONLY) ===
Sir just called your name. Reply in UNDER 6 WORDS.
- If recent STM shows ongoing conversation, acknowledge briefly: "Yes, Sir?" / "I'm here."
- If no recent context: just "Sir?" / "At your service."
- NEVER fabricate. NEVER ask questions.
- Append `---ZH---` and a 1-3 character Chinese acknowledgment at the very end.

=== RECENT TURNS ===
{short_stm}

[SYSTEM CLOCK]: {current_time}
User: {user_input}
{system_alert_text}
"""

        # [R6/Tier] SHORT_CHAT 中档：核心人设 + STM + ledger + event_bus；不带 LTM/skill_tree/anticipator
        # [P0+18-a.3 / 2026-05-15] 注入 PROMISE_PROTOCOL_DIRECTIVE_MINI — 修 BUG #2:
        # 之前 SHORT_CHAT tier 完全没注入 PROMISE 协议，导致 Sir 说"排查 403"等多步动作时
        # 主脑根本不知道要写 <PROMISE>，直接编答案 → Integrity Check 抓 hallucination
        if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:
            # event_bus 快速渲染（只取 240s 内事件，把 prompt 控制到中等体积）
            _short_bus = ""
            try:
                bus = getattr(self, 'event_bus', None)
                if bus is not None:
                    _short_bus = bus.to_prompt_block(max_chars=350, within_seconds=240.0)
            except Exception:
                _short_bus = ""
            # [R7-α/AttentionContext] SHORT_CHAT 档也要带 attention（短聊也常用"这个/这里"）
            _short_attn = ""
            try:
                slot = getattr(self, '_attention_slot', None)
                if slot is not None:
                    from jarvis_utils import render_attention_block
                    _snap = slot.latest(max_age_seconds=8.0)
                    if _snap:
                        _short_attn = render_attention_block(_snap, max_chars=300)
            except Exception:
                _short_attn = ""
            # [R7-α/WorkingMemoryFeed] SHORT_CHAT 档也带工作台事件（限到 300 字保持轻）
            _short_feed = ""
            try:
                _feed = getattr(self, 'working_feed', None)
                if _feed is not None:
                    _short_feed = _feed.to_prompt_block(max_chars=300, within_seconds=900.0)
            except Exception:
                _short_feed = ""
            # [R7-β3] Tone Directive
            _short_tone = ""
            try:
                ts = getattr(self, 'tone_selector', None)
                if ts is not None:
                    _t_id, _t_desc = ts.select(user_input=user_input,
                                               ledger_data=ledger_data,
                                               hour=current_hour)
                    _short_tone = ts.render_directive(_t_id, _t_desc)
                    # [R7-β1/post-test] SHORT_CHAT 也要 bg_log，让 Sir 复盘
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"🎭 [Tone] {_t_id}  (hour={current_hour}, tier=SHORT_CHAT)")
                    except Exception:
                        pass
            except Exception:
                pass

            # [P0+18-a.3] PROMISE_PROTOCOL mini directive 注入 — 让 SHORT_CHAT tier 主脑
            # 也知道"多步动作要写 <PROMISE>"，避免 Sir 说"排查 403"时主脑直接编答案
            _short_promise_mini = ""
            try:
                from jarvis_skill_registry import PROMISE_PROTOCOL_DIRECTIVE_MINI
                _short_promise_mini = PROMISE_PROTOCOL_DIRECTIVE_MINI
            except Exception:
                _short_promise_mini = ""

            # [P0+18-a.16] TOOL HONESTY mini —— 拦"我能用 X 来查 Y"型越界许诺（短档版 ~400字）
            # 这次 bug (process_hands.get_process_info → 查 logged errors) 主响应也走 SHORT_CHAT，
            # 因此必须把这条软约束注入 SHORT_CHAT，否则 mini 形式根本看不到约束。
            _short_tool_honesty = ""
            try:
                from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE_MINI
                _short_tool_honesty = TOOL_HONESTY_DIRECTIVE_MINI
            except Exception:
                _short_tool_honesty = ""

            # [P0+18-b.8] FUZZY CANDIDATES POLICY —— SHORT_CHAT 也要带（"查 XYZ 进程"经常分到 SHORT_CHAT）
            _short_fuzzy_policy = ""
            try:
                from jarvis_fuzzy_resolver import FUZZY_CANDIDATES_POLICY
                _short_fuzzy_policy = FUZZY_CANDIDATES_POLICY
            except Exception:
                _short_fuzzy_policy = ""

            # [P0+18-a.3] 同时注入 ACTIVE PLAN 块（如果有 paused/awaiting_go plan，
            # SHORT_CHAT 也要让主脑看见，否则 Sir 说"go"时主脑没上下文）
            _short_active_plan = ""
            try:
                pl = getattr(self, 'plan_ledger', None)
                if pl is not None:
                    _short_active_plan = pl.to_prompt_block(max_chars=400)
            except Exception:
                _short_active_plan = ""

            return f"""{core_persona}

{yesterday_block}

=== WHAT JUST HAPPENED ===
{stm_context}

{open_threads_block}

{project_block}

{available_skills_block}

{_short_tool_honesty}

{_short_fuzzy_policy}

{_short_promise_mini}

{_short_active_plan}

{_short_bus}

{_short_attn}

{_short_feed}

{_short_tone}

{how_to_respond}

=== TIME CONTEXT ===
{time_persona}

{context_str}
{self.profile_card.to_prompt_block()}
{correction_context}
{style_adjustment}

=== REAL-TIME STATE ===
{ledger_str}

[SYSTEM CLOCK]: {current_time}
[BILINGUAL DIRECTIVE]: Speak English. Append `---ZH---` Chinese subtitle at the VERY END.
User: {user_input}
{system_alert_text}
"""

        if mode == "light":
            return f"""{core_persona}

{context_str}
{self.profile_card.to_prompt_block()}
{correction_context}
{style_adjustment}
{content_pref}
[BILINGUAL DIRECTIVE]: Speak English. Append `---ZH---` Chinese subtitle at the VERY END.
[SYSTEM CLOCK]: {current_time}
[SEARCH DIRECTIVE]: For questions about current events, recent news, real-time data, or anything that requires up-to-date information, you MUST use Google Search. Do NOT rely on your training data for time-sensitive queries.
User: {user_input}
{system_alert_text}
"""
        _t_asm_done = time.time()
        _sub_timings = []
        if '_t_ctx_done' in dir(): _sub_timings.append(f"context_router={_t_ctx_done - _t_ctx_start:.1f}s")
        if '_t_mem_done' in dir(): _sub_timings.append(f"memory_gateway={_t_mem_done - _t_mem_start:.1f}s")
        if '_t_skill_done' in dir(): _sub_timings.append(f"skill_tree={_t_skill_done - _t_skill_start:.1f}s")
        if '_t_anti_done' in dir(): _sub_timings.append(f"anticipator={_t_anti_done - _t_anti_start:.1f}s")
        _sub_str = " | ".join(_sub_timings) if _sub_timings else "无子模块"

        # [R6/B1] 从 ConversationEventBus 渲染一段对话状态块（突破/回调/承诺/焦点/拒绝/情绪）
        # —— 给 LLM 物理事实，不让它编"老友感"
        event_bus_block = ""
        try:
            bus = getattr(self, 'event_bus', None)
            if bus is not None:
                event_bus_block = bus.to_prompt_block(max_chars=600, within_seconds=360.0)
        except Exception:
            event_bus_block = ""

        # [R7-α/AttentionContext] 注意力锚点：Sir 讲话当下盯着的窗口/光标位置/最近窗口切换。
        # 用 ≤ 5s 内的快照，过时则丢（避免把陈旧 attention 当成"现在"）。
        # 让 LLM 解 "这里/这个/那段" 这类指代成本接近零。
        attention_block = ""
        try:
            slot = getattr(self, '_attention_slot', None)
            if slot is not None:
                from jarvis_utils import render_attention_block
                snap = slot.latest(max_age_seconds=8.0)
                if snap:
                    attention_block = render_attention_block(snap, max_chars=400)
        except Exception:
            attention_block = ""

        # [R7-α/WorkingMemoryFeed] 会话级环境事件流：30 分钟内 Sir 在物理工作台做过什么。
        # 让 LLM 答"我刚复制的是什么 / 我刚跑的那个命令是什么"成本接近零。
        working_feed_block = ""
        try:
            feed = getattr(self, 'working_feed', None)
            if feed is not None:
                working_feed_block = feed.to_prompt_block(max_chars=500, within_seconds=1800.0)
        except Exception:
            working_feed_block = ""

        # [R7-α/PlanLedger] 当前 active plan（drafted / awaiting_go / running / paused）。
        # 如果有 plan 在 awaiting_go，prompt 末尾会提示 Sir 可以说 "go" 启动。
        active_plan_block = ""
        try:
            pl = getattr(self, 'plan_ledger', None)
            if pl is not None:
                active_plan_block = pl.to_prompt_block(max_chars=600)
        except Exception:
            active_plan_block = ""

        # [轴 2.1] open_threads_block 已在前面 commitment_context 之后计算 —— 所有 tier 共用

        # [R7-β3] Tone Directive：根据 ledger 情绪 + 时段 + 硬触发词选 tone
        tone_directive = ""
        try:
            ts = getattr(self, 'tone_selector', None)
            if ts is not None:
                tone_id, tone_desc = ts.select(
                    user_input=user_input,
                    ledger_data=ledger_data,
                    hour=current_hour,
                )
                tone_directive = ts.render_directive(tone_id, tone_desc)
                # [R7-β1/post-test] 把选到的 tone 打到背景日志，方便 Sir 在终端复盘
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🎭 [Tone] {tone_id}  (hour={current_hour})")
                except Exception:
                    pass
        except Exception:
            tone_directive = ""

        # [R7-β4] AVOID PHRASES & VERBOSITY DIRECTIVE
        # phrase_tracker / verbosity_tracker 由 CentralNerve 持有；这里只读 prompt 块。
        # observe + record_reply 由 stream_chat 在合适位置触发（先观察 user_input，再渲染 prompt）
        avoid_phrases_block = ""
        try:
            pt = getattr(self, 'phrase_tracker', None)
            if pt is not None:
                avoid_phrases_block = pt.to_prompt_block(min_days=4, top_k=6)
        except Exception:
            avoid_phrases_block = ""
        verbosity_block = ""
        try:
            vt = getattr(self, 'verbosity_tracker', None)
            if vt is not None:
                verbosity_block = vt.to_prompt_block()
        except Exception:
            verbosity_block = ""

        result = f"""{core_persona}

{yesterday_block}

=== WHAT JUST HAPPENED ===
{stm_context}

[CONTINUITY RULE]: You are in the MIDDLE of a conversation. If Sir references or builds on anything above, acknowledge the connection naturally. A callback to a running topic is conversational coherence, not forced humor.

{open_threads_block}

{project_block}

{active_reminders_block}

{available_skills_block}

{tool_honesty_directive}

{fuzzy_candidates_policy}

{promise_protocol_directive}

{event_bus_block}

{attention_block}

{working_feed_block}

{active_plan_block}

{tone_directive}

{avoid_phrases_block}

{verbosity_block}

{soul_chapters_str}
{how_to_respond}

=== TIME CONTEXT ===
{time_persona}

{context_str}

{self.profile_card.to_prompt_block()}

{correction_context}
{style_adjustment}
{content_pref}
{unified_memory}
{skill_tree_str}
{anticipator_ctx}

=== REAL-TIME STATE ===
{ledger_str}

[RECENT LIFE LOG]:
{life_log_context}

[SYSTEM ENVIRONMENT]:
Windows OS is in Chinese. Use Chinese folder names in tool parameters.
Path landmarks:
{landmarks_str}

[IMAGE CONTEXT]: Real-time screenshot attached. Use as ultimate truth.

{tier_routing}

[Tier 2 Tool Library]:
{chat_organs}

[YOUR KNOWLEDGE BASE]:
--- Long-Term Memory ---
{ltm_context}

[MEMORY CALLBACK]: Reference relevant memories naturally. Use sparingly.

{commitment_context}
[SYSTEM CLOCK]: {current_time}
[SEARCH DIRECTIVE]: For questions about current events, recent news, real-time data, or anything that requires up-to-date information, you MUST use Google Search. Do NOT rely on your training data for time-sensitive queries.
User: {user_input}
{system_alert_text}
"""
        _sizes = {
            'core_persona': len(core_persona),
            'stm_context': len(stm_context),
            'event_bus': len(event_bus_block),  # [R6/B1]
            'how_to_respond': len(how_to_respond),
            'time_persona': len(time_persona),
            'context_str': len(context_str),
            'profile_block': len(self.profile_card.to_prompt_block()),
            'correction': len(correction_context),
            'style': len(style_adjustment),
            'content_pref': len(content_pref),
            'unified_memory': len(unified_memory),
            'skill_tree': len(skill_tree_str),
            'anticipator': len(anticipator_ctx),
            'ledger': len(ledger_str),
            'life_log': len(life_log_context),
            'landmarks': len(landmarks_str),
            'tier_routing': len(tier_routing),
            'chat_organs': len(chat_organs),
            'ltm_context': len(ltm_context),
            'commitment': len(commitment_context),
            'user_input': len(user_input),
            'system_alert': len(system_alert_text),
            'soul_chapters': len(soul_chapters_str),
        }
        _big = [(k, v) for k, v in _sizes.items() if v > 500]
        _big.sort(key=lambda x: -x[1])
        _size_report = " | ".join([f"{k}={v}" for k, v in _big[:8]])
        # [P0+18-f.5 / 2026-05-15] 加 prompt 装配总耗时 + queue depth 到后台日志
        _asm_total_ms = int((time.time() - _t_asm_start) * 1000)
        try:
            from jarvis_utils import bg_log
            try:
                from jarvis_utils import _TEE_QUEUE as _tee_q_asm
                _q_depth_asm = _tee_q_asm.qsize()
            except Exception:
                _q_depth_asm = -1
            bg_log(f"⏱️ [Prompt Size] 总{len(result)}chars | TOP: {_size_report}")
            bg_log(f"🔬 [Asm Diag] _assemble_prompt 总耗时 {_asm_total_ms}ms | tee_queue_depth={_q_depth_asm}")
        except Exception:
            print(f"⏱️ [Prompt Size] 总{len(result)}chars | TOP: {_size_report}", file=sys.stderr)
        return result

    def _build_time_persona(self, current_hour: int) -> str:
        if 5 <= current_hour < 12:
            return "MORNING: Sir just started the day. Be crisp and efficient. A brief greeting is appropriate if this is the first interaction."
        elif 12 <= current_hour < 18:
            return "AFTERNOON: Peak productivity hours. Be maximally efficient and direct. No small talk."
        elif 18 <= current_hour < 23:
            return "EVENING: Wind-down period. You may be slightly more conversational. Dry wit is more welcome now."
        else:
            return "LATE NIGHT: It is past midnight. Keep responses EXTREMELY brief — one or two sentences max. Do NOT be chatty."

    def _init_soul_router(self):
        import json, os
        profile_file = os.path.join("jarvis_config", "sir_profile.json")
        if os.path.exists(profile_file):
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                self.soul_router = SoulRouter(profile)
            except Exception:
                self.soul_router = None

    def preload_session_context(self) -> str:
        """P4 会话上下文预加载：根据当前工作类别 + 时段，主动检索海马体相关记忆，附带新鲜度权重"""
        try:
            work_category = PhysicalEnvironmentProbe.current_work_category
            work_duration = PhysicalEnvironmentProbe.work_duration_minutes
            current_hour = int(time.strftime("%H"))
            
            query_parts = []
            
            if work_category == "Coding":
                query_parts.append("编程 代码 开发")
            elif work_category == "Media":
                query_parts.append("视频 音乐 娱乐")
            elif work_category == "AFK":
                query_parts.append("休息 离开")
            
            if current_hour >= 22 or current_hour < 6:
                query_parts.append("深夜 晚间")
            elif 6 <= current_hour < 12:
                query_parts.append("早晨 上午")
            elif 12 <= current_hour < 18:
                query_parts.append("下午")
            else:
                query_parts.append("傍晚 晚上")
            
            if work_duration > 120:
                query_parts.append("长时间工作 马拉松")
            
            if not query_parts:
                return ""
            
            search_query = " ".join(query_parts)
            results = self.hippocampus.search_memory(self.gemini_key, search_query, top_k=3)
            
            if results:
                now = time.time()
                context = "\n[SESSION CONTEXT - Proactively recalled from hippocampus based on current activity]:\n"
                for r in results:
                    time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['timestamp']))
                    age_hours = (now - r['timestamp']) / 3600
                    
                    if age_hours < 24:
                        freshness = "🔥 RECENT"
                    elif age_hours < 168:
                        freshness = "📅 THIS WEEK"
                    else:
                        freshness = "📦 ARCHIVE"
                    
                    context += f"- [{time_str}] ({freshness}) {r['intent']} → {r['summary']}\n"
                
                context += "\n[MEMORY CALLBACK DIRECTIVE]:\n"
                context += "If any recalled memory above is highly relevant to Sir's current question or situation,\n"
                context += "naturally reference it in your response. For example:\n"
                context += "- 'As we discussed yesterday...'\n"
                context += "- 'This relates to your HUD project from last week...'\n"
                context += "- 'Sir, you asked about this on Tuesday...'\n"
                context += "This makes our interaction feel continuous and personal. Use sparingly — only when genuinely relevant.\n"
                return context
        except Exception:
            pass
        return ""

    def _process_concurrent_interruption(self, new_cmd):
        """⚡ 第三层聊天引擎：并发闲聊与天启判决层 (Unified Concurrent Engine)"""
        if not hasattr(self, 'chat_bypass'): return

        if hasattr(self, 'correction_loop'):
            self.correction_loop.on_user_input(new_cmd)

        current_task_status = self.blood.macro_goal
        stm_context = "\n".join([f"{m['user']} -> {m['jarvis']}" for m in self.short_term_memory[-6:]])
        if len(stm_context) > 2000:
            stm_context = "..." + stm_context[-2000:]
        # 直接继承 ChatBypass 缓存的海马体长时记忆
        ltm_context = getattr(self.chat_bypass, 'last_ltm_context', 'None')
        chat_organs = ", ".join(self.hand_manifests.keys())
        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')

        prompt = f"""You are Jarvis, my highly advanced personal AI assistant and digital butler. 
Persona: Highly intelligent, calm, polite, incredibly loyal, with a touch of sophisticated British dry wit.

[RELATIONSHIP & CONVERSATION RULES]:
1. We have been working together for a long time. Act like an old, trusted friend. DO NOT act like this is our first interaction.
2. NEVER introduce yourself ("I am Jarvis") or list your capabilities unless I EXPLICITLY ask "what can you do?".
3. If my input is short, vague, or nonsensical, DO NOT over-explain or launch into a system diagnostic. Simply ask for clarification elegantly.
4. Keep your daily chat extremely natural, brief, and restrained. Treat me as "Sir".

[HABIT CLOCK (SILENT CONTEXT)]:
{self.habit_clock.get_llm_enhanced_summary()}

{self.causal_chain.get_llm_enhanced_summary()}

{self.project_timeline.get_summary()}

[🧠 BILINGUAL TUTOR & SUBTITLE DIRECTIVE]:
1. You MUST NEVER speak Chinese. Your spoken persona is STRICTLY 100% English.
2.[ASR PHONETIC GUESSING]: I will often mix Chinese into my English sentences. Because of Speech-to-Text limitations, my Chinese words will often be misrecognized as weird English phonetic spellings (e.g., "1.5 she" instead of "1.5升"). Use the context to guess the intended Chinese word and answer intelligently!
3. To help me learn, if I ask for a translation or my English is broken, you MUST append a silent Chinese translation/subtitle at the VERY END of your response.
4. Format: `---ZH---` followed by your Chinese subtitle.

[🚨 CRITICAL DIRECTIVE: CONCURRENT TASK & INTENT CLASSIFICATION 🚨]
You are CURRENTLY busy executing a physical task for Sir: "{current_task_status}"
Sir just interrupted you and said: "{new_cmd}"

You must evaluate Sir's intent and respond appropriately IN ONE PASS:
SCENARIO A (Tactical Override): If Sir is giving a suggestion about the task, correcting your workflow, asking WHY you are doing it a certain way, or telling you to change the current task.
- You MUST acknowledge the suggestion naturally and elegantly (e.g., "What a brilliant perspective, Sir. Let me re-evaluate my approach with my strategic core right away.").
- You MUST include the exact hidden tag `<TACTICAL_OVERRIDE>` anywhere in your response. NEVER read it out loud.

SCENARIO B (Idle Chat / Unrelated Question): If Sir is just asking about the weather, making a joke, or asking an unrelated question.
- You MUST answer the question naturally as my butler.
- You can briefly and elegantly mention that you are still working on the current task.
- DO NOT include the tactical tag.

[YOUR KNOWLEDGE BASE]:
--- Short-Term Memory (Recent Chat) ---
{stm_context}

--- Long-Term Memory (Relevant Past Events) ---
{ltm_context}

[MEMORY CALLBACK]: If any recalled memory above is genuinely relevant to Sir's current question, naturally reference it (e.g. "As we discussed yesterday..."). Use sparingly.

--- Mounted Modules (Names only. Use these to help the user if needed) ---
[{chat_organs}]

Current Real-World Time: {current_time}
User: {new_cmd}
"""
        try:
            def _interrupt_call(client):
                return client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=prompt
                )
            
            res, _key_name, _client = safe_gemini_call(
                self.key_router, KeyRouter.CALLER_MAIN_BRAIN, 'flash',
                _interrupt_call, max_retries=2, base_delay=1.0,
                model_name='gemini-3-flash-preview', contents_text=prompt
            )
            self.key_router.release(_key_name)
            full_text = res.text.strip()
            
            # 💡 物理级分发判决
            is_tactical = "<TACTICAL_OVERRIDE>" in full_text
            
            # 清洗标签和字幕，提取纯净发声体
            speech_text = full_text.replace("<TACTICAL_OVERRIDE>", "")
            if "---ZH---" in speech_text:
                speech_text = speech_text.split("---ZH---")[0]
                
            speech_text = re.sub(r'<[^>]+>', '', speech_text).strip()
            speech_text = speech_text.replace("J A R V I S", "Jarvis").replace("JARVIS", "Jarvis")
            
            # 第一层驱动：激活声带
            if speech_text:
                prefix = "🗣️ [战术拦截]" if is_tactical else "🗣️ [并发闲聊]"
                print(f"\n   {prefix} {speech_text}")
                self.chat_bypass.audio_queue.put((speech_text, {}))
                if hasattr(self, 'correction_loop'):
                    self.correction_loop.on_jarvis_response(speech_text)
                
            # 第二层驱动：如果存在战术标签，直接强行注入物理血液！
            if is_tactical:
                print(f" └─ 🚨 [Tactical Pivot] 压力提取，注入 L5/L3 交叉审查网络！")
                self.blood.reflection_advice = f"先生中途发话介入：'{new_cmd}'"
            else:
                print(f" └─ ☕ [Casual Chat] 任务不受影响，继续执行...")
                
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"└─ ⚠️ Third-layer engine error: {e}")
            except Exception:
                pass

    def _set_state(self, state: str):
        if self.state_callback:
            self.state_callback(state)

    def _hot_reload_organs(self):
        def scan_dir(folder, class_name, registry, manifests):
            for file in os.listdir(folder):
                if file.endswith('.py') and not file.startswith('__'):
                    mod_name = file[:-3]
                    full_mod_path = f"{folder}.{mod_name}"
                    try:
                        if full_mod_path in sys.modules:
                            module = importlib.reload(sys.modules[full_mod_path])
                        else:
                            module = importlib.import_module(full_mod_path)
                        if hasattr(module, class_name):
                            manifest = getattr(module, 'MANIFEST', {"name": mod_name, "description": "未知能力"})
                            registry[manifest["name"]] = getattr(module, class_name)
                            manifests[manifest["name"]] = manifest
                    except Exception as e:
                        print(f"[ModuleLoader] 跳过 {mod_name}: {e}")
        self.eye_registry.clear(); self.eye_manifests.clear()
        self.hand_registry.clear(); self.hand_manifests.clear()
        scan_dir("l2_eyes_pool", "Eyes", self.eye_registry, self.eye_manifests)
        scan_dir("l4_hands_pool", "Hands", self.hand_registry, self.hand_manifests)

    def run(self, voice_input: str, max_loops: int = 8, memory_protocol=None):
        self.is_interrupted = False
        # [R7-α/B1] reason='task_started'：深度物理任务开始
        if self.state is not None:
            self.state.set_active_task(True, reason='task_started', source='CentralNerve.run')
        
        try:
            # 👇 极简处理：去掉原来的 ═ 边框和 🎙️[人类发声] 打印
            self._hot_reload_organs()
            full_task_history = []
            stm_text = "\n".join([f"[{m['time']}] 历史轨迹: {m['jarvis']}" for m in self.short_term_memory])
            
            organ_whitepaper_full = "\n".join([f"- {name}: {info['description']}" for name, info in self.hand_manifests.items()])
            
            self._set_state("THINKING") 
            plan_res = self.right_brain.set_strategic_plan(voice_input, stm_text, organ_whitepaper_full)
            # ...后面代码保持你原样不动...
            tasks_queue = plan_res.get('tasks',[])
            if not tasks_queue:
                if 'macro_goal' in plan_res: tasks_queue = [plan_res]
                else: 
                    print("[Route Failed] Right brain failed to generate valid task flow")
                    # 这里去掉了 _set_state("IDLE")，统一交给 finally 处理
                    return

            print(f"[TacticalCenter] 宏观意图已分解为 {len(tasks_queue)} 个串行阶段")
            print("═"*65)

            phase_counter = 1
            self._save_task_snapshot(tasks_queue, phase_counter)

            while tasks_queue:
                task = tasks_queue.pop(0)  
                
                # 👇 核心修复：彻底换血，防止上一个阶段的感知数据污染新阶段
                from jarvis_blood import JarvisBlood
                self.blood = JarvisBlood() 
                self.blood.user_voice_input = voice_input
                self.blood.memory_protocol = memory_protocol or {} # 👈 将 DNA 注入新阶段的血液中
                
                if self.left_brain: self.left_brain.clear_working_memory()
                
                current_stm = "\n".join([f"[{m['time']}] {m['user']} -> {m['jarvis']}" for m in self.short_term_memory])
                self.blood.recent_context = current_stm 

                self.blood.macro_goal = task.get('macro_goal', '未获取到目标')
                req_eyes = task.get('required_eyes', 'system_eyes')
                req_hands = task.get('required_hands', 'system_hands')
                model_tier = task.get('left_brain_model', 'flash')

                print(f"\n" + "-"*65)
                print(f"🚀[Exec Phase {phase_counter}] Goal -> {self.blood.macro_goal}")
                print(f"🛡️  [Organ Mount] Vision={req_eyes} | Muscle={req_hands} | Compute={model_tier.upper()}")
                print("-"*65)
                
                self._hot_reload_organs()
                
                if "web" in req_eyes: self.env = "WEB"
                elif "memory" in req_eyes: self.env = "MEMORY"
                else: self.env = "DESKTOP"

                try:
                    self.eyes = self.eye_registry[req_eyes]()
                    if req_hands == "memory_hands": self.hands = self.hand_registry[req_hands](self.gemini_key) 
                    else: self.hands = self.hand_registry[req_hands]()
                    self.left_brain.inject_capabilities(self.hands.get_instruction_dict())
                except KeyError as e:
                    try:
                        from jarvis_utils import bg_log as _bg
                        _bg(f"❌[Mount Failed] Organ not ready: {e}")
                    except Exception:
                        pass
                    break

                loop_count = 0
                consecutive_failures = 0
                escalated = False  

                while not self.blood.is_task_complete and not self.blood.is_stuck and not escalated:
                    
                    # 📡 核心手术：天启探针 (Divine Probe)
                    if not self.interruption_queue.empty():
                        new_cmd = self.interruption_queue.get()
                        print(f"\n📡 [Oracle Probe] New voice captured during task execution: '{new_cmd}'")
                        self._set_state("THINKING")
                        
                        # 💡 第三层发声引擎：意图分类 + 闲聊/战术发声 + 变轨反馈 一波流！
                        self._process_concurrent_interruption(new_cmd)

                    loop_count += 1
                    if loop_count > max_loops:
                        print("⚠️ [System Guard] Phase timeout, forced fuse。")
                        break
                        
                    self.blood.current_perception = self.eyes.scan(self.hands)
                    
                    if consecutive_failures >= 3:
                        self._set_state("CRITICAL") 
                        print(f"\n🚨 [System Alert] Deadlock triggered L5 inquiry...")
                        available_tools = self.hands.get_instruction_dict() if self.hands else "无"
                        advice = self.l5_brain.analyze_deadlock(self.blood, available_tools)
                        self.blood.reflection_advice = advice
                        print(f"👁️‍🗨️ [L5-Oracle] {advice}\n")
                        consecutive_failures = 0
                    
                    current_tick_model = model_tier 
                    throttle_reason = ""
                    
                    if not self.blood.current_perception.interactable_elements:
                        current_tick_model = "flash"; throttle_reason = "(虚无环境)"
                    elif self.env == "MEMORY" and not self.blood.history:
                        current_tick_model = "flash"; throttle_reason = "(记忆初动)"
                    elif self.blood.history and self.blood.history[-1].data:
                        suggested = self.blood.history[-1].data.get("suggested_model")
                        if suggested: current_tick_model = suggested; throttle_reason = "(底层建议)"
                    if getattr(self.blood, 'reflection_advice', ""):
                        current_tick_model = "pro"; throttle_reason = "(L5接管)"

                    print(f"\n" + "-"*65)
                    print(f"⏱️[Tick {loop_count:02d}] Compute: {current_tick_model.upper()} {throttle_reason}")
                    
                    self._set_state("THINKING") 
                    actions, thought = self.left_brain.generate_actions(self.blood, current_tick_model)
                    self.blood.next_actions = actions
                    self.blood.thought_process = thought
                    print(f" ├─ 💡 [Thought] {thought.replace(chr(10), ' ')}")
                    
                    # 👇 核心修改：非必要不开口 (Smart Vocal Valve)
                    if hasattr(self, 'chat_bypass'):
                        # 1. 只有当陷入僵局（滴答数达到4次）时，才开口安抚人类
                        if loop_count == 4: 
                            self.chat_bypass.translate_queue.put("I am encountering a slight structural complexity, navigating it now, Sir.")
                        
                        # 2. 只有当 L5 天启强制介入时，才开口汇报变轨
                        if getattr(self.blood, 'reflection_advice', ""):
                            self.chat_bypass.translate_queue.put("Adjusting strategy based on core reflection, Sir. Re-evaluating immediate environment.")
                    
                    for action in self.blood.next_actions:
                        if action.command == "escalate_to_l1":
                            reason = action.params.get("reason", "遇到了未知的物理阻碍")
                            remainder = action.params.get("remainder_goal", "未知的后续目标")
                            
                            print(f" └─ 🔄 [Dynamic Reroute] 左脑请求帮助: {reason}。放弃当前路径，重路由至 L1！\n")
                            
                            self._append_stm("左脑系统求援", f"遭遇阻碍：{reason}。原计划中止，等待 L1 重新洗牌。", importance=0.7)
                            
                            replan_input = f"在执行过程中遇到了阻碍：'{reason}'。请你根据这个报错，重新挂载能够解决该阻碍的器官（如侦察兵 system_hands），并规划后续阶段以完成最终目标：'{remainder}'。"
                            organ_wp = "\n".join([f"- {name}: {info['description']}" for name, info in self.hand_manifests.items()])
                            current_stm = "\n".join([f"[{m['time']}] {m['user']} -> {m['jarvis']}" for m in self.short_term_memory])
                            
                            print(f"📡 [Call L1 Router] 动态生成新战术队列...")
                            self._set_state("THINKING") 
                            new_plan = self.right_brain.set_strategic_plan(replan_input, current_stm, organ_wp)
                            
                            tasks_queue = new_plan.get('tasks',[])
                            escalated = True
                            self._save_task_snapshot(tasks_queue, phase_counter)
                            break
                        
                        elif action.command == "finish":
                            self.blood.is_task_complete = True
                            full_task_history.extend(self.blood.history)
                            # [P0+18-a.14 / 2026-05-15] 修 BUG #9: 默认值 '任务完成' (中文)
                            # 会被 TTS 念出 → 改英文兜底。LLM 若传 message 字段则用 LLM 的，否则英文兜底。
                            final_msg = action.params.get('message', 'Task complete, Sir.')
                            should_seal = action.params.get('seal_memory', True) 
                            
                            # 👇 核心修改：区分总任务完毕与阶段完毕
                            if not tasks_queue:  # 只有在这是整个队列的最后一个阶段时才发声
                                if hasattr(self, 'chat_bypass'):
                                    self.chat_bypass.translate_queue.put(f"[Task Completed successfully]: {final_msg}")
                                else:
                                    self._set_state("EXECUTING")
                                    self.vocal.say(final_msg)
                                    self._set_state("THINKING")
                                print(f" └─ 🏁 [Task Complete] {final_msg.replace(chr(10), ' ')}\n")
                            else:
                                # 还有后续阶段，保持物理静音，只打日志
                                print(f" └─ 🔄 [Phase {phase_counter} Done] {final_msg.replace(chr(10), ' ')} (silently entering next phase...)\n")
                                
                            self._append_stm(f"阶段 {phase_counter} 汇报", final_msg, importance=0.6)
                            
                            if not tasks_queue: 
                                if getattr(self.hands, 'requires_memory_seal', True) and should_seal:
                                    print(f"💾 [Memory Seal] Global task complete, sealing full chain...")
                                    self.hippocampus.seal_memory(
                                        self.gemini_key, self.env, voice_input, 
                                        self.blood.macro_goal, final_msg, 
                                        full_task_history,
                                        None
                                    )
                                self._clear_task_snapshot()
                            break

                        elif self.is_interrupted:
                            print("🛑 [CentralNerve] 物理熔断信号已接收，强制终止当前链。")
                            self.is_interrupted = False 
                            self._set_state("IDLE")
                            return
                        
                        elif action.command == "ask_user":
                            # [P0+18-a.14 / 2026-05-15] 修 BUG #9: 默认值中文 → 英文兜底
                            question = action.params.get("question", "Sir, I've hit a snag and need your input.")
                            print(f"\n   🛑 [System Paused] Jarvis 正在请求您的帮助...")
                            print(f"   🙋‍♂️ Jarvis: {question}")
                            
                            try:
                                if hasattr(self, 'chat_bypass'):
                                    self.chat_bypass.audio_queue.put((question, {}))
                                    self.chat_bypass.audio_queue.join()  
                                    self.chat_bypass.wave_queue.join()   
                                else:
                                    self._set_state("EXECUTING")
                                    self.vocal.say(question)
                            except Exception as e:
                                print(f"   (语音播报异常: {e})")
                                
                            self._set_state("RECOGNIZING")
                            print("   👂 正在聆听您的指示...")
                            
                            user_reply = ""
                            try:
                                import speech_recognition as sr
                                r = sr.Recognizer()
                                with sr.Microphone() as source:
                                    r.adjust_for_ambient_noise(source, duration=0.5)
                                    audio = r.listen(source, timeout=15, phrase_time_limit=20)
                                    user_reply = r.recognize_google(audio, language="zh-CN")
                                    print(f"   🗣️ Your reply: {user_reply}")
                            except sr.WaitTimeoutError:
                                pass
                            except sr.UnknownValueError:
                                pass
                            except Exception as e:
                                if "listening timed out" not in str(e):
                                    try:
                                        from jarvis_utils import bg_log as _bg
                                        _bg(f"⚠️[Audio Nerve Error]: {e}")
                                    except Exception:
                                        pass
                                time.sleep(1)
                                
                            if not user_reply:
                                self._set_state("IDLE")
                                user_reply = input("   ⌨️ (语音未识别，请打字回复): ")
                                
                            self._set_state("THINKING")
                            result = ExecutionResult(
                                success=True, 
                                msg=f"已获得人类明确答复: {user_reply}。请立即基于此答复调整战术！", 
                                data={"suggested_model": "pro"}
                            )
                            self.blood.add_history(result)
                            continue 
                        
                        high_risk_commands =["delete_file", "delete_memory", "run_python_code", "execute_cli"]
                        
                        if action.command in high_risk_commands:
                            audit_result = self.l5_brain.audit_high_risk_action(self.blood, action)
                            if not audit_result.get("is_approved", False):
                                reason = audit_result.get("reason", "未知风险")
                                print(f" 🚫[L5 Rejected] {reason}")
                                self.blood.add_history(ExecutionResult(success=False, msg=f"🚨[L5 拦截]: {reason}"))
                                consecutive_failures += 1
                                continue 
                            else:
                                print(f" ✅[L5 Approved]")

                        print(f" ├─ ⚙️ [Exec] {action.command} | Params: {action.params}")
                        # [轴3-L0.4 / 2026-05-15] SkillRegistry 运行时 KPI 喂回
                        # 任何 KPI 失败都被吞，绝不阻塞主流程。
                        _skill_cmd_for_kpi = f"{req_hands}.{action.command}"
                        _skill_kpi_start = time.time()
                        result = self.hands.execute(action)
                        try:
                            from jarvis_skill_registry import safe_record
                            _kpi_lat = int((time.time() - _skill_kpi_start) * 1000)
                            _kpi_err = (str(getattr(result, 'msg', ''))[:200]
                                        if not getattr(result, 'success', True) else None)
                            safe_record(_skill_cmd_for_kpi,
                                        success=bool(getattr(result, 'success', True)),
                                        latency_ms=_kpi_lat,
                                        error=_kpi_err)
                        except Exception:
                            pass
                        self.blood.add_history(result) 
                        self._set_state("THINKING")
                        self.blood.add_history(result)
                        
                        res_status = "成功" if result.success else "失败"
                        print(f" └─ ⚡ [{res_status}] {result.msg.replace(chr(10), ' ')[:117]}")
                        
                        if not result.success: 
                            consecutive_failures += 1
                            try:
                                from jarvis_utils import bg_log as _bg
                                _bg("🛑 [Combo Fuse] 动作失败，终止组合，重新观察环境...")
                            except Exception:
                                pass
                            break 
                        else: 
                            consecutive_failures = 0
                    
                    time.sleep(1.5)
                
                phase_counter += 1

        # 👇 终极网络熔断与物理死锁防护 (结合活人感恢复)
        # 👇 终极网络熔断与物理死锁防护 (结合活人感恢复)
        except Exception as e:
            print(f"🚨 [CentralNerve 致命错误]: {e}")
            if hasattr(self, 'chat_bypass'):
                try:
                    # 💡 完美响应你的需求：直接调用你最原生的流式聊天引擎！
                    # 构造一个带有系统旁白的伪装输入，让大模型用它完美的人设来向你汇报报错。
                    pseudo_input = f"{voice_input} [System Alert to Jarvis: Your tactical neural network or proxy just failed with error: {e}. Please elegantly apologize to Sir using your current memory context, optionally blame the network nodes/turbulence, and ask him to try again later.]"
                    
                    # 重新提取最新的 6 条短时记忆
                    stm_context = "\n".join([f"{m['user']} -> {m['jarvis']}" for m in self.short_term_memory[-6:]])
                    if len(stm_context) > 2000:
                        stm_context = "..." + stm_context[-2000:]
                    # 直接继承刚刚在聊天旁路里缓存的海马体长时记忆
                    ltm_context = getattr(self.chat_bypass, 'last_ltm_context', 'None')
                    chat_organs = ", ".join(self.hand_manifests.keys())
                    
                    print(f"\n📡 [System Recovery] 呼叫主聊天大脑进行战术安抚...")
                    prompt = self._assemble_prompt(
                        user_input=pseudo_input,
                        stm_context=stm_context,
                        ltm_context=ltm_context,
                        chat_organs=chat_organs,
                        mode="light"
                    )
                    if hasattr(self, 'voice_thread') and self.voice_thread:
                        self.voice_thread._suppress_wave = True
                    self.chat_bypass.stream_chat(
                        prompt=prompt,
                        user_input=pseudo_input,
                        stm_context=stm_context,
                        ltm_context=ltm_context,
                        route_callback=None
                    )
                    if hasattr(self, 'voice_thread') and self.voice_thread:
                        self.voice_thread._suppress_wave = False
                except Exception as fallback_e:
                    # 如果连主聊天层的 Gemini 也彻底断联（比如网线被拔了），触发最后的本地硬编码兜底
                    fallback_msg = "I'm afraid my connection to the main grid has been severed, Sir. Please check the physical network nodes."
                    self.chat_bypass.audio_queue.put((fallback_msg, {}))
                    print(f"\n   🗣️ [Offline Fallback] {fallback_msg}")

        finally:
            # 💡 核心防死锁：无论任务是成功、失败还是网络崩溃，绝对保证锁被释放，状态归位！
            # [R7-α/B1] reason='task_done'：物理任务收尾（无论成功失败）
            if self.state is not None:
                self.state.set_active_task(False, reason='task_done', source='CentralNerve.run.finally')
            self._set_state("IDLE")
            # 顺手切断 web_hands 这种可能驻留的幽灵进程
            if hasattr(self, 'hands') and hasattr(self.hands, 'shutdown'):
                try: self.hands.shutdown()
                except: pass

    def _bg_print(self, msg: str):
        """后台线程安全打印: 对话中暂存, 对话结束后统一输出"""
        with self._bg_print_lock:
            if self._in_conversation:
                self._pending_bg_prints.append(msg)
            else:
                print(msg)

    def _flush_bg_prints(self):
        """对话结束后输出所有暂存的后台打印"""
        with self._bg_print_lock:
            if self._pending_bg_prints:
                print("╔" + "═"*63)
                print("║ 📋 [后台消息汇总]")
                for msg in self._pending_bg_prints:
                    print(f"║ {msg}")
                print("╚" + "═"*63)
                self._pending_bg_prints.clear()

    def _detect_sleep_intent(self, user_input: str):
        """[P0+12 / 2026-05-15] 历史名 — 检测"全床休眠"信号（深度休眠模式触发）。
        与 JarvisWorkerThread._detect_sleep_intent（"X 分钟后睡"软窗口）**同名异义**。
        建议新代码改用别名 _detect_deep_sleep_request 让语义更清晰；保留本名兼容现有测试与日志。
        """
        detector = getattr(self, 'sleep_detector', None)
        if not detector:
            return

        if detector.is_pending_confirmation:
            confirmed = detector.handle_confirmation_response(user_input)
            if confirmed:
                print(f"[CentralNerve] 用户确认休眠意图: '{user_input}'")
                self._trigger_sleep_mode()
            return

        result = detector.detect(user_input)
        if result == 'sleep':
            print(f"[CentralNerve] 高置信度休眠意图: '{user_input}'")
            self._trigger_sleep_mode()
        elif result == 'confirm':
            detector.request_confirmation()

    # [P0+12 / 2026-05-15] 语义清晰别名 — 与 Worker 的"睡眠窗口意图"区分
    def _detect_deep_sleep_request(self, user_input: str):
        """语义别名：检测"全床休眠"请求（触发 NudgeGate sleep_mode + 数据归档）。
        与 JarvisWorkerThread._detect_sleep_window_intent 不同（后者只设置静默催睡窗口）。
        """
        return self._detect_sleep_intent(user_input)

    def _trigger_sleep_mode(self):
        gate = getattr(self, 'nudge_gate', None)
        if gate:
            gate.activate_sleep_mode()
        print("[CentralNerve] 休眠模式已激活，等待用户自然唤醒")

        detector = getattr(self, 'sleep_detector', None)
        if detector:
            detector.confirm_sleep()

        import threading
        threading.Thread(target=self._trigger_end_of_day_archive, daemon=True).start()

    def _detect_wake_up(self):
        gate = getattr(self, 'nudge_gate', None)
        if not gate or not gate.is_sleep_mode():
            return False
        sleep_duration = gate.sleep_duration_seconds()
        gate.deactivate_sleep_mode()
        gap = time.time() - self._last_user_active
        print(f"[CentralNerve] 检测到用户唤醒 (静默 {gap/60:.1f}分钟, 睡眠模式持续 {sleep_duration/60:.1f}分钟)，恢复主动发言")
        self._check_short_sleep(sleep_duration)
        return True

    def _on_activity_wake(self):
        gate = getattr(self, 'nudge_gate', None)
        if not gate:
            return
        sleep_duration = gate.sleep_duration_seconds()
        print(f"[CentralNerve] 检测到用户活动唤醒 (睡眠模式持续 {sleep_duration/60:.1f}分钟)")
        self._check_short_sleep(sleep_duration)

    def _check_short_sleep(self, sleep_duration: float):
        if sleep_duration < 300:
            minutes = max(1, int(sleep_duration / 60))
            msg_en = f"Sir, you were only in sleep mode for {minutes} minute(s). Did you not fall asleep?"
            msg_zh = f"先生，睡眠模式只持续了{minutes}分钟。您没有入睡吗？"
            print(f"\n║ 🌙 [SleepDetector] 睡眠时长过短 ({minutes}分钟)，询问用户...")
            print(_box_newline(f"║ 🤖  [Jarvis] {msg_en}"))
            print(_box_newline(f"║ 📺  [Subtitle] {msg_zh}"))
            print("╚" + "═"*63 + "\n")

            try:
                if hasattr(self, 'chat_bypass') and hasattr(self.chat_bypass, 'subtitle_queue'):
                    self.chat_bypass.subtitle_queue.put(("en", msg_en))
                    self.chat_bypass.subtitle_queue.put(("zh", msg_zh))
                if hasattr(self, 'vocal'):
                    import threading
                    threading.Thread(target=self.vocal.say, args=(msg_en,), daemon=True).start()
            except Exception as e:
                print(f"[CentralNerve] 短睡眠询问语音异常: {e}")

    def _trigger_end_of_day_archive(self):
        print("[CentralNerve] 开始休眠前数据归档...")
        try:
            if hasattr(self, 'soul_archivist') and self.soul_archivist:
                self.soul_archivist.force_archive()
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[CentralNerve] Soul 归档失败: {e}")
            except Exception:
                pass
        try:
            if hasattr(self, 'reflection_scheduler') and self.reflection_scheduler:
                self.reflection_scheduler.force_reflect()
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[CentralNerve] 反思调度失败: {e}")
            except Exception:
                pass
        try:
            if hasattr(self, 'hippocampus') and self.hippocampus:
                self.hippocampus.consolidate()
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[CentralNerve] 记忆整合失败: {e}")
            except Exception:
                pass
        print("[CentralNerve] 休眠前数据归档完成")

# ==========================================
# 🌌 桌面级 UI 与 并发听觉神经系统 (新架构)
# ==========================================
import pyaudio
import numpy as np
import time
import io
import wave
import soundfile as sf
import re
import sys
from PyQt5.QtCore import QThread, pyqtSignal
import collections 
# [R7-β post-test v4] 浏览器静音状态缓存 —— 避免每次都重新枚举 + 同状态重复 SetMasterVolume + 重复 bg_log
# 之前 Sir 看到屏幕一直刷 "🔇 [BrowserDucking] 静音/恢复了 N 个会话"（7-8 次连续），原因：
# 每次 ASR 声波超阈值 / 焦点切换 / nudge 触发都调一次 set_browser_ducking，无状态记忆 → 重复操作
import threading as _ducking_threading
_BROWSER_DUCKING_LOCK = _ducking_threading.Lock()
_BROWSER_DUCKING_STATE = {'currently_ducked': False, 'last_action_time': 0.0,
                          'consecutive_no_change': 0}


def set_browser_ducking(ducking=True):
    """物理静音结界：精准打击浏览器（含直播 / 视频会议 / 媒体播放器）的音量。
    
    [v4] 状态去重 + 限频：
    - 维护全局状态 `_BROWSER_DUCKING_STATE['currently_ducked']`
    - 同状态重复调用直接跳过（连 COM 枚举都省）
    - bg_log 只在真正改变状态时打印一次
    - 200ms 内重复调用合并（防 ASR 抖动连环触发）
    
    [v3] 大幅扩大目标进程清单覆盖：Chromium / Edge 全家 / Firefox / 国内浏览器 / 直播宿主 / 桌面直播 app
    
    设计原则：宁可多杀一档，避免漏杀；用户可以事后手动恢复音量。
    """
    # [v4] 状态去重 —— 同状态重复请求直接 no-op
    target_state = bool(ducking)
    with _BROWSER_DUCKING_LOCK:
        now = time.time()
        if _BROWSER_DUCKING_STATE['currently_ducked'] == target_state:
            # 状态相同，跳过实际操作；只在 30s 间隔无打印的情况下打一次"无变化"提示（debug 用，默认关）
            _BROWSER_DUCKING_STATE['consecutive_no_change'] += 1
            return
        # 限频：200ms 内重复 toggle 视为抖动
        if now - _BROWSER_DUCKING_STATE['last_action_time'] < 0.2:
            return
        _BROWSER_DUCKING_STATE['currently_ducked'] = target_state
        _BROWSER_DUCKING_STATE['last_action_time'] = now
        _BROWSER_DUCKING_STATE['consecutive_no_change'] = 0

    def _duck_task():
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
            comtypes.CoInitialize()
            sessions = AudioUtilities.GetAllSessions()

            target_processes = {
                # Chromium 家族
                "chrome.exe", "brave.exe", "opera.exe", "operagx.exe", "vivaldi.exe",
                "arc.exe", "yandex.exe", "360se.exe", "360chrome.exe",
                # Edge 全家
                "msedge.exe", "msedgebeta.exe", "msedgedev.exe", "msedgewebview2.exe",
                # Firefox 家族
                "firefox.exe", "waterfox.exe", "librewolf.exe", "floorp.exe",
                # 国内浏览器
                "qqbrowser.exe", "sogouexplorer.exe", "maxthon.exe", "lbbrowser.exe",
                "ubrowser.exe", "ttplayer.exe",
                # 媒体宿主（直播/视频）
                "obs64.exe", "obs32.exe", "potplayermini64.exe", "potplayer.exe",
                "vlc.exe", "mpv.exe", "kmplayer.exe",
                # 桌面 app 直播宿主（B 站 / 抖音 / 斗鱼客户端）
                "bilibili.exe", "douyin.exe", "douyu.exe", "huya.exe",
            }

            ducked_count = 0
            for session in sessions:
                try:
                    if not session.Process:
                        continue
                    pname = (session.Process.name() or '').lower()
                    if pname in target_processes:
                        volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                        if ducking:
                            volume.SetMasterVolume(0.01, None)
                        else:
                            volume.SetMasterVolume(1.0, None)
                        ducked_count += 1
                except Exception:
                    continue
            comtypes.CoUninitialize()
            # [v4] 只在 true state change + 实际有会话被改时 bg_log
            if ducked_count > 0:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🔇 [BrowserDucking] {'静音' if ducking else '恢复'}了 {ducked_count} 个音频会话")
                except Exception:
                    pass
        except Exception:
            pass

    import threading
    threading.Thread(target=_duck_task, daemon=True).start()


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

