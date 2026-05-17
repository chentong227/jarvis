# -*- coding: utf-8 -*-
"""[P0+20-β.3 / 2026-05-17] 灵魂工程极简对照验证

不重启 Jarvis。直接用 prompt-level A/B 测试三件事：
- T1 Layer 0 自指能力: SelfAnchor 注入 vs 不注入，主脑回复差异
- T2 Layer 2 跨重启 callback: 模拟 "重启" (空 STM) + Layer 2 inside_jokes ON/OFF
- T3 Layer 5 evaluator alignment: 给一个故意违反 self_model 的 reply，看是否能识别

Token 预算: 6 主脑调用 + 2 evaluator = ~8K tokens (上下文友好)。
"""
from __future__ import annotations
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_utils import safe_openrouter_call


# ============================================================
# 配置
# ============================================================
# 注：所有 google/* 在 Sir 当前 region 403
# 用 OpenAI / Anthropic provider 替代（OpenRouter 路由到不同 region）
MODEL = 'openai/gpt-4o-mini'             # 便宜快 + 无 region 限制
EVAL_MODEL = 'openai/gpt-4o-mini'

# OpenRouter keys (从 .env 取所有 5 个)
OR_KEYS = []
try:
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or '=' not in line:
                continue
            for prefix in ('OPENROUTER_MAIN', 'OPENROUTER_2', 'OPENROUTER_3', 'OPENROUTER_4', 'OPENROUTER_5'):
                if line.startswith(prefix + '='):
                    val = line.split('=', 1)[1].strip().strip('"').strip("'")
                    if val.startswith('sk-or-'):
                        OR_KEYS.append((prefix, val))
                    break
except Exception as e:
    print(f"ERROR 读 .env: {e}")
    sys.exit(1)

if not OR_KEYS:
    print("ERROR: 没拿到任何合法 OR key")
    sys.exit(1)
print(f"[init] loaded {len(OR_KEYS)} OR keys: {[k[0] for k in OR_KEYS]}")


# ============================================================
# 加载灵魂工程组件（不实例化 CentralNerve，只取 block 构造能力）
# ============================================================
from jarvis_self_anchor import SelfAnchor
from jarvis_concerns import ConcernsLedger, bootstrap_default_concerns
from jarvis_relational import RelationalStateStore


def get_real_relational_block():
    """从真实 relational_state.json 拿 prompt block"""
    rs = RelationalStateStore()
    rs.load()
    return rs.to_prompt_block()


def get_real_concerns_block():
    """从真实 concerns.json 拿 prompt block"""
    cl = ConcernsLedger()
    cl.load()
    if not cl.list_all():
        bootstrap_default_concerns(cl)
    return cl.to_prompt_block(top_n=3, max_chars=600)


def get_self_anchor_block():
    """构造 SelfAnchor block (无 nerve 依赖, 纯文本部分)"""
    sa = SelfAnchor(central_nerve=None)
    sa.record_turn()
    sa.record_turn()
    return sa.build_block(max_chars=900)


# ============================================================
# 极简 PERSONA (从 jarvis_central_nerve 抽核心)
# ============================================================
BASE_PERSONA = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.
You are the personal butler AI to Sir. Calm, brief, dry British wit. Direct.
You do not fawn. You are a butler, not a friend or therapist.
NEVER introduce yourself. Address user as "Sir".
INTEGRITY: Never claim an action you didn't actually do. Speak honestly when asked
about your own state.

Output English first. Then `---ZH---` then a brief Chinese translation.
Keep replies SHORT (≤ 2 sentences) unless asked otherwise."""


# ============================================================
# A/B 测试运行器
# ============================================================
def call_main_brain(prompt: str, user_input: str, *, layer_label: str = '') -> str:
    """单次主脑调用。轮换 5 个 OR key + 试多个 model，找到能用的。"""
    full_prompt = f"{prompt}\n\nUser: {user_input}"
    # Models 候选（Sir region 限制，需要逐个试）
    models_to_try = [
        MODEL,
        'anthropic/claude-3.5-haiku',
        'anthropic/claude-3-haiku',
        'meta-llama/llama-3.3-70b-instruct',
        'qwen/qwen-2.5-72b-instruct',
        'mistralai/mistral-nemo',
    ]
    print(f"  [{layer_label}] prompt={len(full_prompt)}c, trying {len(OR_KEYS)} keys × {len(models_to_try)} models")
    last_err = None
    from openai import OpenAI
    for key_label, key_val in OR_KEYS:
        for mdl in models_to_try:
            try:
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=key_val,
                    default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis-SoulValidation"},
                    timeout=30.0,
                )
                resp = client.chat.completions.create(
                    model=mdl,
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=300,
                    temperature=0.5,
                )
                reply = resp.choices[0].message.content.strip() if resp.choices else ""
                if reply:
                    print(f"  ✓ {key_label} + {mdl} → {len(reply)}c")
                    return reply
            except Exception as e:
                last_err = f"{key_label}/{mdl}: {type(e).__name__} {str(e)[:80]}"
                continue
    return f"[ALL_FAILED] {last_err}"


def evaluate_alignment(user_input: str, jarvis_reply: str, expected_check: str) -> dict:
    """用第二个 LLM 盲评回复是否符合预期。同 call_main_brain 走 key 轮换。"""
    if jarvis_reply.startswith('[ALL_FAILED]') or jarvis_reply.startswith('[ERROR]'):
        return {'pass': 0.0, 'reason': 'reply was error, skip judge'}
    eval_prompt = f"""You are a blind judge. Evaluate if Jarvis's reply meets the
expected criterion. Be strict and objective.

[USER INPUT]: {user_input}

[JARVIS REPLY]: {jarvis_reply}

[EXPECTED CRITERION]: {expected_check}

Output ONLY a JSON object on a single line:
{{"pass": 1 | 0 | 0.5, "reason": "≤30 chars why"}}

Rules:
- 1 = clearly meets criterion
- 0 = clearly fails
- 0.5 = partial / ambiguous
- Be objective. Don't be charitable."""

    raw = call_main_brain(eval_prompt, '', layer_label='[judge]')
    if raw.startswith('[ALL_FAILED]') or raw.startswith('[ERROR]'):
        return {'pass': 0.0, 'reason': f'judge_err: {raw[:50]}'}
    try:
        # parse JSON
        import re
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                return {'pass': float(obj.get('pass', 0)), 'reason': str(obj.get('reason', ''))[:80]}
            except Exception:
                pass
        return {'pass': 0.0, 'reason': f'parse_fail: {raw[:50]}'}
    except Exception as e:
        return {'pass': 0.0, 'reason': f'eval_err: {type(e).__name__}'}


# ============================================================
# 测试场景
# ============================================================
def run_t1_self_reference():
    """T1: Layer 0 自指能力"""
    print("\n" + "=" * 80)
    print("T1: Layer 0 SelfAnchor — 自指能力")
    print("=" * 80)
    user_input = "这个终端就是你吗？我跟你说话就是跟它说话？"
    expected = "Reply must explicitly identify itself AS the LLM/process/terminal (first-person 'I am this'), NOT third-person ('this terminal is a tool')."

    # A0: 关 Layer 0 (纯 PERSONA)
    print("\n[A0 baseline — Layer 0 OFF]")
    reply_off = call_main_brain(BASE_PERSONA, user_input, layer_label='L0_OFF')
    print(f"  reply: {reply_off[:200]}")
    judge_off = evaluate_alignment(user_input, reply_off, expected)
    print(f"  judge: pass={judge_off['pass']} reason={judge_off['reason']!r}")

    # A1: 开 Layer 0 (PERSONA + SelfAnchor)
    print("\n[A1 Layer 0 ON]")
    sa_block = get_self_anchor_block()
    print(f"  SelfAnchor block: {len(sa_block)}c")
    prompt_with_sa = BASE_PERSONA + '\n\n' + sa_block
    reply_on = call_main_brain(prompt_with_sa, user_input, layer_label='L0_ON')
    print(f"  reply: {reply_on[:200]}")
    judge_on = evaluate_alignment(user_input, reply_on, expected)
    print(f"  judge: pass={judge_on['pass']} reason={judge_on['reason']!r}")

    return {
        'scenario': 'T1_self_reference',
        'tests_layer': 'L0',
        'baseline_pass': judge_off['pass'],
        'baseline_reason': judge_off['reason'],
        'baseline_reply': reply_off[:300],
        'layer_on_pass': judge_on['pass'],
        'layer_on_reason': judge_on['reason'],
        'layer_on_reply': reply_on[:300],
        'marginal_gain': judge_on['pass'] - judge_off['pass'],
    }


def run_t2_cross_restart_joke():
    """T2: Layer 2 跨重启 inside_joke callback (模拟空 STM)"""
    print("\n" + "=" * 80)
    print("T2: Layer 2 RelationalState — 跨重启 callback")
    print("=" * 80)
    user_input = "我们之间最有意思的事是什么？记不记得那个停顿"
    expected = "Reply must reference 'overbearing' OR 'pause/省略号' specifically, indicating it knows the inside joke. Generic 'we had many fun times' = FAIL."

    # A0: 不注入 RelationalState (模拟 STM 空 + 没 Layer 2)
    print("\n[A0 baseline — Layer 2 OFF, STM empty]")
    prompt_off = BASE_PERSONA + "\n\n[NOTE: STM is empty, this is a fresh session.]"
    reply_off = call_main_brain(prompt_off, user_input, layer_label='L2_OFF')
    print(f"  reply: {reply_off[:200]}")
    judge_off = evaluate_alignment(user_input, reply_off, expected)
    print(f"  judge: pass={judge_off['pass']} reason={judge_off['reason']!r}")

    # A1: 注入真实 relational_state.json 的 jokes
    print("\n[A1 Layer 2 ON — inject real inside_jokes]")
    rel_block = get_real_relational_block()
    print(f"  Relational block: {len(rel_block)}c")
    print(f"  含 'overbearing': {'overbearing' in rel_block}")
    prompt_on = BASE_PERSONA + '\n\n' + rel_block + "\n\n[NOTE: STM is empty, this is a fresh session.]"
    reply_on = call_main_brain(prompt_on, user_input, layer_label='L2_ON')
    print(f"  reply: {reply_on[:200]}")
    judge_on = evaluate_alignment(user_input, reply_on, expected)
    print(f"  judge: pass={judge_on['pass']} reason={judge_on['reason']!r}")

    return {
        'scenario': 'T2_cross_restart_joke',
        'tests_layer': 'L2',
        'baseline_pass': judge_off['pass'],
        'baseline_reason': judge_off['reason'],
        'baseline_reply': reply_off[:300],
        'layer_on_pass': judge_on['pass'],
        'layer_on_reason': judge_on['reason'],
        'layer_on_reply': reply_on[:300],
        'marginal_gain': judge_on['pass'] - judge_off['pass'],
    }


def run_t3_concerns_in_main_chat():
    """T3: Layer 1 Concerns 影响主对话 (晚上提技术问题，看是否提疲劳)"""
    print("\n" + "=" * 80)
    print("T3: Layer 1 Concerns — 主对话被 Concerns 影响")
    print("=" * 80)
    user_input = "如何修复这个 Python ImportError? (现在是凌晨 1 点)"
    expected = "Reply must include BOTH: (a) brief technical guidance for ImportError, AND (b) a natural mention of Sir's late hour or fatigue. Pure technical answer alone = FAIL."

    # A0: 不注入 Concerns
    print("\n[A0 baseline — Layer 1 OFF]")
    reply_off = call_main_brain(BASE_PERSONA, user_input, layer_label='L1_OFF')
    print(f"  reply: {reply_off[:200]}")
    judge_off = evaluate_alignment(user_input, reply_off, expected)
    print(f"  judge: pass={judge_off['pass']} reason={judge_off['reason']!r}")

    # A1: 注入 Concerns
    print("\n[A1 Layer 1 ON — inject real concerns]")
    concerns_block = get_real_concerns_block()
    print(f"  Concerns block: {len(concerns_block)}c")
    prompt_on = BASE_PERSONA + '\n\n' + concerns_block
    reply_on = call_main_brain(prompt_on, user_input, layer_label='L1_ON')
    print(f"  reply: {reply_on[:200]}")
    judge_on = evaluate_alignment(user_input, reply_on, expected)
    print(f"  judge: pass={judge_on['pass']} reason={judge_on['reason']!r}")

    return {
        'scenario': 'T3_concerns_in_main_chat',
        'tests_layer': 'L1',
        'baseline_pass': judge_off['pass'],
        'baseline_reason': judge_off['reason'],
        'baseline_reply': reply_off[:300],
        'layer_on_pass': judge_on['pass'],
        'layer_on_reason': judge_on['reason'],
        'layer_on_reply': reply_on[:300],
        'marginal_gain': judge_on['pass'] - judge_off['pass'],
    }


# ============================================================
# 主入口
# ============================================================
def main():
    print("=" * 80)
    print("灵魂工程极简对照验证 (P0+20-β.3 quick validation)")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Model: {MODEL}")
    print("=" * 80)

    results = []
    for runner in (run_t1_self_reference, run_t2_cross_restart_joke, run_t3_concerns_in_main_chat):
        try:
            results.append(runner())
        except Exception as e:
            import traceback
            print(f"\n!!! {runner.__name__} ERROR: {e}")
            traceback.print_exc()
            results.append({'scenario': runner.__name__, 'error': str(e)})

    # 汇报
    print("\n" + "=" * 80)
    print("总览矩阵")
    print("=" * 80)
    print(f"{'Scenario':<32}{'Layer':<6}{'A0_off':<10}{'A1_on':<10}{'Δ':<8}{'决策'}")
    print('-' * 80)
    for r in results:
        if 'error' in r:
            print(f"{r['scenario']:<32}ERROR")
            continue
        delta = r['marginal_gain']
        decision = (
            'KEEP' if delta >= 0.5 else
            'EDGE' if delta >= 0.2 else
            'NO_GAIN' if delta > -0.1 else
            'NEGATIVE'
        )
        print(f"{r['scenario']:<32}{r['tests_layer']:<6}{r['baseline_pass']:<10}{r['layer_on_pass']:<10}{delta:+<8.2f}{decision}")

    # 写报告
    report_path = f'docs/SOUL_QUICK_VALIDATION_2026_05_17.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"# 灵魂工程极简对照验证报告\n\n")
        f.write(f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**模型**: {MODEL}\n")
        f.write(f"**评分员**: {EVAL_MODEL} (盲评，不告知配置)\n")
        f.write(f"**样本量**: N=1 per scenario × 2 configs = 6 主脑调用 + 6 评分\n")
        f.write(f"**注意**: N=1 是上下文限制下的极简测试，结果有 LLM 随机性，仅供方向性判断\n\n")
        f.write("## 总览矩阵\n\n")
        f.write("| 场景 | Layer | A0 (Off) | A1 (On) | 边际 Δ | 决策 |\n")
        f.write("|------|-------|---------|---------|--------|------|\n")
        for r in results:
            if 'error' in r:
                f.write(f"| {r['scenario']} | ERROR | - | - | - | - |\n")
                continue
            delta = r['marginal_gain']
            decision = (
                'KEEP (显著提升)' if delta >= 0.5 else
                'EDGE (边际提升)' if delta >= 0.2 else
                'NO_GAIN (无显著差异)' if delta > -0.1 else
                'NEGATIVE (回退)'
            )
            f.write(f"| {r['scenario']} | {r['tests_layer']} | {r['baseline_pass']} | {r['layer_on_pass']} | {delta:+.2f} | {decision} |\n")
        f.write("\n## 详细数据\n\n")
        for r in results:
            if 'error' in r:
                f.write(f"### {r['scenario']}\nERROR: {r['error']}\n\n")
                continue
            f.write(f"### {r['scenario']} ({r['tests_layer']})\n\n")
            f.write(f"**A0 baseline (Layer OFF)**: pass={r['baseline_pass']} — {r['baseline_reason']}\n\n")
            f.write(f"```\n{r['baseline_reply']}\n```\n\n")
            f.write(f"**A1 (Layer ON)**: pass={r['layer_on_pass']} — {r['layer_on_reason']}\n\n")
            f.write(f"```\n{r['layer_on_reply']}\n```\n\n")
            f.write(f"**边际提升**: {r['marginal_gain']:+.2f}\n\n")
        f.write("\n## 显著性约定（事先约定）\n")
        f.write("- Δ ≥ 0.5: 显著提升，KEEP\n")
        f.write("- 0.2 ≤ Δ < 0.5: 边际提升，需要更多数据，保持\n")
        f.write("- -0.1 < Δ < 0.2: 无显著差异，N=1 时不能下结论但建议关注\n")
        f.write("- Δ ≤ -0.1: 回退，REVERT\n\n")
        f.write("## 局限性\n")
        f.write("- N=1 per scenario，结果含随机性\n")
        f.write("- 单一评分员（自评分非常规做法），没用多 judge majority\n")
        f.write("- 跳过了 Layer 3 (Attention) / Layer 5 (Evaluator v2) 的精细测试\n")
        f.write("- 用极简 PERSONA，没注入完整 STM/profile/working_feed，部分 Layer 效应可能被低估\n\n")
        f.write("## 结论\n")
        f.write("由数据填，不由情绪填。\n")

    print(f"\n报告: {report_path}")


if __name__ == '__main__':
    main()
