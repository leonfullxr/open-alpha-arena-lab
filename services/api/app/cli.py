from __future__ import annotations

import argparse
import getpass
import json
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app.core.auth import password_hash
from app.db.models import Competition, User
from app.db.session import SessionLocal
from app.services.demo import seed_demo
from app.services.reconciliation import reconcile_ledger


def main() -> None:
    parser = argparse.ArgumentParser(prog="arena")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="create/update local schema (production: run Alembic upgrade)")
    bootstrap = sub.add_parser("bootstrap-admin", help="create a local administrator interactively")
    bootstrap.add_argument("--username", required=True)
    seed = sub.add_parser("seed-demo", help="seed the deterministic offline replay")
    seed.add_argument("--rounds", type=int, default=20)
    run = sub.add_parser("run-demo", help="seed or reuse and print the persisted replay")
    run.add_argument("--rounds", type=int, default=20)
    reconcile = sub.add_parser("reconcile", help="compare account projections with the ledger")
    reconcile.add_argument("--competition-id")
    args = parser.parse_args()
    if args.command == "migrate":
        command.upgrade(Config("services/api/alembic.ini"), "head")
        print("database upgraded to latest Alembic revision")
    elif args.command == "bootstrap-admin":
        with SessionLocal() as db:
            if db.scalar(select(func.count()).select_from(User)):
                raise SystemExit("refusing bootstrap: a user already exists")
            first = getpass.getpass("Admin password: ")
            second = getpass.getpass("Confirm password: ")
            if len(first) < 14 or first != second:
                raise SystemExit("passwords must match and contain at least 14 characters")
            db.add(
                User(
                    id=str(uuid.uuid4()),
                    username=args.username,
                    password_hash=password_hash(first),
                    role="admin",
                )
            )
            db.commit()
        print("administrator created")
    elif args.command in {"seed-demo", "run-demo"}:
        with SessionLocal() as db:
            competition_id = seed_demo(db, args.rounds)
            comp = db.get(Competition, competition_id)
            print(
                json.dumps(
                    {
                        "competition_id": competition_id,
                        "name": comp.name if comp else None,
                        "state": comp.state if comp else None,
                        "source": "DEMO REPLAY",
                    },
                    sort_keys=True,
                )
            )
    elif args.command == "reconcile":
        with SessionLocal() as db:
            report = reconcile_ledger(db, competition_id=args.competition_id)
            print(
                json.dumps(
                    {
                        "competition_id": report.competition_id,
                        "accounts_checked": report.accounts_checked,
                        "journals_checked": report.journals_checked,
                        "balanced": report.balanced,
                        "mismatches": [
                            {
                                "account_id": mismatch.account_id,
                                "category": mismatch.category,
                                "expected": mismatch.expected,
                                "actual": mismatch.actual,
                                "delta": mismatch.delta,
                            }
                            for mismatch in report.mismatches
                        ],
                    },
                    sort_keys=True,
                )
            )
            if not report.balanced:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
