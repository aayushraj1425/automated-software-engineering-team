"""Signed evaluation evidence: the only way an open source model joins auto selection.

A `ModelEntry.evaluated` flag is text an operator typed, so it certifies nothing.
Evidence is a results file written by `scripts/eval_open_model.py` after the model
passed the tool-call probes and every golden task for real. The file is signed with
a key derived from ENGINE_SERVICE_SECRET and bound to the model id, endpoint, golden
task definitions and probe definitions, so editing it or changing the tests
invalidates it. Design note: docs/architecture/agents/OPEN_SOURCE_MODELS.md.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from engine.config import Settings
from engine.llm.catalog import ModelEntry
from engine.llm.probes import PROBES, probes_digest

log = structlog.get_logger(__name__)

SCHEMA_VERSION = 1
# Everything passing proves engineer-level work. Senior and principal seats need
# stronger proof than this harness gathers today, so evidence never certifies more.
CERTIFIED_STRENGTH = 3
_SIGNING_CONTEXT = b"asep-model-evaluation-evidence-v1"


class TaskEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    planned: bool
    completed: bool
    committed: bool
    diff_matched: bool | None
    cost_usd: float = Field(ge=0)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.planned and self.completed and self.committed and self.diff_matched is True


class ProbeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str = ""


class EvaluationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    model_id: str
    endpoint_digest: str
    golden_digest: str
    probes_digest: str
    llm_fake: bool
    evaluated_at: datetime
    tasks: list[TaskEvidence]
    probes: list[ProbeEvidence]
    signature: str = ""


@dataclass(frozen=True)
class EvidenceStatus:
    """Whether a model may be auto selected, and a plain reason when it may not."""

    eligible: bool
    certified_strength: int
    reason: str


def golden_tasks() -> tuple[dict[str, Any], ...]:
    # Imported lazily: engine.evaluation pulls in the agent runner, which imports
    # the router, which imports this module.
    from engine.evaluation import GOLDEN_TASKS

    return GOLDEN_TASKS


def golden_tasks_digest() -> str:
    """Changes whenever the golden task prompts or expectations change."""
    payload = json.dumps(
        [(t["name"], t["request"], t["expect_in_diff"]) for t in golden_tasks()], sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def endpoint_digest(entry: ModelEntry) -> str:
    return hashlib.sha256(f"{entry.id}\n{entry.base_url or ''}".encode()).hexdigest()


def _signing_key(settings: Settings) -> bytes:
    return hmac.new(
        settings.engine_service_secret.encode(), _SIGNING_CONTEXT, hashlib.sha256
    ).digest()


def _signed_body(evidence: EvaluationEvidence) -> bytes:
    body = evidence.model_dump(mode="json", exclude={"signature"})
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def sign(evidence: EvaluationEvidence, settings: Settings) -> EvaluationEvidence:
    mac = hmac.new(_signing_key(settings), _signed_body(evidence), hashlib.sha256)
    return evidence.model_copy(update={"signature": mac.hexdigest()})


def build_evidence(
    entry: ModelEntry,
    tasks: list[TaskEvidence],
    probes: list[ProbeEvidence],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> EvaluationEvidence:
    """Signed results for one real evaluation run. Offline runs cannot certify."""
    if settings.llm_fake:
        raise ValueError("evaluation evidence cannot come from an offline LLM_FAKE run")
    return sign(
        EvaluationEvidence(
            schema_version=SCHEMA_VERSION,
            model_id=entry.id,
            endpoint_digest=endpoint_digest(entry),
            golden_digest=golden_tasks_digest(),
            probes_digest=probes_digest(),
            llm_fake=False,
            evaluated_at=now or datetime.now(UTC),
            tasks=tasks,
            probes=probes,
        ),
        settings,
    )


def evidence_path(settings: Settings, model_id: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", model_id)[:80]
    digest = hashlib.sha256(model_id.encode()).hexdigest()[:12]
    return Path(settings.model_evaluation_dir) / f"{slug}.{digest}.json"


def save_evidence(evidence: EvaluationEvidence, settings: Settings) -> Path:
    path = evidence_path(settings, evidence.model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    return path


def check_evidence(
    entry: ModelEntry,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> EvidenceStatus:
    """Verify the stored results for this entry. Never raises; reasons are plain text."""
    path = evidence_path(settings, entry.id)
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        evidence = EvaluationEvidence.model_validate(raw)
    except FileNotFoundError:
        return EvidenceStatus(False, 0, "no evaluation results yet; run scripts/eval_open_model.py")
    except (OSError, ValueError, ValidationError):
        return EvidenceStatus(False, 0, "evaluation results are unreadable")

    expected = hmac.new(_signing_key(settings), _signed_body(evidence), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, evidence.signature):
        return EvidenceStatus(False, 0, "evaluation results failed signature verification")
    if evidence.schema_version != SCHEMA_VERSION or evidence.model_id != entry.id:
        return EvidenceStatus(False, 0, "evaluation results are for a different model")
    if evidence.endpoint_digest != endpoint_digest(entry):
        return EvidenceStatus(False, 0, "the endpoint changed since evaluation; run it again")
    if evidence.llm_fake:
        return EvidenceStatus(False, 0, "evaluation results came from an offline run")
    if evidence.golden_digest != golden_tasks_digest() or evidence.probes_digest != probes_digest():
        return EvidenceStatus(False, 0, "the evaluation tests changed; run the evaluation again")
    current = now or datetime.now(UTC)
    age_limit = timedelta(days=settings.model_evaluation_max_age_days)
    if evidence.evaluated_at > current + timedelta(minutes=5):
        return EvidenceStatus(False, 0, "evaluation results are dated in the future")
    if current - evidence.evaluated_at > age_limit:
        return EvidenceStatus(False, 0, "evaluation results expired; run the evaluation again")

    if {t.name for t in evidence.tasks} != {t["name"] for t in golden_tasks()}:
        return EvidenceStatus(False, 0, "evaluation did not cover every golden task")
    failed = [t.name for t in evidence.tasks if not t.passed]
    if failed:
        return EvidenceStatus(False, 0, f"golden tasks failed: {', '.join(failed)}")
    if not evidence.probes or any(not p.passed for p in evidence.probes):
        return EvidenceStatus(False, 0, "tool call checks did not all pass")
    if {p.name for p in evidence.probes} != {p.name for p in PROBES}:
        return EvidenceStatus(False, 0, "evaluation did not cover every tool call check")
    return EvidenceStatus(True, CERTIFIED_STRENGTH, "passed tool call checks and golden tasks")


def effective_strength(entry: ModelEntry, settings: Settings) -> int:
    """The strength auto selection may rely on. Paid models keep their catalog value;
    open source models get at most what their evaluation results proved."""
    if not entry.needs_evaluation:
        return entry.strength
    status = check_evidence(entry, settings)
    return min(entry.strength, status.certified_strength) if status.eligible else 0
