# JARVIS Dynamic Map & Self-Debug — 动态架构地图 + 思考脑自我调试 (Complete Design)

> **Sir 2026-05-29 01:30 真意 anchor / SOUL Phase 5 / 准则 6 信任 LLM + 动态提取不写死**
>
> **0 代码改动前先写本 doc. Sir 拍板"直接设计一套 design 然后按 design 推进, 需要测试就镜像".**
> **Sir 额外要求: 动态地图保持 agent-readable, 方便 agent 快速理解 Jarvis 架构.**

---

## 0. 元信息

- **状态**: 设计完成, 按 design 推进中
- **缘起**: governor Phase 1-4 完工后, Sir 问 Phase 5 (self-debug). 核对 `JARVIS_ARCHITECTURE_MAP.md` 发现严重过时 (2026-05-23 snapshot, 漏 28 模块 + 思考脑 6957 行核心完全缺失 + β.6/心声/镜像 0 提及). Sir 洞察: "有没有动态地图的可能性?"
- **章程定位**: SOUL Phase 5 — "自我认知" 元架构从"我是谁"(Layer 0 SelfAnchor) 延伸到"我的身体构造"(架构自我认知)
- **复用**: AST 零副作用扫描 pattern 借鉴 `jarvis_skill_registry.py:1414 SkillScanner` (但维度正交: SkillScanner 扫 l4 hands command, 本设计扫模块架构)

---

## 1. TL;DR — 一句话

> **动态地图不是文档, 是 Jarvis 认知自己架构的活组件 (自我认知能力). `jarvis_module_scanner.py` 每次启动 AST 扫自己所有 jarvis_*.py → `memory_pool/module_map.json` (活数据). 主用途: 思考脑 self-debug 读它 (遇异常知道改哪个 vocab); 副产品: 渲染 agent-readable md 替代过时手 map. 文档只是顺便, 核心是 Jarvis 先认知自己才能 debug 自己。**

---

## 2. 定位 — Jarvis 架构的一部分, 不是独立文档 (Sir 2026-05-29 澄清)

### 2.1 双重身份

```
jarvis_module_scanner.py (Jarvis 真模块, 非 dev 工具)
  │ 启动 / git HEAD 变 / 定期 → AST 扫自己所有 jarvis_*.py
  ▼
memory_pool/module_map.json (活数据, 像 concerns.json 一样)
  ├─ 主用途: 思考脑 self-debug 读 (Phase 5 真意 — 认知自己→调自己)
  └─ 副产品: 渲染 docs/JARVIS_ARCHITECTURE_MAP_AUTO.md (agent/人 读)
```

### 2.2 类比 — 动态地图是"认知自己"的活记忆

| Jarvis 已有 | 认知对象 | 活数据 |
|---|---|---|
| `concerns.json` | 认知 **Sir** (我担心 Sir 什么) | 思考脑/主脑读 |
| `relational_state.json` | 认知 **我们关系** | 读 |
| Layer 0 SelfAnchor | 认知 **我是谁/此刻状态** | inject prompt |
| **`module_map.json`** ⭐ | 认知 **我的架构 (身体构造)** | 思考脑 self-debug 读 |

动态地图就像 concerns 一样是 Jarvis 一份活认知 — 只不过 concerns 认知 Sir, 动态地图认知**自己的身体 (架构)**。

### 2.3 为什么必须是活组件 (准则 6 印证)

`JARVIS_ARCHITECTURE_MAP.md` 手维护, Sir 6 天没更新就漏 28 模块 + 思考脑核心。**静态手维护必然过时**。做成活组件:
- 永远新鲜 (每次启动重新认知自己)
- 真服务 self-debug (思考脑读活数据, 不读过时 doc)
- 是"自我认知"元架构的自然延伸

---

## 3. SOUL lineage — 自我认知元架构延伸

| 元架构 (Sir 三元之一) | 现状 | 本设计延伸 |
|---|---|---|
| 自我认知 | Layer 0 SelfAnchor (我是谁/uptime/mood) | **module_map (我由哪些模块组成/怎么运作/改哪调自己)** |

呼应 SOUL Phase 1-4 (governor) 的"思考持续唤醒" + 本 Phase 5 的"自我认知架构层"。governor 让思考脑能 think + govern, 本 design 让思考脑能 **认知自己 + debug 自己**。

---

## 4. 架构设计 (6 层)

### Layer 1 — `jarvis_module_scanner.py` (AST 零副作用扫描)

借鉴 `SkillScanner` 的 AST 零副作用 pattern (不 import 模块, 纯静态解析, 防点火副作用)。

每个 `jarvis_*.py` 提取 (demo 已验证可行):
- `lines` — 行数
- `purpose` — module docstring 首行 (94% 模块有)
- `classes` — ast.ClassDef 名列表
- `vocab_files` — regex `memory_pool/([\w/]+\.json)` 引用
- `doc_refs` — regex `docs/(JARVIS_\w+\.md)` 引用
- `depends_on` — ast.ImportFrom `jarvis_*` 模块
- `depended_by` — 反向依赖 (谁 import 我, 二次遍历算)
- `layer` — 启发式分类 (docstring marker / filename pattern → sensor/memory/soul/thinking/integrity/...)

### Layer 2 — `memory_pool/module_map.json` (活数据)

```json
{
  "_meta": {
    "schema": "module_map", "generated_at": "ISO",
    "generated_by": "jarvis_module_scanner.py", "git_head": "hash",
    "_warning": "AUTO-GENERATED — do not hand-edit. Scanner refreshes."
  },
  "modules": {
    "jarvis_inner_thought_daemon": {
      "file": "...", "lines": 7399,
      "purpose": "Inner Thought Daemon — 持续思考层",
      "classes": ["InnerThought", "InnerThoughtDaemon"],
      "vocab_files": ["inner_thought_pacing_vocab.json", "..."],
      "doc_refs": ["JARVIS_BETA6_UNIFIED_THINKING.md", "..."],
      "depends_on": ["jarvis_central_nerve", "..."],
      "depended_by": ["jarvis_nerve", "..."],
      "layer": "thinking",
      "common_issues": [],   // L7 reflector 补 (runtime 观察)
      "fix_hints": []        // L7 reflector 补
    }
  },
  "stats": {
    "total_modules": 118, "with_docstring": 111,
    "orphans": [...], "circular_deps": [...], "no_docstring": [...]
  }
}
```

### Layer 3 — `docs/JARVIS_ARCHITECTURE_MAP_AUTO.md` (agent-readable, Sir 强调)

渲染规则 (agent-optimized, 让 agent 30 秒懂架构):
- 顶部: ⚠️ AUTO-GENERATED + generated_at + git_head + "手 map 已 deprecated, 看本 doc"
- **agent 快速导航** section: 5 核心枢纽 (按 lines 排) + 各 layer 模块数
- 按 layer 分组模块表: name | lines | purpose | vocab | doc
- 依赖图 (text-based, 核心模块 depends_on/depended_by)
- **架构治理** section: orphans (无人 import) / circular_deps / no_docstring (待补)

### Layer 4 — 思考脑 self-debug inject (Phase 5 主用途)

- `_collect_evidence` 加: 按当前异常 topic (复用 F3 topic_distribution) retrieve 相关模块 self-knowledge
- 例: topic_distribution 显 "ProactiveCare 重复 22 次 🍂 AGED" → retrieve `jarvis_proactive_care` module info (vocab: proactive_care_cooldown_vocab.json)
- `_build_prompt` 加 `[MODULE SELF-KNOWLEDGE — relevant to current concern]` block:
  ```
  [MODULE SELF-KNOWLEDGE]
    Concern 'ProactiveCare 重复' relates to module: jarvis_proactive_care
      purpose: 主动关心引擎
      tunable vocab: proactive_care_cooldown_vocab.json
      → if this behavior is wrong, you may propose_vocab_adjustment
  ```

### Layer 5 — `propose_vocab_adjustment` actionable (真 self-debug)

- 思考脑 actionable=`propose_vocab_adjustment:<vocab_file>:<key_path>:<value>`
- `_do_propose_vocab_adjustment` helper: 写 review queue → Sir 拍板 → 真改 vocab
- **复用 E5 红线**: 不能改 INTEGRITY (claim_*/evidence_*) / safety (health_probe/commitment/chronos) vocab
- **复用 F5 review pattern**: propose → review → Sir activate/reject
- sal>=0.8 gate (改自己配置要高确信)

### Layer 6 — L7 reflector (runtime 行为补充)

- 定期 re-scan (git HEAD 变 or 1h) — 保持 module_map 新鲜
- runtime log 观察 "哪个模块常出哪种异常" → LLM propose 补 `common_issues` / `fix_hints` → review queue → Sir 拍板

---

## 5. 准则 6 三维耦合

| 维度 | 体现 |
|---|---|
| **数据强耦合** | module_map.json 活数据, 思考脑/主脑/dashboard 都读同一份 |
| **行为弱耦合** | scanner 只 publish module_map, 不决策. 思考脑读它自决 self-debug |
| **决策集中 LLM** | 思考脑 LLM 自决"这异常关联哪模块 + 改哪 vocab", python 只提供 retrieve + enforce 红线 |

## 6. 准则 6 — 新 module 4 问筛查

| # | 问 | 答 |
|---|---|---|
| 1 publish SWM? | ✅ scan 完 publish 'module_map_refreshed' event |
| 2 LLM 决策? | ✅ self-debug 调法 LLM 自决, scanner 只提供事实 (lines/vocab/deps) |
| 3 持久化+CLI? | ✅ module_map.json + scripts/module_map_dump.py (list/show/orphans/refresh) |
| 4 正交? | ✅ 跟 SkillScanner 正交 (技能 vs 架构维度). 复用其 AST pattern 不重复造 |

---

## 7. 分 Phase 实施

| Phase | 内容 | 估 | 镜像验证 |
|---|---|---|---|
| **P1** | `jarvis_module_scanner.py` (AST 扫) + module_map.json + 渲染 AUTO.md + CLI + testcase | ~250 行 | scan 真跑 118 模块 + md 生成 |
| **P2** | 思考脑 self-knowledge inject (Layer 4, retrieve + prompt block) + testcase | ~120 行 | 镜像看思考脑 prompt 含 module knowledge |
| **P3** | `propose_vocab_adjustment` actionable (Layer 5, 复用 E5 红线 + F5 review) + testcase | ~100 行 | 镜像看思考脑真 propose vocab 改 → review queue |
| **P4** | L7 reflector (Layer 6, re-scan + runtime 行为补充) + testcase | ~150 行 | 长跑看 common_issues 自动补 |

**P1 是地基** (活地图本身, 解决过时 map 痛点 + agent-readable). P2-P4 是 self-debug 闭环。

---

## 8. 测试 phase

- **P1**: scan 准确性 (lines/docstring/vocab/deps 对) + md 渲染 + orphan/circular 检测 + CLI smoke + 镜像 (真扫 118)
- **P2**: retrieve 按 topic 命中模块 + prompt block 渲染 + 镜像 (思考脑 prompt 含 knowledge)
- **P3**: propose_vocab_adjustment parse + 红线 reject (INTEGRITY/safety) + review queue 写 + 镜像
- **P4**: re-scan 触发 (git HEAD 变) + runtime 行为 propose + review

---

## 9. 风险 + 回滚

| 风险 | 缓解 |
|---|---|
| AST parse fail (语法错模块) | try/except per-module, fail 记 error 不崩全 scan |
| scan 慢 (118 模块) | demo 实测 < 1s. cache + 仅 git HEAD 变 re-scan |
| 思考脑改错 vocab | 全走 review queue + Sir 拍板 (不直 mutate) + E5 红线 |
| module_map inject token 爆 | 只 retrieve 当前异常相关模块 (不全 inject 118) |
| docstring 质量参差 | 7 个无 docstring 模块 → 架构治理 section 列出待补 |

每 Phase 独立 commit, 可单独 revert。scanner 是只读 (AST), 0 副作用。

---

## 10. 与现有原则一致性

- **准则 1 高效**: scan < 1s + cache, 不影响 TTFT
- **准则 5 言出必行**: self-debug 改 vocab 走 review (不假装改了), 红线护 INTEGRITY
- **准则 6 拒绝硬编码**: 动态提取替代手 map, L7 reflector 自动维护
- **准则 7 Sir 元否决**: vocab 改全 review queue, Sir CLI 可拒
- **准则 8 优雅可持续**: 活地图永不过时, 一份数据 3 用途 (人读/self-debug/治理)

---

## 11. 归档协议

完工:
1. 本 design doc 不动 (历史参考)
2. `JARVIS_ARCHITECTURE_MAP.md` (手 map) 顶部加 "⚠️ DEPRECATED — 见 JARVIS_ARCHITECTURE_MAP_AUTO.md (动态地图)"
3. `AGENTS.md` 必读顺序加 AUTO.md (agent 进窗口看活地图)
4. TODO.md 加 Phase 5 完工速览

---

*文档作者: Sir 提出动态地图洞察 + Cascade 综合设计 / 2026-05-29 01:33*
*SOUL Phase 5 — 自我认知元架构从"我是谁"延伸到"我的身体构造". 动态地图是 Jarvis 认知自己的活组件, 非独立文档.*
