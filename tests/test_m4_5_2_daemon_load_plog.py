# -*- coding: utf-8 -*-
"""[Reshape M4.5.2 / 2026-05-24] CW daemon 启动时也从 PromiseLog 拉 active commitment.

覆盖:
  - _load_from_promise_log_locked 拉 kind=commitment+cyclic 的 pending
  - dedup: 同 description 已在 self.commitments 不重加
  - deadline_str parse 'YYYY-MM-DD HH:MM:SS' / 'HH:MM' 两种格式
  - 失败 parse 跳过 (不错 nudge)
  - 过期 deadline 跳过 (max_age_hours 过滤)
  - kind != commitment/cyclic (e.g. self_promise/watch) 不拉
"""
import os
import sys
import tempfile
import threading
import unittest
import time
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestLoadFromPromiseLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_5_2_')
        self.plog_path = os.path.join(self.tmpdir, 'plog.json')
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test(persist_path=self.plog_path)

    def tearDown(self):
        from jarvis_promise_log import reset_default_log_for_test
        reset_default_log_for_test()
        try:
            import shutil
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def _make_cw(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        cw = CommitmentWatcher.__new__(CommitmentWatcher)
        cw.worker = MagicMock()
        cw.gate = None
        cw.commitments = []
        cw._lock = threading.Lock()
        return cw

    def test_load_commitment_kind_from_plog(self):
        """kind=commitment 的 pending 应被拉到 self.commitments."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        future_iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                     time.localtime(time.time() + 3600))
        plog.register(description='Sir 11pm sleep',
                       kind='commitment', deadline_str=future_iso,
                       author='sir')
        cw = self._make_cw()
        added = cw._load_from_promise_log_locked(max_age_hours=48.0)
        self.assertEqual(added, 1)
        self.assertEqual(len(cw.commitments), 1)
        c = cw.commitments[0]
        self.assertEqual(c['source'], 'promise_log')
        self.assertEqual(c['description'], 'Sir 11pm sleep')
        self.assertGreater(c['deadline_ts'], time.time())
        self.assertTrue(c['promise_id'].startswith('p_'))

    def test_dedup_skip_existing_description(self):
        """已在 self.commitments 的 desc 不重加."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        future_iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                     time.localtime(time.time() + 3600))
        plog.register(description='already in cw',
                       kind='commitment', deadline_str=future_iso,
                       author='sir')
        cw = self._make_cw()
        # 模拟 SQLite 已拉 1 条
        cw.commitments.append({'description': 'already in cw',
                                'deadline_ts': time.time() + 3600,
                                'nudged': False})
        added = cw._load_from_promise_log_locked(max_age_hours=48.0)
        self.assertEqual(added, 0, 'dedup 应 0 加')

    def test_self_promise_kind_not_loaded(self):
        """kind=self_promise 不拉 (不是 commitment/cyclic)."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        plog.register(description='I shall remind sir',
                       kind='self_promise', deadline_str='',
                       author='jarvis')
        cw = self._make_cw()
        added = cw._load_from_promise_log_locked(max_age_hours=48.0)
        self.assertEqual(added, 0)

    def test_no_deadline_skipped(self):
        """deadline_str 解析失败 → skip."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        plog.register(description='no deadline x',
                       kind='commitment', deadline_str='invalid_str',
                       author='sir')
        cw = self._make_cw()
        added = cw._load_from_promise_log_locked()
        self.assertEqual(added, 0, 'parse fail 应 skip 不 nudge 错时间')

    def test_old_deadline_skipped(self):
        """deadline 比 max_age_hours 老 → skip."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        old_iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                  time.localtime(time.time() - 100 * 3600))
        plog.register(description='very old commitment',
                       kind='commitment', deadline_str=old_iso,
                       author='sir')
        cw = self._make_cw()
        added = cw._load_from_promise_log_locked(max_age_hours=48.0)
        self.assertEqual(added, 0)

    def test_cyclic_kind_also_loaded(self):
        """kind=cyclic 也应拉 (CW daemon 也管周期任务)."""
        from jarvis_promise_log import get_default_log
        plog = get_default_log()
        future_iso = time.strftime('%Y-%m-%d %H:%M:%S',
                                     time.localtime(time.time() + 1800))
        plog.register(description='check progress every 30min',
                       kind='cyclic', deadline_str=future_iso,
                       author='jarvis')
        cw = self._make_cw()
        added = cw._load_from_promise_log_locked(max_age_hours=48.0)
        self.assertEqual(added, 1)


class TestParseDeadlineStr(unittest.TestCase):
    def setUp(self):
        from jarvis_commitment_watcher import CommitmentWatcher
        self.cw = CommitmentWatcher.__new__(CommitmentWatcher)

    def test_long_format(self):
        result = self.cw._try_parse_deadline_str('2026-05-24 23:00:00')
        self.assertGreater(result, 0)
        # 验证 parse 出的 ts 转回 ISO 一致
        iso = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(result))
        self.assertEqual(iso, '2026-05-24 23:00:00')

    def test_short_hhmm_format_future(self):
        """'HH:MM' 短格式. 若今天该时间还未到, 应返今天那个 ts."""
        # 取一个稳定未来时间 (e.g. 23:59 几乎永远未来或刚过)
        now = time.localtime()
        future_hh = (now.tm_hour + 2) % 24
        future_str = f'{future_hh:02d}:00'
        result = self.cw._try_parse_deadline_str(future_str)
        self.assertGreater(result, time.time())

    def test_empty_returns_zero(self):
        self.assertEqual(self.cw._try_parse_deadline_str(''), 0.0)
        self.assertEqual(self.cw._try_parse_deadline_str(None), 0.0)

    def test_invalid_returns_zero(self):
        self.assertEqual(self.cw._try_parse_deadline_str('not a time'), 0.0)
        self.assertEqual(self.cw._try_parse_deadline_str('25:99'), 0.0)


if __name__ == '__main__':
    unittest.main()
