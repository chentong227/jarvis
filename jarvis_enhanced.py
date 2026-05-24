# -*- coding: utf-8 -*-
"""[Reshape M3.E / 2026-05-24] jarvis_enhanced.py — Facade re-export.

🆕 老 file 739 行包 3 class (ProactiveShield + ProactiveCompanion + SkillTreeTracker).
M3.E 拆 3 file 后此 file 退化为 facade re-export, 兼容老 caller `from jarvis_enhanced import X`.

新位置:
    - `ProactiveShield`     → `jarvis_proactive_shield.py`
    - `ProactiveCompanion`  → `jarvis_proactive_companion.py`
    - `SkillTreeTracker`    → `jarvis_skill_tree_tracker.py`
    - `get_user_idle_seconds()` → `jarvis_proactive_companion.py` (helper)

老死代码 (P0+19 残留 9 个 orphaned class duplicate) 已在 P0+20-β.1.10 删除.

Cleanup trigger (M6.4+): caller 全改 `from jarvis_proactive_shield import` 等
                       直接 import 后, 此 facade file 可 git rm.
"""

# Re-export 3 class for backward compatibility (caller: `from jarvis_enhanced import X`).
from jarvis_proactive_shield import ProactiveShield  # noqa: F401
from jarvis_proactive_companion import ProactiveCompanion, get_user_idle_seconds  # noqa: F401
from jarvis_skill_tree_tracker import SkillTreeTracker  # noqa: F401

__all__ = [
    'ProactiveShield',
    'ProactiveCompanion',
    'SkillTreeTracker',
    'get_user_idle_seconds',
]
