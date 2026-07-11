"""Status and role vocabularies for the agent runtime.

Stored as plain strings (not native Postgres enums) so adding a value never
needs a migration; these StrEnums are the single source of truth in code.
See docs/architecture/AGENT_RUNTIME.md for the lifecycle diagrams.
"""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    PRODUCT_MANAGER = "product_manager"
    BACKEND = "backend"
    FRONTEND = "frontend"
    DEVOPS = "devops"
    REVIEWER = "reviewer"
    QA = "qa"
    SCRUM_MASTER = "scrum_master"


# ── Planning Suite (docs/architecture/PLANNING_SUITE.md) ────────────────────
# A work item is durable and repository-scoped, unlike the per-run AgentTask.


class WorkItemKind(StrEnum):
    FEATURE = "feature"
    BUG = "bug"
    CHORE = "chore"
    SPIKE = "spike"  # a time-boxed investigation, not shippable work


class WorkItemStatus(StrEnum):
    PROPOSED = "proposed"  # planned but not yet accepted into the backlog
    READY = "ready"  # accepted, unblocked, and ready to start
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"  # waiting on an unfinished dependency
    DONE = "done"
    CANCELLED = "cancelled"


class Estimate(StrEnum):
    """Relative size only — never a false-precision hour count."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ArtifactKind(StrEnum):
    SPECIFICATION = "specification"
    DIFF = "diff"
    PULL_REQUEST = "pull_request"
    LOG = "log"
