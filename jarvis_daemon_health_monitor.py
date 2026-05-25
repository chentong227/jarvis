# -*- coding: utf-8 -*-
"""[HM / Sir 2026-05-25 23:38 真意] DaemonHealthMonitor — Sir 不跑 CLI 也自动监控.

Sir 真意:
  "每天帮我看你说的是否健康, 是否太低什么的, 然后帮我优化吧,
   我真就是想少干点活, 别又给我多一项工作, claude"

灵魂工程 Layer 6 — 守护层. 每天自动检 4 项, 异常 publish SWM → Sir 主面板看红条.

检查 (准则 6 evidence-driven + 1 高效):
  1. InnerThought thoughts/24h: 健康区间 30-200, 越界 publish warn
  2. InnerThought 5 类分布: max-min ratio > 70% (一类垄断) → warn
  3. AutoArbiter calibration thresholds: any < 0.55 → warn (太松, 过激)
  4. AutoArbiter actionable fail rate: > 30% → warn (LLM 选 id 不准)

tick: 启动 + 后每 6h 一次 (4 次/day, 不刷屏)
启动 delay: 10min (等系统稳定 + 第一波 thoughts 产出)

publish:
  - SWM event 'daemon_health_warning' (high salience 0.75 → SOUL inject 进主脑)
  - 同 issue 6h cooldown 不重发
  - 持久化 memory_pool/daemon_health.json (Sir 可看历史)
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional


class DaemonHealthMonitor:
    """每日检 InnerThought + AutoArbiter 健康 → 异常自动 publish SWM."""

    PERSIST_PATH = 'memory_pool/daemon_health.json'

    TICK_INTERVAL_S = 6 * 3600   # 6h
    STARTUP_DELAY_S = 600        # 10min
    DEDUP_COOLDOWN_S = 6 * 3600  # 同 issue 6h 内不重发

    # InnerThought 健康区间
    THOUGHTS_24H_MIN = 30        # < 30 → daemon 卡了/LLM 一直 fail
    THOUGHTS_24H_MAX = 200       # > 200 → 频率失控
    CATEGORY_DOMINATION = 0.70   # 一类占比 > 70% → 不健康偏食

    # AutoArbiter 健康
    CALIBRATION_THRESHOLD_FLOOR = 0.55  # 阈值 < 0.55 → 太松 (Sir 撤销率会高)
    AUTO_ARBITER_FAIL_RATE_MAX = 0.30   # actionable fail > 30% → 选 id 不准

    def __init__(self, central_nerve=None):
        self.nerve = central_nerve
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_issue_ts: Dict[str, float] = {}  # issue_key → last publish ts
        self._history: List[dict] = []
        self._load_persist()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._daemon_loop, name='DaemonHealthMonitor', daemon=True
        )
        self._thread.start()
        self._bg_log(
            "🩺 [DaemonHealthMonitor] started — 每 6h 自动检 InnerThought + "
            "AutoArbiter 健康, 异常 publish SWM 进主面板"
        )

    def stop(self) -> None:
        self._stop.set()

    def _daemon_loop(self) -> None:
        self._stop.wait(timeout=self.STARTUP_DELAY_S)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._check_all()
            except Exception as e:
                self._bg_log(f"⚠️ [DaemonHealthMonitor] check fail: {e}")
            self._stop.wait(timeout=self.TICK_INTERVAL_S)

    def _check_all(self) -> None:
        """4 check, 任何异常 publish SWM."""
        issues: List[dict] = []

        # 1. InnerThought thoughts/24h
        thoughts_count = self._count_inner_thoughts_24h()
        if thoughts_count >= 0:  # -1 = file missing, skip
            if thoughts_count < self.THOUGHTS_24H_MIN:
                issues.append({
                    'key': 'inner_thoughts_too_few',
                    'severity': 'warn',
                    'msg': (
                        f"InnerThought daemon 24h 只产 {thoughts_count} 条思考 "
                        f"(健康 ≥ {self.THOUGHTS_24H_MIN}). 可能 LLM 频繁 fail "
                        f"或 cooldown 设错. 看 [InnerThought] log."
                    ),
                    'metric': {'count': thoughts_count,
                                'min': self.THOUGHTS_24H_MIN},
                })
            elif thoughts_count > self.THOUGHTS_24H_MAX:
                issues.append({
                    'key': 'inner_thoughts_too_many',
                    'severity': 'warn',
                    'msg': (
                        f"InnerThought daemon 24h 产 {thoughts_count} 条 "
                        f"(健康 ≤ {self.THOUGHTS_24H_MAX}). 频率失控, 看 "
                        f"tick_interval 是否正确按 sir_state adaptive."
                    ),
                    'metric': {'count': thoughts_count,
                                'max': self.THOUGHTS_24H_MAX},
                })

        # 2. InnerThought 5 类分布
        cat_dist = self._inner_thought_category_dist_24h()
        if cat_dist and sum(cat_dist.values()) >= 10:
            total = sum(cat_dist.values())
            for cat, n in cat_dist.items():
                ratio = n / total
                if ratio > self.CATEGORY_DOMINATION:
                    issues.append({
                        'key': f'inner_thought_cat_{cat}_dominate',
                        'severity': 'warn',
                        'msg': (
                            f"InnerThought 24h 类 {cat} 占 {ratio:.0%} "
                            f"({n}/{total}) — 不健康偏食. 5 类应均衡, "
                            f"看 daemon LLM prompt 是否引导主脑偏向某类."
                        ),
                        'metric': {'category': cat, 'ratio': round(ratio, 2),
                                    'count': n, 'total': total},
                    })

        # 3. AutoArbiter calibration 阈值
        cal = self._load_auto_arbiter_calibration()
        if cal:
            thresholds = cal.get('thresholds') or {}
            for kind, thr in thresholds.items():
                try:
                    if float(thr) < self.CALIBRATION_THRESHOLD_FLOOR:
                        issues.append({
                            'key': f'auto_arbiter_threshold_low_{kind}',
                            'severity': 'warn',
                            'msg': (
                                f"AutoArbiter [{kind}] 阈值 {thr:.2f} < "
                                f"{self.CALIBRATION_THRESHOLD_FLOOR} — 太松, "
                                f"daemon 过激. 看 dashboard /auto_arbiter "
                                f"Sir 撤销率是否过高."
                            ),
                            'metric': {'kind': kind, 'threshold': float(thr),
                                        'floor': self.CALIBRATION_THRESHOLD_FLOOR},
                        })
                except (TypeError, ValueError):
                    pass

        # 4. AutoArbiter actionable fail rate (24h)
        fail_rate, total_actions = self._inner_thought_actionable_fail_rate_24h()
        if total_actions >= 5 and fail_rate > self.AUTO_ARBITER_FAIL_RATE_MAX:
            issues.append({
                'key': 'inner_thought_actionable_fail_high',
                'severity': 'warn',
                'msg': (
                    f"InnerThought 24h actionable 失败率 {fail_rate:.0%} "
                    f"(>{self.AUTO_ARBITER_FAIL_RATE_MAX:.0%}). LLM 选 "
                    f"concern_id 不准. 看 daemon prompt 是否给全 active id."
                ),
                'metric': {'fail_rate': round(fail_rate, 2),
                            'total_actions': total_actions},
            })

        # publish 异常 (dedup cooldown)
        now = time.time()
        new_publish_count = 0
        for issue in issues:
            issue_key = issue['key']
            last_ts = self._last_issue_ts.get(issue_key, 0.0)
            if now - last_ts < self.DEDUP_COOLDOWN_S:
                continue
            self._last_issue_ts[issue_key] = now
            self._publish_issue(issue)
            new_publish_count += 1

        # 记到 history
        snapshot = {
            'ts': now,
            'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            'thoughts_24h': thoughts_count,
            'category_dist': cat_dist,
            'auto_arbiter_thresholds': (cal or {}).get('thresholds', {}),
            'actionable_fail_rate_24h': fail_rate,
            'actionable_total_24h': total_actions,
            'new_issues': len(issues),
            'new_published': new_publish_count,
        }
        with self._lock:
            self._history.append(snapshot)
            # 保留最近 30 days
            cutoff = now - 30 * 86400
            self._history = [h for h in self._history if h.get('ts', 0) > cutoff]
        self._persist()

        if issues:
            self._bg_log(
                f"🩺 [DaemonHealthMonitor] {len(issues)} issue 发现 "
                f"({new_publish_count} 新 publish, 其余 dedup cooldown)"
            )
        else:
            self._bg_log(
                f"🩺 [DaemonHealthMonitor] all healthy "
                f"(thoughts={thoughts_count}, cat={cat_dist})"
            )

    def _publish_issue(self, issue: dict) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='daemon_health_warning',
                description=issue['msg'],
                source='daemon_health_monitor',
                salience=0.75,
                metadata={
                    'issue_key': issue['key'],
                    'severity': issue.get('severity', 'warn'),
                    'metric': issue.get('metric', {}),
                },
                ttl=86400.0,
            )
        except Exception as e:
            self._bg_log(f"⚠️ [HealthMonitor] publish fail: {e}")

    # ----------------------------------------------------------
    # Data collection (从 InnerThought jsonl + AutoArbiter calibration)
    # ----------------------------------------------------------
    def _count_inner_thoughts_24h(self) -> int:
        path = os.path.join('memory_pool', 'inner_thoughts.jsonl')
        if not os.path.exists(path):
            return -1
        cutoff = time.time() - 86400
        count = 0
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get('ts', 0) >= cutoff:
                            count += 1
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception:
            return -1
        return count

    def _inner_thought_category_dist_24h(self) -> Dict[str, int]:
        path = os.path.join('memory_pool', 'inner_thoughts.jsonl')
        if not os.path.exists(path):
            return {}
        cutoff = time.time() - 86400
        dist: Dict[str, int] = {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get('ts', 0) >= cutoff:
                            cat = d.get('category', '?')
                            dist[cat] = dist.get(cat, 0) + 1
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception:
            return {}
        return dist

    def _inner_thought_actionable_fail_rate_24h(self) -> tuple:
        path = os.path.join('memory_pool', 'inner_thoughts.jsonl')
        if not os.path.exists(path):
            return 0.0, 0
        cutoff = time.time() - 86400
        total = 0
        failed = 0
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get('ts', 0) < cutoff:
                            continue
                        action = (d.get('actionable') or 'none').lower()
                        if action == 'none':
                            continue
                        total += 1
                        if not d.get('actionable_done'):
                            failed += 1
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception:
            return 0.0, 0
        rate = (failed / total) if total > 0 else 0.0
        return rate, total

    def _load_auto_arbiter_calibration(self) -> Optional[dict]:
        path = os.path.join('memory_pool', 'auto_arbiter_calibration.json')
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    # ----------------------------------------------------------
    # Persist
    # ----------------------------------------------------------
    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            tmp = self.PERSIST_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({
                    'history': self._history,
                    'last_issue_ts': self._last_issue_ts,
                }, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.PERSIST_PATH)
        except Exception as e:
            self._bg_log(f"⚠️ [HealthMonitor] persist fail: {e}")

    def _load_persist(self) -> None:
        if not os.path.exists(self.PERSIST_PATH):
            return
        try:
            with open(self.PERSIST_PATH, 'r', encoding='utf-8') as f:
                d = json.load(f) or {}
            self._history = d.get('history') or []
            self._last_issue_ts = d.get('last_issue_ts') or {}
        except Exception as e:
            self._bg_log(f"⚠️ [HealthMonitor] load fail: {e}")

    # ----------------------------------------------------------
    # Stats (dashboard / CLI)
    # ----------------------------------------------------------
    def get_latest_snapshot(self) -> dict:
        with self._lock:
            if not self._history:
                return {}
            return dict(self._history[-1])

    def get_active_issues(self) -> List[dict]:
        """返当前活跃 issue (last_issue_ts 还在 cooldown 内的)."""
        now = time.time()
        active = []
        for key, ts in self._last_issue_ts.items():
            if now - ts < self.DEDUP_COOLDOWN_S:
                active.append({
                    'key': key,
                    'last_ts': ts,
                    'last_iso': time.strftime(
                        '%Y-%m-%dT%H:%M:%S', time.localtime(ts)
                    ),
                    'age_s': int(now - ts),
                })
        return active

    # ----------------------------------------------------------
    def _bg_log(self, msg: str) -> None:
        try:
            from jarvis_utils import bg_log
            bg_log(msg)
        except Exception:
            pass


# ==========================================================================
# Module-level singleton
# ==========================================================================
_DEFAULT_MONITOR: Optional[DaemonHealthMonitor] = None


def get_default_monitor() -> Optional[DaemonHealthMonitor]:
    return _DEFAULT_MONITOR


def set_default_monitor(m: DaemonHealthMonitor) -> None:
    global _DEFAULT_MONITOR
    _DEFAULT_MONITOR = m
