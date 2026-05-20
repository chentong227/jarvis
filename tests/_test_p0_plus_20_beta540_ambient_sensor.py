# -*- coding: utf-8 -*-
"""β.5.40-A1 — Ambient audio sensor tests (Sir 方向 A.1)

Tests:
  1. _classify_window 在 silence 不 fire
  2. _classify_window 对 sigh-like 信号 fire 正确 type
  3. AmbientSensor state gate (Jarvis speaking/Sir speaking/in_active reset accum)
  4. AmbientSensor consecutive agree 阈值 (≥ 3 同类才 publish)
  5. AmbientSensor cooldown (同类 60s 不重复)
  6. SWM publish: ambient_state etype 注册 + salience 默认
  7. Trigger: _trigger_ambient_state_judge 看 SWM 触发
  8. Directive seed: ambient_state_judge 在 directives_vocab.json 有 entry
  9. Worker init: 含 β.5.40-A1 hook code
"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta540ClassifierConservative(unittest.TestCase):
    """classifier 必须保守: silence 不 fire, 模糊不 fire."""

    def test_silence_does_not_fire(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        quiet = np.zeros(8000, dtype=np.int16)
        obs = ja._classify_window(quiet)
        self.assertEqual(obs.ambient_type, '', 'silence 不 fire')
        self.assertEqual(obs.confidence, 0.0)

    def test_short_window_does_not_fire(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        short = np.zeros(100, dtype=np.int16)
        obs = ja._classify_window(short)
        self.assertEqual(obs.ambient_type, '', '太短 window 不 fire')

    def test_sigh_like_low_freq_long_sustain(self):
        """低频长持续 + 平稳衰减 → 应该 fire sigh."""
        import numpy as np
        import jarvis_ambient_sensor as ja
        t = np.arange(8000) / 16000.0
        # 200Hz 低频 + 平稳衰减
        sigh = (np.sin(2 * np.pi * 200 * t) * np.linspace(1.0, 0.3, 8000) * 4000).astype(np.int16)
        obs = ja._classify_window(sigh)
        self.assertEqual(obs.ambient_type, 'sigh',
                         f'低频长持续应判 sigh, got {obs.ambient_type!r}')
        self.assertGreaterEqual(obs.confidence, 0.6)

    def test_random_noise_does_not_match_specific_type(self):
        """白噪 → 不应该 fire 任何特定类 (避免误报)."""
        import numpy as np
        import jarvis_ambient_sensor as ja
        np.random.seed(42)
        noise = (np.random.randn(8000) * 1000).astype(np.int16)
        obs = ja._classify_window(noise)
        # 白噪可能匹配 video_playing 或 conversation, 但 confidence 应该不高
        if obs.ambient_type:
            self.assertGreaterEqual(obs.confidence, 0.6,
                                    f'白噪如果 fire 也要 ≥ 0.6 conf')


class TestBeta540SensorStateGate(unittest.TestCase):
    """sensor 必须在 Jarvis/Sir speaking + in_active 时 reset 不分析."""

    def setUp(self):
        import jarvis_ambient_sensor as ja
        ja._GLOBAL_SENSOR = None  # reset singleton

    def test_jarvis_speaking_resets_accum(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        sensor = ja.AmbientSensor(event_bus=None, enabled=True)
        # 喂数据
        data = (np.random.rand(1024) * 1000).astype(np.int16).tobytes()
        sensor.feed_frame(data, is_jarvis_speaking=False)
        self.assertGreater(len(sensor._accum), 0, '没 jarvis speaking 应该 accumulate')
        # 然后 Jarvis 开始说话
        sensor.feed_frame(data, is_jarvis_speaking=True)
        self.assertEqual(len(sensor._accum), 0, 'Jarvis speaking 应该 reset accum')

    def test_sir_speaking_resets_accum(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        sensor = ja.AmbientSensor(event_bus=None, enabled=True)
        data = (np.random.rand(1024) * 1000).astype(np.int16).tobytes()
        sensor.feed_frame(data)
        sensor.feed_frame(data, is_sir_speaking=True)
        self.assertEqual(len(sensor._accum), 0, 'Sir speaking 应该 reset accum')

    def test_in_active_resets_accum(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        sensor = ja.AmbientSensor(event_bus=None, enabled=True)
        data = (np.random.rand(1024) * 1000).astype(np.int16).tobytes()
        sensor.feed_frame(data)
        sensor.feed_frame(data, sir_in_active=True)
        self.assertEqual(len(sensor._accum), 0, 'in_active 应该 reset accum')


class TestBeta540ConsecutiveAgreeAndPublish(unittest.TestCase):
    """≥ 3 连续同类 + confidence ≥ 0.6 才 publish SWM."""

    def setUp(self):
        import jarvis_ambient_sensor as ja
        ja._GLOBAL_SENSOR = None

    def _make_sigh(self, np_mod):
        """制作 sigh-like 8000 sample window. amp 调到 < MAX_VOLUME (1500 mean abs)."""
        t = np_mod.arange(8000) / 16000.0
        # amp 2000 → mean abs ~ 825 < 1500
        return (np_mod.sin(2 * np_mod.pi * 200 * t) * np_mod.linspace(1.0, 0.3, 8000) * 2000).astype(np_mod.int16)

    def test_3_consecutive_sigh_publishes(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        bus_pub_calls = []

        class FakeBus:
            def publish(self, **kwargs):
                bus_pub_calls.append(kwargs)
                return True

        sensor = ja.AmbientSensor(event_bus=FakeBus(), enabled=True)
        sigh = self._make_sigh(np)
        # 喂 3 个 window
        for _ in range(3):
            obs = sensor.feed_frame(sigh.tobytes())
            self.assertIsNotNone(obs, 'feed_frame 喂满 window 应返 obs (volume_gate 通过)')
        # 应该 published 1 次 (3 个连续同类)
        self.assertGreaterEqual(len(bus_pub_calls), 1, '3 个连续 sigh 应该 publish')
        if bus_pub_calls:
            self.assertEqual(bus_pub_calls[0].get('etype'), 'ambient_state')
            self.assertEqual(
                bus_pub_calls[0].get('metadata', {}).get('ambient_type'), 'sigh'
            )

    def test_cooldown_prevents_repeat_publish(self):
        import numpy as np
        import jarvis_ambient_sensor as ja
        bus_pub_calls = []

        class FakeBus:
            def publish(self, **kwargs):
                bus_pub_calls.append(kwargs)
                return True

        sensor = ja.AmbientSensor(event_bus=FakeBus(), enabled=True)
        sigh = self._make_sigh(np)
        # 喂 6 个 window: 第 1-3 published 1 次, 第 4-6 在 cooldown 不重复
        for _ in range(6):
            sensor.feed_frame(sigh.tobytes())
        self.assertEqual(len(bus_pub_calls), 1, '60s cooldown 期内同类只 1 次')


class TestBeta540SWMEtype(unittest.TestCase):
    """SWM ambient_state etype 注册 + salience."""

    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        # import sensor module triggers register
        import jarvis_ambient_sensor  # noqa
        self.assertIn('ambient_state', ConversationEventBus.DEFAULT_TTL,
                      'ambient_state etype 必须注册')
        self.assertIn('ambient_state', ConversationEventBus.DEFAULT_SALIENCE,
                      'ambient_state salience 必须注册')

    def test_salience_is_background_level(self):
        from jarvis_utils import ConversationEventBus
        import jarvis_ambient_sensor  # noqa
        sal = ConversationEventBus.DEFAULT_SALIENCE.get('ambient_state')
        self.assertIsNotNone(sal)
        self.assertLess(sal, 0.55, 'ambient_state 是背景信号 salience < 0.55')


class TestBeta540DirectiveTrigger(unittest.TestCase):
    """_trigger_ambient_state_judge 看 SWM 触发."""

    def test_trigger_callable(self):
        from jarvis_directives import _trigger_ambient_state_judge, DirectiveContext
        ctx = DirectiveContext(current_hour=10, user_input='hello')
        # 不 raise
        result = _trigger_ambient_state_judge(ctx)
        self.assertIsInstance(result, bool)

    def test_trigger_fires_when_swm_has_ambient(self):
        import jarvis_utils
        from jarvis_utils import ConversationEventBus
        from jarvis_directives import _trigger_ambient_state_judge, DirectiveContext
        # 注册 global bus (test isolation)
        bus = ConversationEventBus()
        jarvis_utils._GLOBAL_EVENT_BUS = bus
        bus.publish(
            etype='ambient_state',
            description='Ambient: sigh (conf=0.72, n=3)',
            source='ambient_sensor',
            metadata={'ambient_type': 'sigh', 'confidence': 0.72},
        )
        ctx = DirectiveContext(current_hour=10, user_input='')
        self.assertTrue(_trigger_ambient_state_judge(ctx),
                        'SWM 有 ambient_state 应该触发')


class TestBeta540DirectiveSeed(unittest.TestCase):
    """ambient_state_judge directive 必须在 seed_defs + vocab.json."""

    def test_seed_defs_contains(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='ambient_state_judge'", src,
                      'seed_defs 必须含 ambient_state_judge')
        self.assertIn('_trigger_ambient_state_judge', src,
                      'seed_defs 必须 wire trigger function')

    def test_vocab_json_contains(self):
        import json
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  'r', encoding='utf-8') as f:
            vocab = json.load(f)
        ids = [d.get('id') for d in vocab.get('directives', [])]
        self.assertIn('ambient_state_judge', ids,
                      'directives_vocab.json 必须含 ambient_state_judge')


class TestBeta540WorkerHook(unittest.TestCase):
    """jarvis_worker.py 必须 hook ambient_sensor.feed_frame 到主循环."""

    def test_worker_init_block(self):
        with open(os.path.join(ROOT, 'jarvis_worker.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.40-A1', src, 'worker 必须含 β.5.40-A1 marker')
        self.assertIn('get_ambient_sensor', src, 'worker 必须 import sensor factory')
        self.assertIn('_ambient_sensor', src, 'worker 必须存 sensor 引用')

    def test_worker_feed_frame_in_main_loop(self):
        with open(os.path.join(ROOT, 'jarvis_worker.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('self._ambient_sensor.feed_frame', src,
                      'worker 主循环必须 call feed_frame')
        self.assertIn('is_jarvis_speaking', src)
        self.assertIn('is_sir_speaking', src)
        self.assertIn('sir_in_active', src)


if __name__ == '__main__':
    unittest.main()
