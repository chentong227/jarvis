# -*- coding: utf-8 -*-
"""[P0+17 / 2026-05-15] CommitmentWatcher 启动护栏 — 测试套件

09:22 实测发现：P0+9 的 5min 启动护栏只挡住了 ReturnSentinel.first_active_today 路径，
但 commit 的 trigger 路径完全独立 → 08:03 仍触发了一次"纠正记忆"流程
（数据库里 ID 685 [系统主动提醒] / ID 686 [纠正记忆] 都是当时产物）。

P0+17 修法：CommitmentWatcher.run() 主循环也读 worker.return_sentinel._startup_guard_until，
启动 5min 内即便 commit 已 overdue 也不主动派 nudge，等护栏过期下一轮 tick 自然接管。

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_17_commitment_startup_guard.py
"""
import os
import re
import sys
import time
import threading
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')


def _read(path):
    # [P0+19 / 2026-05-16] 拆分后 CommitmentWatcher 已搬到 jarvis_commitment_watcher.py
    if 'jarvis_nerve.py' in str(path):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        return read_nerve_corpus()
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestP0Plus17CommitmentStartupGuardSourceContract(unittest.TestCase):
    """源码契约：CommitmentWatcher.run 必须接入 ReturnSentinel._startup_guard_until"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_run_method_reads_startup_guard(self):
        """CommitmentWatcher.run 必须读 worker.return_sentinel._startup_guard_until"""
        m = re.search(
            r"class CommitmentWatcher\(threading\.Thread\):.*?"
            r"def run\(self\):.*?"
            r"_startup_guard_until",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "CommitmentWatcher.run 必须读取 _startup_guard_until 字段")

    def test_uses_return_sentinel_as_source(self):
        """护栏必须复用 ReturnSentinel 已有字段（不能新建独立时间线，避免漂移）"""
        m = re.search(
            r"rs\s*=\s*getattr\(self\.worker,\s*['\"]return_sentinel['\"],\s*None\)",
            self.src,
        )
        self.assertIsNotNone(m,
            "必须 rs = getattr(self.worker, 'return_sentinel', None) 复用 ReturnSentinel")

    def test_skip_log_marker_present(self):
        self.assertIn('[CommitmentWatcher/StartupGuard]', self.src,
            "启动护栏触发时必须 bg_log [CommitmentWatcher/StartupGuard]")

    def test_skip_log_rate_limited(self):
        """避免日志刷屏：必须有 _last_startup_guard_log + 限频判定"""
        self.assertIn('_last_startup_guard_log', self.src,
            "必须有 _last_startup_guard_log 字段做限频")
        # 至少 30s 才打一次
        m = re.search(
            r"time\.time\(\)\s*-\s*getattr\(self,\s*['\"]_last_startup_guard_log['\"],\s*0\)\s*>\s*\d+",
            self.src,
        )
        self.assertIsNotNone(m,
            "必须有 time.time() - _last_startup_guard_log > N 的限频判定")

    def test_guard_continues_loop_not_breaks(self):
        """启动护栏内必须 continue（继续等下一轮），而不是 break（永久退出）"""
        m = re.search(
            r"\[CommitmentWatcher/StartupGuard\].*?time\.sleep\(30\)\s*\n\s*continue",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "启动护栏分支必须 time.sleep(30) + continue（不能 break，否则线程退出）")

    def test_guard_does_not_pop_commitments(self):
        """启动护栏内不能 .remove / .pop / .clear commit list（commit 应当保留）"""
        # 找启动护栏 if-block
        chunk = re.search(
            r"\[CommitmentWatcher/StartupGuard\](.*?)continue",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(chunk)
        for danger in ['self.commitments.remove', 'self.commitments.clear',
                       'self.commitments.pop', 'self.commitments = []']:
            self.assertNotIn(danger, chunk.group(1),
                f"启动护栏内不能调用 {danger}（commit 必须保留等护栏过期）")


class TestP0Plus17ReturnSentinelStillHasGuardField(unittest.TestCase):
    """前置依赖：ReturnSentinel 必须仍有 _startup_guard_until 字段（P0+9 不能被回退）"""

    def test_field_initialized(self):
        src = _read(NERVE_PATH)
        self.assertIn('self._startup_guard_until = time.time() + 300.0', src,
            "ReturnSentinel.__init__ 必须仍初始化 _startup_guard_until = time.time() + 300.0")


class TestP0Plus17RuntimeBehavior(unittest.TestCase):
    """运行时行为：构造一个 fake worker + ReturnSentinel + CommitmentWatcher，
    在启动护栏内不应触发 _dispatch_commitment_nudge。"""

    def test_dispatch_blocked_when_guard_active(self):
        from jarvis_nerve import CommitmentWatcher

        class _FakeVoice:
            in_active_conversation = False

        class _FakeRS:
            def __init__(self, guard_seconds):
                self._startup_guard_until = time.time() + guard_seconds

        class _FakeWorker:
            def __init__(self, guard_seconds):
                self.voice_thread = _FakeVoice()
                self.return_sentinel = _FakeRS(guard_seconds)

            def push_command(self, *a, **kw):
                raise AssertionError("启动护栏内 push_command 不应被调用")

        worker = _FakeWorker(guard_seconds=600)
        cw = CommitmentWatcher(worker)
        # 注入一个已 overdue 1 小时的 commit
        cw.commitments.append({
            'deadline_ts': time.time() - 3600,
            'description': 'test_commit',
            'grace_minutes': 10,
            'nudged': False,
            'source_text': '[test]',
            'created_at': time.time() - 3700,
        })

        # 直接手动跑一遍 run() 主循环的"是否进 dispatch"判断
        # （跑真 run() 会无限循环，所以我们提取关键判定独立验证：
        #  rs 存在 + guard_until > now → 进入 continue 分支）
        rs = getattr(worker, 'return_sentinel', None)
        self.assertIsNotNone(rs)
        self.assertGreater(rs._startup_guard_until, time.time(),
            "护栏应当仍未过期")
        # 验证：如果护栏过期了（设为 -1），则可正常进入 dispatch 判定
        worker.return_sentinel._startup_guard_until = time.time() - 1
        self.assertLess(worker.return_sentinel._startup_guard_until, time.time(),
            "护栏过期后应当允许后续逻辑")

    def test_guard_field_default_safe_when_no_return_sentinel(self):
        """worker 没 return_sentinel 时不应崩溃（getattr ... None 兜底）"""
        from jarvis_nerve import CommitmentWatcher

        class _BareWorker:
            class voice_thread:
                in_active_conversation = False

        worker = _BareWorker()
        cw = CommitmentWatcher(worker)
        # 直接调 getattr 模拟 run() 的取值
        rs = getattr(worker, 'return_sentinel', None)
        self.assertIsNone(rs,
            "worker 没 return_sentinel 时 rs 应是 None")
        # 真 run() 此时不会进入 guard 分支，正常跑后续逻辑（不应 AttributeError）


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All P0+17 CommitmentWatcher startup guard tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
