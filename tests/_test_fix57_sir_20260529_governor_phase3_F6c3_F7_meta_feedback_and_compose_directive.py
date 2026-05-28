# -*- coding: utf-8 -*-
"""[Sir 2026-05-29 governor Phase 3 F6改3 + F7] 元学习闭环 + 思考脑装主脑 directive.

设计文档: docs/JARVIS_THINKING_BRAIN_GOVERNOR_DESIGN.md §5 F6改3 + F7
SOUL lineage: SOUL_DRIVE → UNIVERSALIZATION → THOUGHT_LOOP_PLAN → governor

修缮目标:
  F6改3 (缺口 ③ + V6 元学习闭环):
    主脑 reply meta 加 sir_reaction='pending' + directive_id (F7 关联)
    Sir 下一句输入 → mark engaged/rejected (negative keyword)
    思考脑 evidence meta_feedback_loop 看 last 5 reply + reaction
    → 自学习 (rejected 重组 directive)

  F7 (V5 Sir vision 思考脑 = governor):
    思考脑 actionable=compose_main_brain_directive:<text> → 装 directive
    inner_voice_track.set_thinking_brain_directive (TTL 5min)
    主脑 chat_bypass stream_chat 入口前 get_active_directive → 注入 prompt top

F6改3 + F7 真改:
  inner_voice_track.py:
    - mark_pending_main_replies_reacted(reaction, within_min)
    - get_recent_main_replies(within_min, max_n)
    - set_thinking_brain_directive(text, ttl_min, composed_by_thought_id)
    - get_active_directive()
    - clear_active_directive()
  daemon:
    - _execute_actionable dispatcher 加 compose_main_brain_directive
    - _do_compose_main_brain_directive helper (sal gate + set 真调)
    - _collect_evidence 加 ev['meta_feedback_loop']
    - _build_prompt 加 [META FEEDBACK LOOP] block
    - prompt FORMAT 加 compose_main_brain_directive actionable 教学
  chat_bypass:
    - stream_chat 入口 mark_pending_main_replies_reacted (engaged/rejected)
    - stream_chat 入口前 get_active_directive → prepend prompt top
    - main_reply self-append meta 加 sir_reaction + directive_id

测试覆盖 (~18 testcase):
  F6c3 (8):
    - F6c3_1: mark engaged
    - F6c3_2: mark rejected
    - F6c3_3: invalid reaction 跳
    - F6c3_4: 老 entry 超 cutoff 跳
    - F6c3_5: 已 marked 不 re-mark
    - F6c3_6: get_recent_main_replies 只返 main_reply
    - F6c3_7: _collect_evidence ev['meta_feedback_loop'] 含 entries
    - F6c3_8: _build_prompt [META FEEDBACK LOOP] 渲染 + emoji marks

  F7 (10):
    - F7_1: set_thinking_brain_directive 真存 + TTL
    - F7_2: empty/short text reject
    - F7_3: text 超 200 char truncate
    - F7_4: get_active_directive TTL 内返 dict
    - F7_5: get_active_directive 过期 → None + auto-clear
    - F7_6: clear_active_directive
    - F7_7: _do_compose_main_brain_directive sal gate (<0.75 reject)
    - F7_8: _do_compose_main_brain_directive empty text reject
    - F7_9: _do_compose 成功 → set_thinking_brain_directive 真调
    - F7_10: _execute_actionable dispatcher 加 compose_main_brain_directive
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


def _make_thought(thought_text='I should compose a directive',
                  category='B', salience=0.85, actionable='none'):
    from jarvis_inner_thought_daemon import InnerThought
    return InnerThought(
        id=f'th_test_{int(time.time() * 1000)}',
        ts=time.time(),
        ts_iso=time.strftime('%Y-%m-%dT%H:%M:%S'),
        category=category,
        thought=thought_text,
        salience=salience,
        actionable=actionable,
        evidence_link='none',
    )


def _make_fresh_track():
    """构 fresh InnerVoiceTrack (隔离 singleton + jsonl path).

    注: 原始 InnerVoiceTrack 读 prod jsonl 加载旧数据.
    测试 fix: instantiate 后 清 _buffer + disable jsonl persist.
    """
    from jarvis_inner_voice_track import InnerVoiceTrack
    track = InnerVoiceTrack()
    # 清旧数据 + disable persist (防污染 prod jsonl)
    with track._lock:
        track._buffer.clear()
    # patch append 不打 jsonl (在 test fixture 中, MagicMock _persist_entry)
    if hasattr(track, '_persist_entry'):
        track._persist_entry = lambda _e: None
    return track


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    with patch.object(
        InnerThoughtDaemon, '_append_cold_start_record',
        return_value=None,
    ):
        return InnerThoughtDaemon(key_router=MagicMock())


# ============================================================
# F6c3 — meta_feedback_loop
# ============================================================

class TestF6c3MarkReaction(unittest.TestCase):
    """F6c3_1-5: inner_voice_track.mark_pending_main_replies_reacted."""

    def test_F6c3_1_mark_engaged(self):
        """F6c3_1: pending main_reply 标 engaged."""
        track = _make_fresh_track()
        track.append(
            source='self_reflection', intent='noting',
            content='i replied to sir: "test"',
            meta={'kind': 'main_reply', 'sir_reaction': 'pending'},
        )
        n = track.mark_pending_main_replies_reacted('engaged', within_min=10)
        self.assertEqual(n, 1)
        entries = track.recent(minutes=10)
        self.assertEqual(entries[0].meta['sir_reaction'], 'engaged')

    def test_F6c3_2_mark_rejected(self):
        """F6c3_2: 同样可以 mark rejected."""
        track = _make_fresh_track()
        track.append(
            source='self_reflection', intent='noting',
            content='reply', meta={'kind': 'main_reply',
                                     'sir_reaction': 'pending'},
        )
        n = track.mark_pending_main_replies_reacted('rejected')
        self.assertEqual(n, 1)
        entries = track.recent(minutes=10)
        self.assertEqual(entries[0].meta['sir_reaction'], 'rejected')

    def test_F6c3_3_invalid_reaction_skip(self):
        """F6c3_3: invalid reaction (如 'happy') 跳, 返 0."""
        track = _make_fresh_track()
        track.append(
            source='self_reflection', intent='noting', content='r',
            meta={'kind': 'main_reply', 'sir_reaction': 'pending'},
        )
        n = track.mark_pending_main_replies_reacted('happy')
        self.assertEqual(n, 0)

    def test_F6c3_4_old_entry_outside_cutoff_skip(self):
        """F6c3_4: 老 entry 超 cutoff 不 mark."""
        track = _make_fresh_track()
        # 直接 inject 老 entry (ts 1h ago)
        from jarvis_inner_voice_track import VoiceEntry
        old_entry = VoiceEntry(
            ts=time.time() - 3700,  # 1h+ ago
            source='self_reflection', content='old reply',
            intent='noting', urgency=0.3, wants_voice=False,
            meta={'kind': 'main_reply', 'sir_reaction': 'pending'},
        )
        with track._lock:
            track._buffer.append(old_entry)
        n = track.mark_pending_main_replies_reacted(
            'engaged', within_min=30,
        )
        self.assertEqual(n, 0, "F6c3_4 老 entry 不应 mark")

    def test_F6c3_5_already_marked_not_re_mark(self):
        """F6c3_5: 已 marked entry 不 re-mark (sir_reaction != pending)."""
        track = _make_fresh_track()
        track.append(
            source='self_reflection', intent='noting', content='r',
            meta={'kind': 'main_reply', 'sir_reaction': 'engaged'},  # 已 marked
        )
        n = track.mark_pending_main_replies_reacted('rejected')
        self.assertEqual(n, 0, "F6c3_5 已 marked 不应 re-mark")


class TestF6c3GetRecentMainReplies(unittest.TestCase):
    """F6c3_6: get_recent_main_replies filter."""

    def test_F6c3_6_returns_main_reply_only(self):
        """F6c3_6: 只返 meta.kind='main_reply', skip 其他."""
        track = _make_fresh_track()
        track.append(
            source='self_reflection', intent='noting',
            content='main_reply 1',
            meta={'kind': 'main_reply', 'sir_reaction': 'engaged'},
        )
        track.append(
            source='self_reflection', intent='noting',
            content='nudge_reply', meta={'kind': 'nudge_reply'},
        )
        track.append(
            source='inner_thought', intent='reflection', content='thought',
        )
        replies = track.get_recent_main_replies(within_min=10, max_n=5)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].content, 'main_reply 1')


class TestF6c3DaemonEvidence(unittest.TestCase):
    """F6c3_7: daemon _collect_evidence 加 meta_feedback_loop."""

    def test_F6c3_7_evidence_contains_meta_feedback_loop(self):
        """F6c3_7: ev['meta_feedback_loop'] 含 entries (含 reaction + age_s)."""
        daemon = _make_daemon()
        fake_track = MagicMock()
        from jarvis_inner_voice_track import VoiceEntry
        fake_track.recent.return_value = []  # F1 inner voice 用
        fake_entries = [
            VoiceEntry(
                ts=time.time() - 300,
                source='self_reflection', content='replied',
                intent='noting', urgency=0.3, wants_voice=False,
                meta={
                    'kind': 'main_reply',
                    'sir_reaction': 'engaged',
                    'reply_excerpt': 'Sir, noted.',
                    'sir_excerpt': 'hello',
                    'directive_id': 'th_xyz123',
                },
            )
        ]
        fake_track.get_recent_main_replies.return_value = fake_entries
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ):
            ev = daemon._collect_evidence(sir_state='active',
                                            within_seconds=600)
        self.assertIn('meta_feedback_loop', ev)
        mfl = ev['meta_feedback_loop']
        self.assertEqual(len(mfl), 1)
        self.assertEqual(mfl[0]['sir_reaction'], 'engaged')
        self.assertEqual(mfl[0]['reply_excerpt'], 'Sir, noted.')
        self.assertEqual(mfl[0]['directive_id'], 'th_xyz123')
        self.assertGreater(mfl[0]['age_s'], 0)


class TestF6c3PromptRender(unittest.TestCase):
    """F6c3_8: _build_prompt [META FEEDBACK LOOP] block."""

    def test_F6c3_8_prompt_renders_meta_feedback_loop_block(self):
        """F6c3_8: prompt 含 [META FEEDBACK LOOP] + emoji marks."""
        daemon = _make_daemon()
        mock_ev = {
            'sir_state': 'active', 'idle_seconds': 60, 'hour': 0,
            'recent_thoughts': [],
            'swm_events': [],
            'meta_feedback_loop': [
                {'reply_excerpt': 'engaged_reply',
                 'sir_excerpt': 'thanks', 'sir_reaction': 'engaged',
                 'directive_id': 'th_a', 'age_s': 120},
                {'reply_excerpt': 'rejected_reply',
                 'sir_excerpt': 'stop', 'sir_reaction': 'rejected',
                 'directive_id': 'th_b', 'age_s': 60},
            ],
        }
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=MagicMock(recent=MagicMock(return_value=[]))
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ):
            _sys, user_prompt = daemon._build_prompt(
                sir_state='active', evidence=mock_ev,
            )
        self.assertIn('[META FEEDBACK LOOP', user_prompt)
        self.assertIn('engaged_reply', user_prompt)
        self.assertIn('rejected_reply', user_prompt)
        # emoji marks
        self.assertIn('✅', user_prompt)  # engaged
        self.assertIn('❌', user_prompt)  # rejected
        # 教学 sentence
        self.assertIn('re-examine', user_prompt)


# ============================================================
# F7 — compose_main_brain_directive
# ============================================================

class TestF7DirectiveStore(unittest.TestCase):
    """F7_1-6: inner_voice_track set/get/clear_active_directive."""

    def test_F7_1_set_and_get(self):
        """F7_1: set_thinking_brain_directive 真存 + TTL."""
        track = _make_fresh_track()
        ok = track.set_thinking_brain_directive(
            text='be brief, skip health advice',
            ttl_min=5,
            composed_by_thought_id='th_xyz',
        )
        self.assertTrue(ok)
        d = track.get_active_directive()
        self.assertIsNotNone(d)
        self.assertEqual(d['text'], 'be brief, skip health advice')
        self.assertEqual(d['composed_by_thought_id'], 'th_xyz')
        self.assertGreater(d['expires_at'], time.time())

    def test_F7_2_empty_short_text_reject(self):
        """F7_2: empty 或 < 5 char reject."""
        track = _make_fresh_track()
        self.assertFalse(track.set_thinking_brain_directive(''))
        self.assertFalse(track.set_thinking_brain_directive('abc'))
        self.assertFalse(track.set_thinking_brain_directive('   '))

    def test_F7_3_text_truncate_at_200(self):
        """F7_3: text 超 200 char truncate."""
        track = _make_fresh_track()
        long_text = 'a' * 300
        track.set_thinking_brain_directive(long_text)
        d = track.get_active_directive()
        self.assertEqual(len(d['text']), 200)

    def test_F7_4_get_returns_dict_within_ttl(self):
        """F7_4: TTL 内 returns dict."""
        track = _make_fresh_track()
        track.set_thinking_brain_directive(
            text='valid directive', ttl_min=5,
        )
        d = track.get_active_directive()
        self.assertIsInstance(d, dict)

    def test_F7_5_get_returns_none_after_ttl(self):
        """F7_5: TTL 过期 → None + auto-clear."""
        track = _make_fresh_track()
        track.set_thinking_brain_directive(text='will expire')
        # 模拟 TTL 过期: 手改 expires_at
        with track._lock:
            track._active_directive['expires_at'] = time.time() - 1
        d = track.get_active_directive()
        self.assertIsNone(d)
        # auto-clear: 第二次 get 仍 None
        d2 = track.get_active_directive()
        self.assertIsNone(d2)

    def test_F7_6_clear(self):
        """F7_6: clear_active_directive."""
        track = _make_fresh_track()
        track.set_thinking_brain_directive(text='to be cleared')
        self.assertTrue(track.clear_active_directive())
        self.assertIsNone(track.get_active_directive())
        # 第二次 clear (无 active) 返 False
        self.assertFalse(track.clear_active_directive())


class TestF7DaemonAction(unittest.TestCase):
    """F7_7-10: daemon _do_compose_main_brain_directive."""

    def test_F7_7_sal_gate_below_75(self):
        """F7_7: sal < 0.75 reject."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.5)
        ok, result = daemon._do_compose_main_brain_directive(
            thought, 'compose_main_brain_directive:be brief',
        )
        self.assertFalse(ok)
        self.assertIn('sal', result)
        self.assertIn('0.75', result)

    def test_F7_8_empty_text_reject(self):
        """F7_8: empty text after parse → reject."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        ok, result = daemon._do_compose_main_brain_directive(
            thought, 'compose_main_brain_directive:',
        )
        self.assertFalse(ok)
        self.assertIn('empty', result.lower() + 'short')

    def test_F7_9_success_sets_directive(self):
        """F7_9: 成功 → inner_voice_track.set_thinking_brain_directive 真调."""
        daemon = _make_daemon()
        thought = _make_thought(salience=0.85)
        fake_track = MagicMock()
        fake_track.set_thinking_brain_directive.return_value = True
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ):
            ok, result = daemon._do_compose_main_brain_directive(
                thought,
                'compose_main_brain_directive:be brief and skip health',
            )
        self.assertTrue(ok)
        self.assertIn('directive_set', result)
        fake_track.set_thinking_brain_directive.assert_called_once()
        call_args = fake_track.set_thinking_brain_directive.call_args
        self.assertIn('be brief', call_args.kwargs['text'])

    def test_F7_10_execute_actionable_dispatcher(self):
        """F7_10: _execute_actionable 真分发到 compose handler."""
        daemon = _make_daemon()
        # 注: 要 thought.thought 含 'compose' 供 EVIDENCE_LINK gate trace.
        thought = _make_thought(
            thought_text='I should compose a brief directive for next reply',
            salience=0.85,
        )
        thought.actionable = 'compose_main_brain_directive:be brief always'
        thought.evidence_link = 'compose'  # cite 'compose' 在 thought 中
        fake_track = MagicMock()
        fake_track.set_thinking_brain_directive.return_value = True
        with patch(
            'jarvis_inner_voice_track.get_inner_voice_track',
            return_value=fake_track,
        ), patch(
            'jarvis_inner_voice_track.is_enabled', return_value=True,
        ):
            ok, result = daemon._execute_actionable(thought)
        self.assertTrue(ok, f"F7_10 应成功, 实际 result={result}")
        self.assertIn('directive_set', result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
