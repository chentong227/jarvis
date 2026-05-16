# -*- coding: utf-8 -*-
"""[轴3-L3.2 / 2026-05-15] PromiseExecutor + PlanLedger step 字段扩展 — 测试套件

覆盖：
  TestPromiseDraftStepArgs        — PromiseParser 解析 args 字段（向后兼容）
  TestPlanLedgerStepFields        — PlanLedger._normalize_step 保留 skill/args/retry/last_error
  TestPlanLedgerToPromptBlock     — to_prompt_block 渲染 paused 子原因 / skill / result / error
  TestSplitSkill                  — PromiseExecutor._split_skill 工具方法
  TestClassifyMsgSuccess          — fast_call 返回字符串的成功/失败判定
  TestPromiseExecutorBasic        — 创建 / start / stop / tick_once
  TestPromiseExecutorRunsSteps    — 单步 / 多步 / 反推 result / args 透传
  TestPromiseExecutorSkipNonRun   — 非 RUNNING plan 不被跑
  TestPromiseExecutorKPI          — record_invocation 被喂回
  TestRESUMETag                   — RESUME_PLAN 标签抽取 + has_any_tag
  TestNerveIntegrationContract    — 源码契约：CentralNerve 创建 + JarvisWorker 注入 + stream_chat RESUME 解析

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l3_2_executor.py
"""
import os
import sys
import time
import threading
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry, SkillManifest, get_registry,
    DANGER_SAFE, DANGER_RISKY, DANGER_DANGEROUS,
    PromiseParser, PromiseDraft,
    PromiseActivator,
    PromiseExecutor,
    ACTIVATE_TAG_RE, CANCEL_TAG_RE, RESUME_TAG_RE,
    EXEC_PREFIX_FAILURE, TRANSIENT_META_KEYS,
)
from jarvis_utils import PlanLedger
import tempfile
import json


def _make_skill(command='audio_hands.set_volume', danger=DANGER_RISKY,
                description='set audio volume'):
    return SkillManifest(
        command=command, module='m', callable_name='c',
        description=description, dangerous_flag=danger,
    )


def _new_ledger(tmp=None):
    """创建一个临时 PlanLedger，避开默认 memory_pool/plans.json 写入。"""
    if tmp is None:
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name
    return PlanLedger(persist_path=tmp, autosave=False, max_active=10)


# ==========================================================================
# 1. PromiseParser 解析 args（向后兼容）
# ==========================================================================

class TestPromiseDraftStepArgs(unittest.TestCase):

    def test_step_with_args_parsed(self):
        text = ('<PROMISE>{"goal": "set vol", '
                '"steps": [{"description": "set", "skill": "audio_hands.set_volume", '
                '"args": {"level": 30}}]}</PROMISE>')
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].steps[0]['args'], {'level': 30})

    def test_step_without_args_defaults_empty_dict(self):
        text = ('<PROMISE>{"goal": "g", '
                '"steps": [{"description": "do it", "skill": "x.y"}]}</PROMISE>')
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(drafts[0].steps[0]['args'], {})

    def test_args_not_dict_falls_back_to_empty(self):
        # LLM 错把 args 写成 list → 视为空 dict（不抛）
        text = ('<PROMISE>{"goal": "g", '
                '"steps": [{"description": "do", "skill": "x.y", "args": [1,2]}]}</PROMISE>')
        drafts = PromiseParser.extract_all(text)
        self.assertEqual(drafts[0].steps[0]['args'], {})

    def test_args_with_too_many_keys_truncated(self):
        # 超过 20 个 key 自动截
        big = {f'k{i}': i for i in range(50)}
        text = ('<PROMISE>{"goal": "g", '
                '"steps": [{"description": "d", "skill": "x.y", "args": '
                + json.dumps(big) + '}]}</PROMISE>')
        drafts = PromiseParser.extract_all(text)
        self.assertLessEqual(len(drafts[0].steps[0]['args']), 20)


# ==========================================================================
# 2. PlanLedger._normalize_step 字段扩展
# ==========================================================================

class TestPlanLedgerStepFields(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()

    def test_normalize_step_dict_keeps_skill_args(self):
        step_in = {'description': 'do', 'skill': 'audio.set', 'args': {'level': 30}}
        out = self.ledger._normalize_step(step_in)
        self.assertEqual(out['skill'], 'audio.set')
        self.assertEqual(out['args'], {'level': 30})
        self.assertEqual(out['retry_count'], 0)
        self.assertIsNone(out['last_error'])

    def test_normalize_step_str_input_has_defaults(self):
        out = self.ledger._normalize_step('just a description')
        self.assertEqual(out['skill'], None)
        self.assertEqual(out['args'], {})
        self.assertEqual(out['retry_count'], 0)
        self.assertEqual(out['status'], 'pending')

    def test_draft_with_skill_args_preserved(self):
        plan_id = self.ledger.draft(
            goal='g',
            steps=[{'description': 'd1', 'skill': 'audio.set',
                    'args': {'level': 30}, 'status': 'pending', 'retry_count': 0}],
        )
        plan = self.ledger.get(plan_id)
        self.assertEqual(plan['steps'][0]['skill'], 'audio.set')
        self.assertEqual(plan['steps'][0]['args'], {'level': 30})


# ==========================================================================
# 3. to_prompt_block 渲染加强（paused 子原因 + skill + result + error）
# ==========================================================================

class TestPlanLedgerToPromptBlock(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()

    def test_paused_for_clarification_rendered(self):
        plan_id = self.ledger.draft(goal='g',
            steps=[{'description': 'd', 'skill': 'x.y', 'args': {}}],
            metadata={'paused_for_clarification': True,
                      'failed_step_idx': 0,
                      'failed_step_error': 'permission denied'})
        # 推到 RUNNING 然后 PAUSED
        self.ledger.set_state(plan_id, PlanLedger.STATE_RUNNING)
        self.ledger.set_state(plan_id, PlanLedger.STATE_PAUSED)
        block = self.ledger.to_prompt_block()
        self.assertIn('paused', block)
        self.assertIn('permission denied', block)

    def test_paused_for_dangerous_confirm_rendered(self):
        plan_id = self.ledger.draft(goal='g',
            steps=[{'description': 'd'}],
            metadata={'paused_for_dangerous_confirm': True,
                      'dangerous_skills': ['file.delete']})
        self.ledger.set_state(plan_id, PlanLedger.STATE_RUNNING)
        self.ledger.set_state(plan_id, PlanLedger.STATE_PAUSED)
        block = self.ledger.to_prompt_block()
        self.assertIn('dangerous_confirm', block)
        self.assertIn('file.delete', block)

    def test_done_step_result_rendered(self):
        plan_id = self.ledger.draft(goal='g',
            steps=[{'description': 'd1', 'skill': 'audio.set', 'args': {}}])
        self.ledger.set_state(plan_id, PlanLedger.STATE_RUNNING)
        self.ledger.advance_step(plan_id, 0, 'done', result='✅ all good')
        block = self.ledger.to_prompt_block()
        self.assertIn('audio.set', block)
        self.assertIn('all good', block)


# ==========================================================================
# 4. PromiseExecutor 工具方法
# ==========================================================================

class TestSplitSkill(unittest.TestCase):

    def test_basic_split(self):
        self.assertEqual(PromiseExecutor._split_skill('audio_hands.set_volume'),
                         ('audio_hands', 'set_volume'))

    def test_no_dot_returns_none(self):
        self.assertEqual(PromiseExecutor._split_skill('badname'), (None, None))

    def test_empty_returns_none(self):
        self.assertEqual(PromiseExecutor._split_skill(''), (None, None))
        self.assertEqual(PromiseExecutor._split_skill(None), (None, None))


class TestClassifyMsgSuccess(unittest.TestCase):

    def test_check_emoji_is_success(self):
        self.assertTrue(PromiseExecutor._classify_msg_success('✅ done'))

    def test_cross_emoji_is_failure(self):
        self.assertFalse(PromiseExecutor._classify_msg_success('❌ failed'))

    def test_error_prefix_is_failure(self):
        self.assertFalse(PromiseExecutor._classify_msg_success('Error: boom'))

    def test_warning_prefix_is_failure(self):
        self.assertFalse(PromiseExecutor._classify_msg_success('⚠️ degraded'))

    def test_empty_string_is_success(self):
        # 无返回值的工具兜底视为成功
        self.assertTrue(PromiseExecutor._classify_msg_success(''))

    def test_plain_text_is_success(self):
        self.assertTrue(PromiseExecutor._classify_msg_success('volume set to 30'))


# ==========================================================================
# 5. PromiseExecutor 生命周期
# ==========================================================================

class TestPromiseExecutorBasic(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_creation_requires_ledger(self):
        with self.assertRaises(ValueError):
            PromiseExecutor(plan_ledger=None)

    def test_creation_with_ledger_ok(self):
        ex = PromiseExecutor(plan_ledger=self.ledger)
        self.assertFalse(ex.is_running())

    def test_start_stop(self):
        ex = PromiseExecutor(plan_ledger=self.ledger, tick_s=0.05)
        ex.start()
        time.sleep(0.15)
        self.assertTrue(ex.is_running())
        ex.stop()
        self.assertFalse(ex.is_running())

    def test_double_start_idempotent(self):
        ex = PromiseExecutor(plan_ledger=self.ledger, tick_s=0.05)
        ex.start()
        t1 = ex._thread
        ex.start()
        t2 = ex._thread
        self.assertIs(t1, t2)
        ex.stop()


# ==========================================================================
# 6. PromiseExecutor 步骤执行 + 反推
# ==========================================================================

class TestPromiseExecutorRunsSteps(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()
        self.registry.register(_make_skill('audio_hands.set_volume', DANGER_RISKY))
        self.calls = []
        self.fake_fast_call = lambda o, c, a: (
            self.calls.append((o, c, dict(a))) or
            f"✅ {o}.{c}: ok"
        )
        self.ex = PromiseExecutor(
            plan_ledger=self.ledger,
            skill_registry=self.registry,
            fast_call_executor=self.fake_fast_call,
            say_to_sir=None,  # 测试时不真说话
            tick_s=0.05,
        )

    def _draft_and_run(self, steps, dangerous_confirmed=True):
        meta = {}
        if dangerous_confirmed:
            meta['dangerous_confirmed'] = True
        plan_id = self.ledger.draft(goal='g', steps=steps, metadata=meta)
        # awaiting_go → running
        self.ledger.set_state(plan_id, PlanLedger.STATE_RUNNING, reason='test')
        return plan_id

    def test_single_step_plan_completes(self):
        pid = self._draft_and_run([
            {'description': 'set vol 30', 'skill': 'audio_hands.set_volume',
             'args': {'level': 30}}
        ])
        # 跑足够多次 tick 让 step 完成 + plan 收尾
        for _ in range(3):
            self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_DONE)
        self.assertEqual(plan['steps'][0]['status'], 'done')
        # args 正确透传
        self.assertEqual(self.calls[0], ('audio_hands', 'set_volume', {'level': 30}))

    def test_multi_step_plan_in_order(self):
        # 多步：步 1 调 audio.set，步 2 描述性（skill=None），步 3 再调 audio.set
        self.registry.register(_make_skill('audio_hands.list_devices', DANGER_SAFE))
        pid = self._draft_and_run([
            {'description': 's1', 'skill': 'audio_hands.list_devices', 'args': {}},
            {'description': 's2 summary', 'skill': None, 'args': {}},
            {'description': 's3', 'skill': 'audio_hands.set_volume', 'args': {'level': 50}},
        ])
        for _ in range(6):
            self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_DONE)
        for s in plan['steps']:
            self.assertEqual(s['status'], 'done')
        # 顺序：先 list_devices，再 set_volume（step 2 跳过工具）
        self.assertEqual(self.calls[0][1], 'list_devices')
        self.assertEqual(self.calls[1][1], 'set_volume')
        # step 2 (skill=None) 也写了 result
        self.assertIn('描述性', plan['steps'][1].get('result', ''))

    def test_no_skill_step_marked_done_immediately(self):
        pid = self._draft_and_run([
            {'description': 'just thinking', 'skill': None, 'args': {}}
        ])
        self.ex.tick_once()
        self.ex.tick_once()  # 收尾
        plan = self.ledger.get(pid)
        self.assertEqual(plan['steps'][0]['status'], 'done')
        # fast_call 没被调（无 skill）
        self.assertEqual(len(self.calls), 0)

    def test_invalid_skill_name_treated_as_failure(self):
        pid = self._draft_and_run([
            {'description': 's', 'skill': 'no_dot_here', 'args': {}}
        ])
        # 第一次失败 → retry pending；第二次失败 → PAUSE
        for _ in range(4):
            self.ex.tick_once()
        plan = self.ledger.get(pid)
        # step 应该被标 failed + plan PAUSED
        self.assertEqual(plan['state'], PlanLedger.STATE_PAUSED)
        self.assertEqual(plan['steps'][0]['status'], 'failed')

    def test_step_result_recorded_for_main_brain_review(self):
        pid = self._draft_and_run([
            {'description': 's1', 'skill': 'audio_hands.set_volume',
             'args': {'level': 25}}
        ])
        for _ in range(3):
            self.ex.tick_once()
        plan = self.ledger.get(pid)
        # result 应该含 fast_call 返回的成功字符串
        self.assertIn('audio_hands.set_volume', plan['steps'][0].get('result', ''))


# ==========================================================================
# 7. PromiseExecutor 跳过非 RUNNING plan
# ==========================================================================

class TestPromiseExecutorSkipNonRunning(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()
        self.calls = []
        self.ex = PromiseExecutor(
            plan_ledger=self.ledger,
            fast_call_executor=lambda o, c, a: self.calls.append(1) or "✅ ok",
            tick_s=0.05,
        )

    def test_awaiting_go_plan_not_executed(self):
        # 只 draft → awaiting_go，不推 RUNNING
        self.ledger.draft(goal='g', steps=[{'description': 'd', 'skill': 'x.y'}])
        for _ in range(3):
            self.ex.tick_once()
        self.assertEqual(len(self.calls), 0)

    def test_cancelled_plan_not_executed(self):
        pid = self.ledger.draft(goal='g', steps=[{'description': 'd', 'skill': 'x.y'}])
        self.ledger.set_state(pid, PlanLedger.STATE_CANCELLED, reason='test')
        for _ in range(3):
            self.ex.tick_once()
        self.assertEqual(len(self.calls), 0)


# ==========================================================================
# 8. PromiseExecutor KPI 喂回
# ==========================================================================

class TestPromiseExecutorKPI(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()
        self.registry.register(_make_skill('x.y', DANGER_SAFE))
        self.ledger = _new_ledger()
        self.ex = PromiseExecutor(
            plan_ledger=self.ledger,
            skill_registry=self.registry,
            fast_call_executor=lambda o, c, a: "✅ ok",
            tick_s=0.05,
        )

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_record_invocation_called_on_success(self):
        pid = self.ledger.draft(goal='g',
            steps=[{'description': 'd', 'skill': 'x.y', 'args': {}}])
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        for _ in range(3):
            self.ex.tick_once()
        sk = self.registry.get('x.y')
        self.assertGreaterEqual(sk.call_count_30d, 1)
        self.assertEqual(sk.last_30d_success_rate, 1.0)


# ==========================================================================
# 9. RESUME_PLAN 标签
# ==========================================================================

class TestRESUMETag(unittest.TestCase):

    def test_resume_tag_extracted(self):
        text = 'Some text <RESUME_PLAN>abc12345</RESUME_PLAN> ok'
        ids = PromiseActivator.extract_resume_ids(text)
        self.assertEqual(ids, ['abc12345'])

    def test_has_any_tag_includes_resume(self):
        text = 'tail <RESUME_PLAN>x</RESUME_PLAN>'
        self.assertTrue(PromiseActivator.has_any_tag(text))

    def test_resume_no_tag_returns_empty(self):
        self.assertEqual(PromiseActivator.extract_resume_ids('nothing here'), [])


# ==========================================================================
# 10. 源码契约：CentralNerve 创建 + JarvisWorker 注入 + stream_chat RESUME
# ==========================================================================

class TestNerveIntegrationContract(unittest.TestCase):
    """读 jarvis_nerve.py 源码字符串确认接入。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_central_nerve_creates_promise_executor(self):
        self.assertIn('PromiseExecutor(', self.src,
            'CentralNerve.__init__ 必须创建 PromiseExecutor')
        self.assertIn('self.promise_executor', self.src,
            'PromiseExecutor 必须存到 self.promise_executor')

    def test_jarvis_worker_wires_callbacks_and_starts(self):
        # _fast_call / _say 注入 + .start()
        import re
        m = re.search(
            r'_exec\._fast_call.*?_exec\._say.*?_exec\.start\(\)',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'JarvisWorker 必须注入 fast_call/say 后调 PromiseExecutor.start()')

    def test_stream_chat_parses_resume_tag(self):
        self.assertIn('PromiseActivator.resume_from_text', self.src,
            'stream_chat 末尾必须解析 RESUME_PLAN 标签')


# ==========================================================================
if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__]))
    print('\n' + '=' * 60)
    if result.wasSuccessful():
        print('[OK] All R8 axis3 L3.2 PromiseExecutor tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('=' * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
