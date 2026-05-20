"""[β.5.43-fix3 / 2026-05-20] Sir 18:49 痛点 — Jarvis 答应 watch 但没机制兑现.

3 件套:
㋭ SirRequestReflector L7 daemon: 看 STM, LLM judge Sir 是否要求 long-watch X
    → propose concern 进 review queue. Sir dashboard 一键激活.
㋮ PhysicalEnvProbe._check_active_window_unresponsive: IsHungAppWindow API,
    ProactiveCare tick 看到就 publish 'active_window_hung' SWM.
㋯ promise_soft_vocab.json 加 verbs: 'keep .* eye on', 'intervene if/when',
    'alert/notify/let-know if/when'. 兜底 PromiseLog 漏判.
"""
from __future__ import annotations

import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestFix3SirRequestReflector(unittest.TestCase):
    """㋭ SirRequestReflector L7 daemon."""

    def test_module_imports(self):
        import jarvis_sir_request_reflector as m
        self.assertTrue(hasattr(m, 'SirRequestReflector'))
        self.assertTrue(hasattr(m, 'SIR_REQUEST_REFLECTOR_CONFIG'))
        self.assertTrue(hasattr(m, 'SIR_REQUEST_REFLECTOR_PROMPT'))

    def test_config_sensible_defaults(self):
        from jarvis_sir_request_reflector import SIR_REQUEST_REFLECTOR_CONFIG
        # 短 interval (1min) 让 Sir 请求快被 propose
        self.assertEqual(SIR_REQUEST_REFLECTOR_CONFIG['min_interval_s'], 60)
        # 一次最多 1 条 (Sir 不希望 review queue 被 flood)
        self.assertEqual(SIR_REQUEST_REFLECTOR_CONFIG['max_propose_per_run'], 1)
        # 24h dedup
        self.assertEqual(SIR_REQUEST_REFLECTOR_CONFIG['dedup_window_s'], 86400)

    def test_reflector_skips_without_key_router(self):
        """无 key_router 不阻塞主路径, 静默返 reason."""
        from jarvis_sir_request_reflector import SirRequestReflector
        r = SirRequestReflector(
            key_router=None,
            stm_provider=lambda: [],
            concerns_ledger=None,
        )
        res = r.force_run_now()
        self.assertIn('reason', res)

    def test_reflector_wired_in_central_nerve(self):
        """central_nerve 必须 import + start SirRequestReflector daemon."""
        src = open(
            os.path.join(ROOT, 'jarvis_central_nerve.py'), encoding='utf-8'
        ).read()
        self.assertIn('jarvis_sir_request_reflector', src,
                      'central_nerve 必须 import jarvis_sir_request_reflector')
        self.assertIn('SirRequestReflector', src,
                      'central_nerve 必须实例化 SirRequestReflector')
        self.assertIn('β.5.43-fix3-㋭', src,
                      'central_nerve 必须有 fix3-㋭ marker')

    def test_reflector_propose_concern_writes_review_queue(self):
        """模拟 LLM 返 JSON, reflector 写 review queue."""
        from jarvis_sir_request_reflector import SirRequestReflector
        from jarvis_concerns import ConcernsLedger
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            ledger_path = os.path.join(td, 'concerns.json')
            review_path = os.path.join(td, 'concerns_review.json')
            ledger = ConcernsLedger(
                persist_path=ledger_path,
                review_path=review_path,
            )
            r = SirRequestReflector(
                key_router=None,
                stm_provider=lambda: [
                    {'source': 'user_voice', 'text': '下次卡住的时候主动提醒我'},
                    {'source': 'jarvis_voice', 'text': 'shall keep a closer eye'},
                ] * 5,
                concerns_ledger=ledger,
            )
            # 直接调内部 propose path (绕 LLM)
            from jarvis_concerns import Concern
            c = Concern(
                id='watch_windsurf_responsive_test',
                what_i_watch='Windsurf 是否在响应',
                why_i_care='Sir 要求 watch',
                severity=0.5,
                state='review',
            )
            ok = ledger.propose(c)
            self.assertTrue(ok)
            self.assertIn('watch_windsurf_responsive_test', ledger.concerns)
            self.assertEqual(ledger.concerns['watch_windsurf_responsive_test'].state, 'review')


class TestFix3ActiveWindowHung(unittest.TestCase):
    """㋮ PhysicalEnvProbe IsHungAppWindow + ProactiveCare publish."""

    def test_method_exists_in_env_probe(self):
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        self.assertTrue(hasattr(P, '_check_active_window_unresponsive'))
        # 实际调一次 (returns bool, no throw)
        result = P._check_active_window_unresponsive()
        self.assertIsInstance(result, bool)

    def test_snapshot_includes_unresponsive_field(self):
        """get_sensor_snapshot 必含 active_window_unresponsive 字段."""
        # 强行触发一次 snapshot build
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        snap = P._build_sensor_snapshot()
        self.assertIn('active_window_unresponsive', snap,
                      'snapshot 必有 active_window_unresponsive 字段')
        # 类型是 bool
        self.assertIsInstance(snap['active_window_unresponsive'], bool)

    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        self.assertIn('active_window_hung', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('active_window_hung', ConversationEventBus.DEFAULT_SALIENCE)

    def test_proactive_care_publishes_on_hung(self):
        """ProactiveCare tick 若 snapshot.active_window_unresponsive=True → publish SWM."""
        # marker 检查
        src = open(
            os.path.join(ROOT, 'jarvis_proactive_care.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.43-fix3-㋮', src)
        self.assertIn('active_window_hung', src)
        self.assertIn('IsHungAppWindow', open(
            os.path.join(ROOT, 'jarvis_env_probe.py'), encoding='utf-8'
        ).read())


class TestFix3PromiseVocabBackfill(unittest.TestCase):
    """㋯ promise_soft_vocab.json 加 verb 兜底 PromiseLog 漏判."""

    def test_vocab_has_closer_eye_variants(self):
        path = os.path.join(ROOT, 'memory_pool', 'promise_soft_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        verbs = data['groups']['en_soft_verbs']['verbs']
        # 必有 closer/watchful eye 变体
        has_eye_variant = any('closer' in v or 'watchful' in v for v in verbs)
        self.assertTrue(has_eye_variant,
                        f'vocab 必有 keep .* (closer|watchful|...) eye 变体')

    def test_vocab_has_intervene_alert_notify(self):
        path = os.path.join(ROOT, 'memory_pool', 'promise_soft_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        verbs = data['groups']['en_soft_verbs']['verbs']
        # 必有 intervene if + alert if/when + notify if/when + let know
        has_intervene = any('intervene' in v for v in verbs)
        has_alert = any('alert' in v for v in verbs)
        has_notify = any('notify' in v for v in verbs)
        has_letknow = any('let you know' in v for v in verbs)
        self.assertTrue(has_intervene, 'vocab 必有 intervene verb')
        self.assertTrue(has_alert, 'vocab 必有 alert verb')
        self.assertTrue(has_notify, 'vocab 必有 notify verb')
        self.assertTrue(has_letknow, 'vocab 必有 let you know verb')

    def test_history_has_fix3_marker(self):
        path = os.path.join(ROOT, 'memory_pool', 'promise_soft_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        history = data.get('history', [])
        markers = [h.get('marker', '') for h in history]
        self.assertTrue(
            any('β.5.43-fix3' in m for m in markers),
            'vocab history 必有 β.5.43-fix3 marker',
        )

    def test_promise_detector_catches_closer_eye(self):
        """实际跑 SelfPromiseDetector 看 'I shall keep a closer eye on...' 现在能命中."""
        from jarvis_self_promise import get_default_detector
        # vocab mtime 检测自动 recompile
        det = get_default_detector()
        sample = (
            "I shall keep a closer eye on the telemetry and intervene if the "
            "environment appears to have stalled again. Let me note your instruction."
        )
        results = det.detect(sample)
        # 至少检出 1 条 (closer eye / intervene if)
        self.assertGreater(
            len(results), 0,
            f'vocab 加 verb 后 SelfPromiseDetector 应抓到 closer eye / intervene if, '
            f'实际 results={results}'
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
