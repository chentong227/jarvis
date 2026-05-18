# -*- coding: utf-8 -*-
"""
[P0+20-β.4.8 / 2026-05-19] AcousticWakeDetector (openWakeWord) 测试套件

覆盖:
- vocab 加载 (mtime cache / seed fallback / 损坏)
- AcousticWakeDetector.create (各种 fail-safe 路径)
- process / feed_pyaudio_buffer 行为
- 准则 6.5 红线 (vocab 在 memory_pool/, 无 .py 硬编码 wakeword)
- 单例 get / reset
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# Vocab loader
# ==========================================================================

class TestP0Plus20Beta48VocabLoader(unittest.TestCase):
    def setUp(self):
        from jarvis_acoustic_wake import _MIC_VOCAB_CACHE
        _MIC_VOCAB_CACHE['mtime'] = 0.0
        _MIC_VOCAB_CACHE['data'] = None

    def test_vocab_file_exists(self):
        p = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')
        self.assertTrue(os.path.exists(p), 'memory_pool/mic_safety_vocab.json 必须存在')
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('_meta', data)
        self.assertIn('thresholds', data['_meta'])

    def test_load_thresholds_has_all_required_keys(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _SEED_THRESHOLDS
        thr = load_mic_safety_thresholds()
        for k in _SEED_THRESHOLDS:
            self.assertIn(k, thr, f'thresholds 缺字段 {k}')

    def test_load_thresholds_types(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds
        thr = load_mic_safety_thresholds()
        self.assertIsInstance(thr['acoustic_wake_enabled'], bool)
        self.assertIsInstance(thr['openwakeword_model'], str)
        self.assertIsInstance(thr['openwakeword_threshold'], float)
        self.assertIsInstance(thr['openwakeword_frame_length'], int)
        self.assertGreater(thr['openwakeword_threshold'], 0.0)
        self.assertLessEqual(thr['openwakeword_threshold'], 1.0)

    def test_is_acoustic_wake_enabled_default_false(self):
        """β.4.8 P1: 默认 vocab.enabled=false (灰度开关). Sir 真机调通后才 true."""
        from jarvis_acoustic_wake import is_acoustic_wake_enabled
        self.assertFalse(is_acoustic_wake_enabled(),
            'β.4.8 P1 默认 acoustic_wake_enabled=false 防止破坏现 wake')

    def test_seed_fallback_when_missing(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _SEED_THRESHOLDS
        import jarvis_acoustic_wake as mod
        original_path = mod._MIC_VOCAB_PATH
        mod._MIC_VOCAB_PATH = '/nonexistent/file/xyz.json'
        try:
            thr = load_mic_safety_thresholds()
            for k, v in _SEED_THRESHOLDS.items():
                self.assertEqual(thr[k], v, f'seed fallback 字段 {k} 不对')
        finally:
            mod._MIC_VOCAB_PATH = original_path

    def test_corrupt_vocab_falls_back_to_seed(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _SEED_THRESHOLDS
        import jarvis_acoustic_wake as mod
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            f.write('{not valid json')
            tmppath = f.name
        original_path = mod._MIC_VOCAB_PATH
        mod._MIC_VOCAB_PATH = tmppath
        mod._MIC_VOCAB_CACHE['mtime'] = 0.0
        mod._MIC_VOCAB_CACHE['data'] = None
        try:
            thr = load_mic_safety_thresholds()
            self.assertEqual(thr['acoustic_wake_enabled'],
                             _SEED_THRESHOLDS['acoustic_wake_enabled'])
        finally:
            mod._MIC_VOCAB_PATH = original_path
            os.unlink(tmppath)

    def test_mtime_cache_avoids_reread(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _MIC_VOCAB_CACHE
        load_mic_safety_thresholds()
        self.assertIsNotNone(_MIC_VOCAB_CACHE['data'])
        self.assertGreater(_MIC_VOCAB_CACHE['mtime'], 0.0)


# ==========================================================================
# Detector create / fail-safe
# ==========================================================================

class TestP0Plus20Beta48DetectorCreate(unittest.TestCase):
    def setUp(self):
        from jarvis_acoustic_wake import reset_acoustic_wake_singleton
        reset_acoustic_wake_singleton()

    def test_default_vocab_disabled_returns_stub(self):
        """vocab.enabled=false → create() 返 disabled stub, is_available()=False."""
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=False)
        self.assertFalse(det.is_available())
        self.assertIn('enabled', det.get_disable_reason().lower())

    def test_force_enable_loads_openwakeword(self):
        """force_enable=True → 真创建 openWakeWord Model (要求 openwakeword 已装)."""
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            self.skipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=True)
        self.assertTrue(det.is_available(), f'force_enable 创建失败: {det.get_disable_reason()}')
        self.assertGreater(det.frame_length, 0)
        det.close()

    def test_stub_process_returns_not_detected(self):
        """disabled stub.process() 永返 detected=False (不抛异常)."""
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector._make_disabled('test stub')
        import numpy as np
        res = det.process(np.zeros(1280, dtype=np.int16))
        self.assertFalse(res.detected)
        self.assertEqual(res.score, 0.0)

    def test_stub_feed_pyaudio_buffer_returns_empty(self):
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector._make_disabled('test stub')
        import numpy as np
        results = det.feed_pyaudio_buffer(np.zeros(2048, dtype=np.int16).tobytes())
        self.assertEqual(results, [])


# ==========================================================================
# Detector runtime behavior
# ==========================================================================

class TestP0Plus20Beta48DetectorRuntime(unittest.TestCase):
    """需要 openWakeWord 真装. 否则 skip."""

    @classmethod
    def setUpClass(cls):
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        cls.det = AcousticWakeDetector.create(force_enable=True)
        if not cls.det.is_available():
            raise unittest.SkipTest(f'detector unavailable: {cls.det.get_disable_reason()}')

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'det'):
            cls.det.close()

    def test_silence_score_near_zero(self):
        import numpy as np
        res = self.det.process(np.zeros(self.det.frame_length, dtype=np.int16))
        self.assertFalse(res.detected)
        self.assertLess(res.score, 0.3, f'silence 分数 {res.score} 不应高 (probably model loaded wrong)')

    def test_random_noise_low_score(self):
        """白噪音不应触发唤醒."""
        import numpy as np
        rng = np.random.RandomState(42)
        noise = (rng.randn(self.det.frame_length) * 1000).astype(np.int16)
        res = self.det.process(noise)
        self.assertFalse(res.detected,
            f'白噪音不应唤醒, 分数 {res.score:.3f}; model: {self.det.keyword_name}')

    def test_frame_length_mismatch_returns_not_detected(self):
        import numpy as np
        wrong = np.zeros(self.det.frame_length // 2, dtype=np.int16)
        res = self.det.process(wrong)
        self.assertFalse(res.detected)
        self.assertIn('_error', res.raw_scores)
        self.assertIn('mismatch', res.raw_scores['_error'])

    def test_feed_pyaudio_buffer_accumulator(self):
        """PyAudio 1024 + 1024 → 2048 > 1280 → 1 个 frame."""
        import numpy as np
        self.det.reset_accum()
        buf = np.zeros(1024, dtype=np.int16).tobytes()
        r1 = self.det.feed_pyaudio_buffer(buf)
        self.assertEqual(len(r1), 0, '1024 还没攒满 1280, 应 0 result')
        r2 = self.det.feed_pyaudio_buffer(buf)
        self.assertEqual(len(r2), 1, '2048 > 1280, 应 1 result')
        # 再喂 4096 → 至少 3 result (剩 768 + 4096 = 4864 / 1280 = 3 full)
        r3 = self.det.feed_pyaudio_buffer(np.zeros(4096, dtype=np.int16).tobytes())
        self.assertGreaterEqual(len(r3), 3)

    def test_process_with_bytes_input(self):
        import numpy as np
        res = self.det.process(np.zeros(self.det.frame_length, dtype=np.int16).tobytes())
        self.assertFalse(res.detected)


# ==========================================================================
# Singleton
# ==========================================================================

class TestP0Plus20Beta48Singleton(unittest.TestCase):
    def setUp(self):
        from jarvis_acoustic_wake import reset_acoustic_wake_singleton
        reset_acoustic_wake_singleton()

    def test_singleton_returns_same_instance(self):
        from jarvis_acoustic_wake import get_acoustic_wake_detector
        d1 = get_acoustic_wake_detector(force_enable=False)
        d2 = get_acoustic_wake_detector(force_enable=False)
        self.assertIs(d1, d2)

    def test_reset_creates_new(self):
        from jarvis_acoustic_wake import get_acoustic_wake_detector, reset_acoustic_wake_singleton
        d1 = get_acoustic_wake_detector(force_enable=False)
        reset_acoustic_wake_singleton()
        d2 = get_acoustic_wake_detector(force_enable=False)
        self.assertIsNot(d1, d2)


# ==========================================================================
# 准则 6.5 红线 — vocab 必须在 memory_pool/, NOT 硬编码在 .py
# ==========================================================================

class TestP0Plus20Beta48Principle65RedLines(unittest.TestCase):
    def test_no_hardcoded_threshold_in_py_source(self):
        """jarvis_acoustic_wake.py 不应硬编码具体 wakeword/threshold (除 SEED fallback)."""
        path = os.path.join(ROOT, 'jarvis_acoustic_wake.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # SEED 是允许的 fallback (不算硬编码) — 标记 _SEED_THRESHOLDS
        self.assertIn('_SEED_THRESHOLDS', src,
            'SEED 必须存在作为 fail-safe fallback')
        # threshold 必须从 vocab 读
        self.assertIn('load_mic_safety_thresholds', src)
        self.assertIn('openwakeword_threshold', src)

    def test_vocab_file_in_memory_pool(self):
        path = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')
        self.assertTrue(os.path.exists(path),
            'vocab 必须在 memory_pool/ (准则 6.5 持久化)')

    def test_vocab_has_meta_required_fields(self):
        path = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data.get('_meta', {})
        for k in ['schema_version', 'marker', 'purpose', 'edit_via', 'consumer', 'thresholds']:
            self.assertIn(k, meta, f'_meta 缺字段 {k} (准则 6.5 standard schema)')

    def test_no_picovoice_porcupine_reference(self):
        """β.4.8 选 openWakeWord 后, .py 中不应剩 Picovoice/Porcupine 引用 (避免误导)."""
        path = os.path.join(ROOT, 'jarvis_acoustic_wake.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 注释里可以提 (说明 why not), 但 import / API call 不该有
        self.assertNotIn('import pvporcupine', src)
        self.assertNotIn('pvporcupine.create', src)


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.4.8 acoustic wake tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
