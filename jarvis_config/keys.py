# -*- coding: utf-8 -*-
"""
[P0+19-deps / 2026-05-XX] API Key Loader — 从 .env 读取所有 Jarvis 用到的 keys

设计原则
--------
1. **绝不硬编码** — 所有 keys 从 .env 文件读取（python-dotenv 加载到 os.environ）
2. **缺失即报错** — .env 缺 key 不允许"静默退化为占位符"，直接 raise + 给清晰诊断
3. **本文件入 .gitignore** — 虽然本文件只 import os.environ，但为防误改硬编码，
   作为额外防御层一并排除

用法（在 jarvis_nerve.py __main__ 或新拆出来的 main 里）::

    from jarvis_config.keys import load_keys
    keys = load_keys()
    key_router = KeyRouter(
        main_brain_key=keys.OPENROUTER_MAIN,
        google_keys=keys.GOOGLE_LIST,
        openrouter_keys=keys.OPENROUTER_LIST,
    )

新增 key 时（举例增加一个 OpenAI 主线 key）：
1. .env.example 加一行 OPENAI_MAIN=sk-REPLACE_ME
2. 本文件 JarvisKeys dataclass 加字段 OPENAI_MAIN: str
3. _load_required_env 列表加 'OPENAI_MAIN'
4. .env 真填进去（不入 git）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


# .env 必须存在的环境变量名列表
# 🆕 [Sir 2026-05-28 01:18] OPENROUTER_4/5 改可选 — Sir 之前 2 个 key 被 OpenRouter
# selective ban Google/Anthropic/OpenAI provider (申诉中). 副 key 池支持 2-5 个动态.
_REQUIRED_ENV_VARS = [
    "OPENROUTER_MAIN",
    "OPENROUTER_2",
    "OPENROUTER_3",
    "GEMINI_KEY",
    "GOOGLE_KEY_2",
    "GOOGLE_KEY_3",
]
# 可选 env vars — 缺失不 raise, OPENROUTER_LIST 自动 filter
_OPTIONAL_ENV_VARS = [
    "OPENROUTER_4",
    "OPENROUTER_5",
]


@dataclass
class JarvisKeys:
    """聚合所有 API keys。访问字段如同字典 key，但有 IDE 补全。"""

    # 主脑专用（KeyRouter 锁死）
    OPENROUTER_MAIN: str

    # 副 key 池（KeyRouter 随机抽 + 失败切）
    OPENROUTER_LIST: List[str] = field(default_factory=list)

    # Gemini 主 key（用于 hippocampus embedding 等高频小调用）
    GEMINI: str = ""

    # Google key 池（含 GEMINI 自身 + 2 个备份）
    GOOGLE_LIST: List[str] = field(default_factory=list)

    # 🆕 [Sir 2026-05-28 fix45] DeepSeek 专用 key (optional).
    # 不进 OPENROUTER_LIST 池 — 该 key 被 OpenRouter selective ban 海外, 进 pool
    # 会随机抽到给 google/gemini-* 调用导致 403. 由 jarvis_utils.safe_deepseek_call
    # 单独读, 仅供 llm_routing_vocab 路由命中时使用. 缺失或 'REPLACE_ME' → routing
    # 自动 disabled (故障开放).
    OPENROUTER_DS_ONLY: str = ""


def _load_dotenv_if_present() -> None:
    """加载 .env（如果存在）。.env 不存在时不报错，由 _check_required 报告缺失。"""
    try:
        from dotenv import load_dotenv
    except ImportError as e:
        raise RuntimeError(
            "python-dotenv 未安装。请跑：pip install -r requirements.txt"
        ) from e
    
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    dotenv_path = os.path.join(root, ".env")
    # 🆕 [2026-05-30] 编码鲁棒 — .env 若含非 UTF-8 字节 (编辑器把 em-dash '—' /
    # 智能引号 塞进注释), python-dotenv 严格 utf-8 解码会 UnicodeDecodeError 直接崩
    # 整个启动 (load_keys 在 nerve/daemon init 之前 → 主程序 / mirror 都起不来).
    # 治本: 正常加载; 解码失败 → errors='replace' 容错读后从 stream 加载.
    # key 值是 ASCII, 不受影响; 仅注释里的坏字节被替换为 U+FFFD. 准则 8 优雅:
    # 不让一个注释字节炸掉整个启动.
    try:
        load_dotenv(dotenv_path=dotenv_path)
    except (UnicodeDecodeError, ValueError):
        try:
            import io
            if os.path.exists(dotenv_path):
                with open(dotenv_path, "r", encoding="utf-8",
                          errors="replace") as _f:
                    _txt = _f.read()
                load_dotenv(stream=io.StringIO(_txt), override=True)
        except Exception:
            pass


def _check_required() -> None:
    """检查所有必需的 env vars 存在且非占位符。缺失则抛带诊断信息的 RuntimeError。"""
    missing = []
    placeholders = []
    for name in _REQUIRED_ENV_VARS:
        val = os.environ.get(name, "")
        if not val:
            missing.append(name)
        elif "REPLACE_ME" in val:
            placeholders.append(name)
    
    errors = []
    if missing:
        errors.append(f"⛔ 缺失 env vars: {missing}")
    if placeholders:
        errors.append(
            f"⛔ 仍为占位符（请填真实 key）: {placeholders}"
        )
    
    if errors:
        diagnostic = "\n".join(errors)
        raise RuntimeError(
            f"\n{'='*60}\n"
            f"Jarvis API Key 加载失败：\n{diagnostic}\n\n"
            f"修法：\n"
            f"  1. 确认根目录有 .env 文件（不存在则 copy .env.example）\n"
            f"  2. 编辑 .env 把 REPLACE_ME 替换成真实 key\n"
            f"  3. 重启 Jarvis\n"
            f"{'='*60}"
        )


def load_keys() -> JarvisKeys:
    """从 .env 加载所有 API keys。
    
    Raises:
        RuntimeError: 若 .env 缺失关键 key 或仍为占位符。
    """
    _load_dotenv_if_present()
    _check_required()
    
    # 🆕 [Sir 2026-05-28 01:18] OPENROUTER_LIST 动态收 2-5 个 key,
    # 自动 filter 空值 / DEPRECATED 占位符 (老 key 被 ban 时 .env 注释掉即可).
    _or_pool = []
    for name in ("OPENROUTER_2", "OPENROUTER_3",
                  "OPENROUTER_4", "OPENROUTER_5"):
        v = (os.environ.get(name, "") or "").strip()
        if v and "DEPRECATED" not in v and "REPLACE_ME" not in v:
            _or_pool.append(v)

    # 🆕 [Sir 2026-05-28 fix45] DeepSeek 专用 key — optional, 缺失/占位符 → 空字符串
    _ds_raw = (os.environ.get("OPENROUTER_DS_ONLY", "") or "").strip()
    if "REPLACE_ME" in _ds_raw or "DEPRECATED" in _ds_raw:
        _ds_raw = ""

    return JarvisKeys(
        OPENROUTER_MAIN=os.environ["OPENROUTER_MAIN"],
        OPENROUTER_LIST=_or_pool,
        GEMINI=os.environ["GEMINI_KEY"],
        GOOGLE_LIST=[
            os.environ["GEMINI_KEY"],
            os.environ["GOOGLE_KEY_2"],
            os.environ["GOOGLE_KEY_3"],
        ],
        OPENROUTER_DS_ONLY=_ds_raw,
    )
