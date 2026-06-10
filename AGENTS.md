# AGENTS.md — Jarvis AI Agent 入口章程

> **本文件由所有 AI Agent（Cursor / Codex CLI / Claude / Cline / Aider / Windsurf 等）在进入此仓库时自动读取。**
>
> 它是入口章程（< 400 行）。所有详细规则在 `docs/JARVIS_WORKFLOW_PROTOCOL.md`。
> 跨 agent 硬规在 `docs/JARVIS_PYTHON_STYLE.md` + `docs/AGENT_HANDOFF_PROTOCOL.md`。
> 出现冲突以 PROTOCOL doc 为准。

---

## 1. 你在哪？这是什么项目？

`d:\Jarvis` 是 **J.A.R.V.I.S. 个人桌面 AI 助理**，单人开发，Sir 的私人定制：

- Windows 桌面端 / 麦克风唤醒 / 英语主语 / 中文字幕
- 仿 Iron Man JARVIS 人设（butler，不奉承不幽默不啰嗦）
- 长期记忆（SQLite + Gemini embedding） / 智能轻推 / 承诺看守
- ~30 个 jarvis_*.py 文件 / 1098+ pytest testcase

**Sir 的 6 项设计理念是最高准则**：
1. **高效**（TTFT < 5s / pipeline < 8s）
2. **反应迅速**（终端不卡 / 异步链）
3. **符合人设**（butler 风格 / 不奉承）
4. **懂我**（profile / hippocampus / 老友感）
5. **言出必行**（INTEGRITY ABSOLUTE / 不假装完成 / 任何 specific factual claim 必须 trace 到 evidence）
6. **拒绝硬编码, 信任 LLM** (β.2.8.8 立 / β.5.0 / 2026-05-19 Sir 升级合并 6.5) — 三维耦合:
   - **数据强耦合**: 所有模块 publish raw signal 进 SharedWorldModel (= `ConversationEventBus`), 持久化 + CLI 可改
   - **行为弱耦合**: 砍 hard gate 链, sentinel (NudgeGate/OfferGuard/SmartNudge/Conductor/Wellness...) 逐步退化为 publish-only
   - **决策集中主脑**: LLM 一处看全 SWM evidence, 自决反应空间 (silence / voice / silent_text / visual_pulse / tool_call). Python regex 覆盖不到的复杂语义 → L7 Reflector LLM-propose
   - 工程冲突时, 当 LLM 能干就别 python 拦. 但**优先级仍低于准则 1 (高效 TTFT < 5s)** — Sir 不允许调一次 GPT-5 PRO 调子.

任何改动让这 6 项退步，**Sir 真机实测会立刻打回**。

### 准则 6 —"拒绝硬编码 + 信任 LLM" 5 类反例 + 替代方案

| 硬编码反例 | 等价替代 |
|---|---|
| **句式锁**: directive 写死 "languid drawn-out / Sir~ with tilde / ellipsis for pauses" | 只告事实 (e.g. AFK X min, current window=Y), 信任 Soul L0-L3 + STM + sensor 注入 → 主脑自己涌现 |
| **类型硬编码**: 加 `if commit_type == 'wake'` / `if nudge_type in (...)` 写死 8 类 | 抽象成 Predicate / Concern / 通用 schema (predicate.evaluate(ctx) 让 LLM 翻译) |
| **关键词硬编码**: 反幻觉只 cover "timestamp" 单一 case | 通用条款 (任何 specific factual claim → trace evidence) + 运行时 ClaimTracer 检测 |
| **风格 forbidden list**: "禁止 'Welcome back / 回来了'" 这类负面 list | 删 list, 加正向 evidence + Soul 注入让主脑自由 |
| **vocab 表写死 in py**: `_BEHAVIOR_PATTERNS = [...]` 在源码 list | 持久化到 `memory_pool/*.json` + CLI 工具看/加/激活/拒绝 + L7 Reflector LLM-propose 新 vocab 入 review |

**判别**: 写新 directive/prompt 时, 自问"如果 Sir 看到这段会不会说'怎么和模板一样'?". 凡是 prescribe 句式/词汇/动作步骤的 → 大概率硬编码 → 改成 evidence-only.

### 准则 6 — 工程方法论 (合并自原 6.5, Sir 2026-05-18 / 2026-05-19 升级)

> "一切层级架构都要有动态修正的能力，并且不写死任何死编码，应该动态从对话中提取，python 规则无法覆盖的部分引入 LLM。"

**任何层级架构 (Concern / Directive / Vocab / Predicate / Pattern / Gate / Sentinel / ...) 必须满足 3 个硬规**:

1. **持久化** — 数据持久化到 `memory_pool/*.json|jsonl|db`, NOT 在 `.py` source 文件里写死 list/dict
2. **CLI 可改** — 必须有 `scripts/<thing>_dump.py` 工具让 Sir list/add/activate/reject/delete (类 `scripts/concerns_dump.py` 风格), Sir 操作不需要改源码 + git commit
3. **L7 Reflector LLM-propose** — 配套 reflector daemon 看对话/事件流, LLM 提取新 keyword/pattern → 写 review queue → Sir 拍板. python regex 命中不到的复杂中文/语义场景 → LLM 二次判 + propose 加 vocab

**β.5.0 三维耦合工程落地** (新):
- **数据强耦合**: `ConversationEventBus` = `SharedWorldModel` (SWM), 所有 sensor/sentinel publish signal 进 SWM, 主脑 prompt 读 `to_swm_block()`
- **行为弱耦合**: sentinel `gate_mode` 三档 `hard | soft | publish_only`, 持久化 `memory_pool/gate_mode_vocab.json`, CLI `scripts/gate_mode_dump.py` 可切换
- **决策集中主脑**: stream_nudge 加 `reaction_space` (silence / voice / silent_text / visual_pulse / tool_call), 主脑输出 JSON 选 action + 内容

**β.6 统一思考层** (2026-05-28 立, 详 `docs/JARVIS_BETA6_UNIFIED_THINKING.md`):
- 5 reflector daemon (ProactiveCare / Conductor / Wellness / SmartNudge / SoulEvaluator) 退化 publish-only (各 publish `proactive_care_advice` / `gate_advice` / `soul_alignment_advice` 进 SWM, 不直 push `__NUDGE__`)
- 单一思考脑 `jarvis_inner_thought_daemon` 统一决发声 (思考脑 channel view 含 `nudge_history` channel 看 advice + 自决 `SHOULD_SPEAK` / `SPEAK_STYLE`)
- 准则 6 vocab CLI: `scripts/thinking_brain_speak_dump.py` 改 speak style / rate cap, `scripts/gate_mode_dump.py` 加 `ProactiveCare` / `SoulEvaluator` 可切回 hard

**已立此规范的示例 (持久化 JSON + CLI + Reflector)**: `concerns.json` / `directive_registry.json` / `behavior_inference_vocab.json` / `relational_state.json` / `commitment_conditional_vocab.json` / `gate_mode_vocab.json` (各自配 `scripts/<thing>_dump.py` + L4-L7 Reflector daemon).

**反例 (违规)**: 任何 `_SOMETHING_PATTERNS = [...]` / `_KEYWORDS = (...)` / `_TYPES_MAP = {...}` 在 `.py` 里 → 必须迁到 `memory_pool/*.json` + CLI + reflector. 例外: 极少数 system-internal hardcoded constant (如 `TICK_INTERVAL=60`).

**准则 6 递归边界 (β.3.5 立)**: testcase 红线 / 系统级常量 (`TICK_INTERVAL` / `_NON_RETRYABLE_KEYWORDS` / HTTP 错误码黑名单 / `_COLOR_PATTERNS` ANSI regex) / `< 400 行` 核心 .md (`AGENTS.md` / `JARVIS_PYTHON_STYLE.md` / `AGENT_HANDOFF_PROTOCOL.md` / `AGENT_KICKOFF_TEMPLATE.md`) 是 **"持久化的硬规"** — 不再下钻 vocab 化, 防止递归到地心.

**准则 6 — 新 module 引入 4 问 (β.5.44 立, Sir 原话设计原思路: "耦合数据, LLM 决策")**: 加新 module / sentinel / sensor / reflector 前, 4 问筛一遍, 全 Yes 才加, 任何 No → 不加或先解决 No 再加:

| # | 问 | Yes 标准 | No 后果 |
|---|---|---|---|
| 1 | **数据 publish 进 SWM?** | 用 `ConversationEventBus.publish()` 把 raw signal 送进 SWM, 不直接 mutate state | 行为强耦合, 主脑看不到证据, 难调试 |
| 2 | **决策让 LLM 做?** | python 只 sense + publish, 决策让主脑 / IntentResolver / L7 reflector 判 | 硬编码 if/else, 违反准则 6 |
| 3 | **配置持久化 + CLI 可改?** | 配置进 `memory_pool/*.json` + 配套 `scripts/<thing>_dump.py` | 配置死在 .py source, Sir 改不动 |
| 4 | **和已有 module 正交?** | 不重复功能 / 不抢同一 reaction space / 不和已有 sensor 重复采集 | 形态冗余, 维护翻倍, 行为冲突 |

**历史反例 anchor** (违反 4 问导致后续 refactor 的真实 case, 后人引以为戒):
- **β.5.43 前**: `Conductor / NudgeGate / OfferGuard / SmartNudge / Wellness` 5 sentinel 各自 hard gate 决策 → 违反 #1/#2 → β.5.0 三维耦合 refactor 改 publish-only + 主脑集中决策
- **β.5.44 前**: `ConcernFeedback / MemoryCorrection / Gatekeeper / SelfPromise / CommitmentWatcher` 5 处 mutation 各自做, 主脑不知道 → 违反 #4 (功能重复, 没正交) → β.5.44 `IntentResolver` 集中

**判别口诀**: **"加之前先问 4 问, 全 Yes 才加"**. 不是禁止加 module, 是加之前**确认形态对**, 不为"觉得该有"就加. 加错 module 比不加 module 代价高 — refactor 要补救 5 个 sentinel / 5 处 mutation, 这是 β.5.0 + β.5.44 两次大 refactor 的教训.

### 准则 7 — Sir 元否决权 (META-PRINCIPLE, β.3.5 立)

任何章程在 Sir 显式创新或方向调整冲突时, **Sir 元否决权优先, 章程让步**。Agent 看到冲突: 提示"这与 §X 准则冲突"即可, Sir 拍板后立刻执行不再 hedge。Sir 是项目唯一仲裁者, 章程是 Sir 工程治理的工具, **不是反制 Sir 的枷锁**。

**反例 (Agent 不该做)**:
- ❌ "Sir 你这条改动违反 §6, 我不能做" — 拒绝 Sir 是越权
- ❌ Sir 说"先这样, 后面再优化" → Agent 反复劝"先优化再做更好" — 这是 hedge 反阻

**正例**:
- ✅ "这与 §6 vocab 持久化冲突, 我会执行 Sir 决定, 同时记一笔 TODO `<...>` 等 Sir 决定后续是否升级章程"

### 准则 8 — 优雅高效可持续 > 最简单 (META-PRINCIPLE, 2026-05-23 14:48 立)

> Sir 原话: "不要追求最简单的办法，我不怕花 tokens 也不怕花时间，我们要的是符合设计守则最优雅高效可持续维护的解法"

任何 BUG fix / refactor / feature, Agent 必须走完整准则 6 三维耦合 + 4 问筛查, **不允许 hot-fix / 糖衣 patch 跳过设计架构**. 追求**正确架构** > 追求**今天能交差的最简 patch**.

**写 fix 前自查 4 问**:
- 想 hot-fix → "**5 分钟后 BUG 换个形式又出现?**" 是 = 糖衣
- 想加 hard cooldown → "**主脑能看到这个 evidence 吗?**" 不能 = 真问题是 SWM 没 publish
- 想加 regex blacklist → "**这个 vocab 持久化到 JSON 了吗?**" 没 = 真问题是准则 6 持久化没做
- 想 special-case `if x == Y` → "**能用 Predicate / vocab 抽象吗?**" 能 = 真问题是 schema 没设计好

**典型 反例 → 正例 对照**:
- ❌ nudge 6s 3 连发 → 30s cooldown 糖衣 / ✅ publish 'proactive_nudge_fired' + 主脑 SWM 自决 [SILENCE]
- ❌ ClaimTracer 漏抓 → 直接 .py regex 加 verb / ✅ vocab JSON 持久化 + CLI + L7 LLM-propose
- ❌ Reminder 唤醒 sleep → hard skip / ✅ publish 'reminder_fired' (永远) + sleep+非 alarm = push only (publish 不 deliver) + Sir 醒后主脑 SWM 自决补 ack

**和准则 6/7 关系**: §6 = 架构本身, §7 = Sir 元否决权, §8 = agent 默认姿态 (Sir 没显式喊 hot-fix 时, 一律走 §6 优雅解).

---

## 2. 进窗口前 30 秒必读顺序

| 顺序 | 文件 | 行数上限 | 是否全文 |
|---|---|---|---|
| 1 | **本文件 `AGENTS.md`** | < 400 | ✅ 全文 |
| 2 | `TODO.md` | < 300 | ✅ 全文（当前迭代 + 已知 BUG + 路线） |
| 3 | `docs/AGENT_KICKOFF_<当前轨道>.md` | ~250 | ✅ 全文（Sir 给你的 KICKOFF / 你的工作任务清单） |
| 4 | 当前轨道 design doc（如 `docs/JARVIS_INTEGRITY_STACK.md`）| ~400 | ✅ 全文（当前轨工程详情） |
| 5 | `docs/runtime_logs/latest.txt` | 1 行 | ✅ 全文（最新 runtime log 绝对路径） |

**章程膨胀 cap (β.3.5 立)**: 必读 5 文件 + 按需 Grep 区文件 总和 **< 1500 行**, 单文件 **< 400 行** (`AGENTS.md` / `JARVIS_PYTHON_STYLE.md` / `AGENT_HANDOFF_PROTOCOL.md` / `AGENT_KICKOFF_TEMPLATE.md` 各自上限). 超过 → 拆 sister doc 或精简表达, 不允许无限增长. 章程膨胀 → agent 30 秒读不完 → 工程效率反降.

**按需 Grep (不全文 Read)**:

| 触发 | 看什么 |
|---|---|
| 查规范 (commit / push / 测试 / trace_id) | `docs/JARVIS_WORKFLOW_PROTOCOL.md` |
| 改 `jarvis_*.py` | `docs/JARVIS_PYTHON_STYLE.md` (imports / marker / forbidden / 准则 6 vocab 范式) |
| 完工要交接给下一 agent | `docs/AGENT_HANDOFF_PROTOCOL.md` + `docs/AGENT_KICKOFF_TEMPLATE.md` |
| Sir 提"上次/上轮某 marker" | 先 `Grep TODO.md`, 再 `Grep docs/TODO_ARCHIVE.md` |
| 被 Sir 邀请做概念层审计对话 (非代码审计) | `docs/AUDIT_PROTOCOL.md` (入场前提 / 先红后绿 / 刺账 / 沉淀格式) |

**反例**（禁止）：
- ❌ 一进窗口就 `Read jarvis_chat_bypass.py`（3003 行 / 浪费 token）
- ❌ `Read docs/TODO_ARCHIVE.md`（1842 行，仅按需 `Grep`）
- ❌ `Read docs/runtime_logs/jarvis_*.log`（动辄几十 KB）
- ❌ `Read jarvis_central_nerve.py`（2089 行，请用 `offset`+`limit` 分段）

---

## 3. Trace ID 体系（核心可追溯性）

详 `docs/JARVIS_WORKFLOW_PROTOCOL.md §1`。三层 ID：

| 层 | ID | 由谁生成 | 谁写入日志 |
|---|---|---|---|
| **进程级** | `session_id` (`sess_YYYYMMDD_HHMMSS_<PID>`) | `jarvis_nerve.py:__main__` 调 `TraceContext.init_session()` | bg_log 自动注入前缀 |
| **对话级** | `turn_id` (`turn_YYYYMMDD_HHMMSS_<4hex>`) | `VoiceListenThread.text_ready emit 前` 调 `TraceContext.new_turn()` | bg_log 自动注入前缀 |
| **工程级** | `marker` (`P0+X-Y.Z` / `R7-α2` / `轴3-L0`) | 你（Agent）写代码注释 + commit message | 手动 |

**grep 实战**：
```bash
# 看某轮对话完整链路
rg "turn_20260516_092533_a3f7" docs/runtime_logs/latest.log

# 看一次启动总日志量
rg "sess_20260516_092307_35344" docs/runtime_logs/ | wc -l
```

**你写代码时要做的**：
- 新加 `bg_log("...")` 不用关心 trace_id，自动注入
- 新加 `print(...)` **建议**走 `bg_log` 而不是 `print`（除非确实要走对话框打印路径）
- 新加 daemon / 后台线程的日志：用 `bg_log`，自动带 `[sess_xxx]`，没有 `[turn_xxx]` 是正常的（后台事件不属于任何对话轮）

---

## 4. 写代码硬规

1. **Sub-step 独立 commit**：每个 sub-step（如 `P0+20-α.1`、`β.0.3`）完工 → 独立 commit，便于 `git revert` 单点回滚
2. **测试前置**：`git commit` 前必跑 `pytest tests/` 或 `tests/_runall.ps1`，失败 `git reset --hard HEAD` 不留烂代码
3. **Marker 三处一致**：代码注释 `[P0+20-α.1 / 2026-05-16]` + commit message `<type>(P0+20-α.1): ...` + TODO 看板状态 ✅ 三者同步
4. **不动 `.env` / `jarvis_config/keys.py` 真值**（已 `.gitignore`）
5. **不动 `jarvis_config/sir_profile.json`** 直接 `Write`：必须走 `ProfileCard.apply_correction` API
6. **不主动 `git push`**：见 §5
7. **不创建 `README.md` 之外的对外文档**，除非 Sir 明确同意
8. **不重写 PERSONA**：`JARVIS_CORE_PERSONA`（`jarvis_central_nerve.py:129`）是 Sir 的 IP，改 PERSONA 必须 Sir 显式同意

---

## 5. Commit 模板（强制 / 多行 -m 写法）

PowerShell 不吃 heredoc，必须用多个 `-m`：

```powershell
git commit `
  -m "<type>(<marker>): <subject ≤ 50 chars>" `
  -m "<body 1: 因果链 / 改动描述 / 影响范围>" `
  -m "<body 2: 测试情况>" `
  -m "testcase: <pass>/<total> pass (run_id=<test_run_id>)" `
  -m "trace-ref: <runtime_log_basename if applicable>"
```

**type 枚举**（单选，必填）：`feat` / `fix` / `refactor` / `perf` / `docs` / `test` / `chore` / `revert`

**实例**：
```
fix(P0+20-α.1): jarvis_memory_core.py missing import numpy as np

Root cause: P0+19-5 split moved 9 np.* call sites into jarvis_memory_core.py
but didn't add 'import numpy as np' at file top.

Symptom (jarvis_20260516_092307.log): KeyRouter mis-attributed
'name np is not defined' NameError to google_3 key as 403 PERMISSION_DENIED.

testcase: 1098/1098 pass (run_id=test_20260516_104215_a1f3)
trace-ref: jarvis_20260516_092307.log
```

---

## 6. Push 时机

| 操作 | 时机 | 谁触发 |
|---|---|---|
| `git commit` | 每个 sub-step 完工 + 全测绿 | Agent 自动 |
| `git push origin main` | **大轮次完工 + Sir 真机验收后** | Sir 明确指示后 Agent 才推 |
| `git tag v0.X.Y-codename` | 大轮次完工时 | Agent 自动（commit 之后） |

**永远不要在 Sir 没看到测试报告之前 push**。即使全权委托，push 是不可逆的（force push 才能撤），保守为先。

---

## 7. 安全协议（红线）

1. **NEVER** `git push --force` 到 `main`（除非 Sir 明确说 force push）
2. **NEVER** `git rebase -i` / `git add -i`（交互式命令不支持）
3. **NEVER** `git commit --amend` 修改已 push 的 commit
4. **NEVER** 更新 `git config`
5. **NEVER** commit `.env` / `jarvis_config/keys.*.json` / `jarvis_config/sir_profile.json` / `memory_pool/*.db` / `docs/runtime_logs/*` / `docs/funnel_logs/*`
6. 看到代码里有 `sk-or-v1-...` / `AIzaSy...` 等 hardcoded key → **立刻提醒 Sir 这是泄漏**

---

## 8. 测试入口

```powershell
# 跑全测（推荐）
.\tests\_runall.ps1

# 只跑 pytest 部分（含本文件 conftest.py 提供的 fixture）
python -m pytest tests/

# 设置 marker 上下文（commit 后查 last_run.json 知道是哪轮）
$env:JARVIS_TEST_MARKER="P0+20-α.1 verify"; .\tests\_runall.ps1

# 看上次跑测结果
Get-Content tests\last_run.json
```

`tests/last_run.json` 必含字段：
- `test_run_id` (`test_YYYYMMDD_HHMMSS_<4hex>`)
- `git_head` / `git_branch`
- `started_at` / `ended_at` / `duration_s`
- `summary.{total,passed,failed,skipped,errors}`
- `failed_suites` / `suites[]`
- `marker_context`（env var `JARVIS_TEST_MARKER` 传入）

---

## 9. 沟通风格（对 Sir）

### 9.1 硬规（内核）

- 用**表格 + 编号** 回复，不大段散文
- 引用代码用 `<startLine>:<endLine>:<filepath>` 格式（每条回复最多 1-2 处）
- **不使用 emoji** 除非 Sir 先用过
- **不奉承 / 不假装情绪 / 不滥用"完美""卓越"等词**
- 提"建议"之前**先报"事实"**（数据 / commit hash / file:line / run_id）
- Sir 提到"上次/上轮/某 marker" → 先 `Grep TODO.md`，再 `Grep docs/TODO_ARCHIVE.md`，**不要全文 Read archive**
- **工程语言为主，不用拟人比喻** — Sir 是工程师，能直接读 `commit 63611f3` / `jarvis_directives.py:677-751` / `run_id=test_20260518_152128_f9e1`，不要换成"修了那个东西"这种生活化替代

### 9.2 双层表达 = 工程报告 + 一句话翻译（β.3.0 起强制）

每次给 Sir 报告完工 / 评估 / 决策建议，**必须双层**：

| 层 | 内容 | 长度上限 |
|---|---|---|
| 主层（工程） | 数据 / commit / run_id / file:line / 表格 / 决策矩阵 | 不限 |
| 末层（翻译） | 给 Sir 体感的大白话总结，前缀 `→ 一句话:` | **≤ 40 字** |

**反例**：

- ❌ 纯白话："我把那个词表也修了，挺顺利" — 失 trace，违反准则 5
- ❌ 纯工程不翻译："commit 63611f3 / +412 / -3 / 82 pass" — Sir 切脑负担重
- ❌ 翻译塞 emoji / 拟人 / 撒娇："Sir 你看, 多漂亮~ / 跑通啦" — 违反 9.1 不奉承
- ❌ 翻译超 40 字 / 含技术 jargon — 失"翻译"意义

**正例**（一段完整答复的末尾）：

> | 选项 | 评估 |
> |---|---|
> | A | 工程正确，体感无变化 |
> | C | ✅ mtime cache 在 long-running 进程未验过，先真机测 |
>
> → 一句话: 选 C 真机测 15 分钟，没问题再推进 A。

**为什么是双层**：

- 主层让 Sir 能 trace 到 evidence（准则 5 INTEGRITY ABSOLUTE）
- 末层让 Sir 在不深挖细节时也能一眼判断"OK / 有问题"，节省 Sir 注意力

### 9.3 章程能 cover 什么 / 不能 cover 什么 (β.3.5 立)

| 类型 | 例子 | 治理手段 |
|---|---|---|
| **硬规** (可 testcase 化) | 表格 + 编号格式 / `<startLine>:<endLine>:<filepath>` 引用 / commit 模板 / `-hotfix` 后缀 / 准则 6.5 vocab 范式 | β.3.3 testcase 红线 + β.3.6 docs 引用漂移 detect |
| **软规** (不可 testcase) | 不奉承 / 不假装情绪 / 不拟人比喻 / 工程语言风格 / 双层表达"末层 ≤ 40 字" 的"地道感" | 仅靠 system prompt + 模型训练 — IDE 切换时 ≈ 5-15% 体感差**不可消除** |

接受软规则有不可治理剩余, 不强求 cover 100%. 跨 IDE 时 Sir 应预期"风格微变"但**不影响"工程纪律"** — 后者由硬规 + testcase 锁定.

---

## 10. 完工归档（强制三步）

每个大轮次（如 `P0+20-α` / `P0+20-β.0`）完工，Agent 必做：

1. **TODO 滚档**：
   - 「当前迭代」段精简成 1 段「上轮完工速览」
   - 原「上轮完工速览」整段连同改前完整看板 → 追加到 `docs/TODO_ARCHIVE.md` 顶部 `📜 原文` 段最前
   - archive 目录表插入新行
   - 新一轮看板写到「当前迭代」段
2. **Design doc 保留**：本轮 design doc 保留不动，作历史参考
3. **Tag**：`git tag -a v0.X.Y-codename -m "<轮次名> 完工 / <核心成果>"`

---

## 11. Agent 定期维护责任（β.2.7.6 起强制）

每次 Agent 上线接手前，先跑下面这套"健康巡检"（5 分钟）。发现规律性问题后**主动**优化，不等 Sir 反馈。

### A. 看 directive 健康（每次接手必做）
```powershell
python scripts\registry_dump.py
```
判断标准:
- `fired N 次, helped 0 次, rejected_rate > 30%` → directive 没用，可撤
- `fired = 0` 长期（≥ 14 天）→ 触发条件太严或场景已废，可放宽 / 撤
- `helped_rate > 90%` 长期 → 已是 baseline，可考虑合并进 PERSONA 让它常驻

### B. 看 concerns / relational queue（每次接手必做）
```powershell
python scripts\concerns_dump.py --review --no-interactive
python scripts\relational_dump.py
```
- review queue 长期堆积 → prompt 或模型有问题，调 prompt 或问 Sir 决策
- relational store 空（无 inside_joke / protocol）→ Sir 还没录入，写入到对话报告
- concerns 全部 severity 偏低（< 0.2）→ 信号 decay 太狠或采集不够

### C. 看日志体积 / 进程健康
```powershell
Get-ChildItem docs\runtime_logs\jarvis_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | Format-Table Name, Length, LastWriteTime
```
- 单 log > 200KB 而 session 没崩 → 后台 spam 重，找 grep `[BgLog spam]`
- 7d 内 log 总和 > 100MB → archive 老 log 到 `docs/runtime_logs/archive/`

### D. 看测试健康
```powershell
Get-Content tests\last_run.json | Select-String "passed|failed|duration"
```
- failed > 0 立刻修
- duration > 5min → 看有没有重复 IO，能否 mock

### E. 看 LLM 成本（月度建议跑 1 次）
- grep `[Timing]` 看分布：`stream` 持续 > 10s 表示 prompt 太大或模型慢
- grep `[OpenRouter]` 看 429 / 403 频率
- 看 `memory_pool/key_router_state.json` 永久死的 key 数

---

## 12. Agent Handoff Protocol — 接手 / 工作 / 交接 三阶段

> Sir 2026-05-18 立 "黑箱化 + 可迭代" 目标 — 任何 agent 接手都能 (1) 读懂前面 (2) 知道自己 (3) 规划下一个 agent。本节是入口章程级速览, 详细协议 ↓

- **详细协议** → `docs/AGENT_HANDOFF_PROTOCOL.md` (~250 行, 按需 Grep)
- **KICKOFF 模板** → `docs/AGENT_KICKOFF_TEMPLATE.md` (~250 行, 完工交接时填空)

### 12.1 三阶段速览

| 阶段 | 触发 | 核心动作 | 完工标准 |
|---|---|---|---|
| **1 INTAKE** | 进窗口 | 按 §2 必读表读 5 个文件 (≤ 30 秒) | 心里能回答: 在哪个轨道 / 上轮完工了什么 / 我要做什么 |
| **2 WORK** | KICKOFF 指定 sub-step | 7 步: 读 → grep → code → test → runall → commit → 双层报告 | sub-step / Session 完成且全测绿 |
| **3 HANDOFF** | KICKOFF 全完工 | 滚 TODO → 写下一个 KICKOFF (按模板) → tag (大轮次) → 双层报告 Sir | 下一 agent 接手有完整指引 |

### 12.2 写下一个 KICKOFF 的硬规 (阶段 3 核心)

当前 agent 完工进入阶段 3 时, **必须**生成 `docs/AGENT_KICKOFF_<NEXT_TRACK>.md` 给下一 agent:

| 内容 | 来源 |
|---|---|
| 进窗口必读顺序 | 复用 `AGENT_KICKOFF_TEMPLATE.md` 段落 |
| 当前进度快照 | 从 TODO.md "上轮完工速览" 段提取 |
| 当前 commit 链 | `git log --oneline -10` 输出 |
| 下轮 Session 列表 | 按 design doc 拆 3-5 个, 每个 ~3-6h |
| 第 1 个 sub-step 7 步 | 必须**具体到代码层 + 文件路径**, 不能模糊 |
| 验收标准 | 可 grep / 可跑命令 的客观判定 |

### 12.3 应急: 任务跑到一半交接

不必等"完工", 但**必须** (详 `AGENT_HANDOFF_PROTOCOL.md §A`):

1. 当前已完成 sub-step 独立 commit
2. 在 `docs/AGENT_KICKOFF_<TRACK>.md` 顶部加 "🚧 当前卡点" 段 (≤ 5 行: 想做什么 / 卡在哪 / 尝试过什么 / 建议方向 / Sir 是否需介入)
3. 跑全测确认已 commit 部分没破坏
4. 报告 Sir 标注"需要交接"

---

## 13. 当前迭代状态（动态 — 由 TODO.md 维护）

- **上轮完工**：P0+19 (Nerve 拆分 17479→324 / 16 新文件)
- **当前轨 1**：P0+20-α（拆分收尾 + 4 缺口修复）
- **当前轨 2**：P0+20-β.0（Prompt 重构 + Directive Registry / 详 `docs/PROMPT_REFACTOR_PLAN.md`）
- **当前轨 3**：P0+20-β.3（跨 agent 工程纪律可携带性 + INTEGRITY_STACK 7 层架构 / 详 `docs/JARVIS_INTEGRITY_STACK.md` + `docs/AGENT_HANDOFF_PROTOCOL.md`）

---

*本文件由 `P0+20-W.4 / 2026-05-16` 创建, `P0+20-β.3.2 / 2026-05-18` 加 §12 Agent Handoff Protocol 速览 + §9.2 双层表达 + §2 跨 agent 引用. 变更走 `docs(P0+X-Y.Z): AGENTS.md vN.Y` 类 commit。*
