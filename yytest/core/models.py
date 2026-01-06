"""Core data models for yeytest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    VISUAL_MISMATCH = "visual_mismatch"  # Maestro passed ama görsel doğrulama failed


class ValidationLevel(Enum):
    NONE = "none"  # Sadece Maestro sonucu
    LOCAL = "local"  # Pixel diff + OCR
    AI = "ai"  # Claude/GPT vision
    HYBRID = "hybrid"  # Local + şüpheliyse AI


@dataclass
class Screenshot:
    path: Path
    timestamp: datetime
    step_index: int
    description: str = ""


@dataclass
class ValidationResult:
    passed: bool
    confidence: float  # 0.0 - 1.0
    reason: str
    method: str  # "pixel_diff", "ocr", "ai_vision"
    details: dict = field(default_factory=dict)


@dataclass
class StepResult:
    index: int
    action: str
    target: str
    maestro_passed: bool
    validation_result: Optional[ValidationResult] = None
    screenshot_before: Optional[Screenshot] = None
    screenshot_after: Optional[Screenshot] = None
    duration_ms: int = 0
    error_message: str = ""

    @property
    def status(self) -> StepStatus:
        if not self.maestro_passed:
            return StepStatus.FAILED
        if self.validation_result is None:
            return StepStatus.PASSED
        if not self.validation_result.passed:
            return StepStatus.VISUAL_MISMATCH
        return StepStatus.PASSED

    @property
    def truly_passed(self) -> bool:
        """Hem Maestro hem de görsel doğrulama geçti mi?"""
        return self.maestro_passed and (
            self.validation_result is None or self.validation_result.passed
        )


@dataclass
class TestCase:
    name: str
    description: str
    steps: list[dict]  # Maestro steps
    expectations: list[str] = field(default_factory=list)  # Her adım için beklenti


@dataclass
class TestResult:
    test_case: TestCase
    started_at: datetime
    finished_at: Optional[datetime] = None
    step_results: list[StepResult] = field(default_factory=list)
    video_path: Optional[Path] = None

    @property
    def passed(self) -> bool:
        return all(step.truly_passed for step in self.step_results)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at is None:
            return 0
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def summary(self) -> dict:
        total = len(self.step_results)
        passed = sum(1 for s in self.step_results if s.truly_passed)
        visual_mismatches = sum(
            1 for s in self.step_results if s.status == StepStatus.VISUAL_MISMATCH
        )
        return {
            "total_steps": total,
            "passed": passed,
            "failed": total - passed,
            "visual_mismatches": visual_mismatches,
            "duration_seconds": self.duration_seconds,
        }

