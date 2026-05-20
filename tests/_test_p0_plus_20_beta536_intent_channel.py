# -*- coding: utf-8 -*-
"""[β.5.36 / 2026-05-20] Intent channel + tool name scrub regression test (BUG 3 大修).

Sir 2026-05-20 10:46 实测 BUG 3: 工具名泄漏 ("I can run process_hands.get_top_cpu...").
β.5.36 5 sub-step:
  E: memory_pool/intent_to_tool_map.json + scripts/intent_map_dump.py CLI
  F: skill_registry.to_prompt_block 双轨 (intent + 禁工具名)
  G: jarvis_intent_router.py <TOOL_CALL>{intent} 解析 + 调用 + SWM 回流
  H: jarvis_utils.scrub_internal_names + jarvis_ui subtitle scrub
  I: 本 testcase (~20)

doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTENT_MAP_PATH = os.path.join(ROOT, 'memory_pool', 'intent_to_tool_map.json')
INTENT_CLI_PATH = os.path.join(ROOT, 'scripts', 'intent_map_dump.py')


# ==========================================================================
# E: intent_to_tool_map JSON + CLI
# ==========================================================================

class TestBeta536EIntentMapFile(unittest.TestCase):
    """intent_to_tool_map.json schema + seed."""

    def test_file_exists(self):
        self.assertTrue(os.path.exists(INTENT_MAP_PATH),
            f'intent_to_tool_map.json 必须存在: {INTENT_MAP_PATH}')

    def test_schema(self):
        with open(INTENT_MAP_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k in ('_meta', 'intents', 'review_queue', 'rejected_history'):
            self.assertIn(k, data)
        self.assertEqual(data['_meta']['schema_version'], 1)

    def test_seed_intents_present(self):
        with open(INTENT_MAP_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        active = {c['id'] for c in data['intents']
                  if c.get('state', 'active') == 'active'}
        # β.5.36-E 15 seed
        for seed in ('check_top_cpu', 'mute_audio', 'unmute_audio',
                     'set_volume', 'pause_media', 'send_notification',
                     'dashboard_open'):
            self.assertIn(seed, active, f'seed intent {seed} 必须存在')

    def test_intent_fields_complete(self):
        with open(INTENT_MAP_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for c in data['intents']:
            for required in ('id', 'state', 'tool', 'semantic_hint', 'dangerous_flag'):
                self.assertIn(required, c, f'intent {c.get("id")} 缺 {required}')
            self.assertIn(c['dangerous_flag'], ('safe', 'risky', 'dangerous'))


class TestBeta536ECLI(unittest.TestCase):
    """intent_map_dump.py CLI 工作."""

    def test_cli_exists(self):
        self.assertTrue(os.path.exists(INTENT_CLI_PATH))

    def test_cli_active_list_runs(self):
        r = subprocess.run(
            [sys.executable, INTENT_CLI_PATH, '--active-only'],
            capture_output=True, text=True, cwd=ROOT, timeout=30,
            encoding='utf-8', errors='replace',
        )
        self.assertEqual(r.returncode, 0, f'CLI fail: {r.stderr}')
        out = (r.stdout or '').lower()
        self.assertIn('intent', out)


# ==========================================================================
# F: skill_registry.to_prompt_block 双轨
# ==========================================================================

class TestBeta536FDualTrackPromptBlock(unittest.TestCase):
    """skill_registry.to_prompt_block 必须优先用 intent_map (semantic),
    fallback 老 skill list (向后兼容)."""

    def setUp(self):
        from jarvis_skill_registry import SkillRegistry
        SkillRegistry.reset_instance_for_test()
        self.reg = SkillRegistry.get_instance()

    def test_intent_map_renders_semantic_block(self):
        """有 intent_map.json → 渲染 SEMANTIC CAPABILITIES, 不含工具名."""
        block = self.reg.to_prompt_block(intent_map_path=INTENT_MAP_PATH)
        self.assertIn('SEMANTIC CAPABILITIES', block,
            'intent_map 存在时必须用 SEMANTIC CAPABILITIES 标题')
        self.assertIn('<TOOL_CALL>', block,
            'directive 必须教 LLM 用 <TOOL_CALL> tag')
        self.assertIn('NEVER speak the internal tool name', block,
            '必须显式禁工具名')
        # 至少 1 seed intent 在 block 里
        self.assertIn("intent='check_top_cpu'", block)
        # 反例: 不该直接含 organ.command 工具名 (如 process_hands.get_top_cpu)
        self.assertNotIn('process_hands.get_top_cpu', block,
            'SEMANTIC 块不该暴露 tool 全名')

    def test_fallback_when_no_intent_map(self):
        """intent_map 不存在 → fallback skill list, 但仍含工具名禁令."""
        with tempfile.TemporaryDirectory() as tmp:
            non_existent = os.path.join(tmp, 'does_not_exist.json')
            # 注册一个 fake skill 让 fallback 有内容
            from jarvis_skill_registry import SkillManifest, DANGER_SAFE
            self.reg.register(SkillManifest(
                command='fake.test_tool',
                module='fake', callable_name='test_tool',
                description='fake test', dangerous_flag=DANGER_SAFE,
            ))
            block = self.reg.to_prompt_block(intent_map_path=non_existent)
            # fallback 时不再硬要求 LLM "MUST reference by name"
            self.assertNotIn('MUST reference one of these by name', block,
                'fallback 也不该再要求 LLM 说工具名 (β.5.36-F 删)')

    def test_filter_safe_only(self):
        """filter_safe_only=True 必须过滤 risky/dangerous intent."""
        block = self.reg.to_prompt_block(
            intent_map_path=INTENT_MAP_PATH,
            filter_safe_only=True,
        )
        # check_top_cpu (safe) 应在
        self.assertIn("intent='check_top_cpu'", block)
        # kill_process (risky) 应不在
        self.assertNotIn("intent='kill_process'", block)


# ==========================================================================
# G: IntentParser + IntentRouter
# ==========================================================================

class TestBeta536GIntentParser(unittest.TestCase):
    """IntentParser 解析 <TOOL_CALL>{intent}</TOOL_CALL> 标签."""

    def test_extract_single_tag(self):
        from jarvis_intent_router import IntentParser
        text = 'Let me check.\n<TOOL_CALL>{"intent": "check_top_cpu"}</TOOL_CALL>'
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].intent_id, 'check_top_cpu')
        self.assertEqual(calls[0].args, {})

    def test_extract_with_args(self):
        from jarvis_intent_router import IntentParser
        text = '<TOOL_CALL>{"intent": "set_volume", "args": {"level": 30}}</TOOL_CALL>'
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].intent_id, 'set_volume')
        self.assertEqual(calls[0].args, {'level': 30})

    def test_extract_multiple(self):
        from jarvis_intent_router import IntentParser
        text = ('<TOOL_CALL>{"intent": "a"}</TOOL_CALL> '
                'then <TOOL_CALL>{"intent": "b"}</TOOL_CALL>')
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 2)
        self.assertEqual([c.intent_id for c in calls], ['a', 'b'])

    def test_corrupt_tag_skipped(self):
        from jarvis_intent_router import IntentParser
        text = ('<TOOL_CALL>NOT JSON</TOOL_CALL> '
                '<TOOL_CALL>{"intent": "ok"}</TOOL_CALL>')
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 1, '损坏 tag 应跳过, 正确 tag 应通过')
        self.assertEqual(calls[0].intent_id, 'ok')

    def test_has_tool_call_tag(self):
        from jarvis_intent_router import IntentParser
        self.assertTrue(IntentParser.has_tool_call_tag('<TOOL_CALL>{}</TOOL_CALL>'))
        self.assertFalse(IntentParser.has_tool_call_tag('plain text'))
        self.assertFalse(IntentParser.has_tool_call_tag(''))
        self.assertFalse(IntentParser.has_tool_call_tag(None))

    def test_strip_tags(self):
        from jarvis_intent_router import IntentParser
        text = 'hello <TOOL_CALL>{"intent":"x"}</TOOL_CALL> world'
        out = IntentParser.strip_tags(text)
        self.assertEqual(out.strip(), 'hello  world'.strip())

    def test_case_insensitive(self):
        from jarvis_intent_router import IntentParser
        text = '<tool_call>{"intent": "x"}</tool_call>'
        calls = IntentParser.extract_all(text)
        self.assertEqual(len(calls), 1)


class TestBeta536GIntentRouter(unittest.TestCase):
    """IntentRouter 路由 + 调用."""

    def setUp(self):
        from jarvis_intent_router import IntentRouter
        self.invoked = []
        def _fake_fast_call(organ, cmd, args):
            self.invoked.append((organ, cmd, args))
            return f"✅ {organ}.{cmd} done"
        self.router = IntentRouter(
            fast_call_executor=_fake_fast_call,
            intent_map_path=INTENT_MAP_PATH,
        )

    def test_resolve_known_intent(self):
        entry = self.router.resolve_intent('check_top_cpu')
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get('tool'), 'process_hands.get_top_cpu')

    def test_resolve_unknown_intent(self):
        self.assertIsNone(self.router.resolve_intent('nonexistent_intent_xyz'))

    def test_route_and_invoke_success(self):
        from jarvis_intent_router import IntentCall
        call = IntentCall(intent_id='check_top_cpu', args={})
        result = self.router.route_and_invoke(call)
        self.assertTrue(result['success'], f'should succeed: {result}')
        self.assertEqual(result['tool'], 'process_hands.get_top_cpu')
        # fake_fast_call 被调
        self.assertEqual(len(self.invoked), 1)
        organ, cmd, args = self.invoked[0]
        self.assertEqual(organ, 'process_hands')
        self.assertEqual(cmd, 'get_top_cpu')

    def test_route_unknown_intent_no_crash(self):
        from jarvis_intent_router import IntentCall
        call = IntentCall(intent_id='no_such_intent', args={})
        result = self.router.route_and_invoke(call)
        self.assertFalse(result['success'])
        self.assertEqual(result.get('reason'), 'unknown_intent')

    def test_route_dangerous_skipped(self):
        """dangerous intent → skip + reason='dangerous_requires_promise_path'.

        β.5.36-G v1 不自动执行 dangerous, 走 PROMISE 路径."""
        from jarvis_intent_router import IntentCall
        # 临时插一个 dangerous intent fixture
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                          delete=False, encoding='utf-8') as tmp:
            json.dump({
                '_meta': {'schema_version': 1},
                'intents': [{
                    'id': 'do_dangerous',
                    'state': 'active',
                    'tool': 'file_operator.delete',
                    'semantic_hint': 'delete file',
                    'dangerous_flag': 'dangerous',
                }],
                'review_queue': [],
                'rejected_history': [],
            }, tmp)
            tmp_path = tmp.name
        try:
            from jarvis_intent_router import IntentRouter
            r2 = IntentRouter(
                fast_call_executor=lambda o, c, a: "should not be called",
                intent_map_path=tmp_path,
            )
            result = r2.route_and_invoke(IntentCall(intent_id='do_dangerous'))
            self.assertFalse(result['success'])
            self.assertEqual(result['reason'], 'dangerous_requires_promise_path')
        finally:
            os.unlink(tmp_path)

    def test_route_and_invoke_all_extracts_and_runs(self):
        text = ('Let me check. '
                '<TOOL_CALL>{"intent": "check_top_cpu"}</TOOL_CALL>')
        results = self.router.route_and_invoke_all(text)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['success'])

    def test_no_fast_call_no_crash(self):
        from jarvis_intent_router import IntentRouter, IntentCall
        r3 = IntentRouter(fast_call_executor=None,
                          intent_map_path=INTENT_MAP_PATH)
        result = r3.route_and_invoke(IntentCall(intent_id='check_top_cpu'))
        self.assertFalse(result['success'])
        self.assertEqual(result['reason'], 'no_fast_call_executor')


# ==========================================================================
# H: scrub_internal_names + UI subtitle scrub
# ==========================================================================

class TestBeta536HScrubHelper(unittest.TestCase):
    """jarvis_utils.scrub_internal_names + has_internal_name."""

    def test_scrub_tool_name_substitutes(self):
        from jarvis_utils import scrub_internal_names
        t = "I can run process_hands.get_top_cpu to check"
        out = scrub_internal_names(t)
        self.assertNotIn('process_hands', out)
        self.assertNotIn('get_top_cpu', out)
        self.assertIn('a quick check', out)

    def test_scrub_tool_call_tag(self):
        from jarvis_utils import scrub_internal_names
        t = 'hello <TOOL_CALL>{"intent":"x"}</TOOL_CALL> world'
        out = scrub_internal_names(t)
        self.assertNotIn('<TOOL_CALL>', out)
        self.assertNotIn('intent', out)
        self.assertIn('hello', out)
        self.assertIn('world', out)

    def test_scrub_empty_safe(self):
        from jarvis_utils import scrub_internal_names
        self.assertEqual(scrub_internal_names(''), '')
        self.assertEqual(scrub_internal_names(None), '')

    def test_scrub_no_tool_name_passthrough(self):
        from jarvis_utils import scrub_internal_names
        t = "normal speech, nothing internal"
        self.assertEqual(scrub_internal_names(t), t)

    def test_has_internal_name(self):
        from jarvis_utils import has_internal_name
        self.assertTrue(has_internal_name('audio_hands.mute'))
        self.assertTrue(has_internal_name('<TOOL_CALL>{}</TOOL_CALL>'))
        self.assertFalse(has_internal_name('hello world'))
        self.assertFalse(has_internal_name(''))

    def test_scrub_covers_all_organs(self):
        """所有 organ prefix 都该命中 — process/file_operator/audio/window/etc."""
        from jarvis_utils import scrub_internal_names
        organs = [
            'process_hands.X', 'file_operator.Y', 'audio_hands.mute',
            'window_hands.focus', 'media_control_hands.pause',
            'notification_hands.send', 'system_hands.info',
            'ui_control.dashboard_open', 'hippocampus.search',
        ]
        for o in organs:
            scrubbed = scrub_internal_names(o)
            self.assertNotIn(o.split('.')[0], scrubbed,
                f'organ {o} 必须被 scrub')


class TestBeta536HUISubtitleScrub(unittest.TestCase):
    """jarvis_ui.py _poll_queue 'en' / 'zh' branch 必须 import + 调 scrub."""

    def test_ui_imports_scrub(self):
        with open(os.path.join(ROOT, 'jarvis_ui.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.36-H', src,
            'jarvis_ui.py 必须含 β.5.36-H marker')
        self.assertIn('scrub_internal_names', src,
            'jarvis_ui.py 必须 import scrub_internal_names')
        # 必须在 'zh' 和 'en' lang branch 都调
        zh_branch = src[src.find('elif lang == "zh"'):src.find('elif lang == "en"')]
        en_branch = src[src.find('elif lang == "en"'):src.find('elif lang == "user"')]
        self.assertIn('scrub_internal_names', zh_branch,
            "'zh' branch 必须调 scrub")
        self.assertIn('scrub_internal_names', en_branch,
            "'en' branch 必须调 scrub")


# ==========================================================================
# Chat_bypass + worker wiring
# ==========================================================================

class TestBeta536WiringPresent(unittest.TestCase):
    """central wire 完整 (chat_bypass / worker / skill_registry)."""

    def test_chat_bypass_runs_intent_router(self):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.36-G', src, 'chat_bypass 必须有 β.5.36-G marker')
        self.assertIn('IntentParser', src)
        self.assertIn('route_and_invoke_all', src)

    def test_worker_inits_intent_router(self):
        with open(os.path.join(ROOT, 'jarvis_worker.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.36-G', src, 'worker 必须有 β.5.36-G marker')
        self.assertIn('init_default_intent_router', src,
            'worker 必须 init_default_intent_router 注入 fast_call')

    def test_skill_registry_intent_block_renderer(self):
        with open(os.path.join(ROOT, 'jarvis_skill_registry.py'), 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('β.5.36-F', src, 'skill_registry 必须有 β.5.36-F marker')
        self.assertIn('_render_intent_block', src,
            '必须有 _render_intent_block helper')
        self.assertIn('SEMANTIC CAPABILITIES', src)


if __name__ == '__main__':
    unittest.main()
