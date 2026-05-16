# -*- coding: utf-8 -*-
"""[P0+19-5 / 2026-05-16] 切分 jarvis_nerve.py 12 个记忆/纠错/睡意/幽默类 → jarvis_memory_core.py

两段：
  段 A: HumorMemory (lines 3577-3764, 188 行)
  段 B: PromptLayer ~ SleepIntentDetector (@dataclass 起, lines 7366-8255, 890 行)
    - PromptLayer, PromptCache (TTL 缓存)
    - CorrectionEntry, CorrectionMemory (纠错 SQLite)
    - MemoryFragment, UnifiedMemoryGateway (统一记忆访问)
    - FeedbackTracker (反馈追踪)
    - TaskWorkerPool (任务池)
    - Anticipator (threading.Thread — 记忆预加载)
    - CorrectionLoop (纠错闭环)
    - SleepIntentDetector (睡意意图)
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class HumorMemory:' in lines[3576], f'Line 3577 expected HumorMemory, got: {lines[3576]!r}'
assert 'class SmartNudgeSentinel' in lines[3764], f'Line 3765 expected SmartNudgeSentinel, got: {lines[3764]!r}'
assert '@dataclass' in lines[7365], f'Line 7366 expected @dataclass, got: {lines[7365]!r}'
assert 'class PromptLayer:' in lines[7366], f'Line 7367 expected PromptLayer, got: {lines[7366]!r}'
assert 'class CentralNerve:' in lines[8256], f'Line 8257 expected CentralNerve, got: {lines[8256]!r}'

# 切片
humor_body = ''.join(lines[3576:3764])      # 段 A
memory_body = ''.join(lines[7366:8256])     # 段 B (含 @dataclass + 11 类)


HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-5 / 2026-05-16] Jarvis Memory Core — 记忆/纠错/睡意/幽默类（12 类）

从 jarvis_nerve.py 拆出 12 个类，分两组：

A. 幽默 / 个性化记忆（与 SmartNudge 配对）：
  - HumorMemory (~188 行) — Sir 的笑点 + 已用 nudge 重复防御

B. 主脑记忆基础设施（CentralNerve 直接持有）：
  - PromptLayer + PromptCache (TTL 缓存)
  - CorrectionEntry + CorrectionMemory + CorrectionLoop (纠错三件套)
  - MemoryFragment + UnifiedMemoryGateway (统一记忆访问)
  - FeedbackTracker (用户反馈追踪)
  - TaskWorkerPool + Anticipator (记忆预加载线程)
  - SleepIntentDetector (睡意意图)

依赖：
- 标准库：time / re / json / sqlite3 / threading / queue / hashlib / os
- dataclass / field
- jarvis_blood.MemoryFragment (但本文件也定义 MemoryFragment, 注意可能重复 — 后续清理)
- jarvis_hippocampus.Hippocampus (UnifiedMemoryGateway / Anticipator 内部用)

向后兼容：jarvis_nerve.py 转发垫层保证旧 `from jarvis_nerve import HumorMemory / PromptCache / ...` 0 改动。
"""

from __future__ import annotations

import os
import re
import json
import time
import sqlite3
import threading
import queue
import hashlib
import random  # noqa: F401
import collections  # noqa: F401
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional  # noqa: F401

__all__ = [
    'HumorMemory',
    'PromptLayer',
    'PromptCache',
    'CorrectionEntry',
    'CorrectionMemory',
    'MemoryFragment',
    'UnifiedMemoryGateway',
    'FeedbackTracker',
    'TaskWorkerPool',
    'Anticipator',
    'CorrectionLoop',
    'SleepIntentDetector',
]


# ============================================================================
# A. HumorMemory — Sir 笑点 + nudge 重复防御
# ============================================================================

'''

# 拼接 memory body（含 @dataclass + 11 class）
ALL_BODY = HEADER + humor_body + '\n\n# ' + '=' * 76 + '\n# B. 主脑记忆基础设施（11 类）\n# ' + '=' * 76 + '\n\n' + memory_body

# 写 jarvis_memory_core.py
MEMORY_PATH = os.path.join(ROOT, 'jarvis_memory_core.py')
with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
    f.write(ALL_BODY)
print(f'[P0+19-5] WROTE: jarvis_memory_core.py ({ALL_BODY.count(chr(10)) + 1} lines)')


# Patch nerve.py — 两段都替换
STUB_A = '''# ==========================================
# 🎭 [P0+19-5 / 2026-05-16] HumorMemory 已拆到 jarvis_memory_core.py
# ==========================================
from jarvis_memory_core import HumorMemory

'''

STUB_B = '''# ==========================================
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

'''

# 新 nerve.py = lines[:3576] + STUB_A + lines[3764:7366] + STUB_B + lines[8256:]
new_lines = lines[:3576] + [STUB_A] + lines[3764:7366] + [STUB_B] + lines[8256:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'[P0+19-5] nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
print('[P0+19-5] Done. Verify: python -c "import jarvis_nerve"')
