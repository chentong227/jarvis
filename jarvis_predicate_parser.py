# -*- coding: utf-8 -*-
"""
[P0+20-β.2.8.9 / 2026-05-17] PredicateParser — Gatekeeper 后置 LLM Parser

Sir 准则 6 (拒绝硬编码) + Predicate 4 层架构 L3 落地.

设计原则:
  - Gatekeeper 主 prompt 不动 (避免污染主路径)
  - 检测到潜在条件触发模式 (regex 启发式) → 启动独立小 LLM call
  - LLM 看 predicate library 自动 dump prompt + user_text → 输出 condition JSON
  - 失败 → 静默 fallback 老 deadline_str 路径, 不破坏现有
  - 解析成 Predicate object → 传 add_commitment(commit_type='conditional_reminder')

不硬编码 mapping (e.g. "导出 → Premiere"): 只给 LLM library 描述 + schema 示例,
让 LLM 自己理解语义 + 组合 predicate. 新加 predicate 自动出现在 library prompt.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# 启发式: 是否值得跑 predicate parser? (节省 LLM 调用成本)
# ============================================================

# 含 "条件→行动" 句式 → 值得跑 (注意不是"识别为某 type", 只是 gate)
_COND_HINT_PATTERNS_ZH = [
    r'等我?\s*\S+\s*(完|结束|做完|搞完|忙完|后)',  # 等我导出完 / 等做完 / 等忙完
    r'(完|结束|做完|搞完|忙完|关掉)\s*(以?后|之后|了)?\s*(就|提醒|告诉|让|帮)',
    r'(等|当|要是|如果|只要)\s*\S+\s*(就|再|然后)',
    r'见到\s*\S+\s*(就|告诉|提醒)',
    r'打开\s*\S+\s*的?时候',
    r'下次\s*\S+\s*(就|时|再)',
    r'到\s*\S+\s*的时候',
]
_COND_HINT_PATTERNS_EN = [
    r'\bafter\s+i\s+\S+',
    r'\bonce\s+i\s+\S+',
    r'\bwhen\s+i\s+\S+',
    r'\bas\s+soon\s+as\s+',
    r'\bremind\s+me\s+(after|when|once|if)',
]


def looks_like_conditional(text: str) -> bool:
    """启发式判断 user_text 是否含条件触发模式. 不算硬编码 —
    只是省 LLM 调用成本的 gate (LLM 不到不调). 不命中也不影响 — 走老路径."""
    if not text or len(text) < 5:
        return False
    t_l = text.lower()
    for pat in _COND_HINT_PATTERNS_ZH:
        if re.search(pat, text):
            return True
    for pat in _COND_HINT_PATTERNS_EN:
        if re.search(pat, t_l):
            return True
    return False


# ============================================================
# Prompt 构造
# ============================================================

def build_parser_prompt(user_text: str) -> str:
    """构造 predicate parser LLM prompt. library 自动 dump (准则 6)."""
    from jarvis_predicate import predicate_library_prompt
    lib = predicate_library_prompt()
    return f"""You are a SEMANTIC PARSER. Translate a Sir-issued conditional reminder
into a structured predicate JSON tree. The Watcher will evaluate this predicate
each tick — when it returns true, a nudge fires.

USER TEXT (verbatim):
\"\"\"{user_text}\"\"\"

{lib}

OUTPUT RULES:
- If user is NOT requesting a conditional reminder (e.g. just chatting,
  or it's a fixed-time-only reminder like "10pm wake me"), output: null
- Otherwise output ONE JSON object: {{"condition": <predicate_tree>, "action_text": "<what Jarvis should say when triggered>"}}
- predicate_tree is a recursive JSON: {{"type": "...", <args>}} or {{"type": "AND"|"OR", "args": [...]}} or {{"type": "NOT", "arg": ...}}
- Be CONSERVATIVE: if not clearly mappable to library, output null (Watcher falls back to time-anchored path).
- action_text is what to remind Sir of when predicate fires (1 sentence, ≤ 20 words).

EXAMPLES (schema only — DO NOT pattern-match user keywords against these):
  User: "等我做完那件事就提醒我做下一件"
  Output: {{"condition": {{"type": "process_exit", "name": "<infer from context>"}}, "action_text": "<infer>"}}

  User: "下次看到 XYZ 应用打开告诉我"
  Output: {{"condition": {{"type": "window_title_contains", "keyword": "XYZ"}}, "action_text": "<infer>"}}

Now output the JSON for the USER TEXT above. Only the JSON, no markdown, no commentary.
"""


# ============================================================
# 执行 + 解析
# ============================================================


def parse_user_text_to_predicate(user_text: str,
                                    llm_call_fn,
                                    timeout_s: float = 8.0) -> Optional[dict]:
    """跑 LLM 解析 user_text → 返回 {predicate, action_text} 或 None.

    llm_call_fn: callable(prompt: str) -> str (sync). 调用方提供, 用现有 KeyRouter.
    """
    if not looks_like_conditional(user_text):
        return None  # gate 不命中, 不调 LLM

    prompt = build_parser_prompt(user_text)
    try:
        resp = llm_call_fn(prompt)
    except Exception as e:
        bg_log(f"⚠️ [PredicateParser] llm_call err: {e}")
        return None

    if not resp:
        return None
    resp = str(resp).strip()
    # 移除 markdown code fence (如果 LLM 包了)
    if resp.startswith('```'):
        resp = re.sub(r'^```\w*\n?', '', resp)
        resp = re.sub(r'\n?```$', '', resp)
        resp = resp.strip()

    if resp.lower() == 'null' or resp == '':
        return None

    try:
        data = json.loads(resp)
    except Exception as e:
        bg_log(f"⚠️ [PredicateParser] json parse err: {e}, resp={resp[:200]!r}")
        return None

    if not isinstance(data, dict):
        return None
    cond = data.get('condition')
    if not cond:
        return None

    # 验证 predicate 合法
    from jarvis_predicate import parse_predicate
    pred = parse_predicate(cond)
    if pred is None:
        bg_log(f"⚠️ [PredicateParser] parse_predicate failed for {cond}")
        return None

    return {
        'predicate': pred,
        'action_text': str(data.get('action_text', ''))[:200],
        'raw_json': data,
    }


# ============================================================
# Helper: 用 Gatekeeper 同一 key_router/safe_call 做 LLM
# ============================================================


def make_llm_call_fn(key_router, model: str = 'google/gemini-3-flash-preview',
                       max_tokens: int = 400):
    """构造 llm_call_fn — 封装 safe_openrouter_call. 给 Gatekeeper 路径用.
    用 key_router.acquire(...) 拿临时 key, 失败 release.
    """
    def _call(prompt: str) -> Optional[str]:
        key_name = None
        try:
            api_key, key_name, provider = key_router.get_key('predicate_parser')
            if not api_key:
                return None
            from jarvis_utils import safe_openrouter_call
            result = safe_openrouter_call(
                openrouter_key=api_key,
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return result
        except Exception as e:
            if key_name:
                try:
                    key_router.report_error(key_name, str(e))
                except Exception:
                    pass
            return None
        finally:
            if key_name:
                try:
                    key_router.release(key_name)
                except Exception:
                    pass
    return _call
