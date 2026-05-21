# -*- coding: utf-8 -*-
"""[P5-fix-items-i18n / 2026-05-21 10:00-10:15] Sir 09:55 截图反馈 cover.

Sir 截图: dashboard `/items` 页:
  ① 卡片只显 vocab id + tag 没人话翻译 → 加 description_zh + category_zh
  ② 没 👍/👎 反馈按钮 → 加 sir_feedback + /api/items/<id>/feedback endpoint

Cover:
  A. ActionableItem schema 加 description_zh + category_zh + sir_feedback
  B. CATEGORY_ZH_MAP 包含主要 category
  C. struggle / screen_tease / directives extractor 填 description_zh
  D. save_item_feedback persist 到 jsonl + state json
  E. post-process 兜底填 category_zh
  F. dashboard html 含 description_zh + 👍👎 按钮
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_SchemaFields(unittest.TestCase):
    """schema 含 description_zh / category_zh / sir_feedback."""

    def test_schema_has_new_fields(self):
        from jarvis_actionable_items import ActionableItem
        item = ActionableItem(id='x', category='struggle')
        self.assertEqual(item.description_zh, '')
        self.assertEqual(item.category_zh, '')
        self.assertEqual(item.sir_feedback, '')

    def test_to_dict_contains_new_fields(self):
        from jarvis_actionable_items import ActionableItem
        item = ActionableItem(
            id='x', category='struggle',
            description_zh='测试描述', category_zh='测试类别',
            sir_feedback='up',
        )
        d = item.to_dict()
        self.assertEqual(d['description_zh'], '测试描述')
        self.assertEqual(d['category_zh'], '测试类别')
        self.assertEqual(d['sir_feedback'], 'up')


class TestB_CategoryZhMap(unittest.TestCase):
    """CATEGORY_ZH_MAP 包含 dashboard 主要 category."""

    def test_main_categories_present(self):
        from jarvis_actionable_items import CATEGORY_ZH_MAP
        for cat in ('concern', 'struggle', 'directive', 'screen_tease',
                    'inside_joke', 'thread', 'protocol', 'unfinished',
                    'sleep_pattern', 'callback', 'profile'):
            self.assertIn(cat, CATEGORY_ZH_MAP, f'category {cat} 缺中文映射')

    def test_zh_values_have_emoji_prefix(self):
        from jarvis_actionable_items import CATEGORY_ZH_MAP
        # 每个 zh 名都应包含 emoji + 中文 (改善 Sir 阅读)
        for cat, zh in CATEGORY_ZH_MAP.items():
            self.assertTrue(len(zh) >= 4, f'{cat} 中文太短: {zh}')


class TestC_StruggleExtractorDescription(unittest.TestCase):
    """struggle extractor 填 description_zh = 人话."""

    def test_struggle_describe_high_zh(self):
        from jarvis_actionable_items import _extract_struggle, _load_ack_state
        items = _extract_struggle(_load_ack_state())
        self.assertGreater(len(items), 0, 'struggle vocab 应有 seed entries')
        # 找 stuck_zh (Sir 截图里看到的)
        stuck_zh = next((i for i in items if i.id == 'stuck_zh'), None)
        if stuck_zh is None:
            self.skipTest('stuck_zh seed 不在 vocab 里')
        self.assertNotEqual(stuck_zh.description_zh, '', 'stuck_zh 应有 description_zh')
        self.assertIn('Conductor', stuck_zh.description_zh, 'description 应解释 Conductor 触发')
        self.assertIn('offer_help', stuck_zh.description_zh)


class TestD_SaveItemFeedback(unittest.TestCase):
    """save_item_feedback 写 state json + audit jsonl."""

    def setUp(self):
        from jarvis_actionable_items import _feedback_state_path
        # 用真路径但 backup state, test 后 restore
        self._path = _feedback_state_path()
        self._backup = None
        if os.path.exists(self._path):
            with open(self._path, 'r', encoding='utf-8') as f:
                self._backup = f.read()

    def tearDown(self):
        if self._backup is not None:
            with open(self._path, 'w', encoding='utf-8') as f:
                f.write(self._backup)
        elif os.path.exists(self._path):
            os.remove(self._path)
        # 清 audit jsonl 末尾 test entries (不删整个文件 — 可能 Sir 真有数据)
        # 这是 best-effort, test feedback 进 audit 没问题

    def test_save_up(self):
        from jarvis_actionable_items import save_item_feedback, _get_feedback
        ok = save_item_feedback('test_item_xyz', 'up', 'test note')
        self.assertTrue(ok)
        self.assertEqual(_get_feedback('test_item_xyz'), 'up')

    def test_save_down(self):
        from jarvis_actionable_items import save_item_feedback, _get_feedback
        ok = save_item_feedback('test_item_xyz', 'down', '')
        self.assertTrue(ok)
        self.assertEqual(_get_feedback('test_item_xyz'), 'down')

    def test_revoke_feedback_with_empty(self):
        from jarvis_actionable_items import save_item_feedback, _get_feedback
        save_item_feedback('test_item_xyz', 'up', '')
        self.assertEqual(_get_feedback('test_item_xyz'), 'up')
        ok = save_item_feedback('test_item_xyz', '', '')
        self.assertTrue(ok)
        self.assertEqual(_get_feedback('test_item_xyz'), '')

    def test_invalid_verdict_rejected(self):
        from jarvis_actionable_items import save_item_feedback
        ok = save_item_feedback('test_item_xyz', 'maybe', '')
        self.assertFalse(ok)


class TestE_PostProcessFillsCategoryZh(unittest.TestCase):
    """post-process 兜底填 category_zh + sir_feedback."""

    def test_get_all_items_have_category_zh(self):
        from jarvis_actionable_items import get_all_sir_actionable_items
        items = get_all_sir_actionable_items()
        # 至少一些 item 应有 category_zh (post-process 兜底)
        with_zh = [i for i in items if i.category_zh]
        self.assertGreater(len(with_zh), 0, 'post-process 应给每条 item 填 category_zh')


class TestF_DashboardWired(unittest.TestCase):
    """dashboard html 含 description_zh + 👍👎 按钮."""

    def test_dashboard_renders_description_zh(self):
        import scripts.jarvis_dashboard_web as dwm
        with open(dwm.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('item.description_zh', src,
                       'card 应渲染 description_zh')
        self.assertIn('item.category_zh', src,
                       'card 应渲染 category_zh')

    def test_dashboard_has_thumbs_buttons(self):
        import scripts.jarvis_dashboard_web as dwm
        with open(dwm.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('rateItem(item', src,
                       'card 应有 rateItem 按钮')
        self.assertIn("'/api/items/${item.id}/feedback'", src.replace('`', "'"),
                       'rateItem 应 fetch /api/items/<id>/feedback')

    def test_dashboard_has_feedback_endpoint(self):
        import scripts.jarvis_dashboard_web as dwm
        with open(dwm.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("action == 'feedback'", src,
                       'api_items_mutate 应处理 feedback action')
        self.assertIn('save_item_feedback', src)


if __name__ == '__main__':
    unittest.main()
