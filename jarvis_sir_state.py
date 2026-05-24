# -*- coding: utf-8 -*-
"""[Reshape M8.B / 2026-05-24] Unified sir_state.json — 3 state file 合并 + read facade.

# 治本目标 (Sir reshape doc M8)

3 state file 散落:
    - memory_pool/sir_status.json       (SirStatusStore: active/AFK/online/sleep/focus/mood)
    - memory_pool/stand_down_state.json (StandDown: 全局 stand_down 模式 active/since/until)
    - memory_pool/sir_acked_state.json  (ActionableItems: item_id → ack_ts)

合 1 → memory_pool/sir_state.json (单源 schema):

    {
        '_meta': {...},
        'physical': {'sleeping', 'AFK', 'idle_seconds', 'status', ...},
        'attention': {'focus_window', 'category', ...},
        'mood': {'last_known', 'updated_at', ...},
        'stand_down': {'mode', 'reason', 'until', ...},
        'acked': {'last_ack_turn', 'last_ack_at', 'item_acks', ...}
    }

# 当前阶段 (M8.B MVP, 不破老 file)

read_unified() facade:
    - 读 3 老 file 合并到 schema dict
    - 让 dashboard / 主脑 prompt / debug 一处看全 state
    - 老 caller 仍写老 file (不破)

# 写入策略 (后续阶段)

M8.B+ 真合并: 各 owner module 写老 file 时 dual-write 到 sir_state.json
M9+ 老 file 转 _legacy/, sir_state.json 是单源.

# 接口

- read_unified() → Dict (合并 3 老 file)
- get_physical_state() / get_attention_state() / get_mood() / get_stand_down() /
  get_acked_state() → 各分类便利 getter
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional


MEM_DIR = 'memory_pool'
UNIFIED_PATH = os.path.join(MEM_DIR, 'sir_state.json')

LEGACY_PATHS = {
    'sir_status': os.path.join(MEM_DIR, 'sir_status.json'),
    'stand_down': os.path.join(MEM_DIR, 'stand_down_state.json'),
    'sir_acked': os.path.join(MEM_DIR, 'sir_acked_state.json'),
}


def _read_json_safe(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# ============================================================
# Read facade
# ============================================================


def get_physical_state() -> Dict[str, Any]:
    """从 sir_status.json 读 physical state."""
    data = _read_json_safe(LEGACY_PATHS['sir_status'])
    if not data:
        return {'status': 'unknown'}
    cur = data.get('current', {}) or {}
    return {
        'status': cur.get('status', 'unknown'),
        'since_ts': cur.get('since_ts', 0.0),
        'since_iso': cur.get('since_iso', ''),
        'expected_return_s': cur.get('expected_return_s', 0.0),
        'last_keyword': cur.get('last_keyword', ''),
        # AFK / sleeping flags 从 status 推
        'sleeping': cur.get('status') in ('sleeping', 'deep_sleep'),
        'AFK': cur.get('status') in ('afk', 'away'),
        'active': cur.get('status') == 'active',
    }


def get_attention_state() -> Dict[str, Any]:
    """从 sir_status.json 提 attention info (focus_window etc.)."""
    data = _read_json_safe(LEGACY_PATHS['sir_status'])
    if not data:
        return {}
    return data.get('attention', {}) or {}


def get_mood() -> Dict[str, Any]:
    data = _read_json_safe(LEGACY_PATHS['sir_status'])
    if not data:
        return {}
    return data.get('mood', {}) or {}


def get_stand_down_state() -> Dict[str, Any]:
    data = _read_json_safe(LEGACY_PATHS['stand_down'])
    if not data:
        return {'active': False}
    return {
        'active': bool(data.get('active', False)),
        'since_ts': data.get('since_ts', 0.0),
        'until_ts': data.get('until_ts', 0.0),
        'reason': data.get('reason', ''),
        'exit_hint': data.get('exit_hint', ''),
        'set_by_turn': data.get('set_by_turn', ''),
        'set_by_source': data.get('set_by_source', ''),
        'grace_until_ts': data.get('grace_until_ts', 0.0),
        'cleared_at_ts': data.get('cleared_at_ts', 0.0),
    }


def get_acked_state() -> Dict[str, Any]:
    data = _read_json_safe(LEGACY_PATHS['sir_acked'])
    if not data:
        return {'item_acks': {}}
    return {
        'item_acks': data.get('item_acks', {}),
        'last_ack_turn': data.get('last_ack_turn', ''),
        'last_ack_at': data.get('last_ack_at', 0.0),
    }


def read_unified() -> Dict[str, Any]:
    """读 3 老 file 合并 into 统一 schema dict.

    返 schema:
        {
            '_meta': {'read_ts', 'read_iso', 'sources_present'},
            'physical': {...},
            'attention': {...},
            'mood': {...},
            'stand_down': {...},
            'acked': {...},
        }
    """
    now = time.time()
    sources_present = {
        name: os.path.exists(path) for name, path in LEGACY_PATHS.items()
    }
    return {
        '_meta': {
            'read_ts': now,
            'read_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            'sources_present': sources_present,
            'unified_path_exists': os.path.exists(UNIFIED_PATH),
        },
        'physical': get_physical_state(),
        'attention': get_attention_state(),
        'mood': get_mood(),
        'stand_down': get_stand_down_state(),
        'acked': get_acked_state(),
    }


# ============================================================
# Write facade (兼容期 dual-write, 后续 M8.B+ 真启用)
# ============================================================


def write_unified_snapshot() -> bool:
    """读 3 老 file 合并写 sir_state.json snapshot.

    用途:
        - dashboard 周期 dump unified snapshot 让 Sir 一处看
        - debug: snapshot 时间点的 state 状态

    NOTE: 不取代老 file 写入. 老 caller 仍写各自 file.
    """
    try:
        snapshot = read_unified()
        os.makedirs(MEM_DIR, exist_ok=True)
        tmp = UNIFIED_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp, UNIFIED_PATH)
        return True
    except Exception:
        return False


def render_state_block(max_chars: int = 800) -> str:
    """渲染 state block 给主脑 prompt 看 (统一格式)."""
    s = read_unified()
    lines = ['[SIR STATE — unified]']
    p = s['physical']
    if p.get('status', 'unknown') != 'unknown':
        lines.append(f"  physical: status={p['status']}")
        if p.get('sleeping'):
            lines.append(f"    (sleeping)")
        if p.get('AFK'):
            lines.append(f"    (AFK, since={p.get('since_iso', '')})")
    sd = s['stand_down']
    if sd.get('active'):
        until_iso = ''
        try:
            until_iso = time.strftime('%H:%M', time.localtime(sd.get('until_ts', 0)))
        except Exception:
            pass
        lines.append(f"  stand_down: ACTIVE (reason='{sd.get('reason', '')}', until={until_iso})")
    a = s['attention']
    if a.get('focus_window'):
        lines.append(f"  attention: window='{a.get('focus_window', '')[:60]}', "
                     f"cat='{a.get('category', '')}'")
    m = s['mood']
    if m.get('last_known'):
        lines.append(f"  mood: {m.get('last_known')} ({m.get('updated_at', '')})")
    out = '\n'.join(lines)
    if len(out) > max_chars:
        out = out[:max_chars - 15] + '\n...(truncated)'
    return out
