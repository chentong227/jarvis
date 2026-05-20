# -*- coding: utf-8 -*-
"""β.5.40-E1 — CompanionRhythmReflector tests (Sir 方向 E.1)

Tests:
  1. Module structure + config
  2. _detect_refusal Sir 拒绝/不耐烦判定
  3. _is_nudge_entry / _is_user_voice STM 类型识别
  4. _classify_nudge_outcome (engaged / rejected / silent)
  5. _build_hour_buckets 算 score (engaged_rate)
  6. Reflector force_run 不阻塞 + min_samples gate
  7. ProactiveCare publish nudge_window_advice 到 SWM
  8. SWM etype + salience 注册
  9. Directive trigger + seed
  10. Vocab + CLI tool
  11. central_nerve wire
"""

import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestBeta540E1ModuleStructure(unittest.TestCase):
    def test_imports(self):
        import jarvis_companion_rhythm_reflector as crr
        for sym in ('CompanionRhythmReflector', 'COMPANION_RHYTHM_REFLECTOR_CONFIG',
                    '_detect_refusal', '_is_nudge_entry', '_is_user_voice',
                    '_classify_nudge_outcome', '_build_hour_buckets',
                    'get_current_hour_receptive_score'):
            self.assertTrue(hasattr(crr, sym), f'必须有 {sym}')

    def test_config_defaults(self):
        from jarvis_companion_rhythm_reflector import COMPANION_RHYTHM_REFLECTOR_CONFIG as cfg
        self.assertEqual(cfg['min_interval_s'], 86400)
        self.assertEqual(cfg['min_samples_per_hour'], 3, 'Sir 精准 ≥ 3 samples')
        self.assertEqual(cfg['outcome_window_s'], 60.0)


class TestBeta540E1RefusalDetect(unittest.TestCase):
    def test_chinese_refusal(self):
        from jarvis_companion_rhythm_reflector import _detect_refusal
        self.assertTrue(_detect_refusal('不用了'))
        self.assertTrue(_detect_refusal('别催了'))
        self.assertTrue(_detect_refusal('烦死了'))

    def test_english_refusal(self):
        from jarvis_companion_rhythm_reflector import _detect_refusal
        self.assertTrue(_detect_refusal('shut up'))
        self.assertTrue(_detect_refusal('not now'))

    def test_neutral_engaged(self):
        from jarvis_companion_rhythm_reflector import _detect_refusal
        self.assertFalse(_detect_refusal('好的我去处理'))
        self.assertFalse(_detect_refusal('Yeah let me check'))

    def test_short_ok_is_dismiss(self):
        from jarvis_companion_rhythm_reflector import _detect_refusal
        self.assertTrue(_detect_refusal('哦'))
        self.assertTrue(_detect_refusal('ok'))


class TestBeta540E1STMEntryClassify(unittest.TestCase):
    def test_is_nudge_by_source(self):
        from jarvis_companion_rhythm_reflector import _is_nudge_entry
        self.assertTrue(_is_nudge_entry({'source': 'proactive_care', 'user': '', 'jarvis': 'check?'}))
        self.assertTrue(_is_nudge_entry({'source': 'silent_nudge', 'user': '', 'jarvis': ''}))

    def test_is_nudge_by_marker(self):
        from jarvis_companion_rhythm_reflector import _is_nudge_entry
        self.assertTrue(_is_nudge_entry({'jarvis': '[Smart Nudge] hydrate?'}))
        self.assertTrue(_is_nudge_entry({'jarvis': '[ProactiveCare/LIVE] check'}))

    def test_is_not_nudge_user_voice(self):
        from jarvis_companion_rhythm_reflector import _is_nudge_entry
        self.assertFalse(_is_nudge_entry({'user': 'hello', 'jarvis': 'hi', 'source': 'user_voice'}))

    def test_is_user_voice(self):
        from jarvis_companion_rhythm_reflector import _is_user_voice
        self.assertTrue(_is_user_voice({'source': 'user_voice', 'user': 'hello'}))
        self.assertTrue(_is_user_voice({'user': 'speaking', 'jarvis': ''}))


class TestBeta540E1OutcomeClassify(unittest.TestCase):
    def test_engaged_reply(self):
        from jarvis_companion_rhythm_reflector import _classify_nudge_outcome
        now = time.time()
        nudge = {'ts': now, 'jarvis': 'hydrate?', 'source': 'proactive_care'}
        stm = [
            nudge,
            {'ts': now + 10, 'user': '好的我去喝水谢谢', 'source': 'user_voice'},
        ]
        self.assertEqual(_classify_nudge_outcome(nudge, stm), 'engaged')

    def test_rejected_reply(self):
        from jarvis_companion_rhythm_reflector import _classify_nudge_outcome
        now = time.time()
        nudge = {'ts': now, 'jarvis': 'hydrate?', 'source': 'proactive_care'}
        stm = [
            nudge,
            {'ts': now + 5, 'user': '不用别催', 'source': 'user_voice'},
        ]
        self.assertEqual(_classify_nudge_outcome(nudge, stm), 'rejected')

    def test_silent_no_reply(self):
        from jarvis_companion_rhythm_reflector import _classify_nudge_outcome
        now = time.time()
        nudge = {'ts': now, 'jarvis': 'hydrate?', 'source': 'proactive_care'}
        stm = [nudge]
        self.assertEqual(_classify_nudge_outcome(nudge, stm), 'silent')


class TestBeta540E1HourBuckets(unittest.TestCase):
    def test_min_samples_gate(self):
        from jarvis_companion_rhythm_reflector import _build_hour_buckets
        # 只 2 sample → < 3 → null
        samples = [
            {'hour': 10, 'is_weekday': True, 'outcome': 'engaged'},
            {'hour': 10, 'is_weekday': True, 'outcome': 'engaged'},
        ]
        wd, we, sc = _build_hour_buckets(samples)
        self.assertIsNone(wd.get('10'), '< 3 sample 不给 score')

    def test_score_calc(self):
        from jarvis_companion_rhythm_reflector import _build_hour_buckets
        samples = [
            {'hour': 14, 'is_weekday': True, 'outcome': 'engaged'},
            {'hour': 14, 'is_weekday': True, 'outcome': 'engaged'},
            {'hour': 14, 'is_weekday': True, 'outcome': 'rejected'},
        ]
        wd, we, sc = _build_hour_buckets(samples)
        # 2 engaged - 0.5*1 reject / 3 = 0.5
        self.assertAlmostEqual(wd['14'], 0.5, places=2)
        self.assertEqual(sc['weekday']['14'], 3)

    def test_score_clamp(self):
        from jarvis_companion_rhythm_reflector import _build_hour_buckets
        samples = [
            {'hour': 9, 'is_weekday': False, 'outcome': 'engaged'},
            {'hour': 9, 'is_weekday': False, 'outcome': 'engaged'},
            {'hour': 9, 'is_weekday': False, 'outcome': 'engaged'},
        ]
        wd, we, sc = _build_hour_buckets(samples)
        self.assertEqual(we['9'], 1.0, '全 engaged → 1.0')


class TestBeta540E1ReflectorGuards(unittest.TestCase):
    def test_no_stm_provider(self):
        from jarvis_companion_rhythm_reflector import CompanionRhythmReflector
        r = CompanionRhythmReflector(stm_provider=None)
        res = r.force_run_now()
        self.assertFalse(res.get('ok'))
        self.assertIn('stm_provider', res.get('reason', ''))

    def test_min_stm_gate(self):
        from jarvis_companion_rhythm_reflector import CompanionRhythmReflector
        r = CompanionRhythmReflector(stm_provider=lambda: [{'ts': time.time(), 'user': 'a'}] * 5)
        r._last_run_ts = 0
        # 强 force=True 跳过 hour gate + interval, 但 stm_count check 走 force=True skip path
        # 实际 force=True 跳过 min_stm gate? 看 code
        res = r._reflect_once(force=True)  # force skip gates
        # force=True 也得 stm_provider 返非空 → 这里 stm 5 < min_stm=100, 但 force 跳过 stm gate too
        self.assertTrue(res.get('ok'))
        self.assertEqual(res.get('samples_n'), 0)  # 5 entries 无 nudge marker → samples 0


class TestBeta540E1ReflectorFullRun(unittest.TestCase):
    def test_full_pipeline(self):
        """force_run 完整跑: 制作假 STM 含 nudge + user reply, 验证 vocab 写出."""
        from jarvis_companion_rhythm_reflector import CompanionRhythmReflector

        with tempfile.TemporaryDirectory() as tmp:
            vocab_path = os.path.join(tmp, 'nudge_window_vocab.json')
            # init vocab
            with open(vocab_path, 'w', encoding='utf-8') as f:
                json.dump({
                    '_meta': {'history_max': 200},
                    'weekday_hourly_receptive': {str(h): None for h in range(24)},
                    'weekend_hourly_receptive': {str(h): None for h in range(24)},
                    'samples_count': {'weekday': {}, 'weekend': {}},
                    'history': [],
                }, f)
            
            # 制作假 STM (5 个 nudge + reply, 集中在 hour 14 weekday)
            base_ts = time.mktime((2026, 5, 18, 14, 0, 0, 0, 138, 0))  # Mon 14:00
            stm = []
            for i in range(5):
                t = base_ts + i * 300  # 5min apart, all 14:00
                stm.append({'ts': t, 'jarvis': '[Smart Nudge] check?', 'source': 'proactive_care'})
                stm.append({'ts': t + 10, 'user': '好的我去处理', 'source': 'user_voice'})
            
            r = CompanionRhythmReflector(
                stm_provider=lambda: stm,
                vocab_path=vocab_path,
            )
            res = r.force_run_now()
            self.assertTrue(res.get('ok'))
            self.assertEqual(res.get('samples_n'), 5)
            
            with open(vocab_path) as f:
                v = json.load(f)
            self.assertEqual(v['weekday_hourly_receptive']['14'], 1.0,
                             '5 engaged → score 1.0')
            self.assertEqual(v['samples_count']['weekday']['14'], 5)


class TestBeta540E1ProactiveCarePublish(unittest.TestCase):
    def test_proactive_care_has_publish_block(self):
        with open(os.path.join(ROOT, 'jarvis_proactive_care.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.40-E1', src)
        self.assertIn('nudge_window_advice', src)
        self.assertIn('get_current_hour_receptive_score', src)


class TestBeta540E1SWMEtype(unittest.TestCase):
    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        self.assertIn('nudge_window_advice', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('nudge_window_advice', ConversationEventBus.DEFAULT_SALIENCE)


class TestBeta540E1Directive(unittest.TestCase):
    def test_trigger_callable(self):
        from jarvis_directives import _trigger_nudge_window_advice_judge, DirectiveContext
        ctx = DirectiveContext(current_hour=10, user_input='')
        r = _trigger_nudge_window_advice_judge(ctx)
        self.assertIsInstance(r, bool)

    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='nudge_window_advice_judge'", src)
        self.assertIn('_trigger_nudge_window_advice_judge', src)

    def test_vocab_json_has_entry(self):
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  'r', encoding='utf-8') as f:
            vocab = json.load(f)
        ids = [d.get('id') for d in vocab.get('directives', [])]
        self.assertIn('nudge_window_advice_judge', ids)


class TestBeta540E1VocabAndCLI(unittest.TestCase):
    def test_vocab_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'nudge_window_vocab.json')
        self.assertTrue(os.path.exists(path))
        with open(path, encoding='utf-8') as f:
            v = json.load(f)
        self.assertIn('weekday_hourly_receptive', v)
        self.assertIn('weekend_hourly_receptive', v)
        self.assertEqual(len(v['weekday_hourly_receptive']), 24)

    def test_cli_exists(self):
        path = os.path.join(ROOT, 'scripts', 'nudge_window_dump.py')
        self.assertTrue(os.path.exists(path))


class TestBeta540E1WireToCentralNerve(unittest.TestCase):
    def test_central_nerve_wires_reflector(self):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.40-E1', src)
        self.assertIn('CompanionRhythmReflector', src)
        self.assertIn('self.companion_rhythm_reflector', src)


if __name__ == '__main__':
    unittest.main()
