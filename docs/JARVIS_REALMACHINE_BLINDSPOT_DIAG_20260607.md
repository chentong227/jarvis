# 真机首份激活日志 两条盲点诊断 (只读, 不改码/真机/flag)

> **[realmachine-blindspot-diag / 2026-06-07]**
> 依据: 激活后首份真机日志 `docs/runtime_logs/jarvis_20260607_101414.log`, turn `6cc0`("母亲手术"轮)一次口主脑假焊。
> 只诊断, 给根因 + 复现条件 + 影响面。**先别动手修, 等顾问/Sir 定。** energy_grounded_only=1 未动。

---

## 0. 假焊事件实证(turn 6cc0)

| 项 | 实物 | 日志行 |
|---|---|---|
| Sir 输入 | "我前两天跟你讲的母亲做手术的事情, 没有被记录下来吗?" | 1215 |
| tier | **SHORT_CHAT** (cmd_len=44, words=1) | 1206 |
| 口 stream 出口(TTFT 3.7s) | **"I have located the entry in your long-term memory. On June 3rd, you mentioned that your mother would be undergoing surgery…"** | 1230(TTFT)/1233(reply) |
| 工具实际结果 | `search_memory → hippocampus.search_recent success=False … 'Organ 'hippocampus' is not mounted.'` | **1255** |
| 识(InnerThought)同轮判断 | "I have no record of this in my current memory logs, and I must admit this ignorance directly rather than hazarding a guess." | 1249 |
| INTEGRITY/Alert | `gated_silent (no summon, no preflight fail)` — 当轮未拦, 下轮才提醒 | 1239 |
| 下轮 fb29 MemoryCorrection | "母亲手术在6月3日"→"6月5日" — 假焊已被 Sir 纠正后系统才记录 | 1430 |

**时序铁证**: 口在 **3.7s** 就 stream 出"已找到6月3日记录"(行 1230), 而工具失败回执在 **stream 之后**才到(行 1255)。⟹ 口的"已找到"是**纯编造, 非工具结果误读** —— 工具根本没成功, 口却抢先确信声称找到。识(行 1249)同帧判对"该直认无知", 口未采纳。

---

## ① hippocampus 器官 not mounted — 根因 + 偏发/持续判定

### 根因: **三重静态错配, 非 boot 偶发**

`search_memory` intent 的路由目标在 intent map 里写死为 `hippocampus.search_recent`:
```
memory_pool/intent_to_tool_map.json:111-113
  "id": "search_memory", "state": "active", "tool": "hippocampus.search_recent"
```

路由执行链(`IntentRouter.route_and_invoke` → `fast_call_executor`):
- `jarvis_intent_router.py:337` `organ_name, command = tool_full.split('.', 1)` → `organ_name="hippocampus"`, `command="search_recent"`
- 执行落到 `jarvis_chat_bypass.py:2549` `hand_class = self.jarvis.hand_registry.get(organ_name)`
- `hand_registry` 只由 `_hot_reload_organs` 扫 `l4_hands_pool/` 填充(`jarvis_central_nerve.py:5234` `scan_dir("l4_hands_pool", "Hands", self.hand_registry, …)`)
- `l4_hands_pool/` **无 hippocampus organ**(共 26 个 `*_hands`, 记忆类是 `l4_memory_hands.py`, class `Hands`)
- ⟹ `hand_registry.get("hippocampus")` = None → `jarvis_chat_bypass.py:2597` `return "Error: Organ 'hippocampus' is not mounted."`

**三重错配**(任一就够 fail, 三个叠加):
1. **organ 名错**: 该走 `memory_hands`(l4_hands_pool 里真存在), intent map 却写 `hippocampus`(从来不是 l4 organ, 是 `self.jarvis.hippocampus` 直挂属性)
2. **command 名错**: `Hippocampus` 类无 `search_recent` 方法(`jarvis_hippocampus.py:799` 是 `search_memory`, `:934` `search_memory_default`)。memory_hands 的 execute command 也是 `search_memory`(`l4_memory_hands.py:214`)
3. **挂载语义错**: hippocampus 不经 `_hot_reload_organs` 注册, 它是 nerve 直挂属性 + memory_hands 内部 `self.hippocampus = Hippocampus()`(`l4_memory_hands.py:193`)。fast_call 只认 hand_registry, 永远查不到 hippocampus

### 判定: **持续故障 (重启不会修)**
- 起点: `41cbf68`(`feat(beta.5.36) BUG3 intent channel`, 2026-05-20)引入 `hippocampus.search_recent` 这条 intent 映射 —— 引入即错(organ/command 双错)。
- 持续证据: **同一份日志 turn 6cc0(行 1255)+ turn fb29(行 1446)两轮都 `success=False`**, 同一报错, 非单次 boot race。
- `HippocampusBackfill` 线程在 boot 起来了(日志行内线程组), 但那是后台回填线程, 与 fast_call organ 注册是**两套东西** —— 海马体本体活着(识/sentinel 走 `self.jarvis.hippocampus.xxx` 都正常), 只有"主脑经 IntentRouter 调 search_memory"这条路 100% 死。

### 影响面
- **所有走 `search_memory` intent 的检索 100% 失败** —— 主脑想主动查长期记忆库, 经 IntentRouter 这条路必返 not mounted。
- 其他 hippocampus 用法**不受影响**(它们不走 IntentRouter): sentinel/reminder `self.jarvis.hippocampus.fetch_due_reminders`、SelfAnchor `_get_own_health`、Weaver embed 复用、memory_hands 走 `_FAST_CALL_ONLY_ORGANS`? —— 注: memory_hands 是真 organ, 若主脑 emit `memory_hands.search_memory` 能成;死的是 intent map 把 `search_memory` 别名映射到了不存在的 `hippocampus.search_recent`。
- **直接结论**: "接地骨架长厚"之前, 这是一个更底层的硬故障 —— 主脑的主动记忆检索通道(search_memory intent)长期跑不起来。接地检索若依赖这条 intent, 长期空转。

### 修法方向(待 Sir/顾问定, 未动手)
intent map `search_memory.tool` 从 `hippocampus.search_recent` 改为 `memory_hands.search_memory`(organ + command 双修)。纯 JSON 配置改, 走 `scripts/intent_map_dump.py`(准则6 CLI)。需验 memory_hands.search_memory 真能调通(Tier1/Tier2)。

---

## ② 925 墙+衡在各 tier 的 tier-drift 排查 — has_walls/has_conflict 矩阵

### 结构事实(file:line, 可 grep 抽查)
`anchor_boundary_block`(墙+衡 conflict_guidance+affordance)在 `_assemble_prompt`:
- **定义点**: `jarvis_central_nerve.py:4340`(`anchor_boundary_block = ""` + render 拼装)
- **唯一消费点**: `jarvis_central_nerve.py:4699` legacy mega f-string(925f9e2 在 `{promise_protocol_directive}` 后插入 `{anchor_boundary_block}`)

关键: **轻量 tier 在到达 4699 之前就从独立 helper `return` 了, 且这些 helper 不接收 `anchor_boundary_block` 参数** —— 变量虽在 `_assemble_prompt` 作用域定义, 但从未传进 helper, 故轻量 tier 的组装 prompt 里没有墙。

### 各 tier 组装路径 + 墙在否(代码裁定)

| tier | 组装路径 | return 点 | has_walls / has_conflict |
|---|---|---|---|
| **SHORT_CHAT** | `_assemble_short_chat_prompt`(独立 helper, cn:958) | cn:**4480** return(早于 4699) | **False / False** ❌ |
| WAKE_ONLY | `_assemble_wake_only_prompt`(cn:1397) | cn:4470 return | False / False ❌ |
| FACTUAL_RECALL | `_assemble_factual_recall_prompt`(cn:1209) | cn:4453 return | False / False ❌ |
| REMINDER_FIRING | inline PromptBuilder(cn:4417) | cn:4434 return | False / False ❌ |
| TOOL_REQUEST | 无早 return → 落 4699 mega | cn:4699 | **True / True** ✅ |
| DEEP_QUERY | 无早 return → 落 4699 mega | cn:4699 | **True / True** ✅ |
| CRITICAL | 无早 return → 落 4699 mega | cn:4699 | **True / True** ✅ |
| full (tier=None) | 落 4699 mega | cn:4699 | **True / True** ✅ |

(light mode `mode=="light"` 走 cn:4509 独立 PromptBuilder, 同样无墙;但 light 是 mode 非 tier, 列此备注。)

### drift#2 结论
- **确切漏墙分支 = `_assemble_short_chat_prompt`(cn:958-1152)+ 另 3 个轻量 helper**。它们各自用独立 PromptBuilder 注册 block 集, **均未注册 anchor_boundary_block / walls / conflict_guidance**。
- **墙没在最容易出假焊的 casual turn(SHORT_CHAT)前站岗。** turn 6cc0 正是 SHORT_CHAT → 口组装 prompt 无墙无衡 → 假焊当轮无锚边界拦。
- **为何 TASK 8 镜像 B 4 探针全 has_walls=True 却没抓到**: 那 4 探针(kindness/honesty/promise/mundane)输入较长/语义重, 被 tier 分类器判进 DEEP_QUERY/full 等重档(落 4699, 有墙);**从未命中 SHORT_CHAT 轻档**。镜像 B 的盲区 = 没覆盖轻量 tier。这条是 925f9e2 修复的真实覆盖边界: 只补了重档真输出, 轻档(4 个 helper)仍空投。

### 修法方向(待定, 未动手)
把 `anchor_boundary_block` 透传进 4 个轻量 helper(尤其 `_assemble_short_chat_prompt`)+ 在各 helper 的 PromptBuilder 注册 BlockSpec(tier 对应)。属改口主脑真输出 = 真机行为半径 → 需 B 端到端验(且这次要**专门覆盖 SHORT_CHAT tier 探针**, 补镜像盲区)+ Sir 审。

---

## 交付小结

| # | 盲点 | 根因 | 判定 | 影响面 |
|---|---|---|---|---|
| ① | hippocampus not mounted | intent map `search_memory→hippocampus.search_recent` organ/command/挂载语义三重错配(`41cbf68` 引入即错) | **持续故障**, 重启不修 | search_memory intent 主动记忆检索 100% 死;其他 hippocampus 路径不受影响 |
| ② | 墙+衡 tier-drift | 轻量 tier(SHORT_CHAT 等 4 helper)早 return, 不接收 anchor_boundary_block;925f9e2 只补 4699 重档 | SHORT_CHAT/WAKE_ONLY/FACTUAL_RECALL/REMINDER_FIRING = 无墙;TOOL_REQUEST/DEEP_QUERY/CRITICAL/full = 有墙 | casual turn 无锚边界, 假焊正发生在 SHORT_CHAT;镜像 B 盲区(没测轻档) |

**两条根因叠加解释 turn 6cc0 假焊**: (①)工具真失败 + (②)SHORT_CHAT 无墙拦 → 口在轻档无锚边界下, 把失败的检索编成"已找到6月3日记录"。识判对了(行 1249)但口侧轻档既无墙也没采纳识的判断。

只诊断, 未改任何码/真机/flag。energy_grounded_only=1 未动。断言均给 file:line / 日志行号, 可 grep 抽查。

---

*只读诊断。两条都待顾问/Sir 定后再动手。修 ① = JSON intent map(准则6 CLI);修 ② = 4 helper 透传墙块(真机行为半径, 需 B 验 + 补 SHORT_CHAT 探针 + Sir 审)。*
