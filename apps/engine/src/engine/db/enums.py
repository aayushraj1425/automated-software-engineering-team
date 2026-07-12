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
    TECHNICAL_WRITER = "technical_writer"


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


# ── Knowledge & Memory (docs/architecture/KNOWLEDGE_AND_MEMORY.md) ──────────
# A knowledge item is one durable, repository-scoped memory.


class KnowledgeKind(StrEnum):
    DECISION = "decision"  # an approved plan — what the team agreed to build
    OUTCOME = "outcome"  # how a run ended: pull request opened, or why it failed
    PREFERENCE = "preference"  # how the team likes things done (rejections land here)
    NOTE = "note"  # anything worth remembering, including meeting notes


class ArtifactKind(StrEnum):
    SPECIFICATION = "specification"
    DIFF = "diff"
    PULL_REQUEST = "pull_request"
    LOG = "log"


# ── Documentation Suite (docs/architecture/DOCUMENTATION_SUITE.md) ──────────
# A generated document is a human-facing Markdown artifact written by the
# Technical Writer from the repository index — durable and repository-scoped.


class DocumentKind(StrEnum):
    README = "readme"  # project overview: what it is, setup, usage
    API_REFERENCE = "api_reference"  # the endpoints / functions the code exposes
    CHANGELOG = "changelog"  # human summary of what the codebase does, by area
    ARCHITECTURE = "architecture"  # how the modules fit together


# ── External Integrations (docs/architecture/EXTERNAL_INTEGRATIONS.md) ──────
# One connection links a user to an external service. The enum names every
# planned service so the model stays forward-looking; the API activates them
# one adapter at a time (this slice: slack).


class IntegrationKind(StrEnum):
    SLACK = "slack"  # post run outcomes to a Slack incoming webhook
    JIRA = "jira"  # push work items as issues (later slice)
    LINEAR = "linear"  # push work items as issues (later slice)
    GITLAB = "gitlab"  # clone / push / open merge requests (later slice)
    BITBUCKET = "bitbucket"  # clone / push / open pull requests (later slice)
