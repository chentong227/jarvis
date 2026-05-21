# -*- coding: utf-8 -*-
"""[P5-fixCB-revise / 2026-05-21 11:45] Claim Revision Log verify.

Sir 11:30 真理: 道歉是 functional revision 不是 ritual.
真治本 = redirect 不 ban. 测试 cover:

  A. ClaimRevision dataclass + ClaimRevisionStore 持久化
  B. capture_revision_from_reply API
  C. detect_sir_querying_capability (合法 surface 触发 a)
  D. extract_keywords_from_sir + get_pending 匹配
  E. render_pending_revisions_block (Sir 召唤时 prompt block)
  F. mark_surfaced / archive_stale / reject (state transition)
  G. callback_guard publish_callback_violation 改 redirect (调 capture)
  H. capability extract from reply text (regex)
  I. central_nerve / chat_bypass 真接入
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_ClaimRevisionStore(unittest.TestCase):
    """Store 持久化."""

    def setUp(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests
        self._tmpdir = tempfile.mkdtemp()
        self._tmppath = os.path.join(self._tmpdir, 'claim_revisions.json')
        reset_default_store_for_tests(path=self._tmppath)

    def tearDown(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests
        # restore default
        reset_default_store_for_tests(path=None)
        try:
            if os.path.exists(self._tmppath):
                os.remove(self._tmppath)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_dataclass_create_persist_load(self):
        from jarvis_claim_revision_log import ClaimRevision, ClaimRevisionStore
        store = ClaimRevisionStore(path=self._tmppath)
        rev = ClaimRevision(
            id='', capability_keyword='setting a reminder',
            original_claim_excerpt='I have set the reminder', admitted_lacking_reason='no tool call made',
            captured_at=0.0, captured_iso='',
            captured_turn_id='turn_20260521_001234',
            related_keywords=['reminder', 'set'],
        )
        rid = store.add(rev)
        self.assertTrue(rid)
        self.assertTrue(os.path.exists(self._tmppath))

        # reload from disk
        store2 = ClaimRevisionStore(path=self._tmppath)
        items = store2.all_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].capability_keyword, 'setting a reminder')

    def test_capture_api(self):
        from jarvis_claim_revision_log import capture_revision_from_reply, get_default_store
        rid = capture_revision_from_reply(
            reply_excerpt='Regarding my previous claim about setting a reminder, I misspoke.',
            capability_keyword='setting a reminder',
            admitted_lacking_reason='no add_reminder tool was called',
            turn_id='turn_test',
        )
        self.assertTrue(rid)
        items = get_default_store().all_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].capability_keyword, 'setting a reminder')

    def test_get_pending_by_keywords(self):
        from jarvis_claim_revision_log import capture_revision_from_reply, get_default_store
        capture_revision_from_reply(
            reply_excerpt='', capability_keyword='setting a reminder',
            related_keywords=['reminder'],
        )
        capture_revision_from_reply(
            reply_excerpt='', capability_keyword='changing quota',
            related_keywords=['quota', 'limit'],
        )

        store = get_default_store()
        # match by keyword
        pending = store.get_pending(within_days=7.0, related_to_keywords=['reminder'])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].capability_keyword, 'setting a reminder')

        pending2 = store.get_pending(within_days=7.0, related_to_keywords=['quota'])
        self.assertEqual(len(pending2), 1)

        # no keyword = all pending
        all_pending = store.get_pending(within_days=7.0)
        self.assertEqual(len(all_pending), 2)


class TestB_SirInvitedDetect(unittest.TestCase):
    """合法 surface 触发 (a) — Sir 召唤 detect."""

    def test_english_query_capability(self):
        from jarvis_claim_revision_log import detect_sir_querying_capability
        self.assertTrue(detect_sir_querying_capability('Can you actually change the quota?'))
        self.assertTrue(detect_sir_querying_capability('Did you set the reminder?'))
        self.assertTrue(detect_sir_querying_capability('Do you have the ability to do that?'))
        self.assertTrue(detect_sir_querying_capability('you claimed earlier you could do X'))
        self.assertTrue(detect_sir_querying_capability('you lied to me'))

    def test_chinese_query_capability(self):
        from jarvis_claim_revision_log import detect_sir_querying_capability
        self.assertTrue(detect_sir_querying_capability('你能不能改这个 quota'))
        self.assertTrue(detect_sir_querying_capability('你刚才说能改 quota 是吗'))
        self.assertTrue(detect_sir_querying_capability('你撒谎了'))
        self.assertTrue(detect_sir_querying_capability('你之前是不是说过这事'))

    def test_no_query(self):
        from jarvis_claim_revision_log import detect_sir_querying_capability
        self.assertFalse(detect_sir_querying_capability('今天没去体检, 明天再去'))
        self.assertFalse(detect_sir_querying_capability('好的, ok'))
        self.assertFalse(detect_sir_querying_capability(''))

    def test_extract_keywords(self):
        from jarvis_claim_revision_log import extract_keywords_from_sir
        kws = extract_keywords_from_sir('你能不能改一下 quota 的设置', max_n=5)
        self.assertIn('quota', kws)


class TestC_RenderPendingBlock(unittest.TestCase):
    """render_pending_revisions_block — Sir 召唤时 prompt block."""

    def setUp(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests, capture_revision_from_reply
        self._tmpdir = tempfile.mkdtemp()
        self._tmppath = os.path.join(self._tmpdir, 'claim_revisions.json')
        reset_default_store_for_tests(path=self._tmppath)
        capture_revision_from_reply(
            reply_excerpt='Regarding my previous claim about quota',
            capability_keyword='changing quota',
            admitted_lacking_reason='I do not have the interface to change backend quotas',
            related_keywords=['quota', 'limit'],
        )

    def tearDown(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            if os.path.exists(self._tmppath):
                os.remove(self._tmppath)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_block_renders_when_sir_queries(self):
        from jarvis_claim_revision_log import render_pending_revisions_block
        block = render_pending_revisions_block(
            sir_utterance='Can you actually change the quota?',
            within_days=7.0,
        )
        self.assertIn('PENDING CLAIM REVISIONS', block)
        self.assertIn('changing quota', block)
        self.assertIn('do not have the interface', block)
        self.assertIn('有意义', block)

    def test_block_empty_when_sir_unrelated(self):
        from jarvis_claim_revision_log import render_pending_revisions_block
        block = render_pending_revisions_block(
            sir_utterance='今天天气怎么样',
            within_days=7.0,
        )
        # Sir 没问 quota 也没含 query 句式 → 不该显
        self.assertEqual(block, '')

    def test_block_empty_when_empty_utterance(self):
        from jarvis_claim_revision_log import render_pending_revisions_block
        self.assertEqual(render_pending_revisions_block(sir_utterance=''), '')


class TestD_StateTransitions(unittest.TestCase):
    """mark_surfaced / archive_stale / reject."""

    def setUp(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests, capture_revision_from_reply
        self._tmpdir = tempfile.mkdtemp()
        self._tmppath = os.path.join(self._tmpdir, 'claim_revisions.json')
        reset_default_store_for_tests(path=self._tmppath)
        self._rid = capture_revision_from_reply(
            reply_excerpt='', capability_keyword='setting reminder',
        )

    def tearDown(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            if os.path.exists(self._tmppath):
                os.remove(self._tmppath)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_mark_surfaced(self):
        from jarvis_claim_revision_log import get_default_store, STATUS_SURFACED
        store = get_default_store()
        ok = store.mark_surfaced(self._rid, turn_id='turn_surfaced')
        self.assertTrue(ok)
        items = store.all_items()
        # surfaced 仍在 list 但 status 改了
        match = [r for r in items if r.id == self._rid]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].status, STATUS_SURFACED)
        self.assertEqual(match[0].surfaced_turn_id, 'turn_surfaced')

    def test_reject(self):
        from jarvis_claim_revision_log import get_default_store, STATUS_REJECTED
        store = get_default_store()
        ok = store.reject(self._rid)
        self.assertTrue(ok)
        all_items = store.all_items(include_archived=True)
        rev = [r for r in all_items if r.id == self._rid][0]
        self.assertTrue(rev.rejected_by_sir)
        self.assertEqual(rev.status, STATUS_REJECTED)
        # not in pending anymore
        pending = store.get_pending(within_days=7.0)
        self.assertEqual(len(pending), 0)

    def test_archive_stale(self):
        from jarvis_claim_revision_log import get_default_store
        store = get_default_store()
        # Manipulate captured_at to 8 days ago
        for r in store._items.values():
            r.captured_at = time.time() - 8 * 86400
        n = store.archive_stale(days=7.0)
        self.assertGreaterEqual(n, 1)


class TestE_CallbackGuardRedirect(unittest.TestCase):
    """callback_guard.publish_callback_violation 改 redirect."""

    def setUp(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests
        self._tmpdir = tempfile.mkdtemp()
        self._tmppath = os.path.join(self._tmpdir, 'claim_revisions.json')
        reset_default_store_for_tests(path=self._tmppath)
        from jarvis_callback_guard import reset_vocab_cache
        reset_vocab_cache()

    def tearDown(self):
        from jarvis_claim_revision_log import reset_default_store_for_tests
        reset_default_store_for_tests(path=None)
        try:
            if os.path.exists(self._tmppath):
                os.remove(self._tmppath)
            os.rmdir(self._tmpdir)
        except Exception:
            pass

    def test_redirect_writes_to_store_not_violation(self):
        """命中 callback → 不 publish 'unsolicited_callback_detected', 而是写 ClaimRevisionLog."""
        from jarvis_callback_guard import publish_callback_violation
        from jarvis_claim_revision_log import get_default_store

        # 真案 11:23 Sir 实测
        ok = publish_callback_violation(
            hits=[{
                'phrase_id': 'regarding_my_previous_en',
                'severity': 'high',
                'match_text': 'Regarding my previous',
                'pattern': 'regarding my previous',
                'lang': 'en',
                'pos': 100,
            }],
            reply_excerpt=(
                "I see it, Sir. Regarding my previous claim about setting a parameter—"
                "I misspoke. I do not have the direct interface to adjust those backend quotas."
            ),
            sir_utterance="今天 windsurf 这个流量限制是怎么回事",
            turn_id='turn_test',
        )
        self.assertTrue(ok)

        items = get_default_store().all_items()
        self.assertEqual(len(items), 1)
        rev = items[0]
        self.assertIn('parameter', rev.capability_keyword.lower())
        # reason 应含 "do not have" (regex 提取)
        self.assertIn('do not have', rev.admitted_lacking_reason.lower())

    def test_capability_extract_chinese(self):
        from jarvis_callback_guard import _extract_capability_from_reply
        cap, reason = _extract_capability_from_reply(
            reply_text='关于我之前声称更新了日志一事, 我必须承认那并不准确',
            top_hit={'match_text': '关于我之前'},
        )
        self.assertTrue(cap, '中文 capability 应能提取')
        self.assertIn('更新', cap)


class TestF_StaticIntegrationCheck(unittest.TestCase):
    """chat_bypass + central_nerve 真接入新 redirect."""

    def test_chat_bypass_imports_callback_guard(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_callback_guard import', src)
        self.assertIn('CallbackGuard→ClaimRevision', src)

    def test_central_nerve_does_not_inject_pending_revisions(self):
        """[P5-fixCB-final / 2026-05-21 17:22 Sir 真意"全靠 watcher"] 反向断言.

        老版: central_nerve 在 Sir querying capability 时调 render_pending_revisions_block
        注入 [PENDING CLAIM REVISIONS] block. Sir 真意洞察 — 任何"老 over-claim"
        evidence 注入主脑都强化 LLM 训练本能 (RLHF 教 "看到 evidence → 道歉").

        新行为: ClaimRevisionLog 仍持久化 capture (post-stream + CLI 可看), 但
        central_nerve 不再调 render_pending_revisions_block 注入 prompt. 道歉的
        唯一合法发起方 = IntegrityWatcher publish SWM event.
        """
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # render_pending_revisions_block 调用应已删除
        self.assertNotIn('_cr_render(', src,
                          'render_pending_revisions_block 调用应已删除 '
                          '(P5-fixCB-final 真意"全靠 watcher")')


class TestG_DirectiveRevised(unittest.TestCase):
    """unsolicited_callback_guard directive 升级 revise 风格."""

    def test_directive_text_describes_two_apology_types(self):
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        target = reg.directives.get('unsolicited_callback_guard')
        self.assertIsNotNone(target)
        self.assertEqual(target.priority, 12)
        # text describes the 2 apology types (Sir 11:30 真理)
        self.assertIn('Functional revision', target.text)
        self.assertIn('Ritual self-flagellation', target.text)
        # 2 合法 surface 触发
        self.assertIn('Sir 召唤', target.text)
        self.assertIn('promise 没履行', target.text)
        # 11:23 真案
        self.assertIn('11:23', target.text)
        # source_marker upgrade
        self.assertEqual(target.source_marker, 'P0+20-P5-fixCB-revise')


if __name__ == '__main__':
    unittest.main()
