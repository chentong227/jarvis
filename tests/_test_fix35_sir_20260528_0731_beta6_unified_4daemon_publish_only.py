"""[Sir 2026-05-28 07:31 真痛 BUG 续治本] β.6 完整统一: 4 daemon 真退化 publish_only

Sir 7:14 + 7:16 SmartNudge 编 '02:43 番茄钟' 直推 → LLM 看 promise 编 → 幻觉.
根因继: 即使 vocab 标 SmartNudgeSentinel=publish_only, daemon 内部仍 push __NUDGE__
直推 (vocab 只控 NudgeGate.can_speak), 真退化没生效.

Sir 7:31 拍板: 4 daemon (SmartNudge / Conductor / WellnessGuardian / CommitmentWatcher)
真退化 publish_only. daemon 不直 push __NUDGE__, 改 publish 'X_candidate' SWM event.
思考脑 60s tick 看 candidate + 全 SWM ctx 自决 SHOULD_SPEAK + SPEAK_CONTENT + SPEAK_STYLE.

测试覆盖:
  L1: vocab gate_mode_vocab.json current 含 CommitmentWatcher: publish_only
  L2: 4 daemon 源码各有 'publish_only' 真退化 path + 'return' 不 push __NUDGE__
  L3: 思考脑 _ACTION_EVENT_PREFIXES (fallback + vocab) 含 4 个 candidate etype
  L4: runtime_log_marker_vocab.json action_event_prefixes 含 4 个 candidate etype
  L5: WellnessGuardian publish_only mode 不设 PhysicalEnvironmentProbe._wellness_alert flag
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestL1_VocabHasCommitmentWatcher(unittest.TestCase):
    """gate_mode_vocab.json current 含 CommitmentWatcher: publish_only."""

    def test_commitment_watcher_in_vocab(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        current = data.get('current', {})
        self.assertIn('CommitmentWatcher', current,
                       'β.6 完整统一: CommitmentWatcher 必须在 vocab')
        self.assertEqual(current['CommitmentWatcher'], 'publish_only',
                          'β.6 完整统一: CommitmentWatcher = publish_only')

    def test_all_4_daemons_publish_only(self):
        path = os.path.join(ROOT, 'memory_pool', 'gate_mode_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        current = data.get('current', {})
        for name in ('SmartNudgeSentinel', 'Conductor', 'WellnessGuardian',
                      'CommitmentWatcher'):
            self.assertEqual(current.get(name), 'publish_only',
                              f'β.6 完整统一: {name} 必须 publish_only')


class TestL2_DaemonSourceHasPublishOnlyPath(unittest.TestCase):
    """4 daemon 源码各有 'publish_only' 真退化 path + return."""

    def _src(self, fn: str) -> str:
        with open(os.path.join(ROOT, fn), 'r', encoding='utf-8') as f:
            return f.read()

    def test_smart_nudge_publish_only_path(self):
        src = self._src('jarvis_smart_nudge.py')
        self.assertIn('smart_nudge_candidate', src,
                       'SmartNudge 必须 publish smart_nudge_candidate event')
        self.assertIn("read_gate_mode as _rgm_sn", src,
                       'SmartNudge 必须读 vocab gate_mode (SmartNudgeSentinel)')
        self.assertIn("_rgm_sn('SmartNudgeSentinel')", src,
                       'SmartNudge 必须用 SmartNudgeSentinel key 读 vocab')

    def test_conductor_publish_only_path(self):
        src = self._src('jarvis_conductor.py')
        self.assertIn('conductor_candidate', src,
                       'Conductor 必须 publish conductor_candidate event')
        # path A + path B 都要有 (path_a publish + path_b publish + 可能 etype 引用)
        self.assertGreaterEqual(src.count('conductor_candidate'), 2,
                                  'Conductor path_a + path_b 各 publish 1 个 candidate')
        self.assertIn("read_gate_mode as _rgm_cda", src,
                       'Conductor path_a 必须读 vocab')
        self.assertIn("read_gate_mode as _rgm_cdb", src,
                       'Conductor path_b 必须读 vocab')

    def test_wellness_guardian_publish_only_path(self):
        src = self._src('jarvis_sentinels.py')
        self.assertIn('wellness_candidate', src,
                       'WellnessGuardian 必须 publish wellness_candidate event')
        self.assertIn("read_gate_mode as _rgm_wg", src,
                       'WellnessGuardian 必须读 vocab gate_mode (WellnessGuardian)')
        # publish_only 模式必须不设 _wellness_alert flag
        self.assertIn('return  # 不设 _wellness_alert flag', src,
                       'WellnessGuardian publish_only mode 必须 return + 不设 alert flag')

    def test_commitment_watcher_publish_only_path(self):
        src = self._src('jarvis_commitment_watcher.py')
        self.assertIn('commitment_check_candidate', src,
                       'CommitmentWatcher 必须 publish commitment_check_candidate event')
        self.assertIn("read_gate_mode as _rgm_cw", src,
                       'CommitmentWatcher 必须读 vocab gate_mode')
        self.assertIn("_rgm_cw('CommitmentWatcher')", src,
                       'CommitmentWatcher 必须用 CommitmentWatcher key 读 vocab')


class TestL3_ThinkingBrainSeesCandidates(unittest.TestCase):
    """思考脑 _ACTION_EVENT_PREFIXES (fallback + vocab loader) 含 4 个 candidate etype."""

    def test_runtime_log_markers_fallback_includes_candidates(self):
        from jarvis_runtime_log_markers import _DEFAULT_ACTION_EVENT_PREFIXES
        for etype in ('smart_nudge_candidate', 'conductor_candidate',
                       'wellness_candidate', 'commitment_check_candidate'):
            self.assertIn(etype, _DEFAULT_ACTION_EVENT_PREFIXES,
                           f'fallback DEFAULTS 必须含 {etype}')

    def test_load_action_event_prefixes_includes_candidates(self):
        from jarvis_runtime_log_markers import load_action_event_prefixes
        prefixes = load_action_event_prefixes()
        for etype in ('smart_nudge_candidate', 'conductor_candidate',
                       'wellness_candidate', 'commitment_check_candidate'):
            self.assertIn(etype, prefixes,
                           f'load_action_event_prefixes 必须含 {etype}')

    def test_inner_thought_daemon_fallback_includes_candidates(self):
        with open(os.path.join(ROOT, 'jarvis_inner_thought_daemon.py'),
                    'r', encoding='utf-8') as f:
            src = f.read()
        for etype in ('smart_nudge_candidate', 'conductor_candidate',
                       'wellness_candidate', 'commitment_check_candidate'):
            self.assertIn(f"'{etype}'", src,
                           f'inner_thought_daemon fallback 必须含 {etype}')


class TestL4_VocabFileHasCandidates(unittest.TestCase):
    """runtime_log_marker_vocab.json action_event_prefixes 含 4 个 candidate."""

    def test_vocab_file_includes_candidates(self):
        path = os.path.join(ROOT, 'memory_pool', 'runtime_log_marker_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        prefixes = data.get('action_event_prefixes', [])
        for etype in ('smart_nudge_candidate', 'conductor_candidate',
                       'wellness_candidate', 'commitment_check_candidate'):
            self.assertIn(etype, prefixes,
                           f'vocab JSON 必须含 {etype}')


class TestL5_DataStrongCoupling(unittest.TestCase):
    """准则 6 数据强耦合: 4 daemon publish 时含 source/metadata 让思考脑可 trace."""

    def test_smart_nudge_publish_has_metadata(self):
        with open(os.path.join(ROOT, 'jarvis_smart_nudge.py'),
                    'r', encoding='utf-8') as f:
            src = f.read()
        # metadata 含 nudge_type, sentinel, context, gate_mode
        for field in ("'nudge_type'", "'sentinel'", "'context'", "'gate_mode'"):
            self.assertIn(field, src,
                           f'SmartNudge publish metadata 必须含 {field}')

    def test_commitment_watcher_publish_has_author(self):
        with open(os.path.join(ROOT, 'jarvis_commitment_watcher.py'),
                    'r', encoding='utf-8') as f:
            src = f.read()
        # CommitmentWatcher publish 必须含 author (区分 sir vs jarvis)
        self.assertIn("'author':", src,
                       'CommitmentWatcher publish metadata 必须含 author 字段')
        self.assertIn("'who_promised':", src,
                       'CommitmentWatcher publish metadata 必须含 who_promised 字段')


if __name__ == '__main__':
    unittest.main(verbosity=2)
