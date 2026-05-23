# AGENT KICKOFF — Grand Architecture Reshape

> Sir 醒来 / 新 agent 接手 时, **第一份**要看的 doc.
>
> 写于 2026-05-24 00:55, Cascade.

---

## 1. 你在哪一阶段?

JARVIS 大重构 (Grand Architecture Reshape):

```
Phase A (审计) ✅ 完成   — 6000 行 7 doc
Phase B (设计) ✅ 完成   — 1300 行 1 doc (Reshape)
Phase C (Sir 拍板) ⏸ 等 Sir 醒来  ⭐
Phase D (动工) ⏸ 等 Phase C
```

---

## 2. 5 分钟核心信息

### 2.1 Sir 真意 (2026-05-23 23:50 - 2026-05-24 00:00)

> "彻底重构贾维斯, 不仅仅是记忆系统, 所有链路都要一次性重构. 按我的设计思路保持高度可维护性 / 可扩展性, 符合所有设计准则 1-8. 以后添加所有能力都固定在某个架构内新增数据模块, 不动数据耦合和 LLM 决策. 思考链作为 debug 神器, 通过主脑的判决反向追踪到模块最底层的数据获取端. 只要这个架构有持续运转的能力即可, 调整不可避免."

### 2.2 Cascade 答 (2026-05-23 23:55)

不追求 10 年不变, 追求 **5 年内主体稳 + 局部可演化**.

**4 个护城河** (5-10 年不动):
- M1: SWM 唯一中介
- M2: 标准 Action 协议
- M3: **Lineage Trace** ⭐ (Sir 这次新立)
- M4: vocab 持久化 (准则 6.5)

**4 条铁律** (加新能力的硬约束):
- R1: 新 sensor/effector 只 publish SWM
- R2: 新决策必须经 LLM
- R3: 新行为必须 vocab + CLI + L7 propose
- R4: 新数据必须经 `Hub.write_*()` 单入口

### 2.3 Sir 委托 Cascade 拍板 (2026-05-24 00:05)

> "是否拆分你来决定. 3-brain 彻底先放弃, 后面等贾维斯地基牢固再装配手脚的时候需要这种长的工作流程再重构. Q3 Q4 看不懂, 按我们的设计思路听你的."

Cascade 拍板 4 项:
- Q1: jarvis_enhanced.py 拆 4 file
- Q2: 3-brain 移 `_legacy/3_brain_attempt/`
- Q3: central_nerve.memory_gateway 改用 MemoryHub
- Q4: cross_session_callback 保留 (Phase A 误判, 0 KB 是消费完正常)

详见 `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §1.

---

## 3. Sir 醒来 5 步 → 进 Phase D 动工

### Step 1: 阅读 (~20 min)

1. 本 doc (kickoff)
2. `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §1-§3 (决议 + 架构骨架, ~15 min)
3. `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §6.2 (M1 详细, ~5 min)
4. (可选) `AGENTS.md` 准则 1-8 refresh

### Step 2: 拍板 4 项决议 (~5 min)

打开 `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` §11.2:

| 决议 | Cascade 提案 | Sir 选 |
|---|---|---|
| Q1 | jarvis_enhanced.py 拆 4 file | accept / override |
| Q2 | 3-brain 移 `_legacy/` + central_nerve.run() 删 | accept / override |
| Q3 | central_nerve.memory_gateway → MemoryHub | accept / override |
| Q4 | cross_session_callback 保留 (真用跨进程 IPC) | accept / override |

### Step 3: 跟 Cascade 说

```
Cascade, 我看完了, Q1-Q4 全 accept (或: Q2 改成 ...).
开始动工 M1.
```

### Step 4: Cascade 按 M1 详细步骤执行 (1-2 周)

§6.2 Step 1.1-1.7:
1. 新建 `jarvis_lineage.py` (~300 行)
2. 扩 `ConversationEventBus.publish` 加 `evidence_chain`
3. PromptBlock dataclass 新建
4. chat_bypass.stream_chat 末尾 record_decision
5. 新建 `scripts/lineage_dump.py` CLI
6. 新建 `memory_pool/lineage_config.json` + `lineage.jsonl`
7. (后置) `LineageReflector` L7 propose

每 Step 独立 commit, pytest 前置.

### Step 5: M1 完成 → Sir 真测

```powershell
# Sir 真测 1 turn
python scripts/lineage_dump.py --reply-id=<latest>

# 看到完整 evidence chain
# 反向追溯: reply → 30+ block evidence → 6 source row
```

如 Sir 真测 OK → 进 M2.
如 Sir 不满意 → revert M1, 调整设计.

---

## 4. Phase D 8 个 milestone 总路线

| M# | 任务 | 周期 | 风险 | 验收 |
|---|---|---|---|---|
| **M1** ⭐⭐⭐ | Lineage Trace 基础设施 | 1-2 周 | 低 | `lineage_dump.py --reply-id=X` 能反向追溯 |
| **M2** | MemoryHub 演化 | 1 周 | 中 | `central_nerve.memory_gateway = MemoryHub` |
| **M3** | 死代码 + 同名 class + 3-brain → `_legacy/` | 1 周 | 低 | jarvis 启动正常, pytest pass |
| **M4** | 5 套时间承诺合并 → PromiseLog 单源 | 2 周 | 高 | data migration + Sir 真测 1 周 |
| **M5** | 3 决策路径整合 | 1 周 | 中 | IntentResolver 唯一 LLM judge |
| **M6** | NERVE_SPLIT god object 拆分 | 4 周 | 高 | 4 大 file 都 < 1500 行 |
| **M7** | PromptBuilder polymorphic | 2 周 | 中 | STANDARD prompt < 25K char |
| **M8** | 5 audit log 合并 + state 合并 | 3 天 | 低 | mem_audit.jsonl 单源 |

**总周期**: 12-13 周 (~3 个月).

---

## 5. 风险预案

| 时点 | 风险 | 应对 |
|---|---|---|
| M1 完成 | lineage 写盘卡 | benchmark < 1ms; 异步 daemon |
| M3 完成 | 极少数 task 走老 jarvis.run() | 真测 24h 抓 routing 漏 |
| M4 中 | data migration 错误丢承诺 | dry-run + 1 周 A/B + auto backup |
| M6 中 | god object 拆破启动 | 1 周 1 file + 真测 1 天 |
| 任意时点 | Sir 真测打回 | revert milestone 整段 |

---

## 6. Sir 元否决权 (准则 7)

任何冲突 Sir 拍板优先, 章程让步.

如果 Sir 看完 Reshape doc 觉得方向不对:
- ✅ 喊停 → Cascade 立刻停, 不 hedge 不反劝
- ✅ 调整某 milestone → Cascade 改设计 + 重 review
- ✅ 推翻某 Q1-Q4 拍板 → Cascade 走新方向

Sir 是项目唯一仲裁者.

---

## 7. 关键 doc 索引 (按需查)

| 用途 | doc |
|---|---|
| **入口章程** | `AGENTS.md` (< 400 行) |
| **本 kickoff** | `docs/AGENT_KICKOFF_GRAND_RESHAPE.md` |
| **最终设计书** ⭐ | `docs/JARVIS_GRAND_ARCHITECTURE_RESHAPE.md` (~1300 行) |
| Phase A.1 模块审计 | `docs/JARVIS_AUDIT_CARDS.md` (~3300 行) |
| Phase A.2 数据流 | `docs/JARVIS_DATAFLOW_MAP.md` |
| Phase A.3 storage | `docs/JARVIS_STORAGE_MAP.md` |
| Phase A.4 耦合 | `docs/JARVIS_COUPLING_MATRIX.md` |
| Phase A.5 历史 | `docs/JARVIS_LEGACY_AUDIT.md` |
| Phase A 架构总览 | `docs/JARVIS_ARCHITECTURE_MAP.md` |
| Phase B 设计 (Reshape 简化版) | `docs/JARVIS_PHASE_B_DESIGN.md` |
| 立项书 + LIVE 进度 | `docs/JARVIS_GRAND_REFACTOR.md` |
| 老记忆重构 (archive ref only) | `docs/JARVIS_MEMORY_AND_MUTATION_REFACTOR_v1_archive.md` |

---

## 8. 状态快照

**今晚 Cascade 工作**:
- 写了 9 份 doc, 总计 ~7300 行 audit + 设计
- 8 commit (`b53b751` → `<latest>`)
- 全严格核对准则 1-8 + 6.5 + 4 问 + 递归边界
- 4 项决议自己拍板 (Sir 委托)
- M1-M8 详细实施手册 + 测试 plan + 回滚 plan + 风险预案
- Sir 醒来 5 步进 Phase D 动工

**Sir 不需做的**:
- ❌ 再设计 (全有了)
- ❌ 再 audit (覆盖完了)
- ❌ review 每 commit (pytest + 真测为主)

**Sir 需做的**:
- ✅ 看本 doc + Reshape §1+§6.2 (~25 min)
- ✅ Q1-Q4 拍板 (~5 min)
- ✅ 跟 Cascade 说"动工 M1"
- ✅ 每 milestone 完成 1 天真测

**总 Sir 投入**: 拍板 + 真测 + 元否决权.

---

*Sir 早上好. JARVIS 大重构准备就绪, 等你拍板.*
