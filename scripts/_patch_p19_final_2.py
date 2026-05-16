# -*- coding: utf-8 -*-
"""[P0+19-final fix 2 / 2026-05-16] 补完所有运行时 NameError

5 个文件需要补 `from google.genai import types`：
  - jarvis_chat_bypass.py
  - jarvis_memory_core.py
  - jarvis_conductor.py
  - jarvis_sentinels.py
  - jarvis_env_probe.py

额外补：
  - jarvis_sentinels.py: import io / import sys
  - jarvis_commitment_watcher.py: import sys
  - jarvis_worker.py: set_browser_ducking from central_nerve
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATCHES = {
    # (file, anchor): patch_text
    'jarvis_chat_bypass.py': (
        'from jarvis_safety import (',
        '# [P0+19-final fix 2] 缺失的 google.genai.types\nfrom google.genai import types  # noqa: F401\nimport io  # noqa: F401\nimport sys  # noqa: F401\n\n',
    ),
    'jarvis_memory_core.py': (
        'from typing import List, Dict, Any, Optional',
        'from typing import List, Dict, Any, Optional  # noqa: F401\n# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401',
    ),
    'jarvis_conductor.py': (
        'from jarvis_env_probe import PhysicalEnvironmentProbe',
        'from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401\n# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401\nimport io  # noqa: F401',
    ),
    'jarvis_sentinels.py': (
        'from jarvis_env_probe import PhysicalEnvironmentProbe',
        'from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401\n# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401\nimport io  # noqa: F401',
    ),
    'jarvis_env_probe.py': (
        'from pycaw.pycaw import',
        '# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401\nimport io  # noqa: F401\nfrom pycaw.pycaw import',
    ),
    'jarvis_commitment_watcher.py': (
        'from jarvis_env_probe import PhysicalEnvironmentProbe',
        'from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401\n# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401\nimport io  # noqa: F401',
    ),
    'jarvis_return_sentinel.py': (
        'from jarvis_env_probe import PhysicalEnvironmentProbe',
        'from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401\n# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401\nimport io  # noqa: F401',
    ),
    'jarvis_smart_nudge.py': (
        'from jarvis_env_probe import PhysicalEnvironmentProbe',
        'from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401\n# [P0+19-final fix 2]\nfrom google.genai import types  # noqa: F401\nimport sys  # noqa: F401\nimport io  # noqa: F401',
    ),
    'jarvis_worker.py': (
        'from jarvis_central_nerve import CentralNerve, JARVIS_CORE_PERSONA',
        'from jarvis_central_nerve import CentralNerve, JARVIS_CORE_PERSONA, set_browser_ducking  # [P0+19-final fix 2] set_browser_ducking',
    ),
}


def patch(filename, anchor, patch_text):
    path = os.path.join(ROOT, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'P0+19-final fix 2' in content and filename != 'jarvis_worker.py':
        return f'{filename}: already patched'
    
    if anchor not in content:
        return f'{filename}: ANCHOR NOT FOUND'
    
    new = content.replace(anchor, patch_text, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new)
    return f'{filename}: patched'


for f, (a, p) in PATCHES.items():
    print(patch(f, a, p))
