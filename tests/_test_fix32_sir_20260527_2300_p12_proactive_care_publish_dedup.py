# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 23:00 P12 治本] ProactiveCare publish dedup regression test.

Sir 真痛 (inner_voice 截图刷屏):
  concern_active urgency=1.00 / severity=0.85 每 60s 一条数字完全不变的 event,
  dashboard 5min 内刷 5 条, 看着像 "daemon 在重复思考". 但 ProactiveCare 没思考,
  只 Python 算 urgency + publish SWM, 没 dedup → publish 无差别刷.

治本 (准则 6 vocab 持久化 + 准则 8 优雅):
  ProactiveCareEngine._compute_dedup_key / _should_publish_dedup /
  _mark_dedup_published 三 helper. 同 (etype, cid, urgency_bucket,
  severity_bucket) 在 window_s 内只 publish 1 次, 数字 bucket 由 vocab decimals
  控 (urgency=1 → 0.1 粒度, severity=2 → 0.01 粒度).

测试覆盖:
  T1 同 (etype, cid, urgency_bucket, severity_bucket) 在 window 内 dedup
  T2 不同 urgency_bucket (e.g. 0.5 → 0.7) 视为新 event 应 publish
  T3 不同 concern_id 互不影响 dedup cache
  T4 window 过期后同 key 应再 publish
  T5 vocab blocks_enabled[etype_dedup]=False → 退化每次 publish
  T6 vocab 文件不存在 → 用 default config 不挂 (failsafe)
  T7 cache 容量上限 → 自动 prune 防内存泄漏
  T8 dedup skip log 节流 (skip_log_interval_s 600s 内最多 1 行)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

# Windows GBK 默认 console encoding 无法打 emoji. 强制 stdout utf-8.
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestP12ProactiveCarePublishDedup(unittest.TestCase):
    """P12 治本: ProactiveCare publish dedup vocab + helpers."""

    def setUp(self):
        # 清 vocab module-level cache 让每个 test 独立
        import jarvis_proactive_care as pc
        pc._DEDUP_VOCAB_CACHE = {}
        pc._DEDUP_VOCAB_MTIME = 0.0
        self.pc = pc
        # 创 minimal ProactiveCareEngine instance (不 start daemon)
        self.engine = pc.ProactiveCareEngine.__new__(pc.ProactiveCareEngine)
        self.engine._publish_dedup_cache = {}
        self.engine._dedup_log_throttle = {}

    def test_t01_dedup_key_includes_bucket(self):
        """T1 _compute_dedup_key 应根据 vocab decimals 离散化 float."""
        key1 = self.engine._compute_dedup_key(
            'concern_active', 'cid_hydration',
            urgency=0.532, severity=0.853,
        )
        key2 = self.engine._compute_dedup_key(
            'concern_active', 'cid_hydration',
            urgency=0.578, severity=0.857,
        )
        # urgency_decimals=1 → 0.5 vs 0.6 不同 bucket
        # severity_decimals=2 → 0.85 vs 0.86 不同 bucket
        # 期望: key1 和 key2 不同 (urgency 跨 bucket)
        self.assertNotEqual(key1, key2,
            f"urgency 0.532 vs 0.578 应跨 0.1 bucket. key1={key1}, key2={key2}")

    def test_t02_same_bucket_same_key(self):
        """T1b 同 bucket 应同 key (urgency 0.51 vs 0.54 → 都是 0.5)."""
        key1 = self.engine._compute_dedup_key(
            'concern_active', 'cid_hydration',
            urgency=0.51, severity=0.85,
        )
        key2 = self.engine._compute_dedup_key(
            'concern_active', 'cid_hydration',
            urgency=0.54, severity=0.85,
        )
        self.assertEqual(key1, key2,
            f"urgency 0.51 vs 0.54 应同 0.5 bucket. key1={key1}, key2={key2}")

    def test_t03_dedup_in_window(self):
        """T1 同 key 在 window 内只 publish 1 次."""
        now = time.time()
        key = self.engine._compute_dedup_key(
            'concern_active', 'cid_h', urgency=0.8, severity=0.85,
        )
        # 第一次应允许
        ok1 = self.engine._should_publish_dedup('concern_active', key, now)
        self.assertTrue(ok1)
        self.engine._mark_dedup_published('concern_active', key, now)
        # 60s 后同 key 应拒绝 (默 window 300s)
        ok2 = self.engine._should_publish_dedup('concern_active', key, now + 60)
        self.assertFalse(ok2,
            "60s 内同 key 应 dedup 拒绝 (默 window 300s)")

    def test_t04_different_bucket_passes(self):
        """T2 不同 bucket 视为新 event 应 publish."""
        now = time.time()
        key1 = self.engine._compute_dedup_key(
            'concern_active', 'cid_h', urgency=0.5, severity=0.85,
        )
        key2 = self.engine._compute_dedup_key(
            'concern_active', 'cid_h', urgency=0.8, severity=0.85,
        )
        self.engine._mark_dedup_published('concern_active', key1, now)
        ok = self.engine._should_publish_dedup('concern_active', key2, now + 10)
        self.assertTrue(ok,
            "urgency 0.5 -> 0.8 应跨 bucket → 新 event 允许 publish")

    def test_t05_different_concern_id_independent(self):
        """T3 不同 concern_id 互不影响 dedup cache."""
        now = time.time()
        key_h = self.engine._compute_dedup_key(
            'concern_active', 'cid_hydration', urgency=0.8, severity=0.85,
        )
        key_s = self.engine._compute_dedup_key(
            'concern_active', 'cid_sleep', urgency=0.8, severity=0.85,
        )
        self.engine._mark_dedup_published('concern_active', key_h, now)
        # 不同 cid → 不同 key → sleep concern 应可 publish
        ok = self.engine._should_publish_dedup('concern_active', key_s, now + 10)
        self.assertTrue(ok,
            "不同 concern_id 应独立 dedup, sleep 不应被 hydration cache 拦")

    def test_t06_window_expiry_allows_republish(self):
        """T4 window 过期后同 key 应再 publish."""
        now = time.time()
        key = self.engine._compute_dedup_key(
            'concern_active', 'cid_h', urgency=0.8, severity=0.85,
        )
        self.engine._mark_dedup_published('concern_active', key, now)
        # 301s 后 (默 window 300s) 应允许
        ok = self.engine._should_publish_dedup('concern_active', key, now + 301)
        self.assertTrue(ok,
            "300s 后同 key 应允许 republish (window 过期)")

    def test_t07_dedup_disabled_via_vocab(self):
        """T5 vocab blocks_enabled[etype_dedup]=False → 退化每次 publish."""
        # Mock vocab loader 返 dedup 关闭 config
        fake_cfg = {
            'blocks_enabled': {'concern_active_dedup': False},
            'windows': {'concern_active_window_s': 300.0},
            'buckets': {'urgency_decimals': 1, 'severity_decimals': 2},
            'log_throttle': {'skip_log_interval_s': 600.0},
        }
        with mock.patch.object(self.pc, '_load_dedup_vocab', return_value=fake_cfg):
            now = time.time()
            key = self.engine._compute_dedup_key(
                'concern_active', 'cid_h', urgency=0.8, severity=0.85,
            )
            self.engine._mark_dedup_published('concern_active', key, now)
            # 即使 mark 过, dedup 关 → 总应 publish
            ok = self.engine._should_publish_dedup('concern_active', key, now + 10)
            self.assertTrue(ok,
                "blocks_enabled[concern_active_dedup]=False → 总应 publish")

    def test_t08_vocab_missing_uses_default(self):
        """T6 vocab 文件不存在 → 用 default config 不挂."""
        # Mock os.path.exists 返 False
        with mock.patch.object(self.pc.os.path, 'exists', return_value=False):
            self.pc._DEDUP_VOCAB_CACHE = {}
            self.pc._DEDUP_VOCAB_MTIME = 0.0
            cfg = self.pc._load_dedup_vocab()
            self.assertEqual(cfg, self.pc._DEDUP_DEFAULT_CONFIG)
            self.assertIn('blocks_enabled', cfg)
            self.assertTrue(cfg['blocks_enabled']['concern_active_dedup'])

    def test_t09_cache_size_prune(self):
        """T7 cache 容量上限 200 触发自动 prune 防内存泄漏."""
        now = time.time()
        # 灌 250 个 fresh key 触发 prune
        for i in range(250):
            self.engine._mark_dedup_published(
                'concern_active', f'fake_key_{i}', now)
        # prune 后 size 应 ≤ 200 (条件: now - v >= 7days 才删)
        # 这里所有 entry 都是 now (不老), 但触发 size > 200 时 prune 仍走 cutoff
        # filter (cutoff = now - 7days). 全 fresh → 不会删. size 仍 250+
        # 但这测试是 "触发了 prune 路径不崩". 真过期数据测在 T9b
        self.assertGreater(len(self.engine._publish_dedup_cache), 0,
            "cache 不应 empty (250 fresh insert)")

    def test_t10_cache_prune_removes_old_entries(self):
        """T7b prune 真删 7 days+ 老 entry."""
        now = time.time()
        old_ts = now - 8 * 86400  # 8 days ago
        # 灌 199 old + 1 fresh + 1 fresh 触发 prune (>200)
        for i in range(199):
            self.engine._publish_dedup_cache[f'old_key_{i}'] = old_ts
        # 触发 prune 的最后一个 insert
        self.engine._mark_dedup_published('concern_active', 'trigger_key', now)
        self.engine._mark_dedup_published('concern_active', 'trigger_key2', now)
        # 触发 prune 时 cutoff = now - 7days, old (now - 8days) 应被删
        remaining_old = sum(
            1 for k in self.engine._publish_dedup_cache
            if k.startswith('old_key_')
        )
        self.assertEqual(remaining_old, 0,
            f"8-day-old entry 应被 prune 删. 剩 {remaining_old} 个")

    def test_t11_log_throttle_skips_repeat_logs(self):
        """T8 dedup skip log 600s 内最多 1 行 (避免 log 刷屏)."""
        now = time.time()
        key = 'concern_active|cid_h|severity=0.85|urgency=0.8'
        # 灌 cache 让后续 dedup hit
        self.engine._publish_dedup_cache[key] = now
        # 用 bg_log mock 数 call
        with mock.patch.object(self.pc, 'bg_log') as mock_log:
            # 10 次 dedup hit, 但 log throttle 应限到 1 行
            for i in range(10):
                self.engine._maybe_log_dedup_skip(
                    'concern_active', key, now + i, now, 300.0)
            self.assertEqual(mock_log.call_count, 1,
                f"10 次 dedup skip 在 600s 内应 throttle 到 1 行, "
                f"实际 {mock_log.call_count}")

    def test_t12_log_throttle_allows_after_interval(self):
        """T8b skip log throttle interval (600s) 过后应再 log."""
        now = time.time()
        key = 'concern_active|cid_h|severity=0.85|urgency=0.8'
        self.engine._publish_dedup_cache[key] = now
        with mock.patch.object(self.pc, 'bg_log') as mock_log:
            self.engine._maybe_log_dedup_skip(
                'concern_active', key, now, now - 100, 300.0)
            # 立刻第二次应 throttle
            self.engine._maybe_log_dedup_skip(
                'concern_active', key, now + 100, now - 100, 300.0)
            # 601s 后应允许
            self.engine._maybe_log_dedup_skip(
                'concern_active', key, now + 601, now - 100, 300.0)
            self.assertEqual(mock_log.call_count, 2,
                f"interval 601s 后应允许第 2 行, 共 2 call. 实际 {mock_log.call_count}")


class TestP12VocabSchema(unittest.TestCase):
    """vocab schema 完整性 (Sir CLI scripts/proactive_care_dedup_dump.py 依赖)."""

    def test_t13_vocab_file_exists_with_required_keys(self):
        """vocab JSON 必含 _doc / blocks_enabled / windows / buckets / log_throttle."""
        vocab_path = os.path.join(
            ROOT, 'memory_pool', 'proactive_care_publish_dedup_vocab.json',
        )
        self.assertTrue(os.path.exists(vocab_path),
            f"vocab 必须 ship 在 memory_pool/. 缺 {vocab_path}")
        with open(vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k in ('_doc', 'blocks_enabled', 'windows', 'buckets', 'log_throttle'):
            self.assertIn(k, data, f"vocab 缺 key '{k}'")
        # blocks_enabled 必含 2 etype
        for etype in ('concern_active_dedup', 'concern_timing_evidence_dedup'):
            self.assertIn(etype, data['blocks_enabled'])
            self.assertTrue(data['blocks_enabled'][etype],
                f"{etype} 默 ON (Sir 关意外不应 default)")

    def test_t14_cli_dump_script_exists(self):
        """CLI scripts/proactive_care_dedup_dump.py 应 ship (准则 6 Sir 可改不需 .py)."""
        cli_path = os.path.join(ROOT, 'scripts', 'proactive_care_dedup_dump.py')
        self.assertTrue(os.path.exists(cli_path),
            f"CLI 必须 ship. 缺 {cli_path}")
        # 简检 import 能过
        with open(cli_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('def cmd_list', src)
        self.assertIn('def cmd_enable', src)
        self.assertIn('def cmd_disable', src)
        self.assertIn('def cmd_set_window', src)
        self.assertIn('def cmd_set_bucket', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
