# -*- coding: utf-8 -*-
"""[P0+19-4 / 2026-05-16] 切分 jarvis_nerve.py 行 7354-8064 (4 类 router/profile) → jarvis_routing.py

注意：design doc 原计划包含 PromptCenter / GuardianCenter / CompanionCenter 3 类，
但它们引用大量待拆 Sentinel (SoulArchivist / Conductor / SmartNudge / ...) 会产生
循环依赖。这 3 个 Center 推迟到 P0+19-6 sentinel 全拆完后再做（作为 P0+19-6.f）。

本 sub-step 只切：
  - SoulRouter (7354-7489, 136 行)
  - ContextRouter (7490-7582, 93 行)
  - ContentPreferenceTracker (7583-7788, 206 行)
  - ProfileCard (7789-8063, 275 行)
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class SoulRouter:' in lines[7353], f'Line 7354 expected SoulRouter, got: {lines[7353]!r}'
assert 'class ContextRouter:' in lines[7489], f'Line 7490 expected ContextRouter, got: {lines[7489]!r}'
assert 'class ContentPreferenceTracker:' in lines[7582], f'Line 7583 expected ContentPreferenceTracker, got: {lines[7582]!r}'
assert 'class ProfileCard:' in lines[7788], f'Line 7789 expected ProfileCard, got: {lines[7788]!r}'
# ProfileCard 结束于 ~8063，line 8064 空行，line 8065 = '@dataclass', line 8066 = PromptLayer
assert '@dataclass' in lines[8064], f'Line 8065 expected @dataclass, got: {lines[8064]!r}'

# 切片：line 7354-8064 (0-indexed [7353:8064])
routing_body = ''.join(lines[7353:8064])

ROUTING_HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-4 / 2026-05-16] Jarvis Routing — 路由 / 用户画像类

从 jarvis_nerve.py 拆出 4 个类（路由 / 偏好追踪 / 画像聚合）：

| Class                     | 用途                                              |
|---------------------------|---------------------------------------------------|
| SoulRouter                | 中英双语桥 + Sir 的"灵魂章节"路由 (项目/笑话/里程碑) |
| ContextRouter             | 上下文路由（多档分级 prompt tier 决策）             |
| ContentPreferenceTracker  | 内容偏好追踪（Sir 喜欢的 topic / 风格）            |
| ProfileCard               | 用户画像卡片（聚合各模块信息生成紧凑快照）            |

依赖：
- 标准库：time / json / re / threading / collections
- 通过 central_nerve 实例属性访问其他模块（无直接 import 依赖）

向后兼容：jarvis_nerve.py 用 `from jarvis_routing import ...` 转发。

注：P0+19-4 原 design doc 含 PromptCenter / GuardianCenter / CompanionCenter，
但它们引用大量待拆 Sentinel，产生循环依赖。推迟到 P0+19-6.f（sentinel 全拆完后）。
"""

from __future__ import annotations

import time
import json
import re
import threading  # noqa: F401
import collections  # noqa: F401

__all__ = [
    'SoulRouter',
    'ContextRouter',
    'ContentPreferenceTracker',
    'ProfileCard',
]


'''

# 写 jarvis_routing.py
ROUTING_PATH = os.path.join(ROOT, 'jarvis_routing.py')
with open(ROUTING_PATH, 'w', encoding='utf-8') as f:
    f.write(ROUTING_HEADER)
    f.write(routing_body)
print(f'[P0+19-4] WROTE: jarvis_routing.py ({(ROUTING_HEADER + routing_body).count(chr(10)) + 1} lines)')


# Patch nerve.py
STUB = '''# ==========================================
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

'''

new_lines = lines[:7353] + [STUB] + lines[8064:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'[P0+19-4] nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
print('[P0+19-4] Done. Verify: python -c "import jarvis_nerve"')
