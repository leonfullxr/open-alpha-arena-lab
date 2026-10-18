from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    job_id: str
    account_id: str
    state: str
    accepted_proposals: int
    rejected_proposals: int
    protective_exits: int
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class ProtectionCycleReceipt:
    checked_accounts: int
    protective_exits: int
