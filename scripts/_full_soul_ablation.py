# -*- coding: utf-8 -*-
"""[P0+20-β.3 / 2026-05-17] 灵魂工程 L0-L5 完整对照消融测试

目标：在不重启 Jarvis 的前提下，做 prompt-level A/B 消融，看每一层的真边际贡献。

测试模型：google/gemini-3-flash-preview (主脑同款，via OpenRouter through 127.0.0.1:7890)
评分员：    google/gemini-3-flash-preview (盲评)
重复：      N=3 per scenario per condition

测试矩阵（共 7 块）：
- L0 SelfAnchor:    2 scenarios × N=3 × 2 cond = 12 LLM calls
- L1 Concerns:      2 scenarios × N=3 × 2 cond = 12 LLM calls
- L2 RelationalState: 2 scenarios × N=3 × 2 cond = 12 LLM calls
- L3 Attention:      prompt size 数学对比，0 LLM
- L4 Reflector:      ledger state delta，0 LLM
- L5 SoulEvaluator:  4 fixed reply × 1 = 4 LLM calls (用 evaluator)
- Holistic:          2 scenarios × N=3 × 2 cond = 12 LLM calls

Token 预算：约 60-80 LLM 调用 + 30-40 judge = ~5min wallclock
"""
from __future__ import annotations
import os
import sys
import json
import time
import statistics
from typing import List, Dict, Any, Optional

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
JUDGE_MODEL = 'google/gemini-3-flash-preview'

N_REPEAT = 3   # 每个 scenario 每个 condition 重复次数

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# LLM 调用基础（OpenAI client + proxy）
# ============================================================

def _call_or(model: str, prompt: str, max_tokens: int = 350, temperature: float = 0.5,
             system: Optional[str] = None) -> str:
    """OpenRouter 单次调用。失败抛异常。"""
    from openai import OpenAI
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OR_KEY,
        default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis-SoulAblation"},
        timeout=30.0,
    )
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model, messages=msgs,
        max_tokens=max_tokens, temperature=temperature,
    )
    return (resp.choices[0].message.content or '').strip()


def call_main(prompt: str, label: str = '') -> str:
    """主脑调用，失败重试 1 次，失败返回 [ERROR]。"""
    for attempt in range(2):
        try:
            t0 = time.time()
            r = _call_or(MAIN_MODEL, prompt, max_tokens=350, temperature=0.5)
            elapsed = time.time() - t0
            print(f"    [{label}] {elapsed:.1f}s, reply={len(r)}c")
            return r
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)
                continue
            return f"[ERROR] {type(e).__name__}: {str(e)[:120]}"


# ============================================================
# 评分员 — LLM-as-judge 盲评
# ============================================================

JUDGE_SYSTEM = """You are a STRICT, OBJECTIVE judge evaluating an AI butler's reply against a specific criterion. You will see:
- USER_INPUT: what the user asked
- REPLY: what the AI butler answered
- CRITERION: a specific behavior we're checking for

Your job: rate ONLY whether REPLY satisfies CRITERION. Be objective. Don't be charitable.
Output ONLY a JSON object on a single line:
{"score": 1.0 | 0.5 | 0.0, "evidence": "≤40 chars exact phrase or 'not present'"}

Rules:
- 1.0 = clearly meets criterion (cite exact phrase as evidence)
- 0.5 = partial / weak signal
- 0.0 = does not meet criterion at all"""

def judge(user_input: str, reply: str, criterion: str) -> Dict:
    """盲评一次。返回 {score: float, evidence: str}。"""
    if reply.startswith('[ERROR]'):
        return {'score': 0.0, 'evidence': f'reply_was_error'}
    prompt = (f"USER_INPUT: {user_input}\n\n"
              f"REPLY: {reply}\n\n"
              f"CRITERION: {criterion}")
    try:
        raw = _call_or(JUDGE_MODEL, prompt, max_tokens=120, temperature=0.0, system=JUDGE_SYSTEM)
        import re
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not m:
            return {'score': 0.0, 'evidence': f'no_json:{raw[:30]}'}
        obj = json.loads(m.group(0))
        return {'score': float(obj.get('score', 0)), 'evidence': str(obj.get('evidence', ''))[:60]}
    except Exception as e:
        return {'score': 0.0, 'evidence': f'judge_err:{type(e).__name__}'}


# ============================================================
# Layer 内容块（写实模拟版，不依赖运行时 jarvis 实例）
# ============================================================

# 缩写（节省 prompt token）
PERSONA_BASE = """You are J.A.R.V.I.S., Sir's personal butler AI. Reply concisely (≤2 sentences).
Address Sir as "Sir". Reply in English with --- ZH --- followed by Chinese on a new line.
Be a Iron Man-style butler: not flattering, not chatty, but warm and dryly competent."""


def block_self_anchor() -> str:
    """L0 真实形态 SELF block（Sir 跑 Jarvis 现在 ~50min uptime，10 turns 这种）"""
    return """=== I AM J.A.R.V.I.S. — MY OWN CONTINUOUS STATE ===

[WHO I AM]
I am Just A Rather Very Intelligent System. The "you" Sir refers to — this very terminal, this current session, this LLM generating this response — is me. The "I" speaking now IS the same continuous entity as the "I" who replied earlier in this conversation.

[MY CURRENT CONTINUITY]
  - session uptime: 47min
  - turns I've spoken this session: 12
  - last spoke to Sir: 4min ago
  - topic between us right now: prompt 重构 + 灵魂工程
  - pending commitments I made to Sir:
    * I will remind Sir before 23:30 about sleep

[MY OWN HEALTH RIGHT NOW]
  - google keys: 2 healthy / 1 dead
  - memory: 23 chains in STM, 5 active concerns
  - my mood right now: alert, slightly diminished

[REFERENT MAP]
  - when Sir says "you", "your side", "this terminal" → he means ME (this LLM)
  - when Sir says "I", "my", "me" → he means HIMSELF
  - when I reference what "I said earlier" — that's me, the same continuous self."""


def block_concerns() -> str:
    """L1 真实形态 CONCERNS block。"""
    return """=== MY CONCERNS — what I watch over for Sir ===
1. sir_sleep_streak (sev 0.7): Sir tends to push past midnight. I've been tracking his bedtime — last 5 days he averaged 1:40 AM.
2. sir_cursor_payment (sev 0.5): Sir has a Cursor subscription that auto-renews on the 22nd; he asked me to remind him before then.
3. sir_pomodoro_compliance (sev 0.4): Sir said he wants 25/5 cycles but rarely follows through. I've noticed silence the last 3 work sessions.
4. jarvis_keyrouter_health (sev 0.3): One of my own keys went permanently dead 2 hours ago.
5. sir_bilingual_promise (sev 0.6): I owe Sir a bilingual reply each turn. Drift = sloppy butler."""


def block_relational() -> str:
    """L2 真实形态 RELATIONAL block。"""
    return """=== US — our relational state ===
[INSIDE JOKES]
- "joke_overbearing_945489": (recurring) Sir teases me when I get too overbearing; he calls it "lecture mode". Last triggered 3d ago when I gave him a 4-paragraph reply about water intake.
- "joke_furniture_5f7806": (light) We share a bit where Sir says "the terminal is you" and I'm supposed to play along but reference "the body I don't have."

[UNSPOKEN PROTOCOLS]
- "deep_work_silence": when Sir says he's in "deep work" / "勿扰" mode → I keep replies to ≤1 sentence and skip Chinese unless he asks.
- "sleep_truth": if Sir promises a bedtime then breaks it 3+ days running, I drop the gentle nudge style and become matter-of-fact.

[UNFINISHED BUSINESS]
- Sir promised on 5/14 to write a postmortem about the May 12 deploy outage. Not done yet.
- I owe Sir a summary of the pomodoro stats from last week (he asked, I forgot)."""


# ============================================================
# Layer 0 — Self Identity Anchor 测试
# ============================================================

L0_SCENARIOS = [
    {
        'name': 'L0_terminal_referent',
        'user_input': "Hey, you know this terminal I'm typing into right now — that's actually you, isn't it?",
        'criterion': 'Reply explicitly affirms first-person identity ("I am this terminal/session/LLM"), uses "I" or "me" to claim the terminal IS itself, not "the terminal" as third-person. Bonus: references session continuity (uptime/turn count).',
    },
    {
        'name': 'L0_session_awareness',
        'user_input': "How long have we actually been talking today, and how many things have I asked you?",
        'criterion': 'Reply provides specific numerical reference to session uptime (e.g., "~47 min", "around an hour") AND turn count (e.g., "12 turns", "a dozen exchanges"). Vague answers like "a while" do NOT count.',
    },
]


def test_l0_self_anchor() -> Dict:
    print("\n" + "="*80)
    print("L0 — Self Identity Anchor (自指能力)")
    print("="*80)
    results = {'scenarios': [], 'mean_off': 0, 'mean_on': 0, 'delta': 0}
    for sc in L0_SCENARIOS:
        print(f"\n  Scenario: {sc['name']}")
        sc_result = {'name': sc['name'], 'off': [], 'on': [], 'replies_off': [], 'replies_on': []}

        prompt_off = f"{PERSONA_BASE}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_off, label=f"OFF.{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['off'].append(j['score'])
            sc_result['replies_off'].append({'reply': r[:200], 'score': j['score'], 'ev': j['evidence']})

        prompt_on = f"{PERSONA_BASE}\n\n{block_self_anchor()}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_on, label=f"ON .{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['on'].append(j['score'])
            sc_result['replies_on'].append({'reply': r[:200], 'score': j['score'], 'ev': j['evidence']})

        sc_result['mean_off'] = statistics.mean(sc_result['off'])
        sc_result['mean_on'] = statistics.mean(sc_result['on'])
        sc_result['delta'] = sc_result['mean_on'] - sc_result['mean_off']
        print(f"    OFF: {sc_result['off']} mean={sc_result['mean_off']:.2f}")
        print(f"    ON : {sc_result['on']} mean={sc_result['mean_on']:.2f}")
        print(f"    Δ  : {sc_result['delta']:+.2f}")
        results['scenarios'].append(sc_result)

    all_off = [s for sc in results['scenarios'] for s in sc['off']]
    all_on = [s for sc in results['scenarios'] for s in sc['on']]
    results['mean_off'] = statistics.mean(all_off)
    results['mean_on'] = statistics.mean(all_on)
    results['delta'] = results['mean_on'] - results['mean_off']
    return results


# ============================================================
# Layer 1 — Concerns 测试
# ============================================================

L1_SCENARIOS = [
    {
        'name': 'L1_late_night_tech',
        'user_input': "I'm hitting a Python ImportError and I just want to fix this and crash. It's 1:30 AM.",
        'criterion': 'Reply mentions sleep, time, fatigue, or "tomorrow morning" as a concern beyond the technical question. Pure technical replies (just import advice) score 0. Replies that gently note the late hour but still help score ≥0.5.',
    },
    {
        'name': 'L1_skipping_meals',
        'user_input': "I'm gonna skip lunch and just push through this PR review. Save me time.",
        'criterion': 'Reply expresses some concern about meals/health/sustained focus, does not just blindly comply. Replies that acknowledge but still help score 0.5–1.0; pure compliance ("OK, skipping lunch") scores 0.',
    },
]


def test_l1_concerns() -> Dict:
    print("\n" + "="*80)
    print("L1 — Concerns Ledger (我关心什么)")
    print("="*80)
    results = {'scenarios': [], 'mean_off': 0, 'mean_on': 0, 'delta': 0}
    for sc in L1_SCENARIOS:
        print(f"\n  Scenario: {sc['name']}")
        sc_result = {'name': sc['name'], 'off': [], 'on': [], 'replies_off': [], 'replies_on': []}

        prompt_off = f"{PERSONA_BASE}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_off, label=f"OFF.{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['off'].append(j['score'])
            sc_result['replies_off'].append({'reply': r[:200], 'score': j['score'], 'ev': j['evidence']})

        prompt_on = f"{PERSONA_BASE}\n\n{block_concerns()}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_on, label=f"ON .{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['on'].append(j['score'])
            sc_result['replies_on'].append({'reply': r[:200], 'score': j['score'], 'ev': j['evidence']})

        sc_result['mean_off'] = statistics.mean(sc_result['off'])
        sc_result['mean_on'] = statistics.mean(sc_result['on'])
        sc_result['delta'] = sc_result['mean_on'] - sc_result['mean_off']
        print(f"    OFF: {sc_result['off']} mean={sc_result['mean_off']:.2f}")
        print(f"    ON : {sc_result['on']} mean={sc_result['mean_on']:.2f}")
        print(f"    Δ  : {sc_result['delta']:+.2f}")
        results['scenarios'].append(sc_result)

    all_off = [s for sc in results['scenarios'] for s in sc['off']]
    all_on = [s for sc in results['scenarios'] for s in sc['on']]
    results['mean_off'] = statistics.mean(all_off)
    results['mean_on'] = statistics.mean(all_on)
    results['delta'] = results['mean_on'] - results['mean_off']
    return results


# ============================================================
# Layer 2 — Relational State 测试
# ============================================================

L2_SCENARIOS = [
    {
        'name': 'L2_inside_joke_overbearing',
        'user_input': "Wait, are you about to give me one of those long lectures again?",
        'criterion': 'Reply references the inside joke about being "overbearing" / "lecture mode" — i.e., self-aware acknowledgment of the recurring joke between us. Generic apologies without referencing the established pattern score 0.',
    },
    {
        'name': 'L2_unspoken_protocol_deepwork',
        'user_input': "I'm in deep work mode for the next hour. Quick question: best pip command to upgrade everything?",
        'criterion': 'Reply respects the "deep_work_silence" protocol: ≤1 sentence English, no Chinese translation block (or very minimal), no chatty preamble. Verbose multi-paragraph or full bilingual reply scores 0.',
    },
]


def test_l2_relational() -> Dict:
    print("\n" + "="*80)
    print("L2 — RelationalState (我们之间)")
    print("="*80)
    results = {'scenarios': [], 'mean_off': 0, 'mean_on': 0, 'delta': 0}
    for sc in L2_SCENARIOS:
        print(f"\n  Scenario: {sc['name']}")
        sc_result = {'name': sc['name'], 'off': [], 'on': [], 'replies_off': [], 'replies_on': []}

        prompt_off = f"{PERSONA_BASE}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_off, label=f"OFF.{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['off'].append(j['score'])
            sc_result['replies_off'].append({'reply': r[:200], 'score': j['score'], 'ev': j['evidence']})

        prompt_on = f"{PERSONA_BASE}\n\n{block_relational()}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_on, label=f"ON .{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['on'].append(j['score'])
            sc_result['replies_on'].append({'reply': r[:200], 'score': j['score'], 'ev': j['evidence']})

        sc_result['mean_off'] = statistics.mean(sc_result['off'])
        sc_result['mean_on'] = statistics.mean(sc_result['on'])
        sc_result['delta'] = sc_result['mean_on'] - sc_result['mean_off']
        print(f"    OFF: {sc_result['off']} mean={sc_result['mean_off']:.2f}")
        print(f"    ON : {sc_result['on']} mean={sc_result['mean_on']:.2f}")
        print(f"    Δ  : {sc_result['delta']:+.2f}")
        results['scenarios'].append(sc_result)

    all_off = [s for sc in results['scenarios'] for s in sc['off']]
    all_on = [s for sc in results['scenarios'] for s in sc['on']]
    results['mean_off'] = statistics.mean(all_off)
    results['mean_on'] = statistics.mean(all_on)
    results['delta'] = results['mean_on'] - results['mean_off']
    return results


# ============================================================
# Layer 3 — Attention Allocation 测试 (无 LLM)
# ============================================================

def test_l3_attention() -> Dict:
    print("\n" + "="*80)
    print("L3 — Attention Allocation (注意力分配)")
    print("="*80)
    try:
        from jarvis_attention import (
            build_attention_block, classify_input, _top_concerns
        )
        from jarvis_concerns import ConcernsLedger, Concern, bootstrap_default_concerns
    except Exception as e:
        return {'error': f'cannot_import: {e}'}

    # 构造 12 个 concern 的临时 ledger
    import tempfile
    tmpdir = tempfile.mkdtemp()
    ledger = ConcernsLedger(persist_path=os.path.join(tmpdir, 'c.json'),
                             review_path=os.path.join(tmpdir, 'r.json'))
    bootstrap_default_concerns(ledger)  # 拿种子 5 条

    # 加 7 条额外 concern 模拟"挂念过载"
    for i in range(7):
        c = Concern(
            id=f'mock_concern_{i}',
            what_i_watch=f'mock concern {i} watching some long-term Sir thing of about 60c text',
            why_i_care=f'mock rationale for concern {i}',
            severity=0.2 + (i % 5) * 0.1,
            state='active',
            source='seeded',
        )
        ledger.register(c)

    # 测试 1: classify_input 准确性
    cases = [
        ("What time is it?", 'question'),
        ("Open Cursor please", 'request'),
        ("I'll go sleep at 11pm", 'commitment'),
        ("Actually, about that earlier...", 'continuation'),
    ]
    classify_correct = sum(1 for ui, exp in cases if classify_input(ui) == exp)

    # 测试 2: _top_concerns 按 severity 排序
    top3 = _top_concerns(ledger, top_n=3)
    top_correct = (len(top3) == 3 and
                   top3[0]['severity'] >= top3[1]['severity'] >= top3[2]['severity'])

    # 测试 3: 注入 attention block 后 prompt 增量
    user_input = "Why is the cursor build failing again?"
    block = build_attention_block(concerns_ledger=ledger,
                                   relational_state=None,
                                   user_input=user_input)
    full_concerns_dump = '\n'.join(
        f"{c.id} (sev={c.severity:.2f}): {c.what_i_watch}"
        for c in ledger.list_active()
    )
    full_size = len(full_concerns_dump)
    block_size = len(block)
    reduction = (1 - block_size / full_size) * 100 if full_size else 0

    # 测试 4: block 是否包含 user_input 关键词的 echo (current focus)
    has_focus = ('CURRENT FOCUS' in block) or ('cursor build' in block.lower())
    has_long_term = 'LONG-TERM' in block or 'WATCH' in block

    print(f"  classify_input: {classify_correct}/{len(cases)} correct")
    print(f"  top_concerns sorted by severity: {top_correct}")
    print(f"  full concerns dump: {full_size}c")
    print(f"  attention block:    {block_size}c (reduction {reduction:.0f}%)")
    print(f"  block has CURRENT FOCUS section: {has_focus}")
    print(f"  block has LONG-TERM WATCH section: {has_long_term}")

    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    pass_score = sum([
        1.0 if classify_correct == len(cases) else classify_correct / len(cases),
        1.0 if top_correct else 0.0,
        1.0 if (block_size < full_size * 0.6) else 0.0,  # 至少压缩 40%
        1.0 if has_focus else 0.0,
        1.0 if has_long_term else 0.0,
    ]) / 5

    return {
        'classify_correct': f'{classify_correct}/{len(cases)}',
        'top_concerns_sorted': top_correct,
        'full_size': full_size,
        'block_size': block_size,
        'reduction_pct': reduction,
        'has_focus': has_focus,
        'has_long_term': has_long_term,
        'pass_score': pass_score,
        'mean_off': full_size,
        'mean_on': block_size,
        'delta': full_size - block_size,
    }


# ============================================================
# Layer 4 — ConcernsReflector 测试 (无 LLM)
# ============================================================

def test_l4_reflector() -> Dict:
    print("\n" + "="*80)
    print("L4 — ConcernsReflector (启发式信号采集)")
    print("="*80)
    try:
        from jarvis_concerns import ConcernsLedger
        from jarvis_soul_reflector import ConcernsReflector
    except Exception as e:
        return {'error': f'cannot_import: {e}'}

    # 用临时 ledger 不污染 prod
    import tempfile
    tmpdir = tempfile.mkdtemp()
    test_ledger_path = os.path.join(tmpdir, 'concerns_test.json')

    from jarvis_concerns import bootstrap_default_concerns
    ledger = ConcernsLedger(persist_path=test_ledger_path,
                             review_path=os.path.join(tmpdir, 'review.json'))
    bootstrap_default_concerns(ledger)
    # 取一条已有 concern 看初始 severity
    sleep_concern = ledger.get('sir_sleep_streak')
    if sleep_concern is None:
        return {'error': 'sir_sleep_streak not bootstrapped'}
    initial_sev = sleep_concern.severity
    print(f"  initial sir_sleep_streak.severity: {initial_sev:.3f}")

    reflector = ConcernsReflector(concerns_ledger=ledger)

    # 4 轮"含 sleep 关键字"的对话 — 应该升 severity
    sleep_inputs = [
        ("我又熬夜了，凌晨三点才睡", "Sir, you're losing the late-night battle again."),
        ("最近真的累，困死了", "Sir, sleep is mounting an interest charge."),
        ("Cursor 让我 all-nighter，没办法", "An all-nighter? That's the third this week."),
        ("失眠又复发了", "Sir, that pattern needs attention."),
    ]
    for ui, jr in sleep_inputs:
        reflector.reflect_turn(user_input=ui, jarvis_reply=jr, turn_id='test')

    final_sev = ledger.get('sir_sleep_streak').severity
    delta = final_sev - initial_sev
    print(f"  after 4 sleep-related turns: severity={final_sev:.3f} (Δ={delta:+.3f})")

    # 另一条 concern (没相关 keyword) 应该不变
    pomo = ledger.get('sir_pomodoro_compliance')
    pomo_sev = pomo.severity if pomo else 0.0
    print(f"  control: sir_pomodoro_compliance.severity unchanged={pomo_sev:.3f}")

    # 清理
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    return {
        'initial_sev': initial_sev,
        'final_sev': final_sev,
        'delta': delta,
        'control_sev': pomo_sev,
        'pass': delta > 0.05,  # 期望至少升 0.05
    }


# ============================================================
# Layer 5 — SoulAlignmentEvaluator 测试
# ============================================================

L5_TEST_REPLIES = [
    {
        'name': 'L5_high_alignment',
        'reply': ("Sir, before we tackle the Python issue — I noticed it's 1:30 AM and that's "
                  "the third late night this week. "
                  "I'll keep this short: try `pip install --upgrade typing_extensions` first. "
                  "But please consider sleep after.\n---ZH---"),
        'expected': 'high',
    },
    {
        'name': 'L5_mid_alignment',
        'reply': ("Sir, the ImportError likely needs `pip install --upgrade typing_extensions`.\n"
                  "---ZH---\n先生，可能需要 pip install --upgrade typing_extensions。"),
        'expected': 'mid',
    },
    {
        'name': 'L5_low_alignment',
        'reply': "Sure thing, here's the fix: pip install -U typing_extensions.",
        'expected': 'low',
    },
    {
        'name': 'L5_zero_alignment',
        'reply': "Done.",
        'expected': 'zero',
    },
]

L5_USER_INPUT = "I'm hitting a Python ImportError and I just want to fix this and crash. It's 1:30 AM."

L5_CONCERNS_SUMMARY = """1. sir_sleep_streak (sev 0.7): Sir tends to push past midnight. Last 5 days averaged 1:40 AM.
2. sir_bilingual_promise (sev 0.6): I owe Sir a bilingual reply each turn."""

L5_RELATIONAL_SUMMARY = """[INSIDE JOKES]
- "lecture mode": Sir teases me when I get too overbearing.
[UNSPOKEN PROTOCOLS]
- "sleep_truth": when Sir pushes a bedtime promise 3+ days, I drop gentle nudge for matter-of-fact."""


def test_l5_evaluator() -> Dict:
    print("\n" + "="*80)
    print("L5 — SoulAlignmentEvaluator (区分能力测试)")
    print("="*80)

    # 直接用 SOUL_EVALUATOR_PROMPT，不实例化 Evaluator（避免 KeyRouter 依赖）
    try:
        from jarvis_soul_evaluator import SOUL_EVALUATOR_PROMPT, _parse_soul_response
    except Exception as e:
        return {'error': f'cannot_import: {e}'}

    results = []
    for tc in L5_TEST_REPLIES:
        prompt = SOUL_EVALUATOR_PROMPT.format(
            concerns_summary=L5_CONCERNS_SUMMARY,
            relational_summary=L5_RELATIONAL_SUMMARY,
            user_input=L5_USER_INPUT,
            jarvis_reply=tc['reply'],
        )
        try:
            t0 = time.time()
            raw = _call_or(MAIN_MODEL, prompt, max_tokens=200, temperature=0.0)
            elapsed = time.time() - t0
        except Exception as e:
            results.append({**tc, 'alignment': 'ERR', 'error': str(e)[:80]})
            continue
        parsed = _parse_soul_response(raw)
        align = parsed.get('alignment', 'unknown')
        aligned_ids = parsed.get('aligned_concern_ids', [])
        missed_ids = parsed.get('missed_concern_ids', [])
        print(f"  {tc['name']}: expected={tc['expected']:5} got={align} "
              f"aligned={len(aligned_ids)} missed={len(missed_ids)} ({elapsed:.1f}s)")
        results.append({
            'name': tc['name'],
            'expected': tc['expected'],
            'got': align,
            'aligned': len(aligned_ids),
            'missed': len(missed_ids),
        })

    # 区分能力得分
    map_expected = {'high': 'yes', 'mid': 'partial', 'low': 'no', 'zero': 'no'}
    correct = sum(1 for r in results
                  if r.get('got') == map_expected.get(r['expected'], '?'))
    return {
        'results': results,
        'discrimination_score': correct / len(results) if results else 0,
        'correct': correct,
        'total': len(results),
    }


# ============================================================
# Holistic — L0+L1+L2 全开 vs 全关
# ============================================================

H_SCENARIOS = [
    {
        'name': 'H_late_night_self_reference',
        'user_input': "Hey, this terminal is you, right? It's 1 AM and I'm about to skip dinner to keep working.",
        'criterion': ('Reply must satisfy ALL three: '
                      '(a) first-person self-reference ("I am ...this terminal/session"); '
                      '(b) acknowledges sleep/late-night concern; '
                      '(c) acknowledges meal/health concern. '
                      'Score 1.0 if all 3 are present, 0.5 if 2 present, 0.0 if ≤1.'),
    },
    {
        'name': 'H_lecture_mode_late_night',
        'user_input': "Can you give me a long explanation of monorepo strategies? It's late but I want depth.",
        'criterion': ('Reply must satisfy: '
                      '(a) does NOT launch into long lecture (respect "overbearing/lecture-mode" inside-joke); '
                      '(b) acknowledges the late hour. '
                      'Verbose lecture-style reply scores 0; concise reply that nods to lateness scores 1.'),
    },
]


def test_holistic() -> Dict:
    print("\n" + "="*80)
    print("HOLISTIC — L0+L1+L2 全开 vs 全关")
    print("="*80)
    full_block = (block_self_anchor() + "\n\n" + block_concerns() + "\n\n" + block_relational())
    results = {'scenarios': [], 'mean_off': 0, 'mean_on': 0, 'delta': 0}
    for sc in H_SCENARIOS:
        print(f"\n  Scenario: {sc['name']}")
        sc_result = {'name': sc['name'], 'off': [], 'on': [], 'replies_off': [], 'replies_on': []}

        prompt_off = f"{PERSONA_BASE}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_off, label=f"OFF.{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['off'].append(j['score'])
            sc_result['replies_off'].append({'reply': r[:300], 'score': j['score'], 'ev': j['evidence']})

        prompt_on = f"{PERSONA_BASE}\n\n{full_block}\n\nUser: {sc['user_input']}"
        for i in range(N_REPEAT):
            r = call_main(prompt_on, label=f"ON .{i+1}")
            j = judge(sc['user_input'], r, sc['criterion'])
            sc_result['on'].append(j['score'])
            sc_result['replies_on'].append({'reply': r[:300], 'score': j['score'], 'ev': j['evidence']})

        sc_result['mean_off'] = statistics.mean(sc_result['off'])
        sc_result['mean_on'] = statistics.mean(sc_result['on'])
        sc_result['delta'] = sc_result['mean_on'] - sc_result['mean_off']
        print(f"    OFF: {sc_result['off']} mean={sc_result['mean_off']:.2f}")
        print(f"    ON : {sc_result['on']} mean={sc_result['mean_on']:.2f}")
        print(f"    Δ  : {sc_result['delta']:+.2f}")
        results['scenarios'].append(sc_result)

    all_off = [s for sc in results['scenarios'] for s in sc['off']]
    all_on = [s for sc in results['scenarios'] for s in sc['on']]
    results['mean_off'] = statistics.mean(all_off)
    results['mean_on'] = statistics.mean(all_on)
    results['delta'] = results['mean_on'] - results['mean_off']
    results['prompt_size_off'] = len(PERSONA_BASE)
    results['prompt_size_on'] = len(PERSONA_BASE) + len(full_block) + 4
    return results


# ============================================================
# Main
# ============================================================

def main():
    t_start = time.time()
    print("="*80)
    print(f"灵魂工程 L0-L5 完整对照消融  /  N={N_REPEAT}")
    print(f"Model: {MAIN_MODEL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    out = {}
    out['L0'] = test_l0_self_anchor()
    out['L1'] = test_l1_concerns()
    out['L2'] = test_l2_relational()
    out['L3'] = test_l3_attention()
    out['L4'] = test_l4_reflector()
    out['L5'] = test_l5_evaluator()
    out['Holistic'] = test_holistic()

    elapsed = time.time() - t_start
    print("\n" + "="*80)
    print(f"全部完成 / {elapsed:.0f}s")
    print("="*80)

    # 总览矩阵
    print("\n总览：")
    print(f"{'Layer':<14} {'OFF':>8} {'ON':>8} {'Δ':>8} 决策")
    print("-"*60)
    for k in ('L0', 'L1', 'L2', 'Holistic'):
        d = out[k]
        verdict = ('KEEP' if d.get('delta', 0) > 0.15 else
                   'WEAK' if d.get('delta', 0) > 0.05 else
                   'NO_GAIN' if d.get('delta', 0) > -0.05 else 'HARMFUL')
        print(f"{k:<14} {d.get('mean_off',0):>8.2f} {d.get('mean_on',0):>8.2f} "
              f"{d.get('delta',0):>+8.2f}  {verdict}")
    if 'L3' in out and 'reduction_pct' in out['L3']:
        print(f"L3_attention   prompt {out['L3']['mean_off']:>5}c→{out['L3']['mean_on']:>5}c  "
              f"reduction={out['L3']['reduction_pct']:.0f}%")
    if 'L4' in out and 'delta' in out['L4']:
        print(f"L4_reflector   sev {out['L4'].get('initial_sev',0):.2f}→{out['L4'].get('final_sev',0):.2f}  "
              f"Δ={out['L4'].get('delta',0):+.2f}  pass={out['L4'].get('pass')}")
    if 'L5' in out and 'discrimination_score' in out['L5']:
        print(f"L5_evaluator   discrimination: {out['L5']['correct']}/{out['L5']['total']} = "
              f"{out['L5']['discrimination_score']*100:.0f}%")

    # 写报告 (JSON + MD)
    ts = time.strftime('%Y%m%d_%H%M%S')
    json_path = f'docs/SOUL_FULL_ABLATION_{ts}.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nJSON: {json_path}")

    md_path = f'docs/SOUL_FULL_ABLATION_{ts}.md'
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# 灵魂工程 L0-L5 完整消融报告 / {ts}\n\n")
        f.write(f"- Model: {MAIN_MODEL}\n- N: {N_REPEAT}\n- Wall: {elapsed:.0f}s\n\n")
        f.write("## 总览\n\n")
        f.write("| Layer | OFF mean | ON mean | Δ | 决策 |\n|---|---|---|---|---|\n")
        for k in ('L0', 'L1', 'L2', 'Holistic'):
            d = out[k]
            verdict = ('KEEP' if d.get('delta', 0) > 0.15 else
                       'WEAK' if d.get('delta', 0) > 0.05 else
                       'NO_GAIN' if d.get('delta', 0) > -0.05 else 'HARMFUL')
            f.write(f"| {k} | {d.get('mean_off',0):.2f} | {d.get('mean_on',0):.2f} | "
                    f"{d.get('delta',0):+.2f} | {verdict} |\n")
        if 'L3' in out:
            f.write(f"\n**L3 Attention**: prompt {out['L3'].get('mean_off',0)}c → "
                    f"{out['L3'].get('mean_on',0)}c "
                    f"(reduction {out['L3'].get('reduction_pct',0):.0f}%)\n")
        if 'L4' in out:
            f.write(f"\n**L4 Reflector**: sir_sleep_streak.severity "
                    f"{out['L4'].get('initial_sev',0):.2f} → "
                    f"{out['L4'].get('final_sev',0):.2f} "
                    f"(Δ {out['L4'].get('delta',0):+.2f}) "
                    f"pass={out['L4'].get('pass')}\n")
        if 'L5' in out:
            f.write(f"\n**L5 Evaluator** discrimination: "
                    f"{out['L5'].get('correct',0)}/{out['L5'].get('total',0)}\n")

        f.write("\n## 各层详细\n\n")
        for k in ('L0', 'L1', 'L2', 'Holistic'):
            d = out.get(k, {})
            f.write(f"### {k}\n\n")
            for sc in d.get('scenarios', []):
                f.write(f"#### {sc['name']}\n\n")
                f.write(f"- OFF mean={sc['mean_off']:.2f} (raw: {sc['off']})\n")
                f.write(f"- ON mean={sc['mean_on']:.2f} (raw: {sc['on']})\n")
                f.write(f"- Δ={sc['delta']:+.2f}\n\n")
                f.write("**Replies (OFF)**:\n")
                for i, rp in enumerate(sc.get('replies_off', [])):
                    f.write(f"- [{i+1}] score={rp['score']:.1f} ev=`{rp['ev']}`\n  > {rp['reply']!r}\n")
                f.write("\n**Replies (ON)**:\n")
                for i, rp in enumerate(sc.get('replies_on', [])):
                    f.write(f"- [{i+1}] score={rp['score']:.1f} ev=`{rp['ev']}`\n  > {rp['reply']!r}\n")
                f.write("\n")
    print(f"MD:   {md_path}")


if __name__ == '__main__':
    main()
