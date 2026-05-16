from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import time

@dataclass
class Action:
    command: str
    params: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ExecutionResult:
    success: bool
    msg: str
    data: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=lambda: 0.0)

@dataclass
class PerceptionData:
    url: str
    page_title: str
    interactable_elements: List[Dict[str, Any]] = field(default_factory=list)
    image_base64: Optional[str] = None

@dataclass
class JarvisBlood:
    user_voice_input: str = ""
    macro_goal: str = ""
    recent_context: str = "" 
    current_perception: Optional[PerceptionData] = None
    next_actions: List[Action] = field(default_factory=list)
    thought_process: str = ""
    history: List[ExecutionResult] = field(default_factory=list)
    is_task_complete: bool = False
    is_stuck: bool = False
    reflection_advice: str = ""  
    memory_protocol: Dict[str, Any] = field(default_factory=dict)

    def add_history(self, result: ExecutionResult):
        self.history.append(result)

@dataclass
class CorrectionEntry:
    trigger_context: str
    wrong_response: str
    correction: str
    timestamp: float = field(default_factory=time.time)
    context_embedding: Optional[bytes] = None
    source_module: str = "chat"
    confidence: float = 1.0
    times_recalled: int = 0

@dataclass
class FeedbackSignal:
    """[P0+13 / 2026-05-15] 统一定义 — 之前 jarvis_nerve.py 也有一份独立 dataclass，
    nerve 路径用 nerve 版、blood 路径用 blood 版，状态不共享。
    现在 nerve 改为 from jarvis_blood import FeedbackSignal；本类全部字段改有默认值，
    保持与 nerve 旧版的 API 完全兼容（FeedbackTracker.analyze_interaction 不需要改签名）。
    """
    signal_type: str = "neutral"
    user_input: str = ""
    jarvis_response: str = ""
    timestamp: float = field(default_factory=time.time)
    context_snapshot: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MemoryFragment:
    source: str
    content: str
    timestamp: float = field(default_factory=time.time)
    relevance_score: float = 0.0
    freshness_hours: float = 0.0
    source_weight: float = 0.2
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TaskSnapshot:
    task_id: str = ""
    macro_goal: str = ""
    current_phase: int = 0
    total_phases: int = 0
    remaining_tasks: List[Dict[str, Any]] = field(default_factory=list)
    stm_snapshot: List[Dict[str, str]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    environment: str = "DESKTOP"

@dataclass
class PromptLayer:
    layer_id: str
    content: str
    ttl_seconds: float = 3600.0
    generated_at: float = field(default_factory=time.time)
    dependencies: List[str] = field(default_factory=list)

    def is_expired(self) -> bool:
        return time.time() - self.generated_at > self.ttl_seconds