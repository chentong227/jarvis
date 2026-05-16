# -*- coding: utf-8 -*-
"""[P0+20-β.2.4 hotfix / 2026-05-16] 测试 resolve_worker_attr helper +
回归 worker.jarvis.X 伪失效 BUG 修复

根因：P0+19 nerve split 后 sentinel/watcher 的 worker 参数从
JarvisWorkerThread (.jarvis = central_nerve) 改成直接 central_nerve（直持
.hippocampus / .event_bus / .companion_center / ._on_activity_wake）。
原代码 `hasattr(worker, 'jarvis')` 守卫直接 False → 整段功能跳过。

Sir 23:38 报告 BUG：commitment 持久化伪失效 — Commitments 表自 P0+18-e.3 起空。

修法：jarvis_utils.resolve_worker_attr 先 worker.X 后 worker.jarvis.X 回退。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_utils import resolve_worker_attr


class TestResolveWorkerAttr(unittest.TestCase):
    """resolve_worker_attr 双路径优先级 + 容错"""

    def test_none_worker_returns_none(self):
        self.assertIsNone(resolve_worker_attr(None, 'hippocampus'))

    def test_direct_attr_takes_precedence(self):
        """worker.X 优先（P0+19 split 后的新路径）"""
        class _DirectWorker:
            hippocampus = 'DIRECT'

        class _WrappedNerve:
            hippocampus = 'WRAPPED'

        w = _DirectWorker()
        w.jarvis = _WrappedNerve()
        # 直持路径在前
        self.assertEqual(resolve_worker_attr(w, 'hippocampus'), 'DIRECT')

    def test_fallback_to_jarvis_x_when_direct_missing(self):
        """worker.X 缺时回退 worker.jarvis.X（兼容旧 JarvisWorker 包装层）"""
        class _LegacyWorker:
            jarvis = None  # placeholder

        class _Nerve:
            hippocampus = 'FROM_JARVIS'

        w = _LegacyWorker()
        w.jarvis = _Nerve()
        self.assertEqual(resolve_worker_attr(w, 'hippocampus'), 'FROM_JARVIS')

    def test_both_paths_missing_returns_none(self):
        class _Empty:
            pass
        w = _Empty()
        self.assertIsNone(resolve_worker_attr(w, 'hippocampus'))

    def test_jarvis_attr_is_none_returns_none(self):
        class _W:
            jarvis = None
        self.assertIsNone(resolve_worker_attr(_W(), 'hippocampus'))

    def test_direct_attr_none_falls_through_to_jarvis(self):
        """这是关键 case：worker.hippocampus 显式为 None（不 missing 而是 None）
        时也应该回退 jarvis.hippocampus。"""
        class _W:
            hippocampus = None

        class _Nerve:
            hippocampus = 'FROM_JARVIS'

        w = _W()
        w.jarvis = _Nerve()
        self.assertEqual(resolve_worker_attr(w, 'hippocampus'), 'FROM_JARVIS')

    def test_resolves_event_bus(self):
        class _Direct:
            event_bus = 'BUS'
        self.assertEqual(resolve_worker_attr(_Direct(), 'event_bus'), 'BUS')

    def test_resolves_companion_center(self):
        class _Nerve:
            companion_center = 'CC'

        class _W:
            jarvis = _Nerve()
        self.assertEqual(
            resolve_worker_attr(_W(), 'companion_center'), 'CC'
        )

    def test_resolves_callable(self):
        """_on_activity_wake 是 bound method，应能拿到 callable"""
        class _Nerve:
            def _on_activity_wake(self):
                return 'WOKE'

        class _W:
            pass
        w = _W()
        w.jarvis = _Nerve()
        callable_ = resolve_worker_attr(w, '_on_activity_wake')
        self.assertIsNotNone(callable_)
        self.assertTrue(callable(callable_))
        self.assertEqual(callable_(), 'WOKE')


class TestCommitmentWatcherGetHippoFix(unittest.TestCase):
    """回归 BUG：commitment_watcher._get_hippo 必须能拿到 CentralNerve 直持的 hippocampus"""

    def test_get_hippo_finds_direct_hippocampus(self):
        from jarvis_commitment_watcher import CommitmentWatcher

        class _FakeHippo:
            pass

        class _CentralNerve:
            pass

        nerve = _CentralNerve()
        nerve.hippocampus = _FakeHippo()
        # 模拟 P0+19 后的 worker 参数：CentralNerve 直传
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.worker = nerve
        hippo = cw._get_hippo()
        self.assertIs(hippo, nerve.hippocampus)

    def test_get_hippo_fallback_to_jarvis_wrapped_path(self):
        """老 JarvisWorker 包装路径仍兼容"""
        from jarvis_commitment_watcher import CommitmentWatcher

        class _FakeHippo:
            pass

        class _Nerve:
            pass

        class _WrappedWorker:
            pass

        nerve = _Nerve()
        nerve.hippocampus = _FakeHippo()
        w = _WrappedWorker()
        w.jarvis = nerve

        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.worker = w
        hippo = cw._get_hippo()
        self.assertIs(hippo, nerve.hippocampus)

    def test_get_hippo_none_worker_no_crash(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.worker = None
        self.assertIsNone(cw._get_hippo())


class TestNoMoreWorkerJarvisGuards(unittest.TestCase):
    """静态检查：jarvis_*.py 不再有任何 self.worker.jarvis.X 写法
    （除了 jarvis_utils.py 的注释里提到的 doc 字符串）"""

    def test_no_self_worker_jarvis_attr_in_production(self):
        """grep 所有 jarvis_*.py 不能再有 `self.worker.jarvis.` 模式
        （只允许出现在注释 / docstring 里）"""
        import re
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offending = []
        pattern = re.compile(r'self\.worker\.jarvis\.\w+')
        for fname in os.listdir(repo_root):
            if not fname.startswith('jarvis_') or not fname.endswith('.py'):
                continue
            fpath = os.path.join(repo_root, fname)
            try:
                with open(fpath, encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        stripped = line.lstrip()
                        # 跳过注释和 docstring 行
                        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                            continue
                        # 跳过含 `字符内` 的反引号引用（注释里的 reference）
                        if '`self.worker.jarvis' in line:
                            continue
                        if pattern.search(line):
                            offending.append((fname, i, line.strip()))
            except Exception:
                continue
        msg = "\n".join(f"  {f}:{n}  {ln}" for f, n, ln in offending)
        self.assertEqual(len(offending), 0,
                         f"P0+19 split 后仍有 self.worker.jarvis.X 伪失效守卫:\n{msg}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
