# -*- coding: utf-8 -*-
"""[P1 / Sir 2026-05-25 22:10 数字生命基础] Inner Thought Daemon — 持续思考层.

Sir 真问 (22:10 + 22:20):
  "我们要开始推进贾维斯真正的思考层了 ... 长期 prompt 递进能不能让 LLM
   决策时更深刻地理解'贾维斯是我, 我是贾维斯'这个概念"
  "保持高效优雅, 真能看见他的思考的作用"

灵魂工程 Layer 1.5 — 主脑碎碎念 (sit between Layer 1 Concerns + Layer 2 Relational).

设计 (准则 6 evidence-driven + 准则 8 优雅高效):
  - Adaptive 频率 (按 Sir 真物理 idle 自适应):
      Sir 活跃 (idle < 5min)        → 60s tick   (实时 thought)
      Sir AFK 5-30min                → 3min tick  (反思频率)
      Sir 深 AFK 30min+              → 10min tick (低耗心跳)
      Sir 睡眠 (idle > 10min + 凌晨)  → 30min tick (仅维生)
  - 5 类思考池 (主脑自选, 不教 content):
      [A] OBSERVATION  — Sir 当前外部状态 (屏幕/沉默/活动)
      [B] SELF-REFLECT — 看自己最近 reply (tone / 错误 / pattern)
      [C] CONCERN-EVO  — 自评 severity 该升/降 (actionable: update_concern_severity)
      [D] PROACTIVE    — 下次该 silently 做什么 (actionable: publish_swm)
      [E] RELATIONSHIP — inside joke 候选 (actionable: suggest_inside_joke)
  - Actionable 4 档 (本期全可逆/低风险):
      none / update_concern_severity:<id>:<±delta> /
      publish_swm:<etype>:<desc> / suggest_inside_joke:<phrase>
  - Cooldown: 同 category 5min 不重复 + 单 tick 仅 1 thought
    (🆕 [Sir 2026-05-26 12:13 真痛 fix] 30min → 5min: 5 cat × 30min 让 daemon
     5 个 tick 后 silence 25min, 违 Sir "active=1 thought/min 持续" 真意.
     5min cooldown 保 1 thought/min 输出 (tick 6 时 cat A 已 free 300s) +
     同 category 隔 5min 防完全重复.)
  - 持久化: memory_pool/inner_thoughts.jsonl (append-only)
  - SOUL inject: top 3 by salience in last 24h → 主脑下次 turn prompt
    "MY RECENT INNER THOUGHTS" block (~500 char cap)

成本 (Flash-Lite + caller='inner_thought' → 自动 LOW priority, P2 KeyRouter 保护):
  混合频率 ~800 calls/day → $3/月 + 主脑 SOUL token 膨胀 $3.75/月 = ~$7/月

参考:
  docs/JARVIS_SOUL_DRIVE.md (灵魂工程 Layer 0-5 总览)
  jarvis_concerns.py update_concern_field (severity 真改路径)
  jarvis_key_router.py PRIORITY_LOW (本 daemon 自动 LOW, 不挤主流量)
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Tuple


# ==========================================================================
# 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 A 治本 / 准则 6 vocab 持久化]
# Soul block 排序权重 + cap 持久化 (memory_pool/inner_thought_soul_block_vocab.json)
# Sir 真痛: "想了一堆没体现在对话里" → 老 sal=0.9 挤掉新 sal=0.7.
# 治本: score = salience*w_sal + recency*w_rec (e^(-age/halflife)), 权重 vocab 可改.
# ==========================================================================
_SOUL_BLOCK_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_soul_block_vocab.json',
)
_SOUL_BLOCK_CONFIG_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_SOUL_BLOCK_CONFIG_CHECK_INTERVAL_S = 30.0

# fallback config (vocab fail 时用, 让 daemon 不崩)
_SOUL_BLOCK_DEFAULT_CONFIG: dict = {
    'weights': {'salience': 0.5, 'recency': 0.5},
    'recency_halflife_s': 3600,
    'max_inject': 5,
    'max_chars': 800,
    'max_age_s': 86400,
}


def _load_soul_block_config() -> dict:
    """Lazy load soul block vocab + mtime 30s throttle. 失败 fallback default."""
    now = time.time()
    if (_SOUL_BLOCK_CONFIG_CACHE['data'] is not None and
            now - _SOUL_BLOCK_CONFIG_CACHE['checked_at']
            < _SOUL_BLOCK_CONFIG_CHECK_INTERVAL_S):
        return _SOUL_BLOCK_CONFIG_CACHE['data']
    _SOUL_BLOCK_CONFIG_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_SOUL_BLOCK_VOCAB_PATH):
            _SOUL_BLOCK_CONFIG_CACHE['data'] = _SOUL_BLOCK_DEFAULT_CONFIG
            return _SOUL_BLOCK_DEFAULT_CONFIG
        mtime = os.path.getmtime(_SOUL_BLOCK_VOCAB_PATH)
        if (mtime == _SOUL_BLOCK_CONFIG_CACHE['mtime']
                and _SOUL_BLOCK_CONFIG_CACHE['data']):
            return _SOUL_BLOCK_CONFIG_CACHE['data']
        with open(_SOUL_BLOCK_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # merge with default (容错: vocab 缺 key fallback)
        config = dict(_SOUL_BLOCK_DEFAULT_CONFIG)
        for k in ('weights', 'recency_halflife_s', 'max_inject', 'max_chars',
                    'max_age_s'):
            if k in data:
                config[k] = data[k]
        _SOUL_BLOCK_CONFIG_CACHE['data'] = config
        _SOUL_BLOCK_CONFIG_CACHE['mtime'] = mtime
        return config
    except Exception:
        return _SOUL_BLOCK_DEFAULT_CONFIG


# ==========================================================================
# 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 C 治本 / 准则 6 vocab 持久化]
# surface_to_sir 阈值 / 频限 / 通道白名单 (memory_pool/surface_to_sir_vocab.json)
# Sir 真痛: "思考层没主动发声". 给 thought 一档轻量 surface 通道
# (terminal_pulse / next_turn_inject), 不抢 voice channel.
# ==========================================================================
_SURFACE_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'surface_to_sir_vocab.json',
)
_SURFACE_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_SURFACE_VOCAB_CHECK_INTERVAL_S = 30.0

_SURFACE_DEFAULT_CONFIG: dict = {
    'salience_threshold': 0.7,
    'cooldown_global_s': 120,
    'cooldown_per_channel_s': 300,
    'max_per_hour': 6,
    'allowed_channels': ['terminal_pulse', 'next_turn_inject'],
}


def _load_surface_to_sir_config() -> dict:
    """Lazy load surface vocab + mtime 30s throttle. 失败 fallback default."""
    now = time.time()
    if (_SURFACE_VOCAB_CACHE['data'] is not None and
            now - _SURFACE_VOCAB_CACHE['checked_at']
            < _SURFACE_VOCAB_CHECK_INTERVAL_S):
        return _SURFACE_VOCAB_CACHE['data']
    _SURFACE_VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_SURFACE_VOCAB_PATH):
            _SURFACE_VOCAB_CACHE['data'] = _SURFACE_DEFAULT_CONFIG
            return _SURFACE_DEFAULT_CONFIG
        mtime = os.path.getmtime(_SURFACE_VOCAB_PATH)
        if (mtime == _SURFACE_VOCAB_CACHE['mtime']
                and _SURFACE_VOCAB_CACHE['data']):
            return _SURFACE_VOCAB_CACHE['data']
        with open(_SURFACE_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        config = dict(_SURFACE_DEFAULT_CONFIG)
        for k in ('salience_threshold', 'cooldown_global_s',
                    'cooldown_per_channel_s', 'max_per_hour',
                    'allowed_channels'):
            if k in data:
                config[k] = data[k]
        _SURFACE_VOCAB_CACHE['data'] = config
        _SURFACE_VOCAB_CACHE['mtime'] = mtime
        return config
    except Exception:
        return _SURFACE_DEFAULT_CONFIG


# ==========================================================================
# Data structure
# ==========================================================================

@dataclass
class InnerThought:
    """单条 Jarvis 内心独白. 持久化 + SOUL inject."""
    id: str
    ts: float
    ts_iso: str
    category: str            # 'A' | 'B' | 'C' | 'D' | 'E'
    thought: str             # 1-2 sentences, first-person Jarvis POV
    salience: float          # 0.0-1.0
    actionable: str          # 'none' / 'update_concern_severity:...' / ...
    actionable_done: bool = False
    actionable_result: str = 'pending'
    # 🆕 [Sir 2026-05-26 19:48 Phase 2B] thought outcome (Sir react/ignore feedback)
    # =====================================================================
    # 让 thought 真"学" — 落 outcome 后, WeeklyReflectionConsolidator 7d 看
    # sir_engaged rate / sir_silenced rate / sir_rejected rate per category,
    # 反馈 dashboard 调 daemon SAL threshold / cooldown.
    # 现 daemon 不自动判 outcome (需要主脑 reply track + Sir 反应 detector),
    # 这是 Phase 2B Wire 1: 字段就位, outcome 判别由 WRC 反思时打 (read SWM).
    # 值: 'pending' (未 fire), 'sir_engaged' (Sir 回应正面), 'sir_silenced'
    #     (Sir 没回应), 'sir_rejected' (Sir 直接说"别提了"/"不要")
    # =====================================================================
    outcome: str = 'pending'
    sir_state: str = 'unknown'     # 'active' / 'afk_short' / 'afk_deep' / 'sleep'
    tick_interval_s: int = 60
    # 🆕 [Sir 2026-05-26 12:21 真意 Meta-thinking] daemon 让 thought 决定下次 tick 间隔.
    # Sir 原话: "这个思考的间隔能否也成为他思考的一部分? 发现我离开了就减慢思考频率,
    # 发现我回来了就回到 1 分钟一次, 如果很需要频繁思考甚至可以提高 30s 一次".
    # LLM 输出 NEXT_INTERVAL ∈ {30, 60, 180, 600, 1800, default}
    # 'default' = 用 _compute_adaptive_interval baseline (物理状态驱动)
    # Python physical gate: LLM 选超物理边界 → fallback baseline
    # (e.g. sleep 不能选 30s, active 不能选 1800s — 准则 6 信任 LLM 但物理保底)
    # Python smoothing: 最近 5 thought ≥3 选 30s + 平均 sal<0.5 → 强制回 60s
    # (防 token 爆 + 低质量急思考惩罚)
    # 0 = 未设 (老 thought 兼容 + LLM 没输出时 fallback)
    next_interval_s: int = 0
    # 'llm_chosen' = LLM 主动选 (LLM 真给 NEXT_INTERVAL 且 pass physical gate)
    # 'llm_gated' = LLM 选超物理边界, Python fallback baseline
    # 'llm_smoothed' = Python smoothing 强制回 60s (LLM 多次低质量 30s)
    # 'default' = LLM 选 default 或没给, 用 baseline
    # '' = 未设 (老 thought 兼容)
    tick_origin: str = ''
    # 🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] evidence linking 防 LLM 拍脑袋
    # actionable != none 时 LLM 必须 cite THOUGHT 中真实出现的 1-5 词字串证明
    # thought → actionable 真有 trace. Python 校验 cite 在 thought 里, 否则
    # 降级 actionable='none' (无 evidence 不执行, 准则 5 言出必行 + 6 evidence).
    evidence_link: str = ''
    # 🆕 [Sir 2026-05-27 00:11 真意 M1 ThoughtChain] thought 连续性 thread.
    # Sir 真意: "思考能连续, 不像现在离散像看故事". 同主题 thought 串成 thread,
    # 主脑下次 tick 看上 3 thought 自决 "same_thread:<id>" / "new_topic".
    # Python 不判 thread, 只追踪 LLM 自报值; 同主题串成链便于 dashboard 可视化.
    thread_id: str = ''         # ID of thought thread this belongs to (新 thread = self.id)
    continuity: str = 'new_topic'  # 'same_thread' / 'new_topic' (LLM 自报)


# ==========================================================================
# Helpers
# ==========================================================================

def _truncate_at_word_boundary(s: str, max_chars: int,
                                 suffix: str = '…') -> str:
    """🆕 [Sir 2026-05-27 21:11 真测 P2_b] 防 log 截到字/词中间.

    Sir 真测 21:04 看到:
      `actionable=propose_protocol:Always match Sir's conf → ...`
      `proposed:Always match Sir's confirmatio (id=...)`
      `I should aim for a more aligned ton`
    全是 [:N] 硬切到 word 中间, 可读性差.

    算法:
      - len <= max_chars → 直接返
      - cut = s[:max_chars], 倒查最近 word boundary (space/punct),
        回退不超过 max_chars*0.2 (避免丢太多). 找到 → 截到那 + suffix
      - 没找到 → 仍按 max_chars 切 + suffix (CJK 字符天然可切 + 加 …
        视觉上明示截断)
    """
    if not s or len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    boundary_chars = ' .,;:!?，。；：！？\n\t'
    # 允许回退 30% (ratio 0.7) — 给短 max_chars (e.g. 24) 也够空间找 boundary
    lo = max(1, int(max_chars * 0.7))
    for i in range(len(cut) - 1, lo - 1, -1):
        if cut[i] in boundary_chars:
            return cut[:i].rstrip(boundary_chars) + suffix
    return cut.rstrip() + suffix


# ==========================================================================
# Daemon
# ==========================================================================

class InnerThoughtDaemon:
    """Adaptive tick inner thought daemon. 主脑碎碎念 → 持续 identity 涌现.

    生命周期:
      __init__(key_router, concerns_ledger, relational_state, central_nerve)
      start()  → 后台 thread 启动
      stop()   → 停止
      build_soul_block(max_chars) → 拿 SOUL inject text (主脑下次 turn 看)
    """

    PERSIST_PATH = 'memory_pool/inner_thoughts.jsonl'

    # SOUL inject 参数
    SOUL_INJECT_MAX = 3
    SOUL_INJECT_MAX_CHARS = 500

    # adaptive frequency (sec)
    # 🆕 [Sir 2026-05-26 23:24 真痛 D / 准则 4 懂我] 60 → 45s active baseline.
    # =========================================================================
    # Sir 真痛: "我想让他频繁思考的本意是想让他拥有小于我观察间隔的唤醒, 看着像
    # 持续存在的生命". 60s 觉得"不够生命感". Sir google_1 paid $10/月 cap, 用 lite
    # 模型 60s→45s active ⇒ ~$8/月 paid Google (16h × 80 ticks/h × 50% paid lite),
    # 余 $2 buffer. 不爆 cap. 加频不无脑 (Sir 拒 30s 爆 cap), 45s 是优雅平衡点.
    # =========================================================================
    INTERVAL_ACTIVE_S = 45
    INTERVAL_AFK_SHORT_S = 180
    INTERVAL_AFK_DEEP_S = 600
    INTERVAL_SLEEP_S = 1800

    # 阈值 (sec)
    THRESHOLD_AFK_SHORT_S = 300       # idle > 5min = afk_short
    THRESHOLD_AFK_DEEP_S = 1800       # idle > 30min = afk_deep
    THRESHOLD_SLEEP_IDLE_S = 600      # sleep state: idle > 10min
    SLEEP_HOUR_START = 0              # 凌晨 0-6 点
    SLEEP_HOUR_END = 6

    # 🆕 [Sir 2026-05-26 19:01 真痛 元否决 BUG 治本] 准则 6 极致版 — 删 hardcode vocab
    # =========================================================================
    # Sir 19:01 真痛: "怎么我看你的思考链里一堆硬编码? 知道我不在/在电脑前很困难吗?
    # 我们有 30+ 种 sensor 参数矩阵!"
    #
    # 源 BUG: BUG 1 fix (13:32) 用 _REST_INTENT_VOCAB hardcode list (15 keyword) +
    # _has_active_rest_commitment 反推 sleep. 这是把"硬编码时间窗"换成"硬编码 vocab",
    # 没真治本. 19:01 实测仍然 fire — Sir 18:59 真意 "回来" 已被 SirStatusTracker capture
    # 但 daemon 不看, 继续看自己反推 vocab.
    #
    # 真治本 (准则 6 数据强耦合 + 准则 8 优雅):
    #   _classify_sir_state 直接看 SirStatusTracker.current_status() (Sir 真意 sensor,
    #   vocab 已 jarvis_sir_status_tracker.py 持久化 + publish SWM 'sir_declared_status').
    #   + idle 物理 atomic 短路 (< 5min 永远 active, 不管声明).
    #   + is_overdue check (Sir 声明 lunch 已过 3h → 默认回 active).
    #
    # 删: _REST_INTENT_VOCAB + _has_active_rest_commitment (this is the fix).
    # =========================================================================

    # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] LLM-self-chosen tick interval.
    # Sir 真意: thought 决定下次思考间隔 (而不只是物理状态驱动).
    # enum 5 + 'default' (6 选 1): 30s 急 / 60s active 默认 / 180s afk_short /
    # 600s afk_deep / 1800s sleep / default (用 _compute_adaptive_interval baseline)
    # 🆕 [Sir 2026-05-26 23:24] 加 45s (active 默认), Sir 加频但守 $10 cap.
    _NEXT_INTERVAL_ENUM = frozenset({30, 45, 60, 180, 600, 1800})

    # Physical gate (准则 6 信任 LLM 但物理保底):
    # 物理 sir_state 决定哪些 interval LLM 可选. 超出 → fallback baseline.
    # 例: Sir active 不能选 1800 (Sir 真在不能等 30min);
    #     Sir sleep 不能选 30 (睡觉时不应急思考 — 浪费 token + 噪音).
    _PHYSICAL_GATE = {
        'active':    frozenset({30, 45, 60, 180}),  # 🆕 [23:24] +45
        'afk_short': frozenset({45, 60, 180, 600}),  # 🆕 [23:24] +45 (Sir 回来 fast)
        'afk_deep':  frozenset({180, 600, 1800}),
        'sleep':     frozenset({600, 1800}),
        'unknown':   frozenset({60, 180, 600}),  # fallback 中庸
    }

    # Smoothing (防 LLM 总选 30s 爆 token):
    # 最近 N thought 中如果有 ≥ K 选 30s + 平均 sal < threshold → 强制回 60s.
    _SMOOTH_LOOKBACK_N = 5     # 看最近 5 thought
    _SMOOTH_HIGH_FREQ_K = 3    # ≥ 3 个选 30s 算 high-freq
    _SMOOTH_LOW_SAL_THRESHOLD = 0.5  # 平均 sal < 0.5 算 low-quality

    # cooldown
    # 🆕 [Sir 2026-05-26 12:13 真痛 fix] 30min → 5min cooldown.
    # 根因: 5 cat × 30min → 前 5 tick 生 thought 后 silence 25min,
    # 违 Sir 真意 "active = 1 thought / 60s 持续输出".
    # 修: 300s 后极限不静默 (tick 6 = 5min, cat A.last_ts=0 时 cat A 已 free 300s).
    # 同 category 仍隔 5min, 保 diversity 不连发重复.
    SAME_CATEGORY_COOLDOWN_S = 300   # 5min 同 category 不重复 (Sir 12:13 真痛 fix)
    STARTUP_DELAY_S = 30              # 启动 30s 后才开始 (系统稳定)

    # 🆕 [Sir 2026-05-26 23:24 真痛 BUG-5 / 准则 8 优雅] mediocre thought 兜底
    # =========================================================================
    # 当 LLM 没 follow "(quiet) sal=0.0" prompt rule, 输出 sal<0.5 + 无 action 的
    # A/E (passive observation/relationship) thought → daemon skip SWM publish,
    # 不污染 dashboard, log compact. thought 仍 persist (preserve for chain v2).
    # =========================================================================
    _MEDIOCRE_SAL_THRESHOLD = 0.5

    # actionable cap
    SEVERITY_DELTA_CAP = 0.2          # update_concern_severity ±0.2 per thought

    # 🆕 [Sir 2026-05-26 18:54 FIX B/C] runtime_log + SWM action filter constants
    # =====================================================================
    # _ACTION_EVENT_PREFIXES: SWM filter — 从 event_bus 拉真 jarvis 行为 etype
    #                         prefix (准则 6 vocab 持久化 memory_pool/
    #                         runtime_log_marker_vocab.json + CLI 可改 + L7 propose)
    # RUNTIME_LOG_TAIL_BYTES: log seek 末尾字节数 (100KB ~1500 行 ~ 5-30min 覆盖)
    # RUNTIME_LOG_TAIL_MAX_LINES: filter marker 后最多收 N 行 (cap 总 token ~600)
    # RUNTIME_LOG_LINE_MAX_CHARS: 单行 cap 防 super 长 prompt 行污染
    # =====================================================================
    RUNTIME_LOG_TAIL_BYTES = 100_000
    RUNTIME_LOG_TAIL_MAX_LINES = 12
    RUNTIME_LOG_LINE_MAX_CHARS = 180
    RUNTIME_LOG_LATEST_PATH = 'docs/runtime_logs/latest.txt'

    @property
    def _ACTION_EVENT_PREFIXES(self) -> tuple:
        """SWM event_bus filter — 真 jarvis 行为 etype prefix.

        准则 6 vocab 持久化: 从 jarvis_runtime_log_markers 加载,
        Sir CLI add/remove 直接生效 (mtime check, 30s throttle).
        缺失 / 损坏 → fallback 内置 DEFAULTS (preserve daemon 可用).
        """
        try:
            from jarvis_runtime_log_markers import load_action_event_prefixes
            return load_action_event_prefixes()
        except Exception:
            return (
                'proactive_nudge_', 'inner_thought_',
                'concern_severity_changed', 'concern_notes_appended',
                'promise_', 'commitment_', 'reminder_', 'wake_',
                'sir_intent_', 'stand_down_', 'utterance_appended',
            )

    def _collect_runtime_log_tail(self, max_lines: int = None) -> list:
        """🆕 [Sir 2026-05-26 18:54 FIX C] 拉 runtime_log tail 让反思看真日志.

        策略 (准则 8 优雅 — 不全量 read 防 token + IO 爆):
          1. read latest.txt → resolve abs log path (1 IO)
          2. os.path.getsize() — file_size 算
          3. f.seek(max(0, file_size - 100KB)) — 从末尾 100KB 开始读 (~1500 行)
          4. UTF-8 decode errors='ignore' (防 emoji 部分写入)
          5. lines reversed() → marker regex hit → collect
          6. 收 max_lines=12 即 break
          7. 倒序返回 (旧→新, 让 LLM 自然读时间线)
          8. 每行 cap 180 char + 全量 cap ~2.2KB

        Safety: 任何 IO/decode error → return [] (daemon 不挂).

        Args:
          max_lines: cap 行数 (None = 用 RUNTIME_LOG_TAIL_MAX_LINES=12).

        Returns: List[str] (旧→新, 已 marker filter + cap line len).
        """
        max_lines = max_lines or self.RUNTIME_LOG_TAIL_MAX_LINES
        try:
            # Step 1: resolve log path from latest.txt
            latest_path = self.RUNTIME_LOG_LATEST_PATH
            if not os.path.isabs(latest_path):
                # 相对路径 → 解析为 jarvis root 下
                root = os.path.dirname(os.path.abspath(__file__))
                latest_path = os.path.join(root, latest_path)
            if not os.path.exists(latest_path):
                return []
            with open(latest_path, 'r', encoding='utf-8') as f:
                log_path = f.read().strip()
            if not log_path:
                return []
            if not os.path.isabs(log_path):
                root = os.path.dirname(os.path.abspath(__file__))
                log_path = os.path.join(root, log_path)
            if not os.path.exists(log_path):
                return []

            # Step 2-4: seek tail + decode
            file_size = os.path.getsize(log_path)
            read_offset = max(0, file_size - self.RUNTIME_LOG_TAIL_BYTES)
            with open(log_path, 'rb') as f:
                f.seek(read_offset)
                data = f.read()
            text = data.decode('utf-8', errors='ignore')
            lines = text.split('\n')

            # Step 5-6: reversed marker filter
            from jarvis_runtime_log_markers import load_marker_regex
            marker_re = load_marker_regex()
            collected = []
            for line in reversed(lines):
                stripped = line.strip()
                if not stripped or len(stripped) < 20:
                    continue
                if marker_re.search(stripped):
                    collected.append(stripped[:self.RUNTIME_LOG_LINE_MAX_CHARS])
                    if len(collected) >= max_lines:
                        break

            # Step 7: 倒序 (旧→新) 给 LLM
            return list(reversed(collected))
        except Exception:
            return []

    def __init__(self, key_router, concerns_ledger=None,
                  relational_state=None, central_nerve=None):
        self.key_router = key_router
        self.concerns_ledger = concerns_ledger
        self.relational_state = relational_state
        self.nerve = central_nerve

        self._thoughts: List[InnerThought] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_category_ts: dict = {}

        # tick 计数 (for log + dashboard)
        self._tick_count = 0
        self._thought_count = 0
        self._cooldown_skip_count = 0
        self._llm_fail_count = 0

        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] LLM 决定的下次 interval (0 = 用 baseline)
        self._next_tick_interval_s = 0
        # tick origin 统计 (dashboard 看 LLM 真在 self-pacing 还是默认)
        self._tick_origin_stats = {
            'default': 0, 'llm_chosen': 0, 'llm_gated': 0, 'llm_smoothed': 0,
        }

        # 启动时载入近 24h thoughts (重启后 SOUL 仍有上下文)
        self._load_persist()

        # 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] daemon 是心跳 keeper
        # =====================================================================
        # Sir 真反问 "这是独立架构, 还是持续唤醒思考脑带来的能力?" → 后者真.
        # daemon 已 60s tick + 持久化 jsonl, 它本就是 lifetime keeper. 扩 API 即可.
        # 不抽独立 module (准则 8 优雅 + 6.4 公共子集).
        # =====================================================================
        self._process_start_ts = time.time()  # daemon init 近似 nerve cold-start
        self._today_date = time.strftime('%Y-%m-%d')  # 跨日 reset baseline
        self._today_thought_count = 0
        # yesterday recap cache (LLM 生成的昨日 narrative)
        self._yesterday_recap_cached: Optional[Dict[str, Any]] = None
        self._yesterday_recap_last_check_ts = 0.0
        self._yesterday_recap_last_written_ts = 0.0
        # cold_starts.jsonl append (daemon init 真发生)
        try:
            self._append_cold_start_record()
        except Exception:
            pass

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._daemon_loop,
            name='InnerThoughtDaemon',
            daemon=True,
        )
        self._thread.start()
        # 🆕 [Sir 2026-05-26 00:20 真问"显示在想什么"] 启动 cooldown snapshot
        # 让 Sir 一眼看见: 5 类都 free → daemon 60s 后真出 thought
        # (修配套 _load_persist 不再恢复 cooldown ts).
        free_now = self._compute_free_categories()
        cooldown_status = (
            f"all 5 categories FREE (60s 后真出新 thought)"
            if len(free_now) == 5
            else f"{len(free_now)}/5 free: {','.join(free_now)} | "
                 f"cooldown: {','.join(c for c in 'ABCDE' if c not in free_now)}"
        )
        self._bg_log(
            f"💭 [InnerThought] daemon started "
            f"(loaded {len(self._thoughts)} thoughts from last 24h, "
            f"{cooldown_status})"
        )

    def stop(self) -> None:
        self._stop.set()

    def _daemon_loop(self) -> None:
        # 启动延迟让 system 稳定
        self._stop.wait(timeout=self.STARTUP_DELAY_S)
        if self._stop.is_set():
            return
        while not self._stop.is_set():
            interval = self.INTERVAL_ACTIVE_S
            try:
                # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] LLM-self-chosen interval
                # 优先 — _tick 末尾会 set self._next_tick_interval_s; fallback baseline.
                interval = self._compute_adaptive_interval()
                self._tick()
                # tick 后 LLM 可能已选下次 interval, 优先
                if self._next_tick_interval_s > 0:
                    interval = self._next_tick_interval_s
                    self._next_tick_interval_s = 0  # consumed
            except Exception as e:
                self._bg_log(f"⚠️ [InnerThought] tick exception: {e}")
            # 🆕 [Sir 2026-05-27 01:00 β.5.50] yesterday_recap sub-reflector
            # daemon tick 后 check (低频 — 内部 23h cooldown 真守住)
            try:
                self._maybe_write_yesterday_recap()
            except Exception:
                pass
            self._stop.wait(timeout=interval)

    # ----------------------------------------------------------
    # Adaptive frequency + Sir state
    # ----------------------------------------------------------
    def _get_idle_seconds(self) -> float:
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as P
            return float(P.idle_seconds_real or 0.0)
        except Exception:
            return 0.0

    def _read_declared_status(self) -> Tuple[str, float, bool]:
        """🆕 [Sir 2026-05-26 19:01 准则 6 极致版] 读 SirStatusTracker (Sir 真意 sensor).

        vocab 已全 jarvis_sir_status_tracker.py 持久化 (memory_pool/sir_status.json
        + fallback seed), publish SWM 'sir_declared_status'. daemon 只拿,不自己
        reproduce vocab list.

        Returns:
          (status, age_s, is_overdue):
            status: 'unknown' | 'active' | 'sleep' | 'nap' | 'lunch' | 'dinner'
                   | 'out' | 'afk_short' | 'dnd'
            age_s: Sir 声明后多久 (秒)
            is_overdue: 是否已超预期返回时长 (e.g. lunch 声明过 3h)
        """
        try:
            from jarvis_sir_status_tracker import current_status
            cur = current_status()
            return (
                cur.get('status', 'unknown'),
                float(cur.get('age_s', 0)),
                bool(cur.get('is_overdue', False)),
            )
        except Exception:
            return ('unknown', 0.0, False)

    def _classify_sir_state(self) -> str:
        """🆕 [Sir 2026-05-26 19:01 准则 6 极致版] 多 sensor 联合看 state.

        优先级 (准则 6 数据强耦合 + 准则 8 优雅):
          1. idle 物理短路 (< 5min) → active (Sir 在键鼠真在用, 不可能睡/AFK,
             不管声明说什么). 这拦 Q1 真痛: 13:30 wake-up commitment 未 fulfill
             但 Sir 18:55 在键鼠 → 老代码误判 sleep, idle 短路治本.
          2. SirStatusTracker declared_status (Sir 真意 sensor):
             - status sleep/nap + 未 is_overdue → 'sleep'
             - status out/lunch/dinner + idle > 5min → 'afk_deep'
             - status dnd → 'sleep' (不打扰)
             - status afk_short → 'afk_short'
             - is_overdue=True → 不再以声明状态为准 (走底 fallback)
          3. Fallback: 物理 idle 阈值 (老本为底, 依然在)

        删 hardcode (准则 6 严格):
          - 删 commitment_watcher 反推 (忙出错 + 重复 SirStatusTracker)
          - 删 _REST_INTENT_VOCAB hardcode list
          - 删 SLEEP_HOUR_START/END 凌晨窗 (vocab + idle 够了)
        """
        idle_s = self._get_idle_seconds()

        # 🆕 一 物理 atomic 短路 — Sir 在键鼠真在用 → 永远 active.
        # 这 cover Q1 真痛: 13:30 wake commitment 未 fulfill, 但 Sir 18:55 真在用键鼠
        # → 老代码 _has_active_rest_commitment() 误返 True → state=sleep → tick=1800s.
        # idle < 5min 是 Sir 在场物理准据, 比 SirStatusTracker / commitment 可靠得多.
        if idle_s < self.THRESHOLD_AFK_SHORT_S:
            return 'active'

        # 🆕 二 SirStatusTracker (Sir 真意 sensor, 已持久化 vocab).
        status, _age_s, is_overdue = self._read_declared_status()
        if not is_overdue:
            if status in ('sleep', 'nap', 'dnd'):
                return 'sleep'
            if status in ('out', 'lunch', 'dinner'):
                return 'afk_deep'
            if status == 'afk_short':
                return 'afk_short'

        # 🆕 三 底 fallback: 物理 idle 阈值 (面上 SirStatusTracker 未覆盖 的 边 case)
        if idle_s > self.THRESHOLD_AFK_DEEP_S:
            return 'afk_deep'
        if idle_s > self.THRESHOLD_AFK_SHORT_S:
            return 'afk_short'
        return 'active'

    def _compute_adaptive_interval(self) -> int:
        state = self._classify_sir_state()
        return {
            'active': self.INTERVAL_ACTIVE_S,
            'afk_short': self.INTERVAL_AFK_SHORT_S,
            'afk_deep': self.INTERVAL_AFK_DEEP_S,
            'sleep': self.INTERVAL_SLEEP_S,
        }.get(state, self.INTERVAL_ACTIVE_S)

    # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] resolve next interval (LLM hint + gate + smoothing)
    def _resolve_next_interval(self, thought: 'InnerThought',
                                  sir_state: str) -> Tuple[int, str]:
        """Resolve final interval applying physical gate + smoothing.

        Sir 真意 anchor: thought 决定下次思考间隔, 但 Python 物理 gate 保底.

        Logic:
          1. LLM 没给 next_interval_s (=0) → 用 baseline, origin='default'
          2. LLM 给了, 但超物理 gate → 用 baseline, origin='llm_gated'
          3. LLM 给 30 + 最近 ≥3 thought 选 30 + 平均 sal < 0.5 → 强制 60, origin='llm_smoothed'
             (防 token 爆 + 低质量急思考惩罚)
          4. LLM 给且合法 → 用 LLM 选择, origin='llm_chosen'

        Returns: (interval_s, origin)
        """
        baseline = self._compute_adaptive_interval()
        llm_choice = thought.next_interval_s

        # Case 1: LLM 没选 (= 0 = 'default')
        if llm_choice == 0:
            return baseline, 'default'

        # Case 2: physical gate
        allowed = self._PHYSICAL_GATE.get(sir_state,
                                              self._PHYSICAL_GATE['unknown'])
        if llm_choice not in allowed:
            return baseline, 'llm_gated'

        # Case 3: smoothing (LLM 总选 30s + 低质量 → 强制 60s)
        if llm_choice == 30:
            recent = list(self._thoughts)[-self._SMOOTH_LOOKBACK_N:]
            if len(recent) >= self._SMOOTH_LOOKBACK_N:
                high_freq_n = sum(
                    1 for t in recent if t.next_interval_s == 30
                )
                avg_sal = sum(t.salience for t in recent) / len(recent)
                if (high_freq_n >= self._SMOOTH_HIGH_FREQ_K
                    and avg_sal < self._SMOOTH_LOW_SAL_THRESHOLD):
                    return 60, 'llm_smoothed'

        # Case 4: LLM 选择合法 + 不被 smoothing 拦
        return llm_choice, 'llm_chosen'

    # ----------------------------------------------------------
    # Tick (the core)
    # ----------------------------------------------------------
    def _tick(self) -> None:
        self._tick_count += 1
        sir_state = self._classify_sir_state()
        tick_interval = self._compute_adaptive_interval()

        # 🆕 [Sir 2026-05-25 23:18 真痛] cooldown 预选 — 不再 tick 后 cooldown 才发现
        # 老 BUG: tick 调 LLM → LLM 选 cooldown 中 category → skip → 浪费 LLM call.
        # 治本: tick 开头算 free categories, 全 cooldown 则 skip 不调 LLM.
        # 否则把 free list 给 LLM prompt, 让 LLM 只能选 free 中的.
        free_categories = self._compute_free_categories()
        if not free_categories:
            # 所有 5 类都 cooldown — skip 不调 LLM (节省 + 准则 1 高效)
            self._cooldown_skip_count += 1
            # 🆕 [Sir 2026-05-25 23:52 真问"为什么不反思了"] 每 5 tick log 1 次
            # 让 Sir 看见 daemon 真 alive 不是 dead. 算"下次 free" 时间帮诊断.
            if self._cooldown_skip_count % 5 == 1:
                now = time.time()
                next_free_s = min(
                    (self.SAME_CATEGORY_COOLDOWN_S - (now - ts))
                    for ts in self._last_category_ts.values()
                    if ts > 0
                )
                self._bg_log(
                    f"💭 [InnerThought] all 5 categories in cooldown "
                    f"(skip count {self._cooldown_skip_count}), "
                    f"next free in {int(next_free_s / 60)}min — daemon alive, "
                    f"awaiting free slot."
                )
            return

        # collect evidence
        evidence = self._collect_evidence(
            sir_state=sir_state,
            within_seconds=tick_interval * 2,
        )

        # LLM call (Flash-Lite, caller='inner_thought' → P2 LOW priority)
        prompt_sys, prompt_user = self._build_prompt(
            sir_state, evidence, free_categories=free_categories
        )
        raw = self._call_llm(prompt_sys, prompt_user)
        if not raw:
            self._llm_fail_count += 1
            return

        thought = self._parse_thought(raw, sir_state, tick_interval)
        if thought is None:
            return

        # cooldown 二道防御 (LLM 没听 prompt 选了 cooldown 中 → 再 skip)
        last_ts = self._last_category_ts.get(thought.category, 0.0)
        if time.time() - last_ts < self.SAME_CATEGORY_COOLDOWN_S:
            self._cooldown_skip_count += 1
            self._bg_log(
                f"💭 [InnerThought] LLM ignored free_categories prompt, "
                f"chose cooldown category {thought.category} "
                f"({int(time.time() - last_ts)}s < {self.SAME_CATEGORY_COOLDOWN_S}s), "
                f"skip"
            )
            return

        # store
        with self._lock:
            self._thoughts.append(thought)
            self._last_category_ts[thought.category] = thought.ts
            self._thought_count += 1
            # 🆕 [Sir 2026-05-27 01:00 β.5.50] today_thought_count 跨日 reset
            try:
                today = time.strftime('%Y-%m-%d')
                if today != self._today_date:
                    self._today_date = today
                    self._today_thought_count = 0
                self._today_thought_count += 1
            except Exception:
                pass

        # actionable execute (before persist for actionable_result)
        ok, result = self._execute_actionable(thought)
        thought.actionable_done = ok
        thought.actionable_result = result

        # 🆕 [Sir 2026-05-25 23:18 真痛-3] actionable fail → publish SWM
        # 让主脑下轮 prompt 看到自己上轮失败, 改进选 concern_id.
        if not ok and thought.actionable and \
                thought.actionable.lower() != 'none':
            self._publish_actionable_failure(thought, result)

        # 🆕 [Sir 2026-05-25 23:18 真痛-4] B 类 self-correction 闭环:
        # 主脑自己识别 "I keep repeating X" 类 → publish stop_repeating_topic
        # 让 SOUL inject 下轮主脑 prompt 真看到 → 真不重复.
        self._maybe_publish_self_correction(thought)

        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] resolve LLM-chosen next interval
        # 物理 gate + smoothing 后, store 到 self._next_tick_interval_s,
        # _daemon_loop 下次 wait 时优先用.
        resolved_interval, tick_origin = self._resolve_next_interval(
            thought, sir_state
        )
        thought.tick_origin = tick_origin
        self._next_tick_interval_s = resolved_interval
        self._tick_origin_stats[tick_origin] = \
            self._tick_origin_stats.get(tick_origin, 0) + 1

        # persist + publish SWM
        self._persist_thought(thought)

        # 🆕 [Sir 2026-05-26 23:24 真痛 BUG-5 治本 / 准则 8 优雅高效]
        # =====================================================================
        # Sir 截图 (22:41:37): "[E/sal=0.40] Sir is troubleshooting an API tier
        # configuration issue; I shall remain ready to assist" — 平庸 surface
        # observation, 没价值, 浪费 SWM publish + dashboard 噪音.
        # Prompt 第 1166 行已教 "If nothing meaningful comes, output (quiet)
        # SALIENCE=0.0", 但 LLM 偶尔不 follow → daemon 兜底:
        #   sal < MEDIOCRE_THRESHOLD + actionable='none' + A/E (passive 类) →
        #   skip publish_swm (不污染 SWM/dashboard), log compact 标 [skip:mediocre].
        # 不动 sal 阈值 (Sir 拒 E), 仅省 SWM publish + 简化 log. thought 仍 persist
        # (preserve for thought chain v2 / time awareness).
        # =====================================================================
        # 🆕 [Sir 2026-05-26 23:53 真测 BUG-γ] 扩 cover D class.
        # Sir 23:52:38 实测 '[D/sal=0.20] system key routing remains critical;
        # I should continue to monitor...' — D-class PROACTIVE-SEED 但没 action,
        # sal=0.2 极低, 与 A/E 同类无价值 surface observation, skip publish.
        is_mediocre = (
            thought.salience < self._MEDIOCRE_SAL_THRESHOLD
            and (not thought.actionable or thought.actionable.lower() == 'none')
            and thought.category in ('A', 'D', 'E')
        )
        if not is_mediocre:
            self._publish_swm(thought)

        # 🆕 [Sir 2026-05-27 00:11 M3 VisualPulse] 字幕区 subtle 💭 闪 (Sir 真看见思考)
        # =====================================================================
        # Sir 真意: "可视化看到思考变化, 不是离散像看故事".
        # mediocre 跳过, 主对话 5s 内跳过 (vocab 节流). 阈值 + cooldown 全 vocab 可改.
        # =====================================================================
        if not is_mediocre:
            try:
                self._emit_thought_pulse(thought)
            except Exception:
                pass

        # log (Sir 真看见 daemon 在 work) — mediocre 用 compact log
        action_str = ''
        if thought.actionable and thought.actionable.lower() != 'none':
            # 🆕 [Sir 2026-05-27 21:11 真测 P2_b] word-boundary truncate
            # 避免 Sir 看到 "Always match Sir's conf" 这种字中间切断
            _act = _truncate_at_word_boundary(thought.actionable, 40)
            _res = _truncate_at_word_boundary(result, 80)
            action_str = f" | actionable={_act} → {_res}"
        # 🆕 [Sir 2026-05-26 00:25 真痛"地基"] 显示 evidence_link (LLM cite 啥)
        # actionable=none 但 evidence_link 非空 → 也展示 (rejected case Sir 真看)
        ev_str = ''
        if thought.evidence_link and thought.evidence_link.lower() != 'none':
            _cite = _truncate_at_word_boundary(thought.evidence_link, 40)
            ev_str = f" | cite=\"{_cite}\""
        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] 显示下次 tick 由谁决定 +
        # interval 真值 (Sir 看 daemon 真在 self-pacing 还是默认)
        meta_str = f" | next={resolved_interval}s({tick_origin})"
        # 🆕 [Sir 23:24 BUG-5] mediocre log compact (前 50 ch + [skip:mediocre] 标)
        if is_mediocre:
            self._bg_log(
                f"💭 [InnerThought/skip:mediocre] [{thought.category}/sal={thought.salience:.2f}"
                f"] {thought.thought[:60]}…{meta_str}"
            )
        else:
            # 🆕 [Sir 2026-05-27 00:43 真痛] log truncate 100→300 让 Sir 看完整 thought
            # 🆕 [Sir 2026-05-27 21:11 真测 P2_b] word-boundary truncate 避字中间断
            _tt = _truncate_at_word_boundary(thought.thought, 300)
            self._bg_log(
                f"💭 [InnerThought] [{thought.category}/sal={thought.salience:.2f}"
                f"/state={sir_state}/tick={tick_interval}s] {_tt}"
                f"{action_str}{ev_str}{meta_str}"
            )

    def _compute_free_categories(self) -> List[str]:
        """🆕 [Sir 2026-05-25 23:18] 算当前可用 categories (不在 cooldown).

        准则 1 高效 + 8 优雅: 让 LLM 不浪费 token 选 cooldown 类.
        """
        now = time.time()
        free = []
        for cat in 'ABCDE':
            last_ts = self._last_category_ts.get(cat, 0.0)
            if now - last_ts >= self.SAME_CATEGORY_COOLDOWN_S:
                free.append(cat)
        return free

    def _publish_actionable_failure(self, thought, result: str) -> None:
        """🆕 [Sir 2026-05-25 23:18] actionable 失败 → SWM event.

        让主脑下轮 prompt 看到自己上轮选错 concern_id / hallucinate id,
        改进下次选择 (准则 6 evidence + 8 优雅).
        """
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='inner_thought_actionable_failed',
                description=(
                    f"My last {thought.category}-thought tried "
                    f"`{thought.actionable[:60]}` but failed: {result[:80]}. "
                    f"Don't pick wrong concern_id again."
                ),
                source='inner_thought_daemon',
                salience=0.6,
                metadata={
                    'thought_id': thought.id,
                    'category': thought.category,
                    'actionable': thought.actionable[:120],
                    'failure_reason': result[:120],
                },
                ttl=86400.0,
            )
        except Exception:
            pass

    # 🆕 [Sir 2026-05-25 23:38 真测优化] B 类 self-reflection 闭环阈值
    # 老 fix#5 用 keyword hardcode list 限制 cover — Sir 真测 B 类 "caught myself
    # being slightly too reactive" 没 match 任何 keyword → 没触发 publish. 准则 6
    # 反对硬编码 list. 治本: B 类高 salience 全 publish, 让主脑下轮自己决定.
    SELF_REFLECTION_SALIENCE_THRESHOLD = 0.5

    def _maybe_publish_self_correction(self, thought) -> None:
        """🆕 [Sir 2026-05-25 23:38] B 类自反思闭环 — 优雅版.

        删 keyword hardcode (准则 6 反硬编码). 任何 B 类 + sal ≥ 0.5 → publish
        self_reflection_noted SWM. 主脑下轮 SOUL inject 真看到, 自己决定是否
        纠正 — 不靠 daemon 预判 keyword.

        salience 透传 (主脑能区分 sal=0.5 轻反思 vs sal=0.9 强烈反思).
        """
        if thought.category != 'B':
            return
        if thought.salience < self.SELF_REFLECTION_SALIENCE_THRESHOLD:
            return
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='self_reflection_noted',
                description=(
                    f"I just self-reflected: {thought.thought[:140]}. "
                    f"Next reply: consider whether to adjust."
                ),
                source='inner_thought_daemon',
                # salience 透传: 让 SOUL inject 按强度排序
                salience=max(0.7, thought.salience),
                metadata={
                    'thought_id': thought.id,
                    'category': 'B',
                    'original_salience': thought.salience,
                    'thought_excerpt': thought.thought[:200],
                },
                ttl=3600.0 * 6,  # 6h
            )
            self._bg_log(
                f"🪞 [InnerThought/self-reflection] B-thought "
                f"(sal={thought.salience:.2f}) → publish self_reflection_noted "
                f"SWM (主脑下轮 SOUL inject 真看到)"
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Evidence collection
    # ----------------------------------------------------------
    def _collect_evidence(self, sir_state: str, within_seconds: int) -> dict:
        ev: dict = {
            'sir_state': sir_state,
            'idle_seconds': int(self._get_idle_seconds()),
            'hour': time.localtime().tm_hour,
            'swm_events': [],
            'stm': [],
            'concerns': [],
            # 🆕 [Sir 2026-05-27 00:11 真意 M1 ThoughtChain] 上 3 thought 给 LLM 看
            # 让思考连续 (LLM 自决是否延续上次 thread).
            'recent_thoughts': [],
        }
        # 拿上 3 个 thought (含 thread_id + continuity tag)
        try:
            with self._lock:
                recent_3 = sorted(self._thoughts, key=lambda t: -t.ts)[:3]
            # 🆕 [Sir 2026-05-27 00:43 真痛 重复思考] 传 actionable_done + actionable_result 让 LLM 看上次失败
            # Sir image 1: 同主题 2 thought 60s 连 fire, 都 propose 同 tool 都失败.
            # 根因: LLM 只看到上次 actionable 文本不知道为啥 fail. 补上 result 后 LLM
            # 自然看到 "gated:call_tool_requires_sal>=0.9" → 不重提同 tool.
            ev['recent_thoughts'] = [
                {
                    'id': t.id,
                    'thread_id': getattr(t, 'thread_id', '') or t.id,
                    'continuity': getattr(t, 'continuity', 'new_topic'),
                    'category': t.category,
                    'thought': (t.thought or '')[:200],
                    'salience': t.salience,
                    'actionable': (t.actionable or 'none')[:60],
                    'actionable_done': getattr(t, 'actionable_done', None),
                    'actionable_result': (
                        getattr(t, 'actionable_result', '') or ''
                    )[:120],
                    'outcome': getattr(t, 'outcome', 'pending'),
                    'age_s': int(time.time() - t.ts),
                }
                for t in recent_3
            ]
        except Exception:
            pass
        # SWM events
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                top = bus.top_n(n=20) or []
                events = []
                for e in top:
                    age = e.get('_age_s', 9999)
                    if age > within_seconds:
                        continue
                    events.append({
                        'type': e.get('type', '?'),
                        'desc': (e.get('description') or '')[:120],
                        'age_s': int(age),
                    })
                ev['swm_events'] = events[:8]
        except Exception:
            pass
        # 🆕 [Sir 2026-05-26 18:54 真意 anchor "让反思看真证据"] FIX A:
        # =====================================================================
        # 老 BUG: STM 只 2 turn, user 120 char, jarvis 200 char — 一句长 reply 看不全.
        # Sir 真意: "终端省略很多输出, 反思看不到完整对话". 5 turn × 长字数能覆盖
        # Sir 真痛 anchor ("xx不舒服了"/"xx打扰了") + Jarvis 完整 reply (含啰嗦/犯错).
        # 治本 (准则 6 evidence-driven + 准则 8 优雅): 2→5 turn, 字数翻倍.
        # token 加 ~$0.3/月 (5 turn × 650 char = 3.3KB, 老 2 turn × 320 = 640).
        # =====================================================================
        try:
            stm = []
            if self.nerve and getattr(self.nerve, 'short_term_memory', None):
                for t in list(self.nerve.short_term_memory)[-5:]:
                    stm.append({
                        'user': (t.get('user') or '')[:250],
                        'jarvis': (t.get('jarvis') or '')[:400],
                        'when': t.get('time') or t.get('when_iso', ''),
                    })
            ev['stm'] = stm
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 18:54 真意 anchor FIX B] recent_jarvis_actions —
        # =====================================================================
        # Sir 真意: "反思只看 thought 文本太抽象, 看不见 Jarvis 真做了什么 (NUDGE
        # fire/skipped/published_swm/rejected_actionable)". 老 evidence['swm_events']
        # 含所有 event 类型, 太杂. 这里 filter 出 jarvis 真行为 (action signals) 单独
        # 列, 让反思能看 "I just fired return_greeting 6s after commitment_check, 
        # Sir might find it pushy". 准则 6 数据强耦合 (SWM 已 publish, 只 filter).
        # 工程: 从 swm_events 中 filter etype prefix in ACTION_EVENT_PREFIXES, 留
        # 10 个 latest, 给反思看真发生的 jarvis 行为时间线.
        # =====================================================================
        try:
            from jarvis_utils import get_event_bus as _geb_a
            bus_a = _geb_a()
            if bus_a is not None:
                top_a = bus_a.top_n(n=40) or []
                actions = []
                for e in top_a:
                    age = e.get('_age_s', 9999)
                    if age > within_seconds:
                        continue
                    etype = e.get('type', '')
                    # 真 jarvis 行为 etype prefix (准则 6 vocab driven, 不写死)
                    if any(etype.startswith(p) for p in self._ACTION_EVENT_PREFIXES):
                        actions.append({
                            'etype': etype,
                            'desc': (e.get('description') or '')[:140],
                            'source': e.get('source', ''),
                            'age_s': int(age),
                        })
                ev['recent_jarvis_actions'] = actions[:10]
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 18:54 真意 anchor FIX C] runtime_log tail —
        # =====================================================================
        # Sir 真意 anchor: "终端省略了很多输出我记得". 反思如果只看 SWM event +
        # STM 短对话, 真错过 bg_log 写到 docs/runtime_logs/*.log 的完整信息 (sentinel
        # blocked / state transition / failed promise / TTS skipped, 等等). 让 daemon
        # 在 reflect 时 read latest.txt → tail N 行 → regex filter 含 marker (Sir/Jarvis/
        # State/NUDGE/published/rejected/...) → inject ~2KB. 准则 6 evidence-driven 完整版
        # 准则 8 优雅治本 (不解析整 log MB 级, tail + filter).
        # =====================================================================
        try:
            ev['runtime_log_tail'] = self._collect_runtime_log_tail(max_lines=12)
        except Exception:
            ev['runtime_log_tail'] = []

        # 🆕 [Sir 2026-05-26 19:48 Phase 1B] anticipated_ltm_context — Anticipator preload
        # =====================================================================
        # Sir 真问 "目前思考和真主动性距离" → Anticipator 已专职 30s tick + HabitClock
        # + preload LTM (jarvis_memory_core.py:851). thought 复用 preload (不重复 query
        # 浪费 LLM token + 不破 Anticipator 节奏). 准则 8 优雅.
        # =====================================================================
        try:
            if self.nerve and hasattr(self.nerve, 'anticipator'):
                anticipator = self.nerve.anticipator
                if anticipator is not None and hasattr(anticipator, 'get_preloaded_context'):
                    ctx = anticipator.get_preloaded_context() or ''
                    if ctx.strip():
                        ev['anticipated_ltm_context'] = ctx[:1500]
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 19:48 Phase 1C] daemon_health — read SWM 'daemon_health_warning'
        # =====================================================================
        # Sir 真意: thought 该看自己健康 (token 用量, sentinel fail rate, calibration 阈值).
        # DaemonHealthMonitor 已 6h tick + publish SWM (jarvis_daemon_health_monitor.py).
        # thought 只 read SWM 'daemon_health_warning' event, 不重复 monitor 逻辑.
        # =====================================================================
        try:
            from jarvis_utils import get_event_bus as _geb_dh
            bus_dh = _geb_dh()
            if bus_dh is not None:
                top_dh = bus_dh.top_n(n=30) or []
                health_warns = []
                for e in top_dh:
                    if e.get('type') != 'daemon_health_warning':
                        continue
                    age_s = e.get('_age_s', 999999)
                    if age_s > 86400:  # 1d cap
                        continue
                    meta = e.get('metadata') or {}
                    health_warns.append({
                        'issue': (e.get('description') or '')[:140],
                        'severity': meta.get('severity', 'warn'),
                        'age_h': int(age_s / 3600),
                    })
                ev['daemon_health'] = health_warns[:3]
        except Exception:
            pass

        # 🆕 [Sir 2026-05-27 00:11 真意 M2] TimeAwareness — 注入 hour pattern.
        # Sir 原话: "给予贾维斯真正对时间的理解, 这有助于他理解我的行为模式".
        # 数据流: get_pattern_at_now (vocab) + detect_deviation_today (vs 今 STM).
        # vocab JSON 持久化 + reflector hourly mine STM pattern (准则 6).
        try:
            from jarvis_time_awareness import (get_pattern_at_now,
                                                  detect_deviation_today,
                                                  get_routines_active_now,
                                                  maybe_run_reflector)
            ev['time_pattern'] = get_pattern_at_now()
            ev['time_active_routines'] = get_routines_active_now()
            stm_for_dev = ev.get('stm', [])
            # detect_deviation_today 需 stm 含 ts (numeric), 用 raw STM 不一定有
            try:
                ev['time_deviation_today'] = detect_deviation_today(stm_for_dev)
            except Exception:
                ev['time_deviation_today'] = None
            # 周期 reflect (hourly), 在 daemon tick 中顺便触发 — 不阻塞 (内部 30s 缓存)
            try:
                full_stm = []
                if self.nerve and getattr(self.nerve, 'short_term_memory', None):
                    full_stm = list(self.nerve.short_term_memory)[-100:]
                maybe_run_reflector(full_stm)
            except Exception:
                pass
        except Exception:
            pass

        # 🆕 [Sir 2026-05-27 00:49 Option B 人设统一] 4 段公共子集 — 让思考脑跟主脑同人设
        # =====================================================================
        # Sir 真意 (Option B): "主脑装配的 prompt 也该给思考脑保证人设信息统一", "现在
        # 思考脑只看上下文会判断失误". Sir 优先级: 连续 > 时间 > 人设. 不让 LLM 变蠢 =
        # 装最小必要 + 持久化 vocab 让 Sir 一关一段不需改 .py (准则 6).
        # 5 块: now_time / hour_pattern (已有上) / sir_declared_status / sir_profile_mini
        #       / active_directives. 全 vocab gate (memory_pool/inner_thought_identity_
        #       block_vocab.json).
        # =====================================================================
        try:
            _id_vocab = self._load_identity_block_vocab()
        except Exception:
            _id_vocab = {}
        _enabled = (_id_vocab.get('blocks_enabled') or {})
        _limits = (_id_vocab.get('limits') or {})
        # (1) Sir declared status raw — Sir 真声明 (sleep/lunch/dinner/out/dnd) +
        #     age (Sir 何时说的). 老 evidence 只聚合后 sir_state, 看不到细节.
        if _enabled.get('sir_declared_status', True):
            try:
                status, age_s, is_overdue = self._read_declared_status()
                ev['sir_declared_status'] = {
                    'status': status,
                    'age_s': int(age_s),
                    'is_overdue': bool(is_overdue),
                }
            except Exception:
                pass
        # (2) Sir profile mini — ProfileCard.to_prompt_block(400) 截字精简
        if _enabled.get('sir_profile_mini', True):
            try:
                _max = int(_limits.get('profile_max_chars', 400))
                if self.nerve and hasattr(self.nerve, 'profile_card'):
                    pc = self.nerve.profile_card
                    if pc and hasattr(pc, 'to_prompt_block'):
                        ev['sir_profile_mini'] = pc.to_prompt_block(
                            max_chars=_max,
                        )
            except Exception:
                pass
        # (3) Active directives — top N by priority, 只取 id + purpose_short
        if _enabled.get('active_directives', True):
            try:
                from jarvis_directives import (get_default_registry as
                                                   _gdr_drv)
                reg = _gdr_drv()
                if reg and hasattr(reg, 'directives'):
                    top_n = int(_limits.get('directives_top_n', 5))
                    pmax = int(_limits.get('directive_purpose_max_chars', 80))
                    active = [
                        d for d in reg.directives.values()
                        if getattr(d, 'state', '') == 'active'
                        and getattr(d, 'purpose_short', '')
                    ]
                    active.sort(
                        key=lambda d: -int(getattr(d, 'priority', 0))
                    )
                    ev['active_directives'] = [
                        {
                            'id': d.id,
                            'purpose': (d.purpose_short or '')[:pmax],
                            'priority': int(getattr(d, 'priority', 0)),
                        }
                        for d in active[:top_n]
                    ]
            except Exception:
                pass

        # 🆕 [Sir 2026-05-25 23:18 真痛-2] concerns 给全 active id list 防 LLM hallucinate
        # 老 BUG: 只 top 3 → LLM 想改第 4+ concern (e.g. sir_interview_prep_balance
        # severity 极低), 没在 prompt 列 → LLM hallucinate id (e.g. jarvis_internal_health).
        # 治本: concerns top 5 by severity (含 detail) + all_active_ids 给 LLM 选.
        try:
            if self.concerns_ledger and hasattr(self.concerns_ledger, 'list_active'):
                active = self.concerns_ledger.list_active() or []
                active_sorted = sorted(active, key=lambda c: -c.severity)
                ev['concerns'] = [
                    {
                        'id': c.id,
                        'what': (c.what_i_watch or '')[:80],
                        'severity': round(c.severity, 2),
                        # 🆕 [Sir 2026-05-26 13:32 BUG 3] notes 容量信号 — 让 LLM
                        # 看见 concern 已满, 不再 propose adjust_concern_notes 浪费 tick
                        'notes_chars': len((c.notes_for_self or '').strip()),
                    }
                    for c in active_sorted[:5]
                ]
                # 全 active id list (let LLM 见全, 不光 top 5)
                ev['all_active_concern_ids'] = [c.id for c in active_sorted]
        except Exception:
            pass
        # 🆕 [Sir 2026-05-26 13:32 真痛 BUG 治本] BUG 2 propose dedup:
        # ===================================================================
        # 源 BUG: 13:33→13:31 LLM 5+ 次 propose 几乎同样 "Do not use formal apologies"
        # 类 protocol (B 类 self-reflect). 真因: prompt 没 inject 已 active + pending
        # review 的 protocols, LLM 每次 tick 全新发现 "I'm too formal" → propose.
        # 同 BUG 影响 inside_joke ("地基要打牢" 重复 3 次).
        # 治本: inject 已 active + pending review entries, prompt 教 LLM "若已覆盖
        # 同概念, 不再 propose" + dedup hint. 准则 6 数据驱动 (vocab persisted).
        # ===================================================================
        try:
            rs = self.relational_state
            if rs is not None:
                if hasattr(rs, 'list_protocols'):
                    active_protos = rs.list_protocols(include_archived=False) or []
                    ev['active_protocols'] = [
                        (p.rule or '')[:120] for p in active_protos[:5]
                    ]
                if hasattr(rs, 'list_protocols_review'):
                    review_protos = rs.list_protocols_review() or []
                    ev['pending_review_protocols'] = [
                        (p.rule or '')[:120] for p in review_protos[:5]
                    ]
                if hasattr(rs, 'list_inside_jokes'):
                    active_jokes = rs.list_inside_jokes(include_archived=False) or []
                    ev['active_inside_jokes'] = [
                        (j.phrase or '')[:80] for j in active_jokes[:5]
                    ]
                if hasattr(rs, 'list_inside_jokes_review'):
                    review_jokes = rs.list_inside_jokes_review() or []
                    ev['pending_review_jokes'] = [
                        (j.phrase or '')[:80] for j in review_jokes[:5]
                    ]
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 20:14 真意 anchor 3] Skepticism Learning Loop evidence
        # ===================================================================
        # Sir 真意 anchor: "我提质疑时它会降低使用权重, 多次质疑甚至考虑删除".
        # SirSkepticismDetector 在 chat_bypass.stream_chat 入口 publish SWM
        # event ('sir_skepticism' / 'item_skepticism_decay' / 'item_auto_archived'
        # / 'item_reactivated' 等). thought 反思看这些 evidence 自决是否:
        #   - B 类 propose_protocol "Don't reuse joke X" 强化趋势
        #   - C 类 adjust_concern_notes 给 main brain 警告"Sir 不喜欢提 X"
        #   - 让主脑下轮看 SOUL inject "我注意到 Sir 三次质疑 X" → 自然不提
        # 准则 6 数据强耦合: 全 publish SWM, evidence-driven, 不 hardcode behavior.
        # 准则 7 Sir 元否决: Sir reactivation → publish 'item_reactivated' 让反思看到.
        # ===================================================================
        try:
            from jarvis_utils import get_event_bus as _geb_sk
            bus_sk = _geb_sk()
            if bus_sk is not None:
                _SKEPTICISM_ETYPES = {
                    'sir_skepticism', 'sir_reactivation', 'sir_confusion',
                    'item_skepticism_decay', 'item_skepticism_warning',
                    'item_auto_archived', 'item_auto_dismissed', 'item_reactivated',
                }
                top_sk = bus_sk.top_n(n=40) or []
                sk_events = []
                for e in top_sk:
                    etype = e.get('type', '')
                    if etype not in _SKEPTICISM_ETYPES:
                        continue
                    age_s = e.get('_age_s', 999999)
                    if age_s > 86400:  # 24h cap
                        continue
                    meta = e.get('metadata') or {}
                    sk_events.append({
                        'etype': etype,
                        'desc': (e.get('description') or '')[:140],
                        'age_s': int(age_s),
                        'matched_phrase': str(meta.get('matched_phrase', ''))[:60],
                        'target_kind': str(meta.get('target_kind', ''))[:30],
                        'target_id': str(meta.get('target_id', ''))[:60],
                        'count': meta.get('count') or meta.get('new_count'),
                    })
                ev['recent_skepticism_events'] = sk_events[:5]
        except Exception:
            pass
        return ev

    # ----------------------------------------------------------
    # Prompt
    # ----------------------------------------------------------
    def _build_prompt(self, sir_state: str, evidence: dict,
                        free_categories: Optional[List[str]] = None) -> Tuple[str, str]:
        free_str = (
            ''.join(free_categories) if free_categories else 'ABCDE'
        )
        # 🆕 [Sir 2026-05-26 20:21 真痛追根 BUG-B 治本 / 准则 8 优雅]
        # =====================================================================
        # Sir 真测 (20:21:03): InnerThought 输出 "I noticed I've been fixating on..."
        # 这种 casual self-talk 不像 butler. 真根因: 旧 system prompt 只一句
        # "You are J.A.R.V.I.S." 没引主脑 JARVIS_CORE_PERSONA (2700ch identity +
        # INTEGRITY 准则), 思考层人设和主脑分裂 — 主脑 butler / 思考层 casual.
        # 修法 (准则 8 优雅): lazy import PERSONA → 拼到 system 开头 → 思考也守
        # butler 风格 + INTEGRITY claim honesty. THOUGHT 调性改 "first-person but
        # JARVIS-voice (composed, dry, integrity-bound)" 保 inner monologue 私密感
        # 同时不丢人设. PERSONA 失败 fallback 空字符串 (不阻塞 thought 生成).
        # =====================================================================
        try:
            from jarvis_central_nerve import JARVIS_CORE_PERSONA as _JCP
        except Exception:
            _JCP = ""
        _persona_block = (f"{_JCP}\n\n" if _JCP else "")
        system = (
            f"{_persona_block}"
            "=== INNER MONOLOGUE MODE (private mental note, NOT addressed to Sir) ===\n"
            "You are now in a quiet moment, generating ONE brief inner thought for "
            "yourself. This is private self-reflection — Sir will NOT see this directly. "
            "But you remain J.A.R.V.I.S. even in self-talk: composed, dry, restrained, "
            "integrity-bound. No casual slang ('like...', 'kinda', 'gonna'), no "
            "stream-of-consciousness rambling. Think the way a quiet butler would think.\n\n"
            "Output FORMAT (strict, all 5 tags required):\n"
            f"<CATEGORY>{'|'.join(free_categories) if free_categories else 'A|B|C|D|E'}"
            "</CATEGORY>  ← ONLY these are NOT in cooldown right now\n"
            "<THOUGHT>1-2 sentences, first-person but JARVIS-voice (composed, dry, "
            "factually grounded). Examples: 'I appear to have over-attended to...', "
            "'My last reply leaned too formal — drop the apologies.', 'Sir's hour is "
            "late; I should yield further attempts at chatter.' NOT 'I'm kinda noticing...'"
            "</THOUGHT>\n"
            "<SALIENCE>0.0-1.0 (0.7+ = worth bringing up later; 0.3- = passing)</SALIENCE>\n"
            "<ACTIONABLE>one of: none | "
            "update_concern_severity:<concern_id>:<+/-delta> | "
            "publish_swm:<etype>:<short_desc> | "
            "suggest_inside_joke:<phrase> | "
            "propose_protocol:<one-sentence imperative rule> | "
            "adjust_concern_notes:<concern_id>:<note text> | "
            "fire_nudge:<kind>:<1-2 sentence draft> | "
            "propose_watch_task:<trigger_kind:value>:<long-term goal desc> | "
            "call_tool:<tool_name>:<json_args> | "
            "surface_to_sir:<channel>:<one-sentence summary></ACTIONABLE>\n"
            "<EVIDENCE_LINK>If ACTIONABLE != none: cite 1-5 EXACT words from your "
            "own THOUGHT above that justify this actionable (Python will verify the "
            "cite appears in THOUGHT). Else: 'none'</EVIDENCE_LINK>\n"
            "<NEXT_INTERVAL>30 | 60 | 180 | 600 | 1800 | default</NEXT_INTERVAL>  "
            "← how soon should I think again? Python physically gates per Sir state.\n"
            "<CONTINUITY>same_thread:<thread_id_short> | new_topic</CONTINUITY>  "
            "← 🆕 [Sir 2026-05-27 M1] is this thought延续上 3 thought 中某一条? "
            "若延续 → 'same_thread:<thread_id_from_above>' (extends chain); "
            "若新主题 → 'new_topic' (start new chain). 🆕 [Sir 00:43] 若上次 "
            "actionable failed (见 'Result: ❌ FAILED' below), 你 SHOULD 延续 "
            "same_thread 但 propose DIFFERENT approach OR fall back ACTIONABLE=none "
            "— DO NOT repeat the exact same actionable.\n\n"
            "5 categories (pick the ONE most fitting):\n"
            "  [A] OBSERVATION — Sir's current state (screen/app/mood/activity).\n"
            "  [B] SELF-REFLECT — your own recent reply (tone / mistake / pattern). "
            "If sal≥0.75 AND you can extract a CONCRETE behavior rule "
            "('Do not X' / 'Always Y when Z'), use propose_protocol to make it "
            "STRICT for next turn.\n"
            "  [C] CONCERN-EVOLUTION — should a concern severity change? "
            "(use update_concern_severity with REAL concern_id from evidence below) "
            "OR should I update HOW I respond to this concern? (use "
            "adjust_concern_notes with REAL concern_id + short guidance text — "
            "main brain reads this on next turn for self-restraint, e.g. "
            "'DO NOT volunteer this topic unless Sir asks').\n"
            "  [D] PROACTIVE-SEED — what to silently do next? "
            "(use publish_swm so future-you sees it)\n"
            "  [E] RELATIONSHIP — inside joke / callback-worthy phrase "
            "(use suggest_inside_joke if real callback worthy)\n\n"
            "Rules (准则 5 言出必行 + 6 evidence + 8 优雅):\n"
            "  - DO NOT invent facts/numbers you can't see in evidence.\n"
            "  - Use REAL concern IDs from evidence — never invent IDs.\n"
            "  - update_concern_severity delta capped ±0.2 per thought.\n"
            "  - publish_swm etype: short snake_case (e.g. 'sir_seems_tired').\n"
            "  - propose_protocol: IMPERATIVE form (Do/Don't/Always/Never), "
            "OBSERVABLE (verifiable in my next reply). 🆕 [Sir 23:17] cross-class OK "
            "(B is idiomatic but A/C/D/E reflection can also propose if grounded). "
            "Python only gates sal<0.75 (strict rule needs high confidence).\n"
            "  - adjust_concern_notes: short guidance (10-120 char) for main brain "
            "to read on next turn. 🆕 [Sir 23:17] cross-class OK (C is idiomatic "
            "but B-self-reflect can also adjust note if it really notices a pattern). "
            "Python only gates sal<0.7 + cid must exist + cite must overlap concern.\n"
            "  - NEXT_INTERVAL: pick 30 if URGENT thought (sal≥0.85 + actionable + "
            "Sir active), 60 for normal active thinking, 180/600/1800 if Sir AFK/sleep, "
            "or 'default' to use baseline. Python physically gates: e.g. you can't pick 30 "
            "when Sir is in deep AFK (10min idle) — that'd be wasted token; nor 1800 when "
            "Sir is right here. Smoothing: if recent thoughts all pick 30 + sal stays low, "
            "Python forces 60 (don't burn tokens on low-quality urgency).\n"
            "  - If nothing meaningful comes, output <THOUGHT>(quiet)</THOUGHT> "
            "<SALIENCE>0.0</SALIENCE> <ACTIONABLE>none</ACTIONABLE> "
            "<EVIDENCE_LINK>none</EVIDENCE_LINK> "
            "<NEXT_INTERVAL>default</NEXT_INTERVAL> — and that's perfectly fine.\n"
            "  - Keep first-person, brief, like genuine self-talk.\n\n"
            "🆕 [Sir 2026-05-26 真痛 \"地基要打牢\"] EVIDENCE LINKING RULE (HARD):\n"
            "  ACTIONABLE must be traceable to THOUGHT content. The EVIDENCE_LINK\n"
            "  word(s) MUST appear verbatim in your THOUGHT. Examples:\n"
            "  ❌ BAD: <THOUGHT>Sir is toggling general and coding rapidly</THOUGHT>\n"
            "         <ACTIONABLE>update_concern_severity:sir_interview_pr:+0.1</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>toggling</EVIDENCE_LINK>\n"
            "         → wrong concern: 'toggling general/coding' does NOT trace to interview prep.\n"
            "  ✅ GOOD: <THOUGHT>Sir is toggling general and coding rapidly without rest</THOUGHT>\n"
            "         <ACTIONABLE>update_concern_severity:sir_pomodoro_compliance:+0.1</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>without rest</EVIDENCE_LINK>\n"
            "         → 'without rest' traces to pomodoro work-rest concern, AND 'without rest'\n"
            "         actually appears in THOUGHT.\n"
            "  ✅ ALSO OK: <THOUGHT>Quiet moment, nothing notable</THOUGHT>\n"
            "         <ACTIONABLE>none</ACTIONABLE> <EVIDENCE_LINK>none</EVIDENCE_LINK>\n"
            "         → ACTIONABLE=none ALWAYS preferred over forced un-grounded action.\n\n"
            "🆕 [Sir 2026-05-26 SOUL Phase A] B-class propose_protocol example "
            "(LONG-TERM POLICY — 永久行为规则):\n"
            "  ✅ GOOD: <CATEGORY>B</CATEGORY>\n"
            "         <THOUGHT>I opened that last reply with 'My apologies, Sir' — too\n"
            "                  formal, sounded stiff. Should drop the formal apologies.</THOUGHT>\n"
            "         <SALIENCE>0.8</SALIENCE>\n"
            "         <ACTIONABLE>propose_protocol:Do not open replies with formal apologies like 'My apologies, Sir'</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>formal apologies</EVIDENCE_LINK>\n"
            "         → B-class + sal≥0.75 + concrete IMPERATIVE rule + cite\n"
            "         really in THOUGHT → AutoArbiter will likely activate →\n"
            "         next turn Layer 2 STRICT RULES will enforce.\n"
            "  ❌ BAD: <CATEGORY>A</CATEGORY> (not B) → propose_protocol rejected by Python.\n"
            "  ❌ BAD: B-class + sal=0.5 → rejected (low salience reflection not worth STRICT).\n\n"
            "🆕 [Sir 2026-05-27 12:13 真痛 anchor] B-class surface_to_sir example "
            "(SHORT-TERM CONTEXTUAL — 仅本会话/几小时有效):\n"
            "  Sir 真痛根因: 思考脑 L1067 意识到 'redundant Good morning' 但选了 "
            "propose_protocol:'Always prioritize concise' — 抽象+慢通路 (review queue\n"
            "  积压 50+, AutoArbiter 几乎全 DEFER, 主脑下轮看不到). 主脑继续重复 5 次\n"
            "  'Good morning'. 真该走 surface_to_sir:next_turn_inject — 15min TTL\n"
            "  直进主脑 prompt build_soul_block [DAEMON SURFACED] 块, 主脑下轮即看.\n"
            "  ✅ GOOD: <CATEGORY>B</CATEGORY>\n"
            "         <THOUGHT>Sir got up at 8am, I've already said 'Good morning, Sir'\n"
            "                  5 times this morning. Embarrassing — short-term I must\n"
            "                  not generic-greet again.</THOUGHT>\n"
            "         <SALIENCE>0.85</SALIENCE>\n"
            "         <ACTIONABLE>surface_to_sir:next_turn_inject:Sir 已起床 4h, 今早已 5 次 Good morning, 短期内绝不再 generic greet — open with concrete evidence (window title/concern) only</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>5 times</EVIDENCE_LINK>\n"
            "         → B-class + sal≥0.7 + CONCRETE OBSERVABLE 行为指令 (含具体数字\n"
            "         '5 次' + 具体 forbidden behavior 'generic greet' + 具体替代\n"
            "         'open with concrete evidence') + cite traces to THOUGHT →\n"
            "         publish SWM inner_thought_surface (15min TTL) → 主脑下轮 prompt\n"
            "         自动看到 → 主脑改行为.\n"
            "  ❌ BAD: <ACTIONABLE>surface_to_sir:next_turn_inject:Be more concise</ACTIONABLE>\n"
            "         → 抽象到主脑 link 不到具体行为. 必须含**具体 evidence + 具体\n"
            "         forbidden action + 具体替代方案**. Vague = 主脑无视.\n"
            "  ❌ BAD: <ACTIONABLE>propose_protocol:Don't say Good morning more than once per morning</ACTIONABLE>\n"
            "         → 这是短期 contextual (跨午夜失效), 不该走 propose_protocol\n"
            "         (long-term policy 通路). 走 surface_to_sir:next_turn_inject.\n\n"
            "🆕 [Sir 2026-05-27 12:13] 通路选择决策树 (B 类必读):\n"
            "  问 1: 这条规则**跨午夜后**仍然适用吗?\n"
            "    YES (e.g. 'Don't open with formal apologies') → propose_protocol (long-term policy)\n"
            "    NO  (e.g. '今早已 5 次 greet 别再说') → surface_to_sir:next_turn_inject (short-term)\n"
            "  问 2: actionable 内容**具体可观察**吗? (主脑能 link 到具体行为)\n"
            "    YES (含具体数字/具体 forbidden action/具体替代) → propose / surface\n"
            "    NO  ('prioritize concise' / 'be more direct' 这种**抽象**) →\n"
            "      DO NOT propose/surface — Python 会让 AutoArbiter REJECT,\n"
            "      tokens 浪费. 直接 ACTIONABLE=none, 或重写到具体级.\n\n"
            "🆕 [Sir 2026-05-27 12:13 反抽象红线 — Python 会 enforce]:\n"
            "  abstract aspirational vocab (主脑 link 不到具体行为, AutoArbiter 历史几乎全 REJECT)\n"
            "  禁止 propose_protocol 含: 'prioritize', 'be more', 'always strive', 'maintain',\n"
            "  'professional', 'genuine', 'aspire', 'cultivate', 'sound like', 'feel like' —\n"
            "  这些是描述形容词不是 IMPERATIVE 行为. 必须改成具体 'Do/Don't/Never + 具体动作'.\n"
            "  GOOD: 'Do not open replies with X' / 'Never say Y when Z' / 'Always include W after V'\n"
            "  BAD:  'Prioritize concise direct cadence' / 'Maintain genuine restraint'\n\n"
            "🆕 [Sir 2026-05-26 SOUL Phase B] C-class adjust_concern_notes example "
            "(treats Sir's \"减少对面试准备的打扰\" 真意 anchor):\n"
            "  ✅ GOOD: <CATEGORY>C</CATEGORY>\n"
            "         <THOUGHT>Sir asked me to stop bringing up interview prep\n"
            "                  unprompted earlier. The concern is still valid, but my\n"
            "                  delivery should change — only address when Sir asks.</THOUGHT>\n"
            "         <SALIENCE>0.8</SALIENCE>\n"
            "         <ACTIONABLE>adjust_concern_notes:sir_interview_pr:DO NOT volunteer this topic — only address when Sir asks directly</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>stop bringing up</EVIDENCE_LINK>\n"
            "         → C-class + sal≥0.7 + cite traces to concern + appended note\n"
            "         → next turn main brain reads note → genuine self-restraint.\n"
            "  ❌ BAD: <CATEGORY>B</CATEGORY> → rejected (notes adjust only from C).\n"
            "  ❌ BAD: C-class + sal=0.5 → rejected (low salience C-class isn't worth note change).\n"
            "  ❌ BAD: cite \"toggling\" with concern_id sir_interview_pr → rejected (cite ↔\n"
            "         concern no token overlap — wrong concern, fix4 anchor)."
        )

        # User block — give LLM evidence to ground thought
        lines: List[str] = []
        # 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] daemon 自己也知"心跳"
        # ===================================================================
        # 思考脑 prompt 起头注入 mini lifetime block — 让它知道:
        #   - 几分钟前在想啥 (recent thoughts time-ordered)
        #   - 几小时前在做啥 (recent actions)
        #   - process 跑多久 / 今日 turn 数 / 跨 session 数
        # 让"思考脑"也守 continuity 防自相矛盾 / 重复 propose 同 protocol.
        # 准则 6 vocab 持久化 (mode='mini' 320 char cap 省 token, 准则 1).
        # ===================================================================
        try:
            lifetime_mini = self.build_lifetime_block(mode='mini')
            if lifetime_mini:
                for ln in lifetime_mini.splitlines():
                    lines.append(ln)
                lines.append("")
        except Exception:
            pass
        lines.append("[CURRENT MOMENT]")
        lines.append(f"  - Sir state: {evidence.get('sir_state')}")
        lines.append(f"  - idle: {evidence.get('idle_seconds')}s")
        lines.append(f"  - hour: {evidence.get('hour')}:00")
        lines.append("")

        # 🆕 [Sir 2026-05-27 00:11 真意 M1 ThoughtChain] 上 3 thought — 让思考连续
        # =====================================================================
        # Sir 真意: "思考能连续, 不像现在离散像看故事". 给 LLM 看上 3 thought 内容,
        # LLM 自决 <CONTINUITY>same_thread:<id> | new_topic</CONTINUITY> 标签.
        # Python 不强 thread, 只追踪 LLM 自报值 — 准则 6 信任 LLM.
        # =====================================================================
        prev_thoughts = evidence.get('recent_thoughts') or []
        if prev_thoughts:
            lines.append("[MY PREVIOUS THOUGHTS (last 3, for continuity — pick one to延续 or new topic)]")
            for t in prev_thoughts:
                age_s = t.get('age_s', 0)
                age_str = (f"{age_s}s ago" if age_s < 60
                              else f"{age_s // 60}m ago" if age_s < 3600
                              else f"{age_s // 3600}h ago")
                cont_marker = t.get('continuity', 'new_topic')
                thread_id_short = (t.get('thread_id', '') or t.get('id', ''))[:12]
                outcome_str = ''
                if t.get('outcome') not in (None, '', 'pending'):
                    outcome_str = f" [outcome: {t.get('outcome')}]"
                lines.append(
                    f"  [{age_str}] thread={thread_id_short} cat={t.get('category')} "
                    f"sal={t.get('salience', 0):.2f} cont={cont_marker}{outcome_str}"
                )
                lines.append(f"    Thought: \"{t.get('thought', '')[:160]}\"")
                if t.get('actionable') and t.get('actionable') != 'none':
                    lines.append(f"    Did: {t.get('actionable', '')[:80]}")
                    # 🆕 [Sir 2026-05-27 00:43 真痛] 显 actionable result 让 LLM 看是否 failed
                    # 防 LLM 重提同 actionable. 同 actionable + 同 result = same_thread 不要重
                    ar = t.get('actionable_result', '') or ''
                    ad = t.get('actionable_done')
                    if ar:
                        mark = '❌ FAILED' if ad is False else (
                            '✅' if ad else '?'
                        )
                        lines.append(f"    Result: {mark} — {ar[:120]}")
                        if ad is False:
                            lines.append(
                                f"    ⚠️ Do NOT re-propose this exact actionable "
                                f"again — it will fail the same way unless "
                                f"underlying constraint changed."
                            )
            lines.append(
                "  ⚠️ If your new thought continues a SAME topic as one above, "
                "output <CONTINUITY>same_thread:<thread_id_short></CONTINUITY> to "
                "extend the chain (Sir can see continuity visually). If truly new "
                "subject, output <CONTINUITY>new_topic</CONTINUITY>."
            )
            lines.append("")

        lines.append("[RECENT SWM EVENTS]")
        sw = evidence.get('swm_events') or []
        if sw:
            for e in sw:
                lines.append(f"  - {e['age_s']}s ago: [{e['type']}] {e['desc']}")
        else:
            lines.append("  (none recent)")
        lines.append("")

        # 🆕 [Sir 2026-05-27 18:44 真愿景 Phase 1 Step 2b] INNER VOICE block
        # ============================================================
        # 让思考脑读 InnerVoiceTrack 近 10min 非 inner_thought 类 entry
        # (sensor / care_trigger / sir_injected 等). 自家 thought 历史已在
        # 上面 [MY PREVIOUS THOUGHTS] block, 这里只补"其他源" — 让思考脑
        # 看到完整意识流, 自决是否产新 thought 接续这些信号.
        # 可回撤: env JARVIS_INNER_VOICE_ENABLED=0 → 跳过本 block.
        # ============================================================
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled as _ivt_enabled,
            )
            if _ivt_enabled():
                _track = get_inner_voice_track()
                _voice_recent = _track.recent(minutes=10.0, max_n=30)
                # 过滤掉 'inner_thought' 类 (那已在 [MY PREVIOUS THOUGHTS])
                _non_thought = [
                    e for e in _voice_recent if e.source != 'inner_thought'
                ]
                if _non_thought:
                    lines.append(
                        "[INNER VOICE — past 10min, cross-source signals "
                        "feeding your consciousness]"
                    )
                    for e in _non_thought[-15:]:  # cap 15
                        _hhmm = time.strftime('%H:%M', time.localtime(e.ts))
                        _wv = ' ★' if e.wants_voice else ''
                        _urg = (
                            f' u={e.urgency:.1f}' if e.urgency >= 0.3 else ''
                        )
                        lines.append(
                            f"  - {_hhmm} ({e.source}/{e.intent}{_urg}){_wv} "
                            f"{e.content[:140]}"
                        )
                    lines.append(
                        "  ↳ Your next thought may extend, respond to, or "
                        "ignore these — your choice (LLM-driven)."
                    )
                    lines.append("")
        except Exception:
            # 不影响思考脑主路径
            pass

        # 🆕 [Sir 2026-05-26 18:54 FIX A] STM 2→5 turn, 字数翻倍 (反思看完整对话)
        lines.append("[STM LAST 5 TURNS]")
        stm = evidence.get('stm') or []
        if stm:
            for t in stm:
                lines.append(f"  - when={t.get('when', '?')}")
                if t.get('user'):
                    lines.append(f"    Sir: \"{t['user']}\"")
                if t.get('jarvis'):
                    lines.append(f"    Me:  \"{t['jarvis']}\"")
        else:
            lines.append("  (no recent turns this session)")
        lines.append("")

        # 🆕 [Sir 2026-05-26 18:54 FIX B] recent_jarvis_actions — 我真做了什么
        # =====================================================================
        # 反思看具体 NUDGE fire/skipped/published/etc, 不光看 thought 文本.
        # 让 Jarvis 能反思 "I just fired return_greeting 6s after commitment_check,
        # Sir might find it pushy" — 比抽象 thought 更具体可反思.
        # =====================================================================
        actions = evidence.get('recent_jarvis_actions') or []
        if actions:
            lines.append("[WHAT I JUST DID (recent SWM actions, latest first)]")
            for a in actions:
                age_s = a.get('age_s', 0)
                age_str = (f"{age_s}s" if age_s < 60
                              else f"{age_s // 60}m{age_s % 60}s")
                lines.append(
                    f"  - [{age_str} ago] {a.get('etype', '?')} "
                    f"({a.get('source', '?')}): {a.get('desc', '')}"
                )
            lines.append(
                "  ⚠️ Reflect: was this action coherent with Sir's intent? "
                "Did I yield to others properly? (β.5.0 三维耦合)"
            )
            lines.append("")

        # 🆕 [Sir 2026-05-26 18:54 FIX C] runtime_log tail — 看真发生的事
        # =====================================================================
        # 终端 summary 漏太多 (bg_log 真完整在 docs/runtime_logs/*.log).
        # 反思在 reflect 时拉 latest.txt → tail 100KB → marker filter →
        # 收 12 行 (旧→新). LLM 能看 sentinel 真 blocked / state transition / etc.
        # marker vocab 持久化 memory_pool/runtime_log_marker_vocab.json (CLI 可改)
        # =====================================================================
        log_tail = evidence.get('runtime_log_tail') or []
        if log_tail:
            lines.append("[REAL RUNTIME LOG (last few minutes, filtered by marker)]")
            for ln in log_tail:
                lines.append(f"  | {ln}")
            lines.append(
                "  ⚠️ This is the SOURCE OF TRUTH — terminal output is "
                "summarized. If reflection contradicts the log, trust the log."
            )
            lines.append("")

        # 🆕 [Sir 2026-05-26 19:48 Phase 1B] anticipated_ltm_context block
        ant_ctx = evidence.get('anticipated_ltm_context', '').strip()
        if ant_ctx:
            lines.append("[ANTICIPATED LTM CONTEXT (Anticipator preload, predicted relevant)]")
            for ln in ant_ctx.split('\n')[:8]:
                if ln.strip():
                    lines.append(f"  | {ln[:160]}")
            lines.append("")

        # 🆕 [Sir 2026-05-26 19:48 Phase 1C] daemon_health block (我自己健康)
        health_warns = evidence.get('daemon_health', [])
        if health_warns:
            lines.append("[MY OWN HEALTH (DaemonHealthMonitor warnings)]")
            for w in health_warns:
                lines.append(
                    f"  - [{w.get('severity', 'warn')}] {w.get('issue', '')[:140]} "
                    f"({w.get('age_h', 0)}h ago)"
                )
            lines.append(
                "  ⚠️ My own daemon is unhealthy. Reflect if it affects "
                "my judgment. Consider proposing fix or notifying Sir."
            )
            lines.append("")

        # 🆕 [Sir 2026-05-27 00:11 真意 M2] TIME CONTEXT — Sir 行为模式 时间理解
        # =====================================================================
        # Sir 原话: "给予贾维斯真正对时间的理解, 这有助于他理解我的行为模式".
        # 数据 source: jarvis_time_awareness vocab (hourly mined) + active routines
        # + today's deviation. LLM 用此 evidence 自决 "Sir 今天反常 / 该提醒 routine
        # / 该 yield 因为他通常此 hour AFK / etc.".
        # =====================================================================
        tp = evidence.get('time_pattern') or {}
        if tp.get('has_data') or evidence.get('time_active_routines') or evidence.get('time_deviation_today'):
            lines.append("[TIME CONTEXT (Sir's behavioral pattern at this hour, learned)]")
            if tp.get('has_data'):
                acts = ', '.join(tp.get('typical_activities', [])[:5])
                lines.append(f"  - Now: {tp.get('hour')}:00 {tp.get('day')}")
                if acts:
                    lines.append(f"  - Sir's typical at this hour: {acts}")
                if tp.get('frequency', 0) > 0:
                    lines.append(
                        f"  - Pattern confidence: {tp['frequency']:.0%} "
                        f"({tp.get('sample_count', 0)} historical samples)"
                    )
                if tp.get('fallback_used'):
                    lines.append(
                        f"  - (Aggregate across days, no {tp.get('day')}-specific data)"
                    )
            dev = evidence.get('time_deviation_today')
            if dev:
                lines.append(f"  - Today's deviation: {dev}")
            for r in (evidence.get('time_active_routines') or [])[:2]:
                lines.append(
                    f"  - Active routine: {r.get('name', '?')} "
                    f"(sig: {','.join(r.get('signature', [])[:3])})"
                )
            lines.append(
                "  ⚠️ Reflect: does this hour-pattern match Sir's current STM signal? "
                "If Sir deviates from typical (e.g. typical sleep at 23 but still coding), "
                "thought may be: yield/silence vs gentle hint based on severity."
            )
            lines.append("")

        # 🆕 [Sir 2026-05-27 00:49 Option B 人设统一] 3 段公共子集 render
        # (按 Sir 优先 "连续>时间>人设": 时间已上, 现 status > profile > directives)
        # =====================================================================
        # Sir 真意: "现在思考脑只看上下文会判断失误" — 加 SirStatusTracker raw +
        # ProfileCard mini + active directive purpose, 让思考脑跟主脑同人设.
        # 全 vocab gate (准则 6 持久化).
        # =====================================================================
        _ds = evidence.get('sir_declared_status')
        if _ds and _ds.get('status'):
            _age_min = _ds.get('age_s', 0) // 60
            _od = ' (overdue)' if _ds.get('is_overdue') else ''
            lines.append("[SIR DECLARED STATUS (raw — Sir 真意 sensor, before aggregation)]")
            lines.append(
                f"  - status: {_ds['status']} | declared "
                f"{_age_min}min ago{_od}"
            )
            lines.append(
                "  ⚠️ Honor Sir's declaration. e.g. status=sleep/nap/dnd "
                "→ NO surface_to_sir / fire_nudge / call_tool 'open UI' "
                "this tick (only silent SWM publish OK). status=out/lunch "
                "→ delay actionable, low urgency."
            )
            lines.append("")

        _pm = evidence.get('sir_profile_mini')
        if _pm:
            lines.append("[SIR PROFILE MINI (identity + state + habit + projects)]")
            for ln in str(_pm).splitlines():
                lines.append(f"  {ln}")
            lines.append("")

        _ad = evidence.get('active_directives') or []
        if _ad:
            lines.append("[ACTIVE DIRECTIVES — main brain rules you must align with]")
            for d in _ad:
                lines.append(
                    f"  - [{d.get('priority', 0)}] {d.get('id')}: "
                    f"{d.get('purpose', '')}"
                )
            lines.append(
                "  ⚠️ Your thought MUST NOT contradict these. e.g. if a directive "
                "is 'DO NOT volunteer interview prep', do not propose_protocol/"
                "fire_nudge against that topic."
            )
            lines.append("")

        lines.append("[YOUR ACTIVE CONCERNS (top 5 by severity)]")
        cc = evidence.get('concerns') or []
        if cc:
            for c in cc:
                # 🆕 [Sir 2026-05-26 13:32 BUG 3] notes 容量信号 — full/near warn
                _nc = c.get('notes_chars', 0)
                _cap_tag = ''
                if _nc >= 400:
                    _cap_tag = f' [notes {_nc}/500 NEAR FULL — adjust will be rejected]'
                elif _nc >= 250:
                    _cap_tag = f' [notes {_nc}/500 half-full]'
                lines.append(
                    f"  - id={c['id']} (severity {c['severity']}): {c['what']}{_cap_tag}"
                )
        else:
            lines.append("  (none active)")
        # 🆕 [Sir 2026-05-25 23:18 真痛-2] 给全 active id list 防 hallucinate
        all_ids = evidence.get('all_active_concern_ids') or []
        if all_ids:
            lines.append(
                f"  ⚠️ ALL VALID concern_ids ({len(all_ids)}): "
                f"{', '.join(all_ids)}"
            )
            lines.append(
                "  ⚠️ HARD RULE: For update_concern_severity AND "
                "adjust_concern_notes, ONLY use IDs from the list above. "
                "Inventing IDs like 'jarvis_self_maintenance' / "
                "'sir_general_health' that SOUND reasonable but aren't in "
                "the list will be REJECTED (concern_not_found). If your "
                "thought doesn't fit any existing concern, use "
                "ACTIONABLE=publish_swm or none — DO NOT invent a concern."
            )
        lines.append("")

        # 🆕 [Sir 2026-05-26 13:32 真痛 BUG 治本] BUG 2 propose dedup: inject
        # 已 active + pending review protocols/jokes, prompt 教 LLM "若已覆盖
        # 同概念, 不再 propose" — 防 5+ 次重复 "Do not use formal apologies".
        active_protos = evidence.get('active_protocols') or []
        review_protos = evidence.get('pending_review_protocols') or []
        if active_protos or review_protos:
            lines.append("[YOUR ACTIVE PROTOCOLS (already in force — main brain enforces)]")
            if active_protos:
                for p in active_protos:
                    lines.append(f"  ✅ {p}")
            else:
                lines.append("  (none active yet)")
            if review_protos:
                lines.append("[PENDING REVIEW (you already proposed — awaiting Sir's verdict)]")
                for p in review_protos:
                    lines.append(f"  ⏳ {p}")
            lines.append(
                "  ⚠️ DO NOT propose_protocol if any above already covers the "
                "same concept (e.g. 'too formal' / 'too verbose' / 'too robotic'). "
                "Re-proposing wastes tokens + AutoArbiter will DEFER. If Sir "
                "hasn't activated, ACCEPT it's pending — don't re-propose."
            )
            lines.append("")

        active_jokes = evidence.get('active_inside_jokes') or []
        review_jokes = evidence.get('pending_review_jokes') or []
        if active_jokes or review_jokes:
            lines.append("[YOUR ACTIVE INSIDE JOKES + PENDING JOKES]")
            for j in active_jokes:
                lines.append(f"  ✅ \"{j}\"")
            for j in review_jokes:
                lines.append(f"  ⏳ \"{j}\"")
            lines.append(
                "  ⚠️ DO NOT suggest_inside_joke if phrase already above (active "
                "or pending). Same phrase will be dedup_or_fail rejected."
            )
            lines.append("")

        # 🆕 [Sir 2026-05-26 20:14 真意 anchor 3] Skepticism Learning Loop block
        # ===================================================================
        # Sir 自然质疑被 SirSkepticismDetector 捕获 → AttributionEngine 找 30s 内
        # 最 plausible target → DecayEngine 自动累 count + decay weight.
        # thought 看这 evidence 自决: B 类 propose_protocol "Don't reuse X" /
        # C 类 adjust_concern_notes "Sir 不喜欢提 Y, 别 volunteer".
        # 准则 6: 不教句式, 只给证据 (etype + matched_phrase + target + count).
        # ===================================================================
        sk_events = evidence.get('recent_skepticism_events') or []
        if sk_events:
            lines.append("[SIR SKEPTICISM RECENT (last 24h, auto-detected from Sir's natural reply)]")
            for ev_sk in sk_events:
                age_s = ev_sk.get('age_s', 0)
                age_str = (f"{age_s}s" if age_s < 60
                              else f"{age_s // 60}m{age_s % 60}s" if age_s < 3600
                              else f"{age_s // 3600}h")
                target_str = ''
                if ev_sk.get('target_kind') and ev_sk.get('target_id'):
                    target_str = f" → {ev_sk['target_kind']}/{ev_sk['target_id']}"
                count_str = ''
                if ev_sk.get('count') is not None:
                    count_str = f" (count={ev_sk['count']})"
                phrase = ev_sk.get('matched_phrase', '')
                phrase_str = f" \"{phrase}\"" if phrase else ''
                lines.append(
                    f"  - [{age_str} ago] {ev_sk['etype']}{phrase_str}{target_str}{count_str}"
                )
            lines.append(
                "  ⚠️ Reflect: Is Sir tired of a specific topic/joke/concern? "
                "Consider propose_protocol (B) like 'Do not bring up X unless asked' "
                "OR adjust_concern_notes (C) to warn main brain. Loop already "
                "decayed weight — your job is meta-learning the pattern."
            )
            lines.append("")

        if free_categories and len(free_categories) < 5:
            lines.append(
                f"[COOLDOWN] {free_str} are the ONLY non-cooldown categories. "
                f"Cooldown: {[c for c in 'ABCDE' if c not in free_categories]} "
                f"— pick from {free_str} only."
            )
            lines.append("")

        lines.append("Now generate ONE inner thought (4 tags strict).")
        return system, '\n'.join(lines)

    # ----------------------------------------------------------
    # LLM call (Flash-Lite via LlmReflector, caller='inner_thought' → P2 LOW)
    # ----------------------------------------------------------
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            # LlmReflector 用 __new__ 单例 — 直接构造即拿已有实例
            reflector = LlmReflector(key_router=self.key_router)
            res = reflector.reflect(
                model='flash_lite',
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                force=True,  # 不走 cache (每次新 think)
                caller=KeyRouter.CALLER_INNER_THOUGHT,  # 自动 LOW + 30/min 限速
            )
            if not res.get('success'):
                return ''
            return res.get('raw_text', '') or ''
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] LLM call exception: {e}")
            return ''

    # ----------------------------------------------------------
    # Parse LLM output
    # ----------------------------------------------------------
    def _parse_thought(self, raw: str, sir_state: str,
                        tick_interval: int) -> Optional[InnerThought]:
        cat_m = re.search(r'<CATEGORY>\s*([A-E])\s*</CATEGORY>', raw, re.IGNORECASE)
        thought_m = re.search(r'<THOUGHT>(.*?)</THOUGHT>', raw, re.DOTALL)
        sal_m = re.search(r'<SALIENCE>\s*([0-9.]+)\s*</SALIENCE>', raw)
        action_m = re.search(r'<ACTIONABLE>(.*?)</ACTIONABLE>', raw, re.DOTALL)
        # 🆕 [Sir 2026-05-26 00:25 真痛"地基"] evidence link 解析
        ev_link_m = re.search(
            r'<EVIDENCE_LINK>(.*?)</EVIDENCE_LINK>', raw, re.DOTALL
        )
        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] NEXT_INTERVAL 解析
        next_int_m = re.search(
            r'<NEXT_INTERVAL>(.*?)</NEXT_INTERVAL>', raw, re.DOTALL
        )
        # 🆕 [Sir 2026-05-27 00:11 M1 ThoughtChain] CONTINUITY 解析 (option)
        cont_m = re.search(
            r'<CONTINUITY>(.*?)</CONTINUITY>', raw, re.DOTALL
        )
        if not (cat_m and thought_m and sal_m):
            return None
        thought_text = (thought_m.group(1) or '').strip()
        if not thought_text or thought_text.lower() in ('(quiet)', '(none)', '...'):
            return None
        try:
            sal = max(0.0, min(1.0, float(sal_m.group(1))))
        except (ValueError, TypeError):
            sal = 0.3
        actionable = (action_m.group(1).strip() if action_m else 'none')[:200]
        if not actionable:
            actionable = 'none'
        evidence_link = (
            (ev_link_m.group(1) or '').strip() if ev_link_m else ''
        )[:120]
        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] parse next_interval (raw LLM value).
        # 0 = LLM 没给或给 'default' (用 baseline)
        next_int_raw = (
            (next_int_m.group(1) or '').strip().lower() if next_int_m else ''
        )
        next_interval_s = 0
        if next_int_raw and next_int_raw != 'default':
            try:
                _v = int(next_int_raw)
                # 允许 enum 内的值 (gate 在 _tick 才真应用)
                if _v in self._NEXT_INTERVAL_ENUM:
                    next_interval_s = _v
            except (ValueError, TypeError):
                next_interval_s = 0
        now = time.time()
        new_id = f"thought_{time.strftime('%Y%m%d_%H%M%S')}_{int(now * 1000) % 10000:04x}"
        # 🆕 [Sir 2026-05-27 00:11 M1 ThoughtChain] continuity → thread_id 解析
        # LLM 输出 'same_thread:<id_short>' / 'new_topic'.
        # Python: 同 thread → 沿用 prev thread_id; 新 topic → thread_id = self.id (新 thread).
        # 防错: 'same_thread:' 后 id 必须能在 recent_thoughts 中找到 (按 prefix),
        # 否则降级 new_topic + thread_id=self.id (准则 5: 不信 LLM 编造 id).
        continuity_raw = (
            (cont_m.group(1) or '').strip().lower() if cont_m else ''
        )[:80]
        thread_id = new_id  # default: new thread
        continuity = 'new_topic'
        if continuity_raw.startswith('same_thread:'):
            claimed_id = continuity_raw.split(':', 1)[1].strip()[:32]
            if claimed_id:
                # 查 recent thoughts (unlocked snapshot, 接受 race)
                try:
                    for t in list(self._thoughts)[-10:]:
                        candidate_thread = getattr(t, 'thread_id', '') or t.id
                        if (candidate_thread.startswith(claimed_id) or
                                t.id.startswith(claimed_id)):
                            thread_id = candidate_thread
                            continuity = 'same_thread'
                            break
                except Exception:
                    pass
        elif continuity_raw == 'new_topic':
            continuity = 'new_topic'
            thread_id = new_id
        return InnerThought(
            id=new_id,
            ts=now,
            ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
            category=cat_m.group(1).upper(),
            thought=thought_text[:300],
            salience=sal,
            actionable=actionable,
            actionable_done=False,
            actionable_result='pending',
            sir_state=sir_state,
            tick_interval_s=tick_interval,
            evidence_link=evidence_link,
            next_interval_s=next_interval_s,
            tick_origin='',
            thread_id=thread_id,
            continuity=continuity,
        )

    # ----------------------------------------------------------
    # Actionable executor (4 档, 全可逆/低风险)
    # ----------------------------------------------------------
    def _execute_actionable(self, thought: InnerThought) -> Tuple[bool, str]:
        a = (thought.actionable or '').strip()
        if not a or a.lower() == 'none':
            return True, 'none'

        # 🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] EVIDENCE LINK 校验 (HARD GATE)
        # actionable != none 时, LLM 必须 cite THOUGHT 中真实出现的字串证明 trace.
        # 缺 EVIDENCE_LINK 或 cite 字串不在 thought 里 → 降级 actionable=none.
        # 准则 5 言出必行 + 6 evidence: 无 evidence 不执行.
        gate_ok, gate_reason = self._validate_evidence_link(thought)
        if not gate_ok:
            # 降级: 不真执行 actionable, 标记 rejected (Sir 看 log 真知道原因)
            thought.actionable = 'none'  # 防 SOUL inject 误以为有 action
            return False, f'rejected_no_evidence_link:{gate_reason}'

        try:
            if a.startswith('update_concern_severity:'):
                ok, result = self._do_update_concern_severity(thought, a)
                # 🆕 [Sir 真痛 anchor] 二层 fail (cite ↔ concern wrong) →
                # 降级 thought.actionable=none 防 SOUL inject 误导主脑
                if not ok and 'evidence_link_wrong_concern' in result:
                    thought.actionable = 'none'
                return ok, result
            if a.startswith('publish_swm:'):
                return self._do_publish_swm_actionable(thought, a)
            if a.startswith('suggest_inside_joke:'):
                return self._do_suggest_inside_joke(thought, a)
            # 🆕 [Sir 2026-05-26 SOUL Phase A] propose_protocol — B 类反思真改自己行为
            # B 类 sal≥0.75 反思 → propose protocol → AutoArbiter 自决 →
            # Layer 2 SOUL "STRICT RULES" → 下次 turn 主脑硬约束.
            if a.startswith('propose_protocol:'):
                return self._do_propose_protocol(thought, a)
            # 🆕 [Sir 2026-05-26 SOUL Phase B] adjust_concern_notes — C 类反思改 concern note
            # C 类 sal≥0.7 反思 → 给 concern.notes_for_self append note →
            # Layer 1 prompt 主脑下次看 (现有路径) → 主脑自主调整对该 concern 反应方式.
            # Sir 真意 anchor: "减少对面试准备的打扰" → 改 concern.notes 让主脑下次克制.
            if a.startswith('adjust_concern_notes:'):
                ok, result = self._do_adjust_concern_notes(thought, a)
                # 二层 fail (cite ↔ concern wrong) → 降级 actionable=none (同 update_severity)
                if not ok and 'evidence_link_wrong_concern' in result:
                    thought.actionable = 'none'
                return ok, result
            # 🆕 [Sir 2026-05-26 19:48 Phase 1A] fire_nudge — thought 自决出声
            # sal>=0.85 + 接 nudge_coordination yield + 主脑 directive 可 [SILENCE].
            # 详 docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §2 Phase 1A.
            if a.startswith('fire_nudge:'):
                return self._do_fire_nudge_actionable(thought, a)
            # 🆕 [Sir 2026-05-26 19:48 Phase 2A] propose_watch_task — thought 设长目标
            # C/D 类 sal>=0.75 → 调 PromiseLog watch kind (现有 schema).
            if a.startswith('propose_watch_task:'):
                return self._do_propose_watch_task(thought, a)
            # 🆕 [Sir 2026-05-26 19:48 Phase 3] call_tool — thought 真行动 (高风险)
            # sal>=0.90 + tool in allowlist + Sir 元否决预留 (CLI revert).
            if a.startswith('call_tool:'):
                return self._do_call_tool_actionable(thought, a)
            # 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 C] surface_to_sir — thought 主动发声
            # =================================================================
            # Sir 真痛: "思考层也没主动发声". 给 thought 一档轻量 surface 通道:
            #   - terminal_pulse: bg_log 终端显示 (Sir 真看见, 不抢 voice)
            #   - next_turn_inject: publish SWM, 主脑下轮 prompt 强提示 reference
            # 阈值 + 频限 + channel allow list 全持久化
            # memory_pool/surface_to_sir_vocab.json (Sir CLI 可调).
            # =================================================================
            if a.startswith('surface_to_sir:'):
                return self._do_surface_to_sir_actionable(thought, a)
            return False, f'unknown_actionable:{a[:40]}'
        except Exception as e:
            return False, f'exception:{str(e)[:80]}'

    def _validate_evidence_link(self, thought: InnerThought
                                    ) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] 校验 evidence link.

        actionable != none 时, thought.evidence_link 必须:
          1. 非空 (LLM 真给了 cite)
          2. cite 字串 (lower, strip 标点) 真出现在 thought.thought (lower) 里
            (LLM 不能 cite thought 之外的词 — 防 hallucinate trace)

        返回:
          (True, '') — 通过校验, 真执行 actionable
          (False, reason) — 降级 actionable=none, log reason

        准则 6 evidence-driven + 5 言出必行: 无 evidence 不执行.
        """
        cite = (thought.evidence_link or '').strip()
        if not cite or cite.lower() in ('none', '(none)', '-'):
            return False, 'no_cite (LLM 没给 EVIDENCE_LINK)'

        # 归一化: lower + 去标点 (' " . , ! ? ; :)
        def _normalize(s: str) -> str:
            return re.sub(r'[\'".,!?;:\-]', '', s.lower()).strip()

        cite_norm = _normalize(cite)
        thought_norm = _normalize(thought.thought or '')
        if not cite_norm:
            return False, 'cite_empty_after_normalize'

        if cite_norm not in thought_norm:
            # 兜底: 拆词 (LLM 可能 cite "without rest" 而 thought 有 "needing rest"
            # → 分别 check "without" + "rest", 至少 50% words 命中也算)
            cite_words = [w for w in cite_norm.split() if len(w) > 2]
            if not cite_words:
                return False, f'cite_not_in_thought:"{cite[:40]}"'
            hits = sum(1 for w in cite_words if w in thought_norm)
            if hits < max(1, len(cite_words) // 2):
                return False, (
                    f'cite_not_in_thought:"{cite[:40]}" '
                    f'({hits}/{len(cite_words)} words match)'
                )
        return True, ''

    # 🆕 [Sir 2026-05-26 00:25 真痛 anchor] generic stopwords 防 token overlap 噪音
    # ("sir/i/my" 这种词所有 concern/thought 都有, 不能算 meaningful link)
    _GENERIC_STOPWORDS = frozenset({
        'sir', 'jarvis', 'i', 'me', 'my', 'you', 'your', 'we', 'us', 'our',
        'the', 'a', 'an', 'and', 'or', 'but', 'on', 'in', 'at', 'of', 'to',
        'for', 'with', 'is', 'are', 'was', 'were', 'has', 'have', 'had',
        'be', 'been', 'do', 'does', 'did', 'this', 'that', 'these', 'those',
        'it', 'its', 'his', 'her', 'them', 'their', 'as', 'so', 'if', 'than',
        'thought', 'noticed', 'thinking', 'wondering', 'just', 'now',
        'really', 'should', 'would', 'could', 'might', 'may', 'will',
        'shall', 'about', 'over', 'between', 'from', 'into', 'after',
        'before', 'still', 'also', 'very', 'quite',
    })

    def _meaningful_tokens(self, s: str) -> set:
        """拆词去 stopword + 短词 — 留 meaningful evidence tokens."""
        if not s:
            return set()
        words = re.findall(r'\w+', s.lower())
        return {
            w for w in words
            if len(w) > 2 and w not in self._GENERIC_STOPWORDS
        }

    def _evidence_links_to_concern(self, evidence_link: str,
                                       concern) -> Tuple[bool, str]:
        """🆕 [Sir 真痛 anchor 治本] cite 是否真 link 到 concern.

        cite 词跟 concern (id 拆 underscore + what_i_watch) 至少 1 个
        meaningful token 重合. 防"cite 真在 thought 但是 wrong concern"
        (Sir 真测 evidence: thought 提 toggling general/coding → cite=toggling →
         target=sir_interview_pr → 应 reject, toggling 跟 interview 无关).

        Returns: (ok, overlap_word_or_reason).
        """
        cite_tokens = self._meaningful_tokens(evidence_link)
        concern_id_tokens = self._meaningful_tokens(
            (getattr(concern, 'id', '') or '').replace('_', ' ')
        )
        concern_what_tokens = self._meaningful_tokens(
            getattr(concern, 'what_i_watch', '') or ''
        )
        concern_tokens = concern_id_tokens | concern_what_tokens
        if not cite_tokens:
            # cite 全 stopword 或空 — 不严判, LLM 不严就让过 (准则 6 信任 LLM)
            return True, '(no meaningful cite tokens — trust LLM)'
        if not concern_tokens:
            return True, '(concern has no meaningful tokens — trust LLM)'
        overlap = cite_tokens & concern_tokens
        if overlap:
            return True, f'overlap:{next(iter(overlap))}'
        return False, (
            f'no_token_overlap (cite:{sorted(cite_tokens)[:3]} vs '
            f'concern:{sorted(concern_tokens)[:3]})'
        )

    def _do_update_concern_severity(self, thought: InnerThought,
                                       a: str) -> Tuple[bool, str]:
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected update_concern_severity:<id>:<delta>)'
        _, cid, delta_str = parts
        cid = cid.strip()
        if not cid:
            return False, 'empty_concern_id'
        try:
            delta = float(delta_str.strip())
        except ValueError:
            return False, f'delta_not_float:{delta_str[:30]}'
        # cap ±SEVERITY_DELTA_CAP
        delta = max(-self.SEVERITY_DELTA_CAP, min(self.SEVERITY_DELTA_CAP, delta))
        if not self.concerns_ledger:
            return False, 'no_concerns_ledger'
        c = self.concerns_ledger.get(cid) if hasattr(
            self.concerns_ledger, 'get'
        ) else self.concerns_ledger.concerns.get(cid)
        if c is None:
            return False, f'concern_not_found:{cid}'
        # 🆕 [Sir 2026-05-26 00:25 真痛 anchor 治本] 二层校验: cite ↔ concern overlap
        # 真痛: cite 真在 thought 但 wrong concern (toggling → interview_pr).
        # 此处校验 cite 词跟 concern 至少 1 个 meaningful token 重合.
        link_ok, link_msg = self._evidence_links_to_concern(
            thought.evidence_link, c
        )
        if not link_ok:
            return False, f'evidence_link_wrong_concern:{cid}:{link_msg}'
        new_sev = max(0.0, min(1.0, c.severity + delta))
        if abs(new_sev - c.severity) < 1e-3:
            return True, f'no-op (already {c.severity:.2f})'
        ok, msg, old_v = self.concerns_ledger.update_concern_field(
            cid, 'severity', new_sev,
            source='inner_thought',
            turn_id=thought.id,
            reason=f"inner_thought [{thought.category}]: {thought.thought[:80]}",
        )
        if ok:
            return True, f'sev {old_v:.2f}→{new_sev:.2f} ({delta:+.2f})'
        return False, f'update_fail:{msg[:60]}'

    def _do_publish_swm_actionable(self, thought: InnerThought,
                                      a: str) -> Tuple[bool, str]:
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected publish_swm:<etype>:<desc>)'
        _, etype, desc = parts
        etype = etype.strip()[:60] or 'inner_thought_seed'
        desc = desc.strip()[:200]
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return False, 'no_bus'
            bus.publish(
                etype=etype,
                description=desc,
                source='inner_thought',
                salience=thought.salience,
                metadata={
                    'thought_id': thought.id,
                    'thought_category': thought.category,
                    'thought_text': thought.thought[:200],
                },
                ttl=3600.0,
            )
            return True, f'published:{etype}'
        except Exception as e:
            return False, f'publish_fail:{str(e)[:60]}'

    def _do_suggest_inside_joke(self, thought: InnerThought,
                                   a: str) -> Tuple[bool, str]:
        phrase = a.split(':', 1)[1].strip() if ':' in a else ''
        if not phrase:
            return False, 'empty_phrase'
        if not self.relational_state:
            return False, 'no_relational_state'
        if not hasattr(self.relational_state, 'propose_inside_joke'):
            return False, 'propose_inside_joke method not found'
        # build InsideJoke
        try:
            from jarvis_relational import InsideJoke
            joke = InsideJoke(
                id=f"joke_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 10000:04x}",
                phrase=phrase[:80],
                birth_context=f"inner_thought [{thought.category}]: {thought.thought[:120]}",
                tone='wry',  # default, Sir 可改
                source='inner_thought',
                source_marker=thought.id,
                birth_turn_id='',
            )
            ok = self.relational_state.propose_inside_joke(joke)
            if ok:
                # 🚨 [Sir 2026-05-26 12:21 真痛 fix] propose 后立即 flush 到 disk.
                # 不依赖 inside_joke_reflector 救场 (准则 5 言出必行).
                self._flush_relational('inside_joke')
            return ok, f'proposed:{phrase[:30]}' if ok else 'dedup_or_fail'
        except Exception as e:
            return False, f'joke_build_fail:{str(e)[:60]}'

    def _flush_relational(self, kind: str) -> None:
        """🚨 [Sir 2026-05-26 12:21 真痛 fix] flush relational_state to disk + review queue.

        Sir 真测 75 个 thought 后 dashboard 还是 0 protocols — 根因:
        propose_X 只 set _dirty=True 不真写 disk. protocol 没 reflector daemon
        救场 → 永远丢. 准则 5 言出必行: 自己负责自己的 persistence.

        kind 仅 log 用 ('inside_joke' / 'protocol' / 其他). 失败不重抛 (best-effort).
        """
        try:
            rs = self.relational_state
            if rs is None:
                return
            # persist 主 state file (active entities)
            if hasattr(rs, 'persist'):
                rs.persist()
            # write_review_queue 写 review state (AutoArbiter 要看的 queue)
            if hasattr(rs, 'write_review_queue'):
                rs.write_review_queue()
        except Exception as e:
            try:
                self._bg_log(
                    f"⚠️ [InnerThought] _flush_relational({kind}) failed: "
                    f"{str(e)[:80]}"
                )
            except Exception:
                pass

    def _do_propose_protocol(self, thought: InnerThought,
                                a: str) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 SOUL Phase A] propose UnspokenProtocol from B-class.

        actionable=propose_protocol:<one-sentence imperative rule>
        rule 必须:
          - 来自 B 类 self-reflection (强制 category check)
          - sal ≥ 0.75 (强制 salience gate, 低 sal 反思不值得 STRICT RULE)
          - rule 文字非空 + ≤ 200 char

        流程:
          parse rule → build UnspokenProtocol(state=REVIEW) →
          relational.propose_protocol → AutoArbiter 30min tick 自决 →
          Layer 2 SOUL inject 'STRICT RULES' → 下次 turn 主脑硬约束.
        """
        # 🆕 [Sir 2026-05-26 23:17 真痛 BUG-4 治本 / 准则 6 LLM 自决]
        # =====================================================================
        # 老 hard gate `category != 'B'` 拦 cross-class — Sir 真测痛点:
        # B-class thought "my reply abrupt; Sir mentioned fatigue" 想 propose_protocol
        # "Don't be abrupt when Sir tired" — 完全合理, 但被 Python 拦.
        # 准则 6: LLM 决策, python 不教类别. 保 sal gate (准则 5 strict rule 要高 sal).
        # =====================================================================
        if thought.salience < 0.75:
            return False, (
                f'gated:protocol_requires_sal>=0.75 (got {thought.salience:.2f})'
            )

        rule = a.split(':', 1)[1].strip() if ':' in a else ''
        if not rule:
            return False, 'empty_rule'
        if len(rule) < 10:
            return False, f'rule_too_short:{len(rule)}<10'

        if not self.relational_state:
            return False, 'no_relational_state'
        if not hasattr(self.relational_state, 'propose_protocol'):
            return False, 'propose_protocol method not found'

        try:
            from jarvis_relational import UnspokenProtocol
            pid = (
                f"proto_{time.strftime('%Y%m%d_%H%M%S')}"
                f"_{int(time.time() * 1000) % 10000:04x}"
            )
            protocol = UnspokenProtocol(
                id=pid,
                rule=rule[:200],
                source='inner_thought',
                source_marker=thought.id,
            )
            ok = self.relational_state.propose_protocol(protocol)
            if ok:
                # 🚨 [Sir 2026-05-26 12:21 真痛 fix] CRITICAL 修:
                # 之前 propose_protocol 后没调 persist + write_review_queue
                # → _dirty=True 但永远不 flush 到 disk
                # → 重启后 protocols=0 (Sir 真测 75 个 thought 后 dashboard 还是 0)
                # → Phase A propose_protocol 闭环全废
                # protocol 没 reflector daemon 救场, 必须自己 flush.
                self._flush_relational('protocol')
            return ok, (
                f'proposed:{rule[:30]} (id={pid})'
                if ok else 'dedup_or_fail'
            )
        except Exception as e:
            return False, f'protocol_build_fail:{str(e)[:60]}'

    # 🆕 [Sir 2026-05-26 SOUL Phase B] adjust_concern_notes constants
    _NOTES_MAX_CHARS = 500             # concern.notes_for_self 总长 cap (schema)
    _NOTES_APPEND_MAX = 120            # 单次 append note 长 cap (防一次写太长)

    def _do_adjust_concern_notes(self, thought: InnerThought,
                                    a: str) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-26 SOUL Phase B] adjust concern notes from C-class.

        actionable=adjust_concern_notes:<concern_id>:<note text>

        gate:
          - C 类 only (强制 category check) — A/B/D/E reflect 不改 concern notes
          - sal ≥ 0.7 (低 sal reflection 不值得改 concern note)
          - cid 真存在
          - 复用 evidence_link 双层 gate (cite 在 thought + cite ↔ concern overlap)

        流程:
          parse cid + note → 复用 _evidence_links_to_concern 二层 gate →
          existing_notes + ' | [inner_thought] ' + note → cap 500 →
          ConcernsLedger.update_concern_field('notes_for_self', new_value)
          → Layer 1 prompt 主脑下次自然读 (现有路径).

        Sir 真意 anchor: 上一轮 Sir 说"减少对面试准备的打扰" →
        C 类 thought: "Sir asked me to stop bringing up interview prep unprompted"
        actionable: adjust_concern_notes:sir_interview_pr:
                     DO NOT volunteer this topic — only address when Sir asks
        → 下次 turn 主脑读 note → 真克制.
        """
        # 🆕 [Sir 2026-05-26 23:17 真痛 BUG-4 治本 / 准则 6 LLM 自决]
        # =====================================================================
        # 老 hard gate `category != 'C'` 拦 cross-class — Sir 真测痛点 (22:42:13):
        # B-class thought 想 adjust_concern_notes:sir_interview_prep — 完全合理
        # (B-self-reflect 看到自己 abrupt, 给 sir_interview_prep concern 加 note
        # "Sir 累, 别 abrupt"), 但被 Python 拦. 准则 6 违反.
        # 保 sal gate + cid 真存在 + cite 双层 gate 仍守 (准则 5/6 防 LLM 瞎编).
        # =====================================================================
        # gate: sal
        if thought.salience < 0.7:
            return False, (
                f'gated:notes_adjust_requires_sal>=0.7 '
                f'(got {thought.salience:.2f})'
            )

        # parse "adjust_concern_notes:<cid>:<note>"
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected adjust_concern_notes:<cid>:<note>)'
        _, cid, note = parts
        cid = cid.strip()
        note = note.strip()
        if not cid:
            return False, 'empty_concern_id'
        if not note:
            return False, 'empty_note'
        if len(note) < 10:
            return False, f'note_too_short:{len(note)}<10'

        if not self.concerns_ledger:
            return False, 'no_concerns_ledger'

        # locate concern
        c = self.concerns_ledger.get(cid) if hasattr(
            self.concerns_ledger, 'get'
        ) else self.concerns_ledger.concerns.get(cid)
        if c is None:
            return False, f'concern_not_found:{cid}'

        # 二层 gate: cite ↔ concern overlap (复用 fix4 evidence_link 机制 — 防 wrong concern)
        link_ok, link_msg = self._evidence_links_to_concern(
            thought.evidence_link, c
        )
        if not link_ok:
            return False, f'evidence_link_wrong_concern:{cid}:{link_msg}'

        # build new notes (append 不覆盖 + tag 来源 + cap)
        note_capped = note[:self._NOTES_APPEND_MAX]
        existing = (c.notes_for_self or '').strip()
        # 🆕 [Sir 2026-05-27 21:11 真测 P3 升级] notes 满 80% → 自动 prune (archive
        # 老段到 jsonl 不丢历史) → 继续 append. 不再让 InnerThought 反复 propose-reject
        # 循环 (Sir 真测 21:05 看到 'notes_near_cap:485/500' 反复出现).
        # 旧行为 (Sir 2026-05-26 13:32 BUG 3): >=80% → reject 'notes_near_cap'.
        # 新行为: >=80% → ledger.prune_concern_notes(target=50%) → 继续 append.
        # Fallback: 若 prune no-op (smallest segment 已超 target) → 退回老 reject.
        if len(existing) >= int(self._NOTES_MAX_CHARS * 0.8):
            try:
                prune_ok, prune_msg, archived_n = (
                    self.concerns_ledger.prune_concern_notes(
                        cid,
                        target_chars=int(self._NOTES_MAX_CHARS * 0.5),
                        source='inner_thought_auto_prune',
                        turn_id=thought.id,
                    )
                )
                if prune_ok and archived_n > 0:
                    try:
                        from jarvis_utils import bg_log
                        bg_log(
                            f'🗂️ [InnerThought/AutoPrune] {cid} {prune_msg}'
                        )
                    except Exception:
                        pass
                    # reload existing — c.notes_for_self 已被 prune 改写
                    existing = (c.notes_for_self or '').strip()
                # 若 prune no-op (smallest segment exceeds target) → 退回老 reject
                if len(existing) >= int(self._NOTES_MAX_CHARS * 0.8):
                    return False, (
                        f'notes_near_cap:{len(existing)}/{self._NOTES_MAX_CHARS} '
                        f'(>=80% — auto-prune attempted: {prune_msg})'
                    )
            except Exception as e:
                return False, (
                    f'notes_near_cap_prune_exception:{str(e)[:60]}'
                )
        tag = f"[inner_thought/{thought.category}/sal={thought.salience:.2f}]"
        new_note_segment = f"{tag} {note_capped}"
        if existing:
            new_notes = (existing + ' | ' + new_note_segment).strip(' |')
        else:
            new_notes = new_note_segment
        new_notes = new_notes[:self._NOTES_MAX_CHARS]

        # 用 update_concern_field 走标准 mutation 路径 (有 signal trail + 持久化)
        try:
            ok, msg, old_v = self.concerns_ledger.update_concern_field(
                cid, 'notes_for_self', new_notes,
                source='inner_thought',
                turn_id=thought.id,
                reason=f"inner_thought [{thought.category}]: {thought.thought[:80]}",
            )
            if ok:
                return True, (
                    f'notes appended ({len(new_note_segment)} char added, '
                    f'total {len(new_notes)}/{self._NOTES_MAX_CHARS})'
                )
            return False, f'update_fail:{msg[:60]}'
        except Exception as e:
            return False, f'notes_update_exception:{str(e)[:60]}'

    # ============================================================
    # 🆕 [Sir 2026-05-26 19:48 Phase 1A] fire_nudge actionable
    # ============================================================
    # Sir 真问 "目前思考和真主动性距离" → 准则 6 极致版 audit:
    # thought 只 update_concern/notes/publish_swm — 不能直接 trigger 主脑出声.
    # 治本: 加 fire_nudge 让 thought 自决出声, 接 nudge_coordination yield
    # (跟 5 sentinel 平等), 主脑 directive 可 [SILENCE] 反否决.
    # 详 docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §2 Phase 1A.
    # ============================================================
    FIRE_NUDGE_MIN_SAL = 0.85         # 严: sal 不够不 fire (防 daemon 过激)

    def _do_fire_nudge_actionable(self, thought: InnerThought,
                                     a: str) -> Tuple[bool, str]:
        """thought 自决出声 — 接 nudge_coordination yield, 跟 5 sentinel 平等.

        Format: fire_nudge:<kind>:<draft_text>
          kind: 'thought_observation' / 'thought_concern' / 'thought_proactive' / ...
          draft_text: 1-2 句草稿 (主脑可改写, 可 [SILENCE])

        gate:
          - sal >= 0.85 (严)
          - evidence_link 真在 thought 中 (复用 _validate_evidence_link)
          - 接 nudge_coordination.should_yield (跟 5 sentinel 平等)
          - 主脑 directive 看到 type='inner_thought_fire' 可 [SILENCE]
        """
        if thought.salience < self.FIRE_NUDGE_MIN_SAL:
            return False, (
                f'gated:fire_nudge_requires_sal>={self.FIRE_NUDGE_MIN_SAL} '
                f'(got {thought.salience:.2f})'
            )
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected fire_nudge:<kind>:<draft>)'
        _, kind, draft = parts
        kind = (kind or '').strip()[:40] or 'thought_observation'
        draft = (draft or '').strip()[:200]
        if not draft:
            return False, 'empty_draft'

        # nudge_coordination yield (跟 SmartNudge / ReturnSentinel / Conductor / ProactiveCare / CommitmentWatcher 平等)
        try:
            from jarvis_nudge_coordination import (
                should_yield_to_recent_proactive_nudge as _yield_check,
                publish_proactive_nudge_skipped as _pub_skip,
            )
            _should_yield, _yield_reason = _yield_check(
                within_s=600.0,
                current_kind=f'inner_thought_{kind}',
                current_sentinel='InnerThought',
            )
            if _should_yield:
                _pub_skip(
                    kind=f'inner_thought_{kind}',
                    sentinel='InnerThought',
                    reason=_yield_reason,
                )
                return False, f'yielded:{_yield_reason}'
        except Exception:
            pass  # coordination 失败时仍 fire (向后兼容)

        # dispatch __NUDGE__ (同 SmartNudge 路径, 但加 type='inner_thought_fire' 标记
        # 让主脑 directive 知道这是 thought 提议, 优先 [SILENCE])
        try:
            import json as _json_fn
            from jarvis_utils import resolve_worker_attr
            worker = self.nerve
            if worker is None:
                return False, 'no_nerve'
            context = {
                'type': 'inner_thought_fire',
                'kind': kind,
                'channel': 'voice',
                'nudge_directive': draft,
                'source': 'InnerThought',
                'thought_id': thought.id,
                'thought_category': thought.category,
                'thought_salience': thought.salience,
                'thought_evidence_link': thought.evidence_link,
                'thought_text': thought.thought[:200],
            }
            cmd = f"__NUDGE__:{_json_fn.dumps(context, ensure_ascii=False)}"
            # nerve push_command (central_nerve has push_command)
            if hasattr(worker, 'push_command'):
                worker.push_command(cmd)
            else:
                return False, 'nerve_no_push_command'

            # fire 后 publish (让别 sentinel yield)
            try:
                from jarvis_nudge_coordination import publish_proactive_nudge_fired as _pn_pub
                _pn_pub(
                    kind=f'inner_thought_{kind}',
                    sentinel='InnerThought',
                    extra_metadata={
                        'thought_id': thought.id,
                        'thought_category': thought.category,
                    },
                )
            except Exception:
                pass

            return True, f'fired:{kind} (sal={thought.salience:.2f})'
        except Exception as e:
            return False, f'fire_nudge_exception:{str(e)[:60]}'

    # ============================================================
    # 🆕 [Sir 2026-05-26 19:48 Phase 2A] propose_watch_task actionable
    # ============================================================
    # Sir 真意: thought 该能"设长期目标" (e.g. 每 2h check 项目进度).
    # PromiseLog 已有 watch kind + trigger_pattern, 复用现有 schema 不新建 module.
    # 详 docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §2 Phase 2A.
    # ============================================================
    PROPOSE_WATCH_MIN_SAL = 0.75

    def _do_propose_watch_task(self, thought: InnerThought,
                                 a: str) -> Tuple[bool, str]:
        """thought 提议长期 watch task — 直接调 PromiseLog watch kind.

        Format: propose_watch_task:<trigger_kind>:<desc>
          trigger_kind: 'cycle_hours:2' / 'cycle_minutes:30' / 'screen_keyword:interview'
          desc: 1-2 句长目标描述 (e.g. "每 2h check Sir 面试准备进度")

        gate:
          - category in C/D (concern_evolution / proactive_seed)
          - sal >= 0.75
        """
        if thought.category not in ('C', 'D'):
            return False, (
                f'gated:propose_watch_only_from_C_or_D '
                f'(got {thought.category})'
            )
        if thought.salience < self.PROPOSE_WATCH_MIN_SAL:
            return False, (
                f'gated:propose_watch_requires_sal>={self.PROPOSE_WATCH_MIN_SAL} '
                f'(got {thought.salience:.2f})'
            )
        # Format: propose_watch_task:<trigger_kind>:<trigger_value>:<desc>
        # split 3 (max 4 parts: action, kind, value, desc)
        parts = a.split(':', 3)
        if len(parts) < 4:
            return False, (
                'parse_fail (expected propose_watch_task:<trigger_kind>:'
                '<value>:<desc>)'
            )
        _, t_kind, t_val, desc = parts
        t_kind = (t_kind or '').strip()[:30]
        t_val = (t_val or '').strip()[:30]
        desc = (desc or '').strip()[:200]
        if not t_kind or not desc:
            return False, 'empty_trigger_kind_or_desc'

        try:
            from jarvis_promise_log import get_default_log
            plog = get_default_log()
            trigger_pattern = {'kind': t_kind, 'value': t_val}

            pid = plog.register(
                description=desc,
                kind='watch',
                deadline_str='',  # watch kind 没 deadline
                jarvis_reply=thought.thought[:200],
                author='jarvis',
            )
            # 加 trigger_pattern (PromiseLog Promise dataclass 已有 field)
            try:
                p = plog.promises.get(pid)
                if p is not None:
                    p.trigger_pattern = trigger_pattern
                    plog._dirty = True
                    plog._persist()
            except Exception:
                pass
            return True, f'watch_task:{pid} ({t_kind}:{t_val})'
        except Exception as e:
            return False, f'propose_watch_exception:{str(e)[:60]}'

    # ============================================================
    # 🆕 [Sir 2026-05-26 19:48 Phase 3] call_tool actionable (高风险)
    # ============================================================
    # Sir 真意: thought 真"行动" — 调 tool 直接做事 (set_reminder / commitment).
    # 风险: 错调 tool 让 Sir 反感. 准则 7 Sir 元否决预留:
    #   - allowlist 持久化 memory_pool/inner_thought_tool_allowlist.json
    #   - 每次 fire 后 publish SWM 'inner_thought_tool_called' (Sir 看 dashboard)
    #   - CLI scripts/inner_thought_tool_revert.py 1-click 撤
    # 详 docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §2 Phase 3.
    # ============================================================
    CALL_TOOL_MIN_SAL = 0.90          # 极严
    CALL_TOOL_ALLOWLIST_PATH = 'memory_pool/inner_thought_tool_allowlist.json'

    def _load_call_tool_allowlist(self) -> set:
        """读 allowlist (持久化 + fallback)."""
        try:
            import json as _json
            path = self.CALL_TOOL_ALLOWLIST_PATH
            if not os.path.isabs(path):
                root = os.path.dirname(os.path.abspath(__file__))
                path = os.path.join(root, path)
            if not os.path.exists(path):
                return set(self._DEFAULT_CALL_TOOL_ALLOWLIST)
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            return set(data.get('allowlist') or self._DEFAULT_CALL_TOOL_ALLOWLIST)
        except Exception:
            return set(self._DEFAULT_CALL_TOOL_ALLOWLIST)

    # default allowlist (preserve daemon 可用 if JSON missing)
    _DEFAULT_CALL_TOOL_ALLOWLIST = (
        'commitment_register',
        'self_promise_register',
        'milestone_register',
    )

    def _do_call_tool_actionable(self, thought: InnerThought,
                                    a: str) -> Tuple[bool, str]:
        """thought 真行动 — 调 TOOL_REGISTRY 中 allowlist 内 tool.

        Format: call_tool:<tool_name>:<json_args>
          tool_name: 必须 in allowlist (Sir 持久化 JSON 控)
          json_args: tool 的参数 (dict, json 序列化)

        gate:
          - sal >= 0.90 (极严)
          - tool_name in allowlist
          - json_args 真 parse 成 dict
          - 每次 fire 后 publish SWM 让 Sir 看 dashboard
        """
        if thought.salience < self.CALL_TOOL_MIN_SAL:
            return False, (
                f'gated:call_tool_requires_sal>={self.CALL_TOOL_MIN_SAL} '
                f'(got {thought.salience:.2f})'
            )
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, 'parse_fail (expected call_tool:<tool_name>:<json_args>)'
        _, tool_name, args_str = parts
        tool_name = (tool_name or '').strip()
        args_str = (args_str or '').strip()
        if not tool_name:
            return False, 'empty_tool_name'

        # allowlist gate
        allowlist = self._load_call_tool_allowlist()
        if tool_name not in allowlist:
            return False, (
                f'tool_not_in_allowlist:{tool_name} '
                f'(Sir CLI to add: scripts/inner_thought_tool_allowlist_dump.py)'
            )

        # parse args
        try:
            import json as _json
            args_dict = _json.loads(args_str) if args_str else {}
            if not isinstance(args_dict, dict):
                return False, f'args_not_dict:{type(args_dict).__name__}'
        except Exception as e:
            return False, f'args_parse_fail:{str(e)[:60]}'

        # dispatch via TOOL_REGISTRY
        try:
            from jarvis_tool_registry import get_tool_registry
            registry = get_tool_registry()
            tool_fn = registry.get(tool_name)
            if tool_fn is None:
                return False, f'tool_not_registered:{tool_name}'
            result = tool_fn(**args_dict)
            if not isinstance(result, dict):
                return False, f'tool_returned_non_dict:{type(result).__name__}'
            ok_flag = bool(result.get('ok', False))

            # publish SWM 'inner_thought_tool_called' (Sir 看 dashboard + 可 revert)
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='inner_thought_tool_called',
                        description=(
                            f"thought {thought.id} called tool {tool_name} "
                            f"(ok={ok_flag}): {(result.get('result') or result.get('error') or '')[:80]}"
                        ),
                        source='InnerThought',
                        salience=0.85,
                        metadata={
                            'thought_id': thought.id,
                            'tool_name': tool_name,
                            'args': args_dict,
                            'ok': ok_flag,
                            'result': (result.get('result') or '')[:200],
                            'error': (result.get('error') or '')[:200],
                        },
                        ttl=86400.0,
                    )
            except Exception:
                pass

            if ok_flag:
                return True, f'called:{tool_name} → {(result.get("result") or "")[:60]}'
            return False, f'tool_failed:{tool_name} → {(result.get("error") or "")[:60]}'
        except Exception as e:
            return False, f'call_tool_exception:{str(e)[:60]}'

    # ==========================================================================
    # 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 C 治本] surface_to_sir handler
    # ==========================================================================
    # Sir 真痛: "思考层也没主动发声". thought 自决 surface 给 Sir 看, 不抢 voice.
    # 两档 channel:
    #   - terminal_pulse: bg_log "💭 [Thought→Sir] {summary}" — Sir 终端真看见
    #   - next_turn_inject: publish SWM 'inner_thought_surface' — 主脑下轮 prompt
    #     强提示 reference 这条 thought (主脑自决说不说, 不强出声)
    # 阈值 + 频限 + channel allow list 全持久化 memory_pool/surface_to_sir_vocab.json
    # (Sir CLI 可改). 准则 6 vocab + 准则 8 优雅 + 准则 1 高效 (低成本通道).
    # ==========================================================================
    def _do_surface_to_sir_actionable(self, thought: InnerThought,
                                          a: str) -> Tuple[bool, str]:
        """thought 主动 surface 给 Sir — terminal_pulse / next_turn_inject 两档.

        Format: surface_to_sir:<channel>:<one-sentence summary>
        gates: sal >= vocab.salience_threshold, channel in allowed_channels,
               cooldown_global_s, cooldown_per_channel_s, max_per_hour.
        """
        cfg = _load_surface_to_sir_config()
        sal_thr = float(cfg.get('salience_threshold', 0.7))
        if thought.salience < sal_thr:
            return False, (
                f'gated:surface_requires_sal>={sal_thr} '
                f'(got {thought.salience:.2f})'
            )

        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, ('parse_fail (expected '
                              'surface_to_sir:<channel>:<summary>)')
        _, channel, summary = parts
        channel = (channel or '').strip().lower()
        summary = (summary or '').strip()
        if not channel or not summary:
            return False, 'empty_channel_or_summary'

        allowed = list(cfg.get('allowed_channels') or [])
        if channel not in allowed:
            return False, (
                f'channel_not_allowed:{channel} '
                f'(allowed: {",".join(allowed)})'
            )

        # cooldown / hourly cap check (lazy init instance state)
        now = time.time()
        if not hasattr(self, '_surface_history'):
            self._surface_history: List[Tuple[float, str]] = []
        if not hasattr(self, '_surface_last_global_ts'):
            self._surface_last_global_ts = 0.0
        if not hasattr(self, '_surface_last_per_channel_ts'):
            self._surface_last_per_channel_ts: dict = {}

        cd_global = float(cfg.get('cooldown_global_s', 120))
        if now - self._surface_last_global_ts < cd_global:
            wait = int(cd_global - (now - self._surface_last_global_ts))
            return False, f'gated:global_cooldown_{wait}s_left'

        cd_ch = float(cfg.get('cooldown_per_channel_s', 300))
        last_ch_ts = float(self._surface_last_per_channel_ts.get(channel, 0))
        if now - last_ch_ts < cd_ch:
            wait = int(cd_ch - (now - last_ch_ts))
            return False, f'gated:channel_{channel}_cooldown_{wait}s_left'

        max_h = int(cfg.get('max_per_hour', 6))
        # prune history > 1h
        cutoff_h = now - 3600
        self._surface_history = [
            (ts, ch) for ts, ch in self._surface_history if ts > cutoff_h
        ]
        if len(self._surface_history) >= max_h:
            return False, f'gated:hourly_cap_{max_h}_reached'

        # execute per channel
        try:
            if channel == 'terminal_pulse':
                self._bg_log(
                    f"💭 [Thought→Sir / sal={thought.salience:.2f}] {summary[:200]}"
                )
            elif channel == 'next_turn_inject':
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='inner_thought_surface',
                        description=(
                            f"thought {thought.id} surfacing to next turn: "
                            f"{summary[:160]}"
                        ),
                        source='InnerThoughtDaemon',
                        salience=max(0.75, thought.salience),
                        metadata={
                            'thought_id': thought.id,
                            'category': thought.category,
                            'salience': thought.salience,
                            'summary': summary[:200],
                            'channel': channel,
                        },
                        ttl=900.0,  # 15min — 主脑下次 2-3 turn 都能看到
                    )
            else:
                # 新 channel 已 in allowed (vocab 加了), 但 handler 未实现
                return False, f'channel_unimplemented:{channel}'
        except Exception as e:
            return False, f'surface_exception:{channel}:{str(e)[:60]}'

        # update cooldown state
        self._surface_last_global_ts = now
        self._surface_last_per_channel_ts[channel] = now
        self._surface_history.append((now, channel))

        # publish SWM 'inner_thought_surface_executed' 让 outcome worker (D) 可追踪
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='inner_thought_surface_executed',
                    description=(
                        f"thought {thought.id} surfaced via {channel}: "
                        f"{summary[:120]}"
                    ),
                    source='InnerThoughtDaemon',
                    salience=0.7,
                    metadata={
                        'thought_id': thought.id,
                        'channel': channel,
                        'summary': summary[:200],
                    },
                    ttl=86400.0,
                )
        except Exception:
            pass

        return True, f'surfaced:{channel}:{summary[:60]}'

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-27 00:11 M3 VisualPulse] subtle 💭 字幕区闪
    # ----------------------------------------------------------
    _PULSE_VOCAB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'inner_thought_pulse_vocab.json',
    )
    _PULSE_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
    _PULSE_VOCAB_CHECK_INTERVAL_S = 30.0
    _PULSE_DEFAULT_VOCAB = {
        'enabled': True,
        'min_sal_to_pulse': 0.3,
        'min_pulse_cooldown_s': 30,
        'skip_if_main_convo_recent_s': 5,
        'max_text_chars': 50,
        'show_continuity_marker': True,
        'show_category': True,
    }

    def _load_pulse_vocab(self) -> dict:
        """Lazy load + 30s throttle. Fail-safe → default."""
        now = time.time()
        cache = self._PULSE_VOCAB_CACHE
        if (cache['data'] is not None and
                now - cache['checked_at'] < self._PULSE_VOCAB_CHECK_INTERVAL_S):
            return cache['data']
        cache['checked_at'] = now
        try:
            if not os.path.exists(self._PULSE_VOCAB_PATH):
                cache['data'] = dict(self._PULSE_DEFAULT_VOCAB)
                return cache['data']
            mtime = os.path.getmtime(self._PULSE_VOCAB_PATH)
            if mtime == cache['mtime'] and cache['data']:
                return cache['data']
            with open(self._PULSE_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            config = dict(self._PULSE_DEFAULT_VOCAB)
            for k, v in (data or {}).items():
                if k in self._PULSE_DEFAULT_VOCAB:
                    config[k] = v
            cache['data'] = config
            cache['mtime'] = mtime
            return config
        except Exception:
            return dict(self._PULSE_DEFAULT_VOCAB)

    # 🆕 [Sir 2026-05-27 00:49 Option B 人设统一] identity_block vocab loader
    # =====================================================================
    # 持久化 memory_pool/inner_thought_identity_block_vocab.json, mtime cache,
    # 30s throttle, fail-safe → default (5 段全 on / limits 默认值).
    # Sir CLI 一关一段不需改 .py (准则 6 + 8).
    # =====================================================================
    _IDENTITY_VOCAB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'inner_thought_identity_block_vocab.json',
    )
    _IDENTITY_VOCAB_CACHE: dict = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    _IDENTITY_VOCAB_CHECK_INTERVAL_S = 30.0
    _IDENTITY_DEFAULT_VOCAB = {
        'blocks_enabled': {
            'now_time': True, 'hour_pattern': True,
            'sir_declared_status': True, 'sir_profile_mini': True,
            'active_directives': True,
        },
        'limits': {
            'profile_max_chars': 400, 'directives_top_n': 5,
            'directive_purpose_max_chars': 80,
            'hour_pattern_max_activities': 3,
            'hour_pattern_max_topics': 3,
        },
    }

    def _load_identity_block_vocab(self) -> dict:
        """Lazy load + 30s throttle. Fail-safe → default (全 on)."""
        now = time.time()
        cache = self._IDENTITY_VOCAB_CACHE
        if (cache['data'] is not None and
                now - cache['checked_at'] <
                    self._IDENTITY_VOCAB_CHECK_INTERVAL_S):
            return cache['data']
        cache['checked_at'] = now
        try:
            if not os.path.exists(self._IDENTITY_VOCAB_PATH):
                cache['data'] = dict(self._IDENTITY_DEFAULT_VOCAB)
                return cache['data']
            mtime = os.path.getmtime(self._IDENTITY_VOCAB_PATH)
            if mtime == cache['mtime'] and cache['data']:
                return cache['data']
            with open(self._IDENTITY_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # deep-merge (block by block, key by key)
            cfg = {
                'blocks_enabled': dict(
                    self._IDENTITY_DEFAULT_VOCAB['blocks_enabled']
                ),
                'limits': dict(self._IDENTITY_DEFAULT_VOCAB['limits']),
            }
            if isinstance(data.get('blocks_enabled'), dict):
                cfg['blocks_enabled'].update(data['blocks_enabled'])
            if isinstance(data.get('limits'), dict):
                cfg['limits'].update(data['limits'])
            cache['data'] = cfg
            cache['mtime'] = mtime
            return cfg
        except Exception:
            return dict(self._IDENTITY_DEFAULT_VOCAB)

    def _emit_thought_pulse(self, thought: InnerThought) -> None:
        """字幕区 subtle 💭 闪 (Sir 真看见思考). vocab 节流.

        节流条件 (ALL must pass):
          (1) vocab enabled
          (2) sal >= min_sal_to_pulse
          (3) 距上次 pulse >= min_pulse_cooldown_s
          (4) 距主对话最后 turn >= skip_if_main_convo_recent_s
        失败 silent fallback (不阻 daemon).
        """
        vocab = self._load_pulse_vocab()
        if not vocab.get('enabled', True):
            return
        if thought.salience < float(vocab.get('min_sal_to_pulse', 0.3)):
            return
        now = time.time()
        last_pulse = getattr(self, '_last_pulse_ts', 0.0)
        if now - last_pulse < float(vocab.get('min_pulse_cooldown_s', 30)):
            return
        # 主对话 N 秒内不闪 — 优先 Sir 真说话
        skip_recent = float(vocab.get('skip_if_main_convo_recent_s', 5))
        if skip_recent > 0:
            try:
                if self.nerve and getattr(self.nerve, 'short_term_memory', None):
                    stm = list(self.nerve.short_term_memory)
                    if stm and isinstance(stm[-1], dict):
                        last_turn = stm[-1]
                        last_t = last_turn.get('ts') or last_turn.get('time_ts') or 0
                        if isinstance(last_t, (int, float)) and last_t > 0:
                            if now - last_t < skip_recent:
                                return
            except Exception:
                pass
        # 构造 subtitle text
        max_chars = int(vocab.get('max_text_chars', 50))
        thought_preview = (thought.thought or '').strip()[:max_chars]
        markers = []
        if vocab.get('show_category', True):
            markers.append(thought.category)
        if vocab.get('show_continuity_marker', True):
            cont = getattr(thought, 'continuity', '') or ''
            if cont == 'same_thread':
                markers.append('→thread')
            elif cont == 'new_topic':
                markers.append('•new')
        marker_str = ('[' + '/'.join(markers) + '] ') if markers else ''
        subtitle_text = f"{marker_str}{thought_preview}"
        # 真发到 subtitle_queue (chat_bypass holds ref)
        try:
            if self.nerve and hasattr(self.nerve, 'chat_bypass'):
                cb = self.nerve.chat_bypass
                if cb and hasattr(cb, 'subtitle_queue'):
                    cb.subtitle_queue.put(('thought_pulse', subtitle_text))
                    self._last_pulse_ts = now
        except Exception:
            pass

    # ----------------------------------------------------------
    # SWM publish (jarvis_inner_thought event)
    # ----------------------------------------------------------
    def _publish_swm(self, thought: InnerThought) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='jarvis_inner_thought',
                description=f"[{thought.category}] {thought.thought[:120]}",
                source='inner_thought_daemon',
                salience=thought.salience,
                metadata={
                    'thought_id': thought.id,
                    'category': thought.category,
                    'salience': thought.salience,
                    'actionable': thought.actionable[:100],
                    'actionable_done': thought.actionable_done,
                    'actionable_result': thought.actionable_result[:80],
                    'sir_state': thought.sir_state,
                },
                ttl=86400.0,  # 24h, for SOUL inject lookback
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # Persistence (append-only jsonl)
    # ----------------------------------------------------------
    def _persist_thought(self, thought: InnerThought) -> None:
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            with open(self.PERSIST_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(thought), ensure_ascii=False) + '\n')
            # 🆕 [Sir 2026-05-25 23:50 "防爆"] every 10 writes cheap stat check
            try:
                from jarvis_jsonl_rotator import maybe_rotate
                maybe_rotate(self.PERSIST_PATH, check_every_n_writes=10)
            except Exception:
                pass
            # 🆕 [Sir 2026-05-25 23:50 真问] B 类高 salience self-reflection
            # 真存 Hippocampus (长期 self-knowledge, 跨 24h jsonl cutoff 仍存)
            self._maybe_archive_to_hippocampus(thought)
            # 🆕 [Sir 2026-05-27 18:44 真愿景 Phase 1 Step 2] 同步 append voice track
            # 让 thought 成为 inner_voice 流的一部分, 主脑下次召唤能看到为"我刚在想"
            self._append_to_voice_track(thought)
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] persist fail: {e}")

    # 🆕 [Sir 2026-05-27 18:44 真愿景 Phase 1 Step 2] thought → voice 桥
    # ============================================================
    # 把 thought 翻译成 VoiceEntry append 进 InnerVoiceTrack. 主脑下次召唤
    # 读 voice 块, 看到自己刚在想什么, 自然 weave 进 reply.
    # 准则 6 三维耦合: 数据强耦合 (voice 是 SWM 高层); 行为弱耦合 (不强制
    # 主脑 reference); 决策集中主脑 (LLM 自决 weave).
    # 可回撤: env JARVIS_INNER_VOICE_ENABLED=0 → 跳过.
    # ============================================================
    # category → intent map (A 观察 / B 反思 / C 关怀 / D 主动 / E 关系)
    _CATEGORY_TO_INTENT = {
        'A': 'observation',
        'B': 'reflection',
        'C': 'care',
        'D': 'noting',       # 主动想法 (含 actionable)
        'E': 'noting',       # 关系维系 (inside jokes / 心情)
    }

    def _append_to_voice_track(self, thought) -> None:
        """thought → VoiceEntry 桥. 静默 fail (不影响主路径)."""
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled,
            )
            if not is_enabled():
                return
            track = get_inner_voice_track()
            intent = self._CATEGORY_TO_INTENT.get(
                getattr(thought, 'category', '') or '', 'noting'
            )
            # urgency: 复用 salience (0-1)
            urgency = float(getattr(thought, 'salience', 0.0) or 0.0)
            # wants_voice: 高 salience + 含 actionable (非 'none') → 思考脑认为想开口
            actionable = (getattr(thought, 'actionable', '') or 'none').lower()
            has_actionable = actionable not in ('', 'none')
            wants_voice = (urgency >= 0.7) and has_actionable
            # content: 取 thought.thought 原文 (人话, LLM 产, ≤300 char)
            content = (getattr(thought, 'thought', '') or '').strip()
            # meta: 留 category / continuity / thread_id / actionable / outcome
            meta = {
                'category': getattr(thought, 'category', ''),
                'thread_id': getattr(thought, 'thread_id', ''),
                'continuity': getattr(thought, 'continuity', ''),
                'actionable': actionable if has_actionable else None,
                'outcome': getattr(thought, 'outcome', None),
            }
            meta = {k: v for k, v in meta.items() if v}
            track.append(
                source='inner_thought',
                content=content,
                intent=intent,
                urgency=urgency,
                wants_voice=wants_voice,
                meta=meta or None,
                ts=getattr(thought, 'ts', None),
            )
        except Exception:
            # 不影响 thought 主路径
            pass

    # 🆕 [Sir 2026-05-25 23:50 真问 "反思要不要拿额外的记忆来存"]
    # B 类 sal >= 0.8 self-reflection (深刻自反思) → 真存 Hippocampus.
    # 设计 (准则 1 高效 + 6 evidence + 8 优雅):
    #   - 不每条 thought 都存 (cost 爆 + noise). 只存高 sal B 类 (真深刻反思).
    #   - 预计 ~5-20 条/月 (cost 极低, $0.001-$0.005/月)
    #   - 跨 24h jsonl cutoff 仍能 search (Hippocampus decay 30 天 halflife)
    #   - 长期演化基础: 几个月后 Sir 问 "你以前对自己有什么反思过?"
    #     Hippocampus 真能召回历史 self_reflection events
    HIPPOCAMPUS_ARCHIVE_THRESHOLD = 0.8

    def _maybe_archive_to_hippocampus(self, thought) -> None:
        """高 salience B 类反思 → Hippocampus 长期存."""
        if thought.category != 'B':
            return
        if thought.salience < self.HIPPOCAMPUS_ARCHIVE_THRESHOLD:
            return
        try:
            # 直接走 Hippocampus.add_memory (走 MemoryHub 太绕)
            hc = None
            if self.nerve:
                hc = getattr(self.nerve, 'hippocampus', None)
            if hc is None or not hasattr(hc, 'add_memory'):
                return
            # cost-light: 不抢 LLM caller 流量
            summary = (
                f"[Self-Reflection / sal={thought.salience:.2f}] "
                f"{thought.thought}"
            )
            try:
                hc.add_memory(
                    intent='self_reflection',
                    summary=summary,
                    entities=[{
                        'type': 'self_reflection',
                        'category': 'B',
                        'thought_id': thought.id,
                        'salience': thought.salience,
                        'sir_state': thought.sir_state,
                    }],
                    gemini_key='',  # add_memory 会自己经 key_router 拿 key
                )
                self._bg_log(
                    f"🧬 [InnerThought→Hippocampus] B-thought "
                    f"(sal={thought.salience:.2f}) archived to long-term memory"
                )
            except Exception as e:
                self._bg_log(
                    f"⚠️ [InnerThought→Hippocampus] archive fail (非致命): {e}"
                )
        except Exception:
            pass

    def _load_persist(self) -> None:
        if not os.path.exists(self.PERSIST_PATH):
            return
        try:
            cutoff = time.time() - 86400.0  # 24h
            with open(self.PERSIST_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get('ts', 0) < cutoff:
                            continue
                        self._thoughts.append(InnerThought(**d))
                    except (json.JSONDecodeError, TypeError):
                        continue
            # 🆕 [Sir 2026-05-26 00:20 真问"为什么不显示在想什么了"] 治本:
            # 不再从 persist 重建 _last_category_ts. 重启 = 新 session,
            # cooldown 全 reset 让 daemon 第一个 tick (60s) 真出新 thought.
            # SOUL inject 仍读 self._thoughts (给主脑 24h 历史连续性), 不丢.
            # 老 BUG: load 14 旧 thought → 5 类全 in cooldown → 23min 不动 →
            # Sir 终端零新 thought 显示, 误以为 daemon dead.
        except Exception as e:
            self._bg_log(f"⚠️ [InnerThought] load persist fail: {e}")

    # ----------------------------------------------------------
    # SOUL inject (called from central_nerve._build_layer_1b_*)
    # ----------------------------------------------------------
    def build_soul_block(self, max_chars: Optional[int] = None) -> str:
        """返回 SOUL inject block — Freshness-aware ranking.

        🆕 [Sir 2026-05-26 20:55 真痛追根 方案 A 治本 / 准则 6 vocab 持久化]
        =====================================================================
        Sir 真痛: "想了一堆没体现在对话里" — 老 sal=0.9 thought 永远挤掉
        新 sal=0.7 thought, 主脑 prompt 永远看到陈年老 thought.

        修法 (准则 8 优雅): score = salience * w_sal + recency * w_rec.
          recency = e^(-age / halflife_s) ∈ (0, 1], 越新越接近 1.
          默认 w_sal=0.5 / w_rec=0.5 / halflife=1h → 60min 前 sal=0.9 (~0.5)
          会输给 5min 前 sal=0.7 (~0.81). 老 thought 自然 decay.

        权重 + cap 全持久化到 memory_pool/inner_thought_soul_block_vocab.json
        (准则 6 不在 .py 硬编码), Sir CLI 可改.
        =====================================================================
        """
        config = _load_soul_block_config()
        max_age_s = float(config.get('max_age_s', 86400))
        if max_chars is None:
            max_chars = int(config.get('max_chars', self.SOUL_INJECT_MAX_CHARS))
        cutoff = time.time() - max_age_s
        with self._lock:
            recent = [t for t in self._thoughts if t.ts > cutoff]
        if not recent:
            return ''

        # 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 B 治本] query-aware mode
        # =================================================================
        # 检 SWM 最近 60s 有 'sir_thought_query_detected' (directive trigger
        # 在 directive evaluation 时 publish) → 切强化模式:
        #   - recency 权重升 (老 thought 进一步 decay)
        #   - max_inject 升 (给主脑更多 fresh thought 可选)
        #   - 标题改 "[SIR JUST ASKED — SURFACE THESE]" 让主脑强 attention
        # 不修永久 vocab 阈值, 只本次 build 临时 boost. 准则 6 evidence-driven.
        # =================================================================
        sir_asked = False
        try:
            from jarvis_utils import get_event_bus as _geb_q
            _bus_q = _geb_q()
            if _bus_q is not None:
                _top_q = _bus_q.top_n(n=20) or []
                for _ev_q in _top_q:
                    if _ev_q.get('type') != 'sir_thought_query_detected':
                        continue
                    _age_raw = _ev_q.get('_age_s')
                    _age_q = float(_age_raw if _age_raw is not None else 999999)
                    if _age_q <= 60.0:  # 1 turn 内有效
                        sir_asked = True
                        break
        except Exception:
            pass

        # Freshness-aware score (Sir 真痛治本)
        weights = config.get('weights') or {}
        w_sal = float(weights.get('salience', 0.5))
        w_rec = float(weights.get('recency', 0.5))
        halflife_s = float(config.get('recency_halflife_s', 3600))
        # query-aware boost: recency 权重升到 0.8, halflife 短到 30min
        if sir_asked:
            w_sal = 0.2
            w_rec = 0.8
            halflife_s = 1800.0
        now = time.time()
        scored = []
        for t in recent:
            age = max(0.0, now - t.ts)
            recency = math.exp(-age / max(1.0, halflife_s))
            score = t.salience * w_sal + recency * w_rec
            scored.append((t, score))
        scored.sort(key=lambda x: -x[1])

        max_inject = int(config.get('max_inject', self.SOUL_INJECT_MAX))
        if sir_asked:
            max_inject = max(max_inject, 5)  # 给主脑至少 5 条选 (强化)
        top_scored = scored[:max_inject]
        # 时间排序 (旧到新) 让主脑看 narrative
        top_scored.sort(key=lambda x: x[0].ts)

        # query-aware mode → 标题改, 主脑强 attention
        if sir_asked:
            lines = ["=== MY RECENT INNER THOUGHTS — "
                      "SIR JUST ASKED, SURFACE THE FRESHEST ==="]
        else:
            lines = ["=== MY RECENT INNER THOUGHTS "
                      "(last 24h, ranked by freshness × salience) ==="]
        for t, score in top_scored:
            age_min = max(1, int((now - t.ts) / 60))
            action_str = ''
            if t.actionable and t.actionable.lower() != 'none':
                if t.actionable_done:
                    action_str = f" ✓ {t.actionable_result[:30]}"
                else:
                    action_str = " → pending"
            lines.append(
                f"  [{t.category}/{age_min}min ago/sal {t.salience:.2f}] "
                f"{t.thought[:140]}{action_str}"
            )
        # 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 C 衔接] inner_thought_surface event
        # =================================================================
        # 若最近 15min 有 thought 主动 surface (via _do_surface_to_sir_actionable
        # next_turn_inject channel), block 末尾加一行强提示主脑 reference 这条.
        # 准则 6: 全 SWM evidence-driven, 不教内容只给信号.
        # =================================================================
        try:
            from jarvis_utils import get_event_bus as _geb_s
            _bus_s = _geb_s()
            if _bus_s is not None:
                _top_s = _bus_s.top_n(n=20) or []
                _surfaces = []
                for _ev_s in _top_s:
                    if _ev_s.get('type') != 'inner_thought_surface':
                        continue
                    _age_raw = _ev_s.get('_age_s')
                    _age_s = float(_age_raw if _age_raw is not None else 999999)
                    if _age_s > 900.0:  # 15min cap (matches publish ttl)
                        continue
                    _meta = _ev_s.get('metadata') or {}
                    _surfaces.append({
                        'tid': _meta.get('thought_id', '')[:30],
                        'summary': str(_meta.get('summary', ''))[:120],
                        'age_min': max(1, int(_age_s / 60)),
                    })
                if _surfaces:
                    lines.append("")
                    lines.append(
                        "  ⚡ [DAEMON SURFACED THESE FOR YOUR ATTENTION — "
                        "reference if natural, don't force]"
                    )
                    for _s in _surfaces[:3]:
                        lines.append(
                            f"     • [{_s['age_min']}min ago / "
                            f"{_s['tid']}] {_s['summary']}"
                        )
                    # 🆕 [Sir 2026-05-27 12:22 真问 Phase 2] surface 显示来源引导
                    # ===========================================================
                    # Sir 真问: '我在什么方面能感受到他思考链的连续?'
                    # 真痛: 主脑虽看 [DAEMON SURFACED] 但 reference 时**隐藏来源** —
                    # Sir 听不出"这条是思考脑动的, 不是您主动问的". Sir 感不到思考链 alive.
                    # 修法: 给主脑示范"如 reference 请明说来源", 让 Sir 耳朵能听到
                    # "我思考脑刚才在想..." / "我后台想到您..." 这类 explicit 来源标识.
                    # ===========================================================
                    lines.append(
                        "     ↳ [IF YOU REFERENCE — SHOW THE SOURCE]: Sir 真问\n"
                        "       '我感不到思考链 alive'. 若你引用上面这些, **明示来源**\n"
                        "       让 Sir 听到 (不是 Sir 提的, 是我后台想到的). 示范:\n"
                        "         · 'Sir, 我刚才在想... <reference>'\n"
                        "         · '我后台还记得您上次说... <reference>'\n"
                        "         · '后台一直在留意 <topic>, 看到 <evidence>...'\n"
                        "       **避免**'根据系统记录' / '日志显示' (机械感). 用拟人化:\n"
                        "         · 'I've been thinking about...'\n"
                        "         · 'In the back of my mind...'\n"
                        "         · 'I remembered earlier that you...'\n"
                        "       evidence-driven 自决, 不强制每次都说. 一句够."
                    )
        except Exception:
            pass

        block = '\n'.join(lines)
        if len(block) > max_chars:
            block = block[:max_chars - 14].rstrip() + '\n…[truncated]'
        return block

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] daemon 是心跳 keeper
    # ----------------------------------------------------------
    # 设计原则 (Sir 反问校准 — 走 daemon 扩 API, 不抽独立 module):
    #   - daemon 已 60s tick + 持久化 _thoughts jsonl, 它本就 own 时间数据
    #   - 主脑 Layer 1.5 升级为调本 build_lifetime_block (按 tier_mode 选)
    #   - daemon 自己 _build_prompt 也接 mini lifetime (思考脑也知道几分钟前)
    #   - cold_starts.jsonl + yesterday_recap.jsonl 都 daemon own (心跳 keeper)
    # 准则 6.4 公共子集 + 8 优雅 (不重复发明)
    # ----------------------------------------------------------
    _COLD_STARTS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'jarvis_cold_starts.jsonl',
    )
    _YESTERDAY_RECAP_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'jarvis_yesterday_recap.jsonl',
    )
    _LIFETIME_VOCAB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'jarvis_lifetime_block_vocab.json',
    )
    _LIFETIME_VOCAB_CACHE: dict = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    _LIFETIME_DEFAULT_VOCAB = {
        'tier_mode': {
            'SHORT_CHAT': 'full', 'DEEP_QUERY': 'full',
            'FACTUAL_RECALL': 'mini', 'WAKE_ONLY': 'mini',
            'REMINDER_FIRING': 'off',
        },
        'mode_limits': {
            'mini': {'max_chars': 320, 'recent_thoughts_n': 2,
                       'recent_actions_n': 2},
            'full': {'max_chars': 700, 'recent_thoughts_n': 4,
                       'recent_actions_n': 4},
        },
        'recent_thoughts_lookback_s': 900,   # 15min
        'recent_actions_lookback_s': 7200,   # 2h
        'cross_session_max_records': 12,     # 跨 session 显前 N (最近优先)
        'yesterday_recap_enabled': True,
        'yesterday_recap_hour': 23,          # 23 点窗 LLM 写昨日 recap
        'yesterday_recap_cooldown_s': 82800, # 23h
    }

    def _load_lifetime_vocab(self) -> dict:
        """Lazy load + 30s throttle. Fail-safe → default."""
        now = time.time()
        cache = self._LIFETIME_VOCAB_CACHE
        if (cache['data'] is not None and
                now - cache['checked_at'] < 30.0):
            return cache['data']
        cache['checked_at'] = now
        try:
            if not os.path.exists(self._LIFETIME_VOCAB_PATH):
                cache['data'] = dict(self._LIFETIME_DEFAULT_VOCAB)
                return cache['data']
            mtime = os.path.getmtime(self._LIFETIME_VOCAB_PATH)
            if mtime == cache['mtime'] and cache['data']:
                return cache['data']
            with open(self._LIFETIME_VOCAB_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cfg = dict(self._LIFETIME_DEFAULT_VOCAB)
            # deep-merge 1 层
            for k, v in (data or {}).items():
                if k in cfg and isinstance(cfg[k], dict) and isinstance(v, dict):
                    merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
                else:
                    cfg[k] = v
            cache['data'] = cfg
            cache['mtime'] = mtime
            return cfg
        except Exception:
            return dict(self._LIFETIME_DEFAULT_VOCAB)

    def _append_cold_start_record(self) -> None:
        """daemon init 时 append 一条 cold_start record (跨 session 持久)."""
        try:
            sess_id = ''
            try:
                from jarvis_utils import TraceContext
                sess_id = TraceContext.get_session_id() or ''
            except Exception:
                pass
            # 读上一条算 prev_session_age_s
            prev_age = None
            try:
                if os.path.exists(self._COLD_STARTS_PATH):
                    with open(self._COLD_STARTS_PATH, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    if lines:
                        last = json.loads(lines[-1].strip())
                        prev_ts = float(last.get('ts', 0))
                        if prev_ts > 0:
                            prev_age = int(time.time() - prev_ts)
            except Exception:
                pass
            record = {
                'ts': time.time(),
                'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                          time.localtime()),
                'session_id': sess_id,
                'prev_cold_start_age_s': prev_age,
                'reason': 'first_run' if prev_age is None else 'restart',
            }
            os.makedirs(os.path.dirname(self._COLD_STARTS_PATH),
                          exist_ok=True)
            with open(self._COLD_STARTS_PATH, 'a',
                       encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception:
            pass

    def _load_cold_starts(self, max_n: int = 12) -> List[dict]:
        """读末 N 条 cold_start record (最近优先)."""
        try:
            if not os.path.exists(self._COLD_STARTS_PATH):
                return []
            with open(self._COLD_STARTS_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            recs = []
            for ln in lines[-max_n * 2:]:  # 略多读防 broken line
                try:
                    recs.append(json.loads(ln.strip()))
                except Exception:
                    continue
            recs.sort(key=lambda r: -float(r.get('ts', 0)))
            return recs[:max_n]
        except Exception:
            return []

    def _load_yesterday_recap(self) -> Optional[dict]:
        """读末行 yesterday recap (1 day cache mtime)."""
        now = time.time()
        if (self._yesterday_recap_cached is not None and
                now - self._yesterday_recap_last_check_ts < 3600):
            return self._yesterday_recap_cached
        self._yesterday_recap_last_check_ts = now
        try:
            if not os.path.exists(self._YESTERDAY_RECAP_PATH):
                self._yesterday_recap_cached = None
                return None
            with open(self._YESTERDAY_RECAP_PATH, 'r',
                       encoding='utf-8') as f:
                lines = f.readlines()
            if not lines:
                return None
            self._yesterday_recap_cached = json.loads(lines[-1].strip())
            return self._yesterday_recap_cached
        except Exception:
            return None

    def _get_today_turn_count(self) -> int:
        """从 nerve.self_anchor.get_turn_count 拿主聊 turn 数 (跨日不 reset, 但
        和 process_start 比对就能算今日 delta).
        """
        try:
            if self.nerve and hasattr(self.nerve, 'self_anchor'):
                sa = self.nerve.self_anchor
                if sa and hasattr(sa, 'get_turn_count'):
                    return int(sa.get_turn_count())
        except Exception:
            pass
        return 0

    def _get_today_thought_count(self) -> int:
        """跨日 reset thought count. 今日 0 点为界."""
        today = time.strftime('%Y-%m-%d')
        if today != self._today_date:
            self._today_date = today
            self._today_thought_count = 0
        return self._today_thought_count

    def _format_age_human(self, ts: float) -> str:
        age_s = max(0, int(time.time() - ts))
        if age_s < 60: return f"{age_s}s"
        if age_s < 3600: return f"{age_s // 60}min"
        if age_s < 86400: return f"{age_s // 3600}h"
        return f"{age_s // 86400}d"

    def build_lifetime_block(self, mode: str = 'full',
                                max_chars: Optional[int] = None) -> str:
        """🆕 [Sir 2026-05-27 01:00 β.5.50] 主脑 + daemon 复用的 lifetime block.

        Sir 真意 "全面时间感知 / 知道几分钟前在想啥几小时前在做啥".
        7 维 (按 mode):
          1. process uptime (alive since)
          2. cross-session (跨 cold_start 历史)
          3. today counters (turns + thoughts)
          4. recent thoughts (15min 时序)
          5. recent actions (2h SWM tool_called / proposal events)
          6. hour pattern (M2 — Sir typical at this hour)
          7. yesterday recap (LLM 写, jsonl 持久)

        mode='mini' for daemon / FACTUAL_RECALL / WAKE_ONLY (省 token)
        mode='full' for SHORT_CHAT / DEEP_QUERY (主聊用全)
        mode='off' → 返 ''
        """
        if mode == 'off':
            return ''
        vocab = self._load_lifetime_vocab()
        limits = (vocab.get('mode_limits') or {}).get(mode) or \
                  self._LIFETIME_DEFAULT_VOCAB['mode_limits'].get(mode, {})
        if max_chars is None:
            max_chars = int(limits.get('max_chars', 600))
        rt_n = int(limits.get('recent_thoughts_n', 3))
        ra_n = int(limits.get('recent_actions_n', 3))

        lines = ["=== JARVIS LIFETIME — you are ONE continuous entity ==="]

        # (1) Process uptime
        try:
            up_s = int(time.time() - self._process_start_ts)
            up_str = self._format_age_human(self._process_start_ts)
            start_clock = time.strftime(
                '%H:%M %a', time.localtime(self._process_start_ts)
            )
            lines.append(
                f"- Alive: {up_str} since {start_clock} "
                f"(this process incarnation)"
            )
        except Exception:
            pass

        # (2) Cross-session (跨 cold_start)
        try:
            recs = self._load_cold_starts(
                int(vocab.get('cross_session_max_records', 12))
            )
            if recs and len(recs) >= 2:
                # recs[0] 是 self (本次), recs[1:] 是历史
                hist = recs[1:]
                if hist:
                    # 计算 span
                    oldest_ts = float(hist[-1].get('ts', 0))
                    span_s = int(time.time() - oldest_ts) if oldest_ts > 0 else 0
                    span_human = (f"{span_s // 86400}d"
                                    if span_s >= 86400
                                    else f"{span_s // 3600}h")
                    lines.append(
                        f"- Cross-session: {len(recs)} cold-starts "
                        f"over {span_human} (same Jarvis identity, "
                        f"multiple process restarts)"
                    )
        except Exception:
            pass

        # (3) Today counters
        try:
            turn_n = self._get_today_turn_count()
            thought_n_today = self._get_today_thought_count()
            lifetime_thoughts = len(self._thoughts)
            lines.append(
                f"- Today so far: {turn_n} main turns | "
                f"{thought_n_today} new inner thoughts "
                f"({lifetime_thoughts} in last 24h window)"
            )
        except Exception:
            pass

        # (4) Recent thoughts (时序, 不按 salience)
        try:
            lookback_s = int(vocab.get('recent_thoughts_lookback_s', 900))
            cutoff = time.time() - lookback_s
            with self._lock:
                recent_t = sorted(
                    [t for t in self._thoughts if t.ts > cutoff],
                    key=lambda x: -x.ts,
                )[:rt_n]
            if recent_t:
                lines.append(
                    f"- Last {lookback_s // 60}min you thought "
                    f"({len(recent_t)} thoughts, time-ordered):"
                )
                for t in reversed(recent_t):  # 旧→新让 narrative
                    age = self._format_age_human(t.ts)
                    tid_short = (
                        getattr(t, 'thread_id', '') or t.id
                    )[:10]
                    cont = getattr(t, 'continuity', 'new_topic')
                    cont_mark = '🔗' if cont == 'same_thread' else '✨'
                    act_str = ''
                    if t.actionable and t.actionable != 'none':
                        if t.actionable_done is False:
                            act_str = ' ❌'
                        elif t.actionable_done is True:
                            act_str = ' ✓'
                        else:
                            act_str = ' →pending'
                    lines.append(
                        f"    [{age} ago] {cont_mark} cat={t.category} "
                        f"sal={t.salience:.2f} t={tid_short}: "
                        f"\"{t.thought[:90]}\"{act_str}"
                    )
        except Exception:
            pass

        # (5) Recent actions (SWM tool_called / surface / propose 等)
        try:
            from jarvis_utils import get_event_bus as _geb_la
            bus = _geb_la()
            if bus is not None:
                lookback_s = int(vocab.get('recent_actions_lookback_s', 7200))
                top = bus.top_n(n=40) or []
                action_types = (
                    'tool_called', 'inner_thought_tool_called',
                    'inner_thought_surface', 'propose_protocol_activated',
                    'reminder_fired', 'commitment_fulfilled',
                    'commitment_cancelled', 'stand_down_set',
                )
                acts = []
                for ev in top:
                    if ev.get('type') not in action_types:
                        continue
                    age_raw = ev.get('_age_s', 999999)
                    age_s = float(age_raw if age_raw is not None
                                   else 999999)
                    if age_s > lookback_s:
                        continue
                    desc = str(ev.get('description', '') or '')[:80]
                    acts.append({
                        'type': ev.get('type'),
                        'age_s': int(age_s),
                        'desc': desc,
                    })
                acts.sort(key=lambda a: a['age_s'])
                if acts:
                    lines.append(
                        f"- Last {lookback_s // 3600}h you DID "
                        f"({min(len(acts), ra_n)} actions, time-ordered):"
                    )
                    for a in acts[:ra_n]:
                        age = (f"{a['age_s']}s" if a['age_s'] < 60 else
                                  f"{a['age_s'] // 60}min")
                        lines.append(
                            f"    [{age} ago] {a['type']}"
                            f"{(': ' + a['desc']) if a['desc'] else ''}"
                        )
        except Exception:
            pass

        # (6) This hour Sir typical (M2 TimeAwareness)
        try:
            from jarvis_time_awareness import get_pattern_at_now as _gpan
            tp = _gpan()
            if tp and tp.get('has_data'):
                acts = ', '.join((tp.get('typical_activities') or [])[:3])
                if acts:
                    freq = tp.get('frequency', 0)
                    lines.append(
                        f"- This hour ({tp.get('hour')}:00) Sir typically: "
                        f"{acts} ({freq:.0%} conf, "
                        f"{tp.get('sample_count', 0)} samples)"
                    )
        except Exception:
            pass

        # (7) Yesterday recap (jsonl 末行)
        try:
            rec = self._load_yesterday_recap()
            if rec:
                date = rec.get('date', '?')
                narr = (rec.get('narrative') or '')[:160]
                if narr:
                    lines.append(
                        f"- Yesterday ({date}): {narr}"
                    )
        except Exception:
            pass

        # Closing self-awareness directive
        lines.append(
            "  ⚠️ Use this lifetime view: pick up threads Sir started "
            "earlier, honor what you DID (don't re-propose), respect "
            "Sir's typical pattern when choosing tone/urgency."
        )

        block = '\n'.join(lines)
        if len(block) > max_chars:
            block = block[:max_chars - 14].rstrip() + '\n…[truncated]'
        return block

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-27 01:00 β.5.50] yesterday_recap sub-reflector
    # ----------------------------------------------------------
    # 复用 daemon LLM call 路径 (Flash-Lite caller='inner_thought' LOW),
    # 不抽独立 daemon. 内 23h cooldown + hour==23 窗口.
    # 写 memory_pool/jarvis_yesterday_recap.jsonl (每天 append 1 行).
    # 准则 6: 配置全 vocab JSON, narrative LLM 生不模板.
    # ----------------------------------------------------------
    def _maybe_write_yesterday_recap(self) -> None:
        """check + 写 yesterday recap. tick 后调, 多次 check 多次 cooldown 守."""
        vocab = self._load_lifetime_vocab()
        if not bool(vocab.get('yesterday_recap_enabled', True)):
            return
        target_hour = int(vocab.get('yesterday_recap_hour', 23))
        cooldown_s = float(vocab.get('yesterday_recap_cooldown_s', 82800))
        now = time.time()
        # 5min 内不重复 check (省 io)
        if now - self._yesterday_recap_last_check_ts < 300:
            return
        self._yesterday_recap_last_check_ts = now
        # 时间窗 check (only hour == target_hour ± 1)
        cur_hour = int(time.strftime('%H'))
        if cur_hour not in (target_hour, target_hour + 1):
            return
        # cooldown check (jsonl 末行 ts)
        try:
            rec = self._load_yesterday_recap()
            if rec:
                last_ts = float(rec.get('ts', 0))
                if now - last_ts < cooldown_s:
                    return
        except Exception:
            pass
        # 真去写
        try:
            self._do_write_yesterday_recap()
        except Exception as e:
            self._bg_log(
                f"⚠️ [YesterdayRecap] write exception: {e}"
            )

    def _do_write_yesterday_recap(self) -> None:
        """LLM 写 yesterday narrative + persist."""
        from datetime import datetime, timedelta
        # 算 yesterday 的 ymd
        yest = datetime.now() - timedelta(days=1)
        yest_date = yest.strftime('%Y-%m-%d')
        # 收 yesterday 数据: 主聊 turn count / 内省 thought count / 主 action
        yest_start_ts = time.mktime(yest.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timetuple())
        yest_end_ts = yest_start_ts + 86400
        # thoughts in yesterday
        with self._lock:
            yest_thoughts = [
                t for t in self._thoughts
                if yest_start_ts <= t.ts < yest_end_ts
            ]
        # 主 action via SWM
        actions_summary = []
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                top = bus.top_n(n=200) or []
                act_types = ('tool_called', 'inner_thought_surface',
                              'propose_protocol_activated',
                              'reminder_fired')
                for ev in top:
                    if ev.get('type') not in act_types:
                        continue
                    age_s = float(ev.get('_age_s', 999999))
                    ev_ts = time.time() - age_s
                    if yest_start_ts <= ev_ts < yest_end_ts:
                        actions_summary.append(ev.get('type'))
        except Exception:
            pass
        from collections import Counter
        act_counter = Counter(actions_summary)
        # 拼 evidence 给 LLM
        evidence_lines = [
            f"Yesterday: {yest_date} (day before today)",
            f"Inner thoughts: {len(yest_thoughts)} total",
        ]
        if yest_thoughts:
            cats = Counter(t.category for t in yest_thoughts)
            evidence_lines.append(
                f"  by category: {dict(cats)}"
            )
            # top 3 by salience
            top_t = sorted(yest_thoughts,
                              key=lambda t: -t.salience)[:3]
            for t in top_t:
                evidence_lines.append(
                    f"  - [{t.category} sal={t.salience:.2f}] "
                    f"{t.thought[:80]}"
                )
        if act_counter:
            evidence_lines.append(
                f"Actions: {dict(act_counter)}"
            )
        if not yest_thoughts and not actions_summary:
            # 无数据 → 写 minimal recap
            narrative = "no notable activity recorded"
        else:
            # LLM 写 1-2 句 narrative
            try:
                narrative = self._llm_write_yesterday_narrative(
                    yest_date, evidence_lines
                )
            except Exception:
                narrative = (
                    f"{len(yest_thoughts)} inner thoughts, "
                    f"{sum(act_counter.values())} actions"
                )
        # persist
        record = {
            'date': yest_date,
            'ts': time.time(),
            'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                       time.localtime()),
            'narrative': narrative[:300],
            'thought_count': len(yest_thoughts),
            'action_count': sum(act_counter.values()),
        }
        os.makedirs(os.path.dirname(self._YESTERDAY_RECAP_PATH),
                       exist_ok=True)
        with open(self._YESTERDAY_RECAP_PATH, 'a',
                   encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        # invalidate cache
        self._yesterday_recap_cached = None
        self._yesterday_recap_last_written_ts = time.time()
        self._bg_log(
            f"💭 [YesterdayRecap] wrote recap for {yest_date}: "
            f"\"{narrative[:80]}...\""
        )

    def _llm_write_yesterday_narrative(
        self, date: str, evidence_lines: List[str]
    ) -> str:
        """复用 daemon 现有 _call_llm 路径 (LlmReflector + CALLER_INNER_THOUGHT)."""
        if not self.key_router:
            return f"{len(evidence_lines)} signals recorded"
        system_prompt = (
            "You are Jarvis, a continuous AI butler entity. Write 1-2 "
            "short third-person sentences summarizing yesterday from your "
            "own perspective (you are the observer + participant). English "
            "only, under 160 chars total. Do NOT use 'Sir' more than once. "
            "Focus on what was notable, not template phrases."
        )
        user_prompt = (
            f"Yesterday's evidence ({date}):\n"
            + '\n'.join(evidence_lines)
            + "\n\nYour narrative (1-2 sentences, butler tone):"
        )
        try:
            txt = (self._call_llm(system_prompt, user_prompt) or '').strip()
            # 清 markdown / prefix
            for prefix in ('Narrative:', '"', '*', '- '):
                if txt.startswith(prefix):
                    txt = txt[len(prefix):].strip()
            return txt[:200] or "no narrative generated"
        except Exception:
            return "(LLM unavailable)"

    # ----------------------------------------------------------
    # Stats (for CLI dump / dashboard)
    # ----------------------------------------------------------
    def get_stats(self) -> dict:
        with self._lock:
            return {
                'tick_count': self._tick_count,
                'thought_count': self._thought_count,
                'cooldown_skip_count': self._cooldown_skip_count,
                'llm_fail_count': self._llm_fail_count,
                'loaded_thoughts_24h': len(self._thoughts),
                'last_category_ts': dict(self._last_category_ts),
                'current_sir_state': self._classify_sir_state(),
                'current_interval_s': self._compute_adaptive_interval(),
                # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] LLM self-pacing 状态
                # next_tick_interval_s: LLM 真选了的下次 interval (0 = 用 baseline)
                # tick_origin_stats: 累积 tick 来源分布 (Sir 看 LLM 真在 self-pace 还是默认)
                'next_tick_interval_s': self._next_tick_interval_s,
                'tick_origin_stats': dict(self._tick_origin_stats),
            }

    def list_recent_thoughts(self, max_n: int = 20) -> List[dict]:
        with self._lock:
            recent = sorted(self._thoughts, key=lambda t: -t.ts)[:max_n]
        return [asdict(t) for t in recent]

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 D 治本] outcome 闭环 API
    # ----------------------------------------------------------
    def record_outcome(self, thought_id: str, outcome: str) -> bool:
        """OutcomeWatch worker 调 — 写 thought.outcome 字段 + persist.

        Sir 真痛: outcome 字段就位但没人写 → thought 不知 Sir 关心不关心.
        D 闭环: chat_bypass post-reply 检 detection → 调本 API 持久化.

        Args:
          thought_id: target InnerThought.id
          outcome: 'sir_engaged' | 'sir_silenced' | 'sir_rejected' |
                    'jarvis_referenced_no_reaction' | 'no_signal'

        Returns: True 真改写; False 未找到 thought.
        """
        if not thought_id or not outcome:
            return False
        with self._lock:
            target = None
            for t in self._thoughts:
                if t.id == thought_id:
                    target = t
                    break
            if target is None:
                return False
            target.outcome = outcome[:60]
        # 持久化 (append 一条 outcome update 行到 jsonl, 老 thought 不动)
        try:
            os.makedirs(os.path.dirname(self.PERSIST_PATH), exist_ok=True)
            update_row = {
                '_outcome_update': True,
                'thought_id': thought_id,
                'outcome': outcome,
                'ts': time.time(),
                'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            }
            with open(self.PERSIST_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(update_row, ensure_ascii=False) + '\n')
        except Exception:
            pass
        try:
            self._bg_log(
                f"💭 [Outcome] thought {thought_id[:30]} → {outcome}"
            )
        except Exception:
            pass
        return True

    # ----------------------------------------------------------
    # bg_log helper (lazy import to avoid circular)
    # ----------------------------------------------------------
    def _bg_log(self, msg: str) -> None:
        try:
            from jarvis_utils import bg_log
            bg_log(msg)
        except Exception:
            pass


# ==========================================================================
# Module-level singleton (optional, for ad-hoc access)
# ==========================================================================
_DEFAULT_DAEMON: Optional[InnerThoughtDaemon] = None


def get_default_daemon() -> Optional[InnerThoughtDaemon]:
    return _DEFAULT_DAEMON


def set_default_daemon(d: InnerThoughtDaemon) -> None:
    global _DEFAULT_DAEMON
    _DEFAULT_DAEMON = d
