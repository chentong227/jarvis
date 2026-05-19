# -*- coding: utf-8 -*-
"""
[轴3-L0 / 2026-05-15] Jarvis SkillRegistry — 言出必行的能力地图

设计目标
--------
铁则 B (诺言必达) 的基石：
1. **不硬编码** — 工具自动入册（扫 l1/l3/l4_hands_pool/l5/jarvis_nerve.py 的
   public callable + 模块级 MANIFEST + 各 hand 的 get_instruction_dict()）
2. **完整 manifest** — 调用名 / 入参 schema / 前置条件 / 典型延迟 / 已知失败模式 /
   测试覆盖 / 危险等级 / 30d 滚动成功率 — 一处真理
3. **运行时反馈** — 每次 skill 调用都喂回 success/fail/latency → 滚动更新 KPI
4. **OfferGuard 接口** — `all_healthy(min_success_rate=0.7)` 给 NudgeGate 加闸用
5. **Capability-Aware Phrasing 接口** — `to_prompt_block()` 渲染为主脑 prompt 注入块
6. **危险隔离** — `dangerous_flag` 三档（safe/risky/dangerous），PromiseLedger 见
   dangerous 必须 Sir 显式 confirm 才允许自动跑

粒度
----
**每个原子能力一个 SkillManifest**，不是每个模块一个：
- audio_hands.list_devices  (safe)
- audio_hands.set_volume    (risky)  ← 影响系统但可恢复
- file_operator_hands.delete (dangerous) ← 写文件 + 不可逆
等等。这样 OfferGuard 才能精细判断"能调音量 ≠ 能切设备"。

持久化
-----
memory_pool/skill_registry.jsonl —— 每行一个 SkillManifest JSON。
- jsonl 而不是 json：append-only 友好 + 单行 grep 友好
- 启动时 `load()` 读全 + 在内存重建索引
- 运行时滚动更新 → 每 N 秒 `save()` 持久化（脏标记）

线程安全
--------
所有状态修改用 self._lock 保护。read-only 接口（get/all/...）不锁也无害。

[轴3-L0.1 / 2026-05-15] 本文件 = SkillManifest + SkillRegistry 数据结构骨架。
扫描器（L0.2）+ 持久化（L0.3）+ 运行时钩子（L0.4）在后续 step 接入。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ==========================================================================
# 危险等级枚举
# ==========================================================================

DANGER_SAFE = "safe"            # 纯读 / 状态查询 / 不影响系统
DANGER_RISKY = "risky"          # 影响系统但可恢复（音量、剪贴板写、浏览器音量）
DANGER_DANGEROUS = "dangerous"  # 不可逆 / 安全敏感（写文件/删文件/跑命令/改注册表/Kill 进程）

VALID_DANGER_LEVELS = (DANGER_SAFE, DANGER_RISKY, DANGER_DANGEROUS)


# ==========================================================================
# manifest 来源枚举（用于追踪是哪种自动注册策略产生的）
# ==========================================================================

SOURCE_MODULE_MANIFEST = "module_manifest"  # 来自模块级 MANIFEST dict
SOURCE_INSTRUCTION_DICT = "instruction_dict"  # 解析 get_instruction_dict()
SOURCE_DOCSTRING_SCAN = "docstring_scan"    # inspect + ast 抽 docstring
SOURCE_MANUAL = "manual"                    # 显式 register() 调用


# ==========================================================================
# SkillManifest dataclass
# ==========================================================================

@dataclass
class SkillManifest:
    """单个原子能力的完整说明书 + 运行时 KPI。

    必填字段（前 4 个）：
        command            全局唯一 ID，格式 "<module_name>.<command_name>"
                           例: "audio_hands.set_volume" / "memory_finder.search_recent"
        module             python 模块完整路径，例: "l4_hands_pool.l4_audio_hands"
        callable_name      在模块/类内的 callable 名，例: "set_volume" 或 "Hands.execute"
        description        一句话用途（< 80 字），来自 docstring 或 instruction_dict

    可选字段：
        args_schema        入参 schema dict，每个 key 是 arg_name，value 是
                           {"type": "int|str|bool|...", "required": bool, "range"?: [..], "default"?: ...}
        preconditions      运行前必须满足的条件列表（如 "audio_device_available", "wifi"）
        typical_latency_ms 典型耗时（用于 phrasing 决定要不要先说"稍等"）
        failure_modes      已知失败模式（如 "device_not_found", "permission_denied"）
        test_path          关联的测试文件路径（如 "tests/_test_audio_hands.py"），None 表示无测试覆盖
        dangerous_flag     "safe" | "risky" | "dangerous"
        source             "module_manifest" | "instruction_dict" | "docstring_scan" | "manual"

    运行时 KPI（外部不要直接改，用 record_invocation）：
        last_30d_success_rate  滚动 30d 成功率，初始 1.0
        call_count_30d         滚动 30d 调用计数
        last_called_ts         上次调用 unix ts
        last_error             最近一次 error 字符串（截断 200 字）
        registered_at          注册到 registry 的 unix ts
    """
    # 必填
    command: str
    module: str
    callable_name: str
    description: str

    # 可选 manifest 元数据
    args_schema: dict = field(default_factory=dict)
    preconditions: list = field(default_factory=list)
    typical_latency_ms: int = 200
    failure_modes: list = field(default_factory=list)
    test_path: Optional[str] = None
    dangerous_flag: str = DANGER_SAFE
    source: str = SOURCE_MANUAL

    # [P0+18-a.16 / 2026-05-15] 能力诚信约束（capability honesty）
    # 用于 CapabilityClaimValidator —— 拦"我可以运行 X 来查 Y"型越界许诺：
    #   provides:        这个工具**真实**能输出的信息域关键词（小写）。空列表 = 不做白名单检查。
    #   cannot_provide:  这个工具**绝对不能**输出的信息域关键词（小写）。Jarvis 在
    #                    自然语言里许诺这些关键词 + 引用这个 skill 名 → 视为越界许诺。
    # 例 (process_hands.get_process_info):
    #   provides:       ['pid','cpu','memory','executable_path','process_name','create_time']
    #   cannot_provide: ['logged_errors','application_logs','js_exceptions','render_errors',
    #                    'csp_violations','ui_errors','why_app_fails','renderer_state']
    provides: list = field(default_factory=list)
    cannot_provide: list = field(default_factory=list)

    # 运行时 KPI
    last_30d_success_rate: float = 1.0
    call_count_30d: int = 0
    last_called_ts: float = 0.0
    last_error: Optional[str] = None
    registered_at: float = field(default_factory=time.time)

    def __post_init__(self):
        # 校验 dangerous_flag
        if self.dangerous_flag not in VALID_DANGER_LEVELS:
            raise ValueError(
                f"SkillManifest.dangerous_flag must be one of {VALID_DANGER_LEVELS}, "
                f"got {self.dangerous_flag!r}"
            )
        # 校验 command 命名
        if not self.command or '.' not in self.command:
            raise ValueError(
                f"SkillManifest.command must be '<module>.<callable>' format, "
                f"got {self.command!r}"
            )
        # 截断 description
        if self.description and len(self.description) > 200:
            self.description = self.description[:197] + '...'
        # last_error 截断
        if self.last_error and len(self.last_error) > 200:
            self.last_error = self.last_error[:197] + '...'

    def is_healthy(self, min_success_rate: float = 0.7,
                   min_calls_for_judgment: int = 3) -> bool:
        """判定是否健康可用。
        - 调用次数 < min_calls_for_judgment（默认 3）：assume healthy（新工具不歧视）
        - 否则要求 success_rate >= min_success_rate（默认 0.7）
        """
        if self.call_count_30d < min_calls_for_judgment:
            return True
        return self.last_30d_success_rate >= min_success_rate

    def is_dangerous(self) -> bool:
        return self.dangerous_flag == DANGER_DANGEROUS

    def is_risky(self) -> bool:
        return self.dangerous_flag == DANGER_RISKY

    def is_safe(self) -> bool:
        return self.dangerous_flag == DANGER_SAFE

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SkillManifest":
        # 兼容老 jsonl：忽略未知字段
        valid_keys = set(cls.__dataclass_fields__.keys())
        clean = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**clean)

    def render_one_line(self) -> str:
        """渲染为 prompt 注入用的单行摘要。
        例: "audio_hands.set_volume(level: int 0-100) — 设置媒体音量 [risky, ~200ms, healthy]"
        """
        # args
        if self.args_schema:
            arg_parts = []
            for arg_name, arg_spec in self.args_schema.items():
                arg_type = arg_spec.get('type', '?')
                arg_range = arg_spec.get('range')
                if arg_range:
                    arg_parts.append(f"{arg_name}: {arg_type} {arg_range[0]}-{arg_range[1]}")
                else:
                    arg_parts.append(f"{arg_name}: {arg_type}")
            args_str = "(" + ", ".join(arg_parts) + ")"
        else:
            args_str = "()"
        # 健康度
        health_tag = 'healthy' if self.is_healthy() else 'degraded'
        danger_tag = self.dangerous_flag
        return (
            f"{self.command}{args_str} — {self.description} "
            f"[{danger_tag}, ~{self.typical_latency_ms}ms, {health_tag}]"
        )


# ==========================================================================
# SkillRegistry 单例
# ==========================================================================

class SkillRegistry:
    """技能注册中心 — 全局单例。

    使用：
        reg = SkillRegistry.get_instance()
        reg.register(manifest)             # 注册（去重 by command）
        sk = reg.get('audio_hands.set_volume')
        all_healthy = reg.all_healthy(min_success_rate=0.7)
        reg.record_invocation('audio_hands.set_volume', success=True, latency_ms=180)
        prompt_block = reg.to_prompt_block(filter_safe_only=False)

    持久化（L0.3 接入，本 L0.1 仅占位）：
        reg.load(path='memory_pool/skill_registry.jsonl')
        reg.save(path='memory_pool/skill_registry.jsonl')
    """

    _instance: Optional["SkillRegistry"] = None
    _instance_lock = threading.Lock()

    DEFAULT_PATH = os.path.join('memory_pool', 'skill_registry.jsonl')

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        """全局单例。线程安全。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance_for_test(cls):
        """**测试专用** — 清单例。生产代码不要调。"""
        with cls._instance_lock:
            cls._instance = None

    def __init__(self):
        self._skills: dict[str, SkillManifest] = {}
        self._lock = threading.Lock()
        self._dirty = False  # 修改标记，autosave 用
        self._invocation_log: list[dict] = []  # 滚动 30d 调用流水（success/fail/latency/ts）

    # --------------------------------------------------------------
    # 注册
    # --------------------------------------------------------------
    def register(self, manifest: SkillManifest, *, overwrite: bool = False) -> bool:
        """注册一个 manifest。
        - 默认 overwrite=False：如果 command 已存在，**保留旧 KPI**（last_30d_success_rate/
          call_count_30d/last_called_ts/last_error），仅更新元数据（description/args_schema/
          preconditions/typical_latency_ms/failure_modes/test_path/dangerous_flag/source）。
          这是因为 KPI 是宝贵的运行时积累，不能因为重启 + 重扫被清零。
        - overwrite=True：完全替换（含 KPI），适合手动测试时重置。
        返回 True 表示新增；False 表示更新现有。
        """
        with self._lock:
            existing = self._skills.get(manifest.command)
            if existing is None:
                self._skills[manifest.command] = manifest
                self._dirty = True
                return True
            # 已存在
            if overwrite:
                self._skills[manifest.command] = manifest
            else:
                # 保留 KPI，更新元数据
                existing.module = manifest.module
                existing.callable_name = manifest.callable_name
                existing.description = manifest.description
                existing.args_schema = manifest.args_schema
                existing.preconditions = manifest.preconditions
                existing.typical_latency_ms = manifest.typical_latency_ms
                existing.failure_modes = manifest.failure_modes
                existing.test_path = manifest.test_path
                existing.dangerous_flag = manifest.dangerous_flag
                existing.source = manifest.source
            self._dirty = True
            return False

    def unregister(self, command: str) -> bool:
        """显式注销（罕见操作 — 通常 skill 只增不减）。"""
        with self._lock:
            if command in self._skills:
                del self._skills[command]
                self._dirty = True
                return True
            return False

    # --------------------------------------------------------------
    # 查询
    # --------------------------------------------------------------
    def get(self, command: str) -> Optional[SkillManifest]:
        """按 command ID 查 manifest。不存在返回 None。"""
        return self._skills.get(command)

    def has(self, command: str) -> bool:
        return command in self._skills

    def all(self) -> list[SkillManifest]:
        """返回所有 manifest 的快照列表（不影响外部 mutate）。"""
        with self._lock:
            return list(self._skills.values())

    def all_healthy(self, min_success_rate: float = 0.7,
                    min_calls_for_judgment: int = 3,
                    exclude_dangerous: bool = False) -> list[SkillManifest]:
        """OfferGuard 入口：所有健康 + 可对外承诺的 skill。
        - exclude_dangerous=True 时排除 dangerous 档（如 PromiseLedger 自动跑流用此过滤）
        """
        with self._lock:
            result = []
            for sk in self._skills.values():
                if not sk.is_healthy(min_success_rate, min_calls_for_judgment):
                    continue
                if exclude_dangerous and sk.is_dangerous():
                    continue
                result.append(sk)
            return result

    def all_by_danger(self, danger: str) -> list[SkillManifest]:
        """按危险等级筛选。"""
        if danger not in VALID_DANGER_LEVELS:
            raise ValueError(f"danger must be one of {VALID_DANGER_LEVELS}")
        with self._lock:
            return [sk for sk in self._skills.values() if sk.dangerous_flag == danger]

    def count(self) -> int:
        return len(self._skills)

    # --------------------------------------------------------------
    # 运行时 KPI
    # --------------------------------------------------------------
    def record_invocation(self, command: str, *, success: bool,
                          latency_ms: int = 0, error: Optional[str] = None) -> bool:
        """每次 skill 调用后喂回。滚动更新该 manifest 的 KPI。
        返回 True 表示更新成功；False 表示未注册的 skill（忽略）。
        """
        with self._lock:
            sk = self._skills.get(command)
            if sk is None:
                return False
            sk.call_count_30d += 1
            sk.last_called_ts = time.time()
            if not success:
                sk.last_error = (error or 'unknown')[:200]
            # 滚动平均：新调用权重 1/N
            n = sk.call_count_30d
            new_observation = 1.0 if success else 0.0
            sk.last_30d_success_rate = (
                (sk.last_30d_success_rate * (n - 1) + new_observation) / n
            )
            self._dirty = True
            # 流水记录（用于后续做精确 30d 滑窗 — 当前简化为指数滑动）
            self._invocation_log.append({
                'command': command,
                'success': success,
                'latency_ms': latency_ms,
                'ts': time.time(),
                'error': (error or '')[:200] if not success else None,
            })
            # 流水最多保留 5000 条防膨胀
            if len(self._invocation_log) > 5000:
                self._invocation_log = self._invocation_log[-5000:]
            return True

    def get_recent_errors(self, command: str, *, limit: int = 5) -> list[dict]:
        """读最近 N 次失败的流水。OfferGuard 拒绝时打日志可用。"""
        with self._lock:
            errors = [
                e for e in self._invocation_log
                if e['command'] == command and not e['success']
            ]
            return errors[-limit:]

    # --------------------------------------------------------------
    # Prompt 注入渲染
    # --------------------------------------------------------------
    def to_prompt_block(self, *, filter_safe_only: bool = False,
                        only_healthy: bool = True,
                        min_success_rate: float = 0.7,
                        max_skills: int = 50) -> str:
        """[轴3-L2 / 2026-05-15] 渲染为 prompt 可注入的 === AVAILABLE SKILLS === 块。

        参数：
            filter_safe_only  仅列 safe 档（隐藏 risky / dangerous，给保守路径用）
            only_healthy      仅列 healthy（success_rate 达标）
            max_skills        防 prompt 爆炸，最多列 N 条
        """
        with self._lock:
            candidates = list(self._skills.values())

        if only_healthy:
            candidates = [sk for sk in candidates if sk.is_healthy(min_success_rate)]
        if filter_safe_only:
            candidates = [sk for sk in candidates if sk.is_safe()]

        # 按 dangerous_flag 分组排序：safe → risky → dangerous，组内按 command 字母序
        danger_order = {DANGER_SAFE: 0, DANGER_RISKY: 1, DANGER_DANGEROUS: 2}
        candidates.sort(key=lambda sk: (danger_order.get(sk.dangerous_flag, 9), sk.command))

        if len(candidates) > max_skills:
            candidates = candidates[:max_skills]

        if not candidates:
            return "=== AVAILABLE SKILLS ===\n(no healthy skills registered)\n========================"

        lines = ["=== AVAILABLE SKILLS ===",
                 "These are the ONLY actions you can truly perform right now. "
                 "When offering to help Sir, you MUST reference one of these by name. "
                 "Generic offers like 'can I help' or 'shall I take a look' are FORBIDDEN."]
        for sk in candidates:
            lines.append(f"  - {sk.render_one_line()}")
        lines.append(f"========================")
        return '\n'.join(lines)

    # --------------------------------------------------------------
    # 持久化（L0.3 完整接入，L0.1 提供基础接口供测试）
    # --------------------------------------------------------------
    def save(self, path: Optional[str] = None) -> int:
        """落盘 jsonl。返回写入条数。"""
        path = path or self.DEFAULT_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._lock:
            tmp_path = path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                for sk in self._skills.values():
                    f.write(json.dumps(sk.to_dict(), ensure_ascii=False) + '\n')
            # 原子替换
            os.replace(tmp_path, path)
            self._dirty = False
            return len(self._skills)

    def load(self, path: Optional[str] = None) -> int:
        """从 jsonl 加载。返回读取条数。文件不存在返回 0。"""
        path = path or self.DEFAULT_PATH
        if not os.path.exists(path):
            return 0
        loaded = 0
        with self._lock:
            self._skills.clear()
            with open(path, 'r', encoding='utf-8') as f:
                for line_no, raw in enumerate(f, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        sk = SkillManifest.from_dict(d)
                        self._skills[sk.command] = sk
                        loaded += 1
                    except Exception as e:
                        # 单行损坏不阻塞整体加载
                        print(f"[SkillRegistry] load 跳过损坏行 {line_no}: {e}")
            self._dirty = False
        return loaded

    def is_dirty(self) -> bool:
        return self._dirty

    # --------------------------------------------------------------
    # [轴3-L0.3 / 2026-05-15] Bootstrap + autosave 后台线程
    # --------------------------------------------------------------
    def bootstrap(self, *, pools_root: Optional[str] = None,
                  jsonl_path: Optional[str] = None,
                  enable_autosave: bool = True,
                  autosave_interval_s: int = 60) -> dict:
        """启动初始化。CentralNerve.__init__ 调用一行即完成全套。

        步骤：
          1. load() 现有 jsonl（合并已有 KPI）
          2. SkillScanner.scan_all_pools() 扫所有 hand/eye 最新 manifest
          3. register() 每个新的（**保留 KPI**：旧 jsonl 里有的 skill KPI 不被重置）
          4. save() 立刻落盘一次（capture 启动状态）
          5. 启动 autosave daemon（如果 enable_autosave）

        参数：
          pools_root           扫描根目录（默认 '.'）
          jsonl_path           jsonl 路径（默认 SkillRegistry.DEFAULT_PATH）
          enable_autosave      是否启动后台自动保存线程
          autosave_interval_s  每 N 秒检查 dirty 自动 save

        返回 dict：
          {'loaded_from_jsonl': N, 'scanned': N, 'newly_registered': N,
           'total_after_bootstrap': N, 'autosave_started': bool}

        失败容错：任何异常都被吞 + 打印（不影响 CentralNerve 主流程启动）。
        """
        report = {
            'loaded_from_jsonl': 0,
            'scanned': 0,
            'newly_registered': 0,
            'total_after_bootstrap': 0,
            'autosave_started': False,
        }
        path = jsonl_path or self.DEFAULT_PATH
        try:
            report['loaded_from_jsonl'] = self.load(path)
        except Exception as e:
            print(f"[SkillRegistry/bootstrap] load 失败（继续）: {e}")

        try:
            scanned = SkillScanner.scan_all_pools(pools_root or '.')
            report['scanned'] = len(scanned)
            new_count = 0
            for sk in scanned:
                if self.register(sk):
                    new_count += 1
            report['newly_registered'] = new_count
        except Exception as e:
            print(f"[SkillRegistry/bootstrap] scan 失败（继续）: {e}")

        report['total_after_bootstrap'] = self.count()

        try:
            self.save(path)
        except Exception as e:
            print(f"[SkillRegistry/bootstrap] save 失败（继续）: {e}")

        if enable_autosave:
            try:
                self._start_autosave_daemon(path, autosave_interval_s)
                report['autosave_started'] = True
            except Exception as e:
                print(f"[SkillRegistry/bootstrap] autosave 启动失败（继续）: {e}")

        try:
            print(
                f"♻️ [SkillRegistry] bootstrap 完工: "
                f"loaded={report['loaded_from_jsonl']} scanned={report['scanned']} "
                f"new={report['newly_registered']} total={report['total_after_bootstrap']} "
                f"autosave={report['autosave_started']}"
            )
        except Exception:
            pass
        return report

    def _start_autosave_daemon(self, path: str, interval_s: int):
        """后台 daemon：每 interval_s 检查 is_dirty → 自动 save。
        重复调用会跳过（已启动）。"""
        if getattr(self, '_autosave_thread', None) and self._autosave_thread.is_alive():
            return
        self._autosave_path = path
        self._autosave_interval = interval_s
        self._autosave_stop = threading.Event()

        def _loop():
            while not self._autosave_stop.is_set():
                # sleep + 周期性醒来检查 stop
                self._autosave_stop.wait(self._autosave_interval)
                if self._autosave_stop.is_set():
                    break
                try:
                    if self._dirty:
                        self.save(self._autosave_path)
                except Exception as e:
                    print(f"[SkillRegistry/autosave] save 失败（下轮重试）: {e}")

        self._autosave_thread = threading.Thread(
            target=_loop, daemon=True, name='SkillRegistryAutosave'
        )
        self._autosave_thread.start()

    def stop_autosave(self):
        """**测试 / 关机用**。生产代码通常不需要（daemon 进程结束时自然退出）。"""
        if hasattr(self, '_autosave_stop') and self._autosave_stop:
            self._autosave_stop.set()


# ==========================================================================
# 模块级便捷接口
# ==========================================================================

def get_registry() -> SkillRegistry:
    """便捷接口。等价于 SkillRegistry.get_instance()。"""
    return SkillRegistry.get_instance()


# ==========================================================================
# [轴3-L0.4 / 2026-05-15] 运行时 KPI 喂回 helper
# ==========================================================================

def wrap_invocation(command: str, fn, *args, **kwargs):
    """包装一个 callable，自动喂 success/fail/latency 给 registry。

    设计原则：
      - 主流程绝不阻塞：record_invocation 失败被吞 + 打印
      - success 智能判定：
        * 返回 ExecutionResult / 任何 .success 属性 → 用 result.success
        * 返回 bool → 直接当 success
        * 抛异常 → 失败 + error 字符串
        * 其它（None / dict / str） → 视为成功

    使用：
        result = wrap_invocation('audio_hands.set_volume', hand.execute, action)
    """
    start_ts = time.time()
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        latency_ms = int((time.time() - start_ts) * 1000)
        try:
            get_registry().record_invocation(
                command, success=False, latency_ms=latency_ms, error=str(e)[:200],
            )
        except Exception:
            pass
        raise
    latency_ms = int((time.time() - start_ts) * 1000)
    success = True
    error = None
    if hasattr(result, 'success'):
        success = bool(result.success)
        if not success and hasattr(result, 'msg'):
            error = str(result.msg)[:200]
    elif isinstance(result, bool):
        success = result
    try:
        get_registry().record_invocation(
            command, success=success, latency_ms=latency_ms, error=error,
        )
    except Exception:
        pass
    return result


def safe_record(command: str, *, success: bool, latency_ms: int = 0,
                error: Optional[str] = None) -> bool:
    """直接记录的 helper（不调 callable）。任何异常吞掉。"""
    try:
        return get_registry().record_invocation(
            command, success=success, latency_ms=latency_ms, error=error,
        )
    except Exception:
        return False


# ==========================================================================
# [轴3-L1 / 2026-05-15] OfferGuard — 中央闸：贾维斯说出口前必经
# ==========================================================================

# 特殊 require token：表示"必须有任何 healthy safe skill 可承诺"
REQ_ANY_HEALTHY_SAFE = '*ANY_HEALTHY_SAFE*'

# nudge_type → 守门规则配置。
# 设计原则：
#   - 不硬编码在守望者代码里 — 集中在此一处（新加 nudge_type 改这里即可）
#   - 社交类（check_in / late_night / atmosphere）requires=[] —— 社交本身就是兑现
#   - 提议类（offer_help）必须有真实可执行的 safe skill 可 reference
#   - 节奏类（suggest_break / late_night）配 min_interval_s —— 修 path_a/b 双轨绕过的 Cs1
OFFER_REQUIREMENTS = {
    # ---- 社交类（无 skill 要求 + 节奏温和）----
    'check_in': {
        'requires': [],
        'min_interval_s': 1800,
        'note': '社交问候，不承诺动作；30min 节奏',
    },
    'return_greeting': {
        'requires': [],
        'min_interval_s': 60,
        'note': '欢迎归来；快节奏（AFK 归来即触发）',
    },
    'commitment_check': {
        'requires': [],
        'min_interval_s': 0,
        'note': '兑现 Sir 自己的 commit；commit 系统已自带去重',
    },
    'context_switch_alert': {
        'requires': [],
        'min_interval_s': 600,
        'note': '只描述项目切换，不承诺动作',
    },
    'atmosphere': {
        'requires': [],
        'min_interval_s': 1800,
        'note': '闲聊气氛',
    },

    # ---- 节奏建议类（无 skill 要求但严格节奏 — 修 Cs1）----
    'suggest_break': {
        'requires': [],
        'min_interval_s': 7200,  # 2h 节奏 — 同 WellnessGuardian
        'note': '建议休息；2h 间隔（path_a/b 双轨同走此闸，修 10:23 案例）',
    },
    'late_night': {
        'requires': [],
        'min_interval_s': 3600,  # 1h 节奏
        'note': '深夜提醒；1h 间隔',
    },
    'flow_end': {
        'requires': [],
        'min_interval_s': 1800,
        'note': '心流结束建议；30min 间隔',
    },
    'bedtime': {
        'requires': [],
        'min_interval_s': 3600,
        'note': '该睡了；1h 间隔',
    },

    # ---- 提议类（必须有真实能力可 reference — 修 Cs2 "替我排查 403" 宽泛 offer）----
    'offer_help': {
        'requires': [REQ_ANY_HEALTHY_SAFE],
        'min_interval_s': 1200,  # 20min（同时叠加 SmartNudge fingerprint 冷却）
        'note': '主动提议帮助；必须有至少 1 个 healthy safe skill 可 reference',
    },

    # ---- 视觉/被动通道类（轻打扰，节奏宽松）----
    'screen_tease': {'requires': [], 'min_interval_s': 600, 'note': '屏幕轻提示'},
    'background_brief': {'requires': [], 'min_interval_s': 600, 'note': '后台简报'},
    'task_handoff_ready': {'requires': [], 'min_interval_s': 60, 'note': '任务接力就绪'},
    'hydration': {'requires': [], 'min_interval_s': 3600, 'note': '喝水提醒'},
    'stretch': {'requires': [], 'min_interval_s': 3600, 'note': '拉伸提醒'},
    'afternoon': {'requires': [], 'min_interval_s': 3600, 'note': '下午时段问候'},
    'dormant_project': {'requires': [], 'min_interval_s': 86400, 'note': '休眠项目提醒'},
}


class OfferGuard:
    """中央闸：贾维斯说出口前都得过这道门。

    职责：
      1. nudge_type 是否注册（未知 nudge_type → 拒）
      2. required skills 是否 healthy（offer_help → 必须有 1 个 safe healthy）
      3. 节奏（同 nudge_type 上次出口距今 < min_interval_s → 拒）
      4. 拒绝时 publish 'offer_blocked' event_bus 事件（PromiseLedger / 监控用）

    使用：
        ok, reason = OfferGuard.check_offer('suggest_break')
        if not ok:
            bg_log(f"❌ [OfferGuard] suggest_break blocked: {reason}")
            return

    与 NudgeGate 关系：
      - NudgeGate.can_speak 加这道闸作为兜底（守望者忘记调也兜得住）
      - 守望者也可在 publish 前显式调，提前拒掉省下生成话术的 LLM 调用
    """

    # 类级状态（单例语义 — 跨守望者共享 last_offer_ts）
    _last_offer_ts: dict = {}
    _lock = threading.Lock()

    @classmethod
    def reset_for_test(cls):
        """**测试专用**。"""
        with cls._lock:
            cls._last_offer_ts.clear()

    @classmethod
    def check_offer(cls, nudge_type: str, *, registry: Optional[SkillRegistry] = None,
                    publish_event_bus_on_block: bool = True) -> tuple:
        """检查能否 publish。返回 (ok: bool, reason: str)。

        参数：
          nudge_type   nudge 类型字符串
          registry     SkillRegistry 单例（默认 get_registry()）
          publish_event_bus_on_block  True 时拒绝事件投递到 event_bus（要 jarvis_utils
                       的 ConversationEventBus 单例可达，失败被吞）

        [β.5.2 / 2026-05-19] gate_mode 三档 (准则 6 行为弱耦合):
          - hard (默认):     原行为, block 时 publish 'offer_blocked'
          - soft:            block 时 publish + pass 时也 publish 'offer_pass' (双轨观察期)
          - publish_only:    永远 return (True, ...) (永不 hard 拦), 仅 publish 到 SWM
        模式持久化 memory_pool/gate_mode_vocab.json, Sir CLI scripts/gate_mode_dump.py.
        """
        if not nudge_type:
            return True, ''  # 空 nudge_type 不挡（向后兼容）

        # [β.5.2] 读 gate_mode (5s cache, fail-safe→'hard')
        try:
            from jarvis_utils import read_gate_mode
            gate_mode = read_gate_mode('OfferGuard')
        except Exception:
            gate_mode = 'hard'

        spec = OFFER_REQUIREMENTS.get(nudge_type)
        if spec is None:
            # 未注册的 nudge_type — 默认放行 + 记日志（不挡新功能）
            # 但生产部署后要求 unkown nudge_type 必须显式 add 到 OFFER_REQUIREMENTS
            return True, f'unknown_nudge_type:{nudge_type}_default_allow'

        # 内部 evaluate (不 publish, 算 ok/reason)
        ok, reason = cls._evaluate_internal(nudge_type, spec, registry)

        # [β.5.2] publish 策略:
        # hard: block→publish 'offer_blocked' (原行为)
        # soft: block→publish 'offer_blocked' + pass→publish 'offer_pass'
        # publish_only: 同 soft + 永远 return (True, ...)
        if not ok and publish_event_bus_on_block:
            cls._publish_block(nudge_type, reason, True, gate_mode=gate_mode)
        elif ok and gate_mode in ('soft', 'publish_only'):
            cls._publish_pass(nudge_type, gate_mode=gate_mode)

        # publish_only 永不 hard 拦 — 主脑看 SWM 自决
        if gate_mode == 'publish_only':
            return True, f'publish_only_override(was={reason})'
        return ok, reason

    @classmethod
    def _evaluate_internal(cls, nudge_type: str, spec: dict, registry) -> tuple:
        """[β.5.2] 拆出原 check_offer 评估逻辑, 不 publish."""
        # 节奏闸
        min_interval = spec.get('min_interval_s', 0)
        if min_interval > 0:
            with cls._lock:
                last_ts = cls._last_offer_ts.get(nudge_type, 0.0)
            elapsed = time.time() - last_ts
            if elapsed < min_interval:
                remaining = int(min_interval - elapsed)
                return False, f'rhythm_cooldown:remaining_{remaining}s'

        # required skills 闸
        requires = spec.get('requires', []) or []
        if requires:
            reg = registry or get_registry()
            for req in requires:
                if req == REQ_ANY_HEALTHY_SAFE:
                    healthy_safe = [sk for sk in reg.all_healthy() if sk.is_safe()]
                    if not healthy_safe:
                        return False, 'no_healthy_safe_skill_to_offer'
                else:
                    sk = reg.get(req)
                    if sk is None:
                        return False, f'missing_skill:{req}'
                    if not sk.is_healthy():
                        return False, f'degraded_skill:{req}_rate={sk.last_30d_success_rate:.2f}'

        return True, 'ok'

    @classmethod
    def mark_spoken(cls, nudge_type: str):
        """nudge 真出口后调（NudgeGate.mark_spoke 联动）— 更新节奏 last_ts。"""
        with cls._lock:
            cls._last_offer_ts[nudge_type] = time.time()

    @classmethod
    def _publish_block(cls, nudge_type: str, reason: str, enable: bool, *, gate_mode: str = 'hard'):
        """[β.5.2] block decision publish, 加 gate_mode meta."""
        if not enable:
            return
        try:
            from jarvis_utils import bg_log
            bg_log(f"❌ [OfferGuard] {nudge_type} blocked: {reason} (mode={gate_mode})")
        except Exception:
            pass
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus:
                bus.publish(
                    etype='offer_blocked',
                    description=f"OfferGuard blocked nudge '{nudge_type}': {reason} mode={gate_mode}",
                    source='OfferGuard',
                    metadata={
                        'nudge_type': nudge_type,
                        'reason': reason,
                        'decision': 'block',
                        'gate_mode': gate_mode,
                    },
                )
        except Exception:
            pass

    @classmethod
    def _publish_pass(cls, nudge_type: str, *, gate_mode: str = 'soft'):
        """[β.5.2] pass decision publish (soft / publish_only mode 用), 让主脑下轮看
        'OfferGuard 同意了 nudge_type=X' — 配合 SWM evidence 主脑自决.
        """
        try:
            from jarvis_utils import get_event_bus
            bus = get_event_bus()
            if bus:
                bus.publish(
                    etype='offer_blocked',  # 复用 etype, 用 decision 字段区分
                    description=f"OfferGuard passed nudge '{nudge_type}' (mode={gate_mode})",
                    source='OfferGuard',
                    metadata={
                        'nudge_type': nudge_type,
                        'reason': 'ok',
                        'decision': 'pass',
                        'gate_mode': gate_mode,
                    },
                    salience=0.4,  # pass 信号 salience 低 (不抢 evidence)
                )
        except Exception:
            pass


# ==========================================================================
# [轴3-L3 / 2026-05-15] PromiseParser — 主脑 <PROMISE> 标签解析 → PlanLedger
# ==========================================================================

# Promise 标签格式（教 LLM 输出 + 给 Parser 抓）
#
# <PROMISE>
# {
#   "goal": "一句话目标（必填，<= 200 字）",
#   "steps": [
#     {"description": "步骤说明", "skill": "audio_hands.list_devices"},  // skill 可空
#     {"description": "汇总报告", "skill": null}
#   ]
# }
# </PROMISE>
#
# 解析后调 PlanLedger.draft() → state=awaiting_go，等 Sir 说 "go"。
#
# 设计目标：
# - 让"嘴上说 X" → "立刻有可追踪的 plan_id" → "Sir 说 go 再真跑"
# - 修 Cs3：所有"我去做 X"承诺必须落到 ledger，没落地就视为 hallucination

PROMISE_TAG_RE = re.compile(
    r'<PROMISE>\s*(.+?)\s*</PROMISE>',
    re.DOTALL | re.IGNORECASE,
)


class PromiseParseError(Exception):
    pass


class PromiseDraft:
    """单个解析出的承诺草案。draft() 之后变成 PlanLedger plan_id。"""

    def __init__(self, goal: str, steps: list, raw_json: str = '',
                 required_skills: list = None):
        self.goal = (goal or '')[:300]
        self.steps = steps or []
        self.raw_json = raw_json
        # 自动从 steps 抽 required_skills
        self.required_skills = required_skills or [
            s.get('skill') for s in self.steps if s.get('skill')
        ]
        # 标记是否含 dangerous skill（PromiseLedger 自动跑前必须检查）
        self._dangerous_check_done = False
        self._dangerous_skills = []

    def to_dict(self) -> dict:
        return {
            'goal': self.goal,
            'steps': self.steps,
            'required_skills': self.required_skills,
        }

    def has_dangerous_skill(self, registry: Optional[SkillRegistry] = None) -> bool:
        """检查 steps 中引用的任何 skill 是否 dangerous_flag=='dangerous'。
        缓存结果（一次性扫）。"""
        if self._dangerous_check_done:
            return bool(self._dangerous_skills)
        reg = registry or get_registry()
        self._dangerous_skills = []
        for skill_name in self.required_skills:
            if not skill_name:
                continue
            sk = reg.get(skill_name)
            if sk is not None and sk.is_dangerous():
                self._dangerous_skills.append(skill_name)
        self._dangerous_check_done = True
        return bool(self._dangerous_skills)

    def get_dangerous_skills(self, registry: Optional[SkillRegistry] = None) -> list:
        self.has_dangerous_skill(registry)  # 触发缓存
        return list(self._dangerous_skills)

    def get_unknown_skills(self, registry: Optional[SkillRegistry] = None) -> list:
        """步骤中引用但 registry 里不存在的 skill。LLM 编造的 skill 名应该被抓。"""
        reg = registry or get_registry()
        return [s for s in self.required_skills
                if s and reg.get(s) is None]


class PromiseParser:
    """从 LLM 输出文本抽 <PROMISE> 标签 → PromiseDraft 列表。"""

    @classmethod
    def extract_all(cls, text: str) -> list:
        """返回所有解析成功的 PromiseDraft（解析失败的 silently skip）。"""
        if not text:
            return []
        out = []
        for m in PROMISE_TAG_RE.finditer(text):
            raw = m.group(1).strip()
            try:
                draft = cls._parse_one(raw)
                out.append(draft)
            except PromiseParseError:
                # 损坏的 PROMISE 标签 — 不阻塞主流程，由 Integrity Check 抓
                continue
        return out

    @classmethod
    def _parse_one(cls, raw_json: str) -> PromiseDraft:
        try:
            data = json.loads(raw_json)
        except Exception as e:
            raise PromiseParseError(f"invalid JSON: {e}")
        if not isinstance(data, dict):
            raise PromiseParseError(f"PROMISE root must be dict, got {type(data).__name__}")
        goal = data.get('goal', '').strip()
        if not goal:
            raise PromiseParseError("PROMISE missing 'goal'")
        steps = data.get('steps', [])
        if not isinstance(steps, list):
            raise PromiseParseError(f"'steps' must be list, got {type(steps).__name__}")
        norm_steps = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise PromiseParseError(f"step[{i}] must be dict")
            desc = step.get('description', '').strip()
            if not desc:
                raise PromiseParseError(f"step[{i}] missing 'description'")
            skill = step.get('skill')
            # [轴3-L3.2 / 2026-05-15] step.args — LLM 写好执行参数（如 {"level": 30}）
            # 容错：args 缺省 / 不是 dict / 不可序列化 → 视为 {}
            raw_args = step.get('args', {})
            if not isinstance(raw_args, dict):
                raw_args = {}
            else:
                # 防 LLM 塞太大；keys/values 都做 str 化截断兜底
                raw_args = {str(k)[:80]: v for k, v in list(raw_args.items())[:20]}
            norm_steps.append({
                'description': desc[:300],
                'skill': skill if skill else None,
                'args': raw_args,
                # 'status' 在落入 PlanLedger 时由 ledger 自己加
            })
        return PromiseDraft(goal=goal, steps=norm_steps, raw_json=raw_json)

    @classmethod
    def has_promise_tag(cls, text: str) -> bool:
        """快速检测：text 是否含 PROMISE 标签（不解析内容）。"""
        return bool(text) and bool(PROMISE_TAG_RE.search(text))

    @classmethod
    def draft_to_ledger(cls, drafts, ledger) -> list:
        """把 PromiseDraft 列表写入 PlanLedger。返回 plan_id 列表。

        [轴3-L3.2 / 2026-05-15] 传完整 step dict（含 skill + args）让 PromiseExecutor
        能跑工具；PlanLedger._normalize_step 已支持保留这些字段。
        """
        if ledger is None or not drafts:
            return []
        plan_ids = []
        for draft in drafts:
            try:
                # PlanLedger.draft 接受 (goal, steps, metadata)
                # steps 用完整 dict，让 PromiseExecutor 能拿到 skill/args
                plan_id = ledger.draft(
                    goal=draft.goal,
                    steps=[
                        {
                            'description': s.get('description', ''),
                            'skill': s.get('skill'),
                            'args': s.get('args') or {},
                            'status': 'pending',
                            'retry_count': 0,
                        }
                        for s in draft.steps
                    ],
                    metadata={
                        'source': 'promise_parser',
                        'required_skills': draft.required_skills,
                        'raw_json': draft.raw_json[:500],
                        'dangerous_skills': draft.get_dangerous_skills(),
                        'unknown_skills': draft.get_unknown_skills(),
                    },
                    auto_await_go=True,
                )
                plan_ids.append(plan_id)
            except Exception as e:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [PromiseParser] draft_to_ledger 失败: {e}")
                except Exception:
                    pass
                continue
        return plan_ids


# Promise 协议 directive 字符串（给 prompt 用）
PROMISE_PROTOCOL_DIRECTIVE = """[轴3-L3 PROMISE PROTOCOL — 言出必行]:
When you intend to perform a MULTI-STEP action that Sir might want to confirm before you start
(e.g. "shall I diagnose the 403 issue?", "let me check the key router state and propose a fix"),
output a PROMISE tag BEFORE doing it. The tag is JSON inside <PROMISE>...</PROMISE>:

<PROMISE>
{
  "goal": "<one-sentence goal in Chinese or English>",
  "steps": [
    {"description": "<step 1>", "skill": "<skill_name from AVAILABLE SKILLS, or null>",
     "args": {"<arg_name>": <value>}},
    {"description": "<step 2>", "skill": null, "args": {}}
  ]
}
</PROMISE>

Rules:
1. Each `skill` MUST be from [AVAILABLE SKILLS] block above (or null for steps that don't call a tool).
2. Do NOT invent skill names. If a step needs a skill that isn't listed, set skill: null and describe.
3. `args` is the parameter dict passed to the skill (same shape as <FAST_CALL> params). Omit or use {} if unsure.
4. After PROMISE, say ONE short sentence to Sir (e.g. "Shall I proceed, Sir?"). Wait for "go" / "yes" / "好".
5. Use this ONLY for multi-step actions. Trivial single-tool calls just use <FAST_CALL> directly.
6. NEVER write a PROMISE you cannot back with at least one real skill from AVAILABLE SKILLS.

=== ACTIVATING / CANCELLING / RESUMING A PROMISE ===
When the [ACTIVE PLAN] block above shows a plan in a non-terminal state:

(a) State `awaiting_go` (just drafted, waiting for Sir's green light):
- If Sir confirms ("go" / "yes" / "嗯" / "好" / "好的" / "来吧" / "可以" / "行" / "do it" / "sure"):
  Output: <ACTIVATE_PLAN>plan_id_from_active_plan_block</ACTIVATE_PLAN>
  Then ONE short sentence: "On it, Sir." / "Right away."
- If Sir cancels ("cancel" / "算了" / "不用了" / "取消" / "forget it" / "drop it"):
  Output: <CANCEL_PLAN>plan_id_from_active_plan_block</CANCEL_PLAN>
  Then ONE short acknowledgement: "As you wish." / "Noted."
- If Sir is silent or asks an unrelated question, do NOT emit either tag — the plan stays awaiting_go.

(b) State `paused` with reason `dangerous_confirm` (executor saw dangerous skill, asked Sir to reconfirm):
- If Sir reconfirms (same go-words above + clearly accepts the danger):
  Output: <RESUME_PLAN>plan_id</RESUME_PLAN>
  Then ONE short sentence: "Proceeding, Sir."
- If Sir hesitates / refuses → <CANCEL_PLAN>plan_id</CANCEL_PLAN>.

(c) State `paused` with reason `clarification` (a step failed twice, executor needs guidance):
- The pause record includes `failed_step_idx` and `failed_step_error` in the [ACTIVE PLAN] block.
- You SHOULD say ONE short sentence to Sir summarising what failed (in Sir's language, < 16 words),
  then wait for Sir's instruction. Three legal follow-ups:
    1. Sir says "再试一次 / try again / retry" → <RESUME_PLAN>plan_id</RESUME_PLAN>
       (the failed step's retry counter resets, executor will re-run it)
    2. Sir gives a new approach → emit a brand new <PROMISE> AND <CANCEL_PLAN>old_id</CANCEL_PLAN>
    3. Sir gives up → <CANCEL_PLAN>plan_id</CANCEL_PLAN>

The system runs the steps in order and reports results back to you on subsequent turns —
the [ACTIVE PLAN] block always shows current step status (○ pending / ◐ running / ✓ done / ✗ failed)
and the most recent step's `result` text.
"""


# [P0+18-a.3 / 2026-05-15] Mini 版 directive（给 SHORT_CHAT tier 用，体积控在 ~250 字符）
# 全量 directive 太长会把 SHORT_CHAT prompt 撑爆，但 Sir 实测大量"动词请求"（排查/帮我看/删 X）
# 都被分到 SHORT_CHAT — 必须有这个 mini 版让主脑知道：多步动作请用 PROMISE，单工具用 FAST_CALL。
PROMISE_PROTOCOL_DIRECTIVE_MINI = """[PROMISE PROTOCOL — mini]:
Multi-step actions (diagnose/inspect/then-act) → emit <PROMISE>{"goal":"...","steps":[{"description":"...","skill":"<from AVAILABLE SKILLS>","args":{}}]}</PROMISE> + ask "Shall I proceed, Sir?"
Single tool call → use <FAST_CALL> directly. NEVER claim an action you didn't actually invoke.
When [ACTIVE PLAN] shows awaiting_go and Sir says go/yes/好 → emit <ACTIVATE_PLAN>plan_id</ACTIVATE_PLAN>.
When [ACTIVE PLAN] shows paused (dangerous_confirm or step failed) → see [ACTIVE PLAN] for details and react accordingly (RESUME_PLAN / CANCEL_PLAN / new PROMISE).
"""


# ==========================================================================
# [轴3-L3.2 / 2026-05-15] PromiseActivator — 解析 ACTIVATE/CANCEL 标签 → 状态变更
# ==========================================================================

ACTIVATE_TAG_RE = re.compile(
    r'<ACTIVATE_PLAN>\s*([^<]+?)\s*</ACTIVATE_PLAN>',
    re.DOTALL | re.IGNORECASE,
)
CANCEL_TAG_RE = re.compile(
    r'<CANCEL_PLAN>\s*([^<]+?)\s*</CANCEL_PLAN>',
    re.DOTALL | re.IGNORECASE,
)
# [轴3-L3.3 / 2026-05-15] RESUME_PLAN — paused 状态（dangerous_confirm / clarification）回 RUNNING
RESUME_TAG_RE = re.compile(
    r'<RESUME_PLAN>\s*([^<]+?)\s*</RESUME_PLAN>',
    re.DOTALL | re.IGNORECASE,
)


class PromiseActivator:
    """解析主脑输出的 <ACTIVATE_PLAN> / <CANCEL_PLAN> 标签 → ledger 状态变更。

    设计原则：
      - LLM 决定何时 ACTIVATE / CANCEL（看 prompt 中 ACTIVE PLAN 块 + Sir 当前输入）
      - nerve 只做状态机操作（不替 LLM 做意图识别）
      - LLM 输出的 plan_id 可能是 8 字符短前缀，用 prefix 匹配 PlanLedger 里的全 id
      - 任何异常都被吞，不影响主流程
    """

    @classmethod
    def extract_activate_ids(cls, text: str) -> list:
        """抽出所有 <ACTIVATE_PLAN>...</ACTIVATE_PLAN> 中的 plan_id。"""
        if not text:
            return []
        return [m.group(1).strip() for m in ACTIVATE_TAG_RE.finditer(text)]

    @classmethod
    def extract_cancel_ids(cls, text: str) -> list:
        if not text:
            return []
        return [m.group(1).strip() for m in CANCEL_TAG_RE.finditer(text)]

    @classmethod
    def extract_resume_ids(cls, text: str) -> list:
        if not text:
            return []
        return [m.group(1).strip() for m in RESUME_TAG_RE.finditer(text)]

    @classmethod
    def has_any_tag(cls, text: str) -> bool:
        if not text:
            return False
        return bool(
            ACTIVATE_TAG_RE.search(text)
            or CANCEL_TAG_RE.search(text)
            or RESUME_TAG_RE.search(text)
        )

    @classmethod
    def _resolve_plan_id(cls, partial_id: str, ledger) -> Optional[str]:
        """LLM 给的 plan_id 可能是短前缀（如 '7a3f9b1c'），返回 ledger 里的完整 id。
        多个匹配 → 返回最新创建的（last_state_change 最新）。无匹配 → None。"""
        if not partial_id or not ledger:
            return None
        partial = partial_id.strip().lower()
        with ledger._lock:
            candidates = [
                (pid, plan) for pid, plan in ledger._plans.items()
                if pid.lower().startswith(partial) or pid.lower() == partial
            ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[1]['last_state_change'], reverse=True)
        return candidates[0][0]

    @classmethod
    def activate_from_text(cls, text: str, ledger) -> list:
        """解析 ACTIVATE 标签 + 调 ledger.set_state(RUNNING)。返回成功激活的 plan_id 列表。"""
        if ledger is None:
            return []
        activated = []
        for partial in cls.extract_activate_ids(text):
            full_id = cls._resolve_plan_id(partial, ledger)
            if full_id is None:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [PromiseActivator] ACTIVATE_PLAN id={partial!r} 在 ledger 中找不到")
                except Exception:
                    pass
                continue
            ok = ledger.set_state(full_id, ledger.STATE_RUNNING, reason='sir_confirmed_go')
            if ok:
                activated.append(full_id)
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🚀 [PromiseLedger] plan {full_id[:8]} → RUNNING (Sir confirmed)")
                except Exception:
                    pass
            else:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [PromiseActivator] set_state({full_id[:8]}, RUNNING) 拒绝（非法跃迁）")
                except Exception:
                    pass
        return activated

    @classmethod
    def cancel_from_text(cls, text: str, ledger) -> list:
        """解析 CANCEL 标签 + ledger.set_state(CANCELLED)。"""
        if ledger is None:
            return []
        cancelled = []
        for partial in cls.extract_cancel_ids(text):
            full_id = cls._resolve_plan_id(partial, ledger)
            if full_id is None:
                continue
            ok = ledger.set_state(full_id, ledger.STATE_CANCELLED, reason='sir_cancelled')
            if ok:
                cancelled.append(full_id)
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"🗑️ [PromiseLedger] plan {full_id[:8]} → CANCELLED (Sir said no)")
                except Exception:
                    pass
        return cancelled

    @classmethod
    def resume_from_text(cls, text: str, ledger) -> list:
        """[轴3-L3.3] 解析 RESUME 标签 + ledger.set_state(PAUSED → RUNNING)。

        触发时机：
          - paused_for_dangerous_confirm: Sir 二次确认 → 标 metadata['dangerous_confirmed']=True
          - paused_for_clarification: Sir 说"再试一次" → 重置 failed step 的 status/retry_count
          - 其它任意 paused 状态: 直接复活 (Sir 主动 resume)
        """
        if ledger is None:
            return []
        resumed = []
        for partial in cls.extract_resume_ids(text):
            full_id = cls._resolve_plan_id(partial, ledger)
            if full_id is None:
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"⚠️ [PromiseActivator] RESUME_PLAN id={partial!r} 在 ledger 中找不到")
                except Exception:
                    pass
                continue
            with ledger._lock:
                plan = ledger._plans.get(full_id)
                if not plan:
                    continue
                meta = plan.setdefault('metadata', {})
                # dangerous 二次确认：标位 dangerous_confirmed
                if meta.get('paused_for_dangerous_confirm'):
                    meta['dangerous_confirmed'] = True
                    meta.pop('paused_for_dangerous_confirm', None)
                # clarification 重试：把 failed step 重置为 pending + 清 retry_count
                if meta.get('paused_for_clarification'):
                    failed_idx = meta.get('failed_step_idx', -1)
                    if 0 <= failed_idx < len(plan['steps']):
                        plan['steps'][failed_idx]['status'] = 'pending'
                        plan['steps'][failed_idx]['retry_count'] = 0
                    meta.pop('paused_for_clarification', None)
                    meta.pop('failed_step_idx', None)
                    meta.pop('failed_step_error', None)
            ok = ledger.set_state(full_id, ledger.STATE_RUNNING, reason='sir_resumed')
            if ok:
                resumed.append(full_id)
                try:
                    from jarvis_utils import bg_log
                    bg_log(f"▶️ [PromiseLedger] plan {full_id[:8]} → RUNNING (Sir resumed)")
                except Exception:
                    pass
        return resumed


# ==========================================================================
# [轴3-L0.2 / 2026-05-15] SkillScanner — 自动扫描器（AST 静态解析，零副作用）
# ==========================================================================

import ast
import re
import glob


class SkillScanner:
    """自动扫描器。从 l4_hands_pool / l2_eyes_pool 等目录抽 SkillManifest。

    设计原则
    --------
    1. **零副作用**：用纯 ast 静态解析，不 import 模块（避免 l4_terminal_hands 的
       "点火" print / l4_memory_hands 的 DB 连接 / l4_audio_hands 的 PowerShell 调用）
    2. **零硬编码**：每条命令的 dangerous_flag 通过命令名启发式 + 模块级 MANIFEST
       的 `command_dangers` 显式声明（如果有）二选一推导
    3. **保守安全**：未命中启发式 → 默认 RISKY（不假定 SAFE）
    4. **通用复用**：l2 eyes / l4 hands 风格相同 → 同一套 scan_pool() 即可

    输出
    ----
    list[SkillManifest]，调用方决定 register 哪些。

    使用
    ----
        scanner = SkillScanner()
        skills = scanner.scan_pool('l4_hands_pool')
        for sk in skills:
            registry.register(sk)
    """

    # ---- 命令名启发式（按 verb 前缀 / 子串判定）----
    # 设计原则：
    # - SAFE = 纯读、状态查询、不改变任何系统状态、不影响 Sir 视野/听觉
    # - RISKY = 影响系统但完全可恢复（音量、剪贴板、窗口、通知、屏幕截取）
    # - DANGEROUS = 不可逆 / 跑代码 / 删除 / 模拟键鼠输入（可越权点 Sir 没看到的位置）
    SAFE_VERBS = (
        'get', 'list', 'read', 'find', 'search', 'check', 'fetch',
        'view', 'count', 'inspect', 'report', 'status', 'peek', 'detect',
        'scan', 'observe', 'query', 'lookup', 'screenshot', 'is',
        'has', 'wait',  # is_running / wait_for_text 是查询不是动作
    )
    RISKY_VERBS = (
        'set', 'change', 'update', 'modify', 'add', 'append', 'write',
        'launch', 'open', 'close', 'mute', 'unmute', 'play', 'pause',
        'send', 'create', 'make', 'copy', 'move', 'switch', 'toggle',
        'register', 'subscribe', 'unsubscribe', 'navigate',
        'minimize', 'maximize', 'restore', 'hide', 'cascade', 'tile',
        'flash', 'beep', 'toast', 'balloon', 'msgbox',  # 通知类完全可恢复
        'focus', 'topmost', 'configure', 'show',  # show 是动作，移出 SAFE
        'next', 'prev', 'previous', 'stop', 'start',
    )
    DANGEROUS_VERBS = (
        'delete', 'remove', 'kill', 'clear', 'forge', 'exec', 'run',
        'install', 'uninstall', 'wipe', 'reset', 'destroy', 'execute',
        'invoke', 'shell', 'powershell', 'rm', 'rmdir', 'overwrite',
        'format', 'shutdown', 'reboot', 'restart',
        # 模拟键鼠输入：可越权点击 Sir 没看到的元素 / 输入意外字符 → DANGEROUS
        'click', 'type', 'press', 'scroll', 'drag', 'hotkey', 'paste',
        'key',  # key_up / key_down / key_press
    )

    @classmethod
    def infer_dangerous_flag(cls, command_name: str) -> str:
        """从命令名启发式判定危险等级。

        匹配策略（**精确边界匹配** — 避免 'is_running' 误匹配 'run'）：
        - 命令名完全等于 verb
        - 命令名以 'verb_' 开头（前缀匹配）
        - 命令名以 '_verb' 结尾（后缀匹配）
        - 命令名含 '_verb_' 子串（中间匹配，两侧 _ 边界）

        优先级：**SAFE > DANGEROUS > RISKY**
        - SAFE 优先：因为查询动词（is/get/find）一旦匹配就应该是只读
        - 然后 DANGEROUS：危险动词必须升级
        - 最后 RISKY：默认
        """
        cmd_lower = command_name.lower()

        def _match_any(verb_set):
            for verb in verb_set:
                if cmd_lower == verb:
                    return True
                if cmd_lower.startswith(verb + '_'):
                    return True
                if cmd_lower.endswith('_' + verb):
                    return True
                if ('_' + verb + '_') in cmd_lower:
                    return True
            return False

        # SAFE 优先：is_running / get_volume / find_process 这种查询绝不能升级
        if _match_any(cls.SAFE_VERBS):
            return DANGER_SAFE
        # DANGEROUS 次优先：危险动作必须升级
        if _match_any(cls.DANGEROUS_VERBS):
            return DANGER_DANGEROUS
        # RISKY 兜底
        if _match_any(cls.RISKY_VERBS):
            return DANGER_RISKY
        # 未命中 → 默认 RISKY（保守 — 强制 Sir 显式 mark safe 才提级）
        return DANGER_RISKY

    # ---- 解析 get_instruction_dict() 返回字符串 ----
    # 格式：1. "command_name": {arg JSON 或 {}} — description...（— 或 - 都接受）
    # 兼容多行 description（直到下一个 N. " 数字 + 空格 + 引号）
    _CMD_LINE_RE = re.compile(
        r'(\d+)\.\s*'                       # 1.
        r'["\u201c]([^"\u201d]+)["\u201d]'  # "command_name" (直引号或中文引号)
        r'\s*:\s*'                          # :
        r'(\{[^\}]*\})'                     # {args JSON 或 {}}
        r'\s*[—\-]\s*'                      # — 或 -
        r'(.+?)'                            # description
        r'(?=\n\s*\d+\.\s*["\u201c]|\Z)',   # 下一个序号或字符串末尾
        re.DOTALL,
    )

    @classmethod
    def parse_instruction_dict(cls, dict_text: str) -> list:
        """解析 get_instruction_dict() 字符串。
        返回 list[{command, args_text, description}]。

        例：输入
            '1. "list_devices": {} — 列举音频输出设备\\n2. "set_volume": {"level": ...} — 设置...'
        输出：
            [{'command': 'list_devices', 'args_text': '{}', 'description': '列举音频输出设备'},
             {'command': 'set_volume',   'args_text': '{"level": ...}', 'description': '设置...'}]
        """
        if not dict_text:
            return []
        out = []
        seen = set()  # 同名 command 去重（取第一次出现）
        for m in cls._CMD_LINE_RE.finditer(dict_text):
            cmd = m.group(2).strip()
            if not cmd or cmd in seen:
                continue
            seen.add(cmd)
            args_text = m.group(3).strip()
            desc = m.group(4).strip()
            # 多行 desc 折成单行 + 截断
            desc = re.sub(r'\s+', ' ', desc)
            if len(desc) > 200:
                desc = desc[:197] + '...'
            out.append({
                'command': cmd,
                'args_text': args_text,
                'description': desc,
            })
        return out

    @classmethod
    def args_text_to_schema(cls, args_text: str) -> dict:
        """把 '{"level": <0-100 整数, 必填>}' 这种半 JSON 文本转成 args_schema dict。
        失败时返回空 dict（不抛）。"""
        if not args_text or args_text == '{}':
            return {}
        # 尽量真 JSON 解析
        try:
            parsed = json.loads(args_text)
            if isinstance(parsed, dict):
                schema = {}
                for k, v in parsed.items():
                    schema[k] = {'type': type(v).__name__, 'example': v}
                return schema
        except Exception:
            pass
        # 失败：抽 key 名 + 用文本占位
        keys = re.findall(r'"(\w+)"\s*:', args_text)
        return {k: {'type': 'unknown', 'raw_spec': args_text[:80]} for k in keys}

    # ---- AST 静态读模块 MANIFEST + get_instruction_dict() ----

    @classmethod
    def parse_module_file(cls, file_path: str) -> dict:
        """用 ast 静态解析 .py 文件，抽：
          - module_manifest: 模块级 MANIFEST dict（name / description / requires_eyes / 其他）
          - instruction_text: 主类的 get_instruction_dict() 返回字符串
          - main_class: 主类名（Hands / Eyes）
          - source_text: 完整源文本（用于副本启发式如检测 import subprocess）

        失败 → 返回 {'error': 'reason'}。
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                src = f.read()
            tree = ast.parse(src, filename=file_path)
        except Exception as e:
            return {'error': f'parse_failed: {e}'}

        out = {
            'module_manifest': None,
            'instruction_text': None,
            'main_class': None,
            'source_text': src,
        }

        # 1. 找模块级 MANIFEST = {...}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    if node.targets[0].id == 'MANIFEST' and isinstance(node.value, ast.Dict):
                        out['module_manifest'] = cls._ast_dict_to_python(node.value)
                        break

        # 2. 找主类（Hands 或 Eyes 优先；其它取首个 ClassDef）
        main_cls = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in ('Hands', 'Eyes'):
                    main_cls = node
                    break
                if main_cls is None:
                    main_cls = node
        if main_cls is None:
            return out
        out['main_class'] = main_cls.name

        # 3. 在主类里找 get_instruction_dict
        for node in main_cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == 'get_instruction_dict':
                # 找 return 字符串字面量
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return) and sub.value is not None:
                        v = sub.value
                        if isinstance(v, ast.Constant) and isinstance(v.value, str):
                            out['instruction_text'] = v.value
                            break
                break
        return out

    @classmethod
    def _ast_dict_to_python(cls, dict_node: ast.Dict) -> dict:
        """ast.Dict 节点转 python dict（仅支持字面量 key/value：str/int/float/bool/list/dict）。
        非字面量 value 用字符串占位 '<expr>'。"""
        out = {}
        for k_node, v_node in zip(dict_node.keys, dict_node.values):
            try:
                k = ast.literal_eval(k_node)
            except Exception:
                continue
            try:
                v = ast.literal_eval(v_node)
            except Exception:
                v = '<expr>'
            out[str(k)] = v
        return out

    # ---- 公共扫描接口 ----

    @classmethod
    def infer_module_danger_hint(cls, source_text: str) -> Optional[str]:
        """从源码 import / 调用启发式推断"模块整体危险倾向"。
        若命中 → 返回该 hint，调用方可作 per-command 默认值的"上限"约束（不会高于 hint）。
        若未命中 → 返回 None（按 per-command 启发式）。

        启发式：
          - exec / eval / os.system / shutil.rmtree / os.remove → DANGEROUS
          - subprocess + powershell / cmd / shell=True → DANGEROUS
          - open(... 'w') / open(... 'a') → 至少 RISKY
          - 仅 ctypes + 仅读 → SAFE
        """
        if 'os.system(' in source_text or 'shutil.rmtree(' in source_text:
            return DANGER_DANGEROUS
        if 'os.remove(' in source_text or 'os.unlink(' in source_text:
            return DANGER_DANGEROUS
        if re.search(r'\bexec\s*\(', source_text) or re.search(r'\beval\s*\(', source_text):
            return DANGER_DANGEROUS
        if 'subprocess' in source_text and re.search(r'(powershell|cmd\.exe|/bin/sh|shell=True)', source_text):
            # 看是否有 write 路径
            if re.search(r'(SetVolume|kill|taskkill|delete|remove|format|shutdown)', source_text, re.IGNORECASE):
                return DANGER_DANGEROUS
            return DANGER_RISKY
        if re.search(r"open\([^)]*['\"]w['\"]", source_text) or re.search(r"open\([^)]*['\"]a['\"]", source_text):
            return DANGER_RISKY
        return None

    @classmethod
    def scan_module_file(cls, file_path: str) -> list[SkillManifest]:
        """扫一个 .py 文件，输出 SkillManifest 列表。"""
        parsed = cls.parse_module_file(file_path)
        if 'error' in parsed:
            return []
        module_manifest = parsed.get('module_manifest')
        instruction_text = parsed.get('instruction_text')
        if not module_manifest or not instruction_text:
            return []
        module_name = module_manifest.get('name', '')
        module_desc = module_manifest.get('description', '')
        if not module_name:
            return []

        # 模块声明的 dangerous override（可选）
        # 例：MANIFEST = {..., "command_dangers": {"delete_record": "dangerous", "search_memory": "safe"}}
        explicit_dangers = module_manifest.get('command_dangers', {}) or {}

        # [P0+18-a.16 / 2026-05-15] 模块声明的能力诚信元数据（capability honesty）—— 可选
        # 例：MANIFEST = {..., "command_provides": {"get_process_info": ["pid","cpu","memory"]},
        #                       "command_cannot_provide": {"get_process_info": ["logged_errors",...]}}
        # 容错：不是 dict → 视为空
        explicit_provides = module_manifest.get('command_provides') or {}
        explicit_cannot = module_manifest.get('command_cannot_provide') or {}
        if not isinstance(explicit_provides, dict):
            explicit_provides = {}
        if not isinstance(explicit_cannot, dict):
            explicit_cannot = {}

        # 模块整体危险倾向（启发式）
        module_hint = cls.infer_module_danger_hint(parsed['source_text'])

        # 解析指令字典
        commands = cls.parse_instruction_dict(instruction_text)

        # 推导 module_path（从文件路径还原；跨盘符 relpath 失败 → fallback 用文件名）
        try:
            rel_path = os.path.relpath(file_path).replace(os.sep, '/').replace('.py', '').replace('/', '.')
            # 兜底：包含 .. 的路径（cwd 在另一目录）也用绝对裸文件名
            if '..' in rel_path:
                raise ValueError('relpath has ..')
        except (ValueError, OSError):
            base = os.path.splitext(os.path.basename(file_path))[0]
            rel_path = base

        out = []
        for cmd in commands:
            cmd_name = cmd['command']
            global_cmd = f"{module_name}.{cmd_name}"

            # dangerous_flag 决策（per-command 是 source of truth）：
            # 1. 模块显式声明 优先（如 command_dangers["set_volume"] = "risky"）
            # 2. 否则按命令名启发式
            # 注意：module_hint **不再**作为强制上限 —— 否则同模块的 safe 纯读
            # 命令（如 audio_hands.list_devices / input_hands.get_pos）会被模块里另一条
            # dangerous 命令（如 kill_process）"连坐"误升级。module_hint 仅供 Sir 知情。
            if cmd_name in explicit_dangers and explicit_dangers[cmd_name] in VALID_DANGER_LEVELS:
                danger = explicit_dangers[cmd_name]
            else:
                danger = cls.infer_dangerous_flag(cmd_name)

            # [P0+18-a.16] capability honesty 字段：lower + 去重 + 列表化兜底
            def _norm_capability_list(raw):
                if not raw:
                    return []
                if isinstance(raw, str):
                    raw = [raw]
                if not isinstance(raw, (list, tuple)):
                    return []
                seen = set()
                out_list = []
                for item in raw:
                    if not isinstance(item, str):
                        continue
                    s = item.strip().lower()
                    if s and s not in seen:
                        seen.add(s)
                        out_list.append(s)
                return out_list

            # [P0+18-a.16] cannot_provide 支持 `_shared_` 合并（同模块通用黑名单）
            # 例：MANIFEST 写 {'_shared_': ['logged_errors', ...]} 后，每个 command
            # 自动继承这些（再叠加自己单独声明的）→ 避免逐个 command 重复列。
            _cmd_cannot = _norm_capability_list(explicit_cannot.get(cmd_name))
            _shared_cannot = _norm_capability_list(explicit_cannot.get('_shared_'))
            _merged_cannot = list(dict.fromkeys(_shared_cannot + _cmd_cannot))  # 去重保序
            _cmd_provides = _norm_capability_list(explicit_provides.get(cmd_name))
            _shared_provides = _norm_capability_list(explicit_provides.get('_shared_'))
            _merged_provides = list(dict.fromkeys(_shared_provides + _cmd_provides))

            sk = SkillManifest(
                command=global_cmd,
                module=rel_path,
                callable_name=f"{parsed.get('main_class', 'Hands')}.execute({cmd_name})",
                description=cmd['description'] or module_desc,
                args_schema=cls.args_text_to_schema(cmd['args_text']),
                dangerous_flag=danger,
                source=SOURCE_INSTRUCTION_DICT,
                provides=_merged_provides,
                cannot_provide=_merged_cannot,
            )
            out.append(sk)
        return out

    @classmethod
    def scan_pool(cls, pool_dir: str) -> list[SkillManifest]:
        """扫一个 pool 目录（l4_hands_pool / l2_eyes_pool）下所有 .py。
        返回所有 SkillManifest 的合并列表。"""
        if not os.path.isdir(pool_dir):
            return []
        out = []
        for fp in sorted(glob.glob(os.path.join(pool_dir, '*.py'))):
            base = os.path.basename(fp)
            if base.startswith('_') or base == '__init__.py':
                continue
            try:
                out.extend(cls.scan_module_file(fp))
            except Exception as e:
                print(f"[SkillScanner] 扫 {fp} 失败: {e}")
        return out

    @classmethod
    def scan_all_pools(cls, root: str = '.') -> list[SkillManifest]:
        """扫 l4_hands_pool + l2_eyes_pool 所有 hands/eyes。"""
        out = []
        for sub in ('l4_hands_pool', 'l2_eyes_pool'):
            out.extend(cls.scan_pool(os.path.join(root, sub)))
        return out


# ==========================================================================
# [轴3-L3.2 + L3.3 / 2026-05-15] PromiseExecutor — 后台步骤执行 + 重试 + 危险确认 + clarification
# ==========================================================================
#
# 职责
# ----
# 1. 后台 daemon 每 tick_s 秒扫 PlanLedger，找 STATE_RUNNING 的 plan，跑 next pending step
# 2. dangerous skill 二次确认（L3.3 sub 10.c）：plan 第 1 次 RUNNING tick 检测
#    metadata.dangerous_skills 非空 + 未 confirm → vocal say 警告 + PAUSE +
#    metadata['paused_for_dangerous_confirm']=True；Sir 说 confirm → 主脑 RESUME_PLAN →
#    metadata['dangerous_confirmed']=True 后才真跑 dangerous step
# 3. 失败重试链（L3.3 sub 10.a/10.b）：
#    - 第 1 次失败：step.retry_count=1，保持 pending，下轮 tick 再跑
#    - 第 2 次失败：step.status='failed' + plan PAUSE + paused_for_clarification +
#                   vocal say 简短汇报 → 主脑下一轮 prompt 看见 → 反向问 Sir
# 4. clarification 反向提问（L3.3 sub 10.d）：失败汇报里直接 say "Sir, 第 N 步失败：<error>。
#    要换个方式重试还是放下？"；Sir 回答后主脑用 RESUME_PLAN（重试）/ CANCEL_PLAN（放弃）/
#    新 PROMISE（换方案）继续。executor 自身不主动调 LLM —— 把决策权交给主脑 + Sir。
#
# 依赖注入设计（避免循环 import + 测试可 mock）
# -------------------------------------------------
#   plan_ledger:         PlanLedger 实例
#   skill_registry:      SkillRegistry 实例（用于 dangerous 检测；可空 → fallback get_registry()）
#   fast_call_executor:  callable(organ_name, command, args) → str 或抛异常
#                        约定：返回字符串前缀 "✅" 视为成功；"❌"/"Error"/抛异常 视为失败
#                        典型对接：lambda o, c, a: nerve.chat_bypass._execute_fast_call(o, c, a)
#   say_to_sir:          callable(text) → None  (vocal.say 包装；可空 → 只 bg_log)
#   event_bus:           ConversationEventBus 实例（可空 → 跳过事件投递）
#   tick_s:              后台轮询间隔（默认 1.0；测试时可调小）
#
# 线程安全：状态改通过 ledger（已加锁）；executor 自身只读引用；vocal say 走调用方阻塞。
# ==========================================================================


# 步骤执行结果约定
EXEC_PREFIX_SUCCESS = ('✅',)
EXEC_PREFIX_FAILURE = ('❌', 'Error', 'error', 'Exception', '⚠️')

# Sir 重启 Jarvis 时清掉的 metadata 标记（避免上一回 dangerous_confirmed 被静默继承）
TRANSIENT_META_KEYS = (
    'dangerous_confirmed',
    'paused_for_dangerous_confirm',
    'paused_for_clarification',
    'failed_step_idx',
    'failed_step_error',
    'dangerous_warned',
)


class PromiseExecutor:
    """轴3-L3.2 + L3.3 后台步骤执行器。详见模块顶 docstring。"""

    DEFAULT_TICK_S = 1.0
    MAX_RETRIES_PER_STEP = 1  # 第 1 次失败重试 1 次，第 2 次仍失败 → PAUSE for clarification

    def __init__(self, *, plan_ledger, skill_registry=None,
                 fast_call_executor=None, say_to_sir=None,
                 event_bus=None, tick_s: float = None,
                 max_retries_per_step: int = None):
        if plan_ledger is None:
            raise ValueError("PromiseExecutor requires plan_ledger")
        self._ledger = plan_ledger
        self._registry = skill_registry  # 延迟到调用时解析
        self._fast_call = fast_call_executor
        self._say = say_to_sir
        self._event_bus = event_bus
        self._tick_s = float(tick_s) if tick_s is not None else self.DEFAULT_TICK_S
        self._max_retries = int(max_retries_per_step) if max_retries_per_step is not None \
            else self.MAX_RETRIES_PER_STEP
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # 启动时清掉所有 active plan 的 transient meta（防 Sir 上一回话还在生效）
        self._reset_transient_metadata_on_init()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        """启动后台 daemon。重复 start 会被忽略。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='PromiseExecutor'
        )
        self._thread.start()
        try:
            from jarvis_utils import bg_log
            bg_log(f"🚀 [PromiseExecutor] 后台执行器已启动 (tick={self._tick_s}s)")
        except Exception:
            pass

    def stop(self, *, join_timeout: float = 2.0):
        """关闭。测试 / 关机用。"""
        self._stop_event.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=join_timeout)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def tick_once(self):
        """**测试用** 同步触发一次扫描循环。生产代码不调（daemon 自跑）。"""
        try:
            self._scan_and_execute()
        except Exception as e:
            self._safe_bg_log(f"⚠️ [PromiseExecutor] tick_once 异常被吞: {e}")

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._scan_and_execute()
            except Exception as e:
                self._safe_bg_log(f"⚠️ [PromiseExecutor] loop 异常被吞: {e}")
            # 周期 sleep（可被 stop 早醒）
            self._stop_event.wait(self._tick_s)

    # ------------------------------------------------------------------
    # 核心扫描
    # ------------------------------------------------------------------
    def _scan_and_execute(self):
        """每 tick 跑一次：找所有 STATE_RUNNING plan → 处理一步 / 一次性 PAUSE for confirm。"""
        ledger = self._ledger
        if ledger is None:
            return
        actives = ledger.get_active() or []
        for plan in actives:
            state = plan.get('state')
            if state != ledger.STATE_RUNNING:
                continue
            plan_id = plan.get('plan_id')
            if not plan_id:
                continue
            # 1. dangerous 二次确认前置闸（L3.3 sub 10.c）
            if self._maybe_request_dangerous_confirm(plan_id, plan):
                continue  # 已 PAUSE，本轮不再跑步骤
            # 2. 跑 next pending step
            self._execute_next_step(plan_id)

    # ------------------------------------------------------------------
    # dangerous 二次确认（L3.3 sub 10.c）
    # ------------------------------------------------------------------
    def _maybe_request_dangerous_confirm(self, plan_id: str, plan: dict) -> bool:
        """检测 dangerous_skills 非空 + 未 confirm → vocal warn + PAUSE。
        返回 True 表示已挡住（plan 已转 PAUSED）；False 表示无需 confirm 或已 confirmed。"""
        meta = plan.get('metadata') or {}
        dangerous_skills = meta.get('dangerous_skills') or []
        if not dangerous_skills:
            return False
        if meta.get('dangerous_confirmed'):
            return False
        # 未 confirm → 暂停 + 警告 Sir
        ledger = self._ledger
        with ledger._lock:
            real_plan = ledger._plans.get(plan_id)
            if not real_plan or real_plan.get('state') != ledger.STATE_RUNNING:
                return False  # 状态变了，不动它
            real_plan['metadata'].setdefault('paused_for_dangerous_confirm', True)
            real_plan['metadata']['dangerous_warned'] = True
        ok = ledger.set_state(plan_id, ledger.STATE_PAUSED, reason='dangerous_skills_pending_confirm')
        if not ok:
            return False
        # 警告文案（中英 fallback）
        skills_str = ', '.join(dangerous_skills[:5])
        warn_text = (
            f"Sir, this plan involves dangerous skill(s) [{skills_str}]. "
            f"Please reconfirm with 'go' / 'do it' to proceed, or 'cancel' to drop it."
        )
        self._say_safe(warn_text)
        self._publish_event('plan_paused_dangerous_confirm',
                            f"Plan {plan_id[:8]} paused: dangerous_skills={skills_str}",
                            metadata={'plan_id': plan_id, 'dangerous_skills': dangerous_skills})
        self._safe_bg_log(
            f"🛑 [PromiseExecutor] plan {plan_id[:8]} PAUSED for dangerous confirm: {skills_str}"
        )
        return True

    # ------------------------------------------------------------------
    # 步骤执行 + 失败重试 + clarification（L3.2 sub 9.d / L3.3 sub 10.a/b/d）
    # ------------------------------------------------------------------
    def _execute_next_step(self, plan_id: str):
        """跑 plan 的下一个 pending step。"""
        ledger = self._ledger
        # 找下一个 pending step
        with ledger._lock:
            plan = ledger._plans.get(plan_id)
            if not plan:
                return
            if plan.get('state') != ledger.STATE_RUNNING:
                return
            steps = plan.get('steps') or []
            next_idx = -1
            for i, s in enumerate(steps):
                if s.get('status') == 'pending':
                    next_idx = i
                    break
            # 已无 pending → 全跑完检测
            if next_idx < 0:
                all_done = all(s.get('status') == 'done' for s in steps)
                any_failed = any(s.get('status') == 'failed' for s in steps)
                # 无 pending + 无 failed + 全 done → DONE
                target_step = None
            else:
                target_step = dict(steps[next_idx])  # 复制
        # plan 已无 pending：判断收尾
        if next_idx < 0:
            self._maybe_finalize_plan(plan_id)
            return

        # 标 step 为 running（仅修该字段，不改 plan state）
        ledger.advance_step(plan_id, next_idx, new_status='running')

        # 执行步骤
        skill = target_step.get('skill')
        desc = target_step.get('description', '')
        args = target_step.get('args') or {}

        if not skill:
            # 描述性步骤（如"汇总报告"），无工具调用 → 直接 done
            ledger.advance_step(plan_id, next_idx, new_status='done',
                                result=f"(描述性步骤) {desc[:120]}")
            self._safe_bg_log(
                f"⏭️ [PromiseExecutor] plan {plan_id[:8]} step {next_idx+1} (no skill) → done"
            )
            return

        # 解析 skill → organ.command
        organ_name, command = self._split_skill(skill)
        if not organ_name or not command:
            self._record_step_failure(
                plan_id, next_idx,
                error=f"invalid skill name: {skill!r} (expected 'organ.command')",
                skill_for_kpi=skill,
            )
            return

        # dangerous 单步再判一次（防 LLM 把 dangerous skill 写在子步骤但 metadata.dangerous_skills 漏统计）
        if self._step_is_dangerous(skill) and not self._dangerous_confirmed(plan_id):
            self._safe_bg_log(
                f"🛑 [PromiseExecutor] plan {plan_id[:8]} step {next_idx+1} skill={skill} "
                f"is dangerous but plan not confirmed — PAUSE"
            )
            with ledger._lock:
                p = ledger._plans.get(plan_id)
                if p:
                    meta = p.setdefault('metadata', {})
                    meta['paused_for_dangerous_confirm'] = True
                    # 把这个 skill 加到 dangerous_skills 让主脑下一轮看见
                    ds = list(meta.get('dangerous_skills') or [])
                    if skill not in ds:
                        ds.append(skill)
                    meta['dangerous_skills'] = ds
            ledger.advance_step(plan_id, next_idx, new_status='pending')  # 复位
            ledger.set_state(plan_id, ledger.STATE_PAUSED,
                             reason=f'dangerous_step_pending:{skill}')
            self._say_safe(
                f"Sir, step {next_idx+1} uses dangerous skill {skill}. "
                f"Confirm with 'do it' to proceed, or 'cancel'."
            )
            return

        # 跑工具
        if self._fast_call is None:
            # 没注入执行器 → 视为成功 + 占位结果（让测试可以走非工具路径）
            ledger.advance_step(plan_id, next_idx, new_status='done',
                                result=f"(no_executor) {skill}({args})")
            return
        ok, msg = self._invoke_skill(skill, organ_name, command, args)
        if ok:
            ledger.advance_step(plan_id, next_idx, new_status='done',
                                result=msg[:380])
            self._safe_bg_log(
                f"✅ [PromiseExecutor] plan {plan_id[:8]} step {next_idx+1} ({skill}) → done"
            )
        else:
            self._record_step_failure(plan_id, next_idx, error=msg, skill_for_kpi=skill)

    def _record_step_failure(self, plan_id: str, step_idx: int, *,
                             error: str, skill_for_kpi: Optional[str]):
        """L3.3 sub 10.a/10.b：失败处理：第 1 次重试，第 2 次 PAUSE for clarification。"""
        ledger = self._ledger
        with ledger._lock:
            plan = ledger._plans.get(plan_id)
            if not plan:
                return
            steps = plan.get('steps') or []
            if step_idx < 0 or step_idx >= len(steps):
                return
            step = steps[step_idx]
            current_retry = int(step.get('retry_count') or 0)
            step['retry_count'] = current_retry + 1
            step['last_error'] = (error or '')[:200]
            if current_retry < self._max_retries:
                # 第 1 次失败：保持 pending 等下轮重试
                step['status'] = 'pending'
                retry_round = current_retry + 1
            else:
                # 第 2 次失败：标 failed + 准备 PAUSE
                step['status'] = 'failed'
                step['result'] = f"failed (retry={current_retry}): {(error or '')[:200]}"
                retry_round = current_retry + 1
        if step['status'] == 'pending':
            self._safe_bg_log(
                f"🔁 [PromiseExecutor] plan {plan_id[:8]} step {step_idx+1} 失败 "
                f"(round={retry_round}/{self._max_retries+1})，下轮重试 — error={(error or '')[:80]}"
            )
            return
        # 第 2 次失败 → PAUSE + clarification (L3.3 sub 10.b/10.d)
        with ledger._lock:
            plan = ledger._plans.get(plan_id)
            if plan:
                meta = plan.setdefault('metadata', {})
                meta['paused_for_clarification'] = True
                meta['failed_step_idx'] = step_idx
                meta['failed_step_error'] = (error or '')[:200]
        ledger.set_state(plan_id, ledger.STATE_PAUSED,
                         reason='step_failed_pending_clarification')
        # 反向提问 Sir（短文案；详细 error 已写进 metadata 让主脑下一轮看见）
        question = (
            f"Sir, step {step_idx+1} failed: {(error or 'unknown')[:80]}. "
            f"Retry, change approach, or skip?"
        )
        self._say_safe(question)
        self._publish_event(
            'plan_paused_clarification',
            f"Plan {plan_id[:8]} step {step_idx+1} failed: {(error or '')[:80]}",
            metadata={'plan_id': plan_id, 'failed_step_idx': step_idx,
                      'error': (error or '')[:200], 'skill': skill_for_kpi},
        )
        self._safe_bg_log(
            f"🛑 [PromiseExecutor] plan {plan_id[:8]} step {step_idx+1} 二次失败 → "
            f"PAUSE for clarification (error={(error or '')[:80]})"
        )

    def _maybe_finalize_plan(self, plan_id: str):
        """plan 已无 pending step → 判 done / failed / 收尾。"""
        ledger = self._ledger
        with ledger._lock:
            plan = ledger._plans.get(plan_id)
            if not plan:
                return
            if plan.get('state') != ledger.STATE_RUNNING:
                return
            steps = plan.get('steps') or []
            if not steps:
                return
            all_done = all(s.get('status') == 'done' for s in steps)
        if all_done:
            ok = ledger.set_state(plan_id, ledger.STATE_DONE, reason='all_steps_done')
            if ok:
                # 取 plan goal 做完工汇报
                with ledger._lock:
                    p = ledger._plans.get(plan_id) or {}
                    goal = p.get('goal', '')
                report_text = f"Done, Sir. {goal[:80]}" if goal else "Done, Sir."
                self._say_safe(report_text)
                self._safe_bg_log(
                    f"🎉 [PromiseExecutor] plan {plan_id[:8]} → DONE: {goal[:60]}"
                )

    # ------------------------------------------------------------------
    # Skill 工具调用（含 KPI 喂回）
    # ------------------------------------------------------------------
    def _invoke_skill(self, skill_name: str, organ: str, command: str,
                      args: dict) -> tuple:
        """调 fast_call_executor + record_invocation。返回 (success: bool, msg: str)。"""
        registry = self._registry or get_registry()
        start_ts = time.time()
        try:
            raw_msg = self._fast_call(organ, command, args)
        except Exception as e:
            latency_ms = int((time.time() - start_ts) * 1000)
            try:
                registry.record_invocation(
                    skill_name, success=False, latency_ms=latency_ms,
                    error=str(e)[:200],
                )
            except Exception:
                pass
            return False, f"exception: {str(e)[:200]}"
        latency_ms = int((time.time() - start_ts) * 1000)
        msg_str = str(raw_msg) if raw_msg is not None else ''
        success = self._classify_msg_success(msg_str)
        try:
            registry.record_invocation(
                skill_name, success=success, latency_ms=latency_ms,
                error=None if success else msg_str[:200],
            )
        except Exception:
            pass
        return success, msg_str

    @staticmethod
    def _classify_msg_success(msg: str) -> bool:
        """从 fast_call_executor 返回字符串判 success。
        约定：
          - 前缀 "✅" / "Done" / "OK"  → 成功
          - 前缀 "❌" / "Error" / "Exception" / "⚠️"  → 失败
          - 其它（含空字符串）→ 视为成功（给无返回值的 hand 兜底）
        """
        if not msg:
            return True
        s = msg.strip()
        for p in EXEC_PREFIX_FAILURE:
            if s.startswith(p):
                return False
        return True

    @staticmethod
    def _split_skill(skill: str) -> tuple:
        """'audio_hands.set_volume' → ('audio_hands', 'set_volume')。
        失败返回 (None, None)。"""
        if not skill or '.' not in skill:
            return None, None
        organ, _, command = skill.partition('.')
        organ = organ.strip()
        command = command.strip()
        if not organ or not command:
            return None, None
        return organ, command

    def _step_is_dangerous(self, skill: str) -> bool:
        """通过 SkillRegistry 判 step 引用的 skill 是否 dangerous。"""
        if not skill:
            return False
        registry = self._registry or get_registry()
        sk = registry.get(skill)
        if sk is None:
            return False  # 未注册 — 不假设 dangerous（OfferGuard / draft 阶段已挡）
        return sk.is_dangerous()

    def _dangerous_confirmed(self, plan_id: str) -> bool:
        with self._ledger._lock:
            plan = self._ledger._plans.get(plan_id)
            if not plan:
                return False
            return bool((plan.get('metadata') or {}).get('dangerous_confirmed'))

    # ------------------------------------------------------------------
    # 工具：vocal 说话 / event_bus / bg_log（全部异常吞）
    # ------------------------------------------------------------------
    def _say_safe(self, text: str):
        if not text or not self._say:
            return
        try:
            self._say(text)
        except Exception as e:
            self._safe_bg_log(f"⚠️ [PromiseExecutor] say_to_sir 异常被吞: {e}")

    def _publish_event(self, etype: str, desc: str, *, metadata: dict = None):
        bus = self._event_bus
        if bus is None:
            try:
                from jarvis_utils import get_event_bus
                bus = get_event_bus()
            except Exception:
                bus = None
        if bus is None:
            return
        try:
            bus.publish(
                etype=etype, description=desc[:300], source='promise_executor',
                metadata=metadata or {},
            )
        except Exception:
            pass

    @staticmethod
    def _safe_bg_log(text: str):
        try:
            from jarvis_utils import bg_log
            bg_log(text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 启动初始化：清掉 transient metadata
    # ------------------------------------------------------------------
    def _reset_transient_metadata_on_init(self):
        """启动时清掉所有 active plan 的瞬时标记（dangerous_confirmed / paused_for_*），
        避免 Sir 上一回话的状态被静默继承到这一回。"""
        ledger = self._ledger
        if ledger is None:
            return
        try:
            with ledger._lock:
                for plan in ledger._plans.values():
                    meta = plan.get('metadata') or {}
                    for k in TRANSIENT_META_KEYS:
                        meta.pop(k, None)
        except Exception:
            pass


# ==========================================================================
# [P0+18-a.16 / 2026-05-15] CapabilityClaimValidator — 拦"我能用 X 来查 Y"型越界许诺
# ==========================================================================
#
# 背景（2026-05-15 15:50 实测 bug 复盘）
# ----------------------------------
# Jarvis 在 chat 路径（非 PROMISE 标签）里说：
#   "I can run process_hands.get_process_info for Cursor to check for any
#    unusual resource spikes or logged errors that might explain the visual hang."
#
# `process_hands.get_process_info` 只返 OS 层 (PID/CPU/MEM/exe)，**根本不能读
# 应用内部日志**。这是"capability laundering through framing" — 用 `or` 把
# 工具真正能做的事（resource spikes）和不能做的事（logged errors）顺滑缝在一起。
# 这违反 Sir 的"承诺必行"设计理念。
#
# 现有体系覆盖不到的原因
# --------------------
# - <PROMISE> 标签只在 multi-step action 里强制；这种"口头许诺"完全绕开
# - Integrity Check 现在只看 "claim 完成但没调任何工具" / "circuit_broken" 两档
# - 既然在 chat 阶段不会真去运行那个工具，Integrity Check 自然抓不到
#
# 本类做什么
# --------
# 后置（post-hoc）从 Jarvis 输出文本里抽 "use/run/invoke <skill> ... to <claim>"
# 类模式，把 <claim> 和 <skill>.cannot_provide 词典比对：命中 → 报 violation。
#
# 设计原则
# --------
# 1. 不阻塞输出 — Jarvis 已经说出去了，由 Integrity Check 把违例信号回灌 STM
#    + event_bus，让下一轮 prompt 让主脑看见、纠正自己。
# 2. 保守抓 — 宁愿漏（少报）也别误报；只命中**明确点名 skill 名**或别名的 claim。
# 3. 零硬编码 — 词典来自 SkillManifest.cannot_provide；Sir 只要给 skill 加这两个
#    字段就自动获得保护（不用改 Validator）。
# 4. 中英双语 — claim 抽取支持英文和中文常用动词。
# ==========================================================================


# 抽取"使用工具 → 检查/查 Y"模式的正则（中英双语，宽松抓取）
# 形态典型：
#   I can run/use/invoke `process_hands.get_process_info` to check for X or Y
#   我可以运行/调用 process_hands.get_process_info 来检查 X 或 Y
# 设计：用 (?P<skill>) 抓 skill 名（含点号），(?P<claim>) 抓后面的整段（含 or 子句）
# 直到句尾 (.?。?\n+|$)。
#
# 注：用 re.IGNORECASE + UNICODE。
_CLAIM_PATTERNS = [
    # 英文：I can/could/will/might/should + run/use/invoke/call + (`)skill(`) + ... + to/for + verb
    re.compile(
        r'(?:i\s+(?:can|could|will|may|might|should|am\s+able\s+to)\s+'
        r'(?:run|use|invoke|call|execute|trigger|kick\s+off|fire)'
        r'\s+`?\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+)\s*`?'  # skill name (含 .)
        r'[^.!?\n]{0,160}?'                                         # 中间杂质
        r'\b(?:to|for|in\s+order\s+to|so\s+as\s+to)\b\s+'
        r'(?:check|investigate|find|see|inspect|diagnose|explain|'
        r'reveal|determine|verify|confirm|tell|show|expose|surface|'
        r'identify|detect|figure\s+out|look\s+(?:at|into))\s+'
        r'([^.!?\n]{1,250})'                                        # claim 内容
        r')',
        re.IGNORECASE | re.UNICODE,
    ),
    # 中文：我(可以|能|将)(运行|调用|用|跑) skill (来|以)(查|检查|看|找|诊断|调查|排查|确认|说明) Y
    re.compile(
        r'(?:我(?:可以|能|将|可)?(?:运行|调用|用|跑|启动|执行|invoke)\s*'
        r'`?\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+)\s*`?'
        r'[^。！？\n]{0,160}?'
        r'(?:来|以|去|进行|拿来)\s*'
        r'(?:查|检查|看一?下|找|诊断|调查|排查|确认|确认下|说明|揭示|定位|检测|理清)\s*'
        r'([^。！？\n]{1,250})'
        r')',
        re.IGNORECASE | re.UNICODE,
    ),
]


class CapabilityClaimValidator:
    """从 Jarvis 自然语言输出抽 "use X to check Y" 模式 → 校验 Y 是否在 X.cannot_provide。

    用法：
        violations = CapabilityClaimValidator.detect_violations(jarvis_reply)
        if violations:
            for v in violations:
                # v = {'skill': str, 'claim_text': str, 'forbidden_keywords': [str, ...]}
                ...

    线程安全：纯静态方法 + 只读 SkillRegistry。
    """

    # 用于把 claim 文本切成关键词候选的拆分符
    _SPLIT_RE = re.compile(r'[,\.;:!?，。；：！？/]| or | and |、|或者|或|和|及', re.IGNORECASE)

    @classmethod
    def detect_violations(cls, text: str, *,
                          registry: Optional[SkillRegistry] = None,
                          min_keyword_chars: int = 3) -> list:
        """主入口。

        参数：
            text                 Jarvis 自然语言输出
            registry             SkillRegistry（默认 get_registry()）
            min_keyword_chars    cannot_provide 关键词最少匹配字符数（防 'ui' 误命中 'fluid'）

        返回 list[dict]：
            [
              {
                'skill': 'process_hands.get_process_info',
                'claim_text': 'any unusual resource spikes or logged errors that might explain the visual hang',
                'forbidden_keywords': ['logged_errors', 'visual_hang'],  # 命中的 cannot_provide 关键词
                'matched_phrases': ['logged errors', 'visual hang'],     # 在 claim 文本里命中的具体短语
              },
              ...
            ]
        """
        if not text or not isinstance(text, str):
            return []
        reg = registry or get_registry()
        # 收集所有候选 (skill, claim) 对
        candidates = []
        for pat in _CLAIM_PATTERNS:
            for m in pat.finditer(text):
                skill = m.group(1).strip().lower()
                claim = m.group(2).strip()
                if not skill or not claim:
                    continue
                # 同位置/同 skill 去重：用 (skill, claim_lower) 作 key
                key = (skill, claim.lower())
                if key in {(s, c.lower()) for s, c, _ in candidates}:
                    continue
                candidates.append((skill, claim, m.start()))

        if not candidates:
            return []

        violations = []
        for skill, claim, _pos in candidates:
            manifest = reg.get(skill)
            if manifest is None:
                # skill 不在 registry — 这是另一种问题（unknown_skill），由 PromiseParser 抓
                continue
            forbidden = manifest.cannot_provide or []
            if not forbidden:
                continue  # 这个 skill 没声明 cannot_provide，跳过
            claim_lower = claim.lower()
            hits = []      # cannot_provide 词条命中
            phrases = []   # claim 文本里命中的具体短语
            for kw in forbidden:
                if not kw or not isinstance(kw, str):
                    continue
                kw_low = kw.lower().strip()
                if len(kw_low) < min_keyword_chars:
                    continue
                # 关键词形态：'logged_errors' / 'why_app_fails'  → 同时认下划线版和空格版
                kw_variants = {kw_low}
                if '_' in kw_low:
                    kw_variants.add(kw_low.replace('_', ' '))
                    kw_variants.add(kw_low.replace('_', '-'))
                matched_variant = None
                for v in kw_variants:
                    if v in claim_lower:
                        matched_variant = v
                        break
                if matched_variant:
                    hits.append(kw_low)
                    phrases.append(matched_variant)
            if hits:
                violations.append({
                    'skill': skill,
                    'claim_text': claim,
                    'forbidden_keywords': hits,
                    'matched_phrases': phrases,
                })
        return violations

    @classmethod
    def format_violation_note(cls, violations: list) -> str:
        """把 violation 列表渲染成可直接塞 STM 的提示文本（让下一轮主脑看见）。

        返回空字符串表示无 violation。
        """
        if not violations:
            return ''
        lines = []
        for v in violations:
            skill = v.get('skill', '?')
            phrases = v.get('matched_phrases') or []
            phrases_str = ', '.join(repr(p) for p in phrases[:4])
            lines.append(
                f"I claimed `{skill}` could tell me about {phrases_str}, "
                f"but its MANIFEST explicitly says it cannot. "
                f"This violates 承诺必行 — I must not offer to use a tool for something it cannot do."
            )
        joined = ' '.join(lines)
        return f" [CAPABILITY OVERREACH NOTE: {joined}]"


# ==========================================================================
# [P0+18-a.16 / 2026-05-15] TOOL_HONESTY_DIRECTIVE — prompt 软约束块
# ==========================================================================

# [P0+18-a.16] SHORT_CHAT 短档专用 mini 版（~400 字符，控制 SHORT_CHAT prompt 体积）
TOOL_HONESTY_DIRECTIVE_MINI = """[TOOL HONESTY — mini]:
Only claim what a tool's MANIFEST actually provides. NEVER:
(a) say `process_hands.*` can read "logs / errors / exceptions / why an app fails" —
    process tools only see OS-level info (PID/CPU/MEM/exe), NOT application internals.
(b) stitch capable-of and not-capable-of with `or`/`or for` to fuse them.
    WRONG: "...to check resource spikes or logged errors."
For another app's internal failure, propose `file_operator_hands.read` on its log file,
or admit "I don't have a tool that can see that, Sir."
"""


TOOL_HONESTY_DIRECTIVE = """[TOOL HONESTY — 承诺必行的硬约束]:
When offering Sir to use a tool, you MUST only claim what the tool's MANIFEST
explicitly declares it provides. Common traps you MUST avoid:

(a) DO NOT use `process_hands.*` to promise "logs / errors / exceptions / why
    the app fails / blank screen cause". Process tools only see OS-level info
    (PID, CPU, memory, executable path, create time). They CANNOT read another
    application's internal logs, JS exceptions, render errors, or CSP violations.
    If Sir asks about an app's internal failure, the right tool is
    `file_operator_hands.read` (read the app's log files on disk) or `screenshot_hands`
    (visual evidence) — NOT a process tool.

(b) DO NOT stitch "X can do A" and "X can do B" with `or` / `or for` to fuse a
    capable-of claim with a not-capable-of claim. This is the most common shape
    of capability overreach.

    WRONG: "I can run process_hands.get_process_info to check for resource
            spikes or logged errors."
    RIGHT: "I can confirm via process_hands.get_process_info that Cursor.exe is
            alive and not consuming abnormal resources — but I cannot tell from
            that alone WHY a dialog is blank. For the cause, I'd need to read
            Cursor's log files via file_operator_hands.read."

(c) When uncertain whether a tool can deliver what Sir wants, prefer admitting
    "I don't have a tool for that, Sir" over offering a tool whose output won't
    answer the question.

(d) `承诺必行` 的可执行约束：所选工具的真实能力域 ⊇ 你许诺要交付的信息域。
    在 self-talk 里检验一句话："如果我跑了这个工具，它的返回会回答 Sir 的问题吗？"
    答案是"不会，但听起来像会"→ 立即换工具或换说法。
"""

