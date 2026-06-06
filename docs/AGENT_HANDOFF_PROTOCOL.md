# Agent Handoff Protocol — 接手 / 工作 / 交接 三阶段

> **目的**: 任何 agent (Cursor / Windsurf / Codex / Claude Code / Cline / Aider) 接手都能完成 (1) 读懂前面在做什么 (2) 知道自己要做什么 (3) 给下一个 agent 规划要做什么 的可迭代工程纪律性。
> **强制度**: 阶段 1 / 阶段 3 必须执行, 阶段 2 按当前 KICKOFF prompt 推进。
> **入口**: `AGENTS.md §13` 引用本协议。
> **诞生原因**: Sir 2026-05-18 提出 "黑箱化 + 可迭代" 需求 — 工作流程章程彻底规范化, 让 agent 接力赛可无限循环, 不依赖 Sir 持续投入解释。

---

## 阶段 1 — INTAKE (接手 / 进窗口 30 秒)

### 1.1 必读 (按顺序)

| 顺序 | 文件 | 行数 | 是否全文 |
|---|---|---|---|
| 1 | `AGENTS.md` | < 400 | ✅ 全文 (准则 + 章程 + 本协议引用) |
| 2 | `TODO.md` | < 300 | ✅ 全文 (上轮完工速览 + 当前迭代 + 已知 BUG + 路线) |
| 3 | `docs/AGENT_KICKOFF_<当前轨道>.md` | ~250 | ✅ 全文 (Sir 给你的 KICKOFF / 你的工作任务清单) |
| 4 | 当前轨道 design doc (如 `docs/JARVIS_INTEGRITY_STACK.md`) | ~400 | ✅ 全文 (轨道工程详情) |
| 5 | `docs/runtime_logs/latest.txt` | 1 | ✅ 全文 (latest log 绝对路径 — Sir 反馈 BUG 时 grep 用) |

### 1.2 按需 Grep (不全文 Read)

| 触发 | 看什么 |
|---|---|
| 查规范 (commit / push / 测试 / trace_id) | `docs/JARVIS_WORKFLOW_PROTOCOL.md` |
| 改 `jarvis_*.py` | `docs/JARVIS_PYTHON_STYLE.md` (imports / marker / forbidden / 准则 6.5 vocab 范式) |
| 完工要交接给下一 agent | `docs/AGENT_KICKOFF_TEMPLATE.md` (本协议 §3.2 引用) |
| Sir 提"上次/上轮某 marker" | 先 `Grep TODO.md`, 再 `Grep docs/TODO_ARCHIVE.md` |
| 改了什么核心模块, 想知道历史 | `git log --oneline -- <file>` 看最近 commit |

### 1.3 禁止首读 (浪费 token)

- `jarvis_chat_bypass.py` (3003 行)
- `jarvis_central_nerve.py` (2089 行)
- `docs/TODO_ARCHIVE.md` (1842 行 — Grep 命中后用 offset/limit 读片段)
- `docs/runtime_logs/jarvis_*.log` 全文 (动辄几十 KB)

### 1.4 阶段 1 完工标准 (心里能回答 3 个问题)

| 问题 | 答案来源 |
|---|---|
| 当前在哪个轨道? | TODO.md "当前迭代" 段 + KICKOFF prompt 标题行 |
| 上轮完工了什么? | TODO.md "上轮完工速览" 段 |
| 我要做什么? | KICKOFF prompt 指定的 Session N sub-step M |

回答不出来 → 重读, 不要凭感觉 code。

---

## 阶段 2 — WORK (按 KICKOFF 推进 sub-step)

### 2.1 单 sub-step 标准 7 步

每个 sub-step 走 7 步, 任意一步失败 → `git reset --hard HEAD` 不留烂代码:

1. 读 KICKOFF prompt 当前 sub-step 描述, 确认目标
2. 必要时 Grep `docs/JARVIS_PYTHON_STYLE.md` / 当前 design doc / 上一次类似 sub-step 的 commit
3. 写代码 + marker `[<commit-marker> / <ISO date>]` 注释 (`docs/JARVIS_PYTHON_STYLE.md §2`)
4. 写 testcase (新 BUG 修必须配回归 case, 见 `AGENTS.md §4` 第 2 条)
5. 跑 `tests\_runall.ps1` — 必须 0 FAIL (`AGENTS.md §8`)
6. 按 `AGENTS.md §5` 多行 `-m` 模板 commit
7. 双层报告 Sir (`AGENTS.md §9.2`): 主层工程数据 + 末层 `→ 一句话:` 翻译 ≤ 40 字

### 2.2 红线 (违反立刻 stop + alert Sir)

> **§验收铁律 (接手前必读)**: 任何"进主脑 prompt / 影响决策 / 改真机行为"的改动, 验收层级必须匹配影响半径 —— 真路径改动必须经整机 Agent Mirror (B) 验收, 体图镜像 (A) 或单测不得冒充终验。**接手第一轮即读 `docs/JARVIS_VALIDATION_STANDARD.md`** (双镜像边界表 + 真路径铁律 + 投影零假焊维 + 05-31→假焊事故反例), 不是到验收时才翻。

| 红线 | 来源 |
|---|---|
| 触碰 `.env` / `jarvis_config/sir_profile.json` / `memory_pool/*.db` / 任何 `.gitignore` 内文件 | AGENTS.md §7 |
| 看到 `sk-or-v1-...` / `AIzaSy...` 硬编码 API key | AGENTS.md §7 第 6 条 |
| 改 `JARVIS_CORE_PERSONA` 没 Sir 显式同意 | AGENTS.md §4 第 8 条 |
| 跑测失败 (`failed > 0`) 仍 commit | AGENTS.md §4 第 2 条 |
| `git push --force` 到 main | AGENTS.md §7 第 1 条 |
| `git commit --amend` 已 push 的 commit | AGENTS.md §7 第 3 条 |
| Auto `git push` 没 Sir 显式说"push" / "上线" | AGENTS.md §6 |
| 加新 `_<X>_PATTERNS = [...]` 硬编码 in py (违准则 6.5) | docs/JARVIS_PYTHON_STYLE.md §6 |
| `from jarvis_nerve import *` / 主线程 busy-loop / raw sqlite | docs/JARVIS_PYTHON_STYLE.md §4 |
| 进主脑/决策/真机行为类改动用 A 镜像或单测冒充终验 (未经 B 真路径) | docs/JARVIS_VALIDATION_STANDARD.md |

### 2.3 主动 stop 必备情境 (Sir 物理操作, agent 替不了)

- API key rotation (OpenRouter / Google 控制台)
- 填 `.env` 真实 keys
- 真机实测 Sir 跟 Jarvis 对话
- 任务模糊, 多种合理路径无法判定 → 问 Sir 决策
- 看到 sir_profile 内容会被泄漏到 reply → stop

### 2.4 阶段 2 完工标准

| 子任务 | 完成判定 |
|---|---|
| 单 sub-step | 7 步全做完, commit hash 写入报告, 全测绿 |
| 单 Session (含多个 sub-step) | TODO.md 该 Session 状态从 ⏳ 改 ✅, KICKOFF 该 Session 段标 "完工" |
| 整个 KICKOFF | 进入阶段 3 HANDOFF |

---

## 阶段 3 — HANDOFF (完工交接 / 生成下个 KICKOFF)

### 3.1 滚 TODO.md

每个**大 sub-step 段落**或**当前 KICKOFF 全完工**, 必做 TODO 滚动 (详 `AGENTS.md §10`):

```
TODO.md「当前迭代」段:
   原内容 → 浓缩成 1 段「上轮完工速览」, 含:
   - 完成 N 个 sub-step (β.X.Y.Z-1 ~ -N) 清单
   - 关键 commit hash 链 (3-5 个最重要的)
   - 测试: <pass>/<total> (run_id=<最后一次 last_run>)
   - 留给下轮的 N 个 TODO 点 (含原因 / 优先级)
   - 已知遗留 BUG (如有)

   新内容 → 「当前迭代」段写下一轨道看板
```

原"当前迭代"完整段落 + 改前完整看板 → 追加到 `docs/TODO_ARCHIVE.md` 顶部 `📜 原文` 段最前。

### 3.2 写下一个 KICKOFF (核心步骤)

按 `docs/AGENT_KICKOFF_TEMPLATE.md` 模板填空, 输出到 `docs/AGENT_KICKOFF_<NEXT_TRACK>.md`。必填:

| 段落 | 内容 |
|---|---|
| 进窗口必读顺序 | 复用模板, 替换 `<当前轨道 design doc>` |
| 当前进度快照 | 从 TODO.md 阶段 1.4 三问题答案提取 |
| 当前 commit 链 | git log 最近 10 个 commit 倒序 |
| 下轮 Session 列表 | 按 design doc 拆 3-5 个 Session, 每个 ~3-6h 工时 |
| 第 1 个 sub-step 详细步骤 | **必须具体到代码层**, 如 "改 X 文件 + 写 Y testcase + commit Z" |
| 验收标准 | 可 grep / 可跑命令 的客观判定 |

### 3.3 Tag (大轮次完工时)

大轮次完工 = 不是单 KICKOFF, 是整个轨道 (如 `P0+20-β.3` 完整 5 个 Session) 完工:

```powershell
git tag -a v0.X.Y-<codename> -m "<轮次名> 完工 / <核心成果一句话>"
```

非大轮次完工 (单 sub-step / 单 Session) 不打 tag。

### 3.4 报告 Sir 双层 (按 AGENTS.md §9.2)

**主层 (工程)**:

| 字段 | 内容 |
|---|---|
| commit 链 | 按时间倒序, 含 hash + 一行描述 |
| testcase | `<pass>/<total> (run_id=<id>)` |
| 改动文件清单 | git show --stat 最后 commit |
| 下一个 KICKOFF 路径 | `docs/AGENT_KICKOFF_<NEXT>.md` |
| Sir 可立测项 | 跑什么命令 / 看什么文件能验证 |
| 待 review 决策点 | Sir 需拍板的悬而未决项 (如有) |

**末层 (翻译)**:

`→ 一句话:` ≤ 40 字, 含 "做完了什么 + 下一步建议"。

---

## 阶段间禁忌

| 阶段过渡 | 禁忌 |
|---|---|
| 1 → 2 | 跳过必读直接 code (漏当前迭代上下文, 必触发返工) |
| 2 → 2 (sub-step 之间) | 多个 sub-step 合并 commit (违反 AGENTS.md §4 第 1 条 "独立 commit") |
| 2 → 3 | 没跑全测就交接 (烂代码移交, 下一 agent 接手就踩坑) |
| 3 → 下一 agent | 没写新 KICKOFF (下一 agent 进窗口没指引, 浪费 token 探索, Sir 要重新解释) |

---

## 应急场景

### A. Agent 任务跑到一半失败需要交接

不必等"完工", 但**必须**:
1. 当前已完成的 sub-step 独立 commit (即使只 1 个)
2. 当前未完成的卡点写到 `docs/AGENT_KICKOFF_<TRACK>.md` 顶部 "🚧 当前卡点" 段 (5 行内描述: 想做什么 / 卡在哪 / 已尝试什么 / 下一 agent 建议方向)
3. 跑全测确保已 commit 部分没破坏
4. 报告 Sir, 标注"需要交接"

### B. Sir 临时插话改方向

不属于阶段 1/2/3 的标准流转, 但仍要遵守:
- 当前 sub-step 完成 → 独立 commit → 再接 Sir 新任务
- 中途打断 → 已写未完代码 git stash 或 reset, 不留半成品

### C. Agent 发现 KICKOFF prompt 跟当前代码现状不一致

KICKOFF prompt 是上一 agent (或 Sir) 写的快照, 可能过时。**信代码现状, 不信 KICKOFF**, 但要在阶段 3 交接时:
- 在新 KICKOFF "🚧 当前卡点" 段标注 "上轮 KICKOFF Session N 步骤 X 已被 commit Y 提前完成, 跳过"
- 不要默默跳过 — 下一 agent 看到 KICKOFF 还以为没做, 会重做

### D. Sir 实测真机急修 hotfix (β.3.5 立)

Sir 实测真机发现 BUG, 5-10 分钟内自己急修 (Sir 写代码, 不是 agent)。这条 **不走 3 阶段标准流程**, 走以下精简 5 步:

1. **commit message**: `fix(P0+X-Y.Z-hotfix): Sir <HH:MM> 实测 <现象简述>` — 含 `-hotfix` 后缀标合法应急路径
2. **commit body** 含 `trace-ref: Sir <HH:MM> <现象/log 关键字>` — 让后续 agent grep 历史能 reproduce
3. **测试**: 跑相关 testcase 验证, **不必跑全测 `_runall.ps1`** (急修节省时间; 若改动跨核心模块仍建议跑全测)
4. **跳过滚 TODO + 跳过写新 KICKOFF** — 这是急修, **不是 sub-step / Session 完工**, 章程不动
5. **不打 tag** — tag 留给大轮次完工 (`v0.X.Y-codename`); hotfix 只是 fix, 不是 release

**判别**: Sir hotfix vs Agent sub-step:

| 信号 | Sir 急修 | Agent 标准路径 |
|---|---|---|
| commit message 后缀 | `-hotfix` | `-vocab1 / -<feature_name>` |
| 配套 doc 改动 | 0 (单 commit, 仅代码 + testcase) | 必有 (滚 TODO / 写 KICKOFF) |
| 跑全测? | 关键测就行 | 必须 0 FAIL |
| tag? | 不打 | 大轮次完工才打 |
| trace-ref? | `Sir <HH:MM> <现象>` | `<log basename>` 或 `n/a (架构治本)` |

**Agent 接手协议 (重要)**:

Agent 看到 commit 链含 `*-hotfix` 后缀时:
- **不要"善意"补滚 TODO** — Sir 已决定不动章程
- **不要重写**新 KICKOFF 把 hotfix 拆成 sub-step — Sir 急修不要二次加工
- **可以**在 TODO.md 顶部"近期变更"段写一行 hotfix 历史 (只是记录, 不展开)

---

## 协议元信息

- **本协议从 P0+20-β.3.2 起强制** (2026-05-18 立)
- **变更走** `docs(P0+X-Y.Z): HANDOFF_PROTOCOL vN.M` commit
- **冲突处理**: 与 AGENTS.md 冲突时, AGENTS.md 优先 (因为 AGENTS.md 是入口章程)。但本协议是 AGENTS.md §13 的展开, 正常不冲突。

---

*由 P0+20-β.3.2 / 2026-05-18 创建, 应 Sir 2026-05-18 "黑箱化 + 可迭代" 需求.*
