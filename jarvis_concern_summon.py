# -*- coding: utf-8 -*-
"""[P5-Gap4-followup-vocab / 2026-05-21 21:42] Concern Summon Detector — 准则 6.5 vocab loader

Sir 召唤 SOUL concern inject 的 keyword 检测器.
原 jarvis_central_nerve.py 硬编码 _summon_kw tuple, 违反准则 6.5
("vocab 持久化 + CLI 可改 + L7 Reflector LLM-propose").

本模块:
  - load `memory_pool/concern_summon_vocab.json` 取 active patterns
  - 命中任意 keyword → True (主脑下轮 inject SOUL concern)
  - vocab 文件缺失/损坏 → fall back 到 hardcoded list (resilience)

API:
  - is_summoned(text) -> bool: 主流入口
  - load_active_keywords() -> list[str]: 看当前激活的所有 keyword

CLI:
  python scripts/concern_summon_dump.py --list
  python scripts/concern_summon_dump.py --add <kw> --category <cat>
  python scripts/concern_summon_dump.py --activate <id>
  python scripts/concern_summon_dump.py --reject <id>
"""
from __future__ import annotations

import json
import os
import threading
from typing import List, Optional


_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool',
    'concern_summon_vocab.json',
)

# Fallback — vocab 缺失/损坏时用. 跟 commit dec4870 原 hardcoded list 对齐.
_FALLBACK_KEYWORDS = (
    'concern', 'concerns', 'worry', 'worried', 'remind',
    'progress', 'status', "what's up", 'how am i', 'how about',
    'whats up', 'how are you', 'check on me', 'check in',
    '担心', '心事', '进度', '状态', '怎么样', '啥情况', '提醒',
    '记着', '要注意', '检查', '关心',
)

_CACHE_LOCK = threading.Lock()
_CACHED_KEYWORDS: Optional[List[str]] = None
_CACHED_MTIME: float = 0.0


def _load_from_disk() -> List[str]:
    """读 vocab json, 取 active 的 keyword 列表."""
    try:
        if not os.path.exists(_VOCAB_PATH):
            return list(_FALLBACK_KEYWORDS)
        with open(_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        patterns = data.get('patterns') or []
        kws: List[str] = []
        for p in patterns:
            if p.get('state') != 'active':
                continue
            for kw in (p.get('keywords') or []):
                if isinstance(kw, str) and kw:
                    kws.append(kw.lower())
        if not kws:
            # 防御 — vocab 文件存在但全 inactive → 仍 fall back
            return list(_FALLBACK_KEYWORDS)
        return kws
    except Exception:
        # JSON 损坏 / IO error → fall back
        return list(_FALLBACK_KEYWORDS)


def load_active_keywords(force_reload: bool = False) -> List[str]:
    """获取当前激活的 keyword 列表 (mtime 缓存, 1s 内重复调 不读盘)."""
    global _CACHED_KEYWORDS, _CACHED_MTIME
    with _CACHE_LOCK:
        try:
            mtime = os.path.getmtime(_VOCAB_PATH) if os.path.exists(_VOCAB_PATH) else 0.0
        except Exception:
            mtime = 0.0
        if force_reload or _CACHED_KEYWORDS is None or mtime != _CACHED_MTIME:
            _CACHED_KEYWORDS = _load_from_disk()
            _CACHED_MTIME = mtime
        return list(_CACHED_KEYWORDS)


def is_summoned(text: str) -> bool:
    """判 Sir 是否 召唤 concerns (任意 keyword 命中即 True)."""
    if not text:
        return False
    t = text.lower()
    for kw in load_active_keywords():
        if kw and kw in t:
            return True
    return False


def reset_cache_for_test() -> None:
    """testcase 用 — 重置缓存避免 mtime 干扰."""
    global _CACHED_KEYWORDS, _CACHED_MTIME
    with _CACHE_LOCK:
        _CACHED_KEYWORDS = None
        _CACHED_MTIME = 0.0
