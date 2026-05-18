# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.7 / 2026-05-18] ProactiveCare LIVE 默认 + SmartNudge disable 开关

切换点:
  jarvis_proactive_care.py: dry_run 默认 OFF (LIVE), 改 env JARVIS_PROACTIVE_CARE_DRY_RUN=1 才进 dry
  jarvis_routing.py CompanionCenter.start_all:
    - env JARVIS_SMARTNUDGE_DISABLE=1 跳过 SmartNudge 启动
    - 启动 banner 集中显示状态

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta297_care_live.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestProactiveCareDryRunDefault(unittest.TestCase):
    """dry_run 默认从 ON → OFF (LIVE) 的契约."""

    def setUp(self):
        # 清环境变量, 测默认行为
        for key in ('JARVIS_PROACTIVE_CARE_DRY_RUN',
                    'JARVIS_PROACTIVE_CARE_LIVE',
                    'JARVIS_PROACTIVE_CARE_LEVEL'):
            os.environ.pop(key, None)
        # reset module singleton
        from jarvis_proactive_care import reset_default_engine_for_test
        reset_default_engine_for_test()

    def tearDown(self):
        from jarvis_proactive_care import reset_default_engine_for_test
        reset_default_engine_for_test()

    def test_dry_run_default_is_false_live_mode(self):
        from jarvis_proactive_care import ProactiveCareEngine
        worker = MagicMock()
        engine = ProactiveCareEngine(worker, None)
        self.assertFalse(engine.dry_run,
                          'β.2.9.7 起 ProactiveCare 默认 LIVE (dry_run=False)')

    def test_dry_run_opt_in_via_env(self):
        os.environ['JARVIS_PROACTIVE_CARE_DRY_RUN'] = '1'
        from jarvis_proactive_care import ProactiveCareEngine
        worker = MagicMock()
        engine = ProactiveCareEngine(worker, None)
        self.assertTrue(engine.dry_run,
                         'JARVIS_PROACTIVE_CARE_DRY_RUN=1 应进 dry 模式')

    def test_dry_run_env_zero_means_live(self):
        os.environ['JARVIS_PROACTIVE_CARE_DRY_RUN'] = '0'
        from jarvis_proactive_care import ProactiveCareEngine
        worker = MagicMock()
        engine = ProactiveCareEngine(worker, None)
        self.assertFalse(engine.dry_run)


class TestProactiveCareLevelPresets(unittest.TestCase):
    """JARVIS_PROACTIVE_CARE_LEVEL 老开关仍可用."""

    def tearDown(self):
        for key in ('JARVIS_PROACTIVE_CARE_DRY_RUN',
                    'JARVIS_PROACTIVE_CARE_LEVEL'):
            os.environ.pop(key, None)

    def test_silent_level_threshold_2(self):
        os.environ['JARVIS_PROACTIVE_CARE_LEVEL'] = 'silent'
        # _LEVEL_CONF 在 import time 求值, 需要 reload
        import importlib
        import jarvis_proactive_care
        importlib.reload(jarvis_proactive_care)
        self.assertEqual(jarvis_proactive_care.DEFAULT_URGENCY_THRESHOLD, 2.0)

    def test_high_level_threshold_below_normal(self):
        os.environ['JARVIS_PROACTIVE_CARE_LEVEL'] = 'high'
        import importlib
        import jarvis_proactive_care
        importlib.reload(jarvis_proactive_care)
        self.assertLess(jarvis_proactive_care.DEFAULT_URGENCY_THRESHOLD, 0.55)

    def test_default_level_normal(self):
        os.environ.pop('JARVIS_PROACTIVE_CARE_LEVEL', None)
        import importlib
        import jarvis_proactive_care
        importlib.reload(jarvis_proactive_care)
        self.assertEqual(jarvis_proactive_care.DEFAULT_URGENCY_THRESHOLD, 0.55)


class TestSmartNudgeDisableSwitchExists(unittest.TestCase):
    """jarvis_routing.py CompanionCenter.start_all 必须读 env JARVIS_SMARTNUDGE_DISABLE."""

    @classmethod
    def setUpClass(cls):
        import inspect
        from jarvis_routing import CompanionCenter
        cls.src = inspect.getsource(CompanionCenter.start_all)

    def test_smartnudge_disable_env_var_referenced(self):
        self.assertIn('JARVIS_SMARTNUDGE_DISABLE', self.src,
                       'CompanionCenter.start_all 必须读 JARVIS_SMARTNUDGE_DISABLE')

    def test_banner_emitted(self):
        self.assertIn('daemon banner', self.src.lower() + 'daemon banner',
                       '启动 banner 应输出')
        self.assertIn('CompanionCenter', self.src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
