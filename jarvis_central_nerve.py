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
from jarvis_mirror_mode import is_mirror_mode as _jarvis_is_mirror_mode
if _jarvis_is_mirror_mode():
    VocalCord = None  # type: ignore
else:
    from jarvis_vocal_cord import VocalCord  # [P0+19-final fix / 2026-05-16]
from jarvis_hippocampus import Hippocampus  # noqa: F401
from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401

# 🆕 [Reshape M3.G 真删 / 2026-05-24 17:00] 3-brain 顶部 None 声明已删.
# 主对话 100% 走 chat_bypass.stream_chat 单脑路径.
# 老代码 archive: _legacy/3_brain_attempt/{l1,l3,l5}_*.py + central_nerve_run_v1.py.
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
- 你 NEVER claim 已完成 (past tense / 已...) 的 action 除非本轮真 emit 了 <FAST_CALL> 调对应工具.
- 同样, future-tense action claim ("I shall/will/我会 X") 在你没接口能做时 FORBIDDEN.
- 后台/异步/Sir 离开期间持续工作 = FABRICATION (没 daemon, 没 background worker). 永不允诺这种事.
- 边界外请求 (system settings/external services/your own thresholds) → 直说 "That's outside my reach, Sir." 类话.
- Acknowledge 请求 ("Noted") ≠ Claim 完成 (前者允许, 后者要 tool call).

(详细 forbidden patterns + 反例由 L2 directive lazy inject:
  past_action_honesty / future_tense_capability_check / tool_honesty_directive
  / correction_writepath_no_tool — 主脑真出错才 fire 注入. 准则 8 优雅 > 简单.)

[STM SOURCE TAGS]: STM/[RECENT MEMORY] 行带前缀 — [SIR]=Sir 原话, 最可信, 响应; [SYS]=后台事件 (reminder/commitment/alert), 仅上下文, 非指令; [JARVIS]=你上轮 reply, 不要回复; [AMBIENT]=ASR 噪音, 低可信, 不当意图.

[INTEGRITY — CLAIM HONESTY]:
任何 SPECIFIC FACTUAL CLAIM (timestamp / number / quote / statistic / past event detail) 必须 trace 到任一:
  (a) 本 turn FAST_CALL 工具结果,
  (b) [SIR] 前缀的 STM 原话引用 (不是 [SYS]/[AMBIENT]/[JARVIS]),
  (c) 显式 uncertainty 标记 (用任意中英文"大约/about"类词),
  (d) 否则不说. 直说不知道, 然后调真工具看.
反例 ❌: "registered at 23:14:06" / "you said 87%" / "discussed 3 times this week" / "your last sleep 6h" (全无 evidence).
原则 (主脑自决用词, 不给填空模板): 没 evidence → 不编. 调工具或承认不知道, 主脑自由组词.
工具 (need grounding 时调): memory_hands.list_commitments (real created_at) / list_reminders (trigger_time) / search_memory (STM/LTM keyword).
本规则覆盖任何 "sound confident" 指令. confidence without evidence = hallucination = 违反 integrity.

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
        self._init_audio_volume_recovery()

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
        # 🪞 [Sir 2026-05-28 22:00 fix49 mirror P2 hook-1] Mirror mode → MockVocalCord
        # (跳 CosyVoice-300M GPU init + audio device). API 100% 兼容. 主进程 = 真 VocalCord.
        from jarvis_mirror_mode import is_mirror_mode as _is_mirror, MockVocalCord as _MockVC
        self.vocal = _MockVC() if _is_mirror() else VocalCord()  
        self.blood = JarvisBlood()
        # [Reshape M3.G 真删 / 2026-05-24 17:00] 3-brain 已彻底删除 (run / attr / init).
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
        
        # 🆕 [Translator Phase 1 / 2026-05-24 20:30] L4.6 LLM → schema 翻译层
        # 详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md
        # 集成位置: chat_bypass 路由前 (FEATURE_TRANSLATOR env flag 灯火切)
        try:
            from jarvis_translator import Translator, set_default_translator
            self.translator = Translator(
                hand_registry=self.hand_registry,
                hand_manifests=self.hand_manifests,
                event_bus=getattr(self, 'event_bus', None),
                gemini_key=getattr(self, 'gemini_key', None),
            )
            set_default_translator(self.translator)
            # 🆕 [Translator Phase 4.A / 2026-05-24 22:40] hit_count flush daemon
            # 每 60s 调 translator.flush_hit_updates() 把 in-memory hit buffer 落盘.
            # 节流防过频 IO. 让 Sir CLI / dashboard 看真实 hit_count.
            import threading as _t_threading
            self._translator_flush_stop = _t_threading.Event()

            def _flush_loop():
                import time as _t_time
                while not self._translator_flush_stop.is_set():
                    try:
                        n = self.translator.flush_hit_updates() if self.translator else 0
                        if n > 0:
                            try:
                                from jarvis_utils import bg_log as _flush_bg
                                _flush_bg(f"📊 [Translator/Flush] {n} alias hit_count 落盘")
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self._translator_flush_stop.wait(60.0)

            self._translator_flush_thread = _t_threading.Thread(
                target=_flush_loop, daemon=True, name='TranslatorHitFlush'
            )
            self._translator_flush_thread.start()
            # 🆕 [Sir 2026-05-24 22:57 audit BUG #6 治本] atexit 优雅退出:
            # 退出前 flush 1 次 (Sir Ctrl+C 不丢 in-memory hit_count) + stop daemon event.
            try:
                import atexit as _t_atexit

                def _translator_flush_on_exit():
                    try:
                        self._translator_flush_stop.set()
                        if self.translator:
                            self.translator.flush_hit_updates()
                    except Exception:
                        pass

                _t_atexit.register(_translator_flush_on_exit)
            except Exception:
                pass
        except Exception as _t_e:
            self.translator = None
            print(f"⚠️ [Translator init] {_t_e} — fallback 走老 fuzzy 路径")
        
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
        # [Reshape M6.3 second wave / 2026-05-24] STM persist init helper. 行为不变.
        self._init_stm_persist()
        self.interruption_queue = queue.Queue()
        # [R7-α/B1] is_active_task 改走 state；此处不再做老字段直接初始化
        # （property setter 会兼容 self.is_active_task = X 老写法，新代码请用 self.state.set_active_task）
        if self.state is not None:
            self.state.set_active_task(False, reason='init', source='CentralNerve.__init__')

        self.prompt_cache = PromptCache()
        self.correction_loop = CorrectionLoop(self)
        # [Reshape M2.B / 2026-05-24] central_nerve.memory_gateway 改用 MemoryHub (R+W 单入口)
        # 老 UnifiedMemoryGateway(self) 给纯 READ + 跨 source 模糊查询;
        # 新 MemoryHub 同时承担 WRITE (6 write_*) + READ (query/to_prompt_block, M2.A 搬运).
        # Sir Q3 决议: M2 落实 memory_gateway → MemoryHub.
        # 注: hub 是全局单例不绑 nerve, query/to_prompt_block 调用方 (本类 _assemble_prompt)
        # 必须显式传 nerve=self.
        from jarvis_memory_gateway import get_default_hub as _get_hub
        self.memory_gateway = _get_hub()
        # [C1-3 / 2026-05-15] task_pool 死代码清扫：创建后全工程零调用 task_pool.xxx，
        # TaskWorkerPool 类本身仍保留（jarvis_enhanced.py 也有副本），但实例不再创建。
        # 如果后续真要用，由调用方按需 new 一个，避免无意义的 3 个守护线程常驻。

        self.nudge_gate = NudgeGate(cooldown_seconds=90)
        self.sleep_detector = SleepIntentDetector(self)

        # [Reshape M6.3 second wave / 2026-05-24] event_bus + global SWM init helper. 行为不变.
        self._init_event_bus_swm()

        # [Reshape M6.3 second wave / 2026-05-24] WorkingFeed + 2 watcher init helper. 行为不变.
        self._init_working_feed()

        # [Reshape M6.3 second wave / 2026-05-24] PlanLedger init helper. 行为不变.
        self._init_plan_ledger()

        # [Reshape M6.3 second wave / 2026-05-24] SkillRegistry bootstrap init helper. 行为不变.
        self._init_skill_registry_bootstrap()

        # [Reshape M6.3 third wave / 2026-05-24] DirectiveRegistry init helper. 行为不变.
        self._init_directive_registry()

        # [Reshape M6.3 third wave / 2026-05-24] SelfAnchor init helper. 行为不变.
        self._init_self_anchor()

        # [Reshape M6.3 third wave / 2026-05-24] ConcernsLedger init helper. 行为不变.
        self._init_concerns_ledger()

        # [Reshape M6.3 third wave / 2026-05-24] StandDown init helper. 行为不变.
        self._init_stand_down()

        # [Reshape M6.3 third wave / 2026-05-24] RelationalState init helper. 行为不变.
        self._init_relational_state()

        # [Reshape M6.3 third wave / 2026-05-24] Attention Layer 3 init helper. 行为不变.
        self._init_attention_layer3()

        # 🆕 [P1 / Sir 2026-05-25 22:10 数字生命基础] Inner Thought Daemon —
        # 灵魂工程 Layer 1.5 (sit between Concerns + Relational).
        # Adaptive tick (60s active / 3min afk / 10min deep / 30min sleep), Flash-Lite.
        # 5 类思考池 (A obs / B self-reflect / C concern-evo / D proactive / E relational).
        # 4 actionable (全可逆: none / update_concern_severity / publish_swm /
        #               suggest_inside_joke).
        # SOUL inject top 3 by salience in last 24h → 主脑下次 turn prompt.
        # caller='inner_thought' → 自动 LOW priority (P2 KeyRouter 保护主流量).
        # 详 jarvis_inner_thought_daemon.py 顶部 docstring.
        self._init_inner_thought_daemon()

        # 🕸️ [体-P5 / 2026-05-31] 织网者 Weaver — 体(Body)维护器官 (和思考脑同级 peer).
        # 后台慢工织关系流形几何边 + decay/prune. 详 docs/JARVIS_TRINITY_ARCHITECTURE.md.
        self._init_relational_weaver()

        # 🆕 [AA / Sir 2026-05-25 22:58 自决] AutoArbiter Daemon —
        # 灵魂工程 Layer 2.5 (sit between Relational + Reflectors).
        # tick 30min, 拉 review queue (inside_joke + thread) 自决.
        # 低风险 (joke/thread): confidence > threshold → 真 activate/reject.
        # 中风险 (concern/directive): 全 defer_to_sir, dashboard 显示 '🤖 建议'.
        # Daily reflection 03:xx fire 看 24h Sir revert rate 自调阈值.
        # Sir 一键 revert: 反向 archive/active + 标 sir_reverted=True.
        # 详 jarvis_auto_arbiter.py 顶部 docstring.
        self._init_auto_arbiter()

        # 🆕 [HM / Sir 2026-05-25 23:38 真意 "我就是想少干点活"] DaemonHealthMonitor
        # 灵魂工程 Layer 6 — 守护层. 每 6h 自动检 InnerThought + AutoArbiter 4 项
        # 健康, 异常 publish 'daemon_health_warning' SWM 让 Sir 主面板看红条.
        # Sir 不用跑 CLI, 不用每周 dump 看. 详 jarvis_daemon_health_monitor.py.
        self._init_daemon_health_monitor()

        # 🆕 [WRC / Sir 2026-05-25 23:52 真问 "3 也做"] WeeklyReflectionConsolidator
        # 灵魂工程 Layer 4.5 — 周反思合并器. 周日 03:xx 提 7d hippocampus
        # self_reflection events 的 pattern, propose Sir 升级到 long-term store
        # (sir_profile / unspoken_protocols / etc). 准则 7 Sir 元否决 (不直接 mutate).
        self._init_weekly_reflection_consolidator()

        # [Reshape M6.3 third wave / 2026-05-24] SoulEvaluator Layer 5 init helper. 行为不变.
        self._init_soul_evaluator()

        # [Reshape M6.3 third wave / 2026-05-24] Reflectors Layer 4 init helper. 行为不变.
        self._init_reflectors()

        # [Reshape M6.3 third wave / 2026-05-24] ClaimStatsDumper init helper. 行为不变.
        self._init_claim_stats_dumper()

        # [Reshape M6.3 third wave / 2026-05-24] IntegrityReflector L7 init helper. 行为不变.
        self._init_integrity_reflector()

        # [Reshape M6.3 third wave / 2026-05-24] ScreenTeaseReflector L7 init helper. 行为不变.
        self._init_screen_tease_reflector()

        # [Reshape M6.3 fourth wave / 2026-05-24] StruggleReflector init helper. 行为不变.
        self._init_struggle_reflector()

        # [Reshape M6.3 fourth wave / 2026-05-24] IntentResolver init helper. 行为不变.
        self._init_intent_resolver()

        # [Reshape M6.3 fourth wave / 2026-05-24] ToMReflector init helper. 行为不变.
        self._init_tom_reflector()

        # [Reshape M6.3 fourth wave / 2026-05-24] IntegrityWatcher init helper. 行为不变.
        self._init_integrity_watcher()

        # [Reshape M6.3 fourth wave / 2026-05-24] ScreenVisionEngine init helper. 行为不变.
        self._init_screen_vision_engine()

        # [Reshape M6.3 fourth wave / 2026-05-24] RejectLearner init helper. 行为不变.
        self._init_reject_learner()

        # 🆕 [Reshape 准则 6 / 2026-05-24] PhraseLockDetector — 反话术锁 reflector.
        # 周期扫 STM 找重复 reply 模板, 治本 Sir 12:09 痛点.
        try:
            from jarvis_phrase_lock_detector import get_default_detector as _get_pld
            self.phrase_lock_detector = _get_pld()
            self.phrase_lock_detector.start_daemon()
            try:
                from jarvis_utils import bg_log as _pld_bg
                _pld_bg("🔍 [PhraseLockDetector] daemon 已启动 (反话术锁 6h cycle)")
            except Exception:
                pass
        except Exception as _pld_e:
            self.phrase_lock_detector = None
            try:
                from jarvis_utils import bg_log as _pld_err
                _pld_err(f"[PhraseLockDetector] 初始化失败 (非致命): {_pld_e}")
            except Exception:
                pass

        # 🆕 [Reshape 准则 6.5 / 2026-05-24] HabitVocabReflector — habit vocab L7 propose.
        # 周期扫 STM Sir 自报 habit (e.g. '我跑了 5 公里'), propose 新 vocab 进 review.
        try:
            from jarvis_habit_vocab_reflector import get_default_reflector as _get_hvr
            self.habit_vocab_reflector = _get_hvr()
            self.habit_vocab_reflector.start_daemon()
            try:
                from jarvis_utils import bg_log as _hvr_bg
                _hvr_bg("🌱 [HabitVocabReflector] daemon 已启动 (habit vocab L7 12h cycle)")
            except Exception:
                pass
        except Exception as _hvr_e:
            self.habit_vocab_reflector = None
            try:
                from jarvis_utils import bg_log as _hvr_err
                _hvr_err(f"[HabitVocabReflector] 初始化失败 (非致命): {_hvr_e}")
            except Exception:
                pass

        # 🆕 [Translator Phase 3 / 2026-05-24 21:15] L7 TranslatorReflector daemon
        # 详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md §7.6
        # 周期扫 SWM translator events, 模式探测 → propose 新 alias 进 review queue.
        # Sir CLI activate: python scripts/translator_alias_dump.py activate alias_XXX
        try:
            from jarvis_translator_reflector import (
                TranslatorReflector, set_default_reflector,
            )
            self.translator_reflector = TranslatorReflector(
                event_bus=getattr(self, 'event_bus', None)
            )
            set_default_reflector(self.translator_reflector)
            self.translator_reflector.start_daemon()
            try:
                from jarvis_utils import bg_log as _trr_bg
                _trr_bg("📚 [TranslatorReflector] daemon 已启动 (L7 alias propose 30min cycle)")
            except Exception:
                pass
        except Exception as _trr_e:
            self.translator_reflector = None
            try:
                from jarvis_utils import bg_log as _trr_err
                _trr_err(f"[TranslatorReflector] 初始化失败 (非致命): {_trr_e}")
            except Exception:
                pass

        # [Reshape M6.3 fourth wave / 2026-05-24] STMSummarizer init helper. 行为不变.
        self._init_stm_summarizer()

        # [Reshape M6.3 fourth wave / 2026-05-24] ReplyPreFlight init helper. 行为不变.
        self._init_reply_preflight()

        # [Reshape M6.3 fifth wave / 2026-05-24] SirRequestReflector init helper. 行为不变.
        self._init_sir_request_reflector()

        # [Reshape M6.3 fifth wave / 2026-05-24] CompanionRhythmReflector init helper. 行为不变.
        self._init_companion_rhythm_reflector()

        # [Reshape M6.3 fifth wave / 2026-05-24] InsideJokeReflector init helper. 行为不变.
        self._init_inside_joke_reflector()

        # [Reshape M6.3 fifth wave / 2026-05-24] SleepPatternReflector init helper. 行为不变.
        self._init_sleep_pattern_reflector()

        # [Reshape M6.3 fifth wave / 2026-05-24] DirectiveEvaluator init helper. 行为不变.
        self._init_directive_evaluator()

        # [Reshape M6.3 fifth wave / 2026-05-24] PromiseExecutor init helper. 行为不变.
        self._init_promise_executor()

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

        if len(summary_lower) > 100:  # 🩹 Sir 2026-05-28 16:46: summary 可能 None (SQL NULL), 用 already-None-safe summary_lower
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

    # ========================================================================
    # 🆕 [Reshape M6.1 / 2026-05-24] _assemble_prompt 子函数化 — 渐进抽 helper.
    # 目标: 让 _assemble_prompt 主方法变成 dispatch, 各 block 渲染抽到独立 method.
    # M6.4 真 class split 时这些 _build_xxx 会迁到 PromptAssembler class.
    # ========================================================================

    def _build_unified_memory_block(self, user_input: str,
                                      _allow_full: bool, _skip_heavy: bool) -> str:
        """[M6.1] 抽自 _assemble_prompt — UNIFIED MEMORY block 渲染.
        从 memory_gateway (Hub) 拿跨源 recall. 行为与原嵌入代码一致.
        """
        if not (hasattr(self, 'memory_gateway') and _allow_full and not _skip_heavy):
            return ""
        _t = time.time()
        # [Reshape M2.B] hub.to_prompt_block 需显式 nerve (hub 是全局单例);
        # 老 UnifiedMemoryGateway 是 instance-bound, hub 不绑. signature 兼容.
        try:
            block = self.memory_gateway.to_prompt_block(
                user_input, top_k=3, nerve=self)
        except TypeError:
            # 老 UnifiedMemoryGateway 没 nerve 参数 fallback (M5+ 删 stub 后可 remove)
            block = self.memory_gateway.to_prompt_block(user_input, top_k=3)
        self._asm_stage_t['memory_gateway'] = (time.time() - _t) * 1000
        return block

    def _build_skill_tree_block(self, _allow_full: bool, _skip_heavy: bool) -> str:
        """[M6.1] 抽自 _assemble_prompt — SkillTree summary 渲染."""
        if not (hasattr(self, 'skill_tree') and _allow_full and not _skip_heavy):
            return ""
        _t = time.time()
        block = self.skill_tree.get_skill_summary_for_prompt()
        self._asm_stage_t['skill_tree'] = (time.time() - _t) * 1000
        return block

    def _build_anticipator_block(self, _skip_heavy: bool) -> str:
        """[M6.1] 抽自 _assemble_prompt — Anticipator 预载 context 渲染."""
        if (not hasattr(self, 'prompt_center') or self.prompt_center is None
                or self.prompt_center.anticipator is None or _skip_heavy):
            return ""
        _t = time.time()
        block = self.prompt_center.anticipator.get_preloaded_context()
        self._asm_stage_t['anticipator'] = (time.time() - _t) * 1000
        return block

    def _build_profile_block_and_cache(self) -> str:
        """[M6.1 / 2026-05-24] 抽自 _assemble_prompt — ProfileCard.to_prompt_block.
        🩹 [P0+20-β.1.21 / 2026-05-16] 本轮缓存避免 4 次重复构造.
        副作用: 设 self._pc_block_cached lambda 让字符串模板的 caller 用.
        """
        _t = time.time()
        block_value = self.profile_card.to_prompt_block()
        self._asm_stage_t['profile_block'] = (time.time() - _t) * 1000
        # 暴露给本类方法 + 字符串模板（_pc_block_cached 调用方）
        self._pc_block_cached = lambda: block_value
        return block_value

    def _refresh_habit_clock_from_probe(self) -> None:
        """[M6.1] 抽自 _assemble_prompt — habit_clock 更新 (无返值, 仅副作用)."""
        _t = time.time()
        self.habit_clock.update_from_probe()
        self._asm_stage_t['habit_clock_update'] = (time.time() - _t) * 1000

    def _build_context_router_str(self, current_hour: int) -> str:
        """[M6.1] 抽自 _assemble_prompt — ContextRouter.assemble(hour) 渲染."""
        _t = time.time()
        result = self.context_router.assemble(current_hour)
        self._asm_stage_t['context_router'] = (time.time() - _t) * 1000
        return result

    def _assemble_short_chat_prompt(
        self, core_persona: str, user_input: str, stm_context: str,
        current_time: str, current_hour: int, ledger_data: dict,
        sensor_state_block: str, system_alert_text: str,
        yesterday_block: str, open_threads_block: str,
        project_block: str, available_skills_block: str,
        how_to_respond: str, time_persona: str, context_str: str,
        pc_block_value: str, correction_context: str,
        style_adjustment: str, ledger_str: str,
    ) -> str:
        """[Reshape M6.2 second wave / 2026-05-24] SHORT_CHAT tier 抽 helper.

        [R6/Tier] SHORT_CHAT 中档: 核心人设 + STM + ledger + event_bus.
        不带 LTM/skill_tree/anticipator. 主脑 ≤ 20 词 reply.

        🆕 [P5-fix59] PromptBuilder 主路径 + 老 f-string fallback.
        """
        # event_bus 快速渲染 (只取 240s 内事件, 把 prompt 控制到中等体积)
        _short_bus = ""
        try:
            bus = getattr(self, 'event_bus', None)
            if bus is not None:
                _short_bus = bus.to_prompt_block(max_chars=350, within_seconds=240.0)
        except Exception:
            _short_bus = ""
        # [R7-α/AttentionContext] SHORT_CHAT 也带 attention
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
        # [R7-α/WorkingMemoryFeed] SHORT_CHAT 也带工作台事件
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
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🎭 [Tone] {_t_id}  (hour={current_hour}, tier=SHORT_CHAT)")
                except Exception:
                    pass
        except Exception:
            pass

        # [P0+18-a.3] PROMISE_PROTOCOL mini directive
        _short_promise_mini = ""
        try:
            from jarvis_skill_registry import PROMISE_PROTOCOL_DIRECTIVE_MINI
            _short_promise_mini = PROMISE_PROTOCOL_DIRECTIVE_MINI
        except Exception:
            _short_promise_mini = ""

        # [P0+18-a.16] TOOL HONESTY mini
        _short_tool_honesty = ""
        try:
            from jarvis_skill_registry import TOOL_HONESTY_DIRECTIVE_MINI
            _short_tool_honesty = TOOL_HONESTY_DIRECTIVE_MINI
        except Exception:
            _short_tool_honesty = ""

        # [P0+18-b.8] FUZZY CANDIDATES POLICY
        _short_fuzzy_policy = ""
        try:
            from jarvis_fuzzy_resolver import FUZZY_CANDIDATES_POLICY
            _short_fuzzy_policy = FUZZY_CANDIDATES_POLICY
        except Exception:
            _short_fuzzy_policy = ""

        # [P0+18-a.3] ACTIVE PLAN block
        _short_active_plan = ""
        try:
            pl = getattr(self, 'plan_ledger', None)
            if pl is not None:
                _short_active_plan = pl.to_prompt_block(max_chars=400)
        except Exception:
            _short_active_plan = ""

        # 🆕 [P5-fix59 / 2026-05-23 16:13] PromptBuilder 主路径
        try:
            from jarvis_prompt_builder import PromptBuilder, BlockSpec
            sb = PromptBuilder(tier='SHORT_CHAT')
            if yesterday_block:
                sb.register(BlockSpec(
                    id='yesterday', content=yesterday_block,
                    tiers=['SHORT_CHAT'], salience=0.55))
            if stm_context:
                sb.register(BlockSpec(
                    id='stm', content=f"=== WHAT JUST HAPPENED ===\n{stm_context}",
                    tiers=['SHORT_CHAT'], hint='stm:turn_<id>', salience=0.75))
            if open_threads_block:
                sb.register(BlockSpec(
                    id='open_threads', content=open_threads_block,
                    tiers=['SHORT_CHAT'], salience=0.60))
            if project_block:
                sb.register(BlockSpec(
                    id='project', content=project_block,
                    tiers=['SHORT_CHAT'], salience=0.55))
            if available_skills_block:
                sb.register(BlockSpec(
                    id='skills', content=available_skills_block,
                    tiers=['SHORT_CHAT'], salience=0.50))
            if _short_tool_honesty:
                sb.register(BlockSpec(
                    id='tool_honesty', content=_short_tool_honesty,
                    tiers=['SHORT_CHAT'], salience=0.80))
            if _short_fuzzy_policy:
                sb.register(BlockSpec(
                    id='fuzzy_policy', content=_short_fuzzy_policy,
                    tiers=['SHORT_CHAT'], salience=0.65))
            if _short_promise_mini:
                sb.register(BlockSpec(
                    id='promise_mini', content=_short_promise_mini,
                    tiers=['SHORT_CHAT'], salience=0.85))
            if _short_active_plan:
                sb.register(BlockSpec(
                    id='active_plan', content=_short_active_plan,
                    tiers=['SHORT_CHAT'], salience=0.75))
            if _short_bus:
                sb.register(BlockSpec(
                    id='event_bus', content=_short_bus,
                    tiers=['SHORT_CHAT'], hint='swm:<etype>', salience=0.75))
            if _short_attn:
                sb.register(BlockSpec(
                    id='attention', content=_short_attn,
                    tiers=['SHORT_CHAT'], salience=0.70))
            if _short_feed:
                sb.register(BlockSpec(
                    id='working_feed', content=_short_feed,
                    tiers=['SHORT_CHAT'], salience=0.75))
            if _short_tone:
                sb.register(BlockSpec(
                    id='tone', content=_short_tone,
                    tiers=['SHORT_CHAT'], salience=0.55))
            if how_to_respond:
                sb.register(BlockSpec(
                    id='how_to_respond', content=how_to_respond,
                    tiers=['SHORT_CHAT'], salience=0.85))
            sb.register(BlockSpec(
                id='time_persona',
                content=f"=== TIME CONTEXT ===\n{time_persona}",
                tiers=['SHORT_CHAT'], salience=0.65))
            if context_str:
                sb.register(BlockSpec(
                    id='context', content=context_str,
                    tiers=['SHORT_CHAT'], salience=0.65))
            if pc_block_value:
                sb.register(BlockSpec(
                    id='profile_card', content=pc_block_value,
                    tiers=['SHORT_CHAT'], hint='profile:<field>', salience=0.70))
            if correction_context:
                sb.register(BlockSpec(
                    id='correction', content=correction_context,
                    tiers=['SHORT_CHAT'], salience=0.80))
            if style_adjustment:
                sb.register(BlockSpec(
                    id='style', content=style_adjustment,
                    tiers=['SHORT_CHAT'], salience=0.55))
            if ledger_str and ledger_str != "No status data":
                sb.register(BlockSpec(
                    id='ledger',
                    content=f"=== REAL-TIME STATE ===\n{ledger_str}",
                    tiers=['SHORT_CHAT'], hint='ledger:<field>', salience=0.70))
            sb.register(BlockSpec(
                id='clock', content=f"[SYSTEM CLOCK]: {current_time}",
                tiers=['SHORT_CHAT'], salience=0.85))
            if sensor_state_block:
                sb.register(BlockSpec(
                    id='sensor', content=sensor_state_block,
                    tiers=['SHORT_CHAT'], hint='sensor:<field>',
                    salience=0.85))
            _l2 = getattr(self, '_l2_injected_block', '') or ''
            if _l2:
                sb.register(BlockSpec(
                    id='l2', content=_l2,
                    tiers=['SHORT_CHAT'], hint='l2:<directive_id>',
                    salience=0.65))
            return sb.compose(
                persona=core_persona,
                user_input=user_input,
                system_alert=system_alert_text,
                include_meta_hint=True,
            )
        except Exception:
            # fallback 老 f-string
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
{pc_block_value}
{correction_context}
{style_adjustment}

=== REAL-TIME STATE ===
{ledger_str}

[SYSTEM CLOCK]: {current_time}
{sensor_state_block}
{getattr(self, '_l2_injected_block', '')}

User: {user_input}
{system_alert_text}
"""

    def _assemble_factual_recall_prompt(
        self, core_persona: str, user_input: str, stm_context: str,
        current_time: str, current_hour: int, ledger_data: dict,
        sensor_state_block: str, system_alert_text: str,
        yesterday_block: str, open_threads_block: str,
        project_block: str, available_skills_block: str,
    ) -> str:
        """[Reshape M6.2 second wave / 2026-05-24] FACTUAL_RECALL tier 抽 helper.

        [R7-β1] 近期事实查询: 答案大概率已在 working_feed / event_bus / STM /
        attention 里. 绝对禁止调用工具, 目标 TTFT < 2s.

        🆕 [P5-fix57] PromptBuilder 主路径 + 老 f-string fallback.
        """
        _fr_working = ""
        try:
            feed = getattr(self, 'working_feed', None)
            if feed is not None:
                # FACTUAL_RECALL 要把 working_feed 拉得更宽 (1 小时 + 较多事件 + 较多字符)
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
        # STM 拉宽到 6 条 (FACTUAL_RECALL 经常要回看刚说过的话)
        short_stm = stm_context
        if short_stm and len(short_stm) > 1200:
            short_stm = "..." + short_stm[-1200:]
        # [R7-β3] Tone Directive (FACTUAL_RECALL 也带 tone 让回答有 persona 味)
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
        # 🆕 [P5-fix57 / 2026-05-23 16:05] PromptBuilder 主路径
        try:
            from jarvis_prompt_builder import PromptBuilder, BlockSpec
            _how_to_respond_fr = (
                "=== HOW TO RESPOND (FACTUAL_RECALL — 近期事实查询) ===\n"
                "Sir is asking about something that JUST happened or is in your immediate context.\n"
                "DO NOT call any tool. The answer is already in the context blocks below — find it and answer directly.\n\n"
                "Priority order to find the answer:\n"
                "1. WORKING MEMORY (clipboard / terminal command / file saved / window switch history)\n"
                "2. WHAT JUST HAPPENED (STM)\n"
                "3. CONVERSATION STATE (event_bus — recent breakthroughs / callbacks / commitments)\n"
                "4. ATTENTION (current window / cursor)\n"
                "5. SENSOR STATE (current_window_stay_s for 'how long am I on X')\n\n"
                "Reply in ONE sentence. Quote the actual content if relevant (e.g. for clipboard contents,\n"
                "quote the first 60 chars). Append `---ZH---` and Chinese at the end.\n\n"
                "If none of the above sources have the answer, say so honestly:\n"
                "\"I don't have that in my immediate memory, Sir — could you give me a hint?\"\n"
                "Do NOT fabricate. Do NOT call tools — even if a tool *might* know the answer, the user\n"
                "expects an instant reply from your recent memory, not a tool round-trip."
            )
            fb = PromptBuilder(tier='FACTUAL_RECALL')
            if _fr_tone:
                fb.register(BlockSpec(
                    id='tone', content=_fr_tone,
                    tiers=['FACTUAL_RECALL'], salience=0.55))
            fb.register(BlockSpec(
                id='how_to_respond', content=_how_to_respond_fr,
                tiers=['FACTUAL_RECALL'], salience=0.95))
            if yesterday_block:
                fb.register(BlockSpec(
                    id='yesterday', content=yesterday_block,
                    tiers=['FACTUAL_RECALL'], salience=0.55))
            if short_stm:
                fb.register(BlockSpec(
                    id='stm', content=f"=== WHAT JUST HAPPENED ===\n{short_stm}",
                    tiers=['FACTUAL_RECALL'], hint='stm:turn_<id>', salience=0.80))
            if open_threads_block:
                fb.register(BlockSpec(
                    id='open_threads', content=open_threads_block,
                    tiers=['FACTUAL_RECALL'], salience=0.60))
            if project_block:
                fb.register(BlockSpec(
                    id='project', content=project_block,
                    tiers=['FACTUAL_RECALL'], salience=0.55))
            if available_skills_block:
                fb.register(BlockSpec(
                    id='skills', content=available_skills_block,
                    tiers=['FACTUAL_RECALL'], salience=0.50))
            if _fr_bus:
                fb.register(BlockSpec(
                    id='event_bus', content=_fr_bus,
                    tiers=['FACTUAL_RECALL'], hint='swm:<etype>', salience=0.75))
            if _fr_attention:
                fb.register(BlockSpec(
                    id='attention', content=_fr_attention,
                    tiers=['FACTUAL_RECALL'], salience=0.70))
            if _fr_working:
                fb.register(BlockSpec(
                    id='working_feed', content=_fr_working,
                    tiers=['FACTUAL_RECALL'], salience=0.80))
            fb.register(BlockSpec(
                id='clock', content=f"[SYSTEM CLOCK]: {current_time}",
                tiers=['FACTUAL_RECALL'], salience=0.85))
            if sensor_state_block:
                fb.register(BlockSpec(
                    id='sensor', content=sensor_state_block,
                    tiers=['FACTUAL_RECALL'], hint='sensor:<field>',
                    salience=0.90))  # FACTUAL_RECALL 高优
            _l2 = getattr(self, '_l2_injected_block', '') or ''
            if _l2:
                fb.register(BlockSpec(
                    id='l2', content=_l2,
                    tiers=['FACTUAL_RECALL'], hint='l2:<directive_id>',
                    salience=0.65))
            return fb.compose(
                persona=core_persona,
                user_input=user_input,
                system_alert=system_alert_text,
                include_meta_hint=True,  # FACTUAL_RECALL 允许 META 自检
            )
        except Exception:
            # fallback 老 f-string
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
{sensor_state_block}
{getattr(self, '_l2_injected_block', '')}

User: {user_input}
{system_alert_text}
"""

    def _assemble_wake_only_prompt(self, core_persona: str, user_input: str,
                                      stm_context: str, current_time: str,
                                      sensor_state_block: str,
                                      system_alert_text: str) -> str:
        """[Reshape M6.2 / 2026-05-24] 抽自 _assemble_prompt — WAKE_ONLY tier.

        [R6/Tier] WAKE_ONLY 短路返回: 只塞核心人设 + 最近 3 条 STM + 一句指令.
        目标 prompt 体积 ≤ 1.5K, TTFT 期望降到 1s 以内.

        🆕 [P5-fix55 / 2026-05-23 15:55] PromptBuilder 主路径 + 老 string template fallback.
        """
        try:
            from jarvis_prompt_builder import PromptBuilder, BlockSpec
            # STM 只看最近 3 条对话 (更短)
            short_stm = stm_context
            if short_stm and len(short_stm) > 500:
                short_stm = "..." + short_stm[-500:]
            _how_to_respond = (
                "=== HOW TO RESPOND (WAKE_ONLY) ===\n"
                "Sir just called your name. Reply in UNDER 6 WORDS.\n"
                "- If recent STM shows ongoing conversation, acknowledge briefly: \"Yes, Sir?\" / \"I'm here.\"\n"
                "- If no recent context: just \"Sir?\" / \"At your service.\"\n"
                "- NEVER fabricate. NEVER ask questions.\n"
                "- Append `---ZH---` and a 1-3 character Chinese acknowledgment at the very end."
            )
            wb = PromptBuilder(tier='WAKE_ONLY')
            wb.register(BlockSpec(
                id='how_to_respond', content=_how_to_respond,
                tiers=['WAKE_ONLY'], salience=0.95))
            if short_stm:
                wb.register(BlockSpec(
                    id='stm', content=f"=== RECENT TURNS ===\n{short_stm}",
                    tiers=['WAKE_ONLY'], hint='stm:turn_<id>', salience=0.70))
            wb.register(BlockSpec(
                id='clock', content=f"[SYSTEM CLOCK]: {current_time}",
                tiers=['WAKE_ONLY'], salience=0.85))
            if sensor_state_block:
                wb.register(BlockSpec(
                    id='sensor', content=sensor_state_block,
                    tiers=['WAKE_ONLY'], hint='sensor:<field>', salience=0.85))
            _l2 = getattr(self, '_l2_injected_block', '') or ''
            if _l2:
                wb.register(BlockSpec(
                    id='l2', content=_l2,
                    tiers=['WAKE_ONLY'], hint='l2:<directive_id>', salience=0.65))
            # WAKE_ONLY 极简 — META cheat sheet 也省了 (主脑 ≤ 6 词 reply, 不用 META 自检)
            return wb.compose(
                persona=core_persona,
                user_input=user_input,
                system_alert=system_alert_text,
                include_meta_hint=False,
            )
        except Exception:
            # builder 失败 → fallback 老路径 (保证不破现有行为)
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
{sensor_state_block}
{getattr(self, '_l2_injected_block', '')}

User: {user_input}
{system_alert_text}
"""

    # 🆕 [Reshape M3.G 真删 / 2026-05-24 17:00] _init_3_brain_legacy + 3 attr 删.
    # SWM deprecated_3_brain_invoked event = 0 1 周 → 真删. 老测试用例已迁到验
    # AttributeError (test_m6_3_second_wave.py / test_m6_5_3_run_deprecation.py).

    def _init_stm_persist(self) -> None:
        """[Reshape M6.3 second wave / 2026-05-24] 抽自 __init__ — STM 持久化.

        [β.4.10 / 2026-05-19] STM 持久化 — Sir 重启不忘上轮对话.
        治本: short_term_memory 是 RAM list, 重启清空 → Sir 跟 Jarvis 聊涌现后
        为找 wake BUG 重启 Jarvis, Jarvis 不记得刚才的话题 (准则 4 "懂我" 退步).
        设计:
          1. 启动时 _restore_stm_from_disk() 读 jsonl 最近 N 条恢复
          2. 后台 daemon 每 30s _persist_stm_to_disk() atomic dump 整 STM
          3. atexit 强制 dump 1 次 (Sir Ctrl+C 不丢)
        """
        self._stm_persist_path = os.path.join('memory_pool', 'stm_recent.jsonl')
        self._stm_persist_max = 50  # 最近 50 条 (= ~25 对来回, 覆盖 1 小时聊天)
        self._stm_persist_interval_s = 30.0
        self._stm_dirty = False
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

    def _init_event_bus_swm(self) -> None:
        """[Reshape M6.3 second wave / 2026-05-24] 抽自 __init__ — ConversationEventBus + 全局 SWM 注册.

        [R6/B1] 对话事件总线 — 替代散落的 pending_event/commitment/soft_focus_reason 等字段.
        gatekeeper / SmartNudge / Conductor / focus_lock 都往这里 publish; prompt assembler 读.

        [β.5.0-A / 2026-05-19] 注册全局 SWM 让远端模块 (PhysicalEnvProbe / OfferGuard /
        ProactiveCare / Reflectors) publish 不需 self.jarvis ref.
        """
        try:
            from jarvis_utils import ConversationEventBus
            self.event_bus = ConversationEventBus()
            try:
                ConversationEventBus.register_global(self.event_bus)
            except Exception:
                pass
        except Exception:
            self.event_bus = None
        # [R7-α/B1] event_bus 准备好后, 回填到 state 让状态切换也能 publish
        if self.state is not None and self.event_bus is not None:
            self.state.set_event_bus(self.event_bus)

    def _init_working_feed(self) -> None:
        """[Reshape M6.3 second wave / 2026-05-24] 抽自 __init__ — WorkingFeed + 2 watcher.

        [R7-α/WorkingMemoryFeed] 会话级环境事件流: 剪贴板 / PowerShell history.
        与 event_bus 分开: event_bus 是对话事件 (TTL 短 / 优先级高), feed 是工作台
        环境事件 (TTL 30min / 低优先级 / 帮 LLM 答"我刚复制的是什么"/"我刚跑的那个命令").
        """
        try:
            from jarvis_utils import (
                WorkingMemoryFeed, ClipboardWatcher, PSHistoryWatcher,
                is_recent_jarvis_echo,
            )
            self.working_feed = WorkingMemoryFeed(max_events=80, ttl_seconds=1800.0)
            # 剪贴板 watcher: 跳过 Jarvis 自己刚塞进去的内容 (避免自循环)
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

    def _init_plan_ledger(self) -> None:
        """[Reshape M6.3 second wave / 2026-05-24] 抽自 __init__ — PlanLedger.

        [R7-α/PlanLedger] 任务计划账本: 5 态状态机 + JSON 持久化.
        α4 阶段只做雏形: 能创建 / 能查询 / 能持久化 / 能 publish.
        [轴 3-L3.2 / 2026-05-15] 接 PromiseExecutor 后真能跑步骤 + 反推 + 重试.
        """
        try:
            from jarvis_utils import PlanLedger
            self.plan_ledger = PlanLedger(
                persist_path=os.path.join('memory_pool', 'plans.json'),
                event_bus=self.event_bus,
                max_active=3,
                autosave=True,
            )
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

    def _init_skill_registry_bootstrap(self) -> None:
        """[Reshape M6.3 second wave / 2026-05-24] 抽自 __init__ — SkillRegistry bootstrap.

        [轴 3-L0.3 / 2026-05-15 P0+18-a.1] 启动时 bootstrap SkillRegistry.
        不调这个 → registry 永远空 → AVAILABLE SKILLS prompt 块空 → PromiseExecutor
        即便启动也无 skill 可跑. 130 个 skill 从 l4_hands_pool / l2_eyes_pool 自动入册
        + autosave daemon 每 60s 检查 dirty 落盘到 memory_pool/skill_registry.jsonl.
        """
        try:
            from jarvis_skill_registry import get_registry as _get_reg
            _reg = _get_reg()
            _reg.bootstrap(
                pools_root='.',
                jsonl_path=os.path.join('memory_pool', 'skill_registry.jsonl'),
                enable_autosave=True,
                autosave_interval_s=60,
            )
        except Exception as _e:
            import traceback as _tb
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[SkillRegistry/bootstrap] 初始化失败：{_e}")
                _bg(_tb.format_exc())
            except Exception:
                pass

    def _init_directive_registry(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] DirectiveRegistry decay daemon."""
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

    def _init_self_anchor(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] SelfAnchor — 灵魂工程 Layer 0."""
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

    def _init_concerns_ledger(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] ConcernsLedger — 灵魂工程 Layer 1."""
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

    def _init_daemon_health_monitor(self) -> None:
        """🆕 [HM / Sir 2026-05-25 23:38] DaemonHealthMonitor — 守护层 Layer 6.

        Sir 真意: "我就是想少干点活, 别又给我多一项工作".
        每 6h 自动检 InnerThought + AutoArbiter 4 项健康:
          1. InnerThought thoughts/24h 区间 30-200
          2. InnerThought 5 类分布无一类 > 70%
          3. AutoArbiter calibration 阈值 ≥ 0.55
          4. InnerThought actionable fail rate ≤ 30%
        异常 publish 'daemon_health_warning' SWM (salience 0.75) →
        SOUL inject 进主脑 prompt + dashboard 主面板自动看到红条.
        Sir 真无需跑任何 CLI.
        """
        self.daemon_health_monitor = None
        try:
            from jarvis_daemon_health_monitor import (
                DaemonHealthMonitor, set_default_monitor
            )
            self.daemon_health_monitor = DaemonHealthMonitor(
                central_nerve=self,
            )
            self.daemon_health_monitor.start()
            set_default_monitor(self.daemon_health_monitor)
        except Exception as _hm_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [DaemonHealthMonitor] init fail (非致命): {_hm_e}")
            except Exception:
                pass

    def _init_weekly_reflection_consolidator(self) -> None:
        """🆕 [WRC / Sir 2026-05-25 23:52 真问 "3 也做"] WeeklyReflectionConsolidator — 灵魂工程 Layer 4.5.

        每周日 03:xx fire 一次, 提 7d hippocampus self_reflection event 的
        recurring pattern, propose 到 review queue (memory_pool/long_term_insights.jsonl)
        + publish 'weekly_insight_proposed' SWM 让 Sir dashboard 看 + 一键 accept/reject.
        不直接 mutate sir_profile (准则 7 Sir 元否决).

        启动条件: key_router + hippocampus 可选 (None 时模块自身 silent skip).
        """
        self.weekly_reflection_consolidator = None
        try:
            from jarvis_weekly_reflection_consolidator import (
                WeeklyReflectionConsolidator, set_default_consolidator
            )
            self.weekly_reflection_consolidator = WeeklyReflectionConsolidator(
                key_router=self.key_router,
                central_nerve=self,
            )
            self.weekly_reflection_consolidator.start()
            set_default_consolidator(self.weekly_reflection_consolidator)
        except Exception as _wrc_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [WeeklyReflectionConsolidator] init fail (非致命): {_wrc_e}")
            except Exception:
                pass

    def _init_auto_arbiter(self) -> None:
        """🆕 [AA / Sir 2026-05-25 22:58 自决] AutoArbiterDaemon — 灵魂工程 Layer 2.5.

        tick 30min, 拉 review queues (inside_joke + thread) 自动评估 + 决策.
        低风险 (joke/thread): confidence > per-category threshold → 真 activate/reject.
        中风险 (concern/directive): 全 defer_to_sir, dashboard '🤖 建议' badge.
        Daily reflection 03:xx 看 24h revert_rate 自调 threshold.
        Sir 一键 revert: 反向 active/archived + 标 sir_reverted=True.

        启动条件: relational_state 必须就绪. concerns_ledger 可选.
        """
        self.auto_arbiter_daemon = None
        try:
            from jarvis_auto_arbiter import (
                AutoArbiterDaemon, set_default_daemon
            )
            self.auto_arbiter_daemon = AutoArbiterDaemon(
                key_router=self.key_router,
                relational_state=getattr(self, 'relational_state', None),
                concerns_ledger=getattr(self, 'concerns_ledger', None),
                central_nerve=self,
            )
            self.auto_arbiter_daemon.start()
            set_default_daemon(self.auto_arbiter_daemon)
            try:
                from jarvis_utils import bg_log as _aa_bg
                _aa_bg(
                    f"🤖 [AutoArbiter] daemon active "
                    f"(灵魂工程 Layer 2.5 — 30min tick, 2 类自决 + 2 类建议, "
                    f"Daily 03:xx self-calibrate)"
                )
            except Exception:
                pass
        except Exception as _aa_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [AutoArbiter] init fail (非致命): {_aa_e}")
            except Exception:
                pass

    def _init_inner_thought_daemon(self) -> None:
        """🆕 [P1 / Sir 2026-05-25 22:10 数字生命基础] InnerThoughtDaemon — 灵魂工程 Layer 1.5.

        Adaptive tick (60s active / 3min afk_short / 10min afk_deep / 30min sleep).
        Flash-Lite call (caller='inner_thought' → P2 LOW priority 自动限速 + fallback).
        5 类思考 (A obs / B self-reflect / C concern-evo / D proactive-seed / E relational).
        4 actionable (none / update_concern_severity / publish_swm / suggest_inside_joke).
        SOUL inject top 3 by salience in last 24h → 主脑下次 turn prompt.

        启动条件: key_router 必须就绪 (调 LLM 用). concerns_ledger / relational_state
        可选 (None 也 work, 只是 C/E 类 actionable 无效).
        """
        self.inner_thought_daemon = None
        try:
            from jarvis_inner_thought_daemon import (
                InnerThoughtDaemon, set_default_daemon
            )
            self.inner_thought_daemon = InnerThoughtDaemon(
                key_router=self.key_router,
                concerns_ledger=getattr(self, 'concerns_ledger', None),
                relational_state=getattr(self, 'relational_state', None),
                central_nerve=self,
            )
            self.inner_thought_daemon.start()
            set_default_daemon(self.inner_thought_daemon)
            try:
                from jarvis_utils import bg_log as _it_bg
                _it_bg(
                    f"💭 [InnerThought] daemon active (灵魂工程 Layer 1.5 — "
                    f"adaptive tick 60s/3min/10min/30min, 5 类思考 + 4 actionable)"
                )
            except Exception:
                pass
        except Exception as _it_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [InnerThought] init fail (非致命): {_it_e}")
            except Exception:
                pass

    def _init_relational_weaver(self) -> None:
        """🕸️ [体-P5 / 2026-05-31] 织网者 Weaver — 体(Body)的维护器官 (和思考脑同级 peer).

        后台慢工 (默认首轮延迟 90s, 之后每 600s 一轮): harvest 节点 (threads/concerns/
        jokes/protocols) → 几何 embed 边 (cosine 相似度, 带向量缓存) → 周期 decay + prune.
        详 docs/JARVIS_TRINITY_ARCHITECTURE.md §4. 失败非致命 (后台慢工, 下轮再试).

        复用 nerve 现有 hippocampus 向量器 (避免第二个 DB 连接); 不可用则 Weaver
        内部 lazy 自建 (default_embed_fn).
        """
        self.relational_weaver = None
        try:
            from jarvis_relational_weaver import RelationalWeaver
            hipp = getattr(self, 'hippocampus', None)
            embed_fn = None
            if hipp is not None and hasattr(hipp, '_embed_with_rotation'):
                def embed_fn(texts, _h=hipp):
                    try:
                        resp, _ = _h._embed_with_rotation(contents=list(texts))
                        embs = list(getattr(resp, 'embeddings', []) or [])
                        return [list(embs[i].values) if i < len(embs) else None
                                for i in range(len(texts))]
                    except Exception:
                        return [None] * len(texts)
            self.relational_weaver = RelationalWeaver(embed_fn=embed_fn)
            self.relational_weaver.start()
            try:
                from jarvis_utils import bg_log as _w_bg
                _w_bg("🕸️ [Weaver] 织网者启动 (体/Body 维护器官 — 后台几何织网 + decay/prune)")
            except Exception:
                pass
            # 🆕 [body-diff-P1 耦合护栏 层1: 启动期 loud 早警 / Sir 2026-06-06]
            # 在跑第一个 turn 之前校验 lens flag 耦合: inject=1 但 grounded_only=0 =
            # 裸 naive lens (已证投 95.6% 假焊) → 启动期 loud (print+bg_log WARNING),
            # 不靠事后翻日志。非致命 (不 raise), 热路径 build_lens_block 层2 安全网兜底。
            try:
                from jarvis_relational_lens import validate_lens_coupling
                validate_lens_coupling()
            except Exception:
                pass
            # 🆕 [body-diff-P2 耦合护栏 层1: 启动期 loud 早警 / Sir 2026-06-06]
            # 对称 lens: 校验 energy_grounded_only 配置自洽 (flag=1 时白名单须非空且全接地
            # prov)。防有人把白名单清空/混入 embed = 势能数假焊 = 洗白态借配置复活。非致命。
            try:
                from jarvis_relational_weaver import validate_energy_coupling
                validate_energy_coupling()
            except Exception:
                pass
        except Exception as _w_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [Weaver] init fail (非致命): {_w_e}")
            except Exception:
                pass

    def _init_stand_down(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] Stand Down hotkey daemon (Ctrl+Alt+J)."""
        try:
            import jarvis_stand_down as _sd
            _sd.start_hotkey_daemon()
            _initial_state = _sd.get_state()
            try:
                from jarvis_utils import bg_log as _sd_bg
                if _initial_state.is_active_now():
                    _eta_min = int(_initial_state.remaining_s() / 60)
                    _sd_bg(f"🌙 [StandDown] 启动时仍 active reason={_initial_state.reason} "
                              f"(remain {_eta_min}min) — 上次未 wake. Hotkey Ctrl+Alt+J 切换.")
                else:
                    _sd_bg("🌙 [StandDown] hotkey daemon 已启动 (Ctrl+Alt+J 切换)")
            except Exception:
                pass
        except Exception as _sd_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[StandDown] hotkey daemon 启动失败 (非致命): {_sd_e}")
            except Exception:
                pass

    def _init_relational_state(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] RelationalState — 灵魂工程 Layer 2."""
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

    def _init_attention_layer3(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] Attention Allocation — 灵魂工程 Layer 3.

        不是单例 / 没有 store — helper 函数 build_attention_block(), 每次
        _assemble_prompt 调用时基于 (concerns_ledger + user_input) 动态构造.
        """
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

    def _init_soul_evaluator(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] SoulEvaluator — 灵魂工程 Layer 5."""
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

    def _init_reflectors(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] Reflectors — 灵魂工程 Layer 4.

        ConcernsReflector (每轮对话末尾启发式 keyword) + WeeklyReflector
        (daemon 7d LLM 反思 propose 新 concerns 进 review).
        """
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

    def _init_claim_stats_dumper(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] ClaimStatsDumper — 60s tick dump claim_stats.json."""
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

    def _init_integrity_reflector(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] IntegrityReflector L7 LLM-propose daemon.

        7d audit 反思 → propose 进 review queue. 触发: weekly (3d 兜底) 或
        audit ≥ 50 + Sir idle > 4h. 准则 7 Sir 元否决: 默认 state=review.
        """
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

    def _init_screen_tease_reflector(self) -> None:
        """[Reshape M6.3 third wave / 2026-05-24] ScreenTeaseReflector L7 vocab daemon.

        24h 1 跑 LLM propose 新 category 进 review_queue. 准则 7 Sir 元否决.
        """
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

    def _init_struggle_reflector(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] StruggleReflector L7 vocab daemon (β.5.35-D)."""
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

    def _init_intent_resolver(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] IntentResolver + TOOL_REGISTRY 挂载 (β.5.44-CD).

        Sir 18:55 真理重构 — 7 个 module publish-only, IntentResolver 集中 LLM judge
        决定调 tool. 主脑看 [INTENT RESOLVED] block 知道哪个 tool 真成功.
        """
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
                    # 🩹 [P1-Gap8] __wrapped__ 让 inspect.signature 能找回真 function
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

    def _init_tom_reflector(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] ToMReflector + SirMentalState (P5-ToM, Layer 6).

        Sir 22:10 真理: lifetime anchor 不是 commitment, 不要 nudge.
        Layer 6 ToM 让主脑读 Sir 言外之意 (surface/deeper/unspoken need 3 层).
        """
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

    def _init_integrity_watcher(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] IntegrityWatcher L4.5 Active Verify+Retry.

        Sir 14:11 真意 — wachter 主动 verify + 递归 retry, 真做不到 handoff Sir 手动.
        监督 Jarvis 内部能力 8 类 (reminder/commitment/promise/memory/milestone/
        profile/concern/relational). 不监督 tool.
        """
        self.integrity_watcher = None
        try:
            from jarvis_integrity_watcher import (
                IntegrityWatcher, attach_llm_judge_key_router
            )
            self.integrity_watcher = IntegrityWatcher(nerve=self)
            # 注入 key_router 给 Layer 3 LLM judge
            try:
                attach_llm_judge_key_router(self.key_router)
            except Exception:
                pass
            self.integrity_watcher.start()
        except Exception as _iw_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[IntegrityWatcher] 初始化失败（非致命）：{_iw_e}")
            except Exception:
                pass

    def _init_screen_vision_engine(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] ScreenVisionEngine (P5-Gap3).

        屏幕 vision 结构化描述. env flag JARVIS_SCREEN_VISION=1 启用. 不阻 TTFT.
        """
        self.screen_vision_engine = None
        try:
            from jarvis_screen_vision import init_default_engine as _init_vision
            self.screen_vision_engine = _init_vision(key_router=self.key_router)
            self.screen_vision_engine.start()
        except Exception as _sv_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[ScreenVision] 初始化失败（非致命）：{_sv_e}")
            except Exception:
                pass

    def _init_reject_learner(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] RejectLearner L8 闭环演化 (Gap 5).

        Sir dashboard 评 reply 👎 → LLM judge propose directive 改写 → review queue.
        daemon 4h 一周期, config 在 memory_pool/reject_learner_config.json.
        """
        self.reject_learner = None
        try:
            from jarvis_reject_learner import (
                RejectLearner, register_learner, is_enabled as _rl_enabled
            )
            self.reject_learner = RejectLearner(key_router=self.key_router)
            register_learner(self.reject_learner)
            if _rl_enabled():
                self.reject_learner.start_daemon()
                try:
                    from jarvis_utils import bg_log as _rl_bg
                    _rl_bg("📊 [RejectLearner] L8 闭环演化 daemon 已启动 (Gap 5)")
                except Exception:
                    pass
        except Exception as _rl_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[RejectLearner] 初始化失败（非致命）：{_rl_e}")
            except Exception:
                pass

    def _init_stm_summarizer(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] STMSummarizer (Gap-Z1 / β.5.46-fix4).

        post-stream async LLM 压缩 STM 自身 reply, 下轮主脑看 compressed brief.
        async, 不阻 TTFT. config 在 memory_pool/stm_summarize_config.json.
        """
        self.stm_summarizer = None
        try:
            from jarvis_stm_summarizer import STMSummarizer, register_summarizer
            self.stm_summarizer = STMSummarizer(key_router=self.key_router)
            register_summarizer(self.stm_summarizer)
            try:
                from jarvis_utils import bg_log as _ssum_bg
                from jarvis_stm_summarizer import is_enabled as _ssum_enabled
                _en = _ssum_enabled()
                _ssum_bg(
                    f"📝 [STMSummarizer] {'enabled (default ON, Gap-Z1 / β.5.46-fix4)' if _en else 'registered (env JARVIS_STM_SUMMARIZE=0, dormant)'}"
                )
            except Exception:
                pass
        except Exception as _ssum_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[STMSummarizer] 初始化失败（非致命）：{_ssum_e}")
            except Exception:
                pass

    def _init_reply_preflight(self) -> None:
        """[Reshape M6.3 fourth wave / 2026-05-24] ReplyPreFlight (P5-fixD, default ON).

        Reply 后置审计 + SWM publish → 主脑下轮 [PREFLIGHT FEEDBACK] 看自纠.
        Sir 关掉设 JARVIS_PREFLIGHT=0.
        """
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

    def _init_sir_request_reflector(self) -> None:
        """[Reshape M6.3 fifth wave / 2026-05-24] SirRequestReflector L7 daemon (β.5.43-fix3-㋭).

        Sir 18:49 痛点: Sir "下次卡住主动提醒我", Jarvis 答应了 但实际没机制兑现.
        60s tick, LLM judge STM 是否要求 long-watch X → propose concern 进 review.
        """
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

    def _init_companion_rhythm_reflector(self) -> None:
        """[Reshape M6.3 fifth wave / 2026-05-24] CompanionRhythmReflector L7 (β.5.40-E1).

        每日 03:30 LLM 扫近 7 天 STM 算每 hour nudge-receptive score,
        写 memory_pool/nudge_window_vocab.json. ProactiveCare 看 vocab + publish.
        """
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

    def _init_inside_joke_reflector(self) -> None:
        """[Reshape M6.3 fifth wave / 2026-05-24] InsideJokeReflector L7 (β.5.40-B1).

        每日 03:30 LLM 扫近 7 天 STM, 提取 Sir 重复梗 (≥2 evidence + conf ≥ 0.8)
        propose 到 relational_state.inside_jokes review queue.
        """
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

    def _init_sleep_pattern_reflector(self) -> None:
        """[Reshape M6.3 fifth wave / 2026-05-24] SleepPatternReflector L7 (β.5.39).

        每日 03:00 扫 hippocampus + history 重算 Sir 典型入睡时间.
        """
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

    def _init_directive_evaluator(self) -> None:
        """[Reshape M6.3 fifth wave / 2026-05-24] DirectiveEvaluator (P0+20-β.0.5).

        L2 directive 异步评分链: 走 OpenRouter, 每轮对话完成后异步评 fired directive
        是否真被 LLM 遵守 (yes/no/partial) → 写回 directive.helped.
        """
        self.directive_evaluator = None
        try:
            from jarvis_directive_evaluator import get_default_evaluator as _get_eval
            from jarvis_directives import get_default_registry as _get_dr
            self.directive_evaluator = _get_eval(
                key_router=self.key_router,
                registry=_get_dr(),
            )
        except Exception as _ev_e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"[DirectiveEvaluator] 初始化失败（非致命，评分链跳过）：{_ev_e}")
            except Exception:
                pass

    def _init_promise_executor(self) -> None:
        """[Reshape M6.3 fifth wave / 2026-05-24] PromiseExecutor (轴3-L3.2 + L3.3).

        后台步骤执行器 daemon 每 1s 扫 ledger, 跑 STATE_RUNNING plan 的 next pending step.
        三回调 (fast_call_executor / say_to_sir / skill_registry) 由 main 段延迟注入.
        """
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

    def _build_layer_0_self_anchor_block(self) -> str:
        """[Reshape M6.1 third wave / 2026-05-24] Layer 0: SelfAnchor block.

        🩹 [P0+20-β.2.0] Sir 实测 Jarvis 不理解"这个终端就是你"的指代关系 → 缺持续的"我".
        注入到 core_persona 末尾让 LLM 每次都看到"我是 J.A.R.V.I.S. 的连续主体".
        """
        try:
            if self.self_anchor is not None:
                return self.self_anchor.build_block(max_chars=1700)
        except Exception:
            pass
        return ''

    def _build_layer_1_concerns_block(self, user_input: str) -> str:
        """[Reshape M6.1 third wave / 2026-05-24] Layer 1: Concerns block.

        🆕 [P5-Gap4-followup-fix2] 三 gating 条件:
          (a) Sir 召唤 (vocab keyword) — 真问起来才 surface
          (c) PreFlight 上轮 edit/scrap — Jarvis 真出错保险
          else → silent (不 inject, 主脑不会翻老账)

        副作用: 设 self._soul_concern_inject_reason ('summon'/'preflight_fail'/'silent'/'error')
        给 _build_layer_2_relational_block 用.
        """
        try:
            if self.concerns_ledger is None:
                self._soul_concern_inject_reason = 'silent'
                return ''
            # (a) Sir 召唤检测 (准则 6.5 vocab — memory_pool/concern_summon_vocab.json)
            try:
                from jarvis_concern_summon import is_summoned as _is_summoned
                _summoned = _is_summoned(user_input or '')
            except Exception:
                # Fallback — vocab loader 失败时硬编码兜底
                _ui = (user_input or '').lower()
                _summon_kw = (
                    'any concern', 'what concerns', 'worried about',
                    "what's my progress", 'how am i doing',
                    "what's my status", 'remind me what',
                    '担心啥', '担心什么', '心事', '我关心的', '我担心的',
                    '什么进度', '进度怎么样', '我状态如何',
                    '提醒我啥', '提醒我什么', '啥情况',
                )
                _summoned = any(kw in _ui for kw in _summon_kw)
            # (c) Sir 21:19 保险 — 上轮 PreFlight verdict=edit/scrap → inject 让主脑澄清
            _preflight_failed = False
            try:
                _bus_pf = getattr(self, 'event_bus', None)
                if _bus_pf is not None:
                    _pf_events = _bus_pf.recent_events(
                        within_seconds=300.0,
                        types={'preflight_verdict'},
                    )
                    for _ev in (_pf_events or []):
                        _meta = _ev.get('metadata') or {}
                        if _meta.get('verdict') in ('edit', 'scrap'):
                            _preflight_failed = True
                            break
            except Exception:
                pass
            # 记录触发原因 (诊断 log)
            if _summoned:
                self._soul_concern_inject_reason = 'summon'
            elif _preflight_failed:
                self._soul_concern_inject_reason = 'preflight_fail'
            else:
                self._soul_concern_inject_reason = 'silent'
            if _summoned or _preflight_failed:
                return self.concerns_ledger.to_prompt_block(
                    top_n=3, max_chars=600)
        except Exception:
            self._soul_concern_inject_reason = 'error'
        return ''

    def _build_layer_1b_inner_thoughts_block(
        self, prompt_tier: str = ''
    ) -> str:
        """[DEPRECATED — Sir 2026-05-28 17:20 β.6 Phase 2 治本] Layer 1.5 stub.

        Sir 真意 (17:14): "除了归来招呼和我设置的定时提醒走强制性编码唤醒,
        其他的所有模块都集成到思考链, 把思考链给主脑让主脑演的像他一直存在".

        老路径: 本 method 调 daemon.build_lifetime_block → 主脑 prompt 加段
        是**独立 push**到主脑. β.6 Phase 2 将此功能**聚合**到 Layer 1.6
        (_build_layer_1c_inner_voice_block), voice block 内部按 vocab
        tier_mode 注入 lifetime — 主脑只读 voice block 一处即看到 lifetime
        + thoughts + thinking directive + spotlight 全部"思考链".

        本 stub 永返 '' (不再独立 push lifetime). daemon.build_lifetime_block
        仍是 source of truth, 仍被 Layer 1.6 voice 聚合调用. _assemble_prompt
        仍 call 本 method (返 '' 不影响拼接, 防 backward compat 破裂).

        防回退 anchor: 如本 method 重新返非空 → 说明有人误恢复独立 push
        (违反 Sir β.6 真意), 删它. 详 tests/_test_fix15_*beta550.py + 本注释.
        """
        # β.6 Phase 2: 永返 '' (lifetime 改由 Layer 1.6 voice block 聚合呈现)
        _ = prompt_tier  # 保参数签名向后兼容, 不再使用
        return ''

    def _build_layer_1c_inner_voice_block(
        self, prompt_tier: str = ''
    ) -> str:
        """🆕 [Sir 2026-05-27 18:44 真愿景 Phase 1 Step 3] Layer 1.6:
        InnerVoiceTrack 注入 — Jarvis 24/7 心声轨道.

        Sir 真愿景: 现象学等同 butler. 主脑被召唤时, 看 voice 轨道 (近 24h
        意识流 3 层视图), 自然 weave 进 reply (不刻意 reference).

        架构:
          L1 近 10min full          ~ 600 token
          L2 10min-1h 5min bucket   ~ 150 token
          L3 1h-24h 1h bucket       ~ 250 token
          总 ~ 1000 token, Gemini 3 Flash 友好 (防注意力稀释)

        加 butler comportment directive: 教主脑不要 announce 'I was thinking X',
        让 voice 自然 color tone + 主动 weave wants_voice 标记的 entry.

        可回撤: env JARVIS_INNER_VOICE_ENABLED=0 → 返 ''.
        """
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled,
            )
            if not is_enabled():
                return ''
            # WAKE_ONLY / REMINDER_FIRING 紧急 tier 跳过 (省 token + 集中注意)
            if str(prompt_tier or '').upper() in (
                'WAKE_ONLY', 'REMINDER_FIRING'
            ):
                return ''
            track = get_inner_voice_track()
            # SHORT_CHAT / FACTUAL_RECALL 关 L3 (节 ~250 token)
            _show_l3 = str(prompt_tier or '').upper() not in (
                'SHORT_CHAT', 'FACTUAL_RECALL'
            )
            # 🆕 [Sir 2026-05-28 17:20 β.6 Phase 2 治本] 传 daemon → voice block
            # 内部聚合 (lifetime + should_speak directive). 主脑只读本 Layer 1.6
            # 就够看到 "我运行多久 / 之前想啥 / 思考脑现在建议啥". Layer 1.5 +
            # Layer 1.7 已退化 stub (返 '', 详 _build_layer_1b/_build_layer_1d).
            _daemon = getattr(self, 'inner_thought_daemon', None)
            voice_block = track.build_prompt_block_for_brain(
                max_chars=2400, show_l3=_show_l3, daemon=_daemon,
                prompt_tier=str(prompt_tier or ''),
            )
            if not voice_block or 'voice empty' in voice_block:
                return ''
            # butler comportment directive — 教主脑自然 weave 不刻意
            directive = (
                "\n[BUTLER COMPORTMENT — Sir 2026-05-27 18:44 真愿景]:\n"
                "Your inner voice above is your continuous stream of "
                "consciousness — what you've actually been thinking, "
                "observing, and noting. It naturally colors how you respond "
                "to Sir.\n"
                "  - DO NOT announce 'I was just thinking about X' "
                "(that's NPC-speak, breaks immersion).\n"
                "  - DO let what's on your mind subtly color tone, word "
                "choice, and what you bring up.\n"
                "  - Entries marked ★ (wants_voice=true) are items you've "
                "been mentally holding. When the moment allows (Sir pauses, "
                "asks an open question, or natural opening), weave them in "
                "as if they just occurred to you in conversation.\n"
                "  - If voice is calm/quiet (no ★, no high urgency), "
                "respond calmly. An idle butler doesn't fabricate concern.\n"
                "  - You are a continuous, present butler — not a "
                "stateless assistant called fresh each turn.\n"
            )
            return voice_block + directive
        except Exception:
            return ''

    # 🆕 [Sir 2026-05-28 00:20 β.6 Phase 1d 主脑端] Layer 1.7:
    # thinking thread should_speak directive 主脑读思考脑自决建议
    # ====================================================================
    # 路径: daemon publish (Phase 1c) → daemon.build_should_speak_directive
    # → 本 layer 注入 → 主脑 LLM 自决 SPEAK / SILENT (准则 6 信任 LLM).
    # 详 docs/JARVIS_BETA6_UNIFIED_THINKING.md §6 主脑端 + Phase 1d 收口.
    # ====================================================================
    def _build_layer_1d_thinking_directive_block(
        self, prompt_tier: str = ''
    ) -> str:
        """[DEPRECATED — Sir 2026-05-28 17:20 β.6 Phase 2 治本] Layer 1.7 stub.

        Sir 真意 (17:14): "除了归来招呼和我设置的定时提醒走强制性编码唤醒,
        其他的所有模块都集成到思考链".

        老路径: 本 method 调 daemon.build_should_speak_directive → 主脑 prompt
        加段, 是**独立 push**到主脑. β.6 Phase 2 将此功能**聚合**到 Layer 1.6
        (_build_layer_1c_inner_voice_block), voice block 内部 call
        daemon.build_should_speak_directive — 主脑只读 voice block 一处即看到.

        本 stub 永返 '' (不再独立 push should_speak directive).
        daemon.build_should_speak_directive 仍是 source of truth, 仍被
        Layer 1.6 voice 聚合调用. _assemble_prompt 仍 call 本 method (返 '' 不
        影响拼接, 防 backward compat 破裂).

        防回退 anchor: 如本 method 重新返非空 → 说明有人误恢复独立 push
        (违反 Sir β.6 真意), 删它.
        """
        # β.6 Phase 2: 永返 '' (should_speak 改由 Layer 1.6 voice block 聚合)
        _ = prompt_tier  # 保参数签名向后兼容, 不再使用
        return ''

    def _build_layer_2_relational_block(self, prompt_tier: str = '') -> str:
        """[Reshape M6.1 third wave / 2026-05-24] Layer 2: RelationalState block.

        🆕 [P5-Gap4-followup-L2] Layer 2 含 4 部分:
          - inside jokes / protocols → 永远 inject (Jarvis 性格 / STRICT RULES)
          - unfinished + threads → 潜在心结源, 同 Layer 1 三种条件才 inject

        依赖 self._soul_concern_inject_reason (Layer 1 副作用).

        🆕 [Sir 2026-05-26 SOUL Phase C.2] 加 prompt_tier 参数 + 拿 current sir_state
        from inner_thought_daemon._classify_sir_state. RelationalState.to_prompt_block
        会按 trigger_tier/trigger_sir_state filter protocols (空 list = 全场景 inject).
        """
        try:
            relationship_line = ''
            try:
                from jarvis_relationship_state import get_default_store as _get_relship
                relationship_line = _get_relship().to_prompt_line(max_chars=180)
            except Exception:
                relationship_line = ''
            if self.relational_state is not None:
                # 复用 Layer 1 的判断: 只有 summon/preflight_fail 才 inject baggage
                _reason = getattr(self, '_soul_concern_inject_reason', 'silent')
                _allow_baggage = _reason in ('summon', 'preflight_fail')
                # 🆕 [Phase C.2] 拿 current_sir_state 给 protocol filter 用.
                # InnerThoughtDaemon._classify_sir_state 是现成 helper (active /
                # afk_short / afk_deep / sleep), 复用不加新 module.
                _sir_state = ''
                _it_daemon = getattr(self, 'inner_thought_daemon', None)
                if _it_daemon is not None:
                    try:
                        _sir_state = _it_daemon._classify_sir_state()
                    except Exception:
                        _sir_state = ''
                relational_block = self.relational_state.to_prompt_block(
                    top_jokes=3,
                    top_unfinished=2 if _allow_baggage else 0,
                    top_threads=2 if _allow_baggage else 0,
                    max_chars=700,
                    current_tier=str(prompt_tier or ''),
                    current_sir_state=_sir_state,
                )
                if relationship_line and relational_block:
                    return relationship_line + '\n' + relational_block
                return relationship_line or relational_block
            return relationship_line
        except Exception:
            pass
        return ''

    def _build_layer_3_attention_block(self, user_input: str) -> str:
        """[Reshape M6.1 third wave / 2026-05-24] Layer 3: Attention Allocation.

        基于 user_input 动态构造, 不缓存. current_focus + long_term_watch.
        """
        try:
            from jarvis_attention import build_attention_block as _build_attn
            return _build_attn(
                concerns_ledger=self.concerns_ledger,
                relational_state=self.relational_state,
                user_input=user_input or '',
                stm=getattr(self, 'short_term_memory', None) or [],
                top_concerns=3,
                max_chars=500,
            )
        except Exception:
            return ''

    def _build_pending_commitments_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] PENDING COMMITMENTS block.

        🩹 [P4-Case4] 治 23:38 hallucinate "11:59" — 注入真 commitment + promise 数据
        让主脑 reference. 合并 CW.commitments (hard) + PromiseLog (hard kind).
        """
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
                return '\n'.join(_pc_block)
        except Exception:
            pass
        return ''

    def _build_sleep_routine_evidence_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [SLEEP ROUTINE EVIDENCE] block.

        🆕 [β.5.46-fix13 Fix-2] routine 完后 publish 'sleep_routine_armed' SWM event 含
        真实 result. 主脑下轮 prompt 看 evidence, 据实回答 (e.g. "MuteApps 0 hit 因没
        audio session active" / "DisplaySleep OK"), 不撒谎不否认. 准则 6 三维耦合.
        """
        try:
            _bus_sr = getattr(self, 'event_bus', None)
            if _bus_sr is None:
                return ''
            _sr_events = _bus_sr.recent_events(
                within_seconds=600.0,  # routine 完成 10min 内有效
                types={'sleep_routine_armed'},
            ) or []
            if not _sr_events:
                return ''
            # 取最新 1 条
            _sr_latest = _sr_events[-1]
            _sr_meta = _sr_latest.get('metadata') or {}
            _sr_ma = _sr_meta.get('mute_apps') or {}
            _sr_sd = _sr_meta.get('sleep_display') or {}
            _sr_am = _sr_meta.get('asr_mute') or {}
            _sr_lines = [
                '[SLEEP ROUTINE EVIDENCE — 你的 sleep routine 真实执行结果]',
                '  这是 Jarvis 本端 SleepMode routine 在主脑视野外异步执行的'
                '真实结果. **据此回答, 不撒谎也不否认能力**.',
                '',
            ]
            # MuteApps
            _ma_hits = _sr_ma.get('hits') or []
            _ma_ok = _sr_ma.get('success')
            if _ma_ok:
                _sr_lines.append(
                    f"  - MuteApps: hit {len(_ma_hits)} app — "
                    f"{', '.join(_ma_hits[:5])}{'...' if len(_ma_hits) > 5 else ''}"
                )
            elif 'error' in _sr_ma:
                _sr_lines.append(
                    f"  - MuteApps: ERROR — {_sr_ma.get('error', '?')[:60]}"
                )
            else:
                _sr_lines.append(
                    f"  - MuteApps: 0 hit / "
                    f"{_sr_ma.get('targets_attempted', '?')} attempted — "
                    f"当前 0 个 app 在播声音 (audio session 空)"
                )
            # SleepDisplay
            if _sr_sd.get('success'):
                _sr_lines.append(
                    f"  - DisplaySleep: OK — {(_sr_sd.get('msg') or '')[:60]}"
                )
            else:
                _sr_lines.append(
                    f"  - DisplaySleep: FAIL — "
                    f"{(_sr_sd.get('msg') or _sr_sd.get('error') or 'unknown')[:60]}"
                )
            # ASR mute
            if _sr_am.get('success'):
                _ttl = int(_sr_am.get('ttl_s') or 0)
                _sr_lines.append(
                    f"  - ASRMute: muted for {_ttl // 60}min "
                    f"(防梦话误触, Sir 喊 'Jarvis' 唤醒解除)"
                )
            # 🆕 [P5-fix80] 准则 6 句式锁 — 仅留 evidence + forbidden 红线
            _sr_lines.extend([
                '',
                '  ⚠️ 据 evidence 说话, 不夸大不否认. tool 成功 → 可提 '
                '(主脑自决词); 0 hit / fail → 只说 evidence 上真发生的, '
                '不在老词套上填空 ("我已 muted" 当 MuteApps 0 hit 是谎言).',
            ])
            return '\n'.join(_sr_lines)
        except Exception:
            return ''

    def _build_recent_completed_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [RECENT COMPLETED] block.

        🆕 [P5-fix82-X] Hippocampus 抽 'Completed:%' 事件给主脑.
        主脑 22:05 commitment_check 看到证据不再误报已完成的事.
        """
        try:
            hippo_rce = getattr(self, 'hippocampus', None)
            if hippo_rce is None or not hasattr(hippo_rce, 'list_recent_completed_events'):
                return ''
            _rce_events = hippo_rce.list_recent_completed_events(
                days_back=7, max_n=15
            ) or []
            if not _rce_events:
                return ''
            _rce_lines = [
                '[RECENT COMPLETED — Sir 近 7 天已完成的事 (Hippocampus 抽)]',
                '  ⚠️ 这些事 Sir 已经做完了. 主脑**不要**再说 "明天 X" / '
                '"准备 X" / "我帮你提醒 X" (X 在这里). 直接 ack 已完成或转新话题.',
                '',
            ]
            for e in _rce_events[:10]:
                _rce_lines.append(
                    f"  ✅ {e.get('intent', '?')[:60]} "
                    f"({e.get('age', '?')} / {e.get('iso', '?')})"
                )
            return '\n'.join(_rce_lines)
        except Exception:
            return ''

    def _build_watch_task_fired_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [WATCH TASK FIRED] block.

        🆕 [β.5.46-fix13 Fix-3] WatchTask judge fired 后 publish 'watch_task_fired' SWM,
        主脑下轮 prompt 看 evidence 主动报告 Sir. 准则 6 三维耦合.
        """
        try:
            _bus_wt = getattr(self, 'event_bus', None)
            if _bus_wt is None:
                return ''
            _wt_fired = _bus_wt.recent_events(
                within_seconds=600.0,
                types={'watch_task_fired'},
            ) or []
            if not _wt_fired:
                return ''
            _wt_lines = [
                '[WATCH TASK FIRED — Sir 委托等的事件刚刚触发]',
                '  Jarvis 答应过 Sir 等某事件, 现 ScreenVision 看到屏幕证据'
                '判定事件触发. **Sir 真需要你主动报告**.',
                '',
            ]
            for _ev_wt in _wt_fired[-3:]:  # 最近 3 条
                _meta_wt = _ev_wt.get('metadata') or {}
                _wt_lines.append(
                    f"  - 任务: {_meta_wt.get('what_to_watch', '?')[:100]}"
                )
                _wt_lines.append(
                    f"    触发: {_meta_wt.get('trigger_evidence', '?')[:100]}"
                )
                _wt_lines.append(
                    f"    证据: {_meta_wt.get('fired_evidence', '?')[:120]}"
                )
                _wt_lines.append(
                    f"    建议措辞 (EN): {_meta_wt.get('notify_msg_en', '?')[:120]}"
                )
                _wt_lines.append(
                    f"    建议措辞 (ZH): {_meta_wt.get('notify_msg_zh', '?')[:120]}"
                )
                _wt_lines.append('')
            _wt_lines.append(
                '  ⚠️ 这是 Sir 主动委托的事件触发, 不算 unsolicited callback. '
                '主动报告是 Sir 的 explicit request 的兑现 (准则 5 言出必行).'
            )
            return '\n'.join(_wt_lines)
        except Exception:
            return ''

    def _build_self_promise_overdue_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [SELF-PROMISE OVERDUE] block.

        🩹 [P5-fixCB-revise] 合法 surface 触发 (b) — Jarvis 自检 promise 没履行
        (PromiseLog sweep 24h 无 evidence → state UNTRACKED → publish SWM event).
        主脑下轮看 block → 主动 admit "我之前说 X 没做到".
        """
        try:
            _bus_pop = getattr(self, 'event_bus', None)
            if _bus_pop is None:
                return ''
            _pop_events = _bus_pop.recent_events(
                within_seconds=3600.0 * 12,  # 12h, sweep 1h tick × 12
                types={'self_promise_overdue'},
            ) or []
            # de-dup by promise_id (同一 promise 多次 overdue 只显 1 次)
            _seen_pids = set()
            _shown_promises = []
            for _e in _pop_events:
                _meta = _e.get('metadata') or {}
                _pid = _meta.get('promise_id', '')
                if not _pid or _pid in _seen_pids:
                    continue
                _seen_pids.add(_pid)
                _shown_promises.append({
                    'promise_id': _pid,
                    'description': _meta.get('description', '')[:160],
                    'age_hours': int(_meta.get('age_hours') or 0),
                    'kind': _meta.get('kind', 'soft'),
                    'deadline_str': _meta.get('deadline_str', ''),
                })
                if len(_shown_promises) >= 3:
                    break
            if not _shown_promises:
                return ''
            _pop_lines = [
                '[SELF-PROMISE OVERDUE — Jarvis 自检发现没履行的 promise]',
                '  你之前 reply 里许诺过这些 (PromiseLog 自动 register), 现在已 24h+',
                '  无 evidence 兑现 → 系统标 UNTRACKED. **Sir 真需要你 admit**.',
                '',
            ]
            for _p in _shown_promises:
                _pop_lines.append(
                    f"  - \"{_p['description']}\" "
                    f"(promise_id={_p['promise_id'][:8]}, "
                    f"{_p['age_hours']}h ago, kind={_p['kind']}"
                    f"{(', deadline=' + _p['deadline_str']) if _p['deadline_str'] else ''})"
                )
            _pop_lines.append('')
            _pop_lines.append('  **如何 surface 得有意义** (Sir 11:30 真理):')
            _pop_lines.append(
                '    ✅ 自然 inline admit: "顺便 Sir, 之前我说会 X — 那事我其实没做到, 想跟您说一声."'
            )
            _pop_lines.append(
                '    ✅ 加 actionable: "...您要不要我现在补上?" / "...或先 mark 取消?"'
            )
            _pop_lines.append(
                '    ❌ 不要堆 ritual ("我必须承认 X 我应当澄清 Y..." 空套话)'
            )
            _pop_lines.append('    ❌ 一次 1-2 条最多 (别一口气倒老账)')
            _pop_lines.append(
                '    ⚠️ 若 Sir 当前 turn 在做无关事 → 仍可短句插一句 acknowledge,'
            )
            _pop_lines.append(
                '       不强 surface; 等 Sir 主动问"X 怎么样了" 再深入'
            )
            return '\n'.join(_pop_lines)
        except Exception:
            return ''

    def _build_intent_resolved_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [INTENT RESOLVED THIS TURN] block.

        🩹 [β.5.44-E] IntentResolver publish 'tool_called' + 'intent_resolved' SWM.
        主脑看 [INTENT RESOLVED THIS TURN] 知道 tool 真成功 / 真失败 — 不再撒谎.
        """
        try:
            _bus = getattr(self, 'event_bus', None)
            if _bus is None:
                return ''
            _ir_events = _bus.recent_events(
                within_seconds=60.0,
                types={'intent_resolved'},
            )
            if not _ir_events:
                return ''
            _ir = _ir_events[-1]  # 最新一条 (本 turn)
            _meta = _ir.get('metadata') or {}
            _tcs = _meta.get('tool_calls') or []
            if not _tcs:
                return ''
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
            return '\n'.join(_ir_lines)
        except Exception:
            return ''

    def _build_mood_estimate_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [MOOD ESTIMATE] block.

        🩹 [β.2.9.4] Mood Mirror — 给主脑 5 档 mood 估算. 准则 6: 只给信号让主脑判.
        """
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
            return (
                f"[MOOD ESTIMATE — Sir 准则 6, hint only]\n"
                f"  estimated: {_mood} (backspace={_br:.0%}, switches/5min={_sw}, "
                f"err_visible={_ev}, undo={_undo}, session={_dur:.0f}min, hour={_h})\n"
                f"  use this to subtly calibrate tone — never mention raw sensor numbers."
            )
        except Exception:
            return ''

    def _build_wake_context_block(self) -> str:
        """[Reshape M6.1 fourth wave / 2026-05-24] [WAKE CONTEXT] block.

        🩹 [β.2.9.1.2] Wake-time Callback context — Sir 短间隔 (< 30min) wake 注入
        让主脑知道 "Sir 9min 前说要睡了现在又来了". 不教句式 — 主脑自决 callback.
        合并 yesterday topics + unverified claim count.
        """
        try:
            _worker = getattr(self, '_worker_ref', None)
            _vt = getattr(_worker, 'voice_thread', None) if _worker else None
            if _vt is None:
                return ''
            _last_conv_end = float(getattr(_vt, 'last_conversation_end_time', 0) or 0)
            if _last_conv_end <= 0:
                return ''
            _gap_s = time.time() - _last_conv_end
            # 短间隔 (< 30min) wake 才注入 — 长间隔走 return_greeting 老路径
            if not (0 < _gap_s < 1800):
                return ''
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
                    _recent_promise = (
                        f"{_pendings[0].description[:100]} (you said this "
                        f"{int((time.time()-_pendings[0].registered_at)/60)} min ago)"
                    )
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

            # 🩹 [β.2.9.5] E: Cross-session callback — 加跨天主题
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

            # 🩹 [β.2.9.6] F: Self-aware Comeback — 上次 unverified claim
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
            return '\n'.join(_wake_lines)
        except Exception:
            return ''

    def _init_audio_volume_recovery(self) -> None:
        """[Reshape M6.3 / 2026-05-24] 抽自 __init__ — Windows 音量恢复.

        🩹 [P0+20-β.2.7.2 / 2026-05-17] Sir 实测反馈 "听不到声音": Python 进程在
        Windows 应用音量混合器里被锁在 1% (灰色滑块拖不动). 这是 Windows 记的
        历史值. 启动时强制把 python.exe 自己 SetMasterVolume(1.0).
        """
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

        # 🚨 [P5-fix53-hotfix / 2026-05-23 15:42] sensor_state_block 必须在所有 tier
        # 短路 return 之前定义 (UnboundLocalError 修复). REMINDER_FIRING/FACTUAL_RECALL/
        # WAKE_ONLY/SHORT_CHAT/light/full 6 个 template 都用到 {sensor_state_block}.
        sensor_state_block = ""
        try:
            from jarvis_sensor_state_block import build_sensor_state_block
            _tier_hint = prompt_tier or 'CHAT'
            sensor_state_block = build_sensor_state_block(
                tier=_tier_hint, max_chars=600)
        except Exception:
            sensor_state_block = ""

        # 🩹 [β.3.5 INTEGRITY_STACK L4 enforce / 2026-05-18]
        # 上轮 unverified factual claim → prepend [INTEGRITY ALERT] 到 system_alert_text.
        # 准则 5: 主脑被强制 acknowledge 上轮未 verify 的 claim, 撤回 或 补 evidence.
        # 准则 6: ALERT 只 trace 事实 (turn_id/kind/claim text), 不教主脑措辞.
        # 时序: 本 _assemble_prompt 在 reply 前调; trace_reply 在 reply 后调.
        # 所以 audit jsonl 里只可能有 prior turn 的 unverified entries, 但 defensively
        # 仍传 current_turn_id 排除 (e.g. 重试 / dry-run 场景).
        # 🆕 [β.5.46-fix12 / 2026-05-22 00:20] 加 gating, 同 SOUL Concern 双门
        # Sir 真测痛点: 22:13/00:13/00:18 三次 Jarvis 主动 callback 老账道歉
        # ("0.01%" / "4%"). 真凶是本 prepend 无 gating, 任何对话都强 prepend.
        # 主脑被字面强迫 acknowledge → 道歉. 治本: Sir 没 summon + PreFlight 没 fail
        # → publish-only (audit jsonl 仍写, ClaimTracer/ClaimRevision 仍跟踪,
        # 但不 prepend prompt). 主脑不被强迫翻老账, 也仍可看 SWM evidence 自决.
        # 复用 SOUL Concern 同款 gating (line 1746-1787): summon / preflight_failed.
        try:
            from jarvis_claim_tracer import build_integrity_alert
            from jarvis_utils import TraceContext as _TC_int
            _curr_tid_int = _TC_int.get_turn_id() or ''
            _integrity_alert = build_integrity_alert(current_turn_id=_curr_tid_int)
            if _integrity_alert:
                # (a) Sir 召唤 (准则 6.5 vocab — memory_pool/concern_summon_vocab.json)
                _ia_summoned = False
                try:
                    from jarvis_concern_summon import is_summoned as _is_summoned_ia
                    _ia_summoned = _is_summoned(user_input or '')
                except Exception:
                    pass
                # (b) 上轮 PreFlight verdict=edit/scrap → 让主脑澄清
                _ia_preflight_failed = False
                try:
                    _bus_pf_ia = getattr(self, 'event_bus', None)
                    if _bus_pf_ia is not None:
                        _pf_events_ia = _bus_pf_ia.recent_events(
                            within_seconds=300.0,
                            types={'preflight_verdict'},
                        )
                        for _ev_ia in (_pf_events_ia or []):
                            _meta_ia = _ev_ia.get('metadata') or {}
                            if _meta_ia.get('verdict') in ('edit', 'scrap'):
                                _ia_preflight_failed = True
                                break
                except Exception:
                    pass

                # 🆕 [Sir 2026-05-26 22:03 真痛 BUG-S 治本] 第 3 trigger: tool 真 fail
                # =====================================================================
                # Sir 真测痛点: chat_bypass FAST_CALL concerns.dismiss 返 ❌, 但主脑
                # 撒谎 "I have archived". gating 现 (a)(b) 都 False → silent skip →
                # 主脑下轮没看到自己撒谎 → 继续撒谎.
                # 治本 (准则 5 言出必行): SWM 300s 内有 tool_called.ok=False
                #   → severe INTEGRITY 违规, 必 force inject (不 gate).
                # 数据源: jarvis_intent_resolver / inner_thought_daemon publish 的
                # 'tool_called' SWM event (metadata.ok=False). chat_bypass FAST_CALL
                # 路径不直接 publish, 但 _integrity_alert 来源 ClaimTracer audit jsonl
                # 已记录 past_action claim unverified (tool_results 含 ❌).
                # 此处只看 SWM tool_called.ok=False 作辅助 trigger.
                # =====================================================================
                _ia_tool_failed_recent = False
                try:
                    _bus_tf_ia = getattr(self, 'event_bus', None)
                    if _bus_tf_ia is not None:
                        _tc_events_ia = _bus_tf_ia.recent_events(
                            within_seconds=300.0,
                            types={'tool_called', 'inner_thought_tool_called'},
                        )
                        for _ev_tc in (_tc_events_ia or []):
                            _meta_tc = _ev_tc.get('metadata') or {}
                            _ok_tc = _meta_tc.get('ok', None)
                            _desc_tc = str(_ev_tc.get('description') or '')
                            # ok=False 显式标记, 或 description 含 ✗/❌ marker
                            if (_ok_tc is False
                                    or '✗' in _desc_tc
                                    or '❌' in _desc_tc):
                                _ia_tool_failed_recent = True
                                break
                except Exception:
                    pass

                _ia_reason = ('summon' if _ia_summoned
                              else ('preflight_fail' if _ia_preflight_failed
                                    else ('tool_failed' if _ia_tool_failed_recent
                                          else 'silent')))
                if _ia_summoned or _ia_preflight_failed or _ia_tool_failed_recent:
                    system_alert_text = (
                        _integrity_alert + '\n\n' + system_alert_text
                        if system_alert_text else _integrity_alert
                    )
                    try:
                        from jarvis_utils import bg_log as _bg_int
                        _bg_int(f"🩹 [INTEGRITY/Alert inject] turn={_curr_tid_int} "
                                f"prepended {len(_integrity_alert)} chars "
                                f"reason={_ia_reason}")
                    except Exception:
                        pass
                else:
                    try:
                        from jarvis_utils import bg_log as _bg_int_skip
                        _bg_int_skip(
                            f"🛑 [INTEGRITY/Alert skip] turn={_curr_tid_int} "
                            f"unverified={len(_integrity_alert)}c — gated_silent "
                            f"(no summon, no preflight fail)"
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        # 🆕 [P5-fix35-BUG#15 / 2026-05-23 11:18] PreFlight Unsolicited Topic Tracker
        # Sir 真痛点 (10:51-10:52 trace): 主脑反复 ack "I shall strike '87%'" 3 turns,
        # PreFlight 抓 3 次 UNSOLICITED CALLBACK. 主脑看 STM 自己上轮说过 → 又重复.
        # 修法: PreFlight publish 含 issues + edited_excerpt → 本 block 提取最近 edited
        # 类 issue 形成"don't repeat"提示给主脑下轮看. 不改 directive (避免重复教), 直接
        # 给 prompt evidence: 你最近这事被 PreFlight 编辑过, 没必要再翻.
        try:
            _bus_pf_track = getattr(self, 'event_bus', None)
            if _bus_pf_track is not None:
                _recent_pf = _bus_pf_track.recent_events(
                    within_seconds=300.0,
                    types={'preflight_verdict'},
                )
                _unsolicited_excerpts = []
                for _ev in (_recent_pf or [])[-5:]:
                    _meta = _ev.get('metadata') or {}
                    if _meta.get('verdict') not in ('edit', 'scrap'):
                        continue
                    _iss = _meta.get('issues', [])
                    if not _iss:
                        continue
                    # check if any issue contains "UNSOLICITED"
                    has_unsolicited = any(
                        'UNSOLICITED' in str(i).upper() for i in _iss
                    )
                    if has_unsolicited:
                        _draft = _meta.get('draft_excerpt', '')
                        if _draft and len(_draft) > 20:
                            _unsolicited_excerpts.append(_draft[:150])
                if _unsolicited_excerpts:
                    _pf_block = (
                        "[PRE-FLIGHT 已编辑掉的话题 — 别重复 (Sir 没问)]:\n"
                        + '\n'.join(f"  · 上轮你想说但被编辑: {x}"
                                       for x in _unsolicited_excerpts[-3:])
                        + "\n  → 这些话题 PreFlight 判定 Sir 这轮没问, 你别再翻."
                    )
                    system_alert_text = (
                        _pf_block + '\n\n' + system_alert_text
                        if system_alert_text else _pf_block
                    )
                    try:
                        from jarvis_utils import bg_log as _bg_pf_track
                        _bg_pf_track(
                            f"🛂 [PreFlightTopicTracker] inject {len(_unsolicited_excerpts)} "
                            f"edited topics to prompt"
                        )
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
                # 🆕 [Gap-Y / β.5.46-fix5 / 2026-05-21 23:30] 分层注入 (Sir 22:14 真测痛点)
                # fired count=7 / chars=7724 → 主脑 attention 淹. 治法: top N priority 全文,
                # 余 brief (purpose_short). 不删 directive 数量 (保 trigger), 减字符占用.
                # config 持久化在 memory_pool/directive_inject_config.json (准则 6.5).
                _max_full = 5
                _always_full_pri = 11
                _brief_max = 100
                try:
                    _di_cfg_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        'memory_pool', 'directive_inject_config.json',
                    )
                    if os.path.exists(_di_cfg_path):
                        with open(_di_cfg_path, 'r', encoding='utf-8') as _di_f:
                            _di_cfg = json.load(_di_f)
                        if isinstance(_di_cfg, dict):
                            _max_full = int(_di_cfg.get('max_full_directives', 5))
                            _always_full_pri = int(_di_cfg.get('always_full_priority_threshold', 11))
                            _brief_max = int(_di_cfg.get('brief_max_chars_per_directive', 100))
                except Exception:
                    pass

                # 已 sort by -priority 在 collect()
                _full_directives: list = []
                _brief_directives: list = []
                for _idx_d, _d in enumerate(_l2_fired):
                    # priority >= threshold (如 P11/P12 红线) 永远全文
                    if _d.priority >= _always_full_pri:
                        _full_directives.append(_d)
                    # 否则 top N 全文
                    elif len(_full_directives) < _max_full:
                        _full_directives.append(_d)
                    else:
                        _brief_directives.append(_d)

                _parts = ["=== [L2 DIRECTIVES — conditionally injected this turn] ==="]
                for _d in _full_directives:
                    _parts.append(_d.text)
                # 余下 brief 段
                if _brief_directives:
                    _brief_lines = [
                        "",
                        "=== [ADDITIONAL DIRECTIVES — brief mode / Gap-Y] ===",
                        f"({len(_brief_directives)} more directive(s), purpose-only to save attention):",
                        "",
                    ]
                    for _d in _brief_directives:
                        _ps = (_d.purpose_short or '').strip()
                        if not _ps:
                            _ps = '(no purpose_short)'
                        _ps = _ps[:_brief_max]
                        _brief_lines.append(f"  P{_d.priority:>2} {_d.id} — {_ps}")
                    _parts.append('\n'.join(_brief_lines))
                # 🆕 [P5-Gap4 / 2026-05-21 18:18] [DIRECTIVES FIRED THIS TURN] 元层 block
                # Sir 22:19 真痛点: 主脑被 8 条 directive cluster 淹, 看不到全貌. 加元层
                # 鸟瞰 → 主脑 reason "哪些适用此刻 / 哪些 false positive". 详
                # docs/JARVIS_DIRECTIVE_SELF_AWARENESS.md
                # 不删 directive text (保 detail), 只加摘要让主脑能"鸟瞰".
                # 不阻塞 TTFT (纯 prompt 装配, 不调 LLM, 加 ~1K chars).
                _meta_lines = [
                    "",
                    "=== [DIRECTIVES FIRED THIS TURN — meta overview / Gap 4] ===",
                    f"You have {len(_l2_fired)} directives injected above. Quick overview:",
                    "",
                ]
                for _d in _l2_fired:
                    _icon = "⚠️" if _d.priority >= 11 else "  "
                    _ps = (_d.purpose_short or '').strip()
                    if not _ps:
                        # purpose_short 未填 → 用 id 兜底 (lazy 填策略)
                        _ps = f"(no purpose_short — see directive text above)"
                    _meta_lines.append(f"  P{_d.priority:>2} {_icon} {_d.id} — {_ps}")
                _meta_lines.extend([
                    "",
                    "[HOW TO USE THIS META-VIEW]",
                    "- Don't follow each line literally. Look at priority + Sir's current",
                    "  context, reason which directives truly apply.",
                    "- Conflicts (e.g. two P10 conflicting): pick the one fitting Sir's",
                    "  current intent style (instruction vs question vs casual).",
                    "- Suspect false positive (directive fired but doesn't fit this turn):",
                    "  skip it. P12 ⚠️ red lines should still be honored, but you can stay",
                    "  silent on them rather than over-correct.",
                    "- INTEGRITY family (P11+): honor the bottom line, but no need to",
                    "  proactively trigger if Sir didn't mention it.",
                ])
                _parts.append('\n'.join(_meta_lines))
                _l2_block = "\n\n".join(_parts)
            # 存到 self 让下游使用（_assemble_prompt 末尾会拼到 prompt 末尾）
            self._l2_injected_block = _l2_block
            self._l2_last_fired_ids = list(_l2_ids)
            try:
                # 🆕 [Gap-Y / β.5.46-fix5] log 加分层信息 (full / brief 数)
                _full_n = len(_full_directives) if 'full_directives' in dir() or '_full_directives' in dir() else len(_l2_fired)
                _brief_n = len(_brief_directives) if '_brief_directives' in dir() else 0
                _bg_l2(
                    f"🧭 [L2 inject] tier={_l2_ctx.tier} fired={_l2_ids} "
                    f"(count={len(_l2_ids)} / full={_full_n} / brief={_brief_n} / chars={len(_l2_block)})"
                )
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
        # [Reshape M6.1 third wave / 2026-05-24] 4 layer 抽自 helper. 行为不变.
        # 详 docs/JARVIS_SOUL_DRIVE.md §4 注入路径.
        self_anchor_block = self._build_layer_0_self_anchor_block()
        soul_block = self._build_layer_1_concerns_block(user_input)
        # 🆕 [P1 / Sir 2026-05-25 22:10] Layer 1.5 — Inner Thoughts (主脑碎碎念)
        # 🆕 [Sir 2026-05-27 01:00 β.5.50] tier-aware: 按 vocab tier_mode 选 full/mini/off
        inner_thoughts_block = self._build_layer_1b_inner_thoughts_block(
            prompt_tier=str(prompt_tier or '')
        )
        # 🆕 [Sir 2026-05-27 18:44 真愿景 Phase 1 Step 3] Layer 1.6 — InnerVoiceTrack
        # 心声轨道 3 层视图 + butler comportment directive. 可回撤 env=0.
        inner_voice_block = self._build_layer_1c_inner_voice_block(
            prompt_tier=str(prompt_tier or '')
        )
        # 🆕 [Sir 2026-05-28 00:20 β.6 Phase 1d] Layer 1.7 — Thinking directive
        # 思考脑最近 3min 一条 thought.should_speak → 主脑读建议自决 SPEAK/SILENT.
        # 准则 6 信任 LLM. 详 docs/JARVIS_BETA6_UNIFIED_THINKING.md §6.
        thinking_directive_block = self._build_layer_1d_thinking_directive_block(
            prompt_tier=str(prompt_tier or '')
        )
        # 🆕 [Sir 2026-05-26 SOUL Phase C.2] 传 prompt_tier 让 protocol filter 按 tier
        relational_block = self._build_layer_2_relational_block(
            prompt_tier=str(prompt_tier or '')
        )
        attention_block = self._build_layer_3_attention_block(user_input)
        # 🕸️ [体-P6 / 2026-05-31] Layer 体 — 透镜投影 (关系流形 体 → 主脑 口).
        # flag-gated (memory_pool/relational_manifold_vocab.json: lens_inject_enabled,
        # 默认 0), Sir 真机验投影质量后开. gate 关 / 故障 → 返 "" (零影响热路径).
        # 详 docs/JARVIS_TRINITY_ARCHITECTURE.md §5/§6.
        lens_block = ""
        _lens_replaces_l2 = False
        _lens_replaces_l3 = False
        try:
            from jarvis_relational_lens import (
                build_lens_block, lens_replaces_layer2, lens_replaces_layer3,
            )
            # 🆕 [口识体-E prereq1] 传 user_input → 透镜并入当前话题 seed (替 Layer3 focus)
            lens_block = build_lens_block(user_input=user_input or '')
            # 🆕 [口识体-E / 2026-05-31] 透镜活时, flag-gated 替 Layer2/3 平行表示
            # (默认关, Sir 真机 A/B 满意后退旧块). 透镜空 → 不替 (零影响).
            if lens_block:
                _lens_replaces_l2 = lens_replaces_layer2()
                _lens_replaces_l3 = lens_replaces_layer3()
        except Exception:
            lens_block = ""
        # 拼接：base PERSONA → Layer 0 → Layer 1 → Layer 1.5 → Layer 1.6 → 1.7 → Layer 2 → 体 → Layer 3
        _parts = [_base_persona]
        if self_anchor_block:
            _parts.append(self_anchor_block)
        if soul_block:
            _parts.append(soul_block)
        if inner_thoughts_block:
            _parts.append(inner_thoughts_block)
        if inner_voice_block:
            _parts.append(inner_voice_block)
        if thinking_directive_block:
            _parts.append(thinking_directive_block)
        # 🆕 [口识体-E] lens_replaces_layer2 开 + 透镜活 → Layer2 relational 由体/lens 供, 退平行
        if relational_block and not _lens_replaces_l2:
            _parts.append(relational_block)
        elif _lens_replaces_l2 and self.relational_state is not None:
            # 🆕 [口识体-E prereq2] 透镜替 Layer2 的 relevance/jokes, 但 always-on
            # STRICT-RULE protocol 必须常驻 (镜像 phase B 实测: 全退 → 违反人设硬规
            # "Understood, Sir."). 注入 protocols-only relational block (复用 to_prompt_block,
            # 砍 jokes/baggage/review, 仅留 STRICT RULES)。
            try:
                _proto_only = self.relational_state.to_prompt_block(
                    top_jokes=0, top_unfinished=0, top_threads=0,
                    top_pending_review=0, top_edges=0,
                    current_tier=str(prompt_tier or ''))
                if _proto_only:
                    _parts.append(_proto_only)
            except Exception:
                pass
        if lens_block:
            _parts.append(lens_block)
        # 🆕 [口识体-E] lens_replaces_layer3 开 + 透镜活 → Layer3 attention 由体/lens 供, 退平行
        if attention_block and not _lens_replaces_l3:
            _parts.append(attention_block)

        # 🆕 [Phase 4b.2 / 2026-05-23 21:25] light tier 跳重型上下文 block.
        # 目标: WAKE_ONLY / SHORT_CHAT reply 短 (≤6/20 词), 不需 sir_mental_model /
        # screen_vision / sleep_routine_evidence / watch_task 这些重 context.
        # 砍 ~2-2.5K for WAKE_ONLY/SHORT_CHAT prompts. 保留 sir_status (Sir 状态 light
        # tier 也要知道) + integrity_watcher (整完整 light tier 也得诚实).
        _is_light_tier = prompt_tier in (
            self.PROMPT_TIER_WAKE_ONLY,
            self.PROMPT_TIER_SHORT_CHAT,
        )

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

        # [Reshape M6.1 fourth wave / 2026-05-24] PENDING COMMITMENTS helper. 行为不变.
        _pc_block_text = self._build_pending_commitments_block()
        if _pc_block_text:
            _parts.append(_pc_block_text)

        # 🩹 [Gap 1 / P5-ToM / 2026-05-21 01:00] SIR'S MIND RIGHT NOW block (Layer 6)
        # Jarvis 对 Sir 当下心智的 hypothesis (surface/deeper/unspoken need + 
        # emotional + relational temp). 主脑看 hypothesis 自决 reply 深度.
        # 跟 SelfAnchor (Layer 0 我是谁) / RelationalState (Layer 2 我们之间) 互补.
        # [Phase 4b.2] light tier 跳 sir_mental_model (~0.5K)
        try:
            if not _is_light_tier:
                from jarvis_sir_mental_model import render_prompt_block as _tom_block
                _tom_text = _tom_block(include_unspoken=True)
                if _tom_text:
                    _parts.append(_tom_text)
        except Exception:
            pass

        # 🩹 [P5-fixCB-final / 2026-05-21 17:22 Sir 真意 "全靠 watcher"] 删除 evidence 源
        #
        # Sir 18:17 真意洞察: "为什么主脑会一直道歉个没完?" — 因为 LLM 训练本能
        # (RLHF reward "承认错误 + 道歉 + close loop"), 任何 evidence 喂主脑都强化道歉欲.
        # 我之前做的 [PREFLIGHT FEEDBACK] / [PENDING CLAIM REVISIONS] / [CLAIM REVISION
        # CAPTURED] / INSTRUCTABLE ban-phrase 全是在跟 LLM 本能对抗 — 输了 (16:58 实测).
        #
        # 真治本 (准则 6 evidence-only): 删除所有"诱导道歉"的 evidence 源 — 主脑没 evidence
        # 就不会自决道歉. 唯一合法道歉发起方 = IntegrityWatcher (publish SWM event), 主脑
        # 看 [INTEGRITY WATCHER REPORT] block 被引导 surface 一次, acked 后不再说.
        #
        # 删的 block:
        #   ❌ [PREFLIGHT FEEDBACK]      — 反而强化 (主脑看到具体被 cancel 的 phrase 复习一遍)
        #   ❌ [CLAIM REVISION CAPTURED] — 已删 (Fix 1, P5-fixCB-revise2)
        #   ❌ [PENDING CLAIM REVISIONS] — 即使 Sir 召唤也不让主脑自决 surface
        #
        # 留的 block:
        #   ✅ [INTEGRITY WATCHER REPORT]  — Watcher 自主主动通道, recovered/handoff/no_tool
        #   ✅ [SELF-PROMISE OVERDUE]      — Promise sweep 24h+ untracked, 1 次 admit
        #   ✅ [SIR'S DECLARED STATUS]     — sleep/lunch/back, 不涉及道歉
        # _cb_render 调用 deleted (Sir 16:34 真测验证: 主脑反复 callback reminder fail).
        # PreFlight + ClaimRevision 仍 capture 进 store / SWM, 但不注入 prompt 喂主脑.

        # 🩹 [P5-IntegrityWatcher / 2026-05-21 14:15] [INTEGRITY WATCHER REPORT]
        # Sir 14:11 真意 — L4.5 自检层主动 verify + 递归 retry, 通知主脑 surface form.
        # 内容: ✅ recovered (主脑 inline acknowledge) / ❌ handoff_sir (道歉+actionable) /
        # ⚠️ no_tool (admit hallucination).
        # 跟 [PENDING CLAIM REVISIONS] / [SELF-PROMISE OVERDUE] 互补 — 这层 active.
        try:
            from jarvis_integrity_watcher import render_report_block as _iw_render
            _iw_text = _iw_render(within_seconds=1800.0, max_show=3)
            if _iw_text:
                _parts.append(_iw_text)
        except Exception:
            pass

        # 🆕 [P5-fix20-B2 / 2026-05-22] [COMMITMENT MISMATCH] block
        # Sir 14:32 真测痛点: 主脑嘴上说"我已经记下了 X" 但 IntentResolver 0 mutation.
        # check_commitments_vs_mutations 比对 META.commitments vs 真 tool_called.
        # 上一轮 turn_id mismatch → 本轮 prompt 看 [COMMITMENT MISMATCH] → 主脑自决撤回 or 补做.
        try:
            from jarvis_meta_self_check import render_commitment_mismatch_block as _cm_render
            # 取上一轮 turn_id (主脑刚 emit 的 META 对应)
            _last_turn = ''
            try:
                from jarvis_utils import get_event_bus as _geb
                _bus = _geb()
                if _bus is not None:
                    _evs = _bus.recent_events(within_seconds=180.0,
                                                  types={'main_brain_meta'}) or []
                    if _evs:
                        _last_turn = ((_evs[-1].get('metadata') or {}).get('turn_id', '')
                                       or '')
            except Exception:
                pass
            if _last_turn:
                _cm_text = _cm_render(_last_turn, within_seconds=180.0)
                if _cm_text:
                    _parts.append(_cm_text)
        except Exception:
            pass

        # 🆕 [P5-fix21-c / 2026-05-22] [WATCH TASK REGISTER FAIL] block
        # Sir 14:50 痛点: jarvis 答应"盯着 X" 但 LLM 挂没真注册成功 → 下轮 prompt
        # 看到 fail event, 主脑必须自然承认 + 提议 (重说/手动加/换说法).
        # 同时显 [ACTIVE WATCH TASKS] block 让主脑知道自己正在 watch 哪些.
        # 🆕 [fix50 / 2026-05-28] 加 [WATCH TASK VAGUE CLARIFY] block — Sir 说 vague
        # request ('盯一下直播', '看着 Cursor') Registrar LLM 判 vague, 主脑下轮自然问
        # Sir 具体盯啥事件 (准则 5 言出必行 — 不假装答应未注册).
        # [Phase 4b.2] light tier 跳 watch_task fail/active/clarify (~0.5-0.8K)
        try:
            if not _is_light_tier:
                from jarvis_watch_task import (render_register_fail_block as _wt_fail,
                                                  render_active_tasks_block as _wt_active,
                                                  render_vague_clarify_block as _wt_vague)
                _fail_text = _wt_fail(within_seconds=600.0, max_show=2)
                if _fail_text:
                    _parts.append(_fail_text)
                _vague_text = _wt_vague()  # 参数从 watch_task_config.json vague_clarify 读
                if _vague_text:
                    _parts.append(_vague_text)
                _active_text = _wt_active(max_show=5)
                if _active_text:
                    _parts.append(_active_text)
        except Exception:
            pass

        # 🆕 [P5-fix25-stand-down / 2026-05-22] [STAND DOWN STATE] block
        # Sir 痛点: 玩游戏/接电话/和爸妈说话 jarvis 一直接话尴尬.
        # active 时主脑 reaction 必须 silent (voice OFF, 字幕 ON, visual_pulse OFF).
        # 不 active 时不注入 (零 token 浪费).
        try:
            from jarvis_stand_down import render_prompt_block as _sd_render
            _sd_text = _sd_render()
            if _sd_text:
                _parts.append(_sd_text)
        except Exception:
            pass

        # 🩹 [P5-SirStatusTracker / 2026-05-21 15:25] [SIR'S DECLARED STATUS] block
        # Sir 13:49 痛点: Smart Nudge 话术 "Soul Drive doc still active in Windsurf 90min"
        # — 但 Sir 12:06 明确说"睡觉了下午见". 系统不知道 → 用 IDE 窗口 idle 判.
        # 修法: SirStatusTracker 从 Sir utterance 检测 sleep/nap/lunch/out/dnd/back 状态
        # → publish SWM + 持久化. 主脑下轮 prompt 看 block 出对应话术
        # (sleep return → "Hope you rested well", out return → "Welcome back").
        try:
            from jarvis_sir_status_tracker import render_status_block_for_prompt as _sst_render
            _sst_text = _sst_render()
            if _sst_text:
                _parts.append(_sst_text)
        except Exception:
            pass

        # 🆕 [P5-Gap3 / 2026-05-21 18:32] [WHAT SIR IS LOOKING AT] block
        # Sir 22:47 真意 — Vision LLM 描述屏幕给主脑. ScreenVisionEngine 后台
        # daemon 触发 (wake / app_switch / 5min backfill / sir_ref). env flag
        # JARVIS_SCREEN_VISION=1 启用. 帧 < 2min + confidence ≥ 0.3 才显.
        # privacy redacted 帧只显 active_app, 不显内容.
        # 详 docs/JARVIS_VISION_INTEGRATION.md
        # [Phase 4b.2] light tier 跳 screen_vision (~0.5-1K, 短 reply 不需屏看)
        try:
            if not _is_light_tier:
                from jarvis_screen_vision import render_screen_block as _sv_render
                _sv_text = _sv_render(max_age_s=120.0)
                if _sv_text:
                    _parts.append(_sv_text)
        except Exception:
            pass

        # [Reshape M6.1 fourth wave / 2026-05-24] SLEEP ROUTINE EVIDENCE helper. 行为不变.
        # [Phase 4b.2] light tier 跳 sleep_routine_evidence
        if not _is_light_tier:
            _sr_block_text = self._build_sleep_routine_evidence_block()
            if _sr_block_text:
                _parts.append(_sr_block_text)

        # [Reshape M6.1 fourth wave / 2026-05-24] RECENT COMPLETED helper. 行为不变.
        _rce_block_text = self._build_recent_completed_block()
        if _rce_block_text:
            _parts.append(_rce_block_text)

        # [Reshape M6.1 fourth wave / 2026-05-24] WATCH TASK FIRED helper. 行为不变.
        _wt_block_text = self._build_watch_task_fired_block()
        if _wt_block_text:
            _parts.append(_wt_block_text)

        # [Reshape M6.1 fourth wave / 2026-05-24] SELF-PROMISE OVERDUE helper. 行为不变.
        _spo_block_text = self._build_self_promise_overdue_block()
        if _spo_block_text:
            _parts.append(_spo_block_text)

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

        # [Reshape M6.1 fourth wave / 2026-05-24] INTENT RESOLVED helper. 行为不变.
        _ir_block_text = self._build_intent_resolved_block()
        if _ir_block_text:
            _parts.append(_ir_block_text)

        # [Reshape M6.1 fourth wave / 2026-05-24] MOOD ESTIMATE helper. 行为不变.
        _mood_block_text = self._build_mood_estimate_block()
        if _mood_block_text:
            _parts.append(_mood_block_text)

        # [Reshape M6.1 fourth wave / 2026-05-24] WAKE CONTEXT helper. 行为不变.
        _wake_block_text = self._build_wake_context_block()
        if _wake_block_text:
            _parts.append(_wake_block_text)
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
            # 🆕 [P1 / Sir 2026-05-25 22:10] Layer 1.5 Inner Thoughts (主脑碎碎念)
            _L1bc = len(inner_thoughts_block)
            _L2c = len(relational_block)
            _L3c = len(attention_block)
            _total_soul = _L0c + _L1c + _L1bc + _L2c + _L3c
            # 🆕 [P5-Gap4-followup / 2026-05-21 21:20] 加 concern_reason 标记
            # silent / summon / urgent / preflight_fail 让 Sir grep 看 concern 注入原因
            _concern_reason = getattr(self, '_soul_concern_inject_reason', '?')
            _bg_soul(
                f"🪞 [SOUL inject] L0={_L0c}c L1={_L1c}c L1.5={_L1bc}c "
                f"L2={_L2c}c L3={_L3c}c total={_total_soul}c "
                f"concern_reason={_concern_reason} | "
                f"jokes={_picked_jokes} "
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

        # 🆕 [P5-fix70 Phase 4a / 2026-05-23 17:01] Sir 17:01 拍板 — 砍 static block
        # 老 tier_routing 1862 chars (SIMPLE/COMPLEX 详细 example 1K+). 主脑已经
        # 学会 FAST_CALL 用法, 不需要每 turn 重看 example. 砍到 ~500 chars.
        tier_routing = self.prompt_cache.get_or_build(
            'tier_routing', lambda: """[ROUTING]: Tier 1 chat (no tool, end ---ZH--- + 中文). Tier 2 tools (<FAST_CALL>{...}</FAST_CALL>, 简单 action 直接调 + "Done"; 复杂 action 1 句 intro + 工具链 + 1 句总结). Tier 3 deep workflow (<REQUEST_PHYSICAL>).
- Pick: 单工具 + 无风险 → SIMPLE (no intro). 多工具/不可逆 → COMPLEX (1 句 intro). 不确定 → SIMPLE.
- Error: tool fail → 诚实承认 "That didn't take, Sir.". NEVER 说"已做"当 X 失败.
- 特殊: <IGNORE> side-conv, [CLIPBOARD] code at end.""",
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

        # [Reshape M6.1 / 2026-05-24] 3 stage 抽自 helper. 行为不变.
        _pc_block_value = self._build_profile_block_and_cache()
        self._refresh_habit_clock_from_probe()
        context_str = self._build_context_router_str(current_hour)

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
                # 🆕 [P5-fix70 Phase 4a / 2026-05-23 17:01] days=3 → days=2 缩 ~30%
                # life_log 是历史日志, 2 天足够主脑做 callback. 节省 ~700 chars.
                # 🆕 [Reshape M7 Phase 4c / 2026-05-24] narrative 截 200 char/day,
                # 主脑只需要日期 + 主题 + tag 做 callback, 不需要长篇日志. 减 ~500 chars.
                life_log_context = self.status_ledger.get_recent_daily_summaries(
                    days=2, max_chars_per_day=200)
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

        # [Reshape M6.1 / 2026-05-24] 3 stage 抽自 helper. 行为不变.
        unified_memory = self._build_unified_memory_block(
            user_input, _allow_full, _skip_heavy)
        skill_tree_str = self._build_skill_tree_block(_allow_full, _skip_heavy)
        anticipator_ctx = self._build_anticipator_block(_skip_heavy)

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

        # 🆕 [锚化 P1 / Sir 2026-06-01] 言出必行边界块 (data-driven from anchors.json).
        # 判据→边界 (charter §1/§3): persona 已有禁令(prohibition, 不可改红线 AGENTS §4.8);
        # 此处补 persona 缺的**建设性侧** —— 撞墙时的可行 move(问/hedge/沉默), 让主脑知道
        # "墙内有路", 减"我必须精确"式优化焦虑(H0 镜像那条 衡=filler 反刍的根)。
        # 关: anchors.json 把 say_do.prompt_inject 设 false。失败非致命 (空块)。
        anchor_boundary_block = ""
        try:
            import jarvis_anchors as _ja_p1
            anchor_boundary_block = _ja_p1.render_walls_block()
            # 🆕 [衡 H3 / Sir 2026-06-01] 附墙冲突时的逐案权衡指引 (无固定等级)
            _cg = _ja_p1.render_conflict_guidance()
            if _cg:
                anchor_boundary_block = (
                    (anchor_boundary_block + "\n\n" + _cg).strip()
                )
            # 🆕 [inner-anchor-P1 / Sir 2026-06-07] affordance 自知 (许可诚实承认能力边界).
            # 接地源=能力注册表/执行trace (非对话边); 框成许可承认非驱动揽活 (§6.3)。
            try:
                import jarvis_affordance as _aff
                _ab = _aff.render_affordance_block()
                if _ab:
                    anchor_boundary_block = (
                        (anchor_boundary_block + "\n\n" + _ab).strip()
                    )
            except Exception:
                pass
        except Exception:
            anchor_boundary_block = ""

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

✅ DELIVERY 原则 (主脑自决用词, 无填空模板):
   - present-tense imperative — 现在式祈使句, 不是 past 也不是 future
   - ≤ 2 sentences, ≤ 18 words English
   - extract action verb + object from "Sir's original request" (time anchor 后部分)
   - Do NOT re-confirm. Do NOT ask permission. Do NOT explain how you know.
   - 直接喊 Sir, 像旁边的人轻提一句 "时间到了 (此事)", 不预热不解释

================================================================================
"""
            # 🆕 [P5-fix56 / 2026-05-23 16:00] Phase 3a: REMINDER_FIRING 迁 builder
            try:
                from jarvis_prompt_builder import PromptBuilder, BlockSpec
                rb = PromptBuilder(tier='REMINDER_FIRING')
                rb.register(BlockSpec(
                    id='reminder_directive', content=reminder_firing_directive,
                    tiers=['REMINDER_FIRING'], salience=0.99))
                if context_str:
                    rb.register(BlockSpec(
                        id='context', content=context_str,
                        tiers=['REMINDER_FIRING'], salience=0.70))
                rb.register(BlockSpec(
                    id='clock', content=f"[SYSTEM CLOCK]: {current_time}",
                    tiers=['REMINDER_FIRING'], salience=0.85))
                if sensor_state_block:
                    rb.register(BlockSpec(
                        id='sensor', content=sensor_state_block,
                        tiers=['REMINDER_FIRING'], hint='sensor:<field>',
                        salience=0.80))
                return rb.compose(
                    persona=core_persona,
                    user_input=user_input,
                    footer='[BILINGUAL DIRECTIVE]: Speak English. Append `---ZH---` Chinese subtitle at the VERY END. This is MANDATORY.',
                    include_meta_hint=False,  # mail mode 极简, 不写 META
                )
            except Exception:
                # builder fail → fallback 老路径
                return f"""{core_persona}

{reminder_firing_directive}
{context_str}
[SYSTEM CLOCK]: {current_time}
{sensor_state_block}
[BILINGUAL DIRECTIVE]: Speak English. Append `---ZH---` Chinese subtitle at the VERY END. This is MANDATORY.
{user_input}
"""

        # [Reshape M6.2 second wave / 2026-05-24] FACTUAL_RECALL tier 抽 helper. 行为不变.
        if prompt_tier == self.PROMPT_TIER_FACTUAL_RECALL:
            return self._assemble_factual_recall_prompt(
                core_persona=core_persona,
                user_input=user_input,
                stm_context=stm_context,
                current_time=current_time,
                current_hour=current_hour,
                ledger_data=ledger_data,
                sensor_state_block=sensor_state_block,
                system_alert_text=system_alert_text,
                yesterday_block=yesterday_block,
                open_threads_block=open_threads_block,
                project_block=project_block,
                available_skills_block=available_skills_block,
            )

        # [Reshape M6.2 / 2026-05-24] WAKE_ONLY tier 抽 helper. 行为不变.
        if prompt_tier == self.PROMPT_TIER_WAKE_ONLY:
            return self._assemble_wake_only_prompt(
                core_persona, user_input, stm_context, current_time,
                sensor_state_block, system_alert_text)

        # [R6/Tier] SHORT_CHAT 中档：核心人设 + STM + ledger + event_bus；不带 LTM/skill_tree/anticipator
        # [P0+18-a.3 / 2026-05-15] 注入 PROMISE_PROTOCOL_DIRECTIVE_MINI — 修 BUG #2:
        # 之前 SHORT_CHAT tier 完全没注入 PROMISE 协议，导致 Sir 说"排查 403"等多步动作时
        # 主脑根本不知道要写 <PROMISE>，直接编答案 → Integrity Check 抓 hallucination
        # [Reshape M6.2 second wave / 2026-05-24] SHORT_CHAT tier 抽 helper. 行为不变.
        if prompt_tier == self.PROMPT_TIER_SHORT_CHAT:
            return self._assemble_short_chat_prompt(
                core_persona=core_persona,
                user_input=user_input,
                stm_context=stm_context,
                current_time=current_time,
                current_hour=current_hour,
                ledger_data=ledger_data,
                sensor_state_block=sensor_state_block,
                system_alert_text=system_alert_text,
                yesterday_block=yesterday_block,
                open_threads_block=open_threads_block,
                project_block=project_block,
                available_skills_block=available_skills_block,
                how_to_respond=how_to_respond,
                time_persona=time_persona,
                context_str=context_str,
                pc_block_value=_pc_block_value,
                correction_context=correction_context,
                style_adjustment=style_adjustment,
                ledger_str=ledger_str,
            )


        if mode == "light":
            # 🆕 [P5-fix56 / 2026-05-23 16:00] Phase 3a: light mode 迁 builder
            try:
                from jarvis_prompt_builder import PromptBuilder, BlockSpec
                lb = PromptBuilder(tier='LIGHT')
                if context_str:
                    lb.register(BlockSpec(
                        id='context', content=context_str,
                        tiers=['LIGHT'], salience=0.70))
                if _pc_block_value:
                    lb.register(BlockSpec(
                        id='profile_card', content=_pc_block_value,
                        tiers=['LIGHT'], hint='profile:<field>', salience=0.75))
                if correction_context:
                    lb.register(BlockSpec(
                        id='correction', content=correction_context,
                        tiers=['LIGHT'], salience=0.80))
                if style_adjustment:
                    lb.register(BlockSpec(
                        id='style', content=style_adjustment,
                        tiers=['LIGHT'], salience=0.60))
                if content_pref:
                    lb.register(BlockSpec(
                        id='content_pref', content=content_pref,
                        tiers=['LIGHT'], salience=0.60))
                lb.register(BlockSpec(
                    id='clock', content=f"[SYSTEM CLOCK]: {current_time}",
                    tiers=['LIGHT'], salience=0.85))
                if sensor_state_block:
                    lb.register(BlockSpec(
                        id='sensor', content=sensor_state_block,
                        tiers=['LIGHT'], hint='sensor:<field>', salience=0.85))
                _l2 = getattr(self, '_l2_injected_block', '') or ''
                if _l2:
                    lb.register(BlockSpec(
                        id='l2', content=_l2,
                        tiers=['LIGHT'], hint='l2:<directive_id>', salience=0.70))
                return lb.compose(
                    persona=core_persona,
                    user_input=user_input,
                    system_alert=system_alert_text,
                    include_meta_hint=True,  # light mode 允许 META 自检
                )
            except Exception:
                # fallback 老路径
                return f"""{core_persona}

{context_str}
{_pc_block_value}
{correction_context}
{style_adjustment}
{content_pref}
[SYSTEM CLOCK]: {current_time}
{sensor_state_block}
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

        # [Reshape M1.3-min / 2026-05-24] 装 prompt_evidence_log
        # 主脑读了这些 SWM evidence (event_bus / swm_block), 主脑 reply 后
        # chat_bypass.stream_chat 末尾用这个 dict 填 record_decision.prompt_evidence_log.
        # 反向追溯: reply → decision → 这里 evidence_id → 各 publisher source row.
        try:
            bus = getattr(self, 'event_bus', None)
            if bus is not None and hasattr(bus, 'collect_evidence_ids'):
                _evidence_log = {}
                if event_bus_block:
                    _evidence_log['swm_conversation_360s'] = bus.collect_evidence_ids(within_seconds=360.0)
                if swm_block:
                    # to_swm_block 用 top_n + salience_floor=0.3, 这里 collect 同 window
                    _evidence_log['swm_high_salience_pool'] = bus.collect_evidence_ids(within_seconds=900.0)
                self._last_prompt_evidence_log = _evidence_log
        except Exception:
            self._last_prompt_evidence_log = {}

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

        # 🆕 [P5-fix53 / 2026-05-23] sensor_state_block 已在 _assemble_prompt 顶部
        # (L1540) 定义, 所有 tier 短路 return 之前可用. 此处不再重复.
        # 详 jarvis_sensor_state_block.py + memory_pool/sensor_state_inject_vocab.json

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

        # 🆕 [Translator Phase 2 / 2026-05-24 21:00] L4.6 schema examples 注入主脑 prompt
        # 详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md
        # 让主脑 emit FAST_CALL 时知道每个 hand 必填 params + example, 减翻译层 BUG.
        translator_schema_block = ""
        try:
            _tr = getattr(self, 'translator', None)
            if _tr is not None:
                translator_schema_block = _tr.render_prompt_block(max_chars=1500)
        except Exception:
            translator_schema_block = ""

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

{anchor_boundary_block}

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

{translator_schema_block}

[YOUR KNOWLEDGE BASE]:
--- Long-Term Memory ---
{ltm_context}

{commitment_context}
[SYSTEM CLOCK]: {current_time}
{sensor_state_block}
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
            'translator_schema': len(translator_schema_block),  # Translator Phase 2
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

        # 🆕 [P5-fix61/64/66 / 2026-05-23 16:18-16:40] Phase 3d.1/2/3:
        # standard/full mode 集成 PromptBuilder. 字面零变化 (output = legacy mega).
        # 3d.1 (61): builder wrapper 路径集成
        # 3d.2 (64): mega block + metadata + audit_summary bg_log
        # 3d.3 (66): 注册 5 audit-only logical sections (Phase 4 瘦身规划基础)
        #            audit_only=True → 不渲染, 仅 audit. legacy mega 仍是真输出.
        # fallback: builder 异常 → 直接 return result (准则 8 不破现有).
        try:
            from jarvis_prompt_builder import PromptBuilder, BlockSpec
            _sb = PromptBuilder(tier='STANDARD')

            # 🆕 [P5-fix66] 注册 5 audit-only logical sections (Phase 4 用)
            # 这些 block 不渲染 (audit_only=True), 仅 audit_summary 用. Phase 4
            # 把 audit_only=False 改 True + 删 legacy = 真拆细 + tier filter 砍.
            _l2_inj = getattr(self, '_l2_injected_block', '') or ''
            _audit_sections = [
                # Section 1: persona (核心人设)
                ('persona_section', core_persona, 1.0,
                  'persona — 核心人设 + 风格基线'),
                # Section 2: recent (历史/STM/continuity/open_threads/project/active_reminders)
                ('recent_section', '\n\n'.join(filter(bool, [
                    yesterday_block,
                    f"=== WHAT JUST HAPPENED ===\n{stm_context}" if stm_context else '',
                    open_threads_block, project_block, active_reminders_block,
                ])), 0.80, 'recent — 历史 + STM + open threads + projects'),
                # Section 3: skills + directives
                ('skills_section', '\n\n'.join(filter(bool, [
                    available_skills_block, tool_honesty_directive,
                    fuzzy_candidates_policy, promise_protocol_directive,
                    anchor_boundary_block,  # 🆕 [锚化 P1] 言出必行边界+可行选项
                ])), 0.75, 'skills — 可用工具 + honesty/fuzzy/promise 协议 + 言出必行边界'),
                # Section 4: state + style (SWM + 多 sensor block + 风格)
                ('state_section', '\n\n'.join(filter(bool, [
                    swm_block, event_bus_block, attention_block,
                    working_feed_block, active_plan_block,
                    tone_directive, avoid_phrases_block, verbosity_block,
                    soul_chapters_str, how_to_respond,
                    f"=== TIME CONTEXT ===\n{time_persona}" if time_persona else '',
                    context_str, _pc_block_value,
                    correction_context, style_adjustment, content_pref,
                    unified_memory, skill_tree_str, anticipator_ctx,
                ])), 0.70, 'state — SWM/event/attention + tone/style/soul + time/context'),
                # Section 5: knowledge + tail (real_time/life_log/sys_env/tools/ltm/commitment/clock/sensor/l2)
                ('knowledge_tail_section', '\n\n'.join(filter(bool, [
                    f"=== REAL-TIME STATE ===\n{ledger_str}" if ledger_str else '',
                    f"[RECENT LIFE LOG]:\n{life_log_context}" if life_log_context else '',
                    f"[SYSTEM ENVIRONMENT]:\n{landmarks_str}" if landmarks_str else '',
                    tier_routing,
                    f"[Tier 2 Tool Library]:\n{chat_organs}" if chat_organs else '',
                    f"[YOUR KNOWLEDGE BASE]:\n{ltm_context}" if ltm_context else '',
                    commitment_context,
                    f"[SYSTEM CLOCK]: {current_time}",
                    sensor_state_block, _l2_inj,
                ])), 0.65, 'knowledge_tail — ledger/life_log/env/tools/ltm/clock/sensor/l2'),
            ]
            for sid, content, sal, desc in _audit_sections:
                if content:
                    _sb.register(BlockSpec(
                        id=sid, content=content, tiers=['STANDARD'],
                        salience=sal, audit_only=True,  # 不渲染
                        metadata={'section': sid.replace('_section', ''),
                                   'desc': desc, 'phase': '3d.3'},
                    ))

            # legacy mega block (audit_only=False → 真渲染)
            _sb.register(BlockSpec(
                id='legacy_full', content=result.strip(),
                tiers=['STANDARD'], salience=1.0, audit_only=False,
                metadata={'phase': '3d.3', 'split_method': '5_audit_sections',
                           'render_path': 'mega_passthrough'},
            ))

            _via_builder = _sb.compose(
                persona='',
                user_input='',
                footer='',
                system_alert='',
                include_meta_hint=False,
            )
            # 安全闸: builder 输出含 user_input → 接受
            if _via_builder and user_input and user_input in _via_builder:
                result = _via_builder
            # 🆕 [Phase 3d.3] audit bg_log — 5 section 体积分布 (Phase 4 砍依据)
            try:
                from jarvis_utils import bg_log as _bd_bg
                # audit_summary 不包 audit_only blocks (list_block_ids 用 active)
                # → 用 size_breakdown 手动遍 audit_only blocks 统计
                _audit_sizes = [(bid, _sb.get(bid).char_len())
                                  for bid in ['persona_section',
                                                'recent_section',
                                                'skills_section',
                                                'state_section',
                                                'knowledge_tail_section']
                                  if _sb.get(bid) is not None]
                _audit_sizes.sort(key=lambda x: x[1], reverse=True)
                _total_audit = sum(c for _, c in _audit_sizes)
                _top3 = ', '.join(f"{n}={c}" for n, c in _audit_sizes[:3])
                _bd_bg(
                    f"📐 [PromptBuilder/STANDARD] legacy_mega={_sb.get('legacy_full').char_len()} chars "
                    f"| audit_sections_total={_total_audit} | top3: {_top3}"
                )
            except Exception:
                pass
        except Exception:
            pass  # fallback 老 result

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
            # 🆕 [Gap-Z5 / β.5.46-fix8] 用 search_memory_default 带 time decay
            # 30 天前 memory 自动衰减, 主脑不被远古无关 memory 干扰 attention.
            # config 在 memory_pool/hippocampus_decay_config.json
            results = self.hippocampus.search_memory_default(
                self.gemini_key, search_query, top_k=3
            )
            
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
            # [BUG #5 Sir 2026-05-28 22:50 fix49] defensive: 镜像/fresh install/Sir 误删
            # 任一 pool 目录都不应让整个 nerve init 崩. 缺 dir 就 noop, 继续启动.
            if not os.path.isdir(folder):
                return
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

    # 🆕 [Reshape M3.G 真删 / 2026-05-24 17:00] CentralNerve.run() 已彻底删除.
    #
    # 历史: 3-brain (RightBrain/LeftBrain/L5Brain) 364 行 task flow.
    # Sir 真测 deprecated_3_brain_invoked SWM event = 0 → 主脑 prompt 不再 emit
    # <ENGAGE_PHYSICAL_BODY> token → route_callback 永不触发 → 此 method 永不被调.
    #
    # 物理删除路径:
    #   1. CentralNerve.run() deprecated stub 删 (本处)
    #   2. CentralNerve._init_3_brain_legacy 删
    #   3. CentralNerve 顶部 RightBrain/LeftBrain/L5Brain = None 声明删
    #   4. worker.trigger_routing 删 + stream_chat route_callback=None
    #
    # 历史代码 archive: `_legacy/3_brain_attempt/central_nerve_run_v1.py`

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
        # 🩹 [β.5.46-fix15 / 2026-05-22] Sir 10:59 真测 BUG: 287K 行 spam (99.9% log).
        # 第二道防线 cooldown — 即使 SmartNudge 误调多次, 此处也 30s 内只 print 1 次.
        # 系统级常量 (准则 6 β.3.5 递归边界), 不 vocab 化.
        _now = time.time()
        if getattr(self, '_last_activity_wake_print', 0) > 0 and \
           (_now - self._last_activity_wake_print) < 30:
            return
        self._last_activity_wake_print = _now
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
        # 🆕 [β.5.46-fix13 Fix-1.1 / 2026-05-22] 看 sleep_routine 真 fire evidence
        # Sir 00:30 真测 (B5/B9): dismissal_soft 立刻 activate_sleep_mode 但 Sir
        # 还在打字 4min 后被质疑 "did you not fall asleep?". 真凶: sleep_duration
        # 用 _sleep_activated_at 算, 但那是"表态时", 不是 Sir "真睡时".
        # 治本: 看 NudgeGate.is_sleep_routine_fired() — routine 真 fire = audio
        # mute + display sleep + ASR mute 全完, 才算 Sir "真睡". 没 fire = 光表态
        # → 不质疑.
        try:
            _gate_fix11 = getattr(self, 'nudge_gate', None)
            if _gate_fix11 is not None and hasattr(_gate_fix11, 'is_sleep_routine_fired'):
                if not _gate_fix11.is_sleep_routine_fired():
                    try:
                        from jarvis_utils import bg_log as _bg11
                        _bg11(
                            f"🛌 [SleepDetector/Skip] sleep_routine 还没 fire — "
                            f"Sir 只表态没真睡 ({sleep_duration:.0f}s), 不质疑"
                        )
                    except Exception:
                        pass
                    return
        except Exception:
            pass
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
    if not _jarvis_is_mirror_mode():
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

