# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 12:21 真意 Meta-thinking] InnerThought 自决下次 tick 间隔.

Sir 原话:
  "这个思考的间隔能否也成为他思考的一部分? 发现我离开了就减慢思考频率,
  发现我回来了就回到 1 分钟一次, 如果很需要频繁思考甚至可以提高 30s 一次.
  设计一下, 看看有没有什么弊端解决一下."

设计 (准则 6 信任 LLM + Python 物理保底):
  1. InnerThought 加 next_interval_s + tick_origin 字段
  2. prompt 加 NEXT_INTERVAL tag (enum 30/60/180/600/1800/default)
  3. parse next_interval (raw LLM value, 0 = default)
  4. _resolve_next_interval 二段保底:
     a. Physical gate: LLM 选超物理边界 → fallback baseline
        (e.g. sleep 不能选 30 / active 不能选 1800)
     b. Smoothing: 最近 5 thought ≥3 选 30 + 平均 sal<0.5 → 强制回 60
        (防 LLM 总选 30 token 爆 + 低质量急思考惩罚)
  5. start() loop 优先用 LLM-chosen interval (fallback baseline)

弊端 + 解决:
  | 弊端 | 解决 |
  |---|---|
  | LLM 总选 30s token 爆 | Smoothing 强制回 60s |
  | LLM 选非法值 (e.g. 45s) | enum 校验 (只允许 5 enum 值) |
  | LLM 离线判断错 | 物理 gate 保底 |
  | 频率震荡 | 每次自决, 不 sticky, 自然变化 (feature) |
  | 重复思考 | cooldown 5min (现有) 防 |

测试覆盖 (13 个):
  L1 InnerThought dataclass 加 next_interval_s + tick_origin
  L2 prompt 含 NEXT_INTERVAL tag + 教学
  L3 parse 'default' → next_interval_s=0
  L4 parse '30' → next_interval_s=30 (合法 enum)
  L5 parse '90' → next_interval_s=0 (非法 enum 拒; 45 现合法 active baseline)
  L6 parse 缺 NEXT_INTERVAL → next_interval_s=0 (向后兼容)
  L7 resolve LLM 没选 (=0) → return baseline + origin='default'
  L8 resolve LLM 选 30 + active → return 30 + origin='llm_chosen'
  L9 resolve LLM 选 30 + sleep → return baseline + origin='llm_gated' (物理 gate)
  L10 resolve LLM 选 1800 + active → return baseline + origin='llm_gated'
  L11 resolve smoothing: 最近 5 个都选 30 + sal 全 0.3 → 强制 60 + origin='llm_smoothed'
  L12 resolve smoothing: 最近 5 个选 30 + sal 全 0.9 → 真用 30 + origin='llm_chosen' (高 sal 不 smooth)
  L13 get_stats 含 next_tick_interval_s + tick_origin_stats
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(),
                          f'meta_thinking_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


def _mk_thought(next_int: int = 0, sal: float = 0.5, cat: str = 'A'):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f't_{time.time()}',
        ts=time.time(),
        ts_iso='?',
        category=cat,
        thought='test thought',
        salience=sal,
        actionable='none',
        next_interval_s=next_int,
    )


# ==========================================================================
# L1: dataclass 加 next_interval_s + tick_origin
# ==========================================================================
class TestL1DataclassFields(unittest.TestCase):
    def test_inner_thought_has_next_interval_s_and_tick_origin(self):
        from jarvis_inner_thought_daemon import InnerThought
        t = InnerThought(
            id='t1', ts=time.time(), ts_iso='?',
            category='A', thought='x', salience=0.5, actionable='none',
        )
        self.assertEqual(t.next_interval_s, 0,
            'default next_interval_s = 0 (向后兼容)')
        self.assertEqual(t.tick_origin, '',
            'default tick_origin = "" (向后兼容)')


# ==========================================================================
# L2: prompt 含 NEXT_INTERVAL tag + 教学
# ==========================================================================
class TestL2PromptHasNextInterval(unittest.TestCase):
    def test_prompt_has_next_interval_tag_and_teaching(self):
        d = _build_daemon()
        sys_p, _ = d._build_prompt(
            'active', {'sir_state': 'active'},
            free_categories=['A', 'B', 'C', 'D', 'E'],
        )
        self.assertIn('<NEXT_INTERVAL>', sys_p,
            'prompt 必须含 NEXT_INTERVAL tag')
        self.assertIn('30 | 60 | 180 | 600 | 1800 | default', sys_p,
            'prompt 必须含 enum 5 + default')
        self.assertIn('URGENT thought', sys_p,
            'prompt 必须教 LLM 何时选 30s (URGENT)')
        self.assertIn('Smoothing', sys_p,
            'prompt 必须教 LLM smoothing 机制 (防 LLM 滥选 30s)')


# ==========================================================================
# L3-L6: parse 各种 NEXT_INTERVAL 值
# ==========================================================================
class TestL3ParseDefault(unittest.TestCase):
    def test_parse_default_returns_zero(self):
        d = _build_daemon()
        raw = (
            "<CATEGORY>A</CATEGORY>"
            "<THOUGHT>test</THOUGHT>"
            "<SALIENCE>0.5</SALIENCE>"
            "<ACTIONABLE>none</ACTIONABLE>"
            "<EVIDENCE_LINK>none</EVIDENCE_LINK>"
            "<NEXT_INTERVAL>default</NEXT_INTERVAL>"
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertIsNotNone(t)
        self.assertEqual(t.next_interval_s, 0,
            "'default' 应 parse 成 0 (用 baseline)")


class TestL4ParseLegalEnum(unittest.TestCase):
    def test_parse_30_returns_30(self):
        d = _build_daemon()
        raw = (
            "<CATEGORY>A</CATEGORY>"
            "<THOUGHT>urgent test</THOUGHT>"
            "<SALIENCE>0.9</SALIENCE>"
            "<ACTIONABLE>none</ACTIONABLE>"
            "<EVIDENCE_LINK>none</EVIDENCE_LINK>"
            "<NEXT_INTERVAL>30</NEXT_INTERVAL>"
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertEqual(t.next_interval_s, 30)

    def test_parse_all_enum_values(self):
        d = _build_daemon()
        for v in (30, 60, 180, 600, 1800):
            raw = (
                f"<CATEGORY>A</CATEGORY>"
                f"<THOUGHT>test</THOUGHT>"
                f"<SALIENCE>0.5</SALIENCE>"
                f"<ACTIONABLE>none</ACTIONABLE>"
                f"<EVIDENCE_LINK>none</EVIDENCE_LINK>"
                f"<NEXT_INTERVAL>{v}</NEXT_INTERVAL>"
            )
            t = d._parse_thought(raw, 'active', 60)
            self.assertEqual(t.next_interval_s, v,
                f'enum value {v} 应被 parse 接受')


class TestL5ParseIllegalEnum(unittest.TestCase):
    def test_parse_illegal_enum_rejected(self):
        # 🆕 [Sir 2026-05-31 21:04] 45 已是合法 active baseline (_NEXT_INTERVAL_ENUM
        # 含 45, INTERVAL_ACTIVE_S=45) — 旧测 "45 被拒" stale. 改测真非法值 90
        # (不在 {30,45,60,180,600,1800}) → 仍验"非法 numeric enum 拒"逻辑。
        d = _build_daemon()
        raw = (
            "<CATEGORY>A</CATEGORY>"
            "<THOUGHT>test</THOUGHT>"
            "<SALIENCE>0.5</SALIENCE>"
            "<ACTIONABLE>none</ACTIONABLE>"
            "<EVIDENCE_LINK>none</EVIDENCE_LINK>"
            "<NEXT_INTERVAL>90</NEXT_INTERVAL>"
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertEqual(t.next_interval_s, 0,
            '非法 enum 值 90 应被 parse 拒 (返回 0 = default)')

    def test_parse_garbage_rejected(self):
        d = _build_daemon()
        raw = (
            "<CATEGORY>A</CATEGORY>"
            "<THOUGHT>test</THOUGHT>"
            "<SALIENCE>0.5</SALIENCE>"
            "<ACTIONABLE>none</ACTIONABLE>"
            "<EVIDENCE_LINK>none</EVIDENCE_LINK>"
            "<NEXT_INTERVAL>garbage</NEXT_INTERVAL>"
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertEqual(t.next_interval_s, 0,
            'garbage value 应被 parse 拒')


class TestL6ParseMissing(unittest.TestCase):
    def test_parse_missing_tag_compat(self):
        """老 LLM 输出没 NEXT_INTERVAL tag → next_interval_s=0 (向后兼容)."""
        d = _build_daemon()
        raw = (
            "<CATEGORY>A</CATEGORY>"
            "<THOUGHT>test</THOUGHT>"
            "<SALIENCE>0.5</SALIENCE>"
            "<ACTIONABLE>none</ACTIONABLE>"
            "<EVIDENCE_LINK>none</EVIDENCE_LINK>"
        )
        t = d._parse_thought(raw, 'active', 60)
        self.assertIsNotNone(t, '缺 NEXT_INTERVAL 不应导致 parse fail')
        self.assertEqual(t.next_interval_s, 0)


# ==========================================================================
# L7-L10: _resolve_next_interval 物理 gate
# ==========================================================================
class TestL7ResolveDefault(unittest.TestCase):
    def test_resolve_llm_chose_default_returns_baseline(self):
        d = _build_daemon()
        t = _mk_thought(next_int=0)  # LLM 没选
        with patch.object(d, '_classify_sir_state', return_value='active'):
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, d.INTERVAL_ACTIVE_S,
            "LLM 没选 (= 0) → 用 baseline")
        self.assertEqual(origin, 'default')


class TestL8ResolveLLMChosen(unittest.TestCase):
    def test_resolve_llm_30_active_returns_30(self):
        d = _build_daemon()
        t = _mk_thought(next_int=30, sal=0.9)
        with patch.object(d, '_classify_sir_state', return_value='active'):
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 30,
            "LLM 选 30 + Sir active (gate 允许) + 高 sal (不 smooth) → 真用 30")
        self.assertEqual(origin, 'llm_chosen')


class TestL9ResolvePhysicalGateSleep(unittest.TestCase):
    def test_resolve_llm_30_sleep_gated(self):
        d = _build_daemon()
        t = _mk_thought(next_int=30)
        with patch.object(d, '_classify_sir_state', return_value='sleep'):
            interval, origin = d._resolve_next_interval(t, 'sleep')
        self.assertEqual(interval, d.INTERVAL_SLEEP_S,
            "LLM 选 30 + Sir sleep (gate 拒 30/60/180) → fallback baseline")
        self.assertEqual(origin, 'llm_gated')


class TestL10ResolvePhysicalGateActive(unittest.TestCase):
    def test_resolve_llm_1800_active_gated(self):
        d = _build_daemon()
        t = _mk_thought(next_int=1800)
        with patch.object(d, '_classify_sir_state', return_value='active'):
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, d.INTERVAL_ACTIVE_S,
            "LLM 选 1800 + Sir active (gate 拒 600/1800) → fallback baseline")
        self.assertEqual(origin, 'llm_gated')


# ==========================================================================
# L11-L12: Smoothing (LLM 总选 30 + 低 sal → 强制 60)
# ==========================================================================
class TestL11ResolveSmoothing(unittest.TestCase):
    def test_smoothing_low_quality_30s_forced_to_60(self):
        """最近 5 thought ≥3 选 30 + 平均 sal<0.5 → 强制回 60s (token 保护)."""
        d = _build_daemon()
        # 注入 5 个 history thought: 都选 30 + sal 0.3
        for _ in range(5):
            d._thoughts.append(_mk_thought(next_int=30, sal=0.3))
        t = _mk_thought(next_int=30, sal=0.3)  # 新 thought 也选 30
        with patch.object(d, '_classify_sir_state', return_value='active'):
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 60,
            "Smoothing 强制回 60s (LLM 总选 30 + 低 sal)")
        self.assertEqual(origin, 'llm_smoothed')


class TestL12ResolveHighSalNoSmoothing(unittest.TestCase):
    def test_high_sal_30s_not_smoothed(self):
        """最近 5 thought 都选 30 但 sal 高 (0.9) → 真用 30 (高质量急思考真该急)."""
        d = _build_daemon()
        for _ in range(5):
            d._thoughts.append(_mk_thought(next_int=30, sal=0.9))
        t = _mk_thought(next_int=30, sal=0.9)
        with patch.object(d, '_classify_sir_state', return_value='active'):
            interval, origin = d._resolve_next_interval(t, 'active')
        self.assertEqual(interval, 30,
            "高 sal 急思考不被 smoothing 拦 (准则 6 信任 LLM)")
        self.assertEqual(origin, 'llm_chosen')


# ==========================================================================
# L13: get_stats 含 self-pacing 字段
# ==========================================================================
class TestL13GetStats(unittest.TestCase):
    def test_get_stats_has_next_tick_interval_and_origin_stats(self):
        d = _build_daemon()
        stats = d.get_stats()
        self.assertIn('next_tick_interval_s', stats,
            'get_stats 必须返 next_tick_interval_s (LLM self-paced interval)')
        self.assertIn('tick_origin_stats', stats,
            'get_stats 必须返 tick_origin_stats (Sir 看 LLM 真在 pace)')
        # 初始 stats 5 个 origin 都是 0
        # (saturation_force 加于 Sir 2026-05-28 19:20 真意 — Jarvis 学会休息)
        self.assertEqual(stats['tick_origin_stats'], {
            'default': 0, 'llm_chosen': 0,
            'llm_gated': 0, 'llm_smoothed': 0,
            'saturation_force': 0,
        })


if __name__ == '__main__':
    unittest.main()
