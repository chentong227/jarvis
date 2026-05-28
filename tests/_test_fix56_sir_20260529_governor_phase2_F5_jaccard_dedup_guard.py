# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 governor Phase 2 F5] propose dedup python jaccard hard guard.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F5
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → governor

修缮目标 (缺口 ④):
  现状: relational_state.propose_protocol / propose_inside_joke 内有 jaccard
        0.7 dedup, 返 True/False. daemon 拿到 'dedup_or_fail' 不知具体重复哪条
        → LLM 下轮 actionable_result 看不到具体 id → 学不到不重复.
  治本: daemon 入口自 jaccard check (default 0.5 比 relational 0.7 更严),
        命中 → 返 'jaccard_dedup_rejected:overlap_with_<id>:<jaccard>'.
        LLM 下轮看到具体 id + jaccard 数 → 真学习不重复 propose.

F5 真改:
  1. memory_pool/inner_thought_propose_quality_vocab.json 加
     jaccard_dedup_enabled + jaccard_dedup_threshold (default 0.5)
  2. jarvis_inner_thought_daemon.py:
     - _PROPOSE_QUALITY_DEFAULT_VOCAB 加 jaccard_dedup_* fallback
     - 新 method _check_propose_jaccard_dedup(new_text, kind) -> (hit, id, jacc)
     - _do_propose_protocol 入口加 hard guard
     - _do_suggest_inside_joke 入口加 hard guard

测试覆盖 (9 testcase):
  - F5_1: _check_propose_jaccard_dedup hit when overlap >= threshold (protocol)
  - F5_2: _check_propose_jaccard_dedup miss when overlap < threshold
  - F5_3: _check_propose_jaccard_dedup hit on inside_joke
  - F5_4: review state entries 也算 (防 reject pending 同题)
  - F5_5: empty new_text → miss
  - F5_6: jaccard_dedup_enabled=False → 跳过 (放行)
  - F5_7: _do_propose_protocol hit dedup → 返 jaccard_dedup_rejected:overlap_with_<id>
  - F5_8: _do_suggest_inside_joke hit dedup → 同款 reject
  - F5_9: 跨 active+review propose_protocol 真 reject (端到端)
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_thought(category='B', salience=0.85, actionable='none',
                  thought='reflection text'):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f'th_{int(time.time() * 1000)}',
        ts=time.time(),
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
        category=category,
        thought=thought,
        salience=salience,
        actionable=actionable,
        evidence_link='none',
    )


def _make_protocol(pid, rule, state='active'):
    from jarvis_relational import UnspokenProtocol, STATE_ACTIVE, STATE_REVIEW
    p = UnspokenProtocol(id=pid, rule=rule, source='test')
    p.state = STATE_ACTIVE if state == 'active' else STATE_REVIEW
    return p


def _make_joke(jid, phrase, state='active'):
    from jarvis_relational import InsideJoke, STATE_ACTIVE, STATE_REVIEW
    j = InsideJoke(
        id=jid, phrase=phrase, birth_context='test',
        source='test', source_marker='', birth_turn_id='',
    )
    j.state = STATE_ACTIVE if state == 'active' else STATE_REVIEW
    return j


class TestF5Helper(unittest.TestCase):
    """F5_1-F5_6: _check_propose_jaccard_dedup helper."""

    def _make_daemon_with_rs(self):
        """Create daemon with mocked relational_state."""
        import tempfile
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        from jarvis_relational import RelationalStateStore
        rs = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='_rs.json'),
            review_path=tempfile.mktemp(suffix='_review.json'),
        )
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            daemon = InnerThoughtDaemon(
                key_router=MagicMock(),
                relational_state=rs,
            )
        # 清 cache 防其他 test 残留
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['data'] = None
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['mtime'] = 0.0
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['checked_at'] = 0.0
        return daemon, rs

    def test_F5_1_protocol_hit_above_threshold(self):
        """F5_1: protocol overlap >= 0.5 → hit."""
        daemon, rs = self._make_daemon_with_rs()
        # Existing protocol
        rs.add_protocol(_make_protocol(
            'p_existing', 'Do not open replies with formal apologies',
        ))
        # New text high overlap
        new_rule = 'Do not open with formal apologies in replies to Sir'
        hit, hit_id, jacc = daemon._check_propose_jaccard_dedup(
            new_rule, kind='protocol',
        )
        self.assertTrue(hit, f"F5_1 应 hit (jacc={jacc:.2f})")
        self.assertEqual(hit_id, 'p_existing')
        self.assertGreaterEqual(jacc, 0.5)

    def test_F5_2_protocol_miss_below_threshold(self):
        """F5_2: 不同主题 → miss."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_protocol(_make_protocol(
            'p_existing', 'Do not open with formal apologies',
        ))
        # 完全不同主题
        new_rule = 'Always check hydration sensor before nudging'
        hit, _id, _jacc = daemon._check_propose_jaccard_dedup(
            new_rule, kind='protocol',
        )
        self.assertFalse(hit, "F5_2 不同主题应 miss")

    def test_F5_3_inside_joke_hit(self):
        """F5_3: inside_joke 同题 hit."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_inside_joke(_make_joke(
            'j_existing', 'early sleep definition flexible as always',
        ))
        new_phrase = 'early sleep definition flexible always'  # 高重叠
        hit, hit_id, jacc = daemon._check_propose_jaccard_dedup(
            new_phrase, kind='inside_joke',
        )
        self.assertTrue(hit)
        self.assertEqual(hit_id, 'j_existing')

    def test_F5_4_review_state_also_counted(self):
        """F5_4: review state 也算 (防 reject pending 同题 propose)."""
        daemon, rs = self._make_daemon_with_rs()
        # 加 review state protocol
        rs.add_protocol(_make_protocol(
            'p_pending', 'Always confirm Sir command before action',
            state='review',
        ))
        # 新 propose 同义
        new_rule = 'Always confirm Sir command before taking action'
        hit, hit_id, _jacc = daemon._check_propose_jaccard_dedup(
            new_rule, kind='protocol',
        )
        self.assertTrue(hit, "F5_4 review state 也应 hit")
        self.assertEqual(hit_id, 'p_pending')

    def test_F5_5_empty_text_miss(self):
        """F5_5: empty new_text → miss (不算 hit)."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_protocol(_make_protocol('p_existing', 'anything here'))
        hit, _id, _jacc = daemon._check_propose_jaccard_dedup(
            '', kind='protocol',
        )
        self.assertFalse(hit)

    def test_F5_6_disabled_skip(self):
        """F5_6: vocab jaccard_dedup_enabled=False → 放行."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_protocol(_make_protocol('p_existing', 'identical rule text'))
        # Patch vocab disable
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['data'] = {
            'enabled': True,
            'jaccard_dedup_enabled': False,
            'jaccard_dedup_threshold': 0.5,
        }
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['checked_at'] = (
            time.time()
        )
        hit, _id, _jacc = daemon._check_propose_jaccard_dedup(
            'identical rule text', kind='protocol',
        )
        self.assertFalse(hit, "F5_6 disabled 应放行")
        # 清 cache
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['data'] = None


class TestF5EndToEnd(unittest.TestCase):
    """F5_7-F5_9: _do_propose_protocol / _do_suggest_inside_joke 端到端."""

    def _make_daemon_with_rs(self):
        import tempfile
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        from jarvis_relational import RelationalStateStore
        rs = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='_e2e_rs.json'),
            review_path=tempfile.mktemp(suffix='_e2e_review.json'),
        )
        with patch.object(
            InnerThoughtDaemon, '_append_cold_start_record',
            return_value=None,
        ):
            daemon = InnerThoughtDaemon(
                key_router=MagicMock(),
                relational_state=rs,
            )
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['data'] = None
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['mtime'] = 0.0
        InnerThoughtDaemon._PROPOSE_QUALITY_VOCAB_CACHE['checked_at'] = 0.0
        return daemon, rs

    def test_F5_7_propose_protocol_dedup_returns_overlap_with_id(self):
        """F5_7: _do_propose_protocol 命中 → 返 jaccard_dedup_rejected:overlap_with_<id>."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_protocol(_make_protocol(
            'p_xyz', 'Do not open replies with formal apologies',
        ))
        thought = _make_thought(category='B', salience=0.85)
        ok, result = daemon._do_propose_protocol(
            thought,
            'propose_protocol:Do not open replies with formal apologies to Sir',
        )
        self.assertFalse(ok)
        self.assertIn('jaccard_dedup_rejected', result)
        self.assertIn('overlap_with_p_xyz', result)
        self.assertIn('jaccard=', result)

    def test_F5_8_suggest_inside_joke_dedup_returns_overlap_with_id(self):
        """F5_8: _do_suggest_inside_joke 命中 → 同款 reject."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_inside_joke(_make_joke(
            'j_abc', 'early sleep definition flexible always',
        ))
        thought = _make_thought(category='E', salience=0.85)
        ok, result = daemon._do_suggest_inside_joke(
            thought,
            'suggest_inside_joke:early sleep definition flexible as always',
        )
        self.assertFalse(ok)
        self.assertIn('jaccard_dedup_rejected', result)
        self.assertIn('overlap_with_j_abc', result)

    def test_F5_9_non_dup_propose_passes(self):
        """F5_9: 不同主题 propose → 放行 (relational.propose 真调)."""
        daemon, rs = self._make_daemon_with_rs()
        rs.add_protocol(_make_protocol(
            'p_alpha', 'Do not open with formal apologies',
        ))
        thought = _make_thought(category='B', salience=0.85)
        ok, result = daemon._do_propose_protocol(
            thought,
            'propose_protocol:Always confirm before taking destructive action',
        )
        # 不同主题应放行 (relational 真 propose 成 review state)
        self.assertTrue(ok, f"F5_9 不同主题应放行, 实际 result={result}")
        self.assertIn('proposed:', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
