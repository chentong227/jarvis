# -*- coding: utf-8 -*-
"""[P0+19-final fix 4 / 2026-05-16] 一次性给所有 16 个新文件补全标准库 import

减少后续 NameError 暴露面 - 每个新文件添加一个 "safety import block"。
重复 import 在 Python 中无害（仅 namespace 注入）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 要补的标准库（保守集 — 拆分前 nerve.py 顶部有的全部都给）
SAFETY_IMPORTS = '''
# [P0+19-final fix 4 / 2026-05-16] 一次性补全标准库 + 第三方常用 import（防 NameError 暴露）
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import random  # noqa: F401
import queue  # noqa: F401
import sqlite3  # noqa: F401
import hashlib  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
import importlib  # noqa: F401
import concurrent.futures  # noqa: F401
import multiprocessing  # noqa: F401
from collections import defaultdict, deque  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
try:
    from google.genai import types  # noqa: F401
except ImportError:
    pass

'''

# 要 patch 的所有新文件
FILES = [
    'jarvis_safety.py',
    'jarvis_key_router.py',
    'jarvis_llm_reflector.py',
    'jarvis_env_probe.py',
    'jarvis_sensors.py',
    'jarvis_routing.py',
    'jarvis_memory_core.py',
    'jarvis_sentinels.py',
    'jarvis_conductor.py',
    'jarvis_return_sentinel.py',
    'jarvis_commitment_watcher.py',
    'jarvis_smart_nudge.py',
    'jarvis_chat_bypass.py',
    'jarvis_central_nerve.py',
    'jarvis_worker.py',
    'jarvis_ui.py',
]


def patch(filename):
    path = os.path.join(ROOT, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'P0+19-final fix 4' in content:
        return f'{filename}: already patched'
    
    # 在 "from __future__ import" 之后 或 第一个 import 之前 插入
    import re as _re
    
    # 优先在 'from __future__ import' 后插入
    m = _re.search(r'from __future__ import [^\n]+\n', content)
    if m:
        insert_pos = m.end()
        new = content[:insert_pos] + SAFETY_IMPORTS + content[insert_pos:]
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new)
        return f'{filename}: patched (after __future__)'
    
    # 否则在文件第一行（docstring 之后）插入
    # docstring 通常以 """ 开头 + 多行 + """ 结尾
    if content.startswith('"""') or content.startswith('# -*-'):
        # 找文件第一个非注释、非 docstring 的位置
        in_docstring = False
        lines = content.split('\n')
        insert_line = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('"""'):
                if in_docstring:
                    insert_line = i + 1
                    in_docstring = False
                    break
                else:
                    in_docstring = True
                    if stripped.endswith('"""') and len(stripped) > 3:
                        # 单行 docstring
                        insert_line = i + 1
                        break
            elif not in_docstring and stripped and not stripped.startswith('#'):
                insert_line = i
                break
        
        new_lines = lines[:insert_line] + [SAFETY_IMPORTS] + lines[insert_line:]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))
        return f'{filename}: patched (after docstring)'
    
    # 兜底：直接插到文件开头
    with open(path, 'w', encoding='utf-8') as f:
        f.write(SAFETY_IMPORTS + content)
    return f'{filename}: patched (at top)'


for f in FILES:
    print(patch(f))
