# -*- coding: utf-8 -*-
"""[P5-Layer1-fix19 / 2026-05-22] main_brain_meta_dump CLI testcase

Sir Layer 1 META 真测时用 dump 工具看主脑思考摘要. 测 CLI 基本功能.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLI_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'scripts', 'main_brain_meta_dump.py'
)


def _seed_audit(path: str, records: list) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')


def _run_cli(args: list, audit_path: str = '') -> tuple:
    cmd = [sys.executable, CLI_PATH] + list(args)
    if audit_path:
        cmd.extend(['--audit-path', audit_path])
    # Windows cp936 默认编码会让中文 emoji 输出 raise UnicodeEncodeError → rc=1.
    # 测试 subprocess 必须强制 UTF-8.
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                            encoding='utf-8', errors='replace', env=env)
    return proc.returncode, proc.stdout, proc.stderr


class TestA_CliExists(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue(os.path.exists(CLI_PATH))

    def test_cli_help(self):
        rc, out, err = _run_cli(['--help'])
        self.assertEqual(rc, 0)
        self.assertIn('main_brain_meta_audit', out + err)


class TestB_EmptyAudit(unittest.TestCase):
    def test_no_audit_file(self):
        rc, out, _ = _run_cli([], audit_path='/tmp/_no_such_file.jsonl')
        self.assertEqual(rc, 0)
        self.assertIn('无记录', out)

    def test_stats_no_records(self):
        rc, out, _ = _run_cli(['--stats'], audit_path='/tmp/_no_such_file.jsonl')
        self.assertEqual(rc, 0)


class TestC_WithRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False, mode='w', encoding='utf-8')
        self.tmp.close()
        records = [
            {
                'turn_id': 'turn_a', 'evidence': ['stm:turn_x'],
                'reaction': 'voice', 'skip_alert': False,
                'note': 'normal turn', 'ts': time.time() - 100,
                'user_input_excerpt': 'hello',
            },
            {
                'turn_id': 'turn_b', 'evidence': ['none'],
                'reaction': 'voice', 'skip_alert': True,
                'note': 'integrity alert empty turn', 'ts': time.time() - 50,
                'user_input_excerpt': 'morning',
            },
            {
                'turn_id': 'turn_c', 'evidence': ['swm:hold_1', 'profile:loc'],
                'reaction': 'silent_text', 'skip_alert': False,
                'note': 'sir in deep work', 'ts': time.time(),
                'user_input_excerpt': 'busy',
            },
        ]
        _seed_audit(self.tmp.name, records)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_default_list(self):
        rc, out, _ = _run_cli([], audit_path=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertIn('turn_a', out)
        self.assertIn('turn_b', out)
        self.assertIn('turn_c', out)

    def test_filter_by_turn(self):
        rc, out, _ = _run_cli(['--turn', 'turn_b'], audit_path=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertIn('turn_b', out)
        self.assertNotIn('turn_a', out)

    def test_filter_skip_alert(self):
        rc, out, _ = _run_cli(['--skip-alert'], audit_path=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertIn('turn_b', out)
        self.assertNotIn('turn_a', out)
        self.assertNotIn('turn_c', out)

    def test_filter_silent(self):
        rc, out, _ = _run_cli(['--silent'], audit_path=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertIn('turn_c', out)
        self.assertNotIn('turn_a', out)
        self.assertNotIn('turn_b', out)

    def test_stats_basic(self):
        rc, out, _ = _run_cli(['--stats'], audit_path=self.tmp.name)
        self.assertEqual(rc, 0)
        self.assertIn('总轮数', out)
        # 1/3 skip_alert
        self.assertIn('skip_alert=yes', out)
        # reaction 分布: voice=2, silent_text=1
        self.assertIn('voice', out)
        self.assertIn('silent_text', out)


if __name__ == '__main__':
    unittest.main()
