# -*- coding: utf-8 -*-
"""[P0+18-c.5 / 2026-05-15] 海马体 embedding rotation b.4 没修透回归 — 测试

c.5 BUG 链：
1. KeyRouter.report_error 把 PROJECT_DENIED / 403 / permission_denied 当 "普通错误"
   → 累计 3 次才标 unhealthy → google_1 第一次失败后 healthy 仍 True
2. KeyRouter._pick_from_pool 随机选 healthy → 第二轮可能又选 google_1
3. Hippocampus._embed_with_rotation 用 tried_labels 去重，发现重复就 break
   → 实际只试了 1 个 key 就熔断
4. search_memory 的"三 Key 均失败"是静态文案，不管真实尝试几个 → 误导

c.5 修复：
A. KeyRouter.report_error 加 is_permission_error 关键词集合（401/403/permission/forbidden/
   project_denied/unauthorized），一次失败就标 unhealthy（不需 3 次）
B. Hippocampus._embed_with_rotation 改成显式遍历 google_pool 名单：每个 label 独立 build
   client + 健康过滤（跳过 KeyRouter unhealthy 的）+ 真实计数日志
C. search_memory 的熔断文案改成动态计数（"当前所有 google key 均不可用"）

覆盖
----
1. KeyRouter.report_error 一次 PROJECT_DENIED → healthy=False
2. KeyRouter.report_error 一次 403 → healthy=False
3. KeyRouter.report_error 一次 permission denied → healthy=False
4. KeyRouter.report_error 一次 unauthorized / 401 → healthy=False
5. KeyRouter.report_error 一次 普通错误（如 'random_error_xyz'）→ healthy 仍 True（保留旧行为）
6. Hippocampus._embed_with_rotation 显式遍历 google_pool（不靠 KeyRouter 选 key）
7. Hippocampus._embed_with_rotation 跳过 unhealthy key
8. Hippocampus._embed_with_rotation 全部失败时抛 last_err 且日志含真实计数
9. 静态扫描确认 search_memory 不再用静态"三 Key 均失败"文案

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_18_c5_embed_rotation.py
"""

import os
import re
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')
HIPP_PATH = os.path.join(ROOT, 'jarvis_hippocampus.py')


# ============================================================
# A. KeyRouter.report_error 权限错误一次失败就标 unhealthy
# ============================================================

class TestKeyRouterPermissionErrorMarksUnhealthy(unittest.TestCase):
    """[c.5/A] KeyRouter.report_error 看到 PROJECT_DENIED / 403 / permission 等
    一次失败就把 key 标记 unhealthy（旧版需 3 次累计）"""

    def setUp(self):
        # 直接构造一个 KeyRouter 实例
        from jarvis_nerve import KeyRouter
        self.kr = KeyRouter(
            main_brain_key='openrouter_main_key',
            google_keys=['gkey1', 'gkey2', 'gkey3'],
            openrouter_keys=['okey1', 'okey2', 'okey3'],
        )

    def _is_healthy(self, label: str) -> bool:
        key = self.kr._resolve_key(label)
        return self.kr._key_status[key]['healthy']

    def test_project_denied_marks_unhealthy_first_try(self):
        self.assertTrue(self._is_healthy('google_1'))
        self.kr.report_error('google_1', "[AUTH] 403 PROJECT_DENIED: Your project has been denied access.")
        self.assertFalse(self._is_healthy('google_1'),
                         '一次 PROJECT_DENIED 错误后 google_1 应被立刻标 unhealthy')

    def test_403_permission_marks_unhealthy_first_try(self):
        self.assertTrue(self._is_healthy('google_2'))
        self.kr.report_error('google_2', "403 Forbidden: API access denied for this project")
        self.assertFalse(self._is_healthy('google_2'))

    def test_permission_denied_marks_unhealthy_first_try(self):
        self.assertTrue(self._is_healthy('google_3'))
        self.kr.report_error('google_3', "Error: PERMISSION_DENIED — Your account is not authorized")
        self.assertFalse(self._is_healthy('google_3'))

    def test_401_unauthorized_marks_unhealthy_first_try(self):
        # 用 google_1 测试 401（重置一下）
        self.kr._key_status[self.kr._resolve_key('google_1')]['healthy'] = True
        self.kr._key_status[self.kr._resolve_key('google_1')]['error_count'] = 0
        self.kr.report_error('google_1', "401 Unauthorized: invalid credentials")
        self.assertFalse(self._is_healthy('google_1'))

    def test_random_error_still_needs_3_tries(self):
        """保留旧行为：普通错误（不在权限/billing 关键词集合）仍需累计 3 次"""
        self.kr._key_status[self.kr._resolve_key('google_2')]['healthy'] = True
        self.kr._key_status[self.kr._resolve_key('google_2')]['error_count'] = 0
        self.kr.report_error('google_2', "random_network_error_xyz_blah")
        self.assertTrue(self._is_healthy('google_2'),
                        '普通错误第 1 次不应标 unhealthy')
        self.kr.report_error('google_2', "random_network_error_xyz_blah")
        self.assertTrue(self._is_healthy('google_2'),
                        '普通错误第 2 次不应标 unhealthy')
        self.kr.report_error('google_2', "random_network_error_xyz_blah")
        self.assertFalse(self._is_healthy('google_2'),
                         '普通错误累计 3 次后才应标 unhealthy（保留旧行为）')


# ============================================================
# B. Hippocampus._embed_with_rotation 显式遍历 google 池
# ============================================================

class _MockKeyRouter:
    """最小可用的 KeyRouter mock：暴露 _google_pool / _key_status / _try_acquire /
    release / report_error，让 _embed_with_rotation 能正确遍历。"""

    def __init__(self):
        self._google_pool = [
            {'key': 'gkey_alpha', 'label': 'google_1'},
            {'key': 'gkey_beta', 'label': 'google_2'},
            {'key': 'gkey_gamma', 'label': 'google_3'},
        ]
        self._key_status = {
            'gkey_alpha': {'healthy': True, 'error_count': 0, 'label': 'google_1'},
            'gkey_beta': {'healthy': True, 'error_count': 0, 'label': 'google_2'},
            'gkey_gamma': {'healthy': True, 'error_count': 0, 'label': 'google_3'},
        }
        self.report_error_calls = []

    def _try_acquire(self, key):
        return True

    def release(self, key_name):
        pass

    def report_error(self, key_name, err_msg):
        self.report_error_calls.append((key_name, err_msg))
        # 模拟 c.5 修复后的行为：权限错误一次标 unhealthy
        err_lower = err_msg.lower()
        if any(kw in err_lower for kw in (
            'permission', '403', '401', 'forbidden', 'denied', 'project_denied',
        )):
            for k, st in self._key_status.items():
                if st.get('label') == key_name:
                    st['healthy'] = False


class TestEmbedWithRotationExplicitTraversal(unittest.TestCase):
    """[c.5/B] _embed_with_rotation 必须显式遍历 google_pool 名单
    （不靠 KeyRouter 选 key，避免 random.shuffle 重复返同 key 导致 tried_labels break）"""

    def setUp(self):
        from jarvis_hippocampus import Hippocampus
        # 用临时文件 db，避免污染生产 / mkdir(":memory:" dirname) 失败
        self._tmp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp_db.close()
        self.hipp = Hippocampus(db_path=self._tmp_db.name, key_router=_MockKeyRouter())
        # 关闭后台 worker（避免影响测试 / 退出时打日志）
        self.hipp._backfill_worker_started = True

    def tearDown(self):
        try:
            os.unlink(self._tmp_db.name)
        except Exception:
            pass

    def test_all_three_keys_tried_when_each_fails(self):
        """模拟 3 个 google key 全部失败 → 应试满 3 次，每次都换不同 key"""
        from jarvis_hippocampus import Hippocampus
        called_labels = []

        def fake_create_client(api_key=None):
            client = MagicMock()
            client.models.embed_content.side_effect = Exception(
                f"[AUTH] 503 SERVICE_UNAVAILABLE for key={api_key[:4]}"
            )
            return client

        with patch('jarvis_hippocampus.create_genai_client', side_effect=fake_create_client):
            with self.assertRaises(Exception):
                self.hipp._embed_with_rotation(contents=['probe'])

        # 应当 report_error 被调用 3 次（每个 google key 一次）
        labels_called = [c[0] for c in self.hipp.key_router.report_error_calls]
        self.assertEqual(len(labels_called), 3,
                         f"应试满 3 个 key，实际只试了: {labels_called}")
        self.assertEqual(set(labels_called), {'google_1', 'google_2', 'google_3'})

    def test_first_key_success_short_circuits(self):
        """第一个 key 成功就立刻返回，不再继续遍历"""
        mock_response = MagicMock()

        def fake_create_client(api_key=None):
            client = MagicMock()
            if api_key == 'gkey_alpha':
                client.models.embed_content.return_value = mock_response
            else:
                client.models.embed_content.side_effect = Exception('not reached')
            return client

        with patch('jarvis_hippocampus.create_genai_client', side_effect=fake_create_client):
            resp, key_name = self.hipp._embed_with_rotation(contents=['probe'])

        self.assertEqual(key_name, 'google_1')
        self.assertIs(resp, mock_response)

    def test_skips_unhealthy_keys(self):
        """KeyRouter 标 unhealthy 的 key 应被跳过，不计入 tried_labels"""
        # 标 google_1 unhealthy
        self.hipp.key_router._key_status['gkey_alpha']['healthy'] = False

        mock_response = MagicMock()
        called_keys = []

        def fake_create_client(api_key=None):
            called_keys.append(api_key)
            client = MagicMock()
            client.models.embed_content.return_value = mock_response
            return client

        with patch('jarvis_hippocampus.create_genai_client', side_effect=fake_create_client):
            resp, key_name = self.hipp._embed_with_rotation(contents=['probe'])

        # 应该直接跳到 google_2
        self.assertEqual(key_name, 'google_2')
        self.assertNotIn('gkey_alpha', called_keys, 'google_1 unhealthy 时不应被尝试')

    def test_second_key_success_after_first_fails(self):
        """第一个 key 失败 → 自动切到第二个 → 第二个成功"""
        mock_response = MagicMock()

        def fake_create_client(api_key=None):
            client = MagicMock()
            if api_key == 'gkey_alpha':
                client.models.embed_content.side_effect = Exception(
                    "[AUTH] 403 PERMISSION_DENIED for google_1"
                )
            elif api_key == 'gkey_beta':
                client.models.embed_content.return_value = mock_response
            return client

        with patch('jarvis_hippocampus.create_genai_client', side_effect=fake_create_client):
            resp, key_name = self.hipp._embed_with_rotation(contents=['probe'])

        self.assertEqual(key_name, 'google_2',
                         '第一个 key 失败应自动切到第二个，不是直接 break')


# ============================================================
# C. 静态扫描：search_memory 不再用静态"三 Key 均失败"文案
# ============================================================

class TestNoStaticThreeKeyFailedString(unittest.TestCase):
    """[c.5/C] hippocampus.py 不应再出现静态"三 Key 均失败"文案
    （这是 b.4 没修透的误导日志根源）"""

    def test_no_static_three_key_failed_in_hippocampus(self):
        with open(HIPP_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        # 允许在注释里提到（"修 b.4 的'三 Key 均失败'静态文案"），但不应作为 bg_log 输出文本
        # 简化判断：在非注释行中的 bg_log/print 字符串里不应含 "三 Key 均失败"
        offending_lines = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            if '三 Key 均失败' in line:
                # 注释内容里允许；只在 bg_log/print 调用内（含括号+引号）报错
                if ('bg_log(' in line or 'print(' in line or 'log(' in line) and '#' not in line.split('三 Key')[0]:
                    offending_lines.append(f"L{i}: {line.strip()}")
        self.assertEqual([], offending_lines,
                         f'仍存在静态"三 Key 均失败"文案 (应改为动态计数):\n' + '\n'.join(offending_lines))


# ============================================================
# 运行入口
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
