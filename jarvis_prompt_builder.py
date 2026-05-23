# -*- coding: utf-8 -*-
"""[P5-fix54 / 2026-05-23 15:45] PromptBuilder — Sir 拍板槽 1 prompt builder 体系.

Sir 15:39 战略指示:
  '把添加更多模块的思路转变一下来找 bug 和盲点: 优先重构现有模块甚至架构,
   在尽量维护现有框架的同时让贾维斯能获得更多的能力.'

Sir 15:43 META 配合:
  '我们现在有 META 那个思维链, 充分发挥他协助主脑不错误说话的能力以及给
   我们 debug 的能力, 把每个模块清晰的结构化.'

设计 (准则 6 + 准则 8 优雅, 不破坏现有 _assemble_prompt 入口):

  阶段 1 (本 file): 建 PromptBuilder + BlockSpec class, 注册 named blocks. 
                    现有 _assemble_prompt 入口签名不变, 内部逐步迁移到 builder.
  阶段 2 (后续):    迁移 1 个 template (WAKE_ONLY 最简) 作示范, 验证不破坏.
  阶段 3:           其他 5 template 逐步迁移.
  阶段 4:           prompt 瘦身 — 按 tier 真砍冗余 block.

核心机制:

  Block schema 标准化 — 主脑 reply 时 META evidence 可引用 block ID + 字段:
    - 'sensor:current_window_stay_s'  ← sensor_state_block 字段
    - 'swm:concern_active'            ← swm_block top event
    - 'stm:turn_20260523_153912'      ← STM turn ID
    - 'l2:morning_warmth_priority'    ← L2 inject directive
    - 'soul:joke_xxx'                 ← SOUL inject anchor

  端到端可追溯:
    输入 (prompt builder block) → 主脑 reply → META evidence → audit jsonl
    Sir debug: '为什么主脑说 X?' → META.evidence → 看具体 block 内容 → 真相.

API:
  builder = PromptBuilder(tier='CHAT')
  builder.register(BlockSpec(id='sensor', content='...', tiers=['CHAT'], hint='...'))
  prompt_str = builder.compose(template_id='standard', persona=..., user_input=...)

  list_block_ids() -> List[str]   # debug / META 引用
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BlockSpec:
    """Prompt block 元数据 — 让主脑知道每个 block ID + 字段."""
    id: str                                  # block ID, e.g. 'sensor', 'swm', 'soul'
    content: str                             # 块文本
    tiers: List[str] = field(default_factory=list)  # 适用 tier
    hint: str = ''                           # META 引用提示 (e.g. 'sensor:<field_id>')
    salience: float = 0.5                    # 块重要性 (用于 budget 削减)
    max_chars: int = 0                       # 此块最大字符 (0 = 不限)
    # 🆕 [P5-fix64 / 2026-05-23 16:28] Phase 3d.2: metadata 内省字段
    # 让 Phase 3d.3 可以记录 mega block 内 logical sections (head/body/tail/...)
    # debug / Phase 4 瘦身需要这个数据找冗余块.
    metadata: Dict[str, object] = field(default_factory=dict)
    # 🆕 [P5-fix66 / 2026-05-23 16:40] Phase 3d.3: audit_only flag
    # True = 注册但不渲染 (仅 audit_summary 用, Phase 4 瘦身规划基础)
    # 让 central_nerve 注册 5 logical sections + 1 actual legacy mega block,
    # 字面零变化 (output = legacy), 但 audit 可看 5 section 体积分布.
    audit_only: bool = False

    def is_active_for(self, tier: str) -> bool:
        """是否适用此 tier."""
        if not self.tiers:
            return True  # 空 tiers = 全 tier 适用
        return tier in self.tiers

    def render(self) -> str:
        """渲染块. 若 max_chars > 0 强制截断."""
        if self.max_chars > 0 and len(self.content) > self.max_chars:
            return self.content[:self.max_chars - 15] + '\n...(truncated)'
        return self.content

    def char_len(self) -> int:
        """块字符长度 (内省 / Phase 4 瘦身 audit)."""
        return len(self.content) if self.content else 0


class PromptBuilder:
    """按 tier 收集 named blocks, 渲染 prompt 含 META 引用提示.

    用法:
        builder = PromptBuilder(tier='CHAT')
        builder.register(BlockSpec(id='sensor', content='...', hint='sensor:<field>'))
        builder.register(BlockSpec(id='swm', content='...', hint='swm:<etype>'))
        out = builder.compose(persona='...', user_input='...')
    """

    def __init__(self, tier: str = 'CHAT'):
        self.tier = tier
        self._blocks: Dict[str, BlockSpec] = {}
        self._order: List[str] = []  # 注册顺序

    def register(self, block: BlockSpec) -> None:
        """注册块. 同 ID 后注册覆盖前 (允许 builder 内 update)."""
        if not isinstance(block, BlockSpec):
            return
        if not block.id:
            return
        if block.id not in self._blocks:
            self._order.append(block.id)
        self._blocks[block.id] = block

    def get(self, block_id: str) -> Optional[BlockSpec]:
        return self._blocks.get(block_id)

    def list_block_ids(self) -> List[str]:
        """返回当前 tier 下所有 active block ID (META 引用用)."""
        return [bid for bid in self._order
                if self._blocks[bid].is_active_for(self.tier)]

    # 🆕 [P5-fix64 / 2026-05-23 16:28] Phase 3d.2: audit helpers
    # 为 Phase 4 prompt 瘦身做基线, Sir 可看 prompt 体积分布找冗余.

    def total_chars(self) -> int:
        """所有 active block 字符总数 (audit)."""
        return sum(self._blocks[bid].char_len()
                    for bid in self.list_block_ids())

    def size_breakdown(self, top_k: int = 5) -> List[tuple]:
        """返回 top_k 大 block 的 (id, char_len) list, 降序. Phase 4 瘦身 audit 用."""
        sizes = [(bid, self._blocks[bid].char_len())
                  for bid in self.list_block_ids()]
        sizes.sort(key=lambda x: x[1], reverse=True)
        return sizes[:top_k]

    def audit_summary(self) -> Dict[str, object]:
        """audit 摘要 dict — debug / dashboard / Phase 4 用."""
        active_ids = self.list_block_ids()
        return {
            'tier': self.tier,
            'n_blocks': len(active_ids),
            'total_chars': self.total_chars(),
            'top5': self.size_breakdown(top_k=5),
            'block_ids': active_ids,
        }

    def render_blocks(self) -> str:
        """渲染所有 active block (按注册顺序). 跳过 audit_only blocks."""
        parts = []
        for bid in self._order:
            block = self._blocks[bid]
            if not block.is_active_for(self.tier):
                continue
            if block.audit_only:
                continue  # 🆕 [P5-fix66] audit_only block 不渲染
            rendered = block.render()
            if rendered:
                parts.append(rendered)
        return '\n\n'.join(parts)

    def render_meta_hint(self) -> str:
        """渲染 META evidence 引用提示, 告诉主脑可用哪些 block ID."""
        hints = []
        for bid in self.list_block_ids():
            block = self._blocks[bid]
            if block.hint:
                hints.append(f"  - {block.hint}")
        if not hints:
            return ''
        return (
            "[META EVIDENCE CHEAT SHEET]:\n"
            "  你 reply 末尾的 [META] evidence 字段可引用以下 source ID:\n"
            + '\n'.join(hints) + '\n'
            "  例: evidence=sensor:current_window_stay_s,swm:concern_active"
        )

    def compose(self, persona: str = '', user_input: str = '',
                  footer: str = '', system_alert: str = '',
                  include_meta_hint: bool = True) -> str:
        """组装最终 prompt.

        Args:
            persona:        核心人设 (block 列表前)
            user_input:     Sir 输入 (末尾)
            footer:         template-specific footer (e.g. BILINGUAL DIRECTIVE)
            system_alert:   system alert text (末尾, user input 后)
            include_meta_hint: 是否注入 META cheat sheet

        Returns: full prompt str
        """
        parts = []
        if persona:
            parts.append(persona.rstrip())
        blocks_str = self.render_blocks()
        if blocks_str:
            parts.append(blocks_str)
        if include_meta_hint:
            hint = self.render_meta_hint()
            if hint:
                parts.append(hint)
        if footer:
            parts.append(footer.rstrip())
        if user_input:
            parts.append(f"User: {user_input}")
        if system_alert:
            parts.append(system_alert.rstrip())
        return '\n\n'.join(parts)


# ============================================================
# 工厂: 从现有 sensor_state_block / swm_block 等创建 BlockSpec
# (让 _assemble_prompt 逐步迁移到 builder, 不强制立刻)
# ============================================================

def make_sensor_block_spec(tier: str = 'CHAT', max_chars: int = 600) -> Optional[BlockSpec]:
    """从 jarvis_sensor_state_block 拿数据, 包成 BlockSpec."""
    try:
        from jarvis_sensor_state_block import build_sensor_state_block
        content = build_sensor_state_block(tier=tier, max_chars=max_chars)
        if not content:
            return None
        return BlockSpec(
            id='sensor',
            content=content,
            tiers=['SHORT_CHAT', 'CHAT', 'DEEP_QUERY', 'TOOL_REQUEST', 'CRITICAL'],
            hint='sensor:<field_id>  (e.g. sensor:current_window_stay_s)',
            salience=0.85,  # 高 — Sir 真痛点根因
            max_chars=max_chars,
        )
    except Exception:
        return None


def make_swm_block_spec(event_bus=None, n: int = 12, max_chars: int = 900) -> Optional[BlockSpec]:
    """从 EventBus.to_swm_block 拿数据, 包成 BlockSpec."""
    if event_bus is None or not hasattr(event_bus, 'to_swm_block'):
        return None
    try:
        content = event_bus.to_swm_block(n=n, max_chars=max_chars, salience_floor=0.3)
        if not content:
            return None
        return BlockSpec(
            id='swm',
            content=content,
            tiers=['CHAT', 'DEEP_QUERY', 'TOOL_REQUEST', 'CRITICAL'],
            hint='swm:<etype>  (e.g. swm:concern_active, swm:sir_field_updated)',
            salience=0.80,
            max_chars=max_chars,
        )
    except Exception:
        return None
