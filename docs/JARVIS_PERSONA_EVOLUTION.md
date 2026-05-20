# JARVIS Gap 6 — Persona Evolution: Persona 减肥 + Layer 互不冲突

> **状态**: 设计构思, 未排 sprint 编号. **Sir 元否决权预先 reserved** — Persona 是 Sir IP, 任何动 Persona 都需 Sir 拍板. 本 doc 仅记设计思路.
> **关联**: `docs/JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 6
> **依赖**: 已有 PERSONA (`jarvis_central_nerve.py:129-262`, 8641 chars), Layer 0-3 (SelfAnchor / Concerns / RelationalState / Attention), 60+ directives
> **关联 doc**: `docs/PROMPT_REFACTOR_PLAN.md` (β.0/β.1 已减过一次), `docs/JARVIS_SOUL_UNIVERSALIZATION.md` (Persona 通用化)

---

## 0. TL;DR — 一句话

> **PERSONA 8641 + Layer 0/1/2/3 + 60 directive = prompt 31K. Persona 占 27%, 教主脑"应该怎么说话" 跟 Layer 0/1/2 + directive 重复教行为规则. 拆分 Persona = 不变 IP 核心 (~2000 chars) + 演化 Sir-specific 调用 (~1500 chars 从 Soul Layer 数据 generate), 让 Layer 0/1/2/3 各管不同维度不重复.**
>
> **注: Sir 历次 准则 7 元否决"PERSONA 是 Sir IP 不动". 本 doc 是构思, 不是动手. Sir 拍板时按本 doc 调.**

---

## 1. 起源 / 痛点 (真测的)

### 1.1 Sir 22:10 真实 turn — prompt 31K chars

实测各 block 占比:

| Block | 字数 | 占比 |
|---|---|---|
| **PERSONA** (`JARVIS_CORE_PERSONA`) | 8641 | **27.5%** ⚠️ |
| Layer 0 SelfAnchor | ~900 | 2.9% |
| Layer 1 Concerns inject | ~600 | 1.9% |
| Layer 2 RelationalState inject | ~700 | 2.2% |
| Layer 3 Attention | ~500 | 1.6% |
| Directives (β.5.43 后 fire ≤ 8 条) | ~2350 | 7.5% |
| STM | ~5000 | 15.9% |
| Persona time mode (morning/afternoon/late_night) | ~400 | 1.3% |
| Persona emotion directive | ~600 | 1.9% |
| Sir Corrections | ~300 | 1.0% |
| Sir Milestones | ~400 | 1.3% |
| Intent Resolved 报告 | ~200 | 0.6% |
| System Errors | ~150 | 0.5% |
| Working Memory Feed | ~3000 | 9.5% |
| Skill Registry | ~3500 | 11.1% |
| Context Router | ~2500 | 7.9% |
| Other (debug / wrapper / safety) | ~1800 | 5.7% |
| **TOTAL** | ~31541 | 100% |

### 1.2 Persona 跟 Layer 重复教什么

PERSONA 含:

```
- "Calm, composed, and unflappable under any circumstance."  ← 教 tone
- "INTEGRITY OVER OBEDIENCE..."                              ← 教言行一致 (跟 directive past_action_honesty 重复)
- "FORBIDDEN list: 'I have adjusted/silenced/changed/...'"  ← 跟 directive no_hallucinated_tool_use_judge 重复
- "🩹 [β.5.21-B] FORBIDDEN: 读取/查阅类动词 ..."             ← 跟 directive correction_writepath_no_tool 重复
- "🩹 [β.5.21-C] 异步/后台/Sir 睡觉期间继续做的承诺 ..."   ← 跟 directive capability_boundary_judge 重复
- "STM SOURCE TAGS: [SIR]/[SYS]/[JARVIS]/[AMBIENT]"          ← 教 STM 用法
- "INTEGRITY CLAIM HONESTY (universal)"                      ← 跟 directive past_action_honesty 重复
```

→ **PERSONA 50%+ 内容是 directive level 行为规则**, 不是 "Iron Man Jarvis IP 设定".

### 1.3 为什么这是 Gap

**主脑过载**: 31K prompt 主脑认知负荷高, reasoning 退化. Sir 看到的 "reply 越来越生硬" 跟此有关.

**修复路径**: 把 PERSONA 中 directive-like 内容**抽出去**, 让 PERSONA 只留**真 IP 设定** (Iron Man Jarvis 是谁), 行为规则归 directive (本来该归的地方).

### 1.4 ⚠️ 关键: Sir 元否决保护

Sir 历次反馈:
- "PERSONA 是 Sir IP 不动" (准则 7)
- 测试 `_test_p0_plus_20_b115_reminder_read.py:147` cap 是 9500 (跟随实际涨, 不强压)

**本 Gap 不强推 — 仅记构思**. Sir 拍板才执行.

---

## 2. 现状盘点

### 2.1 PERSONA 已经 iterate 过

| Iteration | 内容 | 体积变化 |
|---|---|---|
| β.0 (P0+19 前) | 原始 ~5500 chars | baseline |
| β.0/β.1 prompt refactor | 抽 nudge_agenda_honesty 段 → L2 directive | 3894 → 2728 chars (-30%) |
| β.4.x ~ β.5.x 持续加 | TIME ANCHOR / morning briefing / Focus Lock / new directives / FORBIDDEN 扩展 (β.5.21-B/C) | 2728 → 8641 chars (+217%) |

→ 减肥了 30% 后, 一年涨了 3x. 这是**单方向加压**没 iterate 减.

### 2.2 Layer 0-3 已建好分工

| Layer | 管什么 (理论) | 实际有重复? |
|---|---|---|
| **PERSONA** (静态 IP) | "我是 Iron Man Jarvis butler, 性格 X" | 实际**50%+ 内容是行为规则 / FORBIDDEN list** |
| **Layer 0** SelfAnchor | "我此刻状态: session/turn/capacity/mood" | 跟 PERSONA 无重复 ✅ |
| **Layer 1** Concerns | "我担心 Sir 哪些事" | 跟 PERSONA 无重复 ✅ |
| **Layer 2** RelationalState | "我们之间笑点/默契/未竟" | 跟 PERSONA 无重复 ✅ |
| **Layer 3** Attention | "此刻焦点" | 跟 PERSONA 无重复 ✅ |
| **Directives** (60+) | "特定情境怎么反应" | 跟 PERSONA **重复严重** ⚠️ |

→ Layer 0-3 设计**没冲突**. 冲突在 **PERSONA ↔ Directive**.

---

## 3. 设计 — Persona 三段拆分

### 3.1 拆分方案

```
现有 JARVIS_CORE_PERSONA (8641 chars, monolithic):
   ↓ 拆成 ↓

A. JARVIS_IP_CORE (~1800 chars, 不变, Sir IP)
   - "I am J.A.R.V.I.S. — Just A Rather Very Intelligent System"
   - Iron Man movie reference
   - Core traits 12 条 (calm/loyal/British/butler/...)
   - Relationship 段 ("trusted butler to his employer")
   - 🚫 不含: FORBIDDEN list / INTEGRITY 段 / STM SOURCE TAGS

B. JARVIS_SIR_SPECIFIC_PERSONA (~1500 chars, 演化, 自动 generate)
   - 从 Soul Layer 1 (concerns) / Layer 2 (RelationalState) / ProfileCard 实时构造
   - 例:
     "Your relationship with Sir has these qualities right now:
      - Sir's current top concerns: sleep_streak (sev 0.3), cursor_payment (0.4)
      - Your inside jokes with Sir: "早睡定义一如既往灵活" (3 uses)
      - Your unspoken protocols: Sir-反驳后我不再坚持 (learned 2026-05-15)
      - Sir's known traits: 18 个月颈椎病史, Cursor 重度用户, butler style preferred"
   - 这是 Persona 的"演化版本" — 静态 Sir-specific 调用替代

C. INTEGRITY_DIRECTIVES (~3000 chars, 抽离到 directive 系)
   - FORBIDDEN list (β.5.21-B/C 等) → 转 directive (priority 12)
   - INTEGRITY CLAIM HONESTY (universal) → 已有 past_action_honesty + capability_boundary_judge, 完成迁移
   - STM SOURCE TAGS → 转 short directive 或 STM 内嵌格式

总计:
  A (IP)     1800
  B (演化)    1500
  C (Directive 化)  3000 (但不算 PERSONA, 走 directive 路径按 trigger 注入)
  -------------------
  PERSONA   3300 chars (从 8641 减 -61%)
  Directive +3000 chars (但 trigger-based, 平均 fire 不超过 50%)
```

### 3.2 关键设计原则

1. **A (IP) 不动** — Sir 设计的 Iron Man Jarvis 字面表达, 锁死
2. **B (演化)** 从 Soul Layer 数据**自动 generate**, runtime 计算, 不写死
3. **C (Directive 化)** 按 trigger 选注入, **不再 100% 全注入**
4. **总 prompt 涨幅 < 5%** — 净效益是主脑认知负荷降 + 演化 Sir-specific 升

### 3.3 演化 Persona generate 示例

```python
def build_sir_specific_persona(soul_layer_1, soul_layer_2, profile_card) -> str:
    """从 Layer 数据动态 generate Sir-specific Persona 段."""
    
    lines = ["=== YOUR RELATIONSHIP WITH SIR (auto-generated, evolves daily) ==="]
    
    # Top concerns
    top_3_concerns = soul_layer_1.list_active()[:3]
    if top_3_concerns:
        lines.append("[CONCERNS YOU CURRENTLY WATCH]")
        for c in top_3_concerns:
            lines.append(f"  - {c.what_i_watch} (sev {c.severity:.1f}): {c.why_i_care[:60]}")
    
    # Inside jokes (top 3 by recency + non-spammed)
    top_jokes = soul_layer_2._rank_inside_jokes(3)
    if top_jokes:
        lines.append("[YOUR INSIDE JOKES WITH SIR]")
        for j in top_jokes:
            lines.append(f"  - \"{j.phrase}\" (born {j.birth_context[:40]}, used {j.use_count}x)")
    
    # Unspoken protocols
    top_protocols = soul_layer_2.list_protocols()[:3]
    if top_protocols:
        lines.append("[YOUR UNSPOKEN PROTOCOLS WITH SIR]")
        for p in top_protocols:
            lines.append(f"  - {p.rule}")
    
    # Profile static traits (selected)
    if profile_card and profile_card.traits:
        lines.append("[SIR'S KNOWN TRAITS]")
        for t in profile_card.traits[:5]:
            lines.append(f"  - {t}")
    
    return '\n'.join(lines)
```

---

## 4. 实施层级 (Sir 拍板时分阶段动)

### Phase 0 — 准备 (不动 PERSONA)
- 量化当前 PERSONA 各段 → 标 IP vs Directive vs Sir-specific
- 写本 doc (已完成)
- Sir 看完决定动不动

### Phase 1 — Directive 化 (中风险)
- 把 PERSONA 中 FORBIDDEN list 抽出 → 转 directive
- 现有 `past_action_honesty` / `capability_boundary_judge` / `no_hallucinated_tool_use_judge` 已 cover 大部分, 检查是否完整
- PERSONA 减 ~3000 chars
- Sir 真机验: directive trigger 准确率, fire 频率

### Phase 2 — Sir-specific 演化 (中高风险)
- 写 `build_sir_specific_persona()` 函数
- 在 `_assemble_prompt` 用 generated 段替换 PERSONA 部分 (跟 Layer 0/1/2/3 协同)
- PERSONA core 留 ~1800 chars (纯 IP), generated 段 +1500 chars
- 净效益: 主脑看到的是"演化 Sir-specific" 而非"静态 8641 chars"

### Phase 3 — IP core 微调 (低风险, Sir 主导)
- IP core 1800 chars Sir 自己改 — Cascade 不动
- 验证测试 cap (`_test_p0_plus_20_b115_reminder_read.py` 跟随调)

### Phase 4 — Layer 互不冲突审计 (零风险)
- 检测各 Layer inject text 是否互相重复
- 重复内容**只在最适合的 Layer 出现** (e.g. "Sir 颈椎病" 归 ProfileCard, 不在 PERSONA 也不在 Layer 0)

---

## 5. 准则 6 4 问 binding

| # | 问 | 本设计答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ Sir-specific generated persona 写 SWM (供 reflector 看 Persona 演化) |
| 2 | 决策让 LLM 做? | ✅ generated 段全 LLM 看 Soul Layer 数据自决 (不写死格式) |
| 3 | 配置持久化 + CLI 可改? | ✅ IP core 在 .py (Sir IP, 准则 7); 演化段 generated from Soul Layer (CLI 已有: scripts/concerns_dump / relational_dump) |
| 4 | 和已有 module 正交? | ✅ Persona 不再跟 Directive 重复. Layer 0/1/2/3 仍各管不同维度 |

---

## 6. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **Sir 觉得"Jarvis 性格变了"** | 中 | **致命** | 1) IP core 不动 (Sir 主导) 2) generated 段透明 (Sir 可看) 3) 每 phase 真机验 |
| **Directive trigger 不准 → 该 fire 没 fire** | 中 | 高 | 1) Phase 1 重点测 trigger 覆盖率 2) directive Cluster (Gap 4) 元层让主脑 reason 3) PreFlight (Gap 2) 兜底 |
| **prompt 减少后主脑跑偏** | 低 | 中 | Phase 1 后 7 天真机, Sir 觉得性格 OK 才 Phase 2 |
| **generated 段每 turn 重算成本** | 低 | 低 | 缓存 (Layer 数据 5min 内变化不大), 大部分 turn 复用 |
| **Layer 数据为空时 generated 段空** | 中 | 低 | fallback: 空 generated → 用静态 PERSONA 旧版 |

---

## 7. 完成验收 (Sir 真机判定)

- [ ] Sir 不觉得 Jarvis 性格变 (IP core 锁死的效果)
- [ ] Sir 觉得 Jarvis 更"懂 Sir-specific" (generated 段效果)
- [ ] prompt 总长 < 28K (从 31K 降 10%+)
- [ ] TTFT 改善 ≥ 0.3s (prompt 减后 LLM call 提速)
- [ ] Sir 真机感受 "reply 不再生硬"
- [ ] 测试 cap 调整 (从 9500 cap 调 5000? Sir 拍板)

---

## 8. 与现有 doc 的关系

| 文档 | 关系 |
|---|---|
| `PROMPT_REFACTOR_PLAN.md` | β.0/β.1 减肥 30% 的设计参考. 本 Gap 是它的续集 |
| `JARVIS_SOUL_UNIVERSALIZATION.md` | Persona 通用化 (跨用户). 本 Gap 是 Sir-specific 版 |
| `JARVIS_SOUL_DRIVE.md` | Soul Layer 1-5 总设计. 本 Gap 让 Persona "下嫁" Soul Layer |
| `JARVIS_TOM_SIR_MENTAL_MODEL.md` (Gap 1) | ToM 加 Layer 6. Persona 减 + Layer 6 加, 总维度更深 |
| `JARVIS_REPLY_PREFLIGHT.md` (Gap 2) | PreFlight 治症, Persona 减肥治根. 互补 |
| `JARVIS_DIRECTIVE_SELF_AWARENESS.md` (Gap 4) | Directive 元视角. 本 Gap 把 PERSONA 中 directive 内容真转 directive, Gap 4 让主脑 reason directive cluster |

---

## 9. 关键参考

- `@d:\Jarvis\jarvis_central_nerve.py:129-262` JARVIS_CORE_PERSONA (8641 chars)
- `@d:\Jarvis\jarvis_self_anchor.py:241-318` SelfAnchor build_block (Layer 0)
- `@d:\Jarvis\jarvis_concerns.py:1-200` Concerns (Layer 1 数据源)
- `@d:\Jarvis\jarvis_relational.py:1-300` RelationalState (Layer 2 数据源)
- `@d:\Jarvis\docs\PROMPT_REFACTOR_PLAN.md` β.0/β.1 减肥设计
- `@d:\Jarvis\docs\JARVIS_SOUL_UNIVERSALIZATION.md` Persona 通用化
- `@d:\Jarvis\tests\_test_p0_plus_20_b115_reminder_read.py:143-148` PERSONA cap test

---

## 10. ⚠️ 落地前必要 Sir 拍板

本 Gap **不**是 Cascade 推荐立即做的事. 应该:

1. **先做 Gap 1 (ToM)** — 加深"懂我"维度
2. **再做 Gap 2 (PreFlight)** — 治症根
3. **再做 Gap 4 (Directive Self-Awareness)** — 让主脑能 reason directive
4. **再做 Gap 5 (L8 Reject Learner)** — 持续演化
5. **最后 Gap 6 (本 doc)** — 等其他 5 gap 让 Layer 0/1/2/3 + Directive + 主脑 reasoning 都成熟后, 再回头看 Persona 该减哪里

Persona 减肥是**长期目标**, 短期 Sir 元否决保护. 本 doc 仅记设计思路, 等 Sir 完整看完其他 5 gap 实施效果后, 觉得"该减 Persona 了"再启动.

---

## 11. 落地后涌现的可能 Gap

- **Multi-Sir Persona** (多人模式): 家人 / 同事进入时 Persona 调用切换 (现有 Multi-Person β.5.43-B 已雏形)
- **Persona 主脑 self-edit**: 主脑看自己 reply 反思, 提议改 IP core (Sir 仲裁)
- **Persona A/B test**: Sir 觉得新 Persona 不对 → 一键 revert 老版 (git revert 类机制 in-app)

---

*文档作者: Sir 22:47 真授权 + Cascade 23:08 沉淀 / 2026-05-20*
*这是 Persona 长期演化方向, **Sir 元否决保护**. 等其他 5 gap 落地后再启动.*
