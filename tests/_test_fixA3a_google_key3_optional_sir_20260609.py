# -*- coding: utf-8 -*-
"""[fixA3a-google-key3-optional / Sir 2026-06-09] GOOGLE_KEY_3 改 optional.

根因: GOOGLE_KEY_3 误列 _REQUIRED_ENV_VARS → 缺它 load_keys raise 阻塞启动
(今早靠 .env 临时占位撑). 改法: 移到 _OPTIONAL + GOOGLE_LIST 动态 _google_pool
filter (收非空有效 key, 跳过空/占位/DEPRECATED).

测法 (绝不改真 .env): monkeypatch _load_dotenv_if_present 为 no-op (隔离真 .env)
+ patch os.environ 为干净受控集. load_keys 全程只读 os.environ.

T1 缺 GOOGLE_KEY_3 不 raise: env 留 GEMINI_KEY+GOOGLE_KEY_2 → 通过, pool=2.
T2 有 GOOGLE_KEY_3 行为不变: 3 key → 通过, pool=3.
T3 占位/空值被 filter: GOOGLE_KEY_3=空/REPLACE_ME → pool 不收, 不 raise.
T4 必需 key 仍强制: 去掉 GEMINI_KEY → 仍 raise.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _base_env():
    """全套必需 key (除 GOOGLE_KEY_3) 的干净 env."""
    return {
        'OPENROUTER_MAIN': 'sk-or-main',
        'OPENROUTER_2': 'sk-or-2',
        'OPENROUTER_3': 'sk-or-3',
        'GEMINI_KEY': 'AIza-gemini',
        'GOOGLE_KEY_2': 'AIza-key2',
    }


def _load_with_env(env_dict):
    """干净 env + no-op dotenv 跑 load_keys. 返回 JarvisKeys 或抛."""
    import jarvis_config.keys as keys
    with mock.patch.object(keys, '_load_dotenv_if_present', lambda: None):
        with mock.patch.dict(os.environ, env_dict, clear=True):
            return keys.load_keys()


class TestFixA3aGoogleKey3Optional(unittest.TestCase):

    def test_t1_missing_key3_no_raise(self):
        k = _load_with_env(_base_env())  # 无 GOOGLE_KEY_3
        self.assertEqual(len(k.GOOGLE_LIST), 2,
                         "缺 GOOGLE_KEY_3 → 不 raise, GOOGLE_LIST 收 2 个")

    def test_t2_with_key3_unchanged(self):
        env = _base_env()
        env['GOOGLE_KEY_3'] = 'AIza-key3'
        k = _load_with_env(env)
        self.assertEqual(len(k.GOOGLE_LIST), 3, "有 3 key → pool=3 (行为不变)")

    def test_t3_placeholder_filtered(self):
        for ph in ('', 'REPLACE_ME', 'REPLACE_ME_OPTIONAL'):
            env = _base_env()
            env['GOOGLE_KEY_3'] = ph
            k = _load_with_env(env)
            self.assertEqual(len(k.GOOGLE_LIST), 2,
                             f"占位 {ph!r} 应被 filter → pool=2")

    def test_t4_required_key_still_enforced(self):
        env = _base_env()
        del env['GEMINI_KEY']  # 去掉真正 required 的
        with self.assertRaises(RuntimeError):
            _load_with_env(env)


if __name__ == '__main__':
    unittest.main()
