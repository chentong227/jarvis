# -*- coding: utf-8 -*-
"""[Gap-Z3 / β.5.46-fix11] Reflector Budget 测试."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _patch_paths(test_obj):
    """每个 test 独立 tmp config + state. 装到 test_obj 末尾 tearDown 用."""
    import jarvis_reflector_budget as _mod
    test_obj._tmp_dir = tempfile.mkdtemp()
    test_obj._cfg_path = os.path.join(test_obj._tmp_dir, 'cfg.json')
    test_obj._st_path = os.path.join(test_obj._tmp_dir, 'st.json')
    # 写默认 config
    with open(test_obj._cfg_path, 'w', encoding='utf-8') as f:
        json.dump({
            'enabled': True, 'weekly_cap_total': 10,
            'per_reflector_cap': {'limited_one': 2},
        }, f)
    test_obj._patches = [
        mock.patch.object(_mod, '_CONFIG_PATH', test_obj._cfg_path),
        mock.patch.object(_mod, '_STATE_PATH', test_obj._st_path),
    ]
    for p in test_obj._patches:
        p.start()
    _mod.reset_for_test()


def _unpatch(test_obj):
    for p in test_obj._patches:
        p.stop()
    try:
        if os.path.exists(test_obj._cfg_path):
            os.unlink(test_obj._cfg_path)
        if os.path.exists(test_obj._st_path):
            os.unlink(test_obj._st_path)
        os.rmdir(test_obj._tmp_dir)
    except Exception:
        pass


class TestA_AcquireUnderCap(unittest.TestCase):

    def setUp(self):
        _patch_paths(self)

    def tearDown(self):
        _unpatch(self)

    def test_acquire_succeeds_when_under_cap(self):
        from jarvis_reflector_budget import get_default_budget
        b = get_default_budget()
        for _ in range(3):
            self.assertTrue(b.acquire('test_reflector', 1))


class TestB_WeeklyCapHit(unittest.TestCase):

    def setUp(self):
        _patch_paths(self)

    def tearDown(self):
        _unpatch(self)

    def test_weekly_cap_blocks(self):
        from jarvis_reflector_budget import get_default_budget
        b = get_default_budget()
        # weekly_cap=10, 用 10 个就到顶
        for _ in range(10):
            self.assertTrue(b.acquire('r1', 1))
        # 第 11 次 fail
        self.assertFalse(b.acquire('r1', 1))


class TestC_PerReflectorCap(unittest.TestCase):

    def setUp(self):
        _patch_paths(self)

    def tearDown(self):
        _unpatch(self)

    def test_per_cap_enforced(self):
        from jarvis_reflector_budget import get_default_budget
        b = get_default_budget()
        # 'limited_one' per_cap=2
        self.assertTrue(b.acquire('limited_one', 1))
        self.assertTrue(b.acquire('limited_one', 1))
        self.assertFalse(b.acquire('limited_one', 1),
                          'limited_one 应在 2 次后达 cap')
        # 别的 reflector 仍可
        self.assertTrue(b.acquire('other_one', 1))


class TestD_StatsTracking(unittest.TestCase):

    def setUp(self):
        _patch_paths(self)

    def tearDown(self):
        _unpatch(self)

    def test_stats_correct(self):
        from jarvis_reflector_budget import get_default_budget
        b = get_default_budget()
        b.acquire('r1', 1)
        b.acquire('r1', 1)
        b.acquire('r2', 1)
        s = b.stats()
        self.assertEqual(s['total_used'], 3)
        self.assertEqual(s['usage_by_name']['r1'], 2)
        self.assertEqual(s['usage_by_name']['r2'], 1)
        self.assertEqual(s['remaining'], 7)


class TestE_WindowReset(unittest.TestCase):

    def setUp(self):
        _patch_paths(self)

    def tearDown(self):
        _unpatch(self)

    def test_reset_clears_usage(self):
        from jarvis_reflector_budget import get_default_budget
        b = get_default_budget()
        b.acquire('r1', 5)
        self.assertEqual(b.stats()['total_used'], 5)
        b.reset_window()
        self.assertEqual(b.stats()['total_used'], 0)


class TestF_DisabledMode(unittest.TestCase):

    def setUp(self):
        import jarvis_reflector_budget as _mod
        self._tmp_dir = tempfile.mkdtemp()
        self._cfg_path = os.path.join(self._tmp_dir, 'cfg.json')
        self._st_path = os.path.join(self._tmp_dir, 'st.json')
        with open(self._cfg_path, 'w', encoding='utf-8') as f:
            json.dump({
                'enabled': False, 'weekly_cap_total': 1,
            }, f)
        self._patches = [
            mock.patch.object(_mod, '_CONFIG_PATH', self._cfg_path),
            mock.patch.object(_mod, '_STATE_PATH', self._st_path),
        ]
        for p in self._patches:
            p.start()
        _mod.reset_for_test()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        try:
            if os.path.exists(self._cfg_path):
                os.unlink(self._cfg_path)
            if os.path.exists(self._st_path):
                os.unlink(self._st_path)
            os.rmdir(self._tmp_dir)
        except Exception:
            pass

    def test_disabled_always_passes(self):
        from jarvis_reflector_budget import get_default_budget
        b = get_default_budget()
        for _ in range(50):
            self.assertTrue(b.acquire('r1', 1),
                             'disabled mode 应永远 pass')


if __name__ == '__main__':
    unittest.main()
