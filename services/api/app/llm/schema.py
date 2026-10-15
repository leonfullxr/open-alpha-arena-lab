from __future__ import annotations

import json
import re
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ProposalAction(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_POSITION = "CLOSE_POSITION"
    HOLD = "HOLD"


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    action: ProposalAction
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
    quantity: Decimal = Field(ge=Decimal("0"), max_digits=38, decimal_places=18)
    leverage: Decimal = Field(gt=Decimal("0"), max_digits=8, decimal_places=4)
    stop_loss: Decimal | None = Field(
        default=None, gt=Decimal("0"), max_digits=38, decimal_places=18
    )
    take_profit: Decimal | None = Field(
        default=None, gt=Decimal("0"), max_digits=38, decimal_places=18
    )
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)
    invalidation: str = Field(min_length=1, max_length=500)
    justification: str = Field(min_length=1, max_length=500)


class ProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    proposals: tuple[Proposal, ...] = Field(min_length=1, max_length=6)


class ProposalOutputError(ValueError):
    """Provider returned visible text that does not match the public proposal schema."""


def parse_proposal_output(output: bytes) -> ProposalBatch:
    try:
        parsed: Any = json.loads(output, parse_float=Decimal, parse_int=Decimal)
        if isinstance(parsed, dict) and isinstance(parsed.get("proposals"), list):
            proposals = parsed["proposals"]
            for proposal in proposals:
                if isinstance(proposal, dict) and isinstance(proposal.get("action"), str):
                    proposal["action"] = ProposalAction(proposal["action"])
                if isinstance(proposal, dict):
                    for field in (
                        "quantity",
                        "leverage",
                        "stop_loss",
                        "take_profit",
                        "confidence",
                    ):
                        value = proposal.get(field)
                        if isinstance(value, str):
                            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
                                raise ValueError("invalid decimal string")
                            proposal[field] = Decimal(value)
            parsed["proposals"] = tuple(proposals)
        return ProposalBatch.model_validate(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise ProposalOutputError("invalid_proposal_output") from None
