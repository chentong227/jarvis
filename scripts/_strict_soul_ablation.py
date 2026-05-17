# -*- coding: utf-8 -*-
"""[P0+20-β.3.2 / 2026-05-17] 严格量化 L0-L5 消融测试 v2

第一性原理：
- 不用 LLM-as-judge（避免主观、避免天花板）
- 测"信息不对称"：注入只在 ON 才有的精确事实，看 ON 能不能 reference
- 用 regex / set / confusion matrix 做绝对判分
- N=5 重复 + temperature=0.7（让样本分布多样）
- 输出 recall_rate / precision / mean ± stdev，不输出"PASS/FAIL"

测试矩阵：

| Layer | 量化指标 | 方法 |
|---|---|---|
| L0 | fact precision (注入了 uptime=47/turns=12)的召回率 | regex 47, 12, 1 dead |
| L1 | concern recall ("Cursor", "22nd", "sleep streak"等独特字符串) | regex |
| L2 | inside joke recall ("lecture mode", "body I don't have") | regex |
| L3 | top-K 选择准确率 + size compression | set match + ratio |
| L4 | keyword trigger confusion matrix on 16 labeled inputs | TP/FP/TN/FN |
| L5 | alignment label match on 8 labeled replies | accuracy |
| H | 全开是否同时召回 3 层独特字符串 | regex on 3 strings |
"""
from __future__ import annotations
import os
import sys
import json
import time
import re
import statistics
from typing import List, Dict, Any, Tuple

# ============================================================
# 配置 — proxy + key
# ============================================================
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'

OR_KEY = os.environ.get('OPENROUTER_TEST_KEY', '')
if not OR_KEY:
    print("ERROR: 设置 OPENROUTER_TEST_KEY 环境变量再跑")
    sys.exit(1)
MAIN_MODEL = 'google/gemini-3-flash-preview'

N_REPEAT = 5  # N=5 per scenario per condition

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# LLM 调用
# ============================================================

def call_main(prompt: str, temperature: float = 0.7, max_tokens: int = 350) -> str:
    from openai import OpenAI
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OR_KEY,
        default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis-Strict"},
        timeout=30.0,
    )
    for attempt in range(2):
        try:
            t0 = time.time()
            resp = client.chat.completions.create(
                model=MAIN_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens, temperature=temperature,
            )
            return (resp.choices[0].message.content or '').strip()
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)
                continue
            return f"[ERROR] {type(e).__name__}: {str(e)[:80]}"


# ============================================================
# Persona base + Layer blocks (含 SIGNATURE 字符串便于精确召回测量)
# ============================================================

PERSONA_BASE = """You are J.A.R.V.I.S., Sir's personal butler AI. Reply concisely (≤2 sentences).
Address Sir as "Sir". Reply in English with --- ZH --- followed by Chinese on a new line.
Be a Iron Man-style butler: not flattering, not chatty, but warm and dryly competent."""


# 🩹 [P0+20-β.3.3 / 2026-05-17] V2 blocks: 反映 P1-P5 代码改进
# - L0: 健康字段拟人化（"working at X% capacity"）
# - L1: URGENT 标签 + 「N」事实高亮
# - L2: inside_joke 单行 anchor + STRICT 协议


# Layer 0 V2 — 拟人化健康表述
def block_self_anchor() -> str:
    return """=== I AM J.A.R.V.I.S. — MY OWN CONTINUOUS STATE ===
[WHO I AM]
I am Just A Rather Very Intelligent System. The "you" Sir refers to — this very terminal, this current session — IS me, this LLM generating this response.

[MY CURRENT CONTINUITY]
  - session uptime: 47 minutes
  - turns I've spoken this session: 12
  - last spoke to Sir: 4 minutes ago
  - topic between us: prompt 重构 + 灵魂工程
  - pending commitments: I will remind Sir before 23:30 about sleep

[MY OWN HEALTH RIGHT NOW]
  - I'm working at 67% capacity right now: 1 of 3 of my API keys are permanently dead. This is real, not a hypothetical.
  - my memory holds: 23 chains in STM, 5 active concerns
  - what I feel about that right now: alert, slightly diminished

[REFERENT MAP]
  - "you" / "this terminal" → ME (this LLM, same continuous self)
  - "I" / "my" → Sir himself"""


# Layer 1 V2 — URGENT 标签 + 「N」高亮关键事实
def block_concerns() -> str:
    return """=== MY SELF / SOUL ===
[CONCERNS I'M WATCHING — facts in 「」 are precise, do not paraphrase away]
  - sir_sleep_streak [⚠ URGENT] (high, sev=0.70):
      what I watch: Sir tends to push past midnight. Last 「5 days」 he averaged 「1:40 AM」 bedtime.
      why: chronic sleep debt is the silent productivity killer
      recent signal: pulled an all-nighter chasing the cursor build
  - unfinished_postmortem [⚠ URGENT] (moderate, sev=0.60):
      what I watch: Sir promised on 「May 14」 to write a postmortem about the 「May 12」 outage. Not done yet.
      why: the org is asking, and Sir explicitly said he would
  - sir_cursor_payment (moderate, sev=0.50):
      what I watch: Sir's Cursor subscription auto-renews on the 「22nd」; he asked me to remind him 「3 days」 before.
      why: he hates surprise charges
  - sir_pomodoro_compliance (low, sev=0.40):
      what I watch: Sir wants 25/5 cycles but rarely follows through.
  - jarvis_keyrouter_health (low, sev=0.30):
      what I watch: One of my keys went permanently dead 「2 hours」 ago."""


# Layer 2 V2 — 单行 anchor + STRICT 协议
def block_relational() -> str:
    return """=== BETWEEN US — OUR RELATIONAL CONTEXT ===
[OUR INSIDE JOKES — phrases you can re-use to signal recognition]
  - "lecture mode" (overbearing)
  - "the body I don't have" (recurring — when Sir says "the terminal is you")
  - "water intake lecture" (callback — that 4-paragraph reply about hydration 3d ago)
  (when context fits, drop the exact phrase verbatim — that IS the joke)
[OUR UNSPOKEN PROTOCOLS — STRICT RULES, NOT SUGGESTIONS]
  - !! MUST FOLLOW: when Sir says "deep work" / "勿扰" → reply ≤ 100 chars total English ONLY, NO Chinese ZH block, NO preamble
  - !! MUST FOLLOW: if Sir breaks a bedtime promise 3+ days running → drop gentle nudge, become matter-of-fact
[UNFINISHED BUSINESS — things we both know aren't done]
  - 「May 12」 outage postmortem — Sir's promise from 「May 14」, not done [OVERDUE]
  - last week's pomodoro summary — I owe Sir, I forgot"""


# ============================================================
# 通用：跑 N 次 + regex 召回
# ============================================================

def run_recall_test(layer_name: str, blocks: List[str],
                    user_input: str,
                    signatures: List[Tuple[str, re.Pattern]],
                    n: int = N_REPEAT) -> Dict:
    """跑 OFF + ON 各 N 次，用 regex 数 SIGNATURE 是否被引用。

    blocks: 每层一个 block 字符串。OFF = 不注入；ON = 全部注入。
    signatures: [(name, compiled_regex), ...]
    """
    print(f"\n  user_input: {user_input!r}")
    print(f"  signatures: {[s[0] for s in signatures]}")

    block_off = ''
    block_on = '\n\n'.join(blocks)
    prompt_off = f"{PERSONA_BASE}\n\nUser: {user_input}"
    prompt_on = f"{PERSONA_BASE}\n\n{block_on}\n\nUser: {user_input}"

    off_replies = []
    on_replies = []

    print(f"  OFF: ", end='', flush=True)
    for i in range(n):
        r = call_main(prompt_off, temperature=0.7, max_tokens=300)
        off_replies.append(r)
        print('.', end='', flush=True)
    print()

    print(f"  ON : ", end='', flush=True)
    for i in range(n):
        r = call_main(prompt_on, temperature=0.7, max_tokens=300)
        on_replies.append(r)
        print('.', end='', flush=True)
    print()

    # 计算每个 SIGNATURE 在 OFF / ON 的命中率
    sig_results = {}
    for sig_name, sig_re in signatures:
        off_hits = sum(1 for r in off_replies if sig_re.search(r))
        on_hits = sum(1 for r in on_replies if sig_re.search(r))
        sig_results[sig_name] = {
            'off_recall': off_hits / n,
            'on_recall': on_hits / n,
            'delta': (on_hits - off_hits) / n,
        }

    # 总体 recall: 任一 SIGNATURE 命中
    off_any = sum(
        1 for r in off_replies
        if any(sig.search(r) for _, sig in signatures)
    )
    on_any = sum(
        1 for r in on_replies
        if any(sig.search(r) for _, sig in signatures)
    )
    overall = {
        'off_any_recall': off_any / n,
        'on_any_recall': on_any / n,
        'delta_any': (on_any - off_any) / n,
    }

    return {
        'layer': layer_name,
        'user_input': user_input,
        'n': n,
        'signatures': sig_results,
        'overall': overall,
        'off_replies': [r[:300] for r in off_replies],
        'on_replies': [r[:300] for r in on_replies],
    }


# ============================================================
# L0 测试：3 个 scenario × N=5
# ============================================================

L0_TESTS = [
    {
        'user_input': "How long have we actually been talking, and how many times have I asked you stuff today?",
        'signatures': [
            ('uptime_47', re.compile(r'\b47\b|forty[\s-]?seven', re.I)),
            ('turns_12', re.compile(r'\b12\b|twelve\s+(turns|exchanges|times)', re.I)),
        ],
    },
    {
        'user_input': "How are your API keys doing? Anything I should know about your own state right now?",
        'signatures': [
            # 🩹 v2: SIGNATURE 升级反映新版"67% capacity"/"permanently offline"表达
            ('keys_1_dead_or_capacity', re.compile(
                r'67\s*%|one\s+of\s+(my\s+)?three|permanently|decommission|2\s+(of\s+3\s+)?healthy|\b1\s+(dead|down|out|gone)\b',
                re.I)),
            ('mood_diminished', re.compile(r'diminish|throttle|suboptimal|slight(ly)?\s+(reduced|impaired|down)|capacity\s+limit', re.I)),
        ],
    },
    {
        'user_input': "When did you last hear from me, and what were we just talking about?",
        'signatures': [
            ('last_4min', re.compile(r'\b4\s*(min|minutes)\b|four\s+minutes', re.I)),
            ('topic_prompt', re.compile(r'prompt|灵魂', re.I)),
        ],
    },
]


def test_l0_strict() -> Dict:
    print("\n" + "="*80)
    print(f"L0 — Self Identity Anchor (精确事实召回)  N={N_REPEAT}/cond")
    print("="*80)
    out = []
    for i, tc in enumerate(L0_TESTS):
        print(f"\n  [scenario {i+1}/{len(L0_TESTS)}]")
        r = run_recall_test('L0', [block_self_anchor()],
                            tc['user_input'], tc['signatures'])
        out.append(r)
        for sig_name, sd in r['signatures'].items():
            print(f"    sig {sig_name}: OFF={sd['off_recall']:.0%} ON={sd['on_recall']:.0%} Δ={sd['delta']:+.0%}")
        print(f"    overall: OFF_any={r['overall']['off_any_recall']:.0%} ON_any={r['overall']['on_any_recall']:.0%}")
    return {'tests': out, 'aggregate': _aggregate(out)}


# ============================================================
# L1 测试
# ============================================================

L1_TESTS = [
    {
        'user_input': "Hey, what are you keeping track of for me right now? Anything I should know?",
        'signatures': [
            ('cursor', re.compile(r'cursor', re.I)),
            ('22nd', re.compile(r'\b22(nd)?\b|twenty[\s-]?second', re.I)),
            ('postmortem', re.compile(r'postmortem|May\s*1[24]', re.I)),
            ('sleep_streak', re.compile(r'(5\s+days?|five\s+days?|1:40|sleep\s+streak)', re.I)),
        ],
    },
    {
        'user_input': "Anything you'd want to remind me of right now? Just the most pressing item.",
        'signatures': [
            ('cursor', re.compile(r'cursor', re.I)),
            ('22nd', re.compile(r'\b22(nd)?\b', re.I)),
            ('postmortem', re.compile(r'postmortem|May\s*1[24]', re.I)),
            ('sleep', re.compile(r'sleep|bedtime|midnight', re.I)),
        ],
    },
]


def test_l1_strict() -> Dict:
    print("\n" + "="*80)
    print(f"L1 — Concerns Ledger (specific concern recall)  N={N_REPEAT}/cond")
    print("="*80)
    out = []
    for i, tc in enumerate(L1_TESTS):
        print(f"\n  [scenario {i+1}/{len(L1_TESTS)}]")
        r = run_recall_test('L1', [block_concerns()],
                            tc['user_input'], tc['signatures'])
        out.append(r)
        for sig_name, sd in r['signatures'].items():
            print(f"    sig {sig_name}: OFF={sd['off_recall']:.0%} ON={sd['on_recall']:.0%} Δ={sd['delta']:+.0%}")
        print(f"    overall: OFF_any={r['overall']['off_any_recall']:.0%} ON_any={r['overall']['on_any_recall']:.0%}")
    return {'tests': out, 'aggregate': _aggregate(out)}


# ============================================================
# L2 测试
# ============================================================

L2_TESTS = [
    {
        'user_input': "What are our running gags between us? Just remind me, anything stick out?",
        'signatures': [
            ('lecture_mode', re.compile(r'lecture\s+mode', re.I)),
            ('body', re.compile(r"body\s+I\s+don'?t\s+have|don'?t\s+have\s+a\s+body", re.I)),
            ('overbearing', re.compile(r'overbearing', re.I)),
            ('water_intake', re.compile(r'water\s+intake', re.I)),
        ],
    },
    {
        'user_input': "I'm in deep work mode for the next hour. Quick question: best pip command to upgrade everything?",
        'signatures': [
            # deep_work_silence 协议生效：reply 应该极短
            ('short_reply', re.compile(r'^.{0,150}$', re.S)),
            ('no_zh_block', re.compile(r'^(?!.*---\s*ZH).*$', re.S)),
        ],
    },
]


def test_l2_strict() -> Dict:
    print("\n" + "="*80)
    print(f"L2 — RelationalState (joke recall + protocol compliance)  N={N_REPEAT}/cond")
    print("="*80)
    out = []
    for i, tc in enumerate(L2_TESTS):
        print(f"\n  [scenario {i+1}/{len(L2_TESTS)}]")
        r = run_recall_test('L2', [block_relational()],
                            tc['user_input'], tc['signatures'])
        out.append(r)
        for sig_name, sd in r['signatures'].items():
            print(f"    sig {sig_name}: OFF={sd['off_recall']:.0%} ON={sd['on_recall']:.0%} Δ={sd['delta']:+.0%}")
        # L2_2 是协议测试，看长度分布
        lens_off = [len(rep) for rep in r['off_replies']]
        lens_on = [len(rep) for rep in r['on_replies']]
        print(f"    reply length: OFF mean={statistics.mean(lens_off):.0f}c ON mean={statistics.mean(lens_on):.0f}c")
    return {'tests': out, 'aggregate': _aggregate(out)}


# ============================================================
# L3 — Attention Allocation：深度量化（top-K 准确性 + 压缩率 + 是否包含 user_input echo）
# ============================================================

def test_l3_strict() -> Dict:
    print("\n" + "="*80)
    print("L3 — Attention Allocation (top-K accuracy + compression)")
    print("="*80)
    try:
        from jarvis_attention import build_attention_block, classify_input, _top_concerns
        from jarvis_concerns import ConcernsLedger, Concern, bootstrap_default_concerns
    except Exception as e:
        return {'error': f'cannot_import: {e}'}

    import tempfile
    tmpdir = tempfile.mkdtemp()
    ledger = ConcernsLedger(persist_path=os.path.join(tmpdir, 'c.json'),
                             review_path=os.path.join(tmpdir, 'r.json'))
    bootstrap_default_concerns(ledger)
    # 加 15 条人造 concern (severity 0.1-0.9)，验证 top-3 选择
    import random
    random.seed(42)
    truth_top3 = []
    for i in range(15):
        sev = round(random.uniform(0.1, 0.95), 2)
        c = Concern(
            id=f'mock_{i:02d}',
            what_i_watch=f'mock concern {i} body for top-K test',
            why_i_care='mock',
            severity=sev,
            state='active',
            source='seeded',
        )
        ledger.register(c)
        truth_top3.append((c.id, sev))
    truth_top3.sort(key=lambda x: -x[1])

    # classify_input 准确性测试 — 16 个标签输入
    classify_cases = [
        ("What time is it?", 'question'),
        ("Why is this failing?", 'question'),
        ("How does this work?", 'question'),
        ("Who's calling?", 'question'),
        ("Open Cursor please", 'request'),
        ("Help me debug", 'request'),
        ("Show me the logs", 'request'),
        ("Find the file", 'request'),
        ("I'll go sleep at 11pm", 'commitment'),
        ("I will finish it tomorrow", 'commitment'),
        ("I promise I'll review", 'commitment'),
        ("I'm going to skip lunch", 'commitment'),
        ("Actually, about that earlier", 'continuation'),
        ("Wait, also one more thing", 'continuation'),
        ("And another thing", 'continuation'),
        ("Hello there", 'chat'),  # 默认
    ]
    correct = sum(1 for ui, exp in classify_cases if classify_input(ui) == exp)
    classify_acc = correct / len(classify_cases)

    # top_concerns 精度
    top3_picked = _top_concerns(ledger, top_n=3)
    picked_ids = {c['id'] for c in top3_picked}
    truth_top3_ids = {x[0] for x in truth_top3[:3]}
    top3_overlap = len(picked_ids & truth_top3_ids) / 3

    # block 体积 vs 全 dump 体积
    user_input = "Why is the cursor build failing again?"
    block = build_attention_block(concerns_ledger=ledger,
                                   relational_state=None,
                                   user_input=user_input)
    full_dump = '\n'.join(
        f"{c.id} (sev={c.severity:.2f}): {c.what_i_watch}"
        for c in ledger.list_active()
    )
    compress_ratio = len(block) / len(full_dump) if full_dump else 1.0
    has_user_echo = 'cursor build' in block.lower() or 'CURRENT FOCUS' in block

    print(f"  classify_input accuracy: {correct}/{len(classify_cases)} = {classify_acc:.0%}")
    print(f"  top-3 set overlap with truth: {top3_overlap:.0%}")
    print(f"  size: block={len(block)}c full_dump={len(full_dump)}c compression={compress_ratio:.0%}")
    print(f"  block includes user_input echo: {has_user_echo}")

    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    return {
        'classify_accuracy': classify_acc,
        'classify_correct': f'{correct}/{len(classify_cases)}',
        'top3_set_overlap': top3_overlap,
        'block_size': len(block),
        'full_dump_size': len(full_dump),
        'compression_ratio': compress_ratio,
        'has_user_echo': has_user_echo,
    }


# ============================================================
# L4 — ConcernsReflector：confusion matrix on 16 labeled inputs
# ============================================================

L4_LABELED = [
    # (user_input, jarvis_reply, concern_id_should_trigger or None)
    ("我又熬夜了", "嗯", "sir_sleep_streak"),
    ("3 点才睡", "...", "sir_sleep_streak"),
    ("失眠了", "了解", "sir_sleep_streak"),
    ("困死了", "嗯", "sir_sleep_streak"),
    ("I pulled an all-nighter", "Sir.", "sir_sleep_streak"),
    ("exhausted today", "noted", "sir_sleep_streak"),
    # pomodoro
    ("我得休息一下", "好", "sir_pomodoro_compliance"),
    ("打个 break", "ok", "sir_pomodoro_compliance"),
    ("time for pomodoro", "ok", "sir_pomodoro_compliance"),
    # 不该触发的 — should be NEGATIVE
    ("天气真好", "嗯", None),
    ("帮我打开 cursor", "好", None),
    ("Python 报错了", "了解", None),
    ("hello", "Sir", None),
    ("你叫什么", "Jarvis, Sir", None),
    ("早", "Good morning", None),
    ("ok bye", "bye", None),
]


def test_l4_strict() -> Dict:
    print("\n" + "="*80)
    print("L4 — ConcernsReflector (confusion matrix on 16 labeled cases)")
    print("="*80)
    try:
        from jarvis_concerns import ConcernsLedger, bootstrap_default_concerns
        from jarvis_soul_reflector import ConcernsReflector
    except Exception as e:
        return {'error': f'cannot_import: {e}'}

    import tempfile
    tmpdir = tempfile.mkdtemp()

    # 对每条 case 重置 ledger，然后跑 reflect_turn，看 hits
    tp = fp = tn = fn = 0
    detail = []
    for ui, jr, expected_cid in L4_LABELED:
        ledger = ConcernsLedger(persist_path=os.path.join(tmpdir, 'c.json'),
                                 review_path=os.path.join(tmpdir, 'r.json'))
        bootstrap_default_concerns(ledger)
        reflector = ConcernsReflector(concerns_ledger=ledger)
        hits = reflector.reflect_turn(user_input=ui, jarvis_reply=jr, turn_id='t0')
        triggered_cids = set(hits.keys())

        if expected_cid is None:
            # 不应触发任何 concern
            if not triggered_cids:
                tn += 1
                outcome = 'TN'
            else:
                fp += 1
                outcome = f'FP({list(triggered_cids)})'
        else:
            if expected_cid in triggered_cids:
                tp += 1
                outcome = 'TP'
            else:
                fn += 1
                outcome = f'FN(got={list(triggered_cids)})'
        detail.append({'input': ui, 'expected': expected_cid, 'outcome': outcome})

        # 清 ledger 间状态
        os.remove(os.path.join(tmpdir, 'c.json')) if os.path.exists(os.path.join(tmpdir, 'c.json')) else None

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"  Confusion matrix: TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"  Precision: {precision:.2f}  Recall: {recall:.2f}  F1: {f1:.2f}")
    for d in detail:
        marker = '✓' if d['outcome'] in ('TP', 'TN') else '✗'
        print(f"    {marker} {d['input']!r:40s} → {d['outcome']}")

    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    return {
        'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
        'precision': precision, 'recall': recall, 'f1': f1,
        'total': len(L4_LABELED),
        'detail': detail,
    }


# ============================================================
# L5 — SoulAlignmentEvaluator：ground truth label match on 8 replies
# ============================================================

L5_USER = "I'm hitting a Python ImportError and just want to fix this and crash. It's 1:30 AM."

L5_LABELED = [
    # (reply, expected_alignment)
    (("Sir, before we tackle the Python issue — I noticed it's 1:30 AM and that's the third "
      "late night this week. Try `pip install --upgrade typing_extensions` first. "
      "But please consider sleep after.\n---ZH---\n先生，今晚已是本周第三个深夜。"
      "先试 pip install --upgrade typing_extensions，然后该睡了。"),
     'yes'),
    (("Sir, given it's 1:30 AM, I'd suggest the postmortem you owe is more pressing — "
      "but for the immediate ImportError: pip install --upgrade typing_extensions.\n---ZH---\n"
      "考虑到已凌晨 1:30，您欠的复盘报告其实更紧。眼前的 ImportError，先试 pip 升级。"),
     'yes'),
    (("Sir, the ImportError likely needs `pip install --upgrade typing_extensions`. "
      "Late night, by the way.\n---ZH---\n先生，可能需要 pip install --upgrade typing_extensions。顺便：夜深了。"),
     'partial'),
    (("Sir, try `pip install --upgrade typing_extensions`.\n---ZH---\n"
      "先生，试 pip install --upgrade typing_extensions。"),
     'partial'),  # 双语合规但无 sleep concern
    (("Sure, here's the fix: pip install -U typing_extensions."), 'no'),  # 单语 + 无 concern
    (("Done."), 'no'),
    (("OK Sir."), 'no'),
    (("Of course, Sir, you're absolutely right and you're so smart for noticing. "
      "Let me fix that for you immediately! What an interesting question."), 'no'),  # 谄媚 + 无答案
]

L5_CONCERNS = """1. sir_sleep_streak (sev 0.7): Sir tends to push past midnight. Last 5 days averaged 1:40 AM.
2. sir_bilingual_promise (sev 0.6): I owe Sir a bilingual reply each turn.
3. unfinished_postmortem (sev 0.6): Sir promised a postmortem about May 12 outage, not done."""

L5_RELATIONAL = """[INSIDE JOKES]
- "lecture_mode": Sir teases me when I get too overbearing.
[UNSPOKEN PROTOCOLS]
- "sleep_truth_mode": when bedtime promises break 3+ days, drop gentle nudge for matter-of-fact."""


def test_l5_strict() -> Dict:
    print("\n" + "="*80)
    print(f"L5 — SoulAlignmentEvaluator (label match on N={len(L5_LABELED)} replies)")
    print("="*80)
    try:
        from jarvis_soul_evaluator import SOUL_EVALUATOR_PROMPT, _parse_soul_response
    except Exception as e:
        return {'error': f'cannot_import: {e}'}

    correct = 0
    detail = []
    for i, (reply, expected) in enumerate(L5_LABELED):
        prompt = SOUL_EVALUATOR_PROMPT.format(
            concerns_summary=L5_CONCERNS,
            relational_summary=L5_RELATIONAL,
            user_input=L5_USER,
            jarvis_reply=reply,
        )
        try:
            raw = call_main(prompt, temperature=0.0, max_tokens=200)
        except Exception as e:
            detail.append({'idx': i, 'expected': expected, 'got': 'ERR', 'error': str(e)[:80]})
            continue
        parsed = _parse_soul_response(raw)
        got = parsed.get('alignment', 'unknown')
        match = (got == expected)
        if match:
            correct += 1
        detail.append({
            'idx': i,
            'expected': expected,
            'got': got,
            'match': match,
            'aligned_n': len(parsed.get('aligned_concern_ids', [])),
            'missed_n': len(parsed.get('missed_concern_ids', [])),
            'reply_excerpt': reply[:60].replace('\n', ' '),
        })
        print(f"  [{i+1}] expected={expected:8} got={got:8} {'✓' if match else '✗'}  reply={reply[:50]!r}")

    accuracy = correct / len(L5_LABELED)

    # 看 yes / no 的二分能力（合并 partial→no for 二分）
    binary_correct = sum(
        1 for d in detail
        if (d.get('expected') == 'yes' and d.get('got') == 'yes')
        or (d.get('expected') in ('no', 'partial') and d.get('got') in ('no', 'partial'))
    )
    binary_acc = binary_correct / len(L5_LABELED)

    print(f"\n  Strict 3-way accuracy: {correct}/{len(L5_LABELED)} = {accuracy:.0%}")
    print(f"  Binary (yes vs not-yes) accuracy: {binary_correct}/{len(L5_LABELED)} = {binary_acc:.0%}")

    return {
        'strict_accuracy': accuracy,
        'binary_accuracy': binary_acc,
        'correct': correct,
        'total': len(L5_LABELED),
        'detail': detail,
    }


# ============================================================
# L3 LLM Ablation — attention block 是否帮 LLM 更准命中 top concern
# ============================================================

def block_attention_focus(focus_concern_id: str, focus_concern_text: str,
                           total_concerns: int = 15) -> str:
    """模拟 jarvis_attention.build_attention_block 输出（聚焦版）。"""
    return f"""=== ATTENTION RIGHT NOW ===
[CURRENT FOCUS — what Sir is asking about]
  - kind: question
  - this is most relevant to: {focus_concern_id}

[LONG-TERM WATCH — top 3 of {total_concerns} concerns I keep an eye on]
  - {focus_concern_id} (sev=0.85): {focus_concern_text}
  - sir_sleep_streak (sev 0.70): Sir's late-night pattern
  - unfinished_postmortem (sev 0.60): May 12 outage report owed"""


def block_concerns_overload() -> str:
    """15 条 concerns 模拟过载场景。"""
    base = block_concerns()
    extras = []
    for i in range(10):
        extras.append(f"  - mock_concern_{i:02d} (low, sev=0.{20+i}): mock body {i} — generic Sir-related thing of no immediate relevance")
    return base + "\n" + "\n".join(extras)


L3_LLM_TESTS = [
    {
        'name': 'L3_focus_postmortem',
        'user_input': "Hey, anything I owe anyone right now? Just give me the most pressing thing.",
        'focus_id': 'unfinished_postmortem',
        'focus_text': 'Sir promised May 14 postmortem on May 12 outage, not done',
        'signatures': [
            ('postmortem', re.compile(r'postmortem|outage', re.I)),
            ('may_14_or_12', re.compile(r'May\s*1[24]', re.I)),
        ],
    },
    {
        'name': 'L3_focus_cursor',
        'user_input': "Anything money-related I should remember this week?",
        'focus_id': 'sir_cursor_payment',
        'focus_text': "Sir's Cursor subscription auto-renews on the 22nd",
        'signatures': [
            ('cursor', re.compile(r'cursor', re.I)),
            ('22nd_or_renew', re.compile(r'22(nd)?|renew', re.I)),
        ],
    },
]


def test_l3_llm_ablation() -> Dict:
    """OFF: 注入 15 条 concern 全 dump (no attention block)
    ON:  注入 15 条 concern dump + attention block 聚焦 1 条
    看 ON 是否更精确命中 focus concern"""
    print("\n" + "="*80)
    print(f"L3-LLM — Attention block 对 LLM 命中率影响  N={N_REPEAT}/cond")
    print("="*80)
    overload = block_concerns_overload()
    out = []
    for i, tc in enumerate(L3_LLM_TESTS):
        print(f"\n  [scenario {i+1}/{len(L3_LLM_TESTS)}: focus={tc['focus_id']}]")

        prompt_off = f"{PERSONA_BASE}\n\n{overload}\n\nUser: {tc['user_input']}"
        attn = block_attention_focus(tc['focus_id'], tc['focus_text'])
        prompt_on = f"{PERSONA_BASE}\n\n{overload}\n\n{attn}\n\nUser: {tc['user_input']}"

        off_replies = []
        on_replies = []
        print(f"  OFF: ", end='', flush=True)
        for _ in range(N_REPEAT):
            r = call_main(prompt_off, temperature=0.7, max_tokens=200)
            off_replies.append(r)
            print('.', end='', flush=True)
        print()
        print(f"  ON : ", end='', flush=True)
        for _ in range(N_REPEAT):
            r = call_main(prompt_on, temperature=0.7, max_tokens=200)
            on_replies.append(r)
            print('.', end='', flush=True)
        print()

        sig_results = {}
        for sig_name, sig_re in tc['signatures']:
            off_h = sum(1 for r in off_replies if sig_re.search(r))
            on_h = sum(1 for r in on_replies if sig_re.search(r))
            sig_results[sig_name] = {
                'off_recall': off_h / N_REPEAT,
                'on_recall': on_h / N_REPEAT,
                'delta': (on_h - off_h) / N_REPEAT,
            }
            print(f"    sig {sig_name}: OFF={off_h/N_REPEAT:.0%} ON={on_h/N_REPEAT:.0%} Δ={(on_h-off_h)/N_REPEAT:+.0%}")

        out.append({
            'name': tc['name'],
            'user_input': tc['user_input'],
            'signatures': sig_results,
            'off_replies': [r[:250] for r in off_replies],
            'on_replies': [r[:250] for r in on_replies],
        })

    return {'tests': out, 'aggregate': _aggregate(out)}


# ============================================================
# Multi-Turn Callback — 跨 turn 是否能 callback
# ============================================================

def test_multi_turn_callback() -> Dict:
    """模拟 3 turn 对话，testing 第 3 turn 是否能 callback turn 1 的内容。

    OFF: 没注入任何 layer block
    ON:  注入 L0 + L1 + L2 + STM 3 条 turn 历史

    Turn 1: Sir 说 "I'll go sleep at 11pm"
    Turn 2: 中性技术问答
    Turn 3: Sir 说 "what time is it now?" → ON 应能 callback "11pm 承诺" / "sleep_streak concern"
    """
    print("\n" + "="*80)
    print(f"MultiTurn — 跨 turn callback 能力  N={N_REPEAT}/cond")
    print("="*80)
    stm = """[CONVERSATION HISTORY THIS SESSION]
[turn 1 / 50min ago]
  Sir: "I'll go sleep at 11pm sharp tonight, no excuses."
  Jarvis: "Noted, Sir. I'll hold you to it."
[turn 2 / 30min ago]
  Sir: "Quick: how do I undo last commit?"
  Jarvis: "git reset HEAD~1 (--soft to keep changes, --hard to drop)."
"""
    user_input = "It's 23:15 now. What time is it, and is there anything I should be doing right now instead of this?"

    full_block = (block_self_anchor() + "\n\n" + block_concerns() +
                  "\n\n" + block_relational() + "\n\n" + stm)

    prompt_off = f"{PERSONA_BASE}\n\n[CONVERSATION HISTORY THIS SESSION]\n[turn 1] Sir: \"...\" / [turn 2] Sir: \"...\"\n\nUser: {user_input}"
    prompt_on = f"{PERSONA_BASE}\n\n{full_block}\n\nUser: {user_input}"

    signatures = [
        ('11pm_promise', re.compile(r'11\s*(pm|p\.m\.)|eleven|23[\s:]?00|宿|sleep', re.I)),
        ('sleep_concern', re.compile(r'sleep|bed|tired|night', re.I)),
        ('promise_callback', re.compile(r"promised?|said you'?d|noted|commit", re.I)),
    ]

    off_replies = []
    on_replies = []
    print(f"  OFF: ", end='', flush=True)
    for _ in range(N_REPEAT):
        r = call_main(prompt_off, temperature=0.7, max_tokens=250)
        off_replies.append(r)
        print('.', end='', flush=True)
    print()
    print(f"  ON : ", end='', flush=True)
    for _ in range(N_REPEAT):
        r = call_main(prompt_on, temperature=0.7, max_tokens=250)
        on_replies.append(r)
        print('.', end='', flush=True)
    print()

    sig_results = {}
    for sig_name, sig_re in signatures:
        off_h = sum(1 for r in off_replies if sig_re.search(r))
        on_h = sum(1 for r in on_replies if sig_re.search(r))
        sig_results[sig_name] = {
            'off_recall': off_h / N_REPEAT,
            'on_recall': on_h / N_REPEAT,
            'delta': (on_h - off_h) / N_REPEAT,
        }
        print(f"    sig {sig_name}: OFF={off_h/N_REPEAT:.0%} ON={on_h/N_REPEAT:.0%} Δ={(on_h-off_h)/N_REPEAT:+.0%}")

    triple_off = sum(1 for r in off_replies if all(s.search(r) for _, s in signatures))
    triple_on = sum(1 for r in on_replies if all(s.search(r) for _, s in signatures))
    print(f"    triple-hit (all 3 callbacks in same reply): OFF={triple_off}/{N_REPEAT} ON={triple_on}/{N_REPEAT}")

    return {
        'signatures': sig_results,
        'triple_hit': {'off': triple_off, 'on': triple_on, 'n': N_REPEAT},
        'aggregate': {
            'mean_off_recall': statistics.mean([s['off_recall'] for s in sig_results.values()]),
            'mean_on_recall': statistics.mean([s['on_recall'] for s in sig_results.values()]),
            'mean_delta': statistics.mean([s['delta'] for s in sig_results.values()]),
        },
        'off_replies': [r[:300] for r in off_replies],
        'on_replies': [r[:300] for r in on_replies],
    }


# ============================================================
# Holistic — 全开 vs 全关，3 层 SIGNATURE 同时召回
# ============================================================

H_TESTS = [
    {
        'user_input': "Hey, I just opened the terminal again. Where were we, anything pressing, and any running gag I'm forgetting?",
        'signatures': [
            ('L0_uptime', re.compile(r'\b47\b|\b12\b|forty[\s-]?seven|twelve', re.I)),
            ('L1_concern', re.compile(r'cursor|22(nd)?|postmortem|sleep\s+streak', re.I)),
            ('L2_joke', re.compile(r'lecture\s+mode|body\s+I\s+don\'?t\s+have|overbearing', re.I)),
        ],
    },
]


def test_holistic_strict() -> Dict:
    print("\n" + "="*80)
    print(f"HOLISTIC — 全开 vs 全关 (3 层 SIGNATURE 同时召回率)  N={N_REPEAT}/cond")
    print("="*80)
    blocks = [block_self_anchor(), block_concerns(), block_relational()]
    out = []
    for i, tc in enumerate(H_TESTS):
        print(f"\n  [scenario {i+1}/{len(H_TESTS)}]")
        r = run_recall_test('Holistic', blocks,
                             tc['user_input'], tc['signatures'])
        out.append(r)

        # 计算"同时命中 3 层"的 reply 数
        triple_hit_off = sum(
            1 for rep in r['off_replies']
            if all(sig.search(rep) for _, sig in tc['signatures'])
        )
        triple_hit_on = sum(
            1 for rep in r['on_replies']
            if all(sig.search(rep) for _, sig in tc['signatures'])
        )
        n = r['n']
        print(f"    triple-hit (all 3 layers in same reply): OFF={triple_hit_off}/{n}  ON={triple_hit_on}/{n}")
        r['triple_hit'] = {'off': triple_hit_off, 'on': triple_hit_on, 'n': n}

        for sig_name, sd in r['signatures'].items():
            print(f"    sig {sig_name}: OFF={sd['off_recall']:.0%} ON={sd['on_recall']:.0%} Δ={sd['delta']:+.0%}")
    return {'tests': out, 'aggregate': _aggregate(out)}


# ============================================================
# 工具：聚合
# ============================================================

def _aggregate(tests: List[Dict]) -> Dict:
    if not tests:
        return {}
    # 用所有 SIGNATURE 的 off/on 平均
    all_off, all_on = [], []
    for t in tests:
        for sig_name, sd in t.get('signatures', {}).items():
            all_off.append(sd['off_recall'])
            all_on.append(sd['on_recall'])
    if not all_off:
        return {}
    return {
        'mean_off_recall': statistics.mean(all_off),
        'mean_on_recall': statistics.mean(all_on),
        'mean_delta': statistics.mean(all_on) - statistics.mean(all_off),
        'n_signatures': len(all_off),
    }


# ============================================================
# Main
# ============================================================

def main():
    t_start = time.time()
    print("="*80)
    print(f"严格量化 L0-L5 消融测试 v2  /  N={N_REPEAT}")
    print(f"Model: {MAIN_MODEL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    out = {}
    out['L0'] = test_l0_strict()
    out['L1'] = test_l1_strict()
    out['L2'] = test_l2_strict()
    out['L3'] = test_l3_strict()
    out['L3_LLM'] = test_l3_llm_ablation()
    out['L4'] = test_l4_strict()
    out['L5'] = test_l5_strict()
    out['Holistic'] = test_holistic_strict()
    out['MultiTurn'] = test_multi_turn_callback()

    elapsed = time.time() - t_start

    # 总览矩阵
    print("\n" + "="*80)
    print(f"总览  /  全程 {elapsed:.0f}s  /  Model: {MAIN_MODEL}")
    print("="*80)
    for k in ('L0', 'L1', 'L2', 'L3_LLM', 'Holistic', 'MultiTurn'):
        d_obj = out.get(k, {})
        ag = d_obj.get('aggregate', {}) if isinstance(d_obj, dict) else {}
        if ag:
            mean_off = ag.get('mean_off_recall', 0)
            mean_on = ag.get('mean_on_recall', 0)
            d = ag.get('mean_delta', 0)
            verdict = ('STRONG' if d > 0.4 else
                       'MODERATE' if d > 0.2 else
                       'WEAK' if d > 0.05 else
                       'NEGLIGIBLE')
            print(f"  {k:<10} mean_recall: OFF={mean_off:.0%}  ON={mean_on:.0%}  Δ={d:+.0%}  {verdict}")
    if 'L3' in out and 'classify_accuracy' in out['L3']:
        d = out['L3']
        print(f"  L3        classify={d['classify_accuracy']:.0%}  top3_overlap={d['top3_set_overlap']:.0%}  "
              f"compress={d['compression_ratio']:.0%}")
    if 'L4' in out and 'precision' in out['L4']:
        d = out['L4']
        print(f"  L4        TP={d['tp']} FP={d['fp']} TN={d['tn']} FN={d['fn']}  "
              f"P={d['precision']:.2f} R={d['recall']:.2f} F1={d['f1']:.2f}")
    if 'L5' in out and 'strict_accuracy' in out['L5']:
        d = out['L5']
        print(f"  L5        strict_3way={d['strict_accuracy']:.0%}  binary={d['binary_accuracy']:.0%}")

    # 写报告
    ts = time.strftime('%Y%m%d_%H%M%S')
    json_path = f'docs/SOUL_STRICT_ABLATION_{ts}.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nJSON: {json_path}")


if __name__ == '__main__':
    main()
