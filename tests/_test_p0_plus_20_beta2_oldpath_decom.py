# -*- coding: utf-8 -*-
"""[P0+20-β.2.4.3 / 2026-05-16] 老路径退役回归测试

验证方案 A 第 3 步代码改动正确：
- SoulRouter 只剩 projects / progression chapter，inside_jokes / milestones 已删
- ProfileCard._build_likes_boundaries 不再 dump inside_jokes_count
- memory_core HumorEngine 改读 relational_state.inside_jokes

详 docs/JARVIS_SOUL_DRIVE.md
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_routing import SoulRouter
from jarvis_relational import (
    RelationalStateStore, InsideJoke,
    reset_default_store_for_test, get_default_store,
)


class TestSoulRouterDecommission(unittest.TestCase):
    """SoulRouter 应只剩 projects / progression chapter"""

    def test_only_projects_and_progression_when_all_fields_present(self):
        profile = {
            'active_projects': ['Project A', 'Project B'],
            'our_inside_jokes': ['joke 1', 'joke 2'],     # 应被忽略
            'significant_milestones': ['milestone X'],    # 应被忽略
            'skill_progression': [{'skill': 'rust'}],
        }
        router = SoulRouter(profile)
        self.assertIn('projects', router.chapters)
        self.assertIn('progression', router.chapters)
        self.assertNotIn('inside_jokes', router.chapters)
        self.assertNotIn('milestones', router.chapters)

    def test_no_chapters_when_no_projects_or_progression(self):
        profile = {
            'our_inside_jokes': ['joke 1'],
            'significant_milestones': ['m1'],
        }
        router = SoulRouter(profile)
        # 既然只剩 projects/progression，且这两个都空 → router 没 chapter
        self.assertEqual(len(router.chapters), 0)

    def test_route_does_not_return_inside_jokes_or_milestones(self):
        profile = {
            'active_projects': ['Jarvis system'],
            'our_inside_jokes': ['the furniture joke'],
            'significant_milestones': ['Built Jarvis'],
            'skill_progression': [],
        }
        router = SoulRouter(profile)
        # 即使提到"jokes" 或 "milestones" 关键字，也不应 route 到这两个
        result = router.route("any inside jokes? any milestones?",
                              "tell me jokes milestones")
        self.assertNotIn('inside_jokes', result)
        self.assertNotIn('milestones', result)


class TestProfileCardDecommission(unittest.TestCase):
    """ProfileCard._build_likes_boundaries 不再 dump inside_jokes_count"""

    def test_likes_boundaries_no_inside_jokes_count_field(self):
        # 由于 ProfileCard 需要 central_nerve 实例（太重）— 我们用 mock
        from jarvis_routing import ProfileCard

        class _MockNerve:
            habit_clock = None
            causal_chain = None
            content_tracker = None
            status_ledger = None
            project_timeline = None

        # ProfileCard 内 _load_profile() 读 sir_profile.json 真实路径
        # 我们替换它以隔离测试
        pc = ProfileCard(_MockNerve())
        pc._load_profile = lambda: {
            'conversational_boundaries': 'no fake humor',
            'our_inside_jokes': ['joke 1', 'joke 2'],  # 即使有，不应被 dump
        }
        result = pc._build_likes_boundaries()
        self.assertIn('boundaries', result)
        self.assertNotIn('inside_jokes_count', result)
        self.assertEqual(result['boundaries'], 'no fake humor')


class TestMemoryCoreReadsRelational(unittest.TestCase):
    """HumorEngine._load_profile_jokes 应改读 relational_state，不再读 sir_profile"""

    def setUp(self):
        reset_default_store_for_test()
        # 用临时 relational_state 单例
        from jarvis_relational import _DEFAULT_STORE  # noqa: F401
        self.tmp = tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w', encoding='utf-8'
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        # patch get_default_store 让它返回我们的 fixture
        import jarvis_relational
        self._original_default = jarvis_relational._DEFAULT_STORE
        store = RelationalStateStore(persist_path=self.tmp.name)
        store.add_inside_joke(InsideJoke(
            id='j1', phrase='this is about racing game speed'
        ))
        store.add_inside_joke(InsideJoke(
            id='j2', phrase='cursor coding sucks sometimes'
        ))
        jarvis_relational._DEFAULT_STORE = store
        self.store = store

    def tearDown(self):
        import jarvis_relational
        jarvis_relational._DEFAULT_STORE = self._original_default
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)
        reset_default_store_for_test()

    def test_humor_engine_reads_relational_keywords(self):
        # 直接实例化 HumorEngine 并触发 _load_profile_jokes
        # HumorEngine 名字可能在 memory_core 里不同，找一下
        import jarvis_memory_core as mc
        # 找 class 含 _load_profile_jokes 方法
        engine_cls = None
        for name in dir(mc):
            obj = getattr(mc, name)
            if isinstance(obj, type) and hasattr(obj, '_load_profile_jokes'):
                engine_cls = obj
                break
        self.assertIsNotNone(engine_cls,
                             "expected a class with _load_profile_jokes in jarvis_memory_core")
        engine = engine_cls()
        engine._load_profile_jokes()
        # 'racing'/'speed' → racing_game；'cursor'/'coding' → coding_ide
        self.assertIn('racing_game', engine._profile_joke_keywords)
        self.assertIn('coding_ide', engine._profile_joke_keywords)

    def test_humor_engine_empty_relational_clears_keywords(self):
        # 清空 store 后再 force reload
        self.store.archive_inside_joke('j1')
        self.store.archive_inside_joke('j2')
        import jarvis_memory_core as mc
        engine_cls = None
        for name in dir(mc):
            obj = getattr(mc, name)
            if isinstance(obj, type) and hasattr(obj, '_load_profile_jokes'):
                engine_cls = obj
                break
        engine = engine_cls()
        engine._profile_last_load = 0  # force reload
        engine._load_profile_jokes()
        self.assertEqual(engine._profile_joke_keywords, {})


class TestSoulArchivistRedirection(unittest.TestCase):
    """β.2.4.4：SoulArchivistSentinel 不再 dump jokes/milestones 到 sir_profile，
    改 propose 到 relational_state.review 队列。"""

    def test_sentinel_prompt_uses_proposed_keys(self):
        """静态检查：sentinel 的 LLM prompt 含 proposed_inside_jokes /
        proposed_shared_history_threads 字符串，且明确告诉 LLM 不再输出
        our_inside_jokes / significant_milestones。"""
        sentinels_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_sentinels.py'
        )
        with open(sentinels_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('proposed_inside_jokes', content)
        self.assertIn('proposed_shared_history_threads', content)
        # prompt 中应明确 deprecate 老字段
        self.assertIn('deprecated', content)

    def test_sentinel_redirects_to_relational_propose(self):
        """静态检查：sentinel 在解析 JSON 后调 store.propose_inside_joke /
        store.propose_thread + store.write_review_queue。"""
        sentinels_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'jarvis_sentinels.py'
        )
        with open(sentinels_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('propose_inside_joke', content)
        self.assertIn('propose_thread', content)
        self.assertIn('write_review_queue', content)
        # 同时不再写 our_inside_jokes / significant_milestones 到 profile
        # （检查 pop 这两个 key 防止 LLM 输出老格式时被透传）
        self.assertIn("new_profile.pop('our_inside_jokes'", content)
        self.assertIn("new_profile.pop('significant_milestones'", content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
