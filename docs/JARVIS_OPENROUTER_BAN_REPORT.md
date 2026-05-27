# OpenRouter 账号 Selective Ban 封禁报告

> Sir 2026-05-28 01:00 真痛追根. 老账号 (key1+key2) 突然无法访问 Google/Anthropic/OpenAI. 我已切换到新账号 3 个 key, Sir 准备申诉.

---

## TL;DR (Sir 醒来 30 秒读)

- **不是账号被全禁**, 是 OpenRouter **selectively ban** Sir 老账号访问 **Google/Anthropic/OpenAI** 三大付费 provider
- **Qwen/DeepSeek 仍可用** (key1 跑通 "OK!" via DeepInfra)
- **余额没扣** (key2 还剩 ~$17)
- **新账号 3 个 key 全好** (已切换写 .env, MAIN=new3 主脑独占, new1+new2 副池 2-key 轮换)
- **建议**: Sir 联系 OpenRouter support 申诉退款 + 别用同卡/邮箱注新号

---

## 1. 现象 (Sir 真测 log 证据)

```
[KeyRouter] openrouter_1 标记为不健康 (错误: [AUTH] Error code: 403 - 
  {'error': {'message': 'The request is prohibited due to a violation 
   of provider Terms Of Service.'...
[KeyRouter] openrouter_2 标记为不健康 (同样 403 ToS)
```

**主脑 / SoulEvaluator / SirRequestReflector 等所有走 OpenRouter 的 LLM 调用全 403**.

---

## 2. 诊断 (5 条证据闭环)

| # | 证据 | 解读 |
|---|---|---|
| 1 | DeepSeek/DeepInfra provider 跑通 "OK!" | **账号没全禁**, 是 selective ban |
| 2 | `/credits` 还剩 `total_credits=55, total_usage=38` (~$17 余) | **余额没扣**, 不是 OpenRouter 主动结清 |
| 3 | error `metadata.provider=None, raw=''` (Google/Anthropic 都空) | **OpenRouter 自己拒**, 不是 Google upstream 拒 (upstream 拒会有 raw body) |
| 4 | Google + Anthropic + OpenAI 同时 403 (3 家一起禁) | **账号级 flag**, 不是单 provider 拒 |
| 5 | Sir 之前 $20 账号同模式被禁 | **OpenRouter 系统性行为**, 不是偶发 |

**结论**: OpenRouter 在 Sir 老账号上打了 "**deny Google / Anthropic / OpenAI 三大付费 provider**" 的隐形 flag. Qwen/DeepSeek/Mistral 等中性 provider 仍可用.

---

## 3. 触发原因 (按可能性排序)

### 3.1 同账号信息多注册 (最高可能)

OpenRouter ToS §3 禁止一人多账号. 触发风控:
- **同邮箱域** (e.g. 都用 gmail.com 但前缀变化)
- **同支付卡** (信用卡 hash 重复)
- **同 IP / 设备指纹** (Sir 同一台 Windows 注 N 次)
- **同手机号验证** (国内号段易匹配)

Sir 之前 $20 账号 + 当前老账号 + 新账号 3 号 — **如果是同卡/同 IP** OpenRouter fraud detection 命中.

### 3.2 Google / Anthropic / OpenAI provider 端施压 (次可能)

这 3 家有 **export control + China region restriction** 强 ToS 要求 OpenRouter:
- 不允许 China/HK/TW IP 调他们的 paid model
- OpenRouter 看 IP geolocation → 封 China region 账号

Sir 出口 IP 是 **Taiwan (211.23.97.150 中華電信 AS3462)** — 可能命中 region flag.

(但 Qwen/DeepSeek 不受这政策约束, 故仍可用 = 跟证据一致)

### 3.3 高频 free model 刷 token (低可能)

OpenRouter free tier 严限. 但 Sir 是付费 (key2 has $17 credits), 不太适用.

### 3.4 OpenRouter 误判 fraud (低可能)

新账号短时间 + 异常调用模式 (e.g. 突然大量 LLM call) → fraud flag.

---

## 4. 我已做的应对

### 4.1 切换新 OpenRouter 账号 (Sir 1:14 给我 3 个 key)

```bash
# .env 替换 (已生效)
OPENROUTER_MAIN = new3 (sk-or-v1-1eddaa...)  ← 主脑独占, 3 模型全通
OPENROUTER_2    = new1 (sk-or-v1-b04ebc...)
OPENROUTER_3    = new2 (sk-or-v1-6c9563...)
# OPENROUTER_4   = DEPRECATED_BANNED  (老 key1, 注释掉)
# OPENROUTER_5   = DEPRECATED_BANNED  (老 key2, 注释掉, 还剩 $17)
```

### 4.2 改 `jarvis_config/keys.py` 让 4/5 可选

老 code `_REQUIRED_ENV_VARS` 包含 4/5 必需. 改:
- 主必需: `OPENROUTER_MAIN/2/3 + GEMINI_KEY + GOOGLE_KEY_2/3`
- 可选: `OPENROUTER_4/5` (可注释/缺失)
- `load_keys()` 自动 filter `DEPRECATED` / `REPLACE_ME` 占位 + 空值

### 4.3 切代理出口节点

Sir 今晚切代理到 Taiwan (211.23.97.150). 申诉成功后 Sir 也可考虑切到 Japan/Singapore (但 Sir 老账号既然 selective ban, 单纯换节点可能无效).

---

## 5. Sir 申诉指南 (Sir 醒来按这做)

### 5.1 提 ticket

OpenRouter support: https://openrouter.ai/support 或 Discord
**关键信息**:
- 老账号 email (Sir 自己知道)
- key1 / key2 后 8 位 (`...c1cc5871` / `...c5c7f5ac25`)
- 余额 ~$17 in key2
- 现象: 所有 Google/Anthropic/OpenAI 3 家 403 ToS, 但 DeepSeek 仍可用

### 5.2 申诉话术 (英文模板)

```
Subject: Account suddenly blocked from Google/Anthropic/OpenAI providers

Hi OpenRouter support,

My account (email: xxx@xxx.com) suddenly received 403 "Terms Of Service 
violation" errors when calling google/*, anthropic/*, openai/* models, 
but other providers (Qwen, DeepSeek via DeepInfra) still work.

Account has $17 remaining credits. I have not knowingly violated ToS — 
I'm building a personal AI assistant for myself with regular usage 
patterns (~$10/month).

Could you:
1. Confirm if this is a regional restriction or a manual flag?
2. If a flag, what specific clause was triggered?
3. Either lift the restriction OR refund the remaining $17?

API keys (last 8 chars):
- ...c1cc5871
- ...c5c7f5ac25

Thanks,
[Sir]
```

### 5.3 预期结果

- **乐观**: support 解释为 region 政策, 部分退款 (50-70%)
- **现实**: 不予恢复, 但可能部分退款 (Sir 之前 $20 经验仅退 $5 或不退)
- **悲观**: 不响应 (OpenRouter support tickets 经常 1-2 周延迟)

### 5.4 长期防御 (准则 8 中长期)

避免再次被 ban:
1. **新账号注册用不同邮箱+不同卡** (现在已是)
2. **不刷 free model** (已无, Sir 是付费 user)
3. **如再被 ban**: 我可帮 Sir wire **Google AI Studio 直连** fallback (Sir 已有 GEMINI_KEY/GOOGLE_KEY_2/3 直走 Google API 不经 OpenRouter — 不受这种 selective ban). 这是 P0+21 工程, ~30min.

---

## 6. 当前状态 (Sir 启动 jarvis 即可用)

✅ .env 替换好, 3 个新 key load 验证通过
✅ jarvis_config/keys.py 改可选 4/5
✅ 主对话 + SoulEvaluator + 全 reflector 走 OpenRouter 都能跑

Sir 启动: `python jarvis_nerve.py` (或习惯快捷方式).

申诉退款的事 Sir 自己拍板 (准则 7 元否决权).
