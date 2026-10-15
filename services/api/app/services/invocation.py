from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.models import (
    Competition,
    DecisionRound,
    DomainEvent,
    InvocationAttempt,
    InvocationResult,
    RoundAgentJob,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

_SAFE_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_PUBLIC_METADATA_KEYS = {"adapter", "finish_reason", "error_class", "status_code"}


@dataclass(frozen=True, slots=True)
class InvocationCompletion:
    output_bytes: bytes
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int | None = None
    error_code: str | None = None
    late: bool = False
    public_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationReceipt:
    result_id: str
    job_id: str
    accepted_for_execution: bool
    late: bool
    state: str


@dataclass(frozen=True, slots=True)
class PreparedDispatch:
    attempt_id: str
    job_id: str
    fence: int


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: str
    competition_id: str
    round_id: str
    agent_run_id: str
    snapshot_id: str
    fence: int
    lease_expires_at: datetime


def claim_next_job(db: Session, *, worker_name: str, lease_seconds: int = 30) -> ClaimedJob | None:
    """Claim the next eligible job with a monotonic fence and bounded lease.

    Provider I/O must happen after this transaction commits. The competition row is
    locked first, matching the global write lock order used by invocation completion.
    """
    if not worker_name or len(worker_name) > 80:
        raise ValueError("worker name must be 1..80 characters")
    if not 1 <= lease_seconds <= 60:
        raise ValueError("lease duration must be 1..60 seconds")
    with db.begin():
        now = db.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("database time is unavailable")
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        candidate = db.execute(
            select(RoundAgentJob.id, Competition.id)
            .join(DecisionRound, DecisionRound.id == RoundAgentJob.round_id)
            .join(Competition, Competition.id == DecisionRound.competition_id)
            .where(
                Competition.state == "RUNNING",
                Competition.kill_switch.is_(False),
                DecisionRound.deadline_at > now,
                (RoundAgentJob.state == "PENDING")
                | ((RoundAgentJob.state == "CLAIMED") & (RoundAgentJob.lease_expires_at <= now)),
            )
            .order_by(DecisionRound.logical_at, DecisionRound.round_index, RoundAgentJob.id)
            .limit(1)
        ).first()
        if candidate is None:
            return None
        job_id, competition_id = candidate
        competition = db.scalar(
            select(Competition)
            .where(Competition.id == competition_id)
            .with_for_update(of=Competition)
        )
        job = db.scalar(select(RoundAgentJob).where(RoundAgentJob.id == job_id).with_for_update())
        if competition is None or job is None:
            return None
        round_row = db.get(DecisionRound, job.round_id)
        if round_row is None:
            raise RuntimeError("job round is missing")
        # Recheck after both locks because another worker may have claimed this row.
        if (
            competition.state != "RUNNING"
            or competition.kill_switch
            or round_row.deadline_at <= now
            or not (
                job.state == "PENDING"
                or (
                    job.state == "CLAIMED"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at <= now
                )
            )
        ):
            return None
        job.state = "CLAIMED"
        job.fence += 1
        job.lease_owner = worker_name
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        db.flush()
        return ClaimedJob(
            job_id=job.id,
            competition_id=competition.id,
            round_id=round_row.id,
            agent_run_id=job.agent_run_id,
            snapshot_id=round_row.snapshot_id,
            fence=job.fence,
            lease_expires_at=job.lease_expires_at,
        )


def prepare_invocation_dispatch(
    db: Session,
    *,
    job_id: str,
    fence: int,
    provider: str,
    model: str,
    prompt_bytes: bytes,
    public_parameters: dict[str, Any],
) -> PreparedDispatch | None:
    """Persist exact safe input and commit DISPATCHING before the caller makes HTTP."""
    if not prompt_bytes:
        raise ValueError("prompt bytes are required")
    if any(
        not isinstance(key, str)
        or not isinstance(value, (str, int, bool, type(None)))
        or (isinstance(value, str) and len(value) > 160)
        for key, value in public_parameters.items()
    ):
        raise ValueError("provider parameters must be bounded safe scalars")
    with db.begin():
        competition_id = db.scalar(
            select(Competition.id)
            .join(DecisionRound, DecisionRound.competition_id == Competition.id)
            .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
            .where(RoundAgentJob.id == job_id)
            .with_for_update(of=Competition)
        )
        if competition_id is None:
            raise LookupError("job not found")
        job = db.scalar(select(RoundAgentJob).where(RoundAgentJob.id == job_id).with_for_update())
        if job is None:
            raise LookupError("job not found")
        round_row = db.get(DecisionRound, job.round_id)
        competition = db.get(Competition, competition_id)
        now = db.scalar(select(func.now()))
        if round_row is None or competition is None or now is None:
            raise RuntimeError("competition timing data is unavailable")
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if job.state != "CLAIMED" or job.fence != fence:
            raise ValueError("job claim or fence is no longer current")
        if job.lease_expires_at is None or job.lease_expires_at <= now:
            raise ValueError("job lease expired before dispatch")
        if round_row.deadline_at <= now:
            job.state = "TERMINAL"
            job.terminal_result = "PROVIDER_TIMEOUT"
            job.error_code = "NOT_DISPATCHED"
            return None
        if competition.state != "RUNNING" or competition.kill_switch:
            job.state = "TERMINAL"
            job.terminal_result = "SKIPPED_PAUSED"
            job.error_code = "COMPETITION_STOPPED"
            return None
        if db.scalar(select(InvocationAttempt.id).where(InvocationAttempt.job_id == job_id)):
            raise ValueError("job already has an inference attempt")
        attempt_id = str(uuid.uuid4())
        prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
        db.add(
            InvocationAttempt(
                id=attempt_id,
                job_id=job_id,
                prompt_bytes=prompt_bytes,
                prompt_sha256=prompt_hash,
                provider=provider,
                model=model,
                public_parameters=public_parameters,
                dispatched_at=now,
                fence=fence,
            )
        )
        job.state = "DISPATCHING"
        job.dispatched_at = now
        db.flush()
        return PreparedDispatch(attempt_id=attempt_id, job_id=job_id, fence=fence)


def _validate_completion(result: InvocationCompletion) -> str:
    if not isinstance(result.output_bytes, bytes):
        raise ValueError("provider output must be exact bytes")
    if result.latency_ms is not None and result.latency_ms < 0:
        raise ValueError("latency must be non-negative")
    if any(
        not isinstance(k, str) or not isinstance(v, int) or v < 0 for k, v in result.usage.items()
    ):
        raise ValueError("usage fields must be non-negative integer counts")
    if result.error_code is not None and not _SAFE_ERROR.fullmatch(result.error_code):
        raise ValueError("provider error must be a sanitized error code")
    allowed_values = (str, int, bool, type(None))
    if any(
        key not in _PUBLIC_METADATA_KEYS
        or not isinstance(value, allowed_values)
        or (isinstance(value, str) and len(value) > 120)
        for key, value in result.public_metadata.items()
    ):
        raise ValueError("public metadata must contain only scalar safe values")
    return hashlib.sha256(result.output_bytes).hexdigest()


def apply_invocation_result(
    db: Session, job_id: str, fence: int, result: InvocationCompletion
) -> InvocationReceipt:
    """Append one provider result and advance only its current, fenced DISPATCHING job.

    Lock order is competition then job. The provider call must already have returned; this
    function never performs network I/O. A result for an already terminal job is retained as
    late evidence and cannot become an executable response.
    """
    output_hash = _validate_completion(result)
    with db.begin():
        competition_id = db.scalar(
            select(Competition.id)
            .join(DecisionRound, DecisionRound.competition_id == Competition.id)
            .join(RoundAgentJob, RoundAgentJob.round_id == DecisionRound.id)
            .where(RoundAgentJob.id == job_id)
            .with_for_update(of=Competition)
        )
        if competition_id is None:
            raise LookupError("job not found")
        job = db.scalar(select(RoundAgentJob).where(RoundAgentJob.id == job_id).with_for_update())
        if job is None:
            raise LookupError("job not found")
        attempt = db.scalar(
            select(InvocationAttempt).where(InvocationAttempt.job_id == job_id).with_for_update()
        )
        if attempt is None:
            raise ValueError("job has no committed invocation attempt")
        existing = db.scalar(
            select(InvocationResult).where(InvocationResult.attempt_id == attempt.id)
        )
        if existing is not None:
            raise ValueError("invocation result already exists")

        now = db.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("database time is unavailable")
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        round_row = db.get(DecisionRound, job.round_id)
        if round_row is None:
            raise RuntimeError("job round is missing")
        lease_expired = job.lease_expires_at is None or job.lease_expires_at <= now
        deadline_expired = round_row.deadline_at <= now
        matching_dispatch = (
            job.fence == fence and attempt.fence == fence and job.state == "DISPATCHING"
        )
        accepted = (
            matching_dispatch and not lease_expired and not deadline_expired and not result.late
        )
        is_late = result.late or not accepted
        result_id = str(uuid.uuid4())
        db.add(
            InvocationResult(
                id=result_id,
                attempt_id=attempt.id,
                output_bytes=result.output_bytes,
                output_sha256=output_hash,
                latency_ms=result.latency_ms,
                usage=result.usage,
                error_code=result.error_code,
                late=is_late,
                public_metadata=result.public_metadata,
            )
        )
        if accepted:
            if result.error_code:
                job.state = "TERMINAL"
                job.terminal_result = (
                    "PROVIDER_TIMEOUT"
                    if result.error_code == "PROVIDER_TIMEOUT"
                    else "PROVIDER_ERROR"
                )
                job.error_code = result.error_code
                competition = db.get(Competition, competition_id)
                assert competition is not None
                competition.event_seq += 1
                db.add(
                    DomainEvent(
                        id=str(uuid.uuid4()),
                        competition_id=competition_id,
                        sequence=competition.event_seq,
                        account_id=None,
                        event_type="agent.error",
                        payload={"agent_id": job.agent_run_id, "reason": result.error_code},
                        event_at=datetime.now(UTC),
                    )
                )
            else:
                job.state = "RESPONDED"
        elif (
            matching_dispatch and job.state == "DISPATCHING" and (lease_expired or deadline_expired)
        ):
            job.state = "TERMINAL"
            job.terminal_result = "PROVIDER_TIMEOUT" if deadline_expired else "PROVIDER_ERROR"
            job.error_code = (
                "RESPONSE_DEADLINE_EXCEEDED" if deadline_expired else "DISPATCH_UNCERTAIN"
            )
        db.flush()
        return InvocationReceipt(
            result_id=result_id,
            job_id=job_id,
            accepted_for_execution=accepted and result.error_code is None,
            late=is_late,
            state=job.state,
        )
