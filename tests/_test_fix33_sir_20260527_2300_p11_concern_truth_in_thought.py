# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 22:42 P11 治本] InnerThought daemon 看 concern ledger 真值.

Sir 真痛 (元否决根因):
  主脑刚回 Sir '只喝了 1/10 杯', 但 concern ledger 真值是 8/10. STM stale 或主脑撒谎.
  思考脑此前 prompt 只见 (id, what, severity, notes_chars), 看不到 daily_progress /
  last_user_feedback / optimal_timing → 无法 catch factual mismatch → 准则 5 漏.

治本 (准则 6 vocab 持久化 + 准则 8 优雅):
  inner_thought_identity_block_vocab.json 加 blocks_enabled.concern_truth_in_concerns
  + limits.concern_last_user_feedback_max_chars. 默 on.
  _collect_evidence: ev['concerns'][i] 加 daily_progress / last_user_feedback /
  optimal_timing 三字段.
  _build_prompt [YOUR ACTIVE CONCERNS]: 每 concern 后打 truth 子行 (📊/💬/⏰).
  prompt 加 B-class FACTUAL SELF-CORRECTION example 教 LLM 用 surface_to_sir RECTIFY.

测试覆盖:
  T1 vocab default 含 concern_truth_in_concerns + concern_last_user_feedback_max_chars
  T2 _collect_evidence: concern with daily_progress → ev['concerns'][i] 含 progress
  T3 _collect_evidence: concern with last_user_feedback → 含 raw_text 且 max_chars 截
  T4 _collect_evidence: concern with optimal_timing → 含 optimal_timing
  T5 _collect_evidence: vocab gate=False → 退化老 (无 truth 字段)
  T6 _build_prompt: 📊 ledger truth 行打 + 含 current/target/unit/date
  T7 _build_prompt: 💬 Sir last said 行打 + 截字
  T8 _build_prompt: ⏰ optimal_timing 行打
  T9 prompt 含 FACTUAL SELF-CORRECTION example (anchor 'CORRECTION — Sir 今日真实')
  T10 vocab schema 完整 + CLI 文件 (Sir 可改不需 .py)
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest import mock

if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_fake_concern(cid='c_h', what='Sir hydration', severity=0.8,
                          daily_progress=None, last_user_feedback=None,
                          optimal_timing='', notes_for_self=''):
    """Build minimal Concern-like object (duck-typed)."""
    obj = type('FakeConcern', (), {})()
    obj.id = cid
    obj.what_i_watch = what
    obj.severity = severity
    obj.notes_for_self = notes_for_self
    obj.daily_progress = daily_progress or {}
    obj.last_user_feedback = last_user_feedback or {}
    obj.optimal_timing = optimal_timing
    return obj


class _FakeLedger:
    def __init__(self, concerns):
        self._cs = concerns
    def list_active(self):
        return list(self._cs)


class TestP11ConcernTruthVocab(unittest.TestCase):
    """vocab default + schema 测试."""

    def test_t01_default_vocab_includes_concern_truth(self):
        """T1 InnerThoughtDaemon._IDENTITY_DEFAULT_VOCAB 必含 concern_truth_in_concerns."""
        import jarvis_inner_thought_daemon as itd
        dv = itd.InnerThoughtDaemon._IDENTITY_DEFAULT_VOCAB
        self.assertIn('concern_truth_in_concerns', dv['blocks_enabled'])
        self.assertTrue(dv['blocks_enabled']['concern_truth_in_concerns'],
            "默 on 让思考脑看真值, Sir 不应被默关")
        self.assertIn('concern_last_user_feedback_max_chars', dv['limits'])
        self.assertEqual(dv['limits']['concern_last_user_feedback_max_chars'], 100)


class TestP11CollectEvidence(unittest.TestCase):
    """_collect_evidence: ev['concerns'][i] 加真值字段 (vocab gate 控)."""

    def setUp(self):
        import jarvis_inner_thought_daemon as itd
        self.itd = itd
        # 创最小 daemon stub (绕 __init__ 重 deps)
        self.daemon = itd.InnerThoughtDaemon.__new__(itd.InnerThoughtDaemon)
        # _collect_evidence 用到的 attrs (minimal stub)
        self.daemon.swm = None
        self.daemon.session_stm = None
        self.daemon.concerns_ledger = None
        self.daemon.relational_state = None
        self.daemon._recent_thoughts_buf = []
        self.daemon._recent_thoughts_lock = type('FakeLock', (), {
            '__enter__': lambda s: None, '__exit__': lambda *a: None,
        })()
        # vocab cache → default on
        self.daemon._IDENTITY_VOCAB_CACHE = {
            'data': None, 'mtime': 0.0, 'checked_at': 0.0,
        }

    def test_t02_collect_includes_daily_progress(self):
        """T2 concern with daily_progress → ev['concerns'][0] 含 progress dict.

        [P1 fix / 2026-05-31] iso_date 必须用 today — collect 路径有 fix31 date-guard
        (iso_date==today 才注), 原硬编码 '2026-05-27' 跨天后恒被过滤 → 该测旧编码必 fail.
        """
        _today = time.strftime('%Y-%m-%d', time.localtime())
        c = _make_fake_concern(
            cid='c_h', what='hydration',
            daily_progress={
                'current': 8, 'target': 10, 'unit': 'cups',
                'iso_date': _today,
            },
        )
        self.daemon.concerns_ledger = _FakeLedger([c])
        ev = self.daemon._collect_evidence('awake', 60)
        self.assertEqual(len(ev['concerns']), 1)
        c0 = ev['concerns'][0]
        self.assertIn('daily_progress', c0,
            "daily_progress 必 inject (vocab default on)")
        dp = c0['daily_progress']
        self.assertEqual(dp['current'], 8)
        self.assertEqual(dp['target'], 10)
        self.assertEqual(dp['unit'], 'cups')
        self.assertEqual(dp['iso_date'], _today)

    def test_t03_collect_includes_last_user_feedback_truncated(self):
        """T3 last_user_feedback.raw_text 注入并按 vocab max_chars 截."""
        long_text = '我今天喝了 8 杯水了, ' * 20  # 远超 100 char
        c = _make_fake_concern(
            cid='c_h',
            last_user_feedback={
                'raw_text': long_text,
                'judgement': {},
                'when': 1000,
            },
        )
        self.daemon.concerns_ledger = _FakeLedger([c])
        ev = self.daemon._collect_evidence('awake', 60)
        c0 = ev['concerns'][0]
        self.assertIn('last_user_feedback', c0)
        fb = c0['last_user_feedback']
        self.assertIsInstance(fb, str,
            "last_user_feedback 应抽出 raw_text 字符串 (非 dict)")
        self.assertLessEqual(len(fb), 100,
            f"应按 vocab limit (100) 截. 实长 {len(fb)}")

    def test_t04_collect_includes_optimal_timing(self):
        """T4 optimal_timing 注入."""
        c = _make_fake_concern(cid='c_s', optimal_timing='before_sleep')
        self.daemon.concerns_ledger = _FakeLedger([c])
        ev = self.daemon._collect_evidence('awake', 60)
        c0 = ev['concerns'][0]
        self.assertEqual(c0.get('optimal_timing'), 'before_sleep')

    def test_t05_vocab_gate_off_falls_back(self):
        """T5 vocab blocks_enabled[concern_truth_in_concerns]=False → 老行为."""
        c = _make_fake_concern(
            cid='c_h',
            daily_progress={'current': 8, 'target': 10, 'unit': 'cups',
                            'iso_date': '2026-05-27'},
            optimal_timing='before_sleep',
        )
        self.daemon.concerns_ledger = _FakeLedger([c])
        # Mock _load_identity_block_vocab → gate off
        fake_vocab = {
            'blocks_enabled': {'concern_truth_in_concerns': False},
            'limits': {'concern_last_user_feedback_max_chars': 100},
        }
        with mock.patch.object(self.daemon, '_load_identity_block_vocab',
                                  return_value=fake_vocab):
            ev = self.daemon._collect_evidence('awake', 60)
        c0 = ev['concerns'][0]
        self.assertNotIn('daily_progress', c0,
            "gate off → 不 inject daily_progress")
        self.assertNotIn('optimal_timing', c0)
        self.assertNotIn('last_user_feedback', c0)
        # 原老字段仍在
        self.assertEqual(c0['id'], 'c_h')
        self.assertIn('severity', c0)

    def test_t06_empty_progress_not_injected(self):
        """T2b 空 daily_progress (无 current/target) → 不 inject (避免空行)."""
        c = _make_fake_concern(cid='c_h', daily_progress={})
        self.daemon.concerns_ledger = _FakeLedger([c])
        ev = self.daemon._collect_evidence('awake', 60)
        c0 = ev['concerns'][0]
        self.assertNotIn('daily_progress', c0,
            "空 progress 不应 inject (避免 prompt 空行)")


class TestP11BuildPrompt(unittest.TestCase):
    """_build_prompt: [YOUR ACTIVE CONCERNS] 子行打 truth 行."""

    def setUp(self):
        import jarvis_inner_thought_daemon as itd
        self.itd = itd
        self.daemon = itd.InnerThoughtDaemon.__new__(itd.InnerThoughtDaemon)
        self.daemon._IDENTITY_VOCAB_CACHE = {
            'data': None, 'mtime': 0.0, 'checked_at': 0.0,
        }
        # mock build_lifetime_block / 其他 builder 让 _build_prompt 跑通
        self.daemon.build_lifetime_block = lambda mode='mini': ''
        self.daemon.build_recent_thoughts_block = lambda *a, **kw: ''

    def _build(self, concerns_evidence, want='both'):
        """直接 mock evidence dict 跑 prompt builder, skip _collect_evidence.
        
        want='both' (默) → 'sys\\nuser', want='user' → 只 user, want='sys' → 只 sys.
        T10 用 'user' (system 教学 example 永含 emoji 会 false match).
        """
        evidence = {
            'now_iso': '2026-05-27T22:42:00',
            'hour': 22,
            'swm_events': [],
            'stm': [],
            'concerns': concerns_evidence,
            'all_active_concern_ids': [c['id'] for c in concerns_evidence],
            'recent_thoughts': [],
        }
        # _build_prompt 返 (system, user) 元组
        try:
            sys_prompt, user_prompt = self.daemon._build_prompt(
                'awake', evidence, free_categories=list('ABCDE'),
            )
            if want == 'sys':
                return sys_prompt
            if want == 'user':
                return user_prompt
            return sys_prompt + '\n' + user_prompt
        except Exception as e:
            self.fail(f'_build_prompt 挂: {e}')

    def test_t07_prompt_renders_daily_progress_line(self):
        """T6 📊 ledger truth 行打 + 含 current/target/unit/date."""
        concerns_ev = [{
            'id': 'c_h', 'what': 'hydration', 'severity': 0.8,
            'notes_chars': 50,
            'daily_progress': {
                'current': 8, 'target': 10, 'unit': 'cups',
                'iso_date': '2026-05-27',
            },
        }]
        prompt = self._build(concerns_ev)
        self.assertIn('📊 ledger truth', prompt,
            "[YOUR ACTIVE CONCERNS] 应打 📊 ledger truth 子行")
        self.assertIn('8/10', prompt)
        self.assertIn('cups', prompt)
        self.assertIn('2026-05-27', prompt)

    def test_t08_prompt_renders_last_user_feedback_line(self):
        """T7 💬 Sir last said 行打 + 含 raw_text."""
        concerns_ev = [{
            'id': 'c_h', 'what': 'hydration', 'severity': 0.8,
            'notes_chars': 50,
            'last_user_feedback': '我已经喝了 8 杯水了',
        }]
        prompt = self._build(concerns_ev)
        self.assertIn('💬 Sir last said', prompt,
            "应打 💬 Sir last said 子行")
        self.assertIn('我已经喝了 8 杯水了', prompt)

    def test_t09_prompt_renders_optimal_timing_line(self):
        """T8 ⏰ optimal_timing 行打."""
        concerns_ev = [{
            'id': 'c_h', 'what': 'hydration', 'severity': 0.8,
            'notes_chars': 50,
            'optimal_timing': 'before_sleep',
        }]
        prompt = self._build(concerns_ev)
        self.assertIn('⏰ optimal_timing', prompt,
            "应打 ⏰ optimal_timing 子行")
        self.assertIn('before_sleep', prompt)

    def test_t10_prompt_skips_truth_lines_when_empty(self):
        """T6b concern 无 truth 字段 → user prompt 不打 truth 行 (避免浪费)."""
        concerns_ev = [{
            'id': 'c_h', 'what': 'hydration', 'severity': 0.8,
            'notes_chars': 50,
        }]
        # 只查 user prompt 段 (system 教学 example 含 emoji 会 false match)
        user_prompt = self._build(concerns_ev, want='user')
        self.assertNotIn('📊 ledger truth', user_prompt,
            "user prompt concern 无 truth 字段时不打 📊 子行")
        self.assertNotIn('💬 Sir last said', user_prompt)
        self.assertNotIn('⏰ optimal_timing', user_prompt)

    def test_t11_prompt_contains_factual_self_correction_example(self):
        """T9 prompt system 段含 P11 FACTUAL SELF-CORRECTION example.

        🆕 [Sir 2026-05-28 12:30 β.5.45] surface_to_sir 退化, P11 example 改走
        Layer 1.5 + sal=0.90 + thought.thought 自身含真值 + RECTIFY 指令 path.
        主脑下轮 prompt [MY RECENT INNER THOUGHTS] 自动看 thought 本身 → 自决纠正.
        """
        concerns_ev = []
        prompt = self._build(concerns_ev)
        self.assertIn('FACTUAL SELF-CORRECTION', prompt,
            "prompt 必含 P11 教学 example anchor")
        # 关键 anchor: 教 LLM thought.thought 本身含真值 RECTIFY (走 Layer 1.5)
        self.assertIn('CORRECTION', prompt)
        self.assertIn('Layer 1.5', prompt,
            "prompt 必示 Layer 1.5 path 替代 surface_to_sir")
        self.assertIn('ledger truth', prompt.lower(),
            "示例必引 'ledger truth' 教 LLM concept")


class TestP11VocabSchema(unittest.TestCase):
    """vocab JSON + CLI 文件完整性 (准则 6 持久化 + CLI 可改)."""

    def test_t12_vocab_file_has_new_key(self):
        """vocab JSON 必含 concern_truth_in_concerns key 默 on."""
        vocab_path = os.path.join(
            ROOT, 'memory_pool',
            'inner_thought_identity_block_vocab.json',
        )
        # 文件可能不存在 (lazy load fall back default). 若存在则验 key
        if not os.path.exists(vocab_path):
            self.skipTest(f"vocab {vocab_path} 不存在 (lazy default OK)")
        with open(vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        be = data.get('blocks_enabled') or {}
        # 若用户已自定义 vocab, 不一定有此 key → skip 不报错
        if 'concern_truth_in_concerns' not in be:
            self.skipTest("用户自定义 vocab 无此 key, default fallback 已覆盖")
        self.assertTrue(be['concern_truth_in_concerns'],
            "若 vocab 显式列出此 key, 应默 on")


if __name__ == '__main__':
    unittest.main(verbosity=2)
