# -*- coding: utf-8 -*-
"""[轴3-L3.3 / 2026-05-15] 失败重试链 + dangerous 二次确认 + clarification 反向提问 — 测试套件

覆盖：
  TestRetryFirstFailure              — 第 1 次失败 → retry_count=1, status=pending（下轮再跑）
  TestSecondFailurePauses            — 第 2 次失败 → status=failed + plan PAUSED
  TestSecondFailureClarificationMeta — paused_for_clarification + failed_step_idx + failed_step_error
  TestSecondFailureSaysToSir         — say_to_sir 收到 "step N failed" 形式问句
  TestDangerousPausesForConfirm      — dangerous_skills 非空 → 第一轮 PAUSE for confirm
  TestDangerousConfirmedSkipsPause   — metadata.dangerous_confirmed=True → 不暂停直接跑
  TestDangerousResumeFromText        — RESUME_PLAN → set RUNNING + dangerous_confirmed=True
  TestStepLevelDangerousFallback     — LLM 漏报 metadata 但 step.skill 是 dangerous → executor 跑到时也 PAUSE
  TestClarificationResume            — RESUME_PLAN 让 failed step 复位 + 清 metadata
  TestRESUMENonExistentIgnored       — RESUME 找不到 plan_id 不抛
  TestPromiseExecutorEventBus        — 'plan_paused_*' 事件 publish 到 bus
  TestTransientMetaResetOnInit       — 启动时清掉所有 active plan 的 transient meta
  TestSourceContract                 — jarvis_skill_registry.py 源码契约：方法 + 标志位

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l3_3_retry_dangerous.py
"""
import os
import sys
import time
import tempfile
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry, SkillManifest, get_registry,
    DANGER_SAFE, DANGER_RISKY, DANGER_DANGEROUS,
    PromiseActivator, PromiseExecutor,
    TRANSIENT_META_KEYS, EXEC_PREFIX_FAILURE,
)
from jarvis_utils import PlanLedger, ConversationEventBus


def _make_skill(command='audio_hands.set_volume', danger=DANGER_RISKY,
                description='set audio volume'):
    return SkillManifest(
        command=command, module='m', callable_name='c',
        description=description, dangerous_flag=danger,
    )


def _new_ledger(tmp=None):
    if tmp is None:
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name
    return PlanLedger(persist_path=tmp, autosave=False, max_active=10)


# ==========================================================================
# 1. 第 1 次失败：重试 / 第 2 次失败：PAUSE
# ==========================================================================

class _BaseExecutorCase(unittest.TestCase):
    """共享 setUp：构造一个会失败的 fast_call。"""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()
        self.registry.register(_make_skill('x.y', DANGER_RISKY))
        self.ledger = _new_ledger()
        self.calls = []
        self.said = []
        self.failure_msg = "❌ x.y: device not found"

        def _fast_call(o, c, a):
            self.calls.append((o, c, dict(a)))
            return self.failure_msg

        def _say(text):
            self.said.append(text)

        self.ex = PromiseExecutor(
            plan_ledger=self.ledger, skill_registry=self.registry,
            fast_call_executor=_fast_call, say_to_sir=_say, tick_s=0.05,
        )

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def _draft_running(self, steps, dangerous_confirmed=True):
        meta = {'dangerous_confirmed': True} if dangerous_confirmed else {}
        pid = self.ledger.draft(goal='g', steps=steps, metadata=meta)
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        return pid


class TestRetryFirstFailure(_BaseExecutorCase):

    def test_first_failure_keeps_step_pending(self):
        pid = self._draft_running([
            {'description': 'd', 'skill': 'x.y', 'args': {'k': 1}}
        ])
        # 第 1 次 tick → fail 1 次
        self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertEqual(plan['steps'][0]['status'], 'pending')
        self.assertEqual(plan['steps'][0]['retry_count'], 1)
        # plan 仍 RUNNING（不是 PAUSED）
        self.assertEqual(plan['state'], PlanLedger.STATE_RUNNING)

    def test_first_failure_records_last_error(self):
        pid = self._draft_running([
            {'description': 'd', 'skill': 'x.y', 'args': {}}
        ])
        self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertIn('device not found', plan['steps'][0]['last_error'])


class TestSecondFailurePauses(_BaseExecutorCase):

    def test_second_failure_marks_failed_and_pauses(self):
        pid = self._draft_running([
            {'description': 'd', 'skill': 'x.y', 'args': {}}
        ])
        # 两次 tick = 两次失败
        self.ex.tick_once()
        self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertEqual(plan['steps'][0]['status'], 'failed')
        self.assertEqual(plan['state'], PlanLedger.STATE_PAUSED)


class TestSecondFailureClarificationMeta(_BaseExecutorCase):

    def test_metadata_paused_for_clarification_set(self):
        pid = self._draft_running([
            {'description': 'd', 'skill': 'x.y', 'args': {}}
        ])
        self.ex.tick_once()
        self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertTrue(plan['metadata'].get('paused_for_clarification'))
        self.assertEqual(plan['metadata'].get('failed_step_idx'), 0)
        self.assertIn('device not found', plan['metadata'].get('failed_step_error', ''))


class TestSecondFailureSaysToSir(_BaseExecutorCase):

    def test_say_to_sir_called_with_question(self):
        self._draft_running([
            {'description': 'd', 'skill': 'x.y', 'args': {}}
        ])
        self.ex.tick_once()
        self.ex.tick_once()
        # say_to_sir 至少被调一次（第二次失败时反向提问）
        self.assertTrue(len(self.said) >= 1)
        joined = ' '.join(self.said)
        self.assertIn('failed', joined.lower())
        # 含 "Retry" 或 "skip" 选项让主脑/Sir 知道下一步
        self.assertTrue('retry' in joined.lower() or 'skip' in joined.lower())


# ==========================================================================
# 2. dangerous 二次确认
# ==========================================================================

class TestDangerousPausesForConfirm(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()
        # 注册 dangerous skill
        self.registry.register(_make_skill('file_op.delete', DANGER_DANGEROUS))
        self.ledger = _new_ledger()
        self.calls = []
        self.said = []
        self.ex = PromiseExecutor(
            plan_ledger=self.ledger, skill_registry=self.registry,
            fast_call_executor=lambda o, c, a: (
                self.calls.append((o, c)) or "✅ done"
            ),
            say_to_sir=lambda t: self.said.append(t), tick_s=0.05,
        )

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_dangerous_plan_pauses_on_first_tick(self):
        pid = self.ledger.draft(
            goal='delete file', metadata={'dangerous_skills': ['file_op.delete']},
            steps=[{'description': 'rm /tmp/x', 'skill': 'file_op.delete',
                    'args': {'path': '/tmp/x'}}],
        )
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        self.ex.tick_once()
        plan = self.ledger.get(pid)
        # plan 进 PAUSED
        self.assertEqual(plan['state'], PlanLedger.STATE_PAUSED)
        # metadata 标志位
        self.assertTrue(plan['metadata'].get('paused_for_dangerous_confirm'))
        # vocal 警告 Sir
        self.assertTrue(any('dangerous' in s.lower() for s in self.said))
        # 工具 *没* 被调
        self.assertEqual(len(self.calls), 0)

    def test_dangerous_confirmed_runs_normally(self):
        pid = self.ledger.draft(
            goal='delete file',
            metadata={'dangerous_skills': ['file_op.delete'],
                      'dangerous_confirmed': True},
            steps=[{'description': 'rm', 'skill': 'file_op.delete',
                    'args': {'path': '/tmp/x'}}],
        )
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        for _ in range(3):
            self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_DONE)
        self.assertEqual(len(self.calls), 1)


class TestStepLevelDangerousFallback(unittest.TestCase):
    """LLM 漏报 metadata.dangerous_skills 但 step.skill 是 dangerous → executor 跑到也兜底 PAUSE。"""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()
        self.registry.register(_make_skill('file_op.delete', DANGER_DANGEROUS))
        self.registry.register(_make_skill('safe_op.list', DANGER_SAFE))
        self.ledger = _new_ledger()
        self.calls = []
        self.said = []
        self.ex = PromiseExecutor(
            plan_ledger=self.ledger, skill_registry=self.registry,
            fast_call_executor=lambda o, c, a: (
                self.calls.append((o, c)) or "✅ done"
            ),
            say_to_sir=lambda t: self.said.append(t), tick_s=0.05,
        )

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_dangerous_step_in_misreported_plan_paused(self):
        # plan metadata 没标 dangerous_skills（LLM 漏报），但第 2 步是 dangerous skill
        pid = self.ledger.draft(
            goal='lazy LLM', metadata={'dangerous_skills': []},  # 漏报
            steps=[
                {'description': 'list', 'skill': 'safe_op.list', 'args': {}},
                {'description': 'rm', 'skill': 'file_op.delete', 'args': {}},
            ],
        )
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        # tick 几次让 step 1 跑完，step 2 被 dangerous 兜底 PAUSE
        for _ in range(5):
            self.ex.tick_once()
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_PAUSED)
        # step 1 done，step 2 仍 pending（被复位）
        self.assertEqual(plan['steps'][0]['status'], 'done')
        self.assertEqual(plan['steps'][1]['status'], 'pending')
        # dangerous_skills 已被加入 metadata（让主脑下一轮看见）
        self.assertIn('file_op.delete', plan['metadata'].get('dangerous_skills', []))


# ==========================================================================
# 3. RESUME_PLAN 解析（dangerous 二次确认 + clarification 重试）
# ==========================================================================

class TestDangerousResumeFromText(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()

    def test_resume_clears_dangerous_pause(self):
        pid = self.ledger.draft(goal='g',
            steps=[{'description': 'd', 'skill': 'x.y'}],
            metadata={'paused_for_dangerous_confirm': True,
                      'dangerous_skills': ['x.y']})
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        self.ledger.set_state(pid, PlanLedger.STATE_PAUSED)
        text = f'Proceeding, Sir. <RESUME_PLAN>{pid[:8]}</RESUME_PLAN>'
        resumed = PromiseActivator.resume_from_text(text, self.ledger)
        self.assertEqual(resumed, [pid])
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_RUNNING)
        self.assertTrue(plan['metadata'].get('dangerous_confirmed'))
        self.assertNotIn('paused_for_dangerous_confirm', plan['metadata'])


class TestClarificationResume(unittest.TestCase):

    def setUp(self):
        self.ledger = _new_ledger()

    def test_resume_resets_failed_step(self):
        pid = self.ledger.draft(goal='g',
            steps=[{'description': 'd', 'skill': 'x.y'}])
        # 模拟 step 失败
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        with self.ledger._lock:
            plan = self.ledger._plans[pid]
            plan['steps'][0]['status'] = 'failed'
            plan['steps'][0]['retry_count'] = 2
            plan['steps'][0]['last_error'] = 'permission denied'
            plan['metadata']['paused_for_clarification'] = True
            plan['metadata']['failed_step_idx'] = 0
            plan['metadata']['failed_step_error'] = 'permission denied'
        self.ledger.set_state(pid, PlanLedger.STATE_PAUSED)
        # Sir 说 "再试一次" → 主脑 RESUME
        text = f'Got it. <RESUME_PLAN>{pid[:8]}</RESUME_PLAN>'
        PromiseActivator.resume_from_text(text, self.ledger)
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_RUNNING)
        self.assertEqual(plan['steps'][0]['status'], 'pending')
        self.assertEqual(plan['steps'][0]['retry_count'], 0)
        # clarification 元数据清掉
        self.assertNotIn('paused_for_clarification', plan['metadata'])
        self.assertNotIn('failed_step_idx', plan['metadata'])
        self.assertNotIn('failed_step_error', plan['metadata'])


class TestRESUMENonExistentIgnored(unittest.TestCase):

    def test_resume_unknown_id_silently_ignored(self):
        ledger = _new_ledger()
        # 不抛异常，返回空 list
        out = PromiseActivator.resume_from_text(
            '<RESUME_PLAN>nonexistent12</RESUME_PLAN>', ledger
        )
        self.assertEqual(out, [])


# ==========================================================================
# 4. event_bus 投递
# ==========================================================================

class TestPromiseExecutorEventBus(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.registry = get_registry()
        self.registry.register(_make_skill('x.y', DANGER_RISKY))
        self.registry.register(_make_skill('file_op.delete', DANGER_DANGEROUS))
        self.ledger = _new_ledger()
        self.bus = ConversationEventBus()
        self.ex = PromiseExecutor(
            plan_ledger=self.ledger, skill_registry=self.registry,
            fast_call_executor=lambda o, c, a: "❌ boom",
            say_to_sir=lambda t: None,
            event_bus=self.bus, tick_s=0.05,
        )

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_clarification_event_published(self):
        pid = self.ledger.draft(goal='g',
            metadata={'dangerous_confirmed': True},
            steps=[{'description': 'd', 'skill': 'x.y', 'args': {}}])
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        self.ex.tick_once()
        self.ex.tick_once()  # 两次 tick → PAUSE
        events = self.bus.recent_events(types={'plan_paused_clarification'})
        self.assertTrue(len(events) >= 1)

    def test_dangerous_pause_event_published(self):
        pid = self.ledger.draft(goal='g',
            metadata={'dangerous_skills': ['file_op.delete']},
            steps=[{'description': 'd', 'skill': 'file_op.delete', 'args': {}}])
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        self.ex.tick_once()
        events = self.bus.recent_events(types={'plan_paused_dangerous_confirm'})
        self.assertTrue(len(events) >= 1)


# ==========================================================================
# 5. 启动时清掉 transient meta
# ==========================================================================

class TestTransientMetaResetOnInit(unittest.TestCase):

    def test_dangerous_confirmed_cleared_on_executor_init(self):
        ledger = _new_ledger()
        pid = ledger.draft(goal='g',
            steps=[{'description': 'd'}],
            metadata={'dangerous_confirmed': True,
                      'paused_for_clarification': True,
                      'failed_step_idx': 0,
                      'failed_step_error': 'old error'})
        # 创建新 executor → __init__ 内调 _reset_transient_metadata_on_init
        PromiseExecutor(plan_ledger=ledger)
        plan = ledger.get(pid)
        for k in TRANSIENT_META_KEYS:
            self.assertNotIn(k, plan['metadata'])

    def test_non_transient_meta_preserved(self):
        ledger = _new_ledger()
        pid = ledger.draft(goal='g',
            steps=[{'description': 'd'}],
            metadata={'source': 'promise_parser',
                      'dangerous_skills': ['x.y'],  # 非 transient
                      'dangerous_confirmed': True})  # transient
        PromiseExecutor(plan_ledger=ledger)
        plan = ledger.get(pid)
        # 非 transient meta 保留
        self.assertEqual(plan['metadata'].get('source'), 'promise_parser')
        self.assertEqual(plan['metadata'].get('dangerous_skills'), ['x.y'])
        # transient 清掉
        self.assertNotIn('dangerous_confirmed', plan['metadata'])


# ==========================================================================
# 6. 源码契约
# ==========================================================================

class TestSourceContract(unittest.TestCase):
    """读 jarvis_skill_registry.py 源码字符串确认关键设计未漂移。"""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_skill_registry.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_max_retries_per_step_constant(self):
        self.assertIn('MAX_RETRIES_PER_STEP', self.src)

    def test_dangerous_confirm_method(self):
        self.assertIn('_maybe_request_dangerous_confirm', self.src)

    def test_record_step_failure_method(self):
        self.assertIn('_record_step_failure', self.src)

    def test_clarification_metadata_keys(self):
        self.assertIn('paused_for_clarification', self.src)
        self.assertIn('paused_for_dangerous_confirm', self.src)
        self.assertIn('dangerous_confirmed', self.src)
        self.assertIn('failed_step_idx', self.src)
        self.assertIn('failed_step_error', self.src)

    def test_resume_from_text_method(self):
        self.assertIn('resume_from_text', self.src)

    def test_protocol_directive_explains_resume_plan(self):
        from jarvis_skill_registry import PROMISE_PROTOCOL_DIRECTIVE
        self.assertIn('RESUME_PLAN', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('clarification', PROMISE_PROTOCOL_DIRECTIVE)
        self.assertIn('dangerous', PROMISE_PROTOCOL_DIRECTIVE)


# ==========================================================================
if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__]))
    print('\n' + '=' * 60)
    if result.wasSuccessful():
        print('[OK] All R8 axis3 L3.3 retry/dangerous/clarification tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('=' * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
