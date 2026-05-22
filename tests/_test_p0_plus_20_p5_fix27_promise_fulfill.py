# -*- coding: utf-8 -*-
"""[P5-fix27-promise-fulfill / 2026-05-22] Sir 说"做完了/不用了"
让主脑能 mark promise fulfilled/cancelled.

Sir 真痛点 (20:42):
> "为什么昨天说的今天体检, 今天还会说明天体检?
>  其实我已经说过了今天体检回来了. 为什么贾维斯会忘记?
>  是注册体检这件事的位置错了吗?"

诊断: jarvis_promise_log 已有 mark_fulfilled / mark_cancelled API, 但
1. 主脑无 FAST_CALL 工具 (无 'promises' organ)
2. 无 directive 教主脑听 Sir 说"做完了/不用了"
3. ProactiveCare 凭 stale pending promise 继续 nudge

修法:
- jarvis_chat_bypass._execute_fast_call 加 'promises' organ (fulfill/cancel/list)
- jarvis_directives.py 加 promise_completion_judge directive
- vocab 持久化 memory_pool/promise_completion_vocab.json (准则 6.5)

测试覆盖:
1. Trigger vocab (中文 + 英文)
2. promises organ FAST_CALL (id / keyword 搜)
3. fulfill / cancel / list 三个 command
4. directive 注册到 registry
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPromiseCompletionTrigger(unittest.TestCase):
    """promise_completion_judge directive trigger."""

    def test_chinese_fulfilled_phrases_fire(self):
        from jarvis_directives import _trigger_promise_completion, DirectiveContext
        for phrase in ['体检完了', '搞定了', '已经做完了', '完成了',
                          '从医院回来了', '面试完了', '弄完了']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_promise_completion(ctx),
                              f'should fire for: {phrase}')

    def test_chinese_cancelled_phrases_fire(self):
        from jarvis_directives import _trigger_promise_completion, DirectiveContext
        for phrase in ['不用了', '算了', '不去了', '没事了', '别管', '别提了']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_promise_completion(ctx),
                              f'should fire for: {phrase}')

    def test_english_phrases_fire(self):
        from jarvis_directives import _trigger_promise_completion, DirectiveContext
        for phrase in ['I am done with that', 'finished it', 'never mind',
                          'forget it', "don't bother"]:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_promise_completion(ctx),
                              f'should fire for: {phrase}')

    def test_neutral_phrases_do_not_fire(self):
        from jarvis_directives import _trigger_promise_completion, DirectiveContext
        for phrase in ['你好', 'open dashboard', '今天天气怎么样',
                          'tell me about the weather']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertFalse(_trigger_promise_completion(ctx),
                                f'should NOT fire for: {phrase}')


class TestPromiseCompletionVocabPersistence(unittest.TestCase):
    """vocab JSON 持久化 (准则 6.5)."""

    def test_seed_returns_when_no_json(self):
        from jarvis_directives import (get_promise_completion_patterns,
                                                 _SEED_PROMISE_COMPLETION_PATTERNS)
        # 默认有 seed (json 不存在或不够 fields)
        pats = get_promise_completion_patterns()
        # 应该至少有 fulfilled / cancelled keys
        self.assertIn('fulfilled', pats)
        self.assertIn('cancelled', pats)
        self.assertGreater(len(pats['fulfilled']), 5)
        self.assertGreater(len(pats['cancelled']), 3)


class TestDirectiveRegistration(unittest.TestCase):
    """directive 注册到 default registry."""

    def test_directive_registered(self):
        from jarvis_directives import get_default_registry
        r = get_default_registry()
        d = r.get('promise_completion_judge')
        self.assertIsNotNone(d)
        self.assertEqual(d.priority, 9)
        self.assertEqual(d.source_marker, 'P5-fix27-promise-fulfill')

    def test_directive_text_contains_key_examples(self):
        from jarvis_directives import get_default_registry
        r = get_default_registry()
        d = r.get('promise_completion_judge')
        self.assertIn('PROMISE COMPLETION', d.text)
        self.assertIn('promises', d.text)  # FAST_CALL organ name
        self.assertIn('fulfill', d.text)
        self.assertIn('cancel', d.text)


class TestPromisesFastCallIntegration(unittest.TestCase):
    """jarvis_promise_log API 直调 (chat_bypass FAST_CALL handler 用相同 API).

    完整集成测 (实际 organ handler) 需 chat_bypass 实例 — 太重, 这里覆盖 API
    级别的真实调用即可.
    """

    def setUp(self):
        from jarvis_promise_log import (PromiseExecutionLog, get_default_log)
        # use default log for end-to-end test
        self.log = get_default_log()

    def test_register_fulfill_roundtrip(self):
        """register 一个 promise → mark_fulfilled → state=fulfilled."""
        pid = self.log.register(
            description='[testcase] 我会去体检',
            kind='soft',
            jarvis_reply='I shall remember',
            turn_id='turn_test_fix27_a',
            author='sir',
        )
        self.assertTrue(pid.startswith('p_'))
        # initial state
        self.assertEqual(self.log.promises[pid].state, 'pending')
        # mark fulfilled
        ok = self.log.mark_fulfilled(
            pid, evidence_kind='sir_voice',
            evidence_what='Sir said 体检完了')
        self.assertTrue(ok)
        self.assertEqual(self.log.promises[pid].state, 'fulfilled')

    def test_register_cancel_roundtrip(self):
        pid = self.log.register(
            description='[testcase] 我会去面试',
            kind='soft',
            jarvis_reply='',
            turn_id='turn_test_fix27_b',
            author='sir',
        )
        ok = self.log.mark_cancelled(pid, reason='[testcase] sir cancelled')
        self.assertTrue(ok)
        self.assertEqual(self.log.promises[pid].state, 'cancelled')

    def test_mark_fulfilled_returns_false_for_already_fulfilled(self):
        pid = self.log.register(
            description='[testcase] 我会健身',
            kind='soft',
            jarvis_reply='', turn_id='turn_test_fix27_c', author='sir')
        self.log.mark_fulfilled(pid, evidence_kind='test', evidence_what='ok')
        # second mark fails
        ok = self.log.mark_fulfilled(pid, evidence_kind='test',
                                              evidence_what='again')
        self.assertFalse(ok)

    def test_keyword_search_finds_pending(self):
        """模糊 keyword 搜 — 主脑可能不记 promise_id."""
        pid = self.log.register(
            description='[testcase] 我会安排明天的全身体检',
            kind='soft',
            jarvis_reply='', turn_id='turn_test_fix27_d', author='sir')
        # search by '体检'
        kw_low = '体检'
        found = None
        for _pid, _p in self.log.promises.items():
            if _p.state != 'pending':
                continue
            blob = ((_p.description or '') + ' ' +
                      (_p.jarvis_reply or '') + ' ' +
                      (getattr(_p, 'source_text', '') or '')).lower()
            if kw_low in blob:
                found = _pid
                break
        self.assertEqual(found, pid)
        # cleanup
        self.log.mark_cancelled(pid, reason='[testcase cleanup]')


if __name__ == '__main__':
    unittest.main()
