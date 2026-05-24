# Jarvis TODO

> 🚨🚨🚨 **2026-05-24 09:10 Sir — Phase D 全部主体 done (32 commit), 等 Sir 1-2 周真测验稳定** 🚨🚨🚨
>
> Sir 8:52 "继续按顺序做完, 包括前面留着的子项" → Cascade catch-up 推 M3.B.Claim alias + M3.C-trace deprecation + M4.5.3 dual-mark, 然后用 Sir 准则 7 元否决权把 9 个 sub-step (M3.E / Claim rename / M3.C/D/G/F / M4.6 / M4.7 / M5.3 / M6.1 / M6.2 / M6.3) 合 **M6.4 真 class split 一起做**. 不重复改两次 import.
>
> ## ✅ Phase D 收尾 (32 commit, ~3000 行 code+test+doc, 0 主链路 break)
>
> | Milestone | sub-step | commit |
> |---|---|---|
> | **M1** | 8 step (Lineage Trace) | 8 |
> | **M2** | 5 step (MemoryHub R+W facade) | 5 |
> | **M3** | 4 done (A 死代码 / B blood/SoulRouter / B.Claim alias / C-trace deprecation) | 5 |
> | **M4** | 6 done (1 schema / 2 audit / 3 hub / 4 migration apply / 5.1+5.2+5.3 dual-write+restore+mark) | 7 |
> | **M5** | 1 done (5.1 Conductor dual-emit, 5.2 自动 work via SWM) | 1 |
> | **M6** | audit done | 1 |
> | docs | cleanup checklist + audit doc + TODO | 5 |
> | **共** | | **32** |
>
> ## 🧹 Cleanup checklist 兑现路径 — `docs/JARVIS_LEGACY_CLEANUP_CHECKLIST.md`
>
> 9 个 deferred sub-step 全归 M6.4 真 class split (1 表 audit 完):
>
> ```
> M6.4 触发条件: Sir 真用 1-2 周稳定 + cleanup checklist deferred 项数 < 3
>   → M6.4 真 class split (PromptAssembler/StateRestorer/Lifecycle)
>   → 顺手解决 M3.E + M4.6 + M4.7 + M5.3 + M6.1+2+3 (9 sub-step)
>   → M6.5: 3-brain mv + run() 移 _legacy/ (`deprecated_3_brain_invoked` event = 0 后)
> ```
>
> **真做 trigger**: Sir 真测 1-2 周, dual-write/dual-emit/deprecation warn 都稳定 → M6.4 启动.
>
> ## � Sir 真测期 (~1-2 周, 期间 reshape 暂停)
>
> ```powershell
> # 每天看一下 SWM lineage 是否真 record (M1)
> python scripts/lineage_dump.py --stats
>
> # 看 PromiseLog 真单源 (M4)
> python scripts/audit_promise_sources.py
>
> # 看 deprecated_3_brain_invoked 触发数 (期望 0)
> # → 0 触发 1 周 → M6.5 安全删除 3-brain
>
> # 看 conductor_intent SWM event (M5.1 dual-emit)
> # → 主脑应能从 SWM block 看到 → 验证 M5.2 自动 work
> ```
>
> ## � 已知 BUG (post-reshape 一起修)
>
> 主脑 prompt 工程问题 (跟 reshape 无关):
> 1. `reminder_hands` 幻觉 organ 名 (实际 `memory_hands`)
> 2. `add_reminder` 缺 `intent` 参数 (主脑同时问+发, 矛盾)
> 3. Malformed `FAST_CALL[None/None]`
>
> ## 🎯 Sir 真测期间下一步 menu
>
> ```
> # A: 真测 OK 后启动 M6.4 (真 class split, 解决 9 sub-step)
> Cascade, M6.4.
>
> # B: 修上面 3 个 fast_call 幻觉 bug
> Cascade, 修 fast_call bug.
>
> # C: 真测期间 audit/dashboard tooling 改进
> Cascade, 加 audit dashboard.
> ```
>
> 详 `docs/JARVIS_M6_NERVE_SPLIT_AUDIT.md` + `docs/JARVIS_LEGACY_CLEANUP_CHECKLIST.md` + `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md`.
>
> ---
>
> ## 历史: M5 close + M6 audit (08:50)
>
> Sir 8:43 "我觉得还是全部重构完再慢慢测找 bug 比较合适" + 8:44 "继续往下推进, 不需要测试什么" → Cascade 一口气推 M5 + M6 audit.
>
> ## ✅ M5 close (M5.1 dual-emit + M5.2 自动 work + M5.3 需 M6 配合)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `444f3a4` | **M5.1** | Conductor dual-emit `conductor_intent` SWM (path_a + path_b) + 4 test |
> | (自动) | **M5.2** | 主脑 prompt SWM block 默认 salience_floor=0.3, Conductor 0.7 自动可见, **0 code change** |
> | ⏸ | **M5.3** | 停 `__NUDGE__` push (需 M6 主脑被 SWM 主动触发机制配合) |
>
> ## 📋 M6 audit 完 — `docs/JARVIS_M6_NERVE_SPLIT_AUDIT.md`
>
> central_nerve.py = **4790 行 / 32 method / god class**:
> - `__init__`: 957 行
> - **`_assemble_prompt`: 2537 行** ⚠️⚠️⚠️
> - `run()`: 364 行 (3-brain 长任务流)
>
> ## 🎯 M6 子步建议 (按 risk, 每步独立 commit + Sir 真测)
>
> | Step | risk | scope | 预计 |
> |---|---|---|---|
> | **M6.1** | 低 | `_assemble_prompt` 拆 12 个 `_build_xxx_block` 私有方法 (仍 1 class, 行为不变) | 3 commit, 1 周 |
> | **M6.2** | 中 | 5 tier 分流抽离 `_assemble_full_prompt` / `_wake_only` / `_factual_recall` / `_short_chat` / `_standard` | 2 commit, 1 周 |
> | **M6.3** | 中 | `__init__` 957 行拆 `_init_xxx` 6 个方法 | 3 commit, 1 周 |
> | **M6.5** | 中-高 | 3-brain mv `_legacy/3_brain_attempt/` + run() 移 + worker.trigger_routing 删 | 1 commit, 1 周 |
> | **M6.4** | 高 | 真 class split — `JarvisCore / PromptAssembler / StateRestorer / Lifecycle` 4 class facade | 2 周 |
>
> ## Sir 决定 menu
>
> ```
> # 选项 A: 推 M6.1 (低 risk 拆 _assemble_prompt 子函数化)
> Cascade, 推 M6.1.
>
> # 选项 B: 跳 M6 推 M3.D (3-brain 移 _legacy/)
> Cascade, 先做 M3.D.
>
> # 选项 C: 暂停 reshape 真用一段
> Cascade, M5 close 够了, 真用 1 周再做 M6.
> ```
>
> 详 `docs/JARVIS_M6_NERVE_SPLIT_AUDIT.md`.
>
> ---
>
> ## 历史: M4 主体全 done (08:40)
>
> Sir 8:35 跑 M4.5.1 真测 OK + 8:36 明确指示 "工具调用 bug 不影响功能, 重构完再修" → 3 个 fast_call 幻觉 bug 已记 TODO. Cascade 继续按顺序推 M4.5.2 daemon dual-source restore.
>
> ## ✅ M4 主体全 done (7 commit, ~1500 行 code+test+doc, dual-source ready)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `b39196d` | **M4.1** | PromiseLog schema 扩 4 kind + backfill (9 test) |
> | `3a48e71` | **M4.3** | Hub.write_commitment 4 kind → PromiseLog (7 test) |
> | `209a081` + `5afea9c` | **M4.2** | audit + is_deleted filter fix |
> | `fe4e9b2` | **M4.4** | migration script + 11 test (Sir 真跑 apply OK) |
> | `0d39e1e` | **M4.5.1** + checklist | CW dual-write to PromiseLog + `docs/JARVIS_LEGACY_CLEANUP_CHECKLIST.md` (4 test) |
> | `38b4c9a` | **M4.5.2** | CW init 也从 PromiseLog 拉 active (10 test, dual-source restore) |
> | `bd2e1f5` | bug log | 3 fast_call 幻觉 bug 记账 |
>
> ## 📊 当前 PromiseLog 真单源 (90+ 条, dual-write 5 条新)
>
> ```
> PromiseLog: 91+ (commitment kind dual-write 真生效)
> Commitments SQLite: dual-write 仍写 (备份 + 老 daemon 兼容, M4.5.3 后停)
> ```
>
> ## ⏸ M4 剩余 (推 reshape 稳定 1 周后)
>
> | 子项 | risk | 何时做 |
> |---|---|---|
> | **M4.5.3** | 中-高 | 停 SQLite 写 + 删 dual-write (需要 PromiseLog 真 nudge mark + 1 周观察期) |
> | **M4.6** | 中 | 18+ caller grep 替换 `add_commitment` → `hub.write_commitment` (建议合 M6 NERVE_SPLIT 一起做) |
> | **M4.7** | 低 | dashboard `pending_callbacks.jsonl` 读 PromiseLog (M4.5.3 后) |
>
> ## 📋 Sir M4.5.2 真测 (~3 min)
>
> ```powershell
> # 1. 重启 jarvis (CW init 应同时从 SQLite + PromiseLog 拉)
> # 看 log 含 "[CommitmentWatcher/Persist] 从 SQLite 恢复 X 条" + "[CommitmentWatcher/PromiseLog] 从 PromiseLog 恢复 Y 条"
>
> # 2. 加新 commitment 触发 dual-write
> # 3. 看 PromiseLog 90 → 91+
> python scripts/audit_promise_sources.py
> ```
>
> ## 🎯 Sir M4.5.2 真测 OK 后 menu
>
> 按 Sir 准则 8 (优雅可持续 > 简单), 我建议**暂停 reshape**, 让 Sir 真用 1 周观察:
> - dual-write 是否稳 (PromiseLog 跟 SQLite 数据一致?)
> - daemon nudge 行为是否一致 (没漏 fire / 没重复 fire?)
> - PromiseLog 总数是否合理增长?
>
> 稳定后再做 M4.5.3 (停 SQLite 写) + M5 (决策路径整合).
>
> ```
> # 选项 A: 推 M5 (Conductor + IntentResolver + FAST_CALL 整合)
> Cascade, 推 M5.
>
> # 选项 B: 暂停 reshape (推荐)
> Cascade, M4 主体够了, 我真用 1 周, 稳定后再做 M4.5.3 + M5.
>
> # 选项 C: 同时修上面 3 个 fast_call bug (主脑 prompt 工程)
> Cascade, 跳 reshape, 先修 reminder_hands 幻觉 + add_reminder 缺参数.
> ```
>
> Sir 8:28 跑了 M4.4 `--apply` 真把 1 条 Commitment 迁进 PromiseLog (kind=commitment, pid=p_c69c8325, backup `_legacy/data_migration_backup/20260524_082755/`).
>
> Sir 8:29 明确指示: **"保证我们重构结束并且稳定以后把老版本逐步褪去, 保证架构的 neat"** → Cascade 立 `docs/JARVIS_LEGACY_CLEANUP_CHECKLIST.md` 跟踪 7 类临时 layer + cleanup trigger.
>
> ## ✅ M4 主体 done (6 commit, audit fix + M4.5.1 dual-write + cleanup doc)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `b39196d` | **M4.1** | PromiseLog schema 扩 (3 新 field + backfill) |
> | `3a48e71` | **M4.3** | `Hub.write_commitment` 4 kind → PromiseLog |
> | `209a081` | **M4.2** | audit script (dry-run, 修 is_deleted bug `5afea9c`) |
> | `fe4e9b2` | **M4.4** | migration script + 11 test (Sir 真跑 apply OK) |
> | `5afea9c` | M4.4-fix | audit `is_deleted=0` 过滤 (跟 migration 对齐) |
> | `0d39e1e` | **M4.5.1 + checklist** | CW.add_commitment dual-write to PromiseLog + 4 test + `docs/JARVIS_LEGACY_CLEANUP_CHECKLIST.md` (7 类临时 layer + cleanup trigger) |
>
> ## 📊 当前 PromiseLog 单源 (Sir 真测后)
>
> ```
> PromiseLog: 90 (16 pending 7 fulfilled 63 untracked 2 cancelled + 2 commitment[+1 from migration])
> Commitments SQLite active: 0 (全 nudged)
> CyclicTask / WatchTask / Concerns active: 0
> ```
>
> ## 🧹 7 类临时 backward-compat layer (`docs/JARVIS_LEGACY_CLEANUP_CHECKLIST.md`)
>
> | # | 类型 | 数量 | Cleanup trigger |
> |---|---|---|---|
> | 1 | Deprecated stub (UnifiedMemoryGateway / TaskWorkerPool) | 2 | M5+ 0 真 instantiate |
> | 2 | File shim (jarvis_memory_gateway.py) | 1 | 18 caller 改 import |
> | 3 | Dual-write (CW.add_commitment → PromiseLog) | 1 | **M4.5.3** (daemon 切 PromiseLog 后) |
> | 4 | noqa F401 转发 import | 20+ | stub 删后 |
> | 5 | `__unknown__` author backfill 标 | 1 | 1 个月后 |
> | 6 | TypeError fallback (老 signature) | 1 | UnifiedMemoryGateway 删后 |
> | 7 | Hardcoded fallback (proxy_url) | 1 | **永久保留** (defense in depth) |
>
> Sir 准则 8 强制: **加新 layer 必须在此 doc 加 row**, 不允许 commit.
>
> ## 📋 Sir M4.5.1 真测 (~3 min)
>
> ```powershell
> # 1. 重启 jarvis 跑 1-3 轮 (触发主脑 fast_call set commitment)
> # 2. 看 PromiseLog 多出新 commitment kind 条 (dual-write 真生效)
> python scripts/audit_promise_sources.py
> # 3. mutation_receipts 含 source='cw.add_commitment.dual_write/*'
> Get-Content memory_pool/mutation_receipts.jsonl -Tail 5 | Select-String "dual_write"
> ```
>
> ## 🎯 M4.5.2 + 3 (Sir 真测 OK 后)
>
> | 子项 | risk | scope |
> |---|---|---|
> | **M4.5.2** | 中 | daemon 改优先读 PromiseLog (fallback SQLite, 不破老) |
> | **M4.5.3** | 中 | 停 SQLite 写, dual-write block 删 (cleanup checklist #3 兑现) |
> | **M4.6** | 中 | 全文 grep `add_commitment` → `hub.write_commitment` |
> | **M4.7** | 低 | dashboard `pending_callbacks.jsonl` 读 PromiseLog |
>
> ## Sir M4.5.1 真测 OK 后 menu
>
> ```
> Cascade, M4.5.1 真测 OK, 推 M4.5.2 daemon 切.
> # 或
> Cascade, M4 暂停, 真用一段稳定后做 M4.5.3+ + cleanup checklist 兑现.
> ```
>
> ## 🐛 已知 BUG (Sir 8:36 "重构完再修", post-reshape 统一处理)
>
> 3 个 fast_call 幻觉 bug, 不影响最终功能 (Time Hook 兜底 schedule reminder 08:36 真触发 ✅), 但污染 prompt + 浪费 token:
>
> 1. **主脑幻觉 organ 名 `reminder_hands`** (实际叫 `memory_hands`) → "❌ reminder_hands 未挂载"
>    - 根因: prompt organ_whitepaper 没明列子命令 (主脑凭印象拼名)
>    - 修法 (M5+ 后): 从 `hand_manifests` 自动构建 `command → organ` 反向 vocab + prompt 列子命令
>
> 2. **`add_reminder` 缺 `intent` 参数** → "❌ memory_hands.add_reminder: 缺少 intent 参数"
>    - 根因: 主脑同时问 Sir "提醒啥内容" + 抢发 fast_call (用户没回答怎么有 intent)
>    - 修法: prompt 加 "缺参数时先问 Sir, 不发 fast_call" 规则
>
> 3. **Malformed `FAST_CALL[None/None]`** (organ=None command=None)
>    - 根因: 主脑输出格式错的 FAST_CALL block (可能上下文 truncate / 模板错)
>    - 修法: 加 PreFlight 拦 None FAST_CALL + 主脑 prompt 加 "格式不全宁可不发"
>
> 这 3 个属于**主脑 prompt 工程**, 不是 reshape 范畴. 推 M5+ 主脑决策路径整合时一起修.
>
> ---
>
> ## 历史: M4.1+2+3+4 完成 (08:27)
>
> Sir 8:23 M4.1+2+3 真测 OK + 指示"按顺序往下推进, 除非合后面更优雅", Cascade 继续推 M4.4 — 写完 migration script + 11 test, 但**没擅自动 prod 数据** (准则 8). Sir 自己跑 `--apply` 真执行.
>
> ## ✅ M4.4 done (commit `fe4e9b2`, script + 11 test, 0 prod 数据动)
>
> 写完 `scripts/migrate_commitments_to_promise_log.py` (dry-run / apply / rollback 三模式), 跑 dry-run 显示**真 active 只 1 条** (audit 之前算 4 是没过滤 `is_deleted=0`).
>
> ## � Sir 真执行 M4.4 apply (~30s, 真写 prod 数据)
>
> ```powershell
> # 1. dry-run 再看一遍
> python scripts/migrate_commitments_to_promise_log.py
>
> # 2. 真执行 (auto backup → 真写 → mark SQLite)
> python scripts/migrate_commitments_to_promise_log.py --apply
>
> # 3. 看 PromiseLog 多了 1 条 (kind=commitment, author=sir, evidence 含 migration tag)
> python scripts/audit_promise_sources.py
>
> # 4. 出问题回滚 (backup 在 _legacy/data_migration_backup/<timestamp>/)
> # python scripts/migrate_commitments_to_promise_log.py --rollback 20260524_xxxxxx
> ```
>
> ## 🎯 M4.5+6+7 路线 (Sir M4.4 apply 真测 OK 后)
>
> | 子项 | risk | scope |
> |---|---|---|
> | **M4.5** | 高 | CommitmentWatcher 改 read-only PromiseLog (老 add_commitment 退化为 hub shim, 不再写 SQLite) |
> | **M4.6** | 中 | 全文 grep `add_commitment` / `mark_fulfilled` 替换 `hub.write_commitment` |
> | **M4.7** | 低 | dashboard `pending_callbacks.jsonl` 消费时读 PromiseLog |
>
> ## Sir M4.4 真测 OK 后 menu
>
> ```
> Cascade, M4.4 apply OK, 推 M4.5 CommitmentWatcher 退化.
> # 或
> Cascade, 暂停 reshape 真用一段, M4.5+6+7 之后再做.
> ```
>
> ---
>
> ## 历史: M4.1+2+3 完成 (08:20)
>
> Sir 8:12 M3.A+B 真测 OK, Cascade 按 Sir 准则 7+8 跳 M3 剩余子项 (Claim/E/CDGF 合 M6 一起做), 直接推 M4 PromiseLog 合并主体.
>
> ## ✅ M4.1+2+3 done (3 commit, audit 显示**真要 migrate 仅 4 条**)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `b39196d` | **M4.1** | PromiseLog schema 扩 — Promise dataclass +3 field (`who_promised`/`trigger_pattern`/`bound_to_concern_id`) + `_backfill_who_promised()` 老数据迁移 + kind 扩到 4 类 (commitment/cyclic/watch/self_promise, 老 hard/soft 兼容并存) (9 test) |
> | `3a48e71` | **M4.3** | `Hub.write_commitment` 4 kind 路由 → PromiseLog 单源 (修 M2.A stub bug, 真接 `PromiseLog.register`) (7 test) |
> | `209a081` | **M4.2** | `scripts/audit_promise_sources.py` audit (dry-run 只读) — 看 5 source 数据现状 |
>
> ## � audit 结果 (`python scripts/audit_promise_sources.py`)
>
> | Source | 总数 | active | 待迁 |
> |---|---|---|---|
> | **PromiseLog** (目标) | 88 (16 pending / 7 fulfilled / 63 untracked / 2 cancelled, 全老 kind soft/hard) | - | - |
> | **Commitments SQLite** | 29 | **4** | **4** |
> | **CyclicTask** | NOT EXISTS | 0 | 0 |
> | **WatchTask** | 4 | 0 | 0 |
> | **Concerns notes_for_self** | 0 | 0 | 0 |
> | **总计待迁** | - | - | **4 条** |
>
> ## � Sir 真测 (~3 min)
>
> ```powershell
> # 1. 重启 jarvis 跑 1-3 轮
> # 2. 跑 audit script 看现状 (重启 jarvis 数据应该跟前一样)
> python scripts/audit_promise_sources.py
> # 3. 验 hub.write_commitment 真写 PromiseLog (chat 触发主脑 fast_call set commitment 时)
> Get-Content memory_pool/jarvis_promise_log.json | Select-Object -First 100
> # 4. lineage + mutation_receipts 仍正常
> python scripts/lineage_dump.py --list-decisions --limit 2
> Get-Content memory_pool/mutation_receipts.jsonl -Tail 3
> ```
>
> ## 🎯 M4.4+ 决策 (4 条数据 risk 已极低)
>
> | 子项 | risk | scope | 建议 |
> |---|---|---|---|
> | **M4.4 apply migration** | 低 (4 条) | 真把 4 条 Commitments → PromiseLog + backup SQLite | Sir 决定 |
> | **M4.5 CommitmentWatcher 退化** | 高 | daemon 改 read-only PromiseLog (老 add_commitment 退化为 hub shim) | M4.4 验证后做 |
> | **M4.6 caller grep 替换** | 中 | 全文 `add_commitment` / `mark_fulfilled` → hub.write_commitment | M4.5 配套 |
> | **M4.7 dashboard 兼容** | 低 | `pending_callbacks.jsonl` 消费时读 PromiseLog | M4.5+6 之后 |
>
> 按 Sir 准则 8: **M4.4 真 migration 是一次性, 跑后可立刻回滚 (老 SQLite backup 保留)**. 我建议 Sir 真测 M4.1+2+3 OK 后, 直接做 M4.4. M4.5+6+7 是真"5 套统一"核心改 daemon + caller, 风险高建议**分多 commit + 每 commit 真测**.
>
> ## Sir 真测 OK 后 menu
>
> ```
> Cascade, M4.1+2+3 真测 OK, 推 M4.4 apply migration (4 条).
> # 或
> Cascade, 4 条数据没必要 migrate, 直接推 M4.5+6 (daemon + caller 真换).
> # 或
> Cascade, M4 主体够了, 暂停 reshape 真用一段.
> ```
>
> 详 `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §6.5.
>
> ---
>
> ## 历史: M3.A + M3.B (partial) 完成 (08:05)
>
> Sir 8:01 M2 全部真测 OK (14 decision / 224 evidence / 0 broken / blocks=2,0 = prompt tier 正常分布), Cascade 立刻按顺序推 M3.
>
> ## ✅ M3.A + M3.B (partial) 完成 (3 commit, ~250 行 cleanup)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `08e65df` | **M3.A** | 死代码 + proxy 单源 — 删 2 bak file (archive_promise / integrity tainted) + `jarvis_config/network.json` 配置抽取 + `jarvis_utils._PROXY_URL` 走 config + `jarvis_nerve` 用 utils _PROXY_URL (8 test) |
> | `fb27f39` | **M3.B.1** | 删 blood.py 3 个死 dataclass (`CorrectionEntry / MemoryFragment / PromptLayer`) — P0+19-5 拆分残留 0 caller, 同名 class 冲突消除 (11 test) |
> | `11208b5` | **M3.B.2** | 删 enhanced.SoulRouter 死代码 — 50 行 lightweight 占位 0 caller, 唯一在 `jarvis_routing.SoulRouter` (advanced w/ BILINGUAL_BRIDGE) (2 test) |
>
> ## 📋 Sir M3.A+B 真测 (~3 min, 重启 jarvis)
>
> ```powershell
> # 1. 重启 jarvis 跑 1-3 轮
> # 2. 验 proxy 仍走 jarvis_config/network.json
> python -c "from jarvis_utils import _PROXY_URL; print('Proxy:', _PROXY_URL)"
> # 3. 验 enhanced.SoulRouter 没了 / routing.SoulRouter 仍在
> python -c "import jarvis_enhanced; print('enhanced.SoulRouter exists:', hasattr(jarvis_enhanced, 'SoulRouter'))"
> python -c "from jarvis_routing import SoulRouter; print('routing.SoulRouter:', SoulRouter)"
> # 4. 验 blood.py 3 个死类没了
> python -c "import jarvis_blood; print('blood.CorrectionEntry:', hasattr(jarvis_blood, 'CorrectionEntry'))"
> # 5. 看 chat 仍 work + lineage 仍 record
> python scripts/lineage_dump.py --list-decisions --limit 2
> ```
>
> **预期**:
> - `Proxy: http://127.0.0.1:7890` (从 config 读)
> - `enhanced.SoulRouter exists: False`
> - `routing.SoulRouter: <class 'jarvis_routing.SoulRouter'>`
> - `blood.CorrectionEntry: False`
> - chat 流畅 + lineage 0 broken
>
> ## ⏸ M3 剩余子项 (Sir 决定优先级)
>
> | 子项 | risk | scope | 状态 |
> |---|---|---|---|
> | **M3.B.Claim** | 中 | Claim → FactClaim/IntegrityClaim 改名 + 8+ testcase update | 等 Sir 决定 |
> | **M3.E** | 中 | jarvis_enhanced 拆 3 file (ProactiveShield + ProactiveCompanion + SkillTreeTracker) | 等 Sir 决定 |
> | **M3.C/D/G/F** | 高 | 3-brain 整体移 `_legacy/` + central_nerve.run() 800 行剥离 + worker.trigger_routing 删 | 建议跟 M6 NERVE_SPLIT 一起做 |
> | **M4** | 高 | 5 promise sources → PromiseLog 单源 (data migration) | Sir 决定 |
>
> ## 🎯 Sir M3.A+B 真测 OK 后下一步
>
> ```
> Cascade, M3 真测 OK, 推 M3.B.Claim 改名 (低-中 risk).
> # 或
> Cascade, 跳 M3.E, 直接动工 M4 (PromiseLog 合并).
> # 或
> Cascade, M3 partial 够了, 暂停 reshape 让我写真用例.
> ```
>
> Sir 7:53 M2.B 真测全 OK ("chat 流畅 / mutation 写 / lineage record / blocks=2"), Cascade 按 Sir 指示按顺序推 M2.C cleanup 全部完成.
>
> ## ✅ M2 全部 done (5 commit, ~1700 行 code+test+shim, 0 破坏)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `2dc2458` | **M2.A** | `MemoryHub` alias + 6 `write_*` + `query/to_prompt_block` 搬运 (17 test) |
> | `c4a2cb5` | **M2.B** | `central_nerve.memory_gateway` swap to Hub R+W 单 facade (262 regression) |
> | `c310737` | **M2.C.1+2** | `UnifiedMemoryGateway` → deprecated stub (110 → 50 行) + DeprecationWarning + flaky test fix |
> | `4630648` | **M2.C.3** | `git mv jarvis_memory_gateway.py → jarvis_memory_hub.py` + 老 file 留 backward-compat shim (18 caller 0 改) |
> | `b8f0ffd` | TODO | 上轮真测 checklist |
>
> ## 📋 Sir M2 全部真测 (~3 min, 重启 jarvis)
>
> ```powershell
> # 1. 重启 jarvis 跑 1-3 轮
> # 2. 验证 file rename 后所有 import work
> python -c "from jarvis_memory_gateway import MemoryHub; from jarvis_memory_hub import MemoryHub as H2; print('Same:', MemoryHub is H2)"
> # 3. 看 mutation 仍写
> Get-Content memory_pool/mutation_receipts.jsonl -Tail 3
> # 4. 看 lineage 仍记录 + blocks=1-2 + 0 broken chain
> python scripts/lineage_dump.py --list-decisions --limit 3
> python scripts/lineage_dump.py --stats
> ```
>
> **预期 (M2 全部加强)**:
> - chat 流畅, 无 ImportError / AttributeError
> - prompt 仍含 `[UNIFIED MEMORY - Cross-source recall]:` block (hub.to_prompt_block 走 nerve=self 路径)
> - mutation_receipts.jsonl 仍 append (老 caller 兼容)
> - lineage 仍 record decision (M1 + M2 不冲突)
> - 没看到 `DeprecationWarning: UnifiedMemoryGateway is deprecated` (因为现 0 真使用)
>
> ## 🏗 M2 架构成果 (R+W 单 facade)
>
> ```
> # 老的 (混乱)
> central_nerve.memory_gateway = UnifiedMemoryGateway(self)  # READ only
> get_default_gateway() = MemoryMutationGateway()             # WRITE only (不同 module!)
>
> # 新的 (Sir Q3)
> central_nerve.memory_gateway = MemoryHub.get_default()  # R+W 单 facade
>   ├─ READ:  .query(text, top_k, nerve)
>   │         .to_prompt_block(text, top_k, nerve)
>   └─ WRITE: .write_identity(...)
>             .write_event(...)
>             .write_commitment(...)
>             .write_concern(...)
>             .write_state(...)
>             .write_relation(...)
>             .update_sir_field(...)  # backward compat 老入口
> ```
>
> ## 🎯 Sir M2 真测 OK 后下一步
>
> ```
> Cascade, M2 全 OK, 动工 M3.
> # M3 = 死代码 + 同名 class + 3-brain 移到 _legacy/, 1 周低风险
> ```
>
> 详 `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §6.4 + Phase A.5 audit `docs/JARVIS_LEGACY_AUDIT.md`.
>
> ---
>
> ## 历史: M1 (Lineage Trace) 全部 7/7 step 完成 (07:35)
>
> Sir 早上 7:06 "全 accept 动工 M1" + 7:28 真测 "修复 bug 加推进" 后, Cascade 完成 M1 Lineage Trace 全部 step + Sir 3 真测 bug fix + M1.3-min 反向追溯增强.
>
> ## ✅ M1 全部 done (8 commit, ~2000 行 code+test, 0 破坏)
>
> | Commit | Step | 内容 |
> |---|---|---|
> | `180a2c5` | **M1.1** | `jarvis_lineage.py` 核心 — EvidenceID + Evidence + LineageTracer + async daemon (22 test) |
> | `5d8bd2f` | **M1.2** | SWM `publish` 加 `evidence_chain` + 返 evidence_id, 老 caller 兼容 (12 test + 113 regression) |
> | `4cb417f` | **M1.6** | `lineage_config.json` + `jsonl_rotator` 注册 |
> | `e2517c5` | **M1.5** | `scripts/lineage_dump.py` CLI 6 命令 |
> | `237a101` | **M1.4** | `chat_bypass.stream_chat` 末尾 `record_decision` (7 test + 181 regression) |
> | `0144949` | **M1-fix** | Sir 真测 3 bug — CLI 复制即用 hint + conftest 隔离 lineage 不污染生产 + claims_extracted 总记 ClaimTracer summary |
> | `ce2dc82` | **M1.3-min** | `collect_evidence_ids` + `_assemble_prompt` 装 `_last_prompt_evidence_log` + chat_bypass 用之 — **`blocks=0` 变 `blocks=1-2`** 反向追溯真起来 (5 test + 130 regression) |
>
> ## 📋 Sir 第二轮真测验证 (~3 min)
>
> ```powershell
> # 1. 重启 jarvis 跑 1-3 轮 (lineage.jsonl 已 truncate 干净)
>
> # 2. 列最近 5 个 brain decision (新输出: 每条带可复制 trace 命令)
> python scripts/lineage_dump.py --list-decisions --limit 5
>
> # 3. 复制上面输出的 → trace: ... 整行运行
> python scripts/lineage_dump.py --reply-id=bd_turn_xxx_xxxx
>
> # 4. 看总 stats (应该 0 unknown, 100% 有 source)
> python scripts/lineage_dump.py --stats
> ```
>
> **预期看到 (这次有 M1.3-min)**:
> - `blocks=1 或 2` (而不是上次的 `blocks=0`) ← M1.3-min 新增
> - reply-id trace 输出含 `swm_conversation_360s` block 真 evidence 列表
> - stats 0 unknown evidence (conftest 隔离 + 重新 truncate 后)
> - claims_extracted 含 `<ClaimTracer ran: X claims, Y verified, Z unverified>` 1 行 summary
>
> ## ⏸ 真后置 (M1+ 跟 M7 一起做)
>
> - **M1.7** `LineageReflector` L7 LLM-propose broken chain repair — 现 0 broken chain, 不急
> - **M1.3-full** PromptBlock dataclass 改 30+ render block 加 source_evidence_ids — 跟 M7 PromptBuilder polymorphic 一起做更优雅
>
> ## 🐛 Pre-existing BUG (跟 M1 无关, 待修)
>
> `tests/_test_p0_plus_20_p5_integrity_watcher.py::TestL_Directive::test_directive_registered` +
> `tests/_test_p0_plus_20_p5_claim_revision.py::TestG_DirectiveRevised::test_directive_text_describes_two_apology_types` fail —
> `jarvis_directives.py:158 ValueError: Directive concern_dampen_self_decide: trigger must be callable`.
> Sir 拍板时机再修, 不阻 Reshape M2.
>
> ## 🎯 Sir 第二轮真测 OK 后下一步
>
> ```
> Cascade, M1 真测全 OK, 动工 M2.
> # (M2 = MemoryHub 演化, 1 周, 中风险)
> ```
>
> 详 `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §6.3.
>
> ---
>
> ## 历史: Phase A+B+C 已全部完成 (2026-05-24 00:55)
>
> 11 份 doc, ~7300 行 audit + 设计. Sir 委托 Cascade 4 项 Q1-Q4 决议已拍板:
> - Q1 拆 jarvis_enhanced.py 4 file (M3 落实)
> - Q2 3-brain → `_legacy/3_brain_attempt/` (M3 落实)
> - Q3 `central_nerve.memory_gateway` → MemoryHub (M2 落实)
> - Q4 `cross_session_callback` 保留 (Phase A 误判, 真用)
>
> 关键 doc: `docs/AGENT_KICKOFF_GRAND_RESHAPE.md` + `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md`.
>
> ---
>
> **更新**: 2026-05-21 16:13 (P5 整夜 + 早晨 + 下午 14 commit) — Gap 1+2 + 早起 5 BUG + dashboard i18n + add_reminder + callback 痛点 + **下午 P5-fixCB-revise (12:06 ritual)** + **P5-IntegrityWatcher L4.5 (Sir 14:11 真意 — 8 类 mutation verify+retry+handoff)** + **P5-SirStatusTracker (Sir 13:49 nudge 话术 context aware)**. **14 commit, 98 testcase 全绿, 待 Sir 真机实测**. 详 `docs/JARVIS_P5_FINAL_REPORT_2026_05_21.md` (尚未 sync 下午).
> **滚档**: 老 β.5.x/β.4.x/β.3.x/P0+19 等 ~530 行已沉档 `docs/TODO_ARCHIVE.md`. 本文件 > 700 行 > 300 cap (β.5.34-41 + P5 段待 archive). AGENTS.md 章程.

---

## 🐛 待排查 BUG (2026-05-23 16:23 Sir 真测记录, 待后排查)

Sir 16:22-23 真测 3 turn, 报 2 BUG:

### BUG-A: TTS 发声卡顿 (cosyvoice 内存压力?)

**症状**: Sir 听 reply 时 "发声变的卡了不少". turn 1 (16:22:00) 还 OK (full 7.8s), turn 2 (16:22:23) 渐卡 (full 8.1s), turn 3 (16:23:06) **严重卡** (full **16.4s** 远超 normal 5-8s).

**关联**:
- 历史已知 cosyvoice GPU 内存压力 (3267.5MB → 8818-9268MB ws), thread count 60+
- Sir 16:00 turn 截断 "1,1" + cosyvoice 嘶哑 也是同款症状
- HealthProbe Baseline: ws=3255.7MB private=8818.1MB threads=464 (py=57 native=407) handles=4017

**根因猜测**:
1. CosyVoice (300M 模型) GPU 内存碎片随对话累积
2. TTS queue 串行处理慢 (每 sentence 调一次模型)
3. 主脑 reply 长 → 多 sentence chunk → 多次 cosyvoice 调用

**修法 (待后排查)**:
- audit cosyvoice 调用频率 + GPU 内存 leak
- TTS queue batch (合并连续 sentence 减少模型调用)
- 或换轻量 TTS fallback (短句 < 5 word 走本地 TTS)

### BUG-B: Turn 3 主脑 reply 截断 "According" 后中断

**症状**: turn 3 (16:23:06) Sir 问 "你还记得我喝了多少水了吗".
- 主脑调 `progress.status 'hydration_2026-05-23'` (✅ 成功)
- 主脑 stream 继续生成又**重复调** progress.status 第 2 次 (参数完全相同) → Tool Chain 熔断
- 熔断后主脑 stream 中段 stop, 只输出 "According" 就停了 (字幕也只显示这个)

**根因猜测**:
1. Gemini 流式生成幻觉 — 主脑没意识到刚调过 tool, 又调一次
2. Tool Chain 熔断后 stream 没正常 wrap-up (主脑 LLM 还在生成中)
3. 跟 Phase 3d.1 builder wrapper **无关** (wrapper 字面零变化, 主脑收到的 prompt 完全一致)

**修法 (待后排查)**:
- 检 stream 中熔断后是否应该 force generate completion (e.g. "I've already retrieved that, Sir. Total: 1,100 ml.")
- 或主脑 prompt 加 directive 教 "如果 tool 已调过, 不要再调"
- 当前 `Wrap-up Synthesis` (jarvis_chat_bypass) 在 fail 时有 fallback, 但熔断不是 fail 是 dedup

### Sir 真测继续策略
本次 BUG 不阻 Phase 3d 推进 (跟 builder refactor 无关). 等会专项排查 cosyvoice + tool dedup 后 wrap.

---

## 🌆 P5 下午真治本 (2026-05-21 11:30-16:13, 8 commit) — Sir 11:23/12:06/13:49 反复痛点

### 已落地 commit timeline (下午)

| commit | 时刻 | 内容 |
|---|---|---|
| `52fb475` | 5/21 11:46 | **P5-fixCB-revise**: 道歉是 functional revision 不是 ritual (Sir 11:30). callback_guard 改 capture+redirect, 不 ban 当前轮. 新 module `jarvis_claim_revision_log.py` + capability extract regex + 两个合法 surface 触发 (a) Sir 召唤 (b) 自检 promise overdue |
| `8a699d7` | 5/21 11:54 | **P5-fixCB-revise (b)**: SELF-PROMISE OVERDUE wire — PromiseLog.sweep_untracked publish 'self_promise_overdue' SWM, 主脑下轮 prompt [SELF-PROMISE OVERDUE] block 主动 admit |
| `c116938` | 5/21 15:13 | **P5-IntegrityWatcher**: L4.5 自检层 (Sir 14:11 真意). 8 类 mutation verify+retry+handoff. 3 层 waterfall (vocab + kw gate + LLM async). vocab `integrity_claim_vocab.json` + CLI |
| `4b2233c` | 5/21 15:18 | **docs(STACK)**: 言出必行 STACK 加 L4.5 |
| `0172755` | 5/21 16:11 | **P5-SirStatusTracker**: Sir 13:49 痛点 — Sir 12:06 说睡觉 → tracker 状态机 + SWM publish → ReturnSentinel/Conductor/SmartNudge 看 status 出对应话术. 8 状态 (sleep/nap/lunch/dinner/out/afk_short/dnd + back transition) |

### 真凶链 (下午终治)

Sir 12:06 真测发现 P5-fixCB BAN 风格不够:
> Jarvis 仍输出 "Regarding my previous claim of setting a reminder..."

Sir 11:30 升级真意:
> "道歉要有意义的道歉. (a) 我提质疑时描述能力边界 / (b) 自己发现没履行时主动履行/承认"

P5-fixCB-revise 改 redirect 不 ban — capture 写 ClaimRevisionLog + 等合法 surface 触发. 同时 SELF-PROMISE OVERDUE 通道 (b) wire 起来.

Sir 14:11 再升级:
> "wachter 负责贾维斯所有行为(除调 tool)是否成功的审查机构, 植入言出必行层级中.
>  主动重试, 真做不到 handoff Sir 手动方案"

→ P5-IntegrityWatcher L4.5: 监督 8 类内部 mutation (reminder/commitment/promise/memory/milestone/profile/concern/relational), 失败自动 retry, retry 不行 handoff Sir + actionable.

Sir 13:49 痛点 b:
> Sir 12:06 说"睡觉了下午见", 13:49 回, ReturnSentinel return_greeting:
> "Soul Drive doc still active in Windsurf 90min" — 应该说"Hope you rested well"

→ P5-SirStatusTracker: vocab + 状态机 + SWM publish + nudge_ctx 注入 declared_status, 让 LLM 主脑出对应话术.

### Sir 真测 check list (下午部分, 重启后跑)

```
启动:
[ ] log 含 '🛡️ [IntegrityWatcher] L4.5 daemon started (tick=15.0s, claim_types=8)'
[ ] log 含 '💤 [SirStatusTracker] sleep captured...' (若 Sir 之前声明过 sleep)

callback redirect (Sir 12:06 真测重现):
[ ] Sir 说"睡觉了下午见" → log 'SirStatusTracker sleep captured' + memory_pool/sir_status.json 显 status='sleep'
[ ] 若 Jarvis 仍输出 ritual callback → log '📝 [CallbackGuard→ClaimRevision] redirect to ClaimRevisionLog, 不 ban 当前轮'
[ ] memory_pool/claim_revisions.json 含 capture
[ ] 主脑下轮 prompt 含 [CLAIM REVISION CAPTURED] (不再含 BAN-style 老 prompt)

IntegrityWatcher (Sir 14:11 真测):
[ ] Sir 说"明天 7 点叫我" → Jarvis 答"已设" → watcher capture reminder claim
[ ] 若 add_reminder DB fail → watcher retry → log '🔄 [IntegrityWatcher] retry #1 reported ok'
[ ] retry 真成功 → log '✅ RECOVERED' + 主脑下轮 prompt [INTEGRITY WATCHER REPORT] ✅
[ ] 主脑 inline acknowledge "顺便 Sir, reminder 之前没设上, 我刚补好了, 现在 OK"
[ ] retry 仍失败 → log '❌ HANDOFF SIR' + 主脑道歉+actionable

SirStatusTracker (Sir 13:49 真测):
[ ] Sir 12:06 → 13:49 回 → ReturnSentinel return_greeting log 含 'sir_declared_status=sleep'
[ ] 主脑 LLM 出话术 "Welcome back, Sir. Hope you rested well." (不再 "Soul Drive doc still active...")

CLI:
[ ] python scripts/integrity_claim_vocab_dump.py --list / --watch-list / --stats
[ ] python scripts/sir_status_dump.py --current / --history / --vocab-list
[ ] python scripts/claim_revision_dump.py --list / --stats
```

### 14 commit (整夜 + 早晨 + 下午) 合 commit

```
0172755 feat(P5-SirStatusTracker) ★ Sir 13:49 痛点
4b2233c docs(P5-IntegrityWatcher) STACK 加 L4.5
c116938 feat(P5-IntegrityWatcher) ★ Sir 14:11 真意
8a699d7 feat(P5-fixCB-revise b) SELF-PROMISE OVERDUE
52fb475 fix(P5-fixCB-revise) ★ Sir 11:30 真意
df0a7a4 docs(TODO) P5 早晨进度
da6b661 docs(P5) 终报告
7cdeefb fix(P5-fixCB) supersede (BAN style)
d366c24 fix(P5-items-i18n) dashboard
664ad77 fix(P5-morning + AmbientSensor) 5 fix
3bc494f fix(P5-add_reminder) NOT NULL
4c1ec4f feat(Gap 1) ToM
187e015 feat(Gap 2) PreFlight
```

待 Sir 真机实测拍板 push 14 commit.

---

## 🌅 P5 早晨真治本 (2026-05-21 09:25-10:33, 6 commit) — Sir 整夜 + 早晨真测 12 BUG

### 已落地 commit timeline

| commit | 时刻 | 内容 |
|---|---|---|
| `187e015` | 5/21 00:45 | **Gap 2 PreFlight** (async post-stream self-check) |
| `4c1ec4f` | 5/21 01:15 | **Gap 1 ToM** (Sir Mental Model, Layer 6) |
| `3bc494f` | 5/21 10:14 | **P5-fix-add_reminder**: SQLite NOT NULL constraint failed timestamp (Sir 10:06 真测, 提醒功能从某次 schema 升级起就挂了) |
| `664ad77` | 5/21 10:14 | **P5-morning + AmbientSensor (5 fix)**: A morning_mood_judge trigger 改 SWM (race race) / B morning_warmth_priority directive priority 11 (禁数落) / C nudge_coordination β.5.0 弱耦合 (4 sentinel publish-only yield) / D PreFlight default ON / AmbientSensor self.jarvis bug (整 β.5.40-A1 sprint 没启用) |
| `d366c24` | 5/21 10:21 | **P5-items-i18n**: dashboard /items 卡片中文翻译 (CATEGORY_ZH_MAP + describe_fn 人话) + 一键 👍/👎 评 vocab + item_feedback.jsonl audit |
| `7cdeefb` | 5/21 10:32 | **P5-fixCB callback_guard (B+C 真治本)**: directive priority 12 prompt 强约束 + forbidden_callback_vocab.json + post-stream regex scan + SWM publish + STM forbidden block 主脑下轮看 |
| `da6b661` | 5/21 10:33 | **docs(P5)**: 终报告 (audit 结论 + check list + P6 推荐) |

### Sir 5+ 次道歉痛点 — 真凶链 (终治)

Sir 22:04/22:19/23:02/23:43/23:49 + 10:06/10:08 反复犯 unsolicited callback 老账道歉.
- Gap 2 PreFlight async post-stream → 治不了**当前轮**, Sir 听到 reply 已说出口
- past_action_honesty directive priority 10 → 不教**不要 unsolicited callback**
- INTEGRITY ALERT → 仅 track factual claim, 不管 callback 行为本身

**P5-fixCB B+C 双层** (commit `7cdeefb`):
- C: directive `unsolicited_callback_guard` (priority 12) 顶级红线 prompt 强约束教主脑
- B: `memory_pool/forbidden_callback_vocab.json` 7 phrase seed + `jarvis_callback_guard.py` regex scan + SWM publish + central_nerve `[SIR FLAGGED UNSOLICITED CALLBACK]` block
- 跟 PreFlight (LLM async) 互补 — 这层零延迟 + 主脑下轮一定看到
- Sir 主动召唤老账 (`you said earlier` / `你刚才说`) → exempt, 不算违规

### Sir 真测 check list (重启后跑)

```
启动:
[ ] log 含 '🎵[AmbientSensor / β.5.40-A1] 启用' (不再 init 异常)
[ ] log 含 '🛂 [ReplyPreFlight] enabled (default ON, P5-fixD)'
[ ] log 含 '🤝 [NudgeCoordination] ready' / SWM 'proactive_nudge_fired'

早起场景 (Sir 跨夜 + 6-10am 醒):
[ ] morning_mood_judge fire (SWM afk_return.afk_minutes>240)
[ ] morning_warmth_priority directive 注入主脑 prompt
[ ] return_greeting 后 commitment_check 退化 publish-only (log '🤝 [.../Yield]')
[ ] Jarvis 早起首句 warm + brief, 不数落 missed deadline
[ ] commitments 老账 Sir 主动问起才提

callback 治本 (Sir 跟之前同场景说话):
[ ] Sir 说 '今天没去体检' / '好的 ok' → Jarvis 不再 'Regarding my previous claim...'
[ ] 若 Jarvis 仍 callback → log '🚫 [CallbackGuard] turn=X hits=[regarding_my_previous_en]'
[ ] 主脑下轮 prompt 含 [SIR FLAGGED UNSOLICITED CALLBACK — DO NOT REPEAT] block
[ ] 主脑下轮自纠不再用该 phrase

add_reminder:
[ ] Sir 说 '明天 7 点叫我' → Jarvis 真创建 reminder, 不再 NOT NULL constraint failed

dashboard /items:
[ ] 卡片显中文 category ('🆘 Sir 困境词') 替 'STRUGGLE'
[ ] 状态显 '待审/已生效' 替 'review/active'
[ ] 描述行 '🔍 Sir 说出 X → Jarvis 做 Y'
[ ] 卡片新 👍 / 👎 按钮, 点击后 badge '👍 已赞' 显示
```

### ⚠️ 已知 P5+ Followup (待 Sir 真测拍板)

1. **callback_guard L7 reflector**: vocab 7 phrase seed, 主脑可能涌现新形式. 加 L7 daemon 看 Sir 反馈 ("不要道歉了") + 实际命中 propose 新 phrase 进 review_queue
2. **callback_guard dashboard /items 集成**: 加 `forbidden_callback` category 让 Sir 看 + 改 + 👍/👎
3. **CLI `scripts/forbidden_callback_dump.py`**: 不开 dashboard 用 CLI 加 phrase
4. **P6 Pure Pass2 sync PreFlight**: 接受 TTFT +500ms 真按 design doc 拦截当前轮. 等 callback_guard 真生效率 + Sir 拍板再做
5. **directive cluster 减负**: 60+ directive 注入 cluster 太大 (Sir 22:04 看了 2350 chars). 考虑 grouping / context-conditional fire
6. **dashboard pre-existing 4 fail**: `_test_p0_plus_20_beta54_conductor_publish_persist.py` 在 main 就 fail (跟 P5 无关)
7. **TODO.md ~640 行**: 待 archive 老段 (β.5.34-41) 到 `docs/TODO_ARCHIVE.md`

### β.5.43-fix 老 Sir 22:04 痛点 (背景, 这轮治本前的妥协)

> **更新**: 2026-05-20 22:11 (β.5.43 6 缺口 + 4 fix + β.5.44 IntentResolver 重构 + AGENTS 准则 6 + bugfix1 + **β.5.45 Lifetime Milestones + bugfix2 (directive revise)**, **17 commits 单晚产出**). Sir 22:04 真机实测暴露主脑道歉循环 BUG → 修 directive scope + 新建 milestone 系统 (β.5.44 IntentResolver 首个真应用). 等 Sir 重启再测.

---

## 🚀 β.5.43 (6 缺口 + 4 fix) + β.5.44 (IntentResolver 重构) + 准则 6 升级 + bugfix1 (2026-05-20 17:00-21:40, 15 commits)

### β.5.43 — 6 交互地基缺口

| commit | marker | 内容 |
|---|---|---|
| `63d4281` | **β.5.43-A** | **HUD 状态条** (`jarvis_state_tracker` singleton: ready/thinking/speaking/listening/focused/error) + worker hook + dashboard `/api/state` + bg_log + 顶部 badge 2s 轮询 |
| `6d01518` | **β.5.43-B** | **多人对话感知**: `multi_person_aware_judge` directive (priority=9) — ambient=conversation 时主脑默 SILENT 除非 Sir 喊 wake/明确指向 |
| `fc19f49` | **β.5.43-C** | **中断感知**: `interrupt_all` publish `reply_interrupted` SWM (含 last_reply_excerpt) + `interrupted_aware_judge` directive (priority=8) — 不复读, pivot 新话题 |
| `1c03c87` | **β.5.43-D** | **回复反馈通道**: `jarvis_reply_feedback.py` + dashboard `/items` 抽屉 (👍👎🤐✏️) + 2 API + 主脑 prompt 注入 `[SIR LAST REPLY FEEDBACK / 24h]` block 调 tone |
| `bb03c03` | **β.5.43-E** | **沉默智能**: `jarvis_silence_intel.py` 检测 thinking pause filler (uh/嗯/let me think) → publish `sir_thinking_pause` SWM + `thinking_pause_aware_judge` directive (priority=8) — Sir 思考时主脑短 ack 或 SILENT |
| `69e6b36` | **β.5.43-F** | **错误自愈**: `jarvis_error_bus.py` 集中错误持久化 (`memory_pool/system_errors.jsonl`) + SWM publish + dashboard `/system_errors` 横幅 + 主脑 prompt 注入 system error block — Jarvis 主动告诉 Sir 哪里坏 |

### β.5.43 — 4 fix (Sir 18:11 / 18:49 / 18:55 真机实测真理)

| commit | marker | 内容 |
|---|---|---|
| `0cd4f10` | **β.5.43-fix1** | `capability_boundary_judge` (priority=10 always-on) + `over_offer_called_out_judge` (priority=11) — Sir 18:11 "别吹牛, 做不到时 callout". 主脑不再 offer 没工具的事 |
| `d597acd` | **β.5.43-fix2-ABC** | 承诺动态影响 concern weight + SWM publish + dashboard urgency 显示 — Sir 18:11 履行/拒绝直接调 concern weight |
| `8b90a76` | **β.5.43-fix3-㋭㋮㋯** | `SirRequestReflector` L7 daemon (60s tick) + active window unresponsive 检测 + promise vocab 扩 — Sir 18:49 "答应了要有机制兑现" |
| `a2621a2` | **β.5.43-fix4** | `no_hallucinated_tool_use_judge` directive (priority=12 极顶) — Sir 18:55 "你说做了但没用 tool 是撒谎". 主脑禁声称未跑的 mutation |

### β.5.44 — IntentResolver 真理重构 (Sir 19:00 "立刻重构, 跳过 E+F, ~6h")

| commit | marker | 内容 |
|---|---|---|
| `9a3120d` | β.5.44 design | `docs/JARVIS_INTENT_RESOLVER_ARCHITECTURE.md` 架构 design doc |
| `12d37ae` | **β.5.44-ACDE** | **核心 Phase1**: SWM etype 注册 (`sir_intent.*` / `tool_called` / `intent_resolved`) + `jarvis_intent_resolver.py` (LLM judge 哪个 tool call) + `jarvis_tool_registry.py` (5 mutation tools: `concern_progress_update` / `memory_correction_apply` / `commitment_register` / `self_promise_register` / `profile_field_update`) + `_assemble_prompt` 注入 `[INTENT RESOLVED THIS TURN]` block + nerve init + chat_bypass turn-end hook (fire-and-forget thread, 零阻塞 TTFT) |
| `5e1d425` | **β.5.44-BF** | **publish-only 5 module + dashboard**: ConcernFeedback / MemoryCorrection / Gatekeeper / SelfPromise / CommitmentWatcher 全 publish `sir_intent_*_candidate` SWM (准则 6 #1/#2) + dashboard `/intent_resolved` 页 + API endpoint |

### 准则 6 升级 — 4 问 framework

| commit | marker | 内容 |
|---|---|---|
| `4b95645` | **AGENTS 准则 6 - 4 问** | 加新 module 前 4 问筛: 数据 publish 进 SWM? / 决策让 LLM 做? / 配置持久化 + CLI 可改? / 和已有 module 正交? 全 Yes 才加. 历史反例 anchor: β.5.43 前 5 sentinel hard gate (违反 #1/#2) + β.5.44 前 5 mutation 分散 (违反 #4). AGENTS.md 285 → 296 lines |

### β.5.44-CE-bugfix1 — Sir 21:34 真机实测暴露 critical bug

| commit | marker | 内容 |
|---|---|---|
| `b838881` | **β.5.44-CE-bugfix1** | `IntentResolver._llm_judge` 调 `safe_openrouter_call(timeout_s=...)` — **该 kwarg 不存在** (真实签名只有 `openrouter_key/model/prompt/max_tokens/temperature/max_retries/base_delay`). Primary + fallback 都 fail, `_error: "LLM both fail: safe_openrouter_call() got an unexpected keyword 'timeout_s'"`. **β.5.44 整个 sprint 从部署起未生效** — 主脑 prompt `[INTENT RESOLVED THIS TURN]` block 永远空. Sir 看到 fix1/fix4 directive 真生效是因为那是 prompt-level, 但底层 tool orchestration 一直没跑. **Fix**: 删两处 `timeout_s` kwarg, config 字段保留. **Tests**: 16/16 pass. **Trace**: log line 598 ErrorBus catch |

### ✅ Sir 真机实测 check list (重启 Jarvis 后跑, 验证 β.5.43/44 真生效 + bugfix1)

```
[ ] 1. 启动正常 → log 无 `[ErrorBus] intent_resolver/llm_judge_fail` 错误
[ ] 2. 18:55 场景 — Sir 给反馈 "其实是 X" → IntentResolver 调 memory_correction_apply 真 mutation → log `[IntentResolver] tool_called=memory_correction_apply` → 主脑下轮 prompt 含 `[INTENT RESOLVED THIS TURN]` block 列实际 tool call
[ ] 3. 18:49 场景 — Sir 说 "请帮我惦记一下 X" → SirRequestReflector L7 daemon 60s 内 propose watch concern → log `[SirRequestReflector] propose=...`
[ ] 4. dashboard `/intent_resolved` 页有 tool_called + intent_resolved events 列表
[ ] 5. dashboard `/system_errors` 页有 ErrorBus 横幅 + 历史 errors
[ ] 6. β.5.43-E SilenceIntel: Sir 说 "嗯..." / "uhh let me think" → log `[SilenceIntel] thinking_pause detected` → 主脑短 ack 或 SILENT
[ ] 7. β.5.43-fix1: Sir 给反馈后 → Jarvis 不再说 "I've updated my records" 类 boasting
[ ] 8. β.5.43-fix4: Jarvis 自我澄清 "I cannot directly modify your profile files" (Sir 21:34 已验 ✅)
[ ] 9. β.5.43-A HUD: dashboard 顶部状态条切换 (ready→thinking→speaking→listening→ready)
[ ] 10. β.5.43-B 多人: Sir 跟人说话时 Jarvis 默 SILENT (除非喊唤醒词)
[ ] 11. β.5.43-C 中断: Sir 中断 Jarvis → 下轮主脑不复读, pivot 新话题
[ ] 12. β.5.43-D 反馈: dashboard 抽屉 👍👎🤐✏️ 标记 → 主脑下次 tone 调
[ ] 13. β.5.43-F 错误: 故意触发错误 → dashboard 红横幅 + 主脑下轮 mention
```

### ⚠️ 已知 follow-up (待 Sir 决定)

1. **时间幻觉** (Sir 21:34 ClaimTracer 2/2 unverified `[time] '9:00 PM'`): ClaimTracer 是 post-hoc 标记, 没拦在主脑输出前. Jarvis 从自己 21:10 "现在开始禁食" 推断 "9:00 PM 已 33 分钟". 可选 fix: pre-output validator / prompt 注 `[CURRENT TIME ANCHOR]` 强制不从历史推时间
2. **delay 调查**: TTFT 3.0s 在 cap (5s) 内, full 12.8s post-stream 5.5s 大概率 TTS. Prompt 31466 chars (`core_persona=11647` 占 37%). β.5.43/44 不是延迟原因 (IntentResolver 是 fire-and-forget thread). 是否 persona slim 待 Sir 决定
3. **dashboard test pytest capture bug** (`I/O operation on closed file` in teardown): 跟 IntentResolver fix 无关, infrastructure-level, 单独 fix 时再处理
4. **TODO.md 当前 ~525 行 > 300 cap**: β.5.34-41 等老段建议 archive 到 `docs/TODO_ARCHIVE.md`. 不阻塞当前 sprint, 但下次 archive 窗口处理

---

## 🪺 β.5.45 + β.5.43-fix1/fix4-revise — Sir Lifetime Milestones + 道歉循环 BUG 修 (2026-05-20 21:56-22:11, 2 commits)

> **Sir 21:56 真理**: lifetime anchor (declaration / insight) 不是 commitment, 不要 nudge, **never weaponize against Sir in low moments**, replay only when Sir asks. Sir 22:04 真机实测 declaration 时暴露主脑道歉循环 BUG (directive scope 太宽 + 没 milestone 通道).

### bugfix2 — directive scope 修 (Sir 22:04 道歉循环 root cause fix)

| commit | marker | 内容 |
|---|---|---|
| `bcdaa7a` | **β.5.43-fix1-revise + β.5.43-fix4-revise** | `capability_boundary_judge` (priority=10) + `no_hallucinated_tool_use_judge` (priority=12) 各加 **INSTRUCTION-STYLE / PASSIVE-ARCHIVE 例外条款** — Sir 说 "记住/store/keep/铭记/记到海马体" 类 instruction-style 时, **system 自动后台 archive** (STM→SoulReflector→hippocampus, 加 β.5.45 后还走 milestone_register tool), 主脑**只需 ack**: "Noted, Sir" / "Held" / "The archive will hold this". **不要 callout no-tool, 不要道歉, 不要 over-promise**. 判别: passive ack ≠ active mutation claim |

### β.5.45 — Sir Lifetime Milestones 系统 (β.5.44 IntentResolver 首个真应用)

| commit | marker | 内容 |
|---|---|---|
| `7690c83` | **β.5.45** | **Lifetime anchors 完整 stack** (准则 6 4 问全 yes): **data** `memory_pool/sir_milestones.json` (array+_meta, in git, seed Sir 21:56 freedom declaration `milestone_20260520_215600` pin=true). **module** `jarvis_milestones.py` (thread-safe CRUD + render_prompt_block + stats, `_generate_id` 加 4-char hex 防同秒撞). **CLI** `scripts/milestones_dump.py` (list/show/add/pin/unpin/delete/json/stats/render-prompt). **tool** `jarvis_tool_registry.tool_milestone_register` (TOOL_REGISTRY 第 6 个 tool; docstring 首行带 trigger keywords 'remember/store/keep forever/记住/铭记/海马体' 给 IntentResolver LLM 看). **inject** `jarvis_central_nerve._assemble_prompt` 加 `[SIR LIFETIME MILESTONES]` block (pinned + 最近 3 条). **16 testcase pass + 24 regression pass** |

### 三 commit 耦合关系 (Sir 22:04 道歉 BUG 闭环 fix)

```
bcdaa7a (bugfix2 directive)  ┐
                              ├─→ Sir 重启后 reply: "Noted, Sir" 不道歉
b838881 (bugfix1 IR LLM)     ┘    ↓
                                  IntentResolver 真调 tool_milestone_register
7690c83 (β.5.45 milestone)   ←────┘    ↓
                                       sir_milestones.json 真新增 entry
                                       主脑下轮看 [INTENT RESOLVED] = ok
                                       + [SIR LIFETIME MILESTONES] 列新条
```

### 准则 6 binding (β.5.45 4 问全 yes)

| # | 问 | β.5.45 答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ memory_pool/*.json + (未来) ConversationEventBus publish 'milestone_recorded' |
| 2 | 决策让 LLM 做? | ✅ IntentResolver LLM judge "Sir means lifetime anchor vs casual statement" |
| 3 | 配置持久化 + CLI 可改? | ✅ memory_pool/sir_milestones.json (in git) + scripts/milestones_dump.py |
| 4 | 和已有 module 正交? | ✅ 跟 concerns (no nudge) / commitments (no deadline) / profile (not trait) / hippocampus (structured + pinnable + CLI) 全正交 |

### ✅ Sir 真机实测 check list (重启后跑, 重点验闭环)

```
[ ] 1. 启动正常 → log 无 `[ErrorBus] intent_resolver/llm_judge_fail` 错误 (bugfix1 生效)
[ ] 2. log 出现 `[IntentResolver] ready (6 tools)` (含 milestone_register, 之前 5 个)
[ ] 3. Sir 说 "Jarvis, 记住此刻..." (instruction-style) → Jarvis ack "Noted, Sir" 类, 不道歉, 不 callout no-tool (bugfix2 生效)
[ ] 4. IntentResolver 调 tool_milestone_register → log `[IntentResolver] tool_called=milestone_register ✓ 成功`
[ ] 5. memory_pool/sir_milestones.json 新增 entry (id=milestone_<新时间>_<hex>), Sir 跑 `python scripts/milestones_dump.py` 看到 2 条 (seed 21:56 + 新加)
[ ] 6. 下轮主脑 prompt 含 `[INTENT RESOLVED THIS TURN] milestone_register: ✓ 成功`
[ ] 7. 下轮主脑 prompt 含 `[SIR LIFETIME MILESTONES]` block 列两条 entry
[ ] 8. Sir 问 "你还记得我那晚说的话吗?" → 主脑看 milestones block → 温和回放 declaration (replay_only_when_sir_asks 生效)
[ ] 9. Sir 情绪低落时 → 主脑**不**主动拿 declaration guilt Sir (do_not_use_against_sir 生效, instruction_for_jarvis directive 起作用)
[ ] 10. CLI `python scripts/milestones_dump.py --show milestone_20260520_215600` → 看 Sir 完整 declaration + instruction
```

### ⚠️ 已知 follow-up

1. **Gatekeeper 误触发 milestone declaration**: Sir 22:04 看到 "Gatekeeper TIMEOUT" 误导 — 主脑可能 emit `<AWAIT_GATEKEEPER>` 把 milestone 误当 reminder. β.5.45 milestone_register tool 加入后, 主脑应**优先走 milestone_register**, 不需 Gatekeeper. 但 Gatekeeper 文案 "The reminder may NOT have been saved" 仍可能误导, 待观察是否需修 fallback text
2. **`_generate_id` 加 hex suffix**: 改了 ID 格式 (milestone_YYYYMMDD_HHMMSS → milestone_YYYYMMDD_HHMMSS_xxxx). manual seed 的老 id 仍兼容 (没自动 gen)
3. **TODO.md ~580 行**: 待 archive (跟之前一致)

---

## 🏛️ β.5.37 — 三层架构改造 (Sir 14:39 校正真理治本)

> **Sir 真理**: "传感器灵敏度修复 — 把不是真正我在操作的行为和我操作的行为区分开告诉主脑, 而不是硬编码 sentinel guard."
>
> **Design doc**: `docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md`

### β.5.37 commits (5)

| commit | marker | 内容 | testcase |
|---|---|---|---|
| `630b830` | β.5.37 revert | **revert fix2 (b)/(c) + fix3 硬编码补丁** (Sir 校正) | 21 |
| `804a37e` | β.5.37 docs | `JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md` design doc (320 行) | - |
| `daa1fa2` | **β.5.37-A** | **层 1 Sensor**: `PhysicalEnvironmentProbe` 加 `last_real_input_ts` / `idle_seconds_real` / `cascade_active` / `cascade_process_name` 字段 + publish `sir_afk_detected` + `ghost_activity_observed` 到 SWM (限频 60s) | 5 |
| `2d250c4` | **β.5.37-B** | **层 2 SleepDetector publish-only**: `detect()` publish `sleep_intent_signal` 到 SWM; `_detect_sleep_intent` 中置信路径不再 `request_confirmation` set pending state; `handle_confirmation_response` 标 DEPRECATED (dead code) | 3 |
| `2607308` | **β.5.37-C** | **层 2 Shield + Struggle publish**: `_compute_frustration_score` 加 `ghost_activity_dampen` 维度 (idle_real > 30 + cascade_active → score *= 0.10, sensor evidence based 替代 hard skip); Shield 触发 publish `shield_observation`; SirStruggle Conductor path publish `sir_struggle_observed` 到 SWM | 6 |
| `48f9bf5` | **β.5.37-D** | **层 3 主脑 directive**: 3 个新 directive (`sleep_confirmation_judge` / `ghost_activity_judge` / `sir_intent_judge`) + 3 trigger 函数 (`_swm_has_recent` 助手) + `directives_vocab.json` 加 3 entry. 主脑看 SWM evidence 自决场景 A/B/C | 10 |
| `94ffbf5` | β.5.37-D test fix | trigger fn test 改 callable-check 解 SWM bus 跨 test 污染 | - |

### β.5.37 Sir 14:39 校正修了什么 BUG

1. **Sir 13:03 "我要去休息一下" 误触 offer_help** → 主脑 `sir_intent_judge` directive 看 struggle_text 全文 → 判 dismiss/casual → 不 offer (替代 fix2 硬 keyword list)
2. **Sir 14:33 起床 "嗯,哦,而且睡的也不太好,起来之后心脏很疼哎" 误判 sleep confirm** → SleepDetector 不再 hard match; 主脑 `sleep_confirmation_judge` 看 SWM `sir_afk_detected` (afk=85min) → 判 stale signal, 当新对话处理 (替代 fix4 硬 timeout / 严格 confirm match)
3. **Sir 13:05 "屏幕动是 Cursor 自动编程"** → 1) sensor publish `ghost_activity_observed` + `sir_afk_detected` 2) ProactiveShield 评分 ghost_activity_dampen (score *= 0.10, 非 hard skip) 3) 主脑 `ghost_activity_judge` 看 SWM 不把 IDE 窗口切换当 Sir 操作 (替代 fix3 硬 idle 60s skip)
4. **return_greeting "Windsurf terminal active" 误读** → 主脑 `ghost_activity_judge` directive 教 "看 sir_afk_detected metadata afk 时长, 不评论屏幕"

---

## � β.5.41 — Dashboard 重构 (Sir 16:43 真理)

> Sir 16:43 关键要求: **所有 Sir 拍板的事全面出现 + 交互清晰 + 状态实时 + 让我知道操作会影响什么 + 重构 UI**

| commit | sub-step | 内容 |
|---|---|---|
| `3493e31` | **β.5.41-A 盘点** | `docs/JARVIS_DASHBOARD_REBUILD_AUDIT.md` 21 类 Sir 可操作项盘点 (review queues 11 + active states 9 + sir_profile 1) + 缺口分析 + 4 sub-step 方案 |
| `b218d48` | **β.5.41-B backend** | `jarvis_actionable_items.py` 统一抽象 `ActionableItem` schema (id/category/subcategory/state/preview/fields/impact_if_modified/impact_if_deleted/created_at/use_count/auto_proposed/proposed_by/sir_acked) + 11 extractors 覆盖 21 类 + 68 items 全 scan + `mutate_actionable_item` (modify/delete/restore/activate/reject) + corrections.jsonl + sir_acked tracking. 16 test pass |
| `2c1c887` | **β.5.41-C UI** | `scripts/jarvis_dashboard_web.py` 加 `/items` 3-pane 路由 (sidebar 分类 + 滚动卡片 + 修正/删除按钮 + 影响 tooltip + Toast + Alpine 实时刷新) + 5 API endpoints (`GET /api/items` + `POST /api/items/<id>/<action>`). 老 dashboard 主页加 "💡 我们的事" 按钮入口. 8 test pass |
| `2abcea7` | **β.5.41-D 主脑注入** | `jarvis_central_nerve._assemble_prompt` 加 `[SIR CORRECTIONS / 24h]` block. Sir 改/删 item → corrections.jsonl 写 → 主脑下轮 prompt 看 → 不再用错版本/不再 reference 已删. 1 source test pass |

**total 25 test pass + 147 regression pass, 0 退化.**

### Sir 体感 (重启 + 开 dashboard 后立刻生效)

1. **打开 web dashboard** (http://127.0.0.1:8765) → 顶部按 "💡 我们的事" → 进 /items 页
2. **3-pane**: 左 sidebar (21 类分组 + 数量), 中卡片流 (按 category/state filter), 右 detail (点 ✏️ 修正)
3. **每条卡片**: emoji + category 标签 + 状态彩条 + 🤖auto/Sir 标记 + 已看/未看小圆点 + preview + id + 影响 tooltip + 3 按钮 (✏️ 修正 / 👁 标已看 / 🗑 删)
4. **修正面板**: 显示所有可编辑字段 (string/number/array 自动 form) + 影响预览黄框 + Sir 备注框 + 💾 保存
5. **删除**: 浏览器 confirm (含影响 tooltip) + 原因 prompt → 写 corrections.jsonl + UI 自动 reload
6. **主脑感知**: Sir 改"家具党"为"搬家党" → 下次主脑 prompt 看 `[SIR CORRECTIONS]` → 不再用"家具党"

### 影响范围 (重启即可)
- 主页 `/` 加按钮 (不动老 dashboard 功能)
- 新页 `/items` 全功能 (老 review_queues 还能用 `/api/review/activate/reject` 操作)
- corrections.jsonl 自动注入主脑 prompt (chat + nudge 都看到)

---

## � Jarvis Future Vision — Desktop Copilot (未来构思框架, 无编号无 sprint)

> Sir 16:40 真理: "**不要定位成 β.5.42 编号, 设计成未来构思和主框架设计, 我们还没确定细节如何实现, 这样太武断了**".
>
> Sir 16:30 核心: "脱离繁重数据工作流, 给予 Jarvis (1) 稳固交互地基 (2) 真用鼠标键盘操作复杂工作流".

| 文档 | 内容 |
|---|---|
| `@d:\Jarvis\docs\JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` | **未来构思框架** (改名了, 去 sprint 编号). Sir 真要做时再拆 detailed spec |

**4 模块** (顺序未定):
- **A**: Screen Vision (vision LLM 看屏幕找元素)
- **B**: desktop_workflow_vocab.json (PR/PS/Figma workflow codify)
- **C**: Intent router 扩 + Safety gate
- **D**: 远程触发 (Telegram/微信 bot)

**约束 (Sir 真理)**:
- 不动 LLM 重模块的交互地基
- 不做 ETL / 数据流 (让 Cascade 做)
- 算法精准 ≥ 0.85 confidence 才点
- Sir-可中止 preview 黄金窗口

---

## 🔧 β.5.40-fix — Sir 16:07 sleep nudge BUG (准则 6 evidence-driven)

| commit | 内容 |
|---|---|
| `a3089bc` | **不动 compute_urgency 硬 dampen**. ProactiveCare publish `concern_timing_evidence` SWM 让主脑看. 加 `concern_timing_judge` directive (priority=8 高于其他, 否决 top concern 盲目反应). 主脑看 evidence 自决: 16:07 sleep concern → in_window=False, hours_until=+6 → 不主动提"早睡" |

**Sir 体感 (重启后生效)**:
- 下午 16:07 主脑看 SOUL inject 含 sir_sleep_streak top → 但看 SWM `concern_timing_evidence` → 知道远离 timing → 不再推 "早睡"
- 临近 22:00 (hours_until ≤ 4) → 主脑软铺垫 OK
- 在窗口内 (22-1) → 正常 nudge

**testcase**: 14/14 pass (含 `test_compute_urgency_unchanged` 验证准则 6 没硬编码).

---

## � β.5.40 — Sir 长期方向 A.1/B.1/E.1/A.2 全做 (除 D, ~10h, 4 commit)

> Sir 决定: "全做, 除了 D, 按推荐顺序全部往下, 但是算法要精准". 4 个长期方向 100% 不动 TTFT (全后台 daemon / sensor / publish-only SWM).

| commit | 方向 | 内容 | testcase |
|---|---|---|---|
| `8a07d44` | **A.1 ambient_audio** | `jarvis_ambient_sensor.py` Hook AuditoryCortex 同帧 PCM data (不抢麦克风) + FFT classifier (laughter/sigh/humming/video/conversation) + 500ms window + ≥ 3 连续 + conf ≥ 0.6 才 publish + 60s 同类 cooldown + 隐私只判状态不存 audio. SWM etype `ambient_state` + `ambient_state_judge` directive (5 场景: conversation/video/laughter/sigh/humming) | 17 |
| `b9a69cb` | **B.1 InsideJoke** | `jarvis_inside_joke_reflector.py` L7 daemon 03:30-06:00 跑 LLM 扫近 7d STM 提取 Sir 重复梗/称呼 (≥ 2 evidence + conf ≥ 0.8 严格) → propose `relational_state.inside_jokes review` (Sir CLI 拍板 → active) | 13 |
| `85d5c18` | **E.1 CompanionRhythm** | `jarvis_companion_rhythm_reflector.py` L7 daemon 算每 hour Sir nudge-receptive score (engaged/rejected/silent), 写 `memory_pool/nudge_window_vocab.json` + `scripts/nudge_window_dump.py` CLI. ProactiveCare 每 tick publish `nudge_window_advice` SWM (score < 0.3 → 主脑克制). `nudge_window_advice_judge` directive (3 场景: low/normal/high receptive) | 27 |
| `fc082b3` | **A.2 physio_proxy** | `jarvis_physio_proxy.py` 用 PhysicalEnvProbe 已有 key/mouse/backspace/switch fields 算 energy/focus/stress 评分. ProactiveCare 每 tick publish `physio_state` SWM. `physio_state_judge` directive (4 场景: stress 高/心流/疲倦/正常) | 18 |

**total 75/75 + 41 β.5.37-39 regression (116/116 pass), 0 退化.**

**Sir 真机体感 (要重启才生效, 大部分要数据累积一周)**:
- **A.1 ambient**: Sir 跟别人聊天 / 看视频 → Jarvis 自动 SILENT 不打断 (主脑 `ambient_state_judge`)
- **B.1 inside_joke**: Sir 自创"家具党"梗用 ≥ 2 次 → 一周后 03:30 L7 daemon propose, Sir 拍板后 Jarvis 适时引用. **Sir 强调"算法要精准"**: ≥ 2 evidence + conf ≥ 0.8 严格
- **E.1 rhythm**: Sir 周一 14:00 历史拒 nudge 多 → 之后周一 14:00 主脑 tone 极简偏 SILENT. **Sir CLI**: `python scripts/nudge_window_dump.py --show` 看表 / `--set-weekday 14 0.2` 手设
- **A.2 physio**: Sir 反复改 + undo 多 (stress > 0.6) → 主脑不急 offer help, tone warm 静默. Sir 心流 (focus > 0.7 + stress < 0.3) → SILENT

**SWM evidence (β.5.40 新 3 etype)**:
- `ambient_state` (TTL 180s, salience 0.45)
- `nudge_window_advice` (TTL 3600s, salience 0.35)
- `physio_state` (TTL 180s, salience 0.45)

---

## 🔥 Sir 13:00 真机实测 fix (β.5.34 保留)

| commit | marker | 内容 |
|---|---|---|
| `11b0cc2` | β.5.34-fix | Focus Lock UI 加 listening cue (`🎙️ Listening for your reply…`) — UI 文案非硬编码决策, 保留 |
| `c3dfdf0` | β.5.36-fix | `test_persona_under_3000_chars` cap 5500→9500 (PERSONA 涨随 directives) |

---

## 🔥 β.5.39-fix — Sir 15:22+15:37 实测 BUG 治本 (2 commit)

| commit | 内容 |
|---|---|
| `149708f` | β.5.39-fix `infer_expected_behavior` 优先 parse description 显式 "X 分钟" + dashboard `read_relational` review_n 排除 `_meta` + read_review_queues 加 5 新 vocab sources |
| `fa5b758` | **β.5.39-fix2 真治本**: commitment_check nudge 在 fulfillment 检测**之前**触发 → Sir 真履行也催 BUG. 修法: deadline-based nudge 之前先 PreCheckFulfillment, fulfilled → skip nudge + 走 pending_ack 路径 |

**Sir 真机体感 (要重启才生效)**:
- Sir 说 "我休息 5 分钟" → fulfillment threshold 真用 **5 min** 不是 vocab 30min
- Sir 真离桌回来 → commitment 自动 mark fulfilled → 不催 → 下次 Sir 开口 Jarvis 致意 "您喝完水了 Sir"
- dashboard 反思区显示真 review 数 (不再因 `_meta` 误算)

---

## 🌙 β.5.39 — Sir 动态催睡 3 层架构

| commit | 层 | 内容 |
|---|---|---|
| `4dba8e1` | 层 1 | `memory_pool/sir_sleep_pattern_vocab.json` + `scripts/sleep_pattern_dump.py` CLI |
| 同 | 层 2 | `jarvis_sleep_pattern_reflector.py` L7 daemon (每日 03:00) + wire 到 `central_nerve` |
| 同 | 层 3 | `jarvis_proactive_care.py` distance 公式 + publish `sir_sleep_pattern` SWM + `_trigger_sleep_mode` hook `log_sleep_event` |
| 同 | 层 3 | `late_night_care_judge` directive 教主脑用 `distance_h` 描述, FORBIDDEN 硬编码 "22:00/凌晨" |

**testcase**: 10/10 + 94 regression pass.

**Sir 真机体感**:
- 第一周: vocab unfilled → 走 fallback 老硬规则 (1-5am 凌晨)
- L7 reflector 每日 03:00 扫 sleep events 累计 ≥ 5 → typical_sleep_hour 自动生成
- 之后 ProactiveCare 看 distance 自适应: distance > 2h 不催, distance ~ 0 → 1h 适度, distance > 1h 强催
- 主脑回话: "您比平时晚 30 分钟" 不是 "已经凌晨了"
- Sir CLI 随时 `python scripts/sleep_pattern_dump.py --set-weekday 24 --set-weekend 25.5` 手改典型时间

---

## � β.5.38 — 方向 C 主脑 directive 库扩 (Sir 选)

> 利用 β.5.37 架构杠杆, 5 个新 SWM evidence directive. 主脑看 SWM evidence + 时间 + Sir 当前一句 自决场景 A/B/C/D contextual.

| commit | directive | 触发 | 主脑自决 |
|---|---|---|---|
| `0ac082b` | `morning_mood_judge` | 6-10am + `is_first_active_today` | 看 afk 评 Sir 睡眠 → 个性化简报 (不死板 "Good morning") |
| 同 | `late_night_care_judge` | ≥ 23:00 / < 02:00 | deep work 静默 / 困住柔声 offer / 凌晨温柔提醒 |
| 同 | `silent_company_judge` | 主动 nudge 无 user_input + ghost/afk SWM | 默认 SILENCE, 例外: urgency ≥ 0.85 |
| 同 | `callback_recall_judge` | Sir 输入含 "那个/上次/that one" | 先找 referent (STM/callback/concerns), 不瞎猜 |
| 同 | `mood_shift_judge` | 30min 内 ≥ 3 类 state signal | 多信号 = 复杂 context, tone 一致 |

**testcase**: 14/14 pass + 215 regression pass.

**Sir 真机体感**:
- 早上不再 "Good morning, Sir" 死板模板
- 深夜不再频繁催睡
- Sir 心流时 SILENCE 不打扰
- 模糊指代不瞎猜
- 多信号变化 tone 自适应

---

## ✅ Sir β.5.37 真机实测 check list (重启后跑)

> Sir 重启 Jarvis 后看下面 11 行是否 OK. 出 BUG 报告我修 directive (不动 sensor/sentinel架构).

```
[ ] 1. 启动正常 → 不抛 sensor exception, log 显示 PhysicalEnvProbe / SleepDetector / Conductor 都启
[ ] 2. Sir 说 "我要去休息一下" → 不再 47s 后被催 offer_help (struggle vocab 不命中 "我去" + 主脑 sir_intent_judge 看 struggle_text 判 dismiss)
[ ] 3. Sir 真去休息 30+ min → PhysicalEnvProbe publish sir_afk_detected (Grep log "sir_afk_detected") 到 SWM
[ ] 4. Sir 离桌期间 Cascade 跑代码 → publish ghost_activity_observed (cascade_active=True), ProactiveShield 触 alert 时 frustration_score 含 ghost_activity_dampen 维度
[ ] 5. Sir 起床后 ReturnSentinel return_greeting → 主脑看 SWM ghost_activity_observed → 不说 "Windsurf terminal active" / "您在工作", 改说 afk 真实长度 (e.g. "您小睡了一会儿")
[ ] 6. Sir 起床第一句 "嗯,我睡的不好..." → 主脑 sleep_confirmation_judge 看 sir_afk_detected (afk > 30min) → 判 stale signal, 当新对话处理 (不进 sleep mode)
[ ] 7. Sir 说 "我搞不定 X 了 / stuck on Y" (真 struggle) → 主脑 sir_intent_judge 判场景 A → offer help
[ ] 8. Sir 说 "搞不定老婆 / 看不懂这电视剧" (casual) → 主脑 sir_intent_judge 判场景 B → 不主动 offer help
[ ] 9. SleepDetector 中置信 score (0.5-0.7) → 不再硬 set pending state, log 显示 "(主脑判): ... (signal 已 publish to SWM)"
[ ] 10. Grep latest.log "sleep_intent_signal|ghost_activity_observed|sir_struggle_observed|shield_observation" 各类 SWM 信号都能看到
[ ] 11. directive registry: scripts/registry_dump.py list 含 sleep_confirmation_judge / ghost_activity_judge / sir_intent_judge (state=active)
[ ] 12. β.5.38 早上 6-10am 首次说话 → morning_mood_judge fire, 不再 "Good morning, Sir" 死板
[ ] 13. β.5.38 ≥ 23:00 chat → late_night_care_judge fire, 主脑场景 A/B/C 自决
[ ] 14. β.5.38 心流期主动 nudge (无 user_input) + ghost SWM → silent_company_judge → 主脑 emit <SILENT>
[ ] 15. β.5.38 Sir 说 "把那个文档打开" → callback_recall_judge fire, 主脑先找 referent
[ ] 16. β.5.38 30min 内 ≥ 3 类 SWM signal → mood_shift_judge fire, 主脑 tone 一致维持
[ ] 17. β.5.38-fix BUG #1 修: nudge 字幕真显示 (Jarvis 说的中英文出现在 UI overlay, 不被 listening cue 清掉)
[ ] 18. β.5.38-fix BUG #2 修: Sir 说 "晚上会早点睡" 不再误判 sleep intent + 1800s 倒数 (排除"早点/晚点"副词)
[ ] 19. β.5.39 启动正常 → log 显示 "💤 [SleepPatternReflector] L7 vocab daemon ready"
[ ] 20. β.5.39 Sir 真去睡 → log 显示 "💤 [SleepPattern] logged: YYYY-MM-DD H.Hh (nerve_trigger_sleep_mode)"
[ ] 21. β.5.39 一周后 `python scripts/sleep_pattern_dump.py --show` 显示 typical_sleep_hour 有值 + ProactiveCare 用 distance 公式 (Grep "distance=" in log) + 主脑回话 "您比平时晚 X" 不再说 "已经 22:00 了"
[ ] 22. β.5.39-fix Sir 说 "休息 5 分钟" → log `📝 [CommitmentWatcher] 已注册` + commitment 有 `expected_behavior.threshold=5` (Grep `_threshold_source: description_explicit`)
[ ] 23. β.5.39-fix2 Sir 真离桌 ≥ 5min 回来 → log 显示 `✅ [CommitmentWatcher/PreCheckFulfilled]` + commitment_check nudge 不发 + STM 加 [pending_ack ... fulfilled] tag
[ ] 24. β.5.39-fix2 Sir 没履行 deadline 过了 5min → 还是会 commitment_check nudge (老路径正常工作)
[ ] 25. β.5.39-fix dashboard 反思区显示真 review 数 (不再因 _meta 误算 = 2)
[ ] 26. β.5.39-fix dashboard 含 5 新 vocab review_queue (screen_tease/struggle/directives/sleep_pattern/behavior_inference)
[ ] 27. β.5.40-A1 启动正常 → log `🎵[AmbientSensor / β.5.40-A1] 启用`
[ ] 28. β.5.40-A1 Sir 跟人说话 / 看视频 → log `🎵 [AmbientSensor] conversation/video_playing` + 主脑 silent
[ ] 29. β.5.40-B1 启动正常 → log `😄 [InsideJokeReflector] L7 daemon ready (β.5.40-B1)`
[ ] 30. β.5.40-B1 一周后看 `python scripts/relational_dump.py` inside_jokes 出现新 review entries (Sir 拍板后 active)
[ ] 31. β.5.40-E1 启动正常 → log `📈 [CompanionRhythmReflector] L7 daemon ready (β.5.40-E1)`
[ ] 32. β.5.40-E1 一周后 `python scripts/nudge_window_dump.py --show` 显示某些 hour 有 score (不再全 null)
[ ] 33. β.5.40-A2 启动正常 → log `💪 [PhysioProxy] energy=X.X focus=X.X stress=X.X` 每 60s 一次 (Sir 在使用电脑)
[ ] 34. β.5.40-A2 Sir 心流 (focus > 0.7) → 主脑 SILENT, Sir stress > 0.6 → tone 关切不急 offer
[ ] 35. β.5.40 4 新 SWM signal 都进 SWM: Grep latest.log `ambient_state|nudge_window_advice|physio_state` 有真发
[ ] 36. β.5.40-fix Sir 下午 (e.g. 16:00) 跟 Jarvis 聊天 → 主脑不再推 "早睡 / early night" (看 SWM `concern_timing_evidence` 知道远离 timing). Grep log `concern_timing_evidence`+ `in_window=False`
[ ] 37. β.5.41 主页加 "💡 我们的事" 紫色按钮 → 点开 /items 3-pane (左 sidebar 21 类分组 + 中卡片流 + 右 detail panel)
[ ] 38. β.5.41 sidebar 各 category 显示数量 + 点切换 filter, 状态过滤可选 (全部/review/active)
[ ] 39. β.5.41 卡片 [✏ 修正] 弹出 detail panel, 含所有可编辑字段 + 影响预览黄框 + 备注框 + 💾 保存. 改一条 inside_joke phrase → 应 toast "✅ 已保存"
[ ] 40. β.5.41 卡片 [🗑 删] confirm + 原因 prompt → toast "🗑 已删除" + 卡片消失. memory_pool/sir_corrections.jsonl 含此 delete entry
[ ] 41. β.5.41 [👁 标已看] 点后小圆点变绿. memory_pool/sir_acked_state.json 有此 id 记录
[ ] 42. β.5.41 Sir 改完一条后, 主脑下次对话回应中 Grep log `[SOUL inject]` 之后 prompt 应含 `[SIR CORRECTIONS / 最近 24h]` block 列出 Sir 改了什么
```

**真机出 BUG 时 报告我**:
- 报告 Sir 说了什么 + Jarvis 怎么响应
- Grep 相关 SWM 信号 publish 是否真发了
- 我**只改 directive text** (主脑指引), **不改 sensor / sentinel** — sensor evidence 是 truth, sentinel publish-only 不动

---

## 🚨 主迭代 (β.5.34/35 / 2026-05-20 10:46 → 12:42, 5 commits) — Sir 10:46 实测 4 BUG 治本

### β.5.34 BUG 1 + 4 小修 (单 commit)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `8c633a4` | β.5.34 | **BUG 1 早安 morning briefing 评级反转** — `jarvis_chat_bypass.py:3710-3758` 翻转 β.4.12 "should NOT bring up" 抑制, 改 `[MORNING BRIEFING POSTURE]` evidence-only 让主脑参考 SOUL inject (concerns/threads/unfinished/attention) 自决列简报 + **BUG 4 Focus Lock UI 真激活** — `jarvis_worker.py:3262-3274` 在 focus_lock 后端激活时同步 emit `("focus", True)` → `SubtitleOverlay.set_focus_mode(True)` 触发 → UI overlay 持续显示等 Sir 回应 (而不是淡出消失) + test 跟 Sir β.5.34 决策反转 (β.4.12 推翻) + 顺手修 β.5.22-D `sleep_due` test | 13+4 pass |

### β.5.35 BUG 2 大修 (4 sub-commits) — Design doc: `docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md`
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `d32da6b` | **β.5.35-A/B** | **screen_tease vocab 持久化 + L7 reflector** — `memory_pool/screen_tease_vocab.json` (5 seed: error_debugging / entertainment / slacking / reading_docs / ide_focus) + `scripts/screen_tease_vocab_dump.py` CLI (active/review/add/activate/reject/deactivate) + `jarvis_smart_nudge.py._load_screen_tease_vocab` mtime cache (替代硬编码 error_kw/fun_kw/slack_kw) + `jarvis_screen_tease_reflector.py` 新 daemon (24h 1 跑 OpenRouter cheap, 看 PhysicalEnvironmentProbe.window_history 提取 unmatched titles → propose review_queue) + central_nerve 启动 wire | 12+11 pass |
| `24b88e4` | **β.5.35-C** | **offer_help 触发源重设 + sir_struggle_vocab** — `memory_pool/sir_struggle_vocab.json` (10 seed phrase: stuck/frustrated/asking_how/expletive/confusion × zh/en, severity high/medium) + `scripts/struggle_vocab_dump.py` CLI + `jarvis_worker.py` VoiceListenThread `_load_struggle_vocab + _detect_sir_struggle` (ASR 出口 hook 命中写 `last_struggle_at/phrase_id/severity/text`) + `jarvis_conductor.py._check_path_a` 加 SirStruggleVocab 优先路径 (fresh ≤90s 直触 offer_help, bypass cooldown) + ProactiveShield path 改 `screen_tease` 而非 offer_help (语义解耦) + `_dispatch_path_a` 透传 struggle context 到 nudge_context + `jarvis_chat_bypass.py:3782-3805` offer_help directive 改 evidence-driven 引 Sir 原话 + `_test_p2_refusal_and_audio.py` regex 顺手修 (pre-existing) | 20 pass |
| `031231e` | **β.5.35-D** | **StruggleReflector L7 vocab daemon** — `jarvis_struggle_reflector.py` 新 (24h 1 跑 OpenRouter cheap, 看 STM `[src=user_voice]` 提取 ≥2 evidence 的新 struggle phrase → propose review_queue, Sir CLI `struggle_vocab_dump.py --review-list / --activate` 拍板) + central_nerve 启动 wire (stm_provider 复用 WeeklyReflector 风格) | 12 pass |

### Sir 真机实测 check list (β.5.34/5.35 落地完, Sir 重启实测)

| BUG | check 项 | 预期 | 备用 CLI |
|---|---|---|---|
| **BUG 1** | 早安第一次说话 (跨夜 AFK + morning_window) | Jarvis morning briefing 列 1-2 件 concerns/threads/unfinished (不是普通 welcome back) | - |
| **BUG 4** | Sir 收到任意 nudge (offer_help / proactive_care / sleep_due) | UI 字幕 overlay 持续显示 (不淡出), 90s 内 Sir 不喊唤醒词直接说话能 ASR | log `[Focus Lock]` + UI subtitle stay |
| **BUG 2-tease** | Sir 切到 IDE / 文档 / SO 窗口 | screen_tease 调皮观察 (不再"一周静音") | `python scripts/screen_tease_vocab_dump.py --active-only` |
| **BUG 2-tease L7** | 24h 后看是否 propose 新 category | `screen_tease_vocab.json` `review_queue` 非空 | `python scripts/screen_tease_vocab_dump.py --review-list` |
| **BUG 2-help** | Sir 说"卡住" / "搞不定" / "fuck" / "怎么办" | Conductor 30-90s 内 offer_help (引 Sir 原话, 不说工具名) | log `🆘 [SirStruggle] phrase=...` |
| **BUG 2-help L7** | 24h 后 STM 含 ≥30 user_voice → propose 新 struggle phrase | `sir_struggle_vocab.json` `review_queue` 非空 | `python scripts/struggle_vocab_dump.py --review-list` |
| **BUG 2-shield** | 屏幕看到 error keyword (β.4.X 触发 offer_help 误推) | 改触发 screen_tease (调皮观察, 非"need help") | log `Tease Screen` not `Offer Help` |

### β.5.36 BUG 3 工具名泄漏大修 (单 commit, 5 sub-step 合并)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `41cbf68` | **β.5.36-E/F/G/H/I** | **BUG 3 intent channel + tool name scrub 大修** — E: `memory_pool/intent_to_tool_map.json` (15 seed intent: check_top_cpu/mute_audio/dashboard_open/...) + `scripts/intent_map_dump.py` CLI. F: `jarvis_skill_registry.to_prompt_block` 改双轨 — intent_map 存在 → SEMANTIC CAPABILITIES (intent 列表 + `<TOOL_CALL>` directive + NEVER speak tool names), fallback 老 SKILLS 块也删 "MUST reference by name" 改成 NEVER speak. G: `jarvis_intent_router.py` 新 (IntentParser 提取 `<TOOL_CALL>{intent}` tag + IntentRouter.route_and_invoke_all 翻 tool 名 + 调 fast_call + 结果回流 event_bus, dangerous intent skip 走 PROMISE 路径) + chat_bypass stream_chat/stream_nudge 末尾 hook + worker.run 启动 init_default_intent_router 注入 fast_call. H: `jarvis_utils.scrub_internal_names` helper (剥 organ.command + `<TOOL_CALL>` tag) + `jarvis_ui._poll_queue` 'zh'/'en' branch 调 scrub 防漏给 Sir 看到. I: 33 新 testcase (intent_map schema/CLI + IntentParser corrupt/multi/case + IntentRouter resolve/invoke/dangerous_skip + scrub_internal_names 全 organ + UI/chat_bypass/worker wiring) + 5 老 `_test_r8_axis3_l2_capability_phrasing.py` 改 fallback path. | 33+15 pass |

### Sir 真机实测 check list — 重启 Jarvis 后完整跑

| BUG | 操作 | 预期 | log/CLI 验证 |
|---|---|---|---|
| **BUG 1** 早安 | 跨夜 AFK + 起床第一句 | morning briefing 列 1-2 件 concerns/threads/unfinished (β.5.34) | log `MORNING BRIEFING POSTURE` |
| **BUG 4** Focus | 收 nudge (offer_help/proactive_care/sleep_due) | UI 字幕持续显示, 90s 内不喊唤醒词直接说 | log `[Focus Lock]` + subtitle stays |
| **BUG 2-tease** | 切 IDE/文档/SO/IDE 等 5 类窗口 | screen_tease 调皮 (不再一周静音) (β.5.35-A) | `scripts/screen_tease_vocab_dump.py --active-only` |
| **BUG 2-tease L7** | 24h 后 | `screen_tease_vocab.json` `review_queue` propose 新 category (β.5.35-B) | `scripts/screen_tease_vocab_dump.py --review-list` |
| **BUG 2-help** | 说"卡住"/"搞不定"/"fuck"/"怎么办" | 30-90s 内 offer_help (引 Sir 原话, β.5.35-C) | log `🆘 [SirStruggle] phrase=...` |
| **BUG 2-help L7** | 24h 后 | `sir_struggle_vocab.json` propose 新 struggle phrase (β.5.35-D) | `scripts/struggle_vocab_dump.py --review-list` |
| **BUG 2-shield** | 屏幕含 error keyword (cascade/cursor IDE 错误) | log `Tease Screen` (不是 `Offer Help`, β.5.35-C 语义解耦) | log `🎯 [Focus Lock] screen_tease` |
| **BUG 3-prompt** | 主脑收 offer_help nudge | LLM prompt 含 `SEMANTIC CAPABILITIES (β.5.36 intent channel)`, 不含 `process_hands.X` 工具名 (β.5.36-F) | grep `[Nudge SOUL inject] mode=nudge` 看 prompt 渲染 |
| **BUG 3-tts** | LLM 偶尔违规说工具名 | Audio Guard 替换 'a quick check' (β.4.X) | log `🔇 [Audio Guard / Tool Name]` |
| **BUG 3-subtitle** | LLM 偶尔违规说工具名 | 字幕 overlay 已 scrub 工具名 + `<TOOL_CALL>` tag (β.5.36-H) | UI 字幕不见 `process_hands.X` |
| **BUG 3-intent** | LLM 主动 emit `<TOOL_CALL>{intent="check_top_cpu"}` | intent_router 后端翻 `process_hands.get_top_cpu` 执行 + event_bus publish 结果 (β.5.36-G) | log `🔧 [IntentRouter] check_top_cpu=✅` |

---

## 🚧 历史迭代 (β.5.22 → β.5.25 / 2026-05-19 23:01 → 05-20 02:34, 10 commits)

### β.5.22 Sir 01:22 实测 BUG 治本 (7 sub-step)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `f297deb` | β.5.22-A/B/E | dismissal flow 调 NudgeGate.activate_sleep_mode + CareWindowGuard 看 _sleep_intent_until + ReturnSentinel 接 _check_short_sleep | 33 |
| `679e205` | β.5.22-G/F | sleep_intent 到点 due timer 主动提醒 + refusal_vocab.json (4 类) dismissal/sleep_soft 早退 + CLI scripts/refusal_vocab_dump.py | 同上 |
| `4739ef1` | **β.5.22-C** | **动态语义反馈 LLM judge** - Concern.daily_progress/last_user_feedback/optimal_timing + ConcernsLedger.record_user_feedback API + jarvis_concern_feedback.py (新 ~232 行 QuickClassifier.prompt_raw 调用) + post_chat hook + urgency 计算 progress_mul + timing_mul (0.3 floor 不 close, before_sleep 反弹 1.5x) | 同上 |
| `36d776c` | β.5.22-D + C-fix | sleep_due 加 focus list (offer_help/commitment_check/proactive_care 4 类型) + QuickClassifier.prompt_raw generic API (替代每个 detect_X 重复 boilerplate) | 同上 |

### β.5.23 准则 6 完结 (2 sub-step)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| (待 grep) | β.5.23-A | cooldown 阈值 vocab JSON `memory_pool/proactive_care_cooldown_vocab.json` (11 阈值 + ranges) + `_get_cd()` mtime cache + 5 call sites 替换 + CLI `scripts/cooldown_vocab_dump.py` (list/show/set/history/review) | 23 |
| 同 | β.5.23-B | `jarvis_concern_feedback_reflector.py` (新 ~290 行) ConcernFeedbackReflector L7 daemon - 24h 周期看 7d STM + Concern.last_user_feedback + nudge 推送量 + Sir 拒绝量 → QuickClassifier.prompt_raw propose 阈值调整 → 写 review_queue 等 Sir 拍板 (CompanionCenter 启 daemon) | 同上 |

### β.5.24 Dashboard tkinter 重构 (Sir 01:58 反馈 'X 拒绝说不存在')
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `55e4286` | β.5.24 | scripts/jarvis_dashboard.py 重构 - main grid 信息1/待处理5/观测2 + read_review_queues 整合 4 源 (concerns/relational/directive/**cooldown_vocab L7**) + thread title fallback (修 X BUG root cause) + cooldown action_activate/reject 路径 | 20 |
| `517cf56` | β.5.24-finish | 标题改 β.5.24 + _make_action_card 加 height=380 + grid_propagate(False) (修待处理区塌缩 BUG - 空 inner canvas → group_todo 整块=0) | 同上 |

### β.5.25 Web Dashboard (Sir 02:17 'tkinter 不喜欢, 现代审美 + 窗口缩放')
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `4ceb046` | β.5.25 | `scripts/jarvis_dashboard_web.py` (新 ~600 行 Flask + Tailwind CDN + Alpine.js) - 4 大区 (整体状态 + 待拍板 + 信息 + 观测) + 现代 glass-morphism 卡片 + 响应式 grid (md:2/lg:4) + Toast 通知 + auto 10s 轮询 + /api/all /api/review/<activate|reject> endpoints | 19 |
| `6582ec2` | β.5.25-extend | 补 Commitments todo 区 (3 列 grid) + cancelCommitment Alpine 方法 + /api/commitment/cancel endpoint | 同上 |
| `79faf7d` | β.5.25-finish | 补 Jarvis 承诺卡 (信息区扩 4 卡) + 言出必行健康度宽卡 (top 5 空头话) + dashboard.ps1 一键启动 launcher | 同上 |
| `e01e868` | β.5.25-route | `ui_control.dashboard_open` 改默认开 web (port 8765 探测复用 + 启动失败 fallback tkinter) + dashboard_close 双 kill (web wmic + tkinter taskkill). Sir 现在语音"打开面板"开 web 浏览器 | - |
| (修 BUG 1) | β.5.24-fix2 | tkinter 加回 messagebox.showinfo 完成弹窗 (Sir "默契活动无反应" root cause = 反馈不显眼) | - |

### β.5.31-33 Sir 03:36-03:55 实测 BUG 治本 (5 sub-step)
| commit | marker | 内容 | testcase |
|---|---|---|---|
| `ce66f71` | β.5.31 | TIME ANCHOR 防时间幻觉 (`stream_nudge` 加 `[TIME ANCHOR]` 段反推 Sir 上句时间 + 距今 min) + 短 cmd 不臆造关怀 RULE (准则 5 严重 BUG: Sir 03:42 实测"十几分钟早就过去了" / Sir 03:36 实测 "ber" → 关心手部疲劳) | sub-batch ✓ |
| `ff5f95a` | β.5.31-fix | Sir 反问"为什么是模板?" → 准则 6 服从, 删 prescriptive RULE 改 [ASR QUALITY FACT] 事实段, LLM 自决 ask repeat / acknowledge ambiguity | 同上 |
| `73154cf` | β.5.32 | web layout 重构 (删 Jarvis 承诺卡 - 上面言行一致区已含; 长期惦记/你们之间 50/50 grid; 系统健康单独下行) + dismissal 光速 wake 30s grace lock (Sir 03:55 实测"只 1 分钟"询问光速触发 - NudgeGate.deactivate_sleep_mode 加 30s minimum lock + `_check_short_sleep` 加 30s grace early return) | 同上 |
| `dfbefd2` | **β.5.33** | **Cross-session memory callback PROACTIVITY_NEXT §E 落地** - `jarvis_cross_session_callback.py` 新 (CallbackStore + parse_natural_time_to_iso 周X/明天/后天/HH:MM) + SoulArchivist prompt 加 propose_cross_session_callbacks 数组提取 + dashboard read_review_queues 加 callback source + action_activate/reject 路由 + `_apply_callback_proposal` 写 `pending_callbacks.jsonl` + CommitmentWatcher `_consume_pending_callbacks` (启动时 + 每 5min) 转 hard commitment | 同上 |

**测试现状** (2026-05-20 10:33): pytest 全 collect IO error (PowerShell pipe 老问题, 非测试失败). Sub-batch 分批跑确认 β.5.31-33 引入 0 fail. 老 pre-existing fail: `test_persona_under_3000_chars` (Sir IP 不动) + `proactive_care_level_preset` 2 (vocab 化后 preset 阈值不匹配老 assert).

---

## 📌 文档遗留尾巴清单 (Sir 02:33 全扫结果)

| 来源 | 尾巴 | 优先级 | 现状 |
|---|---|---|---|
| `JARVIS_VOICE_PIPELINE_LATENCY.md §7.3` | filler list 20 条仍 `.py` 硬编码 (β.5.11 留尾), 应迁 `memory_pool/wake_filler_vocab.json` + CLI | 中 | 准则 6 违规, ~30min |
| `INTEGRITY_STACK.md §L1/L2/L3` | 标 ❌/⚠️ 但 β.4.1-4.5 已做 (L4 ClaimTracer enforce / L5 闭环 / L6 dashboard / L7 reflector) | 低 | **文档 stale** - 仅需 sync ❌→✅ |
| `INTEGRITY_STACK.md §L0.5` | 14 directive 全迁 JSON (β.2.9.12 立, 部分迁) | 中 | 进行中 (registry_dump.py 已建) |
| `FOUNDATION_AUDIT.md §STM` | STM source 区分 (reflector 幻觉 root cause) | 中 | **✅ 已做** (β.5.29 STM source append 4 worker + 3 sentinels + nerve API) |
| `PROACTIVITY_NEXT.md §E` | Cross-session memory callback | 低 | **✅ 已做 β.5.33** (SoulArchivist propose → review → activate → commitment_watcher 到点 nudge) |
| `JARVIS_PROACTIVITY_NEXT.md` 整体 | 5 大方向 A-E | 低 | 长期规划 |
| **ProactiveCare sensor=None 老 BUG** | `⚠️ tick err 'NoneType' object has no attribute 'tick'` - daemon bootstrap 路径漏初始化 | 低 | 非阻塞, 主路径 OK, 派生 signal 失效 |
| TODO.md 章程 cap | 当前 ~680 行 > 300 行 cap | 高 | β.4/4.6/4.7/4.8 段应滚 docs/TODO_ARCHIVE.md |

---

## 🎯 Sir 想要的新功能 (β.2.9 候选, 等下次启动)

| # | 功能 | 现状 | 实现方向 |
|---|---|---|---|
| 1 | 说 "睡觉" 自动单进程静音 WeChat (准则 5 真做不只说) | ✅ β.2.9.1 + β.3.0-vocab3 已做 | `l4_audio_hands.mute_app` + audio_ducking_targets.json |
| 2 | 说 "睡觉" 自动 dim 显示器 | ✅ β.2.9.1 已做 | `l4_display_hands.sleep_display` |
| 3 | "睡觉模式" 总调度: 检测 sleep 意图 → 自动 (1)+(2)+字幕透明化+ASR mute 30min | ✅ β.2.9.1 + β.5.22-G 完整 | `_trigger_sleep_mode_routine` + `_fire_sleep_due_nudge` 到点提醒 |

---

## 📚 旧轮归档

> 老段已沉档 `docs/TODO_ARCHIVE.md`. 含 β.5.9-16 / β.4.7-8 / β.4.1-6 / β.3.x / Session 0-4 / P0+19 / P0+18 / R8 etc.
> Sir 提"上次/上轮/某 marker" 时 `Grep docs/TODO_ARCHIVE.md` 取指定段, 不 Read 全文.

---


## 📕 AGENT QUICKSTART（Cursor Agent 必读 / 约 30 秒）

> **进窗口先读这两个文件，本节是简版指引**：
> - `AGENTS.md`（仓库根 / 所有 AI Agent 入口章程 / < 250 行）
> - `docs/JARVIS_WORKFLOW_PROTOCOL.md`（规范唯一源 / trace_id / commit / 测试 / push 时机）
>
> 出现冲突以 `PROTOCOL` 为准。`AGENTS.md` 是简版，`PROTOCOL` 是详版。本 TODO 章程段只列触发场景，**不复述规则**。


> **唯一目的**：让 Agent 用最少的 token 读取最准确的上下文，避免 Cursor 对话超 52MB（`Append data exceeds maximum size of 52428800 bytes`）锁死。**永远不要把整个 TODO / archive / 日志读进上下文。**

### 1. 文件分工

| 文件 | 用途 | Agent 读取规则 |
|---|---|---|
| `TODO.md`（本文件，<300 行） | **当前代办 + 已知 BUG + 章程** | ✅ 每次会话进来先读这个文件 |
| `docs/TODO_ARCHIVE.md` | 已完工的迭代回溯 / 因果链 / 测试统计 | ❌ 不要默认读。**仅当 Sir 明确说"上次/上轮/R7/P0+X/轴X…"等历史关键词** → 用 `Grep` 取那段、不要 `Read` 全文 |
| `docs/PROMPT_REFACTOR_PLAN.md` | **当前迭代 P0+20-β.0 完整 design doc** | ✅ 当 Sir 说"开始 β.0" / "prompt 重构怎么搞" 时 Read |
| `docs/NERVE_SPLIT_PLAN.md` | 上轮 P0+19 拆分 design doc（已完工，保留作历史参考） | ❌ 不主动读，除非 Sir 提"拆分历史" |
| `docs/runtime_logs/jarvis_*.log` | 每次启动的完整 stdout/stderr 实时同步 | ❌ 不要 `Read` 全文。**先看 `docs/runtime_logs/latest.txt`（一行，里面是最新日志的绝对路径），再用 `Grep` 取关键段** |
| `docs/funnel_logs/funnel_*.log` | 智能轻推漏斗的命中/拒绝判定 | 同上，按需 grep |

### 2. "上次/上轮"语义映射（Sir 提到这些词的 SOP）

| Sir 的话 | Agent 该做的事 |
|---|---|
| "上次发生了什么" / "刚才那个 bug" / "前面那段" | (1) `Read docs/runtime_logs/latest.txt` 拿绝对路径；(2) `Grep` 出对应错误/Pipeline/Human 段；(3) 必要时 `Read` 文件**指定行段**（`offset+limit`，**不要全文**） |
| "上轮/上次/上回那个 BUG 修了没" / "P0+X 修了没" | (1) 先 `Grep` `TODO.md` 看是否在已知未尽；(2) 再 `Grep` `docs/TODO_ARCHIVE.md` 找最后一次出现的 marker（`a.X / P0+X / 轴X / RX`）+ 状态 |
| "重启实测/我刚跑了 N 件事" | (1) 拉最新两份 `jarvis_*.log`；(2) Grep `║ 🗣️\|║ 🤖\|⛔\|❌\|🔁` 抓对话框 + 错误；(3) 报告新 bug 时**抄日志关键行号**，不要复述大段 |

### 3. 减少 token / 避开 52MB 上限的 5 条硬规

1. **`Read` 大文件加 `offset` + `limit`**：>500 行的文件一次最多读 200 行；jarvis_chat_bypass.py 3003 行 / jarvis_central_nerve.py 2089 行**永远分段读**。
2. **优先 `Grep`**：找"某变量/某 emoji/某错误码"全用 ripgrep（Grep 工具），不要 `Read` 全文 grep。
3. **TODO 写作上限**：本 `TODO.md` 永远 ≤ 300 行；超出 250 行就把"已完成的迭代"剪到 `docs/TODO_ARCHIVE.md` 顶部。
4. **回复给 Sir 的内容**：用表格 + 行号引用，不要复制大段代码；最多 1-2 个`startLine:endLine:filepath` 引用块。
5. **新增 BUG 修复完工**：在本文件**只保留 1-2 行**说明 + marker；详细因果链/测试统计**直接进 archive 顶部**。

### 4. 完工归档协议 / 三轮滚动制（写代码后做的事）

> **核心规则：本文件永远只保留"上一轮 + 当前轮"的内容；再往前的"上上轮"必须沉到 archive。**

| 时间轴 | 位置 | 内容粒度 |
|---|---|---|
| **当前轮**（进行中） | `TODO.md` 的「当前迭代」段 | 完整任务看板 + 子步骤进度 + 在此处持续更新 |
| **上一轮**（最近一次完工） | `TODO.md` 的「上轮完工速览」段 | 1 个段落 + 关键 marker 列表 |
| **上上轮及更早** | `docs/TODO_ARCHIVE.md` 顶部 | 完整因果链 / 测试统计 / 改动清单等所有细节 |

完工时 Agent 必做 6 步：① 当前轮变上轮（精简） ② 原上轮沉档到 archive ③ archive 目录表加行 ④ 写新一轮看板（marker 连号） ⑤ 完工 commit 带 marker 注释 ⑥ 滚动后整个 TODO ≤ 300 行。

---

## 🔮 路线候选（Sir 选定后开始）

- ✅ **路线 A.7**：P0+18-e — 待办链路收口 + 上游 Audio Guard + CW 持久化 + 终端色彩化
- ✅ **路线 A.8**：P0+18-f — 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报
- ✅ **路线 A.9**：P0+19 — Nerve 拆分（17479→324 / -98.1%）+ 依赖锁定
- ✅ **路线 A.9.5**：P0+20-W — Workflow 规范化 `v0.20.0-workflow`
- ✅ **路线 A.10**：P0+20-α — 拆分收尾 + 6 缺口（α.1-α.6）`v0.20.1-cleanup`
- ✅ **路线 A.10.5**：P0+20-α.7 — trace_id 双路分流 `v0.20.2-trace-stream-fix`
- ✅ **路线 A.11.1**：P0+20-β.0.1-3 — Registry + dry-run + 双层注入 `v0.21.0-prompt-refactor-phase1`
- 🔄 **路线 A.11.2 当前轨**：**Phase 1-6 完整重构** — 救火 5 修 + push + Gemini 评分 + 瘦身 + 全审计 + 全测（详「当前迭代」段，~8-10h）
- ⏳ **路线 B 候选**：让 PromiseExecutor 真跑长任务 — 选 3 个高价值场景（每日 9:00 驾照科一 3 题 / 起床播报 / 番茄钟）
- ⏳ **路线 B+ 候选**：AgendaLedger + DailyBriefing + WeeklyDigest + SkillsAtAGlance（让 Jarvis 从 reactive 变 goal-driven）
- ⏳ **路线 C 候选**：R8 轴 4 — OCR / 后台测试 / 全局热键
- ⏳ **路线 D 候选**：R9 死代码清扫批次 2-3 + Qwen3 本地兜底
- ⏳ **路线 E 候选 / 长期**：跨设备入口（FastAPI + WebSocket）+ 决策透明 UI + 个体演化曲线 + 关系延续证据

---

## 📦 归档指针

- **上一轮 P0+19**（roll/deps/0-9/6.a-f/final / 2026-05-16 00:30-02:45 / 17 sub-step / Nerve 17479→324 / 16 新文件 / 1098 testcase）：`docs/TODO_ARCHIVE.md` 顶部「P0+19 完工段」
- **更上一轮 P0+18-f**（f.1-f.4 / 2026-05-15 22:00-22:50 / 4 BUG / 性能崩溃修复 + 诚信加固 + 长期 mute + Integrity 误报）：`docs/TODO_ARCHIVE.md`「P0+18-f 完工段」
- **更早 P0+18-e / P0+18-d / P0+18-c / P0+18-b / R8 轴3 / R7 等**：`docs/TODO_ARCHIVE.md` 后续段（按归档目录 grep）
- **规范唯一源**：`docs/JARVIS_WORKFLOW_PROTOCOL.md`（trace_id / 测试 / commit / push / Agent 行为 / 安全 / 性能基线）
- **入口章程**：`AGENTS.md`（所有 AI Agent 自动读 / 极简版 / 指向 PROTOCOL）
- **Cursor 硬规则**：`.cursor/rules/jarvis_workflow.mdc` + `jarvis_python_style.mdc` + `jarvis_security.mdc`
- **当前迭代 design doc**：`docs/PROMPT_REFACTOR_PLAN.md`（P0+20-β.0 完整设计 / 11 节 / 9 风险预案）
- **上轮 design doc**：`docs/NERVE_SPLIT_PLAN.md`（P0+19 完整设计，保留作历史参考）

---

*本文件由 Agent 维护。每次完工先改本文件状态，再往 archive 顶部追加详细段。*
