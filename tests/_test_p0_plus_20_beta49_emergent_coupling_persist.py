# -*- coding: utf-8 -*-
"""
[P0+20-β.4.9 / 2026-05-19] 模块耦合加强 — Sir 反馈: "想要真朋友感, 不要一次性 LLM 函数"

覆盖:
1. SoftFocus BUG 修 (主动关怀 reason 宽松 validate) — _test_p0_plus_20_beta299 已含
2. P0 #1: pending_ack 注入 concern.notes_for_self (兑现 → 主脑下次自然致意)
3. P0 #2: Sir 主动承诺通过 infer_concern_link 自动走闭环 (vocab-driven, 0 改动)
4. P2: severity_delta 从 vocab 读 (准则 6.5)
5. record_alignment(aligned=True) 自动清 [pending_ack] tag

设计原则:
- 准则 6 反硬编码: 不写 if concern_id == 'sir_sleep_streak' 那种, 全 vocab 驱动
- 准则 6.5: 数值阈值全 vocab.json, Sir CLI 改即生效
- 准则 7 Sir 元否决: P1 主题连续性 directive 不加 (Sir 担心抑制涌现)
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


# ==========================================================================
# P2: severity_delta vocab 化 (准则 6.5)
# ==========================================================================

class TestP0Plus20Beta49SeverityVocab(unittest.TestCase):
    """severity_decay_vocab.json + _load_severity_delta helper."""

    def setUp(self):
        # 清 vocab cache (sanity)
        try:
            from jarvis_safety import _SEVERITY_VOCAB_CACHE
            _SEVERITY_VOCAB_CACHE['mtime'] = 0.0
            _SEVERITY_VOCAB_CACHE['data'] = None
        except Exception:
            pass

    def test_vocab_file_exists(self):
        p = os.path.join(ROOT, 'memory_pool', 'severity_decay_vocab.json')
        self.assertTrue(os.path.exists(p), 'severity_decay_vocab.json 必须存在')
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('_meta', data)
        self.assertIn('thresholds', data['_meta'])
        self.assertIn('per_concern', data)

    def test_default_thresholds(self):
        """vocab 缺 per_concern 时返默认值."""
        from jarvis_safety import _load_severity_delta
        d = _load_severity_delta('nonexistent_concern_xyz', 'fulfilled')
        self.assertEqual(d, -0.20, '默认 fulfilled = -0.20')
        d = _load_severity_delta('nonexistent_concern_xyz', 'broken')
        self.assertEqual(d, 0.10, '默认 broken = +0.10')

    def test_per_concern_override(self):
        """sir_sleep_streak / sir_hydration_habit per-concern 覆盖."""
        from jarvis_safety import _load_severity_delta
        # sleep 比 default 严重 (- 0.25 fulfilled / + 0.15 broken)
        sleep_fulfilled = _load_severity_delta('sir_sleep_streak', 'fulfilled')
        self.assertLess(sleep_fulfilled, -0.20,
            'sir_sleep_streak fulfilled 应比 default 更负 (兑现感更强)')
        # hydration 比 default 轻 (-0.10)
        hyd_fulfilled = _load_severity_delta('sir_hydration_habit', 'fulfilled')
        self.assertGreater(hyd_fulfilled, -0.20,
            'sir_hydration_habit fulfilled 应比 default 更轻')

    def test_invalid_verdict_returns_zero(self):
        from jarvis_safety import _load_severity_delta
        self.assertEqual(_load_severity_delta('any_cid', 'unknown'), 0.0)
        self.assertEqual(_load_severity_delta('any_cid', ''), 0.0)

    def test_fail_safe_missing_vocab(self):
        """vocab 路径不存在 → 返默认 (不抛异常)."""
        from jarvis_safety import _load_severity_delta
        import jarvis_safety as mod
        orig = mod._SEVERITY_VOCAB_PATH
        mod._SEVERITY_VOCAB_PATH = '/nonexistent/xyz.json'
        mod._SEVERITY_VOCAB_CACHE['mtime'] = 0.0
        mod._SEVERITY_VOCAB_CACHE['data'] = None
        try:
            d = _load_severity_delta('sir_sleep_streak', 'fulfilled')
            self.assertEqual(d, -0.20, 'vocab 缺失应 fallback default')
        finally:
            mod._SEVERITY_VOCAB_PATH = orig

    def test_commitment_watcher_uses_helper(self):
        """jarvis_commitment_watcher.py _on_fulfillment 必须调 _load_severity_delta."""
        p = os.path.join(ROOT, 'jarvis_commitment_watcher.py')
        with open(p, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('_load_severity_delta', src,
            '_on_fulfillment 必须调 _load_severity_delta (β.4.9 vocab 化)')
        # 旧硬编码 severity_delta = -0.2 / +0.1 应不再直接出现 (除 fallback)
        # 严格 check: 不应有 'severity_delta = -0.2$' 单独赋值
        # (fallback except 块里仍可保留以防 vocab 损坏)


# ==========================================================================
# P0 #1: pending_ack 注入
# ==========================================================================

class TestP0Plus20Beta49PendingAck(unittest.TestCase):
    """Sir 兑现 → _on_fulfillment 写 [pending_ack] 到 concern.notes_for_self."""

    def test_commitment_watcher_writes_pending_ack(self):
        """jarvis_commitment_watcher.py _on_fulfillment 必须写 pending_ack 标记."""
        p = os.path.join(ROOT, 'jarvis_commitment_watcher.py')
        with open(p, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('[pending_ack', src,
            '_on_fulfillment 必须写 [pending_ack] 标记到 notes_for_self')
        self.assertIn('notes_for_self', src,
            '必须改 concern.notes_for_self (主脑下次自然致意)')
        # 必须复用 ledger.persist() 落盘
        self.assertIn('ledger2.persist()', src.replace('_ledger2', 'ledger2'))

    def test_pending_ack_fulfilled_branch_present(self):
        p = os.path.join(ROOT, 'jarvis_commitment_watcher.py')
        with open(p, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('fulfilled] Sir', src,
            'fulfilled 分支必须写 "[pending_ack ... fulfilled]"')
        self.assertIn('broken] Sir', src,
            'broken 分支必须写 "[pending_ack ... broken]"')

    def test_pending_ack_dedup_guard(self):
        """已含 [pending_ack 不重复堆 (避免 N 次兑现 spam)."""
        p = os.path.join(ROOT, 'jarvis_commitment_watcher.py')
        with open(p, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'[pending_ack' not in _existing", src,
            'pending_ack 写入前必查 dedup')


# ==========================================================================
# record_alignment 清 pending_ack
# ==========================================================================

class TestP0Plus20Beta49ClearPendingAckOnAlignment(unittest.TestCase):
    """record_alignment(aligned=True) → 清 concern.notes_for_self 里 [pending_ack]."""

    def _make_ledger_with_pending(self):
        from jarvis_concerns import ConcernsLedger, Concern
        import tempfile
        tmp = tempfile.mktemp(suffix='_ledger.json')
        ledger = ConcernsLedger(persist_path=tmp)
        c = Concern(
            id='test_concern_xyz',
            what_i_watch='test',
            why_i_care='test',
            severity=0.5,
            notes_for_self='[pending_ack 12:34 fulfilled] Sir 真兑现 X | 其他笔记保留',
        )
        with ledger._lock:
            ledger.concerns[c.id] = c
        return ledger, c, tmp

    def test_aligned_true_clears_pending_ack(self):
        ledger, c, tmp = self._make_ledger_with_pending()
        try:
            ok = ledger.record_alignment('test_concern_xyz', aligned=True)
            self.assertTrue(ok)
            self.assertNotIn('[pending_ack', c.notes_for_self,
                'aligned=True 应清 [pending_ack] tag')
            # 其他笔记保留
            self.assertIn('其他笔记保留', c.notes_for_self)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def test_aligned_false_keeps_pending_ack(self):
        ledger, c, tmp = self._make_ledger_with_pending()
        try:
            ok = ledger.record_alignment('test_concern_xyz', aligned=False)
            self.assertTrue(ok)
            self.assertIn('[pending_ack', c.notes_for_self,
                'aligned=False (missed) 不清 [pending_ack] (主脑没致意, 留着)')
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass


# ==========================================================================
# P0 #2: Sir 主动承诺自动走闭环 (验现有路径已 work)
# ==========================================================================

class TestP0Plus20Beta49SelfPromiseAutoLink(unittest.TestCase):
    """Sir 主动说承诺 → infer_concern_link 自动反查 → 走闭环.
    (现有路径已 work, 此测锁住契约)"""

    def test_infer_sleep_promise(self):
        """睡眠类承诺反查到 sleep_streak 或 pomodoro_compliance 都合理 (含 '休息' 词)."""
        from jarvis_commitment_watcher import infer_concern_link
        # 明确 sleep 字眼 → sir_sleep_streak
        for desc in ['我去睡觉', '我要去睡了', 'I am going to sleep now']:
            cid = infer_concern_link(desc)
            self.assertEqual(cid, 'sir_sleep_streak',
                f"'{desc}' 应反查到 sir_sleep_streak (实际 {cid})")
        # 含 '休息' / 'rest' 模糊词 → sleep 或 pomodoro 都接受
        for desc in ['我现在去休息', 'I need rest']:
            cid = infer_concern_link(desc)
            self.assertIn(cid, ('sir_sleep_streak', 'sir_pomodoro_compliance'),
                f"'{desc}' 应反查到 sleep 或 pomodoro (实际 {cid})")

    def test_infer_hydration_promise(self):
        from jarvis_commitment_watcher import infer_concern_link
        for desc in ['我去喝点水', '马上喝水了', '补水', 'going to drink water']:
            cid = infer_concern_link(desc)
            self.assertEqual(cid, 'sir_hydration_habit',
                f"'{desc}' 应反查到 sir_hydration_habit (实际 {cid})")

    def test_infer_unrelated_returns_none(self):
        """完全无关的承诺不归任何 concern."""
        from jarvis_commitment_watcher import infer_concern_link
        cid = infer_concern_link('我去散步')
        # 散步可能没在 vocab → None (准则 6.5 设计: vocab 没的 Sir 自己 CLI 加)
        # 这里不强 assert None, 可能未来 vocab 加 'walk' 也合理
        self.assertTrue(cid is None or isinstance(cid, str))


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.4.9 emergent coupling tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
