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


class ArtifactKind(StrEnum):
    SPECIFICATION = "specification"
    DIFF = "diff"
    PULL_REQUEST = "pull_request"
    LOG = "log"
