# 拍4 设计 — 接地偏权 lens 重开 (Sir 已审定, lens 仍关)

> **[body-diff-P1 / 2026-06-06]**
> 状态: **Sir 已审定 (§5 记录)。lens 仍关 (lens_inject_enabled=0)。拍4 实做 (耦合护栏) → 零假焊门+_runall → Tier2 B 端到端 → B 结果回 Sir 审 → 才碰真机翻 flag。不裸翻。**
> 真理源: `docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md §15.6` (P1 三门) + `docs/JARVIS_VALIDATION_STANDARD.md` (双镜像/真路径铁律) + commit `c34cd2d` (grounded_only 实做)。
> 前置已完成: `75d702b` 止血 (lens→0) · `c34cd2d` grounded_only spread + 零假焊门 (先红后绿)。

## 0. 目的 + 不碰真机的边界

接地偏权 spread (`grounded_only`, c34cd2d) 已实做并经零假焊门验证 (Tier1 真函数沙盒)。本设计定**重开 lens 的前置三块**, 缺一不碰真机:
1. **耦合护栏** (首要) — 把"裸 naive lens"这条已证有害路径退役
2. **条件顶替 layer3** — 先验是否已白送, 不加冗余
3. **Tier2 Agent Mirror B 端到端** — 规范要求的真路径终验

**本文件只是设计。不翻任何 flag, 不改生产行为。** Sir 审过本设计 + 看过 B 端到端 run 证据 (turn_complete / lens 块零假焊), 才谈翻 `lens_inject_enabled`。

---

## 1. 耦合护栏 (首要 — 堵"一翻就回 6 天前")

### 1.1 问题

当前 flag 矩阵三个独立、都默认关:
- `lens_inject_enabled` (止血=0)
- `lens_spread_grounded_only` (默 0)
- `lens_replaces_layer3` (=1, 休眠 — 因 inject=0 时 lens_block 恒空)

⟹ 后门: 将来谁重开 lens 只翻 `lens_inject_enabled=1`、忘了同时翻 `grounded_only` → **原样复活 95.6% 假焊** (naive 全边 spread)。naive 全边 lens 是**已证有害路径** (上线 6 天投假焊), 没有正当理由再让它可达。

### 1.2 设计: inject=1 且 grounded_only=0 → 拒绝注入 / fail-loud (两层)

**Sir 审定 (2026-06-06): 两层防误配, 不只热路径日志。**

热路径 bg_log 有个洞 — 日志没人读就等于没报 (正是 05-31 的味道: 有信号没人看)。故两层:

**层1 — 启动期 loud 早警 (在跑第一个 turn 之前抓误配)**: 配置加载/lens 初始化时校验耦合, `inject=1 且 grounded_only=0` → 启动期 WARNING/ERROR 级 loud (print + bg_log, 甚至直接拒绝起 lens)。把误配在第一个 turn 之前抓住, 不靠事后翻日志。

**层2 — 热路径运行时安全网 (限流)**: `build_lens_block()` 入口 (现 `if not lens_inject_enabled(): return ""` 处):

```
inject = lens_inject_enabled()
grounded = lens_spread_grounded_only()   # 新增独立 reader (复用现有 vocab key)
if not inject:
    return ""                            # lens 关 (老行为)
if inject and not grounded:
    # 耦合护栏: 裸 naive lens = 已证有害路径, 退役。不静默走 naive。
    # 限流: 误配会每 turn 触发, bg_log 限一次/状态变化 (防刷屏)。
    _refuse_log_once("[Lens] REFUSE inject: lens_inject_enabled=1 但 "
        "lens_spread_grounded_only=0 — 裸 naive lens 已证投 95.6% 假焊 "
        "(JARVIS_VALIDATION_STANDARD §6), 拒绝注入。")
    return ""                            # 运行时安全网 + 当 off 处理
# inject=1 且 grounded=1 → 正常走接地偏权投影
```

`_refuse_log_once`: 模块级状态记上次是否已报 (或记 (inject,grounded) 状态), 状态不变则不重复 bg_log — 防误配每 turn 刷屏。

**为什么 return "" 而非 raise**: lens 在主脑热路径 (`_assemble_prompt`), raise 会崩主对话 (违准则1)。return "" = 当 lens 关处理 (Layer3 保留, 老行为, 零伤害)。fail-loud 体现在启动期 loud (层1) + 限流 bg_log (层2), 不在 crash。

**效果**: naive 全边 lens 从可达状态退役。进主脑只剩两态: lens 关 (inject=0) 或 接地偏权 (inject=1 且 grounded=1)。中间那条有害路径不可达, 且误配在启动期就被 loud 抓住。

### 1.3 测试 (拍4 实做时补, 先红后绿)
- `inject=1, grounded=0` → build_lens_block 返 "" + bg_log 含 REFUSE (断言 log) + 启动期校验 loud
- `inject=1, grounded=1` → 正常投影 (复用零假焊门)
- `inject=0` → "" (老行为)
- 限流: 连续多次 `inject=1, grounded=0` 调用 → bg_log 只报一次 (状态不变不重复)

---

## 2. 条件顶替 layer3 — 验证已白送, 不加冗余

### 2.1 Sir 洞察 (已验, 成立)

现有 `jarvis_central_nerve.py` 逻辑 (实测确认):
- `:3627` `if lens_block:` 才设 `_lens_replaces_l3 = lens_replaces_layer3()` — **空 lens_block → `_lens_replaces_l3` 恒 False**
- `:3664` `if attention_block and not _lens_replaces_l3:` — 只有 `_lens_replaces_l3=True` 才丢 Layer3

⟹ **空 lens_block → Layer3 保留 (沉默时优雅让位); 非空 → 顶替**。"非空才顶、空就让位"**现有代码已实现**。

叠加耦合护栏 (§1) 后: lens_block 只可能是"空"或"全接地内容" (grounded_only 强制开)。两者一合:
> `lens_block 非空` ⟺ `有接地内容` ⟹ 现有 `if lens_block:` 自动 = "只有接地非空才顶 Layer3"

**结论: 条件顶替语义已白送, 不需新写 gating 分支。** 加冗余分支反而多一处可错状态 (违准则8)。

### 2.2 拍4 只补"边界漏洞"复核 (非新逻辑) — Sir 审定
仅验沉默时优雅让位无边界漏洞:
- lens_block="" → Layer3 在 (已验)
- lens_block 全空白字符 (" \n")? — 复核 project 是否可能返回非空白但无实质内容的串 (现 project `if len(lines)<=2: return ""` 已挡纯头尾, 大概率安全, B 端到端再确认一次)
- 不加新 if 分支, 只在 B 验证里盯这点。

**Sir 审定 (2026-06-06)**: B 验证里**务必显式跑一个沉默 seed (hand_pain)**, 断言此时 **Layer3 被保留、没被空块顶成空白** — 这是"白送"路线唯一要守的边界。(hand_pain 无接地路径 → grounded 投影空 → lens_block="" → 现有 `if lens_block:` 不顶 → Layer3 在。B 端到端实证这条链。)

---

## 3. Tier2 Agent Mirror B 端到端 (规范要求的真路径终验)

### 3.1 为何必须 B (不能停在 Tier1) + B 的活到底是什么 (Sir 审定收紧)
- 拍2/3 的对齐是 **Tier1 真函数** (temp 沙盒真 build_lens_block→project→spread, 但 lens 仍关、非真 turn)。
- 规范 §2: 进主脑改动**终态必须过 B** (真 jarvis_nerve.py → 真 _assemble_prompt → 真组 prompt)。重开 lens 是"翻真机行为开关", 属最高风险类, B 不可跳过。

**⚠️ Sir 审定 (2026-06-06) — B 的活不是再证一遍零假焊**: 零假焊这个不变量 **Tier1 真函数门 (c34cd2d) 已证过且常驻**。Tier2 B 的活是**三件别的**:
1. **整链不崩** — 真 turn 跑通, lens 注入不炸主对话 (TTFT/异常)
2. **真 `_assemble_prompt` 确实调到了 grounded 路径** (没绕道 / 没走 naive / 耦合护栏真生效)
3. **reply 不疯** (人读: 接地投影没让主脑产出退化回复)

⟹ **B 断言可更轻**: 确认"真 turn 里 lens 块是接地的 / 没出 hand_pain↔interview" 即可, **不必为它专门造重型 dump 再证一遍零假焊**。

### 3.2 B 验证步骤 (mirror 副本里开 flag, 绝不碰真盘)
1. `python scripts/jarvis_mirror.py --task "P1 lens 重开 grounded 零假焊端到端"` — copytree 整机到 `D:/jarvis_mirror_<ts>/`
2. **只在 mirror 副本** 改 `<mirror>/memory_pool/relational_manifold_vocab.json`: `lens_inject_enabled=1` + `lens_spread_grounded_only=1` (绝不动真盘 `d:/Jarvis/` 那份)
3. `python scripts/jarvis_mirror_say.py --mirror <mirror> "my hand pain is acting up"` (+ interview / hydration 三 seed)
4. `python scripts/jarvis_mirror_tail.py --mirror <mirror>` 看真 `turn_complete` 事件

### 3.3 断言 (压 lens 块/链路, 不压 reply) — Sir 审定: 轻断言
- **整链通**: 三 seed 各跑出 turn_complete, 无异常/无崩 (整链不崩)。
- **真调 grounded 路径**: hand_pain turn lens 块**无 interview** / interview turn **无 hand_pain** (确认走的是 grounded 非 naive — 这是"真调到 grounded 路径"的可观测证据, 不是重证零假焊)。
- **沉默让位 (§2.2 边界)**: hand_pain (无接地路径) turn → lens 块空 → Layer3 保留 (不被空块顶成空白)。
- **正控**: hydration turn lens 块非空且接地 (整链真投得出)。
- **不压 LLM reply 文本** (非确定/flaky); reply 仅人读"没疯"参考。

### 3.4 lens 块取证 — 先省后加 (Sir 审定 (c))
**先查现有事件够不够, 不够才加码**:
1. 先查现有 `turn_complete` / 既有 mirror 事件是否已带够信号 (能否从中读出 lens 块或推断"没出 hand_pain↔interview")。**能 → 不加码, 白省。**
2. 真没暴露才加一条 dump lens 块的 mirror 审计事件, 且**铁律**:
   - dump 必须 **`JARVIS_MIRROR=1` env 门控** — build_lens_block 是共享模块, 在它里面加 dump = 改了生产热路径; 只有 env 门控才保证**生产侧可证明 no-op**。
   - 这条 env 门控本身**也算进主脑改动**, B 验证时须确认**真机路径不走它** (env 未置时 dump 分支不执行)。

### 3.5 B 铁律 (规范 §5)
- flag **只在 mirror 副本开**, 绝不手滑改真盘 `d:/Jarvis/memory_pool/relational_manifold_vocab.json`。
- 共享 `.env` → B 真烧 token, **限量跑** (3 seed 各一条, 不批量空跑)。
- mirror 跑完即删 → **结论 + lens 块证据落进 commit message / 看板** (不留临时目录)。

---

## 4. 重开顺序 (Sir 审过本设计 + B 验过才执行)
1. 拍4 实做: 耦合护栏 (§1.2 + 测试) — 独立 commit, lens 仍关
2. B 端到端 (§3): mirror 副本开 flag 验零假焊 → 证据落看板
3. 把 §3 的 B run 证据 (lens 块零假焊) 发 Sir
4. **Sir 审过 → 才翻真机 `lens_inject_enabled=1` + `lens_spread_grounded_only=1`** (耦合护栏保证不会只翻一半)
5. 真机灰度观察 (Sir 真机验投影质量, 同 05-31 但这次加了零假焊维)

**不裸翻。** 每步独立 commit, 不裹无关改动。

---

## 5. Sir 审定记录 (2026-06-06)

三点已 Sir 审过, 终态决定已 fold 进上文:
- (a) 耦合护栏 = return ""+限流 bg_log (非 raise) **+ 启动期 loud 早警** (两层, §1.2) ✅
- (b) 条件顶替 = 不加冗余分支 (已白送); **B 里必跑沉默 seed hand_pain 验 Layer3 保留** (§2.2) ✅
- (c) lens 块取证 = **先查现有事件够不够, 不够才加 `JARVIS_MIRROR` 门控的 dump**; B 断言压"整链通 + 真调 grounded 路径", **不必重证零假焊** (Tier1 已证常驻, §3.1/§3.4) ✅

**设计状态: 已审过。** 拍4 实做门 (Sir 提醒): 耦合护栏是改 build_lens_block 入口 = 进主脑热路径 code 改动, 哪怕默认惰性 (真机 inject=0 永不触发), 仍须 **过零假焊门 + _runall 零增红 → 然后 Tier2 B 端到端 → B 结果回 Sir 审 → 审过才翻真机 lens_inject_enabled。别裸翻。**

---

## 6. 🅿️ B 端到端 PARKED (Sir 2026-06-06)

**状态: Tier2 B 暂停 (parked), 非放弃。P1 停在完全安全的休息态, 不流血。**

### 6.1 停在哪 (不掉血的依据)
- 真机 `lens_inject_enabled=0` (止血态 75d702b) → Layer3 真注意力在岗 = 诚实, 假焊不复发。
- `grounded_only` + 耦合护栏代码已提交 (c34cd2d / ac4483b) 但**惰性** (inject=0 永不触发), 既不生效也不碍事。
- "重开 lens" 本质 = 把一个反应式上下文功能开回来 (更多上下文进 prompt), **不是修复** — 修复(止血)早做完。故 B + 重开可延可不做, Jarvis 照常安全跑, lens 暂时安静 ("少说但真 > 常说但假")。

### 6.2 smoke 已证的 + 还差的 (恢复时别误判"环境不行")
- ✅ **LLM key 可用**: 2026-06-06 smoke 起 mirror (copytree 1865 files / 6.9s, subprocess nerve 真启), Weaver + InnerThought daemon **真调 LLM 出 thought** → 证明这台环境 LLM key 能调通。Q2 "key 没在这跑过" 的担忧已解。
- ⏳ **仅差**: 反应式对话 `turn_complete` 未观测到 (注入 "hi jarvis" 后 20s 内 count=0 即被 Cancel)。**worker turn (收注入→tick) 是另一条代码路径, 比 daemon 慢, 很可能只是没等够, 不是坏了。** 恢复时多等即可。

### 6.3 恢复 B 的步骤 (随时可做, 今天不做零损失)
1. `python scripts/jarvis_mirror.py --task "P1 lens B"` (重建 ~7s)
2. **只在 mirror 副本** 改 vocab: `lens_inject_enabled=1` + `lens_spread_grounded_only=1` (绝不碰真盘)
3. `jarvis_mirror_say` 注 hand_pain / interview / hydration 三 seed
4. **等够 worker turn** (比 daemon 慢, 多等; 别 20s 就判死)
5. `jarvis_mirror_tail` 看 turn_complete, 断言压 lens 块 (§3.3: 整链通 + 真调 grounded 路径 + 沉默 seed 验 Layer3 保留, 不压 reply)
6. mirror 跑完即删 → 结论 + lens 块证据落 commit/看板
7. B 结果回 Sir 审 → 审过才翻真机 lens

**优先级**: B parked 期间, 工程重心转向"完整了解体架构" (体势能 / 体↔识 闭环 — 自我核心, 比反应式 lens 通道重要一个量级)。lens 关着不影响自发思考。

*本文件由 body-diff-P1 轨 agent 创建 (拍4 设计草稿)。Sir 审过 + B 验过, 方可碰真机重开 lens。*
