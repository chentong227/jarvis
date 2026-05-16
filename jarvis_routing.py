# -*- coding: utf-8 -*-
"""[P0+19-4 / 2026-05-16] Jarvis Routing — 路由 / 用户画像类

从 jarvis_nerve.py 拆出 4 个类（路由 / 偏好追踪 / 画像聚合）：

| Class                     | 用途                                              |
|---------------------------|---------------------------------------------------|
| SoulRouter                | 中英双语桥 + Sir 的"灵魂章节"路由 (项目/笑话/里程碑) |
| ContextRouter             | 上下文路由（多档分级 prompt tier 决策）             |
| ContentPreferenceTracker  | 内容偏好追踪（Sir 喜欢的 topic / 风格）            |
| ProfileCard               | 用户画像卡片（聚合各模块信息生成紧凑快照）            |

依赖：
- 标准库：time / json / re / threading / collections
- 通过 central_nerve 实例属性访问其他模块（无直接 import 依赖）

向后兼容：jarvis_nerve.py 用 `from jarvis_routing import ...` 转发。

注：P0+19-4 原 design doc 含 PromptCenter / GuardianCenter / CompanionCenter，
但它们引用大量待拆 Sentinel，产生循环依赖。推迟到 P0+19-6.f（sentinel 全拆完后）。
"""

from __future__ import annotations

import os  # [P0+19-final fix 4] ProfileCard._load_profile 用 os.path.join
import time
import json
import re
import math  # [P0+19-final fix 3]
import sys  # noqa: F401
import io  # noqa: F401
import random  # noqa: F401
import queue  # noqa: F401
import sqlite3  # noqa: F401
import hashlib  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
from collections import defaultdict, deque  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
from google.genai import types  # noqa: F401

__all__ = [
    'SoulRouter',
    'ContextRouter',
    'ContentPreferenceTracker',
    'ProfileCard',
]


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
        self.chapters = {}
        self._build_index(sir_profile)

    def _build_index(self, profile: dict):
        # [P0+20-β.2.4.3 / 2026-05-16] 老路径退役第 3 步：删 inside_jokes / milestones
        # 两个 chapter（Layer 2 RelationalState 单源接管）。projects/progression 仍读
        # sir_profile（Sir 画像范畴）。详 docs/JARVIS_SOUL_DRIVE.md
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

        freq = {}
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

    def route(self, cmd: str, stm_context: str) -> list:
        if not self.chapters:
            return []

        context_text = stm_context + " " + cmd
        ctx_freq = self._tokenize_context(context_text)
        ctx_total = sum(ctx_freq.values())
        if ctx_total == 0:
            return []

        ctx_dist = {w: c / ctx_total for w, c in ctx_freq.items()}

        scores = {}
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

class ContextRouter:
    def __init__(self, central_nerve):
        self.nerve = central_nerve

    def assemble(self, current_hour: int) -> str:
        blocks = []

        habit = self._route_habit(current_hour)
        if habit:
            blocks.append(habit)

        causal = self._route_causal()
        if causal:
            blocks.append(causal)

        project = self._route_project()
        if project:
            blocks.append(project)

        emotion = self._route_emotion()
        if emotion:
            blocks.append(emotion)

        prefs = self._route_preferences()
        if prefs:
            blocks.append(prefs)

        if not blocks:
            return ""

        return "=== CURRENT CONTEXT ===\n" + "\n".join(blocks)

    def _route_habit(self, current_hour: int) -> str:
        hc = self.nerve.habit_clock
        prediction = hc.predict_current_state()

        hints = []
        if prediction.get('focus_prediction') == 'high':
            hints.append("Peak focus window. Be maximally efficient.")
        elif prediction.get('focus_prediction') == 'low':
            hints.append("Low focus window. Sir may be open to conversation.")

        if prediction.get('anomaly_detected'):
            hints.append(f"Routine anomaly: {prediction.get('anomaly_detail', '')}")

        return " | ".join(hints) if hints else ""

    def _route_causal(self) -> str:
        patterns = self.nerve.causal_chain.detect_patterns()
        if not patterns:
            return ""
        return patterns[0][:150]

    def _route_project(self) -> str:
        summary = self.nerve.project_timeline.get_summary()
        if not summary:
            return ""
        lines = summary.split('\n')
        if len(lines) <= 1:
            return ""
        return lines[1][:120] if len(lines) > 1 else ""

    def _route_emotion(self) -> str:
        if not hasattr(self.nerve, 'status_ledger'):
            return ""
        ledger = self.nerve.status_ledger.current_ledger
        tone = ledger.get("emotional_tone", "Neutral")
        if tone in ("Neutral", "N/A"):
            return ""

        emotion_map = {
            "Frustrated": "EMOTION: Frustrated. Drop humor. Pure engineer.",
            "Stressed": "EMOTION: Stressed. Calm, concise.",
            "Tired": "EMOTION: Tired. Gentle, brief.",
            "Playful": "EMOTION: Playful. Mirror with dry wit.",
            "Excited": "EMOTION: Excited. Match enthusiasm.",
            "Curious": "EMOTION: Curious. Be thorough.",
            "Impatient": "EMOTION: Impatient. Skip pleasantries.",
        }
        directive = emotion_map.get(tone, "")
        signals = ledger.get("detected_stress_signals", [])
        if signals and len(signals) >= 2:
            directive += " Multiple stress signals. Prioritize stability."
        return directive

    def _route_preferences(self) -> str:
        if not hasattr(self.nerve, 'content_tracker'):
            return ""
        summary = self.nerve.content_tracker.get_preference_summary()
        if not summary:
            return ""
        return f"[Content Preferences] {summary}"

class ContentPreferenceTracker:
    """内容偏好追踪器：从窗口标题中提取Sir的媒体/工具消费偏好
    
    追踪维度：
    - 媒体平台偏好 (斗鱼/B站/YouTube等)
    - 内容类型偏好 (直播/视频/音乐等)
    - 工具使用偏好 (IDE/剪辑/设计等)
    - 突发行为检测 (突然切换内容类型)
    - 长期偏好热力图
    
    所有数据纯本地计算，零API调用。
    """
    
    MEDIA_PLATFORMS = {
        'douyu': '斗鱼直播', '斗鱼': '斗鱼直播',
        'bilibili': 'B站', 'bilibili.com': 'B站',
        'youtube': 'YouTube', 'youtube.com': 'YouTube',
        'twitch': 'Twitch', 'twitch.tv': 'Twitch',
        'netflix': 'Netflix',
        'iqiyi': '爱奇艺', '爱奇艺': '爱奇艺',
        'qqmusic': 'QQ音乐', '网易云': '网易云音乐',
        'spotify': 'Spotify',
    }
    
    TOOL_PLATFORMS = {
        'trae': 'Trae IDE', 'cursor': 'Cursor', 'pycharm': 'PyCharm',
        'vscode': 'VS Code', 'visual studio code': 'VS Code',
        'premiere': 'Premiere Pro', 'photoshop': 'Photoshop',
        'obs': 'OBS Studio', 'terminal': 'Terminal', 'powershell': 'PowerShell',
        'explorer': 'File Explorer', 'chrome': 'Chrome',
    }
    
    def __init__(self):
        self.media_heatmap = {}
        self.tool_heatmap = {}
        self.session_log = []
        self._last_category = None
        self._category_switch_time = time.time()
        self._sudden_switches = []
        self._response_quality = []
        self._interaction_count = 0
    
    def tick(self):
        """每个探测周期调用一次，更新偏好热力图"""
        title = PhysicalEnvironmentProbe.current_window_title.lower() if PhysicalEnvironmentProbe.current_window_title else ''
        proc = PhysicalEnvironmentProbe.current_process_name.lower() if PhysicalEnvironmentProbe.current_process_name else ''
        cat = PhysicalEnvironmentProbe.current_work_category
        
        detected_media = self._detect_media(title, proc)
        detected_tool = self._detect_tool(title, proc)
        
        if detected_media:
            self.media_heatmap[detected_media] = self.media_heatmap.get(detected_media, 0) + 1
        
        if detected_tool:
            self.tool_heatmap[detected_tool] = self.tool_heatmap.get(detected_tool, 0) + 1
        
        if cat != self._last_category and self._last_category is not None:
            switch = {
                'time': time.strftime('%H:%M:%S'),
                'from': self._last_category,
                'to': cat,
                'media': detected_media,
                'tool': detected_tool,
            }
            self.session_log.append(switch)
            if len(self.session_log) > 200:
                self.session_log = self.session_log[-200:]
            
            if self._is_sudden_switch(switch):
                self._sudden_switches.append(switch)
                if len(self._sudden_switches) > 20:
                    self._sudden_switches = self._sudden_switches[-20:]
        
        self._last_category = cat
    
    def _detect_media(self, title: str, proc: str) -> str:
        for kw, name in self.MEDIA_PLATFORMS.items():
            if kw in title or kw in proc:
                return name
        return ''
    
    def _detect_tool(self, title: str, proc: str) -> str:
        for kw, name in self.TOOL_PLATFORMS.items():
            if kw in title or kw in proc:
                return name
        return ''
    
    def _is_sudden_switch(self, switch: dict) -> bool:
        from_cat = switch.get('from', '')
        to_cat = switch.get('to', '')
        
        sudden_pairs = [
            ('Coding', 'Media'),
            ('Media', 'Coding'),
            ('AFK', 'Coding'),
            ('Coding', 'AFK'),
        ]
        
        for a, b in sudden_pairs:
            if a in from_cat and b in to_cat:
                return True
        
        return False
    
    def get_top_media(self, n: int = 3) -> list:
        sorted_media = sorted(self.media_heatmap.items(), key=lambda x: x[1], reverse=True)
        return [(name, count) for name, count in sorted_media[:n] if count >= 3]
    
    def get_top_tools(self, n: int = 3) -> list:
        sorted_tools = sorted(self.tool_heatmap.items(), key=lambda x: x[1], reverse=True)
        return [(name, count) for name, count in sorted_tools[:n] if count >= 3]
    
    def get_recent_sudden_switches(self, n: int = 3) -> list:
        return self._sudden_switches[-n:]
    
    def get_preference_summary(self) -> str:
        parts = []
        
        top_media = self.get_top_media(3)
        if top_media:
            media_str = ', '.join([f"{name}({count})" for name, count in top_media])
            parts.append(f"Media: {media_str}")
        
        top_tools = self.get_top_tools(3)
        if top_tools:
            tools_str = ', '.join([f"{name}({count})" for name, count in top_tools])
            parts.append(f"Tools: {tools_str}")
        
        recent_switches = self.get_recent_sudden_switches(3)
        if recent_switches:
            switch_strs = [f"{s['from']}→{s['to']}" for s in recent_switches]
            parts.append(f"Recent switches: {', '.join(switch_strs)}")
        
        return ' | '.join(parts) if parts else ''

    def detect_implicit_feedback(self, user_input: str, prev_user: str = "", prev_jarvis: str = "") -> dict:
        if not user_input:
            return None

        input_lower = user_input.lower().strip()

        correction_patterns = [
            (r"\b(?:no|nope|not|不对|不是|错了|don't|doesn't|isn't)\b", "correction"),
            (r"\b(?:what\?|huh\?|啥|什么\?|pardon|excuse me\?)\b", "confusion"),
            (r"\b(?:thanks|thank you|谢谢|perfect|exactly|great|good|nice)\b", "positive"),
            (r"\b(?:go on|continue|然后|接着|and then|what else)\b", "follow_up"),
            (r"\b(?:ignore|skip|never mind|算了|不管|别管)\b", "dismiss"),
        ]

        for pattern, fb_type in correction_patterns:
            if re.search(pattern, input_lower):
                return {
                    'type': fb_type,
                    'user_input': user_input[:200],
                    'prev_jarvis': (prev_jarvis or '')[:200],
                    'timestamp': time.time()
                }

        if len(user_input) < 5 and prev_jarvis and len(prev_jarvis) > 100:
            return {
                'type': 'short_response',
                'user_input': user_input[:200],
                'prev_jarvis': prev_jarvis[:200],
                'timestamp': time.time()
            }

        return None

    def record_feedback(self, feedback: dict, user_input: str = "", jarvis_response: str = ""):
        if not feedback:
            return
        fb_type = feedback.get('type', '')
        if fb_type in ('correction', 'confusion', 'dismiss'):
            self._response_quality.append(('negative', time.time()))
        elif fb_type == 'positive':
            self._response_quality.append(('positive', time.time()))

    def record_interaction(self, user_input: str, jarvis_response: str):
        if not hasattr(self, '_response_quality'):
            self._response_quality = []
        if not hasattr(self, '_interaction_count'):
            self._interaction_count = 0
        self._interaction_count += 1

        if len(user_input) < 5 and jarvis_response and len(jarvis_response) > 200:
            self._response_quality.append(('verbose', time.time()))

    def get_preferred_style(self) -> str:
        if not hasattr(self, '_response_quality'):
            return ""
        recent = [s for s in self._response_quality[-20:] if time.time() - s[1] < 3600]
        if not recent:
            return ""
        neg = sum(1 for s in recent if s[0] in ('negative', 'verbose'))
        pos = sum(1 for s in recent if s[0] == 'positive')
        total = len(recent)
        if total < 3:
            return ""
        if neg > pos:
            return "[STYLE PREFERENCE]: Sir prefers concise, direct responses. Avoid verbosity."
        elif pos > neg:
            return "[STYLE PREFERENCE]: Sir responds well to thorough, detailed answers."
        return ""


class ProfileCard:
    """用户画像卡片：聚合所有模块信息，生成紧凑、LLM友好的用户快照
    
    设计原则：
    - 每个字段都有来源模块标注，可追溯
    - 支持被其他模块动态修正（贝叶斯双向修正）
    - 输出格式紧凑，适合注入Prompt
    - 缓存30秒，避免高频重建
    """
    
    def __init__(self, central_nerve):
        self.nerve = central_nerve
        self._cache = {}
        self._cache_time = 0
        self._cache_ttl = 30
        
        self._correction_weights = {
            'habit_clock': 0.30,
            'status_ledger': 0.25,
            'causal_chain': 0.20,
            'physical_probe': 0.15,
            'soul_archivist': 0.10,
        }
    
    def snapshot(self) -> dict:
        now = time.time()
        if now - self._cache_time < self._cache_ttl and self._cache:
            return self._cache
        
        card = {
            "_generated_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "identity": self._build_identity(),
            "current_state": self._build_current_state(),
            "behavioral_patterns": self._build_behavioral_patterns(),
            "content_preferences": self._build_content_preferences(),
            "likes_and_boundaries": self._build_likes_boundaries(),
            "active_projects": self._build_active_projects(),
            "recent_narrative": self._build_recent_narrative(),
            "_corrections": self._get_corrections_log(),
        }
        
        self._cache = card
        self._cache_time = now
        return card
    
    def to_prompt_block(self, max_chars: int = 800) -> str:
        # 🩹 [P0+20-β.1.20 / 2026-05-16] profile_block 瘦身（PROMPT_REFACTOR_PLAN §3 L1 压缩）：
        # 原 ~1500 chars 全量注入，每轮 prompt 都背一遍 → 性价比低。
        # 优化：① 每段 trimming（recent narrative/boundaries/habit/anomaly 各 ≤ 200 chars）
        #      ② 总长度硬上限 max_chars=800（按重要性顺序截断，identity/now 永远保留）
        card = self.snapshot()
        lines = ["=== SIR PROFILE CARD ==="]

        # 优先级：identity/now > habit/anomaly > preferences/projects > narrative/boundaries
        identity = card.get("identity", {})
        if identity:
            lines.append(f"[Identity] {(identity.get('core_traits', '') or '')[:200]}")
            lines.append(f"[Rhythm] {(identity.get('work_rhythm', '') or '')[:150]}")

        state = card.get("current_state", {})
        if state:
            _now = (
                f"[Now] {state.get('activity', '')} | Mood: {state.get('emotional_tone', '')} | "
                f"Focus: {state.get('focus_level', '')} | Session: {state.get('session_duration', '')}"
            )
            lines.append(_now[:250])

        patterns = card.get("behavioral_patterns", {})
        if patterns:
            habit_line = (patterns.get('current_habit_context', '') or '')[:160]
            if habit_line:
                lines.append(f"[Habit] {habit_line}")
            anomaly = (patterns.get('anomaly', '') or '')[:120]
            if anomaly:
                lines.append(f"[Anomaly] {anomaly}")

        prefs = card.get("content_preferences", {})
        if prefs:
            pref_parts = []
            if prefs.get('frequent_media'):
                pref_parts.append(f"Media: {str(prefs['frequent_media'])[:80]}")
            if prefs.get('frequent_tools'):
                pref_parts.append(f"Tools: {str(prefs['frequent_tools'])[:80]}")
            if pref_parts:
                lines.append(f"[Preferences] {' | '.join(pref_parts)}")

        projects = card.get("active_projects", [])
        if projects:
            lines.append(f"[Projects] {', '.join(str(p)[:40] for p in projects[:5])}")

        narrative = (card.get("recent_narrative", '') or '')[:200]
        if narrative:
            lines.append(f"[Recent] {narrative}")

        lb = card.get("likes_and_boundaries", {})
        if lb:
            boundaries = (lb.get('boundaries', '') or '')[:160]
            if boundaries:
                lines.append(f"[Boundaries] {boundaries}")

        out = '\n'.join(lines)
        if max_chars and len(out) > max_chars:
            out = out[:max_chars - 12].rstrip() + '\n…[truncated]'
        return out
    
    def _build_identity(self) -> dict:
        profile = self._load_profile()
        core_traits = profile.get('core_philosophy', '')[:150]
        work_rhythm = profile.get('work_rhythms', '')
        
        hc = self.nerve.habit_clock
        if hc:
            prediction = hc.predict_current_state()
            if prediction.get('focus_prediction') == 'high':
                work_rhythm += ' | NOW: Peak focus confirmed.'
            elif prediction.get('focus_prediction') == 'low':
                work_rhythm += ' | NOW: Low focus confirmed.'
        
        return {
            'core_traits': core_traits,
            'work_rhythm': work_rhythm[:200],
            'idiosyncrasies': profile.get('idiosyncrasies', '')[:150],
        }
    
    def _build_current_state(self) -> dict:
        cat = PhysicalEnvironmentProbe.current_work_category
        proc = PhysicalEnvironmentProbe.current_process_name
        dur = PhysicalEnvironmentProbe.work_duration_minutes
        
        activity = f"{cat}"
        if proc and proc != "Unknown":
            activity += f" ({proc})"
        
        emotional_tone = "Neutral"
        cognitive_load = "Unknown"
        if hasattr(self.nerve, 'status_ledger'):
            ledger = self.nerve.status_ledger.current_ledger
            emotional_tone = ledger.get('emotional_tone', 'Neutral')
            cognitive_load = ledger.get('human_cognitive_load', 'Unknown')
        
        focus_level = "normal"
        hc = self.nerve.habit_clock
        if hc:
            prediction = hc.predict_current_state()
            focus_level = prediction.get('focus_prediction', 'normal')
        
        session_duration = f"{int(dur)}min" if dur > 0 else "just started"
        
        return {
            'activity': activity,
            'emotional_tone': emotional_tone,
            'cognitive_load': cognitive_load,
            'focus_level': focus_level,
            'session_duration': session_duration,
            'physical_state': PhysicalEnvironmentProbe.current_physical_state,
        }
    
    def _build_behavioral_patterns(self) -> dict:
        result = {}
        
        hc = self.nerve.habit_clock
        if hc:
            summary = hc.get_llm_enhanced_summary()
            if summary:
                result['current_habit_context'] = summary[:200]
            
            prediction = hc.predict_current_state()
            if prediction.get('anomaly_detected'):
                result['anomaly'] = prediction.get('anomaly_detail', '')
        
        cc = self.nerve.causal_chain
        if cc:
            patterns = cc.detect_patterns()
            if patterns:
                result['causal_patterns'] = patterns[:3]
        
        return result
    
    def _build_content_preferences(self) -> dict:
        result = {}
        
        if hasattr(self.nerve, 'content_tracker'):
            ct = self.nerve.content_tracker
            top_media = ct.get_top_media(3)
            if top_media:
                result['frequent_media'] = ', '.join([f"{name}({count})" for name, count in top_media])
            
            top_tools = ct.get_top_tools(3)
            if top_tools:
                result['frequent_tools'] = ', '.join([f"{name}({count})" for name, count in top_tools])
            
            sudden = ct.get_recent_sudden_switches(3)
            if sudden:
                result['recent_switches'] = [f"{s['from']}→{s['to']} ({s['time']})" for s in sudden]
        
        return result
    
    def _build_likes_boundaries(self) -> dict:
        # [P0+20-β.2.4.3 / 2026-05-16] inside_jokes_count 字段已废弃（Layer 2 单源），
        # 不再读 our_inside_jokes。仍保留 boundaries（Sir 画像范畴）。
        profile = self._load_profile()
        return {
            'boundaries': profile.get('conversational_boundaries', '')[:200],
        }
    
    def _build_active_projects(self) -> list:
        profile = self._load_profile()
        profile_projects = profile.get('active_projects', [])
        
        pt = self.nerve.project_timeline
        if pt:
            timeline_projects = pt.get_active_projects(min_duration=5)
            timeline_names = [p['name'] for p in timeline_projects[:5]]
            all_projects = []
            seen = set()
            for p in profile_projects[:5]:
                if p not in seen:
                    all_projects.append(p)
                    seen.add(p)
            for p in timeline_names:
                if p not in seen:
                    all_projects.append(p)
                    seen.add(p)
            return all_projects[:8]
        
        return profile_projects[:5]
    
    def _build_recent_narrative(self) -> str:
        if hasattr(self.nerve, 'status_ledger'):
            summaries = self.nerve.status_ledger.get_recent_daily_summaries(days=2)
            if summaries:
                return summaries[:300]
        return ''
    
    def _get_corrections_log(self) -> list:
        if not hasattr(self.nerve, '_profile_corrections'):
            self.nerve._profile_corrections = []
        return self.nerve._profile_corrections[-5:]
    
    def apply_correction(self, source_module: str, field: str, old_value, new_value, confidence: float):
        weight = self._correction_weights.get(source_module, 0.1)
        effective_confidence = confidence * weight

        dedup_key = f"{source_module}:{field}:{str(new_value)[:80]}"
        now = time.time()
        if not hasattr(self, '_correction_dedup'):
            self._correction_dedup = {}

        if dedup_key in self._correction_dedup:
            last_time, last_conf = self._correction_dedup[dedup_key]
            if now - last_time < 300 and abs(effective_confidence - last_conf) < 0.05:
                return

        self._correction_dedup[dedup_key] = (now, effective_confidence)
        stale_keys = [k for k, v in self._correction_dedup.items() if now - v[0] > 600]
        for k in stale_keys:
            del self._correction_dedup[k]
        
        correction = {
            'time': time.strftime('%H:%M:%S'),
            'source': source_module,
            'field': field,
            'old': str(old_value)[:100],
            'new': str(new_value)[:100],
            'confidence': round(effective_confidence, 3),
        }
        
        if not hasattr(self.nerve, '_profile_corrections'):
            self.nerve._profile_corrections = []
        self.nerve._profile_corrections.append(correction)
        if len(self.nerve._profile_corrections) > 50:
            self.nerve._profile_corrections = self.nerve._profile_corrections[-50:]
        
        self._cache_time = 0
        
        if effective_confidence >= 0.30:
            print(f"[ProfileCard] 贝叶斯修正: {source_module} → {field} (置信度: {effective_confidence:.2f})")
    
    def _load_profile(self) -> dict:
        import json as _json
        profile_file = os.path.join("jarvis_config", "sir_profile.json")
        if os.path.exists(profile_file):
            try:
                with open(profile_file, 'r', encoding='utf-8') as f:
                    return _json.load(f)
            except:
                pass
        return {}




# ============================================================================
# [P0+19-6.f / 2026-05-16] 三 Center —— Prompt/Guardian/Companion 调度中心
# ============================================================================
# 从 jarvis_nerve.py 拆出（依赖大量 sentinel，所以排在 sentinel 全拆完后做）

# 跨文件依赖：使用延迟 import 避免循环（routing 早于 sentinel/conductor 加载）
def _resolve_center_deps():
    """延迟解析三 Center 用到的所有跨模块依赖。
    
    返回一个 dict 含所有需要的类。三 Center 的 start_all 方法调用本函数。
    """
    from jarvis_sentinels import (
        SoulArchivistSentinel, ReflectionScheduler, ScreenshotSentinel,
        WellnessGuardian, NudgeGate,
    )
    from jarvis_conductor import Conductor
    from jarvis_return_sentinel import ReturnSentinel
    from jarvis_commitment_watcher import CommitmentWatcher
    from jarvis_smart_nudge import SmartNudgeSentinel
    from jarvis_memory_core import Anticipator
    try:
        from jarvis_enhanced import ProactiveShield
    except ImportError:
        ProactiveShield = None
    return {
        'SoulArchivistSentinel': SoulArchivistSentinel,
        'ReflectionScheduler': ReflectionScheduler,
        'ScreenshotSentinel': ScreenshotSentinel,
        'WellnessGuardian': WellnessGuardian,
        'NudgeGate': NudgeGate,
        'Conductor': Conductor,
        'ReturnSentinel': ReturnSentinel,
        'CommitmentWatcher': CommitmentWatcher,
        'SmartNudgeSentinel': SmartNudgeSentinel,
        'Anticipator': Anticipator,
        'ProactiveShield': ProactiveShield,
    }


# 三 Center 类内部对 SoulArchivistSentinel / Anticipator / Conductor / ... 的引用
# 通过 module-level 注入解析（在 start_all 第一次调用时填充全局名字空间）
_centers_deps_loaded = False
def _ensure_centers_deps():
    global _centers_deps_loaded
    if _centers_deps_loaded:
        return
    deps = _resolve_center_deps()
    g = globals()
    for name, cls in deps.items():
        if cls is not None:
            g[name] = cls
    _centers_deps_loaded = True


class PromptCenter:
    """Prompt 注入调度中心：管理所有不发声的上下文注入模块
    
    职责：提高贾维斯懂 Sir 的能力，纯数据注入，零主动发声
    下属模块：
    - HabitClock: 行为模式提取（免费）
    - SoulArchivistSentinel: 灵魂画像提纯（flash-lite）
    - Anticipator: 记忆预加载（免费）
    - ReflectionScheduler: LLM 反思调度（flash-lite/flash）
    """
    def __init__(self, key_router, central_nerve):
        self.key_router = key_router
        self.central_nerve = central_nerve
        # [C1-4 / 2026-05-15] PromptCenter.habit_clock 死代码清扫：
        # 全工程零外部读取（grep prompt_center.habit_clock = 0 命中）；
        # 业务统一走 CentralNerve.habit_clock。删除孤立实例避免 confusion。
        self.soul_archivist = None
        self.anticipator = None
        self.reflection_scheduler = None

    def start_all(self):
        _ensure_centers_deps()
        self.soul_archivist = SoulArchivistSentinel(
            key_router=self.key_router, central_nerve=self.central_nerve)
        self.soul_archivist.start()

        self.anticipator = Anticipator(self.central_nerve)
        self.anticipator.start()

        self.reflection_scheduler = ReflectionScheduler(self.central_nerve)
        self.reflection_scheduler.start()
        self.central_nerve.reflection_scheduler = self.reflection_scheduler

        print("[PromptCenter] 上下文注入中心就绪 (HabitClock + SoulArchivist + Anticipator + ReflectionScheduler)")


class GuardianCenter:
    """异常介入调度中心：检测异常事件并主动介入
    
    职责：发现 Sir 遇到问题/异常时主动提供帮助
    下属模块：
    - Conductor: 传感器融合 + 规则/LLM 决策
    - ProactiveShield: 效率断崖检测（rapid_alt_tab + error_loop） → _shield_alert
    - WellnessGuardian: 生理节律监控 → _wellness_alert
    - ReturnSentinel: AFK 归来感知（含早晨首次活跃问候）
    - CommitmentWatcher: 承诺监督
    
    注：ProactiveCompanion 已停用 —— morning_greeting 由 ReturnSentinel 接管，
        work_switch 由 SmartNudgeSentinel.flow_end 接管，breath_check 与
        JARVIS 管家人设不符（管家不做周期性情感关怀）。
    """
    def __init__(self, jarvis_worker, nudge_gate: NudgeGate):
        self.worker = jarvis_worker
        self.gate = nudge_gate
        self.conductor = None
        self.return_sentinel = None
        self.commitment_watcher = None
        self.wellness_guardian = None
        self.proactive_shield = None

    def start_all(self):
        _ensure_centers_deps()
        self.conductor = Conductor(self.worker, nudge_gate=self.gate)
        self.conductor.start()
        self.worker.conductor = self.conductor

        self.return_sentinel = ReturnSentinel(self.worker, nudge_gate=self.gate)
        self.return_sentinel.start()
        self.worker.return_sentinel = self.return_sentinel

        self.commitment_watcher = CommitmentWatcher(self.worker, nudge_gate=self.gate)
        self.commitment_watcher.start()
        self.worker.commitment_watcher = self.commitment_watcher

        self.wellness_guardian = WellnessGuardian(central_nerve=self.worker)
        self.wellness_guardian.start()

        # 🛡️ 接通效率断崖哨兵：检测 alt-tab 频繁切换 + 同一报错页面卡 5 分钟
        # self.worker 是 CentralNerve 实例（参照 WellnessGuardian 同款约定）
        self.proactive_shield = ProactiveShield(central_nerve=self.worker)
        self.proactive_shield.start()
        self.worker.proactive_shield = self.proactive_shield

        print("[GuardianCenter] 异常干预中心就绪 (Conductor + ReturnSentinel + CommitmentWatcher + WellnessGuardian + ProactiveShield)")


class CompanionCenter:
    """日常关怀调度中心：日常陪伴和轻量关怀
    
    职责：让 Jarvis 更有人情味，日常轻推
    下属模块：
    - SmartNudgeSentinel: 智能轻推（喝水/拉伸/深夜/氛围/屏幕调侃/午后/心流结束/休眠项目/晨报/晚间/周末）
    """
    def __init__(self, jarvis_worker, nudge_gate: NudgeGate, humor_memory=None):
        self.worker = jarvis_worker
        self.gate = nudge_gate
        # [P0+14 / 2026-05-15] HumorMemory 共享单例 —— main 段会传一个进来
        self.humor_memory = humor_memory
        self.smart_nudge = None

    def start_all(self):
        _ensure_centers_deps()
        # [P0+14 / 2026-05-15] 把共享 humor_memory 注入 SmartNudge，避免双实例状态不同步
        self.smart_nudge = SmartNudgeSentinel(
            self.worker,
            nudge_gate=self.gate,
            humor_memory=self.humor_memory,
        )
        self.smart_nudge.start()

        print("[CompanionCenter] 日常陪伴中心就绪 (SmartNudgeSentinel)")


# [P0+19-final fix 5 / 2026-05-16] 全量跨模块类引用兜底（try/except 防循环依赖）
try:
    from jarvis_safety import *  # noqa: F401, F403
except Exception:
    pass
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except Exception:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except Exception:
    pass
try:
    from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
except Exception:
    pass
try:
    from jarvis_sensors import (  # noqa: F401
        FunnelLogger, SensorFilter, HabitClock, CausalChain,
        ProjectTimeline, SubconsciousMailbox,
    )
except Exception:
    pass
try:
    from jarvis_routing import (  # noqa: F401
        SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard,
        PromptCenter, GuardianCenter, CompanionCenter,
    )
except Exception:
    pass
try:
    from jarvis_memory_core import (  # noqa: F401
        PromptLayer, PromptCache, CorrectionEntry, CorrectionMemory,
        MemoryFragment, UnifiedMemoryGateway, FeedbackTracker,
        TaskWorkerPool, Anticipator, CorrectionLoop, SleepIntentDetector,
        HumorMemory,
    )
except Exception:
    pass
try:
    from jarvis_sentinels import (  # noqa: F401
        ChronosTick, ChronosSentinel, SystemSentinel, SoulArchivistSentinel,
        NudgeGate, UserStatusLedgerSentinel, ScreenshotSentinel,
        WellnessGuardian, ReflectionScheduler,
    )
except Exception:
    pass
try:
    from jarvis_conductor import Conductor  # noqa: F401
except Exception:
    pass
try:
    from jarvis_return_sentinel import ReturnSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_commitment_watcher import CommitmentWatcher  # noqa: F401
except Exception:
    pass
try:
    from jarvis_smart_nudge import SmartNudgeSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS  # noqa: F401
except Exception:
    pass
try:
    from jarvis_blood import (  # noqa: F401
        JarvisBlood, ExecutionResult, FeedbackSignal, Action, PerceptionData, TaskSnapshot,
    )
except Exception:
    pass
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except Exception:
    pass
try:
    from jarvis_vocal_cord import VocalCord  # noqa: F401
except Exception:
    pass
try:
    from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401
except Exception:
    pass
try:
    from jarvis_skill_registry import (  # noqa: F401
        SkillRegistry, SkillManifest, OfferGuard, PromiseExecutor, PromiseActivator,
        get_registry,
    )
except Exception:
    pass
try:
    from l1_right_brain import RightBrain  # noqa: F401
except Exception:
    pass
try:
    from l3_left_brain import LeftBrain  # noqa: F401
except Exception:
    pass
try:
    from l5_reflection_brain import ReflectionBrain  # noqa: F401
except Exception:
    pass
try:
    from jarvis_utils import (  # noqa: F401
        bg_log, set_conversation_active, is_conversation_active,
        register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
        safe_gemini_call, safe_openrouter_call, create_genai_client,
        get_local_fallback, QuickClassifier, get_quick_classifier,
        ConversationEventBus, JarvisState, PlanLedger, WorkingMemoryFeed,
        SessionDigest, ToneSelector, AntiCommonPhraseTracker,
        VerbosityPreferenceTracker, ProjectContextProbe,
        ClipboardWatcher, PSHistoryWatcher, AttentionSlot,
        render_yesterday_block, render_open_threads_block,
        render_active_reminders_block, render_attention_block,
        render_silent_nudge_text, render_project_block,
        extract_open_threads, capture_attention_snapshot,
        resolve_nudge_channel, network_retry, get_rate_limiter,
        get_default_attention_slot, get_default_event_bus,
        get_default_phrase_tracker, get_default_plan_ledger,
        get_default_tone_selector, get_default_verbosity_tracker,
        get_default_working_feed,
    )
except Exception:
    pass

