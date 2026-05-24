# -*- coding: utf-8 -*-
"""[Sir 真测 BUG-2 治本 / 2026-05-24] test_sensor_state_gating — gating_field 验证

Gaming 字段 conditional inject:
  - is_gaming_active=False → gaming_title/gaming_minutes 不 inject (省 token)
  - is_gaming_active=True  → gaming_title/gaming_minutes 都 inject
"""
from __future__ import annotations
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def reset_env_probe():
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    from jarvis_sensor_state_block import reload_vocab
    # 重置
    P.is_gaming_active = False
    P.current_gaming_title = ''
    P.gaming_started_at = 0.0
    reload_vocab()
    yield
    P.is_gaming_active = False
    P.current_gaming_title = ''
    P.gaming_started_at = 0.0


def test_gaming_fields_hidden_when_inactive():
    """is_gaming_active=False → gaming_title / gaming_min 不出现 in block."""
    from jarvis_sensor_state_block import build_sensor_state_block
    b = build_sensor_state_block(tier='CHAT', max_chars=3000)
    # is_gaming_active 应该 inject (False 也显示, 告诉主脑 'Sir 不在 Gaming')
    assert 'is_gaming_active' in b
    # 但 title / min 应 gated 掉
    assert 'gaming_title' not in b
    assert 'gaming_min' not in b


def test_gaming_fields_shown_when_active():
    """is_gaming_active=True → gaming_title / gaming_min 都出现."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    from jarvis_sensor_state_block import build_sensor_state_block
    P.is_gaming_active = True
    P.current_gaming_title = 'League of Legends'
    P.gaming_started_at = time.time() - 1860  # 31 min ago
    b = build_sensor_state_block(tier='CHAT', max_chars=3000)
    assert 'is_gaming_active: True' in b
    assert 'gaming_title' in b
    assert 'League of Legends' in b
    assert 'gaming_min' in b
    # gaming_min 应该是 30 or 31 min
    import re
    m = re.search(r'gaming_min:\s*(\d+)', b)
    assert m is not None
    minutes = int(m.group(1))
    assert 30 <= minutes <= 32  # 31 min ± 1


def test_elapsed_minutes_transform_zero_safe():
    """gaming_started_at=0 → elapsed_minutes 返 0, 不 raise."""
    from jarvis_sensor_state_block import _apply_transform
    assert _apply_transform(0, 'elapsed_minutes') == 0
    assert _apply_transform(None, 'elapsed_minutes') == 0
    assert _apply_transform('', 'elapsed_minutes') == 0
    # 真 timestamp → 转 min
    ts_5_min_ago = time.time() - 300
    assert _apply_transform(ts_5_min_ago, 'elapsed_minutes') == 5


def test_short_chat_tier_only_has_is_gaming_active():
    """SHORT_CHAT tier 仅 is_gaming_active (省 token), title/min 不在."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    from jarvis_sensor_state_block import build_sensor_state_block
    P.is_gaming_active = True
    P.current_gaming_title = 'AOE4'
    P.gaming_started_at = time.time() - 600
    b = build_sensor_state_block(tier='SHORT_CHAT', max_chars=3000)
    assert 'is_gaming_active' in b
    # title / min 在 CHAT/DEEP_QUERY tier 才有, SHORT_CHAT 不在
    assert 'gaming_title' not in b
    assert 'gaming_min' not in b
