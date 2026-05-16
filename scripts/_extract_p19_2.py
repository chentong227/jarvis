# -*- coding: utf-8 -*-
"""[P0+19-2 内部工具] 切分 jarvis_nerve.py 行 130-1286 为 3 个新文件。

执行后请删除本脚本。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')

with open(NERVE_PATH, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 0-indexed 切片
key_router_body = ''.join(lines[134:471])           # line 135-471
llm_reflector_body = ''.join(lines[472:624])        # line 473-624
env_probe_body = ''.join(lines[625:1286])           # line 626-1286


KEY_ROUTER_HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-2 / 2026-05-16] KeyRouter — API Key 智能路由器

从 jarvis_nerve.py 拆出。设计原则：
- 主脑发声 (CALLER_MAIN_BRAIN) → 锁死 MAIN_BRAIN_KEY，绝不共享
- Google 通道：3 个 Google Key 随机抽，挂了换下一个
- OpenRouter 通道：N 个 Key 随机抽，挂了换下一个
- 同 Key 并发熔断：同一 Key 同时最多 N 个请求
- 启动诊断探针 (P0+18-b.5): probe_google_keys_at_startup 探测 3 Key 是否同 Project

依赖：
- 标准库：time / random / threading / hashlib
- 延迟 import：jarvis_utils.bg_log / create_genai_client
- 延迟 import：google.genai.types

向后兼容：jarvis_nerve.py 用 `from jarvis_key_router import KeyRouter` 转发，
旧 `from jarvis_nerve import KeyRouter` 0 改动。
"""

from __future__ import annotations

import time
import random
import threading
import hashlib  # noqa: F401 — 内部函数 _cache_key 用


'''

LLM_REFLECTOR_HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-2 / 2026-05-16] LlmReflector — 共享 LLM 反思引擎

从 jarvis_nerve.py 拆出。设计原则：
- 单例（_instance 模式）
- 规则引擎实时检测 + LLM 定期语义反思
- 缓存确保相同数据不重复调用（200 entry，超过 LRU 淘汰）
- 模型分层：flash_lite (便宜) / flash (中等)
- 跨模块反思结果存储（reflection_store）

依赖：
- 标准库：hashlib / time / re / json
- jarvis_utils.safe_gemini_call
- jarvis_key_router.KeyRouter（用 CALLER_REFLECTOR 常量 + key release）

向后兼容：jarvis_nerve.py 用 `from jarvis_llm_reflector import LlmReflector` 转发。
"""

from __future__ import annotations

import hashlib
import time
import re
import json

from jarvis_utils import safe_gemini_call
from jarvis_key_router import KeyRouter


'''

ENV_PROBE_HEADER = '''# -*- coding: utf-8 -*-
"""[P0+19-2 / 2026-05-16] PhysicalEnvironmentProbe — 物理环境感知

从 jarvis_nerve.py 拆出。设计原则：
- 毫秒级"心流"与"打扰阻力值"探测（28 维传感器矩阵）
- LLM 分类兜底（视觉理解 + 文本上下文）
- visual_context / visual_interruptibility / window_history 等
  **静态类属性**供其他模块只读访问（无须实例化）
- 主要被 jarvis_enhanced.py 的多个 sentinel 反向引用（之前是延迟 import 规避循环依赖）

依赖：
- 标准库：time / collections / threading
- Windows：win32gui / win32api / win32con / pycaw（顶部 import）
- 延迟 import：jarvis_utils.bg_log

线程安全：visual_interruptibility 等类属性允许多线程并发读；
内部 sensors 字典使用 lock 保护多线程更新。

副效益（P0+19-2 核心）：拆出后 jarvis_enhanced.py 可顶部 import 本类，
不再需要 10 处函数内延迟 import，循环依赖消失。
"""

from __future__ import annotations

import time
import collections
import threading

import win32gui
import win32api
import win32con
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation  # noqa: F401


'''


def write_module(filename: str, header: str, body: str) -> None:
    path = os.path.join(ROOT, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write(body)
    n_lines = (header + body).count('\n') + 1
    print(f'  WROTE: {filename} ({n_lines} lines)')


print('[P0+19-2] Extracting 3 modules from jarvis_nerve.py...')
write_module('jarvis_key_router.py', KEY_ROUTER_HEADER, key_router_body)
write_module('jarvis_llm_reflector.py', LLM_REFLECTOR_HEADER, llm_reflector_body)
write_module('jarvis_env_probe.py', ENV_PROBE_HEADER, env_probe_body)
print('[P0+19-2] Done. Verify with: python -c "import jarvis_key_router, jarvis_llm_reflector, jarvis_env_probe"')
