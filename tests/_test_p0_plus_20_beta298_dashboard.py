# -*- coding: utf-8 -*-
"""[P0+20-β.2.9.8 / 2026-05-18] jarvis_dashboard.py — reader 测试 (三大块版)

Sir 反馈 3 轮合成版:
  1. 一窗看所有 (10:06)
  2. 翻译成人话 (10:13)
  3. 三块布局 + 按钮 + Directive 偏移 (10:15)

跑法:
    cd d:\\Jarvis
    python tests/_test_p0_plus_20_beta298_dashboard.py
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util
_DASH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'scripts', 'jarvis_dashboard.py')
_spec = importlib.util.spec_from_file_location('jarvis_dashboard', _DASH_PATH)
dashboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dashboard)


# ============================================================
# A. 人话翻译 helpers
# ============================================================
class TestHumanizeHelpers(unittest.TestCase):
    def test_humanize_age_zh_seconds(self):
        self.assertIn('秒前', dashboard._humanize_age_zh(time.time() - 30))

    def test_humanize_age_zh_minutes(self):
        self.assertIn('分钟前', dashboard._humanize_age_zh(time.time() - 300))

    def test_humanize_age_zh_hours(self):
        self.assertIn('小时前', dashboard._humanize_age_zh(time.time() - 7200))

    def test_humanize_age_zh_days(self):
        self.assertIn('天前', dashboard._humanize_age_zh(time.time() - 86400 * 3))

    def test_humanize_age_zh_zero(self):
        self.assertEqual(dashboard._humanize_age_zh(0), '从没')

    def test_humanize_when_zh_today(self):
        ts = time.time() + 600
        self.assertTrue(dashboard._humanize_when_zh(ts).startswith('今天'))

    def test_humanize_when_zh_tomorrow(self):
        ts = time.time() + 86400 + 600
        result = dashboard._humanize_when_zh(ts)
        # 跨天 boundary 可能落今/明, 任一都接受
        self.assertTrue(result.startswith('今天') or result.startswith('明天'))


# ============================================================
# B. 安全 IO
# ============================================================
class TestSafeIO(unittest.TestCase):
    def test_safe_read_json_missing(self):
        self.assertEqual(dashboard._safe_read_json('/nonexistent/x.json'), {})

    def test_safe_read_json_corrupt(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                            delete=False) as f:
            f.write('{not valid')
            tmpname = f.name
        try:
            self.assertEqual(dashboard._safe_read_json(tmpname), {})
        finally:
            os.remove(tmpname)

    def test_safe_read_jsonl(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                            delete=False, encoding='utf-8') as f:
            f.write('{"a": 1}\n{"b": 2}\nbad\n{"c": 3}\n')
            tmpname = f.name
        try:
            rows = dashboard._safe_read_jsonl(tmpname)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[-1]['c'], 3)
        finally:
            os.remove(tmpname)


# ============================================================
# C. read_now_status (此刻状态条)
# ============================================================
class TestNowStatus(unittest.TestCase):
    def test_no_log_still_returns_clock(self):
        with patch.object(dashboard, '_find_latest_log', return_value=''):
            d = dashboard.read_now_status()
        self.assertIn('wall_clock', d)
        self.assertTrue(d['wall_clock'])

    def test_with_session_log(self):
        fake = (
            "📜 sess_20260518_100000_12345 started\n"
            "active_conversation=True wake_word_detected=jarvis\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log',
                                            delete=False, encoding='utf-8') as f:
            f.write(fake)
            tmpname = f.name
        try:
            with patch.object(dashboard, '_find_latest_log',
                                return_value=tmpname):
                d = dashboard.read_now_status()
            self.assertIn('sess_20260518_100000', d['session_id'])
            self.assertEqual(d['in_conversation'], '在对话中')
        finally:
            os.remove(tmpname)


# ============================================================
# D. read_jarvis_promises
# ============================================================
class TestPromises(unittest.TestCase):
    def test_empty(self):
        with patch.object(dashboard, '_safe_read_json', return_value={}):
            d = dashboard.read_jarvis_promises()
        self.assertEqual(d['total'], 0)
        self.assertEqual(d['pending_n'], 0)

    def test_pending_count(self):
        fake = {
            'p1': {'id': 'p1', 'state': 'pending', 'kind': 'hard',
                   'description': '睡觉', 'deadline_str': '23:00',
                   'registered_at': time.time() - 60, 'evidence': []},
            'p2': {'id': 'p2', 'state': 'fulfilled', 'kind': 'soft',
                   'description': '查 keyrouter', 'registered_at': time.time() - 300,
                   'evidence': [{'kind': 'tool', 'what': 'ok'}]},
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_jarvis_promises()
        self.assertEqual(d['total'], 2)
        self.assertEqual(d['pending_n'], 1)
        self.assertEqual(d['fulfilled_n'], 1)


# ============================================================
# E. read_concerns
# ============================================================
class TestConcerns(unittest.TestCase):
    def test_empty(self):
        with patch.object(dashboard, '_safe_read_json', return_value={}):
            d = dashboard.read_concerns()
        self.assertEqual(d['rows'], [])

    def test_active_sorted_with_zh_name(self):
        fake = {
            'sir_sleep_streak': {
                'state': 'active', 'severity': 0.9,
                'what_i_watch': 'late nights', 'aligned_count': 5,
                'missed_count': 1,
                'recent_signals': [{'when': time.time() - 100}],
            },
            'sir_x_unknown': {
                'state': 'active', 'severity': 0.3,
                'what_i_watch': 'low', 'aligned_count': 0,
                'missed_count': 0, 'recent_signals': [],
            },
            'old_one': {'state': 'archived', 'severity': 1.0},
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_concerns()
        self.assertEqual(len(d['rows']), 2)
        self.assertEqual(d['rows'][0]['id'], 'sir_sleep_streak')
        # 人话翻译 — sleep_streak 有翻译
        self.assertIn('睡眠', d['rows'][0]['zh_name'])
        # 未知 id fallback 用原 id
        self.assertEqual(d['rows'][1]['zh_name'], 'sir_x_unknown')
        # severity_pct 0-100 整数
        self.assertEqual(d['rows'][0]['severity_pct'], 90)


# ============================================================
# F. read_relational
# ============================================================
class TestRelational(unittest.TestCase):
    def test_empty(self):
        with patch.object(dashboard, '_safe_read_json', return_value={}):
            d = dashboard.read_relational()
        self.assertEqual(d['jokes'], [])

    def test_inside_joke(self):
        fake = {'inside_jokes': {'j1': {
            'phrase': '早睡定义灵活', 'state': 'active',
            'birth_ts': time.time() - 86400, 'use_count': 3}}}
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_relational()
        self.assertEqual(len(d['jokes']), 1)
        self.assertEqual(d['jokes'][0]['used'], 3)


# ============================================================
# G. read_directives (β.2.9.8 新加 + 偏移信号)
# ============================================================
class TestDirectives(unittest.TestCase):
    def test_empty(self):
        with patch.object(dashboard, '_safe_read_json', return_value={}):
            d = dashboard.read_directives()
        self.assertEqual(d['total'], 0)
        self.assertEqual(d['rows'], [])

    def test_health_signals(self):
        """4 种健康信号: ✅正常 / ⚠️ 触发未帮 / ❌ 长期空转 / 🌟 候选合并"""
        now = time.time()
        fake = {
            'bilingual_directive': {  # ✅ 健康 (170 fired, 113 helped = 66%)
                'fired': 170, 'helped': 113, 'rejected': 0,
                'last_triggered': now - 60, 'state': 'active',
            },
            'rare_old': {  # ❌ 长期空转 (从没触发 + 没记录)
                'fired': 0, 'helped': 0, 'rejected': 0,
                'last_triggered': 0, 'state': 'active',
            },
            'low_help': {  # ⚠️ 触发未帮 (10 fired, 1 helped = 10%)
                'fired': 10, 'helped': 1, 'rejected': 3,
                'last_triggered': now - 3600, 'state': 'active',
            },
            'merge_candidate': {  # 🌟 候选合并 (30 fired, 29 helped = 96%)
                'fired': 30, 'helped': 29, 'rejected': 0,
                'last_triggered': now - 60, 'state': 'active',
            },
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_directives()
        self.assertEqual(d['total'], 4)
        # health 计数
        self.assertEqual(d['health']['ok'], 1)
        self.assertEqual(d['health']['untriggered'], 1)
        self.assertEqual(d['health']['low_help'], 1)
        self.assertEqual(d['health']['candidate_merge'], 1)

    def test_zh_translation(self):
        fake = {
            'continuity_two_parts': {'fired': 3, 'helped': 1, 'rejected': 0,
                                      'last_triggered': time.time() - 60},
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_directives()
        self.assertIn('两段答', d['rows'][0]['zh_name'])


# ============================================================
# H. read_daemon_status (新 banner pattern)
# ============================================================
class TestDaemonStatus(unittest.TestCase):
    def test_no_log(self):
        with patch.object(dashboard, '_find_latest_log', return_value=''):
            d = dashboard.read_daemon_status()
        self.assertIsNotNone(d['err'])

    def test_grep_smartnudge_proactivecare(self):
        fake = (
            "[CompanionCenter] SmartNudgeSentinel started\n"
            "[CompanionCenter] ProactiveCareEngine 就绪 (mode=LIVE, threshold=0.55)\n"
            "[CompanionCenter] InconsistencyWatcher 就绪\n"
            "[CompanionCenter] HealthProbeDaemon 就绪\n"
            "[ReturnSentinel/Health] win32api OK\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log',
                                            delete=False, encoding='utf-8') as f:
            f.write(fake)
            tmpname = f.name
        try:
            with patch.object(dashboard, '_find_latest_log',
                                return_value=tmpname):
                d = dashboard.read_daemon_status()
            live_ids = [r['id'] for r in d['daemons'] if r['live']]
            self.assertIn('SmartNudge', live_ids)
            self.assertIn('ProactiveCare', live_ids)
            self.assertIn('Inconsistency', live_ids)
            self.assertIn('HealthProbe', live_ids)
            self.assertIn('Return', live_ids)
        finally:
            os.remove(tmpname)


# ============================================================
# I. read_event_stream (新中文 tag)
# ============================================================
class TestEventStream(unittest.TestCase):
    def test_no_log(self):
        with patch.object(dashboard, '_find_latest_log', return_value=''):
            d = dashboard.read_event_stream()
        self.assertIsNotNone(d['err'])

    def test_parse_zh_tags(self):
        fake = (
            "[sess_20260518_100000_12345] 🤝 [ProactiveCare/LIVE] pushed concern=sir_x urgency=0.72\n"
            "[sess_20260518_100100_12345] 📡 [ProactiveCare/Sensor] tick fed 2 signal(s)\n"
            "[sess_20260518_100200_12345] 🛑 [ProactiveCare] skip concern=y urgency=0.50 reason=cd\n"
            "[sess_20260518_100300_12345] ⚖️ [InconsistencyWatcher] FIRE promise=p_xxx\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log',
                                            delete=False, encoding='utf-8') as f:
            f.write(fake)
            tmpname = f.name
        try:
            with patch.object(dashboard, '_find_latest_log',
                                return_value=tmpname):
                d = dashboard.read_event_stream(limit=10)
            self.assertEqual(len(d['events']), 4)
            tags = [e['tag'] for e in d['events']]
            self.assertTrue(any('主动发声' in t for t in tags))
            self.assertTrue(any('信号' in t for t in tags))
            self.assertTrue(any('不打扰' in t for t in tags))
            self.assertTrue(any('言行反差' in t for t in tags))
            self.assertEqual(d['events'][0]['ts'], '10:00:00')
        finally:
            os.remove(tmpname)


# ============================================================
# J. read_review_queues (新 items 结构)
# ============================================================
class TestReviewQueues(unittest.TestCase):
    def test_empty(self):
        with patch.object(dashboard, '_safe_read_json', return_value=[]):
            d = dashboard.read_review_queues()
        self.assertEqual(d['items'], [])

    def test_concern_and_relational_items(self):
        def fake(path, default=None):
            if 'concerns_review' in path:
                return [{'id': 'sir_x', 'what_i_watch': 'new concern about sleep'}]
            if 'relational_review' in path:
                return [{'id': 'j_x', 'phrase': 'new joke candidate'}]
            return default if default is not None else {}
        with patch.object(dashboard, '_safe_read_json', side_effect=fake):
            d = dashboard.read_review_queues()
        self.assertEqual(len(d['items']), 2)
        kinds = [i['kind'] for i in d['items']]
        self.assertIn('concern', kinds)
        self.assertIn('relational', kinds)


# ============================================================
# K. 文本快照 print_snapshot 烟测
# ============================================================
class TestSnapshotSmoke(unittest.TestCase):
    def test_print_snapshot_no_exception(self):
        import io as _io
        import contextlib
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret = dashboard.print_snapshot()
        self.assertEqual(ret, 0)
        out = buf.getvalue()
        for tag in ('🎯', '💞', '📊', '📋', '🤝', '⚠️', '📜', '💡', '🔔', '🤖'):
            self.assertIn(tag, out)


# ============================================================
# L. 按钮操作 (subprocess) — 不真跑, 只测函数存在 + 异常吞掉
# ============================================================
class TestActionSubprocessAPI(unittest.TestCase):
    def test_action_cancel_commitment_exists(self):
        self.assertTrue(callable(dashboard.action_cancel_commitment))

    def test_action_reset_promise_log_exists(self):
        self.assertTrue(callable(dashboard.action_reset_promise_log))

    def test_action_open_review_cli_exists(self):
        self.assertTrue(callable(dashboard.action_open_review_cli))

    def test_action_open_latest_log_exists(self):
        self.assertTrue(callable(dashboard.action_open_latest_log))

    def _capture_subprocess_args(self, action_fn, *args):
        """通用: 跑 action 抓 subprocess.run 实际传入的 args."""
        from unittest.mock import patch as _patch
        import time as _time
        captured = {}

        def _fake_run(args_list, **kwargs):
            captured['args'] = args_list
            class _R:
                returncode = 0
                stdout = '✅ mock ok'
                stderr = ''
            return _R()

        done = {'ok': None, 'out': None}
        def _on_done(ok, out):
            done['ok'] = ok
            done['out'] = out

        with _patch('subprocess.run', side_effect=_fake_run):
            action_fn(*args, on_done=_on_done)
            for _ in range(30):
                if done['ok'] is not None:
                    break
                _time.sleep(0.05)
        return captured.get('args', []), done

    def test_cancel_commitment_arg(self):
        """🩹 BUG 防回归: --cancel 不是 --by-id"""
        args, done = self._capture_subprocess_args(
            dashboard.action_cancel_commitment, 42)
        self.assertTrue(done['ok'])
        self.assertIn('--cancel', args)
        self.assertIn('42', args)
        self.assertIn('scripts/commitment_cancel.py', args[1])

    def test_activate_relational_arg(self):
        """🩹 Sir 10:34 dashboard 直接 ✅ 通过 — relational"""
        args, done = self._capture_subprocess_args(
            dashboard.action_activate_review, 'relational', 'joke_xyz_123')
        self.assertTrue(done['ok'])
        self.assertIn('--activate', args)
        self.assertIn('joke_xyz_123', args)
        self.assertIn('scripts/relational_dump.py', args[1])

    def test_reject_relational_arg(self):
        """🩹 Sir 10:34 dashboard 直接 ❌ 拒绝 — relational"""
        args, done = self._capture_subprocess_args(
            dashboard.action_reject_review, 'relational', 'joke_xyz_123')
        self.assertTrue(done['ok'])
        self.assertIn('--reject', args)
        self.assertIn('joke_xyz_123', args)

    def test_activate_concern_arg(self):
        args, done = self._capture_subprocess_args(
            dashboard.action_activate_review, 'concern', 'sir_new_concern')
        self.assertTrue(done['ok'])
        self.assertIn('scripts/concerns_dump.py', args[1])
        self.assertIn('--activate', args)

    def test_unknown_kind_fails_gracefully(self):
        """未知 kind 应该 on_done(False, ...) 不抛"""
        from unittest.mock import patch as _patch
        import time as _time
        done = {'ok': None, 'out': None}
        def _on_done(ok, out):
            done['ok'] = ok
            done['out'] = out
        # 不需要 mock subprocess (kind 未知就 early-return)
        dashboard.action_activate_review('martian', 'x', on_done=_on_done)
        for _ in range(10):
            if done['ok'] is not None:
                break
            _time.sleep(0.05)
        self.assertEqual(done['ok'], False)
        self.assertIn('martian', done['out'])


# ============================================================
# M. 诊断字段 — Sir 10:23 反馈"还是看不懂"治本
# ============================================================
class TestDiagnosisFields(unittest.TestCase):
    """所有 reader 都必须返 diagnosis + suggestion 字段, 让 Sir 一眼看懂."""

    def test_concerns_has_diagnosis(self):
        with patch.object(dashboard, '_safe_read_json', return_value={}):
            d = dashboard.read_concerns()
        self.assertIn('diagnosis', d)
        self.assertIn('suggestion', d)
        self.assertTrue(d['diagnosis'])

    def test_concerns_critical_diagnosis_triggers(self):
        fake = {'sir_sleep_streak': {
            'state': 'active', 'severity': 0.95,
            'what_i_watch': 'late night', 'aligned_count': 5,
            'missed_count': 0, 'recent_signals': []}}
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_concerns()
        # severity 95% 应触发"准备主动催"诊断
        self.assertIn('紧迫度', d['diagnosis'])
        self.assertTrue('催' in d['diagnosis'] or '准备' in d['diagnosis'])

    def test_directive_offset_triggers_warning(self):
        now = time.time()
        fake = {
            f'd{i}': {'fired': 0, 'helped': 0, 'rejected': 0,
                      'last_triggered': 0, 'state': 'active'}
            for i in range(6)  # 6 条空转
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_directives()
        self.assertIn('跑偏', d['diagnosis'])
        self.assertIn('scripts/', d['suggestion'])

    def test_directive_all_healthy_diagnosis(self):
        now = time.time()
        fake = {
            'bilingual_directive': {
                'fired': 100, 'helped': 70, 'rejected': 0,
                'last_triggered': now - 60, 'state': 'active'},
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_directives()
        self.assertIn('健康', d['diagnosis'])

    def test_promise_untracked_warns(self):
        fake = {
            f'p{i}': {'id': f'p{i}', 'state': 'untracked', 'kind': 'soft',
                       'description': f'thing {i}', 'evidence': [],
                       'registered_at': time.time()}
            for i in range(5)
        }
        with patch.object(dashboard, '_safe_read_json', return_value=fake):
            d = dashboard.read_jarvis_promises()
        self.assertIn('言行不一', d['diagnosis'])

    def test_health_dead_key_warns(self):
        def fake(path, default=None):
            if 'key_router_state' in path:
                return {'k1': {'permanently_dead': True}}
            return default if default is not None else {}
        with patch.object(dashboard, '_safe_read_json', side_effect=fake):
            d = dashboard.read_system_health()
        self.assertIn('API key', d['diagnosis'])

    def test_review_queues_diagnosis(self):
        def fake(path, default=None):
            if 'concerns_review' in path:
                return [{'what_i_watch': 'c'} for _ in range(5)]
            return default if default is not None else {}
        with patch.object(dashboard, '_safe_read_json', side_effect=fake):
            d = dashboard.read_review_queues()
        self.assertIn('累积', d['diagnosis'])


# ============================================================
# N. 整体评估 compute_overall_status
# ============================================================
class TestOverallStatus(unittest.TestCase):
    def _empty_reader_output(self, **overrides):
        base = {
            'concerns': {'rows': [], 'review_n': 0},
            'directive': {'health': {}, 'total': 14, 'rows': []},
            'promise': {'untracked_n': 0, 'pending_n': 0, 'total': 0},
            'relation': {'jokes': [], 'protocols': [], 'unfinished': [], 'review_n': 0},
            'daemon': {'daemons': [{'id': 'ProactiveCare', 'live': True, 'zh': 'x', 'extra': ''}]},
            'health': {'key_router': {'dead_n': 0}, 'health_last': {'ws_mb': 2000}},
            'review': {'items': []},
            'events': {'events': []},
        }
        base.update(overrides)
        return base

    def test_all_healthy_ok_level(self):
        out = dashboard.compute_overall_status(**self._empty_reader_output())
        self.assertEqual(out['level'], 'ok')
        self.assertIn('健康', out['headline'])
        self.assertEqual(out['top_actions'], [])

    def test_critical_concern_promotes_warn(self):
        args = self._empty_reader_output(
            concerns={'rows': [{'zh_name': '睡眠', 'severity_pct': 90,
                                  'warn': '⚠️', 'aligned': 0, 'missed': 5,
                                  'last_sig': '1h前', 'last_trigger': 'never',
                                  'what': 'x', 'sig_n': 5, 'id': 's',
                                  'severity': 0.9}],
                       'review_n': 0})
        out = dashboard.compute_overall_status(**args)
        self.assertIn(out['level'], ('warn', 'crit'))
        self.assertTrue(out['top_actions'])
        self.assertIn('紧迫', out['top_actions'][0]['what'])

    def test_critical_daemon_offline_promotes_crit(self):
        args = self._empty_reader_output(
            daemon={'daemons': [
                {'id': 'ProactiveCare', 'live': False, 'zh': '主动关心', 'extra': ''},
                {'id': 'Inconsistency', 'live': False, 'zh': '言行反差', 'extra': ''},
            ]})
        out = dashboard.compute_overall_status(**args)
        self.assertEqual(out['level'], 'crit')
        self.assertIn('管家', out['top_actions'][0]['what'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
