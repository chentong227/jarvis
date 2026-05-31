# -*- coding: utf-8 -*-
"""[放下能力 build2 / Sir 2026-05-31] request_capability — 识想要某能力 (影响自身).

Sir 真意: "识能主动影响贾维斯本身" — 不止改权重/体, 也包括发现自己缺某能力、想要它.
actionable=request_capability:<desc> → 写 capability_requests.jsonl 给 Sir 看 (Jarvis
想长出什么能力). 接地 thought.id; 去重防 churn.

覆盖 (tmp 隔离, 无 LLM):
  C1 valid request → 写 jsonl + 返 capability_requested
  C2 desc 过短 → 拒
  C3 去重: 同 desc 近期已记 → skip (不重复堆)
  C4 dispatcher 接线 + prompt 含 request_capability
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_inner_thought_daemon import InnerThoughtDaemon


def _daemon(path):
    d = InnerThoughtDaemon.__new__(InnerThoughtDaemon)
    d._bg_log = lambda *a, **k: None
    d.CAPABILITY_REQUESTS_PATH = path
    return d


def _thought(tid='th_cap'):
    return SimpleNamespace(id=tid, thought="I lack a way to read Sir's calendar",
                           salience=0.8)


class TestRequestCapability(unittest.TestCase):
    def test_c1_valid_request_writes(self):
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "cap.jsonl")
            d = _daemon(p)
            ok, res = d._do_request_capability(
                _thought(),
                "request_capability:a way to read Sir's calendar for deadline reminders")
            self.assertTrue(ok, res)
            self.assertIn("capability_requested", res)
            rows = [json.loads(l) for l in open(p, encoding='utf-8')]
            self.assertEqual(len(rows), 1)
            self.assertIn("calendar", rows[0]["desc"])
            self.assertEqual(rows[0]["thought_id"], "th_cap")
            self.assertEqual(rows[0]["state"], "open")

    def test_c2_too_short_rejected(self):
        with tempfile.TemporaryDirectory() as dd:
            d = _daemon(os.path.join(dd, "cap.jsonl"))
            ok, res = d._do_request_capability(_thought(), "request_capability:x")
            self.assertFalse(ok)
            self.assertIn("too_short", res)

    def test_c3_dedup_recent(self):
        with tempfile.TemporaryDirectory() as dd:
            p = os.path.join(dd, "cap.jsonl")
            d = _daemon(p)
            a = "request_capability:a way to read Sir's calendar for reminders"
            self.assertTrue(d._do_request_capability(_thought(), a)[0])
            ok2, res2 = d._do_request_capability(_thought('th2'), a)
            self.assertFalse(ok2)
            self.assertIn("already_requested", res2)
            rows = [l for l in open(p, encoding='utf-8')]
            self.assertEqual(len(rows), 1)  # 没重复堆

    def test_c4_wired(self):
        with open(os.path.join(ROOT, 'jarvis_inner_thought_daemon.py'),
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn("request_capability:", src)        # prompt
        self.assertIn("_do_request_capability", src)     # dispatcher + handler


if __name__ == '__main__':
    unittest.main(verbosity=2)
