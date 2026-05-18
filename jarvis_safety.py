# -*- coding: utf-8 -*-
"""[P0+19-1 / 2026-05-16] Jarvis Safety Helpers — 反幻觉 / 守卫 / 文本格式纯函数

从 jarvis_nerve.py 拆出，包含 12 个纯函数 + 5 个常量：
- Memory Deletion 守卫（P0+16 纯指代词识别 / P0+18-a.5 物理文件删除意图识别）
- Structural Tag 剥离（P0+18-c.1）
- 上游 Audio Guard / 中文检测（P0+18-e.2）
- 终端排版 box + ANSI colorize（P0+18-e.4）

线程安全：全部纯函数 + 不可变常量元组 / regex 模式，无状态。

向后兼容：jarvis_nerve.py 用 `from jarvis_safety import *` 转发，
所有旧 `from jarvis_nerve import _is_xxx` 调用 0 改动。
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


import re


# 显式导出：因为下方所有符号都是 `_` 前缀（私有），默认 `from X import *` 不会带它们。
# 用 __all__ 强制导出，让 jarvis_nerve.py 转发垫层能拿到。
__all__ = [
    # P0+16 纯指代词识别
    '_REFERENCE_TOKENS',
    '_strip_reference_tokens',
    '_is_reference_only_hint',
    # P0+18-a.5 物理文件删除意图识别
    '_PHYSICAL_FILE_DELETE_MARKERS',
    '_is_physical_file_delete_intent',
    # P0+20-β.4.7 / 2026-05-18 Memory Deletion 第 6/7/8 层守卫 (Sir 21:45 实测 BUG 治本)
    '_DELETION_VOCAB_PATH',
    '_user_intent_has_explicit_delete_verb',
    '_user_intent_corrects_asr_or_denies',
    '_load_deletion_safety_thresholds',
    # β.4.9 severity decay vocab
    '_load_severity_vocab',
    '_load_severity_delta',
    '_SEVERITY_VOCAB_PATH',
    # P0+18-e.4 box + colorize
    '_box_newline',
    # P0+18-c.1 结构化标签剥离
    '_STRUCTURAL_TAGS',
    '_STRUCTURAL_TAG_BLOCK_RE',
    '_STRUCTURAL_TAG_ANY_RE',
    '_strip_structural_tag_blocks',
    '_strip_structural_tags_only',
    '_is_forming_structural_tag',
    '_MEMORY_UPDATE_RE',
    '_MEMORY_UPDATE_SELF_CLOSING_RE',
    'parse_memory_update_tags',
    'execute_memory_updates',
    # P0+18-e.2 上游 Audio Guard
    '_CHINESE_CHAR_RE',
    '_sentence_is_chinese_lean',
]


# ==========================================
# 🛡️ [P0+16 / 2026-05-15] Memory Deletion 安全：纯指代词识别
# ==========================================
# 09:22 误删事件根因：Sir 说"删掉那个东西"，Gatekeeper LLM 把口头禅"那个东西"
# 当 delete_memory_hint 直接传给 search_memory + delete top_5 → 误杀 5 条无关记忆，
# 且 Sir 真正想删的"两点睡觉"那条 commit 毫发无损（"嘴上 A 手上 B"）。
#
# 防御层（与 jarvis_hippocampus.py min_similarity 阈值 + Gatekeeper prompt 规则 14
# [REFERENCE DISAMBIGUATION] + 删除前 candidates preview 配合，共 4 层）：
# 在 delete 路径入口拦截 hint == 纯指代词，让 Jarvis 主动问 Sir 澄清具体所指。
#
# 设计原则：剥掉所有指代/虚词后，剩余有效字符 < 2 → 视为纯指代。
#   '那个东西'  → ''        → True  （拒绝删除）
#   '两点睡觉'  → '两点睡觉' → False （正常删除）
#   '那个文件'  → '文件'    → False （正常删除，含具体名词）
#   'that bug' → 'bug'    → False （含具体名词）
_REFERENCE_TOKENS = (
    # 中文指代/量词/虚词
    '那个', '这个', '那', '这', '它', '它们',
    '东西', '玩意儿', '玩意', '记忆', '记录', '条', '段', '次', '部分', '内容', '事',
    # 英文 pronoun + filler noun
    'that', 'this', 'it', 'thing', 'one', 'memory', 'record', 'entry', 'part',
    'the', 'a', 'an',
)


def _strip_reference_tokens(hint: str) -> str:
    """剥掉所有指代/虚词。先剥长的避免子串吃掉超集。"""
    norm = (hint or '').strip().lower()
    for tok in sorted(_REFERENCE_TOKENS, key=len, reverse=True):
        norm = norm.replace(tok, '')
    return norm.strip()


def _is_reference_only_hint(hint: str) -> bool:
    """[P0+16 / 2026-05-15] 判定 delete_memory_hint 是否仅是纯指代词。
    剥掉指代词后剩余有效字符（去空格去标点）< 2 → True，应拒绝删除。"""
    if not hint:
        return True
    stripped = _strip_reference_tokens(hint)
    cleaned = re.sub(r'[\s\W_]+', '', stripped, flags=re.UNICODE)
    return len(cleaned) < 2


# ==========================================
# 🛡️ [P0+18-a.5 / 2026-05-15] Memory Deletion 第 5 层守卫：物理文件删除意图识别
# ==========================================
# 13:03:37 实测复发：Sir 说"帮我把 D:\\Jarvis\\test_dummy.txt 这个文件删了"
# Gatekeeper LLM 误把它解读成"删 STM 中关于这个文件的记忆条目"，触发 delete_memory_hint
# = 'D盘 test.txt 文件'，又一次删了 5 条无辜记忆（ID=110/9/5/194/198 P0+16 复发）。
#
# 根因：hint 含具体名词不是纯指代词（防御 1 不拦），相似度 0.68-0.72 过 0.45 阈值（防御 2 不拦），
#       Gatekeeper prompt 规则 14 教不动 1.5B LLM 区分"删物理文件 vs 删记忆条目"。
#
# 第 5 层守卫：含明显的物理文件 / 文件夹 / 文件路径 / 文件后缀关键词 → 直接拒绝触发 delete_memory，
# 让主脑走 file_operator_hands.delete 路径（PromiseExecutor + dangerous skill 二次确认正轨）。
_PHYSICAL_FILE_DELETE_MARKERS = (
    # 文件后缀（覆盖大部分常见文件）
    '.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.xml', '.yaml', '.yml',
    '.exe', '.bat', '.ps1', '.sh', '.dll', '.bin', '.zip', '.rar', '.7z', '.tar', '.gz',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.ico',
    '.mp3', '.mp4', '.wav', '.flac', '.mkv', '.mov', '.avi', '.webm',
    '.log', '.csv', '.tsv', '.db', '.sqlite', '.cfg', '.ini', '.toml',
    # 路径分隔符
    '\\', '/',
    # 中文盘符 / 目录名
    'd盘', 'c盘', 'e盘', 'f盘', 'g盘', 'h盘',
    '桌面', 'desktop', 'documents', 'downloads', 'pictures',
    # 中英"文件" / "文件夹" / "目录" 关键词（必须独立成词或紧贴名词）
    '文件夹', '文件', '目录', '文档',
    'folder', 'directory', 'file ', 'file.', 'doc ', 'doc.',
    # path 变量（D:\xxx / d://xxx）
    'd:', 'c:', 'e:', 'f:',
)


def _is_physical_file_delete_intent(hint: str) -> bool:
    """[P0+18-a.5] 判定 delete_memory_hint 是否其实指向"物理文件删除"意图。
    True → 应该拒绝触发 delete_memory（让主脑走 file_operator_hands.delete + PromiseExecutor 正轨）。
    
    检测逻辑：hint 小写后含任一 PHYSICAL_FILE_DELETE_MARKERS → True
    
    示例：
      'D盘 test.txt 文件'  → True（含 'd盘' / '.txt' / '文件'）
      '桌面那个文档'        → True（含 '桌面' / '文档'）
      '我桌面的图'         → True（含 '桌面'）
      '两点睡觉的记忆'      → False（没物理文件 marker）
      '那个 bug'           → False
    """
    if not hint:
        return False
    norm = hint.strip().lower()
    if not norm:
        return False
    for marker in _PHYSICAL_FILE_DELETE_MARKERS:
        if marker in norm:
            return True
    return False


# ==========================================
# 🛡️ [P0+20-β.4.7 / 2026-05-18] Memory Deletion 第 6/7/8 层守卫 — Sir 21:45 实测 BUG 治本
# ==========================================
# 21:45 实测复发：Sir 实际说"嗯哎, 没有没有刚才说的这个什么 out的, 这是这是识别错误啊.
# 我没跟你讲这个话" — 但 ASR 误识别前一轮为 "you out了", Gatekeeper LLM 误把
# "识别错误啊" 解读成 "Sir 想删除关于 you out了 的记忆", 抽出 delete_memory_hint='you out了'.
# 5 层 P0+16 防御依次失守: hint 不是纯指代词 (L1)/不是文件 (L5)/sim=0.67-0.78 过 0.45 (L2),
# Gatekeeper prompt 规则 14 教不到 "识别错误" 这个新模式 (L4), preview 只 log 不阻塞 (L3).
# 误删 5 条无关记忆 (ID 1088/972/1078/1035/821).
#
# 第 6/7/8 层守卫 (准则 6.5 全部 vocab 化, 不在 .py 写死 keyword):
#   L6 (_user_intent_has_explicit_delete_verb): cmd 必含显式删除动词
#       (memory_pool/memory_deletion_vocab.json deletion_verb category)
#   L7 (_load_deletion_safety_thresholds): top_k=1 + sim≥0.85 (vocab _meta.thresholds)
#   L8 (_user_intent_corrects_asr_or_denies): cmd 含 memory_correction patterns
#       ('识别错误'/'我没'/'其实'/'搞错了' 等) → Sir 在纠正 ASR, deletion 必拒
#       复用 jarvis_directives.get_memory_correction_patterns() (β.3.4-vocab3)

_DELETION_VOCAB_PATH = os.path.join('memory_pool', 'memory_deletion_vocab.json')
_DELETION_VOCAB_CACHE: Dict = {'mtime': 0.0, 'data': None}


def _load_deletion_vocab() -> Dict:
    """读 memory_deletion_vocab.json (mtime cache + fail-safe). 损坏返 seed defaults."""
    seed = {
        '_meta': {'thresholds': {'min_similarity': 0.85, 'top_k_default': 1}},
        'patterns': [
            {'category': 'deletion_verb', 'keywords':
             ['删', 'delete', 'remove', 'forget', '去掉', '清除']},
        ],
    }
    p = _DELETION_VOCAB_PATH
    if not os.path.exists(p):
        return seed
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return seed
    if _DELETION_VOCAB_CACHE['mtime'] == mt and _DELETION_VOCAB_CACHE['data'] is not None:
        return _DELETION_VOCAB_CACHE['data']
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get('patterns'), list):
            return seed
        _DELETION_VOCAB_CACHE['mtime'] = mt
        _DELETION_VOCAB_CACHE['data'] = data
        return data
    except (OSError, json.JSONDecodeError):
        return seed


def _user_intent_has_explicit_delete_verb(cmd: str) -> bool:
    """[β.4.7 L6] cmd (用户原话) 是否含显式删除动词.

    True → 允许走 memory deletion (但仍要 L1/L2/L3/L5/L7/L8 验)
    False → cmd 没说"删/delete/remove/forget" 等 → 拒触发 deletion
            (典型场景: ASR 误识别一个像意图的词 / Gatekeeper 错抽 hint)

    keyword 来源: memory_pool/memory_deletion_vocab.json
    fail-safe: vocab 损坏 → seed 6 词 fallback
    """
    if not cmd:
        return False
    norm = cmd.lower().strip()
    vocab = _load_deletion_vocab()
    for pat in vocab.get('patterns', []):
        if not isinstance(pat, dict):
            continue
        if pat.get('category') != 'deletion_verb':
            continue
        if pat.get('state', 'active') != 'active':
            continue
        for kw in pat.get('keywords', []) or []:
            if not kw:
                continue
            if kw.lower() in norm:
                return True
    return False


def _user_intent_corrects_asr_or_denies(cmd: str) -> bool:
    """[β.4.7 L8] cmd 是否在纠正 ASR / 否认 / 澄清 (典型 Sir 21:45 场景).

    True → Sir 在说"识别错了 / 我没说过 / 其实是 X / 搞错了" 等 → memory deletion 必拒
           (复用 memory_correction_vocab.json patterns, β.3.4-vocab3)
    False → 普通对话, 不影响 deletion 判定

    fail-safe: jarvis_directives import 失败 → 返 False (不影响主链)
    """
    if not cmd:
        return False
    norm = cmd.lower().strip()
    try:
        from jarvis_directives import get_memory_correction_patterns
    except Exception:
        return False
    try:
        patterns = get_memory_correction_patterns() or ()
    except Exception:
        return False
    for kw in patterns:
        if not kw:
            continue
        if kw.lower() in norm:
            return True
    return False


def _load_deletion_safety_thresholds() -> Dict[str, float]:
    """[β.4.7 L7] 读 memory_deletion_vocab.json _meta.thresholds.

    返 {'min_similarity': float, 'top_k_default': int}.
    fail-safe: vocab 缺失 / 损坏 → seed (sim=0.85, top_k=1).
    """
    vocab = _load_deletion_vocab()
    meta = vocab.get('_meta') if isinstance(vocab, dict) else {}
    thr = meta.get('thresholds') if isinstance(meta, dict) else {}
    if not isinstance(thr, dict):
        thr = {}
    return {
        'min_similarity': float(thr.get('min_similarity', 0.85) or 0.85),
        'top_k_default': int(thr.get('top_k_default', 1) or 1),
    }


# ==========================================
# � [P0+20-β.4.9 / 2026-05-19] Severity Decay vocab 化 (准则 6.5)
# ==========================================
# Sir 反馈: 不同 concern 重要度差异大. 旧硬编码 ±0.2/0.1 不分 concern 类型.
# 治本: memory_pool/severity_decay_vocab.json _meta.thresholds + per_concern.
# fail-safe: vocab 缺/坏 → seed default (-0.20 fulfilled / +0.10 broken).
# Sir CLI 改 vocab 即生效 (mtime cache reload).

_SEVERITY_VOCAB_PATH = os.path.join('memory_pool', 'severity_decay_vocab.json')
_SEVERITY_VOCAB_CACHE: Dict = {'mtime': 0.0, 'data': None}


def _load_severity_vocab() -> Dict:
    """读 severity_decay_vocab.json (mtime cache + fail-safe).
    返 dict 含 _meta.thresholds + per_concern. 损坏返 seed default."""
    seed = {
        '_meta': {
            'thresholds': {
                'default_fulfilled_delta': -0.20,
                'default_broken_delta': 0.10,
            }
        },
        'per_concern': {},
    }
    p = _SEVERITY_VOCAB_PATH
    if not os.path.exists(p):
        return seed
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return seed
    if _SEVERITY_VOCAB_CACHE['mtime'] == mt and _SEVERITY_VOCAB_CACHE['data'] is not None:
        return _SEVERITY_VOCAB_CACHE['data']
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return seed
        _SEVERITY_VOCAB_CACHE['mtime'] = mt
        _SEVERITY_VOCAB_CACHE['data'] = data
        return data
    except (OSError, json.JSONDecodeError):
        return seed


def _load_severity_delta(concern_id: str, verdict: str) -> float:
    """[β.4.9] 读 concern + verdict 对应的 severity delta.

    Args:
        concern_id: e.g. 'sir_sleep_streak'
        verdict: 'fulfilled' / 'broken'

    Returns:
        float delta (fulfilled<0 / broken>0). per_concern 覆盖优先, 没则 default.
        fail-safe: 任何异常 → 返默认 (-0.2 / +0.1).
    """
    default = -0.20 if verdict == 'fulfilled' else 0.10
    if verdict not in ('fulfilled', 'broken'):
        return 0.0
    try:
        vocab = _load_severity_vocab()
        meta = vocab.get('_meta', {})
        thr = meta.get('thresholds', {}) if isinstance(meta, dict) else {}
        default_key = f'default_{verdict}_delta'
        default = float(thr.get(default_key, default) or default)
        per = vocab.get('per_concern', {})
        if isinstance(per, dict) and concern_id in per:
            concern_cfg = per[concern_id]
            if isinstance(concern_cfg, dict) and verdict in concern_cfg:
                return float(concern_cfg[verdict])
    except Exception:
        pass
    return default


# ==========================================
# �� [P0+18-e.4 / 2026-05-15] 多行 box 边框 + ANSI 色彩
# ==========================================
def _box_newline(text: str) -> str:
    """确保多行文本的每一行都有 ║ 边框前缀。
    
    [P0+18-e.4 / 2026-05-15] 加 ANSI 色彩分区 —— 单行 emoji-tag 匹配后整行着色。
    日志文件保持纯文本（TeeStream 已 strip ANSI）。
    """
    # [P0+18-e.4] 单行整体着色（无 \n 的最常见情况）
    if '\n' not in text:
        try:
            from jarvis_utils import colorize_terminal_line
            return colorize_terminal_line(text)
        except Exception:
            return text
    # 多行情况：按行 colorize + 续行加 ║ 前缀
    try:
        from jarvis_utils import colorize_terminal_line as _color_line
    except Exception:
        _color_line = lambda x: x  # type: ignore
    result = []
    i = 0
    while i < len(text):
        if text[i] == '\n':
            result.append('\n')
            if i + 1 < len(text) and text[i + 1] == '║':
                pass
            else:
                result.append('║ ')
        else:
            result.append(text[i])
        i += 1
    joined = ''.join(result)
    # 多行 colorize：按 \n 切，每行单独上色
    try:
        return '\n'.join(_color_line(ln) for ln in joined.split('\n'))
    except Exception:
        return joined


# ==========================================
# 🏷️ [P0+18-c.1 / 2026-05-15] 结构化标签 block-level 剥离
# ==========================================
# 修 Sir 17:22 实测 BUG：`<PROMISE>{"goal":..., "steps":[...]}</PROMISE>` 整段 JSON
# 既被终端 print 又被 _put_audio 喂给 TTS 念出。
#
# 旧防线只挡 `<FAST_CALL>...</FAST_CALL>` 一种 + 通用 `<[^>]+>` 只剥标签字符串本身、
# 保留中间 JSON 文本 → 喂给 TTS。
#
# 修法：抽统一 helper 把 5 类"结构化标签 + 内容"整块剥掉。所有 stream_chat /
# stream_chat_cloud_followup 的 clean_full / final_clean / 收尾 buffer 都调它，
# splitter 的 `is_forming_tag` 守门也用 _STRUCTURAL_TAGS 集合判断。
# 🩹 [β.2.9.9 / 2026-05-18] Sir 10:51 诚信审计加 MEMORY_UPDATE — Sir 纠正记忆时
# Jarvis 用 <MEMORY_UPDATE field="X" old="..." new="..."> 真做记录写盘 (而非空
# 头话 "I've updated"). 见 jarvis_directives.py:memory_update_honesty.
# MEMORY_UPDATE 是 self-closing tag (无 children) — block_re 也匹配单标签.
_STRUCTURAL_TAGS = ('FAST_CALL', 'PROMISE', 'ACTIVATE_PLAN', 'CANCEL_PLAN',
                     'RESUME_PLAN', 'MEMORY_UPDATE')
# 🩹 [β.2.9.9] paired tags (必须闭合才剥, 半成态保留在 buffer 等下一 token)
_STRUCTURAL_TAG_BLOCK_RE = re.compile(
    r'<(?:FAST_CALL|PROMISE|ACTIVATE_PLAN|CANCEL_PLAN|RESUME_PLAN|MEMORY_UPDATE)\b[^>]*>'
    r'.*?'
    r'</(?:FAST_CALL|PROMISE|ACTIVATE_PLAN|CANCEL_PLAN|RESUME_PLAN|MEMORY_UPDATE)>',
    re.DOTALL,
)
# 🩹 [β.2.9.9] MEMORY_UPDATE 单独支持 self-closing 形式 (<MEMORY_UPDATE attrs/>)
_MEMORY_UPDATE_SELF_CLOSING_RE = re.compile(
    r'<MEMORY_UPDATE\b[^>]*/>',
    re.IGNORECASE,
)
_STRUCTURAL_TAG_ANY_RE = re.compile(
    r'</?(?:FAST_CALL|PROMISE|ACTIVATE_PLAN|CANCEL_PLAN|RESUME_PLAN|MEMORY_UPDATE)\b[^>]*/?>'
)
# 🩹 [β.2.9.9] MEMORY_UPDATE 单独 regex (self-closing 形式 + 含 attributes)
_MEMORY_UPDATE_RE = re.compile(
    r'<MEMORY_UPDATE\s+([^>]+?)\s*/?>',
    re.IGNORECASE,
)


def parse_memory_update_tags(text: str) -> list:
    """从 LLM 输出抽 <MEMORY_UPDATE field="X" old="A" new="B"> 标签.

    返回 [{'field': str, 'old': str, 'new': str}, ...]
    准则 5: 主脑只有发了 tag 才算真"更新", 否则被 directive 拦"已更新"假话.
    """
    if not text or '<MEMORY_UPDATE' not in text.upper():
        return []
    out = []
    for m in _MEMORY_UPDATE_RE.finditer(text):
        attrs_str = m.group(1)
        attrs = {}
        for am in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', attrs_str):
            attrs[am.group(1).lower()] = am.group(2)
        if 'field' in attrs and 'new' in attrs:
            out.append({
                'field': attrs.get('field', ''),
                'old': attrs.get('old', ''),
                'new': attrs.get('new', ''),
            })
    return out


def execute_memory_updates(updates: list, source: str = 'llm_tag') -> int:
    """真执行 MEMORY_UPDATE: 写到 memory_pool/profile_corrections.jsonl.

    准则 5: 这是主脑说"已更新"的唯一合法路径. 写完 Sir 在 dashboard 能看到.
    返回成功写入数.
    """
    if not updates:
        return 0
    import json as _json
    import os as _os
    import time as _time
    path = _os.path.join("memory_pool", "profile_corrections.jsonl")
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    n = 0
    try:
        with open(path, 'a', encoding='utf-8') as f:
            for u in updates:
                record = {
                    'time': _time.strftime('%H:%M:%S'),
                    'iso': _time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'ts': _time.time(),
                    'source': source,
                    'field': u.get('field', ''),
                    'old': str(u.get('old', ''))[:200],
                    'new': str(u.get('new', ''))[:200],
                    'confidence': 1.0,  # 主脑显式发 tag 高置信
                }
                f.write(_json.dumps(record, ensure_ascii=False) + '\n')
                n += 1
    except Exception:
        pass
    return n


def _strip_structural_tag_blocks(text: str) -> str:
    """整块剥离 <TAG>...</TAG> 内容（含中间 JSON / 任何 payload）。
    成对闭合的才剥；半成形态 `<PROMISE>...<EOF>` 不剥（保留在 buffer 里等下一片 token）。

    🩹 [β.2.9.9] MEMORY_UPDATE 还可以是 self-closing 形式 (<MEMORY_UPDATE attrs/>),
    单独跑一次自闭合 regex 也剥掉.
    """
    text = _STRUCTURAL_TAG_BLOCK_RE.sub('', text)
    text = _MEMORY_UPDATE_SELF_CLOSING_RE.sub('', text)
    return text


def _strip_structural_tags_only(text: str) -> str:
    """只剥剩余的孤立标签字符串本身（兜底防御，理论上 `_strip_structural_tag_blocks` 跑过后不会再有）"""
    return _STRUCTURAL_TAG_ANY_RE.sub('', text)


def _is_forming_structural_tag(text: str) -> bool:
    """检测 text 里是否有任何 _STRUCTURAL_TAGS 开未闭（即流式半成 tag）"""
    for tag in _STRUCTURAL_TAGS:
        if f'<{tag}>' in text and f'</{tag}>' not in text:
            return True
    return False


# ==========================================
# 🔊 [P0+18-e.2 / 2026-05-15] 上游 Audio Guard helper —— sentence splitter 处提前拦中文
# ==========================================
# 修 Sir 18:22 实测 BUG (jarvis_20260515_182238.log:479, 953)：
#   Memory Correction "Original record not found" 兜底分支结束后，主脑下一句 reply 直接
#   产 Chinese-only sentence（如 "并归档了那个已经过期的快递提醒。我会确保..."），
#   LLM 没加 ---ZH--- 分隔符（持续中文上下文 → LLM 漂到中文），splitter 把中文喂给
#   _put_audio → 兜底 Audio Guard 拦下 → 但 log 里仍可见 "拦截含中文的 TTS 输入" warning。
#
# 修法：splitter 切到一句话时,如果句子含中文且 is_subtitle_mode 为 False（没见过 ---ZH---），
# 视为"隐式 subtitle 模式"，从此后所有 chunk 都进 subtitle_queue("zh") 而不进 TTS。
# 这样既保留中文字幕给 Sir 看，又彻底杜绝中文进 TTS 通路。
_CHINESE_CHAR_RE = re.compile(r'[\u4e00-\u9fa5]')


def _sentence_is_chinese_lean(sentence: str) -> bool:
    """判定句子是否"以中文为主"：含 ≥3 个汉字 或 汉字占比 > 30%。
    单个汉字（如人名"张三"被中文人名 token 化）不算泄漏。
    """
    if not sentence:
        return False
    cjk = _CHINESE_CHAR_RE.findall(sentence)
    if len(cjk) >= 3:
        return True
    if len(sentence) > 0 and len(cjk) / max(len(sentence), 1) > 0.30:
        return True
    return False


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

