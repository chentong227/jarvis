# -*- coding: utf-8 -*-
"""[P5-IntegrityWatcher / 2026-05-21 14:15] L4.5 Active Verify+Retry verify.

Sir 14:11 真意: "wachter 负责贾维斯所有行为(除调 tool)是否成功的审查机构,
植入言出必行层级中. 主动重试, 真做不到 handoff Sir 手动."

Cover:
  A. detect_claims_in_reply — 8 claim type 检测
  B. Claim dataclass + IntegrityWatcherStore persist + load
  C. extract_time_anchor / extract_intent_excerpt
  D. IntegrityWatcher.watch_claim 加入 store
  E. _process_one — verify ok 首次 → STATUS_VERIFIED
  F. _process_one — verify fail + retry ok → 等下轮 verify (RETRY 阶段)
  G. _process_one — verify fail + retry fail (cannot keyword) → STATUS_HANDOFF_SIR
  H. _process_one — fresh_buffer 跳过 (claim 太新)
  I. cannot_recover detect — same error N×
  J. render_report_block — recovered / handoff / no_tool
  K. central_nerve init + chat_bypass static check
  L. directive integrity_watcher_report_use registered (priority 11)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. detect_claims_in_reply
# ============================================================

class TestA_DetectClaims(unittest.TestCase):
    def test_reminder_en(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("Done, Sir. I've set the reminder for 12:00.")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['claim_type'], 'reminder')
        self.assertIn('reminder', hits[0]['target'].lower())

    def test_reminder_zh(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("好的, 已设好提醒了, Sir.")
        types = [h['claim_type'] for h in hits]
        self.assertIn('reminder', types)

    def test_memory_en(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("I'll remember that, Sir.")
        types = [h['claim_type'] for h in hits]
        self.assertIn('memory', types)

    def test_memory_zh(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("我已记住了, Sir.")
        types = [h['claim_type'] for h in hits]
        self.assertIn('memory', types)

    def test_milestone_zh(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("好的, 这一刻我永远记得.")
        types = [h['claim_type'] for h in hits]
        self.assertIn('milestone', types)

    def test_profile_en(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("I've updated your profile, Sir.")
        types = [h['claim_type'] for h in hits]
        self.assertIn('profile', types)

    def test_concern_zh(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("已记录了喝水进度.")
        types = [h['claim_type'] for h in hits]
        self.assertIn('concern', types)

    def test_no_claim_in_chitchat(self):
        from jarvis_integrity_watcher import detect_claims_in_reply
        hits = detect_claims_in_reply("Hello, Sir. How may I help?")
        self.assertEqual(len(hits), 0)


# ============================================================
# B. Store + Claim dataclass
# ============================================================

class TestB_Store(unittest.TestCase):
    def setUp(self):
        from jarvis_integrity_watcher import reset_default_watcher_for_tests
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'iw.json')
        reset_default_watcher_for_tests()

    def tearDown(self):
        try:
            if os.path.exists(self._path):
                os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_dataclass_persist_load(self):
        from jarvis_integrity_watcher import (
            Claim, IntegrityWatcherStore, STATUS_VERIFIED
        )
        store = IntegrityWatcherStore(path=self._path)
        c = Claim(
            id='', claim_type='reminder',
            extracted_action="I've set the reminder",
            extracted_target='reminder',
            extracted_meta={'time_anchor': '12:00'},
            captured_turn_id='turn_test',
        )
        cid = store.add(c)
        self.assertTrue(cid)
        self.assertTrue(os.path.exists(self._path))

        # reload
        store2 = IntegrityWatcherStore(path=self._path)
        items = store2.all_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].claim_type, 'reminder')
        self.assertEqual(items[0].extracted_meta.get('time_anchor'), '12:00')


# ============================================================
# C. extract helpers
# ============================================================

class TestC_Extract(unittest.TestCase):
    def test_time_anchor_hhmm(self):
        from jarvis_integrity_watcher import extract_time_anchor
        self.assertEqual(extract_time_anchor("set reminder for 12:00"), '12:00')
        self.assertEqual(extract_time_anchor("at 7:30 tomorrow"), '07:30')

    def test_time_anchor_zh(self):
        from jarvis_integrity_watcher import extract_time_anchor
        self.assertEqual(extract_time_anchor("11 点叫我"), '11:00')
        self.assertEqual(extract_time_anchor("11 点 30 分"), '11:30')

    def test_duration(self):
        from jarvis_integrity_watcher import extract_time_anchor
        self.assertEqual(extract_time_anchor("in 30 minutes "), '30分钟后')
        self.assertEqual(extract_time_anchor("30 分钟内提醒"), '30分钟后')


# ============================================================
# D. watch_claim
# ============================================================

class TestD_WatchClaim(unittest.TestCase):
    def setUp(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'iw.json')
        self._store = IntegrityWatcherStore(path=self._path)
        self._watcher = IntegrityWatcher(nerve=None, store=self._store)

    def tearDown(self):
        try:
            os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_watch_extracts_claims(self):
        cids = self._watcher.watch_claim(
            "I've set the reminder for 12:00, Sir.",
            turn_id='turn_test'
        )
        self.assertGreater(len(cids), 0)
        items = self._store.all_items()
        self.assertEqual(len(items), len(cids))
        self.assertEqual(items[0].claim_type, 'reminder')
        self.assertEqual(items[0].extracted_meta.get('time_anchor'), '12:00')

    def test_watch_no_claims_chitchat(self):
        cids = self._watcher.watch_claim("Hello, Sir.", turn_id='turn_test')
        self.assertEqual(len(cids), 0)


# ============================================================
# E/F/G. _process_one — verify / retry / handoff
# ============================================================

class TestE_ProcessVerifyOk(unittest.TestCase):
    """verify ok 首次 → STATUS_VERIFIED."""

    def setUp(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore, Claim, STATUS_WATCHING
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'iw.json')
        self._store = IntegrityWatcherStore(path=self._path)
        self._mock_verify = MagicMock(return_value=(True, {'reminder_id': 'r123'}, ''))
        self._watcher = IntegrityWatcher(
            nerve=None, store=self._store,
            verifiers={'reminder': self._mock_verify},
            retriers={'reminder': MagicMock()},
            fresh_buffer_s=0.0,
        )
        self._claim = Claim(
            id='cid_test', claim_type='reminder',
            extracted_action="I've set", extracted_target='reminder',
            captured_at=time.time() - 10,  # 10s old, past fresh_buffer
            captured_turn_id='turn_test',
            status=STATUS_WATCHING,
        )
        self._store.add(self._claim)

    def tearDown(self):
        try:
            os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_verify_ok_marks_verified(self):
        from jarvis_integrity_watcher import STATUS_VERIFIED
        self._watcher._process_one(self._claim)
        self.assertEqual(self._claim.status, STATUS_VERIFIED)
        self.assertEqual(self._claim.final_evidence.get('reminder_id'), 'r123')


class TestF_ProcessVerifyFailRetryOk(unittest.TestCase):
    """verify fail + retry ok → 等下轮 verify (still RETRYING)."""

    def setUp(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore, Claim, STATUS_WATCHING
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'iw.json')
        self._store = IntegrityWatcherStore(path=self._path)
        self._mock_verify = MagicMock(return_value=(False, {}, 'reminder not found'))
        self._mock_retry = MagicMock(return_value=(True, {'reminder_id': 'r999'}, ''))
        self._watcher = IntegrityWatcher(
            nerve=None, store=self._store,
            verifiers={'reminder': self._mock_verify},
            retriers={'reminder': self._mock_retry},
            fresh_buffer_s=0.0,
        )
        self._claim = Claim(
            id='cid_retry', claim_type='reminder',
            extracted_action="I've set", extracted_target='reminder',
            captured_at=time.time() - 10,
            captured_turn_id='turn_test',
            status=STATUS_WATCHING,
        )
        self._store.add(self._claim)

    def tearDown(self):
        try:
            os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_retry_runs_then_backoff(self):
        from jarvis_integrity_watcher import STATUS_RETRYING
        self._watcher._process_one(self._claim)
        # verify fail → retry called
        self._mock_retry.assert_called_once()
        self.assertEqual(self._claim.status, STATUS_RETRYING)
        self.assertEqual(self._claim.retries, 1)
        self.assertGreater(self._claim.next_retry_ts, time.time())  # in backoff


class TestG_HandoffSir(unittest.TestCase):
    """retry fail with cannot keyword → STATUS_HANDOFF_SIR."""

    def setUp(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore, Claim, STATUS_WATCHING
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'iw.json')
        self._store = IntegrityWatcherStore(path=self._path)
        # cannot keyword 'no method'
        self._mock_verify = MagicMock(return_value=(False, {}, 'no method add_reminder'))
        self._mock_retry = MagicMock(return_value=(False, {}, 'no method add_reminder'))
        self._watcher = IntegrityWatcher(
            nerve=None, store=self._store,
            verifiers={'reminder': self._mock_verify},
            retriers={'reminder': self._mock_retry},
            fresh_buffer_s=0.0,
        )
        self._claim = Claim(
            id='cid_handoff', claim_type='reminder',
            extracted_action="I've set", extracted_target='reminder',
            captured_at=time.time() - 10,
            captured_turn_id='turn_test',
            status=STATUS_WATCHING,
        )
        self._store.add(self._claim)

    def tearDown(self):
        try:
            os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_cannot_keyword_handoff(self):
        from jarvis_integrity_watcher import STATUS_HANDOFF_SIR
        self._watcher._process_one(self._claim)
        # Cannot keyword detected after first verify fail (in verify_history) AND retry fail
        # Should mark HANDOFF_SIR
        self.assertEqual(self._claim.status, STATUS_HANDOFF_SIR)
        self.assertIn('cannot', self._claim.final_error.lower())


# ============================================================
# H. fresh_buffer skip
# ============================================================

class TestH_FreshBufferSkip(unittest.TestCase):
    def test_too_fresh_skipped(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore, Claim, STATUS_WATCHING
        )
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'iw.json')
        store = IntegrityWatcherStore(path=path)
        mock_verify = MagicMock()
        watcher = IntegrityWatcher(
            nerve=None, store=store,
            verifiers={'reminder': mock_verify},
            retriers={'reminder': MagicMock()},
            fresh_buffer_s=10.0,  # 10s buffer
        )
        c = Claim(id='cid_fresh', claim_type='reminder',
                   extracted_action='X', extracted_target='X',
                   captured_at=time.time(),  # just now
                   status=STATUS_WATCHING)
        store.add(c)
        watcher._process_one(c)
        # Verifier 不该被调
        mock_verify.assert_not_called()
        self.assertEqual(c.status, STATUS_WATCHING)
        try:
            os.remove(path); os.rmdir(tmpdir)
        except Exception:
            pass


# ============================================================
# I. cannot_recover detect — same error N times
# ============================================================

class TestI_CannotRecoverDetect(unittest.TestCase):
    def test_same_error_three_times(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore, Claim
        )
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'iw.json')
        store = IntegrityWatcherStore(path=path)
        watcher = IntegrityWatcher(nerve=None, store=store, fresh_buffer_s=0.0,
                                    handoff_same_error_n=3)
        c = Claim(id='c1', claim_type='reminder',
                   extracted_action='X', extracted_target='X')
        # 3 同 error retry history
        c.verify_history = [
            {'phase': 'retry', 'ts': time.time() - 30, 'ok': False, 'error': 'DB locked'},
            {'phase': 'retry', 'ts': time.time() - 20, 'ok': False, 'error': 'DB locked'},
            {'phase': 'retry', 'ts': time.time() - 10, 'ok': False, 'error': 'DB locked'},
        ]
        reason = watcher._detect_cannot_recover(c)
        self.assertIsNotNone(reason)
        self.assertIn('DB locked', reason)
        try:
            os.remove(path); os.rmdir(tmpdir)
        except Exception:
            pass


# ============================================================
# J. render_report_block
# ============================================================

class TestJ_RenderBlock(unittest.TestCase):
    def test_recovered_event_renders(self):
        from jarvis_integrity_watcher import render_report_block
        fake = [{
            'type': 'integrity_recovered',
            '_age_s': 30,
            'metadata': {
                'claim_id': 'c1', 'claim_type': 'reminder',
                'extracted_action': "I've set", 'extracted_target': 'reminder',
                'final_evidence': {'reminder_id': 'r123'},
                'retries': 1, 'age_s': 30,
            },
        }]
        mock_bus = MagicMock()
        mock_bus.recent_events.return_value = fake
        with patch('jarvis_utils.get_event_bus') as _g:
            _g.return_value = mock_bus
            block = render_report_block(within_seconds=600.0)
            self.assertIn('INTEGRITY WATCHER REPORT', block)
            self.assertIn('已自动补救', block)
            self.assertIn('reminder', block)

    def test_handoff_event_renders(self):
        from jarvis_integrity_watcher import render_report_block
        fake = [{
            'type': 'integrity_handoff_sir',
            '_age_s': 60,
            'metadata': {
                'claim_id': 'c2', 'claim_type': 'reminder',
                'extracted_action': "I've set", 'extracted_target': 'reminder',
                'cannot_reason': 'no add_reminder method',
                'retries': 3, 'age_s': 60,
            },
        }]
        mock_bus = MagicMock()
        mock_bus.recent_events.return_value = fake
        with patch('jarvis_utils.get_event_bus') as _g:
            _g.return_value = mock_bus
            block = render_report_block(within_seconds=600.0)
            self.assertIn('Jarvis 做不到', block)
            self.assertIn('actionable', block.lower())


# ============================================================
# K. central_nerve init + chat_bypass static check
# ============================================================

class TestK_StaticIntegration(unittest.TestCase):
    def test_central_nerve_init_integrity_watcher(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('IntegrityWatcher', src)
        self.assertIn('self.integrity_watcher', src)
        self.assertIn('integrity_watcher.start()', src)
        self.assertIn('render_report_block', src)
        self.assertIn('INTEGRITY WATCHER REPORT', src)

    def test_chat_bypass_calls_watch_claim_async(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('integrity_watcher', src)
        self.assertIn('watch_claim_async', src)


# ============================================================
# L. directive
# ============================================================

class TestL_Directive(unittest.TestCase):
    def test_directive_registered(self):
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        target = reg.directives.get('integrity_watcher_report_use')
        self.assertIsNotNone(target)
        self.assertEqual(target.priority, 11)
        self.assertIn('INTEGRITY WATCHER REPORT', target.text)
        self.assertIn('recovered', target.text)
        self.assertIn('handoff_sir', target.text)
        self.assertIn('Sir 14:11', target.text)


# ============================================================
# M. 3-Layer Waterfall (vocab + keyword gate + LLM)
# ============================================================

class TestM_VocabLoader(unittest.TestCase):
    """vocab json loader + mtime cache."""

    def test_load_vocab_compiles_patterns(self):
        from jarvis_integrity_watcher import (
            _get_compiled_detectors, reset_vocab_cache, CLAIM_VOCAB_PATH
        )
        reset_vocab_cache()
        detectors = _get_compiled_detectors()
        self.assertGreater(len(detectors), 0)
        types = [d[0] for d in detectors]
        # Should have at least these from seed JSON
        for ct in ('reminder', 'commitment', 'memory', 'milestone'):
            self.assertIn(ct, types)

    def test_vocab_detection_works(self):
        from jarvis_integrity_watcher import (
            detect_claims_via_regex, reset_vocab_cache
        )
        reset_vocab_cache()
        hits = detect_claims_via_regex("I've set the reminder for 7:00.")
        self.assertGreater(len(hits), 0)
        # source must be vocab_layer1 (from json) not unknown
        self.assertEqual(hits[0]['source'], 'vocab_layer1')

    def test_vocab_fallback_when_file_missing(self):
        """File missing → fallback hardcoded detectors."""
        from jarvis_integrity_watcher import (
            _get_compiled_detectors, reset_vocab_cache, _FALLBACK_DETECTORS,
            CLAIM_VOCAB_PATH
        )
        # If vocab file exists, this just confirms _FALLBACK_DETECTORS is non-empty
        self.assertGreater(len(_FALLBACK_DETECTORS), 0)


class TestN_SuspiciousKeywordGate(unittest.TestCase):
    """Layer 2 — suspicious keyword gate."""

    def test_kw_pattern_compiles(self):
        from jarvis_integrity_watcher import (
            _get_compiled_kw_pattern, reset_vocab_cache
        )
        reset_vocab_cache()
        en_pat, zh_pat = _get_compiled_kw_pattern()
        self.assertIsNotNone(en_pat)
        self.assertIsNotNone(zh_pat)

    def test_has_suspicious_keyword(self):
        from jarvis_integrity_watcher import has_suspicious_keyword
        # 含 'set' EN
        self.assertTrue(has_suspicious_keyword("I have set the timer."))
        # 含 '记住' ZH
        self.assertTrue(has_suspicious_keyword("Sir 我记住了."))
        # 不含
        self.assertFalse(has_suspicious_keyword("Hello, Sir."))
        self.assertFalse(has_suspicious_keyword("How may I help?"))


class TestO_WaterfallWatchClaim(unittest.TestCase):
    """watch_claim 3 层 waterfall 行为."""

    def setUp(self):
        from jarvis_integrity_watcher import (
            IntegrityWatcher, IntegrityWatcherStore, reset_vocab_cache
        )
        self._tmpdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tmpdir, 'iw.json')
        self._store = IntegrityWatcherStore(path=self._path)
        self._watcher = IntegrityWatcher(nerve=None, store=self._store)
        reset_vocab_cache()

    def tearDown(self):
        try:
            os.remove(self._path)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_layer1_vocab_hit(self):
        """Layer 1 vocab 命中 → 立即加 watch."""
        cids = self._watcher.watch_claim("I've set the reminder for 7:00.", turn_id='t1')
        self.assertGreater(len(cids), 0)
        items = self._store.all_items()
        # source 应为 vocab_layer1
        self.assertEqual(items[0].extracted_meta.get('detection_source'), 'vocab_layer1')

    def test_layer2_skip_chitchat(self):
        """Layer 1 miss + Layer 2 keyword 不命中 → 跳过 LLM."""
        # Patch LLM judge to track if called
        from jarvis_integrity_watcher import get_default_llm_judge
        judge = get_default_llm_judge()
        with patch.object(judge, 'judge_and_capture') as mock_judge:
            cids = self._watcher.watch_claim("Hello Sir how are you", turn_id='t1')
            self.assertEqual(len(cids), 0)
            # LLM should NOT be called (no suspicious kw)
            mock_judge.assert_not_called()

    def test_layer3_llm_triggered_when_kw_hit_no_vocab(self):
        """Layer 1 miss + Layer 2 keyword 命中 + LLM 可用 → 触发 LLM async."""
        from jarvis_integrity_watcher import get_default_llm_judge
        judge = get_default_llm_judge()
        # mock available + judge_and_capture
        with patch.object(judge, 'is_available', return_value=True), \
             patch.object(judge, 'judge_and_capture') as mock_judge:
            # 'I have logged that to my system' contains 'logged' (kw)
            # but doesn't fit vocab pattern (no claim_type 'log')
            self._watcher.watch_claim(
                "Hmm, I have logged that observation to my system.",
                turn_id='t1'
            )
            # LLM 应被 fire-and-forget 启动 (跑 thread)
            # 等 thread 调一下
            time.sleep(0.1)
            self.assertTrue(mock_judge.called)


# ============================================================
# P. LLM Judge class
# ============================================================

class TestP_LlmJudge(unittest.TestCase):
    def test_unavailable_without_key_router(self):
        from jarvis_integrity_watcher import _LlmClaimJudge
        j = _LlmClaimJudge(key_router=None)
        self.assertFalse(j.is_available())

    def test_attach_key_router_makes_available(self):
        from jarvis_integrity_watcher import _LlmClaimJudge
        j = _LlmClaimJudge(key_router=None)
        self.assertFalse(j.is_available())
        j.attach_key_router(MagicMock())
        self.assertTrue(j.is_available())

    def test_judge_and_capture_no_call_when_unavailable(self):
        from jarvis_integrity_watcher import _LlmClaimJudge, IntegrityWatcher
        j = _LlmClaimJudge(key_router=None)
        watcher = MagicMock()
        # should be no-op without key
        j.judge_and_capture(watcher, "I've set a reminder", "t1", None)
        watcher._add_hits_to_store.assert_not_called()


if __name__ == '__main__':
    unittest.main()
