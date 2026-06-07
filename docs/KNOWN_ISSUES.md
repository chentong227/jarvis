# Known Issues — 已知挂账 BUG (诚实可见, 非静默忽略)

> 预存真 bug 的挂账台账。用 `@unittest.expectedFailure` (xfail) 而非 skip — 真 bug
> 必须可见地挂着, 修好后 xpass 会提醒摘标, 不从 _runall 静默消失。

---

## #pm-parse-12h — `_smart_parse_deadline` pm 未稳定 +12 (真 bug + 时间依赖双重)

- **发现**: 2026-06-07 (body-diff-P2 _runall) / **复核更新**: 2026-06-07 (inner-anchor _runall)
- **性质**: 预存真 BUG **+ 时间依赖**双重 (非 P2/affordance 引入)。
- **现象**: `_smart_parse_deadline('11:30pm', '', '')` 期望 `(23,30)`。解析逻辑 pm 未稳定 +12;且**结果随当前真实时钟浮动** — 某些时段恰好对、某些时段错。
- **关键教训**: 初次误标 `@expectedFailure`(以为稳定红)→ 时间依赖致偶发 xpass。中途改 `@skip`。顾问收尾尝试**确定性 expectedFailure**(mock `time.time` 固定时刻)→ 单跑 3 次稳定红,但 **_runall 整套上下文里仍偶发 xpass**(`_to_24h`/`localtime` 等多处时间耦合,单跑稳套跑漂)→ unittest unexpected-success → 整 suite 误红。**结论: 确定性不可达** → **终态退回 `@unittest.skip`**(顾问预案: 做不到确定性则 skip 带响亮 reason + 留 KNOWN_ISSUES,别静默埋)。
- **根因精确**: `_smart_parse_deadline` 步骤1 hh:mm 正则(`jarvis_commitment_watcher.py:817`)匹配 `11:30` 后立即 `return _to_24h(11,30,None)` — **pm 后缀被吞、am_pm=None**,pm 没 +12。
- **影响测试**: `test_explicit_pm_with_minutes`(`@unittest.skip` 终态)
- **修复计划**: 独立一笔 fix:步骤1 hh:mm 正则带可选 am/pm 后缀传入 `_to_24h`。修好后摘 skip。
- **状态**: OPEN
---

## #hippocampus-not-mounted — search_memory intent 路由三重错配 (RESOLVED)

- **发现**: 2026-06-07 (真机首份激活日志 jarvis_20260607_101414.log turn 6cc0 假焊诊断, commit 3aba672)
- **性质**: 预存真 BUG (持续故障, 重启不修)。
- **现象**: `search_memory` intent 路由目标 `hippocampus.search_recent` 三重错配(organ 名错 / command 名错 / 挂载语义错) → 主脑主动记忆检索 100% `not mounted`(日志行 1255/1446)。turn 6cc0 假焊的根因①(工具失败但口编"6月3日")。
- **根因**: `intent_to_tool_map.json` `search_memory.tool` 自 `41cbf68`(2026-05-20)引入即错 — `hippocampus` 从来不是 `l4_hands_pool` organ(`hand_registry.get` 必 None → `jarvis_chat_bypass.py:2597` not mounted);`Hippocampus` 类也无 `search_recent`(只有 `search_memory`)。
- **修复**: `ad25fcd` — 走准则6 CLI(`intent_map_dump.py --set-tool`)把 `search_memory.tool` 改为 `memory_hands.search_memory`(organ+command 双修)。Tier 真路径 before/after: success=False(not mounted) → success=True(真返回记录 [ID:2477])。
- **状态**: ✅ RESOLVED (ad25fcd)

---

## #tier-wall-drift — SHORT_CHAT 等 4 轻档口 prompt 无墙+衡 (RESOLVED 结构层)

- **发现**: 2026-06-07 (turn 6cc0 假焊诊断, commit 3aba672)
- **性质**: 集成漂移(墙+衡只进重档真输出, 轻档裸奔)。
- **现象**: `anchor_boundary_block`(墙+衡 conflict_guidance)定义在 `jarvis_central_nerve.py:4340`、唯一消费点 legacy mega(`cn:4699`);SHORT_CHAT/WAKE_ONLY/FACTUAL_RECALL/REMINDER_FIRING 4 轻档从独立 helper 早 return、不接收墙变量 → 轻档无墙。假焊正发生在 SHORT_CHAT(turn 6cc0 tier=SHORT_CHAT)。turn 6cc0 假焊的根因②。
- **修复**: `ad9ae2f` — 4 helper 各加 `anchor_boundary_block` 参数 + PromptBuilder BlockSpec(salience 0.88)+ fallback f-string 同补;复用 `cn:4340` 同一份块不另造。B 验(真分类器命中 tier + 真 `_assemble_prompt`):6cc0 类探针**真判 SHORT_CHAT** 且 has_walls/has_conflict=True;4 轻档全 True;重档无回归。
- **状态**: ✅ RESOLVED (结构层, ad9ae2f)
- **注**: 墙 binding 口生成 / 河床闭环 = **设计冻结 35c8bb0** 待施工(`JARVIS_META_ARCH_ALIGNMENT_20260607.md` §4/§6), **不属本条**。本条只解决"墙进入轻档 prompt"的结构漂移。

---

## #verify-standard-all-tiers — B 验须覆盖所有 tier(尤其最高频 SHORT_CHAT)

- **发现**: 2026-06-07 (tier-wall-drift 复盘)
- **性质**: 验证标准补强(流程教训, 非代码 bug)。
- **教训**: TASK 8 镜像 B 4 探针(kindness/honesty/promise/mundane)全飘进重档(DEEP_QUERY/full), **漏 SHORT_CHAT** → 4 轻档实际无墙却签了"墙+衡激活收口"。"轻档未实却签了收口"的根源 = B 验探针未覆盖最高频 tier。
- **标准**: 任何改口主脑 prompt 组装的 B 验, **必须覆盖所有 tier, 且断言探针真命中目标 tier**(打印 classified_tier, 不接受"飘进重档的假绿")。尤其 SHORT_CHAT(Sir 一般对话默认档, 最高频)。
- **状态**: OPEN (流程标准, 后续 B 验遵守)

---

## #affordance-menu-missing — 识 prompt actionable 菜单漏列 `propose_affordance` (挂账 a)

- **发现**: 2026-06-07 (锚重构第一阶段 affordance 实做收尾, TASK 5/9)
- **性质**: 设计缺口 (非 bug)。本轨**刻意只上墙+衡, 不激活 affordance** — 此缺口与该决定一致, 故意不补。
- **现象**: `propose_affordance` 的 dispatch(`jarvis_inner_thought_daemon.py:6171`)+ handler(`:6681`)已接通, 但识 LLM 的 actionable 菜单(`jarvis_inner_thought_daemon.py:4447`)**未列出 `propose_affordance` 选项** → 识 LLM 不知道该 actionable 存在 → 识无法在无人介入下自填 affordance store → affordance 块永不自动出现(store 恒空)。
- **影响**: affordance 子系统机械链路全通(store/核验闸/render/CLI/13 测全绿), 但因菜单漏列, 无自动激活入口。真盘 store 空、口/识 prompt 的 `has_affordance=False` 即此缘故。
- **修复计划**: 待独立动作(顾问/Sir 批激活 affordance 时)→ 在 `:4447` actionable 菜单加 `propose_affordance:<cap_id>[:reason]` 选项 + 走 B 端到端验。本轨不补。
- **状态**: OPEN (deferred by design)

---

## #flaky-runall-baseline — _runall 基线 ±1~2 时序偶发红 (挂账 b)

- **发现**: 2026-06-07 (墙+衡激活轨多次 _runall 观测)
- **性质**: 测试基础设施时序不稳, 非生产码 bug。
- **现象**: `tests/_runall.ps1` 全套跑时, 个别时序敏感套件(`beta44_dashboard_integrity` / `care_live` 等)偶发 ±1~2 红, 单跑则绿。蚀了"_runall 零增红"门的判定确定性 — 难以一眼区分"本笔引入的红" vs "基线 flaky 红"。
- **基线更新**: 现为 **89/41**(① ad25fcd 修好 intent channel 后 `beta536_intent_channel` 多过一条, base==withfix 经 Compare-Object 验证零真增红)。早期记录为 88/42 / 89/40。
- **影响**: 收口判定需逐笔人工核对 flaky 套件名, 增加审查负担。已用"base commit 上跑 _runall 前后对比"法证过 +1 红非本轨 2 行 f-string 引入(TASK 8)。
- **修复计划**: 需独立"flaky 稳定化 / 隔离轨" — 给时序套件注入确定性时钟或 mock IO, 或移出零增红门单独跑。本轨不做。
- **状态**: OPEN

---

## #meta-arch-alignment — 四元架构对齐会(设计冻结已落档)

- **发现**: 2026-06-07 (锚重构第一阶段收口, TASK 9)
- **性质**: 待办事项 (非 bug), 元架构治理。
- **进展**: 对齐会已开, 定案落成**设计冻结** `docs/JARVIS_META_ARCH_ALIGNMENT_20260607.md`(commit `35c8bb0`)。涵盖四元平级互通 / 锚可增减 / 墙独立钉死 / 打通回路(口承接识当轮良心+衡当轮张力+体伤)/ 承接耦合非权重。
- **次序锁死**(设计冻结 §9): 锚重构 → 河床闭环 → 接地骨架长厚 → 动态软化(河床排在动态软化之前)。
- **三红线**(设计冻结 §10): ①不交易 ②不评分 ③墙钉死 — 任一被实现违背即驳回。
- **状态**: OPEN (设计冻结已落, 待按 §9 次序施工; 本轮不施工)

---

## #dev-note-push-proxy — 本机 push 走代理(github:443 直连被挡)

- **发现**: 2026-06-07 (push 已签 commit 时 github.com:443 TCP 建连超时 ~21s)
- **性质**: 本机网络环境注记(非 bug)。
- **现象**: `git push origin main` 直连 `github.com:443` `Could not connect to server`(TCP 建连层失败, 非协议层 — HTTP/1.1/postBuffer 调优无效)。
- **稳定方案**: 走代理单次推, **不持久化 git config**(只用 `-c`):
  ```
  git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push origin HEAD:main
  ```
  探连通性同理: `git -c http.proxy=... -c https.proxy=... ls-remote origin`。
- **注**: 别在传输层(HTTP 版本/buffer)上耗 — 失败在建连层。`git config --get http.proxy` 应保持空(确认没写死)。
- **状态**: OPEN (环境注记, 长期有效)
