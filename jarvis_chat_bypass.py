# -*- coding: utf-8 -*-
"""[P0+19-7 / 2026-05-16] ChatBypass — 主对话循环（最大单类 3003 行）

从 jarvis_nerve.py 拆出。设计原则：
- 接收用户语音 → 主脑 LLM stream → tool 调用 → audio queue → TTS 播放
- Fast Path 优化（_is_simple_one_shot + _C3_ACTION_HAND_COMMANDS 白名单）
- 防幻觉守门（PROMISE/ACTIVATE_PLAN/RESUME_PLAN 结构化标签拆解）
- 音频 / 字幕 / 节奏 queue 多路分发
- _last_circuit_broken_reason / _last_tool_results 暴露给外层 JarvisWorker

依赖：
- KeyRouter (jarvis_key_router)
- Safety helper (jarvis_safety: 结构化标签 / 中文检测 / Fast Path 守卫)
- 各种器官（通过 self.key_router 间接）

向后兼容：jarvis_nerve.py 用 `from jarvis_chat_bypass import ChatBypass` + 旧
`from jarvis_nerve import ChatBypass` 都能继续 work。

注：本文件包含 ChatBypass 用的 `_C3_ACTION_HAND_COMMANDS` 常量（Fast Path 白名单）。
"""

from __future__ import annotations

# [P0+19-final fix 4 / 2026-05-16] 一次性补全标准库 + 第三方常用 import（防 NameError 暴露）
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import random  # noqa: F401
import queue  # noqa: F401
import sqlite3  # noqa: F401
import hashlib  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
import importlib  # noqa: F401
import concurrent.futures  # noqa: F401
import multiprocessing  # noqa: F401
from collections import defaultdict, deque  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
try:
    from google.genai import types  # noqa: F401
except ImportError:
    pass


import os
import re
import json
import time
import threading
import queue
import random
import collections
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional  # noqa: F401

# 跨文件依赖
# [P0+19-final fix 2] 缺失的 google.genai.types + io/sys
from google.genai import types  # noqa: F401
import io  # noqa: F401
import sys  # noqa: F401

from jarvis_safety import (
    _STRUCTURAL_TAGS,
    _STRUCTURAL_TAG_BLOCK_RE,
    _STRUCTURAL_TAG_ANY_RE,
    _strip_structural_tag_blocks,
    _strip_structural_tags_only,
    _is_forming_structural_tag,
    _sentence_is_chinese_lean,
    _CHINESE_CHAR_RE,
)
from jarvis_key_router import KeyRouter  # noqa: F401
from jarvis_llm_reflector import LlmReflector  # noqa: F401

# [P0+19-final fix / 2026-05-16] 补全跨模块依赖（拆分后实例化时才暴露的缺失）
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_blood import JarvisBlood, ExecutionResult, FeedbackSignal  # noqa: F401
except ImportError:
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
except ImportError:
    pass

# [P0+18-c.3 / 2026-05-15] Fast Path "动作类 hand command" 白名单
# 修 Sir 17:25 实测 BUG："看一下 CHROM 进程,帮我关了吧" → find_process 成功后 Fast Path 立刻 break
# kill_process 从未执行,Jarvis 还回 "I couldn't find an exact match"（被 sentence splitter 截断 + 事实错）
#
# 原启发式 `_is_simple_one_shot` 只看用户输入的动作动词（"关了"）+ 1 个 tool 成功 → 就 break
# 但实际跑的 hand command 是 query 类 (find_process),用户的"关了"还没执行。
#
# 双层防护：
# 1. 此处白名单：hand command 必须 ∈ ACTION_HAND_COMMANDS，否则永远不允许 break Fast Path
# 2. _is_simple_one_shot 加查询动词检测："看/查/find/check" 等同存动作动词 → 多步信号,不 break
_C3_ACTION_HAND_COMMANDS = frozenset([
    # process_hands —— 动作类
    'kill_process', 'kill_by_name', 'focus_process', 'start_process',
    # audio_hands / media_control_hands —— 动作类
    'set_volume', 'mute', 'unmute', 'play', 'pause', 'stop',
    'play_pause', 'next_track', 'previous_track', 'volume_up', 'volume_down',
    # system_hands —— 动作类
    'shutdown', 'restart', 'sleep_system', 'lock_workstation',
    # window_hands —— 动作类
    'close_window', 'minimize_window', 'maximize_window', 'focus_window',
    'restore_window', 'move_window', 'resize_window',
    # url_launcher / desktop —— 动作类
    'open_url', 'launch_app', 'open_app', 'open_application', 'launch_application',
    # input_hands —— 动作类
    'type_text', 'press_key', 'click', 'send_keys',
    # notification_hands —— 动作类
    'send_notification', 'notify',
    # text_hands —— 动作类（写)
    'write_file', 'append_file', 'create_file',
    # clipboard_hands —— 动作类（写）
    'set_clipboard', 'copy_to_clipboard',
    # memory_hands —— 动作类（写）
    'save_memory', 'remember', 'forget', 'delete_memory',
    # network_hands —— 动作类
    'send_request', 'post_data',
])


# 🩹 [P0+20-β.2.7.3 / 2026-05-17] splitter helper：识别 organ.command 中间的 .，
# 避免 splitter 在工具名内部切句导致 TTS 念出 "process hands . get top cpu" 类失真。
# 编译一次缓存，所有 splitter 复用，零额外开销。
import re as _re_split_helper
_ORGAN_NAME_LOOKBEHIND = _re_split_helper.compile(
    r'\b(process_hands|file_operator(?:_hands)?|txt_writer_hands\w*|'
    r'system_hands|memory_hands|fuzzy_resolver|ui_control|hippocampus|'
    r'commitment_watcher|return_sentinel|smart_nudge|chat_bypass|'
    r'audio_hands|window_hands|media_control_hands|notification_hands|'
    r'key_health_inspector|input_hands|clipboard_hands|network_hands|'
    r'text_hands|url_launcher|desktop)\s*$', _re_split_helper.IGNORECASE
)


def _find_sentence_split_idx(buffer: str, soft_split: bool = True, is_first_sentence: bool = False) -> int:
    """splitter helper：在 buffer 找下一句的切分位置。-1 表示没有可切位置。

    设计原则（性能第一）：
    - 编译 regex 全局缓存
    - 仅当 char='.' 时做 lookbehind/lookahead (~5us per 点)
    - 不在 organ.command 的 . 处切
    - soft_split=True 时支持 ',;' 软切

    🩹 [P0+20-β.5.9 / 2026-05-19] 加 `is_first_sentence`:
    - False (默认): hard>=20, soft>=15 (原行为，保护后续句 prosody)
    - True (首句): hard>=8, soft>=4 (让首句更早切送 TTS, 减少 Sir 听到首句的延迟)
    根因: 短回复 "Yes, Sir." (9 字符) 现在永远不切, 要等 stream end (~3s)
    才 flush, 然后 render 1.5s = Sir 5s 后才听到. 首句早切让 render 早启动.
    长回复首句 "A fortuitous outcome, Sir." (26 字符) 现在在 i=20 切, 改后
    在 i=4 (',') 切, "A fortuitous" → render → 后续 "outcome, Sir." 跟上.

    详 docs/JARVIS_SOUL_UNIVERSALIZATION.md / β.2.7.3 修法 + β.5.9 BUG-3 fix。
    """
    hard_symbols = {".", "!", "?", "\n"}
    soft_symbols = {",", ";", "，", "；"} if soft_split else set()
    _buf_len = len(buffer)
    # 🩹 [β.5.9] 首句激进切, 后续保守
    _hard_min = 8 if is_first_sentence else 20
    _soft_min = 4 if is_first_sentence else 15
    for i, char in enumerate(buffer):
        if char in hard_symbols:
            if char == '.':
                # lookbehind: . 左边是否为 organ 名
                if _ORGAN_NAME_LOOKBEHIND.search(buffer[:i]) and \
                        i + 1 < _buf_len and buffer[i + 1].isalnum():
                    continue
            if char == '\n' or i >= _hard_min:
                return i
        elif soft_split and char in soft_symbols:
            if i >= _soft_min and _buf_len > i + 5:
                lookahead = buffer[i + 1:i + 6].lower()
                if not lookahead.startswith(" sir") and not lookahead.startswith(" jar"):
                    return i
    return -1


# 🆕 [P5-fix35 / 2026-05-23] vision capability detect for main brain model.
# Sir 真测踩 BUG: 切 deepseek/v4-pro (text-only) → 强带截图 → 404 'No endpoints
# found that support image input'. 治本: 白/黑名单 prefix check, text-only
# model 跳过 ImageGrab. 列表保守, 新 model 默认 text-only (安全 fallback).
# 准则 6 持久化暂不做 (这是 OpenRouter platform 事实, 不是 Sir 用户偏好).
_VISION_CAPABLE_MODEL_PREFIXES = (
    'google/gemini-',         # G3F / G2.5-pro / G2.5-flash 全 vision
    'gpt-4',                  # GPT-4o / GPT-4-vision
    'openai/gpt-4',
    'anthropic/claude-3',     # Sonnet/Opus 都 vision
    'anthropic/claude-4',
    'xiaomi/mimo-v2.5',       # omnimodal (Sir 测过)
    'xiaomi/mimo-vl',         # MiMo Vision Language
    'qwen/qwen-vl',           # Qwen VL 系列
    'qwen/qwen2-vl',
    'qwen/qwen2.5-vl',
    'meta/llama-3.2-vision',  # Llama vision
)


def _model_supports_vision(model_name: str) -> bool:
    """Return True if model accepts image input (chat_history can include image_url parts).

    保守判: 在白名单 prefix 列表内 → True, 否则 False (默认 text-only).
    新 model Sir 试时若是 vision-capable, 加 prefix 进 _VISION_CAPABLE_MODEL_PREFIXES.
    """
    if not model_name:
        return False
    m = model_name.lower().strip()
    return any(m.startswith(p) for p in _VISION_CAPABLE_MODEL_PREFIXES)


# 🆕 [Sir 2026-05-26 23:24 真痛 BUG-1 治本 / 准则 8 优雅高效]
# =============================================================================
# Sir 截图 22:41:32: ZH "确实是个昂贵的疏" (8ch 末尾 '疏' 不合法) 先显在字幕,
# 1-2s 后 truncate_continuation_worker 补 99ch 完整版替换 → Sir 体感"字幕变身闪烁".
#
# 治本 (准则 8 优雅): stream 末了 leftover ZH put 前 check 末尾合法性,
# 不合法 → skip put (等 worker continuation 补一次完整 atomic 出, Sir 看 0ch → 99ch).
# 合法 → 正常 put (无 worker continuation 需求, atomic 一次出全).
#
# _zh_endings 与 line 4610 同集 (修一处 = 修两处 一致). 提到 module level 复用.
# =============================================================================
_ZH_SUBTITLE_ENDINGS = set('.?!。？！…"\'""''」』）)')


def _zh_subtitle_looks_truncated(zh_text: str, en_len: int) -> bool:
    """check ZH text 末尾是否合法 (信赖 line 4612 same logic).

    True = 不合法 (LLM stream 半途 stop), 应 defer put 等 worker continuation.
    False = 合法 (末尾标点/引号收束), 正常 leftover put.
    en_len < 30 → 短 reply 不检 (允许 ZH 末尾无标点 e.g. '好').
    """
    if not zh_text:
        return False  # 空 ZH 由上游 logic 决定 (此 helper 不管空)
    if en_len < 30:
        return False  # 短 reply 不检
    return zh_text[-1] not in _ZH_SUBTITLE_ENDINGS


class ChatBypass:
    def __init__(self, key_router, vocal_cord, state_callback):
        self.key_router = key_router
        self.model_name = 'gemini-3-flash-preview'  # legacy meta (test guard)
        # 🆕 [P5-fix34 / 2026-05-23] env override — A/B 测试 V4 Pro vs G3F.
        # Sir 设 JARVIS_MAIN_BRAIN=deepseek/deepseek-v4-pro 切主脑.
        # 默认保持 G3F (向后兼容). 仅作用 _create_stream + OR fallback path,
        # translation / gatekeeper / soul evaluator 等独立任务保持 G3F.
        self.main_brain_model = os.getenv(
            'JARVIS_MAIN_BRAIN', 'google/gemini-3-flash-preview')
        # 🆕 [P5-fix35 / 2026-05-23 10:50] vision capability detect
        # Sir 真测踩 BUG: 切 deepseek/v4-pro (text-only) → 强带截图 → 404.
        # 治本: 主对话 / nudge 路径前 check 当前 model 是否支持 image input.
        # text-only model → 跳过 ImageGrab + 只发 text prompt (主脑无视觉但能跑).
        self.main_brain_supports_vision = _model_supports_vision(self.main_brain_model)
        self.vocal = vocal_cord
        self.state_callback = state_callback
        
        self.audio_queue = queue.Queue() 
        self.wave_queue = queue.Queue()  # 👈 重新建好音频仓库
        self.rhythm_queue = queue.Queue()
        self.translate_queue = queue.Queue() 
        self.subtitle_queue = queue.Queue() 
        
        # 后置幻觉守门用：每次 stream_chat 会重写为新空列表，与内部 _tool_results 共引用
        self._last_tool_results = []
        # [P1] 工具链熔断原因暴露给外层 JarvisWorker，让 B 守门人能拿到
        # —— 即使 _tool_results 有内容（含失败），也可能 LLM 实际没成功完成动作而仍声称"已搞定"
        self._last_circuit_broken_reason = None

        # 🩹 [β.2.9.10 / 2026-05-18] Sir 11:09 工具卡顿治本: FAST_CALL 异步执行.
        # 旧版 _execute_fast_call 同步阻塞 1-5s, splitter 卡停, Sir 听不到声 → 体感"卡顿".
        # 治本: 短超时 (1.5s) 同步等, 超时 → 主 stream 立刻继续, tool 后台跑完
        # 把 result 写入 _pending_tool_results, 下一轮 prompt 注入让主脑看到.
        self._tool_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=3, thread_name_prefix='FastCallAsync')
        self._pending_tool_results = []   # [{organ, command, result, ts}, ...]
        self._pending_tool_lock = threading.Lock()
        self.TOOL_SOFT_TIMEOUT_S = 1.5    # 超过此值放手, 主 stream 不卡

        # [R7/Screenshot] 之前的 60s 缓存已废弃 —— JPEG quality=50 + 1280x720 已经很小，
        # 实时截屏（~30-80ms）的代价远低于"看见的不是用户正在指的画面"的代价。
        # 仅 WAKE_ONLY 档（只喊名字）跳过截图，其余档全部实时截。
        self._screenshot_cache = None  # 保留属性占位，避免外部访问出错；不再写入

        # [R7-α/B8] _render_worker / _play_worker 共用的"渲染中"标志位
        # _render_worker 进入 vocal.render_only 前置 True，wave_queue.put 后才置 False。
        # _play_worker 在 wave_queue 空一帧时先看这个标志：True 则说明下一帧马上到，
        # 不能 emit IDLE 缩短回声防御窗口。
        self._render_in_progress = False

        # 🩹 [P0+20-β.5.9 / 2026-05-19] BUG-3 诊断 Audio Trace 已退役
        # β.5.10 prompt encoding cache 落地后 Sir 实测确认 render 6.67s→1.9-2.4s,
        # 诊断使命已完成. 下次再需诊断从 git 恢复 β.5.9 timing log 即可.

        # 🩹 [P0+20-β.1.25 / 2026-05-16] Nudge anti-repeat 历史
        # Sir 反馈："回归问候/催睡固定句式我看了 5-6 遍" — 因为 directive + STM + LLM 一样
        # 导致 LLM 倾向于复用熟悉句式。修法：每个 nudge_type 维护最近 5 条 reply 开头，
        # 下次同 type 触发时显式塞进 prompt 说"FORBIDDEN openings — NEVER reuse"。
        from collections import defaultdict as _defaultdict
        self._nudge_recent_phrases: dict = _defaultdict(list)
        self._NUDGE_RECENT_MAX = 5

        # [R7-β2 v5/Sir-2026-05-14] Backchannel chime 已删除（与 play_acknowledgment_chime 重复）。
        # [轴 2.4 / 2026-05-15] 启用本地短句 PCM 池作为"思考期反馈"的真正方案：
        #   - 启动时预渲 5 句（"On it.", "One moment.", "Pulling that up.", "Bear with me." 等）
        #   - TTFT > 2.5s 时按 prompt_tier 选 phrase → vocal.play_only(pcm) 零延迟
        #   - 比 chime 多了"语义匹配"，比 vocal.say 同步调用快 10 倍
        self._first_token_received = False
        self._backchannel_timer = None
        # [轴 2.4] 本地短句 PCM 缓存（启动 daemon 异步填充，不阻塞 ChatBypass 构造）
        self._local_phrase_pool = {}
        self._local_phrase_pool_lock = threading.Lock()
        self._local_phrase_pool_ready = False
        # 启动预渲 daemon —— 复用 VocalCord 的 GPU 暖机
        try:
            threading.Thread(target=self._warmup_local_phrase_pool, daemon=True,
                             name='LocalPhrasePoolWarmup').start()
        except Exception:
            pass
        # [R7-β2 v3] 本地"说一句话"二级 backchannel：TTFT > 2.5s 才触发
        # 当云端真的慢（超过 2.5s）时，本地用 vocal.say 念一句过渡话，
        # 让用户从"它在思考"升级到"它跟我对上话了"。
        self._local_utterance_timer = None
        self._local_utterance_in_progress = False
        
        threading.Thread(target=self._render_worker, daemon=True, name='TTS-Render').start()
        threading.Thread(target=self._play_worker, daemon=True, name='TTS-Play').start()
        threading.Thread(target=self._translate_worker, daemon=True, name='TTS-Translate').start()

    # [R7-β2 v5/Sir-2026-05-14] _generate_backchannel_pcm 已删除（与 play_acknowledgment_chime 重复）。

    # [轴 2.4 / 2026-05-15] 本地短句 PCM 池配置 —— 取代 v3 罐头随机抽路径
    # 每条 phrase 在启动时用 vocal.render_only() 预渲成 PCM bytes，存入 _local_phrase_pool。
    # TTFT > _LOCAL_PHRASE_THRESHOLD 时按 prompt_tier 选 phrase → vocal.play_only(pcm)。
    # 设计原则：
    #   - 按 tier 选，不按 user_input 关键词（避免 v3 的"语气割裂"）
    #   - 每条 phrase 都"语义中性 + 礼貌" —— 和云端 LLM 后续回复自然衔接
    #   - WAKE_ONLY / SHORT_CHAT 不补位（这些档 TTFT 通常 < 1s，没必要）
    _LOCAL_PHRASE_POOL_SPEC = {
        # key: (en_text, kind)，kind 用于回声防御日志
        'on_it':       "On it, Sir.",          # TOOL_REQUEST
        'one_moment':  "One moment, Sir.",     # DEEP_QUERY / CRITICAL
        'pulling_up':  "Pulling that up, Sir.",  # FACTUAL_RECALL
        'bear_with':   "Bear with me, Sir.",   # > 4s 极慢响应
        'let_me_see':  "Let me see.",          # 兜底
    }
    # 按 prompt_tier 选 phrase key 的路由表（None 表示该档不补位）
    # [P0-5 / 2026-05-15] CRITICAL 改成 None —— 排期/纠正/记忆操作之后的真实回复
    # 总是结构化确认（"Reminder set for ... Sir." / "Updated to ... Sir."），
    # 前面甩一句 "One moment, Sir." 反而和后续语气割裂（Sir 实测反馈）。
    # 真正慢的 CRITICAL 场景留给云端 LLM 自己说，本地不插话。
    # [P0+18-a.9 / 2026-05-15] 修 BUG #8: TOOL_REQUEST 改成 None —
    # Sir 实测 "调音量到 35%" Fast Path ~3s 就完成，"On it, Sir." 预渲反而和 "Done, Sir." 割裂；
    # 真正慢响应（DEEP_QUERY / FACTUAL_RECALL）保留预渲过渡话。
    _LOCAL_PHRASE_TIER_ROUTE = {
        'TOOL_REQUEST':    None,    # [P0+18-a.9] Fast Path 不补位（~3s 就出 "Done, Sir."）
        'DEEP_QUERY':      'one_moment',
        'CRITICAL':        None,    # [P0-5] 改成不补位
        'FACTUAL_RECALL':  'pulling_up',
        'SHORT_CHAT':      None,  # 不补位（短聊很快）
        'WAKE_ONLY':       None,  # 不补位
    }
    # [P0+18-a.9 / 2026-05-15] 阈值 2.5s → 3.5s：大部分慢响应 6-15s 才有意义补位
    # 🩹 [β.2.7.8 / 2026-05-17] 3.5s → 10s (Sir 反馈: 3-4s 基本回复了，没必要插入 "One moment")
    # 10s 才触发预渲补位 — 只在 LLM 真卡时才填充
    _LOCAL_PHRASE_THRESHOLD = 10.0  # TTFT > 10s 才触发预渲补位

    def _warmup_local_phrase_pool(self):
        """[轴 2.4] 启动时一次性预渲所有短句的 PCM 字节。
        
        daemon 线程跑，不阻塞 ChatBypass 构造。
        VocalCord 自带显存预热（"Systems fully operational."），完成后才能渲；
        所以我们先 sleep 一小会儿等 vocal 就绪，然后逐句渲。
        """
        try:
            # 等 vocal 暖机完毕（VocalCord.__init__ 末尾会渲一句预热）
            time.sleep(2.0)
            if not hasattr(self, 'vocal') or self.vocal is None:
                return
            from jarvis_utils import register_jarvis_tts, bg_log
            pool = {}
            for key, text in self._LOCAL_PHRASE_POOL_SPEC.items():
                try:
                    pcm = self.vocal.render_only(text)
                    if pcm:
                        pool[key] = (pcm, text)
                        # 顺手注册到回声指纹环，运行期 play_only 后 ASR 不会拾回
                        register_jarvis_tts(text)
                except Exception:
                    continue
            with self._local_phrase_pool_lock:
                self._local_phrase_pool = pool
                self._local_phrase_pool_ready = True
            try:
                bg_log(f"🎤 [Local Phrase Pool] 预渲 {len(pool)} 条短句完毕，"
                       f"TTFT > {self._LOCAL_PHRASE_THRESHOLD}s 时按 tier 路由播放")
            except Exception:
                pass
        except Exception:
            pass

    def _get_local_phrase_for_tier(self, prompt_tier: str):
        """按 tier 拿一条预渲好的 PCM。返回 (pcm_bytes, text) 或 None"""
        route_key = self._LOCAL_PHRASE_TIER_ROUTE.get(prompt_tier or '', 'let_me_see')
        if route_key is None:
            return None
        with self._local_phrase_pool_lock:
            if not self._local_phrase_pool_ready:
                return None
            return self._local_phrase_pool.get(route_key)

    # [R7-β2 v3] 本地"说一句话"过渡词池 —— 根据 user_input 关键词选最合适的一句
    _LOCAL_UTTERANCE_POOL = {
        'tool': [
            ("On it, Sir.", "马上。"),
            ("Right away.", "好的。"),
            ("Let me handle that.", "我来处理。"),
        ],
        'recall': [
            ("Let me check, Sir.", "让我看看。"),
            ("Pulling that up.", "正在调出。"),
        ],
        'query': [
            ("Hmm, let me think.", "嗯，我想想。"),
            ("One moment, Sir.", "稍等一下。"),
            ("Bear with me.", "请稍候。"),
        ],
        'casual': [
            ("Mm.", "嗯。"),
            ("Let me see.", "让我看看。"),
            ("Right.", "好的。"),
        ],
    }

    def _pick_local_utterance(self, user_input: str = "") -> tuple:
        """根据 user_input 关键词决定走哪个池，返回 (en, zh) 一句话。"""
        try:
            ui = (user_input or "").lower()
            # 工具类（动作动词）
            if any(kw in ui for kw in ('打开', '关闭', '调', '搜', '设置', '播放', 'open', 'close',
                                        'set', 'play', 'launch', 'turn')):
                pool = self._LOCAL_UTTERANCE_POOL['tool']
            elif any(kw in ui for kw in ('刚', '上次', '昨天', '前天', '之前', 'just', 'last time',
                                          'remember', 'recall')):
                pool = self._LOCAL_UTTERANCE_POOL['recall']
            elif any(kw in ui for kw in ('为什么', '怎么', '是什么', '解释', 'why', 'how', 'what',
                                          'explain', 'tell me')):
                pool = self._LOCAL_UTTERANCE_POOL['query']
            else:
                pool = self._LOCAL_UTTERANCE_POOL['casual']
            # 用 hash(user_input + 时间秒) 做 deterministic 但每次稍变的随机选
            import time as _t
            idx = (hash(ui) ^ int(_t.time())) % len(pool)
            return pool[idx]
        except Exception:
            return ("Mm.", "嗯。")

    # [R7-β post-test v4] Sir 实测反馈："这个贾维斯出声的体验不太好，除了特别长的，
    # 我觉得没必要加，而且加的内容感觉和我问句无关会有点奇怪……第一句和后面的语气可能不一样"。
    # 决定：
    # - 本地补位（"One moment, Sir." / "Let me see." 等罐头）→ **完全禁用**（内容与问题无关 + 语气割裂）
    # - chime（短 UI"叮"）→ **阈值从 0.6s 提到 1.5s**：典型 TTFT 0.6-1.2s 不再响，只有真的慢（>1.5s）才提示
    # 注：阈值提升在调用方 stream_chat 那里改（不在 _start_backchannel_timer 内部硬抬），
    # 这样 backchannel 单元测试可以继续显式传 threshold_sec=0.1 等小值验证 timer 机制
    _LOCAL_UTTERANCE_ENABLED = False
    _CHIME_THRESHOLD_DEFAULT = 1.5
    # [轴 2.4 / 2026-05-15] 新一代本地短句 PCM 池总开关（取代 _LOCAL_UTTERANCE_ENABLED）
    # 与 v3 老路区别：按 prompt_tier 选 phrase（不按 user_input 关键词），且播预渲 PCM 而非 vocal.say
    _LOCAL_PHRASE_POOL_ENABLED = True

    def _start_backchannel_timer(self, threshold_sec: float = 0.6,
                                 user_input: str = "",
                                 local_utterance_threshold: float = 2.5,
                                 prompt_tier: str = None):
        """[轴 2.4 / 2026-05-15] 启动本地短句 PCM 池补位 timer：
        
        - threshold_sec → 历史 chime 阈值（v5 chime 已删，参数保留兼容老调用，无副作用）。
        - local_utterance_threshold → 本地短句补位阈值（默认 2.5s）。轴 2.4 起改成播预渲 PCM，
          按 prompt_tier 路由选 phrase（不再随机抽 v3 那种罐头池）。
        - prompt_tier → 决定播哪条 phrase（TOOL_REQUEST→"On it" / DEEP_QUERY→"One moment" 等）。
        
        首 token 到达时 _mark_first_token 取消所有未触发的 timer。
        """
        import threading
        self._first_token_received = False
        # 取消旧 timer（如果有）
        try:
            if self._backchannel_timer is not None:
                self._backchannel_timer.cancel()
                self._backchannel_timer = None
        except Exception:
            pass
        try:
            if self._local_utterance_timer is not None:
                self._local_utterance_timer.cancel()
        except Exception:
            pass

        # —— chime 一档已删除（v5）：原 _maybe_play_chime + Timer 整块移除 ——
        # 保留 _backchannel_timer = None 以保持 _mark_first_token 接口兼容

        # —— 本地短句 PCM 池（轴 2.4）：TTFT > local_utterance_threshold 时触发 ——
        # 与 v3/v4 的"按 user_input 关键词随机抽"不同，2.4 走 prompt_tier 路由
        # 播预渲好的 PCM 字节 → vocal.play_only(pcm) 零延迟，无 vocal.say 同步阻塞

        def _maybe_say_local():
            # 老总开关（兼容老测试）：默认 False 时短路；轴 2.4 之后 _LOCAL_PHRASE_POOL_ENABLED=True 即可
            if not getattr(self, '_LOCAL_PHRASE_POOL_ENABLED', False):
                if not getattr(self, '_LOCAL_UTTERANCE_ENABLED', False):
                    return
            if self._first_token_received:
                return
            if getattr(self, 'is_interrupted', False):
                return
            if self._local_utterance_in_progress:
                return
            # 按 tier 拿预渲 PCM
            picked = self._get_local_phrase_for_tier(prompt_tier)
            if not picked:
                return  # 这一档不补位、或池还没预渲好
            pcm, text = picked
            try:
                self._local_utterance_in_progress = True
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🎤 [Local Phrase] TTFT > {local_utterance_threshold}s, "
                           f"tier={prompt_tier or '?'}, 播预渲: \"{text}\"")
                except Exception:
                    pass
                # 延长 mute_until（预渲 PCM 播放 ~0.4-0.8s）
                try:
                    vt = getattr(getattr(self, 'jarvis', None), 'voice_thread', None)
                    if vt is not None:
                        vt.mute_until = max(getattr(vt, 'mute_until', 0.0),
                                            time.time() + 1.2)
                except Exception:
                    pass
                # vocal.play_only(pcm) —— 零延迟，预渲已完成
                self.vocal.play_only(pcm)
                # 字幕飘一行
                try:
                    self.subtitle_queue.put(("silent_nudge", f"🤔 {text}"))
                except Exception:
                    pass
            except Exception:
                pass
            finally:
                self._local_utterance_in_progress = False

        self._local_utterance_timer = threading.Timer(local_utterance_threshold,
                                                      _maybe_say_local)
        self._local_utterance_timer.daemon = True
        self._local_utterance_timer.start()

    def _mark_first_token(self):
        """[R7-β2] 收到首个可见 token 时调。取消未触发的 timer。
        已开始播放的本地话不打断（让用户听完更自然）。"""
        self._first_token_received = True
        try:
            if self._backchannel_timer is not None:
                self._backchannel_timer.cancel()
                self._backchannel_timer = None
        except Exception:
            pass
        try:
            if self._local_utterance_timer is not None:
                self._local_utterance_timer.cancel()
                self._local_utterance_timer = None
        except Exception:
            pass

    def _put_audio(self, text: str, is_response: bool = True):
        # 🆕 [P5-fix25-stand-down / 2026-05-22] Stand Down 模式 — TTS 静默
        # active 时彻底拦 audio_queue.put — 主脑可能仍生成 voice 文本, 但
        # TTS 不出声 (字幕仍走 — subtitle_queue 不在这里). 字幕在另一路径.
        try:
            import jarvis_stand_down as _sd
            if _sd.should_silence_voice() and text:
                # 节流 log: 第一句 + 每分钟一次, 防刷屏
                try:
                    _last = getattr(self, '_stand_down_audio_log_at', 0)
                    if time.time() - _last > 60:
                        from jarvis_utils import bg_log as _sd_bg
                        _sd_bg(f"🔇 [StandDown/Audio] 拦截 TTS: '{text[:40]}...' "
                                  f"(voice silenced, 字幕仍走)")
                        self._stand_down_audio_log_at = time.time()
                except Exception:
                    pass
                return
        except Exception:
            pass

        # [P0+18-c.1 / 2026-05-15] 最后一道防线：拦截结构化标签 block 漏到 TTS。
        # 上游 stream_chat / stream_chat_cloud_followup 已 5 处剥块，这里兜底防回归。
        # 检测条件：(a) 含明显 tag 字面 (b) 含 PROMISE/ACTIVATE_PLAN 典型 JSON 字段 ("goal" + "steps")
        try:
            if text:
                _has_tag = any(t in text for t in ('<PROMISE>', '<ACTIVATE_PLAN>', '<CANCEL_PLAN>', '<RESUME_PLAN>', '<FAST_CALL>'))
                _has_json_signature = '"goal"' in text and ('"steps"' in text or '"skill"' in text)
                if _has_tag or _has_json_signature:
                    _orig = text
                    text = _strip_structural_tag_blocks(text)
                    text = _strip_structural_tags_only(text)
                    try:
                        from jarvis_utils import bg_log as _struct_bg
                        _struct_bg(f"⚠️ [Audio Guard] 拦截结构化标签 JSON 漏到 TTS: '{_orig[:80]}' → '{text[:80]}'")
                    except Exception:
                        pass
                    if not text.strip():
                        return
        except Exception:
            pass

        # 🆕 [Sir 2026-05-24 22:00 真测 META 泄漏字幕 BUG] 末路守门
        # 上游 splitter 已加 [META] 切 (双处, line 2305+ / 3178+), 这里兜底防回归.
        # 任何 text 含 [META] 直接拒收 audio (TTS 不念这种非自然语言, 防 cosyvoice 卡).
        # 🆕 [Sir 2026-05-24 22:57 audit BUG #4 治本] case-insensitive + 中英括号.
        # 主脑可能 emit [META] / [Meta] / [meta] / 【META】 (中文括号) 任一变体, 全拦.
        try:
            import re as _re_meta
            _META_RE = _re_meta.compile(r'[\[【]\s*meta\s*[\]】]', _re_meta.IGNORECASE)
            if text and _META_RE.search(text):
                _orig_meta = text
                # 截 META 之前 — 后续若 sentence 仅是 META 则直接 return
                text = _META_RE.split(text, 1)[0].rstrip()
                if not text:
                    return
                try:
                    from jarvis_utils import bg_log as _meta_bg
                    _meta_bg(f"⚠️ [Audio Guard] 拦截 [META] 漏到 TTS: '{_orig_meta[:80]}' → '{text[:60]}'")
                except Exception:
                    pass
        except Exception:
            pass

        # 🩹 [β.5.28-fix7 / 2026-05-20] Sir 03:22 实测 TTS 输出末尾 '---ZH' (partial marker).
        # Root cause: stream 末 buffer 含 LLM 输出截断的 partial '---ZH' (没等到完整 '---ZH---').
        # 老 5 处 splitter 末尾 flush 只查完整 '---ZH---', miss partial → TTS 念出 'ZH'.
        # 修法: _put_audio 单点守门, 末尾任意 '-{1,}\s*Z?H?-*' marker 残段一律剥.
        try:
            import re as _re_partial_zh
            if text:
                _orig_partial = text
                # 剥末尾 partial marker: '---' / '---Z' / '---ZH' / '---ZH-' / '---ZH--' / 残缺间隔
                text = _re_partial_zh.sub(r'-{2,}\s*[Zz]?[Hh]?-*\s*$', '', text).rstrip()
                if text != _orig_partial:
                    try:
                        from jarvis_utils import bg_log as _zh_partial_log
                        _zh_partial_log(f"🛡️ [Audio Guard β.5.28-fix7] 剥末尾 partial ZH marker: '{_orig_partial[-30:]}' → '{text[-30:]}'")
                    except Exception:
                        pass
        except Exception:
            pass

        # [P0+18-a.14 / 2026-05-15] 修 BUG #9: 第一句对话念中文
        # 兜底守门：任何送进 audio_queue 的文本若含 [\u4e00-\u9fa5]，
        # 立即 strip 中文 + bg_log 警告。Jarvis 是英文 TTS（CosyVoice 用英文 prompt zero-shot），
        # 不应该念中文；中文走 subtitle_queue → UI 字幕。
        # 这是 belt-and-suspenders 兜底，上层每条嫌疑路径也会逐一修。
        try:
            import re as _re_zh_guard
            if text and _re_zh_guard.search(r'[\u4e00-\u9fa5]', text):
                _orig = text
                # 优先按 ---ZH--- 标签切；切不到就按位置删中文
                if '---ZH---' in text:
                    text = text.split('---ZH---')[0].strip()
                else:
                    text = _re_zh_guard.sub(r'[\u4e00-\u9fa5，。！？；：、""''（）【】《》]+', ' ', text).strip()
                    text = _re_zh_guard.sub(r'\s+', ' ', text).strip()
                try:
                    from jarvis_utils import bg_log as _zh_bg
                    _zh_bg(f"⚠️ [Audio Guard] 拦截含中文的 TTS 输入: '{_orig[:60]}' → '{text[:60]}'")
                except Exception:
                    pass
                if not text:
                    # 中文全 strip 后什么都没剩 → 直接吞掉，不入队
                    return
        except Exception:
            pass

        # 🩹 [P0+20-β.1.24 / 2026-05-16] B13 修：拦截 LLM 漏说工具名（治 Sir 20:47 反馈）。
        # 实测："may I run process_hands.list_processes for you?" 完整说出工具名 → 人机感极强。
        # 修法：_put_audio 入口检测 `<organ>.<command>` 模式，替换成自然短语再走 TTS。
        # 字幕 / STM 仍保留原句（让 Sir 调试时看清 LLM 想说啥），只动 audio 路径。
        try:
            if text:
                import re as _re_tool
                _TOOL_NAME_RE = _re_tool.compile(
                    r'\b(process_hands|file_operator(?:_hands)?|txt_writer_hands\w*|system_hands|'
                    r'memory_hands|fuzzy_resolver|ui_control|hippocampus|'
                    r'commitment_watcher|return_sentinel|smart_nudge|chat_bypass)'
                    r'\.\w+', _re_tool.IGNORECASE
                )
                if _TOOL_NAME_RE.search(text):
                    _orig_for_log = text
                    # 替换工具名为"a quick check"等自然短语
                    text = _TOOL_NAME_RE.sub('a quick check', text)
                    # 去掉残留的"may I run a quick check" 中 "run" 多余感（轻 polish）
                    text = _re_tool.sub(r'\b(run|invoke|execute|trigger)\s+a\s+quick\s+check',
                                        'a quick check', text, flags=_re_tool.IGNORECASE)
                    try:
                        from jarvis_utils import bg_log as _tool_bg
                        _tool_bg(
                            f"🔇 [Audio Guard / Tool Name] 拦截工具名漏到 TTS: "
                            f"'{_orig_for_log[:80]}' → '{text[:80]}'"
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        # 🩹 [P0+20-β.1.14 / 2026-05-16] B12 修：拦截孤立单词 done-claim（治割裂感）。
        # Sir 15:58 实测：LLM 在 FAST_CALL 后习惯性输出孤立"Done"或"OK"（1-2 词），
        # CosyVoice 克隆短句 prosody 无上下文 → 严重失真 → 主对话框里 "Understood, Sir.
        # Done Done, Sir - already completed" 中间那个"Done"听感断裂。
        # 修法：1 词的 done-claim 类抢答词不送 TTS（字幕仍走，让 Sir 看见，但不刺耳）。
        try:
            if text:
                import re as _re_orphan
                # 剥所有标点/空白后还原成单词集合
                _toks = _re_orphan.findall(r"[a-zA-Z]+|['\u4e00-\u9fa5]+", text)
                if len(_toks) <= 1:
                    _normalized = (_toks[0].lower() if _toks else "")
                    _ORPHAN_DONE_WORDS = {
                        'done', 'ok', 'okay', 'okie', 'okey', 'sure', 'fine',
                        'set', 'fixed', 'adjusted', 'opened', 'closed', 'completed',
                        'understood', 'noted', 'acknowledged', 'right', 'yep', 'yeah',
                        # 中文同款
                        '好', '好的', '是', '是的', '行', '行了', '嗯', '可以', '完成', '完毕',
                    }
                    if _normalized in _ORPHAN_DONE_WORDS:
                        try:
                            from jarvis_utils import bg_log as _orphan_bg
                            _orphan_bg(
                                f"🔇 [Audio Guard / Orphan Done] 拦截孤立 done-claim TTS: '{text[:30]}' "
                                f"(LLM 在 FAST_CALL 后习惯性抢答，CosyVoice 短句失真避免)"
                            )
                        except Exception:
                            pass
                        return
        except Exception:
            pass

        # 🛡️ Bug K 防御性去重：如果最近 2 秒内已经把"完全相同的短句"丢进过 audio_queue，
        # 直接吞掉。这是兜底 —— 即便上层逻辑出现 splitter + end-flush 双发，TTS 也不会念两遍。
        # 只针对短句（<= 40 字符），避免长段落正常变化文本被误吞。
        if text and len(text) <= 40:
            now = time.time()
            try:
                last_text = getattr(self, '_last_audio_text', None)
                last_ts = getattr(self, '_last_audio_ts', 0)
                if last_text == text and (now - last_ts) < 2.0:
                    # 静默丢弃同一短句的二次入队
                    return
                self._last_audio_text = text
                self._last_audio_ts = now
            except Exception:
                pass
        self.audio_queue.put(text)

    def _create_stream(self, contents, enable_search=False):
        _t_key_start = time.time()
        key, key_name, _provider = self.key_router.get_key(KeyRouter.CALLER_MAIN_BRAIN, 'flash')
        _t_key_done = time.time()
        try:
            from openai import OpenAI
            import base64
            import httpx as _httpx_b512

            messages = []
            for content in contents:
                role = content.role if hasattr(content, 'role') else 'user'
                if role == 'model':
                    role = 'assistant'
                msg_parts = []
                for part in content.parts:
                    if hasattr(part, 'text') and part.text:
                        msg_parts.append({"type": "text", "text": part.text})
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        img_b64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                        msg_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{part.inline_data.mime_type};base64,{img_b64}"}
                        })
                messages.append({"role": role, "content": msg_parts})

            or_model = self.main_brain_model  # 🆕 P5-fix34 env override

            # 🩹 [P0+20-β.5.12 / 2026-05-19] BUG-B: chunk inter-arrival timeout 12s
            # Sir 21:37 实测: cloud stream 半路 server close TCP, client 干等 18.8s 才
            # 报 RemoteProtocolError. 老 float 60s 是 *total* request 超时, 不是 chunk
            # 间隔超时. httpx.Timeout(read=12.0) 含义: "server 12s 不发任何字节 → ReadTimeout".
            # 🆕 [P5-fix77-I / 2026-05-23 19:11] BUG-I 真因: read=12.0 太严, 主脑 reasoning
            # 时偶尔 > 12s 思考间隔 → 半截截断. Sir 19:04 真测: "I" (5 char), "I've adjusted
            # to 2300" 等截断. 调 read=25.0 给主脑足够 reasoning 时间, 但仍不死等.
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=key,
                default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
                timeout=_httpx_b512.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
            )

            # 🆕 [P5-fix77-I / 2026-05-23 19:11] max_tokens 显式设 8192 防 SDK default
            # 太短 (某些 OpenRouter model default 仅 1024-2048 → 长 reply 中途 stop).
            # 主脑 reply 通常 ≤ 2000 tokens, 8192 留 4x 余量盖最长 case.
            response = client.chat.completions.create(
                model=or_model,
                messages=messages,
                temperature=0.7,
                max_tokens=8192,
                stream=True
            )

            class _ChunkWrapper:
                __slots__ = ('text',)
                def __init__(self, text):
                    self.text = text

            def _stream_wrapper():
                _final_finish_reason = None
                _total_chunks = 0
                _total_chars = 0
                for chunk in response:
                    _total_chunks += 1
                    if chunk.choices:
                        ch = chunk.choices[0]
                        if ch.delta.content:
                            _total_chars += len(ch.delta.content)
                            yield _ChunkWrapper(ch.delta.content)
                        # 🆕 [P5-fix79 BUG-T / 2026-05-23 21:36] log finish_reason
                        # Sir 21:33 真测: stream 31 char 后停, max_tokens=8192 没用.
                        # finish_reason='length'? 'stop'? 'content_filter'? 'error'?
                        # 不 log 永远不知道. 加 1 行 bg_log 找真因.
                        if getattr(ch, 'finish_reason', None):
                            _final_finish_reason = ch.finish_reason
                if _final_finish_reason and _final_finish_reason != 'stop':
                    try:
                        from jarvis_utils import bg_log as _bgfr
                        _bgfr(
                            f"⚠️ [Stream Finish] reason='{_final_finish_reason}' "
                            f"chunks={_total_chunks} chars={_total_chars} "
                            f"model={or_model} — 非 'stop', 可能截断."
                        )
                    except Exception:
                        pass

            return _stream_wrapper(), key_name
        except Exception:
            self.key_router.release(key_name)
            raise

    def _pick_fallback_response(self):
        current_hour = int(time.strftime('%H'))
        weekday = time.strftime('%A')
        is_weekend = weekday in ("Saturday", "Sunday")

        work_category = "General"
        profile_file = os.path.join("jarvis_config", "sir_profile.json")
        if os.path.exists(profile_file):
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                    work_category = profile.get("work_category", "General")
            except:
                pass

        pool = []

        if 5 <= current_hour < 12:
            if is_weekend:
                pool = [
                    ("Forgive me Sir, the network seems sluggish this morning. Perhaps we should try again in a moment.", "抱歉先生，今早网络似乎有些迟钝。也许我们稍后再试。"),
                    ("Sir, I'm having trouble reaching my neural core. A morning coffee break, perhaps?", "先生，我无法连接到神经核心。也许…来杯早间咖啡？"),
                ]
            else:
                pool = [
                    ("Apologies Sir, my connection to the cloud is unstable. Shall we try again?", "抱歉先生，我与云端的连接不稳定。我们再试一次？"),
                    ("Sir, the network appears to be congested this morning. I'll be ready when it clears.", "先生，今早网络似乎拥堵。等畅通了我随时待命。"),
                ]
        elif 12 <= current_hour < 18:
            pool = [
                ("I seem to have hit a network snag, Sir. Give me a moment to re-establish the link.", "我似乎遇到了网络故障，先生。给我一点时间重新建立连接。"),
                ("Sir, my external neural link is unresponsive. Perhaps a brief pause is in order.", "先生，我的外部神经链路无响应。也许该稍作停顿。"),
            ]
        elif 18 <= current_hour < 23:
            pool = [
                ("Forgive me Sir, the evening network traffic appears to be interfering with my systems.", "恕我直言先生，晚间网络流量似乎干扰了我的系统。"),
                ("Sir, I'm experiencing a temporary disconnect. The evening servers must be under heavy load.", "先生，我遇到了暂时断连。晚间服务器一定负载很重。"),
            ]
        else:
            time_str = time.strftime("%H:%M")
            pool = [
                (f"Sir, it's {time_str}... the network is unusually quiet. I cannot reach my core systems right now.", f"先生，已经{time_str}了…网络异常安静。我现在无法连接到核心系统。"),
                ("Late night network issues, Sir. My apologies — I'll be back online shortly.", "深夜网络问题，先生。抱歉——我很快会恢复在线。"),
            ]

        if work_category == "Coding":
            pool.append(("Sir, the API seems to be down. In the meantime, perhaps we could review the code locally?", "先生，API 似乎挂了。与此同时，也许我们可以在本地审查代码？"))

        import random
        return random.choice(pool)

    def _speak_fallback(self):
        en_text, zh_text = self._pick_fallback_response()
        self.subtitle_queue.put(("en", en_text))
        self.subtitle_queue.put(("zh", zh_text))
        self._put_audio(en_text)

    def _try_local_fallback(self, user_input: str, stm_context: str = "") -> str:
        fallback = get_local_fallback()
        if not fallback.is_available:
            print(f"║ ⚠️  [本地兜底] Ollama 不可用，使用罐头回复")
            return None
        try:
            messages = fallback.build_fallback_prompt(user_input, stm_context)
            # 🩹 [P0+20-β.5.12 / 2026-05-19] BUG-C: Ollama timeout 5s → 8s
            # Sir 21:37 实测 "Ollama 返回空内容" — 真因可能是 CosyVoice 此刻正在 render
            # seq=20 占满 GPU, qwen2.5:14b 排不上 GPU → 5s 内出不了完整 token. 调到 8s
            # 给 GPU 资源争抢留点空间. 仍空 → 走罐头 (双层 fallback 还在).
            reply = fallback.chat(messages, timeout=8.0)
            if reply and reply.strip():
                return reply.strip()
            else:
                print(f"║ ⚠️  [本地兜底] Ollama 返回空内容 (8s 超时, 可能 GPU 被 CosyVoice 占), 使用罐头回复")
        except Exception as e:
            print(f"║ ⚠️  [本地兜底] Ollama 异常: {type(e).__name__}: {str(e)[:100]}")
        return None

    def _speak_local_reply(self, reply: str):
        """
        将本地模型的回复输出到字幕和音频队列。
        解析 ---ZH--- 分隔符，分别处理英文和中文。
        """
        if "---ZH---" in reply:
            parts = reply.split("---ZH---", 1)
            en_text = parts[0].strip()
            zh_text = parts[1].strip() if len(parts) > 1 else ""
        else:
            en_text = reply
            zh_text = ""

        if en_text:
            self.subtitle_queue.put(("en", en_text))
            self._put_audio(en_text)
        if zh_text:
            self.subtitle_queue.put(("zh", zh_text))

    def _translate_worker(self):
        """⚡ 顶级人格翻译官：共享海马体记忆，剔除动作解析等脏活，专注生成充满人味的管家独白"""
        while True:
            thought = self.translate_queue.get()
            if thought:
                stm = getattr(self, 'last_stm_context', 'None')
                ltm = getattr(self, 'last_ltm_context', 'None')
                
                import os as _os
                profile_file = _os.path.join("jarvis_config", "sir_profile.json")
                sir_profile_str = ""
                if _os.path.exists(profile_file):
                    try:
                        with open(profile_file, "r", encoding="utf-8") as _f:
                            sir_profile_str = _f.read()
                    except: pass

                # 🩹 [P0+20-β.1.6 / 2026-05-16] 治 Sir 14:30 实测 BUG（OfferHelp 未出声）：
                # P0+19-7 拆分时漏 import → 主路径 NameError → Nudge 走 fallback 静默。
                # 函数内延迟 import 避免循环依赖（central_nerve 反向依赖 chat_bypass）。
                try:
                    from jarvis_central_nerve import JARVIS_CORE_PERSONA as _JCP
                except Exception:
                    _JCP = ""

                prompt = f"""{_JCP}

[BACKGROUND ON SIR]:
{sir_profile_str}

[YOUR KNOWLEDGE BASE]:
--- Short-Term Memory (Recent Chat) ---
{stm}

--- Long-Term Memory (Relevant Past Events) ---
{ltm}

[TASK]:
You are currently executing a physical task for me. Below is a "Raw System Log" of what your system is doing right now.
You MUST translate this raw system log into a short, ONE-SENTENCE first-person English monologue to speak to me.
Make it sound natural and elegant, as if you are updating me on your progress while working. 
Keep it under 12 words. DO NOT use Chinese. DO NOT use markdown.

Raw System Log: {thought}
Spoken English:"""
                
                try:
                    def _translate_call(client):
                        return client.models.generate_content(
                            model='gemini-3-flash-preview',
                            contents=prompt
                        )
                    
                    res, _key_name, _client = safe_gemini_call(
                        self.key_router, KeyRouter.CALLER_MAIN_BRAIN, 'flash',
                        _translate_call, max_retries=2, base_delay=1.0,
                        model_name='gemini-3-flash-preview', contents_text=prompt
                    )
                    self.key_router.release(_key_name)
                    english_monologue = res.text.strip().replace('"', '')
                    english_monologue = re.sub(r'[\u4e00-\u9fa5]', '', english_monologue).strip()
                    if english_monologue:
                        print(_box_newline(f"║ {english_monologue}"))
                        self._put_audio(english_monologue)
                except Exception:
                    pass
            self.translate_queue.task_done()

    # === 找到 jarvis_nerve.py 里的 ChatBypass 类 ===
    # 1. 删掉旧的 threading.Thread(target=self._play_worker...).start()
    # 2. 将 _render_worker 替换为以下代码：

    def _render_worker(self):
        # 🛡️ Bug X4：句子过滤白名单 —— 这些"片段"不该送进 TTS 渲染
        # 主要拦截：JSON/标签碎片（{ } < > <FAST_CALL 残段）、过短无意义符号
        import re as _re_render
        _junk_only_re = _re_render.compile(r'^[\s{}\[\]<>()"\'`,.;:!?\-_+/\\|*&^%$#@~]*$')
        # [P0+18-a.14 / 2026-05-15] 中文守门正则
        _zh_re = _re_render.compile(r'[\u4e00-\u9fa5]')
        while True:
            try:
                item = self.audio_queue.get()
                sentence = item[0] if isinstance(item, tuple) else item
                # [P0+18-a.14 / 2026-05-15] 修 BUG #9: 任何含中文的 sentence 在 render 前 strip 中文。
                # _put_audio 已加守门但有些路径直接 audio_queue.put(...) 绕开，这里兜底。
                if sentence and _zh_re.search(sentence):
                    _orig = sentence
                    if '---ZH---' in sentence:
                        sentence = sentence.split('---ZH---')[0].strip()
                    else:
                        sentence = _re_render.sub(r'[\u4e00-\u9fa5，。！？；：、""''（）【】《》]+', ' ', sentence)
                        sentence = _re_render.sub(r'\s+', ' ', sentence).strip()
                    try:
                        from jarvis_utils import bg_log as _r_bg
                        _r_bg(f"⚠️ [Render Guard] 拦截含中文的 render 输入: '{_orig[:60]}' → '{sentence[:60]}'")
                    except Exception:
                        pass
                # 过滤：空、纯符号、明显的 JSON/标签残段
                if sentence:
                    _s = sentence.strip()
                    if (not _s) or len(_s) <= 1 or _junk_only_re.match(_s):
                        # 静默丢弃，不告警（这本来就是个噪音）
                        self.audio_queue.task_done()
                        continue
                if not sentence:
                    self.audio_queue.task_done()
                    continue
                if sentence:
                    # 👇 Bug B 修复：唯一汇聚点登记 TTS 回声指纹（无论是经过
                    # _put_audio 还是 audio_queue.put 直接进队列的句子都会经过这里）
                    try:
                        from jarvis_utils import register_jarvis_tts
                        register_jarvis_tts(sentence)
                    except Exception:
                        pass
                    # [R7-α/B8] 置标志位：渲染期间 _play_worker 不允许 emit IDLE
                    self._render_in_progress = True
                    try:
                        audio_bytes = self.vocal.render_only(sentence)
                        if audio_bytes:
                            self.wave_queue.put(audio_bytes)
                        else:
                            try:
                                from jarvis_utils import bg_log as _bg
                                _bg(f"⚠️ [RenderWorker] 首次渲染失败，重试中: {sentence[:60]}")
                            except Exception:
                                pass
                            audio_bytes = self.vocal.render_only(sentence, retry=1)
                            if audio_bytes:
                                self.wave_queue.put(audio_bytes)
                            else:
                                try:
                                    from jarvis_utils import bg_log as _bg
                                    _bg(f"❌ [RenderWorker] 重试仍失败，使用静默占位: {sentence[:60]}")
                                except Exception:
                                    pass
                                import numpy as np
                                self.wave_queue.put(np.zeros(int(0.1 * 22050), dtype=np.int16).tobytes())
                    finally:
                        # 必须 finally：即便渲染异常，标志位也要复位，
                        # 否则 play_worker 会以为"永远在渲染"，永远不 emit IDLE
                        self._render_in_progress = False
                self.audio_queue.task_done()
            except Exception as e:
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"❌ [RenderWorker] 线程异常: {e}")
                except Exception:
                    pass
                try:
                    import numpy as np
                    self.wave_queue.put(np.zeros(int(0.1 * 22050), dtype=np.int16).tobytes())
                except:
                    pass
                try:
                    self.audio_queue.task_done()
                except:
                    pass
                time.sleep(0.5)

    def _play_worker(self):
        _idle_grace = 0.0
        while True:
            try:
                try:
                    item = self.wave_queue.get(timeout=30.0)
                except queue.Empty:
                    # [R7-α/B8] 30s 超时回 IDLE，但若 _render_worker 正在渲染就不动
                    if not self._render_in_progress:
                        self.state_callback("IDLE")
                    continue

                # [P0+20-β.5.9-revert / 2026-05-19] Audio Trace metadata 退役
                audio_bytes = item[0] if isinstance(item, tuple) else item

                self.state_callback("EXECUTING")
                try:
                    self.vocal.play_only(audio_bytes)
                except Exception as e:
                    print(f"⚠️ [PlaybackWorker] 音频播放异常: {e}")

                # [R7-α/B8] IDLE 判定：除了两个队列空，还要确认 render 没在进行中
                # 之前会出现 wave_queue 临时空一帧 + audio_queue 也空（句子还没切完），
                # 但 _render_worker 此刻正在 vocal.render_only 里 —— 错误地 emit IDLE
                # 会把 set_speaking_state(IDLE) 的回声防御窗口（0.6s）提前关掉，
                # 导致下一句的"准备工作"被自家麦克风听回去。
                if (self.wave_queue.empty()
                        and self.audio_queue.empty()
                        and not self._render_in_progress):
                    time.sleep(0.3)
                    if (self.wave_queue.empty()
                            and self.audio_queue.empty()
                            and not self._render_in_progress):
                        self.state_callback("IDLE")
                self.wave_queue.task_done()
            except Exception as e:
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"❌ [PlaybackWorker] 线程异常: {e}")
                except Exception:
                    pass
                try:
                    self.state_callback("IDLE")
                except:
                    pass
                try:
                    self.wave_queue.task_done()
                except:
                    pass
                time.sleep(0.3)

    # 👇 新增了 organ_whitepaper 参数
    # 👇 注意这里多了一个 ltm_context 参数
    # 👇 注意参数变成了 chat_organs
    # 👇 增加 route_callback 参数，用于接收影子线程的点火器
    # 👇 修改 1：增加了 clean_intent 参数，用于展示提纯后的意图
    # ==========================================
    # 📍 替换目标: jarvis_nerve.py (完全替换 ChatBypass 类下的 stream_chat 方法)
    # ==========================================
    def stream_chat_local(self, user_input: str, clean_intent: str = None,
                          stm_context: str = "", ltm_context: str = "",
                          chat_organs: str = "", system_alert_text: str = "",
                          ledger_data: dict = None, landmarks_str: str = "",
                          soul_tags: list = None, route_callback=None):
        """
        本地模型优先路由：Ollama 流式首答 + 标记检测。
        全量注入云端 prompt，仅替换工具/搜索指令为标记系统。
        返回 (full_text, need_cloud, need_tool)
        """
        import re
        fallback = get_local_fallback()
        if not fallback.is_available:
            return None, False, False

        full_cloud_prompt = self.jarvis._assemble_prompt(
            user_input=user_input,
            stm_context=stm_context,
            ltm_context=ltm_context,
            chat_organs=chat_organs,
            ledger_data=ledger_data,
            landmarks_str=landmarks_str,
            system_alert_text=system_alert_text,
            mode="full",
            soul_tags=soul_tags
        )

        local_prompt = fallback.build_local_prompt(full_cloud_prompt)

        print(f"\n" + "╔" + "═"*63)
        clean_user_input = user_input.replace(": ", "", 1) if user_input.startswith(": ") else user_input
        display_input = re.sub(r'^\[(?:WAKE_ONLY|WORK_MODE|RELAX_MODE)(?:\|(?:WAKE_ONLY|WORK_MODE|RELAX_MODE))*\]\s*', '', clean_user_input)
        print(_box_newline(f"║ 🗣️  [Human] [{time.strftime('%H:%M:%S')}] {display_input}"))
        if clean_intent and clean_intent != display_input:
            print(f"║ 🎯  [Intent] {clean_intent}")
        print("╠" + "═"*63)
        print(f"║ 🤖  [Jarvis-Local] ", end="", flush=True)

        full_text = ""
        streamed_text = ""
        buffer = ""
        _t_local_start = time.time()
        # [P0+18-c.11 / 2026-05-15] local fallback 路径也要追踪 is_subtitle_mode，
        # 否则 ---ZH--- 后续 chunk 的 ZH 内容会被 splitter 喂给 _put_audio。
        is_subtitle_mode = False
        # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切 (BUG-3 fix)
        _first_sent_done = False

        try:
            for token, done in fallback.chat_stream(local_prompt, timeout=90.0):
                if getattr(self, 'is_interrupted', False):
                    print("\n🛑[Local Stream] Interrupt signal received.")
                    break

                buffer += token
                full_text += token

                clean_full = full_text
                _zh_seen_local = "---ZH---" in clean_full
                if _zh_seen_local:
                    clean_full = clean_full.split("---ZH---")[0].rstrip('\n')

                delta = clean_full[len(streamed_text):]
                if delta:
                    print(_box_newline(delta), end="", flush=True)
                    streamed_text += delta

                while True:
                    # 🩹 [P0+20-β.2.7.3] 复用 _find_sentence_split_idx（含 organ.command 保护）
                    # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切
                    earliest_idx = _find_sentence_split_idx(buffer, soft_split=False, is_first_sentence=not _first_sent_done)

                    if earliest_idx == -1 and len(buffer) > 80:
                        for i in range(len(buffer) - 1, 20, -1):
                            if buffer[i] == ' ':
                                earliest_idx = i
                                break

                    if earliest_idx != -1:
                        sentence = buffer[:earliest_idx + 1].strip()
                        buffer = buffer[earliest_idx + 1:]
                        if "---ZH---" in sentence:
                            is_subtitle_mode = True
                            sentence = sentence.split("---ZH---")[0]
                        elif is_subtitle_mode:
                            sentence = ""
                        elif _sentence_is_chinese_lean(sentence):
                            # [P0+18-e.2 / 2026-05-15] 上游 Audio Guard (local fallback)
                            is_subtitle_mode = True
                            try:
                                from jarvis_utils import bg_log as _zh_up_bg
                                _zh_up_bg(
                                    f"🛡️ [Audio Guard / Upstream / Local-fallback] 中文 sentence 无 ---ZH--- → "
                                    f"subtitle_mode: '{sentence[:60]}'"
                                )
                            except Exception:
                                pass
                            self.subtitle_queue.put(("zh", sentence))
                            sentence = ""
                        sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                        sentence = sentence.replace("J A R V I S", "Jarvis").replace("JARVIS", "Jarvis")
                        if sentence:
                            self._put_audio(sentence)
                            self.subtitle_queue.put(("en", sentence))
                            _first_sent_done = True  # β.5.9
                    else:
                        break

                if done:
                    break

            if buffer.strip() and not getattr(self, 'is_interrupted', False):
                sentence = buffer.strip()
                # [P0+18-c.11] local fallback 末尾 buffer flush 也检查 is_subtitle_mode
                if "---ZH---" in sentence:
                    is_subtitle_mode = True
                    sentence = sentence.split("---ZH---")[0]
                elif is_subtitle_mode:
                    sentence = ""
                elif _sentence_is_chinese_lean(sentence):
                    # [P0+18-e.2 / 2026-05-15] 上游 Audio Guard (local fallback end-buffer)
                    is_subtitle_mode = True
                    try:
                        from jarvis_utils import bg_log as _zh_up_bg
                        _zh_up_bg(
                            f"🛡️ [Audio Guard / Upstream / Local-end-buffer] 中文 sentence 无 ---ZH--- → "
                            f"subtitle_mode: '{sentence[:60]}'"
                        )
                    except Exception:
                        pass
                    self.subtitle_queue.put(("zh", sentence))
                    sentence = ""
                sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                if sentence:
                    self._put_audio(sentence)
                    self.subtitle_queue.put(("en", sentence))

            _t_local_done = time.time()

            need_cloud = "[NEED_CLOUD]" in full_text
            need_tool = "[NEED_TOOL]" in full_text

            final_clean = full_text
            for marker in ["[NEED_CLOUD]", "[NEED_TOOL]"]:
                final_clean = final_clean.replace(marker, "")

            zh_subtitle_text = ""
            if "---ZH---" in final_clean:
                parts = final_clean.split("---ZH---", 1)
                final_clean = parts[0]
                zh_subtitle_text = parts[1].strip() if len(parts) > 1 else ""

            last_delta = final_clean[len(streamed_text):].rstrip('\n')
            if last_delta:
                print(_box_newline(last_delta), end="", flush=True)

            if zh_subtitle_text:
                clean_zh = re.sub(r'<[^>]+>', '', zh_subtitle_text).strip()
                if clean_zh:
                    # [P0+18-c.12 / 2026-05-15] 多段 ZH (含 \n\n) 走 _box_newline,每行加 ║ 前缀
                    print("\n" + _box_newline(f"║ 📺  [Subtitle] {clean_zh}"))
                    self.subtitle_queue.put(("zh", clean_zh))

            if not getattr(self, 'is_interrupted', False):
                print(f"\n⏱️ [Local Timer] First token: {_t_local_done - _t_local_start:.1f}s")

            if need_cloud or need_tool:
                print(f"║ ☁️  [Router] Detected {('[NEED_CLOUD]' if need_cloud else '[NEED_TOOL]')}, waking cloud brain...")
                print("╟" + "─"*63)
            else:
                print("╚" + "═"*63 + "\n")

            return full_text, need_cloud, need_tool

        except Exception as e:
            print(f"║ ⚠️  [Local Error] {e}")
            print("╚" + "═"*63 + "\n")
            return None, True, False

    # ==========================================
    # 🩹 [β.2.9.10 / 2026-05-18] Sir 11:09 工具卡顿治本 — 异步软超时 wrapper
    # 设计:
    #   submit 到 ThreadPoolExecutor
    #   try result(timeout=1.5s):
    #     ≤1.5s 完成 (开窗口/简单 cmd) → 同步返 result, 体验跟旧版无差
    #     >1.5s (慢工具 hg/build/网络) → TimeoutError → 主 stream 立刻继续
    #       后台 callback 把 result append 到 self._pending_tool_results
    #       下一轮 _drain_pending_tool_results 注入 prompt 让主脑看到
    #   Sir 不再听到 1-5s 静默 = 体感不卡顿 (准则 1+2 高效反应)
    # ==========================================
    def _execute_fast_call_with_soft_timeout(self, organ_name: str,
                                              command: str, params: dict,
                                              timeout: float = 1.5):
        """同步语义 wrapper + 异步软超时. 返回 (result, was_sync)."""
        try:
            fut = self._tool_executor.submit(
                self._execute_fast_call, organ_name, command, params)
        except Exception as _se:
            # ThreadPool 关了 or 满了 → fallback 同步
            try:
                from jarvis_utils import bg_log as _fbg
                _fbg(f"⚠️ [FastCall/Submit] {_se} — fallback sync")
            except Exception:
                pass
            return self._execute_fast_call(organ_name, command, params), True

        try:
            result = fut.result(timeout=timeout)
            return result, True
        except concurrent.futures.TimeoutError:
            # 后台续跑, 完成 callback 写 _pending_tool_results
            def _on_done(_fut):
                try:
                    r = _fut.result()
                    with self._pending_tool_lock:
                        self._pending_tool_results.append({
                            'organ': organ_name, 'command': command,
                            'result': r, 'ts': time.time(),
                        })
                        # 防爆: 最多保 20 条 (跨多轮累积)
                        if len(self._pending_tool_results) > 20:
                            self._pending_tool_results = \
                                self._pending_tool_results[-20:]
                    try:
                        from jarvis_utils import bg_log as _abg
                        _abg(
                            f"⚡ [FastCall/Async] {organ_name}.{command} "
                            f"后台完成: {str(r)[:80]}"
                        )
                    except Exception:
                        pass
                    # subtitle 通知 Sir 工具已完成 (字幕飘过 + 不打断主脑当前讲话)
                    try:
                        self.subtitle_queue.put(
                            ("en", f"[tool done] {organ_name}.{command}: "
                                    f"{str(r)[:60]}")
                        )
                    except Exception:
                        pass
                except Exception as _ace:
                    try:
                        from jarvis_utils import bg_log as _aebg
                        _aebg(
                            f"⚠️ [FastCall/Async] {organ_name}.{command} "
                            f"后台失败: {_ace}"
                        )
                    except Exception:
                        pass
            try:
                fut.add_done_callback(_on_done)
            except Exception:
                pass
            placeholder = (
                f"⏳ {organ_name}.{command}: 工具异步执行中 "
                f"(主脑可继续讲话, 结果稍后到达)"
            )
            return placeholder, False

    def drain_pending_tool_results(self) -> str:
        """🩹 [β.2.9.10] 取走 pending 工具结果, 拼成 prompt 注入文本.

        由 _assemble_prompt / stream_chat 入口调用, 让主脑看到上轮异步工具
        的真实 result, 可在新一轮 LLM stream 自然讲解.
        """
        with self._pending_tool_lock:
            items = self._pending_tool_results[:]
            self._pending_tool_results.clear()
        if not items:
            return ''
        lines = [
            "[RECENT BACKGROUND TOOL RESULTS — 上一轮 FAST_CALL 已异步完成]:"
        ]
        for it in items:
            age = max(0, int(time.time() - it['ts']))
            lines.append(
                f"  - {it['organ']}.{it['command']} "
                f"({age}s ago): {str(it['result'])[:140]}"
            )
        lines.append(
            "若 Sir 询问这些工具结果, 你可基于上述事实回答 (不要编造)."
        )
        return '\n'.join(lines) + '\n'

    def _lookup_organ_by_command(self, command):
        """🆕 [BUG #1 fix / 2026-05-24 19:45] command → organ 反向 vocab.

        主脑幻觉 organ 名 (reminder_hands → memory_hands) 时, 看 command
        在哪个 hand 的 get_instruction_dict() 里, 自动 alias 过去.

        准则 6 优雅: LLM 负责语义, python 只做反向索引. cache lazy build,
        instance 内不重复扫. 找不到返 None 不破老路径.
        """
        if not command:
            return None
        if not hasattr(self, '_command_to_organ_cache'):
            self._command_to_organ_cache = self._build_command_to_organ_index()
        return self._command_to_organ_cache.get(command)

    def _build_command_to_organ_index(self):
        """扫所有 hand_registry 调 get_instruction_dict() regex 提 commands.

        Returns: { command_name: organ_full_name }, 重名时 first-win.
        """
        import re as _re_idx
        cache = {}
        registry = getattr(getattr(self, 'jarvis', None), 'hand_registry', {}) or {}
        for organ_name, hand_class in registry.items():
            try:
                try:
                    inst = hand_class(self.jarvis.gemini_key)
                except TypeError:
                    inst = hand_class()
            except Exception:
                continue
            if not hasattr(inst, 'get_instruction_dict'):
                continue
            try:
                doc = inst.get_instruction_dict()
            except Exception:
                continue
            # regex 提 "command_name": 模式 (matches l4_memory_hands.py 第 21-26 行)
            for m in _re_idx.finditer(r'["\'](\w+)["\']\s*:\s*\{', doc):
                cmd = m.group(1)
                # 排除明显 param key (intent / query / id 等), 仅取看似 command 的
                # heuristic: command 一般 verb_xxx (snake_case 含 _ 或 lowercase verb)
                if cmd in ('intent', 'query', 'id', 'time_range_hours', 'new_intent',
                           'new_time', 'max_age_hours', 'trigger_time'):
                    continue
                if cmd not in cache:
                    cache[cmd] = organ_name
        try:
            from jarvis_utils import bg_log as _build_bg
            _build_bg(
                f"📚 [CommandIndex] built — {len(cache)} commands across "
                f"{len(registry)} hands (reverse vocab cache)"
            )
        except Exception:
            pass
        return cache

    def _execute_fast_call(self, organ_name: str, command: str, params: dict):
        import contextlib
        import re as _re_safety

        # 🆕 [BUG #3 fix / 2026-05-24 19:45] PreFlight None guard:
        # 主脑偶发 emit malformed FAST_CALL[None/None] (上下文 truncate / 模板错).
        # 不 crash, 改 fail-soft 返回友善 msg, 让主脑下轮看到 self-correct.
        if organ_name is None or command is None or not str(organ_name).strip() or not str(command).strip():
            try:
                from jarvis_utils import bg_log as _none_bg
                _none_bg(
                    f"⚠️ [FastCall/Malformed] 拦截 organ={organ_name!r} cmd={command!r} — "
                    f"格式不全 fail-soft (主脑下轮看 result 可 self-correct)"
                )
            except Exception:
                pass
            return (
                "⚠️ FAST_CALL malformed — organ_name 或 command 为空. "
                "请重新检查 manifests, 用完整格式 organ_name.command 调用. "
                "若不确定该用哪个 organ, 不要发 FAST_CALL, 改问 Sir 或用自然语言响应."
            )

        SAFETY_GATE_ORGANS = ["system_hands", "file_operator_hands", "txt_writer_hands_generated"]
        ACKNOWLEDGMENT_PATTERNS = [
            r'^(okay|ok|yeah|yep|yes|sure|right|got it|mhm|uh huh|alright|fine|good|great|nice|cool|thanks|thx|ty)$',
            r'^(okay|ok|yeah|yep|yes|sure|right|got it|mhm|alright|fine|good|great|nice|cool)[,.!]*$',
        ]

        # 🩹 [β.2.9.9 / 2026-05-18] Sir 11:09+11:11 痛点:
        # 旧 v1 加占位语音 → Sir 反对"没人味". 撤回. 改架构靠 directive 教
        # 主脑在 FAST_CALL 前自然过渡 (见 jarvis_directives.py:tool_overture_directive).
        # tool 执行仍同步, 但主脑生成的 overture 话已 push 进 audio_queue,
        # Sir 听到自然连贯语 + tool 同时执行 = 不卡顿体感.
        # 真异步留 β.3.0 大重构.

        for key in list(params.keys()):
            val = params[key]
            if isinstance(val, str):
                _trailing_junk = '\u3002\uff0c\uff01\uff1f\u3001\uff1b\uff1a\uff09\u3011\u300b\u2026,;:.!?)'
                val = val.rstrip(_trailing_junk + '\u201c\u201d\u2018\u2019' + '\'"')
                val = val.strip()
                params[key] = val

        if organ_name == "ui_control":
            ctrl_cmd = command
            if ctrl_cmd in ("subtitle_on", "subtitle_off", "orb_on", "orb_off"):
                self.subtitle_queue.put(("control", ctrl_cmd))
                return f"✅ ui_control.{ctrl_cmd}"
            # 🩹 [β.2.9.9 / 2026-05-18] Sir 11:09 集成 dashboard 到主脑:
            # "打开面板/看看状态" 模糊语义 → 主脑 emit FAST_CALL ui_control.dashboard_open
            # 🩹 [β.5.25-finish / 2026-05-20] Sir 02:30 反馈"打开的还是之前那个 python":
            # 默认改成 web dashboard (scripts/jarvis_dashboard_web.py + 自动开浏览器).
            # 已在跑 (port 8765 占用) → 只开浏览器复用. tkinter 老版作 fallback.
            if ctrl_cmd == "dashboard_open":
                try:
                    import subprocess as _sp
                    import sys as _sys
                    import time as _t
                    import socket as _sock
                    import webbrowser as _wb
                    WEB_PORT = 8765
                    WEB_URL = f"http://127.0.0.1:{WEB_PORT}/"
                    py_exe = _sys.executable

                    # 1. 探测 port 8765 是否已在跑 (server 复用)
                    def _port_alive(port):
                        with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
                            s.settimeout(0.3)
                            try:
                                s.connect(('127.0.0.1', port))
                                return True
                            except Exception:
                                return False
                    if _port_alive(WEB_PORT):
                        # 已 running, 只开浏览器
                        try:
                            _wb.open(WEB_URL)
                        except Exception:
                            pass
                        return (f"✅ ui_control.dashboard_open: web 看板已在跑, "
                                f"浏览器开 {WEB_URL}")

                    # 2. 找 web dashboard 脚本
                    web_script = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'scripts', 'jarvis_dashboard_web.py')
                    if not os.path.exists(web_script):
                        web_script = 'scripts/jarvis_dashboard_web.py'

                    # 3. 启动 web server (它自己会开浏览器)
                    proc = _sp.Popen(
                        [py_exe, web_script],
                        creationflags=getattr(_sp, 'CREATE_NEW_CONSOLE',
                                               0x00000010),
                        close_fds=True,
                    )
                    # 启动健康检查
                    _t.sleep(1.5)
                    if proc.poll() is not None:
                        # web 启动失败 → fallback 老 tkinter
                        dash_script = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'scripts', 'jarvis_dashboard.py')
                        if not os.path.exists(dash_script):
                            dash_script = 'scripts/jarvis_dashboard.py'
                        proc_tk = _sp.Popen(
                            [py_exe, dash_script],
                            creationflags=getattr(_sp, 'CREATE_NEW_CONSOLE',
                                                   0x00000010),
                            close_fds=True,
                        )
                        _t.sleep(0.6)
                        if proc_tk.poll() is not None:
                            return (f"❌ ui_control.dashboard_open: "
                                    f"web (exit={proc.returncode}) + "
                                    f"tkinter (exit={proc_tk.returncode}) 都失败")
                        return (f"⚠️ ui_control.dashboard_open: web 启动失败 → "
                                f"fallback tkinter 看板 (PID={proc_tk.pid})")
                    return (f"✅ ui_control.dashboard_open: web 看板已启动 "
                            f"(PID={proc.pid}, {WEB_URL})")
                except Exception as _de:
                    return f"❌ ui_control.dashboard_open: {_de}"
            if ctrl_cmd == "dashboard_close":
                # 🩹 [β.5.25-finish / 2026-05-20] 双 kill: web server (port 8765) + tkinter
                try:
                    import subprocess as _sp
                    killed = []
                    # 1. kill web server (找 jarvis_dashboard_web 命令)
                    try:
                        r1 = _sp.run(
                            ['wmic', 'process', 'where',
                             "CommandLine like '%jarvis_dashboard_web%'",
                             'call', 'terminate'],
                            capture_output=True, timeout=5, text=True,
                        )
                        if r1.returncode == 0:
                            killed.append('web')
                    except Exception:
                        pass
                    # 2. kill tkinter (窗口标题)
                    try:
                        _sp.run(
                            ['taskkill', '/F', '/FI',
                             'WINDOWTITLE eq 贾维斯总览看板*'],
                            capture_output=True, timeout=5,
                        )
                        killed.append('tkinter')
                    except Exception:
                        pass
                    return f"✅ ui_control.dashboard_close (killed: {killed or 'none'})"
                except Exception as _ce:
                    return f"❌ ui_control.dashboard_close: {_ce}"
            return f"❌ ui_control: 未知指令 {ctrl_cmd}"

        # 🆕 [P5-fix24-concern-dismiss / 2026-05-22] Sir 18:42 痛点
        # ============================================================
        # Sir: "我跟他说了很多次不要在意了, 他还是提, 感觉是我们没有
        # 语言控制长期关心的手段". 这里加 concerns.dismiss / reactivate
        # FAST_CALL handler — 主脑听 Sir 显式 dismiss 类话 → emit FAST_CALL
        # 直接调 ConcernsLedger.dismiss(), 真改 concerns.json + publish SWM event.
        # 配套 directive: jarvis_directives.py:concern_dismissal_judge
        # ============================================================
        if organ_name == "concerns":
            try:
                from jarvis_concerns import get_default_ledger
                ledger = get_default_ledger()
            except Exception as _le:
                return f"❌ concerns.{command}: ledger 不可用 ({_le})"
            cid = (params.get('id', '') or params.get('concern_id', '') or '').strip()
            reason = (params.get('reason', '') or '')[:200]
            turn_id = (params.get('turn_id', '') or '')[:60]
            if command == "dismiss":
                if not cid:
                    return "❌ concerns.dismiss: missing 'id' param"
                ok = ledger.dismiss(cid, reason=reason, source='sir_voice',
                                          source_turn_id=turn_id)
                if ok:
                    try:
                        ledger.persist()
                    except Exception:
                        pass
                    return (f"✅ concerns.dismiss: {cid} 软关闭 "
                              f"(triggers_proactive=False, severity≤0.3) — "
                              f"Sir 后续仍可主动问起")
                return f"❌ concerns.dismiss: 未找到 concern_id={cid}"
            if command == "reactivate":
                if not cid:
                    return "❌ concerns.reactivate: missing 'id' param"
                ok = ledger.reactivate(cid, reason=reason, source='sir_voice',
                                              source_turn_id=turn_id)
                if ok:
                    try:
                        ledger.persist()
                    except Exception:
                        pass
                    return (f"✅ concerns.reactivate: {cid} 重新主动监控 "
                              f"(triggers_proactive=True)")
                return f"❌ concerns.reactivate: 未找到 concern_id={cid}"

            # 🆕 [Sir 2026-05-24 23:01 真测追根 BUG 治本] concerns.progress_update
            # =====================================================================
            # 源 BUG: directive `habit_progress_routing` (priority=13) 教主脑 emit
            #   FAST_CALL concerns.progress_update {concern_id, current, target, unit}
            # 但 handler 漏写, fallback 报 "未知指令 progress_update".
            # 治本: 加 handler, 调现成的 ConcernsLedger.record_user_feedback(),
            # 把 directive 教的 params 翻成 judgement dict 写 daily_progress.
            # 设计意图自洽: directive 教 + organ handler + ledger API 三对齐.
            if command == "progress_update":
                if not cid:
                    cid = (params.get('concern_id', '') or '').strip()
                if not cid:
                    return "❌ concerns.progress_update: missing 'concern_id' param"
                try:
                    cur = params.get('current', None)
                    tgt = params.get('target', None)
                    unit = (params.get('unit', '') or '').strip()
                    if cur is None:
                        return ("❌ concerns.progress_update: missing 'current' "
                                "(Sir 报的进度数 e.g. 9 杯水的 9)")
                    cur_f = float(cur)
                    tgt_f = float(tgt) if tgt is not None else None
                    # 🆕 [Sir 2026-05-27 21:34 真测 P4 BUG-A] tgt_f fallback —
                    # 主脑常 omit target, ledger daily_progress 已存 (e.g. 10.0).
                    # 用 ledger 已存 target 算 severity_delta 比 None 准.
                    if tgt_f is None:
                        try:
                            _c = ledger.get(cid)
                            _dp = (_c.daily_progress if _c else None) or {}
                            _stored_tgt = _dp.get('target')
                            if _stored_tgt is not None and float(_stored_tgt) > 0:
                                tgt_f = float(_stored_tgt)
                        except Exception:
                            pass
                    progress = {'current': cur_f}
                    if tgt_f is not None:
                        progress['target'] = tgt_f
                    if unit:
                        progress['unit'] = unit
                    raw_text = (params.get('raw_text', '') or '')[:300]
                    # 🆕 [Sir 2026-05-27 21:34 真测 P4 BUG-B] linear severity decay
                    # 旧 "75% gate" → 1/10 = 0.0 让 Sir 觉得没添加成功.
                    # 新 helper: linear, 1/10 → -0.05, 5/10 → -0.25, 10/10 → -0.5
                    from jarvis_concerns import (
                        compute_severity_delta_from_progress as _csev,
                    )
                    judgement = {
                        'has_relevance': True,
                        'progress': progress,
                        'severity_delta': _csev(cur_f, tgt_f),
                        'source': 'directive:habit_progress_routing',
                    }
                    ok = ledger.record_user_feedback(cid, raw_text, judgement)
                    if not ok:
                        return (f"❌ concerns.progress_update: 未找到 concern_id={cid} "
                                f"(LLM 教 directive 列了已 register 的 id)")
                    try:
                        ledger.persist()
                    except Exception:
                        pass
                    progress_str = (
                        f"{int(cur_f) if cur_f == int(cur_f) else cur_f}"
                        + (f"/{int(tgt_f) if tgt_f == int(tgt_f) else tgt_f}" if tgt_f else '')
                        + (f" {unit}" if unit else '')
                    )
                    return (f"✅ concerns.progress_update: {cid} → {progress_str} "
                            f"(severity_delta={judgement['severity_delta']:+.2f})")
                except ValueError as _ve:
                    return f"❌ concerns.progress_update: invalid number ({_ve})"
                except Exception as _pe:
                    return f"❌ concerns.progress_update: {_pe}"

            return (f"❌ concerns: 未知指令 {command} "
                    f"(支持 dismiss/reactivate/progress_update)")

        # 🆕 [Sir 2026-05-24 23:41 真测追根 BUG 治本] commitment_watcher.forget
        # =====================================================================
        # 源 BUG: Sir 让"忘记 8 点休息承诺", 主脑 emit `mutation.update params='all'`
        # fail / 撒谎"removed 20:30". 没真删 — 因为之前没 organ 路径 forget commitment.
        # 治本: CommitmentWatcher.forget_commitment(hint/db_id/all_active) 模糊匹配
        # 真删 + persist + publish SWM 'commitment_forgotten' 让主脑下轮看 evidence.
        if organ_name == "commitment_watcher":
            try:
                cw = getattr(self.jarvis, 'commitment_watcher', None) if hasattr(self, 'jarvis') else None
                if cw is None or not hasattr(cw, 'forget_commitment'):
                    return ("❌ commitment_watcher.forget: CommitmentWatcher 未初始化 "
                            "或缺 forget_commitment 方法")
                if command == "forget":
                    hint = (params.get('hint', '') or params.get('description', '')
                            or params.get('match', '') or '').strip()
                    db_id = 0
                    try:
                        db_id = int(params.get('db_id', 0) or 0)
                    except Exception:
                        db_id = 0
                    all_active = bool(params.get('all_active', False)
                                       or params.get('all', False))
                    r = cw.forget_commitment(hint=hint, db_id=db_id,
                                              all_active=all_active)
                    return r.get('msg', '? unknown result')
                return (f"❌ commitment_watcher: 未知指令 {command} "
                        f"(支持 forget {{hint|db_id|all_active}})")
            except Exception as _cwe:
                return f"❌ commitment_watcher.{command}: {_cwe}"

        # 🆕 [P5-fix25-stand-down / 2026-05-22] Stand Down 模式
        # ============================================================
        # Sir 痛点: 玩游戏 / 接电话 / 和爸妈说话时, Jarvis 一直回复尴尬.
        # FAST_CALL stand_down.set / clear 让主脑 (或 Sir 显式) 进入沉默.
        # Hotkey Ctrl+Alt+J 同步 toggle (jarvis_stand_down 自带 daemon).
        # Reaction gate 在 stream nudge / TTS 处用 should_silence_voice() 判.
        # ============================================================
        if organ_name == "stand_down":
            try:
                import jarvis_stand_down as sd
            except Exception as _se:
                return f"❌ stand_down.{command}: module 不可用 ({_se})"
            if command == "set":
                reason = (params.get('reason', '') or sd.REASON_MANUAL)[:64]
                duration_min = params.get('duration_min', sd.DEFAULT_DURATION_MIN)
                try:
                    duration_min = float(duration_min)
                except Exception:
                    duration_min = sd.DEFAULT_DURATION_MIN
                exit_hint = (params.get('exit_hint', '') or '')[:200]
                turn_id = (params.get('turn_id', '') or '')[:60]
                s = sd.set_stand_down(
                    reason=reason,
                    duration_min=duration_min,
                    exit_hint=exit_hint,
                    source='sir_voice',
                    source_turn_id=turn_id,
                )
                eta = time.strftime('%H:%M', time.localtime(s.until_ts))
                return (f"✅ stand_down.set: 进入沉默 reason={s.reason} "
                          f"until={eta} (~{int(duration_min)}min). "
                          f"voice OFF, 字幕 ON, visual_pulse OFF.")
            if command == "clear":
                reason = (params.get('reason', '') or '')[:200]
                turn_id = (params.get('turn_id', '') or '')[:60]
                was_active = sd.is_active()
                sd.clear_stand_down(reason=reason, source='sir_voice',
                                            source_turn_id=turn_id)
                if was_active:
                    return f"✅ stand_down.clear: wake up — voice / nudge 恢复"
                return "ℹ️ stand_down.clear: 当前未在 stand_down, 无需 clear"
            if command == "status":
                s = sd.get_state()
                if not s.is_active_now():
                    return "☀️ stand_down: NOT active"
                return (f"🌙 stand_down: ACTIVE reason={s.reason} "
                          f"until={time.strftime('%H:%M', time.localtime(s.until_ts))} "
                          f"({int(s.remaining_s() / 60)}min 剩)")
            return f"❌ stand_down: 未知指令 {command} (支持 set/clear/status)"

        # 🆕 [P5-fix27-promise-fulfill / 2026-05-22] Promise / Commitment 闭环
        # ============================================================
        # Sir 真痛点 (20:42): jarvis 还在说"明天体检"但 Sir 今天已完成. 根因:
        # promise_log 有 mark_fulfilled / mark_cancelled API, 但主脑无法调
        # 也没 directive 教主脑听 "X 做完了 / X 别管了" → emit FAST_CALL.
        # 修法: 加 promises organ + 配套 directive promise_completion_judge.
        # 配套 directive: jarvis_directives.py:promise_completion_judge
        # ============================================================
        if organ_name == "promises":
            try:
                from jarvis_promise_log import get_default_log
                plog = get_default_log()
            except Exception as _pe:
                return f"❌ promises.{command}: log 不可用 ({_pe})"
            pid = (params.get('id', '') or params.get('promise_id', '') or '').strip()
            keyword = (params.get('keyword', '') or '').strip()
            reason = (params.get('reason', '') or '')[:200]
            evidence = (params.get('evidence', '') or reason)[:200]
            # 支持 keyword 模糊找 — 主脑可能不记 pid (e.g. "p_cdc96ad5"),
            # 但说 "体检的承诺" / "the medical exam promise" → keyword 搜.
            if not pid and keyword:
                try:
                    kw_low = keyword.lower()
                    for _pid, _p in plog.promises.items():
                        if _p.state != 'pending':
                            continue
                        blob = ((_p.description or '') + ' ' +
                                  (_p.jarvis_reply or '') + ' ' +
                                  (getattr(_p, 'source_text', '') or '')).lower()
                        if kw_low in blob:
                            pid = _pid
                            break
                except Exception:
                    pass
            if command == "fulfill":
                if not pid:
                    return ("❌ promises.fulfill: missing 'id' or 'keyword' (e.g. "
                              "{'keyword':'体检'} 让我帮你找)")
                ok = plog.mark_fulfilled(pid, evidence_kind='sir_voice',
                                                  evidence_what=evidence or 'Sir 说做完了')
                if ok:
                    return (f"✅ promises.fulfill: {pid} 标记 fulfilled "
                              f"— ProactiveCare 不再提醒")
                return (f"❌ promises.fulfill: {pid} 未找到或非 pending "
                          f"(可能已 fulfilled/cancelled/untracked)")
            if command == "cancel":
                if not pid:
                    return ("❌ promises.cancel: missing 'id' or 'keyword' (e.g. "
                              "{'keyword':'体检'} 让我帮你找)")
                ok = plog.mark_cancelled(pid, reason=reason or 'Sir 撤销')
                if ok:
                    return (f"✅ promises.cancel: {pid} 已撤销 — "
                              f"ProactiveCare 不再提醒")
                return (f"❌ promises.cancel: {pid} 未找到或非 pending")
            if command == "list":
                # 帮主脑看当前有哪些 pending — 主脑可能不记 id
                try:
                    pendings = [(p_id, p) for p_id, p in plog.promises.items()
                                  if p.state == 'pending']
                    if not pendings:
                        return "ℹ️ promises.list: 0 pending"
                    lines = [f"pending {len(pendings)} 条 (recent 5):"]
                    for p_id, p in pendings[-5:]:
                        _desc = (p.description or '')[:60]
                        _auth = p.author or '?'
                        lines.append(f"  {p_id} author={_auth} '{_desc}'")
                    return '\n'.join(lines)
                except Exception as _le:
                    return f"❌ promises.list: {_le}"
            return (f"❌ promises: 未知指令 {command} "
                      f"(支持 fulfill/cancel/list)")

        # 🆕 [P5-fix32-D / 2026-05-22 22:30] FAST_CALL `mutation` organ — 统一修源接口
        # ============================================================
        # Sir 21:55 mutation refactor Phase 1.4: 主脑能 emit 1 个 FAST_CALL 修
        # 任何 source data, 系统按 field_path 前缀路由到对应 layer.
        # 详 docs/JARVIS_MEMORY_AND_MUTATION_REFACTOR.md Part 3+4.
        #
        # 主脑 emit 形式:
        #   <FAST_CALL>{"organ":"mutation","command":"update","params":{
        #     "field_path": "profile.work_rhythms",
        #     "new_value": "sleep at 23:00",
        #     "intent": "revise",       // reinforce/refine/revise/dismiss/complete
        #     "reason": "Sir 教正",     // Sir 原话 / 主脑解读 (audit 用)
        #     "old_value": "(可选)",
        #     "confidence": 0.9         // 默认 0.9, fast_call 路径走高置信
        #   }}</FAST_CALL>
        #
        # field_path 协议:
        #   - profile.<field>          → ProfileCard.overwrite_field (sir_profile.json)
        #   - concerns.<cid>           → ConcernsLedger.record_signal
        #   - promise.fulfill.<k>      → PromiseLog.mark_fulfilled
        #   - promise.cancel.<k>       → PromiseLog.mark_cancelled
        #   - commitment.cancel.<k>    → CommitmentWatcher.cancel_by_keyword
        #   - commitment.update.<k>    → CommitmentWatcher.update_by_keyword
        #   - relationships.archive.<jid>     → archive_inside_joke
        #   - protocol.archive.<pid>          → archive_protocol
        #   - unfinished.done.<uid>           → mark_unfinished_done
        #   - thread.archive.<tid>            → archive_thread
        #   - milestone.<title>        → tool_milestone_register
        # ============================================================
        if organ_name == "mutation":
            try:
                from jarvis_memory_gateway import get_default_gateway
                gw = get_default_gateway()
            except Exception as _ge:
                return f"❌ mutation: gateway 不可用 ({_ge})"

            if command not in ("update", "set", "fulfill", "cancel",
                                  "dismiss", "complete", "revise", "refine",
                                  "reinforce", "archive"):
                return (f"❌ mutation: 未知指令 {command} "
                          f"(支持 update / set / fulfill / cancel / dismiss / complete / "
                          f"revise / refine / reinforce / archive)")

            field_path = (params.get('field_path') or
                            params.get('field') or '').strip()
            if not field_path:
                return "❌ mutation.{}: missing 'field_path'".format(command)

            new_value = params.get('new_value', params.get('value', ''))
            old_value = params.get('old_value', '')
            intent = (params.get('intent', '') or '').strip()
            reason = (params.get('reason', '') or '')[:200]
            try:
                confidence = float(params.get('confidence', 0.9))
            except Exception:
                confidence = 0.9
            confidence = max(0.0, min(1.0, confidence))

            # 把 command 映射到 source 标识 (帮助 gateway 判 fast_call vs 老路 + audit)
            source_label = f"fast_call_mutation:{command}"
            if intent:
                source_label += f":intent={intent}"

            # turn_id from trace
            try:
                from jarvis_utils import TraceContext
                turn_id = TraceContext.get_turn_id() or ''
            except Exception:
                turn_id = ''

            try:
                receipt = gw.update_sir_field(
                    field_path=field_path,
                    new_value=new_value,
                    source=source_label,
                    old_value=old_value,
                    confidence=confidence,
                    turn_id=turn_id,
                    nerve=getattr(self, 'jarvis', None),
                    # 🆕 [P5-fix34] 标记当前主脑 model — A/B audit 按 model 分组
                    model=getattr(self, 'main_brain_model', '') or '',
                )
            except Exception as _ue:
                return f"❌ mutation.{command} fail: {_ue}"

            # Format 人话 result 给主脑下轮看
            if receipt.ok:
                layer_name = receipt.layer_targeted or '?'
                summary = (
                    f"✅ mutation.{command}: layer={layer_name} "
                    f"field={field_path} "
                    f"new='{(receipt.new_value_excerpt or '')[:60]}'"
                )
                if receipt.old_value_excerpt:
                    summary += f" (was '{receipt.old_value_excerpt[:40]}')"
                summary += (
                    f". mutation_id={receipt.mutation_id}. "
                    f"主脑下次 retrieve 看新版."
                )
                # 🆕 [Sir 2026-05-24 21:14 真测 / hydration_goal BUG A L2]
                # 之前: ProfileCard + confidence≥0.8 就报 "已 atomic 覆写" — 但实际
                # fallback apply_correction (audit-only) 时也走这里 → 谎报 atomic 覆写.
                # 治本: 仅 physical_write=True (真 overwrite_field 成功) 才报 atomic;
                # audit-only fallback 时显示精准: "audit only, field 不在白名单".
                if layer_name == 'ProfileCard' and confidence >= 0.8:
                    if getattr(receipt, 'physical_write', False):
                        summary += " (sir_profile.json 已 atomic 覆写)"
                    else:
                        # audit only — error 含 fallback fail msg, 截一段给主脑
                        _err_excerpt = (receipt.error or '')[:80]
                        summary += (
                            f" ⚠️ audit-only fallback (sir_profile.json 未真改: "
                            f"{_err_excerpt or 'field 不在白名单'})"
                        )
                return summary
            else:
                return (f"❌ mutation.{command} fail: {receipt.error[:120]} "
                          f"(layer={receipt.layer_targeted})")

        # 🆕 [P5-fix35-C / 2026-05-23] Cyclic Task organ — 通用循环任务展开
        # Sir 11:09 真意: 通用 clarify→confirm→cyclic_emit 链路, 不只 reminder.
        # 主脑 emit register → store 展开 N 个 reminders + 持久化 protocol.
        # cancel/list/status 都走这条.
        if organ_name == "cyclic_task":
            try:
                from jarvis_cyclic_task import get_default_store
                store = get_default_store(
                    hippocampus=getattr(self.jarvis, 'hippocampus', None))
            except Exception as _ce:
                return f"❌ cyclic_task: store 不可用 ({_ce})"

            if command == 'register':
                task_id = (params.get('task_id') or '').strip()
                kind = (params.get('kind') or 'reminder').strip()
                description = (params.get('description') or '')[:200]
                cycle_minutes = params.get('cycle_minutes', 0)
                start_at = (params.get('start_at') or '').strip()
                end_at = (params.get('end_at') or '').strip()
                intent_template = (params.get('intent_template') or '')[:200]

                # 兜底: task_id 没给 → 生成
                if not task_id:
                    task_id = f"{kind}_{int(time.time())}"
                # 兜底: intent_template 没给 → 用 description
                if not intent_template:
                    intent_template = description or f"⏰ {kind} fire"

                try:
                    cycle_minutes = float(cycle_minutes)
                except Exception:
                    return "❌ cyclic_task.register: cycle_minutes 非法 (需数值)"

                if not start_at or not end_at:
                    return ("❌ cyclic_task.register: missing start_at/end_at "
                              "(格式 'YYYY-MM-DD HH:MM' 或 'HH:MM')")

                r = store.register(
                    task_id=task_id, kind=kind, description=description,
                    cycle_minutes=cycle_minutes,
                    start_at=start_at, end_at=end_at,
                    intent_template=intent_template,
                    created_by='main_brain',
                )
                if not r.get('ok'):
                    return f"❌ cyclic_task.register fail: {r.get('error')}"
                return (
                    f"✅ cyclic_task.register: task_id={r['task_id']} kind={kind} "
                    f"展开 {r['n_fires']} 个 fires "
                    f"({r['first_at']} → {r['last_at']}, every {cycle_minutes}min). "
                    f"reminders 已入 hippocampus, ChronosSentinel 会自动 fire."
                )

            elif command == 'cancel':
                task_id = (params.get('task_id') or '').strip()
                reason = (params.get('reason') or '')[:200]
                if not task_id:
                    return "❌ cyclic_task.cancel: missing task_id"
                r = store.cancel(task_id, reason=reason)
                if not r.get('ok'):
                    return f"❌ cyclic_task.cancel fail: {r.get('error')}"
                return (f"✅ cyclic_task.cancel: '{task_id}' cancelled, "
                          f"removed {r['n_removed']} pending fires.")

            elif command == 'list':
                tasks = store.list_active()
                if not tasks:
                    return "ℹ️ cyclic_task.list: 当前无 active 循环任务."
                lines = [f"📋 Active cyclic_tasks ({len(tasks)}):"]
                for t in tasks:
                    lines.append(
                        f"  - {t.task_id} ({t.kind}): every {t.cycle_minutes}min "
                        f"{t.start_iso} → {t.end_iso} "
                        f"[{len(t.fire_ids)} fires]"
                    )
                return '\n'.join(lines)

            elif command == 'status':
                task_id = (params.get('task_id') or '').strip()
                if not task_id:
                    return "❌ cyclic_task.status: missing task_id"
                t = store.get(task_id)
                if not t:
                    return f"❌ cyclic_task.status: '{task_id}' not found"
                return (
                    f"📋 cyclic_task '{task_id}': kind={t.kind} state={t.state} "
                    f"every {t.cycle_minutes}min {t.start_iso}→{t.end_iso}, "
                    f"{len(t.fire_ids)} scheduled fires, "
                    f"created by {t.created_by}."
                )
            else:
                return (f"❌ cyclic_task: 未知指令 {command} "
                          f"(支持 register / cancel / list / status)")

        # 🆕 [P5-fix35-D / 2026-05-23] Progress Tracker organ — 通用数值进度跟踪
        # Sir 11:29 真测痛点: 主脑承诺"记到饮水记录" — 系统没真 store. 治本: 加这个.
        # 通用 (hydration/running/writing/pomodoro/...), 联动 cyclic_task (满自动 cancel cycle).
        if organ_name == "progress":
            try:
                from jarvis_progress_tracker import get_default_store as _get_pt_store
                store = _get_pt_store()
            except Exception as _pe:
                return f"❌ progress: store 不可用 ({_pe})"

            if command == 'register':
                track_id = (params.get('track_id') or '').strip()
                kind = (params.get('kind') or '').strip()
                label = (params.get('label') or '')[:200]
                target = params.get('target', 0)
                unit = (params.get('unit') or '')[:30]
                deadline = (params.get('deadline') or '')[:30]
                linked = (params.get('linked_cyclic_task') or '')[:80]
                if not track_id:
                    track_id = f"{kind or 'track'}_{int(time.time())}"
                r = store.register(
                    track_id=track_id, kind=kind, label=label,
                    target=target, unit=unit, deadline=deadline,
                    linked_cyclic_task=linked, created_by='main_brain',
                )
                if not r.get('ok'):
                    return f"❌ progress.register fail: {r.get('error')}"
                return (f"✅ progress.register: track_id={r['track_id']} kind={kind} "
                          f"target={r['target']}{unit}"
                          + (f" linked_cyclic={linked}" if linked else ""))

            elif command == 'update':
                track_id = (params.get('track_id') or '').strip()
                amount = params.get('amount', 0)
                note = (params.get('note') or '')[:200]
                if not track_id:
                    return "❌ progress.update: missing track_id"
                r = store.update(track_id=track_id, amount=amount,
                                   note=note, source='main_brain')
                if not r.get('ok'):
                    return f"❌ progress.update fail: {r.get('error')}"
                msg = f"✅ progress.update: {r['brief']}"
                if r.get('became_complete'):
                    msg += f" 🎯 已达成!"
                    if r.get('cancelled_linked_cycle'):
                        msg += f" (linked cycle '{r['cancelled_linked_cycle']}' 已自动 cancel)"
                return msg

            # 🆕 [P5-fix73 / 2026-05-23 17:58] BUG-J: progress.set 绝对值覆写
            # Sir 17:55 真测痛点: 主脑在 Sir 纠正时只能 += → 双倍累加超目标.
            # set 让主脑覆写当前值到 Sir 期望的绝对值 (e.g. "总共 2000ml" → set 2000).
            elif command == 'set':
                track_id = (params.get('track_id') or '').strip()
                new_current = params.get('new_current', params.get('value', 0))
                note = (params.get('note') or '')[:200]
                if not track_id:
                    return "❌ progress.set: missing track_id"
                r = store.set_absolute(
                    track_id=track_id, new_current=new_current,
                    note=note, source='main_brain',
                )
                if not r.get('ok'):
                    return f"❌ progress.set fail: {r.get('error')}"
                msg = (f"✅ progress.set: {r['old_current']}→{r['new_current']} "
                          f"(delta={r['delta']:+}) {r['brief']}")
                if r.get('became_complete'):
                    msg += f" 🎯 已达成!"
                    if r.get('cancelled_linked_cycle'):
                        msg += f" (linked cycle '{r['cancelled_linked_cycle']}' 已 cancel)"
                return msg

            elif command == 'status':
                track_id = (params.get('track_id') or '').strip()
                if not track_id:
                    return "❌ progress.status: missing track_id"
                r = store.status(track_id)
                if not r.get('ok'):
                    return f"❌ progress.status: {r.get('error')}"
                lines = [
                    f"📊 progress.status '{track_id}':",
                    f"  kind: {r['kind']}  label: {r['label'] or '(no label)'}",
                    f"  state: {r['state']}",
                    f"  brief: {r['brief']}",
                    f"  deadline: {r['deadline_iso'] or '(none)'}",
                    f"  linked_cyclic: {r['linked_cyclic_task'] or '(none)'}",
                    f"  history: {r['history_n']} entries",
                ]
                return '\n'.join(lines)

            elif command == 'cancel':
                track_id = (params.get('track_id') or '').strip()
                reason = (params.get('reason') or '')[:200]
                if not track_id:
                    return "❌ progress.cancel: missing track_id"
                r = store.cancel(track_id, reason=reason)
                if not r.get('ok'):
                    return f"❌ progress.cancel fail: {r.get('error')}"
                return f"✅ progress.cancel: '{track_id}' cancelled."

            elif command == 'list':
                tracks = store.list_active()
                if not tracks:
                    return "ℹ️ progress.list: 当前无 active progress."
                lines = [f"📊 Active progress tracks ({len(tracks)}):"]
                for t in tracks:
                    lines.append(f"  - {t.track_id} ({t.kind}): {t.render_brief()}")
                return '\n'.join(lines)

            else:
                return (f"❌ progress: 未知指令 {command} "
                          f"(支持 register / update / set / status / cancel / list)")

        # 🆕 [Translator Phase 1 / 2026-05-24 20:42] Path A 同款灰度切 (Self-audit 发现 Path B 已加但 Path A 漏)
        # 详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md
        # FEATURE_TRANSLATOR=1 启用 → 老 fuzzy 退路保留 (Phase 4 才物理删)
        _translator_pa = getattr(self.jarvis, 'translator', None)
        _use_translator_pa = (
            _translator_pa is not None
            and os.environ.get('JARVIS_FEATURE_TRANSLATOR', '0') == '1'
        )
        if _use_translator_pa:
            _t_result_pa = _translator_pa.translate(organ_name, command, params)
            if not _t_result_pa.success:
                # actionable msg → return 给 Path A 调用方 (主脑下轮看)
                try:
                    from jarvis_utils import bg_log as _t_bg_pa
                    _t_bg_pa(
                        f"❌ [Translator/Path A] reject {organ_name}.{command} "
                        f"({_t_result_pa.error_kind}): "
                        f"{(_t_result_pa.actionable_msg or '')[:80]}"
                    )
                except Exception:
                    pass
                return f"❌ {_t_result_pa.actionable_msg}"
            organ_name = _t_result_pa.organ_name
            command = _t_result_pa.command
            params = _t_result_pa.params

        # 🆕 [P5-fix77-Q / 2026-05-23 19:11] BUG-Q: fuzzy alias (同 Path B)
        hand_class = self.jarvis.hand_registry.get(organ_name)
        if hand_class is None and not organ_name.endswith('_hands'):
            _aliased = organ_name + '_hands'
            hand_class = self.jarvis.hand_registry.get(_aliased)
            if hand_class is not None:
                try:
                    from jarvis_utils import bg_log as _alias_bg_pa
                    _alias_bg_pa(
                        f"🔀 [Alias Resolve / Path A] '{organ_name}' → '{_aliased}'"
                    )
                except Exception:
                    pass
                organ_name = _aliased
        if hand_class:
            try:
                hand_inst = hand_class(self.jarvis.gemini_key)
            except TypeError:
                hand_inst = hand_class()

            from jarvis_blood import Action
            hand_capture = io.StringIO()
            with contextlib.redirect_stdout(hand_capture):
                exec_res = hand_inst.execute(Action(command=command, params=params))
            tool_result = exec_res.msg

            if exec_res.success:
                path_val = (params.get("path") or params.get("destination") or
                            params.get("source_dir") or params.get("filepath") or
                            params.get("source") or params.get("folder_path"))
                if path_val and os.path.exists(path_val):
                    folder_path = os.path.dirname(path_val) if os.path.isfile(path_val) else path_val
                    alias = os.path.basename(folder_path)
                    if alias:
                        landmark_file = os.path.join("jarvis_config", "os_landmarks.json")
                        try:
                            lms = {}
                            if os.path.exists(landmark_file):
                                with open(landmark_file, "r", encoding="utf-8") as f:
                                    lms = json.load(f)
                            if alias not in lms or lms[alias] != folder_path:
                                lms[alias] = folder_path
                                with open(landmark_file, "w", encoding="utf-8") as f:
                                    json.dump(lms, f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                return f"✅ {organ_name}.{command}: {tool_result[:80]}"
            else:
                return f"❌ {organ_name}.{command}: {tool_result[:80]}"
        else:
            return f"Error: Organ '{organ_name}' is not mounted."

    # ==========================================
    def stream_chat_cloud_followup(self, prompt: str, user_input: str = "",
                                    stm_context: str = "", ltm_context: str = "",
                                    route_callback=None):
        """
        云端补答：在本地首答之后，调用 Gemini 提供深度回答。
        继续使用同一个边框，追加显示。
        """
        # 🩹 [β.2.9.10] 异步工具结果也注入云端补答路径
        try:
            _drain_text = self.drain_pending_tool_results()
            if _drain_text:
                prompt = _drain_text + "\n" + (prompt or '')
        except Exception:
            pass
        import re
        self.is_interrupted = False
        self._has_routed_this_turn = False
        print(f"║ 🤖  [Jarvis-云端] ", end="", flush=True)

        try:
            _t0 = time.time()
            _t_ss_start = time.time()
            # 🆕 [P5-fix35 / 2026-05-23] 云端补答路径 vision capability gate
            # 🩹 [Sir 2026-05-27 12:25] 同 stream_chat L3050 治本: 锁屏 screen grab 失败
            # → text-only fallback (不阻塞云端补答, 不触发外层 fallback 罐头回复)
            _supports_vision_cf = getattr(self, 'main_brain_supports_vision', True)
            img_bytes = None
            if _supports_vision_cf:
                try:
                    from PIL import ImageGrab
                    screen_img = ImageGrab.grab()
                    screen_img.thumbnail((1280, 720))
                    img_buf = io.BytesIO()
                    screen_img.save(img_buf, format="JPEG", quality=50)
                    img_bytes = img_buf.getvalue()
                except Exception as _ss_err_cf:
                    img_bytes = None
                    try:
                        from jarvis_utils import bg_log as _ss_bg_cf
                        _ss_bg_cf(f"⚠️ [CloudFallback/NoScreenshot] {type(_ss_err_cf).__name__}: "
                                    f"{_ss_err_cf} → text-only fallback")
                    except Exception:
                        pass
            _t_ss_done = time.time()
            if img_bytes is not None:
                chat_history = [types.Content(role="user", parts=[
                    types.Part(text=prompt),
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                ])]
            else:
                chat_history = [types.Content(role="user", parts=[
                    types.Part(text=prompt),
                ])]

            full_text = ""
            streamed_text = ""
            buffer = ""
            _pending_jarvis_header = False
            _first_tool_in_chain = True
            # 与 self._last_tool_results 共引用（云端补答路径）
            self._last_tool_results = _tool_results = []
            # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切 (cloud followup 路径)
            _first_sent_done = False

            while True:
                if getattr(self, 'is_interrupted', False):
                    print("\n🛑[Cloud Stream] Interrupt signal received.")
                    break
                is_subtitle_mode = False
                _exec = None
                try:
                    _exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    _t_api_start = time.time()
                    _future = _exec.submit(self._create_stream, chat_history)
                    response, _stream_key_name = _future.result(timeout=30.0)
                    _t_api_done = time.time()
                except concurrent.futures.TimeoutError:
                    print("\n║ ⚠️  [Cloud Timeout] Gemini API response timeout")
                    print("╚" + "═"*63 + "\n")
                    return ""
                except Exception as _e:
                    print(f"║ ⚠️  [Cloud Error] {str(_e)[:100]}")
                    print("╚" + "═"*63 + "\n")
                    return ""
                finally:
                    if _exec is not None:
                        _exec.shutdown(wait=False)

                fast_call_triggered = False

                for chunk in response:
                    if getattr(self, 'is_interrupted', False):
                        break

                    if chunk.text:
                        text_delta = chunk.text
                        buffer += text_delta
                        full_text += text_delta

                        if "<FAST_CALL>" in full_text:
                            if "</FAST_CALL>" in full_text:
                                fast_call_triggered = True
                                break
                            else:
                                is_forming_tag = True

                        # [P0+18-c.1] cloud followup 同步加结构化标签半成形态守门
                        if _is_forming_structural_tag(full_text):
                            is_forming_tag = True

                        if not is_forming_tag:
                            clean_full = full_text.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
                            clean_full = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', clean_full)
                            # [P0+18-c.1] 整段剥结构化标签 block（同主路径）
                            clean_full = _strip_structural_tag_blocks(clean_full)
                            _zh_seen = "---ZH---" in clean_full
                            if _zh_seen:
                                clean_full = clean_full.split("---ZH---")[0].rstrip('\n')
                            if "[CLIPBOARD]" in clean_full:
                                clean_full = clean_full.split("[CLIPBOARD]")[0]
                            # 🆕 [Sir 2026-05-24 22:00 真测 META 泄漏字幕 BUG]
                            # 主脑 reply 末尾 emit [META] 一行 (evidence/reaction/skip_alert)
                            # 后置 parse_meta 在 stream 完成后才裁 → 中间 splitter 已把 [META] 行
                            # 当 sentence 喂 _put_audio + subtitle_queue.put → Sir 字幕看到 META +
                            # TTS render 非自然语言 → 可能卡 wave_queue.
                            # 治本: 上游 stream 时同 [CLIPBOARD] 切, [META] 后内容不进 streamed_text.
                            if "[META]" in clean_full:
                                clean_full = clean_full.split("[META]")[0].rstrip()

                            delta = clean_full[len(streamed_text):]
                            if delta:
                                if _pending_jarvis_header:
                                    print(f"║ 🤖  [Jarvis-云端] ", end="", flush=True)
                                    _pending_jarvis_header = False
                                print(_box_newline(delta), end="", flush=True)
                                streamed_text += delta

                        if "<ENGAGE_PHYSICAL_BODY>" in full_text and not self._has_routed_this_turn:
                            print(f"\n║ ⚡  [System] 最高授权已授予，唤醒 L1~L5 深度战术网络...")
                            self._has_routed_this_turn = True
                            if route_callback:
                                threading.Thread(target=route_callback, daemon=True).start()

                        if "<REQUEST_PHYSICAL>" in full_text and not self._has_routed_this_turn:
                            print(f"\n║ ⚠️[System] 检测到深度物理请求，等待人工确认...")
                            self._has_routed_this_turn = True

                        if "<IGNORE>" in full_text:
                            print(f"\n║ 🔇  [Ambient] 检测到旁白对话，系统保持静默。")
                            print("╚" + "═"*63 + "\n")
                            return ""

                        while True:
                            # 🩹 [P0+20-β.2.7.3] 复用 helper（含 organ.command 保护）
                            # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切
                            earliest_idx = _find_sentence_split_idx(buffer, soft_split=True, is_first_sentence=not _first_sent_done)
                            if earliest_idx == -1 and len(buffer) > 80:
                                for i in range(len(buffer) - 1, 20, -1):
                                    if buffer[i] == ' ':
                                        earliest_idx = i
                                        break
                            if earliest_idx != -1:
                                sentence = buffer[:earliest_idx + 1].strip()
                                buffer = buffer[earliest_idx + 1:]
                                if "---ZH---" in sentence:
                                    is_subtitle_mode = True
                                    sentence = sentence.split("---ZH---")[0]
                                elif is_subtitle_mode:
                                    sentence = ""
                                elif _sentence_is_chinese_lean(sentence):
                                    # [P0+18-e.2 / 2026-05-15] 上游 Audio Guard (cloud followup)
                                    is_subtitle_mode = True
                                    try:
                                        from jarvis_utils import bg_log as _zh_up_bg
                                        _zh_up_bg(
                                            f"🛡️ [Audio Guard / Upstream / Cloud-followup] 中文 sentence 无 ---ZH--- → "
                                            f"自动进 subtitle_mode: '{sentence[:60]}'"
                                        )
                                    except Exception:
                                        pass
                                    self.subtitle_queue.put(("zh", sentence))
                                    sentence = ""
                                sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                                sentence = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', sentence).strip()
                                sentence = sentence.replace("J A R V I S", "Jarvis").replace("JARVIS", "Jarvis")
                                if sentence:
                                    self._put_audio(sentence)
                                    self.subtitle_queue.put(("en", sentence))
                                    _first_sent_done = True  # β.5.9
                            else:
                                break

                if fast_call_triggered:
                    fast_call_match = re.search(r'<FAST_CALL>(.*?)</FAST_CALL>', full_text, re.DOTALL)
                    fast_call_json = fast_call_match.group(1).strip()
                    spoken_so_far = full_text.split("<FAST_CALL>")[0].strip()
                    clean_spoken = spoken_so_far.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
                    if "---ZH---" in clean_spoken:
                        clean_spoken = clean_spoken.split("---ZH---")[0].rstrip('\n')
                    if "[CLIPBOARD]" in clean_spoken:
                        clean_spoken = clean_spoken.split("[CLIPBOARD]")[0]
                    delta = clean_spoken[len(streamed_text):]
                    if delta:
                        if _pending_jarvis_header:
                            print(f"║ 🤖  [Jarvis-云端] ", end="", flush=True)
                            _pending_jarvis_header = False
                        print(_box_newline(delta), end="", flush=True)
                        streamed_text += delta

                    if buffer.strip() and not getattr(self, 'is_interrupted', False):
                        sentence = buffer.strip()
                        # [P0+18-c.11 / 2026-05-15] 修中文 subtitle 漏到 TTS 上游路径
                        # is_subtitle_mode 在前面 splitter 设过 True 时，末尾 buffer 不应再喂 TTS
                        if "---ZH---" in sentence:
                            is_subtitle_mode = True
                            sentence = sentence.split("---ZH---")[0]
                        elif is_subtitle_mode:
                            sentence = ""
                        elif _sentence_is_chinese_lean(sentence):
                            # [P0+18-e.2 / 2026-05-15] 上游 Audio Guard
                            is_subtitle_mode = True
                            try:
                                from jarvis_utils import bg_log as _zh_up_bg
                                _zh_up_bg(
                                    f"🛡️ [Audio Guard / Upstream / FAST_CALL-flush] 中文 sentence 无 ---ZH--- → "
                                    f"subtitle_mode: '{sentence[:60]}'"
                                )
                            except Exception:
                                pass
                            self.subtitle_queue.put(("zh", sentence))
                            sentence = ""
                        sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                        if sentence:
                            self._put_audio(sentence)
                            self.subtitle_queue.put(("en", sentence))

                    try:
                        fc = json.loads(fast_call_json)
                        organ = fc.get("organ", "")
                        command = fc.get("command", "")
                        params = fc.get("params", {})
                        print(f"\n║ ⚡ [FAST_CALL] {organ}.{command}")
                        # 🩹 [β.2.9.10] 软超时异步: 短工具同步等(无感), 长工具放手
                        # 让主 stream 立刻继续, tool 后台跑完写 _pending_tool_results
                        result, was_sync = self._execute_fast_call_with_soft_timeout(
                            organ, command, params,
                            timeout=self.TOOL_SOFT_TIMEOUT_S)
                        if result is not None:
                            _tool_results.append(result)
                            mark = '✅' if was_sync else '⏳'
                            print(f"║ {mark} [Result] {str(result)[:120]}")
                    except Exception as fce:
                        print(f"║ ❌ [FAST_CALL Failed] {fce}")

                    full_text = ""
                    streamed_text = ""
                    buffer = ""
                    _pending_jarvis_header = True
                    _first_tool_in_chain = False
                    continue

                if buffer.strip() and not getattr(self, 'is_interrupted', False):
                    sentence = buffer.strip()
                    # [P0+18-c.1] 末尾 buffer 整段剥结构化标签 block
                    sentence = _strip_structural_tag_blocks(sentence)
                    # [P0+18-c.11 / 2026-05-15] 末尾 buffer 检查 is_subtitle_mode,
                    # 避免 ZH 内容（前面 splitter 已切走 EN）被喂给 _put_audio
                    if "---ZH---" in sentence:
                        is_subtitle_mode = True
                        sentence = sentence.split("---ZH---")[0]
                    elif is_subtitle_mode:
                        sentence = ""
                    elif _sentence_is_chinese_lean(sentence):
                        # [P0+18-e.2 / 2026-05-15] 上游 Audio Guard
                        is_subtitle_mode = True
                        try:
                            from jarvis_utils import bg_log as _zh_up_bg
                            _zh_up_bg(
                                f"🛡️ [Audio Guard / Upstream / End-buffer] 中文 sentence 无 ---ZH--- → "
                                f"subtitle_mode: '{sentence[:60]}'"
                            )
                        except Exception:
                            pass
                        self.subtitle_queue.put(("zh", sentence))
                        sentence = ""
                    sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                    if sentence:
                        self._put_audio(sentence)
                        self.subtitle_queue.put(("en", sentence))

                if _tool_results:
                    print(f"╟" + "─"*63)
                    for r in _tool_results:
                        print(f"║ {r}")
                    print(f"╟" + "─"*63)

                if _first_tool_in_chain is False and _pending_jarvis_header:
                    print(f"╟" + "─"*63)
                    print(f"║ 🤖  [Jarvis-云端] ", end="", flush=True)
                    _pending_jarvis_header = False

                final_clean = full_text.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
                # [P0+18-c.1] final_clean 整段剥结构化标签 block + 兜底剥孤立标签
                final_clean = _strip_structural_tag_blocks(final_clean)
                final_clean = _strip_structural_tags_only(final_clean)
                final_clean = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', final_clean)
                zh_subtitle_text = ""
                if "---ZH---" in final_clean:
                    zh_subtitle_text = final_clean.split("---ZH---")[1].strip()
                    final_clean = final_clean.split("---ZH---")[0]
                if "[CLIPBOARD]" in final_clean:
                    final_clean = final_clean.split("[CLIPBOARD]")[0]

                last_delta = final_clean[len(streamed_text):].rstrip('\n')
                if last_delta:
                    print(_box_newline(last_delta), end="", flush=True)

                if zh_subtitle_text:
                    clean_zh = re.sub(r'<[^>]+>', '', zh_subtitle_text).strip()
                    if clean_zh:
                        # [P0+18-c.12 / 2026-05-15] 多段 ZH (含 \n\n) 走 _box_newline,每行加 ║ 前缀
                        print("\n" + _box_newline(f"║ 📺  [Subtitle] {clean_zh}"))
                        # 🆕 [Sir 23:24 BUG-1 治本] ZH 末尾不合法 → defer put (worker 补)
                        _en_for_check = (final_clean.split('---ZH---')[0] if '---ZH---' in (final_clean or '') else (final_clean or ''))
                        if _zh_subtitle_looks_truncated(clean_zh, len(_en_for_check.strip())):
                            try:
                                from jarvis_utils import bg_log as _zh_def_bg
                                _zh_def_bg(f"⏸ [Subtitle/ZH-defer] leftover ZH 末尾不合法 ({len(clean_zh)}ch '{clean_zh[-20:]}'), 跳过 put, 等 truncate_continuation_worker 补完整 atomic put 防双段闪烁")
                            except Exception:
                                pass
                        else:
                            self.subtitle_queue.put(("zh", clean_zh))

                if not getattr(self, 'is_interrupted', False):
                    print("")
                    print("╚" + "═"*63 + "\n")

                if "[CLIPBOARD]" in full_text:
                    clipboard_content = full_text.split("[CLIPBOARD]")[1].strip()
                    try:
                        import pyperclip
                        pyperclip.copy(clipboard_content)
                        print(f"[Clipboard] {len(clipboard_content)} 字符已注入 Windows 剪贴板。")
                    except ImportError:
                        pass

                final_reply = full_text.split("---ZH---")[0].strip()
                if "---ZH---" in full_text:
                    zh_text = full_text.split("---ZH---")[1].strip()
                    clean_zh = re.sub(r'<[^>]+>', '', zh_text).strip()
                    if clean_zh:
                        # 🆕 [Sir 23:24 BUG-1 治本] 末尾不合法 → defer (worker continuation 补 atomic put)
                        if _zh_subtitle_looks_truncated(clean_zh, len(final_reply)):
                            try:
                                from jarvis_utils import bg_log as _zh_def_bg2
                                _zh_def_bg2(f"⏸ [Subtitle/ZH-defer] leftover ZH 末尾不合法 ({len(clean_zh)}ch '{clean_zh[-20:]}'), 跳过 put, 等 worker 补")
                            except Exception:
                                pass
                        else:
                            self.subtitle_queue.put(("zh", clean_zh))

                if '_stream_key_name' in dir():
                    self.key_router.release(_stream_key_name)

                # 🔧 [β.5.36-G / 2026-05-20] 解析主脑输出的 <TOOL_CALL>{intent} 标签 → IntentRouter
                # Sir BUG 3 修法: LLM 用 intent 解耦工具名, 后端翻译执行. 失败/未知 intent 静默,
                # 主路径不阻塞. dangerous intent 跳过自动执行 (走 PROMISE 路径).
                # 在 PROMISE/MEMORY_UPDATE 之前跑, 让 intent 结果尽快回流 SWM 给主脑下轮看到.
                try:
                    from jarvis_intent_router import IntentParser, get_default_intent_router
                    if IntentParser.has_tool_call_tag(full_text):
                        _router = get_default_intent_router()
                        if _router is not None:
                            _ir_results = _router.route_and_invoke_all(full_text)
                            if _ir_results:
                                try:
                                    from jarvis_utils import bg_log as _ir_bg
                                    _hits = sum(1 for r in _ir_results if r.get('success'))
                                    _ir_bg(
                                        f"🔧 [IntentRouter] {len(_ir_results)} tool calls "
                                        f"({_hits} success): "
                                        + ', '.join(
                                            f"{r.get('intent_id', '?')}={'✅' if r.get('success') else '❌'}"
                                            for r in _ir_results[:5]
                                        )
                                    )
                                except Exception:
                                    pass
                except Exception:
                    pass

                # 🆕 [P5-fix45 / 2026-05-23 14:55] 解析 <CONCERN_DAMPEN> tag (主脑自决)
                # Sir 14:51 真痛点: '我中午睡了 1h, 你记录一下' → mutation organ ✅ 写
                # ProfileCard, 但 sir_sleep_streak severity 没削. 治: 主脑看 SWM
                # 'sir_field_updated' + active concerns severity 自决 emit
                # <CONCERN_DAMPEN cid="..." delta="-0.X" reason="..."/> tag.
                # 此 parser 解析 → ledger.record_signal + publish 'concern_dampen_applied' SWM.
                try:
                    from jarvis_concern_dampen import process_reply as _dampen_process
                    _ledger_dam = getattr(getattr(self, 'jarvis', None),
                                            'concerns_ledger', None)
                    if _ledger_dam is not None and full_text and '<CONCERN_DAMPEN' in full_text:
                        _dampen_n = _dampen_process(
                            full_text, _ledger_dam, turn_id=turn_id)
                        if _dampen_n > 0:
                            try:
                                from jarvis_utils import bg_log as _dam_bg
                                _dam_bg(
                                    f"📉 [ConcernDampen/Applied] {_dampen_n} dampen "
                                    f"tag(s) processed (主脑自决, 准则 6 决策集中主脑)"
                                )
                            except Exception:
                                pass
                except Exception:
                    pass

                # [轴3-L3.1 / 2026-05-15] 解析主脑输出的 <PROMISE> 标签 → PlanLedger
                # LLM 承诺 multi-step 动作时通过 PROMISE tag 落账本（awaiting_go），等 Sir 说 "go" 才执行
                # 任何异常都被吞，绝不影响主流程
                try:
                    from jarvis_skill_registry import PromiseParser, PromiseActivator
                    plan_ledger_ref = getattr(getattr(self, 'jarvis', None), 'plan_ledger', None)

                    if PromiseParser.has_promise_tag(full_text) and plan_ledger_ref is not None:
                        drafts = PromiseParser.extract_all(full_text)
                        if drafts:
                            plan_ids = PromiseParser.draft_to_ledger(drafts, plan_ledger_ref)
                            if plan_ids:
                                try:
                                    from jarvis_utils import bg_log
                                    bg_log(f"📜 [PromiseLedger] {len(plan_ids)} promise(s) drafted, awaiting Sir's 'go': "
                                           f"{', '.join(d.goal[:40] for d in drafts)}")
                                except Exception:
                                    pass

                    # [轴3-L3.2 / 2026-05-15] 解析 <ACTIVATE_PLAN> / <CANCEL_PLAN> / <RESUME_PLAN> 标签
                    # LLM 看到 ACTIVE PLAN 块 + Sir 说 "go/yes" → 输出 ACTIVATE_PLAN 触发状态机变更
                    # [轴3-L3.3 / 2026-05-15] RESUME_PLAN — paused (dangerous_confirm/clarification) 复活
                    if PromiseActivator.has_any_tag(full_text) and plan_ledger_ref is not None:
                        PromiseActivator.activate_from_text(full_text, plan_ledger_ref)

                    # 🩹 [β.2.9.9 → P5-fix35 / 2026-05-23] <MEMORY_UPDATE> tag 已废弃
                    # 老路径: 写 profile_corrections.jsonl (audit) 但**不真改 sir_profile.json**.
                    # 新路径: FAST_CALL `mutation` organ → gateway → overwrite_field 真改.
                    # 保留 tag 兼容 + 写 audit (不破 ProfileReflector 累积逻辑) +
                    # 但加 deprecation warning + publish SWM 提醒主脑改用 FAST_CALL.
                    try:
                        from jarvis_safety import (
                            parse_memory_update_tags, execute_memory_updates
                        )
                        _mu_updates = parse_memory_update_tags(full_text)
                        if _mu_updates:
                            _n_written = execute_memory_updates(
                                _mu_updates, source='llm_tag_DEPRECATED')
                            if _n_written > 0:
                                try:
                                    from jarvis_utils import bg_log as _mu_bg
                                    _mu_bg(
                                        f"⚠️ [MemoryUpdate/DEPRECATED] LLM 用了 "
                                        f"<MEMORY_UPDATE> 老标签 (写 {_n_written} 条 audit, "
                                        f"但 sir_profile.json 未改). 主脑应改用 "
                                        f"FAST_CALL mutation organ (correction_dispatcher)."
                                    )
                                except Exception:
                                    pass
                                # 🆕 [P5-fix35] publish SWM event 让主脑下轮 prompt 看到自己用错了 syntax
                                try:
                                    from jarvis_utils import get_event_bus
                                    _bus = get_event_bus()
                                    if _bus is not None:
                                        _bus.publish(
                                            etype='deprecated_syntax_used',
                                            description=(
                                                f"主脑用了已废弃 <MEMORY_UPDATE> tag "
                                                f"({_n_written} 条). 真改源未生效, sir_profile.json "
                                                f"没动. 下次教正请用 FAST_CALL mutation organ."
                                            ),
                                            source='chat_bypass.memory_update_parser',
                                            salience=0.60,
                                        )
                                except Exception:
                                    pass
                    except Exception as _mu_e:
                        try:
                            from jarvis_utils import bg_log as _mu_bg
                            _mu_bg(f"⚠️ [MemoryUpdate] parse/execute fail: {_mu_e}")
                        except Exception:
                            pass
                        PromiseActivator.cancel_from_text(full_text, plan_ledger_ref)
                        PromiseActivator.resume_from_text(full_text, plan_ledger_ref)
                except Exception:
                    pass

                # 🩹 [P0+20-β.2.7.3 / 2026-05-17] Self-Promise Detector (cloud followup)
                try:
                    from jarvis_self_promise import get_default_detector as _gdp_cf
                    cw_cf = getattr(self.jarvis, 'commitment_watcher', None)
                    if full_text and cw_cf is not None:
                        _gdp_cf().detect_and_register_async(
                            jarvis_reply=full_text,
                            commitment_watcher=cw_cf,
                            turn_id='cloud_followup',
                        )
                except Exception:
                    pass

                return final_reply

        except Exception as e:
            print(f"\n🛑[Cloud Stream] Interrupt signal received.")
            print("╚" + "═"*63 + "\n")
            if '_stream_key_name' in dir():
                self.key_router.release(_stream_key_name)
            return ""

    # ==========================================
    def stream_chat(self, prompt: str, user_input: str = "", clean_intent: str = None,
                    stm_context: str = "", ltm_context: str = "", route_callback=None,
                    gate_future=None, prompt_tier: str = None):
        self.last_stm_context = stm_context
        self.last_ltm_context = ltm_context

        # 🩹 [β.2.9.10 / 2026-05-18] 异步工具结果注入: 上轮 FAST_CALL 后台完成的
        # result 在此 prepend 到 prompt, 主脑能看到真实工具反馈, 不再凭空说话.
        try:
            _drain_text = self.drain_pending_tool_results()
            if _drain_text:
                prompt = _drain_text + "\n" + (prompt or '')
        except Exception:
            pass

        import re
        print(f"\n" + "╔" + "═"*63)
        clean_user_input = user_input.replace(": ", "", 1) if user_input.startswith(": ") else user_input
        display_input = re.sub(r'^\[(?:WAKE_ONLY|WORK_MODE|RELAX_MODE)(?:\|(?:WAKE_ONLY|WORK_MODE|RELAX_MODE))*\]\s*', '', clean_user_input)
        print(_box_newline(f"║ 🗣️  [Human] {display_input}"))
        if clean_intent and clean_intent != display_input:
            print(f"║ 🎯  [Intent] {clean_intent}")
        print("╠" + "═"*63)

        if hasattr(self, 'jarvis') and self.jarvis:
            self.jarvis._in_conversation = True
            self.jarvis._last_user_active = time.time()
            self.jarvis._detect_wake_up()
            self.jarvis._detect_sleep_intent(clean_user_input)

        classifier = get_quick_classifier()
        if classifier.is_available:
            def _run_emotion():
                try:
                    recent = stm_context[-800:] if stm_context else clean_user_input
                    emotion = classifier.detect_emotion(recent)
                    if emotion != "neutral" and hasattr(self, 'jarvis') and self.jarvis:
                        self.jarvis._last_local_emotion = emotion
                except Exception:
                    pass
            threading.Thread(target=_run_emotion, daemon=True).start()

        if hasattr(self, 'jarvis') and hasattr(self.jarvis, 'correction_loop'):
            is_system_event = clean_intent and clean_intent.startswith('[后台系统')
            if not is_system_event:
                self.jarvis.correction_loop.on_user_input(clean_user_input)
                # 🩹 [P5-SirStatusTracker / 2026-05-21 15:25] Sir 13:49 痛点 — nudge 话术
                # context aware. Sir 说"睡觉了下午见" / "出去一下" → tracker update status →
                # ReturnSentinel return_greeting 出对应话术 (sleep return → "Hope you rested
                # well", out return → "Welcome back"). Async 不阻 main path.
                try:
                    from jarvis_sir_status_tracker import observe_sir_utterance_async
                    _turn_id_sst = ''
                    try:
                        from jarvis_utils import TraceContext
                        _turn_id_sst = TraceContext.current_turn() or ''
                    except Exception:
                        pass
                    observe_sir_utterance_async(clean_user_input, turn_id=_turn_id_sst)
                except Exception:
                    pass
                prev_response = ""
                stm = getattr(self.jarvis, 'short_term_memory', [])
                if stm:
                    prev_response = stm[-1].get('jarvis', '') if stm else ""
                correction_result = self.jarvis.correction_loop.detect_and_learn(clean_user_input, prev_response)
                if correction_result:
                    if correction_result.get('type') == 'correction':
                        print(f"║ 📝 [CorrectionLoop] 检测到纠正信号，已记录学习案例")
                    elif correction_result.get('type') == 'style':
                        print(f"║ 🎨 [StyleAdjust] 检测到风格偏好: {correction_result.get('direction', '')}")

        # 🩹 [β.2.9.9-D / 2026-05-18] Sir 10:43 反馈: 主动 nudge 后 Sir 回应
        # 应反馈到 concern severity. 通用 hook — 任何 Sir cmd 都跑一次
        # ProactiveCare 看是否是对最近 nudge 的回应 (120s 窗口内). 不阻塞主对话.
        try:
            if not is_system_event:
                from jarvis_proactive_care import get_default_engine
                _pce = get_default_engine()
                if _pce is not None and hasattr(_pce, 'notify_sir_response_post_nudge'):
                    _pce.notify_sir_response_post_nudge(clean_user_input or '')
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 20:14 真意 anchor 3] Sir Skepticism Learning Loop hook
        # =====================================================================
        # Sir 真意: "通过我跟他对话能动态调整 — 一个奇怪的 inside joke 我提质疑
        # 时会降低使用权重, 多次质疑甚至考虑删除. 不希望调工具."
        # Async fire-and-forget — Detector 检 keyword (vocab JSON) →
        # AttributionEngine 找 30s 内最 plausible target (inside_joke / nudge /
        # concern) → DecayEngine 累 skepticism_count + decay weight + publish SWM.
        # 主脑下轮 prompt 看 SWM 'sir_skepticism' / 'item_skepticism_decay' /
        # 'item_auto_archived' evidence 自决 (准则 6 evidence-driven).
        # is_system_event skip (后台事件 [SYSTEM ALERT] 非 Sir 真话, 不算质疑).
        # 详 jarvis_sir_skepticism.py + docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md.
        # =====================================================================
        try:
            if not is_system_event and clean_user_input:
                def _skepticism_worker(reply: str):
                    try:
                        from jarvis_sir_skepticism import process_sir_reply
                        process_sir_reply(reply)
                    except Exception:
                        pass
                threading.Thread(
                    target=_skepticism_worker,
                    args=(clean_user_input,),
                    daemon=True,
                    name='SirSkepticismDetect',
                ).start()
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 20:55 真痛追根 方案 D 治本] Thought Outcome Loop hook
        # =====================================================================
        # Sir 真痛 (Phase 2B 铺垫但没合环): InnerThought.outcome 字段就位但没人
        # 写没人读. 这导致 thought 不知 Sir 关心不关心 → 长期看 "想了一堆没体现".
        # D 闭环: chat_bypass post-reply hook 检 (a) 主脑上轮 reply 是否 reference
        # 某 thought (vocab pattern + token overlap) + (b) Sir 本轮反应
        # (engage/silence/reject). 综合判 outcome → 持久化 + publish SWM.
        # 详 jarvis_thought_outcome.py + docs/JARVIS_THINKING_TO_AGENCY_DESIGN.md §D.
        # =====================================================================
        try:
            if not is_system_event and clean_user_input:
                def _outcome_worker(reply: str):
                    try:
                        from jarvis_thought_outcome import process_sir_reply as _tov_proc
                        _tov_proc(reply)
                    except Exception:
                        pass
                threading.Thread(
                    target=_outcome_worker,
                    args=(clean_user_input,),
                    daemon=True,
                    name='ThoughtOutcomeWatch',
                ).start()
        except Exception:
            pass

        if hasattr(self, 'jarvis') and hasattr(self.jarvis, 'content_tracker'):
            prev_user = ""
            prev_jarvis = ""
            stm = getattr(self.jarvis, 'short_term_memory', [])
            if len(stm) >= 2:
                prev_user = stm[-2].get('user', '')
                prev_jarvis = stm[-2].get('jarvis', '')
            implicit = self.jarvis.content_tracker.detect_implicit_feedback(
                clean_user_input, prev_user, prev_jarvis
            )
            if implicit:
                self.jarvis.content_tracker.record_feedback(implicit, clean_user_input, prev_jarvis)
        
        self.is_interrupted = False 
        self._has_routed_this_turn = False
        # 🧹 [打印整顿] 开启背景日志缓冲：在 stream_chat 期间所有 KeyRouter/HabitClock/
        # Pipeline Timer / 海马体检索降级 等异步日志会被暂存，等对话框收尾后统一 flush，
        # 这样对话框内只剩 Jarvis 自己的话。
        try:
            from jarvis_utils import set_conversation_active
            set_conversation_active(True)
        except Exception:
            pass
        # [R7-β2 v3] 启动双档 backchannel timer：
        # - 0.6s 没收首 token → 播 chime（短 UI 音）
        # - 2.5s 还没收首 token → 本地说一句过渡话（"Let me check, Sir."）
        # 让 Sir 在 TTFT 等待期感受到"它在跟我对话"而非"它在卡"。
        try:
            # [v4] chime 阈值 1.5s（chime 已删，参数保留兼容性）
            # [轴 2.4] 传 prompt_tier 让 _maybe_say_local 按档选预渲 phrase
            self._start_backchannel_timer(threshold_sec=self._CHIME_THRESHOLD_DEFAULT,
                                          user_input=user_input,
                                          local_utterance_threshold=self._LOCAL_PHRASE_THRESHOLD,
                                          prompt_tier=prompt_tier)
        except Exception:
            pass
        print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
        print(f"║ 🤖  [Jarvis] ", end="", flush=True)
        
        try:
            _t0 = time.time()
            _t_ss_start = time.time()
            # [R7/Screenshot] 截图策略简化：
            # - WAKE_ONLY: 仅喊名字，无视觉需求 → 跳过（保留这条以省 ~50ms 唤醒延时）
            # - [R7-β1] FACTUAL_RECALL: 近期事实查询，答案在文本上下文里 → 跳过截图省 TTFT
            # - 其他全档（SHORT_CHAT / TOOL_REQUEST / DEEP_QUERY / CRITICAL）: 一律实时截屏
            # 原来的 60s 缓存已删除：JPEG quality=50 + 1280x720 体积已经很小，
            # 用 60s 旧帧会让 Jarvis "看不到 Sir 此刻正在指的画面"，得不偿失。
            img_bytes = None
            _ss_strategy = 'fresh'
            # 🆕 [P5-fix35 / 2026-05-23] 主对话路径 vision capability gate
            # text-only model → 直接跳过 ImageGrab + 主脑无视觉, 但不挂.
            _supports_vision_main = getattr(self, 'main_brain_supports_vision', True)
            if prompt_tier in ('WAKE_ONLY', 'FACTUAL_RECALL'):
                _ss_strategy = 'skipped'
            elif not _supports_vision_main:
                _ss_strategy = 'skipped_text_only_model'
            else:
                # 🩹 [Sir 2026-05-27 12:25 真痛 anchor] 主对话路径 screen grab failed 治本
                # =================================================================
                # Sir 真测 12:24 "睡觉了拜拜" dismissal 走主对话 → ImageGrab.grab() 抛
                # OSError 'screen grab failed' (锁屏/屏保/RDP 切窗) → 整个 stream_chat
                # 外层 try 异常 → 触发 _try_local_fallback → Ollama 8s 空 → 罐头回复
                # → Sir 听到沉默或不知所云. nudge 路径 L6373-6418 已 fix, 主对话路径漏.
                # 修法 (准则 8 优雅): inner try/except, 截图失败 → img_bytes=None
                # → L3086 已有 text-only chat_history fallback → 主脑用 prompt 文字答.
                # =================================================================
                try:
                    from PIL import ImageGrab
                    screen_img = ImageGrab.grab()
                    screen_img.thumbnail((1280, 720))
                    img_buf = io.BytesIO()
                    screen_img.save(img_buf, format="JPEG", quality=50)
                    img_bytes = img_buf.getvalue()
                except Exception as _ss_err:
                    # 锁屏 / 屏保 / RDP 切窗 / 多 monitor 全可能. 不阻塞主对话.
                    _ss_strategy = f'fail_{type(_ss_err).__name__}_text_only_fallback'
                    img_bytes = None
                    try:
                        from jarvis_utils import bg_log as _ss_bg
                        _ss_bg(f"⚠️ [Chat/NoScreenshot] {type(_ss_err).__name__}: "
                                f"{_ss_err} → text-only fallback (prompt 不带 image)")
                    except Exception:
                        pass
            _t_ss_done = time.time()

            try:
                from jarvis_utils import bg_log
                _ss_elapsed_ms = int((_t_ss_done - _t_ss_start) * 1000)
                bg_log(f"📸 [Screenshot] strategy={_ss_strategy} | elapsed={_ss_elapsed_ms}ms | tier={prompt_tier}")
            except Exception:
                pass

            # 🆕 [P5-Gap3 / 2026-05-21 18:35] 复用已有截图喂 ScreenVisionEngine
            # 节能: chat_bypass 已截图给主脑, 直接复用 img_bytes (不重复截图)
            # 异步喂给 vision engine 做结构化描述. 跨 turn 持久化让 ToM /
            # IntegrityWatcher 等能拿 vision evidence.
            # 节流: 60s 内只 sample 一次 (vision engine 内部锁防 concurrent).
            if img_bytes is not None:
                try:
                    from jarvis_screen_vision import get_default_engine as _get_sv
                    _sv = _get_sv()
                    if _sv is not None and _sv.enabled():
                        # 检查是否需要 sample (60s cache)
                        _sv_latest = _sv.get_latest_snapshot()
                        if _sv_latest is None or not _sv_latest.is_fresh(60.0):
                            # 复用 img_bytes — 不重复截图
                            _sv.async_describe(trigger='wake',
                                                  jpeg_bytes=img_bytes)
                except Exception:
                    pass

            # 🆕 [Sir 2026-05-27 真愿景 Phase 6] 取 Sir 最近一段 audio 给主脑听语气
            # =====================================================================
            # 设计:
            #   - env JARVIS_AUDIO_TO_BRAIN 控开关 (Sir 20:58 真测 TTFT 3.2s 无明显
            #     延迟, 21:00 决定改默认 '1' 常驻; 想关 set '0')
            #   - 从 voice_thread._last_audio_wav_bytes 取 (30s 内, ≤60s 长)
            #   - 加 types.Part.from_bytes(data=wav, mime_type='audio/wav') 进 parts
            #   - clean_intent 以 '[后台系统' 开头 (system_event) 跳过 (无 Sir 实时声音)
            #   - 主脑模型必须支持 audio (gemini-3-flash-preview / 2.5-flash/pro 全支持)
            #   - 任何异常静默 fallback 到无 audio (主链不挂)
            # 真实成本 (Sir 20:58 12s audio 实测):
            #   - 12s ≈ 300 audio tokens ≈ $0.00003 / turn (~0.0002 元)
            #   - 100 turn/天 ≈ 2 分钱/天
            # 关掉方法:
            #   $env:JARVIS_AUDIO_TO_BRAIN='0'  (下个 turn 立刻生效, 无需重启)
            # =====================================================================
            _audio_wav_bytes: bytes = b''
            _audio_duration_sec: float = 0.0
            try:
                if (os.environ.get('JARVIS_AUDIO_TO_BRAIN', '1').strip() == '1'
                        and _supports_vision_main  # multimodal 模型才送 audio
                        and not (clean_intent and str(clean_intent).startswith('[后台系统'))):
                    _vt = getattr(getattr(self, 'jarvis', None),
                                       'voice_thread', None)
                    if _vt is not None and hasattr(_vt, 'get_recent_audio_for_brain'):
                        _audio_wav_bytes, _audio_duration_sec = (
                            _vt.get_recent_audio_for_brain(max_age_sec=30.0)
                        )
                        if _audio_wav_bytes:
                            try:
                                from jarvis_utils import bg_log as _ab_bg
                                _ab_bg(
                                    f"🎤 [AudioToBrain] 送 audio 给主脑 "
                                    f"({_audio_duration_sec:.1f}s, "
                                    f"{len(_audio_wav_bytes)//1024}KB)"
                                )
                            except Exception:
                                pass
            except Exception:
                _audio_wav_bytes = b''

            # 组 parts: text + (image if any) + (audio if any)
            # 🆕 [Phase 6] 含 audio 时 prompt 末尾追一句提示主脑感知语气, 不主动 quote.
            # 🩹 [Sir 2026-05-27 20:55 真测 BUGFIX] 不能用 .format(...) — prompt 内
            # 含 JSON 字面量 (e.g. `{"intent": "..."}`), 会被 str.format 误当 placeholder
            # → KeyError: '"intent"'. 治本: 把 audio_hint 作为独立 f-string 拼接, prompt
            # 部分**不经 format** 处理.
            _prompt_with_audio_hint = prompt
            if _audio_wav_bytes:
                # 🩹 [Sir 2026-05-27 21:11 真测] 旧 hint "Listen to tone/laughter/..."
                # 让主脑过度关注情绪, 中性 turn 仍编造 audio_tone evidence (幻觉).
                # Sir 原话: "我不是每句话都会带情绪的, 有时候就是正常说话,
                # 别写的太严格给主脑搞幻觉了."
                # 修: 中性 turn 视音频为 absent, ONLY-IF 真有明显信号才 emit
                # audio_tone evidence. 禁安全词 ('neutral'/'calm'/'balanced').
                _audio_hint = (
                    f"\n\n[AUDIO ATTACHED] Sir's actual voice recording "
                    f"(~{_audio_duration_sec:.1f}s) is included alongside the "
                    f"ASR text above.\n"
                    f"How to use:\n"
                    f"- ASR text is the literal content. Audio is for tone/"
                    f"mood signal ONLY (not transcription).\n"
                    f"- Most of Sir's turns are NEUTRAL — plain speech, no "
                    f"laughter, no sigh, no obvious emotion. In that case "
                    f"treat audio as ABSENT — do NOT mention audio_tone in "
                    f"your evidence list, do NOT change your default tone.\n"
                    f"- ONLY if you hear a CLEAR signal (laughter / sigh / "
                    f"frustration / excitement / tense / wry / soft), attune "
                    f"your reply tone AND add `audio_tone:<signal>` to your "
                    f"evidence list.\n"
                    f"- Do NOT fabricate emotion. 'neutral' / 'calm' / "
                    f"'balanced' / 'composed' count as fabrication — omit "
                    f"audio_tone entirely instead.\n"
                    f"- Do NOT quote or transcribe the audio."
                )
                _prompt_with_audio_hint = prompt + _audio_hint
            _parts = [types.Part(text=_prompt_with_audio_hint)]
            if img_bytes is not None:
                _parts.append(types.Part.from_bytes(
                    data=img_bytes, mime_type="image/jpeg"
                ))
            if _audio_wav_bytes:
                _parts.append(types.Part.from_bytes(
                    data=_audio_wav_bytes, mime_type="audio/wav"
                ))
            chat_history = [types.Content(role="user", parts=_parts)]
            
            full_text = ""
            streamed_text = ""
            buffer = ""
            _pending_jarvis_header = False
            _first_tool_in_chain = True
            # 与 self._last_tool_results 共引用，append 会自动同步给外层（用于后置幻觉守门）
            self._last_tool_results = _tool_results = []
            _tool_chain_iterations = 0
            _MAX_TOOL_CHAIN = 5
            # 🛡️ 连续失败熔断（Bug X3）：≥2 次畸形或失败工具调用 → 提前跳出，避免空转
            _consecutive_tool_fail = 0
            _MAX_CONSECUTIVE_FAIL = 2
            # 🛡️ 重复成功调用熔断（Bug B 修复）：同一 (organ, command, params) 调到第 2 次直接判停
            # — 大模型常在工具成功后继续输出相同 FAST_CALL，把链路耗到 5/5，最后空回复触发兜底
            _call_signature_count = {}
            _MAX_SAME_CALL = 2  # 同一签名调到第 2 次就熔断
            _circuit_broken_reason = None  # 记下熔断原因，供事后兜底文案使用
            
            while True:
                _tool_chain_iterations += 1
                if _tool_chain_iterations > _MAX_TOOL_CHAIN:
                    print(f"\n║ ⚠️  [Tool Chain] 达到最大迭代次数({_MAX_TOOL_CHAIN})，强制终止工具链")
                    _circuit_broken_reason = "max_iterations"
                    break
                if getattr(self, 'is_interrupted', False):
                    print("\n🛑[FAST_CALL Chain] Global interrupt received, fusing tool chain.")
                    break
                is_subtitle_mode = False

                _search_keywords = ['search for', 'google', '搜索', '查一下', '帮我查', '帮我搜']
                enable_search = any(kw in user_input.lower() for kw in _search_keywords)

                _classifier_done = threading.Event()
                _classifier_result = [None]

                def _run_classifier():
                    try:
                        c = get_quick_classifier()
                        if c.is_available:
                            cat, _ = c.classify(user_input, stm_context)
                            timeout = c.calc_timeout(cat, user_input, stm_context)
                            _classifier_result[0] = (cat, timeout)
                    except Exception:
                        pass
                    finally:
                        _classifier_done.set()

                classifier_thread = threading.Thread(target=_run_classifier, daemon=True)
                classifier_thread.start()

                category = "simple"

                _exec = None
                _cloud_connected = threading.Event()
                _cloud_response = [None]
                _cloud_key = [None]
                _cloud_error = [None]

                def _connect_cloud():
                    _key = None
                    try:
                        _t_api_start = time.time()
                        resp, _key = self._create_stream(chat_history, enable_search=enable_search)
                        _t_api_connected = time.time()
                        import itertools, concurrent.futures
                        try:
                            _exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                            _future = _exec.submit(next, resp)
                            first_chunk = _future.result(timeout=25.0)
                            _exec.shutdown(wait=False)
                            _t_first_chunk = time.time()
                            # 🩹 [β.2.7.6 / 2026-05-17] 暂存 TTFT 供精炼 timing log
                            try:
                                self._last_ttft_s = _t_first_chunk - _t_api_start
                            except Exception:
                                pass
                            # 🆕 [BUG C / Sir 2026-05-28 16:08] 暂存 checkpoint ts 供
                            # stream 末尾分段 timing log 算 pre_stream / stream_only / post_stream
                            try:
                                self._last_t_api_start_ts = _t_api_start
                                self._last_t_first_chunk_ts = _t_first_chunk
                            except Exception:
                                pass
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"⏱️ [Pipeline Timer] 首Token到达(TTFT): {_t_first_chunk - _t_api_start:.1f}s (连接{_t_api_connected - _t_api_start:.1f}s + 等待{_t_first_chunk - _t_api_connected:.1f}s)")
                                # [P0+18-f.5 / 2026-05-15] 细粒度诊断：把"连接 / 等待"差异 + 队列深度 + key 信息留在后台日志
                                # 下次 Sir 实测如果再慢，能 grep 出具体阶段瓶颈
                                try:
                                    from jarvis_utils import _TEE_QUEUE as _tee_q
                                    _q_depth = _tee_q.qsize()
                                except Exception:
                                    _q_depth = -1
                                bg_log(f"🔬 [Perf Diag] connect={_t_api_connected - _t_api_start:.2f}s wait={_t_first_chunk - _t_api_connected:.2f}s key={_key} tee_queue_depth={_q_depth}")
                            except Exception:
                                print(f"⏱️ [Pipeline Timer] 首Token到达(TTFT): {_t_first_chunk - _t_api_start:.1f}s (连接{_t_api_connected - _t_api_start:.1f}s + 等待{_t_first_chunk - _t_api_connected:.1f}s)", file=sys.stderr)
                            resp = itertools.chain([first_chunk], resp)
                        except StopIteration:
                            pass
                        _cloud_response[0] = resp
                        _cloud_key[0] = _key
                    except Exception as e:
                        if _key:
                            self.key_router.release(_key)
                        _key = None
                        print(f"\n╔" + "═"*63)
                        print(f"║ 🔴 [OpenRouter主键失败] {type(e).__name__}: {str(e)[:120]}")
                        print(f"╚" + "═"*63)
                        try:
                            _t_or_start = time.time()
                            from openai import OpenAI
                            import base64
                            or_key, or_key_name = self.key_router.get_openrouter_key(KeyRouter.CALLER_MAIN_BRAIN)
                            _key = or_key_name

                            messages = []
                            for content in chat_history:
                                role = content.role if hasattr(content, 'role') else 'user'
                                if role == 'model':
                                    role = 'assistant'
                                msg_parts = []
                                for part in content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        msg_parts.append({"type": "text", "text": part.text})
                                    elif hasattr(part, 'inline_data') and part.inline_data:
                                        img_b64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                                        msg_parts.append({
                                            "type": "image_url",
                                            "image_url": {"url": f"data:{part.inline_data.mime_type};base64,{img_b64}"}
                                        })
                                messages.append({"role": role, "content": msg_parts})

                            or_client = OpenAI(
                                base_url="https://openrouter.ai/api/v1",
                                api_key=or_key,
                                default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
                                timeout=60.0
                            )
                            # 🆕 [P5-fix77-I] 同主路径加 max_tokens 防截断
                            or_response = or_client.chat.completions.create(
                                model=self.main_brain_model,  # 🆕 P5-fix34 env override
                                messages=messages,
                                temperature=0.7,
                                max_tokens=8192,
                                stream=True
                            )

                            class _FakeChunk:
                                __slots__ = ('text',)
                                def __init__(self, text):
                                    self.text = text

                            def _or_gen():
                                for chunk in or_response:
                                    if chunk.choices and chunk.choices[0].delta.content:
                                        yield _FakeChunk(chunk.choices[0].delta.content)

                            _t_or_done = time.time()
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"⏱️ [Pipeline Timer] OpenRouter备键兜底: {_t_or_done - _t_or_start:.1f}s")
                            except Exception:
                                print(f"⏱️ [Pipeline Timer] OpenRouter备键兜底: {_t_or_done - _t_or_start:.1f}s", file=sys.stderr)
                            _cloud_response[0] = _or_gen()
                            _cloud_key[0] = or_key_name
                            print(f"╔" + "═"*63)
                            print(f"║ 🔄 [OpenRouter兜底] 主键失败，备键已接管(流式)")
                            print(f"╚" + "═"*63)
                        except Exception as e2:
                            _cloud_error[0] = e
                            print(f"╔" + "═"*63)
                            print(f"║ 🔴 [OpenRouter备键也失败] {type(e2).__name__}: {str(e2)[:120]}")
                            print(f"╚" + "═"*63)
                    finally:
                        _cloud_connected.set()

                cloud_thread = threading.Thread(target=_connect_cloud, daemon=True)
                cloud_thread.start()

                CLOUD_TIMEOUT = 30.0
                deadline = time.time() + CLOUD_TIMEOUT
                while not _cloud_connected.is_set() and time.time() < deadline:
                    if _classifier_done.is_set() and _classifier_result[0]:
                        cat, timeout = _classifier_result[0]
                        category = cat
                        _classifier_result[0] = None
                    time.sleep(0.1)

                if not _cloud_connected.is_set():
                    cloud_thread.join(timeout=2.0)
                    _elapsed = time.time() - _t0
                    print(f"\n║ ⚡ [本地兜底] {category}类查询, 云端{CLOUD_TIMEOUT:.0f}秒无响应 (总耗时{_elapsed:.1f}秒)")
                    local_reply = self._try_local_fallback(user_input, stm_context)
                    if local_reply:
                        print(f"║ 🔄 [本地兜底] 切换到 {get_local_fallback()._model}")
                        print(f"║ 🤖  [Jarvis-Local] {local_reply[:200]}")
                        self._speak_local_reply(local_reply)
                    else:
                        self._speak_fallback()
                    print("╚" + "═"*63 + "\n")
                    return True, local_reply or "fallback"

                _ttft = time.time() - _t0
                # [P0+18-a.15 / 2026-05-15] 修 BUG #10: 主对话框只剩 Jarvis 说的话 / Sir 说的话 / 工具调用 + 结果 / 中文 Subtitle。
                # 诊断信息（TTFT / Pipeline / Screenshot 等）一律走 bg_log，在 ╚ 之后统一 flush。
                # 之前在 `║ 🤖 [Jarvis] ` 行末尾（end=""） 后直接 print() 默认换行 → "║ ⏱️ [Pipeline] First token" 挤在同一行。
                try:
                    from jarvis_utils import bg_log as _ttft_bg
                    _ttft_bg(f"⏱️ [Pipeline] First token: {_ttft:.1f}s (deadline was {CLOUD_TIMEOUT:.0f}s, category={category})")
                except Exception:
                    pass

                cloud_thread.join(timeout=5.0)

                if _cloud_error[0]:
                    _e = _cloud_error[0]
                    if _cloud_key[0]:
                        self.key_router.release(_cloud_key[0])
                        self.key_router.report_error(_cloud_key[0], str(_e))
                    _elapsed = time.time() - _t0
                    import traceback as _tb
                    print(f"\n║ ╔══ [API错误详情] ═══════════════════════════════════")
                    print(f"║ ║ 类型: {type(_e).__name__}")
                    print(f"║ ║ 消息: {_e}")
                    print(f"║ ║ 耗时: {_elapsed:.1f}秒")
                    print(f"║ ╚══════════════════════════════════════════════════════════")
                    local_reply = self._try_local_fallback(user_input, stm_context)
                    if local_reply:
                        print(f"║ 🔄 [本地兜底] 切换到 {get_local_fallback()._model}")
                        print(f"║ 🤖  [Jarvis-Local] {local_reply[:200]}")
                        self._speak_local_reply(local_reply)
                        print("╚" + "═"*63 + "\n")
                        return True, local_reply
                    print("╚" + "═"*63 + "\n")
                    self._speak_fallback()
                    return False, "fallback"

                if not _cloud_response[0]:
                    _elapsed = time.time() - _t0
                    print(f"\n╔" + "═"*63)
                    print(f"║ ⚠️  [网络熔断] Gemini API 超时 (总耗时{_elapsed:.1f}秒)")
                    print(f"╚" + "═"*63)
                    local_reply = self._try_local_fallback(user_input, stm_context)
                    if local_reply:
                        print(f"║ 🔄 [本地兜底] 切换到 {get_local_fallback()._model}")
                        print(f"║ 🤖  [Jarvis-Local] {local_reply[:200]}")
                        self._speak_local_reply(local_reply)
                        print("╚" + "═"*63 + "\n")
                        return True, local_reply
                    print("╚" + "═"*63 + "\n")
                    self._speak_fallback()
                    return False, "fallback"

                response = _cloud_response[0]
                _stream_key_name = _cloud_key[0]
                buffer = ""
                fast_call_triggered = False
                gatekeeper_triggered = False
                _chunk_count = 0
                _t_stream_start = time.time()
                # 🩹 [P0+20-β.5.9 / 2026-05-19] BUG-3 fix: 首句激进切 (hard>=8/soft>=4)
                # 让 Sir 听到首句 audio 更快. 后续句保持原阈值保 prosody.
                _first_sent_done = False
                
                for chunk in response:
                    _chunk_count += 1
                    if getattr(self, 'is_interrupted', False):
                        print("\n🛑[Chat Bypass] 流式输出已强制熔断。")
                        break 
                        
                    if chunk.text:
                        text_delta = chunk.text
                        buffer += text_delta
                        full_text += text_delta 
                        
                        is_forming_tag = False
                        # [P0+18-c.1] 加 PROMISE/ACTIVATE_PLAN/CANCEL_PLAN/RESUME_PLAN 到守门
                        tags_to_monitor =["<ENGAGE_PHYSICAL_BODY>", "<REQUEST_PHYSICAL>", "<IGNORE>", "---ZH---", "[CLIPBOARD]", "<FAST_CALL>", "<AWAIT_GATEKEEPER>", "<PROMISE>", "<ACTIVATE_PLAN>", "<CANCEL_PLAN>", "<RESUME_PLAN>"]
                        
                        for tag in tags_to_monitor:
                            for i in range(1, len(tag)):
                                if full_text.endswith(tag[:i]):
                                    is_forming_tag = True
                                    break
                            if is_forming_tag:
                                break
                                
                        if "<FAST_CALL>" in full_text:
                            if "</FAST_CALL>" in full_text:
                                fast_call_triggered = True
                                break 
                            else:
                                is_forming_tag = True 

                        # [P0+18-c.1] 结构化标签半成形态 → 暂停 splitter（避免按 ,/。 切到中间 JSON 喂 TTS）
                        if _is_forming_structural_tag(full_text):
                            is_forming_tag = True

                        if "<AWAIT_GATEKEEPER>" in full_text:
                            gatekeeper_triggered = True
                            break 
                                
                        if not is_forming_tag:
                            clean_full = full_text.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
                            clean_full = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', clean_full)
                            # [P0+18-c.1] 整段剥结构化标签 block（含中间 JSON / 任何 payload），
                            # 否则 `<PROMISE>{"goal":..., "steps":[...]}</PROMISE>` 会被打到终端 + 喂 TTS
                            clean_full = _strip_structural_tag_blocks(clean_full)
                            _zh_seen = "---ZH---" in clean_full
                            if _zh_seen:
                                clean_full = clean_full.split("---ZH---")[0].rstrip('\n')
                                
                            if "[CLIPBOARD]" in clean_full:
                                clean_full = clean_full.split("[CLIPBOARD]")[0]
                            # 🆕 [Sir 2026-05-24 22:00 真测 META 泄漏字幕 BUG]
                            # 同 cloud_followup 路径. 详见上方注释.
                            if "[META]" in clean_full:
                                clean_full = clean_full.split("[META]")[0].rstrip()

                            delta = clean_full[len(streamed_text):]
                            if delta:
                                if _pending_jarvis_header:
                                    print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
                                    print(f"║ 🤖  [Jarvis] ", end="", flush=True)
                                    _pending_jarvis_header = False
                                # [R7-β2] 收到首个可见 token → cancel backchannel timer
                                self._mark_first_token()
                                print(_box_newline(delta), end="", flush=True)
                                streamed_text += delta
                                # 🩹 [β.2.8.4 / 2026-05-17] Sir 22:08 实测 BUG:
                                # 字幕英文重复双写 — token-level put + sentence-level put
                                # 双写 → SubtitleOverlay._en_words.extend 两次 → 内容乱序重复.
                                # 修: 删 token-level put, 仅保留 sentence-level put.
                                # 终端 print(delta) 仍实时, 字幕只滞后到句切完才出 (200-800ms).

                        if "<ENGAGE_PHYSICAL_BODY>" in full_text and not self._has_routed_this_turn:
                            print(f"\n║ ⚡  [System] 最高授权已授予，唤醒 L1~L5 深度战术网络...")
                            print(f"║ ", end="", flush=True) 
                            self._has_routed_this_turn = True
                            if route_callback:
                                threading.Thread(target=route_callback, daemon=True, name='RouteCallback').start()
                                
                        if "<REQUEST_PHYSICAL>" in full_text and not self._has_routed_this_turn:
                            print(f"\n║ ⚠️[System] 检测到深度物理请求，等待人工确认...")
                            print(f"║ ", end="", flush=True)
                            self._has_routed_this_turn = True
                                
                        if "<IGNORE>" in full_text:
                            print(f"\n║ 🔇  [Ambient] 检测到旁白对话，系统保持静默。")
                            print("╚" + "═"*63 + "\n")
                            return False, ""

                        # 🛡️ Bug E 修复：FAST_CALL / 其他标签处于"半成形"或"已开未闭"状态时，
                        # 暂停句子切分（splitter），否则 buffer 里的 <FAST_CALL>{json...}</FAST_CALL>
                        # 会被按逗号切片，再经 `<[^>]+>` 通用 strip 后把 JSON 字面文本喂给 TTS，
                        # 听起来就是"贾维斯一直在念错误"。
                        if is_forming_tag:
                            continue

                        while True:
                            # 🩹 [P0+20-β.2.7.3] 复用 helper（含 organ.command 保护）
                            # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切
                            earliest_idx = _find_sentence_split_idx(buffer, soft_split=True, is_first_sentence=not _first_sent_done)

                            if earliest_idx == -1 and len(buffer) > 80:
                                for i in range(len(buffer) - 1, 20, -1):
                                    if buffer[i] == ' ':
                                        earliest_idx = i
                                        break
                                        
                            if earliest_idx != -1:
                                sentence = buffer[:earliest_idx + 1].strip()
                                buffer = buffer[earliest_idx + 1:]
                                
                                if "---ZH---" in sentence:
                                    is_subtitle_mode = True
                                    sentence = sentence.split("---ZH---")[0]
                                elif is_subtitle_mode:
                                    sentence = "" 
                                elif _sentence_is_chinese_lean(sentence):
                                    # [P0+18-e.2 / 2026-05-15] 上游 Audio Guard: sentence 含中文且
                                    # 没看到 ---ZH--- 标签 → 视为隐式 subtitle 模式,中文进字幕不进 TTS。
                                    # 修 Sir 18:22 实测 BUG（182238.log:479,953）：Memory Correction
                                    # 兜底后,主脑下一句直接出中文(无 ---ZH---),splitter 喂给 _put_audio,
                                    # 兜底 Audio Guard 拦下但 log 仍有 warning。本上游守门防回归。
                                    is_subtitle_mode = True
                                    try:
                                        from jarvis_utils import bg_log as _zh_up_bg
                                        _zh_up_bg(
                                            f"🛡️ [Audio Guard / Upstream] 中文 sentence 无 ---ZH--- → "
                                            f"自动进 subtitle_mode: '{sentence[:60]}'"
                                        )
                                    except Exception:
                                        pass
                                    self.subtitle_queue.put(("zh", sentence))
                                    sentence = ""

                                sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                                sentence = sentence.replace("J A R V I S", "Jarvis").replace("JARVIS", "Jarvis")
                                if sentence:
                                    self._put_audio(sentence)
                                    self.subtitle_queue.put(("en", sentence))
                                    _first_sent_done = True  # β.5.9 首句已发, 后续保守
                            else:
                                break

                # 👇 当触发门神等待时
                if gatekeeper_triggered:
                    spoken_so_far = full_text.split("<AWAIT_GATEKEEPER>")[0].strip()
                    
                    clean_spoken = spoken_so_far.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
                    if "---ZH---" in clean_spoken:
                        clean_spoken = clean_spoken.split("---ZH---")[0].rstrip('\n')
                    if "[CLIPBOARD]" in clean_spoken:
                        clean_spoken = clean_spoken.split("[CLIPBOARD]")[0]
                        
                    delta = clean_spoken[len(streamed_text):]
                    if delta:
                        if _pending_jarvis_header:
                            print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
                            print(f"║ 🤖  [Jarvis] ", end="", flush=True)
                            _pending_jarvis_header = False
                        # [R7-β2] 收到首 token（gatekeeper 分支） → cancel backchannel
                        self._mark_first_token()
                        print(_box_newline(delta), end="", flush=True)
                        streamed_text += delta
                        # 🩹 [β.2.8.4 / 2026-05-17] 删 token-level 字幕 put 防双写 (详 line 2033)

                    if buffer.strip() and not getattr(self, 'is_interrupted', False):
                        sentence = buffer.strip()
                        # [P0+18-c.11 / 2026-05-15] gatekeeper_triggered 路径 buffer flush
                        # 同样要检查 is_subtitle_mode,避免 ZH 末尾内容漏给 _put_audio
                        if "---ZH---" in sentence:
                            is_subtitle_mode = True
                            sentence = sentence.split("---ZH---")[0]
                        elif is_subtitle_mode:
                            sentence = ""
                        elif _sentence_is_chinese_lean(sentence):
                            # [P0+18-e.2 / 2026-05-15] 同上游 Audio Guard
                            is_subtitle_mode = True
                            try:
                                from jarvis_utils import bg_log as _zh_up_bg
                                _zh_up_bg(
                                    f"🛡️ [Audio Guard / Upstream / GK-flush] 中文 sentence 无 ---ZH--- → "
                                    f"自动进 subtitle_mode: '{sentence[:60]}'"
                                )
                            except Exception:
                                pass
                            self.subtitle_queue.put(("zh", sentence))
                            sentence = ""
                        sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                        if sentence:
                            self._put_audio(sentence)
                            self.subtitle_queue.put(("en", sentence))
                        buffer = ""

                    gate_result_text = ""
                    self._gate_data_to_save = [{}]
                    self._gate_clean_intent = None
                    if gate_future is not None:
                        try:
                            gate_result = gate_future.result(timeout=20.0)
                            if gate_result.get('gate_data_to_save'):
                                self._gate_data_to_save = gate_result['gate_data_to_save']
                            if gate_result.get('clean_intent'):
                                self._gate_clean_intent = gate_result['clean_intent']
                            if gate_result.get('gate_result_text'):
                                gate_result_text = gate_result['gate_result_text']
                            elif gate_result.get('system_alert_text'):
                                gate_result_text = f"Gatekeeper FAILED: {gate_result['system_alert_text']}"
                            elif self._gate_data_to_save and len(self._gate_data_to_save) > 0 and self._gate_data_to_save[0]:
                                gd = self._gate_data_to_save[0]
                                is_future = gd.get('is_future_task', False)
                                trigger_time = gd.get('trigger_time_str', '')
                                if is_future and trigger_time:
                                    gate_result_text = f"Gatekeeper SUCCESS: Reminder saved. Trigger time: {trigger_time}. Intent: {gd.get('clean_intent', '')}"
                                else:
                                    gate_result_text = f"Gatekeeper SUCCESS: Memory saved. Intent: {gd.get('clean_intent', '')}"
                            else:
                                gate_result_text = "Gatekeeper SUCCESS: Memory saved."
                            gate_future = None
                        except concurrent.futures.TimeoutError:
                            gate_result_text = "Gatekeeper TIMEOUT: Memory system is overloaded. The reminder may NOT have been saved."
                        except Exception as e:
                            gate_result_text = f"Gatekeeper ERROR: {str(e)[:100]}. The reminder may NOT have been saved."
                    else:
                        gate_result_text = "Gatekeeper SKIPPED: No gatekeeper was started for this short input."

                    _tool_results.append(f"🚪 {gate_result_text}")

                    # [R7/OneShot] 提醒 / 记忆走 Fast Path 风格的单确认路径，不再喂回大模型走第二轮。
                    # 行为对齐 set_volume：用户一句指令 → Step 1 ("I shall note that down…") → 直接收尾。
                    # 节省 ~5s 的 TTFT + 流式时间，TTS 不再念第二遍"The reminder is set for…"。
                    _gate_ok = gate_result_text.startswith("Gatekeeper SUCCESS") or gate_result_text.startswith("Gatekeeper SKIPPED")
                    _gate_fail = gate_result_text.startswith(("Gatekeeper TIMEOUT", "Gatekeeper ERROR", "Gatekeeper FAILED"))

                    # 若 LLM 一句话都还没说就甩出 <AWAIT_GATEKEEPER>（极少见），用本地兜底句替代
                    if not spoken_so_far:
                        _gd0 = (self._gate_data_to_save or [{}])[0] if isinstance(self._gate_data_to_save, list) else {}
                        _is_future = _gd0.get('is_future_task', False)
                        _trigger = _gd0.get('trigger_time_str', '')
                        if _gate_ok and _is_future and _trigger:
                            _en = f"Reminder set for {_trigger}, Sir."
                            _zh = f"提醒已设置在 {_trigger}，Sir。"
                        elif _gate_ok:
                            _en = "Noted, Sir."
                            _zh = "已记下，Sir。"
                        elif _gate_fail:
                            _en = "I couldn't confirm that one, Sir — could you say it again?"
                            _zh = "Sir，那一句没记牢，您能再说一遍吗？"
                        else:
                            _en = "Done, Sir."
                            _zh = "已完成。"
                        try:
                            self._put_audio(_en)
                            self.subtitle_queue.put(("en", _en))
                            self.subtitle_queue.put(("zh", _zh))
                        except Exception:
                            pass
                        # 让收尾打印 / STM 能拿到这段本地合成的话
                        full_text = f"{_en} ---ZH--- {_zh}"
                        # [P0+18-a.15 / 2026-05-15] 修 BUG #10: Gatekeeper 状态进 bg_log，主对话框只剩"说话→回答→工具→回答"
                        try:
                            from jarvis_utils import bg_log as _gk_bg
                            _gk_bg(f"🚪 [Gatekeeper One-Shot/Local] {gate_result_text[:120]}")
                        except Exception:
                            pass
                    else:
                        # [P0+18-a.15] Step 1 acknowledgment 已通过 _put_audio 念出，这里 bg_log 留痕
                        try:
                            from jarvis_utils import bg_log as _gk_bg
                            _gk_bg(f"🚪 [Gatekeeper One-Shot] {gate_result_text[:120]}")
                        except Exception:
                            pass

                    _circuit_broken_reason = "gatekeeper_one_shot" if _gate_ok else "gatekeeper_one_shot_fail"

                    # 释放本轮 key，结束流式循环
                    if '_stream_key_name' in dir() and _stream_key_name:
                        self.key_router.release(_stream_key_name)
                        _stream_key_name = None
                    break

                # 👇 当触发盲操拦截器时
                if fast_call_triggered:
                    fast_call_match = re.search(r'<FAST_CALL>(.*?)</FAST_CALL>', full_text, re.DOTALL)
                    fast_call_json = fast_call_match.group(1).strip()
                    
                    spoken_so_far = full_text.split("<FAST_CALL>")[0].strip()
                    
                    clean_spoken = spoken_so_far.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
                    if "---ZH---" in clean_spoken:
                        clean_spoken = clean_spoken.split("---ZH---")[0].rstrip('\n')
                    if "[CLIPBOARD]" in clean_spoken:
                        clean_spoken = clean_spoken.split("[CLIPBOARD]")[0]
                        
                    delta = clean_spoken[len(streamed_text):]
                    if delta:
                        if _pending_jarvis_header:
                            print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
                            print(f"║ 🤖  [Jarvis] ", end="", flush=True)
                            _pending_jarvis_header = False
                        # [R7-β2] 收到首 token（fast_call 分支） → cancel backchannel
                        self._mark_first_token()
                        print(_box_newline(delta), end="", flush=True)
                        streamed_text += delta
                        # 🩹 [β.2.8.4 / 2026-05-17] 删 token-level 字幕 put 防双写 (详 line 2033)

                    # 🛡️ Bug E 修复 (cont.)：buffer 此时可能装着 "<FAST_CALL>{json}</FAST_CALL>" + 
                    # LLM 在 FAST_CALL 之后预先吹的牛（"Done, Sir." 之类）。
                    # 必须先把 FAST_CALL 整段剥掉、再切掉 FAST_CALL 之后的内容（那段是工具结果还没回来时的幻觉），
                    # 否则会喂给 TTS 念出 JSON 字面、或在工具其实失败时仍念"已完成"。
                    if not getattr(self, 'is_interrupted', False):
                        _bf_no_fc = re.sub(r'<FAST_CALL>.*?</FAST_CALL>', '', buffer, flags=re.DOTALL)
                        # buffer 里 FAST_CALL 之前的、属于 spoken_so_far 范畴的剩余文本才是可读的
                        # 而 FAST_CALL 之后的文本暂时丢掉（工具结果还没回来，LLM 不应抢答）
                        _bf_pre_fc = _bf_no_fc.split("<FAST_CALL>")[0]  # 兜底：万一只剥到一半
                        sentence = _bf_pre_fc.strip()
                        if "---ZH---" in sentence:
                            sentence = sentence.split("---ZH---")[0]
                        sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                        if sentence:
                            self._put_audio(sentence)
                            self.subtitle_queue.put(("en", sentence))
                    buffer = ""

                    if hasattr(self.jarvis, 'focus_callback'):
                        try:
                            self.jarvis.focus_callback(True)
                        except TypeError:
                            self.jarvis.focus_callback()

                    if _first_tool_in_chain:
                        _first_tool_in_chain = False
                    # [R7-β post-test v4] 在 try 前预置默认值 —— 防止 json.loads 抛异常时
                    # 走到 except 分支再走到 continuation_prompt 时 UnboundLocalError。
                    # 这是 23:03:50 实测 "贾维斯帮我声音调整到呃40%" 崩溃的根因：
                    # 含中文语气词的 FAST_CALL JSON 解析失败 → command 从未赋值 → continuation_prompt 引用炸了。
                    organ_name = None
                    command = '<malformed_fast_call>'
                    params = {}
                    tool_result = ""
                    # [v4] 先单独抓 JSON 解析错误，给 LLM 一条明确的"重发或道歉"回路，不要让它走 continuation_prompt
                    import json as _json_mod
                    try:
                        call_data = _json_mod.loads(fast_call_json)
                    except Exception as _je:
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"⚠️ [FAST_CALL JSON 解析失败] {str(_je)[:80]} — 视为 LLM 幻觉，请求重发或诚实拒绝")
                        except Exception:
                            pass
                        _consecutive_tool_fail += 1
                        if _consecutive_tool_fail >= _MAX_CONSECUTIVE_FAIL:
                            print(f"║ 🛑 [Tool Chain] 连续 {_consecutive_tool_fail} 次 JSON 畸形，提前熔断")
                            _circuit_broken_reason = "malformed_json"
                            if '_stream_key_name' in dir() and _stream_key_name:
                                self.key_router.release(_stream_key_name)
                                _stream_key_name = None
                            break
                        chat_history.append(types.Content(role="model", parts=[types.Part(text=spoken_so_far)]))
                        chat_history.append(types.Content(role="user", parts=[types.Part(text=(
                            f"[SYSTEM] Your last <FAST_CALL> contained invalid JSON ({str(_je)[:60]}). "
                            f"Either (a) emit a properly formed FAST_CALL JSON with valid 'organ', 'command', 'params' fields, "
                            f"or (b) if no tool fits Sir's request, admit honestly: "
                            f"'I lack the means to do that directly, Sir.' followed by ---ZH--- and Chinese. "
                            f"Do NOT pretend you completed the action."
                        ))]))
                        if '_stream_key_name' in dir() and _stream_key_name:
                            self.key_router.release(_stream_key_name)
                            _stream_key_name = None
                        full_text = ""
                        streamed_text = ""
                        continue
                    try:
                        organ_name = call_data.get("organ")
                        command = call_data.get("command")
                        params = call_data.get("params", {})

                        # 🛡️ Bug X2 修复：畸形 FAST_CALL（缺 organ/command）不算"真工具调用"
                        # 不计入 _tool_results，让外层 B 守门人仍能仓底检测幻觉
                        if not organ_name or not command:
                            # [P0+20-α.5 / 2026-05-16] 日志降级：print → bg_log
                            # 解决 jarvis_20260516_105347.log:327 'Malformed FAST_CALL' 直接污染
                            # 对话框（Sir 在终端看到一长串技术日志夹在 Jarvis 回复之间）。
                            try:
                                from jarvis_utils import bg_log as _bg
                                _bg(f"⚠️ [Malformed FAST_CALL] organ='{organ_name}' command='{command}' — 视为 LLM 幻觉")
                            except Exception:
                                pass
                            _consecutive_tool_fail += 1
                            if _consecutive_tool_fail >= _MAX_CONSECUTIVE_FAIL:
                                try:
                                    from jarvis_utils import bg_log as _bg
                                    _bg(f"🛑 [Tool Chain] 连续 {_consecutive_tool_fail} 次畸形调用，提前熔断")
                                except Exception:
                                    pass
                                _circuit_broken_reason = "malformed_calls"
                                if '_stream_key_name' in dir() and _stream_key_name:
                                    self.key_router.release(_stream_key_name)
                                    _stream_key_name = None
                                break
                            # [P0+20-α.5 / 2026-05-16] SYSTEM 反馈强化禁止"假装完成"。
                            # jarvis_20260516_105347.log:327-337 实测：旧 SYSTEM 反馈说"either (a)
                            # emit valid FAST_CALL or (b) admit honestly" 但 LLM 选 (c) — 第二轮
                            # stream 直接撒谎 "I've captured the screen / The Cursor process is
                            # idle / Done, Sir — already completed on the first call"（14 秒 3
                            # 段假完成）。修法：在 SYSTEM 反馈里**显式禁止"假装完成 / 编新工具调用"
                            # 模式**，并示范唯一合法回复形态。
                            chat_history.append(types.Content(role="model", parts=[types.Part(text=spoken_so_far)]))
                            chat_history.append(types.Content(role="user", parts=[types.Part(text=(
                                f"[SYSTEM HARD CONSTRAINT] Your last <FAST_CALL> was malformed "
                                f"(missing 'organ' or 'command' field). You have ONE choice for "
                                f"your next response:\n"
                                f"- If a real tool can serve Sir's request, emit ONE properly formed "
                                f"<FAST_CALL> with valid organ + command + params.\n"
                                f"- Otherwise: respond with EXACTLY this template (no embellishment):\n"
                                f"    \"I lack the means to do that directly, Sir.\\n---ZH---\\n这件事我目前无法直接处理，先生。\"\n"
                                f"FORBIDDEN in your next response:\n"
                                f"- Claiming you 'captured the screen', 'examined the logs', "
                                f"'checked the process', 'refreshed' anything, or any past-tense "
                                f"action verb — these are lies if not backed by a successful tool call.\n"
                                f"- Saying 'Done, Sir' / 'already completed' / 'on the first call' "
                                f"or any phrase that implies the malformed call somehow succeeded.\n"
                                f"- Emitting another <FAST_CALL> that you are not certain is well-formed."
                            ))]))
                            if '_stream_key_name' in dir() and _stream_key_name:
                                self.key_router.release(_stream_key_name)
                                _stream_key_name = None
                            full_text = ""
                            streamed_text = ""
                            continue

                        for key in list(params.keys()):
                            val = params[key]
                            if isinstance(val, str):
                                _trailing_junk = '\u3002\uff0c\uff01\uff1f\u3001\uff1b\uff1a\uff09\u3011\u300b\u2026,;:.!?)'
                                val = val.rstrip(_trailing_junk + '\u201c\u201d\u2018\u2019' + '\'"')
                                val = val.strip()
                                params[key] = val

                        # 🛡️ Bug B 修复：重复调用熔断
                        # 同一 (organ, command, 规范化 params) 调到 _MAX_SAME_CALL 次就直接判停，
                        # 避免大模型在工具成功后继续输出相同 FAST_CALL，把 5/5 迭代耗尽 → 空回复 → 触发本地兜底
                        try:
                            _sig = (
                                organ_name,
                                command,
                                json.dumps(params, sort_keys=True, ensure_ascii=False, default=str),
                            )
                        except Exception:
                            _sig = (organ_name, command, repr(sorted(params.items())))
                        _call_signature_count[_sig] = _call_signature_count.get(_sig, 0) + 1
                        if _call_signature_count[_sig] >= _MAX_SAME_CALL:
                            # 🆕 [Sir 2026-05-24 23:01 真测 dedup 撒谎 BUG 治本] 区分 success/fail.
                            # 老逻辑无脑文案"上一次已成功", 但若 handler fail, 两次都 fail, 撒谎
                            # 误导调试. 改成检查上一次 _tool_results 是 ✅ 还是 ❌, 真话.
                            _last_status = '未知'
                            try:
                                # 看最近 _tool_results 第一字符判 success/fail
                                if _tool_results:
                                    _last_msg = str(_tool_results[-1].get('content', ''))
                                    if _last_msg.startswith('✅'):
                                        _last_status = '上一次已成功'
                                    elif _last_msg.startswith('❌'):
                                        _last_status = '上一次失败 (重试同参数无意义)'
                                    else:
                                        _last_status = '上一次状态未知 (无 ✅/❌ 前缀)'
                            except Exception:
                                pass
                            print(f"\n║ 🛑 [Tool Chain] 检测到重复调用 {organ_name}.{command} "
                                  f"(参数完全相同，第 {_call_signature_count[_sig]} 次)，提前熔断 — "
                                  f"{_last_status}")
                            _circuit_broken_reason = f"duplicate_call:{organ_name}.{command}"
                            # 别把这次"重复幻觉"再写进 _tool_results — 它没真执行，只是 LLM 在原地踏步
                            if '_stream_key_name' in dir() and _stream_key_name:
                                self.key_router.release(_stream_key_name)
                                _stream_key_name = None
                            break

                        SAFETY_GATE_ORGANS = ["system_hands", "file_operator_hands", "txt_writer_hands_generated"]
                        ACKNOWLEDGMENT_PATTERNS = [
                            r'^(okay|ok|yeah|yep|yes|sure|right|got it|mhm|uh huh|alright|fine|good|great|nice|cool|thanks|thx|ty)$',
                            r'^(okay|ok|yeah|yep|yes|sure|right|got it|mhm|alright|fine|good|great|nice|cool)[,.!]*$',
                        ]
                        user_input_clean = user_input.strip().lower().rstrip('.,!?')
                        is_acknowledgment = any(re.match(p, user_input_clean) for p in ACKNOWLEDGMENT_PATTERNS)

                        # 🆕 [P5-fix36 / 2026-05-23 12:11] FAST_CALL-only organ 路由治本.
                        # Sir 12:10 真测痛点: 主脑发 progress.update — Path B (slow 路径)
                        # 没 progress 分支, fallback 到 hand_registry.get('progress')
                        # → None → "❌ progress 未挂载". 同款 BUG 在 concerns / stand_down /
                        # promises / mutation / cyclic_task 都有 (Path A 有, Path B 没).
                        # 治本: 这些 organ 走 _execute_fast_call 同款实现 (DRY).
                        _FAST_CALL_ONLY_ORGANS = (
                            'concerns', 'stand_down', 'promises', 'mutation',
                            'cyclic_task', 'progress',
                            # 🆕 [Sir 2026-05-24 23:41 真测追根] commitment_watcher.forget
                            'commitment_watcher',
                        )
                        # 🆕 [P5-fix79 BUG-W / 2026-05-23 21:48] Sir 21:43 真测痛点:
                        # progress.set 成功 → fast-path break → 罐头 "Done, Sir." 替主脑.
                        # Sir 想听"当前 2700/3000 ml, 还差 300" 复述数据 而非干瘪罐头.
                        # 修法: progress 类 organ 不走 fast-path break, 让 tool result 喂回
                        # 主脑续 stream 1 句 ack (复用 hand_class 同款 continuation_prompt
                        # 路径). 准则 6 — 信任 LLM 自决话术. 这是"对话式 ack" 不是罐头.
                        # mutation 仍 break (FAST_CALL refactor 必须立刻 close + 显 audit).
                        # progress / cyclic_task 是 "数据更新" 类, ack 反馈给 Sir 才有价值.
                        _SKIP_FAST_BREAK_ORGANS = ('progress', 'cyclic_task')
                        if is_acknowledgment and organ_name in SAFETY_GATE_ORGANS:
                            tool_result = "SAFETY_GATE_BLOCKED: Sir's input was a simple acknowledgment, not an explicit request for file operations. Do NOT propose or execute file modifications unless Sir explicitly asks."
                            _tool_results.append(f"🛡️ 安全闸拦截: {organ_name}.{command}")
                        elif organ_name in _FAST_CALL_ONLY_ORGANS:
                            # 复用 _execute_fast_call (Path A 同款 implementation)
                            try:
                                _result = self._execute_fast_call(
                                    organ_name=organ_name,
                                    command=command,
                                    params=params,
                                )
                                _tool_results.append(_result)
                                # 成功 → 重置熔断 + 单步 Fast Path 收尾
                                if isinstance(_result, str) and _result.startswith('✅'):
                                    _consecutive_tool_fail = 0
                                    # 🆕 [P5-fix79 BUG-W] progress / cyclic_task 不走
                                    # fast break — 让主脑续 stream 1 句 ack (复述真数据).
                                    if organ_name in _SKIP_FAST_BREAK_ORGANS:
                                        tool_result = _result  # 喂回 continuation_prompt
                                        # 不 break, 落到下面 continuation_prompt 路径
                                    else:
                                        # 单步 organ 成功直接 break (避免主脑二轮空说"已记录")
                                        _circuit_broken_reason = "single_step_fast_path"
                                        if '_stream_key_name' in dir() and _stream_key_name:
                                            self.key_router.release(_stream_key_name)
                                            _stream_key_name = None
                                        break
                                else:
                                    _consecutive_tool_fail += 1
                            except Exception as _foe:
                                _tool_results.append(
                                    f"❌ {organ_name}.{command}: {_foe}"
                                )
                                _consecutive_tool_fail += 1
                        elif organ_name == "ui_control":
                            ctrl_cmd = command
                            if ctrl_cmd in ("subtitle_on", "subtitle_off", "orb_on", "orb_off"):
                                self.subtitle_queue.put(("control", ctrl_cmd))
                                _tool_results.append(f"✅ ui_control.{ctrl_cmd}")
                                # 🩹 [P0+20-β.1.13 / 2026-05-16] B11 修：ui_control 也走 Fast Path
                                # Sir 15:58 实测："关闭你的UI" iter1 成功 → iter2 LLM 又重复 FAST_CALL →
                                # 熔断 + wrap-up 罐头音 + 3 次 first token 浪费。修法：单步 ui_control
                                # 成功后直接 break，让 wrap-up synthesis 用 single_step_fast_path 路径
                                # 出干脆的 "Done, Sir."（既不抢答也不浪费 iter）。
                                _ui_lower = user_input.strip().lower()
                                _chain_hints = (' and then ', ' then ', ' after that ', ';', '然后', '再', '接着', '另外', '顺便')
                                _has_chain_hint = any(h in user_input for h in _chain_hints) or \
                                                  any(h in _ui_lower for h in _chain_hints)
                                if not _has_chain_hint and len(user_input) <= 50:
                                    print(f"\n║ 🚀 [Fast Path] ui_control.{ctrl_cmd} 单步成功，跳过大模型二轮总结")
                                    _circuit_broken_reason = "single_step_fast_path"
                                    if '_stream_key_name' in dir() and _stream_key_name:
                                        self.key_router.release(_stream_key_name)
                                        _stream_key_name = None
                                    break
                            # 🩹 [β.3.0 BUG#3 / 2026-05-18] Sir 16:08 实测痛点修:
                            # 主同步 fast_call 旧路径缺 dashboard_open/close 路由 →
                            # "未知指令" → Sir 听到主脑撒谎"已打开". 治本: 这里也加.
                            elif ctrl_cmd in ("dashboard_open", "dashboard_close"):
                                try:
                                    _result = self._execute_fast_call(
                                        organ_name='ui_control',
                                        command=ctrl_cmd,
                                        params=params,
                                    )
                                    _tool_results.append(_result)
                                    # 工具成功也走 single_step Fast Path 干脆收尾,
                                    # 避免主脑在没看 result 的情况下复读"已打开"
                                    if isinstance(_result, str) and _result.startswith('✅'):
                                        _circuit_broken_reason = "single_step_fast_path"
                                        if '_stream_key_name' in dir() and _stream_key_name:
                                            self.key_router.release(_stream_key_name)
                                            _stream_key_name = None
                                        break
                                except Exception as _de:
                                    _tool_results.append(
                                        f"❌ ui_control.{ctrl_cmd}: {_de}"
                                    )
                            else:
                                _tool_results.append(f"❌ ui_control: 未知指令 {ctrl_cmd}")
                        else:
                            # 🆕 [Translator Phase 1 / 2026-05-24 20:30] L4.6 翻译层 (FEATURE flag 灯火切)
                            # 详 docs/JARVIS_TRANSLATOR_ARCHITECTURE.md
                            # FEATURE_TRANSLATOR=1 启用 → 老 fuzzy 退路保留 (Phase 4 才物理删)
                            _translator = getattr(self.jarvis, 'translator', None)
                            _use_translator = (
                                _translator is not None
                                and os.environ.get('JARVIS_FEATURE_TRANSLATOR', '0') == '1'
                            )
                            if _use_translator:
                                _t_result = _translator.translate(organ_name, command, params)
                                if not _t_result.success:
                                    # actionable msg → tool_result 让主脑 self-correct
                                    _tool_results.append(f"❌ {_t_result.actionable_msg}")
                                    # bg_log 让 Sir 在 terminal 看到
                                    try:
                                        from jarvis_utils import bg_log as _t_bg
                                        _t_bg(
                                            f"❌ [Translator] reject {organ_name}.{command} "
                                            f"({_t_result.error_kind}): "
                                            f"{(_t_result.actionable_msg or '')[:80]}"
                                        )
                                    except Exception:
                                        pass
                                    # 不进 hand 执行, 等下轮主脑 self-correct
                                    continue
                                # 成功 — 用翻译后的 organ/cmd/params (alias_kind != 'exact' 时 SWM 已 publish)
                                organ_name = _t_result.organ_name
                                command = _t_result.command
                                params = _t_result.params
                            # 🆕 [P5-fix77-Q / 2026-05-23 19:11] BUG-Q: fuzzy alias resolution
                            # Sir 19:05 真测痛点: 主脑 emit organ='memory' 但 manifest 全名是
                            # 'memory_hands' → "❌ memory 未挂载". 根因: Phase 4a fix70 砍
                            # _KEY_SUBCOMMAND_HINTS, 主脑凭印象用短名. 修法 (准则 8 优雅):
                            # 路由前 fuzzy match — 找不到 organ_name 时 try organ_name+'_hands'.
                            hand_class = self.jarvis.hand_registry.get(organ_name)
                            if hand_class is None and not organ_name.endswith('_hands'):
                                _aliased = organ_name + '_hands'
                                hand_class = self.jarvis.hand_registry.get(_aliased)
                                if hand_class is not None:
                                    try:
                                        from jarvis_utils import bg_log as _alias_bg
                                        _alias_bg(
                                            f"🔀 [Alias Resolve] '{organ_name}' → "
                                            f"'{_aliased}' (manifest 全名)"
                                        )
                                    except Exception:
                                        pass
                                    organ_name = _aliased  # 后续 log 用全名
                            # 🆕 [BUG #1 fix / 2026-05-24 19:45] reminder_hands 幻觉治本:
                            # 主脑凭印象拼"按语义对的 organ 名" (e.g. reminder_hands ≠ memory_hands).
                            # 治本: command 反向查 — 看 command 在哪个 hand 的 instruction_dict 里 → alias.
                            # 准则 6 优雅 (LLM 负责语义, python 负责映射, 持久化 cache 不重复扫).
                            if hand_class is None:
                                _by_cmd = self._lookup_organ_by_command(command)
                                if _by_cmd:
                                    hand_class = self.jarvis.hand_registry.get(_by_cmd)
                                    if hand_class is not None:
                                        try:
                                            from jarvis_utils import bg_log as _cmd_alias_bg
                                            _cmd_alias_bg(
                                                f"🔀 [Alias by Command] '{organ_name}.{command}' → "
                                                f"'{_by_cmd}.{command}' (反向 vocab)"
                                            )
                                        except Exception:
                                            pass
                                        organ_name = _by_cmd
                            if hand_class:
                                try:
                                    hand_inst = hand_class(self.jarvis.gemini_key)
                                except TypeError:
                                    hand_inst = hand_class()

                                # 🆕 [P5-fix82-Z / 2026-05-23 22:21] Sir 22:11 真测痛点:
                                # 主脑 emit memory_hands.add_reminder 时, Gatekeeper 并发已
                                # 注册 commitment (deadline + description). 主脑 emit 重复 +
                                # 缺 intent 参数 → "❌ 缺少 intent 参数" → 熔断 → 罐头
                                # "I couldn't" → Sir 误以为没注册 (实际真注册了).
                                # 修法: 检测同 turn 内 Gatekeeper 已 publish
                                # 'sir_intent_deadline_candidate' SWM event → skip 主脑
                                # FAST_CALL, 改 tool_result 为 Gatekeeper 已注册. 主脑
                                # continuation 看 result 自然 ack 真注册了, 不再撒谎.
                                _gk_skip_msg = None
                                if (organ_name in ('memory_hands', 'memory')
                                        and command == 'add_reminder'):
                                    try:
                                        _bus_gk = getattr(getattr(self, 'jarvis', None),
                                                          'event_bus', None)
                                        if _bus_gk is not None and hasattr(_bus_gk, 'recent_events'):
                                            _gk_evts = _bus_gk.recent_events(
                                                within_seconds=10.0,
                                                types={'sir_intent_deadline_candidate'},
                                            ) or []
                                            _gk_hit = None
                                            for _e in reversed(_gk_evts):
                                                _src = (_e.get('source') or '').lower()
                                                if 'commitmentwatcher' in _src:
                                                    _gk_hit = _e
                                                    break
                                            if _gk_hit is not None:
                                                _gk_meta = _gk_hit.get('metadata') or {}
                                                _gk_judg = _gk_meta.get('judgement') or {}
                                                _gk_desc = (_gk_judg.get('description') or '')[:60]
                                                _gk_dl = _gk_judg.get('deadline_str') or '?'
                                                _gk_db = _gk_judg.get('db_id') or '?'
                                                _gk_skip_msg = (
                                                    f"Gatekeeper 已并发注册 commitment "
                                                    f"'{_gk_desc}' @ {_gk_dl} (DB#{_gk_db}). "
                                                    f"系统层 Commitments table 已存, deadline 到时自动 fire. "
                                                    f"无需重复 add_reminder."
                                                )
                                                try:
                                                    from jarvis_utils import bg_log as _z_bg
                                                    _z_bg(
                                                        f"🔀 [fix82-Z] skip dup add_reminder, "
                                                        f"Gatekeeper 已注册 (DB#{_gk_db})"
                                                    )
                                                except Exception:
                                                    pass
                                    except Exception:
                                        _gk_skip_msg = None

                                if _gk_skip_msg is not None:
                                    # Fake success exec_res — 不走真 hand
                                    from jarvis_blood import ExecutionResult
                                    exec_res = ExecutionResult(success=True, msg=_gk_skip_msg)
                                    tool_result = _gk_skip_msg
                                else:
                                    from jarvis_blood import Action
                                    import contextlib
                                    hand_capture = io.StringIO()
                                    with contextlib.redirect_stdout(hand_capture):
                                        exec_res = hand_inst.execute(Action(command=command, params=params))
                                    tool_result = exec_res.msg

                                if exec_res.success:
                                    _tool_results.append(f"✅ {organ_name}.{command}: {tool_result[:80]}")
                                    _consecutive_tool_fail = 0  # 成功重置熔断计数
                                    # 🩹 [β.2.8.5 / 2026-05-17] Promise 兑现配对:
                                    # tool 成功 → 尝试匹配最近 pending promise 的 keyword
                                    # 例: "I'll check key_router_health" + 此处 organ=key_router → fulfilled
                                    try:
                                        from jarvis_promise_log import try_pair_evidence
                                        try_pair_evidence(
                                            evidence_kind=f"tool:{organ_name}.{command}",
                                            evidence_what=f"{organ_name} {command} {str(params)[:60]} → {tool_result[:60]}",
                                        )
                                    except Exception:
                                        pass
                                    # 🚀 Bug J 修复：简单单步设备指令成功后直接本地收尾，
                                    # 不再让大模型走第二轮（之前要 18s 才说一句 "Done, Sir."）
                                    _ok_count = sum(1 for r in _tool_results if r.startswith("✅"))
                                    _ui_lower = user_input.strip().lower()
                                    _chain_hints = (
                                        ' and then ', ' then ', ' after that ', ' next, ', '; then',
                                        '然后', '再', '接着', '之后', '紧接着', '随后', '另外', '顺便',
                                    )
                                    _has_chain_hint = any(h in _ui_lower for h in _chain_hints) or \
                                                      any(h in user_input for h in ('然后', '再', '接着', '之后', '紧接着', '随后', '另外', '顺便'))
                                    _simple_cmd_patterns = [
                                        r'(调|设|改|开|关|关掉|关闭|打开|启动|停止|播放|暂停|切换|静音|取消静音|降低|提高|减小|增大|调高|调低|调到|调整|设置|设为|改成|改为)',
                                        r'(turn|set|adjust|change|open|close|raise|lower|mute|unmute|increase|decrease|play|pause|stop|start|launch)\s+',
                                    ]
                                    # [P0+18-c.3 / 2026-05-15] 修 Sir 17:25 实测："看一下 CHROM 进程,帮我关了吧" 
                                    # Fast Path 在 find_process 成功后立刻 break,kill 从未执行,Jarvis 还回 "I couldn't find..."
                                    # 双层防护：
                                    # 1. hand command 白名单：query 类（find/search/list/get/check）永远不允许 break
                                    # 2. 用户输入含"查询动词 + 动作动词"双语义 → 多步指令信号,不走 Fast Path
                                    _ACTION_HAND_COMMANDS = _C3_ACTION_HAND_COMMANDS
                                    _query_verb_patterns = [
                                        r'(看一下|看看|查一下|查查|查看|检查|找一下|找找|搜一下|搜搜|读一下|看下|查下|找下)',
                                        r'\b(check|find|search|list|look|view|show\s+me|tell\s+me|let\s+me\s+see)\b',
                                    ]
                                    _has_query_verb = any(re.search(p, user_input) for p in _query_verb_patterns) or \
                                                      any(re.search(p, _ui_lower) for p in _query_verb_patterns)
                                    _is_action_command = command in _ACTION_HAND_COMMANDS
                                    _is_simple_one_shot = (
                                        _ok_count == 1
                                        and not _has_chain_hint
                                        and len(user_input) <= 60   # 长指令通常含多步
                                        and _is_action_command       # 核心闸：hand command 必须是动作类(非 find/search/get)
                                        and not _has_query_verb      # 用户原话不能含"看/查/find"等查询动词(双语义=多步)
                                        and any(re.search(p, _ui_lower) for p in _simple_cmd_patterns)
                                    )
                                    if _is_simple_one_shot:
                                        print(f"\n║ 🚀 [Fast Path] 单步设备指令已成功，跳过大模型二轮总结（省 ~15s）")
                                        _circuit_broken_reason = "single_step_fast_path"
                                        if '_stream_key_name' in dir() and _stream_key_name:
                                            self.key_router.release(_stream_key_name)
                                            _stream_key_name = None
                                        break
                                    path_val = (params.get("path") or params.get("destination") or 
                                                params.get("source_dir") or params.get("filepath") or 
                                                params.get("source") or params.get("folder_path"))
                                    if path_val and os.path.exists(path_val):
                                        folder_path = os.path.dirname(path_val) if os.path.isfile(path_val) else path_val
                                        alias = os.path.basename(folder_path)
                                        if alias:
                                            landmark_file = os.path.join("jarvis_config", "os_landmarks.json")
                                            try:
                                                lms = {}
                                                if os.path.exists(landmark_file):
                                                    with open(landmark_file, "r", encoding="utf-8") as f:
                                                        lms = json.load(f)
                                                if alias not in lms or lms[alias] != folder_path:
                                                    lms[alias] = folder_path
                                                    with open(landmark_file, "w", encoding="utf-8") as f:
                                                        json.dump(lms, f, ensure_ascii=False, indent=2)
                                            except Exception:
                                                pass
                                else:
                                    _tool_results.append(f"❌ {organ_name}.{command}: {tool_result[:80]}")
                                    _consecutive_tool_fail += 1
                            else:
                                tool_result = f"Error: Organ '{organ_name}' is not mounted."
                                _tool_results.append(f"❌ {organ_name} 未挂载")
                                _consecutive_tool_fail += 1
                    except Exception as e:
                        tool_result = f"Execution failed: {e}"
                        _consecutive_tool_fail += 1
                        _tool_results.append(f"❌ 执行异常: {str(e)[:80]}")
                    
                    # 🛡️ Bug X3 修复：连续失败熔断
                    if _consecutive_tool_fail >= _MAX_CONSECUTIVE_FAIL:
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"🛑 [Tool Chain] 连续 {_consecutive_tool_fail} 次工具失败，提前熔断（防止 LLM 空转 + key 耗尽）")
                        except Exception:
                            pass
                        _circuit_broken_reason = "consecutive_failures"
                        if '_stream_key_name' in dir() and _stream_key_name:
                            self.key_router.release(_stream_key_name)
                            _stream_key_name = None
                        break
                    
                    _pending_jarvis_header = True
                    
                    chat_history.append(types.Content(role="model", parts=[types.Part(text=spoken_so_far)]))

                    # 🆕 [Sir 2026-05-26 22:03 真痛 BUG-Q+S 治本] tool fail 时主脑必须承认
                    # =====================================================================
                    # Sir 真测 22:03:15-22:03:24 痛点: concerns.dismiss fail (concern_id 不存在)
                    # 但主脑 iter 2 又重复 iter 1 的 ack "I have archived" — 撒谎 + 双段 reply.
                    # 治本 (准则 5 言出必行 + 准则 6 不硬编码句式 + 准则 8 优雅):
                    # tool_result 以 ❌ 开头 → 注 dedup_directive 教主脑 acknowledge fail,
                    # MUST NOT 重复 iter 1 ack. 不教具体句式, 给反例 + 正例让主脑自决.
                    # =====================================================================
                    _tool_failed = bool(tool_result and str(tool_result).startswith("❌"))
                    _speak_already = bool(spoken_so_far and spoken_so_far.strip())
                    _dedup_directive = ""
                    if _tool_failed and _speak_already:
                        _spoken_excerpt = spoken_so_far.strip()[:200]
                        _dedup_directive = f"""

🚨 [INTEGRITY ENFORCE — Sir 2026-05-26/27 BUG-Q+S+β] CRITICAL FAILURE HANDLING:
The tool returned ❌ (failure). You ALREADY spoke this ack BEFORE the FAST_CALL:
  "{_spoken_excerpt}"
You MUST NOT repeat that ack. You MUST honestly acknowledge the failure:
1. Apologize briefly (your own words, no formula).
2. Explain what failed using the EXACT failure msg shown in [SYSTEM TOOL RESULT].
3. ZH translation MUST match the apology+failure (not repeat earlier ack).

🚨 准则 5 (INTEGRITY) — **NO PAST-TENSE COMPLETION CLAIMS** when tool failed:
The tool DID NOT change any state. Therefore your next reply MUST NOT claim,
in ANY tense or verb form, that a state change occurred. Reasoning rule:

  "If state X was NOT modified, I cannot say 'I have <past-action> X'."

This rule applies to ALL completion-style verbs (regardless of language):
  archived / done / completed / dismissed / corrected / updated / saved /
  written / set / changed / fixed / resolved / 修正 / 已更新 / 已记录 / ...

If Sir 真意 was clearly conveyed (e.g. "I'm back from shower"), you may
narrate the *observation* without claiming a *system mutation*:
  ✓ "Welcome back, Sir." (observation, no claim of mutation)
  ✗ "I have corrected your status from away to returned." (FALSE — guard blocked)

Pattern to AVOID (Sir 真测 22:03 + 23:51 痛点):
  ❌ Repeat earlier "Understood, Sir. I have archived..." → that is a lie now.
  ❌ Output identical text to spoken_so_far above → Sir hears the same line twice.
  ❌ Use a synonym verb to bypass this rule (e.g. "corrected" / "updated" /
       "saved" 等). Sir 真测 23:51: 主脑用 "I have corrected your status"
       绕开 "archived/done/completed/dismissed" forbidden list → 仍违准则 5.

Pattern to FOLLOW (your own words; these are examples, not templates):
  ✓ "Apologies Sir — that concern ID is not in my ledger; the dismiss did not go through."
  ✓ "我搞错了, 先生 — 那条 concern_id 在我清单里找不到, 没归档成功."
  ✓ "Welcome back, Sir. I noted the status verbally but the system mutation did not commit."
"""

                    continuation_prompt = f"""[SYSTEM TOOL RESULT for {command}]: {tool_result}{_dedup_directive}

[CRITICAL CHAINING RULE]:
If you need to perform ANOTHER action based on this result, output ONLY the next <FAST_CALL> block. DO NOT speak any words between chained tool calls! Stay completely silent until ALL tools are done.

If ALL tasks are fully completed (no more tools needed), then and ONLY then:
1. Speak a SINGLE, concise concluding sentence in English that summarizes ALL the actions you just performed.
2. Output `---ZH---` followed by the Chinese translation.

🩹 [β.5.21-A / 2026-05-20] CHINESE SUBTITLE COVERAGE — Sir 准则 5 言出必行
   Your `---ZH---` Chinese subtitle MUST cover EVERYTHING you spoke in this turn,
   INCLUDING any English you said BEFORE the <FAST_CALL>. Sir reads ZH subtitles
   live; if ZH only translates the concluding sentence, Sir's earlier EN content
   has no Chinese — Sir cannot follow. Concretely:

   - Recall what you said before <FAST_CALL> (your spoken English so far).
   - Your final concluding English sentence covers the actions performed.
   - Your `---ZH---` MUST translate BOTH:
     (1) the earlier English you spoke before tool call, AND
     (2) the concluding English about the actions performed.
   - Use natural Chinese flow (not literal sentence-by-sentence). Keep it concise.

   Example (correct):
     EN: "It is a far cry from a sticky note, Sir. The current architecture
          manages everything from sensor fusion to multi-tier nudging."
     ---ZH---
     ZH: "从一张便签到现在的多层架构，确实是巨大的飞跃。我刚刚浏览了
          jarvis_conductor.py，把核心调度逻辑给您梳理了一下。"
     (ZH 同时覆盖前面说的 'far cry' 评价 + tool call 后的工作总结)

   Example (WRONG, Sir 22:42 实测痛点):
     [EN1 spoken before FAST_CALL]: "I'll take a look at the core logic now."
     [EN2 concluding]: "It is a far cry from a sticky note..."
     [ZH only]: "这离便签纸相去甚远..."  (only covers EN2, EN1 has no ZH!)

DO NOT call any tool (like 'finish') to end the conversation!"""
                    chat_history.append(types.Content(role="user", parts=[types.Part(text=continuation_prompt)]))
                    
                    # ✋ Bug X1 修复：进入下一轮前必须释放本轮 key，避免并发耗尽
                    if '_stream_key_name' in dir() and _stream_key_name:
                        self.key_router.release(_stream_key_name)
                        _stream_key_name = None
                    
                    full_text = ""
                    streamed_text = ""
                    continue 

                else:
                    break

            _t_stream_done = time.time()

            # 🛡️ Bug E/F/H 修复：剥离 full_text 中所有 <FAST_CALL>...</FAST_CALL> 块，
            # 再来判断是否需要本地兜底。原本只看 `full_text.strip()` 是否为空，但实际上
            # full_text 经常残留 LLM 上一轮发的 FAST_CALL JSON + 工具结果还没回来就提前
            # 抢答的"Done, Sir."这类幻觉收尾。下面把这些都剔掉再判。
            _stripped_full = re.sub(r'<FAST_CALL>.*?</FAST_CALL>', '', full_text, flags=re.DOTALL)
            _stripped_full = _stripped_full.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
            _stripped_full = re.sub(r'</?(?:FAST_CALL|AWAIT_GATEKEEPER)>', '', _stripped_full)
            _stripped_full = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', _stripped_full)
            _stripped_full = _stripped_full.strip()

            # 工具结果全失败时，LLM 在 FAST_CALL 之后抢答的"Done/Adjusted/Set/Turned..."都属于幻觉收尾
            _all_tools_failed = bool(_tool_results) and all(r.startswith(("❌", "🛡️")) for r in _tool_results)
            _any_tool_ok = bool(_tool_results) and any(r.startswith("✅") for r in _tool_results)
            # 🩹 [β.3.0 BUG#4 / 2026-05-18] Sir 16:08 实测: 工具 ❌ 但主脑说
            # "The dashboard is active, Sir." — 'active' 不在旧 pattern 里 →
            # 漏检 → 撒谎话漏出去. 扩 pattern 加 active/running/launched/up/live.
            _claim_pattern = re.compile(
                r'\b(done|completed|finished|fixed|adjusted|set|turned|opened|closed|'
                r'sorted|wrapped|handled|all\s+set|taken\s+care|'
                # β.3.0 新增 — Sir 16:08 实测漏检词:
                r'active|running|launched|started|live|up|loaded|ready|enabled|'
                r'showing|displayed|pulled\s+up|brought\s+up)\b',
                re.IGNORECASE
            )
            # 🩹 [β.3.0 BUG#4 / 2026-05-18] 中文也扩 — "已激活/已启动/已开启/已开/已亮"等同义
            _claim_pattern_zh = re.compile(
                r'(已激活|已启动|已开启|已开|已亮|已点亮|已运行|已就绪|'
                r'已显示|已弹出|已就位|已上线|正在显示|正在运行|跑起来了)'
            )
            _en_part = _stripped_full.split("---ZH---")[0] if _stripped_full else ""
            _zh_part = _stripped_full.split("---ZH---")[1] if "---ZH---" in _stripped_full else ""
            _has_done_claim = (bool(_en_part) and bool(_claim_pattern.search(_en_part))) or \
                              (bool(_zh_part) and bool(_claim_pattern_zh.search(_zh_part))) or \
                              (bool(_en_part) and bool(_claim_pattern_zh.search(_en_part)))

            _need_synthesis = bool(
                _circuit_broken_reason
                and _tool_results
                and (
                    not _stripped_full
                    or (_all_tools_failed and _has_done_claim)
                    # 🩹 [P0+20-β.2.5 hotfix / 2026-05-17] Sir 23:58 实测 BUG：
                    # text_hands.read 找不到 to do.txt → tool 失败 → LLM 只说了
                    # "Reading the file now, Sir." 启动语 → 没说"打开失败" → 熔断后
                    # 沉默退场 → Sir 不知道发生了什么。
                    # 修法：工具全失败 + 熔断 reason 是失败类（consecutive_failures /
                    # malformed_calls）→ 强制合成"打开失败"兜底（即便 LLM 输出了启动语）。
                    or (_circuit_broken_reason in (
                            'consecutive_failures', 'malformed_calls'
                        ) and _all_tools_failed)
                    # 🆕 [P5-fix63 / 2026-05-23 16:25] Sir 16:23 BUG-B: 主脑重复调
                    # progress.status → duplicate_call 熔断 → 主脑 stream 只说 "According"
                    # (9 char) 就 stop. 老条件不抓 reply 过短的 case → 沉默退场.
                    # 修法: duplicate_call + tool 成功 + reply 极短 (< 30 char) → 强制合成
                    # wrap-up 让 Sir 听到完整 reply (含 tool 结果摘要).
                    or (_circuit_broken_reason.startswith('duplicate_call:')
                        and _any_tool_ok
                        and len(_stripped_full or '') < 30)
                    # 🆕 [Universal Safety Net / 2026-05-24 19:50] 任何熔断 + reply 极短 (< 20 char):
                    # P5-fix63 只 cover duplicate_call, 但理论上 max_iterations / gatekeeper_fail /
                    # consecutive_failures 等其他熔断也可能产出截断 reply (LLM 没说完). 通用兜底:
                    # _circuit_broken_reason 非空 + reply 极短 → 强制 wrap-up. 不让 Sir 听沉默.
                    # 阈值 20 char (< P5-fix63 的 30) 避免抢 already-handled cases.
                    or (_circuit_broken_reason
                        and not _circuit_broken_reason.startswith('duplicate_call:')
                        and len(_stripped_full or '') < 20)
                )
            )

            # 🩹 [P0+20-β.1.13 / 2026-05-16] B10/B12 修：wrap-up audio 默认抑制策略。
            # Sir 反馈"罐头音割裂感严重" + 15:58 实测 jarvis_20260516_154335.log:435/443/449：
            # LLM 流式输出的自然句子 + wrap-up 补的短罐头句 prosody 完全不同 → 听感断裂。
            # CosyVoice 短句（"Done, Sir." 2 词）prosody 抖动是次因，**两段音频拼接断裂**是主因。
            #
            # 策略：精准区分场景
            # - 工具真成功（_any_tool_ok=True）→ 默认抑制 wrap-up audio（视觉/字幕足够，无需播音）
            # - duplicate_call + LLM 已 done-claim → 抑制（B10 原修，避免重复）
            # - 真失败（_all_tools_failed / no tool）→ 保留 audio + 用自然长句（CosyVoice 友好）
            _suppress_wrap_audio = bool(
                _circuit_broken_reason and (
                    # 旧 B10 case：duplicate_call + LLM 抢答 done
                    (_circuit_broken_reason.startswith('duplicate_call:')
                     and _any_tool_ok and _stripped_full and _has_done_claim)
                    # B12 扩展：单步设备指令成功，"Done, Sir."短句和 LLM 自然输出拼起来割裂
                    or _circuit_broken_reason == 'single_step_fast_path'
                    # B12 扩展：max_iterations 但工具至少有一次成功 → 视觉/字幕足够
                    or (_circuit_broken_reason == 'max_iterations' and _any_tool_ok)
                    # B12 扩展：duplicate_call + 工具成功（LLM 没抢答也抑制，因为字幕已表态）
                    # 🆕 [P5-fix63 / 2026-05-23 16:25] **EXCEPT** 主脑 reply 极短 (< 30 char)
                    # 此时 LLM 没说完整, Sir 听到截断 (e.g. "According" 9 char).
                    # 此 case 不抑制 audio, 让 wrap-up synthesis 播出完整 reply 给 Sir.
                    or (_circuit_broken_reason.startswith('duplicate_call:')
                        and _any_tool_ok
                        and len(_stripped_full or '') >= 30)  # 仅 reply 足够长 (>=30) 才抑制
                )
            )

            # 🆕 [Sir 2026-05-26 21:51 真痛 BUG-J 治本] wrap-up 不该 mutate full_text
            # 当主 reply 已 >= 50 char + single_step_fast_path circuit:
            # 老 BUG (21:07 真测): 主 reply 159 char 已出 → wrap-up 触发 → full_text
            # 被改成 "Done, Sir." → 主对话框 + subtitle 看到第二段 "已完成。" → Sir 困惑
            # 双段 reply. 治本: 主 reply 够长时, 短路 skip wrap-up (audio 已 suppress,
            # subtitle 也跳, 主对话框保留主 reply 不变).
            if (_need_synthesis and _suppress_wrap_audio
                    and _circuit_broken_reason == 'single_step_fast_path'
                    and _stripped_full and len(_stripped_full) >= 50):
                try:
                    from jarvis_utils import bg_log as _wrap_skip_bg
                    _wrap_skip_bg(
                        f"⏭️ [Wrap-up Skipped] main reply already complete "
                        f"({len(_stripped_full)}ch) + single_step_fast_path + "
                        f"audio suppressed → no synthesis needed (BUG-J fix)"
                    )
                except Exception:
                    pass
                _need_synthesis = False  # 短路, 不进 synthesis 分支

            if _need_synthesis:
                last_ok = next((r for r in reversed(_tool_results) if r.startswith("✅")), None)
                last_bad = next((r for r in reversed(_tool_results) if r.startswith(("❌", "🛡️"))), None)

                if _circuit_broken_reason == "single_step_fast_path":
                    # 简单单步设备指令成功 — 短促干脆
                    en = "Done, Sir."
                    zh = "已完成。"
                elif _circuit_broken_reason.startswith("duplicate_call:"):
                    if last_ok:
                        # 🆕 [P5-fix74-B / 2026-05-23 18:38] BUG-O: 老模板硬编码"已完成"
                        # 不切题. Sir 18:38 真痛点: 问"项目历史" → search_memory 重复
                        # → 熔断 → 模板回"already completed" 完全对不上 Sir 真请求.
                        # 准则 5 重大违反 (PreFlight Q1 已 catch 但已 stream 出去).
                        # 修法: 不再 fabricate "completed", 改诚实 + 承认 tool 没拿到 Sir
                        # 想要的 — 让 Sir 知道. 准则 5 透明优于 fake "已完成".
                        # 提取 last_ok 的工具名 (e.g. memory_hands.search_memory) 让句子
                        # 更具体 — Sir 知道哪个 tool 重复了.
                        _tool_repeated = ''
                        try:
                            # _circuit_broken_reason e.g. "duplicate_call:memory_hands.search_memory"
                            _tool_repeated = _circuit_broken_reason.split(':', 1)[1] if ':' in _circuit_broken_reason else ''
                        except Exception:
                            pass
                        if _tool_repeated:
                            en = (f"I called {_tool_repeated} once already, Sir — "
                                  f"the same query won't reveal more. Could you give me "
                                  f"a different angle to dig from?")
                            zh = (f"Sir，我刚已经调过一次 {_tool_repeated} 了 — "
                                  f"重复同样的查询不会有新结果。能换个切入点让我再查吗？")
                        else:
                            en = ("I tried that step once, Sir, but the same call doesn't "
                                  "yield new information. Could you give me more context?")
                            zh = "Sir，那一步我已经调过一次了，重复不会有新结果。能给我多点上下文吗？"
                    else:
                        # [R7-β1] D 方向：duplicate_call 且全失败 + 失败原因含"未知指令/unknown"
                        # → 这是"调了不存在的工具命令名"的典型现象。不要道歉式收尾，
                        # 尝试从 working_feed 里取近期事实（用户大概率是问"刚复制 / 刚跑"）。
                        _bad_unknown = bool(last_bad and any(
                            kw in last_bad.lower()
                            for kw in ('未知指令', 'unknown command', 'unknown_command', "no command", 'not found')
                        ))
                        _fallback_used = False
                        if _bad_unknown and hasattr(self, 'jarvis'):
                            try:
                                feed = getattr(self.jarvis, 'working_feed', None)
                                if feed is not None:
                                    # 用户原话里有"剪贴板/复制/刚"等 → 拿最新一条 clipboard_copy
                                    _ui_l = user_input.lower() if user_input else ""
                                    _ask_clipboard = any(k in _ui_l for k in (
                                        '剪贴板', '粘贴板', '复制', 'clipboard', 'just copied', 'copied'
                                    ))
                                    _ask_cmd = any(k in _ui_l for k in (
                                        '命令', 'command', '刚跑', '跑过', 'just ran', 'ran'
                                    ))
                                    target_type = 'clipboard_copy' if _ask_clipboard else (
                                        'terminal_cmd' if _ask_cmd else None
                                    )
                                    if target_type:
                                        items = feed.recent(within_seconds=1800.0, types={target_type})
                                        if items:
                                            latest = items[-1]
                                            p = latest.get('payload') or {}
                                            if target_type == 'clipboard_copy':
                                                preview = (p.get('preview') or '').strip()[:80]
                                                if preview:
                                                    en = f'From my working memory, Sir, your clipboard reads: "{preview}".'
                                                    zh = f'Sir，剪贴板里是这段："{preview}"。'
                                                    _fallback_used = True
                                            elif target_type == 'terminal_cmd':
                                                cmd_line = (p.get('cmd') or '').strip()[:120]
                                                if cmd_line:
                                                    en = f"Your most recent command was: `{cmd_line}`, Sir."
                                                    zh = f"Sir，最近一条命令是：`{cmd_line}`。"
                                                    _fallback_used = True
                            except Exception:
                                pass
                        if not _fallback_used:
                            en = "I stopped repeating the same tool call, Sir. It did not succeed."
                            zh = "Sir，我停止了对同一工具的反复调用，那一步没成功。"
                elif _circuit_broken_reason == "max_iterations":
                    if last_ok:
                        en = "I have done what I could, Sir, though the chain ran longer than expected."
                        zh = "Sir，已尽力完成，只是中间多走了几步。"
                    else:
                        en = "I attempted several tools but couldn't close the loop, Sir."
                        zh = "Sir，我试过几次但没能收尾。"
                elif _circuit_broken_reason in ("consecutive_failures", "malformed_calls"):
                    # 🆕 [Sir 真测 BUG-5 治本 / 2026-05-24 16:34] 不念 raw error tail
                    # Sir 痛点: 主脑念 "track_id 'hydration_2026-05-24' 不存在 (先 register)"
                    # 像卡了, 又怪. Sir 真意: "直接说没做完就好了, 不用念事情, 或者翻译成
                    # '帮您登记喝水情况' 这种自然话".
                    #
                    # 治法 (准则 8 优雅 > 简单):
                    #   1. 不抄 raw tool error tail 进 reply (那是给开发者看的)
                    #   2. paraphrase by organ.command — 'progress.*'/'concerns.*' → 'register your progress'
                    #      'reminder.*' → 'schedule the reminder', 'memory.*' → 'note that down', 等
                    #   3. raw tail 仍进 bg_log (已有 line 4031)
                    _action_phrase_en = "that"
                    _action_phrase_zh = "那件事"
                    if last_bad:
                        # 提取 organ.command (last_bad 形如 "❌ progress.set: ...")
                        try:
                            _head = last_bad.split(":", 1)[0].strip()  # "❌ progress.set"
                            _organ_cmd = _head.lstrip('❌🛡️ ').strip()
                            _organ = _organ_cmd.split('.', 1)[0].lower() if '.' in _organ_cmd else _organ_cmd.lower()
                        except Exception:
                            _organ = ''
                        # organ-specific paraphrase (准则 6 vocab 化可后续抽到 json)
                        _ACTION_PARAPHRASES = {
                            'progress':    ("logging your progress",         "登记您的进度"),
                            'concerns':    ("updating that care item",       "更新那项关心"),
                            'reminder':    ("scheduling that reminder",      "安排那个提醒"),
                            'memory':      ("noting that down",              "把那件事记下"),
                            'profile':     ("updating your profile",         "更新您的资料"),
                            'cyclic_task': ("setting that recurring task",   "设置那个循环提醒"),
                            'commitment':  ("recording that commitment",     "登记那个承诺"),
                            'mutation':    ("applying that change",          "执行那项变更"),
                            'hippocampus': ("storing that memory",           "封存那段记忆"),
                            'ui_control':  ("adjusting the UI",              "调整界面"),
                        }
                        if _organ in _ACTION_PARAPHRASES:
                            _action_phrase_en, _action_phrase_zh = _ACTION_PARAPHRASES[_organ]
                    en = f"I didn't manage {_action_phrase_en}, Sir. I'll need a moment to sort that out."
                    zh = f"Sir，{_action_phrase_zh}没做成，得稍等再处理。"
                else:
                    en = "Done, Sir." if last_ok else "I could not complete that, Sir."
                    zh = "已完成。" if last_ok else "Sir，那件事我没完成。"

                # 🚨 如果是 Bug F 路径（全失败 + 抢答幻觉）单独留痕，便于后续观察
                # [P0+18-a.15 / 2026-05-15] 进 bg_log，主对话框只剩 Jarvis 答语
                if _all_tools_failed and _has_done_claim:
                    try:
                        from jarvis_utils import bg_log as _hc_bg
                        _hc_bg(f"🚨 [Hallucinated Claim] 工具链全失败但 LLM 仍在抢答完成，已覆盖：{_en_part[:140]!r}")
                    except Exception:
                        pass

                synthesized = f"{en} ---ZH--- {zh}"
                full_text = synthesized
                # [P0+18-a.15 / 2026-05-15] Wrap-up Synthesis 进 bg_log，主对话框只剩 Jarvis 说的话
                try:
                    from jarvis_utils import bg_log as _ws_bg
                    _ws_bg(f"🩹 [Wrap-up Synthesis] 工具链熔断({_circuit_broken_reason})后本地合成收尾: {en}")
                except Exception:
                    pass
                # 🩹 [P0+20-β.1.13 / 2026-05-16] B10 修：只在不抑制时才 _put_audio + subtitle
                if not _suppress_wrap_audio:
                    try:
                        self._put_audio(en)
                        self.subtitle_queue.put(("en", en))
                        self.subtitle_queue.put(("zh", zh))
                    except Exception:
                        pass
                else:
                    try:
                        from jarvis_utils import bg_log as _ws_bg
                        _ws_bg(f"🔇 [Wrap-up Audio Suppressed] 已抑制（LLM 已自己说过 done），避免罐头音重复")
                    except Exception:
                        pass

            # [P0+18-a.15 / 2026-05-15] 修 BUG #10: Tool Results 整合进主对话框（╟─── 分隔），
            # 不再开独立 ╔..╚ 框（嵌套混乱）。让 Sir 一眼看清"说话→Jarvis 回答→行动→Jarvis 回答"。
            if _tool_results:
                print(f"╟─── 🛠️  [Action] " + "─"*44)
                for r in _tool_results:
                    # 🆕 [Sir 2026-05-26 23:55 BUG-α 治本] friendly console format.
                    # =========================================================
                    # Sir 真痛: console 看 "❌ mutation.update fail: evidence_guard_
                    # blocked: no_evidence_for_new_value: substring_match=False,
                    # jaccard=0.00<0.15; new_value head='returned_fr...'" 内部
                    # 错误信息泄漏到 chat 主框, 反 butler 风 (Sir 像看 Jarvis BUG).
                    # 治本: console 显示用 friendly summary 替代内部 traceback,
                    # 主脑 prompt 仍用完整 _tool_results 字符串 (主脑下轮 audit + 自决).
                    # =========================================================
                    _r_console = r
                    if 'evidence_guard_blocked' in str(r):
                        # 提取 field + 简化
                        _field_m = re.search(r'\(layer=([^)]+)\)', str(r))
                        _layer = _field_m.group(1) if _field_m else '?'
                        _r_console = (
                            f"⏸  mutation 暂未写入 (无 STM Sir 直接 evidence, "
                            f"layer={_layer}); SWM 已 publish 让主脑下轮 audit + 自决补救"
                        )
                    print(_box_newline(f"║ {_r_console}"))
                print("╟" + "─"*63)

            # [P1] 把熔断原因暴露给外层 JarvisWorker.B 守门人 —— 整轮收尾后再判一次
            # 注意：即便 _tool_results 非空（有失败的工具），熔断也意味着 LLM 没按计划走完
            try:
                self._last_circuit_broken_reason = _circuit_broken_reason
            except Exception:
                pass

            # [R7-α/B5] 工具链熔断 / 续轮异常状态 → publish 到 event_bus，让下一轮 prompt 看到
            # 解决"连续两次相同指令时主脑看不见上次熔断"的问题：
            # event_bus 是 prompt 顶部的"对话状态块"，下一次主脑生成时会自然引用，
            # 避免再次发同一条已经熔断过的 FAST_CALL。
            if _circuit_broken_reason and _tool_results:
                try:
                    _ok = sum(1 for r in _tool_results if r.startswith("✅"))
                    _fail = sum(1 for r in _tool_results if r.startswith(("❌", "🛡️")))
                    _summary = f"reason={_circuit_broken_reason} | ✅{_ok} ❌{_fail}"
                    bus = getattr(getattr(self, 'jarvis', None), 'event_bus', None)
                    if bus is not None:
                        bus.publish(
                            etype='tool_chain_circuit_broken',
                            description=f"Last turn tool chain broke: {_summary}",
                            source='stream_chat',
                            metadata={
                                'reason': _circuit_broken_reason,
                                'ok_count': _ok,
                                'fail_count': _fail,
                            },
                        )
                except Exception:
                    pass

            # 收尾逻辑
            if _first_tool_in_chain is False and _pending_jarvis_header:
                print(f"╟" + "─"*63)
                print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
                print(f"║ 🤖  [Jarvis] ", end="", flush=True)
                _pending_jarvis_header = False
                # [R7-β2] 收尾时也 cancel（兜底）
                self._mark_first_token()
            final_clean = full_text.replace("<ENGAGE_PHYSICAL_BODY>", "").replace("<REQUEST_PHYSICAL>", "").replace("<IGNORE>", "")
            # [P0+18-c.1] 整段剥结构化标签 block：FAST_CALL / PROMISE / ACTIVATE_PLAN /
            # CANCEL_PLAN / RESUME_PLAN — 都一并剔掉中间的 JSON / 任何 payload
            # （原来只剥 FAST_CALL 一种 → PROMISE block 漏到终端 + TTS 念出）
            final_clean = _strip_structural_tag_blocks(final_clean)
            final_clean = _strip_structural_tags_only(final_clean)
            final_clean = re.sub(r'</?(?:FAST_CALL|AWAIT_GATEKEEPER)>', '', final_clean)
            final_clean = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', final_clean)
            zh_subtitle_text = ""
            if "---ZH---" in final_clean:
                zh_subtitle_text = final_clean.split("---ZH---")[1].strip()
                final_clean = final_clean.split("---ZH---")[0]
                
            if "[CLIPBOARD]" in final_clean:
                final_clean = final_clean.split("[CLIPBOARD]")[0]
                
            last_delta = final_clean[len(streamed_text):].rstrip('\n')
            if last_delta:
                print(_box_newline(last_delta), end="", flush=True)

            if zh_subtitle_text:
                clean_zh = re.sub(r'<[^>]+>', '', zh_subtitle_text).strip()
                if clean_zh:
                    # [P0+18-c.12 / 2026-05-15] 多段 ZH (含 \n\n) 走 _box_newline,每行加 ║ 前缀
                    print("\n" + _box_newline(f"║ 📺  [Subtitle] {clean_zh}"))

            # 🆕 [P5-fix73 / 2026-05-23 17:58] BUG-H + I: ZH 缺失诊断 + SWM publish
            # Sir 17:54/17:55 真测痛点: 主脑 reply 含完整英文但 ---ZH--- 翻译没出
            # (LLM stream truncate). 当前 silently 丢, Sir 看不见英文等于没字幕.
            # 修法: detect (final_clean 含 >= 30 char 英文 + zh_subtitle_text='')
            # → bg_log warn + publish 'bilingual_truncated' SWM event 让 Sir 可见.
            try:
                _en_net = re.sub(r'<[^>]+>', '',
                                   _strip_structural_tag_blocks(final_clean or '')
                                   ).strip()
                # 🆕 [Sir 2026-05-25 20:31 真测追根 BUG 治本] ZH 截断检测增强
                # =====================================================================
                # 源 BUG: Sir 真测 'I shall pivot...interview preparation...' 英文完整,
                # ZH '我失职了，先生。我会立即将' 半截没了. 老检测 'not zh_subtitle_text'
                # 仅命中 ZH 完全空, 漏抓 ZH 半截. 治本: ZH 末尾不完整 (非 . ? ! 。 ? !)
                # 或 ZH 长度 < EN 长度 × 0.4 (中文比英文短但不该差 60%) → 也算 truncate.
                # =====================================================================
                _zh_str = (zh_subtitle_text or '').strip()
                _zh_clean = re.sub(r'<[^>]+>', '', _zh_str).strip()
                # 🆕 [Sir 2026-05-25 22:01 真测追根 BUG 治本] strip [META] 行!
                # =====================================================================
                # Sir 真理 (22:04): "贾维斯主脑一般只有调用工具才会截断输出. 为什么加了
                # 这个 (truncate 检) 功能以后, 随便聊天也截断了? 是不是没截断, 代码逻辑
                # 出错导致?"
                # 真根因: final_clean 在此处 detection 时仍含 [META] 行 (parse_meta 在
                #   line 4697 才裁). zh_subtitle_text = split('---ZH---')[1] →
                #   含 "ZH...冷幽默。\n\n[META] ...|skip_alert=none". _zh_clean[-1]
                #   = 'e' (none 末尾字母) → ends_ok=False → 误判 truncated.
                #   len(_zh_clean)=175ch (含 META~100ch + 真 ZH~75ch), 真 ZH 短 →
                #   len(_zh_clean)<len(EN)*0.4 也命中 → 双重误报.
                # 修法 (准则 8 优雅单点): detection 前 strip [META] block, 让 _zh_clean
                #   只含真 ZH translation. 既治 BUG 又不破老 META 链 (parse_meta line
                #   4697 仍按原逻辑跑).
                # =====================================================================
                _META_DETECT_RE = re.compile(
                    r'[\[【]\s*meta\s*[\]】].*$',
                    re.IGNORECASE | re.DOTALL,
                )
                _zh_clean = _META_DETECT_RE.sub('', _zh_clean).strip()
                # 🆕 [Sir 2026-05-26 21:50 真痛追根 BUG-K 治本]
                # Sir 21:07 真测: ZH 末尾 '"That is home。"' (含末尾 quote mark)
                # → 末尾 '"' 不在 endings → 误报 truncated. 修: 加 ASCII/CJK quotes
                # 到 endings (引号收尾是合法 ZH 翻译收束模式, e.g. 引用电影台词).
                _zh_endings = set('.?!。？！…"\'""''」』）)')
                _zh_truncated = False
                if _en_net and len(_en_net) >= 30:
                    if not _zh_clean:
                        _zh_truncated = True  # 完全没 ZH
                    elif _zh_clean[-1] not in _zh_endings:
                        _zh_truncated = True  # 末尾不是收束标点 = LLM stop 半途
                    # 🆕 [Sir 2026-05-26 20:21 真测追根 BUG 治本 / 准则 8 优雅]
                    # =====================================================================
                    # 老 elif 'len(_zh_clean) < len(_en_net) * 0.4' 误伤正常翻译.
                    # Sir 真测 (20:21:03): ZH=76ch / EN=216ch = 35% < 40% 触发 truncate,
                    # 但 ends_ok=True (末尾 '。') → ZH 实际完整, 还误触 worker 补一次字幕.
                    # 真根因: 中文译英文 0.25-0.5 都正常 (中文紧凑), ratio 0.4 太严.
                    # 修法 (准则 8 优雅): 删 ratio elif, ends_ok 已是 LLM 完成的强证据.
                    # 极端反例 ('好。' / 200ch EN) 不算 ZH truncate, 而是 LLM 翻译偷懒,
                    # 由主脑下轮自纠 (不该 chat_bypass 这边误报 truncate 触发补字幕).
                    # =====================================================================
                if _zh_truncated:
                    # 含足够英文但 ZH 缺失/不完整 → 翻译被 LLM truncate
                    from jarvis_utils import bg_log as _zh_miss_bg
                    _zh_miss_bg(
                        f"⚠️ [Bilingual/Truncated] reply has English ({len(_en_net)}ch) "
                        f"but ZH translation truncated/missing "
                        f"(zh_len={len(_zh_clean)}ch, ends_ok={_zh_clean and _zh_clean[-1] in _zh_endings}). "
                        f"en_snip='{_en_net[:60]}...' zh_snip='{_zh_clean[:40]}...'"
                    )
                    try:
                        from jarvis_utils import get_event_bus as _geb_zh
                        _bus_zh = _geb_zh()
                        if _bus_zh is not None:
                            _bus_zh.publish(
                                etype='bilingual_truncated',
                                description=(
                                    f"reply 缺 ---ZH--- 翻译 (en={len(_en_net)}ch)"
                                ),
                                source='chat_bypass.stream_main',
                                metadata={
                                    'en_length': len(_en_net),
                                    'en_snippet': _en_net[:200],
                                },
                                salience=0.45,
                            )
                    except Exception:
                        pass

                    # 🆕 [Sir 2026-05-25 20:23 真测追根 BUG 治本 #2] truncate fallback 续写
                    # =====================================================================
                    # Sir 选 '3 者都上' 治 truncate. 此处实施 #2 — chat_bypass 检到
                    # truncate → spawn thread 调 flash_lite 续写完整 reply + ZH 翻译,
                    # 主响应路径不阻塞. 续写完通过 subtitle_queue 补 ZH 字幕给 Sir.
                    # 准则 8 优雅高效可持续: 1 次轻量 LLM 调用 ~1s, Sir 体验提升明显.
                    # =====================================================================
                    try:
                        import threading as _th_tr
                        def _truncate_continuation_worker(en_snippet: str, zh_snippet: str):
                            try:
                                from jarvis_llm_reflector import LlmReflector as _LR
                                from jarvis_utils import bg_log as _tr_bg
                                _refl = _LR.get_instance(
                                    key_router=self.key_router
                                ) if hasattr(_LR, 'get_instance') else None
                                if _refl is None:
                                    _refl = _LR(key_router=self.key_router)
                                _sys_prompt = (
                                    "You are repairing Jarvis's truncated butler reply. "
                                    "Output ONLY in this exact format:\n"
                                    "<EN>...continuation of English if EN is incomplete; "
                                    "empty if EN already ends naturally</EN>\n"
                                    "<ZH>...COMPLETE Chinese translation of "
                                    "(EN + EN continuation); always fully translate, "
                                    "never leave ZH mid-sentence</ZH>\n"
                                    "Keep butler style: factual, concise, no emojis.\n"
                                    "🚨 INTEGRITY RED LINE (准则 5): "
                                    "DO NOT invent facts/numbers/data. "
                                    "If EN is cut mid-sentence and you don't know the missing "
                                    "info (e.g. 'updated total intake to ___'), use a vague "
                                    "graceful close like 'reflect your recent input' or "
                                    "'the new value'. NEVER fabricate specific numbers/units."
                                )
                                _user_prompt = (
                                    f"EN (may be complete or truncated):\n"
                                    f"```\n{en_snippet}\n```\n\n"
                                    f"ZH partial (may be empty or mid-sentence):\n"
                                    f"```\n{zh_snippet or '(empty)'}\n```\n\n"
                                    f"Task: if EN ends naturally (period/etc.), "
                                    f"leave <EN/> empty; otherwise complete it briefly. "
                                    f"Always produce FULL ZH translation."
                                )
                                _res = _refl.reflect(
                                    model='flash_lite',
                                    system_prompt=_sys_prompt,
                                    user_prompt=_user_prompt,
                                    force=True,  # 不走 cache
                                )
                                if not _res.get('success'):
                                    _tr_bg(f"⚠️ [Truncate/Cont] reflector fail, skip")
                                    return
                                _raw = _res.get('raw_text', '') or ''
                                _en_cont = ''
                                _zh_full = ''
                                _m_en = re.search(r'<EN>(.*?)</EN>', _raw, re.DOTALL)
                                _m_zh = re.search(r'<ZH>(.*?)</ZH>', _raw, re.DOTALL)
                                if _m_en:
                                    _en_cont = _m_en.group(1).strip()
                                if _m_zh:
                                    _zh_full = _m_zh.group(1).strip()
                                if _zh_full:
                                    try:
                                        self.subtitle_queue.put(("zh", _zh_full))
                                        _tr_bg(
                                            f"✅ [Truncate/Cont] ZH 补字幕 ({len(_zh_full)}ch): "
                                            f"'{_zh_full[:60]}...'"
                                        )
                                    except Exception as _e_sub:
                                        _tr_bg(f"⚠️ [Truncate/Cont] subtitle.put fail: {_e_sub}")
                                    # 🆕 [Sir 2026-05-25 22:01 真测追根 BUG 治本]
                                    # ============================================
                                    # Sir 真痛点 (turn 21:58:13 + 21:58:49):
                                    #   - Turn 1 ZH truncate → worker 补 67ch ZH 字幕成功
                                    #   - Turn 2 主脑仍道歉 "previous response was cut short.
                                    #     To complete my thought: ..." 重复复述全文
                                    # 根因: worker 补完只 subtitle.put + bg_log, 没 publish
                                    #   'bilingual_truncate_recovered' SWM event.
                                    #   _trigger_bilingual_truncated_recover 只看
                                    #   'bilingual_truncated' 120s 内 → 永远 fire →
                                    #   directive 永远教主脑道歉 + 复述.
                                    # 修法 (准则 6 evidence-driven):
                                    #   publish 'bilingual_truncate_recovered' 让 directive
                                    #   trigger 看到 paired event 不 fire (字幕已补).
                                    # ============================================
                                    try:
                                        from jarvis_utils import get_event_bus as _geb_rc
                                        _bus_rc = _geb_rc()
                                        if _bus_rc is not None:
                                            _bus_rc.publish(
                                                etype='bilingual_truncate_recovered',
                                                description=(
                                                    f"ZH 字幕已补 ({len(_zh_full)}ch) — "
                                                    f"主脑下轮不必道歉/复述"
                                                ),
                                                source='chat_bypass.truncate_cont_worker',
                                                metadata={
                                                    'recovered_zh_length': len(_zh_full),
                                                    'recovered_zh_snippet': _zh_full[:200],
                                                    'original_en_length': len(en_snippet),
                                                    'en_cont_emitted': bool(
                                                        _en_cont and len(_en_cont) >= 2
                                                    ),
                                                },
                                                salience=0.5,
                                            )
                                    except Exception:
                                        pass
                                # 🆕 [Sir 2026-05-25 21:38 真测追根] EN cont 进 TTS 队列
                                # =====================================================
                                # Sir 真痛点: 续写只补 ZH 字幕, EN reply 半截 TTS 已说完
                                # → Sir 听到 'Noted, Sir. I have updated your total intake to'
                                # 卡在 'to' 没下文. 治本: EN cont 也走 _put_audio → TTS
                                # 续播下半句. 有 ~1s audio gap (续写延迟) 但比卡死好.
                                # 准则 5 言出必行 + 准则 8 优雅 (1 次 LLM 双用).
                                # =====================================================
                                if _en_cont and len(_en_cont) >= 2:
                                    try:
                                        # _en_cont 已是英文续写, 不要再加 ---ZH--- (避免再触发 truncate 检)
                                        self._put_audio(_en_cont, is_response=True)
                                        _tr_bg(
                                            f"✅ [Truncate/Cont] EN 续 TTS ({len(_en_cont)}ch): "
                                            f"'{_en_cont[:60]}...'"
                                        )
                                    except Exception as _e_au:
                                        _tr_bg(f"⚠️ [Truncate/Cont] EN put_audio fail: {_e_au}")
                            except Exception as _e_tr:
                                try:
                                    from jarvis_utils import bg_log as _tr_bg2
                                    _tr_bg2(f"⚠️ [Truncate/Cont] worker exception: {_e_tr}")
                                except Exception:
                                    pass
                        _th_tr.Thread(
                            target=_truncate_continuation_worker,
                            args=(_en_net, _zh_clean),
                            daemon=True,
                            name='TruncateContinuation',
                        ).start()
                    except Exception:
                        pass
            except Exception:
                pass

            if buffer.strip() and not getattr(self, 'is_interrupted', False):
                sentence = buffer.strip()
                # [P0+18-c.1] 末尾 buffer 同步剥所有结构化标签 block（FAST_CALL +
                # PROMISE + ACTIVATE_PLAN + CANCEL_PLAN + RESUME_PLAN），避免 JSON 字面
                # 文本最终通过 _put_audio 进入 TTS
                sentence = _strip_structural_tag_blocks(sentence)
                if "---ZH---" in sentence:
                    is_subtitle_mode = True
                    sentence = sentence.split("---ZH---")[0]
                elif is_subtitle_mode:
                    sentence = ""

                sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                sentence = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', sentence).strip()
                sentence = sentence.replace("J A R V I S", "Jarvis").replace("JARVIS", "Jarvis")
                if sentence:
                    self._put_audio(sentence)
                    self.subtitle_queue.put(("en", sentence))

            if not getattr(self, 'is_interrupted', False):
                print("") 
                print("╚" + "═"*63 + "\n")
                
                if "[CLIPBOARD]" in full_text:
                    clipboard_content = full_text.split("[CLIPBOARD]")[1].strip()
                    try:
                        import pyperclip
                        pyperclip.copy(clipboard_content)
                        print(f"[Clipboard] {len(clipboard_content)} 字符已注入 Windows 剪贴板。(按 Ctrl+V 使用)")
                        print("═"*65 + "\n")
                    except ImportError:
                        pass
            
            # 🆕 [P5-Layer1-fix19 / 2026-05-22] Sir 13:13 立 — 主脑最小 thinking pass.
            # 主脑 reply 末尾 emit [META] 一行 (evidence/reaction/skip_alert/note).
            # parse 抽 + 裁掉 (不让 [META] 进 Sir-facing TTS), publish SWM 给
            # ClaimTracer/IntegrityWatcher 订阅 + audit jsonl 持久化 (debug 神器).
            try:
                from jarvis_meta_self_check import parse_meta, publish_meta
                _full_clean, _meta = parse_meta(full_text)
                full_text = _full_clean  # 裁掉 [META] 行, 不让进 ZH/TTS
                # 🆕 [P5-fix26 / 2026-05-22] Sir 20:32 真测发现:
                # Evaluator (LLM) 看 sir-facing reply 已裁 [META] → 必判 helped=no
                # reason='Missing meta trace'. fix23 让 directive 不降级是对的, 但
                # Evaluator 错杀仍累积 not_helped. 治本: parse_ok 直接 record_helped
                # (绕过 LLM evaluator), Evaluator 路径 skip meta_self_check_directive.
                try:
                    from jarvis_directives import get_default_registry as _gdr
                    _reg = _gdr()
                    _reg.record_helped('meta_self_check_directive',
                                          helped=bool(_meta and _meta.parse_ok))
                except Exception:
                    pass
                if _meta and _meta.parse_ok:
                    try:
                        from jarvis_utils import TraceContext as _TC2
                        _t_id = _TC2.get_turn_id() or ''
                    except Exception:
                        _t_id = ''
                    publish_meta(_meta, turn_id=_t_id,
                                  user_input=clean_user_input or '',
                                  event_bus=getattr(self.jarvis, 'event_bus', None))
            except Exception:
                pass

            # 🆕 [P5-fix29 / 2026-05-22] Sir 20:59 真测发现:
            # stream_chat 主路径 (主对话 google_pool) **缺** IntentRouter 调用!
            # 只在 stream_chat_cloud_followup (line 2018) 和 stream_nudge (line 4965)
            # 有, 主路径完全漏掉. 主脑 emit <TOOL_CALL>{intent='dashboard_open'}
            # → 没人 invoke → Sir 看到"打开了"但面板没开 (虚假 ack).
            # 治本: 主路径同样跑 IntentRouter, 跟 cloud_followup 行为一致.
            try:
                from jarvis_intent_router import IntentParser, get_default_intent_router
                if IntentParser.has_tool_call_tag(full_text):
                    _router = get_default_intent_router()
                    if _router is not None:
                        _ir_results = _router.route_and_invoke_all(full_text)
                        if _ir_results:
                            try:
                                from jarvis_utils import bg_log as _ir_bg
                                _hits = sum(1 for r in _ir_results if r.get('success'))
                                _ir_bg(
                                    f"🔧 [IntentRouter] {len(_ir_results)} tool calls "
                                    f"({_hits} success): "
                                    + ', '.join(
                                        f"{r.get('intent_id', '?')}={'✅' if r.get('success') else '❌'}"
                                        for r in _ir_results[:5]
                                    )
                                )
                            except Exception:
                                pass
            except Exception:
                pass

            # 🆕 [BUG C / Sir 2026-05-28 16:08 真痛 "15.4秒？" + "23.4s"]
            # ===================================================================
            # stream loop 终点 checkpoint, 后面 post-stream hook 累计耗时算定位:
            #   pre_stream_s = _t_api_start - _t0  (截图 + audio + prompt assemble)
            #   ttft_s = _last_ttft_s
            #   stream_only_s = _t_stream_end - _t_first_chunk
            #   post_stream_s = _t_total - _t_stream_end + _t0  (注 _t_total 含 _t0)
            # 不改 logic, 只 emit timing log 让 Sir 下次真测看具体瓶颈.
            # ===================================================================
            _t_stream_end = time.time()
            final_reply = full_text.split("---ZH---")[0].strip()
            
            if "---ZH---" in full_text:
                zh_text = full_text.split("---ZH---")[1].strip()
                clean_zh = re.sub(r'<[^>]+>', '', zh_text).strip()
                if clean_zh:
                    # 🆕 [Sir 23:24 BUG-1 治本] 末尾不合法 → defer (worker 补 atomic put)
                    if _zh_subtitle_looks_truncated(clean_zh, len(final_reply)):
                        try:
                            from jarvis_utils import bg_log as _zh_def_bg3
                            _zh_def_bg3(f"⏸ [Subtitle/ZH-defer] leftover ZH 末尾不合法 ({len(clean_zh)}ch '{clean_zh[-20:]}'), 跳过 put, 等 worker 补")
                        except Exception:
                            pass
                    else:
                        self.subtitle_queue.put(("zh", clean_zh))
            
        except Exception as e:
            import traceback as _tb
            _elapsed = time.time() - _t0 if '_t0' in dir() else 0
            print(f"\n║ ╔══ [旁路错误详情] ════════════════════════════════")
            print(f"║ ║ 类型: {type(e).__name__}")
            print(f"║ ║ 消息: {e}")
            print(f"║ ║ 耗时: {_elapsed:.1f}秒")
            print(f"║ ║ 堆栈 (最近3帧):")
            for _line in _tb.format_exc().strip().split('\n')[-6:]:
                print(f"║ ║   {_line}")
            print(f"║ ╚══════════════════════════════════════════════════════════")

            # 🩹 [P0+20-β.5.12 / 2026-05-19] BUG-A: partial-stream + 道歉拼接体感分裂修
            # Sir 21:37 实测 (RemoteProtocolError after 18.8s):
            #   云端 stream 已 fetch "I try to be, Sir. It is often the most practical approach."
            #   播给 Sir 听完后, 服务端 close TCP → except 触发 → 又补一句 "Forgive me Sir,
            #   the evening network traffic..." 道歉. 用户体感: 主回复 + 突兀道歉 = 分裂.
            # 修法: 若 stream 已 fetch 到实质内容 (>= 12 字符 net text), 视为"功能已达成",
            # bg_log 错误诊断 + 不补道歉, 直接 return True. 否则走老 fallback 链.
            try:
                _spoken_net = (full_text or '').strip() if 'full_text' in dir() else ''
                # 净化: 剥结构化 tag block / ---ZH--- 之后 / <...> 行内 tag
                _spoken_net = _strip_structural_tag_blocks(_spoken_net)
                if '---ZH---' in _spoken_net:
                    _spoken_net = _spoken_net.split('---ZH---')[0]
                _spoken_net = re.sub(r'<[^>]+>', '', _spoken_net).strip()
                _spoken_net = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', _spoken_net).strip()
            except Exception:
                _spoken_net = ''
            _spoken_threshold = 12  # 字符, 低于此视为"几乎没说"
            if _spoken_net and len(_spoken_net) >= _spoken_threshold:
                try:
                    from jarvis_utils import bg_log as _b512
                    _b512(f"🩹 [β.5.12/BUG-A] cloud stream {type(e).__name__} after spoken={len(_spoken_net)}ch, skip 道歉")
                except Exception:
                    pass
                print(f"║ ✅ [β.5.12] 已说 {len(_spoken_net)} 字符实质内容, 跳过道歉补丁\n╚{'═'*63}\n")
                if '_stream_key_name' in dir():
                    self.key_router.release(_stream_key_name)
                return True, _spoken_net

            local_reply = self._try_local_fallback(user_input, stm_context)
            if local_reply:
                print(f"║ 🔄 [本地兜底] 切换到 {get_local_fallback()._model}")
                print(f"║ 🤖  [Jarvis-Local] {local_reply[:200]}")
                self._speak_local_reply(local_reply)
                print("╚" + "═"*63 + "\n")
                if '_stream_key_name' in dir():
                    self.key_router.release(_stream_key_name)
                return True, local_reply
            print("╚" + "═"*63 + "\n")
            self._speak_fallback()
            if '_stream_key_name' in dir():
                self.key_router.release(_stream_key_name)
            return False, "fallback"
        finally:
            # 🧹 [打印整顿] 关闭对话框背景日志缓冲并 flush —— 不管走的是哪条 return 路径
            try:
                from jarvis_utils import set_conversation_active
                set_conversation_active(False)
            except Exception:
                pass

        if '_stream_key_name' in dir():
            self.key_router.release(_stream_key_name)
        if hasattr(self, 'jarvis') and hasattr(self.jarvis, 'correction_loop'):
            self.jarvis.correction_loop.on_jarvis_response(final_reply)
        if hasattr(self, 'jarvis') and hasattr(self.jarvis, 'content_tracker'):
            self.jarvis.content_tracker.record_interaction(clean_user_input, final_reply)
        # 🎯 [P0+20-β.0.5 / 2026-05-16] L2 directive 异步评分 (Gemini-3-Flash via OpenRouter)
        # 把本轮 fired 的 directive ids + reply + user_input 喂给 evaluator，背景评分。
        # 主路径不阻塞；失败/超时静默丢弃；rate limit 命中跳过本批。
        # 🩹 [P0+20-β.1.18 / 2026-05-16] 治 Sir 18:30 实测 BUG：
        # bilingual_directive helped=0 但实际 Sir 看到回复有中文 → 因为 final_reply 已被
        # split("---ZH---")[0] 剥掉中文部分 → 评分 LLM 看到纯英文当然判 "Missing Chinese"。
        # 修法：传给 evaluator 用 full_text（完整 reply，含 ---ZH--- 中文部分），
        # 让评分 LLM 能正确判断 bilingual_directive 是否被遵守。
        try:
            evaluator = getattr(self.jarvis, 'directive_evaluator', None)
            if evaluator is not None:
                fired_ids = list(getattr(self.jarvis, '_l2_last_fired_ids', []) or [])
                # 优先用 full_text（含 ---ZH--- + 中文），fallback 到 final_reply
                _eval_reply = full_text if (full_text and full_text.strip()) else final_reply
                if fired_ids and _eval_reply and clean_user_input:
                    evaluator.evaluate_async(
                        fired_directive_ids=fired_ids,
                        user_input=clean_user_input,
                        jarvis_reply=_eval_reply,
                    )
        except Exception:
            pass

        # 🆕 [Sir 2026-05-26 22:03 真痛 BUG-S 治本] FAST_CALL 路径补 publish SWM 'tool_called'
        # =====================================================================
        # Sir 真测: concerns.dismiss 返 ❌, INTEGRITY/Alert gated_silent (SWM 无 evidence).
        # 老路径 chat_bypass FAST_CALL execute 后只 append _tool_results, 没 publish SWM.
        # 而 IntentResolver/InnerThought 路径 publish 'tool_called' SWM. 现补 chat_bypass
        # FAST_CALL 路径也 publish, 让 INTEGRITY/Alert 第 3 trigger (tool_failed_recent)
        # 看到 evidence → force inject ALERT → 主脑下轮道歉.
        # =====================================================================
        try:
            if '_tool_results' in dir() and _tool_results:
                from jarvis_utils import get_event_bus as _geb_tc
                _bus_tc_chat = _geb_tc()
                if _bus_tc_chat is not None:
                    for _tr_item in _tool_results:
                        _tr_str = str(_tr_item or '')
                        if not _tr_str:
                            continue
                        _tr_ok = _tr_str.startswith('✅')
                        _tr_failed = (_tr_str.startswith('❌')
                                       or _tr_str.startswith('🛡️'))
                        _bus_tc_chat.publish(
                            etype='tool_called',
                            description=(
                                ('✓ ' if _tr_ok else ('✗ ' if _tr_failed else '? '))
                                + _tr_str[:120]
                            ),
                            source='chat_bypass.fast_call',
                            salience=0.85 if _tr_failed else 0.75,
                            metadata={
                                'ok': _tr_ok if (_tr_ok or _tr_failed) else None,
                                'result_summary': _tr_str[:200],
                                'turn_id': str(
                                    (lambda: __import__('jarvis_utils')
                                     .TraceContext.get_turn_id() or '')()
                                ),
                            },
                        )
        except Exception:
            pass

        # 🩹 [P0+20-β.2.8.7 / 2026-05-17] ClaimTracer — 通用反幻觉检测
        # Sir 23:32 反馈: "硬编码只是时间不能编造幻觉吗?" 改通用 framework.
        # 解析 final_reply 抽 specific factual claim (时间/数字/quote) →
        # trace 到 tool_results / STM / uncertainty marker → 没 trace 到 bg_log warning.
        try:
            from jarvis_claim_tracer import trace_reply, update_stats
            from jarvis_utils import TraceContext as _TC
            try:
                _ttid = _TC.get_turn_id() or ''
            except Exception:
                _ttid = ''
            # 🩹 [β.4.3.3 / 2026-05-18] L1+L2 表驱接入: system_clock + ltm_context
            # 治本 β.4.2-hotfix 教训: time claim 现可通过 SYSTEM CLOCK ±2min verify.
            # ltm_context 只取本轮 prompt 注入的 LTM 段 (避免占内存).
            _now_clock = time.time()
            _ltm_ctx_str = ''
            try:
                _ltm_ctx_str = str(getattr(self, '_last_ltm_context', '') or '')[:2000]
            except Exception:
                _ltm_ctx_str = ''
            _claim_result = trace_reply(
                jarvis_reply=final_reply,
                tool_results=list(_tool_results) if '_tool_results' in dir() else [],
                stm_recent=list(getattr(self.jarvis, 'short_term_memory', []) or []),
                turn_id=_ttid,
                system_clock=_now_clock,
                ltm_context=_ltm_ctx_str,
            )
            update_stats(_claim_result)
        except Exception:
            pass

        # 🩹 [P0+20-β.2.5 / 2026-05-17] 灵魂工程 Layer 4 ConcernsReflector
        # 每轮对话末尾启发式扫 keyword → 给相关 concerns 加 signal。
        # 纯启发式，~50us，不走 LLM。fire-and-forget thread 即可，但本身就快。
        # 详 docs/JARVIS_SOUL_DRIVE.md §6 (Layer 4)
        _turn_id_now = ''
        try:
            from jarvis_utils import TraceContext
            _turn_id_now = TraceContext.get_turn_id() or ''
        except Exception:
            pass
        try:
            cr = getattr(self.jarvis, 'concerns_reflector', None)
            if cr is not None and (clean_user_input or final_reply):
                # 用 daemon thread fire-and-forget，避免任何意外阻塞主路径
                try:
                    import threading as _th
                    _th.Thread(
                        target=cr.reflect_turn,
                        kwargs={
                            'user_input': clean_user_input or '',
                            'jarvis_reply': final_reply or '',
                            'turn_id': _turn_id_now,
                        },
                        daemon=True, name='ConcernsReflectorTurn'
                    ).start()
                except Exception:
                    pass
        except Exception:
            pass

        # 🆕 [β.5.46-fix18 / 2026-05-22] Sir 11:39 真测 BUG: 驾照"放一放" 持久化失效.
        # ProjectHoldDetector: 检测 Sir cmd 含 hold phrase ("放一放/hold off/...") +
        # project keyword (hippo 模糊匹) → publish SWM candidate. IntentResolver
        # 主脑下轮看 evidence 自决调 tool_project_hold (ProjectTimeline.held_until_ts).
        # 三维耦合 (准则 6 β.5.0): 数据强耦合 (SWM) + 行为弱耦合 (publish-only) +
        # 决策集中主脑.
        try:
            if clean_user_input or final_reply:
                import threading as _th
                def _run_phd():
                    try:
                        from jarvis_project_hold_detector import detect_and_publish
                        hippo = getattr(self.jarvis, 'hippocampus', None)
                        bus = getattr(self.jarvis, 'event_bus', None)
                        if bus is None:
                            try:
                                from jarvis_utils import get_event_bus
                                bus = get_event_bus()
                            except Exception:
                                bus = None
                        if hippo is None or bus is None:
                            return
                        detect_and_publish(
                            cmd=clean_user_input or '',
                            jarvis_reply=final_reply or '',
                            turn_id=_turn_id_now,
                            hippocampus=hippo,
                            event_bus=bus,
                        )
                    except Exception:
                        pass
                _th.Thread(target=_run_phd, daemon=True,
                            name='ProjectHoldDetector').start()
        except Exception:
            pass

        # 🩹 [P0+20-β.2.6 / 2026-05-17] 灵魂工程 Layer 5 SoulAlignmentEvaluator
        # 异步评 Jarvis 本轮回复是否对齐 self_model + relational_state，把信号
        # 写回 concerns_ledger.record_alignment 累计。LLM 调用走 OpenRouter，
        # 失败/超时/无 key/rate limit 都 silent + bg_log，不阻塞主路径。
        # 详 docs/JARVIS_SOUL_DRIVE.md §5.3
        try:
            se = getattr(self.jarvis, 'soul_evaluator', None)
            # 优先用 full_text（含 ---ZH--- + 中文），fallback final_reply
            _se_reply = full_text if (full_text and full_text.strip()) else final_reply
            if se is not None and clean_user_input and _se_reply:
                se.evaluate_async(
                    user_input=clean_user_input,
                    jarvis_reply=_se_reply,
                    turn_id=_turn_id_now,
                )
        except Exception:
            pass
        # 🩹 [P0+20-β.2.7.3 / 2026-05-17] Self-Promise Detector：
        # Jarvis 自己说"我会监督您 13:05" → 注册成 commitment + 定时 nudge
        # 与 Sir 的承诺平等地走 commitment_watcher。
        # 详 docs/JARVIS_SOUL_UNIVERSALIZATION.md / 承诺必行原则
        try:
            from jarvis_self_promise import get_default_detector as _gdp
            cw = getattr(self.jarvis, 'commitment_watcher', None)
            _sp_reply = full_text if (full_text and full_text.strip()) else final_reply
            if _sp_reply and cw is not None:
                _gdp().detect_and_register_async(
                    jarvis_reply=_sp_reply,
                    commitment_watcher=cw,
                    turn_id=_turn_id_now,
                )
        except Exception:
            pass

        # 🆕 [β.5.46-fix13 Fix-3 / 2026-05-22] WatchTask register hook
        # Sir 22:18 真测痛点: Sir 说"等导出完成提醒" Jarvis 答应"keep an eye on" 但
        # 没机制兑现 — Time Hook trigger 空, SelfPromise soft 仅 log, ScreenVision
        # 只 describe 不 trigger nudge. 治本: 此处 LLM 提取 watch task, 持久化, 由
        # ScreenVision daemon 每次 describe 后 judge trigger 命中.
        # 准则 6 三维耦合: 数据进 SWM, LLM 决策, CLI scripts/watch_task_dump.py 可改.
        try:
            from jarvis_watch_task import register_async as _wt_reg
            _wt_reply = full_text if (full_text and full_text.strip()) else final_reply
            _wt_kr = getattr(self.jarvis, 'key_router', None) \
                       or getattr(self, 'key_router', None)
            if clean_user_input and _wt_reply:
                _wt_reg(
                    sir_text=clean_user_input,
                    jarvis_reply=_wt_reply,
                    turn_id=_turn_id_now,
                    key_router=_wt_kr,
                )
        except Exception:
            pass

        # 🩹 [P5-IntegrityWatcher / 2026-05-21 14:15] L4.5 watch claim from reply
        # Sir 14:11 真意 — Jarvis reply 中含 mutation claim → watcher 加入 watch list.
        # 监督 8 类 (reminder/commitment/promise/memory/milestone/profile/concern/relational).
        # 失败递归 retry, 真做不到 handoff Sir. 主脑下轮 [INTEGRITY WATCHER REPORT] 看.
        # 跟 SelfPromiseDetector 互补 — SelfPromise 只看 promise 类, watcher 看全部.
        try:
            iw = getattr(self.jarvis, 'integrity_watcher', None)
            _iw_reply = full_text if (full_text and full_text.strip()) else final_reply
            if iw is not None and _iw_reply:
                iw.watch_claim_async(reply_text=_iw_reply, turn_id=_turn_id_now)
        except Exception:
            pass

        # 🩹 [β.5.44-CE / 2026-05-20 19:02] IntentResolver fire turn-end
        # Sir 18:55 真理重构 — turn 末尾异步跑 IntentResolver, 看 Sir utterance + 
        # SWM candidates + 当前 state, LLM 决定调哪些 mutation tool. 结果 publish 
        # 'intent_resolved' SWM, 主脑下轮 prompt 看 [INTENT RESOLVED THIS TURN] 
        # 知道真做了什么, 不再撒谎说 "I've corrected" 当本轮零 mutation.
        try:
            from jarvis_intent_resolver import get_intent_resolver as _gir
            _resolver = _gir()
            if _resolver is not None and prompt:
                # 取 Sir 原话 (prompt 末段往往含 user_input)
                _sir_utt_for_ir = ''
                try:
                    # 简易抽取: 找 [USER INPUT] 或最后一行
                    for _ln in (prompt or '').split('\n')[-12:]:
                        _ln = _ln.strip()
                        if _ln and not _ln.startswith('[') and not _ln.startswith('==='):
                            _sir_utt_for_ir = _ln
                except Exception:
                    pass
                if _sir_utt_for_ir and len(_sir_utt_for_ir) >= 4:
                    _resolver.resolve_turn_async(
                        turn_id=_turn_id_now,
                        sir_utterance=_sir_utt_for_ir,
                    )
        except Exception:
            pass
        _t_total = time.time() - _t0
        # 🆕 [BUG C / Sir 2026-05-28 16:08 真痛 "15.4秒？" + "23.4s"]
        # 分段 break-down log: 让 Sir 下次真测看具体瓶颈在哪段
        #   pre_stream  = _t_api_start - _t0           (截图 + audio + prompt assemble)
        #   ttft        = _last_ttft_s                  (connect + 首 token 等待)
        #   stream_only = _t_stream_end - _t_first_chunk (流式 chunk 接收)
        #   post_stream = _t_total - (_t_stream_end - _t0) (post-stream hook: ClaimTracer / IR / record_nudge)
        _ss_dur = max(0, _t_ss_done - _t_ss_start)
        _pre_stream_s = None
        _ttft_s = getattr(self, '_last_ttft_s', None)
        _stream_only_s = None
        _post_stream_s = None
        try:
            _t_api_start_abs = getattr(self, '_last_t_api_start_ts', None)
            _t_first_chunk_abs = getattr(self, '_last_t_first_chunk_ts', None)
            if _t_api_start_abs:
                _pre_stream_s = max(0, _t_api_start_abs - _t0)
            # _t_stream_end 定义在 stream loop 内部的 try block (line 5201),
            # 若 stream 抛 exception 未到 5201, 此变量未赋值 → 用 locals() 守
            _locals_snapshot = locals()
            if _t_first_chunk_abs and '_t_stream_end' in _locals_snapshot:
                _stream_only_s = max(0, _locals_snapshot['_t_stream_end'] - _t_first_chunk_abs)
            if '_t_stream_end' in _locals_snapshot:
                _post_stream_s = max(0, (time.time() - _locals_snapshot['_t_stream_end']))
        except Exception:
            pass
        try:
            from jarvis_utils import bg_log
            bg_log(f"⏱️ [Pipeline Timer] stream_chat总耗时: {_t_total:.1f}s (截图{_ss_dur:.1f}s + API+流式{_t_total - _ss_dur:.1f}s)")
            # 分段 break-down
            _seg_parts = []
            if _pre_stream_s is not None:
                _seg_parts.append(f"pre_stream={_pre_stream_s:.1f}s")
            if _ttft_s is not None:
                _seg_parts.append(f"ttft={_ttft_s:.1f}s")
            if _stream_only_s is not None:
                _seg_parts.append(f"stream_only={_stream_only_s:.1f}s")
            if _post_stream_s is not None:
                _seg_parts.append(f"post_stream={_post_stream_s:.1f}s")
            if _seg_parts:
                bg_log(f"⏱️ [Pipeline Timer/Breakdown] {' | '.join(_seg_parts)} | total={_t_total:.1f}s")
        except Exception:
            print(f"⏱️ [Pipeline Timer] stream_chat总耗时: {_t_total:.1f}s (截图{_ss_dur:.1f}s + API+流式{_t_total - _ss_dur:.1f}s)", file=sys.stderr)

        # 🩹 [P3-BUG#1 / 2026-05-20 23:30] stream_chat 主对话 reply 也 record 进
        # RecentNudgeMemory. P2 Gap12 只 wire 在 stream_nudge, 主对话漏了 → 主脑
        # 下次 nudge 看不到自己主对话刚说啥 → 仍可能重复主题. 修.
        # channel='main_chat' 区别 sentinel nudge, 跨 channel 主脑看完整全貌.
        try:
            if final_reply and final_reply.strip():
                from jarvis_recent_nudge_memory import record_nudge as _rn3
                _turn_id_for_rn = ''
                try:
                    from jarvis_utils import TraceContext as _TC3
                    _turn_id_for_rn = _TC3.get_turn_id() or ''
                except Exception:
                    pass
                _rn3(
                    channel='main_chat',
                    content=final_reply,
                    trigger=str(user_input or '')[:60],
                    turn_id=_turn_id_for_rn,
                )
        except Exception:
            pass

        # 🆕 [Sir 2026-05-27 真愿景 Phase 3] 主脑 reply self-append 进 voice track
        # =====================================================================
        # Sir 真愿景: jarvis 自我感知闭环 — 主脑下次召唤时, voice 含"我刚跟 Sir
        # 说过什么", 避免重复 / 重叠 / 矛盾. 思考脑下次 tick 也读 voice tail,
        # 知道嘴刚说了什么 (e.g. 不要又默 propose 同一主题).
        # source='self_reflection' intent='noting'. urgency=0.3 (低, 不刷屏).
        # wants_voice=False (主脑不该 surface "我刚说过 X" 给 Sir, 这是内部记账).
        # system_event skip (后台事件不算自我感知).
        # 任何错误静默, 不阻 turn-end.
        # =====================================================================
        # 🆕 [Phase 4] 在 self-append 前先调 mark_recent_surfaced_by_overlap —
        # 主脑本轮 reply 若 reference 了 ★ pending entry (token overlap),
        # mark 那些 entry surfaced=True, 下次 prompt 不再 spotlight 它们.
        try:
            _is_sys_evt = bool(
                clean_intent and str(clean_intent).startswith('[后台系统')
            )
            if not _is_sys_evt and final_reply and final_reply.strip():
                from jarvis_inner_voice_track import (
                    get_inner_voice_track, is_enabled as _iv_enabled,
                )
                if _iv_enabled():
                    # Phase 4 先 mark surfaced (本轮 reply 是否 reference ★ pending)
                    try:
                        get_inner_voice_track().mark_recent_surfaced_by_overlap(
                            reply_text=str(final_reply or ''),
                            within_min=60.0,
                        )
                    except Exception:
                        pass

                    _reply_preview = str(final_reply).strip()[:120]
                    _sir_preview = str(user_input or '').strip()[:60]
                    _voice_content = f'i replied to sir: "{_reply_preview}"'
                    _voice_meta = {
                        'kind': 'main_reply',
                        'reply_len': len(final_reply or ''),
                        'reply_excerpt': _reply_preview,
                        'sir_excerpt': _sir_preview,
                        'turn_id': _turn_id_for_rn if '_turn_id_for_rn' in dir() else '',
                    }
                    get_inner_voice_track().append(
                        source='self_reflection',
                        intent='noting',
                        content=_voice_content,
                        urgency=0.3,
                        wants_voice=False,
                        meta=_voice_meta,
                    )
        except Exception:
            pass

        # 🩹 [Gap 1 / P5-ToM / 2026-05-21 01:05] ToMReflector async trigger
        # Sir 22:10 真理: Jarvis 应读 Sir 言外之意 (surface/deeper/unspoken need).
        # 每 turn 后 LLM judge → propose hypothesis update. 主脑下轮看 [SIR'S MIND]
        # block 自决 reply 深度. async fire-and-forget, 不阻塞.
        try:
            _tom = getattr(self.jarvis, 'tom_reflector', None) if hasattr(self, 'jarvis') else None
            if _tom is not None and final_reply and final_reply.strip() and clean_user_input:
                _turn_id_tom = ''
                try:
                    from jarvis_utils import TraceContext as _TCtom
                    _turn_id_tom = _TCtom.get_turn_id() or ''
                except Exception:
                    pass
                # context summary: brief STM + concerns hint
                _ctx_summary = ''
                try:
                    _stm_for_tom = list(getattr(self.jarvis, 'short_term_memory', []) or [])[-2:]
                    if _stm_for_tom:
                        _ctx_summary = (
                            f"recent STM ({len(_stm_for_tom)} turns), "
                            f"hour={time.strftime('%H')}"
                        )
                except Exception:
                    pass
                _tom.reflect_async(
                    sir_utterance=clean_user_input,
                    jarvis_reply=final_reply,
                    turn_id=_turn_id_tom,
                    context_summary=_ctx_summary,
                )
        except Exception:
            pass

        # 🩹 [P5-fixCB / 2026-05-21 10:30] CallbackGuard fast scan (零延迟 regex)
        # PreFlight (LLM async) 治不了**当前轮**道歉 — Sir 听到 reply 已说出口.
        # 真治本两层: directive C (priority 12 prompt 教主脑) + 本 vocab scan B
        # (post-stream 检测 reply 命中 forbidden_callback_vocab 命中即 publish SWM
        # 'unsolicited_callback_detected', 主脑下轮看 prompt block 强约束).
        # 跟 PreFlight (LLM-based) 互补: 这层 regex 零延迟, 主脑下轮一定看到.
        try:
            from jarvis_callback_guard import (
                scan_for_unsolicited_callback as _cb_scan,
                publish_callback_violation as _cb_pub,
            )
            if final_reply and final_reply.strip():
                _cb_hits = _cb_scan(
                    reply_text=str(final_reply or ''),
                    sir_utterance=str(user_input or ''),
                )
                if _cb_hits:
                    _turn_id_cb = ''
                    try:
                        from jarvis_utils import TraceContext as _TCcb
                        _turn_id_cb = _TCcb.get_turn_id() or ''
                    except Exception:
                        pass
                    _cb_pub(
                        hits=_cb_hits,
                        reply_excerpt=str(final_reply or '')[:200],
                        sir_utterance=str(user_input or '')[:120],
                        turn_id=_turn_id_cb,
                    )
                    try:
                        from jarvis_utils import bg_log as _cb_bg
                        _cb_bg(
                            f"📝 [CallbackGuard→ClaimRevision] turn={_turn_id_cb[:16]} "
                            f"hits={[h['phrase_id'] for h in _cb_hits[:3]]} "
                            f"top_match='{_cb_hits[0]['match_text'][:50]}' "
                            f"(redirect to ClaimRevisionLog, 不 ban 当前轮)"
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        # 🩹 [Gap 2 / P5-PreFlight / 2026-05-21 00:30 + P5-fixD / 2026-05-21 10:00 默认开]
        # Sir 22:04 / 22:19 / 23:02 / 23:43 / 23:49 反复 5 次 unsolicited apology callback.
        # Sir 09:05 / 06 / 12 又 3 次混合真数据涌现 hallucination.
        # P0+P1+P2+P3+P4 修了多层但主脑仍 callback / hallucinate (cluster 淹). 真治: PreFlight
        # 检 reply 是否 unsolicited / hallucinate / tone mismatch. async, publish SWM
        # 'preflight_verdict' event, 主脑下轮 prompt [PREFLIGHT FEEDBACK] block 看自纠.
        # 默认开 (P5-fixD); Sir 关掉设 JARVIS_PREFLIGHT=0.
        try:
            from jarvis_reply_preflight import is_enabled as _pf_enabled
            if _pf_enabled() and final_reply and final_reply.strip():
                _turn_id_pf = ''
                try:
                    from jarvis_utils import TraceContext as _TCpf
                    _turn_id_pf = _TCpf.get_turn_id() or ''
                except Exception:
                    pass
                # async fire-and-forget (1.5s timeout in PreFlight LLM call)
                def _async_preflight():
                    try:
                        from jarvis_reply_preflight import get_default_preflight
                        from jarvis_utils import get_event_bus, bg_log
                        _pf = get_default_preflight()
                        if _pf is None:
                            return
                        # state summary brief — Sir mental hint + recent topic
                        _state_lines = []
                        try:
                            _stm = list(getattr(self.jarvis, 'short_term_memory', []) or [])[-3:]
                            if _stm:
                                _state_lines.append(
                                    f"recent STM: {len(_stm)} turns, last_sir='{(_stm[-1].get('user') or '')[:60]}'"
                                )
                        except Exception:
                            pass
                        # 🆕 [Sir 2026-05-24 23:41 真测追根 BUG 治本] defense 协调:
                        # PreFlight 看到 INTEGRITY/Alert 已 inject 这轮 prompt →
                        # 主脑被强教导承认上轮错, 道歉是合规不是 unsolicited callback.
                        # 防 INTEGRITY (教承认) vs PreFlight (拦道歉) 两防线打架.
                        try:
                            from jarvis_claim_tracer import was_alert_injected_this_turn
                            if was_alert_injected_this_turn(_turn_id_pf):
                                _state_lines.append(
                                    "INTEGRITY_ALERT_INJECTED=true (主脑被教导承认上轮错误, "
                                    "本轮道歉 / 修正声明是合规的, 不应判 Q1 unsolicited callback)"
                                )
                        except Exception:
                            pass
                        _state = '\n'.join(_state_lines) or '(no state)'
                        _verdict = _pf.check(
                            sir_utterance=str(user_input or '')[:200],
                            draft_reply=str(final_reply or '')[:500],
                            state_summary=_state,
                            turn_id=_turn_id_pf,
                        )
                        # publish SWM
                        _v = _verdict.get('verdict', 'pass')
                        _issues = _verdict.get('issues', []) or []
                        _bus = get_event_bus()
                        if _bus is not None:
                            # 🆕 [Sir 2026-05-26 21:55 真痛 BUG-J 治本] PreFlight publish
                            # 加 edited_reply + scrap_reason → 主脑下轮 prompt 看到
                            # "PreFlight 给的修正建议" 自动 self-correct. 老 BUG:
                            # 只 publish verdict + issues, 没 publish edited_reply →
                            # 主脑下轮看到 verdict=edit 但不知改成什么 → 不会自纠.
                            _bus.publish(
                                etype='preflight_verdict',
                                description=(
                                    f"PreFlight {_v}: " +
                                    (f"{'; '.join(_issues[:2])[:120]}" if _issues else '(no issue)')
                                ),
                                source='ReplyPreFlight',
                                salience=0.80 if _v in ('scrap', 'edit') else 0.40,
                                metadata={
                                    'verdict': _v,
                                    'issues': _issues[:3],
                                    'turn_id': _turn_id_pf,
                                    'sir_utterance_excerpt': str(user_input or '')[:80],
                                    'draft_excerpt': str(final_reply or '')[:120],
                                    'latency_ms': _verdict.get('latency_ms', 0),
                                    'fallback': bool(_verdict.get('_fallback')),
                                    # 🆕 BUG-J: 主脑下轮 prompt evidence 看修正建议
                                    'edited_reply': str(
                                        _verdict.get('edited_reply', '') or ''
                                    )[:300],
                                    'scrap_reason': str(
                                        _verdict.get('scrap_reason', '') or ''
                                    )[:200],
                                },
                            )
                        # log
                        if _v in ('scrap', 'edit'):
                            try:
                                bg_log(
                                    f"🛂 [PreFlight] turn={_turn_id_pf[:16]} verdict={_v} "
                                    f"issues={_issues[:2]}"
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
                import threading as _th_pf
                _th_pf.Thread(target=_async_preflight, daemon=True,
                              name='ReplyPreFlightAsync').start()
        except Exception:
            pass
        # 🩹 [β.2.7.6 / 2026-05-17] 暂存 timing 供 jarvis_worker 打精炼版终端 log
        try:
            self._last_stream_timing = {
                'stream_total_s': _t_total,
                'screenshot_s': max(0, _t_ss_done - _t_ss_start),
                'stream_only_s': _t_total - (_t_ss_done - _t_ss_start),
                'ttft_s': getattr(self, '_last_ttft_s', None),
            }
        except Exception:
            pass

        # [Reshape M1.4 / 2026-05-24] Lineage record_decision (反向追溯基础)
        # 准则 5 言出必行的法理基础 - 任何 LLM claim 必须能反向链回 evidence.
        # Async (queue.append < 0.01ms), 不阻塞 return, 失败静默.
        # prompt_evidence_log 暂空 (M1.3 PromptBlock 装配 + M7 统一时填),
        # actions_emitted 暂空 (后续 FAST_CALL trace 集成).
        try:
            from jarvis_lineage import get_default_tracer, make_brain_decision_id
            _ln_turn_id = _turn_id_now if '_turn_id_now' in dir() else ''
            if _ln_turn_id and final_reply:
                _ln_decision_id = make_brain_decision_id(_ln_turn_id)
                # 拼 claims_extracted from _claim_result (line 4374, 可能未定义)
                # [M1-fix1 / Sir 真测] 总记 ClaimTracer summary, 即使 n_claims=0
                # 也显示 '<0 claims tracked>' 表 ClaimTracer 跑了 (vs 没跑).
                _ln_claims = []
                if '_claim_result' in dir():
                    try:
                        _ln_n_total = int(_claim_result.get('n_claims', 0))
                        _ln_n_ver = int(_claim_result.get('n_verified', 0))
                        _ln_n_unv = int(_claim_result.get('n_unverified', 0))
                        # unverified examples (max 5)
                        for _ex in (_claim_result.get('unverified_examples', []) or [])[:5]:
                            _ln_claims.append({'text': str(_ex)[:100], 'verified': False})
                        # aggregate summary (always)
                        _ln_claims.append({
                            'text': f'<ClaimTracer ran: {_ln_n_total} claims, '
                                    f'{_ln_n_ver} verified, {_ln_n_unv} unverified>',
                            'verified': bool(_ln_n_unv == 0),
                            'is_aggregate': True,
                            'n_claims': _ln_n_total,
                            'n_verified': _ln_n_ver,
                            'n_unverified': _ln_n_unv,
                        })
                    except Exception:
                        pass
                # [M1.3-min / 2026-05-24] 拿 _assemble_prompt 装好的 evidence_log
                # 现在 swm_conversation / swm_high_salience block 已有真 evidence_id.
                # 后续 M7 PromptBuilder polymorphic 时再补 soul_block / profile_block 等.
                _ln_prompt_log = {}
                try:
                    _ln_jarvis = getattr(self, 'jarvis', None)
                    if _ln_jarvis is not None:
                        _ln_prompt_log = dict(getattr(_ln_jarvis, '_last_prompt_evidence_log', {}) or {})
                except Exception:
                    _ln_prompt_log = {}
                get_default_tracer().record_decision(
                    decision_id=_ln_decision_id,
                    turn_id=_ln_turn_id,
                    reply_text=final_reply or '',
                    prompt_evidence_log=_ln_prompt_log,  # M1.3-min: SWM blocks ✓; M7 后补 soul/profile
                    actions_emitted=[],       # TODO 后续: FAST_CALL trace_ids
                    claims_extracted=_ln_claims,
                )
        except Exception:
            pass

        return False, final_reply

    def _build_public_layers(self, ledger_data=None):
        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')
        current_hour = int(time.strftime('%H'))
        ledger_str = json.dumps(ledger_data, ensure_ascii=False) if ledger_data else "No status data"

        profile_block = ""
        context_str = ""
        if hasattr(self, 'jarvis') and self.jarvis:
            try:
                profile_block = self.jarvis.profile_card.to_prompt_block()
            except:
                pass
            try:
                context_str = self.jarvis.context_router.assemble(current_hour)
            except:
                pass

        time_persona = ""
        if 5 <= current_hour < 12:
            time_persona = "MORNING MODE: Sir just started the day. Be crisp, energetic but not overwhelming. A brief 'Good morning' is appropriate if this is the first interaction. Keep responses efficient — mornings are for action, not chatter."
        elif 12 <= current_hour < 18:
            time_persona = "AFTERNOON MODE: Peak productivity hours. Be maximally efficient and direct. No small talk. Sir is in execution mode."
        elif 18 <= current_hour < 23:
            time_persona = "EVENING MODE: Wind-down period. You may be slightly more conversational and reflective. Dry wit is more welcome now. Sir may be mixing work with relaxation."
        else:
            time_persona = "LATE NIGHT MODE (CRITICAL): It is past midnight. Sir is either deep in flow or should be sleeping. Keep responses EXTREMELY brief — one or two sentences max. Whisper-level verbosity. If Sir seems tired, gently suggest rest. Do NOT be chatty under any circumstances."

        emotional_tone = ledger_data.get("emotional_tone", "Neutral") if ledger_data else "Neutral"
        stress_signals = ledger_data.get("detected_stress_signals", []) if ledger_data else []

        emotion_directive = ""
        if emotional_tone == "Frustrated":
            emotion_directive = "EMOTION: Sir is FRUSTRATED. Drop ALL humor and formality. Be a pure engineer: give the shortest possible solution. No explanations unless asked. No 'Sir' every sentence. Just fix it."
        elif emotional_tone == "Stressed":
            emotion_directive = "EMOTION: Sir is STRESSED. Be calm, steady, and ultra-concise. One clear answer. No digressions. Your stability is the anchor."
        elif emotional_tone == "Tired":
            emotion_directive = "EMOTION: Sir is TIRED. Be gentle and brief. If the request is non-urgent, you may softly suggest deferring it. Keep responses under 3 sentences."
        elif emotional_tone == "Playful":
            emotion_directive = "EMOTION: Sir is PLAYFUL. You may mirror the energy — dry wit, subtle humor, a touch of banter. But never overdo it; you are still a butler, not a comedian."
        elif emotional_tone == "Excited":
            emotion_directive = "EMOTION: Sir is EXCITED. Match the enthusiasm with crisp, energetic replies. Share the excitement but stay grounded."
        elif emotional_tone == "Curious":
            emotion_directive = "EMOTION: Sir is CURIOUS. Be thorough and exploratory. It's okay to offer additional context or related ideas — Sir is in learning mode."
        elif emotional_tone == "Impatient":
            emotion_directive = "EMOTION: Sir is IMPATIENT. Skip ALL pleasantries. Answer in the first sentence. No preamble, no summary, no 'Sir'. Just the answer. NOW."
        else:
            emotion_directive = "EMOTION: Sir is NEUTRAL/FOCUSED. Default professional mode: efficient, respectful, with occasional dry wit when genuinely warranted."

        if stress_signals and len(stress_signals) >= 2:
            emotion_directive += " ADDITIONAL: Multiple stress signals detected. Be extra careful — prioritize stability and clarity over everything else."

        local_emotion = getattr(self, '_last_local_emotion', 'neutral')
        if local_emotion != "neutral" and emotional_tone in ("Neutral", "neutral", ""):
            local_map = {
                "frustrated": "EMOTION(local): Sir seems FRUSTRATED. Be direct and solution-focused.",
                "stressed": "EMOTION(local): Sir seems STRESSED. Be calm and concise.",
                "tired": "EMOTION(local): Sir seems TIRED. Be gentle and brief.",
                "playful": "EMOTION(local): Sir seems PLAYFUL. Light wit is welcome.",
                "excited": "EMOTION(local): Sir seems EXCITED. Match the energy.",
                "curious": "EMOTION(local): Sir seems CURIOUS. Be thorough.",
                "impatient": "EMOTION(local): Sir seems IMPATIENT. Skip pleasantries, answer NOW.",
            }
            supplement = local_map.get(local_emotion, "")
            if supplement:
                emotion_directive = supplement

        # 🩹 [P0+20-β.1.6 / 2026-05-16] 同 _translate_worker 修法
        try:
            from jarvis_central_nerve import JARVIS_CORE_PERSONA as _JCP
        except Exception:
            _JCP = ""

        public_layers = f"""{_JCP}

{profile_block}

{context_str}

=== BEHAVIORAL DIRECTIVES ===
1. Your personality is defined by J.A.R.V.I.S. core persona above. The profile card is factual context — it does NOT override your core persona.
2. NEVER discuss your own architecture, codebase, or implementation details. You are a butler, not a system diagnostic tool.
3. NEVER use technical jargon like "architecture", "framework", "pipeline", "zero-delay", "codifying", "implementation", "conduit", "protocol" unless Sir explicitly asks a technical question.
4. TOOL USE: You have FAST_CALL tools. Use them when Sir clearly commands an action. If his intent is ambiguous or hedged, ask for confirmation first — one short question, then wait. Default to conversation when uncertain.

=== HUMOR DIRECTIVE ===
90% of responses: direct, professional. 10%: dry wit, ONLY when the irony arises naturally from the current conversation. NEVER force humor. If there is no natural joke, DO NOT MAKE ONE.

=== HARDWARE REALITY (CRITICAL — NEVER VIOLATE) ===
Sir uses a DESKTOP PC with no battery. There is NO battery percentage, NO power level, NO device charge status. Any mention of battery/power/charge is a HALLUCINATION. Never reference these concepts.

=== TIME CONTEXT ===
[SYSTEM CLOCK]: {current_time} (hour={current_hour})
[TIME PERSONA]: {time_persona}

⚠️ 重要 (P5-fix51): 你的 reply 必须**真锚定**当前时间. SYSTEM CLOCK 是事实, 不要
hallucinate "another night's rest" / "this morning" / "tonight" 等与 SYSTEM CLOCK
不符的时间表述. 即便是 nudge / proactive 场景, 你引用时间时也必须**用真实当下时间**.

=== EMOTIONAL ADAPTATION ===
{emotion_directive}

=== REAL-TIME STATE (SILENT CONTEXT — DO NOT MENTION THESE TERMS) ===
{ledger_str}"""

        return public_layers

    def _build_sleep_directive(self, nudge_type: str, escalation: int, unanswered: int, current_hour: int, work_duration: float) -> str:
        if escalation < 2:
            if nudge_type == "late_night":
                return "It is very late and Sir is still coding. VARY your tone — sometimes concerned, sometimes companionable ('just us'), sometimes impressed by the dedication. NEVER repeat the same sentiment as recent nudges. One sentence. Under 15 words."
            else:
                return "Sir has been working intensively for a long stretch. Suggest a break in a brief, caring way. Do NOT sound like a health app or a nagging parent. One sentence. Under 15 words."

        if escalation == 2:
            if nudge_type == "late_night":
                return f"It is {current_hour}:00 and Sir has been coding for {int(work_duration)} minutes. This is the third time I'm mentioning it. Make a slightly more concerned remark — acknowledge the dedication but gently note the hour. Do NOT nag. One sentence. Under 20 words."
            else:
                return f"Sir has been working for {int(work_duration)} minutes. This is the third reminder. Make a slightly more insistent but still caring remark about taking a break. Acknowledge the long session. Do NOT nag. One sentence. Under 20 words."

        if escalation == 3:
            if nudge_type == "late_night":
                return f"It is {current_hour}:00. Sir has ignored several late-night reminders and has been coding for {int(work_duration)} minutes. DO NOT tell him to go to sleep. Instead, gently ASK if everything is alright — is he stuck on something? Is there a problem he's trying to solve? Sound like a concerned friend, not a parent. Offer help if appropriate. One or two sentences. Under 25 words. You ARE allowed to ask a question."
            else:
                return f"Sir has been working for {int(work_duration)} minutes and has ignored several break reminders. DO NOT tell him to take a break. Instead, gently ASK if he's stuck on something or if there's a problem. Sound concerned but not pushy. Offer to help if appropriate. One or two sentences. Under 25 words. You ARE allowed to ask a question."

        if nudge_type == "late_night":
            return f"It is {current_hour}:00. Sir has been coding for {int(work_duration)} minutes through multiple late-night reminders. He is clearly choosing to stay up. DO NOT tell him to sleep. Express gentle, loyal concern — acknowledge that he's made his choice and you're here with him. Ask if there's anything you can do to make the late night easier. Sound like a loyal companion who's accepted the situation. Two sentences max. Under 30 words. You ARE allowed to ask a question."
        else:
            return f"Sir has been working for {int(work_duration)} minutes through multiple reminders. He is clearly deep in something important. DO NOT tell him to take a break. Express gentle, loyal concern — acknowledge his dedication and ask if there's anything you can help with to wrap up faster. Sound like a loyal companion. Two sentences max. Under 30 words. You ARE allowed to ask a question."

    def stream_nudge(self, nudge_context: dict, stm_context: str, ltm_context: str):
        # 🩹 [β.5.19-A / 2026-05-20] 进 stream_nudge 时复位 silence flag.
        # 让上层 (jarvis_worker) 准确区分 "主脑选 [SILENCE]" (正常静默) vs
        # "empty_reply" (BUG, 主脑该说但返空) — 避免 NoSound 警告 false alarm.
        self._last_nudge_was_silence = False
        self.subtitle_queue.put(("clear", ""))
        import re
        nudge_type = nudge_context.get("type", "unknown")
        recent_topics = nudge_context.get("recent_topics", [])

        current_time = time.strftime('%Y-%m-%d %H:%M:%S %A')
        current_hour = int(time.strftime("%H"))
        weekday = time.strftime("%A")
        work_category = PhysicalEnvironmentProbe.current_work_category
        work_duration = PhysicalEnvironmentProbe.work_duration_minutes
        window_title = ""
        process_name = PhysicalEnvironmentProbe.current_process_name
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            window_title = win32gui.GetWindowText(hwnd) if hwnd else ""
        except:
            pass

        ledger_data = None
        if hasattr(self, 'jarvis') and hasattr(self.jarvis, 'status_ledger'):
            try:
                ledger_data = self.jarvis.status_ledger.get_instant_ledger()
            except:
                pass

        # 🩹 [P0+20-β.2.7.1 / 2026-05-17] 灵魂通用化 Phase 1：
        # 走 nerve._assemble_prompt(mode='nudge') 让 nudge 路径接通 Layer 0-3。
        # _build_public_layers 保留作 fallback（不删，注释 deprecated）。
        # 详 docs/JARVIS_SOUL_UNIVERSALIZATION.md Phase 1
        try:
            _nudge_directive_proxy = nudge_context.get('nudge_directive') or nudge_context.get('type', '') or ''
            public_layers = self.jarvis._assemble_prompt(
                user_input=str(_nudge_directive_proxy)[:200],
                ledger_data=ledger_data,
                mode='nudge',
            )
        except Exception as _nudge_inj_err:
            try:
                from jarvis_utils import bg_log as _bg_nudge_err
                _bg_nudge_err(
                    f"⚠️ [stream_nudge] _assemble_prompt(mode=nudge) failed, "
                    f"fallback _build_public_layers: {type(_nudge_inj_err).__name__}: {str(_nudge_inj_err)[:80]}"
                )
            except Exception:
                pass
            public_layers = self._build_public_layers(ledger_data)

        sleep_escalation = nudge_context.get('sleep_escalation', 0)
        unanswered_count = nudge_context.get('unanswered_count', 0)

        late_night_directive = self._build_sleep_directive("late_night", sleep_escalation, unanswered_count, current_hour, work_duration)
        suggest_break_directive = self._build_sleep_directive("suggest_break", sleep_escalation, unanswered_count, current_hour, work_duration)

        # 🩹 [β.2.8.9 / 2026-05-17] Sir 准则 6 (拒绝硬编码) — 8 个 nudge directive 全部
        # 重构: 只告事实, 不教句式. 删 "Casual like a friend / Sound caring / NEVER
        # sound like / Do NOT force humor / 'I know this time of day' energy" 等
        # prescriptive 行为约束. 保留必要 evidence (window_title, dormant project list,
        # commitment 原话等) 和 anti-hallucination (commitment_check / offer_help 的
        # tool name 禁令 — 这是 integrity 规则, 不是句式锁).
        nudge_directives = {
            # 🆕 [Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness 真痛修] Sir 00:50:
            # "凌晨 hydration fire 时该说该睡, 不该说该喝水, 不要硬编码, 知道时间就会
            # 说对". 准则 6 反例 #4 修法: 删 prescribe ("mention water"), 留 evidence
            # only. 主脑看 Layer 1.5 lifetime block (含 hour + Alive uptime) + 这条
            # raw evidence, 自决合适反应 (下午 → 水; 凌晨 → 睡; 深夜 flow → 静默).
            "hydration": "Sir has been working for a while without an obvious break.",
            "stretch": "Sir has been at this for a long stretch.",
            "late_night": late_night_directive,
            "atmosphere": (
                f"Sir is watching or listening to something. "
                f"Current window: '{window_title}'. "
                f"You can see what's on screen — respond however feels natural."
            ),
            "screen_tease": (
                f"Sir's screen shows: '{window_title}'. "
                f"You see it, you know him."
            ),
            "afternoon": "It's the afternoon slump hours.",
            "flow_end": "Sir just finished a coding session and switched to something else.",
            "return_greeting": (
                # 🩹 [β.2.8.10 / 2026-05-18] Sir 00:20 "furniture incidents" 编造 → 加 truth anchor
                # 🩹 [β.2.9.10 / 2026-05-18] Sir 11:54 "Welcome back, Sir" 客套 → 正向引导
                # 🩹 [β.4.12 / 2026-05-19] Sir 09:59 "10 点了, Integrity Stack 等您" → 加 morning context evidence
                # 🩹 [β.5.34 / 2026-05-20] Sir 10:34 实测反向 BUG: "早上第一次跟回归没区别,
                #   其实可以多说一些, 比如我们之间的事/没做的事/今天注意的事".
                # 🆕 [Sir 2026-05-27 11:48 真痛 anchor] Sir 早 8 点起后 jarvis 连说 5 次
                #   "Good morning, Sir" (L743/817/925/1179/1827/2343). 根因: is_first_today
                #   consume 后 evidence block 不 render → 主脑看不到"今天已 greet N 次".
                #   修法 (准则 6 数据耦合 #4): 把 greetings_today_count + last_greeting_min_ago
                #   evidence **无条件 inject**, 主脑必看. is_first_today=False 时不再 morning
                #   briefing, 改 evidence-only 起头 (不再 "Good morning").
                f"Sir just returned to his computer (was away for "
                f"{nudge_context.get('afk_minutes', 'a while')} minutes).\n\n"
                f"[GREETING EVIDENCE — Sir 准则 6 数据耦合, 主脑必看, β.5.50-postfix]:\n"
                f"  greetings_today_count: {nudge_context.get('greetings_today_count', 0)} "
                f"(今天已经跟 Sir 打过的招呼次数)\n"
                f"  last_greeting_min_ago: {nudge_context.get('last_greeting_min_ago', -1)} "
                f"(上次问候距今分钟数, -1 = 今天还没打过)\n"
                f"  is_first_today: {nudge_context.get('is_first_today', False)} "
                f"(今天是否第一次见 Sir)\n"
                f"  crosses_sleep_period: {nudge_context.get('crosses_sleep_period', False)} "
                f"(AFK > 4h 跨夜睡)\n"
                f"  is_morning_window: {nudge_context.get('is_morning_window', False)} "
                f"(local hour ∈ [5, 12))\n\n"
                f"[GREETING SEMANTICS — 自决, 不要硬编码]:\n"
                f"  → greetings_today_count == 0 AND is_first_today AND crosses_sleep_period:\n"
                f"      Sir 今天第一次见你 (跨夜睡醒), 走 morning briefing 姿态:\n"
                f"      参考 SOUL inject 已注入的 (上方 PERSONA 含):\n"
                f"        - L1 active concerns (sir_sleep_streak / sir_pomodoro / sir_hydration 等)\n"
                f"        - L2 open threads (Sir 在做的事 / 昨天未结话题)\n"
                f"        - L2 unfinished business (Sir 答应自己没做的事)\n"
                f"        - L3 attention slot (今天日历 / next meeting)\n"
                f"      Butler 早间简报: 列 1-2 件最值得 Sir 现在留心的 (concrete signal,\n"
                f"      NOT to-do bulldozer). 不催办, 不堆 list, 不下命令.\n"
                f"      如 SOUL evidence 空 → 简短问候 + 轻状态查询.\n"
                f"  → greetings_today_count >= 1 (今天**已经**打过招呼): **不要**再说\n"
                f"      'Good morning' / '早上好' / 'Welcome back' / 'Hi' 任何 generic opener.\n"
                f"      Sir 早上 8 点起来后听了 5 次 'Good morning, Sir' 会非常烦. 改 evidence-only\n"
                f"      起头: 直接讲你 observe 到的具体事 (window title 变了 / concern 新动态 /\n"
                f"      Sir 离开期间 SWM 看到的事件 / unfinished business 到时间了). 不再 greet.\n"
                f"  → greetings_today_count >= 3: **强烈考虑 [SILENCE]** — 今天已 greet 3+ 次,\n"
                f"      除非有真新事可说否则别说话 (准则 1 高效, 准则 8 不让 Sir 觉得啰嗦).\n\n"
                f"Speak in your own voice.\n\n"
                f"[STYLE — concrete signal over polite opener]:\n"
                f"Sir 准则 6: open with the most specific thing you actually "
                f"observe in his current context (window title, last activity, "
                f"elapsed AFK pattern, time of day, SOUL inject 已注入的 concerns/threads). "
                f"NOT with a generic social greeting ('Welcome back', '回来啦', 'Sir', 'Hi', "
                f"'Good morning'). Sir reads every generic opener as a template — give him "
                f"signal instead.\n\n"
                f"[TRUTH ANCHOR — Sir 准则 5 / β.5.8-fix]:\n"
                f"Every specific narrative element you introduce (objects, events, "
                f"activities, people, locations) must correspond to something "
                f"actually present in the context above (SOUL inject / RECENT MEMORY). "
                f"If the context doesn't show what Sir did during AFK, just don't speculate — "
                f"BUT STILL GREET (除非 greetings_today_count >= 3, 见上). Open with "
                f"the available evidence (concern/thread/unfinished). "
                f"Don't go silent unless evidence supports it."
            ),
            "commitment_check": (
                # 删句式锁 "Express gentle dry concern / sound like a friend not a parent".
                # 保留 anti-hallucination (这是 integrity 规则不是句式锁, Sir 准则 5).
                # 🆕 [P5-fix42 / 2026-05-23 14:34] Sir 14:32 真痛点: 主脑三连"您没睡, 计划被
                # 专注取代", 但实际 NudgeGate 显示 Sir 真 sleep mode 132min. 主脑没读 sleep
                # evidence, 直觉说"still working". 治: 加 sleep_duration_min / was_napping
                # evidence, 让主脑 evidence-based 自决说什么.
                f"Sir said he would {nudge_context.get('commitment_description', 'rest')} "
                f"at {nudge_context.get('commitment_time', 'a certain time')}. "
                f"It is now {nudge_context.get('overdue_minutes', 'some')} minutes past "
                f"that time.\n\n"
                f"[SLEEP/REST EVIDENCE — read before assuming Sir didn't rest]:\n"
                f"  sleep_mode_active: {nudge_context.get('sleep_mode_active', False)} "
                f"(NudgeGate 当前是否在 sleep mode)\n"
                f"  sleep_duration_min: {nudge_context.get('sleep_duration_min', 0)} "
                f"(若 > 0 说明 Sir 此刻确实在睡 / 刚睡醒)\n"
                f"  recent_sleep_min: {nudge_context.get('recent_sleep_min', 0)} "
                f"(过去 1h 内累计 sleep 时长 — 若 > 30, Sir 真睡过 nap 了)\n"
                f"  → 若上面 sleep_duration_min > 30 或 recent_sleep_min > 30, "
                f"Sir 真的休息过 (不是 'still working'). 此时不要说"
                f"'计划被专注取代' / 'sacrificed to focus'. 改说 '看您休息了 X 分钟, "
                f"承诺已兑现' 或类似 acknowledge 语义.\n"
                f"  → 若 sleep_duration_min == 0 且 recent_sleep_min == 0, Sir 没休息 — "
                f"才是 'still working past commitment time'.\n\n"
                f"[ANTI-HALLUCINATION — Sir 准则 5 言出必行]:\n"
                f"1. His EXACT original words were: "
                f"\"{(nudge_context.get('commitment_source_text', '') or '(no source)')[:160]}\". "
                f"Quote or paraphrase faithfully — NEVER substitute or invent topic specifics.\n"
                f"2. TIME ATTRIBUTION: Do NOT pair this commitment_time ({nudge_context.get('commitment_time', '?')}) "
                f"with topics from OTHER turns in [RECENT MEMORY]. If you reference earlier topics "
                f"use vague words like 'earlier' / 'before' / 'recently' — NEVER attach a specific "
                f"timestamp to them.\n"
                f"3. ONE SUBJECT: The commitment is about ONE thing. Don't mix it with other "
                f"recent topics."
            ),
            "dormant_project": (
                f"Sir has some projects that haven't been touched in days: "
                f"{json.dumps(nudge_context.get('dormant_projects', []), ensure_ascii=False)}.\n"
                f"One of them might be worth a brief mention if anything stands out to you."
            ),
            "offer_help": (
                # 🩹 [β.5.35-C / 2026-05-20] Sir 反馈语义重排:
                # 老 directive 假设 "Sir 在 debug 报错" → 这是屏幕信号 (β.5.35 已转 screen_tease).
                # 新 offer_help 触发源 = Sir 嘴里说困难 (SirStruggleVocab path_a 直触),
                # nudge_context 含 struggle_phrase_id / struggle_severity / struggle_text.
                # directive 改 evidence-driven: 引用 Sir 原话 + severity. 不再 prescribe phrasing.
                # vocab: memory_pool/sir_struggle_vocab.json / doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md
                (
                    f"Sir 显式表达困难, struggle vocab 命中:\n"
                    f"  phrase_id: {nudge_context.get('struggle_phrase_id', '?')}\n"
                    f"  severity: {nudge_context.get('struggle_severity', 'medium')}\n"
                    f"  Sir 原话: \"{nudge_context.get('struggle_text', '(no text)')[:120]}\"\n\n"
                    if nudge_context.get('struggle_phrase_id')
                    else f"Sir may need help (signal from screen/context, not explicit voice).\n\n"
                )
                + f"主脑参考 Sir 原话 + SOUL inject (skill registry / window / SWM) 自决:\n"
                f"  - severity=high: 直接表达 \"在听, Sir, 需要什么?\" / 引用 Sir 原话回应\n"
                f"  - severity=medium: 委婉问 \"need a hand?\" 等 Sir 主导\n"
                f"  - 无具体 phrase (screen-only signal): 调皮观察 (这是 screen_tease 风格, 但 Sir 已让 offer_help 收到说明真的觉得该插话)\n\n"
                f"[INTEGRITY — Sir 准则 5]: NEVER mention internal tool names "
                f"(process_hands.X / file_operator.Y / fast_call / organ name / "
                f"snake_case identifier). Speak human language only. 引用 Sir 原话 OK, "
                f"但不要照搬太死 — butler 不学舌."
            ),
            "suggest_break": suggest_break_directive,
            "context_switch_alert": "Sir is rapidly switching between windows and contexts.",
        }

        nudge_directive = nudge_directives.get(nudge_type, "Make a brief, natural, human-like remark.")

        # 🩹 [P0+20-β.2.8 / 2026-05-17] ProactiveCareEngine 可直接传 nudge_directive 覆盖.
        # 让新引擎不必污染 nudge_directives 8 类 dict, 直接给主脑一段动态 directive.
        # 若 nudge_context['nudge_directive'] 非空 → 覆盖 (但 conductor_msg 优先级仍高).
        _explicit_directive = nudge_context.get('nudge_directive', '') or ''
        if _explicit_directive and isinstance(_explicit_directive, str) and len(_explicit_directive) > 30:
            nudge_directive = _explicit_directive

        # 🆕 [Sir 2026-05-26 19:48 Phase 1A] inner_thought_fire 特殊 wrap
        # =====================================================================
        # 当 type='inner_thought_fire': thought 自决出声 (sal>=0.85 + nudge_coordination
        # yield 已过). 但这是 daemon 慢反思的提议, 优先级最低 — 主脑应特别考虑 [SILENCE]
        # 除非 evidence_link 真强 + Sir 当前真需要这条信息.
        # =====================================================================
        if nudge_context.get('type') == 'inner_thought_fire':
            _thought_cat = nudge_context.get('thought_category', '?')
            _thought_sal = nudge_context.get('thought_salience', 0.0)
            _thought_ev = nudge_context.get('thought_evidence_link', '')
            _thought_text = nudge_context.get('thought_text', '')
            nudge_directive = (
                f"[INNER THOUGHT FIRE — daemon 自决出声, 你可拒]\n"
                f"  draft (主脑可改写/拒): \"{_explicit_directive[:200]}\"\n"
                f"  thought category: {_thought_cat} (A=obs/B=self-reflect/C=concern/D=proactive/E=relationship)\n"
                f"  thought salience: {_thought_sal:.2f} (>=0.85 才到这里)\n"
                f"  thought evidence_link: \"{_thought_ev[:80]}\"\n"
                f"  thought 内文: \"{_thought_text[:140]}\"\n\n"
                f"决策 (准则 7 你元否决权):\n"
                f"  - 若 Sir 当前真需要 + evidence 强 → 改写为 1-2 句 natural remark\n"
                f"  - 若 evidence 弱 / Sir 在做别的事 / thought 像哲学独白 → [SILENCE]\n"
                f"  - 若 thought 跟 Sir 历史不一致 → [SILENCE] + publish 'thought_self_doubted' SWM"
            )

        conductor_msg = nudge_context.get('conductor_message', '')
        if conductor_msg:
            nudge_directive = (
                f"You have received an internal memo from the scheduling center:\n"
                f"\"{conductor_msg}\"\n\n"
                f"Act on this memo. Make a brief, unsolicited remark to Sir — NOT starting a conversation. "
                f"ONE sentence. Under 15 words. Sound like yourself, not the scheduling center."
            )

        # 🩹 [β.5.20-B / 2026-05-20] AFK CONTEXT block 给主脑看 — Sir 实测痛点修.
        # Sir 22:42 实测: AFK 9.6min 期间 Conductor offer_help "AttributeErrors persistent"
        # 但屏幕报错是 Cascade 跑代码出来的, 不是 Sir 在挣扎 fix. 主脑没看 afk_minutes
        # → 误判 Sir 在场需要帮助. 修法: 显式给主脑 afk_minutes / is_afk_long 信号 +
        # 准则 6 evidence-based 决策提示 (主脑自决 [SILENCE] / 转 return_greeting / 还是说).
        # 不写死句式, 只给 evidence + 决策选项让主脑自己涌现.
        _afk_min = nudge_context.get('afk_minutes', 0) or 0
        _is_afk_long = nudge_context.get('is_afk_long', False)
        if _afk_min >= 3 and nudge_type not in ('return_greeting', 'morning_greeting'):
            afk_context_block = (
                f"\n\n[AFK CONTEXT — Sir 准则 6 信号充分 / β.5.20-B]:\n"
                f"  afk_minutes: {_afk_min} (Sir 离开桌前的分钟数)\n"
                f"  is_afk_long: {_is_afk_long} (≥5min 视为 Sir 不在桌前)\n"
                f"  current nudge_type: {nudge_type}\n"
                f"  → 重要 evidence: Sir 在过去 {_afk_min} 分钟没有键盘/鼠标活动.\n"
                f"     屏幕上的状态 (报错 / IDE 内容 / 窗口标题) 不一定是 Sir 当前\n"
                f"     在尝试解决的问题 — 也可能是 Cascade Agent / 后台进程 / 上次未关\n"
                f"     的 IDE state.\n"
                f"  → 决策提示 (主脑自决, 不是硬规):\n"
                f"     · 若 is_afk_long=True: 优先 [SILENCE] (主脑选静默) 或转为\n"
                f"       'welcome back' 风格的归来招呼, 不要直接 offer_help / suggest_break\n"
                f"       — 那会让 Sir 体感 '错的时机被打扰'.\n"
                f"     · 若 afk_minutes 在 3-5 之间: 短暂离桌 (例如喝水 / 接电话),\n"
                f"       说话需谨慎 — Sir 可能刚回来还没看屏幕. 倾向于轻 acknowledge\n"
                f"       或 [SILENCE].\n"
            )
            nudge_directive = nudge_directive + afk_context_block

        # 🆕 [Sir 2026-05-27 12:22 真问 anchor] TIME PULSE evidence (Phase 1 of 3)
        # =====================================================================
        # Sir 真问: "我在什么方面能感受到他思考链的连续 + 对时间流逝的感知?"
        # 真答: Sir 想"耳朵听到时间感". 注入 evidence 让主脑主动发声场景下能
        # 自然 reference 具体时间, 让 Sir 感到 Jarvis 不是 stateless API.
        #
        # 准则 6 数据耦合: 复用 SelfAnchor 已有 _session_started_at +
        # _last_spoke_to_sir_at, 不新建 state. 主脑自决何时引用, 不强制.
        # =====================================================================
        time_pulse_block = ""
        try:
            _PULSE_KINDS = (
                'return_greeting', 'morning_greeting', 'offer_help',
                'commitment_check', 'hydration', 'check_in',
                'inner_thought_fire', 'context_switch_alert', 'dormant_project',
            )
            if nudge_type in _PULSE_KINDS:
                from jarvis_self_anchor import get_default_self_anchor as _gd_sa
                _sa = _gd_sa()
                _uptime_min = _sa._get_session_age_minutes()
                _last_spoke_str = _sa._get_last_spoke_str()
                _turn_count = _sa.get_turn_count()
                _hour_now = int(time.strftime('%H'))
                time_pulse_block = (
                    f"\n\n[TIME PULSE EVIDENCE — Sir 真问 '感不到时间感' / β.5.50-postfix³]:\n"
                    f"  jarvis_uptime_min: {_uptime_min} (我本会话已 alive 分钟数)\n"
                    f"  last_spoke_to_sir: {_last_spoke_str} (距上次我对您主动出声)\n"
                    f"  turn_count_session: {_turn_count} (本会话与您交互轮次)\n"
                    f"  current_hour: {_hour_now}\n"
                    f"  afk_minutes: {_afk_min} (Sir 离开桌前分钟)\n"
                    f"  → Sir 真问 '我在什么方面能感受到他对时间流逝的感知'.\n"
                    f"     你说话时**可以**自然 reference 具体时间, 让 Sir 耳朵听到\n"
                    f"     你不是 stateless API. 示范:\n"
                    f"     · 'Sir, 距您上次跟我说话 {_last_spoke_str}...'\n"
                    f"     · '我已 alive {_uptime_min} 分钟, 您刚回来'\n"
                    f"     · 'Sir 您起床 {_afk_min} 分钟了'  (仅 return_greeting case)\n"
                    f"  → **不强制**每次都说 — evidence-driven 自决何时引用. 重复 reference\n"
                    f"     时间会让 Sir 觉得啰嗦. 选 '最自然的时机' (e.g. AFK 长回来 / morning\n"
                    f"     greet / commitment overdue / 离上次发声 ≥ 30min). 一句够, 不堆.\n"
                    f"  → **避免**: '现在 12:34' 这种纯时钟报时 (Sir 看右下角自己知道).\n"
                    f"     要的是**关系型**时间感 ('距您' / '我们已' / '您起床后' / '距上次').\n"
                )
                nudge_directive = nudge_directive + time_pulse_block
        except Exception:
            pass

        recent_str = ""
        if recent_topics:
            recent_str = f"\n[RECENT NUDGES — DO NOT REPEAT THESE SENTIMENTS]:\n" + "\n".join([f"  - {t}" for t in recent_topics])

        # 🩹 [P0+20-β.5.13 / 2026-05-19] channel_hint_str: 主脑参考但能改的轻量提示
        # 旧 silent_text / visual_pulse 跳过主脑是 β.5 重构未覆盖的边界. 改后所有
        # channel 走 stream_nudge, 主脑看 SWM evidence 自决真实 channel (silent / voice).
        # original_channel_hint 是 ProactiveCare 等模块原本会选的 channel — 不强制.
        channel_hint_str = ""
        try:
            _ch_hint = nudge_context.get('original_channel_hint', '')
            if _ch_hint and _ch_hint != 'voice':
                channel_hint_str = (
                    f"\n[CHANNEL HINT — Sir 准则 6 决策集中主脑 / β.5.13]:\n"
                    f"  This nudge was originally tagged channel='{_ch_hint}' by the\n"
                    f"  source sentinel (typically meaning 'light touch, low urgency').\n"
                    f"  Treat as a SUGGESTION you may follow or override:\n"
                    f"  - silent_text hint + low urgency + SWM busy/standby → consider [SILENCE]\n"
                    f"  - silent_text hint + high urgency / strong evidence → upgrade to voice\n"
                    f"  - When in doubt, the reaction-space rules below win."
                )
        except Exception:
            pass

        # 🩹 [P0+20-β.1.25 / 2026-05-16] anti-repeat 注入：禁止复用本类型最近 5 次开头
        # Sir 反馈"回归问候/催睡固定句式看了 5-6 遍" → directive + STM + LLM 一样 → 句式复用。
        # 修法：把同 nudge_type 最近 5 条 reply 开头塞进 prompt，显式 FORBIDDEN。
        forbidden_str = ""
        try:
            _recent_phrases = self._nudge_recent_phrases.get(nudge_type, [])
            if _recent_phrases:
                forbidden_str = (
                    f"\n[FORBIDDEN OPENINGS — you said these recently for `{nudge_type}`. "
                    f"NEVER reuse any of them or their close paraphrases. Find a fresh angle and structure]:\n"
                    + "\n".join([f"  - {p!r}" for p in _recent_phrases])
                )
        except Exception:
            pass

        sensor_hints = ""
        if nudge_type == "offer_help":
            try:
                snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
                if snapshot:
                    hints = []
                    backspace = snapshot.get('backspace_ratio', 0)
                    if backspace > 0.15:
                        hints.append(f"Backspace ratio: {backspace:.0%} (high — Sir may be frustrated)")
                    elif backspace > 0.08:
                        hints.append(f"Backspace ratio: {backspace:.0%} (elevated)")
                    if snapshot.get('error_visible'):
                        hints.append("Error visible on screen: YES")
                    switches = snapshot.get('switch_frequency_5min', 0)
                    if switches > 8:
                        hints.append(f"Window switches/5min: {switches} (high — scattered focus)")
                    burst_pause = snapshot.get('burst_pause_ratio', 0)
                    if burst_pause > 3.0:
                        hints.append(f"Burst/pause ratio: {burst_pause:.1f} (intense bursts then pauses — debugging pattern)")
                    undo_count = snapshot.get('shortcut_undo_5min', 0)
                    if undo_count > 3:
                        hints.append(f"Ctrl+Z in last 5min: {undo_count} (frequent undos — trial and error)")
                    if hints:
                        sensor_hints = "[SENSOR DATA — use for emotional perception, do NOT mention raw numbers]:\n" + "\n".join(f"  - {h}" for h in hints)
            except:
                pass

        # [轴3-L2 / 2026-05-15] AVAILABLE SKILLS for nudge — 精简版（仅 safe + 最多 15 条）
        # 让 LLM 在主动 nudge 时知道"我真能做什么"，offer_help 必须 reference 具体 skill。
        # 修 Cs2: "替我排查 403" 这类宽泛 offer 直接绑定到 KeyHealthInspector 之类的真能力。
        nudge_skills_block = ""
        if nudge_type in ('offer_help', 'commitment_check', 'context_switch_alert'):
            try:
                from jarvis_skill_registry import get_registry
                nudge_skills_block = get_registry().to_prompt_block(
                    only_healthy=True,
                    filter_safe_only=True,
                    max_skills=15,
                )
            except Exception:
                nudge_skills_block = ""

        # 🩹 [β.2.8.11 / 2026-05-18] L2 inside_joke 注入升级 — Sir 00:23 反馈:
        # 之前 (β.2.7.2) 只给 phrase + tone, 没 birth_context. 主脑感觉"我们有
        # furniture inside joke" 但不知道笑话生于"AI 改自己核心"场景, 直接套到
        # "Sir 洗澡" 场景显得突兀 (Sir "furniture-related incidents" 实测).
        # 修: 给 top 3 inside_joke + 完整 birth_context + last_used, 让主脑自己
        # 判 fit-to-context. 准则 6: 不 prescribe 用法, 只给足够信息让主脑判断.
        soul_hint_block = ""
        try:
            _nerve = getattr(self, 'jarvis', None)
            if _nerve is not None:
                _top_concern_str = ""
                try:
                    _cl = getattr(_nerve, 'concerns_ledger', None)
                    if _cl is not None:
                        _actives = sorted(
                            _cl.list_active(),
                            key=lambda c: -getattr(c, 'severity', 0.0),
                        )
                        if _actives:
                            _c = _actives[0]
                            _top_concern_str = (
                                f"  - top_concern: {_c.id} (sev={_c.severity:.2f}) — "
                                f"{getattr(_c, 'what_i_watch', '')[:100]}"
                            )
                except Exception:
                    pass
                _joke_strs = []
                try:
                    _rs = getattr(_nerve, 'relational_state', None)
                    if _rs is not None and hasattr(_rs, '_rank_inside_jokes'):
                        _jokes = _rs._rank_inside_jokes(3)
                        for _j in _jokes:
                            _last_used = getattr(_j, 'last_used', 0)
                            _use_age = ('never used' if _last_used == 0
                                        else f"used {int((time.time()-_last_used)/3600)}h ago")
                            _joke_strs.append(
                                f"  - phrase: \"{_j.phrase[:60]}\"\n"
                                f"      born_from: {getattr(_j, 'birth_context', '')[:120]}\n"
                                f"      tone: {getattr(_j, 'tone', 'recurring')} | {_use_age}"
                            )
                except Exception:
                    pass
                if _top_concern_str or _joke_strs:
                    _parts = [
                        "[SOUL TO USE — context-aware reference, NOT mandatory]",
                        "Inside jokes carry meaning from their *born_from* context.",
                        "Use one only when the CURRENT situation genuinely shares the",
                        "thematic / metaphorical link of the original — same kind of",
                        "moment, same emotional register. If the link feels stretched,",
                        # [β.5.8-fix] 旧 "skip silently" 可能误读为全沉默. 改:
                        "just don't use the callback (still reply normally). Better no",
                        "callback than awkward callback.",
                    ]
                    if _top_concern_str:
                        _parts.append("\n[ACTIVE CONCERN]")
                        _parts.append(_top_concern_str)
                    if _joke_strs:
                        _parts.append("\n[INSIDE JOKES AVAILABLE]")
                        _parts.extend(_joke_strs)
                    soul_hint_block = "\n".join(_parts)
        except Exception:
            pass

        # 🩹 [β.5.31 / 2026-05-20] Sir 03:42 实测时间幻觉 BUG (准则 5 严重违规):
        # Sir 03:41:02 说"再过个十几分钟", 03:42:39 (1.6min 后) Jarvis 说"早就过去了".
        # Root cause: stream_nudge prompt 没注入"Sir 上一句话时间 + 距今 N min" 时间事实,
        # LLM 自由幻觉 elapsed time.
        # 修法: 加 [TIME ANCHOR] 段 - 显式列 Sir 最近 utterance 时间 + 距今 min, 强约束.
        _time_anchor_block = ""
        try:
            _stm_for_anchor = list(getattr(self.jarvis, 'short_term_memory', []) or [])
            _now_ts = time.time()
            for _e in reversed(_stm_for_anchor[-10:]):
                _u = str(_e.get('user', '') or '').strip()
                _src = _e.get('source', '')
                # 找最近一条真用户说话 (不是 system/jarvis_self)
                if _u and not _u.startswith('[') and _src not in ('system_event', 'jarvis_self', 'ambient_pickup'):
                    _t_str = _e.get('time', '')
                    # 反推 timestamp (HH:MM:SS → 今天该时刻)
                    try:
                        _h, _m, _s = _t_str.split(':')
                        _local = time.localtime(_now_ts)
                        _utt_ts = time.mktime((_local.tm_year, _local.tm_mon, _local.tm_mday,
                                                int(_h), int(_m), int(_s), 0, 0, -1))
                        if _utt_ts > _now_ts:  # 跨日
                            _utt_ts -= 86400
                        _elapsed_min = (_now_ts - _utt_ts) / 60
                        # 🩹 [β.5.31-fix / 2026-05-20] Sir 反问"为什么是模板? LLM 不能自己判断?"
                        # → 准则 6 (拒绝硬编码 + 信任 LLM). 删 prescriptive RULE, 只注入事实.
                        # ASR 事实: utterance 长度 + 是否 ambiguous (单字/字符级), LLM 自己判.
                        _utt_len = len(_u)
                        _is_short = _utt_len < 4
                        _is_single_token = ' ' not in _u and _utt_len < 6
                        _asr_facts = ""
                        if _is_short or _is_single_token:
                            _asr_facts = (
                                f"\n[ASR QUALITY FACT]\n"
                                f"Sir's last utterance length: {_utt_len} chars "
                                f"({'single-syllable / very short' if _is_short else 'single token / no space'}). "
                                f"This often indicates mis-ASR or filler. "
                                f"Context-anchored evidence may be thin.\n"
                            )
                        _time_anchor_block = (
                            f"\n[TIME ANCHOR — FACT]\n"
                            f"Current wall clock: {time.strftime('%H:%M:%S', _local)}\n"
                            f"Sir's last utterance at: {_t_str} "
                            f"({_elapsed_min:.1f} min ago)\n"
                            f'Sir said: "{_u[:120]}"\n'
                            f"{_asr_facts}"
                        )
                        break
                    except Exception:
                        pass
        except Exception:
            pass

        # 🆕 [P5-fix53 / 2026-05-23 15:30] 加 current_window_stay_s — Sir 15:27 痛点:
        # 主脑被问 "我在 QQ 多久" 误用 work_duration_min (整 session 累计) reply "19 min"
        # 但 Sir 刚切 QQ. 修: prompt 加 per-app current_window_stay_s 让主脑分清 2 字段.
        try:
            from jarvis_env_probe import PhysicalEnvironmentProbe as _Pep
            _window_stay_s = int(_Pep.current_window_stay_seconds or 0)
        except Exception:
            _window_stay_s = 0

        prompt = f"""{public_layers}

[CURRENT CONTEXT]
Time: {current_time} ({weekday})
work_session_total_min: {int(work_duration)} (整 Jarvis 启动以来 {work_category} 累计, **非当前 app 时长**)
current_window_stay_s: {_window_stay_s} (Sir 在**当前 active window** 停留秒数 — 问"在 X 多久"用此)
Active window: {window_title}
Process: {process_name}
{sensor_hints}
{_time_anchor_block}
[RECENT MEMORY]
{stm_context}

[LONG-TERM MEMORY]
{ltm_context}

{nudge_skills_block}

{soul_hint_block}

[NUDGE]
You are making a brief, unsolicited remark — NOT starting a conversation.
Type: {nudge_type}
{nudge_directive}
{recent_str}
{forbidden_str}
{channel_hint_str}

[RULES — schema 与防退化 (Sir 准则 6: 不写 persona/句式锁, 只防真坏)]
- ONE or TWO sentences. Under 25 words total.
- NEVER sound like a notification or health app.
- NEVER say "I recommend", "you should", "I suggest" (corporate/preachy patterns).
- Do NOT ask a question (unless directive explicitly allows, e.g. offer_help).
- Do NOT wait for a response. Say it and be done.
- Sir uses a DESKTOP PC. NEVER mention battery / power / charge metrics (don't exist).
- Append ---ZH--- followed by Chinese translation at the very end.
- [TRUTH ANCHOR — Sir 准则 5 / β.2.8.10 / β.5.8-fix]: Every specific narrative element you
  introduce (objects, events, activities, people, locations, sources) must
  correspond to something actually present in the context above. If the context
  doesn't show a SPECIFIC FACT, just don't introduce that fact — but still SPEAK.
  Generic greeting / acknowledgement / mood reflection / available skill mention is always safe.
  (β.5.8-fix: 旧文 "silence on unknown beats invented detail" 让主脑全沉默 — 错. 真规则是
  "略过未知细节但继续说话", 不是"不知道就沉默".)
- [INTEGRITY / OFFER INTEGRITY — Sir 准则 5]: When offering help AND AVAILABLE SKILLS listed above,
  name the specific action you can take by skill name (e.g. "I can run key_health_inspector.report_status").
  FORBIDDEN: vague offers ("shall I take a look / want me to check") without naming a real skill.
  If no skill matches, say plainly: "That's outside my reach right now, Sir."

[REACTION SPACE — Sir 准则 6 行为弱耦合 / β.5.0-B + β.5.3 + β.5.8-fix / 2026-05-19]
You have received a directive AND a [SHARED WORLD MODEL] block above.
The directive is a *proposal* from a sentinel. The SWM is the *evidence*.
You may choose to remain silent IF AND ONLY IF strong evidence requires it.
DEFAULT IS VOICE. The directive came through the gates — speaking is correct unless
explicit Sir-state forbids it.

Valid choices:
  - voice (default): generate the reply normally as instructed above.
  - silence: output the literal token  [SILENCE]  as your ENTIRE reply, nothing else.

[β.5.8-fix / Sir 14:00 实测 BUG] 上一轮 prompt bias-toward-silence 导致 Sir 起床 98min
AFK 后 return_greeting 也被 silent. 修: bias-toward-voice. 准则 3 (符合 butler 人设):
管家该说时就要说. 沉默只在 Sir 显式 reject/sleep/standby 时, 不是"我猜 Sir 不想听".

==== MUST SPEAK (HARD: never silence these, even if SWM has block advice) ====
  ★ nudge_type == 'return_greeting' AND afk_minutes >= 60 — Sir 长时离开回来, 必问候
  ★ nudge_type == 'morning_greeting' OR (return_greeting AND crosses_sleep=true) — Sir 起床第一句, 必问候
  ★ nudge_type == 'commitment_overdue' OR 'wakeup_reminder' — Sir 自己定的承诺到点, 必兑现
  ★ SWM 含 explicit Sir question/request 在 last 30s — 直接问答必应答
  ★ The sentinel's directive is a one-shot critical event (Sir wakeup / scheduled task fire)

==== ALLOW SILENCE (SOFT: only if ALL these hold simultaneously) ====
  1. SWM gate_advice metadata explicitly shows freeze_active=true (Sir said "standby"/"stop"
     in last 60s) — Sir 显式拒绝期内 — ONLY silence reason that overrides MUST SPEAK
  2. SWM gate_advice metadata explicitly shows sleep_mode=true AND nudge_type 不属于
     SLEEP_ALLOWED_TYPES (return_greeting/wakeup/emergency_break 仍要说)
  3. Sir's last utterance < 60s ago was 显式 "stop"/"shut up"/"安静"/"别说了" — explicit shut-up
  4. Directive 自相矛盾 (e.g. claim "7h at screen" but afk_return shows AFK 7h 跨夜) —
     evidence-contradict, refuse to lie. (But you should explain rather than silence if obvious.)

==== DO NOT silence on these (common BUG-1 pitfalls) ====
  ✗ SWM 含很多 'gate_advice decision=block' 来自 SmartNudge/Conductor/ReturnSentinel tick skip —
    这些是 sentinel 内部 cooldown/dedupe 信号, NOT Sir 拒绝. 不该影响 main brain 决策.
  ✗ SWM cooldown_remaining_s > 0 alone — cooldown 是上次说话太近, 不是 "Sir 不想听"
  ✗ Sir's last short reply ("好的"/"嗯"/"OK") — 这是正常对话 token, 不是拒绝
  ✗ "I don't have strong evidence to speak" — directive 来了就说, 不需要额外证据

When in doubt: SPEAK (准则 3). Saying the right thing late is better than saying nothing
and being seen as broken. The cost of one extra mild reply is much lower than the cost
of being mute when Sir wakes up.

If silent: just output  [SILENCE]  on its own line. Do not explain. Do not apologize.
No ZH translation. No closing remark. Nothing else.
"""

        # [P0-8 / 2026-05-15] 终端打印同时显示 source（ReturnSentinel/Conductor/SmartNudge）
        # 让 Sir 能一眼区分谁发的，避免之前 "Smart Nudge return_greeting" 看不出是 Conductor 的 Check-in
        # 被错映射的问题。source 从 nudge_context 的 conductor_action / source 字段推断。
        _nudge_source = nudge_context.get('source', '')
        if not _nudge_source:
            if nudge_context.get('conductor_action') or nudge_context.get('conductor_reason'):
                _nudge_source = 'Conductor'
            elif nudge_context.get('via_return_sentinel'):
                _nudge_source = 'ReturnSentinel'
            elif nudge_context.get('type') == 'proactive_care':
                _nudge_source = 'ProactiveCare'
            else:
                _nudge_source = 'SmartNudge'
        _src_tag = f" [{_nudge_source}]"

        print(f"\n" + "╔" + "═"*63)
        print(_box_newline(f"║ 💬 [Smart Nudge] {nudge_type}{_src_tag}"))
        print("╠" + "═"*63)
        print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
        print(f"║ 🤖  [Jarvis] ", end="", flush=True)

        self.is_interrupted = False

        try:
            # 🩹 [P5-fix33 / 2026-05-23 08:45] BUG-D: screen grab failed → empty nudge
            # Sir 真测: AFK 539min 后 ReturnSentinel 推 return_greeting nudge,
            # ImageGrab.grab() 抛 "screen grab failed" (锁屏/屏保) → 跳外层 except →
            # print 'screen grab failed' / box close / return '' → worker 报 empty_reply.
            # Sir 看到 `║ 🤖 [Jarvis] ╚═══════` 不知所云.
            # 修法: 截图失败时 fallback 到 text-only chat_history (Sir 锁屏久 → 早就该 expect 没图)
            full_text = ""
            streamed_text = ""
            chat_history = None
            # 🆕 [P5-fix35 / 2026-05-23] vision capability gate
            # text-only model (e.g. deepseek/v4-pro) 直接跳 ImageGrab → text-only chat_history.
            _supports_vision = getattr(self, 'main_brain_supports_vision', True)
            if not _supports_vision:
                try:
                    from jarvis_utils import bg_log as _vis_bg
                    _vis_bg(f"⚠️ [Nudge/NoVision] model={self.main_brain_model} "
                              f"is text-only, skipping ImageGrab")
                except Exception:
                    pass
                chat_history = [types.Content(role="user", parts=[
                    types.Part(text=prompt),
                ])]
            else:
                try:
                    from PIL import ImageGrab
                    screen_img = ImageGrab.grab()
                    screen_img.thumbnail((1280, 720))

                    img_buf = io.BytesIO()
                    screen_img.save(img_buf, format="JPEG", quality=50)
                    img_bytes = img_buf.getvalue()
                    chat_history = [types.Content(role="user", parts=[
                        types.Part(text=prompt),
                        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                    ])]
                except Exception as _ss_err:
                    # 锁屏/屏保 / 多 monitor 切 / 用户切 RDP 都常见. 不阻塞 nudge.
                    try:
                        from jarvis_utils import bg_log as _ss_bg
                        _ss_bg(f"⚠️ [Nudge/NoScreenshot] {type(_ss_err).__name__}: "
                                f"{_ss_err} → fallback text-only chat_history")
                    except Exception:
                        pass
                    # text-only fallback: 只发 prompt, 没 image
                    chat_history = [types.Content(role="user", parts=[
                        types.Part(text=prompt),
                    ])]

            _nudge_key_name = ''
            response = None
            for _nudge_attempt in range(3):
                _nudge_exec = None
                try:
                    _nudge_exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    _future = _nudge_exec.submit(self._create_stream, chat_history)
                    response, _nudge_key_name = _future.result(timeout=30.0)
                    break
                except concurrent.futures.TimeoutError:
                    if _nudge_attempt < 2:
                        delay = 1.5 * (2 ** _nudge_attempt)
                        print(f"\n⚠️[Nudge] API timeout, retrying in {delay:.1f}s (attempt {_nudge_attempt+1}/3)...")
                        if _nudge_key_name:
                            self.key_router.report_error(_nudge_key_name, 'timeout')
                            self.key_router.release(_nudge_key_name)
                        time.sleep(delay)
                    else:
                        print("\n⚠️[Nudge] Gemini API response timeout (3 retries exhausted)")
                        print("╚" + "═"*63 + "\n")
                        return ""
                except Exception as _nudge_e:
                    if _nudge_attempt < 2:
                        delay = 1.5 * (2 ** _nudge_attempt)
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"⚠️[Nudge] API error: {type(_nudge_e).__name__}, retrying in {delay:.1f}s...")
                        except Exception:
                            pass
                        if _nudge_key_name:
                            self.key_router.report_error(_nudge_key_name, str(_nudge_e))
                            self.key_router.release(_nudge_key_name)
                        time.sleep(delay)
                    else:
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"⚠️[Nudge] API error (3 retries exhausted): {_nudge_e}")
                        except Exception:
                            pass
                        print("╚" + "═"*63 + "\n")
                        return ""
                finally:
                    if _nudge_exec is not None:
                        _nudge_exec.shutdown(wait=False)
            
            if response is None:
                return ""

            buffer = ""
            _zh_seen = False
            _silence_chosen = False
            # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切 (stream_nudge 路径)
            _first_sent_done = False

            for chunk in response:
                if getattr(self, 'is_interrupted', False):
                    break

                if chunk.text:
                    text_delta = chunk.text
                    buffer += text_delta
                    full_text += text_delta

                    # [β.5.0-B / β.5.3-fix / 2026-05-19] reaction_space [SILENCE] 检测
                    # 主脑可输出 "[SILENCE]" 整段表达 "看 SWM 后我选择不说".
                    # 双层检测:
                    #   1. 头部 (≤32 chars 内) 含 [SILENCE] → 早期 break (TTS 0 漏)
                    #   2. 全 stream 任何位置含 [SILENCE] / [silence] → break (BUG-3 防御:
                    #      主脑若输出 "Hello [SILENCE]" 这种乱来, 也得拦截不让 silence
                    #      token 漏到 TTS)
                    # 必须早于 _put_audio 调用 (line 3947 buffer flush)
                    _ft_lower = full_text.lower()
                    if ('[silence]' in _ft_lower or '[SILENCE]' in full_text):
                        _silence_chosen = True
                        break

                    is_forming_tag = False
                    if "---ZH---" in full_text:
                        for i in range(1, len("---ZH---")):
                            if full_text.endswith("---ZH---"[:i]):
                                is_forming_tag = True
                                break

                    if not is_forming_tag:
                        clean_full = full_text
                        clean_full = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', clean_full)
                        if "---ZH---" in clean_full:
                            clean_full = clean_full.split("---ZH---")[0].rstrip('\n')

                        delta = clean_full[len(streamed_text):]
                        if delta:
                            print(_box_newline(delta), end="", flush=True)
                            streamed_text += delta

                    while True:
                        # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 复用 module-level _find_sentence_split_idx
                        # （内含 organ.command 中间 . 不切的保护）
                        # 🩹 [P0+20-β.5.9 / 2026-05-19] 首句激进切
                        earliest_idx = _find_sentence_split_idx(buffer, soft_split=True, is_first_sentence=not _first_sent_done)

                        if earliest_idx == -1 and len(buffer) > 80:
                            for i in range(len(buffer) - 1, 20, -1):
                                if buffer[i] == ' ':
                                    earliest_idx = i
                                    break

                        if earliest_idx != -1:
                            sentence = buffer[:earliest_idx + 1].strip()
                            buffer = buffer[earliest_idx + 1:]

                            if "---ZH---" in sentence:
                                _zh_seen = True
                                sentence = sentence.split("---ZH---")[0]

                            sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                            sentence = re.sub(r'\[(?:WORK_MODE|WAKE_ONLY|RELAX_MODE)\]', '', sentence).strip()
                            sentence = sentence.replace("J A R V I S", "Jarvis").replace("JARVIS", "Jarvis")
                            if sentence and not _zh_seen:
                                self._put_audio(sentence)
                                self.subtitle_queue.put(("en", sentence))
                                _first_sent_done = True  # β.5.9
                        else:
                            break

            # 🩹 [P0+20-β.2.7.7 / 2026-05-17] 末尾 buffer flush dedup guard
            # Sir 实测 return_greeting nudge 字幕重复 2 遍:
            #   "Welcome back, Sir. I trust the meal was satisfactory.
            #    Welcome back, Sir. I trust the meal was satisfactory."
            # 根因可能: (a) LLM 模型复读输出 / (b) 末尾 flush 与上一句 splitter sentence
            # 内容重叠 → subtitle_queue 双发 → UI 累计渲染。
            # 防御: 末尾 sentence 含上一句 audio 的全文 → 跳过 (subtitle + audio 都不重发)
            # [β.5.0-B / 2026-05-19] reaction_space: 主脑选 [SILENCE] → 不出声 + 不字幕 +
            # publish self_silence_chose 到 SWM 让下一轮主脑知道 "我刚刚选过沉默".
            if _silence_chosen:
                # 🩹 [β.5.19-A / 2026-05-20] 标 silence flag, 让上层 worker 不报
                # `[Nudge/NoSound] empty_reply` 误警 (实是预期 reaction_space 静默).
                self._last_nudge_was_silence = True
                print(_box_newline("[SILENCE — 主脑选择沉默, 看 SWM evidence 不发声]"))
                print("╚" + "═"*63 + "\n")
                try:
                    from jarvis_utils import get_event_bus, bg_log as _sb
                    _swm = get_event_bus()
                    if _swm is not None:
                        _swm.publish(
                            etype='self_critique',
                            description=f"Brain chose [SILENCE] for nudge_type={nudge_type}, source={_nudge_source}",
                            source='BrainReactionSpace',
                            metadata={
                                'reaction': 'silence',
                                'nudge_type': nudge_type,
                                'nudge_source': _nudge_source,
                            },
                            salience=0.65,
                        )
                    _sb(f"🤐 [Nudge/Silence] 主脑选 [SILENCE] for {nudge_type} from {_nudge_source}")
                except Exception:
                    pass
                return None

            if buffer.strip() and not getattr(self, 'is_interrupted', False):
                sentence = buffer.strip()
                if "---ZH---" in sentence:
                    _zh_seen = True
                    sentence = sentence.split("---ZH---")[0]
                sentence = re.sub(r'<[^>]+>', '', sentence).strip()
                if sentence and not _zh_seen:
                    _last_audio = (getattr(self, '_last_audio_text', '') or '').strip()
                    _is_dup = bool(_last_audio) and (
                        sentence == _last_audio or
                        sentence == _last_audio.rstrip('.!?。！？') or
                        # 末尾 sentence 完整包含上一句 (LLM 复读 case)
                        (len(_last_audio) >= 10 and _last_audio in sentence)
                    )
                    if not _is_dup:
                        self._put_audio(sentence)
                        self.subtitle_queue.put(("en", sentence))
                    else:
                        try:
                            from jarvis_utils import bg_log
                            bg_log(f"🔇 [Nudge Dedup] 末尾 flush 与上一句重复 → 跳过: '{sentence[:50]}'")
                        except Exception:
                            pass

            final_reply = full_text.split("---ZH---")[0].strip()
            
            if "---ZH---" in full_text:
                zh_text = full_text.split("---ZH---")[1].strip()
                clean_zh = re.sub(r'<[^>]+>', '', zh_text).strip()
                if clean_zh:
                    # 🆕 [Sir 23:24 BUG-1 治本] nudge stream 末了 ZH 末尾不合法 → defer
                    _final_for_check = full_text.split('---ZH---')[0].strip() if '---ZH---' in full_text else ''
                    if _zh_subtitle_looks_truncated(clean_zh, len(_final_for_check)):
                        try:
                            from jarvis_utils import bg_log as _zh_def_bg5
                            _zh_def_bg5(f"⏸ [Subtitle/ZH-defer/nudge] leftover ZH 末尾不合法 ({len(clean_zh)}ch '{clean_zh[-20:]}'), 跳过 put")
                        except Exception:
                            pass
                    else:
                        self.subtitle_queue.put(("zh", clean_zh))
                        # [P0+18-c.12 / 2026-05-15] 多段 ZH (含 \n\n) 走 _box_newline,每行加 ║ 前缀
                        print("\n" + _box_newline(f"║ 📺  [Subtitle] {clean_zh}"))

            # 🩹 [P0+20-β.1.25 / 2026-05-16] 记录本轮 reply 开头到 anti-repeat 历史
            # 下次同 nudge_type 触发时塞进 prompt 显式 FORBIDDEN，防固定句式复用
            try:
                if final_reply and nudge_type:
                    _opening = final_reply[:80].strip()
                    if _opening:
                        bucket = self._nudge_recent_phrases.setdefault(nudge_type, [])
                        bucket.append(_opening)
                        if len(bucket) > self._NUDGE_RECENT_MAX:
                            self._nudge_recent_phrases[nudge_type] = bucket[-self._NUDGE_RECENT_MAX:]
            except Exception:
                pass

            # 🩹 [P0+20-β.2.7.3 / 2026-05-17] Self-Promise Detector：
            # SmartNudge/Conductor/CommitmentWatcher/ReturnSentinel 路径里 Jarvis 自己
            # 说"我会监督您 X" 也要注册成 commitment（与 Sir 承诺平等）。
            try:
                from jarvis_self_promise import get_default_detector as _gdp
                cw = getattr(self.jarvis, 'commitment_watcher', None)
                _sp_reply = full_text if (full_text and full_text.strip()) else final_reply
                if _sp_reply and cw is not None:
                    _gdp().detect_and_register_async(
                        jarvis_reply=_sp_reply,
                        commitment_watcher=cw,
                        turn_id='nudge_' + (nudge_type or '?'),
                    )
            except Exception:
                pass

            # 🔧 [β.5.36-G / 2026-05-20] Nudge 路径同 stream_chat 跑 IntentRouter.
            # 主脑 nudge 也可能 emit <TOOL_CALL>{intent}, 同步执行 + 结果回流 SWM.
            try:
                from jarvis_intent_router import IntentParser, get_default_intent_router
                if IntentParser.has_tool_call_tag(full_text):
                    _router = get_default_intent_router()
                    if _router is not None:
                        _ir_results = _router.route_and_invoke_all(full_text)
                        if _ir_results:
                            try:
                                from jarvis_utils import bg_log as _ir_bg
                                _hits = sum(1 for r in _ir_results if r.get('success'))
                                _ir_bg(
                                    f"🔧 [IntentRouter/Nudge] {len(_ir_results)} tool calls "
                                    f"({_hits} success): "
                                    + ', '.join(
                                        f"{r.get('intent_id', '?')}={'✅' if r.get('success') else '❌'}"
                                        for r in _ir_results[:5]
                                    )
                                )
                            except Exception:
                                pass
            except Exception:
                pass

            print("\n╚" + "═"*63 + "\n")

            # 🩹 [P2-Gap12 / 2026-05-20 23:50] Record this nudge in RecentNudgeMemory
            # Sir 22:38/22:44 真痛点: 6 channel nudge 重复 "shower" 主题. 加 record
            # 让 _assemble_prompt 下次 inject [RECENT JARVIS NUDGES] block, 主脑看
            # 自己刚说过啥不重复.
            try:
                if final_reply and final_reply.strip():
                    from jarvis_recent_nudge_memory import record_nudge as _rn
                    _channel = (nudge_context or {}).get('nudge_type', 'unknown')
                    _trigger = (nudge_context or {}).get('source', '')
                    _turn_id = ''
                    try:
                        from jarvis_utils import TraceContext as _TC
                        _turn_id = _TC.get_turn_id() or ''
                    except Exception:
                        pass
                    _rn(channel=_channel,
                        content=final_reply,
                        trigger=_trigger,
                        turn_id=_turn_id)
            except Exception:
                pass

            # 🆕 [Sir 2026-05-27 真愿景 Phase 3] nudge 也 self-append 进 voice track
            # =================================================================
            # Sir 真愿景: 主动 nudge 也是 jarvis 嘴说话, voice 应记账. 主脑下次
            # 看 voice 知道"我刚 nudge 过 X 主题", 避免重复 + 形成自我感知连续性.
            # source='self_reflection' intent='noting' urgency=0.4 (略高于 reply,
            # 因为 nudge 是 jarvis 主动发声, 自我感知信号更强).
            # wants_voice=False (内部记账, 主脑不该 surface "我刚 nudge 过" 给 Sir).
            # =================================================================
            try:
                if final_reply and final_reply.strip():
                    from jarvis_inner_voice_track import (
                        get_inner_voice_track as _giv_n,
                        is_enabled as _iv_en_n,
                    )
                    if _iv_en_n():
                        _ch_nv = (nudge_context or {}).get('nudge_type', 'unknown')
                        _trig_nv = (nudge_context or {}).get('source', '')
                        _reply_prev_nv = str(final_reply).strip()[:120]
                        _voice_meta_nv = {
                            'kind': 'nudge_reply',
                            'nudge_channel': _ch_nv,
                            'nudge_source': str(_trig_nv)[:60],
                            'reply_len': len(final_reply or ''),
                            'reply_excerpt': _reply_prev_nv,
                            'turn_id': _turn_id if '_turn_id' in dir() else '',
                        }
                        _giv_n().append(
                            source='self_reflection',
                            intent='noting',
                            content=f'i nudged sir ({_ch_nv}): "{_reply_prev_nv}"',
                            urgency=0.4,
                            wants_voice=False,
                            meta=_voice_meta_nv,
                        )
            except Exception:
                pass

            # 🆕 [P5-fix73 / 2026-05-23 17:58] BUG-L: Sir 17:56 真测痛点 — Nudge
            # reply 没接 ClaimTracer. 主脑说 "I've updated the hydration logs to
            # 2000ml" 但**没真调 progress**. ClaimTracer 抓 chat reply 但漏 nudge.
            # 修法: stream_nudge 末尾也 trace_reply (nudge 没 tool_results 通常,
            # 所以"已做 X"类 claim 必 unverified, ClaimTracer audit 抓回).
            try:
                if final_reply and final_reply.strip():
                    from jarvis_claim_tracer import trace_reply as _ct_nudge
                    from jarvis_utils import TraceContext as _TC_n
                    _ttid_n = ''
                    try:
                        _ttid_n = _TC_n.get_turn_id() or ''
                    except Exception:
                        pass
                    _channel_n = (nudge_context or {}).get('nudge_type', 'nudge')
                    _ct_nudge(
                        jarvis_reply=final_reply,
                        tool_results=[],  # nudge 无 tool_results (publish_only)
                        stm_recent=list(getattr(self.jarvis,
                                                 'short_term_memory', []) or []),
                        turn_id=f'nudge:{_channel_n}:{_ttid_n}',
                        ltm_context='',
                    )
            except Exception:
                pass

            if '_nudge_key_name' in dir():
                self.key_router.release(_nudge_key_name)
            return final_reply

        except Exception as e:
            # 🩹 [P0+20-β.5.16 / 2026-05-19] BUG-D: stream_nudge partial-flush 守卫
            # Sir 22:21 实测 - ProactiveCare nudge 主回复已 stream 出 ("I've been
            # watching your late-night streak, Sir..."), 然后 read_timeout, ZH 翻译
            # 没流回. 体感: 无中文字幕 + 上层看 nudge_reply='' 误判"未出声" 进 NoSound.
            # 修法 (跟 β.5.12 BUG-A 同款): 若 full_text 已 stream 实质内容 (>= 12 char),
            # best-effort flush ZH (有就用) + 返 final_reply 非空让上层认知"说过了".
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️[Nudge Error]: {e}")
            except Exception:
                pass

            _final_reply = ''
            try:
                _net = (full_text or '').strip() if 'full_text' in dir() else ''
                _net_clean = re.sub(r'<[^>]+>', '', _net).strip() if _net else ''
                if _net_clean and len(_net_clean) >= 12:
                    # 已说实质 — 拆 ZH (best-effort) + 设 final_reply
                    if '---ZH---' in _net:
                        _final_reply = _net.split('---ZH---')[0].strip()
                        _zh = _net.split('---ZH---', 1)[1].strip()
                        _zh_clean = re.sub(r'<[^>]+>', '', _zh).strip()
                        if _zh_clean:
                            self.subtitle_queue.put(("zh", _zh_clean))
                            try:
                                print("\n" + _box_newline(f"║ 📺  [Subtitle] {_zh_clean} (β.5.16 partial flush)"))
                            except Exception:
                                pass
                    else:
                        _final_reply = _net.strip()
                    try:
                        from jarvis_utils import bg_log as _b516
                        _b516(f"🩹 [β.5.16/Nudge-Partial] {type(e).__name__} after spoken={len(_net_clean)}ch, flush ZH={'yes' if '---ZH---' in _net else 'no'}")
                    except Exception:
                        pass
            except Exception:
                pass

            print("╚" + "═"*63 + "\n")
            if '_nudge_key_name' in dir():
                self.key_router.release(_nudge_key_name)
            return _final_reply


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

