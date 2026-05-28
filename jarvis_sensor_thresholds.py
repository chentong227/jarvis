# -*- coding: utf-8 -*-
"""[fix44 / Sir 2026-05-28 19:47 P1] sensor thresholds vocab API.

准则 6 持久化 + CLI + reflector — 把原本 hardcode 在 jarvis_env_probe.py /
jarvis_proactive_shield.py 等 sensor 模块内的阈值 / IDE 列表 / 冷却时间
迁出, 持久化到 memory_pool/sensor_thresholds_vocab.json, sensor 模块 lazy
读 + mtime cache, 不再每次拉文件.

思考脑 (inner_thought_daemon) actionable `adjust_sensor_threshold:<path>:<value>`
→ propose_adjustment() 入 review_queue → Sir CLI `scripts/sensor_thresholds_dump.py
proposals/approve/reject/apply/reset` 拍板 → apply_adjustment() 真改 current_values + history.

API:
  get_threshold(path, default=None)        # sensor 读
  get_writable_paths()                      # CLI / inner_thought 看可改 path 列表
  propose_adjustment(path, new_value,       # inner_thought 写 review_queue
                      source, rationale)
  list_review_queue()                       # CLI 看
  apply_adjustment(item_id)                 # Sir CLI 拍板
  reject_adjustment(item_id, reason)        # Sir CLI 拒
  get_history(path=None)                    # CLI 看历史
  reset_to_default(path)                    # Sir CLI 回默认
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, List, Optional, Tuple


_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'sensor_thresholds_vocab.json'
)

# mtime cache (sensor 模块 high-freq 读, 避免每次拉文件)
_CACHE: dict = {
    'data': None,
    'mtime': 0.0,
    'checked_at': 0.0,
}
_CACHE_TTL_S = 5.0  # mtime check 5s 缓存
_LOCK = threading.RLock()


def _vocab_path() -> str:
    """允许 testcase override path."""
    return os.environ.get('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', _VOCAB_PATH)


def _load(force: bool = False) -> dict:
    """Load vocab, mtime cache (5s ttl)."""
    path = _vocab_path()
    now = time.time()
    with _LOCK:
        if (not force and _CACHE['data'] is not None
                and (now - _CACHE['checked_at']) < _CACHE_TTL_S):
            return _CACHE['data']
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            current_mtime = 0.0
        if (not force and _CACHE['data'] is not None
                and current_mtime == _CACHE['mtime']):
            _CACHE['checked_at'] = now
            return _CACHE['data']
        # reload
        if not os.path.exists(path):
            _CACHE['data'] = {
                'enabled': 0,
                'writable_paths': {},
                'review_queue': [],
                'history': [],
            }
            _CACHE['mtime'] = 0.0
            _CACHE['checked_at'] = now
            return _CACHE['data']
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _CACHE['data'] = data
            _CACHE['mtime'] = current_mtime
            _CACHE['checked_at'] = now
            return data
        except (json.JSONDecodeError, OSError):
            # 故障开放: 保留旧 cache, 返空
            if _CACHE['data'] is not None:
                return _CACHE['data']
            return {
                'enabled': 0,
                'writable_paths': {},
                'review_queue': [],
                'history': [],
            }


def _persist(data: dict) -> None:
    """原子写 vocab JSON."""
    path = _vocab_path()
    data['last_modified_at'] = time.time()
    data['last_modified_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S',
                                                 time.localtime())
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    # 让下次 _load force reload
    with _LOCK:
        _CACHE['mtime'] = 0.0
        _CACHE['checked_at'] = 0.0


def invalidate_cache() -> None:
    """让 cache 失效 (testcase 用)."""
    with _LOCK:
        _CACHE['data'] = None
        _CACHE['mtime'] = 0.0
        _CACHE['checked_at'] = 0.0


# ==========================================================================
# Sensor 读 API (lazy cache, low overhead)
# ==========================================================================

def get_threshold(path: str, default: Any = None) -> Any:
    """sensor 模块读取阈值. path eg 'ghost_activity.idle_threshold_s'."""
    data = _load()
    if not data.get('enabled', 1):
        return default
    spec = data.get('writable_paths', {}).get(path)
    if spec is None:
        return default
    return spec.get('current', spec.get('default', default))


def get_writable_paths() -> dict:
    """返 writable_paths schema (CLI / inner_thought 看)."""
    return _load().get('writable_paths', {})


# ==========================================================================
# Validation
# ==========================================================================

def _validate_value(spec: dict, new_value: Any) -> Tuple[bool, str]:
    """根据 spec 校验 new_value 合规. Return (ok, reason)."""
    vtype = spec.get('type', 'str')
    cur = spec.get('current', spec.get('default'))

    if vtype == 'int':
        try:
            new_value = int(new_value)
        except (ValueError, TypeError):
            return False, f'value not int: {new_value!r}'
        lo = spec.get('min')
        hi = spec.get('max')
        if lo is not None and new_value < lo:
            return False, f'new={new_value} < min={lo}'
        if hi is not None and new_value > hi:
            return False, f'new={new_value} > max={hi}'
        cap = spec.get('max_delta_per_change')
        if cap is not None and cur is not None:
            try:
                if abs(int(new_value) - int(cur)) > int(cap):
                    return False, (
                        f'delta={abs(new_value-cur)} > '
                        f'max_delta_per_change={cap}'
                    )
            except (ValueError, TypeError):
                pass
        return True, ''
    if vtype == 'float':
        try:
            new_value = float(new_value)
        except (ValueError, TypeError):
            return False, f'value not float: {new_value!r}'
        lo = spec.get('min')
        hi = spec.get('max')
        if lo is not None and new_value < lo:
            return False, f'new={new_value} < min={lo}'
        if hi is not None and new_value > hi:
            return False, f'new={new_value} > max={hi}'
        return True, ''
    if vtype == 'list_str':
        if not isinstance(new_value, list):
            return False, f'value not list: {type(new_value).__name__}'
        if not all(isinstance(x, str) for x in new_value):
            return False, 'list contains non-str'
        max_items = spec.get('max_items')
        if max_items is not None and len(new_value) > max_items:
            return False, f'len={len(new_value)} > max_items={max_items}'
        return True, ''
    if vtype == 'bool':
        if not isinstance(new_value, bool):
            return False, f'value not bool: {type(new_value).__name__}'
        return True, ''
    if vtype == 'str':
        if not isinstance(new_value, str):
            return False, f'value not str'
        return True, ''
    return False, f'unknown type: {vtype}'


# ==========================================================================
# Review queue (思考脑 / Sir CLI 写, Sir 拍板)
# ==========================================================================

def propose_adjustment(path: str, new_value: Any, source: str,
                          rationale: str = '') -> Tuple[bool, str]:
    """思考脑 / 主脑 propose 一次阈值改动. 入 review_queue 等 Sir 拍板.

    Returns:
      (ok, msg_or_id): ok=True msg=item_id; ok=False msg=reason
    """
    with _LOCK:
        data = _load(force=True)
        spec = data.get('writable_paths', {}).get(path)
        if spec is None:
            return False, f'unknown path: {path}'

        ok, why = _validate_value(spec, new_value)
        if not ok:
            return False, f'validation fail: {why}'

        item_id = f'sta_{int(time.time())}_{uuid.uuid4().hex[:6]}'
        item = {
            'id': item_id,
            'path': path,
            'current_value': spec.get('current'),
            'proposed_value': new_value,
            'source': source,
            'rationale': rationale[:300],
            'state': 'review',
            'created_at': time.time(),
            'created_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                          time.localtime()),
        }
        data.setdefault('review_queue', []).append(item)
        _persist(data)
        return True, item_id


def list_review_queue() -> List[dict]:
    """返当前 review_queue (CLI 看)."""
    data = _load(force=True)
    return list(data.get('review_queue', []))


def apply_adjustment(item_id: str) -> Tuple[bool, str]:
    """Sir CLI 拍板 — 真改 current_value + history. Pop item out review_queue."""
    with _LOCK:
        data = _load(force=True)
        queue = data.get('review_queue', [])
        idx = next((i for i, x in enumerate(queue) if x['id'] == item_id), -1)
        if idx < 0:
            return False, f'item not found: {item_id}'
        item = queue[idx]
        spec = data.get('writable_paths', {}).get(item['path'])
        if spec is None:
            return False, f'path no longer writable: {item["path"]}'

        # re-validate (review 期可能 current 变了, max_delta 可能 fail)
        ok, why = _validate_value(spec, item['proposed_value'])
        if not ok:
            return False, f're-validate fail: {why}'

        old_value = spec.get('current')
        spec['current'] = item['proposed_value']

        history_entry = {
            'item_id': item_id,
            'path': item['path'],
            'old_value': old_value,
            'new_value': item['proposed_value'],
            'source': item['source'],
            'rationale': item['rationale'],
            'action': 'applied',
            'applied_at': time.time(),
            'applied_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                          time.localtime()),
        }
        data.setdefault('history', []).append(history_entry)
        queue.pop(idx)
        _persist(data)
        return True, f'applied: {item["path"]} {old_value!r} → {item["proposed_value"]!r}'


def reject_adjustment(item_id: str, reason: str = '') -> Tuple[bool, str]:
    """Sir CLI 拒一个 proposal. Pop out queue + history.action=rejected."""
    with _LOCK:
        data = _load(force=True)
        queue = data.get('review_queue', [])
        idx = next((i for i, x in enumerate(queue) if x['id'] == item_id), -1)
        if idx < 0:
            return False, f'item not found: {item_id}'
        item = queue[idx]
        history_entry = {
            'item_id': item_id,
            'path': item['path'],
            'old_value': item['current_value'],
            'new_value': item['proposed_value'],
            'source': item['source'],
            'rationale': item['rationale'],
            'reject_reason': reason[:200],
            'action': 'rejected',
            'rejected_at': time.time(),
            'rejected_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                            time.localtime()),
        }
        data.setdefault('history', []).append(history_entry)
        queue.pop(idx)
        _persist(data)
        return True, f'rejected: {item["path"]}'


def get_history(path: Optional[str] = None,
                  limit: int = 50) -> List[dict]:
    """看 history (Sir CLI). path=None 全看, 指定 path 过滤."""
    data = _load(force=True)
    hist = data.get('history', [])
    if path is not None:
        hist = [h for h in hist if h.get('path') == path]
    return hist[-limit:]


def reset_to_default(path: str) -> Tuple[bool, str]:
    """Sir CLI 回默认值."""
    with _LOCK:
        data = _load(force=True)
        spec = data.get('writable_paths', {}).get(path)
        if spec is None:
            return False, f'unknown path: {path}'
        old = spec.get('current')
        spec['current'] = spec.get('default')
        history_entry = {
            'path': path,
            'old_value': old,
            'new_value': spec.get('default'),
            'action': 'reset_to_default',
            'reset_at': time.time(),
            'reset_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
        }
        data.setdefault('history', []).append(history_entry)
        _persist(data)
        return True, f'reset: {path} {old!r} → {spec.get("default")!r}'


# ==========================================================================
# Public validation + Sir 元否决 direct-apply API (CLI 用)
# ==========================================================================

def validate_value(path: str, new_value: Any) -> Tuple[bool, str]:
    """Public — CLI dry-run 用 (Sir 看 propose 会不会过 validate)."""
    data = _load(force=True)
    spec = data.get('writable_paths', {}).get(path)
    if spec is None:
        return False, f'unknown path: {path}'
    return _validate_value(spec, new_value)


def apply_direct(path: str, new_value: Any, source: str = 'sir_cli',
                    rationale: str = '') -> Tuple[bool, str]:
    """Sir 元否决 (准则 7) — 直接改 current 跳过 review queue.

    走完整 validate + history. 用于:
      - Sir CLI `apply` 直改
      - test fixture 注入
    """
    with _LOCK:
        data = _load(force=True)
        spec = data.get('writable_paths', {}).get(path)
        if spec is None:
            return False, f'unknown path: {path}'
        ok, why = _validate_value(spec, new_value)
        if not ok:
            return False, f'validation fail: {why}'
        old_value = spec.get('current')
        spec['current'] = new_value
        history_entry = {
            'item_id': f'direct_{int(time.time())}_{uuid.uuid4().hex[:6]}',
            'path': path,
            'old_value': old_value,
            'new_value': new_value,
            'source': source,
            'rationale': rationale[:300],
            'action': 'applied_direct',
            'applied_at': time.time(),
            'applied_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                          time.localtime()),
        }
        data.setdefault('history', []).append(history_entry)
        _persist(data)
        return True, f'applied_direct: {path} {old_value!r} → {new_value!r}'
