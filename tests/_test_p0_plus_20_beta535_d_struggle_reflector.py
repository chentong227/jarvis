# -*- coding: utf-8 -*-
"""[β.5.35-D / 2026-05-20] StruggleReflector L7 vocab daemon regression test.

Sir BUG 2 续: β.5.35-C 加 sir_struggle_vocab + worker detector + Conductor priority path,
β.5.35-D 补 L7 reflector: 24h 1 跑 LLM 看 STM [src=user_voice] propose 新 struggle phrase.

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta535DReflectorBasics(unittest.TestCase):
    """StruggleReflector 基础行为."""

    def test_module_importable(self):
        from jarvis_struggle_reflector import (
            StruggleReflector,
            STRUGGLE_REFLECTOR_CONFIG,
            STRUGGLE_REFLECTOR_PROMPT,
        )
        self.assertIsNotNone(StruggleReflector)
        self.assertIsInstance(STRUGGLE_REFLECTOR_CONFIG, dict)
        self.assertIsInstance(STRUGGLE_REFLECTOR_PROMPT, str)

    def test_config_has_required_keys(self):
        from jarvis_struggle_reflector import STRUGGLE_REFLECTOR_CONFIG as cfg
        for k in ('primary_model', 'fallback_model', 'min_interval_s',
                  'min_stm_for_run', 'max_propose_per_run', 'stm_lookback'):
            self.assertIn(k, cfg, f'config missing {k}')

    def test_24h_min_interval(self):
        """24h L7 跑频 (Sir 决定 4a OpenRouter cheap)."""
        from jarvis_struggle_reflector import STRUGGLE_REFLECTOR_CONFIG as cfg
        self.assertEqual(cfg['min_interval_s'], 86400)

    def test_no_key_router_no_crash(self):
        from jarvis_struggle_reflector import StruggleReflector
        r = StruggleReflector(key_router=None, stm_provider=lambda: [])
        result = r.force_run_now()
        self.assertIsInstance(result, dict)
        self.assertIn('reason', result)


class TestBeta535DStmFiltering(unittest.TestCase):
    """STM 过滤行为 — 只看 [src=user_voice]."""

    def setUp(self):
        from jarvis_struggle_reflector import StruggleReflector
        self.r = StruggleReflector(
            stm_provider=lambda: self.stm,
        )

    def test_filters_user_voice_only(self):
        self.stm = [
            {'text': 'i am stuck', 'source': 'user_voice'},
            {'text': 'system event', 'source': 'system_event'},
            {'text': 'jarvis self', 'source': 'jarvis_self'},
            {'text': 'how to fix', 'source': 'user_voice'},
        ]
        filtered = self.r._get_user_voice_stm()
        self.assertEqual(len(filtered), 2)
        for e in filtered:
            self.assertEqual(e.get('source'), 'user_voice')

    def test_empty_stm_safe(self):
        self.stm = []
        filtered = self.r._get_user_voice_stm()
        self.assertEqual(filtered, [])

    def test_handles_src_alias(self):
        """STM entry 用 'src' 或 'source' 都该认."""
        self.stm = [
            {'text': 'one', 'src': 'user_voice'},
            {'text': 'two', 'source': 'user_voice'},
        ]
        filtered = self.r._get_user_voice_stm()
        self.assertEqual(len(filtered), 2)


class TestBeta535DReflectionFlow(unittest.TestCase):
    """LLM reflect 路径 + vocab write (mocked LLM)."""

    def setUp(self):
        from jarvis_struggle_reflector import StruggleReflector
        self.tmp_vocab = tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                                     delete=False, encoding='utf-8')
        json.dump({
            '_meta': {'schema_version': 1},
            'phrases': [{
                'id': 'stuck_en',
                'state': 'active',
                'patterns': ['stuck', 'blocked'],
                'severity': 'high',
            }],
            'review_queue': [],
            'rejected_history': [],
        }, self.tmp_vocab)
        self.tmp_vocab.close()
        self.mock_kr = MagicMock()
        self.mock_kr.get_openrouter_key.return_value = ('sk-fake', 'or_test')
        self.stm = [
            {'text': "this code is killing me", 'source': 'user_voice'},
            {'text': "what the hell is going on", 'source': 'user_voice'},
            {'text': "killing me again", 'source': 'user_voice'},
        ]
        self.r = StruggleReflector(
            key_router=self.mock_kr,
            stm_provider=lambda: self.stm,
            vocab_path=self.tmp_vocab.name,
            config={'min_stm_for_run': 1},
        )

    def tearDown(self):
        try:
            os.unlink(self.tmp_vocab.name)
        except Exception:
            pass

    def test_propose_writes_review_queue(self):
        fake_llm = json.dumps({
            'proposed_phrases': [{
                'id': 'frustrated_killing',
                'patterns': ['killing me', "what the hell"],
                'severity': 'high',
                'evidence_utterances': ['this code is killing me'],
                'rationale': 'Sir 表达强 frustration',
            }]
        })
        with patch('jarvis_struggle_reflector.safe_openrouter_call',
                   return_value=fake_llm):
            result = self.r.force_run_now()
        self.assertTrue(result.get('ok'), f'reflect should succeed: {result}')
        self.assertEqual(result.get('proposed_n'), 1)
        with open(self.tmp_vocab.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        review = data.get('review_queue', [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]['id'], 'frustrated_killing')
        self.assertEqual(review[0]['state'], 'review')
        self.assertEqual(review[0]['severity'], 'high')
        self.assertEqual(review[0]['source'], 'L7 reflector')

    def test_dedup_no_double_propose(self):
        """同 id 已 active → 跳过 propose."""
        fake_llm = json.dumps({
            'proposed_phrases': [{
                'id': 'stuck_en',  # 已 active
                'patterns': ['new pattern'],
                'severity': 'high',
            }]
        })
        with patch('jarvis_struggle_reflector.safe_openrouter_call',
                   return_value=fake_llm):
            result = self.r.force_run_now()
        self.assertTrue(result.get('ok'))
        self.assertEqual(result.get('proposed_n'), 0)

    def test_invalid_severity_defaults_medium(self):
        fake_llm = json.dumps({
            'proposed_phrases': [{
                'id': 'new_p',
                'patterns': ['something'],
                'severity': 'INVALID',
            }]
        })
        with patch('jarvis_struggle_reflector.safe_openrouter_call',
                   return_value=fake_llm):
            result = self.r.force_run_now()
        self.assertEqual(result.get('proposed_n'), 1)
        with open(self.tmp_vocab.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        review = data['review_queue']
        # 找新 proposal (不是 stuck_en)
        new_p = next((p for p in review if p['id'] == 'new_p'), None)
        self.assertIsNotNone(new_p)
        self.assertEqual(new_p['severity'], 'medium', 'INVALID severity 必须 fallback medium')

    def test_llm_parse_failure_no_crash(self):
        with patch('jarvis_struggle_reflector.safe_openrouter_call',
                   return_value='not a json'):
            result = self.r.force_run_now()
        self.assertFalse(result.get('ok'))
        self.assertIn('parse fail', result.get('reason', ''))


class TestBeta535DCentralNerveWiring(unittest.TestCase):
    """central_nerve 启动时 wire struggle_reflector."""

    def test_central_nerve_starts_reflector(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.35-D', src,
            'β.5.35-D marker 必须在 jarvis_central_nerve.py')
        self.assertIn('StruggleReflector', src,
            'StruggleReflector 必须被 wire')
        self.assertIn('struggle_reflector', src,
            'self.struggle_reflector 字段必须存在')


if __name__ == '__main__':
    unittest.main()
