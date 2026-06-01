# -*- coding: utf-8 -*-
"""[放权 T0.1 / Sir 2026-06-01] 生命体征台 CLI.

用法:
  python scripts/vitals_dump.py            # 人读体征台
  python scripts/vitals_dump.py --json     # 机读 JSON (dashboard 接)

真相源 docs/JARVIS_LETTING_GO_ROLLOUT.md §3 (第 0 格 T0.1)。
纯读聚合, 不改任何状态。breach=硬证, 其余=会退化代理 (rollout §4)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
try:
    import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout (GBK safe)
except Exception:
    pass

# 让 import jarvis_vitals_board 能找到仓库根
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json  # noqa: E402
import jarvis_vitals_board as vb  # noqa: E402


def main() -> int:
    if "--snapshot" in sys.argv:
        ok = vb.snapshot()
        print(f"snapshot appended: {ok}")
    elif "--trend" in sys.argv:
        print(vb.render_trend())
    elif "--json" in sys.argv:
        print(json.dumps(vb.collect(), ensure_ascii=False, indent=2))
    else:
        print(vb.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
