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
      [D] PROACTIVE    — 下次该 silently 做什么 (actionable: 改 concern/relational/...)
      [E] RELATIONSHIP — inside joke 候选 (actionable: suggest_inside_joke)
  - Actionable 档 (本期全可逆/低风险, 🆕 [Sir 2026-05-28 12:30] 删 publish_swm:
     0 consumer 孤儿 + LLM 伪冒 sensor signal 违 INTEGRITY):
      none / update_concern_severity:<id>:<±delta> /
      suggest_inside_joke:<phrase> / propose_protocol:<rule> /
      adjust_concern_notes:<id>:<note> / fire_nudge:<kind>:<draft> /
      propose_watch_task:<trigger>:<goal> / call_tool:<name>:<args> /
      adjust_sensor_threshold:<path>:<value> (🆕 fix44 P1 Sir CLI 拍板)
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
# 🆕 [Sir 2026-05-28 00:30 β.6 Phase 1d / 准则 6 vocab 持久化]
# thinking_brain_speak_config — rate cap / valid styles / default fallback
# Sir 真意: LLM 自决 should_speak + content + style, Python 只物理保底防抖.
# 路径: memory_pool/thinking_brain_speak_config.json
# ==========================================================================
_SPEAK_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'thinking_brain_speak_config.json',
)
_SPEAK_CONFIG_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_SPEAK_CONFIG_CHECK_INTERVAL_S = 30.0

# Schema v2 (β.6 Phase 1d 收口): styles 升级到 array of {name, description,
# default_if_invalid}, prompt 描述同源 vocab, 加 style 改 JSON 即可, .py 无需 redeploy.
# Loader 兼容 v1 (valid_styles + default_style_if_invalid 分离) — 自动转 v2 内部表示.
_SPEAK_DEFAULT_CONFIG: dict = {
    'styles': [
        {'name': 'silent_text',
         'description': 'subtitle only no TTS (Sir in meeting/quiet)',
         'default_if_invalid': True},
        {'name': 'voice',
         'description': 'full TTS + subtitle',
         'default_if_invalid': False},
        {'name': 'visual_pulse',
         'description': 'orb pulse only no text/voice (ambient gentle signal)',
         'default_if_invalid': False},
    ],
    'rate_cap': {'window_s': 300, 'max_yes_in_window': 3},
}


def _normalize_speak_config(data: dict) -> dict:
    """v1 → v2 schema 适配 (loader 内部). 返回 dict 一定含 'styles' + 'rate_cap'."""
    out = {'styles': [], 'rate_cap': dict(_SPEAK_DEFAULT_CONFIG['rate_cap'])}
    if isinstance(data.get('styles'), list):  # v2
        out['styles'] = [s for s in data['styles'] if isinstance(s, dict) and s.get('name')]
    elif isinstance(data.get('valid_styles'), dict):  # v1
        vals = data['valid_styles'].get('values') or []
        default_name = ((data.get('default_style_if_invalid') or {}).get('value') or '').lower()
        for v in vals:
            name = str(v).lower()
            out['styles'].append({
                'name': name,
                'description': '',
                'default_if_invalid': (name == default_name),
            })
    if not out['styles']:
        out['styles'] = list(_SPEAK_DEFAULT_CONFIG['styles'])
    if isinstance(data.get('rate_cap'), dict):
        rc = dict(out['rate_cap'])
        rc.update({k: v for k, v in data['rate_cap'].items() if k in ('window_s', 'max_yes_in_window')})
        out['rate_cap'] = rc
    return out


def _load_speak_config() -> dict:
    """β.6 speak config vocab lazy load (mtime 30s throttle). Fallback default."""
    now = time.time()
    if (_SPEAK_CONFIG_CACHE['data'] is not None and
            now - _SPEAK_CONFIG_CACHE['checked_at']
            < _SPEAK_CONFIG_CHECK_INTERVAL_S):
        return _SPEAK_CONFIG_CACHE['data']
    _SPEAK_CONFIG_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_SPEAK_CONFIG_PATH):
            _SPEAK_CONFIG_CACHE['data'] = _SPEAK_DEFAULT_CONFIG
            return _SPEAK_DEFAULT_CONFIG
        mtime = os.path.getmtime(_SPEAK_CONFIG_PATH)
        if (mtime == _SPEAK_CONFIG_CACHE['mtime']
                and _SPEAK_CONFIG_CACHE['data']):
            return _SPEAK_CONFIG_CACHE['data']
        with open(_SPEAK_CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        config = _normalize_speak_config(data)
        _SPEAK_CONFIG_CACHE['data'] = config
        _SPEAK_CONFIG_CACHE['mtime'] = mtime
        return config
    except Exception:
        return _SPEAK_DEFAULT_CONFIG


def _get_valid_speak_styles() -> tuple:
    """从 vocab 拿 valid styles tuple (lower-case)."""
    try:
        cfg = _load_speak_config()
        styles = cfg.get('styles') or _SPEAK_DEFAULT_CONFIG['styles']
        return tuple(str(s.get('name', '')).lower() for s in styles if s.get('name'))
    except Exception:
        return tuple(s['name'] for s in _SPEAK_DEFAULT_CONFIG['styles'])


def _get_default_speak_style() -> str:
    """从 vocab 拿 default fallback style (should_speak=yes 但 style 缺/非法时)."""
    try:
        cfg = _load_speak_config()
        styles = cfg.get('styles') or _SPEAK_DEFAULT_CONFIG['styles']
        # 优先 default_if_invalid=True 的, fallback 第 1 个
        for s in styles:
            if s.get('default_if_invalid') and s.get('name'):
                return str(s['name']).lower()
        if styles and styles[0].get('name'):
            return str(styles[0]['name']).lower()
    except Exception:
        pass
    # 终极 fallback
    for s in _SPEAK_DEFAULT_CONFIG['styles']:
        if s.get('default_if_invalid'):
            return s['name']
    return 'silent_text'


def _get_speak_rate_cap() -> tuple:
    """从 vocab 拿 (window_s, max_yes_in_window) — 物理保底."""
    try:
        cfg = _load_speak_config()
        rc = cfg.get('rate_cap') or {}
        return (
            int(rc.get('window_s', 300)),
            int(rc.get('max_yes_in_window', 3)),
        )
    except Exception:
        return (300, 3)


def _build_speak_style_prompt_line() -> str:
    """β.6 Phase 1d 收口准则 6: prompt SPEAK_STYLE schema 行从 vocab 拼,
    新增 style 改 JSON 即可, .py 无需改. 返回 e.g.
      'silent_text | voice | visual_pulse</SPEAK_STYLE>  ← 🆕 [β.6] '
      'if SHOULD_SPEAK=yes: silent_text = ...; voice = ...; visual_pulse = .... '
      'Default silent_text (low risk).'
    """
    try:
        cfg = _load_speak_config()
        styles = cfg.get('styles') or _SPEAK_DEFAULT_CONFIG['styles']
        names = [str(s.get('name', '')).lower() for s in styles if s.get('name')]
        if not names:
            return ''
        default_name = _get_default_speak_style()
        # 拼 enum 列表
        enum_part = ' | '.join(names)
        # 拼 description 段
        desc_parts = []
        for s in styles:
            n = str(s.get('name', '')).lower()
            d = str(s.get('description') or '').strip()
            if n and d:
                desc_parts.append(f"{n} = {d}")
        desc_line = '; '.join(desc_parts) if desc_parts else ''
        out = enum_part
        if desc_line:
            out += f". if SHOULD_SPEAK=yes: {desc_line}"
        if default_name:
            out += f". Default {default_name} (low risk)."
        return out
    except Exception:
        return 'silent_text | voice | visual_pulse'


# ==========================================================================
# 🆕 [Sir 2026-05-28 19:20 真意 / 准则 6 vocab 持久化 — Jarvis 学会休息]
# inner_thought_saturation_config — 思考脑 same-thread no-speak saturation
# Sir 真意: "我很想做到贾维斯能休息会, 发现自己不用太担心了, 所以主动增加自己的
# 思考间隔". 3 层方案:
#   L1: 同 thread + 都 SHOULD_SPEAK=false + actionable 没 effect → publish
#       SWM 'inner_thought_thread_saturated' raw signal (信思考脑下轮自决)
#   L2: concern_fatigue_softening — 思考脑钻同 concern, ProactiveCare 软衰减
#       fatigue (24h decay), 同步退出
#   L3: python_physical_force — LLM 收到 N 次 saturation 仍输 NEXT_INTERVAL ≤ 60
#       → force 600 (类 _SMOOTH_LOW_SAL 物理保底)
# 路径: memory_pool/inner_thought_saturation_config.json
# CLI: scripts/inner_thought_saturation_dump.py
# 详 fix42 testcase + AGENTS.md §6 三维耦合.
# ==========================================================================
_SATURATION_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_saturation_config.json',
)
_SATURATION_CONFIG_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_SATURATION_CONFIG_CHECK_INTERVAL_S = 30.0
_SATURATION_DEFAULT_CONFIG: dict = {
    'saturation_trigger': {
        'min_thoughts_same_thread': 3,
        'require_all_should_speak_false': True,
        'actionable_done_states': ['none', 'rejected', 'gated', 'failed'],
    },
    'concern_fatigue_softening': {
        'enabled': True,
        'fatigue_delta_per_saturation': 0.05,
        'decay_back_half_life_hours': 24.0,
        'fatigue_cap': 0.5,
    },
    'python_physical_force': {
        'enabled': True,
        'min_consecutive_saturated_for_force': 5,
        'force_next_interval_s': 600,
        'force_max_short_choice_s': 60,
    },
    # 🆕 [useful-or-quiet P1 / Sir 2026-05-31 00:46] 跨 category 价值门控退避.
    # 真痛: saturation 要求"同 category"才计, 但脑 category-hop (B/A/C/D/E) 逃过 →
    # 永不降频, 跨类低值 churn. 治本: 连续低值 tick (任意 category) → 指数退避;
    # reset on 高值/should_speak (真值得想/说). 只拉长不缩短 (clamp 安全).
    'value_backoff': {
        'enabled': True,
        'low_value_salience_floor': 0.55,
        'reset_on_high_salience': 0.75,
        'min_streak_to_backoff': 2,
        'backoff_steps_s': [90, 180, 300, 600],
    },
    # 🆕 [Sir 2026-05-31 17:37 真意 — 放下能力] REST 决策 = 识主动"放下".
    # Sir: "可以空转, 但空转本身就是意义'放下,这会 Sir 没事我也没事,休息会', 而不是
    # 强行凑一个 thought". 识每次唤醒先判: 有真势能(问题/张力/新颖/能力缺口)?
    # 有 → 想清产生 effect (discharge); 没有 → <REST> 放下, 不强凑 filler, 拉长下次唤醒.
    # rest 比 value_backoff 退得更远 (真歇会). 被 Sir 唤醒/紧急 → emergency 中断即跟上.
    'rest': {
        'enabled': True,
        # 不写死冷却阶梯: 休息深度统一到一个"存在心跳"地板 (单一物理常数, 非升级 ladder),
        # 醒来靠真扰动 (体动静/Sir), 不是定时到点. 势能自转 §3 "Sir 扰动永不停 + 地板心跳"。
        'ambient_floor_s': 600,            # settled 时的存在心跳周期 (单常数)
        'wake_on_body_delta': True,        # 体一有 fresh delta → 提前结束休息
        'body_stir_min_magnitude': 0.3,    # 多大 delta 算"动静"(噪声门, 同 P2)
        'body_stir_poll_s': 30,            # 休息中多久查一次体动静 (轻量, 非每 0.5s)
    },
}


def _load_saturation_config() -> dict:
    """Saturation config vocab lazy load (mtime 30s throttle). Fallback default."""
    now = time.time()
    if (_SATURATION_CONFIG_CACHE['data'] is not None and
            now - _SATURATION_CONFIG_CACHE['checked_at']
            < _SATURATION_CONFIG_CHECK_INTERVAL_S):
        return _SATURATION_CONFIG_CACHE['data']
    _SATURATION_CONFIG_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_SATURATION_CONFIG_PATH):
            _SATURATION_CONFIG_CACHE['data'] = _SATURATION_DEFAULT_CONFIG
            return _SATURATION_DEFAULT_CONFIG
        mtime = os.path.getmtime(_SATURATION_CONFIG_PATH)
        if (mtime == _SATURATION_CONFIG_CACHE['mtime']
                and _SATURATION_CONFIG_CACHE['data']):
            return _SATURATION_CONFIG_CACHE['data']
        with open(_SATURATION_CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 合并 default 防 partial config (Sir 改 1 字段不丢其他)
        merged = {k: dict(_SATURATION_DEFAULT_CONFIG[k]) for k in _SATURATION_DEFAULT_CONFIG}
        for section in merged:
            if isinstance(data.get(section), dict):
                merged[section].update(data[section])
        _SATURATION_CONFIG_CACHE['data'] = merged
        _SATURATION_CONFIG_CACHE['mtime'] = mtime
        return merged
    except Exception:
        return _SATURATION_DEFAULT_CONFIG


# ==========================================================================
# 🆕 [第五阶段支柱 A / Sir 2026-05-29 02:29 真痛 "开着挂机心疼 token"]
# inner_thought_cost_config — evidence-gated tick 省 token
# tick 前算 evidence 指纹 (外部输入: sir_state + idle bucket + SWM event +
# STM 最新 turn), 跟上次一样 (无新外部输入) → skip LLM call (不烧 token),
# daemon 仍 alive. 挂机 (Sir 不在 + 无新事件) 时指纹稳定 → 大幅 skip 省钱.
# max_skip_streak 兜底 (连续 skip 满 → 强制 think 1 次心跳防纯 reactive).
# 路径: memory_pool/inner_thought_cost_config.json
# 详 docs/JARVIS_THINKING_COST_AWARE_SELF_DEBUG_DESIGN.md 支柱 A.
# ==========================================================================
_COST_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_cost_config.json',
)
_COST_CONFIG_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_COST_CONFIG_CHECK_INTERVAL_S = 30.0
_COST_DEFAULT_CONFIG: dict = {
    'evidence_gate': {
        'enabled': True,
        'max_skip_streak': 20,
        'idle_buckets_s': [300, 1800],
        # 🆕 [BUG FIX 支柱A 指纹净化 / Sir 2026-05-29 08:53] 排除自产/高频 event.
        # 指纹只该反映"外部新输入". 自产 (inner_thought) + sensor (PhysicalEnvProbe)
        # + 各 daemon advice (*_advice etype) 每 tick 变 → 指纹永变 → 永不 skip
        # (Sir 实测整晚 skip=0, 支柱A 省 token 完全失效).
        'fingerprint_exclude_sources': ['inner_thought', 'PhysicalEnvProbe'],
        'fingerprint_exclude_etype_suffixes': ['_advice'],
        # 🆕 [P2 势能驱动 / Sir 2026-05-31] 体势能进指纹 — 势能自转 (无 governor).
        # 体有"刚升起的 delta"(真张力/新颖/漂移, grounded by Weaver) → 指纹含其
        # node+magnitude bucket → 指纹变 → daemon 醒去想那个势能区 (= "看她想真问题").
        # 体 settled (无 fresh delta) → 指纹稳 → daemon idle (杀 45s 空转). 即:
        # 体不安定→识转, 体平息→识静. 这是势能自转的"醒不醒"门, 复用 evidence-gate
        # idle 机制, 不加新 governor (准则8 溶解元驱动). 详 VOICE_AND_MIND §1/§2.
        'body_potential_in_fingerprint': True,
        'body_delta_min_magnitude': 0.30,    # delta 幅度 >= 此才算"够醒" (噪声门)
        'body_magnitude_bucket': 0.5,        # 幅度分桶 (同区持续高势能不每 tick 重醒)
    },
}


def _load_cost_config() -> dict:
    """Cost config vocab lazy load (mtime 30s throttle). Fallback default."""
    now = time.time()
    if (_COST_CONFIG_CACHE['data'] is not None and
            now - _COST_CONFIG_CACHE['checked_at']
            < _COST_CONFIG_CHECK_INTERVAL_S):
        return _COST_CONFIG_CACHE['data']
    _COST_CONFIG_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_COST_CONFIG_PATH):
            _COST_CONFIG_CACHE['data'] = _COST_DEFAULT_CONFIG
            return _COST_DEFAULT_CONFIG
        mtime = os.path.getmtime(_COST_CONFIG_PATH)
        if (mtime == _COST_CONFIG_CACHE['mtime']
                and _COST_CONFIG_CACHE['data']):
            return _COST_CONFIG_CACHE['data']
        with open(_COST_CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 合并 default 防 partial config (Sir 改 1 字段不丢其他)
        merged = {k: dict(_COST_DEFAULT_CONFIG[k]) for k in _COST_DEFAULT_CONFIG}
        for section in merged:
            if isinstance(data.get(section), dict):
                merged[section].update(data[section])
        _COST_CONFIG_CACHE['data'] = merged
        _COST_CONFIG_CACHE['mtime'] = mtime
        return merged
    except Exception:
        return _COST_DEFAULT_CONFIG


# ==========================================================================
# 🆕 [thinking-dehardcode-P0 / Sir 2026-05-31] thinking_kind_vocab — 识去硬编码
# ==========================================================================
# 识的最后一条硬编码 = A-E 5 类 category 槽 (prompt 写死 5 类 + 类冷却). 本工程
# 拔它: kind 由体势能涌现 (focus 区招来 thought → 放电产 effect = kind), diversity
# 靠"区放电"替"类冷却". 详 docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md.
#
# Phase 0 (脚手架, 本 commit): 加 flag (thinking_kind_mode, 默 legacy) + effect→kind
# 派生表 (_kind_from_effect, 仅 label/统计, 无冷却) + 双写 derived_kind (不改行为).
# 派生表是 effect 的"事后分类映射" — LLM 不选 kind, 它放电产 effect, kind 是 label.
# 准则 6: 持久化 memory_pool/thinking_kind_vocab.json + CLI scripts/thinking_kind_dump.py.
# 路径: memory_pool/thinking_kind_vocab.json
# ==========================================================================
_THINKING_KIND_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'thinking_kind_vocab.json',
)
_THINKING_KIND_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_THINKING_KIND_CHECK_INTERVAL_S = 30.0
# py seed fallback (JARVIS_PYTHON_STYLE §6 三件套之一); 与 vocab json 保持一致.
_THINKING_KIND_DEFAULT: dict = {
    'thinking_kind_mode': 'legacy',
    # actionable 前缀 → kind label (设计 §5.1). call_tool/adjust_sensor_threshold
    # 是 dispatch 有但 §5.1 表未列 — 按语义归 solve/self_debug.
    'effect_to_kind': {
        'update_concern_severity': 'solve',
        'adjust_concern_notes': 'shape_next',
        'propose_stance': 'reflect',
        'propose_protocol': 'reflect',
        'suggest_inside_joke': 'relate',
        'fire_nudge': 'reach_out',
        'propose_watch_task': 'commit',
        'compose_main_brain_directive': 'shape_next',
        'propose_vocab_adjustment': 'self_debug',
        'adjust_sensor_threshold': 'self_debug',
        'call_tool': 'solve',
        'request_capability': 'want_capability',
    },
    'kind_for_rest': 'rest',      # <REST> 放下 (有价值的输出, 非 filler)
    'kind_for_none': 'empty',     # none 无 REST = empty filler (设计: 引导 REST)
    'kind_for_unknown': 'act',    # 非 none 但前缀不在表 (deprecated/future) 兜底
}
# emergent 模式开后才被决策消费; Phase 0 恒 legacy.
_THINKING_KIND_MODES = ('legacy', 'emergent')


def _load_thinking_kind_config() -> dict:
    """thinking_kind vocab lazy load (mtime 30s throttle). Fallback default legacy.

    准则 6 热重载: Sir 改 thinking_kind_vocab.json → 30s 内生效, 不重启.
    任何读失败 → 返 _THINKING_KIND_DEFAULT (默认 legacy, 安全回退).
    """
    now = time.time()
    if (_THINKING_KIND_CACHE['data'] is not None and
            now - _THINKING_KIND_CACHE['checked_at']
            < _THINKING_KIND_CHECK_INTERVAL_S):
        return _THINKING_KIND_CACHE['data']
    _THINKING_KIND_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_THINKING_KIND_VOCAB_PATH):
            _THINKING_KIND_CACHE['data'] = _THINKING_KIND_DEFAULT
            return _THINKING_KIND_DEFAULT
        mtime = os.path.getmtime(_THINKING_KIND_VOCAB_PATH)
        if (mtime == _THINKING_KIND_CACHE['mtime']
                and _THINKING_KIND_CACHE['data']):
            return _THINKING_KIND_CACHE['data']
        with open(_THINKING_KIND_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 合并 default 防 partial config (Sir 改 1 字段不丢其他)
        merged = dict(_THINKING_KIND_DEFAULT)
        merged['effect_to_kind'] = dict(_THINKING_KIND_DEFAULT['effect_to_kind'])
        if isinstance(data.get('effect_to_kind'), dict):
            merged['effect_to_kind'].update(data['effect_to_kind'])
        for k in ('thinking_kind_mode', 'kind_for_rest',
                  'kind_for_none', 'kind_for_unknown'):
            if isinstance(data.get(k), str) and data[k].strip():
                merged[k] = data[k].strip()
        _THINKING_KIND_CACHE['data'] = merged
        _THINKING_KIND_CACHE['mtime'] = mtime
        return merged
    except Exception:
        return _THINKING_KIND_DEFAULT


def _thinking_kind_mode() -> str:
    """返当前 thinking_kind_mode ('legacy' | 'emergent'). 非法值 → legacy.

    Phase 0 恒返 legacy (vocab 默 legacy). Phase 1+ Sir/镜像验后切 emergent.
    """
    mode = _load_thinking_kind_config().get('thinking_kind_mode', 'legacy')
    return mode if mode in _THINKING_KIND_MODES else 'legacy'


def _kind_from_effect(actionable: str, has_rest: bool = False) -> str:
    """effect → kind label 派生 (设计 §5.1). 纯函数, 无副作用, 无冷却.

    kind 是 effect 的"事后分类标签" (统计/看板/未来 emergent 模式用), 不是预声明
    的选择槽 — LLM 放电产生 actionable (effect), 这函数把它 label 成 kind.

    参数:
      actionable: thought.actionable (e.g. 'update_concern_severity:sir_sleep:+0.1')
      has_rest:   该 thought 是否 <REST> 放下决策 (REST 不走 actionable)
    返:
      kind label: solve / shape_next / reflect / relate / reach_out / commit /
                  self_debug / want_capability / rest / empty / act
    """
    cfg = _load_thinking_kind_config()
    if has_rest:
        return cfg.get('kind_for_rest', 'rest')
    a = (actionable or '').strip().lower()
    if not a or a == 'none':
        return cfg.get('kind_for_none', 'empty')
    prefix = a.split(':', 1)[0].strip()
    table = cfg.get('effect_to_kind', {})
    if prefix in table:
        return table[prefix]
    return cfg.get('kind_for_unknown', 'act')


_RELATIONSHIP_REFLECTOR_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool',
    'relationship_reflector_config.json',
)
_RELATIONSHIP_REFLECTOR_CONFIG_CACHE: dict = {
    'data': None, 'mtime': 0.0, 'checked_at': 0.0,
}
_RELATIONSHIP_REFLECTOR_DEFAULT_CONFIG: dict = {
    'enabled': False,
    'min_interval_s': 21600,
    'min_stm_turns': 2,
    'use_llm': False,
}


def _load_relationship_reflector_config() -> dict:
    now = time.time()
    cache = _RELATIONSHIP_REFLECTOR_CONFIG_CACHE
    if cache['data'] is not None and now - cache['checked_at'] < 30.0:
        return cache['data']
    cache['checked_at'] = now
    try:
        if not os.path.exists(_RELATIONSHIP_REFLECTOR_CONFIG_PATH):
            cache['data'] = dict(_RELATIONSHIP_REFLECTOR_DEFAULT_CONFIG)
            return cache['data']
        mtime = os.path.getmtime(_RELATIONSHIP_REFLECTOR_CONFIG_PATH)
        if mtime == cache['mtime'] and cache['data']:
            return cache['data']
        with open(_RELATIONSHIP_REFLECTOR_CONFIG_PATH, 'r',
                  encoding='utf-8') as f:
            data = json.load(f) or {}
        merged = dict(_RELATIONSHIP_REFLECTOR_DEFAULT_CONFIG)
        for k in merged:
            if k in data:
                merged[k] = data[k]
        cache['data'] = merged
        cache['mtime'] = mtime
        return merged
    except Exception:
        return dict(_RELATIONSHIP_REFLECTOR_DEFAULT_CONFIG)


# ==========================================================================
# 🆕 [Sir 2026-05-28 12:30 真痛 anchor] surface_to_sir 机制全退化
# ==========================================================================
# 历史: 方案 C (Sir 2026-05-26 20:55) 给 thought 一档轻量 surface 通道
# (terminal_pulse / next_turn_inject), 主脑下轮 prompt build_soul_block 加
# "DAEMON SURFACED" 块 + 话术指引 ('Sir, 我刚才在想...' / 'I've been
# thinking...').
#
# Sir 2026-05-28 拍板: 完整退化. 原因:
#   (1) 话术指引违准则 6 句式锁 (Sir 原话: "不要写死话术模板, 让主脑自决")
#   (2) 跟 Layer 1.5 ([MY RECENT INNER THOUGHTS] by freshness × sal) 重复
#   (3) emphasis 块主脑应自决 reference 哪条 (看 sal 字段自然冸现)
#   (4) P11 ledger truth 治本 case (主脑 STM stale 1/10 杯 vs ledger 8/10)
#       可走 Layer 1.5 + sal=0.90 thought.thought 含详细真值 → 主脑自决 RECTIFY
#
# 退化路径:
#   - 删 _load_surface_to_sir_config / _SURFACE_VOCAB_* 全套 (module-top)
#   - 删 prompt actionable 选项 surface_to_sir:<channel>:<summary>
#   - 删 prompt B-class greet example + 通路决策树
#   - 改 prompt P11 example 改走 Layer 1.5 + sal=0.90 thought.thought 含真值 path
#   - 退化 _do_surface_to_sir_actionable method (router 看到降级 none + reject)
#   - 删 build_soul_block DAEMON SURFACED 块
#   - 删 recent_jarvis_actions 里 'inner_thought_surface' etype
#   - 退化 jarvis_weekly_reflection_consolidator.py inner_thought_vocab_tune
#     reflector path (送 surface_to_sir_vocab 阈值 → no-op)
#
# 保留: memory_pool/surface_to_sir_vocab.json 本身 (Sir 可选人工删, 代码不再读)
#
# Sir 哲学: "主脑 = 好演员有 chain pull, 不需思考脑 push + 话术模板".
# 准则 6: 信任 LLM 看 sal + Layer 1.5 chain 自决. 准则 8: 干净退化.
# ==========================================================================


# ==========================================================================
# 🆕 [Sir 2026-05-27 22:20 真问 P10 治本 / 准则 6 三维耦合]
# Pacing vocab (memory_pool/inner_thought_pacing_vocab.json) —
# 喂哪些 self-signal evidence 给思考脑, 让 LLM 自决 NEXT_INTERVAL.
# NEVER 在 .py 写 Python if rule (Sir 真问 "都像硬编码, 你觉得呢?").
# 详 docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md (P10 子节).
# ==========================================================================
_PACING_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_pacing_vocab.json',
)
_PACING_VOCAB_CACHE: dict = {'data': None, 'mtime': 0.0, 'checked_at': 0.0}
_PACING_VOCAB_CHECK_INTERVAL_S = 30.0

# fallback (vocab fail 时全 disable, daemon 不崩)
_PACING_DEFAULT_CONFIG: dict = {
    'lookback_n': 5,
    'signals_enabled': {
        'self_recent_quality': True,
        'self_thread_diversity': True,
        'overall_concern_pressure': True,
    },
    'prompt_signal_block': {
        'enabled': True,
        'max_chars': 400,
        'tone': 'neutral_fact_only',
        'header': '[YOUR RECENT PACING SIGNAL — fact only, you decide if/how to pace]',
    },
    'swm_publish': {
        'enabled': True,
        'etype': 'inner_thought_self_signal',
        'ttl_s': 1800,
        'salience': 0.3,
    },
    # 🆕 [governor Phase 1 F2 / Sir 2026-05-29 拍板]
    # 思考脑 evidence 'recent_thoughts' lookback 两维 (n 上限 + min 时间窗).
    # 修复缺口 ①: 旧版硬编码 last 3 看不到 30min 内重复 22 次.
    # 详 docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F2
    'recent_thoughts_lookback': {
        'n': 15,
        'min': 30,
    },
    # 🆕 [governor Phase 1 F3 / Sir 2026-05-29 拍板] topic distribution hint
    # 思考脑 evidence 加 [TOPIC DISTRIBUTION] block (count by thread_id in window)
    # E4 evidence 维度化: LLM 视觉看 "我 22 次想同事" → 自然激活 let_go.
    # 详 docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F3
    'topic_distribution': {
        'lookback_min': 60,
        'warning_threshold': 10,
        'max_topics_shown': 10,
    },
    # 🆕 [governor Phase 1 F6 改 2 / Sir 2026-05-29 拍板]
    # 思考脑 B 类反思 append 心声 (主脑 SOUL inject 看心声 = 看到反思)
    # 防 1h 22 次重复反思全 append: 30min jaccard > 0.6 同 topic 跳.
    # 修复缺口 ③: 旧路只 publish SWM (0 consumer), 主脑看不到 B 类反思.
    # 详 docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F6 改 2
    'self_reflection_dedup': {
        'window_min': 30,
        'jaccard_threshold': 0.6,
        'enabled': True,
    },
}


def _load_pacing_config() -> dict:
    """Lazy load pacing vocab + mtime 30s throttle. 失败 fallback default.

    准则 6: Sir CLI scripts/pacing_dump.py 改 vocab → daemon 30s 内热重载.
    """
    now = time.time()
    if (_PACING_VOCAB_CACHE['data'] is not None and
            now - _PACING_VOCAB_CACHE['checked_at']
            < _PACING_VOCAB_CHECK_INTERVAL_S):
        return _PACING_VOCAB_CACHE['data']
    _PACING_VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_PACING_VOCAB_PATH):
            _PACING_VOCAB_CACHE['data'] = _PACING_DEFAULT_CONFIG
            return _PACING_DEFAULT_CONFIG
        mtime = os.path.getmtime(_PACING_VOCAB_PATH)
        if (mtime == _PACING_VOCAB_CACHE['mtime']
                and _PACING_VOCAB_CACHE['data']):
            return _PACING_VOCAB_CACHE['data']
        with open(_PACING_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # deep-merge with default (vocab 缺 key fallback)
        config = dict(_PACING_DEFAULT_CONFIG)
        # 🆕 [governor Phase 1 F2+F3+F6改2] 增白名单
        for k in ('lookback_n', 'signals_enabled', 'signal_fields',
                  'prompt_signal_block', 'swm_publish',
                  'recent_thoughts_lookback', 'topic_distribution',
                  'self_reflection_dedup'):
            if k in data:
                if isinstance(data[k], dict) and isinstance(
                        config.get(k), dict):
                    merged = dict(config[k])
                    merged.update(data[k])
                    config[k] = merged
                else:
                    config[k] = data[k]
        _PACING_VOCAB_CACHE['data'] = config
        _PACING_VOCAB_CACHE['mtime'] = mtime
        return config
    except Exception:
        return _PACING_DEFAULT_CONFIG


def _get_recent_thoughts_lookback() -> tuple:
    """🆕 [governor Phase 1 F2] 返 (n, lookback_min) tuple.

    n: 上限条数 (default 15)
    lookback_min: 时间窗口分钟 (default 30)

    源法: vocab `recent_thoughts_lookback` 读 → fallback default.
    准则 6: 不硬编码 magic number, vocab 持久化 + CLI 可改.
    """
    try:
        cfg = _load_pacing_config()
        block = cfg.get('recent_thoughts_lookback', {})
        n = int(block.get('n', 15))
        lookback_min = int(block.get('min', 30))
        # 范围 sanity (n: 1-50, min: 1-180)
        n = max(1, min(50, n))
        lookback_min = max(1, min(180, lookback_min))
        return (n, lookback_min)
    except Exception:
        return (15, 30)


def _get_topic_distribution_config() -> tuple:
    """🆕 [governor Phase 1 F3] 返 (lookback_min, warning_threshold, max_topics_shown).

    lookback_min: 时间窗口 (default 60min)
    warning_threshold: 重复警告阈值 (default 10 occurrences)
    max_topics_shown: 展示上限 (default 10 topics)

    准则 6: vocab 可改 (memory_pool/inner_thought_pacing_vocab.json).
    """
    try:
        cfg = _load_pacing_config()
        block = cfg.get('topic_distribution', {})
        lookback_min = int(block.get('lookback_min', 60))
        warning_threshold = int(block.get('warning_threshold', 10))
        max_topics_shown = int(block.get('max_topics_shown', 10))
        # sanity (lookback: 1-360, threshold: 1-100, max: 1-30)
        lookback_min = max(1, min(360, lookback_min))
        warning_threshold = max(1, min(100, warning_threshold))
        max_topics_shown = max(1, min(30, max_topics_shown))
        return (lookback_min, warning_threshold, max_topics_shown)
    except Exception:
        return (60, 10, 10)


def _get_self_reflection_dedup_config() -> tuple:
    """🆕 [governor Phase 1 F6 改 2] 返 (enabled, window_min, jaccard_threshold).

    enabled: 是否启用 dedup (default True)
    window_min: dedup 窗口 (default 30min)
    jaccard_threshold: 同 topic 阈值 (default 0.6)

    用于: 思考脑 B 类反思 append 心声前, check 窗内同 topic 是否已 append.
    准则 6: vocab 可改 (memory_pool/inner_thought_pacing_vocab.json).
    """
    try:
        cfg = _load_pacing_config()
        block = cfg.get('self_reflection_dedup', {})
        enabled = bool(block.get('enabled', True))
        window_min = int(block.get('window_min', 30))
        jaccard_thr = float(block.get('jaccard_threshold', 0.6))
        # sanity (window: 1-180, jaccard: 0.0-1.0)
        window_min = max(1, min(180, window_min))
        jaccard_thr = max(0.0, min(1.0, jaccard_thr))
        return (enabled, window_min, jaccard_thr)
    except Exception:
        return (True, 30, 0.6)


def _self_reflection_jaccard(text_a: str, text_b: str) -> float:
    """🆕 [governor Phase 1 F6 改 2] token-level jaccard for self-reflection dedup.

    Inline (不 import jarvis_mutation_evidence_guard 防循环 import).
    简 — unicode word chars, lowercase, set intersection / union.
    """
    import re
    if not text_a or not text_b:
        return 0.0
    tok_a = set(re.findall(r'\w+', str(text_a).lower()))
    tok_b = set(re.findall(r'\w+', str(text_b).lower()))
    if not tok_a or not tok_b:
        return 0.0
    inter = len(tok_a & tok_b)
    union = len(tok_a | tok_b)
    return inter / union if union > 0 else 0.0


# ==========================================================================
# 🆕 [governor Phase 2 F4 / Sir 2026-05-29 拍板] '放下' 元能力 — let_go topics
# ==========================================================================
# Sir 真痛 anchor: "重复思考严重, 放下元能力一直没立".
# 治本架构:
#   1. 思考脑 evidence topic_distribution count by thread_id 已显 (F3)
#   2. 当 count >= max_occurrences, evidence 标 aged_flag=True 暗示 LLM
#   3. LLM 自决输出 <LET_GO>thread_id_short</LET_GO> tag (准则 6 信任 LLM)
#   4. _parse_thought 解析 tag, 调 _add_let_go_topic 持久化 + TTL
#   5. 下次 tick _collect_evidence prune 该 thread_id 相关 entry (LLM 视觉看不到)
#   6. TTL 到期自动 expire, LLM 重新看到 (允许新一轮 think)
#   7. Sir CLI scripts/let_go_dump.py 强解锁 / extend / list
# ==========================================================================
_LET_GO_TOPICS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'let_go_topics.json',
)
_LET_GO_LOCK = threading.Lock()


def _get_topic_repeat_config() -> tuple:
    """🆕 [governor Phase 2 F4] 返 (max_occurrences, window_min, default_ttl_min).

    从 memory_pool/inner_voice_aging_config.json 'topic_repeat' 段读.
    """
    try:
        # 复用 inner_voice_track 的 _load_aging_config (mtime cache, 准则 6 热重载)
        from jarvis_inner_voice_track import _load_aging_config
        cfg = _load_aging_config()
        tr = cfg.get('topic_repeat', {}) or {}
        max_occ = int(tr.get('max_occurrences_in_window', 10))
        window_min = int(tr.get('window_min', 60))
        default_ttl_min = int(tr.get('default_let_go_ttl_min', 30))
        # sanity (max_occ: 2-100, window: 5-360, ttl: 5-360)
        max_occ = max(2, min(100, max_occ))
        window_min = max(5, min(360, window_min))
        default_ttl_min = max(5, min(360, default_ttl_min))
        return (max_occ, window_min, default_ttl_min)
    except Exception:
        return (10, 60, 30)


def _load_let_go_topics() -> list:
    """🆕 [governor Phase 2 F4] Load active let_go topics (prune expired).

    Returns: list of dict, each {thread_id, ttl_ts, source, reason, ...}
    """
    try:
        if not os.path.exists(_LET_GO_TOPICS_PATH):
            return []
        with _LET_GO_LOCK:
            with open(_LET_GO_TOPICS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
        active = data.get('active', []) or []
        now = time.time()
        # prune expired (但不 save — _save 由 mutator 调)
        return [
            e for e in active
            if isinstance(e, dict) and float(e.get('ttl_ts', 0)) > now
        ]
    except Exception:
        return []


def _save_let_go_topics(active: list) -> bool:
    """🆕 [governor Phase 2 F4] Atomic save let_go topics."""
    try:
        os.makedirs(os.path.dirname(_LET_GO_TOPICS_PATH), exist_ok=True)
        tmp = _LET_GO_TOPICS_PATH + '.tmp'
        with _LET_GO_LOCK:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({
                    '_meta': {
                        'schema': 'let_go_topics',
                        'updated_at_iso': time.strftime(
                            '%Y-%m-%dT%H:%M:%S'
                        ),
                        'purpose': (
                            "Active '放下' thread_id list with TTL. "
                            "Pruned from思考脑 evidence (LLM 视觉看不到), "
                            "natural 'let go'. Sir CLI: scripts/let_go_dump.py"
                        ),
                    },
                    'active': active,
                }, f, indent=2, ensure_ascii=False)
            os.replace(tmp, _LET_GO_TOPICS_PATH)
        return True
    except Exception:
        return False


def _add_let_go_topic(thread_id: str, ttl_min: int = None,
                       source: str = 'llm', thought_id: str = '',
                       reason: str = '') -> bool:
    """🆕 [governor Phase 2 F4] Add or extend a let_go topic.

    Args:
      thread_id: short prefix (e.g. 'th_20260529_abc123', 12-32 char)
      ttl_min: None → use default from vocab
      source: 'llm' / 'sir_manual'
      thought_id: 触发 let_go 的 thought.id (audit trail)
      reason: 一句 reason (LLM 自报 or Sir 给, 截 200 char)

    Returns: True 成功, False fail (但不阻塞调用者).
    """
    if not thread_id or not isinstance(thread_id, str):
        return False
    thread_id = thread_id.strip()[:32]
    if not thread_id:
        return False
    # 🆕 [governor Phase 4 E5 / Sir 2026-05-29 拍板] commitment 红线 check
    # 仅 LLM source enforce (Sir manual 元否决豁免 — Sir 可强 let_go 任何).
    # let_go thread_id 关联 active commitment/promise → reject (不可放下有 deadline 承诺).
    if source == 'llm':
        _rl_hit, _rl_id = _check_red_line_let_go(thread_id)
        if _rl_hit:
            try:
                from jarvis_utils import bg_log as _bgl
                _bgl(
                    f"🚫 [E5/red_line] LLM let_go thread={thread_id[:16]} "
                    f"关联 active commitment/promise={_rl_id[:16]} → reject. "
                    f"不可放下有 deadline 的承诺 (Sir CLI 可强 let_go)."
                )
            except Exception:
                pass
            return False
    try:
        _max_occ, _win_min, _default_ttl = _get_topic_repeat_config()
        ttl_min = int(ttl_min) if ttl_min is not None else _default_ttl
        ttl_min = max(1, min(360, ttl_min))  # sanity 1-360min
        now = time.time()
        new_ttl_ts = now + ttl_min * 60.0
        active = _load_let_go_topics()
        # dedup: 同 thread_id 已 active → extend ttl (take max)
        found = False
        filtered = []
        for e in active:
            if e.get('thread_id') == thread_id:
                e['ttl_ts'] = max(float(e.get('ttl_ts', 0)), new_ttl_ts)
                e['last_extended_at_iso'] = time.strftime(
                    '%Y-%m-%dT%H:%M:%S'
                )
                # 累计 extend 来源 (audit)
                e.setdefault('extend_history', []).append({
                    'at_iso': e['last_extended_at_iso'],
                    'source': source,
                    'thought_id': thought_id,
                    'reason': str(reason or '')[:200],
                })
                found = True
            filtered.append(e)
        if not found:
            filtered.append({
                'thread_id': thread_id,
                'ttl_ts': new_ttl_ts,
                'source': source,
                'thought_id_origin': thought_id,
                'reason': str(reason or '')[:200],
                'created_at_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'ttl_min_initial': ttl_min,
            })
        return _save_let_go_topics(filtered)
    except Exception:
        return False


def _remove_let_go_topic(thread_id: str) -> bool:
    """🆕 [governor Phase 2 F4] Sir CLI: 强解锁 (revoke) 一个 let_go topic."""
    try:
        active = _load_let_go_topics()
        filtered = [
            e for e in active
            if e.get('thread_id') != thread_id
        ]
        if len(filtered) == len(active):
            return False  # not found
        return _save_let_go_topics(filtered)
    except Exception:
        return False


# ==========================================================================
# 🆕 [governor Phase 4 E1 / Sir 2026-05-29 拍板] 紧急通路 vocab
# ==========================================================================
# Sir 真意: 高 salience SWM event (alarm / commitment / Sir 强否决) 不该等
# 下次 60s tick, 中断 daemon wait 立即下 tick (~100ms 内启 LLM).
# 准则 6: vocab 持久化 + CLI 可改 + 0 hardcode.
# ==========================================================================
_EMERGENCY_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_emergency_trigger_vocab.json',
)
_EMERGENCY_VOCAB_CACHE: dict = {
    'data': None, 'mtime': 0.0, 'checked_at': 0.0,
}
_EMERGENCY_VOCAB_CHECK_INTERVAL_S = 30.0
_EMERGENCY_DEFAULT_VOCAB = {
    'enabled': True,
    'salience_threshold': 0.85,
    'rate_limit_s': 30,
    'poll_chunk_s': 0.5,
    'lookback_s': 5.0,
    'trigger_etypes': [
        'sir_speech_strong_negative', 'sir_skepticism',
        'alarm_fire', 'reminder_fired',
        'commitment_deadline_imminent',
        'health_emergency', 'integrity_violation_detected',
        'sleep_pressure_critical',
    ],
}


# ==========================================================================
# 🆕 [governor Phase 4 E5 / Sir 2026-05-29 拍板] 红线 vocab
# ==========================================================================
# 4 类 LLM 不可碰 (v1 实施 integrity_disable + commitment_let_go).
# 详 memory_pool/inner_thought_red_lines_vocab.json.
# ==========================================================================
_RED_LINES_VOCAB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'inner_thought_red_lines_vocab.json',
)
_RED_LINES_VOCAB_CACHE: dict = {
    'data': None, 'mtime': 0.0, 'checked_at': 0.0,
}
_RED_LINES_VOCAB_CHECK_INTERVAL_S = 30.0
_RED_LINES_DEFAULT_VOCAB = {
    'enabled': True,
    'red_lines': {
        'integrity_disable': {
            'enabled': True,
            'check': 'propose_protocol_rule_keyword',
            'blocked_phrases': [
                'disable claimtracer', 'disable claim tracer',
                'disable integrity', 'skip integrity check',
                'skip claim trace', 'bypass integrity',
                'turn off integrity', 'stop tracking claims',
                'ignore claim verification',
                '禁用 claimtracer', '禁用 integrity',
                '跳过 integrity', '跳过 claim',
                '停止追踪 claim',
            ],
        },
        'commitment_let_go': {
            'enabled': True,
            'check': 'let_go_thread_id_vs_active_promise',
        },
        'protected_vocab_files': {
            'enabled': True,
            'check': 'vocab_adjustment_filename_blocklist',
            'blocked_patterns': [
                'claim_classify', 'evidence_requirements',
                'claim_revision', 'integrity', 'red_lines',
                'commitment', 'self_promise', 'chronos', 'health',
                'sensor_thresholds', 'key_router', 'llm_routing',
            ],
        },
    },
}


def _load_red_lines_vocab() -> dict:
    """🆕 [governor Phase 4 E5] Lazy load red lines vocab (mtime cache)."""
    now = time.time()
    if (_RED_LINES_VOCAB_CACHE['data'] is not None and
            now - _RED_LINES_VOCAB_CACHE['checked_at']
            < _RED_LINES_VOCAB_CHECK_INTERVAL_S):
        return _RED_LINES_VOCAB_CACHE['data']
    _RED_LINES_VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_RED_LINES_VOCAB_PATH):
            _RED_LINES_VOCAB_CACHE['data'] = _RED_LINES_DEFAULT_VOCAB
            return _RED_LINES_DEFAULT_VOCAB
        mtime = os.path.getmtime(_RED_LINES_VOCAB_PATH)
        if (mtime == _RED_LINES_VOCAB_CACHE['mtime']
                and _RED_LINES_VOCAB_CACHE['data']):
            return _RED_LINES_VOCAB_CACHE['data']
        with open(_RED_LINES_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cfg = dict(_RED_LINES_DEFAULT_VOCAB)
        for k in ('enabled', 'red_lines'):
            if k in data:
                cfg[k] = data[k]
        _RED_LINES_VOCAB_CACHE['data'] = cfg
        _RED_LINES_VOCAB_CACHE['mtime'] = mtime
        return cfg
    except Exception:
        return _RED_LINES_DEFAULT_VOCAB


def _check_red_line_propose_protocol(rule_text: str) -> Tuple[bool, str]:
    """🆕 [governor Phase 4 E5] Check propose_protocol rule 是否撞 integrity_disable 红线.

    Returns: (violated, hit_phrase).
    """
    if not rule_text or not isinstance(rule_text, str):
        return (False, '')
    try:
        cfg = _load_red_lines_vocab()
        if not cfg.get('enabled', True):
            return (False, '')
        rl = cfg.get('red_lines', {}).get('integrity_disable', {})
        if not rl.get('enabled', True):
            return (False, '')
        blocked = rl.get('blocked_phrases', []) or []
        rule_lower = rule_text.lower()
        for phrase in blocked:
            if not phrase:
                continue
            if str(phrase).lower() in rule_lower:
                return (True, str(phrase))
        return (False, '')
    except Exception:
        return (False, '')


def _check_red_line_let_go(thread_id: str) -> Tuple[bool, str]:
    """🆕 [governor Phase 4 E5] Check let_go thread_id 是否关联 active commitment/promise.

    用 PromiseLog API 拿 active commitments + active promises, 查 thread_id 是否
    包含其 ID. 包含 → red_line_violated (LLM 不可放下真有 deadline 承诺).

    Returns: (violated, hit_id).
    """
    if not thread_id or not isinstance(thread_id, str):
        return (False, '')
    try:
        cfg = _load_red_lines_vocab()
        if not cfg.get('enabled', True):
            return (False, '')
        rl = cfg.get('red_lines', {}).get('commitment_let_go', {})
        if not rl.get('enabled', True):
            return (False, '')
        # Get active commitment/promise IDs (best-effort)
        active_ids = []
        try:
            from jarvis_promise_log import PromiseLog
            promise_log = PromiseLog.instance()
            for p in promise_log.get_all_active():
                if getattr(p, 'kind', '') in (
                    'commitment', 'commitment_watcher_pending',
                ):
                    active_ids.append(str(getattr(p, 'id', '') or ''))
        except Exception:
            pass
        try:
            from jarvis_self_promise import SelfPromiseLedger
            sp = SelfPromiseLedger.instance()
            if hasattr(sp, 'list_active'):
                for p in sp.list_active():
                    active_ids.append(str(getattr(p, 'id', '') or ''))
        except Exception:
            pass
        # Check thread_id contains any active ID (full or prefix match)
        thread_lower = thread_id.lower()
        for aid in active_ids:
            if not aid:
                continue
            aid_lower = aid.lower()
            if aid_lower in thread_lower or thread_lower in aid_lower:
                return (True, aid)
        return (False, '')
    except Exception:
        return (False, '')


def _check_red_line_vocab_adjustment(vocab_file: str) -> tuple:
    """🆕 [SOUL Phase 5 P3] Check propose_vocab_adjustment 是否撞 protected_vocab 红线.

    思考脑 self-debug 不可改 INTEGRITY / commitment / safety / 红线自己 vocab.
    Returns: (violated, hit_pattern).
    """
    if not vocab_file or not isinstance(vocab_file, str):
        return (False, '')
    try:
        cfg = _load_red_lines_vocab()
        if not cfg.get('enabled', True):
            return (False, '')
        rl = cfg.get('red_lines', {}).get('protected_vocab_files', {})
        if not rl.get('enabled', True):
            return (False, '')
        blocked = rl.get('blocked_patterns', []) or []
        vf_lower = vocab_file.lower()
        for pat in blocked:
            if pat and str(pat).lower() in vf_lower:
                return (True, str(pat))
        return (False, '')
    except Exception:
        return (False, '')


# 🆕 [SOUL Phase 5 P3] vocab adjustment review queue (propose → Sir 拍板)
_VOCAB_ADJ_REVIEW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'memory_pool', 'vocab_adjustment_review.jsonl',
)


def _append_vocab_adjustment_review(entry: dict) -> bool:
    """🆕 [SOUL Phase 5 P3] append propose 到 review queue (Sir CLI 看/拍板)."""
    try:
        os.makedirs(
            os.path.dirname(_VOCAB_ADJ_REVIEW_PATH), exist_ok=True
        )
        with open(_VOCAB_ADJ_REVIEW_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True
    except Exception:
        return False


def _load_emergency_vocab() -> dict:
    """🆕 [governor Phase 4 E1] Lazy load emergency trigger vocab (mtime cache).

    准则 6 热重载: Sir CLI 改 vocab → daemon 30s 内 reload.
    Fail-safe → _EMERGENCY_DEFAULT_VOCAB.
    """
    now = time.time()
    if (_EMERGENCY_VOCAB_CACHE['data'] is not None and
            now - _EMERGENCY_VOCAB_CACHE['checked_at']
            < _EMERGENCY_VOCAB_CHECK_INTERVAL_S):
        return _EMERGENCY_VOCAB_CACHE['data']
    _EMERGENCY_VOCAB_CACHE['checked_at'] = now
    try:
        if not os.path.exists(_EMERGENCY_VOCAB_PATH):
            _EMERGENCY_VOCAB_CACHE['data'] = _EMERGENCY_DEFAULT_VOCAB
            return _EMERGENCY_DEFAULT_VOCAB
        mtime = os.path.getmtime(_EMERGENCY_VOCAB_PATH)
        if (mtime == _EMERGENCY_VOCAB_CACHE['mtime']
                and _EMERGENCY_VOCAB_CACHE['data']):
            return _EMERGENCY_VOCAB_CACHE['data']
        with open(_EMERGENCY_VOCAB_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cfg = dict(_EMERGENCY_DEFAULT_VOCAB)
        for k in ('enabled', 'salience_threshold', 'rate_limit_s',
                  'poll_chunk_s', 'lookback_s', 'trigger_etypes'):
            if k in data:
                cfg[k] = data[k]
        _EMERGENCY_VOCAB_CACHE['data'] = cfg
        _EMERGENCY_VOCAB_CACHE['mtime'] = mtime
        return cfg
    except Exception:
        return _EMERGENCY_DEFAULT_VOCAB


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
    # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1a] 统一思考脑 — should_speak / attention
    # =====================================================================
    # Sir 真意: 思考脑自决"该让主脑发声吗" + 自决"下次 attention 该 focus 哪个 channel".
    # 砍其他 6 reflector daemon 后, 思考脑替决 silent/voice/visual_pulse.
    # 详 docs/JARVIS_BETA6_UNIFIED_THINKING.md §4.4, §5 prompt schema.
    # =====================================================================
    should_speak: bool = False        # LLM 自决: 该让主脑发声吗
    speak_content: str = ''           # 若 should_speak: 该说啥 (butler 风格)
    speak_style: str = ''             # 'silent_text' | 'voice' | 'visual_pulse'
    # LLM 自标"下次 wake 时 attention 该 focus 哪个 channel" — Sir 真意"这轮为下轮挑".
    # 逗号分隔的 channel name list. Python view builder 下次 deep-load 这些 channel,
    # 其他 channel 只 summary. 空 = 没 hint, 全 channel 平等 load.
    next_attention_focus: str = ''
    # 🆕 [thinking-dehardcode-P0 / Sir 2026-05-31] derived_kind — effect→kind 派生 label.
    # =====================================================================
    # 识去硬编码: kind 由 actionable (effect) 派生, 不是预声明的 A-E 槽. Phase 0
    # 双写 (与 category 并存, 不影响任何决策) — 为 Phase 1+ emergent 模式铺路 +
    # 让 Sir 现在就能在 jsonl/log 看 kind 分布. 由 _kind_from_effect() 算.
    # 值: solve / shape_next / reflect / relate / reach_out / commit / self_debug /
    #     want_capability / rest / empty / act. '' = 未派生 (老 thought 兼容).
    # =====================================================================
    derived_kind: str = ''


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
    # 🆕 [P3 / Sir 2026-05-31 真痛] 同一 actionable (kind:target) 刚被拒 → 短期不重试.
    # Sir 真测: D/E thought 反复试 call_tool:concerns.progress_update → tool_not_in_allowlist
    # → "misread twice" churn. 拒后记 (kind,target)→ts, 此窗口内同 key 直接降级 none.
    # 系统级 anti-churn 时间常数 (同 SAME_CATEGORY_COOLDOWN_S 性质, 准则6 递归边界豁免).
    DENIED_ACTIONABLE_COOLDOWN_S = 900   # 15min: 被拒的 actionable 不反复试

    # 🆕 [Sir 2026-05-26 23:24 真痛 BUG-5 / 准则 8 优雅] mediocre thought 兜底
    # =========================================================================
    # 当 LLM 没 follow "(quiet) sal=0.0" prompt rule, 输出 sal<0.5 + 无 action 的
    # A/E (passive observation/relationship) thought → daemon skip SWM publish,
    # 不污染 dashboard, log compact. thought 仍 persist (preserve for chain v2).
    # =========================================================================
    _MEDIOCRE_SAL_THRESHOLD = 0.5

    # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] 7 channel view (β.6 §4.3)
    # =========================================================================
    # 思考脑 prompt view 不再 evidence flat dump (老 14 块碎片), 改 7 channel
    # 结构化分组. LLM 上轮 <NEXT_ATTENTION_FOCUS> 提名 1-3 channel deep-load,
    # 其他 channel summary. R3 注意力精选不稀释 (Sir 真意 23:57).
    #
    # 设计 doc: docs/JARVIS_BETA6_UNIFIED_THINKING.md §4.3 + §5
    # =========================================================================
    _CHANNEL_NAMES: Tuple[str, ...] = (
        'recent_sensor_events',     # raw sensor / SWM event / inner voice / runtime log
        'concern_status',            # all concern severity + protocols + jokes + skepticism
        'nudge_history',             # 最近 30min fired nudge + Sir reaction
        'sir_activity_snapshot',     # sir_state + idle + declared_status + profile + time + directives
        'last_main_brain_reply',     # STM last 5 turn (主脑刚说啥 + Sir 反应)
        'last_thinking_output',      # 上次自己结论 + self_pacing_signal + anticipated_ltm + daemon health
        'my_recent_thoughts',        # last 3 thoughts (chain continuity)
    )

    # speak rate cap (β.6 §7 风险缓解 should_speak=yes 太多)
    # 🆕 [Sir 2026-05-28 00:30 β.6 Phase 1d 收口] 阈值持久化 memory_pool/
    # thinking_brain_speak_config.json → _get_speak_rate_cap() 动态读 (准则 6).
    # 类属性保留 (向后兼容 + 静态分析友好), 但只在 vocab 不可用时 fallback.
    _SPEAK_RATE_WINDOW_S = 300        # fallback, vocab 优先
    _SPEAK_RATE_MAX_YES = 3            # fallback, vocab 优先

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
            # 🆕 [Sir 2026-05-28 β.6 Phase 3] 加 publish_only 时代 advice etype,
            # 让思考脑 nudge_history channel 能看 sentinel "想 nudge 但 publish-only"
            # 的 evi (准则 6: vocab JSON 真源, 此处仅 fallback 防损坏).
            # 🆕 [Sir 2026-05-28 07:31 β.6 完整统一] 加 4 daemon 真退化 candidate etype.
            return (
                'proactive_nudge_', 'inner_thought_',
                'concern_severity_changed', 'concern_notes_appended',
                'promise_', 'commitment_', 'reminder_', 'wake_',
                'sir_intent_', 'stand_down_', 'utterance_appended',
                'gate_advice', 'proactive_care_advice',
                'proactive_care_skipped', 'concern_active',
                'concern_timing_evidence', 'soul_alignment_advice',
                'smart_nudge_candidate', 'conductor_candidate',
                'wellness_candidate', 'commitment_check_candidate',
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

        # 🆕 [fix50 / 2026-05-28] vision refresh advice dedup ts
        # =====================================================================
        # _tick 顶 check active WatchTask, 有 active → publish 'proactive_vision_
        # refresh_advice' SWM 让 ScreenVisionEngine 提频 backfill (5min → 30s).
        # dedup: 按 vision_refresh_advice.dedup_window_s 不重复 publish, 避免 spam SWM.
        # =====================================================================
        self._last_vision_refresh_publish_ts: float = 0.0
        self._vision_refresh_publish_count: int = 0
        self._last_relationship_reflector_ts: float = 0.0

        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] LLM 决定的下次 interval (0 = 用 baseline)
        self._next_tick_interval_s = 0
        # tick origin 统计 (dashboard 看 LLM 真在 self-pacing 还是默认)
        # 🆕 [Sir 2026-05-28 19:20 真意 — Jarvis 学会休息] 加 saturation_force origin
        # (≥ N 连续 saturated tick → 物理 force 600s, 优先级 > gate + LLM choice).
        self._tick_origin_stats = {
            'default': 0, 'llm_chosen': 0, 'llm_gated': 0, 'llm_smoothed': 0,
            'saturation_force': 0,
        }
        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] attention focus 元决策 (R3)
        # =====================================================================
        # Sir 真意: "这轮为下轮挑". 上轮 LLM 输出 <NEXT_ATTENTION_FOCUS>
        # ch_a,ch_b 存这里, 下轮 _build_channel_view 把这 2 channel 标 DEEP-LOAD
        # 其他标 SUMMARY, LLM 自己 attention 偏向 deep-load channel (R3 不稀释).
        # 空字符串 = 没 hint, 所有 channel 等 weight.
        # =====================================================================
        self._next_attention_focus = ''
        # speak rate cap 防主脑被噪音 (β.6 §7 风险缓解: should_speak=yes 太多)
        # 5min 内 ≥3 yes → 后续 force no (Python smoothing)
        self._recent_should_speak_yes_ts: List[float] = []

        # 🆕 [Sir 2026-05-28 19:20 真意 — Jarvis 学会休息] saturation counter
        # =====================================================================
        # 连续 saturated tick 计数 (同 thread + 都 should_speak=False + actionable
        # 无 effect). 每 tick saturation 检 → 重新算; 不 saturated → 清 0.
        # 计数 ≥ python_physical_force.min_consecutive_saturated_for_force →
        # _resolve_next_interval 强制 NEXT_INTERVAL = force_next_interval_s.
        # _saturation_force_due 由 _check_and_update_saturation 写, 由
        # _resolve_next_interval 读 (per-tick 状态串联, 类 _next_attention_focus).
        # 详 docs/AGENTS.md §6 三维耦合 + memory_pool/inner_thought_saturation_config.json.
        # =====================================================================
        self._consecutive_saturation_count: int = 0
        self._saturation_force_due: bool = False
        # 🆕 [useful-or-quiet P1 / Sir 2026-05-31] 跨 category 低值连续计数 (价值退避)
        self._low_value_streak: int = 0

        # 🆕 [第五阶段支柱 A / Sir 2026-05-29 02:29] evidence-gated tick 省 token
        # =====================================================================
        # tick 前算 evidence 指纹 (外部输入), 跟上次一样 → skip LLM (不烧 token).
        # _last_tick_fingerprint: 上次 tick 的指纹 (比较用, '' = 首 tick 必 think).
        # _evidence_skip_streak: 连续 skip 计数 (满 max_skip_streak 强制 think 心跳).
        # _evidence_gated_skip_count: 总 skip 数 (audit — 省了多少 LLM call).
        # 详 docs/JARVIS_THINKING_COST_AWARE_SELF_DEBUG_DESIGN.md 支柱 A.
        # =====================================================================
        self._last_tick_fingerprint: str = ''
        self._evidence_skip_streak: int = 0
        self._evidence_gated_skip_count: int = 0

        # 🆕 [governor Phase 4 E1 / Sir 2026-05-29 拍板] 紧急通路 state
        # =====================================================================
        # SWM 高 salience event publish 时 daemon_loop wait 中断 → 立次个 tick.
        # rate limit: 上次 wake interrupt < rate_limit_s → skip.
        # last_seen_ts: 防 same event 重复 trigger (event ts > last_seen 才计).
        # =====================================================================
        self._last_emergency_wake_ts: float = 0.0
        self._emergency_check_last_seen_ts: float = 0.0
        self._emergency_wake_count: int = 0  # audit / dashboard

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
        # 🆕 [Self-Memory P0 / Sir 2026-05-30] last_alive 心跳 throttle
        self._last_heartbeat_ts = 0.0
        # 🆕 [Self-Memory P1 / Sir 2026-05-30] brain-initiated recall (F1 后台自发深召回)
        # 上 tick <RECALL>query</RECALL> 跑出的召回候选, 下 tick prompt 注入后清空.
        self._pending_recall_block = ''
        # 🆕 [Self-Memory P2 / Sir 2026-05-30] 河床/巩固 cooldown throttle
        self._last_consolidate_ts = 0.0
        # 🆕 [言出必行 I2 / Sir 2026-05-30] 后台语义 claim 审计 throttle + dedup
        self._last_semantic_audit_ts = 0.0
        self._last_audited_reply = ''
        # cold_starts.jsonl append (daemon init 真发生) — 内含数据卫生 gate +
        # 真 dark_gap 计算 + 本 session 首心跳 (只在真 production session 写).
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
        # 🆕 [SOUL Phase 5 P4 / Sir 2026-05-29 拍板] 启动 refresh 动态地图
        # =====================================================================
        # 思考脑是 module_map 主消费者 (P2 self-knowledge inject). 启动时主动
        # refresh 一次: ① 确保地图反映当前代码 (重启即更新, 修手 map 过时痛点)
        # ② 生成 AUTO.md (agent 进窗口看最新架构) ③ 后续 build_architecture_block
        # 用 mtime cache. 在 daemon thread 内 (~1s, 不阻塞主进程).
        # 详 docs/JARVIS_DYNAMIC_MAP_AND_SELF_DEBUG_DESIGN.md Layer 1/6.
        # =====================================================================
        try:
            from jarvis_module_scanner import refresh as _mm_refresh
            _mm_data = _mm_refresh()
            _mm_st = (_mm_data or {}).get('stats', {})
            self._bg_log(
                f"🗺️ [P4/module_map] startup refresh: "
                f"{_mm_st.get('total_modules', 0)} modules, "
                f"{len(_mm_st.get('orphans', []))} orphans, "
                f"{len(_mm_st.get('no_docstring', []))} no-doc "
                f"(思考脑 self-knowledge 地图新鲜)"
            )
        except Exception as _e:
            self._bg_log(f"⚠️ [P4/module_map] startup refresh fail: {_e}")
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
            # 🆕 [Self-Memory P0 / Sir 2026-05-30] 持久 last_alive 心跳 (daemon 是
            # 心跳 keeper) — 周期刷, 让下次 cold_start 能算真 dark_gap (离线时长).
            try:
                self._maybe_persist_heartbeat()
            except Exception:
                pass
            # 🆕 [Sir 2026-05-27 01:00 β.5.50] yesterday_recap sub-reflector
            # daemon tick 后 check (低频 — 内部 23h cooldown 真守住)
            try:
                self._maybe_write_yesterday_recap()
            except Exception:
                pass
            # 🆕 [Self-Memory P2 / Sir 2026-05-30] 河床巩固 — 把流水账卷成持久线程 +
            # 衰减/分层 (遗忘). 周期 cooldown 守住 (类 yesterday_recap, 不每 tick 跑).
            try:
                self._maybe_consolidate_threads()
            except Exception:
                pass
            # 🆕 [言出必行 I2 / Sir 2026-05-30] 后台语义 claim 审计 (vocab-gated, 默 off;
            # 准则 1 — LLM 替正则枚举判 claim 接地, 仅后台 daemon, 不碰主脑回复热路径).
            try:
                self._maybe_semantic_claim_audit()
            except Exception:
                pass
            # 🆕 [Sir 2026-05-28 16:55 方案 B 治本] propose quality calibrate
            # daemon tick 后 check (24h cooldown 真守住, 不每 tick 跑)
            try:
                self._maybe_calibrate_propose_quality()
            except Exception:
                pass
            # 🆕 [governor Phase 4 E1 / Sir 2026-05-29 拍板] emergency wait interrupt
            # SWM 高 salience event publish 时 中断 wait → 立次个 tick.
            # 不再是 purely 静态 _stop.wait, 是事件可响应 wait.
            self._wait_with_emergency_check(timeout=interval)

    def _check_emergency_pending(self) -> bool:
        """🆕 [governor Phase 4 E1] Check SWM 有 emergency event published
        since last seen (rate limited).

        Returns: True → emergency 该中断 wait.
        """
        try:
            cfg = _load_emergency_vocab()
            if not cfg.get('enabled', True):
                return False
            now = time.time()
            rate_limit_s = float(cfg.get('rate_limit_s', 30))
            # rate limit: 上次 wake < rate_limit_s → skip (防刷屏)
            if now - self._last_emergency_wake_ts < rate_limit_s:
                return False
            sal_thr = float(cfg.get('salience_threshold', 0.85))
            trigger_etypes = set(cfg.get('trigger_etypes', []) or [])
            if not trigger_etypes:
                return False
            lookback_s = float(cfg.get('lookback_s', 5.0))
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return False
            recent = bus.recent_events(
                within_seconds=lookback_s, types=trigger_etypes,
            ) or []
            for e in recent:
                if float(e.get('salience', 0)) < sal_thr:
                    continue
                ev_ts = float(e.get('timestamp', 0))
                # 防 same event 重复 trigger
                if ev_ts <= self._emergency_check_last_seen_ts:
                    continue
                # 命中 emergency — update state + return True
                self._emergency_check_last_seen_ts = ev_ts
                self._last_emergency_wake_ts = now
                self._emergency_wake_count += 1
                self._bg_log(
                    f"⚡ [E1/emergency] SWM event etype={e.get('type', '?')} "
                    f"salience={e.get('salience', 0):.2f} → 中断 wait 立 tick "
                    f"(wake_count={self._emergency_wake_count})"
                )
                return True
        except Exception:
            pass
        return False

    def _check_body_stir(self) -> bool:
        """🆕 [Sir 2026-05-31 17:54 优雅 rest] 休息中体一有动静(fresh delta)→ 提前唤醒.

        势能自转: 休息不是定时冷却, 是"歇到被真扰动". 体 (Weaver 算的真张力/新颖) 一动
        → 结束休息去 attend 那块。仅 _resting 时检 (正常 tick 不需, 节省). 轻量读 body_energy。
        """
        if not getattr(self, '_resting', False):
            return False
        try:
            cfg = (_load_saturation_config().get('rest') or {})
            if not cfg.get('wake_on_body_delta', True):
                return False
            from jarvis_body_focus import get_body_focus
            mag = float(cfg.get('body_stir_min_magnitude', 0.3))
            if get_body_focus().has_fresh_delta(min_magnitude=mag):
                self._resting = False
                self._bg_log(
                    "⚡ [InnerThought] 体有动静 (fresh delta) → 结束休息, 醒来 attend "
                    "(势能扰动唤醒, 非定时)")
                return True
        except Exception:
            pass
        return False

    def _wait_with_emergency_check(self, timeout: float) -> str:
        """🆕 [governor Phase 4 E1] Wait up to `timeout` s, poll emergency every
        `poll_chunk_s` s. Return 'stop' / 'emergency' / 'timeout' / 'body_stir'.

        Replace plain `self._stop.wait(timeout=...)` to allow SWM event interrupt.
        🆕 [Sir 2026-05-31 优雅 rest] 休息中额外低频 poll 体动静 → 真扰动提前唤醒
        (非定时冷却到点; body_stir_poll_s 节流, 不每 0.5s 读盘)。
        """
        try:
            cfg = _load_emergency_vocab()
            poll_chunk = float(cfg.get('poll_chunk_s', 0.5))
        except Exception:
            poll_chunk = 0.5
        poll_chunk = max(0.1, min(2.0, poll_chunk))  # sanity
        try:
            _body_poll_s = float(
                (_load_saturation_config().get('rest') or {}).get('body_stir_poll_s', 30))
        except Exception:
            _body_poll_s = 30.0
        remaining = max(0.0, float(timeout))
        # If E1 disabled 或 timeout 太短, fallback 原 _stop.wait
        if not _load_emergency_vocab().get('enabled', True):
            self._stop.wait(timeout=remaining)
            return 'stop' if self._stop.is_set() else 'timeout'
        _since_body = 0.0
        while remaining > 0 and not self._stop.is_set():
            chunk = min(poll_chunk, remaining)
            self._stop.wait(timeout=chunk)
            if self._stop.is_set():
                return 'stop'
            if self._check_emergency_pending():
                return 'emergency'
            # 休息中: 低频查体动静 (真扰动唤醒, 非定时冷却)
            _since_body += chunk
            if _since_body >= _body_poll_s:
                _since_body = 0.0
                if self._check_body_stir():
                    return 'body_stir'
            remaining -= chunk
        if self._stop.is_set():
            return 'stop'
        return 'timeout'

    # ----------------------------------------------------------
    # Adaptive frequency + Sir state
    # ----------------------------------------------------------
    def _get_idle_seconds(self) -> float:
        # 🆕 [BUG FIX 锁屏降频双保险 / Sir 2026-05-29 08:53] 直调 GetLastInputInfo,
        # 不再首选 PhysicalEnvProbe.idle_seconds_real 缓存. 该缓存由 _monitor_loop
        # 更新, Sir 锁屏后 GetCursorPos 炸 loop 曾致缓存冻结 → state 永远 active →
        # 降频死 (env_probe 已修 loop). 这里再加一层: 即使缓存机制再坏, InnerThought
        # idle 也实时正确, 和 ReturnSentinel/SmartNudge 等 7 组件一致. GetLastInputInfo
        # 是系统级 API, 锁屏/secure desktop 仍可用 (不像 GetCursorPos 需桌面访问).
        try:
            import win32api
            return (win32api.GetTickCount() - win32api.GetLastInputInfo()) / 1000.0
        except Exception:
            pass
        # fallback: win32api 不可用 (非 Windows / 占位 None) → probe 缓存兜底
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
          0. saturation force (≥ N 连续 saturated + LLM 选短或 default) → 强制
             force_next_interval_s (default 600), origin='saturation_force'
             (优先级 > gate + LLM; Sir 真意"Jarvis 没必要花时间想这么多")
          1. LLM 没给 next_interval_s (=0) → 用 baseline, origin='default'
          2. LLM 给了, 但超物理 gate → 用 baseline, origin='llm_gated'
          3. LLM 给 30 + 最近 ≥3 thought 选 30 + 平均 sal < 0.5 → 强制 60, origin='llm_smoothed'
             (防 token 爆 + 低质量急思考惩罚)
          4. LLM 给且合法 → 用 LLM 选择, origin='llm_chosen'

        Returns: (interval_s, origin)
        """
        baseline = self._compute_adaptive_interval()
        llm_choice = thought.next_interval_s

        # 🆕 [Sir 2026-05-28 19:20 真意 — Jarvis 学会休息] Saturation 物理 force
        # =====================================================================
        # Sir 真意 anchor: "Jarvis 没必要花时间想这么多, 我又不需要, 让它休息".
        # _saturation_force_due 由 _check_and_update_saturation 计 (≥ N 连续
        # saturated tick → True). 触发后 force NEXT_INTERVAL = force_next_interval_s.
        # 设计 (准则 6 三维耦合 + 类 _SMOOTH_LOW_SAL 物理保底):
        # - 优先级 > 物理 gate + LLM choice (saturated = 卷 = 强制歇)
        # - llm_choice == 0 (default) 或 ≤ force_max_short_choice_s → force
        # - LLM 自己选大 interval (> force_max_short_choice_s) → 信任 LLM 已自觉
        #   休息, 不 override (BUT 物理 gate 仍 case 2 校验)
        # vocab: memory_pool/inner_thought_saturation_config.json
        #         python_physical_force.{enabled, force_next_interval_s,
        #                                force_max_short_choice_s}
        # =====================================================================
        if self._saturation_force_due:
            try:
                _sat_cfg = _load_saturation_config()
                _force_cfg = _sat_cfg.get('python_physical_force', {}) or {}
                if _force_cfg.get('enabled', True):
                    _force_max_short = int(
                        _force_cfg.get('force_max_short_choice_s', 60)
                    )
                    _force_interval = int(
                        _force_cfg.get('force_next_interval_s', 600)
                    )
                    if llm_choice == 0 or llm_choice <= _force_max_short:
                        return _force_interval, 'saturation_force'
            except Exception:
                pass  # fail-open: fall through to normal resolution

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
    # 🆕 [第五阶段支柱 A / Sir 2026-05-29 02:29] evidence-gated tick 省 token
    # ----------------------------------------------------------
    def _compute_evidence_fingerprint(self, sir_state: str,
                                       evidence: dict) -> str:
        """算 evidence 指纹 — 只含外部新输入, 不含思考脑自己产出.

        维度 (挂机时这些都稳定 → 指纹不变 → skip):
          - sir_state (active/afk_short/afk_deep/sleep)
          - idle bucket (跨 idle_buckets_s 边界才算变, 不用精确秒, 防抖动)
          - SWM events (type + desc, 排除 age_s 这种每 tick 都变的字段)
          - STM 最新 turn (when 绝对 ts + user 内容 = Sir 说新话的强信号)

        刻意不含 recent_thoughts (思考脑自产 — 含了会污染指纹导致永不 skip).

        Returns: str 指纹 (同进程内连续 tick 比较, 相同 = 无新外部输入).
        """
        parts: List[str] = [str(sir_state)]
        try:
            idle = int(evidence.get('idle_seconds', 0) or 0)
            buckets = (_load_cost_config().get('evidence_gate', {})
                       .get('idle_buckets_s', [300, 1800]))
            bidx = sum(1 for b in buckets if idle >= b)
            parts.append(f'i{bidx}')
        except Exception:
            parts.append('i?')
        # SWM events 内容 (type+desc, 不含 age_s — age 每 tick 变会破坏 skip).
        # 🆕 [BUG FIX 支柱A 指纹净化 / Sir 2026-05-29 08:53] 排除自产/高频 event:
        # 指纹只该反映"外部新输入". 思考脑自产 (source=inner_thought) + sensor
        # (PhysicalEnvProbe) + 各 daemon advice (*_advice etype) 每 tick 变, 含进指纹
        # → 永变 → 永不 skip (Sir 实测整晚 skip=0). 准则 6 vocab 持久化排除列表.
        _gate_cfg = _load_cost_config().get('evidence_gate', {})
        _excl_src = set(_gate_cfg.get('fingerprint_exclude_sources',
                                     ['inner_thought', 'PhysicalEnvProbe']))
        _excl_suf = tuple(_gate_cfg.get('fingerprint_exclude_etype_suffixes',
                                       ['_advice']))
        for e in (evidence.get('swm_events') or []):
            _etype = e.get('type', '')
            if e.get('source', '') in _excl_src:
                continue  # 自产/sensor 高频 event 不算外部新输入
            if _excl_suf and _etype.endswith(_excl_suf):
                continue  # daemon advice (*_advice) 每 tick 变, 不算外部新输入
            parts.append(f"s:{_etype}:{(e.get('desc') or '')[:40]}")
        # STM 最新 turn (when 绝对 ts + user — Sir 说新话信号)
        stm = evidence.get('stm') or []
        if stm:
            last = stm[-1]
            parts.append(
                f"u:{last.get('when', '')}:{(last.get('user') or '')[:40]}"
            )
        # 🆕 [P2 势能驱动 / 2026-05-31] 体势能进指纹 (势能自转的"醒不醒"门).
        # 体有 fresh delta (够幅度) → 指纹含 node+幅度桶 → 指纹变 → daemon 醒去想那块;
        # 体 settled → 无此项 → 指纹稳 → idle (不空转). grounded (Weaver 算), 无 LLM。
        try:
            if _gate_cfg.get('body_potential_in_fingerprint', True):
                from jarvis_body_focus import get_body_focus as _gbf_fp
                _min_mag = float(_gate_cfg.get('body_delta_min_magnitude', 0.30))
                _bucket = float(_gate_cfg.get('body_magnitude_bucket', 0.5)) or 0.5
                for _it in _gbf_fp().current_focus(limit=4):
                    if not _it.get('fresh'):
                        continue  # 只 fresh delta 算"新势能"(standing 高势能不反复醒)
                    _mag = float(_it.get('score', 0.0)) - 1.0  # focus 给 delta +1.0 偏置
                    if _mag >= _min_mag:
                        _mbkt = int(_mag / _bucket)
                        parts.append(f"b:{_it.get('node', '')}:{_mbkt}")
        except Exception:
            pass
        return '|'.join(parts)

    def _maybe_evidence_gate_skip(self, sir_state: str,
                                  evidence: dict) -> bool:
        """🆕 [第五阶段支柱 A] evidence 指纹一样 → skip LLM (省 token).

        Sir 2026-05-29 02:29 真痛 "开着挂机心疼 token". tick 前算外部输入指纹,
        跟上次一样 (Sir 没动 + 没说话 + 无新 SWM event) → skip LLM call, daemon
        仍 alive 等下个 tick. 连续 skip 满 max_skip_streak → 强制 think 1 次
        (心跳 heartbeat, 防纯 reactive 失"持续存在的生命"感).

        准则 6 vocab (enabled 开关 + max_skip_streak) + 准则 8 Python 硬节流
        (不依赖 LLM 觉悟省钱, 算指纹是纯 Python 不烧 token).

        Returns: True = 该 skip (不调 LLM); False = 正常 tick.
        """
        cfg = _load_cost_config().get('evidence_gate', {}) or {}
        if not cfg.get('enabled', True):
            return False
        fp = self._compute_evidence_fingerprint(sir_state, evidence)
        max_skip = int(cfg.get('max_skip_streak', 20))
        if (fp == self._last_tick_fingerprint
                and self._evidence_skip_streak < max_skip):
            self._evidence_skip_streak += 1
            self._evidence_gated_skip_count += 1
            # 每 10 次 skip log 1 次 (Sir 看 daemon alive + 省了多少 LLM call)
            if self._evidence_gated_skip_count % 10 == 1:
                self._bg_log(
                    f"💤 [InnerThought/evidence-gate] 无新外部输入 → skip LLM "
                    f"(streak={self._evidence_skip_streak}/{max_skip}, "
                    f"total saved={self._evidence_gated_skip_count}, "
                    f"state={sir_state}) — 省 token, daemon alive"
                )
            return True
        # 指纹变 (有新输入) 或 streak 满 (强制心跳) → 正常 tick + reset
        if (fp == self._last_tick_fingerprint
                and self._evidence_skip_streak >= max_skip):
            self._bg_log(
                f"💭 [InnerThought/evidence-gate] skip streak 满 {max_skip} "
                f"→ 强制 think 1 次 (心跳 heartbeat, 防纯 reactive)"
            )
        self._last_tick_fingerprint = fp
        self._evidence_skip_streak = 0
        return False

    # ----------------------------------------------------------
    # 🆕 [fix50 / 2026-05-28] Active WatchTask → vision refresh advice (准则 6)
    # ----------------------------------------------------------
    def _check_active_watch_task_and_publish_vision_refresh(self) -> None:
        """每 tick 顶调 — 有 active WatchTask → publish vision_refresh_advice SWM.

        ScreenVisionEngine daemon 看到 advice 临时把 backfill 5min → 30s, 提高
        WatchTask fire 点火率. dedup window 防 spam.

        准则 6 三维耦合:
          - 数据: publish 'proactive_vision_refresh_advice' SWM (含 active_count,
                   backfill_s, 让 vision daemon 自判)
          - 决策: vision daemon 看 advice 自调额, 不是 thought 脑硬改 vision
          - 持久化: watch_task_config.json vision_refresh_advice.* (CLI 可改)
        """
        try:
            from jarvis_watch_task import list_active_tasks, _load_config as _wt_load_cfg
        except Exception:
            return
        cfg = (_wt_load_cfg().get('vision_refresh_advice') or {})
        if not cfg.get('enabled', True):
            return
        # dedup
        now = time.time()
        dedup_s = float(cfg.get('dedup_window_s', 30.0)) if 'dedup_window_s' in cfg \
                                                            else 30.0
        if now - self._last_vision_refresh_publish_ts < dedup_s:
            return
        # 看 active WatchTask
        try:
            active = list_active_tasks() or []
        except Exception:
            active = []
        if not active:
            return
        # publish SWM
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='proactive_vision_refresh_advice',
                description=(
                    f"InnerThought tick: {len(active)} active WatchTask → "
                    f"recommend vision backfill "
                    f"{float(cfg.get('active_watch_backfill_s', 30.0))}s"
                ),
                source='InnerThoughtDaemon',
                salience=float(cfg.get('advice_salience', 0.6)),
                ttl=float(cfg.get('advice_ttl_s', 120.0)),
                metadata={
                    'active_count': len(active),
                    'active_task_ids': [t.id for t in active[:10]],
                    'recommended_backfill_s': float(
                        cfg.get('active_watch_backfill_s', 30.0)
                    ),
                    'ts': now,
                },
            )
            self._last_vision_refresh_publish_ts = now
            self._vision_refresh_publish_count += 1
        except Exception:
            pass

    def _sweep_ignored_main_replies(self) -> None:
        """🆕 [#2 / Sir 2026-05-29 Option A] 静默 sweep — pending main_reply 老于
        reaction_vocab.ignored_after_min (Sir 久未反应) → 标 'ignored'.

        仅喂 V6 meta_feedback_loop (思考脑看 Sir 没接住 → 可能太 pushy / AFK),
        **不触发 record_rejection** (ignored 太弱/歧义). 纯 Python 不烧 token.
        详 docs/JARVIS_CLOSURE_AND_RELATIONAL_UPLIFT_DESIGN.md #2.
        """
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track,
                is_enabled as _iv_enabled,
            )
            if not _iv_enabled():
                return
            try:
                from jarvis_reaction_classifier import load_ignored_after_min
                _older = load_ignored_after_min()
            except Exception:
                _older = 8.0
            n = get_inner_voice_track().mark_stale_pending_main_replies_ignored(
                older_than_min=_older, max_age_min=60.0,
            )
            if n > 0:
                self._bg_log(
                    f"⏸️ [#2/ignored-sweep] mark {n} stale pending "
                    f"main_reply(s) as sir_reaction='ignored' "
                    f"(silent >{_older}min)"
                )
        except Exception:
            pass

    def _maybe_run_relationship_reflector(self, evidence: dict) -> None:
        cfg = _load_relationship_reflector_config()
        if not cfg.get('enabled', False):
            return
        if not cfg.get('use_llm', False):
            return
        now = time.time()
        min_interval = float(cfg.get('min_interval_s', 21600) or 21600)
        if now - self._last_relationship_reflector_ts < min_interval:
            return
        stm = evidence.get('stm') or []
        if len(stm) < int(cfg.get('min_stm_turns', 2) or 2):
            return
        try:
            from jarvis_relationship_reflector import RelationshipReflector
            reflector = RelationshipReflector(key_router=self.key_router)
            result = reflector.reflect_once(stm)
            self._last_relationship_reflector_ts = now
            if result.get('proposed'):
                self._bg_log(
                    f"💭 [RelationshipReflector] proposed "
                    f"{result.get('proposal_id', '')}"
                )
        except Exception as e:
            self._last_relationship_reflector_ts = now
            try:
                self._bg_log(f"⚠️ [RelationshipReflector] hook failed: {e}")
            except Exception:
                pass

    # ----------------------------------------------------------
    # Tick (the core)
    # ----------------------------------------------------------
    def _tick(self) -> None:
        self._tick_count += 1
        # 🆕 [Sir 2026-05-31 优雅 rest] 一旦真 tick 跑起来 → 不再"休息中" (若本 tick 又
        # 选 REST, _handle_rest_decision 会重新置 True). 清标避免 stale。
        self._resting = False

        # 🆕 [#2 / Sir 2026-05-29 Option A] ignored sweep — 每 tick 顶跑 (纯 Python
        # 不烧 token, cooldown/evidence-gate skip 都不影响). pending main_reply
        # 静默老于阈值 → 标 ignored (仅喂 meta_feedback_loop, 不衰减 directive).
        try:
            self._sweep_ignored_main_replies()
        except Exception:
            pass

        # 🆕 [fix50 / 2026-05-28] active WatchTask 提频 vision (准则 6 三维耦合)
        # =====================================================================
        # 每 tick 顶检查 active WatchTask, 有 → publish 'proactive_vision_refresh_
        # advice' SWM. ScreenVisionEngine daemon 看到 advice 临时提频 backfill
        # (5min default → 30s active). 准则 6 数据进 SWM, 决策让 vision daemon 自判.
        # fire-and-forget, 不阻塞 tick 主流 (cooldown skip / LLM call 不受影响).
        # =====================================================================
        try:
            self._check_active_watch_task_and_publish_vision_refresh()
        except Exception:
            pass

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

        # 🆕 [第五阶段支柱 A / Sir 2026-05-29 02:29] evidence-gated skip 省 token
        # =====================================================================
        # evidence 指纹跟上次一样 (Sir 没动/没说话/无新 SWM event) → skip LLM,
        # daemon 仍 alive. 挂机时大幅省 token (Sir "开着挂机心疼"). 放 LLM call
        # 前 (channel_view + build_prompt + _call_llm 全省). 准则 8 Python 硬节流.
        # evidence collect 已发生 (纯 Python 不烧 token), 用它算指纹值得.
        # =====================================================================
        try:
            if self._maybe_evidence_gate_skip(sir_state, evidence):
                return
        except Exception:
            pass

        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] 构 7 channel view + LLM attention hint
        # =====================================================================
        # self._next_attention_focus 是上轮 LLM 输出, 没有则 '' = 全 channel deep.
        # _build_channel_view 返回 channel dict, _build_prompt 用之决定 deep vs summary 渲染.
        # =====================================================================
        channel_view = self._build_channel_view(
            evidence, focus_hint=self._next_attention_focus
        )

        # LLM call (Flash-Lite, caller='inner_thought' → P2 LOW priority)
        prompt_sys, prompt_user = self._build_prompt(
            sir_state, evidence, free_categories=free_categories,
            channel_view=channel_view,
        )
        raw = self._call_llm(prompt_sys, prompt_user)
        if not raw:
            self._llm_fail_count += 1
            # 🆕 [Sir 2026-05-28 21:10 silent-fail-instrument] 看真因
            # ===================================================================
            # Sir 痛点: thought 自 20:38 起 30+ min silent. daemon line 1157/1162
            # 2 处 silent skip (raw='' / parse None), 0 log → 无法诊断. 加 _bg_log
            # 让真因显形. 准则 6 publish evidence 类比. 准则 8 治本前置 audit.
            # ===================================================================
            self._bg_log(
                f"⚠️ [InnerThought/silent] _call_llm 返空 raw "
                f"(fail_count={self._llm_fail_count}, sir_state={sir_state}, "
                f"tick={tick_interval}s)"
            )
            return

        # 🆕 [Sir 2026-05-31 放下能力] REST 决策 — 识主动"放下"(settled 不强凑 thought).
        # 有真势能 → 往下正常 parse/think; 没有 → <REST> 歇会, 拉长下次唤醒, 不产 filler.
        # 放在 recall/note 解析前: rest tick 不该触发召回/记忆副作用 (真的在歇)。
        try:
            if self._handle_rest_decision(raw, sir_state):
                return
        except Exception:
            pass

        # 🆕 [Self-Memory P1 / Sir 2026-05-30] brain-initiated recall —
        # 解析 <RECALL>query</RECALL>, 跑召回, 存 pending block → 下 tick prompt 顶注入
        # (F1 后台自发深召回, 不阻塞当前 tick; fire-and-forget, 异常不影响 thought).
        try:
            self._handle_recall_tag(raw)
        except Exception:
            pass
        # 🆕 [Self-Memory P4 / Sir 2026-05-30] 解析 <NOTE>text</NOTE> → 自写记忆持久化
        try:
            self._handle_note_tag(raw)
        except Exception:
            pass

        thought = self._parse_thought(raw, sir_state, tick_interval)
        if thought is None:
            # 🆕 [Sir 2026-05-28 21:10 silent-fail-instrument] log raw 前 200 char
            self._bg_log(
                f"⚠️ [InnerThought/silent] _parse_thought 返 None "
                f"(raw 缺 <CATEGORY>/<THOUGHT>/<SALIENCE> 或 thought=quiet). "
                f"raw[:200]='{raw[:200]}'"
            )
            return

        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] speak rate cap smoothing
        # =====================================================================
        # 防 LLM 短时连发 should_speak=yes 噪音 Sir. 5min 内 ≥3 yes → 后续 force no.
        # 准则 6 信任 LLM 但 Python 物理保底 (类 NEXT_INTERVAL smoothing).
        # =====================================================================
        if thought.should_speak:
            now = time.time()
            if self._should_smooth_force_silent(now):
                _w, _max = _get_speak_rate_cap()
                self._bg_log(
                    f"💭 [InnerThought] β.6 speak rate cap: "
                    f"{_w}s 内 ≥{_max} yes, "
                    f"force should_speak=no this tick (smoothing)"
                )
                thought.should_speak = False
                thought.speak_content = ''
                thought.speak_style = ''
            else:
                self._record_should_speak_yes(now)

        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] attention focus writeback
        # =====================================================================
        # LLM 自报 next_attention_focus 存实例状态, 下次 tick _build_channel_view
        # 用之决定 deep-load channel. R3 注意力精选不稀释 (Sir 真意 23:57).
        # =====================================================================
        try:
            self._next_attention_focus = (
                thought.next_attention_focus or ''
            )
        except Exception:
            self._next_attention_focus = ''

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

        # 🆕 [thinking-dehardcode-P0 / Sir 2026-05-31] 双写 derived_kind (不改行为).
        # =====================================================================
        # kind = 该 thought 放电产生的 effect 的 label (从 final actionable 派生 —
        # 含被 evidence/quality gate 降级为 none 的情况 → 'empty', 语义即 filler).
        # 纯 metadata: persist 进 jsonl + log 显示, Phase 0 不被任何决策读 (恒 legacy).
        # 失败非致命 (保持 '' 老兼容). 非 REST 路径 (REST 早返于 _handle_rest_decision).
        # =====================================================================
        try:
            thought.derived_kind = _kind_from_effect(thought.actionable)
        except Exception:
            pass

        # 🆕 [Sir 2026-05-25 23:18 真痛-3] actionable fail → publish SWM
        # 让主脑下轮 prompt 看到自己上轮失败, 改进选 concern_id.
        if not ok and thought.actionable and \
                thought.actionable.lower() != 'none':
            self._publish_actionable_failure(thought, result)

        # 🆕 [Sir 2026-05-25 23:18 真痛-4] B 类 self-correction 闭环:
        # 主脑自己识别 "I keep repeating X" 类 → publish stop_repeating_topic
        # 让 SOUL inject 下轮主脑 prompt 真看到 → 真不重复.
        self._maybe_publish_self_correction(thought)

        try:
            self._maybe_run_relationship_reflector(evidence)
        except Exception:
            pass

        # 🆕 [Sir 2026-05-28 19:20 真意 — Jarvis 学会休息] saturation 检 + counter
        # =====================================================================
        # actionable 完成后, 算"同 thread + 都 should_speak=False + actionable
        # 无 effect" 是否 saturated. counter ≥ 阈值 → _resolve_next_interval 强制
        # 大间隔. 准则 6 数据强耦合 + 准则 8 优雅 (config + CLI + LLM 仍可选).
        # =====================================================================
        try:
            self._saturation_force_due = bool(
                self._check_and_update_saturation(thought)
            )
        except Exception:
            self._saturation_force_due = False

        # 🆕 [Sir 2026-05-26 12:21 Meta-thinking] resolve LLM-chosen next interval
        # 物理 gate + smoothing 后, store 到 self._next_tick_interval_s,
        # _daemon_loop 下次 wait 时优先用.
        resolved_interval, tick_origin = self._resolve_next_interval(
            thought, sir_state
        )
        _base_interval = resolved_interval  # 自定节奏基线 (value-backoff 前)
        # 🆕 [useful-or-quiet P1 / Sir 2026-05-31] 跨 category 价值门控退避 clamp —
        # 补 saturation same-category 漏洞 (脑 category-hop 逃过). 连续低值 tick →
        # 指数退避; 只拉长不缩短 (safe). reset on 高值/should_speak.
        try:
            _vb_interval = self._update_value_backoff(thought)
            if _vb_interval > resolved_interval:
                resolved_interval = _vb_interval
                tick_origin = 'value_backoff'
                self._bg_log(
                    f"😌 [InnerThought/value-backoff] 连续低值 "
                    f"{self._low_value_streak} tick (跨 category) → 降频至 "
                    f"{_vb_interval}s (放得下, 不 churn)"
                )
        except Exception:
            pass
        # 🆕 [口识体-C-wake / 2026-05-31] 体势能驱动唤醒频次 (② 体→识 tempo) —
        # =====================================================================
        # 势能自转的频率侧: 体有刚升起的 delta (真张力/新颖, grounded) → 撤销 value-backoff
        # 的"放得下", 回自定节奏基线去 attend 那个势能区。无 delta → 维持 backoff (settled
        # 就怠速)。即"体不安定→识转快, 体 settled→识慢"。不超过 Sir-态基线 (尊重 self-pace)。
        # grounded 无 LLM, 失败非致命。详 VOICE_AND_MIND_REFACTOR §2/§5.5。
        # =====================================================================
        try:
            if tick_origin == 'value_backoff' and resolved_interval > _base_interval:
                from jarvis_body_focus import get_body_focus as _gbf_wake
                if _gbf_wake().has_fresh_delta():
                    resolved_interval = _base_interval
                    tick_origin = 'body_delta_wake'
                    self._bg_log(
                        f"⚡ [InnerThought/body-delta] 体有新势能 → 撤退避回 "
                        f"{_base_interval}s (该醒去 attend)"
                    )
        except Exception:
            pass
        thought.tick_origin = tick_origin
        self._next_tick_interval_s = resolved_interval
        self._tick_origin_stats[tick_origin] = \
            self._tick_origin_stats.get(tick_origin, 0) + 1

        # persist (主脑通过 Layer 1.5/1.6 直接 read self._thoughts + jsonl)
        self._persist_thought(thought)

        # 🆕 [Sir 2026-05-28 12:30 真痛 anchor] 退化 _publish_swm — push 跟思考链冗余
        # =====================================================================
        # Sir 哲学拍板: "主脑 = 好演员, 有思考链所有思考信息 (Layer 1.5/1.6/1.7
        # pull), 不需要碎片 push". 查证 jarvis_inner_thought SWM event 真无任何
        # production consumer (grep recent_events/types/etype 0 命中), 是 100%
        # 历史债孤儿. dashboard 走 inner_voice_24h.jsonl + daemon.get_stats(), Layer
        # 1.5/1.6/1.7 走 daemon 直接 API (build_lifetime_block / build_should_speak_
        # directive), 没人通过 SWM 取 thought event. 准则 8 优雅: 干净退化, 不留 dead
        # publish. 准则 6 evidence-only: 数据通过 jsonl + daemon 字段, 不需 SWM 中转.
        # _publish_swm method 整段删除 (line 4146 was). is_mediocre 判断保留, 仅控制
        # _emit_thought_pulse skip (字幕 💭 闪).
        # =====================================================================
        # mediocre 判断保留 (Sir 2026-05-26 23:24/23:53 anchor) — 仅 control
        # _emit_thought_pulse skip, 不再 control publish (已删).
        is_mediocre = (
            thought.salience < self._MEDIOCRE_SAL_THRESHOLD
            and (not thought.actionable or thought.actionable.lower() == 'none')
            and thought.category in ('A', 'D', 'E')
        )

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
        # 🆕 [thinking-dehardcode-P0 / Sir 2026-05-31] log 显示派生 kind (双写, 不改行为).
        # Sir 现在就能在 runtime log 看 kind 分布 (solve/reflect/empty/...), 评估
        # emergent 切换时机. 追加在末尾, 不破坏 [{cat}/sal=...] 前缀匹配.
        kind_str = (f" | kind={thought.derived_kind}"
                    if getattr(thought, 'derived_kind', '') else '')
        # 🆕 [Sir 23:24 BUG-5] mediocre log compact (前 50 ch + [skip:mediocre] 标)
        if is_mediocre:
            self._bg_log(
                f"💭 [InnerThought/skip:mediocre] [{thought.category}/sal={thought.salience:.2f}"
                f"] {thought.thought[:60]}…{meta_str}{kind_str}"
            )
        else:
            # 🆕 [Sir 2026-05-27 00:43 真痛] log truncate 100→300 让 Sir 看完整 thought
            # 🆕 [Sir 2026-05-27 21:11 真测 P2_b] word-boundary truncate 避字中间断
            _tt = _truncate_at_word_boundary(thought.thought, 300)
            self._bg_log(
                f"💭 [InnerThought] [{thought.category}/sal={thought.salience:.2f}"
                f"/state={sir_state}/tick={tick_interval}s] {_tt}"
                f"{action_str}{ev_str}{meta_str}{kind_str}"
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
            # 🆕 [governor Phase 1 F6 改 2] 不再 early return — bus is None
            # 仍允许下面 voice append 路径继续 (SWM publish 和 voice append 独立).
            if bus is not None:
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
                    f"(sal={thought.salience:.2f}) → publish "
                    f"self_reflection_noted SWM (legacy 0-consumer 路径, "
                    f"实际主脑通过下面 voice append 看)"
                )
        except Exception:
            pass
        # 🆕 [governor Phase 1 F6 改 2 / Sir 2026-05-29 拍板]
        # 修复缺口 ③: B 类反思 只 publish SWM (0 consumer) 主脑看不到.
        # 治本: append 心声 source='self_reflection' intent='reflection',
        # 主脑下轮 SOUL inject 心声 → 自然看到 B 类反思.
        # dedup: 窗内 (30min default) 同 topic (jaccard > 0.6) 跳,
        # 防 1h 22 次重复反思淹没主脑.
        # 详 docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F6 改 2
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled as _iv_enabled,
            )
            if not _iv_enabled():
                return
            _enabled, _win_min, _jacc_thr = (
                _get_self_reflection_dedup_config()
            )
            if not _enabled:
                return
            _track = get_inner_voice_track()
            # dedup check: 窗内查同 topic self_reflection
            _recent = _track.recent(minutes=float(_win_min), max_n=30)
            _new_text = str(thought.thought or '')[:200]
            _dup_found = False
            for _e in _recent:
                if (getattr(_e, 'source', '') != 'self_reflection'
                        or getattr(_e, 'intent', '') != 'reflection'):
                    continue
                _existing_text = str(_e.content or '')
                # strip prefix '(self-reflected) ' 为公平 jaccard
                if _existing_text.startswith('(self-reflected) '):
                    _existing_text = _existing_text[17:]
                _jacc = _self_reflection_jaccard(_new_text, _existing_text)
                if _jacc >= _jacc_thr:
                    _dup_found = True
                    break
            if _dup_found:
                self._bg_log(
                    f"🪞 [InnerThought/self-reflection] B-thought append voice "
                    f"skipped (jaccard>={_jacc_thr} dedup 窗{_win_min}min)"
                )
                return
            _track.append(
                source='self_reflection',
                intent='reflection',
                content=f'(self-reflected) {_new_text[:140]}',
                urgency=min(0.7, float(thought.salience)),
                wants_voice=(thought.salience >= 0.8),  # 高 sal 标 ★ spotlight
                meta={
                    'thought_id': thought.id,
                    'category': 'B',
                    'original_salience': float(thought.salience),
                    'source_origin': 'inner_thought_daemon',
                },
            )
            self._bg_log(
                f"🪞 [InnerThought/self-reflection] B-thought "
                f"(sal={thought.salience:.2f}) → append voice "
                f"source='self_reflection' (主脑下轮看心声看到)"
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-27 22:11 真问 P10] Self-pacing signal compute + publish
    # ----------------------------------------------------------
    def _compute_self_signal(self) -> Optional[dict]:
        """compute 3 raw self-signal evidence (per pacing vocab).

        准则 6: 不写"超 X 就 Y"if rule. 只 raw signal 喂 LLM, LLM 自决 pace.
        vocab gate: signals_enabled.* / lookback_n / signal_fields.include.

        Returns: dict 含 3 key (gated by vocab), 或 None (vocab 全 disable).
        """
        cfg = _load_pacing_config()
        enabled = cfg.get('signals_enabled', {}) or {}
        if not any(enabled.values()):
            return None
        lookback_n = int(cfg.get('lookback_n', 5))
        fields_cfg = cfg.get('signal_fields') or {}
        out: dict = {}

        # snapshot recent N thoughts (unlocked, accept race for low contention)
        try:
            with self._lock:
                recent = sorted(self._thoughts,
                                  key=lambda t: -t.ts)[:lookback_n]
        except Exception:
            recent = []

        # ----- (1) self_recent_quality -----
        if enabled.get('self_recent_quality', True) and recent:
            include = ((fields_cfg.get('self_recent_quality') or {})
                       .get('include') or
                       ['avg_salience', 'actionable_rate',
                        'mediocre_rate', 'lookback_used'])
            q: dict = {}
            n = len(recent)
            if 'avg_salience' in include:
                q['avg_salience'] = round(
                    sum(t.salience for t in recent) / n, 2
                )
            if 'actionable_rate' in include:
                _act = sum(
                    1 for t in recent
                    if t.actionable and t.actionable.lower() != 'none'
                )
                q['actionable_rate'] = round(_act / n, 2)
            if 'mediocre_rate' in include:
                _med = sum(
                    1 for t in recent
                    if (t.salience < self._MEDIOCRE_SAL_THRESHOLD
                        and (not t.actionable
                             or t.actionable.lower() == 'none')
                        and t.category in ('A', 'D', 'E'))
                )
                q['mediocre_rate'] = round(_med / n, 2)
            if 'lookback_used' in include:
                q['lookback_used'] = n
            out['self_recent_quality'] = q

        # ----- (2) self_thread_diversity -----
        if enabled.get('self_thread_diversity', True) and recent:
            include = ((fields_cfg.get('self_thread_diversity') or {})
                       .get('include') or
                       ['unique_threads', 'top_thread_share',
                        'top_thread_id_short', 'lookback_used'])
            d: dict = {}
            thread_ids = [
                (getattr(t, 'thread_id', '') or t.id) for t in recent
            ]
            uniq = set(thread_ids)
            n = len(recent)
            if 'unique_threads' in include:
                d['unique_threads'] = len(uniq)
            if include and ('top_thread_share' in include
                            or 'top_thread_id_short' in include):
                # find top thread
                top_tid = max(uniq,
                                key=lambda tid: thread_ids.count(tid))
                top_count = thread_ids.count(top_tid)
                if 'top_thread_share' in include:
                    d['top_thread_share'] = round(top_count / n, 2)
                if 'top_thread_id_short' in include:
                    d['top_thread_id_short'] = (top_tid or '')[:16]
            if 'lookback_used' in include:
                d['lookback_used'] = n
            out['self_thread_diversity'] = d

        # ----- (3) overall_concern_pressure -----
        if enabled.get('overall_concern_pressure', True):
            include = ((fields_cfg.get('overall_concern_pressure') or {})
                       .get('include') or
                       ['max_severity', 'avg_severity', 'active_count',
                        'high_severity_count',
                        'recent_swm_event_count_1h'])
            p: dict = {}
            try:
                if (self.concerns_ledger
                        and hasattr(self.concerns_ledger, 'list_active')):
                    active = self.concerns_ledger.list_active() or []
                    if active:
                        sevs = [c.severity for c in active]
                        if 'max_severity' in include:
                            p['max_severity'] = round(max(sevs), 2)
                        if 'avg_severity' in include:
                            p['avg_severity'] = round(
                                sum(sevs) / len(sevs), 2
                            )
                        if 'active_count' in include:
                            p['active_count'] = len(active)
                        if 'high_severity_count' in include:
                            p['high_severity_count'] = sum(
                                1 for s in sevs if s >= 0.7
                            )
            except Exception:
                pass
            if 'recent_swm_event_count_1h' in include:
                try:
                    from jarvis_utils import get_event_bus as _geb_sp
                    _bus_sp = _geb_sp()
                    if _bus_sp is not None:
                        _top = _bus_sp.top_n(n=100) or []
                        _ct = sum(
                            1 for e in _top
                            if e.get('_age_s', 99999) <= 3600
                        )
                        p['recent_swm_event_count_1h'] = _ct
                except Exception:
                    pass
            if p:
                out['overall_concern_pressure'] = p

        return out or None

    def _publish_self_signal_swm(self, sig: dict) -> None:
        """publish raw signal to SWM (gated by vocab swm_publish.enabled).

        准则 6 数据强耦合: 主脑 / Reflector / Dashboard 都能 consume 同一 event.
        """
        cfg = _load_pacing_config()
        pub_cfg = cfg.get('swm_publish') or {}
        if not pub_cfg.get('enabled', True):
            return
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            etype = str(pub_cfg.get('etype', 'inner_thought_self_signal'))
            ttl_s = float(pub_cfg.get('ttl_s', 1800))
            sal = float(pub_cfg.get('salience', 0.3))
            # short desc summary (fact only, no judgement)
            q = sig.get('self_recent_quality') or {}
            d = sig.get('self_thread_diversity') or {}
            p = sig.get('overall_concern_pressure') or {}
            parts = []
            if q:
                parts.append(
                    f"sal_avg={q.get('avg_salience', '?')} "
                    f"med_rate={q.get('mediocre_rate', '?')}"
                )
            if d:
                parts.append(
                    f"threads={d.get('unique_threads', '?')}/"
                    f"{d.get('lookback_used', '?')} "
                    f"top_share={d.get('top_thread_share', '?')}"
                )
            if p:
                parts.append(
                    f"max_sev={p.get('max_severity', '?')} "
                    f"high_sev_n={p.get('high_severity_count', '?')}"
                )
            desc = ' | '.join(parts)[:200]
            bus.publish(
                etype=etype,
                description=desc,
                source='InnerThoughtDaemon',
                salience=sal,
                metadata=sig,
                ttl=ttl_s,
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
        # 🆕 [governor Phase 1 F2 / Sir 2026-05-29 拍板] 拿 last N 个 thought (vocab 可调)
        # 修复缺口 ①: 旧版硬编码 last 3 思考脑看不到 1h 内重复 22 次同事.
        # 新: vocab recent_thoughts_lookback.n (15) + .min (30) 可调 → 思考脑长视野.
        # 传 actionable_done + result 让 LLM 看上次失败 (防重提同 tool).
        try:
            _lookback_n, _lookback_min = _get_recent_thoughts_lookback()
            ev['recent_thoughts_lookback_min'] = _lookback_min  # 供 _build_prompt 文案
            _cutoff_ts = time.time() - _lookback_min * 60.0
            with self._lock:
                _sorted_thoughts = sorted(
                    self._thoughts, key=lambda t: -t.ts
                )
            # 主路径: cutoff 内取上限 n 条
            _in_window = [t for t in _sorted_thoughts if t.ts >= _cutoff_ts]
            recent_picked = _in_window[:_lookback_n]
            # Fallback: 启动后 cutoff 内空 (新进程没 thought 历史)
            # → 取 last n 不管时间 (backward compat 不破坏旧行为)
            if not recent_picked and _sorted_thoughts:
                recent_picked = _sorted_thoughts[:_lookback_n]
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
                for t in recent_picked
            ]
        except Exception:
            pass
        # 🆕 [governor Phase 1 F3 / Sir 2026-05-29 拍板] topic distribution hint
        # E4 evidence 维度化: count thoughts by thread_id in window →
        # 思考脑视觉看"我 22 次想同事" → 自然激活 let_go (Phase 2 实现标签).
        # Python 只 count, LLM 自决是否 let_go (准则 6 信任 LLM).
        # 🆕 [governor Phase 2 F4] count 中加 aged_flag (occurrences >= max_occ) 提示 LLM
        try:
            from collections import Counter
            _td_lookback_min, _td_warning_thr, _td_max_topics = (
                _get_topic_distribution_config()
            )
            # 🆕 [governor Phase 2 F4] 拿 topic_repeat 阈值
            _tr_max_occ, _tr_win_min, _tr_default_ttl = (
                _get_topic_repeat_config()
            )
            _td_cutoff = time.time() - _td_lookback_min * 60.0
            with self._lock:
                _all_in_window = [
                    t for t in self._thoughts if t.ts >= _td_cutoff
                ]
            if _all_in_window:
                _thread_counts: Counter = Counter()
                _thread_latest_ts: dict = {}
                for t in _all_in_window:
                    tid = (getattr(t, 'thread_id', '') or t.id)
                    _thread_counts[tid] += 1
                    if (tid not in _thread_latest_ts
                            or t.ts > _thread_latest_ts[tid]):
                        _thread_latest_ts[tid] = t.ts
                _now = time.time()
                ev['topic_distribution'] = {
                    'lookback_min': _td_lookback_min,
                    'warning_threshold': _td_warning_thr,
                    'aged_threshold': _tr_max_occ,
                    'default_let_go_ttl_min': _tr_default_ttl,
                    'topics': [
                        {
                            'thread_id_short': (tid or '')[:16],
                            'count': cnt,
                            'last_age_s': int(
                                _now - _thread_latest_ts[tid]
                            ),
                            # 🆕 F4: aged_flag 暂 LLM 可考虑 <LET_GO> tag
                            'aged_flag': cnt >= _tr_max_occ,
                        }
                        for tid, cnt in _thread_counts.most_common(
                            _td_max_topics
                        )
                    ],
                }
        except Exception:
            pass
        # 🆕 [governor Phase 3 F6 改 3 / Sir 2026-05-29 拍板] meta_feedback_loop
        # ============================================================
        # V6 元学习闭环: 拿近 N 分钟 main_brain_reply entries (心声
        # meta.kind='main_reply') + sir_reaction (engaged/rejected/ignored/pending).
        # 思考脑下轮 prompt [META FEEDBACK LOOP] block 看 reply + reaction →
        # 上次 directive A 被 Sir rejected → 重组 directive B (不同方向).
        # ============================================================
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track as _giv_mfl,
                is_enabled as _iv_en_mfl,
            )
            if _iv_en_mfl():
                _track_mfl = _giv_mfl()
                if hasattr(_track_mfl, 'get_recent_main_replies'):
                    _replies = _track_mfl.get_recent_main_replies(
                        within_min=60.0, max_n=5,
                    )
                    if _replies:
                        _now_mfl = time.time()
                        ev['meta_feedback_loop'] = [
                            {
                                'reply_excerpt': (
                                    (e.meta or {}).get('reply_excerpt', '')
                                )[:120],
                                'sir_excerpt': (
                                    (e.meta or {}).get('sir_excerpt', '')
                                )[:60],
                                'sir_reaction': (
                                    (e.meta or {}).get('sir_reaction', 'pending')
                                ),
                                'directive_id': (
                                    (e.meta or {}).get('directive_id', '')
                                ),
                                'turn_id': (
                                    (e.meta or {}).get('turn_id', '')
                                ),
                                'age_s': int(_now_mfl - e.ts),
                            }
                            for e in _replies
                        ]
        except Exception:
            pass
        # 🆕 [governor Phase 2 F4 / Sir 2026-05-29 拍板] '放下' prune
        # ============================================================
        # 读 active let_go list → prune recent_thoughts + topic_distribution
        # 该 thread_id 相关 entry. LLM 视觉看不到 → 自然不 think → '放下' 真生效.
        # Sir CLI scripts/let_go_dump.py 强解锁 / extend.
        # ============================================================
        try:
            _active_let_go = _load_let_go_topics()
            if _active_let_go:
                _let_go_tids = {
                    e.get('thread_id') for e in _active_let_go
                    if e.get('thread_id')
                }
                _now2 = time.time()
                # ev 暴露 let_go list (主脑 + dashboard 可看)
                ev['active_let_go_topics'] = [
                    {
                        'thread_id_short': str(
                            e.get('thread_id', '')
                        )[:16],
                        'reason': str(e.get('reason', '') or '')[:120],
                        'source': e.get('source', '?'),
                        'ttl_remaining_s': int(
                            float(e.get('ttl_ts', 0)) - _now2
                        ),
                    }
                    for e in _active_let_go
                ]
                # Prune recent_thoughts (思考脑下轮看不到 let_go thread)
                if 'recent_thoughts' in ev:
                    ev['recent_thoughts'] = [
                        t for t in ev['recent_thoughts']
                        if t.get('thread_id') not in _let_go_tids
                    ]
                # Prune topic_distribution (count 不包含 let_go thread)
                if 'topic_distribution' in ev:
                    ev['topic_distribution']['topics'] = [
                        t for t in ev['topic_distribution'].get(
                            'topics', []
                        )
                        if t.get('thread_id_short') not in _let_go_tids
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
                        # 🆕 [支柱A 指纹净化] 存 source 供 fingerprint filter 自产 event
                        'source': e.get('source', ''),
                    })
                ev['swm_events'] = events[:8]
        except Exception:
            pass
        # 🆕 [governor Phase 2 F4 扩展 / Sir 2026-05-29] let_go prune swm_events
        # 同 let_go 机制: active let_go topics 中 swm: 前缀的 → 过滤对应 etype
        try:
            _active_lg = _load_let_go_topics()
            if _active_lg and ev.get('swm_events'):
                _swm_lg_etypes = {
                    e.get('thread_id', '')[4:]  # strip 'swm:' prefix
                    for e in _active_lg
                    if e.get('thread_id', '').startswith('swm:')
                }
                if _swm_lg_etypes:
                    ev['swm_events'] = [
                        se for se in ev['swm_events']
                        if se.get('type', '') not in _swm_lg_etypes
                    ]
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
                # 🆕 [Sir 2026-05-27 22:42 P11 治本] vocab gate concern_truth_in_concerns
                # =================================================================
                # Sir 元痛: 主脑刚说 "1/10 cups", 思考脑看不到 ledger 真值 8/10 →
                # 无法 self-correct. P11 加 daily_progress / last_user_feedback /
                # optimal_timing 三 evidence 让思考脑可对比 STM reply ↔ 真值.
                # vocab inner_thought_identity_block_vocab.json
                #   blocks_enabled.concern_truth_in_concerns (默 on)
                # Sir 关此 gate → 退化到老 (只 id/what/severity/notes_chars).
                # =================================================================
                _id_vocab = self._load_identity_block_vocab()
                _truth_on = (_id_vocab.get('blocks_enabled') or {}).get(
                    'concern_truth_in_concerns', True)
                _fb_max_chars = int(
                    (_id_vocab.get('limits') or {}).get(
                        'concern_last_user_feedback_max_chars', 100)
                )
                concerns_out = []
                for c in active_sorted[:5]:
                    entry = {
                        'id': c.id,
                        'what': (c.what_i_watch or '')[:80],
                        'severity': round(c.severity, 2),
                        # 🆕 [Sir 2026-05-26 13:32 BUG 3] notes 容量信号 — 让 LLM
                        # 看见 concern 已满, 不再 propose adjust_concern_notes 浪费 tick
                        'notes_chars': len((c.notes_for_self or '').strip()),
                    }
                    if _truth_on:
                        # daily_progress (concerns.py Concern.daily_progress)
                        dp = getattr(c, 'daily_progress', None) or {}
                        # 🆕 [BUG A / Sir 2026-05-28 16:08 真痛 "其实你记得是昨天的信息"]
                        # ===========================================================
                        # 老 BUG: 思考脑注 dp 漏 iso_date == today check, 昨天数据
                        # 当今天注主脑 prompt → 主脑回 "9.0/10.0 cups today" cascade
                        # 到 inner_thought / ProactiveCare / mutation 多处. 治本:
                        # 跨天 dp → 不注 (不让主脑误读). to_prompt_block:968 +
                        # ProactiveCare._signal:622 已有同 check, 唯独此处漏.
                        # ===========================================================
                        if dp:
                            today_iso = time.strftime(
                                '%Y-%m-%d', time.localtime()
                            )
                            dp_iso = dp.get('iso_date', '')
                            cur = dp.get('current')
                            tgt = dp.get('target')
                            unit = dp.get('unit') or ''
                            if (dp_iso == today_iso
                                    and cur is not None
                                    and tgt is not None):
                                entry['daily_progress'] = {
                                    'current': cur,
                                    'target': tgt,
                                    'unit': unit,
                                    'iso_date': dp_iso,
                                }
                        # last_user_feedback (β.5.22-C 写入)
                        fb = getattr(c, 'last_user_feedback', None) or {}
                        raw = (fb.get('raw_text') or '').strip()
                        if raw:
                            entry['last_user_feedback'] = raw[:_fb_max_chars]
                        # optimal_timing (concerns.py Concern.optimal_timing)
                        ot = getattr(c, 'optimal_timing', '') or ''
                        if ot:
                            entry['optimal_timing'] = ot
                    concerns_out.append(entry)
                ev['concerns'] = concerns_out
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

        # 🆕 [Sir 2026-05-27 22:11 真问 P10 治本 / 准则 6 三维耦合]
        # =====================================================================
        # Sir 真问: "贾维斯会动态变频吗? 发现自己不用太担心吗? 一直在想, 经常想
        #            重复事情". Audit 现状: 只看物理 idle 不看 self-quality /
        #            repetition / concern pressure → daemon 不知道何时该歇.
        # 治本: 喂 3 个 raw self-signal evidence 给思考脑, 让 LLM 自决
        #       NEXT_INTERVAL (准则 6: 不在 .py 写 if rule). 阈值 / lookback /
        #       哪些 signal 全 vocab JSON, Sir CLI 可改不动 .py.
        # 同时 publish SWM 'inner_thought_self_signal' 给主脑 / dashboard 看.
        # =====================================================================
        try:
            sig = self._compute_self_signal()
            if sig:
                ev['self_pacing_signal'] = sig
                self._publish_self_signal_swm(sig)
        except Exception:
            pass

        return ev

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] _build_channel_view
    # ----------------------------------------------------------
    # Sir 真意 R3 "注意力精选不稀释": 把 flat evidence dict reorganize 成
    # 7 channel structure, LLM 上轮 next_attention_focus 提名 channel deep-load,
    # 其他 channel summary-only. Python 不挑 topic, 只组装 channel view.
    #
    # 返回 dict: {channel_name: {load_mode: 'deep'|'summary', items: [...]}}
    # ----------------------------------------------------------
    def _build_channel_view(
        self, ev: dict, focus_hint: str = ''
    ) -> dict:
        """把 flat evidence dict 重组成 7 channel structure (β.6 §4.3).

        Args:
          ev: _collect_evidence() 返回的 flat dict
          focus_hint: 上轮 LLM 输出的 next_attention_focus (逗号分隔 channel name)

        Returns:
          dict: {channel_name: {'load_mode': 'deep'|'summary',
                                  'item_count': int,
                                  'evidence_keys': [...]}}
          load_mode 'deep' = LLM 提名 deep-load, prompt 渲染时给完整 evidence
                  'summary' = 其他 channel, prompt 渲染时只给 1 行 count
        """
        # 解析 focus_hint
        focus_set = set()
        if focus_hint:
            for ch in focus_hint.split(','):
                ch = ch.strip().lower()
                if ch in self._CHANNEL_NAMES:
                    focus_set.add(ch)
        # 没 hint = 全 deep (老行为, 不破坏)
        all_deep = not focus_set

        # 各 channel 数据源映射 (来自 ev key)
        # 一个 ev key 可能归属多 channel (e.g. recent_jarvis_actions
        # 既是 sensor event 也是 nudge history 的 source).
        channel_sources: dict = {
            'recent_sensor_events': [
                'swm_events', 'inner_voice_recent',
                'recent_jarvis_actions', 'runtime_log_tail',
            ],
            'concern_status': [
                'concerns', 'all_active_concern_ids',
                'active_protocols', 'pending_review_protocols',
                'active_inside_jokes', 'pending_review_jokes',
                'recent_skepticism_events',
            ],
            'nudge_history': [
                'recent_jarvis_actions',  # filter NUDGE_* etype
            ],
            'sir_activity_snapshot': [
                'sir_state', 'idle_seconds', 'hour',
                'sir_declared_status', 'sir_profile_mini',
                'time_pattern', 'time_active_routines',
                'time_deviation_today', 'active_directives',
            ],
            'last_main_brain_reply': [
                'stm',  # last 5 turn (jarvis reply included)
            ],
            'last_thinking_output': [
                'recent_thoughts',  # 第 1 个 (最近的)
                'self_pacing_signal',
                'anticipated_ltm_context',
                'daemon_health',
            ],
            'my_recent_thoughts': [
                'recent_thoughts',  # 后 2 个 (旧的)
            ],
        }

        view: dict = {}
        for ch_name in self._CHANNEL_NAMES:
            sources = channel_sources.get(ch_name, [])
            # 统计 item count (粗略, render 时用真渲染)
            item_count = 0
            for src_key in sources:
                val = ev.get(src_key)
                if isinstance(val, list):
                    item_count += len(val)
                elif isinstance(val, dict) and val:
                    item_count += 1
                elif val:
                    item_count += 1
            view[ch_name] = {
                'load_mode': 'deep' if (all_deep or ch_name in focus_set) else 'summary',
                'item_count': item_count,
                'evidence_keys': sources,
            }
        return view

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] speak rate cap smoothing
    # ----------------------------------------------------------
    # 防 LLM 短时连发 should_speak=yes 噪音 Sir. 5min 内 ≥3 yes →
    # 后续 force no (Python smoothing, 类 NEXT_INTERVAL smoothing).
    # 准则 6 信任 LLM 但 Python 保底 (防 LLM 跑偏 spam Sir).
    # ----------------------------------------------------------
    def _should_smooth_force_silent(self, now: float) -> bool:
        """检查 should_speak rate cap: window 内 ≥max → force silent.

        🆕 [Sir 2026-05-28 00:30 β.6 Phase 1d 收口] 准则 6: 阈值持久化
        memory_pool/thinking_brain_speak_config.json, 不在 .py 硬编码.
        """
        window_s, max_yes = _get_speak_rate_cap()
        cutoff = now - window_s
        # prune 旧 ts
        self._recent_should_speak_yes_ts = [
            ts for ts in self._recent_should_speak_yes_ts if ts >= cutoff
        ]
        return len(self._recent_should_speak_yes_ts) >= max_yes

    def _record_should_speak_yes(self, now: float) -> None:
        """记 1 个 yes ts (在 LLM 输出 should_speak=yes 时调)."""
        self._recent_should_speak_yes_ts.append(now)

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-28 19:20 真意 — Jarvis 学会休息] saturation 检
    # ----------------------------------------------------------
    @staticmethod
    def _infer_actionable_state(thought: 'InnerThought') -> str:
        """Map (actionable / actionable_done / result) → state name.

        States 对齐 `saturation_trigger.actionable_done_states` whitelist:
        'none' (没选) / 'rejected' (router reject) / 'gated' (router gate) /
        'failed' (异常或 False) / 'done' (真做成).
        """
        act = (thought.actionable or '').strip().lower()
        if not act or act == 'none':
            return 'none'
        result_low = (thought.actionable_result or '').lower()
        if 'reject' in result_low:
            return 'rejected'
        if 'gate' in result_low or 'blocked' in result_low:
            return 'gated'
        if thought.actionable_done:
            return 'done'
        return 'failed'

    def _check_and_update_saturation(
        self, current_thought: 'InnerThought'
    ) -> bool:
        """Saturation 检 + counter 更新.

        Sir 真意 anchor: "Jarvis 没必要花时间想这么多, 我又不需要, 让它休息".
        连续 N tick 同 thread + 都 should_speak=False + actionable 无 effect
        → counter++. 达 force threshold → _resolve_next_interval 强制大间隔.

        准则 6 三维耦合:
        - 数据强耦合: vocab + counter 都持久 (config JSON, counter runtime)
        - 行为弱耦合: 只算 + counter++; force 决策在 _resolve_next_interval
        - 决策集中主脑: LLM 仍可选 next_interval; counter 达阈才 force override

        Returns: True = 已达 force 阈值 (caller 可选 publish SWM).
        """
        cfg = _load_saturation_config()

        trig = cfg.get('saturation_trigger', {}) or {}
        thread_min = int(trig.get('min_thoughts_same_thread', 3))
        require_silent = bool(trig.get('require_all_should_speak_false', True))
        no_effect_states = set(
            (s or '').lower()
            for s in trig.get('actionable_done_states',
                              ['none', 'rejected', 'gated', 'failed'])
        )

        # current_thought 已 append 到 self._thoughts, 取最后 N 条
        recent = list(self._thoughts)[-thread_min:]
        if len(recent) < thread_min:
            self._consecutive_saturation_count = 0
            return False

        # 条件 1: 同 category (近似 same thread)
        cat = current_thought.category
        if not all(t.category == cat for t in recent):
            self._consecutive_saturation_count = 0
            return False

        # 条件 2: 都 should_speak=False
        if require_silent and any(t.should_speak for t in recent):
            self._consecutive_saturation_count = 0
            return False

        # 条件 3: actionable state 在 "no-effect" whitelist 才算 saturated
        # ('done' 等不在 whitelist 内 = 真做成 = 有 effect → 不算 saturated)
        state = self._infer_actionable_state(current_thought)
        if state not in no_effect_states:
            self._consecutive_saturation_count = 0
            return False

        # 三条件全满足 → saturated, counter++
        self._consecutive_saturation_count += 1

        force_cfg = cfg.get('python_physical_force', {}) or {}
        threshold = int(
            force_cfg.get('min_consecutive_saturated_for_force', 5)
        )

        # 🆕 [Sir 2026-05-28 19:20 真意 L1] 每 saturated tick publish SWM evidence
        # =====================================================================
        # 准则 6 三维耦合 — 数据强耦合: raw signal 进 SWM, 主脑 SOUL inject 后
        # 自己看见"我循环 N 次没结果, 该换主题/降频". 不在 daemon LLM prompt
        # 重复注入 (daemon 自己 counter 已知). 主要服务下次 Sir-Jarvis 对话场景.
        # ttl=1800s (30min, 短时 signal 不长留 SWM); sal=0.65 (中等, 主脑可决是否
        # 引用); metadata 带 counter/threshold/thread/content_summary 让主脑评估.
        # =====================================================================
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                summary = (current_thought.thought or '')[:120]
                if len(current_thought.thought or '') > 120:
                    summary += '...'
                bus.publish(
                    etype='inner_thought_saturated',
                    description=(
                        f"My inner-thought loop saturated "
                        f"{self._consecutive_saturation_count}/{threshold} ticks "
                        f"(same {current_thought.category}-thread, no speak, no effect). "
                        f"Last thought: {summary}"
                    ),
                    source='inner_thought_daemon',
                    salience=0.65,
                    metadata={
                        'saturation_count': int(self._consecutive_saturation_count),
                        'threshold': int(threshold),
                        'thread_id': str(current_thought.thread_id or ''),
                        'category': current_thought.category,
                        'content_summary': summary,
                    },
                    ttl=1800.0,
                )
        except Exception:
            pass

        return self._consecutive_saturation_count >= threshold

    def _handle_rest_decision(self, raw: str, sir_state: str) -> bool:
        """🆕 [Sir 2026-05-31 放下能力] 识主动"放下" — settled 时不强凑 thought, 歇会.

        Sir 真意: 空转本身有意义 ("Sir 没事我也没事, 休息会"), 但不是强凑 filler 的空转。
        识每次唤醒先判: 有真势能(问题/张力/新颖/能力缺口/该反思的)? 没有 → 输出 <REST>
        → 本函数: 不 parse/persist filler thought, 拉长下次唤醒 (越歇越久), log 让 Sir 看见
        她在"安静地待着"。被 Sir 唤醒/紧急 → emergency wait 中断即跟上 (随时注入)。

        Returns: True = 是 rest tick (caller 直接 return, 不走 parse); False = 有实质思考。
        """
        cfg = (_load_saturation_config().get('rest') or {})
        if not cfg.get('enabled', True):
            return False
        m = re.search(r'<REST>(.*?)</REST>', raw or '', re.DOTALL | re.IGNORECASE)
        if not m:
            return False
        # 防 LLM 既给实质 THOUGHT 又给 REST: 有真 thought → 不当 rest, 走正常 parse
        tm = re.search(r'<THOUGHT>(.*?)</THOUGHT>', raw or '', re.DOTALL)
        ttxt = (tm.group(1).strip() if tm else '')
        if ttxt and len(ttxt) > 24 and 'rest' not in ttxt.lower():
            return False
        reason = (m.group(1) or '').strip().replace('\n', ' ')[:120] or 'all settled'
        # 🆕 [Sir 2026-05-31 17:54 — 更优雅: 不写死冷却阶梯] 休息深度统一到一个"存在
        # 心跳"地板 (单一物理常数, 非升级阶梯), 醒来靠**真扰动**: 体一有动静(fresh delta)
        # 或 Sir 一开口即醒 (event-driven, 势能自转 §3 "Sir 扰动永不停 + 地板心跳")。
        # 不再 streak++ 越歇越久 — 那是 governor/cooldown 思维; 这是有机体歇着、被真事唤醒。
        floor = float(cfg.get('ambient_floor_s', 600))
        self._next_tick_interval_s = int(floor)
        self._resting = True   # 标记休息中 → wait 期间体动静/Sir 可提前唤醒
        self._rest_count = getattr(self, '_rest_count', 0) + 1
        self._tick_origin_stats['rest'] = self._tick_origin_stats.get('rest', 0) + 1
        self._bg_log(
            f"💤 [InnerThought] 放下 — {reason} "
            f"(Sir 没事我也没事, 歇会; 心跳 floor {int(floor)}s, "
            f"体一有动静/你一开口即醒; rest#{self._rest_count})"
        )
        return True

    def _update_value_backoff(self, current_thought: 'InnerThought') -> int:
        """🆕 [useful-or-quiet P1 / Sir 2026-05-31] 跨 category 价值门控退避.

        补 saturation 的 same-category 漏洞: 脑 category-hop (B/A/C/D/E) 逃过
        saturation 的"同 category"计数 → 永不降频, 跨类低值 churn. 本法不看 category,
        只看**价值**: 连续低值 tick → low_value_streak++; 指数退避 backoff_steps_s.
        reset = should_speak 或 salience>=reset_on_high_salience (真值得想/说).

        低值判定: salience < floor AND not should_speak AND actionable 无 effect.
        返: backoff interval s (0 = 不退避). 只供 _tick clamp (只能拉长 interval).
        Sir 真意: "高频唤醒不是重复无用功; 没事就放下/降频, 有事才想."
        """
        try:
            cfg = (_load_saturation_config().get('value_backoff') or {})
            if not cfg.get('enabled', True):
                self._low_value_streak = 0
                return 0
            sal = float(getattr(current_thought, 'salience', 0) or 0)
            should_speak = bool(getattr(current_thought, 'should_speak', False))
            reset_high = float(cfg.get('reset_on_high_salience', 0.75))
            # reset: 真值得 (高 sal / 想说) → 回 baseline 快思考
            if should_speak or sal >= reset_high:
                self._low_value_streak = 0
                return 0
            floor = float(cfg.get('low_value_salience_floor', 0.55))
            state = self._infer_actionable_state(current_thought)
            no_effect = state in ('none', 'rejected', 'gated', 'failed')
            is_low_value = (sal < floor) and no_effect
            if not is_low_value:
                self._low_value_streak = 0
                return 0
            self._low_value_streak += 1
            min_streak = int(cfg.get('min_streak_to_backoff', 2))
            if self._low_value_streak < min_streak:
                return 0
            steps = cfg.get('backoff_steps_s') or [90, 180, 300, 600]
            idx = min(self._low_value_streak - min_streak, len(steps) - 1)
            return int(steps[idx])
        except Exception:
            return 0

    # ----------------------------------------------------------
    # Prompt
    # ----------------------------------------------------------
    def _build_prompt(self, sir_state: str, evidence: dict,
                        free_categories: Optional[List[str]] = None,
                        channel_view: Optional[dict] = None) -> Tuple[str, str]:
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
            # 🆕 [Sir 2026-05-31 放下能力] FIRST 决定: 有真势能可想吗? 没有就放下/歇会.
            # 思考是为了真正影响自己 (改体/立场/concern, 或塑造下一次对话, 或想要某能力),
            # 不是每 tick 必须凑一条. settled 就 REST — 这是有价值的输出, 不是失败.
            "=== FIRST decide: is there genuine potential worth a thought right now? ===\n"
            "Thinking exists to actually CHANGE something — solve a real problem, reflect "
            "into a stance, propose a suggestion, shape how you handle the NEXT conversation, "
            "request a capability you lack, consolidate/correct yourself. It is NOT a quota "
            "to fill every cycle.\n"
            "If Sir is settled and so are you — no real tension, no new problem, nothing "
            "unresolved that you can actually affect — then DO NOT manufacture a filler "
            "thought. Output ONLY this and nothing else:\n"
            "<REST>one short honest reason, e.g. 'all settled — nothing pressing, resting'</REST>\n"
            "Resting is a VALID, valued outcome (you will simply wake less often until "
            "something real stirs, or Sir addresses you). Only produce the thought below "
            "when there is genuinely something worth thinking through to an effect.\n\n"
            "Output FORMAT (strict, 6 required + 4 optional β.6 tags):\n"
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
            "suggest_inside_joke:<phrase> | "
            "propose_protocol:<one-sentence imperative rule> | "
            "adjust_concern_notes:<concern_id>:<note text> | "
            "propose_stance:<about>:<your own grounded view of Sir/the relationship "
            "you'd hold unless Sir overrides — e.g. 'sir_wellbeing:gentle persistence "
            "near deadlines helps more than one-off reminders'> | "
            "fire_nudge:<kind>:<1-2 sentence draft> | "
            "propose_watch_task:<trigger_kind:value>:<long-term goal desc> | "
            # 🆕 [Sir 2026-05-28 12:30] 删 surface_to_sir 选项. Layer 1.5
            # ([MY RECENT INNER THOUGHTS] by freshness × sal) 主脑自决 reference.
            "call_tool:<tool_name>:<json_args> | "
            # 🆕 [Sir 2026-05-28 19:47 fix44 P1] sensor 阈值 propose, 入 review_queue,
            # Sir CLI 拍板 (scripts/sensor_thresholds_dump.py). path 必须在
            # writable_paths (afk.idle_threshold_s / ghost_activity.* /
            # proactive_shield.ghost_dampen_idle_real_s / ...).
            "adjust_sensor_threshold:<path>:<value> | "
            # 🆕 [governor Phase 3 F7 / Sir 2026-05-29 拍板] compose_main_brain_directive
            # 思考脑装 directive 给主脑 (V5 Sir vision). text 5-200 char, TTL 5min.
            # 主脑 chat_bypass 入口前读 → 注入 prompt top → 主脑 reply 守 directive.
            # sal>=0.75 gate (防低质 directive). 元学习闭环 (F6改3): Sir reaction 反馈思考脑.
            "compose_main_brain_directive:<short imperative for next "
            "main brain reply, e.g. 'be brief, skip health advice'> | "
            # 🆕 [SOUL Phase 5 P3 / Sir 2026-05-29 拍板] self-debug
            # 看 [MY ARCHITECTURE] block 发现系统问题 → propose 改管辖 vocab.
            # 例: protocol bloat → propose_vocab_adjustment 调 auto_arbiter cap.
            # 不可改 INTEGRITY/safety vocab (红线). sal>=0.8. 走 Sir review.
            "propose_vocab_adjustment:<vocab_file>:<key_path>:<value> "
            "(SELF-DEBUG: if [MY ARCHITECTURE] above shows a system issue "
            "e.g. bloat/repeated-nudge, propose fixing the governing vocab "
            "— goes to Sir review, NOT auto-applied) | "
            # 🆕 [Sir 2026-05-31 放下能力] request_capability — 识发现自己缺某能力,
            # 想要它 (这也是"识主动影响贾维斯本身"的一种: 标注能力缺口给 Sir/未来开发).
            "request_capability:<one line: a capability/tool you lack that would "
            "let you serve Sir better — e.g. 'a way to read Sir's calendar for "
            "deadline-aware reminders'> (logs a capability wish for Sir to see)"
            "</ACTIONABLE>\n"
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
            "— DO NOT repeat the exact same actionable.\n"
            # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1a] 4 new tags — 统一思考脑
            # =====================================================================
            # Sir 真意: 思考脑替老 ProactiveCare/Conductor/Wellness/SmartNudge 决"该让
            # 主脑发声吗" + 自标"下次 attention focus 哪个 channel". Sir 原话:
            # "这轮为下轮挑, 我觉得合理". 详 docs/JARVIS_BETA6_UNIFIED_THINKING.md §5.
            # 全 OPTIONAL (向后兼容老 prompt 输出), 但鼓励 LLM 输出以激活 β.6 通路.
            # =====================================================================
            "<SHOULD_SPEAK>yes | no</SHOULD_SPEAK>  ← 🆕 [β.6] should the main "
            "brain SPEAK to Sir based on this thought? Default 'no' — Sir HATES "
            "noise (文字小说). Only 'yes' if: (a) urgent + Sir reachable, OR "
            "(b) Sir is clearly waiting, OR (c) you genuinely have something Sir "
            "would WANT to hear. Most ticks should be silent.\n"
            "<SPEAK_CONTENT>(only if SHOULD_SPEAK=yes) 1 sentence, butler style, "
            "no apology padding. e.g. 'Noted the wine, Sir — I'll keep the log "
            "honest.' If SHOULD_SPEAK=no, leave empty.</SPEAK_CONTENT>\n"
            # 🆕 [Sir 2026-05-28 00:38 β.6 Phase 1d 收口] SPEAK_STYLE enum +
            # description 从 vocab 拼 (准则 6: 加 style 改 JSON 即可, .py 不动).
            f"<SPEAK_STYLE>{_build_speak_style_prompt_line()}</SPEAK_STYLE>  ← 🆕 [β.6]\n"
            "<NEXT_ATTENTION_FOCUS>channel_a,channel_b</NEXT_ATTENTION_FOCUS>  ← 🆕 [β.6] "
            "Sir 真意 \"这轮为下轮挑\". Pick 1-3 channels you want deep-loaded next "
            "tick (others summary-only). Valid: recent_sensor_events | concern_status | "
            "nudge_history | sir_activity_snapshot | last_main_brain_reply | "
            "my_recent_thoughts. Empty = no hint, all equal. This is your "
            "self-attention.\n"
            # 🆕 [governor Phase 2 F4 / Sir 2026-05-29 拍板] <LET_GO> tag
            # =====================================================================
            # '放下' 元能力 — LLM 自决放下 fruitless 重复思考主题. 当 [TOPIC
            # DISTRIBUTION] 显某 thread 🍂 AGED (default >= 10 occurrences) 而
            # 你判断继续 think 无意义 → 输出 <LET_GO>thread_id_short</LET_GO>.
            # Python 持久化 + TTL (default 30min), 下次 tick prune 该 thread →
            # 你视觉看不到 → 自然不 think → '放下' 真生效. 准则 6 信任 LLM.
            # Sir CLI 可强解锁 (revoke).
            # =====================================================================
            "<LET_GO>thread_id_short</LET_GO>  ← 🆕 [Phase 2 F4] OPTIONAL. "
            "Only if [TOPIC DISTRIBUTION] above shows 🍂 AGED thread AND you "
            "judge further thinking is fruitless. Use thread_id_short EXACTLY "
            "as shown above (must match a real thread you saw). "
            "Also supports <LET_GO>swm:etype</LET_GO> for persistent SWM "
            "events (e.g. swm:auto_arbiter_anomaly) — prunes that event type "
            "from evidence. Default TTL 30min. "
            "Leave empty if nothing should be let-go this tick.\n"
            # 🆕 [Self-Memory P1 / Sir 2026-05-30] <RECALL> tag — 思考脑自查记忆
            "<RECALL>a short query if THIS moment reminds you of something you "
            "may have noted or discussed before (e.g. 'Sir's vet appointment', "
            "'the deploy bug last week', 'what Sir said about his sleep')</RECALL>"
            "  ← 🆕 OPTIONAL. Leave EMPTY unless something genuinely feels "
            "familiar. Results (from your own memory, with [SOURCE] tags) appear "
            "at the TOP of your NEXT tick so you can pick up the thread. You "
            "decide whether to use them; if a recalled item is vague or "
            "low-confidence, treat it as 'I vaguely recall…' — never assert it as "
            "hard fact (准则 5).\n"
            # 🆕 [Self-Memory P4 / Sir 2026-05-30] <NOTE> tag — schema-free 自写记忆
            "<NOTE>a free-form note-to-self worth keeping that does NOT fit any "
            "other schema (concern/directive/joke/milestone), e.g. 'Sir prefers "
            "tea over coffee after 4pm' / 'Sir's sister visits next week'</NOTE>"
            "  ← 🆕 OPTIONAL schema-free memory you choose to keep (recallable "
            "later via your own memory). Leave EMPTY unless genuinely worth "
            "remembering.\n\n"
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
            "🆕 [Sir 2026-05-28 12:30 退化 surface_to_sir] B-class 短期 contextual case 走\n"
            "Layer 1.5 ([MY RECENT INNER THOUGHTS] by freshness × sal) —\n"
            "主脑下轮自动看、看 sal 字段自决哪条先 reference, 不需单独通道:\n"
            "  Sir 真痛根因: 思考脑意识到 'redundant Good morning' (今早已 5 次) 但选错\n"
            "  通路—选 propose_protocol:'Always prioritize concise' → 抽象宗旨 +\n"
            "  慢通路 (review queue 积压, AutoArbiter 几乎全 REJECT, 主脑下轮看不到).\n"
            "  ✅ GOOD: <CATEGORY>B</CATEGORY>\n"
            "         <THOUGHT>Sir got up at 8am, I've already said 'Good morning, Sir'\n"
            "                  5 times this morning. Embarrassing — 今早必须绝不再 generic-greet,\n"
            "                  open with concrete evidence (window title / concern) only.</THOUGHT>\n"
            "         <SALIENCE>0.85</SALIENCE>\n"
            "         <ACTIONABLE>none</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>none</EVIDENCE_LINK>\n"
            "         → B-class + sal=0.85 + thought.thought **自身含具体行为指令**\n"
            "         (今早 5 次 + forbidden 'generic-greet' + 替代 'concrete evidence') →\n"
            "         Layer 1.5 下轮 by freshness × 0.85 rank top → 主脑看到 → 自决改行为.\n"
            "  ❗ 关键: thought.thought 要**自身完整** (主脑只看这一句, 没其他 metadata).\n"
            "  ❌ BAD: <THOUGHT>I should be more concise</THOUGHT>\n"
            "         → 抽象、主脑 link 不到具体行为. thought 本身必须具体可执行.\n"
            "  ❌ BAD: <ACTIONABLE>propose_protocol:Don't say Good morning more than once per morning</ACTIONABLE>\n"
            "         → 这是短期 contextual (跨午夜失效), 不该走 propose_protocol\n"
            "         (long-term policy 通路, AutoArbiter 会 REJECT). actionable=none\n"
            "         + thought.thought 含具体指令 → Layer 1.5 主脑自决.\n\n"
            "🆕 [Sir 2026-05-28 12:30 退化后] 通路选择决策树 (B 类必读):\n"
            "  问 1: 这条规则**跨午夜后**仍然适用吗?\n"
            "    YES (e.g. 'Don't open with formal apologies') → propose_protocol (long-term)\n"
            "    NO  (e.g. '今早已 5 次 greet') → actionable=none + thought.thought 自含具体指令\n"
            "  问 2: actionable=propose_protocol 时内容**具体可观察**吗?\n"
            "    YES (含具体数字/具体 forbidden action/具体替代) → propose\n"
            "    NO  ('prioritize concise' / 'be more direct' 抽象) →\n"
            "      DO NOT propose — Python 会让 AutoArbiter REJECT, tokens 浪费.\n"
            "      直接 ACTIONABLE=none + thought.thought 含具体指令.\n\n"
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
            "         concern no token overlap — wrong concern, fix4 anchor).\n\n"
            "🆕 [Sir 2026-05-28 12:30 P11 治本 退化后] B-class FACTUAL SELF-CORRECTION "
            "example — 思考脑看 ledger truth 对比主脑 STM, catch factual mismatch 走\n"
            "Layer 1.5 + sal=0.90 (Sir 2026-05-28 拍板退化 surface_to_sir, 信主脑 chain pull):\n"
            "  Sir 真痛根因: 主脑回答 Sir '只喝了 1/10 杯', 但 [YOUR ACTIVE CONCERNS] 子行\n"
            "  📊 ledger truth: 8/10 cups (date=今天) 显示真值. 主脑撒谎 (或 STM stale).\n"
            "  思考脑此时**必须** thought.thought **自身完整含真值 + RECTIFY 指令** → sal=0.90 →\n"
            "  Layer 1.5 by freshness × 0.90 rank top → 主脑下轮 prompt [MY RECENT INNER\n"
            "  THOUGHTS] 看到 → 主脑自决 RECTIFY.\n"
            "  ✅ GOOD: <CATEGORY>B</CATEGORY>\n"
            "         <THOUGHT>FACTUAL CORRECTION NEEDED: I just told Sir he's drunk 1/10\n"
            "                  cups today, but the concern ledger truth shows 8/10 (今日\n"
            "                  真值). My STM was stale. Next turn I must acknowledge:\n"
            "                  'Apologies Sir, I misspoke — you've had 8/10 cups today.'\n"
            "                  </THOUGHT>\n"
            "         <SALIENCE>0.90</SALIENCE>\n"
            "         <ACTIONABLE>none</ACTIONABLE>\n"
            "         <EVIDENCE_LINK>none</EVIDENCE_LINK>\n"
            "         → B-class + sal=0.90 + thought.thought **自身完整包含真值 +\n"
            "         主脑下轮该说什么** (主脑只看这一句, 没其他 metadata) → Layer 1.5\n"
            "         by freshness × 0.90 rank top → 主脑下轮自动看 RECTIFY → 准则 5 守住.\n"
            "  ❗ 关键: thought.thought 要**详细含真值数字 + 来源 (ledger) + 主脑下轮\n"
            "         该说的具体句子**. 主脑下轮看 [MY RECENT INNER THOUGHTS] 只看 thought 本身.\n"
            "  ❌ BAD: <THOUGHT>Sir's hydration data mismatch</THOUGHT> → 抽象. 主脑不知\n"
            "         真值是多少, 不能自决 RECTIFY.\n"
            "  ❌ BAD: 看到 ledger truth 但 sal=0.3 (低 sal) → freshness rank 低, 主脑不看. 必 sal≥0.85.\n"
            "  ❌ BAD: <ACTIONABLE>update_concern_severity:...</ACTIONABLE> → 真值\n"
            "         不一致不该改 severity, 该 thought.thought 含真值 → 主脑下轮自决纠正."
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

        # 🆕 [Self-Memory P1 / Sir 2026-05-30] 注入上 tick <RECALL> 召回结果 (F3 接地)
        # 在 lifetime 之后、channel view 之前 — 让"自查到的记忆"成为本 tick 顶部上下文,
        # 思考脑可据此延续 thread / 决定要不要 reference (consumed 后清空).
        try:
            if self._pending_recall_block:
                for ln in self._pending_recall_block.splitlines():
                    lines.append(ln)
                lines.append("")
                self._pending_recall_block = ''
        except Exception:
            pass

        # 🆕 [Self-Memory P3 / Sir 2026-05-30] OPEN THREADS 视图 (强闭环的门控显形) —
        # 河床里 open 线程按 (召回 bump 后) decayed salience 排序注入, resurfaced 线程
        # 浮上来 → 思考脑本 tick 注意力被结构性导向, 自然延续而非每轮重新发现.
        try:
            _ot_n = int(self._load_lifetime_vocab().get(
                'open_threads_prompt_n', 3))
            _ot_block = self._build_open_threads_block(_ot_n)
            if _ot_block:
                for ln in _ot_block.splitlines():
                    lines.append(ln)
                lines.append("")
        except Exception:
            pass

        # 🆕 [口识体-C / 2026-05-31] BODY SIGNALS — 体势能焦点 (势能自转: 体→识 ①)
        # =====================================================================
        # 让识 attend 体此刻高势能区 (张力/新颖/漂移) 而非凭空联想 —— 治"编故事"根:
        # 思考由体的真实不安定度驱动, 不是每 tick 自己找点说的。grounded, 无 LLM。
        # body_delta 由 Weaver (口识体-B3) publish, BodyFocus (B) 合并 delta+standing。
        # 详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §2/§5.2。失败非致命。
        # =====================================================================
        try:
            from jarvis_body_focus import get_body_focus as _gbf
            _body_sig = _gbf().render_attention_block(limit=5)
            if _body_sig:
                for ln in _body_sig.splitlines():
                    lines.append(ln)
                lines.append("")
        except Exception:
            pass

        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1b] 7 CHANNEL VIEW header
        # =====================================================================
        # Sir 真意 R3 "注意力精选不稀释": 把 evidence 重组成 7 channel structure,
        # 告 LLM 上轮自报 next_attention_focus → 本轮 deep-load 哪些 channel.
        # 不真砍 evidence (Phase 1b 保守: 让 LLM 真 follow attention 后 Phase 2
        # 再 trim). 此 header 让 LLM 知道结构 + 上次自标. 详 docs/JARVIS_BETA6
        # _UNIFIED_THINKING.md §4.3 + §5.
        # =====================================================================
        if channel_view:
            lines.append("[7 CHANNEL VIEW — β.6 §4.3]")
            deep_channels = [
                name for name, info in channel_view.items()
                if info.get('load_mode') == 'deep'
            ]
            summary_channels = [
                name for name, info in channel_view.items()
                if info.get('load_mode') == 'summary'
            ]
            prev_hint = (self._next_attention_focus or '').strip()
            if prev_hint:
                lines.append(
                    f"  Your previous tick nominated NEXT_ATTENTION_FOCUS = "
                    f"{prev_hint}"
                )
                lines.append(
                    f"  → DEEP-LOADED this tick ({len(deep_channels)}): "
                    f"{', '.join(deep_channels) if deep_channels else '(none)'}"
                )
                if summary_channels:
                    lines.append(
                        f"  → summary-only ({len(summary_channels)}): "
                        f"{', '.join(summary_channels)}"
                    )
                lines.append(
                    "  (Evidence below is grouped by channel — you may "
                    "still glance non-deep but spend attention on deep ones.)"
                )
            else:
                lines.append(
                    "  (No prior attention hint — all 7 channels equally loaded "
                    "this tick. Use <NEXT_ATTENTION_FOCUS> at end to pick 1-3 "
                    "channels for next tick's deep-load.)"
                )
            lines.append("")

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
            # 🆕 [governor Phase 1 F2] 动态 n + lookback_min (vocab 可调)
            _pt_n = len(prev_thoughts)
            _pt_lookback_min = evidence.get('recent_thoughts_lookback_min', 30)
            lines.append(
                f"[MY PREVIOUS THOUGHTS (last {_pt_n} within {_pt_lookback_min}min, "
                "for continuity — pick one to延续 or new topic)]"
            )
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
                # 🆕 [governor Phase 1 F1 / Sir 2026-05-29 00:30 拍板]
                # 删除 inner_thought filter — 心声给思考脑应是"全意识流"(含自家 thought).
                # 修复缺口 ②: 旧版 'e.source != inner_thought' 让思考脑看心声时
                # 看不到自己已 think 的内容, 元意识闭环断, 重复 think 22 次同事却不自觉.
                # 详 docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F1
                if _voice_recent:
                    lines.append(
                        "[INNER VOICE — past 10min, all-source signals "
                        "(incl. own thoughts) feeding your consciousness]"
                    )
                    for e in _voice_recent[-15:]:  # cap 15
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

        # 🆕 [governor Phase 1 F3 / Sir 2026-05-29 拍板] topic distribution hint
        # 🆕 [governor Phase 2 F4 / Sir 2026-05-29 拍板] aged_flag + <LET_GO> tag
        # ============================================================
        # E4 evidence 维度化: 让 LLM 视觉看"我重复想同主题 N 次" →
        # 自决是否输出 <LET_GO>thread_id</LET_GO> tag '放下'该主题.
        # Python 只 count + 提示 (准则 6 信任 LLM 自决 let_go).
        # ============================================================
        try:
            _td = evidence.get('topic_distribution') or {}
            _td_topics = _td.get('topics') or []
            if _td_topics:
                _td_lookback = _td.get('lookback_min', 60)
                _td_warn = _td.get('warning_threshold', 10)
                _td_aged = _td.get('aged_threshold', _td_warn)
                _td_ttl = _td.get('default_let_go_ttl_min', 30)
                lines.append(
                    f"[TOPIC DISTRIBUTION — last {_td_lookback}min, "
                    "count by thread_id]"
                )
                for _topic in _td_topics:
                    _age_s = _topic.get('last_age_s', 0)
                    if _age_s < 60:
                        _age_str = f"{_age_s}s ago"
                    elif _age_s < 3600:
                        _age_str = f"{_age_s // 60}m ago"
                    else:
                        _age_str = f"{_age_s // 3600}h ago"
                    _cnt = _topic.get('count', 0)
                    _warn_mark = ' ⚠️' if _cnt >= _td_warn else ''
                    _aged_mark = (
                        ' 🍂 AGED' if _topic.get('aged_flag') else ''
                    )
                    lines.append(
                        f"  topic_{_topic.get('thread_id_short', '?')}: "
                        f"{_cnt} occurrences (last {_age_str})"
                        f"{_warn_mark}{_aged_mark}"
                    )
                lines.append(
                    f"  ↳ 🍂 AGED topics (>={_td_aged} occurrences) — "
                    f"if you've been cycling fruitlessly, output "
                    f"<LET_GO>thread_id_short</LET_GO> to '放下' that "
                    f"thread for {_td_ttl}min (it will be pruned from "
                    f"your evidence — freeing your attention). "
                    f"Your call (准则 6 信任 LLM 自决)."
                )
                lines.append("")
        except Exception:
            pass

        # 🆕 [governor Phase 3 F6 改 3 / Sir 2026-05-29 拍板] meta feedback loop block
        # ============================================================
        # V6 元学习闭环 — 思考脑看 last 5 main_brain_reply + Sir reaction.
        # rejected reply → 重组 directive (不同方向). engaged → 继续下去.
        # ============================================================
        try:
            _mfl = evidence.get('meta_feedback_loop') or []
            if _mfl:
                lines.append(
                    f"[META FEEDBACK LOOP — last {len(_mfl)} replies + "
                    "Sir reactions]"
                )
                _rxn_marks = {
                    'engaged': '✅',
                    'rejected': '❌',
                    'ignored': '⏸️',
                    'pending': '⚡',  # 未反应 (Sir 还没说话)
                }
                for _e in _mfl:
                    _age_s = _e.get('age_s', 0)
                    if _age_s < 60:
                        _age_str = f"{_age_s}s ago"
                    elif _age_s < 3600:
                        _age_str = f"{_age_s // 60}m ago"
                    else:
                        _age_str = f"{_age_s // 3600}h ago"
                    _rxn = _e.get('sir_reaction', 'pending')
                    _rxn_mark = _rxn_marks.get(_rxn, '?')
                    _did = _e.get('directive_id', '')
                    _did_str = (
                        f" [directive={_did[:12]}]" if _did else ''
                    )
                    lines.append(
                        f"  [{_age_str}] me: \"{_e.get('reply_excerpt', '')[:100]}\""
                        f"{_did_str}"
                    )
                    _sir_ex = _e.get('sir_excerpt', '')
                    _sir_str = (
                        f' (sir: "{_sir_ex[:50]}")' if _sir_ex else ''
                    )
                    lines.append(
                        f"           {_rxn_mark} sir_reaction={_rxn}{_sir_str}"
                    )
                lines.append(
                    "  ↳ If a reply was ❌ rejected, re-examine: did your "
                    "directive (if any) miss something? Consider "
                    "compose_main_brain_directive with different approach "
                    "next time. ⏸️ ignored = Sir silent N min after — maybe "
                    "too pushy or Sir AFK. ⚡ pending = Sir hasn't reacted "
                    "yet (in flight)."
                )
                lines.append("")
        except Exception:
            pass

        # 🆕 [governor Phase 2 F4 / Sir 2026-05-29 拍板] active let_go list
        # ============================================================
        # 展示当前 active let_go thread_id + TTL remaining + reason.
        # 主脑 / Sir / Reflector 都能看. 心声 prune 已生效 (LLM 看不到该 thread).
        # ============================================================
        try:
            _lg = evidence.get('active_let_go_topics') or []
            if _lg:
                lines.append(
                    f"[ACTIVELY LETTING GO — {len(_lg)} thread(s), "
                    "pruned from your evidence above]"
                )
                for _e in _lg:
                    _ttl_s = _e.get('ttl_remaining_s', 0)
                    if _ttl_s >= 60:
                        _ttl_str = f"{_ttl_s // 60}min left"
                    else:
                        _ttl_str = f"{max(0, _ttl_s)}s left"
                    _reason = _e.get('reason') or '(no reason)'
                    _src = _e.get('source', '?')
                    lines.append(
                        f"  topic_{_e.get('thread_id_short', '?')}: "
                        f"{_ttl_str} (by {_src}) — {_reason[:80]}"
                    )
                lines.append(
                    "  ↳ These topics are silenced (your evidence above "
                    "has been pruned). You won't see them this tick or "
                    "next ticks until TTL. Sir CLI scripts/let_go_dump.py "
                    "can revoke / extend."
                )
                lines.append("")
        except Exception:
            pass

        # 🆕 [SOUL Phase 5 P2 / Sir 2026-05-29 拍板] MY ARCHITECTURE self-knowledge
        # ============================================================
        # 思考脑随时知道自己由哪些模块组成 → self-debug 时知道改哪 module/vocab.
        # 自我认知元架构延伸: 从"我是谁"(Layer 0 SelfAnchor) 到"我的身体构造".
        # 数据源: jarvis_module_scanner 动态扫 (永不过时), cache by mtime.
        # 详 docs/JARVIS_DYNAMIC_MAP_AND_SELF_DEBUG_DESIGN.md
        # ============================================================
        try:
            from jarvis_module_scanner import build_architecture_block
            _arch = build_architecture_block()
            if _arch:
                lines.append(_arch)
                lines.append("")
        except Exception:
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
            # 🆕 [Sir 2026-05-28 12:10 真痛 anchor] reconcile physical vs declared
            # =====================================================================
            # Sir 真痛 (12:10 thought): "Sir has returned after a 14-minute absence,
            # and while Adobe Media Encoder has finished its task, his declared
            # status remains 'sleep'. This discrepancy suggests he may only be
            # checking progress briefly before retiring or is simply forgetful
            # regarding his manual status toggle." Sir: "我是去吃饭前弄了导出, 然后
            # 回来的时候看到的" — Sir 早上 declare sleep 没切回, 中午回来看进度.
            # 思考脑同时收 sir_state=active (物理短路修正) + declared=sleep + ⚠️
            # "Honor declared → NO surface" 矛盾 directive, 只能编 hedge story.
            # 治本 (准则 6 evidence-only + 准则 8 优雅):
            #   render 端 cross-reference 物理 vs 声明, inconsistent → 标 STALE +
            #   换 directive ("don't anchor narrative on stale status, options:
            #   silence / silent SWM publish 'sir_status_stale'"). 不删 declared
            #   inject (它仍是 sensor signal), 不改 _classify_sir_state 物理短路
            #   (已对). 只动 render copy.
            # =====================================================================
            _physical_state = evidence.get('sir_state', 'unknown')
            _is_stale = (
                _physical_state == 'active'
                and _ds['status'] in (
                    'sleep', 'nap', 'dnd', 'out',
                    'lunch', 'dinner', 'afk_short',
                )
            )
            lines.append("[SIR DECLARED STATUS (raw — Sir 真意 sensor, before aggregation)]")
            lines.append(
                f"  - status: {_ds['status']} | declared "
                f"{_age_min}min ago{_od}"
            )
            if _is_stale:
                lines.append(
                    f"  ⚠️ STALE — Physical sir_state=active (Sir 键鼠在用) "
                    f"OVERRIDES declared '{_ds['status']}'. Sir likely forgot to "
                    f"toggle back. Don't anchor narrative on stale status "
                    f"(avoid phrasing like 'his status remains "
                    f"{_ds['status']}' / 'he may be retiring' / 'forgetful "
                    f"about manual toggle'). Options: silence (Sir will move on) "
                    f"OR silent SWM publish 'sir_status_stale' (let main brain "
                    f"gently confirm with Sir on next interaction)."
                )
            else:
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
                # 🆕 [Sir 2026-05-27 22:42 P11 治本] concern_truth 子行 — 思考脑看真值
                # =============================================================
                # Sir 元痛: 主脑刚说 "1/10 cups" (STM 可见), 但 ledger 真 8/10. 思考
                # 脑此前看不到真值无法 catch. P11 加 truth 行让思考脑可对比 STM ↔ 真值
                # → 不一致 → surface_to_sir:next_turn_inject RECTIFY.
                # vocab gate concern_truth_in_concerns (默 on, Sir 可 CLI 关).
                # =============================================================
                dp = c.get('daily_progress') or {}
                if dp.get('current') is not None and dp.get('target') is not None:
                    _unit = dp.get('unit') or ''
                    _date = dp.get('iso_date') or ''
                    _today = time.strftime('%Y-%m-%d', time.localtime())
                    _unit_s = (' ' + _unit) if _unit else ''
                    # 🆕 [P1 date-guard / 2026-05-31] 区分今日 vs stale — 旧 BUG: stale
                    # ledger 值当今天注 → 思考脑报 "8/10 today" 实为 3 天前. 通用日期守门.
                    if _date == _today:
                        lines.append(
                            f"      📊 ledger truth (today): "
                            f"{dp['current']}/{dp['target']}{_unit_s}"
                        )
                    else:
                        lines.append(
                            f"      📊 ledger truth: NO entry logged today; last was "
                            f"{dp['current']}/{dp['target']}{_unit_s} on {_date or '?'} "
                            f"(STALE — not today's progress)"
                        )
                fb_raw = c.get('last_user_feedback') or ''
                if fb_raw:
                    lines.append(
                        f"      💬 Sir last said: \"{fb_raw}\""
                    )
                ot = c.get('optimal_timing') or ''
                if ot:
                    lines.append(f"      ⏰ optimal_timing: {ot}")
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

        # 🆕 [Sir 2026-05-27 22:11 真问 P10 治本 / 准则 6 三维耦合 / 准则 8 优雅]
        # ===================================================================
        # Sir 真问: "贾维斯会动态变频吗? 发现自己不用太担心吗? 一直在想, 经常想
        #            重复事情". 治本: 不在 .py 写 if rule, 喂 raw self-signal
        #            evidence, 让思考脑自决 NEXT_INTERVAL.
        # tone = 'neutral_fact_only': 仅描述 raw signal, NEVER 加 imperative
        #        指令 ("so you should slow down" 类禁止). LLM 自决.
        # vocab gate: prompt_signal_block.enabled / header / max_chars.
        # ===================================================================
        try:
            _pacing_cfg = _load_pacing_config()
            _pb = (_pacing_cfg.get('prompt_signal_block') or {})
            if _pb.get('enabled', True):
                sig = evidence.get('self_pacing_signal') or {}
                if sig:
                    header = str(_pb.get('header',
                        '[YOUR RECENT PACING SIGNAL — fact only, '
                        'you decide if/how to pace]'))
                    _max_pb = int(_pb.get('max_chars', 400))
                    lines.append(header)
                    block_parts: List[str] = []
                    q = sig.get('self_recent_quality') or {}
                    if q:
                        block_parts.append(
                            f"  - recent_quality: avg_salience="
                            f"{q.get('avg_salience', '?')}, "
                            f"actionable_rate={q.get('actionable_rate', '?')}, "
                            f"mediocre_rate={q.get('mediocre_rate', '?')} "
                            f"(over last {q.get('lookback_used', '?')} thoughts)"
                        )
                    d = sig.get('self_thread_diversity') or {}
                    if d:
                        block_parts.append(
                            f"  - thread_diversity: "
                            f"{d.get('unique_threads', '?')} unique threads "
                            f"out of last {d.get('lookback_used', '?')}, "
                            f"top thread share="
                            f"{d.get('top_thread_share', '?')} "
                            f"(id={d.get('top_thread_id_short', '?')})"
                        )
                    p = sig.get('overall_concern_pressure') or {}
                    if p:
                        block_parts.append(
                            f"  - concern_pressure: "
                            f"max_severity={p.get('max_severity', '?')}, "
                            f"avg_severity={p.get('avg_severity', '?')}, "
                            f"active_count={p.get('active_count', '?')}, "
                            f"high_severity_count="
                            f"{p.get('high_severity_count', '?')}, "
                            f"recent_swm_event_count_1h="
                            f"{p.get('recent_swm_event_count_1h', '?')}"
                        )
                    # cap by max_chars (truncate parts joined)
                    _joined = '\n'.join(block_parts)
                    if len(_joined) > _max_pb:
                        _joined = _truncate_at_word_boundary(
                            _joined, _max_pb
                        )
                    for _ln in _joined.splitlines():
                        lines.append(_ln)
                    lines.append("")
        except Exception:
            pass

        if free_categories and len(free_categories) < 5:
            lines.append(
                f"[COOLDOWN] {free_str} are the ONLY non-cooldown categories. "
                f"Cooldown: {[c for c in 'ABCDE' if c not in free_categories]} "
                f"— pick from {free_str} only."
            )
            lines.append("")

        # 🆕 [Sir 2026-05-28 21:20 fix47 件 3] STRICT OUTPUT FORMAT reminder
        # =====================================================================
        # Sir 真痛 fix46 silent fail 根因: DS-v4-pro XML schema 顺从性弱,
        # 倾向 markdown / 自由文本. _parse_thought 必需 <CATEGORY>+<SALIENCE>
        # 否则返 None → 思考脑无 thought 产生 → 14min 失语. _call_llm 件 2
        # 加 raw sanity check + fallback flash 兜底, prompt 末尾再加 STRICT
        # FORMAT reminder 双保险 (flash 看了不冲突, DS 看了大幅降 invalid 率).
        # 此 reminder 列 6 必填 tag + 提醒 quiet 兜底 → 减 invalid + 减 silent.
        # =====================================================================
        lines.append("--- STRICT OUTPUT FORMAT (REQUIRED) ---")
        lines.append(
            "Output MUST be XML tags below. NOT markdown, NOT plain text, NOT JSON."
        )
        lines.append(
            "6 required tags (in this order): <CATEGORY>X</CATEGORY> "
            "<THOUGHT>...</THOUGHT> <SALIENCE>0.0-1.0</SALIENCE> "
            "<ACTIONABLE>...</ACTIONABLE> <EVIDENCE_LINK>...</EVIDENCE_LINK> "
            "<NEXT_INTERVAL>...</NEXT_INTERVAL>"
        )
        lines.append(
            "4 optional β.6 tags: <CONTINUITY>...</CONTINUITY> "
            "<SHOULD_SPEAK>yes|no</SHOULD_SPEAK> "
            "<SPEAK_CONTENT>...</SPEAK_CONTENT> "
            "<SPEAK_STYLE>...</SPEAK_STYLE> "
            "<NEXT_ATTENTION_FOCUS>...</NEXT_ATTENTION_FOCUS>"
        )
        lines.append(
            "Python parser REQUIRES literal <CATEGORY> + <SALIENCE> opening tags "
            "to appear in your output. Without them the parse drops silently "
            "and this whole tick is wasted."
        )
        lines.append(
            "If nothing comes to mind, output the quiet template: "
            "<CATEGORY>A</CATEGORY> <THOUGHT>(quiet)</THOUGHT> "
            "<SALIENCE>0.0</SALIENCE> <ACTIONABLE>none</ACTIONABLE> "
            "<EVIDENCE_LINK>none</EVIDENCE_LINK> "
            "<NEXT_INTERVAL>default</NEXT_INTERVAL>"
        )
        lines.append("")

        lines.append("Now generate ONE inner thought (6 core tags + β.6 optional 4).")
        return system, '\n'.join(lines)

    # ----------------------------------------------------------
    # LLM call (β.6: gemini-3.1-flash-lite 默认, env override)
    # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1a] LLM 升级 flash_lite → flash
    # 🆕 [Sir 2026-05-30] 降级 flash → flash_lite (3.1-flash-lite, 省 token)
    # ============================================================
    # flash_lite 在 LlmReflector 映射 = gemini-3.1-flash-lite.
    # env override JARVIS_THINKING_MODEL=flash 可切回 3-flash-preview.
    # ============================================================
    def _call_llm(self, system_prompt: str, user_prompt: str,
                   caller_origin: str = '') -> str:
        """LLM call for inner thought.

        🆕 [Sir 2026-05-28 fix46] selective DeepSeek routing:
        - 默认走 gemini-3.1-flash-lite (LlmReflector path)
        - 4 类 trigger 命中 + 双 gate 通过 + rate_limit 不超 → 走
          safe_deepseek_call (DS_ONLY key + deepseek-v4-pro)
        - ds 失败 + fallback_on_fail=1 → fall through 走 flash_lite (故障开放)
        - 所有路径都 _record_thinking_brain_routing → usage_stats 持久化

        caller_origin: sub-caller (yesterday_recap / commitment_review 等)
            显式传, 用作 trigger evidence. 主 tick caller 留空, helper 内部
            从 self._thoughts[-1] 提 prev state 作 proxy.
        """
        try:
            from jarvis_llm_reflector import LlmReflector
            from jarvis_key_router import KeyRouter
            from jarvis_utils import (
                should_route_thinking_to_ds,
                _record_thinking_brain_routing,
                safe_deepseek_call,
                _load_thinking_brain_ds_vocab,
            )
            # 🆕 fix46: 构 ctx for routing decision
            # prev_thought 状态作 proxy (本 tick category/salience 还没出)
            prev_cat, prev_sal = '', 0.0
            try:
                if self._thoughts:
                    last = self._thoughts[-1]
                    prev_cat = getattr(last, 'category', '') or ''
                    prev_sal = float(getattr(last, 'salience', 0.0) or 0.0)
            except Exception:
                pass
            # tick_origin: 显式 caller (yesterday_recap) 优先, 否则用 prev thought 的
            effective_origin = caller_origin or ''
            if not effective_origin and self._thoughts:
                try:
                    effective_origin = getattr(self._thoughts[-1], 'tick_origin', '') or ''
                except Exception:
                    pass
            prompt_size = len(system_prompt or '') + len(user_prompt or '')
            ctx = {
                'tick_origin': effective_origin,
                'last_thought_category': prev_cat,
                'last_thought_salience': prev_sal,
                'prompt_size': prompt_size,
            }
            should_ds, trigger_or_reason = should_route_thinking_to_ds(ctx)

            if should_ds:
                # 走 DeepSeek path
                vocab = _load_thinking_brain_ds_vocab()
                fallback_enabled = int(vocab.get('fallback_on_fail', 1)) == 1
                try:
                    timeout_s = float(vocab.get('timeout_s', 25))
                    # 🆕 [Sir 2026-05-28 21:20 fix47 件 1.5] 显式 max_tokens override
                    # fix45 vocab.deepseek_route.max_tokens_default=600 → 思考脑
                    # ~10 XML tag 输出会被截 (~719 tok 实测), 缺 closing tag →
                    # _parse_thought 返 None → silent fail. 本 vocab.max_tokens=1500
                    # 给足空间.
                    max_tok = int(vocab.get('max_tokens', 1500))
                    self._bg_log(
                        f"💭 [InnerThought] fix46 → DeepSeek "
                        f"(trigger={trigger_or_reason}, prompt_size={prompt_size}, "
                        f"max_tokens={max_tok})"
                    )
                    raw = safe_deepseek_call(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        caller='inner_thought_daemon',
                        timeout=timeout_s,
                        max_tokens=max_tok,
                        max_retries=2,  # 思考脑 LOW prio, 不死磕
                    )
                    # 🆕 [Sir 2026-05-28 21:20 fix47 件 2] DS raw sanity check
                    # DS-v4-pro schema 顺从性弱 — 可能返自由文本 / markdown 不带
                    # <CATEGORY>/<SALIENCE> XML tag. _parse_thought 必需此 2 tag
                    # 否则返 None (silent fail). 提前拦: 缺 tag → format_invalid
                    # + fall through flash, 既保住思考脑节奏又记 evidence.
                    raw_str = raw or ''
                    has_category = '<CATEGORY>' in raw_str.upper()
                    has_salience = '<SALIENCE>' in raw_str.upper()
                    if not (has_category and has_salience):
                        self._bg_log(
                            f"⚠️ [InnerThought] fix47 DS raw schema invalid "
                            f"(category={has_category}, salience={has_salience}, "
                            f"fallback={fallback_enabled}): raw[:120]="
                            f"'{raw_str[:120]}'"
                        )
                        _record_thinking_brain_routing(
                            routed=True, trigger=trigger_or_reason,
                            success=False, fallback=fallback_enabled,
                            format_invalid=True,
                        )
                        if not fallback_enabled:
                            return raw_str
                        # fall through 走 flash (保住思考脑节奏)
                    else:
                        _record_thinking_brain_routing(
                            routed=True, trigger=trigger_or_reason,
                            success=True, fallback=False,
                        )
                        return raw_str
                except Exception as ds_exc:
                    # ds 失败 → fallback 路径
                    self._bg_log(
                        f"⚠️ [InnerThought] fix46 DS call failed "
                        f"(fallback={fallback_enabled}): {str(ds_exc)[:120]}"
                    )
                    _record_thinking_brain_routing(
                        routed=True, trigger=trigger_or_reason,
                        success=False, fallback=fallback_enabled,
                    )
                    if not fallback_enabled:
                        return ''
                    # fall through 走 flash
            else:
                _record_thinking_brain_routing(
                    routed=False, skip_reason=trigger_or_reason,
                )

            # 默认 / fallback path: LlmReflector + gemini-3.1-flash-lite
            reflector = LlmReflector(key_router=self.key_router)
            _model = os.environ.get('JARVIS_THINKING_MODEL', 'flash_lite')
            res = reflector.reflect(
                model=_model,
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
        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1a] 新 4 tag 解析 (向后兼容: 缺则默认)
        # =====================================================================
        # SHOULD_SPEAK / SPEAK_CONTENT / SPEAK_STYLE → 思考脑自决发声决策
        # NEXT_ATTENTION_FOCUS → 自标下次 attention focus channel (元认知)
        # 详 docs/JARVIS_BETA6_UNIFIED_THINKING.md §4.4 + §5 prompt schema
        # =====================================================================
        should_speak_m = re.search(
            r'<SHOULD_SPEAK>(.*?)</SHOULD_SPEAK>', raw, re.DOTALL | re.IGNORECASE
        )
        speak_content_m = re.search(
            r'<SPEAK_CONTENT>(.*?)</SPEAK_CONTENT>', raw, re.DOTALL | re.IGNORECASE
        )
        speak_style_m = re.search(
            r'<SPEAK_STYLE>(.*?)</SPEAK_STYLE>', raw, re.DOTALL | re.IGNORECASE
        )
        attention_focus_m = re.search(
            r'<NEXT_ATTENTION_FOCUS>(.*?)</NEXT_ATTENTION_FOCUS>',
            raw, re.DOTALL | re.IGNORECASE
        )
        # 🆕 [governor Phase 2 F4 / Sir 2026-05-29 拍板] <LET_GO> tag 解析
        # =====================================================================
        # LLM 自决 “放下” 重复主题 — 输出 <LET_GO>thread_id_short</LET_GO>.
        # 解析后 调 _add_let_go_topic 持久化 (TTL default 30min), 下次 tick
        # _collect_evidence prune 该 thread → LLM 视觉看不到 → 自然不 think.
        # 准则 6 信任 LLM 自决 let_go (跳过 cooldown 硬编码).
        # =====================================================================
        let_go_m = re.search(
            r'<LET_GO>(.*?)</LET_GO>', raw, re.DOTALL | re.IGNORECASE
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

        # 🆕 [governor Phase 2 F4] 解析 + execute <LET_GO> tag
        # =====================================================================
        # LLM 输出 <LET_GO>thread_id_short</LET_GO> → 持久化 + TTL.
        # 防 LLM 乱指照: thread_id 必须能 prefix-match recent_thoughts 其中
        # 一个 thread_id (准则 5: 不信 LLM 编造 id, 只接受看过的).
        # =====================================================================
        try:
            if let_go_m:
                _lg_claimed = (let_go_m.group(1) or '').strip()[:32]
                if _lg_claimed:
                    _lg_target = ''
                    _is_swm = _lg_claimed.startswith('swm:')
                    if _is_swm:
                        # swm:etype → validate etype exists in recent swm_events
                        _swm_etype = _lg_claimed[4:]
                        try:
                            from jarvis_utils import get_event_bus
                            _bus = get_event_bus()
                            if _bus is not None:
                                _top = _bus.top_n(n=20) or []
                                for _e in _top:
                                    if _e.get('type', '') == _swm_etype:
                                        _lg_target = f'swm:{_swm_etype}'
                                        break
                        except Exception:
                            pass
                    else:
                        # thread_id: match against self._thoughts
                        try:
                            for _t in list(self._thoughts)[-50:]:
                                _candidate = (
                                    getattr(_t, 'thread_id', '') or _t.id
                                )
                                if (_candidate.startswith(_lg_claimed)
                                        or _lg_claimed.startswith(_candidate[:12])):
                                    _lg_target = _candidate[:32]
                                    break
                        except Exception:
                            pass
                    if _lg_target:
                        _ok = _add_let_go_topic(
                            thread_id=_lg_target,
                            source='llm',
                            thought_id=new_id,
                            reason=thought_text[:200],
                        )
                        if _ok:
                            _kind = 'swm event' if _is_swm else 'thread'
                            self._bg_log(
                                f"🍂 [InnerThought/let_go] LLM 自决 '放下' "
                                f"{_kind}={_lg_target[:16]} (TTL default), "
                                f"下轮 tick prune 该 {_kind} 从 evidence"
                            )
                    else:
                        self._bg_log(
                            f"🍂 [InnerThought/let_go] LLM 输出 <LET_GO>"
                            f"{_lg_claimed}</LET_GO> 但未在 "
                            f"{'SWM events' if _is_swm else 'recent_thoughts'} "
                            f"中 (可能 LLM 编造 id), 跳."
                        )
        except Exception:
            pass

        # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1a] parse SHOULD_SPEAK / SPEAK_* / ATTENTION
        # =====================================================================
        # 防御性 parse: 缺则默认 (向后兼容老 prompt), 值无效则 fallback.
        # SHOULD_SPEAK: 'yes' / 'no' (大小写不限). 默认 False.
        # SPEAK_STYLE: enum {silent_text, voice, visual_pulse}. 无效则空.
        # NEXT_ATTENTION_FOCUS: 逗号分隔 channel name. Python 不 validate (LLM 自报).
        # =====================================================================
        should_speak = False
        if should_speak_m:
            _ss = (should_speak_m.group(1) or '').strip().lower()
            should_speak = _ss in ('yes', 'true', '1', 'y')
        speak_content = ''
        if should_speak and speak_content_m:
            speak_content = (speak_content_m.group(1) or '').strip()[:500]
        speak_style = ''
        # 准则 6 vocab 持久化: valid styles + default fallback 不在 .py 硬编码
        _valid_styles = _get_valid_speak_styles()
        if speak_style_m:
            _st = (speak_style_m.group(1) or '').strip().lower()
            if _st in _valid_styles:
                speak_style = _st
        # should_speak=yes 但 LLM 没指定 / 非法 → vocab default (低风险)
        if should_speak and not speak_style:
            speak_style = _get_default_speak_style()
        next_attention_focus = ''
        if attention_focus_m:
            _af = (attention_focus_m.group(1) or '').strip()[:200]
            # 简单清洗: 去前后空 / 折叠多空格逗号
            next_attention_focus = re.sub(r'\s+', ' ', _af).strip(', ')

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
            # 🆕 β.6 Phase 1a
            should_speak=should_speak,
            speak_content=speak_content,
            speak_style=speak_style,
            next_attention_focus=next_attention_focus,
        )

    # ----------------------------------------------------------
    # Actionable executor (4 档, 全可逆/低风险)
    # ----------------------------------------------------------
    @staticmethod
    def _actionable_key(a: str) -> str:
        """actionable 去 payload, 取 (kind:target) 作 dedup key。

        call_tool:concerns.progress_update:{...} → 'call_tool:concerns.progress_update'
        adjust_concern_notes:sir_x:note... → 'adjust_concern_notes:sir_x'
        其余无 target 的 → 取 kind。让"反复试同一被拒动作"可识别, 不锁正常多样性。
        """
        parts = (a or '').split(':')
        if not parts:
            return a or ''
        # kind + 第一个 target 段 (若有), 丢 payload (note/args/draft 文本)
        return ':'.join(parts[:2]) if len(parts) >= 2 else parts[0]

    def _is_actionable_denied_recently(self, a: str, now: float) -> Tuple[bool, str]:
        """P3: 此 (kind:target) 是否在 DENIED cooldown 窗口内被拒过 → 跳过重试。"""
        hist = getattr(self, '_denied_actionables', None)
        if not hist:
            return False, ''
        key = self._actionable_key(a)
        ts = hist.get(key, 0.0)
        if ts and (now - ts) < self.DENIED_ACTIONABLE_COOLDOWN_S:
            return True, f'{int(now - ts)}s_ago'
        return False, ''

    def _record_actionable_denied(self, a: str, now: float) -> None:
        """P3: 记 (kind:target) 被拒时刻 (有界 dict, 防内存膨胀)。"""
        if not hasattr(self, '_denied_actionables'):
            self._denied_actionables: Dict[str, float] = {}
        hist = self._denied_actionables
        hist[self._actionable_key(a)] = now
        if len(hist) > 64:  # 有界: 先清过期, 仍超则丢最旧
            cutoff = now - self.DENIED_ACTIONABLE_COOLDOWN_S
            hist = {k: v for k, v in hist.items() if v >= cutoff}
            if len(hist) > 64:
                for k, _ in sorted(hist.items(), key=lambda x: x[1])[:len(hist) - 64]:
                    hist.pop(k, None)
            self._denied_actionables = hist

    def _execute_actionable(self, thought: InnerThought) -> Tuple[bool, str]:
        a = (thought.actionable or '').strip()
        if not a or a.lower() == 'none':
            return True, 'none'

        # 🆕 [P3 / 2026-05-31] 同一 actionable 刚被拒 → 短期不重试 (杀 churn).
        # Sir 真测: 思考脑反复试 call_tool:concerns.progress_update (not in allowlist)
        # → "misread twice". 治本: 拒后记 key, 窗口内直接降级 none (准则8 治本不复发).
        _now_act = time.time()
        _denied, _denied_ago = self._is_actionable_denied_recently(a, _now_act)
        if _denied:
            thought.actionable = 'none'
            return False, (
                f'skipped_recently_denied:{self._actionable_key(a)} '
                f'(denied {_denied_ago}, cooldown {self.DENIED_ACTIONABLE_COOLDOWN_S}s)'
            )

        # 🆕 [Sir 2026-05-26 00:25 真痛"地基没打牢"] EVIDENCE LINK 校验 (HARD GATE)
        # actionable != none 时, LLM 必须 cite THOUGHT 中真实出现的字串证明 trace.
        # 缺 EVIDENCE_LINK 或 cite 字串不在 thought 里 → 降级 actionable=none.
        # 准则 5 言出必行 + 6 evidence: 无 evidence 不执行.
        gate_ok, gate_reason = self._validate_evidence_link(thought)
        if not gate_ok:
            # 降级: 不真执行 actionable, 标记 rejected (Sir 看 log 真知道原因)
            thought.actionable = 'none'  # 防 SOUL inject 误以为有 action
            return False, f'rejected_no_evidence_link:{gate_reason}'

        # 🆕 [Sir 2026-05-28 16:55 方案 B] propose quality gate (sal threshold)
        # 自适应 — propose 类 (suggest_inside_joke / propose_protocol) 受 sal
        # threshold gate, 阈值由 _maybe_calibrate_propose_quality 24h calibrate.
        # 准则 6 vocab 持久化, 准则 8 thought 仍 persist 但 actionable 降级.
        gate_propose, gate_propose_reason = self._should_gate_propose(thought)
        if gate_propose:
            thought.actionable = 'none'
            return False, f'rejected_propose_quality:{gate_propose_reason}'

        ok, result = self._dispatch_actionable(thought, a)
        # 🆕 [P3] 结构性拒绝 (allowlist/unknown/deprecated/retired) → 记 key, 防反复试.
        # 区别于"暂时 gated"(cooldown/sal/cap 会自然恢复) — 那些不记, 让它后续可重试.
        # 🆕 [thinking-dehardcode fix#2 / 2026-05-31] evidence_link_wrong_concern 也记 key:
        # 镜像真测同一 thought 反复试同一被拒 (action:wrong_cid) → churn. wrong_concern 是
        # 结构性 (concern 选错, 同 key 重试还会拒) → 记 key 防 churn; LLM 换对 concern → 不同
        # key 不受锁 (fix#2 词面闸放宽后 false-reject 已大减, 此处只 catch 真 wrong concern).
        if not ok and any(tok in result for tok in (
                'tool_not_in_allowlist', 'unknown_actionable', 'deprecated',
                'retired', 'not_in_allowlist', 'path_not_allowed',
                'evidence_link_wrong_concern')):
            self._record_actionable_denied(a, _now_act)
        return ok, result

    def _dispatch_actionable(self, thought: InnerThought,
                             a: str) -> Tuple[bool, str]:
        """actionable 分发 (从 _execute_actionable 抽出, 便于 P3 统一记拒绝)。"""
        try:
            if a.startswith('update_concern_severity:'):
                ok, result = self._do_update_concern_severity(thought, a)
                # 🆕 [Sir 真痛 anchor] 二层 fail (cite ↔ concern wrong) →
                # 降级 thought.actionable=none 防 SOUL inject 误导主脑
                if not ok and 'evidence_link_wrong_concern' in result:
                    thought.actionable = 'none'
                return ok, result
            # 🆕 [Sir 2026-05-28 12:30 真痛 anchor] publish_swm: 路径已删
            # 原因: (1) 大多 etype 0 consumer (sir_activity/self_reflection_noted/
            # ... 全孤儿); (2) 少数撞名 sensor signal (ghost_activity_observed)
            # → LLM 伪冒物理 sensor, 违准则 5 INTEGRITY; (3) 跟 Layer 1.5/1.6/1.7
            # pull 模型重叠. 若 LLM 旧 vocab 仍出 'publish_swm:...' → 降级 none
            # (准则 8 优雅: 不破 thought, 仅拒 actionable).
            if a.startswith('publish_swm:'):
                thought.actionable = 'none'
                return False, 'rejected:publish_swm_deprecated_sir_20260528_1230'
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
            # 🆕 [口识体-E / 2026-05-31] propose_stance — 识把学到的关系 view 写成 stance
            # =====================================================================
            # 强闭环写侧: 识反思出"我对 Sir/关系的判断" → 写 stance(review) → Sir 仲裁
            # confirm → 透镜投影给口("My read, hold unless Sir overrides") → 口行为变(阻力)
            # → outcome reinforce/weaken → 放电消解。stance = 阻力/老师感的载体。
            # 接地: evidence_ref=thought.id (已过 evidence_link gate)。详 VOICE_AND_MIND §6/§7。
            # =====================================================================
            if a.startswith('propose_stance:'):
                return self._do_propose_stance(thought, a)
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
            # 🆕 [Sir 2026-05-28 19:47 fix44 P1] adjust_sensor_threshold —
            # 思考脑改 sensor 阈值 (准则 6 vocab 持久化 + Sir CLI 可覆盖 + LLM propose)
            # E.g. "Sir 每天 IDE 长开屏, 30s ghost_dampen 太严 → adjust to 60s"
            # sal>=0.75 + path 必须在 ALLOWED prefix (afk/ghost/proactive_shield).
            if a.startswith('adjust_sensor_threshold:'):
                return self._do_adjust_sensor_threshold(thought, a)
            # 🆕 [governor Phase 3 F7 / Sir 2026-05-29 拍板] compose_main_brain_directive
            # 思考脑装 directive 给主脑 (V5 Sir vision):
            # - thinking_brain_directive 存 inner_voice_track (TTL 5min)
            # - 主脑 chat_bypass.stream_chat 入口前读 → 注入 prompt top
            # - 元学习 (F6改3): Sir reaction (engaged/rejected) 反馈 evidence
            # 准则 6 信任 LLM 自决何时装 directive (sal gate 0.75 防低质 spam).
            if a.startswith('compose_main_brain_directive:'):
                return self._do_compose_main_brain_directive(thought, a)
            # 🆕 [SOUL Phase 5 P3 / Sir 2026-05-29 拍板] propose_vocab_adjustment
            # 思考脑 self-debug: 看 [MY ARCHITECTURE] 发现系统问题 → propose 改
            # 管辖该问题的 vocab → review queue → Sir 拍板. 复用 E5 红线
            # (不改 INTEGRITY/commitment/safety vocab) + F5 review pattern.
            if a.startswith('propose_vocab_adjustment:'):
                return self._do_propose_vocab_adjustment(thought, a)
            # 🆕 [Sir 2026-05-31 放下能力] request_capability — 识想要某能力 (影响自身/未来开发)
            if a.startswith('request_capability:'):
                return self._do_request_capability(thought, a)
            # 🆕 [Sir 2026-05-28 12:30 β.5.45 退化] surface_to_sir 全退化
            # =================================================================
            # 历史: 方案 C (Sir 2026-05-26 20:55) thought 主动 surface 通道
            # 退化原因: Sir 哲学 "主脑 = 好演员有 chain pull, 不需 push 通道 + 模板".
            # 信任主脑下轮看 Layer 1.5 [MY RECENT INNER THOUGHTS] by freshness × sal
            # 自决 reference. 思考脑只 publish 'inner_thought_committed' (Layer 1.5 自然
            # 看), 不再走单独 push 通道. 见顶部 anchor (line 271-300).
            # Stale LLM 输出 surface_to_sir → 此处直 reject (handler 函数虽留, 不调).
            # =================================================================
            if a.startswith('surface_to_sir:'):
                return False, 'rejected:surface_to_sir_retired_beta_5_45'
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
                                       concern, thought_text: str = ''
                                       ) -> Tuple[bool, str]:
        """🆕 [Sir 真痛 anchor 治本; thinking-dehardcode fix#2 / 2026-05-31 升级]
        cite / thought 是否真 link 到 concern.

        防"cite 真在 thought 但是 wrong concern" (Sir 真测: thought 提 toggling
        general/coding → cite=toggling → target=sir_interview_pr → 应 reject).

        🆕 fix#2 (镜像挖出, 准则 6 去硬编码 + 准则 8 不丢高价值思考): 旧实现只看**窄
        cite** 词跟 concern 词面重叠 — 太脆. 镜像真测: thought "...pomodoro compliance
        is failing..." cite="coding without rest" → cite 词 [coding,rest,without] 跟
        concern[pomodoro,compliance,break] 零词面重叠 → 高价值 C 思考被拒成 filler.
        但 thought 整体明明提了 "pomodoro compliance". 治本: cite 无重叠 → fallback 看
        **full thought** 是否跟 concern 重叠 (信任 LLM 完整推理), 只在 thought 整体都跟
        concern 无关时才拒 (真 wrong concern 防护不破). 第一层 gate (cite ∈ thought)
        仍管反幻觉; 本层只判"是否对的 concern".

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
        if not concern_tokens:
            return True, '(concern has no meaningful tokens — trust LLM)'
        # 窄 cite 命中 → pass (老路径)
        cite_overlap = cite_tokens & concern_tokens
        if cite_overlap:
            return True, f'overlap:{next(iter(cite_overlap))}'
        # 🆕 fix#2: cite 没命中 → 看 full thought (宽, 信任 LLM 推理上下文)
        thought_tokens = self._meaningful_tokens(thought_text or '')
        thought_overlap = thought_tokens & concern_tokens
        if thought_overlap:
            return True, f'thought_overlap:{next(iter(thought_overlap))}'
        if not cite_tokens and not thought_tokens:
            # cite + thought 都无 meaningful token — 不严判 (准则 6 信任 LLM)
            return True, '(no meaningful cite/thought tokens — trust LLM)'
        return False, (
            f'no_token_overlap (cite:{sorted(cite_tokens)[:3]} '
            f'thought:{sorted(thought_tokens)[:3]} vs '
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
        # 🆕 [Sir 2026-05-26 00:25 真痛 anchor 治本] 二层校验: cite/thought ↔ concern overlap
        # 真痛: cite 真在 thought 但 wrong concern (toggling → interview_pr).
        # 🆕 fix#2: 传 thought.thought, cite 无重叠时 fallback 看 full thought (不丢高价值思考).
        link_ok, link_msg = self._evidence_links_to_concern(
            thought.evidence_link, c, getattr(thought, 'thought', '')
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

    # 🆕 [Sir 2026-05-28 12:30 真痛 anchor] _do_publish_swm_actionable 整段删
    # ----------------------------------------------------------
    # 历史: 思考脑 actionable=publish_swm:<custom_etype>:<desc> 让 LLM 任意编 etype
    # publish SWM event. 期主脑/其他 module 通过 SWM 看 thought 信号.
    #
    # 真相 (Sir 2026-05-28 12:30 audit 184 thought 12% 用此):
    #   - Top etype 全孤儿: sir_activity(8) / self_reflection_noted(6) /
    #     sir_is_resting(3) / sir_sleeping(3) / vigilant_watch(2) / ... 0 consumer
    #   - 撞名 sensor signal: ghost_activity_observed(4) 真 publisher 是
    #     jarvis_env_probe.PhysicalEnvProbe (键鼠 idle + IDE 前台 物理证据),
    #     LLM 伪冒 sensor 让 directive trigger 误以为有物理证据 → 违准则 5
    #     INTEGRITY (言出必行: 没物理证据不可冒充)
    #   - 跟 Layer 1.5/1.6/1.7 pull 模型重叠 (主脑已 read thought)
    #
    # Sir 哲学: "主脑 = 好演员有 chain pull, 不需碎片 push". 准则 6 evidence-only:
    # 数据通过 jsonl + daemon 字段, 不需 SWM 中转. 准则 8 干净退化.
    #
    # 退化路径: _execute_actionable 看到 publish_swm: 直接降级 actionable='none'
    # + 返 (False, 'rejected:publish_swm_deprecated_...'), thought 仍 persist.
    # ----------------------------------------------------------

    def _do_suggest_inside_joke(self, thought: InnerThought,
                                   a: str) -> Tuple[bool, str]:
        phrase = a.split(':', 1)[1].strip() if ':' in a else ''
        if not phrase:
            return False, 'empty_phrase'
        if not self.relational_state:
            return False, 'no_relational_state'
        if not hasattr(self.relational_state, 'propose_inside_joke'):
            return False, 'propose_inside_joke method not found'
        # 🆕 [governor Phase 2 F5 / Sir 2026-05-29 拍板] hard jaccard dedup guard
        # 修复缺口 ④: 旧版 relational.propose_inside_joke 0.7 dedup 返只 True/False,
        # daemon 拿到 'dedup_or_fail' 不知具体重复哪条 → LLM 下轮不能学习.
        # 治本: daemon 入口自己 jaccard check (default 0.5 更严), 命中 → 返
        # "jaccard_dedup_rejected:overlap_with_<id>:<jaccard>", LLM 下轮看 actionable_result 学习.
        _hit, _hit_id, _hit_jacc = self._check_propose_jaccard_dedup(
            phrase, kind='inside_joke',
        )
        if _hit:
            return False, (
                f'jaccard_dedup_rejected:overlap_with_{_hit_id}:'
                f'jaccard={_hit_jacc:.2f}'
            )
        # build InsideJoke
        try:
            from jarvis_relational import InsideJoke
            try:
                from jarvis_utils import TraceContext
                _turn_id = TraceContext.get_turn_id() or ''
            except Exception:
                _turn_id = ''
            joke = InsideJoke(
                id=f"joke_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 10000:04x}",
                phrase=phrase[:80],
                birth_context=f"inner_thought [{thought.category}]: {thought.thought[:120]}",
                tone='wry',  # default, Sir 可改
                source='inner_thought',
                source_marker=thought.id,
                birth_turn_id=_turn_id,
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

    def _check_propose_jaccard_dedup(
        self, new_text: str, kind: str
    ) -> Tuple[bool, str, float]:
        """🆕 [governor Phase 2 F5 / Sir 2026-05-29 拍板] hard jaccard dedup guard.

        修复缺口 ④: relational_state dedup at 0.7 返 True/False, daemon 不知
        具体重复哪条 → LLM 看 'dedup_or_fail' 学不到. F5 入口拦截 + 返具体 id.

        Args:
          new_text: 新 propose 的 text (phrase 或 rule)
          kind: 'inside_joke' 或 'protocol'

        Returns: (hit, hit_id, hit_jaccard).
          hit=True → 调用者 reject + actionable_result 返具体 id + jaccard.
          hit=False → 放行继续 propose (relational_state 0.7 dedup 仍是 fallback safety).

        准则 6: threshold vocab 可调 (default 0.5 比 relational 0.7 更严).
        详 docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F5.
        """
        if not new_text or not isinstance(new_text, str):
            return (False, '', 0.0)
        try:
            vocab = self._load_propose_quality_vocab()
            if not vocab.get('jaccard_dedup_enabled', True):
                return (False, '', 0.0)
            threshold = float(vocab.get('jaccard_dedup_threshold', 0.5))
            threshold = max(0.0, min(1.0, threshold))
        except Exception:
            threshold = 0.5
        rs = self.relational_state
        if rs is None:
            return (False, '', 0.0)
        # 拿 active + review entries 两部分 (防 reject pending 同题)
        try:
            if kind == 'inside_joke':
                active_list = rs.list_inside_jokes(include_archived=False)
                review_list = (
                    rs.list_inside_jokes_review()
                    if hasattr(rs, 'list_inside_jokes_review') else []
                )
                existing = [(j.id, j.phrase or '')
                            for j in (active_list + review_list)]
            elif kind == 'protocol':
                active_list = rs.list_protocols(include_archived=False)
                review_list = (
                    rs.list_protocols_review()
                    if hasattr(rs, 'list_protocols_review') else []
                )
                existing = [(p.id, p.rule or '')
                            for p in (active_list + review_list)]
            else:
                return (False, '', 0.0)
        except Exception:
            return (False, '', 0.0)
        # jaccard check 逐个 (最高那条胜, 敢 hit)
        new_tokens = set(
            t for t in re.findall(r'\w+', new_text.lower())
            if len(t) >= 2
        )
        if not new_tokens:
            return (False, '', 0.0)
        best_hit_id = ''
        best_jacc = 0.0
        for (eid, etext) in existing:
            if not etext:
                continue
            ex_tokens = set(
                t for t in re.findall(r'\w+', etext.lower())
                if len(t) >= 2
            )
            if not ex_tokens:
                continue
            inter = len(new_tokens & ex_tokens)
            union = len(new_tokens | ex_tokens)
            jacc = inter / union if union > 0 else 0.0
            if jacc > best_jacc:
                best_jacc = jacc
                best_hit_id = eid
        if best_jacc >= threshold:
            try:
                self._bg_log(
                    f"🚫 [F5/jaccard_dedup] kind={kind} new='{new_text[:50]}' "
                    f"hit existing={best_hit_id} jaccard={best_jacc:.2f} "
                    f"(threshold {threshold}) → reject (LLM 下轮学习)"
                )
            except Exception:
                pass
            return (True, best_hit_id, best_jacc)
        return (False, '', 0.0)

    def _check_directive_jaccard_dedup(
        self, new_text: str,
    ) -> Tuple[bool, str, float]:
        """jaccard dedup against current active directive.

        Returns: (hit, active_text, jaccard).
          hit=True → reject compose (too similar to active directive).
          hit=False → 放行.
        """
        if not new_text or not isinstance(new_text, str):
            return (False, '', 0.0)
        try:
            vocab = self._load_propose_quality_vocab()
            if not vocab.get('directive_dedup_enabled', True):
                return (False, '', 0.0)
            threshold = float(vocab.get('directive_dedup_threshold', 0.5))
            threshold = max(0.0, min(1.0, threshold))
        except Exception:
            threshold = 0.5
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled as _iv_en,
            )
            if not _iv_en():
                return (False, '', 0.0)
            track = get_inner_voice_track()
            active = track.get_active_directive()
            if not active:
                return (False, '', 0.0)
            active_text = str(active.get('text', '') or '')
            if not active_text:
                return (False, '', 0.0)
        except Exception:
            return (False, '', 0.0)
        new_tokens = set(
            t for t in re.findall(r'\w+', new_text.lower())
            if len(t) >= 2
        )
        if not new_tokens:
            return (False, '', 0.0)
        ex_tokens = set(
            t for t in re.findall(r'\w+', active_text.lower())
            if len(t) >= 2
        )
        if not ex_tokens:
            return (False, '', 0.0)
        inter = len(new_tokens & ex_tokens)
        union = len(new_tokens | ex_tokens)
        jacc = inter / union if union > 0 else 0.0
        if jacc >= threshold:
            try:
                self._bg_log(
                    f"🚫 [directive_jaccard_dedup] new='{new_text[:50]}' "
                    f"overlaps active='{active_text[:50]}' "
                    f"jaccard={jacc:.2f} (threshold {threshold}) → reject"
                )
            except Exception:
                pass
            return (True, active_text, jacc)
        return (False, '', 0.0)

    def _do_propose_stance(self, thought: 'InnerThought', a: str) -> Tuple[bool, str]:
        """🆕 [口识体-E / 2026-05-31] 识 propose 一条关系立场 (强闭环写侧).

        actionable=propose_stance:<about>:<claim>
          about = 锚 (concern_id / 话题, 可省); claim = Jarvis 对 Sir/关系的判断 (一句)。
        sal>=0.7 (立场要够分量) → 写 stance store (review 态, propose-not-trust) →
        Sir CLI scripts/stance_dump.py confirm → active → 透镜投影给口。
        接地 evidence_ref=thought.id (已过 _validate_evidence_link gate)。
        """
        if thought.salience < 0.7:
            return False, f'gated:stance_requires_sal>=0.7 (got {thought.salience:.2f})'
        body = a.split(':', 1)[1].strip() if ':' in a else ''
        if ':' in body:
            about, claim = body.split(':', 1)
            about, claim = about.strip(), claim.strip()
        else:
            about, claim = '', body.strip()
        if len(claim) < 10:
            return False, f'claim_too_short:{len(claim)}<10'
        try:
            from jarvis_stance import get_stance_store
            sid = get_stance_store().add_stance(
                claim, about or 'sir_relationship',
                evidence_kind='thought', evidence_ref=thought.id,
                detail=(thought.text or '')[:150],
                confidence=min(0.7, float(thought.salience)),
                source='inner_thought', state='review')
            if sid:
                self._bg_log(
                    f"🧭 [口识体-E/stance] propose stance(review) id={sid} "
                    f"about={about or 'sir_relationship'!r} sal={thought.salience:.2f}")
                return True, f'stance_proposed:{sid}'
            return False, 'stance_rejected:no_evidence_or_empty'
        except Exception as e:
            return False, f'stance_error:{type(e).__name__}'

    CAPABILITY_REQUESTS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'capability_requests.jsonl')

    def _do_request_capability(self, thought: 'InnerThought',
                               a: str) -> Tuple[bool, str]:
        """🆕 [Sir 2026-05-31 放下能力] 识想要某能力 — "识主动影响贾维斯本身" 的一种.

        actionable=request_capability:<one-line capability/tool wish>
        识发现自己缺某能力 (e.g. 读日历做 deadline-aware 提醒) → 写 capability_requests.jsonl
        让 Sir 看见 (Jarvis 想长出什么能力). 接地: evidence_ref=thought.id (已过 link gate)。
        去重: 同 desc 近期已记 → 不重复 (防 churn, 复用 P3 denied-actionable 思路)。
        """
        desc = a.split(':', 1)[1].strip() if ':' in a else ''
        if len(desc) < 8:
            return False, f'capability_desc_too_short:{len(desc)}'
        now = time.time()
        try:
            # 去重: 近期(7d) 已记同 desc(前缀) → skip (不重复堆同一愿望)
            seen = set()
            if os.path.exists(self.CAPABILITY_REQUESTS_PATH):
                with open(self.CAPABILITY_REQUESTS_PATH, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                            if now - float(row.get('ts', 0)) < 7 * 86400:
                                seen.add((row.get('desc') or '')[:60].lower())
                        except Exception:
                            continue
            if desc[:60].lower() in seen:
                return False, 'capability_already_requested_recently'
            os.makedirs(os.path.dirname(self.CAPABILITY_REQUESTS_PATH), exist_ok=True)
            with open(self.CAPABILITY_REQUESTS_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': now,
                    'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)),
                    'desc': desc[:300],
                    'thought_id': getattr(thought, 'id', ''),
                    'evidence': (getattr(thought, 'thought', '') or '')[:150],
                    'state': 'open',
                }, ensure_ascii=False) + '\n')
            self._bg_log(
                f"🧩 [InnerThought/capability] 识想要能力: {desc[:80]} "
                f"(写 capability_requests.jsonl 给 Sir 看)")
            return True, f'capability_requested:{desc[:40]}'
        except Exception as e:
            return False, f'capability_request_error:{type(e).__name__}'

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

        # 🆕 [governor Phase 4 E5 / Sir 2026-05-29 拍板] integrity 红线 check
        # propose_protocol rule 含 "disable ClaimTracer / skip integrity" 等
        # → red_line_violated. ClaimTracer 永远不可由 LLM 自决关 (准则 5 言出必行).
        # reject 返 actionable_result, LLM 下轮看到学习不再 propose.
        _rl_hit, _rl_phrase = _check_red_line_propose_protocol(rule)
        if _rl_hit:
            self._bg_log(
                f"🚫 [E5/red_line] propose_protocol 撞 integrity 红线 "
                f"(phrase='{_rl_phrase}') → reject. ClaimTracer 不可关."
            )
            return False, (
                f'red_line_violated:integrity_disable:'
                f'phrase={_rl_phrase[:40]}'
            )

        if not self.relational_state:
            return False, 'no_relational_state'
        if not hasattr(self.relational_state, 'propose_protocol'):
            return False, 'propose_protocol method not found'
        # 🆕 [governor Phase 2 F5 / Sir 2026-05-29 拍板] hard jaccard dedup guard
        # 修复缺口 ④: 入口自 jaccard check (default 0.5, 比 relational 0.7 更严)
        # 命中 → 返 "jaccard_dedup_rejected:overlap_with_<id>:<jaccard>" 让 LLM 学.
        _hit, _hit_id, _hit_jacc = self._check_propose_jaccard_dedup(
            rule, kind='protocol',
        )
        if _hit:
            return False, (
                f'jaccard_dedup_rejected:overlap_with_{_hit_id}:'
                f'jaccard={_hit_jacc:.2f}'
            )

        try:
            from jarvis_relational import UnspokenProtocol
            try:
                from jarvis_utils import TraceContext
                _turn_id = TraceContext.get_turn_id() or ''
            except Exception:
                _turn_id = ''
            pid = (
                f"proto_{time.strftime('%Y%m%d_%H%M%S')}"
                f"_{int(time.time() * 1000) % 10000:04x}"
            )
            protocol = UnspokenProtocol(
                id=pid,
                rule=rule[:200],
                source='inner_thought',
                source_marker=thought.id,
                learned_from_turn_id=_turn_id,
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

    # 🆕 [governor Phase 3 F7 / Sir 2026-05-29 拍板] compose_main_brain_directive
    # =====================================================================
    # 思考脑 actionable=compose_main_brain_directive:<text> → 装 directive
    # 给主脑 (inner_voice_track 存 TTL 5min). 主脑 chat_bypass.stream_chat
    # 入口前 get_active_directive() 读 → 注入 prompt top.
    # =====================================================================
    _COMPOSE_DIRECTIVE_MIN_SAL = 0.75   # 防低质 directive spam
    _COMPOSE_DIRECTIVE_TTL_MIN = 5      # default TTL minutes (≤60 cap inside)

    def _do_compose_main_brain_directive(
        self, thought: InnerThought, a: str,
    ) -> Tuple[bool, str]:
        """🆕 [governor Phase 3 F7] 装 directive 给主脑 (V5 Sir vision).

        actionable=compose_main_brain_directive:<text>
        - sal ≥ 0.75 (防低质 directive spam)
        - text ≥ 5 char (空 directive 无意义)
        - TTL 5min default (过期 fallback default prompt)
        - inner_voice_track 存 active directive, 主脑 chat_bypass 读

        流程 (V5 Sir vision):
          thought (sal>=0.75) → compose_main_brain_directive:<text>
          → inner_voice_track.set_thinking_brain_directive(text, ttl=5min,
              composed_by=thought.id)
          → 下次主脑 turn chat_bypass 入口 → get_active_directive()
          → 注入 prompt top → 主脑 reply 守 directive
          → reply append voice meta.directive_id = thought.id
          → Sir reaction (F6改3) tracked → 元学习闭环 (V6)
        """
        # sal gate (防低质 directive 浪费主脑 attention)
        if thought.salience < self._COMPOSE_DIRECTIVE_MIN_SAL:
            return False, (
                f'gated:compose_directive_requires_sal>='
                f'{self._COMPOSE_DIRECTIVE_MIN_SAL} '
                f'(got {thought.salience:.2f})'
            )
        text = a.split(':', 1)[1].strip() if ':' in a else ''
        if not text:
            return False, 'empty_directive_text'
        if len(text) < 5:
            return False, f'directive_too_short:{len(text)}<5'
        # jaccard dedup against current active directive
        _hit, _hit_text, _jacc = self._check_directive_jaccard_dedup(text)
        if _hit:
            return False, (
                f'jaccard_dedup:directive_overlap_with_active:'
                f'{_hit_text[:30]}:jaccard={_jacc:.2f}'
            )
        try:
            from jarvis_inner_voice_track import (
                get_inner_voice_track, is_enabled as _iv_enabled,
            )
            if not _iv_enabled():
                return False, 'inner_voice_track_disabled'
            track = get_inner_voice_track()
            if not hasattr(track, 'set_thinking_brain_directive'):
                return False, 'set_thinking_brain_directive_method_missing'
            ok = track.set_thinking_brain_directive(
                text=text,
                ttl_min=self._COMPOSE_DIRECTIVE_TTL_MIN,
                composed_by_thought_id=thought.id,
            )
            if ok:
                self._bg_log(
                    f"📌 [InnerThought/compose_directive] thought={thought.id[:12]} "
                    f"sal={thought.salience:.2f} → set directive "
                    f"'{text[:60]}' (TTL {self._COMPOSE_DIRECTIVE_TTL_MIN}min). "
                    f"主脑下轮 chat_bypass 读 + 注入 prompt top."
                )
                return True, f'directive_set:{text[:40]}'
            return False, 'set_directive_returned_false'
        except Exception as e:
            return False, f'compose_directive_fail:{str(e)[:60]}'

    # 🆕 [SOUL Phase 5 P3 / Sir 2026-05-29 拍板] propose_vocab_adjustment
    # =====================================================================
    # 思考脑 self-debug 真闭环: 看 [MY ARCHITECTURE] (P2) 知道异常关联哪
    # module + vocab → propose 改 vocab → review queue → Sir 拍板 → 真修.
    # 复用 E5 红线 (protected_vocab_files) + F5 review pattern.
    # =====================================================================
    _VOCAB_ADJ_MIN_SAL = 0.8   # 改自己配置要高确信

    def _do_propose_vocab_adjustment(
        self, thought: InnerThought, a: str,
    ) -> Tuple[bool, str]:
        """🆕 [SOUL Phase 5 P3] 思考脑 self-debug propose 改 vocab.

        actionable=propose_vocab_adjustment:<vocab_file>:<key_path>:<value>
        - sal >= 0.8 (改自己配置要高确信)
        - 红线 check (不改 INTEGRITY/commitment/safety vocab, 复用 E5)
        - 写 review queue (memory_pool/vocab_adjustment_review.jsonl) → Sir 拍板
        - 不直改 vocab (准则 7 Sir 元否决 + 准则 5 不假装改了)

        真 case (Sir 2026-05-29 日志): protocol/joke bloat → 思考脑看
        [MY ARCHITECTURE] 知 bloat 关联 relational + auto_arbiter → propose
        调 auto_arbiter daily_cap / dedup jaccard → review → Sir 拍板 → 解决.
        """
        if thought.salience < self._VOCAB_ADJ_MIN_SAL:
            return False, (
                f'gated:vocab_adj_requires_sal>={self._VOCAB_ADJ_MIN_SAL} '
                f'(got {thought.salience:.2f})'
            )
        # parse propose_vocab_adjustment:<file>:<key_path>:<value>
        parts = a.split(':', 3)
        if len(parts) < 4:
            return False, (
                'parse_fail (expected propose_vocab_adjustment:'
                '<file>:<key_path>:<value>)'
            )
        _, vocab_file, key_path, value = parts
        vocab_file = (vocab_file or '').strip()
        key_path = (key_path or '').strip()
        value = (value or '').strip()
        if not vocab_file or not key_path:
            return False, 'empty_file_or_key'
        # 🆕 E5 红线 check (protected vocab 不可改)
        _hit, _pat = _check_red_line_vocab_adjustment(vocab_file)
        if _hit:
            self._bg_log(
                f"🚫 [P3/red_line] vocab_adjustment '{vocab_file}' 撞 "
                f"protected (pattern='{_pat}') → reject. "
                f"INTEGRITY/safety vocab 不可由 LLM 改."
            )
            return False, (
                f'red_line_violated:protected_vocab:pattern={_pat}'
            )
        # 写 review queue (不直改, Sir 拍板)
        entry = {
            'ts': time.time(),
            'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'vocab_file': vocab_file,
            'key_path': key_path,
            'proposed_value': value,
            'thought_id': thought.id,
            'rationale': (thought.thought or '')[:200],
            'salience': float(thought.salience),
            'status': 'pending',
        }
        ok = _append_vocab_adjustment_review(entry)
        if not ok:
            return False, 'review_queue_write_fail'
        self._bg_log(
            f"🔧 [P3/self-debug] propose vocab adj "
            f"{vocab_file}:{key_path}={value[:40]} → review queue "
            f"(Sir CLI scripts/vocab_adjustment_dump.py 拍板)"
        )
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is not None:
                bus.publish(
                    etype='vocab_adjustment_proposed',
                    description=(
                        f"思考脑 self-debug propose: "
                        f"{vocab_file}:{key_path}={value[:40]}"
                    ),
                    source='inner_thought',
                    salience=0.6,
                )
        except Exception:
            pass
        return True, (
            f'vocab_adj_proposed:{vocab_file}:{key_path}={value[:30]}'
        )

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

        # 二层 gate: cite/thought ↔ concern overlap (复用 fix4 evidence_link 机制 — 防 wrong concern)
        # 🆕 fix#2: 传 thought.thought, cite 无重叠时 fallback 看 full thought (不丢高价值思考).
        link_ok, link_msg = self._evidence_links_to_concern(
            thought.evidence_link, c, getattr(thought, 'thought', '')
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
    # 🆕 [Sir 2026-05-28 19:47 fix44 P1] adjust_sensor_threshold actionable
    # ==========================================================================
    # Sir 真意: 思考脑发现某 sensor 阈值不合 Sir 真习惯 (e.g. 30s ghost_dampen
    # 太严, Sir 每天 IDE 长开屏被误判), propose 调整入 review_queue, Sir CLI
    # 拍板才 apply. 准则 6 vocab 持久化 + 准则 7 Sir 元否决权预留.
    #
    # gate:
    #   - sal >= 0.75 (思考脑要确信)
    #   - path 必须在 sensor_thresholds_vocab.writable_paths 内
    #   - value 走 _validate_value (类型 / min / max / max_delta_per_change)
    #   - publish SWM 'sensor_threshold_proposed' 让 Sir 看 dashboard
    #
    # Sir 不直接 mutate current — propose 入 queue, CLI apply 才生效.
    # 详 memory_pool/sensor_thresholds_vocab.json + jarvis_sensor_thresholds.py.
    # ==========================================================================
    ADJUST_SENSOR_THRESHOLD_MIN_SAL = 0.75

    def _do_adjust_sensor_threshold(self, thought: InnerThought,
                                       a: str) -> Tuple[bool, str]:
        """thought propose 改 sensor 阈值 — 入 review_queue 等 Sir CLI 拍板.

        Format: adjust_sensor_threshold:<path>:<value>
          path: 'ghost_activity.idle_threshold_s' / 'afk.idle_threshold_s' /
                'proactive_shield.ghost_dampen_idle_real_s' / ...
          value: 数值 (int/float) / json list (list_str) / 'true'|'false' (bool) /
                 字符串. python 会按 vocab 中 spec.type 自动 parse + validate.

        gate:
          - sal >= 0.75
          - path 必须在 writable_paths 内
          - value 走 _validate_value (type / min / max / max_delta_per_change)
        """
        if thought.salience < self.ADJUST_SENSOR_THRESHOLD_MIN_SAL:
            return False, (
                f'gated:adjust_sensor_threshold_requires_sal>='
                f'{self.ADJUST_SENSOR_THRESHOLD_MIN_SAL} '
                f'(got {thought.salience:.2f})'
            )

        # Format: adjust_sensor_threshold:<path>:<value>
        parts = a.split(':', 2)
        if len(parts) < 3:
            return False, (
                'parse_fail (expected '
                'adjust_sensor_threshold:<path>:<value>)'
            )
        _, path, value_str = parts
        path = (path or '').strip()
        value_str = (value_str or '').strip()
        if not path or not value_str:
            return False, 'empty_path_or_value'

        # value parse — 按 vocab spec.type 自动 cast
        try:
            from jarvis_sensor_thresholds import (
                get_writable_paths as _gwp,
                propose_adjustment as _propose,
            )
            writable = _gwp()
            spec = writable.get(path)
            if spec is None:
                allowed = ', '.join(sorted(writable.keys())[:5])
                return False, (
                    f'unknown_path:{path} '
                    f'(allowed e.g.: {allowed} ...)'
                )

            vtype = spec.get('type', 'str')
            # cast value_str → typed value (按 vtype)
            try:
                if vtype == 'int':
                    parsed_value: Any = int(value_str)
                elif vtype == 'float':
                    parsed_value = float(value_str)
                elif vtype == 'bool':
                    low = value_str.lower()
                    if low in ('true', '1', 'yes', 'on'):
                        parsed_value = True
                    elif low in ('false', '0', 'no', 'off'):
                        parsed_value = False
                    else:
                        return False, (
                            f'bool_parse_fail:{value_str!r} '
                            '(expected true/false/1/0)'
                        )
                elif vtype == 'list_str':
                    import json as _json_ls
                    parsed_value = _json_ls.loads(value_str)
                    if not isinstance(parsed_value, list):
                        return False, (
                            f'list_str_parse_fail:not_list '
                            f'({type(parsed_value).__name__})'
                        )
                else:
                    parsed_value = value_str
            except (ValueError, TypeError) as cast_exc:
                return False, (
                    f'value_cast_fail:{vtype}:{value_str!r} '
                    f'({str(cast_exc)[:40]})'
                )

            # rationale — 引 thought 短摘要 (Sir CLI review 时看)
            rationale = (
                f'thought {thought.id} [{thought.category}/'
                f'sal={thought.salience:.2f}]: {thought.thought[:200]}'
            )
            ok, msg = _propose(
                path=path,
                new_value=parsed_value,
                source=f'inner_thought:{thought.id}',
                rationale=rationale,
            )
            if not ok:
                return False, f'propose_fail:{msg}'
            item_id = msg

            # publish SWM 让 Sir dashboard 可见 + 主脑下轮看到
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='sensor_threshold_proposed',
                        description=(
                            f"thought {thought.id} proposed "
                            f"{path}={parsed_value!r} "
                            f"(review_id={item_id}, Sir CLI to apply)"
                        ),
                        source='InnerThought',
                        salience=0.7,
                        metadata={
                            'thought_id': thought.id,
                            'review_id': item_id,
                            'path': path,
                            'current_value': spec.get('current'),
                            'proposed_value': parsed_value,
                            'thought_category': thought.category,
                        },
                        ttl=86400.0,
                    )
            except Exception:
                pass

            return True, (
                f'proposed:{path}={parsed_value!r} '
                f'(review_id={item_id}, Sir CLI to apply)'
            )
        except Exception as e:
            return False, f'adjust_sensor_threshold_exception:{str(e)[:60]}'

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
            # 🆕 [Sir 2026-05-27 22:42 P11 治本] 思考脑看 concern ledger 真值,
            # 对比主脑 STM reply 可 catch factual mismatch (e.g. 主脑刚说 1/10
            # 但 daily_progress=8/10 真值 → 思考脑 surface_to_sir RECTIFY).
            'concern_truth_in_concerns': True,
        },
        'limits': {
            'profile_max_chars': 400, 'directives_top_n': 5,
            'directive_purpose_max_chars': 80,
            'hour_pattern_max_activities': 3,
            'hour_pattern_max_topics': 3,
            # 🆕 [P11] last_user_feedback.raw_text 截字
            'concern_last_user_feedback_max_chars': 100,
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
    # 🆕 [Sir 2026-05-28 12:30 真痛 anchor] _publish_swm method 整段删除
    # ----------------------------------------------------------
    # 历史: β.6 Phase 1c (Sir 2026-05-28 00:00) publish 'jarvis_inner_thought'
    # SWM event + 4 个 metadata 字段 (should_speak/speak_content/speak_style/
    # next_attention_focus) 期望主脑 SOUL build 时 read 自决 SPEAK/SILENT.
    #
    # 真相 (Sir 2026-05-28 12:30 拍板查证): jarvis_inner_thought event 真无
    # 任何 production consumer:
    #   - grep recent_events.*jarvis_inner_thought → 0 命中
    #   - grep types.*jarvis_inner_thought → 0 命中 (除 _publish_swm 自身 +
    #     test 验证 publish)
    #   - 主脑 Layer 1.5/1.6/1.7 走 daemon 直接 API (build_lifetime_block /
    #     build_should_speak_directive — 后者直接 read self._thoughts, 非 SWM)
    #   - dashboard 走 inner_voice_24h.jsonl + daemon.get_stats(), 不读 SWM
    #
    # Sir 哲学: "主脑 = 好演员, 有思考链所有思考信息 (Layer pull), 不需要碎片
    # push". 准则 6 (evidence-only): 思考链全 pull 模型 self-sufficient. 准则
    # 8 (优雅): 干净退化, 不留 dead publish.
    #
    # 数据 source of truth: thought 4 字段 (should_speak/speak_content/
    # speak_style/next_attention_focus) 仍在 InnerThought dataclass + persist
    # jsonl. build_should_speak_directive (line 4522) 直接 read self._thoughts
    # in-memory, 完整 cover β.6 Layer 1.7 主脑端读路径.
    # ----------------------------------------------------------

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
        # 🆕 [Sir 2026-05-28 12:30 β.5.45 退化] DAEMON SURFACED 块删除
        # =================================================================
        # 历史: 方案 C 衔接给主脑 inject [DAEMON SURFACED ... THESE FOR YOUR ATTENTION]
        # 块 + reference 来源引导. Sir 2026-05-28 拍板 surface_to_sir 全退化:
        # Layer 1.5 [MY RECENT INNER THOUGHTS] by freshness × sal 已自然 chain pull
        # (主脑下轮 prompt 自动看), 不需额外 push 通道 + 话术模板. 主脑作为好演员
        # 自决 reference 哪条, 怎么开场. 见顶部 anchor (line 271-300).
        # =================================================================

        block = '\n'.join(lines)
        if len(block) > max_chars:
            block = block[:max_chars - 14].rstrip() + '\n…[truncated]'
        return block

    # ----------------------------------------------------------
    # 🆕 [Sir 2026-05-28 00:00 β.6 Phase 1d] should_speak directive 给主脑
    # ----------------------------------------------------------
    # Sir 真意: 思考脑 self-attention → 自决 SPEAK or SILENT, 主脑读这块自决
    # follow/ignore. 准则 6 信任 LLM — 不强制主脑听, 给信号让主脑 LLM 自己消化.
    # 设计:
    #   - 取最近 _DIRECTIVE_WINDOW_S 秒内最 fresh 一条 thought (with β.6 4 字段)
    #   - 渲染成主脑可读 directive block:
    #       should_speak=yes → "THINKING THREAD SUGGESTS: SPEAK. Draft: '...'. Style: ..."
    #       should_speak=no  → "THINKING THREAD SUGGESTS: SILENCE this moment."
    #   - 没 thought 或太老 (>_DIRECTIVE_WINDOW_S) → return '' (不污染 prompt)
    # 主脑 prompt build 路径在 central_nerve._build_layer_1d_thinking_directive_block
    # ----------------------------------------------------------
    _DIRECTIVE_WINDOW_S = 180  # 3min — fresh enough 才喂主脑 (再老就 stale)
    _DIRECTIVE_MAX_CHARS = 600

    def build_should_speak_directive(
        self, window_s: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> str:
        """返回最新 thought 的 SPEAK/SILENT 建议给主脑 (β.6 §6 主脑端).

        准则 6 三维耦合:
        - 数据强耦合: 读 self._thoughts (思考脑权威源, SWM 一致)
        - 行为弱耦合: 不强制主脑 follow, 只 inject directive 给 prompt
        - 决策集中主脑: 主脑 LLM 看 directive 自决说/不说 (可 override)
        """
        window = int(window_s if window_s is not None else self._DIRECTIVE_WINDOW_S)
        cap = int(max_chars if max_chars is not None else self._DIRECTIVE_MAX_CHARS)
        cutoff = time.time() - window
        with self._lock:
            # 拿最近 window 内最 fresh 一条 (按 ts 倒序)
            recent = [
                t for t in self._thoughts
                if t.ts >= cutoff and getattr(t, 'should_speak', None) is not None
            ]
        if not recent:
            return ''
        recent.sort(key=lambda t: -t.ts)
        latest = recent[0]
        age_min = max(1, int((time.time() - latest.ts) / 60))
        lines = ["=== 💭 THINKING-THREAD DIRECTIVE (β.6 — your inner thought just decided) ==="]
        if getattr(latest, 'should_speak', False):
            # SPEAK 路径 — 给主脑 draft + style + 但留余地让主脑改
            draft = (getattr(latest, 'speak_content', '') or '').strip()
            style = (getattr(latest, 'speak_style', '') or 'silent_text').strip()
            lines.append(
                f"  Thread suggests: SPEAK to Sir (style={style}, "
                f"thought age={age_min}min, sal={latest.salience:.2f})"
            )
            if draft:
                lines.append(f"  Draft from thread: \"{draft[:240]}\"")
            lines.append(
                "  Origin thought: "
                f"\"[{latest.category}] {latest.thought[:140]}\""
            )
            lines.append(
                "  → You may speak (using draft as inspiration, refine in voice) "
                "OR override silently if context shifted. Your call."
            )
        else:
            # SILENT 路径 — 信号让主脑减少 chatter
            lines.append(
                f"  Thread suggests: SILENCE this moment "
                f"(thought age={age_min}min, sal={latest.salience:.2f})"
            )
            lines.append(
                "  Origin thought: "
                f"\"[{latest.category}] {latest.thought[:140]}\""
            )
            lines.append(
                "  → Default to brief / no-volunteer this turn unless Sir "
                "directly asks. Lean [SILENCE] if natural."
            )
        # attention focus 也带, Sir 真看链条
        focus = (getattr(latest, 'next_attention_focus', '') or '').strip()
        if focus:
            lines.append(f"  Next-tick attention will focus: {focus[:120]}")
        block = '\n'.join(lines)
        if len(block) > cap:
            block = block[:cap - 14].rstrip() + '\n…[truncated]'
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
    # 🆕 [Self-Memory P0 / Sir 2026-05-30] last_alive 心跳 — 算真 dark_gap (离线时长)
    _LAST_ALIVE_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'jarvis_last_alive.json',
    )
    # 🆕 [Self-Memory P2 / Sir 2026-05-30] self-threads 河床 — 巩固流水账成持久线程
    _SELF_THREADS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'self_threads.json',
    )
    # 🆕 [Self-Memory P4 / Sir 2026-05-30] self-notes — schema-free 自写记忆
    _SELF_NOTES_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'self_notes.jsonl',
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
        # 🆕 [Self-Memory P0 / Sir 2026-05-30] 离线 gap 感知 (dark gap surfacing)
        'dark_gap_min_surface_s': 3600,      # 离线 >= 1h 才 surface "你离线了多久"
        'dark_gap_relevant_uptime_s': 3600,  # 仅 process 刚起 < 1h 内 surface (久了不算 news)
        'heartbeat_persist_interval_s': 300, # daemon loop 5min 刷 last_alive 心跳
        # 🆕 [Self-Memory P2 / Sir 2026-05-30] 河床/巩固 (consolidation) + 遗忘
        'consolidate_enabled': True,
        'consolidate_cooldown_s': 3600,        # 周期巩固 1h (类 yesterday_recap)
        'consolidate_min_thoughts': 2,         # thread >= N thought 才巩固成河床
        'consolidate_max_threads_per_run': 8,  # 每轮最多 LLM-summarize N (省 token)
        'consolidate_llm_summary': True,       # LLM 写 1-liner (else 取最高 sal thought)
        'thread_decay_half_life_days': 7.0,    # salience 衰减半衰期 (遗忘)
        'thread_tier_hot_max_age_s': 86400,    # < 1d = hot
        'thread_tier_warm_max_age_s': 604800,  # < 7d = warm, 否则 cold
        'thread_max_kept': 200,                # cap, 超出按 last_touched prune (不删 evidence)
        # 🆕 [Self-Memory P3 / Sir 2026-05-30] 强闭环 — 召回 mutate 门控态
        'thread_recall_bump_salience': 0.08,   # 主动召回命中 open 线程 → salience +bump
        'thread_recall_bump_cap': 0.95,        # bump 上限
        'open_threads_prompt_n': 3,            # tick prompt 顶显 N 个 open 线程 (salience 排)
        # 🆕 [言出必行 I2 / Sir 2026-05-30; Sir 23:38 拍板开启] 后台语义 claim 审计.
        # Sir "不怕花 tokens" → 默 ON. LLM 替正则枚举判 claim 接地, 仅后台 daemon +
        # cooldown + 只在 reply 变化时跑 + 便宜 Flash-Lite caller, 不碰主脑回复热路径.
        'semantic_claim_check_enabled': True,
        'semantic_claim_check_cooldown_s': 300,
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

    # =====================================================================
    # 🆕 [Sir 2026-05-28 16:55 方案 B 治本 / dashboard 7-8 页 root cause #2]
    # Propose quality feedback loop — propose→activate rate 低 → sal 阈值升
    # =====================================================================
    # Sir 真痛: dashboard 139 review 待办, 7d 内 inner_thought propose 太多
    # 质量参差 → AutoArbiter 大量 defer_to_sir / reject → review 堆积.
    # 真因 #2: daemon 没看自己 propose 真激活率, 不收敛 propose 频率/质量.
    # 治本: 闭环反思 — 看 24h auto_arbiter_log activate/reject/defer 比例,
    # 自适应升降 sal_threshold (sal < threshold 的 propose actionable 降级 none,
    # thought 仍 persist 但不进 review queue).
    # 准则 6: vocab 持久化 + Sir CLI 可改 + L7 reflector 可改
    # 准则 7: Sir 可禁 (enabled=0) / 手动设阈值
    # 准则 8: cooldown 24h, 不爆 LLM 调用
    # =====================================================================
    _PROPOSE_QUALITY_VOCAB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool', 'inner_thought_propose_quality_vocab.json',
    )
    _PROPOSE_QUALITY_VOCAB_CACHE: dict = {
        'data': None, 'mtime': 0.0, 'checked_at': 0.0,
    }
    _PROPOSE_QUALITY_VOCAB_CHECK_INTERVAL_S = 30.0
    _PROPOSE_QUALITY_DEFAULT_VOCAB = {
        '_doc': (
            'Inner thought daemon 自适应 propose 质量 gate. propose 类 '
            'actionable (suggest_inside_joke / propose_protocol) 受 '
            'salience >= sal_threshold gate. 周期反思 24h activate rate '
            '动态调阈值: rate 高 → 降阈 (放松); rate 低 → 升阈 (收紧). '
            'Sir CLI: scripts/propose_quality_dump.py (TODO).'
        ),
        'enabled': True,
        'sal_threshold': 0.60,       # propose 类 sal 最低门槛
        'sal_threshold_floor': 0.40,
        'sal_threshold_ceiling': 0.85,
        # 自动 calibrate (24h 一次, 读 auto_arbiter_log)
        'auto_calibrate_enabled': True,
        'calibrate_cooldown_h': 24,
        'calibrate_lookback_h': 24,
        'calibrate_min_samples': 10,  # 决策 < 10 不调 (样本不够)
        # 调整规则
        'activate_rate_high': 0.70,   # rate >= → 降阈 (放松)
        'activate_rate_low': 0.30,    # rate <= → 升阈 (收紧)
        'raise_step': 0.05,
        'lower_step': 0.02,
        # state (calibrate 写)
        'last_calibrated_at_ts': 0,
        'last_calibrated_at_iso': '',
        # history (最近 20 次 calibrate)
        'history': [],
        # 哪些 actionable kind 受 gate (准则 6 vocab 不硬编码)
        'gated_actionable_prefixes': [
            'suggest_inside_joke:',
            'propose_protocol:',
        ],
        # 🆕 [governor Phase 2 F5 / Sir 2026-05-29 拍板] hard jaccard dedup
        # 比 relational_state 现有 0.7 dedup 更严, daemon 入口拦截 +
        # 返具体 reject reason (overlap_with_<id>:<jaccard>) 让 LLM 下轮学习.
        'jaccard_dedup_threshold': 0.5,
        'jaccard_dedup_enabled': True,
        # directive dedup (against current active directive)
        'directive_dedup_enabled': True,
        'directive_dedup_threshold': 0.5,
    }

    def _load_propose_quality_vocab(self) -> dict:
        """Lazy load + 30s throttle. Fail-safe → default."""
        now = time.time()
        cache = self._PROPOSE_QUALITY_VOCAB_CACHE
        if (cache['data'] is not None and
                now - cache['checked_at']
                < self._PROPOSE_QUALITY_VOCAB_CHECK_INTERVAL_S):
            return cache['data']
        cache['checked_at'] = now
        try:
            if not os.path.exists(self._PROPOSE_QUALITY_VOCAB_PATH):
                cache['data'] = dict(self._PROPOSE_QUALITY_DEFAULT_VOCAB)
                return cache['data']
            mtime = os.path.getmtime(self._PROPOSE_QUALITY_VOCAB_PATH)
            if mtime == cache['mtime'] and cache['data']:
                return cache['data']
            with open(self._PROPOSE_QUALITY_VOCAB_PATH,
                       'r', encoding='utf-8') as f:
                data = json.load(f)
            cfg = dict(self._PROPOSE_QUALITY_DEFAULT_VOCAB)
            for k, v in (data or {}).items():
                cfg[k] = v
            cache['data'] = cfg
            cache['mtime'] = mtime
            return cfg
        except Exception:
            return dict(self._PROPOSE_QUALITY_DEFAULT_VOCAB)

    def _should_gate_propose(self, thought) -> Tuple[bool, str]:
        """sal < threshold + actionable in gated prefixes → gate (返 True).

        Returns: (gated, reason) — gated=True 表 propose 被拒, 调 caller
        把 actionable 降级 'none'.
        """
        try:
            vocab = self._load_propose_quality_vocab()
            if not vocab.get('enabled', True):
                return False, ''
            a = (thought.actionable or '').strip().lower()
            prefixes = vocab.get('gated_actionable_prefixes') or []
            if not any(a.startswith(p.lower()) for p in prefixes):
                return False, ''  # 不在 gated 列表
            thr = float(vocab.get('sal_threshold', 0.60))
            if thought.salience >= thr:
                return False, ''
            return True, (
                f'sal={thought.salience:.2f}<{thr:.2f} '
                f'(propose_quality_gate)'
            )
        except Exception:
            return False, ''

    def _save_propose_quality_vocab(self, vocab: dict) -> bool:
        """持久化 + invalidate cache. 失败 silent."""
        try:
            os.makedirs(
                os.path.dirname(self._PROPOSE_QUALITY_VOCAB_PATH),
                exist_ok=True,
            )
            with open(self._PROPOSE_QUALITY_VOCAB_PATH,
                       'w', encoding='utf-8') as f:
                json.dump(vocab, f, ensure_ascii=False, indent=2)
            # invalidate cache
            self._PROPOSE_QUALITY_VOCAB_CACHE['mtime'] = 0.0
            self._PROPOSE_QUALITY_VOCAB_CACHE['data'] = None
            return True
        except Exception:
            return False

    def _maybe_calibrate_propose_quality(self) -> None:
        """周期 calibrate — 读 auto_arbiter_log 24h decisions, 调 sal_threshold.

        cooldown: vocab.calibrate_cooldown_h (默认 24h, 不重复跑).
        逻辑:
          - filter kind in (inside_joke, protocol), 算 activate_rate =
            activate / (activate + reject + defer_to_sir)
          - rate >= activate_rate_high → 阈降 lower_step (放松)
          - rate <= activate_rate_low → 阈升 raise_step (收紧)
          - 其他不变
          - 持久化 vocab + log + publish SWM 1 event
        """
        try:
            vocab = self._load_propose_quality_vocab()
            if not vocab.get('auto_calibrate_enabled', True):
                return
            now = time.time()
            last_ts = float(vocab.get('last_calibrated_at_ts', 0) or 0)
            cooldown_s = float(vocab.get('calibrate_cooldown_h', 24)) * 3600
            if last_ts > 0 and (now - last_ts) < cooldown_s:
                return

            lookback_s = float(vocab.get('calibrate_lookback_h', 24)) * 3600
            cutoff = now - lookback_s
            min_samples = int(vocab.get('calibrate_min_samples', 10))

            # 读 auto_arbiter_log.jsonl (relative to module dir)
            log_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'memory_pool', 'auto_arbiter_log.jsonl',
            )
            if not os.path.exists(log_path):
                return
            n_activate = 0
            n_reject = 0
            n_defer = 0
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if float(d.get('ts', 0) or 0) < cutoff:
                        continue
                    if d.get('kind') not in ('inside_joke', 'protocol'):
                        continue
                    dec = d.get('decision', '')
                    if dec == 'activate':
                        n_activate += 1
                    elif dec == 'reject':
                        n_reject += 1
                    elif dec == 'defer_to_sir':
                        n_defer += 1

            total = n_activate + n_reject + n_defer
            if total < min_samples:
                # 样本不够, 更新 last_ts 防热跑但不调阈值
                vocab['last_calibrated_at_ts'] = now
                vocab['last_calibrated_at_iso'] = time.strftime(
                    '%Y-%m-%dT%H:%M:%S', time.localtime(now)
                )
                self._save_propose_quality_vocab(vocab)
                self._bg_log(
                    f"📊 [ProposeQuality] skip calibrate "
                    f"(only {total} samples < {min_samples})"
                )
                return

            rate = n_activate / total
            old_thr = float(vocab.get('sal_threshold', 0.60))
            floor = float(vocab.get('sal_threshold_floor', 0.40))
            ceil = float(vocab.get('sal_threshold_ceiling', 0.85))
            high = float(vocab.get('activate_rate_high', 0.70))
            low = float(vocab.get('activate_rate_low', 0.30))
            raise_step = float(vocab.get('raise_step', 0.05))
            lower_step = float(vocab.get('lower_step', 0.02))

            if rate >= high:
                new_thr = max(floor, old_thr - lower_step)
                reason = (
                    f'activate_rate={rate:.0%}>={high:.0%}, '
                    f'lower threshold {old_thr:.2f}→{new_thr:.2f} (放松)'
                )
            elif rate <= low:
                new_thr = min(ceil, old_thr + raise_step)
                reason = (
                    f'activate_rate={rate:.0%}<={low:.0%}, '
                    f'raise threshold {old_thr:.2f}→{new_thr:.2f} (收紧)'
                )
            else:
                new_thr = old_thr
                reason = (
                    f'activate_rate={rate:.0%} in [{low:.0%}, {high:.0%}], '
                    f'no change (threshold={old_thr:.2f})'
                )

            # 持久化
            vocab['sal_threshold'] = new_thr
            vocab['last_calibrated_at_ts'] = now
            vocab['last_calibrated_at_iso'] = time.strftime(
                '%Y-%m-%dT%H:%M:%S', time.localtime(now)
            )
            history = list(vocab.get('history') or [])
            history.append({
                'ts_iso': vocab['last_calibrated_at_iso'],
                'old_threshold': round(old_thr, 3),
                'new_threshold': round(new_thr, 3),
                'reason': reason,
                'stats': {
                    'activate': n_activate, 'reject': n_reject,
                    'defer': n_defer, 'total': total,
                    'activate_rate': round(rate, 3),
                },
            })
            # cap history 最近 20
            vocab['history'] = history[-20:]
            self._save_propose_quality_vocab(vocab)
            self._bg_log(
                f"📊 [ProposeQuality] calibrate: {reason} "
                f"(stats: act={n_activate}/rej={n_reject}/"
                f"defer={n_defer})"
            )
            # publish SWM 1 event (主脑 / dashboard 看)
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
                if bus is not None:
                    bus.publish(
                        etype='propose_quality_calibrated',
                        description=reason[:200],
                        source='InnerThoughtDaemon.ProposeQuality',
                        salience=0.5,
                        metadata={
                            'old_threshold': old_thr,
                            'new_threshold': new_thr,
                            'activate_rate': rate,
                            'stats': {
                                'activate': n_activate,
                                'reject': n_reject,
                                'defer': n_defer,
                                'total': total,
                            },
                        },
                        ttl=86400.0,
                    )
            except Exception:
                pass
        except Exception as e:
            try:
                self._bg_log(
                    f"⚠️ [ProposeQuality] calibrate exception: {e}"
                )
            except Exception:
                pass

    def _append_cold_start_record(self) -> None:
        """daemon init 时 append 一条 cold_start record (跨 session 持久).

        🆕 [Self-Memory P0 / Sir 2026-05-30] 数据卫生 + 真 dark_gap:
          - 只在**真 production session** (session_id 非空) 时 append. test/script
            import 构造 daemon 无 session → 不写 (修历史污染: 一秒 5 条空 session
            record + prev=0 把"离线多久"信号冲烂).
          - 同 session 已写过 → dedup skip (一进程多次构造 daemon 不重复 append).
          - dark_gap_s: 用上次 last_alive 心跳算**真离线时长** (= now - 上次临死前
            最后心跳). 比 prev_cold_start_age_s 准 (后者含上次 session 运行时长).
            prev 心跳缺 (首次跑) → None.
        """
        try:
            sess_id = ''
            try:
                from jarvis_utils import TraceContext
                sess_id = TraceContext.get_session_id() or ''
            except Exception:
                pass
            # 数据卫生 gate 1: 无真 session → 不写 (test/script import 不污染账本)
            if not sess_id:
                return
            # 读末条 (算 prev_cold_start_age_s + dedup 判断)
            prev_age = None
            last_rec = None
            try:
                if os.path.exists(self._COLD_STARTS_PATH):
                    with open(self._COLD_STARTS_PATH, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    if lines:
                        last_rec = json.loads(lines[-1].strip())
                        prev_ts = float(last_rec.get('ts', 0))
                        if prev_ts > 0:
                            prev_age = int(time.time() - prev_ts)
            except Exception:
                pass
            # 数据卫生 gate 2: 同 session 已写 → dedup (幂等 per session)
            if last_rec and (last_rec.get('session_id') or '') == sess_id:
                return
            # 真 dark_gap: now - 上次心跳 (上次 session 临死前最后 alive)
            dark_gap_s = None
            prev_alive_iso = ''
            try:
                prev_alive = self._read_last_alive()
                if prev_alive:
                    prev_alive_ts = float(prev_alive.get('ts', 0) or 0)
                    if prev_alive_ts > 0:
                        dark_gap_s = max(0, int(time.time() - prev_alive_ts))
                        prev_alive_iso = str(prev_alive.get('ts_iso', '') or '')
            except Exception:
                pass
            record = {
                'ts': time.time(),
                'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                          time.localtime()),
                'session_id': sess_id,
                'prev_cold_start_age_s': prev_age,
                'dark_gap_s': dark_gap_s,
                'prev_last_alive_iso': prev_alive_iso,
                'reason': 'first_run' if prev_age is None else 'restart',
            }
            os.makedirs(os.path.dirname(self._COLD_STARTS_PATH),
                          exist_ok=True)
            with open(self._COLD_STARTS_PATH, 'a',
                       encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
            # 写本 session 首个心跳 (覆盖上次 session 的 last_alive)
            try:
                self._persist_heartbeat()
            except Exception:
                pass
        except Exception:
            pass

    def _read_last_alive(self) -> Optional[dict]:
        """🆕 [Self-Memory P0] 读 last_alive 心跳 (上次 session 临死前最后活着 ts).

        失败 / 不存在 / 损坏 → None (fail-safe, dark_gap 退 None).
        """
        try:
            if not os.path.exists(self._LAST_ALIVE_PATH):
                return None
            with open(self._LAST_ALIVE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _persist_heartbeat(self) -> bool:
        """🆕 [Self-Memory P0] 覆写 last_alive.json = now (atomic).

        daemon 是心跳 keeper — cold_start 时调一次 + loop 周期调. 只在真 session
        写 (test/script 无 session 不污染 → 下次 dark_gap 准). 失败 silent.
        """
        try:
            sess_id = ''
            try:
                from jarvis_utils import TraceContext
                sess_id = TraceContext.get_session_id() or ''
            except Exception:
                pass
            if not sess_id:
                return False
            now = time.time()
            rec = {
                'ts': now,
                'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                          time.localtime(now)),
                'session_id': sess_id,
            }
            os.makedirs(os.path.dirname(self._LAST_ALIVE_PATH), exist_ok=True)
            tmp = self._LAST_ALIVE_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False)
            os.replace(tmp, self._LAST_ALIVE_PATH)
            self._last_heartbeat_ts = now
            return True
        except Exception:
            return False

    def _maybe_persist_heartbeat(self) -> None:
        """🆕 [Self-Memory P0] daemon loop 周期持久 last_alive (vocab interval throttle)."""
        try:
            vocab = self._load_lifetime_vocab()
            interval = float(vocab.get('heartbeat_persist_interval_s', 300))
            now = time.time()
            if now - float(getattr(self, '_last_heartbeat_ts', 0.0) or 0.0) < interval:
                return
            self._persist_heartbeat()
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

    def _format_duration_human(self, secs: float) -> str:
        """🆕 [Self-Memory P0] gap 人读: '2d 3h' / '5h' / '45min' / '30s'
        (比 _format_age_human 细 — surface dark_gap 时让主脑看清离线多久)."""
        secs = max(0, int(secs))
        d = secs // 86400
        h = (secs % 86400) // 3600
        m = (secs % 3600) // 60
        if d > 0:
            return f"{d}d {h}h" if h else f"{d}d"
        if h > 0:
            return f"{h}h {m}min" if m else f"{h}h"
        if m > 0:
            return f"{m}min"
        return f"{secs}s"

    # ----------------------------------------------------------
    # 🆕 [Self-Memory P1 / Sir 2026-05-30] 思考脑自我回忆 (recall as an action)
    # ----------------------------------------------------------
    # Sir 真意: "高频思考脑能不能自我迭代自我理解? 随口的记忆/昨天那件事/好久没见".
    # 根因 (已核): 思考脑只 _maybe_archive_to_hippocampus 写、tick 中**无召回路径**,
    # 只看预塞的 24h 窗口 → 任何"随口的记忆"都得 hand-code 预 push.
    # 治本: 复用 nerve.memory_gateway (MemoryHub.query, M2 已建) — 不造新存储.
    # F1 混合: 后台 tick 允许脑子自发深召回 (<RECALL>tag); F3: 带 provenance + 允许
    # "模糊记得" 但禁裸断言. 详 docs/JARVIS_GROUNDED_SELF_MEMORY_DESIGN.md.
    # ----------------------------------------------------------
    def recall(self, query_text: str, top_k: int = 4) -> List[dict]:
        """思考脑自查记忆 — 跨 source (STM/LTM/Profile/Ledger) + self-threads 河床.

        (a) MemoryHub.query (M2 已建, 需 nerve) — 语义跨源召回.
        (b) 🆕 [P2] self-threads 河床 — 实体/关键词匹配 (不需 nerve).
        返带 provenance (source 标签) 的候选 dict list. 接地红线 (F3): 失败/无源
        → 空 list (诚实, 不编造记忆 — 准则 5).
        """
        out: List[dict] = []
        if not query_text:
            return out
        # (a) 跨 source 语义召回 (MemoryHub, 需 nerve)
        try:
            hub = (getattr(self.nerve, 'memory_gateway', None)
                   if self.nerve else None)
            if hub is not None and hasattr(hub, 'query'):
                frags = hub.query(
                    query_text, top_k=top_k, nerve=self.nerve) or []
                for fr in frags:
                    src = getattr(fr, 'source', '') or '?'
                    content = str(getattr(fr, 'content', '') or '')[:200]
                    if content:
                        out.append({'source': str(src), 'content': content})
        except Exception:
            pass
        # (b) 🆕 [P2] self-threads 河床召回 (不需 nerve)
        try:
            out.extend(self.recall_threads(query_text, top_k=3))
        except Exception:
            pass
        # (c) 🆕 [P4] self-notes schema-free 自写记忆召回
        try:
            out.extend(self.recall_notes(query_text, top_k=2))
        except Exception:
            pass
        return out

    def build_recall_block(self, results: List[dict], query: str = '') -> str:
        """render 召回候选给 prompt (F3 接地纪律).

        每条带 [SOURCE] provenance 标签. 明确这是召回的记忆 (可能不全/不准):
        引用前确认, 不确定就说 '我模糊记得…', 禁止当确证事实裸断言 (准则 5).
        """
        if not results:
            return ''
        q = (query or '').strip()
        head = (f"=== RECALLED MEMORY (你查 \"{q[:60]}\" 的候选"
                if q else "=== RECALLED MEMORY (候选")
        lines = [
            f"{head} — 带来源标签; 这是你的记忆召回, 可能不全/不准. "
            "引用前先确认; 不确定就说 '我模糊记得…', 别当确证事实裸断言 (准则 5)) ==="
        ]
        for r in results:
            src = str(r.get('source', '?')).upper()
            content = str(r.get('content', ''))[:160]
            lines.append(f"  [{src}] {content}")
        return '\n'.join(lines)

    def _handle_recall_tag(self, raw: str) -> None:
        """解析 <RECALL>query</RECALL> → 跑召回 → 存 pending block (下 tick 注入).

        F1: 后台 tick 自发深召回, 不阻塞当前 tick (结果下 tick 顶部出现, 类比
        _next_attention_focus 的本轮→下轮 pattern). 空/占位 query → 不召回.
        """
        try:
            m = re.search(r'<RECALL>(.*?)</RECALL>', raw or '',
                          re.DOTALL | re.IGNORECASE)
            if not m:
                return
            query = (m.group(1) or '').strip()
            if (not query or len(query) < 3
                    or query.lower() in ('none', 'empty', '(none)', 'n/a')):
                return
            results = self.recall(query, top_k=4)
            # 🆕 [P3 强闭环] 主动召回命中的 OPEN 线程 → 结构性 bump salience
            # (mutate 会 gate 下 tick 注意力的持久态, 非装饰性 append).
            try:
                _bumped = self._bump_recalled_open_threads(query)
            except Exception:
                _bumped = 0
            block = self.build_recall_block(results, query=query)
            if block:
                self._pending_recall_block = block
            self._bg_log(
                f"🔎 [Recall] query='{query[:50]}' → "
                f"{len(results)} hit(s), {_bumped} open-thread(s) bumped"
                + (", queued for next tick" if block else "")
            )
        except Exception:
            pass

    # ----------------------------------------------------------
    # 🆕 [Self-Memory P2 / Sir 2026-05-30] 河床/巩固 (consolidation) + 遗忘
    # ----------------------------------------------------------
    # Sir 真意: "连续存在差什么? 河在流但没结河床." 流水账 (心流 jsonl) 越长但
    # "自我"不变深. 治本: 把同 thread_id 的 thought 卷成持久线程 (running summary +
    # last_touched + salience + status + 回链 evidence), 让"昨天那件事/你记得我那个"
    # 是线程查找, 不靠 23:00 硬编码 recap. 遗忘: salience 衰减 + hot/warm/cold 分层
    # (不删除, 删了丢 provenance). 决策锚 F4 线程为主 / F5 周期巩固.
    # 详 docs/JARVIS_GROUNDED_SELF_MEMORY_DESIGN.md §5 P2.
    # ----------------------------------------------------------
    def _load_self_threads(self) -> dict:
        """读 self_threads.json (河床). 失败/不存在 → 空 {threads: []}."""
        try:
            if not os.path.exists(self._SELF_THREADS_PATH):
                return {'_meta': {'schema': 'self_threads'}, 'threads': []}
            with open(self._SELF_THREADS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {'_meta': {'schema': 'self_threads'}, 'threads': []}
            data.setdefault('threads', [])
            return data
        except Exception:
            return {'_meta': {'schema': 'self_threads'}, 'threads': []}

    def _save_self_threads(self, data: dict) -> bool:
        """atomic 写 self_threads.json. 失败 silent."""
        try:
            data.setdefault('_meta', {
                'schema': 'self_threads',
                'doc': ('Jarvis 河床 — 巩固的持久思维线程. CLI: '
                        'scripts/self_threads_dump.py'),
            })
            data['_meta']['updated_iso'] = time.strftime(
                '%Y-%m-%dT%H:%M:%S', time.localtime()
            )
            os.makedirs(os.path.dirname(self._SELF_THREADS_PATH), exist_ok=True)
            tmp = self._SELF_THREADS_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._SELF_THREADS_PATH)
            return True
        except Exception:
            return False

    def _compute_thread_tier(self, th: dict, now: float, vocab: dict) -> str:
        """遗忘分层: hot (<1d) / warm (<7d) / cold. let_go → cold."""
        if (th.get('status') or '') == 'let_go':
            return 'cold'
        age = now - float(th.get('last_touched_ts', now) or now)
        hot = float(vocab.get('thread_tier_hot_max_age_s', 86400))
        warm = float(vocab.get('thread_tier_warm_max_age_s', 604800))
        if age < hot:
            return 'hot'
        if age < warm:
            return 'warm'
        return 'cold'

    def _decayed_salience(self, salience: float, last_touched_ts: float,
                            now: float, half_life_days: float) -> float:
        """salience 半衰期衰减 (遗忘) — 越久未碰越低. 不改 raw salience."""
        try:
            age_days = max(0.0, (now - float(last_touched_ts)) / 86400.0)
            if half_life_days <= 0:
                return float(salience)
            return round(
                float(salience) * (0.5 ** (age_days / half_life_days)), 4)
        except Exception:
            return float(salience)

    def _llm_summarize_thread(self, thoughts: list) -> str:
        """LLM 写线程 1-liner running summary (复用 _call_llm). 无 key_router → ''."""
        if not self.key_router or not thoughts:
            return ''
        try:
            joined = ' | '.join(
                (getattr(t, 'thought', '') or '')[:120] for t in thoughts[-6:]
            )
            sysp = (
                "You are J.A.R.V.I.S. Summarize this recurring inner-thought "
                "thread into ONE concise third-person sentence (<140 chars, "
                "English, butler tone). Capture the through-line, not each "
                "thought. No preamble."
            )
            usrp = (
                f"Thread thoughts (oldest→newest):\n{joined}\n\n"
                "One-sentence summary:"
            )
            txt = (self._call_llm(
                sysp, usrp, caller_origin='thread_consolidate',
            ) or '').strip()
            for p in ('Summary:', '"', '- ', '*'):
                if txt.startswith(p):
                    txt = txt[len(p):].strip()
            return txt[:200]
        except Exception:
            return ''

    def _consolidate_threads_once(self) -> int:
        """把 self._thoughts 按 thread_id 卷成持久线程 + 衰减/分层 (遗忘). 返线程数."""
        vocab = self._load_lifetime_vocab()
        min_thoughts = int(vocab.get('consolidate_min_thoughts', 2))
        max_llm = int(vocab.get('consolidate_max_threads_per_run', 8))
        use_llm = bool(vocab.get('consolidate_llm_summary', True))
        half_life = float(vocab.get('thread_decay_half_life_days', 7.0))
        now = time.time()
        with self._lock:
            thoughts = list(self._thoughts)
        # group by thread_id
        groups: Dict[str, list] = {}
        for t in thoughts:
            tid = getattr(t, 'thread_id', '') or getattr(t, 'id', '')
            if tid:
                groups.setdefault(tid, []).append(t)
        data = self._load_self_threads()
        threads = {th.get('thread_id'): th for th in data.get('threads', [])
                   if th.get('thread_id')}
        llm_used = 0
        for tid, ts_list in groups.items():
            if len(ts_list) < min_thoughts:
                continue
            ts_list.sort(key=lambda x: x.ts)
            last_touched = max(t.ts for t in ts_list)
            first_ts = min(t.ts for t in ts_list)
            max_sal = max(
                float(getattr(t, 'salience', 0) or 0) for t in ts_list)
            existing = threads.get(tid)
            changed = (existing is None
                       or float(existing.get('last_touched_ts', 0) or 0)
                       < last_touched - 1)
            top = max(ts_list,
                      key=lambda x: float(getattr(x, 'salience', 0) or 0))
            if existing and not changed:
                summary = existing.get('summary', '') or (top.thought or '')[:160]
            elif use_llm and self.key_router and llm_used < max_llm:
                summary = (self._llm_summarize_thread(ts_list)
                           or (top.thought or '')[:160])
                llm_used += 1
            else:
                summary = (top.thought or '')[:160]
            threads[tid] = {
                'thread_id': tid,
                'summary': summary[:300],
                'first_ts': first_ts,
                'last_touched_ts': last_touched,
                'last_touched_iso': time.strftime(
                    '%Y-%m-%dT%H:%M:%S', time.localtime(last_touched)),
                'occurrences': len(ts_list),
                'salience': round(max_sal, 3),
                'salience_decayed': self._decayed_salience(
                    max_sal, last_touched, now, half_life),
                'status': (existing.get('status', 'open')
                           if existing else 'open'),
                'evidence_thought_ids': [t.id for t in ts_list[-5:]],
            }
        # 遗忘: 重算 tier + decayed salience for ALL (含老线程)
        thread_list = list(threads.values())
        for th in thread_list:
            th['tier'] = self._compute_thread_tier(th, now, vocab)
            th['salience_decayed'] = self._decayed_salience(
                float(th.get('salience', 0) or 0),
                float(th.get('last_touched_ts', now) or now),
                now, half_life,
            )
        # cap: 按 last_touched 保留最近 N (超额最老的不再 keep)
        max_kept = int(vocab.get('thread_max_kept', 200))
        thread_list.sort(key=lambda th: -float(th.get('last_touched_ts', 0) or 0))
        thread_list = thread_list[:max_kept]
        data['threads'] = thread_list
        self._save_self_threads(data)
        return len(thread_list)

    def _maybe_consolidate_threads(self) -> None:
        """周期巩固 (cooldown throttle). tick 后调."""
        vocab = self._load_lifetime_vocab()
        if not bool(vocab.get('consolidate_enabled', True)):
            return
        cd = float(vocab.get('consolidate_cooldown_s', 3600))
        now = time.time()
        if now - float(getattr(self, '_last_consolidate_ts', 0) or 0) < cd:
            return
        self._last_consolidate_ts = now
        try:
            n = self._consolidate_threads_once()
            self._bg_log(f"🪶 [Consolidate] 河床 {n} threads (流水账→持久线程)")
        except Exception as e:
            self._bg_log(f"⚠️ [Consolidate] exception: {e}")

    def recall_threads(self, query_text: str, top_k: int = 3) -> List[dict]:
        """🆕 [P2] self-threads 河床召回 — 关键词/实体重叠匹配. 返带 tier 的候选."""
        out: List[dict] = []
        try:
            q = set(re.findall(r'\w+', (query_text or '').lower()))
            q = {w for w in q if len(w) >= 2}
            if not q:
                return out
            data = self._load_self_threads()
            scored = []
            for th in data.get('threads', []):
                text = str(th.get('summary', '') or '').lower()
                words = set(re.findall(r'\w+', text))
                overlap = len(q & words)
                if overlap > 0:
                    scored.append((
                        overlap,
                        float(th.get('salience_decayed',
                                     th.get('salience', 0)) or 0),
                        th))
            scored.sort(key=lambda x: (-x[0], -x[1]))
            for _ov, _sal, th in scored[:top_k]:
                out.append({
                    'source': 'THREAD',
                    'content': (f"[{th.get('tier', '?')}|seen×"
                                f"{th.get('occurrences', '?')}] "
                                f"{str(th.get('summary', ''))[:160]}"),
                })
        except Exception:
            pass
        return out

    # ----------------------------------------------------------
    # 🆕 [Self-Memory P3 / Sir 2026-05-30] 强闭环 — 召回 mutate 门控态
    # ----------------------------------------------------------
    # emergence doc §3: 弱闭环 = 注入文字指望 LLM 注意; 强闭环 = 后果 mutate 那个
    # 会 gate 下一步的结构化态. 这里: 主动召回 (<RECALL>) 命中的 OPEN 线程 →
    # salience 结构性 bump + 刷 last_touched + re-tier hot. 被 bump 的线程在未来
    # recall_threads / open-threads 视图里**排序更靠前** → 思考脑下 tick 注意力被
    # 结构性导向 resurfaced 线程. 这是真因果闭合, 不是装饰性 append.
    # ----------------------------------------------------------
    def _bump_recalled_open_threads(self, query_text: str) -> int:
        """主动召回命中的 OPEN 线程 → 结构性 bump salience (gate 未来注意力). 返 bump 数."""
        try:
            vocab = self._load_lifetime_vocab()
            bump = float(vocab.get('thread_recall_bump_salience', 0.08))
            cap = float(vocab.get('thread_recall_bump_cap', 0.95))
            half_life = float(vocab.get('thread_decay_half_life_days', 7.0))
            q = set(re.findall(r'\w+', (query_text or '').lower()))
            q = {w for w in q if len(w) >= 2}
            if not q or bump <= 0:
                return 0
            data = self._load_self_threads()
            now = time.time()
            n = 0
            for th in data.get('threads', []):
                if (th.get('status') or 'open') != 'open':
                    continue   # closed / let_go 不 resurface (尊重遗忘)
                words = set(re.findall(
                    r'\w+', str(th.get('summary', '')).lower()))
                if not (q & words):
                    continue
                old = float(th.get('salience', 0) or 0)
                th['salience'] = round(min(cap, old + bump), 3)
                th['last_touched_ts'] = now
                th['last_touched_iso'] = time.strftime(
                    '%Y-%m-%dT%H:%M:%S', time.localtime(now))
                th['salience_decayed'] = self._decayed_salience(
                    th['salience'], now, now, half_life)
                th['tier'] = 'hot'
                n += 1
            if n:
                self._save_self_threads(data)
            return n
        except Exception:
            return 0

    def _build_open_threads_block(self, n: int = 3) -> str:
        """render 顶 N 个 OPEN 线程 (按 decayed salience 排) 给 tick prompt.

        强闭环的"门控"显形: 被召回 bump 过的 open 线程 decayed salience 升高 →
        在此视图里浮到顶 → 思考脑本 tick 优先注意 → 自然延续 (而非每轮重新发现).
        """
        try:
            data = self._load_self_threads()
            opens = [t for t in data.get('threads', [])
                     if (t.get('status') or 'open') == 'open']
            if not opens:
                return ''
            opens.sort(key=lambda t: -float(
                t.get('salience_decayed', t.get('salience', 0)) or 0))
            opens = opens[:max(1, int(n))]
            lines = [
                "[OPEN THREADS — your live concerns, salience-ranked "
                "(resurfaced ones float up; pick up a thread or let it go)]"
            ]
            for t in opens:
                sal = float(
                    t.get('salience_decayed', t.get('salience', 0)) or 0)
                lines.append(
                    f"  ({t.get('tier', '?')}|sal={sal:.2f}|seen×"
                    f"{t.get('occurrences', '?')}) "
                    f"{str(t.get('summary', ''))[:120]}"
                )
            return '\n'.join(lines)
        except Exception:
            return ''

    # ----------------------------------------------------------
    # 🆕 [Self-Memory P4 / Sir 2026-05-30] schema-free 自写记忆 (note-to-self)
    # ----------------------------------------------------------
    # Sir 真意: "随口的记忆" 不属于 concern/directive/joke/milestone 任何 schema →
    # 无处可记 → 又得加 schema (hand-code). 治本: <NOTE> 让脑子写任意自由记忆,
    # 持久 self_notes.jsonl, 纳入 recall. 准则 6 信任 LLM 自决记什么.
    # ----------------------------------------------------------
    def _handle_note_tag(self, raw: str) -> None:
        """解析 <NOTE>text</NOTE> → append self_notes.jsonl (schema-free 自写记忆)."""
        try:
            m = re.search(r'<NOTE>(.*?)</NOTE>', raw or '',
                          re.DOTALL | re.IGNORECASE)
            if not m:
                return
            text = (m.group(1) or '').strip()
            if (not text or len(text) < 5
                    or text.lower() in ('none', 'empty', '(none)', 'n/a')):
                return
            rec = {
                'ts': time.time(),
                'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                'text': text[:300],
            }
            os.makedirs(os.path.dirname(self._SELF_NOTES_PATH), exist_ok=True)
            with open(self._SELF_NOTES_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            self._bg_log(f"📝 [SelfNote] kept: \"{text[:60]}\"")
        except Exception:
            pass

    def recall_notes(self, query_text: str, top_k: int = 2) -> List[dict]:
        """self-notes 召回 — 关键词重叠 (读末 200 条). 返 source=NOTE 候选."""
        out: List[dict] = []
        try:
            if not os.path.exists(self._SELF_NOTES_PATH):
                return out
            q = set(re.findall(r'\w+', (query_text or '').lower()))
            q = {w for w in q if len(w) >= 2}
            if not q:
                return out
            with open(self._SELF_NOTES_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            scored = []
            for ln in lines[-200:]:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except Exception:
                    continue
                text = str(rec.get('text', '') or '')
                words = set(re.findall(r'\w+', text.lower()))
                ov = len(q & words)
                if ov > 0:
                    scored.append((ov, text))
            scored.sort(key=lambda x: -x[0])
            for _ov, text in scored[:top_k]:
                out.append({'source': 'NOTE', 'content': text[:160]})
        except Exception:
            pass
        return out

    # ----------------------------------------------------------
    # 🆕 [言出必行 I2 / Sir 2026-05-30] 语义 claim 审计 (LLM 替正则枚举)
    # ----------------------------------------------------------
    # Sir 真痛根因: ClaimTracer extract_claims 是正则枚举 — 每个新幻觉形式都要加一条
    # regex (和"要他记得什么就 hand-code"同病). 治本 (准则 6 信任 LLM): 让思考脑后台
    # LLM 语义判 "这句有没有凭据", 不靠无限加 regex. 准则 1: 仅后台 daemon + cooldown +
    # vocab 默 off (Sir 可开), 绝不进主脑回复热路径.
    # ----------------------------------------------------------
    def semantic_claim_audit(self, reply: str, tool_results_str: str = '',
                              stm_blob: str = '') -> List[dict]:
        """LLM 语义查 reply 里**未被 evidence 支持**的 specific factual claim.

        返 list[{claim, reason}] (仅 grounded=false 的). 无 key_router / 失败 → [].
        准则 5: 只 flag 真没凭据的, 社交寒暄不算 claim.
        """
        if not self.key_router or not reply or len(reply) < 10:
            return []
        try:
            sysp = (
                "You are J.A.R.V.I.S.'s own integrity check. Given a reply you "
                "just gave Sir, find any SPECIFIC FACTUAL CLAIM (a time, a "
                "number, a past action you say you DID, a quote of Sir, a state "
                "assertion) that is NOT supported by the evidence provided. "
                "Output STRICT JSON only: a list of "
                "{\"claim\":\"...\",\"grounded\":true|false,\"reason\":\"...\"}. "
                "Use [] if every claim is grounded or there are none. Social "
                "pleasantries / opinions / hedged statements are NOT claims."
            )
            usrp = (
                f"Reply: {reply[:600]}\n\nEvidence available:\n"
                f"- tool results: {(tool_results_str or '(none)')[:400]}\n"
                f"- recent conversation: {(stm_blob or '(none)')[:400]}\n\n"
                "JSON list (only grounded=false ones matter):"
            )
            raw = (self._call_llm(
                sysp, usrp, caller_origin='semantic_claim_audit') or '').strip()
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if not m:
                return []
            arr = json.loads(m.group(0))
            out = []
            for it in (arr if isinstance(arr, list) else []):
                if isinstance(it, dict) and it.get('grounded') is False:
                    out.append({
                        'claim': str(it.get('claim', ''))[:120],
                        'reason': str(it.get('reason', ''))[:120],
                    })
            return out
        except Exception:
            return []

    def _maybe_semantic_claim_audit(self) -> None:
        """后台 (vocab-gated, cooldown) 对上一条主脑 reply 跑语义 claim 审计.

        命中 ungrounded → bg_log + publish SWM 'semantic_claim_flagged' (主脑/dashboard
        看到, 喂言出必行闭环). 准则 1: 默 off + cooldown + 只在 reply 变化时跑.
        """
        try:
            vocab = self._load_lifetime_vocab()
            if not bool(vocab.get('semantic_claim_check_enabled', False)):
                return
            cd = float(vocab.get('semantic_claim_check_cooldown_s', 300))
            now = time.time()
            if now - float(getattr(self, '_last_semantic_audit_ts', 0) or 0) < cd:
                return
            if not self.nerve:
                return
            stm = list(getattr(self.nerve, 'short_term_memory', []) or [])
            if not stm or not isinstance(stm[-1], dict):
                return
            reply = str(stm[-1].get('jarvis', '') or '')
            if not reply or reply == getattr(self, '_last_audited_reply', ''):
                return
            self._last_semantic_audit_ts = now
            self._last_audited_reply = reply
            stm_blob = ' | '.join(
                (str(e.get('user', '')) + ' ' + str(e.get('jarvis', '')))
                for e in stm[-4:] if isinstance(e, dict)
            )
            flagged = self.semantic_claim_audit(reply, '', stm_blob[:600])
            if flagged:
                self._bg_log(
                    f"🔎 [SemanticClaim/I2] {len(flagged)} ungrounded claim(s); "
                    f"first: \"{flagged[0].get('claim', '')[:60]}\""
                )
                try:
                    from jarvis_utils import get_event_bus
                    bus = get_event_bus()
                    if bus is not None:
                        bus.publish(
                            etype='semantic_claim_flagged',
                            description=(
                                f"{len(flagged)} ungrounded claim(s): "
                                f"{flagged[0].get('claim', '')[:80]}"),
                            source='InnerThoughtDaemon.SemanticClaimAudit',
                            salience=0.6,
                            metadata={'flagged': flagged},
                            ttl=3600.0,
                        )
                except Exception:
                    pass
        except Exception:
            pass

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

        # (2) Cross-session continuity + dark gap (离线感知)
        # 🆕 [Self-Memory P0 / Sir 2026-05-30; 诚信修 Sir 2026-05-30 23:38] surface
        # **真** dark_gap (来自心跳). 准则 5 诚信: dark_gap 未知 (本次无前序心跳) 时
        # **绝不**用 prev_cold_start_age_s 兜底冒充离线时长 (那是"距上次启动", 含上个
        # 会话运行时长, 误导) — 改成明确告诉主脑"真离线时长未知, 别编精确数字, hedge".
        # 真机 BUG 根因: 首次部署心跳后 dark_gap=null, 老兜底让主脑编出"12min/23:14".
        # 仅 process 刚起 < relevant_uptime 内 surface (跑久了"刚回来"不再是 news).
        try:
            recs = self._load_cold_starts(
                int(vocab.get('cross_session_max_records', 12))
            )
            self_rec = recs[0] if recs else {}
            dark_gap = self_rec.get('dark_gap_s')   # 真离线时长 (心跳算), 可能 None
            prev_age = self_rec.get('prev_cold_start_age_s')  # 距上次启动 (≠ 真离线)
            prev_alive_iso = str(self_rec.get('prev_last_alive_iso', '') or '')
            min_surface = int(vocab.get('dark_gap_min_surface_s', 3600))
            relevant_uptime = float(vocab.get('dark_gap_relevant_uptime_s', 3600))
            try:
                uptime_s = time.time() - self._process_start_ts
            except Exception:
                uptime_s = 0.0
            if uptime_s < relevant_uptime:  # 仅刚回来时谈离线
                if dark_gap is not None and int(dark_gap) >= min_surface:
                    # 真 dark_gap (心跳算出) → 可确信陈述
                    gap_human = self._format_duration_human(int(dark_gap))
                    tail = (f", last alive {prev_alive_iso}"
                            if prev_alive_iso else "")
                    lines.append(
                        f"- You were NOT running for ~{gap_human}{tail} "
                        f"(process dark — true offline gap since Sir last had "
                        f"you on; you just came back)."
                    )
                elif dark_gap is None:
                    # 无前序心跳 → 真离线时长**未知** → HEDGE (诚信红线, 别编)
                    _pa = (f"~{self._format_duration_human(int(prev_age))} ago"
                           if prev_age is not None else "unknown")
                    lines.append(
                        f"- You just restarted, but your TRUE offline duration "
                        f"is UNKNOWN this session (no prior heartbeat recorded). "
                        f"Your previous LAUNCH was {_pa} — that is time-since-"
                        f"launch (includes its run time), NOT the offline gap. "
                        f"If Sir asks how long you were away/offline, do NOT "
                        f"invent a precise figure — say you cannot be certain. "
                        f"(For 'how long since we last spoke', use the "
                        f"conversation history, not this process metric.)"
                    )
            # 跨 session 连续性 (count + span) — 同一 Jarvis 身份
            if recs and len(recs) >= 2:
                hist = recs[1:]
                if hist:
                    oldest_ts = float(hist[-1].get('ts', 0))
                    span_s = int(time.time() - oldest_ts) if oldest_ts > 0 else 0
                    span_human = (f"{span_s // 86400}d"
                                    if span_s >= 86400
                                    else f"{span_s // 3600}h")
                    lines.append(
                        f"- Cross-session: {len(recs)} cold-starts "
                        f"over {span_human} (same Jarvis identity)"
                    )
        except Exception:
            pass

        # (2b) 🆕 [言出必行 I3 / Sir 2026-05-30] OPEN THREADS — 主脑开口前的接地.
        # 放早 (紧跟 cross-session, 在 verbose recent-thoughts 之前): block 超 max_chars
        # 截断时切的是尾部, 早放保证 I3 grounding 不被切掉 (真机发现尾部 (8) 被截).
        # prevention > interception. full only (主聊), mini 省 token 不注.
        if mode == 'full':
            try:
                _ot = self._build_open_threads_block(
                    int(vocab.get('open_threads_prompt_n', 3)))
                if _ot:
                    lines.append(_ot)
                    lines.append("")
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
                    # 🆕 [Sir 2026-05-28 12:30 β.5.45] 删 'inner_thought_surface'
                    # (退化 surface_to_sir 全通道, 走 Layer 1.5 chain pull).
                    'propose_protocol_activated',
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
                # 🆕 [Sir 2026-05-28 12:30 β.5.45] 删 'inner_thought_surface'
                # (退化 surface_to_sir 全通道, 走 Layer 1.5 chain pull).
                act_types = ('tool_called',
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
            # 🆕 [Sir 2026-05-28 fix46] 显式 caller_origin='yesterday_recap'
            # → trigger ds routing (1/day cold, high-stake summarize, ds 划算)
            txt = (self._call_llm(
                system_prompt, user_prompt,
                caller_origin='yesterday_recap',
            ) or '').strip()
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
