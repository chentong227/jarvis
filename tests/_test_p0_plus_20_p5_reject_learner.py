# -*- coding: utf-8 -*-
"""[Gap 5 / β.5.46-fix10 / 2026-05-22 00:10] Reject Learner 测试."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_reject_learner import (
    RejectLearner,
    is_enabled,
    register_learner,
    get_default_learner,
    reset_default_learner_for_test,
    list_review_queue,
    update_review_status,
    _read_recent_rejects,
    _propose_id,
    _load_config,
)


class TestA_Config(unittest.TestCase):

    def test_config_loads_with_defaults(self):
        cfg = _load_config()
        self.assertIn('enabled', cfg)
        self.assertIn('cycle_interval_hours', cfg)
        self.assertIn('min_reject_count', cfg)

    def test_env_disable(self):
        with mock.patch.dict(os.environ, {'JARVIS_REJECT_LEARNER': '0'}):
            self.assertFalse(is_enabled())


class TestB_ReadRejects(unittest.TestCase):

    def test_filter_only_negative_verdicts(self):
        # mock _FEEDBACK_PATH 用临时文件
        import jarvis_reject_learner as _mod
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                           delete=False, encoding='utf-8') as f:
            entries = [
                {'ts': time.time(), 'verdict': 'good', 'reply_excerpt': 'Yes Sir'},
                {'ts': time.time(), 'verdict': 'bad', 'reply_excerpt': 'apology'},
                {'ts': time.time(), 'verdict': 'silent_wanted', 'reply_excerpt': 'silent'},
                {'ts': time.time(), 'verdict': 'edit', 'reply_excerpt': 'edited'},
            ]
            for e in entries:
                f.write(json.dumps(e) + '\n')
            tmp = f.name
        try:
            with mock.patch.object(_mod, '_FEEDBACK_PATH', tmp):
                rejects = _read_recent_rejects(hours=24.0)
            self.assertEqual(len(rejects), 3,
                             '应过滤出 bad/silent_wanted/edit 三种, 不含 good')
            verdicts = {r['verdict'] for r in rejects}
            self.assertEqual(verdicts, {'bad', 'silent_wanted', 'edit'})
        finally:
            os.unlink(tmp)

    def test_filter_old_entries_excluded(self):
        import jarvis_reject_learner as _mod
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                           delete=False, encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': time.time() - 30 * 3600,  # 30h 前
                'verdict': 'bad', 'reply_excerpt': 'old',
            }) + '\n')
            f.write(json.dumps({
                'ts': time.time() - 1 * 3600,
                'verdict': 'bad', 'reply_excerpt': 'recent',
            }) + '\n')
            tmp = f.name
        try:
            with mock.patch.object(_mod, '_FEEDBACK_PATH', tmp):
                rejects = _read_recent_rejects(hours=24.0)
            self.assertEqual(len(rejects), 1)
            self.assertEqual(rejects[0]['reply_excerpt'], 'recent')
        finally:
            os.unlink(tmp)


class TestC_ProposeIdConsistent(unittest.TestCase):

    def test_same_rejects_same_id(self):
        rejects = [
            {'ts': 1000.0, 'verdict': 'bad', 'reply_excerpt': 'a' * 50},
            {'ts': 2000.0, 'verdict': 'edit', 'reply_excerpt': 'b' * 50},
        ]
        id1 = _propose_id(rejects)
        id2 = _propose_id(rejects)
        self.assertEqual(id1, id2)
        self.assertTrue(id1.startswith('rl_'))


class TestD_RunCycleSkipsBelowMin(unittest.TestCase):

    def test_skip_when_too_few(self):
        import jarvis_reject_learner as _mod
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                           delete=False, encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': time.time(),
                'verdict': 'bad', 'reply_excerpt': 'a' * 50,
            }) + '\n')
            tmp = f.name
        try:
            with mock.patch.object(_mod, '_FEEDBACK_PATH', tmp):
                learner = RejectLearner()
                # min_reject_count = 3 in config, only 1 reject
                result = learner.run_cycle(force=True)
                self.assertIsNone(result, '少于 min 应 skip')
        finally:
            os.unlink(tmp)


class TestE_ReviewQueue(unittest.TestCase):

    def setUp(self):
        import jarvis_reject_learner as _mod
        self._tmp_dir = tempfile.mkdtemp()
        self._tmp_review = os.path.join(self._tmp_dir, 'review.json')
        self._patcher = mock.patch.object(_mod, '_REVIEW_PATH', self._tmp_review)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        try:
            if os.path.exists(self._tmp_review):
                os.unlink(self._tmp_review)
            os.rmdir(self._tmp_dir)
        except Exception:
            pass

    def test_list_empty_initially(self):
        self.assertEqual(list_review_queue(), [])

    def test_update_review_status_pending(self):
        import jarvis_reject_learner as _mod
        # write a propose
        _mod._save_review_queue([{
            'id': 'rl_test1', 'status': 'pending',
            'propose': {'propose_type': 'directive_amend'},
        }])
        ok = update_review_status('rl_test1', 'accepted', sir_note='good')
        self.assertTrue(ok)
        queue = _mod._load_review_queue()
        self.assertEqual(queue[0]['status'], 'accepted')
        self.assertIn('sir_note', queue[0])

    def test_update_invalid_id(self):
        ok = update_review_status('rl_nonexistent', 'accepted')
        self.assertFalse(ok)


class TestF_Singleton(unittest.TestCase):

    def setUp(self):
        reset_default_learner_for_test()

    def test_register_get(self):
        learner = RejectLearner()
        register_learner(learner)
        self.assertIs(get_default_learner(), learner)

    def tearDown(self):
        reset_default_learner_for_test()


class TestG_StaticIntegration(unittest.TestCase):

    def test_central_nerve_registers_learner(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_reject_learner import', src)
        self.assertIn('register_learner', src)
        self.assertIn('self.reject_learner', src)

    def test_config_file_exists(self):
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'reject_learner_config.json',
        )
        self.assertTrue(os.path.exists(cfg_path))


if __name__ == '__main__':
    unittest.main()
