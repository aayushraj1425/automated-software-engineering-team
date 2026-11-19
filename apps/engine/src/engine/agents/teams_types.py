"""Shared contracts for adaptive teams; implementation ownership is in PLAN.md."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from engine.db.enums import AgentRole, Complexity
from engine.llm.catalog import ModelSelection, SeatLevel

Level = SeatLevel
ModelChoice = ModelSelection


@dataclass(frozen=True)
class TriageDecision:
    complexity: Complexity
    reason: str
    test_only: bool
    source: str = "rules"


TriageResult = TriageDecision


class StageName(StrEnum):
    DESIGN = "design"
    PLAN = "plan"
    BUILD = "build"
    REVIEW = "review"
    SANDBOX = "sandbox"
    SECURITY = "security"
    DEPENDENCY = "dependency"
    PRINCIPAL_REVIEW = "principal_review"
    PREVIEW_DEPLOY = "preview_deploy"
    CLOUD_TESTS = "cloud_tests"
    PUBLISH = "publish"
    TEST_REPORT = "test_report"


class Seat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str  # stable role:level identifier, e.g. backend:engineer
    role: AgentRole
    level: SeatLevel
    model: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class TeamTemplate:
    name: str
    complexity: Complexity
    seats: tuple[Seat, ...]
    stages: tuple[StageName, ...]
