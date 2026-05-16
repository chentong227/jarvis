# -*- coding: utf-8 -*-
"""[P0+19-0 / 2026-05-16] 测试源码扫描垫层

历史背景
========
P0+19 之前，多个测试用 `_read('jarvis_nerve.py')` + 正则扫源码验证修复落地
（如 `_test_p0_plus_18_d_brain_db_link.py` 13 处 / `_test_p0_plus_18_f` 3 处 等）。

P0+19 把 `jarvis_nerve.py` 17479 行拆成 17 个文件后，原来在 nerve.py 里的符号
会分散到新文件。扫描型测试需要"读多个文件后拼接当一个 corpus 扫"才能继续 work。

设计原则
========
- **`NERVE_SOURCES`**: 列出"原 nerve.py 涉及的所有文件"。每拆出一批就 append 一行。
- **`read_nerve_corpus()`**: 拼接读，返回单一字符串。
- 在 P0+19-0 这一步刚建好时 NERVE_SOURCES 只有 `['jarvis_nerve.py']`，
  `read_nerve_corpus()` 行为**等价**于旧的 `_read('jarvis_nerve.py')`，
  所以这一步是**纯行为等价**改造，不影响任何 assertion。
- 后续每批 sub-step 把对应新文件名追加进 `NERVE_SOURCES`，扫描测试自动跟随。

测试文件改造协议
================
**旧代码**：
```python
def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
        return f.read()

class TestXXX(unittest.TestCase):
    def setUp(self):
        self.src = _read('jarvis_nerve.py')   # ← 这一行
```

**新代码**：
```python
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 加 tests/ 入 path
from _source_corpus import read_nerve_corpus

# _read 保留！其它如 _read('jarvis_utils.py') 仍要用

class TestXXX(unittest.TestCase):
    def setUp(self):
        self.src = read_nerve_corpus()        # ← 改成这个
```

只改 `_read('jarvis_nerve.py')` 这种调用，其余如 `_read('jarvis_utils.py')` /
`_read('jarvis_hippocampus.py')` **不动**（这些文件不在拆分范围内）。
"""

from __future__ import annotations

import os
from typing import List

# 项目根目录（tests/ 的上一级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# =============================================================================
# NERVE_SOURCES — 拆分进度跟随
# =============================================================================
# 每完成一个 P0+19-X sub-step 就在下方对应行 uncomment 文件名。
# 这样扫描型测试始终能"看到完整的 nerve corpus"，不漏检符号。

NERVE_SOURCES: List[str] = [
    'jarvis_nerve.py',                  # 当前主文件（拆分中逐渐变薄）

    # [P0+19-1 / 2026-05-16] 已抽出：
    'jarvis_safety.py',

    # [P0+19-2 / 2026-05-16] 已抽出：
    'jarvis_key_router.py',
    'jarvis_llm_reflector.py',
    'jarvis_env_probe.py',

    # [P0+19-3 / 2026-05-16] 已抽出：
    'jarvis_sensors.py',

    # [P0+19-4 / 2026-05-16] 已抽出（含 SoulRouter / ContextRouter /
    # ContentPreferenceTracker / ProfileCard；3 个 Center 推迟到 P0+19-6.f）：
    'jarvis_routing.py',

    # [P0+19-5 / 2026-05-16] 已抽出：
    'jarvis_memory_core.py',

    # [P0+19-6.a / 2026-05-16] 已抽出 9 普通 sentinel：
    'jarvis_sentinels.py',
    # [P0+19-6.b~e / 2026-05-16] 已抽出 4 个大 sentinel 类：
    'jarvis_conductor.py',
    'jarvis_return_sentinel.py',
    'jarvis_commitment_watcher.py',
    'jarvis_smart_nudge.py',

    # [P0+19-7 / 2026-05-16] 已抽出：
    'jarvis_chat_bypass.py',

    # [P0+19-8 / 2026-05-16] 已抽出：
    'jarvis_central_nerve.py',

    # [P0+19-9 / 2026-05-16] 已抽出：
    'jarvis_worker.py',
    'jarvis_ui.py',

    # [P0+20-β.0.1 / 2026-05-16] L2 directive registry 承载 LLM 行为约束文本：
    'jarvis_directives.py',
]


# =============================================================================
# 工具函数
# =============================================================================

def read_file(rel_path: str) -> str:
    """读取项目根目录下的单个文件。
    
    Args:
        rel_path: 相对项目根目录的路径，如 'jarvis_nerve.py'
    
    Returns:
        文件全文字符串
    
    Raises:
        FileNotFoundError: 文件不存在
    """
    full_path = os.path.join(ROOT, rel_path)
    with open(full_path, 'r', encoding='utf-8') as f:
        return f.read()


def read_nerve_corpus() -> str:
    """读 `NERVE_SOURCES` 列表中所有文件并拼接成单一字符串。
    
    设计：
    - 每个文件之间插入 `# === FILE BOUNDARY: <rel_path> ===` 分隔符注释，
      便于人工 debug 时定位某符号原本在哪个文件
    - 找不到的文件**跳过但不报错**（保证拆分中间状态测试也能跑）
    
    Returns:
        所有文件拼接后的字符串
    """
    parts = []
    for rel in NERVE_SOURCES:
        try:
            content = read_file(rel)
            parts.append(f'\n# === FILE BOUNDARY: {rel} ===\n')
            parts.append(content)
        except FileNotFoundError:
            parts.append(f'\n# === FILE BOUNDARY: {rel} (NOT FOUND, skipped) ===\n')
    return ''.join(parts)


def open_nerve_corpus():
    """返回一个 io.StringIO 对象包含 corpus，用作"伪文件"。
    
    用途：兼容旧测试中的 `with open(NERVE_PATH, 'r', encoding='utf-8') as f:` 模式。
    
    旧代码：
        with open(NERVE_PATH, 'r', encoding='utf-8') as f:
            src = f.read()
    
    新代码：
        with open_nerve_corpus() as f:
            src = f.read()
    
    注意：StringIO 不需要 encoding 参数（已经是 unicode）。
    
    Returns:
        io.StringIO 对象，支持 .read() / .readlines() / for line in f 等
    """
    import io
    return io.StringIO(read_nerve_corpus())


def list_active_sources() -> List[str]:
    """返回当前生效的 NERVE_SOURCES 列表（用于 debug / log）"""
    return list(NERVE_SOURCES)
