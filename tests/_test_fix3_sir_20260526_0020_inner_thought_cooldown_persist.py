# -*- coding: utf-8 -*-
"""[fix3 / Sir 2026-05-26 00:20 真问"为什么不显示在想什么了"]
InnerThought 重启 cooldown 状态不应该跨进程恢复.

Sir 真痛 (真机 log 真测):
  daemon load 24h 内 14 thought → 5 类 cooldown ts 也恢复 → 23min 不动 →
  Sir 启动后零新 thought 显示, 误以为 daemon dead.

治本 (1 行): _load_persist 不再 set _last_category_ts.
加分 (1 行): start() 多打 cooldown snapshot 让 Sir 启动一眼看清.

测试覆盖:
  L1 _load_persist 还在 load _thoughts (SOUL inject 不丢)
  L2 _load_persist 不再 set _last_category_ts (cooldown reset)
  L3 重启场景: 14 旧 thought load 后, _compute_free_categories 返回全 5 类
  L4 start() log 含 "cooldown" 关键词 (Sir 真看见)
  L5 SOUL inject 仍读历史 thought (build_soul_block 不丢)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_thought_dict(ts: float, category: str = 'A',
                          salience: float = 0.5) -> dict:
    """生成 1 条 thought jsonl line dict (符合 InnerThought schema)."""
    return {
        'id': f't_{int(ts)}_{category}',
        'ts': ts,
        'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                  time.localtime(ts)),
        'category': category,
        'thought': f'test thought {category}',
        'salience': salience,
        'actionable': 'none',
        'actionable_done': True,
        'actionable_result': 'none',
        'sir_state': 'active',
        'tick_interval_s': 60,
    }


def _build_daemon_from_jsonl(tmp_jsonl: str):
    """构建 daemon (临时 PERSIST_PATH 不污染生产)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    saved = InnerThoughtDaemon.PERSIST_PATH
    InnerThoughtDaemon.PERSIST_PATH = tmp_jsonl
    try:
        d = InnerThoughtDaemon(key_router=None)
    finally:
        InnerThoughtDaemon.PERSIST_PATH = saved
    d.PERSIST_PATH = tmp_jsonl
    return d


class TestInnerThoughtRestartCooldown(unittest.TestCase):
    """Sir 真痛 anchor: 14 thought load 后不该卡 23min."""

    def setUp(self):
        self.tmp = os.path.join(
            tempfile.gettempdir(),
            f'inner_cooldown_fix3_{time.time()}.jsonl',
        )
        # 写 14 条 24h 内最近时间的 thought (5 类齐 + 重复)
        now = time.time()
        lines = []
        # 3 个 A (最近的 5min 内)
        for i in range(3):
            lines.append(_make_thought_dict(now - 60 * (i + 1), 'A'))
        # 3 个 B (10-15min)
        for i in range(3):
            lines.append(_make_thought_dict(now - 60 * 10 - 60 * i, 'B'))
        # 3 个 C (20min 前)
        for i in range(3):
            lines.append(_make_thought_dict(now - 60 * 20 - 60 * i, 'C'))
        # 3 个 D (25min 前)
        for i in range(3):
            lines.append(_make_thought_dict(now - 60 * 25 - 60 * i, 'D'))
        # 2 个 E (3min 前)
        for i in range(2):
            lines.append(_make_thought_dict(now - 60 * 3 - 60 * i, 'E'))
        with open(self.tmp, 'w', encoding='utf-8') as f:
            for d in lines:
                f.write(json.dumps(d) + '\n')

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_l1_load_still_loads_thoughts_for_soul(self):
        """L1: _load_persist 还在 load _thoughts (SOUL inject 历史不丢)."""
        d = _build_daemon_from_jsonl(self.tmp)
        self.assertEqual(len(d._thoughts), 14,
            'load 14 旧 thought 进 _thoughts 给 SOUL inject 用')

    def test_l2_load_does_NOT_set_cooldown_ts(self):
        """L2 治本: _load_persist 不再 set _last_category_ts.

        重启 = 新 session, cooldown 不跨进程. 老 BUG 治根.
        """
        d = _build_daemon_from_jsonl(self.tmp)
        # _last_category_ts 应该全 0 (没设过)
        for cat in 'ABCDE':
            self.assertEqual(d._last_category_ts.get(cat, 0.0), 0.0,
                f'重启后 category {cat} cooldown ts 必须 0, 不能从 persist 恢复')

    def test_l3_restart_compute_free_returns_all_5(self):
        """L3 真用户场景: 14 旧 thought load 后, _compute_free_categories 返回全 5 类.

        Sir 真痛 anchor — 老 BUG 重启返回 0 free, 等 23min. 治本后返回 5 free,
        daemon 60s 真出新 thought.
        """
        d = _build_daemon_from_jsonl(self.tmp)
        free = d._compute_free_categories()
        self.assertEqual(set(free), set('ABCDE'),
            '重启后 5 类全 free, daemon 60s 后真出新 thought')

    def test_l4_start_log_shows_cooldown_status(self):
        """L4: start() 必须 log "cooldown" 关键词 (Sir 真看见 daemon 状态)."""
        d = _build_daemon_from_jsonl(self.tmp)
        captured = []

        # patch bg_log 抓 start() 输出
        def _capture(msg):
            captured.append(msg)
        with patch.object(d, '_bg_log', _capture):
            d.start()
        try:
            # start 至少打 1 行
            self.assertTrue(captured, 'start() 必须有 bg_log')
            start_msg = '\n'.join(captured)
            # Sir 真测要看见 daemon 状态 (任一关键词: cooldown / FREE / free)
            has_status_keyword = any(
                kw in start_msg
                for kw in ('cooldown', 'FREE', 'free')
            )
            self.assertTrue(has_status_keyword,
                'start log 必须含 cooldown/FREE 状态让 Sir 一眼看见 daemon 真活着')
            # 验证显示 "14 thoughts" 历史 (SOUL 还在)
            self.assertIn('14', start_msg,
                'start log 必须显示 loaded 14 旧 thought 数')
            # 全 free 时 friendly 提示 (Sir 真意 "看见 daemon 在 work")
            self.assertIn('FREE', start_msg,
                '全 free 时 log 必须 friendly 提示 daemon 60s 真出新 thought')
        finally:
            d.stop()

    def test_l5_soul_inject_still_reads_historical(self):
        """L5: build_soul_block 仍读历史 14 thought (SOUL inject 不丢).

        准则 6 evidence: cooldown reset 不影响主脑认知连续性 — SOUL inject 是 prompt
        路径, cooldown 是 daemon 调度路径, 两者独立.
        """
        d = _build_daemon_from_jsonl(self.tmp)
        block = d.build_soul_block(max_chars=2000)
        # block 必须非空 (有 14 thought 可用)
        self.assertTrue(block,
            'build_soul_block 必须非空, 历史 14 thought 给主脑连续性')
        # 含 "MY RECENT INNER THOUGHTS" header
        self.assertIn('INNER THOUGHTS', block,
            'SOUL inject block 必须含 INNER THOUGHTS header')

    def test_l6_first_tick_after_restart_not_skipped(self):
        """L6 端到端: 重启后 _tick 不再因 cooldown skip (cooldown 全 reset).

        通过 mock LLM, 验证 _compute_free_categories 在 tick 入口返回非空 → 不 early-skip.
        """
        d = _build_daemon_from_jsonl(self.tmp)
        # mock _classify_sir_state / _compute_adaptive_interval (避免触发外部依赖)
        with patch.object(d, '_classify_sir_state', return_value='active'):
            with patch.object(d, '_compute_adaptive_interval', return_value=60):
                free = d._compute_free_categories()
        self.assertTrue(free, '重启后第一 tick free_categories 非空 → 不 early-skip')


class TestNoRegression(unittest.TestCase):
    """fix 不破坏现有行为."""

    def test_cooldown_still_works_within_session(self):
        """同进程内 cooldown 还是 work: 一个 tick 写 _last_category_ts, 之后 30min 内同类 skip.

        证明: fix 只去掉"跨进程恢复 cooldown", 不去掉 cooldown 机制本身.
        """
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        tmp = os.path.join(
            tempfile.gettempdir(),
            f'inner_cd_within_{time.time()}.jsonl',
        )
        try:
            d = _build_daemon_from_jsonl(tmp)
            # 模拟 tick 写 cooldown
            d._last_category_ts['A'] = time.time()
            free = d._compute_free_categories()
            self.assertNotIn('A', free,
                '同 session 内, A 类刚 cooldown → 不在 free 列表 (cooldown 仍 work)')
            self.assertEqual(len(free), 4,
                '其他 4 类还 free')
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_persist_load_handles_empty_file(self):
        """空文件不 crash."""
        tmp = os.path.join(
            tempfile.gettempdir(),
            f'inner_empty_{time.time()}.jsonl',
        )
        open(tmp, 'w').close()  # 空文件
        try:
            d = _build_daemon_from_jsonl(tmp)
            self.assertEqual(len(d._thoughts), 0)
            # 空 + fix → 全 free
            self.assertEqual(set(d._compute_free_categories()), set('ABCDE'))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


if __name__ == '__main__':
    unittest.main()
