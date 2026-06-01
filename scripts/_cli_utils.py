# -*- coding: utf-8 -*-
"""
🆕 [Sir 2026-05-28 14:51 Track 2] CLI 共享 utility — Windows GBK emoji safe.

历史 BUG: Windows PowerShell 默认 GBK code page, 78 个 dump CLI script 用
emoji print (`✅ ❌ 📭 ⏳ 🆕` 等) → `UnicodeEncodeError: 'gbk' codec can't
encode U+XXXX` → 整个 CLI fail (--accept/--reject/--list 都死), Sir 看似无
反应实际 print 之前已 raise.

历史 root case: tests/_test_p0_plus_20_p5_fix23_meta_protect.py runtime
                pollution 调查时撞 phrase_lock_dump.py --accept fail.

修法 (准则 8 优雅): 单一 utility import 时 side-effect 自动 reconfigure
stdout UTF-8 (Python 3.7+) + 提供 safe_print() fallback for ancient Python.
所有 dump CLI 顶部加 `import _cli_utils` 即可 (78 file boilerplate 共享).

用法:
  # scripts/your_dump.py 顶部:
  import os, sys
  sys.path.insert(0, os.path.dirname(__file__))
  import _cli_utils  # noqa: F401  # side-effect force utf8 stdout

  # 之后所有 print('✅', '中文') 在 Windows GBK 终端都安全
"""
from __future__ import annotations

import sys


def force_utf8_stdout() -> bool:
    """Reconfigure sys.stdout/stderr 到 UTF-8. Python 3.7+ 支持.

    Returns: True 成功 reconfigure / False 失败 (老 Python 或 stream 不支持).
    """
    ok = True
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding='utf-8')  # Python 3.7+
        except (AttributeError, ValueError, OSError):
            # 老 Python (< 3.7) 或不支持 reconfigure 的 stream (e.g. pytest
            # capture / IPython 已包装 stream). 不 raise, fallback 用
            # safe_print().
            ok = False
    return ok


def safe_print(msg: str = '', **kwargs) -> None:
    """Emoji/中文 safe print. 失败 fallback 把不能 encode 字符替成 '?'.

    用法 (老 CLI 改最小): print() → safe_print().
    新 CLI: 顶部 import _cli_utils 即可, 之后用普通 print().
    """
    try:
        print(msg, **kwargs)
    except UnicodeEncodeError:
        enc = (sys.stdout.encoding or 'ascii')
        # 把不能 encode 的字符 replace 成 '?', 防数据丢失
        safe = msg.encode(enc, 'replace').decode(enc, 'replace')
        print(safe, **kwargs)


# ============================================================
# import 时 side-effect: 自动 force utf-8 stdout (Sir Windows 真痛)
# ============================================================
force_utf8_stdout()
