# -*- coding: utf-8 -*-
"""β.5.43-fix1 — Sir 18:11 真理: Jarvis 反复吹牛 (offer 没工具的事).

修法: 加 capability_boundary_judge directive (priority=10) +
       over_offer_called_out_judge directive (priority=11, 当 Sir 反讥时触发).
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestCapabilityBoundaryDirective(unittest.TestCase):
    def test_trigger_always_fires(self):
        from jarvis_directives import (
            _trigger_capability_boundary_judge, DirectiveContext,
        )
        ctx = DirectiveContext(current_hour=10, user_input='hi')
        self.assertTrue(_trigger_capability_boundary_judge(ctx),
            'capability_boundary_judge 应该 always-on')

    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='capability_boundary_judge'", src)
        self.assertIn('β.5.43-fix1', src)
        # priority 10 (顶级)
        idx = src.find("id='capability_boundary_judge'")
        block = src[idx:idx + 800]
        self.assertIn('priority=10', block)

    def test_vocab_json_has_entry(self):
        import json
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  encoding='utf-8') as f:
            v = json.load(f)
        ids = [d.get('id') for d in v.get('directives', [])]
        self.assertIn('capability_boundary_judge', ids)


class TestOverOfferCalledOutDirective(unittest.TestCase):
    def test_trigger_fires_on_callout_chinese(self):
        from jarvis_directives import (
            _trigger_over_offer_called_out, DirectiveContext,
        )
        for text in [
            '你别吹牛逼了',
            '又吹牛',
            '你做不到',
            '你没权限',
            '你哪有这能力',
            '你别假装',
        ]:
            ctx = DirectiveContext(current_hour=18, user_input=text)
            self.assertTrue(
                _trigger_over_offer_called_out(ctx),
                f'"{text}" 应该触发 over_offer_called_out',
            )

    def test_trigger_does_not_fire_on_normal(self):
        from jarvis_directives import (
            _trigger_over_offer_called_out, DirectiveContext,
        )
        for text in ['你好', '帮我看一下', '今天天气怎么样']:
            ctx = DirectiveContext(current_hour=18, user_input=text)
            self.assertFalse(
                _trigger_over_offer_called_out(ctx),
                f'"{text}" 不该触发',
            )

    def test_seed_in_directives_py(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn("id='over_offer_called_out_judge'", src)
        idx = src.find("id='over_offer_called_out_judge'")
        block = src[idx:idx + 800]
        self.assertIn('priority=11', block,
            'over_offer_called_out 必须 priority=11 (顶 — Sir 反讥时立刻看)')

    def test_vocab_json_has_entry(self):
        import json
        with open(os.path.join(ROOT, 'memory_pool', 'directives_vocab.json'),
                  encoding='utf-8') as f:
            v = json.load(f)
        ids = [d.get('id') for d in v.get('directives', [])]
        self.assertIn('over_offer_called_out_judge', ids)


class TestDirectiveTextHasExamples(unittest.TestCase):
    """confirm directive text 含 Sir 18:11 实测反例."""

    def test_capability_text_lists_examples(self):
        with open(os.path.join(ROOT, 'jarvis_directives.py'), encoding='utf-8') as f:
            src = f.read()
        # Sir 18:11 反例
        for example in [
            'Shall I swap the active API keys',  # Sir 17:35 BUG
            'monitoring the logs',  # Sir 18:11 BUG
            'permanently commit',  # Sir 18:11 BUG
        ]:
            self.assertIn(example, src, f'capability directive text 必须含反例 "{example}"')


if __name__ == '__main__':
    unittest.main()
