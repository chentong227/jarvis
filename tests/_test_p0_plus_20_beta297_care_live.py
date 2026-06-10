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

    # 🆕 [fixT-C / Sir 2026-06-11 裁决G-C] β.5.23-A 后 vocab 是阈值真相源
    # (DEFAULT_URGENCY_THRESHOLD = _get_cd(key, _LEVEL_CONF['threshold'])), env
    # preset 降级为 fallback seed. 老断言钉死 env 优先 → vocab 化后过期红.
    # 现代化为守今日双重契约: ① env 仍选中 preset dict (fallback 意图保留);
    # ② 模块常量 = vocab 优先、preset fallback 的精确叠加 (机器 vocab 无关).

    def _reload_and_get(self, level):
        import importlib
        import jarvis_proactive_care
        if level is None:
            os.environ.pop('JARVIS_PROACTIVE_CARE_LEVEL', None)
        else:
            os.environ['JARVIS_PROACTIVE_CARE_LEVEL'] = level
        importlib.reload(jarvis_proactive_care)
        return jarvis_proactive_care

    def test_silent_level_threshold_2(self):
        pc = self._reload_and_get('silent')
        # ① env 选中 silent preset (threshold=2.0 实质禁用)
        self.assertEqual(pc._LEVEL_CONF['threshold'], 2.0)
        # ② 常量 = vocab 优先 + silent preset fallback
        self.assertEqual(pc.DEFAULT_URGENCY_THRESHOLD,
                         pc._get_cd('DEFAULT_URGENCY_THRESHOLD', 2.0))

    def test_high_level_threshold_below_normal(self):
        pc = self._reload_and_get('high')
        # ① env 选中 high preset, preset 自身 high < normal
        self.assertLess(pc._LEVEL_CONF['threshold'],
                        pc._LEVEL_PRESETS['normal']['threshold'])
        # ② 常量 = vocab 优先 + high preset fallback
        self.assertEqual(pc.DEFAULT_URGENCY_THRESHOLD,
                         pc._get_cd('DEFAULT_URGENCY_THRESHOLD',
                                    pc._LEVEL_PRESETS['high']['threshold']))

    def test_default_level_normal(self):
        pc = self._reload_and_get(None)
        self.assertEqual(pc._LEVEL_CONF['threshold'], 0.55)
        self.assertEqual(pc.DEFAULT_URGENCY_THRESHOLD,
                         pc._get_cd('DEFAULT_URGENCY_THRESHOLD', 0.55))


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
