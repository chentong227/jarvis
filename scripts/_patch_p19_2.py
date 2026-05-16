# -*- coding: utf-8 -*-
"""[P0+19-2 patch] 修改 jarvis_nerve.py 和 jarvis_enhanced.py：
1. nerve.py: 删 KeyRouter+LlmReflector+EnvProbe 三段 (行 130-1286, 1157 行) → 加转发垫层
2. enhanced.py: 10 处 `from jarvis_nerve import PhysicalEnvironmentProbe` 延迟 import
   → 改为顶部 `from jarvis_env_probe import PhysicalEnvironmentProbe`（消除循环依赖）
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')
ENHANCED = os.path.join(ROOT, 'jarvis_enhanced.py')


# =============================================================================
# Step 1: nerve.py 切换段
# =============================================================================
with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言（防止意外）
assert lines[129].strip().startswith('# ===') or '🧠' in lines[130], \
    f'Line 130 mismatch: {lines[129]!r} / {lines[130]!r}'
assert 'class KeyRouter:' in lines[134], f'Line 135 expected KeyRouter, got: {lines[134]!r}'
assert 'class LlmReflector:' in lines[472], f'Line 473 expected LlmReflector, got: {lines[472]!r}'
assert 'class PhysicalEnvironmentProbe:' in lines[625], f'Line 626 expected EnvProbe, got: {lines[625]!r}'
assert 'class FunnelLogger:' in lines[1286], f'Line 1287 expected FunnelLogger, got: {lines[1286]!r}'

STUB = '''# ==========================================
# 🚂 [P0+19-2 / 2026-05-16] 基础设施层已拆到独立文件
# ==========================================
# 原内容（行 130-1286, 1157 行 / KeyRouter + LlmReflector + PhysicalEnvironmentProbe）
# 已搬到：
#   - jarvis_key_router.py     (KeyRouter / API Key 路由 + 启动诊断探针 / 365 行)
#   - jarvis_llm_reflector.py  (LlmReflector / 共享 LLM 反思引擎 / 182 行)
#   - jarvis_env_probe.py      (PhysicalEnvironmentProbe / 物理环境感知 / 696 行)
# 转发垫层保证 `from jarvis_nerve import KeyRouter / LlmReflector / PhysicalEnvironmentProbe` 0 改动
from jarvis_key_router import KeyRouter
from jarvis_llm_reflector import LlmReflector
from jarvis_env_probe import PhysicalEnvironmentProbe

'''

# 替换：保留 lines[:129] + STUB + lines[1286:]
new_lines = lines[:129] + [STUB] + lines[1286:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f'[P0+19-2 patch] nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')


# =============================================================================
# Step 2: enhanced.py 10 处延迟 import → 顶部 import
# =============================================================================
with open(ENHANCED, 'r', encoding='utf-8') as f:
    text = f.read()

# 计数前
delayed_count = text.count('from jarvis_nerve import PhysicalEnvironmentProbe')
print(f'[P0+19-2 patch] enhanced.py: 检测到 {delayed_count} 处延迟 import')

# 把所有"函数内延迟 import"行删掉（这些行通常有缩进）
# 匹配模式：行首有空白 + `from jarvis_nerve import PhysicalEnvironmentProbe`
text_new = re.sub(
    r'^([ \t]+)from jarvis_nerve import PhysicalEnvironmentProbe\s*\n',
    '',
    text,
    flags=re.MULTILINE,
)

# 验证：现在 enhanced.py 中应该 0 处含此 import
remaining = text_new.count('from jarvis_nerve import PhysicalEnvironmentProbe')
assert remaining == 0, f'Still {remaining} delayed imports remaining'

# 在顶部 import 区追加（找一个稳定的 anchor）
# enhanced.py 头部应该有 `from collections import deque, defaultdict` 这种
anchor = 'from collections import deque, defaultdict'
assert anchor in text_new, f'Anchor not found: {anchor!r}'
top_import = '\nfrom jarvis_env_probe import PhysicalEnvironmentProbe   # [P0+19-2] 顶部 import, 旧延迟 import 已移除\n'
text_new = text_new.replace(anchor, anchor + top_import, 1)

with open(ENHANCED, 'w', encoding='utf-8') as f:
    f.write(text_new)

print(f'[P0+19-2 patch] enhanced.py: 删除 {delayed_count} 处延迟 import, 加 1 处顶部 import')
print('[P0+19-2 patch] Done. Verify: python -c "import jarvis_nerve"')
