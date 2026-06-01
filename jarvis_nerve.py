# =============================================================================
# 🚀 JARVIS NERVE — 主入口 + 转发垫层
# =============================================================================
# [P0+19 / 2026-05-16] 本文件曾达 17479 行；现在已拆为 16 个独立文件 + < 500 行入口
#
# 拆分历史（按完工顺序）：
#   P0+19-1   → jarvis_safety.py            (反幻觉守卫 / 12 helper)
#   P0+19-2   → jarvis_key_router.py        (API Key 路由)
#                jarvis_llm_reflector.py    (共享 LLM 反思引擎)
#                jarvis_env_probe.py        (物理环境感知)
#   P0+19-3   → jarvis_sensors.py           (6 个感知类)
#   P0+19-4   → jarvis_routing.py           (路由 + 三 Center)
#   P0+19-5   → jarvis_memory_core.py       (12 个记忆/纠错/睡意类)
#   P0+19-6.a → jarvis_sentinels.py         (9 个普通守护线程)
#   P0+19-6.b → jarvis_conductor.py         (指挥官)
#   P0+19-6.c → jarvis_return_sentinel.py   (回归哨兵)
#   P0+19-6.d → jarvis_commitment_watcher.py (承诺守望)
#   P0+19-6.e → jarvis_smart_nudge.py       (智能轻推)
#   P0+19-7   → jarvis_chat_bypass.py       (主对话循环)
#   P0+19-8   → jarvis_central_nerve.py     (主脑 + CORE_PERSONA)
#   P0+19-9   → jarvis_worker.py            (PyQt5 QThread)
#                jarvis_ui.py               (PyQt5 + OpenGL UI)
#
# 新代码请直接 `from jarvis_xxx import Y`，不要再往本文件加东西。
# 本文件仅承担：(1) __main__ 启动入口 + (2) 旧 `from jarvis_nerve import X` 转发垫层。
# =============================================================================

import win32gui
import io
import re
import numpy as np
import soundfile as sf
import json
import concurrent.futures
from funasr import AutoModel
from PIL import ImageGrab, Image
import os
import random
import sys
import math
import threading
import queue
import sqlite3
# [Sir 2026-05-28 22:42 fix49 BUG #2 mirror cosyvoice import gate]
# Mirror 没复制 CosyVoice/ 目录 (launcher DEFAULT_IGNORE_NAMES 跳了, 500MB 模型权重不需要镜像).
# 真 VocalCord 顶 import cosyvoice 会 ModuleNotFoundError 杀进程, except 块 print '❌' 又 GBK 二崩.
# Mirror gate: JARVIS_MIRROR=1 改用 MockVocalCord (API 100% 兼容: speak/say/render_only/play_only/stop_immediately).
# 主进程链路 0 变化.
if os.environ.get('JARVIS_MIRROR') == '1':
    from jarvis_mirror_mode import MockVocalCord as VocalCord
else:
    from jarvis_vocal_cord import VocalCord
import speech_recognition as sr
import comtypes
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QPainter, QColor, QRadialGradient
from fuzzywuzzy import fuzz
# [C1-7 / 2026-05-15] 删除未使用的 difflib import（全文件零调用）
import time
import importlib
import multiprocessing 
from dataclasses import dataclass, field
from jarvis_blood import JarvisBlood, ExecutionResult
from jarvis_blood import FeedbackSignal  # P0+13 双定义合并 + P0+19-5 拆分后保留顶部 import 兼容（测试源码扫描要求独立成行）
# 🆕 [Reshape M3.F / 2026-05-24] 3-brain 已 mv 到 _legacy/3_brain_attempt/.
# 顶部 try/except import 全删, 主对话 100% 走 chat_bypass.stream_chat 单脑.
RightBrain = None  # type: ignore
LeftBrain = None  # type: ignore
ReflectionBrain = None  # type: ignore
from jarvis_hippocampus import Hippocampus
from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion
from google import genai
from jarvis_utils import safe_gemini_call, get_local_fallback, safe_openrouter_call, QuickClassifier, get_quick_classifier, create_genai_client
from google.genai import types 
# 👇 新增：用于自主神经系统的物理探针底层库
import win32api
import win32con
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation
# [C1-7 / 2026-05-15] 删除重复 import：threading / queue / comtypes / pycaw
# 上面 line 14-19 已经导入过。pycaw 第二次 import 还少了 IAudioMeterInformation 是 bug。
# 🌐 【物理世界网络总闸】：强行统一下游所有器官的 TLS/SSL 加密信道
# [Reshape M3.A / 2026-05-24] 单源走 jarvis_config/network.json (准则 6 持久化).
# Sir 改 proxy 不必改源码, 改 network.json 即可. fallback 老硬编码保 backward compat.
try:
    from jarvis_utils import _PROXY_URL as _PROXY_URL_FROM_CONFIG
    os.environ["HTTP_PROXY"] = _PROXY_URL_FROM_CONFIG
    os.environ["HTTPS_PROXY"] = _PROXY_URL_FROM_CONFIG
except Exception:
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
# ==========================================
# 🧬 自主神经底层基建 (Autonomic Subsystem)
# ==========================================

# ==========================================
# 🔒 J.A.R.V.I.S. 核心人设 — 不可变，写死，任何模块不得修改
# ==========================================
# 🔒 [P0+19-8 / 2026-05-16] JARVIS_CORE_PERSONA 已搬到 jarvis_central_nerve.py
from jarvis_central_nerve import JARVIS_CORE_PERSONA


# ==========================================
# 🛡️ [P0+19-1 / 2026-05-16] Memory Deletion 守卫已拆到 jarvis_safety.py
# ==========================================
# 原内容（_REFERENCE_TOKENS / _strip_reference_tokens / _is_reference_only_hint /
# _PHYSICAL_FILE_DELETE_MARKERS / _is_physical_file_delete_intent）+ 完整历史 marker
# 已搬到 `jarvis_safety.py`。本处转发垫层保证：
# - `from jarvis_nerve import _is_reference_only_hint` 等旧 import 0 改动
# - 后续 nerve 内部 `_is_xxx(...)` 直接调用 0 改动
from jarvis_safety import (
    _REFERENCE_TOKENS,
    _strip_reference_tokens,
    _is_reference_only_hint,
    _PHYSICAL_FILE_DELETE_MARKERS,
    _is_physical_file_delete_intent,
    # [P0+19-1 第二段 / 2026-05-16] _box_newline / 结构化标签 / 中文检测
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


# ==========================================
# 📍 修改目标位置: jarvis_nerve.py (替换整个 PhysicalEnvironmentProbe 类)
# ==========================================
import collections # 确保文件顶部有这行

# ==========================================
# 🚂 [P0+19-2 / 2026-05-16] 基础设施层已拆到独立文件
# ==========================================
# 原内容（行 130-1286, 1157 行 / KeyRouter + LlmReflector + PhysicalEnvironmentProbe）
# 已搬到：
#   - jarvis_key_router.py     (KeyRouter / API Key 路由 + 启动诊断探针 / 365 行)
#   - jarvis_llm_reflector.py  (LlmReflector / 共享 LLM 反思引擎 / 182 行)
#   - jarvis_env_probe.py      (PhysicalEnvironmentProbe / 物理环境感知 / 696 行)
# 转发垫层保证 `from jarvis_nerve import KeyRouter / LlmReflector / PhysicalEnvironmentProbe` 0 改动
from jarvis_key_router import KeyRouter
from jarvis_llm_reflector import LlmReflector
from jarvis_env_probe import PhysicalEnvironmentProbe

# ==========================================
# 🌡️ [P0+19-3 / 2026-05-16] 传感/感知/工具类已拆到 jarvis_sensors.py
# ==========================================
# 原内容（行 143-1085, 944 行 / FunnelLogger + SensorFilter + HabitClock +
# CausalChain + ProjectTimeline + SubconsciousMailbox）已搬到 `jarvis_sensors.py`。
# 转发垫层保证旧 `from jarvis_nerve import SensorFilter / HabitClock / ...` 0 改动。
from jarvis_sensors import (
    FunnelLogger,
    SensorFilter,
    HabitClock,
    CausalChain,
    ProjectTimeline,
    SubconsciousMailbox,
)

# 📍 修改目标文件: jarvis_nerve.py (替换整个 ChronosTick 类)
# ==========================================
# ==========================================
# 🛡️ [P0+19-6.a / 2026-05-16] 5 个普通 sentinel 已拆到 jarvis_sentinels.py (段 A)
# ==========================================
# 原内容（行 161-781, 621 行 / ChronosTick + ChronosSentinel + SystemSentinel +
# SoulArchivistSentinel + NudgeGate）
from jarvis_sentinels import (
    ChronosTick,
    ChronosSentinel,
    SystemSentinel,
    SoulArchivistSentinel,
    NudgeGate,
)

# 🎼 [P0+19-6.b / 2026-05-16] Conductor (722 行) → jarvis_conductor.py
from jarvis_conductor import Conductor


# 🎼 [P0+19-6.f / 2026-05-16] 三 Center → jarvis_routing.py 末尾
from jarvis_routing import PromptCenter, GuardianCenter, CompanionCenter

# ==========================================
# 🛡️ [P0+19-6.a / 2026-05-16] 4 个普通 sentinel 已拆到 jarvis_sentinels.py (段 B)
# ==========================================
# 原内容（行 1615-2317, 703 行 / UserStatusLedgerSentinel + ScreenshotSentinel +
# WellnessGuardian + ReflectionScheduler）
from jarvis_sentinels import (
    UserStatusLedgerSentinel,
    ScreenshotSentinel,
    WellnessGuardian,
    ReflectionScheduler,
)

# 🔄 [P0+19-6.c / 2026-05-16] ReturnSentinel (711 行) → jarvis_return_sentinel.py
from jarvis_return_sentinel import ReturnSentinel

# 📌 [P0+19-6.d / 2026-05-16] CommitmentWatcher (554 行) → jarvis_commitment_watcher.py
from jarvis_commitment_watcher import CommitmentWatcher

# 💡 [P0+19-6.e / 2026-05-16] SmartNudgeSentinel (548 行) → jarvis_smart_nudge.py
from jarvis_smart_nudge import SmartNudgeSentinel

# 💬 [P0+19-7 / 2026-05-16] ChatBypass (3003 行) + _C3_ACTION_HAND_COMMANDS → jarvis_chat_bypass.py
from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS

# ==========================================
# 🧭 [P0+19-4 / 2026-05-16] 路由/画像类已拆到 jarvis_routing.py
# ==========================================
# 原内容（行 7354-8064, 711 行 / SoulRouter + ContextRouter + ContentPreferenceTracker + ProfileCard）
# 已搬到 `jarvis_routing.py`。转发垫层保证旧 `from jarvis_nerve import SoulRouter / ...` 0 改动。
from jarvis_routing import (
    SoulRouter,
    ContextRouter,
    ContentPreferenceTracker,
    ProfileCard,
)

# ==========================================
# 🧠 [P0+19-5 / 2026-05-16] 记忆/纠错/睡意 11 类已拆到 jarvis_memory_core.py
# ==========================================
# 原内容（行 7367-8256, 890 行 / PromptLayer + PromptCache + CorrectionEntry +
# CorrectionMemory + MemoryFragment + UnifiedMemoryGateway + FeedbackTracker +
# TaskWorkerPool + Anticipator + CorrectionLoop + SleepIntentDetector）
# 已搬到 jarvis_memory_core.py。
from jarvis_memory_core import (
    PromptLayer,
    PromptCache,
    CorrectionEntry,
    CorrectionMemory,
    MemoryFragment,
    UnifiedMemoryGateway,
    FeedbackTracker,
    TaskWorkerPool,
    Anticipator,
    CorrectionLoop,
    SleepIntentDetector,
)

# 🧠 [P0+19-8 / 2026-05-16] CentralNerve (2089 行) → jarvis_central_nerve.py
from jarvis_central_nerve import CentralNerve

# 🪟 [P0+19-9 / 2026-05-16] Worker + UI 已拆到独立文件
from jarvis_worker import VoiceListenThread, JarvisWorkerThread
from jarvis_ui import SubtitleOverlay, BreathingLightUI

# 🪞 [Sir 2026-05-28 22:00 fix49 mirror P2 hook-2] Agent Mirror Testing
# `JARVIS_MIRROR=1` 镜像 subprocess 才生效, 主进程 0 影响.
# 详 docs/JARVIS_AGENT_MIRROR_TESTING.md + jarvis_mirror_mode.py
from jarvis_mirror_mode import (
    is_mirror_mode as _is_mirror_mode,
    write_mirror_meta as _write_mirror_meta,
    MirrorBreathingLightUI as _MirrorBreathingLightUI,
    MirrorSubtitleOverlay as _MirrorSubtitleOverlay,
    create_mirror_voice_worker as _create_mirror_voice_worker,
)

# 🔑 [P0+19-deps / 2026-05-16] API key loader —— 只从 .env 读，绝不硬编码
from jarvis_config.keys import load_keys

# 🧬 [P0+20-W.2 / 2026-05-16] TraceContext — 进程级 session_id（日志可追溯起点）
from jarvis_utils import TraceContext

if __name__ == "__main__":
    multiprocessing.freeze_support()

    # 🧬 [P0+20-W.2 / 2026-05-16] 启动序列第一步：开 session
    # 之后所有 bg_log 自动带 [sess_xxx] 前缀，grep 一个 session_id 拿一次启动的全链路
    _session_id = TraceContext.init_session()
    print(f"🧬 [TraceContext] session 开启: {_session_id}")

    keys = load_keys()

    key_router = KeyRouter(
        main_brain_key=keys.OPENROUTER_MAIN,
        google_keys=keys.GOOGLE_LIST,
        openrouter_keys=keys.OPENROUTER_LIST,
    )

    # [P0+18-b.5 / 2026-05-15] 启动后 2s 跑一次三 Key 探针，
    # 若 3 个 Google Key 全部 PROJECT_DENIED 会清晰告诉 Sir "同一 Project 等于一 Key"
    key_router.probe_google_keys_at_startup(async_mode=True)
    
    app = QApplication(sys.argv)

    # 🪞 [Sir 2026-05-28 22:00 fix49 mirror P2 hook-2] 镜像 mode 早写 meta
    # Cascade 看 _mirror_meta.json 知道镜像就绪 (pid / cwd / task / start_ts)
    _MIRROR = _is_mirror_mode()
    if _MIRROR:
        _write_mirror_meta()

    if _MIRROR:
        ui = _MirrorBreathingLightUI()  # no-op, 不抢 OpenGL / 不显示窗口
        print("🪞 [mirror_mode] BreathingLightUI replaced by no-op stub")
    else:
        ui = BreathingLightUI()
        ui.show()

    jarvis_worker = JarvisWorkerThread(api_key=keys.OPENROUTER_MAIN, gemini_key=keys.GEMINI, key_router=key_router)
    jarvis_worker.state_changed.connect(ui.change_state)
    jarvis_worker.start()

    if _MIRROR:
        subtitle_overlay = _MirrorSubtitleOverlay(ui)  # 字幕事件全转 _mirror_output.jsonl
        print("🪞 [mirror_mode] SubtitleOverlay replaced by no-op stub (events → _mirror_output.jsonl)")
    else:
        subtitle_overlay = SubtitleOverlay(ui)
    jarvis_worker.jarvis.chat_bypass.subtitle_queue = subtitle_overlay.subtitle_queue
    jarvis_worker.subtitle_overlay = subtitle_overlay
    
    screenshot_sentinel = ScreenshotSentinel()
    screenshot_sentinel.start()
    
    status_ledger = UserStatusLedgerSentinel(key_router=key_router, central_nerve=jarvis_worker.jarvis, screenshot_sentinel=screenshot_sentinel)
    status_ledger.start()
    
    jarvis_worker.status_ledger = status_ledger
    jarvis_worker.jarvis.status_ledger = status_ledger
    
    jarvis_worker.jarvis.conductor = jarvis_worker.jarvis.guardian_center.conductor
    if jarvis_worker.jarvis.conductor:
        jarvis_worker.jarvis.conductor.set_screenshot_sentinel(screenshot_sentinel)
    jarvis_worker.jarvis.reflection_scheduler = jarvis_worker.jarvis.prompt_center.reflection_scheduler
    jarvis_worker.jarvis.commitment_watcher = jarvis_worker.jarvis.guardian_center.commitment_watcher
    
    # [P0+14 / 2026-05-15] HumorMemory 共享单例 —— 复用 CentralNerve 创建的实例，
    # 不再 new 一份。SmartNudge 已在 CompanionCenter.start_all 收到同一对象。
    humor_memory = jarvis_worker.jarvis.humor_memory
    jarvis_worker.humor_memory = humor_memory
    
    if _MIRROR:
        # mirror: 不开麦克风 / funasr / 唤醒检测; poll _mirror_input.jsonl 模拟 Sir 输入
        voice_worker = _create_mirror_voice_worker(poll_interval=0.5)
        print("🪞 [mirror_mode] VoiceListenThread replaced by MirrorVoiceWorker (polling _mirror_input.jsonl)")
    else:
        voice_worker = VoiceListenThread()
    voice_worker.return_sentinel = jarvis_worker.jarvis.guardian_center.return_sentinel
    voice_worker.interrupt_signal.connect(jarvis_worker.interrupt_all)
    voice_worker.text_ready.connect(jarvis_worker.push_command)
    voice_worker.awake_signal.connect(ui.set_awake_status)
    voice_worker.awake_signal.connect(jarvis_worker.set_awake_status)
    
    jarvis_worker.state_changed.connect(voice_worker.set_speaking_state)
    jarvis_worker.voice_thread = voice_worker
    jarvis_worker.jarvis.voice_thread = voice_worker
    # [R7-α/B1] 把 voice_thread 也挂到中央状态机，让 in_active_conversation 一路走 state
    voice_worker.state = jarvis_worker.state
    # 把 voice_thread 此前的本地 _local_in_active_conv 同步到 state 一次，防止首启时不一致
    if voice_worker.state is not None:
        voice_worker.state.set_active_conversation(
            voice_worker._local_in_active_conv,
            reason='init', source='main.wire_voice_state'
        )
    # [R7-α/AttentionContext] 创建一个共享 attention slot；voice_worker 写、jarvis_worker 读
    try:
        from jarvis_utils import AttentionSlot
        _attn_slot = AttentionSlot(
            window_history_provider=lambda: PhysicalEnvironmentProbe.window_history,
            max_age_seconds=8.0,
        )
        voice_worker._attention_slot = _attn_slot
        jarvis_worker._attention_slot = _attn_slot
        jarvis_worker.jarvis._attention_slot = _attn_slot
    except Exception as _e:
        print(f"[Attention] 注入失败：{_e}")

    # [R7-β5] 注入 subtitle_queue 引用，让 VoiceListenThread 能 push listening_start/done
    try:
        voice_worker._subtitle_queue = jarvis_worker.chat_bypass.subtitle_queue
    except Exception:
        voice_worker._subtitle_queue = None

    voice_worker.start()
    sys.exit(app.exec_())