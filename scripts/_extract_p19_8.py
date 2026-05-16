# -*- coding: utf-8 -*-
"""[P0+19-8 / 2026-05-16] 切 CentralNerve + JARVIS_CORE_PERSONA → jarvis_central_nerve.py

- JARVIS_CORE_PERSONA: line 55+ (长字符串约 50 行)
- CentralNerve: lines 355-2443 (2089 行)
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert lines[54].startswith('JARVIS_CORE_PERSONA'), f'L55: {lines[54]!r}'
assert 'class CentralNerve:' in lines[354], f'L355 CentralNerve: {lines[354]!r}'
assert 'class VoiceListenThread' in lines[2443], f'L2444 VoiceListenThread: {lines[2443]!r}'

# 找 JARVIS_CORE_PERSONA 结束行（"""结束 — 紧跟一个空行）
persona_end = None
for i in range(55, 200):
    if lines[i].rstrip().endswith('"""'):
        persona_end = i + 1
        break
assert persona_end is not None, 'Cannot find JARVIS_CORE_PERSONA end'
print(f'JARVIS_CORE_PERSONA spans lines 55-{persona_end}')

persona_body = ''.join(lines[54:persona_end])      # JARVIS_CORE_PERSONA string
centralnerve_body = ''.join(lines[354:2443])        # CentralNerve class

HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-8 / 2026-05-16] CentralNerve + JARVIS_CORE_PERSONA — 主脑总控

从 jarvis_nerve.py 拆出 1 个超大类（2089 行）+ 不可变核心人设字符串。

CentralNerve 职责：
- 主对话编排（接 ChatBypass / Hippocampus / SmartNudge / Conductor 等）
- prompt 五档分级 (WAKE_ONLY / SHORT_CHAT / FACTUAL_RECALL / TOOL_REQUEST / DEEP_QUERY)
- _assemble_prompt 多层 prompt 装配（含 ACTIVE REMINDERS / WORKING FEED / 等）
- 三 Center 启动 (PromptCenter / GuardianCenter / CompanionCenter)

JARVIS_CORE_PERSONA：
- 不可变核心人设字符串（约 60 行）
- [INTEGRITY — ABSOLUTE] / [NUDGE / AGENDA HONESTY] 段定义反幻觉锚

向后兼容：jarvis_nerve.py 转发垫层 0 改动。
"""

from __future__ import annotations

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

# 跨文件依赖 — 所有上游已拆完
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
from jarvis_chat_bypass import ChatBypass  # noqa: F401

from jarvis_blood import JarvisBlood, ExecutionResult, FeedbackSignal  # noqa: F401
from jarvis_hippocampus import Hippocampus  # noqa: F401
from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401

'''

ALL_BODY = HEADER + persona_body + '\n\n' + centralnerve_body

OUT_PATH = os.path.join(ROOT, 'jarvis_central_nerve.py')
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write(ALL_BODY)
print(f'WROTE jarvis_central_nerve.py ({ALL_BODY.count(chr(10)) + 1} lines)')


# Patch nerve.py:
# - 删 line 55-persona_end (JARVIS_CORE_PERSONA)
# - 删 line 355-2443 (CentralNerve)
# - 在原 JARVIS_CORE_PERSONA 位置加 `from jarvis_central_nerve import JARVIS_CORE_PERSONA`
# - 在原 CentralNerve 位置加 `from jarvis_central_nerve import CentralNerve`

STUB_PERSONA = '''# 🔒 [P0+19-8 / 2026-05-16] JARVIS_CORE_PERSONA 已搬到 jarvis_central_nerve.py
from jarvis_central_nerve import JARVIS_CORE_PERSONA

'''

STUB_NERVE = '''# 🧠 [P0+19-8 / 2026-05-16] CentralNerve (2089 行) → jarvis_central_nerve.py
from jarvis_central_nerve import CentralNerve

'''

# new_lines = lines[:54] + STUB_PERSONA + lines[persona_end:354] + STUB_NERVE + lines[2443:]
new_lines = (
    lines[:54]
    + [STUB_PERSONA]
    + lines[persona_end:354]
    + [STUB_NERVE]
    + lines[2443:]
)
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
