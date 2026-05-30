# -*- coding: utf-8 -*-
"""[Self-Memory P4 / Sir 2026-05-30] schema-free 自写记忆 (note-to-self) 回归.

Sir 真意: "随口的记忆" 不属于 concern/directive/joke/milestone 任何 schema → 无处
可记 → 又得 hand-code 一个 schema. P4 治本: <NOTE> 让脑子写任意自由记忆, 持久
self_notes.jsonl, 纳入 recall. 准则 6 信任 LLM 自决记什么.

测试覆盖:
  P4A <NOTE> tag → append self_notes.jsonl; 空/占位/无 tag → 不写
  P4B recall_notes 关键词召回
  P4C recall() 纳入 NOTE 源
  P4D prompt FORMAT 含 <NOTE>; CLI --notes 可跑
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(), concerns_ledger=None,
        relational_state=None, central_nerve=None,
    )


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


class TestP4ANoteTag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        self.daemon._SELF_NOTES_PATH = os.path.join(self.tmp, 'self_notes.jsonl')

    def test_note_tag_persists(self):
        raw = ("<THOUGHT>Sir mentioned tea</THOUGHT>"
               "<NOTE>Sir prefers tea over coffee after 4pm</NOTE>")
        self.daemon._handle_note_tag(raw)
        notes = _read_jsonl(self.daemon._SELF_NOTES_PATH)
        self.assertEqual(len(notes), 1)
        self.assertIn('tea over coffee', notes[0]['text'])

    def test_empty_note_no_write(self):
        self.daemon._handle_note_tag("<NOTE></NOTE>")
        self.assertEqual(_read_jsonl(self.daemon._SELF_NOTES_PATH), [])

    def test_placeholder_note_no_write(self):
        self.daemon._handle_note_tag("<NOTE>none</NOTE>")
        self.assertEqual(_read_jsonl(self.daemon._SELF_NOTES_PATH), [])

    def test_no_note_tag_no_write(self):
        self.daemon._handle_note_tag("<THOUGHT>nothing to note</THOUGHT>")
        self.assertEqual(_read_jsonl(self.daemon._SELF_NOTES_PATH), [])


class TestP4BRecallNotes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        self.daemon._SELF_NOTES_PATH = os.path.join(self.tmp, 'self_notes.jsonl')
        with open(self.daemon._SELF_NOTES_PATH, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'ts': 1, 'text': "Sir's sister visits next week"}) + '\n')
            f.write(json.dumps({'ts': 2, 'text': "Sir prefers tea after 4pm"}) + '\n')

    def test_keyword_recall(self):
        hits = self.daemon.recall_notes('when does his sister visit', top_k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['source'], 'NOTE')
        self.assertIn('sister', hits[0]['content'])

    def test_no_match(self):
        self.assertEqual(self.daemon.recall_notes('quantum physics'), [])


class TestP4CRecallIncludesNotes(unittest.TestCase):
    def test_recall_surfaces_note(self):
        tmp = tempfile.mkdtemp()
        d = _make_daemon()
        d.nerve = None
        d._SELF_THREADS_PATH = os.path.join(tmp, 'threads.json')  # 空河床
        d._SELF_NOTES_PATH = os.path.join(tmp, 'self_notes.jsonl')
        with open(d._SELF_NOTES_PATH, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'ts': 1, 'text': "Sir's cat Mochi vet Friday"}) + '\n')
        out = d.recall('cat vet appointment')
        self.assertTrue(any(h['source'] == 'NOTE' for h in out))


class TestP4DPromptAndCLI(unittest.TestCase):
    def test_prompt_offers_note_tag(self):
        d = _make_daemon()
        system, _user = d._build_prompt(
            sir_state='active',
            evidence={'sir_state': 'active', 'idle_seconds': 10, 'hour': 14},
        )
        self.assertIn('<NOTE>', system)

    def test_cli_notes_runs(self):
        import importlib
        mod = importlib.import_module('scripts.self_threads_dump')
        rc = mod.main(['--notes'])
        self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
