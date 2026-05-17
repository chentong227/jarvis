# -*- coding: utf-8 -*-
"""
[P0+20-β.2.8.6 / 2026-05-17] Jarvis 自身健康自检 daemon

Sir 22:42 反馈: "我们持续运行的脚本需要 2G 的持续内存, 是正常的吗?
没有什么内存残留导致的问题吧?"

每 5min 自检:
- WorkingSet (RAM 实占)
- Private (虚拟保留)
- Threads count
- Handles count
- 增长率 (compared to baseline / last sample)

异常阈值告警 (bg_log + 可选 nudge):
- threads > 800 → 严重泄漏
- private > 15 GB → 异常增长
- WS 增长 > 30% in 30min → 内存泄漏怀疑

数据写 memory_pool/jarvis_health_history.jsonl 供长期趋势分析.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import List, Optional, Dict

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


HEALTH_HISTORY_PATH = os.path.join('memory_pool', 'jarvis_health_history.jsonl')
SAMPLE_INTERVAL_S = 300.0  # 5min
HISTORY_MAX_LINES = 2880   # 5min * 2880 ≈ 10 天

# 告警阈值
THRESHOLD_THREADS = 800
THRESHOLD_PRIVATE_GB = 15.0
THRESHOLD_WS_GROWTH_PCT_30MIN = 30.0   # 30min 内涨 >30% → 警


class HealthProbeDaemon(threading.Thread):
    """每 5min 自检, 记录 jsonl + 异常告警."""

    def __init__(self, interval_s: float = SAMPLE_INTERVAL_S,
                  history_path: Optional[str] = None):
        super().__init__(daemon=True, name='HealthProbeDaemon')
        self.interval = interval_s
        self.history_path = history_path or HEALTH_HISTORY_PATH
        self._stop = threading.Event()
        self._history: List[Dict] = []
        self._baseline: Optional[Dict] = None

    def stop(self) -> None:
        self._stop.set()

    def sample(self) -> Optional[Dict]:
        """采一份 process 健康快照. psutil 不可用返回 None."""
        if not _HAS_PSUTIL:
            return None
        try:
            p = psutil.Process()
            mem = p.memory_info()
            ws_mb = mem.rss / 1024 / 1024
            private_mb = mem.private / 1024 / 1024 if hasattr(mem, 'private') else mem.vms / 1024 / 1024
            num_threads = p.num_threads()
            try:
                num_handles = p.num_handles()
            except Exception:
                num_handles = -1
            cpu_pct = p.cpu_percent(interval=None)
            # 🩹 [β.2.8.7 / 2026-05-17] Sir 23:28 反馈: 严格排查 thread 来源
            # Python 角度 (threading.enumerate()) 看到的 thread = 我们能控制的
            # OS 角度 (num_threads) = Python 线程 + native (CUDA/gRPC/PyAudio/Qt 等)
            # 差值 = native, 不可控
            import threading
            py_threads = threading.enumerate()
            py_thread_count = len(py_threads)
            native_thread_count = max(0, num_threads - py_thread_count)
            sample = {
                'ts': time.time(),
                'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                'ws_mb': round(ws_mb, 1),
                'private_mb': round(private_mb, 1),
                'threads': num_threads,
                'py_threads': py_thread_count,
                'native_threads': native_thread_count,
                'handles': num_handles,
                'cpu_pct': round(cpu_pct, 1),
            }
            return sample
        except Exception as e:
            bg_log(f"⚠️ [HealthProbe] sample err: {e}")
            return None

    def dump_python_threads(self) -> str:
        """详细列 Python 线程 (按 name prefix 分组). 给 Sir 排查用."""
        import threading
        import collections
        threads = threading.enumerate()
        groups = collections.Counter()
        named = []
        for t in threads:
            name = t.name or 'unnamed'
            # group by prefix (split by - or _ or digit)
            import re
            prefix = re.split(r'[\-_0-9]', name, maxsplit=1)[0]
            groups[prefix or name] += 1
            named.append(name)
        lines = ["=== Python 线程分组 ==="]
        for grp, n in groups.most_common():
            lines.append(f"  {grp:30s}  {n}")
        lines.append(f"\n总 Python 线程: {len(threads)}")
        return '\n'.join(lines)

    def evaluate_alerts(self, s: Dict) -> List[str]:
        """根据当前 sample 出告警 list."""
        alerts: List[str] = []
        if s['threads'] > THRESHOLD_THREADS:
            alerts.append(
                f"threads={s['threads']} > {THRESHOLD_THREADS} (严重泄漏疑似)"
            )
        if s['private_mb'] / 1024 > THRESHOLD_PRIVATE_GB:
            alerts.append(
                f"private={s['private_mb']/1024:.1f}GB > {THRESHOLD_PRIVATE_GB}GB"
            )
        # 30min 内涨幅 (用历史最近 6 个 sample)
        if len(self._history) >= 6:
            base_ws = self._history[-6]['ws_mb']
            if base_ws > 100:
                growth_pct = (s['ws_mb'] - base_ws) / base_ws * 100
                if growth_pct > THRESHOLD_WS_GROWTH_PCT_30MIN:
                    alerts.append(
                        f"WS 30min 涨 {growth_pct:.0f}% "
                        f"({base_ws:.0f}MB→{s['ws_mb']:.0f}MB) 怀疑泄漏"
                    )
        return alerts

    def _append_history(self, s: Dict) -> None:
        self._history.append(s)
        if len(self._history) > 2880:
            self._history = self._history[-1440:]
        try:
            os.makedirs(os.path.dirname(self.history_path) or '.', exist_ok=True)
            with open(self.history_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(s, ensure_ascii=False) + '\n')
            # 限制 file 行数 (rotate)
            self._rotate_if_needed()
        except Exception:
            pass

    def _rotate_if_needed(self) -> None:
        try:
            if not os.path.exists(self.history_path):
                return
            with open(self.history_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) > HISTORY_MAX_LINES:
                tail = lines[-HISTORY_MAX_LINES // 2:]
                with open(self.history_path, 'w', encoding='utf-8') as f:
                    f.writelines(tail)
        except Exception:
            pass

    def run(self) -> None:
        time.sleep(60)
        if not _HAS_PSUTIL:
            bg_log("⚠️ [HealthProbe] psutil 不可用, 跳过自检")
            return
        bg_log(f"💓 [HealthProbe] started (interval={self.interval}s, "
               f"history={self.history_path})")
        # 第一次 sample 立即跑
        s0 = self.sample()
        if s0:
            self._baseline = s0
            self._append_history(s0)
            bg_log(f"💓 [HealthProbe/Baseline] ws={s0['ws_mb']}MB "
                   f"private={s0['private_mb']}MB threads={s0['threads']} "
                   f"(py={s0.get('py_threads', '?')} native={s0.get('native_threads', '?')}) "
                   f"handles={s0['handles']}")
            # β.2.8.7: baseline 时打一份 Python 线程分组让 Sir 看清来源
            try:
                bg_log(self.dump_python_threads())
            except Exception:
                pass
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            try:
                s = self.sample()
                if s is None:
                    continue
                self._append_history(s)
                alerts = self.evaluate_alerts(s)
                if alerts:
                    msg = (
                        f"⚠️ [HealthProbe/Alert] ws={s['ws_mb']}MB "
                        f"private={s['private_mb']}MB threads={s['threads']} "
                        f"handles={s['handles']}: " + " | ".join(alerts)
                    )
                    print(msg)
                    bg_log(msg)
                # 每 6 个 sample (30min) 打一次正常 health log
                if len(self._history) % 6 == 0:
                    bg_log(
                        f"💓 [HealthProbe] ws={s['ws_mb']}MB "
                        f"private={s['private_mb']}MB threads={s['threads']} "
                        f"handles={s['handles']} cpu={s['cpu_pct']}%"
                    )
            except Exception as e:
                bg_log(f"⚠️ [HealthProbe] tick err: {e}")


_DEFAULT_PROBE: Optional[HealthProbeDaemon] = None
_LOCK = threading.Lock()


def ensure_health_probe_started() -> None:
    global _DEFAULT_PROBE
    with _LOCK:
        if _DEFAULT_PROBE is None:
            _DEFAULT_PROBE = HealthProbeDaemon()
            _DEFAULT_PROBE.start()


def get_default_probe() -> Optional[HealthProbeDaemon]:
    return _DEFAULT_PROBE
