import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum


class HilState(Enum):
    IDLE = "idle"
    ARMED = "armed"
    RUNNING = "running"
    AWAITING_OBSERVATION = "awaiting_observation"
    PASSED = "passed"
    FAILED = "failed"
    REPAIRING = "repairing"
    WAITING_INPUT = "waiting_input"
    DISCONNECTED = "disconnected"


@dataclass
class RunRecord:
    run_id: str
    requirement: str
    code: str
    code_hash: str
    attempt: int
    output: str = ""


@dataclass(frozen=True)
class HilDecision:
    state: HilState
    reason: str
    request_repair: bool = False


ERROR_RE = re.compile(
    r"Traceback \(most recent call last\)|(?:^|\n)(?:OSError|MemoryError|ImportError|ValueError|TypeError):",
    re.MULTILINE,
)
READY_MARKER = "[HIL:READY]"
PASS_MARKER = "[HIL:PASS]"


class HilAgent:
    """Correlates bounded backend output with one generated-code run."""

    def __init__(self, max_repairs=2, max_output_chars=12000):
        self.max_repairs = max_repairs
        self.max_output_chars = max_output_chars
        self.active = None
        self.state = HilState.IDLE
        self.last_code_hash = None

    def start(self, requirement, code, attempt=0):
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if attempt and code_hash == self.last_code_hash:
            self.state = HilState.FAILED
            return HilDecision(self.state, "The repair returned unchanged code")
        self.active = RunRecord(str(uuid.uuid4()), requirement, code, code_hash, attempt)
        self.last_code_hash = code_hash
        self.state = HilState.ARMED
        return HilDecision(self.state, "Waiting for Thonny to accept the target run")

    def command_accepted(self, command_name):
        if self.active is None or self.state != HilState.ARMED:
            return None
        if str(command_name).lower() != "run":
            return None
        self.state = HilState.RUNNING
        return HilDecision(self.state, "Run accepted; collecting target evidence")

    def execution_rejected(self, reason):
        if self.active is None or self.state != HilState.ARMED:
            return None
        self.state = HilState.FAILED
        return HilDecision(self.state, reason, False)

    def feed_output(self, data):
        if self.active is None or self.state != HilState.RUNNING:
            return None
        self.active.output = (self.active.output + str(data))[-self.max_output_chars :]
        if ERROR_RE.search(self.active.output):
            return self._failure("Target traceback detected")
        if PASS_MARKER in self.active.output:
            self.state = HilState.PASSED
            return HilDecision(self.state, "The target reported a measured validation pass")
        if READY_MARKER in self.active.output:
            self.state = HilState.AWAITING_OBSERVATION
            return HilDecision(self.state, "Target initialized; confirm the physical result")
        return None

    def toplevel_finished(self):
        if self.active is None or self.state != HilState.RUNNING:
            return None
        if ERROR_RE.search(self.active.output):
            return self._failure("Target traceback detected")
        self.state = HilState.AWAITING_OBSERVATION
        return HilDecision(self.state, "Program finished without a traceback; confirm the hardware result")

    def observation_timeout(self, run_id):
        if (
            self.active is None
            or self.active.run_id != run_id
            or self.state != HilState.RUNNING
        ):
            return None
        self.state = HilState.AWAITING_OBSERVATION
        return HilDecision(
            self.state,
            "No failure was reported during startup; confirm the physical result",
        )

    def input_requested(self):
        if self.active is None:
            return None
        self.state = HilState.WAITING_INPUT
        return HilDecision(self.state, "The program is waiting for input")

    def disconnected(self):
        if self.active is None:
            return None
        self.state = HilState.DISCONNECTED
        return HilDecision(self.state, "Target disconnected")

    def observe(self, passed, feedback=""):
        if self.active is None or self.state != HilState.AWAITING_OBSERVATION:
            return None
        if passed:
            self.state = HilState.PASSED
            return HilDecision(self.state, feedback or "Hardware behavior confirmed")
        return self._failure(feedback or "Hardware behavior did not match the requirement")

    def mark_repairing(self):
        self.state = HilState.REPAIRING

    def _failure(self, reason):
        self.state = HilState.FAILED
        can_repair = bool(self.active and self.active.attempt < self.max_repairs)
        return HilDecision(self.state, reason, can_repair)
