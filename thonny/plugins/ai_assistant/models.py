from dataclasses import dataclass, field
from threading import Event
from typing import Callable, Optional


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    label: str
    base_url: str
    default_model: str


@dataclass(frozen=True)
class HardwareContext:
    platform: str = "unknown"
    board: str = "unknown"
    firmware: str = "unknown"
    connected: bool = False
    pin_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationRequest:
    model: str
    messages: list[dict[str, str]]
    timeout: float = 60.0


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    request_id: Optional[str] = None


DeltaCallback = Callable[[str], None]
CancelEvent = Event
