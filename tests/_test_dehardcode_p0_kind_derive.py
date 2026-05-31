# -*- coding: utf-8 -*-
"""[thinking-dehardcode-P0 / Sir 2026-05-31] 识去硬编码 Phase 0 脚手架.

工程: 拔识的最后一条硬编码 = A-E 5 类 category 槽 → 势能驱动涌现的 kind.
详 docs/JARVIS_THINKING_DEHARDCODE_CATEGORIES_DESIGN.md + AGENT_KICKOFF_THINKING_DEHARDCODE.md.

Phase 0 = 脚手架 (本 commit, 恒 legacy, 双写 derived_kind 不改行为):
  - flag thinking_kind_mode (默 legacy) + reader (mtime cache, fail→legacy)
  - effect→kind 派生表 (_kind_from_effect, 设计 §5.1) — effect 的事后 label, 无冷却
  - InnerThought.derived_kind 字段 + persist 前赋值 (与 category 并存, 不影响决策)

覆盖 (纯函数, 无 LLM):
  T1  每 actionable 前缀 → 正确 kind (设计 §5.1 全表)
  T2  带 payload 的 actionable (prefix:arg:arg) → 取前缀派生
  T3  REST (has_rest=True) → rest
  T4  none / 空 (无 REST) → empty (filler)
  T5  unknown 前缀 (deprecated/future) → act (兜底)
  T6  大小写不敏感 (LLM 输出 UpperCase 仍对)
  T7  flag 默认 legacy (committed vocab); 非法值 → legacy
  T8  emergent 模式可读 (cache 注入模拟); 回 legacy
  T9  InnerThought.derived_kind 字段存在且默认 '' (老 jsonl 兼容)
  T10 vocab 与 py seed default 一致 (准则6 三件套不漂移)
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_inner_thought_daemon as itd
from jarvis_inner_thought_daemon import (
    InnerThought,
    _kind_from_effect,
    _thinking_kind_mode,
    _load_thinking_kind_config,
    _THINKING_KIND_DEFAULT,
)


def _reset_kind_cache() -> None:
    """清 mtime cache, 强制下次从真 vocab 文件重读 (隔离 test 间污染)."""
    itd._THINKING_KIND_CACHE['data'] = None
    itd._THINKING_KIND_CACHE['mtime'] = 0.0
    itd._THINKING_KIND_CACHE['checked_at'] = 0.0


class TestP0KindDerive(unittest.TestCase):
    def setUp(self):
        _reset_kind_cache()

    def tearDown(self):
        _reset_kind_cache()

    # ----- T1: 设计 §5.1 全表 -----
    def test_t1_each_effect_to_kind(self):
        cases = {
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
        }
        for prefix, expect in cases.items():
            self.assertEqual(
                _kind_from_effect(prefix), expect,
                f"{prefix} 应派生 {expect}")

    # ----- T2: 带 payload -----
    def test_t2_with_payload(self):
        self.assertEqual(
            _kind_from_effect('update_concern_severity:sir_sleep:+0.1'), 'solve')
        self.assertEqual(
            _kind_from_effect('adjust_concern_notes:sir_x:DO NOT volunteer'),
            'shape_next')
        self.assertEqual(
            _kind_from_effect('fire_nudge:care:Sir, water check.'), 'reach_out')

    # ----- T3: REST -----
    def test_t3_rest(self):
        self.assertEqual(_kind_from_effect('none', has_rest=True), 'rest')
        # has_rest 优先于 actionable 内容
        self.assertEqual(_kind_from_effect('', has_rest=True), 'rest')

    # ----- T4: none / 空 → empty -----
    def test_t4_none_empty(self):
        self.assertEqual(_kind_from_effect('none'), 'empty')
        self.assertEqual(_kind_from_effect(''), 'empty')
        self.assertEqual(_kind_from_effect('  '), 'empty')
        self.assertEqual(_kind_from_effect(None), 'empty')

    # ----- T5: unknown → act -----
    def test_t5_unknown_fallback(self):
        self.assertEqual(_kind_from_effect('some_future_action:foo'), 'act')
        # deprecated (publish_swm/surface_to_sir) 不在表 → act
        self.assertEqual(_kind_from_effect('publish_swm:x'), 'act')
        self.assertEqual(_kind_from_effect('surface_to_sir:x'), 'act')

    # ----- T6: 大小写不敏感 -----
    def test_t6_case_insensitive(self):
        self.assertEqual(
            _kind_from_effect('UPDATE_CONCERN_SEVERITY:sir_x:+0.1'), 'solve')
        self.assertEqual(_kind_from_effect('Propose_Stance:Sir:view'), 'reflect')

    # ----- T7: seed fallback 恒 legacy (mode 是部署开关) -----
    def test_t7_seed_default_is_legacy(self):
        # 种子 fallback 恒 legacy (vocab 缺失/损坏 → 安全回退 A-E+冷却).
        # prod 实际 mode 是部署开关 (Sir 2026-05-31 真机迭代翻 emergent), 不硬断言.
        self.assertEqual(_THINKING_KIND_DEFAULT['thinking_kind_mode'], 'legacy')
        self.assertIn(_thinking_kind_mode(), ('legacy', 'emergent'))

    def test_t7b_illegal_mode_falls_to_legacy(self):
        # cache 注入非法值 → _thinking_kind_mode 守门回 legacy
        itd._THINKING_KIND_CACHE['data'] = {'thinking_kind_mode': 'bogus'}
        itd._THINKING_KIND_CACHE['checked_at'] = time.time()
        self.assertEqual(_thinking_kind_mode(), 'legacy')

    # ----- T8: emergent 可读 -----
    def test_t8_emergent_readable(self):
        itd._THINKING_KIND_CACHE['data'] = {'thinking_kind_mode': 'emergent'}
        itd._THINKING_KIND_CACHE['checked_at'] = time.time()
        self.assertEqual(_thinking_kind_mode(), 'emergent')

    # ----- T9: derived_kind 字段 -----
    def test_t9_dataclass_field_default(self):
        t = InnerThought(
            id='t_p0', ts=1000.0, ts_iso='2026-05-31T18:00:00',
            category='A', thought='test', salience=0.5, actionable='none',
        )
        # 默认 '' (老 jsonl 无此字段时兼容)
        self.assertEqual(t.derived_kind, '')
        # asdict 序列化含此字段 (持久化双写)
        from dataclasses import asdict
        self.assertIn('derived_kind', asdict(t))

    def test_t9b_old_jsonl_dict_construct(self):
        # 老 jsonl (无 derived_kind) → InnerThought(**td) 仍可构造 (默认 '')
        td = {
            'id': 'old', 'ts': 1.0, 'ts_iso': '?', 'category': 'B',
            'thought': 'old', 'salience': 0.5, 'actionable': 'none',
        }
        t = InnerThought(**td)
        self.assertEqual(t.derived_kind, '')

    # ----- T10: vocab ↔ py seed 不漂移 -----
    def test_t10_vocab_matches_seed(self):
        path = os.path.join(ROOT, 'memory_pool', 'thinking_kind_vocab.json')
        self.assertTrue(os.path.exists(path), 'vocab 文件须存在 (准则6 持久化)')
        with open(path, 'r', encoding='utf-8') as f:
            vocab = json.load(f)
        # mode 是部署开关 (legacy|emergent), 不比对; 派生表 + 特例 label 不漂移才比对
        self.assertIn(vocab.get('thinking_kind_mode'), ('legacy', 'emergent'))
        self.assertEqual(vocab.get('effect_to_kind'),
                         _THINKING_KIND_DEFAULT['effect_to_kind'])
        for k in ('kind_for_rest', 'kind_for_none', 'kind_for_unknown'):
            self.assertEqual(vocab.get(k), _THINKING_KIND_DEFAULT[k])


if __name__ == '__main__':
    unittest.main()
