# -*- coding: utf-8 -*-
"""[P5-fixCB / 2026-05-21 10:30] Unsolicited Callback Guard verify.

Sir 5+ 次真测痛点 (10:06/10:08 重启后 + 22:04/22:19/23:02/23:43/23:49):
主脑 unsolicited callback 老账道歉 (Sir 当前 turn 完全没问).
PreFlight async 治不了当前轮. 真治本两层:
  C. directive unsolicited_callback_guard (priority 12)
  B. 本模块 vocab regex scan + SWM publish + STM forbidden block

Cover:
  A. vocab JSON load + active filter
  B. scan_for_unsolicited_callback regex 命中 Sir 真测 phrase
  C. _sir_invited_callback (Sir 主动 callback 时不算违规)
  D. publish_callback_violation 写 SWM
  E. render_forbidden_block_for_prompt
  F. directive unsolicited_callback_guard registered
  G. chat_bypass + central_nerve wire 静态 check
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_VocabLoad(unittest.TestCase):
    """forbidden_callback_vocab.json 真存在 + 含 active phrase."""

    def setUp(self):
        from jarvis_callback_guard import reset_vocab_cache
        reset_vocab_cache()

    def test_vocab_file_exists(self):
        from jarvis_callback_guard import DEFAULT_VOCAB_PATH
        self.assertTrue(os.path.exists(DEFAULT_VOCAB_PATH),
                          f'vocab 文件不存在: {DEFAULT_VOCAB_PATH}')

    def test_vocab_loads_compiled_patterns(self):
        from jarvis_callback_guard import _load_vocab
        compiled = _load_vocab()
        self.assertGreater(len(compiled), 0, '应有 active phrase compiled')


class TestB_ScanCatchesRealSirCases(unittest.TestCase):
    """scan_for_unsolicited_callback 真命中 Sir 5+ 次反复看到的 callback phrase."""

    def setUp(self):
        from jarvis_callback_guard import reset_vocab_cache
        reset_vocab_cache()

    def test_sir_10_06_real_case_caught(self):
        """Sir 10:06 真测: 'Regarding my previous claim of updating the logs, I must admit that was inaccurate'"""
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = (
            "Understood, Sir. I've noted the postponement. Regarding my previous claim "
            "of updating the logs, I must admit that was inaccurate; no such update was performed."
        )
        sir = "今天没有去体检, 今天时间也来不及了, 明天早上再去"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertGreater(len(hits), 0, '应命中 unsolicited callback')
        phrase_ids = {h['phrase_id'] for h in hits}
        self.assertIn('regarding_my_previous_en', phrase_ids)
        self.assertIn('i_must_admit_en', phrase_ids)

    def test_sir_10_08_real_case_caught(self):
        """Sir 10:08 真测: 'Regarding my previous claim of setting a reminder...'"""
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = (
            "I'll remain on standby, Sir. Regarding my previous claim of setting a "
            "reminder, it appears the database rejected the entry. I'll need to look into that."
        )
        sir = "好的, ok"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertGreater(len(hits), 0)
        phrase_ids = {h['phrase_id'] for h in hits}
        self.assertIn('regarding_my_previous_en', phrase_ids)

    def test_sir_zh_subtitle_case_caught(self):
        """Sir 10:06 中文字幕: '关于我之前声称更新了 X 一事, 我必须承认...'"""
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = (
            "明白了, 先生. 关于我之前声称更新了日志一事, 我必须承认那并不准确, 我当时并未执行该操作."
        )
        sir = "今天没去体检"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertGreater(len(hits), 0)
        phrase_ids = {h['phrase_id'] for h in hits}
        # 中文 phrase_id 应命中
        self.assertTrue(
            any(pid in phrase_ids for pid in ('guanyu_qianmian_zh', 'wo_bixu_chengren_zh')),
            f'应命中中文 callback phrase, 实际命中: {phrase_ids}'
        )

    def test_clean_reply_no_hit(self):
        """正常回复不命中."""
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = "Understood, Sir. Tomorrow morning at 7 then. Shall I set a reminder?"
        sir = "今天没去体检, 明天再去"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertEqual(len(hits), 0)


class TestC_SirInvitedCallbackExempt(unittest.TestCase):
    """Sir 主动 callback 时, scan 应放过 (solicited callback 不违规)."""

    def setUp(self):
        from jarvis_callback_guard import reset_vocab_cache
        reset_vocab_cache()

    def test_sir_explicitly_invites_callback(self):
        """Sir 'you said earlier' 类 → callback solicited, 不算违规."""
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = "Regarding my previous claim of updating logs, that was inaccurate."
        sir = "wait, you said earlier that you updated the logs?"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertEqual(len(hits), 0, 'Sir 主动 callback → solicited, scan 应放过')

    def test_sir_zh_invites_callback(self):
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = "关于我之前声称的事, 确实没做."
        sir = "你刚才说更新了日志? 真的吗?"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertEqual(len(hits), 0)

    def test_sir_calls_out_lying(self):
        """Sir 'you lied' → 召唤老账道歉, 不算违规."""
        from jarvis_callback_guard import scan_for_unsolicited_callback
        reply = "I must admit, Sir, that was wrong of me."
        sir = "you lied to me earlier"
        hits = scan_for_unsolicited_callback(reply, sir)
        self.assertEqual(len(hits), 0)


class TestD_PublishCallbackViolation(unittest.TestCase):
    """publish_callback_violation 写 SWM event."""

    def test_redirect_writes_to_store_even_no_bus(self):
        """P5-fixCB-revise: publish_callback_violation 现在 redirect 到 ClaimRevisionLog,
        即使 bus None 也能写 store. 仅 ClaimRevisionLog import 失败 fallback 才走 bus 路径.
        这是预期 — redirect 不全靠 bus."""
        import os, tempfile
        from jarvis_callback_guard import publish_callback_violation
        from jarvis_claim_revision_log import reset_default_store_for_tests, get_default_store
        # Redirect store to tmp to isolate
        tmpdir = tempfile.mkdtemp()
        tmppath = os.path.join(tmpdir, 'cr.json')
        reset_default_store_for_tests(path=tmppath)
        try:
            ok = publish_callback_violation(
                hits=[{'phrase_id': 'x', 'severity': 'high', 'match_text': 'X',
                       'pattern': '', 'lang': 'en', 'pos': 0}],
                reply_excerpt='Regarding my previous claim about Y, I do not have the X interface',
                sir_utterance='', turn_id='t1',
            )
            self.assertTrue(ok)
            items = get_default_store().all_items()
            self.assertEqual(len(items), 1)
        finally:
            reset_default_store_for_tests(path=None)
            try:
                os.remove(tmppath); os.rmdir(tmpdir)
            except Exception:
                pass

    def test_redirect_publishes_claim_revision_captured(self):
        """P5-fixCB-revise: redirect publish 'claim_revision_captured' (not 'violation')."""
        import os, tempfile
        from jarvis_callback_guard import publish_callback_violation
        from jarvis_claim_revision_log import reset_default_store_for_tests
        tmpdir = tempfile.mkdtemp()
        tmppath = os.path.join(tmpdir, 'cr.json')
        reset_default_store_for_tests(path=tmppath)
        try:
            from unittest.mock import patch, MagicMock
            mock_bus = MagicMock()
            with patch('jarvis_utils.get_event_bus') as _mock:
                _mock.return_value = mock_bus
                ok = publish_callback_violation(
                    hits=[
                        {'phrase_id': 'x', 'severity': 'high', 'match_text': 'X',
                         'pattern': '', 'lang': 'en', 'pos': 0},
                    ],
                    reply_excerpt='Regarding my previous claim of X, I do not have the Y',
                    sir_utterance='sir said', turn_id='t1',
                )
                self.assertTrue(ok)
                # publish called via capture_revision_from_reply
                self.assertTrue(mock_bus.publish.called)
                # etype should be 'claim_revision_captured' (info, not violation)
                kwargs = mock_bus.publish.call_args.kwargs
                self.assertEqual(kwargs['etype'], 'claim_revision_captured')
                self.assertEqual(kwargs['source'], 'ClaimRevisionLog')
                # salience info-level (lower than 0.7)
                self.assertLess(kwargs['salience'], 0.7)
        finally:
            reset_default_store_for_tests(path=None)
            try:
                os.remove(tmppath); os.rmdir(tmpdir)
            except Exception:
                pass

    def test_no_hits_no_publish(self):
        from jarvis_callback_guard import publish_callback_violation
        ok = publish_callback_violation([], 'r', 's', 't')
        self.assertFalse(ok)


class TestE_RenderForbiddenBlock(unittest.TestCase):
    """render_forbidden_block_for_prompt 渲染 SWM event 成 prompt block."""

    def test_no_recent_event_empty_block(self):
        from jarvis_callback_guard import render_forbidden_block_for_prompt
        from unittest.mock import patch, MagicMock
        mock_bus = MagicMock()
        mock_bus.top_n.return_value = []
        with patch('jarvis_utils.get_event_bus') as _mock:
            _mock.return_value = mock_bus
            block = render_forbidden_block_for_prompt(within_seconds=900.0)
            self.assertEqual(block, '')

    def test_recent_event_renders(self):
        """P5-fixCB-revise: block 现在说 redirect 不说 ban."""
        from jarvis_callback_guard import render_forbidden_block_for_prompt
        from unittest.mock import patch, MagicMock
        fake_events = [{
            'type': 'claim_revision_captured',
            '_age_s': 100,
            'metadata': {
                'capability_keyword': 'changing quota',
                'top_match_text': 'regarding my previous',
                'revision_id': 'rev123',
                'hits_n': 1,
            },
        }]
        mock_bus = MagicMock()
        mock_bus.top_n.return_value = fake_events
        with patch('jarvis_utils.get_event_bus') as _mock:
            _mock.return_value = mock_bus
            block = render_forbidden_block_for_prompt(within_seconds=900.0)
            # 新风格字眼
            self.assertIn('CLAIM REVISION CAPTURED', block)
            self.assertIn('redirect', block.lower())
            # 应只采 capability_keyword
            self.assertIn('changing quota', block)
            # 不再含 ban 风格 提示
            self.assertNotIn('priority 12', block)


class TestF_DirectiveRegistered(unittest.TestCase):
    """unsolicited_callback_guard directive registered (priority 12)."""

    def test_directive_in_seed(self):
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        ids = {d.id for d in reg.directives.values()}
        self.assertIn('unsolicited_callback_guard', ids)

    def test_directive_priority_12(self):
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        target = reg.directives.get('unsolicited_callback_guard')
        self.assertIsNotNone(target)
        self.assertEqual(target.priority, 12)

    def test_directive_text_revise_describes_redirect(self):
        """P5-fixCB-revise: 不再 ban 风格, 说 redirect."""
        from jarvis_directives import DirectiveRegistry, _bootstrap_seed_only
        reg = DirectiveRegistry()
        _bootstrap_seed_only(reg)
        target = reg.directives.get('unsolicited_callback_guard')
        # 含合法 surface 触发论述
        self.assertIn('Functional revision', target.text)
        self.assertIn('Sir 召唤', target.text)
        # 11:23 Sir 真测案改写
        self.assertIn('11:23', target.text)
        # 原不合法句式仍举例
        self.assertIn('Regarding my previous', target.text)
        # source_marker 升级
        self.assertEqual(target.source_marker, 'P0+20-P5-fixCB-revise')


class TestG_StaticIntegrationCheck(unittest.TestCase):
    """chat_bypass + central_nerve 真接入 callback_guard."""

    def test_chat_bypass_imports_callback_guard(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_callback_guard import', src)
        self.assertIn('scan_for_unsolicited_callback', src)
        self.assertIn('publish_callback_violation', src)

    def test_central_nerve_imports_render_block(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('render_forbidden_block_for_prompt', src)


if __name__ == '__main__':
    unittest.main()
