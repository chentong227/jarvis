"""[Reshape 准则 6.5 / 2026-05-24] tests for HabitVocabReflector."""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import jarvis_habit_vocab_reflector as hvr


class TestExtractCandidates(unittest.TestCase):
    def test_zh_pattern_extract(self):
        lines = [
            {'user': '我跑了 5 公里', 'turn_id': 't1', 'ts': time.time()},
            {'user': '我跑了 3 公里', 'turn_id': 't2', 'ts': time.time()},
        ]
        cands = hvr._extract_candidates(lines, set(), set())
        phrases = [c['phrase'] for c in cands]
        self.assertIn('跑了', phrases)

    def test_en_pattern_extract(self):
        lines = [
            {'user': 'I biked 10 km today', 'turn_id': 't1', 'ts': time.time()},
            {'user': 'I biked 12 km', 'turn_id': 't2', 'ts': time.time()},
        ]
        cands = hvr._extract_candidates(lines, set(), set())
        phrases = [c['phrase'] for c in cands]
        self.assertIn('biked', phrases)

    def test_existing_vocab_excluded(self):
        lines = [
            {'user': '我喝了 3 杯水', 'turn_id': 't1', 'ts': time.time()},
            {'user': '我喝了 5 杯水', 'turn_id': 't2', 'ts': time.time()},
        ]
        cands = hvr._extract_candidates(lines, existing_zh={'喝了'}, existing_en=set())
        phrases = [c['phrase'] for c in cands]
        self.assertNotIn('喝了', phrases)

    def test_min_2_occurrences(self):
        lines = [
            {'user': '我学了 1 小时', 'turn_id': 't1', 'ts': time.time()},
        ]
        cands = hvr._extract_candidates(lines, set(), set())
        self.assertEqual(len(cands), 0)


class TestRunCycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_review = hvr._REVIEW_PATH
        self._orig_stm = hvr._STM_PATH
        self._orig_vocab = hvr._VOCAB_PATH
        hvr._REVIEW_PATH = os.path.join(self.tmpdir, 'habit_progress_vocab_review.json')
        hvr._STM_PATH = os.path.join(self.tmpdir, 'stm_recent.jsonl')
        hvr._VOCAB_PATH = os.path.join(self.tmpdir, 'habit_progress_vocab.json')
        hvr.reset_for_test()
        # seed empty vocab
        with open(hvr._VOCAB_PATH, 'w', encoding='utf-8') as f:
            json.dump({'zh_keywords': [], 'en_keywords': []}, f)

    def tearDown(self):
        hvr._REVIEW_PATH = self._orig_review
        hvr._STM_PATH = self._orig_stm
        hvr._VOCAB_PATH = self._orig_vocab
        hvr.reset_for_test()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_stm(self, lines):
        with open(hvr._STM_PATH, 'w', encoding='utf-8') as f:
            for r in lines:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def test_run_cycle_proposes_review(self):
        lines = [
            {'user': '我跑了 5 公里', 'turn_id': 't1', 'ts': time.time()},
            {'user': '我跑了 3 公里', 'turn_id': 't2', 'ts': time.time()},
            {'user': '我跑了 7 公里', 'turn_id': 't3', 'ts': time.time()},
        ]
        self._write_stm(lines)
        ref = hvr.HabitVocabReflector()
        new_props = ref.run_cycle()
        self.assertGreater(len(new_props), 0)
        # 验证 review queue 写入
        with open(hvr._REVIEW_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertGreater(len(data), 0)
        # all pending
        for entry in data:
            self.assertEqual(entry.get('status'), 'pending')

    def test_cycle_with_no_new_candidates(self):
        # all phrases already in vocab
        with open(hvr._VOCAB_PATH, 'w', encoding='utf-8') as f:
            json.dump({'zh_keywords': ['喝了'], 'en_keywords': []}, f)
        lines = [
            {'user': '我喝了 3 杯水', 'turn_id': 't1', 'ts': time.time()},
            {'user': '我喝了 5 杯水', 'turn_id': 't2', 'ts': time.time()},
        ]
        self._write_stm(lines)
        ref = hvr.HabitVocabReflector()
        new_props = ref.run_cycle()
        self.assertEqual(len(new_props), 0)


if __name__ == '__main__':
    unittest.main()
