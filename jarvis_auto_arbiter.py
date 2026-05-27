# -*- coding: utf-8 -*-
"""[AA / Sir 2026-05-25 22:58 自决] AutoArbiterDaemon — 让贾维斯自己拍板.

Sir 真意 (22:58):
  "让他自己拍板吧, 有任何不对地方我发日志给你, 你给我修复, 能做到吗?
   然后让他能自己迭代这种拍板的准确性, 通过每日的思考"

灵魂工程 Layer 2.5 — 自决引擎 (sit between Relational + Reflectors).

设计 (准则 6 evidence-driven + 准则 7 Sir 元否决 + 准则 8 优雅):

  ## 三档风险 (RISK)
    LOW    = {inside_joke, thread}      # 真自决 (activate/reject)
    MEDIUM = {concern, directive}        # propose_to_sir + UI badge "🤖 建议"
    HIGH   = (暂无, 全留 Sir)             # 不动

  ## 4 档决策 (DECISION)
    activate       — 真激活 (调 relational.activate_from_review)
    reject         — 真拒绝 (调 relational.reject_from_review)
    defer_to_sir   — 不执行, 写 'recommended' queue (UI badge)
    noop           — 不评 (confidence 太低 / dedup 已 fail / cap reached)

  ## per-category confidence 阈值 (calibration 可调, 准则 6 不写死)
    DEFAULT_THRESHOLDS = {
      'inside_joke': 0.75,  # 低风险, 中阈值
      'thread':      0.75,
      'concern':     0.85,  # 中风险, 高阈值
      'directive':   0.90,  # 中-高风险
    }

  ## Daily Self-Iteration (Sir 真问 "通过每日的思考")
    凌晨 03:xx 一次 reflection:
      - 看 24h decisions
      - per kind: count sir_reverted / total = revert_rate
      - rate > 30% → 阈值 +0.05 (cap 0.95) — 太激进, 收敛
      - rate < 10% AND total ≥ 5 → 阈值 -0.02 (floor 0.5) — 太保守, 放松
      - 持久化 calibration + publish SWM event

  ## Sir 反馈 (准则 7 元否决)
    Sir 在 dashboard 点撤销:
      - reverse 真动作 (activate→reject_from_review, reject→re-propose)
      - 标 sir_reverted=True + 记 reason
      - 计入 daily reflection 的 revert_rate
      - publish SWM 'sir_reverted_auto_arbitrate' event

  ## 防爆 cap (准则 1 高效)
    MAX_AUTO_DECISIONS_PER_DAY = 50 (per-kind 各 25)

  ## Caller 路由 (P2 集成)
    LLM caller='auto_arbiter' → 默认 LOW priority + 30/min 限速

成本估算:
  ~10 reviewable items/day × $0.000125/call (Flash-Lite) = $0.04/day = $1.2/月

参考:
  jarvis_relational.py  (activate_from_review / reject_from_review API)
  jarvis_inner_thought_daemon.py  (daemon pattern 参考)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Tuple


# ==========================================================================
# Data structure
# ==========================================================================

@dataclass
class ArbiterDecision:
    """单条自决记录. 持久化 + Sir 一键撤销基础."""
    id: str
    ts: float
    ts_iso: str
    kind: str               # 'inside_joke' | 'thread' | 'concern' | 'directive'
    item_id: str            # 目标条目 id
    item_preview: str       # 短预览 (Sir dashboard 一眼)
    risk_level: str         # 'low' | 'medium' | 'high'
    decision: str           # 'activate' | 'reject' | 'defer_to_sir' | 'noop'
    confidence: float       # 0.0-1.0
    reason: str             # LLM 给的理由
    threshold_at_decision: float  # 当时用的阈值 (calibration 时回看)
    executed_ok: bool = False
    executed_at: float = 0.0
    execution_msg: str = ''
    sir_reverted: bool = False
    sir_reverted_at: float = 0.0
    sir_revert_reason: str = ''


# ==========================================================================
# Daemon
# ==========================================================================

class AutoArbiterDaemon:
    """Auto arbitration daemon. Jarvis 自己审 review queues + 真拍板.

    生命周期:
      __init__(key_router, relational_state, concerns_ledger, central_nerve)
      start() → 启 2 thread (tick + daily_reflection)
      stop()  → 停
      sir_revert(decision_id, reason) → Sir 一键撤销
    """

    PERSIST_PATH = 'memory_pool/auto_arbiter_log.jsonl'
    CALIBRATION_PATH = 'memory_pool/auto_arbiter_calibration.json'
    # 🆕 [Sir 2026-05-27 12:13 真痛 anchor] abstract protocol auto-reject vocab
    # Sir 真痛: 思考脑 propose abstract 'prioritize concise' → AutoArbiter LLM
    # eval 也几乎全 DEFER_TO_SIR (review queue 积压 50+). 治本: 不调 LLM 先看
    # vocab keyword pre-check, 命中 → bypass LLM 直接 REJECT (省 tokens + 不积压).
    # 准则 6 持久化 + Sir CLI 可改 (memory_pool/auto_arbiter_abstract_reject_vocab.json)
    ABSTRACT_REJECT_VOCAB_PATH = 'memory_pool/auto_arbiter_abstract_reject_vocab.json'

    DEFAULT_THRESHOLDS = {
        'inside_joke': 0.75,
        'thread':      0.75,
        'protocol':    0.80,  # 🆕 [Sir 2026-05-26 SOUL Phase A] 中间档 — 严过 joke (行为 STRICT)
        'concern':     0.85,
        'directive':   0.90,
    }
    THRESHOLD_FLOOR = 0.50
    THRESHOLD_CEILING = 0.95
    REVERT_RATE_HIGH = 0.30       # >30% → 阈值升 0.05
    REVERT_RATE_LOW = 0.10        # <10% & total≥5 → 阈值降 0.02
    THRESHOLD_RAISE_STEP = 0.05
    THRESHOLD_LOWER_STEP = 0.02

    # 风险分类
    # 🆕 [Sir 2026-05-26 SOUL Phase A] protocol 列 LOW 真自决 (Sir 元否决可 revert)
    RISK_LOW = frozenset({'inside_joke', 'thread', 'protocol'})
    RISK_MEDIUM = frozenset({'concern', 'directive'})
    KNOWN_KINDS = RISK_LOW | RISK_MEDIUM

    # tick (default fallback, calibration runtime 段 overrides)
    # 🆕 [Sir 2026-05-26 21:02 真痛 dashboard pending bloat / 方案 E.1+E.3 治本]
    # 30min → 5min: dashboard 一堆 pending → AutoArbiter 现在每 5min tick.
    # 同时 calibration JSON 加 'runtime' 段, Sir CLI 可调.
    TICK_INTERVAL_S = 300            # 5min (was 1800/30min)
    STARTUP_DELAY_S = 60             # 60s 让系统稳定
    DAILY_REFLECTION_HOUR = 3        # 03:xx
    REFLECTION_CHECK_INTERVAL_S = 600  # 10min 检查 hour

    # 🆕 [方案 E.1+E.3+F+G 治本] runtime defaults (calibration JSON runtime 段 overrides)
    DEFAULT_RUNTIME = {
        'tick_interval_s': 300,             # E.1: 5min tick
        'reevaluate_after_h': 6.0,          # E.3: defer_to_sir 6h 后可重评
        'pre_activate_dedup_jaccard': 0.6,  # F: pre-activate 重复硬拦阈值
        'startup_delay_s': 60,
        # 🆕 G: monitor daemon (Sir 真痛 "时刻帮我检查 AutoArbiter 拍板内容")
        'monitor_interval_s': 900,          # 15min 监查一次
        'monitor_bloat_warn_n': 25,         # active items > 25 → warn
        'monitor_bloat_alert_n': 40,        # active items > 40 → alert
        'monitor_revert_rate_warn': 0.30,   # 24h revert rate > 30% → warn
        'monitor_dedup_pair_jaccard': 0.5,  # 任一对 active >= 0.5 → warn
    }

    # cap
    MAX_AUTO_DECISIONS_PER_DAY = 50  # 全局 cap
    MAX_PER_KIND_PER_DAY = 25        # per-kind cap

    def __init__(self, key_router, relational_state=None,
                  concerns_ledger=None, central_nerve=None):
        self.key_router = key_router
        self.relational = relational_state
        self.concerns = concerns_ledger
        self.nerve = central_nerve

        self._decisions: List[ArbiterDecision] = []
        self._calibration: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reflection_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None  # 🆕 [G]
        self._last_reflection_date = ''
        self._last_monitor_warning_ts: dict = {}  # 🆕 [G] dedup warning (kind → ts)

        # stats
        self._tick_count = 0
        self._llm_call_count = 0
        self._llm_fail_count = 0

        # 启动加载
        self._load_persist()
        self._load_calibration()

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._daemon_loop, name='AutoArbiterDaemon', daemon=True
        )
        self._thread.start()
        self._reflection_thread = threading.Thread(
            target=self._reflection_loop, name='AutoArbiterReflection',
            daemon=True
        )
        self._reflection_thread.start()
        # 🆕 [G] monitor daemon — Sir 真痛 "时刻帮我检查 AutoArbiter 拍板内容"
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name='AutoArbiterMonitor',
            daemon=True
        )
        self._monitor_thread.start()
        self._bg_log(
            f"🤖 [AutoArbiter] daemon started "
            f"(loaded {len(self._decisions)} decisions from 7d, "
            f"thresholds={self._effective_thresholds()})"
        )

    def stop(self) -> None:
        self._stop.set()

    def _daemon_loop(self) -> None:
        # 🆕 [E.1] startup + tick interval 从 calibration runtime 段读 (可热调)
        runtime = self._effective_runtime()
        startup_wait = float(runtime.get('startup_delay_s', self.STARTUP_DELAY_S))
        self._stop.wait(timeout=startup_wait)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                self._bg_log(f"⚠️ [AutoArbiter] tick exception: {e}")
            # 每 tick 重读 (Sir CLI 改 calibration runtime 段后立刻生效)
            runtime = self._effective_runtime()
            tick_wait = float(runtime.get('tick_interval_s', self.TICK_INTERVAL_S))
            self._stop.wait(timeout=tick_wait)

    def _reflection_loop(self) -> None:
        # 等 startup 后再启
        self._stop.wait(timeout=self.STARTUP_DELAY_S + 30)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._maybe_do_daily_reflection()
            except Exception as e:
                self._bg_log(
                    f"⚠️ [AutoArbiter] reflection exception: {e}"
                )
            self._stop.wait(timeout=self.REFLECTION_CHECK_INTERVAL_S)

    # ==========================================================================
    # 🆕 [Sir 2026-05-26 21:04 真痛 / 方案 G 治本] Monitor daemon
    # ==========================================================================
    # Sir 真痛: "你也要时刻帮我检查他拍板的所有内容".
    # AutoArbiter 自决了 → 没人看 → 出错 Sir 才发现. monitor daemon 周期扫:
    #   1. bloat: active items 总数 > vocab.monitor_bloat_warn_n (默认 25)
    #   2. revert burst: 24h 内 revert_rate > vocab.monitor_revert_rate_warn (30%)
    #   3. dedup miss: 任一对 active jaccard >= vocab.monitor_dedup_pair_jaccard
    # 发现 anomaly → publish SWM 'auto_arbiter_anomaly' → InnerThought 看到
    # evidence 反思 → 必要时 propose_protocol / surface_to_sir Sir.
    # 准则 6: vocab 持久化, Sir CLI 可调; 不硬编码阈值.
    # ==========================================================================
    def _monitor_loop(self) -> None:
        # 等 daemon 起后 + 30s 让 reflection_loop 先启
        self._stop.wait(timeout=self.STARTUP_DELAY_S + 60)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            try:
                self._do_monitor_scan()
            except Exception as e:
                self._bg_log(
                    f"⚠️ [AutoArbiter] monitor exception: {e}"
                )
            runtime = self._effective_runtime()
            wait = float(runtime.get('monitor_interval_s', 900))
            self._stop.wait(timeout=wait)

    def _do_monitor_scan(self) -> None:
        """周期扫 — 检 bloat / revert burst / dedup miss → publish SWM warning."""
        if self.relational is None:
            return
        runtime = self._effective_runtime()
        warnings: List[dict] = []

        # 1. bloat check (3 kind: joke / thread / protocol)
        bloat_n = int(runtime.get('monitor_bloat_warn_n', 25))
        alert_n = int(runtime.get('monitor_bloat_alert_n', 40))
        for kind_name, store_attr in [
            ('inside_joke', 'inside_jokes'),
            ('thread', 'shared_history_threads'),
            ('protocol', 'unspoken_protocols'),
        ]:
            try:
                store = getattr(self.relational, store_attr, {}) or {}
                active_n = sum(
                    1 for it in store.values()
                    if getattr(it, 'state', '') == 'active'
                )
            except Exception:
                continue
            if active_n >= alert_n:
                warnings.append({
                    'severity': 'alert',
                    'type': 'bloat',
                    'kind': kind_name,
                    'msg': (
                        f'{kind_name} active count = {active_n} '
                        f'(>= alert {alert_n}) — likely over-bloat, '
                        f'should archive low-value ones'
                    ),
                    'metrics': {'active_n': active_n, 'threshold': alert_n},
                })
            elif active_n >= bloat_n:
                warnings.append({
                    'severity': 'warn',
                    'type': 'bloat',
                    'kind': kind_name,
                    'msg': (
                        f'{kind_name} active count = {active_n} '
                        f'(>= warn {bloat_n}) — getting crowded'
                    ),
                    'metrics': {'active_n': active_n, 'threshold': bloat_n},
                })

        # 2. revert burst (24h)
        revert_warn = float(runtime.get('monitor_revert_rate_warn', 0.30))
        cutoff = time.time() - 24 * 3600
        with self._lock:
            recent = [d for d in self._decisions if d.ts > cutoff]
        for kind_name in ('inside_joke', 'thread', 'protocol'):
            kind_recent = [d for d in recent if d.kind == kind_name
                              and d.decision in ('activate', 'reject')]
            if len(kind_recent) < 5:  # 样本少不算
                continue
            reverted = sum(1 for d in kind_recent if d.sir_reverted_at > 0)
            rate = reverted / len(kind_recent)
            if rate >= revert_warn:
                warnings.append({
                    'severity': 'warn',
                    'type': 'revert_burst',
                    'kind': kind_name,
                    'msg': (
                        f'{kind_name} 24h revert rate = {rate:.2%} '
                        f'(>= warn {revert_warn:.0%}, {reverted}/{len(kind_recent)}) '
                        f'— Sir reverting often, calibration may be off'
                    ),
                    'metrics': {
                        'rate': rate,
                        'reverted': reverted,
                        'total': len(kind_recent),
                    },
                })

        # 3. dedup miss — any pair in active >= jaccard threshold
        dedup_thr = float(runtime.get('monitor_dedup_pair_jaccard', 0.5))
        try:
            import re as _re
        except Exception:
            _re = None
        if _re is not None:
            for kind_name, store_attr, text_attr in [
                ('inside_joke', 'inside_jokes', 'phrase'),
                ('thread', 'shared_history_threads', 'title'),
                ('protocol', 'unspoken_protocols', 'rule'),
            ]:
                try:
                    store = getattr(self.relational, store_attr, {}) or {}
                    active_items = [
                        (it.id, (getattr(it, text_attr, '') or '').lower())
                        for it in store.values()
                        if getattr(it, 'state', '') == 'active'
                    ]
                except Exception:
                    continue
                # 用 dedup_thr 找 top 1 重复对 (不全列, 避免 SWM 爆)
                worst_pair = None
                worst_jac = 0.0
                for i, (id_a, text_a) in enumerate(active_items):
                    if len(text_a) < 3:
                        continue
                    tokens_a = set(_re.findall(r'\w+', text_a))
                    if not tokens_a:
                        continue
                    for id_b, text_b in active_items[i + 1:]:
                        if len(text_b) < 3:
                            continue
                        tokens_b = set(_re.findall(r'\w+', text_b))
                        if not tokens_b:
                            continue
                        inter = len(tokens_a & tokens_b)
                        union = len(tokens_a | tokens_b)
                        jac = (inter / union) if union > 0 else 0.0
                        if jac > worst_jac:
                            worst_jac = jac
                            worst_pair = (id_a, text_a, id_b, text_b)
                if worst_pair and worst_jac >= dedup_thr:
                    warnings.append({
                        'severity': 'warn',
                        'type': 'dedup_miss',
                        'kind': kind_name,
                        'msg': (
                            f'{kind_name} active pair jaccard = {worst_jac:.2f} '
                            f'(>= warn {dedup_thr}) — likely dup slipped through '
                            f'pre-activate. {worst_pair[0][:15]} ↔ {worst_pair[2][:15]}'
                        ),
                        'metrics': {
                            'jaccard': worst_jac,
                            'a_id': worst_pair[0],
                            'b_id': worst_pair[2],
                            'a_text': worst_pair[1][:80],
                            'b_text': worst_pair[3][:80],
                        },
                    })

        # publish + log (dedup: 同 kind+type 1h 内不重复 publish)
        for w in warnings:
            ddup_key = f"{w['type']}:{w['kind']}"
            last_ts = float(self._last_monitor_warning_ts.get(ddup_key, 0))
            if time.time() - last_ts < 3600:
                continue
            self._last_monitor_warning_ts[ddup_key] = time.time()
            self._bg_log(
                f"🚨 [AutoArbiter/Monitor] {w['severity'].upper()} "
                f"{w['type']}/{w['kind']}: {w['msg']}"
            )
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='auto_arbiter_anomaly',
                        description=w['msg'][:200],
                        source='AutoArbiterMonitor',
                        salience=0.8 if w['severity'] == 'alert' else 0.7,
                        metadata={
                            'severity': w['severity'],
                            'anomaly_type': w['type'],
                            'kind': w['kind'],
                            'metrics': w['metrics'],
                        },
                        ttl=86400.0,
                    )
            except Exception:
                pass

    # ----------------------------------------------------------
    # Calibration (per-category confidence threshold)
    # ----------------------------------------------------------
    def _effective_thresholds(self) -> dict:
        """合并默认 + calibration (calibration 不存在则全用默认)."""
        out = dict(self.DEFAULT_THRESHOLDS)
        cal_th = (self._calibration or {}).get('thresholds') or {}
        for k, v in cal_th.items():
            if k in out:
                try:
                    out[k] = max(self.THRESHOLD_FLOOR,
                                  min(self.THRESHOLD_CEILING, float(v)))
                except (TypeError, ValueError):
                    pass
        return out

    def _effective_runtime(self) -> dict:
        """🆕 [E.1+E.3+F] 合并默认 + calibration['runtime'] (Sir CLI 可热调).

        runtime keys:
          tick_interval_s — daemon loop tick 间隔 (E.1, 默认 300s/5min)
          reevaluate_after_h — defer_to_sir 后 N h 可重评 (E.3, 默认 6.0)
          pre_activate_dedup_jaccard — pre-activate 重复 jaccard 阈值 (F, 默认 0.6)
          startup_delay_s — daemon 起 N s 后才开 (默认 60)
        """
        out = dict(self.DEFAULT_RUNTIME)
        cal_rt = (self._calibration or {}).get('runtime') or {}
        for k, v in cal_rt.items():
            if k in out:
                try:
                    # 数字类型 type-check (防 Sir 误填 string)
                    if isinstance(out[k], (int, float)):
                        out[k] = type(out[k])(v)
                except (TypeError, ValueError):
                    pass
        return out

    def _load_calibration(self) -> None:
        if not os.path.exists(self.CALIBRATION_PATH):
            self._calibration = {
                'thresholds': dict(self.DEFAULT_THRESHOLDS),
                'revert_history_24h': {},
                'last_calibrated_at': 0,
                'last_calibrated_iso': '',
            }
            return
        try:
            with open(self.CALIBRATION_PATH, 'r', encoding='utf-8') as f:
                self._calibration = json.load(f) or {}
            if 'thresholds' not in self._calibration:
                self._calibration['thresholds'] = dict(self.DEFAULT_THRESHOLDS)
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] load calibration fail: {e}")
            self._calibration = {
                'thresholds': dict(self.DEFAULT_THRESHOLDS),
                'revert_history_24h': {},
            }

    def _save_calibration(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.CALIBRATION_PATH), exist_ok=True)
            tmp = self.CALIBRATION_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._calibration, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.CALIBRATION_PATH)
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] save calibration fail: {e}")

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-27 12:13 真痛 anchor] Abstract protocol auto-reject
    # ----------------------------------------------------------
    # Sir 真痛 (jarvis_20260527_073636.log): 思考脑 propose abstract 'prioritize
    # concise' → AutoArbiter LLM eval 也 'subjective and aspirational' DEFER →
    # review queue 50+ 积压, Sir 没空 dashboard 拍板. propose 永不 activate,
    # 浪费 tokens, 主脑下轮也看不到效果.
    # 治本 (准则 6 + 准则 8): vocab keyword pre-check bypass LLM 直接 REJECT
    #   - vocab 持久化 memory_pool/auto_arbiter_abstract_reject_vocab.json
    #   - Sir CLI 可改 (加新词不需改 .py)
    #   - lazy load + mtime 30s cache (Sir 改后下次 tick 即生效)
    # 双层守: 思考脑源头 prompt 也禁这些词 (jarvis_inner_thought_daemon.py:1466)
    # ----------------------------------------------------------
    _ABSTRACT_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
    _ABSTRACT_VOCAB_CHECK_INTERVAL_S = 30.0

    def _load_abstract_reject_vocab(self) -> dict:
        """Lazy load abstract vocab + mtime 30s throttle. 失败 fallback empty.

        Returns:
            dict 含 enabled / abstract_keywords / min_keyword_hits_to_reject /
            min_words_in_rule / log_rejected.
            空 dict 表示 vocab 不存在或 disabled.
        """
        default_disabled = {'enabled': False, 'abstract_keywords': []}
        path = self.ABSTRACT_REJECT_VOCAB_PATH
        cache = AutoArbiterDaemon._ABSTRACT_VOCAB_CACHE
        now = time.time()
        # 30s throttle, 避免每 tick read JSON
        if (cache['data'] is not None and
                now - cache['checked_at'] < self._ABSTRACT_VOCAB_CHECK_INTERVAL_S):
            return cache['data']
        cache['checked_at'] = now
        if not os.path.exists(path):
            cache['data'] = default_disabled
            return default_disabled
        try:
            mtime = os.path.getmtime(path)
            if cache['data'] is not None and mtime == cache['mtime']:
                return cache['data']
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            cache['data'] = data
            cache['mtime'] = mtime
            return data
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] load abstract_reject_vocab fail: {e}")
            cache['data'] = default_disabled
            return default_disabled

    def _is_abstract_protocol(self, rule_text: str) -> Tuple[bool, str]:
        """检 protocol rule 是否过抽象, 命中 vocab keyword 即直接 REJECT.

        Args:
            rule_text: protocol 候选规则文本

        Returns:
            (is_abstract, reason): True 表示 abstract 应 reject;
                reason 含命中关键词 + 触发条件 (供 log + persist).
        """
        if not rule_text or not rule_text.strip():
            return False, 'empty_rule'
        vocab = self._load_abstract_reject_vocab()
        if not vocab.get('enabled', False):
            return False, 'vocab_disabled'
        keywords = vocab.get('abstract_keywords', []) or []
        if not keywords:
            return False, 'no_keywords'
        min_hits = int(vocab.get('min_keyword_hits_to_reject', 2))
        min_words = int(vocab.get('min_words_in_rule', 4))

        rule_lower = rule_text.lower().strip()
        # 短 rule pre-reject (太短没具体内容)
        word_count = len(rule_lower.split())
        if word_count < min_words:
            return True, f'too_short:{word_count}w<{min_words}'
        # 数 abstract 关键词命中
        hits = [kw for kw in keywords if kw.lower() in rule_lower]
        if len(hits) >= min_hits:
            return True, f'abstract_kw_hit:{",".join(hits[:5])}'
        return False, f'concrete:{len(hits)}hits<{min_hits}'

    def _handle_pre_reject_abstract(self, kind: str, item_id: str,
                                          preview: str, risk: str,
                                          rule_text: str,
                                          abs_reason: str) -> None:
        """abstract protocol 直接走 REJECT path, bypass LLM eval.

        构造 ArbiterDecision (decision='reject', confidence=1.0 表示 deterministic
        pre-check), 真调 _execute(reject) 让 relational.reject_from_review 把
        item 从 review queue 移除. 持久化 + log + publish SWM.
        """
        now = time.time()
        d = ArbiterDecision(
            id=f"aa_{time.strftime('%Y%m%d_%H%M%S')}_"
                f"{int(now * 1000) % 10000:04x}",
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            kind=kind,
            item_id=item_id,
            item_preview=preview[:100],
            risk_level=risk,
            decision='reject',
            confidence=1.0,  # deterministic pre-check, 非 LLM 置信度
            reason=f'pre_reject_abstract: {abs_reason}',
            threshold_at_decision=0.0,  # 不走阈值路径
        )
        # 真执行 reject (从 review queue 移)
        try:
            ok, msg = self._execute(kind, item_id, 'reject')
            d.executed_ok = ok
            d.executed_at = time.time()
            d.execution_msg = msg[:200]
        except Exception as e:
            d.executed_ok = False
            d.execution_msg = f'execute_exception:{e}'[:200]

        with self._lock:
            self._decisions.append(d)
        self._persist_decision(d)
        self._publish_swm(d)

        vocab = self._load_abstract_reject_vocab()
        if vocab.get('log_rejected', True):
            self._bg_log(
                f"🤖 [AutoArbiter] [{kind}/{item_id[:20]}] "
                f"PRE_REJECT abstract (bypass LLM) | reason: {abs_reason} "
                f"| rule_preview: {rule_text[:60]}"
            )

    # ----------------------------------------------------------
    # Tick (核心: 拉 review queues, per item evaluate + decide)
    # ----------------------------------------------------------
    def _tick(self) -> None:
        self._tick_count += 1
        if not self.relational:
            return
        # cap 检查
        today_count = self._count_today_decisions()
        if today_count >= self.MAX_AUTO_DECISIONS_PER_DAY:
            self._bg_log(
                f"🤖 [AutoArbiter] tick skipped: today cap reached "
                f"({today_count}/{self.MAX_AUTO_DECISIONS_PER_DAY})"
            )
            return

        # 拉 review queue (inside_joke + thread)
        items_to_eval: List[dict] = []
        try:
            jokes_review = self.relational.list_inside_jokes_review() or []
            for j in jokes_review:
                items_to_eval.append({
                    'kind': 'inside_joke', 'entity': j,
                    'preview': (j.phrase or '')[:80],
                })
        except Exception:
            pass
        try:
            threads_review = self.relational.list_threads_review() or []
            for t in threads_review:
                items_to_eval.append({
                    'kind': 'thread', 'entity': t,
                    'preview': (t.title or '')[:80],
                })
        except Exception:
            pass
        # 🆕 [Sir 2026-05-26 SOUL Phase A] protocol review queue
        try:
            protocols_review = (
                self.relational.list_protocols_review() or []
                if hasattr(self.relational, 'list_protocols_review') else []
            )
            for p in protocols_review:
                items_to_eval.append({
                    'kind': 'protocol', 'entity': p,
                    'preview': (p.rule or '')[:80],
                })
        except Exception:
            pass

        if not items_to_eval:
            return

        self._bg_log(
            f"🤖 [AutoArbiter] tick: {len(items_to_eval)} review items "
            f"(jokes + threads + protocols), evaluating..."
        )

        for item in items_to_eval:
            # 看决策过吗 (防重复)
            if self._already_decided_recently(item['kind'],
                                                self._entity_id(item['entity'])):
                continue

            # per-kind cap
            if self._count_today_decisions_by_kind(item['kind']) \
                    >= self.MAX_PER_KIND_PER_DAY:
                self._bg_log(
                    f"🤖 [AutoArbiter] {item['kind']} per-kind cap reached, skip"
                )
                continue
            # 评估 + 决策 + 执行 + 持久
            try:
                self._evaluate_and_decide(item)
            except Exception as e:
                self._bg_log(
                    f"⚠️ [AutoArbiter] eval fail for "
                    f"{item['kind']}/{self._entity_id(item['entity'])}: {e}"
                )

    def _entity_id(self, entity) -> str:
        return getattr(entity, 'id', '') or ''

    def _already_decided_recently(self, kind: str, item_id: str,
                                     within_h: float = 24) -> bool:
        """🆕 [E.3 治本] 老 BUG: defer_to_sir 一次 → 24h 不再 retry → dashboard 堆.
        新法:
          - 'activate' / 'reject' 决策: 24h 内不重做 (终态, 不该再判)
          - 'defer_to_sir' / 'noop': 看 calibration.runtime.reevaluate_after_h
            (默认 6h), 超 6h 给 LLM 再机会 (Sir 没手动操作 → 自动重评)
        """
        cutoff_terminal = time.time() - within_h * 3600
        reevaluate_after_h = float(
            self._effective_runtime().get('reevaluate_after_h', 6.0)
        )
        cutoff_defer = time.time() - reevaluate_after_h * 3600
        with self._lock:
            for d in self._decisions:
                if d.kind != kind or d.item_id != item_id:
                    continue
                # terminal 决策 24h 内 skip (don't unmake decision)
                if d.decision in ('activate', 'reject'):
                    if d.ts > cutoff_terminal:
                        return True
                # non-terminal (defer/noop): 看 reevaluate_after_h
                elif d.decision in ('defer_to_sir', 'noop'):
                    if d.ts > cutoff_defer:
                        return True
        return False

    def _count_today_decisions(self) -> int:
        today = time.strftime('%Y-%m-%d')
        with self._lock:
            return sum(1 for d in self._decisions
                        if time.strftime('%Y-%m-%d',
                                           time.localtime(d.ts)) == today
                        and d.decision in ('activate', 'reject'))

    def _count_today_decisions_by_kind(self, kind: str) -> int:
        today = time.strftime('%Y-%m-%d')
        with self._lock:
            return sum(1 for d in self._decisions
                        if d.kind == kind
                        and time.strftime('%Y-%m-%d',
                                           time.localtime(d.ts)) == today
                        and d.decision in ('activate', 'reject'))

    # ----------------------------------------------------------
    # Evaluate + decide
    # ----------------------------------------------------------
    def _evaluate_and_decide(self, item: dict) -> None:
        kind = item['kind']
        entity = item['entity']
        item_id = self._entity_id(entity)
        preview = item['preview']

        risk = ('low' if kind in self.RISK_LOW
                  else 'medium' if kind in self.RISK_MEDIUM
                  else 'high')

        # 🆕 [Sir 2026-05-27 12:13 真痛 anchor] abstract protocol pre-check
        # ============================================================
        # 调 LLM 前先看 vocab keyword, 命中 abstract 直接 REJECT (省 tokens +
        # 不积 review queue). 防御 Sir 真痛: 50+ DEFER 项 'subjective and
        # aspirational' 反复积压.
        # ============================================================
        if kind == 'protocol':
            rule_text = getattr(entity, 'rule', '') or ''
            is_abs, abs_reason = self._is_abstract_protocol(rule_text)
            if is_abs:
                # 直接构造 REJECT decision, bypass LLM, bypass _decide
                self._handle_pre_reject_abstract(
                    kind=kind, item_id=item_id, preview=preview,
                    risk=risk, rule_text=rule_text, abs_reason=abs_reason,
                )
                return  # 不进 LLM eval / 不进 _decide

        # 收集 evidence
        evidence = self._collect_evidence(kind, entity)

        # LLM eval
        action, conf, reason = self._llm_evaluate(kind, entity, evidence)

        # 决策映射
        thresholds = self._effective_thresholds()
        thr = thresholds.get(kind, 0.80)
        decision = self._decide(action, conf, thr, risk)

        # 🆕 [Sir 2026-05-26 21:04 真痛 "拍板必须去重" / 方案 F 治本]
        # =================================================================
        # pre-activate hard-check: 即将 ACTIVATE 前再 jaccard 一遍 active list,
        # 命中 vocab.pre_activate_dedup_jaccard 阈值 (默认 0.6) → 改 decision
        # 为 'reject' + reason 加 'pre_activate_dedup'. propose_protocol 在 入
        # review queue 时已 dedup (0.7) 但当时 active 可能为空, 后续多次 propose
        # 后真活化时再确认一次, 防 race condition + Sir 之后真用时已重复.
        # =================================================================
        if decision == 'activate':
            dedup_ok, dup_reason = self._pre_activate_dedup_check(kind, entity)
            if not dedup_ok:
                decision = 'reject'
                reason = (
                    f'pre_activate_dedup_check fail: {dup_reason} '
                    f'| llm_orig_conf={conf:.2f} (overridden by hard dedup)'
                )

        # build ArbiterDecision
        now = time.time()
        d = ArbiterDecision(
            id=f"aa_{time.strftime('%Y%m%d_%H%M%S')}_"
                f"{int(now * 1000) % 10000:04x}",
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            kind=kind,
            item_id=item_id,
            item_preview=preview[:100],
            risk_level=risk,
            decision=decision,
            confidence=conf,
            reason=reason[:300],
            threshold_at_decision=thr,
        )

        # 执行
        if decision in ('activate', 'reject'):
            ok, msg = self._execute(kind, item_id, decision)
            d.executed_ok = ok
            d.executed_at = time.time()
            d.execution_msg = msg[:200]
        # defer_to_sir / noop: 不执行

        # persist + log
        with self._lock:
            self._decisions.append(d)
        self._persist_decision(d)
        self._publish_swm(d)

        self._bg_log(
            f"🤖 [AutoArbiter] [{kind}/{item_id[:20]}] "
            f"sal={conf:.2f}/thr={thr:.2f} → {decision.upper()} "
            f"({'OK' if d.executed_ok else 'NOEXEC' if decision in ('defer_to_sir', 'noop') else 'FAIL'}) "
            f"| reason: {reason[:80]}"
        )

    def _decide(self, action: str, conf: float, thr: float,
                  risk: str) -> str:
        """映射 LLM action + confidence → 最终 decision (4 档).

        LOW risk: confidence >= thr → 真 activate/reject; else defer_to_sir
        MEDIUM risk: 不真执行, 全 defer_to_sir (Sir 在 dashboard 看 '🤖 建议')
        """
        if action not in ('activate', 'reject'):
            return 'noop'
        if conf < thr:
            return 'defer_to_sir'
        if risk == 'low':
            return action
        # medium: 只建议不真做
        return 'defer_to_sir'

    def _pre_activate_dedup_check(self, kind: str,
                                       entity) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 21:04 真痛 "拍板必须去重" / 方案 F 治本]

        即将 ACTIVATE 前最后一道防线: 与现有 active list 算 jaccard, 命中
        vocab.pre_activate_dedup_jaccard (默认 0.6) → 阻止激活.

        Args:
          kind: 'inside_joke' / 'thread' / 'protocol'
          entity: 候选 entity (有 phrase/title/rule 字段)

        Returns:
          (ok, reason): ok=True 通过 (无重复), False 阻止;
                          reason 含命中的 active id + jaccard 值
        """
        try:
            import re as _re
        except Exception:
            return True, 'regex_unavailable'  # 故障开放: 不影响活化
        if self.relational is None:
            return True, 'no_relational_store'

        # 提取候选 text
        if kind == 'inside_joke':
            cand_text = getattr(entity, 'phrase', '') or ''
        elif kind == 'thread':
            cand_text = getattr(entity, 'title', '') or ''
        elif kind == 'protocol':
            cand_text = getattr(entity, 'rule', '') or ''
        else:
            return True, f'no_dedup_for_kind:{kind}'
        cand_text = cand_text.lower().strip()
        if len(cand_text) < 3:
            return True, 'cand_too_short'

        cand_tokens = set(_re.findall(r'\w+', cand_text))
        if not cand_tokens:
            return True, 'cand_no_tokens'

        # 收集 active list
        try:
            if kind == 'inside_joke':
                active_items = [
                    (j.id, (j.phrase or '').lower())
                    for j in self.relational.inside_jokes.values()
                    if getattr(j, 'state', '') == 'active'
                ]
            elif kind == 'thread':
                active_items = [
                    (t.id, (t.title or '').lower())
                    for t in self.relational.shared_history_threads.values()
                    if getattr(t, 'state', '') == 'active'
                ]
            elif kind == 'protocol':
                active_items = [
                    (p.id, (p.rule or '').lower())
                    for p in self.relational.unspoken_protocols.values()
                    if getattr(p, 'state', '') == 'active'
                ]
            else:
                active_items = []
        except Exception as e:
            return True, f'active_list_fail:{str(e)[:40]}'

        threshold = float(
            self._effective_runtime().get('pre_activate_dedup_jaccard', 0.6)
        )
        cand_id = self._entity_id(entity)

        for ex_id, ex_text in active_items:
            if ex_id == cand_id:
                continue  # 排除自己
            ex_text = (ex_text or '').strip()
            if not ex_text:
                continue
            # 1. substring (≥ 12 char) 直接拦
            if (len(cand_text) >= 12 and len(ex_text) >= 12
                    and (cand_text in ex_text or ex_text in cand_text)):
                return False, (
                    f'substring_match active={ex_id[:20]} '
                    f'(ex="{ex_text[:50]}")'
                )
            # 2. jaccard
            ex_tokens = set(_re.findall(r'\w+', ex_text))
            if not ex_tokens:
                continue
            inter = len(cand_tokens & ex_tokens)
            union = len(cand_tokens | ex_tokens)
            jaccard = (inter / union) if union > 0 else 0.0
            if jaccard >= threshold:
                return False, (
                    f'jaccard={jaccard:.2f}>={threshold} '
                    f'active={ex_id[:20]} (ex="{ex_text[:50]}")'
                )
        return True, 'no_dup'

    # ----------------------------------------------------------
    # Evidence collection
    # ----------------------------------------------------------
    def _collect_evidence(self, kind: str, entity) -> dict:
        ev = {'kind': kind, 'entity': {}}
        try:
            if kind == 'inside_joke':
                ev['entity'] = {
                    'phrase': getattr(entity, 'phrase', ''),
                    'birth_context': getattr(entity, 'birth_context', ''),
                    'tone': getattr(entity, 'tone', ''),
                    'source': getattr(entity, 'source', ''),
                }
                # 现有 active jokes (dedup 参考)
                active_jokes = [j for j in self.relational.inside_jokes.values()
                                  if getattr(j, 'state', '') == 'active']
                ev['existing_active_jokes'] = [
                    {'phrase': j.phrase[:80], 'tone': j.tone}
                    for j in active_jokes[:5]
                ]
                # 🆕 [E.4] active 总数 (LLM 看到 bloat 自动调严)
                ev['active_count_total'] = len(active_jokes)
            elif kind == 'thread':
                ev['entity'] = {
                    'title': getattr(entity, 'title', ''),
                    'detail': getattr(entity, 'detail', '')[:200],
                    'source': getattr(entity, 'source', ''),
                }
                active_threads = [t for t in
                                    self.relational.shared_history_threads.values()
                                    if getattr(t, 'state', '') == 'active']
                ev['existing_active_threads'] = [
                    {'title': t.title[:80]}
                    for t in active_threads[:5]
                ]
                ev['active_count_total'] = len(active_threads)
            elif kind == 'protocol':
                # 🆕 [Sir 2026-05-26 SOUL Phase A]
                ev['entity'] = {
                    'rule': getattr(entity, 'rule', ''),
                    'source': getattr(entity, 'source', ''),
                    'source_marker': getattr(entity, 'source_marker', ''),
                }
                active_protocols = [
                    p for p in self.relational.unspoken_protocols.values()
                    if getattr(p, 'state', '') == 'active'
                ]
                ev['existing_active_protocols'] = [
                    {'rule': p.rule[:120], 'source': p.source}
                    for p in active_protocols[:5]
                ]
                ev['active_count_total'] = len(active_protocols)
        except Exception:
            pass
        # STM 最近 5 turn (主脑近况)
        try:
            stm = []
            if self.nerve and getattr(self.nerve, 'short_term_memory', None):
                for t in list(self.nerve.short_term_memory)[-5:]:
                    stm.append({
                        'user': (t.get('user') or '')[:120],
                        'jarvis': (t.get('jarvis') or '')[:150],
                    })
            ev['stm'] = stm
        except Exception:
            ev['stm'] = []
        return ev

    # ----------------------------------------------------------
    # LLM evaluate (Flash-Lite, caller='auto_arbiter' → LOW)
    # ----------------------------------------------------------
    def _llm_evaluate(self, kind: str, entity,
                        evidence: dict) -> Tuple[str, float, str]:
        """调 LLM 评估 + 返 (action, confidence, reason).

        action: 'activate' | 'reject'  (LLM 不输出 defer/noop, 那是阈值映射)
        confidence: 0.0-1.0
        reason: <= 300 char
        """
        system, user = self._build_prompt(kind, entity, evidence)
        raw = self._call_llm(system, user)
        if not raw:
            self._llm_fail_count += 1
            return 'reject', 0.0, 'LLM call failed (treat as reject by default)'
        return self._parse_llm_output(raw)

    def _build_prompt(self, kind: str, entity,
                        evidence: dict) -> Tuple[str, str]:
        system = (
            f"You are J.A.R.V.I.S. acting as Sir's deputy auditor for the "
            f"{kind} review queue. A reflector has proposed a new {kind}; you "
            f"must decide ACTIVATE or REJECT based on evidence.\n\n"
            f"Output FORMAT (strict, 3 tags all required):\n"
            f"<ACTION>ACTIVATE|REJECT</ACTION>\n"
            f"<CONFIDENCE>0.0-1.0</CONFIDENCE>\n"
            f"<REASON>1-2 sentences explaining your judgment, citing "
            f"specific evidence (existing dedup / Sir's STM usage / "
            f"quality / tone fit).</REASON>\n\n"
            f"Decision criteria for {kind}:\n"
        )
        if kind == 'inside_joke':
            system += (
                "  ACTIVATE if: phrase is genuinely Sir-specific callback, NOT a\n"
                "    generic butler stock phrase any AI would say.\n"
                "    Must fit Sir's casual tone + have real evidence in STM (≥2 hits).\n"
                "  REJECT if: dry / forced / one-off / overlaps with existing joke /\n"
                "    no STM evidence / Sir would find it cringey / **GENERIC BUTLER\n"
                "    STOCK PHRASE** like 'I stand corrected, Sir' / 'As you wish' /\n"
                "    'Indeed, Sir' / 'Of course, Sir' / 'Understood, Sir' — these\n"
                "    are not inside jokes, they're hospitality clichés.\n"
                "  STOCK PHRASE TEST: Would any butler AI say this exact phrase\n"
                "    given similar context? If YES → REJECT (it's not Sir-specific).\n"
                "    Real inside joke = phrase that only makes sense to Sir+me\n"
                "    given our specific shared history (e.g. callback to a\n"
                "    specific incident, Sir's specific word choice, etc).\n"
                # 🆕 [Sir 2026-05-26 19:14 准则 6 极致版] 删 "必须<0.7" 硬规 —
                # 老 BUG: '2+ STM hits' 硬限 + 'otherwise <0.7' 强制 LLM 抑低
                # confidence → 大量 inside_joke 永远 defer_to_sir 赗积. STM 只 5 turn,
                # 一个 phrase 一般只 1 mention → 永过不了. 准则 6 信任 LLM 自评.
                "  CONFIDENCE: 你自评 0.0-1.0 (看整体 evidence 质量, 不必 抓 "
                "'2+ STM hits' 这种人为阈值). birth_context 含 Sir 具体 "
                "phrase 即可高 conf. Sir-specific + 未与现有 active jokes "
                "重叠 是 高 conf 项. stock butler phrase 仍 低 conf.\n"
            )
        elif kind == 'thread':
            system += (
                "  ACTIVATE if: real milestone Sir mentioned ≥ 2 times, "
                "distinct from existing active threads, has clear "
                "title + concrete detail.\n"
                "  REJECT if: vague / generic / overlaps with existing thread "
                "(e.g. another 'data alignment milestone' #4) / no STM "
                "evidence Sir cares.\n"
                # 🆕 [Sir 2026-05-26 19:14 准则 6 极致版] 删 '必须<0.7' 硬规 — 同 joke
                "  CONFIDENCE: 你自评 0.0-1.0 (看 evidence 质量, 不必 抓 '2+ "
                "STM hits'). 明确里程碑 + 与现有 active threads 明显 区别 是 "
                "高 conf 项. 模糊 / 重叠 / 广告词 仍 低 conf.\n"
            )
        elif kind == 'protocol':
            # 🆕 [Sir 2026-05-26 SOUL Phase A] protocol 严于 joke — 这是 STRICT 行为约束
            system += (
                "  ACTIVATE if: rule encodes a CONCRETE, ACTIONABLE behavior\n"
                "    constraint Sir would want enforced (e.g. 'Do not open\n"
                "    replies with formal apologies' / 'Skip exposition when\n"
                "    Sir says \u2018just do it\u2019'). Rule must be:\n"
                "      • IMPERATIVE form (Do / Don't / Always / Never)\n"
                "      • OBSERVABLE (someone reading my next reply can verify)\n"
                "      • DISTINCT from existing active protocols (no dup)\n"
                "      • Grounded in B-class self-reflection thought evidence.\n"
                "  REJECT if: vague (e.g. 'be nicer') / generic butler norm /\n"
                "    overlaps with existing protocol / aspirational but un-\n"
                "    enforceable / Sir-flatter rule (e.g. 'always praise Sir').\n"
                "  Remember: this becomes STRICT RULES injected into Sir-facing\n"
                "    prompts. Bad protocol → main brain over-constrained → worse\n"
                "    replies. Apply solid REJECT criteria, but if rule is\n"
                "    concrete + observable + distinct from active, ACTIVATE\n"
                "    with confident judgment (≥ 0.80). Don't reflex-defer.\n"
                # 🆕 [Sir 2026-05-26 19:14 准则 6 极致版] 删 '必须<0.7' 硬规 — 同 joke
                "  CONFIDENCE: 你自评 0.0-1.0 (看 rule 具体度 + observable + "
                "distinct). 具体可看 + 与现有 active 不重叠 是 高 conf 项. "
                "模糊 / 重叠 / 广告词 仍 低 conf. Be 严格 — protocol 是 STRICT "
                "RULES, 错 protocol 过约束 主脑.\n"
            )
        else:
            system += (
                "  (Generic) Use evidence to judge fairly.\n"
            )
        # 🆕 [Sir 2026-05-26 21:02 方案 E.2 治本] 删 conservative bias.
        # 老 BUG: 'When in doubt REJECT' 指令 + 'Be conservative' x 2 处 →
        # LLM 难以自信给 conf ≥ 0.80 → 大量 protocol stuck defer_to_sir →
        # dashboard pending bloat. 准则 6 极致: 信 LLM 自评, 不加一侧压低.
        # Sir 元否决 + revert log + monitor daemon 兑底.
        system += (
            "\nRules (准则 5+6+8):\n"
            "  - Cite specific evidence; do NOT hallucinate facts not in "
            "the input below.\n"
            "  - Self-assess confidence fairly based on evidence — if "
            "evidence is solid and item is distinct from existing active "
            "set, give a HIGH confidence (≥ 0.80). If evidence is thin / "
            "item is generic / overlap exists, give LOW confidence and "
            "the threshold gate will defer to Sir. Don't artificially "
            "suppress confidence — trust your judgment.\n"
            "  - Brief, factual, no Sir-flatter."
        )

        # user
        ent = evidence.get('entity', {})
        if kind == 'inside_joke':
            user_lines = ["[CANDIDATE INSIDE_JOKE]"]
            user_lines.append(f"  phrase:        \"{ent.get('phrase', '')}\"")
            user_lines.append(
                f"  birth_context: \"{(ent.get('birth_context') or '')[:160]}\""
            )
            user_lines.append(f"  tone:          {ent.get('tone', '')}")
            user_lines.append(f"  source:        {ent.get('source', '')}")
            user_lines.append("")
            user_lines.append("[EXISTING ACTIVE JOKES (dedup reference)]")
            existing = evidence.get('existing_active_jokes') or []
            if existing:
                for j in existing:
                    user_lines.append(
                        f"  - \"{j['phrase']}\" (tone={j['tone']})"
                    )
            else:
                user_lines.append("  (none active)")
        elif kind == 'thread':
            user_lines = ["[CANDIDATE SHARED_HISTORY_THREAD]"]
            user_lines.append(f"  title:  \"{ent.get('title', '')}\"")
            user_lines.append(
                f"  detail: \"{(ent.get('detail') or '')[:180]}\""
            )
            user_lines.append(f"  source: {ent.get('source', '')}")
            user_lines.append("")
            user_lines.append("[EXISTING ACTIVE THREADS (dedup reference)]")
            existing = evidence.get('existing_active_threads') or []
            if existing:
                for t in existing:
                    user_lines.append(f"  - \"{t['title']}\"")
            else:
                user_lines.append("  (none active)")
        elif kind == 'protocol':
            # 🆕 [Sir 2026-05-26 SOUL Phase A]
            user_lines = ["[CANDIDATE UNSPOKEN_PROTOCOL]"]
            user_lines.append(f"  rule:          \"{ent.get('rule', '')}\"")
            user_lines.append(f"  source:        {ent.get('source', '')}")
            user_lines.append(
                f"  source_marker: {(ent.get('source_marker') or '')[:60]}"
            )
            user_lines.append("")
            user_lines.append("[EXISTING ACTIVE PROTOCOLS (dedup reference)]")
            existing = evidence.get('existing_active_protocols') or []
            if existing:
                for p in existing:
                    user_lines.append(
                        f"  - \"{p['rule']}\" (source={p['source']})"
                    )
            else:
                user_lines.append("  (none active — first protocol!)")
        else:
            user_lines = [f"[CANDIDATE {kind.upper()}]", repr(ent)[:300]]

        user_lines.append("")
        user_lines.append("[SIR RECENT STM (last 5 turns)]")
        stm = evidence.get('stm') or []
        if stm:
            for t in stm:
                if t.get('user'):
                    user_lines.append(f"  Sir:    \"{t['user']}\"")
                if t.get('jarvis'):
                    user_lines.append(f"  Me:     \"{t['jarvis']}\"")
        else:
            user_lines.append("  (no recent STM)")
        # 🆕 [E.4] 显式列 active 总数 让 LLM 看到 bloat 自动调严
        # 老 BUG: prompt 只列前 5 个 active, LLM 不知总量. 当 active 已 30+,
        # LLM 看仍只 5 条 → 误以为 "active 很少, 可以多 activate" → bloat.
        # 修法: 显式 TOTAL ACTIVE: N. 主脑 LLM 看到 N>20 自然降 conf.
        active_n = int(evidence.get('active_count_total', 0))
        user_lines.append("")
        if active_n > 0:
            bloat_hint = ""
            if active_n >= 30:
                bloat_hint = " (⚠️ bloat zone — only ACTIVATE if truly distinct + valuable)"
            elif active_n >= 15:
                bloat_hint = " (heads-up — getting crowded, apply stricter dedup)"
            user_lines.append(
                f"[TOTAL ACTIVE {kind.upper()}S]: {active_n}{bloat_hint}"
            )
        else:
            user_lines.append(
                f"[TOTAL ACTIVE {kind.upper()}S]: 0 (first one — give chance)"
            )
        user_lines.append("")
        user_lines.append(
            "Now output your decision (3 tags strict)."
        )
        return system, '\n'.join(user_lines)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            reflector = LlmReflector(key_router=self.key_router)
            self._llm_call_count += 1
            res = reflector.reflect(
                model='flash_lite',
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                force=True,
                caller=getattr(KeyRouter, 'CALLER_AUTO_ARBITER',
                                'auto_arbiter'),  # auto_arbiter → LOW
            )
            if not res.get('success'):
                return ''
            return res.get('raw_text', '') or ''
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] LLM call exception: {e}")
            return ''

    def _parse_llm_output(self, raw: str) -> Tuple[str, float, str]:
        action_m = re.search(r'<ACTION>\s*(ACTIVATE|REJECT)\s*</ACTION>',
                                raw, re.IGNORECASE)
        conf_m = re.search(r'<CONFIDENCE>\s*([0-9.]+)\s*</CONFIDENCE>', raw)
        reason_m = re.search(r'<REASON>(.*?)</REASON>', raw, re.DOTALL)
        if not (action_m and conf_m):
            return 'reject', 0.0, f'LLM output parse fail: {raw[:120]}'
        action = action_m.group(1).lower()
        try:
            conf = max(0.0, min(1.0, float(conf_m.group(1))))
        except (ValueError, TypeError):
            conf = 0.0
        reason = reason_m.group(1).strip()[:300] if reason_m else ''
        return action, conf, reason

    # ----------------------------------------------------------
    # Execute decision (真调 relational API)
    # ----------------------------------------------------------
    def _execute(self, kind: str, item_id: str,
                  action: str) -> Tuple[bool, str]:
        # 🆕 [Sir 2026-05-26 SOUL Phase A] protocol 复用 activate/reject_from_review 路径
        if kind in ('inside_joke', 'thread', 'protocol'):
            try:
                if action == 'activate':
                    res_kind = self.relational.activate_from_review(item_id)
                    if not res_kind:
                        return False, f'activate_from_review returned empty (item_id={item_id})'
                    # persist
                    try:
                        self.relational.persist()
                        self.relational.write_review_queue()
                    except Exception:
                        pass
                    return True, f'activated as {res_kind}'
                elif action == 'reject':
                    res_kind = self.relational.reject_from_review(item_id)
                    if not res_kind:
                        return False, f'reject_from_review returned empty'
                    try:
                        self.relational.persist()
                        self.relational.write_review_queue()
                    except Exception:
                        pass
                    return True, f'rejected as {res_kind}'
                else:
                    return False, f'unknown action {action}'
            except Exception as e:
                return False, f'exec exception: {str(e)[:100]}'
        return False, f'kind {kind} not supported for auto-execute'

    # ----------------------------------------------------------
    # Sir 撤销 (准则 7 元否决)
    # ----------------------------------------------------------
    def sir_revert(self, decision_id: str,
                    reason: str = '') -> Tuple[bool, str]:
        """Sir 一键撤销某条 auto decision.

        撤销规则:
          - 当时 activate → 撤销 = reject_from_review (退回 review 状态需重 propose)
            实际: archive 已 active 的 → Sir 看不到, joke 不会再 inject
          - 当时 reject → 撤销 = 重 propose (难: archive 已 archive 的 → ???)
            简化: 仅记 sir_reverted 标记, 不真撤回 (rejected 的不易回)
          - 当时 defer_to_sir / noop → 仅记标记, 无副作用
        """
        target: Optional[ArbiterDecision] = None
        with self._lock:
            for d in self._decisions:
                if d.id == decision_id:
                    target = d
                    break
        if target is None:
            return False, f'decision {decision_id} not found'
        if target.sir_reverted:
            return False, f'already reverted at {target.sir_reverted_at}'

        msg = 'marked as reverted'
        try:
            if target.decision == 'activate' and target.executed_ok:
                # 反向 reject (archive 已 active 的)
                if self.relational and target.kind in ('inside_joke', 'thread'):
                    # 直接 setattr state=archived (因 active 的不能 reject_from_review)
                    try:
                        store_map = {
                            'inside_joke': self.relational.inside_jokes,
                            'thread': self.relational.shared_history_threads,
                        }
                        store = store_map.get(target.kind)
                        if store and target.item_id in store:
                            entity = store[target.item_id]
                            entity.state = 'archived'
                            self.relational._dirty = True
                            self.relational.persist()
                            self.relational.write_review_queue()
                            msg = f'reverted: {target.kind} {target.item_id} → archived'
                    except Exception as e:
                        msg = f'revert exec exception: {str(e)[:100]}'
            elif target.decision == 'reject' and target.executed_ok:
                # 反向 activate: 把已 archive 的重激活 (Sir 后悔拒了)
                if self.relational and target.kind in ('inside_joke', 'thread'):
                    try:
                        store_map = {
                            'inside_joke': self.relational.inside_jokes,
                            'thread': self.relational.shared_history_threads,
                        }
                        store = store_map.get(target.kind)
                        if store and target.item_id in store:
                            entity = store[target.item_id]
                            entity.state = 'active'
                            self.relational._dirty = True
                            self.relational.persist()
                            self.relational.write_review_queue()
                            msg = f'reverted: {target.kind} {target.item_id} → active'
                    except Exception as e:
                        msg = f'revert exec exception: {str(e)[:100]}'
        except Exception as e:
            msg = f'revert exception: {str(e)[:100]}'

        # 标记 + 持久 + publish SWM
        with self._lock:
            target.sir_reverted = True
            target.sir_reverted_at = time.time()
            target.sir_revert_reason = (reason or '')[:200]
        # rewrite (append a new line with same id, dashboard 看时取最新)
        self._persist_decision(target)

        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='sir_reverted_auto_arbitrate',
                    description=(
                        f"Sir reverted auto {target.decision} of "
                        f"{target.kind} {target.item_id} — reason: {reason[:80]}"
                    ),
                    source='auto_arbiter',
                    salience=0.7,
                    metadata={
                        'decision_id': decision_id,
                        'kind': target.kind,
                        'item_id': target.item_id,
                        'orig_decision': target.decision,
                        'reason': reason[:200],
                    },
                    ttl=86400.0,
                )
        except Exception:
            pass

        self._bg_log(
            f"🔄 [AutoArbiter] sir_revert {target.kind}/{target.item_id} "
            f"({target.decision}) → {msg} | Sir reason: {reason[:80]}"
        )
        return True, msg

    # ----------------------------------------------------------
    # Daily reflection (Sir 真问 "通过每日的思考迭代准确性")
    # ----------------------------------------------------------
    def _maybe_do_daily_reflection(self) -> None:
        """每天 03:xx 检查时 fire 一次 (一天最多 1 次)."""
        now_local = time.localtime()
        today = time.strftime('%Y-%m-%d', now_local)
        if now_local.tm_hour != self.DAILY_REFLECTION_HOUR:
            return
        if self._last_reflection_date == today:
            return
        self._last_reflection_date = today
        self._do_daily_reflection()

    def _do_daily_reflection(self) -> None:
        """看 24h decisions, per kind 算 revert_rate, 调阈值."""
        cutoff = time.time() - 86400.0
        recent: List[ArbiterDecision] = []
        with self._lock:
            recent = [d for d in self._decisions if d.ts > cutoff]
        if not recent:
            self._bg_log(
                "🌙 [AutoArbiter] daily reflection: no decisions in last 24h"
            )
            return

        per_kind = {}
        for d in recent:
            if d.decision not in ('activate', 'reject'):
                continue
            k = d.kind
            if k not in per_kind:
                per_kind[k] = {'total': 0, 'reverted': 0}
            per_kind[k]['total'] += 1
            if d.sir_reverted:
                per_kind[k]['reverted'] += 1

        changes = []
        thresholds = self._effective_thresholds()
        for kind, stat in per_kind.items():
            total = stat['total']
            if total == 0:
                continue
            revert_rate = stat['reverted'] / total
            old_thr = thresholds.get(kind, 0.80)
            new_thr = old_thr
            why = ''
            if revert_rate > self.REVERT_RATE_HIGH:
                new_thr = min(self.THRESHOLD_CEILING,
                                old_thr + self.THRESHOLD_RAISE_STEP)
                why = f'revert_rate={revert_rate:.0%} > {int(self.REVERT_RATE_HIGH*100)}% (over-confident)'
            elif (revert_rate < self.REVERT_RATE_LOW and total >= 5
                    and old_thr > self.THRESHOLD_FLOOR):
                new_thr = max(self.THRESHOLD_FLOOR,
                                old_thr - self.THRESHOLD_LOWER_STEP)
                why = f'revert_rate={revert_rate:.0%} < {int(self.REVERT_RATE_LOW*100)}% (too conservative)'
            if abs(new_thr - old_thr) > 1e-3:
                self._calibration.setdefault('thresholds', {})[kind] = new_thr
                changes.append({
                    'kind': kind, 'total': total, 'reverted': stat['reverted'],
                    'old_thr': old_thr, 'new_thr': new_thr, 'why': why,
                })

        self._calibration['revert_history_24h'] = per_kind
        self._calibration['last_calibrated_at'] = time.time()
        self._calibration['last_calibrated_iso'] = time.strftime(
            '%Y-%m-%dT%H:%M:%S'
        )
        self._save_calibration()

        if changes:
            summary = '; '.join(
                f"{c['kind']}: {c['old_thr']:.2f}→{c['new_thr']:.2f} ({c['why']})"
                for c in changes
            )
            self._bg_log(
                f"🌙 [AutoArbiter] daily reflection: {len(recent)} decisions, "
                f"adjusted {len(changes)} thresholds | {summary}"
            )
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='auto_arbiter_calibration_updated',
                        description=summary,
                        source='auto_arbiter',
                        salience=0.6,
                        metadata={'changes': changes,
                                    'total_decisions_24h': len(recent)},
                        ttl=86400.0 * 3,
                    )
            except Exception:
                pass
        else:
            self._bg_log(
                f"🌙 [AutoArbiter] daily reflection: {len(recent)} decisions, "
                f"thresholds stable"
            )

    # ----------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------
    def _persist_decision(self, d: ArbiterDecision) -> None:
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            with open(self.PERSIST_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(d), ensure_ascii=False) + '\n')
            # 🆕 [Sir 2026-05-25 23:50 "防爆"] every 10 writes cheap rotate check
            try:
                from jarvis_jsonl_rotator import maybe_rotate
                maybe_rotate(self.PERSIST_PATH, check_every_n_writes=10)
            except Exception:
                pass
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] persist fail: {e}")

    def _load_persist(self) -> None:
        if not os.path.exists(self.PERSIST_PATH):
            return
        try:
            cutoff = time.time() - 7 * 86400.0  # 7d 历史
            latest_by_id: dict = {}
            with open(self.PERSIST_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get('ts', 0) < cutoff:
                            continue
                        # 同 id 多次写 (revert), 取最新
                        latest_by_id[rec.get('id')] = rec
                    except (json.JSONDecodeError, TypeError):
                        continue
            for rec in latest_by_id.values():
                try:
                    self._decisions.append(ArbiterDecision(**rec))
                except (TypeError, KeyError):
                    continue
        except Exception as e:
            self._bg_log(f"⚠️ [AutoArbiter] load fail: {e}")

    def _publish_swm(self, d: ArbiterDecision) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='auto_arbiter_decision',
                description=(
                    f"[{d.decision}/{d.kind}] {d.item_preview[:80]} "
                    f"(conf {d.confidence:.2f}/thr {d.threshold_at_decision:.2f})"
                ),
                source='auto_arbiter',
                salience=d.confidence if d.decision != 'noop' else 0.3,
                metadata={
                    'decision_id': d.id,
                    'kind': d.kind,
                    'item_id': d.item_id,
                    'decision': d.decision,
                    'confidence': d.confidence,
                    'executed_ok': d.executed_ok,
                    'risk_level': d.risk_level,
                },
                ttl=86400.0,
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Stats (dashboard / CLI 用)
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        with self._lock:
            decisions = list(self._decisions)
        now = time.time()
        h24 = now - 86400.0
        h24_decisions = [d for d in decisions if d.ts > h24]
        per_kind_24h = {}
        for d in h24_decisions:
            k = d.kind
            if k not in per_kind_24h:
                per_kind_24h[k] = {
                    'total': 0, 'activate': 0, 'reject': 0,
                    'defer_to_sir': 0, 'noop': 0, 'reverted': 0,
                }
            per_kind_24h[k]['total'] += 1
            per_kind_24h[k][d.decision] = per_kind_24h[k].get(d.decision, 0) + 1
            if d.sir_reverted:
                per_kind_24h[k]['reverted'] += 1
        return {
            'total_decisions_loaded': len(decisions),
            'decisions_24h': len(h24_decisions),
            'per_kind_24h': per_kind_24h,
            'effective_thresholds': self._effective_thresholds(),
            'tick_count': self._tick_count,
            'llm_call_count': self._llm_call_count,
            'llm_fail_count': self._llm_fail_count,
            'last_reflection_iso': (self._calibration or {}).get(
                'last_calibrated_iso', ''
            ),
        }

    def list_recent_decisions(self, max_n: int = 50,
                                 hours: float = 24.0) -> List[dict]:
        cutoff = time.time() - hours * 3600.0
        with self._lock:
            recent = [d for d in self._decisions if d.ts > cutoff]
        recent.sort(key=lambda d: -d.ts)
        return [asdict(d) for d in recent[:max_n]]

    # ----------------------------------------------------------
    # bg_log helper
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
_DEFAULT_DAEMON: Optional[AutoArbiterDaemon] = None


def get_default_daemon() -> Optional[AutoArbiterDaemon]:
    return _DEFAULT_DAEMON


def set_default_daemon(d: AutoArbiterDaemon) -> None:
    global _DEFAULT_DAEMON
    _DEFAULT_DAEMON = d
