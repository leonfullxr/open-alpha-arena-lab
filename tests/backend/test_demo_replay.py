from decimal import Decimal

from app.db.models import (
    Account,
    Base,
    Competition,
    EquitySample,
    InvocationAttempt,
    InvocationResult,
    LedgerPosting,
    MarketQuote,
    MarketSnapshot,
    Order,
    QuoteSet,
)
from app.services.demo import seed_demo
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


def test_demo_is_durable_idempotent_and_reproducible_after_engine_restart(tmp_path) -> None:
    path = tmp_path / "demo.sqlite3"
    url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        competition_id = seed_demo(db, 20)
        snapshot = list(
            db.scalars(
                select(EquitySample).order_by(EquitySample.account_id, EquitySample.round_index)
            )
        )
        first_values = [(row.account_id, row.round_index, str(row.equity)) for row in snapshot]
        assert len(first_values) == 42
        assert all(
            value == "10000.000000000000000000"
            for _, round_index, value in first_values
            if round_index == 0
        )
        assert all(row.equity > Decimal("0") for row in snapshot)
        assert db.scalar(select(func.count()).select_from(InvocationAttempt)) == 40
        assert db.scalar(select(func.count()).select_from(InvocationResult)) == 40
        assert db.scalar(select(func.count()).select_from(MarketSnapshot)) == 20
        assert db.scalar(select(func.count()).select_from(QuoteSet)) == 20
        assert db.scalar(select(func.count()).select_from(MarketQuote)) == 120
        assert db.scalar(select(func.count()).select_from(Order)) > 0
        assert db.scalar(select(func.count()).select_from(LedgerPosting)) > 0
        # Repeating the seed returns the existing replay without appending any rows.
        assert seed_demo(db, 20) == competition_id
        assert db.scalar(select(func.count()).select_from(EquitySample)) == 42
        original_leaderboard = [
            str(a.cash) for a in db.scalars(select(Account).order_by(Account.id))
        ]
    engine.dispose()

    restarted_engine = create_engine(url)
    restarted_factory = sessionmaker(restarted_engine, expire_on_commit=False)
    with restarted_factory() as db:
        competition = db.get(Competition, competition_id)
        persisted = list(
            db.scalars(
                select(EquitySample).order_by(EquitySample.account_id, EquitySample.round_index)
            )
        )
        assert competition is not None and competition.state == "FINISHED"
        assert competition.source_label.startswith("DEMO REPLAY")
        assert [
            (row.account_id, row.round_index, str(row.equity)) for row in persisted
        ] == first_values
        assert [
            str(a.cash) for a in db.scalars(select(Account).order_by(Account.id))
        ] == original_leaderboard
    restarted_engine.dispose()
