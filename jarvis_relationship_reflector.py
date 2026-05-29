# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from jarvis_relationship_state import RelationshipStateStore


DIMENSION_HINTS = {
    'temperature': 'current warmth / ease in the interaction',
    'trust': 'stable confidence that Jarvis follows through',
    'rhythm': 'how well Jarvis matches Sir timing and cadence',
    'recent_friction': 'recent irritation, correction, or mismatch',
    'closeness': 'felt familiarity and shared context',
}


RELATIONSHIP_REFLECTOR_PROMPT = """[ROLE]
You are Jarvis's relationship-state reflector. Read recent dialogue and propose at most one RelationshipState dimension adjustment.

[DIMENSIONS]
{dimensions}

[CURRENT STATE]
{current_state}

[RECENT DIALOGUE]
{recent_dialogue}

[OUTPUT JSON ONLY]
{{"proposal": null}}
or
{{"proposal": {{"dimension": "temperature|trust|rhythm|recent_friction|closeness", "value": 0.0, "reason": "short evidence-grounded reason"}}}}

Rules:
- Propose only if evidence is clear.
- Do not decide behavior. Only propose a state update for Sir review.
- No markdown.
"""


class RelationshipReflector:
    def __init__(self, relationship_store: Optional[RelationshipStateStore] = None,
                 key_router=None, config: Optional[Dict[str, Any]] = None):
        self.relationship_store = relationship_store or RelationshipStateStore()
        self.key_router = key_router
        self.config = {
            'primary_model': 'google/gemini-2.5-flash-lite',
            'fallback_model': 'google/gemini-3.1-pro-preview',
            'temperature': 0.2,
            'max_output_tokens': 300,
            'timeout_s': 15.0,
            'stm_lookback': 30,
        }
        if config:
            self.config.update(config)

    def propose_from_signal(self, dimension: str, value: float, reason: str,
                            evidence_turn_id: str = '') -> tuple[bool, str]:
        return self.relationship_store.propose_dimension(
            dimension,
            value,
            reason=reason,
            evidence_turn_id=evidence_turn_id,
            source='relationship_reflector',
        )

    def build_prompt(self, stm: List[Dict[str, Any]]) -> str:
        recent = self._format_stm(stm[-int(self.config.get('stm_lookback', 30)):])
        dims = '\n'.join(f'- {k}: {v}' for k, v in DIMENSION_HINTS.items())
        return RELATIONSHIP_REFLECTOR_PROMPT.format(
            dimensions=dims,
            current_state=self.relationship_store.to_prompt_line(max_chars=220),
            recent_dialogue=recent,
        )

    def reflect_once(self, stm: List[Dict[str, Any]], force_llm_text: str = '') -> Dict[str, Any]:
        result = {'ok': False, 'proposed': False, 'proposal_id': '', 'reason': ''}
        if not stm:
            result['reason'] = 'no_stm'
            return result
        response_text = force_llm_text or self._call_llm(self.build_prompt(stm))
        if not response_text:
            result['reason'] = 'empty_llm_response'
            return result
        proposal = self._parse_response(response_text)
        if not proposal:
            result.update({'ok': True, 'reason': 'no_proposal'})
            return result
        ok, msg = self.propose_from_signal(
            proposal.get('dimension', ''),
            proposal.get('value', 0.5),
            proposal.get('reason', '')[:300],
            evidence_turn_id=self._latest_turn_id(stm),
        )
        result.update({
            'ok': ok,
            'proposed': ok,
            'proposal_id': msg if ok else '',
            'reason': msg,
        })
        return result

    def _call_llm(self, prompt: str) -> str:
        if self.key_router is None:
            return ''
        try:
            from jarvis_utils import safe_openrouter_call
            key, _label = self.key_router.get_openrouter_key(
                caller='relationship_reflector')
            try:
                return safe_openrouter_call(
                    openrouter_key=key,
                    model=self.config['primary_model'],
                    prompt=prompt,
                    max_tokens=int(self.config['max_output_tokens']),
                    temperature=float(self.config['temperature']),
                    timeout_s=float(self.config['timeout_s']),
                )
            finally:
                try:
                    self.key_router.release(_label)
                except Exception:
                    pass
        except Exception:
            return ''

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, Any]]:
        try:
            raw = (text or '').strip()
            if raw.startswith('```'):
                lines = raw.split('\n')
                if len(lines) >= 3 and lines[-1].strip().startswith('```'):
                    raw = '\n'.join(lines[1:-1])
            data = json.loads(raw)
            proposal = data.get('proposal')
            if not isinstance(proposal, dict):
                return None
            return proposal
        except Exception:
            return None

    @staticmethod
    def _format_stm(stm: List[Dict[str, Any]]) -> str:
        lines = []
        for item in stm:
            src = item.get('source') or item.get('src') or item.get('role') or 'unknown'
            speaker = 'Sir' if src in ('user', 'user_voice', 'sir') else 'Jarvis'
            text = (item.get('text') or item.get('content') or '').strip()
            if text:
                lines.append(f'[{speaker}] {text[:180]}')
        return '\n'.join(lines) if lines else '(empty)'

    @staticmethod
    def _latest_turn_id(stm: List[Dict[str, Any]]) -> str:
        for item in reversed(stm):
            tid = item.get('turn_id') or item.get('trace_id') or ''
            if tid:
                return str(tid)
        return ''


def propose_relationship_signal(dimension: str, value: float, reason: str,
                                evidence_turn_id: str = '',
                                store: Optional[RelationshipStateStore] = None
                                ) -> tuple[bool, str]:
    return RelationshipReflector(store).propose_from_signal(
        dimension, value, reason, evidence_turn_id=evidence_turn_id)
