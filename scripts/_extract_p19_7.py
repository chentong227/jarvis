# -*- coding: utf-8 -*-
"""[P0+19-7 / 2026-05-16] 切 ChatBypass + _C3_ACTION_HAND_COMMANDS → jarvis_chat_bypass.py

ChatBypass 3003 行 + _C3 常量 36 行 = 3041 行
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'P0+18-c.3' in lines[318], f'L319 _C3 comment: {lines[318]!r}'
assert '_C3_ACTION_HAND_COMMANDS' in lines[328], f'L329 _C3 define: {lines[328]!r}'
assert 'class ChatBypass:' in lines[356], f'L357 ChatBypass: {lines[356]!r}'
# 切片范围 line 319-3359 (0-idx [318:3359])
# 但 line 3360-3392 是已有的 P0+19-4/5 转发段，必须保留
# 让我再看 ChatBypass 真正末尾
# 我们已经看到 line 3358 = 'return ""'，3359 空行，3360 起 P0+19-4 STUB

body = ''.join(lines[318:3359])  # 1-indexed line 319-3359, 3041 行

HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-7 / 2026-05-16] ChatBypass — 主对话循环（最大单类 3003 行）

从 jarvis_nerve.py 拆出。设计原则：
- 接收用户语音 → 主脑 LLM stream → tool 调用 → audio queue → TTS 播放
- Fast Path 优化（_is_simple_one_shot + _C3_ACTION_HAND_COMMANDS 白名单）
- 防幻觉守门（PROMISE/ACTIVATE_PLAN/RESUME_PLAN 结构化标签拆解）
- 音频 / 字幕 / 节奏 queue 多路分发
- _last_circuit_broken_reason / _last_tool_results 暴露给外层 JarvisWorker

依赖：
- KeyRouter (jarvis_key_router)
- Safety helper (jarvis_safety: 结构化标签 / 中文检测 / Fast Path 守卫)
- 各种器官（通过 self.key_router 间接）

向后兼容：jarvis_nerve.py 用 `from jarvis_chat_bypass import ChatBypass` + 旧
`from jarvis_nerve import ChatBypass` 都能继续 work。

注：本文件包含 ChatBypass 用的 `_C3_ACTION_HAND_COMMANDS` 常量（Fast Path 白名单）。
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
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional  # noqa: F401

# 跨文件依赖
from jarvis_safety import (
    _STRUCTURAL_TAGS,
    _STRUCTURAL_TAG_BLOCK_RE,
    _STRUCTURAL_TAG_ANY_RE,
    _strip_structural_tag_blocks,
    _strip_structural_tags_only,
    _is_forming_structural_tag,
    _sentence_is_chinese_lean,
    _CHINESE_CHAR_RE,
)
from jarvis_key_router import KeyRouter  # noqa: F401
from jarvis_llm_reflector import LlmReflector  # noqa: F401

'''

OUT_PATH = os.path.join(ROOT, 'jarvis_chat_bypass.py')
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write(HEADER)
    f.write(body)
print(f'WROTE jarvis_chat_bypass.py ({(HEADER + body).count(chr(10)) + 1} lines)')


# Patch nerve.py
STUB = '''# 💬 [P0+19-7 / 2026-05-16] ChatBypass (3003 行) + _C3_ACTION_HAND_COMMANDS → jarvis_chat_bypass.py
from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS

'''

new_lines = lines[:318] + [STUB] + lines[3359:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
