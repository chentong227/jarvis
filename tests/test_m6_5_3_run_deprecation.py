# -*- coding: utf-8 -*-
"""[Reshape M3.G 真删 / 2026-05-24 17:00] CentralNerve.run() 3-brain 真删验证.

历史: 老 M6.5.3 stub 验证 run() 走 raise + except 路径.
本 test 升级为 验证 run() method 已彻底删除 (M3.G 真删).

Sir 真测 SWM deprecated_3_brain_invoked event = 0 → 主脑 prompt 不再 emit
<ENGAGE_PHYSICAL_BODY> token → route_callback 永不触发 → run() 永不被调.
物理删除路径:
  1. CentralNerve.run() 删
  2. CentralNerve._init_3_brain_legacy 删
  3. CentralNerve 顶部 RightBrain/LeftBrain/ReflectionBrain = None 声明删
  4. worker.trigger_routing 删 + stream_chat route_callback=None
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestRunMethodDeleted(unittest.TestCase):
    """M3.G 真删: CentralNerve.run() / _init_3_brain_legacy / 3 brain attr 都删了."""

    def test_run_method_removed(self):
        """CentralNerve.run() 不应再存在."""
        from jarvis_central_nerve import CentralNerve
        self.assertFalse(
            hasattr(CentralNerve, 'run'),
            'M3.G 真删未完成: CentralNerve.run() 仍存在'
        )

    def test_init_3_brain_legacy_removed(self):
        """CentralNerve._init_3_brain_legacy method 不应再存在."""
        from jarvis_central_nerve import CentralNerve
        self.assertFalse(
            hasattr(CentralNerve, '_init_3_brain_legacy'),
            'M3.G 真删未完成: _init_3_brain_legacy method 仍存在'
        )

    def test_3_brain_classes_not_in_module(self):
        """jarvis_central_nerve 模块顶部不应再有 RightBrain/LeftBrain/ReflectionBrain 声明.

        老顶部有 'RightBrain = None' 等声明 (None placeholder 兼容老测试). 真删后
        这些名字应该完全没 import / 没 placeholder. 主对话 100% chat_bypass 单脑.
        """
        import jarvis_central_nerve as cn
        # 这 3 个名字不应再在模块 namespace (M3.G 真删彻底清理)
        self.assertFalse(
            hasattr(cn, 'RightBrain'),
            'M3.G 真删未完成: jarvis_central_nerve.RightBrain 仍存在'
        )
        self.assertFalse(
            hasattr(cn, 'LeftBrain'),
            'M3.G 真删未完成: jarvis_central_nerve.LeftBrain 仍存在'
        )
        self.assertFalse(
            hasattr(cn, 'ReflectionBrain'),
            'M3.G 真删未完成: jarvis_central_nerve.ReflectionBrain 仍存在'
        )
        self.assertFalse(
            hasattr(cn, 'L5Brain'),
            'M3.G 真删未完成: jarvis_central_nerve.L5Brain 仍存在'
        )

    def test_worker_trigger_routing_removed(self):
        """jarvis_worker 里 trigger_routing closure 已删, route_callback 传 None."""
        with open(
            os.path.join(ROOT, 'jarvis_worker.py'), 'r', encoding='utf-8'
        ) as f:
            src = f.read()
        # 不应再有 'def trigger_routing' closure
        self.assertNotIn(
            'def trigger_routing',
            src,
            'M3.G 真删未完成: jarvis_worker.py 里 trigger_routing closure 仍存在'
        )
        # 也不应再有 'route_callback=trigger_routing' 调用
        self.assertNotIn(
            'route_callback=trigger_routing',
            src,
            'M3.G 真删未完成: jarvis_worker.py 里 route_callback=trigger_routing 仍存在'
        )


if __name__ == '__main__':
    unittest.main()
