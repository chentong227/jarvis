# -*- coding: utf-8 -*-
"""[P5-fix82 / 2026-05-23] Completion Cascade + Gatekeeper Skip regression.

Sir 真意 (2026-05-23 22:14): "我教过的东西除非我重新修正不然不用改, 以后都按这个".

修法:
  fix82-X: MemoryGateway.update_sir_field 末尾 _maybe_cascade_completion
           - 检测 new_value 含完成 vocab → 抽 noun keyword
           - CommitmentWatcher.cancel_by_keyword (24h 窗口)
           - Hippocampus.add_completed_event 写 TaskMemories 'Completed:%'
           - publish SWM 'completion_cascaded'
           - vocab 持久化 memory_pool/completion_event_vocab.json (准则 6)
  fix82-X-2: Hippocampus.list_recent_completed_events 抽近 7 天 → prompt block
  fix82-Z: chat_bypass detect dup add_reminder (Gatekeeper 已注册 10s 内) → skip
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(rel):
    p = os.path.join(ROOT, rel)
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


class TestFix82XCompletionCascade(unittest.TestCase):
    """fix82-X: cascade_completion in MemoryGateway."""

    def test_marker_present(self):
        # [Reshape M2.C.3 / 2026-05-24] file 已 git mv → jarvis_memory_hub.py,
        # jarvis_memory_gateway.py 是 backward-compat 转发垫层.
        src = _read('jarvis_memory_hub.py')
        self.assertIn('P5-fix82-X', src,
                      'fix82-X: marker 在 jarvis_memory_hub.py (M2.C.3 后)')

    def test_cascade_method_exists(self):
        src = _read('jarvis_memory_hub.py')
        self.assertIn('_maybe_cascade_completion', src,
                      'fix82-X: _maybe_cascade_completion 方法应存在')
        self.assertIn('_load_completion_vocab', src,
                      'fix82-X: _load_completion_vocab 方法应存在')

    def test_completion_vocab_seed(self):
        """vocab 持久化 + 准则 6 seed defaults"""
        from jarvis_memory_gateway import MemoryMutationGateway
        g = MemoryMutationGateway()
        v = g._load_completion_vocab()
        self.assertIsInstance(v, dict)
        self.assertIn('completion_keywords', v)
        self.assertIn('noun_extract_keywords', v)
        # seed 包含基础 keywords
        for kw in ('已完成', '去过了', 'completed', 'done'):
            self.assertIn(kw, v['completion_keywords'])
        # 文件持久化
        vocab_path = os.path.join(ROOT, 'memory_pool', 'completion_event_vocab.json')
        self.assertTrue(os.path.exists(vocab_path),
                        f'fix82-X: vocab 应持久化 {vocab_path}')

    def test_cw_cancel_called_in_cascade(self):
        src = _read('jarvis_memory_hub.py')
        self.assertIn('cancel_by_keyword', src,
                      'fix82-X: cascade 应调 cancel_by_keyword')
        self.assertIn('max_age_seconds=86400', src,
                      'fix82-X: cancel 应给 24h 窗口')

    def test_publish_completion_cascaded(self):
        src = _read('jarvis_memory_hub.py')
        self.assertIn("'completion_cascaded'", src,
                      'fix82-X: publish completion_cascaded SWM event')

    def test_add_completed_event_call(self):
        src = _read('jarvis_memory_hub.py')
        self.assertIn('add_completed_event', src,
                      'fix82-X: cascade 应调 hippocampus.add_completed_event')


class TestFix82XHippocampusAPI(unittest.TestCase):
    """fix82-X: Hippocampus add_completed_event + list_recent_completed_events."""

    def test_add_completed_event_method(self):
        src = _read('jarvis_hippocampus.py')
        self.assertIn('def add_completed_event', src,
                      'fix82-X: add_completed_event 方法应存在')

    def test_list_recent_completed_events_method(self):
        src = _read('jarvis_hippocampus.py')
        self.assertIn('def list_recent_completed_events', src,
                      'fix82-X: list_recent_completed_events 方法应存在')
        self.assertIn("'Completed:%'", src,
                      'fix82-X: LIKE pattern 应捕 Completed:')

    def test_e2e_add_then_list(self):
        """实测: add 一条 → list 抽到"""
        import jarvis_hippocampus as hp
        h = hp.Hippocampus()
        rid = h.add_completed_event(
            'fix82-X test event blood pressure',
            keywords=['test', 'blood pressure'],
            source='unit_test',
        )
        self.assertGreater(rid, 0, 'add 应返 rowid > 0')
        events = h.list_recent_completed_events(days_back=1, max_n=20)
        # 至少含我们刚才 add 的
        hit = any(
            'fix82-X test event' in (e.get('intent') or '')
            for e in events
        )
        self.assertTrue(hit, 'list 应能 hit 刚 add 的事件')


class TestFix82XPromptBlock(unittest.TestCase):
    """fix82-X step 2: [RECENT COMPLETED] prompt block in _assemble_prompt."""

    def test_marker_present(self):
        src = _read('jarvis_central_nerve.py')
        self.assertIn('P5-fix82-X step 2', src,
                      'fix82-X step 2: marker 在 jarvis_central_nerve.py')

    def test_recent_completed_block_render(self):
        src = _read('jarvis_central_nerve.py')
        self.assertIn('[RECENT COMPLETED', src,
                      'fix82-X step 2: prompt block label 应存在')
        self.assertIn('list_recent_completed_events', src,
                      'fix82-X step 2: 应调 hippocampus.list_recent_completed_events')


class TestFix82ZGatekeeperSkip(unittest.TestCase):
    """fix82-Z: chat_bypass skip dup add_reminder when Gatekeeper just registered."""

    def test_marker_present(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('P5-fix82-Z', src,
                      'fix82-Z: marker 在 jarvis_chat_bypass.py')

    def test_check_swm_for_gatekeeper_event(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn("'sir_intent_deadline_candidate'", src,
                      'fix82-Z: 应查 sir_intent_deadline_candidate SWM event')
        self.assertIn('within_seconds=10', src,
                      'fix82-Z: 10s 窗口检查最近 Gatekeeper 注册')

    def test_skip_only_for_add_reminder(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn("command == 'add_reminder'", src,
                      'fix82-Z: 仅 skip add_reminder cmd, 不影响其他')

    def test_fake_success_not_failure(self):
        """skip 时构造 fake success ExecutionResult, 不触发熔断."""
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('ExecutionResult(success=True', src,
                      'fix82-Z: skip 时 fake success, 不算 fail')


if __name__ == '__main__':
    unittest.main()
