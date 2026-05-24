# -*- coding: utf-8 -*-
"""[Reshape M3.E / 2026-05-24] SoulRouter — Sir 灵魂章节路由 (中英双语桥 + ngram KL)

从 `jarvis_routing.py` 拆出 (M3.E completion).

# Purpose

Sir 的 "灵魂章节" = sir_profile.json 的 active_projects + skill_progression.
每段 chapter 提 ngram 频谱. STM context + 当前 cmd 也提 ngram. 用 KL divergence
找最匹配的 chapter, 让 prompt 注入相关 SOUL 段, 帮 Jarvis "懂 Sir 在说哪个项目".

# 准则 1 高效

纯 in-process ngram + KL, 不调 LLM. O(N) text length.

# 老路径兼容

`jarvis_routing.py` 仍 re-export `SoulRouter`, 老 caller `from jarvis_routing import SoulRouter`
不破.

# Public API

- `class SoulRouter(sir_profile: dict)`
- `.route(cmd: str, stm_context: str) -> list[str]`  # top-K chapter names
"""
from __future__ import annotations

import math
from typing import Dict, List

__all__ = ['SoulRouter']


class SoulRouter:
    BILINGUAL_BRIDGE = {
        "代码": "code", "编程": "coding", "项目": "project",
        "神经网络": "neural network", "重构": "refactor", "重构的": "refactor",
        "桌面": "desktop", "文件": "file", "部署": "deploy",
        "服务器": "server", "数据库": "database", "接口": "api",
        "测试": "test", "调试": "debug", "优化": "optimize",
        "配置": "config", "安装": "install", "更新": "update",
        "模型": "model", "训练": "train", "推理": "inference",
        "语音": "voice", "识别": "recognition", "唤醒": "wake",
        "记忆": "memory", "对话": "conversation", "回复": "reply",
    }

    def __init__(self, sir_profile: dict):
        self.chapters: Dict[str, Dict] = {}
        self._build_index(sir_profile)

    def _build_index(self, profile: dict):
        # [P0+20-β.2.4.3 / 2026-05-16] 老路径退役第 3 步: 删 inside_jokes / milestones
        # 两个 chapter (Layer 2 RelationalState 单源接管). projects/progression 仍读
        # sir_profile (Sir 画像范畴). 详 docs/JARVIS_SOUL_DRIVE.md
        chapters_def = {
            "projects": " ".join(profile.get("active_projects", [])),
            "progression": " ".join(
                s.get("skill", "") for s in profile.get("skill_progression", [])
            ),
        }
        for name, text in chapters_def.items():
            if not text.strip():
                continue
            freq = self._ngram_freq(text)
            total = sum(freq.values())
            if total > 0:
                self.chapters[name] = {
                    "freq": {w: c / total for w, c in freq.items()},
                }

    def _ngram_freq(self, text: str) -> dict:
        text = text.lower().strip()
        if not text:
            return {}

        freq: Dict[str, int] = {}
        i = 0
        while i < len(text):
            ch = text[i]
            if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff':
                if i + 1 < len(text) and (
                    '\u4e00' <= text[i + 1] <= '\u9fff' or '\u3040' <= text[i + 1] <= '\u30ff'
                ):
                    bigram = text[i:i + 2]
                    freq[bigram] = freq.get(bigram, 0) + 1
                    i += 2
                    continue
                else:
                    freq[ch] = freq.get(ch, 0) + 1
                    i += 1
                    continue

            if ch.isalpha():
                j = i
                while j < len(text) and text[j].isalpha():
                    j += 1
                word = text[i:j]
                if len(word) >= 2:
                    freq[word] = freq.get(word, 0) + 1
                    for k in range(len(word) - 2):
                        freq[word[k:k + 3]] = freq.get(word[k:k + 3], 0) + 1
                i = j
                continue

            i += 1

        return freq

    def _tokenize_context(self, text: str) -> dict:
        freq = self._ngram_freq(text)

        for cn_word, en_word in self.BILINGUAL_BRIDGE.items():
            if cn_word in text.lower():
                freq[en_word] = freq.get(en_word, 0) + 2
                for part in en_word.split():
                    freq[part] = freq.get(part, 0) + 1

        return freq

    def route(self, cmd: str, stm_context: str) -> List[str]:
        if not self.chapters:
            return []

        context_text = stm_context + " " + cmd
        ctx_freq = self._tokenize_context(context_text)
        ctx_total = sum(ctx_freq.values())
        if ctx_total == 0:
            return []

        ctx_dist = {w: c / ctx_total for w, c in ctx_freq.items()}

        scores: Dict[str, float] = {}
        for name, chapter in self.chapters.items():
            kl = 0.0
            overlap = 0
            for word, p_chapter in chapter["freq"].items():
                p_ctx = ctx_dist.get(word, 1e-9)
                if word in ctx_freq:
                    overlap += 1
                kl += p_chapter * math.log(p_chapter / p_ctx)

            if overlap == 0:
                scores[name] = float('inf')
            else:
                scores[name] = kl / math.log(overlap + 1)

        finite_scores = {k: v for k, v in scores.items() if v != float('inf')}
        if not finite_scores:
            return []

        total_inv = sum(1.0 / v for v in finite_scores.values())
        probs = {k: (1.0 / v) / total_inv for k, v in finite_scores.items()}

        entropy = -sum(p * math.log(p) for p in probs.values())
        max_entropy = math.log(len(probs))
        if max_entropy == 0:
            return []

        normalized_h = entropy / max_entropy

        if normalized_h > 0.8:
            return []
        elif normalized_h > 0.4:
            k = min(2, len(probs))
        else:
            k = 1

        ranked = sorted(probs.keys(), key=lambda x: probs[x], reverse=True)
        return ranked[:k]
