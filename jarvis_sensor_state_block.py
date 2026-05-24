# -*- coding: utf-8 -*-
"""[P5-fix53 / 2026-05-23 15:30] [SENSOR STATE] block builder — 主脑 prompt 注入 Sir 真实物理状态.

Sir 15:27 真痛点 + 15:29 深层痛点 + 15:31 设计指示:
  '主脑必须知道我的一切信息, 才能保证话术不是 hallucinate'
  '动态注入, 不是全量 prompt, 这和后面 prompt 瘦身重构有关, 可以提前落位'
  '准则 6 持久化, 不要硬编码, 优雅高效可维护'

设计 (准则 6 三维耦合 + 准则 8 优雅):
  1. **数据强耦合**: vocab JSON `memory_pool/sensor_state_inject_vocab.json` 持久化字段 list
  2. **行为弱耦合**: 按 tier 注入子集 (SHORT_CHAT 紧凑 / CHAT 中等 / DEEP_QUERY 全量)
  3. **决策集中主脑**: 主脑 prompt 看 raw evidence, 自决用哪个字段 reply

预先落位 (post-fix53 prompt 瘦身 refactor):
  - central_nerve 仅调 `build_sensor_state_block(tier, max_chars)` (3 行)
  - 后续 refactor 直接复用 builder, 不再改 central_nerve
  - Sir CLI scripts/sensor_state_dump.py 看/激活/拒字段, 不需改 .py

API:
  build_sensor_state_block(tier='CHAT', max_chars=600) -> str
    tier: 'SHORT_CHAT' | 'CHAT' | 'DEEP_QUERY' (按需选不同字段集)
    max_chars: 防 token 爆炸
    返回 multi-line 'SENSOR STATE' block 或 '' (vocab 没字段时).

  reload_vocab() -> None
    强制 reload vocab JSON (CLI 改后).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

_VOCAB_PATH = Path(__file__).parent / 'memory_pool' / 'sensor_state_inject_vocab.json'
_VOCAB_CACHE: Optional[dict] = None
_VOCAB_MTIME: float = 0.0
_VOCAB_TTL_S: float = 5.0
_LAST_LOAD_T: float = 0.0


def _load_vocab() -> Optional[dict]:
    """Load vocab JSON with mtime cache + TTL."""
    global _VOCAB_CACHE, _VOCAB_MTIME, _LAST_LOAD_T
    now = time.time()
    if _VOCAB_CACHE is not None and (now - _LAST_LOAD_T) < _VOCAB_TTL_S:
        return _VOCAB_CACHE
    try:
        if not _VOCAB_PATH.exists():
            return None
        mtime = _VOCAB_PATH.stat().st_mtime
        if _VOCAB_CACHE is not None and mtime == _VOCAB_MTIME:
            _LAST_LOAD_T = now
            return _VOCAB_CACHE
        _VOCAB_CACHE = json.loads(_VOCAB_PATH.read_text(encoding='utf-8'))
        _VOCAB_MTIME = mtime
        _LAST_LOAD_T = now
        return _VOCAB_CACHE
    except Exception:
        return None


def reload_vocab() -> None:
    """Force vocab reload (CLI 改 vocab 后)."""
    global _VOCAB_CACHE, _VOCAB_MTIME, _LAST_LOAD_T
    _VOCAB_CACHE = None
    _VOCAB_MTIME = 0.0
    _LAST_LOAD_T = 0.0


def _resolve_value(source: str) -> object:
    """source = 'Module.attr' → 拿 attribute 值. 失败返 None."""
    try:
        if '.' not in source:
            return None
        mod_name, attr = source.rsplit('.', 1)
        if mod_name == 'PhysicalEnvironmentProbe':
            from jarvis_env_probe import PhysicalEnvironmentProbe as _M
            return getattr(_M, attr, None)
        # extensible: support more sources
        return None
    except Exception:
        return None


def _apply_transform(val, transform: str):
    """转换 raw value 到展示格式. 容错."""
    if transform == 'int_default_0':
        try:
            return int(val or 0)
        except (TypeError, ValueError):
            return 0
    if transform == 'str_truncate_80':
        return (str(val) if val else '')[:80]
    if transform == 'str_truncate_40':
        return (str(val) if val else '')[:40]
    if transform == 'str_default_idle':
        return str(val) if val else 'Idle'
    if transform == 'bool':
        return bool(val)
    if transform == 'elapsed_minutes':
        # 🆕 [Sir 真测 BUG-2 治本 / 2026-05-24] gaming_started_at (timestamp) → 已 N min
        # val=0 (never started) → 返 0. val>0 (ts) → 算 now - ts, 转 min.
        try:
            ts = float(val or 0)
            if ts <= 0:
                return 0
            elapsed_s = max(0, time.time() - ts)
            return int(elapsed_s / 60)
        except (TypeError, ValueError):
            return 0
    return val


def build_sensor_state_block(tier: str = 'CHAT', max_chars: int = 600) -> str:
    """Build [SENSOR STATE] block per tier 配置.

    Args:
        tier: 'SHORT_CHAT' / 'CHAT' / 'DEEP_QUERY' — 按 vocab field.tiers 过滤
        max_chars: budget 上限, 超过截断

    Returns:
        multi-line block 或 '' (vocab miss / 全 inactive)
    """
    vocab = _load_vocab()
    if not vocab:
        return ''
    fields = vocab.get('fields', [])
    if not fields:
        return ''
    header = vocab.get('header_text', '[SENSOR STATE]:')
    footer = vocab.get('footer_text', '')
    lines = [header]
    # 🆕 [Sir 真测 BUG-2 治本 / 2026-05-24] 第 1 pass 收集 raw values, 用于 gating
    # (e.g. gaming_title 仅在 is_gaming_active=True 时 inject — 否则浪费 token).
    raw_by_id: dict = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        fid = field.get('id', '')
        if fid:
            raw_by_id[fid] = _resolve_value(field.get('source', ''))
    for field in fields:
        if not isinstance(field, dict):
            continue
        if not field.get('active', True):
            continue
        tiers = field.get('tiers', [])
        if tier not in tiers:
            continue
        fid = field.get('id', '')
        if not fid:
            continue
        # 🆕 [BUG-2 治本] gating_field: 仅在另一字段 truthy 时 inject 本字段.
        gating_field = field.get('gating_field')
        if gating_field:
            gating_raw = raw_by_id.get(gating_field)
            if not gating_raw:
                continue  # gating field falsy → skip 本字段
        raw = raw_by_id.get(fid)
        val = _apply_transform(raw, field.get('transform', ''))
        label = field.get('label', fid)
        annot = field.get('annotation', '')
        fmt = field.get('format', '{value}')
        try:
            val_str = fmt.format(value=val)
        except Exception:
            val_str = str(val)
        if annot:
            lines.append(f"  {label}: {val_str}  ({annot})")
        else:
            lines.append(f"  {label}: {val_str}")
    if footer:
        lines.append(footer)
    block = '\n'.join(lines)
    if len(block) > max_chars:
        block = block[:max_chars - 20] + '\n  ...(truncated)'
    return block


def list_active_fields(tier: str = 'CHAT') -> list:
    """Return list of active field ids for a tier (for CLI / inspection)."""
    vocab = _load_vocab()
    if not vocab:
        return []
    out = []
    for f in vocab.get('fields', []):
        if not isinstance(f, dict):
            continue
        if not f.get('active', True):
            continue
        if tier in f.get('tiers', []):
            out.append(f.get('id'))
    return [x for x in out if x]
