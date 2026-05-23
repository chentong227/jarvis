# -*- coding: utf-8 -*-
"""[P5-fix35-D / 2026-05-23 11:30] ProgressTracker tests.

Sir 真痛点: 主脑承诺"我会记到饮水记录" — 没真 store. 治本: 加 progress organ.

覆盖:
A. ProgressTrackerStore — register/update/cancel/status/list
B. chat_bypass FAST_CALL progress organ handler (静态扫源)
C. progress_tracker_dispatcher directive + trigger + vocab
D. CLI scripts/progress_dump.py
E. cyclic_task 联动 (linked_cyclic_task 满 auto-cancel)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ============================================================
# A. ProgressTrackerStore unit tests
# ============================================================

class TestAProgressTrackerStore(unittest.TestCase):

    def setUp(self):
        from jarvis_progress_tracker import (
            ProgressTrackerStore, reset_default_store_for_test
        )
        reset_default_store_for_test()
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8').name
        os.remove(self.tmpfile)
        self.store = ProgressTrackerStore(log_path=self.tmpfile)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_register_basic(self):
        r = self.store.register(
            track_id='hyd1', kind='hydration', label='今日饮水',
            target=3000, unit='ml')
        self.assertTrue(r['ok'])
        self.assertEqual(r['target'], 3000)

    def test_register_dup_active_rejected(self):
        self.store.register(track_id='dup', kind='x',
                              target=100, unit='unit')
        r = self.store.register(track_id='dup', kind='x',
                                   target=200, unit='unit')
        self.assertFalse(r['ok'])
        self.assertIn('已 active', r['error'])

    def test_update_accumulates(self):
        self.store.register(track_id='hyd', kind='hydration',
                              target=3000, unit='ml')
        r1 = self.store.update(track_id='hyd', amount=500, note='lunch')
        self.assertTrue(r1['ok'])
        self.assertEqual(r1['current'], 500)
        self.assertAlmostEqual(r1['progress_ratio'], 500/3000)
        self.assertEqual(r1['remaining'], 2500)

        r2 = self.store.update(track_id='hyd', amount=300)
        self.assertEqual(r2['current'], 800)
        self.assertEqual(r2['remaining'], 2200)

    def test_update_unknown_track(self):
        r = self.store.update(track_id='nope', amount=100)
        self.assertFalse(r['ok'])
        self.assertIn('不存在', r['error'])

    def test_completion_flips_state(self):
        self.store.register(track_id='hyd', kind='hydration',
                              target=1000, unit='ml')
        r = self.store.update(track_id='hyd', amount=1500)  # over target
        self.assertTrue(r['became_complete'])
        self.assertEqual(r['state'], 'completed')

    def test_completion_cancels_linked_cycle(self):
        # mock cyclic_task store
        from jarvis_cyclic_task import (
            CyclicTaskStore, register_default_store as ct_register,
            reset_default_store_for_test as ct_reset,
        )
        ct_reset()
        ct_tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8').name
        os.remove(ct_tmpfile)
        ct_store = CyclicTaskStore(protocol_path=ct_tmpfile, hippocampus=None)
        ct_register(ct_store)

        from datetime import date
        today = date.today().strftime('%Y-%m-%d')
        ct_r = ct_store.register(
            task_id='hyd_cycle', kind='reminder', description='x',
            cycle_minutes=60,
            start_at=f'{today} 14:00', end_at=f'{today} 18:00',
            intent_template='drink')
        self.assertTrue(ct_r['ok'])

        # progress with linked cycle
        self.store.register(
            track_id='hyd_p', kind='hydration', target=1000, unit='ml',
            linked_cyclic_task='hyd_cycle')

        # update to completion
        r = self.store.update(track_id='hyd_p', amount=1500)
        self.assertTrue(r['became_complete'])
        self.assertEqual(r.get('cancelled_linked_cycle'), 'hyd_cycle')
        # verify cycle is now cancelled
        self.assertEqual(ct_store.get('hyd_cycle').state, 'cancelled')

        os.remove(ct_tmpfile) if os.path.exists(ct_tmpfile) else None

    def test_cancel(self):
        self.store.register(track_id='c1', kind='x', target=10, unit='u')
        r = self.store.cancel('c1', reason='test')
        self.assertTrue(r['ok'])
        t = self.store.get('c1')
        self.assertEqual(t.state, 'cancelled')

    def test_persist_roundtrip(self):
        from jarvis_progress_tracker import ProgressTrackerStore
        self.store.register(track_id='persist',
                              kind='running', target=5, unit='km')
        self.store.update(track_id='persist', amount=2.5, note='warmup')
        store2 = ProgressTrackerStore(log_path=self.tmpfile)
        t = store2.get('persist')
        self.assertIsNotNone(t)
        self.assertEqual(t.kind, 'running')
        self.assertEqual(t.current, 2.5)
        self.assertEqual(len(t.history), 1)

    def test_render_brief(self):
        self.store.register(track_id='b', kind='hydration',
                              target=3000, unit='ml')
        self.store.update(track_id='b', amount=500)
        t = self.store.get('b')
        brief = t.render_brief()
        self.assertIn('500', brief)
        self.assertIn('3000', brief)
        self.assertIn('ml', brief)
        self.assertIn('余', brief)


# ============================================================
# B. chat_bypass FAST_CALL handler (static scan)
# ============================================================

class TestBChatBypassOrgan(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'),
                   'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_organ_handler_present(self):
        self.assertIn('organ_name == "progress"', self.src)

    def test_uses_progress_tracker_store(self):
        self.assertIn('from jarvis_progress_tracker import', self.src)

    def test_supports_register_update_status(self):
        self.assertIn("command == 'register'", self.src)
        self.assertIn("command == 'update'", self.src)
        self.assertIn("command == 'status'", self.src)


# ============================================================
# C. directive + vocab
# ============================================================

class TestCDirective(unittest.TestCase):

    def test_directive_registered(self):
        import jarvis_directives as jd
        reg = jd.get_default_registry()
        d = reg.get('progress_tracker_dispatcher')
        self.assertIsNotNone(d, 'progress_tracker_dispatcher not registered')
        self.assertEqual(d.id, 'progress_tracker_dispatcher')
        self.assertEqual(d.source_marker, 'P5-fix35-D')

    def test_directive_text_keywords(self):
        import jarvis_directives as jd
        reg = jd.get_default_registry()
        d = reg.get('progress_tracker_dispatcher')
        self.assertIsNotNone(d)
        self.assertIn('progress', d.text)
        self.assertIn('FAST_CALL', d.text)
        self.assertIn('register', d.text)
        self.assertIn('update', d.text)
        self.assertIn('hydration', d.text)
        self.assertIn('running', d.text)

    def test_trigger_fires_on_chinese(self):
        import jarvis_directives as jd
        jd._PROGRESS_CACHE = None
        jd._PROGRESS_MTIME = 0.0
        from jarvis_directives import (
            _trigger_progress_tracker_dispatcher, DirectiveContext
        )
        # 🆕 [P5-fix49 / 2026-05-23 15:25] vocab 收紧后, '还差多少' 移除. 仍 fire 的:
        # 数值 progress 强信号 (动词 + 单位).
        for phrase in ['我刚喝了 500 毫升水',
                          '今天目标 3000ml',
                          '还差 2 公里',  # '还差' kept
                          '我跑了 3 公里']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_progress_tracker_dispatcher(ctx),
                              f'should fire on: {phrase}')

    def test_trigger_fires_on_english(self):
        import jarvis_directives as jd
        jd._PROGRESS_CACHE = None
        from jarvis_directives import (
            _trigger_progress_tracker_dispatcher, DirectiveContext
        )
        # 🆕 [P5-fix49] 'log it for me' 移除 (vocab 收紧 — log 太通用), 改用具体 progress 短语
        for phrase in ['i drank 500ml',
                          'i ran 3km today',
                          'i wrote 800 words']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertTrue(_trigger_progress_tracker_dispatcher(ctx),
                              f'should fire on: {phrase}')

    def test_fix49_no_misfire_on_mutation_phrases(self):
        """[P5-fix49] Sir 14:51 真痛点: '我中午睡了 1h, 你记录一下' 不该 fire progress."""
        import jarvis_directives as jd
        jd._PROGRESS_CACHE = None
        from jarvis_directives import (
            _trigger_progress_tracker_dispatcher, DirectiveContext
        )
        # 这些是 mutation/correction 信号, 不该 fire progress tracker
        for phrase in ['你现在记录一下我中午睡了一个小时',
                          '帮我登记这件事',
                          '做了 / 完成了 / 我做完了',  # 通用 verb 不带数值单位
                          '今天什么时候睡的']:
            ctx = DirectiveContext(user_input=phrase, tier='CHAT', stm=[])
            self.assertFalse(_trigger_progress_tracker_dispatcher(ctx),
                                f'should NOT fire (no numeric progress signal): {phrase}')

    def test_trigger_skip_unrelated(self):
        import jarvis_directives as jd
        jd._PROGRESS_CACHE = None
        from jarvis_directives import (
            _trigger_progress_tracker_dispatcher, DirectiveContext
        )
        ctx = DirectiveContext(user_input='what time is it',
                                  tier='CHAT', stm=[])
        self.assertFalse(_trigger_progress_tracker_dispatcher(ctx))

    def test_vocab_persistence(self):
        path = os.path.join(ROOT, 'memory_pool',
                              'progress_tracker_dispatcher_vocab.json')
        self.assertTrue(os.path.exists(path),
                          'vocab JSON 必须持久化 (准则 6)')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('patterns', data)
        self.assertGreater(len(data['patterns']), 15)


# ============================================================
# D. CLI
# ============================================================

class TestDCLI(unittest.TestCase):

    def test_cli_exists(self):
        path = os.path.join(ROOT, 'scripts', 'progress_dump.py')
        self.assertTrue(os.path.exists(path),
                          'progress_dump.py 必须存在 (准则 6 CLI 可改)')

    def test_cli_actions(self):
        path = os.path.join(ROOT, 'scripts', 'progress_dump.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        for arg in ('--list-all', '--status', '--update', '--cancel', '--json'):
            self.assertIn(arg, src, f'CLI missing {arg}')


if __name__ == '__main__':
    unittest.main()
