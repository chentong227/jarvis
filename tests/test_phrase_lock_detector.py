"""[Reshape 准则 6 / 2026-05-24] tests for PhraseLockDetector."""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jarvis_phrase_lock_detector as pld
from jarvis_phrase_lock_detector import (
    _detect_phrase_locks, _extract_zh_ngrams, _extract_en_ngrams,
    _is_zh, PhraseLockDetector, _load_config, DEFAULT_CONFIG,
)


class TestNgramExtraction(unittest.TestCase):
    def test_extract_zh_ngrams_basic(self):
        text = '我不打扰您'
        ngrams4 = _extract_zh_ngrams(text, 4)
        self.assertIn('我不打扰', ngrams4)
        self.assertIn('不打扰您', ngrams4)

    def test_extract_zh_ngrams_skip_punct(self):
        text = '明白了, 先生. 我不打扰您.'
        ngrams4 = _extract_zh_ngrams(text, 4)
        # 标点不影响 ngram
        self.assertIn('明白了先', ngrams4)
        self.assertIn('我不打扰', ngrams4)

    def test_extract_en_ngrams(self):
        text = 'I shall stay out of your way'
        ngrams3 = _extract_en_ngrams(text, 3)
        self.assertIn('shall stay out', ngrams3)
        self.assertIn('stay out of', ngrams3)
        self.assertIn('out of your', ngrams3)
        self.assertIn('of your way', ngrams3)

    def test_is_zh_detection(self):
        self.assertTrue(_is_zh('明白了先生'))
        self.assertFalse(_is_zh('Understood Sir'))
        # mixed: 50% ZH chars in EN
        self.assertTrue(_is_zh('hello 我不打扰您'))


class TestPhraseLockDetection(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(DEFAULT_CONFIG)
        self.cfg['min_count'] = 3            # lower for test
        self.cfg['min_diversity_turns'] = 2
        self.cfg['ngram_zh_chars'] = [4]
        self.cfg['ngram_en_words'] = [3]

    def test_zh_lock_detected(self):
        replies = []
        for i in range(5):
            replies.append({
                'jarvis': f'明白了, 先生. 我不打扰您, 您继续.',
                'turn_id': f'turn_{i}',
                'ts': time.time() - i * 60,
            })
        locks = _detect_phrase_locks(replies, self.cfg)
        # '我不打扰您' 5 chars, 但 ngram=4 会拿 '我不打扰' / '不打扰您'
        phrases = [l['phrase'] for l in locks]
        self.assertTrue(any('打扰' in p for p in phrases))
        self.assertTrue(any(l['count'] >= 3 for l in locks))

    def test_en_lock_detected(self):
        replies = []
        for i in range(5):
            replies.append({
                'jarvis': 'Understood, Sir. I shall stay out of your way.',
                'turn_id': f'turn_{i}',
                'ts': time.time() - i * 60,
            })
        locks = _detect_phrase_locks(replies, self.cfg)
        phrases = [l['phrase'] for l in locks]
        # '3-gram' should include 'stay out of'
        self.assertTrue(any('stay out' in p for p in phrases))

    def test_below_min_count_not_locked(self):
        replies = [
            {'jarvis': '明白了, 先生. 我不打扰您.', 'turn_id': 't1', 'ts': time.time()},
            {'jarvis': '明白了, 先生. 我不打扰您.', 'turn_id': 't2', 'ts': time.time()},
        ]
        locks = _detect_phrase_locks(replies, self.cfg)
        # only 2 occurrences < min_count=3
        self.assertEqual(len(locks), 0)

    def test_diversity_filter(self):
        # 5 replies BUT all same turn → diversity=1 < min=2 → no lock
        replies = []
        for i in range(5):
            replies.append({
                'jarvis': '明白了, 先生. 我不打扰您.',
                'turn_id': 'turn_same',
                'ts': time.time() - i,
            })
        locks = _detect_phrase_locks(replies, self.cfg)
        self.assertEqual(len(locks), 0)

    def test_exclude_phrases_skipped(self):
        replies = []
        for i in range(10):
            replies.append({
                'jarvis': '好的好的好的, 先生.',
                'turn_id': f't_{i}',
                'ts': time.time(),
            })
        locks = _detect_phrase_locks(replies, self.cfg)
        # '先生' is in exclude_phrases_zh, should not lock
        phrases = [l['phrase'] for l in locks]
        self.assertNotIn('先生', phrases)


class TestRunCycleAndPersist(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # patch module paths
        self._orig_review = pld._REVIEW_PATH
        self._orig_stm = pld._STM_PATH
        pld._REVIEW_PATH = os.path.join(self.tmpdir, 'phrase_lock_review.json')
        pld._STM_PATH = os.path.join(self.tmpdir, 'stm_recent.jsonl')
        # patch config
        self._orig_cfg = dict(pld.DEFAULT_CONFIG)
        pld.DEFAULT_CONFIG['min_count'] = 3
        pld.DEFAULT_CONFIG['min_diversity_turns'] = 2
        pld.DEFAULT_CONFIG['lookback_hours'] = 8760  # huge
        pld.DEFAULT_CONFIG['cooldown_after_propose_hours'] = 0  # no cooldown for test
        pld.reset_for_test()

    def tearDown(self):
        pld._REVIEW_PATH = self._orig_review
        pld._STM_PATH = self._orig_stm
        for k, v in self._orig_cfg.items():
            pld.DEFAULT_CONFIG[k] = v
        pld.reset_for_test()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_stm(self, replies):
        with open(pld._STM_PATH, 'w', encoding='utf-8') as f:
            for r in replies:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def test_run_cycle_writes_review(self):
        replies = []
        for i in range(5):
            replies.append({
                'jarvis': f'明白了, 先生. 我不打扰您, 让您专注.',
                'turn_id': f'turn_{i}',
                'ts': time.time() - i * 60,
            })
        self._write_stm(replies)
        det = PhraseLockDetector()
        new_locks = det.run_cycle()
        self.assertGreater(len(new_locks), 0)
        # review file written
        self.assertTrue(os.path.exists(pld._REVIEW_PATH))
        with open(pld._REVIEW_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertGreater(len(data), 0)
        # all status pending
        for entry in data:
            self.assertEqual(entry.get('status'), 'pending')
            self.assertIn('phrase', entry)
            self.assertIn('count', entry)

    def test_no_locks_returns_empty(self):
        # each reply uses fully distinct ngrams (no overlap)
        templates = [
            'Today the weather is rainy.',
            'Pizza tastes great with cheese.',
            'Meeting moved Friday afternoon.',
            'Code review pending on backend.',
            'Coffee brewed strong this morning.',
        ]
        replies = []
        for i, t in enumerate(templates):
            replies.append({'jarvis': t, 'turn_id': f't_{i}', 'ts': time.time()})
        self._write_stm(replies)
        det = PhraseLockDetector()
        new_locks = det.run_cycle()
        self.assertEqual(len(new_locks), 0)


if __name__ == '__main__':
    unittest.main()
