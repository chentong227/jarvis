# -*- coding: utf-8 -*-
"""[Sir 2026-05-24 22:57 audit BUG #1 治本] Translator vocab IO 集中 + 同进程锁.

源 BUG (审计发现):
  Translator.flush_hit_updates + TranslatorReflector.run_cycle 都对 vocab.json
  read-modify-write, 但两边各自 open/write 无共享锁 → race condition:
    1. T1 read vocab (hit_count=5)
    2. T2 read vocab (hit_count=5)
    3. T1 写 hit_count=10 (5+5)
    4. T2 写 propose 新 alias (但 hit_count 还是 5+propose, 覆盖 T1)
  → T1 的 hit_count 增长 silently 丢失. 同理 Sir CLI activate 时也可能丢.

修法:
  1. 把 vocab read-modify-write 操作集中到此 module
  2. module-level threading.Lock 保护同进程并发 (translator + reflector 同进程)
  3. CLI 是独立进程 — 用 atomic write (tmp+rename) + post-write mtime check
     (CLI 写完后 reflector/translator 下次读拿最新 mtime → 自动 reload)
  4. 提供 read_then_mutate(callback) helper: 持锁 read → mutate → write 一气呵成
  5. CLI 调 read_then_mutate 也走此路径 (统一)

设计原则:
  - 同进程 (translator + reflector + nerve flush daemon): 持锁串行 (零冲突)
  - 跨进程 (CLI dump.py): mtime cache 检测 (CLI 写后 .py mtime 变 → 下次 reload)
  - 不引 fcntl/portalocker (windows 兼容 + 零依赖, JarvisRule §1 efficient)
  - atomic write (tmp + os.replace) 防部分写
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

# 全局 lock — 同进程 translator + reflector + nerve flush 共享
_VOCAB_LOCK = threading.RLock()  # RLock 防 nested callback 调


def load_vocab(vocab_path: str) -> Dict[str, Any]:
    """加载 vocab.json. 持锁读 — 保证不读到 partial write.

    返默认 schema 如果文件不存在 / 损坏.
    """
    with _VOCAB_LOCK:
        if not os.path.exists(vocab_path):
            return {'schema_version': 1, 'aliases': []}
        try:
            with open(vocab_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'schema_version': 1, 'aliases': []}


def save_vocab(vocab_path: str, data: Dict[str, Any]) -> bool:
    """atomic write vocab.json. 持锁写 + tmp+rename.

    Returns:
        True 写成功, False 写失败 (caller 决定 retry)
    """
    with _VOCAB_LOCK:
        try:
            data['last_modified'] = datetime.utcnow().isoformat() + 'Z'
            os.makedirs(os.path.dirname(vocab_path), exist_ok=True)
            tmp = vocab_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, vocab_path)
            return True
        except Exception:
            return False


def read_then_mutate(vocab_path: str,
                      mutator: Callable[[Dict[str, Any]], Optional[Any]]) -> Any:
    """原子 read-modify-write: 持锁 load → 调 mutator(vocab) → save.

    Args:
        vocab_path: vocab.json 绝对路径
        mutator: 接 vocab dict, 直接 mutate (in-place). 返值会作为本函数返值.
                 若返 None 表示 "无需写回", 跳过 save.

    Returns:
        mutator 的返值 (None = 跳过 save).

    Example:
        def _bump(vocab):
            for a in vocab.get('aliases', []):
                if a['id'] == 'alias_001':
                    a['hit_count'] = a.get('hit_count', 0) + 1
                    return a  # 返非 None → 写回
            return None  # 没找到 → 跳过写
        bumped = read_then_mutate(VOCAB_PATH, _bump)
    """
    with _VOCAB_LOCK:
        vocab = load_vocab(vocab_path)
        result = mutator(vocab)
        if result is not None:
            save_vocab(vocab_path, vocab)
        return result


def get_lock() -> threading.RLock:
    """暴露 lock 给需要复合操作的 caller (e.g. CLI + reflector 都 import 此 module)."""
    return _VOCAB_LOCK
