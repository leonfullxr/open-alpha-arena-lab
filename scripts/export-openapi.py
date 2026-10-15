from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))


def export() -> None:
    from app.main import admin_app, public_app

    contracts = ROOT / "contracts"
    contracts.mkdir(exist_ok=True)
    for filename, application in (
        ("public.openapi.json", public_app),
        ("admin.openapi.json", admin_app),
    ):
        target = contracts / filename
        target.write_text(
            json.dumps(application.openapi(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    export()
