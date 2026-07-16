from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentMode(str, Enum):
    INFORM = "inform"
    OPERATE = "operate"


class TaskState(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class InteractiveElement:
    id: str
    role: str
    text: str
    selector: str
    operation: str
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageSnapshot:
    id: str
    created_at: float
    url: str
    title: str
    text_excerpt: str
    elements: tuple[InteractiveElement, ...]
    fingerprint: str


@dataclass(frozen=True)
class ToolResult:
    success: bool
    message: str
    before: PageSnapshot
    after: PageSnapshot
    changed: bool
    error: str | None = None


@dataclass
class TaskContext:
    goal: str
    state: TaskState = TaskState.PLANNING
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    latest_snapshot: PageSnapshot | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    kind: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
