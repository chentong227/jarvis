# -*- coding: utf-8 -*-
"""
[P0+20-β.4.5.1 / 2026-05-18] INTEGRITY_STACK Session 4 (sub-step 1):
ClaimStatsDumper 跨进程持久化 — _CLAIM_STATS → memory_pool/claim_stats.json.

设计准则:
  - 准则 5 言出必行: dashboard 跨进程读 claim_stats.json 算 verify_rate (β.4.4 hook)
  - 准则 6.5: dump 失败 fail-safe + 路径可注入 + atomic write

测试覆盖 (5 TestClass):
  1. TestDumpStatsToDisk — 基本 dump 行为 + atomic + schema
  2. TestFailSafe — 不可写路径 / 损坏目录全 fail-safe
  3. TestClaimStatsDumper — daemon tick / 启动立刻 dump 一次 / stop 干净
  4. TestCrossModule — dump 后 dashboard.read_integrity_stats 能读到 verify_rate
  5. TestRedLines — 准则 6 反硬编码 + 准则 6.5 持久化 + central_nerve 注册
"""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

# Sir Session 4 设计: claim_tracer 职责单一只做 trace, 反思/持久化在 integrity_reflector
import jarvis_claim_tracer as ct  # 仅用于 _CLAIM_STATS counter 设隐藏验证
import jarvis_integrity_reflector as ir  # noqa: E402


# ---------------------------------------------------------------
# 1. TestDumpStatsToDisk
# ---------------------------------------------------------------

class TestDumpStatsToDisk(unittest.TestCase):

    def setUp(self):
        # 备份原 _CLAIM_STATS, 测试隔离
        self._orig = dict(ct._CLAIM_STATS)
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'claim_stats.json')

    def tearDown(self):
        # 恢复
        ct._CLAIM_STATS.clear()
        ct._CLAIM_STATS.update(self._orig)
        if os.path.exists(self.path):
            os.unlink(self.path)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_dump_writes_json_file(self):
        ok = ir.dump_claim_stats(self.path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self.path))

    def test_dump_schema(self):
        # 模拟有计数
        ct._CLAIM_STATS['total_replies_traced'] = 10
        ct._CLAIM_STATS['total_claims'] = 50
        ct._CLAIM_STATS['total_unverified'] = 5
        ir.dump_claim_stats(self.path)
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for key in ('total_replies_traced', 'total_claims',
                    'total_unverified', 'dumped_at', 'dumped_iso'):
            self.assertIn(key, data)
        self.assertEqual(data['total_replies_traced'], 10)
        self.assertEqual(data['total_claims'], 50)
        self.assertEqual(data['total_unverified'], 5)

    def test_dump_atomic_via_tmp_replace(self):
        # 第 1 次 dump
        ct._CLAIM_STATS['total_claims'] = 100
        ir.dump_claim_stats(self.path)
        with open(self.path, 'r', encoding='utf-8') as f:
            d1 = json.load(f)
        self.assertEqual(d1['total_claims'], 100)
        # 第 2 次 dump 覆盖 (atomic — tmp + replace)
        ct._CLAIM_STATS['total_claims'] = 200
        ir.dump_claim_stats(self.path)
        with open(self.path, 'r', encoding='utf-8') as f:
            d2 = json.load(f)
        self.assertEqual(d2['total_claims'], 200)
        # 应无 .tmp 残留
        self.assertFalse(os.path.exists(self.path + '.tmp'))

    def test_dump_creates_parent_dir(self):
        # 路径中间目录不存在 → 应自动创建
        nested = os.path.join(self.tmpdir, 'sub', 'deep', 'stats.json')
        ok = ir.dump_claim_stats(nested)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(nested))
        # cleanup
        os.unlink(nested)
        os.rmdir(os.path.dirname(nested))
        os.rmdir(os.path.dirname(os.path.dirname(nested)))


# ---------------------------------------------------------------
# 2. TestFailSafe
# ---------------------------------------------------------------

class TestFailSafe(unittest.TestCase):

    def test_unwritable_path_returns_false_no_raise(self):
        # Windows: 用文件名包含非法字符 (':' 在 Windows 不允许在文件名中)
        bad_path = 'memory_pool/invalid:char|name<>.json'
        result = ir.dump_claim_stats(bad_path)
        # 不 raise, 返 False
        self.assertFalse(result)

    def test_dump_no_path_uses_default(self):
        # path=None 走默认 _CLAIM_STATS_DUMP_PATH
        # 此路径在 memory_pool/, 应能写
        default_path = ir._CLAIM_STATS_DUMP_PATH
        ok = ir.dump_claim_stats()  # 无参 = 默认
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(default_path))


# ---------------------------------------------------------------
# 3. TestClaimStatsDumper
# ---------------------------------------------------------------

class TestClaimStatsDumper(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'stats.json')
        # 强制重置单例 (上一个测试可能起过 dumper)
        ir._DEFAULT_CLAIM_STATS_DUMPER = None

    def tearDown(self):
        ir._DEFAULT_CLAIM_STATS_DUMPER = None
        if os.path.exists(self.path):
            os.unlink(self.path)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_dumper_init_defaults(self):
        d = ir.ClaimStatsDumper(tick_seconds=60.0, dump_path=self.path)
        self.assertEqual(d.tick_seconds, 60.0)
        self.assertEqual(d.dump_path, self.path)
        self.assertTrue(d.daemon)
        self.assertEqual(d.name, 'ClaimStatsDumper')

    def test_dumper_starts_and_dumps_immediately(self):
        # 设极短 tick (1s) + 启动 → 应立刻看到 dump 文件
        d = ir.ClaimStatsDumper(tick_seconds=10.0, dump_path=self.path)
        d.start()
        # 给它最多 2s 完成首次 dump
        for _ in range(20):
            if os.path.exists(self.path):
                break
            time.sleep(0.1)
        d.stop()
        d.join(timeout=2.0)
        self.assertTrue(os.path.exists(self.path),
                         '首次启动应立刻 dump 一次')
        stats = d.get_stats()
        self.assertGreaterEqual(stats['dumps_total'], 1)

    def test_dumper_stop_cleanly(self):
        d = ir.ClaimStatsDumper(tick_seconds=0.5, dump_path=self.path)
        d.start()
        time.sleep(0.3)
        d.stop()
        d.join(timeout=3.0)
        self.assertFalse(d.is_alive(), 'stop() 后 daemon 应能退出')

    def test_singleton_factory(self):
        # 同一进程 get_default 多次 → 同一实例
        d1 = ir.get_default_claim_stats_dumper(dump_path=self.path)
        d2 = ir.get_default_claim_stats_dumper(dump_path=self.path)
        self.assertIs(d1, d2)


# ---------------------------------------------------------------
# 4. TestCrossModule — dashboard 端到端
# ---------------------------------------------------------------

class TestCrossModule(unittest.TestCase):

    def setUp(self):
        self._orig = dict(ct._CLAIM_STATS)

    def tearDown(self):
        ct._CLAIM_STATS.clear()
        ct._CLAIM_STATS.update(self._orig)

    def test_dump_then_dashboard_reads_verify_rate(self):
        """端到端: dump _CLAIM_STATS → dashboard reader 算 verify_rate."""
        import jarvis_dashboard as jd

        # 设模拟数据 (100 claim, 20 unverified → verify_rate 0.8)
        ct._CLAIM_STATS['total_claims'] = 100
        ct._CLAIM_STATS['total_unverified'] = 20

        stats_tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        stats_tmp.close()

        try:
            ir.dump_claim_stats(stats_tmp.name)
            # dashboard 读
            audit_tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
            audit_tmp.close()
            try:
                result = jd.read_integrity_stats(
                    audit_path=audit_tmp.name,
                    stats_path=stats_tmp.name,
                )
                self.assertIsNotNone(result['verify_rate'])
                self.assertAlmostEqual(result['verify_rate'], 0.8, places=2)
            finally:
                os.unlink(audit_tmp.name)
        finally:
            os.unlink(stats_tmp.name)


# ---------------------------------------------------------------
# 5. TestRedLines — 准则 6 + 准则 6.5 + central_nerve
# ---------------------------------------------------------------

class TestRedLines(unittest.TestCase):

    def test_no_hardcoded_path_in_module(self):
        # 准则 6.5: dump path 必须可注入 (不是写死 .py)
        # _CLAIM_STATS_DUMP_PATH 是 module-level constant, OK (系统级)
        # 但 dump_claim_stats 必须接 path 入参
        import inspect
        sig = inspect.signature(ir.dump_claim_stats)
        self.assertIn('path', sig.parameters,
                       'dump_claim_stats must accept path kwarg for testcase isolation')

    def test_dumper_class_threading_thread(self):
        # ClaimStatsDumper 必须是 threading.Thread 子类 + daemon=True
        import threading
        d = ir.ClaimStatsDumper()
        self.assertIsInstance(d, threading.Thread)
        self.assertTrue(d.daemon)

    def test_central_nerve_imports_dumper_from_reflector(self):
        # central_nerve.py 应 import 从 jarvis_integrity_reflector (Sir Session 4 决定)
        cn_path = os.path.join(ROOT, 'jarvis_central_nerve.py')
        with open(cn_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from jarvis_integrity_reflector import get_default_claim_stats_dumper',
                       src,
                       'central_nerve must register ClaimStatsDumper from integrity_reflector')
        self.assertIn('ClaimStatsDumper', src)

    def test_claim_tracer_does_not_define_dumper(self):
        # 准则 7 (Sir 设计决定): claim_tracer 职责单一只做 trace,
        # 持久化/反思在 jarvis_integrity_reflector
        ct_path = os.path.join(ROOT, 'jarvis_claim_tracer.py')
        with open(ct_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('class ClaimStatsDumper', src,
                          'claim_tracer should NOT define ClaimStatsDumper (moved to integrity_reflector)')
        self.assertNotIn('def dump_claim_stats', src)

    def test_default_path_is_in_memory_pool(self):
        # 持久化路径必须在 memory_pool/ 下 (gitignore 已 cover)
        self.assertIn('memory_pool', ir._CLAIM_STATS_DUMP_PATH)


if __name__ == '__main__':
    unittest.main(verbosity=2)
