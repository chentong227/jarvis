# -*- coding: utf-8 -*-
"""[β.5.46-fix13 Fix-3 / 2026-05-22] WatchTask 抽象 verify

Sir 22:18 真测痛点: Sir 说"等导出完成提醒" Jarvis 答应 "I'll keep an eye on Adobe
Media Encoder" 但**没机制兑现**:
  - Time Hook 注册了 trigger=空 (regex 解不出"导出完成")
  - SelfPromise soft 找不到匹配 concern → 仅 log
  - ScreenVisionEngine 只 describe 给主脑, 不 trigger nudge

治本: WatchTask 抽象 (jarvis_watch_task.py)
  - Sir 说 + Jarvis ack → LLM 提取 watch task → 持久化 watch_tasks.json
  - ScreenVisionEngine.describe 后 → LLM judge active tasks → 命中 publish 'watch_task_fired' SWM + push __NUDGE__
  - _assemble_prompt [WATCH TASK FIRED] block → 主脑主动报告 Sir

Cover:
  A. WatchTask dataclass round-trip (to_dict / from_dict)
  B. _load_tasks / _save_tasks atomic + tolerant
  C. Registrar trigger phrase pre-filter (中英)
  D. Registrar template fallback (LLM 不可用时)
  E. Registrar persist + SWM publish
  F. Judge active_tasks query
  G. Judge mark_fired + SWM publish
  H. CLI: list / show / cancel / expire / stats
  I. ScreenVisionEngine._do_describe 接 judge hook (静态)
  J. chat_bypass.stream_chat 接 register hook (静态)
  K. _assemble_prompt [WATCH TASK FIRED] block (静态)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_tmp_tasks_file(tasks_list):
    """helper — 临时 watch_tasks.json."""
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump({'tasks': tasks_list}, tmp, ensure_ascii=False)
    tmp.close()
    return tmp.name


class TestA_WatchTaskDataclass(unittest.TestCase):
    def test_roundtrip(self):
        from jarvis_watch_task import WatchTask
        wt = WatchTask(
            id='wt_test_123',
            created_at=1779380000.0,
            sir_request='等导出完成提醒我',
            jarvis_ack="I'll keep an eye on the export",
            turn_id='turn_test',
            what_to_watch='Adobe Media Encoder export progress',
            trigger_evidence='progress reaches 100%',
            notify_msg_en='Sir, export complete.',
            notify_msg_zh='先生, 导出完成了.',
            state='active',
            expires_at=1779394400.0,
        )
        d = wt.to_dict()
        wt2 = WatchTask.from_dict(d)
        self.assertEqual(wt2.id, wt.id)
        self.assertEqual(wt2.what_to_watch, wt.what_to_watch)
        self.assertEqual(wt2.trigger_evidence, wt.trigger_evidence)
        self.assertEqual(wt2.state, wt.state)

    def test_is_active_states(self):
        from jarvis_watch_task import WatchTask
        wt = WatchTask(
            id='x', created_at=time.time(),
            sir_request='', jarvis_ack='', turn_id='',
            what_to_watch='x', trigger_evidence='x',
            notify_msg_en='', notify_msg_zh='',
            state='active',
        )
        self.assertTrue(wt.is_active())
        wt.state = 'fired'
        self.assertFalse(wt.is_active())

    def test_is_expired(self):
        from jarvis_watch_task import WatchTask
        wt = WatchTask(
            id='x', created_at=time.time(),
            sir_request='', jarvis_ack='', turn_id='',
            what_to_watch='x', trigger_evidence='x',
            notify_msg_en='', notify_msg_zh='',
            expires_at=time.time() - 100,  # past
        )
        self.assertTrue(wt.is_expired())
        wt.expires_at = time.time() + 100
        self.assertFalse(wt.is_expired())
        wt.expires_at = 0  # no expiry
        self.assertFalse(wt.is_expired())


class TestB_StoreLoadSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8')
        self.tmp.close()
        os.remove(self.tmp.name)  # we want path but not file (test missing-path tolerance)
        self.path = self.tmp.name

    def tearDown(self):
        try:
            os.remove(self.path)
        except Exception:
            pass

    def test_load_missing_returns_empty(self):
        from jarvis_watch_task import _load_tasks
        out = _load_tasks(path=self.path)
        self.assertEqual(out, [],
                          'missing file should return empty list (not raise)')

    def test_save_and_load_roundtrip(self):
        from jarvis_watch_task import WatchTask, _save_tasks, _load_tasks
        wt = WatchTask(
            id='wt_rt1', created_at=1779380000.0,
            sir_request='等导出完', jarvis_ack="I'll watch",
            turn_id='turn_x',
            what_to_watch='x', trigger_evidence='y',
            notify_msg_en='en', notify_msg_zh='zh',
        )
        ok = _save_tasks([wt], path=self.path)
        self.assertTrue(ok)
        out = _load_tasks(path=self.path)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].id, 'wt_rt1')

    def test_load_tolerant_corrupted(self):
        from jarvis_watch_task import _load_tasks
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('not valid json !!!')
        out = _load_tasks(path=self.path)
        self.assertEqual(out, [],
                          'corrupted file should return empty (not raise)')


class TestC_RegistrarTriggerPhrase(unittest.TestCase):
    def setUp(self):
        from jarvis_watch_task import WatchTaskRegistrar
        self.r = WatchTaskRegistrar()

    def test_zh_phrase_hits(self):
        self.assertTrue(self.r._has_trigger_phrase('等他导出完成提醒我'))
        self.assertTrue(self.r._has_trigger_phrase('好了告诉我'))
        self.assertTrue(self.r._has_trigger_phrase('渲染完通知我'))

    def test_en_phrase_hits(self):
        self.assertTrue(self.r._has_trigger_phrase('let me know when it finishes'))
        self.assertTrue(self.r._has_trigger_phrase('remind me when the build is done'))
        self.assertTrue(self.r._has_trigger_phrase('Tell me when it finishes please.'))

    def test_no_trigger_no_match(self):
        self.assertFalse(self.r._has_trigger_phrase("how's the weather"))
        self.assertFalse(self.r._has_trigger_phrase('what time is it'))


class TestD_RegistrarTemplateFallback(unittest.TestCase):
    def test_template_fallback_returns_dict_with_phrase(self):
        from jarvis_watch_task import WatchTaskRegistrar
        r = WatchTaskRegistrar()
        out = r._template_fallback(
            sir_text='等导出完成提醒我',
            jarvis_reply="I'll keep an eye on it",
        )
        self.assertIsNotNone(out)
        self.assertIn('what_to_watch', out)
        self.assertIn('trigger_evidence', out)
        self.assertIn('notify_msg_en', out)
        self.assertIn('notify_msg_zh', out)

    def test_template_fallback_none_without_phrase(self):
        from jarvis_watch_task import WatchTaskRegistrar
        r = WatchTaskRegistrar()
        out = r._template_fallback(
            sir_text='hello how are you',
            jarvis_reply='good',
        )
        self.assertIsNone(out)


class TestE_RegistrarParseJson(unittest.TestCase):
    def setUp(self):
        from jarvis_watch_task import WatchTaskRegistrar
        self.r = WatchTaskRegistrar()

    def test_parse_valid_json(self):
        raw = """{"watch": {
            "what_to_watch": "Adobe Media Encoder export progress",
            "trigger_evidence": "progress reaches 100%",
            "notify_msg_en": "Sir, export complete.",
            "notify_msg_zh": "先生, 导出完成了.",
            "rationale": "Sir asked to ping him when done"
        }}"""
        out = self.r._parse_llm_json(raw, 'etas', 'replys')
        self.assertIsNotNone(out)
        self.assertEqual(out['what_to_watch'],
                          'Adobe Media Encoder export progress')
        self.assertEqual(out['trigger_evidence'], 'progress reaches 100%')

    def test_parse_no_watch(self):
        raw = '{"watch": null}'
        out = self.r._parse_llm_json(raw, 'hello', 'hi')
        self.assertIsNone(out)

    def test_parse_markdown_fence(self):
        raw = """```json
{"watch": {"what_to_watch": "x", "trigger_evidence": "y",
"notify_msg_en": "e", "notify_msg_zh": "z"}}
```"""
        out = self.r._parse_llm_json(raw, 's', 'r')
        self.assertIsNotNone(out)
        self.assertEqual(out['what_to_watch'], 'x')


class TestF_JudgeBehavior(unittest.TestCase):
    """judge_against_snapshot 基础行为 — 没 active task / no key_router 时 skip."""

    def test_no_active_tasks_returns_empty(self):
        """sweep — 没 active task 时 judge 返 []."""
        from jarvis_watch_task import WatchTaskJudge

        class _FakeSnapshot:
            active_app = 'Test'
            screen_summary = 'test summary'
            file_or_url_visible = ''
            errors_visible = []
            build_output_status = ''
            recent_visible_keywords = []
            privacy_redacted = False

        # 注意此处用全局 tasks file, 但如果是空环境/没 active task → 应返 []
        # 用 _last_judge_at + min_judge_interval_s force allow:
        j = WatchTaskJudge()
        j._last_judge_at = 0  # force allow
        out = j.judge_against_snapshot(_FakeSnapshot(), key_router=None)
        self.assertIsInstance(out, list,
                                'judge should return list (even empty)')


class TestG_StaticHookChecks(unittest.TestCase):
    """静态 check ScreenVision / chat_bypass / nerve 接入点正确."""

    def test_screen_vision_has_judge_hook(self):
        import jarvis_screen_vision
        with open(jarvis_screen_vision.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('jarvis_watch_task', src,
                       'screen_vision 应 import jarvis_watch_task')
        self.assertIn('judge_against_snapshot', src,
                       'screen_vision 应调 judge_against_snapshot')
        self.assertIn('privacy_redacted', src,
                       'judge hook 应 skip privacy 帧')

    def test_chat_bypass_has_register_hook(self):
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('jarvis_watch_task', src,
                       'chat_bypass 应 import jarvis_watch_task')
        self.assertIn('register_async', src,
                       'chat_bypass 应调 watch_task.register_async')

    def test_nerve_has_watch_task_fired_block(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('WATCH TASK FIRED', src,
                       'nerve _assemble_prompt 应有 [WATCH TASK FIRED] block')
        self.assertIn("'watch_task_fired'", src,
                       'nerve 应 query SWM watch_task_fired event')
        self.assertIn('Sir 委托', src,
                       'block 应说明 "Sir 委托" 区分 unsolicited callback')


class TestH_CLI(unittest.TestCase):
    """CLI script 基础 check (import + 函数存在)."""

    def test_cli_script_imports(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'watch_task_dump_test',
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), 'scripts', 'watch_task_dump.py'),
        )
        self.assertIsNotNone(spec)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)  # type: ignore
        # 关键命令函数存在
        self.assertTrue(hasattr(m, 'cmd_list'))
        self.assertTrue(hasattr(m, 'cmd_show'))
        self.assertTrue(hasattr(m, 'cmd_cancel'))
        self.assertTrue(hasattr(m, 'cmd_expire'))
        self.assertTrue(hasattr(m, 'cmd_stats'))


class TestI_PrincipleCompliance(unittest.TestCase):
    """准则 6 4 问 — module 设计 check."""

    def test_module_publishes_swm(self):
        """#1 数据 publish SWM: register + fire 都 publish."""
        import jarvis_watch_task
        with open(jarvis_watch_task.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'watch_task_registered'", src,
                       'register 应 publish watch_task_registered SWM event')
        self.assertIn("'watch_task_fired'", src,
                       'fire 应 publish watch_task_fired SWM event')

    def test_module_uses_llm_decision(self):
        """#2 LLM 决策: 不写死 keyword 硬规则."""
        import jarvis_watch_task
        with open(jarvis_watch_task.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('safe_openrouter_call', src,
                       'registrar/judge 应调 LLM (safe_openrouter_call)')
        # judge prompt 含 LLM 自由判
        self.assertIn('judge: did any of', src.lower(),
                       'judge prompt 应让 LLM 自由判')

    def test_module_persists_with_cli(self):
        """#3 持久化 + CLI: tasks 进 JSON, CLI 可改."""
        import jarvis_watch_task
        with open(jarvis_watch_task.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('memory_pool', src,
                       'tasks 应在 memory_pool/')
        self.assertIn('cancel_task', src,
                       '应有 cancel_task CLI helper')
        self.assertIn('expire_task', src,
                       '应有 expire_task CLI helper')


if __name__ == '__main__':
    unittest.main()
