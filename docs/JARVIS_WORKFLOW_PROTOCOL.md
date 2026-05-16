# Jarvis Workflow Protocol — 工程协作章程

**版本**：v1.0 / 2026-05-16
**作者**：Sir + Claude 4.7 / P0+20-W
**生效范围**：所有在本仓库工作的 AI Agent（Cursor / Codex / Claude / Cline / Aider 等）+ 人工操作。

> 本文件是 **唯一规范源**。`AGENTS.md` / `.cursor/rules/jarvis_workflow.mdc` / `TODO.md` 章程段都引用本文件。
> 出现冲突时以本文件为准。

---

## 0. TL;DR — 一句话规范

> **每一个 commit 都要可追溯、可重现、可回滚；每一行运行时日志都能 grep 到本轮对话；每一个测试都有 trace-id 落档。**

---

## 1. Trace ID 体系（核心可追溯性）

### 1.1 三层 ID

| 层 | ID 名 | 生命周期 | 格式 | 作用域 |
|---|---|---|---|---|
| **进程级** | `session_id` | 单次启动 Jarvis 进程 | `sess_YYYYMMDD_HHMMSS_<PID>` | 所有 daemon 线程 / 哨兵 / sentinel 共享 |
| **对话级** | `turn_id` | 单轮对话（user wake → jarvis 回复完毕）| `turn_YYYYMMDD_HHMMSS_<4 hex>` | 该轮 stream_chat / prompt 装配 / FAST_CALL / TTS / 字幕 / Integrity Check |
| **工程级** | `marker` | 单个 sub-step / BUG 修复 | `P0+X-Y.Z` / `R7-α2` / `轴3-L0` 等 | code 注释 + commit message + TODO + archive |

### 1.2 `session_id` 实现

- 入口 `jarvis_nerve.py:__main__` 启动时生成
- 写入全局单例 `TraceContext.session_id`
- 也写到 `docs/runtime_logs/jarvis_<timestamp>.log` 文件头部

### 1.3 `turn_id` 实现

- `VoiceListenThread` 在 `text_ready` 信号触发时生成新 `turn_id`
- 写入 `JarvisState.current_turn_id` + `ConversationEventBus`
- `bg_log` / `print` 自动从 `TraceContext` 取 + 注入到日志行前缀
- 该轮回复完毕（`Pipeline Timer Full pipeline` 后）清空 turn_id（保留 session_id）

### 1.4 日志格式（统一）

```
<timestamp> [<session_id>] [<turn_id>] [<organ>] <message>
```

例：

```
2026-05-16 09:25:33.847 [sess_20260516_092307_35344] [turn_20260516_092533_a3f7] [Pipeline Timer] TTFT 3.0s
2026-05-16 09:25:34.012 [sess_20260516_092307_35344] [turn_20260516_092533_a3f7] [Asm Diag] _assemble_prompt 1274ms
2026-05-16 09:25:34.890 [sess_20260516_092307_35344] [turn_20260516_092533_a3f7] [Hippocampus/KeyRotate] 跳过 google_1
2026-05-16 09:25:35.124 [sess_20260516_092307_35344] [turn_20260516_092533_a3f7] [Integrity Check] no_tool_called
```

**关键好处**：
- `grep turn_20260516_092533_a3f7 latest.log` → 拿到该轮完整链路
- `grep sess_20260516_092307_35344 latest.log | wc -l` → 该次启动总日志行数
- 跨日志文件查问题：`grep -r turn_20260516_092533_a3f7 docs/runtime_logs/` 跨文件 grep

### 1.5 Background daemon 日志

后台 daemon（HabitClock / Anticipator / ScreenshotSentinel / Hippocampus backfill / SmartNudge 等）**没有 turn_id**（不在对话内），但**必须有 session_id + organ tag**：

```
2026-05-16 02:33:15.234 [sess_20260516_023300_18472] [HabitClock LLM] 反思完成
2026-05-16 02:33:42.567 [sess_20260516_023300_18472] [Hippocampus Backfill] 补 3 条 embedding
```

---

## 2. 测试规范

### 2.1 目录结构（**P0+20-W 后逐步迁移，不强制一次性归位**）

```
tests/
├── _runall.ps1              # 跑全测入口（必须输出 last_run.json）
├── conftest.py              # pytest 全局 fixture（trace_id / report writer / session hook）
├── _source_corpus.py        # 已有：多文件源码扫描的拼接器
├── unit/                    # 单元测试（纯函数 / 单类，无 IO 无 thread）
├── integration/             # 集成测试（多模块协作，可有 IO，无网络）
├── regression/              # BUG 回归（_test_p0_plus_X.py 等历史 BUG 守卫）
└── smoke/                   # 启动冒烟（import 全通 / CentralNerve 能装配 / 不真启动 Worker）
```

**P0+20-W 不动现有测试结构**（90+ 个 `_test_*.py` 在 tests/ 根），仅强制新增测试按规范放到对应子目录。后续 P0+20-X / B 系列 routine 工作时再逐步归位。

### 2.2 测试命名规范

| 类型 | 文件名模式 | 例 |
|---|---|---|
| **回归** (BUG 守卫) | `_test_reg_<marker>_<topic>.py` 或现有 `_test_p0_plus_X_topic.py` | `_test_reg_p0_plus_20_alpha1_numpy.py` |
| **单元** | `_test_unit_<module>_<topic>.py` | `_test_unit_safety_referential.py` |
| **集成** | `_test_int_<chain>.py` | `_test_int_chat_bypass_integrity.py` |
| **冒烟** | `_test_smoke_<scope>.py` | `_test_smoke_imports.py` / `_test_smoke_central_nerve_assemble.py` |

### 2.3 测试报告（`tests/last_run.json`）

每次 `_runall.ps1` 或 `pytest tests/` 跑完，**强制写一份**：

```json
{
  "test_run_id": "test_20260516_103045_4521",
  "session_id": "sess_20260516_103045_<pid>",
  "git_head": "dea1eb5",
  "git_branch": "main",
  "started_at": "2026-05-16T10:30:45.123Z",
  "ended_at": "2026-05-16T10:31:02.890Z",
  "duration_s": 17.7,
  "summary": {
    "total": 1098,
    "passed": 1098,
    "failed": 0,
    "skipped": 5,
    "errors": 0
  },
  "failed_tests": [],
  "marker_context": "P0+20-α.1 verification"
}
```

由 `tests/conftest.py` 的 `pytest_sessionfinish` hook 自动写（**pytest 直接跑时生效**），或由 `tests/_runall.ps1` 末尾聚合写入（**走 PS1 入口时生效**）。两条路径产物字段一致。

### 2.4 测试硬规

1. **每个 sub-step commit 前** 必须本地 `pytest tests/` 全绿；不允许"先 commit 再修测试"
2. **新增 BUG 修复** 必须配 1+ 回归 testcase（即使是 import fix 这种简单 BUG 也要加一条 smoke 守卫）
3. **测试不能有外网依赖**（要嘲弄 `safe_gemini_call` / `safe_openrouter_call` / `KeyRouter` 等）
4. **测试不能写真实 `memory_pool/*.db`**（用 tmp_path fixture）
5. **测试 trace-id** 写到 last_run.json，commit message 引用：`testcase: 1098/1098 pass (run_id=test_20260516_103045_4521)`

---

## 3. Git 工作流

### 3.1 Branch 策略

- `main`：**唯一长期分支**。单人项目主干开发，不强制 PR。每个 commit 必须 testcase 全绿
- `exp/<topic>`：可选实验分支。**不要 push 到 origin**（避免污染 remote）
- 不开 `dev` / `staging` / `release` 等分支

### 3.2 Commit Message 模板（**强制**）

```
<type>(<marker>): <subject ≤ 50 chars>

<body 1: 因果链 / 改动描述 / 影响范围>

<body 2: 测试情况>

<body 3 可选: 副作用 / 留尾 / 后续 TODO>

testcase: <pass>/<total> pass (run_id=<test_run_id>)
trace-ref: <runtime_log_basename if applicable>
```

#### type 枚举（必填，单选）

| type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | BUG 修复 |
| `refactor` | 重构（行为不变）|
| `perf` | 性能优化 |
| `docs` | 文档 / 规范 |
| `test` | 测试 |
| `chore` | 杂务（依赖 / 配置 / lint）|
| `revert` | 回滚 |

#### marker 必填（一律 `<type>(<marker>)` 格式）

- 主迭代：`P0+20-α.1` / `P0+20-β.0.3` / `轴3-L0.2` / `R7-β5`
- 杂务：`P0+20-W.2` / `chore-2026-05-16`

#### 示例

```
fix(P0+20-α.1): jarvis_memory_core.py missing import numpy as np

Root cause: P0+19-5 split moved 9 np.* call sites out of jarvis_nerve.py
into jarvis_memory_core.py (CorrectionMemory.search / UnifiedMemoryGateway
/ Anticipator) but didn't add 'import numpy as np' at file top.

Symptom (jarvis_20260516_092307.log): KeyRouter mis-attributed 'name np
is not defined' NameError to google_3 key as 403 PERMISSION_DENIED,
polluting health probe state.

Fix: single line 'import numpy as np' at jarvis_memory_core.py:30 with
P0+20-α.1 marker comment.

testcase: 1098/1098 pass (run_id=test_20260516_104215_a1f3)
trace-ref: jarvis_20260516_092307.log
```

### 3.3 何时 commit / 何时 push / 何时 tag

| 操作 | 时机 | 工具 |
|---|---|---|
| `commit` | 每个 sub-step 完成 + 全测绿 | `git commit -m ...` 手动 |
| `push` | **大轮次完工 + Sir 真机验收后** | `git push origin main` 手动 / Agent 提示但不自动 |
| `tag` | 大轮次完工：`v<major>.<minor>.<patch>-<codename>` | `git tag -a v0.20.1-cleanup -m "..."` |
| 中途也想 push | 担心机器丢数据 / 跨设备同步 | Sir 主动说"现在 push 一下"，Agent 才 push |

#### 版本号规则（SemVer 变体）

- `MAJOR`：API 大变（重构入口 / 删模块）
- `MINOR`：新功能 / 新模块（β / 新 sub-step batch）
- `PATCH`：BUG 修复 / 小优化
- `codename`：人类可读的轮次代号

#### 已有 tag 候选

- `v0.19.0-nerve-split`（P0+19 完工，可补打）
- `v0.20.0-workflow`（P0+20-W 完工）
- `v0.20.1-cleanup`（P0+20-α 完工）
- `v0.21.0-prompt-refactor`（P0+20-β.0 完工）

### 3.4 Git 安全协议（**Agent 硬规**）

1. **NEVER** `git push --force` 到 main（除非 Sir 明确说"force push"）
2. **NEVER** `git rebase -i` / `git add -i`（交互式命令 Cursor 不支持）
3. **NEVER** 跳过 hooks（`--no-verify` 等），除非 Sir 明确同意
4. **NEVER** `git commit --amend` 修改已 push 的 commit
5. **NEVER** 更新 `git config`（user.email / user.name 等）
6. **NEVER** commit 含敏感信息的文件：`.env` / `jarvis_config/keys.*.json` / `jarvis_config/sir_profile.json` / `memory_pool/*.db` 已 `.gitignore` 保护，但 commit 前肉眼扫一眼 `git status` 确认
7. **PUSH 前必须**：① `pytest tests/` 全绿 ② Sir 真机验过该大轮次 ③ `git log` 看一遍待 push 的 commits

---

## 4. AI Agent 行为规范

### 4.1 进窗口的前 30 秒（Agent 必读顺序）

| 顺序 | 文件 | 用途 | 读取规则 |
|---|---|---|---|
| 1 | `AGENTS.md`（仓库根 / 各 Agent 自动读）| 极简入口 + 章程指针 | 全文，但短 |
| 2 | `TODO.md` | 当前迭代 / 已知 BUG / 路线 | 全文，必须 < 300 行 |
| 3 | `docs/JARVIS_WORKFLOW_PROTOCOL.md`（本文件）| 规范唯一源 | 按需 grep，**不全文读** |
| 4 | 当前迭代 design doc（如 `docs/PROMPT_REFACTOR_PLAN.md`）| 当前轮工程详情 | 全文（已经控制在 ~400 行） |
| 5 | `docs/runtime_logs/latest.txt` | 最新日志绝对路径 | 1 行 |

**反例**（禁止）：
- ❌ 一进窗口就 `Read jarvis_chat_bypass.py`（3003 行，浪费 token）
- ❌ `Read docs/TODO_ARCHIVE.md`（1842 行，仅按需 Grep）
- ❌ `Read docs/runtime_logs/jarvis_*.log`（动辄几十 KB）

### 4.2 干活硬规

1. **Sub-step 独立 commit**：每个 sub-step 完工独立 commit，便于 `git revert` 单点回滚
2. **测试前置**：commit 前必跑 `pytest tests/`，失败 `git reset --hard HEAD` 不留烂代码
3. **Marker 一致性**：code 注释 `[P0+20-X.Y / 2026-05-16]` + commit message `<type>(P0+20-X.Y): ...` + TODO 看板状态 ✅ 三者同步
4. **不啰嗦改 PERSONA**：JARVIS_CORE_PERSONA 是 Sir 的 IP，改 PERSONA 必须 Sir 显式同意（P0+20-β.0.3 已是例外）
5. **不主动 push**：见 §3.3
6. **不动 .env / keys.py**：Sir 手动维护，Agent 只读模板 `.env.example`
7. **不写 `.gitignore`**：除非 Sir 明确同意（避免破坏现有保护）

### 4.3 沟通风格

- 用表格 / 编号回复 Sir，不大段散文
- 引用代码用 `<startLine>:<endLine>:<filepath>` 格式（最多 1-2 处）
- 不使用 emoji 除非 Sir 用过（保持专业克制）
- 不奉承 / 不假装情绪 / 不滥用"完美"等词
- 提"建议" 之前先报"事实"

### 4.4 完工归档（**强制三步**）

每个大轮次完工，Agent 必做：

1. **TODO 滚档**：
   - 「当前迭代」段精简成 1 段「上轮完工速览」
   - 原「上轮完工速览」整段连同改前完整看板 → 追加到 `docs/TODO_ARCHIVE.md` 顶部 "📜 原文" 段最前
   - archive 目录表插入新行
   - 新一轮看板写到「当前迭代」段
2. **Design doc 保留**：本轮 design doc（如 PROMPT_REFACTOR_PLAN）**保留不动**，作历史参考
3. **Tag**：`git tag -a v0.X.Y-codename -m "<轮次名> 完工 / <核心成果>"`

---

## 5. 文档体系

### 5.1 永久文档

| 文件 | 角色 | 行数上限 |
|---|---|---|
| `README.md` | 朋友视角的安装 + 入门 | < 300 行 |
| `AGENTS.md` | 所有 AI Agent 入口章程 | < 250 行 |
| `TODO.md` | 当前迭代工作板 | < 300 行 |
| `docs/JARVIS_WORKFLOW_PROTOCOL.md`（本文件）| 规范唯一源 | < 500 行 |
| `docs/TODO_ARCHIVE.md` | 历史轮次完工归档 | 无上限（按时间倒序 + 目录表 + grep）|

### 5.2 轮次文档（每个大迭代一份）

| 当前轮 | 文件 |
|---|---|
| P0+19 | `docs/NERVE_SPLIT_PLAN.md`（已完工，历史参考）|
| P0+20-β.0 | `docs/PROMPT_REFACTOR_PLAN.md`（进行中）|
| P0+20-W | （本文件即是）|
| 未来 B / B+ | `docs/<TOPIC>_PLAN.md` |

每个 design doc 必含 11 节：TL;DR / 起点 / 调研 / 设计 / 数据结构 / 算法 / sub-step / 验收 / 风险 / 工程量 / 归档协议。

### 5.3 日志体系

| 目录 | 文件 | 用途 |
|---|---|---|
| `docs/runtime_logs/` | `jarvis_<timestamp>.log` | 每次启动一份 |
| `docs/runtime_logs/` | `latest.txt` | 一行 = 最新 log 绝对路径 |
| `docs/funnel_logs/` | `funnel_<timestamp>.log` | SmartNudge 漏斗判定 |
| `tests/` | `last_run.json` | 最近一次 pytest 报告 |

---

## 6. 安全 / 隐私

### 6.1 永远不进 git 的文件

`.gitignore` 已保护以下（仅列重点，详见 `.gitignore`）：

- `.env`（API keys 真值）
- `jarvis_config/keys.*.json`
- `jarvis_config/sir_profile.json`（Sir 个人画像）
- `jarvis_config/bilibili_auth.json`
- `memory_pool/*.db` / `*.db-shm` / `*.db-wal`（对话记忆）
- `memory_pool/skill_registry.jsonl`（运行时计数）
- `docs/runtime_logs/`（含真实对话）
- `docs/funnel_logs/`
- `.venv/` / `__pycache__/` / `.pytest_cache/`
- `ffmpeg.exe` / `ffprobe.exe`（大文件 / 二进制）

### 6.2 Agent 操作敏感文件硬规

- **读 `sir_profile.json`**：可以（用于 ProfileCard 注入），但**不要把内容打印到 chat 回复**
- **写 `sir_profile.json`**：只允许 `ProfileCard.apply_correction` 这种已有接口；Agent 不直接 `Write`
- **读 `memory_pool/*.db`**：只允许通过 `Hippocampus` API；不直接 `sqlite3.connect`
- **API key**：Agent 看到 `sk-or-v1-...` / `AIzaSy...` 在代码里 → 立刻提醒 Sir 这是泄漏

---

## 7. 性能基线（必须守住）

| 指标 | 当前基线 | 守住的阈值 | 测点 |
|---|---|---|---|
| TTFT (Time To First Token) | 3.0s（P0+18-f.1 后）| < 5s | `[Pipeline Timer] TTFT` |
| `_assemble_prompt` 耗时 | 1274ms（P0+20-β.0 前）| < 600ms（β.0 后 < 400ms）| `[Asm Diag]` |
| Full pipeline | 6.2s | < 8s | `[Pipeline Timer] Full pipeline` |
| Prompt size (DEEP_QUERY) | 30K chars | < 25K（β.0 后 < 19K）| `[Prompt Size]` |
| 1098 testcase | 全绿 | 全绿 | `tests/last_run.json` |

**任何 PR / commit 让这些指标退步必须有充分理由 + Sir 同意**。

---

## 8. 协议版本演化

| 版本 | 日期 | 主要变化 |
|---|---|---|
| v1.0 | 2026-05-16 | 初版（P0+20-W）：trace_id 体系 / 测试规范 / commit 模板 / Agent 行为规范 |

后续变更走 `chore(P0+X-W): protocol v1.X` 类 commit，更新顶部版本号 + 在本节加行。

---

*Sir 的 5 项设计理念（高效 / 反应迅速 / 符合人设 / 懂我 / 言出必行）是本协议的最高准则。所有规则的存在都是为了让 Jarvis 在这 5 项上长期可持续地达标。*
