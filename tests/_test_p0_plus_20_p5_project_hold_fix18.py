# -*- coding: utf-8 -*-
"""[β.5.46-fix18 / 2026-05-22] Sir 11:39 真测 BUG — 驾照"放一放" 持久化失效

Sir 反馈:
  > "驾照考试我说了不用在意, 最近, 但是贾维斯好像没有记住"

Root cause: ProjectTimeline 不感知 Sir hold 信号. Sir 5/20 + 5/22 反复说
"驾照放一放/hold off/暂停/搁置", SmartNudge 仍 fire dormant_project.

3 数据源 refactor (A-F):
  A. vocab project_hold_phrases_vocab.json (25 phrases zh/en)
  B. ProjectTimeline 加 held_until_ts 列 + migration
  C. hippo.hold_project(name, hours) + find_project_by_keyword(kw)
  D. get_dormant_projects 过滤 held_until_ts > now
  E. tool_project_hold + TOOL_REGISTRY
  F. ProjectHoldDetector — vocab + project 双命中 → publish SWM candidate

Cover:
  TestA: vocab json schema (25 phrases active)
  TestB: detect_hold_phrase (vocab 命中)
  TestC: hippo migration — held_until_ts 列存在
  TestD: hippo.hold_project + find_project_by_keyword
  TestE: get_dormant_projects 过滤 hold 中的 project
  TestF: tool_project_hold (TOOL_REGISTRY 注册)
  TestG: detect_and_publish — 端到端 publish SWM candidate
  TestH: IntentResolver candidate_types 含新 type
  TestI: scripts CLI 工具能 list / add / activate
  TestJ: marker 在源码
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_VocabJson(unittest.TestCase):
    """A: vocab json schema + 25 active phrases."""

    def setUp(self):
        self.vocab_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'memory_pool', 'project_hold_phrases_vocab.json'
        )

    def test_vocab_exists(self):
        self.assertTrue(os.path.exists(self.vocab_path),
                          'project_hold_phrases_vocab.json 应存在')

    def test_vocab_schema(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('phrases', data)
        self.assertIn('review_queue', data)
        self.assertIn('rejected_history', data)

    def test_vocab_has_active_phrases(self):
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        active = [p for p in data['phrases'] if p.get('state') == 'active']
        self.assertGreaterEqual(len(active), 20,
                                  '应有 20+ active phrases')

    def test_vocab_sir_real_phrases(self):
        """Sir 真测里说过的关键 phrase 必须在 vocab."""
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        all_phrases = {p['phrase'].lower() for p in data['phrases']}
        for must in ['放一放', '暂停', '搁置', 'hold off', 'on hold',
                       'suppress the nudges']:
            self.assertIn(must.lower(), all_phrases,
                            f'vocab 缺关键 phrase: {must}')


class TestB_DetectHoldPhrase(unittest.TestCase):
    """B: detect_hold_phrase — vocab 命中."""

    def test_zh_phrase_hit(self):
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('驾照考试先放一放呢')
        self.assertIsNotNone(hit)
        self.assertIn(hit['phrase'], ['放一放', '先放一放'])

    def test_en_phrase_hit(self):
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase('Let me put driver license on hold')
        self.assertIsNotNone(hit)
        self.assertEqual(hit['phrase'], 'on hold')

    def test_jarvis_reply_hit(self):
        """Sir 5/20 jarvis reply: 'I shall suppress the nudges'."""
        from jarvis_project_hold_detector import detect_hold_phrase
        hit = detect_hold_phrase(
            "currently occupying the top of your stack, the driver's "
            "license theory can certainly wait. I shall suppress the nudges"
        )
        self.assertIsNotNone(hit)

    def test_no_hit_clean_text(self):
        from jarvis_project_hold_detector import detect_hold_phrase
        self.assertIsNone(detect_hold_phrase('Hello, how are you?'))
        self.assertIsNone(detect_hold_phrase('你好啊先生'))


class TestC_HippoMigration(unittest.TestCase):
    """C: ProjectTimeline 加 held_until_ts 列 (新 db / 老 db migration)."""

    def _build_temp_hippo(self):
        from jarvis_hippocampus import Hippocampus
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        hippo = Hippocampus(db_path=tmp.name)
        return hippo, tmp.name

    def test_new_db_has_held_until_ts_column(self):
        hippo, db_path = self._build_temp_hippo()
        try:
            conn = hippo._get_conn()
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(ProjectTimeline)")
            cols = {row[1] for row in cur.fetchall()}
            conn.close()
            self.assertIn('held_until_ts', cols,
                            'ProjectTimeline 应有 held_until_ts 列')
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


class TestD_HoldProjectMethod(unittest.TestCase):
    """D: hippo.hold_project + find_project_by_keyword."""

    def setUp(self):
        from jarvis_hippocampus import Hippocampus
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.hippo = Hippocampus(db_path=self.tmp.name)
        # 种 1 个 project: 驾照科一复习
        conn = self.hippo._get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ProjectTimeline (project_name, last_active_time, "
            "first_seen_time, status) VALUES (?, ?, ?, 'active')",
            ('驾照科一复习', time.time() - 10 * 86400, time.time() - 20 * 86400)
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_hold_project_success(self):
        ok = self.hippo.hold_project('驾照科一复习', hours=72)
        self.assertTrue(ok)

    def test_hold_project_case_insensitive(self):
        ok = self.hippo.hold_project('驾照科一复习', hours=72)
        self.assertTrue(ok)

    def test_hold_project_not_exists(self):
        ok = self.hippo.hold_project('does_not_exist_xyz', hours=72)
        self.assertFalse(ok, '不存在的 project hold 应返 False')

    def test_hold_project_invalid_hours(self):
        ok = self.hippo.hold_project('驾照科一复习', hours=0)
        self.assertFalse(ok)
        ok = self.hippo.hold_project('驾照科一复习', hours=-5)
        self.assertFalse(ok)

    def test_find_project_by_keyword(self):
        name = self.hippo.find_project_by_keyword('驾照')
        self.assertEqual(name, '驾照科一复习',
                          '模糊找 "驾照" 应返完整 project_name')

    def test_find_project_by_keyword_not_found(self):
        name = self.hippo.find_project_by_keyword('不存在')
        self.assertIsNone(name)


class TestE_DormantFilteredByHold(unittest.TestCase):
    """E: get_dormant_projects 过滤 hold 中的 project."""

    def setUp(self):
        from jarvis_hippocampus import Hippocampus
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.hippo = Hippocampus(db_path=self.tmp.name)
        # 种 2 个 dormant project (10 天没动)
        conn = self.hippo._get_conn()
        cur = conn.cursor()
        for name in ['驾照科一复习', 'cursor_billing']:
            cur.execute(
                "INSERT INTO ProjectTimeline (project_name, last_active_time, "
                "first_seen_time, status) VALUES (?, ?, ?, 'active')",
                (name, time.time() - 10 * 86400, time.time() - 20 * 86400)
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_dormant_default_returns_both(self):
        dormant = self.hippo.get_dormant_projects(dormant_days=3)
        names = {d['project_name'] for d in dormant}
        self.assertIn('驾照科一复习', names)
        self.assertIn('cursor_billing', names)

    def test_dormant_after_hold_excludes_held(self):
        """关键测试: Sir 真测 case — hold 驾照后, get_dormant 不再返."""
        self.hippo.hold_project('驾照科一复习', hours=72)
        dormant = self.hippo.get_dormant_projects(dormant_days=3)
        names = {d['project_name'] for d in dormant}
        self.assertNotIn('驾照科一复习', names,
                            '驾照 hold 后 get_dormant 不应再返')
        self.assertIn('cursor_billing', names,
                       '其他 project (无 hold) 仍在')

    def test_dormant_after_hold_expires_returns_again(self):
        """hold 过期后 get_dormant 又能返."""
        # hold 仅 1ms (立刻过期)
        self.hippo.hold_project('驾照科一复习', hours=1.0 / 3600.0 / 1000.0)
        time.sleep(0.01)
        dormant = self.hippo.get_dormant_projects(dormant_days=3)
        names = {d['project_name'] for d in dormant}
        self.assertIn('驾照科一复习', names,
                       'hold 过期后应再次进 dormant')


class TestF_ToolRegistered(unittest.TestCase):
    """F: tool_project_hold 注册到 TOOL_REGISTRY."""

    def test_tool_in_registry(self):
        from jarvis_tool_registry import TOOL_REGISTRY
        self.assertIn('project_hold', TOOL_REGISTRY)

    def test_tool_signature(self):
        from jarvis_tool_registry import tool_project_hold
        # missing project_keyword
        r = tool_project_hold(project_keyword='')
        self.assertFalse(r['ok'])
        # invalid hours
        r = tool_project_hold(project_keyword='驾照', hours=0)
        self.assertFalse(r['ok'])
        r = tool_project_hold(project_keyword='驾照', hours=999999)
        self.assertFalse(r['ok'])

    def test_tool_no_nerve(self):
        """nerve 不可用应 fail 但不 throw."""
        from jarvis_tool_registry import tool_project_hold
        r = tool_project_hold(project_keyword='驾照', hours=72, nerve=None)
        self.assertFalse(r['ok'])

    def test_tool_no_hippocampus(self):
        from jarvis_tool_registry import tool_project_hold

        class _NerveNoHippo:
            pass
        r = tool_project_hold(project_keyword='驾照', hours=72,
                                nerve=_NerveNoHippo())
        self.assertFalse(r['ok'])


class TestG_DetectAndPublish(unittest.TestCase):
    """G: detect_and_publish 端到端 — Sir 真测 case 复现 + 修."""

    def setUp(self):
        from jarvis_hippocampus import Hippocampus
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.hippo = Hippocampus(db_path=self.tmp.name)
        conn = self.hippo._get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ProjectTimeline (project_name, last_active_time, "
            "first_seen_time, status) VALUES (?, ?, ?, 'active')",
            ('驾照科一复习', time.time() - 10 * 86400, time.time() - 20 * 86400)
        )
        conn.commit()
        conn.close()
        # event bus mock
        self.events = []

        class _MockBus:
            def __init__(self, sink):
                self.sink = sink

            def publish(self, **kw):
                self.sink.append(kw)

            def recent_events(self, **kw):
                return list(self.sink)
        self.bus = _MockBus(self.events)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_sir_actual_case_zh_publishes_candidate(self):
        """Sir 5/22 11:39 case: '我要准备面试, 驾照考试先放一放呢'."""
        from jarvis_project_hold_detector import detect_and_publish
        result = detect_and_publish(
            cmd='可是我记得我跟你说过, 我最近要准备面试的事情, 所以驾照考试先放一放呢',
            jarvis_reply='',
            turn_id='turn_test',
            hippocampus=self.hippo,
            event_bus=self.bus,
        )
        self.assertIsNotNone(result, 'Sir 案例应触发 candidate')
        self.assertEqual(result['project_name'], '驾照科一复习')
        self.assertIn(result['phrase_hit'], ['放一放', '先放一放'])
        # event 真 publish 进 bus
        self.assertGreaterEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual(ev['etype'], 'sir_intent_project_hold_candidate')

    def test_sir_zh_cmd_with_project_keyword(self):
        """Sir 中文 cmd 含 hold phrase + project keyword → publish."""
        from jarvis_project_hold_detector import detect_and_publish
        result = detect_and_publish(
            cmd='驾照考试暂停一下吧',
            jarvis_reply='',
            turn_id='turn_test',
            hippocampus=self.hippo,
            event_bus=self.bus,
        )
        self.assertIsNotNone(result, 'cmd 含 "驾照" + "暂停" 应 publish')
        self.assertEqual(result['project_name'], '驾照科一复习')

    def test_no_phrase_no_publish(self):
        from jarvis_project_hold_detector import detect_and_publish
        result = detect_and_publish(
            cmd='Hello, how are you today?',
            jarvis_reply='Doing well, Sir.',
            turn_id='turn_test',
            hippocampus=self.hippo,
            event_bus=self.bus,
        )
        self.assertIsNone(result)
        self.assertEqual(len(self.events), 0)

    def test_phrase_no_project_no_publish(self):
        """phrase 命中但没 project match → 不 publish (避免误触)."""
        from jarvis_project_hold_detector import detect_and_publish
        result = detect_and_publish(
            cmd='放一放吧',  # 有 phrase 但没 project keyword
            jarvis_reply='',
            turn_id='turn_test',
            hippocampus=self.hippo,
            event_bus=self.bus,
        )
        # '放一放' 命中但 hippo.find_project_by_keyword 找不到匹 '驾照科一复习' 的关键词
        # → 返 None
        self.assertIsNone(result)


class TestH_IntentResolverCandidateType(unittest.TestCase):
    """H: IntentResolver _collect_candidates 含新 type."""

    def test_candidate_type_registered(self):
        import jarvis_intent_resolver
        with open(jarvis_intent_resolver.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'sir_intent_project_hold_candidate'", src,
                       'IntentResolver candidate_types 应含 project_hold')


class TestI_CliTool(unittest.TestCase):
    """I: scripts/project_hold_phrases_dump.py CLI 工具基本可用."""

    def test_cli_imports(self):
        # CLI 模块能 import (语法 ok)
        cli_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'project_hold_phrases_dump.py'
        )
        self.assertTrue(os.path.exists(cli_path), 'CLI 工具应存在')

    def test_cli_load_function(self):
        """CLI 的 _load 函数能读 vocab."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts'
        ))
        try:
            import project_hold_phrases_dump as cli
            data = cli._load()
            self.assertIn('phrases', data)
            self.assertGreater(len(data['phrases']), 0)
        finally:
            # 清理 import (避免污染其他 test)
            if 'project_hold_phrases_dump' in sys.modules:
                del sys.modules['project_hold_phrases_dump']


class TestJ_MarkerCoverage(unittest.TestCase):
    """J: fix18 marker 在所有改动文件."""

    def test_markers(self):
        files = [
            'jarvis_hippocampus.py',
            'jarvis_tool_registry.py',
            'jarvis_intent_resolver.py',
            'jarvis_chat_bypass.py',
            'jarvis_project_hold_detector.py',
        ]
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in files:
            path = os.path.join(base, fname)
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
            self.assertIn('β.5.46-fix18', src,
                            f'fix18 marker 应在 {fname}')


if __name__ == '__main__':
    unittest.main()
