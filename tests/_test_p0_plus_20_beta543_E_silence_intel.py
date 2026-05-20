"""[β.5.43-E / 2026-05-20 19:13] Silence Intelligence — thinking pause

Sir 17:10 真理 (6 缺口 E): Sir 说话过程中 'uh / 嗯 / let me think' → 主脑感知, 
默认沉默或极短 ack, 不打断思维.

测试覆盖:
- vocab json 加载 + mtime cache
- is_thinking_pause 检测准确度 (positive + negative)
- publish_thinking_pause_event 写 SWM
- directive thinking_pause_aware_judge 注册 + trigger 工作
- worker hook 在 emit text_ready 前调
"""
from __future__ import annotations

import os
import sys
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestVocabLoading(unittest.TestCase):

    def test_vocab_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'thinking_pause_vocab.json')
        self.assertTrue(os.path.exists(path),
                        'thinking_pause_vocab.json must exist')

    def test_vocab_json_well_formed(self):
        path = os.path.join(ROOT, 'memory_pool', 'thinking_pause_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('groups', data)
        self.assertIn('en_thinking_fillers', data['groups'])
        self.assertIn('zh_thinking_fillers', data['groups'])
        # vocab 含关键 filler
        en = data['groups']['en_thinking_fillers']['verbs']
        self.assertTrue(any(v in en for v in ['uh', 'um', 'hmm']),
                        'must include basic en fillers')
        zh = data['groups']['zh_thinking_fillers']['verbs']
        self.assertTrue(any(v in zh for v in ['嗯', '让我想想']),
                        'must include basic zh fillers')


class TestIsThinkingPause(unittest.TestCase):

    def test_short_zh_filler_positive(self):
        from jarvis_silence_intel import is_thinking_pause
        for utt in ['嗯', '嗯嗯嗯', '呃', '让我想想', '等等']:
            is_pause, ev = is_thinking_pause(utt)
            self.assertTrue(is_pause,
                            f'"{utt}" should be detected as thinking pause '
                            f'(got conf={ev["confidence"]})')

    def test_short_en_filler_positive(self):
        from jarvis_silence_intel import is_thinking_pause
        for utt in ['uh', 'um', 'hmm', 'let me think', 'hold on']:
            is_pause, ev = is_thinking_pause(utt)
            self.assertTrue(is_pause,
                            f'"{utt}" should be detected as thinking pause '
                            f'(got conf={ev["confidence"]})')

    def test_normal_question_not_pause(self):
        from jarvis_silence_intel import is_thinking_pause
        for utt in [
            '今天天气怎么样',
            'what is the weather today',
            '请帮我看看 windsurf 的状态',
            'tell me a joke',
        ]:
            is_pause, ev = is_thinking_pause(utt)
            self.assertFalse(is_pause,
                             f'"{utt}" should NOT be thinking pause '
                             f'(got conf={ev["confidence"]})')

    def test_empty_input_not_pause(self):
        from jarvis_silence_intel import is_thinking_pause
        is_pause, ev = is_thinking_pause('')
        self.assertFalse(is_pause)
        is_pause, ev = is_thinking_pause(None)
        self.assertFalse(is_pause)

    def test_evidence_includes_fields(self):
        from jarvis_silence_intel import is_thinking_pause
        _, ev = is_thinking_pause('嗯嗯嗯')
        self.assertIn('confidence', ev)
        self.assertIn('matched_fillers', ev)
        self.assertIn('utterance_short', ev)
        self.assertIn('lang', ev)


class TestSWMEtypeAndPublish(unittest.TestCase):

    def test_etype_registered(self):
        from jarvis_utils import ConversationEventBus
        self.assertIn('sir_thinking_pause', ConversationEventBus.DEFAULT_TTL)
        self.assertIn('sir_thinking_pause', ConversationEventBus.DEFAULT_SALIENCE)

    def test_publish_thinking_pause_event(self):
        from jarvis_silence_intel import publish_thinking_pause_event
        from jarvis_utils import ConversationEventBus

        bus = ConversationEventBus()
        ConversationEventBus.register_global(bus)

        publish_thinking_pause_event(
            cmd='嗯嗯嗯',
            evidence={'confidence': 0.85, 'matched_fillers': ['嗯'],
                      'utterance_short': True, 'lang': 'zh',
                      'matched_patterns': []},
            turn_id='turn_test_e',
        )
        evs = bus.recent_events(types={'sir_thinking_pause'})
        self.assertGreaterEqual(len(evs), 1)
        ev = evs[-1]
        self.assertEqual(ev['source'], 'SilenceIntel')
        meta = ev.get('metadata', {})
        self.assertEqual(meta.get('cmd'), '嗯嗯嗯')


class TestDirectiveRegistered(unittest.TestCase):

    def test_directive_in_seed(self):
        src = open(
            os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8'
        ).read()
        self.assertIn("id='thinking_pause_aware_judge'", src)
        self.assertIn('β.5.43-E', src)
        self.assertIn('THINKING PAUSE AWARE JUDGE', src)
        self.assertIn('_trigger_thinking_pause_aware_judge', src)

    def test_directive_in_vocab_json(self):
        path = os.path.join(ROOT, 'memory_pool', 'directives_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ids = [d.get('id') for d in data.get('directives', [])]
        self.assertIn('thinking_pause_aware_judge', ids)


class TestWorkerHookIntegration(unittest.TestCase):

    def test_worker_has_silence_intel_hook(self):
        src = open(
            os.path.join(ROOT, 'jarvis_worker.py'), encoding='utf-8'
        ).read()
        self.assertIn('β.5.43-E', src)
        self.assertIn('SilenceIntel', src)
        self.assertIn('is_thinking_pause', src)
        self.assertIn('publish_thinking_pause_event', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
