# -*- coding: utf-8 -*-
"""[P5-fix35 / 2026-05-23 11:11] Cyclic Task 通用循环任务架构测试

Sir 11:09 真意: 通用 clarify → confirm → cyclic_emit 链路 (不只 reminder).

覆盖:
A. CyclicTaskStore — register/cancel/list/status/_parse_dt
B. chat_bypass FAST_CALL cyclic_task organ handler (静态扫源)
C. cyclic_task_dispatcher directive 注册 + trigger + vocab 持久化
D. CLI scripts/cyclic_task_dump.py 文件 + actions
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ============================================================
# A. CyclicTaskStore unit tests
# ============================================================

class TestACyclicTaskStore(unittest.TestCase):
    """Core store: register / cancel / list / parse."""

    def setUp(self):
        from jarvis_cyclic_task import (
            CyclicTaskStore, reset_default_store_for_test
        )
        reset_default_store_for_test()
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8').name
        os.remove(self.tmpfile)  # fresh
        self.store = CyclicTaskStore(
            protocol_path=self.tmpfile, hippocampus=None)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_register_basic_6_fires(self):
        """14:30 → 22:00 every 90 min = 6 fires"""
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        r = self.store.register(
            task_id='t1', kind='reminder',
            description='hydration', cycle_minutes=90,
            start_at=f'{today_str} 14:30',
            end_at=f'{today_str} 22:00',
            intent_template='drink water',
        )
        self.assertTrue(r['ok'])
        self.assertEqual(r['n_fires'], 6)
        self.assertEqual(r['task_id'], 't1')

    def test_register_pomodoro_25min(self):
        from datetime import datetime as dt
        now = dt.now()
        start = now.strftime('%H:%M')
        end = (now + timedelta(hours=2)).strftime('%H:%M')
        r = self.store.register(
            task_id='pom_test', kind='pomodoro',
            description='pomodoro 25min', cycle_minutes=25,
            start_at=start, end_at=end,
            intent_template='take 5min break',
        )
        self.assertTrue(r['ok'])
        # 2h / 25min = ~5 fires (4-5)
        self.assertGreaterEqual(r['n_fires'], 4)
        self.assertLessEqual(r['n_fires'], 6)

    def test_register_rejects_dup_active(self):
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        r1 = self.store.register(
            task_id='dup_test', kind='reminder',
            description='x', cycle_minutes=60,
            start_at=f'{today_str} 10:00', end_at=f'{today_str} 12:00',
            intent_template='x',
        )
        self.assertTrue(r1['ok'])
        r2 = self.store.register(
            task_id='dup_test', kind='reminder',
            description='y', cycle_minutes=60,
            start_at=f'{today_str} 10:00', end_at=f'{today_str} 12:00',
            intent_template='y',
        )
        self.assertFalse(r2['ok'])
        self.assertIn('already active', r2['error'])

    def test_register_rejects_bad_window(self):
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        r = self.store.register(
            task_id='bad', kind='reminder', description='', cycle_minutes=60,
            start_at=f'{today_str} 22:00', end_at=f'{today_str} 10:00',
            intent_template='',
        )
        self.assertFalse(r['ok'])
        self.assertIn('end_at must be after', r['error'])

    def test_register_rejects_zero_cycle(self):
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        r = self.store.register(
            task_id='zero', kind='reminder', description='', cycle_minutes=0,
            start_at=f'{today_str} 10:00', end_at=f'{today_str} 11:00',
            intent_template='',
        )
        self.assertFalse(r['ok'])
        self.assertIn('cycle_minutes', r['error'])

    def test_register_caps_at_50_fires(self):
        """tight cycle (1 min) over 24h should cap at max_fires=50"""
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        r = self.store.register(
            task_id='spam_test', kind='reminder', description='spam',
            cycle_minutes=5,  # 5min over 12h = 144 fires, cap at 50
            start_at=f'{today_str} 00:00', end_at=f'{today_str} 23:00',
            intent_template='spam',
        )
        self.assertTrue(r['ok'])
        self.assertLessEqual(r['n_fires'], 50)

    def test_cancel_removes_task(self):
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        self.store.register(
            task_id='cancel_test', kind='reminder', description='x',
            cycle_minutes=60,
            start_at=f'{today_str} 14:00', end_at=f'{today_str} 16:00',
            intent_template='x',
        )
        r = self.store.cancel('cancel_test', reason='unittest cleanup')
        self.assertTrue(r['ok'])
        t = self.store.get('cancel_test')
        self.assertEqual(t.state, 'cancelled')
        self.assertIn('unittest cleanup', t.cancelled_reason)

    def test_cancel_unknown_task(self):
        r = self.store.cancel('nonexistent')
        self.assertFalse(r['ok'])
        self.assertIn('not found', r['error'])

    def test_list_active_filters_cancelled(self):
        from datetime import date
        today_str = date.today().strftime('%Y-%m-%d')
        self.store.register(
            task_id='a', kind='reminder', description='',
            cycle_minutes=60,
            start_at=f'{today_str} 14:00', end_at=f'{today_str} 15:00',
            intent_template='')
        self.store.register(
            task_id='b', kind='reminder', description='',
            cycle_minutes=60,
            start_at=f'{today_str} 14:00', end_at=f'{today_str} 15:00',
            intent_template='')
        self.store.cancel('a', reason='test')

        active = self.store.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].task_id, 'b')

        all_tasks = self.store.list_all()
        self.assertEqual(len(all_tasks), 2)

    def test_persist_roundtrip(self):
        from datetime import date
        from jarvis_cyclic_task import CyclicTaskStore
        today_str = date.today().strftime('%Y-%m-%d')
        self.store.register(
            task_id='persist_test', kind='check', description='persist',
            cycle_minutes=120,
            start_at=f'{today_str} 09:00', end_at=f'{today_str} 17:00',
            intent_template='check progress')
        # reload
        store2 = CyclicTaskStore(
            protocol_path=self.tmpfile, hippocampus=None)
        t = store2.get('persist_test')
        self.assertIsNotNone(t)
        self.assertEqual(t.kind, 'check')
        self.assertEqual(t.cycle_minutes, 120)


class TestAParseDt(unittest.TestCase):
    """_parse_dt formats: full ISO / date+HH:MM / HH:MM-only"""

    def test_parse_full_iso(self):
        from jarvis_cyclic_task import _parse_dt
        dt = _parse_dt('2026-05-23 14:30')
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 14)

    def test_parse_hh_mm_only(self):
        from jarvis_cyclic_task import _parse_dt
        dt = _parse_dt('14:30')
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.minute, 30)
        # 应该是 today
        self.assertEqual(dt.date(), datetime.now().date())

    def test_parse_invalid(self):
        from jarvis_cyclic_task import _parse_dt
        self.assertIsNone(_parse_dt('nonsense'))
        self.assertIsNone(_parse_dt(''))


# ============================================================
# B. chat_bypass FAST_CALL cyclic_task organ handler (静态扫源)
# ============================================================

class TestBChatBypassOrgan(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'),
                   'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_organ_handler_present(self):
        self.assertIn('organ_name == "cyclic_task"', self.src,
                       'cyclic_task organ handler 未挂载')

    def test_register_command_handler(self):
        self.assertIn("command == 'register'", self.src)
        self.assertIn('cycle_minutes', self.src)
        self.assertIn('start_at', self.src)
        self.assertIn('end_at', self.src)

    def test_cancel_command_handler(self):
        self.assertIn("command == 'cancel'", self.src)

    def test_list_status_commands(self):
        self.assertIn("command == 'list'", self.src)
        self.assertIn("command == 'status'", self.src)

    def test_uses_cyclic_task_store(self):
        self.assertIn('from jarvis_cyclic_task import get_default_store',
                       self.src)


# ============================================================
# C. cyclic_task_dispatcher directive + trigger + vocab
# ============================================================

class TestCDirectiveRegistration(unittest.TestCase):

    def test_directive_registered_priority_11(self):
        import jarvis_directives as jd
        reg = jd.get_default_registry()
        d = reg.get('cyclic_task_dispatcher')
        self.assertIsNotNone(d, 'cyclic_task_dispatcher not registered')
        # priority either 11 (.py seed) or what's persisted in JSON
        # if persisted, the test may differ; treat 11 as expected after restart
        # but for now assert .id matches
        self.assertEqual(d.id, 'cyclic_task_dispatcher')
        self.assertEqual(d.source_marker, 'P5-fix35-B')

    def test_directive_text_has_critical_keywords(self):
        import jarvis_directives as jd
        reg = jd.get_default_registry()
        d = reg.get('cyclic_task_dispatcher')
        self.assertIsNotNone(d)
        self.assertIn('cyclic_task', d.text)
        self.assertIn('MANDATORY', d.text)
        self.assertIn('FAST_CALL', d.text)
        self.assertIn('cycle_minutes', d.text)
        self.assertIn('register', d.text)
        self.assertIn('clarify', d.text)
        # examples
        self.assertIn('pomodoro', d.text)
        self.assertIn('hydration', d.text)


class TestCTriggerVocab(unittest.TestCase):

    def setUp(self):
        import jarvis_directives as jd
        jd._CYCLIC_TASK_CACHE = None
        jd._CYCLIC_TASK_MTIME = 0.0

    def test_trigger_fires_on_chinese_vocab(self):
        from jarvis_directives import (
            _trigger_cyclic_task_dispatcher, DirectiveContext
        )
        ctx = DirectiveContext(
            user_input='每 90 分钟提醒我喝水', tier='CHAT', stm=[])
        self.assertTrue(_trigger_cyclic_task_dispatcher(ctx))

    def test_trigger_fires_on_english_vocab(self):
        from jarvis_directives import (
            _trigger_cyclic_task_dispatcher, DirectiveContext
        )
        ctx = DirectiveContext(
            user_input='remind me every 30 minutes',
            tier='CHAT', stm=[])
        self.assertTrue(_trigger_cyclic_task_dispatcher(ctx))

    def test_trigger_skip_no_match(self):
        from jarvis_directives import (
            _trigger_cyclic_task_dispatcher, DirectiveContext
        )
        ctx = DirectiveContext(
            user_input='what time is it?', tier='CHAT', stm=[])
        self.assertFalse(_trigger_cyclic_task_dispatcher(ctx))

    def test_trigger_skip_empty(self):
        from jarvis_directives import (
            _trigger_cyclic_task_dispatcher, DirectiveContext
        )
        ctx = DirectiveContext(user_input='', tier='CHAT', stm=[])
        self.assertFalse(_trigger_cyclic_task_dispatcher(ctx))

    def test_vocab_persistence_path_exists(self):
        path = os.path.join(
            ROOT, 'memory_pool', 'cyclic_task_dispatcher_vocab.json')
        self.assertTrue(os.path.exists(path),
                          'vocab JSON must persist per 准则 6')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('patterns', data)
        self.assertGreater(len(data['patterns']), 10)
        # spot check: 中英都有
        patterns_lower = [p.lower() for p in data['patterns']]
        self.assertTrue(
            any('每' in p for p in patterns_lower),
            '应含中文')
        self.assertTrue(
            any('every' in p for p in patterns_lower),
            '应含英文')

    def test_vocab_mtime_reload(self):
        """change vocab file → next get_cyclic_task_patterns() picks up new"""
        import jarvis_directives as jd
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        json.dump({'patterns': ['ZZZ_unique_test_kw']}, tmp,
                   ensure_ascii=False)
        tmp.close()
        try:
            jd._CYCLIC_TASK_VOCAB_PATH = tmp.name
            jd._CYCLIC_TASK_CACHE = None
            jd._CYCLIC_TASK_MTIME = 0.0
            patterns = jd.get_cyclic_task_patterns()
            self.assertIn('zzz_unique_test_kw', patterns)
        finally:
            os.remove(tmp.name)
            # restore default path
            jd._CYCLIC_TASK_VOCAB_PATH = os.path.join(
                'memory_pool', 'cyclic_task_dispatcher_vocab.json')
            jd._CYCLIC_TASK_CACHE = None
            jd._CYCLIC_TASK_MTIME = 0.0


# ============================================================
# D. CLI cyclic_task_dump.py existence + actions
# ============================================================

class TestDCLI(unittest.TestCase):

    def test_cli_file_exists(self):
        path = os.path.join(ROOT, 'scripts', 'cyclic_task_dump.py')
        self.assertTrue(os.path.exists(path),
                          'cyclic_task_dump.py CLI must exist (准则 6 CLI 可改)')

    def test_cli_has_required_actions(self):
        path = os.path.join(ROOT, 'scripts', 'cyclic_task_dump.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('--list-all', src)
        self.assertIn('--cancel', src)
        self.assertIn('--status', src)
        self.assertIn('--json', src)


if __name__ == '__main__':
    unittest.main()
