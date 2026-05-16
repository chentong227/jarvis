# -*- coding: utf-8 -*-
"""[P0+19-9 / 2026-05-16] 切 Worker + UI → jarvis_worker.py + jarvis_ui.py

- worker: VoiceListenThread + JarvisWorkerThread (lines 308-3772, 3465 行)
- ui: SubtitleOverlay + BreathingLightUI (lines 3773-4464, 692 行)
- 保留 if __name__ == "__main__" (lines 4465+)
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class VoiceListenThread' in lines[307], f'L308: {lines[307]!r}'
assert 'class JarvisWorkerThread' in lines[965], f'L966: {lines[965]!r}'
assert 'class SubtitleOverlay' in lines[3772], f'L3773: {lines[3772]!r}'
assert 'class BreathingLightUI' in lines[4185], f'L4186: {lines[4185]!r}'
assert '__name__ == "__main__"' in lines[4464], f'L4465: {lines[4464]!r}'

worker_body = ''.join(lines[307:3772])    # VoiceListenThread + JarvisWorkerThread
ui_body = ''.join(lines[3772:4464])       # SubtitleOverlay + BreathingLightUI


WORKER_HEADER = '''# -*- coding: utf-8 -*-
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
from jarvis_central_nerve import CentralNerve, JARVIS_CORE_PERSONA  # noqa: F401

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

'''

UI_HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-9 / 2026-05-16] Jarvis UI — PyQt5 + OpenGL 视觉层

从 jarvis_nerve.py 拆出 2 个 UI 类：
  - SubtitleOverlay (413 行) — 字幕覆盖窗口
  - BreathingLightUI (279 行) — 呼吸灯 OpenGL 渲染窗口

依赖：
- PyQt5.QtWidgets.QWidget / QApplication
- PyQt5.QtCore: Qt / QTimer / pyqtSignal
- PyQt5.QtGui: QPainter / QColor / QRadialGradient
- PyQt5.QtOpenGL.QOpenGLWidget
- PyOpenGL (glVertex2f / glEnd / glUseProgram / 等)

向后兼容：jarvis_nerve.py 用 `from jarvis_ui import ...` 转发。
"""

from __future__ import annotations

import math
import time
import queue

from PyQt5.QtWidgets import QWidget, QApplication  # noqa: F401
from PyQt5.QtCore import Qt, QTimer, pyqtSignal  # noqa: F401
from PyQt5.QtGui import QPainter, QColor, QRadialGradient  # noqa: F401

# QOpenGLWidget 跨版本 import 兼容
try:
    from PyQt5.QtOpenGL import QOpenGLWidget  # noqa: F401
except ImportError:
    try:
        from PyQt5.QtWidgets import QOpenGLWidget  # noqa: F401
    except ImportError:
        QOpenGLWidget = QWidget  # 退化

# OpenGL
try:
    from OpenGL.GL import *  # noqa: F401, F403
except ImportError:
    pass  # 没装 PyOpenGL 时 BreathingLightUI 会跑时报错

'''

WORKER_PATH = os.path.join(ROOT, 'jarvis_worker.py')
with open(WORKER_PATH, 'w', encoding='utf-8') as f:
    f.write(WORKER_HEADER)
    f.write(worker_body)
print(f'WROTE jarvis_worker.py ({(WORKER_HEADER + worker_body).count(chr(10)) + 1} lines)')

UI_PATH = os.path.join(ROOT, 'jarvis_ui.py')
with open(UI_PATH, 'w', encoding='utf-8') as f:
    f.write(UI_HEADER)
    f.write(ui_body)
print(f'WROTE jarvis_ui.py ({(UI_HEADER + ui_body).count(chr(10)) + 1} lines)')


# Patch nerve.py
STUB = '''# 🪟 [P0+19-9 / 2026-05-16] Worker + UI 已拆到独立文件
from jarvis_worker import VoiceListenThread, JarvisWorkerThread
from jarvis_ui import SubtitleOverlay, BreathingLightUI

'''

new_lines = lines[:307] + [STUB] + lines[4464:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
