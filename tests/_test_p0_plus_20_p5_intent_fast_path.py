# -*- coding: utf-8 -*-
"""[P5-fix20-B1 / 2026-05-22] IntentResolver vocab fast-path 测试.

Sir 14:32 真测痛点修: OpenRouter 全挂 → IntentResolver LLM 全 fail → 0 mutation.
fast-path 在 LLM 之前 keyword 匹配, 高确定性场景直达 tool, LLM 挂兜底.

测试覆盖 (~10 条):
  A: _load_fast_path_vocab — 读 vocab json + filter active
  B: _render_template_value — {sir_utterance} / {after_phrase} / {before_phrase}
  C: _check_vocab_fast_path — 各种命中/不命中场景
  D: required_args 必填空 → skip
  E: resolve_turn fast-path 命中 → skip LLM 直调 tool (mock tool)
  F: resolve_turn fast-path 不命中 → 走 LLM
  G: vocab/CLI 持久化 (准则 6)
  H: telemetry: fast_path_hits 计数
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _make_resolver(tools=None, vocab=None, vocab_path=None):
    """Build IntentResolver with mock tools + optional vocab override."""
    from jarvis_intent_resolver import IntentResolver
    if tools is None:
        # default: project_hold mock returns ok with project_keyword
        def _project_hold(project_keyword='', raw_text='', hours=72.0, **kw):
            if not project_keyword:
                return {'ok': False, 'error': 'project_keyword required'}
            return {'ok': True, 'result': f"hold {project_keyword} {hours}h"}
        tools = {'project_hold': _project_hold}
    r = IntentResolver(
        key_router=None,  # 跳 LLM (key_router=None → _llm_judge 返 _error)
        central_nerve=None,
        tool_registry=tools,
    )
    if vocab_path:
        r._VOCAB_PATH = vocab_path
    return r


class TestA_LoadVocab(unittest.TestCase):
    """A: _load_fast_path_vocab 读 + filter active."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _seed(self, vocab):
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump({'vocab': vocab}, f)

    def test_load_active_only(self):
        self._seed([
            {'phrase': '暂停', 'tool_name': 'project_hold', 'active': True},
            {'phrase': 'old', 'tool_name': 'project_hold', 'active': False},
        ])
        r = _make_resolver(vocab_path=self.tmp.name)
        v = r._load_fast_path_vocab()
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]['phrase'], '暂停')

    def test_load_missing_file(self):
        r = _make_resolver(vocab_path='/no/such/path/vocab.json')
        v = r._load_fast_path_vocab()
        self.assertEqual(v, [])


class TestB_RenderTemplate(unittest.TestCase):
    """B: _render_template_value — 各种占位符."""

    def setUp(self):
        self.r = _make_resolver()

    def test_sir_utterance(self):
        out = self.r._render_template_value(
            '{sir_utterance}', '我想暂停 dashboard 项目', '暂停')
        self.assertEqual(out, '我想暂停 dashboard 项目')

    def test_after_phrase_zh(self):
        out = self.r._render_template_value(
            '{after_phrase}', '我想暂停 dashboard 项目', '暂停')
        self.assertEqual(out, 'dashboard 项目')

    def test_after_phrase_en(self):
        out = self.r._render_template_value(
            '{after_phrase}', 'shelve the new feature', 'shelve')
        self.assertEqual(out, 'the new feature')

    def test_before_phrase(self):
        out = self.r._render_template_value(
            '{before_phrase}', 'driver license put on hold', 'put on hold')
        self.assertEqual(out, 'driver license')

    def test_non_string(self):
        out = self.r._render_template_value(72.0, 'x', 'y')
        self.assertEqual(out, 72.0)

    def test_phrase_not_in_utterance(self):
        out = self.r._render_template_value(
            '{after_phrase}', 'hello world', 'XXX')
        self.assertEqual(out, '')


class TestC_CheckFastPath(unittest.TestCase):
    """C: _check_vocab_fast_path — 各种命中/不命中."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _seed(self, vocab):
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump({'vocab': vocab}, f)

    def test_hit_simple(self):
        self._seed([{
            'phrase': '暂停',
            'tool_name': 'project_hold',
            'tool_args_template': {'project_keyword': '{after_phrase}'},
            'required_args': ['project_keyword'],
            'min_utterance_len': 4,
            'active': True,
        }])
        r = _make_resolver(vocab_path=self.tmp.name)
        m = r._check_vocab_fast_path('我想暂停 dashboard 项目')
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]['name'], 'project_hold')
        self.assertEqual(m[0]['args']['project_keyword'], 'dashboard 项目')
        self.assertEqual(m[0]['_via'], 'fast_path')
        self.assertEqual(m[0]['_phrase'], '暂停')

    def test_no_hit_too_short(self):
        self._seed([{
            'phrase': '暂停',
            'tool_name': 'project_hold',
            'tool_args_template': {'project_keyword': '{after_phrase}'},
            'min_utterance_len': 100,  # too long
            'active': True,
        }])
        r = _make_resolver(vocab_path=self.tmp.name)
        m = r._check_vocab_fast_path('暂停 X')
        self.assertEqual(m, [])

    def test_no_hit_phrase_absent(self):
        self._seed([{
            'phrase': '暂停',
            'tool_name': 'project_hold',
            'tool_args_template': {'project_keyword': '{after_phrase}'},
            'min_utterance_len': 4,
            'active': True,
        }])
        r = _make_resolver(vocab_path=self.tmp.name)
        m = r._check_vocab_fast_path('我想继续做 dashboard')
        self.assertEqual(m, [])

    def test_inactive_skipped(self):
        self._seed([{
            'phrase': '暂停',
            'tool_name': 'project_hold',
            'tool_args_template': {'project_keyword': '{after_phrase}'},
            'min_utterance_len': 4,
            'active': False,  # inactive
        }])
        r = _make_resolver(vocab_path=self.tmp.name)
        m = r._check_vocab_fast_path('我想暂停 X')
        self.assertEqual(m, [])

    def test_unknown_tool_skipped(self):
        self._seed([{
            'phrase': '暂停',
            'tool_name': 'fake_tool_not_registered',
            'tool_args_template': {},
            'min_utterance_len': 4,
            'active': True,
        }])
        r = _make_resolver(vocab_path=self.tmp.name)
        m = r._check_vocab_fast_path('我想暂停 X')
        self.assertEqual(m, [])

    def test_required_args_empty_skipped(self):
        """phrase 命中但 required_arg 抽空 → skip 这条 vocab."""
        self._seed([{
            'phrase': '暂停',
            'tool_name': 'project_hold',
            'tool_args_template': {'project_keyword': '{after_phrase}'},
            'required_args': ['project_keyword'],
            'min_utterance_len': 4,
            'active': True,
        }])
        r = _make_resolver(vocab_path=self.tmp.name)
        # '暂停' 在 utt 末尾, after_phrase = '' → skip
        m = r._check_vocab_fast_path('我决定暂停')
        self.assertEqual(m, [])

    def test_dedup_same_tool(self):
        """两条 vocab 都命中同一 tool → 仅取首条 (vocab order = priority)."""
        self._seed([
            {'phrase': '暂停', 'tool_name': 'project_hold',
             'tool_args_template': {'project_keyword': '{after_phrase}'},
             'required_args': ['project_keyword'], 'min_utterance_len': 4,
             'active': True},
            {'phrase': '搁置', 'tool_name': 'project_hold',
             'tool_args_template': {'project_keyword': '{after_phrase}'},
             'required_args': ['project_keyword'], 'min_utterance_len': 4,
             'active': True},
        ])
        r = _make_resolver(vocab_path=self.tmp.name)
        m = r._check_vocab_fast_path('我想暂停搁置 dashboard 项目')
        # 都命中, 但同一 tool 仅 1 条
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]['_phrase'], '暂停')  # 首条优先


class TestE_ResolveTurnFastPath(unittest.TestCase):
    """E: resolve_turn fast-path 命中 → skip LLM 直调 tool."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()
        # mock tool 跟踪调用
        self.calls = []

        def _mock_tool(**kw):
            self.calls.append(kw)
            return {'ok': True, 'result': 'mocked'}
        self.tools = {'project_hold': _mock_tool}

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _seed_and_resolve(self, vocab, utterance):
        with open(self.tmp.name, 'w', encoding='utf-8') as f:
            json.dump({'vocab': vocab}, f)
        r = _make_resolver(tools=self.tools, vocab_path=self.tmp.name)
        return r, r.resolve_turn(turn_id='turn_test', sir_utterance=utterance)

    def test_fast_path_skip_llm(self):
        """Sir 暂停 X → fast-path 命中 → 直接调 tool, 不调 LLM (key_router=None)."""
        r, result = self._seed_and_resolve(
            [{'phrase': '暂停', 'tool_name': 'project_hold',
              'tool_args_template': {'project_keyword': '{after_phrase}'},
              'required_args': ['project_keyword'], 'min_utterance_len': 4,
              'active': True}],
            '我想暂停 dashboard 项目',
        )
        self.assertTrue(result.get('fast_path_matched'))
        self.assertEqual(len(result['executed']), 1)
        self.assertTrue(result['executed'][0]['ok'])
        self.assertEqual(result['executed'][0]['via'], 'fast_path')
        self.assertEqual(self.calls[0]['project_keyword'], 'dashboard 项目')
        # telemetry
        self.assertEqual(r.stats()['fast_path_hits'], 1)

    def test_fast_path_not_matched_falls_back_to_llm(self):
        """无 vocab 命中 → 走 LLM (key_router=None → LLM fail, 返 _error)."""
        r, result = self._seed_and_resolve(
            [{'phrase': '暂停', 'tool_name': 'project_hold',
              'tool_args_template': {'project_keyword': '{after_phrase}'},
              'required_args': ['project_keyword'], 'min_utterance_len': 4,
              'active': True}],
            '我想继续做 dashboard',  # 不含 phrase
        )
        self.assertFalse(result.get('fast_path_matched'))
        # tool 没被调
        self.assertEqual(len(self.calls), 0)
        # LLM fail (key_router=None)
        self.assertIn('key', result.get('reason', '').lower())


class TestF_VocabPersistence(unittest.TestCase):
    """F: 准则 6 — vocab json + CLI 持久化."""

    def test_vocab_json_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'intent_fast_path_vocab.json')
        self.assertTrue(os.path.exists(path), 'vocab json 应已创建')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('vocab', data)
        self.assertGreater(len(data['vocab']), 0, 'seed vocab 不能空')

    def test_cli_exists_and_help(self):
        cli = os.path.join(ROOT, 'scripts', 'intent_fast_path_dump.py')
        self.assertTrue(os.path.exists(cli))
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        r = subprocess.run([sys.executable, cli, '--help'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn('--list', r.stdout)
        self.assertIn('--add', r.stdout)
        self.assertIn('--test', r.stdout)

    def test_cli_test_command(self):
        cli = os.path.join(ROOT, 'scripts', 'intent_fast_path_dump.py')
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        r = subprocess.run([sys.executable, cli, '--test',
                              '我想先暂停 dashboard 项目'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn('project_hold', r.stdout)


class TestG_Marker(unittest.TestCase):
    """G: marker P5-fix20-B1 出现在源码."""

    def test_marker_in_resolver(self):
        with open(os.path.join(ROOT, 'jarvis_intent_resolver.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-B1', src)
        self.assertIn('_check_vocab_fast_path', src)
        self.assertIn('_execute_tool_calls', src)
        self.assertIn('fast_path_hits', src)

    def test_marker_in_cli(self):
        with open(os.path.join(ROOT, 'scripts', 'intent_fast_path_dump.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-B1', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
