# -*- coding: utf-8 -*-
"""[Reshape M8.A / 2026-05-24] Unified mem_audit.jsonl — 5 audit log 合并 + read facade.

# 治本目标 (Sir reshape doc M8)

5 老 audit log 散落:
    - memory_pool/mutation_receipts.jsonl    (MemoryHub.write_* 真执行)
    - memory_pool/profile_corrections.jsonl  (ProfileCard.apply_correction 老路)
    - memory_pool/claim_revisions.json       (ClaimTracer 反幻觉 review)
    - memory_pool/claim_stats.json           (ClaimTracer stats snapshot)
    - memory_pool/integrity_audit.jsonl      (ClaimTracer unverified entries)

合 1 → memory_pool/mem_audit.jsonl (单源):
    每行 {kind, ts, iso, source, ...record_data}
    kind 标识来源: 'mutation' / 'correction' / 'claim_revision' / 'claim_stat' /
                   'integrity_unverified' / ...

# 当前阶段 (M8.A MVP, 不破老 file)

dual-write 兼容:
    - 5 老 file 仍写 (老 caller / dashboard 不破)
    - mem_audit.jsonl 也写 (新 caller + 主脑可统一查)
    - 未来 caller 全切 mem_audit.jsonl 后, 老 file 转 _legacy/

read_unified() facade:
    - 读 mem_audit.jsonl + 5 老 file
    - 按 ts 合并去重 (5 老 file 的 record dual-written 进 mem_audit, 后者 fresh)
    - 让 dashboard / Sir 一处看全 audit

# 为什么是 jsonl

- append-only 不破历史
- 故障 partial line 不影响其他行
- mutation_dump 等 scripts 已用 jsonl 风格

# 接口

- write_audit(record, kind, source='') — 写 1 条 audit (caller 用)
- read_unified(limit=200, kinds=None) — 读 facade
- get_default() — 单例

# 兼容期 dual-write hook

caller 用 write_audit() 时:
    1. 写 mem_audit.jsonl
    2. 按 kind 标识同时 dual-write 到老 file (兼容期默认 ON, env JARVIS_MEM_AUDIT_NO_DUAL=1 关)

未来:
    M8.B+ caller 全切 write_audit() → 关 dual-write → 老 file 转 _legacy/
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set


# ============================================================
# Path / Config
# ============================================================

MEM_DIR = 'memory_pool'
UNIFIED_PATH = os.path.join(MEM_DIR, 'mem_audit.jsonl')

# 老 file paths (兼容期 dual-write 目标)
LEGACY_PATHS = {
    'mutation': os.path.join(MEM_DIR, 'mutation_receipts.jsonl'),
    'correction': os.path.join(MEM_DIR, 'profile_corrections.jsonl'),
    'claim_revision': os.path.join(MEM_DIR, 'claim_revisions.json'),
    'claim_stat': os.path.join(MEM_DIR, 'claim_stats.json'),
    'integrity_unverified': os.path.join(MEM_DIR, 'integrity_audit.jsonl'),
}

VALID_KINDS = set(LEGACY_PATHS.keys()) | {
    'lineage_evidence',  # M1 lineage trace event (新 kind)
    'system_event',       # 通用 catch-all
}


def _is_dual_write_disabled() -> bool:
    val = os.environ.get('JARVIS_MEM_AUDIT_NO_DUAL', '').strip()
    return val in ('1', 'true', 'True', 'yes', 'on')


# ============================================================
# Writer
# ============================================================

_WRITE_LOCK = threading.Lock()


def _ensure_dir() -> None:
    try:
        os.makedirs(MEM_DIR, exist_ok=True)
    except Exception:
        pass


def _normalize_record(record: Dict[str, Any], kind: str,
                       source: str) -> Dict[str, Any]:
    """补足必要字段 (ts/iso/kind/source) 并保持原 caller 数据不丢失."""
    out = dict(record) if isinstance(record, dict) else {'data': record}
    if 'ts' not in out:
        out['ts'] = time.time()
    if 'iso' not in out:
        try:
            out['iso'] = time.strftime('%Y-%m-%dT%H:%M:%S',
                                         time.localtime(out['ts']))
        except Exception:
            out['iso'] = ''
    out['kind'] = kind
    if source and 'source' not in out:
        out['source'] = source
    return out


def _append_jsonl(path: str, record: Dict[str, Any]) -> bool:
    try:
        line = json.dumps(record, ensure_ascii=False)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        return True
    except Exception:
        return False


def _write_json_singleton(path: str, record: Dict[str, Any]) -> bool:
    """For claim_stats.json / claim_revisions.json (json singleton, not jsonl)."""
    try:
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing = json.load(f) or {}
            except Exception:
                existing = {}
        # use 'updates' list (append) or merge top-level
        if isinstance(existing, dict):
            updates = existing.setdefault('updates', [])
            if isinstance(updates, list):
                updates.append(record)
                # cap at 500 most recent
                existing['updates'] = updates[-500:]
            existing['last_update_ts'] = record.get('ts', time.time())
            existing['last_update_iso'] = record.get('iso', '')
        else:
            existing = {'updates': [record], 'last_update_ts': record.get('ts', time.time())}
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def write_audit(record: Dict[str, Any], kind: str = 'system_event',
                 source: str = '', dual_write: Optional[bool] = None) -> bool:
    """写 1 条 audit 到 mem_audit.jsonl (+ optional dual-write 老 file).

    Args:
        record: 字段 dict (caller 自由 schema)
        kind: 'mutation' / 'correction' / 'claim_revision' / 'claim_stat' /
              'integrity_unverified' / 'lineage_evidence' / 'system_event'
        source: 调用 source 标 (e.g. 'MemoryHub.write_identity', 'ProfileCard.apply_correction')
        dual_write: None (default) → 跟 env 决定; True/False → override

    Returns: True if mem_audit.jsonl 写成功 (legacy file 失败不影响).
    """
    _ensure_dir()
    rec = _normalize_record(record, kind, source)
    ok_unified = False
    with _WRITE_LOCK:
        ok_unified = _append_jsonl(UNIFIED_PATH, rec)
        # dual write (老 file 兼容期)
        do_dual = (not _is_dual_write_disabled()) if dual_write is None else dual_write
        if do_dual and kind in LEGACY_PATHS:
            legacy_path = LEGACY_PATHS[kind]
            if kind in ('claim_revision', 'claim_stat'):
                # json singleton 格式
                _write_json_singleton(legacy_path, rec)
            else:
                # jsonl append
                _append_jsonl(legacy_path, rec)
    return ok_unified


# ============================================================
# Reader
# ============================================================


def _read_jsonl(path: str, max_lines: int = 1000) -> List[Dict[str, Any]]:
    """Tail-read jsonl (最近 max_lines)."""
    if not os.path.exists(path):
        return []
    try:
        out: List[Dict[str, Any]] = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f.readlines()[-max_lines:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        out.append(rec)
                except Exception:
                    continue
        return out
    except Exception:
        return []


def _read_json_singleton(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        updates = data.get('updates', [])
        if isinstance(updates, list):
            return [u for u in updates if isinstance(u, dict)]
        return []
    except Exception:
        return []


def read_unified(limit: int = 200, kinds: Optional[Set[str]] = None,
                  include_legacy: bool = True) -> List[Dict[str, Any]]:
    """读 unified audit (mem_audit.jsonl + 老 5 file 合并).

    Args:
        limit: 总返回上限
        kinds: 过滤 kind (None = 全 kind)
        include_legacy: True (default) → 合并读老 file (兼容期);
                        False → 只读 mem_audit.jsonl

    Returns: list of audit records, 按 ts 倒序 (最新在前).
    """
    out: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()  # dedup by (ts, kind, source) hash

    def _dedup_key(r: Dict[str, Any]) -> str:
        # 含 ts + kind + source + content hash — 同 ts 同 kind 同 source 但 content 不同
        # 不 dedup. content_hash 用 sorted json (除 ts/iso/kind/source 外的 payload).
        try:
            payload = {k: v for k, v in r.items()
                        if k not in ('ts', 'iso', 'kind', 'source')}
            content_repr = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            content_repr = str(r)
        return (f"{r.get('ts', 0)}-{r.get('kind', '')}-"
                f"{r.get('source', '')}-{hash(content_repr)}")

    # 1. 读 unified
    unified = _read_jsonl(UNIFIED_PATH, max_lines=max(limit * 2, 500))
    for r in unified:
        if kinds and r.get('kind') not in kinds:
            continue
        k = _dedup_key(r)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        out.append(r)

    # 2. 读老 file (dual-write fallback - 应已在 unified, 但兜底)
    if include_legacy:
        for kind, path in LEGACY_PATHS.items():
            if kinds and kind not in kinds:
                continue
            if kind in ('claim_revision', 'claim_stat'):
                records = _read_json_singleton(path)
            else:
                records = _read_jsonl(path, max_lines=max(limit * 2, 500))
            for r in records:
                # 补 kind (老 file 没标)
                r.setdefault('kind', kind)
                k = _dedup_key(r)
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                out.append(r)

    # 3. 排序 + 截断
    out.sort(key=lambda r: float(r.get('ts', 0) or 0), reverse=True)
    return out[:limit]


# ============================================================
# Helpers
# ============================================================


def get_audit_stats() -> Dict[str, Any]:
    """简单统计: 各 kind 的 record count + 文件 size."""
    stats = {
        'unified_path': UNIFIED_PATH,
        'unified_exists': os.path.exists(UNIFIED_PATH),
        'unified_size': 0,
        'unified_lines': 0,
        'legacy': {},
        'dual_write_enabled': not _is_dual_write_disabled(),
    }
    if stats['unified_exists']:
        try:
            stats['unified_size'] = os.path.getsize(UNIFIED_PATH)
            with open(UNIFIED_PATH, 'r', encoding='utf-8') as f:
                stats['unified_lines'] = sum(1 for _ in f)
        except Exception:
            pass
    for kind, path in LEGACY_PATHS.items():
        info = {'path': path, 'exists': os.path.exists(path), 'size': 0}
        if info['exists']:
            try:
                info['size'] = os.path.getsize(path)
            except Exception:
                pass
        stats['legacy'][kind] = info
    return stats
