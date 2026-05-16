# -*- coding: utf-8 -*-
"""[P0+19-6.a / 2026-05-16] 切 9 个普通 sentinel → jarvis_sentinels.py

两段：
  段 A (lines 161-781, 621 行): ChronosTick + ChronosSentinel + SystemSentinel +
                                 SoulArchivistSentinel + NudgeGate
  段 B (lines 1615-2317, 703 行): UserStatusLedgerSentinel + ScreenshotSentinel +
                                 WellnessGuardian + ReflectionScheduler
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class ChronosTick' in lines[160], f'Line 161 expected ChronosTick, got: {lines[160]!r}'
assert 'class NudgeGate' in lines[653], f'Line 654 expected NudgeGate, got: {lines[653]!r}'
assert 'class Conductor' in lines[781], f'Line 782 expected Conductor, got: {lines[781]!r}'
assert 'class UserStatusLedgerSentinel' in lines[1614], f'Line 1615 expected UserStatusLedgerSentinel, got: {lines[1614]!r}'
assert 'class ReflectionScheduler' in lines[2118], f'Line 2119 expected ReflectionScheduler, got: {lines[2118]!r}'
assert 'class ReturnSentinel' in lines[2317], f'Line 2318 expected ReturnSentinel, got: {lines[2317]!r}'

# 切片
section_a = ''.join(lines[160:781])     # ChronosTick ~ NudgeGate (5 类)
section_b = ''.join(lines[1614:2317])   # UserStatus ~ ReflectionScheduler (4 类)


HEADER = '''# -*- coding: utf-8 -*-
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

'''

ALL_BODY = HEADER + section_a + '\n\n# ' + '=' * 76 + '\n# B. 状态/截图/健康/反思 (UserStatusLedger + Screenshot + Wellness + ReflectionScheduler)\n# ' + '=' * 76 + '\n\n' + section_b

SENTINELS_PATH = os.path.join(ROOT, 'jarvis_sentinels.py')
with open(SENTINELS_PATH, 'w', encoding='utf-8') as f:
    f.write(ALL_BODY)
print(f'[P0+19-6.a] WROTE: jarvis_sentinels.py ({ALL_BODY.count(chr(10)) + 1} lines)')


# Patch nerve.py — 两段都替换
STUB_A = '''# ==========================================
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

'''

STUB_B = '''# ==========================================
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

'''

new_lines = lines[:160] + [STUB_A] + lines[781:1614] + [STUB_B] + lines[2317:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'[P0+19-6.a] nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
print('[P0+19-6.a] Done. Verify: python -c "import jarvis_nerve"')
