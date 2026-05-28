# -*- coding: utf-8 -*-
"""[Sir 2026-05-28 16:52 方案 A 治本 / dashboard 7-8 页堆积] stale_review_reaper

Sir 真痛 (dashboard 7-8 页 139 review 待办):
  "你认为 review 待办堆这么多 真因是什么?"

真因 (Sir 自查 + Cascade 数据印证):
  - 7d 内 163 个 defer_to_sir 累积 (57% 不动)
  - 没 TTL → 永远等 Sir 拍板, dashboard 翻 7-8 页

治本 (方案 A): AutoArbiter monitor_loop tick (15min) 末尾跑 reaper —
  - created_at + stale_review_archive_after_h 仍 review → 自动 archive
  - per-tick cap 防一次扫光
  - enabled=0 Sir 总开关关
  - publish SWM 'stale_review_archived' 让主脑/思考脑看
  - 准则 6 vocab: 全 calibration runtime 段 (Sir CLI scripts/auto_arbiter_dump.py)
  - 准则 7: archive 非 reject, Sir dashboard 可 restore

Cover:
  A. 老 review (≥ TTL) → 自动 archive (state 转 STATE_ARCHIVED)
  B. 新 review (< TTL) → 不动 (state 仍 STATE_REVIEW)
  C. enabled=0 → reaper 不跑 (老的也不动)
  D. per-tick cap 真守 (插 N 老, cap=2 只 reap 2)
  E. marker 在源码
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_auto_arbiter import AutoArbiterDaemon
from jarvis_relational import (
    RelationalStateStore,
    InsideJoke,
    STATE_REVIEW,
    STATE_ARCHIVED,
)


def _build_arbiter(runtime_overrides: dict = None) -> tuple:
    """构造 minimal AutoArbiterDaemon + 真 relational store (tmp persist).

    Returns (arbiter, store, tmp_path).
    """
    tmp = tempfile.NamedTemporaryFile(
        prefix='_test_fix37_relational_', suffix='.json', delete=False
    )
    tmp.close()
    store = RelationalStateStore(persist_path=tmp.name)
    store.load()
    arbiter = AutoArbiterDaemon(
        key_router=MagicMock(),
        relational_state=store,
    )
    # 注入 calibration runtime 段 (走 _effective_runtime 合并 default)
    if runtime_overrides:
        arbiter._calibration = {'runtime': dict(runtime_overrides)}
    return arbiter, store, tmp.name


def _insert_old_review_joke(store: RelationalStateStore,
                              jid: str, age_h: float) -> InsideJoke:
    """插一个 STATE_REVIEW 的 inside_joke, created_at = now - age_h*3600."""
    j = InsideJoke(
        id=jid,
        phrase=f'test_phrase_{jid}',
        birth_context='test',
        state=STATE_REVIEW,
        created_at=time.time() - age_h * 3600,
        source='test',
        source_marker=f'fix37_{jid}',
    )
    store.add_inside_joke(j)
    return j


class TestA_OldReviewArchived(unittest.TestCase):
    def test_old_review_auto_archived(self):
        """≥ TTL h 老 review → 自动 archive (state STATE_REVIEW → STATE_ARCHIVED)."""
        arbiter, store, _ = _build_arbiter(runtime_overrides={
            'stale_review_archive_after_h': 1.0,  # TTL 1h
            'stale_review_reap_per_tick_cap': 10,
            'stale_review_reap_enabled': 1,
        })
        old_joke = _insert_old_review_joke(store, 'jold_001', age_h=5.0)
        # sanity: state 是 REVIEW
        self.assertEqual(old_joke.state, STATE_REVIEW)
        arbiter._do_stale_review_reap()
        # 验证 state 转 archived
        archived = store.get_inside_joke('jold_001')
        self.assertIsNotNone(archived)
        self.assertEqual(archived.state, STATE_ARCHIVED,
                          msg=f"老 review 应 archived, got {archived.state}")


class TestB_NewReviewNotTouched(unittest.TestCase):
    def test_new_review_not_archived(self):
        """< TTL h 新 review → 不动 (state 仍 STATE_REVIEW)."""
        arbiter, store, _ = _build_arbiter(runtime_overrides={
            'stale_review_archive_after_h': 5.0,  # TTL 5h
            'stale_review_reap_per_tick_cap': 10,
            'stale_review_reap_enabled': 1,
        })
        new_joke = _insert_old_review_joke(store, 'jnew_001', age_h=1.0)
        arbiter._do_stale_review_reap()
        unchanged = store.get_inside_joke('jnew_001')
        self.assertEqual(unchanged.state, STATE_REVIEW,
                          msg=f"新 review 应保持 REVIEW, got {unchanged.state}")


class TestC_DisabledSwitchHonored(unittest.TestCase):
    def test_enabled_zero_no_reap(self):
        """enabled=0 → 老的也不动."""
        arbiter, store, _ = _build_arbiter(runtime_overrides={
            'stale_review_archive_after_h': 1.0,
            'stale_review_reap_per_tick_cap': 10,
            'stale_review_reap_enabled': 0,  # 总开关 OFF
        })
        old_joke = _insert_old_review_joke(store, 'jdis_001', age_h=10.0)
        arbiter._do_stale_review_reap()
        unchanged = store.get_inside_joke('jdis_001')
        self.assertEqual(unchanged.state, STATE_REVIEW,
                          msg='enabled=0 应不 reap, state 应保持 REVIEW')


class TestD_PerTickCap(unittest.TestCase):
    def test_per_tick_cap_honored(self):
        """插 5 老, cap=2 → 1 tick 只 reap 2 个."""
        arbiter, store, _ = _build_arbiter(runtime_overrides={
            'stale_review_archive_after_h': 1.0,
            'stale_review_reap_per_tick_cap': 2,  # cap = 2
            'stale_review_reap_enabled': 1,
        })
        for i in range(5):
            _insert_old_review_joke(store, f'jcap_{i:03}', age_h=10.0)
        arbiter._do_stale_review_reap()
        archived_n = sum(
            1 for jid in [f'jcap_{i:03}' for i in range(5)]
            if store.get_inside_joke(jid).state == STATE_ARCHIVED
        )
        self.assertEqual(archived_n, 2,
                          msg=f"cap=2 应只 reap 2, got {archived_n}")


class TestE_MarkerPresent(unittest.TestCase):
    def test_marker_in_source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_auto_arbiter.py',
        )
        src = open(path, 'r', encoding='utf-8').read()
        self.assertIn('_do_stale_review_reap', src,
                       msg='方案 A: _do_stale_review_reap 应在源码')
        self.assertIn('stale_review_archive_after_h', src,
                       msg='方案 A: vocab key stale_review_archive_after_h 应在源码')
        self.assertIn('Sir 2026-05-28 16:52', src,
                       msg='方案 A: Sir marker 应在源码')


if __name__ == '__main__':
    unittest.main()
