# -*- coding: utf-8 -*-
"""[P0+19-3 / 2026-05-16] 切分 jarvis_nerve.py 行 143-1085 (6 个传感/工具类) → jarvis_sensors.py
   + patch nerve.py 加转发垫层。

包含 6 个类：
  - FunnelLogger (143-219, 77 行)
  - SensorFilter (220-486, 267 行)
  - HabitClock (487-714, 228 行)
  - CausalChain (715-906, 192 行)
  - ProjectTimeline (907-1051, 145 行)
  - SubconsciousMailbox (1052-1085, 34 行)

设计：无 threading.Thread 子类，全部纯工具/感知 class，无前后相对引用。
依赖：PhysicalEnvironmentProbe (from jarvis_env_probe) + threading / collections
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class FunnelLogger:' in lines[142], f'Line 143 expected FunnelLogger, got: {lines[142]!r}'
assert 'class SensorFilter:' in lines[219], f'Line 220 expected SensorFilter, got: {lines[219]!r}'
assert 'class HabitClock:' in lines[486], f'Line 487 expected HabitClock, got: {lines[486]!r}'
assert 'class SubconsciousMailbox:' in lines[1051], f'Line 1052 expected SubconsciousMailbox, got: {lines[1051]!r}'

# lines[1086] (0-idx) = 1-idx 行 1087 = "# 📍 修改目标文件:"
# lines[1088] (0-idx) = 1-idx 行 1089 = "class ChronosTick..."
assert '修改目标文件' in lines[1086] or 'ChronosTick' in lines[1086], f'Line 1087 expected ChronosTick comment, got: {lines[1086]!r}'
assert 'class ChronosTick' in lines[1088], f'Line 1089 expected ChronosTick class, got: {lines[1088]!r}'

# 切片：line 143-1085 (0-indexed [142:1086])
sensors_body = ''.join(lines[142:1086])

SENSORS_HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-3 / 2026-05-16] Jarvis Sensors — 传感/感知/工具类（无 Thread 子类）

从 jarvis_nerve.py 拆出 6 个类（不含 threading.Thread 子类）：

| Class               | 用途                                                  |
|---------------------|-------------------------------------------------------|
| FunnelLogger        | 智能轻推漏斗判定 logger（命中/拒绝/原因）              |
| SensorFilter        | 28 维传感器矩阵 + LLM 分类兜底的"打扰阻力值"滤波器     |
| HabitClock          | 习惯时钟 — 时段语义 / 凌晨上下文 / 睡眠倾向            |
| CausalChain         | 因果链记忆 — 用户行为 → 系统反应 → 用户反馈           |
| ProjectTimeline     | 项目时间线 — 长跨度任务的"上次干到哪了"反查           |
| SubconsciousMailbox | 潜意识收件箱 — 三级递进提醒 + 心脏起搏器仲裁源        |

依赖：
- 标准库：time / threading / collections / queue / random / re / json
- jarvis_env_probe.PhysicalEnvironmentProbe (SensorFilter 内部用)
- jarvis_utils.bg_log (延迟 import)
- jarvis_llm_reflector.LlmReflector (延迟 import, 用 reflect 接口)

向后兼容：jarvis_nerve.py 用 `from jarvis_sensors import *` 转发，
旧 `from jarvis_nerve import FunnelLogger / SensorFilter / HabitClock /
CausalChain / ProjectTimeline / SubconsciousMailbox` 0 改动。
"""

from __future__ import annotations

import time
import threading
import collections
import queue  # noqa: F401 — SubconsciousMailbox 可能用
import random  # noqa: F401
import re
import json

from jarvis_env_probe import PhysicalEnvironmentProbe  # SensorFilter / HabitClock 内部用

__all__ = [
    'FunnelLogger',
    'SensorFilter',
    'HabitClock',
    'CausalChain',
    'ProjectTimeline',
    'SubconsciousMailbox',
]


'''

# 写 jarvis_sensors.py
SENSORS_PATH = os.path.join(ROOT, 'jarvis_sensors.py')
with open(SENSORS_PATH, 'w', encoding='utf-8') as f:
    f.write(SENSORS_HEADER)
    f.write(sensors_body)
print(f'[P0+19-3] WROTE: jarvis_sensors.py ({(SENSORS_HEADER + sensors_body).count(chr(10)) + 1} lines)')


# Patch nerve.py
STUB = '''# ==========================================
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

'''

new_lines = lines[:142] + [STUB] + lines[1086:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'[P0+19-3] nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
print('[P0+19-3] Done. Verify: python -c "import jarvis_nerve"')
