# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


DEFAULT_PATH = os.path.join('memory_pool', 'relationship_state.json')


@dataclass
class RelationshipState:
    temperature: float = 0.5
    trust: float = 0.5
    rhythm: float = 0.5
    recent_friction: float = 0.0
    closeness: float = 0.5
    source: str = 'default'
    source_marker: str = ''
    updated_at: float = field(default_factory=time.time)
    updated_turn_id: str = ''
    note: str = ''

    def clamp(self) -> None:
        for key in ('temperature', 'trust', 'rhythm', 'recent_friction', 'closeness'):
            val = getattr(self, key)
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = 0.5
            setattr(self, key, max(0.0, min(1.0, val)))

    def to_dict(self) -> Dict[str, Any]:
        self.clamp()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RelationshipState':
        state = cls(
            temperature=float(data.get('temperature', 0.5)),
            trust=float(data.get('trust', 0.5)),
            rhythm=float(data.get('rhythm', 0.5)),
            recent_friction=float(data.get('recent_friction', 0.0)),
            closeness=float(data.get('closeness', 0.5)),
            source=str(data.get('source', 'default')),
            source_marker=str(data.get('source_marker', '')),
            updated_at=float(data.get('updated_at', time.time())),
            updated_turn_id=str(data.get('updated_turn_id', '')),
            note=str(data.get('note', ''))[:300],
        )
        state.clamp()
        return state


class RelationshipStateStore:
    DEFAULT_PATH = DEFAULT_PATH
    _DIMENSIONS = frozenset({
        'temperature', 'trust', 'rhythm', 'recent_friction', 'closeness',
    })

    def __init__(self, path: Optional[str] = None):
        self.path = path or self.DEFAULT_PATH
        self.state = RelationshipState()

    def load(self) -> RelationshipState:
        if not os.path.exists(self.path):
            return self.state
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f) or {}
            self.state = RelationshipState.from_dict(raw.get('state') or raw)
        except Exception:
            self.state = RelationshipState()
        return self.state

    def persist(self) -> bool:
        try:
            dirname = os.path.dirname(self.path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            snapshot = {
                'state': self.state.to_dict(),
                '_meta': {
                    'schema_version': 1,
                    'persisted_at': time.time(),
                    'persisted_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                },
            }
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def set_dimension(self, key: str, value: float, source: str = 'sir_manual',
                      turn_id: str = '', note: str = '') -> tuple[bool, str]:
        if key not in self._DIMENSIONS:
            return False, f'unknown dimension: {key}'
        try:
            val = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError) as e:
            return False, f'invalid value: {e}'
        old = getattr(self.state, key)
        setattr(self.state, key, val)
        self.state.source = source
        self.state.updated_at = time.time()
        self.state.updated_turn_id = turn_id
        self.state.note = str(note or '')[:300]
        self.persist()
        self._publish_update(key, old, val, source, turn_id, note)
        return True, f'{key}: {old:.2f} -> {val:.2f}'

    def to_prompt_line(self, max_chars: int = 180) -> str:
        self.state.clamp()
        s = self.state
        line = (
            'RELATIONSHIP STATE: '
            f'temperature={s.temperature:.2f}, trust={s.trust:.2f}, '
            f'rhythm={s.rhythm:.2f}, friction={s.recent_friction:.2f}, '
            f'closeness={s.closeness:.2f}'
        )
        if s.note:
            line += f' | note: {s.note[:60]}'
        if len(line) > max_chars:
            line = line[:max(0, max_chars - 1)].rstrip() + '…'
        return line

    def _publish_update(self, key: str, old: float, new: float, source: str,
                        turn_id: str, note: str) -> None:
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='relationship_state_updated',
                description=f'{key} changed {old:.2f}->{new:.2f} (src={source})',
                source='relationship_state',
                salience=0.7,
                metadata={
                    'dimension': key,
                    'old': old,
                    'new': new,
                    'source': source,
                    'turn_id': turn_id,
                    'note': str(note or '')[:200],
                },
                ttl=86400.0,
            )
        except Exception:
            pass


_DEFAULT_STORE: Optional[RelationshipStateStore] = None


def get_default_store() -> RelationshipStateStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = RelationshipStateStore()
        _DEFAULT_STORE.load()
    return _DEFAULT_STORE


def reset_default_store_for_test() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = None
