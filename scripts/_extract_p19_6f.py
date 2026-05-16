# -*- coding: utf-8 -*-
"""[P0+19-6.f / 2026-05-16] 三 Center → jarvis_routing.py 末尾
   - PromptCenter (lines 138-172, 35 行)
   - GuardianCenter (lines 173-221, 49 行)
   - CompanionCenter (lines 222-246, 25 行)
   总 109 行
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NERVE = os.path.join(ROOT, 'jarvis_nerve.py')
ROUTING = os.path.join(ROOT, 'jarvis_routing.py')

with open(NERVE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 边界断言
assert 'class PromptCenter:' in lines[137], f'L138: {lines[137]!r}'
assert 'class CompanionCenter:' in lines[221], f'L222: {lines[221]!r}'
assert 'P0+19-6.a' in lines[248], f'L249 expected STUB_B: {lines[248]!r}'

centers_body = ''.join(lines[137:247])  # PromptCenter ~ CompanionCenter (含末尾空行)


# 追加到 jarvis_routing.py 末尾
APPEND_BLOCK = '''


# ============================================================================
# [P0+19-6.f / 2026-05-16] 三 Center —— Prompt/Guardian/Companion 调度中心
# ============================================================================
# 从 jarvis_nerve.py 拆出（依赖大量 sentinel，所以排在 sentinel 全拆完后做）

# 跨文件依赖：使用延迟 import 避免循环（routing 早于 sentinel/conductor 加载）
def _resolve_center_deps():
    """延迟解析三 Center 用到的所有跨模块依赖。
    
    返回一个 dict 含所有需要的类。三 Center 的 start_all 方法调用本函数。
    """
    from jarvis_sentinels import (
        SoulArchivistSentinel, ReflectionScheduler, ScreenshotSentinel,
        WellnessGuardian, NudgeGate,
    )
    from jarvis_conductor import Conductor
    from jarvis_return_sentinel import ReturnSentinel
    from jarvis_commitment_watcher import CommitmentWatcher
    from jarvis_smart_nudge import SmartNudgeSentinel
    from jarvis_memory_core import Anticipator
    try:
        from jarvis_enhanced import ProactiveShield
    except ImportError:
        ProactiveShield = None
    return {
        'SoulArchivistSentinel': SoulArchivistSentinel,
        'ReflectionScheduler': ReflectionScheduler,
        'ScreenshotSentinel': ScreenshotSentinel,
        'WellnessGuardian': WellnessGuardian,
        'NudgeGate': NudgeGate,
        'Conductor': Conductor,
        'ReturnSentinel': ReturnSentinel,
        'CommitmentWatcher': CommitmentWatcher,
        'SmartNudgeSentinel': SmartNudgeSentinel,
        'Anticipator': Anticipator,
        'ProactiveShield': ProactiveShield,
    }


# 三 Center 类内部对 SoulArchivistSentinel / Anticipator / Conductor / ... 的引用
# 通过 module-level 注入解析（在 start_all 第一次调用时填充全局名字空间）
_centers_deps_loaded = False
def _ensure_centers_deps():
    global _centers_deps_loaded
    if _centers_deps_loaded:
        return
    deps = _resolve_center_deps()
    g = globals()
    for name, cls in deps.items():
        if cls is not None:
            g[name] = cls
    _centers_deps_loaded = True


'''

# 直接修改 PromptCenter/GuardianCenter/CompanionCenter 的 start_all 第一行注入
# 简化版：让原始代码不变，但前面追加一个全局加载
# 实际上 centers_body 内 start_all 方法直接用 SoulArchivistSentinel 等名字 - 我们让 _ensure_centers_deps 在 import 时自动跑

# 但是 import 时跑会循环依赖。所以只能在 start_all 第一次调用时跑。
# 我们在 centers_body 内的每个 start_all 内加一行 _ensure_centers_deps()。但 centers_body 是固定字符串，
# 没法简单加。改为：在 centers_body 之前加 _ensure_centers_deps() module-level call 行不行？不行，因为 import 时仍然会循环。

# 最简单方案：让 centers_body 在加载时不需要依赖（导入时不报错），
# 把 start_all 中的依赖类放进函数体内的延迟 import。
# 但 centers_body 是从 nerve.py 直接复制，里面 start_all 内**直接**调用类名。

# 实际方案：在 _ensure_centers_deps 内打到 globals()，然后让 centers_body 在 start_all 第一行调它。
# 用 sed 在 centers_body 中改 def start_all(self): 后第一行注入 _ensure_centers_deps()
import re
centers_body_patched = re.sub(
    r'(def start_all\(self\):\s*\n)',
    r'\1        _ensure_centers_deps()\n',
    centers_body,
)


with open(ROUTING, 'a', encoding='utf-8') as f:
    f.write(APPEND_BLOCK)
    f.write(centers_body_patched)
print(f'Appended 3 centers to jarvis_routing.py')


# Patch nerve.py
STUB = '''# 🎼 [P0+19-6.f / 2026-05-16] 三 Center → jarvis_routing.py 末尾
from jarvis_routing import PromptCenter, GuardianCenter, CompanionCenter

'''

new_lines = lines[:137] + [STUB] + lines[247:]
with open(NERVE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print(f'nerve.py: {len(lines)} → {len(new_lines)} lines (cut {len(lines) - len(new_lines)})')
