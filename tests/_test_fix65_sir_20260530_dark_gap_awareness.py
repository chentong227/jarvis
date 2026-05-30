# -*- coding: utf-8 -*-
"""[Self-Memory P0 / Sir 2026-05-30] 离线 gap 感知 (dark gap awareness) 回归.

Sir 真痛: "我两天没打开贾维斯, 但他没有'他没开着'的时间概念."

根因 (已核源码):
  1. cold_starts.jsonl 的 prev_cold_start_age_s 算出来全仓零消费者 (死数据)
  2. build_lifetime_block 跨 session 维度只报"次数+总跨度", 不报"我离线了多久"
  3. 账本被污染: test/script import 构造 daemon 一秒写 5 条空 session_id + prev=0
  4. 无"上次活着"锚点 (无心跳)

P0 治本 (本测覆盖):
  - 数据卫生: 无真 session 不写 + 同 session dedup
  - last_alive 心跳 → 算真 dark_gap (离线时长, 比 prev_cold_start_age_s 准)
  - build_lifetime_block surface "你离线了多久" (中性事实, 仅刚回来 surface)

测试覆盖 (P0A 卫生 / P0B 心跳 / P0C dark_gap / P0D surface / P0E format):
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


def _make_daemon():
    """Make daemon with mock deps (no real LLM/nerve). __init__ 内 _append_cold_
    start_record 因测试环境无真 session → no-op (不污染真账本)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=None,
    )


def _isolate(daemon, tmpdir):
    """把 daemon 的 cold_starts / last_alive 路径指到 tmp (instance attr 遮 class attr)."""
    daemon._COLD_STARTS_PATH = os.path.join(tmpdir, 'cold_starts.jsonl')
    daemon._LAST_ALIVE_PATH = os.path.join(tmpdir, 'last_alive.json')


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


# ============================================================
# P0A — 数据卫生 (gate 真 session + dedup)
# ============================================================

class TestP0AHygiene(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_no_session_no_write(self):
        """无真 session (空 session_id) → 不写 (修 test/script import 污染)."""
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value=''):
            self.daemon._append_cold_start_record()
        self.assertEqual(_read_jsonl(self.daemon._COLD_STARTS_PATH), [],
            "无 session 不该写 cold_start record")

    def test_real_session_writes_once(self):
        """真 session → 写 1 条."""
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_test_A'):
            self.daemon._append_cold_start_record()
        recs = _read_jsonl(self.daemon._COLD_STARTS_PATH)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['session_id'], 'sess_test_A')

    def test_same_session_dedup(self):
        """同 session 二次调 → dedup, 不重复 append (修一秒 5 条)."""
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_test_A'):
            self.daemon._append_cold_start_record()
            self.daemon._append_cold_start_record()
            self.daemon._append_cold_start_record()
        recs = _read_jsonl(self.daemon._COLD_STARTS_PATH)
        self.assertEqual(len(recs), 1,
            "同 session 多次构造只该有 1 条 (dedup)")

    def test_new_session_appends(self):
        """不同 session → 真 append 第 2 条."""
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_test_A'):
            self.daemon._append_cold_start_record()
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_test_B'):
            self.daemon._append_cold_start_record()
        recs = _read_jsonl(self.daemon._COLD_STARTS_PATH)
        self.assertEqual(len(recs), 2)


# ============================================================
# P0B — last_alive 心跳
# ============================================================

class TestP0BHeartbeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_persist_with_session(self):
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_hb'):
            ok = self.daemon._persist_heartbeat()
        self.assertTrue(ok)
        rec = self.daemon._read_last_alive()
        self.assertIsNotNone(rec)
        self.assertEqual(rec['session_id'], 'sess_hb')
        self.assertGreater(float(rec['ts']), 0)

    def test_no_session_no_heartbeat(self):
        """无 session 不写心跳 (否则 test 污染 → 下次 dark_gap 失真)."""
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value=''):
            ok = self.daemon._persist_heartbeat()
        self.assertFalse(ok)
        self.assertIsNone(self.daemon._read_last_alive())

    def test_read_missing_returns_none(self):
        self.assertIsNone(self.daemon._read_last_alive())


# ============================================================
# P0C — 真 dark_gap (now - 上次心跳)
# ============================================================

class TestP0CDarkGap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def test_dark_gap_from_prior_heartbeat(self):
        """写一个 2 天前的 last_alive → 冷启 record 应含 dark_gap_s ≈ 2 天."""
        two_days = 2 * 86400
        old_ts = time.time() - two_days
        with open(self.daemon._LAST_ALIVE_PATH, 'w', encoding='utf-8') as f:
            json.dump({'ts': old_ts,
                       'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                 time.localtime(old_ts)),
                       'session_id': 'sess_old'}, f)
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_new'):
            self.daemon._append_cold_start_record()
        recs = _read_jsonl(self.daemon._COLD_STARTS_PATH)
        self.assertEqual(len(recs), 1)
        gap = recs[0].get('dark_gap_s')
        self.assertIsNotNone(gap, "record 应含 dark_gap_s")
        # 容差 ±120s
        self.assertAlmostEqual(gap, two_days, delta=120)

    def test_dark_gap_none_when_no_prior_heartbeat(self):
        """首次跑 (无 last_alive) → dark_gap_s = None (诚实, 不编造)."""
        with patch('jarvis_utils.TraceContext.get_session_id',
                    return_value='sess_first'):
            self.daemon._append_cold_start_record()
        recs = _read_jsonl(self.daemon._COLD_STARTS_PATH)
        self.assertIsNone(recs[0].get('dark_gap_s'))


# ============================================================
# P0D — build_lifetime_block surface dark gap
# ============================================================

class TestP0DSurface(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.daemon = _make_daemon()
        _isolate(self.daemon, self.tmp)

    def _write_self_record(self, dark_gap_s):
        rec = {
            'ts': time.time(),
            'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'session_id': 'sess_now',
            'prev_cold_start_age_s': dark_gap_s,
            'dark_gap_s': dark_gap_s,
            'prev_last_alive_iso': '2026-05-28T20:00:00',
            'reason': 'restart',
        }
        with open(self.daemon._COLD_STARTS_PATH, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    def test_surfaces_long_gap_when_fresh(self):
        """离线 2 天 + 刚起 (uptime~0) → block 含 'NOT running'."""
        self._write_self_record(2 * 86400)
        self.daemon._process_start_ts = time.time()  # uptime ~0
        block = self.daemon.build_lifetime_block(mode='full')
        self.assertIn('NOT running', block,
            "离线 2 天刚回来应 surface dark gap")
        self.assertIn('2d', block, "应含人读时长 2d")

    def test_no_surface_below_threshold(self):
        """离线 60s (< 1h min_surface) → 不 surface (短重启不报)."""
        self._write_self_record(60)
        self.daemon._process_start_ts = time.time()
        block = self.daemon.build_lifetime_block(mode='full')
        self.assertNotIn('NOT running', block,
            "短离线 (<1h) 不该 surface")

    def test_no_surface_when_stale_uptime(self):
        """离线 2 天但已跑 2h (> relevant_uptime 1h) → 不 surface ('刚回来'不再是 news)."""
        self._write_self_record(2 * 86400)
        self.daemon._process_start_ts = time.time() - 7200  # uptime 2h
        block = self.daemon.build_lifetime_block(mode='full')
        self.assertNotIn('NOT running', block,
            "跑久了不再 surface 'just came back'")

    def test_null_dark_gap_hedges_not_fabricates(self):
        """🆕 [诚信修 Sir 23:38 真机 BUG 回归] 首次重启 dark_gap=null →
        不冒充精确离线时长 (老兜底说 'NOT running ~3h' 误导, 主脑还编出 '12min/23:14')
        → 改成诚实 HEDGE: 真离线未知, 别编精确数字.
        """
        rec = {
            'ts': time.time(),
            'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'session_id': 'sess_now',
            'prev_cold_start_age_s': 10689,   # ~3h 距上次 LAUNCH (含运行时长, 非真离线)
            'dark_gap_s': None,               # 无前序心跳 → 真离线未知
            'prev_last_alive_iso': '',
            'reason': 'restart',
        }
        with open(self.daemon._COLD_STARTS_PATH, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        self.daemon._process_start_ts = time.time()  # fresh
        block = self.daemon.build_lifetime_block(mode='full')
        self.assertNotIn('NOT running for', block,
            "dark_gap 未知时不该冒充精确离线时长 (老 BUG 根因)")
        self.assertIn('UNKNOWN', block, "应诚实告知离线时长未知")
        self.assertIn('do NOT invent', block, "应指示主脑别编精确数字 (准则 5)")


# ============================================================
# P0E — _format_duration_human
# ============================================================

class TestP0EFormat(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()

    def test_format_durations(self):
        f = self.daemon._format_duration_human
        self.assertEqual(f(30), '30s')
        self.assertEqual(f(90), '1min')
        self.assertEqual(f(3600), '1h')
        self.assertEqual(f(3660), '1h 1min')
        self.assertEqual(f(86400), '1d')
        self.assertEqual(f(2 * 86400 + 3 * 3600), '2d 3h')


if __name__ == '__main__':
    unittest.main(verbosity=2)
