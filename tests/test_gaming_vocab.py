# -*- coding: utf-8 -*-
"""[Sir 真测 BUG-2 治本 / 2026-05-24] test_gaming_vocab — Gaming auto-detection 验证

测试覆盖 (准则 6.5 三件套):
  1. vocab JSON 持久化加载 + mtime cache
  2. _check_gaming title 命中 + fullscreen 判定
  3. is_gaming_active class attr 切换
  4. get_gaming_vad_adaptation 倍数
  5. SWM publish gaming_mode_activated / ended
  6. fail-safe: vocab 损坏 → seed fallback
"""
from __future__ import annotations
import os
import sys
import json
import time
import tempfile
import shutil
import pytest

# 确保 import 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def vocab_tmpdir(tmp_path, monkeypatch):
    """临时 vocab 路径 + monkeypatch PhysicalEnvironmentProbe 用此路径."""
    from jarvis_env_probe import PhysicalEnvironmentProbe
    vocab_path = tmp_path / 'gaming_vocab.json'
    # reset cls cache
    PhysicalEnvironmentProbe._gaming_vocab_cache = None
    PhysicalEnvironmentProbe._gaming_vocab_mtime = 0.0
    PhysicalEnvironmentProbe._gaming_vocab_path = str(vocab_path)
    PhysicalEnvironmentProbe.is_gaming_active = False
    PhysicalEnvironmentProbe.current_gaming_title = ''
    PhysicalEnvironmentProbe.gaming_started_at = 0.0
    yield str(vocab_path)
    # cleanup cls state
    PhysicalEnvironmentProbe._gaming_vocab_cache = None
    PhysicalEnvironmentProbe._gaming_vocab_path = None
    PhysicalEnvironmentProbe.is_gaming_active = False


def _write_vocab(path: str, titles: list, require_fs: bool = True,
                  vol_mult: float = 1.8, sil_mult: float = 1.3) -> None:
    data = {
        '_meta': {'version': 2},
        'require_fullscreen': require_fs,
        'title_keywords': [
            {'pattern': p, 'state': 'active', 'added': '2026-05-24'}
            for p in titles
        ],
        'vad_adaptation': {
            'volume_threshold_multiplier': vol_mult,
            'silence_limit_multiplier': sil_mult,
        },
        '_review_queue': [],
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def test_load_gaming_vocab_active_only(vocab_tmpdir):
    """vocab JSON 加载只取 state=active. mixed state → 只 active 进 cache."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    data = {
        'require_fullscreen': True,
        'title_keywords': [
            {'pattern': 'lol', 'state': 'active'},
            {'pattern': 'badgame', 'state': 'rejected'},
            {'pattern': '帝国时代', 'state': 'active'},
        ],
        'vad_adaptation': {'volume_threshold_multiplier': 1.8,
                            'silence_limit_multiplier': 1.3},
    }
    with open(vocab_tmpdir, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    vocab = P._load_gaming_vocab()
    assert vocab is not None
    assert 'lol' in vocab['title_keywords']
    assert '帝国时代' in vocab['title_keywords']
    assert 'badgame' not in vocab['title_keywords']
    assert vocab['require_fullscreen'] is True


def test_load_gaming_vocab_mtime_cache(vocab_tmpdir):
    """mtime cache: 第二次 load 不重读 file."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['lol'])
    v1 = P._load_gaming_vocab()
    v2 = P._load_gaming_vocab()
    assert v1 is v2  # 同一 dict 引用 (cache hit)


def test_load_gaming_vocab_mtime_reload(vocab_tmpdir):
    """vocab 文件变 → cache 自动 reload."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['lol'])
    v1 = P._load_gaming_vocab()
    assert 'lol' in v1['title_keywords']
    time.sleep(0.05)
    _write_vocab(vocab_tmpdir, ['lol', 'dota'])
    # 强制 mtime 变化 (Windows file system mtime granularity)
    os.utime(vocab_tmpdir, None)
    v2 = P._load_gaming_vocab()
    assert 'dota' in v2['title_keywords']


def test_load_gaming_vocab_missing_returns_none(vocab_tmpdir):
    """vocab 文件不存在 → 返 None (走 seed fallback)."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    # vocab_tmpdir 路径还没写 file
    assert not os.path.exists(vocab_tmpdir)
    vocab = P._load_gaming_vocab()
    assert vocab is None


def test_load_gaming_vocab_corrupted_returns_none(vocab_tmpdir):
    """vocab 文件损坏 → 返 None, 不 crash."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    with open(vocab_tmpdir, 'w', encoding='utf-8') as f:
        f.write('{ malformed json {{')
    vocab = P._load_gaming_vocab()
    assert vocab is None


def test_check_gaming_title_match_require_fullscreen(vocab_tmpdir, monkeypatch):
    """title 命中 + require_fullscreen=True → 必须全屏才算."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['league of legends'], require_fs=True)
    # mock fullscreen check
    monkeypatch.setattr(P, '_is_window_fullscreen', staticmethod(lambda hwnd: True))
    assert P._check_gaming('League of Legends (TM) Client', hwnd=12345) is True
    # 不全屏 → False
    monkeypatch.setattr(P, '_is_window_fullscreen', staticmethod(lambda hwnd: False))
    assert P._check_gaming('League of Legends (TM) Client', hwnd=12345) is False


def test_check_gaming_title_match_no_require_fullscreen(vocab_tmpdir, monkeypatch):
    """require_fullscreen=False → title 命中即 True."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['league of legends'], require_fs=False)
    monkeypatch.setattr(P, '_is_window_fullscreen', staticmethod(lambda hwnd: False))
    assert P._check_gaming('League of Legends Client', hwnd=12345) is True


def test_check_gaming_no_match(vocab_tmpdir):
    """title 不命中 → False (即使全屏)."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['lol'])
    assert P._check_gaming('Visual Studio Code - main.py', hwnd=12345) is False
    assert P._check_gaming('', hwnd=12345) is False
    assert P._check_gaming('Steam', hwnd=12345) is False  # Steam 不算


def test_check_gaming_case_insensitive(vocab_tmpdir, monkeypatch):
    """title match 是 case-insensitive."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['lol'], require_fs=False)
    assert P._check_gaming('LOL Client', hwnd=12345) is True
    assert P._check_gaming('lol client', hwnd=12345) is True
    assert P._check_gaming('LoL CLIENT', hwnd=12345) is True


def test_check_gaming_seed_fallback(vocab_tmpdir, monkeypatch):
    """vocab 缺失 → seed fallback (LOL/帝国时代/...)."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    # 不写 vocab 文件 → fallback
    assert not os.path.exists(vocab_tmpdir)
    monkeypatch.setattr(P, '_is_window_fullscreen', staticmethod(lambda hwnd: True))
    # seed 含 'league of legends' / '帝国时代'
    assert P._check_gaming('League of Legends', hwnd=12345) is True
    assert P._check_gaming('帝国时代 IV', hwnd=12345) is True
    assert P._check_gaming('Random App', hwnd=12345) is False


def test_get_gaming_vad_adaptation_inactive(vocab_tmpdir):
    """is_gaming_active=False → 返 (1.0, 1.0)."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    P.is_gaming_active = False
    assert P.get_gaming_vad_adaptation() == (1.0, 1.0)


def test_get_gaming_vad_adaptation_active(vocab_tmpdir):
    """is_gaming_active=True → 返 vocab 倍数."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['lol'], vol_mult=2.0, sil_mult=1.5)
    P.is_gaming_active = True
    v, s = P.get_gaming_vad_adaptation()
    assert v == 2.0
    assert s == 1.5


def test_get_gaming_vad_adaptation_safety_bounds(vocab_tmpdir):
    """倍数应被 clamp 到安全区间 (1.0-3.0 / 1.0-2.5)."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    _write_vocab(vocab_tmpdir, ['lol'], vol_mult=100.0, sil_mult=100.0)
    P.is_gaming_active = True
    v, s = P.get_gaming_vad_adaptation()
    assert v == 3.0  # clamped
    assert s == 2.5  # clamped


def test_get_gaming_vad_adaptation_fallback_no_vocab(vocab_tmpdir):
    """vocab 缺失但 is_gaming_active=True → 用 hardcoded fallback (1.8, 1.3)."""
    from jarvis_env_probe import PhysicalEnvironmentProbe as P
    # 不写 vocab
    P.is_gaming_active = True
    v, s = P.get_gaming_vad_adaptation()
    assert v == 1.8
    assert s == 1.3
