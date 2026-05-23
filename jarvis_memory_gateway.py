# -*- coding: utf-8 -*-
"""[Reshape M2.C.3 / 2026-05-24] DEPRECATED — 转发垫层 → jarvis_memory_hub.py

历史: 此 file 原是 `MemoryMutationGateway` (P2-Gap7 / 2026-05-20 23:55) 实现.
Sir Q3 决议 (M2 落实): 改名 `MemoryHub`. M2.C.3 阶段 `git mv` 到
`jarvis_memory_hub.py`, 此 file 留 backward-compat 转发垫层让老 import 全 work:

    from jarvis_memory_gateway import update_sir_field       # 老 import 不破
    from jarvis_memory_gateway import MemoryMutationGateway  # 老 import 不破
    from jarvis_memory_gateway import get_default_gateway    # 老 import 不破

推荐新代码:
    from jarvis_memory_hub import get_default_hub, MemoryHub

类似 `jarvis_nerve.py` 转发 `jarvis_memory_core.py` 的处理, 0 caller 必须改.
"""

from __future__ import annotations

# 转发所有名字 (含 *)
from jarvis_memory_hub import *  # noqa: F401, F403

# 显式 re-export 让 IDE + linter 高兴
from jarvis_memory_hub import (  # noqa: F401
    # core classes
    WriteReceipt,
    MemoryMutationGateway,
    MemoryHub,
    # singletons
    get_default_gateway,
    get_default_hub,
    reset_default_gateway_for_test,
    reset_default_hub_for_test,
    # convenience entry
    update_sir_field,
    # internal helpers (test 用)
    _detect_target_layer,
    _RECEIPT_PATH,
)
