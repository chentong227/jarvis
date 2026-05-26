# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 12:21 真痛 CRITICAL] InnerThought propose_* 后立即 persist.

Sir 真测真痛:
  Dashboard 显示 75 thought 中 actionable_result='proposed:Do not open...
  (id=proto_20260526_115712_0a40)' — 看起来真 proposed.
  但 `python scripts/relational_dump.py` 显示 protocols=0,
  `memory_pool/relational_state.json` + `memory_pool/relational_review.json`
  都没那条 protocol. Phase A propose_protocol 闭环全废 (silently).

根因:
  InnerThought._do_propose_protocol → relational_state.propose_protocol()
  → 只 set _dirty=True 不真 flush 到 disk.
  inside_joke 被 inside_joke_reflector 救场 (那 daemon 周期 persist),
  但 protocol 没 reflector → _dirty 永远不 flush → 重启后丢.

修:
  + _flush_relational(kind) helper 调 persist() + write_review_queue()
  + _do_propose_protocol 成功后立即 _flush_relational('protocol')
  + _do_suggest_inside_joke 成功后立即 _flush_relational('inside_joke')
    (虽然 reflector 救场, 但准则 5 言出必行 — 不依赖别人)

测试覆盖 (6 个):
  L1 _flush_relational 调 persist + write_review_queue (基本)
  L2 _flush_relational rs=None 不爆 (defensive)
  L3 _flush_relational rs 无 persist method 不爆 (defensive)
  L4 _do_propose_protocol 成功后 真调 _flush_relational
  L5 _do_propose_protocol 失败 (dedup) 不调 _flush_relational
  L6 _do_suggest_inside_joke 成功后真调 _flush_relational
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _build_daemon(relational_state=None):
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    tmp = os.path.join(tempfile.gettempdir(),
                          f'persist_fix_{time.time()}.jsonl')
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp
    try:
        d = InnerThoughtDaemon(
            key_router=None,
            relational_state=relational_state,
        )
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp
    return d


# ==========================================================================
# L1: _flush_relational 调 persist + write_review_queue
# ==========================================================================
class TestFlushRelationalBasic(unittest.TestCase):
    def test_flush_calls_persist_and_write_review_queue(self):
        rs = MagicMock()
        rs.persist = MagicMock(return_value=True)
        rs.write_review_queue = MagicMock(return_value=True)
        d = _build_daemon(relational_state=rs)
        d._flush_relational('protocol')
        rs.persist.assert_called_once()
        rs.write_review_queue.assert_called_once()


# ==========================================================================
# L2: defensive — rs=None 不爆
# ==========================================================================
class TestFlushRelationalDefensiveNone(unittest.TestCase):
    def test_flush_with_none_rs_does_not_crash(self):
        d = _build_daemon(relational_state=None)
        # 不爆
        d._flush_relational('protocol')


# ==========================================================================
# L3: defensive — rs 无 persist method 不爆
# ==========================================================================
class TestFlushRelationalDefensiveMissingMethod(unittest.TestCase):
    def test_flush_with_rs_no_persist_method_does_not_crash(self):
        rs = MagicMock(spec=['add_protocol'])  # 没 persist 也没 write_review_queue
        d = _build_daemon(relational_state=rs)
        # 不爆
        d._flush_relational('protocol')


# ==========================================================================
# L4: _do_propose_protocol 成功后真调 _flush_relational
# ==========================================================================
class TestProposeProtocolFlushesOnSuccess(unittest.TestCase):
    def test_successful_propose_protocol_flushes_to_disk(self):
        """Sir 真痛 anchor: propose 后 disk 必须真有 protocol."""
        from jarvis_inner_thought_daemon import InnerThought
        from jarvis_relational import RelationalStateStore
        tmp_dir = tempfile.mkdtemp(prefix='propose_persist_fix_')
        persist_path = os.path.join(tmp_dir, 'rel.json')
        review_path = os.path.join(tmp_dir, 'rel_review.json')
        rs = RelationalStateStore(persist_path=persist_path,
                                       review_path=review_path)
        d = _build_daemon(relational_state=rs)

        thought = InnerThought(
            id='t_protofix',
            ts=time.time(),
            ts_iso='?',
            category='B',
            thought='I opened with formal apologies again, too stiff',
            salience=0.85,
            actionable='propose_protocol:Do not open replies with formal apologies',
            evidence_link='formal apologies',
        )
        ok, result = d._do_propose_protocol(thought, thought.actionable)
        self.assertTrue(ok, f'should succeed, got {result}')
        # 🎯 Sir 真痛 anchor: review_path 必须真有 protocol (不是只 in-memory)
        self.assertTrue(os.path.exists(review_path),
            f'review_path {review_path} 必须存在 (write_review_queue 真调)')
        import json
        review_data = json.load(open(review_path, encoding='utf-8'))
        protocols_in_review = review_data.get('unspoken_protocols', [])
        self.assertGreaterEqual(len(protocols_in_review), 1,
            'review queue 必须真有刚 propose 的 protocol')
        # 找到刚 propose 的那条
        found = [p for p in protocols_in_review
                 if 'formal apologies' in p.get('rule', '')]
        self.assertEqual(len(found), 1,
            f'刚 propose 的 protocol 必须在 review queue, got: {protocols_in_review}')


# ==========================================================================
# L5: 失败 (dedup) 不调 _flush_relational
# ==========================================================================
class TestProposeProtocolNoFlushOnFail(unittest.TestCase):
    def test_dedup_failure_does_not_flush(self):
        rs = MagicMock()
        rs.propose_protocol = MagicMock(return_value=False)  # 假装 dedup fail
        rs.persist = MagicMock()
        rs.write_review_queue = MagicMock()
        d = _build_daemon(relational_state=rs)

        from jarvis_inner_thought_daemon import InnerThought
        thought = InnerThought(
            id='t_dedup',
            ts=time.time(),
            ts_iso='?',
            category='B',
            thought='formal apologies issue noticed',
            salience=0.85,
            actionable='propose_protocol:Do not open with formal apologies',
            evidence_link='formal apologies',
        )
        ok, _ = d._do_propose_protocol(thought, thought.actionable)
        self.assertFalse(ok)
        # 失败时不 flush (节省 disk I/O)
        rs.persist.assert_not_called()
        rs.write_review_queue.assert_not_called()


# ==========================================================================
# L6: _do_suggest_inside_joke 成功后真调 _flush_relational
# ==========================================================================
class TestProposeInsideJokeFlushesOnSuccess(unittest.TestCase):
    def test_successful_propose_joke_flushes(self):
        rs = MagicMock()
        rs.propose_inside_joke = MagicMock(return_value=True)
        rs.persist = MagicMock()
        rs.write_review_queue = MagicMock()
        d = _build_daemon(relational_state=rs)

        from jarvis_inner_thought_daemon import InnerThought
        thought = InnerThought(
            id='t_joke',
            ts=time.time(),
            ts_iso='?',
            category='E',
            thought='Sir said "vocal cord logic" — that\'s a callback worthy phrase',
            salience=0.8,
            actionable='suggest_inside_joke:vocal cord logic',
            evidence_link='vocal cord',
        )
        ok, _ = d._do_suggest_inside_joke(thought, thought.actionable)
        self.assertTrue(ok)
        rs.persist.assert_called_once()
        rs.write_review_queue.assert_called_once()


if __name__ == '__main__':
    unittest.main()
