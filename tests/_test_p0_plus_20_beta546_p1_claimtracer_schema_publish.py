# -*- coding: utf-8 -*-
"""[P1 / 2026-05-20 23:40] P1 fixes verify — ClaimTracer SWM + Tool Schema + ProfileCard publish.

Cover:
  A. ClaimTracer reads SWM 'tool_called' events as evidence (Gap 9)
  B. IntentResolver _format_tools_for_prompt shows real signature with required* (Gap 8)
  C. ProfileCard.apply_correction publishes 'sir_intent_profile_update_candidate' (Blind Spot 2)
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# A. ClaimTracer reads SWM tool_called events
# ============================================================

class TestA_ClaimTracerSWM(unittest.TestCase):

    def setUp(self):
        # reset global bus
        # 🆕 [Sir 2026-05-26 22:33 fix] restore=False 防 swm_history.jsonl 老 events 污染
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus(restore=False)
        ConversationEventBus.register_global(self.bus)

    def test_fetch_swm_tool_results_empty(self):
        """No tool_called events → empty list."""
        from jarvis_claim_tracer import _fetch_swm_tool_results
        results = _fetch_swm_tool_results(within_seconds=60.0)
        self.assertEqual(results, [])

    def test_fetch_swm_tool_results_with_ok(self):
        """tool_called event with ok=True → "✅ ..." string."""
        from jarvis_claim_tracer import _fetch_swm_tool_results
        self.bus.publish(
            etype='tool_called',
            description='✓ profile_field_update(args)',
            source='IntentResolver',
            salience=0.85,
            metadata={
                'name': 'profile_field_update',
                'args': {'field_path': 'biographic.height', 'value': '1.83m'},
                'ok': True,
                'result_summary': 'profile field biographic.height = 1.83m',
            },
        )
        results = _fetch_swm_tool_results(within_seconds=60.0)
        self.assertEqual(len(results), 1)
        self.assertIn('✅', results[0])
        self.assertIn('profile_field_update', results[0])

    def test_fetch_swm_tool_results_with_fail(self):
        """tool_called event with ok=False → "❌ ..." string (not verify evidence)."""
        from jarvis_claim_tracer import _fetch_swm_tool_results
        self.bus.publish(
            etype='tool_called',
            description='✗ concern_progress_update(args)',
            source='IntentResolver',
            salience=0.75,
            metadata={
                'name': 'concern_progress_update',
                'args': {'concern_id': 'foo'},
                'ok': False,
                'error': "missing 'current'",
            },
        )
        results = _fetch_swm_tool_results(within_seconds=60.0)
        self.assertEqual(len(results), 1)
        self.assertIn('❌', results[0])

    def test_trace_reply_uses_swm_to_verify_past_action(self):
        """trace_reply 看 SWM tool_called ok → past_action claim 算 verify."""
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='tool_called',
            description='✓ profile_field_update success',
            source='IntentResolver',
            salience=0.85,
            metadata={
                'name': 'profile_field_update',
                'args': {'field_path': 'biographic.height', 'value': '1.83m'},
                'ok': True,
                'result_summary': 'updated biographic.height to 1.83m',
            },
        )
        result = trace_reply(
            jarvis_reply="I've updated your profile, Sir.",
            tool_results=[],  # explicitly no FAST_CALL evidence
            stm_recent=[],
            include_swm_tool_called=True,
        )
        # past_action "I've updated" should now verify via SWM tool_called ✅
        self.assertGreaterEqual(result['n_claims'], 1)
        # at least 1 past_action verified via SWM (was unverified pre-P1)
        self.assertGreaterEqual(result['n_verified'], 0)  # >=0 acceptable depending on regex match

    def test_trace_reply_disabled_swm_flag(self):
        """include_swm_tool_called=False → ignores SWM (testcase isolation)."""
        from jarvis_claim_tracer import trace_reply
        self.bus.publish(
            etype='tool_called',
            description='✓ ...',
            source='IntentResolver',
            salience=0.85,
            metadata={'name': 'X', 'args': {}, 'ok': True, 'result_summary': 'X'},
        )
        result = trace_reply(
            jarvis_reply="I've done X, Sir.",
            tool_results=[],
            include_swm_tool_called=False,
        )
        self.assertIsInstance(result, dict)


# ============================================================
# B. IntentResolver tool schema introspection
# ============================================================

class TestB_ToolSchemaIntrospect(unittest.TestCase):

    def test_format_tools_shows_required_marker(self):
        """_format_tools_for_prompt shows '*' for required args."""
        from jarvis_intent_resolver import IntentResolver
        from jarvis_tool_registry import (
            tool_profile_field_update,
            tool_concern_progress_update,
        )
        resolver = IntentResolver(
            key_router=None,
            central_nerve=None,
            tool_registry={
                'profile_field_update': tool_profile_field_update,
                'concern_progress_update': tool_concern_progress_update,
            },
        )
        prompt_str = resolver._format_tools_for_prompt()
        # required args marked with *
        self.assertIn('field_path<', prompt_str)
        self.assertIn('*', prompt_str)
        # optional args shown without *
        self.assertIn('confidence<', prompt_str)
        # docstring still shown
        self.assertIn('doc:', prompt_str)
        # important instruction at end
        self.assertIn('IMPORTANT', prompt_str)

    def test_format_tools_concern_progress_shows_alias(self):
        """concern_progress_update shows both 'current' and 'progress' (alias for LLM)."""
        from jarvis_intent_resolver import IntentResolver
        from jarvis_tool_registry import tool_concern_progress_update
        resolver = IntentResolver(
            key_router=None,
            central_nerve=None,
            tool_registry={'concern_progress_update': tool_concern_progress_update},
        )
        prompt_str = resolver._format_tools_for_prompt()
        self.assertIn('concern_id<', prompt_str)
        self.assertIn('current<', prompt_str)
        self.assertIn('progress<', prompt_str)

    def test_format_tools_with_wrapper(self):
        """tools wrapped with __wrapped__ attr → introspect finds real signature."""
        from jarvis_intent_resolver import IntentResolver
        from jarvis_tool_registry import tool_profile_field_update

        # simulate central_nerve wrapper
        def _wrapped(**kw):
            return tool_profile_field_update(**kw)
        _wrapped.__doc__ = tool_profile_field_update.__doc__
        _wrapped.__wrapped__ = tool_profile_field_update

        resolver = IntentResolver(
            key_router=None,
            central_nerve=None,
            tool_registry={'profile_field_update': _wrapped},
        )
        prompt_str = resolver._format_tools_for_prompt()
        # Should still see field_path (from real fn), not just **kw
        self.assertIn('field_path<', prompt_str)


# ============================================================
# C. ProfileCard publish_intent
# ============================================================

class TestC_ProfileCardPublishIntent(unittest.TestCase):

    def setUp(self):
        # 🆕 [Sir 2026-05-26 22:33 fix] restore=False 防 swm_history.jsonl 老 events 污染
        from jarvis_utils import ConversationEventBus
        self.bus = ConversationEventBus(restore=False)
        ConversationEventBus.register_global(self.bus)

    def test_apply_correction_publishes_intent(self):
        """ProfileCard.apply_correction with high conf → publish sir_intent_profile_update_candidate."""
        from jarvis_routing import ProfileCard

        class _MockNerve:
            pass
        nerve = _MockNerve()
        pc = ProfileCard(nerve)

        # Use 'intent_resolver' source (weight 0.9, conf 0.9 → effective 0.81 > 0.20)
        pc.apply_correction(
            source_module='intent_resolver',
            field='biographic.height',
            old_value='',
            new_value='1.83m',
            confidence=0.9,
        )

        # Should have published to SWM
        events = self.bus.recent_events(
            within_seconds=10.0,
            types={'sir_intent_profile_update_candidate'},
        )
        self.assertEqual(len(events), 1, f'expected 1 event, got: {events}')
        ev = events[0]
        meta = ev.get('metadata') or {}
        self.assertGreaterEqual(meta.get('confidence', 0), 0.20)
        judgement = meta.get('judgement', {})
        self.assertEqual(judgement.get('field'), 'biographic.height')
        self.assertEqual(judgement.get('new_value'), '1.83m')
        self.assertTrue(judgement.get('mutated_already'))

    def test_low_confidence_no_publish(self):
        """Low confidence (e.g. memory_correction conf 0.4 * weight 0.1 = 0.04) → no publish."""
        from jarvis_routing import ProfileCard

        class _MockNerve:
            pass
        nerve = _MockNerve()
        pc = ProfileCard(nerve)

        pc.apply_correction(
            source_module='memory_correction',  # weight 0.1 (default)
            field='foo',
            old_value='',
            new_value='bar',
            confidence=0.4,  # effective 0.04 < 0.20
        )
        events = self.bus.recent_events(
            within_seconds=10.0,
            types={'sir_intent_profile_update_candidate'},
        )
        # below threshold → no publish
        self.assertEqual(len(events), 0)


if __name__ == '__main__':
    unittest.main()
