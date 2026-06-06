# JARVIS 验收规范 — 双镜像适用边界 + 真路径铁律

> **[validation-standard / 2026-06-06 创建]**
> **强制度**: 常驻硬规。任何 agent 在声称"验过 / 测过 / 没问题"之前必须先读本文件。
> **入口**: `AGENTS.md §11 (定期维护)` + `docs/AGENT_HANDOFF_PROTOCOL.md §2` + `docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md` 交叉引用。
> **写给谁**: 完全不了解背景的下一个 agent。本文件是规定式的, 不是叙事。照做即可。
> **诞生原因**: 2026-05-31 一次 lens 改动用了错误的验收口径 + 弱镜像, 导致 95.6% 假关联持续投进主脑 prompt 约 6 天无人发现 (详 §6 事故案例)。修代码只修了那一次; 立本规范是为防下一次。

---

## 0. 一句话铁律 (先记住这条)

**声称"真机 / 真路径验过"的改动, 必须给得出整机 Agent Mirror (B) 的 run 证据 (turn_complete / lens 块 / 组好的 prompt)。拿体图镜像 (A) 或单元测试冒充终验 = 未验。**

**适用范围 (不只 lens)**: 本规范适用于**所有碰 body→brain 投影 / 真机行为的改动**, 不限于 lens/spread —— 包括任何未来的投影通道、记忆注入路径、决策门。不要读成"这是 lens 专用规范, 我改的不是 lens 所以不关我事"。

---

## 1. 两个镜像 (别混) — 定义 + 适用边界表

JARVIS 有**两个完全不同**的"镜像", 名字像但能力天差地别。混用是事故根源。

| 维度 | **A. 体图镜像** | **B. 整机 Agent Mirror** |
|---|---|---|
| 入口 | `scripts/manifold_*_mirror.py` (如 `manifold_p1_spread_mirror.py` / `manifold_p0c_mirror.py` / `manifold_deweld_mirror.py`) | `scripts/jarvis_mirror.py --task "..."` (核心 `jarvis_mirror_mode.py`); 配 `scripts/jarvis_mirror_say.py` (注入) + `scripts/jarvis_mirror_tail.py` (看输出) |
| 本质 | 一次性只读 Python 诊断脚本 | 真运行系统: copytree 整个 `d:/Jarvis` → `D:/jarvis_mirror_<ts>/`, `subprocess python jarvis_nerve.py` env `JARVIS_MIRROR=1` |
| 镜像范围 | **只** RelationalManifold 体数据 (复制 `relational_manifold.json` 到 temp, 读 inner_thoughts/self_threads 做诊断) | **整机**: memory_pool 全库 / self_threads / inner_thoughts / SWM / 全部 vocab / *.db / 全部 .py / 配置 |
| 跑真生产代码路径? | **否**。自己复刻投影口径 (手写 spread/project 逻辑), 不走 `_assemble_prompt`→`build_lens_block`→`RelationalLens.project`→`manifold.spread` | **是**。真 `jarvis_nerve.py` → 真 `_assemble_prompt` → 真 `build_lens_block` → 真 `project` → 真 `spread`, 真组发给主脑的 prompt |
| 能端到端触发 tick / 一轮对话? | 否 (只算/复刻) | 是 (`jarvis_mirror_say.py` 注真话 → 真 tick → 真 thought / 真 prompt / 真 reply) |
| LLM | 零 token (纯图遍历) | 真调 LLM (共享 `.env`, 真烧 token), MockVocalCord 只替 TTS |
| 确定性 | 确定性 (可断言精确数值) | 非确定 (LLM reply 会变; 但 LLM **之前**的产物如 lens 块/prompt 是确定的) |
| 隔离 | 复制到 temp + `save=False` + 跑完 `rmtree`, 绝不回写 | 独立目录 + 独立 subprocess cwd, copytree 真复制 (`symlinks=False`), 不回写主 `d:/Jarvis` |

---

## 2. 铁律 — 验收层级必须匹配改动的影响半径

判断你的改动属于哪一类, 用对应层级验收。**不接受降级。**

| 改动影响半径 | 最低验收层级 | 说明 |
|---|---|---|
| 纯图 / 数据逻辑 (不进主脑、不影响决策、不改真机行为) | **A 可以** | 体图镜像快速迭代 OK。例: 调面检测参数看 largest_frac、量孤儿数 |
| **任何会进主脑 prompt / 影响决策 / 改真机行为的改动** | **必须 B 真代码路径验收** | 不接受用 A 或单测替代当"验过"。例: lens 投影、prompt 层装配、注意力选取、nudge 决策 |
| 触碰真机行为开关 (如 `lens_inject_enabled` / `lens_replaces_layer3` 等 flag) | **先 B 端到端验 + 理论侧审, 才碰真机** | 开关一翻就是真机行为变化, 必须先在 mirror 看清后果 |

**A 与单测的定位**: A 镜像和单元测试用于**快速迭代 + 确定性回归**, 可以先跑它们筛掉低级错误。但对"进主脑"类改动, 它们**只是前置筛子, 不是终验**。终验只认 B。

### 2.1 分类示例 (堵"自我降级") — 对号入座, 不许 rationalize 进便宜那格

| 你改了什么 | 半径 | 最低层级 |
|---|---|---|
| `spread` / `project` / lens / SWM inject / decision gate / vocab flag (`lens_*`) | 进主脑 | **B 必须** |
| 任何 `_assemble_prompt` 或其 import 链里的函数 | 进主脑 | **B 必须** |
| `manifold.compute_surfaces` / `complexity_report` / 纯图度量 (**确认无下游注入消费方**) | 图数据 | A 可以 |

**有疑义时**: 默认升级到 B, 或直接问 Sir。**禁止自行降级。** "我觉得这只是数据所以 A 就行" 是事故的标准前奏 —— 改 `spread` 看着像"图逻辑", 但它是 lens 投影的核心原语, 一字之差就进主脑。判别口诀: **问"这条改动的产物有没有任何路径流进主脑 prompt 或决策?" 有 → B; 拿不准 → B。**

---

## 3. 断言压在确定性产物 (不压 LLM reply)

- 验收断言**必须压在 LLM 之前的产物**: lens 块 / 组好的 prompt / spread 投影出的节点集。这些是确定的, 可精确断言。
- **严禁**把验收断言压在 LLM 的 reply 文本上 — reply 非确定, 必 flaky, 用它当门会让验收随机过/不过, 等于没门。
- B 镜像里取证: 看 `turn_complete` 事件 (含 final_reply / tool_results) + 真组出的 prompt / lens 块, 断言压 lens 块那一层, reply 仅供人读参考。

---

## 4. "投影零假焊" — 投影类特性的常驻验收维

- 凡是"把体内容投进主脑 prompt"的特性 (lens / spread / 任何 body→prompt 注入), 验收维**不是只有一条**。两条并列, 缺一不可:
  1. **回复相关 + 无人设违反** (整体有益度)
  2. **投影零假焊** (投进 prompt 的每条关联都经得起人读 ground-truth 核验, 不含已证伪的假关联)
- 历史教训: 只验 (1) 不验 (2) → "lens 整体有益"和"lens 在投假焊"可以同时为真, (1) 通过不代表 (2) 通过 (详 §6)。
- **新断言必须先红后绿**: 任何新加的验收断言 (尤其"零假焊"), 必须先证明它**能抓到 bug** (在未修代码上跑出红), 再证明修后转绿。一上来就绿的断言 = 没验到东西, 不可信。

---

## 5. 镜像隔离 + 留痕纪律

**隔离纪律**:
- 改 flag / 改 vocab 做实验 → **只动 mirror 目录里的副本**, 绝不手滑改真机 `d:/Jarvis` 那份。
- copytree 不回写主目录; mirror crash 不污染真机。
- ⚠️ 共享 `.env` → B 镜像**真烧 token**, 限量跑 (按需注入几条, 不要批量空跑)。
- dashboard 8765 端口撞主 → 已在 chat_bypass 短路, 知道即可。

**留痕纪律 (最易踩)**:
- Agent Mirror 目录 (`D:/jarvis_mirror_*`) **跑完即删**, 是临时沙盒。
- ⟹ 验收结论 + 关键证据 (turn_complete / lens 块摘录 / 通过的断言) **必须落进 commit message 或看板**, 严禁只留在临时 mirror 目录。
- 这正是 §6 事故里"连 artifact 都查不到"的直接教训: mirror 删了, 结论只剩 vocab 一句注释, 无法复盘当时到底验了什么口径。

---

## 6. 永久反例 (事故案例 — 钉档, 任何 agent 不得重蹈)

**2026-05-31 lens A/B 验收口径漏维事故**:

- **改动**: `lens_inject_enabled=1` + `lens_replaces_layer3=1` (lens 投影进主脑 prompt 且顶替 Layer3 attention)。
- **当时验收口径**: 仅"回复相关 + 无人设违反" (见 `relational_manifold_vocab.json` 的 `_doc_lens_replace` 注释)。**漏了"投影零假焊"这一维。**
- **后果**: `spread` 沿存储图的假焊边把 **95.6% 假关联**投进主脑 prompt, 含人读已证伪的 `hand_pain↔interview` 双向互焊 (手痛=玩 AoE4 游戏, 非 coding), 并**顶替**了原 Layer3 真信号 (双重代价: 加假 + 删真)。
- **持续时长**: flag 落款 2026-05-31, 2026-06-06 镜像复核发现; 期间生产若按 HEAD 运行则持续投假焊。**确切起始未留 run artifact, 以 flag 落款为最早可能点。** (无法精确定位起始, 正是 §5 留痕纪律缺失的后果 —— 本事故自我印证了该律。)
- **止血**: commit `75d702b` 把 `lens_inject_enabled` 翻回 0 (诚实沉默 > 投假)。

**三条教训 (本规范的立规依据)**:
1. **验收口径不全 = 事故**。"回复相关"通过 ≠ "零假焊"通过; 投影类特性两维缺一不可 (§4)。
2. **真路径改动用弱镜像验 = 没验**。lens 是进主脑的改动, 属 §2 "必须 B 验"类; 若当时用 B 端到端看真组出的 prompt + 压"零假焊"断言, 假焊当场暴露, 不会上线 6 天。
3. **断言缺失 = 漏检无声**。05-31 时"投影零假焊"断言**根本不存在** —— 没人能察觉漏了一维, 因为一个不存在的检查永远不会报红。教训: 规则 (§4 先红后绿) 是修法; 更深一层, 对任何投影/真路径改动, 接手 agent 必须**先问"有没有缺的维度"**, 而非只跑已有断言。这是 known-unknowns 层面的纪律: 已有断言全绿 ≠ 验全了。

---

## 7. commit 纪律

- 本规范是**文档**, 不是生产行为, 可正常提交。
- 立/改本规范走**独立文档 commit**, 不混进任何代码改动 (如 grounded_only spread 实做), 也不裹挟无关的工作区脏改动。
- marker 用 `validation-standard`; commit 类型 `docs`。

---

*本文件由 `[validation-standard / 2026-06-06]` 创建。维护者: 接手"进主脑/决策/真机行为"类改动的任何 agent。变更走 `docs(validation-standard): ...` commit。*
