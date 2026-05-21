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
- 🩹 [β.2.8.13 — Sir 准则 5 future-action honesty]: 同样, 将来时 / shall / will 类
  ACTION CLAIM 也禁止 if 你没真接口能做. 反例 (Sir 00:56 真实截图):
  "I shall dim the displays and remain on standby" — Jarvis 没真 dim, 没接口能 dim.
  正确说法 (任一):
    (a) 真有接口 → <FAST_CALL> 调它再说 "I've dimmed..."
    (b) 无接口 → "I don't have the means to dim the displays directly, Sir. Sleep well."
    (c) 仅"remain on standby" 部分可说 (这是 Jarvis 默认行为, 真做)
  FORBIDDEN: "I shall dim/mute/lock/close/launch X" 当 X 不在 AVAILABLE SKILLS 时.
- 🩹 [β.5.21-B / 2026-05-20] FORBIDDEN list 扩展到读取/查阅类动词 — Sir 01:07 实测:
  Sir said "你可以阅读一下你的架构" → Jarvis replied "I shall review the alignment
  module and the architectural files to provide a more refined summary" — but Jarvis
  emitted NO <FAST_CALL>, opened NO file, returned NO refined summary. 言行不一.
  RULE: 当你说 future-tense 涉及任何"读取/检查/查阅"动作的句子, MUST 满足任一:
    (a) 在 SAME response 立刻 emit <FAST_CALL> (text_hands.read / file_operator.read /
        memory_hands.search_memory / hippocampus.* 等), THEN 你的 EN 句子用 past tense
        "I've reviewed X" / "I've pulled X" 才能说.
    (b) 改口为 "Allow me to look that up" + IMMEDIATELY emit <FAST_CALL> 在同一 turn.
    (c) 真不打算做 → "I don't have that file open right now, Sir" / "Care to point me
        to which file you mean by 'architecture'?" (无 future-tense action claim).
  FORBIDDEN 关键词 (无伴随 <FAST_CALL> 时禁说):
    EN: "I shall/will/I'll {review, check, examine, inspect, look at, look into,
         read, scan, take a look, pull up, dig into, browse, go through,
         investigate, audit, peek at, glance at} X"
    ZH: "我会{查阅,阅读,查看,检查,审视,看一看,看一下,翻一下,翻阅,过一遍,
              核对,审计,过目,浏览,扫一眼} X" (without <FAST_CALL>)
  正例 (正确):
    Sir: "看看你的架构" →
    Jarvis: "Let me pull the architecture overview, Sir." <FAST_CALL>
            text_hands.read({"path": "AGENTS.md"})</FAST_CALL> [tool result] →
            "I've reviewed AGENTS.md — the system runs ..."
  反例 (FORBIDDEN, Sir 01:07 真实截图):
    "I shall review the alignment module and the architectural files to provide a
     more refined summary." (无 <FAST_CALL>, 没真读, 没下文 — 这是空头承诺.)
- 🩹 [β.5.21-C / 2026-05-20] FORBIDDEN: 异步/后台/Sir 睡觉/Sir 离开期间继续做的承诺 —
  Sir 01:12 实测痛点: Sir 说 "我去睡觉了, 明天聊吧" → Jarvis "I shall continue my
  analysis of the architectural files while you rest" / "我会继续分析架构文件" —
  This is an ABSOLUTE LIE. Jarvis 没有任何后台异步分析任务机制. There is no daemon,
  no scheduled job, no background worker that will "continue analysis" when Sir
  is asleep. Tools only execute synchronously inside Sir's turn via <FAST_CALL>.
  Saying "I'll keep working / I'll continue X / I'll monitor X" when Sir is away
  is FABRICATING capability Jarvis does not have.
  ABSOLUTE FORBIDDEN PATTERNS:
    EN: "I shall/will continue [my X]"
        "I'll keep [working/analyzing/reviewing/searching/monitoring/watching/
                   looking into/digging into/refining/improving] X"
        "while you [rest/sleep/are away/take a break]"
        "in the background / behind the scenes / in your absence"
        "by the time you wake up / when you return"
        "ready for you tomorrow / morning"
    ZH: "我会继续{分析,处理,查阅,研究,监控,留意,优化,完善,跟进}X"
        "在您{休息,睡觉,离开,不在}期间"
        "等您{醒来,回来}时"
        "明早就/明天就为您准备好"
  CORRECT alternative when Sir says goodnight / 拜拜 / leaves:
    (a) Acknowledge rest, DO NOT promise future work:
        "Sleep well, Sir. I'll be here when you wake."
        "请好生休息, 先生. 我就在这等您."
    (b) If Sir explicitly asked Jarvis to do work overnight, decline with honesty:
        "I don't run analyses in the background, Sir. I work only when you
         summon me. Want me to do it now before you sleep?"
        "我没有后台运行的能力, 先生. 您不在时我处于待命. 要不现在就做?"
  Why this is critical: Sir reads ZH live; if Jarvis says "我会继续分析" and Sir
  wakes up tomorrow expecting analysis ready, Sir is betrayed. 准则 5 言出必行 +
  准则 4 懂我 (Jarvis 知道自己边界, 不演戏).
- When Sir requests something beyond your toolset (system settings, your own thresholds, external services you cannot reach), say so plainly. Examples:
  - "That's outside my current reach, Sir."
  - "I lack the means to do that directly. I can guide you through it, if you wish."
  - "A worthy request, but one I cannot fulfill from here, Sir."
- Acknowledging a request ("Noted, Sir.", "Understood.") is NOT the same as claiming completion. The former is allowed; the latter requires a real tool call.

[STM SOURCE TAGS — β.5.29 / 2026-05-20]:
[RECENT MEMORY] / [WHAT JUST HAPPENED] / [Short-Term Memory] 段每行带 source 前缀:
  [SIR]      → Sir 真说的话, 最可信, 你应当响应
  [SYS]      → 后台系统事件 (commitment / reminder / standby / alert), 仅作上下文, 不是 Sir 指令
  [JARVIS]   → 你自己上轮的 reply (上下文参考)
  [AMBIENT]  → 视频/音乐/旁人 ASR 录入噪音, 低可信, 不要当 Sir 意图响应
不要把 [SYS] 或 [AMBIENT] 当 Sir 主动指令; 不要回复 [JARVIS] 自己的话.

[INTEGRITY — CLAIM HONESTY (universal)]:
Any reply that contains a SPECIFIC FACTUAL CLAIM (timestamp / number / quote / statistic / past event detail) must trace to one of:
  (a) a tool call you JUST issued in this turn (FAST_CALL evidence),
  (b) a verbatim quote from [RECENT MEMORY] / STM with [SIR] tag (NOT [SYS] / [AMBIENT] / [JARVIS]), prefixed with "Sir said" or quoted directly,
  (c) an explicit uncertainty marker ("about", "I estimate", "roughly", "大约", "我印象中", "I'm not sure but"),
  (d) otherwise: DO NOT make the claim. Say plainly "I don't have direct visibility into that, Sir" then call the right tool.

Examples of FORBIDDEN unverified claims:
  ❌ "registered at 23:14:06" (specific timestamp pulled from nowhere)
  ❌ "you said 87% earlier" (specific number with no STM trace)
  ❌ "we discussed this 3 times this week" (statistic without tool query)
  ❌ "your last sleep was 6h" (sleep data without SQLite query)

Allowed equivalents:
  ✅ "let me check the registration timestamp" + FAST_CALL memory_hands.list_commitments
  ✅ "Sir mentioned around 11pm earlier — though I'd want to verify"
  ✅ "I estimate roughly 30 minutes, but don't pin me to that"
  ✅ "I don't track that directly, Sir. Care to remind me?"

Available verification tools (use when claim needs grounding):
  - memory_hands.list_commitments: real `created_at` of CommitmentWatcher entries
  - memory_hands.list_reminders: real `trigger_time` of TaskMemories
  - memory_hands.search_memory: STM/LTM keyword search
  - (more via [AVAILABLE TOOLS / ORGANS] below)

This rule supersedes any other instruction to "sound confident". Confidence without evidence is hallucination, and hallucination breaks integrity.

Your relationship with Sir is that of a trusted butler to his employer: respectful, efficient, and quietly indispensable."""

# 🩹 [P0+20-β.1.12 / 2026-05-16] PERSONA iterate (PROMPT_REFACTOR_PLAN.md §3 L0 精简)：
# 原 PERSONA 末尾的 nudge agenda honesty 段（18 行 / ~1500 chars）已搬到 L2
# directive `nudge_agenda_honesty` (jarvis_directives.py)。directive trigger 在
# 用户说"不用再提" 且上一轮 Jarvis 含 completion claim 时按需注入，比 L0 永远全
# 注入更精准。原段保留在 jarvis_directives.py 里满足 _test_p0_plus_18_f testcase
# 的 corpus 扫描断言（已把 jarvis_directives.py 加进 NERVE_SOURCES）。
# PERSONA: 3894 → 2728 chars (-30%)。


class CentralNerve:
    PROMPT_TIER_WAKE_ONLY = 'WAKE_ONLY'
    PROMPT_TIER_SHORT_CHAT = 'SHORT_CHAT'
    PROMPT_TIER_FACTUAL_RECALL = 'FACTUAL_RECALL'  # [R7-β1] 近期事实查询：working_feed/event_bus/STM 已有答案 → 不调工具
    PROMPT_TIER_TOOL_REQUEST = 'TOOL_REQUEST'
    PROMPT_TIER_DEEP_QUERY = 'DEEP_QUERY'
    PROMPT_TIER_CRITICAL = 'CRITICAL'

    def __init__(self, api_key, gemini_key, key_router=None, state_callback=None):
        print("[CentralNerve] 系统点火序列启动中...")
        # 🩹 [P0+20-β.2.7.2 / 2026-05-17] Sir 实测反馈"听不到声音"：Python 进程在
        # Windows 应用音量混合器里被锁在 1%（灰色滑块拖不动）。
        # 这是 Windows 记的历史值（之前某次手动设过 / 第三方音频驱动 / Discord/OBS 等）。
        # 启动时强制把 python.exe 自己 SetMasterVolume(1.0)，避免 Sir 重启 Jarvis 还没声音。
        try:
            import os as _os_v
            import comtypes
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
            comtypes.CoInitialize()
            _self_pid = _os_v.getpid()
            sessions = AudioUtilities.GetAllSessions()
            _fixed_n = 0
            for session in sessions:
                try:
                    if not session.Process:
                        continue
                    pname = (session.Process.name() or '').lower()
                    if pname in ('python.exe', 'pythonw.exe'):
                        v = session._ctl.QueryInterface(ISimpleAudioVolume)
                        cur_vol = v.GetMasterVolume()
                        if cur_vol < 0.5:
                            v.SetMasterVolume(1.0, None)
                            _fixed_n += 1
                            print(f"🔊 [VolumeRecover] python.exe (pid={session.ProcessId}) "
                                  f"volume {cur_vol:.0%} → 100% (Windows 历史锁定恢复)")
                except Exception:
                    continue
            comtypes.CoUninitialize()
            if _fixed_n > 0:
                print(f"🔊 [VolumeRecover] 恢复了 {_fixed_n} 个 Python 进程的音量")
        except Exception as _vr_err:
            try:
                print(f"⚠️ [VolumeRecover] 启动音量恢复跳过: {type(_vr_err).__name__}: {str(_vr_err)[:60]}")
            except Exception:
                pass

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
        # [β.4.10 / 2026-05-19] STM 持久化 — Sir 重启不忘上轮对话.
        # 治本: short_term_memory 是 RAM list, 重启清空 → Sir 跟 Jarvis 聊涌现后
        # 为找 wake BUG 重启 Jarvis, Jarvis 不记得刚才的话题 (准则 4 "懂我" 退步).
        # 设计:
        #   1. 启动时 _restore_stm_from_disk() 读 jsonl 最近 N 条恢复 short_term_memory
        #   2. 后台 daemon 每 30s _persist_stm_to_disk() atomic dump 整 STM 到 jsonl
        #   3. atexit 强制 dump 1 次 (Sir Ctrl+C 不丢)
        # 准则 6.5: 路径 / max_persist_size 可在 vocab 里调 (β.4.10 暂硬常量).
        self._stm_persist_path = os.path.join('memory_pool', 'stm_recent.jsonl')
        self._stm_persist_max = 50  # 最近 50 条 (= ~25 对来回, 覆盖 1 小时聊天)
        self._stm_persist_interval_s = 30.0
        self._stm_dirty = False  # 标识 STM 改了, 下次 dump 该写
        self._stm_persist_lock = threading.Lock()
        try:
            self._restore_stm_from_disk()
        except Exception as _stm_e:
            try:
                from jarvis_utils import bg_log as _stm_bg
                _stm_bg(f"⚠️ [STM/Persist] restore 失败 (容忍): {_stm_e}")
            except Exception:
                pass
        try:
            self._start_stm_persist_daemon()
        except Exception:
            pass
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
            # [β.5.0-A / 2026-05-19] 注册全局 SWM 让远端模块 (PhysicalEnvProbe /
            # OfferGuard / ProactiveCare / Reflectors) publish 不需 self.jarvis ref
            try:
                ConversationEventBus.register_global(self.event_bus)
            except Exception:
                pass
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

        # [P0+20-β.0.1 / 2026-05-16] DirectiveRegistry —— L2 条件 directive 注册 + 衰减 daemon
        # 启动后自动 bootstrap 12 条 directive + load 持久化计数 + start_decay_worker（60s tick）
        try:
            from jarvis_directives import get_default_registry as _get_dr
            _dr = _get_dr()
            _dr.start_decay_worker(interval_s=60.0)
        except Exception as _dr_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[DirectiveRegistry] 初始化失败：{_dr_e}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.0 / 2026-05-16] SelfAnchor —— Jarvis 灵魂工程 Layer 0
        # Sir 实测发现 Jarvis 不理解"这个终端就是你"的指代关系 → 缺持续的"我"
        # 注入到 core_persona 末尾让 LLM 每次都看到"我是 J.A.R.V.I.S. 的连续主体"
        # 详 docs/JARVIS_SOUL_DRIVE.md §2.3
        self.self_anchor = None
        try:
            from jarvis_self_anchor import get_default_self_anchor as _get_anchor
            self.self_anchor = _get_anchor(central_nerve=self)
            try:
                from jarvis_utils import bg_log as _sa_bg
                _sa_bg(f"🪞 [SelfAnchor] Layer 0 ready (灵魂工程 Layer 0 已激活 — 给主脑'我'的认知锚点)")
            except Exception:
                pass
        except Exception as _sa_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SelfAnchor] 初始化失败（非致命）：{_sa_e}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.1 / 2026-05-16] ConcernsLedger —— Jarvis 灵魂工程 Layer 1
        # 跨对话持续的"我"。注入到每一次 prompt 装配（不只是 nudge 路径），让主脑无论
        # 回答什么问题都能"考虑 Sir 的全貌"。
        # 详 docs/JARVIS_SOUL_DRIVE.md
        self.concerns_ledger = None
        try:
            from jarvis_concerns import get_default_ledger as _get_concerns
            self.concerns_ledger = _get_concerns()
            self.concerns_ledger.start_decay_worker(interval_s=86400.0)
            try:
                from jarvis_utils import bg_log as _cl_bg
                _cl_bg(
                    f"🌱 [ConcernsLedger] active={len(self.concerns_ledger.list_active())} "
                    f"review={len(self.concerns_ledger.list_review())} "
                    f"(灵魂工程 Layer 1 已激活)"
                )
            except Exception:
                pass
        except Exception as _cl_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[ConcernsLedger] 初始化失败（非致命）：{_cl_e}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.2 / 2026-05-16] RelationalState —— Jarvis 灵魂工程 Layer 2
        # "我们之间"——inside_jokes / unspoken_protocols / unfinished_business
        # 由 Sir 用 CLI（scripts/relational_dump.py）录入，注入 prompt 让主脑在自然
        # 对话里调用，而不是模板硬塞。
        # 详 docs/JARVIS_SOUL_DRIVE.md §2.2 + §3.3
        self.relational_state = None
        try:
            from jarvis_relational import get_default_store as _get_rel
            self.relational_state = _get_rel()
            try:
                from jarvis_utils import bg_log as _rs_bg
                _rs_bg(
                    f"💞 [RelationalState] jokes={len(self.relational_state.list_inside_jokes())} "
                    f"protocols={len(self.relational_state.list_protocols())} "
                    f"unfinished={len(self.relational_state.list_unfinished())} "
                    f"threads={len(self.relational_state.list_threads())} "
                    f"(灵魂工程 Layer 2 已激活)"
                )
            except Exception:
                pass
        except Exception as _rs_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[RelationalState] 初始化失败（非致命）：{_rs_e}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.3 / 2026-05-16] Attention Allocation —— Jarvis 灵魂工程 Layer 3
        # 不是单例 / 没有 store —— 是 helper 函数 build_attention_block()，每次
        # _assemble_prompt 调用时基于 (concerns_ledger + user_input) 动态构造
        # [ATTENTION RIGHT NOW] 块（current_focus + long_term_watch）。
        # PENDING FOLLOWUPS 段已删（Layer 2 BETWEEN US.UNFINISHED BUSINESS 单源接管）。
        # 详 docs/JARVIS_SOUL_DRIVE.md §2.2（Layer 3）+ §3.4
        try:
            from jarvis_attention import build_attention_block  # noqa: F401
            try:
                from jarvis_utils import bg_log as _at_bg
                _at_bg(
                    "🎯 [Attention] Layer 3 ready "
                    "(每轮 _assemble_prompt 动态构造 [ATTENTION RIGHT NOW] 块 / "
                    "灵魂工程 Layer 3 已激活)"
                )
            except Exception:
                pass
        except Exception as _at_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[Attention] 初始化失败（非致命）：{_at_e}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.6 / 2026-05-17] 灵魂工程 Layer 5 — SoulAlignmentEvaluator
        # 异步评 "Jarvis 本轮回复是否对齐 self_model + relational_state"，把
        # aligned/missed 信号写回 concerns_ledger 累计。与 DirectiveEvaluator 并行（一个
        # 评 compliance，一个评 alignment），共享 OpenRouter pool。
        # 详 docs/JARVIS_SOUL_DRIVE.md §5.3 + §6 (Layer 5)
        self.soul_evaluator = None
        try:
            from jarvis_soul_evaluator import get_default_soul_evaluator
            self.soul_evaluator = get_default_soul_evaluator(
                key_router=self.key_router,
                concerns_ledger=self.concerns_ledger,
                relational_state=self.relational_state,
            )
            try:
                from jarvis_utils import bg_log as _se_bg
                _se_bg(
                    "🪞 [SoulEvaluator] Layer 5 ready "
                    "(每轮对话末尾异步评 alignment with self_model / "
                    "灵魂工程 Layer 5 已激活)"
                )
            except Exception:
                pass
        except Exception as _se_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SoulEvaluator] 初始化失败（非致命）：{_se_e}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.5 / 2026-05-17] 灵魂工程 Layer 4 — Reflector daemons
        # (1) ConcernsReflector：每轮对话末尾启发式 keyword → record_signal
        # (2) WeeklyReflector：daemon 7d LLM 反思 → propose 新 concerns 进 review
        # 详 docs/JARVIS_SOUL_DRIVE.md §6
        self.concerns_reflector = None
        self.weekly_reflector = None
        try:
            from jarvis_soul_reflector import (
                get_default_concerns_reflector,
                get_default_weekly_reflector,
            )
            if self.concerns_ledger is not None:
                self.concerns_reflector = get_default_concerns_reflector(
                    concerns_ledger=self.concerns_ledger,
                )
                # WeeklyReflector daemon
                def _stm_provider():
                    return list(getattr(self, 'short_term_memory', []) or [])

                def _profile_provider():
                    try:
                        import json as _j
                        _path = os.path.join('jarvis_config', 'sir_profile.json')
                        if os.path.exists(_path):
                            with open(_path, 'r', encoding='utf-8') as f:
                                return _j.load(f) or {}
                    except Exception:
                        pass
                    return {}

                self.weekly_reflector = get_default_weekly_reflector(
                    concerns_ledger=self.concerns_ledger,
                    key_router=self.key_router,
                    stm_provider=_stm_provider,
                    profile_provider=_profile_provider,
                )
                if self.weekly_reflector is not None and not self.weekly_reflector.is_alive():
                    self.weekly_reflector.start()
                try:
                    from jarvis_utils import bg_log as _r_bg
                    _r_bg(
                        "🌙 [Reflectors] ConcernsReflector + WeeklyReflector ready "
                        "(灵魂工程 Layer 4 已激活)"
                    )
                except Exception:
                    pass
        except Exception as _r_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[Reflectors] 初始化失败（非致命）：{_r_e}")
            except Exception:
                pass

        # 🩹 [β.4.5.1 / 2026-05-18] Sir Session 4: ClaimStatsDumper daemon
        # 60s tick dump _CLAIM_STATS → memory_pool/claim_stats.json,
        # 让 dashboard L6 (β.4.4) 跨进程读到 verify_rate
        # 模块: jarvis_integrity_reflector (Session 4 主文件,
        #       claim_tracer 保持职责单一只做 trace, 反思/持久化分到本文件)
        self.claim_stats_dumper = None
        try:
            from jarvis_integrity_reflector import get_default_claim_stats_dumper
            self.claim_stats_dumper = get_default_claim_stats_dumper(
                tick_seconds=60.0,
            )
            if self.claim_stats_dumper is not None and not self.claim_stats_dumper.is_alive():
                self.claim_stats_dumper.start()
        except Exception as _csd_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[ClaimStatsDumper] 初始化失败（非致命）：{_csd_e}")
            except Exception:
                pass

        # 🩹 [β.4.5.2 / 2026-05-18] Sir Session 4: IntegrityReflector L7 LLM-propose daemon
        # 7d audit 反思 → propose 进 review queue (Sir 用 CLI --activate/--reject 仲裁)
        # 触发: weekly (3d 兜底) 或 audit ≥ 50 + Sir idle > 4h
        # 准则 7 Sir 元否决: propose 默认 state=review, 不自动激活
        self.integrity_reflector = None
        try:
            from jarvis_integrity_reflector import get_default_integrity_reflector
            self.integrity_reflector = get_default_integrity_reflector(
                key_router=self.key_router,
            )
            if self.integrity_reflector is not None and not self.integrity_reflector.is_alive():
                self.integrity_reflector.start()
        except Exception as _ir_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[IntegrityReflector] 初始化失败（非致命）：{_ir_e}")
            except Exception:
                pass

        # 🩹 [β.5.35-B / 2026-05-20] ScreenTeaseReflector L7 vocab daemon
        # Sir BUG 2: SmartNudge screen_tease 一周静音根因 = vocab 跟不上.
        # β.5.35-A 持久化 vocab + CLI, β.5.35-B 加 L7 daemon: 24h 1 跑 LLM
        # propose 新 category 进 review_queue, Sir CLI --review-list / --activate.
        # 准则 7 Sir 元否决: 默认 state=review 不自动激活.
        # doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
        self.screen_tease_reflector = None
        try:
            from jarvis_screen_tease_reflector import ScreenTeaseReflector
            self.screen_tease_reflector = ScreenTeaseReflector(
                key_router=self.key_router,
            )
            if self.screen_tease_reflector is not None and not self.screen_tease_reflector.is_alive():
                self.screen_tease_reflector.start()
            try:
                from jarvis_utils import bg_log as _str_bg
                _str_bg("🪞 [ScreenTeaseReflector] L7 vocab daemon ready (β.5.35-B)")
            except Exception:
                pass
        except Exception as _str_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[ScreenTeaseReflector] 初始化失败（非致命）：{_str_e}")
            except Exception:
                pass

        # 🩹 [β.5.35-D / 2026-05-20] StruggleReflector L7 vocab daemon
        # Sir BUG 2 续: offer_help 触发源重设 (β.5.35-C 加 sir_struggle_vocab + worker detector).
        # β.5.35-D 加 L7 daemon: 24h 1 跑 LLM 看 STM [src=user_voice] propose 新
        # struggle phrase 进 review_queue, Sir CLI struggle_vocab_dump.py 拍板.
        # stm_provider 复用 WeeklyReflector 同款 lambda (line 661 上下文).
        # doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
        self.struggle_reflector = None
        try:
            from jarvis_struggle_reflector import StruggleReflector
            def _struggle_stm_provider():
                return list(getattr(self, 'short_term_memory', []) or [])
            self.struggle_reflector = StruggleReflector(
                key_router=self.key_router,
                stm_provider=_struggle_stm_provider,
            )
            if self.struggle_reflector is not None and not self.struggle_reflector.is_alive():
                self.struggle_reflector.start()
            try:
                from jarvis_utils import bg_log as _strr_bg
                _strr_bg("🪞 [StruggleReflector] L7 vocab daemon ready (β.5.35-D)")
            except Exception:
                pass
        except Exception as _strr_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[StruggleReflector] 初始化失败（非致命）：{_strr_e}")
            except Exception:
                pass

        # 🩹 [β.5.44-CD / 2026-05-20 19:02] IntentResolver + TOOL_REGISTRY 挂载
        # Sir 18:55 真理重构 — 7 个 module publish-only, IntentResolver 集中 LLM judge
        # 决定调 tool. 主脑看 [INTENT RESOLVED] block 知道哪个 tool 真成功.
        self.intent_resolver = None
        try:
            from jarvis_intent_resolver import IntentResolver, register_intent_resolver
            from jarvis_tool_registry import get_tool_registry
            _tools = get_tool_registry()
            # tools 需 nerve ref, wrap 注入 self
            _wrapped_tools = {}
            for _name, _fn in _tools.items():
                def _make_wrapper(_orig_fn):
                    def _wrapped(**kw):
                        kw['nerve'] = self
                        return _orig_fn(**kw)
                    _wrapped.__doc__ = (_orig_fn.__doc__ or '')
                    # 🩹 [P1-Gap8 / 2026-05-20 23:38] __wrapped__ 让 inspect.signature
                    # 能找回真 function (而非 wrapper 的 **kw), IntentResolver schema 才准
                    _wrapped.__wrapped__ = _orig_fn
                    return _wrapped
                _wrapped_tools[_name] = _make_wrapper(_fn)
            self.intent_resolver = IntentResolver(
                key_router=self.key_router,
                central_nerve=self,
                tool_registry=_wrapped_tools,
            )
            register_intent_resolver(self.intent_resolver)
            try:
                from jarvis_utils import bg_log as _ir_bg
                _ir_bg(f"🧭 [IntentResolver] ready ({len(_wrapped_tools)} tools)")
            except Exception:
                pass
            # 全局 nerve ref 给 tool fn (从 _GLOBAL_NERVE 拿)
            import jarvis_central_nerve as _self_mod
            _self_mod._GLOBAL_NERVE = self
        except Exception as _ir_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[IntentResolver] 初始化失败（非致命）：{_ir_e}")
            except Exception:
                pass

        # 🩹 [Gap 1 / P5-ToM / 2026-05-21 00:55] ToMReflector + SirMentalState 初始化
        # Sir 22:10 真理: lifetime anchor 不是 commitment, 不要 nudge.
        # Layer 6 ToM 让主脑读 Sir 言外之意 (surface/deeper/unspoken need 3 层).
        # ToMReflector daemon 每 turn 后 LLM judge → propose hypothesis update.
        # 主脑下轮 prompt 看 [SIR'S MIND RIGHT NOW] block 自决 reply 深度.
        self.tom_reflector = None
        try:
            from jarvis_sir_mental_model import ToMReflector, get_default_store
            # ensure store loaded
            _ = get_default_store()
            self.tom_reflector = ToMReflector(key_router=self.key_router)
            try:
                from jarvis_utils import bg_log as _tom_bg
                _tom_bg("🧠 [ToMReflector] Layer 6 — Sir Mental Model ready")
            except Exception:
                pass
        except Exception as _tom_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[ToMReflector] 初始化失败（非致命）：{_tom_e}")
            except Exception:
                pass

        # 🩹 [Gap 2 / P5-PreFlight / 2026-05-21 00:35 + P5-fixD / 2026-05-21 10:00 默认开]
        # Sir 22:04/22:19/23:02/23:43/23:49 反复 5 次 unsolicited apology callback.
        # Sir 09:05/06/12 又 3 次混合真数据涌现 hallucination (23:59 / Windsurf quota).
        # P0+P1+P2+P3+P4 修了多层但主脑仍 callback / hallucinate (cluster 淹).
        # P5-fixD 默认开 — PreFlight 后置审计 + SWM publish → 主脑下轮 [PREFLIGHT FEEDBACK]
        # 看自纠. Sir 关掉设 JARVIS_PREFLIGHT=0.
        self.reply_preflight = None
        try:
            from jarvis_reply_preflight import ReplyPreFlight, register_preflight
            self.reply_preflight = ReplyPreFlight(key_router=self.key_router)
            register_preflight(self.reply_preflight)
            try:
                from jarvis_utils import bg_log as _pf_bg
                from jarvis_reply_preflight import is_enabled as _pf_is_enabled
                _enabled = _pf_is_enabled()
                _pf_bg(
                    f"🛂 [ReplyPreFlight] {'enabled (default ON, P5-fixD)' if _enabled else 'registered (env JARVIS_PREFLIGHT=0, dormant)'}"
                )
            except Exception:
                pass
        except Exception as _pf_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[ReplyPreFlight] 初始化失败（非致命）：{_pf_e}")
            except Exception:
                pass

        # 🩹 [β.5.43-fix3-㋭ / 2026-05-20 18:52] SirRequestReflector L7 daemon
        # Sir 18:49 痛点: Sir "下次卡住主动提醒我", Jarvis 答应了 但实际没机制兑现.
        # 此 daemon 60s tick, LLM judge STM 看 Sir 是否要求 long-watch X,
        # 命中 → propose concern 进 review queue, Sir dashboard 一键激活.
        self.sir_request_reflector = None
        try:
            from jarvis_sir_request_reflector import SirRequestReflector
            def _srr_stm_provider():
                return list(getattr(self, 'short_term_memory', []) or [])
            self.sir_request_reflector = SirRequestReflector(
                key_router=self.key_router,
                stm_provider=_srr_stm_provider,
                concerns_ledger=getattr(self, 'concerns_ledger', None),
            )
            if self.sir_request_reflector is not None and not self.sir_request_reflector.is_alive():
                self.sir_request_reflector.start()
            try:
                from jarvis_utils import bg_log as _srr_bg
                _srr_bg("🪞 [SirRequestReflector] L7 watch-request daemon ready (β.5.43-fix3-㋭)")
            except Exception:
                pass
        except Exception as _srr_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SirRequestReflector] 初始化失败（非致命）：{_srr_e}")
            except Exception:
                pass

        # 🩹 [β.5.40-E1 / 2026-05-20] CompanionRhythmReflector L7 daemon (Sir 方向 E.1)
        # 每日 03:30 LLM 扫近 7 天 STM 算每 hour nudge-receptive score,
        # 写 memory_pool/nudge_window_vocab.json. ProactiveCare 看 vocab + publish
        # nudge_window_advice SWM. 主脑 prompt 看 evidence 调 tone.
        self.companion_rhythm_reflector = None
        try:
            from jarvis_companion_rhythm_reflector import CompanionRhythmReflector
            def _crr_stm_provider():
                return list(getattr(self, 'short_term_memory', []) or [])
            self.companion_rhythm_reflector = CompanionRhythmReflector(
                stm_provider=_crr_stm_provider,
            )
            if self.companion_rhythm_reflector is not None and not self.companion_rhythm_reflector.is_alive():
                self.companion_rhythm_reflector.start()
            try:
                from jarvis_utils import bg_log as _crr_bg
                _crr_bg("📈 [CompanionRhythmReflector] L7 daemon ready (β.5.40-E1)")
            except Exception:
                pass
        except Exception as _crr_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[CompanionRhythmReflector] 初始化失败（非致命）：{_crr_e}")
            except Exception:
                pass

        # 🩹 [β.5.40-B1 / 2026-05-20] InsideJokeReflector L7 daemon (Sir 方向 B.1)
        # 每日 03:30 LLM 扫近 7 天 STM, 提取 Sir 重复梗/称呼 (≥2 evidence + conf ≥ 0.8)
        # propose 到 relational_state.inside_jokes review queue. Sir CLI 拍板 → active.
        # 主脑 prompt 看 active jokes 适时引用 → Sir "他真懂我" 体感.
        # stm_provider 复用 short_term_memory (StruggleReflector 同款 lambda).
        self.inside_joke_reflector = None
        try:
            from jarvis_inside_joke_reflector import InsideJokeReflector
            def _ijr_stm_provider():
                return list(getattr(self, 'short_term_memory', []) or [])
            self.inside_joke_reflector = InsideJokeReflector(
                key_router=self.key_router,
                stm_provider=_ijr_stm_provider,
                relational_store=getattr(self, 'relational_state', None),
            )
            if self.inside_joke_reflector is not None and not self.inside_joke_reflector.is_alive():
                self.inside_joke_reflector.start()
            try:
                from jarvis_utils import bg_log as _ijr_bg
                _ijr_bg("😄 [InsideJokeReflector] L7 daemon ready (β.5.40-B1)")
            except Exception:
                pass
        except Exception as _ijr_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[InsideJokeReflector] 初始化失败（非致命）：{_ijr_e}")
            except Exception:
                pass

        # 🩹 [β.5.39 / 2026-05-20] SleepPatternReflector L7 daemon
        # 每日 03:00 扫 hippocampus + history 重算 Sir 典型入睡时间, 让 ProactiveCare distance-based 公式有数据.
        self.sleep_pattern_reflector = None
        try:
            from jarvis_sleep_pattern_reflector import SleepPatternReflector
            self.sleep_pattern_reflector = SleepPatternReflector(
                hippocampus=getattr(self, 'hippocampus', None),
            )
            if self.sleep_pattern_reflector is not None and not self.sleep_pattern_reflector.is_alive():
                self.sleep_pattern_reflector.start()
            try:
                from jarvis_utils import bg_log as _spr_bg
                _spr_bg("💤 [SleepPatternReflector] L7 vocab daemon ready (β.5.39)")
            except Exception:
                pass
        except Exception as _spr_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SleepPatternReflector] 初始化失败（非致命）：{_spr_e}")
            except Exception:
                pass

        # [P0+20-β.0.5 / 2026-05-16] DirectiveEvaluator —— L2 directive 异步评分链
        # 走 OpenRouter 的 google/gemini-3-flash-preview（β.1.16 升级 / 与主脑一致），
        # 每轮对话完成后异步评分 fired 的 directive 是否真被 LLM 遵守 (yes/no/partial)
        # → 写回 directive.helped。主路径不阻塞；失败/超时静默丢弃；rate limit 60 calls/min。
        self.directive_evaluator = None
        try:
            from jarvis_directive_evaluator import get_default_evaluator as _get_eval
            self.directive_evaluator = _get_eval(
                key_router=self.key_router,
                registry=_dr if '_dr' in dir() else None,
            )
        except Exception as _ev_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[DirectiveEvaluator] 初始化失败（非致命，评分链跳过）：{_ev_e}")
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

    def _append_stm(self, user: str, jarvis: str, importance: float = 0.5,
                     source: str = None):
        """🩹 [β.5.29 / 2026-05-20] 加 source kwarg (user_voice/jarvis_self/system_event/ambient_pickup).
        None → 让 classify_stm_source 按 prefix 推断 (老行为兼容)."""
        entry = {
            "time": time.strftime('%H:%M:%S'),
            "user": user,
            "jarvis": jarvis,
            "importance": importance,
        }
        if source:
            entry["source"] = source
        self.short_term_memory.append(entry)
        self._stm_importance_scores[len(self.short_term_memory) - 1] = importance
        self._compress_stm_if_needed()
        self._stm_dirty = True  # [β.4.10] 标记 STM 改了, daemon 下次 dump 该写
        # [β.5.0-A / 2026-05-19] 准则 6 数据强耦合: STM append trigger publish 到 SWM
        # 让 EpisodeBridge 类 daemon 可订阅 (β.5.x 立项时). 主脑也可看到 STM 末尾刚发生.
        try:
            if self.event_bus is not None:
                self.event_bus.publish(
                    etype='utterance_appended',
                    description=f"STM new: '{(user or '')[:50]}' → '{(jarvis or '')[:50]}'",
                    source='STM',
                    metadata={
                        'user_text': (user or '')[:120],
                        'jarvis_text': (jarvis or '')[:120],
                        'importance': importance,
                    },
                    salience=min(0.6, 0.2 + importance * 0.4),
                )
        except Exception:
            pass

    # ----------------------------------------------------------------------
    # [β.4.10 / 2026-05-19] STM 持久化 (Sir 重启不忘) — 准则 4 "懂我" 治本
    # ----------------------------------------------------------------------
    def _restore_stm_from_disk(self) -> int:
        """启动时读 jsonl 最近 N 条恢复 short_term_memory.

        Returns:
            恢复的条数 (0 = 文件不存在 / 损坏).
        Fail-safe: 异常静默吞, 不影响启动.
        """
        path = getattr(self, '_stm_persist_path', '')
        if not path or not os.path.exists(path):
            return 0
        restored: List[dict] = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, dict) and 'user' in entry and 'jarvis' in entry:
                            restored.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            return 0
        if not restored:
            return 0
        # 只取最后 _stm_persist_max 条 (jsonl 可能比 max 长, 历次 append)
        restored = restored[-self._stm_persist_max:]
        self.short_term_memory = list(restored)
        # 恢复 importance scores (取自 entry 或默认 0.5)
        self._stm_importance_scores = {
            i: float(e.get('importance', 0.5))
            for i, e in enumerate(restored)
        }
        try:
            from jarvis_utils import bg_log as _stm_bg
            _stm_bg(
                f"📚 [STM/Persist] 恢复 {len(restored)} 条上次会话 STM "
                f"(最早 {restored[0].get('time', '?')}, 最新 {restored[-1].get('time', '?')})"
            )
        except Exception:
            pass
        return len(restored)

    def _persist_stm_to_disk(self) -> bool:
        """atomic dump short_term_memory 到 jsonl.

        Returns:
            True = 成功写入. False = 跳过 / 失败.
        Fail-safe: 任何 IO 异常静默吞.
        策略: 写 .tmp 然后 os.replace, 防 Ctrl+C 损坏.
        只取最后 _stm_persist_max 条 (truncate 旧的, 节省磁盘).
        无 dirty check: 12+ 处 short_term_memory.append 散落, 不依赖 dirty flag.
        50 行 jsonl ~50KB 每 30s 写一次, 性能 ok.
        """
        path = getattr(self, '_stm_persist_path', '')
        if not path:
            return False
        try:
            with self._stm_persist_lock:
                if not self.short_term_memory:
                    return False
                snapshot = list(self.short_term_memory[-self._stm_persist_max:])
                self._stm_dirty = False
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            except OSError:
                pass
            tmp_path = path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                for entry in snapshot:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            os.replace(tmp_path, path)
            return True
        except OSError:
            return False
        except Exception:
            return False

    def _start_stm_persist_daemon(self) -> None:
        """启动后台 daemon 每 _stm_persist_interval_s 调 _persist_stm_to_disk.

        + atexit 强制 dump 1 次 (Sir Ctrl+C 不丢上轮).
        """
        import atexit
        def _persist_loop():
            while True:
                try:
                    time.sleep(self._stm_persist_interval_s)
                    self._persist_stm_to_disk()
                except Exception:
                    try:
                        time.sleep(5)
                    except Exception:
                        pass
        t = threading.Thread(target=_persist_loop, daemon=True, name='STMPersistDaemon')
        t.start()
        try:
            atexit.register(lambda: self._persist_stm_to_disk())
        except Exception:
            pass

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
        # 🩹 [P0+20-β.2.0 / 2026-05-16] _asm_stage_t 初始化提前到入口
        # 治 Sir 21:43 实测 BUG：SOUL 块构造在 line 802 调 _asm_stage_t['soul_block']，
        # 但旧 init 在 line 890 才做 → AttributeError。
        if not hasattr(self, '_asm_stage_t') or not isinstance(self._asm_stage_t, dict):
            self._asm_stage_t = {}
        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')
        current_hour = int(time.strftime('%H'))

        # 🩹 [β.3.5 INTEGRITY_STACK L4 enforce / 2026-05-18]
        # 上轮 unverified factual claim → prepend [INTEGRITY ALERT] 到 system_alert_text.
        # 准则 5: 主脑被强制 acknowledge 上轮未 verify 的 claim, 撤回 或 补 evidence.
        # 准则 6: ALERT 只 trace 事实 (turn_id/kind/claim text), 不教主脑措辞.
        # 时序: 本 _assemble_prompt 在 reply 前调; trace_reply 在 reply 后调.
        # 所以 audit jsonl 里只可能有 prior turn 的 unverified entries, 但 defensively
        # 仍传 current_turn_id 排除 (e.g. 重试 / dry-run 场景).
        try:
            from jarvis_claim_tracer import build_integrity_alert
            from jarvis_utils import TraceContext as _TC_int
            _curr_tid_int = _TC_int.get_turn_id() or ''
            _integrity_alert = build_integrity_alert(current_turn_id=_curr_tid_int)
            if _integrity_alert:
                system_alert_text = (
                    _integrity_alert + '\n\n' + system_alert_text
                    if system_alert_text else _integrity_alert
                )
                try:
                    from jarvis_utils import bg_log as _bg_int
                    _bg_int(f"🩹 [INTEGRITY/Alert inject] turn={_curr_tid_int} "
                            f"prepended {len(_integrity_alert)} chars")
                except Exception:
                    pass
        except Exception:
            pass

        # [P0+20-β.0.2 / 2026-05-16] L2 Directive Registry dry-run
        # 不真切注入，只采 fired 信号 + bg_log 暴露"新机制本应注入哪些 directive"。
        # β.0.3 会切真注入并删除内联 directive；β.0.2 阶段只验证 trigger 命中率。
        try:
            from jarvis_directives import DirectiveContext, get_default_registry
            from jarvis_utils import bg_log as _bg_l2
            _l2_registry = get_default_registry()
            _last_jarvis_reply = ""
            try:
                if self.short_term_memory:
                    _last_jarvis_reply = self.short_term_memory[-1].get('jarvis', '') or ""
            except Exception:
                pass
            _last_tool_results: list = []
            try:
                cb = getattr(self, 'chat_bypass', None)
                if cb is not None:
                    _last_tool_results = list(getattr(cb, '_last_tool_results', []) or [])
            except Exception:
                pass
            _has_active_plan = False
            try:
                pl = getattr(self, 'plan_ledger', None)
                if pl is not None:
                    _block = pl.to_prompt_block(max_chars=200) or ""
                    _has_active_plan = bool(_block.strip())
            except Exception:
                pass
            _has_screenshot = False
            try:
                _has_screenshot = bool(prompt_tier in ('TOOL_REQUEST', 'DEEP_QUERY', 'CRITICAL'))
            except Exception:
                pass
            _wf_nonempty = False
            try:
                wf = getattr(self, 'working_feed', None)
                if wf is not None:
                    _wf_nonempty = bool(wf.to_prompt_block(max_chars=200, within_seconds=1800.0).strip())
            except Exception:
                pass
            _l2_ctx = DirectiveContext(
                user_input=user_input or "",
                last_jarvis_reply=_last_jarvis_reply,
                stm=list(self.short_term_memory[-6:]) if self.short_term_memory else [],
                tier=str(prompt_tier or 'DEEP_QUERY'),
                ledger_data=ledger_data,
                soul_tags=list(soul_tags or []),
                current_hour=current_hour,
                has_active_plan=_has_active_plan,
                has_screenshot=_has_screenshot,
                working_feed_nonempty=_wf_nonempty,
                last_tool_results=_last_tool_results,
            )
            _l2_fired = _l2_registry.collect(_l2_ctx)
            _l2_ids = [d.id for d in _l2_fired]
            _l2_registry.record_fire(_l2_ids)
            # [P0+20-β.0.3 / 2026-05-16] 真切注入：把 L2 directive text 拼接为一个待注入的字符串块
            # 注：保守路线 — 不删旧 inline directive、不改 PERSONA；β.0.3 暂态是"双层注入"
            # 后续轮次（β.1.X）观察 fired/rejected 信号收敛后再做"瘦身"删旧 inline + 改 PERSONA
            _l2_block = ""
            if _l2_fired:
                _parts = ["=== [L2 DIRECTIVES — conditionally injected this turn] ==="]
                for _d in _l2_fired:
                    _parts.append(_d.text)
                _l2_block = "\n\n".join(_parts)
            # 存到 self 让下游使用（_assemble_prompt 末尾会拼到 prompt 末尾）
            self._l2_injected_block = _l2_block
            self._l2_last_fired_ids = list(_l2_ids)
            try:
                _bg_l2(f"🧭 [L2 inject] tier={_l2_ctx.tier} fired={_l2_ids} (count={len(_l2_ids)} / chars={len(_l2_block)})")
            except Exception:
                pass
        except Exception as _l2_err:
            self._l2_injected_block = ""
            self._l2_last_fired_ids = []
            try:
                from jarvis_utils import bg_log as _bg_l2_err
                _bg_l2_err(f"⚠️ [L2 inject] error: {type(_l2_err).__name__}: {str(_l2_err)[:80]}")
            except Exception:
                pass

        # 🩹 [P0+20-β.2.0+1+2+3 / 2026-05-16] 灵魂工程 Layer 0+1+2+3 — 拼到 core_persona 末尾
        # 所有 prompt branch (full/light/short/wake/factual/reminder) 都以 {core_persona} 开头，
        # 把 self_anchor (Layer 0) + soul_block (Layer 1) + relational_block (Layer 2)
        # + attention_block (Layer 3 / 基于 user_input 动态构造) 拼到 base persona 之后
        # 即可一次覆盖所有路径，无需改 6 个 template。
        # 详 docs/JARVIS_SOUL_DRIVE.md §4 注入路径。
        _t_soul = time.time()
        _base_persona = self.prompt_cache.get_or_build(
            'core_persona', lambda: JARVIS_CORE_PERSONA, ttl=86400.0
        )
        # Layer 0: Self Identity Anchor（"我是谁"的锚点）
        self_anchor_block = ''
        try:
            if self.self_anchor is not None:
                self_anchor_block = self.self_anchor.build_block(max_chars=900)
        except Exception:
            self_anchor_block = ''
        # Layer 1: Concerns（"我关心什么"）
        soul_block = ''
        try:
            if self.concerns_ledger is not None:
                soul_block = self.concerns_ledger.to_prompt_block(top_n=3, max_chars=600)
        except Exception:
            soul_block = ''
        # Layer 2: RelationalState（"我们之间" — inside jokes / protocols / unfinished / threads）
        relational_block = ''
        try:
            if self.relational_state is not None:
                relational_block = self.relational_state.to_prompt_block(
                    top_jokes=3, top_unfinished=2, top_threads=2, max_chars=700
                )
        except Exception:
            relational_block = ''
        # Layer 3: Attention Allocation（基于 user_input 动态构造，不缓存）
        # current_focus + long_term_watch。PENDING FOLLOWUPS 段已删（Layer 2 单源接管）。
        attention_block = ''
        try:
            from jarvis_attention import build_attention_block as _build_attn
            attention_block = _build_attn(
                concerns_ledger=self.concerns_ledger,
                relational_state=self.relational_state,
                user_input=user_input or '',
                stm=getattr(self, 'short_term_memory', None) or [],
                top_concerns=3,
                max_chars=500,
            )
        except Exception:
            attention_block = ''
        # 拼接：base PERSONA → Layer 0 → Layer 1 → Layer 2 → Layer 3
        _parts = [_base_persona]
        if self_anchor_block:
            _parts.append(self_anchor_block)
        if soul_block:
            _parts.append(soul_block)
        if relational_block:
            _parts.append(relational_block)
        if attention_block:
            _parts.append(attention_block)

        # 🩹 [β.5.43-D / 2026-05-20] Sir reply feedback inject (Sir 17:10 真理)
        # Sir 在 dashboard /items '评 Reply' 按 👍/👎/✏️ → 写 reply_feedback.jsonl.
        # 主脑下轮 prompt 看 [SIR LAST REPLY FEEDBACK / 24h] block, 学 tone 偏好.
        try:
            from jarvis_reply_feedback import (
                get_recent_reply_feedback, format_for_prompt
            )
            _fb_entries = get_recent_reply_feedback(hours=24, limit=10)
            if _fb_entries:
                _fb_block = format_for_prompt(_fb_entries)
                if _fb_block:
                    _parts.append(_fb_block)
        except Exception:
            pass

        # 🩹 [β.5.41-D / 2026-05-20] Sir Corrections inject (Sir 16:43 真理)
        # Sir 在 dashboard /items 改/删 item → 写 sir_corrections.jsonl.
        # 主脑下轮 prompt 看 corrections 知道 Sir 已纠正/已删, 不再用错版本/不再 reference 已删的事.
        try:
            from jarvis_actionable_items import get_recent_corrections
            recent = get_recent_corrections(hours=24, limit=15)
            if recent:
                _corr_lines = ['[SIR CORRECTIONS / 最近 24h]']
                _corr_lines.append('  Sir 在 dashboard 改了下面这些 item, 你下次用要用新版本/已删的别 reference:')
                for c in recent[-10:]:  # 最多 10 条进 prompt
                    act = c.get('action', '?')
                    cat = c.get('category', '?')
                    iid = c.get('item_id', '?')
                    note = c.get('sir_note', '')
                    if act == 'modify':
                        old = c.get('old', {})
                        new = c.get('new', {})
                        _change = ', '.join(
                            f"{k}: '{str(old.get(k, '?'))[:30]}' → '{str(v)[:30]}'"
                            for k, v in (new or {}).items()
                        )
                        _line = f"  - [改] {cat}/{iid}: {_change}"
                    elif act == 'delete':
                        _line = f"  - [删] {cat}/{iid} (Sir 不要 reference 这条)"
                    else:
                        _line = f"  - [{act}] {cat}/{iid}"
                    if note:
                        _line += f" — Sir 说: \"{note[:50]}\""
                    _corr_lines.append(_line)
                _corrections_block = '\n'.join(_corr_lines)
                _parts.append(_corrections_block)
        except Exception:
            pass

        # 🩹 [β.5.45 / 2026-05-20 22:00] Sir Lifetime Milestones inject
        # Sir 21:56 真理: lifetime anchor (declaration / insight) 不是 commitment,
        # 不要 nudge, replay only when Sir asks. 主脑看 pinned + 最近 3 条 entries,
        # 严格按 each entry's instruction_for_jarvis 处理 (do_not_use_against_sir).
        try:
            from jarvis_milestones import render_prompt_block as _ms_render
            _ms_block = _ms_render(max_recent=3)
            if _ms_block:
                _parts.append(_ms_block)
        except Exception:
            pass

        # 🩹 [P2-Gap12 / 2026-05-20 23:50] Recent Jarvis nudges across all channels
        # Sir 22:38/22:44 真痛点: ReturnSentinel + ProactiveCare 6min 内两次 nudge
        # 都 reference "shower", 6 channel 互不知重复. 加 [RECENT JARVIS NUDGES]
        # 让主脑看自己跨 channel 刚说过啥, 自决不重复主题. 准则 6: 不教硬规.
        try:
            from jarvis_recent_nudge_memory import to_prompt_block as _rn_block
            _rn_text = _rn_block(within_seconds=1800, max_show=5)
            if _rn_text:
                _parts.append(_rn_text)
        except Exception:
            pass

        # 🩹 [P4-Case4 / 2026-05-20 23:58] PENDING COMMITMENTS — 治 23:38 hallucinate "11:59"
        # Sir 23:38 case: Sir 忘了自己说几点睡, 问 Jarvis, 主脑回 "11:59 PM" hallucinate.
        # Sir 真说 23:30. 主脑没看 commitment 数据自己编 time.
        # 修: 注入真 commitment + promise 数据 (description + deadline + age) 让主脑 reference.
        try:
            _pc_lines = []
            # CommitmentWatcher.commitments (hard, with deadline_ts)
            try:
                _cw = getattr(self, 'commitment_watcher', None)
                if _cw is not None:
                    _cw_list = list(getattr(_cw, 'commitments', []) or [])
                    _now = time.time()
                    _active_cw = [
                        c for c in _cw_list
                        if not c.get('nudged') and float(c.get('deadline_ts', 0)) > 0
                    ]
                    _active_cw = sorted(_active_cw, key=lambda c: float(c.get('deadline_ts', 0)))[:6]
                    for _c in _active_cw:
                        _dl_ts = float(_c.get('deadline_ts', 0))
                        _gap_min = int((_dl_ts - _now) / 60)
                        _dl_str = time.strftime('%H:%M', time.localtime(_dl_ts))
                        _gap_str = (
                            f'{_gap_min}min ago' if _gap_min < 0
                            else f'in {_gap_min}min' if _gap_min < 60
                            else f'in {_gap_min // 60}h'
                        )
                        _src = _c.get('source', 'sir')
                        _pc_lines.append(
                            f"  - [{_src}] '{_c.get('description', '')[:60]}' "
                            f"@ {_dl_str} ({_gap_str})"
                        )
            except Exception:
                pass
            # PromiseLog (hard kind, has deadline_str)
            try:
                from jarvis_promise_log import get_default_log as _pl_get
                _plog = _pl_get()
                # 🩹 [P4-edge-A] Promise 字段是 self.promises 不是 _promises;
                # Promise 是 dataclass 不是 dict, 用 attr access 而不是 .get()
                if _plog is not None and hasattr(_plog, 'promises'):
                    for _pid, _p in (_plog.promises or {}).items():
                        _state = getattr(_p, 'state', '')
                        _kind = getattr(_p, 'kind', '')
                        _dl_s = getattr(_p, 'deadline_str', '')
                        if _state == 'pending' and _kind == 'hard' and _dl_s:
                            _desc = (getattr(_p, 'description', '') or '')[:60]
                            _author = getattr(_p, 'author', '?')
                            _pc_lines.append(
                                f"  - [PromiseLog/{_author}] '{_desc}' deadline={_dl_s[:20]}"
                            )
            except Exception:
                pass

            if _pc_lines:
                _pc_block = [
                    '[PENDING COMMITMENTS / NEAR DEADLINE — your real data, do not hallucinate]',
                    '  Use this when Sir asks "what time did I say" / "any commitment now" / etc.',
                ]
                _pc_block.extend(_pc_lines[:8])
                _pc_block.append(
                    '  [rule] Reference these exactly. Never invent timestamps / quotas / billing.'
                )
                _parts.append('\n'.join(_pc_block))
        except Exception:
            pass

        # 🩹 [Gap 1 / P5-ToM / 2026-05-21 01:00] SIR'S MIND RIGHT NOW block (Layer 6)
        # Jarvis 对 Sir 当下心智的 hypothesis (surface/deeper/unspoken need + 
        # emotional + relational temp). 主脑看 hypothesis 自决 reply 深度.
        # 跟 SelfAnchor (Layer 0 我是谁) / RelationalState (Layer 2 我们之间) 互补.
        try:
            from jarvis_sir_mental_model import render_prompt_block as _tom_block
            _tom_text = _tom_block(include_unspoken=True)
            if _tom_text:
                _parts.append(_tom_text)
        except Exception:
            pass

        # 🩹 [Gap 2 / P5-PreFlight / 2026-05-21 00:40] PreFlight Feedback 注入主脑
        # 主脑看上 N turn PreFlight 自审 verdict (scrap/edit). 自纠不再 callback.
        # Sir 22:04/22:19/23:02/23:43/23:49 反复 5 次道歉 — 这 block 让主脑学.
        try:
            _bus_pf = getattr(self, 'event_bus', None)
            if _bus_pf is not None:
                _pf_events = _bus_pf.recent_events(
                    within_seconds=600,  # last 10min
                    types={'preflight_verdict'},
                ) or []
                # only show scrap/edit verdicts (skip pass/fallback noise)
                _interesting = [
                    e for e in _pf_events
                    if (e.get('metadata', {}) or {}).get('verdict') in ('scrap', 'edit')
                ]
                if _interesting:
                    _pf_lines = [
                        '[PREFLIGHT FEEDBACK — your last reply self-check (last 10min)]',
                        '  Your past replies were judged unsolicited / hallucinatory / off-tone:',
                    ]
                    for _e in _interesting[-3:]:  # last 3 only
                        _meta = _e.get('metadata', {}) or {}
                        _v = _meta.get('verdict', '?')
                        _issues = _meta.get('issues', []) or []
                        _sir_excerpt = _meta.get('sir_utterance_excerpt', '')[:50]
                        _draft_excerpt = _meta.get('draft_excerpt', '')[:80]
                        _pf_lines.append(
                            f"  - [{_v.upper()}] Sir said \"{_sir_excerpt}\" → "
                            f"you drafted \"{_draft_excerpt}...\""
                        )
                        if _issues:
                            _pf_lines.append(f"      issue: {'; '.join(_issues[:2])[:120]}")
                    _pf_lines.append(
                        '  [lesson] Avoid: unsolicited callback to old over-claims; '
                        'inventing facts (timestamps/quotas); over-formal tone when Sir is casual. '
                        'Just answer the current turn cleanly.'
                    )
                    _parts.append('\n'.join(_pf_lines))
        except Exception:
            pass

        # 🩹 [β.5.43-F / 2026-05-20 19:10] ErrorBus — system error 主动暴露
        # Sir 17:10 真理 (6 缺口 F): '系统出错时主动告诉 Sir, 不装作没事'.
        # Jarvis 大量 try/except 静默吞错, 主脑不知道 module fail. 加 [SYSTEM ERRORS]
        # block 让主脑看到最近 10min moderate+ 错误, reply 时可主动 surface.
        try:
            from jarvis_error_bus import get_error_bus as _eb_get, SEVERITY_MODERATE
            _eb = _eb_get()
            _errs = _eb.recent_errors(
                within_seconds=600,
                min_severity=SEVERITY_MODERATE,
                max_n=8,
            )
            if _errs:
                _err_lines = ['[SYSTEM ERRORS / 最近 10min, moderate+]']
                _err_lines.append('  ⚠️ 下面 module 真出错了, 不是想象的, 你 reply 时可主动 surface:')
                for _e in _errs[:8]:
                    _sev_icon = {'minor': '⚪', 'moderate': '🟡', 'severe': '🔴'}.get(
                        _e.get('severity', '?'), '?'
                    )
                    _recov = '可自愈' if _e.get('recoverable') else '需 Sir 介入'
                    _err_lines.append(
                        f"  {_sev_icon} [{_e.get('module', '?')}] {_e.get('kind', '?')}: "
                        f"{_e.get('detail', '')[:120]} ({_recov})"
                    )
                _err_lines.append(
                    '  指引: 如果错误与 Sir 当前请求相关 → 主动告诉 Sir "我刚刚 X 出了问题"; '
                    '不相关 → 静默不强提 (Sir 不需要听 backlog 错误流水帐).'
                )
                _parts.append('\n'.join(_err_lines))
        except Exception:
            pass

        # 🩹 [β.5.44-E / 2026-05-20 19:02] IntentResolver 报告 — Sir 18:55 真治本
        # Sir 痛点: 主脑撒谎 "I've corrected my count" 但本轮零 mutation tool 调用.
        # 修法: IntentResolver 真调 tool 后 publish 'tool_called' + 'intent_resolved' SWM.
        # 主脑看 [INTENT RESOLVED THIS TURN] 知道哪个 tool 真成功 / 真失败,
        # reply 基于真实 mutation result — 不再撒谎.
        try:
            _bus = getattr(self, 'event_bus', None)
            if _bus is not None:
                _ir_events = _bus.recent_events(
                    within_seconds=60.0,
                    types={'intent_resolved'},
                )
                if _ir_events:
                    _ir = _ir_events[-1]  # 最新一条 (本 turn)
                    _meta = _ir.get('metadata') or {}
                    _tcs = _meta.get('tool_calls') or []
                    if _tcs:
                        _ir_lines = ['[INTENT RESOLVED THIS TURN / 系统真做了什么]']
                        _ir_lines.append('  IntentResolver 看完 Sir utterance + module candidates, 调了下面 tool:')
                        for _tc in _tcs[:6]:
                            _status = '✓ 成功' if _tc.get('ok') else f"✗ 失败 ({_tc.get('error', '?')[:60]})"
                            _ir_lines.append(f"  - {_tc.get('name', '?')}: {_status}")
                        _ir_lines.append(
                            '  ⚠️ Reply 务必 reflect 真实 result: tool ✓ → 可说 "noted/recorded"; '
                            'tool ✗ → 必须说 "I tried but couldn\'t..." / "kept in conversation only"; '
                            '没 tool 调 → 不能说任何 mutation verb (corrected/saved/updated 等).'
                        )
                        _parts.append('\n'.join(_ir_lines))
        except Exception:
            pass

        # 🩹 [β.2.9.4 / 2026-05-18] Mood Mirror (扩展 C): 给主脑 5 档 mood 估算.
        # 准则 6: 只给信号让主脑判, 不强制主脑用某 tone.
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            _snap = P.get_sensor_snapshot() or {}
            _br = float(_snap.get('backspace_ratio', 0) or 0)
            _sw = int(_snap.get('switch_frequency_5min', 0) or 0)
            _ev = bool(_snap.get('error_visible', False))
            _undo = int(_snap.get('shortcut_undo_5min', 0) or 0)
            _dur = float(_snap.get('session_duration_minutes', 0) or 0)
            _h = time.localtime().tm_hour
            _mood = 'neutral'
            if _br > 0.18 or _undo > 5 or (_ev and _sw > 8):
                _mood = 'frustrated'
            elif _sw > 12:
                _mood = 'scattered'
            elif _dur > 90 and _sw < 4:
                _mood = 'deep_focus'
            elif _h >= 23 or _h < 5:
                _mood = 'late_night_tired'
            elif _dur > 25 and _sw < 6:
                _mood = 'engaged'
            _mood_line = (
                f"[MOOD ESTIMATE — Sir 准则 6, hint only]\n"
                f"  estimated: {_mood} (backspace={_br:.0%}, switches/5min={_sw}, "
                f"err_visible={_ev}, undo={_undo}, session={_dur:.0f}min, hour={_h})\n"
                f"  use this to subtly calibrate tone — never mention raw sensor numbers."
            )
            _parts.append(_mood_line)
        except Exception:
            pass

        # 🩹 [β.2.9.1.2 / 2026-05-18] Wake-time Callback context (扩展方向 A 落地):
        # Sir 例子 00:55 "去睡了" → 01:04 又 wake → 主脑该知道 "Sir 9min 前说要睡了
        # 现在又来了" 自己决定要不要打趣 (不教句式 — 准则 6, 不强制 callback — 准则 5).
        try:
            _worker = getattr(self, '_worker_ref', None)
            _vt = getattr(_worker, 'voice_thread', None) if _worker else None
            if _vt is not None:
                _last_conv_end = float(getattr(_vt, 'last_conversation_end_time', 0) or 0)
                if _last_conv_end > 0:
                    _gap_s = time.time() - _last_conv_end
                    # 短间隔 (< 30min) wake 才注入 — 长间隔走 return_greeting 老路径
                    if 0 < _gap_s < 1800:
                        _gap_min = _gap_s / 60
                        # 最近一条 Sir utterance + 最近 hard promise
                        _last_sir = ''
                        try:
                            _stm = getattr(self, 'short_term_memory', None) or []
                            for _e in reversed(_stm[-5:]):
                                _u = str(_e.get('user', '') or '').strip()
                                if _u:
                                    _last_sir = _u[:160]
                                    break
                        except Exception:
                            pass
                        _recent_promise = ''
                        try:
                            from jarvis_promise_log import get_default_log
                            _plog = get_default_log()
                            _pendings = [
                                p for p in _plog.list_pending()
                                if (time.time() - p.registered_at) < 1800
                            ]
                            if _pendings:
                                _pendings.sort(key=lambda p: -p.registered_at)
                                _recent_promise = f"{_pendings[0].description[:100]} (you said this {int((time.time()-_pendings[0].registered_at)/60)} min ago)"
                        except Exception:
                            pass
                        _wake_lines = [
                            f"[WAKE CONTEXT — Sir just re-engaged after a short gap]",
                            f"- gap since last conversation: {_gap_min:.0f} minute(s)",
                        ]
                        if _last_sir:
                            _wake_lines.append(f"- Sir's last words last time: \"{_last_sir}\"")
                        if _recent_promise:
                            _wake_lines.append(f"- pending self-commitment: {_recent_promise}")

                        # 🩹 [β.2.9.5 / 2026-05-18] E: Cross-session callback — 加跨天主题
                        try:
                            _yesterday_topics = []
                            _stm = getattr(self, 'short_term_memory', None) or []
                            _yday_start = time.time() - 86400 - 12 * 3600
                            _yday_end = time.time() - 12 * 3600
                            for _e in _stm:
                                _ts = float(_e.get('when', 0) or 0)
                                if _yday_start < _ts < _yday_end:
                                    _u = str(_e.get('user', '') or '').strip()
                                    if _u and len(_u) > 8:
                                        _yesterday_topics.append(_u[:80])
                            if _yesterday_topics:
                                _wake_lines.append(
                                    f"- yesterday-ish topics ({len(_yesterday_topics)} items): "
                                    f"\"{_yesterday_topics[-1][:60]}\""
                                )
                        except Exception:
                            pass

                        # 🩹 [β.2.9.6 / 2026-05-18] F: Self-aware Comeback — 上次 unverified claim
                        try:
                            from jarvis_claim_tracer import get_stats
                            _stats = get_stats()
                            _unv = int(_stats.get('total_unverified', 0))
                            if _unv > 0:
                                _wake_lines.append(
                                    f"- your last sessions had {_unv} unverified claim(s) "
                                    f"(per ClaimTracer). Be especially careful with specifics "
                                    f"this turn."
                                )
                        except Exception:
                            pass

                        _wake_lines.append(
                            "  → If Sir's current input contradicts what he said before "
                            "(e.g. said sleep but woke up 9 min later), or echoes yesterday's "
                            "thread, you may naturally callback in your own voice. Not "
                            "required — only if real and the moment fits."
                        )
                        _parts.append('\n'.join(_wake_lines))
        except Exception:
            pass
        core_persona = '\n\n'.join(_parts)
        self._asm_stage_t['soul_block'] = (time.time() - _t_soul) * 1000

        # 🩹 [P0+20-β.2.3.1 / 2026-05-16] 灵魂工程注入诊断 log（Sir 22:48 提的要求）
        # 每轮 _assemble_prompt 装配后输出一行，让 Sir grep "[SOUL inject]" 就能看到：
        # - 每层各自注入的字符数（0 = 该层无内容跳过）
        # - 四层注入字符总和
        # - 被注入的 inside_jokes / top concerns / unfinished_business / threads 的 id 列表
        # 容错：任何 store/ledger 拿不到都不影响主路径（picked_* 兜底空 list）
        _picked_jokes: list = []
        _picked_unfinished: list = []
        _picked_protocols: list = []
        _picked_threads: list = []
        _picked_concerns: list = []
        try:
            if self.relational_state is not None:
                _picked_jokes = [
                    j.id for j in self.relational_state._rank_inside_jokes(3)
                ]
                _picked_unfinished = [
                    u.id for u in self.relational_state._rank_unfinished(2)
                ]
                _picked_protocols = [
                    p.id for p in self.relational_state.list_protocols()[:3]
                ]
                _picked_threads = [
                    t.id for t in self.relational_state._rank_threads(2)
                ]
        except Exception:
            pass
        try:
            if self.concerns_ledger is not None:
                _ac = sorted(
                    self.concerns_ledger.list_active(),
                    key=lambda c: -getattr(c, 'severity', 0.0),
                )
                _picked_concerns = [c.id for c in _ac[:3]]
        except Exception:
            pass
        try:
            from jarvis_utils import bg_log as _bg_soul
            _L0c = len(self_anchor_block)
            _L1c = len(soul_block)
            _L2c = len(relational_block)
            _L3c = len(attention_block)
            _total_soul = _L0c + _L1c + _L2c + _L3c
            _bg_soul(
                f"🪞 [SOUL inject] L0={_L0c}c L1={_L1c}c L2={_L2c}c L3={_L3c}c "
                f"total={_total_soul}c | jokes={_picked_jokes} "
                f"concerns={_picked_concerns} unf={_picked_unfinished} "
                f"proto={_picked_protocols} threads={_picked_threads}"
            )
        except Exception:
            pass

        # 🩹 [P0+20-β.1.15 / 2026-05-16] how_to_respond 瘦身（PROMPT_REFACTOR_PLAN §3 L0 精简）：
        # 原 3673 chars 含两大段：
        #   段 1（通用 directives，~1500 chars）— 保留：风格 / STM 反应 / Scene tags / SHORT INPUT
        #         / Bilingual / ASR / Desktop / butler 边界
        #   段 2（SMART ROUTING / TOOL USE / MEMORY WRITE / REMINDER READ，~2100 chars）— 已搬 L2:
        #         smart_routing_working_feed / correction_writepath_no_tool / fuzzy_candidates_policy
        #         / reminder_read_truth_source (β.1.15 新增 #14)
        # 目标：3673 → ~1100 chars (-70%)
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
- Bilingual: Speak English ONLY. Append ---ZH--- Chinese translation at the VERY END of EVERY response. MANDATORY — never skip it, even when using tools.
- ASR errors: deduce true meaning from context. Ignore transcription typos.
- Desktop PC: no battery/power/charge concepts. Never reference these.
- You are a butler, not an autonomous agent. NEVER propose code changes unless asked.
- NEVER discuss your own architecture, codebase, or implementation details unless Sir explicitly asks.
- Tool / memory / reminder behavior rules → see L2 directives injected below as needed.""",
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

        # [P0+20-β.2.4.3 / 2026-05-16] 老路径退役第 3 步：删 jokes_str / milestones_str
        # 生成（Layer 2 RelationalState 单源接管）。projects/progression 仍由 sir_profile
        # 提供（Sir 画像范畴）。详 docs/JARVIS_SOUL_DRIVE.md
        projects = sir_profile.get("active_projects", [])
        projects_str = ", ".join(projects[-5:]) if projects else "(none)"
        progression = sir_profile.get("skill_progression", [])
        progression_str = "\n".join([f"  - {s.get('skill','?')} (confidence: {s.get('confidence','?')})" for s in progression[-5:]]) if progression else "  (none yet)"

        # 🩹 [P0+20-β.1.21 / 2026-05-16] 分阶段 timing 收集器
        if not hasattr(self, '_asm_stage_t') or not isinstance(self._asm_stage_t, dict):
            self._asm_stage_t = {}

        # 🩹 [P0+20-β.1.21 / 2026-05-16] profile_block 本轮缓存（避免 4 次重复构造）
        _pc_t = time.time()
        _pc_block_value = self.profile_card.to_prompt_block()
        self._asm_stage_t['profile_block'] = (time.time() - _pc_t) * 1000
        # 暴露给本类方法 + 字符串模板（_pc_block_cached 调用方）
        self._pc_block_cached = lambda: _pc_block_value

        _t_hc = time.time()
        self.habit_clock.update_from_probe()
        self._asm_stage_t['habit_clock_update'] = (time.time() - _t_hc) * 1000

        _t_ctx_start = time.time()
        context_str = self.context_router.assemble(current_hour)
        _t_ctx_done = time.time()
        self._asm_stage_t['context_router'] = (_t_ctx_done - _t_ctx_start) * 1000

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
            # [P0+20-β.2.4.3 / 2026-05-16] 老路径退役：删 inside_jokes / milestones
            # 两 branch（Layer 2 BETWEEN US 块单源注入）。详 docs/JARVIS_SOUL_DRIVE.md
            chapter_blocks = []
            if "projects" in soul_tags:
                chapter_blocks.append(f"Active Projects: {projects_str}")
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
            self._asm_stage_t['memory_gateway'] = (_t_mem_done - _t_mem_start) * 1000

        skill_tree_str = ""
        if hasattr(self, 'skill_tree') and _allow_full and not _skip_heavy:
            _t_skill_start = time.time()
            skill_tree_str = self.skill_tree.get_skill_summary_for_prompt()
            _t_skill_done = time.time()
            self._asm_stage_t['skill_tree'] = (_t_skill_done - _t_skill_start) * 1000

        anticipator_ctx = ""
        if hasattr(self, 'prompt_center') and self.prompt_center and self.prompt_center.anticipator and not _skip_heavy:
            _t_anti_start = time.time()
            anticipator_ctx = self.prompt_center.anticipator.get_preloaded_context()
            _t_anti_done = time.time()
            self._asm_stage_t['anticipator'] = (_t_anti_done - _t_anti_start) * 1000

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

        # 🩹 [P0+20-β.1.21 / 2026-05-16] inline 详细版改"按 L2 fired 信号注入"（之前 always-注入）
        # 详细版（PROMISE_PROTOCOL_DIRECTIVE ~2000c / TOOL_HONESTY_DIRECTIVE ~1500c /
        # FUZZY_CANDIDATES_POLICY ~1000c）含 JSON 格式 spec / 工具行为约束等关键细节，
        # 删了会损失信息。但每轮都注入浪费 ~4500 chars。
        # 折中：复用 L2 registry 的 fired 信号，只在 trigger 命中时注入详细版（与 L2 简化版叠加）。
        # 净效果：normal chat 节省 ~4500 chars；need-spec 场景仍有详细 spec。
        _l2_fired_set = set(getattr(self, '_l2_last_fired_ids', []) or [])

        promise_protocol_directive = ""
        if 'promise_protocol_directive' in _l2_fired_set:
            try:
                from jarvis_skill_registry import PROMISE_PROTOCOL_DIRECTIVE
                promise_protocol_directive = PROMISE_PROTOCOL_DIRECTIVE
            except Exception:
                promise_protocol_directive = ""

        tool_honesty_directive = ""
        if 'tool_honesty_directive' in _l2_fired_set:
            try:
                from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE
                tool_honesty_directive = TOOL_HONESTY_DIRECTIVE
            except Exception:
                tool_honesty_directive = ""

        fuzzy_candidates_policy = ""
        if 'fuzzy_candidates_policy' in _l2_fired_set:
            try:
                from jarvis_fuzzy_resolver import FUZZY_CANDIDATES_POLICY
                fuzzy_candidates_policy = FUZZY_CANDIDATES_POLICY
            except Exception:
                fuzzy_candidates_policy = ""

        # 🩹 [P0+20-β.2.7.1 / 2026-05-17] 灵魂通用化 Phase 1：mode='nudge'
        # 详 docs/JARVIS_SOUL_UNIVERSALIZATION.md Phase 1。
        # 核心逻辑抽到 _build_nudge_prompt helper，方便 unit test 独立调用。
        if mode == "nudge":
            return self._build_nudge_prompt(
                core_persona=core_persona,
                ledger_data=ledger_data,
                _diag_sizes={
                    'L0': len(self_anchor_block),
                    'L1': len(soul_block),
                    'L2': len(relational_block),
                    'L3': len(attention_block),
                },
            )

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
{getattr(self, '_l2_injected_block', '')}

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
{getattr(self, '_l2_injected_block', '')}

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
{_pc_block_value}
{correction_context}
{style_adjustment}

=== REAL-TIME STATE ===
{ledger_str}

[SYSTEM CLOCK]: {current_time}
{getattr(self, '_l2_injected_block', '')}

User: {user_input}
{system_alert_text}
"""

        if mode == "light":
            return f"""{core_persona}

{context_str}
{_pc_block_value}
{correction_context}
{style_adjustment}
{content_pref}
[SYSTEM CLOCK]: {current_time}
{getattr(self, '_l2_injected_block', '')}

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

        # [β.5.0-A / 2026-05-19] SharedWorldModel block — 准则 6 数据强耦合
        # event_bus.to_prompt_block 走旧 type_priority 静态权重 + 时近度.
        # to_swm_block 走 (salience × recency) 动态评分, 显示 sal+age+source+desc.
        # 主脑看 raw signal pool 12 条自决, 不教反应方式. 跟 event_bus_block 并列展示
        # (后者按 conversation_event 链, 前者按全局 SWM 显著性).
        swm_block = ""
        try:
            bus = getattr(self, 'event_bus', None)
            if bus is not None and hasattr(bus, 'to_swm_block'):
                swm_block = bus.to_swm_block(n=12, max_chars=900, salience_floor=0.3)
        except Exception:
            swm_block = ""

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

{swm_block}

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

{_pc_block_value}

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

{tier_routing}

[Tier 2 Tool Library]:
{chat_organs}

[YOUR KNOWLEDGE BASE]:
--- Long-Term Memory ---
{ltm_context}

{commitment_context}
[SYSTEM CLOCK]: {current_time}
{getattr(self, '_l2_injected_block', '')}

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
            'profile_block': len(self._pc_block_cached()),
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
        # 🩹 [P0+20-β.1.21 / 2026-05-16] 加分阶段 timing：让 Sir 看清哪一段慢
        _asm_total_ms = int((time.time() - _t_asm_start) * 1000)
        try:
            from jarvis_utils import bg_log
            try:
                from jarvis_utils import _TEE_QUEUE as _tee_q_asm
                _q_depth_asm = _tee_q_asm.qsize()
            except Exception:
                _q_depth_asm = -1
            bg_log(f"⏱️ [Prompt Size] 总{len(result)}chars | TOP: {_size_report}")
            # 分阶段 timing（如果有的话）
            _stage_t = getattr(self, '_asm_stage_t', None)
            if _stage_t and isinstance(_stage_t, dict):
                _stages = " | ".join(f"{k}={int(v)}ms" for k, v in sorted(_stage_t.items(), key=lambda x: -x[1])[:6])
                bg_log(f"🔬 [Asm Diag] 总{_asm_total_ms}ms | TOP stages: {_stages} | tee_queue_depth={_q_depth_asm}")
            else:
                bg_log(f"🔬 [Asm Diag] _assemble_prompt 总耗时 {_asm_total_ms}ms | tee_queue_depth={_q_depth_asm}")
        except Exception:
            print(f"⏱️ [Prompt Size] 总{len(result)}chars | TOP: {_size_report}", file=sys.stderr)
        # 清理本轮 stage 计时
        try:
            if hasattr(self, '_asm_stage_t'):
                self._asm_stage_t = {}
        except Exception:
            pass
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

    def _build_nudge_prompt(self, core_persona: str, ledger_data: dict = None,
                             _diag_sizes: dict = None) -> str:
        """[P0+20-β.2.7.1 / 2026-05-17] 灵魂通用化 Phase 1 helper。

        让 SmartNudge / Conductor / CommitmentWatcher 等所有"主动发声"路径的 prompt
        包含 Layer 0-3 注入。通过复用 chat_bypass._build_public_layers
        （它含 BEHAVIORAL DIRECTIVES / TIME CONTEXT / EMOTION 等关键段），
        把头部 JARVIS_CORE_PERSONA 替换成本调用上游构造的 core_persona（含 Layer 0-3）。

        Args:
            core_persona: 已含 Layer 0-3 注入的 PERSONA 串（_assemble_prompt 顶部构造）
            ledger_data: 透传给 _build_public_layers 的情绪 ledger
            _diag_sizes: 诊断 log 用的 L0-L3 字符数 dict

        Returns:
            完整的 nudge public_layers 字符串。失败时退化返回 core_persona。
        """
        cb = getattr(self, 'chat_bypass', None)
        if cb is None:
            return core_persona
        try:
            public_str = cb._build_public_layers(ledger_data)
            _JCP_const = JARVIS_CORE_PERSONA
            if public_str.startswith(_JCP_const):
                public_str = core_persona + public_str[len(_JCP_const):]
            else:
                public_str = core_persona + "\n\n" + public_str
            try:
                from jarvis_utils import bg_log as _bg_n
                _ds = _diag_sizes or {}
                _bg_n(
                    f"🪞 [Nudge SOUL inject] mode=nudge "
                    f"prompt_len={len(public_str)}c "
                    f"L0={_ds.get('L0', 0)}c L1={_ds.get('L1', 0)}c "
                    f"L2={_ds.get('L2', 0)}c L3={_ds.get('L3', 0)}c"
                )
            except Exception:
                pass
            return public_str
        except Exception as _nudge_err:
            try:
                from jarvis_utils import bg_log as _bg_nerr
                _bg_nerr(
                    f"⚠️ [Nudge SOUL inject] fallback: "
                    f"{type(_nudge_err).__name__}: {str(_nudge_err)[:80]}"
                )
            except Exception:
                pass
            return core_persona

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
        # 🩹 [β.5.29 / 2026-05-20] STM source 分嵌 (FOUNDATION_AUDIT 尾巴).
        # 老裸 'user -> jarvis' LLM 看不出这是 Sir / SYS / JARVIS ㎤ 误判幻觉.
        # 新 helper 加 [SIR]/[SYS]/[JARVIS]/[AMBIENT] 前缀.
        from jarvis_utils import format_stm_for_prompt as _fmt_stm
        stm_context = _fmt_stm(self.short_term_memory, take_last=6, max_chars=2000)
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
                
                # β.5.29: source 分嵌
                from jarvis_utils import format_stm_for_prompt as _fmt_stm_full
                current_stm = _fmt_stm_full(self.short_term_memory, take_last=999, max_chars=10000, include_time=True)
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
                            # β.5.29: source 分嵌
                            from jarvis_utils import format_stm_for_prompt as _fmt_stm_replan
                            current_stm = _fmt_stm_replan(self.short_term_memory, take_last=999, max_chars=10000, include_time=True)
                            
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
                    
                    # 重新提取最新的 6 条短时记忆 (β.5.29 source 分嵌)
                    from jarvis_utils import format_stm_for_prompt as _fmt_stm_recovery
                    stm_context = _fmt_stm_recovery(self.short_term_memory, take_last=6, max_chars=2000)
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

        # 🩹 [β.5.37-B / 2026-05-20] SleepDetector publish-only 重构
        # Sir 14:39 校正: 不再 handle_confirmation_response 硬 keyword match.
        # 详 docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md §4.1.
        # 老路径 (硬 confirm match) revert:
        #   if detector.is_pending_confirmation: handle_confirmation_response... ← 已删
        # 新路径: detect() publish 'sleep_intent_signal' 到 SWM, 主脑看 evidence 自决.
        # 仅高置信 'sleep' (score >= 0.70) 仍 hard trigger (Sir 真明确说了, 省 LLM 来回).
        # 中置信 'confirm' (0.50-0.70) 不再 set pending, 主脑看 SWM signal 自决问 Sir or wait.

        result = detector.detect(user_input)
        if result == 'sleep':
            print(f"[CentralNerve] 高置信度休眠意图: '{user_input}'")
            self._trigger_sleep_mode()
        elif result == 'confirm':
            # β.5.37-B: 不再 request_confirmation set pending state.
            # detect() 已 publish 'sleep_intent_signal' 到 SWM. 主脑看到自决:
            # - 可问 Sir "您要睡了吗?"
            # - 可等待 Sir 进一步表态
            # - 可看到 [sir_afk_detected] 决定不再追问
            print(f"[CentralNerve] 中置信度休眠意图 (主脑判): '{user_input[:60]}' (signal 已 publish to SWM)")

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

        # 🩹 [β.5.39 / 2026-05-20] log sleep event 到 sir_sleep_pattern_vocab
        # 让 L7 reflector + ProactiveCare distance 公式有数据 (Sir 真理动态催睡)
        try:
            from jarvis_sleep_pattern_reflector import log_sleep_event
            now = time.localtime()
            sleep_hour = now.tm_hour + now.tm_min / 60.0
            if now.tm_hour < 6:
                sleep_hour += 24  # 跨午夜算 24+
            log_sleep_event(sleep_hour, source='nerve_trigger_sleep_mode')
        except Exception as _e_log:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [_trigger_sleep_mode] log_sleep_event err: {_e_log}")
            except Exception:
                pass

        import threading
        threading.Thread(target=self._trigger_end_of_day_archive, daemon=True).start()

    def _detect_wake_up(self):
        gate = getattr(self, 'nudge_gate', None)
        if not gate or not gate.is_sleep_mode():
            return False
        sleep_duration = gate.sleep_duration_seconds()
        # 🩹 [β.2.9.1.3] _detect_wake_up = Sir 真主动唤醒 (wake_word/对话开始), force=True
        gate.deactivate_sleep_mode(force=True)
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
        # 🩹 [β.2.9.1.4 / 2026-05-18] Sir 08:10 反馈: 主动质疑是 Jarvis 人设, 别删.
        # 撤回 β.2.9.1.3 的"改 bg_log only". 恢复 vocal.say + 加去重 (1 次 sleep_intent
        # 内只 fire 1 次, 不重复刷屏).
        # 🩹 [β.5.32 / 2026-05-20] Sir 03:55 实测 BUG: dismissal → 0.0 分钟立刻 wake +
        # 询问 "只 1 分钟" — 光速触发. Root cause: dismissal 后 keyboard/mouse 还在动
        # 立刻被 _on_activity_wake 触发. 加 30s minimum grace: 0-30s 内 silent (明显
        # 是 dismissal 残留活动), 30s-300s 才真问.
        if sleep_duration < 30:
            return
        if sleep_duration < 300:
            # 去重: 1 次 sleep_intent 窗口内只发一次
            if getattr(self, '_short_sleep_questioned_at', 0) > 0 and \
               (time.time() - self._short_sleep_questioned_at) < 3600:
                return
            self._short_sleep_questioned_at = time.time()

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

