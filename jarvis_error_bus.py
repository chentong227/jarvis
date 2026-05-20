# -*- coding: utf-8 -*-
"""[β.5.43-F / 2026-05-20 19:10] Error Self-Healing Bus

Sir 17:10 真理 — 6 缺口 F: '系统出错时主动告诉 Sir, 不装作没事'.

Jarvis 当前有大量 try/except 静默吞错 (key_router fail / LLM timeout / tool fail /
ASR drop / SirRequestReflector LLM fail / IntentResolver tool fail / ProactiveCare 
sensor 异常 / ...). Sir 不知道这些 silently fail, 主脑也不知道, 主脑可能基于"系统
正常" 假设答复 Sir 实际有 bug. 

设计 (β.5.0 三维耦合 + Sir 准则 6):
1. ErrorBus 集中收 module 出错 (ErrorBus.report(module, kind, detail))
2. 持久化 memory_pool/system_errors.jsonl (rolling 1000 条)
3. publish SWM 'system_error_visible' (sal 0.85, TTL 600s)
4. 主脑 prompt _assemble 注入 [SYSTEM ERRORS THIS TURN] block
5. dashboard /api/system_errors + banner 显示
6. Sir 看 banner 知道 Jarvis 哪里坏了, Jarvis 自己 reply 也能 surface 错误状态

不是 alert 系统 (吵闹), 是诚实暴露 — 主脑可以基于真实状态 reply.
准则 6 (vocab 持久化): error_kinds vocab json + CLI scripts/error_kinds_dump.py (后续).

doc 推断: β.5.43-F (Sir 17:10 6 缺口 F, 主诉 'error 暴露')
"""
from __future__ import annotations

import json
import os
import time
import threading
from collections import deque
from typing import Any, Dict, List, Optional


_BUS_INSTANCE: Optional['ErrorBus'] = None
_LOCK = threading.Lock()

ERROR_BUS_CONFIG = {
    'persist_path': os.path.join('memory_pool', 'system_errors.jsonl'),
    'in_memory_max': 200,         # 在内存最多 200 条 (避免 unbounded)
    'persist_max': 1000,           # 文件最多 1000 条 (rolling)
    'dedupe_window_s': 60,         # 同 (module, kind) 1min 内去重
    'swm_publish_threshold': 'minor',  # minor 以上 publish SWM
}


# 错误严重度: minor (静默, 主脑不主动提) / moderate (主脑可 surface) / severe (主脑必 surface)
SEVERITY_MINOR = 'minor'
SEVERITY_MODERATE = 'moderate'
SEVERITY_SEVERE = 'severe'

_SEVERITY_ORDER = {SEVERITY_MINOR: 1, SEVERITY_MODERATE: 2, SEVERITY_SEVERE: 3}


class ErrorBus:
    """集中收 module 出错 + 持久化 + SWM publish."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(ERROR_BUS_CONFIG)
        if config:
            self.config.update(config)
        self._lock = threading.Lock()
        self._buffer = deque(maxlen=self.config['in_memory_max'])
        self._dedupe = {}  # (module, kind) -> last_ts
        self._stats = {
            'total_reports': 0,
            'dedupe_skipped': 0,
            'swm_published': 0,
            'persisted': 0,
        }
        # ensure dir
        try:
            os.makedirs(
                os.path.dirname(self.config['persist_path']) or '.',
                exist_ok=True,
            )
        except Exception:
            pass

    def report(
        self,
        module: str,
        kind: str,
        detail: str = '',
        severity: str = SEVERITY_MODERATE,
        recoverable: bool = True,
        suggested_action: str = '',
    ) -> bool:
        """报告一个错误.
        
        Args:
          module: 来源模块 (e.g. 'key_router', 'intent_resolver', 'proactive_care')
          kind: 错误类型 (e.g. 'llm_timeout', 'api_quota', 'sensor_fail', 'tool_fail')
          detail: 详细描述 (堆栈片段 / 触发 context)
          severity: minor / moderate / severe
          recoverable: 是否可自愈 (False = Sir 必须介入)
          suggested_action: 主脑/Sir 可参考的修复建议
        
        Returns: True = recorded, False = dedupe skipped
        """
        if not module or not kind:
            return False
        if severity not in _SEVERITY_ORDER:
            severity = SEVERITY_MODERATE
        now = time.time()
        with self._lock:
            self._stats['total_reports'] += 1
            # dedupe
            dkey = (module, kind)
            last_ts = self._dedupe.get(dkey, 0)
            if now - last_ts < self.config['dedupe_window_s']:
                self._stats['dedupe_skipped'] += 1
                return False
            self._dedupe[dkey] = now

            entry = {
                'ts': now,
                'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
                'module': str(module)[:60],
                'kind': str(kind)[:60],
                'detail': str(detail)[:500],
                'severity': severity,
                'recoverable': bool(recoverable),
                'suggested_action': str(suggested_action)[:200],
            }
            self._buffer.append(entry)

            # persist (append jsonl, rolling 后台处理)
            try:
                with open(self.config['persist_path'], 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
                self._stats['persisted'] += 1
            except Exception:
                pass

        # publish SWM (in main thread or worker, lock-free here)
        try:
            self._publish_swm(entry)
        except Exception:
            pass

        # bg log
        try:
            from jarvis_utils import bg_log
            sev_icon = {'minor': '⚪', 'moderate': '🟡', 'severe': '🔴'}.get(severity, '?')
            bg_log(
                f"{sev_icon} [ErrorBus] {module}/{kind} — "
                f"{str(detail)[:80]}{' (recoverable)' if recoverable else ' (NEEDS SIR)'}"
            )
        except Exception:
            pass

        return True

    def _publish_swm(self, entry: Dict) -> None:
        """publish 'system_error_visible' SWM event."""
        thresh = self.config.get('swm_publish_threshold', 'minor')
        if _SEVERITY_ORDER[entry['severity']] < _SEVERITY_ORDER.get(thresh, 1):
            return
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            sev_to_sal = {
                SEVERITY_MINOR: 0.50,
                SEVERITY_MODERATE: 0.75,
                SEVERITY_SEVERE: 0.92,
            }
            sal = sev_to_sal.get(entry['severity'], 0.75)
            bus.publish(
                etype='system_error_visible',
                description=(
                    f"[{entry['module']}] {entry['kind']}: "
                    f"{entry['detail'][:120]}"
                ),
                source='ErrorBus',
                salience=sal,
                metadata={
                    'module': entry['module'],
                    'kind': entry['kind'],
                    'detail': entry['detail'],
                    'severity': entry['severity'],
                    'recoverable': entry['recoverable'],
                    'suggested_action': entry['suggested_action'],
                    'iso': entry['iso'],
                },
            )
            with self._lock:
                self._stats['swm_published'] += 1
        except Exception:
            pass

    def recent_errors(
        self,
        within_seconds: float = 600.0,
        min_severity: str = SEVERITY_MINOR,
        max_n: int = 20,
    ) -> List[Dict]:
        """返回最近 N 条 error (新 → 老), 按 severity 过滤."""
        cutoff = time.time() - within_seconds
        min_sev_v = _SEVERITY_ORDER.get(min_severity, 1)
        with self._lock:
            arr = [
                e for e in self._buffer
                if e['ts'] >= cutoff
                and _SEVERITY_ORDER.get(e['severity'], 1) >= min_sev_v
            ]
        arr.sort(key=lambda e: -e['ts'])
        return arr[:max_n]

    def stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)

    def clear_dedupe(self) -> None:
        """手动清 dedupe (e.g. 测试场景)."""
        with self._lock:
            self._dedupe.clear()


# ---------------- 全局 singleton + 便捷 helpers ----------------

def get_error_bus() -> ErrorBus:
    """获 ErrorBus singleton (lazy init)."""
    global _BUS_INSTANCE
    with _LOCK:
        if _BUS_INSTANCE is None:
            _BUS_INSTANCE = ErrorBus()
        return _BUS_INSTANCE


def report_error(
    module: str,
    kind: str,
    detail: str = '',
    severity: str = SEVERITY_MODERATE,
    recoverable: bool = True,
    suggested_action: str = '',
) -> bool:
    """便捷 helper: get_error_bus().report(...). 
    
    用法:
        from jarvis_error_bus import report_error
        try:
            tool_X()
        except Exception as e:
            report_error('intent_resolver', 'tool_call_fail',
                         detail=f'{tool_name}: {e}', severity='moderate')
    """
    return get_error_bus().report(
        module=module, kind=kind, detail=detail, severity=severity,
        recoverable=recoverable, suggested_action=suggested_action,
    )
