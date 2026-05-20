# -*- coding: utf-8 -*-
"""[β.5.35-B / 2026-05-20] ScreenTeaseReflector L7 vocab daemon regression test.

Sir BUG 2 follow-up: β.5.35-A 持久化 vocab + CLI 后, β.5.35-B 加 L7 daemon:
  - 后台 60s 一次采 PhysicalEnvironmentProbe.window_history → in-memory 24h unique titles
  - 24h 1 跑 LLM (OpenRouter cheap) propose 新 category 进 review_queue
  - 失败/超时/无 key 静默, 不阻塞主路径

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBeta535BReflectorBasics(unittest.TestCase):
    """ScreenTeaseReflector 基础行为."""

    def test_module_importable(self):
        from jarvis_screen_tease_reflector import (
            ScreenTeaseReflector,
            SCREEN_TEASE_REFLECTOR_CONFIG,
            SCREEN_TEASE_REFLECTOR_PROMPT,
        )
        self.assertIsNotNone(ScreenTeaseReflector)
        self.assertIsInstance(SCREEN_TEASE_REFLECTOR_CONFIG, dict)
        self.assertIsInstance(SCREEN_TEASE_REFLECTOR_PROMPT, str)

    def test_config_has_required_keys(self):
        from jarvis_screen_tease_reflector import SCREEN_TEASE_REFLECTOR_CONFIG as cfg
        for k in ('primary_model', 'fallback_model', 'min_interval_s',
                  'min_unique_titles_for_run', 'max_propose_per_run',
                  'sampling_tick', 'unique_titles_maxlen'):
            self.assertIn(k, cfg, f'config missing {k}')

    def test_24h_min_interval(self):
        """24h L7 跑频 (Sir 决定 4a OpenRouter cheap)."""
        from jarvis_screen_tease_reflector import SCREEN_TEASE_REFLECTOR_CONFIG as cfg
        self.assertEqual(cfg['min_interval_s'], 86400, '必须 24h 1 跑')

    def test_no_key_router_no_crash(self):
        """无 key_router → 静默 fail, 不抛."""
        from jarvis_screen_tease_reflector import ScreenTeaseReflector
        r = ScreenTeaseReflector(key_router=None)
        result = r.force_run_now()
        self.assertIsInstance(result, dict)
        # 没 key 或没足够 titles 都行, 只要不抛
        self.assertIn('reason', result)


class TestBeta535BSamplingBehavior(unittest.TestCase):
    """sampling + dedup + GC 行为."""

    def setUp(self):
        from jarvis_screen_tease_reflector import ScreenTeaseReflector
        self.tmp_vocab = tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                                     delete=False, encoding='utf-8')
        json.dump({
            '_meta': {'schema_version': 1},
            'categories': [{
                'id': 'ide_focus',
                'state': 'active',
                'keywords': ['VSCode', 'Cursor'],
                'directive_hint': 'IDE',
            }],
            'review_queue': [],
            'rejected_history': [],
        }, self.tmp_vocab)
        self.tmp_vocab.close()
        self.r = ScreenTeaseReflector(vocab_path=self.tmp_vocab.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp_vocab.name)
        except Exception:
            pass

    def test_sample_titles_with_mock_probe(self):
        """sample_titles_now 从 PhysicalEnvironmentProbe.window_history 累计 unique."""
        from collections import deque
        fake_history = deque([
            {'time': time.time(), 'title': 'Windsurf - jarvis_chat_bypass.py', 'idle_ms': 100},
            {'time': time.time(), 'title': 'Windsurf - jarvis_chat_bypass.py', 'idle_ms': 100},
            {'time': time.time(), 'title': 'Outlook - Inbox', 'idle_ms': 200},
        ])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.window_history',
                   new=fake_history):
            new_n = self.r.sample_titles_now()
        # 2 unique titles
        self.assertEqual(new_n, 2)
        self.assertEqual(len(self.r._unique_titles), 2)
        # 同 title 第 2 次 → count += 1
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.window_history',
                   new=fake_history):
            new_n2 = self.r.sample_titles_now()
        # 无新 unique title (都已存在)
        self.assertEqual(new_n2, 0)

    def test_unmatched_titles_filter(self):
        """_get_unmatched_titles_top_n 排除命中 vocab keyword 的 title."""
        # 注入 unique titles 模拟: VSCode 命中 vocab, Outlook / Notion 不命中
        self.r._unique_titles = {
            'VSCode - main.py': (time.time(), 5),
            'Outlook - Inbox': (time.time(), 3),
            'Notion - My Workspace': (time.time(), 2),
            'Cursor - file.ts': (time.time(), 4),  # 命中 vocab 'Cursor'
        }
        unmatched = self.r._get_unmatched_titles_top_n(10)
        unmatched_titles = [t for t, _ in unmatched]
        self.assertIn('Outlook - Inbox', unmatched_titles)
        self.assertIn('Notion - My Workspace', unmatched_titles)
        self.assertNotIn('VSCode - main.py', unmatched_titles)
        self.assertNotIn('Cursor - file.ts', unmatched_titles)

    def test_gc_old_titles_removed(self):
        """sample_titles_now 删 > 25h 老 title."""
        old_t = time.time() - 26 * 3600  # 26h 前
        recent_t = time.time()
        self.r._unique_titles = {
            'Old Window 26h': (old_t, 5),
            'Recent Window': (recent_t, 3),
        }
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe.window_history',
                   new=[]):
            self.r.sample_titles_now()
        self.assertNotIn('Old Window 26h', self.r._unique_titles)
        self.assertIn('Recent Window', self.r._unique_titles)


class TestBeta535BReflectionFlow(unittest.TestCase):
    """LLM reflect 路径 + vocab write 行为 (mocked LLM)."""

    def setUp(self):
        from jarvis_screen_tease_reflector import ScreenTeaseReflector
        self.tmp_vocab = tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                                     delete=False, encoding='utf-8')
        json.dump({
            '_meta': {'schema_version': 1},
            'categories': [{
                'id': 'ide_focus',
                'state': 'active',
                'keywords': ['VSCode', 'Cursor'],
                'directive_hint': 'IDE',
            }],
            'review_queue': [],
            'rejected_history': [],
        }, self.tmp_vocab)
        self.tmp_vocab.close()
        self.mock_kr = MagicMock()
        self.mock_kr.get_openrouter_key.return_value = ('sk-fake-key', 'or_test')
        self.r = ScreenTeaseReflector(key_router=self.mock_kr,
                                      vocab_path=self.tmp_vocab.name,
                                      config={'min_unique_titles_for_run': 1})
        # 灌 unmatched titles
        self.r._unique_titles = {
            'Outlook - Inbox': (time.time(), 8),
            'Outlook - Calendar': (time.time(), 5),
            'Gmail - main': (time.time(), 3),
        }

    def tearDown(self):
        try:
            os.unlink(self.tmp_vocab.name)
        except Exception:
            pass

    def test_propose_writes_review_queue(self):
        """LLM propose → vocab review_queue 多出 item."""
        fake_llm_resp = json.dumps({
            'proposed_categories': [{
                'id': 'writing_email',
                'keywords': ['Outlook', 'Gmail'],
                'directive_hint': 'Sir 在写邮件',
                'evidence_titles': ['Outlook - Inbox', 'Gmail - main'],
            }]
        })
        with patch('jarvis_screen_tease_reflector.safe_openrouter_call',
                   return_value=fake_llm_resp):
            result = self.r.force_run_now()
        self.assertTrue(result.get('ok'), f'reflect should succeed: {result}')
        self.assertEqual(result.get('proposed_n'), 1)
        # 重读 vocab
        with open(self.tmp_vocab.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        review = data.get('review_queue', [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]['id'], 'writing_email')
        self.assertEqual(review[0]['state'], 'review')
        self.assertEqual(review[0]['source'], 'L7 reflector')

    def test_dedup_no_double_propose(self):
        """LLM propose 重复 id → 跳过."""
        # 先注入一个 active id
        with open(self.tmp_vocab.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['categories'].append({
            'id': 'writing_email',
            'state': 'active',
            'keywords': ['Outlook'],
            'directive_hint': 'existing',
        })
        with open(self.tmp_vocab.name, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # LLM 还是 propose 同 id
        fake_resp = json.dumps({
            'proposed_categories': [{
                'id': 'writing_email',
                'keywords': ['Outlook', 'Gmail'],
                'directive_hint': 'dup',
            }]
        })
        with patch('jarvis_screen_tease_reflector.safe_openrouter_call',
                   return_value=fake_resp):
            result = self.r.force_run_now()
        # ok but 0 added (因 dedup)
        self.assertTrue(result.get('ok'))
        self.assertEqual(result.get('proposed_n'), 0)

    def test_llm_parse_failure_no_crash(self):
        """LLM 返非 JSON → 静默 fail."""
        with patch('jarvis_screen_tease_reflector.safe_openrouter_call',
                   return_value='not a json'):
            result = self.r.force_run_now()
        self.assertFalse(result.get('ok'))
        self.assertIn('parse fail', result.get('reason', ''))


class TestBeta535BCentralNerveWiring(unittest.TestCase):
    """central_nerve 启动时 wire screen_tease_reflector."""

    def test_central_nerve_starts_reflector(self):
        """jarvis_central_nerve.py 必须含 ScreenTeaseReflector 启动代码."""
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.35-B', src,
            'β.5.35-B marker 必须在 jarvis_central_nerve.py')
        self.assertIn('ScreenTeaseReflector', src,
            'ScreenTeaseReflector 必须被 wire')
        self.assertIn('screen_tease_reflector', src,
            '必须 self.screen_tease_reflector 字段')


if __name__ == '__main__':
    unittest.main()
