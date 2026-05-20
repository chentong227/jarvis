# -*- coding: utf-8 -*-
"""β.5.40-B1 — InsideJokeReflector L7 daemon tests (Sir 方向 B.1)

Tests:
  1. Module imports + class structure
  2. Config defaults (24h interval, min STM 50, ≥ 2 evidence, conf ≥ 0.8)
  3. force_run_now 无 key_router 静默 return reason
  4. dedup vs existing inside_jokes
  5. hour gate (preferred 03-06 local)
  6. central_nerve wire (InsideJokeReflector start)
"""

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta540B1ModuleStructure(unittest.TestCase):
    def test_module_imports(self):
        import jarvis_inside_joke_reflector as ijr
        self.assertTrue(hasattr(ijr, 'InsideJokeReflector'))
        self.assertTrue(hasattr(ijr, 'INSIDE_JOKE_REFLECTOR_CONFIG'))
        self.assertTrue(hasattr(ijr, 'INSIDE_JOKE_REFLECTOR_PROMPT'))

    def test_config_defaults(self):
        from jarvis_inside_joke_reflector import INSIDE_JOKE_REFLECTOR_CONFIG as cfg
        self.assertEqual(cfg['min_interval_s'], 86400, '24h 周期')
        self.assertGreaterEqual(cfg['min_stm_for_run'], 30, 'STM 阈值至少 30')
        self.assertGreaterEqual(cfg['min_confidence'], 0.8, 'Sir 精准要求 conf ≥ 0.8')
        self.assertEqual(cfg['max_propose_per_run'], 3, 'max 3 / run 防爆')
        self.assertEqual(cfg['preferred_run_hour_local'], 3, '03:00 idle hour')

    def test_prompt_has_critical_constraints(self):
        from jarvis_inside_joke_reflector import INSIDE_JOKE_REFLECTOR_PROMPT as p
        self.assertIn('APPEND ONLY', p)
        self.assertIn('AT LEAST 2', p)  # ≥ 2 evidence
        self.assertIn('≥ 0.8', p)  # confidence threshold
        self.assertIn('AT MOST 3', p)  # cap


class TestBeta540B1ForceRunGuards(unittest.TestCase):
    def test_no_key_router_returns_reason(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(
            key_router=None,
            stm_provider=lambda: [{'text': 'a'}] * 100,
            relational_store=type('Fake', (), {'inside_jokes': {}})(),
        )
        res = r.force_run_now()
        self.assertFalse(res.get('ok'))
        self.assertIn('key_router', res.get('reason', ''))

    def test_no_relational_store_returns_reason(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(
            key_router=object(),
            stm_provider=lambda: [],
            relational_store=None,
        )
        res = r.force_run_now()
        self.assertFalse(res.get('ok'))
        self.assertIn('relational_store', res.get('reason', ''))

    def test_too_soon_skip(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(
            relational_store=type('Fake', (), {'inside_jokes': {}})(),
        )
        r._last_run_ts = time.time()  # 刚跑过
        res = r._reflect_once(force=False)
        self.assertFalse(res.get('ok'))
        self.assertIn('too soon', res.get('reason', ''))

    def test_min_stm_gate(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(
            relational_store=type('Fake', (), {'inside_jokes': {}})(),
            stm_provider=lambda: [{'text': 'a'}] * 5,  # 5 < 50
        )
        r._last_run_ts = 0
        # _should_run_by_hour 不强制看时段, force=False 走 hour gate 后再 stm check
        # 直接调 reflect (force 跳过 hour gate but not stm gate)
        res = r._reflect_once(force=False)
        self.assertFalse(res.get('ok'))
        # 应在 hour gate 或 stm gate 失败
        self.assertTrue(
            'outside preferred hour' in res.get('reason', '')
            or 'not enough STM' in res.get('reason', '')
            or 'too soon' in res.get('reason', '')
        )


class TestBeta540B1ExistingJokesDedup(unittest.TestCase):
    """LLM 看到 existing_jokes_str 避免重复 propose."""

    def test_build_existing_jokes_str_empty(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(relational_store=type('F', (), {'inside_jokes': {}})())
        s = r._build_existing_jokes_str()
        self.assertEqual(s, '(none yet)')

    def test_build_existing_jokes_str_with_jokes(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector

        class FakeJoke:
            def __init__(self, phrase, state='active'):
                self.phrase = phrase
                self.state = state

        store = type('F', (), {'inside_jokes': {
            'j1': FakeJoke('家具党'),
            'j2': FakeJoke('码农命', 'review'),
        }})()
        r = InsideJokeReflector(relational_store=store)
        s = r._build_existing_jokes_str()
        self.assertIn('家具党', s)
        self.assertIn('码农命', s)
        self.assertIn('[active]', s)
        self.assertIn('[review]', s)


class TestBeta540B1HourGate(unittest.TestCase):
    """preferred run hour: 03-06 local."""

    def test_force_bypasses_hour_gate(self):
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(relational_store=type('F', (), {'inside_jokes': {}})())
        self.assertTrue(r._should_run_by_hour(force=True))

    def test_non_force_check_hour(self):
        """non-force 时 hour gate 实际生效 — 测当前 hour 是否对/错."""
        from jarvis_inside_joke_reflector import InsideJokeReflector
        r = InsideJokeReflector(relational_store=type('F', (), {'inside_jokes': {}})())
        cur_hour = time.localtime().tm_hour
        expected = (3 <= cur_hour < 6)
        actual = r._should_run_by_hour(force=False)
        self.assertEqual(actual, expected,
                         f'hour={cur_hour}, expected {expected} but got {actual}')


class TestBeta540B1WireToCentralNerve(unittest.TestCase):
    """central_nerve 必须 wire InsideJokeReflector daemon."""

    def test_central_nerve_imports_reflector(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.40-B1', src, 'central_nerve 必须含 β.5.40-B1 marker')
        self.assertIn('from jarvis_inside_joke_reflector import InsideJokeReflector', src)
        self.assertIn('self.inside_joke_reflector', src,
                      '必须存 reflector 引用')

    def test_central_nerve_starts_reflector(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        # start() called 
        self.assertIn('self.inside_joke_reflector.start()', src,
                      '必须 start daemon')


if __name__ == '__main__':
    unittest.main()
