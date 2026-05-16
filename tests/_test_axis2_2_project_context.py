"""轴 2.2 单元测试：ProjectContextProbe —— 项目维度感知

[Sir-2026-05-15] 现在 STM / feed / 海马体三家都不知道 Sir 当前在哪个项目，跨项目串台。
新模块 ProjectContextProbe：foreground 进程 cwd → up-walk 找 .git → 项目名。
prompt 注入 `=== CURRENT PROJECT ===` 块，主脑切项目时立刻知道在哪个 git root。

跑法：
    cd d:\\Jarvis
    python tests/_test_axis2_2_project_context.py
"""
import os
import re
import sys
import time
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import (
    ProjectContextProbe,
    find_git_root,
    render_project_block,
)


class TestFindGitRoot(unittest.TestCase):
    """find_git_root 的纯函数测试：up-walk 找 .git。"""

    def test_returns_empty_for_empty_path(self):
        self.assertEqual(find_git_root(''), '')

    def test_returns_empty_when_no_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, 'a', 'b', 'c')
            os.makedirs(sub)
            # 没 .git → 空
            self.assertEqual(find_git_root(sub), '')

    def test_returns_root_when_git_in_self(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, '.git'))
            self.assertEqual(find_git_root(tmpdir), os.path.abspath(tmpdir))

    def test_returns_root_when_git_in_ancestor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = tmpdir
            os.makedirs(os.path.join(git_root, '.git'))
            sub = os.path.join(git_root, 'src', 'a', 'b')
            os.makedirs(sub)
            self.assertEqual(find_git_root(sub), os.path.abspath(git_root))

    def test_max_depth_prevents_infinite(self):
        # 给一个很深的路径但没 .git → 不应死循环
        with tempfile.TemporaryDirectory() as tmpdir:
            # 构造一个 5 级路径，无 .git
            sub = tmpdir
            for i in range(5):
                sub = os.path.join(sub, f'level{i}')
            os.makedirs(sub)
            self.assertEqual(find_git_root(sub, max_depth=3), '')

    def test_returns_jarvis_root_in_repo(self):
        """本测试在 D:\\Jarvis 仓库里跑，应能找到自己的 git root。"""
        result = find_git_root(os.path.dirname(os.path.abspath(__file__)))
        # 应当返回某个含 .git 的祖先（要么是 D:\Jarvis，要么是更上的）
        # 注意：可能 Jarvis 仓库根本没初始化 .git，那 result 就是 ''
        if result:
            # 至少 path 末尾应当含 .git 同级目录
            self.assertTrue(os.path.isdir(os.path.join(result, '.git')))


class TestRenderProjectBlock(unittest.TestCase):
    def test_empty_info_returns_empty(self):
        self.assertEqual(render_project_block(None), "")
        self.assertEqual(render_project_block({}), "")

    def test_renders_header_and_rule(self):
        info = {
            'name': 'd-Jarvis',
            'root': 'D:\\Jarvis',
            'process': 'Cursor.exe',
        }
        block = render_project_block(info)
        self.assertIn('=== CURRENT PROJECT ===', block)
        self.assertIn('d-Jarvis', block)
        self.assertIn('Cursor.exe', block)
        self.assertIn('PROJECT RULE', block)
        self.assertIn('this project', block)

    def test_no_name_returns_empty(self):
        self.assertEqual(render_project_block({'root': '/foo'}), "")


class TestProjectContextProbe(unittest.TestCase):
    def test_init_no_crash(self):
        probe = ProjectContextProbe()
        self.assertIsNone(probe._cached_project)
        self.assertEqual(probe._cached_at, 0.0)

    def test_get_current_project_no_crash_in_isolated_env(self):
        """没有真实 foreground / git root 也不该挂；返回 None 是合法的。"""
        probe = ProjectContextProbe()
        # 在测试环境调用 → 大概率没有 foreground 是 Cursor.exe 这种本仓库进程；
        # 但函数本身必须不抛异常
        try:
            result = probe.get_current_project()
            # 不挂即通过；可能 None 也可能命中本仓库
            self.assertIsInstance(result, (dict, type(None)))
        except Exception as e:
            self.fail(f"get_current_project 不应抛异常：{e}")

    def test_cache_ttl_works(self):
        probe = ProjectContextProbe()
        # 先调一次填充缓存
        probe.get_current_project()
        first_at = probe._cached_at
        # 立刻再调一次（< 5s 缓存 TTL 内）
        probe.get_current_project()
        # _cached_at 不应被更新（缓存命中）
        self.assertEqual(probe._cached_at, first_at)

    def test_invalidate_forces_refresh(self):
        probe = ProjectContextProbe()
        probe.get_current_project()
        probe.invalidate()
        self.assertEqual(probe._cached_at, 0.0)

    def test_get_with_mocked_foreground_dir_having_git(self):
        """模拟 foreground 进程的 cwd 是某 .git 目录的子目录 → 应正确识别。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = os.path.join(tmpdir, 'fake_project')
            os.makedirs(os.path.join(git_root, '.git'))
            sub = os.path.join(git_root, 'src')
            os.makedirs(sub)

            # patch _detect_current_project 让它返回我们伪造的项目
            import jarvis_utils as _u
            orig = _u._detect_current_project
            try:
                _u._detect_current_project = lambda: {
                    'name': 'fake_project',
                    'root': git_root,
                    'process': 'test.exe',
                }
                probe = ProjectContextProbe()
                info = probe.get_current_project()
                self.assertIsNotNone(info)
                self.assertEqual(info['name'], 'fake_project')
                self.assertEqual(info['root'], git_root)
            finally:
                _u._detect_current_project = orig


class TestPromptInjection(unittest.TestCase):
    """源码契约：project_block 在三档 prompt 都注入。"""

    @classmethod
    def setUpClass(cls):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.src = read_nerve_corpus()

    def test_project_probe_initialized(self):
        self.assertIn('ProjectContextProbe()', self.src,
                      "CentralNerve 必须初始化 ProjectContextProbe")
        self.assertIn('self.project_probe', self.src)

    def test_project_block_computed(self):
        self.assertIn('render_project_block(', self.src)
        self.assertIn('project_block = ', self.src)

    def test_project_block_in_three_tiers(self):
        count = self.src.count('{project_block}')
        # full + SHORT_CHAT + FACTUAL_RECALL 至少 3 处
        self.assertGreaterEqual(count, 3,
            f"project_block 至少要在 full/SHORT_CHAT/FACTUAL_RECALL 三处注入，实际：{count}")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestFindGitRoot),
        loader.loadTestsFromTestCase(TestRenderProjectBlock),
        loader.loadTestsFromTestCase(TestProjectContextProbe),
        loader.loadTestsFromTestCase(TestPromptInjection),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] 轴 2.2 ProjectContextProbe tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
