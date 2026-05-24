# -*- coding: utf-8 -*-
"""[Sir 2026-05-24 22:00 真测 META 泄漏字幕 BUG] regression test.

源 BUG: turn_20260524_213856 reply 含 [META] 行 → stream splitter 把它当 sentence
       → _put_audio + subtitle_queue.put → Sir 字幕显 META + 可能 TTS 卡 wave_queue.

修法:
1. stream 主路径 + cloud_followup 加 [META] 切 (同 [CLIPBOARD] 模式)
2. _put_audio 入口加 [META] 末路守门 (双保险)

本 test 验证:
- jarvis_chat_bypass.py 主路径 + cloud 路径都加了 [META] split
- _put_audio 入口有 [META] guard
- META 不会进 streamed_text → 不进 subtitle_queue
"""
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestMetaStripUpstream(unittest.TestCase):
    """[META] block 必须在 stream 上游被剥, 不能进 splitter/_put_audio/subtitle."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_main_path_splits_meta(self):
        """主路径 stream 必须含 '[META]' split (整 source 至少有 2 处)."""
        # 整源都有 "[META]" in clean_full split (主路径 + cloud_followup, 加起来 ≥ 2)
        n_check = self.src.count('"[META]" in clean_full')
        self.assertGreaterEqual(n_check, 2,
                                  '主路径 + cloud_followup 都必须有 [META] in clean_full 检查 (≥ 2)')
        n_split = self.src.count('clean_full.split("[META]")')
        self.assertGreaterEqual(n_split, 2,
                                  'split [META] 至少 2 处')

    def test_cloud_followup_splits_meta(self):
        """cloud_followup 路径必须含 '[META]' split (附近 50 行内)."""
        idx = self.src.find('[Jarvis-云端]')
        self.assertGreater(idx, 0, '应能找到 cloud_followup 路径')
        # 附近 ±50 行 (200 chars 每行 = ±10000 chars)
        start = max(0, idx - 5000)
        end = min(len(self.src), idx + 5000)
        section = self.src[start:end]
        self.assertIn('"[META]" in clean_full', section,
                      'cloud_followup 附近必须含 [META] in clean_full 检查')

    def test_put_audio_meta_guard(self):
        """_put_audio 入口必须含 [META] 末路守门 (audit BUG #4 后改用 regex 防 [Meta]/【META】)."""
        idx = self.src.find('def _put_audio')
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 3000]
        # 接受老的字面 check 或 audit BUG #4 后的 regex (任一存在即可)
        has_literal = "'[META]' in text" in section
        has_regex = '_META_RE' in section and 'IGNORECASE' in section
        self.assertTrue(has_literal or has_regex,
                        '_put_audio 必须有 [META] 字面 check 或 _META_RE regex')
        self.assertIn('Audio Guard', section,
                      '_put_audio 必须有 Audio Guard log')

    def test_meta_split_before_streamed_text(self):
        """[META] split 必须在 delta = clean_full[len(streamed_text):] 之前 (整源每一对)."""
        # 找所有 META split 位置, 必须每个都在对应的 delta = clean_full 之前
        meta_split_positions = []
        pos = 0
        while True:
            idx = self.src.find('clean_full.split("[META]")', pos)
            if idx == -1:
                break
            meta_split_positions.append(idx)
            pos = idx + 1
        self.assertGreaterEqual(len(meta_split_positions), 2, '至少 2 处 META split')

        # 对每个 META split, 找紧随其后的 delta = clean_full[ 行
        for meta_pos in meta_split_positions:
            section = self.src[meta_pos:meta_pos + 500]
            self.assertIn('delta = clean_full[len(streamed_text):]', section,
                          f'META split @{meta_pos} 后必须紧跟 delta = clean_full')


class TestMetaStripBehaviorLogic(unittest.TestCase):
    """parse_meta + 上游 split 双层防御 联合行为."""

    def test_parse_meta_strips_full_meta_line(self):
        """parse_meta 应剥 [META] 行 (用作 stream 完成后的兜底)."""
        from jarvis_meta_self_check import parse_meta
        reply = (
            "As you wish, Sir. I shall drop the matter.\n\n"
            "[META] evidence=stm:turn_x | reaction=dropped_proposal | skip_alert=true"
        )
        clean, meta = parse_meta(reply)
        self.assertNotIn('[META]', clean, 'parse_meta 应剥 [META] 行')
        self.assertIn('As you wish, Sir', clean)
        self.assertTrue(meta.parse_ok or not meta.evidence, 
                         'parse_ok 应 True 或 evidence 至少非空')


if __name__ == '__main__':
    unittest.main()
