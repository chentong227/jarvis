# -*- coding: utf-8 -*-
"""[P0+19-final fix / 2026-05-16] 批量给拆出的新文件补全跨模块 import

问题：每次启动暴露一处 NameError（VocalCord / PromptCenter / LlmReflector...），
原因是 batch extract 时 header 列表不够全。一次性补齐降低后续暴露面。

策略：在每个新文件的"第一段 jarvis_xxx import 之后"插入一段完整的 extended imports。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 通用 extended imports（每个文件都加同一段，重复 import 无副作用）
EXTENDED_IMPORTS = '''
# [P0+19-final fix / 2026-05-16] 补全跨模块依赖（拆分后实例化时才暴露的缺失）
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except ImportError:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except ImportError:
    pass
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

'''

# 受影响文件（不含 jarvis_central_nerve.py / jarvis_worker.py，那俩已手工补全）
FILES_TO_PATCH = [
    'jarvis_sentinels.py',
    'jarvis_conductor.py',
    'jarvis_return_sentinel.py',
    'jarvis_commitment_watcher.py',
    'jarvis_smart_nudge.py',
    'jarvis_chat_bypass.py',
    'jarvis_memory_core.py',
    'jarvis_routing.py',
]

# 找一个稳定 anchor：每个文件应该都有 'from jarvis_env_probe import' 或 'from jarvis_sensors import'
# 在它后面注入 extended imports
ANCHORS = [
    'from jarvis_sentinels import NudgeGate  # noqa: F401',
    'from jarvis_sentinels import NudgeGate',
    'from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401',
    'from jarvis_env_probe import PhysicalEnvironmentProbe',
]


def patch(filename):
    path = os.path.join(ROOT, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'P0+19-final fix / 2026-05-16] 补全跨模块依赖' in content:
        return f'{filename}: already patched'
    
    for anchor in ANCHORS:
        if anchor in content:
            new_content = content.replace(anchor, anchor + '\n' + EXTENDED_IMPORTS, 1)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return f'{filename}: patched (anchor: "{anchor[:50]}...")'
    
    # 找不到 anchor 时，在第一个 from jarvis_ 后插入
    import re
    m = re.search(r'^(from jarvis_\w+ import [^\n]+)\n', content, re.MULTILINE)
    if m:
        new_content = content[:m.end()] + EXTENDED_IMPORTS + content[m.end():]
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return f'{filename}: patched (after first jarvis_ import)'
    
    return f'{filename}: NO ANCHOR FOUND, skip'


for f in FILES_TO_PATCH:
    print(patch(f))
