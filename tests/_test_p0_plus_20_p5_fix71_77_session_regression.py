# -*- coding: utf-8 -*-
"""[P5-fix71~77 / 2026-05-23] 今晚 session 综合回归 test.

覆盖 commit:
  d10acd9 P5-fix71 hydration unit directive
  c399dba P5-fix72 reminder_acknowledged event + guards
  b773d92 P5-fix73 batch (J progress.set / L ClaimTracer nudge / H/I ZH truncate / N KeyRouter leak)
  fa53310 P5-fix74 (J unit strict + O wrap-up honest)
  ed51e97 P5-fix75 (G ProactiveCare ack guard)
  26ddaf6 P5-fix76 (P time field disambiguation)
  807668f P5-fix77 batch (Q alias / I max_tokens / integ exclude / R SWM events / concern prompt)

测试策略: 静态 source 校验 + 关键 method 行为 mock.
不测真 LLM call / 真 stream / 真 TTS (那些需 Sir 实测).
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _read(p: str) -> str:
    with open(ROOT / p, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================
# fix71 — BUG-E hydration unit directive
# ============================================================
class TestFix71HydrationUnitDirective(unittest.TestCase):

    def test_71_ambiguous_unit_handling_directive_exists(self):
        src = _read('jarvis_directives.py')
        self.assertIn('ambiguous_unit_handling', src,
                      'fix71: ambiguous_unit_handling directive 应注册')

    def test_71_unit_conversion_priority_hint(self):
        src = _read('jarvis_directives.py')
        # 主动问 cup_ml / 单位
        self.assertTrue(
            'cup_ml' in src or '杯' in src,
            'fix71: directive 应引导主脑问杯子容量 (cup_ml / 杯)'
        )


# ============================================================
# fix72 — BUG-F/G reminder_acknowledged + sentinel guards
# ============================================================
class TestFix72ReminderAckEvent(unittest.TestCase):

    def test_72_sentinels_publish_reminder_acknowledged(self):
        src = _read('jarvis_sentinels.py')
        self.assertIn('reminder_acknowledged', src,
                      'fix72: sentinels 应 publish reminder_acknowledged event')

    def test_72_smart_nudge_guard_checks_ack(self):
        src = _read('jarvis_smart_nudge.py')
        self.assertIn('reminder_acknowledged', src,
                      'fix72: smart_nudge 应有 reminder_acknowledged guard')

    def test_72_commitment_watcher_guard(self):
        src = _read('jarvis_commitment_watcher.py')
        self.assertIn('reminder_acknowledged', src,
                      'fix72: commitment_watcher 应有 reminder_acknowledged guard')


# ============================================================
# fix73 — batch BUG-J/L/H/I/N
# ============================================================
class TestFix73ProgressSetAbsolute(unittest.TestCase):
    """BUG-J: progress.set absolute value command"""

    def test_73j_set_absolute_method_exists(self):
        from jarvis_progress_tracker import ProgressTrackerStore
        self.assertTrue(hasattr(ProgressTrackerStore, 'set_absolute'),
                         'fix73-J: ProgressTrackerStore.set_absolute method 应存在')

    def test_73j_dispatcher_handles_set_command(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn("command == 'set'", src,
                      'fix73-J: chat_bypass progress dispatcher 应支持 set command')

    def test_73j_directive_teaches_set_vs_update(self):
        src = _read('jarvis_directives.py')
        # directive 用 JSON 格式 "command":"set" 不是 "progress.set" 字面
        self.assertIn('"command":"set"', src,
                      'fix73-J: directive 应教 set 命令 (JSON FAST_CALL 格式)')
        # update vs set 选择规则
        self.assertTrue(
            '搞错了' in src or '总共' in src or 'set new_current' in src,
            'fix73-J: directive 应有 update vs set 选择规则'
        )


class TestFix73ClaimTracerOnNudge(unittest.TestCase):
    """BUG-L: ClaimTracer trace at stream_nudge end"""

    def test_73l_nudge_calls_trace_reply(self):
        src = _read('jarvis_chat_bypass.py')
        # stream_nudge 末尾应调 trace_reply
        nudge_section = re.search(
            r'def stream_nudge.*?(?=def |\Z)', src, re.DOTALL
        )
        self.assertIsNotNone(nudge_section, '应有 stream_nudge method')
        self.assertIn('trace_reply', nudge_section.group(0),
                      'fix73-L: stream_nudge 末尾应调 trace_reply 抓幻觉')


class TestFix73BilingualTruncated(unittest.TestCase):
    """BUG-H/I: ZH translation truncate detection"""

    def test_73hi_bilingual_truncated_log(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Bilingual/Truncated', src,
                      'fix73-H/I: 应 bg_log Bilingual/Truncated warning')

    def test_73hi_publishes_swm_event(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('bilingual_truncated', src,
                      'fix73-H/I: 应 publish bilingual_truncated SWM event')


class TestFix73KeyRouterLeak(unittest.TestCase):
    """BUG-N: KeyRouter resource leak fix"""

    def test_73n_wrapper_no_longer_releases_key(self):
        src = _read('jarvis_utils.py')
        # safe_openrouter_call 文档说 caller 责任
        self.assertIn('caller 责任', src,
                      'fix73-N: safe_openrouter_call doc 应说 caller 责任 release')

    def test_73n_callers_use_try_finally(self):
        # stm_summarizer / struggle_reflector / watch_task 应有 try/finally release
        for fname in ('jarvis_stm_summarizer.py', 'jarvis_struggle_reflector.py',
                       'jarvis_watch_task.py'):
            src = _read(fname)
            self.assertIn('key_router.release', src,
                          f'fix73-N: {fname} 应有 key_router.release 调用')


# ============================================================
# fix74 — BUG-J unit strict + BUG-O wrap-up honest
# ============================================================
class TestFix74UnitConversionStrict(unittest.TestCase):

    def test_74j_directive_warns_raw_count_as_ml(self):
        src = _read('jarvis_directives.py')
        # Sir 18:36 真测痛点 case 应作为反例
        self.assertTrue(
            '18:36' in src or 'raw 杯数' in src or '4900' in src,
            'fix74-J: directive 应含 Sir 18:36 raw 杯数当 ml 反例'
        )


class TestFix74WrapupHonest(unittest.TestCase):

    def test_74o_wrapup_no_fabricated_done(self):
        src = _read('jarvis_chat_bypass.py')
        # 新模板不再用"already completed on the first call"
        # 而是诚实问 Sir 换角度
        # 至少应出现 "different angle" 或 "more context"
        self.assertTrue(
            'different angle' in src or 'more context' in src or '换个切入点' in src,
            'fix74-O: duplicate_call+last_ok 路径应诚实 not fabricate "completed"'
        )


# ============================================================
# fix75 — BUG-G ProactiveCare ack guard
# ============================================================
class TestFix75ProactiveCareAckGuard(unittest.TestCase):

    def test_75g_proactive_care_checks_reminder_ack(self):
        src = _read('jarvis_proactive_care.py')
        self.assertIn('reminder_acknowledged', src,
                      'fix75-G: ProactiveCare 应有 reminder_acknowledged guard')

    def test_75g_break_concern_keywords_listed(self):
        src = _read('jarvis_proactive_care.py')
        # 至少应识别 break/rest/stretch/stand 类 concern
        for kw in ('break', 'stretch', 'stand'):
            self.assertIn(kw, src, f'fix75-G: 应识别 {kw} 类 concern')


# ============================================================
# fix76 — BUG-P ProactiveCare time field disambiguation
# ============================================================
class TestFix76TimeFieldDisambiguation(unittest.TestCase):

    def test_76p_snapshot_includes_window_stay(self):
        src = _read('jarvis_proactive_care.py')
        self.assertIn('current_window_stay_seconds', src,
                      'fix76-P: _snapshot_current_activity 应含 current_window_stay_seconds')

    def test_76p_disambiguates_two_time_fields(self):
        src = _read('jarvis_proactive_care.py')
        # snapshot 应同时返 session total + current window stay
        self.assertTrue(
            'session total' in src and 'current window' in src,
            'fix76-P: snapshot 应同时给 session_total + current_window 两字段'
        )

    def test_76p_directive_teaches_distinction(self):
        src = _read('jarvis_proactive_care.py')
        self.assertIn('NEVER conflate', src,
                      'fix76-P: directive 应教主脑不混淆 2 时间字段')


# ============================================================
# fix77 — batch (Q/I/integ/R/concern)
# ============================================================
class TestFix77QFuzzyAlias(unittest.TestCase):
    """BUG-Q: chat_bypass fuzzy organ alias (memory → memory_hands)"""

    def test_77q_alias_resolve_in_path_a(self):
        src = _read('jarvis_chat_bypass.py')
        # 应 try organ_name + '_hands'
        self.assertIn("organ_name + '_hands'", src,
                      'fix77-Q: 应有 organ_name + "_hands" fallback')

    def test_77q_alias_resolve_log(self):
        src = _read('jarvis_chat_bypass.py')
        self.assertIn('Alias Resolve', src,
                      'fix77-Q: alias 解析应 bg_log')


class TestFix77IntegrityCheckExclude(unittest.TestCase):
    """integ: integrity check 排除 single_step_fast_path"""

    def test_77integ_excludes_success_fast_path(self):
        src = _read('jarvis_worker.py')
        self.assertIn('_is_success_fast_path', src,
                      'fix77-integ: 应有 _is_success_fast_path 标志')
        self.assertIn("== 'single_step_fast_path'", src,
                      'fix77-integ: 应对比 single_step_fast_path 字符串')


class TestFix77RClaimTracerSWMMutation(unittest.TestCase):
    """BUG-R: ClaimTracer cross-module SWM mutation evidence"""

    def test_77r_fetch_swm_includes_mutation_types(self):
        src = _read('jarvis_claim_tracer.py')
        for etype in ('memory_corrected', 'sir_field_updated'):
            self.assertIn(etype, src,
                          f'fix77-R: _fetch_swm_tool_results 应拿 {etype} events')

    def test_77r_mutation_event_to_check_evidence(self):
        src = _read('jarvis_claim_tracer.py')
        # mutation event 应 emit ✅ marker (与 past_action vocab 兼容)
        # 等 mutation event 处理片段 包含 ✅
        # 找 "✅ {etype}(" 字面
        self.assertIn('f"✅ {etype}(', src,
                      'fix77-R: mutation event 应 emit ✅ marker for trace')


class TestFix77ConcernFeedbackPrompt(unittest.TestCase):
    """concern: ConcernFeedback LLM prompt 严格规则"""

    def test_77concern_prompt_warns_topic_overlap(self):
        src = _read('jarvis_concern_feedback.py')
        self.assertIn('话题不重叠', src,
                      'fix77-concern: prompt 应教 LLM 话题不重叠 → has_relevance=false')

    def test_77concern_prompt_example_refactor_vs_jiazhao(self):
        src = _read('jarvis_concern_feedback.py')
        self.assertTrue(
            '重构' in src and ('驾照' in src or 'jiazhao' in src),
            'fix77-concern: prompt 应含 Sir 19:08 重构 vs 驾照真案例'
        )


class TestFix77IStreamMaxTokens(unittest.TestCase):
    """BUG-I: stream truncate fix"""

    def test_77i_create_stream_sets_max_tokens(self):
        src = _read('jarvis_chat_bypass.py')
        # _create_stream 应传 max_tokens=8192
        self.assertIn('max_tokens=8192', src,
                      'fix77-I: stream create 应设 max_tokens=8192 防 SDK 短 default')

    def test_77i_read_timeout_increased(self):
        src = _read('jarvis_chat_bypass.py')
        # read timeout 应 25.0 (从 12.0 提)
        self.assertIn('read=25.0', src,
                      'fix77-I: read timeout 应提到 25s 给主脑 reasoning 时间')


# ============================================================
# 行为 (非静态) test — 用 mock 真路径
# ============================================================
class TestFix73SetAbsoluteBehavior(unittest.TestCase):
    """fix73-J: ProgressTrackerStore.set_absolute 行为"""

    def test_set_absolute_overrides_current(self):
        from jarvis_progress_tracker import ProgressTrackerStore
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'progress.jsonl')
            store = ProgressTrackerStore(log_path=log_path)
            # 注册 track
            r = store.register(track_id='test_h', kind='hydration',
                                  label='Test', target=3000, unit='ml')
            self.assertTrue(r.get('ok'))
            # 加 += 500
            r2 = store.update(track_id='test_h', amount=500)
            self.assertTrue(r2.get('ok'))
            # set absolute 2000 (Sir 纠正)
            r3 = store.set_absolute(track_id='test_h', new_current=2000)
            self.assertTrue(r3.get('ok'),
                              f'set_absolute should ok, got {r3}')
            track = store.tracks.get('test_h')
            self.assertIsNotNone(track)
            self.assertEqual(track.current, 2000.0,
                              'set_absolute 应覆写 current=2000')


if __name__ == '__main__':
    unittest.main(verbosity=2)
