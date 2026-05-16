# -*- coding: utf-8 -*-
"""[P0+19-6.b/c/d/e / 2026-05-16] 切 4 个大 sentinel 类到独立文件
   - Conductor (722 行) → jarvis_conductor.py
   - ReturnSentinel (711 行) → jarvis_return_sentinel.py
   - CommitmentWatcher (554 行) → jarvis_commitment_watcher.py
   - SmartNudgeSentinel (548 行) → jarvis_smart_nudge.py

中间保留：
   - PromptCenter/GuardianCenter/CompanionCenter (897-1005, 109 行) → 留 nerve.py（P0+19-6.f）
   - STUB_B (1007-1017) → 保留
   - _C3_ACTION_HAND_COMMANDS (2832-2867) → 留 nerve.py（被 ChatBypass 用）
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class Conductor' in lines[173], f'L174 Conductor: {lines[173]!r}'
assert 'class PromptCenter' in lines[896], f'L897 PromptCenter: {lines[896]!r}'
assert 'class ReturnSentinel' in lines[1018], f'L1019 ReturnSentinel: {lines[1018]!r}'
assert 'class CommitmentWatcher' in lines[1729], f'L1730 CommitmentWatcher: {lines[1729]!r}'
assert 'class SmartNudgeSentinel' in lines[2283], f'L2284 SmartNudge: {lines[2283]!r}'
assert 'P0+18-c.3' in lines[2831], f'L2832 _C3 comment: {lines[2831]!r}'
assert 'class ChatBypass' in lines[2869], f'L2870 ChatBypass: {lines[2869]!r}'

# 切 4 段
conductor_body = ''.join(lines[173:895])         # 174-895 (722 行)
return_body = ''.join(lines[1018:1729])           # 1019-1729 (711 行)
commit_body = ''.join(lines[1729:2283])           # 1730-2283 (554 行)
smart_body = ''.join(lines[2283:2831])            # 2284-2831 (548 行)


COMMON_IMPORTS = '''from __future__ import annotations

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

# 跨文件依赖（上游已拆完）
from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
from jarvis_sensors import (  # noqa: F401
    SubconsciousMailbox, CausalChain, HabitClock,
    FunnelLogger, SensorFilter, ProjectTimeline,
)
from jarvis_sentinels import NudgeGate  # noqa: F401

'''


def write_module(filename: str, title: str, description: str, classname: str, body: str, extra_imports: str = ''):
    path = os.path.join(ROOT, filename)
    header = f'''# -*- coding: utf-8 -*-
"""[{title} / 2026-05-16] {description}

从 jarvis_nerve.py 拆出 1 个大类（>500 行）。
向后兼容：jarvis_nerve.py 用 `from {filename[:-3]} import {classname}` 转发，
旧 `from jarvis_nerve import {classname}` 0 改动。
"""

'''
    full = header + COMMON_IMPORTS + extra_imports + '\n' + body
    with open(path, 'w', encoding='utf-8') as f:
        f.write(full)
    print(f'  WROTE: {filename} ({full.count(chr(10)) + 1} lines)')


# 写 4 个独立文件
write_module(
    'jarvis_conductor.py', 'P0+19-6.b',
    '指挥官 Conductor — 传感器融合 + 规则/LLM 决策 + 三档轻推',
    'Conductor', conductor_body,
)
write_module(
    'jarvis_return_sentinel.py', 'P0+19-6.c',
    '回归哨兵 ReturnSentinel — 动态唤醒回应 + AFK 归来主动问候 + 软焦点验证',
    'ReturnSentinel', return_body,
)
write_module(
    'jarvis_commitment_watcher.py', 'P0+19-6.d',
    '承诺守望者 CommitmentWatcher — 用户承诺监督 + SQLite 持久化（P0+18-e.3）',
    'CommitmentWatcher', commit_body,
)
write_module(
    'jarvis_smart_nudge.py', 'P0+19-6.e',
    'SmartNudge 哨兵 — 11 种 nudge 类型 + type-mute (P0+18-f.3) + humor_memory',
    'SmartNudgeSentinel', smart_body,
    extra_imports='from jarvis_memory_core import HumorMemory  # noqa: F401\n',
)


# Patch nerve.py — 4 段都替换
STUB_CONDUCTOR = '''# 🎼 [P0+19-6.b / 2026-05-16] Conductor (722 行) → jarvis_conductor.py
from jarvis_conductor import Conductor

'''

STUB_RETURN = '''# 🔄 [P0+19-6.c / 2026-05-16] ReturnSentinel (711 行) → jarvis_return_sentinel.py
from jarvis_return_sentinel import ReturnSentinel

'''

STUB_COMMIT = '''# 📌 [P0+19-6.d / 2026-05-16] CommitmentWatcher (554 行) → jarvis_commitment_watcher.py
from jarvis_commitment_watcher import CommitmentWatcher

'''

STUB_SMART = '''# 💡 [P0+19-6.e / 2026-05-16] SmartNudgeSentinel (548 行) → jarvis_smart_nudge.py
from jarvis_smart_nudge import SmartNudgeSentinel

'''

# 新 lines = lines[:173] + STUB_C + lines[895:1018] (含 PromptCenter/Guardian/Companion + STUB_B)
#           + STUB_R + lines[1729:1729] (空) + STUB_M + lines[2283:2283] (空) + STUB_S + lines[2831:]
# 注意：4 段必须按序拼接

new_lines = (
    lines[:173]
    + [STUB_CONDUCTOR]
    + lines[895:1018]               # PromptCenter / GuardianCenter / CompanionCenter + STUB_B
    + [STUB_RETURN]
    + lines[1729:1729]              # 空段
    + [STUB_COMMIT]
    + lines[2283:2283]              # 空段
    + [STUB_SMART]
    + lines[2831:]                   # _C3_ACTION_HAND_COMMANDS + ChatBypass + 后续
)

with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f'[P0+19-6.bcde] nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
print('Done.')
