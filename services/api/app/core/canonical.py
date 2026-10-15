import hashlib
import json
from decimal import Decimal
from typing import Any


def _validate(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("floats are forbidden in canonical evidence; use decimal strings")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be serialized")
        return str(value)
    if isinstance(value, dict):
        return {str(k): _validate(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_validate(v) for v in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _validate(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
