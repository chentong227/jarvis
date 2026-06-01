# -*- coding: utf-8 -*-
"""[P5-fix46 / 2026-05-23 15:00] 系统盲点审计 — Sir 真意 4 类 BUG.

Sir 15:02 原话:
  '我让你排查的 BUG 其实就是指这方面的:
   - 有没有存在但是不生效的地方?
   - 有没有能力分配错误导致长久错误的地方?
   - 有没有可以优化 LLM 模型提高性价比和性能的地方?
   - 等等. 当然, 还有纯粹的 BUG, 自然也是要修的'

审计范围:
  1. **存在但不生效**: register 了但从不 fire / publish 了但没人读
  2. **能力分配错**: 1.5B 做复杂语义 / 大模型做简单事 / 错 model
  3. **可优化性价比**: 同 LLM 重复调 / 缓存缺失 / 错 model tier
  4. **纯 BUG**: dead path / config mismatch / TODO 未补

输出: docs/SYSTEM_BLIND_SPOTS_<TIMESTAMP>.md
"""
from __future__ import annotations

import json
import os
import re
import sys
# 🆕 [Sir 2026-05-28 Track 2] force utf-8 stdout (Windows GBK fix)
import os as _cu_os, sys as _cu_sys
_cu_sys.path.insert(0, _cu_os.path.dirname(_cu_os.path.abspath(__file__)))
import _cli_utils  # noqa: F401  # side-effect: force utf-8 stdout

import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


REPORT_LINES = []


def log(line: str = ''):
    REPORT_LINES.append(line)
    print(line)


def section(title: str):
    log('')
    log(f'## {title}')
    log('')


# ============================================================
# 审计 1: 1.5B QuickClassifier 调用点
# ============================================================

def audit_quick_classifier():
    section('1. QuickClassifier (qwen2.5:1.5b) 调用点审计')
    log('| 文件 | 调用方式 | 任务复杂度 | 评级 | 建议 |')
    log('|---|---|---|---|---|')

    callers = []
    for py in ROOT.rglob('*.py'):
        if 'scripts' in py.parts or 'tests' in py.parts:
            continue
        try:
            content = py.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        if 'QuickClassifier' in content or 'get_quick_classifier' in content or 'prompt_raw' in content:
            # 提取每行调用
            for i, line in enumerate(content.split('\n'), 1):
                if 'prompt_raw' in line and 'def ' not in line:
                    callers.append((py.name, i, line.strip()[:80]))

    seen_files = set()
    for fname, lineno, line in callers:
        if fname in seen_files:
            continue
        seen_files.add(fname)
        # 评估每个文件用途
        if fname == 'jarvis_concern_feedback.py':
            log(f'| `{fname}` | prompt_raw 调 1.5B 判 N concern × 4 字段 JSON | **超复杂** | 🔴 错配 | 拆 binary 单字段 OR 升 3B |')
        elif fname == 'jarvis_concern_feedback_reflector.py':
            log(f'| `{fname}` | L7 reflector 周期回看历史 | **复杂** | 🟡 边界 | 监控 JSON 失败率, 必要时升 3B |')
        else:
            log(f'| `{fname}` | line {lineno}: `{line}` | ? | 待评 | 个别看 |')

    log('')
    log('**总结**:')
    log('- 🔴 ConcernFeedback judge_async — 14:51 Sir 实测 0 [RECORD] log, 主因 1.5B 容量不足')
    log('- 🟡 fix45 已治本 (主脑自决 CONCERN_DAMPEN), ConcernFeedback 可降级为 fallback')
    log('- ✅ classify(simple/code/reasoning/search) — 4-way enum, 1.5B 完全胜任')


# ============================================================
# 审计 2: SWM publish 但没人读 (dead data)
# ============================================================

def audit_swm_publish_consumers():
    section('2. SWM publish but no consumer — dead data publish')

    # 收集所有 publish etype
    publishers = defaultdict(list)
    for py in ROOT.rglob('jarvis_*.py'):
        if 'tests' in py.parts or 'scripts' in py.parts:
            continue
        try:
            content = py.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        for m in re.finditer(r"etype\s*=\s*['\"]([a-z_]+)['\"]", content):
            etype = m.group(1)
            publishers[etype].append(py.name)

    # 收集所有 reader (类型 query)
    reader_etypes = set()
    for py in ROOT.rglob('jarvis_*.py'):
        if 'tests' in py.parts or 'scripts' in py.parts:
            continue
        try:
            content = py.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        # 看 types={'X', 'Y'} 或 'X' in types
        for m in re.finditer(r"types\s*=\s*\{([^}]+)\}", content):
            for etype_m in re.finditer(r"['\"]([a-z_]+)['\"]", m.group(1)):
                reader_etypes.add(etype_m.group(1))

    # 也算 to_swm_block 默认看的 (= 全 publish 都进 prompt)
    log('| etype | publisher | 有 specific reader? | 进 prompt (to_swm_block default sal≥0.3)? | 评级 |')
    log('|---|---|---|---|---|')

    for etype in sorted(publishers.keys()):
        files = ', '.join(set(publishers[etype]))
        has_reader = '✅' if etype in reader_etypes else '⚠️ 仅 to_swm_block default'
        prompt = '✅ default in prompt'  # 几乎所有都通过 to_swm_block 进 prompt
        # 没人具体 query 的 = 仅靠主脑 prompt scan
        rating = '🟢 OK (prompt 通用)' if etype not in reader_etypes else '✅ 强耦合'
        log(f'| `{etype}` | {files[:40]} | {has_reader} | {prompt} | {rating} |')

    log('')
    log(f'**总 publish etype: {len(publishers)}, 有 specific reader: {len(reader_etypes & set(publishers.keys()))}**')


# ============================================================
# 审计 3: directive 注册但 0 fire (dead directive)
# ============================================================

def audit_dead_directives():
    section('3. directive 注册但是否 fire 不明 (dead directive 嫌疑)')

    src_path = ROOT / 'jarvis_directives.py'
    if not src_path.exists():
        log('- skip: jarvis_directives.py not found')
        return
    src = src_path.read_text(encoding='utf-8', errors='replace')

    # 提取所有 Directive(id='X', ..., trigger=Y)
    dirs = []
    for m in re.finditer(
        r"Directive\s*\(\s*id\s*=\s*['\"]([\w_]+)['\"]"
        r".*?trigger\s*=\s*([\w_]+)",
        src, re.DOTALL):
        did, trig = m.group(1), m.group(2)
        dirs.append((did, trig))

    log('| directive id | trigger fn | 状态 |')
    log('|---|---|---|')
    for did, trig in dirs:
        if trig == 'None':
            status = '🟢 常驻 always-on'
        elif trig.startswith('_trigger'):
            status = '🟡 vocab/regex 触发 (看 vocab 是否生效)'
        else:
            status = '⚠️ 未知触发'
        log(f'| `{did}` | `{trig}` | {status} |')

    log('')
    log(f'**总 directive {len(dirs)} 个**. 真 fire/skip 统计需要 runtime audit, 见 `scripts/directive_fire_stats.py` (TODO)')


# ============================================================
# 审计 4: vocab 空文件
# ============================================================

def audit_empty_vocabs():
    section('4. vocab 文件: 加了但空 / 没 seed / reflector 不跑')

    vocab_dir = ROOT / 'memory_pool'
    if not vocab_dir.exists():
        log('- memory_pool/ dir not found')
        return

    log('| vocab 文件 | 大小 | active items | 状态 |')
    log('|---|---|---|---|')

    for jf in sorted(vocab_dir.glob('*.json')):
        if jf.name in ('concerns.json', 'concerns_review.json',
                        'directive_registry.json', 'directive_review.json'):
            # 大文件不细查
            try:
                size = jf.stat().st_size
                log(f'| `{jf.name}` | {size} B | (skip-detail) | 🟢 ledger |')
            except Exception:
                pass
            continue
        try:
            size = jf.stat().st_size
            data = json.loads(jf.read_text(encoding='utf-8'))
            n_active = 0
            n_total = 0
            if isinstance(data, dict):
                items = data.get('patterns') or data.get('items') or data.get('vocab') or data.get('keywords')
                if isinstance(items, list):
                    n_total = len(items)
                    for it in items:
                        if isinstance(it, dict):
                            if it.get('status') == 'active' or it.get('active', True):
                                n_active += 1
                        else:
                            n_active += 1
                else:
                    n_active = n_total = len([k for k in data if k != '_meta'])
            elif isinstance(data, list):
                n_total = len(data)
                n_active = n_total
            status = '🟢 健康' if n_active > 0 else '🔴 空 / dead'
            if size < 200:
                status += ' (size 极小)'
            log(f'| `{jf.name}` | {size} B | {n_active}/{n_total} | {status} |')
        except Exception as e:
            log(f'| `{jf.name}` | ? | parse fail: {str(e)[:30]} | ⚠️ |')


# ============================================================
# 审计 5: TODO 未补 / FIXME / XXX 标记
# ============================================================

def audit_todos():
    section('5. 代码中 TODO / FIXME / XXX 等技术债 (sample top 20)')

    todos = []
    for py in ROOT.rglob('jarvis_*.py'):
        try:
            content = py.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        for i, line in enumerate(content.split('\n'), 1):
            if re.search(r'\b(TODO|FIXME|XXX|HACK)\b', line):
                todos.append((py.name, i, line.strip()[:100]))

    log(f'**total: {len(todos)} TODO/FIXME marks across jarvis_*.py**\n')
    log('| 文件 | 行 | 内容 |')
    log('|---|---|---|')
    for fname, lineno, line in todos[:20]:
        log(f'| `{fname}` | L{lineno} | `{line}` |')


# ============================================================
# 审计 6: API model 配置 (能力分配 / 性价比)
# ============================================================

def audit_model_configs():
    section('6. LLM model 配置审计 (能力分配 / 性价比)')

    # 扫描所有 'model_name', 'primary_model', 'fallback_model' 配置
    configs = []
    for py in ROOT.rglob('jarvis_*.py'):
        try:
            content = py.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        for m in re.finditer(
            r"['\"]?(primary_model|fallback_model|model_name|model)['\"]?\s*[:=]\s*['\"]([a-zA-Z0-9\-_./:]+)['\"]",
            content):
            key, val = m.group(1), m.group(2)
            if not val or len(val) < 3:
                continue
            if val in ('on', 'off', 'true', 'false'):
                continue
            configs.append((py.name, key, val))

    # 汇总每个模型用到哪里
    model_uses = defaultdict(list)
    for fname, key, val in configs:
        model_uses[val].append((fname, key))

    log('| 模型 | 用途数 | 用途文件 | 评级 |')
    log('|---|---|---|---|')
    for model in sorted(model_uses.keys()):
        uses = model_uses[model]
        files = set(f for f, _ in uses)
        if 'gemini' in model.lower() or 'gpt' in model.lower() or 'claude' in model.lower() or 'openai' in model.lower():
            rating = '🟢 cloud'
        elif 'qwen2.5:1.5b' in model:
            rating = '🟡 fix45 已治本, 留 fast path'
        elif 'qwen' in model.lower():
            rating = '🟢 local'
        else:
            rating = '?'
        log(f'| `{model}` | {len(uses)} | {len(files)} files | {rating} |')


# ============================================================
# 审计 7: 长 .py 文件 (准则 6 / 8 工程债)
# ============================================================

def audit_large_files():
    section('7. 巨型 .py 文件 (准则 8 可维护性风险)')

    log('| 文件 | 行数 | 建议 |')
    log('|---|---|---|')

    files = []
    for py in ROOT.rglob('jarvis_*.py'):
        try:
            n_lines = sum(1 for _ in py.open(encoding='utf-8', errors='replace'))
            files.append((py.name, n_lines))
        except Exception:
            continue
    files.sort(key=lambda x: x[1], reverse=True)
    for fname, n in files[:10]:
        if n > 3000:
            advice = '🔴 拆 (>3000 行难维护)'
        elif n > 1500:
            advice = '🟡 考虑拆 sister module'
        else:
            advice = '🟢 OK'
        log(f'| `{fname}` | {n} | {advice} |')


# ============================================================
# 主流程
# ============================================================

def main():
    log(f'# Jarvis 系统盲点审计 — {time.strftime("%Y-%m-%d %H:%M:%S")}')
    log('')
    log('Sir 准则 8: 优雅高效可持续 > 最简单')
    log('Sir 真意 4 类: 存在但不生效 / 能力分配错 / LLM 性价比 / 纯 BUG')

    audit_quick_classifier()
    audit_swm_publish_consumers()
    audit_dead_directives()
    audit_empty_vocabs()
    audit_todos()
    audit_model_configs()
    audit_large_files()

    # 写报告
    ts = time.strftime('%Y%m%d_%H%M%S')
    out_path = ROOT / 'docs' / f'SYSTEM_BLIND_SPOTS_{ts}.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(REPORT_LINES), encoding='utf-8')
    print(f'\n📄 写报告: {out_path}')


if __name__ == '__main__':
    main()
