# JARVIS 全流程闭环 — 工作进度 (做一步记一步, 抗上下文丢失)

> **用途**: Sir 担心 agent 上下文超限遗忘 → 本文件是**持久化工作日志**。任何接手 agent (含
> 重置后的我) 读本文件 + `git log` 即可完整恢复状态。**做一步, 记一步, 独立 commit。**
> **总图**: `docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md` (设计真相源)。
> **三位一体**: `JARVIS_TRINITY_ARCHITECTURE.md` (体) + `JARVIS_VOICE_AND_MIND_REFACTOR.md` (口/识/势能自转)。

---

## 已建地基 (commit 链, 倒序)

| commit | 件 |
|---|---|
| fd89550 | E 强闭环写侧: 识 propose_stance → stance(review) → 透镜 |
| a5539d9 | B2 fix: 口写体 turn_id 缺失退时间戳 ref (镜像验出) |
| 200750a | C-wake: 体势能驱动唤醒频次 |
| 6f94636 | B2: 口写体 turn→共现边 |
| d6a106b | C-read: 识 attend 体势能 (BODY SIGNALS) |
| bf82c0b | value-backoff baseline (前轮 WIP, Sir 选 A) |
| af47a62 | B: current_focus 桥 BodyFocus + 口透镜势能 seeds |
| 9a41e36 | B3: 体势能 E + body_delta |
| 03b3d47 | churn fix + 开 gate + 势能自转设计 v3 |
| 8ea41eb | 体六层 P1-P6 (manifold/weaver/stance/lens) |

地基测试: 61+ body test 全绿; 镜像端到端验过 (体势能 Δ=12 + 口 grounded reply + 口写体 15 边)。

---

## 闭环工作清单 (8 项) + 状态

> 排序: 先做自包含/低上下文风险 (D1/hippo), 跨模块调查重的 (A/B/C/E) 稳妥推进。

| # | closure | 闭哪环 | 触哪文件 | 上下文风险 | 状态 |
|---|---|---|---|---|---|
| **D1** | 复杂度度量 (metric 替计数告警) | 维护环 | manifold/weaver (熟) | 低 (纯计算) | ✅ (真机验: blob score 0.222 largest_frac 0.778) |
| **G0** | hippo 永不动 guard + doc | 锚 | 新 test + doc | 低 (小) | ✅ (静态守护 2 test) |
| **D2** | 主动合并决余簇 (alias, 不动源) | 维护环 | manifold/weaver/focus | 中 | ✅ (alias+resolve+Weaver检测+focus去重, 4 test) |
| **A** | outcome→stance (Sir 反应 reinforce/weaken) | 学习环后半 | meta_feedback(查) + stance | 中 (需查 meta_feedback) | ✅ (lens 记投影 stance + apply_reaction_outcome + chat_bypass 接线, 7 test) |
| **C** | nudge 群退化 publish→体能量 | 感知环 | nudge 模块群(查) + 体 | 中-高 | ✅ (compute_energy 加 nudge 张力源 + SWM 读 4 etype, 6 test) |
| **B** | 言出必行用体作 evidence 源 | 验证环 | ClaimTracer(查) + 体 | 中 | ✅ (body_evidence_provider + lens.body_claim_evidence + chat_bypass 接线, 11 test) |
| **E** | SOUL L2/3→体/识 收敛, 删 relational 平行 | 内敛 | SOUL/central_nerve(查) | 高 (敏感, 真机验) | 🔶 机制就绪 (flag-gated 替换 L2/L3, 默认关; **待 Sir 真机 A/B 验后开+退旧**, 5 test) |
| **收尾** | D输出闸 / G口吸收Layer1/2 / 硬编码清 / F dyad | — | 热路径 | 高 | ⬜ 最后 |

**状态图例**: ⬜ 待 / 🔵 进行中 / ✅ 完成(commit) / 🔶 部分

---

## 逐步日志 (做一步记一步)

- **[P3 拒绝动作不重试 ✅]** ~17:05: Sir 真测 D/E thought 反复试 `call_tool:concerns.progress_update` → tool_not_in_allowlist → "misread twice" churn。**修(准则8 治本不复发)**: `_execute_actionable` 抽出 `_dispatch_actionable`, 顶部加守门 — 结构性拒绝(allowlist/unknown/deprecated/retired/path_not_allowed)后记 `(kind:target)→ts` (去 payload, 通用任何 actionable), `DENIED_ACTIONABLE_COOLDOWN_S=900s` 窗口内同 key 直接降级 none。**区分"暂时 gated"(cooldown/sal/cap 自然恢复, 不记不误锁)。** 有界 dict(64, 过期/最旧淘汰)。7 test。注: 跑回归发现 `_test_fix12` 在 HEAD 也 hang(真 LLM 调用, 非我引入); 我的 stance_loop/daemon-core 测过绿。下一步 P2 势能驱动。
- **[P1 进度跨天守门 ✅]** ~16:50: Sir 真测 (今天5-31) "记得喝多少水" → Jarvis 报 9 杯(来自 LTM 5-28 旧记录) / 思考脑报 "8 of 10 today"(ledger daily_progress iso=5-28 旧值)。**根因**: 今天 daily_progress 空(还没记录) → 系统没说"今天没记录"而捞旧数据当今天。**修(通用非硬编码, 准则5接地)**: (1) `jarvis_concerns.py` to_prompt_block — 有 target 但今天没记录 → 显式 "NOT logged yet today" evidence(防主脑 fallback 旧 LTM); (2) `jarvis_inner_thought_daemon.py:4635` ledger truth 行加 iso_date==today 守门(stale→"NO entry today, last X on <date> STALE")。新 test 4 case + 修 truncate_silo(stale 行为更新) + fix33 t02(原硬编码旧日期, 改 today)。31 pass。注: fix33 含前轮 WIP, 我的 t02 修留在未提交树不混入本 commit。下一步 P3。
- **[数据卫生 ✅]** ~14:09: Sir 要求按体识说整理已有数据 (去重/标记/调用)。审计发现体是 blob (score 0.222, 最大面 78%), 根因 = **识(inner_thought)自生成大量近重复 self-talk** (8 个 'Sir 装睡' joke 变体 / 重述 hydration-standby thread / 2 个 Metoprolol joke)。**做**: (1) `scripts/manifold_dump.py --merge-dups [--threshold]` 新 CLI (准则6 可逆工具) — alias 合并近重复(不删源); 跑 0.86 合并 8 对。(2) **lens.project alias-aware** — resolve 折叠近重复到代表, dup 不重复投影占预算 (T7 守)。(3) 数据: archive 6 个识自生成近重复 joke (active 33→27, 保代表, 可逆 state=archived); 精确重复 protocol 0 个 (审计的"dup"只是 50-char 前缀碰撞, 全文不同, 未误删)。(4) hippocampus 永不动 (只碰 relational_state/manifold, 全 gitignored runtime, 可逆)。**blob metric 仍 0.222**: 结构性 (单人关系本就一密集主题 + embed 边只增不按 cosine prune → 累积), 非功能问题; embed_threshold 0.72→0.78 实验无效(旧边不删)已回滚。**未动 Sir 的 concern/life 数据** (unfinished_jiazhao_ke1 sev=0 等待 Sir 确认是否完成)。code(lens/CLI/test)提交, data 改 gitignored 仅报告。
- **[E prereq1+2 ✅]** ~13:57: closure E 替换前提 (Sir 选 A)。**prereq1** 透镜 seed 吃当前 user_input — `lens.seeds_from_text(text)` 词法匹配体节点 (复用 Weaver `_distinctive_terms`), `build_lens_block(user_input=)` 当前话题 seed 优先 + 体 standing 焦点补充 → 替 Layer3 current-focus 角色 (验: "interview"→sir_interview_prep_balance/sir_sleep_streak)。**prereq2** 替 Layer2 时 STRICT-RULE protocol 常驻 — central_nerve `_lens_replaces_l2` 分支注入 protocols-only block (`to_prompt_block(top_jokes=0,...)` 砍 jokes/baggage 仅留 STRICT RULES), 修镜像 phase B 实测的人设违反 ("Understood, Sir.")。E7/E8 test + 98 body 绿。下一步: 数据卫生 (de-blob/dedup/mark)。
- **[E 镜像 A/B + 2 bug fix]** ~13:40: Sir 要求镜像 A/B 验 closure E。**核发现**: (1) prod `lens_inject_enabled=1` 已开但**透镜投影空** — 根因 `body_energy.json` 被 stale 测试数据 (th1/th2, 不存在节点) 污染 → default_seeds 指向空 → 投影空; 污染源 = `tests/_test_body_p2_weaver.py::_mk_weaver` 漏传 energy_path → weave_once 写真 `memory_pool/body_energy.json` (测试隔离 bug)。(2) 镜像 3 phase: A(lens off)=Layer2/3 grounded reply; B(replace on + 透镜空)=回复违反 STRICT-RULE protocol ("Understood, Sir.", 因 Layer2 被退+透镜空); C(replace on + energy 修复)=透镜投影真内容 grounded。(3) 直接内容对比: 透镜(对的 seed)relevance-ranked 远优于 Layer3 severity-ranked context-blind; 但透镜与 Layer2 jokes/protocol **重叠 (平行确认)** 且**不含 always-on STRICT-RULE protocol** (只投 graph-connected 的)。**2 修**: lens.default_seeds 过滤不存在 seed→fallback concern (透镜永不因脏 energy 空); p2_weaver _mk_weaver 补 energy_path/stance_path (测试隔离)。prod body_energy 已 weave 重生 (77 nodes/6 energy). 96 body test 绿。**结论: closure E replace 暂不可开 — 需先补 (a)用户输入驱动 seed (b)always-on protocol 保证 (c)stance(当前0)。详 A/B 报告。**
- **[E 🔶机制就绪]** ~13:16: SOUL Layer2/3 → 体/lens 收敛 (内敛, 渐进退平行)。**核发现**: central_nerve `_assemble_prompt` 现状 relational_block(L2) + lens_block(体) **并存** = 平行表示 (准则6#4 反例)。加 2 flag (manifold seed `lens_replaces_layer2`/`lens_replaces_layer3`, 默认 0) + lens 模块 2 helper。central_nerve 接线: **透镜活(lens_block 非空) + flag 开 → 退对应 Layer2/3 旧块** (relational/attention 不 append)。**默认关 → 零生产影响; 透镜空 → 不替 (双重安全)。逐块退: 先 lens_inject_enabled=1 看投影质量, 满意再 replaces_layer2/3=1 退旧, 别一次全换。** ⚠️ **待 Sir 真机 A/B 验** (做完标准要求, 不擅自开 + 不删旧 builder)。5 test 绿 + 全 body(95)绿。**A/B/C/E 机制全落地 → 5 环全闭 (E 待真机验收开关)。** 下一步: 收尾 (D/G/硬编码迁移/F) + 双层报告。
- **[B ✅]** ~13:11: 言出必行用体作 evidence 源 (闭验证环)。ClaimTracer 仿 recall_provider 加 `body_evidence_provider` (并行兜底, recall 未命中后试体): 抽 `_match_claim_against_provider(claim, provider, label)` 通用核 (DRY, recall/body 共用词重叠匹配), `_try_body_match` trace_to='body'。`trace_to_evidence`/`trace_reply` 加 body_evidence_provider 参 (None=老 caller 零变化)。默认 provider `lens.body_claim_evidence(q)`: active stance(conf>=0.4) + 词重叠的体节点文本(concern/thread/joke/protocol) → list[{source,content}]。chat_bypass post-stream trace 处接线 (仅 unverified 罕触发, 不碰 TTFT)。**不受 lens_inject gate (只读验证非投影); 体已有 stance/节点 → closure B 立即 live (不等透镜上热路径)。** 加 reset_lens_for_test。11 test 绿 + claim_tracer 回归(157)绿。下一步: closure E (SOUL L2/3 收敛, 敏感真机最后做)。
- **[C ✅]** ~13:05: nudge 群退化 publish→体能量 (闭感知环)。compute_energy 加张力源2: Weaver `_nudge_tension_map` 读 SWM 近期 4 类 nudge/care 警报(`proactive_care_advice`/`care_signal_derived`/`soul_alignment_advice`(取 missed_concern_ids)/`proactive_nudge_fired`) → 映射到对应 active concern node 张力 (per_event 0.5 × salience, 单 concern 封顶 1.5)。**只计真实存在 concern node (不造幻影, 准则5); 新外部警报不受 stance 覆盖压制(放电靠 event 老化+识 attend); delta-on-rise 杜绝平台期 churn。** config 进 manifold seed energy (nudge_tension_* 5 键) + JSON override + manifold_dump CLI。Weaver 加 event_bus 注入(生产 lazy 全局 bus)。"一个 wellness 警报 = 体张力" → 识经 body_delta attend 而非 nudge 抢话筒。6 test 绿 + 回归(79 body)绿。下一步: closure B 言出必行用体作 evidence 源。
- **[A ✅]** ~12:47: outcome→stance 闭学习环后半。lens.project(turn_id=) 记录本轮真正投影进 prompt 的 stance_id (有界 OrderedDict + 1800s TTL 对齐 meta_feedback 30min 反应窗口, 纯 in-memory 准则1) + `apply_reaction_outcome(turn_id, reaction)`: engaged→reinforce(+0.1, evidence_kind='outcome'/ref=turn_id), rejected→weaken(0.15, 跌破0.15转review), 幂等consume。chat_bypass F6c3/meta_feedback 处: mark 前收 pending reply 的 turn_id → mark 后调 apply。**透镜上热路径前 (gate 默认关) 无投影记录 → no-op; closure E/G 开 lens 后自动闭环。** 7 test 绿 + 回归(lens/stance/e/p4 共25)绿。下一步: closure C nudge→体能量。
- **[D2 ✅]** ~11:20: manifold alias(add_alias/resolve链+防环/persist) + Weaver weave_geometric 检测 cosine>=merge_threshold(0.90) 近重复→add_alias(代表=度数高) + BodyFocus.current_focus 按 resolve 去重 + complexity merged_dups. **不删源(hippo永不动)**, 体层把 dup 当代表。4 test 绿 + 回归绿。维护环闭合(decay/prune/merge 齐)。下一步: A outcome→stance (需查 meta_feedback, 留给新窗口)。
- **[G0 ✅]** ~11:10: hippo 永不动 guard — 静态扫体 5 模块断言无 hippo 写(INSERT/store_memory/...)+ weaver embed 只读注释。2 test 绿。下一步: D2 主动合并 (针对 blob)。
- **[D1 ✅]** ~11:05: manifold.complexity_report (health/score/largest_surface_frac/grounded_frac) + CLI `--complexity` + Weaver 每 weave log + blob/over_dense 告警。真机验: prod manifold = blob (score 0.222, largest_frac 0.778) — 正确抓出 54 节点 blob。3 test 绿。下一步: G0 hippo guard。

---

## 恢复指南 (若上下文丢失, 接手 agent 读这里)

1. 读本文件 + `git log --oneline -15` → 知道做到哪。
2. 读 `JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md` §4 (5 个 closure) = 工作真相源。
3. 体的 API: `jarvis_relational_manifold.py` (边/面/势能) / `jarvis_relational_weaver.py` (织网+能量+口写体) / `jarvis_body_focus.py` (焦点) / `jarvis_relational_lens.py` (投影) / `jarvis_stance.py` (立场)。
4. 测试: `tests/_test_body_*.py` (全绿基线)。改完跑对应 + 相关回归。
5. 红线: hippocampus 永不动 (体只引用); 全接地 (无 trace 边/stance 拒); Sir 否决; selective 写防 bloat。
