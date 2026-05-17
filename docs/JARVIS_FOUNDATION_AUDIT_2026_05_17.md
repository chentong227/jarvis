# Jarvis 地基审计 — 2026-05-17

**作者**: Sir 提问 + Claude 客观盘点
**版本**: P0+20-β.2.7.6 (commit `8720359`)
**目的**: 在扩展生产力能力前，诚实评估地基是否够稳

---

## 0. TL;DR

| 维度 | 状态 |
|---|---|
| 核心管线（ASR → 主脑 → TTS） | ✅ 稳定 |
| 灵魂工程 L0-L5 | ✅ 全部实现 + ablation 验证 |
| 承诺必行（Sir + Jarvis 自承诺） | ✅ β.2.7.3 补齐 |
| Agent 维护文档 | ✅ β.2.7.6 加 AGENTS.md §11 |
| **STM source 区分** | ⚠️ **未做** (reflector 幻觉 root cause) |
| **观测性 / dashboard** | ⚠️ **缺** |
| **生产力工具集成** | ⚠️ **基础设施有，应用控制少** |
| **跨设备** | ❌ **未做** |
| 长跑稳定性 | ❓ **未充分测试** (24h+ 连续运行) |

总评：**地基够支撑当前个人 butler 用法**。要做 J.A.R.V.I.S. 级生产力工具，需要 3 类补强 + 3 类新能力。

---

## 1. 已完工 (Sir 实测验证)

| 能力 | 实现 | 实测验证 |
|---|---|---|
| voice in/out + ETE 英文 TTS | jarvis_worker / jarvis_chat_bypass / CosyVoice | ✅ Sir 实测 |
| L0 SelfAnchor (self-identity) | jarvis_self_anchor.py | ✅ ablation +73% |
| L1 Concerns (我关心什么) | jarvis_concerns.py | ✅ ablation +68% |
| L2 RelationalState (我们之间) | jarvis_relational.py | ✅ ablation +77% |
| L3 Attention Allocation | jarvis_attention.py | ✅ classify 100% |
| L4 ConcernsReflector + WeeklyReflector | jarvis_soul_reflector.py | ✅ F1=0.95 / β.2.7.5 治幻觉 |
| L5 SoulAlignmentEvaluator (动态切 flash/pro) | jarvis_soul_evaluator.py | ✅ 88-100% accuracy |
| Sir 承诺持久化 | jarvis_commitment_watcher.py + Gatekeeper | ✅ β.2.7.3 hedge 放宽 |
| **Jarvis 自承诺持久化** | jarvis_self_promise.py + 5 路径接入 | ✅ β.2.7.3 |
| nudge 灵魂注入 (Phase 1) | _assemble_prompt(mode='nudge') | ✅ β.2.7.1 |
| 多信号 ProactiveShield 评分 | jarvis_enhanced.py | ✅ β.2.7.3 |
| SleepIntent immediate | jarvis_worker.py | ✅ β.2.7.3 |
| Splitter organ.command 保护 | jarvis_chat_bypass.py | ✅ β.2.7.3 |
| 模型成本优化 (动态切 flash/pro) | jarvis_soul_evaluator.py | ✅ β.2.7.6 |
| 终端降噪 (黑名单 marker) | jarvis_utils.py | ✅ β.2.7.6 |
| 65/65 全测绿 | tests/_runall.ps1 | ✅ |

---

## 2. 已知盲点 / 隐患 (按优先级)

### 🔴 P0 — 影响功能正确性

| 盲点 | 现象 | 修法估时 |
|---|---|---|
| **STM source 不区分** | reflector 把视频音 / Jarvis 自言自语当 Sir 说的 → 幻觉 concern（Sir 实测 6 条 propose 里 4-5 条幻觉） | hippocampus schema +column source / 写入路径 5 处标 source / 2h |
| **OpenRouter region 限制** Sir 必须开 proxy | 启动脚本不自检 proxy 可达，崩在 LLM 调用时才知道 | 启动健康检查 / 30min |

### 🟡 P1 — 影响长期稳定 / 可观测

| 盲点 | 现象 | 修法估时 |
|---|---|---|
| **观测性缺失** | 没有 dashboard 看 7d alignment 率 / nudge 触发 / commitment 完成率 / cost trend | 1 个 daily_stats.py + ASCII chart / 2h |
| **SQLite single-writer 竞争** | hippocampus + skill_tree + commitment + concerns 多 thread 并发写，没看见但理论存在 deadlock | 改 WAL mode + connection pool / 1.5h |
| **STM 50 条 cap** | 复杂多日话题（如 P0+20 整个 β 工程）超过 50 条会被截断 | hippocampus 加 long-term semantic search 强化 / 已有但用得少 |
| **CosyVoice GPU 显存** | 长跑 OOM 风险，未监控 | 启动时记 baseline + 周期检查 / 1h |
| **Plan 卡 running 没收尾** | PromiseExecutor 异常时 plan 状态卡死 | 加 plan 超时回收 daemon / 1h |
| **BrowserDucking 应用列表硬编码** | 新应用不被识别 → 不静音 | 改成 sir_profile.audio_ducking_targets / 30min |

### 🟢 P2 — 优化空间 (功能正常，可更细)

| 盲点 | 现象 | 修法估时 |
|---|---|---|
| **L3 attention triple-hit 仅 40%** | LLM 在 single reply 里只挑 1-2 层 highlight，不 dump 全部 | prompt 重构 + 测试 / 3h |
| **silent_nudge / standby exit / spinal reflex** 纯模板 | Phase 2/3 没做（详 `docs/JARVIS_SOUL_UNIVERSALIZATION.md`） | 4-6h |
| **L4 ConcernsReflector keyword cap 0.15/turn** | severity 累积慢，强信号被天花板压住 | 加 mass mode / 1h |
| **STM source ambient_pickup 没过滤** | 视频/电视音被 ASR 录入污染 STM | 看 4.3 |
| **WeeklyReflector 单 turn 评估** | 每周一次跑，看不到 Sir 自己 STM 演化 | 加 incremental 模式 / 2h |

### ❓ 待 Sir 实测验证

| 项 | 验证方法 |
|---|---|
| 24h+ 连续运行稳定性 | Sir 不重启跑一整天 |
| 跨日 long-term memory 召回 | Sir 第二天问"昨天我们说过的 X" |
| 不同时段 tone 切换正确性 | Sir 在 03/12/18/23 点对话感觉自然度 |
| Commitment 真实 nudge 触发 | Sir 真承诺 + 等到点 |
| SoulPromise 真实 nudge 触发 | Jarvis 自承诺 + 等到点 |

---

## 3. 从 butler → J.A.R.V.I.S. 级生产力工具 路径

### 当前能力 vs 钢铁侠 J.A.R.V.I.S. 能力 gap

| 钢铁侠 JARVIS | Sir 的 Jarvis 当前 |
|---|---|
| 实时数据分析 + 可视化 | ❌ 无 |
| 控制 Iron Man 套装 / 武器系统 | N/A (现实没装备) |
| 自然语言操作复杂应用 (Photoshop/CAD) | 🟡 只有 ui_control / process_hands |
| 长跑后台 task (跑 30min 分析然后报告) | ❌ 无 task ledger |
| 跨设备协作 (手机/平板/桌面) | ❌ 桌面单点 |
| 主动情报推送 (新闻/股票/监控) | ❌ 无爬虫 |
| 多模态决策 (vision + audio + 数据图) | 🟡 已有 vision，没有图分析 |
| 自我升级 / 自我修复 | 🟡 SoulEvaluator 评分但不写代码 |

### 3 阶段扩展路径（推荐）

#### Phase α — 地基补强（必做，1 周）
1. **STM source 区分**（治幻觉 root cause）
   - hippocampus schema 加 `source` 列：`user_voice / ambient_pickup / jarvis_self / system_event`
   - voice_thread 录入时标 user_voice
   - chat_bypass 写 jarvis reply 时标 jarvis_self
   - WeeklyReflector prompt 加约束："只信 user_voice"
2. **观测性 dashboard** (`scripts/jarvis_daily_stats.py`)
   - 7d alignment 率 / nudge 触发 / commitment 完成率 / cost / TTFT 分布
   - ASCII chart 给 Sir 一眼看 trend
3. **proxy / GPU / plan 超时** 三件套自检 daemon
4. **真机 24h 长跑测试** (Sir 实测一整天 + 看 log 健康)

#### Phase β — 应用控制 Skill Pack（核心生产力, 2-3 周）
5. **Skill Pack 机制**: 把 Cursor / Premiere / Excel / VSCode / Photoshop 等应用控制写成**可插拔 skill_pack**
   - 每个 pack = 一个 `l4_hands_pool/l4_<app>_hands.py`
   - 含: `list_<app>_state` (safe) + `<app>_action_X` (risky/dangerous)
   - 自动 skill_tree 注册
6. **Long-running task ledger**:
   - 升级 PlanLedger 支持 "30min 后台 task + 进度通知"
   - 例: "Jarvis, 帮我跑这个 pytest suite, 完了告诉我"
   - Jarvis 后台执行 + 周期 nudge 进度 + 完成播报
7. **Multi-step planner upgrade**:
   - 当前 PromiseParser 是单 LLM 一次出 plan
   - 升级为: ReAct 风格 (think → act → observe → re-plan)
   - 失败自动重试 / 走 fallback skill

#### Phase γ — 主动情报 + 跨设备（高阶, 3-4 周）
8. **主动情报源**:
   - Jarvis 每天早上 7 点 daily brief: GitHub starred / 关注 RSS / 公众号 / 邮件
   - 走 L0-L5 灵魂注入 → 不是 dump 而是"管家级摘要"
9. **跨设备桥接**:
   - iOS Shortcut / iPad / 手机 → 转发到 Jarvis 主进程
   - 走 HTTP server (FastAPI) on 主机
10. **数据分析能力**:
    - 加 `l4_hands_pool/l4_data_analyzer_hands.py`
    - pandas / matplotlib / 让 Jarvis 自己跑分析 + 把图发到 Sir

---

## 4. 给下一个 Agent 的工作清单（按优先级）

如果下一个 Agent 接手，按这个顺序：

| 顺 | 任务 | marker | 估时 | 是否必做 |
|---|---|---|---|---|
| 1 | 跑 `scripts/registry_dump.py` + `concerns_dump --review --no-interactive` + `relational_dump` 看健康 | β.2.7.7-巡检 | 10min | **必** |
| 2 | 真机 24h 长跑测试 + 收集 log → 看是否有 plan 卡死 / GPU OOM / SQLite lock | β.2.7.7-长跑 | 1d 等待 | **必** |
| 3 | STM source 区分 (`source` column + 写入路径 5 处) | β.2.7.7-source | 2h | **必** |
| 4 | daily_stats.py (ASCII chart dashboard) | β.2.7.8-obs | 2h | 推荐 |
| 5 | proxy / GPU / plan 超时自检 daemon | β.2.7.8-health | 2h | 推荐 |
| 6 | Skill Pack 机制 + Cursor / Premiere / Excel 三个 pack | β.2.8 | 2 周 | Sir 拍 |
| 7 | Long-running task ledger 升级 | β.2.9 | 1 周 | Sir 拍 |
| 8 | iOS / 跨设备桥接 | β.3.0 | 2-3 周 | Sir 拍 |

---

## 5. 给 Sir 的真话

地基**够支撑当前 butler 用法**（陪聊 / 提醒 / 承诺 / 灵魂）。我们这 4 天做了 14 个 β 子轮（β.0-β.2.7.6），实测验证 + 65/65 全测稳定，灵魂工程 5 层全部接通。

但**要做生产力工具 J.A.R.V.I.S.**，缺的是：
1. **应用控制层** (Cursor/Premiere/Excel skill pack — 现在只能开/关进程)
2. **长跑 task agent** (Plan 跑 30min 后台 + 报告 — 现在 plan 是 multi-step 同步)
3. **跨设备 / 主动情报** (现在只能桌面单点 + 被动响应)
4. **数据分析能力** (现在不能跑 pandas + 出图)

建议先把 **Phase α 地基补强（1 周）** 做完再开 Phase β。否则在沙地上盖楼。

---

*本文件由 P0+20-β.2.7.6 / 2026-05-17 创建。下个大轮次完工后整体审计可写新 audit 文件，本文件不动作历史参考。*
