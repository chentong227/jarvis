# -*- coding: utf-8 -*-
"""
[P0+20-β.4.10 / 2026-05-19] STM 持久化 + ProactiveCare silent gate

Sir 02:00 实测痛点:
1. STM 重启清空: Sir 跟 Jarvis 聊涌现, 为找 BUG 重启 Jarvis, Jarvis 不记得了 (准则 4 退步)
2. ProactiveCare silent_text 不占全局 cooldown:
   凌晨 1 点 sleep silent push → 立刻 hydration silent push → Sir 烦 + attribution 错 (
   Sir 回应 sleep 但被 attribute 给 hydration)

修复:
- CentralNerve init 加 _restore_stm_from_disk + _start_stm_persist_daemon (atomic dump 30s)
- ProactiveCare 加 SILENT_GLOBAL_COOLDOWN_S=90 + last_silent_global_ts 独立 gate
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# STM 持久化
# ==========================================================================

class TestP0Plus20Beta410STMPersist(unittest.TestCase):
    """STM 持久化 — restore + dump + atomic."""

    def setUp(self):
        # 不实例化 CentralNerve (太重), 直接测 helper 方法
        # 把 helper 拆下来到一个 mock instance 用
        from jarvis_central_nerve import CentralNerve
        self.tmp = tempfile.mktemp(suffix='_stm.jsonl')
        # 创最小 mock instance 含必要字段
        instance = CentralNerve.__new__(CentralNerve)
        instance._stm_persist_path = self.tmp
        instance._stm_persist_max = 50
        instance._stm_persist_interval_s = 30.0
        instance.short_term_memory = []
        instance._stm_importance_scores = {}
        instance._stm_dirty = False
        import threading
        instance._stm_persist_lock = threading.Lock()
        self.inst = instance

    def tearDown(self):
        for p in (self.tmp, self.tmp + '.tmp'):
            try:
                os.unlink(p)
            except (OSError, FileNotFoundError):
                pass

    def test_persist_dump_creates_jsonl(self):
        self.inst.short_term_memory = [
            {'time': '01:48:00', 'user': '问涌现', 'jarvis': 'Emergence is...'},
            {'time': '01:48:30', 'user': '继续', 'jarvis': '...complex systems...'},
        ]
        ok = self.inst._persist_stm_to_disk()
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self.tmp), 'jsonl 应创建')
        with open(self.tmp, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            entry = json.loads(line)
            self.assertIn('user', entry)
            self.assertIn('jarvis', entry)

    def test_persist_empty_returns_false(self):
        """STM 空时 _persist 不写文件."""
        self.assertEqual(self.inst.short_term_memory, [])
        ok = self.inst._persist_stm_to_disk()
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.tmp))

    def test_persist_truncates_to_max(self):
        """超 _stm_persist_max 只保留最后 N 条."""
        self.inst._stm_persist_max = 5
        for i in range(20):
            self.inst.short_term_memory.append({
                'time': f'01:{i:02d}:00', 'user': f'q{i}', 'jarvis': f'a{i}',
            })
        self.inst._persist_stm_to_disk()
        with open(self.tmp, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 5, '应只 dump 最后 5 条')
        last = json.loads(lines[-1])
        self.assertEqual(last['user'], 'q19', '最后条应是最新的')

    def test_atomic_write_uses_tmp(self):
        """_persist 写 .tmp 再 replace 防 Ctrl+C 损坏."""
        self.inst.short_term_memory = [{'time': '01:00:00', 'user': 'x', 'jarvis': 'y'}]
        self.inst._persist_stm_to_disk()
        # 写完 .tmp 应该不存在 (已 replace 到 path)
        self.assertFalse(os.path.exists(self.tmp + '.tmp'))
        self.assertTrue(os.path.exists(self.tmp))

    def test_restore_from_disk(self):
        # 先写 jsonl
        with open(self.tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'time': '01:48:00', 'user': '问涌现', 'jarvis': 'Emergence is...'}) + '\n')
            f.write(json.dumps({'time': '01:48:30', 'user': '继续', 'jarvis': '...complex...'}) + '\n')
        # restore
        n = self.inst._restore_stm_from_disk()
        self.assertEqual(n, 2)
        self.assertEqual(len(self.inst.short_term_memory), 2)
        self.assertEqual(self.inst.short_term_memory[0]['user'], '问涌现')

    def test_restore_missing_file_returns_zero(self):
        """文件不存在 → 0, 不挂."""
        self.inst._stm_persist_path = '/nonexistent/xyz.jsonl'
        n = self.inst._restore_stm_from_disk()
        self.assertEqual(n, 0)

    def test_restore_corrupt_lines_skipped(self):
        """corrupt jsonl 行跳过, 不抛."""
        with open(self.tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'user': 'ok', 'jarvis': 'fine'}) + '\n')
            f.write('{not valid json\n')
            f.write(json.dumps({'user': 'ok2', 'jarvis': 'fine2'}) + '\n')
        n = self.inst._restore_stm_from_disk()
        self.assertEqual(n, 2, '损坏行跳过, 2 行有效')

    def test_restore_caps_at_max(self):
        """jsonl 超 max 也只读最后 N 条."""
        self.inst._stm_persist_max = 3
        with open(self.tmp, 'w', encoding='utf-8') as f:
            for i in range(10):
                f.write(json.dumps({'user': f'q{i}', 'jarvis': f'a{i}'}) + '\n')
        n = self.inst._restore_stm_from_disk()
        self.assertEqual(n, 3)
        # 取最后 3 条 (q7/q8/q9)
        self.assertEqual(self.inst.short_term_memory[0]['user'], 'q7')


# ==========================================================================
# ProactiveCare silent global cooldown
# ==========================================================================

class TestP0Plus20Beta410ProactiveCareSilentGate(unittest.TestCase):
    """silent_text 独立全局 cooldown 90s."""

    def test_silent_global_cooldown_constant_defined(self):
        from jarvis_proactive_care import SILENT_GLOBAL_COOLDOWN_S
        self.assertIsInstance(SILENT_GLOBAL_COOLDOWN_S, float)
        self.assertGreater(SILENT_GLOBAL_COOLDOWN_S, 30.0, '至少 30s 防连推')
        self.assertLess(SILENT_GLOBAL_COOLDOWN_S, 300.0, '比 voice 300s 短')

    def test_engine_has_last_silent_global_ts(self):
        """ProactiveCareEngine 应有 last_silent_global_ts 字段."""
        src_path = os.path.join(ROOT, 'jarvis_proactive_care.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('last_silent_global_ts', src,
            'ProactiveCareEngine 必须有 last_silent_global_ts 状态 (β.4.10 silent gate)')
        self.assertIn('SILENT_GLOBAL_COOLDOWN_S', src,
            'SILENT_GLOBAL_COOLDOWN_S 常量必须定义')

    def test_silent_push_updates_silent_global_ts(self):
        """silent push 后 last_silent_global_ts 应 set (不只 silent_history per_concern)."""
        src_path = os.path.join(ROOT, 'jarvis_proactive_care.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 检查 silent push 路径 (channel != voice) 也 set last_silent_global_ts
        self.assertIn('self.last_silent_global_ts = now_ts', src,
            'silent push 后必须 set last_silent_global_ts (β.4.10)')

    def test_silent_gate_check_in_tick(self):
        """_tick 必须查 silent global cooldown."""
        src_path = os.path.join(ROOT, 'jarvis_proactive_care.py')
        with open(src_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('silent_global_cooldown', src,
            '_tick guard 必须有 silent_global_cooldown 拦截 reason')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.4.10 STM persist + silent gate tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
