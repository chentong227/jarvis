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


class ChatBypass:
    def __init__(self, key_router, vocal_cord, state_callback):
        self.key_router = key_router
        self.model_name = 'gemini-3-flash-preview'
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

            or_model = 'google/gemini-3-flash-preview'

            # 🩹 [P0+20-β.5.12 / 2026-05-19] BUG-B: chunk inter-arrival timeout 12s
            # Sir 21:37 实测: cloud stream 半路 server close TCP, client 干等 18.8s 才
            # 报 RemoteProtocolError. 老 float 60s 是 *total* request 超时, 不是 chunk
            # 间隔超时. httpx.Timeout(read=12.0) 含义: "server 12s 不发任何字节 → ReadTimeout".
            # 这正是 chunk inter-arrival timeout — 12s 既能盖 reasoning (gemini ~5-10s 思考)
            # 又能让网络僵局快速断离. connect/write/pool 仍各自 10s.
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=key,
                default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
                timeout=_httpx_b512.Timeout(connect=10.0, read=12.0, write=10.0, pool=10.0)
            )

            response = client.chat.completions.create(
                model=or_model,
                messages=messages,
                temperature=0.7,
                stream=True
            )

            class _ChunkWrapper:
                __slots__ = ('text',)
                def __init__(self, text):
                    self.text = text

            def _stream_wrapper():
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield _ChunkWrapper(chunk.choices[0].delta.content)

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

    def _execute_fast_call(self, organ_name: str, command: str, params: dict):
        import contextlib
        import re as _re_safety

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
            # → 此处 subprocess 启动 jarvis_dashboard.py (pythonw, 无 console).
            if ctrl_cmd == "dashboard_open":
                # 🩹 [β.2.9.13 / 2026-05-18] Sir 14:00 实测痛点修:
                # 旧版用 pythonw.exe 静默失败 + return ✅ → 主脑说"已打开"但 Sir
                # 没看到窗口 = 言行不一. 准则 5 修:
                #   1. 优先 python.exe (有 console 看 error), 不用 pythonw 静默失败
                #   2. 启动后 sleep 0.5s 检查进程 poll() — 活着才返 ✅, 死了返 ❌
                try:
                    import subprocess as _sp
                    import sys as _sys
                    import time as _t
                    py_exe = _sys.executable  # 用主进程 python (有 console)
                    dash_script = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'scripts', 'jarvis_dashboard.py')
                    if not os.path.exists(dash_script):
                        dash_script = 'scripts/jarvis_dashboard.py'
                    # CREATE_NEW_CONSOLE 让 dashboard 在新窗口 (Sir 能看启动 log)
                    proc = _sp.Popen(
                        [py_exe, dash_script],
                        creationflags=getattr(_sp, 'CREATE_NEW_CONSOLE',
                                               0x00000010),
                        close_fds=True,
                    )
                    # 启动健康检查 — 准则 5 不假装成功
                    _t.sleep(0.6)
                    if proc.poll() is not None:
                        # 进程秒退 = 启动失败 (Tkinter / import error / etc)
                        return (f"❌ ui_control.dashboard_open: 进程秒退 "
                                f"(exit_code={proc.returncode}) — Sir 直接跑 "
                                f"`scripts\\jarvis_dashboard.cmd` 看 console error")
                    return f"✅ ui_control.dashboard_open: 看板已启动 (PID={proc.pid})"
                except Exception as _de:
                    return f"❌ ui_control.dashboard_open: {_de}"
            if ctrl_cmd == "dashboard_close":
                try:
                    import subprocess as _sp
                    # taskkill 找窗口标题含 J.A.R.V.I.S 的 python 进程
                    _sp.run(
                        ['taskkill', '/F', '/FI',
                         'WINDOWTITLE eq 贾维斯总览看板*'],
                        capture_output=True, timeout=5,
                    )
                    return f"✅ ui_control.dashboard_close"
                except Exception as _ce:
                    return f"❌ ui_control.dashboard_close: {_ce}"
            return f"❌ ui_control: 未知指令 {ctrl_cmd}"

        hand_class = self.jarvis.hand_registry.get(organ_name)
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
            from PIL import ImageGrab
            screen_img = ImageGrab.grab()
            screen_img.thumbnail((1280, 720))
            img_buf = io.BytesIO()
            screen_img.save(img_buf, format="JPEG", quality=50)
            img_bytes = img_buf.getvalue()
            _t_ss_done = time.time()
            chat_history = [types.Content(role="user", parts=[
                types.Part(text=prompt),
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
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
                        self.subtitle_queue.put(("zh", clean_zh))

                if '_stream_key_name' in dir():
                    self.key_router.release(_stream_key_name)

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

                    # 🩹 [β.2.9.9 / 2026-05-18] Sir 10:51 诚信审计治本路径:
                    # 解析 <MEMORY_UPDATE field="X" old="A" new="B"> 标签 → 真写
                    # memory_pool/profile_corrections.jsonl. 这是主脑说"已更新"
                    # 的唯一合法路径 (准则 5). 没发标签 + 说"已更新" → 被
                    # memory_update_honesty directive 拦.
                    try:
                        from jarvis_safety import (
                            parse_memory_update_tags, execute_memory_updates
                        )
                        _mu_updates = parse_memory_update_tags(full_text)
                        if _mu_updates:
                            _n_written = execute_memory_updates(
                                _mu_updates, source='llm_tag')
                            if _n_written > 0:
                                try:
                                    from jarvis_utils import bg_log as _mu_bg
                                    _mu_bg(
                                        f"📝 [MemoryUpdate] LLM 标签触发, "
                                        f"写入 {_n_written} 条 profile correction"
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
            if prompt_tier in ('WAKE_ONLY', 'FACTUAL_RECALL'):
                _ss_strategy = 'skipped'
            else:
                from PIL import ImageGrab
                screen_img = ImageGrab.grab()
                screen_img.thumbnail((1280, 720))
                img_buf = io.BytesIO()
                screen_img.save(img_buf, format="JPEG", quality=50)
                img_bytes = img_buf.getvalue()
            _t_ss_done = time.time()

            try:
                from jarvis_utils import bg_log
                _ss_elapsed_ms = int((_t_ss_done - _t_ss_start) * 1000)
                bg_log(f"📸 [Screenshot] strategy={_ss_strategy} | elapsed={_ss_elapsed_ms}ms | tier={prompt_tier}")
            except Exception:
                pass

            # 没有图就只送文本（WAKE_ONLY 路径），有图就附带（vision-aware）
            if img_bytes is None:
                chat_history = [types.Content(role="user", parts=[
                    types.Part(text=prompt),
                ])]
            else:
                chat_history = [types.Content(role="user", parts=[
                    types.Part(text=prompt),
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                ])]
            
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
                            or_response = or_client.chat.completions.create(
                                model="google/gemini-3-flash-preview",
                                messages=messages,
                                temperature=0.7,
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
                            print(f"\n║ 🛑 [Tool Chain] 检测到重复调用 {organ_name}.{command} "
                                  f"(参数完全相同，第 {_call_signature_count[_sig]} 次)，提前熔断 — "
                                  f"上一次已成功，不再重复执行")
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

                        if is_acknowledgment and organ_name in SAFETY_GATE_ORGANS:
                            tool_result = "SAFETY_GATE_BLOCKED: Sir's input was a simple acknowledgment, not an explicit request for file operations. Do NOT propose or execute file modifications unless Sir explicitly asks."
                            _tool_results.append(f"🛡️ 安全闸拦截: {organ_name}.{command}")
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
                            hand_class = self.jarvis.hand_registry.get(organ_name)
                            if hand_class:
                                try:
                                    hand_inst = hand_class(self.jarvis.gemini_key)
                                except TypeError:
                                    hand_inst = hand_class()
                                    
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
                    
                    continuation_prompt = f"""[SYSTEM TOOL RESULT for {command}]: {tool_result}

[CRITICAL CHAINING RULE]:
If you need to perform ANOTHER action based on this result, output ONLY the next <FAST_CALL> block. DO NOT speak any words between chained tool calls! Stay completely silent until ALL tools are done.

If ALL tasks are fully completed (no more tools needed), then and ONLY then:
1. Speak a SINGLE, concise concluding sentence in English that summarizes ALL the actions you just performed.
2. Output `---ZH---` followed by the Chinese translation.
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
                    or (_circuit_broken_reason.startswith('duplicate_call:') and _any_tool_ok)
                )
            )

            if _need_synthesis:
                last_ok = next((r for r in reversed(_tool_results) if r.startswith("✅")), None)
                last_bad = next((r for r in reversed(_tool_results) if r.startswith(("❌", "🛡️"))), None)

                if _circuit_broken_reason == "single_step_fast_path":
                    # 简单单步设备指令成功 — 短促干脆
                    en = "Done, Sir."
                    zh = "已完成。"
                elif _circuit_broken_reason.startswith("duplicate_call:"):
                    if last_ok:
                        en = "Done, Sir — the action already completed on the first call."
                        zh = "已经完成了，Sir，第一次调用就生效了。"
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
                    # 拿最后一条失败信息的"为什么失败"塞进去，比纯模板更有信息量
                    bad_tail = ""
                    if last_bad:
                        bad_tail = last_bad.split(":", 1)[-1].strip()[:80]
                    if bad_tail:
                        en = f"I couldn't complete that, Sir — {bad_tail}"
                        zh = f"Sir，那件事我没能做完：{bad_tail}"
                    else:
                        en = "I lacked the right tool to do that cleanly, Sir."
                        zh = "Sir，那件事没有合适的工具直接完成。"
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
                    print(_box_newline(f"║ {r}"))
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
            
            final_reply = full_text.split("---ZH---")[0].strip()
            
            if "---ZH---" in full_text:
                zh_text = full_text.split("---ZH---")[1].strip()
                clean_zh = re.sub(r'<[^>]+>', '', zh_text).strip()
                if clean_zh:
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
        _t_total = time.time() - _t0
        try:
            from jarvis_utils import bg_log
            bg_log(f"⏱️ [Pipeline Timer] stream_chat总耗时: {_t_total:.1f}s (截图{_t_ss_done - _t_ss_start:.1f}s + API+流式{_t_total - (_t_ss_done - _t_ss_start):.1f}s)")
        except Exception:
            print(f"⏱️ [Pipeline Timer] stream_chat总耗时: {_t_total:.1f}s (截图{_t_ss_done - _t_ss_start:.1f}s + API+流式{_t_total - (_t_ss_done - _t_ss_start):.1f}s)", file=sys.stderr)
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
{time_persona}

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
            "hydration": "Sir has been working for a while without an obvious break — could be time to mention water.",
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
                #   准则 6: 不写 forbidden list (那是负向), 改告诉主脑 "用具体观察开场".
                #   Sir 偏好 signal > 礼貌; 具体的窗口/活动/时段比 "Welcome back" 强 10 倍.
                f"Sir just returned to his computer (was away for "
                f"{nudge_context.get('afk_minutes', 'a while')} minutes).\n"
                # [β.4.12] morning evidence — 主脑看 evidence 自己涌现 morning tone, 不教句式
                + (
                    f"[MORNING CONTEXT — evidence, not directive]:\n"
                    f"  is_first_today: {nudge_context.get('is_first_today', False)}\n"
                    f"  crosses_sleep_period: {nudge_context.get('crosses_sleep_period', False)} "
                    f"(AFK > 4h indicates likely overnight sleep)\n"
                    f"  is_morning_window: {nudge_context.get('is_morning_window', False)} "
                    f"(local hour in [5, 12))\n"
                    f"  → If all three are true, this is Sir's first activity of the day after sleep.\n"
                    f"    Treat the moment as a fresh-day check-in, not a return-from-break.\n"
                    f"    Pending work topics (yesterday's threads, overdue tasks) should NOT be the\n"
                    f"    opening — Sir hasn't had coffee yet. Acknowledge the new day briefly,\n"
                    f"    then a lightweight status check ('how did you sleep' / 'how's the morning').\n"
                    f"    Bring up pending threads ONLY if Sir asks or signals readiness.\n\n"
                    if nudge_context.get('is_first_today') and nudge_context.get('crosses_sleep_period')
                    else ""
                )
                + f"Speak in your own voice.\n\n"
                f"[STYLE — concrete signal over polite opener]:\n"
                f"Sir 准则 6: open with the most specific thing you actually "
                f"observe in his current context (window title, last activity, "
                f"elapsed AFK pattern, time of day). NOT with a generic social "
                f"greeting ('Welcome back', '回来啦', 'Sir', 'Hi'). Sir reads "
                f"every generic opener as a template — give him signal instead.\n\n"
                f"[TRUTH ANCHOR — Sir 准则 5 / β.5.8-fix]:\n"
                f"Every specific narrative element you introduce (objects, events, "
                f"activities, people, locations) must correspond to something "
                f"actually present in the context above. If the context doesn't "
                f"show what Sir did during AFK, just don't speculate about it — "
                f"BUT STILL GREET. Open with a generic acknowledgement of the "
                f"return / fresh day, then a soft check-in. Don't go silent. "
                f"Sir 准则 3 (butler 人设): a greeting on return is what a butler does."
            ),
            "commitment_check": (
                # 删句式锁 "Express gentle dry concern / sound like a friend not a parent".
                # 保留 anti-hallucination (这是 integrity 规则不是句式锁, Sir 准则 5).
                f"Sir said he would {nudge_context.get('commitment_description', 'rest')} "
                f"at {nudge_context.get('commitment_time', 'a certain time')}. "
                f"It is now {nudge_context.get('overdue_minutes', 'some')} minutes past "
                f"that time and he is still working.\n\n"
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
                # 删 6 段 "CRITICAL — TONE VARIATION / PHRASING VARIETY / EMOTIONAL PERCEPTION"
                # 句式锁清单. 保留 anti-pollution (tool name 禁令 — 这是 integrity 规则).
                f"Sir seems to be stuck on an error or debugging issue. "
                f"You can offer help if you have a real way to help.\n\n"
                f"[INTEGRITY — Sir 准则 5]: NEVER mention internal tool names "
                f"(process_hands.X / file_operator.Y / fast_call / organ name / "
                f"snake_case identifier). Speak human language only."
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

        conductor_msg = nudge_context.get('conductor_message', '')
        if conductor_msg:
            nudge_directive = (
                f"You have received an internal memo from the scheduling center:\n"
                f"\"{conductor_msg}\"\n\n"
                f"Act on this memo. Make a brief, unsolicited remark to Sir — NOT starting a conversation. "
                f"ONE sentence. Under 15 words. Sound like yourself, not the scheduling center."
            )

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

        prompt = f"""{public_layers}

[CURRENT CONTEXT]
Time: {current_time} ({weekday})
Sir has been: {work_category} for {int(work_duration)} minutes
Active window: {window_title}
Process: {process_name}
{sensor_hints}

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
            
            full_text = ""
            streamed_text = ""

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

            print("\n╚" + "═"*63 + "\n")
            if '_nudge_key_name' in dir():
                self.key_router.release(_nudge_key_name)
            return final_reply

        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️[Nudge Error]: {e}")
            except Exception:
                pass
            print("╚" + "═"*63 + "\n")
            if '_nudge_key_name' in dir():
                self.key_router.release(_nudge_key_name)
            return ""


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

