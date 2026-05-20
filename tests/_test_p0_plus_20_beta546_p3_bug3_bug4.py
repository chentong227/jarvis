# -*- coding: utf-8 -*-
"""[P3 BUG#3+#4 / 2026-05-20 23:48] ProfileReflector LLM + ReturnSentinel publish

Cover:
  BUG #3: ProfileReflector propose_from_corrections accepts use_llm flag,
          stub fallback when LLM unavailable
  BUG #4: ReturnSentinel _on_return publishes sir_intent_return_greeting_candidate
          + env JARVIS_RETURN_SENTINEL_RETIRE=1 真退化
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# BUG #3: ProfileReflector LLM-propose + stub fallback
# ============================================================

class TestBug3_ProfileReflectorLLM(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='profile_reflector_test_')
        self.review_path = os.path.join(self.tmpdir, 'profile_review.json')
        self.corrections_path = os.path.join(self.tmpdir, 'profile_corrections.jsonl')
        # seed corrections (need >=5 total, >=3 per field)
        with open(self.corrections_path, 'w', encoding='utf-8') as f:
            for i in range(4):
                f.write(json.dumps({
                    'time': '12:00:00', 'iso': '2026-05-20T12:00:00', 'ts': time.time() - 100 + i,
                    'source': 'intent_resolver', 'field': 'biographic.height',
                    'old': '1.80m', 'new': '1.83m', 'confidence': 0.8,
                }) + '\n')
            for i in range(3):
                f.write(json.dumps({
                    'time': '12:00:00', 'iso': '2026-05-20T12:00:00', 'ts': time.time() - 50 + i,
                    'source': 'intent_resolver', 'field': 'biographic.weight',
                    'old': '90kg', 'new': '95kg', 'confidence': 0.8,
                }) + '\n')

        from jarvis_profile_reflector import ProfileReflector
        self.reflector = ProfileReflector(
            review_path=self.review_path,
            corrections_path=self.corrections_path,
            min_corrections=3,
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stub_aggregation(self):
        """use_llm=False → stub aggregation."""
        new_props = self.reflector.propose_from_corrections(use_llm=False)
        self.assertGreaterEqual(len(new_props), 2)  # at least biographic.height + weight
        # 验 stub rationale prefix
        for p in new_props:
            self.assertIn('[stub]', p.rationale)

    def test_llm_path_falls_back_when_llm_unavail(self):
        """No LLM keys / model → fallback to stub."""
        # In test env, key_router unavailable, so _llm_propose falls back to stub.
        new_props = self.reflector.propose_from_corrections(use_llm=True)
        self.assertGreaterEqual(len(new_props), 2)
        # 验 fallback to stub (since no LLM in test env)
        # rationale could be [stub] or [LLM conf=...], both OK
        for p in new_props:
            self.assertTrue(
                p.rationale.startswith('[stub]') or p.rationale.startswith('[LLM '),
                f'unexpected rationale: {p.rationale}'
            )

    def test_review_queue_persisted(self):
        self.reflector.propose_from_corrections(use_llm=False)
        self.assertTrue(os.path.exists(self.review_path))
        with open(self.review_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('proposals', data)
        self.assertGreaterEqual(len(data['proposals']), 2)

    def test_dedup_skip_existing_review(self):
        """Same field with open review proposal → skip."""
        first = self.reflector.propose_from_corrections(use_llm=False)
        self.assertGreaterEqual(len(first), 2)
        # second run: all fields already in review → skip
        second = self.reflector.propose_from_corrections(use_llm=False)
        self.assertEqual(len(second), 0)


# ============================================================
# BUG #4: ReturnSentinel publish candidate + retire env flag
# ============================================================

class TestBug4_ReturnSentinelPublish(unittest.TestCase):

    def test_source_has_publish_candidate(self):
        """static check: jarvis_return_sentinel.py contains publish path."""
        import jarvis_return_sentinel
        with open(jarvis_return_sentinel.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("etype='sir_intent_return_greeting_candidate'", src,
                       'P3 BUG#4: must publish sir_intent_return_greeting_candidate')
        self.assertIn('JARVIS_RETURN_SENTINEL_RETIRE', src,
                       'P3 BUG#4: must support env JARVIS_RETURN_SENTINEL_RETIRE')

    def test_gate_mode_vocab_has_return_sentinel(self):
        """Verify gate_mode_vocab.json has ReturnSentinel entry."""
        import json as _json
        gate_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'gate_mode_vocab.json'
        )
        if not os.path.exists(gate_path):
            self.skipTest('gate_mode_vocab.json not present in test env')
        with open(gate_path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        current = data.get('current', {})
        self.assertIn('ReturnSentinel', current,
                       'ReturnSentinel should have gate_mode entry')


if __name__ == '__main__':
    unittest.main()
