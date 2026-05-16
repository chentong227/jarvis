# -*- coding: utf-8 -*-
"""[轴3-L0.3 / 2026-05-15] SkillRegistry.bootstrap() + autosave daemon — 测试套件

覆盖：
  TestBootstrapEndToEnd       — 启动初始化全流程（load+scan+register+save）
  TestBootstrapKpiPreservation — 重启不丢 KPI（last_30d_success_rate / call_count）
  TestBootstrapErrorTolerance  — load 失败 / scan 失败 不影响主流程
  TestAutosaveDaemon          — 后台自动 save 线程
  TestRealLifeBootstrap       — 真扫 d:\\Jarvis 输出预期 130+ skill

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l0_3_bootstrap_autosave.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry,
    SkillManifest,
    SkillScanner,
    DANGER_SAFE,
    DANGER_RISKY,
    DANGER_DANGEROUS,
    get_registry,
)


def _make_skill(command='audio_hands.set_volume', **overrides):
    base = dict(
        command=command,
        module='l4_hands_pool.l4_audio_hands',
        callable_name='set_volume',
        description='set vol',
        dangerous_flag=DANGER_RISKY,
    )
    base.update(overrides)
    return SkillManifest(**base)


class TestBootstrapEndToEnd(unittest.TestCase):
    """bootstrap 端到端："""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.tmpdir = tempfile.mkdtemp()
        self.jsonl = os.path.join(self.tmpdir, 'reg.jsonl')

    def tearDown(self):
        self.reg.stop_autosave()
        SkillRegistry.reset_instance_for_test()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bootstrap_scans_and_writes_jsonl(self):
        report = self.reg.bootstrap(
            pools_root=ROOT,
            jsonl_path=self.jsonl,
            enable_autosave=False,
        )
        self.assertGreater(report['scanned'], 100)
        self.assertEqual(report['newly_registered'], report['scanned'],
            '空 registry → 全部新注册')
        self.assertGreater(report['total_after_bootstrap'], 100)
        self.assertTrue(os.path.exists(self.jsonl))
        with open(self.jsonl, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 100)

    def test_bootstrap_returns_proper_report_structure(self):
        report = self.reg.bootstrap(
            pools_root=ROOT, jsonl_path=self.jsonl, enable_autosave=False,
        )
        for key in ['loaded_from_jsonl', 'scanned', 'newly_registered',
                    'total_after_bootstrap', 'autosave_started']:
            self.assertIn(key, report)
        self.assertFalse(report['autosave_started'])

    def test_bootstrap_with_autosave_starts_daemon(self):
        report = self.reg.bootstrap(
            pools_root=ROOT,
            jsonl_path=self.jsonl,
            enable_autosave=True,
            autosave_interval_s=10,
        )
        self.assertTrue(report['autosave_started'])
        self.assertTrue(self.reg._autosave_thread.is_alive())


class TestBootstrapKpiPreservation(unittest.TestCase):
    """关键铁则：重启不丢 KPI"""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.tmpdir = tempfile.mkdtemp()
        self.jsonl = os.path.join(self.tmpdir, 'reg.jsonl')

    def tearDown(self):
        self.reg.stop_autosave()
        SkillRegistry.reset_instance_for_test()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_kpi_preserved_across_bootstrap(self):
        """场景：第一次 bootstrap → 跑 skill 攒 KPI → 第二次 bootstrap（重启）→ KPI 保留"""
        # 第一次 bootstrap
        self.reg.bootstrap(pools_root=ROOT, jsonl_path=self.jsonl, enable_autosave=False)
        cmd = 'audio_hands.set_volume'
        self.assertTrue(self.reg.has(cmd), f'必须扫到 {cmd}')

        # 模拟 skill 调用 → 攒 KPI
        for _ in range(8):
            self.reg.record_invocation(cmd, success=True, latency_ms=180)
        for _ in range(2):
            self.reg.record_invocation(cmd, success=False, latency_ms=200, error='boom')
        sk_before = self.reg.get(cmd)
        self.assertEqual(sk_before.call_count_30d, 10)
        self.assertAlmostEqual(sk_before.last_30d_success_rate, 0.8, places=2)

        # 落盘（autosave 关了，手动 save）
        self.reg.save(self.jsonl)

        # **重启**：reset + 重 bootstrap
        SkillRegistry.reset_instance_for_test()
        new_reg = get_registry()
        report = new_reg.bootstrap(
            pools_root=ROOT, jsonl_path=self.jsonl, enable_autosave=False,
        )
        self.assertGreater(report['loaded_from_jsonl'], 100,
            '应从 jsonl 加载之前所有 skill')
        # scanned 还是 130 但 newly_registered 应该是 0（全部已存在）
        self.assertEqual(report['newly_registered'], 0,
            '所有 skill 已在 jsonl，重 scan 不应新增')

        # KPI 必须保留
        sk_after = new_reg.get(cmd)
        self.assertEqual(sk_after.call_count_30d, 10,
            'call_count_30d 必须从 jsonl 恢复')
        self.assertAlmostEqual(sk_after.last_30d_success_rate, 0.8, places=2,
            msg='last_30d_success_rate 必须从 jsonl 恢复')
        self.assertEqual(sk_after.last_error, 'boom')

    def test_metadata_updates_but_kpi_preserved(self):
        """场景：jsonl 已有该 skill 的 KPI，但代码改了 description → register 应更新 desc 保留 KPI"""
        # 预先放一条带 KPI 的 manifest 到 jsonl
        old_sk = _make_skill(description='OLD DESCRIPTION')
        old_sk.call_count_30d = 50
        old_sk.last_30d_success_rate = 0.9
        with open(self.jsonl, 'w', encoding='utf-8') as f:
            f.write(json.dumps(old_sk.to_dict(), ensure_ascii=False) + '\n')

        # bootstrap：load + scan（scan 会发现真实 audio_hands.set_volume，描述不一样）
        self.reg.bootstrap(pools_root=ROOT, jsonl_path=self.jsonl, enable_autosave=False)
        sk = self.reg.get('audio_hands.set_volume')
        self.assertIsNotNone(sk)
        self.assertEqual(sk.call_count_30d, 50, 'KPI 必须保留')
        self.assertAlmostEqual(sk.last_30d_success_rate, 0.9, places=2)
        # desc 必须更新（来自 scan 的真实模块 docstring）
        self.assertNotEqual(sk.description, 'OLD DESCRIPTION',
            'description 应被 scan 的真实值覆盖')


class TestBootstrapErrorTolerance(unittest.TestCase):
    """bootstrap 任何步骤失败不应影响主流程"""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()

    def tearDown(self):
        self.reg.stop_autosave()
        SkillRegistry.reset_instance_for_test()

    def test_nonexistent_pools_root_yields_empty_scan(self):
        report = self.reg.bootstrap(
            pools_root='/nonexistent/path',
            jsonl_path=os.devnull,
            enable_autosave=False,
        )
        self.assertEqual(report['scanned'], 0)

    def test_corrupt_jsonl_does_not_abort(self):
        """jsonl 损坏 → load 跳过损坏行，bootstrap 继续 scan + register"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8') as f:
            f.write('GARBAGE NOT JSON\n')
            f.write(json.dumps(_make_skill().to_dict()) + '\n')
            f.write('MORE GARBAGE\n')
            jsonl = f.name
        try:
            report = self.reg.bootstrap(
                pools_root=ROOT,
                jsonl_path=jsonl,
                enable_autosave=False,
            )
            self.assertEqual(report['loaded_from_jsonl'], 1, '只有 1 行有效')
            self.assertGreater(report['scanned'], 100)
        finally:
            os.unlink(jsonl)


class TestAutosaveDaemon(unittest.TestCase):
    """后台 autosave 线程"""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.tmpdir = tempfile.mkdtemp()
        self.jsonl = os.path.join(self.tmpdir, 'reg.jsonl')

    def tearDown(self):
        self.reg.stop_autosave()
        SkillRegistry.reset_instance_for_test()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_autosave_daemon_writes_when_dirty(self):
        """attribute → dirty=True → daemon 应在 interval 内 save"""
        self.reg.register(_make_skill())
        # 启动 1s autosave
        self.reg._start_autosave_daemon(self.jsonl, interval_s=1)
        # 此时 dirty=True，autosave 1s 后应触发
        time.sleep(2.5)
        self.assertTrue(os.path.exists(self.jsonl))
        # save 后 dirty 应被清
        self.assertFalse(self.reg.is_dirty())

    def test_autosave_idempotent_start(self):
        """重复启动 daemon 不应造成 N 个线程"""
        self.reg._start_autosave_daemon(self.jsonl, interval_s=10)
        first = self.reg._autosave_thread
        self.reg._start_autosave_daemon(self.jsonl, interval_s=10)
        second = self.reg._autosave_thread
        self.assertIs(first, second, '重复 _start_autosave_daemon 应保留同一个线程')

    def test_stop_autosave_terminates_daemon(self):
        self.reg._start_autosave_daemon(self.jsonl, interval_s=10)
        self.reg.stop_autosave()
        time.sleep(0.5)  # 给线程时间退出
        # daemon 标志应为 set
        self.assertTrue(self.reg._autosave_stop.is_set())


class TestRealLifeBootstrap(unittest.TestCase):
    """真扫 d:\\Jarvis 应输出 130+ skill 且关键 case 不回退"""

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()

    def tearDown(self):
        self.reg.stop_autosave()
        SkillRegistry.reset_instance_for_test()

    def test_real_bootstrap_yields_expected_distribution(self):
        with tempfile.TemporaryDirectory() as td:
            jsonl = os.path.join(td, 'reg.jsonl')
            report = self.reg.bootstrap(
                pools_root=ROOT, jsonl_path=jsonl, enable_autosave=False,
            )
            self.assertGreater(report['scanned'], 100)
            self.assertGreater(len(self.reg.all_by_danger('safe')), 20)
            self.assertGreater(len(self.reg.all_by_danger('risky')), 50)
            self.assertGreater(len(self.reg.all_by_danger('dangerous')), 10)


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L0.3 bootstrap + autosave tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
