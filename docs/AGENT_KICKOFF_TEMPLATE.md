# Agent Kickoff Template — 填空生成新 KICKOFF

> **用途**: 当前 agent 完工进入 HANDOFF 阶段 3 时, 复制本模板, 把 `<占位符>` 替换成具体内容, 输出到 `docs/AGENT_KICKOFF_<NEXT_TRACK>.md`。
> Sir 复制粘贴新 KICKOFF 到新对话窗口 → 下一 agent 接手。
> **协议**: `docs/AGENT_HANDOFF_PROTOCOL.md §3.2` 引用本模板。
> **现有实例**: `docs/AGENT_KICKOFF_INTEGRITY_STACK.md` 是本模板的 reference 实现。

---

## 📋 Sir 复制粘贴版 (一次性给 Agent)

```
你要接手 J.A.R.V.I.S. 项目的 <轨道名: 1 行描述, 如 "INTEGRITY_STACK 7 层架构推进">.

═══ 进窗口必读 (按顺序) ═══

1. AGENTS.md — 项目入口章程 (强制全读, < 400 行)
   特别留意:
   - 准则 5 言出必行 (INTEGRITY ABSOLUTE) — 任何 specific factual claim 必须 trace 到 evidence
   - 准则 6 拒绝硬编码 5 类反例 + 替代方案
   - 准则 6.5 动态架构必须 + LLM 兜底 (持久化 + CLI + L7 LLM-propose 三硬规)
   - §9.2 双层表达 (主层工程数据 + 末层 → 一句话 ≤ 40 字)
   - §13 Agent Handoff Protocol (本 KICKOFF 由此协议生成)

2. TODO.md — 当前迭代状态 (全读, < 300 行)
   看 "上轮完工速览" 段 + 本轮迭代任务

3. <轨道 design doc 路径, 如 docs/JARVIS_INTEGRITY_STACK.md> — <一行描述, 如 "立项 / 推进路线"> (全读, ~<N> 行)
   特别看:
   - <章节 1, 如 "§0.5 L0.5 Dynamic Vocab Substrate">
   - <章节 2, 如 "§3 当前状态盘点">
   - <章节 3, 如 "§4 推进步骤 N Session">

4. docs/JARVIS_PYTHON_STYLE.md — 改 jarvis_*.py 时按需 Grep
   - imports safety net (numpy/json 必须先加)
   - marker [<P0+X-Y.Z / 2026-XX-XX>] 三处一致
   - bg_log vs print 选择
   - 准则 6.5 红线 (_SEED_/get_/CLI 三件套)

5. docs/runtime_logs/latest.txt — 1 行 latest log path
   仅在 Sir 反馈 BUG 时用 Grep, 不要全文 Read

═══ 当前进度快照 (截止 <轨道> commit <hash>) ═══

<状态盘点表 / 文字描述. 推荐格式 e.g.:

L0   ✅ INTEGRITY ABSOLUTE 在 PERSONA (历史已有)
L0.5 ⚠️ 立此规范 + behavior_inference_vocab.json 完成 (β.2.9.12)
L1   ❌ Claim 分类器未做
L2   ❌ Evidence 中央表未做
...

或 e.g.:

- 上轮 (β.2.9.12) 完工: vocab 持久化范式立 + behavior_inference_vocab.json + L7 LLM-propose 预留
- 已完成 sub-step: β.3.0-vocab1 (tool_intent), β.3.0-vocab2 (dashboard_intent)
- 待做 sub-step: β.3.0-vocab3 (memory_correction) 起到 -vocab7
- 已知 BUG: <列表>
>

═══ 你的工作顺序 (严格按此, 不跳序) ═══

╔═══════════════════════════════════════════════════════════════╗
║ Session 0 (优先做) ── <段落标题, e.g. "L0.5 Dynamic Vocab 全面迁移"> ║
╚═══════════════════════════════════════════════════════════════╝

目标: <一句话 / 1-2 行清晰目标>

<具体步骤 / 表格 / sub-step 清单. 推荐表格:

| sub-step | 当前位置 | 迁移目标 |
|---|---|---|
| β.3.0-vocabN | jarvis_<file>.py:_XXX_PATTERNS | memory_pool/<x>_vocab.json + scripts/<x>_dump.py |
...

照搬 <上一次 sub-step commit hash> 范式:
1. <动作 1>
2. <动作 2>
...
>

预期工时: ~<N>h. 每项 ~<M>min.

╔═══════════════════════════════════════════════════════════════╗
║ Session 1 ── <段落标题, e.g. "L4 enforce 升级">              ║
╚═══════════════════════════════════════════════════════════════╝

<同上格式>

预期工时: ~<N>h.

╔═══════════════════════════════════════════════════════════════╗
║ Session 2 ── <段落标题>                                       ║
╚═══════════════════════════════════════════════════════════════╝

<同上>

... (按需加 Session 3 / Session 4)

═══ 执行准则 (跨所有 Session) ═══

1. 准则 6.5: 任何新加 keyword/pattern/list 必须立刻 json + CLI, 永不写死 in py
   (例外: 系统级常量 TICK_INTERVAL / API 错误码黑名单)

2. 准则 5 言出必行: 所有 commit message / TODO 描述 / Sir 报告必须 trace 到
   evidence (commit hash / testcase run_id / log basename). 不空头说"已完成".

3. 每个 sub-step 独立 commit + 全测绿. 失败 git reset --hard HEAD 不留烂代码.
   tests\_runall.ps1 必须 0 FAIL 才允许 commit.

4. 不主动 push. 等 Sir 真机实测后说"push" / "上线" / "上线" 才执行.

5. 不动 .env / jarvis_config/sir_profile.json / memory_pool/*.db 等隐私文件.

6. 双层表达 (§9.2): 主层工程数据 (commit / run_id / file:line / 表格) + 末层
   "→ 一句话:" ≤ 40 字翻译.

7. 每完成 1 个 Session, 按 docs/AGENT_HANDOFF_PROTOCOL.md §3 滚 TODO + 汇报 Sir.

═══ 第 1 个 sub-step 开始 ═══

进窗口先读 AGENTS.md 全文, 然后读 TODO.md, 然后读 <轨道 design doc 路径>.

读完后立刻开始 Session 0 的第 1 个 sub-step (<具体 sub-step 名, e.g. β.3.0-vocab3 memory_correction>):

1. <具体步骤 1, e.g. "设计 memory_pool/memory_correction_vocab.json schema (照搬 tool_intent_vocab.json)">
2. <具体步骤 2, e.g. "从 jarvis_directives.py:_MEMORY_CORRECTION_PATTERNS_ZH/EN 迁移">
3. <具体步骤 3, e.g. "改 _trigger_memory_correction 用 get_memory_correction_patterns()">
4. <具体步骤 4, e.g. "写 scripts/memory_correction_dump.py CLI">
5. <具体步骤 5, e.g. "写 testcase tests/_test_p0_plus_20_beta3X_memory_correction_vocab_persist.py">
6. <具体步骤 6, e.g. "跑全测 tests\_runall.ps1 — 必须 0 FAIL">
7. <具体步骤 7, e.g. "commit: feat(P0+20-β.3.X-vocabN): memory_correction vocab 迁 json + CLI">

═══ 第 1 个 step 完工 stop ═══

完成 <第 1 个 sub-step 名> 后 stop, 按 docs/AGENT_HANDOFF_PROTOCOL.md §3.4 双层报告 Sir
(主层 commit hash + 全测结果 + 下一步打算; 末层 "→ 一句话:" ≤ 40 字).
让 Sir 决定继续推进还是先实测.
```

---

## ⚠️ 模板填空要点 (生成新 KICKOFF 的 agent 注意)

| 占位符 | 怎么填 | 反例 |
|---|---|---|
| `<轨道名>` | 当前推进的轨道大名, 1 行 | ❌ 5 行长描述 / ❌ 含技术 jargon Sir 看不懂 |
| `<轨道 design doc>` | 该轨道的设计文档绝对/相对路径 | ❌ 让 agent 自己找 / ❌ 写过期路径 |
| `<状态盘点>` | 从 TODO.md "上轮完工速览" 提取, 用 ✅/⚠️/❌ 三态机 | ❌ 模糊的 "基本完工" / ❌ 不写 commit hash |
| `<commit hash>` | 上一 agent 最后 commit, 来自 `git log -1 --format=%h` | ❌ 写"最近"等模糊词 |
| `Session N` 拆分 | 按 design doc 拆 3-5 个, 每个 ~3-6h 工时 | ❌ 1 个超大 Session 8h+ / ❌ 拆超过 5 个让 agent 选 |
| 第 1 个 sub-step 7 步 | **必须具体到代码层 + 文件路径** | ❌ "实现 vocab" 不写哪个文件 / ❌ 让 agent 自己想步骤 |

---

## 📦 当前 commit 链 (Agent 接手前必看)

```
<填最近 10 个 commit, 倒序, 格式: <hash> <type>(<marker>): <subject>>

示例:
63611f3 feat(P0+20-β.3.0-vocab1): tool_intent vocab 迁 py → json + CLI (准则 6.5)
080c611 docs(P0+20-β.2.9.12): TODO 滚动 — 20 commits 累计 + INTEGRITY_STACK 立项完整
043af31 feat(P0+20-β.2.9.12): vocab 持久化治本 + 准则 6.5 升级 + INTEGRITY_STACK doc 升级
...
```

---

## 🎯 验收标准 (本 KICKOFF 全完工)

<填**可 grep / 可跑命令** 的客观判定, 不要 "差不多就行">

示例 (从 INTEGRITY_STACK KICKOFF 抄):

```powershell
# 在 d:\Jarvis 跑, 应 0 命中:
rg -p "_PATTERNS\s*=\s*[\[\(]" --type py
rg -p "_KEYWORDS\s*=\s*[\[\(]" --type py
rg -p "_VOCAB\s*=\s*[\[\(]" --type py
```

应该只看到:
- `_SEED_<X>_PATTERNS` (fallback 仅, OK)
- `_<X>_PATTERNS_CACHE` (mtime cache 变量, OK)

不应再看到任何 `_<X>_PATTERNS = [...]` / `_<X>_KEYWORDS = (...)` 类硬编码。

---

## 🚧 当前卡点 (如有)

> 此段只在阶段 3 应急场景 (协议 §A "任务跑到一半失败需要交接") 才写。
> 正常完工 KICKOFF 删除本段。

格式 (≤ 5 行):

```
- 想做什么: <一行>
- 卡在哪: <一行, 含 file:line 或 error message>
- 已尝试什么: <一行>
- 下一 agent 建议方向: <1-2 行>
- 触发 Sir 介入?: <yes/no, 如 yes 说明何时>
```

---

*本模板由 P0+20-β.3.2 / 2026-05-18 创建, `docs/AGENT_HANDOFF_PROTOCOL.md §3.2` 引用. 变更走 `docs(P0+X-Y.Z): KICKOFF_TEMPLATE vN.M` commit.*
