# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 22:11 真问 P10 治本] InnerThought 自 pacing 准则 6 三维耦合.

Sir 真问 (审 audit 后):
  "贾维斯会动态变频吗? 发现自己不用太担心吗?
   一直在想, 经常想重复事情"
Sir 自查 4 个 P6-P9 hot-fix 选项: "都像硬编码, 你觉得呢?"

根因审视: 4 选项 (改阈值 / sim hash / meta-detection / baseline 调) 全
        magic number 或 Python if rule, 违反准则 6 (信任 LLM, 持久化 vocab).
        Sir 真意 anchor: "应该动态从对话中提取, python 规则无法覆盖的部分引入 LLM".

治本 (P10 准则 6 三维耦合):
  1. 数据强耦合: _compute_self_signal 算 3 类 raw signal, publish SWM
     'inner_thought_self_signal' (主脑/Reflector/Dashboard 都能看).
  2. 决策集中 LLM: _build_prompt 加 [YOUR RECENT PACING SIGNAL] 段 (中性
     事实陈述, NEVER 加 imperative 指令), 让 LLM 自决 NEXT_INTERVAL.
  3. 持久化 + CLI: memory_pool/inner_thought_pacing_vocab.json + 
     scripts/pacing_dump.py Sir 改不动 .py.

3 类 raw signal (准则 6 fact-only):
  - self_recent_quality: avg_salience / actionable_rate / mediocre_rate
  - self_thread_diversity: unique_threads / top_thread_share
  - overall_concern_pressure: max/avg severity / active_count / 
                              high_severity_count / recent_swm_event_count_1h

测试覆盖:
  - vocab JSON 持久化 + lazy load + mtime hot reload
  - _compute_self_signal 真算 3 类 signal (空 / 全 mediocre / 混合)
  - prompt 含 [YOUR RECENT PACING SIGNAL] 段且 tone neutral
  - SWM publish event etype 正确
  - signals_enabled / prompt_signal_block / swm_publish 真 gate
  - prompt 段 NEVER 含 imperative ("you should" / "you must" / "slow down")
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


# ----------------------------------------------------------------------
# 共享 fixture
# ----------------------------------------------------------------------

def _make_thought(category='A', salience=0.5, actionable='none',
                    thread_id='thread_A', ago_s=10):
    """构造一个 InnerThought (复用模块的 dataclass)."""
    from jarvis_inner_thought_daemon import InnerThought
    now = time.time()
    return InnerThought(
        id=f"thought_{int((now - ago_s) * 1000) % 100000}",
        ts=now - ago_s,
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S',
                                time.localtime(now - ago_s)),
        category=category,
        thought='dummy thought text',
        salience=salience,
        actionable=actionable,
        thread_id=thread_id,
    )


def _build_daemon_with_thoughts(thoughts=None, concerns_severities=None):
    """构造 InnerThoughtDaemon 实例 (mocked deps)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    mock_router = MagicMock()
    mock_ledger = MagicMock()
    # build concerns_ledger if specified
    if concerns_severities is not None:
        active = []
        for i, sev in enumerate(concerns_severities):
            c = MagicMock()
            c.severity = sev
            c.id = f"concern_{i}"
            active.append(c)
        mock_ledger.list_active = MagicMock(return_value=active)
    else:
        mock_ledger.list_active = MagicMock(return_value=[])
    daemon = InnerThoughtDaemon(
        key_router=mock_router,
        concerns_ledger=mock_ledger,
    )
    # always replace _thoughts (即使空 list 也要覆盖 — _load_persist 已载入老 thoughts)
    if thoughts is not None:
        daemon._thoughts = list(thoughts)
    return daemon


# ----------------------------------------------------------------------
# Test 1: vocab JSON 持久化 + lazy load + mtime hot reload
# ----------------------------------------------------------------------

class TestPacingVocabPersistence(unittest.TestCase):
    def test_vocab_file_exists_and_valid(self):
        path = os.path.join(_REPO, 'memory_pool',
                              'inner_thought_pacing_vocab.json')
        self.assertTrue(os.path.exists(path),
            'memory_pool/inner_thought_pacing_vocab.json 必须存在')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 校验必要 key
        self.assertIn('lookback_n', data)
        self.assertIn('signals_enabled', data)
        self.assertIn('prompt_signal_block', data)
        self.assertIn('swm_publish', data)
        # 校验 3 类 signal 全在
        sigs = data['signals_enabled']
        self.assertIn('self_recent_quality', sigs)
        self.assertIn('self_thread_diversity', sigs)
        self.assertIn('overall_concern_pressure', sigs)

    def test_load_pacing_config_returns_full_keys(self):
        from jarvis_inner_thought_daemon import _load_pacing_config
        cfg = _load_pacing_config()
        self.assertIsInstance(cfg, dict)
        self.assertIn('lookback_n', cfg)
        self.assertIn('signals_enabled', cfg)
        self.assertIn('prompt_signal_block', cfg)
        self.assertIn('swm_publish', cfg)

    def test_load_pacing_config_fallback_on_missing_file(self):
        """vocab 文件不存在 → fallback default (daemon 不崩)."""
        import jarvis_inner_thought_daemon as mod
        # 临时改 path 到不存在文件 (cache 也清)
        original_path = mod._PACING_VOCAB_PATH
        original_cache = dict(mod._PACING_VOCAB_CACHE)
        try:
            mod._PACING_VOCAB_PATH = os.path.join(
                tempfile.gettempdir(),
                f'_test_nonexistent_pacing_{os.getpid()}.json'
            )
            mod._PACING_VOCAB_CACHE['data'] = None
            mod._PACING_VOCAB_CACHE['checked_at'] = 0.0
            cfg = mod._load_pacing_config()
            self.assertIsInstance(cfg, dict)
            # 应该是 default
            self.assertEqual(cfg['lookback_n'], 5)
        finally:
            mod._PACING_VOCAB_PATH = original_path
            mod._PACING_VOCAB_CACHE.update(original_cache)


# ----------------------------------------------------------------------
# Test 2: _compute_self_signal — 3 类 raw signal
# ----------------------------------------------------------------------

class TestComputeSelfSignal(unittest.TestCase):
    def test_empty_thoughts_returns_concern_only(self):
        """无 thought → quality/diversity 没 (gated by `and recent`), 但 concern 仍算."""
        daemon = _build_daemon_with_thoughts(
            thoughts=[], concerns_severities=[0.5, 0.3])
        sig = daemon._compute_self_signal()
        self.assertIsNotNone(sig)
        # quality / diversity 不出 (no recent)
        self.assertNotIn('self_recent_quality', sig)
        self.assertNotIn('self_thread_diversity', sig)
        # concern 出 (有 active concerns)
        self.assertIn('overall_concern_pressure', sig)
        p = sig['overall_concern_pressure']
        self.assertEqual(p['active_count'], 2)
        self.assertEqual(p['max_severity'], 0.5)

    def test_all_mediocre_thoughts(self):
        """5 个全 mediocre (sal=0.3 + A/D/E + actionable=none) → mediocre_rate=1.0."""
        thoughts = [
            _make_thought(category='A', salience=0.3, actionable='none',
                              thread_id='same_thread', ago_s=i * 10)
            for i in range(5)
        ]
        daemon = _build_daemon_with_thoughts(thoughts=thoughts)
        sig = daemon._compute_self_signal()
        self.assertIsNotNone(sig)
        q = sig['self_recent_quality']
        self.assertEqual(q['mediocre_rate'], 1.0)
        self.assertEqual(q['actionable_rate'], 0.0)
        self.assertEqual(q['avg_salience'], 0.3)
        # diversity: 5 个 thought 全 same_thread → 1 unique / 5
        d = sig['self_thread_diversity']
        self.assertEqual(d['unique_threads'], 1)
        self.assertEqual(d['top_thread_share'], 1.0)

    def test_diverse_high_quality_thoughts(self):
        """5 个 thread + 高 sal + 有 actionable → quality 好 / diversity 高."""
        thoughts = [
            _make_thought(category='C', salience=0.8,
                              actionable='update_concern_severity:x:+0.1',
                              thread_id=f'thread_{i}', ago_s=i * 10)
            for i in range(5)
        ]
        daemon = _build_daemon_with_thoughts(thoughts=thoughts)
        sig = daemon._compute_self_signal()
        q = sig['self_recent_quality']
        self.assertGreaterEqual(q['avg_salience'], 0.7)
        self.assertEqual(q['actionable_rate'], 1.0)
        self.assertEqual(q['mediocre_rate'], 0.0)
        d = sig['self_thread_diversity']
        self.assertEqual(d['unique_threads'], 5)
        self.assertLessEqual(d['top_thread_share'], 0.21)  # 1/5=0.2

    def test_concern_pressure_high(self):
        """concerns severities=[0.9, 0.8, 0.7, 0.4] → high_severity_count=3."""
        daemon = _build_daemon_with_thoughts(
            thoughts=[], concerns_severities=[0.9, 0.8, 0.7, 0.4])
        sig = daemon._compute_self_signal()
        p = sig['overall_concern_pressure']
        self.assertEqual(p['max_severity'], 0.9)
        self.assertEqual(p['active_count'], 4)
        self.assertEqual(p['high_severity_count'], 3)  # ≥0.7

    def test_signals_enabled_gate(self):
        """signals_enabled 全 False → _compute_self_signal 返 None."""
        import jarvis_inner_thought_daemon as mod
        original_cache = dict(mod._PACING_VOCAB_CACHE)
        try:
            mod._PACING_VOCAB_CACHE['data'] = {
                'lookback_n': 5,
                'signals_enabled': {
                    'self_recent_quality': False,
                    'self_thread_diversity': False,
                    'overall_concern_pressure': False,
                },
            }
            mod._PACING_VOCAB_CACHE['checked_at'] = time.time()
            daemon = _build_daemon_with_thoughts(
                thoughts=[_make_thought()], concerns_severities=[0.5])
            sig = daemon._compute_self_signal()
            self.assertIsNone(sig)
        finally:
            mod._PACING_VOCAB_CACHE.update(original_cache)


# ----------------------------------------------------------------------
# Test 3: prompt [YOUR RECENT PACING SIGNAL] 段
# ----------------------------------------------------------------------

class TestPromptPacingBlock(unittest.TestCase):
    def test_prompt_contains_pacing_block_when_signal_present(self):
        """evidence 含 self_pacing_signal → prompt 含 PACING SIGNAL header."""
        thoughts = [_make_thought(salience=0.4, actionable='none')
                       for _ in range(3)]
        daemon = _build_daemon_with_thoughts(
            thoughts=thoughts, concerns_severities=[0.5])
        evidence = daemon._collect_evidence(
            sir_state='active', within_seconds=120)
        prompt_sys, prompt_user = daemon._build_prompt(
            sir_state='active', evidence=evidence, free_categories=list('ABCDE'))
        self.assertIn('PACING SIGNAL', prompt_user)
        # 至少含一类 signal 关键 anchor
        self.assertTrue(
            ('recent_quality' in prompt_user
             or 'thread_diversity' in prompt_user
             or 'concern_pressure' in prompt_user),
            'prompt 应含 ≥1 类 signal block'
        )

    def test_prompt_tone_neutral_no_imperative(self):
        """tone='neutral_fact_only' — prompt 段 NEVER 含 imperative 指令."""
        thoughts = [_make_thought(salience=0.3) for _ in range(3)]
        daemon = _build_daemon_with_thoughts(
            thoughts=thoughts, concerns_severities=[0.5])
        evidence = daemon._collect_evidence(
            sir_state='active', within_seconds=120)
        _, prompt_user = daemon._build_prompt(
            sir_state='active', evidence=evidence, free_categories=list('ABCDE'))
        # 找 PACING SIGNAL header 后 ~600 char 段
        idx = prompt_user.find('PACING SIGNAL')
        if idx < 0:
            self.skipTest('no pacing block in this evidence')
        snippet = prompt_user[idx:idx + 700].lower()
        # 禁 imperative anchor
        forbidden_anchors = [
            'you should slow', 'you should think less', 'you must slow',
            'so slow down', 'so you should', 'imperative:',
        ]
        for anchor in forbidden_anchors:
            self.assertNotIn(anchor, snippet,
                f'pacing block tone 必须中性, 禁含 imperative anchor: {anchor!r}')

    def test_prompt_block_disabled_gate(self):
        """prompt_signal_block.enabled=False → prompt 不含 PACING SIGNAL header."""
        import jarvis_inner_thought_daemon as mod
        original_cache = dict(mod._PACING_VOCAB_CACHE)
        try:
            mod._PACING_VOCAB_CACHE['data'] = {
                'lookback_n': 5,
                'signals_enabled': {
                    'self_recent_quality': True,
                    'self_thread_diversity': True,
                    'overall_concern_pressure': True,
                },
                'prompt_signal_block': {'enabled': False},
                'swm_publish': {'enabled': False},
            }
            mod._PACING_VOCAB_CACHE['checked_at'] = time.time()
            thoughts = [_make_thought() for _ in range(3)]
            daemon = _build_daemon_with_thoughts(
                thoughts=thoughts, concerns_severities=[0.5])
            evidence = daemon._collect_evidence(
                sir_state='active', within_seconds=120)
            _, prompt_user = daemon._build_prompt(
                sir_state='active', evidence=evidence,
                free_categories=list('ABCDE'))
            self.assertNotIn('PACING SIGNAL', prompt_user,
                'prompt_signal_block.enabled=False 应 hide block')
        finally:
            mod._PACING_VOCAB_CACHE.update(original_cache)


# ----------------------------------------------------------------------
# Test 4: SWM publish gate
# ----------------------------------------------------------------------

class TestSwmPublishGate(unittest.TestCase):
    def test_publish_self_signal_calls_event_bus(self):
        """swm_publish.enabled=True → bus.publish('inner_thought_self_signal',...)
        被调."""
        from unittest.mock import patch
        thoughts = [_make_thought() for _ in range(3)]
        daemon = _build_daemon_with_thoughts(
            thoughts=thoughts, concerns_severities=[0.5])
        sig = daemon._compute_self_signal()
        self.assertIsNotNone(sig)

        mock_bus = MagicMock()
        with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
            daemon._publish_self_signal_swm(sig)

        self.assertEqual(mock_bus.publish.call_count, 1)
        call_kwargs = mock_bus.publish.call_args.kwargs
        self.assertEqual(
            call_kwargs.get('etype'), 'inner_thought_self_signal'
        )
        self.assertEqual(call_kwargs.get('source'), 'InnerThoughtDaemon')

    def test_swm_publish_disabled_gate(self):
        """swm_publish.enabled=False → bus.publish 不被调."""
        from unittest.mock import patch
        import jarvis_inner_thought_daemon as mod
        original_cache = dict(mod._PACING_VOCAB_CACHE)
        try:
            mod._PACING_VOCAB_CACHE['data'] = {
                'lookback_n': 5,
                'signals_enabled': {'self_recent_quality': True},
                'swm_publish': {'enabled': False},
            }
            mod._PACING_VOCAB_CACHE['checked_at'] = time.time()

            thoughts = [_make_thought() for _ in range(3)]
            daemon = _build_daemon_with_thoughts(
                thoughts=thoughts, concerns_severities=[0.5])
            sig = daemon._compute_self_signal() or {'dummy': 1}

            mock_bus = MagicMock()
            with patch('jarvis_utils.get_event_bus', return_value=mock_bus):
                daemon._publish_self_signal_swm(sig)
            self.assertEqual(mock_bus.publish.call_count, 0,
                'swm_publish.enabled=False 应不 publish')
        finally:
            mod._PACING_VOCAB_CACHE.update(original_cache)


# ----------------------------------------------------------------------
# Test 5: 准则 6 反硬编码自查 (静态扫描)
# ----------------------------------------------------------------------

class TestAntiHardcodeAudit(unittest.TestCase):
    """static 自查: 不能在 .py 写 if rule, 必须 vocab 驱动."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_REPO, 'jarvis_inner_thought_daemon.py'),
                    'r', encoding='utf-8') as f:
            cls.body = f.read()

    def test_no_hardcoded_pacing_threshold_in_py(self):
        """`.py` NOT contain 'if avg_sal < 0.3' / 'if mediocre_rate > 0.6' 类硬规则."""
        # 检几个明确硬编码反例
        forbidden_patterns = [
            "if avg_sal <",
            "if mediocre_rate >",
            "if top_thread_share >",
            "if max_severity <",
            "next_tick = 300 if",
            "next_tick = 120 if",
        ]
        for pat in forbidden_patterns:
            self.assertNotIn(pat, self.body,
                f'NEVER hardcode pacing if-rule in .py: {pat!r}. '
                f'Use vocab + LLM 自决 instead (准则 6).')

    def test_uses_pacing_vocab_loader(self):
        """daemon 必须用 _load_pacing_config (vocab 驱动)."""
        self.assertIn('_load_pacing_config', self.body)
        self.assertIn('_PACING_VOCAB_PATH', self.body)
        self.assertIn('inner_thought_pacing_vocab.json', self.body)

    def test_prompt_tone_neutral_anchor_in_default_config(self):
        """default config + vocab JSON tone 必须 neutral_fact_only."""
        import jarvis_inner_thought_daemon as mod
        default_tone = (mod._PACING_DEFAULT_CONFIG
                            .get('prompt_signal_block', {})
                            .get('tone', ''))
        self.assertEqual(default_tone, 'neutral_fact_only',
            'default config tone 必须 neutral_fact_only (准则 6 反 prescriptive).')


if __name__ == '__main__':
    unittest.main(verbosity=2)
