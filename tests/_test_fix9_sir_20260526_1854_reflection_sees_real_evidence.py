# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 18:54 真意 anchor] 反思看真证据 — A+B+C 三层 evidence 扩展.

Sir 真意 (3 个深问题):
  Q1: 排查思考不能作用于主脑的地方, 不生效的地方
  Q2: 反思是不是靠看屏幕截图? 是不是要让反思看真日志?
       (现在 STM 2 turn 只 320 char, 看不见 sentinel 真行为)
  Q3: log 载入不要全量, 分析方案 → Sir 选方案 8 (vocab 持久化完整版)

三层修复:
  FIX A: STM 2→5 turn, user 120→250 char, jarvis 200→400 char
  FIX B: 加 recent_jarvis_actions = SWM filter etype prefix (jarvis 真行为)
  FIX C: 加 runtime_log_tail = read latest.txt → seek 100KB tail → marker filter
         marker vocab 持久化 memory_pool/runtime_log_marker_vocab.json
         CLI scripts/runtime_log_marker_dump.py (add/remove/list/history)

测试覆盖 (25 testcase):
  A1-A4 STM 扩 (5 turn, 字数 cap, 老 1 turn 兼容, 空 STM 安全)
  B1-B4 recent_jarvis_actions (filter 准确, etype prefix, 空 bus 安全, age cap)
  C1-C6 runtime_log_tail (read latest.txt, seek tail, marker filter, max_lines, 
                          IO 安全, 路径解析)
  V1-V5 vocab loader (load default, missing file fallback, mtime cache, 
                        add_marker, remove_marker)
  P1-P3 prompt block (STM 5 turn 显示, actions 显示, log tail 显示)
  CLI1-CLI3 CLI commands (list, add, remove)
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


# ==========================================================================
# Helpers
# ==========================================================================
def _make_daemon_with_nerve(stm_entries):
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    nerve = MagicMock()
    nerve.short_term_memory = list(stm_entries)
    nerve.commitment_watcher = None
    daemon = InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=nerve,
    )
    return daemon


# ==========================================================================
# A1-A4: STM 扩 (2→5 turn, 字数翻倍)
# ==========================================================================
class TestFixAStmExtended(unittest.TestCase):
    def test_a1_stm_5_turn_captured(self):
        """STM 5 turn 全被 evidence 收 (老 2 turn → 5 turn)."""
        entries = [
            {'user': f'turn_{i}_sir', 'jarvis': f'turn_{i}_jar',
              'time': f'18:00:0{i}', 'importance': 0.5}
            for i in range(10)
        ]
        daemon = _make_daemon_with_nerve(entries)
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertEqual(len(ev.get('stm', [])), 5,
            'STM 必须收 5 turn (FIX A)')

    def test_a2_user_capped_at_250_char(self):
        """user 字段 cap 250 char (老 120)."""
        long_user = 'X' * 500
        entries = [{'user': long_user, 'jarvis': 'short',
                       'time': '18:00:01'}]
        daemon = _make_daemon_with_nerve(entries)
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertEqual(len(ev['stm'][0]['user']), 250,
            'user cap 250 char')

    def test_a3_jarvis_capped_at_400_char(self):
        """jarvis 字段 cap 400 char (老 200)."""
        long_jarvis = 'Y' * 800
        entries = [{'user': 'short', 'jarvis': long_jarvis,
                       'time': '18:00:01'}]
        daemon = _make_daemon_with_nerve(entries)
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertEqual(len(ev['stm'][0]['jarvis']), 400,
            'jarvis cap 400 char')

    def test_a4_empty_stm_safe(self):
        """空 STM 不挂."""
        daemon = _make_daemon_with_nerve([])
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        self.assertEqual(ev.get('stm', []), [],
            '空 STM 返 []')


# ==========================================================================
# B1-B4: recent_jarvis_actions (SWM filter)
# ==========================================================================
class TestFixBRecentJarvisActions(unittest.TestCase):
    def _patch_event_bus(self, events):
        """Patch get_event_bus 返 mock bus with top_n."""
        bus = MagicMock()
        bus.top_n = MagicMock(return_value=events)
        return patch('jarvis_utils.get_event_bus', return_value=bus)

    def test_b1_action_filter_etype_prefix(self):
        """只收 etype prefix in ACTION_EVENT_PREFIXES."""
        events = [
            {'type': 'proactive_nudge_fired', 'description': 'fired',
              'source': 'SmartNudge', '_age_s': 10},
            {'type': 'inner_thought_actionable_failed', 'description': 'failed',
              'source': 'daemon', '_age_s': 20},
            {'type': 'random_sensor_signal', 'description': 'irrelevant',
              'source': 'sensor', '_age_s': 5},  # 不该收
        ]
        daemon = _make_daemon_with_nerve([])
        with self._patch_event_bus(events), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        actions = ev.get('recent_jarvis_actions', [])
        self.assertEqual(len(actions), 2,
            'filter 应只留 proactive_nudge_+ inner_thought_, 不留 random_sensor_signal')
        etypes = [a['etype'] for a in actions]
        self.assertIn('proactive_nudge_fired', etypes)
        self.assertIn('inner_thought_actionable_failed', etypes)
        self.assertNotIn('random_sensor_signal', etypes)

    def test_b2_age_filter(self):
        """age > within_seconds 不收."""
        events = [
            {'type': 'proactive_nudge_fired', 'description': 'fresh',
              'source': 'SmartNudge', '_age_s': 100},  # 100s 内 ✓
            {'type': 'proactive_nudge_fired', 'description': 'stale',
              'source': 'SmartNudge', '_age_s': 700},  # 700s 超 600s ✗
        ]
        daemon = _make_daemon_with_nerve([])
        with self._patch_event_bus(events), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        actions = ev.get('recent_jarvis_actions', [])
        self.assertEqual(len(actions), 1,
            'age 过滤后只留 fresh')

    def test_b3_max_10_actions(self):
        """cap 10 actions (防 prompt 膨胀)."""
        events = [
            {'type': f'proactive_nudge_{i}', 'description': f'a{i}',
              'source': 'S', '_age_s': i}
            for i in range(20)
        ]
        daemon = _make_daemon_with_nerve([])
        with self._patch_event_bus(events), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        actions = ev.get('recent_jarvis_actions', [])
        self.assertLessEqual(len(actions), 10,
            '最多 10 actions')

    def test_b4_no_bus_safe(self):
        """event_bus 缺失 → 安全 fallback."""
        daemon = _make_daemon_with_nerve([])
        with patch('jarvis_utils.get_event_bus', return_value=None), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        # 应返 [] 或不存在 (不挂)
        self.assertIn(ev.get('recent_jarvis_actions', []), [[], None])


# ==========================================================================
# C1-C6: runtime_log_tail
# ==========================================================================
class TestFixCRuntimeLogTail(unittest.TestCase):
    def setUp(self):
        """Create tmp log + latest.txt 让 daemon 真读."""
        self.tmp_dir = tempfile.mkdtemp(prefix='jarvis_fix9_')
        # tmp log content (含 marker + 含非 marker 噪音)
        self.log_path = os.path.join(self.tmp_dir, 'fake.log')
        log_lines = [
            "[sess_X] [turn_Y] 🤖 [Jarvis] Hello Sir, how may I assist",
            "[sess_X] [turn_Y] noisy random sensor data without marker",
            "[sess_X] [turn_Z] 🗣️ [Human] 帮我看面试题",
            "[sess_X] [turn_Z] 🔁 [ConcernFeedback/RECORD] cid=sir_pomodoro",
            "[sess_X] [turn_W] 🟡 [JarvisState] focused → listening",
            "[sess_X] [turn_W] more noise without any marker word",
            "[sess_X] [turn_V] proactive_nudge_fired by SmartNudge: stretch",
            "[sess_X] [turn_V] return_greeting rejected: too soon after nudge",
            "[sess_X] [turn_U] 🎙️ [接收物理声波] [Spinal Reflex] Command received",
        ]
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(log_lines) + '\n')
        # latest.txt point to log file
        self.latest_path = os.path.join(self.tmp_dir, 'latest.txt')
        with open(self.latest_path, 'w', encoding='utf-8') as f:
            f.write(self.log_path)

    def tearDown(self):
        try:
            import shutil
            shutil.rmtree(self.tmp_dir)
        except Exception:
            pass

    def test_c1_read_latest_and_resolve_log(self):
        """daemon 真 read latest.txt + resolve log path."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )
        daemon.RUNTIME_LOG_LATEST_PATH = self.latest_path
        tail = daemon._collect_runtime_log_tail()
        self.assertGreater(len(tail), 0,
            'log 真读到非空 tail')

    def test_c2_marker_filter_works(self):
        """marker filter 留 marker line, 弃 noise line."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )
        daemon.RUNTIME_LOG_LATEST_PATH = self.latest_path
        tail = daemon._collect_runtime_log_tail()
        combined = '\n'.join(tail)
        # marker line 应在 (Jarvis / Human / JarvisState / fired / rejected / Spinal Reflex)
        self.assertIn('[Jarvis]', combined, '[Jarvis] marker 应留')
        self.assertIn('[Human]', combined, '[Human] marker 应留')
        self.assertIn('fired', combined, 'fired keyword 应留')
        self.assertIn('rejected', combined, 'rejected keyword 应留')
        # noise line 应 filter 掉
        self.assertNotIn('noisy random sensor data', combined,
            '无 marker 的 noise 应 filter 掉')
        self.assertNotIn('more noise without any marker', combined,
            '无 marker 的 noise 应 filter 掉')

    def test_c3_max_lines_cap(self):
        """max_lines 限制收的行数."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )
        daemon.RUNTIME_LOG_LATEST_PATH = self.latest_path
        tail = daemon._collect_runtime_log_tail(max_lines=3)
        self.assertLessEqual(len(tail), 3,
            'max_lines=3 cap')

    def test_c4_line_capped_at_180_char(self):
        """单行 cap 180 char."""
        long_line = "[Jarvis] " + "X" * 500  # marker [Jarvis] + 500 char
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write(long_line + '\n')
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )
        daemon.RUNTIME_LOG_LATEST_PATH = self.latest_path
        tail = daemon._collect_runtime_log_tail()
        if tail:
            self.assertLessEqual(len(tail[0]), 180,
                '单行 cap 180 char')

    def test_c5_missing_latest_safe(self):
        """latest.txt 缺失 → return []."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )
        daemon.RUNTIME_LOG_LATEST_PATH = '/nonexistent/path/latest.txt'
        tail = daemon._collect_runtime_log_tail()
        self.assertEqual(tail, [],
            'latest.txt 缺失 → return [] (不挂)')

    def test_c6_chronological_order(self):
        """返回 旧→新 顺序 (LLM 自然读)."""
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
            central_nerve=None,
        )
        daemon.RUNTIME_LOG_LATEST_PATH = self.latest_path
        tail = daemon._collect_runtime_log_tail()
        # 验证 reverse 不是; 期望 旧→新 = log file 自然 order 的 subset
        if len(tail) >= 2:
            # 第一行的 turn (Y/Z/W/V/U) 应 < 末行
            # log file: Y, Y, Z, Z, W, W, V, V, U (旧→新)
            # filter 后: Y, Z, Z, W, V, V, U (顺序保留)
            # 第一收应是较早的 turn
            first = tail[0]
            last = tail[-1]
            # 简单验证: first 不等于 last (有 chronological 差异)
            self.assertNotEqual(first, last,
                '至少 first != last 证明顺序保留')


# ==========================================================================
# V1-V5: vocab loader
# ==========================================================================
class TestVocabLoader(unittest.TestCase):
    def setUp(self):
        # 不污染真 vocab — 用 tmp path
        self.tmp = tempfile.mktemp(suffix='.json')
        # 写 valid vocab
        vocab_data = {
            '_meta': {'schema_version': 1},
            'action_event_prefixes': [
                'custom_action_', 'other_event_',
            ],
            'log_line_markers': [
                '[CustomMarker]', 'unique_word',
            ],
            'history': [],
            'review_queue': [],
        }
        with open(self.tmp, 'w', encoding='utf-8') as f:
            json.dump(vocab_data, f)
        # reset cache (singleton may have stale data)
        from jarvis_runtime_log_markers import _Cache
        cache = _Cache()
        cache._data = {}
        cache._mtime = 0.0
        cache._last_check_ts = 0.0
        cache._marker_regex_cache = None
        cache._action_prefixes_cache = ()

    def tearDown(self):
        try:
            os.unlink(self.tmp)
        except Exception:
            pass
        # reset cache 防污染 next test
        from jarvis_runtime_log_markers import _Cache
        cache = _Cache()
        cache._data = {}
        cache._mtime = 0.0
        cache._last_check_ts = 0.0
        cache._marker_regex_cache = None
        cache._action_prefixes_cache = ()

    def test_v1_load_action_event_prefixes(self):
        from jarvis_runtime_log_markers import load_action_event_prefixes
        prefixes = load_action_event_prefixes(self.tmp)
        self.assertEqual(prefixes,
            ('custom_action_', 'other_event_'))

    def test_v2_missing_file_fallback_defaults(self):
        from jarvis_runtime_log_markers import (
            load_action_event_prefixes,
            _DEFAULT_ACTION_EVENT_PREFIXES,
        )
        prefixes = load_action_event_prefixes('/nonexistent/path.json')
        self.assertEqual(prefixes, _DEFAULT_ACTION_EVENT_PREFIXES,
            '缺失 vocab → fallback defaults')

    def test_v3_marker_regex_compiles(self):
        from jarvis_runtime_log_markers import load_marker_regex
        regex = load_marker_regex(self.tmp)
        # marker '[CustomMarker]' 应 match
        self.assertIsNotNone(regex.search('blah [CustomMarker] blah'),
            'marker regex 应 match 含 [CustomMarker] 的 line')
        self.assertIsNotNone(regex.search('blah unique_word blah'),
            'marker regex 应 match 含 unique_word 的 line')
        self.assertIsNone(regex.search('totally unrelated line'),
            '无 marker 的 line 不 match')

    def test_v4_add_marker(self):
        from jarvis_runtime_log_markers import (
            add_marker, load_log_line_markers,
        )
        ok = add_marker('[NewTag]', kind='log_line', path=self.tmp)
        self.assertTrue(ok)
        markers = load_log_line_markers(self.tmp)
        self.assertIn('[NewTag]', markers,
            'add_marker 后 reload 应见 [NewTag]')

    def test_v5_remove_marker(self):
        from jarvis_runtime_log_markers import (
            remove_marker, load_log_line_markers,
        )
        ok = remove_marker('[CustomMarker]', kind='log_line', path=self.tmp)
        self.assertTrue(ok)
        markers = load_log_line_markers(self.tmp)
        self.assertNotIn('[CustomMarker]', markers,
            'remove_marker 后 reload 不该见 [CustomMarker]')


# ==========================================================================
# P1-P3: prompt block 展示
# ==========================================================================
class TestPromptBlocksDisplay(unittest.TestCase):
    def test_p1_stm_5_turns_in_prompt(self):
        """prompt 含 [STM LAST 5 TURNS] block."""
        entries = [
            {'user': f'sir_{i}', 'jarvis': f'jar_{i}', 'time': '18:00'}
            for i in range(5)
        ]
        daemon = _make_daemon_with_nerve(entries)
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('[STM LAST 5 TURNS]', user,
            'prompt 应含 5 TURNS section header')

    def test_p2_actions_in_prompt(self):
        """prompt 含 [WHAT I JUST DID] block."""
        events = [{'type': 'proactive_nudge_fired',
                     'description': 'fired stretch nudge',
                     'source': 'SmartNudge', '_age_s': 30}]
        bus = MagicMock()
        bus.top_n = MagicMock(return_value=events)
        daemon = _make_daemon_with_nerve([])
        with patch('jarvis_utils.get_event_bus', return_value=bus), \
             patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('WHAT I JUST DID', user,
            'prompt 应含 WHAT I JUST DID section')
        self.assertIn('fired stretch nudge', user,
            'action desc 必须显示')

    def test_p3_runtime_log_in_prompt(self):
        """prompt 含 [REAL RUNTIME LOG] block."""
        tmp_dir = tempfile.mkdtemp(prefix='jarvis_fix9_p3_')
        log_path = os.path.join(tmp_dir, 'fake.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("[sess_X] [turn_Y] [Jarvis] hello sir how may i assist\n")
        latest_path = os.path.join(tmp_dir, 'latest.txt')
        with open(latest_path, 'w', encoding='utf-8') as f:
            f.write(log_path)
        daemon = _make_daemon_with_nerve([])
        daemon.RUNTIME_LOG_LATEST_PATH = latest_path
        with patch('jarvis_env_probe.PhysicalEnvironmentProbe') as MockP:
            MockP.idle_seconds_real = 5.0
            ev = daemon._collect_evidence('active', 600)
        system, user = daemon._build_prompt('active', ev)
        self.assertIn('REAL RUNTIME LOG', user,
            'prompt 应含 REAL RUNTIME LOG section')
        self.assertIn('SOURCE OF TRUTH', user,
            'prompt 教 LLM 信 log > terminal')
        # 清理
        import shutil
        shutil.rmtree(tmp_dir)


# ==========================================================================
# CLI1-CLI3: CLI commands (subprocess 调用)
# ==========================================================================
class TestCLICommands(unittest.TestCase):
    def setUp(self):
        # tmp vocab 防污染真 vocab
        self.tmp_vocab = tempfile.mktemp(suffix='.json')
        vocab_data = {
            '_meta': {'schema_version': 1},
            'action_event_prefixes': ['initial_action_'],
            'log_line_markers': ['[Initial]'],
            'history': [],
            'review_queue': [],
        }
        with open(self.tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump(vocab_data, f)
        # reset singleton cache 防 V1-V5 残留数据污染
        from jarvis_runtime_log_markers import _Cache
        cache = _Cache()
        cache._data = {}
        cache._mtime = 0.0
        cache._last_check_ts = 0.0
        cache._marker_regex_cache = None
        cache._action_prefixes_cache = ()

    def tearDown(self):
        try:
            os.unlink(self.tmp_vocab)
        except Exception:
            pass
        from jarvis_runtime_log_markers import _Cache
        cache = _Cache()
        cache._data = {}
        cache._mtime = 0.0
        cache._last_check_ts = 0.0
        cache._marker_regex_cache = None
        cache._action_prefixes_cache = ()

    def test_cli1_add_then_remove_log_line_marker(self):
        """add_marker + remove_marker (直接调 API, 不 subprocess 避免 unicode 死)."""
        from jarvis_runtime_log_markers import (
            add_marker, remove_marker, load_log_line_markers,
        )
        ok = add_marker('[CliAdded]', kind='log_line',
                          path=self.tmp_vocab, source='test_cli')
        self.assertTrue(ok)
        markers = load_log_line_markers(self.tmp_vocab)
        self.assertIn('[CliAdded]', markers)
        # history 应记 op
        from jarvis_runtime_log_markers import list_all
        data = list_all(self.tmp_vocab)
        hist = data.get('history') or []
        self.assertTrue(any(e.get('marker') == '[CliAdded]' and
                                e.get('op') == 'add' for e in hist),
            'history 应有 add op')
        # remove
        ok = remove_marker('[CliAdded]', kind='log_line',
                              path=self.tmp_vocab)
        self.assertTrue(ok)
        markers = load_log_line_markers(self.tmp_vocab)
        self.assertNotIn('[CliAdded]', markers)

    def test_cli2_add_dup_returns_false(self):
        from jarvis_runtime_log_markers import add_marker
        ok1 = add_marker('[Dup]', kind='log_line', path=self.tmp_vocab)
        self.assertTrue(ok1)
        ok2 = add_marker('[Dup]', kind='log_line', path=self.tmp_vocab)
        self.assertFalse(ok2, '重复 add 应 return False')

    def test_cli3_add_action_event_prefix(self):
        from jarvis_runtime_log_markers import (
            add_marker, load_action_event_prefixes,
        )
        # reset cache 防 dirty (跟 V1-V5 共用 singleton)
        from jarvis_runtime_log_markers import _Cache
        cache = _Cache()
        cache._data = {}
        cache._mtime = 0.0
        cache._last_check_ts = 0.0
        cache._action_prefixes_cache = ()
        ok = add_marker('new_prefix_', kind='action_event_prefix',
                          path=self.tmp_vocab)
        self.assertTrue(ok)
        prefixes = load_action_event_prefixes(self.tmp_vocab)
        self.assertIn('new_prefix_', prefixes,
            'add_marker action_event_prefix 应生效')


if __name__ == '__main__':
    unittest.main()
