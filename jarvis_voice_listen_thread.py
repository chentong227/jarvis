# -*- coding: utf-8 -*-
"""[Reshape M6.W1 / 2026-05-24 17:50] VoiceListenThread 抽出独立模块.

历史: 跟 JarvisWorkerThread 同住 jarvis_worker.py 5888 行. M6.W1 god file 拆 W1 启动:
VoiceListenThread + _WAKE_FILLER_* helpers 抽到独立文件 (1340 行).

向后兼容: jarvis_worker.py 顶部 re-export VoiceListenThread, 老 rom jarvis_worker import VoiceListenThread 仍 work.
"""
from __future__ import annotations

import os
import sys
import io
import re
import time
import json
import math
import random
import threading
import collections
from collections import defaultdict, deque
from typing import List, Dict, Any, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal

import numpy as np
import soundfile as sf
import win32gui
import win32api
import win32con
import speech_recognition as sr
from fuzzywuzzy import fuzz
import comtypes
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation

from jarvis_safety import *
from jarvis_env_probe import PhysicalEnvironmentProbe
from jarvis_utils import bg_log, set_conversation_active, is_conversation_active
# 🆕 [Reshape M6.W8 / 2026-05-24 19:20] noise floor helper
from jarvis_worker_helpers import compute_adaptive_noise_threshold
# 🚨 [BUG-X HOTFIX / 2026-05-24 19:25] M6.W1 抽 VoiceListenThread 时漏的 import
# 13 处用 set_browser_ducking 都靠 NameError 失败 → Audio Nerve 断连. 修.
from jarvis_central_nerve import set_browser_ducking

_WAKE_FILLER_CACHE: list = []
_WAKE_FILLER_MTIME: float = 0.0
_WAKE_FILLER_SEED = [
    r'\bhey\b', r'\bhi\b', r'\bhiya\b', r'\byo\b', r'\boi\b',
    r'\bhello\b', r'\bhallo\b', r'\bhola\b', r'\bok\b', r'\bokay\b',
    r'嘿', r'喂', r'嗨', r'哟', r'哎', r'唉', r'喔', r'噢', r'哈喽', r'哈罗',
]


def _load_wake_filler_vocab() -> list:
    """读 memory_pool/wake_filler_vocab.json + mtime cache.
    失败 fallback 用 hardcoded SEED (跟老 β.5.11 list 同).
    """
    global _WAKE_FILLER_CACHE, _WAKE_FILLER_MTIME
    import json as _json
    import os as _os
    path = _os.path.join('memory_pool', 'wake_filler_vocab.json')
    try:
        mt = _os.path.getmtime(path)
        if mt == _WAKE_FILLER_MTIME and _WAKE_FILLER_CACHE:
            return _WAKE_FILLER_CACHE
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        words = data.get('filler_words') or []
        words = [w for w in words if isinstance(w, str) and w.strip()]
        if not words:
            return _WAKE_FILLER_SEED
        _WAKE_FILLER_CACHE = words
        _WAKE_FILLER_MTIME = mt
        return words
    except Exception:
        return _WAKE_FILLER_SEED


class VoiceListenThread(QThread):
    text_ready = pyqtSignal(str)
    interrupt_signal = pyqtSignal()
    awake_signal = pyqtSignal(bool) 
    
    # [R6/B5] 拆成"硬指令"+"次硬指令"两档：
    # - STRICT_STOP_WORDS: 即便句子稍长（如"你给我闭嘴"）也立刻触发
    # - SOFT_STOP_WORDS:  容易和正常陈述歧义（如"安静"），必须在首位且短句才触发
    # 注意"安静"从硬档移除 —— "外面很安静" 不应误炸为强制停止。
    # 🆕 [P5-fix37 / 2026-05-23 12:15] PAUSE_ONLY_WORDS — 暂停语气词
    # Sir 12:13 真痛点: Sir 说 "嗯, 那稍等一下, 我去把这部分能力修复一下,
    # 待会再帮我寄" — STRICT_STOP_WORDS 含 "稍等一下" + head=8 命中 → 触发 dismiss
    # mute 30s + standby. Sir 反应 "欸欸欸? 错了! 错了!". Sir 真意是**承前对话**,
    # 不是真离场. 治本: 暂停语气词 (稍等/等一下/wait a moment/hold on) 移到
    # PAUSE_ONLY_WORDS, 仅整句**完全等于**才触发 (即 Sir 单独说 "稍等一下"). 句子
    # 含更多内容 → Sir 在继续上下文, 不算 dismiss.
    PAUSE_ONLY_WORDS = [
        "稍等一下", "等一下", "稍等", "等等",
        "wait a moment", "hold on", "wait a sec", "wait a second",
    ]
    STRICT_STOP_WORDS = [
        "停止", "终止", "别弄了", "退下", "闭嘴", "shut up", "stand down",
        # 🩹 [β.2.7.10 / 2026-05-17] Sir 焦点退出痛点: 显式 dismiss 立刻 mute
        # 让 Sir 不用小心翼翼避免说话被录入
        "好的就这样", "就这样吧", "ok that's all", "thats all",
        "我去打电话", "i am taking a call", "i'm taking a call",
        "我在打电话", "on a call", "im taking a call", "taking a call",
        "我跟别人说话", "我和别人说话", "我和我妈说话", "我跟我妈说话",
        "我和我爸说话", "我跟我爸说话", "和别人说话呢",
        # 注意: "稍等一下" / "等一下" / "wait a moment" / "hold on" 已移到
        # PAUSE_ONLY_WORDS (P5-fix37) — 这 4 个词容易在承前对话中误触发.
    ]
    SOFT_STOP_WORDS = ["安静", "shut"]
    # 兼容字段：保持外部访问 STOP_WORDS 的旧调用不挂（合并所有词）
    STOP_WORDS = STRICT_STOP_WORDS + SOFT_STOP_WORDS + PAUSE_ONLY_WORDS

    # DISMISS_WORDS 拆成两档：
    # - EXCLUSIVE: 专属告别词，整句出现一次基本就是再见（晚安/再见/goodbye/bye 等）
    # - POLITE:    礼貌词，本身高频出现在非告别语境中（谢谢/thanks）→ 必须整句很短才算告别
    # "stand down" 之前同时挂在 STOP_WORDS 和 DISMISS_WORDS，逻辑上属于强制中断 → 仅留 STOP_WORDS
    DISMISS_EXCLUSIVE = [
        "goodbye", "good night", "bye", "see you", "see you next time",
        "晚安", "再见", "拜拜",
    ]
    DISMISS_POLITE = [
        "thanks", "thank you",
        "谢谢",
    ]
    DISMISS_WORDS = DISMISS_EXCLUSIVE + DISMISS_POLITE  # 兼容旧调用

    DEBUG_ASR = False

    def __init__(self):
        super().__init__()
        self._state_lock = threading.Lock()
        self.is_jarvis_speaking = False
        # [R7-α/B1] in_active_conversation 走 self.state 中央状态机；
        # 但本类在 __init__ 时还没注入 state（state 在 main 里事后绑过来），
        # 所以保留一个 _local_in_active_conv 兜底字段，property 在没 state 时读它。
        self._local_in_active_conv = False
        self.state = None
        self.last_interaction_time = 0
        self.last_user_speech_time = 0
        self.mute_until = 0.0
        self.last_conversation_end_time = 0
        # [R6/B6] 记录上次"对话结束"是什么原因导致的，供 wake_weight 区分误唤醒严重度
        # 取值：'manual_stop'（用户喊停）/ 'manual_dismiss'（告别）/ 'timeout'（超时）/ 'natural'（正常结束）
        self.last_dismissal_reason = None
        self._suppress_wave = False
        # [R7-β5] 共享 subtitle_queue 引用，main 段事后注入（push 'listening_start' / 'listening_done'）
        self._subtitle_queue = None
        # 🩹 [β.5.35-C / 2026-05-20] Sir struggle detector — offer_help 真触发源
        # Sir 反馈: 老 ProactiveShield 看屏幕 error keyword 触 offer_help 误触多 (Sir 没在挣扎).
        # 修法: 看 **Sir 嘴里说的话** (asr 出口) 命中 struggle vocab → 写 self.last_struggle_at,
        # Conductor path_b 读这个 fresh signal 决定是否真触发 offer_help.
        # vocab: memory_pool/sir_struggle_vocab.json / CLI: scripts/struggle_vocab_dump.py
        # doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
        self._struggle_vocab_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'memory_pool', 'sir_struggle_vocab.json'
        )
        self._struggle_vocab_cache = None
        self._struggle_vocab_mtime = 0.0
        self.last_struggle_at = 0.0           # 最近一次命中 struggle 的时间戳
        self.last_struggle_phrase_id = ''     # 命中的 phrase id (e.g. 'stuck_zh')
        self.last_struggle_severity = ''      # 'low' / 'medium' / 'high'
        self.last_struggle_text = ''          # Sir 原话片段 (用于 directive evidence)
        # 🆕 [Sir 2026-05-27 真愿景 Phase 6] 缓存最近一段 Sir audio 给主脑听语气
        # env JARVIS_AUDIO_TO_BRAIN=1 才被 chat_bypass.stream_chat 读. 默 b''.
        # 30s 后视为过期 (主脑下次召唤时 fresh check).
        self._last_audio_wav_bytes: bytes = b''
        self._last_audio_ts: float = 0.0
        self._last_audio_duration_sec: float = 0.0

    def get_recent_audio_for_brain(self,
                                       max_age_sec: float = 30.0) -> tuple:
        """🆕 [Phase 6] chat_bypass 调本 helper 取 Sir 最近一段 audio.

        Args:
            max_age_sec: 最大新鲜度 (default 30s). 超此 age 视为过期返 b''.

        Returns:
            (wav_bytes: bytes, duration_sec: float)
            wav_bytes 空 b'' 表示没新鲜 audio (老对话/未录入/过期).
        """
        try:
            if not self._last_audio_wav_bytes:
                return (b'', 0.0)
            age = time.time() - (self._last_audio_ts or 0.0)
            if age > max_age_sec:
                return (b'', 0.0)
            return (self._last_audio_wav_bytes,
                       float(self._last_audio_duration_sec or 0.0))
        except Exception:
            return (b'', 0.0)

    def _load_struggle_vocab(self) -> list:
        """β.5.35-C: 读 memory_pool/sir_struggle_vocab.json, mtime cache.

        返回 active phrases list, 每条 {'id', 'patterns', 'severity'}.
        失败 / 文件不存在 → 返 [], fail-safe (不触发, 跟硬编码 0 命中一致).
        """
        try:
            if not os.path.exists(self._struggle_vocab_path):
                return []
            mtime = os.path.getmtime(self._struggle_vocab_path)
            if mtime == self._struggle_vocab_mtime and self._struggle_vocab_cache is not None:
                return self._struggle_vocab_cache
            with open(self._struggle_vocab_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            active = [p for p in data.get('phrases', [])
                      if p.get('state', 'active') == 'active' and p.get('patterns')]
            self._struggle_vocab_cache = active
            self._struggle_vocab_mtime = mtime
            return active
        except Exception:
            return self._struggle_vocab_cache or []

    def _detect_sir_struggle(self, cmd: str) -> bool:
        """β.5.35-C: cmd 命中 struggle vocab → set self.last_struggle_*. 返 bool.

        命中规则: 任一 phrase 的任一 pattern 是 cmd.lower() 的子串 → 命中.
        同一轮多 phrase 命中: 取 severity 最高的 (high > medium > low).
        """
        if not cmd or not isinstance(cmd, str):
            return False
        lower_cmd = cmd.lower().strip()
        if len(lower_cmd) < 2:
            return False
        active = self._load_struggle_vocab()
        if not active:
            return False
        # 找命中 + 最高 severity
        sev_rank = {'high': 3, 'medium': 2, 'low': 1, '': 0}
        best_match = None
        best_rank = 0
        for phrase in active:
            patterns = phrase.get('patterns', [])
            for pat in patterns:
                if pat.lower() in lower_cmd:
                    sev = phrase.get('severity', 'medium')
                    rank = sev_rank.get(sev, 0)
                    if rank > best_rank:
                        best_match = (phrase, pat)
                        best_rank = rank
                    break  # 同 phrase 第一个命中即用
        if best_match is None:
            return False
        phrase, pat = best_match
        self.last_struggle_at = time.time()
        self.last_struggle_phrase_id = phrase.get('id', '')
        self.last_struggle_severity = phrase.get('severity', 'medium')
        self.last_struggle_text = cmd[:160]  # cap 160 char
        try:
            from jarvis_utils import bg_log
            bg_log(
                f"🆘 [SirStruggle] phrase={self.last_struggle_phrase_id} "
                f"sev={self.last_struggle_severity} pattern='{pat}' "
                f"text='{cmd[:60]}'"
            )
        except Exception:
            pass
        return True

    def _publish_listening_done(self):
        """[R7-β5] ASR 结果被丢弃（hallucination/too_short/echo）时清掉 Listening… 指示。"""
        try:
            if self._subtitle_queue is not None:
                self._subtitle_queue.put(("listening_done", ""))
        except Exception:
            pass

    # [R7-α/B1] in_active_conversation 通过 property 走 state.active_conversation；
    # state 未注入时退到本地 _local_in_active_conv，保证早期访问（如单元测试）不挂。
    @property
    def in_active_conversation(self) -> bool:
        state = self.state
        if state is None:
            return self._local_in_active_conv
        return state.active_conversation

    @in_active_conversation.setter
    def in_active_conversation(self, value):
        value = bool(value)
        self._local_in_active_conv = value
        state = self.state
        if state is not None:
            state.set_active_conversation(value, reason='legacy_setter', source='VoiceListenThread')

    # [R6/B5] 上下文感知的停止/告别词检测
    # 规则：
    # 1. 整句完全等于关键词 → 一定触发（"闭嘴"、"再见"）
    # 2. 关键词在首 6 个字符内出现 → 触发（短的强制指令）
    # 3. 否则不触发（"现在外面好安静" / "Thanks for that, can you also..."）
    # 这样避免一个无心词把整个会话击碎。
    @staticmethod
    def _phrase_at_head(needle: str, haystack_lower: str, head_chars: int = 6) -> bool:
        """关键词是否出现在 haystack 前 head_chars 字符内，且对英文使用词边界。

        [P0+20-β.2.5 hotfix / 2026-05-17] \\b 在 Python re 默认含汉字 word char，
        所以 '是stand' 之间不算 boundary → 用显式 ASCII lookbehind/lookahead 替代。
        """
        if not needle or not haystack_lower:
            return False
        prefix = haystack_lower[:head_chars]
        if any('\u4e00' <= c <= '\u9fa5' for c in needle):
            return needle in prefix
        # 英文：ASCII 词边界 + 起始位置在 head_chars 内
        m = re.search(r'(?<![a-zA-Z])' + re.escape(needle) + r'(?![a-zA-Z])',
                      haystack_lower)
        if not m:
            return False
        return m.start() <= head_chars

    @staticmethod
    def _phrase_at_tail(needle: str, haystack_lower: str, tail_chars: int = 14) -> bool:
        """[P0+20-β.2.5 hotfix / 2026-05-17] 关键词是否在 haystack **末尾** tail_chars
        字符内。Sir 23:58 实测 BUG：'不是不是我说错了，是 stand down' 这种纠正/补救式
        输入 sw 在尾部不在首部，原 _phrase_at_head 路径不触发 → stand down 没退出焦点。
        英文用显式 ASCII boundary（\\b 默认含汉字 → '是stand' 之间不算 boundary）。"""
        if not needle or not haystack_lower:
            return False
        suffix = haystack_lower[-max(tail_chars, len(needle) + 4):]
        if any('\u4e00' <= c <= '\u9fa5' for c in needle):
            return needle in suffix
        m = re.search(r'(?<![a-zA-Z])' + re.escape(needle) + r'(?![a-zA-Z])', suffix)
        return m is not None

    def detect_stop_command(self, clean_text: str) -> bool:
        """是否是强制停止指令。被 ASR 主循环调用。"""
        if not clean_text:
            return False
        s = clean_text.lower().strip()
        s_clean = re.sub(r'[，。,.!?？！\s]+', '', s)
        if not s_clean:
            return False
        # 1. 整句完全等于硬/软停止词 / PAUSE_ONLY 词 → 触发
        # 🆕 [P5-fix37] PAUSE_ONLY_WORDS 仅在整句完全等于时触发 (Sir 12:13 真痛点修).
        for sw in self.STRICT_STOP_WORDS + self.SOFT_STOP_WORDS + self.PAUSE_ONLY_WORDS:
            if s_clean == sw.lower().replace(' ', ''):
                return True
        # 2. 硬停止词出现在首部（6 字符内）→ 触发. PAUSE_ONLY 不走此路径.
        for sw in self.STRICT_STOP_WORDS:
            if self._phrase_at_head(sw.lower(), s, head_chars=8):
                return True
        # 3. 软停止词仅在 "整句 ≤ 4 字符 且 首部命中" 触发（保留"安静"作为短促停止的兜底）
        for sw in self.SOFT_STOP_WORDS:
            if len(s_clean) <= 4 and self._phrase_at_head(sw.lower(), s, head_chars=4):
                return True
        # 4. [P0+20-β.2.5 hotfix / 2026-05-17] 硬停止词出现在句末（最后 max(len(sw)+6, 14)
        # 字符内）→ 也触发。修 Sir 23:58 实测 BUG："不是不是我说错了，是 stand down" 这种
        # 纠正模式：句首是否定词「不是」，真正意图在句末。短句 (≤ 26 字符) 强制句末检测；
        # 长句仍跳过避免误炸"I want to talk about stand down protocols"这类话题讨论。
        # 🆕 [P5-fix37] PAUSE_ONLY 也不走此路径 (避免承前对话误判).
        if len(s_clean) <= 26:
            for sw in self.STRICT_STOP_WORDS:
                if self._phrase_at_tail(sw.lower(), s, tail_chars=max(len(sw) + 6, 14)):
                    return True
        return False

    def detect_dismiss_command(self, clean_text: str) -> bool:
        """是否是告别/告退（用户准备结束这一段对话）。"""
        if not clean_text:
            return False
        s = clean_text.lower().strip()
        s_clean = re.sub(r'[，。,.!?？！\s]+', '', s)
        if not s_clean:
            return False

        # 1. 整句等于任何告别词（精确匹配）
        for dw in self.DISMISS_WORDS:
            if s_clean == dw.lower().replace(' ', ''):
                return True

        word_count = len(s.split())
        zh_count = sum(1 for c in s if '\u4e00' <= c <= '\u9fa5')

        # 2. 礼貌词（thanks / 谢谢）—— 必须整句极短才算告别
        # 中文：≤ 4 个汉字总量；英文：≤ 3 个词
        for dw in self.DISMISS_POLITE:
            dw_lower = dw.lower()
            if any('\u4e00' <= c <= '\u9fa5' for c in dw_lower):
                if zh_count <= 4 and dw_lower in s_clean:
                    return True
            else:
                if word_count <= 3:
                    if self._phrase_at_head(dw_lower, s, head_chars=6):
                        return True
                    if re.search(r'\b' + re.escape(dw_lower) + r'\b\s*[!.?]*\s*$', s):
                        return True

        # 3. 强告别词（再见 / bye / goodbye）—— 短句 ≤ 8 词 / ≤ 16 字符 + 首尾命中
        if word_count <= 8 and len(s_clean) <= 16:
            for dw in self.DISMISS_EXCLUSIVE:
                dw_lower = dw.lower()
                if any('\u4e00' <= c <= '\u9fa5' for c in dw_lower):
                    dw_compact = dw_lower.replace(' ', '')
                    if s_clean.startswith(dw_compact) or s_clean.endswith(dw_compact):
                        return True
                else:
                    if self._phrase_at_head(dw_lower, s, head_chars=8):
                        return True
                    if re.search(r'\b' + re.escape(dw_lower) + r'\b\s*[!.?]*\s*$', s):
                        return True

        return False

    def set_speaking_state(self, state_str):
        # 🩹 [β.5.43-A / 2026-05-20] Sir 17:10 真理 — Jarvis HUD 状态条
        # state_str: EXECUTING / THINKING / IDLE → tracker 4-way map
        try:
            from jarvis_state_tracker import (
                set_state as _set_js, STATE_SPEAKING, STATE_THINKING,
                STATE_READY, STATE_FOCUSED,
            )
            if state_str == "EXECUTING":
                _set_js(STATE_SPEAKING, reason='tts_started')
            elif state_str == "THINKING":
                _set_js(STATE_THINKING, reason='llm_stream')
            elif state_str == "IDLE":
                _next = STATE_FOCUSED if self.in_active_conversation else STATE_READY
                _set_js(_next, reason='turn_complete')
        except Exception:
            pass

        if state_str == "EXECUTING":
            self.is_jarvis_speaking = True
            set_browser_ducking(True)
            # [P0+18-a.7 / 2026-05-15] 修 BUG #5: Jarvis 自己说话期间不续命焦点 →
            # 30s standby 倒计时跨 vocal 回答阶段 → Sir 听完 Jarvis 回答时焦点已经掉了。
            # 边界续命：进 EXECUTING（开始说话）+ 出 IDLE（说完）各续一次，
            # 与 Bug E 修复不冲突 — Bug E 是说不要在 THINKING 状态持续续命（思考阶段无限续）；
            # 这里只在状态切换瞬间续，单次操作。
            try:
                if getattr(self, 'in_active_conversation', False):
                    self.last_interaction_time = time.time()
            except Exception:
                pass
        elif state_str == "THINKING":
            if getattr(self, 'is_jarvis_speaking', False):
                self.mute_until = time.time() + 1.5
            self.is_jarvis_speaking = False
            # 👇 Bug E 修复：不在这里把 last_interaction_time 顶到现在，
            # 否则任何 Jarvis 自己思考/说话都会续命焦点锁，30 秒永远到不了。
            # last_interaction_time 现在只在"用户成功讲了有效话"时才更新。
            # （P0+18-a.7 备注：续命只在 EXECUTING/IDLE 切换瞬间做，THINKING 仍不续 —
            # 思考态可能持续很久，避免拖死 standby）
        elif state_str == "IDLE":
            was_speaking = getattr(self, 'is_jarvis_speaking', False)
            self.is_jarvis_speaking = False
            # 👇 Bug A 修复：Jarvis 刚说完话 → 保留一个短窗口（0.6s）防止
            # 喇叭余音/房间混响被自家麦克风又拾回去当成"用户输入"。
            # 之前在 in_active_conversation=True 时把 mute_until 强制清零，
            # 直接导致 "As you wish, muting audio" 被自己听进去的死循环。
            if was_speaking:
                # 焦点对话里给 0.6s（够让 TTS 余音衰减但不影响用户秒回）；
                # 非对话状态给 1.5s（更保守，因为我们没在等用户讲话）。
                grace = 0.6 if self.in_active_conversation else 1.5
                self.mute_until = max(self.mute_until, time.time() + grace)
                # [P0+18-a.7 / 2026-05-15] 出 EXECUTING → IDLE（说完一段话）也续命一次，
                # 让 Sir 听完 Jarvis 答语后还有完整 30s 思考时间。
                try:
                    if getattr(self, 'in_active_conversation', False):
                        self.last_interaction_time = time.time()
                except Exception:
                    pass
            if not self.in_active_conversation:
                set_browser_ducking(False)

    def parse_wake_word(self, text):
        text_lower = text.lower().strip()
        if not text_lower:
            return False, text_lower

        wake_aliases = [
            "jarvis", "贾维斯", "javis", "jervis", "jarvi", "jarvice",
            "charles", "travis", "jovis", "gervais",
            "chavis", "jarvid", "jarvs",
            "rovis", "noice", "jarbis", "jarvas", "charvis", "jarviz",
            "jarbis", "jarbus", "jarbiz", "jerviz", "jervas",
            "jarbys", "jarbice", "jervice", "jervis",
        ]

        found_alias = None
        for w in wake_aliases:
            w_lower = w.lower()
            if re.match(r'^[a-z]+$', w_lower):
                if re.search(r'\b' + w_lower + r'\b', text_lower):
                    found_alias = w_lower
                    break
            else:
                if w_lower in text_lower:
                    found_alias = w_lower
                    break

        if found_alias is None:
            english_words = re.findall(r'[a-z]+', text_lower)
            for word in english_words:
                if 4 <= len(word) <= 8:
                    if fuzz.ratio(word, "jarvis") >= 78:
                        found_alias = word
                        break
                    if fuzz.partial_ratio(word, "jarvis") >= 82:
                        found_alias = word
                        break

            if found_alias is None:
                zh_chars = re.sub(r'[^\u4e00-\u9fa5]', '', text_lower)
                if len(zh_chars) >= 2:
                    for size in [2, 3]:
                        for i in range(len(zh_chars) - size + 1):
                            window = zh_chars[i:i+size]
                            if fuzz.ratio(window, "贾维斯") >= 66:
                                found_alias = window
                                break
                        if found_alias:
                            break

        if found_alias is None:
            wake_phrases_fuzzy = [
                "wake up", "wake", "woke up", "woke", "awake",
                "wca", "wka", "wakeup", "way cup", "weigh cup",
                "wake out", "wakeup", "wait up", "wake app",
            ]
            for wp in wake_phrases_fuzzy:
                wp_clean = wp.replace(" ", "")
                text_clean = text_lower.replace(" ", "")
                if wp_clean in text_clean:
                    found_alias = wp
                    break
                if len(text_lower.split()) <= 3:
                    if fuzz.ratio(text_clean, wp_clean) >= 75:
                        found_alias = wp
                        break

        if found_alias is None:
            return False, text_lower

        cmd = text_lower
        cmd = re.sub(r'\b' + re.escape(found_alias) + r'\b', '', cmd)

        wake_phrases = [
            r'\bare\s+you\s+there\b', r'\byou\s+there\b',
            r'\bare\s+you\s+up\b', r'\byou\s+up\b',
            r'\bare\s+you\s+online\b', r'\byou\s+online\b',
            r'\bare\s+you\b',
        ]
        for phrase in wake_phrases:
            cmd = re.sub(phrase, '', cmd)

        # 🩹 [P0+20-β.5.11 / 2026-05-19] 纯语气词 + jarvis → 视作空唤醒走 reflex 短路径
        # Sir 真机痛点: "hey jarvis" 被识成 cmd='hey' 送 LLM 跑全主脑, 应走快唤醒.
        # 设计意图: 任意词+jarvis 中"任意词"若是纯 filler/呼语 (hey/hi/yo/嘿/喂...),
        # 不应被当 LLM cmd, 而该降级为空唤醒, 让 fallback `cmd = "jarvis"` 接住走 reflex.
        # 注: 实词 ("jarvis 帮我开 cursor" → cmd='帮我开 cursor') 仍走 LLM 唤醒, 不影响.
        # 🩹 [β.5.26 / 2026-05-20] Sir 准则 6 vocab 化 - 老硬编码 list 留作 fallback,
        # source of truth = memory_pool/wake_filler_vocab.json. CLI scripts/wake_filler_dump.py.
        # 🩹 [β.5.26-fix / 2026-05-20] 调模块级 _load_wake_filler_vocab (Sir 02:43 实测
        # 'VoiceListenThread no attribute _load_wake_filler_vocab' - 老把它放 JarvisWorkerThread 类错了).
        filler_addressing_words = _load_wake_filler_vocab()
        for filler in filler_addressing_words:
            cmd = re.sub(filler, '', cmd)

        cmd = re.sub(r'[，。,.!?？！\s]+', ' ', cmd).strip()

        if not cmd or len(cmd) <= 1:
            cmd = "jarvis"

        return True, cmd

    # 🩹 [β.2.7.10 / 2026-05-17] Sir 焦点退出"小心翼翼"痛点修复
    # Sir 不想"焦点模式期间随便录入电话/旁人话/视频音都触发 Jarvis"
    # 启发式打分: ASR 文本是否像"对 Jarvis 说" vs "对其他人/旁路说"
    # 返回 0-1 score, < 0.3 视为旁路语, 不触发主脑
    # 🆕 [Sir 2026-05-25 21:14 真测追根] '小贾' = Sir 对 Jarvis 的活泼称呼
    # Sir 21:14 原话 "小贾是我叫贾维斯的活泼的称呼而已"
    # 准则 6 evidence: Sir 显式声明 → 立刻加 vocab. 后续如果 Sir 有更多昵称,
    # 加 memory_pool/wake_word_vocab.json + scripts/wake_word_dump.py (TODO).
    _JARVIS_DIRECT_WAKE = (
        'jarvis', '贾维斯', 'javis', 'jervis', 'jarvi',
        '小贾', '小贾贾', 'xiaojia',  # 🆕 Sir 活泼称呼
    )
    _JARVIS_DIRECT_VERBS_EN = (
        'help me', 'tell me', 'find', 'search', 'open', 'close', 'launch',
        'remind me', 'set ', 'show me', 'play ', 'stop ', 'pause ',
        'note this', 'save ', 'remember ', 'forget ', 'cancel ',
        'check ', 'list ', 'kill ', 'mute', 'unmute',
        'what time', 'what date', 'what is the', 'how do i',
    )
    _JARVIS_DIRECT_VERBS_ZH = (
        '帮我', '告诉我', '查一下', '找一下', '打开', '关闭', '关了', '启动',
        '提醒我', '设个', '设一个', '播放', '暂停', '停一下',
        '记下', '保存', '记一下', '取消', '取消提醒',
        '查看', '列一下', '杀掉', '静音',
        '几点了', '今天几号', '什么是', '怎么',
        '帮个忙', '麻烦你', '请你', '你帮我', '替我',
    )
    _PHONE_OPENERS_EN = (
        'hello', 'hi ', 'hey ', 'are you there', 'can you hear me',
    )
    _PHONE_OPENERS_ZH = (
        '喂', '你好啊', '你好吗', '在不在', '在吗', '听得到吗', '能听到吗',
    )
    _THIRD_PERSON_INDICATORS_ZH = (
        '他说', '她说', '他们', '她们', '他在', '她在',
        '你妈', '你爸', '我妈', '我爸', '我儿', '我女',
    )
    _THIRD_PERSON_INDICATORS_EN = (
        ' he ', ' she ', ' they ', 'mum ', 'dad ', 'mom ', 'mother ',
        'father ', 'boyfriend', 'girlfriend',
    )

    def classify_jarvis_directness(self, text: str) -> tuple:
        """启发式打分: ASR 文本是否像"对 Jarvis 说"。返回 (score, breakdown).
        score 0-1: 越高越像直接对 Jarvis 说话.
          >= 0.6: 直接触发主脑
          0.3-0.6: 灰区, 仍触发 (保守)
          < 0.3:  视为旁路语 (电话/旁人/视频), 不触发主脑
        """
        if not text or not text.strip():
            return 0.0, {'empty': True}
        t = text.lower().strip()
        t_pad = ' ' + t + ' '
        breakdown = {}
        score = 0.5  # 基线中性

        # +0.5 含 Jarvis 直接称呼
        if any(w in t for w in self._JARVIS_DIRECT_WAKE):
            score += 0.5
            breakdown['wake_word'] = +0.5

        # +0.4 含 jarvis-direct verb (中英)
        if any(v in t for v in self._JARVIS_DIRECT_VERBS_EN):
            score += 0.35
            breakdown['en_direct_verb'] = +0.35
        if any(v in t for v in self._JARVIS_DIRECT_VERBS_ZH):
            score += 0.35
            breakdown['zh_direct_verb'] = +0.35

        # -0.5 电话开场词
        if any(t.startswith(p) for p in self._PHONE_OPENERS_EN) or \
           any(t.startswith(p) for p in self._PHONE_OPENERS_ZH):
            score -= 0.4
            breakdown['phone_opener'] = -0.4

        # 🩹 [P5-bypass-fix / 2026-05-21 17:02 Sir 16:57 真测痛点]
        # Sir 直接对 Jarvis 说话 (含 wake_word 或 direct_verb) 但描述 / 转述外部
        # 对话 ("我和 ud 聊天 / 我跟他说") → 不应被 third_person + conversational_marker
        # 双罚拉到 < 0.3 旁路化. Sir 是在向 Jarvis 转述, 不是跟外人说话.
        # 修法: 检测到 "Sir 直接说话" 信号 → 转述类罚分降权 50%.
        # 🆕 [Sir 2026-05-25 21:14 真测追根 #2] Sir 第一人称自叙也是 addressing jarvis
        # Sir 痛点: Sir 跟 Jarvis 讲自己事 ('我今天去面试...我是表现最好的...他要我上台')
        # 含多个 '我' 第一人称 → Sir 在跟 Jarvis 叙事, 不是跟外人对话. 不该旁路化.
        # 判定: '我' 出现 >= 2 次 → Sir 自叙 evidence (排除 '我妈/我爸' 家庭指代 → 那
        # 是真转述他人对话).
        _wo_count = text.count('我')
        _has_family_indicator = any(w in text for w in ('我妈', '我爸', '我儿', '我女'))
        _is_first_person_narrative = (_wo_count >= 2 and not _has_family_indicator)
        _is_addressing_jarvis = (
            'wake_word' in breakdown
            or 'zh_direct_verb' in breakdown
            or 'en_direct_verb' in breakdown
            or '你' in text  # Sir 第二人称 → 直接对 Jarvis
            or _is_first_person_narrative  # Sir 自叙给 Jarvis 听
        )

        # -0.3 含明确第三人称指代 (含 padding 避免误判 ' the ')
        third_hits_zh = sum(1 for w in self._THIRD_PERSON_INDICATORS_ZH if w in text)
        third_hits_en = sum(1 for w in self._THIRD_PERSON_INDICATORS_EN if w in t_pad)
        if third_hits_zh + third_hits_en >= 1:
            penalty = min(0.4, 0.2 + (third_hits_zh + third_hits_en) * 0.1)
            if _is_addressing_jarvis:
                penalty *= 0.5  # Sir 在转述, 不是跟第三人说话, 降权
            score -= penalty
            breakdown['third_person'] = -penalty

        # -0.2 长句 + 多疑问号 (电话/对外深度对话)
        q_count = text.count('?') + text.count('？')
        if len(text) > 40 and q_count >= 2:
            penalty_lq = 0.2
            if _is_addressing_jarvis:
                penalty_lq *= 0.5  # Sir 直接问 Jarvis 长问题, 不是对外深度
            score -= penalty_lq
            breakdown['long_multi_question'] = -penalty_lq

        # -0.15 含 "我和/和我...说" 之类外部对话标记
        if '和我' in text or '跟我' in text or '我和' in text or '我跟' in text:
            penalty_cm = 0.15
            if _is_addressing_jarvis:
                penalty_cm *= 0.5  # Sir 在转述外部对话给 Jarvis 听, 不是和外人说
            score -= penalty_cm
            breakdown['conversational_marker'] = -penalty_cm

        # -0.1 极短句 (≤3 字) 且无 wake word (mhm/嗯/对/好) 默认旁路概率高
        if len(t) <= 3 and 'wake_word' not in breakdown:
            score -= 0.15
            breakdown['too_short'] = -0.15

        score = max(0.0, min(1.0, score))
        return score, breakdown

    def _handle_acoustic_wake(self, res: 'Any') -> None:
        """[P0+20-β.4.8 / 2026-05-19] Acoustic wakeword 检测到 → 触发 wake.

        复用 line 1077-1091 的 ASR string match wake 逻辑, 但 cmd 有限 (声学售醒不能告诉你
        “售醒后说了什么”, 只能告诉你“被售醒了”). cmd=='jarvis' 走 默认 “At your service”.

        Args:
            res: WakeDetectionResult (含 score / keyword)
        """
        try:
            from jarvis_utils import bg_log
        except Exception:
            bg_log = lambda m: print(f"║ {m}")
        bg_log(
            f"🔔 [Acoustic Wake / β.4.8] keyword={res.keyword!r} "
            f"score={res.score:.3f} → 触发 wake (跳过 ASR string match)"
        )
        if not self.in_active_conversation:
            self.awake_signal.emit(True)
        if self.state is not None:
            self.state.set_active_conversation(
                True, reason='wake', source='acoustic_wake_word'
            )
        else:
            self.in_active_conversation = True
        self.last_interaction_time = time.time()
        try:
            set_browser_ducking(True)
        except Exception:
            pass
        # 声学售醒 → 发 'jarvis' empty cmd 走 default “At your service” 路径
        # Sir 接下来说话走 active_conversation 里的 ASR 转写链
        try:
            self._emit_with_attention("jarvis")
        except Exception:
            pass

    def _emit_with_attention(self, cmd: str):
        """[R7-α/AttentionContext] emit text_ready 之前先抓拍一份 attention 快照。
        slot 未挂上时不挂；抓拍异常吞掉不影响 emit 主路径。
        capture_now 内部已做 try/except + ≤ 10ms 防御，不会阻塞 ASR 节奏。
        """
        try:
            slot = getattr(self, '_attention_slot', None)
            if slot is not None:
                slot.capture_now()
        except Exception:
            pass
        # 🧬 [P0+20-W.2 / 2026-05-16] 开新对话轮：本轮所有 bg_log 自动带 [turn_xxx] 前缀
        try:
            from jarvis_utils import TraceContext
            TraceContext.new_turn()
        except Exception:
            pass
        # 🪞 [P0+20-β.2.0 / 2026-05-16] 通知 SelfAnchor 新 turn 开始（用于 turn_count + last_spoke）
        try:
            from jarvis_self_anchor import get_default_self_anchor
            _anchor = get_default_self_anchor()
            if _anchor is not None:
                _anchor.record_turn()
        except Exception:
            pass
        # 🆘 [β.5.35-C / 2026-05-20] Sir struggle detector — offer_help 真触发源
        # 看 cmd 命中 struggle vocab → 写 self.last_struggle_at 让 Conductor 决策时读.
        # 失败/异常静默, 主路径不阻塞.
        try:
            self._detect_sir_struggle(cmd)
        except Exception:
            pass
        # 🩹 [β.5.43-E / 2026-05-20] Silence Intelligence — thinking pause 检测
        # Sir 17:10 真理 (6 缺口 E): Sir 说 'uh / 嗯 / let me think' → publish SWM, 
        # 主脑 directive 决定怎么反应 (短 'mhm' / 不打断). publish-only, 不阻塞 emit.
        try:
            from jarvis_silence_intel import is_thinking_pause, publish_thinking_pause_event
            _is_pause, _evidence = is_thinking_pause(cmd)
            if _is_pause:
                publish_thinking_pause_event(cmd, _evidence)
                try:
                    from jarvis_utils import bg_log as _si_bg
                    _si_bg(
                        f"⏸️ [SilenceIntel] thinking pause detected (conf="
                        f"{_evidence.get('confidence', 0):.2f}): \"{cmd[:40]}\""
                    )
                except Exception:
                    pass
        except Exception:
            pass
        # 🆕 [P5-fix25-stand-down / 2026-05-22] 15s 试探期 grace cancel
        # Sir 进 stand_down 后 15s 内说话 → 视为误触发, 自动 cancel.
        # 防止 Sir 按错 hotkey / LLM 误判 dismissal 进 stand_down.
        try:
            import jarvis_stand_down as _sd
            if _sd.is_in_grace() and cmd and cmd.strip():
                cancelled = _sd.grace_cancel_if_in_grace(
                    reason=f'Sir 说话 in grace: "{cmd[:40]}"')
                if cancelled:
                    try:
                        from jarvis_utils import bg_log as _gc_bg
                        _gc_bg(f"☀️ [StandDown/Grace] cancel — Sir 说话 in 15s 试探期: \"{cmd[:40]}\"")
                    except Exception:
                        pass
        except Exception:
            pass
        # 🆕 [P5-fix25-phase3-one-shot / 2026-05-22] one-shot summon
        # 在 stand_down active 时 Sir 喊 "Jarvis ..." / "贾维斯 ..." → mark
        # 本轮 voice 不静默 (听 reply). 答完 60s 后自动回全静默.
        # 注意: 在 grace_cancel 之后判 — 如果 Sir 在 grace 内说话已 cancel,
        # 这里 _sd.is_active() 返 False, 不会 mark (合理).
        try:
            import jarvis_stand_down as _sd2
            if _sd2.is_active() and cmd and cmd.strip():
                _cmd_low = cmd.lower()
                if any(w in _cmd_low for w in ('jarvis', '贾维斯')):
                    # 拿 current turn_id (best effort)
                    _turn_id = ''
                    try:
                        from jarvis_utils import TraceContext
                        _turn_id = TraceContext.get_turn_id() or ''
                    except Exception:
                        pass
                    _sd2.mark_one_shot_summon(turn_id=_turn_id, duration_s=60.0)
        except Exception:
            pass
        self.text_ready.emit(cmd)

    def run(self):
        print("🧠[AuditoryCortex] 正在将 SenseVoiceSmall 神经网络加载到 GPU 显存...")
        try:
            from funasr import AutoModel
            model = AutoModel(model="iic/SenseVoiceSmall", trust_remote_code=True, device="cuda:0")
            print("✅[AuditoryCortex] 本地模型挂载完毕, 完全离线运行！")
        except Exception as e:
            print(f"❌ [模型挂载失败]: {e}")
            return

        import pyaudio, numpy as np, time, wave, soundfile as sf, re, sys
        p = pyaudio.PyAudio()
        try:
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        except Exception as e:
            print(f"❌[麦克风锁定失败]: {e}")
            return

        print("[AuditoryCortex] 24/7 物理环境音频监听已启动...")

        # [P0+20-β.4.8 / 2026-05-19] Acoustic wakeword detector init (openWakeWord)
        # vocab.acoustic_wake_enabled=false → stub (不动原 wake 链); =true → 真实例
        # is_available() 差重, in_active_conversation 期间不调 (节省 CPU)
        try:
            from jarvis_acoustic_wake import get_acoustic_wake_detector
            self._acoustic_det = get_acoustic_wake_detector()
            if self._acoustic_det.is_available():
                print(f"🔊[AcousticWake / β.4.8] 启用 → keyword={self._acoustic_det.keyword_name!r} "
                      f"threshold={self._acoustic_det.threshold}")
            else:
                print(f"🔇[AcousticWake / β.4.8] 未启用 ({self._acoustic_det.get_disable_reason()[:80]})")
        except Exception as _aw_e:
            print(f"⚠️[AcousticWake / β.4.8] init 异常不启用: {_aw_e}")
            self._acoustic_det = None

        # 🩹 [β.5.40-A1 / 2026-05-20 + P5-fix-AmbientBus / 2026-05-21 09:55]
        # Ambient sensor init (Sir 方向 A.1) — 轻量被动听感 hook 同一帧 PCM data,
        # publish ambient_state SWM. 不调 ASR / 不抢麦克风 / 不存 audio raw (隐私) /
        # 仅 IDLE 时分析. ENV: JARVIS_AMBIENT_DISABLE=1 可强制关闭.
        #
        # BUG fix: 原 line `getattr(getattr(self.jarvis, ...))` 访问 `self.jarvis` —
        # 但 VoiceListenThread 没这字段 (`self.jarvis` 是 JarvisWorkerThread 才有).
        # Sir 09:53 真测真报: "init 异常不启用: 'VoiceListenThread' object has no attribute 'jarvis'".
        # AmbientSensor 整个 sprint 从启动起就没工作过 — 主脑没看到 ambient_state SWM signal.
        # 修法: 改用 jarvis_utils.get_event_bus() 全局 singleton, 跟 SilenceIntel /
        # ProactiveCare 等其他 publish-only 模块同 pattern, 不依赖类继承链.
        try:
            from jarvis_ambient_sensor import get_ambient_sensor
            from jarvis_utils import get_event_bus as _amb_geb
            _bus = _amb_geb()
            self._ambient_sensor = get_ambient_sensor(event_bus=_bus)
            stats = self._ambient_sensor.get_stats()
            if stats.get('effective_enabled'):
                print(f"🎵[AmbientSensor / β.5.40-A1] 启用 — 后台被动听感 (laughter/sigh/humming/video/conversation)")
            else:
                print(f"🔇[AmbientSensor / β.5.40-A1] 未启用 ({stats})")
        except Exception as _as_e:
            print(f"⚠️[AmbientSensor / β.5.40-A1] init 异常不启用: {_as_e}")
            self._ambient_sensor = None

        # 🆕 [Sir 真测 BUG-2 治本 / 2026-05-24 15:55] 智能 VAD 自适应
        # Sir 真意 (拒绝手动 env): "并没什么智能方案吗？贾维斯他看我打开游戏就会说一些
        # 我玩游戏不休息了的话，讲道理他是知道我在玩游戏的吧？"
        # 治本: PhysicalEnvironmentProbe 看 foreground window title + fullscreen,
        # 命中 gaming_vocab.json → is_gaming_active=True → VoiceListenThread 自动倍增
        # VOLUME_THRESHOLD + SILENCE_LIMIT (vocab 配 multiplier).
        # 不需要 Sir 手动 env. env 仍保留作 fallback (vocab 损坏时).
        try:
            VOLUME_THRESHOLD_BASE = int(os.environ.get('JARVIS_VAD_VOLUME_THRESHOLD', '180'))
        except Exception:
            VOLUME_THRESHOLD_BASE = 180
        SILENCE_LIMIT_BASE = 1.8
        # 👇 Bug D 修复：用户实际诉求是"对话完保持 30 秒焦点模式后自动退出"，
        # 原来 60s 太长 + 又被环境噪音不断续命，实际从来不会自动退出。
        ACTIVE_TIMEOUT = 30.0

        pre_roll_buffer = collections.deque(maxlen=20) 
        audio_frames = []
        is_speaking = False
        silence_timer = time.time()
        start_record_time = 0.0 

        # 🩹 [P0+20-β.1.1 / 2026-05-16] 声波打印节流（治 B6 致命卡顿）
        # 原症状：每帧（64ms）都 sys.stdout.write 进度条 → PowerShell 看不懂 \r
        # → 把所有 ~50 字节进度条横向叠成 30K bytes 单行 → 终端阻塞 → 麦克风
        # 录入再叠加上一段说的话。
        # 修法：① 100ms 内最多刷一次；② 单段进度条结束（is_speaking 落到 False）
        # 再统一换行收尾；③ 异常完全吞掉，绝不影响 ASR 主路径。
        WAVE_PRINT_INTERVAL = 0.10  # 100ms
        last_wave_print_at = 0.0
        wave_in_progress = False  # 当前是否在打印一段声波（决定收尾换行）

        # 🆕 [BUG-2 中期治本 / 2026-05-24 18:50] 自适应 noise floor (准则 6 三维耦合)
        # Sir 真意: Gaming 1.8x mult 仍可能被持续游戏背景音 (300-500 dB) 触发录音.
        # 治本: 5s 滑窗算 idle frame percentile-30 = noise_floor, threshold 动态自适.
        # threshold = max(BASE * gaming_mult, floor * 2.5, MIN_THRESHOLD).
        # 安静办公室: floor=50 → threshold=125, Sir 说话仍触发.
        # 游戏背景音: floor=300 → threshold=750, 持续游戏不触发, Sir 大声说话仍触发.
        # 限频 SWM publish (30s + 50dB delta) 让主脑下轮看 evidence (准则 6 数据耦合).
        NOISE_FLOOR_WINDOW_FRAMES = 78        # ~5s @ 64ms/frame
        NOISE_FLOOR_PERCENTILE_INDEX = 0.30   # 30%
        NOISE_FLOOR_THRESHOLD_MULT = 2.5      # threshold >= floor * 2.5
        NOISE_FLOOR_MIN_THRESHOLD = 80        # floor low hard min
        NOISE_FLOOR_MIN_FRAMES_BEFORE_USE = 30  # 30 frames warmup
        noise_floor_buffer = collections.deque(maxlen=NOISE_FLOOR_WINDOW_FRAMES)
        last_floor_publish_ts = 0.0
        last_published_floor = 0.0
        NOISE_FLOOR_PUBLISH_INTERVAL = 30.0   # 30s
        NOISE_FLOOR_PUBLISH_DELTA = 50         # 50dB

        while True:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                volume = np.abs(audio_data).mean()

                # 🩹 [P0+20-β.1.22 / 2026-05-16] 焦点超时检查提到主循环顶部（治 Sir 20:36 反馈）
                # 之前 timeout 检查只在 line 922 的"安静声波"路径，环境有持续音量（视频音/音乐）
                # → volume > VOLUME_THRESHOLD → 走 line 618 分支 → 永远 reach 不到 timeout 检查。
                # 修法：每次 iter 顶部检查一次（不依赖 is_speaking / volume 分支）。
                if self.in_active_conversation and not is_speaking:
                    if time.time() - self.last_interaction_time > ACTIVE_TIMEOUT:
                        print("\n💤[System Standby] 专注锁超时，返回潜意识状态。")
                        if self.state is not None:
                            self.state.set_active_conversation(False, reason='timeout', source='active_timeout_toplevel')
                        else:
                            self.in_active_conversation = False
                        self.last_conversation_end_time = time.time()
                        self.last_dismissal_reason = 'timeout'
                        self.awake_signal.emit(False)
                        set_browser_ducking(False)
                        try:
                            if self._subtitle_queue is not None:
                                self._subtitle_queue.put(("focus", False))
                                self._subtitle_queue.put(("clear", ""))
                        except Exception:
                            pass

                if getattr(self, 'is_jarvis_speaking', False) or time.time() < getattr(self, 'mute_until', 0) or getattr(self, '_suppress_wave', False):
                    frames_left = stream.get_read_available()
                    if frames_left > 0:
                        stream.read(frames_left, exception_on_overflow=False) # 抽干脏水
                    # 清 acoustic accumulator (Jarvis 说话 / mute 期间不肯污染 wake 检测)
                    if getattr(self, '_acoustic_det', None) is not None:
                        try:
                            self._acoustic_det.reset_accum()
                        except Exception:
                            pass
                    continue

                # [P0+20-β.4.8 / 2026-05-19] Acoustic wakeword check (non-active only)
                # 优点: 声学检测, 不依赖 ASR 转写质量; 远场扬声到不了 model 就不启, 近场 clipping 也能识
                # in_active 期间不调 (节省 CPU, Sir 已售醒, 走 ASR 转写链)
                # Fail-safe: 检测失败 → 继续走原 VAD + ASR + parse_wake_word 兰底
                if not self.in_active_conversation \
                        and getattr(self, '_acoustic_det', None) is not None \
                        and self._acoustic_det.is_available():
                    try:
                        ow_results = self._acoustic_det.feed_pyaudio_buffer(data)
                        for ow_res in ow_results:
                            if ow_res.detected:
                                self._handle_acoustic_wake(ow_res)
                                # [β.4.8 P2 / 2026-05-19] 启动 cooldown_s 静默期
                                # 防 timeout 后立刻被环境音/键盘/Jarvis TTS 余音连击
                                # 同时清 accum 防 Jarvis 自己说话期间污染下次唤醒
                                try:
                                    self._acoustic_det.mark_wake_triggered()
                                    try:
                                        from jarvis_utils import bg_log as _cd_log
                                        _cd_log(f"⏸️ [Acoustic Wake] cooldown 启动 ({self._acoustic_det.cooldown_s:.0f}s) — 期内 acoustic 通道关")
                                    except Exception:
                                        pass
                                except Exception as _mt_e:
                                    self._acoustic_det.reset_accum()
                                    try:
                                        from jarvis_utils import bg_log as _cd_log
                                        _cd_log(f"⚠️ [Acoustic Wake] mark_wake_triggered 失败 fallback reset: {_mt_e}")
                                    except Exception:
                                        pass
                                audio_frames = []
                                is_speaking = False
                                break
                    except Exception as _ow_e:
                        # 声学检测出异常不能阻塞主链
                        try:
                            from jarvis_utils import bg_log as _ow_bg
                            _ow_bg(f"⚠️ [Acoustic Wake] feed 异常 (容忍): {_ow_e}")
                        except Exception:
                            pass

                # 🩹 [β.5.40-A1 / 2026-05-20] AmbientSensor feed (Sir 方向 A.1)
                # 同帧 PCM data 喂 ambient_sensor, 内部:
                # 1. state gate (is_jarvis_speaking / sir is_speaking / in_active) reset accum 不跑
                # 2. 累积满 500ms 跑 FFT + rule classifier
                # 3. ≥ 3 连续同类 + confidence ≥ 0.6 → publish 'ambient_state' 到 SWM
                # 4. 同类 60s cooldown 不重复
                # 不抛异常: classifier 内部 try/except 兜底
                if getattr(self, '_ambient_sensor', None) is not None:
                    try:
                        self._ambient_sensor.feed_frame(
                            data,
                            is_jarvis_speaking=getattr(self, 'is_jarvis_speaking', False),
                            is_sir_speaking=is_speaking,
                            sir_in_active=self.in_active_conversation,
                        )
                    except Exception:
                        pass  # ambient 永不挡主链

                # 🩹 [P0+20-β.2.2 / 2026-05-16] 滞后双阈值 VAD（治 Sir 21:43 反馈 ASR 不触发）
                # 根因：Sir 后台 Premiere 视频导出让 volume 在 100-200 抖动 →
                # 单一阈值 180 让某些帧进 if-high 分支刷新 silence_timer →
                # silence_timer 永远不超时 → ASR 永远不触发。
                # 修：保持 ENTRY=180 不漏 Sir 真说话，加 EXIT=100 让背景音落到"中间区"，
                # 中间区帧不刷新 silence_timer，让累积正常超时触发 ASR。
                SILENCE_THRESHOLD_EXIT_BASE = 100  # 真安静阈值（< 100 视为安静）
                # 🆕 [Sir 真测 BUG-2 治本 / 2026-05-24 15:55] Gaming 自适应 VAD
                # PhysicalEnvironmentProbe 每秒检测 foreground window. 命中 vocab + 全屏
                # → is_gaming_active=True → VOLUME_THRESHOLD *= 1.8, EXIT *= 1.8.
                # 不影响 Sir 说话 (Sir 通常 > 300, 1.8x=324 仍触发) + 挡背景音效.
                # 高频 loop 调 cls method (查 cls attr + return tuple, O(1)).
                try:
                    _vol_mult, _sil_mult = PhysicalEnvironmentProbe.get_gaming_vad_adaptation()
                except Exception:
                    _vol_mult, _sil_mult = 1.0, 1.0
                VOLUME_THRESHOLD_GAMING = int(VOLUME_THRESHOLD_BASE * _vol_mult)
                SILENCE_THRESHOLD_EXIT = int(SILENCE_THRESHOLD_EXIT_BASE * _vol_mult)
                # [BUG-2 mid-term fix / 2026-05-24 18:50] adaptive noise floor.
                # idle frame buffer 5s, percentile-30 = floor, threshold = max(gaming, floor*2.5, MIN).
                # cheap: sorted 78 elements < 1ms each frame.
                # [W8 / 2026-05-24 19:20] noise floor compute extracted to helpers
                if not is_speaking and volume < VOLUME_THRESHOLD_GAMING:
                    noise_floor_buffer.append(float(volume))
                noise_floor, adaptive_threshold = compute_adaptive_noise_threshold(
                    noise_floor_buffer,
                    gaming_threshold=VOLUME_THRESHOLD_GAMING,
                    percentile_index=NOISE_FLOOR_PERCENTILE_INDEX,
                    threshold_mult=NOISE_FLOOR_THRESHOLD_MULT,
                    min_threshold=NOISE_FLOOR_MIN_THRESHOLD,
                    min_frames_before_use=NOISE_FLOOR_MIN_FRAMES_BEFORE_USE,
                )
                VOLUME_THRESHOLD = adaptive_threshold
                # SWM publish rate-limited (30s + 50dB delta) - main brain sees evidence
                _now_floor = time.time()
                if (noise_floor > 0 and
                        abs(noise_floor - last_published_floor) > NOISE_FLOOR_PUBLISH_DELTA and
                        _now_floor - last_floor_publish_ts > NOISE_FLOOR_PUBLISH_INTERVAL):
                    last_published_floor = noise_floor
                    last_floor_publish_ts = _now_floor
                    try:
                        from jarvis_utils import get_event_bus as _vad_geb
                        _bus = _vad_geb()
                        if _bus is not None:
                            _bus.publish(
                                etype='vad_noise_floor_changed',
                                description=(
                                    f"VAD noise floor adapted: floor={int(noise_floor)} "
                                    f"threshold={int(adaptive_threshold)} "
                                    f"gaming_mult={_vol_mult:.2f}"
                                ),
                                source='VoiceListenThread.adaptive_noise_floor',
                                salience=0.55,
                                metadata={
                                    'noise_floor': int(noise_floor),
                                    'threshold': int(adaptive_threshold),
                                    'gaming_mult': float(_vol_mult),
                                    'window_frames': len(noise_floor_buffer),
                                },
                            )
                    except Exception:
                        pass
                if volume > VOLUME_THRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        # 🩹 [β.5.43-A] HUD: Sir 开始说话 → LISTENING
                        try:
                            from jarvis_state_tracker import set_state as _set_js, STATE_LISTENING
                            _set_js(STATE_LISTENING, reason='asr_voice_detected')
                        except Exception:
                            pass
                        self.last_user_speech_time = time.time()
                        start_record_time = time.time() 
                        audio_frames = list(pre_roll_buffer) 
                        
                        if self.in_active_conversation:
                            try:
                                # 🩹 β.1.1：起始用 \r 而不是 \n，避免新行+\r 在 PowerShell
                                # 里堆积视错觉
                                sys.stdout.write("\r🎙️ [接收物理声波] ")
                                sys.stdout.flush()
                                wave_in_progress = True
                                last_wave_print_at = time.time()
                            except Exception:
                                pass
                            # [R7-β5] 第一帧拾到声波 → 屏幕显示 "Listening…"，让 Sir 立刻
                            # 知道 Jarvis 听到了。ASR 完成后由 'user' 频道替换为正式转录。
                            try:
                                if self._subtitle_queue is not None:
                                    self._subtitle_queue.put(("listening_start", ""))
                            except Exception:
                                pass

                    if self.in_active_conversation:
                        # 👇 Bug E 修复：不要在每个高于阈值的声波帧都顶起 last_interaction_time，
                        # 否则环境噪音（风扇/键盘/音乐）会让焦点模式永远续命，30 秒到不了。
                        # last_interaction_time 现在只在 ASR 真正成功转录出有意义内容时才更新（见下方）。
                        # 🩹 β.1.1：节流到 100ms 一次刷新（每帧 64ms → 平均 1-2 帧刷一次）
                        now_t = time.time()
                        if now_t - last_wave_print_at >= WAVE_PRINT_INTERVAL:
                            try:
                                bars = "█" * min(int(volume / 100), 30)
                                sys.stdout.write(f"\r🎙️ [接收物理声波] {bars} ".ljust(50))
                                sys.stdout.flush()
                                last_wave_print_at = now_t
                            except Exception:
                                pass

                    silence_timer = time.time() 
                    audio_frames.append(data)

                # 🩹 [P0+20-β.2.2 / 2026-05-16] 中间区：100 < volume <= 180
                # 视为背景噪音 / 说话尾音，audio 仍然录入但 silence_timer 不刷新
                # 让 silence_timeout 能正常累积到达
                elif is_speaking and volume > SILENCE_THRESHOLD_EXIT:
                    audio_frames.append(data)
                    # 注意：不刷新 silence_timer，不打格子（避免误以为 Sir 在说话）

                elif is_speaking:
                    audio_frames.append(data)
                    
                    current_speaking_duration = time.time() - start_record_time
                    
                    if self.in_active_conversation:
                        if current_speaking_duration < 3:
                            current_silence_limit = 1.5
                        else:
                            current_silence_limit = 2
                    else:
                        current_silence_limit = 1.5
                    # 🆕 [Sir 真测 BUG-2 治本 / 2026-05-24 15:55] Gaming 自适应 silence
                    # Gaming 时游戏背景音常在 EXIT-ENTRY 中间 → silence_timer 难超时.
                    # 抬高 silence_limit (1.3x) 让累积更稳定到达, 避免 ASR fragment.
                    current_silence_limit *= _sil_mult
                    
                    max_record_time = 60.0 if self.in_active_conversation else 4.0 
                    
                    is_silence_timeout = (time.time() - silence_timer > current_silence_limit)
                    is_max_time_reached = (time.time() - start_record_time > max_record_time)
                    
                    if is_silence_timeout or is_max_time_reached:
                        is_speaking = False
                        # 🩹 [P0+20-β.1.1 / 2026-05-16] 收尾换行：保证一段声波结束后
                        # 后续 [Pipeline]/[Tier]/[Human] 等输出不和进度条粘连。
                        if wave_in_progress:
                            try:
                                sys.stdout.write("\n")
                                sys.stdout.flush()
                            except Exception:
                                pass
                            wave_in_progress = False
                        
                        if self.in_active_conversation and self.DEBUG_ASR:
                            sys.stdout.write("\r🧠[声波截断] 正在进行神经网络转译...".ljust(50) + "\n")
                            sys.stdout.flush()

                        pcm_data = b''.join(audio_frames)
                        # 🆕 [Sir 2026-05-27 20:45 真愿景 Phase 6] 缓存 WAV bytes
                        # 让主脑能听 Sir 语气. chat_bypass.stream_chat 读这个,
                        # env JARVIS_AUDIO_TO_BRAIN=1 才接进 Gemini multi-modal.
                        # 不缓存太长 (cap 60s, 主脑不该听 6 分钟独白).
                        _wav_bytes_for_brain: bytes = b''
                        with io.BytesIO() as wav_io:
                            with wave.open(wav_io, 'wb') as wav_file:
                                wav_file.setnchannels(1)
                                wav_file.setsampwidth(2)
                                wav_file.setframerate(16000)
                                wav_file.writeframes(pcm_data)
                            wav_io.seek(0)
                            _wav_bytes_for_brain = wav_io.getvalue()
                            wav_io.seek(0)
                            speech_array, _ = sf.read(wav_io)
                        # 暂存最近一段 (60s cap, 30s 后过期). 任何错误静默.
                        try:
                            _duration_sec = len(pcm_data) / (16000 * 2)  # 16k mono 16bit
                            if 0 < _duration_sec <= 60.0 and len(_wav_bytes_for_brain) < 2_000_000:
                                self._last_audio_wav_bytes = _wav_bytes_for_brain
                                self._last_audio_ts = time.time()
                                self._last_audio_duration_sec = _duration_sec
                        except Exception:
                            pass

                        res = model.generate(input=speech_array, cache={}, language="auto", use_itn=True, disable_pbar=True)

                        if res and len(res) > 0:
                            raw_text = res[0].get("text", "")
                            clean_text = re.sub(r'<\|.*?\|>', '', raw_text).strip()
                            clean_text_lower = clean_text.lower()
                            
                            if clean_text and len(clean_text) >= 2 and self.DEBUG_ASR:
                                print(f"\n🔊 [ASR Diag] Model heard: '{clean_text}' (raw: '{raw_text}')")
                            
                            is_woken_up, raw_cmd = self.parse_wake_word(clean_text)

                            # [R6/B5] 改走上下文感知检测 —— "外面很安静" 不再误炸
                            if self.detect_stop_command(clean_text):
                                if self.DEBUG_ASR:
                                    print(f"\n🛑 [Force Stop] 中断指令已接收，系统终止。")
                                # [R7-α/B1] 显式 reason='stop_cmd'
                                if self.state is not None:
                                    self.state.set_active_conversation(False, reason='stop_cmd', source='detect_stop_command')
                                else:
                                    self.in_active_conversation = False
                                self.last_conversation_end_time = time.time()
                                self.last_dismissal_reason = 'manual_stop'  # [R6/B6] 标记停止原因
                                self.awake_signal.emit(False)
                                self.interrupt_signal.emit()
                                set_browser_ducking(False)
                                # 🩹 [β.2.7.10 / 2026-05-17] 显式 dismiss → ASR mute 30s
                                # 治 Sir "焦点退出小心翼翼" 痛点: Sir 说"我去打电话"立刻不再录入
                                self.mute_until = max(getattr(self, 'mute_until', 0), time.time() + 30.0)
                                self._bypass_speech_count = 0
                                try:
                                    from jarvis_utils import bg_log as _ds_bg
                                    _ds_bg(f"🤫 [Dismiss] 显式停止指令 → ASR mute 30s ('{clean_text[:40]}')")
                                except Exception:
                                    pass
                                # [R7-β1/post-test] 清字幕
                                try:
                                    if self._subtitle_queue is not None:
                                        self._subtitle_queue.put(("focus", False))
                                        self._subtitle_queue.put(("clear", ""))
                                except Exception:
                                    pass
                                frames_left = stream.get_read_available()
                                if frames_left > 0: stream.read(frames_left, exception_on_overflow=False)
                                continue

                            ghost_hallucinations = [
                                "the.", "the", "no.", "no", "yeah.", "yeah", ".", "i.", "i", "a.", "oh.",
                                "you.", "you", "and.", "and", "to.", "to", "is.", "is", "it.", "it",
                                "he.", "he", "she.", "she", "we.", "we", "they.", "they",
                                "als", "als you", "r as", "robin", "hello joyce", "hello",
                                "mhm.", "mhm", "uh.", "uh", "um.", "um", "hmm.", "hmm",
                                "rs.", "rs", "com.", "com", "jo.", "jo", "da", "da.",
                                "ok.", "ok", "okay.", "okay", "yes.", "yes", "so.", "so",
                                "me.", "me", "my.", "my", "in.", "in", "on.", "on",
                                "at.", "at", "of.", "of", "be.", "be", "do.", "do",
                                # [v4] Sir 23:02:33 实测发现 ASR 把背景杂音听成 "I am" 触发空轮 LLM。
                                # Whisper-class 模型对长尾噪声的典型幻觉就是 "I am" / "thank you" / "you" 等。
                                "i am.", "i am", "i'm", "im",
                                "thank you.", "thank you", "thanks.", "thanks",
                                "bye.", "bye", "goodbye.", "goodbye",
                                "all right.", "all right", "alright.", "alright",
                                "go.", "go", "hi.", "hi", "hey.", "hey", "ha.", "ha",
                                "novice.", "novice", "alice.", "alice", "joice.", "joice",
                                "zice.", "zice", "do all this.", "do all this",
                                "davis.", "davis", "travis.", "service.", "service",
                                "nervous.", "nervous", "harvest.", "harvest",
                                "this.", "this", "that.", "that", "what.", "what",
                                "or.", "or", "as.", "as", "if.", "if", "us.", "us",
                                "all.", "all", "not.", "not", "but.", "but", "are.", "are",
                                "am.", "am", "an.", "an", "has.", "has", "had.", "had",
                                "was.", "was", "were.", "were", "will.", "will", "would.", "would",
                                # [P0+18-a.8 / 2026-05-15] 修 BUG #6: ASR 把 Jarvis 末尾 "It's"/"if"/"or"
                                # 当用户输入。补全英文常见缩写 + 短助词，让 echo 余音被静默丢弃。
                                "it's.", "it's", "its.", "its",
                                "i'll.", "i'll", "i've.", "i've", "i'd.", "i'd",
                                "we'll.", "we'll", "we've.", "we've", "we're.", "we're",
                                "you'll.", "you'll", "you've.", "you've", "you're.", "you're", "your.", "your",
                                "they'll.", "they'll", "they've.", "they've", "they're.", "they're",
                                "that's.", "that's", "there's.", "there's", "here's.", "here's", "where's.", "where's",
                                "what's.", "what's", "who's.", "who's", "how's.", "how's",
                                "won't.", "won't", "don't.", "don't", "can't.", "can't",
                                "couldn't.", "couldn't", "shouldn't.", "shouldn't", "wouldn't.", "wouldn't",
                                "doesn't.", "doesn't", "didn't.", "didn't", "wasn't.", "wasn't", "weren't.", "weren't",
                                "isn't.", "isn't", "aren't.", "aren't", "hasn't.", "hasn't", "haven't.", "haven't",
                                "sir.", "sir", "ma'am.", "ma'am",
                                # Jarvis 常说的尾巴音节（"...Sir." 之后 ASR 偶尔切出来的孤词）
                                "with.", "with", "for.", "for", "from.", "from", "by.", "by", "into.", "into",
                                "very.", "very", "well.", "well", "just.", "just", "now.", "now", "then.", "then",
                                "some.", "some", "any.", "any", "much.", "much", "many.", "many",
                                "let.", "let", "see.", "see", "got.", "got", "get.", "get",
                                # 中文短助词常见 ASR 噪声（jarvis 中文翻译末尾）
                                "嗯", "呃", "啊", "哦", "嗯。", "呃。", "啊。", "哦。", "嗯，", "呃，",
                                "好的", "好的。", "是的", "是的。", "好", "对", "对。",
                            ]
                            # 👇 核心修复：将中文纳入有效信息判定！
                            meaningful_en_words = [w for w in re.findall(r'[a-z]+', clean_text_lower) if len(w) >= 2]
                            zh_chars = re.findall(r'[\u4e00-\u9fa5]', clean_text)
                            
                            # 如果既没有英文单词，也没有中文字符，才算真的没有意义 (纯符号或乱码)
                            has_no_meaning = len(meaningful_en_words) == 0 and len(zh_chars) == 0
                            
                            # 对于纯英文，长度 <=3 极大概率是底噪 ("oh", "ah")，所以拦截；
                            # 但对于中文，即使只有 2 个字符 ("好的", "查询", "谢谢") 也是完全有意义的指令，绝不能拦截！
                            is_too_short = len(clean_text) <= 3 and len(zh_chars) == 0
                            
                            # 终极拦截逻辑：如果太短且没中文、或是已知空耳幻觉、或彻底没内容，才丢弃
                            if is_too_short or clean_text_lower in ghost_hallucinations or has_no_meaning:
                                if not self.in_active_conversation:
                                    set_browser_ducking(False)
                                # [R7-β5] ASR 丢弃 → 清 Listening… 状态
                                self._publish_listening_done()
                                continue

                            # 👇 Bug B 修复：核心回声防御 ——
                            # ASR 转录的文本是否高度疑似 Jarvis 自己最近 12s 说过的话？
                            # 命中即作为麦克风拾到的喇叭余音丢弃，绝不送进 LLM 形成"Jarvis 跟自己对话"。
                            # 这是 16:22:22 那次 "As you wish, muting audio" 死循环的最后一道闸。
                            try:
                                from jarvis_utils import is_recent_jarvis_echo
                                if is_recent_jarvis_echo(clean_text):
                                    if self.DEBUG_ASR:
                                        print(f"\n🔇 [Echo Guard] 检测到 Jarvis 自己的回声，丢弃: '{clean_text[:80]}'")
                                    else:
                                        try:
                                            from jarvis_utils import bg_log
                                            bg_log(f"🔇 [Echo Guard] 丢弃 Jarvis 自己的回声: '{clean_text[:60]}'")
                                        except Exception:
                                            pass
                                    if not self.in_active_conversation:
                                        set_browser_ducking(False)
                                    # [R7-β5] echo 丢弃 → 清 Listening… 状态
                                    self._publish_listening_done()
                                    continue
                            except Exception:
                                pass

                            # 👇 往下继续保留您原来的代码
                            if hasattr(self, 'return_sentinel') and self.return_sentinel:
                                if self.return_sentinel.soft_focus_active:
                                    if self.return_sentinel.validate_soft_focus(clean_text):
                                        # [P0+18-c.13 / 2026-05-15] 改 bg_log 不漏到 acoustic wave 行尾
                                        try:
                                            from jarvis_utils import bg_log as _sf_bg_log
                                            _sf_bg_log("🔒 [Soft Focus] Verified, focus mode locked。")
                                        except Exception:
                                            pass
                                    else:
                                        try:
                                            from jarvis_utils import bg_log as _sf_bg_log
                                            _sf_bg_log("🔇 [Soft Focus] 检测到背景音/非对话，静默退出。")
                                        except Exception:
                                            pass
                                        # [R7-α/B1+B3] 显式 reason='soft_focus_fail'，并补上 B3 漏掉的 last_dismissal_reason
                                        if self.state is not None:
                                            self.state.set_active_conversation(False, reason='soft_focus_fail', source='validate_soft_focus')
                                        else:
                                            self.in_active_conversation = False
                                        self.last_conversation_end_time = time.time()
                                        # [B3 修复] 之前这里只 emit awake_signal 但没标 last_dismissal_reason，
                                        # 导致 wake_weight 把这次错误退出当成 natural（中性），相当于回声/底噪
                                        # 让 Jarvis 退场后又被自家底噪触发误唤醒；现在标成 false_alarm 让 wake_weight
                                        # 把短时间内紧跟的"复唤醒"按"误退出后的恢复"处理（不扣权重）。
                                        self.last_dismissal_reason = 'false_alarm'
                                        self.awake_signal.emit(False)
                                        set_browser_ducking(False)
                                        # [P0+11 / 2026-05-15] soft_focus_fail 退出时也清 Listening… 状态
                                        # 之前 too_short / hallucination / echo 三处补了，soft_focus_fail 漏了
                                        # 导致字幕区"Listening…"残留直到下一次 ASR 成功覆盖
                                        self._publish_listening_done()
                                        continue  

                            # [R6/B5] 改走上下文感知检测 —— "Thanks for that, can you also..." 不再被错判为告别
                            if self.in_active_conversation and self.detect_dismiss_command(clean_text):
                                print("\n💤 [System Standby] 告别指令已接收，进入潜意识状态。")
                                # [R7-α/B1] 显式 reason='dismiss'
                                if self.state is not None:
                                    self.state.set_active_conversation(False, reason='dismiss', source='detect_dismiss_command')
                                else:
                                    self.in_active_conversation = False
                                self.last_conversation_end_time = time.time()
                                self.last_dismissal_reason = 'manual_dismiss'  # [R6/B6] 标记告别原因
                                self.awake_signal.emit(False)
                                # [R7-β1/post-test] 告别 → 清字幕
                                try:
                                    if self._subtitle_queue is not None:
                                        self._subtitle_queue.put(("focus", False))
                                except Exception:
                                    pass
                                cmd = re.sub(r'[，。,.!?？！\s]+$', '', clean_text)
                                if cmd: self._emit_with_attention(cmd)
                                continue

                            # 👇 极简处理：不再打印“神经元捕获残影”等废话，直接发送指令
                            if is_woken_up:
                                if not self.in_active_conversation:
                                    self.awake_signal.emit(True)
                                # [R7-α/B1] 显式 reason='wake'
                                if self.state is not None:
                                    self.state.set_active_conversation(True, reason='wake', source='wake_word_match')
                                else:
                                    self.in_active_conversation = True
                                self.last_interaction_time = time.time()
                                set_browser_ducking(True) 
                                cmd = re.sub(r'[，。,.!?？！\s]+$', '', raw_cmd)
                                if cmd:
                                    self._emit_with_attention(cmd)
                                else:
                                    self._emit_with_attention("jarvis")
                                    set_browser_ducking(False) 
                                    
                            elif self.in_active_conversation:
                                cmd = re.sub(r'[，。,.!?？！\s]+$', '', clean_text)
                                if cmd:
                                    # 🩹 [β.2.7.10 / 2026-05-17] Sir 痛点: 焦点期间不应触发旁路语
                                    # (Sir 打电话/和家人说话/视频音被 ASR 录入 → 不应 trigger Jarvis)
                                    _score, _bd = self.classify_jarvis_directness(cmd)
                                    if _score < 0.3:
                                        # 旁路语 — 静默丢弃, 仅 bg_log 留痕
                                        # 触发"旁路语计数器", 累计 3 次后缩 TIMEOUT
                                        self._bypass_speech_count = getattr(self, '_bypass_speech_count', 0) + 1
                                        try:
                                            from jarvis_utils import bg_log as _by_bg
                                            _by_bg(
                                                f"🔇 [Bypass Speech] 旁路语 score={_score:.2f} "
                                                f"breakdown={_bd} count={self._bypass_speech_count}: "
                                                f"'{cmd[:60]}'"
                                            )
                                        except Exception:
                                            pass
                                        # 连续 3 次旁路语 → 缩 TIMEOUT 让 Jarvis 早点退场
                                        if self._bypass_speech_count >= 3:
                                            self.last_interaction_time = time.time() - (ACTIVE_TIMEOUT - 8.0)
                                            try:
                                                from jarvis_utils import bg_log as _to_bg
                                                _to_bg(
                                                    "🔇 [Bypass Speech] 连续 3 次旁路语 → "
                                                    "缩 ACTIVE_TIMEOUT 让 Jarvis 8s 后自动退场"
                                                )
                                            except Exception:
                                                pass
                                            self._bypass_speech_count = 0
                                    else:
                                        # jarvis-direct, 重置 bypass 计数 + 正常触发
                                        if _score < 0.6:
                                            try:
                                                from jarvis_utils import bg_log as _gz_bg
                                                _gz_bg(
                                                    f"🟡 [Directness Gray] score={_score:.2f} "
                                                    f"breakdown={_bd} '{cmd[:50]}' — 仍触发但灰区"
                                                )
                                            except Exception:
                                                pass
                                        self._bypass_speech_count = 0
                                        self.last_interaction_time = time.time()
                                        set_browser_ducking(True)
                                        self._emit_with_attention(cmd)

                        self.mute_until = time.time() + 1.0

                        frames_left = stream.get_read_available()
                        if frames_left > 0:
                            stream.read(frames_left, exception_on_overflow=False)   
                else:
                    if not is_speaking:
                        pre_roll_buffer.append(data)
                        if self.in_active_conversation and (time.time() - self.last_interaction_time > ACTIVE_TIMEOUT):
                            print("\n💤[System Standby] 专注锁超时，返回潜意识状态。")
                            # [R7-α/B1] 显式 reason='timeout'
                            if self.state is not None:
                                self.state.set_active_conversation(False, reason='timeout', source='active_timeout')
                            else:
                                self.in_active_conversation = False
                            self.last_conversation_end_time = time.time()
                            self.last_dismissal_reason = 'timeout'  # [R6/B6] 标记是"自然超时"，与"用户主动喊停"区分
                            self.awake_signal.emit(False)
                            set_browser_ducking(False)
                            # [R7-β1/post-test] 焦点超时 → 清字幕 + 通知 SubtitleOverlay 退焦点
                            try:
                                if self._subtitle_queue is not None:
                                    self._subtitle_queue.put(("focus", False))
                                    self._subtitle_queue.put(("clear", ""))
                            except Exception:
                                pass

            except Exception as e:
                print(f"⚠️[Audio Nerve 断连]: {e}")
                time.sleep(1)
