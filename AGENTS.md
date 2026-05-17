# AGENTS.md — Jarvis AI Agent 入口章程

> **本文件由所有 AI Agent（Cursor / Codex CLI / Claude / Cline / Aider 等）在进入此仓库时自动读取。**
>
> 它是极简入口（< 250 行）。所有详细规则在 `docs/JARVIS_WORKFLOW_PROTOCOL.md`。
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
6. **拒绝硬编码**（β.2.8.8 / 2026-05-17 Sir 立准则）— 一切以足够智能的动态上下文注入让 Jarvis 自然涌现"懂我"的感觉, 不靠硬编码句式/触发/角色

任何改动让这 6 项退步，**Sir 真机实测会立刻打回**。

### 准则 6 —"拒绝硬编码" 4 类反例 + 替代方案

| 硬编码反例 | 等价替代 |
|---|---|
| **句式锁**: directive 写死 "languid drawn-out / Sir~ with tilde / ellipsis for pauses" | 只告事实 (e.g. AFK X min, current window=Y), 信任 Soul L0-L3 + STM + sensor 注入 → 主脑自己涌现 |
| **类型硬编码**: 加 `if commit_type == 'wake'` / `if nudge_type in (...)` 写死 8 类 | 抽象成 Predicate / Concern / 通用 schema (predicate.evaluate(ctx) 让 LLM 翻译) |
| **关键词硬编码**: 反幻觉只 cover "timestamp" 单一 case | 通用条款 (任何 specific factual claim → trace evidence) + 运行时 ClaimTracer 检测 |
| **风格 forbidden list**: "禁止 'Welcome back / 回来了'" 这类负面 list | 删 list, 加正向 evidence + Soul 注入让主脑自由 |

**判别**: 写新 directive/prompt 时, 自问"如果 Sir 看到这段会不会说'怎么和模板一样'?". 凡是 prescribe 句式/词汇/动作步骤的 → 大概率硬编码 → 改成 evidence-only.

---

## 2. 进窗口前 30 秒必读顺序

| 顺序 | 文件 | 行数上限 | 是否全文 |
|---|---|---|---|
| 1 | **本文件 `AGENTS.md`** | < 250 | ✅ 全文 |
| 2 | `TODO.md` | < 300 | ✅ 全文（当前迭代 + 已知 BUG + 路线） |
| 3 | `docs/JARVIS_WORKFLOW_PROTOCOL.md` | < 500 | ❌ 按需 Grep（规范唯一源，需要查规范时打开）|
| 4 | 当前迭代 design doc（如 `docs/PROMPT_REFACTOR_PLAN.md`）| ~400 | ✅ 全文（当前轮工程详情） |
| 5 | `docs/runtime_logs/latest.txt` | 1 行 | ✅ 全文（最新 runtime log 绝对路径） |

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
8. **不重写 PERSONA**：`JARVIS_CORE_PERSONA`（central_nerve.py:129）是 Sir 的 IP，改 PERSONA 必须 Sir 显式同意

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

- 用**表格 + 编号** 回复，不大段散文
- 引用代码用 `<startLine>:<endLine>:<filepath>` 格式（每条回复最多 1-2 处）
- **不使用 emoji** 除非 Sir 先用过
- **不奉承 / 不假装情绪 / 不滥用"完美""卓越"等词**
- 提"建议"之前**先报"事实"**（数据 / 日志 / 行号）
- Sir 提到"上次/上轮/某 marker" → 先 `Grep TODO.md`，再 `Grep docs/TODO_ARCHIVE.md`，**不要全文 Read archive**

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

## 12. 当前迭代状态（动态 — 由 TODO.md 维护）

- **上轮完工**：P0+19 (Nerve 拆分 17479→324 / 16 新文件)
- **当前轨 1**：P0+20-α（拆分收尾 + 4 缺口修复）
- **当前轨 2**：P0+20-β.0（Prompt 重构 + Directive Registry / 详 `docs/PROMPT_REFACTOR_PLAN.md`）
- **本轮 (P0+20-W)**：本规范化协议本身（trace_id 体系 + 测试规范 + commit 模板 + 本文件）

---

*本文件由 `P0+20-W.4 / 2026-05-16` 创建。变更走 `docs(P0+X-W): AGENTS.md vN.Y` 类 commit。*
