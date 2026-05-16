"""R7-α/PlanLedger 单元测试。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_alpha_plan_ledger.py

覆盖：
- draft 创建计划 + auto_await_go
- set_state 状态机转换（合法/非法跃迁）
- advance_step 步骤推进
- get / get_active / list_recent / cancel_all
- to_prompt_block 渲染
- JSON 持久化 save/load
- event_bus 投递
- max_active 限制
- 源码契约：CentralNerve 实例化 + 启动时 load + prompt 注入
"""
import os
import re
import sys
import json
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    PlanLedger, ConversationEventBus,
    get_default_plan_ledger,
)


class TestPlanLedgerBasic(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.persist = os.path.join(self.tmpdir, 'plans.json')
        self.ledger = PlanLedger(persist_path=self.persist, autosave=False)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_draft_creates_plan_in_awaiting_go(self):
        pid = self.ledger.draft("把 R7 改动整理成备忘", steps=["grep 改动", "总结", "写 md"])
        self.assertIsInstance(pid, str)
        self.assertEqual(len(pid), 16)
        plan = self.ledger.get(pid)
        self.assertEqual(plan['state'], PlanLedger.STATE_AWAITING_GO)
        self.assertEqual(len(plan['steps']), 3)
        self.assertEqual(plan['steps'][0]['description'], 'grep 改动')
        self.assertEqual(plan['steps'][0]['status'], 'pending')

    def test_draft_no_auto_await_stays_drafted(self):
        pid = self.ledger.draft("foo", auto_await_go=False)
        self.assertEqual(self.ledger.get(pid)['state'], PlanLedger.STATE_DRAFTED)

    def test_draft_empty_goal_raises(self):
        with self.assertRaises(ValueError):
            self.ledger.draft("")

    def test_normal_state_transition_drafted_to_done(self):
        pid = self.ledger.draft("foo", steps=["a", "b"], auto_await_go=False)
        # drafted → awaiting_go
        self.assertTrue(self.ledger.set_state(pid, PlanLedger.STATE_AWAITING_GO))
        # awaiting_go → running
        self.assertTrue(self.ledger.set_state(pid, PlanLedger.STATE_RUNNING, reason='go'))
        # running → done
        self.assertTrue(self.ledger.set_state(pid, PlanLedger.STATE_DONE, reason='all_steps_complete'))
        self.assertEqual(self.ledger.get(pid)['state'], PlanLedger.STATE_DONE)

    def test_invalid_transition_returns_false(self):
        pid = self.ledger.draft("foo", auto_await_go=False)
        # drafted → done 是非法跃迁
        self.assertFalse(self.ledger.set_state(pid, PlanLedger.STATE_DONE))
        # done 状态后任何跃迁都不允许
        self.ledger.set_state(pid, PlanLedger.STATE_AWAITING_GO)
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING)
        self.ledger.set_state(pid, PlanLedger.STATE_DONE)
        self.assertFalse(self.ledger.set_state(pid, PlanLedger.STATE_RUNNING))

    def test_pause_resume(self):
        pid = self.ledger.draft("foo", auto_await_go=True)
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING, reason='go')
        self.assertTrue(self.ledger.set_state(pid, PlanLedger.STATE_PAUSED, reason='Sir said pause'))
        self.assertTrue(self.ledger.set_state(pid, PlanLedger.STATE_RUNNING, reason='Sir said continue'))

    def test_cancel_from_any_state(self):
        # drafted → cancelled
        pid1 = self.ledger.draft("foo1", auto_await_go=False)
        self.assertTrue(self.ledger.set_state(pid1, PlanLedger.STATE_CANCELLED))

        # awaiting_go → cancelled
        pid2 = self.ledger.draft("foo2")
        self.assertTrue(self.ledger.set_state(pid2, PlanLedger.STATE_CANCELLED))

        # running → cancelled
        pid3 = self.ledger.draft("foo3")
        self.ledger.set_state(pid3, PlanLedger.STATE_RUNNING)
        self.assertTrue(self.ledger.set_state(pid3, PlanLedger.STATE_CANCELLED))

    def test_advance_step(self):
        pid = self.ledger.draft("foo", steps=["a", "b", "c"])
        self.assertTrue(self.ledger.advance_step(pid, 0, 'running'))
        self.assertEqual(self.ledger.get(pid)['steps'][0]['status'], 'running')
        self.assertTrue(self.ledger.advance_step(pid, 0, 'done', result='OK'))
        self.assertEqual(self.ledger.get(pid)['steps'][0]['status'], 'done')
        self.assertEqual(self.ledger.get(pid)['steps'][0]['result'], 'OK')

    def test_advance_step_invalid_index(self):
        pid = self.ledger.draft("foo", steps=["a"])
        self.assertFalse(self.ledger.advance_step(pid, 99, 'done'))
        self.assertFalse(self.ledger.advance_step('nonexistent', 0, 'done'))

    def test_get_active_filters_done(self):
        pid1 = self.ledger.draft("foo1")
        pid2 = self.ledger.draft("foo2")
        self.ledger.set_state(pid1, PlanLedger.STATE_RUNNING)
        self.ledger.set_state(pid1, PlanLedger.STATE_DONE)
        # 只剩 pid2 active
        actives = self.ledger.get_active()
        self.assertEqual(len(actives), 1)
        self.assertEqual(actives[0]['plan_id'], pid2)

    def test_list_recent(self):
        pids = []
        for i in range(7):
            pids.append(self.ledger.draft(f"foo{i}"))
            time.sleep(0.01)  # 让 created_at 有差异
        recent = self.ledger.list_recent(5)
        self.assertEqual(len(recent), 5)
        # 最近的应该是 foo6
        self.assertEqual(recent[0]['goal'], 'foo6')

    def test_cancel_all(self):
        pid1 = self.ledger.draft("foo1")
        pid2 = self.ledger.draft("foo2")
        self.ledger.set_state(pid1, PlanLedger.STATE_RUNNING)
        cancelled = self.ledger.cancel_all(reason='interrupt_all')
        self.assertEqual(set(cancelled), {pid1, pid2})
        self.assertEqual(self.ledger.get_active(), [])

    def test_max_active_enforced(self):
        ledger = PlanLedger(persist_path=self.persist, max_active=2, autosave=False)
        ledger.draft("foo1")
        ledger.draft("foo2")
        ledger.draft("foo3")
        actives = ledger.get_active()
        self.assertEqual(len(actives), 2)


class TestPlanLedgerRendering(unittest.TestCase):
    def setUp(self):
        self.ledger = PlanLedger(persist_path=None, autosave=False)

    def test_empty_block(self):
        self.assertEqual(self.ledger.to_prompt_block(), "")

    def test_renders_active_plan(self):
        pid = self.ledger.draft(
            "把 R7 改动整理成备忘",
            steps=["grep 改动", "总结", "写 md"],
        )
        block = self.ledger.to_prompt_block()
        self.assertIn("ACTIVE PLAN", block)
        self.assertIn("把 R7 改动整理成备忘", block)
        self.assertIn("awaiting_go", block)
        self.assertIn("grep 改动", block)

    def test_renders_step_status_markers(self):
        pid = self.ledger.draft("foo", steps=["a", "b", "c"])
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING, reason='go')
        self.ledger.advance_step(pid, 0, 'done')
        self.ledger.advance_step(pid, 1, 'running')
        block = self.ledger.to_prompt_block()
        self.assertIn("✓", block)  # done
        self.assertIn("◐", block)  # running
        self.assertIn("○", block)  # pending

    def test_max_chars_cap(self):
        pid = self.ledger.draft("x" * 300, steps=["y" * 100 for _ in range(20)])
        block = self.ledger.to_prompt_block(max_chars=200)
        self.assertLessEqual(len(block), 220)


class TestPlanLedgerPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.persist = os.path.join(self.tmpdir, 'plans.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_then_load(self):
        ledger = PlanLedger(persist_path=self.persist, autosave=False)
        pid = ledger.draft("important task", steps=["step1", "step2"])
        ledger.set_state(pid, PlanLedger.STATE_RUNNING, reason='go')
        ledger.advance_step(pid, 0, 'done', result='OK')
        self.assertTrue(ledger.save())
        # 新 ledger 从同一文件加载
        ledger2 = PlanLedger(persist_path=self.persist, autosave=False)
        self.assertTrue(ledger2.load())
        plan = ledger2.get(pid)
        self.assertIsNotNone(plan)
        self.assertEqual(plan['goal'], 'important task')
        self.assertEqual(plan['state'], PlanLedger.STATE_RUNNING)
        self.assertEqual(plan['steps'][0]['status'], 'done')
        self.assertEqual(plan['steps'][0]['result'], 'OK')

    def test_load_missing_file_returns_false(self):
        ledger = PlanLedger(persist_path='/nonexistent/plans.json', autosave=False)
        self.assertFalse(ledger.load())

    def test_autosave_triggers_on_state_change(self):
        ledger = PlanLedger(persist_path=self.persist, autosave=True)
        ledger.draft("foo")
        # 文件应该已经写出来
        self.assertTrue(os.path.exists(self.persist))
        # 内容能解析
        with open(self.persist, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


class TestPlanLedgerEventBusIntegration(unittest.TestCase):
    def setUp(self):
        self.bus = ConversationEventBus(max_events=20)
        self.ledger = PlanLedger(persist_path=None, event_bus=self.bus, autosave=False)

    def test_draft_publishes_event(self):
        self.ledger.draft("foo", steps=["a"])
        # 至少 plan_drafted + auto_await_go 两条
        events = self.bus.recent_events()
        types = {e['type'] for e in events}
        self.assertIn('plan_drafted', types)
        self.assertIn('plan_state_awaiting_go', types)

    def test_set_state_publishes(self):
        pid = self.ledger.draft("foo")
        self.bus.clear()
        self.ledger.set_state(pid, PlanLedger.STATE_RUNNING, reason='go')
        events = self.bus.recent_events(types={'plan_state_running'})
        self.assertEqual(len(events), 1)
        self.assertIn('running', events[0]['description'])


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_central_nerve_creates_plan_ledger(self):
        self.assertRegex(
            self.src,
            r'self\.plan_ledger\s*=\s*PlanLedger\(',
            "CentralNerve 必须实例化 PlanLedger"
        )

    def test_central_nerve_load_on_startup(self):
        # 启动时必须 load() 恢复未完结计划
        self.assertRegex(
            self.src,
            r'self\.plan_ledger\.load\(\)',
            "CentralNerve 必须在启动时 plan_ledger.load() 恢复"
        )

    def test_prompt_has_active_plan_block(self):
        self.assertIn('{active_plan_block}', self.src,
                      "prompt 必须包含 {active_plan_block} 占位")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestPlanLedgerBasic),
        loader.loadTestsFromTestCase(TestPlanLedgerRendering),
        loader.loadTestsFromTestCase(TestPlanLedgerPersistence),
        loader.loadTestsFromTestCase(TestPlanLedgerEventBusIntegration),
        loader.loadTestsFromTestCase(TestSourceContract),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-α/PlanLedger tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
